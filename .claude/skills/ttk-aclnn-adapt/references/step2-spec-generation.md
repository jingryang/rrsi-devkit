# Step 2：生成 golden.py

目标：把用户 golden 包装成 TTK ACLNN TestSpec，并保证**参数顺序与 aclnn C 形参一致**。

> 本文的 `aclnnXxx`、`XxxAclnnTestSpec`、`in0/in1/out0` 都是占位符，按 Step 0 契约替换。

## 1. 文件与注册

在 `WORKDIR` 下生成唯一代码产物 `golden.py`（文件名不能以 `_` 开头），显式注册：

```python
__spec__ = {"aclnnXxx": "XxxAclnnTestSpec"}
```

用户原始 `USER_GOLDEN` 不改；修正/适配后的版本写到 `$WORKDIR/golden.py`。
旧版本、诊断脚本等放 `$WORKDIR/debug/`，不要留在产物根目录。

- 注册 key == CSV 的 `api_name`（大小写完全一致）。
- 类名可自由命名；有 `__spec__` 时不再依赖 `PascalCase + TestSpec` 约定。
- `--plugin "$WORKDIR"` 指向目录即可。

## 2. golden 的调用契约（ACLNN）

框架调用自定义 golden 时：

```
args = [按 C 形参顺序排列的张量/标量]，去掉 workspaceSize / executor
```

- **张量队列包含输入和输出**：输出张量由框架分配并常量初始化后一并传入；
- 标量（`aclScalar*`）从标量队列按序插入；C 基本类型（如 `double`）从 `attributes` 取值后按序插入；
- 返回值必须是**输出列表**，顺序与 `output_tensor_indexes` 一一对应；
- 入参是 CPU 侧 `torch.Tensor`（非 torch 原生 dtype 时可能是 numpy 视图，见 `use_numpy`）；
- `**kwargs` 始终接收：`testcase_name`、`tensor_dtypes`、`tensor_formats`、`scalar_dtypes`、`use_numpy`、`short_soc_version` 等；CSV `attributes` 中未被形参消费的键也会进入 kwargs。

以 Step 0 契约 `<in0, in1, attr0, attr1, out0, out1, out2>` 为例，调用形态是：

```python
golden(in0, in1, attr0, attr1, out0, out1, out2, **kwargs)
```

用户 golden 常写成只接收输入和属性的形式（如 `user_op(in0, in1, attr0=..., attr1=...)`），
**直接注册会因多余位置参数报错或把张量绑到标量上**。必须写适配层。

## 3. 通用适配模板

```python
# golden.py
import torch

__spec__ = {"aclnnXxx": "XxxAclnnTestSpec"}


def _compute(in0, in1, attr0, attr1):
    """用户 golden 的数学实现（照抄 USER_GOLDEN，不改变语义）。"""
    ...
    return [out0, out1, out2]


class XxxAclnnTestSpec:
    def golden(in0, in1, attr0, attr1, out0=None, out1=None, out2=None, **kwargs):
        # 输出形参只为对齐 C 签名，计算不需要它们
        return _compute(in0, in1, attr0, attr1)
```

要点：

- 形参名不必与头文件一致（函数形式按位置绑定），但**顺序必须一致**；输出形参用默认值，避免框架传入时缺参。
- 输出列表的顺序必须与 `output_tensor_indexes` 一致；数量不一致会在比对阶段报错。
- 若用户 golden 还有自定义关键字参数，确认它们在 `attributes` 或 kwargs 中同名可见。
- 不确定签名时用 `scripts/dump_aclnn_signature.py` 对照。

## 4. dtype 与精度

- 按文档声明的输出 dtype 返回：例如统计类输出强制 float32、主输出与输入同 dtype。
- 计算精度：
  - 先保持用户 golden 的算术精度（通常 float32），不要一上来就改语义；
  - 若 Step 5 证明失败来自 golden 的舍入误差（近零抵消），再考虑内部用 float64 计算、最后 cast 到输出 dtype——这是**提高 golden 准确度**，不是放宽判据。
- 不要在 golden 里对输出做 clamp/round 来"凑"比对结果。

## 5. tolerance（可选）

默认不写 `tolerance`，走 TTK 默认 `mixed`。只有算子有明确生态标准时才声明：

```python
tolerance = {
    "float32": {"standard": "mix_tolerance"},
    "float16": {"standard": "mix_tolerance"},
}
```

`stat_rel_err` 对近零元素敏感，容易把抵消点误差放大成 FAIL；是否采用要以 Step 5 的取证为准。

## 6. customize_inputs（按需）

用户 CSV 的范围不足以覆盖场景（固定值、特殊值、可复现随机）时：

```python
class XxxAclnnTestSpec:
    def customize_inputs(in0, in1, attr0, attr1,
                         out0=None, out1=None, out2=None, **kwargs):
        # 原地写：返回 None 即可
        ...
        return None
```

- 参数顺序同样按 C 形参；
- 返回序列只对应**输入张量槽**（纯输出槽除外），或整体返回 `None` 表示原地修改；
- 若只需范围，优先用 CSV 的 `input_data_ranges`，不要写插件。

## 7. 自检

- spec 文件语法：`python3 -c "import ast; ast.parse(open('$WORKDIR/golden.py').read())"`
- 接线是否正确只能靠 Step 3 冒烟验证：`GOLDEN_FAILURE` / `TypeError` / 输出数量不匹配都是签名问题。
- 不要用 `register()` 手写签名——签名应来自算子头文件；手写会与真实接口漂移。
