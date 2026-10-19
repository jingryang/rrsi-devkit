# op-plugin 详细模板

> **文件路径约定**：
> - 代码生成目标：`{PTA_DIR}/op-plugin/`（独立工作目录，非 pytorch 子模块）
> - 以下所有文件路径均相对于 `op-plugin/` 根目录
> - 禁止创建独立的 output 汇总目录

## § 0 dst_type 编码对应关系（统一参考）

torch_npu 自定义 dtype 通过 `c10_npu::DType` 枚举暴露到 Python 层。

**转换公式**：`c10_npu::DType = ACL枚举值 + 256`，反向 `aclDataType = DType - 256`

### 全量映射表

#### 基础类型（PyTorch 原生有对应）

| Python 属性 (`torch_npu.xxx`) | C++ DType 枚举 | ACL 枚举 | ACL 值 | DType 值 | PyTorch 原生 |
|---|---|---|---|---|---|
| `torch_npu.float32` | `FLOAT` | `ACL_FLOAT` | 0 | 256 | `torch.float32` |
| `torch_npu.float16` | `FLOAT16` | `ACL_FLOAT16` | 1 | 257 | `torch.float16` |
| `torch_npu.int8` | `INT8` | `ACL_INT8` | 2 | 258 | `torch.int8` |
| `torch_npu.int32` | `INT32` | `ACL_INT32` | 3 | 259 | `torch.int32` |
| `torch_npu.uint8` | `UINT8` | `ACL_UINT8` | 4 | 260 | `torch.uint8` |
| `torch_npu.int16` | `INT16` | `ACL_INT16` | 6 | 262 | `torch.int16` |
| `torch_npu.uint16` | `UINT16` | `ACL_UINT16` | 7 | 263 | `torch.uint16` |
| `torch_npu.uint32` | `UINT32` | `ACL_UINT32` | 8 | 264 | `torch.uint32` |
| `torch_npu.int64` | `INT64` | `ACL_INT64` | 9 | 265 | `torch.int64` |
| `torch_npu.uint64` | `UINT64` | `ACL_UINT64` | 10 | 266 | `torch.uint64` |
| `torch_npu.float64` | `DOUBLE` | `ACL_DOUBLE` | 11 | 267 | `torch.float64` |
| `torch_npu.bool` | `BOOL` | `ACL_BOOL` | 12 | 268 | `torch.bool` |
| `torch_npu.complex64` | `COMPLEX64` | `ACL_COMPLEX64` | 16 | 272 | `torch.complex64` |
| `torch_npu.complex128` | `COMPLEX128` | `ACL_COMPLEX128` | 17 | 273 | `torch.complex128` |
| `torch_npu.bfloat16` | `BF16` | `ACL_BF16` | 27 | 283 | `torch.bfloat16` |
| `torch_npu.complex32` | `COMPLEX32` | `ACL_COMPLEX32` | 33 | 289 | `torch.complex32` |

#### 扩展类型（仅 torch_npu，无 PyTorch 原生对应）

| Python 属性 (`torch_npu.xxx`) | C++ DType 枚举 | ACL 枚举 | ACL 值 | DType 值 | 说明 |
|---|---|---|---|---|---|
| `torch_npu.string` | `STRING` | `ACL_STRING` | 13 | 269 | 字符串类型 |
| `torch_npu.int4` | `INT4` | `ACL_INT4` | 29 | 285 | 4-bit 整型 |
| `torch_npu.uint1` | `UINT1` | `ACL_UINT1` | 30 | 286 | 1-bit 无符号 |

#### 低精度浮点类型（Quant 算子常用，重点关注）

| Python 属性 (`torch_npu.xxx`) | C++ DType 枚举 | ACL 枚举 | ACL 值 | DType 值 | PyTorch 原生 | 说明 |
|---|---|---|---|---|---|---|
| `torch_npu.hifloat8` | `HIFLOAT8` | `ACL_HIFLOAT8` | 34 | 290 | 无 | 华为自定义 8-bit 浮点 |
| `torch_npu.float8_e5m2` | `FLOAT8_E5M2` | `ACL_FLOAT8_E5M2` | 35 | 291 | `torch.float8_e5m2` (23) | FP8，5位指数2位尾数 |
| `torch_npu.float8_e4m3fn` | `FLOAT8_E4M3FN` | `ACL_FLOAT8_E4M3FN` | 36 | 292 | `torch.float8_e4m3fn` (24) | FP8，4位指数3位尾数 |
| `torch_npu.float8_e8m0fnu` | `FLOAT8_E8M0` | `ACL_FLOAT8_E8M0` | 37 | 293 | 无 | E8M0 scale 专用 |
| `torch_npu.float6_e3m2` | `FLOAT6_E3M2` | `ACL_FLOAT6_E3M2` | 38 | 294 | 无 | 6-bit 浮点，3位指数2位尾数 |
| `torch_npu.float6_e2m3` | `FLOAT6_E2M3` | `ACL_FLOAT6_E2M3` | 39 | 295 | 无 | 6-bit 浮点，2位指数3位尾数 |
| **`torch_npu.float4_e2m1fn_x2`** | `FLOAT4_E2M1` | `ACL_FLOAT4_E2M1` | 40 | **296** | 无 | FP4，uint8 承载，尾轴减半 |
| **`torch_npu.float4_e1m2fn_x2`** | `FLOAT4_E1M2` | `ACL_FLOAT4_E1M2` | 41 | **297** | 无 | FP4，uint8 承载，尾轴减半 |

