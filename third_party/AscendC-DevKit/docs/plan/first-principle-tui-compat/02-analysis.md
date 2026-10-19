# 第一准则对齐 — L3 方案分析（2026-06-17）

> 层级：**L3 / 方案分析**。回答「每个问题有哪些选项、选了哪个、为什么」。
> 问题证据见同目录 `01-problems.md`（L1，F1-F4）；分层约定见 `../README.md`；
> 上位准则见 `CLAUDE.md` §第一准则。本文定**调和模型**（内层 skill 链 vs 外层 DevKit 编排
> 如何并存），它覆盖 step-8(design 已完成)/step-9(test_design) 的既有结论,是二者 L4 的前提。

---

## 核心张力（本文要解决的根问题）

第一准则 #4 要求「skill 链能自闭环、不依赖工程框架」;而 DevKit 9-stage 主链需要外层编排
(gate / loopback / fork-join / 重试 / 接主链)。两者看似矛盾。本文给出调和模型,使**同一套
skill 既能在 TUI 被人手动跑通,又能被 DevKit 无人值守驱动**,且两条路**共用同一文件契约**、
不分叉。

---

## §M 调和模型（已拍板）：内层自闭环 + 外层可选驱动 + 单一文件契约

### M1 两层定义

- **内层 = skill / skill 链**：事实源。每个 skill「读 CWD 里约定的输入文件 → 产 CWD 里约定的
  输出文件」;skill 之间靠**文件接力**(前一个的输出文件 = 后一个的输入文件)完成链式闭环。
  内层自带「下一步提示」(末尾告诉用户/驱动者该跑哪个 skill)。**内层不含跨 stage 高阶编排。**
- **外层 = DevKit 编排（可选）**：驱动器。它不取代内层,而是**沿用内层的文件契约**驱动 skill 链:
  spawn 前把 State 物化成 skill 约定的**输入文件**放到 CWD;skill 跑完后从**输出文件**收集回 State;
  在 skill 调用**之间**(边界上)施加 gate / loopback / 重试 / fork-join。

### M2 两种运行形态(同一 skill、同一文件契约)

| | TUI(无框架) | DevKit(有框架) |
|---|---|---|
| 谁准备输入文件 | 人类把输入文件放进工作目录 | 编排把 State 物化成输入文件放进 CWD |
| 谁推进下一步 | 人类读「下一步提示」后手敲 `/next-skill` | 编排读边界、spawn 下一个 skill |
| skill 自己做什么 | **完全相同**:读输入文件→产输出文件→提示下一步 | **完全相同** |
| 接力载体 | 文件(workflow_context.json / 合并版 .md / JSON) | **同样的文件**(编排顺带读它做收集/路由) |

> 关键:skill 看不出自己跑在 TUI 还是 DevKit——它只认 CWD 的文件。这就是「不依赖框架」的落地。

### M3 边界纪律（外层 DevKit 可做 / 不可做）

**可做**(都发生在 skill 调用**之间**的边界上,基于 skill 的**输出文件**):
- 读 skill 输出文件 → 物化进 State / 收集产物。
- 基于输出文件内容做 gate(质量门)、loopback(回退重跑)、重试。
- fork-join:把同一 skill 在 N 个**隔离子目录**各 spawn 一次,再合并(并行优化)。
- spawn 前把上游 State 物化成下游 skill 的输入文件(替代「注入 prompt」)。

**不可做**(否则又把 skill 绑死在框架上):
- ❌ 把结构化产物**注入 prompt** 作为 skill 的输入旁路(违 F2;TUI 无此通道)。
- ❌ 让 skill 去**轮询另一个 skill 的 checkpoint 判断「对方完成没/能否往下走」**(=AC0 控制流耦合,
  死循环病根)——这条**仍然禁止**,见 M4。
- ❌ 要求 skill 读 DevKit workspace 专有布局(`output/<run_id>/...`)或专有 MCP 工具。

### M4 关键区分:文件接力(保留) vs checkpoint 控制流轮询(仍禁) —— 不是同一回事

