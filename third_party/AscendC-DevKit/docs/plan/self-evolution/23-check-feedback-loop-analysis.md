# P44/P45 — 详设反馈通路收口（check 越界 + loopback 显式消费）— 方案分析（第三层）

> 状态：已冻结 + 已实施（2026-07-07，P44=B+C、P45=第一刀+(a)，详见 `24-check-feedback-loop-impl.md`）
> 层级：**第三层 / 方案分析**。选项 + 取舍 + 拍板理由。
> 覆盖问题：P44（check stage 越界硬件判定 + 下结构改造令）、P45（loopback 反馈消费端契约缺失）。
> 输入：run `20260706-192227-63c875` 复盘 + L1 `06-problems.md` P44/P45 + 代码现状调研。
> **承接**：`17-anchor-truth-loopback-analysis.md` / `18-...-impl.md`（P24-P27）。本 L3 是其在「反馈产出端的越界」与「反馈消费端的契约」两处的**剩余缺口**，不是新造方案。
> 约定：按符号定位（不写 file:line）；外部依赖（CANN / 知识库文档 / chip spec）只读。

---

## 1. 定位：P44/P45 是 17/18 的延伸缺口

17/18 已定三决策并部分落地：
- **P24**（硬件参数**数值**单源）：chip spec 唯一源、删内置真值表、anchor 消费 `hw_params.json`。
- **P25**（失败原因可读）：统一 `render_issue`、loopback payload 携完整 detail 注入下游 prompt。
- **P26**（read-only gate 闭环）：anchor `max_iter=1` 首轮即 forward；不变式 II「能自修才自迭代，否则 max_iter=1 即 forward」。

落地核查（本次调研）：anchor `disallowed_tools=[Write,Edit,Glob]` 已设、两 anchor stage `default_max_iterations=1` 已设、消费 `hw_params.json` 单源已通、基类 `_DesignSubstage._build_prompt` 的 `## 上次反馈` 段已注入下游。

**P44/P45 正是这套闭环的两个漏：**
- **P44（产出端）**：17 的约束（权限 + SKILL + max_iter）**齐了仍挡不住** anchor-consistency 的 LLM agent 执行层越权——越权重做硬件查证、把 API 文档缺项误读为硬件不支持、在 `detail` free-text 里下结构改造令。17 假设「约束齐了 agent 就守规矩」，P44 证伪。
- **P45（消费端）**：P26 假设「forward 给能修的 stage 就能修」，但消费端契约缺失——tiling 子类 prompt 重写丢了 `## 上次反馈` 段（反馈**根本没进 prompt**），加上 issue 无状态/谓词/升级出口。

---

## 2. 现状（代码调研事实）

### 2.1 反馈产出端（check stage）— P44 域

- **约束本就齐**：anchor agent frontmatter `disallowed_tools: [Write, Edit, Glob]`；per-template / consistency SKILL 反复申明「只判定报告、不改产物、不替下游决策」；consistency SKILL 明确「不重新执行 per-template 硬件查证，只汇总」。
- **对质范围被 SKILL 限定为「骨架级 API」**（gather/scatter/reduce/sort/topk/broadcast/transpose）；Exp/Muls/Adds 这类 elementwise **不在范围**，per-template 应标 N/A 直接通过。
- **越界是 consistency agent 实际做的**（SKILL 未授权）：run 的 `anchor_report.json` 原文「本汇总关卡独立靶向核验 910D_knowledge_extra/{Exp,Muls,Adds}.md dtype 行后【坐实】」——违反 SKILL「只汇总不重查」；并把 Exp 只列 half/float 误读为「A5 硬件不支持 bf16」（API 层 ≠ 硬件层，A5 硬件支持 bf16，Adds/Muls 列 bfloat16_t 为证）。
- **同 run 的 per-template（T1）反而正确**：把 bf16 列入 `out_of_scope_advisory`，明说「超出 AC0-AC3 骨架门范围」。越界只发生在 consistency 汇总关卡。
- **issue 数据结构无「判定 vs 补救」分层**：`{code, severity, detail, target, target_template}` 五字段，**无** `remediation/directive/status` 字段。fp32/Cast/tileLength 减半等结构改造令全塞在 free-text `detail` 里，与事实判定（「claim UNVERIFIED」）混煮。改造令经 `loopback_feedback()` 原样灌进下游 tiling prompt。

