# step-77 — batch `20260727_225324` 问题总览（5 算子首跑，0/5 真正成功）

> 性质：**L1 问题清单**（本次 batch 实证 + 产权引用），step 77。self-evolution 线。
> batch_id=`20260727-145339-3dd653`，TS=`20260727_225324`，5 算子首跑，跑完 3.83h（22:53→02:44）。
> **真实结果：0/5 算子 cann-bench eval 通过**。batch 汇总 "2/5 succeeded" 误导（见 Q6）——2 "OK" = workflow done 但 eval 0 分（discovery broken）；3 FAIL = precision_debug 耗尽。
> 用途：本次 batch 暴露的所有问题集中索引，便于"一一分析解决"。每条只记客观事实 + 产权引用，不提方案（方案在各 step / 待分析）。
> 纪律：§1.8——已有文档的问题**只引用不重复事实**；新问题标注待入 `06-problems.md` L1。

---

## batch 概况

- 5 算子、8 卡并发、worktree 隔离；batch 主进程 `ascendc-devkit run --batch`，跑完 13812s（3.83h）。
- design 阶段 4/5 正常（5c3b24 走 step-76 的 review 越界空转→毒性前逃）；codegen/precision 阶段 3/5 失败；eval 阶段系统性 discovery broken。
- 之前的死循环 5c3b24 最终也跑到 eval（0 分），**未崩 batch**——框架对单 agent 进程中断有韧性。

| 算子 | execution | 终态 | 真实情况 |
|---|---|---|---|
| advance_step_v2 | c403fd | "OK" | workflow done，eval `0.00/0.00%`（discovery broken） |
| ai_infra_manifold_constrained_hyper_connection_post | 5c3b24 | "OK" | 同上 eval 0 分——毒性前逃到底（Q1 印证） |
| scatter_pa_kv_cache | b45a5c | FAIL exit 65 | precision_debug 耗尽（00:53 halt） |
| ai_infra_aggregate_hidden_grad | dfd71a | FAIL exit 65 | precision_debug 耗尽（01:00 halt） |
| multi_add_rms_norm_dynamic_quant | 130f8b | FAIL exit 65 | precision_debug 耗尽（01:32 halt） |

---

## 问题清单

### Q1 [已有 step-76，已订正] design-review 越界查 requirement + requirement 缺 golden 自检

- **本次实证**：5c3b24 的 requirement.json `math_formula`（`(Σ)*h_post+h_out`）与 golden.py L94-95（`h_post*h_out+Σ`）不等价，review 越界报 GD-R1（target=requirement/infeasible）+ requirement 自检未拦，错误 design 一路毒性前逃到 eval。
- **产权**：`76-design-review-infeasible-loopback-analysis.md`（L3 已订正：根因=职责分层违反，**非控制流 bug**；空转有界非 10h 死循环；corrective 耗尽后带 known-issue 前逃）；CLAUDE.md §2.9 已加第 5 条"门不越界查上游产物"。
- **状态**：L3 已订正，**L4 待实施**（requirement 自检加 golden 数值等价 + review 收回 CR1/CR2/CR3 范围）。

### Q2 [已有 06-P1 + step-72/75] cann-bench discovery broken（2 "OK" 算子 eval 0 分根因）

