# step-84 — design validate 门不合理 loopback：越界查 docgen + 3-iter 空转 + 信 log 不信文件 + advisory 触发全尾重跑 — 方案分析（L3）

> 性质：**L3 方案分析**（选项 + 取舍 + 推荐，待用户拍板后冻结）。self-evolution 线，step 84。
> 上游 L1：`84-batch-205112-issues-summary.md` Q5（越界查 docgen 逃逸）、Q6（3-iter 空转重报）、Q7（信 decision_log 胜过信文件）、Q8（advisory 触发全尾 loopback）。
> 关键前置：step-78（`78-gate-scope-ownership-contract-{analysis,impl}.md`）已实施"gate scope & ownership contract"，且在本批 HEAD `ce4b6423` 之前合入。本文核心任务之一=判定 Q5–Q8 各自是 step-78 的**(A) 回归 / (B) 未覆盖盲区 / (C) 设计如此缺消费端**，据此给对方案。
> 纪律：§1.8——事实产权在 L1，本文只记根因（L3 产权）+ 选项决策；代码改动配方留 L4。

---

## 0. 一句话

design `validate` 门有四类不合理 loopback/churn，经核实与 step-78 对照：Q5=**(C) 设计如此但缺 docgen 重渲染消费端**（step-78 让 docgen-target 走 advisory 前逃，但没接 re-render 渠道，issue 直接 stale 逃逸，且 validate 本不该查下游终稿）；Q6/Q7/Q8=**(B) step-78 从未覆盖的盲区**。四者均非 step-78 回归。

**实施结论（深评 V5/V6 后）**：真正落地的是**两个 skill 层收口**（低风险、消除根因、无控制流回归）——① **F1/Q5 收紧 GV3 scope**：GV3 只核产物、不核终稿、禁引用终稿 §编号（V6 证否"表体同源"，故落点是防 reviewer 越界查下游，非删同源检查）；② **Q7 落盘核实自检**：validate 就地修正须重读文件确认落盘、信文件不信 log（§1.13）。**F2/Q8 暂不做**（V5 未过：severity/verdict 是 LLM 自标，条件化 loopback 于未验证标注风险=真 blocker 误标漏修，违 §1.2；advisory 抑制只信 gate_scope 结构化 route）。**F3/Q6 暂缓**（首检即 bounce 要动 review/anchor/validate 共用的 gate 控制流，回归面大 vs 收益不成比例；stagnation 已兜跨阶段空转；且 GV3 收紧已消除最常见一类 in-stage 重报源）。

---

## 1. 事实（L1 产权，本文只引用 + 补代码 map）

### 1.1 现象（Q5–Q8，L1 已录）
- **Q5**：scatter validate `[GV3→docgen]`（§4.0.4 函数签名表 vs §4.1.4 函数体缺 `__gm__ uint8_t*` 参数，标 `建议非强制`）→ 耗尽 3 iter → `known_issues: 终稿 stale` 逃逸，**无 docgen 重渲染触发**。aggregate `[GV3→docgen]`（§4.0.4）同型。
- **Q6**：aggregate `[GV8-A→tiling/T2]`（伪代码非代码块级）、manifold `[GV3/GV4→tiling/T1]`（buffer 数 vs UB-factor 数学不符）validate 烧满 3/3 iter 重报同一 blocker（`iteration 4/5 复查确认与 iteration 3 一致`）才 loopback 到 tiling。
- **Q7**：scatter validate decision_log iter 1&2 声称已修 `DeQue` 误用、实际未落盘，iter 3 重读才真改（白烧 2 iter ~7min）。
- **Q8**：multi_add anchor AC3 全 advisory（`verdict=verified/unverified`）触发全 tiling→docgen 重生成。

