# 实际算子 → 模板判定示例

> 用实际算子的真实算法逻辑演示"结构特征 → SIMT 适用场景排查 → 纯 SIMT / MIXED / SIMD"的判定链。
> **判定依据是算子的结构特征（访问模式/控制流/数据规模/原子写/确定性），算子名仅用于对照真实案例**，禁止按算子名匹配分类。
> **默认选择 = SIMD**：先排查是否命中 SIMT 适用场景（有限特例集），未命中即 SIMD。SIMT 适用场景即"每线程一个独立小任务"型算子（索引收集/读语义、逐元素标量函数计算、窗口独立规约、坐标驱动采样）——本文件**仅罗列这些命中 SIMT 适用场景的示例**，以及索引写/归约语义（不命中 SIMT 特例 → SIMD）的边界说明。
> 规则编号对应 `selection_strategy.md`；输出字段对应 `schema/template_decision.json`。

---

## 示例 1：索引读语义收集型（embedding / gather 查表类）→ SIMT 特例①

**实际算法**：`output[...] = weights[indices[...]]` 或 `output[i] = src[indices[i]]`——用索引张量做下标，从源张量随机收集元素/行（查表）。

**结构特征分析**：访问地址由索引值驱动（`indices` 的值决定取哪个位置），不可静态推导；行内连续但行间随机。**读语义**：index 重复只是多线程读同一地址，读不产生冲突，结果确定 → 命中 R-01（读语义）SIMT 特例。数据规模小（查表总量 < 阈值），无大块连续搬运 → **纯 SIMT**。

| 维度 | finding | rule_id | verdict | 确定性 |
|---|---|---|---|---|
| access_pattern | 索引张量驱动随机寻址（**读语义**，index 重复无害） | R-01 | simt | 确定性（读不冲突） |
| deterministic | 默认确定性；无跨线程规约/原子写，确定性允许 SIMT（单线程内顺序累加仍确定） | R-05 | simt | 确定性 |
| data_scale | 查表总量 < 阈值（如 2048） | R-03 | simt | 确定性 |

**推荐模板**：SIMT（实际实现：embedding 的 two_dim / no_contiguous 路径、gather_v2 小数据路径均用 SIMT 模板；`SIMD_THRES` 低于阈值全部走 SIMT）

---

## 示例 2：索引写/归约语义型（scatter_add / unsorted_segment_sum 类）→ 不命中 SIMT 特例 → SIMD（默认选择）

**实际算法**：
- scatter_add：`var[indices[i], :] += updates[i, :]`——按索引把 updates 累加到 var 指定行，不同索引可能命中同一行
- unsorted_segment_sum：`output[segment_id[i]] += data[i, :]`——按 segment_id 分组累加，segment 长度不均、id 顺序任意

**结构特征分析**（两者共享同一结构特征，仅是索引维度不同）：
- 索引驱动寻址 + 多线程写同一地址（原子加）→ R-04 倾向 SIMT（仅性能）；
- **写/归约语义**：index 重复 → 多线程写同一地址，原子加**只保证原子性，不保证顺序** → 浮点原子累加顺序随调度变化，bit-exact 不可复现；
- **不命中 SIMT 适用场景**：R-01 的 SIMT 特例**仅对读语义成立**，写/归约语义不作 SIMT 优先策略（确定性默认走 SIMD deterministic）；
- **算子默认确定性** → 浮点原子路径不能作为确定性默认路径。

| 维度 | finding | rule_id | verdict | 确定性 |
|---|---|---|---|---|
| access_pattern | 索引驱动寻址（**写/归约语义**，index 重复 → 写冲突，原子不保证顺序） | R-01 | simd | 确定性（默认） |
| atomic_write | 多线程写同一地址（原子加，不保证顺序）——默认确定性下被 R-05 覆盖，该维度不产生模板倾向 | R-04 | unknown | 确定性（默认） |
| deterministic | 默认确定性；涉及多线程写同一地址（原子写/跨线程归并），SIMT 的跨线程规约/写数据被确定性禁止 → 只能 SIMD | R-05 | simd | 确定性 |
| data_scale | 尾维/内维 × dtype 小（< 阈值） | R-03 | simt | **非确定性（仅兜底）** |
| data_scale | 尾维/内维 × dtype 大（≥ 16KB，大块连续搬运） | — | simd | 确定性（默认） |

