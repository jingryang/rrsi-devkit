# P59/P60/P61 — 设计阶段 loopback 收敛慢：路由方向 + 重跑范围 + entry-kind 维度 — 方案分析（第三层）

> 状态：**方案冻结**（2026-07-10，用户拍板）。落地范围 = **P0（前向建议通道）+ P1-a（entry-kind 单点判据 + prompt 触发量改对）+ P1-b（定向重跑范围）**，修掉 P59/P60/P61 三个根因。**P1-c（delta 前传）降级为数据驱动 follow-up**——P0+P1-a+P1-b 落地后用 e2e 收敛曲线定去留；若做，**复用 P0 已建的前向通道**（payload 扩 `issue | delta`），不另造通路。P2（shift-left）最后。冻结决策见 §3（D1-D9）；L4 见 `36-loopback-routing-and-incremental-impl.md`。
> 三条正交根因（P59 路由方向错 / P60 重跑范围粗 / P61 entry-kind 维度缺）的选项分析与取舍；用户主导的架构探索（增量修改 vs 全量重生成、forward 通道、三轴正交模型、selfcheck 是否生效 / 如何加载）已吸收并澄清。
> 层级：**第三层 / 方案分析**。选项 + 取舍 + 待定。
> 覆盖问题：P59（gate 把跨模板一致性问题 backward 回 per-template 盲 tiling）、P60（corrective 按 target→current 整段重跑）、P61（entry-kind 未建模、增量修复错挂 iteration>1）。
> 输入：run `e2e_self_evolve_20260710-140459-5d4217`（anchor-consistency 产 verified+advisory 的 AC3、remediation 自指 integrate，却被 corrective→tiling 全量重跑）+ 用户主导探索（loopback 改增量修改、修改点下游传递、所有 stage 自修不 loopback 备选、forward 与 loopback 是否预约定、iteration/corrective/entry-kind 三轴语义）。
> **承接**：P15（loopback 无收敛校验——超额回跳）/ P13-P16（docgen 死锁族，路由方向问题）/ P45·P47·P54（in-stage 闭环 + 反馈消费自检的同形先例，shift-left 思路来源）。
> 约定：按符号定位（不写 file:line）；外部依赖只读；本文件不写具体改哪个函数（那是 L4）。

---

## 0. 现状澄清（共享事实，先于选项）

这三条问题交织，但根因正交。先把三件易混淆的事说清，避免选项里串味。

### 0.1 forward 问题与 loopback 问题不是「提前约定好」的静态分类

issue 本身只携带 `target` / `verdict` / `remediation` 三面，没有预先盖「这是 forward 类 / 这是 loopback 类」的章。一个 issue 该前向还是回跳，**由 gate 的 verdict + 框架 route_type 词表共同决定**，是路由时刻的判定，不是 issue 产出时的静态属性。今天的问题不是「约定缺失」，而是 **route_type 词表里根本没有「前向建议」这一类**——gate 即便判出「非阻断、owner 在下游」也无边可投，只能 fallback 到 backward corrective 或 `__halt__`。所以 P59 的修复点是**给词表加一类前向非阻断通道**，而非给 issue 加静态分类字段。

### 0.2 corrective 回跳计数是 scope（group）属性，不是 stage 属性、也不是边属性

回答用户的提问。今天的实现里：

- **计数归谁**：corrective（与 escalation）计数挂在 **scope**——即「当前所处的 group 路径」上（root group 是顶层 scope，嵌套 group 是子 scope）。回跳时 `scope["corrective"] += 1`，累加的是「这个 group 内已发生几次 corrective」，不是「这个 stage 被回跳几次」、也不是「这条 from→to 边走了几次」。
- **上限归谁**：`cap = max_corrective` 是 **group 节点**的属性（root scope 用顶层 `max_corrective`，子 group 用该 group 节点的 `max_corrective`）。即「这个 group 最多容忍几次 corrective」。
- **边的信息放哪**：per-edge 的 `(from→to, sig)` 历史**存在 scope 里**（`scope["history"]`），但它的用途不是计数，而是**停滞检测**——同一 `(from→to, signature)` 出现 ≥2 次即判停滞、停 corrective 前进。所以「边」在数据里是有形状的（history 元素带 from/to/sig），但它不持有计数器，计数器是 group 级的。

