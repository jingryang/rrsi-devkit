# batch 20260812-001959 — 问题记录（L1）

> 批次：`batch_self_evolve.sh` 首跑，batch_id `20260811-162020-d0ece5`（UTC，=本地 2026-08-12 00:20:20 CST），脚本 TS `20260812_001959`，worktree `cann-bench-batch/20260812_001959/`。
> 算子：grid_sampler_3d(exec `...-e0559b`) / resize_bilinear(exec `...-91ec15`) / unique(exec `...-8d29b4`)。
> 结果：**0/3 workflow-done、0/3 eval-passed，全部 FAIL(exit 65=halt)**，脚本 exit 1。批次耗时约 4h44m（00:20→05:04）。
> 记录者：Claude（交互会话内启动 + 每半小时周期观察 + 事后取证）。日期：2026-08-12。
> 本文只记**问题/需求**层客观事实（哪里坏、凭什么），不提方案、不排顺序、不写决策——§1.8 L1 产权；方案分析另见 `batch-20260812-001959-3of3-apierror-halts-analysis.md`（L3，待产出）。

## P1：3/3 全部 halt，直接触发均为 LLM 服务端 API 层显式错误（`thinking 回传` APIError / `type validation` UnknownError）

**哪里坏了**：三个算子全部在详设阶段 halt，无一进入 codegen/precision/eval。三个 halt 的最终崩溃点均为 **opencode serve ↔ LLM 网关之间的服务端 API 错误**：
- grid_sampler_3d：`tiling/T1/precision-perf` forkjoin 分支，`[partial]`（03:17:27，87.6s 速挂）。
- resize_bilinear：`anchor-forkjoin/anchor-per-template` forkjoin 分支，缺 `anchor_template_reports`（02:42:47）。
- unique：`tiling/T2/precision-perf` forkjoin 分支，`[partial]`（05:04:33，1679s 长会话后）。

**凭什么这么说（证据）**：

1. **每个 halt 分支的 transcript 末条 `error` 均为服务端 API 错误**（`agents/*.jsonl` 的 crash record，`opencode_backend.py:767 crashed=bool(err)`，`_message_error` 读 message.info.error）：
   - grid `ascendc-design-generator-T1-06.jsonl` turn 6（ts=03:17，=halt 时刻）：`APIError: The content[].thinking in the thinking mode must be passed back to the API. (request id: 20260811191716...)`
   - unique `ascendc-design-generator-T2-07.jsonl` turn 50（ts=05:04，=halt 时刻）：同一 `APIError`，**连续 4 个 request id**（20260811210342/43/44/…）——服务端反复拒绝 thinking 模式请求，非单次抖动。
   - resize `ascendc-design-anchor-T1-02.jsonl`：同一 `APIError`；另 `ascendc-design-generator-T1-01/02.jsonl`：`UnknownError: Type validation failed: {"type":"message_delta","delta":{"stop_reason":"end_turn"}…}`（流式 message_delta 校验失败）。

2. **APIError 贯穿全程，非"突发"单点**：全部 transcript 的 error 时间线显示 `thinking 回传` APIError 共 **7 次**，从批次头到批次尾均匀分布——00:30 unique、00:41 grid、00:46 unique、00:54 grid、02:42 resize、03:17 grid（halt）、05:04 unique（halt）；`type validation` UnknownError 2 次（01:23/01:38 resize）。早期几次被后续 resume/重试吸收，末两次（及 resize 的 anchor 重试）直接导致 halt。

3. **turn_stall 看门狗触发 4 次**（01:08/02:01/02:25/02:27，608-609s 无新轮次 > 600s），其中 resize anchor-per-template 的 turn_stall（02:27）→ 杀 serve → 重试时 APIError（02:42）→ 分支缺产物 → halt。turn_stall 静默期与 APIError 交替出现，同为服务端不稳的观察信号。

4. **同一机制在早期多次自愈成功**（对照，非整体故障）：run.log 中多次 `agent_resume … auto-resuming session … (sidecar present — silent-cut recovery)` + `cut_streak` 计数（00:20-01:54 共 4 次 silent-cut 恢复）；上批实施的 silent-cut 检测（`opencode_backend.py:760 _cut`）确实在工作。说明故障形态不是"整体不可用"，而是**服务端 API 对 thinking 模式请求的反复拒绝/校验失败**，与批次中后段才累积到 halt。

5. **非框架看门狗/资源问题**：manifest `workflow_timeout_sec=36000`（10h，批次实际 4h44m 未到）、`stage_timeout_sec=0`；无 OOM/资源信号；grid precision-perf 87.6s 速挂非超时（是 APIError 立即返回）；三次 halt 均在 `workflow done` 内以 `fail_strategy=halt` 终止（`Workflow halted: stage '…' failed with fail_strategy=halt: fork-join 分支 … 失败`）。

