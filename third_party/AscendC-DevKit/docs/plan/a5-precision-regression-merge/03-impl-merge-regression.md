# L4 实施方案 — regression 合入 kernel_debug

## 改动点（符号级）

### 1. Python 编排层

| 文件 | 改动 |
|------|------|
| `src/ascendc_devkit/orchestration/stages/precision_debug_a5/regression.py` | **删除**（regression 阶段类移除）。 |
| `src/.../kernel_debug.py` | 新增 `_reconcile_queue_from_full_kl(state, cp, phase_result)`：`fixed` 后读 KL summary（`_load_latest_kl_data`）→ `_refresh_queue_kl_diffs` / `_reconcile_queue_from_kl` / `_apply_kl_failures_to_queue`（含 `load_cann_bench_case_meta` 富集）→ 交叉校验 `new_failed_cases` → 返回 `_kl_status`（`vector_error` / `kl_all_pass` / `case_kl_fails`）；`fixed` 且提供 `kl_result` 时 `_merge_best_snapshot` + `_commit_modified_numeric_phase`（晋升 best_commit）。`transition` 在 `not skipped and debug_status=fixed` 时调用，`dc["_kl_status"]=...`。`resolve_condition`：`fixed` → `dc.get("_kl_status", "case_kl_fails")`。`_phase_prompt` 增「修复后全量 KernelLaunch 验证」步骤。 |
| `src/.../case_loop.py` | 新增 `_all_kl_passed(kl_data)`（per_case/all_results 全量携带 passed 证据才判全过）。 |
| `src/.../transition_table.py` | 删除 `regression` 条目；kernel_debug 的 `fixed→regression` 改为 `kl_all_pass→baseline(validation)`、`case_kl_fails→kernel_debug(corrective)`。 |
| `src/.../base.py` | `_PHASE_STEM_MAP` 删 `regression_result.json`；`_STATUS_KEY_BY_PHASE` / `_KNOWN_STATUS_VALUES_BY_PHASE` / `_RETURN_FIELD_RES` 删 `regression`；注释同步。 |
| `src/.../__init__.py` | 删 `RegressionSubstage` / `FinalizeSubstage` 导入、导出、别名；导出 `_all_kl_passed`。 |
| `src/.../checkpoint.py` | `_FRAMEWORK_OWNED_KEYS` 删 `regression_round`。 |
| `src/.../best_snapshot.py` | `_numeric_result`：`phase=="regression"` 分支并入 `phase=="kernel_debug"`（先 `kl_result` 后 `precision_result`）；注释同步。 |
| `src/.../precision_debug_tree.py` | A5 children 删 `RegressionSubstage`（6→5 叶子）。 |
| `resources/orchestration-config.json` | `skills.stages` 删 `regression`；`skills.tail_calls` 删 `ascendc-precision-regression`。 |

### 2. skill / agent

- 删除 `.claude/skills/ascendc-precision-regression/`、`.claude/agents/ascendc-precision-regression.md`。
- `.claude/skills/ascendc-precision-kernel-debug/SKILL.md`：新增 Step 7（fixed 后批跑全量
  KernelLaunch + `kl_result` 输出 + 路由由框架推导）；删「不得跑全量用例」禁令；Driver 状态机
  映射更新；上下游阶段引用更新。
- `.claude/agents/ascendc-precision-kernel-debug.md`：职责补「fixed 后批跑全量 KL」。
- `.claude/skills/ascendc-precision-baseline/SKILL.md` / `-vector-error-debug` /
  `-op-plugin-debug`：删除对 regression 的引用。

### 3. 测试

- `tests/ut/orchestration/test_precision_debug_a5_routing.py`：regression 用例改写为
  kernel_debug fixed + 全量 KL 调和/路由用例；agent-return 校验用例改 kernel_debug；
  删 regression prompt 用例；transition table 断言更新。
- `tests/ut/orchestration/test_precision_debug_a5_source_safety.py`：regression → kernel_debug
  （KL schema 晋升 / round 文件约定 / drift guard）。
- `tests/ut/orchestration/test_precision_debug_stage.py`：A5 group 5 子阶段；kernel_debug
  transition table / resolve_condition / vector-error 源阶段 / 非终态断言更新。
- `tests/ut/orchestration/test_precision_debug_runtime_refine.py`：A5 group 长度 6→5。

## 验证

- `PYTHONPATH=src python3 -m pytest tests/ut/orchestration/test_precision_debug_a5_routing.py
  tests/ut/orchestration/test_precision_debug_a5_source_safety.py
  tests/ut/orchestration/test_precision_debug_stage.py -q --no-env-check` 全绿。
- `PYTHONPATH=src python3 -m pytest tests/ut/orchestration -q --no-env-check` 全绿（0 回归）。
- 全仓 grep 无 `ascendc-precision-regression` / `RegressionSubstage` / `regression_status`
  / `regression_round` 残留（A3 侧 `regression_evidence` 等不同概念除外）。

## 环境备注

本机默认 editable install 指向陈旧路径
`/home/w00940184/workspace/Agent/AscendC-DevKit-BatchRun/workdir_0818/AscendC-DevKit`，
导致裸 `pytest` 加载旧代码。验证统一用 `PYTHONPATH=src` 前置本仓源码树。
