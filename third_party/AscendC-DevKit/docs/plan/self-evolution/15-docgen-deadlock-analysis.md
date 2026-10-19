# docgen→validate 死锁治理 — L3 方案分析

> 层级：**L3 / 方案分析**。覆盖 L1 issues P13–P20（L2 step-14）。
> 记录「有哪些选项、选了哪个、为什么」。调研中演进、拍板后冻结。
> 配套：L1 `06-problems.md` P13–P20；L4 `16-docgen-deadlock-impl.md`。

---

## 1. 问题定位（来自 L1，不重述事实）

三条独立根因链 + 一组旁支：

| 根因 | L1 | 性质 |
|---|---|---|
| 确定性 docgen 渲染漏装 `kernel_pseudo_code` | P13 | 实现缺陷（硬编码装载逻辑不全） |
| GV8-A 把内容丢失 route 给确定性的 docgen | P14 | route 不可达（target 与 stage 性质矛盾） |
| loopback 无收敛 → 死循环到超时 | P15 | 兜底缺失（精确根因见 §2） |
| 超时致下游全跳过 + 回滚 | P16 | P13–P15 衍生 |
| docgen 空动作 WARN 误报 | P17 | 可观测旁支（已随 P13 修） |
| validate 跨 loopback 轮次无增量、每轮从零全量重验 | P18 | 合法 corrective 回路上的效率损耗（兜底 A 后仅 `redo_tiling` 触发、有上限；§3.6 用户决策删除） |
| gd-review 持 Glob/Bash 导致全仓探测、单次耗时偏高 | P19 | 效率旁支（reviewer 工具集超出职责所需；§3.7 已实施：去 Bash+Glob、加 Write） |
| GV8-A/B 核对对象错配（绑终稿）→ 终稿标注被重渲染抹掉 | P20 | 核对对象错位（§3.8 已实施大修：GV8-A/B/GV5 脱终稿、design_doc 降级） |

L3 要回答：每条根因修不修、怎么修、兜底放哪层。

---

## 2. 调研新增的关键事实（决定方案选择）

1. **框架已有停滞检测**（`GraphExecutor._execute_sequential` 的 stagnation 段）：同一 `(from→to, error_signature)` 出现 ≥2 次即停 corrective、记 `stagnation` 事件后前进。**机制已存在**，依赖 `stage.error_signature(state)` 返回非空签名。
2. **`error_signature` 仅 `verify` 定义**；`ValidateStage` 未定义 → validate loopback 时 `sig=""` → 停滞检测的 `and sig` 条件不成立、整段跳过。**这是 P15 的精确根因**（修订了 L1 初版「框架无校验」的表述——实为「机制存在、gate 未接入」）。
3. **`design_doc.markdown` 无下游消费者**：`codegen.input_contract.requires = [design_spec, tiling_strategy, mode, profile]`，不含 `design_doc`；全仓只有 `validate` 校验它。即 design_doc 是**纯人类可读交付物**，其「Kernel 架构」节空缺不影响算子代码生成。
4. **停滞触发后行为 = 前进**（`i += 1`），非 halt。若走 error_signature 方案，validate 停 → 走完 design 组 → 到 codegen——技术上不崩溃（结合事实 3，codegen 不读 design_doc），但**前进本身是否正确**是另一个问题（见 §3.2 决策修订）。
5. **GV8-A 的 target 由 reviewer 按 skill 规则填写**（`target: docgen`），经 `ValidateStage.resolve_condition` 映射 `redo_doc` → 转移表 `"redo_doc": ("docgen", "corrective")`。即 route 决策半静态（规则文本钉死）、半动态（reviewer 填 target）。
6. **纠正性 loopback 合法性前提**（用户指正后确立的不变式）：`corrective` loopback 只有在"重跑 target 能产生不同结果"这一前提成立时才逻辑自洽。LLM/agent stage（随机性 + 可吸收 `loopback_feedback` 改变决策）满足该前提；纯函数式的确定性 stage（`DocgenStage`：`actions()` 恒返回 `[]`，渲染在 `transition` 中同步完成、输出是输入的纯函数）不满足——对它的 loopback 是一条**结构性死边**，无论重试多少次都不可能收敛，因此"重试几次后停" ≠ "问题被处理"，只是"预算被消耗后放弃"。
7. **`__halt__` 是 scope-agnostic 原语**（本轮读 `graph_executor.py:150-270` 确认）：`_execute_sequential` 对 `route = node.transition_table.get(child.name, {}).get(condition)` 的处理中，`__escalate__:<cond>` 判断（line 217）与 `__halt__` 判断（line 223）在同一处理点上、先于 `target_idx = order.index(target_name)`（line 240，仅在非 halt/非 escalate 时才会执行）。即无论 `node.transition_table` 是组内表（`_DETAILED_DESIGN_TRANSITION_TABLE`）还是 pipeline 顶层表，`("__halt__", ...)` 都被同一段代码统一处理——组内表可以直接写 halt，不必先 `__escalate__:<cond>` 冒泡到 pipeline 层再转 halt。这与 `workflow.py` 顶层给 `verify`/`test_design` "exhausted" 用的写法（`("__halt__", "escalation")`）完全同构。

