# step-79 — design 阶段 human 决策通道：用 in-flow `resolve_ambiguity` 替代 `__halt__`（L3 方案分析）

> **状态：已冻结（2026-07-28）**——a/b/d 拍板 + c 查证 + GV7-A/B 落点定方案 X。下一步排 L4（实施方案）。
> **覆盖问题**：P118（`06-problems.md`）。
> **关联**：step-60（设计逃生 + halt 仅限 429 拍板）、step-78（INV-A 残余缝）、step-61（review 三向路由）。

---

## 0. 问题（一句话）

review 门把 `GD-H*`/`GD-CR2 真方向歧义` 标 `target=human` → `design_needs_human` → `__halt__`（`design_tree.py:44` + `workflow.py:264`），**整轮 run 硬终止**（`graph_executor.py:470-497`，`is_terminal=True`）。但：

1. 这违反 step-60 已冻结决策「**设计质量门不 halt**，halt 仅留给 429 这类服务端不可用」（`60-analysis.md:17`）——step-60 修C 已据此删 validate 的 human halt，review 的对称清理未做。
2. `__halt__` 是 abort 语义（流程终止，人离线介入后另起新 run），而"需人决策"本该是 suspend 语义（流程内挂起等人、拿到答案继续）。
3. reviewer **手上已有** `resolve_ambiguity`（`agents/ascendc-design-reviewer.md` allowed_tools；§4.4；`engine_mcp_stdio.py:178` "waits on a decision"）——in-flow 向人提问的通道已存在，该路由却没用它，转而让整条 pipeline 死掉。

> 事实层详见 P118 L1。本文只做选项取舍（方案层）。

---

## 1. 目标不变式

继承 step-60 三条 + 新增第四条（人作为流程内环节）：

1. **预算尽后才逃生**（corrective loop 保留）——对齐 step-60。
2. **产物不能少**（逃生前提 = `output_contract` 满足）——对齐 step-60。
3. **halt 仅留给服务端不可用 / 硬故障**（429、corrective 全耗尽、基础设施挂）——对齐 step-60；**design 质量门不因"需人决策"而 halt**。
4. **【新增】人作为流程内环节，in-flow 提问优先于 halt**：需人决策时，agent 优先用 `resolve_ambiguity` 在流程内提问（suspend），拿到答案转 corrective 给 producer 继续；halt 是人**也**无法决定 + 逃生预算耗尽后的 last resort，不是"一需人就终止"。

---

## 2. 选项

### O0 维持现状（review human→halt）
- **否决**：违反 step-60「设计门不 halt」决策；abort 承载 suspend 语义；reviewer 持有的 in-flow 通道闲置。

### O1 删 review 的 human 路由，全走 corrective / 前逃
- 即 review 只留 `generator`/`requirement` 两向，human code 一律不 emit（或 emit 后 route=None 前逃）。
- **否决**：`GD-H*` 真方向歧义 producer **修不了**（producer 只能猜，猜了不算解决）→ 要么变带毒前逃（违背"产物不能少/质量"精神），要么把人决策入口删了（人无从介入）。失去"人作为流程内环节"的正当通道。

### O2 ✅ 主推：reviewer 用 `resolve_ambiguity` 流程内提问 → 人决策转 corrective feedback
- reviewer 判 `GD-H*`/`GD-CR2 真方向歧义` 时，**不写 `target=human` → halt**，而是**就地在流程内调 `resolve_ambiguity`** 向人提问（"反向传播要不要支持？意图 A 还是 B？"）。
- 拿到人决策后，因 reviewer 只评审不重设计（manifest 边界："你只做判定与最小修复，不做重新设计"），把人的决策**转写为 `target=generator`/`requirement` 的 blocking_issue**（带人决策的 `loopback_feedback`），走既有 corrective 闭环让 producer 拿着人的决策去修。
- 非交互/CI 下走 `resolve_ambiguity` 的 `default` 策略（受控、非静默；§4.4 "must NOT silently pick"）。
- halt 只保留给：人显式拒绝/也无法决定 **且** corrective 预算耗尽（此时前逃 known_issue 仍优于 halt，见 §5-a）。