一句话：**计数与上限是 group（scope）属性；边只贡献停滞检测的素材**。这与「iteration 是 stage 属性」泾渭分明——见 0.3。

> 含义推论：P60「重跑范围粗」本质上是因为 corrective 的计数/上限/清空都以 group 的顺序区间为粒度（target→current 整段），而非以单条边或单个 segment 为粒度。要收窄范围，是给 group 内引入更细的「子范围」语义（template-precise），不是动计数归属。

### 0.3 三个正交轴（用户的核心洞察，本方案的语义地基）

| 轴 | 含义 | 谁判 | 计数归属 | 今天的状态 |
|---|---|---|---|---|
| **entry-kind** | 本次 agent 调用：首次从零生成，还是基于已有产物增量修改 | 编排按「有无合格前置产物 + 有无 feedback」推断 | 无计数（二值维度） | **未建模**，被错误代理到 iteration（P61） |
| **iteration** | 本 stage 本轮进入后第几次自迭代（产物不合格→再 spawn） | stage 自判（producer） | stage 属性（`stage_iterations[stage]`） | 已建模，但 loopback 重入重置为 1 |
| **corrective** | 跨节点回跳了几次 | gate 判（reviewer） | scope（group）属性 | 已建模，见 0.2 |

三者**必须分离**。P61 的根因正是把 entry-kind 代理到了 iteration 上；iteration 一旦和 loopback 混计（如「让 iteration 跨 loopback 续计」），就把 producer 自判的轴和 gate 判的轴搅在一起，正是要避免的概念混淆。**结论：iteration 保持干净（自迭代、重入重置），另立显式 entry-kind 轴承载「生成 vs 修改」。**

---

## 1. 定位：三条正交根因，叠加成「回跳 = 从零再生成」的慢收敛

把运行 `e2e_self_evolve_20260710-140459-5d4217` 的一次真实回跳拆开看：

1. **方向错（P59）**：anchor-consistency 判出的是「两模板 R5 字段命名冲突」，verdict=verified、remediation 自指 integrate。这是跨模板问题，单模板 tiling segment 结构上修不了。但词表无前向通道 → 回跳 per-template 盲的 tiling。**这一步本不该回跳。**
2. **范围粗（P60）**：即便要回 tiling，回跳清空的是 target→current 整段顺序区间，fork-join 下等于全模板全 segment 重 spawn。**只需定向改一个模板时，却全组重跑。**
3. **口径错（P61）**：重跑时 entry-kind 没建模，增量修复 prompt 错挂在 iteration>1，而 loopback 重入 iteration=1 → 增量段不触发。**agent 收到的是「从零生成」口径，已有产物 + feedback 没被用于增量。**

三者叠加 = 每次回跳都全量从零再生成，收敛极慢。任一单修都缓解，但根因正交、需分别对症。

---

## 2. 选项与取舍

### 2.1 P0（针对 P59，最高 ROI / 最低风险）：新增「前向建议通道」route_type

**问题**：route_type 词表 `{corrective, escalation, validation}` 无前向非阻断类型；gate 判出「非阻断、owner 在下游」时无边可投。

**选项**：
- **P0-a（采纳方向）**：加一类前向非阻断路由（暂记 `advisory` / `forward`）。语义 = 「issue 非阻断，不回跳、不 halt，随 state 前向流到 `target` 指定的下游合法 owner，由该 owner 在自己的 self-check / transition 里就地吸收」。**不是新的 loopback 边**，而是一条「携带问题前流、到 owner 处就地修」的通道，天然落到 0.1 说的「路由时刻判定」。
  - gate 侧：`resolve_condition` 区分 verdict——`infeasible`（真不可行，producer 责任）才 backward corrective；`verified` + remediation 指向下游 owner 时走 `advisory` 前向。
  - owner 侧（如 integrate）：在自己的产物构造里读「待办 advisory 清单」，就地统一（如统一两模板 R5 字段命名），不回跳、不烧 fork-join。
