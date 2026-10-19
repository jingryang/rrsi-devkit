# step-78 — gate scope & ownership contract（声明式 gate 检查范围 + capability 归属 + 加载期 join + feedback-selfcheck 泛化）— L3 方案分析

> 性质：self-evolution 线 L3 方案分析，step 78。**架构级全局改造**，根治 step-76 这一类控制流 bug。
> 状态：**拍板（关键决策已锁定），待 L4**。本步覆盖 step-76 的"主修"并升级为结构性根治。
> 承接：**step-76**（暴露 bug 类 + §2.9 第 5 条"门不越界查上游"已落 CLAUDE.md）；**step-60**（halt 边界不动，本步不扩 halt）。
> 不冲突：step-70/72 仍是 training-time 层；本步是 inference-time 编排层的 gate 契约。
> 纪律：L3 只写选项/决策/理由，落点（改哪个函数）留 L4；语义锚点 + 已核实 file 锚点供 L4 取用。

---

## 0. 一句话 + 目标

把质量门的**检查范围（scope）**与**issue 归属（capability）**声明式化，加载期 join 校验 + 运行期 scope 校验 + feedback-selfcheck 泛化，让两个不变量（INV-A 不越界 / INV-B target 能修）**由构造保证**——step-76 那一类 bug（门越界查上游、target 标错、多 issue 字典序丢失、producer 修不了被报的 issue）结构性不再可能。

**全局范围经核实很小**：全仓只有 3 个 issue-routing gate（`GeneralDesignReviewStage` / `AnchorConsistencyStage` / `ValidateStage`），全在 `design_substages.py`、全继承 `_DesignGate`、共享路由逻辑；codegen/precision_debug/perf/requirement 侧无 issue-routing gate。改动面 = 3 个 mapping + 1 个共享基类 + N 个 producer 声明 capability + 1 个加载期校验器 + feedback-selfcheck 泛化。

---

## 1. 问题（引用 step-76，不重复事实）

step-76 暴露的 bug 类，同时违反两个不变量：

- **INV-A（scope，不越界）**：gate 只能对自己声明范围内的问题产出 issue。
- **INV-B（capability，target 能修）**：gate 产出的 `issue.target` 必须是一个声明了能修这类问题的 skill。

step-76 的 5c3b24：review 越界查 requirement math（违反 INV-A）+ `target=requirement` 但 requirement 未声明能修 math-equiv（违反 INV-B）+ 多 target 字典序优先级让 `redo_generator` 赢（下游放大）。

**现状根因**：3 个 gate 的 `issue_target_mapping` 是各自 Python dict 硬编码（`design_substages.py:1136/1548/1871`），target 体系各搞各的（6 个不同 target，仅 `human` 共享），**无声明式契约、无加载期 join、运行期不校验 scope**。越界/target 错全靠 LLM 自觉，必然复发。

---

## 2. 选项与决策

### 2.1 用户原始提案（5 组件）

1. 检查项 + target 存 skill md 文件
2. review 读它定 loopback 目标
3. 另一 md：自己能修的问题（capability 清单）
4. Python 强校验 issue vs target capability；不一致 warn + 带着走
5. 多问题全交最靠前 agent，直到全解决或前置无法解决

### 2.2 逐组件评估 + 修正

| 组件 | 评估 | 修正 |
|---|---|---|
| ① 检查项+target 声明 | 对，但定位要改：若只当"路由表"= 给越界发通行证 | 定位为 **scope 契约**：每项检查声明 `self_fixable`；`self_fixable=false ⇒ 必须同时声明 loopback_target+feedback_channel`，否则**加载期拒绝**（§1.3） |
| ② review 读它定目标 | 对 | 路由以**声明 target 为权威**，gate 自标 target 仅 advisory |
| ③ capability md | **与①冗余必漂移**（双源） | **单源 + join**：producer 声明 capabilities，①的 loopback_target 引用 capability ID，加载期 join |
| ④ 强校验 + warn&carry | 加载期部分完全对；运行期要**区分两种 mismatch** | `code` 在范围内 target 标错→以声明为准+warn；`code` **完全越界→drop+warn，不 carry**（没人能修，carry=毒性前逃） |
| ⑤ 多问题全交最靠前 | 直觉对（先修最上游避免下游白修），不用新造控制流 | 每 issue 按自己 target 路由（修字典序 bug）；多 target 选最上游 fixable，其余进 `design_known_issues`；收敛复用 max_corrective/escalation/stagnation |

### 2.3 选定方案：gate scope & ownership contract

声明式契约（gate 的 scope + producer 的 capability）+ 加载期 join（INV-B 构造保证）+ 运行期 scope 校验（INV-A）+ feedback-selfcheck 泛化（channel 有真消费者）。

### 2.4 否决的替代（记录取舍）

