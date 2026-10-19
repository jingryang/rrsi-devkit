# S4 实施方案 — 进程级外层优雅退出（SIGTERM + 进程组 + atexit）

> 层级：**L4 / 实施方案**。决策依据见 `02-analysis.md`（L3）D7。S1（backend 硬墙）已让 SDK close escalation 正常跑；S4 是**更外层**的进程级保险——外部信号（SIGTERM）/ 进程退出时也优雅（save state + 清子进程 + 不留孤儿）。这是用户「各种情况下各种粒度的退出都要优雅」的最外层。

## 范围

三部分，各自独立、互补：

1. **opencode 进程组 killpg**（最具体、最高价值）：opencode serve 经 `_start_serve` 拉起，其子进程（engine MCP stdio）目前 `_stop_serve` 只 `proc.terminate/kill` **杀不到** → 孤儿。改 `start_new_session=True` + `os.killpg` 杀整组。
2. **atexit 兜底**：框架退出（正常/未捕获异常/SIGTERM 中断）时，若 opencode serve 还在跑（spawn 中途退出未 `_stop_serve`），atexit 兜底清掉。与 claude SDK 自带 `_kill_active_children` 双保险。
3. **SIGTERM→KeyboardInterrupt**：注册 SIGTERM handler 抛 KeyboardInterrupt，**复用** dispatcher 现有 `except KeyboardInterrupt` 路径（runner.cancel + save state + EX_SIGINT）——让 SIGTERM 行为等同 Ctrl+C。

> claude CLI 子进程由 claude_agent_sdk 的 SubprocessCLITransport 管理 + SDK 自带 `_kill_active_children` atexit，**不在 S4 改动范围**。S4 只管**我们自己的**子进程（opencode serve）。

## 改动清单

### 1. `capabilities/agent/opencode_backend.py`（进程组 + atexit 追踪）
- 模块级 `_ACTIVE_SERVE_PROCS: set[subprocess.Popen]` + 一次性 `atexit.register(_atexit_cleanup)`（首次 import 或首次 `_start_serve` 时注册）。
- `_start_serve`：`Popen(..., start_new_session=True)`（serve+其子进程成新会话/进程组）；`_ACTIVE_SERVE_PROCS.add(proc)`。
- `_stop_serve`：`os.killpg(os.getpgid(proc.pid), SIGTERM)` 杀整组 → `proc.wait(5)` → 超时 `os.killpg(pgid, SIGKILL)`；`_ACTIVE_SERVE_PROCS.discard(proc)`；保留 serve_log_handle close。
- `_atexit_cleanup()`：遍历 `_ACTIVE_SERVE_PROCS` 残留项，对每个 `_stop_serve`（best-effort）。

### 2. `application/dispatcher.py`（SIGTERM handler）
- 模块级 `def _sigterm_to_keyboard_interrupt(signum, frame): raise KeyboardInterrupt`。
- dispatch 主 try 前：`signal.signal(SIGTERM, _sigterm_to_keyboard_interrupt)`（try/except 守非主线程/不支持）；保存旧 handler。
- 现有 `finally`（D8 report）里恢复旧 SIGTERM handler。
- **复用** 现有 `except KeyboardInterrupt`（cancel + save + EX_SIGINT）——不加新分支。

## TDD

### 进程组（S4a）
- UT：`_start_serve` 创建的 proc，`_stop_serve` 用 `os.killpg`（mock `os.killpg`/`os.getpgid` 断言整组被 SIGTERM→SIGKILL）；`start_new_session=True` 传入 Popen（断言 Popen kwargs）。
- 用 fake proc（pid 固定）避免真起子进程。

### atexit 追踪（S4b）
- UT：`_start_serve` 后 proc 在 `_ACTIVE_SERVE_PROCS`；`_stop_serve` 后移除；`_atexit_cleanup` 对残留 proc 调 `_stop_serve`。

### SIGTERM（S4c）
- UT：`_sigterm_to_keyboard_interrupt(None, None)` raises KeyboardInterrupt。
- dispatch 注册：mock `signal.signal` 断言 SIGTERM 注册了 handler + finally 恢复（集成级，可选）。

## 验证

- S4a/S4b/S4c UT 绿；全量 UT 零回归。
- **不跑** heavy_llm ST（真机 SIGTERM/进程组秒级 kill 属 S5，§3.11 用户确认）。

## 不在 S4 范围
- claude CLI 子进程（SDK 自管 + `_kill_active_children`）。
- 具体场景的真机验证 → S5 heavy_llm ST。
