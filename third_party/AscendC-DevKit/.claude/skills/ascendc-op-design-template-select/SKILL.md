---
name: ascendc-op-design-template-select
description: 概要设计阶段（tiling 前）判断算子主模板编程模型（SIMD/SIMT/MIXED）并给出 shape 路由与 VF 段级拆分建议
triggers:
  - 模板选择
  - SIMD/SIMT 模板判断
  - simd-simt-select
  - template-select
---

# SIMD/SIMT 模板选择

## 职责

在概要设计阶段、tiling 之前，判定算子计算主模板（SIMD / SIMT / MIXED）。

**判定总原则**：默认选择 = SIMD——先排查算子是否命中 SIMT 适用场景（有限特例集），未命中即 SIMD；命中后按是否存在大块连续内存搬运裁决纯 SIMT / MIXED。**计算形态分两类**：标量形态（R-06，每线程算单个标量）与张量/向量级批量算术（R-07，对整个张量做逐元素运算）——R-07 类天然可向量化，SIMD 主路径 + SIMT 兜底 → MIXED。具体规则、子类、阈值与技术依据见 `references/selection_strategy.md`；判定示例见 `references/examples.md`。

## 输入

从 prompt / 上下文读取算子规格（不跨读其它设计步骤的中间文件）：

- 确定性要求（默认确定性，总前提）
- 线程任务结构（每个线程是否独立完成输出元素的计算？规约是否跨线程归并？）
- 访问模式（有无索引张量 / 坐标驱动、连续/随机寻址、索引用于读还是写/归约）
- 控制流特征、计算模式（标量形态 vs 张量/向量级批量算术，R-06 / R-07）、shape / dtype、原子写、目标平台
- 数据规模与搬运特征（是否存在大块连续内存搬运，用于纯 SIMT / MIXED 裁决）

## 输出（写到当前工作目录）

| 产物 | 必需 | 说明 | 契约 |
|---|---|---|---|
| `template_decision.json` | 是 | 结构化决策数据（字段化裁决记录） | `schema/template_decision.json` |

> MIXED 时 json 的 `routing` 必填。产出不符合 schema → 拒绝，重试。

## 执行步骤

1. **平台检查（C-01）**：C-01 是**能力规则**（A5 代 950 系列支持 SIMT & SIMD；A2/A3 代 910B/910C 仅支持 SIMD），**只做能力放行、不产生模板倾向**：
   - A5 → 平台维度 verdict 记 **`unknown`**（两者皆可用，不倾向任何一方），继续排查 SIMT 适用场景；
   - 非 A5 → 平台维度 verdict 记 **`simd`**（强制 SIMD，'强制'语义由 rule_id C-01 承载），直接结束。
   判定记录：`dimension=platform, rule_id=C-01`。
2. **确定性前提裁决（R-05）**：默认确定性——算子未明确声明允许非确定性 → 按确定性方案设计。确定性**允许 SIMT**（无跨线程规约/原子写时，SIMT 与 SIMD 均确定性），但**禁止 SIMT 的跨线程规约与写数据**（涉及 C-02/R-04 语义则强制 SIMD）。判定记录：`dimension=deterministic, rule_id=R-05, verdict=simt`（默认允许 SIMT）；若计算涉及跨线程规约/原子写 → verdict 记 `simd`。
3. **计算形态判据（R-06 / R-07 区分）**：区分**标量形态**（R-06）与**张量/向量级批量算术**（R-07），见 selection_strategy.md「计算形态判据」：
   - **标量形态**（每线程算单个标量：比较/数学函数/纯标量算术）→ 命中 R-06，computation_mode 记 `simt`，进入 SIMT 特例排查；
   - **张量/向量级批量算术**（对整个张量做逐元素算术，如 `y=x1+(x2/x3)*scalar`，天然可向量化）→ 走 R-07：**SIMD 全覆盖**（规整连续大块、无广播/TensorList 大小不一）→ computation_mode 记 `simd`，纯 SIMD；**存在 SIMD 覆盖不到的 shape 子集**（中小数据 / 广播 strided / 多张量大小不一 / SIMD 约束不满足）→ computation_mode 记 `mixed`（SIMD 主路径 + SIMT 兜底），整体 MIXED。
