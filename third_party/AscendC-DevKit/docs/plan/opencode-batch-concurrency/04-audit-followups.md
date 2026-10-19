# opencode 后端批跑并发 — L1 审计 follow-ups（post-implementation）

> 层次：L1（客观事实 + 证据 + 建议修法，不写决策/排期）。决策与排期见各自产权 track。
> 来源：2026-07-21 对已提交改动 `45483dda..HEAD`（S1/S2/S5 + P93 + S4）的独立对抗式 hack 审计。
> 状态：全部 **open**（待修），无阻塞项。

## 审计结论（recap）

独立 reviewer 总评：**三个 commit 干净可留在生产，无 hack / 无阻塞项**。已验证清的类别：
debug 残留 / FIXME-HACK-XXX-TODO / 硬编码 IP·端口·密钥·绝对路径 / 业务逻辑裸 `except: pass` /
注释掉的代码 / "只让测试过"的改动混进生产 / mock 后还标依赖标记 / 无意义断言——**均无**。
keepalive `idle=600/poll=10` 默认值有据（容忍长单 tool call）、`external_directory: allow` 为已知决策、
`_Tee` 退役干净无双通路残留（§2.5）。

以下 5 项是 reviewer 发现的**非阻塞收紧项**，记录待修。

---

## AU-1 — `Logger._emit` console print 未兜底（契约回归）★ 最该修

- **严重度**：LOW-MED
- **产权**：framework（S1 / P-BC1 fix 的 follow-up，本工作引入）
- **位置**：`src/ascendc_devkit/infra/logger.py:39`（`Logger._emit`）
- **事实**：
  - `_emit` docstring 承诺 "Either sink is best-effort: a closed run.log (thread teardown) or a hostile terminal never raises — logging must never break a run."
  - 实现：仅 run.log 侧（`f.write`）包了 `try/except (ValueError, OSError)`；**console 侧 `print(line, end=end, file=sys.stderr, flush=flush)` 未兜底**。
  - 退役的 `_Tee.write` 是**两个 sink 都兜**的（含对 "closed terminal fd in some test harnesses" 的处理）。
  - 可触发抛错：`BrokenPipeError`（`python … 2>&1 | head` 等 pipe 提前关闭）、`OSError`（fd 耗尽）、`ValueError`（对已关闭 stream 写）。
- **为何是问题**：docstring 与实现不一致（§1.2 可维护：契约-实现 divergence 是维护隐患）；logging 抛错会打断 run，违背"日志永不阻断"设计意图。
- **建议修法**：`print(...)` 包 `try/except (BrokenPipeError, OSError, ValueError): pass`（与 run.log 侧对称）；或若刻意让 console 抛错传播，则修正 docstring 为"run.log best-effort；console 抛错传播"。
- **UT**：现有 `test_log_capture.py` 不覆盖（capsys 不触发 BrokenPipe）；可补一个 monkeypatch `sys.stderr` 为会抛的 fake 验证不 raise。

## AU-2 — P93 `"timed out"` 标记过宽（子串误匹配）

- **严重度**：MED
- **产权**：**P93**（非本工作所写，本工作仅提交；改动前建议征询 P93 作者）
- **位置**：`src/ascendc_devkit/capabilities/agent/_shared.py:352`（`_INFRA_ERROR_MARKERS`）
- **事实**：
  - 标记 `"timed out"` 经 `any(m in text for m in _INFRA_ERROR_MARKERS)` 子串匹配任意 crash 文本。
  - 注释限定为 "backend HTTP spawn timeout (message_timeout wall)"，但实际命中**任何**含 "timed out" 的文本：
    - `socket.timeout: timed out`（瞬时网络抖动，原本走 transient 重试）
    - `URLError: <urlopen error The read operation timed out>`（urllib 瞬时）
    - bash 子进程 timeout 透传到 agent crash 文本
  - `_classify_error_type` 在 `base_backend.py:273`（任意 agent crash 的 `crash_reason`）+ `orchestration/graph_executor.py:127`（任意未捕获 stage 异常）被调用 → 命中即判 "infra"（halt 不重试）。