L1 F3 反转了「剥离文件接力」,但**没有**复活 AC0。二者本质不同,务必分清:

- ✅ **文件接力 = 数据依赖**:skill B 把 skill A 的**输出文件当输入数据**读(analyze 产
  `_测试分析_合并版.md` → casedesign 读它做用例设计)。这是正常 I/O,是 TUI 自闭环的必需,**保留**。
- ❌ **checkpoint 轮询 = 控制流耦合**:skill A **轮询** skill B 的状态文件判断「B 完成了吗/模板齐了吗/
  anchor 过了吗」来决定自己 GO/NO-GO(design AC0:A 找 B 从没建的文件→误判→死循环)。这是把**控制流
  判断**塞进 skill,**仍禁**——这类判断归外层(TUI 是人、DevKit 是 Python)。
- **一句话**:skill 可以读上游 skill 的**产物当数据**;不可以读他人状态**当控制流信号替自己做调度决策**。
  前者是「这是我要加工的料」,后者是「我替编排决定要不要往下走」。


---

## §F 各不合规点的解法（对齐 M 模型）

### F1 解法：schema 文件从 DevKit 路径迁到 skill 目录 + SKILL.md 自带契约（schema 已外置,迁目标即可）

> 前提更正:schema 不在 Python——step-8 已用 `SchemaLoader`(`adapters/schema/loader.py`)把 schema
> 外置到 `resources/schemas/<stage>/*.json`。故 F1 不是「从 Python 抽 schema」,而是「把已外置的
> schema 从 **DevKit 路径**迁到 **skill 目录**,并让 SKILL.md 自带契约」——工作量小于初稿设想。

- **迁移 SchemaLoader 的根**:把 `_SCHEMAS_ROOT` 从 `resources/schemas/<stage>/` 指向**对应 skill 的
  目录**(如 `ascendc-op-design-integrate/schema/*.json`)。schema JSON 文件原样搬进 skill 目录;
  `SchemaLoader.load_contract` 改按 skill 定位。DevKit 与 TUI 读**同一份**(skill 目录内),不分叉。
- **SKILL.md 自带 I/O 契约**:在每个 SKILL.md 正文写明「输入文件:<名/来源>、输出文件:<名 + required_keys
  + example>」,引用本目录 schema 相对路径。⇒ TUI 里没有工程 prompt 渲染器时,SKILL.md 正文自身即是
  契约来源(slash 注入 SKILL.md 时一并到达),不靠 `render_output_requirements`。
- **Python `render_output_requirements` 降为「DevKit 内的便利渲染」**:DevKit 仍可从 skill 目录的
  schema 渲染输出要求进 prompt(增强,无害),但它**不再是 skill 拿到契约的唯一通道**——SKILL.md 自带。
- **格式选型(留 L4)**:沿用现有 JSON(`{required, required_keys, description, example}`,机器可校验、
  DevKit 已在用)即可,无需换格式;只需在 SKILL.md 用人类可读方式复述/引用同一契约,供 TUI 用户阅读。
  → 即「JSON schema(机器/复用现状)+ SKILL.md 内联契约(人类/TUI)」并存,同源于 skill 目录的 schema 文件。

### F2 解法：输入从「注入 prompt」改为「物化成输入文件」

- **编排物化输入文件**:spawn 前,外层把上游 State 写成 skill schema 约定的输入文件放进 CWD
  (如把三件套写成 `design_spec.json` 等),替代 `_inputs_section` 往 prompt 塞 JSON。
- **SKILL.md 改「从文件读」**:删掉 intake 等 skill 里「输入已在对话上下文/禁止读文件」的指令,
  改为「从 CWD 读约定输入文件」。slash 触发仍只注入**方法学**(§P9 不变),输入走文件。
- **prompt 只留方法学 + 算子身份指针**:prompt 可保留「算子名/op_dir」这类轻量定位信息(TUI 里
  人类也会在 `/skill` 后跟一句),但**结构化产物本身走文件**,不在 prompt 里。

### F3 解法：保留并修复 skill 链文件接力（撤销 step-9 T2 的「彻底剥离」）

