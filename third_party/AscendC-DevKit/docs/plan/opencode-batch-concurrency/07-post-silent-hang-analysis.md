# 07 — 单算子 design-generator POST 后 opencode silent 重试卡 3600s — 方案分析（L3）

> 对应 L1 `06-problems.md` P117、memory [[batch-design-primary-mcp-hang]]、[[opencode-silent-swallow-gateway-error]]。
> 阶段：**已冻结 + 已实施（2026-07-27）路线 C**。
> **修订（2026-07-27）**：用户否决 A（tail opencode.log 违 §1.7 仓自闭环），路线收敛为**仅 B（turn-stall）+ trip reason 带 tool 诊断 + 2 阈值 config**。下文 §4-§9 已同步修订。

## 1. 问题陈述

P115（G+A）修后，单算子 design-generator POST message 后 opencode silent → `message_timeout=3600`（1h）hard cap 空烧。run `20260725-152037-8a4efa` `900f0c/docgen` 实证（spawn 13:32:28 → 3600s abort 14:32:36）。同期 ed4992/docgen 正常（1142s）。

## 2. 根因（opencode 源码 + 日志铁证）

### 2.1 opencode 内部：网关 1313 + session 层无限重试 + silent 吞

- **网关 1313 Fair Usage Policy 限流**（账号被限频）：opencode.log 记 184 次 `stream error [1313]`（指数 backoff 2→1024s + backoff 到顶后重置多轮）。
- **executor 层 `MAX_RETRIES=2`（有限）对 1313 不生效**：`executor.ts:281 if (status<400) return response` —— 1313 是 HTTP 200 body 业务码，当成功放行，不进 `retryStatusFailures` 重试。
- **session 层 `SessionRetry.policy` 无次数上限**：`retry.ts:181 Schedule.fromStepWithMetadata` 只靠 `retryable()` 返回 undefined 停，否则永远重试。1313 经 `message-v2.ts` 分类（`ResponseStreamError` isRetryable=**true 硬编码**，或 `APICallError` ai-sdk isRetryable）→ `retry.ts:75 if (!isRetryable && !(status>=500)) return undefined` 不命中 → 无限重试（docgen 184 次）。
- **silent 吞**：opencode POST 不返回 framework（自己无限重试），framework 收不到 1313 错误码。

### 2.2 framework 侧：keepalive 被 SSE noise 骗

- `_subscribe_sse._handle`（`opencode_backend.py:371`）对 **ANY** SSE frame 刷新 `last_event_ts`（注释"ANY parsed frame = liveness"）。
- opencode 重试期持续发 SSE noise（loop/permission/skill frame，37min 静默窗内 opencode.log 1385 行活动）→ last_event_ts 持续刷新 → keepalive **误判存活** → 不 trip → 等 3600s hard cap。

### 2.3 framework 已认识 1313 但信号不可达

- `_RATE_LIMIT_MARKERS`（`_shared.py:411-415`）含 `[1313]`/`Fair Usage Policy`，归 429 SOFT（可退避重试）。但 opencode 吞了 1313，framework 的 POST 收不到 → `_is_rate_limit_error` 没机会运行。问题不在分类，在信号不可达。

## 3. 根因演进（last=None 假设证伪）

初判根因「keepalive `last_event_ts=None`（POST 后从未活跃）盲区」。**opencode.log + run.log 实证证伪**：
- run.log docgen **turn 2-12 有 121 行 agent_stream**（13:32→13:55），last_event_ts 从未 None（POST 后 opencode 持续发 SSE）。
- 真因是 **last 持续刷新（SSE noise）但 keepalive 误判存活**（P115 §3 同型盲区），不是 last=None。

P117 与 P115 是**同型盲区**（SSE noise 骗 keepalive），触发源不同（P115=MCP 握手 SSE 心跳；P117=网关 1313 重试的内部 SSE 活动）。

## 4. opencode 不可改约束

opencode 是只读外部依赖（session 层无限重试 + silent 吞是 opencode 设计/缺陷）。framework 只能：**观测 opencode 外部行为 + 止损 + 留信号**。不能改 opencode 的重试策略 / silent 行为。

