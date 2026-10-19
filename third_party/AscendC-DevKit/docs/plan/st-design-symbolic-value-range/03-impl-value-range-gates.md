# L4 实施方案（as-built）— 符号值域闸口 + 逐输入挂载

> 对应 L3 方案 C。日期：2026-10-12。全部改动已落地并验证。

## 改动清单

### 1. `scripts/utils.py` — 共享单点（§1.15）

- `is_numeric_range_bound(v)`：int/float 或可 `float()` 解析的字面量（inf/-inf/nan/+0/-0/1e3）；bool 与其余（符号串、None、嵌套结构）为假。
- `validate_numeric_value_range_candidates(candidates, origin)`：候选对含不可执行边界 → `ValueError` 指名候选、因子与符号，附补救配方（形状来源 calculate 约束模板）。
- `validate_rendered_value_ranges(input_ranges, testcase_name)` + `_iter_range_pairs`：渲染期兜底，深度优先产出 `[lo,hi]` 对（兼容 TensorList 嵌套与 None 占位），报错指名用例。

### 2. `scripts/generate_factor_values.py` — 求解端三读取口 + 异常口

- `get_value_range_for_dtype`：返回前校验（`derive_value_range_from_dtype` 与 dtype 扩展共用）。
- `get_factor_domain`：`value_range*` 属性分支返回前校验（无约束因子的候选兜底路径）。
- `_declared_value_ranges`：声明读取时校验（覆盖补齐的强制注入路径）。
- `solve_constraint_range`：`except ValueError: raise` 前置于裸 `except: return None`——诚实校验错误不被吞（P5）。

### 3. `scripts/generate_test_cases.py` — 渲染端兜底

- `_build_ttk_case_data` 首行调用 `validate_rendered_value_ranges`（case 名可trace）。

### 4. `scripts/generate_implicit_constraints.py` — 移除假承诺（P4）

- 新增 `_has_symbolic_range_bound(param, factors)`：检测即打警告，附手写 calculate 约束配方（单一精确模板）。
- 三个 value_range 消费检查（`_check_value_range_from_dtype` / `_check_value_from_value_range` / `_check_array_value_from_range`）符号候选时不生成机械约束。

### 5. `SKILL.md` — 作者契约（§2.12 单一精确模板）

- §2.1 value_range 规范新增：边界必须可执行数值；shape 依赖值域禁止写符号候选，给出 calculate 约束模板。

### 6. `src/ascendc_devkit/adapters/testdesign/csv_to_testcases.py` — 转换端单点挂载

- ranges 解析 → `_normalize_range_slots`（空→[]；单输入行扁平对包装；数值对字面挂载含 `[0,0]`；inf/nan 字符串→float；符号串→`ValueError` 指名）。
- `_flat_inputs` / `_build_inputs`：逐输入挂载 `value_range`，长度平等性按路径把关（proto 路径按逻辑参数、flat 路径按张量槽、DYNAMIC 单值域管全部成员；DYNAMIC 分支 fixed 参数挂载补遗）。
- 删除 `generator_params.ranges` 死字段（§2.5/§1.4），`generator_params=None`。

## 验证（as-built）

| 项 | 结果 |
|---|---|
| 转换端 UT（`tests/ut/adapters/test_csv_to_testcases.py`） | 49 passed（含 10 条 ranges 契约 + 2 条真实事故行回归：事故行硬报错、实例化行逐输入挂载） |
| 生成端 UT（`tests/ut/skills/test_st_design_scripts.py`） | 33 passed（含 10 条符号闸口：判定、三读取口、覆盖路径、异常不吞、渲染兜底、隐式约束门） |
| adapters 全目录 | 620 passed |
| 全量 UT（除既有挂死 application/cli） | **4527 passed / 12 skipped / 0 failed** |
| 非 heavy ST | 106 passed / 8 skipped / 2 failed（均为既有 P10：NPU 卡 0 探测失败，与本改动无关） |
| heavy_llm ST | 本机无网关未跑（P2，如实记录） |
| 真实事故设计（04 含 `[[0,"C-1"]]`）跑求解器 | `ValueError: 值域候选 [0, 'C-1']（因子 targets.value_range_int64）含不可实例化的符号边界 'C-1'…`（附补救配方）✓ |
| 修正设计（04 去符号 + 05 形状来源约束）全链 | 求解 30 case → `targets.value_range` 全数值（[0,8]/[0,15]/[0,5683]…，`generate_solver_config` 拓扑排序自动排 `targets.value_range` 至 shape 后层级）；渲染 12 case 零符号；merge 归一化引号形态；转换器逐输入挂载 `[0, C-1]` 实例值，`generator_params` 无 ranges ✓ |

## 边界与遗留

- **整型输入缺声明值域的回退**：渲染端 `[-2,2]`（skill）与 harness `[-1,1]`（runner）对"完全未声明 ranges"的整型输入仍会回退出 -1——与本次同类终点、不同入口（声明缺失而非符号）。属声明契约问题（需拍板"受约束整型必须显式声明值域"），另案跟踪，未在本案范围。
- **950 侧同源缺口**：runner/harness 的 ranges 处理缺失在 950 侧同源存在（未触发），按用户裁决不同步，台账记录。
- P2 heavy_llm 批量复跑：待用户确认网关环境（§3.11）。