- **修复 testdesign 三 skill 的接力到自洽**:撤销 step-4 的半残改造,让
  analyze→casedesign→generate-case 的文件交接(workflow_context.json 或等价的约定文件 + 合并版 .md)
  **完整可跑**,接力约定写进 skill 目录。
- **保留「下一步提示」**:skill 末尾「请运行下一个 skill」的提示**保留**——TUI 里人类据此推进;
  DevKit 里外层忽略它、自己驱动(提示无害)。**但删掉强制 `/clear` 的硬指令**——上下文管理是
  运行环境的事,skill 不该假定;改为软提示(「如上下文紧张可清理后继续」)。
- **DevKit 沿用同一接力文件**:外层驱动多 skill 时,把上一 skill 的输出文件留在共享 CWD,下一 skill
  spawn 时直接读到(M2)。⇒ **step-9 T3 的 test substage 必须共享同一工作目录**(非 design 的
  per-template 隔离),否则接力文件互相看不见。

### F4 解法：目录外资源收进 skill 目录，改相对路径

- **common-rules / 知识库收进 skill 目录**:`.claude/rules/common/...common-rules.md` 与
  `.claude/AIInfra-OPTest_knowledge/` 复制/移动进引用它们的 skill 目录(或共享 plugin 的 skill 内),
  SKILL.md 全部改**包内相对路径**。
- **多 skill 共用的公共规则**:若多个 skill 共用同一份 common-rules,放进该 plugin 的**每个**相关
  skill 目录(自包含优先,接受少量冗余),或确认 plugin 整体作为分发单元时放 plugin 根——L4 定粒度。

---

## §保留/被覆盖清算（对 step-8 数据流 (c) 与 step-9 的逐条结论）

| 既有结论(来源) | 在第一准则下 | 说明 |
|---|---|---|
| 「编排注入 prompt、skill 不从文件读输入」(c) | **被覆盖** | 改为编排物化输入文件、skill 从文件读(F2) |
| 「schema 外置到 `resources/schemas/`、经 prompt 渲染到达 skill」(step-8) | **迁移(非推翻)** | step-8 外置 schema 是对的;只把外置目标从 DevKit 路径迁到 skill 目录 + SKILL.md 自带契约(F1) |
| 「skill 间文件接力 = 游离编排债务,剥离」(step-4/c) | **反转** | 文件接力是 TUI 自闭环契约,保留并修复(F3) |
| 「skill 不轮询他人 checkpoint 做控制流」(c/AC0) | **保留** | 控制流耦合仍禁;与文件接力(数据依赖)区分(M4) |
| 「跨 stage 高阶编排归 Python:gate/loopback/fork-join」 | **保留(降为外层)** | 仍归 Python,但定位为可选外层;TUI 单链不需要它(M1/M3) |
| §P9 slash 注入 SKILL.md 方法学 | **保留** | 与 TUI `/<skill>` 天然一致;输入改走文件后更纯粹(只注方法学) |
| 物化产物到稳定路径 + 可回灌调试(c) | **保留并强化** | 正是文件契约;TUI/DevKit 共用,回灌天然成立 |
| step-9 拆 substage(T3) | **保留,语义调整** | 拆 substage=外层驱动;须共享 CWD 让接力跑通(F3) |
| step-9 三件套升 requires(T1) | **保留** | 结构性保证不变;只是注入方式改文件(F2) |
| design 阶段 per-template 隔离目录(P2) | **保留(仅 fork-join)** | 并行分支隔离防覆盖;**串行接力链反而要共享目录**(F3),二者按形态选 |

> 一句话:**控制流仍归外层、checkpoint 轮询仍禁**(架构纪律没松);松的是「I/O 必须走 prompt 注入」
> 和「schema 归 Python」这两条——它们被「I/O 走文件 + schema 随 skill」取代,以换 TUI 可移植性。

---

## §顺序：先 step-10 定调和模型,再回溯 8/9

### 决策(已拍板)

