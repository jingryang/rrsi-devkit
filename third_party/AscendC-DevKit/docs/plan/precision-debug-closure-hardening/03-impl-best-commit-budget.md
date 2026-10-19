# L4 — 实施方案：passed_count 计数 + 墙钟预算 + 退出收敛 + 配置化

> 层级：L4（改哪个函数、什么顺序、怎么验证）。覆盖 L1 P1-P4。
> 设计依据：用户三点诉求（计通过用例数 + 严格大于才更新 + 12000s 预算退出收敛）+ 路由确认（self_evolve_op 超时→exhausted→cannbench_adapt→cannbench_eval）+ 配置化（P4）。

## 改动总览

| # | 主题 | 覆盖 | 关键文件 |
|---|---|---|---|
| 1 | passed_count 计数 + 严格大于更新 | P1 | `precision_debug_substages.py` |
| 2 | 12000s 墙钟预算 + 超时→exhausted | P2 | 同上 + `runtime_config.py` |
| 3 | 退出收敛到 best_commit（rollback + redeploy） | P3 | 同上 |
| 4 | 字段/文档同步 | P1/P2 | `verification.py` / `init-checkpoint.py` / `SKILL.md` |
| 5 | 预算配置化 | P4 | `orchestration-config.json` / `runtime_config.py` / `precision_debug_substages.py` |

## 改动 1 — passed_count 计数 + 严格大于更新（P1 核心）

**数据来源**：`passed_count = total_count − failed_count`；`total_count` 来自 run_test agent 写的 `_summary.total_count`（skill 契约强制）；`failed_count = len(failed_case_queue)`。

**`_update_best_metrics(cp, run_result) -> bool`**（重写，§1.4 直接改干净不留旧字典序判据）：
- 比较 = `passed_count` **严格大于**（`new_passed > old_passed`）。
- 首次（`best_passed_count is None`）→ 总是记录并返回 True（初始化最优 commit）。
- 相等 → False；退步（更小）→ False（保留更早最优，防越改越差）。
- `failed_count`/`crashed_count`/`real_max_err` 仍记录（观测），不参与比较。

**`RunTestsSubstage.transition` 正常分支**：
- 算 `passed_count = max(0, total − failed)`。
- 首次 run_test 写 `cp["run_tests_start_ts"] = time.time()`（改动 2 计时）。
- `run_result` 增加 `passed_count` 字段。
- **条件 snapshot**：`if _update_best_metrics(cp, run_result): _snapshot_best_commit(...)`（仅严格大于才更新 best_commit）。

## 改动 2 — 12000s 墙钟预算 + 超时退出（P2）

**`_time_budget_exhausted(dc) -> bool`** helper（resolve_condition 与 _sync_debug_result 共用，保证一致）：
- `start = dc.get("run_tests_start_ts")`；`start is None` → False（未初始化）。
- 否则 `(time.time() − start) > precision_debug_time_budget_sec()`。
- `is None` 判定（非 `bool()`）——区分"未初始化"与合法时间戳（`bool(0.0)` 会误判 epoch 为未初始化）。

**`resolve_condition`**：`rounds > max_iterations → exhausted` 之后加 `if _time_budget_exhausted(dc): return "exhausted"`（复用既有退出路由，不动 transition_table）。

**`_sync_debug_result`**：terminal 追加 `or _time_budget_exhausted(dc)`，使超时也触发终态物化 + 收敛（改动 3）。

> 边界：超时是软预算——某次 run_test 执行中越过预算，框架无法硬中断，等其完成后下个 transition 检查并退出。可接受。

## 改动 3 — 退出收敛到 best_commit（rollback + redeploy）（P3）

**关键事实**：cannbench_eval 读 `state.deploy_result`（编译包），不读 op_dir 源码；cannbench_adapt 仅 schema 偏离才 rebuild。故**必须 rollback 源码 + 重新 deploy 更新 deploy_result**，仅回退源码无效。

**`_converge_to_best_commit(state, dc) -> State`**（新增，`_sync_debug_result` terminal 分支内、`return state` 前调用）：
- `status == "passed"` → 跳过（HEAD 已最优且已 deploy）。
- `best_commit` 缺失 / `op_identity` 缺失 → 跳过。
- `best_commit == git rev-parse HEAD` → 跳过（已是当前）。
- 否则：
  1. `RepoGuard().rollback(repo_root, op_dir, best_commit)` — scoped `git checkout <ref> -- op_dir` + `git clean -fd op_dir`（不动 HEAD、不 `reset --hard`，D4/R1）。
  2. `new_deploy, err = Deployer().deploy(state)` — 重新编译 best_commit 源码成 opp 包（纯数据 in/out，复用 precision_debug agent 同一 deploy 链）。
  3. `new_deploy.smoke_passed` → `state.with_updates(deploy_result=new_deploy)`；否则保留旧包 + `Logger.error`（best_commit 历史上 deploy 过，重编应成功；失败不阻断 eval，降级用旧包并告警）。

