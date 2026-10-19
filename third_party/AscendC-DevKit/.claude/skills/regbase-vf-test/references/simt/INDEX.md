# SIMT VF 编程参考（与 SIMD RegBase 区分）

> 本目录是 **SIMT 模式（`__simt_vf__`）** 的编程参考，与 `vf-instructions/`（SIMD RegBase 指令参考）并列。
> 判据先行：先确认当前 VF 是 SIMD 还是 SIMT，再走对应知识路径。**SIMD 与 SIMT 是两种不同的编程模型，规则互不通用。**

## 判据（结构信号，不按算子名）

| 信号 | 判定 |
|------|------|
| VF 声明含 `__simt_vf__ __launch_bounds__(N)`，体用裸 `__gm__`/`__ubuf__` 指针 + `threadIdx.x`/`blockIdx.x` 线程映射 | **SIMT** |
| VF 声明为 `__simd_vf__ inline`，体用 `AscendC::Reg::RegTensor` + `LoadAlign`/`StoreAlign`/`UpdateMask` + `uint16_t` 硬件循环 | **SIMD** |
| 目标：不规则访存（gather/scatter/稀疏）、复杂分支控制流 | 优先 SIMT |
| 目标：规则连续 elementwise / 归约 / 布局变换，向量吞吐优先 | 优先 SIMD |
| VF 需要 `asc_vf_call<Kernel>(cce::dim3(N), ...)` 在 kernel 内启动 | SIMT |
| VF 需要 `LoadDist`/`StoreDist`/`CastTrait`/`Interleave` 等 Reg 指令 | SIMD |

## SIMD vs SIMT 核心差异

| 维度 | SIMD（`__simd_vf__`） | SIMT（`__simt_vf__`） |
|------|------------------------|------------------------|
| 并行单位 | 向量指令（1 指令多数据） | 线程（thread-per-element/row/ow） |
| 数据搬运 | 必须经 UB：GM→(MTE2)→UB→`LoadAlign`→Reg→`StoreAlign`→UB→(MTE3)→GM | 可 **直接读写 GM**（经 DCache）或读写 UB |
| 访存 | 规则连续，32B 对齐语义强 | 离散/随机自然，标量寻址 |
| 分支 | 硬件循环内禁 `if/else`/`?:`（`if constexpr` 除外） | **运行时分支合法**（warp 内发散有性能代价） |
| 循环 | 硬件循环：`for (uint16_t i=0; i<n; ++i)`，变量 `uint16_t`、步长 1 | 普通循环：`uint32_t`/`uint64_t` 均可，指针下标合法 |
| Mask | `UpdateMask`/`MaskReg` 管理尾部 | 无需 mask，`if (threadIdx.x >= n) return;` 空转保护 |
| 启动 | `asc_vf_call<simd_fn>(ubuf 指针, 标量...)`（无 dim3 重载） | `asc_vf_call<simt_fn>(cce::dim3(threads), gm/ubuf 指针, 标量...)` |
| 同步 | VF 内禁 `DataCopy`/`SetFlag`；用 `LocalMemBar` | 依赖外部 `SetFlag/WaitFlag<HardEvent>`；线程间用 `asc_syncthreads`/`asc_threadfence*` |
| 寄存器 | `RegTensor`/`MaskReg`（≤32/≤8 约束） | 每线程寄存器（受 `__launch_bounds__` 决定，见编程模型） |
| 地址空间 | `LocalTensor`/`GlobalTensor` 封装 | 裸指针必须带 `__gm__`/`__ubuf__`；**禁止直接 C-style cast 跨地址空间** |

## 文档导航

| 文件 | 内容 |
|------|------|
| `simt-programming-model.md` | 两层结构、线程架构、内置变量、`__launch_bounds__`、`asc_vf_call` + `cce::dim3`、`__simt_vf__`/`__simt_callee__` 约束 |
| `simt-memory-access.md` | GM 直读直写（DCache）、UB 访问（SingleOperatorLaunch 8KB 窗口硬约束）、对齐、地址空间指针转换 |
| `simt-sync.md` | 流水线同步（`SetFlag/WaitFlag<HardEvent>`）、TQue 不覆盖 async SIMT、线程级同步（`asc_syncthreads`/`asc_threadfence*`）、SIMD/SIMT VF 串序 |
| `simt-pitfalls.md` | 高频坑位与对策表（编译拒、8KB 越界、同步竞态、dtype/寻址等） |
| `simt-examples-map.md` | 本仓 `references/examples_simt/` 可运行样例清单、结构模板、SIMD/SIMT 样例对照 |

## 检索路径

1. 先读本 `INDEX.md` 确认 VF 模式（SIMD 走 `vf-instructions/` + `a5-api-enhanced/`，SIMT 走本目录）。
2. SIMT VF 编写 → `simt-programming-model.md`（结构）+ `simt-memory-access.md`（窗口/寻址）+ `simt-sync.md`（同步）+ `simt-pitfalls.md`（坑位）。
3. 具体 SIMT 样例 → `simt-examples-map.md`；本仓可运行样例 → `examples_simt/`（`gather`/`adds`/`scatter`）。
4. 类别级历史经验 → `vf_experiences/{类别}/INDEX.md`（gather-scatter 类别含 SIMT 条目：`experience-simt-async-infra.md`、`experience-simt-gather.md`，横切标签 `simt-async`）。
5. 官方 SIMT API 语义（`asc_syncthreads`/`asc_threadfence*`/`asc_atomic_*`/cache hint 等）→ `ascendc-dev-knowledge/references/api_reference_docs/SIMT_API/`（兜底）。

## 横切标签

`simt-async`（8KB 窗口 + HardEvent 同步）、`multi-dtype`（SIMT 原生位搬运，dtype 分派）、`unaligned-2d`。

## 实证来源

- `gather` `compute_gather_simt` / `compute_gather_row_segment` / `compute_gather_stride`（57/57、57/57、60/60 bit-exact）
- `adaptive_avg_pool_3d` `accumulate_window_sum` / `normalize_cast`（SIMT 窗口累加/归一化，36/36、30/30）
