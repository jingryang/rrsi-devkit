# E2E self_evolve 运行日志 — moe_re_routing (run_id 20260724-045259-898837)

> 运行日志（诚实记录）。任务进行中，本文档随进展更新。
> 最后更新：2026-07-24 14:08（design corrective 2/3 进行中）

## 1. 基本信息

| 项 | 值 |
|---|---|
| 算子 | moe_re_routing（cann-bench L3，多输入多输出 + 可选输入 + int8） |
| run_id | 20260724-045259-898837 |
| chip | A2（本机 910B3，显式 `CHIP_VERSION=A2` 避开 detect_chip_version hdcdrv 卡死） |
| 启动 | 2026-07-24 12:52:59，`CHIP_VERSION=A2 bash scripts/e2e_self_evolve.sh` |
| 后台 task | b6a0fsyov |
| 权威日志 | `output/20260724-045259-898837/run.log` |

环境探测全通过：NPU 8×910B3 健康、CANN cann-9.1.0-beta.3、cann-bench 仓 + moe_re_routing proto/golden/cases 齐全、`chip_decision.mismatch=false`（design=A2/cli、runtime=A2/probe）。
唯一 env_warning：`devkit.git.dirty=true`（untracked docs，无害）。

## 2. 链路进展（截至 14:08）

- ✅ requirement
- 🔄 **design**（corrective loopback 反复触发，详见 §3）
  - ✅ general-design-generator / general-design-review
  - ✅ template-division（单模板 T1）
  - tiling 第 1 轮 ✅ → **anchor-consistency 发现 AC0/AC2** → corrective 1（13:17）→ 13:33 `passed after 1 corrective retries`
  - ✅ integrate / ✅ docgen
  - ✅ validate（828s, events 内 3 iter）→ **判定 blocked (AC0)** → corrective 2（14:00）🔄 进行中（split ✓ / buffer-kernel turn 16）
- ⏳ test_design → codegen → deploy → precision_debug → cannbench_adapt → cannbench_eval

## 3. 核心发现：design validate 判定 blocked（AC0 反复未解决）

### 3.1 validate blocking_status.json 摘要（`status: blocked`, blocking_issue_count=1）

- **GV9-a BLOCK** — 算子含骨架级 gather 语义，tiling_results 的 split/buffer_kernel/precision_perf 三段**均无 `verifiable_claims` 字段**（grep 命中 0 次）。
- **GV9-b BLOCK** — anchor_report.blocking_issues 非空（AC0 unverified + AC2 infeasible）。
- GV1/GV3/GV8-A/GV9-c/GV10 **PASS**；GV2/GV7 **N/A**。
- **GV4 PASS 但带刺** — +32B 算术偏差（`buffer_kernel.ub_usage.worst_case` 131264→131232 / case_driven 16576→16544）validate 每轮就地修正，**但 tiling producer 连续 3 轮未在源头修复**，致每次接力复现。结论（≤100% UB）不变。

### 3.2 AC0（blocker，verdict=unverified）— 跨多轮反馈循环未解决

validate 的 `iteration_note` 明确：
> AC0/AC2 已进入**第 4–5 轮反馈循环**；`verifiable_claims` 字段**连续 4 轮（iter2/3/4/5）缺失**；GV4 算术偏差**连续 3 轮在源头未修复**。tiling producer 多轮仍无法产出 source_pointer 实证的 claim，也未能修正算术偏差——**强烈建议工程路由升级为 human 介入**。

即：AC0 跨 anchor-consistency + validate 两个质量门、累计 ~5 轮反馈仍未消化。

### 3.3 暴露的工程缺陷模式（疑似）

**corrective 反馈闭环失效**：validate 报 AC0 → corrective loopback 回退到 tiling producer → producer **未按要求补 `verifiable_claims`、未在源头修 GV4 算术偏差** → 下一轮 validate 仍判 blocked → 再次 corrective。validate 自己的就地修复（GV4 算术偏差）也**未传回 producer 源产物**。结果是 corrective 机制空转、design 阶段显著拉长（已 ~67 分钟仍在 corrective）。

> 待确认（§3.3 原判断，已被 §3.4 部分修正）：原疑 producer 不消费反馈，但 corrective 2 证据显示 producer 其实补了——见 §3.4。

### 3.4 【14:28 更正】根因疑为 integrate 合并丢字段，而非 producer 不补

深入检查 corrective 2 产物后修正 §3.3：