**根因（事实陈述，非方案）**：服务端（第三方 LLM 网关，经 opencode serve 访问）对 **thinking 模式请求返回显式 APIError**（`content[].thinking must be passed back`）及流式 `type validation` 错误，从批次头持续到尾。框架忠实检测到该错误（`_message_error`→`crashed`→有产物则 `partial`/无产物则 `fatal`），design 阶段 forkjoin 分支（precision-perf/anchor-per-template）对这些 partial/缺产物直接 `fail_strategy=halt` → 整算子 workflow 终止、零评测。与上批 20260810 用户确认的"外部第三方网关**静默**中断"**同源（外部网关不可靠），但形态不同：静默切流→silent-cut 恢复已覆盖；本批为显式 API 拒绝（crashed），silent-cut 恢复机制不覆盖该路径**（见 P2）。

**影响范围（事实）**：本批 3/3 全部 halt、0 评测，批次级归零。非并发/单算子偶发——三算子分处不同 stage 不同时刻先后 halt，共用"服务端 API 错误 → forkjoin halt"同一条因果链。

**产权（事实）**：服务端 API 错误在外部第三方网关（不可控）；错误检测与 partial/fatal 语义在框架 backend（`opencode_backend.py`/`base_backend.py` `_build_result`）；design 阶段 forkjoin 分支 `fail_strategy=halt` 在框架 orchestration（`design_substages.py` / `node_forkjoin.py` / `graph_executor.py`）；thinking 模式回传协议兼容在 opencode↔网关侧。

## P2：design 阶段 forkjoin 分支对服务端 APIError（crashed→partial）直接 `fail_strategy=halt`，无 resume/降级兜底（框架结构性放大器）

**哪里坏了**：服务端 APIError 被框架正确识别为 crashed→partial（`base_backend.py:262-263` crashed+artifacts→partial），但 design 阶段的 **forkjoin 分支（per-template 的 precision-perf/anchor-per-template 等）对 partial 直接 halt**，没有像普通 stage 那样走 resume/重试吸收服务端抖动。

**凭什么这么说（证据）**：

1. **同类 APIError 在普通 stage 被吸收、在 forkjoin 分支致 halt 的对照**：00:41/00:54 的 grid APIError（主链 agent，turn 30）后续 resume 恢复继续推进；而 03:17 的 precision-perf/T1（forkjoin 分支）同型 APIError → 直接 halt。差异在分支/阶段的 fail_strategy 与恢复路径。
2. **halt 日志形态**：resize 为 `Stage 'anchor-per-template' reached max iterations (1) without satisfying output_contract`（**max_iterations=1**，一次 APIError 烧掉唯一迭代）；grid/unique 为 `Stage 'precision-perf' failed with fail_strategy=halt`（partial 直接 halt）。均无"分支重试吸收服务端抖动"的路径。
3. **silent-cut 恢复机制只覆盖"末条 thinking-only 切流"（cut）**：`opencode_backend.py:760` `_cut = not err and not _last_turn_actionable`——**`not err` 为前提**，服务端 APIError（err 非空）时走 `crashed` 路径（`:767`），不产生 cut、不走 silent-cut resume。即上批为"静默切流"设计的恢复机制**对"显式 API 拒绝"形态天然不覆盖**。

**根因（事实陈述，非方案）**：服务端故障形态从上批的"静默切流"演进为"显式 API 错误"；既有恢复机制（silent-cut resume + turn_stall 杀 serve）针对前者设计，对后者只做了忠实检测（partial/fatal）而未配恢复路径；forkjoin 分支 `max_iterations=1`/`fail_strategy=halt` 再把单次服务端错误放大为 batch 级 halt。**服务端触发，框架放大**。

**影响范围（事实）**：放大作用使"服务端 API 抖动"在本批从"可吸收的局部事件"变成"0/3 批次归零"。若服务端持续拒绝 thinking 模式，即使加 resume 也未必能靠重试达成进度（需如实上报外部故障，§1.11 / external-infra）。

## P3：批跑观察性事实（非缺陷，供后续决策参考）

- 本批运行在含上批修复的版本上（silent-cut 检测 + cut 计数 + turn_stall 看门狗均已生效，从日志 `agent_resume…silent-cut recovery` / `cut_streak=1/5` / `turn_stall 600s` 可见）；本批新增未覆盖形态：服务端显式 APIError。
- 三个 exec 的 `events.jsonl` 中 `action_complete` result=partial 事件多次（grid 2 / resize 3 / unique 5），对应 silent-cut 恢复与 crashed 交替；`stage_complete` partial 仅 halt 分支（resize anchor-per-template 1 次）。
- 批次结束：`.batch_id` 已写 `cann-bench-batch/20260812_001959/.batch_id`；worktree 保留（KEEP_WORKTREES=1）。`RESUME=1` 续跑会重跑未完成算子，但服务端 thinking 回传错误未修复前预计复现同型 halt。
- 本批 devkit 运行时代码状态：HEAD 时 git status 显示 `M scripts/batch_self_evolve.sh` 等 20+ 文件 dirty（会话启动时快照），复现/对照需记录版本身份。
