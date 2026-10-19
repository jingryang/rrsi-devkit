# SIMT 编程模型（`__simt_vf__`）

> 本文件是 SIMT VF 的编程结构参考，自成体系。依据：SIMT API 编程模型（线程架构/函数执行空间限定符/核函数配置）+ 本仓 `vf_experiences/gather-scatter/` SIMT 实测条目 + `examples_simt/` 可运行验证。

## 适用场景

SIMT 适合**控制流复杂 + 访存不规则**的算子片段：gather/scatter 间接寻址、稀疏、条件密集、哈希表。规则连续 elementwise 优先 SIMD（见 `INDEX.md` 判据）。

## 两层结构（SingleOperatorLaunch 单元测试形态）

```
__global__ __aicore__ void {vf_func_snake}_custom(GM_ADDR ..., GM_ADDR workspace, GM_ADDR tiling)
  └─ 读 tiling → 准备 GM 指针 / UB buffer
       └─ asc_vf_call<SimtImpl>(cce::dim3(THREAD_COUNT), __gm__ ptr..., __ubuf__ ptr..., 标量...)
```

- **`__aicore__` wrapper**：保持 `GM_ADDR`/`LocalTensor` 权威签名，`GetPhyAddr()` 提取 `__ubuf__` 裸指针、`(__gm__ T*)` 转 GM 裸指针，再转发给 `__simt_vf__`。
- **`__simt_vf__` 体**：只收裸指针（`__gm__`/`__ubuf__`）+ PoD 标量，无返回值，用 SIMT 内置变量做线程映射。
- **编译约束**：`asc_vf_call` 的 dim3 重载需 `#include "simt_api/common_functions.h"`（`kernel_operator.h` 只有纯透传版）；`dim3` 写 **`cce::dim3(N)`**（裸 `dim3` 在部分编译上下文报 undeclared）。

## 线程架构与内置变量

层次：Grid（线程块网格）→ Thread Block → Warp（32 线程）→ Thread。

| 内置变量 | 含义 | 约束 |
|----------|------|------|
| `gridDim` | Grid 维度（= 启动的 AIV 核数） | `gridDim.x * y * z ≤ 65535`；混合编程下 y/z 必须为 1 |
| `blockDim` | Thread Block 维度（`asc_vf_call` 的 dim3） | `x*y*z ≤ 2048`，建议 32 的倍数 |
| `blockIdx` | 当前 Block 在 Grid 中的索引（= 核号） | — |
| `threadIdx` | 当前线程在 Block 内索引 | `[0, blockDim.x)` |
| `warpSize` | 32（常量） | — |

一维全局线程号：`uint32_t idx = blockIdx.x * blockDim.x + threadIdx.x;`

## 线程映射与空转保护

```cpp
// 直接映射：一线程一元素/一行
if (threadIdx.x >= total) { return; }

// stride 循环：行数/元素数 > 线程数时摊开（推荐）
uint32_t tid = blockIdx.x * blockDim.x + threadIdx.x;
uint32_t stride = gridDim.x * blockDim.x;
for (uint32_t i = tid; i < total; i += stride) {
    // 每个线程处理第 i 个元素
}
```

## `__launch_bounds__(N)`

- 可选，缺省最大线程数 1024；`N` 范围 `[1, 2048]`，且 `N ≥ blockDim.x*y*z`。
- `N` 决定每线程可用寄存器数（**关键，超出会寄存器溢出/栈溢出**）：
  | N | 每线程寄存器数 |
  |---|---|
  | 1025~2048 | 16 |
  | 513~1024 | 32 |
  | 257~512 | 64 |
  | 1~256 | 127 |
  > N→寄存器数映射为**编译器（bisheng/ccec）实现细节，随工具链版本可变**——上述取值是
  > 本项目实测基线（Ascend950DT / CANN 9.1.0~9.2.0 / SingleOperatorLaunch），换工具链
  > 时以实际编译产物（寄存器分配报告 / 溢出报错）为准，不要当作绝对硬事实。
- 建议 `N` 与实际启动线程数一致；单测样例一般用 `__launch_bounds__(256)`。

## `__simt_vf__` / `__simt_callee__` 约束

- 返回类型必须 `void`（`__simt_vf__`）；入参仅 PoD 类型及其指针/数组/结构体，指针必须指向 GM 或 UB。
- `__simt_vf__` 内只能调 `__simt_callee__` 或 `__callee__` 函数。
- `__simt_callee__` 可以有返回值，体可用 SIMT 内置变量。
- **SIMT 不受 SIMD 硬件循环规则约束**：可用 `uint32_t`/`uint64_t` 循环、指针下标、运行时 `if/else`/三目。SingleOperatorLaunch 的 static_check 只检查 `__simd_vf__`/`__simd_callee__`，不拦 SIMT。

## 与 SIMD VF 的串序关系

同一 kernel 内可混合 SIMD VF 与 SIMT VF，二者**串序执行**（同一时刻 AIV 只执行一种）。切到 SIMT 时 DCache 数据保留。SIMT VF 后接 SIMD VF（或反）时用 `asc_vf_call` 顺序下发即可，数据交互经 UB。

## SingleOperatorLaunch 实测要点（Ascend950DT / CANN 9.2.0）

- SIMT 可**直读直写 GM**（`__gm__ float*` 读 + 写），经 DCache，无需为输出申请 UB 缓冲——gather 样例即此形态，天然避开 8KB UB 窗口。
- 若 SIMT 需要写 UB（供后续 SIMD 消费），buffer 必须落在 **UB offset 0 起的单 8KB 窗口内**（工具链硬约束，见 `simt-memory-access.md`）。
- 单核 `block_dim=1` 时 `blockIdx.x=0`、`gridDim.x=1`，stride 循环即线程块内摊开；多核 `block_dim>1` 时 `blockIdx.x=核号` 自动跨核拆分。

## 参考样例

- 本仓可运行：`references/examples_simt/gather.cpp`（线程每行 + stride 循环 + GM 直写）、`adds.cpp`（线程每元素）、`scatter.cpp`（线程每元素 + 间接写），清单与模板见 `simt-examples-map.md`。
