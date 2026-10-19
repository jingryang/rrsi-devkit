# batch 20260812-001959 — 实施方案（L4）

> 配套：L1 事实 `batch-20260812-001959-3of3-apierror-halts-issues.md`（P1/P2/P3）；L3 取舍 `batch-20260812-001959-3of3-apierror-halts-analysis.md`（A 统一 resume / B 可观测 / C 配置规避）。
> 本层只记**改哪个函数、什么顺序、怎么验证**。实施者：Claude。日期：2026-08-12。
> **范围（本期 L4）**：A（服务端错误统一有限次原地 resume）+ B（主日志可观测）。C（thinking 配置规避）为调研态，不在此期实施。

---

## A. 服务端错误统一有限次原地 resume

### A1. 改动点（最终实现：判定 + 预算 + 策略共享，adapter 只留机制动作；§2.5 单一来源）

**方案选型**（L3 A+，2026-08-12 拍板 + 两次修正）：把「该不该处理 / 怎么处理（backoff 还是立即 resume） / 预算推进」抽到 `_shared.py` 单一来源；两 backend（opencode/sdk）各在自己的错误获取 seam（opencode `_message_error` / sdk `_crash_text`）拿到错误文本后调用。adapter 只保留「sleep + resume 动作」（同步/异步差异）与特有条件（如 sdk 无 session_id / D2 transient）。

**A1.1** `_shared.py` 新增三个共享 helper：
- `should_server_backoff(text)`——黑名单排除判定：非空错误文本且非 infra → True；infra → False；空 → False。
- `advance_backoff(attempt, elapsed_s, *, base_s, factor, max_total_s, max_retries)`——backoff 预算推进，返回 `(sleep_s, next_attempt, next_elapsed_s)`；耗尽 → `sleep_s=None`。
- `server_backoff_strategy(text)`——**恢复策略分离（根治空等）**：429/503 → `"backoff"`（需 sleep 等窗口）；其他非 infra 服务端错误（APIError/type validation/未知）→ `"resume"`（**立即续跑不 sleep**，误判时只浪费一次重试预算，不空等）；infra/空 → `None`。

**A1.2** `opencode_backend.py` gate 用 `server_backoff_strategy` 分离（`_message_error` 只返回错误文本）：

```python
err = self._message_error(message)
if not err:
    break                    # 成功 → build_result
strategy = server_backoff_strategy(err)
if strategy is None:
    Logger.error(f"Agent {agent_name} infra (un-retryable) message error: {err}")
    break                    # infra → P116 infra halt
Logger.warn(f"Agent {agent_name} server-side message error (retryable): {err}")
if strategy == "backoff":    # 429/503 → 指数退避 sleep 等窗口（有界）
    sleep_s, rl_attempt, rl_elapsed_s = advance_backoff(...)
    if sleep_s is None:
        Logger.warn(f"... backoff exhausted ... → halt: {err}")
        break
    time.sleep(sleep_s)
else:                        # "resume" → 立即续跑同一会话，不 sleep（不空等）
    rl_attempt += 1
    if rl_attempt >= self._rl_max_retries:
        Logger.warn(f"... server resume exhausted ... → halt: {err}")
        break
# → resume 同一会话（"继续"）
```

**A1.3** `sdk_backend.py` gate 对齐（claude backend）：
- 入口 `should_server_backoff(_crash_text) and not _is_transient_error(_crash_text)`，内部按 `server_backoff_strategy(_crash_text)` 分离：429/503 → backoff sleep；其他 → 立即 resume（不 sleep）。
- **判定基于 `_crash_text`（last_result_text or last_exc + stderr）而非裸 last_result_text**——SDK 内部失败时 last_result_text 可能含正常文本，崩溃上下文更可靠承载错误措辞。
- **必须排除 `_is_transient_error`（SSE 流故障，如 "Content block not found"）**：transient 走原 D2 立即 resume；被吞进 backoff 会真实退避 sleep 致卡死——`test_no_progress_gate_stops_early` 回归实证（20260812）。opencode 无 D2 transient，故仅 sdk 需此排除。
- 耗尽诊断保留类别词（P131b honest-wording）：429 → "hard quota"；其他 → "halt"，均附错误原文；`not consumer.session_id` 特有条件保留。

**A1.4** `rate_limit_*` 预算经 `runtime_config.resume_limits()` ← `orchestration-config.json` `agent` 段注入；**`rate_limit_backoff_max_total_s` 默认 900→600**（runtime_config 默认常量 + 两 backend 构造默认 + 配置权威源三处同步，20260812）。

