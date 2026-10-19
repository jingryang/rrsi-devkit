# 87 — P4 D1 彻底修：harness 共享中间层抽取（L4 实施方案）

> 关联 L1：`batch-20260801-050054-ab7283-issues.md` P4 D1
> 关联上游：`86-batch-20260731-132818-compare-tensors-fallback-impl.md`（F1/F2/F3，本修复的直接前置）

## 改什么（Why + What）

**根因**（L1 P4 D1 已定论）：`_harness_template.py` 的 per-case 循环把共享中间段（get_input / kernel / golden）**逐行内联两份**（CANN 分支 + FALLBACK 分支）。CANN 分支漏调 `get_input`（cann-bench evaluator step 2.5，`evaluator.py:182-202`），把 `[-1, 4368]` value_range 产生的 `-1` 直送 kernel → AICORE OOB → fatal abort。drift 根因 = 一份逻辑抄两份，必然漂移。

**彻底修（§2.5 根治漂移类）**：把共享中间层提成单一定义的函数，模板只留「输入生成 + 比较」两头按 backend 切换。共享步骤构造性保证两路径都走，不可能再漏抄（§2.9）。

## 改动（files）

唯一改源 `src/ascendc_devkit/adapters/npu/_harness_template.py` + 机械重生成 `tests/ut/adapters/fixtures/harness_devkit_golden.txt`。`precision_comparer.py` / `runner.py` / `golden_binding.py` 不动。

### 新增 3 个共享函数（loop 之前，单一定义点）

- **`_golden_core(_inputs, _attrs)`**（`$golden_bind_helper` 后、`_golden_wrap` 前）：golden bind+invoke 单一来源 `_golden_raw(**bind_golden_args(_golden_raw, list(_inputs), _attrs))`。`_golden_wrap` 改为调用它（input-type 归一化 + `_to_np_list` 不动）。
- **`_apply_get_input(_torch_inputs, _attrs)`** + **`_run_kernel(_torch_inputs, _attrs)`**（删 `to_npu` 原位）：get_input 应用（无 get_input 时 no-op）+ list-aware npu-move + kernel 调用 + sync + tuple 归一。

**四把尺子裁定**：get_input + kernel 完全共享（零风险）；golden 只单一化 core bind+call——`golden_input_type`（torch/numpy）是真实维度，强塞统一函数是过度抽象，输入类型归一化 + 输出格式留调用点。canonical form = list of torch CPU tensors。

### 两分支改造

- **CANN 分支**：DataGenerator 后新增 `_torch_inputs = _apply_get_input(...)`（**bug 修复**）；kernel 段 → `_run_kernel`；golden bind+call → `_golden_core`；显示循环 `for o in kernel_out` → `for o in _k_tensors`。
- **FALLBACK 分支**：gen_input 后 bridge（numpy→torch，保留 F3 phrasing）→ `_apply_get_input` → `_run_kernel` → `_to_np_list` → 从 post-get_input torch 回派生 numpy 喂 golden；store 补 `case_id`（与 CANN/no-golden store 对齐，修 latent bug）。

## 验证

- **重生成快照**：复用 `TestHarnessExtractionSnapshot._src()` 调 `_build_test_harness` 覆写 fixture（构造性逐字节相等）。
- **5 个 UT 文件**（`--quick`）：`test_runner_execute` / `test_adapters` / `npu/test_golden_binding` / `test_precision_comparer` / `test_precision_compare` —— **172 passed, 7 skipped**（3.81s）。7 skip = `TestParityCannBench`（缺 cann-bench PYTHONPATH 时 importorskip）。
- **带 cann-bench PYTHONPATH 跑 parity**：6/7 pass；唯一 fail = `test_parity_small_value_stage2`，根因为 devkit `compare_outputs` stage2 比 cann-bench `compare_tensors` 更严（**预存缺陷、与本修复无关**，独立 L4 处理，见 §「独立发现」）。
- substring/AST 契约全保留（`_golden_raw(**bind_golden_args(` 单一来源、`if _get_input is not None:` 重定位、F3 TensorList phrasing、`bind_golden_args` 顶层 FunctionDef、`_ns` top-level、`py_compile` torch_op+pybind）。

## 原则符合性

§1.13（get_input 是 golden 自己的机制，harness 忠实调用，不修正 golden）/ §2.5（删旧副本单一通路）/ §2.9（共享调用点构造性保证两路径都调，不加检查门）/ §1.12（`_apply_get_input` 通用，无算子名）。

## 独立发现（不属于本修复，单独处理）

跑 parity 时暴露 `compare_outputs` stage2 比 cann-bench `compare_tensors` 更严（无 CPU 参考时 small_value/cancel 零容忍 vs cann-bench ratio≤2）。**设计决策 2026-08-01：保持 devkit 严格、不对齐 cann-bench**（防 golden=1e-6 / output=65504 被 ratio 规则误判通过）。落地：`test_small_value_no_cpu_ref_devkit_intentionally_stricter` 固化此有意偏离（断言 dev 更严、cb 更宽）+ `precision_compare.py` 两处特判分支加保护注释防回退。单独 commit，不混入本 P4。

> **⚠️ 已反转（2026-08-10）**：用户拍板「完全对齐 cann-bench 生产评测」——零容忍"有意偏离"撤销。gelu 算子复盘（`session_gelu`）实证零容忍把 4 个正确用例假性判失败（相消桶，CPU 同精度参考自身也脏，devkit 无 native_ref 时误杀）。反转内容：
> - `precision_compare.py` 小值域/相消改恒 ratio≤2 + 补正常值域 #92 同精度兜底；
> - `_harness_template.py` 两路（CANN/FALLBACK）加 fp64 golden + native 参考（`native_output`/`native_refs`）；
> - `test_small_value_no_cpu_ref_devkit_intentionally_stricter` → `test_small_value_no_cpu_ref_aligned_parity`；
> - 防 golden=1e-6/output=65504 假阳性守卫放弃（用户明确接受）。
> 完整方案见 `docs/plan/cannbench-precision-alignment/`。