- P0-b：给 issue 加静态 `kind: forward|loopback` 字段，产出时盖章。**否**——违反 0.1（forward/loopback 是路由时刻判定、非 issue 静态属性），且把判定责任推给可能看不全下游的 gate。

**取舍**：选 P0-a。它直接消灭最多「方向错的回跳」（P59 的全部 + 一大批同类跨模板/跨 stage 非阻断问题），不动计数/上限/重跑机制，风险最低。verdict 与 remediation 在表达层早已分离（issue_render），路由层只需开始用它们。

### 2.2 P1（针对 P60 + P61，结构性）：三轴正交增量 —— 显式 entry-kind + 定向重跑范围 + 结构化 delta 前传

**问题**：P60 重跑范围粗 + P61 entry-kind 未建模，共同导致「回跳 ≈ 从零再生成」。

**子项**：
- **P1-a · 显式 entry-kind 轴（修 P61）**：把「generate | modify」作为 prompt 构造的显式维度，由「有无合格前置产物 + 有无 feedback」推断，**不挂 iteration**。iteration 保持干净（自迭代、重入重置，见 0.3）。modify 模式下 prompt 走「基于已有产物 + feedback 做定向修改」口径，generate 模式走从零口径。直接修掉 P61 的代理错。
- **P1-b · 定向重跑范围（修 P60）**：corrective 清空不再无脑取 target→current 整段，而是按「爆炸半径」分类：
  - **localized**（如单模板字段）：复用既有 `rerun_selector` 做 template-precise 回滚，只清涉事模板/segment 子树。
  - **structural**（如 tiling key 推导变了、波及全模板）：才退化到整组重跑。
  分类依据来自 gate 的 issue + remediation（local/structural 本就可判）。把已有的 template-precise 原语（C4）真正接到 corrective 路径上。
- **P1-c · 结构化 delta 前传（用户 Msg2 的修改点下游传递）—— 数据驱动 follow-up，不在本轮落地**：modify 模式产出的不只是新产物，还带一份「修改点 delta」（改了哪些字段/约束、blast-radius 类别），随 state 前向流动。下游 stage 在自己的 entry-kind=modify 时，读 delta 做**针对性修改**而非全量重算。收敛速度来自这里——每个 stage 只消化增量，不重算整段。
  - **本轮不做**（D3）：P0+P1-a+P1-b 落地后用 e2e 收敛曲线定去留。若定向重跑（P1-b）+ 增量口径（P1-a）已够收敛，P1-c 边际收益不足、不做；若不够再做。
  - **若做，复用 P0 前向通道**（D6）：delta 不另造前传通路，搭 P0 的 `advisory` 通道，payload 从 `issue` 扩成 `issue | delta`。delta 形态待 P0 通道落地后定，不预先定 schema（避免过早抽象）。
  - 约束（与 §2.5/§1.1 一致）：delta 是「非约束建议 + 结构化事实」，下游可选择吸收或忽略后自判；不构成跨 stage 强耦合。

**取舍**：本轮落地 **P1-a + P1-b**（P1-c 降级 follow-up，见 D3）。P1-a 是地基（没有显式 entry-kind，P1-b 的 modify 口径无处挂）；P1-b 复用既有 `rerun_selector` 原语、改动收敛。**P1-c 的风险**（引入跨 stage 数据契约）是它降级的主因——在「P1-a+P1-b 是否已够收敛」无真实数据前定 delta schema 是过早抽象；且 P1-c 真要做时复用 P0 通道（D6），不另造通路，故不急于在 P0 通道形态定清前预设 delta 形态。

### 2.3 P2（横切，针对源头）：shift-left 自检 —— 让 loopback 从源头变少

**问题**：P59 那类跨模板一致性问题，今天由最末的 anchor-consistency gate 兜底发现；若 producer 侧（如 integrate 的自检）更早发现并就地修，根本到不了 gate、不触发回跳。