核心困境：framework 无法用 SSE 区分「合法长 tool」（turn 7 read 22min，0 chars + noise frame）vs「卡住重试」（1313，0 chars + noise frame）——两者 SSE 表现一样。

**用户决策**：不读 `opencode.log`（§1.7 仓自闭环——framework 不依赖外部文件）。framework 不去精确区分二者，而是用 turn-stall gate 统一兜底（无新 turn 即 trip），并把"卡住前最后 turn 在做什么"（turn 号 + tool 活动）作为诚实信号交给操作者——是否终止、是否给合法长 tool 更多空间，由用户按 config + run.log 判断，framework 不替用户猜。

## 5. 候选方案（§1.2 四把尺子）

| # | 方案 | 可维护 | 可扩展 | 可诊断 | 架构合理 | 评估 |
|---|---|---|---|---|---|---|
| A | **tail opencode.log** 检测 stream-error storm → trip（reason 含 1313，复用既有 `_RATE_LIMIT_MARKERS`）+ 诚实反馈 run.log | △ log 格式依赖 opencode 版本 | ✓ 任何 opencode 内部异常（log 有信号就覆盖） | ✓✓ 直接暴露 SDK 真实状态 | ✓ keepalive 产权，业务语义（真实错误） | **主修复（PRIMARY）** |
| B | **turn-stall 兜底**：`state["turn_ts"]` 超 turn_stall_s 未更新 → trip | ✓ | △ 只覆盖"无 turn"类 | △ | ✓ | **兜底（A 漏的卡法）** |
| C | **A + B 组合**，所有阈值 config 可配 | △ A 格式依赖 | ✓✓ | ✓✓ | ✓ | **选定** |
| D | framework 重建成 opencode 内部状态（in_flight_tool 状态机）区分长 tool vs 卡住 | ✗ 逐案打补丁，每新卡法加判据 | ✗ | △ | ✗ §1.10 机制特征代理 | 否决（逐案） |

**初决策（路线 C = A+B）**：opencode 不可改 → 不用被骗的 SSE 心跳，不用 3600s 盲目硬墙。A（tail opencode.log）+ B（turn-stall）+ 阈值 config 可配。

**修订决策（仅 B，2026-07-27）**：用户否决 A——tail opencode.log 违 §1.7 仓自闭环（framework 不读外部文件）。收敛为：**B turn-stall gate 作主止损**（无新 turn 即 trip，统一覆盖卡住重试 + opencode 内部卡），**trip reason 带 tool 诊断**（卡住前最后 turn 号 + block_types，操作者知道 SDK 在做什么，合法长 tool 有心理准备），**2 阈值 config 可配**（turn_stall_s + message_timeout_s，0=disabled；合法长 tool 调大 turn_stall_s 留空间，不用硬超时兜底）。仍符合用户「诚实反馈 SDK 内部 + 判断权交出 + 不要硬超时兜底」，且不引入外部文件依赖。

## 6. 路线 C 实施（framework 侧，修订后仅 B）

### B — turn-stall gate（主止损 + 诚实信号）
- `_new_sse_log_state` 加 `turn_ts`；`_handle_sse_event` turn++（message.updated role=user）旁盖 `turn_ts`（对称 `last_event_ts`），并在新 turn 时重置 `block_types`。
- `_handle_sse_event` 对 message.part.updated 的 text/thinking/tool_use block 累积进 `block_types`（tool 记 `tool:<name>`）。
- `_post_message_watched` keepalive loop 判据：`turn_ts` 超 `turn_stall_s` 未更新 → trip `_KeepaliveAbort`（reason=`no_turn_progress`）。**trip reason 带 `state["turn"]` + `state["block_types"]`**（卡住前最后 turn 的活动，sorted join）——操作者可见"卡在 turn 12: tool:read"，对合法长 tool 有心理准备。0=disabled。
- 不读 opencode.log（§1.7）。