覆盖两条退出路径：轮数耗尽 + 时间预算超时。`passed` 不收敛；`upstream` 不覆盖（首轮上游 halt，best=initial 无意义）。

## 改动 4 — 字段/文档同步（P1/P2 观测）

- `PrecisionDebugResult`（`domain/verification.py`）：加 `best_passed_count: int = -1`（补偿 scoped 不动 HEAD 的可观测性）；`_sync_debug_result` 从 dc 填充。
- `_extract_debug_checkpoint`：白名单加 `best_passed_count` / `run_tests_start_ts`（否则写进 control.json 后下轮 dc 取不到 → 超时 helper 永远 None → 超时不触发）。
- `RunTestsSubstage.transition`：cp 变更后镜像 `dc["best_passed_count"]`/`dc["run_tests_start_ts"]`/`dc["best_commit"]`（dc 在入口提取、早于 cp 变更，镜像使同轮 resolve/sync 见到新值）。
- `_CONTROL_DEFAULTS` / `init-checkpoint.py`：seed `best_passed_count=None` / `run_tests_start_ts=None`。
- `ascendc-precision-run-tests/SKILL.md`：best_* 判据改为 passed_count 严格大于 + 预算说明。

## 改动 5 — 预算配置化（P4）

- `resources/orchestration-config.json` `timeouts` 段加 `precision_debug_time_budget_sec: 12000`（+ `_comment`）。
- `runtime_config.py`：`_DEFAULT_PRECISION_DEBUG_TIME_BUDGET_S=12000` + `_load_precision_debug_time_budget()`（MISSING→默认；present-but-invalid→ConfigError；`_positive_int` 校验拒 bool/float/string/≤0）+ 模块常量 `PRECISION_DEBUG_TIME_BUDGET_S` + `precision_debug_time_budget_sec()` accessor（镜像 `hw_probe_timeout_sec()` 范式）。
- `precision_debug_substages.py`：删硬编码 `_PRECISION_TIME_BUDGET_S`，`_time_budget_exhausted` 改调 `precision_debug_time_budget_sec()`；顶层 import runtime_config。

## 复用（不新造）

- `RepoGuard.rollback`（scoped 收敛，dispatcher/codegen 已用）
- `_snapshot_best_commit` / `_operator_dir`（既有）
- `Deployer.deploy`（纯数据 in/out deploy 链）
- runtime_config loader 范式（hw_probe_timeout_sec）
- UT 真git范式：`test_plan_a_inrepo.py` `_init_git_repo`/`_has_git`

## 验证（TDD，§3.1；前台跑，§3.3）

`tests/ut/orchestration/test_precision_debug_stage.py`：
- `TestBestMetrics`（重写）：首次初始化 / 严格大于更新 / 退步不动 / 相等不动 / 非单调序列 6→14→11→16→20 → best_passed_count 单调不减 `[6,14,14,16,20]`。
- `TestPassedCountAndTimeBudget`：`_time_budget_helper_boundaries`（边界相对配置预算）；transition 算 passed_count + 首次计时；resolve 超时→exhausted / 未超→has_failures；`_sync_debug_result` 超时 terminal + best_passed_count 透出。
- `TestConvergeToBestCommit`（真git，`_has_git` skip 守卫，monkeypatch `_FakeDeployer`）：rollback+redeploy / passed 不收敛 / best==HEAD 跳过 / redeploy smoke 失败保留旧包。

`tests/ut/orchestration/test_runtime_config.py`：`TestPrecisionDebugTimeBudget`（缺失→默认 / 非法→ConfigError / shipped config 12000 + getter）。

**结果**：`test_runtime_config.py` + `test_precision_debug_stage.py` 共 195 passed；全量 `tests/ut/` **2830 passed, 8 skipped**（env-gated §3.7），0 回归。

> heavy_llm：端到端 precision_debug 全链路 ST 属 `heavy_llm`（§3.11）——不默认跑，由用户在关键节点（PR 前）决策跑一次。
