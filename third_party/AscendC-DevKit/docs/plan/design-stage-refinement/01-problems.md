# 设计阶段精细化 — L1 问题记录（2026-06-15）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/现象/根因/影响）。
> 修复方案见同目录 `02-analysis.md`（L3）；工作步骤与状态见总纲 `../skills-integration-and-tdd-plan.md`（L2）。
>
> **状态：已收口 / superseded（2026-07-09）**。P1–P7、P9 已全部解决——或直接修复、或并入现行权威 track `self-evolution/06-problems.md`。按 §1.8，「修复记录」产权转移至 self-evolution，本文件只保留「事实记录」产权。去向（于当前代码核实）：
> - P1（最致命：详设 agent 未加载 skill、裸提示词+空上下文）→ 直接修复：skill 名角色 agent + slash 注入；`skills=[]` 抑全 bug 治愈
> - P2（fork-join 共用 working dir 产物互相覆盖）→ 直接修复：`_TilingSegmentStage._working_dir` 逐模板隔离
> - P3（loopback 黑盒、回退原因不上控制台）→ 直接修复（`_log_loopback`/`render_issue`）+ self-evo **P25**
> - P4（skill dir 混入非同系列/旧 skill）→ 直接修复：清理 + `validate_skill_map()` 启动期一致性校验
> - P5（ascendc-designer.md 脱节、design_spec.json 来源未定义）→ 直接修复：旧 agent 退役，改 ascendc-design-generator/-reviewer/-anchor
> - P6（阶段结束未列产物清单）→ 直接修复：`Logger.stage_done` 逐产物打印
> - P7（错误吞仍打 ✓ / max_turns / 停滞）→ 直接修复：`run_stage` 异常 re-raise、`max_turns=10000`、停滞指纹 tool_use
> - P9（skill 是 slash command 非 Skill 工具）→ 直接修复（同 P1 slash 注入机制）
> - **P8（低，未做）**：`--detailed-design` 结构化捷径省冗余 LLM 解析——非正确性、窄适用，已挂 self-evo **P37** 暂缓（优先级中）。**本 track 唯一未闭环项。**

本记录基于一次 `ascendc-devkit run` 的真实运行（rotary_position_embedding 算子，
incremental / non-interactive 模式），结合日志、`events.jsonl`、运行产物目录与源码逐条核对。

运行命令：

```
ascendc-devkit run \
  --op-dir /home/.../ops-transformer/posembedding/rotary_position_embedding \
  --requirement /home/.../tests/fixtures/rope_requirements.md \
  --mode incremental --non-interactive --on-decision default \
  --workflow-timeout 7200
```

日志文件：`rope-e2e-20260615-163757.log`
运行目录：`output/20260615-083757-dd75e9/`

运行形态：requirement → 概设 → 概设评审 → 详设（template-division → tiling[5 模板并行] →
anchor-check → ...）。详设阶段 anchor-check 连续两次回退到 tiling（`loopback count 1/3、2/3`），
tiling 各 segment 反复重跑，最终卡在详设循环。

> 结论速览：**最致命的是 P1 —— 详设各阶段的 agent 根本没有加载到对应 skill / 系统提示词，
> 在"裸提示词 + 空上下文"下运行**（`gd-generate` agent 自述"the specific operator wasn't
> provided"）。这同时解释了用户反馈的"详设黑盒 loopback""skill checkpoint 全部消失"
> "产物不符预期"。其余问题（P2 并行日志/产物目录冲突、P3 loopback 不可见、P4/P5 skill 与
> agent 描述失配）多为此根因的并发表现或独立可观测性缺口。

---

## P1（最致命）：详设各阶段 agent 未加载 skill，跑在"裸提示词 + 空上下文"下

### 证据

`events.jsonl` 的 `spawn_context` 显示，除 `requirement-analyst` 外，所有详设 agent 的
`skills=[]`：