---

## 3. 选项与决策

### 3.1 P13 — docgen 装载 `kernel_pseudo_code`（止血，本轮实施）

| 选项 | 内容 | 取舍 |
|---|---|---|
| **A（选）** | `DocgenStage._render_detailed` 内化装载：从 `state.tiling_results[tpl].buffer_kernel.kernel_pseudo_code` 读 5 函数渲染到 markdown「Kernel 架构」节 | 确定性渲染器的装载映射属代码职责。schema 不变（`design_doc.json` 是渲染索引，不承载 pseudocode 内容） |
| B（弃） | 让 docgen 读 `section_mapping_convention.md` 按规约装载 | 违反第一准则「框架不读 skill 内容做逻辑」；该 md 本就是给 agent-based docgen 的，确定性渲染器内化即可 |
| C（弃） | 回退 docgen 为 agent-based | 违背 §2.5；确定性渲染是 P8 既定方向（cures drift），补装载即可，无需回退 |

**决策**：选项 A。修复后 GV8-A 不再触发（终稿有内容）→ 死锁消失。

### 3.2 兜底 A — validate `redo_doc` 直接 halt（运行期，本轮实施；取代 error_signature 方案）

> **本节为修订版**。原方案（`ValidateStage.error_signature` 接入既有 stagnation 检测，停滞后前进到 codegen）已被用户指正推翻：*"Validate 根本就不该出现 docgen 的错误，或者说出现了错误根本就不该跳转，不如直接停下，各个环节在逻辑上要站得住。"* 下方保留原方案的评估以说明为何被弃，决策以「决策（修订）」为准。

| 选项 | 内容 | 取舍 |
|---|---|---|
| **A（选，修订后）** | 转移表 `_DETAILED_DESIGN_TRANSITION_TABLE["validate"]["redo_doc"]` 由 `("docgen", "corrective")` 直接改为 `("__halt__", "escalation")`。不尝试 loopback，`validate` 一旦判定内容丢失且 target=docgen，立即终止运行、走人工 triage | 每条 loopback 都要在事实 6（rerun-can-differ 前提）下站得住；docgen 不满足前提，唯一逻辑自洽的处理是不跳转、直接停。机制上零新增代码路径（复用既有 `__halt__` 原语，事实 7） |
| B（弃，原方案） | `ValidateStage` 加 `error_signature(state)`，接入既有 stagnation 检测：重复 ≥2 次后停 corrective、**前进**到 codegen | 表面「不崩溃」（design_doc 无下游消费者，事实 3），但**前进 = 把已知的「终稿内容丢失」问题静默吞掉、推给更下游的人工/后续环节去发现**——直接违反 CLAUDE.md §1.2「可诊断」（不把错误静默吞掉、推迟到更难定位的下游）。且该方案对"loopback 本不该发生"这一更早的错误没有响应——它是在错误已经发生（跳转到 docgen）之后才补救，而非阻止错误发生 |
| C（弃） | `redo_doc` 改为 `("__escalate__:redo_doc_unfixable", "escalation")`，冒泡到 pipeline 层表再由该表转 halt | 多余的一跳：halt 是 scope-agnostic 原语（事实 7），组内表可直接终止，不需要父 scope 参与决策；`__escalate__` 语义是"决策权交给父 scope"（用于 human/redo_general 这类确实需要 pipeline 层知情的跨 group 决策），这里没有这类需求 |