- **为何是问题**：把"特定观察到的 backend spawn-timeout 文本"与"通用英文短语"混同，可能把**瞬时网络抖动**误判 infra → halt 而非 transient 重试（§1.2 可诊断：未来瞬时 timeout 被静误标，无可观测信号）。
- **建议修法**：收紧到 spawn 路径独有的措辞（如 `"spawn failed: timed out"`）；或上游 `_classify_uncaught` 用 `isinstance(exc, TimeoutError)` 而非子串匹配 "timed out"。
- **UT**：`test_capabilities.py::test_spawn_timeout_is_infra` 现只断言规范串；补 transient `socket.timeout: timed out` **不应**判 infra 的回归。

## AU-3 — P93 `"Invalid token"` 标记偏宽

- **严重度**：LOW-MED
- **产权**：**P93**（同 AU-2）
- **位置**：`src/ascendc_devkit/capabilities/agent/_shared.py:355`
- **事实**：同 AU-2 子串匹配模式；"Invalid token" 是非 LLM auth 失败的常见措辞（任意外部 API 工具、agent transcript 里的自定义 HTTP code）。范围比 AU-2 小（auth 措辞较统一），仍偏宽。
- **建议修法**：用更具体标记（如 `"request failed: Invalid token"`）。

## AU-4 — `_start_serve` monkey-patch `serve_log_handle` 到 stdlib `Popen`

- **严重度**：LOW
- **产权**：framework（S2 follow-up）
- **位置**：`src/ascendc_devkit/capabilities/agent/opencode_backend.py:1072`（`proc.serve_log_handle = handle` / `proc.serve_log_path = ...`），`_stop_serve` 用 `getattr(proc, "serve_log_handle", None)` 读回。
- **事实**：给 stdlib `subprocess.Popen` 实例挂 ad-hoc 属性能跑（读侧 getattr 兜底），但是 code smell（无类型提示、易拼错、未来 slotted Popen 子类会断）。
- **建议修法**：`_start_serve` 返回一个小 wrapper（`types.SimpleNamespace(proc=…, serve_log_handle=…, serve_log_path=…)`）或 `@dataclass`，把句柄与 proc 一起携带。

## AU-5 — keepalive abort 后 POST worker 可能泄漏

- **严重度**：LOW
- **产权**：framework（S5 follow-up）
- **位置**：`src/ascendc_devkit/capabilities/agent/opencode_backend.py:1188`（watchdog trip 后 `self._stop_serve(proc)` → `thread.join(timeout=5.0)`）
- **事实**：
  - watchdog trip 后 `_stop_serve` 杀 serve 子进程；但 worker 的 `urllib.request.urlopen(..., timeout=self._message_timeout=3600.0)` **无短 socket timeout**，未必能立刻感知断连（kernel TIME_WAIT / half-close）。
  - `thread.join(timeout=5.0)` 返回后，daemon worker 可能继续阻塞在 socket 读最多 `message_timeout`（3600s）。
  - worker 是 `daemon=True`，进程退出时被回收——**单进程模型下无碍**；长生命周期 host（ThreadPoolExecutor worker 跨 exec 复用）下若干泄漏 worker 可能累积。
- **建议修法**：这个 POST 传更短的 urllib `timeout=`（如 `keepalive_idle_s + 2*keepalive_poll_s`），让 worker 在 watchdog 本就会触发的时间点附近自行 timeout，而非依赖 serve 断连传播。

---

## 相关（非本审计范围，pre-existing，仅记录）

- `_shared.py:512` `_ACLOSE_ERROR_MARKER` 单数别名是 §1.4 禁止的向后兼容 shim——但在 `4703b778` 引入（审计范围之前），非本工作。
- `_stop_serve` `proc.kill()` 后未 `proc.wait()` 回收（pre-existing）。
- `_cfg_scratch_dir` `decision_workspace=None` 时回退 `tempfile.mkdtemp(prefix="opencode_home_")` 且不清理（pre-existing）。

## 已记录的其它 follow-up（非本审计）

- **S5 gap**：keepalive 被 opencode 心跳帧绕过（permission-block 期间 `last_event_ts` 仍刷新 → 不触发），只抓 SSE 静默、抓不到 permission-block。见 `03-impl.md` 「S5 gap」段。

---

## 后续运行发现（2026-07-21 批跑看护 `output/20260721-010537-8b790c/`，非原 hack 审计）

