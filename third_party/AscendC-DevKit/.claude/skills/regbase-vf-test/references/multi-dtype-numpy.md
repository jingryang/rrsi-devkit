# RegBase VF 单元测试多 dtype numpy 支持指南

> 本说明用于补充 `regbase-vf-test` Skill 中“多数据类型如何在 Python 测试脚本里用 numpy 表达”的细节。阅读前请确保已经熟悉 `SingleOperatorLaunch` 的基本用法（参见 `SKILL.md` §6 及 `SingleOperatorLaunch/README.md`）。

## 1. 为什么需要这份说明

`SingleOperatorLaunch` 的 `__call__` 可以接受任意 `numpy.ndarray` 作为 GM 输入/输出，并在内部通过 `ttk.utilities.dtypes.get_dtype_width()` 计算字节数。因此测试脚本只需要正确构造 numpy dtype，并把 dtype 信息同步到 Kernel 的模板参数/tiling 中即可。

但 numpy 不原生支持 `bfloat16 / int4 / float8 / float4` 等低精度类型，直接写 `np.dtype("bfloat16")` 会报错。Ascend 测试工具链 `ttk` 在 `ttk.utilities.dtypes` 中提供了这些类型的 numpy 构造器和转换辅助函数，本说明就是教你在 VF 单元测试里如何调用它们。

## 2. dtype 字符串 → numpy dtype 对象

`ttk.utilities.dtypes.dtype_map` 已经把常见别名（如 `fp16`、`bf16`、`s8`）映射为规范名；`resolve_custom_numpy_dtypes()` 再把规范名转为 dtype 对象。建议测试脚本里统一使用下面这个 helper：

```python
from ttk.utilities.dtypes import dtype_map, resolve_custom_numpy_dtypes
import numpy as np

def to_np_dtype(dtype_str):
    if not isinstance(dtype_str, str):
        return dtype_str
    canonical = dtype_map.get(dtype_str, dtype_str)
    try:
        return np.dtype(canonical)
    except (TypeError, ValueError):
        # 对 bfloat16 / int4 / fp8 / fp4 / hifloat 等自定义类型，先由 resolve_custom_numpy_dtypes
        # 拿到 class 对象，再包一层 np.dtype()，得到带 .name 的 dtype 对象，便于后续 get_dtype_width 识别。
        return np.dtype(resolve_custom_numpy_dtypes(canonical))
```

`dtype_map` 覆盖了 `float32/float16/bfloat16/int8/uint8/int16/.../int4/float8_e5m2/float8_e4m3fn/float8_e8m0/float4_e2m1/float4_e1m2/hifloat8/hifloat4` 等常见别名。

## 3. 常用非原生 dtype 构造器

| dtype | 构造方法 | 依赖包 |
|---|---|---|
| `bfloat16` | `from ttk.utilities.dtypes import numpy_bfloat16; numpy_bfloat16()` | `ml_dtypes` |
| `int4` | `from ttk.utilities.dtypes import numpy_int4; numpy_int4()` | `ml_dtypes` |
| `float8_e5m2` | `numpy_float8_e5m2()` | `ml_dtypes` |
| `float8_e4m3fn` | `numpy_float8_e4m3fn()` | `ml_dtypes` |
| `float8_e8m0` | `numpy_float8_e8m0()` | `en_dtypes`（>=0.0.4） |
| `float4_e2m1` | `numpy_float4_e2m1()` | `en_dtypes`（>=0.0.4） |
| `float4_e1m2` | `numpy_float4_e1m2()` | `en_dtypes`（>=0.0.4） |
| `hifloat8` | `numpy_hifloat8()` | `en_dtypes`（>=0.0.4） |
| `hifloat4` | `numpy_hifloat4()` | `en_dtypes`（>=0.0.4） |

这些构造器返回的是可以直接传给 `np.array(..., dtype=...)` / `np.astype(...)` 的对象。

## 4. 用 dtype width 计算 Vector 寄存器/对齐粒度

Kernel 里经常需要按 `256B` 一个 VL 计算 `repeat_stride` 或元素对齐数。`ttk.utilities.dtypes.get_dtype_width()` 对各种 dtype 都返回字节宽度（`int4/float4` 返回 `0.5`）：