> **注意**：Python 属性名与 C++ 枚举名不完全一致：
> - FP4 带 `fn_x2` 后缀：`float4_e2m1fn_x2`（非 `float4_e2m1`）
> - FP8 E8M0 带 `fnu` 后缀：`float8_e8m0fnu`（非 `float8_e8m0`）

### 各层使用方式

| 层级 | 传入值 | 判断方式 | 示例 |
|------|--------|----------|------|
| Python 测试 | `torch_npu.float4_e2m1fn_x2` | 直接用属性 | `dst_type=torch_npu.float8_e5m2` |
| yaml 签名 | 整数默认值 `296` | 不可转换，yaml 格式限制 | `int dst_type=296` |
| meta 注册 | 整数 `296` | `TORCH_DTYPE_ENUM_VALUE_TO_SCALAR_TYPE_MAP` + `torch_npu.xxx` | 双路判断 |
| C++ OpAPI | `int64_t dst_type` | `c10_npu::GetAclDataType(dst_type)` | 自动 -256 |
| torchair converter | 整数 `296` | `torch_dtype_value_to_ge_type()` | 自动转 GE 枚举 |
| GE raw op attr | GE 枚举值 `40` | `attr.Int(dst_type)` | 已经是 ACL 值 |

### FP8 双编码说明

FP8 类型有两套编码共存：
- **PyTorch 原生**：`torch.float8_e5m2` = ScalarType 23，`torch.float8_e4m3fn` = ScalarType 24
- **torch_npu 扩展**：`torch_npu.float8_e5m2` = 291，`torch_npu.float8_e4m3fn` = 292

`GetAclDataType()` 两套都能处理：`>= 256` 走偏移路径，`< 256` 走 ScalarType 转换路径。
meta 注册中必须双路判断：`torch_dtype == torch.float8_e5m2 or dst_type == torch_npu.float8_e5m2`。

---

## § 0.5 文件操作规范（重要）

### 路径确认红线（主线仓）

| 禁止行为 | 说明 |
|---------|------|
| 🚫 自动扫描找仓库 | 必须由用户显式提供父目录路径 |
| 🚫 基于设计文档推断 | 设计文档路径≠实际代码路径 |
| 🚫 默认使用当前目录 | 必须用户确认 |

**确认后方可执行**：
- [ ] 父目录路径已获取（用户输入）
- [ ] `{parent}/op-plugin`、`{parent}/torchair`、`{parent}/pytorch` 存在
- [ ] 目标文件实际路径已确认

### 前置确认

- [ ] 已找到正确的仓库根目录（op-plugin/ 和 torchair/）
- [ ] 已确认目标文件的实际路径（注意 python/ 子目录差异）
- [ ] 已读取目标文件末尾 30 行，确认追加位置和格式

### 操作模式分类

| 模式 | 文件 | 操作说明 |
|-----|------|---------|
| **追加** | `config/op_plugin_functions.yaml` | 在 `custom:` 段末尾追加新接口定义 |
| **追加** | `python/meta/_meta_registrations.py` | 在文件末尾追加新的 `@impl` 函数 |
| **追加** | `test/core_tests/test_fake_tensor.py` | 在文件末尾（`if __name__` 之前）追加新测试类 |
| **追加** | `test/core_tests/torch_npu_OpApi_schema_all.json` | 在顶层对象中追加新 schema 条目（注意 JSON 格式） |
| **新建** | `ops/opapi/{OpName}KernelNpuOpApi.cpp` | 创建全新的 C++ OpAPI 文件 |
| **新建** | `test/test_custom_ops/test_{op_name}.py` | 创建全新的测试文件 |

### 追加文件检查

| 文件 | 追加位置确认 | 格式检查 |
|-----|-------------|---------|
| `op_plugin_functions.yaml` | 找到 `custom:` 段最后一个条目 | 保持相同缩进（2空格）|

> **⚠️ yaml 段结构警告**：`op_plugin_functions.yaml` 包含多个顶级段，顺序为：
> `official:` → `autograd:` → `custom:` → `symint:` → `quant:`
> 新算子条目**必须追加在 `custom:` 段内**，不可放在 `symint:` 或 `quant:` 段下。
> **常见错误**：直接在文件末尾（`quant:` 段之前）追加，误以为还在 `custom:` 段内，实际已落入 `symint:` 段。
> **验证方法**：追加后执行 `grep -n "^[a-z_]*:" op_plugin_functions.yaml`，确认条目行号在 `custom:` 行号之后、`symint:` 行号之前。
| `_meta_registrations.py` | 最后一个 `@impl` 函数之后 | 保持 4 空格缩进 |
| `test_fake_tensor.py` | 最后一个测试类之后，`if __name__` 之前 | 类名不重复 |
| `torch_npu_OpApi_schema_all.json` | 最后一个 schema 条目之后 | JSON 逗号闭合正确 |

### 新建文件检查

- [ ] 文件名符合 PascalCase/snake_case 命名规范
- [ ] 文件头包含正确的版权声明
- [ ] 导入语句完整且正确
- [ ] 代码格式与仓库现有风格一致

### 关键禁忌

- 🚫 **禁止**创建 `.append`、`.tmp`、`.bak` 等临时文件
- 🚫 **禁止**删除或修改源文件中任何现有内容
- 🚫 **禁止**创建独立的 output 汇总目录
- 🚫 **禁止**生成两个连续下划线开头的函数/变量名（`__npu_xxx`），这会导致 Python 名称修饰问题
- ✅ **必须**直接使用 Edit 工具在原文件指定位置插入
- ✅ **必须**保持原有代码的格式和缩进风格
- ✅ **必须**在所有代码生成时，检查生成的函数名不包含 `__npu_` 模式

