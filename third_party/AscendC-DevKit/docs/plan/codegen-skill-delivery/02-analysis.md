# codegen skill 投递缺失 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。

## 决策 1（P2）— 修法：投递既有 skill vs prompt 文字加纪律 → **选投递既有 skill**

- **选项 A 投递既有 skill**：让 CodegenStage 经 STAGE_SKILL_MAP 把
  `/stage-codegen:ascendc-op-dev-coding` 作 spawn 首行投递（§4.3），skill 方法体注入。
- **选项 B prompt 文字加纪律**：在 codegen prompt 「编码规则」section 加「不确定 API 查
  ascendc-dev-knowledge、禁 grep CANN」文字。
- **选 A 的理由**：ascendc-op-dev-coding skill **已含完整正确纪律**（Step3 知识库查阅 +
  Step4 按 programming_model 选编码路径 + Step5 TilingData 归一化 + Step6 编码自检）。
  B 在 prompt 重写一遍 = 同一概念两套实现 = §2.5 要消灭的债；且 B 只补「API 查找」一条，
  漏掉 skill 的编码方法论（分层编码顺序、TilingData plain-C、自检表）。
  投递是**根因修复**（补回 §4.3 缺失的投递），不是打补丁。[[soundness-over-minimal-change]]。

## 决策 2（P3）— 投递机制：进 STAGE_SKILL_MAP 统一单源 vs codegen 自建 → **选统一单源**

- **选项 A 进 STAGE_SKILL_MAP**：`orchestration-config.json` 的 `skills.stages` 加
  `"codegen": "stage-codegen:ascendc-op-dev-coding"`；CodegenStage 读它 prepend `/{skill}`。
- **选项 B codegen 自建 prepend**：CodegenStage 自己 hardcode skill 名 + prepend。
- **选 A 的理由**：§2.5 同一职责一条通路——skill 分派的单源已是 STAGE_SKILL_MAP，
  codegen 接入即与设计侧同机制，`validate_skill_map()` 顺带校验 codegen skill 存在性（§1.3
  加载期校验）。B 另起一套 = 又一条 skill 分派通路。

## 决策 3（P4）— meta.json 契约：codegen 物化 vs 改 skill 放宽 → **选 codegen 物化**

- **选项 A codegen 物化 meta.json**：`_materialize_inputs` 增写 `meta.json`，
  `programming_model` 由 canonical 代际派生（A2/A5→Regbase、A3→Membase，据 SKILL.md Step4 表），
  `chip_code`=canonical 代际，`soc_version`=`to_soc_version(chip)`。
- **选项 B 改 skill 放宽 meta.json**：删 skill 的 meta.json 硬要求。
- **选 A 的理由**：programming_model 是**有用信号**（驱动编码路径 + 解决设计侧 platform 代际
  歧义，见 01-problems P4），物化它让 skill 真正发挥作用；改 skill 是削弱契约迁就缺陷。
  单源仍是 chip.py canonical（§1.9）；generation→programming_model 映射是 codegen-skill 契约的
  本地派生，落在 codegen.py（不污染 chip.py，programming_model 是 codegen 编码路径概念非芯片身份）。

## 决策 4（边界）— incremental-developer 是否同投递 → **本轮仅 new，incremental 列 follow-up**

- moe_re_routing 是 new 模式（ascendc-coder），本轮先修 new。
- incremental-developer（改存量）同样适用该 skill，但本轮不扩范围；记 follow-up 评估。

## 四把尺子自检
- **可维护**：补回 §4.3 投递，skill 纪律单源（SKILL.md），不再 prompt 重复。
- **可扩展**：后续 codegen 类 stage 接入 STAGE_SKILL_MAP 自动获得投递；多输出/整数算子自动走
  skill 的 KB 查阅，不再各自 grep CANN。
- **可诊断**：skill 投递后 agent 按 Step3 查知识库，失败有明确「查不到」信号；不再静默 grep。
- **架构合理**：改动落在投递层（STAGE_SKILL_MAP + CodegenStage prepend）+ 契约物化层
  （codegen meta.json），与设计侧对称，不越层。
