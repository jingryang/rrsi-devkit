# KernelLaunch

昇腾 NPU 单算子二进制 Kernel 启动器。依赖 TTK（`binary_kernel_match`、`dyn_do_tiling`、`RTSInterface`），提供简单的 Kernel 级算子测试能力。

主要特点：

- **binary kernel 模式**：使用 OPP 预编译 binary kernel 执行（`ttk kernel -b=release` 等效），不进行 TBE 动态编译。
- **无 camodel 依赖**：仅支持真实 NPU 设备。
- **OOB 自动检测**：每次 `run()` 后执行哨兵检查和数据不变检查，帮助发现越界写入。
- **内置 RegBase 静态检查**：`static_check()` 自动定位算子源码并执行 `__simd_vf__` / `__simd_callee__` 规范预检，编译前可选强制执行。
- **多 dtype 支持**：原生支持 numpy dtype 及 `bfloat16`、`float8` 等扩展类型。

## 快速开始

```python
import sys
import numpy as np

sys.path.insert(0, ".")
from KernelLaunch import KernelLauncher, setup_log_separation

setup_log_separation(log_file="log_add.log", result_file="result_add.log")

launcher = KernelLauncher("add", device_id=0)
launcher.show_op_info()   # 打印算子签名 + 动态脚本路径

shape = (8, 1024)
launcher.set_input(0, np.random.randn(*shape).astype(np.float16))
launcher.set_input(1, np.random.randn(*shape).astype(np.float16))
launcher.set_output(0, shape=shape, dtype=np.float16)

outputs = launcher.run()
launcher.close()

result = outputs[0]  # np.ndarray
```

## 安装

本工程依赖 ttk 包，且需要 `KernelLaunch/` 目录在 Python 导入路径上。

```bash
export ASCEND_OPP_PATH=/path/to/Ascend/opp

# KernelLaunch 所在父目录需在 Python 路径上
cd /path/to/KernelLaunch/..
python3 KernelLaunch/examples/run_add.py
```

## API

### `KernelLauncher(op_name, device_id=0, kernel_meta=None, static_check=False)`

启动器。

| 参数 | 说明 |
|------|------|
| `op_name` | 算子名，snake_case（如 `add`、`add_rms_norm`） |
| `device_id` | NPU 设备号，默认 0 |
| `kernel_meta` | kernel_meta 根目录，默认 None（使用当前目录 `kernel_meta/`，并追加 `op_name` 子目录） |
| `static_check` | 是否在 `run()` 前自动执行内置 RegBase 静态检查，默认 `False` |

**方法：**

| 方法 | 说明 |
|------|------|
| `set_input(index, tensor, dtype_override=None)` | 设置第 `index` 个输入，支持 `torch.Tensor` / `np.ndarray`；`dtype_override` 强制指定 dtype 字符串 |
| `set_output(index, shape, dtype)` | 设置第 `index` 个输出的 shape 和 dtype |
| `set_attr(index, value)` | 设置第 `index` 个属性的值 |
| `show_op_info()` | 打印当前算子的 input / output / attr 签名，以及动态算子脚本路径 |
| `locate_op_source(op_name=None)` | 定位算子 AscendC 内核源码 `.cpp` 路径（通过算子注册信息推导） |
| `static_check(op_name=None, raise_on_failure=True)` | 对定位到的内核源码执行内置 RegBase 静态检查，返回 `StaticCheckReport` |
| `run()` | 执行：binary match → tiling → launch → OOB 检测，返回 `List[np.ndarray]` |
| `run_case(case, golden_fn, seed=42)` | 一键跑单个 cann-bench case：生成输入 → 设置 attrs → 启动 kernel → 按 MERE/MARE 标准与 golden 比较，返回 `compare_outputs` 结果 dict（见下文「Golden 函数与精度比较」） |
| `close()` | 释放 NPU 设备资源 |

`run()` 返回的输出列表顺序与 `set_output` 的 index 一致。

支持 `with` 上下文管理器，自动调用 `close()`。

### `show_op_info` 输出示例

