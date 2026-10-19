# L1 问题记录：baseline 总结未区分 st-design 生成用例与 cann-bench 原有用例

> 事实快照，不提方案、不排顺序、不写决策。
> 观测来源：run `20260923-120650-529af0/20260923-120650-2d93d3/artifacts/precision_debug_a5/baseline/baseline_result.json`
> （算子实例仅作证据，机理对所有跑 test_design 增量融合的算子通用）。

## P1 — BASELINE_RESULT 只给合并总数，st-design 子集不可见

**现象**
- `baseline_result.json`：`rc_result` = `pass:136 / total:136`、`kl_result` = `pass:20 / total:20`。
  但 136 = **20 个 cann-bench 原有 L2 case** + **116 个 st-design 生成 L0/L1 case**
  （run-cases 跑合并集；KernelLaunch 只跑 cann-bench `cases.csv` 的 20 例）。
- agent 只能在 `conclusion` 文字里附带说明（如「其中任务 cases.csv 的 20 个 L2 case 与
  test_design 合并的 116 个 L0/L1 ST case 全过」），且 `rc_result` 里塞了一个**非 schema**
  的 `case_set` 字段自描述——既不在契约里，也无法被框架/下游确定性消费。
- `## BASELINE_RESULT` 返回块只有 `rc_pass` / `kl_pass` 两行，st-design 子集的通过率
  没有任何独立行（用户诉求：需要 `st-design-case: {N}/{M}`）。

## P2 — 用例来源无结构信号，拆分只能靠命名猜测

**现象**
- `TestCase`（`domain/requirement.py`）**没有来源字段**：cann-bench loader
  （`load_cann_bench_cases`）与 test-design CSV adapter（`parse_testcase_csv`）产出的
  `TestCase` 在结构上不可区分。
- 实测两来源的 `case_id` 都呈 cann-bench 风格（未命中时由 runner 从 name 末段 + golden
  rel_path 反推，如 st-design 的 `aclnnGridSampler3D_L0_001` → `level2/grid_sampler_3d_001`），
  所以**按 case_id 前缀分辨不可靠**。
- 唯一可分辨的是 name 约定（st-design 名 `aclnn..._L0_xxx`、cann-bench 名
  `{operator}_{case_id}`）——属命名启发式，非结构信号（§1.12）。
- 框架侧唯一存在的来源标记是 `state.cases_source`（单个值 `"cannbench"|"devkit"`），
  在增量融合下只表示「有外部 cases」，**不代表逐 case 来源**。