**推荐模板**：**SIMD（默认选择）**——**索引写/归约语义不命中 SIMT 特例**，确定性默认走 SIMD deterministic（实际实现：scatter_add 的 `ScatterAddDeterministicImpl`、unsorted_segment_sum 的 `KernelUSSDeterministic`——先 `Sort` 排序 indices，把同一目标地址的 updates 规整为连续段，再按固定顺序累加/量化计数）；**仅当输入明确允许非确定性时**，才按 `尾维/内维 × dtype < 阈值` 路由输出非确定性方案——尾维小走 SIMT 原子路径，尾维大走 SIMD 批量路径

> 冲突仲裁：R-01（写语义动态寻址）与 R-04（原子写）均倾向 SIMT，但 R-05（默认确定性）覆盖两者——**确定性为硬性语义要求，SIMT 原子路径仅限非确定性模式**。这也是"原子写不保证顺序"的必然推论：`R-04 倾向 SIMT` 在这里是"性能最高但结果不确定"，`R-05 倾向 SIMD` 是"结果确定"，默认优先确定性。**本示例是"未命中 SIMT 适用场景 → SIMD（默认选择）"的边界说明**。

---

## 示例 3：小数据量元素独立重排型（reverse_v2 尾维小时）→ SIMT 特例②

**实际算法**：`output[...] = input[反转后的索引]`——按指定轴翻转元素顺序，跨轴重排。

**结构特征分析**：无索引张量（地址可推导），但**元素独立**（每个输出来自一个对应输入位置，零耦合）；末维数据量小时向量化启动/搬运开销大于收益；无大块连续搬运 → **纯 SIMT**。

| 维度 | finding | rule_id | verdict | 确定性 |
|---|---|---|---|---|
| element_dependency | 元素独立（每输出 1:1 取数，重排搬运无累加） | C-02 不命中 | unknown | 确定性 |
| deterministic | 默认确定性；无跨线程规约/原子写，确定性允许 SIMT | R-05 | simt | 确定性 |
| data_scale | 末维 × dtype < 128B | R-03 | simt | 确定性 |

**推荐模板**：SIMT（实际实现：`isSimd_ = false` 当 `末维 × dtypeSize < SIMD_THRESHOLD(128)`；此时所有维度组合走 SIMT）

---

## 示例 4：二分查找型（bucketize_v2）→ 命中 SIMT 特例（R-02）+ 大块连续搬运 → MIXED

**实际算法**：对每个 `x[i]` 在排序好的 `boundaries` 中二分查找所属区间，`output[i] = 区间号`。

**结构特征分析**：逐元素比较查找（无索引张量、地址连续）；**元素独立**（每个输出只依赖一次查找结果，零耦合）；每个元素独立判定（数据相关分支，命中 R-02 SIMT 特例）——**SIMT 是主路径**；同时输入数据是连续大块，单次搬运可能 ≥ 16KB，**可向量化大块连续搬运** → 数据量大时 SIMD 并存。

| 维度 | finding | rule_id | verdict | 确定性 |
|---|---|---|---|---|
| element_dependency | 元素独立（逐元素查找，无跨元素累加） | C-02 不命中 | unknown | 确定性 |
| deterministic | 默认确定性；无跨线程规约/原子写，确定性允许 SIMT | R-05 | simt | 确定性 |
| control_flow | 二分查找含数据相关分支 | R-02 | simt | 确定性 |
| data_scale | 大块连续数据（≥16KB，大块连续搬运） | — | simd | 确定性 |

**推荐模板**：MIXED——**SIMT 特例路径（主路径）** + **SIMD 大块路径（数据规模 ≥ 16KB 时可向量化）**（实际实现：FULL_LOAD / CASCADE 模板处理大块，SIMT 模板处理中小数据与 int64 边界）

