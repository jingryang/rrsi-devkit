# step-84 — batch `20260730_205112` 问题总览（5 算子首跑，4/5 halt，1 精度通过但 perf 缺 + 日志假信号）

> 性质：**L1 问题清单**（本次 batch 实证 + 产权引用），step 84。self-evolution 线。
> batch_id=`20260730-125126-091882`，TS=`20260730_205112`，HEAD=`ce4b6423`（v0.2.0，req-analysis 全维度锚定 golden + 去算子名锚点）。
> 后端 opencode + glm-5.2；芯片 A2/`ascend910b`，UB=192KiB，vector_core=40；`workflow_timeout_sec=36000`，codegen agent 硬帽 `3600s`。
> **真实结果：4/5 算子 halt（scatter/manifold/aggregate/multi_add）；advance_step_v2 跑完全流程且精度实际通过（cann-bench 真报告 func=30/compile=20/overall=50/20-20 cases，仅 perf=0 因 `_C` 计时未跑）→ 1/5 精度通过 + 4 halt**。（注：run.log 的 `func=0.00` 是 `cannbench_scorer._parse_report` 硬编码 0 的**假信号**，非真精度；详见 Q12。）
> 用途：本次 batch 暴露的所有问题集中索引，便于"一一分析解决"。每条只记客观事实 + 产权引用，不提方案（方案在各 step / 待分析）。
> 纪律：§1.8——已有文档的问题**只引用不重复事实**；新问题标注待入 `06-problems.md` L1。
> 观察方法说明见 `batch-runlog-20260730_205112.md`（含早期误判纠正：run.log tail 在 halt 后不更新、stage-done grep 模式漏后缀，权威源=events.jsonl + WARN/ERROR/halt）。

---

## batch 概况

- 5 算子、8 卡并发、worktree 隔离、`design_concurrency=5`；脚手架（脚本/worktree/manifest/加载期校验/design 全 27 stage）**全绿**，无 FATAL、无 `no_proto`/`missing_task_files`。
- **失败全部集中在 codegen 及其下游**（4 个 halt 均在 codegen/precision）。对照上批 214817/db504b：脚手架债已清（memory `batch-214817-scaffolding-fixed`），本批暴露的是 **codegen 生成 kernel 的运行时质量** + **一个框架契约缺陷** + **设计阶段 loopback 效率/闭合缺陷**。
- 设计阶段 loopback **未直接导致任何失败**（4 个 halt 都更晚），但是真实的效率与闭合缺陷，且部分**疑似 step-78 gate-scope 修复的回归/盲区**（step-78 在本批 HEAD 之前已合入）。

| 算子 | execution | 终态 | 停在哪 | 真因归类（详见对应 Q） |
|---|---|---|---|---|
| advance_step_v2 | `316462` | ✓ 精度通过（func=30，perf=0 因 `_C`） | 全流程跑完 | Q12（`_C` 未复发；run.log func=0 是 scorer 硬编码假信号） |
| scatter_pa_kv_cache | `37b9e2` | ✗ halt | codegen **3600s 硬超时** | Q1（codegen 慢收敛被切 + 缺 InferShape） |
| ai_infra_manifold_constrained_hyper_connection_post | `d7237a` | ✗ halt | codegen deploy_failed | Q2（kernel runtime OOB：DataCopyPad GM 地址/MTE 对齐） |
| ai_infra_aggregate_hidden_grad | `e66710` | ✗ halt | codegen deploy_failed | Q3（kernel runtime OOB：EnQue/DeQue 生命周期失衡） |
| multi_add_rms_norm_dynamic_quant | `facf2e` | ✗ halt | precision_debug（upstream） | Q4（框架契约缺陷：epsilon str vs float） |

---

## 问题清单

### A. codegen / precision 失败（4 算子 halt）

### Q1 [新发现] scatter codegen 3600s 硬超时——慢收敛被切在"最后一修"前 + 缺 InferShape 注册

