# 测试设计阶段精细化 — L1 问题记录（2026-06-17）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/现象/根因/影响）。
> 修复方案见同目录 `02-analysis.md`（待产出）。本记录沿用 design 阶段精细化
> （`../design-stage-refinement/`）已固化的同源结论：§P9 skill 投递机制、数据流 (c)、
> "skill 自带游离编排 = 历史债务"（detailed-design 删除先例）。
>
> test_design 的原始设计见 `../step-3-test-design-stage.md`（L2，2026-06-12）+
> `../step-3b-test-design-impl.md`（L3）；那是 §P9/§P1 发现**之前**的方案，本记录陈述
> 相对其假设现已暴露的问题。

证据基于源码（`orchestration/stages/test_design.py`、`agents/test-designer.md`、
`.claude/plugins/stage-testdesign/skills/*/SKILL.md`）逐条核对 + 真实链路探测
（同会话 resume 多消息 slash 注入实测，见 CLAUDE.md skill 投递条）。

> 结论速览：test_design 的问题**不止 §P9（skill 投递）表层**，而是三类叠加：
> **T1 输入失配**（skill 要散文需求/详设说明书，stage 给结构化 requirement + optional 设计产物，
> 且本应作主输入的设计产物被设为 optional）；**T2 skill 自带游离编排 / 与 DevKit 数据流冲突**
> （workflow_context.json 文件接力、"引导用户清空上下文"、知识库自学习——与 detailed-design 同款债务）；
> **T3 §P9 投递 + 链式多 skill**（单 agent 串调 3 子 skill，但模型无 Skill 工具；且 slash 单消息只
> 注入首个）。三者使 test_design 在真实链路很可能跑在裸上下文 / 退化路径，且从未被真实验证。

---

## T1（根本）：test_design 的输入与 skill 期望失配，设计产物本应是主输入却是 optional

### 证据

- **stage 注入的输入**（`test_design.py:40-45` input_contract）：
  ```
  requires  = ["requirement"]
  optional  = ["design_doc", "design_spec", "tiling_results",
               "detailed_design_path", "user_feedback", "last_error"]
  ```
  即唯一**必需**输入是 `requirement`（结构化 Requirement）；概设/详设产物（design_doc /
  design_spec / tiling_results）全是 **optional**。`_build_prompt`（:67）渲染 requirement 摘要
  （`_render_requirement` 取 op_spec name/inputs/outputs/constraints 几行）+ 仅当存在时渲染
  `design_doc.markdown`（`_render_design_doc`，8000 字上限）。

- **skill 声明的输入**（`AIInfra-OP-testdesign-analyze-skill/SKILL.md` frontmatter description）：
  > 从**《XX算子需求分析与设计说明书》**和**《XX算子详细设计说明书》两篇 markdown 文档**中提取
  > 关键测试信息并进行测试分析

  skill 设计时假定输入是**两篇人类写的散文文档**（需求说明书 + 详设说明书）；stage 给的是
  结构化 requirement 摘要 + optional 的 design_doc，二者**形态与来源都不一致**。

### 根因

1. test_design 的 input_contract 把"设计产物"定为 optional——但测试用例的覆盖面（模板/tiling/
   精度链/边界/泛化）本应**主要由设计决定**。理论上 test_design 应以前置 design 阶段产物
   （概设/详设三件套 design_spec/tiling_strategy/kernel_architecture，或 design_doc）为**主输入**，
   requirement 为辅。现状反过来：requirement 必需、设计产物可选。
2. design_doc 缺失时（design 未跑 / SE-only 流程 / design_doc 未物化），test_design 只拿 requirement
   摘要凭空设计测试——与 design 阶段 P1 的"裸上下文设计"同类风险。
3. skill 与 stage 对"输入是什么"没有共识：skill 等两篇散文说明书，stage 喂结构化摘要。

### 影响

- 测试用例可能脱离实际设计（不覆盖 design 切出的模板/tiling 边界），降低 TDD 验收用例的有效性。
- design_doc optional ⇒ 存在"无设计也能跑 test_design"的退化路径，产出的用例质量不可控。

