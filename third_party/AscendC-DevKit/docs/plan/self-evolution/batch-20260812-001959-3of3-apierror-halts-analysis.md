# batch 20260812-001959 — 根因分析（L3）

> 配套：L1 事实见 `batch-20260812-001959-3of3-apierror-halts-issues.md`（P1 服务端 APIError 全 halt / P2 forkjoin fail_strategy=halt 放大 / P3 观察）。
> 本文分析**为什么**、列出**有哪些选项、选哪个、为什么**。本节为调研态，拍板后冻结。
> 分析者：Claude。日期：2026-08-12。调研动因：用户确认「服务端错误无法解决」，要求确认 resume 是否生效、能否统一走 resume 且重试次数可配置、审视 thinking 回传 / type validation 两个错误。

---

## 结论先行

**根因分层**（与上批 20260810 用户确认的"第三方网关静默中断"同源，形态升级）：
1. **服务端**：opencode ↔ 第三方代理网关（baseURL `http://1.95.37.146:3000/v1`，模型 `deepseek-v4-flash`）的 **Anthropic 协议适配缺陷**——`content[].thinking must be passed back` APIError（7 次，确定性复发）+ `Type validation failed: message_delta` UnknownError（2 次）。**非随机抖动，属协议兼容问题，resume 收效有限，应优先配置规避**（§P3）。
2. **框架放大**：design 阶段 forkjoin 分支（precision-perf / anchor-per-template）对 **partial（crashed）直接 `fail_strategy=halt`**，且 `_classify_error_type` 不识别 APIError/UnknownError（返回 None → 默认逻辑失败）→ 服务端错误被 halt 拦截，剩余迭代预算不启用。

**方案方向（本 L3 拍板 + 调研）**：
- **A（核心，拍板）**：服务端错误统一「黑名单排除 + 有限次原地 resume」，**重试次数/预算可配置**（复用 `runtime_config` 注入模式）。
- **B（拍板）**：服务端错误统一进主日志（`Logger.error` + halt 带根因），消除当前"APIError 在主日志静默"的可观测性缺口（§1.3）。
- **C（调研态）**：thinking 回传 / type validation 的**配置规避**（关 thinking / 换模型）——这两类是确定性协议缺陷，resume 兜不住，需从源头评估。

---

## A. 服务端错误统一「黑名单排除 + 有限次原地 resume」（核心，拍板）

### 现状（缺陷定位）

| 错误形态 | 当前路径 | 问题 |
|---|---|---|
| silent-cut（末条 thinking-only） | **有** resume（backend 级 sidecar，Part 1/2 已实施，本批 11 次生效） | 无 |
| 429 burst rate-limit | **有**独立 bounded backoff resume | 无 |
| turn_stall（turn 停滞 + chars 静止 600s） | **有** infra_backoff（max_retries=3, max_total=600s）+ sidecar resume | 无（已是有界 resume） |
| crashed：APIError / UnknownError / 其他 message 级错误 | **无**——`_classify_error_type` 返回 None → 默认逻辑失败 → `fail_strategy=halt`（iteration 1/3 剩余预算被跳过） | **缺恢复路径** |

**根因**：`_shared.py:_classify_error_type` 只把「不可重试的 config/quota/auth」（黑名单 `_INFRA_ERROR_MARKERS`）识别为 infra；**其余 crashed 一律落默认失败**。而 crash 的判定基础（`_build_result` 里 `crashed=bool(err)`，err 来自 message 级服务端错误或 backend 异常）**本身已排除 agent 逻辑失败**——agent 想错/产出不全不会置 crashed。

### 方案（选型 + 理由）

**判定基础用「黑名单排除」，不用「白名单识别」**：

```
agent 结束
 ├─ crashed=False → 走契约/质量门（逻辑失败归这里，不属服务端错误）
 └─ crashed=True（服务端/backend 异常统一信号）
      ├─ 命中不可重试黑名单（No available channel/401/403/timed out/price/Usage limit…）
      │      → 不 resume，快速失败（首请求即同错误，秒级），上报「不可重试：<原因>」
      └─ 未命中 → 有限次原地 resume（sidecar 保留 + spawn 自动 resume）
                   ├─ resume 成功 → 继续，进度不丢
                   └─ 预算耗尽仍失败 → halt + 主日志暴露错误 + 如实上报外部故障
```

**为什么这样选**（四把尺子）：
- **可维护**：判定基础是 crashed 信号（已有），黑名单只用于"排除不可重试"（可保持小）；未知服务端错误**天然落入 resume**（不在黑名单即 resume），无需预先枚举——本批 APIError 就是"之前不在任何清单"的活例。
- **可扩展**：新增服务端错误形态自动被兜住（不在黑名单 → resume），不用每加一种错误打一个补丁。
- **可诊断**：resume 预算耗尽 → halt 前主日志暴露错误文本（配 B），外部故障可看见、可追责（§1.11）。
- **架构合理**：不新增机制，复用既有 sidecar resume + infra_backoff 骨架（§2.5 单一通路）。

