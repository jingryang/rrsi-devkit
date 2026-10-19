# 27 — infra 错误分类 + codegen 熔断器不误伤 + resume 可恢复（P50 实施）

> L4 实施方案。L1 问题记录见 `06-problems.md` P50。L3 方案决策已在本仓一次排障对话中
> 拍板，此处压缩为「方案决策」一节（frozen）。

> **⚠️ 部分 supersede（2026-07-17，step 57）**：本文把 **429** 归 infra「不重试、不加 backoff（YAGNI）」的判定，其证据是单次 503 `No available channel`（真配置错）语境。批跑 20260715 多算子实证 429（`Request rejected (429)`）是**可 resume 的 burst 突发限流**（manifold resume 3 次终 DONE），非账号硬封 → 该判定对 **429 子类失效**，已由 `57-burst-429-resume-{analysis,impl}.md`（L1 P80）改为「独立退避-resume 内循环」。**本文对 `No available channel`/401/403 的 infra 判定仍完全有效**（那些重试确实无意义），infra 不变式保留。

## 背景（一句话）

run `20260707-091803-29a24f` 的 codegen 在 503「No available channel」（模型无网关频道，**本地配置错**）
下连烧 3 次迭代 → 熔断器跳闸 → 计数器随快照持久化 → 后续 resume 在 `actions()` 入口 0.0s 立即跳闸、
不 spawn agent，run 永久卡死；同一 run 的 integrate 设计子阶段 429 也烧光 3 次迭代 halt。
根因：infra 错误（配置/配额/鉴权）被当成逻辑失败计数，且熔断状态跨 resume 不复位。

## 方案决策（frozen）

按「重试有没有意义」分类，**不**按 HTTP 状态码；且**不**对 infra 做自动重试（配置错重试无意义）。

| 类 | 例子 | 重试有意义？ | 处理 |
|---|---|---|---|
| SSE 流式故障 | "Content block not found" | 有（中途断流） | 立刻 resume session（**现状不变**，`_TRANSIENT_ERROR_MARKERS`） |
| **infra（配置/配额/鉴权）** | "No available channel"、"Usage limit reached"、401、403 | **没有** | 不重试、**不计数**、halt + 写明可操作原因 |
| 逻辑失败 | coder 真修不动 build/精度 | 没有（要看 N 次确认） | 原 N-strike 熔断（计数） |

对应 CLAUDE.md §1.2 三件套：
- **正确改动（主修复，保不变式）= A**：`AgentResult.error_type` 把 infra 与逻辑失败区分；infra 不消耗熔断预算。不变式：*失败预算只计逻辑失败*。
- **宽容兜底（last resort）= B**：resume 复位 `codegen_consecutive_failures` + 清 infra 类型 `last_error`，防 run 永久死亡。
- **可观测 = C**：halt 日志带 `failure_reason`，写明「infra: 模型 X 无可用 channel，改配置后 resume」。

## 改动配方

### A-1 backend 分类（stage 无关，根因层）

- `capabilities/agent/backend.py`：`AgentResult` 新增 `error_type: str | None = None`
  （`None`=逻辑/默认；`"infra"`=配置/配额/鉴权/网关不可达，不可重试、非逻辑失败）。
- `capabilities/agent/sdk_backend.py`：新增 `_INFRA_ERROR_MARKERS`（"No available channel" /
  "Usage limit reached" / "API Error: 401" / "API Error: 403"）+ `_classify_error_type(text) -> str | None`。
  在 crashed 路径的 `fatal`/`partial` 构造点（`failure_reason` 已在手）设 `error_type`。
  **不**加入 `_TRANSIENT_ERROR_MARKERS`（不重试），**不**加 backoff（YAGNI，重试对配置错无意义）。

### A-2 codegen 接线（急性 bug 所在）

- `stages/codegen.py` `transition()` 失败尾：`error_type=="infra"` 时 **不**递增 `codegen_consecutive_failures`，
  `last_error.error_type="infra"`、`message` 带 `failure_reason`（C）。
- `stages/codegen.py` `actions()`（熔断检查之后）：`state.last_error.error_type=="infra"` 时记 error 日志 + `return []`
  （同熔断器模式，使 stage 终止），但**不动计数器**。→ 首次 infra 即 halt，不烧满 N 次。

### B resume 复位

- `application/dispatcher.py`：抽纯函数 `_resume_breaker_reset(state) -> dict`
  （`codegen_consecutive_failures=0`；若 `last_error.error_type=="infra"` 则 `last_error=None`），
  在 resume 分支的 `state.with_updates(...)` 里展开应用。
  - **为何同时清 infra `last_error`**：A-2 的 infra 守卫看 `last_error.error_type=="infra"`，
    若 resume 保留它，首次 `actions()` 即被守卫拦下 → 抵消 B。清掉才让人工修复后的 resume 真正重试。
  - **为何落 dispatcher 而非 `State.from_snapshot`**：from_snapshot 语义是纯反序列化；
    「这是 fresh resume 尝试」是策略决策，归 resume 决策层（与其它 CLI override 同层）。

### C 可观测

codegen 的 infra halt 日志已带 `failure_reason`（A-2 写进 `last_error.message` 并在 `actions()` 输出）。

## 验证（UT，TDD 红→绿）

- `tests/ut/capabilities/test_capabilities.py`：`AgentResult.error_type` 默认 None / 可设；
  `_classify_error_type` 对 503/429/401/403 → "infra"，对逻辑错误文本 → None。
- `tests/ut/orchestration/test_stages.py` `TestCodegenStage`：
  - `test_transition_infra_does_not_increment_breaker`：fatal+error_type="infra" → `codegen_consecutive_failures` 不变、`last_error.error_type=="infra"`。
  - `test_actions_infra_last_error_halts`：`last_error.error_type=="infra"` → `actions()` 返回 `[]`。
  - 逻辑失败仍递增（既有 `test_transition_partial_counts_as_failure` 守护，不回归）。
- `tests/ut/application/test_dispatcher_resume_bridge.py`：`_resume_breaker_reset` 对
  breaker=3 + infra last_error → 返回 `codegen_consecutive_failures=0` + `last_error=None`；
  对 breaker=3 + 逻辑 last_error → 计数清 0 但保留 last_error（携上下文进 resume）。

回归：全量 UT。**非 §3.9 对象**：纯逻辑/分类/字符串语义，UT 等价覆盖，非 LLM 行为。

## 范围边界（明确不做 / deferral）

- **设计子阶段（template-division/tiling/integrate/docgen/validate）的 stage 侧 infra 接线 = DEFER**。
  理由：(1) 无 sticky 熔断器，resume 天然重跑（本 run 19:04 resume 后 integrate 即成功，已实证），
  不会出现 codegen 那种「永久卡死」；(2) backend 的 `error_type` 分类已就位，将来给设计子阶段接线时信号免费可用，
  现在逐个 substage 接线属扩大面、违反「avoid overdesign」。
  本次仅记录、不静默——L1 P50 关联节标注此 deferral。
- **不加 infra 自动重试 / 退避**：用户定调「No available channel 是本地配置错，重试只会一直报错」。
  现状 backend 对非 transient 已不重试，保持。