> 来源：`scripts/batch_self_evolve.sh` 5 算子并发现有跑批（batch_id=`20260721-010537-8b790c`，worktree `cann-bench-batch/20260721_090523/`）的实跑观察，
> 非本文件顶部那轮 `45483dda..HEAD` 对抗式审计。二者同一 commit 集（P-BC1 thread-local + design B SSE 流式）的后果，故挂此处产权，但来源标注区分。
> 状态：AU-6/AU-7 **已解决（2026-07-22）**，详见各自条目末尾「已解决」小节。

## AU-6 — agent_stream 不落 per-op run.log（SSE daemon 线程无 thread-local run.log binding）

- **严重度**：MED（诊断体验退化，非正确性；与 design B「real-time turn 可见」初衷在 per-op 维度落空）
- **产权**：framework（P-BC1 thread-local run.log + design B SSE 流式 的组合 follow-up）
- **位置**：`src/ascendc_devkit/capabilities/agent/opencode_backend.py`（`_subscribe_sse` 起 daemon 线程 `threading.Thread(target=_run, daemon=True)` + `_emit_agent_stream` 调 `Logger.action`）+ `src/ascendc_devkit/infra/log_capture.py`（`_run_log_ctx = threading.local()`，仅在 exec worker 线程 `bind_run_log`）+ `infra/logger.py`（`_emit` 读 `current_run_log_file()`）
- **事实**：
  - design B 从**独立 daemon 线程**发 `agent_stream`：SSE 帧在该线程上经 `_handle → _handle_sse_event → _emit_agent_stream → Logger.action("agent_stream",…)`。
  - P-BC1 把 run.log 改为 **thread-local**（`_run_log_ctx = threading.local()`），仅 exec worker 线程调 `bind_run_log`。`threading.local()` **不向子线程继承** → SSE daemon 线程 `current_run_log_file()` 返回 `None`。
  - `Logger._emit` 见 `None` 跳过 run.log、只写 `sys.stderr`（console）；console 被 batch 脚本 `2>&1 | tee` 抓进**batch 级 log**。
  - 实测：5 并发批跑每 op 的 `run.log` 含 `agent_spawn`/`agent_session`/`stage_iteration`/`✓done`（均 worker 线程发）但 **`agent_stream` 行 = 0**；batch 级 log（`logs/batch_20260721_090523.log`）有 **9067** 行 `agent_stream`。同一 `Logger.action` 因发线程不同而两种命运。
- **为何是问题**：per-op `run.log` 是排查单算子的自然入口，缺 turn 日志则只能去 batch 级 log 忍受 5 op 交织（见 AU-7）；design B 注释自述 "surfacing each turn's parts as agent_stream Logger lines in real time (the user's core ask)"，该初衷只在 console 维度达成、per-op 维度落空。
- **建议修法**：
  - **Option 1（最小定向）**：`spawn()` 起 SSE 线程前捕获 worker 的 `current_run_log_file()` 句柄，透传给 `_subscribe_sse`/`_emit_agent_stream`，在 `Logger.action` 之后再 best-effort 写一行到该句柄（加 per-exec 锁防 worker+SSE 并发半行交错——同 op 无跨算子串流风险，P-BC1 兄弟线程隔离不变）。
  - **Option 2（架构更干净）**：`_run_log_ctx` 从 `threading.local` 换 `contextvars`，SSE 线程用 `copy_context().run(_run)` 起以继承 worker binding，`_emit` 零改动。动共享 infra，面稍大。
- **UT**：现有 `test_log_capture.py` 覆盖单线程；补「monkeypatch SSE 线程发 agent_stream 后该 exec 的 run.log 含该行」回归（需模拟 daemon 线程路径）。

**已解决（2026-07-22）**：采用 Option 2。`infra/log_capture.py` 的 `_run_log_ctx`/新增 `_op_name_ctx` 均从
`threading.local()` 换成 `contextvars.ContextVar`，并新增唯一入口 `spawn_context_thread(target)`
（内部 `copy_context().run(...)`）；`opencode_backend.py` 的 `_subscribe_sse` 改用该 helper 起 daemon
线程，daemon 线程运行时即继承 worker 线程 `bind_run_log` 时已生效的绑定，`Logger._emit` 零改动。对
plain `threading.Thread`（未走 `spawn_context_thread`）语义不变——新线程仍是空 Context，sibling exec
worker 线程互相隔离的 P-BC1 不变式不受影响（`test_concurrent_threads_runlog_isolated` 无需改动即通过）。
UT：`tests/ut/infra/test_log_capture.py`（`spawn_context_thread` 继承/隔离回归）+
`tests/ut/capabilities/test_opencode_backend.py::test_subscribe_sse_thread_writes_agent_stream_into_bound_run_log`
（真实 `_subscribe_sse` 起线程后 `agent_stream` 落进被绑定的 run.log 文件）+
`tests/st/test_run_log_turn_visibility_opencode.py`（`@pytest.mark.llm`，真实 opencode SSE 流实测，
不是 mock fixture——proves 真实帧格式下 daemon 线程确实继承了 run.log 绑定）。

