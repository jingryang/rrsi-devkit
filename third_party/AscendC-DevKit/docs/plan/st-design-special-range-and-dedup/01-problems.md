# L1 问题记录：ascendc-st-design 特殊取值域漏生成 + 泛化用例重复 + 覆盖报告自证

> 事实快照，不提方案、不排顺序、不写决策。
> 观测来源：run `20260923-120650-529af0/20260923-120650-2d93d3/artifacts/test_design/`
> （算子实例仅作证据，机理对所有算子通用——问题在 skill 脚本层）。

## P1 — 声明的特殊取值域（zero/extreme/negative/with_inf/with_nan）未被生成，L0 门槛用例无从覆盖

**现象**
- `testcases/aclnnGridSampler3D_l0_test_cases.csv`（16 条门槛用例）中，`input_data_ranges` 的 x 取值区间为
  `{(-0.x,..),(0,0.001),(-100,100),(-1,1),(-10,-2),(-6.1e-5,..),(-0,-0),(65504,65504),(-65504,65504),(1,2),(10,1000),(0.01,1),(-0.001,0),(-0.0078125,0.0078125),(-3.05e-5,3.05e-5),(2,10)}`
  —— 含 zero、signed-zero、次正规、±65504、negative，但 **不含 inf/-inf/nan**。
- `design/07_因子值.csv` 2000 行中 `x.value_range` 仅 **16 个不同值**；而 `design/04_测试因子.yaml`
  声明 `x.value_range_float16` 与 `x.value_range_float32` 各 27 个取值（含 `inf`/`-inf`/`nan`）。
  `grid.value_range` 实际 9 个 vs 声明各 11 个。
- 合并产物 `合并_测试用例.csv`（116 行）中 inf/nan 相关用例数 = 0。

**根因（现象级，代码事实）**
1. `generate_factor_values.py::generate_all_cases` 用
   `while len(all_cases) < max_cases: all_cases += generate_complete_cases(anchor_combinations)`
   把**同一批 anchor 组合**反复拼接凑到 `--max-cases`（本算子 anchor 组合仅 24 组 → 2000 行实为 24 条内容 × ~84 重复）。
2. `generate_factor_values.py::solve_constraint_range` 的 `derive_value_range_from_dtype` 分支对
   每个组合 `random.choice(value_ranges)` 取 **一个** range，取值由 context hash 种子决定——声明列表里未被抽中的
   range（含 inf/-inf/nan）在结果中**静默消失**；拼接重复行也不会补上。

**可诊断性缺陷**
- `测试设计方案.md` §8 声称覆盖「`x` 的特殊值域（±0、次正规、±65504、inf/-inf/nan）」——与产物不符（overclaim）。
- `testcases/aclnnGridSampler3D_l0_coverage_report.yaml` 报 `50/50 = 100.00%`，其中 `x.value_range` 目标集
  恰为「已生成的 16 个值」——分母取自生成结果，缺生成的声明值不在分母内。

## P2 — L1 泛化用例大量重复（100 条中 98 条为重复行，有效唯一 2 条）

**现象**
- `testcases/aclnnGridSampler3D_l1_test_cases.csv` 100 行，按用例内容（忽略 `testcase_name`）去重后
  **仅 2 种内容**（56 条 + 44 条）。
- `design/aclnnGridSampler3D_l1_coverage_report.yaml`（若产出）中「可行两两组合覆盖 100%」，但有效唯一用例 2 条。

**根因（现象级，代码事实）**
- `generate_test_cases.py::pad_cases` 从 `selected_indices`（**已选中**的 2 个索引）里
  `random.choice` 重复抽样补到 `--target-count 100`；补齐行与实选行内容完全相同。
- 可补的「新」材料也少：L1 的 `is_discrete_factor` 过滤掉 `.value_range`/`.value`/`.shape`，本算子
  离散多值因子只剩 x/grid/y.dtype（受 C-TYPE-001/002 强相关），两两可行组合仅 6 个、贪心选中 2 条即覆盖完毕。
- 上述 P1 又使底层池只有 24 条内容——即便按索引补齐也拿不到新内容。

## P3 — L0 覆盖报告分母取自生成结果，属自证 100%（不可诊断）

**现象**
- `aclnnGridSampler3D_l0_coverage_report.yaml`：`total_factor_values: 50 / covered: 50 / coverage_rate: 100.00%`，
  但同时 P1 表明声明的 inf/-inf/nan 等 11 个 range 从未生成。

**根因（现象级，代码事实）**
- `generate_test_cases.py::extract_all_factor_values` 在给定 df 时，目标域 = `df[factor].unique()`
  （**生成结果**），不并入 `04_测试因子.yaml` 的声明值 → 「声明了却没生成」的缺口不进分母，报告恒 100%。
- 与 P1 叠加时，报告把 P1 的漏生成掩盖成「已覆盖」。

## P4 — （相邻，未在本工作处理）空 tensor 派生脚本列名失配

**现象**
- `generate_test_cases.py` 调 `generate_empty_tensor_cases_derive.py` 时抛
  `KeyError: 'case_name'`，被 `generate_empty_cases_inline` 的 `except Exception` 以 WARN 吞掉
  → L0/L1 无空 tensor 用例（需求明确的 `N=0` / 输出空间维为 0 边界在 L0/L1 缺样例）。
- 该脚本仍用旧 TTK 列名（`case_name`/`input_tensor_dtype`/`input_tensor_shape`），而当前中间列已改名为
  `testcase_name`/`tensor_dtypes`/`tensor_view_shapes`。

## P5 — P1 修复引入结构过集中：补入的 value_range 全堆在同一结构模板上

> 观测于 P1 修复落地后的产物（run `20260923-120650-529af0` 单 stage 重跑结果）。

**现象**
- `testcases/aclnnGridSampler3D_l0_test_cases.csv` 36 条中，**21 条**（第 1、11–27、34–36 条）
  的 `tensor_view_shapes`/`tensor_dtypes`/`attributes` **完全同构**——同为
  `(1,10,1,1,4)/(1,2,1,4,3)/(1,10,2,1,4)`、float16、bilinear·zeros·align0，仅
  `input_data_ranges` 的 `x.value_range`（少数为 `grid.value_range`）不同。
- 该 run 池中本有 12 种不同形状，却让 58% 的门槛用例落在同一个形状模板上。

**根因（现象级，代码事实）**
- `generate_factor_values.py::complete_value_range_coverage` 为补全每个声明 range 所克隆的基用例
  **恒取 `same_dtype[0]`**（第一条同 dtype 用例），故同 dtype 的全部缺失 range 被堆到同一个结构上；
  下游 L0 单因子覆盖又必须让每个 range 各出现一次，遂把这批同构行全部选入 → 大量结构重复。

## P6 — （相邻观察，未在本工作处理）池级去重与 TTK 表示不一致，L1 出现 1 条表示层重复

**现象**
- 单 stage 重跑后 `aclnnGridSampler3D_l1_test_cases.csv` 69 行中，2 行（L1_001/L1_012）在
  13 列 TTK 表示下完全相同；池 `07_因子值.csv` 中这两行仅 `align_corners.value_range` 不同
  （`["+0","+0"]` vs `[0,1]`），而该因子不进 TTK 的 `input_data_ranges`/`scalar_data_ranges`/`attributes`。
- `pad_cases` 按池级内容（全列）去重，故这两行在**池层不同、表示层相同**时都被保留。

