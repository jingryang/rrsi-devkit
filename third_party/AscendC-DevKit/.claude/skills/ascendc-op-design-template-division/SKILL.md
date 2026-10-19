---
name: ascendc-op-design-template-division
description: 确定算子计算模板列表、TilingKey 路由、锁定关键决策
triggers:
  - 模板划分
  - template-division
  - 算子计算模板设计
---

# AscendC 算子模板划分

## 职责

确定算子计算模板列表、TilingKey 路由、锁定关键决策。

## 输入

从当前工作目录读取上游产物文件：

- `general_design.json`：上游概设的结构化产物（轴优先级、TilingData 字段定义、模板候选方案等）。
- `template_decision.json`：上游概设的 SIMD/SIMT 编程模型判定（可选——A2/A3 平台锁定 SIMD 不产出；无此文件时默认编程模型=SIMD）。
- 算子身份已在 prompt 提供（「## 算子」段）。
- 兼容性约束（可选，增量场景）。

> 不跨读其它设计步骤写出的中间文件。
## 输出（用 Bash（`cat`）写到当前工作目录）

| 产物 | 必需 | required_keys | schema |
|---|---|---|---|
| `template_division.json` | 是 | `templates, locked_decisions` | `schema/template_division.json`（本 skill 同 plugin 根目录，可按需 Read 确认字段结构） |

> 契约的机器校验来源：`schema/template_division.json`（JSON，含 required_keys + example）。
> 产出不符合 schema → DevKit 适配层拒绝，重试。
## 执行步骤

> **不校验上游完成状态**：直接消费已提供的概设产物即可。**不去找 checkpoint 判断上游"完成没"**
> ——跨步骤搜寻"本应存在"的中间文件正是要铲除的死循环病根。

1. 从已提供的算子规格与概设产物提取轴属性、模板候选、TilingData 字段定义等，作为已知约束
2. **消费编程模型决策（`template_decision.json`）**：
   - 读取 `template_decision.json` 的 `recommendation`（SIMD / SIMT / MIXED）；文件缺失时**默认编程模型=SIMD**（A2/A3 平台锁定，能力规则 C-01）。
   - `SIMD` / `SIMT` → 模板条目标注 `programming_model`，模板划分按既有原则（轴属性/mode/对齐）进行；
   - `MIXED` → 模板列表**必须覆盖 SIMD 性能路径 + SIMT 兜底路径**（性能路径不可遗漏）：`routing` 的 shape 条件是模板路由的**唯一来源**（与 TilingKey 路由一致，不另立一套路由）；编码形态（模板内双路径 vs 拆独立条目）按模板数量控制原则现场决定。
3. 读取兼容性约束（若提供），提取存量接口约束
4. 算子计算模板划分（AskUserQuestion 确认）：
   - 基于轴属性组合枚举候选模板
   - 分析各模板的计算路径差异
   - 确定是否可合并（退化关系分析）
   - **reduce 对齐差分**：若算子使用 `ReduceSum` 高阶归约 API，判断 reduce 最内层轴是否可能非 32B 对齐，决定单模板内 DataCopyPad 补零还是按对齐/非对齐分模板。A2/A3 `srcInnerPad` 只支持 true 的约束与补零范式见 `ascendc-op-design-shared/references/reduce_align_strategy.md`（A5 Regbase 不适用，见 `a5_regbase_design.md`）
   - **规约类算子二分累加模板**（A5，命中二分累加场景时）：沿规约轴计算 sum/mean/var 的算子，规约轴对齐后 ≤ 4·VL² 且 UB 容纳时采用**单一的性能二分全载模板**；二分累加是模板**内置属性**，kernel 内部按规约长度分 ≤VL / ≤2VL / ≤2VL² / ≤4VL² 四分支运行时分派，**不按分支拆 TILING_KEY**（判据与红线见 `ascendc-op-design-shared/references/a5_regbase_design.md`「树形/二分累加设计要点」）
5. TilingKey 路由设计（AskUserQuestion 确认）：
   - 每个 TilingKey 唯一路由到一个 Kernel 入口
   - 路由条件基于 shape 特征（非 C++ 模板参数）
   - 验证路由完整性（无遗漏、无重叠）
   - **轴参算子路由枚举**：若为轴参算子（概设含 `axis_param_design`），`route_condition` 须**显式枚举 dim 路径分支**（如 `dim==last_axis` / `dim!=last_axis`），使每个 dim 路径可被独立路由到 kernel 入口或同入口内 if 分支；**严禁"dim 任意轴"式笼统概括**——笼统概括会使下游无法核对路径覆盖度，导致 dim≠末轴 路径静默漏设计（EZ1008）。
