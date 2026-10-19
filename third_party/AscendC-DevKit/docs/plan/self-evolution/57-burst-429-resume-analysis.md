# 57 — 突发 429 收进 backend session-resume 内循环（有界指数退避 + 可配置）（L3 方案分析）

> L3 方案分析：有哪些选项、选了哪个、为什么。关联 L1：`06-problems.md` P80；L4：`57-burst-429-resume-impl.md`。
> **supersede 关系**：本文推翻 `27-infra-error-classification-impl.md`（P50）对 **429 子类**的「归 infra、不重试、不 backoff（YAGNI）」判定；对 `No available channel`/401/403 仍沿用 step-27（那些重试确实无意义）。
> 产出时间：2026-07-17。用户已拍板三项决策（见 §2），本文记录取舍理由并冻结。

## 1. 问题复述（一句话）

批跑实证 `Request rejected (429)` 是**可 resume 的 burst 突发限流**（非账号硬封），但现措辞不匹配任何 marker 集，被当逻辑失败烧 stage iteration 预算、且每次 fresh 重跑丢 session 推理记忆（P80）。用户方案：429 后 sleep 一段、resume 同 session 发「继续」、有界重试、耗尽再 halt。

## 2. 用户拍板的三项决策（frozen）

| 决策点 | 选定 | 备注 |
|---|---|---|
| sleep+resume 落哪层 | **backend 内循环** | 复用 `sdk_backend.py` 既有 resume-retry 循环，session 推理记忆保留、不烧 stage 断路器、sdk+opencode 一处对齐 |
| 退避策略 | **指数退避 + 总时长封顶** | 参数**必须可在 `orchestration-config.json` 配置**，不配则用默认值 |
| burst vs 硬配额 | **统一按 burst 有界重试** | 措辞无法可靠区分；硬配额自然在退避预算耗尽后 halt（reason 可操作） |

## 3. 为什么落 backend 内循环（而非脚本层 / stage 层）

用户 runlog 里的手法是**脚本层**手动做的：`WORKTREE_ROOT=... RESUME=1 bash batch_self_evolve.sh` + 人工等一阵重投。三个层次对比：

| 落点 | session 推理记忆 | 断路器影响 | 通路数（§2.5） | 判定 |
|---|---|---|---|---|
| **backend 内循环** ✅ | **保留**（resume 同 session_id） | 不烧（重试全在 backend 内消费，caller 只见一个 AgentResult，与 step-11 B2-resume 同架构） | 一处（sdk+opencode parity） | **选定** |
| stage 层（现状 429 误落此） | 丢（fresh re-dispatch） | 烧 iteration/N-strike 预算 | — | 现状 bug，即 P80 |
| 脚本层手动 RESUME | 丢（整 run 级 resume，snapshot 跳已完成节点但被中断节点仍 fresh spawn） | 整 run 重入 | 双通路（且脚本正被 step-55 瘦身删除 RESUME 逻辑） | 否决 |

- **架构合理（§1.2）**：429 是 agent spawn 的**瞬时可恢复故障**，与 `Content block not found` 同类（都「中途断、session 没坏、resume 可续」）。它的正确归属层就是 backend 的 spawn 重试循环——step-11 已为 SSE 断流建好这条循环，429 本就该复用它，而非在 stage 层被当逻辑失败、或在脚本层靠人肉重投。
- **可维护**：sleep+resume 的生命周期全归 backend，不新增 State 字段、不碰 stage transition；与 step-40 sidecar（session_id 磁盘态归 backend）一致。
- **§2.5 唯一通路**：不新造第四条 429 处理路；backend 循环是 sdk+opencode 已有的同一条，只扩其触发集 + 加退避。脚本层 RESUME 正被 step-55 删，不能反向加固它。

## 4. 429 收进重试集的三种落法（选 B）

429 要变「可重试」，落点有三：

- **A：加进 `_TRANSIENT_ERROR_MARKERS`**。最省事，但会让 429 与 `Content block not found` **共用 no_progress 闸**——而 429 被拒时天然「零新增 text/tool/file」，会瞬间打满 `no_progress>=3`（默认）→ 3 次内就放弃，退避几乎没机会生效。**否决**（闸语义对 429 错配）。
- **B：新增独立 `_RATE_LIMIT_MARKERS` + 独立退避重试预算** ✅。429 判定与 SSE 瞬态判定分开；429 命中 → sleep（指数退避）→ resume「继续」，用**独立的 `rate_limit_max_retries` 预算**，不与 SSE 的 `no_progress` 混。**选定**。
- **C：把 429 归 infra 但对 infra 加退避重试**。会污染 infra 语义（`No available channel`/401/403 重试确实无意义，step-27 的不变式「失败预算只计逻辑失败、infra 不重试」要保住）。**否决**。

### 选 B 的四把尺子