```python
from ttk.utilities.dtypes import get_dtype_width

dtype = to_np_dtype("float16")          # np.float16
w = get_dtype_width(dtype)              # 2
repeat_stride_b32 = int(256 / w)        # 128，一个 VL 的元素数
align_elem = int(32 / w)                # 16，每 32B 对齐的元素数
```

`SKILL.md` 中 `MulsRegImpl` 示例里的 `REPEAT_STRIDE_B32 = 64` 仅对 `float32` 成立；换成 `float16` 时应用 `256 / sizeof(T)` 动态计算。

## 5. 测试数据生成与取值范围

`ttk.utilities.dtypes.get_dtype_range()` 返回指定 dtype 的最小/最大值，可直接用于随机生成：

```python
from ttk.utilities.dtypes import get_dtype_range, numpy_int4

# int4
lo, hi = get_dtype_range("int4")
x = np.random.randint(lo, hi + 1, size=total_length).astype(np.int8).astype(numpy_int4())
```

对浮点低精度类型（`bfloat16 / float8 / float4`），建议先用 `float32` 在合适范围内生成随机数，再 `astype` 到目标 dtype，避免直接生成极大/极小数导致 golden 溢出：

```python
from ttk.utilities.dtypes import numpy_bfloat16

x = np.random.uniform(-1.0, 1.0, size=total_length).astype(np.float32).astype(numpy_bfloat16())
```

## 6. Golden 计算与精度比较

低精度 dtype 在 numpy 中往往不能直接做加减乘除（会报 `TypeError: No loop matching...`），所以 golden 要在更高精度下算，再转回目标 dtype 或把输出提到更高精度比较。

`ttk.utilities.dtypes.DTYPE_PROMOTE_MAP` 给出了推荐的上扩 dtype：

```python
from ttk.utilities.dtypes import DTYPE_PROMOTE_MAP

promote_dtype = np.dtype(DTYPE_PROMOTE_MAP.get("bfloat16", "float32"))
x_fp = x.astype(promote_dtype)
golden = x_fp * scalar  # 在 float32 上计算
```

整数类型没有固定 promote map，但同样建议在 `int64` / `float64` 上算 golden，避免中间溢出：

```python
golden = x.astype(np.int64) * scalar
```

**精度判定走生态精度标准（MERE/MARE + per-dtype 阈值），唯一实现是
`SingleOperatorLaunch.precision_check.compare_tensor`**（VF 单测生成脚本里**禁止**
手写 `np.allclose(..., rtol=..., atol=...)` 作为通过判据）。它按 output dtype 查阈值
（fp16=2^-10 / bf16=2^-7 / fp32=fp64=2^-13 / hifp32=2^-11 / fp8_e4m3fn=2^-3 /
fp8_e5m2=2^-2 / 整数 exact），golden 传**更高精度**数组即可，函数内部先截断到
output dtype 再比较；整数精确匹配，`threshold=0.0` 可强制位级一致：

```python
# bf16 输入：golden 在 float32 上算，y 保持 bf16 原生 dtype
verdict = compare_tensor(y, golden, dtype="bfloat16")

# 整数：精确匹配（自动走 exact 路径）
verdict = compare_tensor(y_int, golden_int64.astype(np.int64), dtype="int32")

# 纯搬运/位级语义：强制 bit-exact
verdict = compare_tensor(y, golden, dtype="float32", threshold=0.0)
```

`float8/float4/int4` 不建议直接按数值比较：要么 unpack/转换回
bfloat16/float32 后交给 `compare_tensor`（输出 dtype 用转换后的 dtype），
要么按位级语义传 `threshold=0.0`。

## 7. 4-bit 类型（int4 / float4）的打包与解包

numpy 的 `int4` / `float4` dtype 在内存中每个元素实际占 1 字节，但 NPU 期望 2 个元素紧凑打包在 1 个 `uint8` 中。`SingleOperatorLaunch` 拷贝字节时按 `get_dtype_width()` 算长度（对 `int4/float4` 算 `0.5` 字节），因此**不要把未打包的 int4/float4 numpy 数组直接传给 kernel**，否则会出现元素截断/错位。

正确做法是用 `ttk.utilities.dtypes.pack_4bits` / `unpack_4bits`（int4）或 `trans_np_bfloat16_tensor_to_fp4_*` / `trans_np_fp4_*_tensor_to_bfloat16`（float4）手动转换。Kernel 侧输入 buffer 用 `uint8_t` 接收，再在 VF 里 `reinterpret_cast` 到 `int4x2_t` / `fp4x2_e2m1_t`。

