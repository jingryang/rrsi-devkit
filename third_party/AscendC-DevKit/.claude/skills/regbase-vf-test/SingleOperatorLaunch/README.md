# SingleOperatorLaunch

基于 TTK 的 PyCUDA 风格单算子编译与执行工具，面向 **Ascend NPU**。编写 AscendC Kernel、编译为 `.o` 并直接在 NPU 上运行，无需借助 `atc`、`msopst` 或算子库。

---

## 目录结构

```
SingleOperatorLaunch/
├── __init__.py                # 模块入口
├── device_info.py             # 设备信息查询（对标 pycuda.driver.Device）
├── source_module.py           # 算子编译与执行（对标 pycuda.compiler.SourceModule）
├── diagnostics.py             # OOB 检测、overflow 检测、assert 回调、数据 dump
├── logging_config.py          # log 控制
└── examples                   # 样例
    ├── example_add.py             # Add 算子完整示例
    ├── example_add_prof.py        # Add 算子性能测试示例
    ├── example_reducesum.py       # ReduceSum 算子示例
    ├── example_mixed_tiling.py    # 混合类型 tilingData 示例
    ├── add_custom.cpp             # example_add.py 对应 AscendC 源码
    ├── add_custom_prof.cpp        # example_add_prof.py 对应 AscendC 源码
    ├── reducesum_custom.cpp       # example_reducesum.py 对应 AscendC 源码
    └── mixed_tiling_custom.cpp    # example_mixed_tiling.py 对应 AscendC 源码
```

---

## 快速开始

### 1. 查询设备信息

```python
from SingleOperatorLaunch import DeviceInfo

dev = DeviceInfo()
print(dev)
```

输出示例：

```
DeviceInfo(2 device(s))
  [0] Ascend910_9362 | Health:OK | Temp:44C
  [1] Ascend910_9362 | Health:OK | Temp:44C
```

### 2. 编译并执行单个算子

你可以把 AscendC Kernel 直接以字符串形式传入 `SourceModule`，也可以将源码保存到 `.cpp` 文件，由 Python 脚本读取后传入。将 kernel 源码分离到 `.cpp` 文件可以方便 IDE 进行语法高亮、格式化与版本管理。

#### 创建 `.cpp` 代码
```cpp
// scale_add_custom.cpp
#include "kernel_operator.h"

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    uint8_t *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) {
        dst[i] = src[i];
    }
}

template <typename T>
__aicore__ inline void DataCopyInTensor1D(LocalTensor<T>& dst, GlobalTensor<T>& gm, uint64_t gmOffset,
        uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),                  // blockCount
        static_cast<uint32_t>(len * sizeof(T)),    // blockLen
        static_cast<uint32_t>(0),                  // srcStride
        static_cast<uint32_t>(0),                  // dstStride
        0                                          // rsv
    };
    DataCopyPadExtParams<T> padParams{
        false,                   // isPad
        static_cast<uint8_t>(0), // leftPadding
        static_cast<uint8_t>(0), // rightPadding
        static_cast<T>(0.0)      // paddingValue
    };
    DataCopyPad(dst, gm[gmOffset], copyParams, padParams);
}

template <typename T>
__aicore__ inline void DataCopyOutTensor1D(GlobalTensor<T>& gm, LocalTensor<T>& src, uint64_t gmOffset,
        uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),                  // blockCount
        static_cast<uint32_t>(len * sizeof(T)),    // blockLen
        static_cast<uint32_t>(0),                  // srcStride
        static_cast<uint32_t>(0),                  // dstStride
        0                                          // rsv
    };
    DataCopyPad(gm[gmOffset], src, copyParams);
}

// 混合类型 tilingData 结构体
struct MixedTilingData {
    uint64_t totalLength;   // 数据长度
    float    eps;           // 浮点偏置
    float    repeat;        // 重复次数
};

__aicore__ inline void MixedCompute(LocalTensor<float>& dst, LocalTensor<float>& src,
            float repeat, float eps, uint32_t len)
{
    Muls(src, src, repeat, len);
    PipeBarrier<PIPE_V>();      // for Ascend910B
    Adds(dst, src, eps, len);
}

extern "C" __global__ __aicore__ void scale_add_custom(
    GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    MixedTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);

    uint32_t blockLength = tilingData_.totalLength;
    uint32_t blockLengthAlign = AscendC::CeilDivision(blockLength * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(float);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECOUT, 1> outQueueY;
    GlobalTensor<float> xGm;
    GlobalTensor<float> yGm;

    xGm.SetGlobalBuffer((__gm__ float*)x, blockLength);
    yGm.SetGlobalBuffer((__gm__ float*)y, blockLength);

    pipe.InitBuffer(inQueueX, 1, blockLengthAlign * sizeof(float));
    pipe.InitBuffer(outQueueY, 1, blockLengthAlign * sizeof(float));

    LocalTensor<float> xLocal = inQueueX.AllocTensor<float>();
    DataCopyInTensor1D<float>(xLocal, xGm, 0, blockLength);
    inQueueX.EnQue(xLocal);

    xLocal = inQueueX.DeQue<float>();
    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();

    MixedCompute(yLocal, xLocal, tilingData_.repeat, tilingData_.eps, blockLength);

    outQueueY.EnQue<float>(yLocal);
    inQueueX.FreeTensor(xLocal);

    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor1D<float>(yGm, yLocal, 0, blockLength);
    outQueueY.FreeTensor(yLocal);
}
```

