# opencode 后端 POST→流式 — L3 方案分析

> 层次：L3（选项 + 取舍 + 理由）。事实见 `01-problems.md`（L1），改动配方见
> `03-impl-*.md`（L4，拍板后产出）。调研中演进、拍板后冻结。
> 目标：opencode 后端中间 turn 实时落日志，效果对齐 claude SDK 后端（P-S1）。

## 0. 名词约定（澄清"POST vs GET"）

用户原话「POST vs GET」在 opencode 语境对应：
- **POST（现状）**：`POST /session/:id/message` —— 阻塞"发+等"，单次同步请求返回最终
  assembled message。当前 opencode 后端唯一传输路径。
- **GET（流式）**：`GET /event` SSE 总线 —— 长连接增量推事件；配合
  `POST /session/:id/prompt_async`（204 非阻塞触发）解耦"发"与"收"。

即"流式"≠ 单纯 GET，而是「订阅 SSE 总线 + 非阻塞触发 + 按 session 过滤事件」的组合。
下文称**方案 A/B/C**。

## 1. POST（现状） vs 流式（SSE）利弊

### POST 阻塞（现状）

| 维度 | 评价 |
|---|---|
| 实时性 | ❌ turn 级黑盒，可达 3600s 无任何中间信号（P-S1） |
| 可诊断 | ❌ 中途 kill/OOM 中间 turn 全丢（P-S2）；claude 对照组 per-event flush 可定位崩点 |
| 实现复杂 | ✅ 单次 urllib + 单 JSON 响应，无流解析、无事件词表依赖、无线程/异步 |
| 完成判定 | ✅ 响应即最终态，确定性 |
| 与 claude 对齐 | ❌ 结构性背离（claude 纯流式 per-event 可见） |
| tokens | ❌ 未收集（P-S5） |
| 连接稳健 | ⚠️ 长持连接（3600s），relay/代理 idle timeout 可能静默断 |
| 隔离性 | ✅ docstring 明确"不依赖 SSE 词表"——刻意隔离，版本漂移免疫 |

### 流式 SSE + prompt_async

| 维度 | 评价 |
|---|---|
| 实时性 | ✅ `message.part.updated` 随产随推，`agent_stream` 行 per-event 落日志，对齐 claude |
| 可诊断 | ✅ per-event transcript flush，崩在哪都能看到已产出 turn（P-S2 解决） |
| 实现复杂 | ❌ 需 SSE 帧解析（`event:`/`data:`）+ 并发（SSE 消费与触发并发）+ 按 session 过滤 + 完成判定 + 断线重连 |
| 完成判定 | ⚠️ 须正确识别 `session.idle`/finishReason 为 turn-done，错判=挂死或早断 |
| 与 claude 对齐 | ✅ 同 IR/IRConsumer/transcript/Logger 管线，最大对齐 |
| tokens | ✅ 可从 `message.updated` info 抽（P-S5 顺带） |
| 连接稳健 | ✅ SSE 为长连接而生（chunked + keep-alive），无 3600s 单请求 |
| 隔离性 | ❌ 依赖 opencode SSE 事件词表与载荷 schema，版本漂移有风险（P-S4） |
| Tool 可观测 | ✅ `tool.execute.before/after` 给工具调用粒度（POST 模式无） |

**一句话**：POST 赢在简单/隔离/确定，输在实时性/可诊断/对齐——而后三者正是用户诉求。
流式赢在用户真正要的实时可见 + 崩溃可定位 + claude 对齐，输在实现复杂 + SSE 词表耦合
（需 spike 实测证伪/坐实）。

## 2. 方案选项

### 方案 A：纯流式（prompt_async + SSE 权威）—— 最大 claude 对齐
- `GET /event` 订阅 SSE（先于触发，按 session_id 过滤）→ `POST prompt_async`（204）
  → SSE 事件驱动：`message.part.updated`/`tool.execute.*` → IR record → 复用
  `IRConsumer` + transcript flush + `agent_stream` Logger；`session.idle`/finishReason
  为 turn-done 停消费；artifacts/metrics 仍走 `_build_result`。