### 7.1 int4 示例

```python
from ttk.utilities.dtypes import numpy_int4, pack_4bits, unpack_4bits

# 生成 int4 测试数据
x_i4 = np.random.randint(-8, 9, size=total_length).astype(np.int8).astype(numpy_int4())

# 打包为 uint8（2 个元素 / 字节），再传给 kernel
x_packed = pack_4bits(x_i4)   # 形状需为 1D；多维请先 reshape

# kernel 输出 buffer 也用 uint8
y_packed = np.zeros(x_packed.shape, dtype=np.uint8)

# 调用 kernel ...
# muls_reg_func(x_packed, y_packed, ...)

# 解包回 int4 做 golden 比较
y_i4 = unpack_4bits(y_packed, numpy_int4())
```

### 7.2 float4 示例（以 `float4_e2m1` 为例）

```python
from ttk.utilities.dtypes import numpy_bfloat16, numpy_float4_e2m1
from ttk.utilities.dtypes import trans_np_bfloat16_tensor_to_fp4_e2m1
from ttk.utilities.dtypes import trans_np_fp4_e2m1_tensor_to_bfloat16

# 1. 用 float32 生成随机数，截断为 bfloat16
x_bf16 = np.random.uniform(-1, 1, size=(rows, cols * 2)).astype(np.float32).astype(numpy_bfloat16())

# 2. 转换为 NPU 认识的 uint8 打包格式（2 个 fp4 / 字节）
x_fp4_u8 = trans_np_bfloat16_tensor_to_fp4_e2m1(x_bf16)  # shape (rows, cols)

# 3. kernel 输出同样用 uint8
y_fp4_u8 = np.zeros_like(x_fp4_u8)

# 4. 执行后转回 bfloat16 / float32 做比较
y_bf16 = trans_np_fp4_e2m1_tensor_to_bfloat16(y_fp4_u8)
y_fp32 = y_bf16.astype(np.float32)
```

## 8. FP8 E8M0 的编码

`float8_e8m0` 只保存指数，没有尾数，通常由 `bfloat16/float16/float32` 的指数部分编码而来。`ttk.utilities.dtypes.encode_float8_e8m0()` 提供了直接转换：

```python
from ttk.utilities.dtypes import numpy_bfloat16, numpy_float8_e8m0
from ttk.utilities.dtypes import encode_float8_e8m0

x_bf16 = np.random.uniform(-1, 1, size=total_length).astype(np.float32).astype(numpy_bfloat16())
x_e8m0 = encode_float8_e8m0(x_bf16)
```

## 9. MX 量化相关 dtype

对于 `float8/float4` + `scale` 的 MX 量化场景，`ttk.utilities.dtypes` 还提供了：

- `mx_quantize(fp_array, mx_ele_dtype, axis, block_size, round_mode, scale_alg)` — 普通 MX 量化
- `grouped_mx_quantize(fp_array, group_index, mx_ele_dtype, axis, block_size, round_mode)` — 分组 MX 量化

它们直接产出 `scale`（`float8_e8m0`）和 `element`（目标 fp8/fp4）两个 numpy 数组。MX 相关 VF 测试通常需要配合 `anti_mx_quant_vf_golden.py` 等专用 golden 函数，具体实现参考 `$SKILL_ROOT/references/vf_experiences/dequant-quant/` 下的条目。

## 11. 各特殊 dtype 完整示例

以下示例都是“端到端片段”：生成输入 → 声明输出 → 调用 kernel（用 `SingleOperatorLaunch` 或 `KernelLaunch`） → 计算 Golden → 比较。你可以根据实际 VF 函数替换计算逻辑。

### 11.1 bfloat16 示例