6. 沿用概设的轴优先级：
   - 从概设产物取「并行分解策略」的多核切分轴优先级
   - 若产物未含该节（如用户提供的概设格式不同），从概设正文中搜索
     "多核切分"、"轴优先级"、"parallel"等关键词，提取等效内容
   - 作为当前步骤的已知约束，不重复讨论
7. 关键决策锁定（逐项 AskUserQuestion，优先通过 `ascend-hardware` 确认目标平台）：
   - 精度策略（**派生，非自由"是否升 FP32"**）：(i) 算子是否对值做算术、(ii) 是否 bit-exact（atol=0）→ 据此派生中间类型：**浮点算术 → 可升精度累加**；**非计算 → native dtype**。**整数不升精度**（运算精确；int→FP 丢精度禁止，原语约束下换原生 int 路径）。判据按"算子是否对值做算术"，不认算子名。A5 Subnormal 软仿是否影响精度路径。
   - **算法可实施性自检**（**结构信号，不认算子名**，源头治理）：识别指定算法是否含以下模式，评估其在目标硬件的 dtype 约束 + 单会话可实施性：
     - **排序/去重/逆映射**（排序键比较、去重压缩、按索引散射回写）→ 检查排序键 dtype 转换是否有精度风险（int 索引/排序键转 fp 比较的丢精度边界与受支持 dtype 见 `ascendc-api-best-practices/references/api-precision.md`）；风险高 → 用 comparable 位序 / host 预排序 / 换方案。
     - **跨 dtype 转换参与比较**（排序键/索引需转 fp 才有原语支持）→ 检查转换是否无损；不能无损则 comparable 位序或分段，**禁止裸 `Cast(int, fp)` 排序**。
     - **多遍扫描 / 全局依赖**（需先算完一遍才能确定第二遍的范围/数量）→ 评估是否需拆解为多阶段或 host 预计算。
     - 判定产出：高风险 → `implementability: {risk: high, reason: <结构描述>, mitigation: <拆解/换方案/known_limitations>}`；低风险 → `{risk: low, reason: <一句结构确认>}`。**这是"评估 + 提示拆解"，非禁止**——合法排序（排序为主功能）标低风险 + 确认 dtype 可行，不误伤。
   - BUFFER_NUM 初步选择（基于 Roofline 粗估，A5 Regbase 下寄存器中间结果减少 UB 压力，可能影响 BUFFER_NUM 选择）
   - 多阶段 UB 方案（若需要，区分 Membase/Regbase：A3 中间结果占 UB，A5 中间结果留寄存器，方案可行性判断不同）
   - ⚠️ 核间切分轴优先级**不在此处锁定**。此项已在概设产物「并行分解策略」节给出。若模板划分结果与概设的轴优先级假设不一致，通过 AskUserQuestion 向用户确认。
8. 按本 skill「## 输出」段的契约（required_keys）写出模板划分结构化产物（含模板列表、路由、锁定决策、跨模板依赖等字段）。**轴参算子须将概设 `axis_param_design` 原样透传进 `template_division.json` 顶层**（当前实现易在该步丢失，导致下游 tiling/codegen 拿不到轴参规格而无法实现 dim≠末轴 路径）。
   - **模板 notes 内容边界（防下游被越界预判锚定）**：`templates[].notes` 只写**模板划分与路由事实**——覆盖域、路由条件、候选否决理由、跨模板关系。**禁止**写入模板内 kernel/VF 结构预判（如"各段共用同一规约骨架""以迭代序号分支区分语义""统计量驻留寄存器/UB"）——模板内的计算段划分与 VF 编排是下游 `ascendc-op-tiling-vf-design` 按其 C1-C4 切分规则**独立推导**的职责，本步骤的预判会随 prompt 注入锚定下游结构选择，造成同类算子跨 run 结构漂移。若确有跨步骤必须传递的结构事实（如 golden 分母语义差异），写入 `known_limitations` 并标注"语义事实，非结构预判——下游独立做结构推导"。