#### 从 `.cpp` 文件读取源码

```python
import os
import numpy as np
from SingleOperatorLaunch import SourceModule, pack_tiling_data

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KERNEL_SRC_PATH = os.path.join(SCRIPT_DIR, "scale_add_custom.cpp")

with open(KERNEL_SRC_PATH, "r", encoding="UTF-8") as f:
    kernel_src = f.read()

mod = SourceModule(
    source=kernel_src,
    kernel_name="scale_add_custom",
    block_dim=1,
    core_type="VectorCore",
    workspace_sizes=1024,
)

# 获取可调用函数
scale_add = mod.get_function()

# 准备数据
x = np.random.randn(total_length).astype(np.float32)
y = np.empty(total_length, dtype=np.float32)

# 用 pack_tiling_data 构造混合类型 tiling 数据
#    对应 C 结构体：{ uint64_t totalLength; float eps; float repeat; }
tiling_data = pack_tiling_data(
    [("totalLength", np.uint64), ("eps", np.float32), ("repeat", np.float32)],
    {"totalLength": total_length, "eps": 0.5, "repeat": 3},
)

# 执行：必须按顺序传入 (input, output, workspace, tiling_data) 并保持与 kernel 入口顺序一致
scale_add(x, y, *mod.workspace_arrays, tiling_data=tiling_data)

# 验证（生态精度标准：MERE/MARE + per-dtype 阈值，见 references/examples）
from SingleOperatorLaunch.precision_check import compare_tensor
golden = x * 3.0 + 0.5
verdict = compare_tensor(y, golden, dtype="float32")
assert verdict.passed, verdict.error_msg
print("PASS")
```

---

## API 说明

### `DeviceInfo`

对标 `pycuda.driver.Device`，用于查询 NPU 硬件状态。

| 方法 | 说明 |
|------|------|
| `device_count` | 可用设备数量 |
| `list_logical_device_ids()` | 逻辑设备 ID 列表 |
| `get_soc_version(dev_id=0)` | 完整 SoC 型号，如 `Ascend910B3` |
| `get_short_soc_version(dev_id=0)` | 短型号，如 `Ascend910B` |
| `get_device_health(dev_id=0)` | 设备健康状态 |
| `get_temperature(dev_id=0)` | 芯片温度（°C） |
| `get_utilization(dev_id=0, type=2)` | 利用率（1=内存, 2=AI Core...） |
| `get_frequency(dev_id=0, type=7)` | 频率（MHz） |
| `get_hw_info(dev_id=0)` | 完整硬件信息字典 |

