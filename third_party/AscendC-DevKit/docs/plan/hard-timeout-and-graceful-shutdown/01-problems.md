# 硬超时与优雅退出 — L1 问题记录（2026-07-25）

> 层级：**L1 / 问题记录**。只陈述「哪里坏、凭什么这么说」（证据/现象/根因/影响）。
> **不提方案、不排顺序、不写决策**。方案分析见 `02-analysis.md`（L3）；实施方案见 `03-impl-*.md`（L4）。
>
> 与现有工作的边界：
> - `stage-timeout-granularity/` 建的是**软超时检测层**（per-stage deadline + Option A 软放过）。本记录的 P1 描述该检测层的一个结构性盲区，不否定该工作。
> - `precision-debug-agent-abort/` 是 precision-debug 特定的中断善终场景；本记录的 P3/P4 是其泛化的通用缺口。

---

## P1（严重）：deadline 检测是轮询式，spawn 执行期间无中断点 → agent 卡死时 run 挂死

### 证据

- `runner._check_timeout()`（`orchestration/kernel/runner.py:484`）只在两处被调用：
  - iteration 循环顶部（`runner.py:274`）
  - `_execute_spawn_agent` 的 spawn **之前**（`runner.py:586`，注释「P5: check timeout before spawn, not just at iteration boundaries」）
- `self._agent_backend.spawn(...)` 是**同步阻塞**调用（`runner.py:587`），返回 `AgentResult`。
- 一旦进入 `spawn`，deadline 到点也无处检查 —— 必须等 `spawn` 返回后下一个检查点才能发现超时。

### 影响

当 agent spawn 卡死（opencode serve hang、claude CLI 子进程不响应、MCP stdio 死等），deadline 检查点永远到不了，整个 run 挂死。memory 记录的 `batch-design-primary-mcp-hang`（`message_timeout=1h` 致空等）、`npu-driver-hdcdrv-hang`（detect 卡住致 pytest 整体挂）即此类。

---

## P2（严重）：claude SDK backend 无硬终止能力，与 opencode backend 不对称

### 证据

- **opencode backend 已有 per-spawn 硬墙**：`_post_message_watched`（`capabilities/agent/opencode_backend.py:1137`）的 keepalive watchdog + `_stop_serve`（`:1213`，`proc.terminate()`→5s→`proc.kill()`），到点 kill `opencode serve` 子进程。
- **claude SDK backend 无对应机制**：`_spawn` 的核心是 `async for event in query(prompt, options)`（`capabilities/agent/sdk_backend.py:413`），`spawn` 经 `asyncio.run(self._spawn(...))`（`:188`）同步阻塞。
- `AgentBackend.spawn` 协议签名（`capabilities/agent/backend.py:43-59`）**无 timeout/deadline 参数**，调用方无法在阻塞期间注入中断。
- claude SDK 的底层是 `SubprocessCLITransport`（claude_agent_sdk/client.py:191），`anyio.open_process` 拉起 `claude` CLI 子进程，句柄在 `transport._process`（subprocess_cli.py:128）。**外部（sdk_backend）拿不到该句柄，无法直接 kill。**

### 影响

两个 backend 的硬终止能力不对称：opencode 卡死能被 kill 救活，claude 卡死只能等。`spawn` 协议无 deadline 入口，deadline 无法下沉到 spawn 内部。

---

## P3（中等）：无通用的「stage 中断善终」机制，只有手写的 _generate_report

### 证据

- 全仓 grep 无 `teardown` / `must_run` / `always_run` / `final_stage` 这类机制。
- 唯一的「无论如何都跑」是 `dispatcher._generate_report(workspace, ...)`（`application/dispatcher.py:1048`），在多个异常分支被硬编码调用（`:955`、`:997`，注释「covers all paths including aborted stages」）。它是 dispatcher 里的手写函数调用，**不是 stage 机制、不可复用、不能被 stage 自定义**。
- `FinalizeStage`（`orchestration/stages/finalize.py:53`）是普通 stage，`WorkflowTimeoutError` 在它之前 raise 时它**不会执行**。
- `Stage` 基类无 `teardown` 钩子；stage 被硬超时中断时无标准的「收尾」入口（回退到最后可用版本、清理临时资源、写「被中断」标记等只能散落在各处或缺失）。

### 影响