- **本次实证**：`ascendc-coder` turn 352 撞 `exceeded 3600s hard cap`，22:33:15 被杀，codegen 达 max iterations(40) 未满足 output_contract（缺 `generated_sources`/`build_result`/`deploy_result`），15 文件作为 partial 快照落 `artifacts/codegen/`。
- **不是 hang，是慢收敛**：coder 爬了一条 ~7 级错误阶梯，每修一个撞下一个（各为不同错、非同一错震荡）：host 编译 `GetData()` 模板推导失败 → `opbuild ... The dtype size of input[0] ... is 0`（build_ascendc.log，6 次，21:43–21:47）→ `DataCopyPad` 参数类型配对（`DataCopyParams` vs `DataCopyExtParams`）→ **kernel 模板派发**（`no matching function for call to 'scatter_pa_kv_cache_2306_tilingkey'`，`ASCENDC_TPL_DTYPE_DECL` vs `ASCENDC_TPL_DATATYPE_DECL` 的 6 路 kv-dtype×slot-dtype 实例化，21:55–22:09 耗时最长 ~15min）→ plugin `const_cast<char*>` 右值绑定 + `'converted_params' is not captured` → manifest 缺失（`codegen_manifest.callable_target missing`）→ `FRACTAL_NZ` 无 bin（`Cannot find any bin for input 1 [storage format 2]`，改 OpDef 为 `FORMAT_ND`）。
- **最终墙**（smoke.log）：`key_cache must be 4D ..., got 1 dims [scatter_pa_kv_cache_tiling.cpp:78]` → `Failed to execute tiling (EZ1008)`。张量真为 4D `[17,4112,8,16]`，但 tiling 的 `GetStorageShape().GetDimNum()` 返回 1。coder 22:32（被杀前秒级）正确诊断为**缺 InferShape 注册**，开始写 `scatter_pa_kv_cache_infershape.cpp`，22:33:15 被硬帽杀在修复中途——**离成功约 1 修**。
- **凭什么说是问题**：① 主导是 codegen 实现摩擦（先写码、靠编译错误考古契约；两处自伤最烧时间：6 路 `ASCENDC_TPL` dtype 实例化 + 缺 InferShape）；② 3600s 硬帽把 agent 切在已有正确诊断、正在落最后一修的瞬间（关联 Q11）。参考算子 `moe_re_routing` 自带 bug（GetData/DataCopyPad 配对）逼 coder 现场修，属噪声脚手架（关联 Q10）。
- **产权**：codegen 实现质量（新）；缺 InferShape 是否 codegen 系统性盲点待查（关联 `tilingkey-ascendc-tpl-unification/`——ASCENDC_TPL 收口）；硬超时归 Q11。
- **状态**：待分析（L3）。

### Q2 [新发现] manifold codegen 编译通过、首次上板 runtime 崩溃——DataCopyPad GM 地址/MTE 对齐越界

- **本次实证**：编译/打包/安装**全过**（build_ascendc.log tail "CMake extensions built successfully" + wheel packaged），首次 NPU launch 即崩，smoke.log 13 次全核同 PC(`0x85c`)：`error code 507035 / aivec error / The GM address accessed by scalar exceeds 48 bits. The access address of the MTE instruction is not aligned with the data type bit width.`。`last_deploy.json`：`smoke_passed:false, max_diff:999.0, elapsed_ms:-1.0`。
- **真因归类**：**codegen 生成 kernel 缺陷**（非 infra——build/deploy/NPU 全正常）。地址算术错在生成 kernel `op_kernel/...post.h`：逐行 strided `DataCopyPad(xLocal[ubOff], xGm[gmOff], ...)`（.h:211）+ `hOutGm[curBatchS*D_+curD]`（.h:228）——GM element offset 误缩放/非 32B 对齐 + `curBatchS*n_*D_` 索引可能溢出 48-bit。coder 中途还修了个真 tiling bug（核派发 `r` 公式变负 → `r = totalElements - blockDim*(batchSPerMain-1)`），turn 258 主动停下问方向（**未超时**），in-session loop 内没能力做 runtime 调试（printf/DumpTensor）。
- **凭什么说是问题**：编译期查不出的运行时地址/对齐缺陷，codegen 自检覆盖不到；coder 编译层耗尽预算，进不到 runtime 调试。
- **产权**：codegen 生成 kernel 运行时地址安全（新，与 Q3 同类）。
- **状态**：待分析（L3）。

### Q3 [新发现] aggregate codegen 编译通过、首次上板 runtime 崩溃——EnQue/DeQue 生命周期失衡致 scalar buffer OOB

