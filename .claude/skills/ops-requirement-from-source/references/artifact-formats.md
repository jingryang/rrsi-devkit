# 产物格式要求

本文件是 `ops-requirement-from-source` 的格式契约。用例数固定 20、要求 `design.md`、`note` 为一句话自然语言描述，全部产物限定在所选芯片范围内。`references/exp/` 提供格式样例，只用于对齐结构，不是目标算子的语义来源。

## 1. 文件夹与命名

```text
<输出路径>/<ops_snake>/
├── desc.md
├── golden.py
├── proto.yaml
├── cases.yaml
├── cases.csv
├── design.md
└── ttk/                      # 可选：TTK 验证产物（TTK_WORKDIR 未显式指定时的默认位置）
    ├── golden.py             # TTK TestSpec 包装层，不等于需求包 golden.py
    ├── cases.csv             # TTK 用例（七列 + pass/note），不写回需求包
    └── debug/
```

- `ops_snake`：snake_case 算子名，例如 `deep_norm`。
- `ops_pascal`：PascalCase 算子名，例如 `DeepNorm`。
- 文件夹名、golden 入口名、`proto.operator.schema` 入口名必须一致。
- `ttk/` 是验证证据目录，不是需求包必需产物；TTK 未执行或用户另行指定 `TTK_WORKDIR` 时可以不出现。其中的 `golden.py` 是 TestSpec 包装层，**不得**复制进需求包根目录。

## 2. golden.py

1. 唯一公开（不以 `_` 开头）的模块级函数名为 `ops_snake`。
2. 其他模块级辅助函数加前导下划线，或写成入口内部嵌套函数；模块级 import、docstring、常量不受限制。
3. 入口不得有名为 `self` 的形参；按仓库约定改为 `params` 或语义等价名称，并同步函数体、docstring、desc 调用示例。
4. 张量参数补类型标注：
   - 必选：`torch.Tensor`；
   - 可缺省/可空：`Optional[torch.Tensor] = None`；
   - 列表：`List[torch.Tensor]` / `Optional[List[torch.Tensor]] = None`；
   - 需要时在顶部补 `from typing import List, Optional`。
5. 标注与 `proto.yaml` 的 inputs 一致（含 `is_list`、是否必选）；只补类型标注，不改变参数顺序/默认值语义。
6. 多输出返回 `List[torch.Tensor]` / `Tuple[torch.Tensor, ...]`，顺序与 op def / aclnn 输出槽一致。
7. 文件必须以顶层 import/from 开头，以换行结尾，便于 desc 代码块逐字符校验。

## 3. proto.yaml

```yaml
operator:
  name: <ops_pascal>
  category: <类别>
  difficulty: <L1/L2/...>
  formula: <公式>
  description: <一句话功能>
  shape_support: <shape 规则>
  attrs:
  - name: ...
    type: ...
    default: ...
    description: ...
  inputs:
  - name: ...
    description: ...
    dtype: [...]
  outputs:
  - name: ...
    description: ...
    dtype: [...]
  note: ...
  schema: <ops_snake>(Tensor x, ...) -> Tensor y
```

要求：

- `operator.name` 为 PascalCase，且与 desc 一级标题一致。
- `schema` 以 `ops_snake(` 开头，参数顺序、默认值、输出数量与 op def / aclnn 接口一致。
- dtype 列表只包含文档声明支持、且在所选芯片种类（默认 A5）可用的组合。
- 可选输入标注可选性；属性默认值照抄 op def。

## 4. cases.yaml 与 cases.csv

- `cases.yaml` 为主数据，顶层为 `cases` 非空列表，**恰好 20 项**。
- 每个 case 的字段顺序固定：`operator, case_id, input_shape, dtype, attrs, value_range, note`。
- `operator` 为 `ops_pascal`；`case_id` 为 1~20 且唯一。
- `input_shape`、`dtype`、`value_range` 均为按输入顺序排列的列表。
- `attrs` 为映射；无属性写 `{}`。
- `note` 为一句话自然语言描述（单行、不带 JSON 结构），只概括该用例的外部可观察特征，例如 dtype、规模、对齐/尾块、值域形态、属性取值、特殊值、非连续视图；不写 `chips`/`layout`/`generator`/`seed`/`view`/`expected`/`behavior` 等机器字段，不写芯片种类，不出现 tiling key、模板编号、源码函数名、kernel 名称。
- 芯片种类由本次 `--chip` 统一决定，不逐用例标注；输出 shape/dtype 由 `proto.yaml` 与 golden 推导；布局默认 `ND`、连续视图，`seed` 固定为 `case_id`，只有非默认构造需要在 `note` 中点明。
- `cases.csv` 列顺序固定：

```text
operator,case_id,input_shape,dtype,attrs,value_range,note
```

- CSV 的结构化单元格使用 JSON；NaN/Inf 用字符串 `"nan"`、`"inf"`、`"-inf"`。
- YAML 与 CSV 表达同一批用例，顺序与内容必须逐项一致；不在两处独立维护。
- 用例必须满足“不重复、覆盖全”的要求，具体判定见 `case-design.md`。

