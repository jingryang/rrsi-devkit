# 批跑 20260721-010537-8b790c 问题交接清单

> 生成日期：2026-07-23
> 批跑 ID：`20260721-010537-8b790c`（worktree：`cann-bench-batch/20260721_090523/`）
> 工作流：`self_evolve_op`，目标芯片 A2，5 个算子
> 用途：把批跑暴露的所有问题按「初步根因 / 根因所属 stage / 日志路径」汇总，便于快速分派给对应责任人分析解决。

---

## 一、总览

### 1.1 算子状态总表

| 算子 | exec_id | cann-bench 分 | compile_rt | function | 当前 stage | 状态 |
|---|---|---|---|---|---|---|
| scatter_pa_kv_cache | 20260721-010537-7533c9 | **0 / 100** | 0（20/20 崩） | 0 | finalize | 算子双崩 |
| advance_step_v2 | 20260721-010537-7c6361 | **20 / 100** | 20（能跑） | 0（精度发散） | finalize | 精度未修就放过 |
| manifold_hyper_conn_post | 20260721-010537-e95d13 | **8 / 100** | 8（12 崩+8 精度发散） | 0 | finalize | 部分崩+精度发散 |
| aggregate_hidden_grad | 20260721-010537-308ace | 无 eval | — | — | fix | precision 11 轮未收敛 |
| multi_add_rms_norm_dq | 20260721-010537-bf0757 | 无 eval | — | — | scope_guard | codegen 未完成 |

> cann-bench score 构成：`compilation_score`（编译）+ `compile_runtime_score`（编译+运行不崩）+ `function_score`（精度）+ `performance_score`（性能 vs baseline）。本批 5 算子**无一拿到 function/performance 分**。

### 1.2 问题分级（建议处理顺序）

| 优先级 | 问题 | 根因 stage | 影响面 |
|---|---|---|---|
| **P0** | multi_add codegen 未完成（manifest 缺失） | codegen + dispatch(NPU预检) | 1 算子无法评测 |
| **P0** | precision_debug 第 1 轮 aborted 即 SOFT GATE 放过 | orchestration/workflow | advance_step_v2 / manifold / aggregate 精度没修就进 eval |
| **P1** | scatter 算子 kernel 双崩（tiling EZ1008 + vector 507035） | codegen(算子 kernel) | 1 算子 0 分 |
| **P1** | advance_step_v2 / manifold / aggregate 精度缺陷 | codegen(算法实现) + precision_debug | 3 算子 function=0 |
| **P2** | baseline_source=fallback | cann-bench baseline | perf 评分近似（不影响 crash 诊断） |

---

## 二、算子级问题

### 问题 1 ｜ scatter_pa_kv_cache — 算子 kernel 双崩（0/100）

- **现象**
  - cann-bench：20 个 case 全失败（3 个 `failed` + 17 个 `cascade`），`compile_runtime_score=0`（编译运行阶段即崩，根本到不了精度/性能评测）。
  - precision_debug：跑了 16 轮，**每一轮都是 `EZ1008 tiling execute failed`**（在 `ScatterPaKvCache_1` 就崩，`total_count=0`），中间做了 58 次 `fix` + 57 次 `printf_location` 定位，无一次通过。
- **初步根因**
  - 算子 AscendC 代码有两个独立缺陷，不同输入触发不同崩溃路径：
    1. **tiling 阶段 `EZ1008`**（tiling kernel execute failed）——precision_debug 简化用例触发。
    2. **vector 阶段 `0x4000 / 507035`**（AIVec errcode，`blockIdxCache` 越界 48-bit GM）——cann-bench 完整用例触发。
  - git log 显示一条「打地鼠」修复链（每修一个 crash 就暴露下一个）：`3b59d07`(FRACTAL_NZ→ND 修 EZ9999) → `c444d2a`(加 AutoContiguous 修 GE dimNum 坍缩) → `48b9941`(GetValue 直读 GM 修 0x4000，**但不完整**)。当前停在 `48b9941`，tiling 崩是新暴露的。
  - ⚠️ **纠正一处误判**：曾以为「precision 能跑、cann-bench 崩」，实际 control.json 显示 precision 16 轮也全崩（EZ1008），只是 precision_debug 是 SOFT GATE，崩了也流到 eval。