- **删**阻塞 `POST /message` + 事后 `GET /message` 重建通路（§2.5 单一通路）。
- 优：单一传输路径，与 claude 完全同构，最 §2.5 合规；实时性/可诊断/对齐全满分。
- 劣：把"正确结果"也押在 SSE 上——SSE 词表/载荷漂移即断链（P-S4），未实测前风险最高。

### 方案 B：混合（POST 权威 + SSE 仅观测）—— 风险隔离
- **保留**阻塞 `POST /message` 作为结果/产物权威通路（已验证）；**并行**起一个 SSE
  订阅**只**为实时 `agent_stream` 日志 + per-event transcript flush（崩溃可定位）。
  SSE 非权威：解析失败/断线 → 仅丢实时视图，回退为现状（POST 重建），结果不受影响。
- 优： correctness 不赌 SSE，渐进、可回退；实时性/可诊断拿到 90% 收益。
- 劣：**两条传输路径并存**（§2.5 张力）——即便职责不同（权威 vs 观测），仍是双路；
  transcript 若两路都写需去重协调（让 SSE 喂 transcript、POST 仅取最终 info 做 metrics
  对账，可缓解）。

### 方案 C：subprocess `opencode run` 流式 stdout —— 否决
- opencode headless 权威路径是 `opencode serve`（`server.mdx`）；`opencode run` 偏
  TUI/CLI 语义，非 SDK 接缝；与 claude `query()` 进程模型类比牵强，且解析 stdout 文本
  比解析结构化 SSE 更脆。**否决**。

## 3. 推荐与 §2.5 张力处理

- **首选 A，B 为 spike 不通过时的退路**：两后端共享 step-68 IR（P-S3）使 A 的实现成本
  主要在"SSE event→IR"映射 + 并发框架，下游全复用；一旦 spike（§4）证实 SSE 载荷稳定、
  `session.idle` 可靠，A 既是 claude 最大对齐、又是最 §2.5 合规的单一路径。
- **B 的存在价值 = "正确性不押未实测的 SSE"**：若 spike 揭示 SSE 载荷不稳/`idle` 不可靠，
  B 用 POST 兜 correctness、SSE 仅观测，是可接受的**稳定架构**（两路职责正交：权威 vs
  观测，非同一职责两套实现）。但若 SSE 稳定，A 严格优于 B（消双路）。
- **避免"长期 B"**：B 若选定，须在 L4 标注"SSE 词表经 N 次回归稳定后收敛为 A"的退出
  条件，不允许 B 无限期双路存续（§2.5）。

## 4. 决定性风险 + spike gate（验证先行，§9 范式）

复用 `04/05/06-global-config` 的实测范式（`opencode debug` / 真实 serve 探针），**A/B
落地前必须打穿**：

- **Spike-1 SSE 载荷 schema**：真实发一条 prompt_async，抓 `GET /event` 全量事件，
  摸清 `message.part.updated` / `message.updated` / `session.idle` / `tool.execute.*`
  的 `properties` 字段（part 增量是 full-replace 还是 delta？tool 状态机字段？idle 是否
  必发？）。→ 决定"SSE event→IR"映射可行性与字段名锚点（P-S4）。
- **Spike-2 订阅时序**：`GET /event` 必须先于 `prompt_async` 建立（否则丢首事件）；
  验证同 session 多 turn / resume 续发 / 429 重试场景下事件流是否连贯、能否按
  session_id+messageID 精确过滤（防串流）。
- **Spike-3 完成判定可靠性**：确认 `session.idle`（或 `message.updated` 的 finishReason）
  在正常完成 / 截断 / 工具中断 / subagent 派发 各场景都稳定触发，作为 turn-done 唯一
  信号（错判=挂死或早断）。
- **Spike-4 断线/重连**：SSE 连接中途断（serve 重启 / 网络抖动）是否丢事件、opencode
  是否 replay；不 replay 则 A 需补 GET /message 对账兜底（此时 B 更稳）。

**Spike 结果直接决定 A vs B**：全绿→A；任一不稳→B（或补对账后 A）。