### config（`orchestration-config.json` timeouts section，全部可配）
2 字段（`runtime_config.opencode_timeouts()` reader，先例 `resume_limits()`）：`opencode_turn_stall_s`（300）、`opencode_message_timeout_s`（3600，0=disabled）。流转：reader → dispatcher 3 处 `build_agent_backend` kwargs（turn_stall_s + message_timeout）→ `OpenCodeBackend.__init__`（factory inspect 自动过滤）。

`message_timeout` 不做删/留决策——做成可配（0=disabled），与 stage 超时同语义。用户在 config 定：0=纯依赖 turn-stall/keepalive（符合「不要硬超时兜底」），>0=兜底值。

## 7. 验证

- **UT**（`tests/ut/capabilities/test_p117_turn_stall_watchdog.py`，9 用例）：turn-stall trip（reason 带 turn + tool:read）/ sorted blocks join（text,tool:bash,tool:read）/ 无 activity 优雅降级（turn=0 不打印空 ':'）/ turn>0 但无 block（"last turn 5" 无空 ':'）/ 0=disabled / SSE handler stamp turn_ts + 重置 block_types / block 累积 tool:<name> / 回归（正常完成不误杀）/ message_timeout=0 disabled。
- **config UT**（`tests/ut/orchestration/test_runtime_config.py::TestOpencodeTimeouts`，8 用例）：reader 解析（defaults/override/0=disabled/negative fails-fast/bool rejected/section-not-object/real config）。
- **全量 UT**：3070 passed / 7 skipped（cann-bench 环境跳过 §3.7）。P-BC3 keepalive 既有 UT 不回归。
- **真实链路 ST（§3.9）**：新增 `tests/st/test_turn_stall_e2e.py::test_turn_stall_gate_aborts_real_opencode_spawn`（`@llm` + `@heavy_llm`）——turn_stall_s=8s + 长纯生成（1500 字，无 tool）→ 生成期间 turn_ts 不更新 → gate 真实 trip；断言 aborted='hard_timeout' + run.log 含 `no new turn`/`turn_stall` 签名（区分 hard cap）。**默认不跑**（conftest:119 `not heavy_llm`，§3.11），用户 `-m heavy_llm` 决策。生成长度非确定（§3.10，模型 <8s 完成则不 trip，re-run）。既有 `test_hard_timeout_e2e` 守护 keepalive 主链路不退化。

## 8. 风险

1. **turn-stall 误杀合法长 tool**：`turn_stall_s` 默认 300s 可配；合法长 tool（如长 compile / 大文件 read）超 300s 无新 turn 会被 trip。缓解：① trip reason 带 tool 活动，操作者可判断是合法长 tool 还是卡住；② `turn_stall_s` 调大（用户定，给合法长 tool 留空间）；③ `message_timeout_s=0` 完全禁用硬超时（纯依赖 turn-stall，符合「不要硬超时兜底」）。docgen turn 7 read 22min 是 1313 病态（非正常 read），trip 是对的。
2. **不读 opencode.log 的代价**：放弃 opencode.log 的精确错误信号（1313 文本）。换得 §1.7 仓自闭环（framework 不依赖外部文件）。turn-stall 统一兜底覆盖卡住重试 + opencode 内部卡，但 reason 不再携带 1313 具体错误码——下游 `_is_rate_limit_error` 不会因此把 turn-stall 当 429 backoff resume（turn-stall reason 无 1313 marker，走 spawn crash-salvage 重试，与 429 退避 resume 不同路径）。这是相对 A 的可诊断性回退，可接受（§1.7 优先）。

## 9. 避免重复分析

未来再遇「单算子 agent POST 后 silent 卡 1h」，先读本 L3：
- 根因 = opencode session 层无限重试（`SessionRetry.policy` 无上限）+ silent 吞网关错误 + SSE noise 骗 keepalive（`:371` ANY frame）。**不是 last=None**（已证伪），不是并发 DB lock（P115 G 修了），不是 MCP 握手（A 修了）。
- opencode 不可改，framework 侧路线 C 修订版（turn-stall gate + trip reason 带 tool 诊断 + 2 阈值 config，**不读 opencode.log**）已实施。
- 真根因（opencode 无限重试 + silent 吞）在 opencode 侧，framework 只止损不根治。
