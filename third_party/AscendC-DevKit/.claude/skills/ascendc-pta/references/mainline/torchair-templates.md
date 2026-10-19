# torchair 详细模板

> **文件路径约定**：
> - 代码生成目标：`{PTA_DIR}/torchair/`（独立工作目录，非 pytorch 子模块）
> - 以下所有文件路径均相对于 `torchair/` 根目录
> - 禁止创建独立的 output 汇总目录

## § 2.0 文件操作规范（重要）

### 前置确认

- [ ] 已找到正确的仓库根目录（torchair/）
- [ ] 已确认目标文件的实际路径
- [ ] 已读取目标文件末尾 30 行，确认追加位置和格式

### 操作模式分类

| 模式 | GE 原型注册 | converter 注册 | 适用场景 |
|-----|------------|---------------|---------|
| **GE 图模式** | ✅ 需要 `auto_generated_ge_raw_ops.py` | ✅ 需要 `ge_converter/custom/{op_name}.py` | 需要 GE 原型映射的算子 |
| **aclgraph 模式** | ❌ 不需要 | ✅ 仅需 `ge_converter/custom/{op_name}.py` | 直接走 aclnn 接口的算子 |

> **判断依据**：根据算子接口确认是否需要 GE 原型注册。仅当算子在 GE 图编译时需要原型映射（GE OP）时才需要修改 `auto_generated_ge_raw_ops.py`。

### 追加文件检查

| 文件 | 追加位置确认 | 格式检查 |
|-----|-------------|---------|
| `auto_generated_ge_raw_ops.py` | 最后一个函数定义之后 | docstring 格式一致 |

### 新建文件检查

- [ ] 文件名符合 snake_case 命名规范
- [ ] 文件头包含正确的版权声明
- [ ] 导入语句完整且正确（`from torchair._ge_concrete_graph.ge_converter.converter_utils import *`）
- [ ] 代码格式与仓库现有风格一致

### 关键禁忌

- 🚫 **禁止**创建 `.append`、`.tmp`、`.bak` 等临时文件
- 🚫 **禁止**删除或修改源文件中任何现有内容
- 🚫 **禁止**创建独立的 output 汇总目录
- 🚫 **禁止**生成两个连续下划线开头的函数/变量名（`__npu_xxx`），这会导致 Python 名称修饰问题
- ✅ **必须**直接使用 Edit 工具在原文件指定位置插入
- ✅ **必须**保持原有代码的格式和缩进风格
- ✅ **必须**在所有代码生成时，检查生成的函数名不包含 `__npu_` 模式

---

## § 2.1 auto_generated_ge_raw_ops.py

```python
# This api is auto-generated from IR {算子PascalCase名}
@auto_convert_to_tensor([{Tensor动态性}], [{Tensor可选性}])
def {算子PascalCase名}({输入参数},
                       *,
                       {属性参数},
                       dependencies=[],
                       node_name=None):
    """REG_OP({算子PascalCase名})\n
    .INPUT({输入名}, TensorType({{dtype列表}}))\n
    .OUTPUT({输出名}, TensorType({{dtype列表}}))\n
    .ATTR({属性名}, {GE类型}, {默认值})\n
    """
    op = get_default_ge_graph().op.add()
    op.type = "{算子PascalCase名}"
    op.name = next_unique_name(node_name, "{算子PascalCase名}")

    for dependency in dependencies:
        op.input.append(dependency.controller)

    # inputs
    op.input.append({输入名}.tensor)
    op.input_desc.add().CopyFrom({输入名}.desc)
    op.input_desc[-1].name = "{输入名}"

    # attrs
    # String: op.attr["{key}"].s = compat_as_bytes(val)
    # Int:    op.attr["{key}"].i = val
    # Float:  op.attr["{key}"].f = val
    # Bool:   op.attr["{key}"].b = val
    # 注意：attr key 以 CANN OpDef 为准，可能与 Python 参数名不同
    #       例如 block_size → "blocksize"（无下划线）

    # outputs
    output_index = 0
    op.output_desc.add().name = "{输出名}"
    {var} = Tensor(op, output_index)
    output_index += 1

    return {输出变量列表}
```

### @auto_convert_to_tensor

- 第一个列表：每个 Tensor 输入是否动态，长度 = `*` 前 Tensor 个数
- 第二个列表：每个 Tensor 输入是否可选，长度同上
- 默认都是 False

### GE 属性类型对照

