# turn-stall 恢复链路 — L3 方案分析（2026-08-12，rev2）

> 层级：**L3 / 方案分析**。记录「有哪些选项、选了哪个、为什么」。调研演进、拍板后冻结。
> 问题事实见同目录 `01-problems.md`（L1）；具体代码配方见 `03-impl.md`（L4）。
>
> **rev2（2026-08-12，用户决策）**：设计意图明确为「**turn-stall → 先原地 resume → 数次不成功
> → 退化 spawn**」。rev1 的「resume 短窗升级 fresh」经对比后**放弃**（见下方选项①的否决理由）。
> rev2 与 rev1 的关键差异：不做短窗（满窗 600s，不误杀慢活），退化靠**计数**而非短窗探测。

## 目标

在 turn-stall / keepalive / hard-timeout 场景，恢复 P131c 声称的恢复语义，且：

- **短暂 transport 抖动**（SSE 静默断流、一次性网关 blip）→ 先**原地 resume** 保住上下文；
- **session/网关窗口级卡死** → **数次 resume 不成功后退化 spawn（fresh）**，真正采样新窗口，
  不再同一死窗上空转到底；
- **预算有界、可诊断**：不新增无限循环；退化动作留可观测信号；P131c / stage / workflow deadline 兜底。

## 候选选项

### 选项 ① — resume 短窗无进展升级 fresh（rev1，已否决）

对跨 spawn 的 resume 重 arm 缩短的无进展窗口（`resume_stall_s`，如 180s）；窗口内 resume 仍
「无新 turn 且 chars 静止」（沿用 P137 守卫）→ 抛 `_ResumeStallAbort` → 就地 fresh-degrade。

- **否决理由（决定性）**：短窗会把「慢但活的 resume」误判成死——resume 的 "继续" 可能直接进入
  长 tool call，期间 opencode 无 SSE 进展、chars 静止，短窗到点即误杀，**丢失一个健康 session 的
  全部上下文**。这正是 P131/P137 换来的教训：turn_stall 从 300s 提到 600s（2× 网关 request_timeout）
  就是为了不误杀慢但活的单请求。短窗违背这一保守性，不可接受。

### 选项 ② — turn-stall 即退化 spawn（清 sidecar on abort，纯 fresh）

看门狗 kill 时把 sidecar 一并清除，P131c re-spawn 必然 fresh session。

- **否决理由**：放弃「transport 级断流、session 本身健康」场景的上下文保全（20260810 Part 2
  silent-cut 恢复的延伸价值）。且对常见 session 级卡死，总墙钟被 P131c 预算（max_retries=4）封顶，
  与「先 resume」方案同长，没有速度收益，只有上下文损失。

### 选项 ③ — 降 `turn_stall_s`（600 → 更低）

- 否决：治标。只更早触发看门狗，不解决「永不退化 fresh」；600s 是 P131 实证的「2× 网关窗口」，
  再降重蹈 300s 误杀。

### 选项 ④ — 依赖 opencode 自身 resume

- 否决：P117 已实证不可行——opencode session 层无限重试 + 静默吞 1313，POST 永不返回。框架自兜。

### 选项 ⑤ — **resume 数次（满窗）→ 计数退化 spawn（rev2 决策，用户设计）**

turn-stall abort 后，P131c re-spawn 走 **sidecar 原地 resume**（续同一 session、"继续"、**满窗
600s**）；sidecar 记录 `resume_fails`（连续失败的 resume 次数），读到 `resume_fails >= N`（默认 3）
→ **清 sidecar + fresh spawn**（新 session + 全量 prompt + skill steer）。fresh 首跑卡死不计数
（下轮先 resume）。

## 决策：选 ⑤（resume 数次满窗 → 计数退化 spawn）

### 选 ⑤ 的理由

1. **§1.2 组合优先**：廉价 resume（保上下文）承担主恢复，计数退化做确定性兜底，P131c 预算做
   stop-loss——三档各司其职。
2. **零额外成本 vs 现状**：现状本就 resume 最多 3 次（每次 600s）且永不退化；⑤ 只是把最后一发
   从「注定失败的 resume」改成「fresh 采样」，**总墙钟/预算与现状完全相同**，换来的是「session 级
   卡死终于能采样到 fresh window」。
3. **不误杀慢活（关键）**：resume 用满窗 600s，不违背 P131/P137 换来的保守性——这是 ⑤ 相对 ① 的
   决定性优势。① 的短窗会误杀健康长 tool call。