```
ascendc-op-general-design          | skills= []
ascendc-op-general-design-review   | skills= []
ascendc-op-design-template-division| skills= []
ascendc-op-tiling-split            | skills= []  (×15)
ascendc-op-tiling-buffer-kernel    | skills= []  (×10)
ascendc-op-tiling-precision-perf   | skills= []  (×10)
ascendc-op-design-anchor-check     | skills= []  (×2)
requirement-analyst                | skills= ['stage-requirement', 'shared']   ← 唯一正常
```

`gd-generate` 的 transcript（`agents/ascendc-op-general-design-01.jsonl` turn 1）：

```
"the specific operator wasn't provided, I'll build a normalization gradient
 design that likely involves layer normalization based on the context."
```

agent 在不知道算子是什么的情况下凭空猜了一个"layernorm 归一化梯度"设计。

### 根因

1. **agent 文件缺失**：`design_substages.py` 用 skill 名作为 `agent_name`
   （`ascendc-op-general-design`、`ascendc-op-tiling-split` 等），但 `.claude/agents/`
   下**没有**这些 `.md` 文件（只有 `ascendc-designer.md`、`ascendc-coder.md` 等 6 个旧 agent）。
2. `runner._execute_spawn_agent` 通过 `load_agent_manifest(agent_name)` 解析 plugins，
   文件不存在 → 返回空 manifest（`plugins=[]`）；`SpawnAgent`（design_substages 第 78 行）
   又**没有传 `plugins=` 兜底** → `effective_plugins=[]` → SDK 不加载任何 stage-design 插件，
   skill 无法被 model 发现。
3. `sdk_backend._find_agent_prompt` 找不到 agent.md → 回退到
   `"You are {agent_name}. Complete the task as described."` 这条**通用占位系统提示词**。
4. **（第二层根因，独立于上述）`skills=[]` 把 skill 全过滤**：即使前三点修好、plugin 被加载，
   `sdk_backend._spawn` 仍写死 `skills=skills or []`，而 `runner.spawn` 从不传 `skills=` →
   实参恒为 `[]`。按 SDK 语义 `skills=[]` = **全部抑制**（含 plugin 已加载的 skill，列表隐藏 +
   Skill 工具拒绝调用，见 `docs/agent-sdk-ref/skills.md`、`types.py` 的 `skills` docstring，
   已记入 CLAUDE.md）。实证：本次 run **无任何 agent 调用过 Skill 工具**；唯一 plugins 非空的
   `requirement-analyst` 能跑，是因为方法学**内联在 agent.md body 里**（不依赖 skill 调用），
   并非 skill 生效。⇒ skill 机制对所有 agent 当前实际是「死」的。

于是 SKILL.md 里沉淀的设计方法学（切分轴优先级、TilingData、checkpoint 写出约定等）
**完全没有进入 agent 的上下文**——既因没加载（根因 1/2），也因加载了也被过滤（根因 4）。

### 影响

- 用户反馈 3「skill 输出的 checkpoint 完全没有了」：SKILL.md 中 10 个 skill 都约定写
  `checkpoints/*.json`（已核对），但 skill 没被加载 → checkpoint 永不产生。
- 用户反馈「产物不符预期」：agent 在裸提示词下自由发挥，质量不可控。
- 详设 loopback（见 P3）的深层诱因之一：缺方法学约束导致产物残缺。

> 修复方案见 `02-analysis.md` §P1（agent 角色化 / stage 指派 skill / 数据流 (c) / 上下文注入 / fail-fast）。

---

## P2：fork-join 多分支共用同一 working dir + 同名日志，产物互相覆盖、日志无法区分

> 对应用户反馈 1（缺产物清单）与 2（并行日志看不出是哪个模板）。

### 证据

- template-division 切出 **5 个模板**：`T1_HalfFull / T2_InterleaveFull / T3_QuarterFull /
  T4_InterleaveHalfFull / T5_InterleaveHalfPartial`（`template_division.json`）。