**决策（修订）**：选项 A。`_DETAILED_DESIGN_TRANSITION_TABLE["validate"]["redo_doc"]` 改为 `("__halt__", "escalation")`。`ValidateStage.resolve_condition` 不改（仍返回 `"redo_doc"`，只是转移表把这个条件路由到 halt 而非 docgen）；`ValidateStage` 不需要新增 `error_signature`（没有 loopback 发生，无停滞可检测）。

**为何这是对「硬编码环节」更诚实的兜底**：halt 不是"退而求其次的近似"，而是对事实 6 不变式的直接落地——凡 corrective 转移表把确定性 stage 设为 target，都是 route 设计的错误，运行期一旦命中就该让人看见并停下，而不是靠"多试几次、悄悄放过去"来掩盖。即便未来出现新的「target 钉死到确定性 stage」的 P14 类缺陷，本次修复只堵死了 `validate→docgen` 这一条具体边；根治同类问题仍需 §3.3 的加载期可达性校验（对所有 corrective 边通用）。

### 3.3 兜底 B — 转移表 target 可达性加载期校验（留拍板，本轮不实施）

| 选项 | 内容 | 取舍 |
|---|---|---|
| A（候选） | 转移表注册时校验：`corrective` target 若 `actions()` 返回空（确定性 stage），须声明「loopback 改变其输入字段」，否则加载期报配置错误 | 把 P14 类「target 钉死不可达 stage」变成加载期错误（§1.3） |
| B（候选） | 不做加载期校验，仅靠兜底 A 运行期自停 | 简单，但「不可达 route」仍会消耗一次 loopback + validate 全量重验成本才停 |

**决策**：**本轮不实施**，仅立方案。理由：(a) 要给确定性 stage 建模「输入依赖」声明，改动面较大；(b) 兜底 A（halt）已让 `validate→docgen` 这一具体死边不再可能发生，B 是根因层加固（覆盖所有 corrective 边、不止这一条），边际收益低于紧急程度；(c) B 的精确 schema（怎么声明输入依赖、哪些 stage 需声明）需独立设计。留作后续 L3 单独拍板。**兜底 A 定案后，B 的落点更明确**：B 要校验的不变式正是事实 6（corrective target 必须满足 rerun-can-differ），即"转移表注册时，若 target stage 是确定性的（`actions()` 恒空/无 agent），则该边不得是 `corrective`"——这条规则加载期即可判定，能在 P14 类缺陷第一次落地转移表时就报错，而非等到运行期真的触发一次 halt 才发现。

### 3.4 延伸洞察（不实施，记于此供架构讨论）

- **design_doc 是「无人消费的人类交付物」，却作 blocking gate 阻断 codegen**。GV8-A 校验的是文档保真，而文档保真与算子代码生成无关（codegen 不读它，事实 3）。这等价于「用人类交付物质量门控机器链路」。
- 呼应 P12（design_doc / golden 角色定位）。可能的方向：把「文档保真」（GV8-A）从 blocking 降为 warning（不阻断 codegen，仅标记交付物质量），让机器链路只被「代码生成相关」的 gate 阻断。
- **本轮不动**——这是 design_doc 角色重定位，影响面大，需独立讨论。兜底 A 选择 halt 而非"停滞后前进"，恰恰使这一延伸洞察更凸显而非被掩盖：halt 会让「GV8-A 阻断了一个 codegen 根本不需要的文档」这一架构错位在每次命中时都被人看见（触发 halt、需要人工介入），而不是像"停滞后前进"那样把这个错位悄悄压下去、看起来像是"解决了"。换言之，halt 是诚实地暴露问题，为 §3.4 的角色重定位讨论提供持续的、真实的触发信号。