| Python 类型 | GE ATTR | 赋值 |
|-------------|---------|------|
| str | String | `.s = compat_as_bytes(val)` |
| int | Int | `.i = val` |
| float | Float | `.f = val` |
| bool | Bool | `.b = val` |
| List[int] | ListInt | `.list.i.extend(val)` |

### GE 数据类型枚举

> 完整编码对应关系（含 Python 属性名、ACL 值、DType 值）见 **op-plugin-templates.md § 0**。

| GE 值 (ACL) | 含义 | Python dst_type (DType) |
|-------|------|------------------------|
| 40 | DT_FLOAT4_E2M1 | `torch_npu.float4_e2m1fn_x2` (296) |
| 41 | DT_FLOAT4_E1M2 | `torch_npu.float4_e1m2fn_x2` (297) |
| 35 | DT_FLOAT8_E5M2 | `torch_npu.float8_e5m2` (291) |
| 36 | DT_FLOAT8_E4M3FN | `torch_npu.float8_e4m3fn` (292) |

---

## § 2.2 custom converter

```python
from torchair._ge_concrete_graph.ge_converter.converter_utils import *


@declare_supported([
    Support(F16(8, 256))
])
@register_fx_node_ge_converter(torch.ops.npu.{接口名}.default)
def conveter_{接口名}_default(
    x: Tensor,
    {可选参数}: {类型} = {默认值},
    ...
    meta_outputs: List[TensorSpec] = None
):
    """
    NB: aten::{接口名}(Tensor x, *, {签名}) -> ({输出})
    """
    # 1. dst_type 转换
    acl_dst_type = torch_dtype_value_to_ge_type(dst_type)

    # 2. 调用 GE raw op
    y, mxscale = ge.{算子PascalCase名}(x, round_mode=round_mode, dst_type=acl_dst_type, ...)

    # 3. 设置输出 desc.dtype
    y.desc.dtype = torch_dtype_value_to_ge_proto_type(dst_type)
    mxscale.desc.dtype = ProtoDataType.DT_FLOAT8_E8M0

    # 4. FP4 Bitcast 处理 (float4_e2m1fn_x2=296, float4_e1m2fn_x2=297)
    if dst_type == 296 or dst_type == 297:  # torchair 签名默认值为整数，此处用数值判断
        dim_num = x.rank
        bit_shape = []
        for _ in range(dim_num - 1):
            bit_shape.append(1)
        bit_shape.append(2)
        div_x2 = ge.Cast(ge.Const(bit_shape), dst_type=DataType.DT_INT32)
        y_shape_int4 = ge.Shape(y)
        y_shape_uint8 = ge.Div(y_shape_int4, div_x2)
        y_shape_int4_2bit = ge.ConcatV2(
            [y_shape_uint8, ge.Cast(ge.Const([2]), dst_type=DataType.DT_INT32)],
            concat_dim=0, N=2
        )
        y = ge.Bitcast(ge.Reshape(y, y_shape_int4_2bit), type=DataType.DT_UINT8)
        return ge.Reshape(y, y_shape_uint8), mxscale
    else:
        return y, mxscale
```

### 关键点

- 函数命名：`conveter_{接口名}_default`（参考代码用 `conveter`，保持一致）
- `converter_utils` 的 `*` 导入提供：`ge`、`Tensor`、`DataType`、`ProtoDataType`、`torch_dtype_value_to_ge_type`、`torch_dtype_value_to_ge_proto_type` 等
- `x.rank`：GE Tensor 维度数
- `ge.Shape/Div/ConcatV2/Reshape/Bitcast`：GE 图算子，图编译期执行
- FP4 Bitcast 本质：GE 内部 FP4 shape 按元素计，PyTorch 侧期望 uint8 视图（2 个 FP4 合 1 个 uint8）

### 两个转换函数

| 函数 | 返回 | 用途 |
|------|------|------|
| `torch_dtype_value_to_ge_type` | int（GE 枚举值） | 传给 raw op attr |
| `torch_dtype_value_to_ge_proto_type` | ProtoDataType | 设置 desc.dtype |

### PyTorch → GE dtype 转换

> 完整编码对应关系见 **op-plugin-templates.md § 0**。

| Python dst_type | Python 属性 | GE dst_type | ProtoDataType |
|-----------------|-------------|-------------|---------------|
| 296 | `torch_npu.float4_e2m1fn_x2` | 40 | DT_FLOAT4_E2M1 |
| 297 | `torch_npu.float4_e1m2fn_x2` | 41 | DT_FLOAT4_E1M2 |
| 23 / 291 | `torch_npu.float8_e5m2` | 35 | DT_FLOAT8_E5M2 |
| 24 / 292 | `torch_npu.float8_e4m3fn` | 36 | DT_FLOAT8_E4M3FN |

