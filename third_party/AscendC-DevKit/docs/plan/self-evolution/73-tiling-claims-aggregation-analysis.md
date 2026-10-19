# 73 — tiling 段聚合接力 verifiable_claims 收口（L3 方案分析）

> 工作线：self-evolution / design 详设 loopback 闭环
> 性质：**L3 方案分析** —— 有哪些选项、选哪个、为什么。**已拍板（方案 S）**，本文件冻结。
> 对应 L1：[[P100]]（`06-problems.md`）。前序：[[P85]] / 方案62（产出端 schema `required_keys` 收口 verifiable_claims）、[[P37]]（段聚合 `payload.get(segment_key)` 单键写法定型）。
> 对应 L4：`73-tiling-claims-aggregation-impl.md`。
>
> 方案命名（避免字母复用混淆）：**方案 N**（Nest-only，只挪 verifiable_claims）/ **方案 S**（Structural，选定）/ **方案 R**（Relay 变换）/ **方案 G**（Gate-rewrite）。
>
> 字段分类原则（T1 修正后）：**gate-relevant 设计内容**进 segment；**过程元数据/纯簿记**留顶层白名单。判据：门是否消费该字段做对质/校验。

## 1. 问题再陈述

三处对 `verifiable_claims` 的**位置**假设不一致，构成构造性一致性断裂（§2.9）：

| 层 | 期望位置 | 证据 |
|---|---|---|
| 产出端 schema（per-stage 文件） | segment 对象的**顶层兄弟** | 三段 `required_keys=['template','<segment>','verifiable_claims']`（方案62 加） |
| 聚合层（`design_substages.py:2050`） | 只搬 segment **内层对象** | `tmpl_entry[segment_key]=payload.get(segment_key)` → 丢顶层兄弟 |
| 消费端门（anchor / validate GV9-a） | 聚合文件的**三段产物各含** verifiable_claims | anchor SKILL.md:34/57/67；validate SKILL.md:109/175/230 |

producer 已按 schema 正确产出（带 `verification=api_checked`+`source_pointer`），但 claims 在聚合接力时被结构性丢弃 → 门永远看不到 → AC0 死循环（run `20260724-045259-898837` 实证）。

## 2. 关键事实（影响选项）

- **schema 是开放的**：`ArtifactSpec.validate_payload`（`domain/artifact.py:64-94`）**只检 `required_keys` 是否存在，不拒绝未知键**。三段 schema 也只有 `required_keys`+`example`，无 `allowed_keys`。→ schema 从未阻止过"加一个顶层兄弟字段"，这是孤儿能出现的根因之一。
- **无 Python 读 verifiable_claims**：工程层不解析 `claim_type`/`verification`/`evidence`（`60-design-escape-hatch-impl.md:80` grep 实证）。消费方纯 LLM gate skill → 改形状不触发 Python 解析路径。
- **门已期望"按段"**：anchor / validate 都读"三段产物的 verifiable_claims"——即门要的是 **per-segment claims**。
- **decisions 另有通路**：`_capture_decision_log(state, raw)`（`design_substages.py:2051`）从完整 raw 另存进 `state.decision_logs`，不依赖聚合。
- **per-stage 实际顶层字段**（artifacts 实证）：三段都有 `step/template/status/<segment>/decisions/key_parameters/self_check_summary/verifiable_claims/external_verification`；buffer_kernel 多一个 `kernel_structure`。其中 schema 只声明了 `{template,<segment>,verifiable_claims}` 为 required，其余是 agent 产、未声明。

## 3. 选项

### 方案 S（选定，结构性）：gate-relevant 设计内容进 segment + schema 闭合

两部分，缺一不可：

**（a）内容重构**：把 **gate-relevant 设计内容**顶层兄弟移进 segment 对象——
- `verifiable_claims`（anchor AC0/1/2 的**对质输入**，门消费）；
- `key_parameters`（GV4 类数值推导，门可能核）；
- `kernel_structure`（buffer_kernel，GV8-A 核函数清单）。

`self_check_summary` **留顶层**：它是 producer 自检结果（结构一致性快照），**唯一消费者是 feedback-selfcheck**（producer 产出后末尾自调、从**源文件**读、就地全量回验，不经聚合）；对质门 anchor/validate 0 命中不读。按 `checkpoint_convention.md:130-133` 作用域隔离（selfcheck 只判结构、不碰查证、**不提升 verification**）→ **非 load-bearing**，无需流向门，聚合丢弃无害（详 §8）。

顶层允许集 = 纯簿记 `{template, step, status, decisions(→decision_logs), external_verification, self_check_summary}` + `<segment>` 本身。

**（b）schema 闭合**：给 `ArtifactSpec` 加 `allowed_top_level_keys`，`validate_payload` 增"拒绝未知顶层键"分支（扩展既有早拒机制，§1.3 精神）。三段 schema 各设上述允许集。

