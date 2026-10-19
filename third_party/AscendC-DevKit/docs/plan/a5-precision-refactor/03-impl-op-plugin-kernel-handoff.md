# L4 — 实施方案：op_plugin_debug 移交 kernel_debug（need_kernel_debug 出口）

> 层级：L4（改哪个函数、什么顺序、怎么验证）。覆盖 L1 P7，设计依据 `02-analysis.md` §3.6「新增 need_kernel_debug 出口」。
> 代码基线：branch `devA5Debug`。

## 目标

`op_plugin_debug` 现有三出口（converged→baseline / retry→自循环 / exhausted→escalate）过于死板：适配层排查确认非根因（或已修复）时，残余失败在 kernel/tiling 层却无诚实出口，只能 retry 烧轮次后 escalated 杀流程，或绕 baseline 全量重跑。新增 `need_kernel_debug` 出口直接移交 `kernel_debug` 做 per-case 调试。

## 改动总览

| # | 主题 | 关键文件 |
|---|---|---|
| 1 | 转移表加 `need_kernel_debug → kernel_debug` | `transition_table.py` |
| 2 | 已知状态集加 `need_kernel_debug`（防 invalid_status） | `base.py` `_KNOWN_STATUS_VALUES_BY_PHASE` |
| 3 | transition 处理移交 + queue 改标 + resolve_condition 路由 | `op_plugin_debug.py` |
| 4 | SKILL.md 加移交协议（判据 / kernel_cases / RETURN） | `ascendc-precision-op-plugin-debug/SKILL.md` |
| 5 | TDD 用例 | `test_precision_debug_a5_routing.py` |

## 改动 1 — 转移表（transition_table.py）

`_A5_TRANSITION_TABLE["op_plugin_debug"]` 增加：

```python
"need_kernel_debug": ("kernel_debug", "corrective"),
```

前向跳转（op_plugin_debug 在 children 索引 1 → kernel_debug 索引 2），`corrective` 计入 corrective 预算（`graph_executor` 对 forward 的 corrective 跳转直接 `i = target_idx`）。

## 改动 2 — 已知状态集（base.py）

`_KNOWN_STATUS_VALUES_BY_PHASE["op_plugin_debug"]` 追加 `"need_kernel_debug"`：
否则 `_validate_agent_return` 会判 agent 上报值为 `invalid_status` → 重试（§1.3 加载期校验）。

## 改动 3 — op_plugin_debug.py

**`transition`**（关键路径）：
- `status = phase_result.get("debug_status", "retry")` 提取一次；`history` 记录该 status。
- 轮次钳制改为**只钳 `retry`**：`if round_num >= max_op_plugin_rounds and status == "retry": status = "exhausted"`。`converged`/`need_kernel_debug` 是正向决策出口，不得被轮次上限误改 exhausted。
- `need_kernel_debug` 分支：
  - `self._apply_kernel_handoff(cp, phase_result)` 改标 queue；
  - `code_modified` → `_commit_candidate_phase`（适配层确有修改先落 candidate commit，避免移交后丢失；kernel_debug 修完的 baseline/regression 再推进高水位）。
- dc 注入：`debug_status`、`kernel_cases`、`_handoff_no_pending`（移交后无 pending case → resolve_condition 退化走 converged 回 baseline）。

**`_apply_kernel_handoff(cp, phase_result)`**（新 helper）：
- 有 `kernel_cases` 清单：命中 case → `error_layer="kernel"` + `status="pending"` + `attempt_count=0`；已 `error_layer=kernel` 的 case 保持 `pending`；其余纯适配层 case → `status="resolved"`。
- 无 `kernel_cases`（空/缺省）：全部 case 改标 kernel + pending（适配层全局判定正确）。
- `current_case_index` 指向第一个 `pending` case。

**`resolve_condition`**：`status == "need_kernel_debug"` → 若 `_handoff_no_pending` 返回 `"converged"`，否则返回 `"need_kernel_debug"`。

**`_phase_prompt`**：任务清单加第 8 步（移交判据），返回协议加 `OP_PLUGIN_NEED_KERNEL_DEBUG`。

## 改动 4 — SKILL.md

- description / 职责边界：加 kernel 层移交能力。
- Step 6 双跑验证后加 **Step 6.5 移交判定**：适配层全 pass + 传参无差异 + 残余失败 case RC 与 KL 都失败 → `debug_status=need_kernel_debug` + `kernel_cases`。判别要点：**仍有 RC fail + KL pass 的 case → 仍适配层问题，必须 retry**。
- result JSON：`debug_status` 枚举加 `need_kernel_debug`；新增 `kernel_cases` 数组字段（仅该状态必填）。
- RETURN 行 / Driver 状态机映射 / 死循环防护（轮次上限只钳 retry）同步更新。

## 改动 5 — TDD 用例（test_precision_debug_a5_routing.py）

新增 7 个用例（已实现并通过）：
1. `test_op_plugin_handoff_reroutes_kernel_cases`：移交改标 + `current_case_index=1` + 路由 `kernel_debug`。
2. `test_op_plugin_handoff_empty_kernel_cases_marks_all_kernel`：空清单 → 全 kernel。
3. `test_op_plugin_handoff_no_pending_falls_back_to_converged`：清单未命中 → 退化 converged。
4. `test_op_plugin_retry_clamped_to_exhausted_at_max_rounds`：轮次上限钳 retry。
5. `test_op_plugin_need_kernel_debug_not_clamped_at_max_rounds`：need_kernel_debug 不受钳。
6. `test_op_plugin_debug_known_status_values_include_handoff`：已知状态集含新值。
7. `test_op_plugin_debug_transition_table_has_need_kernel_debug`：转移表 wiring。

## 验证

- `test_precision_debug_a5_routing.py` 全绿（43 passed）。
- 回归：`test_precision_debug_stage.py` + `test_precision_debug_a5_source_safety.py` + `test_graph_executor.py` + `test_precision_debug_runtime_refine.py` 全绿（295 passed / 3 skipped，skip 为环境类）。
- 运行方式（本机 PYTHONPATH 被 batchrun workdir 遮蔽，须显式前置 src）：
  `PYTHONPATH=/root/workspace/AscendC-DevKit/src:$PYTHONPATH python -m pytest tests/ut/orchestration/test_precision_debug_a5_routing.py -q --no-env-check`