- **本次实证**：编译通过（早期 `op_plugin/...plugin.cpp:79 'at::Tensor' has no member 'value'` 已被 coder 修为 `mask.value()`），末次 deploy smoke.log：`case AiInfraAggregateHiddenGrad_1:4096x4x768 failed: ... error code 507035 / fftsplus aivector error / The address for the scalar to access the internal buffer of AICore is out of bounds. retCode=0x31 [vector core exception]`。`last_deploy.json`：`smoke_passed:false`；packages built successfully。
- **真因归类**：**codegen 生成 kernel 缺陷**（design/requirement 正常——golden 是标准 width-3 causal-conv 反向，测试 shape `[4096,4,768]`、无 mask）。生成 kernel `ai_infra_aggregate_hidden_grad.h`（L202–360）`inQueueGO` 队列协议不平衡：`hasMask==0`（本测试）路径下 stage-1 `ComputeGradInput` DeQue（L264）后**未 re-EnQue**，stage-2 `ComputeGradWeight`（L335）又 DeQue + FreeTensor（L359），"复用 go_buf for stage2"（design decision #4）跨两 stage EnQue/DeQue 失衡 → scalar buffer OOB（`subErrType:4`）。
- **凭什么说是问题**：同 Q2——编译过、运行时崩；coder 全部预算（138 次编译错误命中，含修 moe_re_routing）耗在 7 层 SDK-API/编译问题，进不到 runtime 调试就停。
- **次要**：T2 模板声明但未实现（kernel 恒走 T1，`ubTileS=1` fallback）；本测试 D=768 不触发，但是大 D 潜在正确性缺口。
- **产权**：codegen 生成 kernel 运行时地址安全（新，与 Q2 同类）；T2 未实现属 codegen 完整性。
- **状态**：待分析（L3）。

### Q4 [新发现，框架缺陷] multi_add precision_debug halt——epsilon 契约 str vs float 割裂（harness/loader 层）

- **本次实证**：过 codegen（2 iter），进 precision_debug，死于 harness PD-CONTRACT：`test_cases[0].attrs['epsilon'] expected float, got str='1e-6'`，0/0 用例运行、无 kernel 执行。halt `condition='upstream'`。
- **真因归类：框架缺陷**，非任何上游算子产物。字符串 `'1e-6'` 源自 cann-bench **原始 fixture**（`cann-bench-batch/20260730_205112/multi_add.../bench_lab/kernel_bench/level2/.../cases.csv` attrs JSON `{"epsilon":"1e-6"}`；sibling `cases.yaml` 的 `epsilon: 1e-6` 被 YAML `safe_load` 解析成 **str**——无小数点/符号不识别为 float，已实证）。epsilon 在权威处**全为 float**：`requirement.json:95 type=float`、`golden.py:24 epsilon:float=1e-6`、ops-info `attr_epsilon.type=float`、kernel `float epsilon_=1e-6f`；DevKit 自己的 `artifacts/staging/test_cases.json:74` 也是正确 float `1e-06`。但精度 runner 从 cann-bench `cases.csv` 重加载用例（绕过正确的 staging 副本）。
- **框架自相矛盾（凭什么说是框架 bug）**：① loader `domain/cann_bench_cases_loader.py:81/107` 透传 attrs（`_loads_or`）**不按 declared spec coerce**；② subprocess harness `adapters/npu/_harness_template.py:236 _cast_attr` **已有** numeric-string 强制转换（注释明说"cases.csv stores numbers as quoted strings"），但 `runner.py:130 _validate_attrs`（L106 pre-flight）在 `_cast_attr` **之前**就 type-check 拒了。同一约定框架已承认、下游已补救，唯 pre-flight 未补。
- **halt 决策方向对、归属错**：precision loop 确实修不了（0/0 case，kernel 没跑）→ halt 省预算对；但 scope_guard verdict 归因"codegen op-plugin/ACLNN 或 golden/test_design"**错**——修复应落 **DevKit harness/loader**，非任何上游算子产物。
- **产权**：新框架问题（attr 类型契约割裂）。关联 `cannbench-adapt-timeout-gap/`、`06-problems.md` case 通路（P9/P10）、记忆 `inplace-mutation-mode-two-layers`（cann-bench fixture 约定）。
- **状态**：**已修复（2026-07-31，跳过 L4 直修）**。修法=`runner.py:_validate_attrs` 在 type-check **前**按 declared spec 对 numeric-string 强制转换（`isinstance(v,str) and expected in (int,float)` → `int(v)`/`float(v)`，就地 mutate attrs dict 使 coerced 值流向 harness）；单一 spec-aware 咽喉点，harness `_cast_attr` 变冗余但无害。**不改 loader**（`cann_bench_cases_loader` 是确定性 parser、无 attr spec 访问，docstring "no repo-specific"，不该塞 spec 逻辑）。UT 守护：`test_runner_contract.py` 新增 4 用例（epsilon '1e-6'→float、'2'→int、非数字串仍 raise、str-spec 不误 coerce），36 passed。**确定性可复现、通用、不碰算子——本批唯一明确必修的框架 bug，已闭环。**
  - ⚠️ 未跑真实 heavy_llm 端到端回归（multi_add 重跑）——纯 Python 逻辑由 UT 覆盖（§3.11 不强造 heavy）；建议列入下次 batch 重跑验证清单。