1. **step-10 本文(L3 调和模型)先行**——它是 step-8/9 回溯的共同前提,不先定,8/9 的 L4 会建在
   未拍板的调和模型上、返工。
2. **step-9(test_design)作首个落地验证场景**:它同时含 F1-F4 四类问题(范围全),且是主链前置,
   适合把调和模型完整跑通一遍。step-9 的 L4 按本文 M 模型 + F 解法重订(替换其受反转的 T1/T2)。
3. **step-8(design 已完成)回溯随后**:design 已实现的 11 substage 按 F1/F2 改造(schema 下沉 +
   输入物化文件)。改动面大但同构,排在 step-9 验证通过后,复用其跑通的范式。
4. **requirement/codegen 等其余 stage**:同 F1/F2,最后批量对齐。

> **§收口结论（2026-06-23）**：requirement 与 codegen 的 F1/F2/F4 改造经逐项核查已随 L4-a（schema
> 迁 skill 目录，`resources/schemas/requirement/` 已删除，`load_contract_from_skill` 为唯一通路）和
> L4-b（基类 `_DesignSubstage` 改 `_materialize_inputs`→requirement 继承；codegen 独立实现同名方法）
> 一并完成。codegen 非 slash skill 模式，F1/F4 不适用。UT 1257 全绿无回归。步骤 10 主文档状态已更新为
> "已完成"，"待排期"标记已移除。

### 依赖与风险

- 依赖:本文 M 模型拍板 → step-9 L4 → step-9 实现验证 → step-8 回溯 → 其余 stage。
- 风险:step-8 design 是已完成且主链在用的代码,回溯改 schema 来源/输入通道有回归风险;
  必须有真实链路(rope e2e)守护 + 「TUI 单跑某 skill 能闭环」的新守护(L4 定)。

### §收口纪律（CLAUDE.md 纪律一/二 在本工作的落地，强制）

> 两条工程准则(2026-06-17，见 `CLAUDE.md` 落地纪律):① 所有 skill 逐一改造到合规(终态全量,
> 无 TUI 豁免);② 只留一条通路、删尽历史债务、并存只能限时。本工作据此承担如下**收口义务**:

1. **全量 skill 合规是终态(纪律一)**:本工作的回溯范围不止 step-8/9 用到的 skill,而是仓内**全部**
   skill——含 `.claude/skills/` 下尚未 plugin 化的 ~50 个 TUI skill(归 step-3 分批 plugin 化时一并
   按第一准则改造)。分批推进顺序:test_design(step-9 首发)→ design(step-8 回溯)→ requirement/codegen
   → 其余 stage → 未 plugin 化的裸 skill。**终态:无一例外全部满足四条硬约束。**
2. **删旧 schema 根,收敛唯一通路(纪律二)**:step-9 引入的「skill-dir 根 + `resources/schemas/` 旧根」
   并存是**限时过渡**。本工作(step-10)的 design 回溯**必须**:
   - 把 `resources/schemas/design/*` + `resources/schemas/requirement/*` 全部迁进对应 skill 目录;
   - **删除** `SchemaLoader._SCHEMAS_ROOT` 常量 + `load_spec`/`load_contract` 旧方法(收敛到唯一
     `*_from_skill` 通路);删除后 `resources/schemas/` 目录消失。
   - 收口验收:全仓 `grep "resources/schemas\|_SCHEMAS_ROOT\|load_contract("` 应为 0 命中(只剩
     `*_from_skill`)。
3. **同时清理其它「旧通路」债务(纪律二)**:本工作每改一处,删被取代的旧通路,不留并存——
   - prompt 注入输入(`_inputs_section`)→ 删,改文件物化(F2);
   - 坏掉的 workflow_context.json 外壳 → 删,改自洽接力(F3);
   - 旧 `TestDesignStage` 单 stage 类 → 删(step-9 L4-a 已列);
   - 旧 §P9 假设残留(agent.md 指示「调用 skill」等)→ 核查删除。
   - 验收:每个 PR 自检「是否留下了被取代但未删的旧通路」,有则补删或登记下一步收口期。

---

## §收敛决策（开放点 1-3 已拍板，开 step-9 L4 前的最后收敛）

