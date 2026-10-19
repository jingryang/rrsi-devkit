# 同步与原子操作谱系

## 1. 同步原语全景

| 原语 | 粒度 | 用途 | 前提 |
|------|------|------|------|
| `asc_syncthreads()` | 核内（block 内） | VF 内线程间同步 | 需配合 CUDA 风格 threadIdx |
| `AscendC::SyncAll()` | 跨核 | 多核数据交换/阶段分隔 | tiling 必须 `SetScheduleMode(1)` |
| `SetFlag/WaitFlag<HardEvent>` | 流水线 | VF 与 MTE2/MTE3/标量间的依赖 | 取 event id 配对 |
| `DataSyncBarrier<MemDsbT::UB>()` | 标量→VF | UB 参数可见性 | 传 `__ubuf__` 前 |
| `__builtin_cce_dcci` / `DataCacheCleanAndInvalid` | cache | 刷 DCache 保证 GM 可见 | scatter 清零后、stateful 回写 |
| `__threadfence()` | 内存序 | 发布语义（hash 表 key 先于 state） | CAS 抢槽后 |
| `asc_shfl_down/up/__shfl` | warp | 归约/广播/扫描 | 同 warp |

## 2. VF 间同步限制（易踩坑）

- 同一个 kernel 内多个 `Simt::VF_CALL` 之间**仅能保证 block 内串行**，**不能保证全核同步**；
- 需要全核同步时在 VF 之间加 `SyncAll()`，且 tiling 设 `SetScheduleMode(1)`；
- VF 与 DMA 之间的数据依赖必须用 event，不能靠函数返回顺序。

```cpp
// 两阶段 kernel 的标准编排（清零 → SyncAll → 累加）
asc_vf_call<InitOutputZeroSimt>(dim3(THREAD_NUM), outputSize, outGradGm);
SyncAll();
asc_vf_call<ComputeDeformableOffsetGrad>(dim3(THREAD_NUM), ...);
```

- 出处：`conv/deformable_offsets_grad`、`math/histogram_*`、`index/unsorted_segment_*`（InitGm + SyncAll）

## 3. SIMT 与 Vector/DMA 流水线的 event 依赖链

```cpp
// MTE2_V（加载完成才能算）→ V_MTE3（产出完成才能写回）→ MTE3_MTE2（写回完成才能覆盖输入缓冲）
event_t eventIdVToMte3 = static_cast<event_t>(this->pipe_->FetchEventID(HardEvent::V_MTE3));
SetFlag<HardEvent::V_MTE3>(eventIdVToMte3);
WaitFlag<HardEvent::V_MTE3>(eventIdVToMte3);
DataCopyPad(outValueGm_[gmOffset], finalValues_, valueCopyParam);
event_t eventIdMte3ToMte2 = static_cast<event_t>(GetTPipePtr()->FetchEventID(HardEvent::MTE3_MTE2));
SetFlag<HardEvent::MTE3_MTE2>(eventIdMte3ToMte2);
WaitFlag<HardEvent::MTE3_MTE2>(eventIdMte3ToMte2);
// 标量写 UB → VF 读：S_V 或 DataSyncBarrier<UB>
```

- 出处：`math/sort/op_kernel/arch35/sort_small_axis_two_stage.h`、`conversion/dynamic_stitch`（S_V）

## 4. 原子操作完整谱系

| 原子 | 语义 | 适用 | 出处 |
|------|------|------|------|
| `asc_atomic_add/max/min/or` | GM/UB 标量原子 | scatter/histogram/ragged | 全仓库 |
| `Simt::AtomicMax/Min/Cas` | SIMT API 封装 | scatter_nd_max/min、prod CAS 自旋 | unsorted_segment_prod |
| `asc_atomic_cas` | 比较交换 | hash 表抢槽、prod 乘法 | embedding_hash_table |
| `asc_atomic_exch` | 交换 | binary 置位（read+exch 快 1.27×） | ragged_bin_count |
| `SetAtomicAdd<T>()` + DataCopyPad | DMA 整块原子加 | UB 私有直方图折叠、SIMD scatter | histogram、scatter_add |
| `SetAtomicMax<float>()` | DMA 原子 max | binary OR 折叠（防加出 2.0） | ragged_bin_count |

```cpp
// CAS 自旋实现无原生原子指令的乘法（unsorted_segment_prod）
while (true) {
    TX oldVal = outputGm[outputIndex];
    TX newVal = oldVal * curGmValue;
    TX cas = Simt::AtomicCas(outputGm + outputIndex, oldVal, newVal);
    if (cas == oldVal) { break; }
}
```

## 5. 原子性能经验

- **同核线程间 → UB SRAM 原子最快**；核间归并 → 连续 DMA 级 `SetAtomicAdd`（每核一次）；输入稀疏 → SIMT 直接 GM 散列原子（交给 DCache）。
- **binary 输出必须原子**：plain store 因 cache line false sharing 实测只有 6.25% 正确；`read + asc_atomic_exch` 比裸 exch 快 1.27×（ragged_bin_count 源码注释实测数据）。
- **CAS 自旋高冲突退化**：prod 更依赖排序模板兜底高聚合比场景。
- int8/uint8/bool/fp16 无对应原子指令 → workspace 三段式（见 data-movement.md 第 5 节）。

## 6. 跨核数据交换（workspace 协议）

```cpp
// 生产者写 workspace → SyncAll → 消费者读
// tiling: SetScheduleMode(1) + SetWorkspaceSize(大小)
// kernel: 阶段1 各核写 partial → SyncAll → 阶段2 core0/各核读
// 注意：跨核 partial 写入用 asc_atomic_exch 防缓存行互逐（ragged_bin_count）
```
