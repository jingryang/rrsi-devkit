# step-60 — 设计阶段逃生路径 + validate halt 三层根因 — 方案分析（第三层）

> 状态：方案已拍板（A/B/C 方向 + 逃生路径原则均经用户逐条确认），待实施。
> 层级：**第三层 / 方案分析**。选项 + 取舍 + 拍板理由。代码改动配方在 L4 `60-design-escape-hatch-impl.md`。
> 覆盖问题：P81（design_chip 误判 A5）/ P82（UNVERIFIED 死状态 + selfcheck 越界）/ P83（design gate 无逃生路径）。
> 承接：P47（step-25/26 反馈消费闭环，消费端确定性）/ P80（step-57 429 退避，backend 层）。本 step 是**编排层 condition 路由 + 产出端字段职责**的收口。
> 约定：按符号定位（不写 file:line，落点在 L4）；外部依赖只读。

---

## 0. 逃生路径原则（统领三条，用户拍板）

设计阶段没有客观标准，**不完美的设计也必须能进入 codegen**（只是让后续更艰难，不代表要 halt）。由此定三条不变式：

1. **预算尽后才逃生**：corrective loop（`is_satisfied` + `max_iterations`）保留，先尽力修；不是一遇问题就放过。
2. **产物不能少**：逃生（放行到 codegen）的前提是设计产物链完整产出（`output_contract` 满足）；产物残缺走 `contract unsatisfied`，不 forward。
3. **halt 仅留给 429 这类服务端不可用**：连 LLM 都调不了时才 halt（P80/backend 层已处理）；设计质量门不 halt。

这三条同时回答了 P83 的根因——当前 design gate 把"质量未过"和"服务端不可用"混为一谈，都用 halt。

---

## 1. P81 — design_chip 由谁决定

### 选项与取舍

- **选项 A（schema example 去污染）**：把 skill example 里的 A5 改占位。治标、单点，只防"照抄 example"，不防 agent 其他途径凭空产。
- **选项 B（加载期文档溯源）**：`_apply` 校验 agent 产的 chip 必须能追溯到 requirement_doc.md 字样。**被否**：用户指出 A6 散落风险——naive 溯源要枚举芯片字样/别名；且 `domain/chip.py` **故意不留 alias**（§1.4，只认 canonical A2/A3/A5），溯源需别名归一化（需求文档可能写 Ascend910B/950/David），与现有设计冲突。
- **选项 C（agent 不参与 chip 决定，显式 canonical 字段）✅ 拍板**：design_chip 权威源收敛为 `CLI > 需求文档显式 canonical 字段 > runtime 兜底`；agent 产的 constraint **不再是 chip 来源**。需求文档指定 chip 走显式 canonical 字段（frontmatter），确定性解析、用 `is_known_generation` 校验合法性。

### 拍板理由

- **可扩展（A6 不散落）**：所有 chip 知识单一源 `domain/chip.py`；入口/解析只引用 canonical、不枚举字样。加 A6 只改 `domain/chip.py` 一处，入口/解析零改动自动适配。
- **机制保证**：override 与否由 Python 确定性解析决定（显式字段在不在 + canonical 合不合法），不依赖 agent 行为。
- **不需要别名归一化**：显式 canonical 字段绕开"扫自然语言找芯片字样"，不违反 domain 不留 alias。
- **契约明确化（§1.3）**：需求文档指定 chip 从"agent 自然语言推断（=本次 bug 根因）"收紧成"显式 canonical 字段"，是利。
- 配套 example 去 A5（选项 A 作为卫生整改并入）。

### 不选

- 选项 B（文档溯源）：与 domain 不留 alias 冲突，且扫自然语言有"顺带提到 vs 真指定"歧义。
- "chip 完全只由 CLI+runtime 决定、需求文档也不能 override"：剥夺了"A2 机器做 A5 设计"的正当能力（§requirement.py:300-304 有意允许）。

---

## 2. P82 — UNVERIFIED 加消费者 + selfcheck 边界 + 是否核对一致性

### 子问题 1：UNVERIFIED 的查证闭环由谁驱动

- **选项 A（产出方即查证）✅ 拍板**：产出方（buffer_kernel 等）产出 claims 时即查证——标 UNVERIFIED 前必须先查证源（platform_diff/knowledge），查到升 `derived` 附 evidence，查不到才 UNVERIFIED 附 `why_unverifiable`。
- 选项 B（validate 第三方驱动）：产出方照标 UNVERIFIED，validate 发现后驱动查证。**否**：把查证后置到 gate，UNVERIFIED 仍是"先污染后治理"。
- 选项 C（selfcheck 自查一致性）：在 selfcheck 加"selfcheck 等级投影 claims 等级"检查。**否**（见子问题 3）。

**拍板理由**：这次 buffer_kernel 明明读了 platform_diff.md（evidence 都引了）、本可查到 derived，却没把查证做完整就标 UNVERIFIED——查证该**前置到产出**，从源头不让 UNVERIFIED 轻易产生。配合 `verification` 等级判据明确（文档推导够 `derived`，不滥用 UNVERIFIED）。

### 子问题 2：selfcheck 边界

