# S1b 实施方案 — claude SDK backend 硬墙（方案 A：anyio.fail_after）

> 层级：**L4 / 实施方案**。记录「改哪个函数、什么顺序、怎么验证」。
> 决策依据见 `02-analysis.md`（L3）D1（调研中从 B' 改判 A）。协议层（`AgentResult.aborted` / `spawn(deadline_monotonic)`）已由 S1a 落地，本切片只补 **claude backend 的硬墙物理实现**。

## 范围

让 claude SDK backend 的 `spawn` 在 `deadline_monotonic` 到点时**真正中断** `_spawn`（query 流式 + CLI 子进程），到点必返回（带 `aborted="hard_timeout"`），并依赖 SDK `transport.close()` 的 SIGTERM→SIGKILL escalation 完成秒级优雅退出 + 保留 session sidecar 可 resume。

## 方案选型：B' → A（调研中改判）

S1a 时 L3 选定 B'（`ClaudeSDKClient` async-with + `asyncio.timeout` 打断 receive 循环）。S1b 实施前深 probe 发现 B' 有隐藏代价，改判 **A（anyio.fail_after 包整个 `_spawn`）**：

| 维度 | B'（原选） | A（改判） |
|---|---|---|
| `_spawn` 改动 | 整体重写：`query()` 函数式 → `ClaudeSDKClient` 上下文（connect/query/receive_messages），stall/resume/429/sidecar/transcript 全迁 | **零改动**：spawn 入口加薄 wrapper |
| receive 自然停 | 否（流式，`ResultMessage` 后不停）→ 仍需自包中断 | 不涉及（cancel 整个 task） |
| 依赖 | 纯 asyncio | anyio（已是 SDK 传递依赖，零新增） |
| shield 认的取消 | `asyncio.timeout` 绕开 cancel-飞-中跑 close 的问题 | anyio cancel scope 正是 shield 认的取消方式 |
| 回归面 | 大（碰成熟核心） | 小（只碰 spawn 入口） |

详见 L3 D1 的演进叙事与「最初否 A 的两条理由为何站不住」（anyio 已是传递依赖 + asyncio backend 下 `asyncio.sleep` 原生可用无需替换）。

## 改动清单

### 1. `capabilities/agent/sdk_backend.py`（唯一改动文件）

- `import anyio`（保留 `import asyncio`）。
- `spawn`（sdk_backend.py:179）重写为 `_timed` wrapper：
  ```python
  def spawn(self, ..., deadline_monotonic=None):
      start_ms = int(time.time() * 1000)
      async def _timed() -> AgentResult:
          coro = self._spawn(...)               # 主体零改动
          if deadline_monotonic is None:
              return await coro
          with anyio.fail_after(max(deadline_monotonic - time.monotonic(), 0.001)):
              return await coro
      try:
          return anyio.run(_timed)              # asyncio backend
      except TimeoutError:                      # 到点：cancel 已结束才抛
          Logger.warn(f"{agent_name} hard timeout ...; SDK close escalation killed CLI")
          return self._build_result(agent_name, consumer=None, crashed=True,
              crash_reason="hard timeout (deadline_monotonic reached)",
              artifacts={}, transcript_path=None, attempt=0,
              start_ms=start_ms, aborted="hard_timeout")
  ```
- `_spawn` 主体**一行不动**；`_spawn` 内 `deadline_monotonic` 不直接消费（spawn 层 cancel 整个 task）。
- **`asyncio.sleep`（429 backoff）保留不动** —— anyio backend 下原生可用，且 3 个 429 UT 的 `monkeypatch sdk_backend.asyncio.sleep` 契约不破。

### 关键不变式（为何 A 能让 shield escalation 正常跑）

- `subprocess_cli.py:641-650` caveat：`transport.close()` 的 `anyio.CancelScope(shield=True)` **只防 anyio cancel scope 的取消；raw asyncio cancel 会穿透**。
- A 用 `anyio.fail_after` → cancel 是 anyio cancel scope 发起 → shield 正常生效 → close 的 SIGTERM→SIGKILL escalation 不漏跑 → CLI 不孤儿。
- `anyio.run` 用 asyncio backend → `asyncio.sleep`（_spawn 内 429 backoff）原生工作；被 cancel 时抛 `CancelledError`，fail_after 在 scope 退出转为 `TimeoutError`，被 spawn catch。

### 可 resume 保证（构造性，§1.2）

硬终止场景 consumer 随 `_spawn` 栈丢失，但：
- sidecar 在 session_id 捕获瞬间已 flush 落盘（`_write_session_sidecar`）。
- crash 时不清除（`if not crashed: clear`）。
→ resume 靠 sidecar 恢复，不依赖 in-flight consumer。

## TDD 顺序（已执行）

1. 先复现 429 测试被 asyncio→anyio import 误伤（`ImportError: ...sdk_backend.asyncio`）→ 决定保留 `import asyncio` + 429 backoff 用 `asyncio.sleep`（最小改动，不碰 429 测试契约）。
2. `sdk_backend.py` 落 `_timed` wrapper（`anyio.run` + `fail_after`）。
3. `test_hard_timeout.py` 加 3 个 claude spawn 层 UT：
   - `test_claude_spawn_hard_wall_aborts_overrun`：monkeypatch `_spawn` 为 30s 慢协程，`deadline=now+0.2` → `aborted=="hard_timeout"` + `status=="fatal"` + `elapsed<5s`（证硬墙 cancel，非慢路径自然结束）。
   - `test_claude_spawn_no_deadline_runs_spawn`：`deadline_monotonic=None` → 不套 fail_after，`_spawn` 正常返回，`aborted is None`。
   - `test_claude_spawn_deadline_in_future_runs_to_completion`：deadline 在未来 + `_spawn` 快速完成 → 未到点，`aborted is None`。
4. `pytest tests/ut/capabilities/` 全绿（292 passed，含 11 个 test_hard_timeout + 3 个 429）。
5. 全量 UT 回归。

## 验证

- `test_hard_timeout.py` 11 个全绿（8 stub/opencode/runner + 3 claude spawn 层）。
- `tests/ut/capabilities/` 全绿（292 passed）。
- 全量 UT 零回归。
- **不跑** heavy_llm ST（claude 真实硬超时秒级 kill 属 S5，§3.11 用户确认）。

## 不在 S1b 范围

- `aborted` 的 stage 消费（teardown 善终、precision-debug git reset 等）→ S2/S3。
- `teardown` 钩子 / `uninterruptible` → S3。
- SIGTERM handler / 进程组 killpg / atexit 兜底 → S4（A 已让 SDK close escalation 正常跑，S4 是框架进程级的外层保险）。
- heavy_llm ST（claude/opencode 真实硬超时全流程）→ S5（用户确认，§3.11）。