- **producer 在 corrective 2 确实补了高质量 verifiable_claims**（事实）：`tiling/T1/` 子产物 `tiling_precision_perf.json`(4)/`tiling_buffer_kernel.json`(3)/`tiling_split.json`(1) 均含结构化 verifiable_claims 数组——`claim_type=hardware_api_capability` + `verification=api_checked` + source_pointer 指向 Gather.md 产品支持表（A2 训练/推理 √、T 列表 half/bfloat16_t 含 int8_t 不含）。质量符合 validate acceptance。
- **但 integrate 合并产物 `integrate/tiling_results.json` 里 verifiable_claims = 0**（事实：grep 0 + 递归遍历无 key）。
- **关键限定**：当前 integrate/tiling_results.json mtime=14:24:14 = integrate stage 开始时间，是 integrate 的**输入快照**（corrective 2 integrate 仍在 turn 25 进行中，最终输出未写出）。故"integrate 丢字段"**尚未最终确认**。

**待确认的因果链（强信号）**：producer 补 verifiable_claims（T1/ 子产物）→ integrate 合并到 tiling_results.json 时丢字段 → validate grep tiling_results.json=0 → 判 AC0 blocked → corrective → producer 再补 → integrate 再丢 → 空转。若成立，根因是 **integrate 合并逻辑未透传 verifiable_claims 字段**（§2.9 下游消费上游派生产物的边界），而非 producer 不消费反馈。

**conclusive 判据**（下次检查）：corrective 2 integrate 完成 → docgen → validate 时，若 tiling_results.json 仍无 verifiable_claims 且 validate 再次 block → 确认 integrate bug，触发 corrective 3/3。届时可考虑定位 integrate 合并代码（框架 domain 层，需用户授权）。

### 3.5 【14:47 容器重连后确认】AC0 最终结局 + integrate bug 确认

容器断开期间（14:28→14:47）design 收尾，关键事实：
- 14:35:46 corrective 2 的 validate done（201s）→ `loopback validate passed after 1 corrective retries`
- 但**最新 validate/blocking_status.json 仍是 `status=blocked`, AC0**；且 `validate/tiling_results.json` verifiable_claims=0。
- 即：**AC0 在最终 validate 仍未真正解决**，但系统在 corrective 重试后**放行**（带 unresolved/blocked），design 进入 test_design → codegen。

**integrate bug 确认（验证 §3.4 判据）**：
- producer 在 T1/ 子产物补了 verifiable_claims（split 1 / buffer_kernel 3 / precision_perf 4 处，结构化 + api_checked + Gather.md 引用）；
- integrate 合并后的 tiling_results.json verifiable_claims = **0**（validate 工作目录拷贝亦 0）；
- → **integrate 合并 tiling 子产物 → tiling_results.json 时未透传 verifiable_claims 字段**。
- 后果：validate grep tiling_results.json=0 → 反复判 AC0 blocked → corrective 空转（design 多耗 ~50 分钟）→ 最终放行带 unresolved。

**影响**：AC0 unresolved 但**不阻塞 codegen**（已 14:35 进入 codegen）；按 §4 判断不影响算子功能正确性（A2 gather fp16/bf16 明文可用）。但 integrate 丢字段是**真实框架缺陷**，建议任务结束后定位修复（domain 层 integrate 合并逻辑，需授权）。

## 4. 影响判断（我的评估）

- AC0 主要是**设计产物的可审计性/可验证性缺口**（缺结构化 API 能力断言 + 文档指针），**不必然是算子功能缺陷**：A2 平台 Gather 对 fp16/bf16 明文可用（AC2 已在散文层确认与 Gather.md 一致）、int8 不支持；算子是否采用 Gather API 属设计选择（UB-local vs GM-resident）。
- GV4 算术偏差结论（≤100% UB）不变，非致命。
- **推论**：即便 corrective 2/3 用尽、design 带 unresolved/blocked 进入 codegen，算子大概率仍能正确生成并在 precision/eval 跑通——AC0 缺的是"证据"不是"正确性"。但若 codegen/precision 因 gather 实现路径出问题，需回看此处。

## 5. 处理决策

- **不打断后台任务**：让 corrective 2/3 跑完，观察是否最终通过或带 unresolved 进 codegen（设计预期 corrective 用尽后可带 unresolved 继续）。
- **持续监控重点**：corrective 是否收敛 → codegen 编译是否通过 → precision 是否因 gather 路径失败 → cannbench_eval function/perf 评分。
- **若需在设计期彻底解决 AC0**：可在 design 结束后人工介入，按 validate 的 `acceptance` 给 tiling_results.T1 补 `verifiable_claims`（hardware_api_capability gather 查证项 + source_pointer → Gather.md）+ 源头修 GV4 算术偏差。

## 6. 时间线

