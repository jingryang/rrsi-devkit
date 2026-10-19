# codegen/详设 dtype 策略缺陷 — L1 问题记录（2026-08-06）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据 / 现象 / 根因事实 / 产权）。
> **不提方案、不排顺序、不写决策**（§1.8 L1 产权）。方案分析见 `02-analysis.md`（L3）。
>
> 上游 RCA：`docs/plan/precision-debug-unique-3of20-rca/01-problems.md` 的 **P1**（unique kernel float 中转 → 17/20 精度失败）。本文是 P1 的 codegen/详设 根因深挖——回答「为什么 codegen 会生成 float 中转的 kernel」。

## 证据来源

- **触发运行**：`output/20260805-152456-8b48b2/20260805-152456-434434/`（`unique` 算子，3/20 通过）
- **设计产物**（决策证据）：`artifacts/design/{template-division,tiling/T1/tiling_buffer_kernel.json,tiling/T1/tiling_precision_perf.json,integrate/data_flow.json,validate/design_spec.json,general-design-generator/general_design.json}` + `artifacts/requirement/requirement.json`
- **codegen 产物**：`artifacts/codegen/op_kernel/unique.h`
- **skill / agent / 知识库**：`.claude/skills/ascendc-op-{tiling-precision-perf,design-template-division,tiling-buffer-kernel,dev-coding}/`、`.claude/agents/ascendc-coder.md`、`.claude/skills/ascendc-code-review/`、`.claude/skills/evolution-strategies/`
- **调研方法**：三路并行 Explore（设计产物 / codegen skill / 详设 skill）+ 关键文件直读核实

## 核心事实（结论先行）

「所有 dtype 经 float 中转」**是详设阶段的显式决策**，codegen 忠实实现、未自创。根因不在 codegen、不在 unique 本身，而在**详设 skills 缺「非计算/bit-exact 算子必须 native dtype」的结构性规则**——`precision-perf` R1「一律升精度」对非计算算子主动误导，且整条流水线无 round-trip 损失验证、无 bit-exact/特殊值保真分析。

---

## P1（严重 · 详设 precision-perf）：R1「一律升精度」对非计算算子误导 + 无往返/特殊值保真分析

### 哪里坏了

`ascendc-op-tiling-precision-perf` 是精度分析 THE stage，却对「中转类型选择」既无正确判据、又无损失验证：
- **R1 主动误导**：「Cast 时机 = CopyIn 后立即升精度，CopyOut 前降精度」**无条件**。升精度只对**计算型**算子（算术累加，更宽累加器减舍入）有益；对**非计算/位敏感**算子（仅比较/搬运/重排/去重/掩码，对值不做算术）零收益、只引往返损失。R1 无此 carve-out。
- **Step 2 无往返损失验证**：精度链条只列 Cast 时机 + atol/rtol + Subnormal 策略，**不要求验证** `src→intermediate→src` 往返是否 bit-exact（只允许断言）。
- **无特殊值保真分析**：bit-exact（atol=0）算子的 ±0.0 符号 / NaN payload / Inf 符号在比较与中转路径的保真未作必做分析项。
- **一致性约束只查「与锁定决策一致」不查「决策合理」**：锁定决策（是否升 FP32）与算子位敏感性矛盾时不拦。

### 凭什么这么说（证据）

1. **skill 文件**（`.claude/skills/ascendc-op-tiling-precision-perf/SKILL.md`）：
   - L38 R1：「Cast 时机 = CopyIn 后立即升精度，CopyOut 前降精度」——无条件，无 carve-out。
   - L57-61 Step 2「精度分析」：精度链条表 / Cast 时机 / 验收标准（atol/rtol）/ 异常值策略——**无 round-trip 验证、无 bit-exact/特殊值项**。
   - L45 一致性：「精度策略必须与模板划分产物中的锁定决策一致（是否升 FP32、Subnormal 处理）」——**只查一致，不查合理**。
