# step-80 — docgen gate fail-forward + integrate 标量归一化 — L4 实施方案

> 性质：self-evolution 线 L4，step 80。修 P119（docgen gate halt 违背 fail-forward）+ P120（integrate 零标量归一化致非确定性提升）。
> 纪律：TDD（§3.1，每 slice 红→绿）；全覆盖（§3.2，UT 全绿）；符号级落点。
> 承接：P118（design gate 不 halt 系列）/ step-60（设计逃生，halt 仅 429）/ step-78（gate scope & ownership）。
> 触发：batch `20260728-134831-ccda3b/51d915` 卡死 docgen（epsilon 标量误杀）。

---

## 0. 实施总览

| slice | 内容 | 状态 |
|---|---|---|
| A | docgen gate `_error(halt)` → 写 `design_known_issues` + 放行（fail-forward） | ✅ |
| C | `_route_scalar_params` surgical 标量搬移 + 接入 IntegrateStage.transition（治根） | ✅ |
| D | gate `_opdef_missing_canonical_anchors` 认标量→Attr + 补 attrs 段检查 | ✅ |
| 配套 | design_spec schema example 加 attrs + integrate SKILL step2 加标量→attrs 指令 | ✅ |

A 是架构对齐（docgen 不该 halt，带问题前进）；C 是治根（标量确定归 attrs，未来算子不漂移）；D 让 advisory 信号准确；配套减少 LLM 漂移。

> **实施完成（2026-07-29）**：slice A/C/D + 配套全绿。UT 全量 **3170 passed / 7 skipped**（零连带回归）；即时逻辑验证 51d915 真实产物 `missing=[]`/不 halt。heavy_llm 51d915 重跑待用户确认（§3.11）。

---

## 1. slice A — docgen gate halt → advisory（fail-forward）

文件 `src/ascendc_devkit/orchestration/stages/design_substages.py::DocgenStage.transition`。

- `_opdef_missing_canonical_anchors` 发现 `missing` 时：原 `self._error(error_type="schema_violation")`（在继承的 `fail_strategy="halt"` 下 → halt 整算子）→ 改为构建 issue dict（`code=opdef_non_canonical`, `severity=warning`, `target=codegen`, `source=docgen`, `detail` 含"以 codegen def.cpp 编译产物为准"）+ append `design_known_issues`（按 source 分区：保留别 gate 的 carried issue，只替换 docgen 自己的切片——复用 `_set_known_issues`（`:1013-1025`）的分区语义，但内联实现，因 `DocgenStage` 非 `_DesignGate`、无 `blocking_issues()`）+ `_success_updates`（清 `last_error`/`pending_relocation`，放行 validate→codegen）。
- 检查逻辑**保留**（虚构 OpDef 信号以 known_issue 流到 codegen prompt + 人审，不丢可观测性），只去阻断。
- 更新上方注释（`Hard gate ... Halts → human` → `Hallucination backstop ... ADVISORY (fail-forward)`）。
- 依据：md 是 presentation 下游不消费（`DocgenStage` docstring + `ValidateStage.input_contract`）；codegen `def.cpp` 编译是权威 backstop（§2.9）；`design_tree.py:78-82` + `state.py:200-209` 明定 docgen 不 halt、ride forward。

## 2. slice C — integrate 标量归一化治根

新增模块级 `_is_scalar_param(item)` + `_route_scalar_params(design_spec)`（`design_substages.py`，`_REAL_SOCS` 前）。

- `_is_scalar_param`：`role=="attr" or (role!="tensor" and (shape == [] or format=="SCALAR"))`。
  - 扩展 `OperatorSpec._route`（`operator.py:104` 的 `"shape" not in e` 抓不住 `shape:[]`——epsilon 键存在）。
  - **不含"无 shape"**（避免误判 test fixture 的无 shape tensor，如 `_state()` 的 x / in-place key_cache）。
