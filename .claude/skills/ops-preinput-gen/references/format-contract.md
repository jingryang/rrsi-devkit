# 前置输入五文件格式契约

> 本文件是**规范**：字段集封闭，不得自行扩展。
> 标「硬约束」的必须遵守；标「惯例」的可按算子语义偏离，但需在交付说明里写明理由。

## 0. 下游怎么吃这五个文件（决定了什么必须严格、什么可以松）

| 消费者 | 读什么 | 严格程度 |
|---|---|---|
| eval runner 的 `read_category()` | **只读** `proto.yaml` 的 `operator.category`，作为 `{category}` 注入 prompt 上下文 | **唯一的程序化读取点**：键名错/文件坏 → category 变空串，下游 LLM 拿不到算子归类 |
| 工作目录准备 | 把算子目录下**所有文件平铺复制**到 `operators/{op}/` | 文件名即契约 |
| architect / developer / reviewer | 把 `desc.md` / `cases.yaml` / `proto.yaml` / `golden.py` 当 **prompt 上下文**读 | LLM 语义消费 |
| 精度比对 harness | `proto.yaml` 的 `precision_thresholds`；整数/索引输出默认精确相等，浮点输出阈值 `0` → 触发 bit-exact 分支 | 程序化 |

**关键结论：没有任何 `cases.yaml` / `desc.md` 的强 schema 校验器。**
畸形产物不会被拒绝，只会静默拉低下游成功率。所以校验责任必须落在生成侧
（用 `scripts/validate_preinput.py`），这是本 skill 存在的核心理由之一。

## 1. 目录与文件名

```
<level1|level2|level3>/<op_snake_case>/
├── desc.md       ← spec 文件名**必须**是 desc.md（不是 spec.md / <op>.md）
├── cases.yaml    ← 唯一事实来源
├── cases.csv     ← 由 cases.yaml 机械派生，禁止手写
├── proto.yaml
└── golden.py
```

- 五文件齐备是硬约束，不要多放文件（个别算子有辅助脚本属特例，非常规）。
- `difficulty` 与目录层级**恒等**：`level1↔L1`、`level2↔L2`、`level3↔L3`。

## 2. cases.yaml —— schema 刚性，字段集封闭

顶层只有 `cases:`。每条用例**恰好 7 个键，全部必填，无可选键**：

```yaml
cases:
- operator: Gelu            # PascalCase，必须 == proto.operator.name
  case_id: 1                # 1..20 连续递增
  input_shape:
  - [1024, 1024]            # list of shape；每个输入一项，顺序同 proto.inputs
  dtype: [float16]          # 长度 == len(input_shape)
  attrs: {approximate: none}  # 无属性算子写 {}
  value_range: [-1, 1]      # 见 §2.2
  note: "S-float16-1M-对齐-对称小值域-精确模式"   # 见 §2.4
```

### 2.1 硬约束

- **恰好 20 例**。这是不可变契约。
- `case_id` 从 1 连续到 20。
- `len(dtype) == len(input_shape)`（例外：`foreach_*` 这类 `is_list` 算子，
  一个 dtype 覆盖整个张量列表）。
- `len(input_shape)` ∈ [必选输入数, 全部输入数]。

### 2.2 value_range 两种合法写法

| 写法 | 语义 |
|---|---|
| 扁平 `[lo, hi]` | 所有输入共用同一值域 |
| 逐输入 `[[lo,hi], [lo,hi], ...]` | 长度必须 == `len(input_shape)` |

- **`null` 占位**：逐输入写法里，`input_shape` / `dtype` / `value_range` 三个列表
  **同位置同时写 `null`**，表示「该可选输入本例缺省」，位置对齐不打破。
  例：
  ```yaml
  input_shape: [[1024, 3584], [3584, 4608], [4608], null, null, [4608]]
  dtype:       [int8, int8, float32, null, null, int32]
  value_range: [[-128,127], [-128,127], [0.001,0.01], null, null, [-100,100]]
  ```
- **特殊值写法**：YAML 原生 `.inf` / `-.inf` / `.nan` 是唯一规范写法。
  写成字符串 `'inf'` 会被解析成文本，**禁止**。
- **科学计数法必须带显式 `+` 号**。PyYAML 走 YAML 1.1 规则：
  `3.0e38` 被解析成**字符串**，`3.0e+38` 才是浮点。写 fp32 边界值用例时极易踩到，
  且畸形值会一路静默流到下游。G9 门会抓这个（报「含非数值项」）。

  ```yaml
  value_range: [-3.0e38, 3.0e38]     # ✗ str，错的
  value_range: [-3.0e+38, 3.0e+38]   # ✓ float
  ```

### 2.3 dtype 与可表示范围必须自洽

