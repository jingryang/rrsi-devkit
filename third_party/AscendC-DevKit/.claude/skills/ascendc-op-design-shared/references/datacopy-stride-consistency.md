# DataCopyPad strided 搬运的行距一致性

> 详设阶段 strided `DataCopyPad`（`blockCount > 1` / 含 `srcStride`/`dstStride`）的
> **搬运行距一致性**不变式与尾块处理范式。被 `ascendc-op-tiling-buffer-kernel` /
> `ascendc-op-tiling-split`（详设）、
> `ascendc-op-dev-coding`（编码）、`ascendc-precision-diagnose`（debug）按需 Read。
>
> **相关模式**：B03_axis-param（轴参算子 generalized 路径）、尾块/非 32B 对齐行的 strided tile。

---

## 1. 核心不变式

> **搬运行距必须等于寻址行距。**

strided `DataCopyPad` 把多行数据搬进 UB tile 时，每行在 tile 中的物理间距由
`blockLen` 对齐 + `dstStride` 决定；后续 kernel 用「行索引 × 行步长」寻址读这些行。
两套行距只要不一致，行错位或越界必现——且**只在尾块/非 32B 对齐行上触发**（主块恒对齐、恒一致，测试常常测不出来）。

---

## 2. 根因机制（为什么只在尾块炸）

`DataCopyPad` 的 `DataCopyExtParams`：

| 字段 | 单位 | 语义 |
|------|------|------|
| `blockLen` | 字节 | 每行数据长度（GM 侧，支持非对齐） |
| `srcStride` | 字节（GM）/ dataBlock（UB） | 前一块尾与下一块头的间隔 |
| `dstStride` | 字节（GM）/ dataBlock（UB） | UB 侧行间隔；`0` = 行连续 |

**UB 侧（dst）行为**：当 `blockLen` 非 32B 倍数时，`DataCopyPad` 自动把每行补位到 32B 边界，
`dstStride=0` 时的实际行距 = `AlignUp(blockLen, 32)`。

于是「行距」随每行数据宽度变化：

```
主块（curChunkLen = B_chunk）：blockLen = 64B（已对齐）→ 行距 = 64B
尾块（curChunkLen = lastChunkLen）：blockLen = 2B（非对齐）→ 行距 = AlignUp(2,32) = 32B
```

**错位链条**：
1. 搬运侧按各自对齐长度排布（主块 64B / 尾块 32B 行距）；
2. kernel 却按**主块固定步长** `rowStrideElems_ = AlignUp(主块宽×s, 32)/s` 寻址读所有行；
3. 尾块行 j 实际被读到 `offset j×64B` 处 = 尾块物理行 `(j×64)/32 = 2j` → **错位 2 倍**；
   若错位读取超出 tile 范围 → 越界垃圾。

**判别证据**（cummin 实测）：
- 尾块 1 元素（bf16，2B→32B）vs 主块 32 元素（64B）：kernel row j 读 input row **2j**；
- 尾块 9 列（fp16，18B→32B）vs 主块 560 元素（1120B）：rows 1..16 全错（读越界垃圾）；
- 尾块补位后恰好与主块同为 32B 的用例（`AlignUp(尾宽×s,32) == AlignUp(主宽×s,32)`）**全部通过**——
  反证触发条件唯一性。

**触发条件**：`AlignUp(尾块宽 × sizeof(T), 32) != AlignUp(主块宽 × sizeof(T), 32)`。
主块与尾块对齐后行距不同即命中；相同则天然不触发。

---

## 3. 两种解法的取舍

### 方案一：统一按主块对齐行距搬运 + 寻址（推荐）

尾块行也写到主块行距的槽位上（`tile[j * rowStrideElems_]`），kernel 全程单一行距公式。

> **术语澄清（先分清两种"尾块"，搬运形态完全不同）**：
> - **列分块尾块**：同一行被切成多个列块，各块 GM 起址不连续
>   （块间 `srcStride=(B-块宽)×s`）且块宽互异 → 批量参数无法统一表达，才逐行循环；
> - **行分块尾块**（行不满一批，`curRows < multiNNum/batchRows`）：行的 GM 布局与主块
>   完全同构，**`blockCount` 本就是运行时变量，传 `curRows` 即可，仍是单条指令整块搬入**
>   **禁止把列分块尾块的逐行形态错误推广到行分块尾块/整 tile。**