- **拍板**：selfcheck 只判结构/逻辑（公式↔伪代码、Buffer↔Kernel、对齐、UB 占用），**不判查证充分性**（查证归 claims）。`selfcheck.a5_regbase_vf_split PASS per platform_diff` 这种越界判查证的项要收窄。
- 理由：selfcheck 与 claims 判不同维度（结构 vs 查证），边界清晰后天然不重叠，从根上消除"同事实两判定打架"。

### 子问题 3：要不要核对 claims↔selfcheck 一致性（关键转折）

- **结论：不核对**。
- 推演过程：若 selfcheck 边界收窄到位（只判结构），selfcheck 与 claims 不重叠 → 不存在"一致性"需要核对。还要核对，恰恰说明边界没收窄。validate GV3 里"核对 claims↔selfcheck 等级"是 selfcheck 越界时代的兜底债务，应随边界收窄删除，而非"复用保留"。
- 且 selfcheck 自查一致性**不可靠**（这次矛盾就是 selfcheck 漏检——产出方写得出 PASS，自查时也看不出越界）。

### 拍板理由（整体）

- **单一权威（§2.5）**：claims 的 verification 是查证唯一出口；selfcheck 只判结构；二者不交汇，无需核对。
- **UNVERIFIED 不再死状态**：产出方即查证 + evidence 结构化（附 why_unverifiable）。
- GV9-a 改语义匹配（UNVERIFIED + 涉及硬件 API，非字面 claim_type 串匹配），堵 a5_vf_split 这类子类漏网。

---

## 3. P83 — design gate 预算尽后放行（不 halt）

### 选项与取舍

- **选项 A（escalation-only 第一轮就 halt）**：**否**——违反逃生路径原则（设计质量门不 halt）。
- **选项 B（去掉 design gate 的 halt/escalate 出口，预算尽后放行）✅ 拍板**：corrective loop 保留跑预算；预算尽后 `redo_doc/human/redo_general` 不再 `__halt__/__escalate__`，design group completed，线性推进到 codegen（带未消解 issue 作 known_issues）。`redo_tiling`（可修 loopback）保留。

### 关键洞察（Explore 确认）

design group 是 codegen 的**线性后继**（SequentialGroup：detailed-design → test_design → codegen_init → codegen）。**不需要 TRANSITION_TABLE 加 codegen 边**——只要 design gate 不 halt（group completed），自然推进到 codegen。修 C 本质 = 去掉 design gate 预算尽后的 halt/escalate 出口。

### 子问题：known_issues 怎么从 validate 带到 codegen

- 复用 advisory（pending_advisories）：**否**——advisory 按 `target==target_name` 滤，validate 的 target 是 docgen/tiling/human 不命中 codegen；且 codegen 现在不消费 pending_advisories。
- **拍板**：新增独立字段 `design_known_issues`（State），validate.transition populate 未消解 blocking_issues，codegen 经 staging 物化（`known_issues.json`）+ prompt 段消费。bypass advisory 的 target filter，更干净。

### 子问题：产物完整性（硬约束②）

- 现有 runner `has_all`（atomic stage 级 provides 校验）已正确，不改 runner。
- codegen.validate_inputs 已校验 design_spec.inputs/outputs 非空（缺失 → PreconditionError halt）；**加 `validation_report is not None`**（保证 validate 至少跑过一轮，产物链完整才放行）。

### 与 P80（429）的边界

429 退避在 `capabilities/agent/*` backend 层（P80/step-57），与 design gate（`design_tree.py`/`graph_executor.py`/`workflow.py`）**零文件重叠**。429 耗尽 → AgentResult fatal → 走 fail_strategy/last_error，不走 condition 路由。两层正交，改 design gate 不动 429。

---

## 4. 实施顺序与依赖

**A → C → B**：

- **A 先**：design_chip 是导火索，独立、最小、收益广（防任何凭空 constraint）。修了 A，A5 不再误判，本次 case 的 VF 拆分根本不产生。
- **C 次**：让 design gate 的 halt 行为正确（逃生路径），解锁"设计阶段必定到 codegen"。C 不依赖 A/B。
- **B 后**：产出端字段职责（UNVERIFIED 消费者 + selfcheck 边界）。B 主要是 skill 文档 + schema，依赖 A/C 之后的产物链稳定。

三条独立但叠加：任意砍断一条都改变本次结局，但只有三条全修才能防整类问题（A 防 chip 污染、C 防 halt 死局、B 防产物内部矛盾）。

---

## 5. 待实施时的注意

- agents/*.jsonl 只记总结不记工具调用，A5/UNVERIFIED 的 agent 内部推理无法坐实（L1 已注明）；本 step 落点都基于代码现状（Explore 确认）。
- B 主要是 skill markdown + schema，可测部分有限（schema 加载期校验 + UT 测"validate 不再因 claims↔selfcheck 报矛盾"这类机制行为）；skill 文档引导效果靠 heavy_llm e2e 守护（§3.11，跑前确认）。
- halt 文案（dispatcher.py corrective_exhausted）误报 build/precision：C 修完后 design gate 不再走这条 halt，文案问题自然消失（design gate 不 halt）；保留给 codegen/precision 的 build/precision 场景仍合适。