```text
Operator: add  (type: Add)
  Script: /root/Ascend/cann-9.1.0/opp/built-in/op_impl/ai_core/tbe/impl/ops_math/dynamic/add_apt.py
  Inputs:
    [0] x1  dtype=['float16', 'float32', ...]  format=['ND', ...]  paramType=required
    [1] x2  dtype=['float16', 'float32', ...]  format=['ND', ...]  paramType=required
  Outputs:
    [0] y  dtype=['float16', 'float32', ...]  format=['ND', ...]
```

脚本路径由 `_impl_base_path` + `_ops_group` + `opFile.value` 拼接得到；若脚本不存在，则回退打印 `Impl base:`。

### 内置 RegBase 静态检查

`KernelLaunch` 自带一套轻量、基于正则的 AscendC 内核源码静态检查逻辑（`KernelLaunch/static_check.py`，不依赖外部工具）。它扫描 `__simd_vf__` / `__simd_callee__` 函数并检查 RegBase 编程规范，帮助在昂贵的 `ccec` 编译之前尽早发现问题。

```python
from KernelLaunch import KernelLauncher

launcher = KernelLauncher("add", device_id=0)

# 自动定位算子源码并执行静态检查
report = launcher.static_check("add", raise_on_failure=False)
print(report.passed)          # True / False
for failure in report.failures:
    print(failure.name, failure.message)

# 默认 raise_on_failure=True：发现违规直接抛异常
launcher.static_check("add")
```

算子源码路径通过算子注册信息自动推导：`{impl_base_path}/impl/{ops_group}/ascendc/{op_interface}/{op_file}.cpp`。若算子未注册或源码缺失，`static_check()` 会抛出 `RuntimeError`。

也可以在构造时开启自动检查，使 `run()` 在编译前强制执行：

```python
launcher = KernelLauncher("add", device_id=0, static_check=True)  # run() 前自动检查
```

当前检查规则：

| 检查项 | 说明 |
|--------|------|
| `simd_vf_modifiers` | `__simd_vf__` / `__simd_callee__` 函数是否带 `inline` 关键字 |
| `simd_vf_ubuf_access` | SIMD 函数体内是否用 `ptr[i]` 直接访问 `__ubuf__` |
| `simd_vf_no_gm` | SIMD 函数体内/参数是否出现 GM/HBM 访问（`GM_ADDR`、`__gm__`、`GlobalTensor`、`SetGlobalBuffer`） |
| `hardware_loop_var_type` | SIMD 函数 `for` 循环变量是否为 `uint16_t` |
| `hardware_loop_branch` | SIMD 函数 `for` 循环体内是否包含运行时 `if/else` 或三目 `?:`（`if constexpr` 除外） |
| `hardware_loop_var_mutation` | `UpdateMask<T>(var)` 的参数是否在循环体内被重新赋值/修改 |
| `vf_function_level_branch` | SIMD 函数在循环体外是否包含运行时分支 |

> 这些检查基于正则实现，属于快速预检，不能替代 `ccec` 编译检查。复杂场景下可能存在误报或漏报，需要结合人工判断。

也可直接使用库接口：

```python
from KernelLaunch import check_regbase_source

report = check_regbase_source(source_code, "add_custom", raise_on_failure=False)
```

### OOB 检测

`run()` 执行后自动进行两阶段 OOB（Out-of-Bounds）检测：

1. **哨兵检查（Sentinel check）**：检测 kernel 是否写超了 HBM 分配边界。分配 output/workspace 时在 buffer 末尾写入哨兵值（`OOB_SENTINEL=2`），kernel 执行后回读对比。写入超尾则哨兵被覆盖，报 `FAIL`。

2. **数据不变检查（Data-change / Silent OOB check）**：执行前保存 output HBM 快照，执行后对比。若数据完全未变，说明 kernel 写到了错误地址（静默越界），报 `data unchanged`。此检查可发现 kernel 未向预期输出地址写入任何数据的场景。

> 注意：某些特殊算子（如 `zeros_like`）输出本就为 0，会触发数据不变检查的误报，但数值结果仍可能正确。

