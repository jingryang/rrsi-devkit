---
name: ascendc-st-design
description: Ascend C 算子系统测试（ST）设计技能。基于 aclnn 接口文档，完成算子参数定义、测试因子提取、约束关系分析、测试用例生成（L0/L1/L2）的完整流程。当需要以下任务时使用此技能：设计算子测试用例、生成ST用例。
---

# Ascend C 算子测试设计

本技能提供 Ascend C 算子测试设计的完整工作流程，并输出结构化用例数据支撑算子功能和精度验证。

## 核心工作流程

### 1. 输入文件校准

从以下文档获取算子接口信息（**CWD 相对路径**，由调用方提供或按用户指定的文件路径）：
- 需求文档：`./REQUIREMENTS.md`（或用户指定的需求文档路径）
- ACLNN 接口文档：`./aclnn{OperatorName}.md`（或用户指定的接口文档路径）

如果调用方已提供结构化的参数定义（如 DevKit 编排已生成 `./design/03_参数定义.yaml`），
可跳过 step 2 直接从 step 3 开始。


### 1.1 输出路径规范

**所有测试设计结果统一存放到当前工作目录（CWD）下**，目录约定：

```
./design/                       # 测试设计中间产物
├── 03_参数定义.yaml
├── 04_测试因子.yaml
├── 05_约束定义.yaml
├── 06_求解配置.yaml
└── 07_因子值.csv
./testcases/                    # 最终测试用例（下游直接消费）
├── {operator_name}_L0_test_cases.csv
├── {operator_name}_L0_coverage_report.yaml
├── {operator_name}_L1_test_cases.csv
├── {operator_name}_L1_coverage_report.yaml
└── {operator_name}_L2_test_cases.csv
./合并_测试用例.csv              # 合并后的下游 13 列 CSV（step 9）
```

**路径变量**：
- `DESIGN_DIR`：测试设计中间产物目录，`./design/`
- `TESTCASE_DIR`：最终测试用例目录，`./testcases/`

> **脚本路径约定**：下文脚本调用中的 `<skill_dir>` 表示本 skill 所在的目录
> （TUI 单跑时即 `.claude/skills/ascendc-st-design/` 所在位置；若已取出为独立
> 目录则为该目录）。所有输入输出文件一律用 CWD 相对路径，不写绝对路径。

### 2. 算子参数定义

根据参数类型定义参数规范。支持 **3 大类 6 种**参数类型：

| 类别 | type 值 | 值配置字段 |
| ---- | ------- | ---------- |
| Tensor 类 | aclTensor, aclTensorList | dtype_with_ranges |
| Array 类 | aclIntArray, aclFloatArray, aclBoolArray, aclScalarList | dtype_with_ranges |
| Scalar 类 | aclScalar, 18种标量类型（int4_t~string） | dtype_with_values |

**详细规范和模板**：参考 [parameter-definition.md](references/parameter-definition.md)

**关键要点**：
- **aclnn_name 必填**：在参数定义文件的顶层添加 `aclnn_name` 字段，值为算子的 aclnn 接口名称（从接口文档名称获取，如 `aclnnGridSampler2DBackward.md` → `aclnnGridSampler2DBackward`）
- 为每个参数定义 `name`、`type`、`required`、`io_type` 属性
- **数据类型必须完整**：从原始资料的数据类型列中完整复制所有类型，不允许遗漏
- `io_type` 字段：标识参数的输入输出类型
  - `input`：输入参数（需准备测试数据）
  - `output`：输出参数（无需定义`value_range`和`special_range/special_value`）
- Tensor 类需定义 `format`、`dimensions`；TensorList 额外需定义 `length_ranges`
- `dimensions` 取值范围：通用最小为1、最大为8，需结合算子接口文档中的维度约束（如"不超过N维"）调整。例如接口文档写"不超过8维"时取 `[1, 2, 3, 4, 5, 6, 7, 8]`；写"3维"时取 `[3]`。
- Array 类需定义 `length_ranges`
- Scalar 类需定义 `is_enum`、`dtype_with_values`
- 明确 `value_range` 和 `special_range/special_value`
- 无需定义workspaceSize和executor参数