```python
from ttk.utilities.dtypes import numpy_bfloat16, get_dtype_width
import numpy as np

DTYPE = numpy_bfloat16()
W = get_dtype_width(DTYPE)             # 2
REPEAT_STRIDE_B32 = int(256 / W)       # 128
ALIGN_ELEM = int(32 / W)               # 16

N = 256
scalar = 2.0

x = np.random.uniform(-1.0, 1.0, size=N).astype(np.float32).astype(DTYPE)
y = np.zeros(N, dtype=DTYPE)

# SingleOperatorLaunch: muls_reg_func(x, y, *mod.workspace_arrays, tiling_data=..., output_indices={1})
# KernelLaunch: launcher.set_input(0, x); launcher.set_output(0, (N,), dtype=DTYPE); y = launcher.run()[0]

x_f = x.astype(np.float32)
golden = x_f * scalar
from SingleOperatorLaunch.precision_check import compare_tensor
verdict = compare_tensor(y, golden, dtype="bfloat16")  # golden 内部截断到 bf16
is_pass, max_diff = verdict.passed, verdict.max_diff
```

### 11.2 float16 示例

```python
import numpy as np
from ttk.utilities.dtypes import get_dtype_width

DTYPE = np.float16
W = get_dtype_width(DTYPE)             # 2
REPEAT_STRIDE_B32 = int(256 / W)       # 128
ALIGN_ELEM = int(32 / W)               # 16

N = 256
x = np.random.uniform(-1.0, 1.0, size=N).astype(np.float32).astype(DTYPE)
y = np.zeros(N, dtype=DTYPE)

# 调用 kernel ...

golden = x.astype(np.float32) * 2.0
from SingleOperatorLaunch.precision_check import compare_tensor
verdict = compare_tensor(y, golden, dtype="float16")
is_pass = verdict.passed
```

### 11.3 int4 示例（必须打包）

```python
from ttk.utilities.dtypes import numpy_int4, pack_4bits, unpack_4bits, get_dtype_width
import numpy as np

N = 64                                  # 元素数必须是偶数
W = get_dtype_width("int4")              # 0.5
ALIGN_ELEM = int(32 / W)                # 64

# 生成 int4 数据并打包成 uint8
x_i4 = np.random.randint(-8, 8, size=N).astype(np.int8).astype(numpy_int4())
x_u8 = pack_4bits(x_i4)                 # shape (N/2,), dtype uint8
y_u8 = np.zeros_like(x_u8)

# 调用 kernel：输入/输出 buffer 在 kernel 内用 uint8_t 接收，再 reinterpret_cast 到 int4x2_t
# muls_reg_func(x_u8, y_u8, ...)

# 解包回 int4 做 golden（整数走 compare_tensor exact 路径）
y_i4 = unpack_4bits(y_u8, numpy_int4())
golden = x_i4.astype(np.int64) * 2
from SingleOperatorLaunch.precision_check import compare_tensor
verdict = compare_tensor(y_i4.astype(np.int64), golden, dtype="int64")
is_pass = verdict.passed
```

### 11.4 float8_e5m2 示例

```python
from ttk.utilities.dtypes import numpy_float8_e5m2, get_dtype_width
import numpy as np

DTYPE = numpy_float8_e5m2()
W = get_dtype_width(DTYPE)             # 1
REPEAT_STRIDE_B32 = int(256 / W)       # 256

N = 256
x = np.random.uniform(-1.0, 1.0, size=N).astype(np.float32).astype(DTYPE)
y = np.zeros(N, dtype=DTYPE)

# 调用 kernel ...

golden = x.astype(np.float32) * 2.0
# FP8 输出 → 按 float8_e5m2 生态阈值判定（compare_tensor 支持 fp8 dtype）
from SingleOperatorLaunch.precision_check import compare_tensor
verdict = compare_tensor(y, golden, dtype="float8_e5m2")
is_pass = verdict.passed
```

### 11.5 float8_e8m0 示例（指数编码）

```python
from ttk.utilities.dtypes import numpy_bfloat16, numpy_float8_e8m0, encode_float8_e8m0
import numpy as np

N = 256
x_bf16 = np.random.uniform(-1.0, 1.0, size=N).astype(np.float32).astype(numpy_bfloat16())
x_e8m0 = encode_float8_e8m0(x_bf16)     # 仅保留指数部分
y_e8m0 = np.zeros_like(x_e8m0)

# 调用 kernel ...

# 比较通常转回 bfloat16/float32 后按最大误差判断
```

### 11.6 float4_e2m1 示例（从 bfloat16 转换）

