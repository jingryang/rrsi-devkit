# L4 — 实施方案：precision_debug 配置重构（candidate_loop 移除 + 三层配置 + 默认值调整）

> 层级：L4（具体改哪个函数/文件、什么顺序、怎么验证）。问题见 `01-problems.md`（Pc1-Pc3）。
> 无 L3——用户直接拍板（去冗余 + 三层 + 15/6/8），非探索式，对齐 [[precision-debug-closure-hardening]] step-71 跳过 L3 先例。

## 配置三层所有权（本次确立的不变式）

| 层 | 载体 | 谁写 | 谁读 |
|---|---|---|---|
| 全局 | `orchestration-config.json` 的 `precision_debug` 段（4 knob） | 人 | runtime_config accessor |
| per-run | `control.json` 顶级（同 4 knob） | `init-checkpoint.py` 首轮写（值来自全局 accessor 经 CLI 注入）；人可手改 | **所有 substage**（路由只读此层，不读全局） |
| 硬编码 | 模块常量（`_ABORT_EXHAUST_THRESHOLD=3` / `_DIAGNOSE_REFINE_MAX_CYCLES=3` / deploy_fail_streak≥3 / `999.0` 崩溃标记） | —— | **不变**（用户明确要求不改变硬编码参数） |

**不变式**：substage 路由只读 `control.json`，永不直接读全局配置 → 手改 control.json 即生效（per-run 优先）。首轮 control.json 的 4 knob = 全局 accessor 当前值（per-run 初始 = 全局）。

## 改动清单

### 改动 1 — runtime_config：4 knob loader（Pc2）
`src/ascendc_devkit/orchestration/runtime_config.py`：
- 删旧 `_load_time_budget` 单一 loader；新增 `_precision_knob(key, default)` 通用 loader（**读实时 `_RAW`**，镜像 `_load_timeouts`；section guard 移入函数；`_positive_int` 拒 bool/float/string/≤0）。
- 4 默认值常量：`_DEFAULT_PRECISION_MAX_ITERATIONS=15` / `_MAX_CORRECTIVE_CYCLES=6` / `_MAX_ATTEMPTS_PER_CASE=8` / `_TIME_BUDGET_S=12000`。
- 4 accessor：`precision_debug_max_iterations()` / `_max_corrective_cycles()` / `_max_attempts_per_case()` / `_time_budget_sec()`（末者名保留——首轮 init-checkpoint 的全局值来源）。

### 改动 2 — orchestration-config.json：precision_debug 顶级段（Pc2/Pc3）
`resources/orchestration-config.json`：新增顶级 `precision_debug` 段（4 knob：15/6/8/12000）；迁出旧 `timeouts.precision_debug_time_budget_sec`（4 knob 聚合到新段）。

### 改动 3 — init-checkpoint.py：4 参数 + 删 candidate_loop（Pc1/Pc2）
`.claude/skills/ascendc-precision-run-tests/scripts/init-checkpoint.py`：
- `init_control()` + argparse 新增 4 参数（默认 15/6/8/12000，自包含 §2.1）。
- control.json 顶级写 4 knob（per-run 层）；**删 candidate_loop 写入块**。

### 改动 4 — RunTestsSubstage：prompt 注入 4 全局默认（Pc2）
`precision_debug_substages.py`：
- `_common_context` 注入 4 accessor 值（`precision_max_iterations` 等）。
- `_phase_prompt` 的 init-checkpoint 命令带 `--max-iterations` 等 4 参数（从 ctx）——首轮 control.json 种子 = 全局值（per-run 初始 = 全局）。

### 改动 5 — substage 读取源改 control.json + 删 candidate_loop 框架引用（Pc1/Pc2）
`precision_debug_substages.py`：
- `_CONTROL_REQUIRED_KEYS` / `_CONTROL_DEFAULTS`：删 candidate_loop，加 4 knob + `best_passed_count` / `run_tests_start_ts` / `consecutive_aborts` / `bounds_check_*`。
- `_extract_debug_checkpoint`：`max_attempts_per_case` / `time_budget_sec` 读 control.json 顶级。
- `_time_budget_exhausted`：读 `dc.get("time_budget_sec", 12000)`（不再调 accessor）。
- `FixSubstage.transition`：`max_attempts = cp.get("max_attempts_per_case", 8)`（case 止损单值，所有 case 共享）。
- contract：candidate_loop 类型修复 → "剥离 legacy candidate_loop + 警告"（§2.5 恢复清理，不留旧债）。
- `_candidate_pool_exhausted`：纯 `len(pending)==0`（不变，本就如此——这是 Pc1 移除 candidate_loop 的前提）。

### 改动 6 — skill 文档清理（Pc1）
- `fix.md`：循环边界 `while pending_hits 非空:`（删 `and current_tried < max_plans`）；删 8 处 `current_tried += 1` / `tried_plan_ids.append`；删 candidate_loop 写入骨架；trim_level / 返回协议删 max_plans 引用；case 止损改述为框架 `max_attempts_per_case`。
- `fix/SKILL.md`（输入/输出表格 + 边界声明）+ `schema/precision_fix.json` description + 6 phase `_shared-protocol.md`（control.json 字段列表）+ diagnose/comment_bisect/printf prompt（"禁止写入"列表）+ run-tests SKILL.md：删 candidate_loop / current_tried / max_plans 引用。
- `build-failed-case-queue.py`：删 per-case `max_attempts_per_case: 10`（改 control.json 顶级单值，消除 per-case 与顶级不一致风险）。
- `update-checkpoint.py`：dead-fields 举例删 candidate_loop。
- run-tests SKILL.md：`timeouts.precision_debug_time_budget_sec` → `precision_debug.time_budget_sec`（config key 迁移同步）。

## 验证

- TDD：`test_runtime_config.py`（`TestPrecisionDebugKnobs`：4 knob 默认值 / 缺失回落 / 非法值 ConfigError / section 非对象）+ `test_precision_debug_stage.py`（`_control` / `_case` helper 删 candidate_loop / max_attempts；`TestCandidatePoolBudget` 改纯 pending 语义）。
- 同步清理另外 3 个 precision_debug test 文件的 `_control` helper 残留 candidate_loop（runtime_refine / per_output_sinking / agent_abort）。
- UT：`tests/ut/orchestration/` **1495 passed**；全量 `tests/ut/` **2830 passed / 8 skipped**（env-gated §3.7）零回归。
- heavy_llm 端到端 precision_debug 全流程（含 cann-bench 评测 best_commit 收敛）待用户决策（§3.11，PR 前关键节点）。