### 1.2 代码 map（本文首次落入，L4 锚点；general-purpose agent 核实）
- **validate 门**：`ValidateStage(_DesignGate)`（`design_substages.py:2324-2400`，`agent_name=ascendc-design-reviewer`，`issue_target_mapping={docgen:redo_doc, tiling:redo_tiling, human:human}` `:2394`）。gate 基类 `_DesignGate`（`:971-1092`）：`is_satisfied = not blocking_issues`（`:1000-1002`）、`blocking_issues=_scope_filter(_raw)`（`:1068-1072`）、`resolve_condition` 按声明序路由（`:1074-1092`）、`error_signature=issue_fingerprint`（`:1004-1008`，管跨阶段 stagnation）。
- **in-stage 预算=3**：`resources/orchestration-config.json:99` `validate:3`（覆盖 default）；**跨阶段配额**：`detailed_design_group{max_corrective:3, max_escalations:1}`（`:104`）——两个独立计数器（report.md 看到的"3 iter"是 in-stage 重试，loopback 配额另算）。GV1-GV10+SR1-4 检查码在 **SKILL**（`ascendc-op-design-validate/SKILL.md:65-136`）非代码。
- **step-78 实况**：shipped 是 `GateRoute(target, fix_owner XOR advisory XOR escalate)`（`domain/gate_scope.py:31-71`），**非** impl 文档 §1 描述的 `GateCheck(self_fixable, fix_owner, feedback_channel)` 形。`ascendc-op-design-validate/schema/gate_scope.json` 三路由：`tiling→fix_owner=ascendc-op-tiling-split + feedback_channel=ascendc-op-design-feedback-selfcheck`（真消费者）；`docgen→advisory:true`（**无 fix_owner、无 feedback_channel**，描述明写"P83 前逃 redo_doc 不在 transition table→带 known-issue 前进不 loopback"）；`human→escalate:true`。load-time 校验对 advisory 路由**空过**（`GateRoute.__post_init__:63-71` advisory 不要求 feedback_channel）。
- **无 docgen 重渲染 loopback**：`_DETAILED_DESIGN_TRANSITION_TABLE`（`design_tree.py:69-90`）**只有** `redo_tiling:(tiling,corrective)`；`redo_doc`/`human` 故意缺席（`:78-82`：docgen `actions()` 恒 `[]` 确定性重渲染永不收敛，故"不 halt，带 known_issue 前进"）。**validate 只能 loopback 到 tiling。**
- **severity 不 gate loopback（Q8）**：`is_satisfied`/`resolve_condition`/`blocking_issues` **从不读** `severity`/`verdict`。schema 有 `severity:blocker/warning`+`verdict:verified`（`schema/blocking_status.json`），但 `issue_render.py:45-60` 只把 verdict/remediation 当"建议非强制"渲染=**display only**。`blocking_issues` 里任何 issue 都触发 loopback 不分 severity。
- **无落盘校验（Q7）**：`transition` 读 `blocking_status.json`（`:2358`）+ 捕 decision_log（`:2368`），但**不重读被编辑产物文件**确认 claimed edit 落盘。SKILL.md:184 自检"所有可修正问题已就地修正"是 **LLM 自陈**。`_merge_issue_history`（`:2384`"防 tiling 假装修"）防的是**跨轮 tiling** 假修（经 feedback-selfcheck），**不**校验 validate 自己的 claimed edit。

---

## 2. 根因（L3 产权）+ step-78 对照分类

### Q5 → (C) 设计如此的越界 + 缺消费端，叠加 SKILL 违规
step-78 **故意**把 docgen-target findings 路由为 advisory→known_issue 前逃、无 re-render 消费端（`gate_scope.json` docgen 路由 + `design_tree.py:78-82`）——**非回归**。但两重缺陷：① **validate 本不该查 docgen 终稿**：SKILL.md（`:36,70,92,102`）反复告知 validate *不查终稿*，`[GV3→docgen] §4.0.4-vs-§4.1.4` 恰是它不该发的终稿表-体检查（§2.9 门不越界查下游）；② **缺 docgen 重渲染消费端**：advisory 前逃让 issue 直接 stale 逃逸（Q5 实证"终稿 stale 未修"）。**根因=职责越界（查了不该查的下游）+ 若真要查则缺构造性保证/消费渠道，非控制流 bug。**