### 2.2 反馈消费端（生成 stage）— P45 域

- **反馈传递机制存在**：`State._loopback_feedback`（transient）← gate 的 `loopback_feedback()` 钩子原样搬运 `blocking_issues`；基类 `_DesignSubstage._build_prompt` 有 `## 上次反馈` 段，渲染 `[code](target=…, template=…) detail`。
- **直接根因（已核实）**：`_TilingSegmentStage._build_prompt` 重写覆盖基类，其 sections（任务/重试上下文/operator/inputs/skill/当前模板/output_boundary/user_feedback/`_previous_decision_section`/decision_log）**不含 `_loopback_feedback`** → tiling corrective 回退时反馈根本没进 prompt → run 的 3 轮零消费由此而来。`_previous_decision_section`（decision_log 回忆）是另一条通路，与 loopback 反馈互不引用，替代不了。
- **issue 无状态**：`issue_id/resolved/escalated/must_hold` 全工程零命中；每轮 `transition` 整份覆盖 `validation_report`，上一轮 issue 丢失，无跨轮追踪 → 同一 AC1 跨 3 轮逐字重报。
- **配额耗尽只前进**：`max_corrective=3`（detailed-design 组），耗尽后 `i += 1` 继续往下游跑（带未消解 issue），**不升级、不转人工**。停滞检测 `same>=2` 依赖 `error_signature`，gate stage 不重写它 → 对详设 gate 无效。

---

## 3. P44 方案（产出端：check 越界）

### 问题

LLM agent 不守 SKILL（17 约束已齐仍越权）；`detail` 一锅煮给改造令留通道；越权的前提是 consistency agent **拿得到原始知识库文档**去重查。

### 选项

- **A. 纯 SKILL 强化**（软）：consistency SKILL 加粗「禁止重查 / 禁止在 detail 下结构改造令」。
- **B. 能力约束**（硬，治本）：consistency stage **不向 agent 提供原始知识库文档**（`910D_knowledge_extra/*` 等），只给 per-template 已结构化的 `anchor_template_report` + 产物 → 从输入上断掉「越权重查」的能力（呼应 §1.3 机械优于自觉、[[verify-known-risks-statically]]）。
- **C. schema 分层 + 产物校验**（硬，结构）：issue 拆 `status`（判定面：`unverified/infeasible/verified`）+ 可选 `remediation`（非强制、仅建议）；anchor_report 过 schema 校验，`detail` 含改造令关键词（fp32/Cast/tileLength…）则告警/拒绝。

### 取舍

- **A 单独不够**：17 已写过同类约束，agent 仍越权——软约束挡不住 LLM。
- **B 直击能力根因**：consistency 的职责是「汇总 per-template 结论」，本就不需要原始文档；不给它就从根本上消除了重查越权。合法查证需求由 per-template（它该有文档 + 该限定骨架级 API）承担，职责不混淆。
- **C 结构分离判定/补救**：即使 agent 守规矩，把改造令从 `detail` 拆出来也能让下游明确「这是建议不是判决」，并为 P45 消费端「只读判定面」铺路。
- A 与 B/C 不冲突，可作兜底加成。

### 推荐：B + C（A 兜底）

能力约束断越权（B）+ schema 分层分离判定/补救（C）。SKILL 强化（A）作为软兜底。

> 注：B/C 涉及 `.claude/`（agent inputs / SKILL / schema）与 stage inputs 组装（`design_substages` 的 inputs 物化）。skill 侧改动遵守 §2.1（即插即用、不耦合框架）。

---

## 4. P45 方案（消费端：loopback 显式消费）

### 问题

tiling 子类 prompt 丢了反馈段（直接）+ issue 无状态/谓词/升级出口（深层）。

### 选项

**第一刀（立即、最小、无争议 — 纯 bug 修复）：**
- 抽 `_feedback_section(state)` helper（读 `_loopback_feedback` 渲染 `## 上次反馈`），基类与 `_TilingSegmentStage` 共用，消除「子类重写丢反馈」。**只此一刀即让 run 那种 3 轮零消费消失**，不改 schema。

