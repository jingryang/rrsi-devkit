# 设计阶段精细化 — L3 方案分析（2026-06-15）

> 层级：**L3 / 方案分析**。回答「每个问题有哪些选项、选了哪个、为什么」。
> 问题证据见同目录 `01-problems.md`（L1）；工作步骤与状态见总纲 `../skills-integration-and-tdd-plan.md`（L2）；
> 精确到改哪个函数/怎么验证的实施配方见 `03-impl-*.md`（L4，拍板后按需产出）。

---

## §P1 详设 agent 未加载 skill —— agent 角色化 + Stage 指派 skill + 数据流 (c)

### 修复方向（已拍板）

- **Agent 角色化**：不为 10 个 substage 各建一个同名 agent，而是按「工具/权限 profile」收敛为
  少数角色（A 设计生成者 / B 质量门评审者 / C 外部锚点判定者，C 禁改产物为权限级差异）。
  agent.md 只承载角色级契约，放 `.claude/agents/`（框架硬编码查找路径，不可放 plugins）。
- **Stage 指派 skill**：`SpawnAgent` 显式带 `skills=["stage-design:<skill>"]`，prompt 显式
  指令调用该 skill；backend 透传到 `ClaudeAgentOptions.skills`，**顺手修掉 `skills or []`
  全抑制 bug**（L1 根因 4）。这样每次 spawn 最小 skill 暴露、且 skill 选择确定性（不靠模型猜）。
- **方法学单一来源（Pattern 2）**：SKILL.md 原样复用承载方法学，agent.md 不内联方法学；
  `max_turns`/`model` 等每次调用维度下沉到 stage/SpawnAgent 配置。
- **数据流走 (c)**：运行时以 State 为事实源（保留编排解析/路由/fork-join 合并/docgen 渲染），
  skill 只做领域判断、**不跨读其他 skill 的 checkpoint**（铲除 AC0 控制流重复）；每 stage 产物
  确定性物化到按模板隔离的稳定路径，并支持单步调试时从产物文件**回灌** stage 输入。
  与 P2（隔离路径）、P3（控制流归 Python）、P6（产物清单）串到同一套机制。
- **上下文注入**：把算子名 / op_dir / 需求摘要 / 上游结构化产物注入 prompt/context，禁止 agent 靠猜。
- **加载期 fail-fast**：workflow 引用的每个 `agent_name` 必须解析到非占位系统提示词，否则启动报错。

### 决策记录（agent/skill 架构 + 数据流）

- **agent.md 必须放 `.claude/agents/`**：`load_agent_manifest` / `_find_agent_prompt` 硬编码该路径；
  `.claude/plugins/` 是 skill 专用布局（plugin.json + skills/<name>/SKILL.md），放 agent.md 不被读。
- **skill 加载靠 plugins，`skills` 字段是过滤器不是加载器**：已实证并记入 CLAUDE.md。
  `skills=[]` = 全抑制，是 skill 当前对所有 agent 失效的第二层根因。
- **Agent 不按子任务 1:1，而按权限 profile 角色化**：10 个 substage 是「同少数角色执行不同方法学」，
  把方法学维度焊进角色会牺牲可维护性（10 份样板）与可扩展性（加子任务要同时加 agent）。
- **角色挂多个 skill 不会上下文超载（D3 论证依据，已核实）**：SDK skill 是**两段式加载**——
  启动时只加载每个 skill 的 **name+description**（一句话元数据），**全文仅在被调用时 load**
  （`docs/agent-sdk-ref/skills.md:21`）。叠加 §P1 的「stage 显式指派」：每次 spawn 由
  `skills=["stage-design:<单个>"]` 过滤器只暴露当前步骤那一个 skill。⇒ generator 角色即便"理论上"
  可用十几个 skill，**运行时每个 spawn 实际只见 1 个被指派 skill 的描述 + 其全文**，上下文负担
  与"一步一专属 agent"几乎无差别。角色只承载工具/权限 profile（A 能写 / B 只改 / C 禁改），
  与 skill 数量解耦。