### yaml 追加示例

```yaml
# 找到 custom: 段的最后一个条目，在其后追加
- func: npu_xxx(...) -> (...)
  op_api: [v2.1, newest]

- func: npu_yyy(...) -> (...)  # ← 新增条目
  op_api: [v2.1, newest]
```

### JSON 追加技巧

追加前必须检查文件末尾结构：
```json
// 原文件末尾可能是这样：
"func: npu_old(...) -> (...)": {
    "version": ["all_version"]
}

// 需要先在前一个条目后加逗号，再追加：
"func: npu_old(...) -> (...)": {
    "version": ["all_version"]
},
"func: npu_new(...) -> (...)": {  // ← 新增条目
    "version": ["all_version"]
}
```

---

## § 0.6 Shape 推导前置扫描规范（强制）

**触发时机**：在编写以下文件的 shape 相关代码之前，**必须**重新扫描设计文档：
- OpAPI C++ 的输出 shape 构造函数
- `_meta_registrations.py` 的 shape 推导逻辑
- `test_fake_tensor.py` 的测试用例构造

**原因**：长上下文场景下，早期读取的文档细节（尤其是各参数的 shape 约束、条件分支下的维度变化）容易在后续代码生成时丢失或混淆。

### 扫描步骤

1. **重新读取设计文档**中所有输入/输出参数的 shape 描述段落（通常在 §2.1 参数说明）
2. **提取并输出结构化 Shape 摘要**，覆盖每个 Tensor 参数，格式如下：

```
=== Shape 摘要（从设计文档提取）===

【输入 Tensor】
- {参数名}: shape={各条件分支下的shape} | dtype={支持的数据类型}
  约束: {维度取值范围、对齐要求、与其他参数的关系等}

【输出 Tensor】
- {参数名}: dtype={输出数据类型}
  shape={推导规则，标注每个维度的来源}
  ⚠️ 条件分支: {若输出shape受属性/模式参数影响，逐条列出}

【条件分支对 shape 的影响】
- 当 {参数名}={值} 时: {对输入/输出 shape 的具体影响}
- ...

===
```

3. **将摘要作为代码生成的直接参考**，逐条对照编写 shape 推导逻辑
4. 如果文档中输出 shape 描述不明确，**必须向用户确认**后再编写代码

### 检查清单

- [ ] 已重新读取设计文档的参数说明章节
- [ ] 已输出结构化 Shape 摘要
- [ ] 每个条件分支下的 shape 都已覆盖
- [ ] 属性/模式参数对 shape 的影响已标注
- [ ] 输出 shape 的每个维度来源已明确（来自哪个输入的哪个维度，或由哪个属性决定）

---

## § 1.1 op_plugin_functions.yaml

### 新增 vs 修改接口

**新增接口**：在 `custom:` 段末尾追加
```yaml
- func: {接口名}({必选参数}, *, {可选参数}) -> ({输出类型列表})
  op_api: {版本范围}
```

**修改接口**：定位原有条目（通过 func 签名匹配），在原位置修改
```yaml
# 原条目
- func: npu_xxx(Tensor x, *, int old_param=0) -> (Tensor)
  op_api: [v2.1, newest]

# 修改为
- func: npu_xxx(Tensor x, *, int old_param=0, int new_param=1) -> (Tensor)
  op_api: [v2.1, newest]
```

参考（单轴，含 int? 可选参数）：
```yaml
- func: npu_dynamic_mx_quant(Tensor input, *, int axis=-1, str round_mode="rint", int dst_type=296, int block_size=32, int? scale_alg=0) -> (Tensor, Tensor)
  op_api: [v2.1, newest]
```

参考（双轴）：
```yaml
- func: npu_dynamic_mx_quant_with_dual_axis(Tensor input, *, str round_mode="rint", int dst_type=296, int scale_alg=0) -> (Tensor, Tensor, Tensor, Tensor)
  op_api: [v2.1, newest]
```

---

## § 1.2 OpAPI 封装 .cpp

### yaml 参数类型 → C++ 类型映射（完整版）