检测结果打印格式：
```
OOB check: output=['OK', 'OK', 'FAIL'], workspace=['OK']
```
- `OK`：哨兵完整 + 数据已更新（正常）
- `FAIL`：哨兵损坏 或 数据未变（越界）

## 测试

`KernelLaunch/tests/` 下提供了 pytest 测试用例：

```bash
# 运行所有测试（需要 NPU）
python3 -m pytest KernelLaunch/tests/ -v --device-id=0

# 仅运行无需 NPU 的单元测试
python3 -m pytest KernelLaunch/tests/ -v -m "not npu"

# 运行单个集成测试
python3 -m pytest KernelLaunch/tests/test_launcher_integration.py -v --device-id=0 -k "test_add_float32"
```

测试分类：

- `test_import.py`：导入与默认参数检查。
- `test_launcher_unit.py`：无需 NPU，mock TTK 环境，验证构造、输入输出设置、`_build_testcase`、上下文管理等。
- `test_static_check.py`：无需 NPU，验证内置 RegBase 静态检查逻辑以及 `locate_op_source()` / `static_check()` 的接入。
- `test_launcher_integration.py`：标记 `npu`，依赖真实 NPU，验证 `add`、`add_rms_norm`、`tensor_move` 等算子的 float32/float16/bfloat16/FP8 执行。

## 示例

### Add

```python
import sys
import numpy as np

sys.path.insert(0, ".")
from KernelLaunch import KernelLauncher, setup_log_separation
setup_log_separation(log_file="log_add.log", result_file="result_add.log")

def compute_golden(inputs):
    return [inputs[0] + inputs[1]]

def precision_test(output, golden, rtol=1e-3, atol=1e-3):
    is_pass = np.allclose(output, golden, rtol=rtol, atol=atol)
    max_diff = np.max(np.abs(output.astype(np.float64) - golden.astype(np.float64)))
    return is_pass, max_diff

launcher = KernelLauncher("add", device_id=0)
launcher.show_op_info()

shape = (8, 1024)
a = np.random.randn(*shape).astype(np.float32)
b = np.random.randn(*shape).astype(np.float32)
launcher.set_input(0, a)
launcher.set_input(1, b)
launcher.set_output(0, shape, dtype=np.float32)

outputs = launcher.run()
launcher.close()

golden = compute_golden([a, b])[0]
is_pass, max_diff = precision_test(outputs[0], golden)
print(f"{'PASS' if is_pass else 'FAIL'}  max_diff={max_diff:.2e}")
```

详见 [`examples/run_add.py`](examples/run_add.py)。

### AddRmsNorm

```python
import sys
import numpy as np

sys.path.insert(0, ".")
from KernelLaunch import KernelLauncher, setup_log_separation
setup_log_separation(log_file="log_add_rms_norm.log",
                     result_file="result_add_rms_norm.log")

def compute_golden(inputs, epsilon=1e-5):
    x1, x2, gamma = inputs
    x = x1 + x2
    rms = np.sqrt(np.mean(x.astype(np.float64) ** 2, axis=-1, keepdims=True) + epsilon)
    y = (x / rms) * gamma
    return [y.astype(x1.dtype), (1.0 / rms).astype(x1.dtype), x.astype(x1.dtype)]

def precision_test(output, golden, rtol=1e-3, atol=1e-3):
    is_pass = np.allclose(output, golden, rtol=rtol, atol=atol)
    max_diff = np.max(np.abs(output.astype(np.float64) - golden.astype(np.float64)))
    return is_pass, max_diff

B, S, H = 4, 128, 256
dtype = np.float32
x1 = np.random.randn(B, S, H).astype(dtype)
x2 = np.random.randn(B, S, H).astype(dtype)
gamma = np.random.randn(H).astype(dtype)

launcher = KernelLauncher("add_rms_norm", device_id=0)
launcher.show_op_info()
launcher.set_input(0, x1)
launcher.set_input(1, x2)
launcher.set_input(2, gamma)
launcher.set_attr(0, 1e-5)
launcher.set_output(0, (B, S, H), dtype=dtype)
launcher.set_output(1, (B, S, 1), dtype=np.float32)
launcher.set_output(2, (B, S, H), dtype=dtype)

outputs = launcher.run()
launcher.close()

golden = compute_golden([x1, x2, gamma])
for idx, name in enumerate(["yOut", "rstdOut", "xOut"]):
    is_pass, max_diff = precision_test(outputs[idx], golden[idx])
    print(f"[{name}] {'PASS' if is_pass else 'FAIL'}  max_diff={max_diff:.2e}")
```