---

### `SourceModule`

对标 `pycuda.compiler.SourceModule`，负责 AscendC 源码的编译与执行。

#### 构造参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `source` | `str` | **必填** | AscendC Kernel 源码 |
| `kernel_name` | `str` | **必填** | Kernel 入口函数名 |
| `block_dim` | `int` | `1` | 启动核数 |
| `core_type` | `str` | `"VectorCore"` | 核类型：`AiCore` / `VectorCore` / `CubeCore` / `MIX` |
| `platform` | `str` | `None` | 完整 SoC 型号（如 `Ascend910B3`），自动检测 |
| `kernel_meta` | `str` | `None` | 编译产物输出目录，默认 `<调用脚本目录>/kernel_meta/<kernel_name>`；每次编译前清理该 kernel 旧产物（fresh-build） |
| `device_id` | `int` | `0` | 目标 NPU 设备 ID |
| `task_ration` | `str` | `"1:0"` | MIX 核任务比例 |
| `keep_source` | `bool` | `False` | 是否保留 `.cce` 源文件 |
| `ascendc_dump` | `bool` | `False` | 是否启用 ASCENDC_DUMP。设为 `False` 时编译添加 `-DASCENDC_DUMP=0`，与 CANN `handle_dump_options` 行为一致 |
| `workspace_sizes` | Workspace sizes in bytes. Can be a single int or a list/tuple of ints. When provided, workspace arrays are auto-generated and can be accessed via ``workspace_arrays`` and passed to the kernel call. |
| `include_paths` | `list[str]` | `None` | 额外加入 `ccec` 的 `-I` 包含路径 |
| `auto_include_script_dir` | `bool` | `True` | 是否自动把调用 `SourceModule` 的 Python 脚本所在目录加入 `-I` 包含路径 |

#### 静态检查（强制）

`SourceModule` 在真正调用 `ccec` 编译前**必须**执行一轮轻量级 RegBase/AscendC 静态检查，用于尽早拦截常见编程错误，避免昂贵的 NPU 编译/启动失败。该检查是强制性的，无法关闭；检查失败时会直接抛出 `RuntimeError`，停止后续编译与设备操作。

当前检查项：

| 检查项 | 说明 |
|--------|------|
| `simd_vf_modifiers` | `__simd_vf__` / `__simd_callee__` 函数是否带 `inline` 关键字 |
| `simd_vf_ubuf_access` | `__simd_vf__` / `__simd_callee__` 函数体内是否用 `ptr[i]` 直接访问 `__ubuf__` |
| `simd_vf_no_gm` | `__simd_vf__` / `__simd_callee__` 函数体内是否出现 GM/HBM 访问（`GM_ADDR`、`__gm__`、`GlobalTensor`、`SetGlobalBuffer`） |
| `hardware_loop_var_type` | `__simd_vf__` / `__simd_callee__` 的 `for` 循环变量是否为 `uint16_t` |
| `hardware_loop_branch` | `__simd_vf__` / `__simd_callee__` 的 `for` 循环体内是否包含运行时 `if/else` 或三目运算符 `?:`（`if constexpr` 除外） |

> 说明：这些检查基于正则实现，属于语法层面的快速预检，不能替代 `ccec` 编译检查。遇到复杂场景（如指针解引用 `*ptr` 与乘法 `a * b` 难以区分）时，检查器会保守地跳过该规则，避免误报。如果源码确实需要绕过某条规则，可直接使用 `RegBaseChecker(...).run_all()` 或 `check_regbase_source(..., raise_on_failure=False)` 获取报告并自行处理，但 `SourceModule` 的编译流程不接受关闭检查。

#### 属性