stage 被硬超时中断时无统一善终路径。precision-debug 的 `best_commit` 回退（`precision_debug_substages.py:672` `_snapshot_best_commit` + fix phase verify-才-commit `:1449`）是该 stage 自己的局部机制，未泛化。`_generate_report` 的手写调用违反「同一职责一条通路」（CLAUDE.md §2.5）。

---

## P4（中等）：无全局 signal handler / atexit，SIGTERM 不走优雅退出，子进程易孤儿

### 证据

- 全仓 grep `signal.signal(` / `atexit.register`（工程自身代码）= **零注册**。整个工程依赖 Python 默认 SIGINT→KeyboardInterrupt 行为。
- SIGTERM 默认直接终止进程，**不触发** KeyboardInterrupt → 不走 `dispatcher.py:987-994` 的 `runner.cancel()` + 保存状态路径 → 直接 EX 退出。
- `_start_serve`（`opencode_backend.py:1074`）`subprocess.Popen` 未设 `start_new_session=True`，主进程异常退出时 `opencode serve` 子进程、engine MCP stdio 子进程可能变孤儿。
- claude SDK **自带** `_ACTIVE_CHILDREN` 全局集 + `atexit.register(_kill_active_children)`（claude_agent_sdk subprocess_cli.py:33-47），但这只在 Python 正常退出时生效；SIGKILL/OOM 时 atexit 不跑。

### 影响

运维 `kill <pid>`（SIGTERM）直接杀进程，丢失运行状态、不落 events、子进程孤儿。Ctrl+C 的 `runner.cancel()` 也是软的（设 flag，等 spawn 返回才生效，受 P1 同样的卡死盲区制约）。

---

## P5（中等）：cann-bench 等重型 stage 在硬超时时丢失评测结果

### 证据

- `CannbenchEvalStage`（`orchestration/stages/cannbench_eval.py:32`）是确定性 subprocess stage（`actions() return []`，`:72`；注释 `:2`「deterministic shell-command stage (no agent)」），跑 `cann-bench kernel_eval` CLI，**自身已有 30min subprocess timeout**（`_run_eval` `:259` `timeout=1800`）。
- workflow 硬超时（`WorkflowTimeoutError`）在 cann-bench 之前 raise 时，cann-bench 不执行 → 无评测结果（`overall_score` 缺失）。
- workflow 硬超时在 cann-bench 执行中触发时，cann-bench 被 `_check_timeout` 在 iteration 边界中断（若它回到边界）→ 评测半途而废。
- cann-bench 的输入契约 `requires=["deploy_result", ...]`（`:54-58`），其 `transition` 已处理上游未完成（`:77` `deploy_result missing or smoke not passed → skip eval → score=0`）。

### 影响

self-evolution / cann-bench 评测场景下，硬超时导致 `overall_score` 缺失或半途而废，进化无 loss 信号。用户诉求：「即使是硬超时也应该走完评测，否则没有结果」；约束：「不在主流程为 cann-bench 写特殊逻辑，要通用方案」。

---

## 证据汇总（关键代码定位）

| 关注点 | 位置 |
|---|---|
| deadline 检测点 | `runner.py:274`（iteration 顶）、`runner.py:586`（spawn 前） |
| deadline 检测实现 | `runner.py:484` `_check_timeout` |
| Option A 软放过 | `runner.py:497-510`（`_last_iter_ok=True` 时 warn 不 raise） |
| deadline 配置 | `orchestration/runtime_config.py` `resolve_stage_timeout` / `timeouts.*` |
| spawn 协议（无 deadline 入口） | `capabilities/agent/backend.py:43-59` |
| claude spawn 阻塞点 | `sdk_backend.py:413` `async for event in query(...)` |
| opencode 已有硬墙 | `opencode_backend.py:1137` `_post_message_watched` + `:1213` `_stop_serve` |
| 控制流异常清单 | `graph_executor.py:311` `_control_exceptions`（含 WorkflowTimeoutError/StageTimeoutError/RunnerCancelledError/KeyboardInterrupt） |
| 退出码 | `domain/exit_codes.py`（EX_TIMEOUT=124 / EX_SIGINT=130 / EX_SIGKILL=137 已预留） |
| 手写 report finally | `dispatcher.py:1048` `_generate_report`（`:955`/`:997` 调用） |
| cann-bench 30min timeout | `cannbench_eval.py:259` |
| precision-debug best_commit | `precision_debug_substages.py:672` / `:1449` |
