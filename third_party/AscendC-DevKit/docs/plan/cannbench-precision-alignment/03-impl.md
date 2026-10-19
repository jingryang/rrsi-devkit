# L4 实施方案：devkit 精度判定完全对齐 cann-bench 生产评测

> 关联 L1 `01-problems.md`（P1-P5）、L3 `02-analysis.md`（选 B）。状态：**已实施 ✅**。

## 改动 1：`src/ascendc_devkit/adapters/npu/precision_compare.py`

1. `OutputVerdict` 增加 4 字段 `normal_error_count` / `normal_cpu_error_count` / `normal_total_count` / `normal_passed` + `to_dict` 透出（对齐 cann-bench `CompareResult.normal_*`）。
2. `_compare_single`：
   - 小值域：删「`cpu_error_count == 0` 零容忍」特判 → 恒 `ratio≤2`；
   - 相消：同删零容忍 → 恒 `ratio≤2`；
   - 正常值域：补 #92 兜底——`normal_passed = (normal_error_count / normal_cpu_error_count) ≤ 2`（CPU 参考自身也脏时放宽），否则严格失败；
   - 最终 `passed = normal_passed and small_value_passed and cancel_passed`；
   - display MERE/MARE 逻辑对齐 cann-bench（pass 显示排除小值域/相消后的 normal 区值，fail 按原因）。
3. 模块 docstring：取消 2026-08-01 偏离声明，声明三值域完全对齐。

## 改动 2：`src/ascendc_devkit/adapters/npu/_harness_template.py`

1. 新增 `_upcast_fp64(_x)`：对齐 cann-bench `tensors_to_fp64_cpu`——浮点（torch/numpy）→ float64，int/bool/None 保持，list（TensorList）递归。
2. **CANN 分支**（`_golden_core` 路径）：
   - ① native 参考：原生精度输入跑 golden → `_n_tensors`；
   - ② fp64 golden：`_upcast_fp64(_torch_inputs)` 跑 golden → `_g_tensors`；
   - `compare_tensors(..., native_output=_fp64_native_out)`。
3. **FALLBACK 分支**（`golden_fn` 路径）：
   - ① native 参考：现有原生 `golden_np_list` → `_n_tensors`；
   - ② fp64 golden：`golden_fn(*_upcast_fp64(_np_inputs))` → `golden_np_list_fp64` → `_g_tensors`；
   - `compare_outputs(..., native_refs=(_n_tensors if _fp64_ok else None))`。
4. 显示逻辑（`golden_first10`/`max_diff_location`）用 fp64 golden `golden_np_list_fp64`（与判定同源，F2/F3 review 整改）。

> **review 整改（2026-08-10，F1/F2/F3）**：三处 fp64 golden 调用（CANN torch / CANN else / FALLBACK）均包 `try/except Exception`——golden 不支持 fp64 输入（抛异常）时 `print('[harness] WARN ... fp64 golden 不可用...')` 留痕（可观测）+ 回退 native golden 当权威 + native 参考置 None（`cpu_diff≡0` 严格语义），不把 case 打成 error（§1.2 正确改动+宽容兜底+可观测）。显示基准统一为 fp64 golden（原 native 显示会与判定对不上）。

## 改动 3：`tests/ut/adapters/test_precision_compare.py`

1. `test_small_value_no_cpu_ref_devkit_intentionally_stricter` → `test_small_value_no_cpu_ref_aligned_parity`（断言 dev==cb parity，不再断言 dev 更严）。
2. 新增 helper `_cannbench_compare_with_native` / `_assert_parity_with_native`（两侧都传同精度参考对拍）。
3. 新增 6 个 parity 盲区用例：
   - `test_parity_small_value_with_native`（1-2 错干净 native PASS / 3 错 FAIL / CPU 脏 ratio≤2 PASS）；
   - `test_parity_cancel_with_native`（同款）；
   - `test_parity_normal_region_issue92`（#92 兜底 PASS / 参考干净 FAIL / ratio>2 FAIL）；
   - `test_output_verdict_exposes_normal_fields`（normal_* 字段透出）；
   - `test_parity_native_length_mismatch`（F5 review 整改：native 输出数量不匹配 → devkit 与 cann-bench 都显式失败 + error_msg）。

## 改动 4：`tests/ut/adapters/test_runner_execute.py` + fixture

1. `TestHarnessBackendContractVars` 新增：
   - `test_devkit_harness_passes_native_refs`（断言 FALLBACK 含 `native_refs=(_n_tensors if _fp64_ok else None)` / `_upcast_fp64` / `golden_np_list_fp64` / F1 `fp64 golden 不可用` WARN / F2 显示 `golden_np_list_fp64[_v.index]`）；
   - `test_cannbench_harness_passes_native_output`（断言 CANN 含 `native_output=_fp64_native_out` / `_upcast_fp64(_torch_inputs)` / F1 WARN）。
2. `fixtures/harness_devkit_golden.txt` 经 `TestHarnessExtractionSnapshot._src()` 重建（构造性逐字节）。

## 改动 5：文档

- `docs/plan/self-evolution/87-batch-20260801-050054-ab7283-harness-shared-middle-impl.md` §独立发现补「⚠️ 已反转（2026-08-10）」。
- 本目录 `01-problems.md`（L1）/ `02-analysis.md`（L3）/ `03-impl.md`（L4）。
- `docs/plan/skills-integration-and-tdd-plan.md` L2 索引表追加本工作行。

## 验证

1. parity UT（带 cann-bench PYTHONPATH）：`test_precision_compare.py` 57 passed（含 6 个新 parity 盲区，+F5 native 数量守卫）。
2. 差分回归：69 场景 × 3 参考模式（无参考/干净 native/脏 native）× 三值域，`compare_outputs` vs `compare_tensors` **0 分歧**。
3. 受影响 adapters UT：499 passed；全量 UT `--quick` 3969 passed（2 failed 为既存 capabilities 环境问题：gitignored `.claude/settings.json` 缺失）。
4. ST（真实 NPU）：本环境无 NPU，留待有环境时验证 gelu 病态用例 debug 与 cann-bench eval 判定一致（§3.9/§3.11）。

## as-built（review 整改记录）

- **commit**：本工作（`da024826`）+ 整改（未独立提交，改动并入当前工作区）。整改文件：`precision_compare.py`（F5 native 数量守卫）、`_harness_template.py`（F1 fp64 兜底 / F2/F3 显示同源）、`test_precision_compare.py`（+F5 parity）、`test_runner_execute.py`（+F1/F2 断言）、`harness_devkit_golden.txt`（重建）。
- **偏差**：改动 2 §4「显示用 native」已反转（review F2/F3 定为 fp64 同源）；改动 2 §2/§3 native 参考改经 `_fp64_ok` 条件传入（F1）。
- **F4/F6 待办**：无 NPU 未跑执行态测试/真机 ST；大 shape golden 预算需真机关注。
- **F7 待办**：差分回归 69 场景 × 3 参考模式固化为可复用脚本。
