# step-84 — `_C`/eval "空心" 为何反复未根除 + Q12 澄清（func 实为 30 非 0，是日志假信号）— 方案分析（L3）

> 性质：**L3 方案分析**（根因 + 选项 + 推荐，待拍板后冻结）。self-evolution 线，step 84。
> 上游 L1：`84-batch-205112-issues-summary.md` Q12（advance_step_v2 eval）。用户问："`_C` 问题已改多次为何一直无法根除？"
> 关键结论前置：**本批 advance_step_v2 的 `_C` 实际已修复、精度实际通过（func=30）**；"反复未根除"的表象来自 ① 三个不同失败模式共用 "`_C`" 一个词、② DevKit 日志两处假信号（`unreachable` WARN 是正常自愈、`func=0.00` 是 `_parse_report` 硬编码 0）。真正的框架 bug 是**日志可诊断性**，非 `_C` 本身。
> 纪律：§1.8——事实产权在 L1，本文记根因（L3）+ 决策。

---

## 0. 一句话

"`_C` 问题反复未根除"是**词汇混淆 + 日志假信号**制造的错觉，不是一个没杀死的 bug。三个**不同失败模式**（BISHENG 编不出 / site-packages 污染 import / build 未触发）被同一个 "`_C`" 词概括，每次修复各杀死其一，下批换一个冒头就像"没修好"。本批 advance_step_v2 的 `_C` **实际已修**（`/lib64/libc.so.6` 符号链接已建=doc-83 环境修复生效，eval_prepare 重编成功），**精度实际通过**（授权报告 JSON `function_score=30/compilation=20/overall=50/pass_rate=1.0/mismatch=0`）。我先前判的"空心 eval / 0/5"**是被 DevKit 日志误导**——`cannbench_scorer.py:321-323` 把 func/compile/perf **硬编码成 0** 再打印，`golden_used:false` 来自另一条 DevKit smoke 展示路径（非 cann-bench 真精度）。**唯一真为 0 的是 performance_score**（`_C` 反作弊工具没跑成 perf 计时）。

---

## 1. 事实（L1 产权，本文补代码/报告核实）

### 1.1 Q12 澄清——func 实为 30，不是 0（我先前判断已订正）
- **授权源=eval 报告 JSON**（`cann-bench-batch/20260730_205112/advance_step_v2/reports/advancestepv2_eval_20260731_005919.json`）：`function_score=30.0, compilation_score=20.0, performance_score=0.0, overall=50.0, passed_cases=20/20, pass_rate=1.0, output_results[0].passed=true, mismatch_count=0, total_count=16956`。**cann-bench kernel_eval 内部用真 golden 比对且通过**。
- **DevKit 日志的 `func=0.00 compile=0.00` 是假信号**：`cannbench_scorer.py:321-323` `_parse_report` 硬编码 `compile_score=function_score=performance_score=0.0`（注释 :320 "not exposed in report JSON; weighted overall is authoritative"），只信 `overall_score`，然后 :345-347 把这三个 0 打进 run.log。**读日志的人（包括我）被这三个 0 误导成"精度没过"。**
- **`golden_used:false / golden_first10:[] / no_golden_reference` 也是假信号**：它来自 **DevKit smoke/adapt harness**（`_harness_template.py:194 golden_used=golden_fn is not None`；:576 `no_golden_reference`），deploy 阶段跑来确认 kernel 可执行的**展示路径**，该路径没给 advance_step_v2 接 golden，故诚实打印空 golden + diff=-1。**非评分精度结果**。真精度在 cann-bench kernel_eval 子进程内（用它自己的 golden）。
- **唯一真 0 = performance_score**：`baseline_perf_us=0 / avg_speedup=0`（无 perf baseline + `_C` 反作弊工具没跑成计时），这才是 `_C` 不可达的**真实且唯一**后果。

