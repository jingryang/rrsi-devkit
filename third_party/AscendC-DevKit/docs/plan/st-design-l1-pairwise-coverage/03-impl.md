# L4 实施方案：st-design L1「两两组合覆盖」修复

> 对应 L1：`01-problems.md`（P1/P2/P3/P4）；L3：`02-analysis.md`（方案 A×4，冻结）。
> 全部改动在 `.claude/skills/ascendc-st-design/scripts/generate_test_cases.py` + UT。

## 改动清单

| # | 位置 | 改动 | 覆盖问题 |
|---|------|------|----------|
| 1 | `generate_test_cases.py` 模块级 | 新增 `_DISCRETE_SUFFIXES`/`_VALUE_SUFFIX` 常量 + `_enum_param_names(param_def)`（读 `03_参数定义.yaml` 的 `is_enum: true`） | P1 |
| 2 | 同上 | 新增 `select_pairwise_factors(df, param_def)`：结构性离散（后缀 ∪ `is_enum` 的 `.value`）且池中 `nunique>1` | P1 |
| 3 | `generate_pairwise_combinations` | 重写：签名 `(df, discrete_factors)`，扫描池行枚举**实际出现**的两两组合（构造性可行；删除 `cubeMathType.value` 硬编码与笛卡尔积） | P1/P2 |
| 4 | `select_cases_L1` | 签名改 `(df, pairwise_combinations, discrete_factors, verbose, sample_size)`；删除内部重复的离散性判据，`factor_names = sorted(discrete_factors)` | P1/§1.15 |
| 5 | `generate_L1_report` | 签名改 `(pairwise_combinations, coverage_info, discrete_factors, target_count, final_count)`；`factor_statistics` 用 `discrete_factors`；summary 增 `pairwise_factor_count`/`pairwise_factor_value_count` | P3 |
| 6 | `_generate_l0_l1_cases` | 增 `param_def` 形参；L1 分支先 `select_pairwise_factors` → `generate_pairwise_combinations` → `select_cases_L1` | P1/P2 |
| 7 | `create_csv` | 调用处传 `params.param_def` | P1 |
| 8 | `_save_case_results` | 删除 L1 专用「仅 CSV」分支，**统一**调 `save_results`（L0/L1 走同一存盘通路，报告落盘） | P4/§2.5 |
| 9 | `tests/ut/skills/test_st_design_scripts.py` | 新增 6 例（`TestSelectPairwiseFactors` / `TestFeasiblePairwiseCombinations` / `TestL1ReportAndSave`） | 验证 |

## 关键不变式

- **可行性来自权威源**：目标域的两两组合全部取自约束已满足的因子值池，L1 层不重推约束可行性。
- **同源一致**：`select_pairwise_factors`（因子集合）与 `generate_pairwise_combinations`（目标域）
  都基于同一 `df`；覆盖率的分子分母同源，100% 可达且诚实。
- **枚举判据 = 显式声明**：`is_enum` 是 `03_参数定义.yaml` 的权威字段，与因子生成侧
  （`generate_test_factors.py` 仅在 `is_enum` 时产 `.value`）同源，无参数名假设。

## 验证

### UT
`PYTHONPATH=src python3 -m pytest tests/ut/skills/test_st_design_scripts.py --quick -q` → **18 passed**。
定向回归 `test_st_design_scripts.py` + `test_merge_test_cases.py` + `test_csv_to_testcases.py` +
`tests/st/test_test_design_e2e.py` → **63 passed**。

### 真实管线回放（该 run 的 `design/03,04,05,06`）

| 指标 | 修复前 | 修复后 |
|---|---|---|
| L1 离散因子数 | 3（仅 x/grid/y.dtype） | **6**（+ interpolation_mode/padding_mode/align_corners 枚举） |
| 两两组合目标 | 12（含 6 个约束不可能） | **64（全部可行）** |
| 两两覆盖率 | 6/12 = **50.00%** | **64/64 = 100.00%** |
| 贪心实选条数 | 2 | **7**（最小可行两两覆盖集） |
| `..._L1_coverage_report.yaml` | **未落盘** | **落盘**（selected 7 / padded 58 / final 65） |
| L1 CSV 条数 / 内容唯一 | 65 / 65 | 65 / 65 |
| 合并 CSV + 下游 `parse_testcase_csv` | 99 / 99 通过 | 99 / 99 通过 |

> 说明：上表为**离线重放**该 run 的 `design/03,04,05,06` 输入所得（未跑 agent）。
> 随后已单 stage 真实重跑刷新该 run 产物，见下节。

## 真实 run 产物刷新（2026-09-24）

`ascendc-devkit stage run -n ascendc-st-design --from-run 20260923-120650-2d93d3 --non-interactive`
单 stage 真实重跑 287s（agent 重做 step 3-9），产物已刷新（旧产物备份
`/tmp/opencode/test_design_before_l1fix_20260924-113149/`）。该 run 的
`..._L1_coverage_report.yaml` **首次落盘**：

```yaml
summary:
  pairwise_factor_count: 5
  pairwise_factor_value_count: 11
  total_pairwise_combinations: 42
  covered_pairwise_combinations: 42
  uncovered_pairwise_combinations: 0
  coverage_rate: 100.00%
  selected_case_count: 6
  padded_case_count: 60
  final_case_count: 66
factor_statistics:  # 只有插值/填充两个枚举属性入目标，不再只有 3 个 dtype
  grid.dtype / x.dtype / y.dtype / interpolation_mode.value / padding_mode.value
```

| 指标（该 run 产物） | 前 | 后 |
|---|---|---|
| `..._L1_coverage_report.yaml` | 未落盘 | **落盘**（42/42=100%，selected 6 / padded 60 / final 66） |
| L1 离散因子 | 3（仅 x/grid/y.dtype） | **5**（+interpolation_mode.value/padding_mode.value） |
| 两两组合目标 | 12（含约束不可能） | **42（全可行）** |
| 覆盖率 | 6/12 = 50% | **42/42 = 100%** |
| L0 / L1 / L2 CSV | 34 / 65 / 6 | 36 / 66 / 6 |
| 合并 CSV + 下游 `parse_testcase_csv` | 99 / 99 通过 | 102 / 102 通过 |

> **设计阶段方差（诚实记录）**：本次 agent 重生成 `03_参数定义.yaml` 时把 `align_corners`
> 声明为 `is_enum: false`（上一轮为 `is_enum: true`），故本算子 L1 离散因子为 5 个；
> 修复后的判据严格遵循该显式声明（§1.10），不因参数名/类型自行猜测——若需把 bool 属性
> 固定纳入两两，属「设计阶段 `is_enum` 声明质量」问题，另立，非本脚本职责。

## 不做

- 不把 `.value_range`/`.shape` 纳入两两（连续/派生，性能取舍）。
- 不改 `--sample-size` 大池采样语义（已知限制见 L3 §6）。
- 不处理空 tensor 派生脚本列名失配（另一产权线，即「点 2」）。

