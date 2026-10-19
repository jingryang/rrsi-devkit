# P47 — 详设反馈消费确定性闭环（skill 内自检）— 方案分析（第三层）

> 状态：方案已定（§7 已拍板），待实施（用户指示先不动代码）
> 层级：**第三层 / 方案分析**。选项 + 取舍 + 拍板理由。
> 覆盖问题：P47（详设反馈消费确定性闭环）+ 闭环 P45 后置的 (b)(c) + 闭环 bug-fix agent 悬空（P45 讨论方向）。
> 输入：P45 第一刀+(a) 落地后的真实残余 + 用户认知校正（issue 判据必须 LLM 可执行）。
> **承接**：17/18（P24-P27）→ 23/24（P44/P45）→ 本 L3。P47 是详设反馈通路的**第三层闭环**：17/18 修产出端越界、23/24 修产出端 schema 分层 + 消费端 prompt bug，P47 修消费端「确定性消费」。
> 约定：按符号定位（不写 file:line）；外部依赖（CANN / 知识库文档 / chip spec）只读。

---

## 1. 定位：P47 是 P45 闭环的第三层

详设反馈通路三层：

- **第一层（产出端约束，17/18）**：anchor 权限 + SKILL + max_iter，防产出端越权。
- **第二层（产出端 schema + 消费端 prompt，23/24）**：P44 issue `verdict`/`remediation` 分层 + consistency 证据源约束；P45 第一刀修消费端 prompt 丢反馈段 bug + (a) issue 指纹激活停滞检测。
- **第三层（消费端确定性消费，本 L3）**：P45 第一刀+(a) 后，反馈进了 prompt、框架能检测停滞，但「反馈是否被生成 skill 真消费」仍是 LLM 概率行为——P47 把它升级为 skill 内确定性自检。

P45 落地后仍未闭环的：
- (b) `must_hold` 谓词、(c) 自动升级——之前后置。
- bug-fix agent 方向（P45 讨论时用户提的候选）——之前悬空（L1「待讨论定案」）。

P47 一并处理：(b)(c) 重新激活但**改落点**（框架状态机 → skill 内自检，更符合 §2.7）；bug-fix agent 被 skill 内自检替代（更轻，[[avoid-overdesign-prefer-reuse]]）。

---

## 2. 现状（P45 第一刀+(a) 落地后的真实残余）

### 2.1 反馈进了 prompt，但消费是概率性的

- P45 第一刀（`_feedback_section`）已让 `## 上次反馈` 段进 tiling prompt（UT `TestFeedbackSection` 守护渲染）。
- 但「LLM 是否读了、照做了」无任何实证：`test_design_tui_selfclosure` 是 happy path（空 `blocking_issues`）+ 直接 spawn 绕过 Stage，根本没触发 `_feedback_section`，**不构成 P45 消费证据**（前序会话曾误用它作证据，已纠正）。
- `_feedback_section` 只列 issue 判定，无「你必须解决」的强制语；P44-C 把 `remediation` 标「建议非强制」防越界，**同时削弱了反馈行动力**——防越界 vs 促修复的张力。

### 2.2 反馈无历史、无消解判据

- validate 的 `blocking_status.json` 每轮 transition 整份覆盖（P45 L1 早已记录），上一轮 issue 丢失 → 无法做多轮累积自检（用户 step 4 的「读多轮 schema 确认无回归」无地基）。
- issue schema（P44-C）有 `verdict`（事实）+ `remediation`（建议），但**无消解判据**（怎样算解决）→ 即便 skill 想自检，也缺「判什么」。

### 2.3 框架层停滞检测已通（P45-(a)），但是被动兜底

- (a) issue 指纹激活 `same>=2` 停滞 halt——这是「消费失败 N 轮后停」，是被动兜底，不是「主动确定性消费」。
- P47 补的是主动消费链路，让停滞检测尽量不触发。