**第二层（治本，分项 — 避免过度设计，按真实残余滚动）：**
- **(a) issue 加 `issue_id` + 跨轮追踪**：`routing_scopes[path]["history"]` 记 `outstanding_ids`；`is_satisfied` 按 ID 集合判消解（替当前的「整体非空」判定）。顺带让 gate 重写 `error_signature` 返回 issue_id 集合 → 停滞检测 `same>=2` 对 gate 生效 → 消解「逐字重报」+ 提供「未消解则停」的自动出口。
- **(b) issue 加 `must_hold` 谓词**：机可判「是否已修」，闭环「生成→验证」。
- **(c) 配额耗尽 + 仍有 outstanding → 自动 escalation**（转 human/halt）。

### 取舍

- 第一刀必做（纯 bug，零争议）。
- 第二层警惕过度设计（[[avoid-overdesign-prefer-reuse]]）：**推荐先 (a)**——issue_id + 追踪一举消解「逐字重报」并激活停滞检测（复用既有 `same>=2` 机制，不新造出口）。**(b) must_hold、(c) 自动升级** 视第一刀 + (a) 后的真实残余再立，避免为可能不发生的场景预造谓词/状态机。

### 推荐：第一刀 + 第二层 (a)；(b)(c) 后置

---

## 5. P44/P45 依赖与时序（关键）

- **若先修 P45 第一刀（tiling 读反馈）而不修 P44**：`detail` 里的改造令（fp32/Cast/tileLength）会真正灌进 tiling prompt → tiling 可能照错误改造令改 → **比现状（反馈没进 prompt、空转）更毒**。
- 故 **P44 的 schema 分层（C：判定/补救分离）须先于或同步于 P45 第一刀**；P45 第一刀读反馈时只取判定面（`status`/事实），不把 `remediation` 当强制指令。
- **推荐时序**：
  1. P44-C（schema 拆 `status`/`remediation`）+ P44-B（consistency 能力约束）
  2. P45 第一刀（`_feedback_section` 共用，只读判定面）
  3. P45-(a)（issue_id + 追踪 + 停滞检测生效）

---

## 6. 待确认点（已拍板 + 已实施，2026-07-07）

1. **P44 方向** → **B + C**（A 作软兜底）。已实施。
2. **P44-B 边界** → **inputs 不传文档（本就成立）+ stage prompt 硬约束**。L4 核实结论：`AnchorConsistencyStage._upstream_inputs` 只给 per-template 报告 + tiling 摘要，**从未传原始知识库文档**；越权通道实为 agent `Read`/`Grep` + SKILL「Grep 知识库查证」引导。工具层无法精确切路径，故硬落点 = stage 级 prompt 注入（`_extra_prompt_sections`），而非工具层路径限制。
3. **P45 第二层范围** → **仅 (a)**（issue_id+指纹激活既有停滞检测）；(b) must_hold / (c) 自动升级后置。
4. **P44-C 改造令拦截强度** → **告警**（`lint_directives`，可诊断不阻断，§6.4）。

状态：**已冻结 + 已实施 + 已验证**（`24-check-feedback-loop-impl.md` Step1-4）。UT 18 绿；heavy_llm e2e 已验证（anchor_hwparams_selfclosure 193s + design_tui_selfclosure 285s 真实 LLM 全绿，P44/P45 真实链路成立）。

---

## 7. 与现有工作的关系

- **承接 17/18（P24-P27）**：P44 补 anchor 越界（17 假设约束足够，P44 证伪 → 加能力约束 + schema 分层）；P45 补消费端（P26 假设 forward 即修，P45 证伪 → 修 prompt bug + issue 状态）。
- **与 P41/P42（session 自检）对偶**：P41/P42 是「session 内一次合格」，本 L3 是「跨 stage 反馈可消费」——同一质量主题的两半。
- **与 P43/P46（codegen 链路）正交**：本 L3 聚焦详设反馈通路（validate/anchor ↔ tiling），不动 codegen/deploy。