### 恢复策略分离（实施优化，20260812 回填）

实现时进一步区分「怎么 resume」——`server_backoff_strategy` 单一来源（§2.5）：
- **429/503（限流/不可用）→ backoff**：指数退避 sleep 等窗口再 resume（429 需等限流窗口，有界）。
- **其他非 infra 服务端错误（APIError/type validation/未知）→ 立即 resume 不 sleep**：误判时只浪费一次重试预算，**不空等**——SSE transient（Content block not found）被吞进 backoff 真实 sleep 致卡死的回归实证（20260812），此为根治。
- 二者共享 `rl_attempt` 总重试上限（有界是有意设计），backoff 额外受 `rate_limit_backoff_max_total_s` 累计 sleep 封顶（900→600）。

**安全边界（防止误伤）**：resume 仅限 `crashed=True` 的服务端异常；agent 逻辑失败（契约不满足 / 质量门 / empty_artifacts）走原有逻辑，**不因"不在黑名单"被当作服务端错误 resume**——否则掩盖真实缺陷。

### 重试次数可配置（用户明确要求）

沿用 `resources/orchestration-config.json` `agent` 段 + `runtime_config.py` 读取的既有注入模式，**统一 resume 预算为配置键**（默认值按现有一致口径）：

| 配置键（agent 段） | 现状默认 | 方案语义 | 备注 |
|---|---|---|---|
| `resume_max_retries` | 10 | **服务端错误 resume 上限**（silent-cut 沿用） | 用户可调：网关不稳时下压省 token，稳定时上调 |
| `resume_max_no_progress` | 3 | 连续无进展止损 | 已有 |
| `infra_retry_max_retries` | 3 | turn_stall / infra 重试上限（沿用） | 已有，与 resume 上限口径统一 |
| `infra_backoff_base_s` / `factor` / `max_total_s` | 20 / 2 / 600 | 退避节奏 + 累计封顶（沿用） | 已有 |
| `opencode_turn_stall_s` | 600 | turn_stall 判定窗（沿用） | 已有 |

> 关键：**所有"有限次"都用同一个可配置预算模型**（max_retries + max_total 双封顶），不让 crashed 与 turn_stall/429 的口径漂移。默认值建议 crashed resume 上限 **3（对齐 infra_retry_max_retries）**、累计时间封顶沿用 max_total=600s——语义上"有限次"而非"无限吞 token"。

### 需要改的（指向 L4，本层不写代码）

1. `_classify_error_type` / backend crash 路径：crashed 且不在黑名单 → 不再落到默认失败/`fail_strategy=halt`，改进入 resume 预算。
2. forkjoin 分支对服务端错误（partial/crashed）的响应：`fail_strategy=halt` 不拦截服务端错误，用剩余迭代预算 + resume 循环（复用 infra_backoff + sidecar）。
3. 预算统一：resume/infra/429 三类走同一可配置 `max_retries` + `max_total` 双封顶。

---

## B. 主日志可观测性：服务端错误统一进主日志（拍板）

**现状缺陷**（用户指出的关键）：本批 APIError 在 run.log **零命中**（grep 无结果），只在 `agents/*.jsonl` transcript crash record 里。主日志只有 turn_stall（看门狗自己 `Logger.error`）和最终 halt。原因是 `opencode_backend.py:750 err=_message_error(...)` → `:767 _build_result(crashed=bool(err), crash_reason=err)` **中间无 `Logger` 调用**，crash_reason 只进 AgentResult → transcript。

**方案**（3 处，均低风险）：
1. backend crash 路径补统一 `Logger.error("Agent … crashed: <error_type>: <message>")`（对齐 turn_stall 的 ERROR 行格式）。
2. `[partial]` / `Workflow halted` 的 ERROR 行**附上最后崩溃的 crash_reason**（不再只写笼统的"fork-join 分支失败"）。
3. （可选）`events.jsonl` 的 spawn_agent action_complete 事件补充 error_type / failure_reason 字段（当前只有 result=partial，无诊断字段）。

**理由**：§1.3 可诊断性（不把错误静默吞掉、推迟到下游）；§1.11 外部故障如实上报——主日志可见后，网关故障可定位、可追责，而非静默变 0/3。

---

## C. thinking 回传 / type validation 的配置规避（调研态）

**为什么单独调研**：这两类是**确定性协议缺陷**（APIError 7 次贯穿全程，非随机），resume 后 opencode 仍以同样方式构造请求 → **同样错误复发**（本批证据：早期 APIError 被 resume 吸收多次，最后仍拖垮 3/3）。resume 只能兜随机/传输层错误，**协议缺陷需从源头规避**。

**配置真相**（`opencode-config.json`，框架 run 级生成）：
```json
"provider": { "anthropic": { "options": { "baseURL": "http://1.95.37.146:3000/v1", ... },
               "models": { "deepseek-v4-flash": { "name": "deepseek-v4-flash[1m]", ... } } } },
"model": "deepseek-v4-flash"
```
无显式 thinking 配置——opencode 对 deepseek-v4-flash 走 thinking 是 provider/model 默认行为。