**选项**：
- **P2-a（采纳方向）**：强化 producer / 整合 stage 的 self-check（既有 `selfcheck_report.json` / feedback-selfcheck skill 是同形先例），把「跨模板一致性」这类可在 owner 处就地判定的问题前移到 owner 自检。gate 退化为「最后防线」而非「唯一发现点」。
- P2-b：把所有一致性检查都堆进 gate。**否**——gate 是 reviewer 角（§4.1），只读 + 报告，不能就地改产物；问题越晚发现、回跳成本越高。

**取舍**：选 P2-a。它是「让 loopback 罕见」的预防性手段，与 P0/P1 的「让必要的 loopback 收敛快」互补。**不强制排期**——P0/P1 落地后视回跳频率决定 P2 投入。

### 2.4 被否备选（用户 Msg3）：所有 stage 自修、不 loopback

**主张**：取消 loopback，谁发现问题谁就地改。

**否决理由**（四把尺子）：
- **可维护 / 事件溯源**：跨 stage 就地改他人产物，破坏产物 provenance（events.jsonl 的权威性），resume 与审计失据。
- **架构合理 / 分层（§1.1）**：下游 stage 改上游产物 = 反向依赖；reviewer gate 改产物 = 越界作者（违反 §4.1 reviewer 只读 + 报告）。
- **可扩展**：「发现者离问题源越远、修改量越大」不是小概率——跨模板/跨 stage 问题正是修改爆炸的常见情形，备选在最需要它的场景里最差。
- **可诊断**：就地改若失败，错误归属混乱（谁改坏了？）。

**采纳的合理子集**：备选里「stage 内自己发现问题自己改」的子集，**今天已存在**——就是 stage 自迭代（iteration 轴，producer 自判）。P2-a 把它的精神（shift-left）抽出来加强 producer 自检，但不取消跨 stage loopback。loopback 仍是「跨节点问题」的必要机制，只是要让它方向对（P0）、范围精（P1-b）、走增量（P1-a/c）。

---

## 3. 决策（已拍板 2026-07-10）

- **D1 — P0 新增 `advisory` route_type，与 `validation` 独立**。语义边界：`validation` = 前向再校验（可能再触发路由、计入相应配额）；`advisory` = 单向前向投递非阻断问题、owner 就地吸收后**不再触发路由**、**不计 corrective 配额**、**不 invalidate 重跑区间**。两者语义不同，合并会污染 validation 的再校验语义，故独立。
- **D2 — entry-kind 单点判据，看「工作目录是否存在本 stage/segment 的既有产物」**。实现为单点函数 `entry_kind(state) → "generate" | "modify"`，判据 = 本 stage output_contract 对应的产物文件在工作目录已存在（loopback 的 invalidate 只清 `node_status`、**不删产物文件**；自迭代第 2+ 轮亦留有上轮产物 → 两者都判 modify；首次无产物 → generate）。**不引入 gate/owner 显式宣告字段**（避免新跨 stage 契约）。结构上预留 `or 有 delta` 扩展位（P1-c 落地时加，见 D6），但**不预实现**。
- **D3 — P1-c 降级为数据驱动 follow-up，不在本轮落地**。P0+P1-a+P1-b 落地后跑 e2e 测收敛曲线：已够收敛 → 不做；不够 → 再做。delta schema 不预先定。
- **D4 — P1-b blast-radius 分类权归 gate，编排兜底；template-precise 机制已存在、改动轻**。gate 在 issue 里带 `blast-radius: localized | structural`（它最懂问题边界）；编排遇缺失则兜底为 `structural`（保守）。**关键**：tiling group 已挂 `_tiling_rerun_selector`（读 issue 的 `target_template` 做 template-precise 回滚，C4 既有机制），故 `localized`（单模板）只需 gate 在 issue 带 `target_template` 让既有机制生效、**不另造回滚原语**；`structural`（跨模板）退化为全模板重跑——但跨模板 structural issue 的正解是 P0 前向到 integrate（不回 tiling），故 P1-b 的 structural 分支实际罕用。
- **D5 — P2 排期按回跳频率实测**。P0+P1-a+P1-b 落地后，用 e2e 回跳次数 / 收敛轮数实测定 P2（shift-left producer 自检）投入。
- **D6 — P0 与 P1-c 共用一条前向通道，不建第二条**。P1 前向信息携带统一走 P0 建的 `advisory` 通道：P0 的 payload 是 `issue`，P1-c（若做）的 payload 是 `delta`，同通道、不同 payload 类型。这是反对「现在为 delta 预设独立通路」的硬理由（§2.5 唯一通路），也是 P1-c 能安全后做的前提——通道形态由 P0 先定清。
- **D7 — entry-kind 与 selfcheck 是两个独立判据，各自正确，不强行同源**（调查修正）。entry-kind 问「本次生成还是改」→ 看**本产物是否存在**（D2）；selfcheck 问「有无上游反馈要消费」→ 看**反馈报告是否存在**（`ascendc-op-design-feedback-selfcheck` 的 SKILL.md 明写「重跑时跑、初次不跑」）。两者维度不同：loopback 重入时两者都成立（既有 loopback 前本产物、又有 gate 产反馈报告）；自迭代第 2+ 轮则 entry-kind=modify 而 selfcheck 不触发（无新反馈报告）——这正是各自语义，不矛盾。**先前「entry-kind 与 selfcheck 同源」的表述错误**：判据独立、不强行同源，避免把两个维度错误耦合。