| yaml 类型 | C++ 类型 | 示例 | 说明 |
|-----------|---------|------|------|
| `Tensor` | `const at::Tensor &` | `const at::Tensor &self` | Tensor 引用 |
| `Tensor?` | `const c10::optional<at::Tensor> &` | `const c10::optional<at::Tensor> &bias` | 可选 Tensor |
| `Tensor[]` | `at::TensorList` | `at::TensorList tensors` | Tensor 列表 |
| `int` | `int64_t` | `int64_t dim` | 整型（注意不是 int） |
| `int?` | `c10::optional<int64_t>` | `c10::optional<int64_t> dst_type` | 可选整型，**按值传递**（不加 `const &`），否则与 codegen 生成的 `OpInterface.cpp` 签名不匹配导致链接失败 |
| `int[]` | `at::IntArrayRef` | `at::IntArrayRef normalized_shape` | 整型数组 |
| `float` | `double` | `double eps` | 浮点（注意不是 float） |
| `float?` | `c10::optional<double>` | `c10::optional<double> scale` | 可选浮点 |
| `float[]` | `at::ArrayRef<double>` | `at::ArrayRef<double> scales` | 浮点数组 |
| `bool` | `bool` | `bool keepdim` | 布尔型 |
| `bool?` | `c10::optional<bool>` | `c10::optional<bool> pin_memory` | 可选布尔 |
| `str` | `c10::string_view` | `c10::string_view quant_mode` | 字符串视图 |
| `str?` | `c10::optional<c10::string_view>` | `c10::optional<c10::string_view> mode` | 可选字符串 |
| `Scalar` | `const at::Scalar &` | `const at::Scalar &alpha` | 标量 |
| `Scalar?` | `const c10::optional<at::Scalar> &` | `const c10::optional<at::Scalar> &p` | 可选标量 |
| `Scalar[]` | `at::ArrayRef<at::Scalar>` | `at::ArrayRef<at::Scalar> scalars` | 标量数组 |
| `ScalarType` | `at::ScalarType` | `at::ScalarType dtype` | 数据类型 |
| `ScalarType?` | `c10::optional<at::ScalarType>` | `c10::optional<at::ScalarType> dtype` | 可选数据类型 |
| `SymInt` | `c10::SymInt` | `c10::SymInt output_size` | 符号整型 |
| `SymInt?` | `c10::optional<c10::SymInt>` | `c10::optional<c10::SymInt> size` | 可选符号整型 |
| `SymInt[]` | `c10::SymIntArrayRef` | `c10::SymIntArrayRef output_size` | 符号整型数组 |
| `Device?` | `c10::optional<at::Device>` | `c10::optional<at::Device> device` | 可选设备 |
| `Layout?` | `c10::optional<at::Layout>` | `c10::optional<at::Layout> layout` | 可选布局 |
| `MemoryFormat?` | `c10::optional<at::MemoryFormat>` | `c10::optional<at::MemoryFormat> format` | 可选内存格式 |
| `Generator?` | `c10::optional<at::Generator>` | `c10::optional<at::Generator> generator` | 可选随机数生成器 |
| `Dimname` | `at::Dimname` | `at::Dimname dim` | 维度名 |
| `Dimname[]` | `at::DimnameList` | `at::DimnameList dims` | 维度名列表 |

### 文件模板

```cpp
// Copyright (c) {当前年份} Huawei Technologies Co., Ltd
// All rights reserved.
//
// Licensed under the BSD 3-Clause License  (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// https://opensource.org/licenses/BSD-3-Clause
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

#include "op_plugin/AclOpsInterface.h"
#include "op_plugin/OpApiInterface.h"
#include "op_plugin/utils/op_api_common.h"

namespace op_api {
using npu_preparation = at_npu::native::OpPreparation;

namespace {
constexpr int64_t MIN_INPUT_DIM = 2;
constexpr int64_t DEFAULT_SCALE_ALG = 0;
}; // namespace

std::tuple<{输出类型列表}> {算子PascalCase名}(
    const at::Tensor &input,
    {可选参数列表，按类型映射表转为 C++ 类型})
{
    // 1. 输入校验
    TORCH_CHECK(input.dim() >= MIN_INPUT_DIM,
        "The input should be at least 2D" + OPS_ERROR(ErrCode::PARAM));

    // 2. 推导输出 shape
    //    op_infer::array_to_small_vector(input.sizes())  // 拷贝为可修改向量
    //    op_infer::CeilDiv(a, b)                         // 向上取整除法
    //    mxscale_shape.emplace_back(ALIGN_NUM)           // 尾部追加维度

    // 3. str 参数转换：char *ptr = const_cast<char *>(round_mode.data());
    // 4. 可选参数解包：int64_t val = opt.has_value() ? opt.value() : DEFAULT;

    // 5. 分配输出 tensor（非 Quant 类算子）
    at::Tensor output = npu_preparation::apply_tensor_without_format(output_shape, c10::dtype(at::ScalarType::Float));

    // 5. 分配输出 tensor（Quant 类算子，见下方特殊处理）

    // 6. EXEC_NPU_CMD: aclnn接口名, Tensor输入, 标量参数, 输出
    EXEC_NPU_CMD(aclnn{算子名}, input, round_mode_ptr, output);

    return std::make_tuple({输出列表});
}

} // namespace op_api
```

### 通用关键点

- **整数类型**：yaml 中的 `int` 映射到 C++ 的 `int64_t`，不是 `int`
- **浮点类型**：yaml 中的 `float` 映射到 C++ 的 `double`，不是 `float`
- **字符串转换**：`c10::string_view` → `char*` 使用 `const_cast<char*>(round_mode.data())`
- **可选参数**：`c10::optional<T>` 用 `.has_value()` 判断后解包
- **分配输出**：`npu_preparation::apply_tensor_without_format(shape, dtype)`
- **EXEC_NPU_CMD 顺序**：`aclnn接口名` → `Tensor输入` → `标量参数` → `输出Tensor`

### 自定义 Dtype 算子特殊处理

**使用场景**：
- 处理 PyTorch 不原生支持的 ACL 数据类型（HIFLOAT8、FP4、FP8、INT4 等）
- 需要通过 `c10::optional<int64_t>` 传入自定义 dtype 参数（如 `query_dtype`、`key_dtype`）

**核心机制**：
```cpp
// 使用 c10_npu::GetAclDataType() 将 Python dtype 转换为 aclDataType
// 对应关系参考 §0 映射表
aclDataType acl_type = c10_npu::GetAclDataType(dtype_value);  // 290 → ACL_HIFLOAT8
```