### Q6 → (B) step-78 未覆盖的盲区
step-78 治"issue 路由到哪个 target"，**没治"in-stage 何时停重试、转 loopback"**。in-stage 预算(3)与 loopback 正交：executor 在 gate 满足前 in-stage 重跑到预算耗尽**才** `resolve_condition` 路由到 tiling。每次 in-stage iter 重读**未变的** tiling 产物（validate 不能自修 tiling 问题，SKILL.md:100,180 tiling issue 只报不修）重报同一 `blocking_issues`；`error_signature` stagnation（`:1004-1008`）检测 same≥2 但管**跨阶段**配额、非 in-stage 重试。**无机制短路这段浪费的 in-stage 空转。根因=in-stage 重试预算对"本 stage 不可自修、必须 loopback"类 issue 无意义空转。**

### Q7 → (B) step-78 未覆盖的盲区
无 validate 自己 claimed edit 的落盘校验；step-78 没加 file-vs-log 检查。`_merge_issue_history` 管的是**另一个 actor（tiling）**跨轮假修，非 validate 自陈。**根因=validate 自检信 decision_log 胜过信文件内容（违反 §1.13 产物权威），放大 Q6 空转。**

### Q8 → (B) step-78 未覆盖的盲区
路由 severity-blind；step-78 只 scope target/code（INV-A），**没让 loopback 条件化于 `severity=blocker`/`verdict≠verified`**。一个 advisory 级（valid owned code + `target=tiling`）findings 仍触发整轮 redo_tiling loopback。**根因=loopback 触发只看"blocking_issues 非空"，不看 severity/verdict，advisory 与 blocker 同等触发全尾重跑。**

**综合**：四者**无一是 step-78 回归**。Q5 是 by-design 越界+缺消费端(C)；Q6/Q7/Q8 是 step-78 正交未覆盖的三个盲区(B)——step-78 管"issue 路由正确性"，没管"重试时机(Q6)/编辑落盘(Q7)/severity 门控 loopback(Q8)"。

---

## 3. 选项（四把尺子）

四个修复独立、可分步。总原则：validate 守本职（只查本 stage 产物 + 一次检测即路由），不越界查下游、不空转、不 severity-blind（§2.9）。

### 修复 Q5：validate 不查 docgen 终稿
- **⚠️ 实施期订正（V6 实证）**：原 ⓐ 表述"表与体由**同一份**源同源派生 → docgen 构造性保证"**与实证不符**。查 docgen SKILL.md：§4.0.4 函数签名表 ← `tiling_strategy.json` 共享签名，§4.x.4 Kernel 体 ← `buffer_kernel.kernel_pseudo_code`，**两者不同源**——表↔体一致性**非**同源构造性可保（V6 结论）。故本修复的真正落点**不是**"删一个会触发 loopback 的检查"（docgen 本就 `advisory:true` 无 loopback，Q5 churn 是 in-stage 重报=Q6），而是**收紧 GV3 措辞防 reviewer LLM 越界**。
- **ⓐ（已实施，订正后）收紧 GV3 scope**：GV3 措辞原只列"TilingData↔Kernel 伪代码"等对象、未 pin 输入来源，reviewer LLM 遂把 §4.0.4/§4.1.4（终稿章节）读进 GV3。**已在 `ascendc-op-design-validate/SKILL.md` GV3 补**：核对对象只限产物（`tiling_results.<tpl>.split/.buffer_kernel`）、**明确不核终稿 design_doc**、**禁在 GV3 issue 里引用终稿 §编号作证据**（§2.9 门不越界查下游 + discover-but-can't-fix 逃逸）；终稿表↔体渲染一致性归 docgen 自检（不同源，非本门可裁）。UT `test_validate_skill_scope_contract.py::{test_gv3_scoped_to_products_not_final_doc, test_gv3_forbids_citing_final_doc_section_numbers}`。
- **ⓑ 接 docgen 重渲染消费端**：给 `redo_doc` 接真 loopback。**仍否决**——docgen `actions()` 恒 `[]` 永不收敛，且不解越界根因。
- **ⓑ 接 docgen 重渲染消费端**：给 `redo_doc` 接一个真能重渲染 docgen 的 loopback（`design_tree.py` 加 `redo_doc:(docgen,corrective)`）。**否决**——docgen `actions()` 恒 `[]` 确定性重渲染永不收敛（`design_tree.py:78-82` 已述），接了也是空转；且没解决"validate 越界查下游"根因。
- **四把尺子**：ⓐ 架构合理（职责归位：终稿一致性@docgen 构造性保证，validate 不越界）、可维护（消除 §2.9 越界）、可诊断（不再有 stale 逃逸的假闭环）；ⓑ 违反"构造性保证优先"且不收敛。**推荐 ⓐ。**

