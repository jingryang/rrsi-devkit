# 第一准则对齐（skill 须可在 TUI 自闭环）— L1 问题记录（2026-06-17）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/现象/根因/影响）。
> 修复方案见同目录 `02-analysis.md`（待产）。
>
> **上位准则**（见 `CLAUDE.md` §第一准则，2026-06-17 重大决策）：skill 兼容性是第一准则，
> 优先级高于工程架构纯度。四条硬约束：① 自包含可独立使用；② I/O schema = 文件；
> ③ schema 文件随 skill 目录走；④ **skill / skill 链必须能在 Claude Code TUI 自闭环、
> 不依赖工程框架**（最强）。本记录登记现状对这四条的违背点,作为跨阶段回溯(step-8 design 已完成 +
> step-9 test_design)的输入。
>
> 证据基于源码（`orchestration/base.py`、`stages/design_substages.py`、`stages/test_design.py`）
> + skill 正文（`.claude/plugins/*/skills/*/SKILL.md`）逐条核对。

> 结论速览：现工程为「编排归 Python / State 为事实源 / 数据流 (c)」而设计,使 skill 的**契约与闭环
> 能力被吸进工程框架**——schema 落在 DevKit 路径且只经工程 prompt 渲染到达 skill、输入靠编排注入 prompt、skill 链
> 的时序交接被当债务剥离。这些在 DevKit 内能跑,但 skill 一旦拿到 Claude Code TUI 就**契约缺失/
> 无法接力/读不到目录外资源**,违背第一准则。共四类:F1 schema 在 Python 不随 skill;F2 输入靠 prompt
> 注入而非文件;F3 skill 链文件接力被剥坏(无法自闭环);F4 读 skill 目录外资源(不自包含)。

---

## F1：I/O schema 在 DevKit 路径(`resources/schemas/`)且只经工程 prompt 渲染到达 skill,不随 skill 目录走（违准则 #2/#3）

> 勘误(2026-06-17 复核源码后修正):初稿曾称「schema 写在 Python `artifact_contract`」——**不准确**。
> step-8 已把 schema **外置**到 `resources/schemas/<stage>/*.json`,由 `SchemaLoader.load_contract`
> 加载(`adapters/schema/loader.py`),Python 的 `artifact_contract()` 只是**引用文件名**、不持有 schema
> 真值。故 F1 不是「schema 在 Python」,而是「schema 在 **DevKit 专有路径**、且只经**工程 prompt 渲染**
> 到达 skill」——两点都使 skill 离开 DevKit 后拿不到自己的契约。

### 证据

- **schema 已外置,但落在 DevKit 路径**:`adapters/schema/loader.py:_SCHEMAS_ROOT = resources/schemas`;
  实存 `resources/schemas/design/{design_spec,tiling_strategy,kernel_architecture,...}.json`(14 个)、
  `resources/schemas/requirement/requirement.json`。schema 真值在这些 JSON(含 required_keys/example),
  **不在 skill 目录**。`IntegrateStage.artifact_contract()`(`design_substages.py:442`)只是
  `SchemaLoader.load_contract("design", ["design_spec.json", ...])`——引用文件名。
- **skill 目录无 schema 文件**:`ls .claude/plugins/stage-design/skills/ascendc-op-design-integrate/`
  只有 `SKILL.md` + `references/`,**没有任何 schema 文件**。skill 单独拿出时不知道自己该产什么结构。
- **schema 只经工程 prompt 渲染到达 skill**:`design_substages.py:252` 用
  `artifact_contract().render_output_requirements()`(`domain/artifact.py:107`)把 schema 渲染成
  「## 输出要求」段塞进 prompt。⇒ schema→skill 的唯一通道是**工程的 prompt 渲染**;TUI 里没有这个
  渲染器,skill 就拿不到输出契约。
- **输出侧本身已是文件形态(这点已合规)**:render 文案是「用 Write 把以下 JSON 写入当前工作目录」——
  产物落 CWD 文件,符合准则 #2 的输出侧。**缺的是「契约本身随 skill 走」,不是「输出走文件」。**

### 根因

step-8 把 schema 外置到 `resources/schemas/`(一次正确的解耦),但**外置目标是 DevKit 工程资源目录、
分发通道是工程 prompt 渲染**——schema 与 **DevKit** 解耦了,却没与 **skill** 绑定。对 DevKit 内自洽,
但 skill 拿到 TUI 后既找不到 `resources/schemas/`(不在 skill 目录),也没有 prompt 渲染器喂它契约。

### 影响

- skill 拿到 TUI 后,用户/模型不知道输出 JSON 的 required_keys/文件名,契约缺失,产物无法被下游
  (无论 TUI 下一个 skill 还是 DevKit 适配层)稳定消费。违反「schema 随 skill 走、自包含」。