> **纯 SIMT vs MIXED 的边界**：命中 SIMT 适用场景后，若数据存在**大块连续内存搬运**（如单次 ≥ 16KB、可向量化规整）→ MIXED（SIMT 特例路径 + SIMD 大块路径并存，按 shape 互斥路由）；**无大块连续搬运** → 纯 SIMT。SIMD 大块路径用于搬运量足够大、向量化划算的形状；SIMT 路径用于中小数据 / 数据相关分支主导的形状。

---

## 示例 5：逐元素标量函数计算型（threshold 类）→ SIMT 特例③（按数据规模裁决纯 SIMT / MIXED）

**实际算法**：`y[i] = (x[i] > threshold) ? 1.0 : 0.0`——逐元素比较/标量函数，输出与输入一一对应，无索引张量。

**结构特征分析**：无索引张量、地址连续；计算是**标量函数/比较**（A5 SIMT 的 Thread 即单元素处理单元，天然贴合，命中 R-06 SIMT 特例）；元素独立（每输出 = f(单输入)），C-02 不命中。**数据规模决定最终模板**：
- **中小数据**（无大块连续搬运）：SIMD 向量化需先搬运到 UB、配对、再向量函数，启动开销大于收益 → **纯 SIMT**；
- **中大数据**（存在大块连续搬运，单次 ≥ 16KB 可向量化规整）：SIMD 大块路径为性能路径，SIMT 特例路径兜底中小数据/广播 strided → **MIXED**。

| 维度 | finding | rule_id | verdict | 确定性 |
|---|---|---|---|---|
| platform | A5 代 950 系列支持 SIMT & SIMD（能力放行，不产生模板倾向） | C-01 | unknown | 确定性 |
| element_dependency | 元素独立（每输出依赖 ≤1 个输入，标量函数计算） | C-02 不命中 | unknown | 确定性 |
| deterministic | 默认确定性；无跨线程规约/原子写，确定性允许 SIMT | R-05 | simt | 确定性 |
| computation_mode | 元素独立 + 标量函数计算（R-06 SIMT 特例，恒命中） | **R-06** | simt | 确定性 |
| data_scale | 中小数据 → 无大块连续搬运 | R-03 | simt | 确定性 |
| data_scale | 中大数据 → 大块连续搬运（≥16KB 可向量化） | — | simd | 确定性 |

**推荐模板**：
- **中小数据** → **SIMT**（实际实现：threshold 的 arch35 kernel 为纯 SIMT——`__simt_vf__` grid-stride loop，每线程一个元素做比较；erfinv / foreach 系列同模式）
- **中大数据** → **MIXED**（SIMD 大块路径——规整连续大块可向量化，性能路径 + SIMT 特例路径——中小数据/广播 strided 兜底，按 shape 互斥路由）

> `computation_mode` 命中 R-06 恒记 `simt`（SIMT 特例始终成立，因为计算型 SIMT 每线程算一个元素天然贴合标量函数）；**数据规模决定最终是纯 SIMT 还是 MIXED**——无大块连续搬运 → 纯 SIMT；有大块连续搬运 → MIXED（SIMD 大块路径 + SIMT 特例路径）。这是"**计算型** SIMT"（每线程算一个元素），区别于索引收集的"搬运型" SIMT。
---

## 示例 6：窗口独立规约型（avg_pool 窗口平均类）→ 命中 SIMT 特例 + 大块连续搬运 → MIXED

**实际算法**：`y[n,c,oh,ow] = mean(窗口内 K 个元素)`——滑动窗口内浮点求和再平均，窗口边界由 padding/stride 运行期计算。

**结构特征分析**：无索引张量；每个输出 = 窗口内 K 个元素的**局部浮点规约**；**规约完全在单线程内完成**（窗口循环累加），结果不经跨线程树形/原子归并 → **累加序固定，bit-exact 可复现**（确定性，C-02 不命中）；窗口边界（padding/stride）运行期计算，循环边界数据相关（命中 R-02 SIMT 特例）——**SIMT 是保障任何 shape 都能算的路径**；同时规整窗口/连续大块（stride 连续、kernel 适中、能按块搬入 UB）存在**大块连续内存搬运** → SIMD 并存。

