# 测试设计阶段精细化 — L3 方案分析（2026-06-17）

> ⚠️ **上位决策插入（2026-06-17，晚于本文初稿）——本文 T1/T2/T3 须据此重审，部分结论已反转**：
> 工程目标调整，**skill 兼容性升为第一准则**（见 `CLAUDE.md` §第一准则 + 跨阶段回溯
> `../first-principle-tui-compat/01-problems.md`）：所有 skill 必须能在 Claude Code TUI 中直接
> `/<skill>` 复用，I/O 契约以**文件**为载体、schema 文件随 skill 目录走，且 **skill / skill 链
> 必须能靠自己的文件接力自闭环、不依赖工程框架**。这与本文部分决策冲突，**冲突处以第一准则为准**：
> - **T1**：原「把三件套**注入 prompt**」→ **反转**为「skill 从**文件**读输入；编排（可选外层）把
>   三件套物化成 skill schema 约定的输入文件」；schema 文件收进各 skill 目录。requires 升级
>   （结构性保证三件套存在）不变。
> - **T2**：原「剥离 workflow_context.json **文件接力**」→ **反转**：skill 间文件接力是 TUI 自闭环的
>   唯一机制，**必须保留并修复**（接力约定收进 skill 目录），只剥离「破坏可移植性的耦合」
>   （目录外资源 / DevKit workspace 专有路径 / 专有 MCP）。重写（非重建）、保留知识库自学习不变,
>   但其修法从「改注入」变为「修文件接力 + 收资源进目录」。
> - **T3**：拆 substage 的结论**方向不变**（每步 `/<skill>` 正是 TUI 用法），但语义调整——DevKit 拆
>   substage 是**可选外层驱动**，须沿用 skill 链既有的文件接力契约（不另起 prompt 注入旁路）；
>   且 test substage 须**共享同一工作目录**让文件接力跑通（与 design 的 per-template 隔离目录相反）。
>   否决多消息 resume 不变。
> - **顺序**：test_design 先行不变；它同时成为「第一准则 = 文件 I/O + schema 随 skill + 链自闭环」的
>   首个落地验证场景。但第一准则的回溯范围**大于 step-9**（含已完成的 step-8 design），见总纲 step 10。
>
> 详细重审与 schema-文件落点在 L4（`03-impl-*`）按第一准则展开；本文正文保留初稿，仅以此横幅标注差异。

> 层级：**L3 / 方案分析**。回答「每个问题有哪些选项、选了哪个、为什么」。
> 问题证据见同目录 `01-problems.md`（L1，已评审通过）；分层约定见 `../README.md`；
> 精确到改哪个函数/怎么验证的实施配方见 `03-impl-*.md`（L4，拍板后按需产出）。
>
> 本记录沿用 design 阶段精细化（`../design-stage-refinement/`）已**固化**的同源结论，
> 作为不再翻案的前提直接复用：
> - **§P9 skill 投递**：本 CLI 把 plugin skill 暴露为 slash command，模型无 `Skill` 工具；
>   编排在首消息以 `/plugin:skill` 触发注入 SKILL.md（design 单 skill 已闭环）。
> - **数据流 (c)**：State 为运行时事实源 + 磁盘产物为可回灌物化层；skill 只做领域判断、
>   读编排注入的输入、写自己的输出，**不跨读他人中间文件/checkpoint**。
> - **detailed-design 删除先例**：自带 Phase 编排 + execution_state.json + 文件接力的 skill
>   判为历史债务；按"职责对不对"决定删/重写（详见 §T2）。
> - **角色化 + STAGE_SKILL_MAP**：少数权限 profile 角色复用多 substage，按集中配置表逐步指派
>   单 skill；两段式加载保证每次 spawn 只见 1 个 skill 全文，复用多 stage 不超载。

---

## 结论速览（四个开放点逐一拍板）

