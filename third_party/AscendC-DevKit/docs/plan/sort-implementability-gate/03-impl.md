# L4 实施方案：可实施性自检提前 + 精度知识补全

> 层级：**L4 / 实施方案**。具体改哪个函数、什么顺序、怎么验证。
> 依据 `01-problems.md`（L1）+ `02-analysis.md`（L3，已拍板 A 主 + B 兜底 / 补知识 / P4 通用对质）。
> **红线**：所有判据用结构信号，禁止耦合算子名（§1.12）。判据删掉算子名结论不变。
> **实施状态**：阶段 A / B 已完成（含 UT 3713 绿）；P4 的 H01 补丁 + knowledge_policy 修订已完成；阶段 C 待定（见 §五）。

---

## 一、改动目标

1. **template-division** 在"关键决策锁定"步加"算法可实施性自检"，产出 `locked_decisions.implementability`。**（已完成，见 §二）**
2. **`api-precision.md`** 修 "int32→float 无精度损失" 误导 + 补 int 索引/排序键 comparable 范式。**（已完成，见 §三）**
3. **H01 排序算法族**补"比较排序 + int64 索引精度陷阱"盲区。**（已完成，见 §四-P4）**
4. **knowledge_policy.md** 补"发现知识源信息遗漏 → 先下沉各层 → 都没有才暴露/提问，不自行猜测"。**（已完成，见 §四-P4）**
5. **codegen 前加载期校验**（兜底门）用知识库约束表机械查 dtype/算法组合冲突。**（阶段 C，待定，见 §五）**

本 L4 已覆盖 P1（可实施性自检）+ P2（精度知识）+ P4（通用对质机制）；P3（debug 减法）按 `precision-debug-blindspot/03-impl` 独立排期。

---

## 二、阶段 A：template-division 加可实施性自检

### A.1 改 `.claude/skills/ascendc-op-design-template-division/SKILL.md`

**位置**：`## 输出` 契约表下方，或"关键决策锁定"步（Step 6）。在 `locked_decisions` 的 `precision`/`buffer_num`/`split_axis_priority` 之后加 `implementability` 字段。

**新增自检项（Step 6 内，紧跟精度策略）**：

> **算法可实施性自检**（结构信号，不认算子名）：识别指定算法是否含以下模式，评估其在目标硬件的 dtype 约束 + 单会话可实施性：
> - **排序/去重/逆映射**（排序键比较、去重压缩、按索引散射回写）→ 检查排序键 dtype 转换是否有精度风险（见 `api-precision.md` int→fp 条目）、是否需多遍扫描。
> - **跨 dtype 转换参与比较**（排序键/索引需转 fp 才有原语支持，如 A2 Select 仅 half/float）→ 检查转换是否无损（|int| ≤ 2^24 才可进 fp32；int64 不可精确进 fp32）。
> - **多遍扫描 / 全局依赖**（需先算完一遍才能确定第二遍的范围/数量）→ 评估是否需拆解为多阶段或 host 预计算。
> 判定产出：高风险 → `implementability: {risk: high, reason: <结构描述>, mitigation: <拆解/换方案/known_limitations>}`；低风险 → `{risk: low, reason: <一句结构确认>}`。

**关键约束**：
- 判据只描述算法模式（排序/去重/逆映射/跨 dtype 比较），**不出现任何算子名**。
- `implementability` 是"评估 + 提示拆解"，**非禁止**：合法排序算子（排序为主功能的）标注低风险 + 确认 dtype 可行，不误伤。
- `known_limitations` 字段已有（SKILL.md L67 引用），高风险算法复用该字段。

### A.2 改 `schema/template_division.json`

**位置**：`example.locked_decisions` 加 `implementability` 字段（示例值 `{risk: low, reason: "native dtype 直接比较，无跨 dtype 转换"}`）；若 `required_keys` 或 example 有字段枚举，同步补。

---

## 三、阶段 B：补 `api-precision.md`

### B.1 修误导条目

`Cast RoundMode 选择` 表 L24 的 `int32_t → float | CAST_NONE | 整数→浮点，无精度损失` 改为：

```
| int32_t → float | CAST_NONE | 整数→浮点：\|v\| ≤ 2^24 无损；> 2^24 丢尾数（fp32 尾数 24bit）|
```

### B.2 加新条目「int 索引/排序键转 fp 比较」

在 `Cast RoundMode 选择` 表后新增一节（结构描述，不认算子名）：

