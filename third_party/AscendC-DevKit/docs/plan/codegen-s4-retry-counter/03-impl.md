# s4 子阶段重试计数（per-substage）— 实施方案（L4）

> 对应 L1 `01-problems.md` / L3 `02-analysis.md`（已冻结）。TDD 模式（§3.1）。

## 改动清单

1. **`src/ascendc_devkit/orchestration/stages/codegen_s4.py`**
   - 新增 `_retry_key_label(err_type) -> (key, label) | None`：错误类型→(计数器键, label)
     唯一映射（ENV/DSG/未知 → None）。
   - 新增 `_step_retry_count(plan, sid) -> int`：读 `orchestration_plan.json`
     sub_stage 条目的 `retry_count`（per-substage，缺省 0）。
   - `check_retry_exceeded(rd, sid, err_type)`：`used = _step_retry_count(plan, sid)`，
     `limit = RETRY_COUNTER_LIMITS[key]`；ENV/DSG/未知分支保持原语义与文案。
   - `bump_retry_counter(rd, sid, err_type)`：递增该 sub_stage 的 `retry_count`
     （写回 plan，懒初始化）；无映射类别或 sid 空不动作。
   - `_set_status`/`_set_statuses`：状态置 `done` 时清零 `retry_count`（尝试窗口计）。
   - `dispatch` FAILED 分支：`failure_sid = failed_sub_stage or current`，
     `bump_retry_counter(rd, failure_sid, error_type)` 后
     `check_retry_exceeded(rd, failure_sid, error_type)`。
   - 删除不再使用的 `_read_meta` / `_counter_exhausted`（§2.5 不留死代码）。

2. **`src/ascendc_devkit/orchestration/stages/codegen.py`**
   - `_transition_regbase_s4_parallel` FAILED 分支：
     `bump_retry_counter(rd, sub_stage, effective_error_type)` →
     `check_retry_exceeded(rd, sub_stage, effective_error_type)`。

3. **`tests/ut/orchestration/test_codegen_s4_dispatch.py`**
   - 改用 plan sub_stage 的 `retry_count` 断言（`_set_step_retry_count` /
     `_step_retry_count` 辅助）；删 `_set_meta`。
   - 新增：FAILED 递增当前子阶段 retry_count / 同一子阶段 4 次后 rollback /
     **per-substage 隔离**（4.B1 触顶不影响 4.A）/ ENV 不递增 / VF 子阶段递增。

4. **`tests/ut/orchestration/test_codegen_regbase_phases.py`**
   - 并行 FAILED 成员递增其 VF 子阶段 retry_count。

## 实施顺序

1. 先写失败 UT（红）：per-substage 递增 + 隔离断言。
2. 实现 `_retry_key_label` / `_step_retry_count` / `bump_retry_counter` /
   `check_retry_exceeded`（per-substage）/ dispatch 接线 / 并行 transition 接线（绿）。
3. 回归：`test_codegen_s4_dispatch.py` + `test_codegen_regbase_phases.py` + 全量 orchestration UT。

## 验证

- 定向：`PYTHONPATH=src pytest tests/ut/orchestration/test_codegen_s4_dispatch.py tests/ut/orchestration/test_codegen_regbase_phases.py`
- 回归：`PYTHONPATH=src pytest tests/ut/orchestration`
- 全量：`PYTHONPATH=src pytest tests/ut --quick`
- heavy_llm 真实 e2e 属 §3.11 用户确认项，不在本次默认执行。

## 不做清单

- 不改 ENV 恒 pause / DSG 恒回退 / 未注册错误类型（OTH/未知）语义。
- 不改 s2/s5 的 `_handle_regbase_failure` 计数通路（阶段级，非 substage）。
- 不新增计数类别、不改 RETRY_COUNTER_LIMITS 上限。
- `meta.json retries` 不再承载 s4 计数（仅 s2/s5 阶段计数 + limit 镜像保留）。

## As-built（2026-09-01）

已实施：上述 1/2/3/4 全部落地；`dispatch` 与并行 transition 均按失败子阶段递增；
done 清零 retry_count。验证：

- 新增 UT 6 例（dispatch 递增 / 4 次后 rollback / per-substage 隔离 / ENV 不递增 /
  VF 子阶段递增 / 并行批成员递增），先红后绿。
- 回归：`test_codegen_s4_dispatch.py` + `test_codegen_regbase_phases.py` 176 passed；
  `tests/ut/orchestration` 全量 **2073 passed**。
- 全量 `tests/ut --quick` 待跑（§3.2）。
- heavy_llm 真实 e2e 属 §3.11 用户确认项，未在本次执行。
