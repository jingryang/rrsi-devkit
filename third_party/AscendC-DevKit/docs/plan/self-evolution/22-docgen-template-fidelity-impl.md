# P36 — docgen 详设说明书模板保真收口（L4 实施）

> 状态：待 L3 review 后实施　日期：2026-07-06　L3：`21-docgen-template-fidelity-analysis.md`（定案 Y，推翻 B）

## 改动（路径 Y）

### 0. 回滚方案 B 残留错改（先做）
- `design_substages.py` DocgenStage：md 名 `<op>_design_doc.md` → 恢复 `<op>_详细设计说明书.md`；_render title 同步恢复。
- `kernel/state.py`：design_doc 字段注释恢复。
- `ascendc-op-design-docgen/SKILL.md`：删「SE 手工参考、不调此 skill」定位块，恢复「LLM 按 v2.0 模板组装详设」本职。
- `ascendc-op-design-shared/references/checkpoint_convention.md`：`<op>_design_doc.md` → 恢复 `<op>_详细设计说明书.md`。
- 测试断言恢复「详细设计说明书」：`test_docgen_render.py`、`test_design_pipeline_e2e.py`。

### 1. 解 validation_report 寄生（前置耦合）
- `state` 增独立 `validation_report` 字段（与 design_doc 异质，不再寄生）。
- `ValidateStage.transition`：report 写独立字段，不再折叠进 design_doc。
- `ValidateStage.resolve_condition`：从独立字段读 report 路由。
- `DocgenStage.transition`：删 validation_report 保留逻辑。

### 2. 解 dd-intake short-circuit 耦合（前置耦合，最小处理）
- `DetailedDesignIntakeStage.transition`：不再调 `_render_detailed`；short-circuit 时 design_doc 指向外部文档路径（外部已有详设）。
- **范围限定**：仅让 dd-intake 在 design_doc 改路径后不崩；其既有问题（validate 契约缺口 + 转写职责错配 + 无 e2e）**不在 P36 修**，留 P37（增量开发优先级提升时补全）。

### 3. DocgenStage 改 LLM spawn
- `actions()`：返回 SpawnAgent（ascendc-op-design-docgen skill），输入中间产物 + 自带 doc_template_v2.0.md。
- `transition`：从 agent 产物读 md 路径存入 state.design_doc；agent 无 md 产物（重试耗尽）→ halt 转人工，不降级放行（文档关键、关系人的理解；halt 机制沿用 P35 `fail_strategy='halt'`，实施时确认）。
- 删 `_render_detailed`/`_render_concept`/`_persist_markdown`/`_render_kernel_pseudocode`/`skip_reason`（确定性渲染逻辑全删）。

### 4. SKILL.md 接线为工程通路
- 输入：design_spec/tiling_strategy/tiling_results/general_design/integration + 自带 doc_template_v2.0.md。
- 输出：`<op>_详细设计说明书.md`（v2.0 模板保真）+ checkpoint。

### 5. design_doc.json schema 处置
撤销聚合 json 后 schema 失消费者。已 grep 确认引用点：`test_design_schemas.py`（SchemaLoader 所有权映射）、`test_design_tui_selfclosure.py`（TUI ST）、`design_substages.py` field_map。删 schema 文件 + 三处引用（§1.4 不留兼容）。

### 6. concept render 处置
`_render_concept`（概要设计说明书）随确定性渲染逻辑一并删。SE workflow 不挂 docgen、full workflow 总走 detailed → concept 路径无触发场景。实施时再 grep 确认 SE 概设文档如何产出（是否另有机制）。

## 验证
- UT：`test_docgen_render`（改 LLM spawn 测试）、`test_detailed_design_intake`（short-circuit 改路径）、`test_design_substages`（validate routing 改独立字段）、`test_design_schemas`（删 design_doc.json schema）+ 全量回归。
- ST：`test_design_pipeline_e2e`；`test_design_tui_selfclosure`（heavy_llm，用户确认后跑）。
- 实施前 grep 复核：validation_report 所有读写点、_render_concept 消费者、SE 概设文档产出路径。

## 顺序
回滚（0）→ 解耦（1、2）→ DocgenStage 改造（3）+ SKILL 接线（4）→ schema 删除（5）→ concept 处置（6）→ 测试 + 全量回归。
