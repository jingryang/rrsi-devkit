# L4 实施方案：baseline st-design / cann-bench 用例来源拆分

> 依据 L3 `02-analysis.md` 冻结的决策（方案 A + 框架注入/复核）。

## 改动清单

| # | 位置 | 改动 |
|---|------|------|
| 1 | `src/ascendc_devkit/domain/requirement.py` | `TestCase` 增 `source: str = ""`（来源：`cannbench` / `devkit`；空=unknown/存量） |
| 2 | `src/ascendc_devkit/domain/cann_bench_cases_loader.py` | `parse_cann_bench_csv` 构造 `TestCase(..., source="cannbench")` |
| 3 | `src/ascendc_devkit/adapters/testdesign/csv_to_testcases.py` | `_row_to_testcase` 构造 `TestCase(..., source="devkit")` |
| 4 | `src/ascendc_devkit/orchestration/stages/precision_debug_a5/base.py` | 新增常量 `CASE_SOURCE_CANN_BENCH`/`CASE_SOURCE_DEVKIT` + `case_source_composition(cases)`；`_common_context` 注入 `test_case_source_composition` |
| 5 | `src/ascendc_devkit/orchestration/stages/precision_debug_a5/baseline.py` | `_phase_prompt` 渲染注入组成 + 拆分任务；transition 复核 `rc_result.by_source.devkit.total == composition.devkit`（不一致 WARN，不改路由）；组成写入 checkpoint |
| 6 | `.claude/skills/ascendc-precision-baseline/SKILL.md` | Step 2 增「用例来源拆分」小节；Step 8 schema 增 `rc_result.by_source`；返回块增 `st-design-case: {N}/{M}` 行 + 说明 |
| 7 | `.claude/agents/ascendc-precision-baseline.md` | 增「Case-source split (mandatory)」段：与注入组成一致、分类规则、kl 无 st-design 拆分 |
| 8 | `tests/ut/orchestration/test_case_source_provenance.py` | 新增 5 例（两 loader 打标 / 组成计数 / 空与 None / baseline prompt 渲染） |

## 关键不变式

- **来源在构造点单点确定**（§1.15）：两 loader 各自打标，无第二处推断。
- **不认名字**（§1.12）：拆分依据是 `TestCase.source`，不是 `aclnn` 前缀 / case_id 形态。
- **复核不改路由**：`st-design-case` 是报告维度；`double_tool_passed`/队列路由不受影响。
- **unknown 不静默归并**：无标记用例单列 `unknown`，不进 cannbench/devkit。

## 验证

- UT：`PYTHONPATH=src python3 -m pytest tests/ut/orchestration/test_case_source_provenance.py --quick -q`
  → **5 passed**。
- 相邻回归：`tests/ut/domain/test_cann_bench_cases_loader.py` +
  `tests/ut/adapters/test_csv_to_testcases.py` +
  `tests/ut/orchestration/test_precision_debug_a5_routing.py` + 新用例
  → **143 passed**。
- 全量 `tests/ut/{orchestration,domain,adapters} --quick`：2836 passed；
  63 failed + 2 errors 全部为**本机缺 `anyio`** 的既有环境失败（改前即存在，§3.7），
  与本改动无关（失败文件均经 `sdk_backend` 导入链）。

## 不做

- 不改 run-cases（跑合并集）/ KernelLaunch（只跑 cann-bench）行为。
- 不改路由/验收语义（不把来源拆分上升为闸门）。
- 不处理「kl 也覆盖 st-design」的未来形态（L3 §4 留观）。
- 不新增 baseline schema 文件（baseline 走自定义契约，`_validate_phase_json` 已跳过）。

## 后续修订（2026-09-29）：`rc_pass` 标记语义

> 见 L3 §5。改动 5/6/7 文案：`## BASELINE_RESULT` 的 `rc_pass` 行取 cann-bench 子集
> （`by_source.cannbench`，与 `kl_pass` 同基、可直接交叉对比），`rc_result.pass/total`
> 保持全量合并（框架验收门不变）；Step 7 增补两行关系的说明。UT
> `test_baseline_prompt_renders_composition_and_split_instruction` 断言同步更新
> （`rc_pass` 子集 + `by_source.cannbench`）。