- 日志里 5 个 split agent 并发，turn 行**完全交错且无模板标识**：

  ```
  • agent_stream ascendc-op-tiling-split turn 1/15, 558 chars, 13.5s
  • agent_stream ascendc-op-tiling-split turn 1/15, 730 chars, 18.2s
  • agent_stream ascendc-op-tiling-split turn 3/15, 639 chars, 21.5s
  ... 5 路 turn 计数各自独立，混在一起完全无法判断属于哪个模板
  ```

- 产物目录 `artifacts/design/split/` **只有一份** `tiling_split.json`（应有 5 份）。
  `buffer-kernel/`、`precision-perf/` 同理各只剩一份。

### 根因

1. `design_substages.py:82`：`working_dir = artifacts / "design" / self.name`。`self.name`
   对同一 segment 的所有分支是**同一个常量**（`"split"`），5 个并行分支因此被塞进同一目录，
   后写覆盖先写 → 4 个模板的产物丢失。State JSON 侧靠 `tiling_results[{template}]` 隔离没问题，
   但**落盘文件被覆盖**，导致无法 debug 单模板中间产物，也是 anchor-check 读不到产物的来源之一。
2. `Logger.action("agent_stream", f"{agent_name} turn ...")`（`sdk_backend.py:515`）只打
   `agent_name`，不带分支/模板标识；并发分支共用同一 `agent_name` → 日志无法归属。
3. `SDKBackend._spawn_seq` 与 transcript 文件名按 `agent_name` 计序
   （`agents/ascendc-op-tiling-split-01..15.jsonl`），15 个文件名也无法对应回 5 个模板 × 多轮重跑。

### 影响

- 用户无法 debug 单模板中间产物（产物被覆盖 + 日志不可归属）。
- 这是 P3 loopback 的直接物理原因之一：tiling 产物没能完整落到 anchor-check 能读到的位置。

> 修复方案见 `02-analysis.md` §P2（产物覆盖已由数据流 (c) 解决；日志归属用 SpawnAgent 一等字段
> `branch_label` 透传）。

---

## P3：详设 loopback 黑盒——回退原因不上控制台，checkpoint 缺失

> 对应用户反馈 3。

### 证据

- 控制台只看到 `split / buffer-kernel / precision-perf` 不断重跑，**看不到任何"为什么回退"**。
- 回退原因只写进了 `events.jsonl`，控制台无对应输出：

  ```json
  {"type":"loopback","scope":"generate_ascendc/detailed-design",
   "from_node":"anchor-check","to_node":"tiling","route_type":"corrective","count":1,"max":3}
  {"type":"loopback",... "count":2,"max":3}
  ```

- 真正的回退动因在 `anchor_report.json`：

  ```json
  {"code":"AC0","severity":"blocker",
   "detail":"工作目录无任何 tiling 产物可对质（缺失 tiling 头/源、template 分支文件、
             TilingData 定义等），anchor-check 无法对照真实硬件 API 进行核验",
   "target":"tiling"}
  ```

  即 anchor-check 在自己的隔离 working dir（`artifacts/design/anchor-check/`，里面只有它自己
  写的两个文件）里**根本读不到 tiling 产物**，于是判 AC0 阻塞 → 回退 tiling → 再跑还是读不到 →
  耗尽 corrective 配额（max=3）。

### 根因

1. **可观测性**：`graph_executor._execute_sequential` 在路由回退时只 `event_log.append(loopback())`，
   **没有任何 `Logger` 输出**到 stderr/控制台；`stage_iteration` 日志也只打 `iteration N/ceiling`，
   不打"本次为何重来"。用户看到的就是黑盒重跑。
2. **checkpoint 缺失**：根因即 P1——skill 没加载，约定的 `checkpoints/*.json` 不产生；
   编排侧也没有把 quality-gate 的 `blocking_issues` 回显到控制台。
