# L4 — 实施方案：跨阶段结论接力文件（conclusions.json）

> 层级：L4（改哪个函数、什么顺序、怎么验证）。覆盖 L1 P8，设计依据 `02-analysis.md` 附录 A。
> 代码基线：branch `devA5Debug`。

## 目标

每个阶段把一段话结论写进共享 JSON，其他阶段开工前读它看到流程中所有已完成 agent 的结论。

## 改动总览

| # | 主题 | 关键文件 |
|---|---|---|
| 1 | 新模块 conclusions.py（路径 / 读取 / 物化） | `precision_debug_a5/conclusions.py` |
| 2 | 注入 `conclusions_path` + 基类 `_record_conclusion` | `precision_debug_a5/base.py` |
| 3 | 6 个 transition 各插一行物化调用 | `baseline.py` / `kernel_debug.py` / `vf_test.py` / `vector_error_debug.py` / `op_plugin_debug.py` / `regression.py` |
| 4 | 导出 helpers | `precision_debug_a5/__init__.py` |
| 5 | 6 个 skill result schema 加 `conclusion` 必填字段 | 6 个 `ascendc-precision-*/SKILL.md` |
| 6 | TDD 用例 | `test_precision_debug_a5_routing.py` |

## 改动 1 — conclusions.py（新模块）

- `_conclusions_path(state)`：`{debug_dir}/conclusions.json`。
- `_read_conclusions(state)`：读文件，坏 JSON → `{}`。
- `_materialize_conclusion(state, phase, round_num, phase_result)`：
  - 读 `phase_result["conclusion"]`；`None` 或空白 → Logger.warn + 不写（§1.2 可诊断）。
  - 追加 `{"round", "conclusion", "updated_at"}` 到 `phases[phase]`，保留轮次历史；
  - 原子写（read → merge → write）。

## 改动 2 — base.py

- `_common_context`：`conclusions_path` + `prior_conclusions` 加入 ctx（模块内 import `_conclusions_path`/`_format_conclusions_block` 避免循环依赖）。
- `_format_paths_block`：新增 `conclusions_path` 行，提示 agent 读取完整历史。
- `_build_prompt`：在 paths 块与 phase 块之间插入 `prior_conclusions` 块——**只携带上一个 agent（`conclusions.json` 的 `last`）的结论**，构造性可见（§2.9，不依赖 agent 自行 Read 文件）、且不膨胀携带更早历史；完整历史由 agent 从 `conclusions_path` 读文件。
- 基类新方法 `_record_conclusion(state, phase_result, round_num)`：调 `_materialize_conclusion`，作为框架唯一写入方。

## 改动 1 补充 — conclusions.py 的 `last` 追踪

`_materialize_conclusion` 除追加 `phases[phase]` 历史外，另维护 `data["last"] = {phase, round, conclusion, updated_at}`（最近一个完成的 agent）；`_format_conclusions_block` 只渲染 `last`。

## 改动 3 — 6 个 transition 各插一行

在 `_agent_return_abnormal` 校验通过之后、业务逻辑之前调用 `self._record_conclusion(state, phase_result, round_num)`。baseline 用固定 `round=0`（无 round 计数器，与 `_merge_best_snapshot(…, 0)` 一致）；其余阶段用各自的 `round_num`（`{stem}_round + 1`）。

## 改动 4 — 导出

`__init__.py` 导出 `_conclusions_path` / `_read_conclusions` / `_materialize_conclusion`（供测试与后续阶段使用）。

## 改动 5 — skill schema

6 个 skill 的 result JSON schema 均加 `conclusion`（必填，一段话字符串）+ 说明"框架会把它物化到 `{debug_dir}/conclusions.json`（`conclusions_path`），后续阶段开工前读它可见其他 agent 结论"。覆盖：baseline / kernel_debug / op_plugin_debug / vf_debug / vector_error_debug / regression。

## 改动 6 — TDD 用例

1. `test_phase_conclusion_materialized_to_relay`：op_plugin_debug 带 conclusion → 文件出现 `phases.op_plugin_debug[0]`。
2. `test_phase_conclusion_accumulates_across_rounds`：两轮 → `[1, 2]` 历史保留。
3. `test_phase_without_conclusion_skipped_not_blocking`：缺 conclusion → 不写 + 路由不受影响。
4. `test_baseline_conclusion_materialized_round_0`：baseline round=0。
5. `test_common_context_injects_conclusions_path`：ctx + paths 块注入。
6. `test_next_agent_prompt_includes_previous_agent_conclusion`：**上一 agent 结论在下一 agent prompt 中可见**（baseline→kernel_debug 链验证）。
7. `test_prompt_injection_bounded_to_previous_agent`：**注入有界**——baseline+op_plugin_debug 后，kernel_debug prompt 只含 op_plugin_debug（`last`）、不含 baseline；完整历史仍在文件里。

## 验证

- `test_precision_debug_a5_routing.py` 全绿（50 passed）。
- 回归：`test_precision_debug_stage.py` + `test_precision_debug_a5_source_safety.py` + `test_graph_executor.py` + `test_precision_debug_runtime_refine.py` 全绿（374 passed / 3 skipped，skip 为环境类）。
- 运行方式（本机 PYTHONPATH 被 batchrun workdir 遮蔽，须显式前置 src）：
  `PYTHONPATH=/root/workspace/AscendC-DevKit/src:$PYTHONPATH python -m pytest tests/ut/orchestration/test_precision_debug_a5_routing.py -q --no-env-check`
