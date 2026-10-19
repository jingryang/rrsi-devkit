# opencode 后端批跑并发 — L1 问题/事实记录

> 层次：L1（客观事实 + 证据，不提方案/顺序/决策）。方案取舍见 `02-analysis.md`（L3），
> 改动配方见 `03-impl-*.md`（L4，拍板后产出）。
> 触发场景：`scripts/batch_self_evolve.sh` 5 算子并发 `self_evolve_op`（ThreadPoolExecutor
> sibling thread 同进程，每算子 spawn 独立 `opencode serve` 子进程）。
> 诊断现场：v0.2.0 分支 `output/20260720-165327-df6f35/`（5 exec）+ 单算子对照
> `output/20260720-163934-5725c0/`。

## P-BC1：run.log 并发串流 / 丢失（framework Logger，进程内）

### 现象
5 并发批跑的 5 个 exec 各应有独立 `run.log`，实测：
- `48191a/run.log` 与 `c8aeff/run.log` **md5 完全相同**（`e2158efeb4c1d843d1398391a858b848`），都含全部 5 个算子内容（advance_step_v2 / scatter_pa_kv_cache / ai_infra_aggregate_hidden_grad / ai_infra_manifold_constrained_hyper_connection_post / multi_add_rms_norm_dynamic_quant）。
- `3c0daf/run.log` **0 字节**（整个 exec 日志丢失）。
- 另两个（140ffa / a479d5）各自不同 md5。

### 根因（`src/ascendc_devkit/infra/log_capture.py` + `infra/logger.py`）
- `Logger` 是无状态静态类，所有日志 `print(..., file=sys.stderr)`。
- `bind_run_log(path)` 把**进程级全局** `sys.stderr` 替换为 `_Tee(sys.stderr, file)`（`_BINDING` 全局单例，line 42/135-136）。
- 5 并发 exec 是 **ThreadPoolExecutor sibling thread（同进程）**（`graph_executor.py:662`、`batch_runner.py:30`），各自 `bind_run_log(自己的 run.log)` **互相覆盖** `sys.stderr`/`_BINDING`：后 bind 的覆盖先 bind 的 → 串流；抢不到的 → 空。
- **framework 自知**：`_Tee.write` 注释（line 64-66）明文 "under concurrent dispatch (batch) — the file closed mid-write by a SIBLING thread's rebind (sys.stderr and the _BINDING slot are process-global, so concurrent runs race on them)"；当前用 "swallow both sinks, never raise" + "events.jsonl 是权威记录" **容忍** run.log 串流/丢失。

### 证据
- md5：`md5sum 48191a/run.log c8aeff/run.log` 相同；`3c0daf/run.log` 0 字节。
- 代码：`log_capture.py:42`（`_BINDING` 全局）、`:64-66`（自标 sibling thread race）、`:135-136`（`sys.stderr = _BINDING`）。
- 并发模型：`graph_executor.py:662`（`ThreadPoolExecutor`）。

### 影响边界（澄清：不污染算子产物）
- run.log 串流**只影响诊断日志**；算子产物（`requirement.json`/`general_design.json` 等）由 agent 用 Bash/Edit **直接写 cwd**（per-exec 独立 `output/<exec>/artifacts/<stage>`），**不经过全局 `sys.stderr`**，实测 5 exec 的 `requirement.op_name` 全部对应自己算子（仅 snake_case↔PascalCase 格式差异）——产物层不串。

## P-BC2：opencode serve stderr 被吞（framework，进程间子进程）

### 现象
design 卡死时 opencode serve + engine MCP 子进程的 stdout/stderr **零信号**，无法定位卡在 opencode 内部哪一步。

### 根因（`src/ascendc_devkit/capabilities/agent/opencode_backend.py:857-865`）
`_start_serve` 用 `stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL` 启动 opencode serve；engine MCP 子进程（`engine_mcp_stdio`）的 stderr 同样不落盘。