2. **unique 设计产物实证 mis-标定**（`artifacts/design/tiling/T1/tiling_precision_perf.json`）：
   - `compute_dtype=fp32`（PP-001），`precision_chain` 对 **bf16** 评 `"low"` 并断言「bf16→fp32 升精度无损… bf16→fp32→bf16 往返保真」、对 **fp16** 评 `"low"`——**断言未验证**，恰是失败用例（BF16→全零、FP16 ±0.0 符号被 `float==` 抹）。
   - PP-004「±0.0 通过 mask sign bit 视为相等，写出统一 +0.0」——**指定了 mitigation 却从未落地**（kernel 实为 `float==` 相邻比较，无位掩码、无强制 +0.0）。
3. **后果**：precision-perf 本该拦住 lossy 中转，却给 float 漏斗盖了「low risk / 往返保真」的合规章。

### 根因（事实）

精度分析 stage 缺三条结构性规则：(a) 非计算算子 native dtype carve-out；(b) 中转往返 bit-exact **验证**（非断言）；(c) bit-exact 算子特殊值保真必做分析 + kernel 级落地。

### 产权

`ascendc-op-tiling-precision-perf` skill。与 §1.13（golden 是权威、bit-exact 要求须忠实保真）、§2.9（producer 自检闭环）相关。

---

## P2（严重 · 详设 template-division）：LD1 精度策略锁是二元「是否升 FP32」，无派生判据

### 哪里坏了

`ascendc-op-design-template-division` 的 LD1「精度策略（是否升 FP32…）」是**自由二元选择**，不要求声明算子是否计算型、是否 bit-exact，故无法据算子语义派生正确策略——unique（非计算 + bit-exact）本不该升 FP32，却被锁成 fp32。

### 凭什么这么说（证据）

1. **skill 文件**（`.claude/skills/ascendc-op-design-template-division/SKILL.md`）：LD1 prompt 仅「精度策略（是否升 FP32，A5 Subnormal 软仿是否影响精度路径）」——二元、自由字符串。
2. **unique 设计产物**（`artifacts/design/template-division/template_division.json`）：`locked_decisions.precision="fp32"`，rationale「排序网络比较逻辑需在统一位宽上判定 IEEE 754 数值相等」。
3. **内部自相矛盾**（决策被推翻、无不变式兜底）：原 LD1 rationale 写「整数 dtype 走原生位宽比较，不触发升 FP32」，但 `buffer-kernel BK-002` 以「Sort API 仅支持 half/float」为由**推翻**之，把 int 也灌进 fp32。即设计流水线对 dtype 策略**无一致不变式**，后段可自由覆盖前段。

### 根因（事实）

LD1 缺「算子是否对值做算术 + 是否 bit-exact」两个派生输入；策略应由算子语义派生，非自由选择。

### 产权

`ascendc-op-design-template-division` skill（LD1 锁）。

---

## P3（严重 · 详设 buffer-kernel）：workspace 示例硬编码 sizeof(float) + R7 无 dtype 一致性约束

### 哪里坏了

`ascendc-op-tiling-buffer-kernel` 的 canonical workspace 示例直接写 `sizeof(float)`，诱导产生 float workspace；R7（Cast 标注/时机）不约束 buffer/workspace 元素 dtype 与精度决策一致。

### 凭什么这么说（证据）

1. **skill 文件**（`.claude/skills/ascendc-op-tiling-buffer-kernel/SKILL.md` L94）：用户 workspace 字节数示例「`sCoreNum × W × dAlignF32 × sizeof(float)`」；`schema/tiling_buffer_kernel.json` example `workspace.rationale="cross-core reduce: sCoreNum*W*dAlignF32*sizeof(float)"`——**示例本身硬编码 float**。
2. **unique 设计产物**（`artifacts/design/tiling/T1/tiling_buffer_kernel.json`）：`cast_annotation`「int8/int32/int64/uint8 输入：CopyIn 后立即 Cast 到 fp32…bf16 走 bf16→fp32 Cast」；决策 BK-002「CopyIn 后立即 Cast 升 fp32（R3）→ 走 Sort → CopyOut 前 Cast 回」——buffer-kernel 按 skill 示例范式产出 float workspace。

### 根因（事实）