---

## 3. 认知校正（用户主导，本 L3 的理论基石）

### 3.1 错误的二分：机可判 vs 语义

前序讨论一度把 issue 分「机可判（结构化，如 bf16）vs 语义（如 kernel 缺伪码）」，据此判「skill 自检能覆盖前者、覆盖不了后者」。

**这个二分错了**。错在把 step 4 的「自检问题是否解决」误当成「框架写代码机械判定（grep 产物）」——但 step 4 是 **skill 内 LLM 自检**，自检主体是 LLM 不是框架代码。LLM 的判定能力远超 grep，只要 issue 描述清晰，「kernel 是否补了伪码」LLM 完全能自检。

### 3.2 正确的原则：issue 是给 LLM 的，判据必须 LLM 可执行

> issue 是给 LLM 看的。它的判据必须写成 LLM 能理解、能据此判断「是否已解决」的形式。如果一条 issue 连 LLM 都无法据此自检，那不是「这类 issue 特殊」，而是这条 issue 的描述不严谨——应该回去修这条判据，而不是在消费端为它造一套特殊机制。

这是 §1.3 的同构精神（问题在产出期就该清晰，不推迟到消费期才暴露「没法判」）。**不可判不是 issue 的固有属性，是 issue 的质量缺陷** → 修产出端，不在消费端打补丁。

### 3.3 判据执行的边界（完善，非反驳）

判据「执行」有两种：
- **静态读产物即可判**（结构/字段/dtype/描述完整性）——详设 issue 几乎全是这类。
- **需运行才能判**（精度/性能/编译通过）——主要在 verify/codegen 阶段。

P47 范围是详设反馈通路（validate/anchor ↔ tiling），issue 几乎全静态，LLM 自检完全覆盖。需运行的边界属另一阶段，不影响本方案。

---

## 4. 方案（用户四步 + 认知校正修正）

### step 1 — issue 迭代版本化（地基）

validate/anchor 产出的 `blocking_status` 类 schema：
- 加 `iteration` 字段标时序（「第 N 轮发现」），防「第1轮发现已修」与「第N轮新发现」混淆。
- 按迭代累积不覆盖（文件内 `history[]` 或分迭代文件），让多轮自检有历史可读。

**为什么是地基**：step 4 的「读多轮 schema 确认无回归」依赖全部历史 issue 可得；现状每轮覆盖，历史丢失。

### step 2 — issue schema 补「消解判据」维度（认知校正的落点）

P44-C 的 `verdict`/`remediation` 之外，补第三维度 **消解判据**（`acceptance`：怎样算解决，给 skill 自检用的可执行标准）。
- 形态：自然语言可执行描述（给 LLM 看，非机械谓词）。
- 产出端 SKILL（validate/anchor）强制每条 issue 带消解判据，且判据须 LLM 可执行——判据写不出/写不清 = issue 本身不成立，不该产出。

**这是 §3.2 原则的直接落地**：把「判据质量」变成产出期的硬约束，而非消费端的兜底。

### step 3 — loopback 写 prompt（保留，降级为辅助）

= P45 第一刀 `_feedback_section`。保留，**不指望它驱动消费**——prompt 注入只当辅助提示，主修复靠 step 4。现状已满足，无需改。

### step 4 — 生成 skill 末尾 LLM 自检（核心）

每个生成 skill（`tiling-buffer-kernel` / `tiling-precision-perf` 等）末尾加一步：
- 读当前轮 + 历史全部轮的 issue（含消解判据）。
- 读自己的产物。
- LLM 自检每条 issue 的消解判据是否满足。
  - 未消解 → skill 内部修复（增量 Edit，呼应基类「重试基于已有产物」）。
  - 修不了（超 skill 能力 / 判据仍不满足）→ 标 unresolved，halt/转人工（复用既有 halt 出口，不新造状态机）。
