# SIMT 异步基础设施（asc_vf_call / 共享内存窗口 / 同步结构）— 跨类别共享

> 本条目是所有 `__simt_vf__` 类 VF（gather / 窗口累加 / SIMT 归一化 cast）共享的**基础设施约束**，跨类别引用。

## 适用判据

VF 使用 SIMT 编程模型（`__simt_vf__` thread-per-element 或 thread-per-ow），或通过 `asc_vf_call` 启动异步 SIMT kernel。**SIMT 不受 SIMD 硬件循环规则约束**（指针下标/运行时分支/uint32 循环均合法——SingleOperatorLaunch static_check 正则只拦 `__simd_vf__/__simd_callee__`）。

## 关键实现要点

### 启动形态（本地 CANN 9.1.0）

```cpp
#include "simt_api/common_functions.h"   // 关键！kernel_operator.h 只有纯透传版 asc_vf_call
#include "simt_api/asc_fp16.h"           // __half2float 等内建真身（需要时）
#include "simt_api/asc_bf16.h"
asc_vf_call<Kernel<DX, DI>>(cce::dim3(256), xPtr, idxPtr, yPtr, scalars...);
```
- `dim3` 必须写 `cce::dim3`（裸 dim3 报 undeclared）。
- `__simt_vf__` 需 `__launch_bounds__(256)`；体只收 `__ubuf__`/`__gm__` 裸指针 + 标量，`LocalTensor` 形式留给 `__aicore__` wrapper。

### 同步结构（async SIMT 必须，官方混合编程模式）

```
DataCopyPad(MTE2) → SetFlag/WaitFlag<HardEvent::MTE2_V>(0) → asc_vf_call(V)
  → SetFlag/WaitFlag<HardEvent::V_MTE3>(0) → DataCopyPad(MTE3)
```
**TQue EnQue/DeQue 不保证 async SIMT VF 完成**（实测大 case 竞态丢数据），必须显式 HardEvent flag。

### SIMT 共享内存窗口（launch 配置；SingleOperatorLaunch 默认 8KB，可放大）

> **历史误区修正**：早前版本称"SIMT VF 的 UB 读写窗口 = 绝对 [0, 8192B)，与分配方式无关"。这是把 **SingleOperatorLaunch 默认 launch 配置**当成了固定硬件上限——设备实测证明窗口可随 launch 期 SIMT 共享内存大小放大，非绝对 8KB（详见下方"实测证据"与 `docs/plan/simt-ub-window-misconception/`）。

**正确模型**：SIMT 共享内存 = Unified Buffer（256KB），块内线程共享；UB 从低到高分 静态内存 → 动态内存 → 预留 8KB → Data Cache(≥32KB)。SIMT 场景须预留 8KB + 至少 32KB DCache，即动态共享内存可配置上限 ≈ 256−8−32 = **216KB**。launch 期通过动态共享内存大小指定窗口（官方 `<<<grid, block, dynUBufSize>>>`；RTS 为 `LaunchKernelArgs.simt_share_memory_size` → `RtTaskCfgInfo.dynamic_share_mem_size`，默认 0 → RTS 落 8KB 默认）。**生产集成走 TPipe/TQue 常规分配 + `GetPhyAddr()` 转 `__ubuf__*` 传给 SIMT VF，不要求排 offset 0 单窗口**（真实 gather 生产 kernel 即如此并通过 run-cases）。

**工具支持（SingleOperatorLaunch 已内置放大窗口的公开参数）**：`func(...)` / `SourceModule(...)` / `.profile(...)` 均接受可选 `simt_share_memory_size`（字节数）并透传进 launch——不需要再低层手工构造 `LaunchKernelArgs`。默认 `None`/`0` → RTS 兜底 8KB；传正值放大（上限受 UB−预留8KB−DCache≥32KB 约束）；`< 0` 抛 `ValueError`。设备实测（2026-09-02）：显式传 `65536` → 64KB 全窗口 PASS（见下实测表）。

**实测证据**（Ascend950DT / CANN 9.1.0 / SingleOperatorLaunch，探针：`LocalTensor<uint8_t>(VECCALC, 0, 65536)` 大 pool + SIMT 256 threads 全窗口读写）：

| 数据量 | simt_share_memory_size | 结果 |
|--------|------------------------|------|
| 9216B (>8KB) | 0（SingleOperatorLaunch 默认） | **VEC_ERROR**（仅 ~8KB 内正确） |
| 8192B | 0（默认） | PASS（默认窗口恰 = 8KB） |
| 64KB | 65536 | **PASS（64KB 全窗口通过）** |
| 64KB | 8192/12288/16384/32768 | VEC_ERROR（数据越出配置窗口） |
| 12KB | 12288 | PASS |

**对策**：把 VF 单批的输入输出 buffer 占用控制在 **launch 配置的 SIMT 共享内存窗口**内（不传 `simt_share_memory_size` 时按 8KB 默认规划）；需要更大窗口时直接给 launch 传参放大：
```python
func(src, out, *ws, tiling_data=td, simt_share_memory_size=65536)  # 窗口放大到 64KB
```
手工小 pool 写法仅用于 SingleOperatorLaunch 无 TPipe 的单测壳：
```cpp
LocalTensor<uint8_t> pool(VECCALC, 0, 8192);
// pool.ReinterpretCast<DI>()[0] + pool.ReinterpretCast<DX>()[idxBytesAligned/sizeof(DX)]（段间 32B 对齐）
```

## 坑位与对策

| 现象 | 根因 | 对策 |
|------|------|------|
| `No module named ttk / SingleOperatorLaunch` | sys.path 放错层级 | 注入**包的父目录**（skill 根；ttk 为本机 ops-test-kit 源码） |
| `use of undeclared identifier 'dim3'` | dim3 在 `cce::` 命名空间 | `cce::dim3(256)` |
| `too many arguments`（asc_vf_call 无 dim3 重载） | kernel_operator.h 纯透传版 | `#include "simt_api/common_functions.h"` |
| 大 case 数据错位/丢失/VEC_ERROR（UB 窗口界） | 数据超 launch 配置的 SIMT 共享内存窗口（默认 8KB，可放大） | 单批 ≤ 配置窗口；放大窗口传 `simt_share_memory_size=<字节>`（上限 ≈ UB−8KB−32KB ≈ 216KB）；生产用 TPipe/TQue 正常分配 + host tiling `SetDynUBufSize` |
| async VF 后 CopyOut 读到 stale | EnQue 的 flag 不等待 async 任务 | 显式 `SetFlag/WaitFlag<V_MTE3>` |
| `cast 'const uint64_t*' to '__ubuf__ uint64_t*'` 编译拒 | ccec 禁地址空间指针 C-style cast | `reinterpret_cast<uintptr_t>` 整数中转 |

## 横切标签

`simt-async`。

## 实证来源

- `gather` `compute_gather_simt`（57/57；共享内存窗口五路实验证据——默认 8KB 内通过；窗口可放大，见上）
- `gather` `compute_gather_row_segment` / `compute_gather_stride`（57/57、60/60）
- `adaptive_avg_pool_3d` `accumulate_window_sum` / `normalize_cast`（SIMT 窗口累加/归一化，36/36、30/30）