| 开放点 | 决策 | 一句话理由 |
|---|---|---|
| **T1** 输入失配 / 设计产物 optional→requires | 设计三件套升 **requires**（与 requirement 并列必需）；主输入=设计产物、辅=requirement；裸上下文设计用 `validate_inputs` fail-fast 堵死 | dev/full 必跑 design group（整合或 dd-intake 短路都产三件套），上游结构性保证；SE 无 test_design，无降级问题 |
| **T2** skill 重写 vs 重建 / 知识库自学习 | **重写**（不重建）3 个 product skill：保留方法学+知识库自学习，剥离 workflow_context.json/`clear`/文件接力三类游离编排 | 职责对（测试设计），错的是外壳；方法学+案例库是真实资产，重建是浪费——与 detailed-design（职责错→删）相反 |
| **T3** 多消息 resume 注入 vs 拆 substage | **拆 substage**（β）：test_design → CompositeGroup（test-analyze / test-casedesign / test-casegen），复用 design 的"一步一 spawn 一 slash 单 skill"闭环 | 完全复用 design 已固化机制（substage/(c)/角色/可观测性），上下文最小、中间产物可回灌；多消息 resume 是崩溃恢复机制误用，且引入第二套范式 |
| **顺序** test_design vs ascendc-dev 收编 | **test_design 先行**，各自独立 step，不合并 | test_design 是主链前置、直接卡 codegen 质量；是同源问题（游离 skill+自带编排）在"多 skill 链"上的最小验证场景，闭环后再推广 ascendc-dev |

> 一条贯穿全篇的耦合：**T1（stage 注入什么）与 T2（skill 期望什么）必须协同改写**——
> 正如 design 阶段 §P9 隐患 2 / L4-c。skill 输入契约从"两篇散文说明书 + workflow_context.json"
> 改为"编排注入的结构化三件套/tiling + 算子身份"，否则 agent 仍去找不存在的文档（AC0 病根）。

---

## §T1：输入失配 + 设计产物 optional→requires

### 决策（已拍板）

1. **设计三件套升 requires**：`input_contract` 改为
   `requires = ["requirement", "design_spec", "tiling_strategy", "kernel_architecture"]`
   （`tiling_results` / `design_doc` / `detailed_design_path` 仍 optional）。
   理由：test_design 只存在于 dev/full 流程（`_PIPELINE_STAGE_NAMES` 含 test_design，
   `_SE_STAGE_NAMES = [entry, context, requirement, finalize]` **不含**），而 dev/full 的
   design group **必跑**——正常流经 integrate 整合、详设输入流经 dd-intake 短路，**两条路都产出
   三件套**（design 阶段 §P5「design_spec 唯一权威来源 = integrate 或 dd-intake」已固化）。
   故三件套在 test_design 上游**结构性保证存在**，升 requires 是 fail-fast 而非新增耦合。

2. **主/辅定位翻正**：测试覆盖面（模板划分/tiling 边界/精度链/泛化）**主要由设计决定**，
   设计三件套（+ tiling_results）是**主输入**；requirement 提供精度阈值/语义/广播规则，是**辅输入**
   （但仍必需——三件套不一定完整携带精度阈值）。`_build_prompt` 相应改为注入结构化三件套 +
   tiling_results（沿 design substage `_inputs_section` 的 8000 字上限分块渲染），不再只渲染
   `design_doc.markdown`。`design_doc` 降为可选的"渲染陪衬"（若改造后 skill 需散文文档形态可喂）。

3. **SE-only / 无设计场景**：
   - **SE 无降级问题**：SE 流程不含 codegen/verify，自然不含 test_design（步骤 4 §P6「SE 不接」
     已固化），所以不存在"SE 下无设计跑 test_design"。
   - **无设计的退化路径用 `validate_inputs` 堵死**：新增内容级校验（非仅存在性），三件套缺失/空
     则 fail-fast 报错，**禁止裸上下文设计测试**——直接复用 design 阶段 §P1「禁裸上下文设计」的底线。
   - **单步调试**：复用数据流 (c) 的回灌装载器（`design_artifacts_to_state`，
     `design_artifacts.py:72`）从盘上 `design/integrate/*.json` 重建三件套注入，
     `stage run --name test_design` 即可单独调起，无需重跑 design。

### 根因对照（L1 → 解法）

- L1 根因 1（设计产物 optional 反了）→ 升 requires + 主辅翻正。
- L1 根因 2（design_doc 缺失则凭空设计）→ validate_inputs fail-fast + (c) 回灌。
- L1 根因 3（skill 等散文、stage 给摘要）→ 与 §T2 协同：skill 输入契约改吃结构化三件套。


---

## §T2：3 个 testdesign skill 的处置 —— 重写（剥离游离编排，保留知识库自学习）

### 决策（已拍板：重写，不重建）

对 `AIInfra-OP-testdesign-analyze-skill` / `-generate-casedesign-skill` / `-generate-case-skill`
三个**产出型**子 skill 执行**就地重写**，不推倒重建。

### 重写 vs 重建的判据（与 detailed-design 删除先例对照）