> 这三点是跨阶段共性的格式/粒度决策,先定再开 step-9 L4,避免 testdesign 先选一套、step-8 回溯时返工。

### 收敛-1 schema 文件格式：沿用现有 JSON + SKILL.md 内联人类可读契约（同源于 skill 目录的 schema）

- **不换格式**:沿用现有 `resources/schemas/*.json` 的结构(`{required, required_keys, description,
  example}`,机器可校验、DevKit 已在用、`SchemaLoader` 已支持)。把这些 JSON **搬进 skill 目录**即可。
- **SKILL.md 内联契约**:每个 SKILL.md 用人类可读方式复述「输入/输出文件名 + required_keys + example」,
  并指向本目录 schema 文件相对路径。⇒ JSON(机器/DevKit 校验)与 SKILL.md 内联(人类/TUI)**同源**于
  skill 目录的 schema 文件,不分叉。
- **否决「换 IO.md 自定义格式」**:现 JSON 已是单一来源且工程在用,换格式纯增成本、丢 SchemaLoader 复用。

### 收敛-2 公共资源自包含粒度：分发单元 = plugin，公共资源放 plugin 根、skill 专属资源留 skill 目录

- **实证依据**:`plugin.json` 的 `name=stage-testdesign` 打包 3 个 skill——**分发单元是 plugin,不是
  单个 skill**。故「自包含」的边界是 **plugin 完整**,而非每个 skill 都冗余一份。
- **决策**:① 多个 skill 共用的公共资源(如 common-rules)→ 放 **plugin 根**(如
  `.claude/plugins/stage-testdesign/shared/`),各 skill 用相对路径引用;② skill 专属资源(如 casedesign
  的知识库 `references/案例*.md`,实测 16 个已在该 skill 目录内)→ **留在该 skill 目录**。
- **准则 #1「自包含」据此精确化**:指「**plugin 取出后完整**」,plugin 内 skill 间共享 plugin 根资源
  允许;但**禁止**引用 plugin 之外(如另一 plugin、仓根 `.claude/rules/`)的资源。

### 收敛-3 接力文件形态：改用轻量约定文件，TUI 与 DevKit 共读同一份

- **决策**:skill 链接力不沿用历史 `workflow_context.json`(其结构混入了跨会话状态机字段),改用
  **轻量约定文件**——即「上一 skill 的输出产物文件本身」(F3:输出文件 = 下一 skill 的输入文件),
  必要的链级元信息(算子名/输出目录)放一个极简 `chain_context.json`(仅数据指针,无控制流状态)。
- **TUI 与 DevKit 共读同一份**:TUI 里人类不用管它(skill 自己读写);DevKit 外层把 State 物化成同名
  文件、跑完读回。**禁止**接力文件里出现「阶段完成标志/重试计数/门控状态」这类控制流字段(那归外层,M4)。

---

## §F4 补充证据（复核后强化）：引用的公共资源是「悬空引用」,文件根本不存在

> 复核(2026-06-17)发现 F4 比 L1 初稿更严重:被引用的两个目录外资源**在全仓都不存在**。

- `.claude/rules/common/AIInfra-OP-testdesign-common-rules.md`:`find` 全仓**无此文件**(悬空引用)。
- `.claude/AIInfra-OPTest_knowledge/`:`find` 全仓**无此目录**(悬空引用);真实知识库案例(16 个
  `案例*.md`)其实已在 `casedesign-skill/references/` 内。
- ⇒ F4 解法据此细化:① common-rules 悬空 → 要么补建并放 plugin 根(收敛-2),要么把其规则内联进
  SKILL.md / 删除该引用(L4 核实该规则是否真有内容需保留);② 知识库引用路径 `.claude/AIInfra-OPTest_knowledge/`
  → 直接改为本 skill 目录相对路径 `references/`(案例已在那)。

---

## 待 L4 细化的开放点（仅登记，不在此定配方）

> （开放点 1-3 已在上 §收敛决策 拍板,不再列入。）