### 2.1 value_range 定义规范

**必须覆盖的取值范围**：
1. **全量默认值**：按照 `references/parameter-definition.md` 中的默认值定义
2. **算子特定值**：根据算子功能识别的特殊值

**定义步骤**：
1. 复制默认值模板（从 parameter-definition.md）
2. 根据算子功能删除不适用的范围（如归一化操作删除负值范围）
3. 添加算子特定的约束值

**float16 全量默认值示例**：参见 [parameter-definition.md](references/parameter-definition.md) 中的「默认 value_range 定义」表。

**边界必须是可执行数值**：`value_range` 候选的每个边界只能是数值，或 `inf`/`-inf`/`nan`（及带符号零 `+0`/`-0`）字面量。依赖其他参数 shape 的值域（如"类别下标上界 = 类别维大小减一"）**禁止写成符号候选**——生成链无法在渲染期实例化符号，流入用例会让消费端回退默认区间、产出非法输入。表达方式是约束定义中的形状来源 `calculate` 约束：

```yaml
- id: "RANGE-<param>"
  type: calculate
  sources: [<提供维度语义的参数>.shape]
  target: "<param>.value_range"
  expression: "[0, sources[0][1] - 1]"
```

`expression` 必须算出数值 `[lo, hi]`（`sources` 在作用域内可直接引用）。若值域与 shape 无关，直接把候选写成数值即可，无需约束。

### 3. 使用脚本自动提取测试因子

**推荐方式**：使用 `generate_test_factors.py` 脚本自动提取

```bash
python <skill_dir>/scripts/generate_test_factors.py \
    ./design/03_参数定义.yaml \
    ./design/04_测试因子.yaml
```

**脚本功能**：自动识别参数类型，提取所有测试因子（存在性、格式、维度、数据类型、取值范围、特殊值等），生成规范的 YAML 格式输出。

### 4. 参数依赖关系分析

解析输入资料，理解算子的数学公式及计算逻辑，提取 GetWorkspaceSize 接口中950系列产品支持的参数、参数取值范围和参数依赖关系。

**详细规范**：参考 [dependency-yaml-spec.md](references/dependency-yaml-spec.md)

**约束类型速查**：

| 类型 | 语义 | 典型场景 |
|------|------|----------|
| `calculate` | 计算约束 | 类型等值、形状计算、自引用修改、多shape广播结果(`get_broadcast_result`) |
| `broadcast_dim` | 指定维度广播 | 单维度广播兼容性 |
| `broadcast_shape` | 张量广播 | 完整形状广播（单向/双向） |
| `conditional` | 条件约束 | if-then-else 分支 |
| `match` | 匹配约束（双向） | 维度/属性双向匹配 |
| `existential` | 存在性约束 | 可选参数联动 |
| `convertible` | 可转换约束 | 类型兼容性检查 |
| `inferable_filter` | 链式依赖约束 | 多 Tensor 类型互推导 |
| `inferable` | 可推导约束 | 类型推导检查 |

**约束类型完整示例**：参考 [constraint-examples.md](references/constraint-examples.md)

#### 4.1 约束分析维度（按优先级）

在识别因子依赖关系时，按以下优先级进行分析：

1. **数据类型依赖**：类型推导链、类型等价约束、类型可转换性、类型互斥规则、精度层级关系
2. **形状依赖**：维度数约束、维度大小计算、Broadcast方向性和兼容性、指定维度值匹配
3. **数值依赖**：标量取值范围、枚举值定义域、特殊数值语义、数值精度影响
4. **存在性依赖**：可选参数联动、条件参数约束

#### 4.2 约束定义文件规范