## 5. 并发机制取舍（A/B 共性，L4 细化）

- **threading + stdlib SSE reader**（倾向）：opencode_backend 现为纯 stdlib 同步
  （urllib），SSE 帧可逐行 readline 解析；后台线程消费 SSE 喂 IRConsumer + Logger，
  主线程 `prompt_async`（B）或等 done 信号（A）。零新依赖、与现有同步 `spawn` 契合。
- **asyncio**（备选，对齐 claude 的 `asyncio.run`）：需 `aiohttp`/`httpx` 或手写 async
  SSE reader，新依赖 + 重写 spawn 为 async。仅在 threading 证伪阻塞问题时采用。
- 判据：SSE 长连接 readline 是否阻塞主线程退出/被 stall 打断——spike 时验证。

## 6. 能力对齐矩阵（A 落地后 vs claude）

| 维度 | claude 现状 | opencode A 落地后 | 对齐 |
|---|---|---|---|
| 中间 turn 实时日志 | `agent_stream` per-event | `agent_stream` per-event（同 Logger） | ✅ |
| transcript per-event flush | ✅ | ✅（同 `_write_transcript_record`） | ✅ |
| 崩溃可定位 | ✅ | ✅ | ✅ |
| session_id 首事件捕获 | ✅ | ✅（`message.updated`/首个带 sid 事件） | ✅ |
| 截断检测 | stop_reason→truncated_turns | finishReason→truncated_turns（已有映射） | ✅ |
| stall 内容信号 | content-based should_stop | `session.idle`+content 混合（待 spike） | ⚠️ 待定 |
| tokens | ❌（两后端都缺） | 可顺带补（P-S5） | 增量 |
| subagent DISPATCH 可观测 | SDK 折叠进父流 | opencode `task` 事件（待 spike 验可见性） | ⚠️ 待定 |

## 7. 约束核对（落地前自检）
- §1.2 合理性：A 由 spike 背书后是四把尺子最优解（单路/对齐/可诊断/可扩展）；B 是 spike
  不通过时的正确兜底。
- §2.5 唯一通路：A 单路最合规；B 须标退出条件防长期双路。
- §3.4/§3.9：双后端 UT + 真实 ST 守护（SSE 真链路须 `@llm` 真 spawn 不 mock）；heavy_llm
  端到端流式链路用户确认后跑（§3.11）。
- §1.3：SSE 事件→IR 映射若发现词表版本耦合，加载期/启动期做最小 smoke 校验（首事件非
  `server.connected` 即告警），不推迟到运行期静默。
- §1.8：本 L3 已冻结（§8 决策）；L4 动手前写（spike 后）；进度挂 L2 总纲一行。

## 8. 四把尺子评估 + 决策冻结（用户拍板 2026-07-20）

四把尺子（§1.2：可维护/可扩展/可诊断/架构合理）逐选项判定：

### 8.1 目标架构 A vs B

| 尺子 | A 纯流式 | B 混合 |
|---|---|---|
| 可维护 | ✅ 单一传输路径，与 claude 单路哲学一致，无双路债；"事件→IR"承重但无 fallback | ❌ 双传输路径驱动同次 run（§2.5 张力），transcript 双写归属 + 退出条件是新维护面 |
| 可扩展 | ✅ 第三后端沿用"流 native event→IR"；新事件均匀映射 | ⚠️ 观测路径可扩但"双路"范式不易推广，是风险隔离形态非干净扩展点 |
| 可诊断 | ✅ per-event flush 达 claude 级；**但** correctness 押 SSE 完成判定，误判=挂死/早断且无交叉校验 | ✅✅ 最强：SSE 实时视图 + POST correctness 交叉校验，不一致本身是诊断信号 |
| 架构合理 | ✅ 单一职责传输层，与 step-68 IR 边界同构 | ⚠️ 两路驱动 transcript 模糊 single-source-of-truth，artifacts/metrics 归属有越层风险 |

A 在可维护/可扩展/架构合理更优但**全部有条件**（SSE 可靠）；B 在可诊断无条件最强。