| 维度 | finding | rule_id | verdict | 确定性 |
|---|---|---|---|---|
| element_dependency | 窗口内 N→1 浮点规约，但**单线程内完成**（归并不跨线程） | **C-02 不命中** | unknown | 确定性 |
| deterministic | 默认确定性；窗口内累加序固定（单线程内），确定性允许 SIMT | R-05 | simt | 确定性 |
| control_flow | 窗口边界随 padding/stride 动态计算 | R-02 | simt | 确定性 |
| data_scale | 大窗口/大块连续数据（大块连续搬运） | — | simd | 确定性 |

**推荐模板**：MIXED——**SIMT 特例路径（无条件可用，任何 shape 都能算）** + **SIMD 大块路径（优先，性能路径）**（实际实现：arch35 下 SIMD 小 kernel / 大 kernel 模板各有 `IsCapable()` 约束，**满足时优先走 SIMD**——性能路径；`PoolSimtTiling::IsCapable() = true` **无条件可用**——当 SIMD 模板因 shape/format/UB 约束不满足（如 kernel 过大、stride 离散、特殊 format、缓冲放不下）时**走 SIMT**，每线程独立完成窗口求和）

> **SIMD 大块路径的使用场景**：窗口规整、stride 连续、kernel 大小适中、输入能按块搬入 UB 做向量化（SIMD 小/大 kernel 模板 `IsCapable()` 满足）→ 批量向量化求和，吞吐高；**单次搬运量 ≥ 16KB** 时向量化收益明显。
> **SIMT 特例路径的使用场景**：窗口/stride 形状让 SIMD 模板不可用（大 kernel、离散 stride、UB 放不下整块）→ 每线程独立算一个输出窗口，直接读 GM 求窗口和，**灵活、任何 shape 都能算**。
>
> 两者结果都确定性（窗口内求和顺序固定于单线程），区别仅在**性能**：SIMD 是优先的性能路径（大块连续搬运时启用），SIMT 是保证任何 shape 都能算的路径（无大块连续搬运或 SIMD 约束不满足时启用）。
>
> **C-02 判的是"归并是否跨线程"**：本例每个线程独立完成窗口全部求和，累加序确定，C-02 不命中。**对比**：若同一行/同一段的规约需多个线程的部分和合并（如 norm 类跨线程平方和），则命中 C-02 强制 SIMD。

---

## 示例 7：坐标驱动采样型（deformable_offsets 类）→ SIMT 特例④

**实际算法**：`y[输出点] = Σ_k BilinearSample(x, 采样坐标(offset)) × w`——按运行期计算的采样坐标对输入做双线性插值并加权。

**结构特征分析**：**无索引张量**；采样地址由**运行期计算的坐标**（stride/dilation/pad 与 offset 数据组合）决定，离散非连续、跨行跨列，命中 R-01（运行期动态寻址）SIMT 特例；双线性插值涉及 4 邻点采样 + 加权和（局部耦合，但加权和在单线程内完成）；每个输出依赖的输入范围局部且形状可变，向量化难静态规划搬运；**寻址离散、无大块连续搬运** → **纯 SIMT**。

| 维度 | finding | rule_id | verdict | 确定性 |
|---|---|---|---|---|
| element_dependency | 每输出依赖 4 邻点加权和（局部耦合），加权和在单线程内完成 | C-02 不命中 | unknown | 确定性 |
| deterministic | 默认确定性；加权和在单线程内完成，无跨线程规约，确定性允许 SIMT | R-05 | simt | 确定性 |
| access_pattern | 运行期动态寻址（坐标计算驱动，非索引张量） | **R-01** | simt | 确定性 |
| control_flow | 采样边界 clamp / 越界分支 | R-02 | simt | 确定性 |

**推荐模板**：SIMT（实际实现：deformable_offsets 的 arch35 kernel 为纯 SIMT；psroi_pooling_v2 同模式；multi_scale_deformable_attn 按通道数路由为 MIXED——通道 < 64 走 SIMT，通道 ≥ 64 走 SIMD）