```yaml
# 元信息
metadata:
  operator: "{算子名}"
  version: "1.0"
  description: "{算子名}算子约束关系定义"

# 因子节点定义
factors:
  {param}.{attribute}: {type: {type}, param: {param}, io_type: {io_type}}

# 约束定义
constraints:
  - id: "C-XXX-001"
    type: {constraint_type}
    # ...
```

因子节点定义和各约束类型的完整 YAML 示例见 [constraint-examples.md](references/constraint-examples.md)。

**约束设计原则**：
- `calculate` 是通用计算约束，等值场景使用 `expression: "sources[0]"`
- `match` 是**双向约束**，`calculate` 是**单向计算**，语义不同不应合并
- `broadcast_shape` **不支持** `source_shape_expr` 字段；如需表达"广播到派生形状"，使用两步约束模式（见 [constraint-examples.md §4](references/constraint-examples.md)）
- 固定取值范围已在 `04_测试因子.yaml` 中定义，无需添加约束
- `sources` **不可为空** `[]`；需要自引用时可 `sources` 包含 `target` 自身

#### 4.3 检查清单

- 05_约束定义.yaml必须包含metadata、factors、constraints节点
- constraints节点中的sources不为[]；即：固定取值范围无需定义约束
- **Array 类参数的元素级约束**：检查 aclIntArray/aclFloatArray/aclBoolArray/aclScalarList 的各元素是否有独立取值要求（如某些位置必须固定值、某些位置取值范围不同），如有则需在隐式约束之后新增 calculate 约束，通过 `sources: ["param.value"]` + `target: "param.value"` + 指定索引覆盖的方式实现
- **逐条核对原始文档约束**：将原始算子文档中的每条参数说明/使用说明/约束说明逐一对照，确认是否都有对应的约束定义或已在测试因子中覆盖

### 5. 生成通用约束

**推荐方式**：使用 `generate_implicit_constraints.py` 脚本自动生成

```bash
python <skill_dir>/scripts/generate_implicit_constraints.py \
    ./design/04_测试因子.yaml \
    ./design/05_约束定义.yaml \
    --verbose
```

脚本自动识别需要生成隐式依赖的因子，生成三类通用隐式约束，避免重复约束（幂等性保证），并自动备份原有约束文件。

**通用依赖规则**：

1. **Tensor / TensorList 输入**：`{param}.shape` 依赖于 `{param}.dimensions`
2. **所有输入**：`{param}.value_range` 依赖于 `{param}.dtype`
3. **TensorList / Array 类**：`{param}.length` 依赖于 `{param}.length_ranges`
4. **TensorList**：`{param}.shape_list` 依赖于 `{param}.length` 和 `{param}.dimensions`
5. **Array 类**：`{param}.value` 依赖于 `{param}.length` 和 `{param}.value_range`
6. **非 Tensor 非枚举类型**：`{param}.value` 依赖于 `{param}.value_range`

### 6. 构建测试因子依赖图

**推荐方式**：使用 `generate_solver_config.py` 脚本自动生成

```bash
python <skill_dir>/scripts/generate_solver_config.py \
    ./design/05_约束定义.yaml \
    ./design/06_求解配置.yaml
```

脚本解析约束定义，构建因子依赖图，拓扑排序确定求解层级，识别锚点因子（入度为0）。

**输出示例**：
```yaml
solver:
  strategy: topological
  anchors:
    - batch1.dtype
    - batch1.shape
  derivation_order:
    level_0: [batch1.dtype, batch1.shape, self.dtype, ...]
    level_1: [alpha.dtype, batch2.shape, beta.dtype, out.dtype]
    level_2: [out.shape]
```

### 7. 约束求解与测试因子值生成

**推荐方式**：使用 `generate_factor_values.py` 脚本自动生成满足约束的测试因子值

```bash
python <skill_dir>/scripts/generate_factor_values.py \
    ./design/06_求解配置.yaml \
    ./design/05_约束定义.yaml \
    ./design/04_测试因子.yaml \
    ./design/07_因子值.csv \
    --max-cases 2000
```