- 多轮累积：不只验当前 outstanding，回验历史全部轮 issue 无回归。

**这是反馈消费从「LLM 概率行为」→「skill 流程强制步骤 + LLM 自检」的升级**。符合 §2.7（消费反馈是生成 skill 核心职责，该在 skill 里）。

### python 侧日志（可诊断，顺带）

stage python 侧（`design_substages` transition）读 `blocking_status` 打印 issue 摘要 + 迭代号（扩展现有 `_lint_issues`）。§1.2 可诊断性。

---

## 5. 取舍：为什么 skill 内自检 > bug-fix agent > 框架状态机

| 方案 | 落点 | 评价 |
|---|---|---|
| **skill 内自检（本方案）** | 生成 skill 末尾加自检步骤 | ✅ 选。反馈消费是生成 skill 核心职责（§2.7），skill 自读产物自检最内聚；复用既有 halt 出口，零新状态机（[[avoid-overdesign-prefer-reuse]]） |
| bug-fix agent（P45 讨论候选） | 新建独立 agent 扛修复 | ❌ 否决。新增 agent 类型 + 重新划分 stage 职责（生成 stage 不扛修复），架构级改动成本高；与 skill 内自检职责重叠但更重。skill 内自检已覆盖其价值 |
| 框架状态机（P45 原 (b)(c) 落点） | 框架层加 `must_hold` 谓词 + 自动升级 | ❌ 否决（原落点）。框架膨胀、与具体产物强耦合（谓词要懂 tiling JSON 结构）；改落点到 skill 内更符合 §2.7 |

---

## 6. 依赖与时序

1. **step 1**（迭代版本化）——地基，没它 step 4 无历史可读。
2. **step 2**（消解判据维度 + 产出端 SKILL 强制）——step 4 可靠性前提（无判据 = 自检无标）。
3. **step 4**（skill 末尾自检 + halt 降级）——核心。
4. step 3（现状已满足）、python 日志——顺手。

**关键时序**：step 2 必须先于 step 4（判据先于自检）；step 1 必须先于 step 4（历史先于累积自检）。

---

## 7. 拍板结论（2026-07-07，用户认可倾向）

1. **自检 skill 落点** → **抽共享自检 skill + 各生成 skill 末尾调用**（跨实例通用部分共享，符合 §2.7）。
2. **消解判据 schema 形态** → **自然语言可执行描述**（issue 本就是给 LLM 的，§3.2）。
3. **多轮累积粒度** → **全量回验**（防「修新坏旧」，用户 step 4 明确）。
4. **修不了的降级** → **halt 复用既有出口**（最小，不新造状态机）。

实施配方见 L4 `26-feedback-consumption-closure-impl.md`。

---

## 8. 与现有工作的关系

- **承接 P44/P45（23/24）**：P44 `verdict`/`remediation` 分层 + P45 第一刀+(a) 是 P47 的前置（schema 分层 + prompt 注入 + 停滞检测已通）；P47 补第三维度（消解判据）+ 确定性消费。
- **闭环 P45 后置的 (b)(c)**：原框架状态机落点 → 改 skill 内自检（§5 取舍）。
- **闭环 bug-fix agent 悬空**（P45 L1 讨论方向）：选 skill 内自检，否决独立 agent。
- **与 P41/P42（session 内自检）同源**：P41/P42 是「session 内一次合格的自检保证」，P47 是「跨 stage 反馈被消费的自检保证」——同一「机械自检」主题的两半，P47 的 skill 末尾自检是 P42 框架层自检在 skill 内的对偶。
- **不动 codegen/verify**：P47 范围限详设反馈通路（validate/anchor ↔ tiling）；「需运行才能判」的 issue（精度/性能/编译）属 verify/codegen，不在本方案。

---

状态：**方案已定（§7 已拍板），待实施**。用户指示先不动代码。L4 已立（`26-feedback-consumption-closure-impl.md`），待授权实施。