## AU-7 — batch 级 agent_stream 无 op 归属（5 并发 turn 交织）

- **严重度**：LOW-MED
- **产权**：framework（batch 并发可观测性；`pipeline-observability` P10 的 batch 并发未覆盖面）
- **位置**：`src/ascendc_devkit/capabilities/agent/opencode_backend.py`（`_emit_agent_stream` 的 `attribution`，由 `spawn()` 的 `stage_name`/`branch_label` 拼成 `[stage/branch]`）
- **事实**：
  - `agent_stream` 行 attribution 是 `[stage_name/branch_label]`（如 `[precision-perf/T2]`），**不含 op_name / execution_id**。
  - `pipeline-observability` P10 已让 `agent_session` 行带 `session_id`（一次性首捕），但 **`agent_stream` 每行仍无 op 标识**。
  - 5 并发时同 stage（如多 op 都在 `precision-perf/T2`、都跑 `ascendc-design-generator`）的 turn 行在 batch log 交织、无法归属哪个算子——只能靠 cwd/时间戳猜。
- **为何是问题**：因 AU-6，batch 级 log 是 `agent_stream` 唯一落点，却又无 op 归属 → 单 op 排查仍不可直读。P10 解决的是 SDK 单进程语境，batch sibling 并发语境未覆盖（`pipeline-observability/01-problems.md` 自述「P8-P13 单进程语境，未覆盖 sibling thread 并发」）。
- **建议修法**：`agent_stream` attribution 增带 `op_name`（或 execution_id 短哈希），从 `spawn()` context 已有的算子标识取（`AgentResult`/spawn context 已持 op 信息）。
- **UT**：断言并发两 op 同 stage 的 `agent_stream` 行可按 op 区分。

**已解决（2026-07-22）**：`infra/log_capture.py` 新增 `bind_op_name`/`current_op_name`（与 run.log 同一
contextvars 机制），`dispatcher.py` 在两处 `bind_run_log` 调用点（resume 分支用 `state.op_name`、新建
run 分支用 `task_request.get("op_name", "")`，二者与 `State.op_name` 同源）后各绑定一次；单 stage/单
skill 的 CLI 入口不绑定，`current_op_name()` 保持默认空串，attribution 退化为原格式，行为不变。
attribution 拼接从 `opencode_backend.py`/`sdk_backend.py` 里各自手写的重复逻辑收敛成
`_shared.format_attribution(stage_name, branch_label)` 单一实现（内部读 `current_op_name()`），两个后端
一起受益、不留重复代码。格式：`[op_name/stage_name/branch_label]`（op_name 缺省时同原格式）。
UT：`tests/ut/infra/test_log_capture.py`（`bind_op_name`/`current_op_name` 读写）；受影响的
`test_opencode_backend.py`/`test_opencode_sse.py`/claude 后端相关 UT 全量回归通过（详见 dispatcher/
capabilities 全量 UT，482 passed，另全仓 UT 亦全绿）。另补：
`tests/ut/capabilities/test_shared.py`（`format_attribution` 全分支：无 stage/仅 stage/stage+branch/
stage+op/stage+branch+op）+
`tests/ut/application/test_state_machine_dispatcher.py::test_dispatch_binds_op_name_for_new_run` +
`tests/ut/application/test_application.py::TestDispatcherResume::test_resume_binds_op_name_from_state`
（两处 `bind_op_name` 调用点的接线断言，resume 分支专门验证读的是 `state.op_name` 而非
`task_request`）+
`tests/ut/capabilities/test_opencode_backend.py::test_concurrent_ops_same_stage_produce_distinguishable_attribution`
（AU-7 核心场景：两个并发 op 共享同一 `stage_name/branch_label`，`agent_stream` 行按 op_name 可区分、
无串扰）。全量 UT 2680 passed / 7 skipped（较修复前 2671 passed，新增 9 条全部通过）。