### 修复 Q6：一次检测即 bounce，取消 in-stage 重报空转
- **判据**：对 validate owned code 中**本 stage 不可自修、必须 loopback 到 tiling** 的 issue 类（GV3/GV4/GV8 tiling-target），首次检测即 `resolve_condition` 路由，**不进 in-stage 重试**。in-stage 预算只留给 validate **能自修** 的 issue（就地 Edit 源产物）。
- **四把尺子**：可诊断/可维护（消除 ~8-10min/算子空转）、架构合理（in-stage 重试语义=自修重验，对不可自修类无意义）。**风险**：需区分"validate 可自修" vs "必 loopback"的 issue 类——SKILL.md 已声明（tiling issue 只报不修 `:100,180`），按 target≠自身即 bounce。**推荐。**

### 修复 Q7：validate 自检落盘校验（已实施为 skill 自检项）
- **判据**：validate 对 claimed 已修的产物，**重读文件确认 edit 落盘**，未落盘不算已修（§1.13 产物权威）。
- **实施落点订正**：不做 Python transition 侧文件比对（validate 就地 Edit 的是**源产物文件**，transition 侧无 issue→文件的确定性映射，且这属 reviewer agent 本职自检 §2.9），改为 **skill 自检项**——已在 `ascendc-op-design-validate/SKILL.md` §9 输出自检加"就地修正已落盘核实（信文件不信 log）"：每个声称已 Edit 的问题重新 Read 目标文件确认改动真在文件里，禁凭上一轮 decision_log"已修"记录判定，文件与 log 不符以文件为准。UT `test_validate_skill_scope_contract.py::test_selfcheck_verifies_edit_persisted`。
- **四把尺子**：可诊断（不再信 log 假闭环）、架构合理（自检以文件为准、归 reviewer 本职 §2.9）。**低风险小修，已做。**

### 修复 Q8：severity 门控 loopback（**暂不实施——V5 未过**）
- **判据（原）**：loopback 触发从"blocking_issues 非空"改为"存在 `severity=blocker` 且 `verdict≠verified`"；advisory 只记录不 loopback。
- **暂不实施的理由（V5 未过 + 风险）**：① **V5 未证**——`severity`/`verdict` 是 **LLM 自标**，`issue_render.py:45-60` 现仅 display，从未当控制流输入；把 loopback 条件化于未经稳定性验证的 LLM 标注，风险是**真 blocker 被误标 advisory → 静默漏修**（比 Q8 的"advisory 触发多余 loopback"后果更重，违 §1.2 可诊断——静默吞问题）。② **本批 Q8 实证的 advisory 全尾重跑，多数已被 Q6 修复间接缓解**——Q6 的"一次检测即 bounce、不 in-stage 空转"砍掉重复触发；剩余"单次 advisory 触发一轮 loopback"成本远小于误标漏修风险。③ 若要做，须先补 V5：advisory 判定需**确定性**依据（如 gate_scope route 的 `advisory:true` 已是**结构化、非 LLM 标**的确定信号——docgen 路由已 advisory 前逃不 loopback，这是对的方向），而非依赖 issue 级 LLM `verdict`。**结论：保持 blocker 默认（所有 owned-code issue 触发 loopback），advisory 抑制只信 gate_scope 结构化 route（已有），不接 issue 级 LLM verdict。待 V5 有确定性判据再议。**