### B. 设计阶段 loopback（系统性，未直接致失败，部分疑似 step-78 回归/盲区）

> 方法论坑：`report.md` per-stage `iterations` 列在设计阶段**误导**——几乎全显示 `iterations=1`，但 DD 尾链（tiling→anchor→integrate→docgen→validate）实际被跨 stage loopback 重跑 2–3 遍（只有 validate 自身 in-stage 重试露出）。真相在 `events.jsonl`（`stage_enter` 重入）+ `run.log`（`• loopback X→Y (corrective N/3)`）。见 Q9。
> spawn 计数（events.jsonl）：design-generator 7/12/24/19/7、design-reviewer 2/4/5/5/2、design-anchor 2/4/5/5/2（顺序 advance/scatter/manifold/aggregate/multi_add）。多数 generator spawn 是正常 per-template fan-out（每模板 split+vf-design+buffer-kernel+precision-perf），excess 才是 loopback。

**真 loopback vs 正常 fan-out 分布（agent 交叉核实）**：

| 算子 | 真 loopback | 是否收敛 | DD 阶段浪费墙钟 |
|---|---|---|---|
| advance_step_v2 | **0** | — | 0（干净单遍，7/2/2 全正常 fan-out） |
| scatter | 1（validate GV3） | **否**（docgen-stale 逃逸） | ~10min validate 空转 / 33min DD |
| aggregate | 2（anchor AC2 ✓ / validate GV8-A） | AC2 收敛；GV8-A 空转 3 iter 才修 | **~32min / 81min（40%）** |
| manifold | 1（validate GV3/GV4） | 是，但先空转 3 iter | **~50min / 74min（68%）** |
| multi_add | 1（anchor AC3，全 advisory） | 是 | ~12min / 53min |

> 值得的 bounce（不算问题）：aggregate AC2（T1 `Mul fp16×fp16→fp32` 标 api_checked，但 `Mul.md` 要求同 dtype，硬件锚定真缺陷，1 次 corrective 收敛）、manifold buffer/math 自洽（buffer_kernel 分配 7 个 TBuf 但 UB-factor 数学只验 6 个子集）。以下 Q5–Q8 是不合理 churn。

### Q5 [新发现，疑似 step-78 回归/盲区] validate 越界查它写不了的 docgen 终稿 → discover-but-can't-fix 逃逸