3. **anchor 读不到产物**：anchor-check 的 working dir 与 tiling 产物目录隔离（且 P2 还覆盖），
   skill 期望"在工作目录对质 tiling 文件"，但编排是按 State JSON 传递产物的——
   **skill 的工作假设与编排的数据流不一致**。

### 影响

- 详设阶段对用户完全黑盒，无法判断是设计真有问题还是流水线自身缺陷（本例是后者）。
- 大量无效重跑（5 模板 × 3 segment × 多轮）烧时间与 token。

> 修复方案见 `02-analysis.md` §P3（AC0 根因已由数据流 (c) 解决；loopback 控制台输出用 Python
> 确定性拼接 blocking_issues 摘要，前 N 条上台、全量留 jsonl）。

---

## P4：stage-design/skills 目录里混入了非同系列 / 旧版 skill

> 对应用户反馈 4。

### 证据

`.claude/plugins/stage-design/skills/` 现有 13 个 skill，但与编排实际调用的不匹配：

- 编排实际用到（design_substages 的 `agent_name`）：`ascendc-op-general-design`、
  `ascendc-op-general-design-review`、`ascendc-op-design-template-division`、
  `ascendc-op-tiling-split`、`ascendc-op-tiling-buffer-kernel`、`ascendc-op-tiling-precision-perf`、
  `ascendc-op-design-anchor-check`、`ascendc-op-design-integrate`、`ascendc-op-design-docgen`、
  `ascendc-op-design-validate`（共 10 个，docgen 实际是确定性渲染、不 spawn agent）。
- **`ascendc-tiling-strategy`**：frontmatter 自述"tiling 代码需要优化或审查……通过 Agent
  subagent 执行"，是**性能/代码审查系列**的优化型 skill，与本阶段"从需求推导设计"的 substage
  不是一个系列，放在 stage-design 下无对应调用方，纯噪声。
- **`ascendc-op-detailed-design`**：frontmatter 自述编排"Phase 1 语义理解 → Phase 2 设计推导 →
  Phase 3 文档生成 → 全局校验 → 反馈收集"，是**老版本一体化详设**实现；当前详设已拆成
  template-division→tiling→anchor→integrate→docgen→validate 的细粒度 substage。它仅被
  `dd-intake`（解析用户提供的现成详设文档的短路分支）以 `agent_name` 引用，承担的语义已和
  其 SKILL.md 描述的"从概设生成详设"完全不同 → 描述与实际用途失配。

### 根因

skill 目录是历史多版本叠加，没有按"当前稳定 substage 流水线"做过一次清理与对齐；
skill 名集合 ≠ 编排调用名集合，二者无强校验。

### 影响

- 干扰维护者判断"哪个 skill 真正生效"。
- `ascendc-op-detailed-design` 描述失配，易被误用/误改。

> 修复方案见 `02-analysis.md` §P4（移出 ascendc-tiling-strategy；重定义 dd-intake 的解析 skill；
> 加 skill 集合 ⇄ agent_name 集合一致性校验）。

---

## P5：`ascendc-designer.md` 等旧 agent 描述与现行编排脱节，design_spec.json 来源未定义

> 对应用户反馈 5。

### 证据

- `.claude/agents/ascendc-designer.md` 描述自己"一把生成 design_spec.json / tiling_strategy.json /
  kernel_architecture.json / data_flow.json"，并给了一套**极简、与现行 schema 不符**的 JSON 模板
  （如 `tiling_strategy` 只有 `tile_size/core_strategy/ub_usage`）。
- 但现行详设流水线**根本不调用 `ascendc-designer`**（已 grep 确认 src 中只有 design_substages
  以 skill 名作 agent_name），design_spec/tiling_strategy/kernel_architecture 实际由
  `IntegrateStage`（agent `ascendc-op-design-integrate`）汇聚 tiling 产物整合而成，或由
  `dd-intake` 从用户文档解析。
- 因此 `ascendc-designer.md` 描述的 "design_spec.json 来源" 与真实数据流**不一致**，
  且该 agent 处于"悬空"状态（有文件、无调用方）。