详见 [`examples/run_add_rms_norm.py`](examples/run_add_rms_norm.py)。

## Golden 函数与精度比较

KernelLaunch 提供两种路径与 golden 对比：

- **手动路径**（简单场景）：自己实现 golden 与精度比较逻辑。
- **cann-bench 路径**（推荐生产场景）：加载 cann-bench 任务目录下的 `golden.py` 与 `cases.csv`，用 MERE/MARE 标准比较。

所有工具（`load_golden`、`load_cases`、`find_task_asset`、`compare_outputs`）均可从 `KernelLaunch` 顶层直接导入：

```python
from KernelLaunch import (
    KernelLauncher, load_golden, load_cases,
    find_task_asset, compare_outputs, setup_log_separation,
)
```

完整端到端示例见 [`examples/run_exp_with_cannbench.py`](examples/run_exp_with_cannbench.py)。

---

### 1. 手动 golden + 精度比较（简单场景）

适用于快速单 case 验证，golden 逻辑简单可直接内联：

```python
def compute_golden(inputs):
    return [inputs[0] + inputs[1]]

def precision_test(output, golden, rtol=1e-3, atol=1e-3):
    is_pass = np.allclose(output, golden, rtol=rtol, atol=atol)
    max_diff = np.max(np.abs(output.astype(np.float64) - golden.astype(np.float64)))
    return is_pass, max_diff

outputs = launcher.run()
golden = compute_golden([a, b])[0]
is_pass, max_diff = precision_test(outputs[0], golden)
print(f"{'PASS' if is_pass else 'FAIL'}  max_diff={max_diff:.2e}")
```