design 阶段对 `ascendc-op-detailed-design` 的处置是**删除 + 新建 intake**，因为它**职责错了**
（stage 要"录入转写"，skill 给"从概设生成详设"，名实不符）。本处与之**相反**：

- **职责对**：三个 skill 做的正是 test_design 需要的事（特性分析 / 用例方案设计 / 用例 CSV 生成），
  与 stage 目标一致，**没有名实不符**。
- **资产真实且重**：方法学规则（`rules/*.md`）、知识库案例（`references/` 数十个 `案例*.md`）、
  确定性脚本（`testcase_generator.py` / `duplicate_checker.py` / `self_checker.py` /
  `merge_*.py`，**仅标准库**，step-3b 已核实）——这些是真实领域资产，重建=重造且丢历史积累。
- **错的只是外壳**：游离编排（workflow_context.json / `clear` / 文件接力 / 跨会话状态机）是套在
  正确方法学外面的 TUI 工作流外壳。**剥壳保核**即可，无需重建。

> 一句话：detailed-design 是"职责错→删"，testdesign 三件是"外壳错→重写"。判据是**职责对不对**，
> 不是"有没有游离编排"——两者都有游离编排，但前者职责也错，后者职责对。

### 重写的三类剥离（对齐数据流 (c)）

1. **删 workflow_context.json 文件接力**：三个 SKILL.md 现状自相矛盾——阶段4.1/5.1 已声明
   "本 skill 不维护跨会话 workflow_context.json"，但阶段1.0「检测并读取」、阶段4.2/5.2「workflow_context.json
   已更新」「请 /clear 后执行下一 skill」仍在（step-4 迁移**改了一半**）。重写**彻底删干净**：
   输入一律从编排注入的 prompt / 当前工作目录已有产物读取（数据流 (c)：读编排喂的输入、不跨读
   他人 checkpoint），符合 CLAUDE.md「不留过渡层、要么彻底改要么不改」。
2. **删"引导用户清空上下文后继续"**：删除所有 `/clear` 提示与"请输入：执行 XX-skill"的人机交互
   推进话术。阶段时序由编排（拆 substage 后的 GraphExecutor，见 §T3）驱动，skill 不假定自己在
   TUI 会话里被用户手动推进。
3. **删自带阶段编排话术**：删除"接力棒""上下文重置提示""下一阶段"等 skill 自述编排的措辞；
   skill 正文只保留"本步方法学 + 本步输入契约 + 本步产物契约"，时序/门控/路由归 Python。

### 明确**保留**项

- **知识库自学习机制**：**保留**。它不是游离编排，而是**领域方法学的一部分**——casedesign skill
  生成用例前检索 `references/案例*.md` 学习章节说明/表格结构/数据组合/典型值/level 标注，是保证
  输出质量与既有案例一致的真实手段（与 design skill 内联的"切分轴优先级/BUFFER_NUM"等规则同性质）。
  剥离它等于砍掉方法学。保留，但**修正其文件路径**：现 casedesign SKILL.md:509 指向
  `.claude/AIInfra-OPTest_knowledge/`（仓外绝对感路径，违反 CLAUDE.md「代码仓自闭环」），应改为
  skill 包内相对路径 `references/`（实际案例就在该 skill 的 `references/` 下，已随 plugin 自包含）。
- **章节拆解 / 动态规则加载 / 流式合并脚本**：**保留**。这些是"降上下文压力"的执行技巧，属方法学，
  非跨 skill 编排。只删跨会话/跨 skill 的状态接力，不删 skill 内部的分章处理。
- **确定性脚本**：**保留**。CSV 生成/去重/自检脚本是确定性领域工具，正是数据流 (c) 鼓励的
  "领域判断的产出规整成结构化"。

### 与 §T3 的协同（重写后 skill 的输入契约形态）

重写 skill 输入契约时，须与 §T3 拆 substage 后"每个 substage 注入什么"对齐（同 design §P9 隐患 2）：

- analyze skill：输入从"两篇散文说明书 + workflow_context.json"改为"编排注入的结构化三件套 +
  tiling_results + 算子身份"（§T1 的 stage 注入），产出结构化测试分析报告。
- casedesign skill：输入从"读盘上 `_测试分析_合并版.md`"改为"编排注入上游 analyze 产物 +
  知识库案例（包内 references/）"。
- generate-case skill：输入从"找 `{算子名}测试设计方案_合并版.md`"改为"编排注入上游 casedesign 产物"；
  文件名接力缺口（L1 T4）随之消解——产物经 State/(c) 物化路径传递，不靠文件名约定（同 design §P2/T4）。