### 修复 Q6：一次检测即 bounce（**深评后暂缓——控制流风险**）
- **判据（原）**：tiling-target issue 首检即路由、不 in-stage 重试。
- **深评后暂缓**：in-stage 预算(3)与跨阶段 corrective 配额是**两个独立计数器**（`orchestration-config.json:99 validate:3` vs `:104 max_corrective:3`），改"首检即 bounce"要动 `graph_executor._execute_sequential` 的 gate 重跑逻辑（`:359-660`），影响所有 gate（review/anchor/validate 共用 `_DesignGate`），**回归面大**；且 `error_signature` stagnation（same≥2 止损）已对**跨阶段**空转兜底。本批 Q6 的 in-stage 重报浪费真实存在，但**修复收益（省 ~8min/算子）vs 动共用 gate 控制流的回归风险**不成比例，且 §1.2 要求"最小改动 vs 正确改动按工程价值取舍"。**暂缓，留作独立 L4 专项**（需先给 gate 控制流补足 UT 覆盖再动）。当前 Q5 的 GV3 收紧已消除**一类**最常见的 in-stage 重报源（越界查终稿的 stale issue）。

---

## 4. 推荐 + scope（2026-07-31 实证订正 + 实施）

**关键订正（两个后台 agent 逐产物核实,推翻早先假设）**：
- **loopback 机制本身是好的、真解决问题**——aggregate tiling 从 0/0/0 真实 API → 12/4/3;manifold 7-buffer UB 超限 39% → 6-buffer 全 ≤上限;multi_add 1 次 loopback 解 #1-#4 + integrate 解 #5。产物 mtime + reviewer 可复算判据(正则/UB 算术)证明**非"换轮次放行"**。**故不改 loopback。**
- **真正缺陷是三个,全部实证根因(非压制表现)**：

**① Q6/F-a in-stage 空转（✅ 已修，根因驱动）**:validate 首检即知 target=tiling(只读修不了),却烧满 3 iter 对**冻结产物**重报同一问题(reviewer 自写"与 iteration N-1 一致")。修:`_DesignGate.stop_in_stage_retry`——本轮 blocking_issues 全部命中 fix_owner(loopback)route 时首检即停重试 → resolve_condition 立即 loopback;判据是**结构信号(gate_scope route 模式)非 issue 内容启发式**;存在自修/advisory 项则保留重试(保守)。runner 早停 hook 复用既有 is_satisfied break 机制,不动共用 executor 循环。UT `test_gate_stop_in_stage_retry.py`(5)。

**② Q5+B2 误报（✅ 已修，根因驱动）**:validate `_upstream_inputs` 只物化 `tiling_results`(integrate **前** per-template 合并态,旧命名),**没物化 `tiling_strategy`**(integrate 产出的**跨模板统一契约**),导致 validate 看不到统一结果 → 幻觉"integrate 未执行" → 把已解决的跨模板命名 issue 重报 advisory(multi_add 实证)。修:`_upstream_inputs` + `input_contract` 补 `tiling_strategy`;SKILL.md GV2 改核 `tiling_strategy`(统一契约权威源)非 stale `tiling_results`。

**③ docgen 终稿 A3 零消费者（✅ 已修，用户洞察 + 实证）**:A3 codegen `_build_codegen_prompt` grep `design_doc`=0、`input_contract` 不含 design_doc、框架三处注释"no downstream consumes"。**A3 上校验终稿一致性从源头无意义**(修了不影响端到端)。修:SKILL.md 加根本原理块 + GV3 收紧(不核终稿/禁引 §编号,已在前轮)。

