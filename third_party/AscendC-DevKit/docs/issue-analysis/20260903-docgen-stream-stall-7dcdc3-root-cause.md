# Root Cause Analysis: adaptive_avg_pool_3d docgen 反复 stall → halt

**Date:** 2026-09-04
**Run:** `output/20260903-073532-eddf10/20260903-073532-7dcdc3`
**Operator:** adaptive_avg_pool_3d（A3 双模板 T1+T2 codegen 全流程）
**Phase:** `self_evolve_op/detailed-design/docgen/docgen`
**Result:** docgen 未产出 `<op>_详细设计说明书.md`，`fail_strategy=halt` 终止（17:05:17）
**Status:** 根因定位——**外部模型服务对重负载长请求的请求级静默挂起**，非工程框架缺陷

---

## Executive Summary

**直接原因**：docgen agent（`ascendc-design-generator`）在 `pangu_ultra_moe` 模型上发起 stream 请求后，
**模型网关对请求完全零返回**（无 token / 无 usage / 无 error / 无 finish），opencode 空等流首包
超过 stall bound 180s，框架按设计 abort + kill serve。

**归因分层**（工程无关 → 模型服务请求级静默断流 → 断流后 resume/fresh 均无法恢复）：

| 层 | 结论 | 证据 |
|---|---|---|
| 工程框架 | ✅ **无关** | 同批 5ddae2 同框架 8 阶段零 stall；7dcdc3 前 5 个 design 阶段成功 |
| 模型服务整体 | ✅ **无关**（非全局故障） | 卡死同窗口 5ddae2 在同一服务跑 372 条 stream 全部正常 |
| 模型服务**请求级** | ✅ **故障点** | 每次卡死 = stream 发出后零返回（详见 §3） |
| 断流后恢复 | ❌ **resume 与 fresh 均无法恢复** | 同 session resume 4 次全卡 + degrade 到 fresh session 也卡（详见 §5） |

**一句话**：7dcdc3 在 docgen 阶段反复撞上 `pangu_ultra_moe` 模型服务的**请求级静默断流**
（stream 发出后首包零返回）。关键证据——**无论 resume 同一被 kill 的 session 还是
degrade 到从未卡过的 fresh session，下一次 tool:write 续流请求都再次静默断流**，
即该故障在 docgen 这一特定执行上持续复现，resume 无法恢复。框架的 turn_stall 探测 +
abort + infra_backoff + degrade-fresh 机制**全部正确工作**（把潜在无限死等收敛为有界
stall→重试→降级），但每次新请求都撞同一断流口，最终耗尽重试上限 halt。

---

## 证据链

### §1 决定性对照：同批同框架同服务，一成一败

同一父批 `eddf10`（2026-09-03 15:35:41 并行启动，同一框架代码/环境/NPU/模型服务）：

| run | 算子 | docgen 结果 | turn_stall abort |
|---|---|---|---|
| 5ddae2 | apply_adam_w（**单模板**） | ✅ 成功产出 39KB 详设文档 | **0 次**（全程 8 阶段零 stall） |
| 7dcdc3 | adaptive_avg_pool_3d（**双模板**） | ❌ 反复 6 次 abort 后 halt | 6 次 |

5ddae2 走完整条 `self_evolve_op` 链（requirement→general→template→tiling→synthesize→
**docgen 成功**→codegen→precision_debug→workflow done），全程零 stall → **证明工程框架
无系统缺陷**（若框架有等待/超时/编排 bug，5ddae2 必然同受）。

### §2 卡死时刻 = 模型 stream 发出后零返回

opencode.log 中每次 stall 的形态完全一致（以 16:35:32 第一次 docgen 卡死为例）：

```
08:35:32 message=process  session=ses_f999ab... messageID=msg_06668b...
08:35:32 message=stream   provider=92bpangu model=pangu_ultra_moe   ← 发起模型流请求
08:35:32 message="llm runtime selected" ...
        (此后到 08:39:09 被杀，3.5 分钟零日志 —— 无 token/usage/error/finish)
```

run.log 对应：`no new turn for 188s > stall bound 180s (chars static 180s) — last turn 26:
text,thinking,tool:write`。即 **agent 在等模型吐字，模型 188 秒一个字没吐**。

**关键**：这排除了"文件太大导致模型读不完""长输出写到一半停"等模型**行为**假设——
是**请求级完全无响应**（首包都没回）。

### §3 模型服务整体故障被排除（最强反证）

7dcdc3 docgen 反复卡死的 16:38–17:05 窗口内，5ddae2 **在同一模型服务上正跑 372 条
agent_stream**（codegen 16:16-16:41 + precision_diagnose 16:42-16:53），**全部正常、零卡死**。
若模型服务全局故障，5ddae2 必然同受。它没有 → 故障是**请求级/连接级**，非全局。

### §4 任务负载差异：docgen 是整链最重阶段，7dcdc3 比 5ddae2 更重

docgen skill 要求逐模板**全量装载** `tiling_results.json` 的 kernel 伪代码并**全量渲染**输出
（不压缩、不摘要，`每次 ≤ 10000 字符分段写`，但 kernel 段全量）。

| 输入/输出 | 5ddae2（单模板） | 7dcdc3（双模板） |
|---|---|---|
| docgen 输入 JSON 合计 | ~38 KB | **~71 KB**（tiling_results 37.7KB / 537行） |
| 产出详设文档 | 39 KB（ApplyAdamW_详细设计说明书.md） | 未产出（预计 >70KB，双份 kernel 伪代码） |
| tiling_results 模板键 | T1 | **T1 + T2** |