9. **输出自检**：
   - [ ] 模板列表有明确数量（非 "N 待定"）
   - [ ] 每个模板有路由条件（无遗漏、无重叠）
   - [ ] 每个模板的 tiling_key 唯一（不同模板不重复同一个 key——否则 codegen 路由歧义）
   - [ ] **编程模型已消费**：`template_decision.json` 存在时 `recommendation` 已并入模板条目（每条目标注 `programming_model`）；MIXED 时模板列表覆盖 **SIMD 性能路径 + SIMT 兜底路径**（性能路径未遗漏）、`routing` 条件与 TilingKey 路由一致（无二套路由）；文件缺失时已按默认编程模型=SIMD 处理
   - [ ] **规约类二分累加模板（A5 命中场景）**：`templates` 中命中场景是否仅为**一个**性能二分全载模板？该模板的 `route_condition` 是否写明判据（规约轴对齐 ≤ 4·VL² 且 UB 容纳）？二分四分支（≤VL / ≤2VL / ≤2VL² / ≤4VL²）是否保留在同一模板内运行时分派、未拆成多个模板或多个 TILING_KEY？
   - [ ] 锁定决策有明确理由（知识库/逻辑推导/用户裁决）
   - [ ] **算法可实施性**：`locked_decisions.implementability` 已产出（risk=high/low + reason 结构描述 + 高风险带 mitigation）；含排序/去重/逆映射/跨 dtype 转换的算法已核对精度风险（见 Step 7），无"裸 int→fp 排序"未标注
   - [ ] 核间切分轴优先级：已确认与概设产物「并行分解策略」节一致（或已 AskUserQuestion 确认差异）
   - [ ] **轴参算子**（概设含 `axis_param_design`）：已原样透传进 `template_division.json` 顶层？`route_condition` 已显式枚举 dim 路径（末轴/非末轴）而非"dim 任意轴"式笼统概括？
   - [ ] **化简/降维/等价声称验证**：模板选择/算法简化若含"化简/降维/等价/覆盖"声称，已用 Python 对照 golden 验证或引用 `ascendc-op-design-shared/references/design-math-claims/verified_facts.md`，产物含 `support_domain` + `known_limitations`（方法/判据见 `ascendc-op-design-shared/references/design-math-claims/claim-verification-checklist.md`；禁止裸描述，跑不通先自修、多次后仍不行标限制继续、不 halt）
   - [ ] **模板 notes 内容边界**：`templates[].notes` 无模板内 kernel/VF 结构预判（共用骨架/迭代分支区分/统计量驻留位置等）；确需传递的结构事实已放 `known_limitations` 并标注"语义事实，非结构预判"
   - 自检失败 → 就地修正直到通过
   - 自检通过后，用 Bash（`cat`）把模板划分结构化产物写到当前工作目录（字段以本 skill「## 输出」段声明的 required_keys 为准；`templates` 记模板列表、`decisions` 记模板划分与路由决策，跨模板依赖等记入相应字段）。

## 知识引用策略

通用知识引用策略（三层优先级 + 禁止猜测 + AskUserQuestion 兜底）详见 `ascendc-op-design-shared/references/knowledge_policy.md`。

平台差异化参考（A3 vs A5）详见 `ascendc-op-design-shared/references/platform_diff.md`。

本 skill 特有的查询场景：

| 层级 | 查询场景 | 对应执行步骤 |
|------|---------|-------------|
| Tier 1 | 目标平台确认（A3 vs A5）、UB 大小、核数 | 步骤 7（关键决策锁定） |
| Tier 2 | BUFFER_NUM 选择策略、精度策略、核间切分轴优先级原则 | 步骤 7（关键决策锁定） |
| Tier 3 | 多阶段 UB 方案的 API 可行性、轴合并的格式限制 | 步骤 7（多阶段 UB 方案） |

**兜底策略**：当 Tier 2/Tier 3 均无法提供决策依据，必须通过 `AskUserQuestion` 向用户提问。锁定决策必须有明确理由——理由可以是知识库查证、逻辑推导或用户裁决，不可"待定"。

## 约束

- 只确认"算子计算模板"（运行时 kernel 类），不涉及 C++ 模板参数
- C++ 模板参数属于 tiling skill 的职责范围
- 锁定决策必须有明确理由，不可"待定"