**④ Q7 落盘校验（✅ 已修，manifold 实证靶点）**:manifold 前 3 轮 `fixed_in_place` 声称改了但产物未落地。已由 SKILL.md §9"落盘核实、信文件不信 log(§1.13)"(前轮)覆盖,本批 manifold 证据确凿。

**⑤ F-c issue 归错 target（✅ 已修，用户问题1 方向——比"改路由"更根本）**:multi_add #1/#2(不存在的 Cast RoundMode 枚举/`SetScalarValue`)detail 自称"codegen 层 API 命名,非 tiling 能力层",却 target=tiling。**用户订正:不改路由(治标+仍越界),而是让生产者自检(§2.9 生产者自检优先于检查门)**——① **anchor 收窄 AC3**:SKILL.md AC3 加边界"只查仓库范式,禁扩用成 codegen 层 C++ API 字面量审查(枚举拼写/API 调用形式/签名)",从源头不产生这类错位 issue;判据"claim 若须落到具体 C++ API 字面拼写才能证伪 → 不属 anchor"。② **codegen 自检兜**:SKILL.md Step6 加**维7 Kernel API 字面量正确性**(codegen 本职,查 RoundMode 真实枚举集、禁造 `CAST_FP16_TO_FP32`、`SetScalarValue`→`Duplicate`+`DataCopy`,查知识库不靠记忆)。UT:`test_anchor_closure.py::test_ac3_excludes_codegen_cpp_api_literal_audit` + `test_codegen_selfcheck_dims.py::test_step6_has_dim7_kernel_api_literal`。**不用"写中间产物给下游消费"**——anchor 根本不必查(codegen 自检更合适),不引入跨 stage 传递(该方案留作"必须检查且必须下游解决"时的 fallback 原则)。

**关键设计约束**：
- validate **守本职**(§2.9):只查本 stage 能写的源产物 + 统一契约;下游终稿零消费者 → 不核;上游 tiling 正确性由 tiling 自检,validate 首检即 bounce 不空转。
- **severity/verdict 不升为 loopback 门控**(推翻早先 F2):它们是 LLM 自标,条件化 loopback 于未验证标注风险=真 blocker 误标 advisory 静默漏修(违 §1.2)。**advisory 抑制只信 gate_scope 结构化 route(docgen:advisory 已有)**,不接 issue 级 LLM verdict。
- **不重复 step-78**:修的是 step-78 正交盲区,不动其 INV-A/gate_scope 路由正确性。

**F-c 全项排查（用户要求不局限 AC3，后台 agent 逐码审计）**：排查 anchor-per-template AC0/AC1/AC2/AC4 + anchor-consistency 全码 + validate GV1-GV10，**AC3 是唯一 C++ 落地越界孤例,其余全合法**——AC0(claim 存在性)/AC1(verification 字段)/AC2(硬件能力可用性,`Gather` 是能力名非字面拼写)/AC4(block_dim source 是否静态核数,判据落 `source_pointer` 字段,`GetCoreNumAiv` 只在 remediation)/consistency-AC3(跨模板一致性,正确路由 target=integrate) 判据都停在"能力可用/值来源/跨模板契约自洽"抽象层。validate GV10(旧宏→POD 就地重写)与 codegen Step5 职责重叠但各在不同产物层闭环、就地可修非错位,不越界。**结论:不需改 anchor 其他项(改了是过度收缩)。**
> **守门边界原则(可复用判据)**：判据落"能力可用/值来源合规/跨模板契约自洽"(产物结构信号+权威源可判)=合法;滑向"某 API 枚举拼写对不对/签名可否编译/生成 C++ 长什么样"=越界,归 codegen 自检。

**scope**：本 L3 覆盖 design validate 门（Q5–Q8）+ F-c(anchor AC3 越界)。不含：Q9（report loopback 可观测，已记录暂缓）、Q11（硬超时，不做）、Q1–Q4/Q10（codegen/框架，另三份 L3）。