| 属性 | 说明 |
|------|------|
| `kernel_meta` | 编译产物目录（`.o`、`.json` 等） |
| `workspace_arrays` | 根据 `workspace_sizes` 自动生成的 workspace numpy 数组列表。每个元素为 `numpy.zeros(size, dtype=uint8)`，可直接传入 kernel 调用 |

#### 方法

| 方法 | 说明 |
|------|------|
| `get_function()` | 获取编译后的可调用 kernel 函数。每个 `SourceModule` 仅包含一个 kernel 入口 |
| `__call__(*args, ...)` | 等价于 `get_function()(...)`，直接传入参数执行 kernel |

---

### `pack_tiling_data`

辅助函数，用于将混合类型的 C 结构体数据打包成 `bytes`，以便通过 ``tiling_data`` 关键字参数安全地传给 kernel。

#### 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `fields` | `list[tuple]` | **必填** | 字段描述列表，格式 ``[(name, numpy_dtype), ...]``。支持的 dtype：``np.uint8/16/32/64``、``np.int8/16/32/64``、``np.float16/32/64`` |
| `values` | `dict` / `list` / `tuple` | `None` | 字段值。``dict`` 按名字赋值，``list/tuple`` 按顺序赋值。为 ``None`` 时返回全零数组，用户可自行修改后调用 ``.tobytes()`` |

#### 返回值

``bytes`` — 可直接作为 ``tiling_data`` 参数传入 kernel 调用。

#### Kernel 调用参数

`get_function()` 返回的对象可直接调用，参数规则如下：

- **`numpy.ndarray`** — 自动拷贝到 HBM，执行后自动写回并释放
- **`int` / `numpy.integer`** — 作为整型参数传入
- **`float` / `numpy.floating`** — 作为 `float32` 传入
- **`ctypes.c_void_p`** — 直接传入设备地址

支持运行时覆盖 `block_dim`：

```python
add(x, y, z, 1024, block_dim=16)
```

**关键字参数：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `block_dim` | `int` | `None` | 覆盖默认 block_dim |
| `tiling_data` | `bytes` | `None` | tiling 原始字节数据 |
| `output_indices` | `set[int]` | `None` | 输出参数索引集合（如 `{0, 2}`）。传入时额外启用数据不变 OOB 检测；`None` 时仅检查哨兵越界 |

#### Tiling 支持

当算子需要传递 tiling 数据时，**不要**把 tiling 当作普通 `numpy.ndarray` 参数传入。相反，使用 `tiling_data` 关键字参数传入**原始字节**（`bytes`）。RTS 运行时会自动将 tiling 数据写入 host-side buffer，并在 kernel 参数列表末尾插入正确的地址占位符。

**混合类型（使用 `pack_tiling_data`）**

当 tiling 结构体包含 `float`、`uint64` 等混合字段时，使用 ``pack_tiling_data`` 辅助函数自动按正确的内存布局打包：

```python
from SingleOperatorLaunch import pack_tiling_data

# 对应 C 结构体：
# struct MixedTilingData { uint64_t totalLength; float eps; float repeat; };
tiling_data = pack_tiling_data(
    [("totalLength", np.uint64), ("eps", np.float32), ("repeat", np.float32)],
    {"totalLength": 1024, "eps": 1.5, "repeat": 64},
)
func(x, y, z, *mod.workspace_arrays, tiling_data=tiling_data)
```

也可以用列表按顺序传值：

```python
tiling_data = pack_tiling_data(
    [("totalLength", np.uint64), ("eps", np.float32), ("repeat", np.float32)],
    [1024, 1.5, 64],
)
```

> **为什么用 bytes？**
> - tiling 数据本质上是**内存布局固定的二进制结构体**，用 `bytes` 可以精确控制每个字段的字节顺序和类型
> - RTS 会自动将 `tiling_data` 的内容复制到 launch buffer 中，无需用户手动分配 HBM
> - 如果错误地把 tiling 当作 `numpy.ndarray` 传入，`numpy` 会把它当作普通 GM 指针处理，导致 kernel 读到错误的地址