**模式 A：输出 Tensor 使用 TensorWrapper（标准 Quant 类）**
```cpp
// 1. 获取 aclDataType
aclDataType y_acltype = c10_npu::GetAclDataType(dst_type);

// 2. 转换为 ScalarType（用于创建 PyTorch Tensor）
at::ScalarType scalar_dtype = npu_preparation::convert_to_scalar_type(y_acltype);

// 3. 创建输出 tensor（存储类型）
at::Tensor y = npu_preparation::apply_tensor_without_format(y_shape, c10::dtype(scalar_dtype));

// 4. 用 TensorWrapper 绑定真实 dtype（让 aclnn 感知逻辑类型）
TensorWrapper y_wrapper = {y, y_acltype};

// 5. 传递给 EXEC_NPU_CMD（注意 y_acltype 通常也要传）
EXEC_NPU_CMD(aclnnXXX, input, y_acltype, y_wrapper, ...);
```

**模式 B：输入 Tensor 使用 TensorWrapper（如 hifloat8 输入）**
```cpp
// 用于：PyTorch 不支持输入 dtype，需要通过 dtype 参数指定

// 1. 判断是否为特定自定义类型（显式比较 aclDataType）
std::variant<at::Tensor, TensorWrapper> input_processed;

if (input_dtype.has_value() && 
    c10_npu::GetAclDataType(input_dtype.value()) == ACL_HIFLOAT8) {
    // hifloat8 类型：使用 TensorWrapper 绑定真实 aclDataType
    input_processed = make_wrapper(input, input_dtype);
} else {
    // 标准类型：直接使用 at::Tensor
    input_processed = input;
}

// 2. std::visit 处理所有类型组合
std::visit([&](const auto& input_arg) {
    EXEC_NPU_CMD(aclnnXXX, input_arg, ...);
}, input_processed);
```

**模式 C：多输入使用 TensorWrapper**
```cpp
// 多个输入都可能是自定义类型（如 query/key 都可能是 hifloat8）
std::variant<at::Tensor, TensorWrapper> query_processed;
std::variant<at::Tensor, TensorWrapper> key_processed;

if (query_dtype.has_value() && 
    c10_npu::GetAclDataType(query_dtype.value()) == ACL_HIFLOAT8) {
    query_processed = make_wrapper(query, query_dtype);
} else {
    query_processed = query;
}

if (key_dtype.has_value() && 
    c10_npu::GetAclDataType(key_dtype.value()) == ACL_HIFLOAT8) {
    key_processed = make_wrapper(key, key_dtype);
} else {
    key_processed = key;
}

// std::visit 处理所有组合（2x2=4种）
std::visit([&](const auto& query_arg, const auto& key_arg) {
    EXEC_NPU_CMD(aclnnXXX, query_arg, key_arg, ...);
}, query_processed, key_processed);
```

**关键 API 说明**：

| API | 功能 | 示例 |
|-----|------|------|
| `c10_npu::GetAclDataType(int64_t)` | PyTorch dtype → aclDataType | `GetAclDataType(290)` → `ACL_HIFLOAT8` |
| `c10_npu::GetAclDataType(DType)` | c10_npu::DType 枚举 → aclDataType | `GetAclDataType(c10_npu::DType::HIFLOAT8)` |
| `make_wrapper(tensor, dtype)` | 创建 TensorWrapper 绑定真实 dtype | `make_wrapper(query, query_dtype)` |

**常见自定义类型**：参考 §0 完整映射表（`torch_npu.hifloat8` → `ACL_HIFLOAT8`，`torch_npu.float4_e2m1fn_x2` → `ACL_FLOAT4_E2M1` 等）

**DType 编码原理**（了解即可）：
- ACL 原生类型: 0-255（如 `ACL_HIFLOAT8 = 34`）
- c10_npu::DType: ACL值 + 256（如 `c10_npu::DType::HIFLOAT8 = 290`）
- `GetAclDataType()` 自动处理偏移：`>= 256` 时 `-256`，`< 256` 时按 ScalarType 处理

**FP4 特殊处理**（dst_type 为 FLOAT4_E2M1/FLOAT4_E1M2）：
- 输出用 `ScalarType::Byte`（uint8）承载
- shape 尾轴除以 2（两个 FP4 合一个 uint8）
- 详见 §1.3 的 shape 推导

**mxscale 处理**：
- 存储 dtype 为 `ScalarType::Byte`
- TensorWrapper 绑定 `ACL_FLOAT8_E8M0`

### Norm 类算子处理

### Norm 类算子处理

**使用场景**：算子名含 norm/rms_norm/layer_norm/batch_norm，且无 quant 关键词

**特点**：
- 不使用 TensorWrapper
- 不使用 GetAclDataType
- 标准 FP16/BF16/FP32 处理
- 典型输出分配：
```cpp
at::Tensor output = npu_preparation::apply_tensor_without_format(input.sizes(), input.dtype());
```

---

## § 1.3 _meta_registrations.py

