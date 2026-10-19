# opencode 后端批跑并发 — L4 实施方案

> 层次：L4（改哪个函数 / 什么顺序 / 怎么验证）。事实见 `01-problems.md`（L1），
> 选项+取舍见 `02-analysis.md`（L3）。本文记录 S1/S2/S5 的已实施改动（拍板后冻结）。
> S3/S4（P-BC4 运行时复现+修）见「S3 / S4 ✅ 已定位 + 已修复 + 已运行时验证」段（已解决）。
> 审计 follow-ups（AU-1~AU-7，待修、非阻塞）见 `04-audit-followups.md`。

## S3 / S4（P-BC4 design 5 并发死锁）—— ✅ 已定位 + 已修复 + 已运行时验证

### S3 定位结果（2026-07-21 复现，网关 8082 恢复后）

**根因 = opencode `external_directory` 权限默认 `ask` + 非交互批跑无 resolver → 无限阻塞。**

5 并发 batch（run 20260721-004437）复现 + S2 serve log + events.jsonl 定位：
- requirement-analyst **正常完成**（读 cwd 内 `requirement_doc.md`，不探外部 → 无 external_directory ask）。
- design-generator 探索 worktree（`find`/`ls` cwd 外的 proto.yaml/examples）→ 触发
  `permission=external_directory action.action=ask`（opencode.log 08:48:34）→ 非交互无 resolver →
  **阻塞 12+ min**（08:48:34 → 09:01:21，靠手动 kill serve 才断连 crash-salvage）。
- 5 个 primary design-generator 全命中 → 全 stall。网关健康(200)、无 bash 子进程、
  `ss` 无网关连接 = 卡在权限决策，非 LLM/工具/SQLite 争用（5 serves 虽共享 `~/.local/share/opencode/opencode.db`，但非本次根因）。
- **完美解释 requirement ✓ / design ✗**：差异在 design-generator 探索 worktree（外部路径）。

framework `_assemble_config` 权限块设了 skill/question/edit/bash/webfetch/websearch，**唯独漏 `external_directory`** → 走 opencode 默认 `ask`。属 **path 甲（framework config 缺口）**，非 opencode 多实例限制（external-infra）。

### S4 修复（path 甲：config 补 `external_directory: allow`）

`opencode_backend.py` `_assemble_config` 的 permission 块加：
```python
"external_directory": "allow",  # agents 操作 worktree（cwd 外），默认 ask 在 headless 无 resolver→阻塞
```
UT `test_assemble_config_projects_all_four_decisions` 加断言 `external_directory == "allow"`。

### 运行时验证（2026-07-21 09:05 batch 20260721-010537）

修复后 5 并发 design-generator：
- **越过 turn 7（原 stall 点）→ 推进到 turn 20+** 持续流动（agent_stream 6s gap）。
- **写出 `general_design.json`**（此前 stall 从未产出的契约产物）+ 跑 python3 自检脚本验证 +
  写 `decision_log.json`，loop step 5→6→7→8 正常推进。
- 对比修复前（turn 7 stall 12+ min，零产物）：**P-BC4 解决**。

### S5 gap（本次复现发现，独立 follow-up，不阻塞 P-BC4）

S5 keepalive **未触发**（design stall 12+ min 期间无 `_KeepaliveAbort`）。根因：opencode 在
permission-block 期间仍发 SSE 心跳帧 → `_handle` wrapper 每帧刷新 `last_event_ts` → keepalive
误判"活跃"。即 S5 只抓"SSE 静默"（agent 死/SSE 断），抓不到"permission-block 但有心跳"。
修法方向：`last_event_ts` 只在**内容事件**（delta/part.updated/message.updated）刷新，心跳/step
事件不刷新。属 S5 自身完善，与 P-BC4（已由 S4 解决）独立，另立工作。

## 已实施：S1 / S2 / S5（framework 自身三 bug，全部 UT 验证）

### S1 — P-BC1 Logger 并发串流（决策 A：thread-local）