### 3.5 P17（已完成，随 P13 落地）

确定性 stage 声明 `skip_reason`（`"deterministic_render"`），框架据此把「空动作 WARN」降为 info，不再把「有意的空动作」与「bug 空动作」混为一谈。已实施。

---

### 3.6 P18 — validate 跨 loopback 轮次无增量（立方案，实施待频率数据）

> **现状定性**：兜底 A 落地后，validate 失去 `redo_doc` 这条死边，**只剩 `redo_tiling` 一条 corrective 出边**（target=tiling，LLM stage，满足事实 6 的 rerun-can-differ 前提，合法）。即 P18 不再是死锁放大器，而是**合法 corrective 回路上的效率损耗**：每次 `validate → tiling → docgen → validate` 重入，reviewer 都从零全量重验 GV1–GV9。`detailed_design_group` 的 `max_corrective=3`，故浪费上限 ≈ 3 轮全量重验；且 `redo_tiling` 是否高频未知（anchor-consistency 已在 validate 之前前置拦截 tiling 可行性，正常流程下 GV3/GV4 内容性不一致触发回 tiling 的概率应不高）。**非阻断、有上限、频率待观测。**

**精确根因（不重述 L1 事实，只补机制层定位）**：validate 重入时，`_DesignSubstage._build_prompt` 经 `_previous_decision_section` 注入的是上一轮 validate 的 **decision_log**——其 schema 是「关键决策 / 已知问题 / 假设」，记录的是「为什么这么判」，**不是「哪些 GV 规则已 PASS / 核对的产物指纹是什么」**。两类信息性质不同：决策记录面向「避免重复已排除方案」，规则验证状态面向「跳过已确认无误的核对」。当前只有前者、没有后者，reviewer 拿不到「上轮 GV1/GV2/GV5 已 PASS 且其核对对象本轮未变」的信号，只能每轮从零 Glob→Read→逐条重验。叠加 `loopback_feedback` 只透传 `blocking_issues`（只告诉它「哪里挂了」，不告诉它「哪里已经稳了」），增量上下文缺口完整。

| 选项 | 内容 | 取舍 |
|---|---|---|
| **A（根治方向，暂不实施）** | validate 产物（`blocking_status.json`）增 `rule_results` 段：每条 GV 规则记 `{verdict, checked_artifact_fingerprints}`；`ValidateStage.loopback_feedback` 除 `blocking_issues` 外，再注入「上轮 rule_results + 本轮对应产物指纹对比」；prompt 增量段明示「指纹未变的规则上轮已 PASS，仅复核指纹变化的规则」 | 机制正确：把「验证状态」显式化、可比对。但 (a) 需为每条 GV 规则定义「它核对的产物子集」以算指纹，规则-产物映射要单独维护；(b) reviewer 是 LLM，「跳过已 PASS 规则」是行为层宽容而非强制，给对信号但不保证省时；(c) 在 `redo_tiling` 触发频率未知时上此机制，有过度设计之嫌 |
| B（弃） | 把 GV1（模板数 vs 章节数）、GV8-A（buffer_kernel 函数清单 vs 终稿函数名）、GV9-c（loop 字段命名）等**机械可判定**规则下沉为确定性 Python 预检，reviewer 只留语义规则（GV3/GV4/GV7/GV8-B/GV9-a/b） | 思路对（确定性优先，重入时幂等秒过），但 validate 的规则集里**机械规则占比低**（多数需语义判断），下沉收益小、维护面反而增大；且不解决语义规则跨轮重验的核心浪费 |
| **C（选，本轮）** | 不实施，仅立方案；先采集 `redo_tiling` 的真实触发频率（event_log 里 `validate→tiling` corrective 计数），频率证实偏高再按 A 实施 | 兜底 A 已消除阻断性后果，P18 是衍生效率问题；在无频率数据时加机制违反「避免过度设计」。诚实留观，方案备好待用 |