- **本次实证**：scatter validate GV3（`target=docgen`）：报"`§4.0.4` 函数签名表 CopyOutK/CopyOutV 缺 `__gm__ uint8_t* key_cache/value_cache`，与 `§4.1.4` 函数体不一致"——但 validate 工作目录只有源产物，docgen 终稿在 `../docgen/`，`decision_log.json` 明写"终稿在 ../docgen/ 下，无法就地 Edit"。validate 耗尽 3/3 iter，`known_issues: 待 docgen 重渲染修复…终稿 stale` **逃逸未修**，**无 docgen 重渲染 loopback 被触发**。aggregate GV3（§4.0.4）同型。且该 GV3 是 `建议非强制`（advisory，关联 Q8）。
- **凭什么说是问题（§2.9）**：正是 §2.9 明禁的"门越界查下游…发现问题修不了…报 target=X 让控制流兜底"。validate 只该查本 stage 源产物；文档表 vs 体一致性应由 docgen 构造性保证或前移到 buffer-kernel 产出时自检。
- **与 step-78 关系（待核实）**：step-78 gate-scope 声明 validate GV 系列含"redo_doc/human 前逃"（`78-...-impl.md` §4.2/§5），即 validate→docgen 前逃**是设计的**；但本批实证 docgen 重渲染**未被接线/未触发**，finding 直接 stale 逃逸——疑似 step-78 的 redo_doc 反馈渠道未真正闭合，或该类 advisory 根本不该触发 loopback。**需对照 step-78 实现确认是回归、盲区、还是设计如此但缺 docgen 消费端**。
- **产权**：`78-gate-scope-ownership-contract-analysis/impl.md`（redo_doc 渠道）、`76-design-review-infeasible-loopback-analysis.md`（越界查 + 毒性前逃范式）、CLAUDE.md §2.9 第 5 条（门不越界查上游/下游）、记忆 `design-review-infeasible-loopback-deadloop`。
- **状态**：**L3 已展开**（`84-design-validate-loopback-analysis.md`）——分类 (C) by-design 越界+缺 docgen 重渲染消费端；非 step-78 回归。修复方向 ⓐ 移除 validate 终稿表-体检查、交 docgen 构造性保证。

### Q6 [新发现] validate 烧满 3-iteration 预算反复 re-detect 同一问题，才触发真正修它的 loopback

- **本次实证**：aggregate GV8-A（`target=tiling/T2`，"T2 buffer_kernel Kernel 伪代码停留在意图/散文层级，未达代码块级保真"）validate 3/3 iter 不收敛，每 iter 重报同一 complaint（`iteration 4/5 复查确认与 iteration 3 一致`），再触发全 tiling→docgen loopback，第二次 validate pass。manifold GV3/GV4（`target=tiling/T1`，buffer_kernel 分配 7 TBuf 但 UB-factor 数学只验 6 子集）同型：3/3 iter 重报后才 loopback。scatter DeQue 项亦然。
- **凭什么说是问题（§2.9）**："gates that repeatedly bounced the same issue without converging"——修复本该发生在 `tiling`，validate 的 3 次 in-stage 重试纯浪费（~8–10min/算子）。正确行为：一次检测 → 立即 loopback，不在 validate 内空转重报。
- **产权**：`35-loopback-routing-and-incremental-analysis.md`（loopback 路由）、`78-gate-scope-ownership-contract-impl.md`（validate redo_tiling 自修/前逃路径）；validate in-stage 重试预算 vs 立即 loopback 的边界可能新。
- **状态**：**L3 已展开**（`84-design-validate-loopback-analysis.md`）——分类 (B) step-78 未覆盖盲区；修复方向：target≠validate 自身即首检 bounce、不进 in-stage 重试。

### Q7 [新发现] scatter validate 自检"信 decision_log 胜过信文件内容"——声称已修但未落盘

- **本次实证**：scatter validate `decision_log.json` iter 1&2 **声称**已把 `segK.DeQue()`（DeQue 误用为 LocalTensor 方法）修成 `kvSegQue.DeQue<kvDtype>()`，但编辑**从未落盘**；iter 3 重读文件发现未改（`前两轮 decision_log 声称已修但实际未落盘`）才真改。白烧 2 iter（~7min）。
- **凭什么说是问题（§1.13/§2.9）**：自检结论必须以实际文件内容为准，不能信自己的 log。这个"信 log 不信文件"直接违反 validate 最终自己引用的产物真值原则，放大 Q6 空转。
- **产权**：新问题（validate 自检落盘校验）。关联 CLAUDE.md §1.13（产物权威）、§2.9（自检闭环）。
- **状态**：**L3 已展开**（`84-design-validate-loopback-analysis.md`）——分类 (B) step-78 未覆盖盲区；修复方向：validate transition 重读文件校验 claimed edit 落盘（§1.13）。

### Q8 [新发现] advisory 级（建议非强制）发现触发全尾链重生成