- `_route_scalar_params`：in-place 扫 `inputs`/`outputs`，标量项搬到 `attrs` **list**（dict 形态归一为 list；缺则建；idempotent——同名不重加）；保留 `semantic`/`note`/`description`；其他顶层键（platform/data_flow/templates/precision_thresholds…）不动（surgical，**不全量 OperatorSpec round-trip** 丢元数据）；返回 `moved` 列表。
- 接入 `IntegrateStage.transition`（`parsed, errors = parse(raw)` 后、构建 `updates` 前）；`moved` 非空时 `Logger.warn`（LLM 漂移可观测，§1.2 可诊断）。
- 配套：`schema/design_spec.json` 的 `example` 加 `attrs` 示例（`{name,type,default}`，给 LLM 正确目标；**不**加 `required_keys`——多数算子无 attrs）；`SKILL.md` step2 加 bullet"标量（空 shape/SCALAR/int|float|str 带 default）必须放 attrs"。

## 3. slice D — gate 输入形式覆盖

`_opdef_missing_canonical_anchors`：
- `inputs` 用 `_is_scalar_param` 分流（标量→期望 `Attr("<name>")`，tensor→`Input("<name>")`，原状）。
- `outputs` 维持 `Output("<name>")`（outputs 皆 tensor）。
- 新增 `attrs` 段检查（**list + dict** 两种形态）→ 每项期望 `Attr("<name>")`。
- `missing` 文案天然区分 `Attr(...)`/`Input(...)`（§1.2 可诊断）。
- 因 C 治根后标量都在 attrs，inputs 标量分支是**防御性**（漂移时 advisory 不误报）。

## 4. 测试（TDD，纯逻辑 UT §3.8）

- `tests/ut/orchestration/test_docgen_render.py::TestOpDefCanonicalGate`：
  - A：`test_hallucinated_opdef_records_known_issue` / `test_missing_each_anchor_records_known_issue`（参数化）/ `test_placeholder_soc_records_known_issue` / `test_inplace drop Output → known_issue` / `test_known_issue_does_not_clobber_other_sources`（source 分区）。**更新**原 halt 断言 → known_issue 断言。
  - D：`test_scalar_input_expects_attr_not_input` / `test_attrs_list_requires_attr_anchor` / `test_attrs_dict_form_checked`。
  - 回归：`test_canonical_opdef_passes` / `test_prose_only_doc_skips_gate` 行为不变。
- `tests/ut/orchestration/test_design_substages.py`：
  - C：`test_integrate_routes_scalar_from_inputs_to_attrs` / `_empty_shape_without_format` / `_attrs_dict_normalized_to_list` / `_tensor_not_routed` / `_preserves_other_toplevel_keys`。

## 5. 验证

- **即时逻辑（零 token）**：51d915 真实 `design_spec.json`（epsilon 在 inputs）→ `_route_scalar_params` 搬 epsilon 进 attrs（`moved=['inputs/epsilon']`）；真实 docgen md（`Attr("epsilon").Float(1e-6f)`）→ gate `missing=[]`（original 与 routed spec 均空）；`DocgenStage.transition` → `last_error=None`/`design_doc` 产出/0 known_issue（md 完整正确）。
- **UT 全量 3170 passed / 7 skipped**（198s），零连带回归。
- **heavy_llm 51d915 重跑（§3.11，待用户确认）**：A 使 docgen 不 halt → codegen。⚠️ 51d915 的 integrate 已 completed，resume 不重跑 integrate → 旧 design_spec（epsilon 在 inputs）不变；A（advisory）使其不 halt，codegen 如何处理 inputs 标量是后续观察点（codegen build gate 编译兜底）。**最干净的 C 治根端到端验证是下一新算子**（integrate 用新逻辑产 design_spec）。

## 6. scope 边界（不做）

- 不改 `OperatorSpec._route`（用扩展判据 surgical helper，不全量 round-trip 丢元数据）。
- 不改其他 design gate（P118 审视结论：review/anchor/validate 已对，只 docgen 违背）。
- 不改 codegen 对 inputs 标量的处理（若 51d915 重跑暴露，单独追）。
- 不加 attrs 到 design_spec `required_keys`（多数算子无 attrs）。
