# opencode 后端 POST→流式 — L1 问题/事实记录

> 层次：L1（客观事实 + 证据，不提方案/顺序/决策）。方案取舍见 `02-analysis.md`（L3），
> 改动配方见 `03-impl-*.md`（L4，拍板后产出）。
> 目标诉求：把 opencode 后端当前「阻塞 POST」改为流式，中间 turn 信息实时落日志，
> 效果对齐 claude SDK 后端。

## P-S1：opencode 后端运行期中间 turn 信息完全不可见（结构性缺失）

### 现象
经 DevKit spawn 的 opencode agent 一次 turn 执行期间（可达 3600s），**文本增量 /
thinking / tool_use / tool_result 等中间过程对运行日志完全不可见**；只有等整段 turn
跑完，才一次性把全量 history 拉回重建。对照 claude（SDK）后端每个 assistant 事件就
打一条 `agent_stream` 进度行 + per-event transcript flush，两者体感差异巨大。

### 根因（`src/ascendc_devkit/capabilities/agent/opencode_backend.py`）
`POST /session/:id/message` 是**阻塞整个 turn 的同步 HTTP 调用**（urllib，默认 timeout
3600s），返回即视为完成；之后再发 `GET /session/:id/message` 把整段 history 拉回重建
turn 信息。中间过程不解析、不落盘。
- 阻塞 POST：`opencode_backend.py` `spawn` 内 `POST /session/{id}/message`
  （`_message_timeout` 默认 3600s）。
- 事后重建：`_session_transcript_records` → `GET /session/{id}/message`，逐条写
  transcript。
- 模块 docstring 明确「this backend does NOT depend on parsing opencode's SSE event
  vocabulary」——这是**刻意**的隔离选择，代价就是本问题。

### 证据
- opencode server 提供 **`GET /event` 全局 SSE 事件总线**（`docs/opencode-sdk-ref/
  server.mdx`：`GET /event` "Server-sent events stream. First event is
  `server.connected`, then bus events"），且 **`POST /session/:id/prompt_async`**
  「Send a message asynchronously (no wait)」, returns `204 No Content`——即"发"与"收"
  本可解耦。
- 事件词汇表（`docs/opencode-sdk-ref/plugins.mdx` §Events）：
  - Message 增量：`message.part.updated` / `message.part.removed` / `message.updated`
    / `message.removed`
  - Session 生命周期：`session.idle`（turn 结束信号）/ `session.status` / `session.error`
    / `session.created` / `session.updated` / `session.compacted`
  - Tool：`tool.execute.before` / `tool.execute.after`
  - Server：`server.connected`（SSE 首事件）
- 对照 claude 后端（`sdk_backend.py`）：`async for event in query(...)` 纯流式，
  每事件 `_serialize_event`→IR→`IRConsumer.consume`，同时 `_write_transcript_record`
  （flush）+ assistant 事件触发 `Logger.action("agent_stream", ...)`（带 `text`/
  `thinking`/`tool:<name>` block 标签）；`Logger` 写 stderr，经 `infra/log_capture._Tee`
  同步 tee 到 `<run>/run.log`。

## P-S2：serve 中途被杀 → 中间 turn 全丢（不可诊断）

### 现象 / 证据
阻塞 POST 中途若 serve 子进程被 kill/OOM，crash-salvage 分支用 `consumer=None`，
transcript 只剩已 open 的空文件——**中间 turn 信息全部丢失**，事后无法定位"跑到哪崩了"。
对照 claude 后端 per-event flush，崩在哪都能看到已产出的 turn。

## P-S3：两后端共享 step-68 IR —— 流式复用成本极低（利好事实）

### 证据
- step-68 已统一两后端 IR：`IRConsumer`（`base_backend.py`）拥有所有信号提取
  （turn_count / full_response / session_id / truncated_turns / stall）；`AgentResult`
  由唯一 `_build_result` 工厂构造。
- opencode 侧已有 native→IR 映射 `_parts_to_records`（`opencode_backend.py`，处理
  `text/reasoning/tool/step-*` → `text/thinking/tool_use/<ptype>`）；claude 侧
  `_serialize_event`/`_serialize_block`（`_shared.py`）。
- 结论：opencode 流式只需新增「SSE event → IR record」映射，下游 IRConsumer / transcript /
  Logger / `_build_result` 管线**原样复用**——这正是 claude 流式走过的同一条路。

## P-S4：SSE 事件「载荷 schema」未在 SDK 文档给出（待实测风险）

### 现象 / 证据
`docs/opencode-sdk-ref/` 只在 `plugins.mdx` §Events **列了事件名**，未给每个事件的
`properties` 载荷 schema；`server.mdx` 的 OpenAPI 表也只到 endpoint 级，未含 SSE 帧
字段。要做「SSE event → IR record」正确映射，必须**实测**真实事件载荷（参照
`04-problems-global-config.md` 用 `opencode debug config` 实测的范式）。事件名/字段随
opencode 版本漂移的风险存在（当前实测基线 opencode 1.18.x）。

## P-S5：tokens 用量两后端都未收集（旁支，非本工作主线）

### 证据
`AgentResult.metrics` dataclass 注释（`backend.py`）期望 `{elapsed_ms, tokens_in,
tokens_out}`，但 `_build_result` 两后端都只填 `elapsed_ms / response_len`（opencode）
或 `elapsed_ms / response_len[/ failure_reason / resume_attempts]`（claude）。流式改造
可顺带从 `message.updated` 的 info 抽 tokens，但属增量收益，不构成本工作阻断项。