```python
@impl(m, "{接口名}")
def {接口名}(input_dummy, *, {可选参数与默认值}):
    dim_num = input_dummy.dim()

    # 1. 参数校验（与 C++ 侧一致）

    # 2. 推导输出 shape
    output_shape = list(input_dummy.shape)

    # 3. 根据 dst_type 确定输出 dtype（Quant 类算子）
    torch_dtype = TORCH_DTYPE_ENUM_VALUE_TO_SCALAR_TYPE_MAP.get(dst_type, torch.int8)

    if torch_dtype == torch.float8_e5m2 or dst_type == torch_npu.float8_e5m2:
        output = torch.empty_like(input_dummy, dtype=torch.float8_e5m2)
    elif torch_dtype == torch.float8_e4m3fn or dst_type == torch_npu.float8_e4m3fn:
        output = torch.empty_like(input_dummy, dtype=torch.float8_e4m3fn)
    else:
        # FP4：uint8 承载，尾轴减半
        if input_dummy.size(dim_num - 1) % 2:
            raise RuntimeError("last dim must be divisible by 2" + ops_error(ErrCode.PARAM))
        output_shape = []
        for dim in range(dim_num - 1):
            output_shape.append(input_dummy.size(dim))
        output_shape.append(input_dummy.size(dim_num - 1) // 2)
        output = input_dummy.new_empty(output_shape, dtype=torch.uint8)

    mxscale = input_dummy.new_empty(mxscale_shape, dtype=torch.uint8)
    return (output, mxscale)
```

### 关键点

- `torch.empty_like`：shape 不变只改 dtype（FP8）
- `input_dummy.new_empty`：shape 有变化（FP4）
- dtype 判断需同时检查映射表和 `torch_npu.float8_xxx` 枚举值
- `TORCH_DTYPE_ENUM_VALUE_TO_SCALAR_TYPE_MAP` 是文件中已有的全局字典
- 参数校验逻辑与 C++ 侧保持一致

### dst_type → shape/dtype 速查

> 完整编码对应关系见 **§ 0**。
标准写法参考 `TestNpuDynamicBlockQuant`（约 3825 行）。

**核心逻辑**：验证 meta 注册（`_meta_registrations.py`）的 shape 推导与真实算子执行是否一致。
- `actual_xxx`：FakeTensorMode **外**，op-plugin 真实执行结果（需 NPU 设备）
- `fake_xxx`：FakeTensorMode **内**，torchair meta 推导结果（不需要 NPU）
- 对比：`self.assertEqual(actual.shape, fake.shape)`

每个维度/dtype 场景平铺展开（不用 `test_cases` 循环），device 用 `.to("npu")`。

```python
class Test{PascalCase名}(TestCase):
    def test_{接口名}_meta(self):
        # {维度}D, {dtype}, {参数说明}
        x = torch.randn({shape}, dtype={dtype}).to("npu")
        # ... 构造其他输入 ...
        actual_y, actual_scale = torch_npu.{接口名}(x, {参数})
        with FakeTensorMode():
            fake_x = torch.randn({shape}, dtype={dtype}).to("npu")
            # ... 构造其他 fake 输入 ...
            fake_y, fake_scale = torch_npu.{接口名}(fake_x, {参数})
        self.assertEqual(actual_y.shape, fake_y.shape)
        self.assertEqual(actual_scale.shape, fake_scale.shape)

        # {另一维度/dtype 场景，平铺展开}
        x = torch.randn({shape2}, dtype={dtype2}).to("npu")
        ...
```

### 关键点

- **不要**硬编码预期 shape，用 `actual.shape == fake.shape` 对比
- **不要**用 `test_cases` 列表循环，按场景平铺
- **不要**用 `@SupportedDevices` 装饰器（fake_tensor 测试不需要）
- device 用 `.to("npu")`，不用 `device='npu'`
- 每个输出都要对比 shape

---

## § 1.5 torch_npu_OpApi_schema_all.json

```json
"func: {接口名}({签名}) -> ({输出})": {
    "version": ["all_version"]
}
```

---

## § 1.6 算子测试文件

文件路径：`op-plugin/test/test_custom_ops/test_npu_{op_name_snake}.py`

> **⚠️ 命名规范**：无论接口名是 `npu_xxx` 还是 `_npu_xxx`，测试文件名统一为 `test_npu_xxx.py`（`test_` 与 `npu` 之间只有一个下划线）。禁止出现 `test__npu_` 双下划线文件名。
>
> | 接口名 | 测试文件名 |
> |--------|-----------|
> | `npu_dynamic_mx_quant` | `test_npu_dynamic_mx_quant.py` |
> | `_npu_kv_quant_sparse_flash_attention_pioneer` | `test_npu_kv_quant_sparse_flash_attention_pioneer.py` |

测试文件采用 golden 对比模式：`supported_op_exec` 提供预期输出，`custom_op_exec` 调用 NPU 算子，用 `assert_close` / `assert` 对比。

### golden 来源（按优先级）

| 优先级 | golden 方式 | 适用场景 | 说明 |
|--------|------------|----------|------|
| 1 | **拼接已有 NPU 算子** | 融合/拼接算子（如 AddRmsNormDynamicMxQuant = AddRmsNorm + DynamicMxQuant） | 子算子已独立验证过精度，最可靠 |
| 2 | 用户提供硬编码数据 | 简单场景、特定输入 | 如全零输入的预期输出 |
| 3 | CPU fp32 手写实现 | 无已有子算子可拼接 | 需用户确认逻辑正确性 |

**不可自行编造 golden 数据**。优先询问用户是否有可拼接的子算子或参考实现。

### dst_type 参数规范

- 测试文件中**不要**用魔鬼数字（296、297、35、36），直接用 `torch_npu.xxx` 属性
- 完整属性名见 § 0 映射表
- 常用：`torch_npu.float8_e5m2`、`torch_npu.float8_e4m3fn`、`torch_npu.float4_e2m1fn_x2`、`torch_npu.float4_e1m2fn_x2`

### 模式一：拼接已有算子作为 golden（融合算子推荐）

