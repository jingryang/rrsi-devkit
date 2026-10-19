# SIMT 同步与流水线

> SIMT VF 是异步任务：`asc_vf_call` 只做下发，**不等 SIMT 完成**。与后续流水（SIMD VF / MTE3 搬出）之间必须显式同步。线程级协作（同一 block 内）用 SIMT 同步/栅栏接口。

## 流水线同步（SIMT VF 与 MTE/SIMD 之间）

标准结构（官方混合编程模式 + 本仓实测）：

```
DataCopyPad(MTE2) 搬入输入
  → SetFlag/WaitFlag<HardEvent::MTE2_V>(0)   // 搬入对 SIMT 可见
  → asc_vf_call<SimtKernel>(cce::dim3(N), ...)  // SIMT 计算（V 流水）
  → SetFlag/WaitFlag<HardEvent::V_MTE3>(0)   // SIMT 写 UB 对 MTE3 可见
  → DataCopyPad(MTE3) 搬出结果到 GM
```

- **TQue EnQue/DeQue 不保证 async SIMT VF 完成**（实测大 case 竞态丢数据），必须显式 `SetFlag/WaitFlag<HardEvent::MTE2_V>` / `<HardEvent::V_MTE3>`。
- 若 SIMT 直写 GM（不经 UB），MTE3 搬出环节可省略，但 kernel 结束前 RTS/stream 同步保证写回可见。
- SIMT VF 与 SIMD VF **串序执行**：连续两个 `asc_vf_call`（先 SIMT 后 SIMD）在同一核上顺序执行，SIMT 写 UB → SIMD 读 UB 的依赖由 VF 串序 + 需要的 `LocalMemBar` 保证（见下）。

## SIMT 写 UB → SIMD 读（in-place 接力）

- SIMT VF 写 UB 后，SIMD VF（`LoadAlign` 读同一地址）之间除 VF 串序外，若为**同一 UB 地址写后读**，插 `LocalMemBar<VEC_STORE, VEC_LOAD>`（`asc_local_membar` / `Reg::LocalMemBar`）防 V 流水内乱序。
- 混合场景判断口诀（与 `ascend_regbase_programing_guide.md` 的 LocalMemBar 模型一致）：写后读同址 → RAW，必须屏障。

## 线程级同步（Thread Block 内）

| 接口 | 头文件 | 语义 |
|------|--------|------|
| `asc_syncthreads()` | `simt_api/device_sync_functions.h` | 块内所有线程同步（barrier） |
| `asc_threadfence_block()` | 同上 | 块内内存栅栏：保证本线程访存对其他线程可见的顺序 |
| `asc_threadfence()` | 同上 | 全局内存栅栏 |
| `asc_atomic_*()` | `simt_api/device_atomic_functions.h` | UB/GM 原子操作（add/cas/max/min/exch 等） |

- 块内多线程对同一 UB 地址并发读改写（如 histogram、counter）必须用原子操作或同步，不能裸 `++`。
- `asc_threadfence` 不替代 `asc_syncthreads`：栅栏只保证可见性顺序，不保证执行点同步。

## 与 SIMD 硬件循环的同步差异

| 场景 | SIMD | SIMT |
|------|------|------|
| VF 内自身同步 | `LocalMemBar<VEC_STORE, VEC_LOAD>`（同 UB 读写） | 无内部屏障概念；依赖外部 `SetFlag/WaitFlag` |
| VF 内异步下发 | 禁 `DataCopy`/`SetFlag`/`PipeBarrier`（静态检查拦） | 同样禁 MTE 下发；线程级用 `asc_syncthreads` 等 |
| kernel 层流水同步 | `SetFlag/WaitFlag<HardEvent::MTE2_V/V_MTE3>`（跨流水） | 同左；TQue 不保证 async SIMT 完成 |

## 调试提示（同步竞态定位）

同一份源码"加 `printf`/`DumpTensor` 就 PASS、移除后就 FAIL"，或结果多轮不稳 → **先锁流水同步竞态**，依次：
1. `__aicore__` 层 VF 调用前后补显式 HardEvent 同步（前：`SetFlag/WaitFlag<HardEvent::MTE2_V>(0)` 保证 MTE2 搬入对 SIMT 可见；后：`SetFlag/WaitFlag<HardEvent::V_MTE3>(0)` 保证 SIMT 写对 MTE3 可见）；
2. SIMT 写 UB → SIMD 读同址补 `LocalMemBar<VEC_STORE, VEC_LOAD>`；
3. 之后才查 kernel_meta 新鲜度与数值/寻址问题。

## 参考样例

- `references/examples_simt/gather.cpp`（GM 直写，无 MTE3，stream 同步兜底）。
- `vf_experiences/gather-scatter/experience-simt-async-infra.md`（UB 接力 + HardEvent 结构最小骨架）。