整型的可表示范围是**非对称**的，`value_range` 取满量程时要写准：
`int8 → [-128, 127]`、`uint8 → [0, 255]`、`int32 → [-2147483648, 2147483647]`、
`float16 → [-65504, 65504]`。

### 2.4 note 字段语法

```
<规模档>-<dtype>-<元素数>-<对齐性>-<值域或特殊值>[-<维度>][-<属性>][ | baseline_kernels: ...]
```

- 规模档 `S` / `M` / `L`
- 元素数用 **2^20 = 1M** 口径（`[4096,4096]`=16.7M → 写 `16M`）
- 对齐性三档：`对齐` / `非对齐` / `质数非对齐`
- 值域类：`对称微小值域` / `对称小值域` / `对称大值域` / `非对称小值域` /
  `非对称中值域` / `非对称大值域`
- 特殊值类：`inf特殊值` / `nan特殊值` / `零值` / `float16边界值` / `float32边界值`
- **`| baseline_kernels: Xxx×N` 是下游 profiling 回填的度量注解，生成时一律不写。**
  生成侧无法测量，编造会造成 yaml↔csv 漂移。

## 3. cases.csv —— 100% 机械派生，禁止手写

- 表头固定：`operator,case_id,input_shape,dtype,attrs,value_range,note`
- 21 行（表头 + 20 例）。
- 每个结构化列 = 对应 yaml 值的 `json.dumps(..., ensure_ascii=False)`；
  `csv.writer` 默认 QUOTE_MINIMAL（无逗号的值不加引号，如 `[[1000003]]`）。
- inf/nan 在 CSV 内嵌 JSON 里写成**字符串** `"inf"` / `"-inf"` / `"nan"`。
- `input_shape` / `dtype` / `value_range` 三列**可完全机械派生**。
  一律用 `scripts/gen_cases_csv.py` 生成，不要手写、不要事后单独改 CSV。

## 4. proto.yaml

顶层只有 `operator:`。

**必填**：`name` `category` `difficulty` `formula` `description`
`shape_support` `attrs` `inputs` `outputs` `schema`
**可选**：`precision_thresholds`（按输出 dtype 配置；整数/索引输出可写 0，量化整数输出可写非零绝对误差）、`note`

- `inputs[]` / `outputs[]`：必填 `name` `description` `dtype`；
  可选 `shape`、`optional`、`is_list`、`compare`（`false` = 该输出不做逐元素比对）、`index_gather`
- `attrs[]`：必填 `name` `type` `description`；可选 `required` `default`
- `attrs: []` 合法（无属性算子）
- `category` 取值全集（13 类；作为上下文注入下游 prompt，**建议别造新词**以保持归类一致）：

  `Elementwise` `Broadcast` `Reduction` `Normalization` `Contraction`
  `LayoutTransform` `SortSelect` `ScatterUpdate` `IndexGather`
  `MaskPredicate` `NumericalStable` `VVFusion` `FusedComposite`

- `schema` 形如 `gelu(Tensor x, str approximate="none") -> Tensor y`，
  与 `desc.md` §3 算子原型**去掉 `torch.ops.npu.` 前缀后逐字相同**，
  函数名 == `golden.py` 里的 `def` 名。

## 5. desc.md —— 节骨架固定

节标题与顺序**不可变**。L1/L2/L3 是**六节**；**L4 FA 注意力家族不写 `## 6. 额外信息`，只有前五节**
（注意力算子没有可复现的 `.so` 直调示例，§6 无信息量）：

