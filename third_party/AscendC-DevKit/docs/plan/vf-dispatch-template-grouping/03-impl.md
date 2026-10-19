# VF 并行派发按模板组分批 — 实施方案（L4）

> 对应 L1 `01-problems.md` / L3 `02-analysis.md`（已冻结）。TDD 模式（§3.1）。

## 改动清单

1. **`src/ascendc_devkit/orchestration/stages/codegen_s4.py`** — 新增辅助函数
   `vf_group_base(sid)`：VF 步骤的模板组基名（去掉 `.VT.{M}` 后缀；
   `4.C.3.VT.0 → 4.C.3`），非 VF id 原样返回。

2. **`src/ascendc_devkit/orchestration/stages/codegen.py`** — `_actions_regbase_vf`：
   保留串行 canary（`first_vf in pending → [first_vf]`）；并行阶段批量改为
   「只取与当前 frontier 同组的 pending VF」，取前 `max_concurrent_vf` 个；
   组内无成员时退化为 `[sub_stage]`。import `vf_group_base`。

3. **`tests/ut/orchestration/test_codegen_regbase_phases.py`** — 新增跨模板隔离用例：
   - plan 含两组 VF（`4.C.3.VT.{0,1}` 与 `4.C.6.VT.{0,1}`），首个 VF done 后，
     frontier=`4.C.3.VT.1` → 批内**只含** `[4.C.3.VT.1]`，不含 `4.C.6.VT.*`；
   - frontier 到 `4.C.6.VT.0`（4.C.3 组全部 done）→ 批 = `[4.C.6.VT.0, 4.C.6.VT.1]`。

## 实施顺序

1. 先写失败的 UT（红）：跨模板隔离断言。
2. 实现 `vf_group_base` + 改 `_actions_regbase_vf`（绿）。
3. 回归：`tests/ut/orchestration/test_codegen_regbase_phases.py` 全量 + 相关 codegen UT。

## 验证

- 定向：`PYTHONPATH=src pytest tests/ut/orchestration/test_codegen_regbase_phases.py tests/ut/orchestration/test_codegen_s4_dispatch.py`
- 回归：`PYTHONPATH=src pytest tests/ut/orchestration`（codegen 相关套件）。
- 真实 heavy_llm codegen e2e（VF 并行批真实跑）属 §3.11 用户确认项，不在本次默认执行。

## 不做清单

- 不改 `max_concurrent_vf`（保持 2）。
- 不改 plan 顺序推进 / 重试 / 升级逻辑。
- 不动 `4.C.3.VT.0` 的串行 canary 语义（保留）。

## As-built（2026-09-01）

已实施：

1. `codegen_s4.vf_group_base(sid)`：`.VT.{M}` 基名提取（`4.C.3.VT.0 → 4.C.3`），非 VF id 原样返回。
2. `codegen.py:_actions_regbase_vf`：串行 canary 保留；并行阶段 `batch =
   group_pending[:max_concurrent_vf]`（同组过滤），组内空退化为 `[sub_stage]`。
3. 测试 +2（跨模板隔离 / T2 组内并行），fixture `_cross_group_vf_plan_steps()`。

验证结果：

- 定向（新测试红→绿）+ `TestParallelVfDispatch` 12 例全绿。
- 回归：`test_codegen_regbase_phases.py` + `test_codegen_s4_dispatch.py` +
  `test_codegen_a5_constraints.py` + `test_session_resume.py` 共 208 passed。
- `tests/ut/orchestration` 全量 2067 passed。
- 全量 `tests/ut --quick` 4129 passed / 2 failed——2 failed 为 `test_p126_git_identity_fallback.py`
  存量环境失败（git identity 探测，与本改动无关，base commit 上同样失败）。
- heavy_llm codegen e2e（VF 并行批真实跑）§3.11 用户确认项，未在本次执行。