### 根因对照

- L1 T2 根因（从 TUI 工作流移植、未按 DevKit 架构改造）→ 重写剥离三类游离编排 + 修知识库路径。
- L1 T4（文件名接力缺口）→ 被 §T3 拆 substage + 数据流 (c) 物化路径**一并解决**，不再单独处理
  （与 design 阶段 P2「靠 State 传递、不靠文件名约定」同源）。


---

## §T3：链式多 skill 投递 —— 拆 substage（复用 design 闭环），不走多消息 resume

### 两条路的权衡

L1 T3 末尾登记两条路。先把两者讲清，再说为什么选拆 substage。

- **路 α：backend 增"编排驱动多消息 resume 注入"**。单 agent `test-designer` 一次 spawn，
  编排首消息发 `/analyze`，再用 `resume=session_id` 同会话发 `/casedesign`、`/generate-case`，
  逐条注入 skill 方法学（CLAUDE.md 已实证"同会话 resume 每条首个 slash 都会展开"）。
- **路 β：拆 substage**。把 `test_design` 从单 AtomicStage 拆成一个 CompositeGroup，含
  3 个串行 substage（test-analyze / test-casedesign / test-casegen），**完全复用 design group 已
  固化的"一步一 spawn 一 slash 单 skill"机制**：`_DesignSubstage` 基类、`STAGE_SKILL_MAP` 指派、
  `_with_trigger` 首消息 slash 注入、数据流 (c) 物化、角色 agent、`stage_name`/`branch_label` 可观测性。

### 决策（已拍板：路 β 拆 substage）

理由按 CLAUDE.md「四把尺子」（可维护 / 可扩展 / 可诊断 / 架构合理）：

1. **可维护——复用而非新建机制**：design 阶段已把"一步一 skill"打磨为闭环（substage 基类 +
   STAGE_SKILL_MAP + slash 触发 + (c) 物化 + 角色 + 可观测性，均在 `design_substages.py` /
   `skill_config.py` / `sdk_backend.py` 在用）。拆 substage 是**套用现成范式**，零新机制。
   路 α 要在 backend 新增一套"编排可主动驱动的多消息会话"API，是**第二套 skill 投递范式**，
   与 design 的单 skill 范式并存，违背"单一来源/不留过渡层"。

2. **架构合理——resume 是崩溃恢复，不是编排原语**：现 backend `resume=session_id`（`sdk_backend.py:697`）
   是 **step-5a 崩溃恢复**专用——固定 `_RESUME_PROMPT="请继续…"`、session_id 只在内部循环捕获、
   不向编排/runner 暴露。把它改造成"编排按业务语义逐阶段投递不同 slash 的多消息驱动器"，是让一个
   "容错重试"机制兼任"正常控制流"，职责越界（控制流本应归 Python 编排的 stage 拆分，而非 backend
   会话续跑）。这正是数据流 (c) / §P3「控制流归 Python」要避免的。

3. **可诊断 + 可观测**：拆 substage 后每步独立 spawn、独立 transcript、独立 `[stage]` 日志前缀
   （复用 D8 的 `stage_name` 透传），analyze/casedesign/casegen 各自的产物、失败、重试都能在
   events.jsonl / 控制台分辨；单步可回灌调试。路 α 三步挤在一个 session 里，日志是一长串 turn，
   中间步失败难定位、无法单独重跑某一步。

4. **可扩展 + 上下文最小**：两段式加载下，拆 substage 每个 spawn 只注入当前 1 个 skill 全文
   （analyze 时不背 casedesign/casegen 全文）；路 α 同会话累积三个 skill 全文 + 三步全部中间输出，
   上下文单调增长，长链更易触顶/漂移。新增第 4 步测试 skill 时，拆 substage 只需加一个 substage 类
   + 一行 STAGE_SKILL_MAP；路 α 要改 backend 多消息序列编排。

> 取舍代价（已接受）：拆 substage 要把 test_design 从 AtomicStage 改为 CompositeGroup，动 workflow
> 拓扑（`_design_root` 之后、codegen 之前插一个 test_design group）+ 新增 3 个 substage 类 + 适配层
> CSV 定位改为读末步 substage 物化产物。改动量比路 α 大，但**全部是套用 design 现成范式的同构改动**，
> 且换来上面四项价值；多花的改动量值得（CLAUDE.md「不以修复速度为准」）。

### 落点（细化待 L4）