## AU-8 — ForkJoin 并发分支整段在 per-op run.log 不可见（ThreadPoolExecutor pool worker 不继承 contextvars run.log binding；AU-6 未覆盖此边界）★ 已实施

> 发现于 run `20260727-020230-bec0db`（gelu / 批 `run-npu-2ic-0228e0`，commit `0d5b508a`，**已含 AU-6
> 修复 `527f0f1`**；本仓 `output/` 下只读分析，不在本仓复现执行）。AU-6 解决了「SSE daemon 线程继承
> 调用线程的 run.log binding」，但 ForkJoin 分支跑在 `ThreadPoolExecutor` pool worker 里——pool worker
> 不继承提交线程的 contextvars context——AU-6 的 `spawn_context_thread` 只在「调用线程已 bind」时才有效，
> pool worker 本身就没 bind，于是整段分支执行都落不进 per-op run.log。

- **严重度**：MED-HIGH（observability；ForkJoin 是详设 tiling / anchor-forkjoin 的标准结构，并发分支
  在 per-op run.log 完全静默，叠加 join 屏障会把「单分支早崩」呈现为「长时间无输出后整段失败」——
  本次把一个 03:32 即崩的分支在 run.log 上呈现为 02:32→04:46 的 2h14m「无日志」）
- **产权**：framework（run.log 并发可观测性；AU-6 的未覆盖面）
- **位置**：`orchestration/graph_executor.py`（`_execute_forkjoin` 用 `ThreadPoolExecutor` +
  `pool.map(_run, pending)` 并发跑分支）+ `infra/log_capture.py`（`_run_log_ctx` 为 contextvars，
  `bind_run_log` 在 dispatch/应用层线程设置）+ `capabilities/agent/opencode_backend.py`
  （`_subscribe_sse` 经 `spawn_context_thread` 起 daemon，`copy_context()` 继承的是**调用线程** context）
- **事实**：
  - `bind_run_log` 把 run.log 句柄写入 contextvars `_run_log_ctx`（绑定在 dispatch/应用层线程）。
  - 顺序阶段在绑定线程内执行 → 所有 Logger 行（含经 `spawn_context_thread` 继承 binding 的 SSE
    `agent_stream`）落进 per-op run.log（实测 ForkJoin 前 328 条 `agent_stream` 正常）。
  - **ForkJoin 分支不同**：`graph_executor._execute_forkjoin` 用 `ThreadPoolExecutor.pool.map`
    并发跑分支；Python `concurrent.futures` 的 pool worker 是独立线程、**不复制提交线程的
    contextvars context** → 分支 `_run` 在无 binding 的 pool worker 里跑 → 该分支所有 Logger 输出
    （`agent_spawn`/`agent_session`/`stage_iteration`/`agent_stream`/`✓done`）都落不进 per-op run.log
    （`Logger._emit` 读 `current_run_log_file()` 得 `None` → 只写 console/batch log）。
  - 实测 run `20260727-020230-bec0db`（**含 AU-6 修复**）：`template-division done`（02:32:01）到
    ForkJoin join `WARN`（04:46:13）之间，per-op run.log **零** ForkJoin 分支行（无 spawn/session/
    iteration/stream）；同期 `events.jsonl` 完整记录 20 条 T1_none/T1_tanh 活动（`forkjoin_start` /
    `stage_enter` / `action_start` / `action_complete[partial]` / `forkjoin_complete`）。
  - AU-6 的真环境 ST `tests/st/test_run_log_turn_visibility_opencode.py` 仅 single-spawn 用例
    （`test_real_opencode_spawn_writes_agent_stream_turn_lines_into_run_log`，自述 "single-spawn"），
    **未覆盖 ForkJoin 并发分支** → 本缺口无真实测试守护（§3.9）。
- **为何是问题**：per-op run.log 是排查单算子的自然入口；ForkJoin 段整段静默时，排查者只能去 batch 级
  log（多算子交织）或 `events.jsonl`（非默认入口）。本次直接后果：据 run.log「2h 无输出」初判为
  「断链 / persist 崩溃」，实际是 **P115**（并发 DB lock→hang，已修）+ 本 observability 缺口叠加造成
  的误读——observability 缺口把诊断引向了错误根因。
