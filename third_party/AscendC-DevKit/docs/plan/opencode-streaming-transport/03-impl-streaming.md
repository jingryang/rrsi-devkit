# opencode 后端流式 observability — L4 实施方案（方案 B：POST 权威 + SSE 观测）

> 配方层：**实际落地的是什么**。L3 §10 记录了 A→B 的实施修正（动手时发现纯 A 要重写已验证
> 重试逻辑、风险不匹配）。本文件描述**已实施**的 B；A 设计收在末尾附录作后续收敛参考。
> 遵 [[plan-doc-discipline]]：不写 file:line，只点模块/函数名与顺序。

## 0. 架构（B：增量叠加，零改动 correctness 路径）

```
OpenCodeBackend.spawn（既有流程，仅 +2 处接线）
 ├─ _start_serve / _wait_healthy / POST /session → session_id           （现有，不动）
 ├─ [新] sse = _subscribe_sse(base, "", agent, attr, start_ms)          ← POST 前订阅 GET /event
 │       daemon 线程：parse_sse_frames → _handle_sse_event →
 │         · message.part.delta  → 累积 chars（不 per-token 打日志，防刷屏）
 │         · message.part.updated → text/thinking/tool → Logger.action("agent_stream")
 │         · message.updated      → tokens 捕获；role=user 时 bump turn+reset
 ├─ [现有不动] while True: POST /session/:id/message（阻塞）+ 429 backoff + resume-degrade
 ├─ [现有不动] GET history → _parts_to_records → IRConsumer.consume（transcript/turn/截断）
 ├─ [现有不动] _build_result（artifacts/status/sidecar）
 └─ [新] finally: sse.stop_and_join()                                   ← 关响应解锁 readline
```

**关键不变量**：POST = result/retry 权威（429/degrade/gone 全不动）；SSE = pure observability
（`agent_stream` 实时日志 + tokens）。两者职责正交，各是各的唯一通路（§2.5 不违背）。专用
serve 单租户（每 spawn 一个新 serve），SSE 订阅传 `session_id=""` 不过滤（无串流可能，且对
rare resume-degrade 的新 session 鲁棒）。

## 1. 已实施组件

### 1.1 `opencode_sse.py`（新模块，纯函数 + I/O-free）
- `parse_sse_frames(lines)`：SSE `data:` 帧 → `{type, properties}`（无 `event:` 前缀，type 在
  JSON 内——spike 实测锚定）；多行 data 拼接、heartbeat 跳过、非 JSON→`{"_raw":...}` 不静默丢。
- `_part_to_block(part)`：opencode part → IR block（text/thinking/tool_use/step-*），**与
  `_parts_to_records` 共享**（slice 2 重构 `_parts_to_records` 改调它，消除重复）。
- `sse_event_to_ir_records` + 信号访问器 `event_session_id`/`event_tokens`/`is_idle_completion`/
  `event_error`（A 收敛时用；B 仅用前两个）。
  **【2026-09-14 删除】**：方案 A 未采用，该函数与 `is_idle_completion`/`event_error`
  从未接线（生产零调用），且其 delta 分型按 `field=="reasoning"` 与 opencode 实际发射
  不符（`field` 恒 `"text"`）。按 §2.5 唯一通路整删，协议守护见
  `docs/plan/opencode-cut-classification/`；保留 `event_session_id`/`event_tokens`/
  `is_session_compacted`（生产在用）。

### 1.2 `OpenCodeBackend` SSE 方法（新增）
- `_new_sse_log_state()`：per-spawn 状态（turn/chars/block_types/tokens/current_role）。
- `_handle_sse_event(event, state, ...)`：**核心逻辑**。按 block type 判（非 message role——
  opencode 的 role 标签滞后，见 L3 §10）；assistant text/tool part→`agent_stream`；step-marker
  跳过降噪；tokens 从 `message.updated` 捕获；turn 在 `message.updated(role=user)` bump。