### 根因

agent 文件未随"单体 designer → 细粒度 substage"重构同步更新/退役；design_spec 的
**权威来源（integrate 整合 vs dd-intake 解析）**没有在 agent/skill 层面写清楚。

### 影响

- 维护者读 `ascendc-designer.md` 会被误导以为它是 design_spec 的生产者。
- 与 P1 叠加：真正需要的 `ascendc-op-*` agent 文件缺失，不需要的旧 agent 还在。

> 修复方案见 `02-analysis.md` §P5（文档化 design_spec 唯一权威来源；退役/重写 ascendc-designer；
> 与 P1 角色化统一）。

---

## P6：阶段结束未列出产物清单，难以核对中间产物

> 对应用户反馈 1。

### 证据

`Logger.stage_done` 只打印 `✓ <stage> done (<elapsed>)`（`logger.py:18`），
不列出该 stage 产出/改动了哪些文件。用户需手动 `find output/.../artifacts/<stage>` 才能看到产物。

### 根因

`runner` 在 `stage_complete` 事件里只带 `total_iterations`，没有把 `agent_result.artifacts`
的文件清单回显到控制台。

> 修复方案见 `02-analysis.md` §P6（stage 结束打印产物清单，与 P2 的模板标识配合）。

---

## P7：其他确认的问题（独立于上述主线）

1. **错误被吞、仍打 `✓ done`**（沿袭历史问题，仍存在）：
   - `[ERROR] Agent ascendc-op-tiling-split query attempt 1 failed: Reached maximum number of
     turns (15)` 之后紧跟 `✓ split done (358.7s)`（log 507/508 行）。
   - `[ERROR] Agent ascendc-op-design-anchor-check query attempt 1 failed: Missing required
     field in assistant message: 'signature'` 之后紧跟 `✓ anchor-check done (119.0s)`（log 561/562）。
   根因：`graph_executor._execute_atomic` 对非控制流异常 `Logger.error` 后**照常标记 completed
   并线性前进**；`sdk_backend` 对崩溃且无产物只在有产物时降 `partial`。结果是失败 stage 对外仍显成功。

2. **`max_turns=15` 对详设 tiling 偏紧 → 频繁撞顶**：
   日志多处 `turn 16/15 ... turn 31/15`，并最终 `Reached maximum number of turns (15)`。
   说明 15 轮对"读上游 + 推导 + 写多文件 + 自检"的 tiling segment 不够，agent 在撞顶前未必收敛。

3. **agent 空转/停滞迹象仍在**：连续 turn 字符数不变（如 split `turn 13/14/15/16 均 3553 chars`、
   precision-perf `turn 14..19 均 3040 chars`）。已有 `MAX_STALLED_TURNS=3` 停滞检测，但这里靠
   `had_tool_use` 复位，疑似有"无文本但反复无效工具调用"的退化路径未被截断。

4. **`turn N/15` 计数会超过 ceiling 仍继续**：日志出现 `turn 31/15`，说明流式 turn 计数与
   SDK 的 max_turns 终止不是同一把闸（SDK 侧到 15 才报错终止，本地计数继续累加显示）。属显示语义混乱。

5. **概设/概设评审同样跑在裸提示词下**（P1 的同源表现）：`gd-generate` 猜成 layernorm，
   说明 requirement 产物没有作为强上下文喂给概设 agent，跨 stage 的产物传递链需端到端核对。

> 修复方案见 `02-analysis.md` §P7。

---

## P8：dev workflow 用本工程设计者流程产出的详设时，经 `--detailed-design` 走 LLM 解析短路存在冗余

> 本条为 step-8 L4-a 实施期间发现的新优化点（2026-06-16）。**仅登记，不展开方案**——
> 留待当前 L4 全部开发任务完成后再做详细设计。

### 现象/证据

