# P36 — docgen 详设说明书模板保真收口（L3）

> 状态：已定案（选 Y，2026-07-06，推翻 B）　创建：2026-07-05　L1：`06-problems.md` P36；上承 `15` §3.4

## 议题

docgen 产物不达 v2.0 模板保真（确定性 dump JSON）+ design_doc.json 无文档消费者 + skill 通路未接线。前置决策：design_doc.json 该不该存在？md 如何达模板保真？

## 选项

- **X**：保留 design_doc.json 作 md 桥梁——确定性聚合 json → LLM 转 md。代价：双源真相（聚合 json 与 design_spec 同步）、两层映射（Python 渲染 json + LLM 渲染 md）、json 仍无机器消费者孤悬。违反 §2.5/§2.7。
- **Y（选）**：撤销 design_doc.json；md 由 LLM 直接从中间产物 + v2.0 模板生成（接线 skill）；`state.design_doc` 存 md 路径。
- ~~B~~（已推翻）：design_doc 降结构化索引 + skill 降 SE 手工参考 + 产物改名。方向反了——B 处置「md 无意义 dump」，正解是让 md 达模板保真（LLM 生成）+ 撤销聚合 json（而非降级保留）。

## 定案 Y 理由

1. **唯一消费者悖论**：design_doc.json 无机器消费者——validate 核中间产物（P20）、codegen 消费 design_spec/tiling_strategy、design group 对外契约不含 design_doc。唯一潜在消费者是 md 生成本身；为 md 前置中间态单独维护聚合 json + schema + 同步规则 = 双源真相（§2.5）。
2. **模块化优于聚合**：codegen/validate 直接消费单一职责的上游 json，schema 权威、无翻译误差；聚合 json 是冗余搬运、零信息增量。
3. **md 是呈现、呈现归 LLM（§2.7）**：md 价值在 mermaid/文字/模板格式，是呈现非事实；确定性聚合 json 再转 md 是两层映射，属非核心内容固化进 Python。
4. **当前不保真根因正是确定性 dump**：接入 LLM 即可直接按 section_mapping 组装，聚合 json 失去存在理由。

## 关键决策点

- **`state.design_doc` 存 md 路径**（非 markdown 内容、非 json）：预留消费者锚点，未来新增 stage 从 state 取路径消费；不挂 gate、不阻塞主链路（§1.2 可扩展）。
- **md 生成失败 halt**：md 关系人的理解、是关键交付件，docgen 生成失败（重试耗尽）halt 转人工 triage，不降级放行空/坏文档（§1.2 可诊断）。注：halt 在 docgen 自身质量门，与「`state.design_doc` 存路径不阻塞下游」不矛盾——后者指 design_doc 字段内容不被 validate/codegen 消费。
- **串行生成**（integrate 之后）：用户接受当前串行；并行（json 后并行生成 md）框架处理强杀/Ctrl+C 复杂，暂缓。

## 实施前置：两处寄生耦合须先解耦

grep 暴露 design_doc 当前被两处寄生，改造 DocgenStage 前必须先解，否则路由/短路机制断：

1. **validation_report 寄生于 `state.design_doc` 字段**：ValidateStage.transition 把 validation_report 折叠进 design_doc、resolve_condition 从 design_doc 读 report 路由（redo_doc/redo_tiling/human）。design_doc 改存 md 路径后 report 无处寄生。
   - 解耦取向：validation_report 剥离为独立 state 字段（它与 design_doc 异质，寄生是 P20 大修连带的历史遗留）。改 ValidateStage transition/resolve_condition + DocgenStage transition。
2. **dd-intake short-circuit 直接调 `DocgenStage._render_detailed`**（外部 `--detailed-design` 输入时，短路到 validate 前渲染 design_doc）。DocgenStage 改 LLM 后此函数消失。
   - 解耦取向：short-circuit 时 design_doc 直接指向外部文档路径（外部已有详设，无需再 LLM 生成）。

> 注：此两处是「字段/函数复用」耦合，**非 design_doc.json 的文档消费**——不否定路径 Y；但实施须剥离保留 validate 路由机制与 dd-intake 短路能力。