buffer-kernel 落地层无「workspace/buffer 元素 dtype 须与精度决策一致、非计算/bit-exact 算子须 = IO native dtype」约束，且示例反向诱导。

### 产权

`ascendc-op-tiling-buffer-kernel` skill + schema。

---

## P4（严重 · codegen）：维4 未覆盖 UB 侧标量 cast 漏斗 + 无 dtype 策略默认

### 哪里坏了

`ascendc-op-dev-coding` 的自检 `维4`（AR-1/AR-2/AR-3）只禁主循环 **GM↔scalar** 搬送，未覆盖 **UB 侧标量 cast 漏斗**（元素循环内 `LocalTensor GetValue → 标量 ToFloat/ToBfloat16/ScalarCast → SetValue`）；且 codegen 无 dtype 策略默认规则（默认应 IO native dtype）。

### 凭什么这么说（证据）

1. **skill 文件**（`.claude/skills/ascendc-op-dev-coding/SKILL.md` L299-301）：维4 AR-1「主循环内 GetValue/SetValue 做 **GM↔scalar** 搬送」——**只覆盖 GM 侧**，UB 侧 LocalTensor 标量 cast 不在禁列。
2. **unique codegen 产物**（`artifacts/codegen/op_kernel/unique.h`）：L104 `GlobalTensor<float> valGm_`；L200 BF16 `AscendC::ToFloat(xDeq.GetValue(i))`；L336 BF16 出 `AscendC::ToBfloat16(...)`；L348-350 FP16 出 `ScalarCast<float, half, CAST_ODD>`——**全在 UB 侧元素循环内做标量 cast 漏斗**，维4 漏过。
3. **维N 为 agent 自读引导、无 Python scanner**（已核实 `src/` 无对应扫描器）——故扩维4 是改 skill 文本，非改 Python。

### 根因（事实）

维4 范围漏 UB 侧标量 cast；codegen 缺「默认 native dtype、非计算算子禁中转」策略规则。

### 产权

`ascendc-op-dev-coding` skill（维4 + Step 4）。

---

## P5（中等 · coder agent）：放任 LLM 自选计算类型

### 哪里坏了

`.claude/agents/ascendc-coder.md:28`「Use fp16 (half) for compute unless specified otherwise」给 LLM 一个**错误粒度**的默认——它建立「LLM 可独立于 IO dtype 自选一个计算类型」的先例，叠加 P4 无 native-dtype 规则，使 LLM 自由选 float 标量中转作「通用多 dtype 处理」。

### 凭什么这么说（证据）

- `.claude/agents/ascendc-coder.md` L28（Coding Rules）：「Use fp16 (half) for compute unless specified otherwise」——全栈唯一显式 compute-dtype 默认，且放任 LLM。
- 注：codegen 最终产出是 A3 Membase 路径（`ScalarCast`/`ToFloat` 为 A3 标量 API），与 `ascendc-coder`（非 regbase）路径一致；regbase coder（`ascendc-coder-regbase.md`）未重复此规则、全交给 skill。

### 根因（事实）

coder agent 默认规则粒度错（应「IO native dtype」，非「fp16 compute」），对非计算算子误导。

### 产权

`.claude/agents/ascendc-coder.md`。

---

## P6（中等 · code-review）：red-line 无 lossy dtype intermediate 规则

### 哪里坏了

`ascendc-code-review` 的 7 大类 + 13 TopN 红线**无 lossy dtype 中转 / scalar-cast funnel 项**，复发时无人兜底。

### 凭什么这么说（证据）

- `.claude/skills/ascendc-code-review/references/red-line-checklist.md`：7 类（除零…数据竞争）+ 13 TopN（特殊值/输入校验/int64 偏移/GM workspace…）——**无 dtype 中转/cast 漏斗红线**。TopN 2.1「特殊值」只管 op doc 文档化 nan/inf/±0，不管 cast 正确性。
- 最接近的指引 `evolution-knowledge/.../common_pitfalls.md`#4「Wrong Cast Direction」**自相矛盾**（同一条 `Cast(fp32,fp16,CAST_NONE)` 既标 WRONG 又标 RIGHT），且只管 vector `Cast()` 不管标量漏斗。

