# golden 提取与规范化

## 1. 来源优先级

```text
用户显式 golden_path
> PATH/tests/assets/golden.py
> PATH/tests/**/golden*.py
> PATH/tests/st/**/executor_*.py 中的 compute_golden / golden 函数
> 由文档公式 + op_host infershape + op_kernel 计算路径推导
```

推导 golden 属于需求决策：必须在 `design.md` 说明推导依据、与源码可能的差异及风险，不能让最终需求处于“待确认”状态。

## 2. 常见源码 golden 形态

### 2.1 `__golden__` 注册表（tests/assets/golden.py）

```python
__golden__ = {
    "kernel": {"op_name": "op_golden"},
    "aclnn": {"aclnnOp": "op_aclnn_golden"},
}
```

处理规则：

1. 读取注册表与函数签名，确认被测入口。
2. 一般选择与 kernel 语义对应的 golden；若需求以 aclnn 接口为外部契约，则选择 aclnn 入口，并单独处理它额外做的布局转换。
3. 多个函数共享 `_compute_*` 时，以共享计算函数为语义核心重写。
4. 去掉 `__golden__`、`__input__`、`__spec__`、`_TOLERANCE` 等测试框架配置。

### 2.2 executor 中的 `compute_golden`

`tests/st/<api>/executor_<api>.py` 通常含 numpy/torch 混合实现：

- 确认它接受的是逻辑张量还是带布局的内存张量（NHWC/NCHW/CHW）。
- 把 numpy 运算逐项映射为 torch，保持 `axis`、`keepdims`、broadcast、dtype 提升顺序一致。
- `torch.bfloat16` 与 numpy 的转换需要显式经 float32，避免精度路径改变。

### 2.3 委托兄弟算子

部分 golden 通过相对路径加载另一个算子的 golden（例如 `add_rms_norm_cast` 委托 `add_rms_norm`）。必须：

1. 读取被委托文件并内联实际计算；
2. 保留委托层新增的后处理（cast、量化、输出裁剪）；
3. 产出物不得依赖源码树相对路径。

### 2.4 无 golden

按文档公式实现，并用 kernel/infershape 校验 shape、dtype、输出顺序；在 `design.md` 标记为“推导实现”。

## 3. 规范化规则（强制）

1. 模块只有一个公开函数，名称等于 `ops_snake`。
2. 其余模块级辅助函数加前导下划线，或写成入口内部嵌套函数。
3. 入口形参不得叫 `self`；按仓库约定改为 `params` 或其他语义等价名称，并同步函数体、docstring、desc 调用示例。
4. 张量参数补类型标注：
   - 必选：`torch.Tensor`；
   - 可缺省/可空：`Optional[torch.Tensor] = None`；
   - 列表：`List[torch.Tensor]` / `Optional[List[torch.Tensor]] = None`。
5. 参数顺序与默认值以 op def / 文档为准，不照搬源码 golden 的框架 kwargs。
6. 删除 `**kwargs`、`output_dtypes`、`testcase_name` 等测试框架参数；若这些参数影响语义（例如决定输出 dtype），把规则固化为需求决策。
7. 保留数值逻辑：升精度、归约顺序、epsilon 位置、clamp、mask、特殊值处理、输出 cast。
8. 多输出顺序按 op def `this->Output(...)` 与 aclnn 输出槽位确定，不按字典或集合顺序。
9. 输出 dtype 与文档一致：例如 mean/rstd 恒 float32，y 与输入同 dtype。
10. 自包含、确定性、CPU 可运行；禁止 `torch_npu`、禁止读取源码目录。

## 4. 必须核对的语义点

- 输入 dtype 与计算 dtype：fp16/bf16 是否先升 fp32，何时转回；
- 归约维与 keepdim 规则；
- 属性默认值与类型（int/float/bool/list）；
- 可选输入缺省时的行为；
- 空张量、零维、单元素、极大/极小 shape；
- 广播规则与输出 shape；
- 特殊值：NaN 传播、Inf 符号、±0、除零；
- in-place 语义与输出槽；
- 布局：ND/NCHW/NHWC，逻辑张量与存储视图；
- 数值稳定技巧：Welford、Newton-Raphson、分段归约对最终数学结果的影响。

## 5. 验证

1. 用 2~3 组代表性 shape/dtype/属性在 CPU 运行 golden。
2. 与源码 golden 对照：同输入、同 dtype，比较每个输出；记录最大绝对/相对误差。
3. 检查输出数量、shape、dtype。
4. 检查边界：最小 shape、非对齐长度、可选输入缺省、特殊值（若契约要求）。
5. 结果写入 `design.md` 的“源码依据与需求决策”与验证状态；不能运行或无法对照时，明确写“未执行”及原因。

## 6. 常见错误

- 直接把 numpy golden 复制成 torch，`np.mean` 与 `torch.mean` 的 dtype 提升不同；
- 忘记把 bf16 输入升 fp32，导致与源码精度不一致；
- 输出顺序按源码返回元组猜测，与 op def 不一致；
- 把测试框架的 `output_dtypes` 分支删掉后，输出 dtype 变成固定值；
- 保留了源码 golden 的 fallback 分支（空张量返回零），但需求要求报错；
- 引入源码树的相对 import，导致需求包不可移植。