**决策**：**C（本轮立方案不实施）**，A 作为已设计好的根治路径备查。理由：四把尺子里「可诊断/架构合理」对 P18 不构成硬伤（兜底 A 已让问题有上限、可见），「可维护/可扩展」的边际收益需频率数据支撑；贸然实施 A 是为未必存在的问题建机制。**触发实施的判据**：连续若干次 self-evolve run 的 event_log 显示 `validate→tiling` corrective 频繁发生（接近 `max_corrective` 上限）——此时 A 的收益才值得其维护成本。

| 尺子 | 选项 A（根治） | 选项 C（本轮立方案待数据） |
|---|---|---|
| 可维护 | 澄清「验证状态」契约（与 decision_log 区分） | 不新增契约，零维护负担 |
| 可扩展 | rule_results 模式可复用到 anchor/review 等同类 gate | — |
| 可诊断 | 增量核对失败时指向具体规则+指纹 | 浪费有上限、可在 event_log 观测 |
| 架构合理 | 验证状态归 gate 产物，职责正确 | 不为未证实问题建机制（避免过度设计） |
| **最终** | ❌ 用户决策删除（不修——选项 A 维护成本不抵收益、属过度设计；L4 改动 6） | — |

---

### 3.7 P19 — general-design-review 单次耗时偏高（本轮实施）

**精确根因**：`ascendc-design-reviewer` agent 的 `allowed_tools` 含 `Glob` 与 `Bash`。reviewer 的输入本已由 `_DesignSubstage._materialize_inputs` 确定性地物化到 working dir（`general_design.json` 等已知文件名，F2），reviewer 只需 `Read` 这些已知路径即可。但持有 `Glob`/`Bash` 时，agent 倾向于「Bash 全仓找文件 → 逐文件 Read 探测」的开放式探测路径（L1 P19 观测到的 48 turn / 201s 主要消耗在此），而非「直接 Read 编排声明的输入文件」的靶向路径。这与 step-13 anchor 重构前的问题同构（anchor 持 Glob 导致全仓扫 CANN）。

| 选项 | 内容 | 取舍 |
|---|---|---|
| **A（选）** | 从 `ascendc-design-reviewer` 的 `allowed_tools` 移除 `Glob`（保留 `Read`/`Edit`/`Bash`/`Grep`/`Skill`）。reviewer 的输入文件名由编排契约确定，无需探测；`Bash` 保留是因 reviewer 仍需 `cat >` 写结构化产物 | 根因层修复：移除「诱导开放式探测」的工具，强制走靶向 Read。与 step-13 Phase 4（anchor 移除 Glob、保留靶向 Grep）同模式、同理由。改 agent frontmatter 一处 |
| B（选，与 A 配合） | reviewer 的 prompt（gd-review / validate 共用 reviewer 角色的 prompt_intro）增一行：「输入已物化为 working dir 中的 `{general_design.json}` 等已知文件，直接 `Read`，勿用 Bash/Glob 全仓探测」 | 行为层引导：即便保留工具也明示正确路径。与 A 叠加收益最大 |
| C（弃） | 不修 | L1 已定性「轻」，但根因（工具诱导探测）明确、修复（移除 Glob）一行、与既有 step-13 模式一致，性价比高，无理由不修 |

**决策**：**A + B**。移除 `Glob` 是根因层（工具权限决定 agent 可选行为空间），prompt 明示是行为层（即便工具在也引导正确路径），二者叠加。`Bash` 不移除——reviewer 用它写产物（`cat > *_reviewed.json`），且 step-13 的先例也是「移除 Glob、保留靶向 Grep/Read」，并非禁 Bash。