> **int 索引/排序键转 fp 比较（A2 原语约束）**
> - **问题**：排序/去重/逆映射类算法需比较 int 索引/排序键，但 A2 的 `Select` 仅支持 half/float（`Select.md`），int 无法直接用向量比较做交换 → 被迫转 fp。
> - **精度风险**：int32 大值（>2^24）转 fp32 丢尾数；**int64 无法精确进 fp32**（64bit 值域 vs 24bit 尾数）。直接 `Cast(int64, float)` 排序 → 排序键错乱。
> - **正确做法**：
>   1. **comparable 位序转换**：把 int 按位序重排成可比较的 fp32/half（负数翻转、正数置符号位），无精度损失地用 `Compare/Select` 比较。示例（标量范式，可向量化）：
>      ```cpp
>      // int32 → 可比较的 uint32：负数取反，正数置最高位
>      uint32_t oa = (uint32_t)a;
>      oa = (a < 0) ? ~oa : (oa | 0x80000000u);   // 用位序而非数值比较
>      ```
>   2. **half 分段**（int32）：高 16bit 转 half 比较 + 低 16bit 兜底。
>   3. **避免**：int64 直接转 fp32 排序（必错）。
> - **判据**：索引/排序键比较涉及跨 dtype 转换 → 检查是否无损；不能无损则用 comparable 位序或分段，禁止裸 `Cast(int, fp)` 排序。

### B.3 更新引用

若 `api-precision.md` 被其他 skill 引用（如 codegen 的 dtype 策略），确认新条目在引用链可见。

---

## 三·五、阶段 P4：H01 补丁 + knowledge_policy 修订（通用对质机制）

> P4（枚举盲区）从 `01-problems.md` P4 坐实：H01 排序算法族生效但漏"比较排序 + int64 索引"组合 → 枚举式补 skill 改不完 → 需通用对质机制。本阶段已完成，记录如下。

### P4.1 改 H01 比较排序行（补 int64→fp32 精度陷阱）

**文件**：`.claude/skills/ascendc-op-general-design/references/patterns/atomic/H01_select-sort.md`

**改动**（L121 比较排序行"已知陷阱"扩展）：
- 在"硬件原语约束多…须逐条对质 + 实测验证"后追加 **跨 dtype 比较陷阱**：A2 `Select` 仅 half/float，int 排序键/索引需转 fp 才能向量比较；int32 大值（>2^24）转 fp32 丢尾数、**int64 转 fp32 必错**；排序键比较涉跨 dtype 转换必须对质无损性，不能无损用 comparable 位序（引用 `api-precision.md`）或换 radix/bitmap；**禁止裸 `Cast(int, fp)` 排序**。
- 选型判据加"**跨 dtype 转换必须无损**"条（L124-127 区）。

**红线**：判据用结构信号（"int 排序键/索引转 fp"），不认算子名。

### P4.2 改 knowledge_policy.md（信息遗漏 → 先下沉各层，不猜测）

**文件**：`.claude/skills/ascendc-op-design-shared/references/knowledge_policy.md`

**改动**（L38 后新增「发现知识源本身有信息遗漏时的处理」）：
- 某层知识源（含 best-practices）发现 API 关键约束文档未覆盖/描述不清 → **不得自行猜测、不得默认"文档没提就是没限制"**。
- **处理顺序**：① 先向下一层知识源下沉探索（best-practices 漏 → 查 Tier 3 dev-knowledge 裸签名/支持矩阵）；② 只有所有相关层级都没有明文 → 显式暴露（`known_limitations`/`verifiable_claims` 标注"未确认"），涉及决定计算正确性的约束 → `AskUserQuestion`；③ 不猜测填补。
- 判据：影响正确性判断的约束缺失必须显式暴露（§1.2 可诊断），但暴露前必须已完整下沉探索各层。

**这是 P4-B 通用对质机制的核心**：把"跨 dtype 转换无损性"作为骨架级 API 强制查证门（sort/topk 已触发）的必查项，不枚举 dtype 组合。

### P4.3 验证

- H01 补丁：结构信号判据，无算子名（grep 核查）。
- knowledge_policy 修订：分层语义正确（先下沉再暴露），不跳过任一层。
- 全量 UT 回归（H01/knowledge_policy 是 skill 文档，不影响 UT；若 H01 有守护测试 `test_h01_algorithm_family.py`，跑它确认不回归）。

---

## 四、阶段 C：codegen 前加载期校验（兜底门）

### C.0 决策（2026-08-23）：**不实施机械门**

- 判据：`int64 索引转 fp 比较 → FAIL` 需要机械扫描 LLM 产出的自由文本（design_spec 算法描述），而该描述无结构化字段 → 机械门脆弱（§1.14 控模型风险：易误报/漏报）。
- 本次已实施的引导层已覆盖：阶段 A（template-division 自检）+ 阶段 B（api-precision.md）+ P4（knowledge_policy 通用对质机制）在源头兜住 codegen 生成质量。
- 机械门的唯一价值是"设计自检漏了"场景——该场景由 debug 阶段（P3 减法后的"诊断+修复"阶段）本地识别并修，非加脆弱机械门。
- **状态**：不做。留档待未来实证"引导层确实拦不住"时再评估。