```python
from ttk.utilities.dtypes import numpy_bfloat16, numpy_float4_e2m1
from ttk.utilities.dtypes import trans_np_bfloat16_tensor_to_fp4_e2m1
from ttk.utilities.dtypes import trans_np_fp4_e2m1_tensor_to_bfloat16
import numpy as np

rows, cols = 4, 64                       # 打包后每行 cols 个 uint8，原始 bf16 每行 cols*2 个元素
x_bf16 = np.random.uniform(-1.0, 1.0, size=(rows, cols * 2)).astype(np.float32).astype(numpy_bfloat16())

x_fp4_u8 = trans_np_bfloat16_tensor_to_fp4_e2m1(x_bf16)  # shape (rows, cols), dtype uint8
y_fp4_u8 = np.zeros_like(x_fp4_u8)

# 调用 kernel：输入/输出用 uint8_t 接收，在 VF 里 reinterpret_cast 为 fp4x2_e2m1_t
# muls_reg_func(x_fp4_u8, y_fp4_u8, ...)

# 转回 bfloat16 / float32 比较
y_bf16 = trans_np_fp4_e2m1_tensor_to_bfloat16(y_fp4_u8)

# kernel 输出为 fp4 量化值 → golden 需先过同一 fp4 量化再比（requant），
# 转回 bf16 后交 compare_tensor 判定（禁止用宽松 np.allclose 掩盖量化）
golden_bf16 = (x_bf16.astype(np.float32) * 2.0).astype(numpy_bfloat16())
golden_fp4_u8 = trans_np_bfloat16_tensor_to_fp4_e2m1(golden_bf16)
golden_bf16_2 = trans_np_fp4_e2m1_tensor_to_bfloat16(golden_fp4_u8)
from SingleOperatorLaunch.precision_check import compare_tensor
verdict = compare_tensor(y_bf16, golden_bf16_2.astype(np.float32), dtype="bfloat16")
is_pass, max_diff = verdict.passed, verdict.max_diff
```

### 11.7 hifloat8 / hifloat4 示例

```python
from ttk.utilities.dtypes import numpy_hifloat8, numpy_hifloat4
import numpy as np

# hifloat8：1 字节，可直接当 dtype 使用
N = 128
x_h8 = np.random.uniform(-1.0, 1.0, size=N).astype(np.float32).astype(numpy_hifloat8())
y_h8 = np.zeros(N, dtype=numpy_hifloat8())

# 调用 kernel ...

# hifloat4：实际底层为 float4_e1m2，需要打包成 uint8
N = 128
x_h4 = np.random.uniform(-1.0, 1.0, size=N).astype(np.float32).astype(numpy_hifloat4())
# 注意 hifloat4 也是 4-bit，2 个元素 / 字节；可用 pack_4bits 打包
from ttk.utilities.dtypes import pack_4bits, unpack_4bits
x_h4_u8 = pack_4bits(x_h4)              # shape (N/2,), dtype uint8
y_h4_u8 = np.zeros_like(x_h4_u8)

# 调用 kernel ...

# 解包时指定 numpy_hifloat4()（底层为 float4_e1m2）
y_h4 = unpack_4bits(y_h4_u8, numpy_hifloat4())
```

## 12. 注意事项

1. **`pack_tiling_data` 只支持标准 numpy 整数/浮点类型**（`np.uint8/16/32/64`、`np.int8/16/32/64`、`np.float16/32/64`），不要把 `bfloat16 / int4` 等低精度类型放在 tiling 结构体里。
2. `SourceModule` 的 `__call__` 对 numpy 数组按 `get_dtype_width()` 计算字节数，**dtype 对象本身必须能被 `get_dtype_width` 识别**。`ttk.utilities.dtypes` 中列出的类型均已处理。
3. 对 `bfloat16` 做 `np.max` / `np.sum` 等聚合操作时，若 numpy 报 `TypeError: No loop matching...`，说明当前环境把 `bfloat16` 当作“不可计算”类型。此时先把数组 `astype(np.float32)` 再计算，这正是 `DTYPE_PROMOTE_MAP` 推荐的做法。
4. 4-bit 类型打包后，最后一维长度会减半，设计 `output` numpy buffer 形状时务必按打包后的 `uint8` 形状分配，而不是原始元素数量。
5. 不确定 dtype 在环境是否可用时，先用 `python3 -c "from ttk.utilities.dtypes import numpy_bfloat16; print(numpy_bfloat16())"` 验证对应依赖包（`ml_dtypes` / `en_dtypes`）是否已安装。