| 尺子 | 选项 A+B |
|---|---|
| 可维护 | 工具权限与 stage 的「输入已物化」契约对齐 |
| 可扩展 | 同模式可用于任何「输入由编排物化」的 reviewer/gate agent |
| 可诊断 | 探测开销下降直接反映在 turn 数 / 耗时上，可观测 |
| 架构合理 | 工具集 = 职责所需最小集（§4.1 agent 契约 manifest 驱动），Glob 非 reviewer 职责所需 |
| **最终** | ✅ 已实施（升级：去 Bash+Glob、加 Write + 两 skill 输出约定 Bash→Write，L4 改动 4） |

---

### 3.8 P20 — docgen 重渲染抹掉 `[继承自概设独有设计]` 标注（定案：结构化吸收记录）

> **与兜底 A 的关系**：兜底 A 把 `redo_doc` 改为 `__halt__`，故 P20 的「终稿无标注 → target=docgen → redo_doc」这条路径已一次命中即停（不会再 loopback 抹标注）。但 P20 的根因——**GV8-B 的核对对象错配**——并未消除：若 reviewer 把 GV8-B 失败的 target 填为 `tiling`（吸收职责本就在 tiling），仍会走 `redo_tiling` 合法回路，而 tiling 产物其实已吸收（标注在产物里）、只是终稿没装载，于是 redo 后 docgen 重渲染仍无标注 → 又判 GV8-B 失败，直到 `max_corrective` 耗尽。故 P20 需独立根治，不依赖兜底 A。

**精确根因（核对对象错配，三层错位叠加）**：

1. **吸收证据是自由文本**：tiling-split 的 R7（及 buffer_kernel/precision_perf 对应规则）把 `unique_design_points` 吸收进 tiling **markdown 产物**，吸收内容带 `[继承自概设独有设计]` 标注——是 markdown 里的自由文本，**不是结构化字段**。
2. **validate 看不到 tiling markdown**：`ValidateStage._upstream_inputs` 物化的是 `design_doc`（终稿）+ `tiling_results.json`（结构化，**不含**自由文本标注）+ `anchor_report`。reviewer **看不到** tiling 三段 markdown 里的标注。
3. **GV8-B 规则文本允许「查终稿」**：GV8-B 写的是核对独有点「已被**对应阶段产物 / 终稿**吸收（带 `[继承自概设独有设计]` 标注）」。reviewer 既然看不到 tiling 产物标注，就退而核对**终稿**里的标注字符串。
4. **DocgenStage 确定性渲染器不装载标注**：`_render_detailed` 只 dump `design_spec`/`tiling_strategy`/`kernel_architecture` 的 JSON + 装载 `kernel_pseudo_code`（P13），**从不装载** tiling markdown 的逐节内容，故终稿里没有 `[继承自概设独有设计]` 标注。

四层叠加 → reviewer 在终稿找不到标注 → 要么报 blocking（target 填错就浪费 corrective 配额）、要么就地 Python 往 markdown 补（被下次 docgen 重渲染抹掉，L1 P18 观测到的「每轮补回」）。**这是规则语义（GV8-B 允许查终稿）与渲染机制（docgen 不转载标注）的错位，不是单纯的渲染 bug。**

