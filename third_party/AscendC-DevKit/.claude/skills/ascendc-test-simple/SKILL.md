---
name: ascendc-test-simple
description: "AscendC 算子 Simple 模式测试：PTA 直调脚本快速验证精度/性能，适合开发初期和单用例调试。"
---

# AscendC Simple Testing Framework

## 核心原则：生成独立可执行脚本

生成的测试脚本必须是**完全自包含**的，不依赖任何 skill 内部文件。所有精度对比函数、阈值常量、数据生成逻辑都**内联**到生成的脚本中。

这样做的原因：用户可能需要把脚本发给同事、提交到仓库 tests/ 目录、或在没装 skill 的机器上运行。

**参考实现**：生成代码时，先读 [precision_utils.py](references/precision_utils.py) 了解各函数的算法细节，然后把用到的函数直接写进生成的脚本。不要 import 它。

**脚本模板**：参考 [pta_test_template.md](references/pta_test_template.md) 了解脚本整体结构。

## 入口交互流程

当用户触发 Simple 测试时，按以下步骤收集信息：

### Step 1: 算子类别

如果无法从上下文判断算子类别，用 AskUserQuestion 确认：

```yaml
AskUserQuestion:
  question: "该算子属于哪个类别？（决定对比方法和误差度量）"
  header: "算子类别"
  options:
    - label: "浮点计算"
      description: "MatMul, Softmax, LayerNorm 等 — 双标杆 MARE/MERE/RMSE"
    - label: "非计算类"
      description: "Gather, Scatter, Transpose, Cast — 单标杆 Bitwise Match"
    - label: "整数计算"
      description: "INT8/16/32 Add, Mul — 单标杆 Bitwise + AE"
    - label: "量化计算"
      description: "Quant, Dequant, QLinear — AE(整型输出) 或双标杆(浮点输出)"
```

### Step 2: 精度等级（仅浮点计算 / 量化浮点输出）

仅当算子类别为**浮点计算**或**量化计算（浮点输出）**时，且用户没有明确指定精度等级，**必须**提示选择：

```yaml
AskUserQuestion:
  question: "请选择精度看护等级（影响阈值严格程度和数据分布策略）"
  header: "精度等级"
  options:
    - label: "L0 常规"
      description: "MARE<=10, MERE<=2.0, RMSE<=2.0 — 常规算子，宽松标准"
    - label: "L1 重要"
      description: "MARE<=5, MERE<=1.5, RMSE<=1.5 — 多模态/LLM-MOE/推荐系统"
    - label: "L2 关键（推荐）"
      description: "MARE<=2, MERE<=1.2, RMSE<=1.2 — 最严苛标准，关键算子"
```

非计算类和整数计算算子不涉及 L 级别区分，直接跳过此步。

### Step 3: 用例来源与规模

用 AskUserQuestion 询问用例策略：

```yaml
AskUserQuestion:
  question: "你有典型测试用例吗？"
  header: "用例来源"
  options:
    - label: "我提供典型用例"
      description: "输入典型 shape/dtype，skill 在此基础上自动补充边界用例"
    - label: "全自动生成"
      description: "skill 根据算子签名（输入输出数量、dtype）自动生成全部用例"
```

**如果用户选择「我提供典型用例」**，继续收集：

- 输入/输出的名称、dtype、shape（可以多组）
- 是否有特殊值域要求（如仅正数、[0,1] 范围、需要包含 NaN/Inf 测试等）

然后用 AskUserQuestion 选择用例规模：

```yaml
AskUserQuestion:
  question: "需要多少测试用例？（含用户提供的典型用例 + 自动补充的边界用例）"
  header: "用例规模"
  options:
    - label: "quick (5)"
      description: "1-2 典型 shape × 主要 dtype，快速开发验证"
    - label: "standard (15)（推荐）"
      description: "典型 shape + 边界(1元素/非对齐/大tensor) + 多dtype + 多分布"
    - label: "thorough (30)"
      description: "全面覆盖，加入小值域边界、极端shape、所有支持的dtype组合"
```

### 自动补充边界用例策略

基于用户给定的典型 shape，自动补充以下边界：

| 边界类型 | 示例 | 说明 |
|---------|------|------|
| 1 元素 | [1] 或 [1,1,1,1] | 最小 tensor |
| 非对齐 | 将典型 shape 最后一维改为非 32 对齐值 | 测试 tail mask |
| 大 tensor | 将典型 shape 的 batch/seq 维放大 4-8x | 测试多 tile/多核 |
| 退化维度 | 某维设为 1 | 测试 broadcast 场景 |
| 高维 | 增加维度（如 3D→5D） | 仅在算子支持时 |

自动补充的用例数 = 总目标用例数 - 用户提供的典型用例数。

**如果用户选择「全自动生成」**，直接选规模，然后根据算子的输入输出签名自动生成 shape 组合。

### Step 4: 生成测试脚本

收集完信息后：

1. 读 [precision_utils.py](references/precision_utils.py) 了解精度函数的实现
2. 读 [pta_test_template.md](references/pta_test_template.md) 了解脚本应包含哪些部分及其结构
3. 生成**完全自包含**的测试脚本，把用到的精度函数直接内联进脚本
4. 按模板结构填充各部分（精度工具函数、算子实现、精度测试、简易性能测试、main 汇总等）
5. 设置对应精度等级或对比方式

## 精度验证标准

### 算子类别与误差度量