聚合 `:2050` **零逻辑改**：设计内容已在 segment 内层，`payload.get(segment_key)` 天然带上；门已期望段内 → 门 skill 零改。

> 字段分类判据（固化进 §6/UT-A 白名单）：**门是否消费该字段做对质/校验**。是 → 进 segment（须流向门）；否（过程元数据/纯簿记）→ 留顶层白名单（声明"非 gate-visible"，不流向亦无害）。

### 方案 N（否决，Nest-only）：只挪 verifiable_claims

只把 verifiable_claims 嵌进 segment，其余顶层兄弟不动、schema 不闭合。
- 否决理由：开放 schema 下，未来谁加个新顶层兄弟（如 `safety_assertions`）→ :2050 照丢 → 同型复发。只修了今天这一个字段，没消除"孤儿兄弟"这个**类别**。

### 方案 R（否决，Relay）：聚合层 sibling→segment 变换

`:2050` 把顶层兄弟并进 segment。transport 层为补 contract 失配而 reshape（层级 smell），两形不一致，每字段都要配 transform。否决。

### 方案 G（否决，Gate-rewrite）：聚合收集到 T1 级 + 重写门

门 skill 大面积改写 + 三段 claims 合并丢段归属。最差。否决。

## 4. 为什么方案 S 能"结构性消除"复发（核心论证）

复发面 = "某 gate 要读的字段，作为顶层兄弟被 :2050 丢掉"。方案 S 从两条路径同时堵死：

**路径 1（gate-relevant 设计内容不再在顶层）**：claims/key_params/kernel_structure 进 segment → 聚合天然带过 → 门从段内读到。门要见的字段**构造性地**随 segment 流转，无需 relay、无需 re-check（§2.9 构造性保证）。

**路径 2（顶层不能再加 gate-relevant 设计内容）**：schema 闭合（`allowed_top_level_keys` + 拒未知键）→ 未来任何新顶层字段若不在白名单，`validate_payload` 在**段 transition 读产物时立即拒**（schema_violation → 重 spawn），根本到不了 :2050/下游门。孤儿兄弟在 **producer 边界**就被挡（§1.3 精神），不是下游门 discover+regenerate（§2.9 禁止的形态）。

**白名单盲区基本消失**：闭合后顶层只剩 `{template, step, status, decisions, external_verification, self_check_summary}`——纯标识符/状态/有 alternate 通路（decisions→decision_logs）/过程元数据（self_check_summary，对质原则门不读）。门不会对它们做设计级对质 → 即便不流向门，也不构成 AC0 型"缺证据→死循环"。方案 N/R 的"白名单字段变 gate-visible"盲区，因白名单全是"按定义非 gate-visible"的字段而**实际消除**。

> 结合论：方案层（方案 S 两部分）让不变式对今天和未来的 gate-relevant 字段都成立；UT（见 L4 UT-A/UT-B）做纵深兜底，防"有人改回开放 schema 或 :2050 回归"。dev-time 守护 ≠ runtime discover+regenerate，合法（§2.9）。

## 5. 四把尺子（§1.2）

| 尺 | 方案 S（内容重构+闭合） | 方案 N（只挪 claims） | 方案 R（Relay） |
|---|---|---|---|
| 可维护 | ✅ 单一形状（gate-relevant 在段内），闭合 schema 是硬契约，字段分类有判据 | ⚠ 仅 claims 进段，其余顶层混乱 | ⚠ 两形不一致 |
| 可扩展 | ✅ 加 gate-relevant 字段→进 segment 自动流转；加顶层字段→闭合 schema 拒绝（强制对） | ⚠ 新顶层孤儿会复发 | ⚠ 每字段配 transform |
| 可诊断 | ✅ 闭合 schema 在 producer 边界即报（§1.3 精神） | ⚠ 仍靠下游门发现 | ✅ |
| 架构合理 | ✅ 修在 contract/schema 层（字段位置产权层），transport 不 reshape | ⚠ 半截 | ⚠ transport 补 contract |

方案 S 四尺全优。代价：改 ArtifactSpec（框架 1 类）+ 3 schema（挪字段+设 allowed）+ 3 skill 引导 + producer 行为变更 + heavy_llm ST。

## 6. 反驳与边界