- **本次实证**：multi_add anchor AC3 全 advisory（`verdict=verified/unverified`：不存在的 `Round` source_pointer、`SetScalarValue` 用法注记、跨模板 `oriDtypeSize` 命名不一致），却触发一整轮 tiling→docgen 重生成（~7 次 loopback generator spawn）。scatter GV3（Q5）亦标 `建议非强制` 却触发 2 次额外 re-iter。
- **凭什么说是问题（§2.9）**：对 cosmetic advisory 做全量 loopback 不成比例——应按 severity 门控（advisory 只记录不 loopback）或走构造性保证，而非全尾重跑。
- **产权**：新问题（severity-gating）。关联 `78-gate-scope-ownership-contract-impl.md`（gate 自标 advisory 但未按 severity 抑制 loopback）、§2.9（构造性保证优先于检查门）。
- **状态**：**L3 已展开**（`84-design-validate-loopback-analysis.md`）——分类 (B) step-78 未覆盖盲区；修复方向：severity 门控 loopback，advisory 只记录不 loopback。

### C. 横切 / 可观测性

### Q9 [新发现] report.md `iterations` 列在设计阶段误导——跨 stage loopback 被折叠隐藏

- **本次实证**：DD 尾链被 loopback 重跑 2–3 遍（d7237a validate 13:33 跑完又在 14:07 重入、e66710 13:50→14:00 后 14:18 重入），但 `report.md` 除 scatter validate（3 iter）外几乎全显 `iterations=1`。判 loopback 必须读 events.jsonl `stage_enter` 重入 + run.log `loopback` 行。
- **凭什么说是问题**：可观测性——现有 report 让人误以为设计一遍过，掩盖 40–68% 的 DD loopback 墙钟；呼应 step-7（design 执行审计报告，记录 loop-back 次数）低优增强未做。
- **产权**：`skills-integration-and-tdd-plan.md` step-7（DFX design 审计报告）、`pipeline-observability/`、记忆 `batch-status-provenance-events-jsonl`。
- **状态**：待分析（L3，可低优）。

### Q10 [已有 memory + `cann-bench-deploy-builds-all-ops`] moe_re_routing 参考算子带毒 + coder 编译层内耗

- **本次实证**：scatter/aggregate/manifold 三 codegen 大量轮次耗在 SDK-API/模板/plugin 编译错误（scatter 7 级阶梯、aggregate 138 次编译命中）；`moe_re_routing`（cann-bench 仓非预置算子，commit 21c71d2）自带 bug（GetData 模板、DataCopyPad 配对）反复逼 coder 现场修/改名 `_moe_re_routing` 排除 CMake GLOB。
- **凭什么说是问题**：coder 有限预算被编译层 + 参考算子噪声吃掉，留给 runtime 调试（Q2/Q3）的预算不足。moe_re_routing 编译污染是已知问题（cann-bench deploy 经 CMake GLOB 编译 csrc/ops/ 全部算子）。
- **根因深挖（2026-07-31，已核实 + 用户订正）——脚手架参考经 cwd 隐式仓耦合浏览，解耦通路已存在但未接线**：**先厘清两条参考通路职责不同**（`repository.py:83-85` docstring："intentionally distinct concerns and never merged"）：**方案级** `reference_code`/`reference_op_path`（相似算子全量源码指导解法，消费方 `requirement.py:80,149,188` + codegen）vs **脚手架级** profile `default_reference_root` → `state.reference_roots`（仓 op 组织/注册/CMakeLists 约定参考）。**Q10 病根在脚手架级通路**：① codegen 需学目标仓脚手架约定，但脚手架通路 `state.reference_roots`（profile `default_reference_root` 已填）**codegen 根本不读**（grep 证实全仓只 `verify_repo.py:124` 读）；② coder cwd=`.../csrc/ops/<op>/`，脚手架通路没接线 → coder 回退**隐式浏览 sibling** 学脚手架（aggregate/manifold coder 各引用 `moe_re_routing` 87–88 次学其注册/DataCopyPad/CMakeLists，scatter 0 次浏览 add/sqrt）——**既是 §2.1 仓耦合，又是 moe 带毒源**；③ prompt `codegen.py:922` 明令禁 coder 自搜 `ops/`，但脚手架通路没接线 + cwd 在 ops/ 内，禁令形同虚设（禁了没给替代 config 通路）；④ **profile 现指"整个 ops 目录"（`default_reference_root: .../csrc/ops` bare dir）而非"声明干净脚手架样例"**——用整目录本身就是让带毒 sibling 混进参考的结构原因；⑤ 解耦通路本已存在只是没接进 codegen：profile `default_reference_root` + `--reference`（`run.py:30`）→ `state.reference_roots`（经 `entry.py:112`/`dispatcher.py:771`/`context.py:194,240`），但 codegen 不读；⑥ 先例：golden/cases 已刻意从 profile 预置迁 CLI 显式（`cann-bench.yaml` 末注释 13 E1）。**注意**：方案级 `reference_code` 生产链路也没填，但那是独立问题，不是 Q10 病根。
- **产权**：记忆 `cann-bench-deploy-builds-all-ops`（修法=删该 op 源目录，属手工特判非通用）、`codegen-skill-upstream-reuse/`、`codegen-skill-selfcheck-dims/`。
- **状态**：**L3 已展开**（`84-codegen-convergence-analysis.md` 机制 ⓪ 脚手架参考解耦 = 治本，接通 `reference_roots` + profile 收窄为干净样例 + 关隐式浏览；机制 ③ GLOB 隔离 = 编译侧兜底）；待核实 V4：cann-bench 脚手架约定是否变→profile 样例清单是否需刷新。memory 手工删 sibling 记法降级为非通用兜底。**带毒源已清（2026-07-31）**：`csrc/ops/moe_re_routing`（local-only commit 21c71d2，非 origin/master）已 `git revert`（e1ea7ca）于 canonical cann-bench 仓，后续 worktree 检出不再带它；保留 `tasks/level3/moe_re_routing`（remote 评测任务 bc05bbd，in origin）。规则=cann-bench 只用远端代码，local-only 新增全删（见 memory `cann-bench-local-only-code-must-go`）。此为 Q10 的**即时止血**；机制 ⓪ 仍是通用治本（防新算子再落进 csrc/ops 被隐式当参考）。