---

## T2：testdesign skill 自带游离编排 + 文件接力，与 DevKit「控制流归 Python / State 为事实源」冲突

> 与 design 阶段删除的 `ascendc-op-detailed-design`（自带 Phase 编排 + execution_state.json +
> AskUserQuestion 门控，判为历史债务删除）是**同一类病根**。

### 证据（`AIInfra-OP-testdesign-analyze-skill` / `-generate-casedesign-skill` SKILL.md 正文）

- **workflow_context.json 文件接力**（casedesign SKILL.md:26-28, 310-321）：
  > 启动时自动检测并读取 `workflow_context.json`，获取前序分析报告路径和约束；
  > 完成后更新 `workflow_context.json`，生成接力棒供下一阶段使用
  这是 skill **自带的一套跨 skill / 跨会话状态机**，与 §design 数据流 (c)「skill 不跨读他人中间
  文件、上下游靠编排注入产物」冲突（同 AC0 病根）。
- **"引导用户清空上下文后继续"**（analyze SKILL.md:18；casedesign:29 "末尾输出上下文重置提示"）：
  skill 假定自己在**人机交互式 TUI 会话**里跑、由用户手动推进阶段——而非被 DevKit GraphExecutor
  无人值守调度。
- **章节拆解 / 动态规则加载 / 知识库自学习四步流程 / 临时文档流式合并脚本**：skill 自带一整套
  执行编排与产物管理，假定自己是流程主体，不是被编排调度的"领域判断单元"。

### 根因

这三个 testdesign skill 是从**独立的人机交互式测试设计工作流**移植进 plugin 的（与 ascendc-dev
系列同源），未按 DevKit「编排归 Python、skill 只做领域判断、数据流 (c)」改造。skill 名集合在
step-3b 已接进 stage，但 skill **正文的工作假设**与 DevKit 架构从未对齐。

### 影响

- skill 去读/写 workflow_context.json、等用户"清空上下文"——在无人值守编排下这些动作要么空转、
  要么找不到预期文件（同 AC0 死循环风险）。
- 维护者难以判断 test_design 的真实控制流归属（skill 以为自己编排，工程也在编排）。

---

## T3：§P9 skill 投递 + 单 agent 链式多 skill —— 模型无 Skill 工具，slash 单消息只注入首个

### 证据

- **agent 串调 3 子 skill 的设计**（`test-designer.md` body "How you work"）：
  > Call only the product sub-skills, in order: 1. analyze-skill 2. generate-casedesign-skill
  > 3. generate-case-skill
  agent.md 用散文指示 agent **自己依次调用** 3 个子 skill。
- **模型无 Skill 工具**（真实探测，见 CLAUDE.md §P9 条 + 本次 resume 探测）：本 CLI 暴露 plugin skill
  为 slash command，可用 tools 仅 Read/Write/Edit/Bash/Glob/Grep(/mcp__engine__resolve_ambiguity)，
  **无 `Skill` 工具**。agent 实测自述"没有任何 skill 加载/调用工具"，agent.md 指示它"调用 skill"无效
  → 退化为 `Bash cat SKILL.md`（不可靠、非设计意图），或干脆裸 prompt 自由发挥。
- **slash 单消息只注入首个 skill**（实测）：首消息堆两个 `/skill` 只展开第一个；**但同会话
  `resume=session_id` 发后续消息，每条首个 slash 都会被展开注入**（实测 casedesign 方法体被逐条
  复述确认）。⇒ 链式多 skill 在本 CLI **可行，但必须由编排驱动多消息会话**，不能靠 agent 自调、
  也不能靠单消息堆叠。

### 根因

step-3b 设计 test-designer 时（2026-06-12）假定 agent 能用 Skill 工具自行串调子 skill——这个假设
与 design 阶段 §P9 的发现相同地**不成立**。design 阶段已用"编排发 slash 首消息"闭环（单 skill），
但 test_design 是单 agent 多 skill，需要更进一步的"编排驱动多消息 resume 逐阶段注入"，尚未实施。