- **纯控制流修字典序优先级**（step-76 次因兜底）：治标，不防越界复发，每来一个新越界都要再补丁。违反 §1.2 可扩展。
- **扩 halt 到 evidenced infeasible**（step-76 初判 Route 2）：已否决——GD-R1 可修（requirement re-derive golden），evidenced infeasible ≠ unfixable。
- **只做 step-76 主修-1**（requirement 加 golden 自检）：单点修，不防其他 gate/其他越界。本步把它纳入 §3.7 作为 capability 声明的实例。
- **双 md 声明**（检查项 md + capability md）：双源必漂移，单源 + join 取代。
- **md 声明**：SchemaLoader 只吃 JSON，md 要新造 parser；仓第一性原理"schema travels with skill"是 JSON 形态。用 JSON 复用 SchemaLoader。

---

## 3. 设计（选定方案）

### 3.1 两个不变量（本步的目标不变式）

- **INV-A**：gate 发出的 `issue.code ∈ 本 gate 声明的 checks`（运行期校验）。
- **INV-B**：gate 声明的每个 `loopback_target` 引用的 capability 必须在某 producer 的 `capabilities` 里存在（加载期 join，构造保证）。

### 3.2 声明式契约结构（复用 SchemaLoader + agent manifest）

- **gate skill** 在自己目录加声明 JSON（复用 `SchemaLoader` 路径约定 `.claude/skills/<skill>/schema/`）：
  ```
  checks: [
    { code, description, self_fixable: bool,
      loopback_target?: <capability_id>,   # self_fixable=false 时必有
      feedback_channel?: <tail_call_skill> } # self_fixable=false 时必有
  ]
  ```
  约束：`self_fixable=false ⇒ loopback_target + feedback_channel 都必填`，加载期 reject 否则（§1.3）。
- **producer skill** 声明 `capabilities: [{id, description}]`，放 **agent manifest frontmatter**（复用机制 B，`capabilities/skill/loader.py:162`）。

### 3.3 加载期校验（§1.3，挂 `dispatcher.py:816` startup 链）

- **join**：每个 gate.checks[].loopback_target 引用的 capability 必须在某 producer.capabilities 存在 → **INV-B 构造保证**。
- **self_fixable=false 完备性**：必须有 loopback_target + feedback_channel。
- **capability ID 全局唯一**。
- 复用 `validate_skill_map()` / `validate_manifest()` 的 fail-fast 风格，errors 接 `dispatcher.py:816` 已有的汇总。

### 3.4 运行期校验（落 `_DesignGate.resolve_condition` / `transition`）

- 发出的 `issue.code ∈ 本 gate 声明 checks`（**INV-A**）：
  - `code` 在范围、target 标错 → 以**声明 target 为准** + warn。
  - `code` 完全越界（不在声明范围）→ **drop 该 issue + 醒目 warn**（要求更新声明/skill 内容），**不 carry**。
- `target=human` 保留（gate 范围内真需人的）。

### 3.5 多 issue 路由（修字典序优先级 bug）

- **每 issue 按自己 loopback_target 路由**（不再 `_route_from_issues` 字典序合并出一个 condition）。
- 一次 transition 只走一个 condition → 多 target 时**选最上游 fixable target** 路由，其余 issue 进 `design_known_issues`（已有机制，不丢；下游 review 重跑自然再 surface）。
- 收敛复用现有 `max_corrective` / `max_escalations` / stagnation（`error_signature same>=2`），**不新造收敛逻辑**。

### 3.6 feedback-selfcheck 泛化（配套，本次一起做）

- **现状**：`ascendc-op-design-feedback-selfcheck` 是 tiling 专用（硬编码读 `validation_report`/`anchor_report`、过滤 `target=tiling`、修 tiling 段产物），唯一消费者是 4 个 tiling skill 的 tail_call。
- **泛化**：把核心模式提炼为通用 selfcheck——**读全历史轮 issue + 逐条 `acceptance` 回验（不臆造判据）+ 能修就地 Edit + 修不了标 unresolved + 复用 stagnation halt**。
- 挂到**所有 `self_fixable=false` producer** 的 tail_call（经 `orchestration-config.json` 的 `skills.tail_calls` + `STAGE_TAIL_CALL_MAP`）。
- **必要性**：声明的 `feedback_channel` 必须有真消费者，否则 = 虚假闭环（§2.9 禁止"只发现问题无法解决"）。这是 INV-B 落地的配套闭环。

### 3.7 step-76 主修-1 纳入（推荐，作为 capability 声明的首个实例）

- requirement skill 声明 capability `math-equiv-golden`（能修"math_formula 与 golden 数值等价"类问题）+ 加载期要求其 selfcheck 存在。
- general-design-review 的 checks 声明里**不含** math-equiv 检查（它归 requirement）→ review 越界查 math 在 INV-A 运行期校验时直接 drop。
- 这样 step-76 的"源头自检"从单点修升级为声明式强制，且是本框架的首个端到端实例。

---

## 4. 复用现有机器（不新造）