```
CopyIn（列分块尾块）:  for j in [0, curRows):        // 仅列分块尾块需要逐行
                         DataCopyPad(tile[j * rowStrideElems_], gm + j*B,
                                     {blockCount:1, blockLen: curChunkLen*s})
CopyIn（主块/行分块尾块）: DataCopyPad(tile, gm, {blockCount:curRows, blockLen: 主块宽*s,
                                          srcStride:(B-主块宽)*s, dstStride:0})
                          // curRows 含行尾块场景（不满一批时 blockCount 自然变小，恒单条指令）
寻址（统一）:    row = tile[j * rowStrideElems_]        // rowStrideElems_ = AlignUp(主块宽*s,32)/s
```

- ✅ **单一寻址路径**，从结构上消灭"两套行距"这一类 bug
- ✅ CopyIn / CopyOut 共用同一 `rowStrideElems_`，天然对称（CopyOut 尾块分支同样
  `tile[j * rowStrideElems_]`）
- ⚠️ 代价：尾块行占用 = 主块行距（即使只有 2B 数据也占满 64B 槽）→ UB 略浪费。
  尾块通常仅最后一块、行数少，浪费可忽略
- ⚠️ 尾块行槽位的 gap 区（行距空洞）是未初始化区，kernel 不读即可，无害；
  但注意**初始化语义不干净**（非整块有效数据），不得对该区做任何读/规约

#### ⚠️ 逐行 `blockCount=1` 只适用于"列分块尾块"——禁推广到行分块尾块/整 tile 搬运

上例中逐行循环**仅用于列分块尾块**（同一行切成多个列块，块间 `srcStride=(B-块宽)×s`
非连续、块宽互异，批量参数表达不了变块长）。**行距均匀的行块搬运（主块、行分块尾块、
整 tile）必须一次批量完成**——行分块尾块（`curRows < 一批的行数`）的 GM 布局与主块
同构，`blockCount` 传运行时 `curRows` 即可，指令条数恒为 1。不得把列分块尾块的
逐行形态推广成默认 CopyIn/CopyOut 写法：

- **批量形态**（行块搬运默认，含主块/行分块尾块/整 tile）：`DataCopyPad(tile, gm,
  {blockCount:rows, blockLen: 行宽字节, srcStride: GM行间隔字节, dstStride: UB行间隔/32})`。
  GM→UB 时 GM 源行连续填 `srcStride=0`（字节单位）；UB 侧 `dstStride` 单位是
  dataBlock(32B)，行距按 256B 量子规划时恒整除；`rightPadding` 在 Normal 模式下
  **逐块生效**（每块独立补到 32B 槽），与逐行行为等价；`blockCount` 上限 4095
  （ubFactor 闭式解须 ≤4095，超限拆循环）。行分块尾块仅使 blockCount 从常量变
  `curRows`，形态与主块完全一致。
- **性能红线** MTE 微事务数是行级搬运的第一性能杀手，shape 越窄越致命。
### 方案二：各自按自己的对齐长度搬入 + 各自按自己的对齐长度寻址

```
CopyIn（尾块）:  DataCopyPad(tile, gm, {blockCount:curRows, blockLen: 尾块宽*s,
                                          srcStride:(B-尾块宽)*s, dstStride:0})
CopyIn（主块）:  同上（主块宽）
寻址（尾块）:    row = tile[j * tailRowStrideElems_]   // tailRowStrideElems_ = AlignUp(尾块宽*s,32)/s
寻址（主块）:    row = tile[j * rowStrideElems_]
```

- ✅ UB 最省（尾块行只占自己的对齐长度）
- ⚠️ **kernel 必须按块类型分支寻址**（主块 / 尾块两套 stride）→ 两条寻址路径 = 多一个出错点。
  当前 bug 的历史根因正是"搬运按方案二、寻址按方案一"的混搭
- ⚠️ 若选本方案，必须把"尾块寻址"写成独立函数、与 CopyOut 对称，并在 verifiable_claims
  记录"两套行距各配对称的搬运与寻址"

### 选择建议

**默认方案一**：单一寻址路径，天然消灭此类 bug。仅当尾块行数巨大、UB 紧张到必须省
行距空间时才考虑方案二（那种场景下先尝试增大 `B_chunk` 使尾块对齐，往往更简单）。

---

## 4. 编码落地对照（A2/A3 Membase）