- **本次实证**：advance_step_v2 + 5c3b24 均 `CannbenchEvalStage: overall=0.00 pass_rate=0.00%`；WARN `cann-bench discovery broken: ... operators=[], total_cases=0`。
- **真根因（已定位，推翻初始假设）**：**不是** discovery 链路问题——wrapper 在（adapt 已注入）、`_C` 注册在（`torch.ops.cann_bench.<op>` 存在）、`scan_interfaces` 实测扫到 advance_step_v2、06-P1/72/75 **全修且生效**；也**不是** bench_lab 无 baseline——`bench_lab/kernel_bench/metadata/` 有 `910b2/910b3/950pr.json`（比 tasks/metadata 还全，910b3 正好匹配本次硬件）。真因 = `cannbench_eval.py` 调 kernel_eval **没传 `--task-dir`**，默认 tasks_root=`cann-bench/tasks/`（16 个标准算子）；bench_lab 5 个算子 + baseline 在 `<repo_root>/bench_lab/kernel_bench/`（cases.yaml 格式与 tasks 完全兼容），kernel_eval 没被指向那里 → `match_operators`（package_manager.py:645，从 tasks_root 加载）空 → `operators=[]`。WARN 归因（_C stale / redeploy）**错误，曾误导诊断**。
- **产权（订正）**：非 06-P1/72/75（discovery 链路，已修且生效）；本质是 **case 数据通路**——cann-bench eval 的 case 来源（tasks_root）没覆盖 bench_lab 评测集。关联 `06-problems.md` P9/P10（case 通路）。
- **状态：已修复（2026-07-28）**。`cannbench_eval.py` 加 `_resolve_task_dir`（按 `level*/<op>/cases.yaml` 发现 op 所在评测集根：bench_lab/kernel_bench 优先，fallback tasks）+ `_run_eval` 注入 `--task-dir`。验证：① task_loader 实测从 bench_lab/kernel_bench 发现全部 5 个目标算子（PascalCase：AdvanceStepV2/ScatterPaKvCache/AiInfraAggregateHiddenGrad/AiInfraManifoldConstrainedHyperConnectionPost/MultiAddRmsNormDynamicQuant）；② UT 21 passed（含 4 新 `TestTaskDirDiscovery`）。**待办**：① 重跑 batch 实证 eval 不再 operators=[]（heavy_llm，用户决策）；② `_discovery_broken_error` 归因仍笼统（operators=[] 统称 discovery 断，未来真 tasks-无-case 会再误报），待订正为区分"discovery 链路断"vs"tasks 无 case"。

### Q3 [已有 31/33/54] precision_debug 耗尽致 3/5 FAIL(exit 65)

- **本次实证**：scatter/aggregate/multi_add 三算子 `Workflow halted ... quota exhausted at condition 'upstream'`（3 halt 00:53/01:00/01:32）。从 zip 归档提取 precision_debug report/control.json（execution 已归档为 `3dd653.zip`，目录留壳）。
- **订正（推翻"precision_debug 共性 bug"假设）**：precision_debug + scope_guard **工作正确**——3 算子 scope_guard 首轮**全部准确判 SCOPE_UPSTREAM**（"应 halt 归上游"；control.json `history=1` 只 run_tests + `scope_verdict=upstream` 佐证，**没空耗** fix/comment_bisect）。halt 的 `condition='upstream'` 正是 scope_guard 触发；"exhausted correction budget" 是笼统 halt 模板（掩盖根因，关联 Q6）。
- **3 个不同的上游根因**（非精度 bug，各自独立）：
  - **scatter_pa_kv_cache → 非 deploy/_C 缺陷，是 site-packages cann_bench 污染 + harness env 注入不稳定**（深挖订正，2026-07-28，详见 Q8）：原判"scatter 在 `_C.abi3.so`+wrapper 双缺 → deploy 缺陷"**被推翻**——`_C.abi3.so` **含** scatter 注册（md5 worktree=per-op 同二进制 `f94e952fb027ae98f7b1be98ca407b13`；import worktree `_C` → `torch.ops.cann_bench.scatter_pa_kv_cache` 注册成功；m.def schema 正确 plugin.cpp L102-107 `-> (Tensor, Tensor)`）。真因 = 系统 `site-packages/cann_bench`（cann-bench repo 标准算子集 build，op 集 = add/sqrt/moe_re_routing，**无 scatter/advance_step_v2**）污染——precision_debug harness 的 `__import__('cann_bench')`（harness.py L271）**没确定性注入 per_op_python_dir**，运行时 sys.path 落 site-packages → not registered。铁证：scope_guard 说的"only add/sqrt/moe_re_routing"**正是 site-packages cann_bench 的 op 集**（实测 site-packages `scatter_pa_kv_cache=False`）；advance harness **case 真跑**（run_tests_iter-13 报 IndexError，跑 19 轮）= advance 的 agent 让 harness 解析到 per-op cann_bench，scatter 的落 site-packages——**同模板 harness、不同结果 = env 注入靠 LLM 不稳定**。**wrapper 缺失**（per-op `__init__.py` 无 scatter wrapper，adapt 没注入）是另一个独立 bug，但 harness 走 `torch.ops` Dispatcher 不经 wrapper，**不是 not registered 的直接原因**。
  - **aggregate_hidden_grad → codegen 缺陷**：20/20 failed，11 nullptr + 9 dtype_mismatch，`AclNN_Parameter_Error(EZ1001)`（算子代码 bug，coder 产出问题）。
  - **multi_add_rms_norm_dynamic_quant → test_design 缺陷**：cases.yaml shape schema 错（Tensor[] 嵌套编码，harness 不认），0/0 cases ran（关联 step-55 P5/P6 harness 用例形态）。