| 机器 | 锚点 | 复用方式 |
|---|---|---|
| SchemaLoader（JSON 声明→加载+校验） | `adapters/schema/loader.py:74` | gate scope 声明走它，零新 loader |
| issue `acceptance` 字段加载期强制 | `domain/artifact.py:63,101-113` | feedback-selfcheck 的回验判据已契约化 |
| `design_known_issues` 前逃 | `state.py:209` + `_set_known_issues` | 多 issue 路由的"带着不丢" |
| stagnation halt | `issue_render.py:103` + `graph_executor.py:569` | 收敛/止损，不新造 |
| tail_calls 机制 | `orchestration-config.json` + `skill_config.py:47` + `STAGE_TAIL_CALL_MAP` | feedback-selfcheck 挂载 |
| 加载期校验挂点 | `dispatcher.py:816` + `validate_skill_map`/`validate_manifest` | INV-B join 校验接入 |
| agent manifest frontmatter | `capabilities/skill/loader.py:162` | producer capabilities 声明 |

---

## 5. 全局落地范围（经核实）

- **3 个 gate + `_DesignGate` 基类**：`GeneralDesignReviewStage` / `AnchorConsistencyStage` / `ValidateStage`（`design_substages.py`）。公共路由逻辑（`_route_from_issues` / `resolve_condition` / `_set_known_issues`）一次改，三 gate 受益。
- **N 个 producer 声明 capabilities**：generator / tiling-* / requirement 等（agent manifest）。
- **不受影响**：codegen / precision_debug / perf / requirement 侧无 issue-routing gate（perf `resolve_condition` 走 state 字段、requirement 消费 issue 做反馈但不路由）。但 producer 仍需补 capabilities 声明。

---

## 6. 风险与边界（诚实）

- **不能解决"LLM 把已声明的检查判错"**：声明保证"查该查的、路由到能修的"，不保证"查得对"。review 声明了查梯度公式但判错 = LLM 能力问题，非控制流。
- **主要配套成本在 feedback-selfcheck 泛化**：声明/校验部分复用现成很轻；泛化 selfcheck 是实打实的工作量（去 tiling 硬编码、参数化报告源/过滤/修复对象）。
- **声明漂移**：靠单源 + 加载期 join 缓解（join 不过 = load fail），不能完全消除人写声明时的笔误，但加载期拦得住不一致。
- **运行期 drop 越界 issue 的副作用**：drop 会让该轮 review 少报一个 issue。靠醒目 warn 兜（要求更新声明或修 skill 内容），不静默。

---

## 7. 决策锁定（用户已拍板）

1. **JSON 复用 SchemaLoader**（非 md 新造 parser）。
2. **越界 issue → drop + warn**（非 warn + carry，防毒性前逃）。
3. **feedback-selfcheck 泛化本次一起做**（channel 必有真消费者）。

---

## 8. 锚点（L4 实施参考）

- **gate 基类与子类**：`_DesignGate`（`design_substages.py:890`）、`issue_target_mapping`（`:910`）、`resolve_condition`（`:929`）、`_route_from_issues`（`:39`）、`_resolve_with_redirect`（`:55`）、`_set_known_issues`（`:940`）；三子类 mapping（`:1136/1548/1871`）。
- **声明加载**：`SchemaLoader.load_spec_from_skill`/`load_contract_from_skill`（`adapters/schema/loader.py:83/94`）、`ArtifactSpec`（`domain/artifact.py`）、`issue_required_keys`（`:101-113`）。
- **加载期校验挂点**：`dispatcher.py:816`、`validate_skill_map`（`skill_config.py:117`）、`validate_manifest`（`capabilities/skill/loader.py:229`）、`ArtifactSpec.validate_payload`（`domain/artifact.py:73`）。
- **feedback-selfcheck**：`.claude/skills/ascendc-op-design-feedback-selfcheck/SKILL.md` + `schema/selfcheck_report.json`；tail_calls `orchestration-config.json` + `skill_config.py:47`；现有消费者 `design_substages.py:1957/2066`。
- **agent manifest**：`capabilities/skill/loader.py:162`（`load_agent_manifest`）、`AgentManifest`（`domain/skill.py:20`）。
- **多 issue / 收敛**：`design_known_issues`（`state.py:209`）、stagnation `issue_fingerprint`（`issue_render.py:103`）+ `graph_executor.py:569`、`max_corrective`/`max_escalations`（`node.py` + `orchestration-config.json`）。

---

## 9. 与既有原则 / step 的关系

- **§2.9（含第 5 条"门不越界查上游"，本次新加）的构造性落地**：从"原则推导"升级为"加载期 + 运行期强制"。铁证（review skill schema 曾允许 target=requirement）不再可能。
- **step-60 halt 边界不动**：本步不扩 halt；INV-A 越界 drop、INV-B join fail 是"加载期/运行期校验"，不是 halt。
- **step-76 收口**：本步覆盖 step-76 主修（§3.7 requirement 自检为首例）+ 把次因（路由字典序）结构性修掉（§3.5）。step-76 的 L4 实施并进本步。
