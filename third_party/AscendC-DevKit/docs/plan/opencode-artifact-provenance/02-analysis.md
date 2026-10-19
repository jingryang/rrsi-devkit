# opencode 后端产物落点取证失效 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。
> 用户已拍板（2026-07-18）：P1 走 (b) 产出端归一化；P2 走 GET 会话历史。本文档冻结。

## 关键前提：transcript block schema 的唯一消费者是 harvest

全仓核实（grep `kind`/`tool_name`/`tool_input`/`blocks` 消费点）：读取 agent transcript **block**
结构的只有 `_harvest_relocation_evidence`（`design_substages.py:128`）一处。`show` 命令读的是
`events.jsonl`（事件流），**不读** agent transcript 的 blocks。故改 transcript block schema 的
影响面 = harvest 一处，无 `show`/回放牵连。这是下面选 (b) 成本极低的客观依据。

目标 schema（SDK `_serialize_block`，`_shared.py:27`，即 harvest 期望）：
- 文本：`{"kind": "text", "text": ...}`
- 工具：`{"kind": "tool_use", "tool_name": <名>, "tool_input": <参数>}`
- record：`{ts, type, turn, blocks}`，`turn` 为真实轮次序号。

opencode 现状（`_parts_to_records`，`opencode_backend.py:621-648`）：block 用 `type`/`name`/`input`、
record `turn` 硬编码 1——block 级与目标 schema 零交叉（P1），且只落末条消息（P2）。

## 决策 1（P1）— schema 归一化方向：(a) 改消费端兼容 / (b) 改产出端对齐 → **选 (b)**

- **(a) 让 harvest 兼容 opencode 的 `type`/`name`/`input`**：改消费端，harvest 内部维护 SDK+opencode
  两套字段映射。
- **(b) 让 opencode `_parts_to_records` 落盘对齐 SDK 的 `kind`/`tool_name`/`tool_input`**：改产出端，
  transcript 落盘即归一，harvest（唯一消费者）与未来任何消费者只认一种 schema。

**选 (b) 的理由（四把尺子）**：
- **可维护**：归一化只在 `_parts_to_records` 一处；(a) 要在消费端长期维护两套映射。
- **可扩展**：transcript schema 成为 backend 对上层的统一契约，未来新 backend 只需在自己产出点对齐同一
  schema；(a) 每加一个 backend，消费端就多一套映射（N×M）。
- **可诊断**：落盘证据全局同构；(a) 下 transcript 文件仍是两种格式，排障要先分清后端。
- **架构合理**：归一化落在**产出边界**（backend 是翻译点），对齐 §1.6（业务层只持统一 protocol、
  实现注入）、§1.9（`chip.py` 单一翻译点）、§2.5（同一职责一条通路）。(a) 把后端差异归一化的职责
  推给消费端，是留债。

**成本与边界**：唯一代价是旧 transcript 文件（`type`/`name`/`input`）与新格式不一致——按 §1.4
不考虑向后兼容，旧 transcript 是历史运行数据、不迁移、不加读取兼容分支，直接改干净。因唯一消费者
harvest 本就期望新 schema，(b) 落地后 harvest 对 opencode transcript **自动生效、无需改消费端**。

## 决策 2（P2）— 采集完整性：补末条消息 parts / GET 会话历史 → **选 GET 会话历史**

- **仅补末条消息的 tool parts**：治标——若返回的最终消息本就不含中间轮次的工具调用，补也补不到。
- **完成后 `GET /session/{id}/message` 取整段会话**：opencode server 持久化全部消息（所有 turn、
  所有 parts 含 tool 调用），REST 端点暴露、`_http_json` 已具调用能力。遍历所有消息逐条落 transcript，
  用**真实 turn 序号**取代硬编码 1。

**选 GET 会话历史的理由**：一举解决 P2 两个表现——① 采到本轮全部 Write/Edit 的 `file_path`（harvest
取证的数据源）；② 恢复真实 turn（用户可观测症状）。落点仍在 `_parts_to_records` 邻域，与决策 1 一处收口。
**best-effort 边界**（§1.2 可诊断不阻断）：GET 失败/超时则回退到现有「POST 返回值 + turn 1」，仅记
WARN，不阻断 spawn 主流程——transcript 是诊断证据、非必需输入（与 step 51 harvest 的 best-effort 一致）。

## 决策 3 — Bash `cp`/`mv` 写文件仍不覆盖（沿用 step 51 决策 4）

step 51 已界定 Bash 命令写文件无结构化 `file_path` 字段、需命令解析、覆盖面弱于 Write/Edit，列为
best-effort 非阻塞项。本轮同样不覆盖 Bash 落盘路径——GET 会话历史会采到 Bash `tool_use` block，但其
`input` 是 `{"command": "..."}`，harvest 仍只解析 Write/Edit 的 `file_path`。范围一致，不扩。

## 决策 4 — 不改 harvest 逻辑本身

(b) 落地后 harvest 读的 `kind`/`tool_name`/`tool_input` 正是 opencode 归一后产出的字段，harvest
**零改动**即在两后端生效。仅补一条 UT：喂一份 opencode 归一格式的 transcript，断言 harvest 能定位
落在 wd 之外的 Write。不新增 harvest 分支（否则又回到 (a) 的消费端多态，自相矛盾）。