- `--detailed-design <文档>` 当前走短路：dd-intake spawn 一个 agent 把**散文详设文档**解析回三件套
  （design_spec/tiling_strategy/kernel_architecture），再经 validate→codegen（`design_tree.py:47-49`
  `"dd-intake": {"short_circuit": ("validate","validation")}`；CLI `run.py:32`）。
- 该路径假定输入是**人类写的文档**：`DetailedDesignIntakeStage._read_doc` 读全文（8000 字上限）塞进
  prompt 让 agent 理解转写。

### 冗余所在

当用户拼接的两段是**同一工程的设计者流程产出**（详设本就来自上游 design 组、已是/能无损还原成三件套
JSON，落在 `artifacts/design/integrate/*.json`）时，会出现一次无意义的来回：

```
上游已产出结构化三件套 → 人工渲染成 markdown 详设 → dd-intake 又用一次 LLM spawn 反向解析回三件套
```

结构化→文档→再解析回结构化，不仅多一次 LLM 调用，还可能在 LLM 转写中引入信息损耗/漂移——源头本是
干净 JSON。

### 与现有机制的关系（仅指明方向，不在此定方案）

- step-8 任务 5 的回灌 `design_artifacts_to_state(artifacts_dir)`（数据流 (c)）已能**不经 LLM**从上游
  run 的 `artifacts/design/` 直接重建三件套，但当前只接在**单 stage 调试入口**
  （`dispatcher._build_state_for_stage` 的 `--sources` 层）；dev workflow **主入口**没有"结构化产物
  直通、跳过 dd-intake 的 LLM 解析"这条路。
- 理想形态（待详设）：给 dev workflow 增一条"结构化详设直通"入口，复用回灌把三件套直接注入 codegen，
  省掉 dd-intake 的 LLM spawn。与"散文文档 → LLM 解析短路"并存，按输入形态二选一。

### 影响

- 限定场景（详设来自本工程设计者流程）下的一次冗余 LLM 调用 + 潜在转写损耗。非正确性问题，属效率/保真
  优化。普通场景（人类手写散文详设）仍需现有 LLM 解析短路，不受影响。

---

## P9（重大，推翻 P1 修复假设）：本 CLI 版本下 skill 是 slash command，不存在可被模型工具调用的 `Skill` 工具

> step-8 L4-a 验收期间发现（2026-06-16）。这是 §P1 修复的**闭环阻断点**：L4-a 任务 1-5 的代码改动
> 全部正确（透传链/角色/指派/上下文/数据流，1220 UT/ST 全绿），但"让 design agent 真正调用 skill"
> 这个 §P1 终极目标在真实链路下**仍未达成**，且根因不在我们的代码，而在对 SDK/CLI skill 机制的
> 假设错误。

### 证据（不经我方代码，直接复现）

用真实 `claude` CLI（2.1.178）按我方 backend 等价参数发起，抓 `system` init 事件：

```
claude --print --output-format stream-json --verbose \
  --allowedTools "Read,Write,Edit,Bash,Glob,Grep,Skill,Skill(stage-design:ascendc-op-tiling-split)" \
  --setting-sources project,local \
  --plugin-dir <repo>/.claude/plugins/stage-design \
  --plugin-dir <repo>/.claude/plugins/shared \
  "本步骤方法学由 skill stage-design:ascendc-op-tiling-split 承载。请调用该 skill。"
```

system init 返回：
```
tools:          ['Bash', 'Edit', 'Read']            ← 没有 Skill 工具；甚至大部分 allowedTools 被忽略
slash_commands: [..., 'stage-design:ascendc-op-tiling-split', ...]  ← skill 被发现，但身份是 slash command
```

真实 LLM 链路（新增 ST `test_skill_invocation.py`，21 分钟 3 次尝试）佐证：agent transcript 原话
**"I don't see a direct skill tool in my current set"**，于是退而用 `Bash find SKILL.md` + `cat` 读取
skill 文件内容——绕开机制。手动用 `/stage-design:ascendc-op-tiling-split` slash command 触发则正常：
CLI 把 SKILL.md 注入会话，agent 随后用 Bash/Read 执行其方法学。

