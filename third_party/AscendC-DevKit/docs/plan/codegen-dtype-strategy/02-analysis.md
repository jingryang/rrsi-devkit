# codegen/详设 dtype 策略缺陷 — L3 方案分析（2026-08-06）

> 层级：**L3 / 方案分析**。回答「有哪些选项、选了哪个、为什么」。
> 问题事实见 `01-problems.md`（L1，产权：证据/根因）。本文只做选项取舍 + 决策。
> **本轮按用户要求只落文档、不改 skill/agent/red-line 文件**（其他 session 正在改 `.claude/`，避冲突）；
> 落地编辑（Layer 1-4）记为 Phase 2，待并发 session 收口后执行（见末节）。

## 分析原则

四把尺子（§1.2）：**可维护**（维持/澄清既有不变式）/ **可扩展**（同类新情况自动归位）/ **可诊断**（异常留可观测信号）/ **架构合理**（落在职责正确的层）。
硬约束：§1.12（按算子**类别/行为**判，不认算子名——举例用结构特征描述）、§2.9（producer 自检 > 跨段门）、§2.1（skill 即插即用、改的是引导文本）。

## 决策总览（先看这个）

根因是**详设 skills 缺结构性 dtype 规则**（P1-P3），codegen/review/知识库是放大器与缺兜底（P4-P7）。采用**全链引导文本**方案（用户拍板）：

| 问题 | 决策 | 落点 |
|---|---|---|
| P1 precision-perf 误导+无验证 | **R1 加非计算算子 carve-out + Step2 加往返损失验证 + 特殊值保真 + 一致性加策略合理性** | `ascendc-op-tiling-precision-perf` |
| P2 LD1 二元 | **LD1 改派生决策（算子是否计算型 + 是否 bit-exact → 派生中间类型策略）** | `ascendc-op-design-template-division` |
| P3 workspace sizeof(float) | **示例 dtype-parametric + R7 加 dtype 一致性约束** | `ascendc-op-tiling-buffer-kernel` + schema |
| P4 维4 漏 UB 侧 cast | **扩维4 禁 UB 侧标量 cast 漏斗 + Step4 加 native dtype 默认** | `ascendc-op-dev-coding` |
| P5 coder 放任 | **改「Use fp16 for compute」→ 「IO native dtype 默认 + 非算术算子禁中转」** | `ascendc-coder.md:28` |
| P6 red-line 缺项 | **加 TopN「Lossy dtype intermediate / scalar-cast funnel」** | `ascendc-code-review` |
| P7 A1 卡误导 | **限定「仅算术累加；非计算/位敏感算子 lossy 不得套用」** | `evolution-strategies` |
| 附 compute_dtype orphaned | **暂不处理**（非根因；若 P1-P4 落地后仍有价值再评估机检） | — |

---

## P1 precision-perf：R1 carve-out + 往返验证 + 特殊值保真（主战场）

### 选项

- **A（producer 规则）**：R1 加 carve-out（计算型才升精度；非计算/位敏感算子 native dtype 禁中转）；Step 2 加「往返 bit-exact **验证**（非断言）」+「bit-exact 算子 ±0.0/NaN/Inf 保真必做 + kernel 级落地」；一致性加「策略合理性」（锁定决策与位敏感性矛盾即就地修正）。
- **B（机器门）**：把 `compute_dtype` 结构化 + validate 加 GV 规则机检。
- **C（精度闭环兜）**：不改设计，靠 precision_debug 逐算子修。

### 决策：**A**

- §2.9 producer 自检 > 跨段门：精度损失应在产出 stage（precision-perf）就地闭合，不外推给 codegen/precision 闭环。
- B 是 backstop，非主修（且涉框架 gate 机制，更大）；C 违 §2.9（discover+regenerate，把设计缺陷拖到下游）。
- **四把尺子**：可维护 ✅（澄清 R1 不变式——升精度仅计算型）/ 可扩展 ✅（同类非计算算子自动 native）/ 可诊断 ✅（往返验证留证据）/ 架构合理 ✅（落在精度分析产权层）。

### 判据（结构语义，§1.12）

「计算型」判据 = **算子是否对值做算术**（加减乘除/规约/激活等改变数值），非算子名。非计算/位敏感 = 仅比较/搬运/重排/去重/掩码/选择（compare/sort/dedup/gather/scatter/mask/select）——举例用此结构特征，不点 unique/sort 名。

---

## P2 template-division LD1：二元 → 派生决策

### 选项

- **A**：LD1 必填 (i) 算子是否计算型、(ii) 是否 bit-exact（atol=0）；中间类型策略由二者**派生**（计算型→可升精度累加器；非计算/bit-exact→native 禁中转）。
- **B**：保留二元「是否升 FP32」，靠 P1 在下游拦。