- **产权（订正）**：非 31/33/54（precision-debug 本身表现正确）；3 上游根因分别归 deploy/codegen/test_design。
- **状态（2026-07-28，step-80 已修）**：3 halt 根因均已修——① scatter → **Q8** 已修（harness 烘 `sys.path.insert(0, per_op_python_dir)` 确定性压过 site-packages）；② aggregate → codegen 加 plugin `m.def` inputs vs `manifest.inputs` 自检门（Phase E，warn 留信号，实测在 aggregate 真实 plugin 抓到 phantom mask）；③ multi_add → runner `_validate_case_form` 放宽 DYNAMIC/`Tensor[]` 嵌套 `list[list[int]]`（Phase A3，**框架缺陷**——harness 模板 L223 本支持嵌套归一化，前置校验器是唯一堵点）。precision_debug 本体无需修。**ST/UT 覆盖（step-80）**：校验器——`test_runner_contract.py` 5 个 DYNAMIC 用例（接受/拒 nested、多 tensor、REQUIRED 仍拒、无 op 回退 REQUIRED、非 int 内层拒）；harness 生成——`test_runner_execute.py::TestHarnessDynamicNestedShape`（3 用例，`_build_test_harness` 对 DYNAMIC nested shape 不再 raise 且嵌套字面量正确 inline）。**不补 heavy NPU ST**：纯 Python 逻辑（校验器+模板归一化），无简单 Tensor[] kernel 可部署（仅复杂 multi_add），强造 heavy=巨量脚手架换边际价值（§3.11 不强造、§3.9 仅 SDK/agent 真实行为链路需 real ST）。

### Q4 [已有 step-55 P9 模式] control.json missing `consecutive_aborts`（precision agent contract 不一致）

- **本次实证**：`[WARN] [PD-CONTRACT] control.json missing 1 required key(s): ['consecutive_aborts']. Auto-initializing to safe defaults` 出现 ≥4 次（00:16/00:41/00:52/01:30）。
- **产权**：`55-precision-debug-review-problems.md` P9（`_CONTROL_REQUIRED_KEYS` 滞后：漏登记 `phase_counter/run_iter_counter`）+ `55-precision-debug-review-fixes-impl.md`。
- **状态（2026-07-28，step-80 已修）**：确认 step-55 P9 修复**确实漏了** `consecutive_aborts`（只同步 phase_counter/run_iter_counter）。已补：`init-checkpoint.py` 写 `"consecutive_aborts": 0`（required_keys L267 + defaults L313 已有，init-checkpoint 写入是第四部分）。UT 守护（`test_init_checkpoint_contract.py`）。

### Q5 [部分已有 06 + step-16] cannbench_adapt/eval/finalize "produced no actions with no skip_reason"

- **本次实证**：多 stage 后跟 `[WARN] Stage 'self_evolve_op/<stage>' produced no actions with no skip_reason (possible bug or misconfigured stage)`，出现在 cannbench_adapt / cannbench_eval / finalize（advance_step_v2 日志可见）。
- **产权**：`06-problems.md` + `16-docgen-deadlock-impl.md` 有 "no actions" 相关讨论，但**本场景（cannbench_adapt/eval/finalize 终态 stage）是否同一模式待确认**。
- **状态（2026-07-28，step-80 已修）**：**确认是 runner 误报**——cannbench_adapt/eval/codegen_init 是设计无 agent stage（`actions() return []`，工作在 `transition()`），finalize 条件空。runner.py L487 对"actions 空但无 skip_reason"报 WARN（设计是 intentional-empty→○ skipped / unintentional→⚠，但这些 stage 没实现 skip_reason）。已修：4 stage 加 `skip_reason`（复用 `design_substages.py` L2210-2225 + `perf.py` L330-334 范式）。UT 守护（`test_deterministic_stage_skip_reason.py`）。

### Q6 [部分已有 39/70] "2/5 succeeded" 汇总误导（workflow done ≠ 算子正确）

