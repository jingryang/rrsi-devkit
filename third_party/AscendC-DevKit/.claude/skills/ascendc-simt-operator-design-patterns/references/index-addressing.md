# 索引计算与地址合成

> SIMT 的核心开销是地址计算。两仓库贯穿始终的原则：**绝不在 VF 内用硬件除法**，全部换成 host 预计算的 magic/shift 快除；同时正确处理位宽、负索引、越界与 bank 冲突。

## 1. Magic Number 快除

```cpp
// host（__aicore__ 侧）预计算，kernel 免整数除法
GetUintDivMagicAndShift<DIV_T>(magic, shift, divisor);
// VF 内两种写法：
// ① Simt::UintDiv
uint32_t row = Simt::UintDiv(index, m, s);
uint32_t col = index - row * innerSize;   // 用乘减取代取模
// ② 手写 __umulhi（更快的内联形式）
uint32_t t1 = __umulhi(i, magic);
uint32_t numRows = (t1 + i) >> shift;
```

- 出处：`conversion/as_strided/op_kernel/arch35/as_strided_simt.h`、`concat`、`view_copy`
- **反例**：`add_row_ranges` 注释记录 magic number 在大下标时溢出，改回原生除法 `idx / N`——大索引场景注意快除的位数限制。

## 2. 索引位宽双轨（int32/int64）

偏移 ≤ INT32_MAX 用 int32 索引（寄存器压力小、1024 线程）；超限切 int64 + 512 线程。判定标准不只是总量，还有**中间乘积**（如 `shape[i]*stride[i]`、`isize*osize`）：

```cpp
// 非连续布局必须用 shape*stride 判断（最大地址由 stride 决定）
bool enableInt64 = false;
for (i in dims) { if (shape[i] * stride[i] > INT32_MAX) { enableInt64 = true; } }
// pooling：StartIndex 公式里的 outIdx*inLen 中间量
bool NeedInt64(int64_t isize, int64_t osize) { return isize * osize > INT32_MAX; }
// 分发：if (maxOffset <= INT32_MAX) { asc_vf_call<Kernel<T, uint32_t>>(...); }
//        else { asc_vf_call<Kernel<T, uint64_t>>(...); }
```

- 出处：`index/embedding_no_contiguous`、`pooling/adaptive_avg_pool2d_grad`、`math/prod_force_se_a`

## 3. 坐标分解链：按内存布局选轴序

原则"相邻线程处理相邻 GM 地址"：**最内维先除，寄存器链最短**。

```cpp
// NHWC：最内维 C 先除（c = idx % C）
int32_t c  = idx - Simt::UintDiv(idx, magicC, shiftC) * C;
int32_t r  = Simt::UintDiv(idx, magicC, shiftC);
// NCHW：从 W 开始（w 最内）
// 高维（≥5）用 GET_TILING_DATA_PTR_WITH_STRUCT 从 GM 读 tiling（见 vf-programming.md）
```

- 出处：`pooling/dilation2_d/op_kernel/arch35/dilation2_d_simt.h`、`conversion/im2col`（6 维四/五级 UintDiv 链）

## 4. 负索引回绕与越界处理（三形态）

```cpp
// 形态 1：模板参 NIS 编译期消除（gather_v2/gather_nd，无负索引场景零开销）
if constexpr (NIS) { if (unlikely(indicesValue < 0)) { indicesValue += gatherDimSize; } }
bool outOfBound = indicesValue < 0 || indicesValue >= gatherDimSize;
y[yIndex] = outOfBound ? 0 : x[xIndex];              // 越界填 0

// 形态 2：((v % n) + n) % n 归一化（linear_index_v2 / inplace_sub）
((indexValue % valueSize + valueSize) % valueSize) * stride

// 形态 3：越界 skip（scatter/segment/优化器）
if (idx < 0 || idx >= varRows) continue;             // 非法索引静默跳过
```

## 5. 前缀和 / 偏移表定位（不规则结构）

不等长结构（tensor-list、稀疏、掩码）用**前缀和定位**而非逐元素计算：

```cpp
// 扁平 index → 线性扫 cumOffsets 定位 tensor（tensor 数 ≤256 可接受）
while (flatIdx >= cumulativeOffsets[t]) t++;
localIdx = flatIdx - (t > 0 ? cumulativeOffsets[t - 1] : 0);
// 块内前缀和 + 跨块归约定位（sparse_slice / masked_scatter / unique_dim 公共骨架）
SimtComputePrefixSum<int64_t>(tmpValNum);   // Hillis-Steele 双缓冲
```

- 出处：`foreach/foreach_erfc`、`index/sparse_slice/op_kernel/arch35/sparse_slice_simt_local.h`

## 6. Bank 冲突规避

向量 gather/连续跨步访问时会反复命中同一 bank 组：

```cpp
// 行跨距为 4×32B 整数倍时反复命中同一 bank 组 → 加一个 block 的 padding 旋转行起始地址
if (rowBytes % (4 * blockBytes) == 0U) { rowBytes += blockBytes; }
// gather 全载模板：对齐后恰为 256B/128B 时额外加一个 ubBlock 规避 bank 冲突
if (aSizeAligned == 256 || aSizeAligned == 128) { aSizeAligned += ubBlockSize; }
```

- 出处：`math/sort/op_host/arch35/sort_tiling_arch35.cpp`（AddBankRotationPadding）、`index/gather_v2`（IsGaAllLoad）

## 7. 特殊寻址技巧

| 技巧 | 写法 | 算子 |
|------|------|------|
| 对角寻址 | `idx*(N+1)` 一式无除法 | trace、diag_part、matrix_diag |
| 连续段折叠 | `dstSize[i+1]*dstStride[i+1]==dstStride[i]` 判断连续 | view_copy |
| 广播 stride 置 0 | 广播维 stride=0，坐标累加自动复用首元素 | polar、cross、lars |
| 线性地址累加 | 多张量索引分别乘 stride 累加进 UB 输出 | linear_index_v2 |
| `asc_ldcg/stcg` | 绕 L1 cache 的 GM 读写（随机读带宽） | histogram、coalesce_sparse |