### 子项（与 O2 并行，针对 validate/anchor 的 attribution 缺陷）
- **O2-a `GV7-A`/`GV7-B` 落点（c 查证 + 方案 X 确认）**：公式 provenance = **requirement**（`requirement.json` 的 `math_formula` 字段，`op_spec_schema.md:100`），且 requirement 已声明能力 `math-equiv-golden`（产公式后自检与 golden 等价，不等 re-derive，真冲突 resolve_ambiguity→human；`capabilities.json:4-5`）。由此推导落点：
  - **GV7-B（公式↔伪代码不一致）**：公式侧权威（requirement 已 `math-equiv-golden` 自检）→ 不一致错在伪代码 → `target=tiling` 走 `redo_tiling`（buffer-kernel 重产伪代码）。validate 不加 requirement route（守 INV-A「routes 不含 requirement」+ §2.9 门不越界查上游公式正确性）。
  - **GV7-A（公式修正项含位置下标 = 公式内部缺陷）**：公式"对不对"是 requirement 层**构造性保证**（§2.9）→ **强化 requirement `math-equiv-golden` 自检**让它兜住此类（前移上游自检），而非 validate escalation 回 requirement（守 P83 详设不 escalation）。validate 侧 GV7-A 不再判 human：发现公式缺陷 = requirement 自检漏网 → 标 known_issue 前逃 + 反馈强化上游自检。
  - **caveat（L4 确认）**：`math-equiv-golden` 是"数值等价"自检，能否 catch GV7-A"修正项含位置下标"这类**结构**约束存疑（数值等价 ≠ 结构正确）；若不能，GV7-A 仍需一个结构层校验点（留 validate 但判 tiling/前逃，不回 requirement）。
- **O2-b `GV9-b` 绑定 corrective 耗尽**：GV9-b 是上游锚点门 AC0/AC1/AC2 阻断的再标记，而 AC0/AC1/AC2 在锚点门自身路由 `target=tiling`（corrective）。GV9-b 的 human 升级条件应从"无条件"改为"tiling corrective 已耗尽仍未解"——耗尽前不该跳过 producer 直接交人。
- **O2-c 清 anchor 死配置**：anchor 的 `gate_scope.json` 声明 `target=human, escalate:true`，但 `SKILL.md:86` 把 `owner_ambiguous` 实际标 `target=integrate`，human 路由从未被 emit。按 §1.4（不留死配置）删该声明，或显式归入 P83 前逃哲学并改 description。

---

## 3. O2 主方案设计要点（待拍板后落 L4 细化）

- **触发点**：review skill 判 `GD-H*`/`GD-CR2 真方向歧义` 时，引导 agent 调 `resolve_ambiguity`（而非产 `target=human` blocking_issue）。判据用业务语义（§1.10）：「连需求层都定不了的方向性歧义」才触发提问，"难修/缺信息"归 generator/requirement（已有判据，`SKILL.md:104-119`）。
- **人决策落地**：reviewer 把 `resolve_ambiguity` 返回的决策，写成 `target=generator`/`requirement` 的 blocking_issue（`loopback_feedback` 携带人决策原文），复用 step-61 既有的 review→generator/requirement corrective 通路（`redo_generator` / `design_input_invalid` bubble 带 feedback）。**不新增路由**——复用 step-61 三向路由，只是把 human 这一向的"halt"换成"提问→转 corrective"。
- **非交互降级**：`default` 策略下（CI），`resolve_ambiguity` 选首项后照样转 corrective；若首项导致 producer 仍修不好，corrective 耗尽后走 known_issue 前逃（不 halt）。
- **halt 边界（收紧后）**：design 阶段 halt 仅留"corrective 全耗尽 + 产物残缺（`output_contract` 不满足）"——即 step-60 不变式 2+3 的交集；纯"需人决策"不再 halt。

---

## 4. 四把尺子（§1.2）