---

## § 2.3 aclgraph 模式 converter 示例

### 适用场景

当算子仅需 aclgraph 模式支持（图模式走 aclnn 接口），不需要 GE 原型注册时，只需创建 `ge_converter/custom/{op_name}.py` 文件。

### aclgraph 模式 converter 范式（参考 sparse_flash_attention.py）

```python
from typing import (
    Any, Callable, ContextManager, Iterator, List, Literal, NamedTuple, Optional, Sequence, Tuple, TypeVar,
    Union, overload,
)

import torch
from torch import Generator, contiguous_format, inf, strided, SymInt
from torch.types import Device, Number, _bool, _complex, _device, _dtype, _float, _int, _layout, _qscheme, _size
import torchair
from torchair._ge_concrete_graph import ge_apis as ge
from torchair._ge_concrete_graph.fx2ge_converter import declare_supported, register_fx_node_ge_converter
from torchair.ge._ge_graph import Tensor, TensorSpec, DataType
from torchair._ge_concrete_graph.supported_declaration import _TypedTensor, F32, F16, F64, I32, I16, I64, I8, U8, \
    BOOL, Support
from torchair._ge_concrete_graph.utils import dtype_promote
from torchair.ge import attr


@register_fx_node_ge_converter(torch.ops.npu.{接口名}.default)
def convert_{接口名}(
    {必选Tensor参数},
    {其他必选非Tensor参数},
    *,
    {可选参数},
    meta_outputs: TensorSpec = None,
):
    return torchair.ge.custom_op(
        "{GE Op名称}",
        inputs={
            "{输入名}": {输入变量},
            ...
        },
        attrs={
            "{属性名}": attr.{类型}({属性值}),
            ...
        },
        outputs=[
            "{输出名1}",
            "{输出名2}",
        ]
    )
```

### 关键点

1. **函数命名**：`convert_{接口名}`，以 `convert_` 开头（参考 sparse_flash_attention.py）
2. **装饰器**：`@register_fx_node_ge_converter(torch.ops.npu.{接口名}.default)`
3. **返回值**：使用 `torchair.ge.custom_op()` 返回多个 Tensor
4. **inputs**：字典形式传递所有 Tensor 输入，可选 Tensor 用 `None`
5. **attrs**：字典形式传递属性，使用 `attr.Float()`、`attr.Int()`、`attr.Str()` 等
6. **outputs**：列表形式指定输出名称

---

## § 2.4 文件操作规范（重要）

### 操作模式分类

| 模式 | 文件 | 操作说明 |
|-----|------|---------|
| **GE 图模式（追加）** | `_ge_concrete_graph/auto_generated_ge_raw_ops.py` | 在文件末尾追加新的 GE raw op 函数 |
| **GE 图模式（新建）** | `_ge_concrete_graph/ge_converter/custom/{op_name}.py` | 创建全新的 converter 文件 |
| **aclgraph 模式（仅新建）** | `_ge_concrete_graph/ge_converter/custom/{op_name}.py` | 仅需创建 converter，无需 GE 原型注册 |

### 路径差异注意

模板路径与实际路径可能存在差异：

| 说明 | 模板路径 | 实际路径示例 |
|-----|---------|-------------|
| torchair | `torchair/_ge_concrete_graph/...` | `torchair/python/torchair/_ge_concrete_graph/...` |

**必须根据实际仓库结构调整**，不能机械套用模板路径。

### auto_generated_ge_raw_ops.py 追加位置

在文件末尾、最后一个函数定义之后追加：

```python
# 最后一个已有函数
def AlltoAllMatmul(...):
    ...
    return y, all2all_out

# ← 在此处追加新函数（保持相同缩进和格式）
def AddRmsNormDynamicMxQuant(...):
    ...
    return y, x_out, mxscale_out, rstd_out
```

### 关键禁忌

- 🚫 **禁止**创建临时文件再手动合并
- 🚫 **禁止**修改文件顶部导入语句（除非新增依赖）
- 🚫 **禁止**生成两个连续下划线开头的函数/变量名（`__npu_xxx`），这会导致 Python 名称修饰问题
- ✅ **必须**保持与已有代码相同的缩进风格（4空格）
- ✅ **必须**确保新函数的 docstring 格式一致
- ✅ **必须**在所有代码生成时，检查生成的函数名不包含 `__npu_` 模式