4. **SIMT 适用场景排查（有限特例集）**：仅对**标量形态（R-06）**继续逐维度排查。排查分两步：
   - 先确认**未命中 C-02**（跨线程/跨 VF 浮点归并 → 强制 SIMD，verdict 记 **`simd`**、rule_id 记 C-02，结束；C-02 判据见 selection_strategy.md）；
   - 再排查是否命中任一 SIMT 特例（索引收集 R-01 读语义 / 标量形态计算 R-06 / 窗口独立规约 / 坐标驱动采样 R-01）。索引写/归约语义（R-04）不作 SIMT 适用场景。未命中任何特例 → **SIMD（默认选择）**。
5. **纯 SIMT / MIXED 裁决**：
   - **标量形态命中 R-06**：检查是否存在大块连续内存搬运（单次 ≥ 16KB，**建议值**）——无 → 纯 SIMT；有 → MIXED（SIMT 特例路径 + SIMD 大块路径）；
   - **张量/向量级批量算术（R-07）**：SIMD 为主路径——SIMD 全覆盖（规整连续大块）→ 纯 SIMD；存在 SIMD 覆盖不到的 shape 子集（中小数据/广播/多张量/SIMD 约束不满足）→ MIXED（SIMD 大块路径 + SIMT 兜底路径）；
   - 其余 SIMT 特例（索引读/R-02 动态控制流/窗口规约/坐标采样）按 selection_strategy.md「纯 SIMT vs MIXED」规则裁决。
   给出互斥、无遗漏、无重叠的 `routing`：**SIMD 大块路径**覆盖"规整连续、单次搬运 ≥ 16KB（建议值）的可向量化大块"；**SIMT 路径**覆盖其余形状（中小数据 / 离散寻址 / 动态寻址）。
6. **裁决收敛**：未命中 SIMT 特例且非 R-07 → SIMD；标量形态命中且无大块连续搬运 → 纯 SIMT；标量形态命中且有大块连续搬运 → MIXED；R-07 张量级批量算术 → SIMD 全覆盖则纯 SIMD，否则 MIXED（`routing` 中 SIMD 大块路径不可遗漏）。

**verdict 取值（全小写）与维度映射**：
- `simd`：该维度倾向/支持 SIMD。含硬约束命中——C-01 非 A5 平台、C-02 跨线程归并均强制 SIMD，verdict 一律记 `simd`（'强制'语义由 rule_id C-01/C-02 承载）；也用于 data_scale 中大数据量 + 大块连续搬运、access_pattern 索引写/归约语义确定性路径、R-07 张量/向量级批量算术 SIMD 全覆盖、R-05 涉及跨线程规约/原子写时等 SIMD 倾向维度。
- `simt`：该维度倾向/支持 SIMT。标量形态计算（比较/数学函数/纯标量算术）R-06 特例命中 → computation_mode 记 `simt`；R-05 确定性默认允许 SIMT（无跨线程规约/原子写时）→ deterministic 记 `simt`；也用于 R-01 索引读语义、R-02 动态控制流、R-03 中小数据规模。
- `mixed`：该维度同时存在 SIMD 与 SIMT 两条路径。用于 computation_mode 为**张量/向量级批量算术且存在 SIMD 覆盖不到的 shape 子集**（SIMD 主路径 + SIMT 兜底）；也用于 access_pattern 既有索引读语义 SIMT、又存在大块连续搬运可并入 SIMD 大块路径等单维度双路径场景。
- `unknown`：该维度不适用、不产生倾向或无信息。典型：platform 在 A5 上仅能力放行（两者皆可用）→ `unknown`；element_dependency 元素独立、C-02 不命中（仅"不排除 SIMT"，不倾向任何一方）→ `unknown`。
- **`mixed` 是整体推荐（recommendation）层面的状态**，通常由多个单维度 verdict 组合收敛得出（如张量级批量算术 computation_mode 记 `mixed`、data_scale 大块连续搬运记 `simd` → recommendation=MIXED）。

6. **写产物**：`template_decision.json`。


## 知识引用

| 内容 | 位置 |
|---|---|
| 判定策略（总原则 + 规则库 + SIMT 适用子类 + 阈值 + 技术依据） | `references/selection_strategy.md` |
| 结构特征 → 模板判定示例 | `references/examples.md` |
| 产物字段结构 | `schema/template_decision.json` |

## 约束

- 判定依据算子结构特征（线程任务结构/归并方式/访问模式/控制流/计算模式/数据规模/原子/确定性），不用算子名做分类锚点
- 默认输出确定性方案；非确定性方案仅当输入明确允许非确定性时才输出
- 只做"运行时 kernel 模板"选择，不涉及 C++ 模板参数（属 tiling skill 职责）
- 阈值为建议值，需按目标 CANN 版本复核，标注于 `known_limitations`