- **"改 ArtifactSpec 影响全框架 schema"**：`allowed_top_level_keys` 默认 None（不设=开放，兼容现状），仅三段 tiling schema 显式设。其它 schema 不受影响、可日后按需 opt-in。非一刀切强制全闭合。
- **"挪 key_parameters/kernel_structure 动静大"**：它们本就是 agent 产、未声明、未正名的"流浪字段"；挪进 segment 是给它们正名（归属该段设计）。`self_check_summary` **不挪**（唯一消费者 feedback-selfcheck 从**源文件**读、不经聚合；且非 load-bearing——详 §8 + `checkpoint_convention.md:130-133`）。exact inventory 落地时核 artifacts。
- **"producer 行为变更要 heavy_llm 复核"**：真。schema 闭合 + 内容重构是确定性引导，heavy_llm ST（方案62 已建）复核 producer 真产在段内、闭合 schema 不误拒。
- **[[P110]]**：随方案 S 消解——key_parameters 进 segment（流向门）；self_check_summary 留顶层白名单（对质原则门不读，不流向亦无害）；闭合 schema 立"顶层只许簿记/过程元数据"规则。

## 7. 决策（已拍板）

**选定方案 S（结构性）**。冻结，出 L4。备选 N/R/G 仅作记录。后续若要"门输入契约化"做极致零盲区，已因白名单全是"按定义非 gate-visible"字段而**优先级降为低**（follow-up 可不做）。

## 8. §2.9 合规论证（问题类型 → 闭合层级）

方案 S + 既有的 self_check / feedback-selfcheck / anchor 设计，把不同性质的问题路由到各自该闭合的层级——这正是 §2.9「问题尽量在 agent 内自闭环」的本意（**能 in-agent 的不外推**，而非"一切都在 agent 内"）：

| 问题类型 | 闭合层级 | 机制 | §2.9 判定 |
|---|---|---|---|
| 结构/逻辑一致性（公式↔伪代码、Buffer↔Kernel、对齐、UB、字段命名） | **agent 内** | `self_check_summary` + **feedback-selfcheck**（producer 末尾自调、工作目录内全量回验+就地修） | ✅ §2.9 点名的合法 in-agent 闭合（②反馈消费渠道） |
| 硬件/API 查证（gather 可用性、dtype 支持） | **外部对质门** | `verifiable_claims` + anchor AC0/1/2（独立查硬件文档） | ✅ §2.9 合法例外（①）：**不信自评**，producer 自查硬件能力不可信，必须独立源核对，无法 in-agent 自闭 |
| 契约/schema 形状（顶层键合规） | **框架** | `validate_payload`（确定性，§1.3） | ✅ 见下"为何归框架" |

**方案 S (a) 内容重构 = §2.9 修复性**：P100 本质是病态 discover+regenerate（anchor 反复"发现" claims 缺失 → 回退 producer → producer 本就产对 → 聚合再丢 → 再发现，§2.9 禁止形态）。(a) 让 claims 构造性到场 → 消除该病态环；门的真活（AC1/AC2 查 claims 内容）保留为合法对质。

**方案 S (b) schema 闭合 = §2.9 偏好的构造性保证**：§2.9 原文「**构造性保证优先于检查门**」。闭合让"孤儿顶层字段"在源头（producer 边界）就产生不了，而非放任流向下游再由门"发现"（那才是 discover+regenerate）。**用构造性预防替代了潜在检查门**——比"加门去查"更 §2.9。

**为何 schema 校验归框架、非 §2.9 违反**：
1. 契约/语法校验权威天然在框架（§1.3，如编译器之于语法）；`validate_payload` 本就在 producer **自己边界**上（检 required_keys 已存在），重 spawn 的也是它自己（非下游 agent）。
2. **确定性 > LLM 自查**：schema 形状确定性可判，框架 100% 可靠；让 LLM agent 自查 schema 合规反而可能漏。§2.9 要 in-agent 自闭的是**语义/质量**问题；**契约形状是另一类**（§1.3）。
3. 方案 S 是**双层**：primary = agent 自合规（`to_prompt_block` 把 allowed 集渲染进 prompt，producer 知契约、自守）；closure = §1.3 兜底（agent 漏了才拒，且拒带精确错讯"unexpected key X, allowed=[...]"，非碰运气重跑）。**主路径在 agent 内**，框架只 last-resort——即 §1.2"正确改动主修复 + 宽容兜底"。

**self_check_summary 非承重（T1 实证依据）**：唯一消费者 feedback-selfcheck 从**源文件**读（不经聚合 → 聚合丢弃无害）；`checkpoint_convention.md:130-133` 把它限在"结构一致性"、**禁止提升 verification** → 系统不依赖它正确，正确性由 feedback-selfcheck 全量回验 + anchor 对质两套独立机制保证（不信自评的双层落地）。

**结论**：符合 §2.9，且是**构造性预防 + 修掉一个 §2.9 违反**（P100 病态环）。可选的"更纯"增强：把"顶层键 ⊆ allowed"显式纳入 producer self_check 范围（in-agent 自发现自修复）——但边际（框架已确定性兜住，LLM 自查反而更弱），不增强亦合规。