- **根因所属 stage**：**codegen**（产出的算子 `op_host/*_tiling.cpp` + `op_kernel/*_kernel.cpp` 缺陷）
- **日志路径**
  - precision control（146 条 history，最权威）：`output/20260721-010537-8b790c/20260721-010537-7533c9/artifacts/debug/scatter_pa_kv_cache/control.json`
  - precision 末轮结果：`output/.../7533c9/artifacts/debug/scatter_pa_kv_cache/run_tests_iter-4/result.json`（`error` 字段含 schema/`EZ1008`）
  - cann-bench 评测报告：`cann-bench-batch/20260721_090523/scatter_pa_kv_cache/reports/scatterpakvcache_eval_20260722_234227.json`
  - 算子源（commit `48b9941`）：`cann-bench-batch/20260721_090523/scatter_pa_kv_cache/examples/aclnn_launch_example/csrc/ops/scatter_pa_kv_cache/op_host/scatter_pa_kv_cache_def.cpp`（+ `op_host/..._tiling.cpp`、`op_kernel/..._kernel.cpp`）
- **责任域**：AscendC kernel 开发（tiling + vector 双路径修复）
- **建议**：需人工 ascendc kernel 调试（precision 自动 loop 已证明对该 bug 无效）。可用 `ascendc-dumptensor` / `ascendc-ttklog-debug` skill 做指令级定位。precision_debug 的 57 次 printf_location 产物是定位起点。

---

### 问题 2 ｜ multi_add_rms_norm_dynamic_quant — codegen 未完成（无 eval）

- **现象**
  - precision_debug scope_guard 阶段直接报：**`hard_error: callable_target not available (codegen_manifest missing)`**。
  - state：`codegen_manifest=None`（缺失）、`codegen_iterations=3`、`current_stage=scope_guard`，算子根本无法被调起。
- **初步根因**
  - codegen 没有产出 `codegen_manifest`（精度/评测靠它定位 `callable_target`）。根因是**全批并发 resume 时，从 codegen 续跑的算子在 dispatch 入口被 NPU 预检误杀**：
    - dispatch 入口对「从 codegen 续」也跑 NPU 预检（`torch_npu.device_count()`），但并发下触发 `hdcdrv_connect_wait_reply` 死等（无 timeout），超预检窗口 → 判 NPU 缺失 → halt → codegen 没真正跑完。
    - codegen 是 host 代码生成**不需要 NPU**，预检对它过严。
    - 单算子 retry 时预检不卡（单进程不争用 device_count），但 retry 又撞上 token 401（外部网关，非框架问题）。
- **根因所属 stage**：**codegen**（未完成）+ **batch_runner/dispatch**（NPU 预检对 codegen 续跑过严）
- **日志路径**
  - state：`output/20260721-010537-8b790c/20260721-010537-bf0757/state_snapshot.json`（看 `codegen_manifest`/`codegen_iterations`）
  - precision：`output/.../bf0757/artifacts/debug/multi_add_rms_norm_dynamic_quant/control.json`（`hard_error` 字段）
  - run.log（NPU 预检拦截图，原文 `NPU 运行时缺失，运行将中止`）：`output/.../bf0757/run.log`
- **责任域**：codegen（补产出 manifest）+ dispatch/编排（NPU 预检逻辑放宽对 codegen 续跑）
- **关联**：memory `resume-codegen-npu-prefetch-kill`、`npu-driver-hdcdrv-hang`、`external-infra-not-framework-responsibility`
- **建议**：单独单算子 retry（单进程预检不卡）重跑 codegen → precision；或修 dispatch 让 codegen 续跑跳过 NPU 预检。

---

### 问题 3 ｜ advance_step_v2 — 精度发散 + precision 放弃过早（20/100）

- **现象**
  - cann-bench：`compile_runtime_score=20`（算子能编译运行、不崩），但 `function_score=0`（精度发散，max_diff 超阈值）、`perf=0`。
  - precision_debug：**只跑了 1 轮就 `aborted`**（`failure_type=unknown`），随后 SOFT GATE 直接放行到 cann-bench，精度**从未真正修复**。