### C.1 定位

codegen 阶段（`codegen.py`）的输入校验，或 `validate`/`preflight`。按 §1.3 加载期校验优于运行期暴露。

### C.2 判据（结构信号，机械可查）

对设计产物（`design_spec.json` / `tiling_strategy.json`）扫描：
- **int64 索引参与 fp 比较**：设计声明"排序键/索引 dtype 为 int64 + 转 fp 比较" → 加载期 FAIL（int64 无法精确进 fp32），打回设计换 comparable 位序 / host 预排序。
- **int32 大值索引转 fp**：无法静态判定值域 → 不硬拦，靠 A.1 自检 + `known_limitations` 标注。

### C.3 判据来源

不硬编码 dtype 表，从知识库（`api-precision.md` 新增条目）读取约束，避免代码内维护第二份知识（§1.5 算子知识不进 Python）。

---

## 五、TDD 验证

### 阶段 A（template-division）

- **UT**：新增/更新 `tests/ut/.../test_template_division*`，验证 `implementability` 字段：
  - 含排序/去重 + 跨 dtype 转换的设计 → 产出 `risk: high`（判据命中，不认算子名）
  - 纯算术 + native dtype 比较 → `risk: low`
  - schema 校验 `implementability` 字段合法（required_keys/example 更新后加载期过）
- **ST**（可选）：真实跑 template-division skill，验证 `implementability` 写入 `template_division.json`。

### 阶段 B（精度知识）

- 无独立 UT（纯知识文档）。验证：新条目被 codegen 引用链可见（grep），措辞无算子名（判据：删掉算子名结论不变）。

### 阶段 C（加载期门）

- **UT**：`codegen.validate_inputs`（或对应函数）新增用例：
  - 设计含"int64 索引转 fp 比较" → 加载期 FAIL，reason 明确
  - 设计含"int32 索引 native 比较" → 通过
  - 判据从知识库读取，非硬编码

### 回归（§3.4 不 skip）

- 全量 UT 绿。
- 现有 template-division 用例（若 schema `locked_decisions` 加字段，确认 `example`/required 校验不破坏既有用例）。

---

## 六、边界（本 L4 不碰）

- **不碰** precision_debug 减法（P3，按 `precision-debug-blindspot/03-impl` **独立排期**，见 §八）。本次仅做其前置（P4 通用对质机制，让 codegen 少生成错 kernel）。
- **不碰** codegen 的算法实现（排序/去重逻辑本身），只做设计侧自检 + 知识 + 加载期门。
- **不碰** 其他 skill（`ascendc-op-design-tiling-*` 等），除非 P1 自检发现需同步。

## 七、风险

1. **误伤合法排序算子**：A.1 判据若过宽，可能把排序为主功能的算子也标 high。缓解：判据是"评估 + 提示拆解"非"禁止"，且 `implementability.risk=high` 只触发 `mitigation` 建议，不 halt。
2. **schema 变更破坏既有用例**：`locked_decisions` 加字段，需同步 example + 校验逻辑，用 TDD 阶段 A 回归兜住。
3. **判据措辞耦合算子**：所有判据用结构描述（排序/去重/跨 dtype），A/B/C 三阶段 code review 时核查"删掉算子名结论是否不变"。

## 八、实施顺序与决策状态

### 已完成
- **阶段 B**（api-precision.md 补精度知识）：已完成，UT 3719 绿。
- **阶段 A**（template-division 可实施性自检）：已完成，UT 3719 绿。
- **阶段 P4**（H01 补丁 + knowledge_policy 通用对质机制）：已完成，新增守护测试 6 用例。
- 全量默认范围（含非 heavy ST）：3846 绿，0 failed。

### 决策（2026-08-23）
- **阶段 C（codegen 加载期机械门）：不实施**（§四 C.0：控模型脆弱，引导层已覆盖，留档待实证）。
- **P3（debug 减法）：独立排期，本次不实施**。它是大重构（六 phase → 两 phase，触 framework orchestration + agent + skill + schema + UT），需专门设计 + 独立提交。本次完成的 P4 是其前置（减少错 kernel 进 debug）。

### P3 独立排期要点（后续）
- 按 `precision-debug-blindspot/03-impl`：删 bounds_check / printf_location / comment_bisect 独立 phase，收敛到「run_tests → 诊断+修复」两段。
- 删对应 schema（precision_diagnose.json 的 candidate_pool/runtime_error_info/arch_gaps、precision_printf.json、precision_comment_bisect.json、precision_bounds_check.json）。
- 删对应 UT（test_precision_debug_* 里测已删结构的用例）。
- 本次 unique 实证：六 phase 全跑仍失败（290min 空转）是减法的必要性证据。