#### Workspace 支持

当算子需要 workspace 内存时，在构造 `SourceModule` 时传入 `workspace_sizes`：

```python
# 单个 workspace
mod = SourceModule(source, kernel_name="foo", workspace_sizes=4096)

# 多个 workspace
mod = SourceModule(source, kernel_name="bar", workspace_sizes=[1024, 2048])
```

`SourceModule` 会自动生成对应大小的 `numpy.uint8` 数组，通过 `mod.workspace_arrays` 获取并手动传入 kernel：

```python
func = mod.get_function()

# 方式1：展开传入（tiling_data 通过关键字参数传递）
func(x, y, z, *mod.workspace_arrays, tiling_data=tiling_data)

# 方式2：逐个传入
ws0, ws1 = mod.workspace_arrays
func(x, y, z, ws0, ws1, tiling_data=tiling_data)

# 方式3：直接调用 SourceModule 本身（等价于 get_function()()）
mod(x, y, z, *mod.workspace_arrays, tiling_data=tiling_data)
```

> **注意**：workspace 在参数序列中位于 output 之后、tiling 之前，顺序需与 kernel 函数签名一致。tiling 数据始终通过 `tiling_data` 关键字参数传递。

#### 性能测试 (`profile`)

`get_function()` 返回的对象还提供 `profile()` 方法，基于 msprof 采集 kernel 执行耗时。

```python
result = add.profile(
    x, y, z, *mod.workspace_arrays,
    repeat_times=5,   # 采样次数
    warmup_times=2,   # warmup 次数
    tiling_data=tiling_data,
)
print(result["median_us"])   # 中位耗时（us）
print(result["result_path"]) # msprof 数据路径
```

**参数说明：**

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `*args` | — | — | 同 `__call__`，numpy.ndarray / int / float |
| `block_dim` | `int` | `None` | 覆盖默认 block_dim |
| `repeat_times` | `int` | `10` | msprof 采样迭代次数 |
| `warmup_times` | `int` | `3` | 无 msprof 的 warmup 迭代次数 |
| `result_path` | `str` | `None` | msprof 输出目录，默认 `./msprof/<kernel_name>` |
| `tiling_data` | `bytes` | `None` | tiling 原始字节数据，同 `__call__` |
| `output_indices` | `set[int]` | `None` | 输出参数索引集合（如 `{0, 2}`），同 `__call__` |

**返回值：**

| 字段 | 说明 |
|------|------|
| `median_us` | 中位 task duration（us），采集失败时为 `"UNKNOWN"` |
| `status` | `"OK"` 或 `"UNKNOWN"` |
| `repeat_times` | 实际采样次数 |
| `warmup_times` | 实际 warmup 次数 |
| `result_path` | msprof 结果目录 |

---

### `Diagnostics`

`Diagnostics` 提供 OOB 内存越界检测、kernel assert 回调、浮点溢出检测、失败数据 dump 等诊断能力。`SourceModule` 内部自动创建 `Diagnostics` 实例，一般不需用户直接操作。

#### 检测类型

| 检测 | 机制 | 触发条件 |
|------|------|---------|
| **哨兵越界** | 每个 HBM 缓冲区尾部追加 288 字节 guard region（32B 对齐填充 + 256B `0x02` 哨兵），执行后校验 | 内核写入超出缓冲区尾部，覆盖哨兵区域（写入偏移 ≤ 256B） |
| **数据不变越界** | 执行前保存 output HBM 快照，执行后对比 | 内核写入地址偏离目标缓冲区（跳过 guard，写入完全错误地址）。需通过 `output_indices` 指定哪些参数是 output |
| **Kernel Assert** | `rtSetTaskFailCallback` + `rtSetExceptionExtInfo` 注册回调，`rtStreamSynchronize` 后捕获异常码 | AIC_ERROR / VEC_ERROR / TRAP / TIMEOUT 等硬件异常 |
| **浮点溢出** | `rtCtxGetOverflowAddr` 查询硬件 overflow 标志 | 只读查询，需硬件支持（Ascend950 不支持，自动跳过） |
| **数据 Dump** | 失败时将 args HBM 内容写出到 `.bin` 文件 | 上述任一检测失败时触发 |

