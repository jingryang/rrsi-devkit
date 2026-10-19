# OpDef 渲染 recipe + chip 通路 + param_type 全链 — 实施方案（L4）

> 对应 `01-problems.md` P1（修）。P2（多芯片）本轮不做。

## 改了什么

不动任何 design JSON **契约语义**（chip 仍走 state/meta/hw_params，不进 design_spec）。
补三件事：渲染知识单点入知识库 + 让 docgen 够得着既有 chip 通道 + param_type（含 OPTIONAL）全链。

### A. 共享 OpDef 渲染 recipe（渲染知识单点，§1.5）
- 位置 `.claude/skills/ascendc-op-design-shared/references/OpDef渲染规格映射.md`（**设计共享资源**，非下载树）。
  > 落点修正：初版误放进 `ascendc-dev-knowledge/references/basic_knowledge_docs/`（spider 重生树，
  > `restructure_kb.py` 会重生 INDEX、生成文件覆盖同名——手写文件会变孤儿/丢）。已移到
  > `ascendc-op-design-shared`（设计类 skill 的共享资源容器，已有 platform_diff/knowledge_policy 等，
  > 被 general-design/tiling-*/req-analysis 等 skill 以 `ascendc-op-design-shared/references/<f>.md` 引用）。
  > docgen/codegen 直指新路径；recipe 内对官方文档的引用改 `ascendc-dev-knowledge/references/...` 全路径；
  > 撤掉 basic_knowledge_docs/INDEX.md 的指针（该 INDEX 是重生产物）。
- 内容：
  dtype 串→`ge::DT_*` / format→`ge::FORMAT_*` / attr.type→setter / `param_type`→`.ParamType(...)` /
  chip→`to_soc_version()` 映射表 + 渲染规程 + canonical 形态门（虚构-token 黑名单）。
- `basic_knowledge_docs/INDEX.md` 工程化节加一行。

### B. docgen 够得着 chip（补全既有 sanctioned 通道）
- `design_substages.py::_materialize_run_context`：物化 `hw_params.json` 时追加 `chip_code`（canonical）
  + `soc_version`（`to_soc_version(state.design_target_chip)`）。已知芯片才写，未知不伪造（§3.7）。
  hw_params 是缓存共享对象，物化前 copy 不原地改。

### C. param_type（含 OPTIONAL）全链 — mend 断裂的 IO 契约轨
- 契约源头 `requirement.json` 声明 `param_type`（REQUIRED/OPTIONAL/DYNAMIC，默认 REQUIRED）：
  `ascendc-op-req-analysis/references/op_spec_schema.md` + `schema/requirement.json` +
  `SKILL.md` 新增「输入/输出 ParamType 分析」步。
- Python proto `domain/operator.py::TensorSpec`：移除未用的 `optional: bool`，改为 `param_type: str = "REQUIRED"`
  （§2.5 单一表示；filter_known_fields 自动解析；asdict 物化保留）。
- mend 断轨：`design_substages.py::IntegrateStage._upstream_inputs` 加 `requirement`（物化 requirement.json 进
  integrate 目录）；`ascendc-op-design-integrate/SKILL.md` 加「IO 契约对齐」步（按 name 把 requirement 的
  param_type 并入 design_spec，差异记决策日志）+ 收窄「不跨读 checkpoint」注记（requirement 是契约源头
  非设计步产物）+ 自检每个 IO 必有 param_type。`schema/design_spec.json` example 加 param_type。
- `ascendc-op-design-intake/SKILL.md`：从用户详设抽 param_type（未声明默认 REQUIRED）。

### D. docgen / A3 codegen 接 recipe + 自检
- `ascendc-op-design-docgen/SKILL.md`：§2.3 渲染步指 recipe + 从 `hw_params.json.chip_code` 取 chip；
  自检加「§2.3 OpDef canonical 形态」门（拒虚构 token / 占位）。`references/doc_template_v2.0.md` §2.3 占位注释改指引。
- `ascendc-op-dev-coding/SKILL.md`：Step3 指 recipe；Step4② `def.cpp` 注明按 recipe + `meta.json.chip_code`；
  维5 加「OpDef param_type 一致」+「OpDef canonical 形态」两条自检。

### E. docgen 硬检测门 — 正向锚点（last-resort 兜底，§1.2；重构自黑名单）
- codegen `def.cpp` 有编译作天然硬门；**docgen 详设文档不编译**，原本无硬门 → 幻觉会静默流到人审
  （即原 bug 路径）。补一条：`design_substages.py::DocgenStage.transition` 读产出文档后做 **canonical
  正向锚点**校验。