```
## 1. 算子简介      → 一段简介 + **主要应用场景**(bullet) + **算子特征**(bullet：难度等级/输入输出/维度)
## 2. 算子定义      → ### 数学公式（LaTeX $$）  [+ ### 特殊情况 | ### 处理流程]
## 3. 接口规范      → ### 算子原型 / ### 输入参数说明 / ### 输出
                     / ### 数据类型 / ### 规则与约束 / ### 支持范围
## 4. 精度要求      → 固定样板，见 §5.2
## 5. 标准 Golden 代码 → ```python 代码块，与 golden.py 同名同签名
## 6. 额外信息      → ### 算子调用示例   ← **仅 L1/L2/L3；L4 不写此节**
```

必备 H3 子节：`数学公式` `算子原型` `输出` `数据类型` `输入参数说明`
`规则与约束` `支持范围`；`算子调用示例` **仅 L1/L2/L3 必备**（L4 无 §6 故不含）。
G6 门按 `difficulty` 取对应切片：L4 期望五节且**不得出现第 6 节**。

### 5.1 §3「支持范围」表 —— 三列，表头固定

```
| 维度 / 参数 | 范围 | 备注 |
```

典型 3~15 行。**两列各有明确分工，这是全文最容易做错的地方**：

| 列 | 是什么 | 怎么定 |
|---|---|---|
| **范围** | 算子**声明支持**的上界 | 由「语义合法性 + 硬件/dtype 上限」推出，与 cases 无关。可用 `2^23` 幂次、`64M` 后缀 |
| **备注** | cases.csv **实测覆盖**面 | 必须**从 cases.yaml 反算**，写成 `cases.csv 实测 A ~ B` 或 `实测 1D / 2D / 3D` |

**自洽律：`备注(实测) ⊆ 范围(声明)`，且备注必须等于 cases 的真实极值。**

> 典型错误：声称「各维实测 2 ~ 8192」，但 cases 里存在 `[255, 8193]` —— 8193 > 8192，
> 不自洽。备注列必须从 cases.yaml **反算**，不能凭印象写。G8 门会机械比对。

### 5.2 §4「精度要求」样板

**默认直接抄这段固定样板**：引用生态算子精度标准 → MERE/MARE 两条公式
→ 六 dtype 阈值表（`2^-10 / 2^-7 / 2^-13 / 2^-11 / 2^-3 / 2^-2`）
→ 「MERE < Threshold 且 MARE < 10 × Threshold 判通过」。

仅当输出是**索引/整数/去重结果等需要逐位精确**的算子，或算子存在明确的整数容差语义时，才改写为精确/自定义阈值版。
此时在 `proto.yaml` 按**输出 dtype** 写 `precision_thresholds`：

- 需要逐位精确的输出 dtype 写 `0`
- 量化/舍入类整数输出可写非零绝对误差阈值（例如 `int8: 1.0` 表示允许 ±1）
- 不要把 `precision_thresholds` 机械写成“所有 dtype: 0”；混合输出算子应只覆盖需要特判的输出 dtype

### 5.3 §3 算子原型 与 §6 调用示例 —— 必须用本仓真实的直调约定

⚠️ **禁止写 `cann_bench.<op>(...)` / `import cann_bench`** —— 那是另一个基准仓
（cann-bench）的包，本仓没有，照抄会给下游一个跑不通的示例。

ops-direct-invoke 是**直调**流程：算子在开发阶段被编译成 `.so`，经 `TORCH_LIBRARY`
注册进 `npu` 命名空间，再从 PyTorch 调用。约定如下：

| 项 | 约定 |
|---|---|
| 命名空间 | `torch.ops.npu` |
| 输入 | 需 `.npu()` 搬到设备后再调用 |

所以：

**§3 算子原型**

```python
torch.ops.npu.<op>(Tensor x, ...) -> Tensor y
```

**§6 算子调用示例**（**仅 L1/L2/L3；L4 FA 家族不写 §6**）

```python
import torch
import torch_npu

x = torch.randn(1024, 1024, dtype=torch.float32).npu()   # 输入需先搬到 NPU
y = torch.ops.npu.<op>(x)

torch.npu.synchronize()
```

⚠️ **不写** `torch.ops.load_library("build/lib<op>_ops.so")` 及其「# 加载…算子库…」注释，
**也不写**「> 算子编译为…注册到 npu…接口契约（等于把注册名写进了需求）」的收尾 blockquote。
这些是**接入背景说明**，不属于需求前置输入内容；`.so` 加载与注册契约由下游流程负责。
**G16 门会拦：出现 `load_library` 或含「接口契约」的收尾 blockquote 判 FAIL。**

`proto.yaml` 的 `schema:` 字段保持**无前缀**的裸签名（`abs(Tensor x) -> Tensor y`），
它正好等于 `TORCH_LIBRARY` 里 `m.def()` 的 schema 字符串，不要加 `torch.ops.npu.`。

G16 门会校验这一点：默认 `--target direct-invoke` 下出现 `cann_bench` 判 FAIL；
`load_library` / 接口契约收尾 blockquote 也判 FAIL。
（`--target cann-bench` 仅用于审计 cann-bench 原生素材，生成算子时不要用。）

## 6. golden.py

```python
#!/usr/bin/python3
# coding=utf-8

# --------------- (CANN Open Software License 2.0 头) ---------------

import torch

"""
<PascalCase>算子Torch Golden参考实现

<一句话描述>
公式: <formula>
"""
def <schema 函数名>(x: torch.Tensor, ...) -> torch.Tensor:
    """<docstring：描述 + 公式 + Args + Returns>"""
    ...
    return y
```

- 函数名 == `proto.operator.schema` 的函数名 == snake_case 算子名。
- 必须能被 `importlib` 直接加载并按「位置传 input_shape 对应张量 + attrs 传 kwargs」调用。
- **fp16/bf16 建议升 fp32 计算再降回**，避免 golden 自身精度不足反而拖垮比对。
  `desc.md` §5 与 `golden.py` 允许在实现细节上略有差异（如 §5 省略升精度样板），
  但**函数名与签名必须一致**。