---

## 5. 待用户拍板 + 待核实

**决策点（实施后更新）：**
- **F1（Q5）——✅ 已实施（订正版）**：V6 实证表↔体不同源（非构造性可保），故落点不是"删检查"（docgen 本无 loopback）而是**收紧 GV3 scope**——SKILL.md GV3 补"只核产物、不核终稿、禁引用终稿 §编号"。弃 ⓑ（不收敛）。UT 2 个。
- **F2（Q8）——❌ 暂不实施（V5 未过）**：severity/verdict 是 LLM 自标、从未当控制流输入；条件化 loopback 于未验证标注，风险=真 blocker 误标 advisory 静默漏修（比多余 loopback 后果重，违 §1.2）。**保持 blocker 默认；advisory 抑制只信 gate_scope 结构化 route（docgen:advisory 已有），不接 issue 级 LLM verdict。**
- **F3（Q6）——⏸️ 暂缓（控制流回归风险）**：首检即 bounce 要动 `graph_executor` gate 重跑逻辑（review/anchor/validate 共用 `_DesignGate`），回归面大 vs 收益（~8min/算子）不成比例；stagnation 已兜跨阶段空转。留独立 L4 专项（先补 gate 控制流 UT）。Q5 的 GV3 收紧已消除最常见一类 in-stage 重报源。
- **Q7——✅ 已实施**：SKILL.md §9 自检加"就地修正落盘核实（信文件不信 log，§1.13）"。UT 1 个。

**待核实（结论）：**
- **V5（Q8）**：LLM `建议非强制`/`verdict` 标注**未证稳定**——故 F2 暂不接 issue 级 verdict 当 loopback 门控。若要做须先给 advisory 确定性判据（gate_scope 结构化 route 才可靠，非 issue 级 LLM 标）。
- **V6（Q5）——已证否**：docgen §4.0.4 表 ← `tiling_strategy` 共享签名、§4.x.4 体 ← `buffer_kernel.kernel_pseudo_code`，**不同源**，表↔体一致性**非**同源构造性可保。故 F1 落点是收紧 GV3 防越界（reviewer 不该查终稿），非"删同源检查"。

---

## 6. 句柄（取证 + 代码锚点）

- L1：`84-batch-205112-issues-summary.md` Q5/Q6/Q7/Q8
- 关联 plan：`78-gate-scope-ownership-contract-{analysis,impl}.md`（step-78，本文对照基准）、`76-design-review-infeasible-loopback-analysis.md`（越界+前逃范式）、`35-loopback-routing-and-incremental-analysis.md`（loopback 路由）、`60-design-escape-hatch-*.md`（redo_doc 前逃由来）
- 门代码：`orchestration/stages/design_substages.py:{2324-2400 ValidateStage,971-1092 _DesignGate,1000-1008 is_satisfied/error_signature,1068-1072 blocking_issues,1074-1092 resolve_condition,2358/2368/2384 transition+merge_issue_history}`、`domain/gate_scope.py:{31-71 GateRoute,63-71 __post_init__}`、`orchestration/.../design_tree.py:{69-90 TRANSITION_TABLE,78-82 redo_doc 缺席}`、`orchestration/.../issue_render.py:45-60`（severity display-only）
- 配置：`resources/orchestration-config.json:{99 validate:3,104 detailed_design_group}`、`ascendc-op-design-validate/schema/gate_scope.json`（三路由）、`schema/blocking_status.json`（severity/verdict 字段）
- skill：`.claude/skills/ascendc-op-design-validate/SKILL.md:{36,70,92,102 不查终稿,65-136 GV/SR 检查码,100,180 tiling issue 只报不修,184 自检自陈}`
- 实证：scatter/aggregate/manifold events.jsonl validate iteration_start（3 iter 重报）+ `artifacts/design/validate/decision_log.json`（Q7 声称已修未落盘）