### Q11 [已有 `hard-timeout-and-graceful-shutdown/` + `stage-timeout-granularity/` + step-39] 3600s 硬帽按机制特征切、不按业务语义（是否仍在收敛）

- **本次实证**：scatter（Q1）在已正确诊断缺 InferShape、正在落最后一修时被 3600s 硬帽杀（22:33:15），离成功约 1 修。
- **凭什么说是问题（§1.10）**：硬帽用"墙钟到点"这一机制特征判该不该切，不看"是否仍在单调收敛（每轮撞新错、非同错震荡）"这一业务语义；语义上仍在收敛的重型 codegen 与真卡死共享同一超时特征，必有一类被误判。
- **产权**：`hard-timeout-and-graceful-shutdown/`、`stage-timeout-granularity/`、`39-soft-stage-timeout-analysis/impl.md`（软 stage 超时）、CLAUDE.md §1.10（横切控制流用业务语义不用机制特征）。
- **状态**：待分析（L3）——是否给 codegen 硬帽加"收敛信号"豁免/延长，需权衡与真卡死的区分成本。

### Q12 [新发现，已订正] advance_step_v2 精度实际通过（func=30），run.log `func=0` 是 scorer 硬编码假信号 + `_C` 未复发

- **本次实证（订正先前"空心 eval"误判）**：advance_step_v2（`316462`）01:10 跑完全流程。**授权源=eval 报告 JSON**（`reports/advancestepv2_eval_20260731_005919.json`）：`function_score=30, compilation_score=20, performance_score=0, overall=50, passed_cases=20/20, pass_rate=1.0, mismatch_count=0/total=16956`——**cann-bench kernel_eval 内部用真 golden 比对且精度通过**。唯一真 0 = performance_score（`_C` 反作弊 perf 计时未跑）。
- **run.log 的假信号（凭什么说是问题=日志可诊断性框架 bug）**：① `CannbenchScorer: func=0.00 compile=0.00` 是 `cannbench_scorer.py:321-323 _parse_report` **硬编码** `function_score=compile_score=performance_score=0.0`（注释"weighted overall_score is authoritative"）再打印——与报告 JSON（func=30/compile=20）**矛盾**，读日志的人被误导成"精度挂"（我先前即被此误导判"空心/0-5"）；② `golden_used:false / no_golden_reference` 来自 **DevKit smoke 展示路径**（`_harness_template.py:194,576`），非评分精度；③ `WARN cann_bench_utils unreachable; running eval_prepare` 是**正常自愈触发**（scorer.py:181 precheck 失败→build→scorer.py:225 重 precheck 成功=`_C` 编出来了），非失败。
- **`_C` 本批未复发**：`/lib64/libc.so.6 -> /usr/lib64/libc.so.6`（Jul 30 15:39 建=doc-83）BISHENG 编译阻塞已解；eval_prepare 自愈成功。用户问的"`_C` 反复未根除"是**三个不同失败模式共用一词 + 日志假信号**制造的错觉，非一个没杀死的 bug（详见 `84-cann-bench-utils-recurrence-analysis.md`）。
- **产权**：真框架 bug=`cannbench_scorer._parse_report` 日志假 0（可诊断性，§1.3/§1.11）；`_C` 三模式（BISHENG 编不出/site-packages 污染/build 未触发）各自修复实际有效；perf=0 是 `_C` perf 计时未跑的诚实降级（记忆 `cannbench-utils-bisheng-libc-lib64` 只挂 perf 不挂精度本批证实）。
- **状态**：**L3 已展开**（`84-cann-bench-utils-recurrence-analysis.md`）。推荐 P1：`_parse_report` 读报告真分维度分数弃硬编码 0。**本批真实 tally = 1/5 精度通过（advance_step_v2，perf 缺）+ 4 halt**，非先前误记的 0/5。

