# codegen manifest artifact-retry 耗尽 halt 信号被 runner 归一化抹掉（回归）

> L1 问题记录 + L4 实施记录（单一问题，两层合一片）。
> 发现路径：2026-08-22 全量默认 pytest 系统性验证，ST `test_manifest_missing_callable_target_routes_back` 失败。

## L1：哪里坏了？凭什么这么说？

`CodegenStage._artifact_retry` 的**耗尽分支**同时写 `last_error=ErrorFeedback(incomplete_output)`（halt 意图，docstring/WARN/message 三处明示 "halting/manual triage"）与**占位** `deploy_result=DeployResult(smoke_passed=False)`（保 schema 完整）。

runner 两条归一化都以「记错分支与交付产物互斥」为前提：

- **F6 收尾清错**（`bc871c85`，runner.py `_delivered → 清 own error`）：占位 deploy_result 使 has_all=True + 质量 True → _delivered=True → 把耗尽 halt 错误当"过时错误"抹掉。
- **R1 循环归一化**（`cda48ea8`，runner.py 456-473，artifact 类 + has_all → 清）：`incomplete_output` ∈ is_artifact_retry_error 可重试类 → 同样抹掉。

净效果：5 次定向 retry 耗尽后，stage 以 status=ok"成功交付"收场，halt 信号死在 runner——**预算耗尽冒充成功交付**（§1.10 一种错误冒充另一种；fail-open 框架里"halt 仅预算耗尽"，耗尽恰是唯一合法 halt 点却被吞）。

- 回归点：bisection 实证 `bc871c85` 引入（其父 `f1533e6f` 该 ST 仍过）；`cda48ea8` 后是第二条同样效果的通路。
- 既有 UT `test_artifact_retry_exhausted_halts` 只测 stage 层 transition 输出（不经 runner），没拦住——ST 才是 runner 层守护。

## L4：改动（窄修复，三处同键，不波及 codegen 其余 14 个 own-error 写点）

1. `_artifact_retry` 耗尽分支：`error_type` `incomplete_output` → **`exhausted`**（taxonomy 既有终态类：selffix 类 loopback 以 `exhausted→__halt__` 兜底；workflow transition 表已有 `"exhausted" → ("__halt__", "escalation")` 路由）。退出 `is_artifact_retry_error` 可重试类 → R1 两条通路（归一化清错 + 通用重试加倍预算）都自然不再命中。
2. `CodegenStage.is_satisfied` 覆写（窄 keyed：`stage_name=="codegen" ∧ error_type=="exhausted" ∧ details.reason=="manifest_non_conforming_exhausted"`）→ False：占位交付不算可接受 → F6 `_delivered` 不成立 → halt 错误保留。
3. `CodegenStage.stop_in_stage_retry` 同键 → True：耗尽后立即停（B3 机制），不再空烧 re-spawn 到 iteration 上限。

不变式归属（§1.15）：F6/R1 的「记错与交付互斥」单点不变式**保留不动**（修违反者，不修框架）；stage 侧以语义正确的错误类 + 窄覆写表达终态。

## 验证

- [x] ST `test_manifest_missing_callable_target_routes_back`：last_error=exhausted 存活到调用方 + `stage_iterations==5`（不空烧）+ `codegen_artifact_retries==5`
- [x] UT `test_artifact_retry_exhausted_halts`：error_type=exhausted + details.reason 键
- [x] test_stages / test_artifact_retry_common / test_self_evolution_stages / runner·workflow 相关 298 全绿
- [x] 全量默认 pytest（UT+非 heavy ST）3830 passed / 0 failed

## 附带发现（独立问题，待用户决策）

`src/ascendc_devkit/orchestration/artifact_recovery.py` **从未入库**（任何分支无历史），但 `codegen.py:6` 自 `cda48ea8` 起 import 它——干净检出/worktree/CI 必炸 `ModuleNotFoundError`（本次 bisection worktree 实证）。系该提交漏 `git add` 新文件。修法：单独补提交该文件。
