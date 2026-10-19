# turn-stall 恢复链路失真：P131c fresh-window 采样被 sidecar 自动 resume 击穿 — L1 问题记录（2026-08-12）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据 / 现象 / 根因 / 影响）。
> 不提方案、不排序、不写决策——修复方案见同目录 `02-analysis.md`（L3）。
>
> **触发背景（用户观测）**：当前工程使用的模型服务偶发「突然长时间无任何输出、也不报错」，
> 被框架判为 turn-stall 超时（600s）。本记录取证的是**框架对该观测的恢复路径**——turn-stall
> 看门狗触发后，框架是否真正按 P131c 设计意图恢复。
>
> **取证基线**：HEAD `a2c6137c`。两个机制先后独立落地：P131c 跨 run backoff-resume
> （trial-20260730）与 20260810 批 sidecar 自动 resume（`f7c7a88e` 之前，Part 2）。
> 二者**未考虑交互**，叠加后产生本记录的两项事实 P1/P2。

> 结论速览：设计的恢复语义是「**先原地 resume → 数次不成功 → 退化 spawn**」两阶段（Phase 1 续同一
> session 保上下文；Phase 2 换 fresh 采样新窗口）。但现状只有 Phase 1——sidecar 自动 resume 使每次
> P131c re-spawn 都重挂同一被杀 session，**永不进入 Phase 2**。对「session/网关窗口级卡死」
> （非 transport 级一次性断流），每次重试都在同一死窗上空转 600s，fresh window 永不采样，直到预算
> 耗尽才 halt。共两项事实 P1/P2。

---

## P1：恢复链路只有 Phase 1（resume）、永不进入 Phase 2（退化 spawn）——设计意图未实现

### 证据

- 设计语义（rev2 明确，见同目录 `02-analysis.md` 选项⑤）：turn-stall 后**先原地 resume**（续同一
  session 保上下文），**数次不成功后退化 spawn**（fresh 采样新窗口）。两阶段缺一不可。
- `capabilities/agent/opencode_backend.py:549-578`（20260810 批 Part 2 自动 resume）：
  re-spawn 时 `resume_session_id` 默认 None（runner `kernel/runner.py:892` 透传 `action.resume_session_id`），
  sidecar 存在（= 上一迭代会话崩溃未 clean finish）→ **以 `_RESUME_PROMPT`（"继续"）POST 回同一
  `session_id`**，不 fresh POST。
- `capabilities/agent/opencode_backend.py:782-791`：crash-salvage（含看门狗 kill）**保留 sidecar**
  作为 resume 句柄；sidecar 仅在 clean finish（`:789-791`）与 resume-degrade session-gone（`:661`）清除。
- **无任何「resume 连续失败 → 退化 fresh」的计数或出口**（`runtime_config.infra_backoff()` 无此配置、
  backend 无计数器）——即 Phase 2 从未实现。

### 根因

20260810 批 Part 2 引入 sidecar 自动 resume 时，只实现「上一迭代会话被切/崩溃未 clean finish → 续跑」
的 Phase 1（保上下文），**未实现/未设计 Phase 2 的退化条件**。P131c（trial-20260730）的 re-spawn
语义被 Part 2 静默改写为「重挂旧窗口」，而两机制交互未做对质——「resume 数次不成功就换 fresh」这一
设计意图停留在口头，从未落进代码。

### 影响

- 当卡死是 **session/网关窗口级**（该会话的后续请求仍会卡死）而非 **transport 级一次性断流**时，
  每次 re-spawn 都回到同一卡死 session，**fresh window 永不采样**（Phase 2 缺失的直接后果）。
- 收敛路径退化为「退避 → 同一死窗」→ 最多 `infra_retry_max_retries`（3）次空转（每次含 600s
  空等 + 退避）后才 P116 halt，全程未做 P131c 声称的恢复动作。

---

## P2：无「resume 连续失败次数」计数与退化阈值（只有 session-gone 一条 fresh 出口）

### 证据

- `capabilities/agent/opencode_backend.py:655-691`：唯一从 resume 降级到 fresh 的入口是
  `_is_opencode_session_gone(post_exc)`——**session 在 opencode 侧已消失（HTTP 404）**才降级。
- sidecar（`base_backend.py:108-149`）只记录 `{agent_name, session_id, stage_name}`，**无
  `resume_fails` 计数**；crash-salvage（看门狗 kill）不写任何失败计数。
- `runtime_config.infra_backoff()`（`runtime_config.py:675-701`）只有退避节奏配置，**无
  `resume_attempts`（允许的连续失败次数）**。
- 即：设计意图「resume 数次不成功 → 退化」所需的**计数 + 阈值**两个要素在代码中都不存在。

### 根因

「resume 数次不成功退化」的 Phase 2 未实现（P1 根因的细粒度化）：既没有「这次 resume 是第几次失败」
的计数，也没有「达到几次就退化」的阈值。现状把 resume 建模成「无限重试」而非「有界探测后换 fresh」。

### 影响

- session 活着但卡死（opencode 不 404，`_is_opencode_session_gone` 不命中）→ 循环
  `resume → 600s 空转 → P131c 重试 → resume` → 预算耗尽才 halt，全程未采样 fresh window（叠加 P1）。
- 与 P1 叠加，是「session 级卡死」场景下恢复链路失真的完整闭环。

---

## P3：代价量化（为何值得修）

### 证据

- `infra_backoff()` 默认（`resources/orchestration-config.json` + `runtime_config.py:630-633`）：
  `infra_retry_max_retries=3`（修复后默认 4，见 L3/L4）、base 20s×2、累计退避 ≤600s。
- 单次 turn-stall 空等 = `turn_stall_s` 600s（`opencode_turn_stall_s=600`）+ 一次退避。

### 影响

- 最坏收敛代价 ≈ `3 × (600s 空等 + 退避)` ≈ **30+ 分钟纯空转**，且以 P116 halt（预算耗尽）收场，
  全程未做 P131c 声称的恢复动作。对「本可通过一次 fresh 换窗恢复」的场景，这是纯粹的浪费。

---

## 问题关系（事实层，不含方案）

| # | 事实 | 与其他问题关系 |
|---|---|---|
| P1 | 恢复链路只有 Phase 1（resume）、永不进 Phase 2（退化 spawn） | P2 的承载对象：被重挂的正是同一死 session |
| P2 | 无 resume 失败计数、无退化阈值（仅 session-gone 404 一条 fresh 出口） | 放大 P1：Phase 2 的两个要素（计数+阈值）都缺失 |
| P3 | 代价 ≈ 3×(600s 空等 + 退避)，以 P116 halt 收场 | P1/P2 的量化后果 |

> 方案（如何让「短暂 transport 抖动」廉价原地恢复、同时「session 级卡死」能真正采样 fresh window，
> 二者不误伤、预算有界）见同目录 `02-analysis.md`（L3）；具体代码配方见 `03-impl.md`（L4）。