**约束求解流程**：
1. 加载求解配置、约束定义和测试因子
2. 识别锚点因子（Level 0），独立随机采样
3. 按拓扑顺序逐层推导
4. 验证每个测试用例是否满足所有约束
5. 输出满足约束的测试因子值到 CSV 文件

**可选参数**：`--max-cases N`（最大用例数，默认10000）、`--seed N`（随机数种子）、`--verbose`

### 8. 测试用例生成（L0/L1/L2）

**推荐方式**：使用统一的 `generate_test_cases.py` 脚本

> **注意**：由于 L0 和 L1 和 L2 算法复杂度较高，建议分三步执行，并设置 **5分钟超时**。

```bash
# 步骤1: 生成 L0 用例（单因子覆盖，≤200条）
python <skill_dir>/scripts/generate_test_cases.py \
    ./design/03_参数定义.yaml \
    ./design/04_测试因子.yaml \
    ./design/07_因子值.csv \
    ./testcases/ \
    --level L0 \
    --verbose

# 步骤2: 生成 L1 用例（两两组合覆盖，≤100条）
python <skill_dir>/scripts/generate_test_cases.py \
    ./design/03_参数定义.yaml \
    ./design/04_测试因子.yaml \
    ./design/07_因子值.csv \
    ./testcases/ \
    --level L1 \
    --target-count 100 \
    --seed 42 \
    --verbose

# 步骤3: 生成 L2 用例（异常用例，每个异常场景一条用例）
python <skill_dir>/scripts/generate_test_cases.py \
    ./design/03_参数定义.yaml \
    ./design/04_测试因子.yaml \
    ./design/07_因子值.csv \
    ./testcases/ \
    --level L2 \
    --constraints-file ./design/05_约束定义.yaml \
    --verbose
```

**超时设置**：在调用 Bash 工具时设置 `timeout=300000`（5分钟）

**用例级别说明**：

| 级别 | 定义 | 覆盖目标 | 用例数 |
| ---- | ---- | -------- | ------ |
| L0 | 门槛用例 | 核心功能直通 | <=200 |
| L1 | 功能/精度/性能用例 | 参数BC组合测试，正常+典型边界，DFX基准测试 | ≤100 |
| L2 | 异常用例 | dtype、dim等异常 | <=20 |

**L1 可选参数**：`--target-count N`（目标用例数量，默认100）、`--seed N`（随机数种子）

**输出文件**：`{operator_name}_L0_coverage_report.yaml`、`{operator_name}_L0_test_cases.csv`（含空tensor用例）、`{operator_name}_L1_coverage_report.yaml`、`{operator_name}_L1_test_cases.csv`（含空tensor用例）、`{operator_name}_L2_test_cases.csv`

> **空tensor用例**：L0和L1用例均自动生成空tensor用例（从正常用例派生），确保算子空tensor场景覆盖。详见 [empty-tensor-guide.md](references/empty-tensor-guide.md)。

### 9. 合并测试用例 CSV

使用 `merge_test_cases.py` 脚本将 L0/L1/L2 三级 CSV 合并为下游 13 列格式：

```bash
python <skill_dir>/scripts/merge_test_cases.py \
    --op-name {operator_name} \
    --aclnn-name {aclnn_name} \
    --testcase-dir ./testcases/ \
    --output ./合并_测试用例.csv
```

**参数说明**：
- `--op-name` —— 算子名（对应目标 CSV 的 `op_name` 列）
- `--aclnn-name` —— ACLNN 接口名（对应目标 CSV 的 `stc_op_name` 列）
- `--testcase-dir` —— L0/L1/L2 CSV 所在目录（脚本自动按文件名中的 `l0`/`l1`/`l2` 匹配）
- `--default-precision` —— 绝对精度阈值（默认 `1e-05`）
- `--default-format` —— 输入/输出格式（默认 `ND`）
- `--output` —— 输出文件名（默认 `合并_测试用例.csv`）

**输出列的格式契约**（下游 `csv_to_testcases.py` 用 `ast.literal_eval` 解析）：