1. **外层物化/收集的落点**:在 runner spawn 前后,还是在各 stage 的 actions/transition;与现有
   `_collect` / `design_artifacts_to_state` 回灌机制如何并轨。
2. **「TUI 自闭环」的守护测试**:如何在 CI 里证明「单 skill 从文件输入能跑通」「skill 链文件接力
   能闭环」而不起 DevKit 框架——这是第一准则的回归防线,必须有。
3. **common-rules 悬空引用的处置**:核实其规则是否有实质内容需保留(补建放 plugin 根)还是直接删引用。
4. **step-10 自身 L4 拆分**:建议 a=schema 迁 skill 目录 + SchemaLoader 改根 + SKILL.md 内联契约(F1) /
   b=输入物化 + 接力修复(F2/F3) / c=资源自包含 + 悬空引用清理(F4) / d=TUI 自闭环守护测试。挂总纲 step 10 索引行。

---

## 进度与待办（2026-06-17 checkpoint）

### 已完成 ✅
- **L4-a（schema 收口）**：见 `03-impl-a-schema-converge.md`。删 `resources/schemas/` stage-artifact 旧根
  + `SchemaLoader.load_spec/load_contract/_SCHEMAS_ROOT`；design 14 schema → `stage-design` plugin 根、
  requirement → 其 skill 目录；收敛到唯一 `*_from_skill`/`*_from_plugin` 通路（纪律二收口达成）。
  commit `5d69aa9`；UT 1259 + design/reflow ST 15 绿。
  - 注：`resources/schemas/repository/profile.json` 非 skill 契约（ProfileLoader 的 YAML 校验器），保留。

### 待办（design 阶段回溯 b/c/d）—— 另起会话专做，理由见下
> **为何不在本会话续做**：design 是已完成且**主链在用**（rope e2e 路径）的 11 个 substage。b（输入物化）
> 与 c（11 SKILL.md 第一准则改造）**强耦合、必须同落**——只物化不改 SKILL.md 会让真实 design agent 既
> 收不到 prompt 注入、又没被告知读文件，**打断主链**。正确性需 11-substage 真实 LLM 链路验证（30-60+ 分钟、
> 高回归风险），且 rope e2e 是其天然安全网。故作为专门会话推进，不在 schema 收口会话里夹带。

- **L4-b（输入物化 F2，design）**：把 `_DesignSubstage` 基类从 `_inputs_section`（prompt 注入上游产物）
  改为「spawn 前物化上游 State 产物为 CWD 文件 + `_inputs_section` 返回空」——复用 step-9
  `_TestDesignSubstage._materialize_inputs` 范式（已验证）。**关键差异**：design substage 各自独立工作目录
  （`artifacts/design/<name>`，非共享），物化的输入文件名不得与本步输出文件名冲突（已核对现有产物无冲突）；
  dd-intake 现 SKILL.md 明令「禁止读文件、输入在对话上下文」需反转为「从 CWD 读详设文档/三件套文件」。
- **L4-c（11 SKILL.md 第一准则改造，design）**：逐一改 `stage-design/skills/*/SKILL.md` 为
  「从 CWD 读输入文件 + 写产物文件 + 自带 I/O 契约（指向 plugin 根 `schema/`）+ 资源自包含」。
  需先 grep 各 design SKILL.md 的外部/悬空引用（仿 step-9 L4-c 的 F4 清查）。
- **L4-d（守护，design）**：扩 `tests/st/test_skill_invocation.py`（已是 design §P9 守护）+ 仿
  `test_testdesign_tui_selfclosure.py` 加 design 链 TUI 自闭环 @llm 守护。
- **起步锚点**：`_DesignSubstage` 在 `design_substages.py:61`；`_inputs_section` 在 :216；step-9 范式参照
  `test_design_substages.py` 的 `_materialize_inputs`/`_INPUT_FILENAMES`/`_inputs_section` 覆写。

### 后续（纪律一全量合规，更远）
- step-3 的 ~50 个未 plugin 化裸 `.claude/skills/` TUI skill，按第一准则四条硬约束分批改造（终态全量合规）。

---
