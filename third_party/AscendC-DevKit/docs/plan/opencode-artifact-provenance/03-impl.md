# opencode 后端产物落点取证失效 — 实施（L4）：schema 归一 + 会话历史采集

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`（P1→(b)、P2→GET 会话历史），事实见 `01-problems.md`。
> 触点集中在 `capabilities/agent/opencode_backend.py`；harvest（`design_substages.py`）零改动、只加 UT。

## 改动 1（P1/b）— `_parts_to_records` block 字段对齐 SDK schema

`opencode_backend.py:_parts_to_records`（621-648），把 block 产出从 `type`/`name`/`input` 改为
SDK schema（`_shared.py:_serialize_block` 为权威样式）：
- `type=="text"` → `{"kind": "text", "text": ...}`（`type`→`kind`）
- `type=="reasoning"` → `{"kind": "thinking", "text": ...}`
- `type=="tool"` → `{"kind": "tool_use", "tool_name": p.get("tool") or p.get("name"),
  "tool_input": p.get("state") or p.get("input") or {}}`（`name`→`tool_name`、`input`→`tool_input`）
- 其余（step-start/step-finish/未知）→ `{"kind": str(ptype), "text": ...}`（`type`→`kind`，保留可回放）

record 外层维持 `{ts, type:"opencode_message", turn, blocks}`；`turn` 由改动 2 传入真实序号
（无历史时回退 1）。**删除**旧 `type`/`name`/`input` 产出（§1.4/§2.5，不留旧格式分支）。

## 改动 2（P2）— 完成后 GET 会话历史，逐消息落 transcript（真实 turn）

在 `spawn` 的 transcript 持久化处（`opencode_backend.py:261-264`，现为「只对 POST 返回的单条 `message`
调 `_parts_to_records`」），改为：
1. 阻塞 POST 正常返回后，`GET {base_url}/session/{session_id}/message`（复用 `_http_json`）取整段会话
   消息列表。
2. 遍历消息列表，第 i 条（从 1 起）调 `_parts_to_records(msg, turn=i)`，逐条 `_write_transcript_record`。
3. `_parts_to_records` 增形参 `turn: int = 1`，record 用它替代硬编码 1。
4. **best-effort 回退**（决策 2 边界）：GET 抛异常/超时/返回非列表 → `Logger.warn` 后回退旧路径
   （对 POST 返回的单条 `message` 调 `_parts_to_records(message, turn=1)`），不阻断 spawn。

`_build_result` 不变（仍用 POST 返回的 `message` 判 `err`/`text`/`artifacts`）——GET 只服务 transcript
持久化，不参与结果判定（隔离：采集增强不改 spawn 语义）。

## 改动 3（验证 harvest 在 opencode 生效）— 不改 harvest，仅加 UT

`_harvest_relocation_evidence` 零改动。加 UT 证明 (b) 后它对 opencode transcript 生效。

## 顺序

改动 1 → 改动 2（改动 2 依赖 1 的 `turn` 形参 + 归一 block）。改动 3 是 1+2 落地后的守卫。

## 验证（TDD，先红后绿）

**UT — `tests/ut/capabilities/agent/`（opencode backend）**：
- `_parts_to_records` 新 schema：喂含 text/reasoning/tool 三类 part 的 message，断言产出 block 为
  `kind`/`tool_name`/`tool_input`（不再有 `type`/`name`/`input`），tool block 的 `tool_input` 含
  `file_path`。
- `turn` 传递：`_parts_to_records(msg, turn=3)` 的 record `turn==3`。
- GET 会话历史遍历：mock `_http_json` 的 GET 返回多条消息（含中间 tool 调用），断言 transcript 落多行、
  turn 递增、tool_use block 出现；mock GET 抛错 → 断言回退到单条 message + turn 1 + 记 WARN、不抛。

**UT — `tests/ut/orchestration/`（harvest 跨后端）**：
- `_harvest_relocation_evidence` 喂一份 opencode 归一格式 transcript（`kind:tool_use` + Write 的
  `file_path` 落在 wd 外），断言返回该 Path——证明 (b) 后取证对 opencode 生效（§3.9 意义的真实链路守护，
  但此处是确定性 UT）。

**回归**：现有 opencode backend UT（transcript/parts 相关）断言随新 schema 更新；SDK 侧 `_serialize_block`
与 harvest 既有 UT 不变（本轮不动 SDK 产出与 harvest 逻辑）。

**全量**：CLAUDE.md §3.6 全量 UT + 非 heavy ST 绿。**heavy_llm（§3.11）**：本改动是确定性
transcript 采集/字段映射，非 §3.9 真实 LLM 行为对象，UT 以 mock HTTP 确定性覆盖 GET 遍历与回退；
真实 opencode 全流程（跑一次看 transcript 是否含真实 turn + tool_use `file_path`）留 PR 前节点由用户决策。

## 后续（不在本轮）
- Bash `cp`/`mv` 落盘路径不覆盖（决策 3，沿用 step 51 决策 4）。
- 真实误落点确认后的用户决策门已由 step 51 建成（`pending_relocation` + `on_decision`），本轮不动。

## 实施结果（2026-07-18，✅ 已完成）

**改动落点**（`capabilities/agent/opencode_backend.py`）：
- 改动 1（P1/b）：`_parts_to_records` 增 `turn: int = 1` 形参；block 产出改 SDK schema
  `kind`/`tool_name`/`tool_input`（删旧 `type`/`name`/`input`，§1.4/§2.5）。
- 改动 2（P2）：新增 `_session_transcript_records`（完成后 `GET /session/{id}/message`、遍历所有消息、
  真实 1-based turn；GET 失败/异常回退单条 message + turn 1 + WARN，best-effort）+ `_extract_history_messages`
  （容忍 list / `{messages:[...]}` / 其他→空）；`spawn` 持久化处改调 `_session_transcript_records`。
  `_build_result` 不变（GET 只服务 transcript，不参与结果判定）。
- 改动 3：`_harvest_relocation_evidence` 零改动。

**测试**（TDD 红→绿 + 覆盖自审补充 §3.2）：
- opencode backend（`test_opencode_backend.py`）：`_parts_to_records` 新 schema + file_path 透传 + turn
  透传；`_extract_history_messages` 形状容忍；`_session_transcript_records` 遍历历史（真实 turn + tool_use）
  + GET 失败回退 + **空 history 回退**（GET 成功但返空/非识别形状 → 回退单条 message，补全 best-effort
  另一支）；**spawn 级端到端接线**（spawn 实际发 GET 历史、transcript 落 tool_use + Write 的 file_path
  ——闭环 P2「补不到中间 tool 调用」的根因）。`_FakeServe` 加 `message_history` 脚本 + GET/POST 分流；
  `_Rate429Serve` 计数只算 POST（GET 历史不再误计）。
- harvest 跨后端（`test_design_substages.py::test_harvest_works_on_opencode_produced_transcript`）：用真实
  `OpenCodeBackend._parts_to_records` 产出的 transcript 喂 harvest，断言定位到落在 wd 外的 Write——证明
  (b) 端到端闭合 opencode 取证空转。

**验收**：opencode backend + design_substages 定向 174 passed；**全量 UT 2328 passed / 7 skipped**
（新增 8 UT，既有 cann-bench 外部依赖 skip），零回归；stub-based ST（`design_pipeline_e2e` 6 +
`integration` 28）34 passed。**未跑**（§3.7 诚实记录）：`test_skill_invocation_dual_backend[opencode]` /
`test_tool_permission_dual_backend[opencode]` 需真实 opencode serve + 在线 LLM（§3.9 真实链路守护），
本轮未跑，留 PR 前节点由用户决策——届时同时验真实 transcript 是否含真实 turn + tool_use `file_path`。