### 8.2 过程 spike 先行 vs 直接动手

| 尺子 | spike 先行 | 直接动手 |
|---|---|---|
| 可诊断 | ✅ 运行期前探测完成判定/断线地表；spike 事件集=解析器测试夹具 | ❌ SSE 词表未实测前写解析器，完成判定错只能运行期暴露 |
| 架构合理 | ✅ "机制存在性 claim 先打穿再定案"是 §9 既有边界 | ⚠️ 信息不全下注，非严谨 |

### 8.3 并发 threading vs asyncio

| 尺子 | threading+stdlib | asyncio |
|---|---|---|
| 可维护 | ✅ 零新依赖，与 opencode_backend stdlib-only 风格一致，spawn 同步契约不变 | ❌ 新依赖（aiohttp/httpx），spawn 重写为 async |
| 可扩展 | ⚠️ SSE reader 可复用；第三后端若强制 async 则两模型并存 | ✅ async 范式易组合 |
| 可诊断 | ⚠️ 线程生命周期可记；孤儿/竞态难诊断；IRConsumer 线程安全是新不变式 | ✅ 结构化并发纪律性强；但 async bug 同样隐蔽 |
| 架构合理 | ✅✅ I/O 长流+同步主线程的最小并发解；不强行 async 重构 | ❌ opencode serve 是 HTTP，async **非强制**（claude 是 SDK 强制），仅为对齐付代价不必要 |

### 8.4 tokens 纳入 vs 不纳入 vs 机会主义

| 尺子 | 纳入 | 不纳入 | 机会主义 |
|---|---|---|---|
| 可维护 | ✅ 填 metrics 契约；但两路径维护 | ⚠️ P-S5 仍开 | ✅ 免费才填，不强加维护面 |
| 可诊断 | ⚠️ token 字段未文档化，猜错=静默 0，新静默失败面 | 中性 | ✅ 不引入新静默面 |
| 架构合理 | ❌ 跨关注点越边界 | ✅ 干净范围 | ✅ 保焦点，映射层即扩展点 |

### 8.5 冻结决策

- **过程**：spike 先行（§9 verify-first；可诊断+架构合理两尺子胜）。
- **目标**：默认 **A**（四把尺子最优兑现），spike 任一不稳退 **B**（可诊断兜底）。A/B 由 spike 结果机械决定，不主观判断。
- **并发**：**threading + stdlib** SSE reader（可维护+架构合理胜；async 非强制）。spike 验不阻塞退出后定；证伪切 asyncio。
- **tokens**：**机会主义**——不纳入为主线，Spike-1 若实测 `message.updated` 顺手带 token 用量则零成本抽；否则留 follow-up。

**Spike 环境（2026-07-20 实测就绪）**：opencode 1.18.3、项目 `opencode.json`（anthropic/GLM-5.2，baseURL `1.95.37.146:3000/v1`）、网关可达、企业代理已透传。可直接起 serve 跑 spike。

## 9. Spike 实测结果（2026-07-20，opencode 1.18.3）— A 确认可行

跑 `/tmp/spike_sse.py`：起 serve → `GET /event` 订阅 → `POST /session` → `POST /session/:id/prompt_async`（204）→ 抓 84 帧。四视角结论：

- **Spike-1 载荷 schema（✅ 全映射）**：
  - SSE 帧格式 = `data: {"id":"evt_...","type":"<事件>","properties":{...}}`（**无 `event:` 前缀**，type 在 JSON 内，符 sdk.mdx `event.type/properties`）。解析器须读 `data:` 行解析 JSON 按 `.type` 派发。
  - `message.part.delta` `{messageID, partID, field:"text", delta:"<增量>"}` —— **流式文本核心事件**，映射 IR text 增量。
  - `message.part.updated` `{part:{type:"text"|"step-start"|"step-finish", text, messageID, id}}` —— 全 part（user 回显 + 组装态）。
  - `message.updated` `{info:{role, agent, model, tokens:{total,input,output,reasoning,cache}, cost}}` —— 完成态带 **tokens**（维度3 兑现：零成本抽）。
  - `session.updated` `{info:{tokens, cost, ...}}` —— session 级 tokens/cost。
  - `session.idle` `{sessionID}` —— turn-done（极简载荷）。
  - `session.status` `{type:"busy"|"idle"}` —— 状态序列 busy→idle。
  - `session.error` `{error:{name, data:{message}}}` —— 错误（本次为真实 HOME 下 `/root/.claude/skills/cannbench-atk-pipeline/SKILL.md` YAML 解析错，**非网关/LLM 失败**；模型仍正常返回 "OK"，output tokens=2。生产隔离 HOME 即避免）。
  - `server.connected`（首事件）/`server.heartbeat`（keepalive，9×）/`plugin.added`（启动噪声，45×）。
  - **每事件 `properties.sessionID` 都在 → 按 session 过滤极简**。