### 证据
- 7fdd0cc9 design 卡死诊断时：opencode serve `epoll` 空转、CPU 零增长、`ss` 无网关连接，但**无任何 opencode/MCP 内部输出**可查（stderr→/dev/null）。
- 代码：`opencode_backend.py:863-864`（`stdout/stderr=DEVNULL`）。

## P-BC3：design 卡死空烧 1h（framework，超时/keepalive 缺失）

### 现象
design 卡死时 framework 的 blocking `POST /session/:id/message` **空等 message_timeout（3600s=1h）** 才报错，期间 5 算子全僵、资源空占。

### 根因（`opencode_backend.py:108` + `:255-257`）
- `message_timeout: float = 3600.0`（默认 1h）。
- blocking POST `timeout=self._message_timeout` 等整段 turn；**无 keepalive** 检测 agent 是否真在跑（v0.2.0 SSE 已订阅 `/event`，有事件流可判活，但未用于超时控制）。

### 证据
- 7fdd0cc9 卡死：27min 仍在等（未到 1h timeout）。
- 代码：`opencode_backend.py:108`（3600.0）、`:255-257`（blocking POST）。

## P-BC4：design 5 并发 primary 死锁（批跑核心阻塞，根因待 P-BC2 定位）

### 现象
- **5 并发**：5 个算子的 `ascendc-design-generator`（opencode **primary mode**）全部卡在 `action_start`（session 建后 turn1 不发起），opencode serve `epoll` 空转、CPU 零增长、无网关连接。v0.2.0（含 SSE 流式）**同样复现**——SSE 是观测层（POST 权威未改），不解决卡死。
- **单算子对照**：1 个 design-generator（primary + engine MCP）**正常跑通**（turn 1-9 推进，SSE `agent_stream` 显示 `tool:engine_resolve_ambiguity` **真实调用 9 次**，MCP 完整链路启动+握手+tools/call 全走通）。
- requirement 阶段（subagent）5 并发**不卡**。

### 根因（2026-07-21 复现定位，确认）
**opencode `external_directory` 权限默认 `ask` + 非交互批跑无 resolver → design-generator 无限阻塞。**
- framework `_assemble_config` 权限块（`opencode_backend.py:619-626`）设了 skill/question/edit/bash/webfetch/websearch，**唯独漏 `external_directory`** → 走 opencode 默认 `ask`。
- design-generator 探索 worktree（`find`/`ls` cwd 外的 proto.yaml/examples，opencode.log 实测 `permission=external_directory action.action=ask` @08:48:34）→ 非交互无 resolver → 阻塞 12+ min。
- requirement-analyst 读 cwd 内 `requirement_doc.md`（不探外部）→ 不触发 → 故正常完成。
- 已排除：① MCP 死锁（单算子 MCP 9 次正常）；② token/网关（8082 健康 200）；③ SQLite 争用（5 serves 共享 `~/.local/share/opencode/opencode.db` 实存，但非本次 stall 根因——卡点在权限决策，非 DB 写锁）。

### 证据
- 7fdd0cc9（output/20260720-104711-bf84a2）+ v0.2.0（output/20260720-165327-df6f35）：5 并发 design-generator 全卡 action_start。
- 单算子 v0.2.0（output/20260720-163934-5725c0/...c60034）：design-generator turn 1-9 正常，9 次 engine_resolve_ambiguity。
- events.jsonl：5 exec 卡点 `agent=ascendc-design-generator` / `type=action_start`。

## 相关既有工作（非本工作产权，仅引用）
- `opencode-streaming-transport/`：SSE 流式观测（design B，POST 权威未改）——已合入 v0.2.0，是 P-BC4 的观测手段，但不解决卡死；其 L3 §10 明确"纯 A（prompt_async 异步）留作 SSE 驱动重试经验证后的收敛"。
- `pipeline-observability/`：P8-P13 Logger 日志改进（单进程语境），未覆盖 sibling thread 并发（P-BC1）。