| 时间 | 事件 |
|---|---|
| 12:52:59 | 启动 |
| 13:03 | requirement/general-design/template-division 完成 |
| 13:17 | anchor-consistency 发现 AC0/AC2，corrective 1 |
| 13:33 | corrective 1 passed |
| 13:38/13:46 | integrate/docgen 完成 |
| 14:00:09 | validate 完成（828s），判定 blocked (AC0)，corrective 2 |
| 14:08 | corrective 2 进行中（buffer-kernel turn 16） |
| 14:35 | design 放行（AC0 unresolved）→ test_design 秒级 → codegen |
| 15:06 | codegen 完成（30min）+ 编译通过 + redeploy → precision_debug run_tests |
| 15:08 | precision_debug run_tests 第一轮进行中（turn 11） |

## 7. codegen / precision_debug 阶段发现（15:08）

- ✅ **编译通过**：codegen 15:06 完成（30min），算子已出包部署（否则无法进 run_tests）；19 个源码文件齐全（kernel/host/api/plugin）。
- ⚠️ **codegen manifest keyword-call schema 参数名 drift**（潜在风险）：manifest 的 inputs/outputs 字段完整（3 in + 4 out），但某个 keyword-call 参数名汇总列表只列 5 项（3 输入 + expert_token_num_type/idx_type），**漏 4 个输出 tensor 名**。框架 WARN："cann-bench keyword-call will fail (P10)；cannbench_adapt will rename m.def schema to proto names as fallback"。**风险**：fallback 是 rename 非补缺，若 schema 无输出参数名，cann-bench 按名调用可能传/接不到 4 个输出。待 cannbench_adapt/eval 验证。
- ⚠️ **control.json 首轮缺 20 key**（良性）：precision_debug control.json 首写不完整（缺 best_commit/candidate_pool/failed_case_queue 等 20 key），框架已自动初始化 safe defaults。不影响。
- ✅ **soft-gate 陷阱暂未触发**：control.json `run_iter_counter=0`、`consecutive_aborts=0`（run_tests 第一轮还在跑，未 abort）。持续盯第一轮结果。

## 8. precision_debug 闭环 + runtime 崩溃根因（15:28）

- ✅ **soft-gate 陷阱确认未触发**：run_tests 第一轮正常完成（`run_iter_counter=1`, `consecutive_aborts=0`），precision_debug 走完整闭环 run_tests→scope_guard→bounds_check→diagnose→fix，**非** soft-gate passthrough。scope_verdict=pass（确认失败属本阶段职责，非上游产物缺陷）。
- 🔴 **runtime 崩溃，diagnose 精确定位根因**：
  - error_code **507035**（ACL_ERROR_RT_VECTOR_CORE_EXCEPTION），core_id=21。
  - 根因：`op_kernel/moe_re_routing.h:190-204` 的 `BuildIndexOnCore0` 用 scalar `GlobalTensor::SetValue` 在 core 0 写 GM（构建 permute_token_idx / expert_token_num），**SetValue 后缺 `DataCacheCleanAndInvalid`** → 多核经 SyncAll(:286) 后读到脏 DataCache → scalar 访问 invalid GM → 向量核异常。
  - 经典 AscendC 同步陷阱：scalar 写 GM 后，若其他核要读，必须手动 DataCacheClean（CANN《Scalar读写数据.md》明文）。candidate_pool 4 个 fix_plan，fix 阶段（ascendc-precision-fix turn 22）验证中。
- **与 design AC0 的关系**：非直接因果（AC0 是 gather 语义 verifiable_claims 文档缺口；crash 是 kernel 代码的 DataCache 同步缺陷），但都落在 gather/permute 路径（BuildIndexOnCore0 构建 permute 索引）。AC0 unresolved 未直接致 crash；crash 是 codegen 产物的独立同步缺陷。

## 9. precision fix 进展 + AC0 关联已知 P100（15:48）

- **fix 完成、runtime 未解、转 comment_bisect**（15:24→16:16 ~52min / 3130s，**未触 stage_timeout**）：control.json 更新滞后，最终显示 `candidate_loop.current_tried=2`、tried `diag-001-datacache-clean` + `diag-002-ub-gm-datacopy-rewrite` **两个 fix_plan 均失败**（case 0 仍 runtime, attempt_count=2, resolved=0, run_iter_counter=2）。候选池用尽 → 按 runtime 分流 **comment_bisect**（16:16 起，ascendc-precision-comment-bisect 注释二分定位 crash 根因，turn 34 进行中）。说明 507035 根因比 diagnose 给的 DataCache-clean 更深，2 个 plan 未中。**前两轮汇报的"control.json 零进展"实为 control.json 更新滞后**——fix 一直在工作。precision 闭环正常推进（非 soft-gate、非超时）。