| 列 | 格式 | 示例 |
|---|---|---|
| `stc_input_dtypes` | Python tuple repr | `('float32',)` 或 `('float16','float16',)` |
| `stc_inputs` | Python list-of-tuples repr | `[(5398427)]` 或 `[(1,76),(6703005,67)]` |
| `stc_input_formats` | Python tuple repr | `('ND',)` 或 `('ND','ND',)` |
| `output_dtypes` | Python tuple repr | 同上 |
| `stc_outputs` | Python list repr | `[()]` 或 `[(2,3)]` |
| `output_formats` | Python tuple repr | 同上 |
| `other_compilation_params` | JSON 字符串 | `{"scalar": 2.0}` |
| `input_data_ranges` | Python repr | `(((-100,100,),),)` |

> **禁止**手写 merge CSV 脚本或手动拼接列值。`stc_input_dtypes` 等列**必须**是合法 Python tuple/list repr，裸值 `float32` 会被下游 `ast.literal_eval` 拒绝。

> **缺省可选输入必须留位置占位（`None`）**：`stc_inputs` / `stc_input_dtypes` /
> `stc_input_formats` / `input_data_ranges` 是**按 proto 输入顺序对齐的等长数组**。
> 当某个可选输入在某条用例中缺省时，该位置必须写 Python `None`（裸 `None`，非字符串
> `'None'`），**不得压缩掉该位置**——下游 harness 按位置逐位绑定 golden/kernel，压缩会让
> 其后所有输入上移错位。这与 cann-bench `cases.csv` 用 `null` 占位可选输入是同一约定。
> 例：`expanded_permuted_rows, expanded_src_to_dst_row, skip1, skip2, bias, scales,
> expert_for_source_row` 中 skip2 缺省时 →
> `stc_inputs = [(8192,512),(8192),(2048,512),None,(16,512),(2048,4),(2048,4)]`。
> 该占位由 `generate_test_cases.py` 生成、`merge_test_cases.py` 透传，无需手工处理。

### 10. 测试设计结果总结

在 `./` 目录总结算子测试设计过程与结果：

- 算子参数定义
- 提取测试因子
- 参数依赖关系分析
- 生成隐式约束
- 构建测试因子依赖图
- 约束求解与测试因子值生成
- 测试用例生成（L0/L1/L2）

## 参考文件

### 技能文档

- **[parameter-definition.md](references/parameter-definition.md)** - 参数定义规范、模板和 value_range 默认值表
- **[dependency-yaml-spec.md](references/dependency-yaml-spec.md)** - 依赖关系约束表达模型完整规范
- **[constraint-examples.md](references/constraint-examples.md)** - 约束类型详细示例和完整约束文件示例
- **[standards.md](references/standards.md)** - 算子验收标准和用例级别规范
- **[empty-tensor-guide.md](references/empty-tensor-guide.md)** - 空tensor用例生成指南（自动派生）

### 自动化工具

- **[scripts/generate_test_factors.py](scripts/generate_test_factors.py)** - 测试因子提取脚本
- **[scripts/generate_implicit_constraints.py](scripts/generate_implicit_constraints.py)** - 隐式约束生成脚本
- **[scripts/generate_solver_config.py](scripts/generate_solver_config.py)** - 求解配置生成脚本
- **[scripts/generate_factor_values.py](scripts/generate_factor_values.py)** - 自动生成满足约束的测试因子值脚本
- **[scripts/generate_test_cases.py](scripts/generate_test_cases.py)** - 测试用例生成脚本（支持L0/L1/L2，L0和L1自动生成空tensor用例）
- **[scripts/merge_test_cases.py](scripts/merge_test_cases.py)** - 合并 L0/L1/L2 CSV 为下游 13 列格式（自动匹配文件名，输出 `合并_测试用例.csv`）
- **[scripts/generate_empty_tensor_cases_derive.py](scripts/generate_empty_tensor_cases_derive.py)** - 空tensor用例派生脚本（独立调用）