| 选项 | 内容 | 取舍 |
|---|---|---|
| A（弃） | 让 DocgenStage 装载标注：从 tiling markdown 提取 `[继承自概设独有设计]` 标注重渲染进终稿 | 走不通：标注是 markdown 自由文本，docgen 不装载 tiling markdown 的逐节内容（它只 dump 结构化 JSON + pseudocode），从自由文本结构化提取标注既不可靠也违背 docgen「第 4 章以产物为权威单源、不从概设拼入」的设计意图 |
| B（弃） | 把 tiling 三段 markdown 物化进 validate 的 working dir，让 reviewer 直接核对产物里的自由文本标注 | 自由文本核对不可靠（LLM 判「是否吸收」主观）；且要新增一条「物化 tiling markdown 到 validate」的数据通路，违反「下游只读直接上游 output_contract」（P4 同类禁忌） |
| **C（选）** | **结构化吸收记录**：tiling 三段产物 schema 各增一个可选字段 `inherited_design_points`（结构化：`[{point_ref, section, note}]`），R7 吸收时写该字段（仍可同时在 markdown 留标注供人读）；GV8-B 改为**核对 `tiling_results.<tpl>.<segment>.inherited_design_points`** 是否覆盖所有 `unique_design_points`（按 `stage` 路由到对应 segment），**不再核对终稿标注字符串**；docgen 装载该字段为可选增强（非 GV8-B 依赖） | 「正确改动」落在职责正确的层：吸收记录归 tiling 产物（吸收职责所在）、核对归 validate（gate 职责）、核对对象是 validate 已有的 `tiling_results.json`（无需新数据通路）。彻底消除「终稿标注」这层错位——docgen 渲不渲染标注都不再影响 GV8-B。与 P4（下游读直接上游结构化产物，不跨读）一致 |

**决策**：**C**。把自由文本标注升级为结构化吸收记录，让 GV8-B 的核对对象明确、可机器化、在 validate 已有输入内。`inherited_design_points` 是 `unique_design_points.{stage}` 的逆向闭环：CR3 标注「待吸收的独有点」（带 stage 归属）→ tiling R7 吸收并回写「已吸收的独有点」（同 stage 维度）→ GV8-B 核对「待吸收 ⊆ 已吸收」。三方用同一套 point_ref 串联，物理上不漂移。

**与 §3.4 角色重定位的关系**：§3.4 指出 design_doc 是「无人消费的人类交付物」，GV8-A/GV8-B 用文档保真门控机器链路是架构错位。P20 的 C 方案是这一洞察在 GV8-B 上的**具体落地**——GV8-B 不再依赖终稿（人类交付物）保真，而是核对 tiling 产物（机器链路的结构化中间态）的吸收完整性。GV8-A（终稿 Kernel 函数保真）仍是「终稿内容」校验，其角色重定位留 §3.4 独立讨论，本节不涉及。

| 尺子 | 选项 C（结构化吸收记录） |
|---|---|
| 可维护 | 「吸收」契约从自由文本升级为结构化字段，语义清晰、可 diff |
| 可扩展 | 同模式（结构化 provenance 字段）可复用到其它「产物→终稿保真」规则 |
| 可诊断 | GV8-B 失败时指向具体未吸收的 `point_ref`（section 定位），而非「终稿里找不到一个字符串」 |
| 架构合理 | 吸收记录归 tiling 产物、核对归 validate、核对对象在 validate 已有输入内（不跨层、不新通路） |
| **最终** | ✅ 已实施（升级大修：GV8-A/GV8-B/GV5 脱终稿、design_doc 降级、tiling `inherited_design_points`+R7-8，L4 改动 5） |

---

## 4. 取舍总结（四把尺子）

| 尺子 | P13 装载 | 兜底 A halt | 兜底 B 加载校验 | P17 skip_reason |
|---|---|---|---|---|
| 可维护 | 澄清渲染装载职责 | 让 route 与 stage 性质的不变式（事实 6）在运行期被强制 | 新增 route 不变式 | 消除 WARN 误报 |
| 可扩展 | 同类装载可循 | 模式可复用到任何「确定性 stage 被误设为 corrective target」的边 | 覆盖所有 corrective 边（加载期） | 覆盖所有确定性 stage |
| 可诊断 | 终稿不再空 | **不静默吞错**——halt 事件带 condition，问题第一时间可见（优于停滞后前进） | 加载期即报错，比运行期 halt 更早 | WARN 不再失真 |
| 架构合理 | 装载职责在渲染层 | 复用既有 `__halt__` 原语，零新增代码路径，与 verify/test_design "exhausted" 同构 | 加载期校验层 | stage 自描述 |
| **本轮** | ✅ 实施 | ✅ 实施 | ⏸ 留拍板（落点已因兜底 A 更明确，见 §3.3） | ✅ 随 P13 |

