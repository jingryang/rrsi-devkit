# L1 — 问题记录：precision_debug 闭环 best_commit 选错 + 无墙钟预算 + 退出不收敛

> 层级：L1（客观事实，不提方案/不排顺序/不写决策）。方案见 `03-impl-best-commit-budget.md`。
> 触发 run：`20260721-010537-308ace`，算子 `ai_infra_aggregate_hidden_grad`
> （git 仓 `cann-bench/examples/aclnn_launch_example/csrc/ops/ai_infra_aggregate_hidden_grad`）。
> artifacts：`20260721-010537-308ace/artifacts/debug/ai_infra_aggregate_hidden_grad`。

## P1 — best_commit 选错：无条件 snapshot + 判据错（严重）

**事实**：precision_debug 每轮 run_test 后声称"保存效果最好的 commit"，但实际 best_commit 永远等于**最后一次** run_test 的 HEAD，而非通过用例最多的 commit。两处缺陷叠加：

1. `RunTestsSubstage.transition` 无条件调用 `_snapshot_best_commit`（把 best_commit 刷成当前 HEAD），完全忽略 `_update_best_metrics` 返回的"是否更好"信号。
2. best 的比较维度是 `(failed_count, crashed_count)` 字典序，不是用户诉求的"通过用例数（passed_count）"。passed_count 在闭环中**强非单调**，字典序判据无法稳定收敛到通过最多的那轮。

**证据**：
- 旧 `precision_debug_substages.py` transition：`_update_best_metrics(cp, run_result)` 后**无条件** `_snapshot_best_commit(cp, ...)`（best_commit = 最后一次 HEAD）。
- 旧 `_update_best_metrics`：`if new_failed != old_failed: better = new_failed < old_failed elif new_crashed ...`（字典序）。
- artifacts iter 序列（passed_count = total − failed）实测非单调：

  | iter | passed_count | 趋势 |
  |---|---|---|
  | iter-0 | 6/20 | 起点 |
  | iter-1 | 14/20 | ↑ |
  | iter-3 | 11/20 | **↓ 退步** |
  | iter-7 | 16/20 | ↑ |
  | iter-9 | 20/20 | 全过 |

  iter-1→iter-3 退步（14→11）正是病灶：无条件 snapshot 会把 best 刷成退步的 iter-3 HEAD。

**影响**：交付给 cann-bench 评测阶段的 commit 可能是通过用例较少（甚至退步）的那轮，而非通过最多的最优轮。

## P2 — 无墙钟预算（中等）

**事实**：precision_debug 闭环只有轮数上限 `max_iterations=30`（resolve_condition 的 `rounds > max → exhausted`），没有总墙钟预算。某轮 run_test/fix 卡住（长编译、慢用例）时，只能烧满 30 轮才退出。

**证据**：
- 旧 `resolve_condition`：唯一退出条件是 `status=="passed"` / `rounds > max_iterations` / scope_guard upstream；无任何时间判据。
- 旧 `_sync_debug_result` 的 terminal 判定同上，无时间维度。

**影响**：stuck loop 无法按总耗时收敛退出，浪费 NPU/LLM 资源且不保证停在最优 commit。

## P3 — 退出不收敛到 best_commit（严重）

**事实**：即使 best_commit 选对了，退出时 working tree 仍停在**最后一次 fix**（可能最差）的 HEAD。全链路无 `git checkout best_commit`。更关键：cann-bench 评测（cannbench_eval）读 `state.deploy_result`（已编译 opp 包），**不读 op_dir 源码**；cannbench_adapt 仅在 schema 偏离时才 rebuild opp。故仅回退源码对评测无效——评测仍编译并跑最差 commit 的包。

**证据**：
- `cannbench_eval.py:75` 附近：读 `state.deploy_result`（opp 包 `install_path`）。
- `cannbench_adapt.py:260` 附近：仅在 schema 偏离时 rebuild。
- 旧 `_sync_debug_result` terminal 分支：只物化 debug_result，无 rollback/redeploy 收敛。

**影响**：P1 修复（选对 best_commit）若无退出收敛，对 cann-bench 评测完全无效——交付的还是最差 commit 的包。

## P4 — 墙钟预算硬编码，不可配置（轻微）

**事实**：超时预算 `12000s` 写死在 `precision_debug_substages.py` 模块常量，无法在不改代码的情况下调整。项目既有约定（`resources/orchestration-config.json` 为调参单一权威源 + `runtime_config.py` loader 范式：hw_probe_sec / stage timeouts / iterations 等）未被遵循。