#### 输出示例

哨兵越界：
```
Arg 2 (float32(1007,), 4028 bytes) memory out of bound (sentinel corrupted) !!
Guard region at [0x10004c600fc0, 0x10004c6010e0): 60/288 bytes != 2 (expected).
```

数据不变越界：
```
Arg 2 (float32(1023,), 4092 bytes) memory out of bound (data unchanged) !!
The kernel wrote NOTHING to the expected output buffer.
Pre-kernel (first 16B):  10 c2 c6 ab ff ff 00 00 10 c2 c6 ab ff ff 00 00
Post-kernel (first 16B): 10 c2 c6 ab ff ff 00 00 10 c2 c6 ab ff ff 00 00
=> Identical. Kernel wrote to a different GM address.
```

Kernel Assert（VEC_ERROR）：
```
[EXCEPTION] Stream sync failed: errcode=0x7000003, desc=Core[0] AIC_ERROR occurred (VEC_ERROR)
```

#### 控制诊断

```python
# 通过 __call__ 或 profile 的关键字参数控制
add(x, y, z, output_indices={2})    # {2} 因为输出 z 从 0 开始数编号为 2

# 禁用数据不变 OOB 检测（性能测试场景，不传 output_indices 即可）
add(x, y, z)
```

失败数据 dump 输出目录：`kernel_meta/<kernel_name>/oob_dump/arg_N_<kernel_name>.bin`。

---

## 环境依赖

1. **ttk** 已安装（`pip install ttk`）
2. **CANN 工具链** 已安装并 source 环境变量（`ASCEND_HOME_PATH`、`ASCEND_OPP_PATH` 等）
3. **`ccec`** 与 **`ld.lld`** 在 `PATH` 中可用

---

## 注意事项

1. **`extern "C"` 必须添加**
   
   C++ 编译器会对函数名进行修饰（mangling），导致 RTS 注册函数时找不到符号。因此 Kernel 入口必须写：
   
   ```cpp
   extern "C" __global__ __vector__ void my_kernel(...) { ... }
   ```

2. **自动推导 kernel magic**
   
   `SourceModule` 会根据 `core_type` 自动选择正确的 binary magic：
   
   | core_type | magic |
   |-----------|-------|
   | `AiCore` | `RT_DEV_BINARY_MAGIC_ELF` |
   | `VectorCore` | `RT_DEV_BINARY_MAGIC_ELF_AIVEC` |
   | `CubeCore` | `RT_DEV_BINARY_MAGIC_ELF_AICUBE` |

3. **编译自动包含头文件路径**
   
   工具会自动添加两类 `-I` 路径：
   - 根据当前机器架构（`aarch64-linux` 或 `x86_64-linux`）从 `$ASCEND_HOME_PATH/<arch>/asc/include`（以及 impl 目录）添加 AscendC 系统头文件路径；
   - 默认把调用 `SourceModule` 的 Python 脚本所在目录加入 `-I`，因此你可以在 kernel 中使用 `#include "xxx.h"` 引入同目录下的自定义头文件。
   
   如需额外目录，可传入 `include_paths`：
   
   ```python
   mod = SourceModule(
       source=kernel_src,
       kernel_name="add_custom",
       include_paths=["/path/to/common"],
   )
   ```
   
   如需关闭自动包含脚本目录，可设置 `auto_include_script_dir=False`。