## 5. desc.md

一级标题：

```markdown
# <ops_pascal> 算子 API 描述
```

固定章节：

```markdown
## 1. 算子简介
## 2. 算子定义
### 数学公式
### 特殊情况
## 3. 接口规范
### 算子原型
### 输入参数说明
### 输出
### 数据类型
### 规则与约束
### 支持范围
## 4. 精度要求
## 5. 标准 Golden 代码
## 6. 额外信息
### 算子调用示例
### 用例执行与数据构造约定
```

规则：

1. 算子原型写成 `cann_bench.<ops_snake>(...)`，保留参数表与返回签名。
2. `## 5. 标准 Golden 代码` 下的第一个 `python` fenced block 必须与 `golden.py` 从第一个顶层 import/from 到文件末尾逐字符一致；允许排除此前的 shebang、编码声明、License 注释。
3. 调用示例先 `import cann_bench`，再 `cann_bench.<ops_snake>(...)`；不要写 `import cann_bench.<ops_snake>`。
4. 第 4 节采用生态算子精度标准，给出 MERE/MARE 公式与 dtype 阈值表，并说明多输出如何分别判定。
5. 第 6 节的“用例执行与数据构造约定”说明全局数据生成规则（默认 uniform、seed 固定为 case_id、有限区间采样）、显式值列表/特殊值规则，以及 `note` 只写一句话特征、不承载机器字段的约定。
6. “支持范围”只描述本次所选芯片种类；其他芯片的约束不得出现。
7. 不出现 tiling key、模板编号、源码路径、内部函数名、内部枚举值。

## 6. design.md

内部设计文档，至少包含：

```markdown
# <ops_pascal> 算子设计分析（<芯片种类>，默认 A5）

## 1. 芯片范围与源码布局
## 2. 实现概览
## 3. 模板设计
## 4. 分核设计
## 5. 分块设计
## 6. 性能调优技巧
## 7. 模板与测试覆盖映射
## 8. 源码依据与需求决策
```

要求：

1. 记录本次采用的芯片种类（默认 A5）、该芯片对应的 arch/config/kernel/tiling 路径，以及被排除的芯片目录、配置和分支。
2. 记录 `PATH` 布局、采用的文档、排除的文档候选及理由、aclnn 接口映射。
3. 记录 golden 来源、提取/重写方式和 CPU 对照结果。
4. 模板设计可用 tiling key、内部模板名、函数名、行号；必须结合实际分发逻辑解释，不能只罗列编号。
5. 覆盖映射表至少包含：目标芯片（固定为所选芯片）、内部模板/分支、源码依据、完整外部触发条件、case_id、验证状态（静态推断/已运行验证/未覆盖/不适用）。
6. 需求决策区分：源码事实、基于代码的推断、AI 自行确定的规则、用户覆盖、TTK 实测结果。不得把自定规则冒充源码事实。
7. 记录 TTK 环节状态、失败项与遗留事项；未执行时明确写“未执行”。
8. 内部标识只允许出现在 `design.md`，不得反向写入 `desc.md`、`golden.py`、`proto.yaml`、`cases.*`。

## 7. 校验

```bash
python3 <skill目录>/scripts/validate_artifacts.py <需求文件夹路径> --chip <A5|A3|A3,A5>

# 第四步已执行（或已判定跳过）时追加 TTK 产物校验
python3 <skill目录>/scripts/validate_artifacts.py <需求文件夹路径> --chip <A5|A3|A3,A5> \
  --with-ttk [--ttk-workdir <TTK_WORKDIR>]
```

`--with-ttk` 的 `TTK_WORKDIR` 默认取 `<需求文件夹>/ttk/`。脚本检查：

- 六个必需文件存在；
- 文件夹名为 snake_case；
- golden 只有一个公开模块级函数且名称等于文件夹名，入口无 `self`；
- desc 一级标题与 `proto.operator.name` 一致；
- desc 第 5 节代码块与 golden 正文逐字符一致；
- proto schema 入口名一致，desc 含 `cann_bench.<ops_snake>(`；
- CSV 列顺序正确；
- YAML 与 CSV 完全一致；
- 用例恰好 20 个、case_id 唯一、无重复签名；
- 每个 `note` 为非空单行自然语言描述，不使用 JSON；
- `design.md` 包含规定的章节标题并标注所选芯片；
- 输出提示中列出无法静态验证的语义、精度和覆盖项。

追加 `--with-ttk` 时，只对 `<TTK_WORKDIR>` 做轻量检查：

- `debug/handoff.json` 可解析，`status` 为 `executed` 或 `skipped`；`skipped` 时需有 `skip_reason`；
- `executed` 时 `cases.csv` 存在且行数为 20，`pass` 只能是 `PASS/FAIL/SKIP`；
- `handoff.json` 中 `FAIL` 用例必须有合法 `attribution`。

TTK 的内部构造、用例命名和细节由子代理保证，脚本不重复校验。
