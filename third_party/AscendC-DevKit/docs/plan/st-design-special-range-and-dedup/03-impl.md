# L4 实施方案：st-design 特殊取值域覆盖 + 泛化去重 + 覆盖报告诚实化

> 依据 L3 `02-analysis.md` 冻结的决策。改动全部落在 skill 脚本（§2.1 自闭环）。

## 1. 改动清单

### 1.1 `generate_factor_values.py`

| 位置 | 改动 |
|---|---|
| 新增 `_declared_value_ranges()` | 从 `04_测试因子.yaml` 收集 `{param}.value_range_{dtype}` 声明域 → `{(param, dtype): [range...]}` |
| 新增 `complete_value_range_coverage(cases)` | 对每个 (param, dtype)，克隆同 dtype 基用例并覆盖 `value_range`，补回缺席的声明 range（叶子因子，不破坏其它约束） |
| 新增 `_structure_key(case)` + 轮转（P5） | 克隆基不再恒取 `same_dtype[0]`：按「排除全部 `*.value_range` 的结构键」去重得到不同结构基，补缺失 range 时**轮转**选基，使 range 覆盖分摊到多种形状/属性（避免结构过集中） |
| `generate_all_cases()` | 删除 `while len < max_cases: 重复拼接` 循环；改为 `base → complete_value_range_coverage → [:max_cases]` |

### 1.2 `generate_test_cases.py`

| 位置 | 改动 |
|---|---|
| `pad_cases(..., df=None)` | 候选 = 未选中行；按 `case_content_key` 去重补齐；`seed` 控 shuffle；候选耗尽即停（允许 < target） |
| 新增 `case_content_key(row)` | 用例内容键（忽略索引/名字，仅因子取值） |
| `complete_case(..., df=None)` | 透传 df；verbose 打印实际补齐数 |
| `_generate_l0_l1_cases` | 调 `complete_case(..., df)`；`generate_L1_report(..., final_count=len(selected))` |
| `generate_L1_report(..., final_count=None)` | `padded_case_count` 用实际补齐数；新增 `final_case_count` |
| `extract_all_factor_values` | 目标域 = 声明值 ∪ 实际值；只保留物化列（df.columns）；`_declared_factor_values` + `_normalize_declared_value`（list→str(list)，bool/int/str 原样） |

## 2. 顺序

1. `generate_factor_values.py`（池的覆盖与去重）——先做，L1/L0 才有材料。
2. `generate_test_cases.py`（选择/补齐/报告）——依赖 1 的池。
3. UT 与真实管线回放。

## 3. 验证

### 3.1 UT

`tests/ut/skills/test_st_design_scripts.py`（12 例）：
- P2：`pad_cases` 跳重复内容 / 上限 / 无 df 时 no-op。
- P3：声明值不在 CSV 也进目标；未物化因子列被剔除；bool/int 原样。
- P1：缺失声明 range 被补全 / 克隆保其它因子 / 无基用例的 dtype 跳过 / 已覆盖不变。
- P4：`generate_all_cases` 不重复凑数。

### 3.2 真实管线回放（run `20260923-120650-529af0` 的 design 输入）

```
python generate_factor_values.py design/06 design/05 design/04 design/07 --max-cases 2000
python generate_test_cases.py design/03 design/04 design/07 <out>/ --level L0 --verbose
python generate_test_cases.py design/03 design/04 design/07 <out>/ --level L1 --target-count 100 --seed 42 --verbose
python merge_test_cases.py --op-name GridSampler3D --aclnn-name aclnnGridSampler3D --testcase-dir <out>/ --output 合并_测试用例.csv
```

实测结果：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| `07_因子值.csv` 行数 / 不同内容 | 2000 / 24 | 62 / 62 |
| x.value_range 声明覆盖（fp16/fp32） | 16/27、部分 | 27/27、27/27（含 inf/-inf/nan） |
| grid.value_range 声明覆盖 | 9/11 | 11/11 |
| L0 条数 / 覆盖 | 16 / 50-50（自证） | 34 / 69-69（含声明域） |
| L0 含 inf/nan 用例 | 0 | 3 |
| L1 条数 / 唯一内容 | 100 / 2 | 62 / 62 |
| 合并 CSV 行数 / 唯一内容 | 116 / ~16 | 96 / 62 |
| 下游 `parse_testcase_csv` | 通过 | 96/96 通过 |

### 3.3 回归

- `tests/ut/skills`（除 `test_precision_debug_selfcontained.py` 因本机缺 `anyio` 失败，env 前置问题）通过。
- `tests/st/test_test_design_e2e.py` + `tests/ut/adapters/test_csv_to_testcases.py` + `tests/ut/skills/test_merge_test_cases.py` 45 passed。
- 全量 UT 本机受 `anyio` 缺失影响（大量 collection error / failure 与本改动无关，改前即存在，§3.7）。

### 3.4 P5（结构轮转）验证

UT 新增 2 例（`test_structure_key_ignores_value_range` / `test_missing_ranges_rotate_across_structures`），
`tests/ut/skills/test_st_design_scripts.py` 共 **20 passed**。

真实单 stage 重跑该 run（`--from-run 20260923-120650-2d93d3`）产物前后对比：

| 指标 | 轮转前 | 轮转后 |
|---|---|---|
| L0 行数 | 36 | 35 |
| L0 结构唯一数（shape/dtype/attr） | 10 | **11** |
| L0 单结构最大重复数 | **21** | **5** |
| L0 覆盖 | 72/72（x.vr 33、grid.vr 11） | 72/72（x.vr 33、grid.vr 11） |
| L1 行数 / 内容唯一 | 66 / 66 | 69 / 68（见 P6） |
| 合并 CSV + 下游 `parse_testcase_csv` | 102 / 102 | 104 / 104 |

> 覆盖保证（72/72、声明域 33/11）在轮转后不变——轮转只改克隆基的选取，不动覆盖不变式。

## 4. 不做（记录）

- `grid` inf/nan out-of-domain：保持设计阶段决策（§1.13）。
- L1 两两组合纳入 `.value_range`：保持既有性能取舍（§1.14）。
- 跨 L0/L1 内容去重：既有结构，留观。
- L1 P4 空 tensor 派生脚本列名失配：另立（L1 P4 已留证据）。
- P6（池级去重 vs TTK 表示层不一致致 1 条表示层重复）：本工作不处理，L1 已留证据；属「表示层去重」另一产权线。

