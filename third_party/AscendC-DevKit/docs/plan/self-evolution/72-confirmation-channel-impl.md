# L4 实施 — 用户确认公共模块（ConfirmationChannel）

> **性质**：self-evolution 线 step 72（L4）。承接 `70-training-loop-and-confirmation-analysis.md` D4（多通道确认模块）。
> **纪律**：语义锚点（类名/方法名/接口签名），不写 `file:line`（实施时现场读）；TDD 先红后绿（CLAUDE.md §3.1）；UT 用 stub/mock 不碰真实外部（§3.8）。
> **设计参照**：`EvaluationBackend` Protocol + `select_backend()` 选择器 + 默认注册表（`adapters/evaluation/__init__.py`）——本模块照此范式。

---

## 1. 目标与设计概览

引入 `ConfirmationChannel` 协议抽象，把当前**散落在 3 处**的决策逻辑（`AskUserQuestion` action / `resolve_ambiguity` MCP / loopback 路由）+ **重复 2 处**的 `decision_response.json` replay 收口为单一通路（§2.5），并在此协议上挂多通道 adapter（默认 FileChannel + MCPChannel + WelinkChannel）。异步暂停统一复用既有 `DecisionPendingError` + abort/resume 原语（§1.2 不造新暂停原语）。

**核心契约**（与既有 `decision_handler` callable 对齐，零摩擦接入）：
```python
class ConfirmationChannel(Protocol):
    name: str
    def request_decision(self, question: str, options: list[str],
                         default_index: int | None = None,
                         context: dict | None = None) -> str: ...
        # 返回所选 option 字面量；异步通道 raise DecisionPendingError 暂停。
    def available(self) -> bool: ...
```
- `select_channel(config) -> ConfirmationChannel`：按优先级探测 `available()`（仿 `select_backend`），缺省返回 `FileChannel`。
- `Decision` 不单独建模——返回值即 option 字面量，与既有 `decision_handler` 契约一致（最小改动）。

**异步模型**（统一）：通道负责「通知用户」+「本地解析」；需等待外部回复时一律 `raise DecisionPendingError`（写 `pending_decision.json`）→ 用户经 `respond` CLI 或通道回调写 `decision_response.json` → `--resume` 时 replay。不同通道只差「如何通知」（MCP 弹框 / Welink 消息 / 邮件）与可选「如何收回复」（respond CLI 通用；Welink 回调可直写 `decision_response.json`）。

---

## 2. 改动清单（按语义锚点）

### 改动 1 — `ConfirmationChannel` 协议 + `select_channel()` 选择器（新）
- **新增** `src/ascendc_devkit/capabilities/confirmation/`（或并入 `capabilities/`）：`ConfirmationChannel` Protocol、`select_channel(config)`、`ConfirmationConfig`（dataclass：`interactive`/`on_decision`/`channel`/`webhook_url`/`welink_*` 等，从 runtime config 读）。
- 范式照 `EvaluationBackend`：Protocol + `_default_registry()` 返回 `[FileChannel, MCPChannel, WelinkChannel]`，`select_channel` 探测 `available()`。

### 改动 2 — `FileChannel`（默认，包装既有 abort/resume）
- 把 `Runner._execute_ask_user_question` 的「resume replay + 非交互策略（abort/default）」两步 + `mcp_tools.resolve_ambiguity` 的 replay 块**抽成共享 helper** `_replay_decision_response(workspace_dir) -> str | None`（新，放 confirmation 模块），`FileChannel.request_decision` 调用它 + 必要时 `raise DecisionPendingError`。
- **收口重复**：`mcp_tools.py` replay 块 + `runner.py` replay 块改为调同一 helper（消除 2 处重复，§2.5 单一通路）。
- 默认行为与现状逐字节等价（既有 UT 守护，不回归）。

### 改动 3 — `MCPChannel`（包装 `resolve_ambiguity`）
- `MCPChannel.request_decision` 委托 `create_resolve_ambiguity_handler(interactive, on_decision, workspace_dir, webhook_url)`，把其 `on_decision` 三策略（default/abort/notify-webhook）映射为通道行为。
- `available()`：交互 TTY 或配置了 webhook 时 True。

### 改动 4 — `WelinkChannel`（外部版 REST adapter，薄客户端）
- 薄 REST 客户端（不内置 SDK，§2.6 / [[external-infra-not-framework-responsibility]]）：`request_decision` → POST 问题+选项到 Welink 开放 API（`open.welink.huaweicloud.com`，需 app 凭证）发消息卡片 → `raise DecisionPendingError`（异步等回复）。
- 回复收集：默认走通用 `respond` CLI 写 `decision_response.json`；可选 Welink 回调端点直写 `decision_response.json`（L4 后议）。
- `available()`：配置了 Welink 凭证时 True；否则 False（`select_channel` 自动降级到 FileChannel/MCPChannel）。

### 改动 5 — 接入点：`Runner.decision_handler` → `select_channel()`
- `Runner.__init__` 的 `decision_handler` 注入点：若调用方未显式注入，runner 内部默认 `decision_handler = lambda *a: select_channel(config).request_decision(*a)`。
- 如此 `_execute_ask_user_question` 的步骤 1（注入 handler）自动走通道；既有显式注入路径不变（向后无兼容包袱，但最小扰动）。