**根因**：`_Tee` 绑进程全局 `sys.stderr` + `_BINDING` 全局单例，5 并发 sibling thread
各自 `bind_run_log` 互相覆盖 → run.log 串流/丢失（`_Tee.write` 自标 sibling race）。

**改动**（`src/ascendc_devkit/infra/log_capture.py` 重写）：
- 退役 `_Tee` / `_BINDING` / `_REGISTERED` / `atexit`（§2.5 单一通路：run.log 唯一写入点收敛到 Logger）。
- `_run_log_ctx = threading.local()`：每线程独立 run.log 句柄。
- `bind_run_log(path)`：set 当前线程句柄（line-buffered append）；同线程重复 bind 先关旧句柄（无泄漏）；open 失败 warn + 不绑（日志永不阻断 run）。
- `unbind_run_log()`：关当前线程句柄，幂等。
- 新增 `current_run_log_file()`：Logger._emit 读它镜像到 per-exec run.log。

**改动**（`src/ascendc_devkit/infra/logger.py`）：
- 新增 `_emit(line, *, end, flush)`：`print(..., file=sys.stderr)`（共享 console，并发 interleave 可接受——console 本就是共享终端）+ 写 `current_run_log_file()`（per-thread 隔离，best-effort 吞 `ValueError`/`OSError`）。
- 9 个静态方法（`stage_header`/`stage_done`/`stage_skipped`/`action`/`heartbeat`/`info`/`warn`/`error` + `_ts`）的 `print` 全改为 `Logger._emit`。

**改动**（注释同步，无功能影响）：
- `capabilities/agent/sdk_backend.py:542` retry-trail 注释 `_Tee` → `Logger._emit + thread-local bind_run_log`（flush-per-write 不变，SIGKILL 不丢）。
- `tests/conftest.py` autouse fixture 注释（机制改 thread-local，per-test teardown 需求不变——pytest 顺序跑同主线程）。
- `tests/ut/application/test_state_machine_dispatcher.py` 集成测试注释。

**验证**：`tests/ut/infra/test_log_capture.py` 重写——7 UT 全过，含
`test_concurrent_threads_runlog_isolated`（P-BC1 回归：4 sibling thread 各 50 行，
每 run.log 只含自己线程内容，无串流）。

### S2 — P-BC2 stderr 被吞（决策 A：落 scratch_dir）

**根因**：`_start_serve` 用 `stdout=DEVNULL, stderr=DEVNULL` → design 卡死时
opencode serve + engine MCP 零信号可查。

**改动**（`src/ascendc_devkit/capabilities/agent/opencode_backend.py`）：
- `_start_serve`：`stdout=<file handle>, stderr=subprocess.STDOUT`（合并同流），
  落 `scratch_dir/.opencode-serve-<port>.log`。`scratch_dir` = `env["OPENCODE_CONFIG"]`
  父目录（`<workspace.dir>/.opencode_home`，与 run.log 同父目录、非 agent artifacts 目录 → 不污染产物）。
- 新增 `_serve_log_path(env, port)`：派生路径（从 env，不改 `_start_serve` 签名 → 不破 UT override）。
- 句柄存 `proc.serve_log_handle` / `proc.serve_log_path`；`_stop_serve` 用 `getattr(..., None)` 关闭（防御 UT opaque proc，无 fd 泄漏）。
- serve 启动时 `Logger.info` 记录路径（→ run.log 可发现）。

**验证**：`tests/ut/capabilities/test_opencode_backend.py` 加 2 UT：
`test_start_serve_writes_log_not_devnull_and_closes_on_stop`（非 DEVNULL + stderr=STDOUT + 路径在 scratch + stop 关 handle）、
`test_serve_log_path_falls_back_to_tmpdir_without_config`（防御）。

### S5 — P-BC3 空烧 1h（决策 C：keepalive 判活 + timeout 硬兜底）