- **新增 test-design group**：CompositeGroup `test_design`，子节点
  `test-analyze → test-casedesign → test-casegen`（串行，无 fork-join）。
  transition_table 内部线性；group 失败/耗尽沿用现 test_design 的 exhausted→halt（不回退 design）。
- **STAGE_SKILL_MAP 增三行**：在 `orchestration-config.json` 的 `skills.stages` 加
  `test-analyze / test-casedesign / test-casegen → stage-testdesign:<对应 skill>`；
  §P4 一致性校验扩到 stage-testdesign 插件（校验 map 值 ⇄ 插件实际 skill 集合）。
- **角色复用**：三个 substage 是"按方法学产出结构化产物"，归**角色 A（generator）**，
  无需新角色（D3「三角色定型」克制依旧成立）。归属已核定为**复用现有 `ascendc-design-generator`**
  （见下 §T3-a 决策），无需新建 testdesign 专属 generator。
- **数据流 (c) 物化**：每 substage 产物物化到 `test_design/<substage>/*.json|md`；末步 casegen 产
  CSV，适配层 `parse_testcase_csv` 从其物化路径定位（替代现 `_locate_csv` 的全树 rglob 模糊匹配，
  L1 T4 缺口随之消解）。
- **§P9 真实守护**：现 ST（`test_test_design_e2e.py`）用 stub backend，不验证 skill 真实注入
  （L1 T3 影响：§P9 在 test_design 真实链路从未验证）。L4 须新增 `@pytest.mark.llm` 守护：断言
  首消息发 `/stage-testdesign:<skill>` 后 agent 上下文出现该 skill 方法学（仿 design §P9 隐患 4 的
  ST 改写）。

### §T3-a：角色 agent 归属 —— 复用 `ascendc-design-generator`（已核定）

三个 test substage 的角色 agent 归属，核定为**直接复用现有 `ascendc-design-generator`**，
不新建 `ascendc-testdesign-generator`，现 `test-designer.md` agent **删除**。

依据（已对照 manifest / SKILL frontmatter 实证）：

1. **工具维度完全覆盖**：三个 testdesign skill 的 `allowed-tools` 实际只需
   `Read,Write,Bash`（analyze / casedesign）与 `Read,Write,Glob,Bash`（generate-case，多一个 Glob）；
   `ascendc-design-generator` 的 `allowed_tools` = `Read/Write/Edit/Bash/Glob/Grep/Skill/mcp__engine__resolve_ambiguity`
   是其**超集**。无任何工具缺口，无需为 testdesign 单开权限 profile。
2. **角色语义一致**：generator 角色定义是"按指派 skill 的方法学产出结构化产物"——这正是三个
   test substage 要做的（按 testdesign skill 方法学产测试分析 / 用例方案 / 用例 CSV）。与 D3
   「角色只承载工具/权限 profile，与 skill 数量/领域解耦」完全吻合；testdesign 只是又一组被指派的 skill。
3. **避免样板重复（D2/D3 克制）**：新建 `ascendc-testdesign-generator` 会多一份与 design-generator
   几乎逐字相同的 agent.md（同工具、同"套用指派 skill 方法学"正文），违背"角色按 profile 收敛、
   不按子任务 1:1"。复用既有角色零新增样板。
4. **可观测性已解决**：复用同一 generator 被多 stage 调用的日志分辨问题，已由 D8 的
   `stage_name` 透传解决（turn 日志/transcript 带 `[test-analyze]` 等前缀），无需靠 agent 名区分。

> 须显式处理的一处张力（L4 落点）：generator 现 plugins 声明为 `[stage-design, shared]`，
> 复用到 testdesign 需补 `stage-testdesign`（变 `[stage-design, stage-testdesign, shared]`）。
> 这与 §P9「两段式加载 + 每次 spawn 由 STAGE_SKILL_MAP 只指派 1 个 skill」叠加后**不致上下文超载**
> （generator 即便理论可见三组 skill，每个 spawn 实际只注入被指派的那 1 个全文）——与 design 阶段
> 「generator 复用多 stage 不超载」同一论证。agent.md 正文无需改（已是领域无关的"套用本步 skill"措辞）。


---

## §顺序：test_design 改造 与 ascendc-dev 收编 的先后

### 决策（已拍板：test_design 先行，独立 step，不合并）

- **test_design 先做**，作为独立 step 推进；ascendc-dev 系列收编**在其后**，另起 step。
- **不合并为一个"外围流程对齐"大 step**。

### 理由