**错误本质的再定位（用户 2026-08-12 两次指出，已修正为"待证假设"而非定论）**：
- **TUI 正常是强反证**（§1.11：同凭证正常工作是最强可用证据，与之矛盾应先怀疑假设）。用户观察 TUI 下 thinking 一致正常 → "opencode resume thinking 回传不一致" 不能作为定论。
- **本批早期 3 次 APIError 均 resume 成功**（unique 00:30 turn5 / grid 00:41 turn30 / unique 00:46 turn5 均恢复推进）——若"resume 必坏（同型请求复发）"，早期 resume 不可能成功。**该证据反驳"确定性 thinking 回传缺陷"假设**。
- 故 APIError 真实触发条件**未知**：候选假设包括 ① 网关侧特定条件（负载/上下文形态/窗口）偶发；② opencode serve 路径偶发（非确定性）；③ 其他。**须以最小复现实验证明根因，在此之前不写死任何单一归因。**

**选项（调研，未拍板；C 的第一步 = 复现实验，非修复假设）**：

| 选项 | 思路 | 依据/风险 |
|---|---|---|
| **C0. 最小复现实验（第一步，优先）** | 构造 TUI vs SDK（opencode serve）对照：多轮 thinking 请求 + resume，观察 APIError 能否复现、复现条件 | 证明根因再谈修；**复现不了 → 归为网关偶发，A（统一有限次 resume）已覆盖，无需动 thinking**；复现成功 → 定位是 serve 特有还是网关偶发 |
| C1'. 若复现指向 serve 路径 → 确保 resume thinking 与首轮一致 | 升级 opencode / 配置统一 thinking 行为 | 治本且保住 thinking 价值；仅在 C0 证明 serve 特有后启动 |
| C2. 关闭 thinking（reasoning off，fallback） | provider/model 配置禁 thinking | 绕开路径；风险：降低复杂任务表现；仅当 C1' 不可达 |
| C3. 换网关完整支持的模型 | 用网关对 Anthropic 协议完整的模型 | 治本但受网关通道限制 |
| C4. 上报网关协议缺陷 | 向第三方代理商报 thinking 回传 + SSE 流校验问题 | 外部项，框架不做，但 A/B 落地后错误可看见，为上报提供证据 |

**当前立场**：C 的下一步 = **C0 复现实验**（TUI vs SDK 对照，验证 APIError 真实触发条件），在充分测试证明前不把"thinking 回传不一致"当根因。**A（统一有限次 resume）+ B（可观测）已落地，对网关偶发已兜底；C 仅在复现证明需要时才动 thinking。**

**决策记录（用户 2026-08-12 拍板）**：**暂不深入分析与修改 thinking 根因**。判据：基于本批证据，thinking 问题判定为**非阻塞性**——①APIError 是间歇性单次失败（早期 3 次 APIError 后同会话继续成功推进 27 轮）；②A 方案 in-session backoff resume 吸收一次性失败，resume 后能继续执行、不会一直报 thinking；③唯一 halt 场景 = resume 预算内反复触发（网关持续异常），属兜底设计的 stop-loss，非阻塞性问题。故 C0 复现实验 / 升级 opencode / 切 backend 均**不立即执行**；A（resume 兜底）+ B（可观测）保持落地，真实重跑验证留待用户随时触发（heavy_llm 成本决策）。若未来出现"resume 后仍连续 thinking 失败致多算子 halt"的实证，再重启 C。

---

## 跨 A/B/C 取舍小结

- **A（统一 resume）**：覆盖所有服务端错误形态，重点是**让 crashed 不再被 fail_strategy=halt 拦截**，预算可配置、有界。对随机/传输层错误有效。
- **B（可观测）**：让服务端错误可见，任何形态都不再静默——A 兜不住（确定性协议缺陷）时，B 保证"可看见 + 可追责"。
- **C（配置规避）**：对确定性协议缺陷（thinking/type validation）从源头消掉，A/B 都治不了根。
- **诚实边界**：若服务端持续拒绝（确定性缺陷且无法配置规避），任何 resume 都只是延长到预算耗尽——此时**如实上报外部故障**（§1.11 / external-infra），由用户向第三方网关追责，而非框架无限重试吞 token。

**未决/待验证项**：
1. opencode 1.18.3 是否支持 per-model 禁 thinking（C1 可行性）。
2. deepseek-v4-flash 在网关（1.95.37.146）下 thinking 回传错误的精确触发条件（为什么早期 resume 能吸收、后期致命）。
3. A 方案落地时 forkjoin 分支与普通 stage 的 resume 预算是否需区分（先统一，观察是否需 split）。
4. A 的默认 `resume_max_retries` 取 3（对齐 infra）还是更高（如 5），需结合 C1 落地后服务端错误率定。