**根因**：blocking `POST /session/:id/message` `timeout=message_timeout(3600s)` 空等整 turn，
无 keepalive（v0.2.0 SSE 已订阅 `/event` 有事件流但未用于判活）。

**改动**（`src/ascendc_devkit/capabilities/agent/opencode_backend.py`）：
- 新增 `_KeepaliveAbort(RuntimeError)` 异常（模块级）。
- `__init__` 加 `keepalive_idle_s=600.0` / `keepalive_poll_s=10.0`（`message_timeout` 保留为硬墙钟兜底）。
- `_new_sse_log_state` 加 `"last_event_ts": time.time()`（keepalive 基线）。
- `_subscribe_sse` 的 `_handle` wrapper：每帧先 `state["last_event_ts"] = time.time()`（任何帧=活跃，含被过滤的 noise/delta）。
- 新增 `_post_message_watched(base_url, session_id, body, sse, proc, agent_name, attribution)`：
  POST 跑 worker 线程，主线程轮询 `sse.state["last_event_ts"]`——
  ① `keepalive_idle_s` 无帧 → keepalive trip；② `message_timeout` 硬墙钟到 → hard_timeout trip。
  触发即 `_stop_serve(proc)` 断连让 POST 抛错 + `raise _KeepaliveAbort(<可诊断 reason>)` →
  spawn 的 `except Exception` → crash-salvage（不再空烧 1h）。race-safe：worker 已出结果则结果胜。
- spawn 的 POST 调用点（`while True` 429 循环内）`self._http_json("POST",...)` →
  `self._post_message_watched(...)`。429 退避 sleep 在 watchdog 外（不被误判）；
  worker 的 HTTP 错（如 404 session-gone）原样抛出走既有 degrade 逻辑。

**验证**：`tests/ut/capabilities/test_opencode_backend.py` 加 3 UT：
`test_post_message_watched_returns_message_on_normal_completion`（正常完成返回结果）、
`test_post_message_watched_aborts_on_sse_idle`（SSE idle → _KeepaliveAbort + serve killed）、
`test_post_message_watched_aborts_on_hard_timeout`（硬墙钟 → _KeepaliveAbort）。

### 整体回归

- `tests/ut/capabilities/ + tests/ut/infra/`：**361/361 全过**（S1/S2/S5 无连带破坏）。
- `tests/ut/capabilities/test_opencode_backend.py`：42/42（含新增 5 UT）。
- `tests/ut/infra/test_log_capture.py + test_logger_artifacts.py`：14/14。

### 已知阻塞（非本次改动引入，记录诚实）

- `tests/ut/application/test_state_machine_dispatcher.py` 中 3 个 `dispatch()`-based UT
  （`test_pipeline_completes_with_new_fields` / `test_dispatch_with_custom_quotas` /
  `test_dispatch_binds_run_log_into_run_dir`）遇 **torch_npu 原生 segfault**（`torch._C`/`torch_npu._C`）。
  经 `git stash` 对照确认：**pre-change 代码同样 segfault**——既有环境问题（NPU 设备交互期原生崩溃，
  非项目 bug、非 S1 引入），符合记忆 `st-suite-sporadic-native-crash` / `npu-driver-hdcdrv-hang` 模式。
  autoload=0 无效（排除 `torch-npu-autoload-conflict`）。本次不修（§3.7：环境问题报清不强行变绿）。
  S1 的 dispatcher 集成接线由代码审查 + 隔离 UT 共同保证成立。

## S3 / S4 历史阻塞（已解除）

本工作初次收尾时（2026-07-21 早），S3 复现被 LLM 网关 `/v1/messages` 持续 503 阻塞
（探针误测 `ANTHROPIC_BASE_URL=192.168.0.212:3000`；batch 实际走 opencode provider
`192.168.0.212:8082`，后者恢复后即跑通）。网关恢复后 S3/S4 已完成，结果见**上文
「S3 / S4 ✅ 已定位 + 已修复 + 已运行时验证」段**（根因 = `external_directory` 权限默认 `ask`）。
