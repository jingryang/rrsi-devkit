# L1 问题记录 — st-design 符号值域流入用例（A3 批量精度全挂）

> 日期：2026-10-12 冻结。本文件只记客观事实与证据，不含方案与排序。

## P1 109 条 devkit 用例批量精度全挂（触发事实）

- run：`output/20261010-075905-d21c30/20261010-075905-02c9f4`（A3 机器 precision_debug）
- 现象：`HALTED — test_design: devkit(aclnn L0/L1)用例输入非法、golden 全挂`；109 条 devkit 用例全部失败，报错为 cross_entropy `IndexError`（targets 取到 -1，非法类别下标）。
- 事故行（`artifacts/test_design/合并_测试用例.csv` 的 `aclnnMseLossCrossEntropyLoss_L0_001`，原样）：
  - `stc_inputs = [(1,2,3,1,1,1,1,8,),(1,3,1,1,1,1,8,),(1,2,3,1,1,1,1,8,)]`，`stc_input_dtypes = ('bfloat16','int64','bfloat16',)`
  - `input_data_ranges = ((0,0,),(0,C-1,),(0,0,),)` —— 第二个输入（int64 targets）的上界是**符号表达式** `C-1`。

## P2 符号候选的承载链：声明 → 求解 → 渲染 → 合并 → 装箱，全程零校验

1. 声明：`design/04_测试因子.yaml` 的 `targets.value_range_int64: [[0, "C-1"]]`（符号直接作为声明候选）。
2. 求解：`generate_factor_values.py` 的三个读取口（`get_value_range_for_dtype`、`get_factor_domain` 前缀兜底、`_declared_value_ranges` 覆盖补齐）把候选**原样**装进组合/结果，无任何数值校验；实测 30 case 中 `[0, 'C-1']` 原样落盘。
3. 渲染：`generate_test_cases.py` 将其写入用例 CSV `input_data_ranges` 列（`_format_number` 对不可识别字符串原样 `str(x)`）。
4. 合并：`merge_test_cases.py` 汇入 devkit 13 列格式（inf/nan 归一为带引号字面量，符号串同样照抄）。
5. 装箱：`csv_to_testcases.py` 历史实现把 ranges 原始字符串塞进 case 级 `generator_params.ranges`（**全仓零消费者**）。
6. 运行：harness 读不到 per-input `value_range` → 回退 `[-1,1]` → int64 targets 生成 -1 → P1 的事故。

## P3 缺陷双端同源，A5 未触发只因其算子域

- 950 侧 runner/harness 同样没有 ranges 处理（逐字节同源）；A5 批量一直绿，是因为其算子无受约束整数域（类别下标类），`[-1,1]` 回退对 float 无害。
- 合并（fusion，用户裁决沿用）使 st-design 对外部用例也跑 LLM 因子设计，109 条 devkit 用例**首次进入 A3 test set**（base 上该路径为 NoOp skip）——合并改变的是**触发面**，缺陷本身先于合并存在。

## P4 机械隐式约束对符号候选构成假承诺

- `05_约束定义.yaml` 含 `IMPLICIT-RANGE-targets`（`derive_value_range_from_dtype`）。事实：该约束 target 为 `targets.value_range`，与 per-dtype 因子名 `targets.value_range_int64` 精确匹配**不中**（`find_all_constraints_for_factor` 全等比较）——真实链路中它是死约束，实际承载靠 `expand_value_range_for_dtype` 裸读候选。
- 语义层面：候选含符号时，"按 dtype 选值"无法实例化符号，该约束的描述与行为不成立。

## P5 求解器裸 `except` 会吞掉诚实校验错误

- `generate_factor_values.py` `solve_constraint_range` 的 `except: return None`：任何 `ValueError`（含本应指名报错的校验）被吞成 None，静默转入候选兜底路径。

## P6 `(0,0)` 与 inf/nan 的语义钉死（验证过程事实）

- `(0,0)` 是因子候选列表中被选中的**字面区间**（全零 logits 边界用例），不是空占位/无约束——设计产物 `04_测试因子.yaml` 候选表实证。
- `inf/-inf/nan` 为特殊值字面量（带引号形式可被 `literal_eval` 解析）；真实合并 CSV 中 52 行含此形态。
- `C-1` 类符号是**未实例化表达式**；`C = logits.shape[1]` 仅存在于 `requirement.json` 的 prose，全链无机器可执行定义。