- **初步根因**
  - 算子算法实现精度不对（非崩溃，是数值结果错误）。
  - precision_debug 第 1 轮 aborted 即触发 exhausted（SOFT GATE）→ 没进入有效 fix 循环就流到 eval（见框架问题 A）。
- **根因所属 stage**：**codegen**（算法/计算实现）+ **precision_debug**（soft gate 过早放过）
- **日志路径**
  - cann-bench 报告：`cann-bench-batch/20260721_090523/advance_step_v2/reports/advancestepv2_eval_20260721_124415.json`
  - precision control（rounds=1）：`output/20260721-010537-8b790c/20260721-010537-7c6361/artifacts/debug/advance_step_v2/control.json`
  - state：`output/.../7c6361/state_snapshot.json`
- **责任域**：codegen（算法精度）+ precision_debug（流程）
- **建议**：重跑 precision_debug 并确保进入有效 fix 循环（修复框架问题 A 后自动解决）；或人工核对算子算法。

---

### 问题 4 ｜ manifold_hyper_conn_post — 部分崩 + 精度发散（8/100）

- **现象**
  - cann-bench：`compile_runtime_score=8`，即 **12 个 case 编译运行崩 + 8 个 case 能跑但精度发散**（`function=0`、`perf=0`）。`compile_runtime_fail_cases=12`。
  - precision_debug：1 轮 `aborted`（SOFT GATE 放过）。
- **初步根因**
  - 混合缺陷：部分 case 触发算子崩溃（类似 scatter 的执行期错误），部分 case 能跑但数值错误。
  - precision_debug 同样 1 轮放弃（框架问题 A）。
- **根因所属 stage**：**codegen**（部分崩溃 + 算法精度）+ **precision_debug**（soft gate）
- **日志路径**
  - cann-bench 报告：`cann-bench-batch/20260721_090523/ai_infra_manifold_constrained_hyper_connection_post/reports/aiinframanifoldconstrainedhyperconnectionpost_eval_20260721_122709.json`
  - precision control（rounds=1）：`output/20260721-010537-8b790c/20260721-010537-e95d13/artifacts/debug/ai_infra_manifold_constrained_hyper_connection_post/control.json`
  - state：`output/.../e95d13/state_snapshot.json`
- **责任域**：codegen + precision_debug
- **建议**：先定位 12 个崩 case 的错误码（cann-bench case 级 error 在报告里为空，需看 cann-bench run log / subprocess stderr），区分崩因与精度因分别处理。

---

### 问题 5 ｜ aggregate_hidden_grad — precision 11 轮未收敛（无 eval）

- **现象**
  - 停在 precision_debug 的 `fix` 阶段，跑了 11 轮，**每轮 `aborted`**，`max_err=999.0`（哨兵值=算子崩/未跑出结果），`failure_type=runtime`。无 cann-bench eval。
- **初步根因**
  - 算子运行期错误（`max_err=999` 哨兵表明结果根本没算出来，是 runtime 崩而非纯精度发散）。
  - precision_debug 11 轮 fix 未收敛（接近 `max_corrective_cycles=8` / `max_iterations=30` 上限）。
- **根因所属 stage**：**codegen**（算子 runtime 缺陷）+ **precision_debug**（未收敛）
- **日志路径**
  - precision control（11 轮 history）：`output/20260721-010537-8b790c/20260721-010537-308ace/artifacts/debug/ai_infra_aggregate_hidden_grad/control.json`
  - state：`output/.../308ace/state_snapshot.json`（`current_stage=fix`）
- **责任域**：codegen + precision_debug
- **建议**：先确认 runtime 崩的错误码（control.json diagnose phase 有记录），判断是 tiling 崩还是 vector 崩，再决定是人工修还是重跑 precision。

---

## 三、框架级问题（跨算子共性）

### 框架问题 A ｜ precision_debug 第 1 轮 aborted 即 SOFT GATE 放过（P0）