---

## F2：skill 输入靠编排注入 prompt,而非从文件读（违准则 #2/#4）

### 证据

- `design_substages.py:203 _upstream_inputs` + `:216 _inputs_section`:编排把上游结构化产物
  (如 tiling_results)dump 成 JSON **塞进 prompt 的「## 上游输入」段**,skill 从对话上下文取输入。
- `ascendc-op-design-intake/SKILL.md`(step-8 新建)正文明示:「本步骤输入已在本次对话上下文中提供,
  不需要你去工作目录或别处搜寻」「禁止去读 op_spec.md / template_division.md」——即 skill 被显式
  要求**不从文件读输入**,只认 prompt 注入。
- `test_design.py:67 _build_prompt`:同样把 requirement/design_doc 渲染进 prompt。

### 根因

数据流 (c) 的核心手法是「编排注入 prompt、skill 不跨读文件」。它为铲除 AC0(skill 跨读他人
checkpoint 做控制流)而生,但**连带把正常的文件 I/O 也禁掉了**,改走 prompt 注入。

### 影响

- TUI 里没有「编排注入 prompt」这一步——用户跑 `/skill` 时,skill 因被指令「不从文件读输入」而
  拿不到任何输入,无法独立工作。违反「I/O=文件、可独立使用」。

---

## F3：skill 链的文件接力被当债务剥坏,链无法在 TUI 自闭环（违准则 #4,最强）

### 证据

- testdesign 三 skill 原靠 `workflow_context.json` + 合并版 `.md` 文件接力 + 「末尾提示运行下一个
  skill」完成 analyze→casedesign→generate-case 的链式闭环(SKILL.md 阶段1.0/4.2/5.2)。
- step-4 迁移把这套接力判为「游离编排债务」要剥离,但**只改了一半**:阶段4.1/5.1 声明「本 skill 不
  维护 workflow_context.json」,而阶段1.0/4.2 仍在读写它——**自相矛盾的半残态**(step-9 L1 T2 已记)。
- step-9 L3 初稿(02-analysis T2)曾决定「彻底剥离文件接力」——**该决定与第一准则 #4 直接冲突,已作废**。

### 根因

「控制流归 Python」被推到极致,把 skill 链**自身的时序与文件交接**也当成要剥离的编排债务。但这套
接力正是 skill 链在 TUI 里**不依赖工程框架自闭环**的唯一机制——剥掉它,链就断了。

### 影响

- 三个 testdesign skill 在 TUI 里无法接力:analyze 产物 casedesign 找不到、链跑不通。违反「skill 链
  必须能自闭环、不依赖工程框架」。**这是 step-4 把 TUI skill 改坏的直接后果。**

---

## F4：skill 读自身目录之外的资源,不自包含（违准则 #1）

### 证据

- `AIInfra-OP-testdesign-generate-casedesign-skill/SKILL.md:14/507` 读
  `.claude/rules/common/AIInfra-OP-testdesign-common-rules.md`(skill 目录外的公共规则)。
- 同文件 `:509` 读 `.claude/AIInfra-OPTest_knowledge/`(skill 目录外的知识库;且与实际案例所在的
  包内 `references/` 路径不一致——step-9 T2 已记此路径错)。
- `analyze-skill/SKILL.md:525` 同样引 `.claude/rules/common/...common-rules.md`。

### 根因

skill 从 TUI 工作流移植时,依赖了仓内「公共规则目录 / 知识库目录」等 skill 目录**之外**的资源,
靠绝对感路径引用。

### 影响

- skill 单独拿出(或在他人仓的 TUI)时,这些目录外资源不存在,skill 不完整、跑不通。违反「自包含」。

---

## 受影响范围(跨阶段回溯清单)

| 阶段 | 不合规点 | 对应 F |
|---|---|---|
| design(step-8 已完成) | 11 substage 的 schema 在 `resources/schemas/`(DevKit 路径)且只经工程 prompt 渲染到达;输入靠 _inputs_section 注入 prompt;intake 明令「不从文件读」 | F1, F2 |
| test_design(step-9) | 三件套注入 prompt;CSV/报告 schema 在适配层/stage;文件接力被剥坏;读目录外 common-rules/知识库 | F1, F2, F3, F4 |
| requirement / codegen | schema 在 `resources/schemas/`(DevKit 路径)、只经 prompt 渲染到达(F1);输入注入 prompt(F2) | F1, F2 |

> 优先级:第一准则覆盖 step-8/9 既有结论。回溯顺序与方案(保留多少外层编排、schema 文件格式、
> 接力约定如何与 DevKit 外层并存)留 `02-analysis.md`(L3)拍板。

---