### 根因

- **本 CLI 版本（2.1.178）把 plugin 提供的 skill 暴露为 slash command（`/plugin:skill`），不暴露为
  一个通用 `Skill` 工具**。SDK `subprocess_cli._apply_skills_defaults` 在 `skills` 为 list 时只把
  `Skill(<name>)` 模式加进 allowedTools，但 CLI 实际可用 `tools` 仍只有 Bash/Edit/Read，没有 `Skill`。
- slash command **只能由用户键入**触发；编排发给 agent 的是自然语言 prompt（"请调用该 skill"），
  模型无法自行发出 `/slash-command`，也没有 Skill 工具可调 → 必然落到 Bash 读文件的退化路径。
- ⇒ §P1 与 CLAUDE.md 记录的「`skills` 是过滤器、改成非空 allow-list 就能让模型调用 skill」这一假设，
  **在本 CLI 版本不成立**：过滤器能控制 slash command 集合，但无法凭空造出一个工具调用入口。

### 已确认不是问题的点（缩小排查面）

- plugin 加载正常：skill 确实被发现（出现在 `slash_commands`）。
- 我方 backend 的 `skills=skills`、runner 透传、`STAGE_SKILL_MAP` 指派、allowed_tools 含 "Skill" 均正确。
- 失败的不是这些代码，而是"模型经 Skill 工具调用 skill"这条路径在本 CLI 根本不存在。

### 影响

- §P1 修复**未闭环**：design agent 仍拿不到 skill 方法学（除非自己 Bash 去 cat SKILL.md，不可靠且非设计意图）。
- L4-a 进度表标的"已完成"需降级为"代码就位、但 §P1 终极目标未达成"。
- 新增 ST `test_skill_invocation.py` 的断言（`"tool_name": "Skill"`）对本 CLI 版本是**错误信号**，需改写或
  改为验证"skill 内容进入 agent 上下文"的正确信号（slash-command 注入 / 系统提示注入）。

### 待定方向（不在此拍板，需单独分析）

1. **编排显式注入 skill 内容**：既然 skill 本质是一段方法学文本，编排可在 spawn 前把 SKILL.md 内容
   直接读出、注入 prompt（确定性，不依赖模型自觉调用工具）。与 §P1「方法学单一来源」相容——SKILL.md
   仍是唯一来源，只是改由编排注入而非模型调用。
2. **预置 slash command 触发**：spawn 的首条消息以 `/stage-design:<skill>` 开头（CLI 实测可行），让 CLI
   注入方法学。需确认 SDK headless 模式是否支持首消息走 slash command。
3. **升级/改配 CLI**：确认是否存在让 plugin skill 暴露为 `Skill` 工具的 CLI 版本/配置（成本与可控性需评估）。

> 修复方案见 `02-analysis.md` §P9（已拍板：方案 2 编排预置 slash-command 触发 + ST 守护 + L4-c 改写
> SKILL.md 输入契约）。在该点闭环前，§P1 不算完成。

---

## 问题与用户反馈对应表

| 用户反馈 | 本文条目 |
|---------|---------|
| 1 阶段结束应列产物清单 | P6（+ P2 并行分支清单） |
| 2 并行 agent 日志无法区分模板 | P2 |
| 3 详设 loopback 黑盒 / checkpoint 消失 | P3（根因 P1） |
| 4 stage-design skill 混入非同系列/旧版 | P4 |
| 5 ascendc-designer 描述问题 / design_spec 来源 | P5 |
| 6 其他阶段 skill 精细化 | P4 + P1（skill 加载机制是前提） |
| 7 其他你发现的问题 | P1（最致命）、P7（错误吞、turn 预算、停滞、计数、跨 stage 上下文）、P8（结构化详设直通冗余，待 L4 完成后详设） |