- **Spike-2 订阅时序/过滤（✅）**：先订阅后触发，`server.connected` 起全程捕获；sessionID 过滤精确防串流。
- **Spike-3 完成判定（✅ 双信号冗余）**：`session.idle` 与 `session.status{type:idle}` 都可靠触发；watchdog 用 wall-clock 仅作"防 SSE 静默挂死"硬兜底（非 stall 判定，stall 仍 content-based）。
- **Spike-4 断线重连（⏸ 未测，不阻断）**：SSE drop→按 transient 走既有 resume 门；防御性处理，留 ST 验证。

**关键 caveat（影响 L4）**：finishReason/stop_reason **不在 SSE 干净完成时携带**（实测仅 `step-finish` part 名含 "finish"，无真 finishReason 字段）。→ Option A 完成后做**一次轻量 `GET /session/:id/message/:lastAssistantMessageID`** 取 finishReason（截断检测）+ 权威 tokens 对账。**这不是 Option B 的双路**——SSE 仍是流式/transcript 的唯一权威通路，final GET 只读末条 message 的 info 元数据，不重放 history。

**决策（机械执行）**：spike 全绿 → **方案 A（纯流式）**。tokens 机会主义兑现（`message.updated` 带用量 → 零成本填 metrics）。

## 10. 实施落地修正：A → B（2026-07-21，动手时据实调整）

落地读 `spawn` 全文后发现：**纯 A 要把已验证的 429-backoff / resume-degrade / session-gone
重试逻辑整体改成事件驱动**（动 correctness 路径，风险与收益不匹配——用户核心诉求是"实时
日志"，不是"删 POST"）。故实施改用 **B（增量叠加）**，四把尺子复核反而更优：

- **可维护**：保留已验证的 POST+重试逻辑（> 重写未验证的事件驱动重试）；transcript 仍由
  既有 GET history→`_parts_to_records`→IRConsumer（不变）。
- **可诊断**：SSE 实时 `agent_stream`（用户诉求）+ POST 交叉校验，双路信号。
- **架构合理**：POST=result/retry 权威、SSE=observability，**各是各职责的唯一通路**——非
  同职责双路，§2.5 不违背。
- **落地**：新增 `GET /event` daemon 订阅（与阻塞 POST 并发），SSE 事件→`agent_stream`
  Logger 行（per assistant text/tool part，带 block-type 标签 + chars + elapsed）+ tokens
  捕获。POST/retry/degrade/IRConsumer/transcript **零改动**。spike-verified 真实 serve 跑通
  （8 条 agent_stream 实时落日志，含 `tool:read` 可见，turn/chars/elapsed 实时）。

**实测修正（spike 未覆盖的 opencode 行为）**：`message.updated(role)` 在消息**完成时**才发
（滞后），assistant part 流式时 role 标签仍是上一个 user——故 `agent_stream` 按 **block type**
判（非 message role），否则会误跳过所有 assistant part（含 tool 调用）。turn 在
`message.updated(role=user)`（交换开始、先于 part）bump，避免滞后。

**A 作为后续收敛（非本次）**：待 SSE 驱动重试经实战验证后，可把 429/degrade 搬到事件、删
阻塞 POST，收敛为纯 A 单传输。本次不实施（合理性优先，不为纯洁性付未验证风险）。