- **本次实证**：batch 汇总标 `2/5 succeeded`，但 2 "OK" 算子 cann-bench eval 均 0 分（discovery broken）。汇总不区分 "workflow done" vs "eval meaningful"，致 "succeeded" 严重高估真实成败。
- **凭什么说是问题**：cann-bench 是终态 loss、NO loopback、eval 失败不阻断 done（step-70 §07 决策，**设计如此**）；但 batch 汇总的可观测性应反映 eval 实际分数/失败，否则 "succeeded" 误导（本次 0/5 真正 eval 通过，汇总却报 2/5 succeeded）。
- **产权**：`70-training-loop-and-confirmation-analysis.md`（cann-bench NO loopback 决策）+ `39-soft-stage-timeout-impl.md`；**汇总可观测性维度可能新**。
- **状态（2026-07-28，step-80 已修）**：`RunOutcome` 加 `eval_score`/`eval_pass_rate`（`_dispatch_one` 从 `state_snapshot.json` 的 `eval_result` dict 直读，try/except 兜底 None）；`summary` 改 `X/Y workflow-done, Z/W eval-passed`（`overall_score > 0` 判 passed，复用 `loss_aggregator.py` L48 阈值）+ 每行 `eval=分数/通过率`。**不改** `ok`/done 语义（cann-bench NO loopback，step-70 §07）。UT 守护（`test_batch_runner.py::TestBatchSummaryEvalVisibility`）。

### Q7 [已有 记忆 step-61] batch log 无 op 归属 / stream 捕获不全（诊断教训）

- **本次实证**：batch 总日志 `agent_stream` 只捕获 requirement-analyst；一度误判"5 算子都在 requirement 阶段"，实际早已进 design。真相在 per-op run.log `stage_iteration` 序列。
- **产权**：记忆 `opencode-backend-transcript-provenance-gap`（step-61，AU-6/7）。
- **状态（2026-07-28，step-80 层1+层2 已修）**：层1 `kernel/runner.py` `_execute_actions` spawn 回填 `stage_name=action.stage_name or self._current_stage_name`（一次性覆盖 requirement/codegen/smoke/perf 等忘设 stage_name 的 stage）；层2 `_shared.format_attribution` 去掉空 `stage_name` 短路（op 非空时仍产出 `[op]`，防御纵深）。层3（batch progress_callback）**可选跳过**——核心 op 归属已由层1+层2 解决，D3 边际价值低且 op 归属在 dispatch 上下文不确定。UT 守护（`test_runner_stage_attribution.py` + `test_shared.py`）。**不补 heavy batch ST**：归因是纯 Python 日志格式（两层均 UT 覆盖），跑整 batch 验一个日志前缀=高成本低价值（§3.11 不强造 heavy）。

### Q8 [新发现，2026-07-28] precision_debug harness 漏 per-op PYTHONPATH 确定性注入 + site-packages cann_bench 污染