4. **不丢上下文**：transport 断流场景，resume 成功即保全上下文——这是 ⑤ 相对 ② 的优势。
5. **§1.10 一致性**：退化判据是业务语义「resume 连续失败次数」（显式声明、可计数），不是
   spawn 次数/含 subprocess 机制特征代理；且复用既有 `aborted` 信号区分「stall 被杀（可退化）」
   vs「cut/非 abort 崩溃（保留 resume）」（20260810 Part 2 不动）。
6. **可诊断**：`resume_fails` 落在 sidecar（可观测），退化走既有 fresh 路径 + 明确日志/事件；
   P131c 预算/事件链原样。
7. **可扩展**：计数语义与具体网关/后端解耦；新配置 `resume_attempts` 走既有加载校验模式（§1.3）。

### 四把尺子复核（§1.2）

| 尺子 | 计数退化方案（⑤） |
|---|---|
| **可维护** | 维持既有不变式：sidecar 生命周期（写于 session 捕获、clean finish 清除、session-gone 降级）仅**扩一个字段** `resume_fails`；`aborted` → 预算兜底 halt 不变；与 P117/P131/P137 同族 |
| **可扩展** | 同类新情况自动正确归位——「resume 连续失败 N 次 → 退化 fresh」是通用语义，不为已知网关/session 打补丁（§1.12）；`resume_attempts` 可配 |
| **可诊断** | `resume_fails` 计数落盘可观测；退化动作发 `agent_resume`/`agent_degrade` 日志 + events；fresh 首跑不计数、resume 才计数，语义明确 |
| **架构合理** | 「该不该退化 fresh」是横切恢复裁决，归 backend（sidecar 是 session 恢复态的产权方）与 runner 预算（§1.10 业务语义）协作；不越层让 stage/skill 决定 |

### 关键约束（实施必须守住）

1. **满窗、不短窗**：resume 尝试用 `turn_stall_s`（600s）满窗。短窗是 ① 的否决点，⑤ 不引入。
2. **退化是「清 sidecar + fresh 全量 prompt」**：新 session 无上下文，必须带全量 stage prompt +
   skill steer（不能只发 "继续"）。
3. **计数语义精确**：
   - resume-stall abort → `resume_fails += 1`；
   - fresh 首跑 stall → **不计数**（下轮先 resume）；
   - resume 成功（session 继续推进）→ 不 trip，计数自然不增（progress 重置 `_last_chars_ts`）；
   - 退化 fresh 后写新 sidecar `resume_fails=0`（新 session 全新预算）。
4. **预算有界**：`resume_attempts`（N）< `infra_retry_max_retries`（默认 4）→ 预算内保证至少一发
   fresh（加载期校验，§1.3）。否则 N 太大时预算先耗尽、退化永远轮不到。
5. **与 silent-cut 恢复不冲突**：cut（非 abort）保留 sidecar、下轮 resume（20260810 Part 2 原样）；
   仅 stall-abort（aborted 置位）进入计数退化。二者以 §1.10 业务信号 `aborted` 区分。

### 收敛性证明（框架层 backstop 链）

- **session 级卡死**（N=3, max_retries=4）：fresh(600s)stall → resume#1(600s)stall(resume_fails=1)
  → resume#2(600s)stall(resume_fails=2) → resume#3(600s)stall(resume_fails=3) → 读 sidecar 见
  `>=3` → 清 sidecar + fresh(600s)stall → 预算耗尽 halt。**第 5 发是真正 fresh 采样**，恢复
  P131c 语义；总墙钟由预算封顶（初跑 + 4 re-spawn）。
- **transport 级断流**：fresh stall → resume#1 续上 → session 保全上下文续跑，无退化、无 abort。
- **慢但活 resume**：resume 满窗 600s，长 tool call 正常完成，不误杀（⑤ 相对 ① 的保证）。
- **cut/silent-cut**：非 abort → 保留 sidecar → 下轮 resume（Part 2 原样，不退化）。
- **全局网关挂**：所有尝试（含 fresh）都卡 → 预算耗尽 → P116 halt 带原因（换窗口修不好全局故障）。

## 不在本次范围

- P131c 退避节奏 / 累计 600s 不动；`infra_retry_max_retries` 默认 3→4（为 resume_attempts=3 让出发退化槽位，§1.3 交叉校验要求 N < max_retries）。
- 429 in-session backoff-resume 与 SDK backend 的 SSE-error resume 路径不动（判据不同）。
- 模型服务侧（网关自身超时 / fail-fast 配置）——外部基础设施，不归框架。
- 短窗 resume 探测（①）——否决，记为未来优化（若实证 resume 死窗占绝对主导且误杀可忽略）。