- **comment_bisect 完成、转第二轮 fix**（comment_bisect 16:16→16:31 done 15min；16:31 起第二轮 fix，turn 51 验证中）：comment_bisect 产出 experiments/tried_bisect_paths；iter-2 result 显示 case 0 错误码演变为 **507057**（`SUSPECT REMOTE ERROR`，非初版 507035 vector core exception）——**runtime 缺陷多层**（DataCache 之后暴露下一层），precision 闭环逐层剥离。`run_iter_counter=3`、`max_iterations=30`（远未到上限），无超时/429/abort。

- **fix↔comment_bisect 循环、runtime 顽固**（第二轮 fix 16:31→16:53 done 21min → 第二轮 comment_bisect 17:08 进行中 turn 58）：**3 个 fix_plan 全失败** —— `diag-001-datacache-clean`、`diag-002-ub-gm-datacopy-rewrite`、`cbisect-001-rewrite-buildindex-ub-datacopy`（comment_bisect 定位后的 BuildIndex 重写）。`run_iter=4`、`candidate_loop.current_tried=3/10`、case 0 仍 runtime(`attempt_count=3`)、resolved=0。闭环正常（fix↔comment_bisect 交替，非 soft-gate/非超时），但 **runtime 缺陷顽固**——根因疑似 `BuildIndexOnCore0` 用 scalar `GlobalTensor::SetValue` 在 core 0 建索引 + 多核读这一模式本身的多核同步困难（补丁式 fix 难以根治）。若最终修不好 → 带 unresolved 进 cannbench_eval → **function 大概率 0（算子崩、无结果）**。

- **闭环加速、第 4 plan 方向印证根因**（17:09 后加速：`run_iter 4→8/30`，comment_bisect 单轮缩至 117-197s，fix 缩至 11min）：第 4 plan **`cbisect-002-eliminate-scalar-gm-setvalue`**（彻底消除 scalar GM SetValue）——**方向印证 §9 根因判断**（该模式本身需消除）。但 case 0 仍 runtime(`attempt_count=4`, resolved=0)，第三轮 comment_bisect 定位中。即消除 scalar SetValue 的重写仍不完整或暴露新层。`candidate_loop 3-4/10`。无超时/429/abort。

- **🔴 case 0 被 skipped（runtime 修不好的强信号）**（17:29 后闭环 `run_iter 8→11/30`，run_tests→diagnose→fix 快速循环）：control.json `failed_case_queue[0].status` 从 pending 变 **`skipped`**（attempt 重置为 0、仍 `failure_type=runtime / max_err=999.0`），**resolved=0**。即 case 1(1024x512) runtime 崩溃经 4+ plan 多轮仍未修好，被 advance/skip 跳过。precision_debug 继续（diagnose→fix 第四轮）。**强烈暗示最终 cannbench_eval function 受影响**（case 1 过不了）。precision_debug 已跑 ~160min，run_iter=11/30。

- **🔴🔴 precision_debug 实质失败：全部 20 case skipped**（18:08）：control.json case 状态分布 **`{skipped: 20}`**、**resolved=0**、`run_iter=11/30`。moe_re_routing 在**所有 case 上 runtime 崩溃**、precision 闭环无法修复、全部跳过。第四轮 fix 仍跑（28.5min, turn 92，进程数 4→疑在编译验证），全 case skipped 后 precision 可能在 candidate_pool/run_iter 用尽前继续空转若干轮。最终 cannbench_eval **function 大概率 0**（算子崩、无结果）。

- **🔴🔴🔴 确认 runtime hard_error（非改善）**（18:28 复查）：failed_case_queue 从 `{skipped:20}` 变为长度 1 的 **`moe_re_routing:hard_error`**（伪 case，多 case 失败归并非改善）；`run_tests_iter-12` 的 `case_details` **为空**（passed=False, max_diff=999）——**算子 hard_error 连用例都跑不起来**。第五轮 fix（18:17 起, turn 58）继续尝试修 hard_error。`run_iter=13/30, candidate_loop=4/10`。runtime 严重失败结论**不变**（比之前判断更确证），最终 cannbench_eval **function 大概率 0**。
- **AC0 关联已知问题 P100**（修正 §3 的"新发现"表述）：本 runlog §3-8 记录的 AC0 / verifiable_claims 丢失死循环 = 已知专项 `loopback-closure-defects-batch` 的 **P100**（根因 `design_substages.py:2050` 丢 verifiable_claims，有方案 73 待拍板，推荐 C「嵌进 segment」）。本次 AC0 corrective 空转是该已知缺陷的**实例印证**；本 runlog 独立定位到 integrate 阶段，与 P100 根因（design_substages.py:2050 合并逻辑）一致——非全新发现。