### 影响

- test_design 在真实链路很可能 skill-dead（3 个子 skill 的方法体都没真正进 agent 上下文），
  退化为裸 prompt——与 design 阶段修复前的 P1 同症。
- 现有 ST（`tests/st/test_test_design_e2e.py`）用 **stub backend**，不验证 skill 真实调用；真实
  e2e（rope）这次**卡在 design 没跑到 test_design** ⇒ test_design 的 §P9 在真实链路**从未被验证**。

---

## T4（次要）：skill 链文件名接力存在缺口（已被 stage 侧模糊匹配兜住，但脆弱）

### 证据

- analyze 产出 `{算子名}算子测试设计方案_测试分析_合并版.md`（analyze SKILL.md 归档规范）。
- casedesign 读该文件、产 `{算子名}算子测试设计方案.md`（casedesign SKILL.md:260-267）。
- generate-case **期望输入** `{算子名}测试设计方案_合并版.md`（generate-case SKILL.md:14）——
  与上游产出的 `{算子名}算子测试设计方案.md` / `..._测试分析_合并版.md` **文件名对不齐**
  （少/多 "算子"、"测试分析"、"_合并版" 等修饰）。
- stage 侧 `_locate_csv`（test_design.py）用 `rglob("*.csv")` + 模糊匹配（优先含「合并」「测试用例」）
  兜底定位最终 CSV，**容忍**了文件名不一致 → State 边界没炸。

### 根因 / 影响

skill 链靠**文件名约定**接力，但三个 skill 的命名约定彼此不完全一致；目前靠 stage 侧模糊匹配
+ skill 间"自动检测 workflow_context.json"勉强串起来。属脆弱耦合，一旦命名或目录变动易断；与 T2
（文件接力机制）同源。优先级低于 T1/T2/T3。

---

## 与 design 阶段精细化的同源对照

| test_design 问题 | design 阶段同源项 | design 已采用的解法（可借鉴） |
|---|---|---|
| T1 输入失配 / 设计产物 optional | P1 裸上下文 + 数据流 (c) 注入链 | input_contract requires 对齐 + 编排注入上游结构化产物到 prompt |
| T2 skill 自带游离编排 / 文件接力 | detailed-design 历史债务 + AC0 跨读 checkpoint | 删/重写 skill：剥离自带编排，改"读编排注入产物、不跨读他人中间文件" |
| T3 §P9 投递 + 链式多 skill | §P9 slash 触发（单 skill 已闭环） | 编排发 slash 首消息；**多 skill 需扩展为多消息 resume 注入（新增能力）** |
| T4 文件名接力缺口 | P2 产物路径 / State 为事实源 | 产物经 State 传递，不靠文件名约定接力 |

> 与 ascendc-dev 系列收编**本质同源**（游离 skill 体系 + 自带编排 + §P9 投递）。test_design 范围更小、
> 是主链前置流程，宜作为"多消息 resume 注入"机制的首个落地与验证场景，再推广到 ascendc-dev。

---

## 待 L3 拍板的开放点（仅登记，不在此定方案）

1. **T1**：test_design 主输入应改为设计产物（design_spec/tiling_strategy/kernel_architecture 或
   design_doc）为主、requirement 为辅？设计产物是否应从 optional 升为 requires（dev 流程 design 必跑）？
   SE-only / 无设计场景如何降级？
2. **T2**：3 个 testdesign skill 是**重写**（剥离 workflow_context.json / 用户清空上下文 / 自带编排，
   对齐数据流 c）还是**重建**（仿 design-intake 那样建薄 skill）？知识库自学习机制是否保留？
3. **T3**：backend 增"同会话多消息 resume 注入"能力（复用现有 `resume=session_id`），test_design stage
   改为多消息驱动 analyze→casedesign→generate-case；或改为像 design 那样拆 substage（一步一 spawn 一
   slash）。两条路权衡。
4. **顺序**：test_design 改造 与 ascendc-dev 收编 的先后 / 是否合并为一个"外围流程对齐"大 step。
