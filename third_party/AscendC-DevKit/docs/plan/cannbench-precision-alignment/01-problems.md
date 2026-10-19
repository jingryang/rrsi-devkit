# L1 问题记录：devkit 精度判定与 cann-bench 不一致（gelu 假性不通过）

> 四层方案体系（docs/plan/README.md）L1：只记录客观事实，不提方案、不排顺序、不写决策。

## P1：devkit `compare_outputs` 小值域/相消无 CPU 参考时零容忍，比 cann-bench `compare_tensors` 严

- **事实**：`precision_compare.py` 小值域分支（原 L452-462）与相消分支（原 L474-481）在 `small_value_cpu_error_count == 0` / `cancel_cpu_error_count == 0` 时要求 NPU 零错误；cann-bench `compare.py` 同场景用 `ErrorCount_npu / max(ErrorCount_cpu, 1) ≤ 2`（容忍 ≤2 个）。
- **证据**：差分实测 `golden=1e-6, output=2e-6`（1 个小值域误差，无 native 参考）——devkit `passed=False`、cann-bench `passed=True`。
- **来源**：2026-08-01 设计决策「保持 devkit 严格、不对齐 cann-bench」（提交 `924d0438`，防 golden=1e-6/output=65504 假阳性）。

## P2：devkit `compare_outputs` 正常值域无同精度兜底，缺 cann-bench issue #92 逻辑

- **事实**：cann-bench `855d3ef`（2026-07-24）为正常值域补同精度兜底：同精度参考(native)自身在正常值域也超标时（深归约/病态 fp32）允许候选不差于 2× 参考；devkit `precision_compare.py`（复刻基线 2026-07-14，早于 #92）仍是「正常值域有超标点直接失败」。
- **证据**：差分实测 `golden=[1,2,3], output=1.02 偏移, native=1.01 偏移`——devkit `passed=False`、cann-bench `passed=True`（#92 兜底 3/3≤2）。

## P3：devkit harness 从不传同精度参考，cpu_diff≡0 致 P1 分支恒触发

- **事实**：`_harness_template.py` CANN 分支（compare_tensors）不传 `native_output`、FALLBACK 分支（compare_outputs）不传 `native_refs`；无参考时 `cpu_diff ≡ 0` → `cpu_error_count ≡ 0` → P1 零容忍分支恒触发。
- **证据**：gelu 算子复盘（`session_gelu`，2026-08-09~10）：4 个用例（gelu_5/8/11/20）在 devkit precision_debug 判失败、cann-bench 真实评测 20/20 通过。根因是相消桶（`cancel_cpu_error_count=64`），kernel 精度 ≈ CPU 同精度参考（Erfc/sigmoid 修复后 0 错），零容忍误杀正确修复。

## P4：devkit harness golden 以原生精度计算，无 fp64 golden

- **事实**：cann-bench 生产评测 `golden_precision=fp64_cpu`：golden 在升精度 fp64 输入上跑作权威真值，原生精度跑作同精度参考。devkit harness 只有原生精度 golden 一遍，无 fp64 权威 golden。
- **证据**：`_harness_template.py` CANN 分支 L423 / FALLBACK 分支 L618 均单次原生精度调用 golden。

## P5（客观后果）：同一算子 devkit 与 cann-bench 判定可能不一致

- 病态深归约（CPU 参考脏）场景 devkit 误杀；已由 P3/P4 的 gelu 实例证实。
- 方向恒为「devkit 更严」（不存在 devkit 漏判），对评测公平性是偏保守方向但产生假性不通过。