| 环节 | 要求 |
|------|------|
| Buffer | 尾块行槽位按**主块行距**分配（方案一）→ Buffer 对齐后字节数 = `AlignUp(主块宽×s,32) × 行数`（整块） |
| CopyIn | 主块/行距均匀整 tile：**单条批量 strided**（`blockCount=rows`，GM 连续 `srcStride=0`，UB `dstStride=(行距−AlignUp32(块宽))/32`）；仅**尾块**（块间非连续/变块长）逐行 `blockCount=1` 写 `tile[j*rowStrideElems_]`。禁把逐行形态推广到整 tile 搬运（MTE 微事务性能红线，§3） |
| CopyOut | 与 CopyIn 同源寻址 `tile[j*rowStrideElems_]`（对称），批量/逐行形态与 CopyIn 一致 |
| 寻址 | `rowStrideElems_ = AlignUp(主块宽×s, 32) / s` 单一路径 |
| 注释 | 显式写明不变式 + 触发条件 + 判别证据，防回归 |

> A5 Regbase 差异：寄存器级 tile 布局的对齐/步长约束不同，见 `platform_diff.md` / `a5_regbase_design.md`；
> 本文不变式（搬运行距 == 寻址行距）对所有架构成立，落地形式随架构变化。

---

## 5. 自检判据（各阶段）

- **详设 buffer-kernel**：stride 伪代码是否同时给出了尾块分支？尾块行距与 kernel 寻址
  `rowStrideElems_` 是否一致（方案一：恒等；方案二：有独立的对称 `tailRowStrideElems_`）？
  是否满足 `AlignUp(尾宽×s,32) == AlignUp(主宽×s,32)` 的天然一致或显式分支？
- **详设 anchor**：涉及 strided DataCopyPad 行距的 claim 是否独立用本文 + DataCopyPad API
  文档复核？
- **编码**：落码前是否 Read 本文核对行距一致性？strided CopyIn/CopyOut 是否共用同一
  `rowStrideElems_`？
- **debug diagnose**：尾块列/行错位或越界（输出=错位行数据 / 越界垃圾）时，是否把
  "strided 行距不一致"列入候选根因？

---

## 6. 适用范围与限制

- **适用**：A2/A3（Membase）上使用 strided `DataCopyPad`（`blockCount>1` 或含 stride 字段）
  且存在非 32B 对齐行 / 尾块的算子。
- **不适用**：纯连续搬运（`blockCount=1`，无行距概念）；A5 Regbase 路径（布局约束不同，见 §4）。
- **姊妹易错点**：`ReduceSum` 最内层轴非 32B 对齐的补零范式见 `reduce_align_strategy.md`；
  `SetAtomicAdd` 不支持 dtype 的跨核汇总 fallback 见 `atomicadd_dtype_fallback.md`。

---

## 7. DataCopyPad 的 pad 语义（A5 跨步列块场景补充）

> 本节补 §1-6 未覆盖、但在 A5 Regbase 跨步列块（softmax 族 T2 等，`blockLen=rSize×s` 非对齐、
> `srcStride=(R−rSize)×s` 行首间隔）设计中反复需要核对的点。**§1 不变式对 A5 同样成立**；
> 本节是 A5 落地时的补充查证清单。

1. **pad 是搬运侧行为，行被补到 32B 边界**：`DataCopyPad` 搬行时把每行补位到 32B 倍数
   （UB 侧行槽 = `AlignUp(blockLen,32)`）。设计 Buffer 时**UB 行槽宽必须按 AlignUp 后的宽度分配**，
   不能按裸 `blockLen`。若 UB 预算/行距按 fp32-worst 规划（`rowBytes=AlignUp(colTileElem×4,32)`），
   `colTileElem` 取 8 的倍数时 `AlignUp` 恒等、零 slop。
2. **尾列块（rLastTileElem）**：把列块截断成 `rLastTileElem` 时，读侧 pad 通道数据**不参与计算**
   （计算只在 `[0,rLastTileElem)` 上跑，mask 兜住）；写回（CopyOut）只拷有效元素，不把 pad 写出。
   即"读侧 pad + 尾 mask 双保险"，pad 通道填安全值即可，不必担心污染输出。
3. **pad 填充值用 `SetPadValue` 控制**（950PR/950DT 支持 GM→VECIN/VECOUT 通路）。安全值按用途定：
   在线 softmax 累加器 pad 通道 `mRun=−inf / sRun=0`；逐元素选择链可填 0。
   文档锚点：`ascendc-dev-knowledge/references/910D_knowledge_extra/DataCopyPad(ISASI).md`、
   `SetPadValue(ISASI).md`。
4. **查证要点（写 verifiable_claims 时）**：`DataCopyPad` 支持通路 / `SetPadValue` 支持通路 /
   A5(950) 是否支持设置 mode——均需带锚点查证（agent 曾为"pad 是否让 UB slab 行按 32B 取整分配"
   反复查证；本节第 1 点即答案，不用重推）。