```python
import torch
import torch_npu
from torch_npu.testing.testcase import TestCase, run_tests
from torch_npu.testing.common_utils import SupportedDevices
from torch.testing import assert_close


class Test{PascalCase名}(TestCase):
    def custom_op_exec(self, x1, x2, gamma, {参数}):
        return torch_npu.{接口名}(x1, x2, gamma, {参数赋值})

    def supported_op_exec(self, x1, x2, gamma, {参数}):
        # 拼接已有 NPU 算子
        y_norm, rstd, x_out = torch_npu.npu_{子算子1}(x1, x2, gamma, ...)
        y_quant, mxscale = torch_npu.npu_{子算子2}(y_norm, ...)
        return y_quant, x_out, mxscale, rstd

    def generate_input(self, shape, dtype="float16"):
        data_type = torch.float16 if dtype == "float16" else torch.bfloat16
        return torch.randn(shape, dtype=data_type)

    @SupportedDevices(['{芯片型号}'])
    def test_{接口名}_{dtype}(self, device="npu"):
        x1 = self.generate_input({shape}, "{dtype}").to(device)
        # ... 构造其他输入 ...

        golden_y, golden_x_out, golden_mxscale, golden_rstd = self.supported_op_exec(
            x1.clone(), x2.clone(), gamma.clone(), dst_type=torch_npu.{dst_type属性}
        )
        custom_y, custom_x_out, custom_mxscale, custom_rstd = self.custom_op_exec(
            x1.clone(), x2.clone(), gamma.clone(), dst_type=torch_npu.{dst_type属性}
        )

        assert_close(custom_x_out.float(), golden_x_out.float(), atol=1e-3, rtol=1e-3)
        assert torch.all(custom_y.view(torch.uint8) == golden_y.view(torch.uint8))
        assert_close(custom_mxscale, golden_mxscale, atol=0.01, rtol=0.001)


if __name__ == "__main__":
    run_tests()
```

### 模式二：硬编码数据 golden（简单场景）

参考 `test_npu_dynamic_mx_quant_with_dual_axis.py`：

```python
class Test{PascalCase名}(TestCase):
    def supported_op_exec(self, input_tensor):
        # 特定输入对应的硬编码预期输出
        device = input_tensor.device
        y1 = torch.tensor([[[0, 0], [0, 0]]], dtype=torch.float8_e5m2, device=device)
        mxscale1 = torch.tensor([[[[5.87747e-39, ...]]]], dtype=torch.uint8, device=device)
        return y1, mxscale1, ...

    def custom_op_exec(self, input_tensor, {参数}):
        return torch_npu.{接口名}(input_tensor, {参数赋值})

    @SupportedDevices(['{芯片型号}'])
    def test_{接口名}(self, device="npu"):
        input_tensor = self.generate_input({shape}).to(device)
        supported_output = self.supported_op_exec(input_tensor.clone())
        custom_output = self.custom_op_exec(input_tensor.clone(), {参数})
        assert torch.all(custom_output[0].view(torch.uint8) == supported_output[0].view(torch.uint8))
        assert_close(supported_output[1], custom_output[1], atol=0.01, rtol=0.001)
```

### `@SupportedDevices` 装饰器

芯片型号必须为 `Ascend950`、`Ascend910B`、`Ascend910_93` 之一。

**外部叫法与内部写法映射表**：

| 外部叫法 | 内部写法 |
|---------|---------|
| 910B, A2 | `Ascend910B` |
| 910C, A3 | `Ascend910_93` |
| 910D, A5 | `Ascend950` |

若用户提供的外部叫法不在上表，或内部写法不在 `Ascend950`、`Ascend910B`、`Ascend910_93` 列表中，提示用户修正。

### golden 对比要点

- 量化类算子：y 用 `view(torch.uint8)` 做逐元素对比，mxscale 用 `assert_close(atol=0.01, rtol=0.001)`
- 非量化输出（如 x_out）：用 `assert_close(atol=1e-3, rtol=1e-3)`
- 测试覆盖：fp16 + bf16 输入、不同 shape（2D/3D）、不同 dst_type（FP4 + FP8）
---

## §1.7 接口修改指南

> **适用场景**：为已有 PTA 接口新增参数，或修改接口行为

### 1.7.1 新增参数的两种情况

#### 情况一：新增参数需要传给 aclnn（需要 aclnnV2）

**特征**：
- 新增参数需要透传到 aclnn 层
- aclnn 已提供带新参数的 V2 接口

**代码示例**：
```cpp
// aclnn 接口已更新为 V2 版本
EXEC_NPU_CMD(aclnnQuantLightningIndexerV2, query, key, ..., quant_dtype);
```

**确认清单**：
- [ ] aclnn 是否已提供带新参数的 V2 接口？
- [ ] V2 接口的参数顺序和类型是否确认？

#### 情况二：新增参数仅 PTA 层使用（不需要 aclnnV2）

**特征**：
- PyTorch 不支持该 dtype 类型
- 新增参数仅用于 `make_wrapper` 打包，不直接传给 aclnn
- 通过 TensorWrapper 将真实 dtype 捆绑传递给 aclnn

**代码示例**：
```cpp
// 1. 判断是否为 hifloat8 并包装
std::variant<at::Tensor, TensorWrapper> query_processed;
if (query_dtype.has_value() && 
    c10_npu::GetAclDataType(query_dtype.value()) == ACL_HIFLOAT8) {
    query_processed = make_wrapper(query, query_dtype);
} else {
    query_processed = query;
}

// 2. std::visit 调用原接口（不需要 V2）
std::visit([&](const auto& query_arg) {
    EXEC_NPU_CMD(aclnnQuantLightningIndexer, query_arg, ...);
}, query_processed);
```