### 决策：**A**

- 决策应在上游（LD1 锁定）就正确，下游 precision-perf（P1）是校验兜底——§2.9「上游自检兜住，下游忠实消费」。B 把修正责任全压给下游，违构造性保证优先。
- **四把尺子**：可维护 ✅（LD1 不变式 = 策略由语义派生）/ 可扩展 ✅ / 可诊断 ✅（LD1 记录算子类别 + 派生理由）/ 架构合理 ✅（决策产权在 template-division）。

---

## P3 buffer-kernel：示例 dtype-parametric + R7 一致性

### 选项

- **A**：`sizeof(float)` 示例改 `sizeof(T)`/native；R7 加「buffer/workspace 元素 dtype 须与 precision-perf `compute_dtype` 一致；非计算/bit-exact 算子须 = IO native」。
- **B**：仅修示例，不加 R7 约束。

### 决策：**A**

- 示例是强诱导信号（agent 3 实证 unique 的 float workspace 即按此范式），必改；R7 一致性是落地层构造保证（下游消费上游决策，§2.9）。
- **四把尺子**：可维护 ✅ / 可扩展 ✅ / 可诊断 ✅ / 架构合理 ✅（buffer-kernel 是落地 instantiation 产权层）。

---

## P4 codegen 维4：扩 UB 侧标量 cast + native dtype 默认

### 选项

- **A**：扩维4（AR 系列）禁「UB 侧 LocalTensor GetValue→标量 ToFloat/ToBfloat16/ScalarCast→SetValue 元素循环 cast 漏斗」，指向 vector `Cast()`；Step 4 加「默认 IO native dtype，非计算算子禁中转，仅算术 + design 声明 compute_dtype 才用更宽中转」。
- **B**：仅加 Step 4 策略，不动维4。
- **C**：加 Python scanner 机检。

### 决策：**A**

- unique 的 float 漏斗**正是 UB 侧标量 cast 循环**（`unique.h` L200/336/348）——维4 现版只禁 GM↔scalar，必须扩到 UB 侧才拦得住复发。
- C 不取：维N 是 agent 自读引导（已核实无 Python scanner），加 scanner 是过度工程（违 §2.9 构造性保证优先——producer 规则足够）。
- **四把尺子**：可维护 ✅（维4 不变式 = 禁标量 cast 做 tensor 转换）/ 可扩展 ✅ / 可诊断 ✅（维4 warning 留信号）/ 架构合理 ✅（维4 是 codegen 本职自检产权）。

---

## P5 coder agent：替换错误粒度默认

### 决策

`ascendc-coder.md:28`「Use fp16 (half) for compute unless specified otherwise」→「默认 IO native dtype 运算；非算术算子（compare/sort/dedup/gather/scatter/mask）中间必须 native（bit-exact）；仅算术算子在 design 声明 compute_dtype 时才用更宽中转」。

- 与 P2/P4 同源（native dtype 由算子语义决定），coder agent 须与 skill 一致（§4.1 manifest 与 skill 对齐）。

---

## P6 code-review red-line：加 lossy dtype intermediate（defense）

### 决策

加 TopN「Lossy dtype intermediate / scalar-cast funnel」：扫 kernel 元素循环内 `ToFloat(`/`ToBfloat16(`/`ScalarCast<`；标记 intermediate ≠ IO dtype 且算子非计算/bit-exact。
- §1.2 组合策略：P1-P5 是「正确改动」主修，P6 是 review 兜底（复发时拦），判据用 API 模式 + 算子类别（§1.12 结构信号）。

---

## P7 知识库 A1 卡：限定适用范围

### 决策

`A1_fp32_intermediate.md` 加限定：「FP32 intermediate 保精度**仅算术累加**；非计算/位敏感算子（compare/sort/dedup/gather/scatter）FP32 中转 lossy（BF16 往返/±0.0 符号/int 范围），不得套用」。
- 消除 LLM 当初套用「fp32 中转 = precision-preserving」的来源。

---

## 附 compute_dtype orphaned：暂不处理

P1-P4 落地后，dtype 策略正确性由 producer 规则保证；`compute_dtype` 字段是否结构化 + 机检（P1 选项 B）非必需，且涉框架 gate 机制（更大、与「只改引导文本」约束冲突）。**记 follow-up**：若未来要机器门，再评估结构化 `compute_dtype` + validate GV。

---

## 验证（desk check，非 heavy_llm）

新规则 applied 到 unique 的 requirement（7 dtype、bit-exact atol=0、算子=非计算去重），对照现有 design 产物证明能拦住旧 float 漏斗：