- **现象**：advance_step_v2、manifold 的 precision_debug **都只跑了 1 轮就 aborted**，随后 `precision_debug` node 标 `completed` 流到 cann-bench，精度根本没修 → 这两个算子 `function=0`。aggregate 11 轮也全 aborted。
- **初步根因**
  - `workflow.py:660-671`：precision_debug 的 `exhausted` 是 SOFT GATE（→ `cannbench_adapt`），只有 `scope_guard=upstream` 才 halt。
  - 第 1 轮 `run_tests` aborted（`failure_type=unknown`）就触发 exhausted，没进入有效 fix 循环就放行。这违反 §2.9「自检闭环优先」——门只报问题、修复靠重跑碰运气。
- **根因所属 stage**：**orchestration/workflow**（precision_debug CompositeGroup 退出条件 + soft gate 语义）
- **日志路径**：`src/ascendc_devkit/orchestration/workflow.py:660-671`、`workflow.py:352-354`（exhausted→`__halt__` 注释）、`precision_debug_tree.py`
- **责任域**：编排/框架
- **建议**：评估「1 轮 aborted 即 exhausted」是否过松——若首轮 aborted 属可自修（如 redeploy 后重试），应在 agent 范围内闭环（§2.9），而非放行到 eval 制造虚假通过。

### 框架问题 B ｜ dispatch 入口 NPU 预检误杀 codegen 续跑（P0）

- 见问题 2。全批并发 resume 时 `torch_npu.device_count()` 死等 → codegen 续跑被误判 NPU 缺失 → halt。
- **根因所属 stage**：**batch_runner/dispatch**（`_probe_npu_card_count_bounded` + dispatch 入口预检）
- **日志路径**：`src/ascendc_devkit/application/batch_runner.py`（`_probe_npu_card_count_bounded`/`_probe_via_torch_npu`）、dispatch 入口（看 `run.log` 的 `NPU 运行时缺失`）
- **责任域**：dispatch/编排
- **建议**：codegen 续跑（host 代码生成，不需 NPU）应跳过 NPU 预检，或预检失败时区分「需 NPU 的 stage」与「不需 NPU 的 stage」。

### 框架问题 C ｜ baseline_source=fallback（P2，低优先级）

- **现象**：3 个有 eval 的算子 `baseline_source=fallback`。
- **初步根因**：910B3 → 910b2 映射**已存在**于 worktree baseline_resolver（`line 68`），但 fallback 说明用的是近似 baseline（未真实采集 `910b3.json`），不是映射缺失。
- **根因所属 stage**：**cann-bench** baseline（metadata 采集）
- **日志路径**：`cann-bench-batch/20260721_090523/scatter_pa_kv_cache/src/kernel_eval/utils/baseline_resolver.py:61-81`
- **责任域**：cann-bench
- **影响**：仅影响 `performance_score` 的评分基准（用 910b2 近似），**不影响 crash/精度诊断**。本批 0 个算子有 perf 分，故暂不影响结论。

---

## 四、分派建议速查

| 责任域 | 待办问题 | 关键入口 |
|---|---|---|
| **AscendC kernel 开发** | 问题 1（scatter 双崩）、问题 4（manifold 部分崩）、问题 5（aggregate runtime 崩） | 各算子 `op_host/*_tiling.cpp` + `op_kernel/*_kernel.cpp` |
| **codegen（算法精度）** | 问题 3（advance_step_v2 精度）、问题 4/5（精度发散部分） | 各算子 `generated_sources`（state_snapshot）|
| **codegen（流程）** | 问题 2（manifest 缺失补产出） | `output/.../bf0757/state_snapshot.json` |
| **编排/框架（dispatch）** | 框架问题 B（NPU 预检误杀） | `batch_runner.py` + dispatch 入口 |
| **编排/框架（workflow）** | 框架问题 A（precision soft gate 过早放过） | `workflow.py:660-671` |
| **cann-bench** | 框架问题 C（baseline 采集） | `baseline_resolver.py` + `metadata/` |

> 注：各算子 `output/.../<exec>/run.log` 是该算子整条流水线的权威日志，`state_snapshot.json` 是状态权威；precision 细节在 `artifacts/debug/<op>/control.json`（history 数组，按 phase 时序）；cann-bench 评测在 `cann-bench-batch/.../<op>/reports/*_eval_*.json`。
