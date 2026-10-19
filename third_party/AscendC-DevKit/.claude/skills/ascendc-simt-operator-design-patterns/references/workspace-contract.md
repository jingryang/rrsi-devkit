# Workspace 规划与 host-kernel 强契约

> workspace 是 SIMT 多核协作与确定性实现的数据交换通道，也是本体系**最主要的工程风险点**：host 与 kernel 两侧的分段公式必须逐段一致，任何一侧的近似都会在大 shape 下越界。

## 1. 16MB 系统区打底 + 算子专属区

```cpp
static constexpr uint32_t RESERVED_WS_SIZE = 16 * 1024 * 1024;   // 16MB 系统区打底
ge::graphStatus GetWorkspaceSize() {
    auto currentWorkspace = context->GetWorkspaceSizes(1);
    currentWorkspace[0] = RESERVED_WS_SIZE;
    if (isDeterministic_ == 1) {   // 算子专属区，kernel 侧 ComputeInWs 按同公式读
        currentWorkspace[0] += ROWS_IN_WORKSPACE * innerDim_ * valueTypeBytes_ +
                               ROWS_IN_WORKSPACE * idTypeBytes_;
    }
    return ge::GRAPH_SUCCESS;
}
```

- 出处：`index/segment_sum/op_host/arch35/segment_sum_simt_tiling.cpp`

## 2. host-kernel 强契约（事故教训）

scatter_reduce_common 的旧实现 host 侧 workspace 计算带 `"+128 margin"` 近似，在 M>1M 时排序越界写穿相邻 region（VEC_ERROR）。修复方式是 host **精确复算 kernel 的 padding 公式**：

```cpp
// kernel 侧归并排序需要 padM = P2 * runLen0（P2 是把 runLen0 压到 ≤SORT_TILE=8192 的 2 的幂）
// host 必须复算同一公式，不能用任何近似：
constexpr uint64_t SORT_TILE_HOST = 8192UL; // MUST match SORT_TILE in kernel
uint64_t padM = indicesNum;
if (indicesNum > SORT_TILE_HOST) {
    uint64_t p2 = 1UL;
    while (p2 * 2UL <= blockNum) { p2 *= 2UL; }
    while ((indicesNum + p2 - 1UL) / p2 > SORT_TILE_HOST) { p2 *= 2UL; }
    padM = p2 * ((indicesNum + p2 - 1UL) / p2);
}
uint64_t mAlign = ((padM + 7UL) / 8UL * 8UL) + 128UL;
```

- 出处：`index/scatter_reduce_common/op_host/arch35/scatter_reduce_common_tiling.cpp`（注释记录完整事故）

**铁律**：workspace 分段公式、magic 参数、per-core 区间表、tiling struct 布局，host 侧怎么算 kernel 侧就必须怎么读——把"一致性"当作正确性的硬要求，参数化共享头文件（`*_tiling_data.h` / `*_precision_policy.h`）防漂移。

## 3. SIMT Dynamic Unified Buffer（host tiling 必配）

SIMT 线程可访问的 UB 区 = **Dynamic Unified Buffer**（RTS SIMT 共享内存窗口；API 默认 0 = 不声明，不声明则仅落在 runtime 兜底小窗口，大共享 buffer / 线程本地 DCache 越界）。**模板是 SIMT（VF 走 Simt 线程 / SIMT 直访 GM）时 host tiling 必须显式声明**，SIMD 模板不配：

大小从平台 UB 扣掉 DCache（SIMT 线程直接访 GM 依赖 UB 内预留的 DCache 区）与静态/预留后下发 kernel，**host 私有化决策与 device TPipe 分配必须用同一个数**：

| 档位 | DCache 大小 | 典型算子 |
|------|------|---------|
| 小 | 32KB | sort/elementwise/histogram |
| 中 | 58KB | one_hot（特殊） |
| 大 | 128KB | foreach/pooling/ragged 系 |

```cpp
// 接口：当前名为 gert::TilingContext::SetDynUBufSize（CANN ≥9 头文件标注：不设置默认为 0）。
// SetLocalMemorySize 是同函数废弃名（mainline ops-nn arch35 仍大量按旧名调用，语义完全一致——
// 生成代码用新名 SetDynUBufSize）。
constexpr uint64_t DCACHE_SIZE = 128 * 1024;              // DCache 三档按算子选（见上表）
uint32_t ubSize = Ops::Base::GetUbSize(context);          // 平台 UB（op_common/op_host/util/platform_util.h），禁硬编码
auto ret = context->SetDynUBufSize(ubSize - DCACHE_SIZE); // 若另有静态 TPipe buffer，再扣对应预算；必须与 kernel TPipe 分配一致
```

- 判据：**按结构信号判**（模板走 SIMT 线程化路径 / kernel 含 SIMT 直访 GM 段），不按算子名。
- 出处：`index/gather_v2/op_host/arch35/gather_v2_tiling.cpp`（SIMT 模式 `SetLocalMemorySize(ubSize_ - DCACHE_SIZE)`，DCACHE=128K；SIMD 模式不调）、`index/unsorted_segment_sum/..._simt_tiling.cpp`、`index/scatter_elements/..._base.cpp`、`index/segment_sum/..._simt_tiling.cpp` 等 ops-nn arch35 SIMT tiling 全量统一。
- 参考：CANN 头文件 `exe_graph/runtime/tiling_context.h`（`SetLocalMemorySize` 标注 deprecated、`return SetDynUBufSize(...)`）。

## 4. SetScheduleMode(1)：需要 SyncAll 就必须 batch 独占调度

kernel 内有 `SyncAll()`（多核协作）时，tiling 必须 `SetScheduleMode(1)`（batch 调度独占核），否则多流场景死锁：

```cpp
// Kernel 侧有 SyncAll() 的算子，tiling 侧必须：
context->SetScheduleMode(1);   // batch mode 全核同时驻留
```

- 出处：`index/sort_lib/op_kernel/arch35/sort_lib.h`（使用契约注释：batchmode 独占核，否则多流死锁）

## 5. 多个 VF_CALL 之间的同步限制

- 同一个 kernel 内多个 `Simt::VF_CALL` 之间**仅能保证 block 内串行**，不能保证全核同步；
- 需要全核同步时在 VF 之间加 `SyncAll()`，且 tiling 设 `SetScheduleMode(1)`；
- VF 与 MTE3/MTE2 的数据依赖用显式 event：`SetFlag/WaitFlag<HardEvent::V_MTE3 / MTE3_MTE2 / S_V>`。

## 注意事项

- workspace 大小计算必须做 uint64 溢出检查（batch×numN 等乘积）。
- 确定性场景的 workspace（部分和/临时行）大小必须与 kernel 的段划分严格对应。