- **取证边界**：本条只记「ForkJoin 分支整段在 per-op run.log 不可见」这一 observability 缺口（AU-6
  未覆盖 `ThreadPoolExecutor` pool worker 边界）。机制已在代码层确认（`pool.map` + contextvars 不跨
  pool 边界）；**L3 已出**：`07-forkjoin-runlog-binding-analysis.md`（推荐 **B：copy_context 流入
  `pool.map`**，待用户拍板转 L4）。本 run 里 T1_none「为何 hang（0-turn→3600s hard cap）」是
  **P115**（分析见 `05-engine-mcp-handshake-hang-analysis.md`，已在 `6f8c636` 修 per-spawn XDG 隔离 +
  engine 握手超时；本 run commit `0d5b508a` 早于该修复，属历史复发），不在本条产权内。

**已实施（2026-07-27，方案 B）**：见 `07-forkjoin-runlog-binding-analysis.md`（L3）/ `08-forkjoin-runlog-binding-impl.md`（L4）。
`infra/log_capture.py` 新增 `context_callable(fn)`（`spawn_context_thread` 的姊妹——后者给后台**线程**继承
context，前者给提交到 **pool** 的 callable 继承）；`graph_executor._execute_forkjoin` 改为 `[context_callable(_run) for _ in pending]`
（**每分支一份** context 拷贝）+ `pool.map(lambda r, ic: r(ic), wrapped, pending)`；`_launch_sidetask` 的单次 submit 同样包。
**实施期发现的关键约束**（L3 原判「shared ctx 只读并发安全」被证伪）：CPython 不允许两个线程同时 enter 同一个
`Context`（`RuntimeError: cannot enter context: ... is already entered`），故**必须每 task 一份拷贝**（在提交线程
即 dispatch 线程捕获），不能一份 shared ctx 给 `pool.map` 反复 enter。UT 守护：`test_context_callable_pool_worker_inherits_binding`
+ `test_context_callable_concurrent_tasks_each_inherit_binding`（锁死 per-task-copy 不变式）+ `test_plain_callable_in_pool_drops_binding`
（对照）+ `test_forkjoin_branch_logger_reaches_runlog`（ForkJoin 端到端）
+ `test_sidetask_branch_logger_reaches_runlog`（SideTask 端到端——**两调用点对称守护**：解包任一 submit/pool.map 即测试红，
原 SideTask 点无 binding 测试的静默复发缺口已堵）。全量 UT 3057 passed/7 skipped/0 failed（SideTask 守护为 review 后补，相关 UT 文件 26 passed）。

**§3.9 real-link 守护**：`tests/st/test_run_log_turn_visibility_opencode.py::test_real_opencode_forkjoin_branches_agent_stream_into_run_log`
（`@pytest.mark.llm`，**非** heavy_llm——两并发单 turn spawn、秒级）。它精确复刻 `_execute_forkjoin` 的 pool 调度模型（`ThreadPoolExecutor` +
每分支一份 `context_callable`），对**真实 opencode SSE 流**断言两分支的 `agent_stream` 都落进提交线程绑定的 run.log；不包 `context_callable` 则
pool worker contextvars 为空、agent_stream 落不进 run.log（即 AU-8 缺陷）。**注意**：仓内现有 heavy_llm 用例（design/docgen/vfdesign/testdesign
TUI self-closure 等）**全部绕过 `GraphExecutor`**（直接 `backend.spawn`，不经 `_execute_forkjoin`），故对 AU-8 **零覆盖**——
AU-8 的 real-link 守护只能靠这条聚焦 llm 用例，不能靠跑 heavy_llm 套件。

## 相关（非缺陷，诚实澄清）

- **`.batch_id` 捕获**：CLI 在 batch **正常结束时** `click.echo(f"batch_id: {result.batch_id}", err=True)`（`cli/commands/run.py:132`）→ 被脚本 `2>&1 | tee` 抓进 log → 末尾 `grep` 写 `.batch_id`。**正常跑无缺口**；唯一真缺口是 batch **被 kill** 时 `result.batch_id` 不 echo → `.batch_id` 不写 → 续跑断链（已记于 `self-evolution/batch-runlog-20260720-token401.md`）。本次看护对在跑 batch 预写 `.batch_id`（值取自 `output/<batch_id>/` 目录结构）是针对 kill 场景的无害兜底，非修缺陷。
