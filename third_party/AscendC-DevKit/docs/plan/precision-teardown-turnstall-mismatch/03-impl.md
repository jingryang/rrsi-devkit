# L4 实施方案 — teardown 只在循环真退出时触发（B 案）

> 对应 L3 B 案（用户 2026-08-27 认可）。

## 改动 1：调用位移（runner.py infra-retry 循环）

```python
_abort = getattr(_ares, "aborted", None)
if _is_cancelled() or not self._infra_backoff_retry(stage):
    if _abort:
        result_state = self._run_stage_teardown(stage, result_state, _abort)
    result["is_terminal"] = True
    break
self._check_timeout(stage.name)
actions = stage.actions(result_state, iteration)   # retry——不调 teardown
```

- 「resume ⇒ 绝不动代码」由调用位置构造性保证（retry 分支不可达 teardown）；
- 旧 D5 注释（「每次 kill 前触发一次，保证重采样从 known-good baseline 起步」）
  随位移删除——其前提（fresh 重采样）被 sidecar auto-resume（step-37）架空；
- 异常出口（`_check_timeout` 在退避后抛出）**故意**不触发 teardown：树保留给
  resume（记忆==树）；真 halt 的退出清洁由 converge 自身 checkout-to-best 兜底
  （下游权威点位，非新增兜底）。

## 验证（UT `tests/ut/orchestration/test_infra_backoff_resume.py`）

- `test_teardown_skipped_when_loop_resumes`：2 abort + ok → teardown **0 次**
  （99c4c0 发散形态的回归门）；
- `test_teardown_fires_once_at_terminal_exhaustion`：预算耗尽 → teardown 恰
  一次（最终 abort 上）；
- `test_teardown_not_called_on_timeout_raise_after_abort`：异常出口不触发
  （树保留语义 UT 固化）；
- 既有 `test_kernel.py TestStageTeardown` 两条更新为 terminal 语义
  （退避预算=0 使首个 abort 即退出）。

## 不做清单

1. 不加 `resuming` 参数/双钩子（A 案否决记录——约定式非构造式）；
2. 不动 `_infra_backoff_retry` 判定与 P116 halt 语义；
3. 不为「fresh re-spawn 失去 baseline」预建机制（演进前提记录于 L3 §3）。

## as-built（2026-08-27）

- 按改动 1 落地；与 step-95 同区域（with-block 内）无冲突。
- 全量 UT 3736 绿。有效性最终验证属下批真实跑：观测点 = turn_stall kill 后
  resume 的工作树一致性（session 记忆==树、无重做循环）。