- **D8 — target 判定按 owner 能力正交化（P59 深层根因）**。P59 的本源不是 route_type 词表缺 forward，而是 anchor-consistency 的 target 判定用错了维度：「跨模板」（blast-radius）被当路由键，但它与 owner 能力正交——AC3 把 owner 不同的子类（TilingKey/workspace/dtype 冲突→上游重推；字段命名不一致→整合层统一）混进同一 code，owner 信息丢失才被迫丢 LLM 临场判 target。修正：target 按 **owner 能力矩阵**判（上游可修→tiling；整合层可修→integrate；需人→human），写进 SKILL.md 替代「跨模板→target=tiling」默认。**AC code 结构不重排**（按问题类型分给 selfcheck/人看合理）。归类动作仍需 LLM（语义理解，§1.5），但标准确定化、可 acceptance 校验、可 selfcheck——从「概率拍 target」变「按矩阵归类」。**元原则**：任何「不得不丢 LLM 判定」的路由，先怀疑分类键选错维度（§1.2 在路由设计上的具体化）。
- **D9 — 灰区 default forward + 用户决策**（用户补充原则）。owner 归属不明的真灰区 issue → **default forward**（advisory 到默认 owner，design 链路默认 integrate），**不 loopback 猜、不 halt**；**同时上报用户裁定**（advisory 带 `owner_ambiguous` 标记 → 触发 resolve_ambiguity / human review 通道），用户裁定优先于 default。理由：forward 三者中代价最小、最可逆（判错则 owner 拿信息后仍可二次上报）；灰区不该烧 loopback 配额或 halt 打断。**与运行时失败灰区的边界**：失败处理 default loopback 给修复机会；设计 issue 路由 default forward 更便宜——共同内核是灰区不 halt、可逆、最终交人。

### 落地顺序

```
P0   target 判定正交化（owner 能力矩阵进 SKILL.md，D8）+ 前向建议通道（advisory route_type + mapping/transition 加边 + state.pending_advisories + graph_executor 前向分支 + owner 吸收 + 灰区用户决策，D9）
P1-a entry_kind(state) 单点判据（看本产物存在，D2）+ prompt 增量段触发量从 iteration>1 改 entry-kind
P1-b 定向重跑范围（issue 带 blast-radius + corrective 路径按类收窄，复用 rerun_selector）
───── 以上落地后跑 e2e 测收敛曲线（§3.11 heavy_llm 节点）─────
P1-c delta 前传（数据驱动；复用 P0 通道，扩 payload）   ← 视收益
P2   shift-left producer 自检                           ← 按回跳频率
```

P0 独立、ROI 最高、先做；P1-a 是 P1-b 的 modify 口径地基；P1-c/P2 数据驱动。L4 见 `36-loopback-routing-and-incremental-impl.md`（P0/P1-a/P1-b 符号级 + TDD）。
