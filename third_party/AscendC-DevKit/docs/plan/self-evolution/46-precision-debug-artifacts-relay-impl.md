# 42 — precision_debug artifacts-relay bug 根治（L4 实施方案）

> 工作线：self-evolution
> 状态：**已实施**（2026-07-13）；UT 1889 全绿，ST 非 heavy 102 passed（0 回归，1 heavy_llm codegen deselect §3.11）
> 关联 L3：`46-precision-debug-artifacts-relay-analysis.md`
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md`

## 改动（函数级）

### `orchestration/stages/precision_debug.py`

1. **`transition` 改读源**（225-273 行）：`dr_content` 来源从 SDK `agent_result.artifacts` dict → `<op_dir>/debug_result.json` 文件。
   ```python
   op_dir = state.op_dir or (state.op_identity.op_dir
                             if state.op_identity else None)
   checked_path = (op_dir / "debug_result.json") if op_dir is not None else None
   dr_content = None
   if checked_path is not None and checked_path.exists():
       try:
           dr_content = checked_path.read_text(encoding="utf-8")
       except OSError:
           dr_content = None
   ```
   - `op_dir` 解析对齐 P66/24d989f 的 spawn `working_dir` 兜底链（`state.op_dir` 优先，`op_identity.op_dir` 次之），transition 读源与 spawn cwd 同一兜底，不漂移。
   - `state.op_dir` 类型 = `Path`（state.py:63），`op_dir / "debug_result.json"` 直接可用。
   - **删** `if hasattr(agent_result, "artifacts") and agent_result.artifacts: dr_content = agent_result.artifacts.get("debug_result.json")`（SDK dict 死读，§2.5）。
   - `agent_result is None` 早返回保留（229-231）——「agent 根本没跑」guard，与读源无关。

2. **parse 逻辑不变**（238-260）：`json.loads` → `PrecisionDebugResult(...)` 构造完全不动。

3. **else 分支 message 加诊断路径**（§1.2 可诊断）：
   ```python
   if checked_path is not None:
       msg = f"agent 未产出 debug_result.json（期望路径: {checked_path}）"
   else:
       msg = "agent 未产出 debug_result.json（op_dir 与 op_identity.op_dir 均未设）"
   ```
   原 message 空泛「agent 未产出 debug_result.json」无法定位；现在含期望路径，「agent 跑了但忘写/写错位置」一眼可见。

4. **docstring/prompt 措辞对齐**（§1.2 可维护）：
   - 模块 docstring（11 行）+ transition docstring（226 行）：「from agent artifacts」→「from the op_dir file-relay（§2.3）」，并记单通路「每 stage 各守其 agent 产出机制」。
   - prompt（220 行）：「写 debug_result.json 到工作目录 artifacts」→「到 operator_dir（= 你的工作目录 cwd）」，对齐 skill `write-debug-result.py:28` 实际契约。

## 不改（关键边界）

- **parse 逻辑 / routing / fail_strategy=halt / _max_rounds**——只换读源。
- **skill 侧**（`write-debug-result.py` / SKILL.md / main-loop.md）——写入契约 `<operator_dir>/debug_result.json` 已正确（§2.1 不动 skill）。
- **SDK artifacts 机制全局**——codegen/perf/requirement 读 dict 是对的，不动。

## 实施顺序（TDD，§3.1）

1. `tests/ut/orchestration/test_precision_debug_stage.py`：
   - 新增 `_dr_path(state)` / `_write_debug_result(state, payload)` helper；`_agent_result()` 简化为 bare AgentResult（artifacts 空，transition 不再读）。
   - 改 3 现有 UT（`test_transition_passed_advances` / `failed_exhausted` / `best_commit_recorded`）：塞 dict → 写文件到 op_dir。
   - 改 `test_transition_no_debug_result_json_incomplete`：断言 message 含期望路径。
   - 改 `test_transition_malformed_json_incomplete`：坏 JSON 写到文件（非塞 dict）。
   - 新增 3 回归守卫：`test_transition_reads_op_dir_file_ignores_sdk_artifacts`（**事实9 防复发核心**：op_dir 写真值 + SDK dict 塞矛盾假值 → 断言读文件）/ `test_transition_falls_back_to_op_identity_op_dir`（对齐 P66 兜底链）/ `test_transition_no_op_dir_incomplete`（均未设 → message 含「均未设」）。
   - 先红（当前 transition 读 dict，新测试写文件 → 失败）。
2. 改 `precision_debug.py:transition` + 措辞 → 绿。
3. 全量回归。

## 验证

- **UT**：全量 **1889 passed**（本文件 19：原 16 + 3 新守卫），零失败、零回归。
- **ST（非 heavy，§3.6）**：**102 passed, 5 skipped, 1 deselected**，0 failed。1 deselected = `test_smoke.py::TestCodegenStageEndToEnd::test_full_pipeline`（heavy_llm codegen，§3.11 不默认跑）；5 skipped = test_npu 预存 NPU 子用例（与本方案正交）。`test_resume_cli.py ..`（task #21 修复稳固）、`test_self_evolution_stages.py` 全过（stage wiring 完好）。
- **heavy_llm（§3.11）**：本改动不改 LLM 链路（只换 transition 读源，agent 行为不变）。端到端「precision-debug 写文件 → transition 读到 → 不冤杀」验证属 heavy_llm，**未跑**（待用户决策）。**本次未覆盖 heavy_llm：precision_debug 文件接力端到端**（诚实记录，§3.11）。
