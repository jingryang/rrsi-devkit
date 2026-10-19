# AscendC 算子 Tiling 类目模式库（索引）

> 本目录按**算子类目**沉淀 Tiling 设计的场景判定、切分/UB 预算公式、算法选型与 Kernel 编排参考。
> 它是**知识/数据**，不是切分方法的第二权威——方法主线仍在 `ascendc-op-tiling-split`（核间/核内切分、
> ubFactor）与 `ascendc-op-tiling-buffer-kernel`（Buffer/Kernel 伪代码），本目录只补「该类算子的特定套路」。

## 何时查阅

- 已判定算子类目，需要该类目的**场景分支树**（如何在 UB 容量/多核约束下继续细分）。
- 需要类目特定的 **UB 预算公式 / tile 推导**（如 transpose 的 `tileNA*(16*C+32)`、sort 的 `sortBytesPerElem`）。
- 需要在多个**算法**之间选型（在线单遍 Welford、跨核 Group Reduce、二分累加、两级归并排序等）。
- 审查/校对某类算子的 tiling 是否漏了关键分支或约束。

**不用于**：核间/核内切分的通用方法（走 `ascendc-op-tiling-split`）；TQue/TBuf 分配与 Cast 时机
（走 `ascendc-op-tiling-buffer-kernel`）；精度/性能分析（走 `ascendc-op-tiling-precision-perf`）；
A5 RegBase 的 VF 编排（走 `ascendc-op-tiling-vf-design`）；SIMT 场景（走 `ascendc-simt-operator-design-patterns`）。

## 阅读顺序

1. 先用下方「类目路由」按**结构判据**（不看算子名）确定类目。
2. 读该类目目录下的 `patterns.md`（场景判定 + 分支树 + 跨文档链接）。
3. 沿 `patterns.md` 的链接进入详细文档（算法/UB 预算/实现参考）；一个子问题最多展开 3~5 篇。
4. 需要跨类目公共概念（对齐、UB 预算口径）时再看 [`reduction/tiling-fields.md`](reduction/tiling-fields.md)。

## 类目路由（结构判据优先）

> **判据来自算子结构/语义，不来自算子名。** 下表左列是可从 proto/shape/公式客观判定的结构信号，
> 命中后才加载对应类目参考；同一条目可叠加多个类目（如融合算子）。

| 类目 | 结构判据（命中即选） | 参考入口 |
|------|----------------------|----------|
| Reduction | 输出维度少于输入 / 含沿轴把长度 N 折叠为 1 的规约；可选带极值位置索引输出；**归一化**（LayerNorm/RmsNorm/Rms 类 = 归约 + 逐元素/广播变换）也走此路由 | [reduction/patterns.md](reduction/patterns.md)（⚠️ 先读，含场景路由与算法选择） |
| Sort | 需要全局有序或 Top-K 选择（比较/排列语义，输出为有序序列或前 K 项+索引） | [sort/patterns.md](sort/patterns.md)（⚠️ 先读） |
| Elementwise | 所有输入与输出 shape 相同、逐元素独立、无跨元素依赖 | [elewise/patterns.md](elewise/patterns.md)（⚠️ 先读） |
| Broadcast | 输入之间 shape 不同、需按轴广播对齐到输出 shape | [broadcast/patterns.md](broadcast/patterns.md)（⚠️ 先读） |
| Conversion | 输入输出元素总数相同、维度顺序/布局发生重排（transpose/permute 等） | [conversion/patterns.md](conversion/patterns.md)（当前仅 small-channel transpose 展开） |

> 未覆盖类目（MatMul / FlashAttention / Random / Convolution / 其它 NN 融合）不在本目录——MatMul、
> FlashAttention 等有各自的专门设计流与模式，按 `ascendc-op-general-design` 的 LP×CP×ES 框架及对应
> 专项方法处理；其余未覆盖类目同样按 LP×CP×ES 框架与 `ascendc-op-tiling-split`/`-buffer-kernel` 通用方法推导。

## 类目资产

| 类目 | 目录 | 用途 |
|------|------|------|
| Reduction | [reduction/](reduction/) | 场景路由、算法选型（Welford/GroupReduce/二分累加）、AR/ARA 全载/分载、索引跟踪、多轴变换、多输出 Buffer 方程、Norm 类 Tiling 字段（LayerNorm/RmsNorm） |
| Sort | [sort/](sort/) | 场景路由（Pattern A/B/C）、单次 Sort UB 建模、两级归并排序详细方案 |
| Elementwise | [elewise/](elewise/) | 场景路由、dtype × 运算升精度分支、多核/UB 切分公式、最小 Tiling 模板 |
| Broadcast | [broadcast/](broadcast/) | 合轴与场景路由、OneDim、UB Broadcast（静态/动态）、NDDMA Broadcast |
| Conversion | [conversion/](conversion/) | small-channel transpose 建模、UB 预算、offset table、Kernel 骨架 |

## 使用纪律

- **硬件参数单一来源**：一切硬件容量/带宽/核数/寄存器参数（`UB_SIZE`、L1/L0、Cube/Vector 峰值）
  必须运行时从平台取（`GetCoreMemSize(UB)` / `GetPlatformInfo().GetUbSize()` / `PlatformAscendC`）或查
  [`../platform_diff.md`](../platform_diff.md) 与工作目录 `hw_params.json`。本文档中的公式一律用符号
  （`UB_SIZE`、`ubSize`），**文档里的数值仅为推导示例，不得当作可硬编码常量**。
- **芯片命名**：本目录用代际码 A2/A3/A5 表述（A2/A3 Membase、A5 Regbase）。进 CANN 编译/`AddConfig`
  的字面量一律经 `domain/chip.py` 的 `to_soc_version()` 翻译，勿在代码里展开产品名（见 CLAUDE.md §1.9）。
- **平台能力差异显式声明**：A5 独有路径（如 NDDMA、动态 UB Broadcast）在文档中已标注；命中 A5 而本目录
  未覆盖的能力，**如实声明未覆盖**，不套用 A2/A3 路径。
- **结构判据，不认算子名**：先按上表结构信号类目，再进参考；不得因"算子名叫 X"就套用某类目套路。
- **控制加载量**：一个子问题最多展开 3~5 篇 reference；不够就拆分子问题。
- **参考实现只是线索**：文档中的 API 片段/算子示例用于理解套路，不可不做设计判断直接照抄。
- **精度/同步细节归实现阶段**：Cast 写法、同步原语、API 参数等属于 Compute/codegen 阶段；具体 API 用法见
  `ascendc-dev-knowledge` / `ascendc-api-best-practices` 知识库。