### 1.2 `/lib64/libc.so.6` 已修（本批 `_C` 实际编出来了）
- `ls -la /lib64/libc.so.6` → `-> /usr/lib64/libc.so.6`（符号链接，建于 Jul 30 15:39=doc-83 remediation）。BISHENG lld 缺 libc 的编译阻塞在本机**已解除**。
- run.log 00:57:39 `WARN cann_bench_utils unreachable; running eval_prepare (2 steps)` → **是自愈触发，不是失败**：`CannbenchScorer._ensure_eval_prepare`（scorer.py:181）precheck `import cann_bench_utils` 失败 → 跑 profile 的 build+install → **重 precheck 返回空=build 成功**（scorer.py:225），eval 才真跑（00:59→01:10 产出真报告）。若仍不可达会短路 `EvalResult(0.0)`+infra reason（scorer.py:99-103），不会有真报告。

### 1.3 "`_C`" 词下的三个不同失败模式（历史核实）
| 模式 | 失败类型 | 归属 | 既有修复 |
|---|---|---|---|
| (a) BISHENG lld 缺 `/lib64/libc.so.6` → `_C` **编不出** | COMPILE | 环境前置（非框架 bug） | `verify_env` 自检 + `ln -s` + doc-83 |
| (b) harness `__import__('cann_bench')` 落 site-packages（无目标算子）| IMPORT/PYTHONPATH | 框架（Q8）| step-80 `_harness_template.py` 烘 `sys.path.insert(0, per_op_python_dir)` + probe |
| (c) `cann_bench_utils` eval 时未 build/install | BUILD-NOT-TRIGGERED | 框架 | step-82 `_ensure_eval_prepare`（scorer.py:181）|
| (d) torch_npu↔CANN ABI（500001/561103）| runtime init | 环境 | 配套 pairing（记忆）|
| (e) symbol/wrapper drift（discovery operators=[]）| discovery | 框架 | step-71/75 |

三个是**不同失败模式**（COMPILE vs IMPORT vs BUILD-NOT-TRIGGERED），共用 "`_C`"/"ImportError"/"unreachable" 词汇。

---

## 2. 根因（L3 产权）——为何"反复未根除"（META 答案）

**不是一个没杀死的 bug，是三重错觉叠加：**

1. **(i) 跨不同根因打地鼠**（主因）：(a)(b)(c) 三个无关缺陷共享 "`_C`/unreachable/ImportError" 字符串。每次修复正确杀死**其一**，下批**另一个**冒头，且 memory/日志复用同一词汇 → 读起来像"没修好"。本批既非(a)（libc 已修）也非(b)（step-80 已烘 PYTHONPATH）也非(c)失败（eval_prepare 自愈成功）——**本批 `_C` 根本没失败**。
2. **(ii) 一个成员是环境前置、非框架能修**：(a) BISHENG lld + 缺 libc，仓只能 fail-loud + `verify_env` 自检 + 建符号链接，不能"根除"环境缺失本身。本机已 remediate。
3. **(iii) 验证缺口 + 日志假信号**：step-80/82/83 的"已修"由 targeted UT + 推理验证，**没跑 heavy_llm 端到端**，故直到本批才对真 run 复验；而 DevKit 日志两处假信号（`unreachable` WARN 正常自愈被读成失败、`func=0.00` 硬编码被读成精度挂）**持续再生"复发"的表象**——真报告 JSON 与日志矛盾时，人只看到日志。

**∴ 真正待修的框架 bug 只有一个，且不是 `_C`——是 `_parse_report` 的日志可诊断性缺陷**（§1.3/§1.11 诊断看实际产出）：它制造与授权报告矛盾的"func=0/空心 eval"假信号，让每次正常的 eval 都看着像失败。`_C` 三模式各自的修复实际有效。

---

## 3. 选项（四把尺子）