- `_emit_agent_stream(...)`：`agent_stream [stage/branch] agent turn N (text,tool:Read), M chars, Xs`
  （对齐 claude 的 P13 格式）。
- `_subscribe_sse(...)`：**传输 seam**（与 `_http_json`/`_start_serve` 同级），起 daemon 线程读
  `GET /event`，逐行 `parse_sse_frames` → `_handle_sse_event`；返回 handle（`state` + `stop_and_join`，
  关响应解锁阻塞 readline）。**测试 override** 喂脚本化事件。

### 1.3 spawn 接线（+2 处，极小侵入）
- session 确定后、POST 前：`sse = self._subscribe_sse(...)`。
- `finally`：`sse.stop_and_join()`（在 transcript/serve 清理前）。

## 2. TDD 测试（遵 §三）

- **UT（纯逻辑）**：`test_opencode_sse.py` 22 例（解析器/part→block/event→record/信号访问器/
  spike 切片端到端）；`test_opencode_backend.py` +6 例（`_handle_sse_event`：text/tool 日志、
  step-marker 跳过、delta 累积 chars、tokens 捕获、session 过滤）。`_FakeServe` override
  `_subscribe_sse` 为 no-op 保护既有 POST-path UT。
- **全量 UT 回归**：2614 passed / 0 fail（`_parts_to_records` 重构 + import + SSE 接线无回归）。
- **真实 serve 验证（slice-4）**：`/tmp/verify_streaming.py` 起真 opencode serve → 真
  `_subscribe_sse`（非 override）+ `prompt_async` → **8 条 agent_stream 实时落日志**，含
  `tool:read` 可见、turn 1/2/3 递进、chars 0→6 累积、elapsed 实时。用户核心诉求**实地验证达成**。

## 3. 后续（未实施，合理性优先不本次做）

- **@llm ST 守护**：把 `/tmp/verify_streaming.py` 固化为 `tests/st/test_opencode_streaming.py`
  （`@pytest.mark.llm`，断言真 spawn 运行期 run.log 有 `agent_stream`）——回归守护真链路（§3.9）。
  本次 verify 已证可用，固化留 follow-up。
- **tokens 入 metrics**：`_handle_sse_event` 已捕获 tokens 到 `sse.state`，但 `_build_result` 未
  读它（维度 3 机会主义的"抽"已就位、"填 metrics"待接）。一行接线 + UT。
- **transcript 实时 flush（P-S2 崩溃可定位）**：当前 transcript 仍事后 GET；若要 per-event flush
  崩溃可定位，SSE handler 增 `_write_transcript_record`（transcript 打开点前移到 POST 前）。
- **纯 A 收敛**：SSE 驱动重试经验证后，搬 429/degrade 到事件、删阻塞 POST（L3 §10）。

## 4. 约束核对
- §1.2：B 由实施时四把尺子复核选定（保留已验证重试 > 重写）；SSE+POST 职责正交。
- §2.5：每职责单通路（POST=result/retry、SSE=observability、GET history=transcript/IRConsumer）。
- §3.4/§3.9：失败必修；真链路 verify 已跑（@llm ST 固化留 follow-up）。
- §1.8：本 L4 反映**已实施**的 B（L3 §10 记 A→B 修正）；A 设计附录于下。

---

## 附录：纯 A 设计（未实施，后续收敛参考）

> 落地前设想的 A：`prompt_async`(204) + SSE 权威驱动 IR/transcript/completion + 删阻塞 POST +
> final GET 取 finishReason + IRConsumer 增量累积。实施时发现重试逻辑事件驱动化风险高，
> 改 B。A 的 SSE 解析/事件映射基建（`opencode_sse.py`）已就位并为 B 复用；收敛回 A 时主要工作
> 是把 429/degrade 从 POST 异常搬到 `session.error` 事件 + `prompt_async` 续发。