P18/P19/P20 的四把尺子评估见各自 §3.6/§3.7/§3.8 小表，本轮汇总：

| 问题 | 性质 | 决策 | 一句话理由 |
|---|---|---|---|
| P18 | 效率（合法回路上、有上限、频率未知） | ❌ 删除（用户决策不修） | 选项 A 维护成本不抵收益、属过度设计 |
| P19 | 效率（工具诱导探测） | ✅ 已实施（升级：去 Bash+Glob、加 Write） | 连根去掉探测工具、Write 写报告 |
| P20 | 正确性（核对对象错配） | ✅ 已实施（升级大修：GV8-A/B/GV5 脱终稿） | design_doc 无下游消费者；落点全部归位产物 |

---

## 5. 实施顺序（L4 细化）

1. **P13**（TDD）：先测 docgen 渲染含 pseudocode，再改 `_render_detailed`。
2. **兜底 A**（TDD）：先测转移表 `_DETAILED_DESIGN_TRANSITION_TABLE["validate"]["redo_doc"] == ("__halt__", "escalation")`，再测 `GraphExecutor` 集成（validate 报 docgen-target blocking issue → 实际 halt，`state.is_terminal=True`，不再执行任何下游 stage），最后改 `design_tree.py` 一行。
3. **P17**：随 P13 给 docgen 加 `skip_reason`。
4. design 组 UT + ST 回归。
5. **P19**（已实施）：reviewer agent 去 `Bash`+`Glob`、加 `Write` + 两 skill 输出约定 Bash→Write（L4 改动 4）。
6. **P20**（已实施，大修）：GV8-A/GV8-B/GV5 脱终稿、design_doc 降级、tiling `inherited_design_points`+R7-8 回写、ValidateStage input_contract 改产物（L4 改动 5）。
7. 兜底 B——后续拍板；§3.4 角色重定位已随 P20 大修落地；**P18 用户决策删除**（不修）。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | L3 立项：P13 选内化装载（A）；兜底 A 选复用 stagnation + ValidateStage.error_signature；兜底 B 留拍板；P17 随 P13；P18/P19/§3.4 后续。关键事实：design_doc 无下游消费者 → 兜底「停滞后前进」安全。 |
| 2026-07-03 | **兜底 A 方案修订**：用户指正「validate 出现 docgen 的错误就不该跳转，应直接停」——废弃 error_signature/stagnate-then-advance（违反 §1.2 静默吞错），改为 `_DETAILED_DESIGN_TRANSITION_TABLE["validate"]["redo_doc"]` 直接 `("__halt__", "escalation")`。新增不变式（事实 6）：corrective loopback 合法性要求「重跑 target 能产生不同结果」，确定性 stage 不满足。确认 `__halt__` 为 scope-agnostic 原语（事实 7，`graph_executor.py:223`），组内表可直接 halt，无需 `__escalate__` 冒泡。§3.3/§3.4/§4/§5 相应更新。 |
| 2026-07-03 | **P19/P20 实施完成、P18 删除**（原立方案，实施前升级）：P19 从「移 Glob」升级为「去 Bash+Glob、加 Write」（移 Glob 留 Bash 仍有 find/ls 探测口子，reviewer 原无 Write 靠 Bash cat> 写报告，故连 Bash 去、加 Write）；P20 从「小修 C」升级为「大修 §3.4 落地」（核实 design_doc 无下游消费者，GV8-A/GV8-B/GV5 全部脱终稿、design_doc 降级，GV8-A 落点改 buffer_kernel 产物、GV8-B 核 inherited_design_points、GV5 归 docgen）；P18 用户决策删除（选项 A 维护成本不抵收益）。UT 1496 + 非 heavy ST 101 + heavy_llm 4 + test_npu 10 全绿。CLAUDE.md 新增 §3.11（heavy_llm ST 执行需用户确认）。 |