### 修复 P1（真框架 bug）：`_parse_report` 暴露真实分维度分数，消除假信号
- `cannbench_scorer.py:321-323` 别再硬编码 `compile/function/performance=0`——从报告 JSON 的 `operators[0].{compilation_score,function_score,performance_score}` 读真值（本批报告**明确有** `function_score:30/compilation_score:20`）。日志 `func=/compile=/perf=` 打印真值。
- **四把尺子**：可诊断（§1.11 日志=实际产出，不再假 0 误导）、可维护（消除"日志 vs 报告"矛盾这一长期误诊源）、可扩展（任何算子的分维度可见）、架构合理（scorer 忠实转述报告，不自造 0）。**风险**：报告 schema 字段名需稳定（`function_score` 等）——本批报告已确认字段在；若旧版报告无这些字段，缺失回退 0 + 标记"未暴露"而非静默 0。**推荐，面小必修。**

### 澄清 P2（perf=0 的真后果）——**订正：不是 `_C` 没跑 perf，是 cann-bench baseline 锚点解析 bug**
- **先前判断错误**：曾记 "perf=0 是 `_C` 反作弊工具没跑成 perf 计时"。**实证推翻**——报告 `operators[0].cases[0].op_times.device_kernels.aclnnAdvanceStepV2 = 151.48us`：**kernel 真机执行 + profiling 均成功**，`_C` 计时**跑成了**。
- **perf=0 真因（三段实证，全在 cann-bench 侧）**：
  1. 该算子 baseline **存在**于 `bench_lab/kernel_bench/metadata/910b3.json`（`advance_step_v2` case1 `baseline_perf_us=117.64`）。
  2. eval 时硬件解析 fallback 到 `DEFAULT_HARDWARE=910b2`（报告 `device=""`，`DeviceManager.get_device_name()` 未拿到型号），而 **`910b2.json` 的 `level2` 为空**，无 advance_step_v2 → `BaselineStore.get_perf()` 返回 0。
  3. 更根因：`baseline_resolver.py:PLATFORM_ALIAS` **无任何 key 映射到 "910b3"**（只有 910b2/910b1/310p/950pr）。有人把"新增 14 个 vector 算子"的 baseline 收进 `910b3.json`（`_metadata.source` 明写），却无法被自动检测解析 → 这 14 个算子的 baseline 全是**孤儿数据**，自动 eval 一律 perf=0。
  4. → `baseline_perf_us=0` → `scoring.aggregate_eq4` 按 §3.3「缺锚点按 0 计入性能项」→ `performance_score=0`（精度项不受影响，故 func=30 保持）。
- **归属**：cann-bench 上游 bug（alias 缺 910b3 + 默认平台 910b2 缺这批算子 baseline）。**DevKit 不为它耦合兜底**（§1.13 下游忠实消费 + 用户点 3「不为其他仓 bug 做耦合修改」）；正解在 cann-bench 产权方（补 PLATFORM_ALIAS 910b3 映射 / 修 device 检测 / 或把 baseline 并进正确平台文件）。cann-bench 本地已 `reset --hard origin/master`，不擅自本地改。
- **DevKit 侧唯一关联修 = P1（G1，已实施）**：修前日志把 func/compile/perf 全硬编码 0，**无法区分**"perf 因缺 baseline 真为 0" vs "整体没跑"。P1 修好后 perf=0 与 func=30 如实并列，此"大问题"才可见。

### 澄清 P3（环境前置不归框架）：(a) libc/BISHENG 保持 fail-loud + 自检
- 已有 `verify_env` 自检 + doc-83；本机已建符号链接。**不新增**，符合"外部基础设施故障不归框架修，框架只不误报"（记忆 `external-infra-not-framework-responsibility`）。P1 修好后即便 `_C` 真编不出，日志会如实显示 perf=0 + `unreachable` 而非污染 func。

---

## 4. 推荐 + scope

