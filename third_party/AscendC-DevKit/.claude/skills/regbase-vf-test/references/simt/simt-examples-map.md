# SIMT 可运行样例（本仓自成体系）

> 本目录（`references/examples_simt/`）是与 `references/examples/`（SIMD）并行的 **SIMT 可运行样例集**，全部基于 SingleOperatorLaunch（`__simt_vf__` + `asc_vf_call`），可直接在 NPU 上运行验证。编写 SIMT VF 时以 `references/simt/`（编程模型/内存/同步/坑位）为知识主体，本目录为落地模板。

## 样例清单

| 样例 | VF 名 | 演示点 | 验证 |
|------|-------|--------|------|
| `gather.cpp` / `test_gather.py` | `GatherRowSimtImpl` | 线程每行 + stride 循环；GM 直读直写（index 表 + 输入矩阵）；越界钳制 | bit-exact，含 `[20001,1023]`+12288 参考规模 |
| `adds.cpp` / `test_adds.py` | `AddsSimtImpl` | 线程每元素 + stride 循环；标量经 tiling 传入；GM 直写（与 SIMD adds 对应） | bit-exact |
| `scatter.cpp` / `test_scatter.py` | `ScatterSimtImpl` | 间接写（与 gather 反向）；越界钳制；数据竞争语义说明 | bit-exact（置换 index） |

运行方式（device 1 为本机健康设备）：

```bash
source /usr/local/Ascend/ascend-toolkit/set_env.sh
python3 examples_simt/test_gather.py   --device_id 1
python3 examples_simt/test_adds.py     --device_id 1
python3 examples_simt/test_scatter.py  --device_id 1
```

## 样例结构模板（新建 SIMT 样例时复制）

**`.cpp` 结构**：

```cpp
#include "kernel_operator.h"
#include "simt_api/common_functions.h"   // 必须有：asc_vf_call 的 dim3 重载
#include <cstdint>

constexpr uint32_t THREAD_COUNT = 256;

namespace CustomRegImpl {
// SIMT VF：裸 __gm__/__ubuf__ 指针 + 标量；thread-per-element/row + stride 循环
__simt_vf__ __launch_bounds__(THREAD_COUNT) inline void XxxSimtImpl(
    __gm__ float *in, __gm__ float *out, uint32_t total_length)
{
    uint32_t tid = blockIdx.x * blockDim.x + threadIdx.x;
    uint32_t stride = gridDim.x * blockDim.x;
    for (uint32_t i = tid; i < total_length; i += stride) {
        out[i] = in[i];
    }
}
} // namespace CustomRegImpl

struct XxxTilingData { uint32_t totalLength; };

extern "C" __global__ __aicore__ void xxx(
    GM_ADDR in, GM_ADDR out, GM_ADDR workspace, GM_ADDR tiling)
{
    (void)workspace;
    XxxTilingData td;
    // ... CopyTilingData(&td, tiling)
    asc_vf_call<CustomRegImpl::XxxSimtImpl>(cce::dim3(THREAD_COUNT),
        (__gm__ float *)in, (__gm__ float *)out, td.totalLength);
}
```

**`.py` 结构**：复用 `test_adds.py`（稳健自举 + `output_indices` OOB 检测 + 对齐/非对齐/极小/大多 shape 覆盖）。

## SIMT 与 SIMD 样例对照

| 能力点 | SIMD 样例（`references/examples/`） | SIMT 样例（`references/examples_simt/`） |
|--------|-------------------------------------|-------------------------------------------|
| 标量运算 | `adds`/`muls`（Reg::Adds/Muls + mask） | `adds`（线程每元素） |
| 间接读 | （Gather Reg 指令见 a5-api-enhanced） | `gather`（线程每行 + stride） |
| 间接写 | （Scatter Reg 指令见 a5-api-enhanced） | `scatter`（线程每元素 + 越界钳制） |
| 归约 | `reducesum`/`reducemax` | 见 `vf_experiences/reduce/` SIMT 条目 |

## 如何新增一个 SIMT 样例

1. 在 `examples_simt/` 下新建 `{op}.cpp` + `test_{op}.py`（复制 `adds` 模板）。
2. `.cpp`：`__simt_vf__ __launch_bounds__(256) inline` + `asc_vf_call<Kernel>(cce::dim3(256), ...)` + tiling struct。
3. `.py`：复用 `test_adds.py` 的稳健自举 + `output_indices` OOB 检测 + 多 shape 覆盖。
4. 在本文件清单表中登记，并在 `SKILL.md` §5.2 的 SIMT 列表补一行。
5. 若产出可抽象的类别级经验，按 `vf_experiences/{类别}/INDEX.md` 判据并入既有条目（保留 `simt-async` 横切标签）。