`max_diff` 在 float64 下计算以避免下溢出。低精度 dtype（BF16/FP8）需按 [`精度容差`](#精度容差) 放宽 `rtol` / `atol`。

详见 [`examples/run_add.py`](examples/run_add.py)。

### 2. 手动比较也可用 MERE/MARE 标准：`compare_outputs`

`compare_outputs` 委托 `ascendc_devkit.precision_compare`，与 run-cases 同等标准：

```python
from KernelLaunch import compare_outputs

result = compare_outputs(outputs, golden)
print(result["passed"], result["mare"])
for po in result["per_output"]:
    print(f"  out[{po['index']}] {po['dtype']} passed={po['passed']} "
          f"MERE={po['mere']:.2e} MARE={po['mare']:.2e}")
```

返回 dict 字段：

| 字段 | 含义 |
|------|------|
| `passed` | 全部输出是否通过（bool） |
| `mere` | 加权平均相对误差 |
| `mare` | 最大相对误差 |
| `max_diff` | 最大绝对误差 |
| `mean_diff` | 加权平均绝对误差 |
| `mismatch_count` / `total_count` | 失配元素数 / 总元素数 |
| `threshold` / `dtype` | 首个失败输出的阈值 / dtype |
| `error_msg` | 顶层错误信息（通过时为空） |
| `per_output` | 每输出 verdict（index/dtype/passed/mere/mare/max_diff/mismatch_count/total_count/threshold/error_msg） |

阈值可按 dtype 覆盖（优先级 `proto > thresholds > 默认值`）：

```python
result = compare_outputs(outputs, golden, thresholds={"float16": 1e-2})
```

---

### 3. 加载 cann-bench golden：`find_task_asset` + `load_golden`

cann-bench 任务目录结构通常为 `{cannbench_dir}/tasks/{level}/{op_name}/golden.py`，其中
`golden.py` 定义期望计算函数，`cases.csv` 定义多组 (shape, dtype, attrs) 测试用例。

#### `find_task_asset` — 自动定位任务资源

扫描任务目录树，返回第一个匹配文件的绝对路径：

```python
from KernelLaunch import find_task_asset

golden_path = find_task_asset(
    "/path/to/cann-bench",      # 任务根目录
    "exp",                       # 算子名
    "golden.py",                 # 文件名（golden.py 或 cases.csv）
)
```

内部逻辑：遍历 `{task_dir}/tasks/{level0..level4}/{op_name}/{filename}`，返回首个命中。

#### `load_golden` — 加载 golden 可调用函数

从 `golden.py` 加载 golden 函数，遵循 devkit harness 契约（importlib + wrap）。返回
`fn(*inputs, **attrs) -> List[np.ndarray]`（单输出也会包成 list）：

```python
from KernelLaunch import load_golden, find_task_asset

golden_fn = load_golden(
    find_task_asset(cannbench_dir, "exp", "golden.py"),
    entry="exp",            # golden.py 中的函数名（cann-bench 惯例用算子名）
    input_type="torch",     # "numpy"（默认）或 "torch"
)

# 调用：传入 numpy 数组 + 算子属性
result = golden_fn(input_a, input_b, epsilon=1e-5)
# → List[np.ndarray]
```

参数：

| 参数 | 说明 |
|------|------|
| `golden_path` | `golden.py` 的绝对路径 |
| `entry` | 函数名。cann-bench 惯例用算子名（如 `"exp"`、`"add_rms_norm"`）；手写 fixture 用 `"reference"` |
| `input_type` | `"numpy"`（默认）或 `"torch"`。golden 期望的输入类型：若 golden 函数内用了 `torch` API，选 `"torch"`；否则 `"numpy"` |

> **何时用 `input_type="torch"`**：cann-bench 自带的 golden.py 多使用 PyTorch
> 实现（`torch.sum`、`torch.sqrt` 等），此时需 `input_type="torch"`，`load_golden`
> 会在调用前自动做 `torch.from_numpy()` 转换，并将返回值转回 `np.ndarray`。

#### `load_cases` — 加载 cases.csv

解析 cann-bench 标准 CSV（`operator, case_id, input_shape, dtype, attrs, value_range, note`），返回 list[dict]：

```python
from KernelLaunch import load_cases, find_task_asset

cases = load_cases(find_task_asset(cannbench_dir, "exp", "cases.csv"))

# 可选过滤
cases = load_cases(csv_path, case_ids=[1, 3, 5])   # 只加载指定 case
cases = load_cases(csv_path, skip_large={7, 9})    # 跳过超大 case
```

每个 case dict 结构：

| 键 | 类型 | 含义 |
|----|------|------|
| `case_id` | `int` | 用例编号 |
| `shape` | `tuple[int]` | 输入 shape |
| `dtype` | numpy dtype | 数据类型 |
| `attrs` | `dict[str, float]` | 算子属性 key→value |
| `value_range` | `tuple[float, float]` | 输入随机值范围（NaN/Inf 用特殊值） |
| `note` | `str` | 备注 |

---

### 4. 一键跑 case：`run_case`（推荐）

`run_case(case, golden_fn)` 串起「生成输入 → 设置 attrs → launch kernel → MERE/MARE 比较」：

```python
from KernelLaunch import KernelLauncher, find_task_asset, load_cases, load_golden, setup_log_separation

setup_log_separation(log_file="log_exp.log", result_file="result_exp.log")

OP_NAME = "exp"

golden_fn = load_golden(
    find_task_asset(cannbench_dir, OP_NAME, "golden.py"),
    entry=OP_NAME, input_type="torch",
)
cases = load_cases(find_task_asset(cannbench_dir, OP_NAME, "cases.csv"))
print(f"[{OP_NAME}] golden + {len(cases)} cases loaded")

launcher = KernelLauncher(OP_NAME, device_id=7)

for c in cases:
    result = launcher.run_case(c, golden_fn)

    marker = "PASS" if result["passed"] else "FAIL"
    print(f"#{c['case_id']:3d} shape={c['shape']} [{marker}] "
          f"MERE={result['mere']:.2e} MARE={result['mare']:.2e} "
          f"max_diff={result['max_diff']:.2e}")

    # 逐输出详细
    for po in result["per_output"]:
        print(f"  out[{po['index']}] {po['dtype']} passed={po['passed']} "
              f"thr={po['threshold']:.2e} "
              f"MERE={po['mere']:.2e} MARE={po['mare']:.2e}")

launcher.close()

# 汇总
n_pass = sum(1 for c in cases if launcher.run_case(c, golden_fn)["passed"])
print(f"Passed: {n_pass}/{len(cases)}")
```

`run_case` 返回与 `compare_outputs` 相同结构的 dict。

> `run_case` 内部自动处理：随机种子输入生成、attr 名称到 launcher index 的映射、
> bf16↔float32 转换、单输入算子的 shape/dtype 适配。

完整示例见 [`examples/run_exp_with_cannbench.py`](examples/run_exp_with_cannbench.py)。

## 多 Dtype 支持

KernelLaunch 通过 TTK 的 dtype 工具统一处理各类 dtype，无需手动位操作。

### 支持列表

| dtype | 写法 | 说明 | 底层库 |
|-------|------|------|--------|
| float32 | `np.float32` | numpy 原生 | numpy |
| float16 | `np.float16` | numpy 原生 | numpy |
| float64 | `np.float64` | numpy 原生 | numpy |
| int8 / int16 / int32 / int64 | `np.int8` … | numpy 原生 | numpy |
| uint8 / uint16 / uint32 / uint64 | `np.uint8` … | numpy 原生 | numpy |
| bool | `np.bool_` | numpy 原生 | numpy |
| bfloat16 | `numpy_bfloat16()` | `ttk.utilities.dtypes.numpy_bfloat16()` | `ml_dtypes` |
| int4 | `numpy_int4()` | `ttk.utilities.dtypes.numpy_int4()` | `ml_dtypes` |
| float8_e5m2 | `numpy_float8_e5m2()` | `ttk.utilities.dtypes.numpy_float8_e5m2()` | `ml_dtypes` |
| float8_e4m3fn | `numpy_float8_e4m3fn()` | `ttk.utilities.dtypes.numpy_float8_e4m3fn()` | `ml_dtypes` |
| float8_e8m0 | `numpy_float8_e8m0()` | `ttk.utilities.dtypes.numpy_float8_e8m0()` | `en_dtypes` |
| float4_e2m1 | `numpy_float4_e2m1()` | `ttk.utilities.dtypes.numpy_float4_e2m1()` | `en_dtypes` |
| float4_e1m2 | `numpy_float4_e1m2()` | `ttk.utilities.dtypes.numpy_float4_e1m2()` | `en_dtypes` |
| hifloat8 | `numpy_hifloat8()` | `ttk.utilities.dtypes.numpy_hifloat8()` | `en_dtypes` |
| hifloat4 | `numpy_hifloat4()` | `ttk.utilities.dtypes.numpy_hifloat4()` | `en_dtypes` |

> int4/float4 是 4-bit 类型，numpy 中 1 个字节存 2 个元素，`get_dtype_width()` 返回 0.5。FP8/FP4 精度极低，默认使用 `binary_equal` 或 `requant` 比较方法，不适合 `np.allclose`。

### bfloat16 标准写法

```python
from ttk.utilities.dtypes import numpy_bfloat16
BF16 = numpy_bfloat16()

# 输入：float32 生成 → truncate 到 BF16
x = np.random.randn(8, 1024).astype(np.float32).astype(BF16)

# 输出：kernel 返回 BF16 数组 → 转回 float32 比较
result = outputs[0].astype(np.float32)

# set_output 直接传 dtype 对象
launcher.set_output(0, shape=(8, 1024), dtype=BF16)
```

### 数据流

```
float32 随机数据
    │
    ▼  .astype(BF16)    ← BF16 截断（丢掉低 16 位尾数）
BF16 numpy 数组
    │
    ▼  copy_nparray_to_hbm → kernel 执行 → get_data_from_hbm
BF16 numpy 数组（返回）
    │
    ▼  .astype(np.float32)   ← 转回 float32 用于精度比较
float32 （与 golden 对比）
```

### 精度容差

低精度 dtype 需要放宽 `rtol` / `atol`：

| dtype | rtol | atol |
|-------|------|------|
| float32 | 1e-3 | 1e-3 |
| float16 | 1e-3 | 1e-3 |
| bfloat16 | 1e-2 | 1e-2 |
| FP8 / FP4 | 按 bit 或 requant | - |

> 注意：`set_input` 不再依赖 `dtype_override` 参数。只要 numpy 数组的 dtype 已经是 `numpy_bfloat16()`，`_build_testcase()` 中的 `_np_dtype_to_str` 会自动识别为 `"bfloat16"` 传给 TTK 的 TestcaseOp。

### float8 示例（以 float8_e5m2 为例）

```python
from ttk.utilities.dtypes import numpy_float8_e5m2
FP8 = numpy_float8_e5m2()

# 输入：float32 生成 → truncate 到 FP8
x = np.random.randn(8, 1024).astype(np.float32).astype(FP8)

# 输出：kernel 返回 FP8 数组 → 转回 float32 比较
result = outputs[0].astype(np.float32)

# set_output 直接传 dtype 对象
launcher.set_output(0, shape=(8, 1024), dtype=FP8)
```

> FP8 精度很低，TTK 默认使用 `requant`（按 ULP 逐 bit 比较）而非 `np.allclose`。若仍需 `np.allclose`，建议用 `rtol=1e-1, atol=1e-1`。

详见 [`examples/run_add.py`](examples/run_add.py)（含 float32/float16/BF16）、[`examples/run_add_rms_norm.py`](examples/run_add_rms_norm.py)（含 float32）、[`examples/run_fp8_test.py`](examples/run_fp8_test.py)（含 FP8）。

## 核心逻辑

### 流水线

```
show_op_info()  →  OpInfoKeeper 读取算子注册信息 + 动态脚本路径

run():
  1. _build_testcase
     → 构造 TestcaseOp，填充 shape/dtype/format/attribute
     → 手动设置分布（distribution=0），绕过 validate 校验

  2. 编译
     → binary_kernel_match：匹配 OPP 预编译 binary kernel，失败则报错（不做动态编译）

  3. _do_tiling
     → dyn_do_tiling：调用 Optiling 引擎计算 block_dim、tiling_key、tiling_data

  4. _launch_kernel
     → rtSetDevice → rtCtxCreate → rtStreamCreate
     → 注册 kernel binary（fat-bin / non-fat-bin 分别走不同路径）
     → HBM 分配：input → output → workspace → global_workspace
     → 按 output_placeholder 决定 arg 排列顺序
     → rtKernelLaunchWithHandleV2 / rtKernelLaunchWithFlag
     → 同步
     → OOB 检测：哨兵检查 → 数据不变检查（data-change / silent OOB）
     → 回拷结果，释放资源
```

### 设计要点

- **依赖 TTK**：不重复实现 binary match、tiling 和设备管理，直接调用 `binary_kernel_match`、`dyn_do_tiling`、`RTSInterface`。
- **binary kernel 模式**：使用 OPP 预编译 binary kernel（`ttk kernel -b=release` 等效），不进行 TBE 动态编译。
- **自动 SoC 检测**：首次构造时自动探测当前 NPU 的 `full_soc_version` 与 `short_soc_version`，并设置对应环境变量。
- **懒初始化**：`__init__` 仅做环境准备，设备上下文在 `run()` 首次调用时创建。
- **安全清理**：`finally` 块确保 HBM 内存、stream、context 全部释放；`close()` 可重复调用。
- **不修改 TBE 脚本**：不会改写算子目录下的 Python 脚本。

### 地址排列约定

kernel 启动参数按以下顺序排列：

```
inputs (0..N-1) + outputs (if output_placeholder) + workspaces
```

`output_placeholder` 由 `OpInfoKeeper().op_output_defined()` 返回——若算子定义中 outputs 不占参数位置（如 Add），则不传入 outputs，由 kernel 内部推导。