**推荐只修 P1**（`_parse_report` 暴露真实分维度分数）——这是"`_C` 反复未根除"表象的**唯一真 DevKit-侧 bug**（日志假信号），面小、确定、通用。**P1 已实施**（`cannbench_scorer.py:318-338` 从 `operators[0]` 读真 `compilation_score/function_score/performance_score`，缺字段回退 0；UT `test_parse_report_exposes_real_dimension_scores` + `test_parse_report_missing_dimension_fields_fall_back_to_zero`，21 pass）。P2 订正为 cann-bench baseline 锚点 bug（归上游，DevKit 不兜）、P3 是环境前置（不新增）。

**Q12 订正**：先前 L1 记的"advance_step_v2 空心 eval / 0/5 真正通过"**部分错误**——advance_step_v2 **精度实际通过**（func=30，cann-bench 真 golden 20/20），只是 **perf=0**（cann-bench baseline 锚点缺失，非 `_C` 没跑）+ **DevKit 日志假 0 误导**。真实 tally 应为 **1/5 精度通过（advance_step_v2，perf 缺）+ 4 halt**，非 0/5。需回改 L1 Q12 + 标题 + memory。

**scope**：本 L3 覆盖 Q12 + "`_C` 为何反复"。不含其余 Q。与 Q4（epsilon，已修）、边界/收敛/validate 三 L3 正交。

---

## 5. 待用户拍板

- **G1**：P1 = `_parse_report` 从报告 JSON 读真 `function_score/compilation_score/performance_score` 打日志，弃硬编码 0——**✅ 已实施**（用户「其他按推荐来」认可，UT 21 pass）。
- **G2**：Q12 订正——advance_step_v2 **精度实际通过（func=30）**，本批真实 = 1 精度通过（perf 缺）+ 4 halt，非 0/5 空心——**✅ 已回改 L1/memory**。
- **G3（订正）**：perf=0 **不是** `_C` 没跑 perf（kernel 已计时 151.48us），是 **cann-bench baseline 锚点解析 bug**（910b3.json 孤儿 baseline + PLATFORM_ALIAS 无 910b3 + 默认 910b2 缺该算子）。**归 cann-bench 上游产权方，DevKit 不耦合兜底**（用户点 3 + §1.13）。DevKit 侧已由 G1 让 perf=0 如实可见。**需否知会 cann-bench 维护者补 910b3 alias / 修 device 检测？**（唯一残留决策，DevKit 侧无动作）

---

## 6. 句柄

- L1：`84-batch-205112-issues-summary.md` Q12（✅ 已订正）
- 报告 JSON（授权源）：`cann-bench-batch/20260730_205112/advance_step_v2/reports/advancestepv2_eval_20260731_005919.json`（func=30/compile=20/perf=0/overall=50/pass=20/20；`cases[0].op_times.device_kernels=151.48us`=kernel 已计时）
- DevKit 代码：`adapters/evaluation/cannbench_scorer.py:{99-103 infra 短路,181/225 _ensure_eval_prepare 自愈+重precheck,318-338 ✅ 已改读真分维度,344-349 打日志}`、`adapters/npu/_harness_template.py:{194 golden_used,576 no_golden_reference}`（smoke 展示路径，非评分精度）
- **cann-bench baseline bug 句柄**：`src/kernel_eval/utils/baseline_resolver.py:61 PLATFORM_ALIAS`（缺 910b3）、`baseline_store.py:246 get_perf`（fallback 到 910b2 缺该算子 → 0）、`benches/cann_loader.py:244-253`（device 检测失败 fallback DEFAULT_HARDWARE）、`bench_lab/kernel_bench/metadata/910b3.json`（孤儿 baseline，14 算子）
- 环境：`/lib64/libc.so.6 -> /usr/lib64/libc.so.6`（Jul 30 15:39 建，doc-83）
- 关联：记忆 `cannbench-utils-bisheng-libc-lib64`（只挂 perf 不挂精度，本批证实）、`precision-debug-harness-env-pollution`（step-80 模式 b）、`external-infra-not-framework-responsibility`、`74-perf-gate-false-green-analysis.md`、step-82（eval_prepare 自愈，模式 c）
