# L4 实施方案 — refine_cycles 主动路径计数 + abort 熔断路由 run_tests

> 层约定：L4 记录改哪个函数、什么顺序、怎么验证。本文为 as-built 记录（commit `6c92e7f5` + B1 修复 commit）。

## §1 refine_cycles 主动路径计数（commit 6c92e7f5）

| 改动 | 位置 | 内容 |
|---|---|---|
| 主动标记置位 | `precision_debug_substages.py` FixSubstage.transition | `applied_partial` 为真时 `cp["refine_pending"] = True` |
| 消费式计数 | `DiagnoseRefineSubstage.transition` | `if cp.pop("refine_pending", False): refine_cycles += 1`；被动落点不计数 |
| 链满路由 | `DiagnoseRefineSubstage.resolve_condition` | `refine_cycles > 3` → `"refine_done"`（原 `"exhausted"`） |
| 转移表 | `precision_debug_tree.py` | `diagnose_refine.refine_done → ("run_tests", "linear")` |
| 清零 | RunTestsSubstage.transition 正常路径 + abort 分支 | `cp["refine_cycles"] = 0`（§P2-refine，同 corrective_cycles） |

## §2 abort 熔断路由（commit 6c92e7f5）

| 改动 | 位置 | 内容 |
|---|---|---|
| 阈值 | `precision_debug_substages.py` | `_ABORT_EXHAUST_THRESHOLD = 3 → 2` |
| 触发清零 | `_handle_abort` | bump 后 `n ≥ 阈值` → `cp["consecutive_aborts"] = 0`（dc 覆盖回触发值 `n` 供 `_resolve_abort_condition` 判定） |
| 转移表 | `precision_debug_tree.py` | 6 阶段（diagnose/fix/diagnose_refine/printf_location/comment_bisect/bounds_check）`abort_exhausted → ("run_tests", "linear")`；run_tests/scope_guard 保持 escalate |

## §3 B1 修复（review 后 commit）

| 改动 | 位置 | 内容 |
|---|---|---|
| 置位落盘 | `precision_debug_substages.py` FixSubstage.transition | `refine_pending` 置位后紧跟 `_save_control(state, cp)`（防 `_append_history` 磁盘重载丢标记） |
| 跨阶段测试 | `test_precision_debug_runtime_refine.py` | `test_fix_applied_partial_persists_refine_pending`（fix 生产端 → control.json 断言落盘）+ `test_fix_non_applied_partial_does_not_set_pending` |

## §4 验证

- TDD：跨阶段测试先红（`refine_pending` 未落盘）→ 补 save → 绿。
- UT 全量：`python -m pytest tests/ut -q` → 全绿（本次修复后重跑确认）。
- 新增用例覆盖：abort 阈值=2、熔断路由 run_tests（6 阶段参数化）、触发清零、refine 被动不计数、refine_done 路由、run_tests 双清零、跨阶段落盘。

## §5 未做（如实记录）

- abort 阈值配置化（保持常量 2；若需 per-run 调参，镜像 `precision_debug_max_corrective` 模式加 `precision_debug.max_abort_threshold`）。
- ST 全量未跑（相关链路为 heavy_llm 类，待用户确认后执行）。