### 产权

`ascendc-code-review` skill（red-line-checklist）。

---

## P7（轻 · 知识库）：A1 策略卡把「fp32 intermediate」框为通用 precision-preserving

### 哪里坏了

`evolution-strategies` 的 `A1_fp32_intermediate.md` 把「FP32 intermediate computation」列为 **precision-preserving 策略**——对算术累加正确，对非计算/位敏感算子是毒。LLM 当初套用「fp32 中转 = 保精度」的来源即此（叠加 `ascendc-dev-knowledge` 标量 API 文档把 `ToFloat`/`ScalarCast<float,half,CAST_ODD>` 列为标量提升正道）。

### 凭什么这么说（证据）

- `.claude/skills/evolution-strategies/references/strategy_cards/A1_fp32_intermediate.md`：以「FP32 intermediate — 精度保持」立卡，未限定算子类别。
- 三路调研结论：codegen 任何 skill/agent 文件**都不提** `ToFloat/CAST_ODD`——LLM 从 API 知识库 + A1 卡自学此模式。

### 产权

`evolution-strategies` 知识库（A1 卡）。

---

## 附：`compute_dtype` 字段 orphaned（次要卫生问题）

`precision-perf` schema 声明 `compute_dtype`（example `"fp32"`），但全仓 grep **无任何 reader**——codegen 不读此字段（它通过 design 的 pseudocode/cast_annotation 得到 fp32 决策，见 P4 证据 2）。即字段**声明了未被消费**。这不是 float 漏斗的根因（决策经他路到达 codegen），但是契约卫生缺口（设计意图本可经此字段机检，却悬空）。

---

## 问题汇总矩阵

| 问题 | 严重度 | 层 | 核心锚点 | 产权 skill/文件 |
|---|---|---|---|---|
| P1 R1 误导 + 无往返/特殊值分析 | 严重 | 详设 | `precision-perf` R1 L38 / Step 2 L57-61 / 一致性 L45 | `ascendc-op-tiling-precision-perf` |
| P2 LD1 二元无派生判据 | 严重 | 详设 | `template-division` LD1 | `ascendc-op-design-template-division` |
| P3 workspace sizeof(float) + R7 无约束 | 严重 | 详设 | `buffer-kernel` L94 / R7 + schema | `ascendc-op-tiling-buffer-kernel` |
| P4 维4 漏 UB 侧标量 cast + 无 dtype 默认 | 严重 | codegen | `dev-coding` 维4 L299-301 / Step 4 | `ascendc-op-dev-coding` |
| P5 coder agent 放任自选计算类型 | 中等 | codegen | `ascendc-coder.md:28` | `ascendc-coder.md` |
| P6 red-line 无 lossy dtype 项 | 中等 | review | `red-line-checklist.md` | `ascendc-code-review` |
| P7 A1 卡误导 | 轻 | 知识库 | `A1_fp32_intermediate.md` | `evolution-strategies` |
| 附 compute_dtype orphaned | 轻 | 契约卫生 | `tiling_precision_perf.json` 无 reader | precision-perf schema |

## 与既有工作关系（避免重复产权）

- **`precision-debug-unique-3of20-rca` P1**：即本缺陷的下游表象（kernel float 中转 → 17/20 精度失败）。本文是 P1 的**上游根因**（为什么 codegen 会产 float 中转）。RCA 的 P2/P3/P4 是 precision 闭环框架侧，另线。
- **`precision-debug-agent-abort` / `precision-debug-closure-hardening`**：正交（precision 闭环机制/账目）；本组是上游 design/codegen 不再产 lossy dtype 策略。
- **§1.12（禁具体算子耦合）**：所有规则须按「算子是否对值做算术 + 是否 bit-exact」（结构语义）判，不认 unique/sort 等名——本组问题清单的修复均遵守此约束（见 L3）。

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-08-06 | 初版：基于 unique 运行 + 三路调研记录 P1-P7 + 附 compute_dtype orphaned。方案见 `02-analysis.md`（L3）|