- **数据流四方案权衡 → 选 (c)**：
  - (a) 物化到盘让 skill 读盘：保留 skill 侧控制流（AC0 病根）+ 并行落盘冲突，架构倒退，否决。
  - (b) State 纯内存单源、磁盘只 write-only 投影：架构干净但**单步调试只能改整坨 state_snapshot**，
    无法靠编辑单个产物文件控制 stage 输入，调试性差。
  - (d) 磁盘为唯一事实源：State 含 node_status/配额/loopback history 等**运行时控制流状态**，
    无自然文件形态；fork-join 并行合并、部分重跑、resume 需用无事务的文件系统重写；
    且控制流回流 skill，与「routing in Python」冲突。代价大且无额外调试收益，否决。
  - **(c) State 为运行时事实源 + 磁盘产物为可回灌物化层**：运行时收益同 (b)，又补上 (a) 唯一真优点
    （盘上产物可直接编辑驱动调试），且物化是编排的确定性投影、非 skill 间隐式协议。**采纳**。

- **skill 仍直接读写文件——精确边界（避免误读「skill 不碰文件」）**：(c) 下 skill 照常用
  Read/Write/Edit 操作 cwd 文件，改的是「读写哪一类文件」，不是「不读写文件」：
  - **输出侧不变**：skill 依旧用 Write 把本步产物 JSON 写到工作目录（如 split 写
    `tiling_split.json`），这是 agent 产物收集（`_collect`/`changed_files.json`）的根基，不动。
  - **输入侧才是改造点**：现在 skill 读的是「别的 skill 写的 checkpoint」（anchor-check 读
    `checkpoints/tiling-split-{name}.json` 并校验 `status=="completed"`）——这是**跨 skill 的
    控制流耦合**，是 AC0 死循环病根（A 去找 B 从没创建的文件 → 误判未完成 → 死循环）。改造后
    skill 读的是**编排注入/物化给它的本步输入产物**（prompt 直接给 JSON，或编排把上游产物物化到
    其 cwd 确定路径供 Read），来源是编排对 State 的确定性投影（保证存在与正确）。
  - **一句话区分**：❌ 铲除「skill A 读 skill B 的 checkpoint 来判断 B 完成没/模板齐没/anchor 过没」
    （控制流）；✅ 保留「skill 读编排喂的输入、写自己的输出」（正常 IO）。判断「上游齐没齐、
    能否往下走」的控制流从 skill 移走、归 Python 编排。
  - 这正是映射表中「物化产物路径」与「requires(注入输入)」两列须一一对应的原因：保证 skill 要读的
    输入，编排都已确定性放到它能读到的位置；skill 永不跨读其他 skill 的 checkpoint。

### 详设 substage → 角色 / skill / 契约 / 物化路径 映射表

> 每行均来自源码（`design_substages.py` 的 agent_name / 契约 / schema_file / segment_key）与
> 对应 SKILL.md 核对。作为 L4 实施方案的域/契约输入，也是 (c) 回灌机制的完整性依据。

