# 核内共享内存与 Buffer 复用

> 类似 CUDA 的 shared_memory，SIMT 核内多线程之间交换数据使用 UB buffer（`__ubuf__` 指针）。本节补充实际算子的生命周期复用技巧。

## 1. 基本用法（TBuf + __ubuf__）

```cpp
// 1. kernel 中申请 buffer
TBuf<QuePosition::VECCALC> sharedBuf_;
pipe_->InitBuffer(sharedBuf_, 2048);                       // 2048 字节
// 2. 获取数据指针
LocalTensor<uint32_t> sharedTensor = sharedBuf_.Get<uint32_t>();
__ubuf__ uint32_t* sharedUbPtr = (__ubuf__ uint32_t*)sharedTensor.GetPhyAddr();
// 3. 传入 SIMT VF
Simt::VF_CALL<OpSimt<T>>(Simt::Dim3(THREAD_NUM), ..., sharedUbPtr);
```

- 注意：同地址并发写必须用原子操作；buffer 大小受 UB 可用空间限制；tiling 侧用 `SetDynUBufSize` 预留（Dynamic Unified Buffer，默认 0 = 不声明；`SetLocalMemorySize` 为同函数废弃名，主线仓 arch35 仍大量用旧名——生成代码用新名，见 workspace-contract §3）。

## 2. 三处共享 buffer 的典型用途

| 用途 | 写法 | 代表算子 |
|------|------|---------|
| 参数打包 | magic/shift/shape/stride 写入 UB，传 `__ubuf__` 指针，避免 VF 参数过多 | pooling（14 个 magic）、strided_slice_grad |
| 线程间数据交换 | 每个线程写自己槽位，syncthreads 后读别人槽位 | segment_sum（uniquePos）、hash（insertCounts） |
| 跨 warp 归约缓冲 | lane0 写 warp 和，syncthreads 后 warp0 归约 | trace（warpBuf） |

```cpp
// 线程槽位 + 归约（nll_loss：每线程私有槽天然无冲突）
int64_t ubIdx = (i % (blockNums_ * blockDim.x)) % THREAD_DIM;
tmpOut_[ubIdx] -= weight[target] * x[i * C + target];
asc_syncthreads();
SimtComputeBinaryReduction(tmpOut_, tmpWeight_);   // UB 内二叉树归约
```

## 3. UB buffer 生命周期别名复用（压 UB 峰值）

多个缓冲按生命周期刻意别名，host 侧 UB 估算按同一别名规则计算——**关键设计**：

```cpp
// sort 小轴：finalValues_ 直接别名 inputValues_（阶段1 后输入不再被读）
finalValues_ = inputValues_;
// 非 rank-inverse 路径：finalIdxBuf_ 先当 uint16 的 stage2KeysIn_，后复用为 uint32 gather 偏移
stage2KeysIn_ = finalIdxBuf_.template Get<uint16_t>();
stage2KeysOut_ = rankInverseBuf_.template Get<uint16_t>();
// 两阶段峰值取 max：排序阶段 vs 索引转置阶段
peakUb = std::max(sortPhaseUb, sortedIndexBytes + outputIndexBytes);
```

- 出处：`math/sort/op_kernel/arch35/common/small_axis_two_stage_base.h`、`sort_tiling_arch35.cpp`

## 4. UB 私有副本（直方图/私有化散写）

每核分配整幅输出副本，散写打 UB（原子在核内 SRAM 解决、不与他核共享 cache line），轮末一次性折叠回 GM：

```cpp
LocalTensor<float> histogram = histogramQueue.template AllocTensor<float>();
Duplicate(histogram, 0.0F, privateHistElems);
LaunchScatter<..., true, ...>(..., (__ubuf__ float*)histogram.GetPhyAddr(), ...);
histogramQueue.EnQue(histogram); histogramQueue.template DeQue<float>();
if constexpr (BINARY_OUTPUT) { SetAtomicMax<float>(); } else { SetAtomicAdd<float>(); }
DataCopyPad(outputGlobal, histogram, copyParams);   // 一次性折叠回 GM
SetAtomicNone();
```

- 出处：`math/ragged_bin_count/op_kernel/arch35/ragged_bin_count_simt.h`（私有化散写）
- 决策条件：输出能装进 UB 且回写流量 `outputElements*coreNum ≤ numValues*8`；更多冲突处理档位见深度策略库 `kimi_simt_strategy.md` 第四章 K1-K3（UB 私有直方图三档）与第八章（冲突谱系）。

## 5. 注意事项

- SIMT 线程直接访 GM 依赖 DCache，UB 里给 buffer 的空间必须从 `ubSize - DCACHE_SIZE` 里分配，两者必须一致（host 私有化决策与 device TPipe 分配用同一个数）；host 侧用 `context->SetDynUBufSize(ubSize - DCACHE_SIZE)` 声明该预算（见 workspace-contract §3）。
- buffer 别名时，host 侧 `CalcUBTotalSize` 与 kernel 侧 `InitBuffer` 必须**逐项对称**，任何一侧多算/漏算都会 UB 溢出。
- VF 内写 UB 数据给后续 DMA 用时，需 `SetFlag/WaitFlag<HardEvent::V_MTE3>` 保证产出完成再搬。
