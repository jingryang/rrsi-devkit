# S1a 实施方案 — backend 硬墙（协议 + stub + opencode + runner 接线）

> 层级：**L4 / 实施方案**。记录「改哪个函数、什么顺序、怎么验证」。
> 决策依据见 `02-analysis.md`（L3）D1–D4。**claude 硬墙在 S1b**（`04-impl-s1b-claude-hard-wall.md`，方案 A/anyio），本切片不含。

## 范围

让 `spawn(deadline_monotonic)` 协议落地，**stub + opencode** 实现硬墙、**runner** 传入剩余 deadline、**sdk** 仅加签名透传（硬墙 S1b 补）。落地后：deadline 到点时 stub/opencode 的 spawn 一定返回（带 `aborted="hard_timeout"`），claude 暂时仍软（S1b 补硬）。

## 改动清单

### 1. `capabilities/agent/backend.py`（协议）
- `AgentResult` 加字段：`aborted: str | None = None`（None=正常；`"hard_timeout"`/`"cancelled"`/`"keepalive"`=被硬终止）。
- `AgentBackend.spawn` 加参数：`deadline_monotonic: float | None = None`（monotonic 时间墙；None=不设硬墙，保持原行为）。

### 2. `capabilities/agent/stub_backend.py`（UT 对象）
- `spawn` 签名加 `deadline_monotonic`，记录进 `spawn_calls`。
- 硬墙逻辑：`if deadline_monotonic is not None and time.monotonic() >= deadline_monotonic:` → 返回 `AgentResult(agent_name, status="fatal", aborted="hard_timeout")`，不返回 canned response、不落产物。

### 3. `capabilities/agent/sdk_backend.py`（**S1a 仅加签名透传**）
- `spawn` / `_spawn` 签名加 `deadline_monotonic`，**暂不实现硬墙**（S1b 的 A/anyio 实现）。加注释标记 `# S1b: hard wall implemented at spawn layer (anyio.fail_after)`。
- 理由：runner 会给所有 backend 传 `deadline_monotonic`，签名不接受会 TypeError；claude 硬墙单独切片。

### 4. `capabilities/agent/opencode_backend.py`（接外部 deadline）
- `spawn` 签名加 `deadline_monotonic`。
- 入口算 effective timeout：`if deadline_monotonic: eff = min(deadline_monotonic - now, self._message_timeout)`，传入 `_post_message_watched`（局部覆盖 `self._message_timeout`，不改实例）。
- `_KeepaliveAbort` 路径（`_post_message_watched` raise 处）填 `aborted="hard_timeout"`；hard wall 路径同理。

### 5. `orchestration/kernel/runner.py`（传入剩余 + event）
- `_execute_spawn_agent`（runner.py:557）：spawn 前算 `remaining = min(workflow_deadline, stage_deadline) - now`（两者皆 None → None），传 `deadline_monotonic=now + remaining`（或直接传 deadline 绝对值）。
- spawn 后 `if agent_result.aborted:` → emit `agent_aborted` event（agent_name + reason + stage）。

### 6. `orchestration/kernel/event.py`
- 加 `agent_aborted(agent_name, reason, stage)` event 构造器（仿 `output_truncated`）。

### 7. UT `tests/ut/capabilities/test_hard_timeout.py`（新建）
- `test_stub_deadline_passed_returns_aborted`：`spawn(deadline_monotonic=now-1)` → `result.aborted == "hard_timeout"` + `status == "fatal"` + 无产物落盘。
- `test_stub_no_deadline_returns_canned`：`spawn(deadline_monotonic=None)` → 返回 canned（原行为不变）。
- `test_stub_deadline_future_returns_canned`：`spawn(deadline_monotonic=now+100)` → 返回 canned（未到点）。
- `test_spawn_calls_record_deadline`：`spawn_calls[-1]["deadline_monotonic"]` 记录正确。

## TDD 顺序

1. 写 `test_hard_timeout.py`（**红**：AgentResult 无 aborted / spawn 不接受 deadline_monotonic）。
2. `backend.py` 加字段 + 参数（协议层）。
3. `stub_backend.py` 实现硬墙（**绿**：stub 三个 UT 过）。
4. `sdk_backend.py` 加签名透传（不实现）。
5. `opencode_backend.py` 接外部 deadline + UT（用现有 opencode UT 的 server mock 范式）。
6. `runner.py` 传 deadline + event + UT（用 stub backend 验 runner 传了 deadline、aborted 时 emit event）。
7. 全量回归 `pytest tests/ut/`。

## 验证

- 新增 `test_hard_timeout.py` 全绿。
- 全量 UT 零回归（基线见 memory `ut-preexisting-env-failures`：2026-07-15 全绿 2138 pass/7 cann-bench skip）。
- **不跑** heavy_llm ST（claude/opencode 真实硬超时属 S5，§3.11 用户确认）。

## 不在 S1a 范围

- claude 硬墙（A/anyio）→ S1b（`04-impl-s1b`）。
- `teardown` 钩子 / `uninterruptible` → S3。
- SIGTERM handler / 进程组 killpg / atexit → S4。
- `aborted` 的 stage 消费（precision-debug git reset 等）→ S2/S3 各 stage L4。
- `_generate_report` 收口 → S3。