- **可维护**：O2 复用 step-61 既有三向路由 + §4.4 既有 `resolve_ambiguity` 通道，不新增控制流原语；兑现 step-60「设计门不 halt」不变式，澄清了 halt 的语义边界（abort vs suspend）。
- **可扩展**：判据用业务语义（"连需求层都定不了"才提问），同类新方向歧义自动归位到 in-flow 提问，不必每次打补丁。
- **可诊断**：`resolve_ambiguity` 的提问/决策有结构化记录（§4.4 受控非静默），比 halt 后"流程外离线诊断"可观测性强；转 corrective 后 producer 修没修好有 `is_satisfied`/`acceptance` 闭环信号。
- **架构合理**：修复落在职责正确的层——"需人决策"归 agent 的 in-flow 提问（§4.4 已为编排型 agent 定义此职责），halt 归真·无法继续的硬故障。纠正了"用 abort 承载 suspend"的层/语义错配。

---

## 5. 拍板记录（2026-07-28 用户决策）

- **a ✅ 已拍板**：人也无法决定时 → **前逃**（known_issue + `needs_human_decision`），不 halt（对齐 step-60「设计门不 halt / 不完美设计也进 codegen」）。halt 留给"产物残缺"（不变式 2）+ corrective 全耗尽。
- **b ✅ 已拍板**：`resolve_ambiguity` 的 `default` 策略对 GD-H* → **转 known_issue 前逃 + 标 `needs_human_decision`**，非"选首项继续"（避免 CI 下用错误决策一路修）。
- **d ✅ 已拍板**：**全范围**——review / validate / anchor 凡涉此类 attribution 问题（误判 human / 用 halt 承载需人决策 / 死配置）都改。
- **c ✅ 已查证**：公式 = requirement 的 `math_formula`（`op_spec_schema.md:100`），requirement 已声明 `math-equiv-golden` 自检能力（`capabilities.json:4-5`）。衍生 GV7-A/B 落点见 §2 O2-a。
- **✅ GV7-A/B 落点已确认方案 X（2026-07-28）**：公式正确性归 requirement 自检（构造性保证 §2.9），validate 只查一致性→tiling；**不给详设加 requirement escalation**（守 P83 详设不 escalation + INV-A routes 不含 requirement）。GV7-B→`target=tiling`/`redo_tiling`；GV7-A→强化 requirement `math-equiv-golden` 自检，validate 侧发现公式缺陷=上游自检漏网→前逃+反馈。**caveat（L4 确认）**：`math-equiv-golden` 数值等价能否 catch GV7-A"修正项含位置下标"这类结构约束；若不能，GV7-A 补结构校验但仍判 tiling/前逃，不回 requirement。

---

## 6. 与既有工作边界

- **step-60 修C**：已删 validate 的 human halt（前逃）。O2 是其**概设对偶**——review 的 human halt 也该按同一哲学改造，只是用 in-flow 提问而非简单前逃（因 GD-H* producer 修不了，前逃=带毒）。
- **step-61**：review 三向路由（generator/requirement/human）+ `_DesignGate` 公共基类 + review→requirement bubble 带 feedback。O2 复用其 generator/requirement 通路与 feedback 渲染，**只改 human 这一向**（halt → 提问转 corrective）。
- **step-78 INV-A**：scope 纪律 + `_scope_filter`。O2 不动 INV-A（human 仍在 scope 内合法），改的是 human 的**下游承载**（halt → in-flow）。
- **§4.4 / `resolve_ambiguity`**：既有 MCP 通道，O2 是其设计用途的正常应用（编排型 agent 流程内向人澄清），非新机制。

---

## 7. 明确不做

- **不改 `graph_executor` 的 `__halt__` 语义**（`is_terminal=True` 硬终止）——halt 仍是真·硬故障的正当 abort，语义不动；改的是 design 路由**不再把"需人决策"导向 halt**。
- **不给 anchor 死配置加 wiring**（让 owner_ambiguous 真 emit human）——那是反方向（把死配置变活 = 增加 halt 面）。O2-c 是**删声明**，按 §1.4 / §2.5 单一通路清理。
- **不把 GD-H* 改成 producer corrective**——方向歧义 producer 修不了（O1 已否决）；O2 是"人决策 → 转 producer corrective"，决策主体是人，producer 只执行人的决策。