### 非问题观察（记录以免重复分析）

- **`git diff found changes the agent didn't report`（4 算子全出现）**：都是合法生成的 codegen 文件，因 agent 崩/停在 clean handoff 前，output_contract 解析不到自报字段，回退 raw git diff 快照。属报告卫生告警，非缺陷。产权：记忆 `batch-status-provenance-events-jsonl`。

---

## 一一分析的建议顺序（按阻塞面 + 依赖 + 确定性）

1. **Q4（epsilon 契约）**：本批唯一确定可复现、通用、不碰算子的框架 bug；修改面小（loader/runner 一处 coerce），直接解锁 multi_add 类（凡 cann-bench numeric-string attr 算子）。
2. **Q2 + Q3（codegen runtime OOB）**：同类（编译过、上板 OOB），是 4 halt 里 2 个的直接死因；决定 codegen 生成 kernel 的运行时质量，需看是否加地址安全自检 + 预算优先进 runtime 调试。
3. **Q5（validate 越界查 docgen）**：§2.9 违反 + step-78 疑似回归/盲区；先核对 step-78 redo_doc 渠道落地实况，判回归/盲区/设计缺消费端。
4. **Q6 + Q8（validate 空转 + advisory 触发全尾 loopback）**：与 Q5 同属 validate 门行为，一并收口（一次检测即 bounce + advisory 不 loopback）。
5. **Q7（validate 信 log 不信文件）**：小修（落盘校验），放大 Q6，随 validate 门一起。
6. **Q1（scatter 慢收敛 + 缺 InferShape）**：缺 InferShape 是否 codegen 系统性盲点待查；与 Q11 硬帽策略相关。
7. **Q11（硬帽业务语义）**：需权衡与真卡死区分成本，独立分析。
8. **Q10（moe_re_routing 毒 + 编译内耗）**：memory 已录修法，是否固化脚手架。
9. **Q9（report loopback 可观测）**：低优 DFX 增强。

---

## 句柄

- batch 总日志：`logs/batch_20260730_205112.log`；运行日志：`docs/plan/self-evolution/batch-runlog-20260730_205112.md`
- batch_id：`20260730-125126-091882`；HEAD：`ce4b6423`
- 各算子 execution：`output/20260730-125126-091882/{316462,37b9e2,d7237a,e66710,facf2e}/`
- 关键证据文件（每算子）：`subprocess/{build_ascendc.log,smoke.log}`、`artifacts/debug/*/last_deploy.json`、`events.jsonl`（halt/spawn_context/iteration）、`agents/ascendc-coder-*.jsonl`（coder 转录）、`artifacts/codegen/decision_log.json`、`artifacts/design/{validate,anchor-consistency}/{decision_log,anchor_report,blocking_status}.json`
- worktree 根：`/home/x00584171/code/cann-bench-batch/20260730_205112/`
- 续跑：`RESUME=1 bash scripts/batch_self_evolve.sh`