| # | stage (name) | 现 agent_name | 角色 | 复用 skill (stage-design:) | requires (注入输入) | provides | 物化产物路径 |
|---|---|---|---|---|---|---|---|
| 1 | gd-generate | ascendc-op-general-design | A | ascendc-op-general-design | requirement | general_design | design/gd-generate/general_design.json |
| 2 | general-design-review | ascendc-op-general-design-review | B | ascendc-op-general-design-review | general_design | general_design_reviewed | design/general-design-review/general_design_reviewed.json |
| 3 | dd-intake | ascendc-design-generator | A | ascendc-op-design-intake（D4 新建） | requirement + detailed_design_path（dev workflow 入口） | design_spec/tiling_strategy/kernel_architecture（短路） | design/dd-intake/*.json |
| 4 | template-division | ascendc-op-design-template-division | A | ascendc-op-design-template-division | general_design | template_division | design/template-division/template_division.json |
| 5 | split (×模板) | ascendc-op-tiling-split | A | ascendc-op-tiling-split | template_division | tiling_results[t].split | design/tiling/&lt;template&gt;/tiling_split.json |
| 6 | buffer-kernel (×模板) | ascendc-op-tiling-buffer-kernel | A | ascendc-op-tiling-buffer-kernel | template_division (+本模板 split) | tiling_results[t].buffer_kernel | design/tiling/&lt;template&gt;/tiling_buffer_kernel.json |
| 7 | precision-perf (×模板) | ascendc-op-tiling-precision-perf | A | ascendc-op-tiling-precision-perf | template_division (+本模板 split/buffer) | tiling_results[t].precision_perf | design/tiling/&lt;template&gt;/tiling_precision_perf.json |
| 8 | anchor-check | ascendc-op-design-anchor-check | C | ascendc-op-design-anchor-check | tiling_results | anchor_report | design/anchor-check/anchor_report.json |
| 9 | integrate | ascendc-op-design-integrate | A | ascendc-op-design-integrate | tiling_results, anchor_report | design_spec, tiling_strategy, kernel_architecture (+opt data_flow) | design/integrate/{design_spec,tiling_strategy,kernel_architecture}.json |
| 10 | docgen | （无 agent，确定性渲染） | — | — | design_spec, tiling_strategy, kernel_architecture | design_doc | design/docgen/design_doc.* |
| 11 | validate | ascendc-op-design-validate | B | ascendc-op-design-validate | design_doc | design_validated | design/validate/blocking_status.json |

> docgen 不 spawn agent（确定性渲染），不占角色；dd-intake 是 dev workflow 的详设输入入口
> （D4-1：删旧 `ascendc-op-detailed-design` + 新建 `ascendc-op-design-intake`）。

### 三角色契约定义（A/B/C 独立）

| | 角色 A 设计生成者 | 角色 B 质量门评审者 | 角色 C 外部锚点判定者 |
|---|---|---|---|
| 职责 | 按指派 skill 方法学产出结构化设计产物 | 校验上游产物、就地 Edit 可修项、报告不可修项 | 对 tiling claims 独立对照硬件 API 判可行性 |
| allowed_tools | Read/Write/Edit/Bash/Glob/Grep/Skill | Read/Edit/Bash/Glob/Grep/Skill | Read/Bash/Glob/Grep/Skill |
| **关键权限差异** | 可创作产物 | 只就地修，不重新创作 | **禁止 Write/Edit 产物**（只读+写报告） |
| 产出 | 各 stage 的设计 JSON | `*_reviewed`/`blocking_status` + 就地修订 | `anchor_report`（blocking_issues） |
| 用于 stage | 1,3,4,5,6,7,9 | 2,11 | 8 |

C 独立的依据：其「禁改产物」是**权限级**约束（SKILL 明确「不重新设计、不改产物」），用
`disallowed_tools` 在角色层表达，比靠 prompt 自律更可测、可校验——这也是「A/B/C 必须独立」的拍板理由。

### (c) 回灌机制完整性自检

- 每个 substage 的「物化产物路径」⇄「provides 的 State 字段」一一映射 → 回灌装载器据此实现：
  `stage run --name anchor-check` 从 `design/tiling/<t>/*.json` 读回重建 `tiling_results` 注入；
  改盘上某模板的 `tiling_split.json` 即可控制该 stage 输入（正面满足「编辑磁盘文件驱动调试」诉求）。
- tiling 三段按 `<template>` 子目录隔离 → 直接消除 P2 的覆盖问题。
- 每个 requires 都能从上游 provides 的物化文件取得，无一项需「读另一个 skill 的 checkpoint」 →
  验证 (c) 下 skill 不跨读、控制流归 Python。

---

## §P2 并行分支日志/产物归属

P2 是两个独立子问题：

1. **产物覆盖**（5 分支共用 `design/split`）—— **已被 §P1 数据流 (c) 解决**：tiling 三段物化路径
   带 `<template>` 子目录（`design/tiling/<template>/tiling_split.json`），分支隔离，不再覆盖。
   无需在 P2 单独处理。

2. **日志无法归属**（并发 turn 行只有 `agent_name`，看不出哪个模板）—— **独立缺口，本节处理**。

### 决策：分支标识用 SpawnAgent 一等字段 `branch_label` 透传（已拍板）

- 备选 (P2-a) 塞进 `SpawnAgent.context`：改动小，但 `context` 语义是「喂给 agent 的领域输入」，
  掺入展示用标识会污染语义。
- 备选 (P2-b) 给 `SpawnAgent` 加一等字段 `branch_label`（或 `instance_id`），从 fork-join 透传，
  backend 打日志 / 命名 transcript 时读它。**采纳**——可观测性标识是 spawn 的固有属性，
  不应寄生在 context；语义干净，代价是动 action 数据类 + runner + backend 三处签名（一次性）。
- 效果：`agent_stream [T3_QuarterFull] ascendc-op-tiling-split turn N`；transcript 文件名带分支标识，
  5 模板 × 多轮重跑可一一对应。

---

## §P3 loopback 黑盒

P3 也是两层：

1. **AC0 死循环根因**（anchor-check 跨读 tiling checkpoint 判控制流）—— **已被 §P1 数据流 (c) 解决**：
   anchor-check 改为消费编排注入的 `tiling_results`，不再找不存在的 checkpoint，控制流归 Python。

2. **loopback 不上控制台**（回退原因只进 events.jsonl）—— **独立缺口，本节处理**。

### 决策：Python 确定性拼接 blocking_issues 摘要上控制台（已拍板）

- **不需要 LLM**：`blocking_issues` 本身已是结构化字段
  （`{code, severity, detail, target, target_template}`），「摘要」不是 NLP 压缩，而是
  **字段选择 + 截断**，是确定性字符串操作。用 LLM 会引入不确定性/延迟/成本/幻觉，
  让可观测性日志不可信——日志的价值恰在忠实反映系统真实状态。
- **摘要方式**（Python 侧）：`detail` 本就是 skill 写好的人类可读一句话，无需再压缩，仅在过长时
  按字符数截断；一行 = `[{code}→{target}{/template}] {截断 detail}`。
  ```python
  def _summarize_issue(issue: dict) -> str:
      code = issue.get("code", "?"); target = issue.get("target", "?")
      tmpl = issue.get("target_template"); detail = (issue.get("detail") or "").strip()
      if len(detail) > 80: detail = detail[:77] + "..."
      tmpl_part = f"/{tmpl}" if tmpl else ""
      return f"[{code}→{target}{tmpl_part}] {detail}"
  ```
- **输出策略**：`graph_executor` 路由决策点新增 `Logger.action("loopback", ...)`，与现有
  `event_log.append(loopback())` 双写（控制台 + jsonl 一致）；控制台打前 N 条摘要（如 2 条）+
  `(+k more, see events.jsonl)`，**全量始终留 events.jsonl**，可回溯。
- 之所以能纯 Python 做，正是因为 §P1 的 (c) 把「领域判断的产出」规整成了结构化字段
  （skill 写 `code/detail/target`），编排只做确定性的展示与路由。
- 数据来源：quality-gate（anchor-check / validate / review）已写在 State 里的 `blocking_issues`，
  编排路由时本就读得到。

---

## §P4 stage-design skill 精选与对齐

- 移出 `ascendc-tiling-strategy`（归入 perf/codereview 系列或独立目录），它在 stage-design 下无调用方。
- **dd-intake 的 skill 处置（D4 已拍板：D4-1 删旧 + 新建 intake）**：`--detailed-design` 经核实
  **不是可选短路，而是 dev workflow（`generate_ascendc_dev`）的设计输入入口**——dev workflow root 为
  `entry→context→[general-design][detailed-design]→test_design→codegen→verify→perf→integrate→finalize`
  （workflow.py:466），design group 含 dd-intake；有详设文档时 dd-intake 解析三件套→short_circuit→
  validate→喂 codegen。全流程 `generate_ascendc` 也复用同一短路。⇒ 该功能是核心，**不可废弃**
  （废弃将同时打断 dev workflow 与全流程短路）。结论：
  - **删除** `ascendc-op-detailed-design`（旧的一体化生成实现，职责不符，是真正的历史债务）。
  - **新建** `ascendc-op-design-intake`（职责：忠实转写详设文档为 design_spec/tiling_strategy/
    kernel_architecture 三件套，不重新设计）。删旧 + 建新 = 清掉债务且保住 dev workflow 入口，零债务。
- 加一条加载期校验：stage-design 下的 skill 集合应与编排引用的 `agent_name`/`skills` 指派集合
  一一对应（多余/缺失都告警），呼应 §P1 的「加载期 fail-fast」。

---

## §P5 旧 agent 退役 + design_spec 权威来源定义

### 决策（已拍板）

- **`ascendc-designer` → 删除（不重写）**。核实：`src/` 无任何字面/间接调用，确认彻底悬空；
  其"单体一把生成详设三件套"的职责在新架构里已被 §P1 的角色 A + integrate/dd-intake 路径完整取代，
  无可复用的独立价值。强行重写等于造第二条 design_spec 生产路径，反违背"design_spec 唯一权威来源"。
- **design_spec/tiling_strategy/kernel_architecture 的唯一权威来源**：integrate 整合路径（正常流）
  + dd-intake 解析路径（短路流）。写进对应 agent/skill 的描述。

### 删除闭包（L4 待办——必须一次清干净，否则破坏测试/留失真文档）

ascendc-designer 的悬空不止一个文件，而是一组"单体 designer"陈旧叙事散落在测试与文档：

- **A 类 真依赖，删 .md 即破坏，必须同改**：
  - `tests/ut/capabilities/test_capabilities.py:693/712/714`：断言 ascendc-designer 存在且其
    manifest allow `mcp__engine__resolve_ambiguity` → 移除该断言项（requirement-analyst 同处已断言）。
  - `tests/ut/orchestration/test_kernel.py:1097`、`tests/ut/cli/test_cli.py:688/702`：仅把
    "ascendc-designer" 当字符串样例 → 换成在用 agent 名。
- **B 类 陈旧文档，删 .md 不报错但变失真孤儿，随设计阶段整体改造一并校正**：
  - `CLAUDE.md:96`（design 阶段=SpawnAgent("ascendc-designer")）、`docs/stages/design.md`（多处）、
    `docs/architecture-overview.md:344`、`docs/layers/L5-capabilities.md:142` → 更新为现行细粒度
    substage 编排（与"design_spec 唯一权威来源文档化"是同一件事）。
- **删除动作本身**：`.claude/agents/ascendc-designer.md`，与 A 类同一 commit 完成；可逆（git 历史可找回）。

> 为何不现在孤立删：干净删除的真实闭包已蔓延到测试（A 类）与多份文档（B 类），孤立删要么挂测试、
> 要么留失真文档，均违背"符合最新框架"原则。故归入 step-8 L4 实施项，连同代码改动可测试地完成。

### 其余 5 个在用 agent 的框架对齐（跨步骤提醒，归属 step-3）

- `ascendc-coder` / `incremental-developer` / `perf-tuner` / `requirement-analyst` / `test-designer`
  均在用（codegen/perf/requirement/test 阶段调用）。但 §P1 核查显示：除 requirement-analyst 外，
  它们多半也跑在 `skills=[]` 全抑制下（靠 body 内联方法学撑着，skill 未真正生效）。
- 这属于"在用但未必符合最新框架（角色化 + skills 指派）"，**牵涉 codegen/perf/test 三阶段，不在
  step-8（设计阶段）范围**。按总纲 step-3「其余阶段 skill plugin 化」统一改造，不塞进 step-8 扩大范围。


---

## §P6 阶段产物清单

- stage 结束时打印产物清单（相对路径 + 行数/字节），数据来自 `agent_result.artifacts` 或 working
  dir 扫描；与 §P2 的 `branch_label` 配合，让并行分支各自列清单。
- 与 (c) 的物化路径天然对齐：清单即「本 stage 物化到 `design/<stage>/...` 的文件」。

---

## §P7 其他问题的处理方向

1. **失败不再伪装成功**：stage 级别保留并上报失败状态，`done` 行区分 `✓ / ✗ / ⚠ partial`；
   `graph_executor._execute_atomic` 对非控制流异常不应照常标记 completed。**正确性底线，优先级高。**
2. **per-stage max_turns**（**低优先级遗留，暂不修改**）：取值依赖 §P1 修好后的真实重测数据
   （skill 真正加载 + 上下文注入后，agent 收敛轮数会变），现在拍值即猜；且它只影响"撞顶后多跑
   几轮"，不影响正确性。故暂不动，待 §P1 落地、积累重测数据后再评估是否需要 per-stage 配置
   （与 step-5b 的 per-stage timeout 同源）。
3. **停滞检测复核**：把「连续多轮无新产物文件」纳入停滞信号，堵住「无文本但反复无效工具调用」的
   退化路径。
4. **turn 计数口径对齐**：本地 `turn N/ceiling` 显示与 SDK 实际 max_turns 终止对齐，消除 `turn 31/15`
   这类语义混乱。
5. **跨 stage 上下文链端到端核对**：§P1 的「上下文注入」要覆盖概设/概设评审（gd-generate 猜 layernorm
   即此处缺失），确保 requirement 产物作为强上下文喂给下游。

---

## §P9 skill 投递机制 —— 本 CLI 下 skill 是 slash command，非 `Skill` 工具

> 问题证据见 `01-problems.md` P9（含直连 CLI 复现 + 真实链路 transcript）。这是 §P1 的**闭环阻断点**：
> L4-a 代码全就位（1220 UT/ST 绿），但 design agent 真实链路下拿不到 skill 方法学，根因是对 SDK/CLI
> skill 机制的假设错误，不在我方代码。

### 关键事实（已实测，2026-06-16）

- 本 CLI（2.1.178）把 plugin skill 暴露为 **slash command**（`/stage-design:<skill>`），CLI 可用
  `tools` 仅 `Bash/Edit/Read`，**没有 `Skill` 工具**。原 §P1 假设「把 `skills` 过滤器改成非空 allow-list
  即可让模型 tool-call skill」在本 CLI **不成立**。
- **SDK headless 可触发 slash command**：SDK 走 `--input-format stream-json` + stdin 传 prompt；首消息
  文本以 `/stage-design:<skill>` 开头时，CLI **确实展开** slash command，把 SKILL.md 方法学注入会话
  （实测 agent 随即按 skill 契约行事）。slash command **后可跟参数/上下文**，算子身份能一并带入。
- **`skills` 过滤器不收窄 slash 菜单**：传 `["stage-design:<单个>"]` 与 `"all"`，`slash_commands` 都列
  全部 12 个 stage-design skill。过滤器在 slash 模式下不做机制级收窄。

### 决策（已拍板：方案 2 为主 —— 编排预置 slash-command 触发）

- **采纳方案 2**：spawn 的首条消息以 `/stage-design:<skill>` 开头（编排按 `STAGE_SKILL_MAP` 拼），让 CLI
  确定性注入该 skill 方法学。理由：① headless 实测可行；② 与 TUI 的 `/skill` 习惯一致；③ 确定性由编排
  控制首消息保证，不靠模型自觉；④ 复用 SDK 既有 plugin 加载，改动小。
- **否决方案 1（编排读 SKILL.md 全文塞 prompt）的理由**：它要么注入全文（与方案 2 等效但绕过 CLI 原生
  机制、自造一套注入逻辑），要么只注入「要点」（破坏 SKILL.md 单一来源）。方案 2 用 CLI 原生 skill 通道，
  更贴合机制、维护面更小。方案 1 仅在「需规避 CLI slash 行为变化」时作为退路（见风险）。
- **否决方案 3（换 CLI）**：成本/可控性不确定，且方案 2 已在现版本可行，无需换。

### 已接受的取舍 / 风险

- **隐患 3（过滤器不收窄 slash 菜单）—— 判定可接受**：菜单列 12 个，但 SKILL.md **全文仅在被 `/` 触发时
  注入**（两段式加载下半段），实际进 agent 上下文的只有编排触发的那 1 个全文 + 其余的元数据。§P1「最小
  暴露」在**上下文负担**意义上成立；「机制锁定只能用 1 个」在 slash 模式做不到，但对 headless + 编排控首
  消息 + 单步单 skill 的场景非硬需求。
- **隐患 4（slash 展开稳定性 / 受 CLI 版本影响）—— 方案 2 唯一真实弱点**：依赖 CLI 的 slash 解析行为，
  换版本有回归风险。**缓解**：把现 xfail 的 ST `test_skill_invocation.py` 改写为方案 2 的守护——断言
  「首消息发 `/stage-design:<skill>` 后 agent 上下文出现该 skill 方法学」（而非断言 `Skill` tool_use）。
- **隐患 2（SKILL.md 重型文件契约与数据流 (c) 冲突）—— 与方案无关，归 L4-c**：被调起的 skill（实测）会
  按 SKILL.md 写死的契约找 `op_spec.md`/`template_division.md`/`checkpoint`/workdir。这与 §P1 数据流 (c)
  「skill 读编排注入的产物、不跨读 checkpoint」冲突。**无论方案 1/2 都需在 L4-c 改写 SKILL.md 输入契约**，
  否则 agent 仍去找不存在的文件（P3 的 AC0 病根）。P9 修复与 L4-c 的 SKILL.md 改写须协同。

### 实施落点（细化待 L4-a 续作 / 新增实施项）

1. **substage 拼首消息**：design substage 的 spawn prompt 首行改为 `/stage-design:<STAGE_SKILL_MAP[name]去掉plugin前缀>`
   触发；其余算子上下文/产物注入跟在其后。需确认 slash 名格式（`/stage-design:ascendc-op-tiling-split`）。
   `skills=[...]` 过滤器可保留（控制元数据暴露），但不再是「让模型能调用」的手段。
2. **改写 ST 守护**（隐患 4）：`test_skill_invocation.py` 去 xfail，改断言 skill 方法学进入上下文。
3. **L4-c 协同**（隐患 2）：SKILL.md 输入契约从「找 checkpoint/op_spec.md/workdir」改为「读编排注入产物」。

> 在 P9 落地（首消息 slash 触发 + ST 守护翻绿 + SKILL.md 契约改写）前，§P1 不算闭环。

---

## 待你拍板/待 L4 细化的开放点

### 已拍板/已定（存档）

- §P5：ascendc-designer 处置 —— **已拍板：删除**（删除闭包见 §P5，作为 L4 实施项）。
- §P7.2：per-stage max_turns —— **已定：低优先级遗留，暂不修改**（依赖 §P1 重测数据，且不影响正确性）。
- **D1 agent.md 组织方式 —— 已定：(a) 维持扁平 + `ascendc-<stage>-<role>` 命名前缀分组**（零框架改动；
  分子目录会因查找路径硬编码扁平而使 agent 找不到、重新引入 P1）。
- **D5 L4 拆分 —— 已定：四份** a(§P1) / b(§P2+§P3+§P6 可观测性) / c(§P4+§P5 清理) /
  d(§P7.1/7.3/7.4/7.5 正确性)。
- **D6 §P3 控制台摘要条数 —— 已定：前 2 条**，余数 `(+k more, see events.jsonl)`。
- **D7 stage→skill 映射的配置位置 —— 已定：(ii) 集中配置表，套用现有 STAGE_MODEL_MAP 范式**。
  - 现状惯例：`STAGE_MODEL_MAP`（stage→model）配在 `resources/orchestration-config.json`（编排调优
    单一事实源）的 `models` section，由 `model_config.py` 加载，runner 用 `.get(stage_name)` 查。
  - D7 落点：在同一 json 加 `skills` section（如 `{"skills": {"stages": {"split":
    "stage-design:ascendc-op-tiling-split", ...}}}`），仿 `model_config.py` 加载为 `STAGE_SKILL_MAP`；
    design substage `actions()` 用 `skills=[STAGE_SKILL_MAP.get(self.name)]`（取代 L4-a 任务 3 原
    "写 stage 类属性" 预设）。
  - 顺带使 §P4 一致性校验自然落地：校验 `STAGE_SKILL_MAP` 值集合 ⇄ stage-design 插件实际 skill 集合一一对应。
  - 否决的候选：(i) 写 stage 类属性（映射散在各类，不集中）；(iii) 从 agent.md 读（角色化后
    1 角色复用多 stage，agent.md 无"当前是哪一步"信息，语义对不上，除非放弃角色化退回一 stage 一 agent）。
- **D2 角色命名 —— 已定（认可）**：三角色文件名/agent_name 为 `ascendc-design-generator /
  -reviewer / -anchor`。**附加约束**：因 1 个角色 agent 被多个 stage 复用，运行日志必须能清晰分辨
  当前是哪个 stage（而非只看到角色名）—— 见 D8。
- **D3 角色数量 —— 已定（确认）**：A/B/C 三角色（A 生成 / B 评审 / C 锚点；C 因"禁改产物"独立）。
  agent 个数 = 角色数 = 3，与 stage 数/命名无关；每次 spawn 由 D7 配置只指派 1 个 skill，
  叠加两段式加载 → generator 复用多 stage 不会上下文超载（论证见 §P1 决策记录）。
- **D4 dd-intake skill 处置 —— 已定：D4-1（删旧 + 新建 intake）**：`--detailed-design` 经核实是
  **dev workflow 的设计输入入口**（非可选短路），功能不可废弃；删名实不符的 `ascendc-op-detailed-design`
  （历史债务）+ 新建 `ascendc-op-design-intake`（只做转写）。详见 §P4。

  - **dd-intake 在编排里的挂载位置（以代码为准，`design_tree.py:140-163`）**：它不是顶层 stage，而是
    `detailed-design` 这个 CompositeGroup 的**第一个子节点**（`AtomicStage(DetailedDesignIntakeStage())`），
    组内层级路径为 `detailed-design/dd-intake`，`stage.name == "dd-intake"`。组结构为
    `dd-intake → template-division → tiling[ForkJoin] → anchor-check → integrate → docgen → validate`。
    短路由组的 transition_table 控制：`_DETAILED_DESIGN_TRANSITION_TABLE` 中
    `"dd-intake": {"short_circuit": ("validate", "validation")}` —— resolve 出 `short_circuit` 时组内
    直接跳到 `validate`，跳过中间 5 个节点。该详设组被 dev workflow 与全流程（generate_ascendc）共用，
    故短路对两条流水线都生效（这正是"废弃将同时打断二者"的原因）。
  - **dd-intake 的两种运行形态**：有 `--detailed-design` 文档 → spawn agent 解析文档为三件套
    （design_spec/tiling_strategy/kernel_architecture）→ `resolve_condition` 返回 `short_circuit`；
    无文档 → `actions()` 返回 `[]`（no-op 透传）、`resolve_condition` 返回 `default`，组走正常生成流程。
  - **`ascendc-op-design-intake` 的职责契约（D4 原文未展开，此处补全）**：一个**极薄的转写 skill**，
    职责单一——把人类写好的详设文档**读入、转成机器结构**，不做任何设计推导。
    - 输入：用户详设文档全文（已由 `DetailedDesignIntakeStage._build_prompt` 注入，8000 字上限）+ requirement。
    - 输出：`design_spec.json` / `tiling_strategy.json` / `kernel_architecture.json`（+ 可选 `data_flow.json`），
      schema 由 `DetailedDesignIntakeStage.artifact_contract()` 约定。
    - **禁止**：spawn SubAgent、做 Phase 推导、写 execution_state.json、跨读其他 skill 的 checkpoint、
      AskUserQuestion 决策门控——这些恰是 §P1 数据流 (c) 要铲除的旧 skill 行为。
    - 方法学只有一条：**忠实映射文档章节到三件套字段，文档没写的标为缺失/null，绝不脑补设计**。
  - **与被删 `ascendc-op-detailed-design` 的本质差异（名实不符的根因）**：旧 skill 是**一体化详设生成器**
    —— Phase 1 语义理解 → Phase 2 设计推导（全局分析 SubAgent + per-template SubAgent）→ Phase 3 文档生成
    → GV 全局校验 → 反馈收集，贯穿 execution_state.json 断点恢复，自带 SubAgent 编排与 AskUserQuestion
    决策门控（见其 SKILL.md）。它做的是"从概设**生成**详设"，与 dd-intake 这个 stage 需要的"读入现成
    文档**转写**为结构"语义相反。⇒ 用 detailed-design 当 dd-intake 的 skill 是**名实不符**（stage 要 intake，
    skill 给 full generation），且其"生成 + 自带编排 + 跨 skill 控制流"与当前架构（细粒度 substage +
    控制流归 Python + 数据流 c）整体冲突，故判历史债务删除。**一句话类比**：intake 之于 detailed-design，
    如同"OCR 录入"之于"建筑设计"——同样产出三件套，一个是转录、一个是创作。
  - **复用角色 A 的张力与约束（L4-c 实施须显式处理）**：dd-intake 的角色定为 A（generator，有 Write）。
    但 intake 本质是"读入转写"而非"创作"，从权限洁癖看更像"解析器"。然而现有三角色无"解析者"，硬加第四
    角色违背 D3（三角色定型）的克制；而 generator 的 Write 权限对"写出三件套 JSON"确属必要，故复用 A 是
    合理折中。代价：intake 的 SKILL.md body **必须**用"忠实转写、禁止重新设计"的指令约束住 generator，
    不让它在 intake 场景下发挥创作。这条约束是 intake skill 的核心，L4-c 建该 skill 时须显式写进 SKILL.md。

- **D8 角色 agent 复用下的 stage 日志可分辨性 —— 已定（认可候选）**：generator 等角色被多个 stage
  复用，现有日志（`agent_stream {agent_name} turn`）只打角色名，无法分辨当前 stage。**采纳**：给
  `SpawnAgent` 加一等字段 `stage_name` + `branch_label`，从 substage 填充、经 runner 透传到 backend，
  turn 日志与 transcript 文件名带前缀 `[{stage}/{template}]`（tiling 模板名来自
  `template_division.templates[].name`，编排内唯一）。与 §P2 的 `branch_label` 透传同源，
  **L4-b 任务 1 实施**（细化见 `03-impl-b-observability.md`）。

### 待决策（未拍板）

- **D9 dev workflow 结构化详设直通入口（对应 `01-problems.md` P8，新登记）**：当拼接的详设来自本工程
  设计者流程（已是/能无损还原成三件套 JSON）时，经 `--detailed-design` 走 dd-intake 的 LLM 解析短路存在
  冗余（结构化→文档→再 LLM 解析回结构化 + 潜在转写损耗）。step-8 任务 5 的回灌 `design_artifacts_to_state`
  已能不经 LLM 重建三件套，但只接在单 stage 调试入口；dev workflow 主入口尚无"结构化产物直通、跳过
  dd-intake LLM 解析"的路。**仅登记，不展开方案——留待当前 step-8 L4 全部开发任务完成后再做详细设计。**

### 实施顺序

- 见总纲 `../skills-integration-and-tdd-plan.md` step-8 索引行；L4 实施配方拍板后按需产出 `03-impl-*.md`。

---

