# golden_precision harness-eval 分裂 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发算子：resize_bilinear（批跑 `20260809-170202-976a7a` / 执行 `20260809-170202-339545`）。
> 涉及代码：`adapters/npu/_harness_template.py`（harness golden 调用）、`adapters/npu/runner.py`、
> `application/debug_service.py`、`orchestration/kernel/state.py`、cann-bench
> `evaluator.py` / `utils/compare.py`（只读，非本仓 bug）。

## P1 — precision_debug 判 20/20，cann-bench eval 判 13/20

### 现象
resize_bilinear 批跑：precision_debug 4 轮 fix 后 `best_passed_count=20` → `converge_best_commit
6be45b47` 提前收敛；cann-bench 终评 **13/20**，7 例 `precision_mismatch`（case 4/5/8/12/16/17/19）。
debug 报告 `20/20 passed` 是假收敛。

### 根因（铁证，离线重算逐位复现 eval 报告）
1. **评测侧 golden 参考精度 = fp64_cpu**：cann-bench `BenchConfig.golden_precision` 默认
   `"fp64_cpu"`（`cann-bench/src/kernel_eval/registry/bench_registry.py:56`），evaluator
   `_apply_golden_precision` 把 golden 输入升 fp64 计算参考（`evaluator.py:831`）；比较时
   `compare.py:350` 再把 golden 截断回 kernel dtype。
2. **devkit harness 无 golden_precision 实现**：`_harness_template.py` 的 CANN 路径
   `_golden_core(_torch_inputs, _attrs)` 直接把原生 dtype（fp16/bf16/fp32）输入喂 golden
   → 原生精度参考。
3. **两侧参考不同 → 判定分裂**。用真实 kernel（== native torch fp16，harness 实证 diff=0.0）
   分别对两种 golden 重算（`compare_tensors`，同输入 seed）：

   | case | kernel vs native golden | kernel vs fp64 golden（截断） | eval 报告 |
   |---|---|---|---|
   | case4 | MERE=0.0 / MARE=0.0（过） | MERE=0.000777 / MARE=0.147（挂） | MERE=0.000777 / MARE=0.147 ✅ |
   | case17 | 0.0（过） | MERE=2.1e-3 / MARE=224（挂） | MERE=2.1e-3 / MARE=224 ✅ |

   → **eval 用 fp64 参考，精确复现**；harness 用原生参考，判全过。
4. **深层**：kernel == native torch（golden 的原生行为，无实现缺陷）。**native torch 自身相对
   fp64 参考在 7 个边界用例上超差**（大值域 / align_corners=true 上采样 / ±inf 输入 / 近零输出，
   fp16 舍入与相消误差被 MARE 指标放大）。当前 kernel 另因 round-2「fp16/bf16 权重量化」
   （为对齐 native torch）偏离 fp64 参考。

### 凭证
- eval 报告：`cann-bench-batch/20260810_010146/resize_bilinear/reports/resizebilinear_eval_20260810_101930.json`
  （passed_cases=13 / failed_cases=7）。
- harness 最终回归：`artifacts/debug/resize_bilinear/run_tests_iter-8/result.json`（passed=True，
  golden_used=True，20 例 diff=0.0）。
- control.json：`best_passed_count=20`、`elapsed_sec=28232`（36000s 预算只用 78%）、
  `max_iterations=30` 只走到 5 次回归即收敛。
- 离线重算脚本结论见本目录 `02-analysis.md` 附录。

## P2 — harness 声称「matches cann-bench eval exactly」但 golden 精度未对齐

`_harness_template.py` CANN 路径注释自称「Matches cann-bench eval exactly」、seed 公式也刻意
复刻 eval（`case_seed = SHA256(case_id)`），但 **golden 参考精度维度缺失**：eval 升 fp64，
harness 原生。契约层（`golden_contract`）只有 `{path, entry, input_type}`，无 precision 字段
→ 无从对齐。DevKit 全仓 grep 无 `golden_precision` / `fp64_cpu` 命中（2026-08-10 实证）。

## 关联
- `precision-debug-dtype-coverage-gap`：harness 只测 fp16 vs eval 测 fp16+bf16 → 同类
  「debug 过 / eval 挂」的覆盖缺口（已修，cases_source=cannbench 同源）。
- `precision-debug-abort-false-positive`：abort 判据误杀自修复型 phase。
- 本问题是「golden 参考精度」维度，独立于 dtype 覆盖与 abort 判据。