4. **ASCENDC_DUMP 选项**
   
    默认情况下 `ascendc_dump=False`，不额外添加编译选项，保持 CANN 默认的 dump 行为。如需显式启用 dump（等价于 CANN `handle_dump_options` 中检测的 `-DASCENDC_DUMP=1`），可设置：
    
    ```python
    mod = SourceModule(source, kernel_name="add_custom", ascendc_dump=True)
    ```

5. **Workspace 内存管理**
   
   当算子声明了 workspace 时，需通过 `workspace_sizes` 参数指定大小（字节）。工具会自动生成 `numpy.uint8` 数组并通过 `mod.workspace_arrays` 暴露，由用户手动传入 kernel 调用。workspace 在参数序列中位于 output 之后、tiling 之前，顺序需与 kernel 函数签名严格一致。workspace 数组的 HBM 分配与释放随其他 ndarray 参数统一管理。

6. **HBM 内存自动管理**
   
   调用 Kernel 时，`numpy.ndarray`（含 workspace 数组）会自动：
   - 主机 → 设备（HBM）拷贝
   - Kernel 执行
   - 设备 → 主机拷贝回 ndarray
   - 释放 HBM

7. **Context 与 Stream**
   
   `SourceModule` 内部会自动创建 RTS Context 与 Stream，并在对象销毁时清理资源。

---

## 与 ttk 的关系

`SingleOperatorLaunch` 依赖 `ttk` 的底层基础设施：

| 功能 | 依赖的 ttk 模块 |
|------|----------------|
| 设备信息查询 | `ttk.core_modules.dsmi.DSMIInterface` |
| 算子编译 | `ttk.core_modules.npu.op.compilation.common.CceManualCompile` |
| Kernel 注册 / 启动 / 同步 | `ttk.core_modules.runtime.RTSInterface` |
| SoC 平台检测 | `ttk.utilities.platform.get_ascend_full_soc_version` |

因此你可以独立使用 `SingleOperatorLaunch` 进行单算子快速验证，也可以与 `ttk kernel` 的批量测试流程结合使用。

---

## 示例运行

### 指定设备 ID

所有 example 都支持通过 `--device_id` 参数指定目标 NPU 设备（默认 `0`）：

```bash
cd /path/to/SingleOperatorLaunch/..
python3 SingleOperatorLaunch/examples/example_add.py --device_id 1
```

当环境中有多个 NPU 卡时，可依次指定不同 `device_id` 进行测试。

### 指定 Kernel 源码文件

所有 example 脚本都支持通过 `--kernel_src` 参数指定要编译的 AscendC 源码文件（默认使用脚本同目录下的 `.cpp` 文件）：

```bash
cd /path/to/SingleOperatorLaunch/..
python3 SingleOperatorLaunch/examples/example_add.py --kernel_src /path/to/your/add_custom.cpp
```

### 功能验证

```bash
cd /path/to/SingleOperatorLaunch/..
python3 SingleOperatorLaunch/examples/example_add.py
```

预期输出：

```
DeviceInfo(2 device(s))
  [0] Ascend910_9362 | Health:OK | Temp:44C
  ...
Compiled kernel metadata dir: .../SingleOperatorLaunch/examples/kernel_meta/add_custom
Got function: _KernelFunction(add_custom, block_dim=8)
...
[PASS] Shape [1024] passed!
```

### ReduceSum

```bash
cd /path/to/SingleOperatorLaunch/..
python3 SingleOperatorLaunch/examples/example_reducesum.py
```

### 混合类型 Tiling

```bash
cd /path/to/SingleOperatorLaunch/..
python3 SingleOperatorLaunch/examples/example_mixed_tiling.py
```

### Add（性能测试）

```bash
cd /path/to/SingleOperatorLaunch/..
python3 SingleOperatorLaunch/examples/example_add_prof.py
```

### 性能测试

```bash
cd /path/to/SingleOperatorLaunch/..
python3 SingleOperatorLaunch/examples/example_add_prof.py
```

msprof 详细数据位于 `./msprof/<kernel_name>/`，可用 msprof 工具进一步分析。