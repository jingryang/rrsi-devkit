# SIMT 高频坑位与对策

> 按频率排序。来源：`vf_experiences/gather-scatter/` SIMT 实测条目 + 本仓 `examples_simt/` 验证（坑位均为本环境实测或可复现项，自成体系）。

| 现象 | 根因 | 对策 |
|------|------|------|
| SIMT UB 越界 / 数据错位 / VEC_ERROR | SIMT UB 读写窗口 = 绝对 `[0, 8192B)`（Ascend950DT / CANN 9.1.0~9.2.0 实测基线，换工具链以实测为准） | buffer 排 UB offset 0 单窗口；或**直写 GM 避开窗口**；case 按 dtype 缩放 |
| async SIMT 后 CopyOut 读到 stale / 丢数据 | TQue EnQue/DeQue 不等待 async SIMT 任务 | 显式 `SetFlag/WaitFlag<HardEvent::MTE2_V>` + `<HardEvent::V_MTE3>` |
| `cast 'const uint64_t*' to '__ubuf__ uint64_t*'` 编译拒 | ccec 禁地址空间指针 C-style cast | `reinterpret_cast<uintptr_t>` 整数中转 |
| `use of undeclared identifier 'dim3'` | `dim3` 在 `cce::` 命名空间 | 写 `cce::dim3(256)` |
| `too many arguments`（asc_vf_call 无 dim3 重载） | `kernel_operator.h` 只有纯透传版 | `#include "simt_api/common_functions.h"` |
| `No module named ttk / SingleOperatorLaunch` | sys.path 放错层级 | 注入**包的父目录**（skill 根；ttk 为本机 ops-test-kit 源码） |
| 每线程局部变量多 → 栈溢出/性能崩 | `__launch_bounds__(N)` 决定每线程寄存器数（N 大 → 寄存器少） | N 与实际线程数一致；局部变量按 N 的寄存器预算控制（见编程模型表） |
| Warp 内分支发散 → 性能差 | 同一 Warp 32 线程走不同分支被串行执行 | 分支尽量对齐到整 Warp（32 的倍数边界）；发散严重改 SIMD 或重排数据 |
| 大 shape 单线程串行拷贝慢 | 线程数 < 数据量，且每线程内层串行大循环 | 用 stride 循环摊开；或线程每元素 + 短向量（`float2/4`）合并访存 |
| 空转线程写越界 | `threadIdx.x >= total` 未保护 | 入口空转保护 `if (threadIdx.x >= total) return;` |
| 输入越界读 GM（SIGBUS/VEC_ERROR） | index 越界未钳制 | 钳制 `if (idx >= bound) idx = bound-1;`（SIMT 允许运行时分支） |
| 块内多线程裸写同一 UB 地址 | 数据竞争（histogram/counter） | 用 `asc_atomic_*` 或 `asc_syncthreads` 分段 |
| golden IndexError（host 越界） | 布局契约错（`innerIdx ≤ innerSrc`、`idxDimStrides` 用不含自身版本） | `idxDimStrides` 用**含自身后缀积** `prod(shape[k:])`；`xDimStrides` 用不含自身标准 stride |
| 精度比较误用 allclose | gather 是纯拷贝（位搬运） | `compare_tensor(output, golden, dtype=..., threshold=0.0)` bit-exact 比较（§6.6） |
| device 0 不可用 | 环境设备异常 | 先 `DeviceInfo()` 选 Health:OK（本机默认 device 1） |
| 改源码后结果"没变" | kernel_meta 旧产物 | SourceModule 默认 fresh-build；排查 `kernel_meta/` 的 `.o` mtime 晚于 `.cpp` |

## 与 SIMD 坑位的本质区别

- **无 mask/尾块问题**：SIMT 用 `if (threadIdx.x >= n) return;` 代替 `UpdateMask` 尾部掩码。
- **无硬件循环限制**：`uint32_t` 循环、指针下标、运行时分支均合法。
- **无 32B 对齐硬约束（GM 直写）**：标量寻址自由；UB 消费方若为 SIMD 仍需对齐。
- **坑位重心从"指令语义"转向"窗口 + 同步 + 寻址 + 寄存器预算"**。