- **重构（用户定调「删负向黑名单 → 加正向锚点」）**：初版是虚构-token 黑名单（`_OPDEF_HALLUCINATION_TOKENS`
  + `_opdef_hallucination_hits` 全文扫描）。改为 `_opdef_missing_canonical_anchors(code, design_spec)`：
  - 正向锚点（present 即 canonical）：`OP_ADD(` / `.ParamType(` / `.DataType(` / `AddConfig(` / 每个
    `design_spec` 输入→`Input("<name>")` / 每个输出→`Output("<name>")` / 至少一个真 soc 字面量。
  - soc 字面量取自 §1.9 单一翻译点：`_REAL_SOCS = {to_soc_version(c) for c in CHIP_GENERATIONS}`
    （公共 API，chip.py 加代际自动同步，不 import 私有 `_SOC_VERSION`）。占位串 `<...>` 无真字面量
    → 缺锚点（正向覆盖，不需负向 token 检查）。
  - **作用域收窄到围栏代码块**（`_opdef_code_region`：抽所有 ` ```…``` `）——不再扫全文。回答了
    「为什么硬门扫全文」：只对渲染出的代码下判断，prose 不可能幻觉 API。prose-only 文档（路径/命名
    UT 用）无代码块 → 空 region → 跳过（整段缺 §2.3 是 agent 自检的职责，非本幻觉兜底的）。
- 缺任一锚点 → `last_error`（halt 交人，非 discover+regenerate 盲循环——消息点名缺哪些锚点 + 指向 recipe、
  可消费）。主修复仍是 recipe + agent 自检（构造性保证，§2.9）；此门只兜「LLM 自检漏掉」。

### F. 原地（in-place）算子支持（纯知识，无 schema/字段新增）
- CANN 原地声明真相（来自 ops-transformer `scatter_pa_kv_cache`）：被更新的输入**同时**声明为同名
  Output（`this->Input("key_cache")…` + `this->Output("key_cache")…`），图编译器从名字碰撞推断 zero-copy
  别名。**无** `.Inplace()`/`.Alias()`/`.To()`/descriptor——这些 API 不存在。
- 已天然覆盖、仅需补知识：
  - schema：无「输入输出名唯一」约束，同名两边可并存 ✓。
  - param_type 轨：integrate 按 name 独立对齐输入/输出 → 同名两侧都带 param_type ✓。
  - recipe 渲染：遍历 inputs/outputs 各发一条 builder 链 → 天然产出同名 Input+Output ✓。
  - 正向锚点门：逐名 `Input("<n>")`/`Output("<n>")` 各自查 → 同名时两锚点各自命中；漏任一侧即判缺
    （原地必须两侧都声明）✓——比黑名单更鲁棒（黑名单对原地无感）。
- 落地：recipe 新增「原地（in-place）更新」节（内化 scatter 风格范例，不引外部仓路径，§2.7/§1.7）；
  docgen/codegen skill 指引补原地要点。**不**加 `inplace` 布尔字段（名字复用已是真理源，加字段=第二
  真理源，违 §2.5；[[avoid-overdesign-prefer-reuse]]）。

## 不在范围（A5，本轮不改）
`ascendc-op-dev-coding-regbase` / `ascendc-dev-s2-analysis`：A5 经 s2-analysis 中转（映射表不抽 param_type/
chip），暂不受益，已知。

## 验证
- UT 全绿：`tests/ut/orchestration/test_design_substages.py`（+hw_params chip_code/soc_version、
  +integrate 物化 requirement、+param_type 透传）、`tests/ut/orchestration/test_docgen_render.py`
  （OpDef 正向锚点门：canonical 放行 / 虚构文档 halt / 逐锚点缺失 halt / 占位 soc halt / **原地两侧必
  声明** / prose-only 跳过）、`tests/ut/skills/test_opdef_recipe.py`（recipe 完整性 + soc↔chip.py sync-guard
  + 虚构 API 教育性警示 + docgen/codegen wiring）。全量 `tests/ut`（not heavy_llm）**2739 通过 / 7 skipped**。
- 就地回验（heavy_llm，**已跑过 2026-07-23**）：`test_design_docgen_tui_selfclosure.py::test_docgen_assembles_template_faithful_md`
  296.7s 通过——真实 LLM 自闭环读 CWD JSON 组装 v2.0 文档，§2.3 渲染 canonical OpDef（正向锚点
  `OP_ADD(`/`Input(`/`.ParamType(`/`.DataType(`/`AddConfig(` 全命中 + 真 soc `ascend950` + 无虚构 token +
  OPTIONAL 输入 `bias` 正确渲染），M1 正向链路守护到位（§3.9/§3.11）。