> **R-01 已泛化为"运行期动态寻址"**：地址由索引张量驱动（index 类）或坐标公式运行期计算（采样类）均命中，不再限定"必须有 index 张量"。
> **MIXED 说明**：multi_scale_deformable_attn 在通道 ≥ 64 时走 SIMD——此时通道维连续、存在大块连续内存搬运（可向量化），属"命中 SIMT 特例 + 大块连续搬运 → MIXED"的实例。

---

## 示例 8：张量/向量级批量算术型（addcdiv 类，三输入逐元素）→ R-07 → 纯 SIMD / MIXED

**实际算法**：`y[k] = x1[k] + (x2[k] / x3[k]) * scalar`——三输入逐元素算术运算，对整个张量做批量算术（四则复合），无索引张量，输入可为 TensorList（L=1~64）。

**结构特征分析**：无索引张量、地址连续；计算是**张量/向量级批量算术**（对整个张量做逐元素四则运算，天然可向量化为 SIMD 批量指令，计算单元是整张量/向量**非单个标量**）→ 走 R-07（子类⑥），**不命中** R-06（标量形态）；元素独立（每输出 = f(三输入对应位置)），C-02 不命中。**SIMD 为主路径**：SIMD 全覆盖（规整连续大块）→ 纯 SIMD；存在 SIMD 覆盖不到的 shape 子集（中小数据 / 广播 strided / 多张量大小不一 / SIMD 约束不满足）→ SIMT 兜底 → **MIXED**。

| 维度 | finding | rule_id | verdict | 确定性 |
|---|---|---|---|---|
| platform | A5 代 950 系列支持 SIMT & SIMD（能力放行，不产生模板倾向） | C-01 | unknown | 确定性 |
| element_dependency | 元素独立（每输出依赖对应位置输入，算术运算在单线程内完成） | C-02 不命中 | unknown | 确定性 |
| deterministic | 默认确定性；无跨线程规约/原子写，确定性允许 SIMT | R-05 | simt | 确定性 |
| computation_mode | 张量/向量级批量算术（逐元素四则运算，天然可向量化），非标量形态 | **R-07** | **mixed**（存在 SIMD 覆盖不到的 shape 子集时） | 确定性 |
| data_scale | 单元素张量 numel 大（1~64M），大块连续搬运存在（≥16KB 可向量化） | — | simd | 确定性 |

**推荐模板**：
- **SIMD 全覆盖（规整连续大块，无广播/TensorList 大小不一）** → **SIMD**（默认选择）
- **存在 SIMD 覆盖不到的 shape 子集**（本算子 TensorList L=1~64 成员大小不一 + 可能广播）→ **MIXED**（**SIMD 大块路径（性能路径，优先级高）** + **SIMT 兜底路径（中小数据 / 广播 strided 访存）**，按 shape 互斥路由）

> **R-07 与 R-06 的区分**：本例计算是三输入逐元素**四则复合算术**（`+` `/` `*`），计算单元是整张量/向量，天然可向量化 → R-07（子类⑥）。对比「示例 5」threshold 的 `y[i]=x[i]>t?1:0`，计算单元是**单个标量比较**，每线程算一个标量 → R-06（子类③）。二者互斥，不重叠。
> **R-07 与 R-06 的对称化**：R-06（标量形态）主路径 SIMT，数据规模大才配 SIMD；R-07（向量/张量级）主路径 SIMD，存在 SIMD 覆盖不到的 shape 子集才配 SIMT 兜底——两条规则方向对称（主路径恒定，兜底按需）。

---

## 附：示例产物（template_decision.json 片段，对应示例 1）

```json
{
  "operator_id": "output[batch,seq] = weights[indices[batch,seq],:]（查表收集型）",
  "platform": "950PR",
  "recommendation": "SIMT",
  "confidence": "high",
  "decisions": [
    {
      "dimension": "access_pattern",
      "finding": "索引张量驱动随机寻址（查表）",
      "rule_id": "R-01",
      "verdict": "simt"
    }
  ]
}
```
