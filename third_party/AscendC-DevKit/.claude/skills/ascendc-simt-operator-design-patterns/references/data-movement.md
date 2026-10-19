# 数据搬运选型

> SIMT 支持直接读写 GM，这是与 SIMD 的最大差异。但"什么时候直接读 GM、什么时候 UB 中转、什么时候与 DMA 混合"需要按访存形态决策。

## 选型决策流

```cpp
if (逐元素无依赖 或 访存离散不规则)    use = GM_DIRECT;          // 直接 __gm__ 读写
else if (需要核内线程间共享数据)       use = UB_MIDDLE;          // TBuf + __ubuf__ 指针
else if (多次访问同一数据)             use = UB_CACHE;           // 复用延迟低于 GM
else if (一侧连续一侧离散)             use = DMA + SIMT 混合;    // 连续侧 DataCopyPad，离散侧 SIMT
else if (输出需连续落盘)               use = SIMT 写 UB + DMA 搬出;
```

## 1. GM 直读（默认，简单场景）

```cpp
// 逐元素操作，无依赖——避免不必要的 UB 搬运
__simt_vf__ LAUNCH_BOUND(512) inline void OpSimt(uint64_t count, __gm__ float* x, __gm__ float* y) {
    for (i = ...; i < count; i += step) { y[i] = x[i] + 1.0f; }   // 直接读写 GM
}
```

- 出处：`activation/threshold/op_kernel/arch35/threshold_simt.h`

## 2. UB 中转（核内共享 / 延迟优化）

```cpp
// tiling 侧：SetDynUBufSize 声明 Dynamic Unified Buffer（先扣 DCache；SetLocalMemorySize 为废弃同名，
// 主线仓 arch35 仍大量用旧名，语义一致——生成代码用新名，见 workspace-contract §3）
context->SetDynUBufSize(ubSize - DCACHE_SIZE);
// kernel 侧：TBuf 声明 buffer，取 __ubuf__ 指针传 VF
TBuf<QuePosition::VECCALC> sharedBuf_;
pipe_->InitBuffer(sharedBuf_, 2048);
LocalTensor<uint32_t> sharedTensor = sharedBuf_.Get<uint32_t>();
Simt::VF_CALL<OpSimt<T>>(Simt::Dim3(THREAD_NUM), ..., (__ubuf__ uint32_t*)sharedTensor.GetPhyAddr());
```

- 出处：`index/gather_nd`（indices 搬 UB）、`embedding_no_contiguous`（两遍协作）、`pooling`（magic 参数打包 UB）

## 3. 连续侧 DMA + 离散侧 SIMT（访存不对称场景）

```cpp
// view_copy：源视图连续段走 ND-DMA/MoveAlign 进 UB（保证读带宽），写侧因 dst stride 不规则由 SIMT 散写
for (uint32_t i = threadIdx.x; i < batchSize; i += blockDim.x) {
    // __umulhi 分解 UB 内坐标，同时累加 srcIndex（UB 连续）与 dstIndex（GM 散列）
    dst[dstIndex] = src[srcIndex];
}
// strided_slice_grad：dy 连续读入 UB，SIMT 按 begin/stride 散写回 GM
// batch_to_space_nd：SIMT 写 UB（离散读）→ DataCopyPad 整块写 GM（连续写）
```

- 出处：`conversion/view_copy/op_kernel/arch35/view_copy_simt_dim3.h`、`strided_slice_grad/copy_out_simt.h`、`batch_to_space_nd`

## 4. 原子 DMA 归约（随机写 + 连续折叠）

```cpp
// SIMT 把随机写打进 UB 私有副本，轮末用 SetAtomicAdd + DataCopyPad 整块原子折叠进 GM
asc_vf_call<UbSimtComputeWsReduce>(dim3{THREAD_NUM}, xGmAddr, yLocalAddr, ...);  // SIMT: UB 原子
SetAtomicAdd<int32_t>();
DataCopyPad(this->yGm_, yLocal, copyParams);   // vector: DMA 原子加（每核一次连续原子）
SetAtomicNone();
```

- 出处：`math/histogram_fixed_width/op_kernel/arch35/histogram_fixed_width_simt_full_load.h`
- 注意：`SetAtomicAdd<T>` 硬件只支持部分 dtype（int32 等）；int64 需 SIMT `asc_atomic_add`，fp16 需 fp32 workspace 中转。

## 5. 低比特 dtype 的 workspace 三段式

无原子指令/无高精度累加的 dtype（int8/uint8/int16/fp16）：

```cpp
CopyVarToWs(var, ws, /*castTo*/int32);   // 阶段1: 整 var cast 到 int32/fp32 workspace
SyncAll();
Compute<int32>(ws, ...);                 // 阶段2: workspace 上原子加（高精度）
SyncAll();
CopyWsToVar(ws, var);                    // 阶段3: Cast 回原 dtype
```

- 出处：`index/scatter_add/op_kernel/arch35/scatter_add_simt.h`（int8）、`inplace_index_add`、`matmul/sparse_tensor_dense_mat_mul`（B16 用 fp32 workspace + SIMD Cast 回写）

## 6. 特殊内存访问优化

| 技巧 | 说明 | 出处 |
|------|------|------|
| `asc_ldcg/asc_stcg` | 绕 L1 cache 的 GM 读写，随机读带宽榨取 | histogram_fixed_width（6 路展开 + ldcg）、coalesce_sparse |
| `__gm__ volatile` | 防编译器重排（DCache 脏数据保护） | max_pool_v3_grad、pad_grad |
| 循环展开 | 连续多次 `asc_ldcg` 再连续多次写，交叠加载延迟与计算 | histogram（UNROLL_FACTOR=6）、sort 两阶段（8 路） |

## 注意事项

- UB 中转前必须 `DataSyncBarrier<MemDsbT::UB>()` 保证标量写对 VF 可见。
- TQue（AllocTensor/EnQue/DeQue）双缓冲流水化时，用 `SetFlag/WaitFlag<HardEvent::S_V / MTE3_V>` 做时序。
- 选择方案时把"读写两侧的访存形态"列出来：两侧连续→DMA；两侧离散→SIMT 直读；一连续一离散→混合。