**证据**：
- 旧 `precision_debug_substages.py`：`_PRECISION_TIME_BUDGET_S = 12000`（硬编码）。
- `resources/orchestration-config.json` 已有 `timeouts` 段（`stages` / `hw_probe_sec`）。
- `runtime_config.py` 已有 `hw_probe_timeout_sec()` 等带默认值 + fail-fast 校验的 loader 范式。

**影响**：超时调优需改代码、走代码评审，与"调参集中配置"约定不符。

## P5 — codegen 产物不 commit → converge/teardown 的 clean -fd 误删（严重，根因）

**事实**：step-73（P3）加的 `_converge_to_best_commit` 与 `teardown` 都用 `RepoGuard.rollback`
（`git checkout <ref> -- op_dir` + `git clean -fd -- op_dir`），其安全性隐含假设 best_commit / HEAD
含全部 codegen 产物。但 codegen 成功路径**不 commit**（产物停留 op_dir 工作区 untracked），fix agent
只选择性 `git add <修改的文件>`（不收编 op_plugin/op_api 等注册文件），故 best_commit（= fix commit HEAD）
不含未被 fix 收编的 untracked codegen 文件。

**证据**：
- codegen 成功路径不 commit（产物另镜像 artifacts/）。
- fix agent `git add` 只加修改的文件（`ascendc-precision-fix/SKILL.md`）。
- `RepoGuard.rollback` 含 `git clean -fd -- op_dir`（`repo_guard.py`）。

**影响**：converge/teardown 的 `clean -fd` 删除未被 fix 收编的 codegen 文件 → 工作区残缺 → redeploy
残缺。这是 P3（退出收敛）安全性在 step-73 未触及的根因隐患。

## P6 — escalation + except 通道退出不 converge（严重）

**事实**：step-73 的 `_converge_to_best_commit` 只在 `_sync_debug_result` terminal 路径（轮数耗尽 / 墙钟超时）
调用。precision_debug 另两条退出路径未收敛：
1. **escalation 通道**（`graph_executor.py` `__escalate__` 分支，abort_exhausted/exhausted/deploy_broken）——
   只 bubble，不 converge，deploy_result 不指向 best_commit；
2. **except 通道**（架构超时 StageTimeoutError/WorkflowTimeoutError）—— 既有零覆盖。

**证据**：
- `graph_executor.py` `__escalate__` 分支（step-73 前）无 converge 调用。
- except 通道（step-73 前）无 converge 调用。
- cannbench_eval 读 `state.deploy_result`（编译包），不读 op_dir 源码（P3 已证）。

**影响**：escalation/except 退出时 deploy_result 停在最后（可能最差）fix 的包，cann-bench 评测错误 commit。
与 P3 同类（deploy_result 失真），但是不同退出路径的覆盖缺口。

## P7 — best_commit 缺失时 converge 直接 return（中等）

**事实**：`_converge_to_best_commit` 在 best_commit 缺失时 `return state`（不收敛）。init-checkpoint 失败 /
非 git 转 git 等边缘下 best_commit 可能缺失。

**证据**：
- step-73 `_converge_to_best_commit`：`if not best: return state`。

**影响**：边缘场景退出不收敛，deploy_result 失真（同 P3/P6 影响类）。入口 commit（P5 修复）后 best_commit
正常不空，本问题是边缘兜底缺失。

## P8 — teardown 用 git reset --hard 违 RepoGuard D4/R1（轻微）

**事实**：`_PrecisionDebugSubstage.teardown` 用 `subprocess.run(["git","reset","--hard",best], cwd=op_dir)`
回退——无 pathspec（整 worktree）、动 HEAD，违反 RepoGuard D4/R1（禁 whole-repo `reset --hard`）。

**证据**：
- step-73 teardown：`git reset --hard best`（无 pathspec）。
- RepoGuard D4/R1：scoped rollback（`checkout <ref> -- op_dir` + `clean -fd`，不动 HEAD）。

**影响**：teardown 回退语义与 converge（step-73 改动3 用 RepoGuard.rollback）不一致，且 reset --hard 动 HEAD
有副作用（precision_debug resume 从工作区+control.json 开始不读 git 线性历史，故 HEAD 是否回 best 不影响
正确性，但违 RepoGuard 规约）。

## 关联问题

- [[precision-debug-loop-control]] 闭环收敛治理（corrective_cycles / max_iterations）。
- [[printf-selfclose-fix]] printf→fix 上下文丢失（同闭环不同病灶）。
- [[self-evolution]] step 14/15（self-evolve pipeline 死锁 + run 机制，precision_debug 是其中一环）。