| 算子类别 | 典型场景 | 对比方法 | 误差度量 |
|---------|---------|---------|---------|
| 非计算类（搬移/Cast） | Gather, Scatter, Transpose, Cast | 单标杆 | Bitwise Match |
| 整数计算（INT8/16/32） | Add(int), Mul(int) | 单标杆 | Bitwise Match + AE |
| 量化计算（FLOAT4/8/INT8） | Quant, Dequant, QLinear | 单标杆(整型输出) / 双标杆(浮点输出) | AE + MARE/MERE/RMSE |
| 浮点计算（FLOAT16/32） | MatMul, Softmax, LayerNorm | 双标杆 | MARE/MERE/RMSE |

### 评价指标定义

- **Bitwise Match**：逐比特位对齐，`actual == golden` 逐元素
- **AE** (Absolute Error)：`|actual - golden|`
- **MARE** (Max Absolute Relative Error)：`max(|actual - golden| / |golden + 1e-7|)`
- **MERE** (Mean Absolute Relative Error)：`mean(|actual - golden| / |golden + 1e-7|)`
- **RMSE** (Root Mean Squared Error)：`sqrt(mean((actual - golden)²))`

### 单标杆验证

NPU 输出与单一精度标杆（Golden）直接比较，适用于非计算类、整数计算、量化计算（整型输出）：

```text
Golden (CPU, precision +1) ──── vs ──── NPU (Custom kernel)
```

直接对 AE / Bitwise Match 判定，不做 ratio 计算。

### 双标杆验证

NPU 输出同时与 Golden 和 Bench 比较，通过 ratio 消除算法固有误差，适用于浮点计算和量化计算（浮点输出）：

```text
Golden (CPU, precision +1) ────────┐
                                   ├──> Ratio = NPU_metric / max(Bench_metric, error_thd)
Bench (NPU small ops / CPU) ───────┤
                                   │
NPU (Custom fused kernel) ─────────┘
```

Bench 选项：NPU small ops（默认，在 NPU 上用小算子拼接）或 CPU（NPU 不可用时替代）。

### 正常值域通过标准

定义误差比值（Ratio）：`NPU误差指标 / max(标杆误差指标, err)`，用于量化 NPU 实现相对于标杆的误差水平。

不同浮点格式的 err 设定如下：
- FLOAT16: err = 2⁻¹¹
- BFLOAT16: err = 2⁻⁸
- FLOAT32: err = 2⁻¹⁴

### 精度分级（L0/L1/L2）

| 等级 | MARE ratio | MERE ratio | RMSE ratio | 适用场景 |
|------|-----------|-----------|-----------|---------|
| L0 | <=10 | <=2.0 | <=2.0 | 常规算子 |
| L1 | <=5 | <=1.5 | <=1.5 | 重要算子（多模态/LLM-MOE/推荐系统） |
| L2 | <=2 | <=1.2 | <=1.2 | 关键算子，最严苛标准 |

### 各类算子通过标准

- **非计算类**：单标杆，所有元素 Bitwise Match
- **整数计算**：单标杆，Bitwise Match 或 AE=0（所有元素）
- **量化计算**：整型输出 AE<=1（所有元素）；浮点输出参照浮点计算标准
- **浮点计算**：双标杆，按 L0/L1/L2 等级的 ratio 阈值判定

### 小值域通过标准

小值域中 `|golden| <= SmallValueThreshold` 的元素单独判定，不参与 MARE/MERE/RMSE 计算。

小值域误差判定：若 `|actual - golden| > SmallValueErrorThreshold`，则该元素计入 ErrorCount。

| dtype | SmallValueThreshold | SmallValueErrorThreshold |
|-------|-------------------|------------------------|
| FLOAT16 | 2⁻¹¹ | 2⁻¹⁶ |
| BFLOAT16 | 2⁻⁸ | 2⁻¹⁶ |
| FLOAT32 | 2⁻¹⁴ | 2⁻³⁰ |
| HIFLOAT32 | 2⁻¹² | 2⁻²⁸ |
| FLOAT8 E4M3 | 2⁻⁴ | 2⁻⁶ |
| FLOAT8 E5M2 | 2⁻³ | 2⁻⁵ |

小值域通过标准：`ErrorCount_NPU / max(ErrorCount_bench, 1) <= 2`

### 复检机制（Bootstrap 统计复检）

当单用例不通过时，可触发 Bootstrap 统计复检：

- **方法**：更换随机种子执行 N 次（推荐 1000），收集每次的误差 ratio，计算中位数的 95% 置信区间
- **前置规则**：N < 200 直接不通过
- **判定**：CI_lower <= 1 → 通过（即误差中位数的 95% 下界不超过 1）
- **置信区间**：CI_lower = Q_0.025, CI_upper = Q_0.975（排序后取分位数）

## 内联函数参考

生成脚本时，从 [precision_utils.py](references/precision_utils.py) 中选取需要的函数内联。按算子类别，通常需要内联的函数组合：

### 浮点计算算子（最常见）

必须内联：
- `get_level_thresholds` — L0/L1/L2 阈值
- `get_small_value_thresh` / `get_small_value_error_thresh` — 小值域阈值
- `get_error_thd` — ratio 分母保护阈值
- `get_golden_dtype` — 精度 +1 dtype
- `calc_metrics_with_mask` — MARE/MERE/RMSE 计算
- `calc_small_value_error_count` — 小值域误差计数
- `compare_with_dual_benchmark` — 双标杆对比主函数
- `generate_tensor_with_distribution` / `get_distribution_type` — 数据生成
- `print_failure_details` — 失败调试输出

可选内联：
- `recheck_with_bootstrap` — 仅在需要复检时

### 非计算类算子

必须内联：`compare_bitwise`

### 整数计算算子

必须内联：`compare_integer`

### 量化计算算子

必须内联：`compare_quantized`（整型输出路径），或浮点计算的全套（浮点输出路径）