单 turn 最大 chars：5ddae2 docgen 有 **42685 chars**（成功），7dcdc3 有 22595 chars——单 turn
长度本身不是决定性差异（5ddae2 更长却成功）。但 **docgen 的总负载（读入+写出）7dcdc3 约为
5ddae2 的 2 倍**，是整条流水线最重的 LLM 任务。

### §5 关键证据：resume 与 fresh session 均无法恢复（静默断流持续复现）

docgen 共 abort 6 次，session 追踪如下：

| 时间 | session | 类型 | 结果 |
|---|---|---|---|
| 16:31:43 | ses_f999ab（首 spawn） | fresh | turn 1-25 正常，turn 26 `tool:write` 后断流卡死 |
| 16:38:40 | ses_f999ab | **resume 同 session** | 到 turn 2（tool:write）又卡死 |
| 16:42:18 | ses_f999ab | **resume 同 session** | 到 turn 2 又卡死 |
| 16:46:15 | ses_f999ab | **resume 同 session** | 到 turn 2 又卡死 |
| 16:50:52 | ses_f999ab | **resume 同 session** | 到 turn 2 又卡死 |
| 16:53:39 | resume 4x 失败 → degrade | **fresh ses_f9986b** | **从未卡过的全新 session 也在 17:01 stream 后断流卡死** |
| 17:05:17 | — | 最终 abort → halt | 耗尽 |

**决定性事实**：最后一次是 **degrade 到全新的 `ses_f9986b`**（此前从未被硬杀、上下文干净），
它也在 17:01:10 发出 stream 后**零返回 248s** 直到被杀（17:05:17 abort）。这排除了
「session 被反复硬杀后状态损坏」的归因——**fresh session 同样断流**。

**→ 修正结论**：故障不是 session 状态问题，而是**该 docgen 执行持续触发模型服务请求级
静默断流**——无论 resume 同一 session 还是换全新 session，下一个 `tool:write` 续流请求
都再次断流。resume 无法恢复，换 fresh session 也无法恢复。这正是「模型突然静默断流，
且对该执行反复出现」的特征。

### §6 7dcdc3 前半段说明断流非全局、特定于该执行的负载/时刻

7dcdc3 共 15 次 spawn、8 阶段成功，仅 2 个阶段 stall：
- **general-design**（15:48 卡 1 次，315s）→ respawn 后 15:52 成功（断流未复现）
- **docgen**（卡 5 次）→ 每次续流都断流，未能恢复

general-design 断流 1 次后未复现，docgen 却每次都复现——说明断流不是服务全局状态，
而是**特定执行（docgen 的重负载 + 该时段的请求形态）反复撞上**。docgen 是整链最重阶段
（§4），7dcdc3 双模板比 5ddae2 单模板重 2 倍——负载是「为什么偏偏 docgen 反复撞上」的
合理解释，但**根因是模型服务对这类重负载请求的间歇性静默断流**，非工程可修。

### §7 框架机制工作正常（非缺陷证据）

框架对每次 stall 的反应（run.log）：
```
abort: no new turn for Ns > stall bound 180s (chars static 180s) — killing opencode serve to unblock.
infra_backoff ... transient infra abort; sleeping Xs then re-spawning to sample a fresh gateway window
agent_degrade ... resume failed 3x >= resume_attempts 3; degrading to fresh spawn
```

这是**正确的容错设计**：把"模型服务静默挂起"从无限死等收敛为有界 stall → kill serve → 退避
重试 → resume 失败后 degrade fresh spawn → 最终诚实 halt（不产出坏文档、不放行空文档）。
§「外部 infra 故障不归框架修」——框架不为此加静默纠偏，留信号给上游（模型服务）判定。

---

## 为什么"当时模型能力较差"是合理的辅助解释

用户提示"当时运行的模型能力确实较差"。证据支持这是一个**叠加的放大因素**而非主因：

- `pangu_ultra_moe` 是第三方 MoE 模型（provider=92bpangu），非本仓/本地可控。
- 它对**重负载长请求**（docgen 的 37.7KB 输入 + 逐模板全量渲染 + 双份 kernel 伪代码 + 长文档
  写出）表现出**间歇性完全无响应**——轻负载请求（5ddae2 单模板、同 run 前半段）正常。
- 能力/服务较差的模型在重负载下更容易触发网关静默超时/断流，这与「轻负载全过、最重负载
  反复挂」的观测一致。

**它不是工程可修的**——工程无法也不应通过"给弱模型加静默重试兜底"来掩盖外部服务缺陷
（§1.2 可诊断性、裁决族：不建掩盖错误的兜底）。

---

## 验证 / 闭环动作

本分析已通过 fresh-session 也断流排除「session 状态损坏」。剩余唯一待闭环项：确认断流在
**模型服务侧状态变化后**是否消失。需在**模型服务恢复/更换后**重跑 7dcdc3 的 docgen：
- 若通过 → 闭环（断流随模型服务状态消失，框架无碍）。
- 若仍卡 → 进一步佐证是 docgen 特定负载触碰模型侧某上限，届时可评估把 docgen 的单次渲染
  拆小或换更强模型（属 skill/任务层优化，是独立改进，与本次"谁的问题"判定分开）。

当前无需改任何工程代码。

---

## 附录：本批同族 issue-analysis

- `20260803-cannbench-eval-507035-root-cause.md` — apply_adam_w debug 20/20 而 eval 1/20（step-119 已修）
- `20260803-precision-debug-binary-inconsistency.md`
- `20260803-warmup-trigger-507035-analysis.md`
- `20260803-sync-fix-attempt-failed.md`
