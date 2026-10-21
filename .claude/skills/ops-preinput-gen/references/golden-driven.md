# golden-driven 模式：从 golden 实现生成前置输入五文件

> 本文承载 name-driven 之外的**第二种输入模式**：不给算子名，只给一份
> **golden 实现**（KernelBench 风格的 `class Model(nn.Module)`），同样产出合规五文件。
>
> 与 name-driven 是**反的**：name 模式里 `golden.py` 由语义反推着写；golden 模式里
> **golden 实现本身就是语义唯一事实源** —— 先把它转写成可导入的自由函数 `golden.py`，
> 其余四文件（proto / desc / cases / csv）全部对齐这个函数。
>
> 单输入 elementwise 的 20-case 骨架仍走 `case-design.md`；多张量输入的耦合 / 角色化值域
> / 语义不变量仍走 `l2-l3-design.md` —— 本文只补「Model → 五文件」这段转换。

---

## 0. 什么时候用本文

输入是一段 Python，含 `class Model(nn.Module)`，`forward(self, x, ...)` 把若干 torch
算子串成一个**融合算子**（可能只有一个算子，也可能是 where→expm1→where→add 这种链）。
文件名往往是编号（`0873.py`），**没有算子名**。

先跑机械抽取拿事实包：

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/resolve_golden.py <golden.py>
# 有构造参数时补上，并可加运行探测确认 output 形态：
#   --init-args num_channels=4 alpha_value=0.25 --input-shape 2,4,8
```

它输出 `forward_args` / `stateful` / `op_sequence` / `tensor_inputs` /
`suggested_name` / `hints`，是下面每一步的依据。

---

## 1. 核心转换：Model → 自由函数 golden.py

| Model 元素 | → 五文件角色 |
|---|---|
| `forward(self, x, ...)` 的形参（除 self） | **数据输入**，proto.inputs 打头、cases `input_shape[0..]` |
| `self.X = nn.Parameter(...)` / `torch.tensor(...)` / `torch.randn(...)` | **张量输入**（可随机化），**不是**烘焙常量 |
| `self.m = nn.<Module>(...)` 子模块 | 内联成 `F.*` 泛函；其权重张量也提升为**张量输入** |
| `__init__` 的标量构造参数（`num_channels`、`alpha`） | attrs，或某个输入的形状决定量 |
| `__init__` 的形状构造参数（`condition_tensor_shape`） | 决定对应张量输入的耦合 shape |
| `forward` 里的算子序列 | 命名（按算子组合）与定级的依据 |

### 1.1 为什么 stateful 张量必须是输入，而不是烘焙常量

下游泛化测试要对**同一组随机输入**同时喂 golden 和待测 kernel，逐元素比对精度。
若把 `self.condition = nn.Parameter(torch.randn(...))` 当成 golden 内部的隐藏随机常量，
kernel 侧拿不到同一份权重，跨用例根本无法复现比对。所以：

> **`__init__` 里所有 Parameter / buffer / 子模块权重，一律提升为 golden 函数的显式入参。**

这与 `baddbmm` 把 `input`/`batch1`/`batch2` 全列为输入是同一个道理。

### 1.2 子模块 → 推理期泛函速查

`Model` 里的 `nn.<Module>` 是有状态层；转写时**内联成对应 `F.*` 泛函**，并把它的权重
张量提升为输入。**训练态模块一律取推理（eval）语义**：

| 子模块 | 泛函形式 | 提升为输入的权重 | 关键点 |
|---|---|---|---|
| `PReLU(C, init=a)` | `F.prelu(x, weight)` | `weight` (C,) 或 (1,) | init 值 → weight 的初值语义，作为一路输入 |
| `BatchNorm{1,2,3}d(C)` | `F.batch_norm(x, running_mean, running_var, weight, bias, training=False, eps)` | `running_mean/var, weight, bias` (C,) | **training=False**；`running_var` 值域必须为正 |
| `LayerNorm(shape)` | `F.layer_norm(x, shape, weight, bias, eps)` | `weight, bias` | normalized_shape 取自构造实参 |
| `GroupNorm(g, C)` | `F.group_norm(x, g, weight, bias, eps)` | `weight, bias` (C,) | `C % g == 0` 写进约束 |
| `Linear(in, out)` | `F.linear(x, weight, bias)` | `weight` (out,in)、`bias` (out,) | 耦合：x[-1]==in |
| `Conv2d(...)` | `F.conv2d(x, weight, bias, stride, padding)` | `weight` (C_out,C_in,K,K)、`bias` (C_out,) | 见 l2-l3-design 卷积耦合 |
| `Embedding(n, d)` | `F.embedding(idx, weight)` | `weight` (n,d) | x 为整型索引 |

`resolve_golden.py` 的 `stateful[].functional` 会直接给出该形式，`tensor_inputs`
已把权重展开成一路路输入（命名 `<attr>_<weight>`，如 `batch_norm_running_var`）。

### 1.3 golden.py 撰写规则

- **写成自由函数**，函数名 == `suggested_name.snake` == proto.schema 函数名。
- **入参顺序**：先所有张量输入（数据输入 + 提升的权重，按 `tensor_inputs` 顺序），
  后标量 attr（带默认值）。这正是 `validate_preinput.py` G13 的绑定顺序
  （形参名命中 attrs 就填 attr，否则按序取下一个张量）。
- **保持 forward 的算子顺序**，逐句翻译，不要「优化」掉中间算子。
- **in-place 前先 clone**：`x[mask] = 0` 这类下标赋值会改到入参，先 `x = x.clone()`。
- **reduction / exp 类升 fp32**：`max`/`sum`/`digamma`/`expm1`/`sigmoid` 等在 fp16/bf16
  下升 `float32` 计算再降回，避免 golden 自身精度不足拖垮比对。
- **docstring 写清**：一句描述 + 公式 + Args + Returns（照 format-contract §6）。

### 1.4 三个边角（本 skill 5 个样例里出现过）

- **reduce 到标量再广播**（0000：`x = torch.max(x)` 后 `x + parameter`）：
  golden 照写即可，输出 shape 由 `parameter` 决定；desc/proto 的输出 shape 要如实写
  （不是输入 shape）。
- **in-place 下标赋值**（1043：`x[mask] = 0`）：clone 后赋值；`mask` 由 `isin` 得到，
  `isin_values` 是一路**1D 成员集**输入，值域取「x 值域内的若干离散点」。
- **多 where 掩码融合**（0873：两次 `torch.where(x>0, x, ·)`）：谓词 `x>0` 不额外建输入，
  `condition`/`value`/`exp_tensor` 各是一路与 x 同形（或可广播）的张量输入。

---

## 2. 定级与分类（融合算子）

`resolve_golden.py` 的 `hints` 给初判，按下表复核：

| 判据 | difficulty |
|---|---|
| 单算子逐元素、无额外张量输入 | **L1**（如 0018 sigmoid） |
| 单数据输入 + 一层结构算子 / 2 个算子的短融合 | **L2**（如 0048 elu+triu） |
| ≥2 路额外张量输入 / 含 reduction / ≥3 个算子的长融合 | **L3**（如 0000 / 0873 / 1043） |

category（取 `format-contract.md` §4 的 13 类之一，别造新词）：

- 单算子逐元素 → `Elementwise`
- `where` / `isin` / `masked_fill` 主导 → `MaskPredicate`
- 含 `sum`/`mean`/`max` 归约 → `Reduction`（若归约只是链条一环、整体是融合，可判 `FusedComposite`）
- 其余多算子融合 → `FusedComposite`

> `hints.category` 只是提示。0000 含 `max` 被机判 `Reduction`，但它整体是
> batch_norm→digamma→max→add 的融合，判 `FusedComposite` 更贴切 —— 以语义为准。

---

## 3. 融合算子的 cases 设计（在 l2-l3-design.md 之上补三条）

多张量输入的耦合 shape、角色化值域、语义不变量**全部照 `l2-l3-design.md`**。golden 模式
额外注意：

1. **权重张量的 shape 必须与 x 耦合，并写进 desc**（否则 G15 告警、下游造数造错）：
   - `F.prelu` 的 `weight`：长度 == x 的通道维 C（或 1）
   - `F.batch_norm` 的 4 路权重：长度均 == C == x 的通道维（NCHW 的第 1 维）
   - 广播型（0873 的 condition/value/exp_tensor）：与 x 同形，或标准可广播 shape
2. **按角色分配值域**：`running_var` 恒取**正区间**（如 `[0.5, 2]`，方差不能为负）；
   `weight`/`bias`/`parameter` 与数据同量级或 1/10；`isin_values` 取 x 值域内的离散点；
   谓词涉及的输入不写 inf/nan。
3. **成员集类输入单列**（`isin_values`）：它不是逐元素张量而是「被判定集合」，
   1D、元素个数小（几个到几十个），值落在 x 值域内 —— 单开说明，别套 x 的骨架。

特殊值槽位按语义裁剪（照 l2-l3-design §4.3）：inf/nan 只施加在**浮点数据主体**上，
权重/成员集/索引保持合法。

---

## 4. desc.md 的额外要求

- **§1 算子简介必须记原文件编号作溯源**：一句「本算子改编自 golden 实现 `<source_id>`
  （如 `0873`）」，让产物能回指来源。
- **§3 支持范围表用符号维度**（`C` = 通道维、`N`/`H`/`W` 等），表后 `约束：` 行集中声明
  权重↔x 的 shape 耦合（≥3 输入必须有，G15 检查）。
- **§5 标准 Golden 代码**与 `golden.py` 同名同签名（允许 §5 省略升精度样板）。
- **§3 原型 / §6 调用示例**仍用本仓直调约定 `torch.ops.npu.<op>(...)` +
  `torch.ops.load_library("build/lib<op>_ops.so")`，**不得出现 `cann_bench`**（G16）。

---

## 5. 收尾：G13 是转换正确性的兜底

`validate_preinput.py --run-golden` 的 **G13 会实跑你写的自由函数复算全部 20 例**。
它就是在验证「Model → 自由函数」这步转换有没有做对：

- golden 跑挂在 `size must match` / `out of bounds` 这类 → 你的**耦合 shape 设计错了**，
  回 cases 修，并确认 desc 的约束写全（否则 `G13-unsynth` 会点名，下游同样会踩）。
- golden 跑挂在别的异常 → 多半是**转写本身错了**（漏 clone、算子顺序错、
  子模块泛函形式不对）—— 回 golden.py 修。

> 记住：golden 模式下 `golden.py` 必须是原 `Model.forward` 的**语义等价自由函数**。
> 转写完先本地 `python3 -c "from golden import <fn>; ..."` 手跑一例，再进 16 门。