### 改动 6 — `HumanReviewStage`（可复用门 Stage）
- 新 Stage（`@register_stage`，注册进 `registry._ensure_stages_loaded`）：`actions()` 返回 `AskUserQuestion(question, options=[approve/revise/abort], default_index=...)`；`transition()` 按 choice 推进；`resolve_condition()` 返回 `approve`/`revise`/`abort` 供 TRANSITION_TABLE 路由。
- 复用 `_maybe_append_review` 的 approve/revise/abort 语义，但提升为**独立 Stage**（§2.5 P6b：训练时人工审核=独立 Stage），可挂在任意 stage 之后作 human-gate。
- 决策解析经改动 5 的通道（自动支持 MCP/Welink）。

### 改动 7 — 统一 `decision_pending` 事件可观测性
- 现状仅路径 A（`runner.py` AskUserQuestion）发 `decision_pending` 事件；路径 B（MCP）/C（loopback）不发。
- 在 `FileChannel`/`MCPChannel` 抛 `DecisionPendingError` 前统一 `event_log.append(evt.decision_pending(stage, iteration, question))`（或由 runner 捕获处统一发）——补齐 B/C 缺口，确保任何通道暂停都留可观测信号（§1.2 可诊断）。

---

## 3. 实施顺序（先红后绿）

1. **改动 1**（协议 + select_channel）+ UT：协议存在性、select_channel 降级到 FileChannel。
2. **改动 2**（FileChannel + 抽 replay helper）+ UT：replay 行为等价、abort 写 pending_decision.json、default 选首项；既有 decision 相关 UT 全绿（回归守护）。
3. **改动 5**（Runner 接入）+ UT：未注入 handler 时走 select_channel；显式注入不被破坏。
4. **改动 3**（MCPChannel）+ UT：三策略映射；包装 resolve_ambiguity 不改其原生行为。
5. **改动 6**（HumanReviewStage）+ UT：approve/revise/abort 三态 transition + resolve_condition；作为门 Stage 挂载。
6. **改动 7**（事件统一）+ UT：三路径暂停均发 decision_pending。
7. **改动 4**（WelinkChannel）+ UT：mock HTTP（`responses`/`httpx_mock` 或 stub）验证 POST 载荷 + raise DecisionPendingError；`available()` 凭证探测。**真实 Welink ST 留待凭证（见 §5）**。

---

## 4. 验证（TDD 用例清单）

UT（`tests/ut/capabilities/` 或 `tests/ut/orchestration/`，匹配既有 backend UT 约定，标记无 `llm`/`npu`——纯逻辑）：
- `test_select_channel_defaults_to_file`：无任何通道 available → 返回 FileChannel。
- `test_file_channel_replay_equivalence`：decision_response.json 存在 → replay 返回正确 option + unlink；不存在 → None。
- `test_file_channel_abort_raises`：abort 策略 + 无 response → raise DecisionPendingError + 写 pending_decision.json（字段 question/options/timestamp）。
- `test_file_channel_default_picks_first`：default 策略 → 返回 options[0]。
- `test_replay_helper_dedup`：mcp_tools 与 runner 共用同一 helper（单一通路）。
- `test_runner_routes_to_channel`：未注入 decision_handler → 调 select_channel。
- `test_mcp_channel_strategy_mapping`：default/abort/webhook 三分支行为。
- `test_human_review_stage_transitions`：approve→推进、revise→回上 stage、abort→__halt__。
- `test_decision_pending_emitted_all_paths`：B/C 路径暂停也发事件。
- `test_welink_channel_notify_then_pause`：mock Welink HTTP → POST 正确载荷 → raise DecisionPendingError；无凭证 → available()=False。

ST（`@pytest.mark.llm`，真实链路，§3.9）：
- `test_human_review_via_mcp_interactive`（heavy_llm 候选）：真实 MCP resolve_ambiguity 跑通一次 approve。
- `test_welink_channel_e2e`（heavy_llm，**需 Welink 凭证**）：真实 Welink 发卡片 + respond 回复 + resume。

---

## 5. 不在本轮 / 外部依赖

- **Welink 外部版凭证**（app key/secret + 测试群空间/robot + 收件人）：改动 4 的 UT 用 mock HTTP 不需要；**真实 ST 必须用户提供凭证**。无凭证时 WelinkChannel `available()=False`，自动降级，不阻塞 72 其余部分。
- **内部版 Welink / 钉钉 / 飞书 / 邮件 adapter**：协议已保证可扩展，留后续 step。
- **3 抛出路径的强制收口**：本 step 用「抽取共享 helper + 新代码走通道」做正确改动；既有 3 路径**包装复用**而非一刀切重写（保回归绿）。若包装后仍有冗余，留 follow-up 评估彻底收口。
- **GitAdapter / gitcode Issue 流**：属 step 74，不在 72。

---

## 6. 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-07-23 | v0.1 | 初版 L4：基于取证（`EvaluationBackend` Protocol 范式 + `Runner.decision_handler` 注入点 + abort/resume 成熟机制 + 3 抛出点/2 重复 replay）。7 改动 + 7 步顺序 + TDD 用例清单。核心=抽取收口既有散落决策逻辑 + 协议抽象 + 多通道 adapter，异步统一复用 DecisionPendingError。 |