1. **test_design 在主链上、直接卡 codegen 质量**：它是 design→codegen 之间的 TDD 验收用例固化点，
   不修则 codegen 在无可靠验收用例下编码（L1 T3 影响：真实链路很可能 skill-dead / 裸 prompt）。
   ascendc-dev 系列是更外围的开发者交互流程，优先级低于主链前置。

2. **test_design 是同源问题的最小验证场景**：L1 已述 test_design 与 ascendc-dev「本质同源」
   （游离 skill 体系 + 自带编排 + §P9 投递），但 test_design **范围更小、是主链前置**。它正好是
   "§P9 多 skill 链 + 数据流 (c) skill 重写"在**多 skill 串接**形态下的首个落地：design 验证了
   单 skill 闭环，test_design 验证 3-skill 串接闭环（拆 substage 范式）。**先在小范围闭环并经真实
   链路（rope e2e）验证，再把同一套范式推广到 ascendc-dev**，降低一次性大改的风险。

3. **合并会扩大 step 范围、违背克制**：ascendc-dev 收编涉及裸 `.claude/skills/` 下数十个 TUI skill
   （`ascendc-dev` / `-auto` / `-interactive` / `ascendc-fa-*` 等），范围远大于 test_design 的 3 个
   product skill。合并成一个大 step 会让范围失控、难以单独验证与回退（违背"解决被问到的问题、
   不扩大范围"）。两者保持独立 step，各自闭环。

4. **依赖方向单向**：test_design 改造**不依赖** ascendc-dev 收编（test_design 的三个 skill 已在
   `stage-testdesign` plugin 内、已接 stage）；反之 ascendc-dev 收编可借鉴 test_design 跑通的
   "多 skill 拆 substage" 范式。先后顺序与依赖方向一致。

---

## 与 design 阶段精细化的同源对照（更新版）

| test_design 决策 | design 阶段同源项 | 复用/差异 |
|---|---|---|
| T1 三件套升 requires + 主辅翻正 | §P1 input_contract 对齐 + 上游结构化产物注入 | **直接复用**注入范式；差异：design 内部 substage 链产三件套，test_design 跨 group 消费 |
| T1 validate_inputs fail-fast | §P1「禁裸上下文设计」底线 | 直接复用 |
| T1 单步回灌调试 | 数据流 (c) `design_artifacts_to_state` | 直接复用回灌装载器 |
| T2 重写剥离游离编排 | detailed-design「职责错→删」 | **相反判据**：testdesign「职责对→重写」；保留方法学+知识库自学习 |
| T2 修知识库路径仓内自闭环 | CLAUDE.md「代码仓自闭环」 | 直接复用约束 |
| T3 拆 substage 多 skill 链 | §P9 单 skill slash 闭环 + substage 范式 | **复用并扩展**：单 skill→3-skill 串行 group，零新机制 |
| T3 否决多消息 resume | §P3「控制流归 Python」 | 直接复用原则（resume=崩溃恢复，非编排原语） |
| T4 文件名接力缺口 | §P2 产物经 State/(c) 传递 | 被 T3 拆 substage 一并解决，不单列 |
| §P9 真实链路守护 | §P9 隐患 4 的 ST 改写 | 复用：断言 slash 注入方法学进上下文 |

---

## 待 L4 细化的开放点（仅登记，不在此定配方）

> （T3-a 角色 agent 归属已核定 = 复用 `ascendc-design-generator`，见 §T3-a，不再列入。）

1. **T3-b group 内 transition / 失败粒度**：analyze/casedesign/casegen 任一步失败时，是整 group
   重跑还是仅重跑失败 substage（resume-skip 已完成步）？沿用 design group 的 resume-skip 语义即可，
   L4 确认 test_design group 的 transition_table 与现 exhausted→halt 的衔接。
2. **T2-a 重写后 SKILL.md 输入契约的精确 schema**：三个 skill 各自 requires 哪些注入字段、产物
   JSON/md 的 schema（对齐 §T1 注入 + (c) 物化路径），与 design substage 的 artifact_contract 范式对齐。
3. **§P9 守护 ST 的算子选型**：用哪个真实算子（rope / add）做 `@pytest.mark.llm` 守护，复用现有
   e2e fixture 还是新增。
4. **顺序登记**：本 step（test_design 改造）的 L4 拆分（建议仿 design 的 a/b/c/d 分片：
   a=拆 substage+输入契约对齐 / b=skill 重写 / c=可观测性与守护 ST / d=清理与一致性校验），
   挂到总纲 `../skills-integration-and-tdd-plan.md` step 索引行；ascendc-dev 收编另起 step。

---