- **本次实证（深挖 Q3 scatter 根因发现）**：scatter_pa_kv_cache precision_debug 报 `torch.ops.cann_bench.scatter_pa_kv_cache` not registered，scope_guard 误判"_C 缺 scatter → deploy 缺陷"。深挖（md5 + import 实验）证实 _C **含** scatter，真因是 harness `__import__('cann_bench')`（harness.py L271）落到系统 `site-packages/cann_bench`（cann-bench repo 标准算子集 build，无 scatter）。
- **凭什么说是框架缺陷（非纯环境问题）**：① deploy `_smoke_script`（`deploy.py` L387/406/425/433）**正确**隔离——硬编码 `sys.path.insert(0, per_op_python_dir)`，smoke pass；precision_debug harness **没等效确定性注入**（run_tests prompt `precision_debug_substages.py` L1518+ 只传 context，env 靠 LLM agent 跑 Bash 时自觉）→ 不稳定。② cannbench_eval（`cannbench_eval.py` L246-252 `_resolve_cann_bench_pkg_root` + `pypath_parts`）也确定性注入——**precision_debug 是唯一漏的**。③ advance/scatter 同模板 harness、同不执行 `_cann_src` 分支，advance import 对、scatter 错 = env 注入靠 LLM 不稳定（§1.10：横切控制流不用机制特征/LLM 自觉代理）。
- **诊断教训（§1.11）**：scope_guard 重跑 harness 复现 not registered（"实际产出"），但产出环境本身污染（落 site-packages），产出反映环境污染非 _C 缺陷；强反证（md5 + import 实证 _C 有 scatter）应优先于弱探测（受污染的 not registered）。scope_guard 据 `__init__.py` wrapper 推断"_C 也缺 scatter"是二阶误判。
- **产权**：新问题（precision_debug harness env 隔离）。关联 §1.7（资源路径自闭环 / per-op 隔离）、§1.10（横切控制流确定性）、deploy `_smoke_script`（正确范式）、cannbench_eval `_resolve_cann_bench_pkg_root`（正确范式）。
- **状态（2026-07-28，step-80 已修）**：A1 harness 模板（`_build_test_harness` ~490 行 `lines=[...]` 字符串列表）提取到 `adapters/npu/_harness_template.py`（`string.Template`，12 个 `$var`，snapshot 测试逐字节守护行为零变更，runner.py 1128→640 行）；A2 模板烘 `sys.path.insert(0, per_op_python_dir)` + `[harness] cann_bench.__file__` 探针（自包含抗 agent 绕过、import 错版本可观测，复用 `_smoke_script` 范式）。site-packages 全局 cann_bench 是环境污染物（建议清，但框架现已防御、不依赖环境干净）。**ST/UT 覆盖（step-80）**：源级——`TestHarnessExtractionSnapshot`（4 用例，含 `sys.path.insert` 注入/省略 + probe 非 `{` 前缀）；运行时——`tests/st/test_npu.py::test_harness_imports_per_op_cann_bench_not_site_packages`（`@npu @slow`，读 `run.log` 断言 probe `[harness] cann_bench.__file__` 指向 per-op deploy 目录、非 site-packages）**已跑过（2026-07-28，87s）**——deploy 重建 cann_bench（add/sqrt）→ smoke pass → harness 跑 → probe 证实 import 落 per-op。**非 heavy_llm**（路径无 LLM——deploy+subprocess，§3.5 marker=运行时依赖）。**env 前置**：cann-bench 仓 `examples/.../csrc/ops/moe_re_routing`（非预置、A2 Membase MoE 算子，commit 21c71d2）编译失败致 `deployed_add` smoke 不过→此前全 `TestNPURunnerRealExecution` 跳过；已物理删除该 op 源目录（cann-bench 仓内 unstaged，未提交）+ 清 build/build_py/dist 产物，CMake GLOB 重建后仅 add/sqrt 编译通过。UT 守护（`test_runner_execute.py::TestHarnessExtractionSnapshot`）。

---

## 一一分析的建议顺序（按阻塞面 + 依赖）

1. **Q2（cann-bench discovery）**：最先——它让 2 个 "OK" 算子 eval 全 0 分、且阻塞所有算子的 eval 可信度；06-P1 标 ✅ 但本次仍 broken，需查 72/75 修复是否落地。
2. **Q3（precision_debug 耗尽）**：3/5 FAIL 主因，决定 codegen→precision 链路健康度；需逐算子看 verify/transcript 区分 build vs 精度失败。
3. **Q4（consecutive_aborts）**：step-55 P9 模式复现，可能小修（登记 required key），但先确认 55 修复为何没覆盖。
4. **Q6（汇总误导）**：可观测性——影响判断真实成败，修改面小（汇总输出层）。
5. **Q5（no actions）**：次要 stage 行为，先确认是否设计如此。
6. **Q1（design-review）**：L3 已订正，L4 实施（独立于本 batch 其他问题）。
7. **Q7（batch log）**：已知 gap，长期。
8. **Q8（harness env 隔离）**：precision_debug 漏 per-op PYTHONPATH 确定性注入（scatter not registered 误判的真因）；L4 待修（比照 `_smoke_script` 确定性注入 + harness 打印 `cann_bench.__file__` 可观测）。

---

## 句柄

- batch 总日志：`logs/batch_20260727_225324.log`（29801 行）
- batch_id：`20260727-145339-3dd653`
- 各算子 execution：`output/20260727-145339-3dd653/{130f8b,5c3b24,b45a5c,c403fd,dfd71a}/`
- eval 报告：`cann-bench-batch/20260727_225324/<op>/reports/*_eval_*.json`
- 续跑：`RESUME=1 bash scripts/batch_self_evolve.sh`
