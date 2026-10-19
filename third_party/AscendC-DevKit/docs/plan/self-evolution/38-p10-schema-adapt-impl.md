# 38 — P10 根治：cannbench_adapt 确定性对齐 m.def schema 名（L4 实施方案）

> 工作线：self-evolution
> 状态：**已实施**（2026-07-12）
> 关联 L3：`38-p10-schema-adapt-analysis.md`
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md` 方案一

## 改动（函数级）

### `orchestration/stages/cannbench_adapt.py`
1. **模块头注释**（33-42）：声明 P10 后处理职责边界——agent 适配 glue files，P10 后处理修 m.def schema 名，两者正交；确定性 Python，不需 LLM；只改 m.def schema 字符串、不动 C++ 形参名/不动 kernel（torch 按 schema 名绑定）。
2. **`_extract_mdef_params(source) -> list[str]`**（71）：正则提取首个 `m.def("op(...)<params>) -> ...")` 的参数名序列（按位置有序）。如 `"swi_glu(Tensor x, int dim=-1)"` → `["x","dim"]`。无 m.def / 无参数返回 `[]`。只解析首个 m.def（一 plugin 一算子）。
3. **`rename_mdef_schema(source, old_names, new_names) -> str`**（114）：把 source 中首个 m.def schema 参数名按位置从 old 改为 new（只改 schema 字符串）。
4. **`transition()`**（215）：末尾调 `self._align_mdef_schema(state)`（243-245，独立于 agent_result——agent 适配 glue、P10 修 m.def，正交）。结果并入 `AdaptResult`：`schema_renamed=schema_renamed`、`adapted=len(files_modified)>0 or bool(schema_renamed)`（250/253）。rebuild 失败的 `last_error` 透传到 state（阻断 eval）。
5. **`_align_mdef_schema(state)`**（265-348）：P10 后处理主逻辑，返回 `(schema_renamed, rebuilt, errors, new_deploy, last_error)`：
   - 1. proto 基准：`state.requirement.op_spec.inputs[].name` + `op_spec.attrs.keys()`（`state.requirement_path` fallback 直接 `yaml.safe_load`）。无 proto → 安全跳过。
   - 2. 定位 m.def 源文件：`op_dir` 顶层优先，fallback `op_identity.op_dir`。
   - 3. 解析 m.def schema 参数名（`_extract_mdef_params`）。
   - 4. 参数数量不一致 → 记 error + 安全跳过（不强 rename，避免错位）。
   - 5. 比对 + rename（319-330）：`renamed = [(o,n) for o,n in zip(schema_names, proto_names) if o!=n]`；空则已对齐跳过；非空则 `rename_mdef_schema` 改写 + `plugin_path.write_text`。`schema_renamed=[{"from":o,"to":n}]`。
   - 6. rebuild opp（332-348）：`Deployer().deploy(state)`；`err is not None or not smoke_passed` → `last_error=ErrorFeedback(stage_name="cannbench_adapt", error_type="schema_adapt_failed", ...)` 返回（阻断 eval）；成功 → `new_deploy=deploy_result`。

### `domain/verification.py`
- **`AdaptResult.schema_renamed: list[dict]`**（78/87，§1.4 直接加字段不留兼容）：`field(default_factory=list)`，记 `[{"from":old,"to":new}, ...]`。

### `orchestration/stages/codegen.py`
- **`transition()` 加载期 warn**：解析 `codegen_manifest` 后，若 manifest 参数名 ≠ `state.requirement.op_spec` 名 → `Logger.warn`（**不自动改 manifest**——那是 codegen skill 职责；cannbench_adapt 后处理是兜底）。

## fail_strategy 语义

- glue 适配失败 → `continue`（现有，eval 能 fallback）。
- P10 rebuild/m.def 解析失败 → `last_error=ErrorFeedback(error_type="schema_adapt_failed")` + 阻断 eval（旧 opp 全 0 不能放行）。

## 验证（前台 pytest，§3.3/§3.8）

- **UT**（`tests/ut/orchestration/test_cannbench_adapt_schema.py`，18 用例）：fake `op_plugin/<op>_plugin.cpp` m.def + fake `state.requirement.op_spec`，断言 rename 正确性、rebuild 触发条件（m.def 一致时不调 subprocess）、`AdaptResult.schema_renamed` 记录、rebuild 失败阻断（`last_error=schema_adapt_failed`）。snapshot round-trip 模式。全绿。
- **回归**：全量 UT 1839 passed（含 18 新增），0 回归。
- **ST**（§3.9，非 heavy）：cannbench_adapt→eval 真实链路 stub 用例（codegen 产物 m.def 名故意错 → 后处理 rename + rebuild → eval 非 0）随非 heavy ST 94 passed。
- **heavy_llm**：P10 不依赖 LLM 全流程（确定性后处理），无 heavy_llm 用例。

## 诚实边界

- P10 后处理是「codegen→cann-bench 桥接层兜底」，非 codegen skill 根治——codegen 仍可能再生成错名（由 codegen `transition` warn 暴露）。若 warn 频繁，后续可强化 codegen skill 约束（L3 选项 A）。