| 新规则 | applied 到 unique | 拦住的旧缺陷 |
|---|---|---|
| P2 LD1 派生 | unique 非计算 + bit-exact → native、禁 fp32 | 旧 `LD1_precision=fp32` |
| P1 往返验证 | 强制验 bf16→fp32→bf16 → 证伪（ToFloat 产零/±0.0 抹除）→ CRITICAL | 旧断言「往返保真」未验证 |
| P1 R1 carve-out | 非计算算子禁升精度中转 | 旧 R1「一律升精度」误导 |
| P1 特殊值保真 | ±0.0 须 kernel 级位掩码落地 | 旧 PP-004「mask sign bit」未落地 |
| P4 维4 扩展 | UB 侧标量 ToFloat/ScalarCast in loop → 标记 | 旧 `unique.h` L200/336/348 |
| P6 red-line | 同模式扫到 | 复发兜底 |

- 无 Python 改动 → 不跑 UT（维N 无 scanner）。
- 输出：desk-check 报告（Phase 2 落地时产出），逐条对照 unique 旧产物证命中。

---

## 执行分阶段（用户「别急着写代码」，避并发冲突）

### Phase 1（本轮，纯文档、零冲突）✅
- 新建本目录 `codegen-dtype-strategy/`：`01-problems.md`（L1）+ `02-analysis.md`（L3，本文）。
- `docs/plan/00-status-summary.md` 加索引行。
- **不动任何 skill/agent/red-line 文件。**

### Phase 2（已落地，2026-08-06）✅
并发 session push 后目标文件全 clean，落地 Layer 1-4 共 7 文件编辑。

**实施期沉淀的两点框架精化**（比初版决策更准，已写入规则）：
1. **解耦「升精度」与「升到 FP32」**：升精度是浮点算术累加的保精度技巧，不是普适"统一到 FP32"的 reflex；原语约束（Sort API half/float-only）强制更宽类型**不属"升精度"**（FP 用 vector Cast + 验往返，int 换原生路径）。规则措辞按此解耦，不把"升精度"当被禁的轴。
2. **升精度是浮点概念**：整数运算精确（仅溢出风险），扩宽是防溢出、非升精度；**int→FP 必丢精度（>2²⁴）禁止**。unique 把 int 灌进 FP32 称"升精度"是范畴错误。

**Desk-check（applied 到 unique：7 dtype / bit-exact atol=0 / 非计算去重）**：每条新规则均拦住旧 float 漏斗——
- LD1/R1 派生：unique 非计算 → native；整数不升精度 → 不锁"升 FP32"（拦旧 `LD1_precision=fp32`）。
- Step 2 往返验证：强制验 bf16→fp32→bf16 → 证伪（标量 `ToFloat` 产零 / `float==` 抹 ±0.0 / int 超范围）→ CRITICAL。**此条框架无关、最硬**，三类独立缺陷都就地证伪。
- codegen 维4 AR-4 / Step 4：UB 侧标量 cast 漏斗（`unique.h` L200/336/348）→ 标记，改 vector `Cast` / native。
- red-line TopN2.5 / A1 卡限定：复发兜底 + 消误导源。
- 无 Python 改动（维N 为 agent 自读引导，无 scanner）→ 不跑 UT。

### Phase 2 落地文件（7）
- `.claude/skills/ascendc-op-tiling-precision-perf/SKILL.md`（R1 / 一致性 / Step 2 往返验证 / 自检）/ `schema/tiling_precision_perf.json`
- `.claude/skills/ascendc-op-design-template-division/SKILL.md`（LD1 派生）
- `.claude/skills/ascendc-op-tiling-buffer-kernel/SKILL.md`（R3 / R7 / reduce 示例澄清）
- `.claude/skills/ascendc-op-dev-coding/SKILL.md`（维4 AR-4 / Step 4 dtype 策略）
- `.claude/agents/ascendc-coder.md`（L28 native dtype 默认）
- `.claude/skills/ascendc-code-review/references/red-line-checklist.md`（TopN2.5）
- `.claude/skills/evolution-strategies/references/strategy_cards/A1_fp32_intermediate.md`（限定浮点算术累加）

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-08-06 | 初版：P1-P7 决策（全链引导）+ 四把尺子 + 执行分阶段。Phase 1 完成（纯文档）；Phase 2 延后避冲突 |
| 2026-08-06 | Phase 2 落地（7 文件编辑 + desk-check）。实施期沉淀两点框架精化并写入规则：①解耦「升精度」与「升到 FP32」；②升精度是浮点概念、整数不升精度（int→FP 禁止）|