- **可维护**：新增 marker 集 + 退避 helper 是纯增量，`_is_transient_error` / `_classify_error_type` 语义不动，step-27 的 infra 不变式原样保留。
- **可扩展**：未来别的「服务端软拒、可退避重试」措辞（如 503 burst）加进 `_RATE_LIMIT_MARKERS` 即自动获得退避-resume，无需再打补丁。
- **可诊断（§1.2）**：每次退避 sleep 前 `Logger.action("agent_backoff", ...)` 记 attempt/sleep 秒数/累计等待；退避预算耗尽 halt 时 `failure_reason` 写明「429 burst：退避 N 次累计 Xs 仍被限，判为硬配额或长 burst，请隔窗 resume」——不静默吞、不把错误推迟到更难定位的下游。
- **架构合理**：主修复落 backend（物理正确层）；step-27 的 infra 分类作为 last-resort 兜底仍在（真硬配额措辞若某天精确化，可回落 infra 快速 halt）。

## 5. 退避参数设计（指数 + 封顶，全可配置）

复用 `resume_limits()` 的加载模式（`runtime_config.py`，读 `orchestration-config.json` 的 `agent` 段，缺失/非法 fail-fast）。新增四参数，均有默认值：

| 配置键（`agent` 段） | 默认 | 含义 |
|---|---|---|
| `rate_limit_max_retries` | 6 | 429 退避-resume 最大次数（独立于 `resume_max_retries`） |
| `rate_limit_backoff_base_s` | 30 | 首次退避基数秒 |
| `rate_limit_backoff_factor` | 2.0 | 指数因子（30→60→120→…） |
| `rate_limit_backoff_max_total_s` | 900 | **总时长封顶**（累计 sleep 达此值即停止重试、halt）——真硬配额时快速止损，不 sleep 几小时 |

- 单次 sleep = `min(base * factor**attempt, 剩余可用总预算)`；累计到 `max_total_s` 即 halt。
- 默认组合 30/60/120/240/(封顶) ≈ 15min 内 4–6 次尝试，够跨过典型 burst 窗口（manifold 实证隔窗可过），又不至真硬配额时空等。
- **可配置是硬要求**（用户）：参数进 config，不硬编在 backend；default 常量在 `runtime_config.py` 单一权威源，backend 由 dispatcher 注入（同 `resume_max_retries` 现有注入链），**capabilities/L5 不 import orchestration/L3**。

## 6. burst vs 硬配额：为何统一按 burst（不按措辞二分）

- runlog 客观事实：`Request rejected (429) · Weekly/Monthly Limit Exhausted` 与真硬配额**可能同文案** → 措辞二分不可靠（P80 客观事实 2）。
- 统一按 burst 有界退避重试：真 burst → 隔窗跑通（收益）；真硬配额 → 退避预算/总时长封顶耗尽 → halt，`failure_reason` 可操作（止损）。两种情况都得到正确终态，无需事前区分。
- 这也回避了「误判硬配额为 burst 而空等几小时」——`rate_limit_backoff_max_total_s` 封顶就是那道止损闸。

## 7. 与既有机制的边界（不重叠，§2.5）

- **vs step-11 SSE resume（`Content block not found`）**：同一 backend 循环、不同触发集与闸。SSE 用 `no_progress` 闸（断流后应立即有进展）；429 用独立退避预算（被限期间天然零进展，不能共用 no_progress）。两者在 `_spawn` 循环里是并列的 elif 分支，各判各的。
- **vs step-27 infra（`No available channel`/401/403）**：infra 仍不重试、不计数、快速 halt（不变式保留）。本方案只把 **429 子类**从 infra 的「不重试」判定里拆出来单独退避重试。step-27 impl 顶部加 supersede 注记指向本 step。
- **vs step-40 session sidecar**：sidecar 提供跨 run resume 的 session_id 持久化；本方案是**同一 spawn 内**的退避-resume，用 in-memory `session_id`（已捕获）。两者互补：若 spawn 期间进程被硬杀，sidecar 仍是下次 run 的 resume 门票。
- **vs step-55 脚本瘦身**：脚本层 RESUME 手法被 step-55 删除后，backend 内退避-resume 成为 429 的**唯一**自动处置通路，不与脚本双通路并存。

## 8. 风险与残留

- **风险 1：sleep 期间进程被外部硬杀**——sleep 用 `asyncio.sleep`（可被取消），硬杀时 sidecar（step-40）已在盘上，下次 run resume 兜底。可接受。
- **风险 2：429 与真逻辑失败在同一 attempt 交替**——退避预算按「连续 429」累计；一旦某 attempt 返回非 429（真进展或真逻辑失败），退避计数复位/退出，交回既有 SSE-resume 或逻辑失败通路。
- **残留（不在本 step）**：疑似 9/10 的 precision_debug 编排器 async 自转（step-52/53/56）——那是 dispatch 语义 bug，429 退避治不了，也不该治。本 step 只治横切面「429 误分类 + 无退避重试」。

## 9. 结论

选 **B（独立 `_RATE_LIMIT_MARKERS` + 独立退避重试预算，落 backend 内循环）**。主修复保住「burst 429 可 resume 续跑、保 session 记忆、不烧 stage 预算」不变式；step-27 infra 兜底对非-429 保留；退避参数全可配置、总时长封顶止损。L4 见 `57-burst-429-resume-impl.md`。