**语义对照**（改动前后行为不变的部分，确保纯增量）：
| 错误 | 改前 | 改后 |
|---|---|---|
| 成功（opencode err 空 / sdk 未 crashed） | break | break（不变） |
| infra（401/403/quota/config） | break（不 backoff） | break + Logger.error（不变，仅补日志） |
| 429/503 | in-session backoff sleep | backoff sleep（不变，预算 900→600） |
| **APIError/type validation/未知**（opencode 本批实证） | **break → crash → partial → halt** | **立即 resume（不 sleep，有限次）** |
| **503/APIError/未知**（sdk，原缺口） | 走 D2 transient 或 break | **立即 resume（不 sleep，对齐）** |
| SSE transient（sdk，如 Content block not found） | D2 立即 resume | D2 立即 resume（不变，排除出 backoff） |

### A2. 已完成（非待办）
- **sdk_backend gate 对齐**已实施（A1.3），不再是后续项。
- **P129 测试修复**（§3.4，非本次方案引入）：`test_p129_partial_halt_reason.py` 的 `aborted="turn_stall"` 会触发 runner `infra_backoff` 真实 sleep（20s→40s→80s 共 ~140s）——`_run` mock `runner.time.sleep` 让退避快速走完，测试意图（aborted → last_error 合成）不变，4 passed 0.19s。

### A3. 验证（TDD）
1. 现有 rate_limit/soft_retry/resume/infra/capabilities UT 全部保持通过（非 infra 判定不变）。
2. 新增 UT（覆盖 A+ 全部核心行为）：
   - `test_p131_soft_retry_markers.py`——`should_server_backoff` 黑名单排除语义（429/503/APIError/thinking/type validation/未知→True；infra/空→False）+ `advance_backoff` 预算推进/耗尽/封顶。
   - `test_opencode_backend.py`——APIError/thinking→backoff（`test_server_error_thinking_retryable_backoff`）；infra→无 backoff（`test_infra_message_error_no_backoff`）。
   - `test_session_resume.py`——sdk APIError/thinking→backoff resume（`test_thinking_error_sleeps_then_resumes_same_session`）；sdk infra→无 backoff（`test_infra_message_error_no_backoff`）。
3. 测试实现注意：mock `asyncio.sleep` 须用 `async def`（普通 lambda 返回 None → `await None` TypeError）。
3. 全量 UT（§3.2）无回归。

---

## B. 主日志可观测（服务端错误不再静默）

### B1. 改动点（随 A1.2 一并落地）
- **A1.2 的 `Logger.error`（infra）与 `Logger.warn`（可重试服务端错误）即 B 的核心**——APIError/type validation 进主日志，不再只存 transcript。
- backoff 耗尽 break 处（`opencode_backend.py:700-706` 已有 `Logger.warn` "soft rate-limit/unavailable: backoff exhausted"）自然带出错误文本——但当前文案仅限 429/503 措辞，**A1.2 改后对 APIError 也走同一文案**（"server-side message error ... backoff exhausted"），错误原文已在 `Logger.warn` 首行带出。

### B2. 已知缺口（本期记录，是否修视 A 落地后评估）
- **forkjoin 分支 halt 时 P129 own_error 未带 APIError 进主日志**（grid halt 段只有 `[partial]` + `fail_strategy=halt`）。P129 合成在 runner.py:638 有实现，但 forkjoin 分支路径未生效——需专项定位（可能 last_agent.metrics.failure_reason 未传 / forkjoin 包装层 own_error 非 None）。**待 A 落地后再查**，避免一次改动面过大。

---

## 实施顺序

1. A1.1 import + A1.2 gate 改动（opencode_backend.py）。
2. 新增/确认 UT（gate 语义），跑定向 UT。
3. 全量 UT 回归。
4. （A2）记录 sdk_backend 对齐为后续项。
5. （B2）记录 forkjoin own_error 暴露缺口，A 落地后专项。

## 不做（本期）
- C（thinking 相关）——调研态，第一步 = **C0 最小复现实验**（TUI vs SDK 对照，验证 APIError 真实触发条件）；在充分测试证明前不把"thinking 回传不一致"当根因（用户 2026-08-12：TUI 正常是强反证 + 早期 3 次 resume 成功反证"resume 必坏"）。见 L3 C 节。
- sdk_backend gate 对齐、forkjoin own_error 专项——标注后续。