**核心原理**：
```
PTA 层：
  query (at::Tensor, dtype=Byte) + query_dtype=290 (hifloat8)
    ↓ GetAclDataType(290) == ACL_HIFLOAT8
    ↓ make_wrapper
  TensorWrapper {tensor_, ACL_HIFLOAT8}
    ↓ ConvertTypes (EXEC_NPU_CMD 内部)
  aclTensor (dtype=ACL_HIFLOAT8) → 传给 aclnn
```

**判断矩阵**：

| 新增参数 | PyTorch 支持 | aclnn 需要 | 处理方式 | 示例 |
|---------|-------------|-----------|---------|------|
| `axis` (int) | ✅ | ✅ 改变逻辑 | 直接传参 + V2 接口 | `AscendQuantV3` |
| `scale` (float) | ✅ | ✅ 改变计算 | 直接传参 + V2 接口 | `DynamicQuant` |
| `query_dtype=290` (hifloat8) | ❌ | ✅ 感知类型 | `TensorWrapper` + 原接口 | `QuantLightningIndexer` |

---

### 1.7.2 TorchAir GE 通路

**GE 转换文件位置**：
```
torchair/_ge_concrete_graph/auto_generated_ge_raw_ops.py
torchair/_ge_concrete_graph/ge_converter/custom/{op_name}.py
```

**是否需要 GE 通路？**

| 场景 | 是否需要 GE 注册 | 说明 |
|-----|----------------|------|
| 训练场景（图模式） | ✅ 需要 | 需要 GE 图编译 |
| 推理场景（单算子） | ❌ 不需要 | 直接走 PTA 调用 |
| 动态图模式 (eager) | ❌ 不需要 | 直接走 PTA 调用 |

**确认清单**：
- [ ] 用户是否需要在图模式下使用该算子？
- [ ] 若需要，是否已提供 GE converter 实现？

---

### 1.7.3 EXEC_NPU_CMD 类型选择

| 宏 | 使用场景 | 特点 |
|---|---------|------|
| `EXEC_NPU_CMD` | 标准算子调用 | 包含完整的格式检查、内存管理 |
| `EXEC_NPU_NO_FORMAT_CHECK_CMD` | 自定义格式/布局算子 | **跳过格式检查**，适用于特殊布局算子 |
| `EXEC_NPU_CMD_SYNC` | 同步执行场景 | 阻塞等待执行完成 |

**核心区别**：

`EXEC_NPU_CMD` 标准流程：
```cpp
// 1. ConvertTypes(...)  - 包含格式检查
// 2. 调用 aclnnGetWorkspaceSize
// 3. 调用 aclnn 执行
```

`EXEC_NPU_NO_FORMAT_CHECK_CMD` 特殊流程：
```cpp
// 1. InitPTACacheThreadLocal()  - 初始化 PTA 缓存
// 2. SetPTAHashKey(0)           - 设置 hash key 跳过格式检查
// 3. ConvertTypes(...)          - 无格式检查
// 4. 调用 aclnnGetWorkspaceSize
// 5. 调用 aclnn 执行
```

**使用建议**：

| 算子类型 | 推荐宏 |
|---------|--------|
| 标准 PyTorch 算子（Conv, Matmul等） | `EXEC_NPU_CMD` |
| Lightning Attention 系列 | `EXEC_NPU_NO_FORMAT_CHECK_CMD` |
| Quant/自定义 Dtype 算子 | `EXEC_NPU_CMD` |
| Fused 融合算子（特殊布局） | `EXEC_NPU_NO_FORMAT_CHECK_CMD` |
| 自定义通信算子 | `EXEC_NPU_NO_FORMAT_CHECK_CMD` |

> **⚠️ EXEC_NPU_* 宏参数约束**：所有传入 `EXEC_NPU_CMD` / `EXEC_NPU_NO_FORMAT_CHECK_CMD` 的参数**必须是具名左值变量**。宏内部日志宏 `generate_log_infos` 通过非 const 左值引用接收参数，临时值（右值）会导致编译失败。常见违规：
> - `optional.value_or(0)` → 提取为 `int64_t val = opt.value_or(0);`
> - `static_cast<T>(x)` → 提取为 `T val = static_cast<T>(x);`
> - 三元表达式 `a ? b : c` → 提取为局部变量
> - 函数返回值 → 先绑定到变量再传入

---

### 1.7.4 修改接口最佳实践 Checklist

**开发前确认**：
1. [ ] **接口变更类型**：新增参数是否需要传给 aclnn？若需要，aclnn 是否已提供 V2 接口？
2. [ ] **数据类型**：是否涉及自定义 dtype（hifloat8、FP4、INT4 等）？若涉及，使用 TensorWrapper 模式
3. [ ] **GE 通路**：是否需要图模式支持？若需要，同步添加 GE converter
4. [ ] **EXEC 宏选择**：标准算子 → `EXEC_NPU_CMD`；特殊布局 → `EXEC_NPU_NO_FORMAT_CHECK_CMD`

**开发步骤**：
1. 若涉及自定义 dtype，使用 TensorWrapper 模式（参考 §1.2 自定义 Dtype 算子特殊处理）
2. 根据是否需要格式检查选择 EXEC_NPU_CMD 或 EXEC_NPU_NO_FORMAT_CHECK_CMD
3. 若需要 GE 支持，同步添加 torchair converter
4. 测试覆盖：单算子测试 + 图模式测试（如需要）
