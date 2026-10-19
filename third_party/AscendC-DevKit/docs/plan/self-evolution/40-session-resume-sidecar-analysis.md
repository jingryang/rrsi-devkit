# 40 — 提案#1：session_id 持久化 + 跨 run resume + 降级（sidecar 方案）（L3 方案分析）

> 工作线：self-evolution（六算子批跑收口）
> 状态：**已拍板冻结**（2026-07-12）
> 关联 L4：`40-session-resume-sidecar-impl.md`；L1：`batch-sixops-runlog.md` 问题 7
> 上游 plan：`/root/.claude/plans/lovely-painting-aurora.md` 方案二
> 关联既有：`19-resume-hardkill-analysis.md` / `20-resume-hardkill-impl.md`（P29，node_status snapshot flush——**互补、不重叠**）

## 问题（L1 事实引用）

429（Weekly/Monthly Limit，软限流非硬墙）不破坏 session，但当前 `session_id` 仅在单次 spawn 内为 "Content block not found" 瞬态错误捕获复用（`sdk_backend.py`），**不持久化**。手动 resume 时 `_resume_breaker_reset` 清 infra last_error + fresh 重跑整个 stage（`dispatcher.py`），丢掉 crashed session 的推理记忆 → 浪费 token。本次 plan 期间两个 Explore agent 被 429 打断，实证了该场景的现实性。

## 选项

### A. session_id 进 State（snapshot 持久化）❌ 不选
- 落点：`State.crashed_session_id`，随 `to_snapshot` asdict 持久化，`from_snapshot` 恢复；codegen `transition` crash 分支设、ok 分支清；codegen `actions` 检测它发 resume spawn。
- **被否决的两个理由（用户驱动）**：
  1. **session_id 是「正常信息」不是「错误信息」**：它在 spawn 后已获取并输出到日志，是正常产物。把它放在 State 里挨着 `last_error`（crash 分支设）语义错位——把正常信息和错误状态混在一起。
  2. **进程被外部强杀（SIGKILL/OOM）时无 transition 可设 State 字段**：hard-kill 不跑任何 Python except/finally/transition，只有**已在盘上的状态**幸存。State 字段在 `transition` 设 → mid-spawn hard-kill 时 transition 没跑 → session_id 没进 State → resume 拿不到。即 State 字段**覆盖不了 hard-kill**（用户明确要求考虑的场景）。

### B. sidecar 文件（`<run>/agents/<agent>.session.json`）✅ 选定
- 落点：由 `SDKBackend._spawn` 在**捕获 session_id 当下**写盘（mid-spawn，crash/kill 前）；clean finish 删；codegen `actions` 入口读 sidecar → 发 resume spawn；backend 收到 resume_session_id 用 resume options，session 过期则降级 fresh。
- **解决 A 的两个否决点**：
  1. session_id 不进 State——sidecar 是 backend 管的磁盘态，与 State 的错误/进度状态分离，语义干净。
  2. **覆盖 hard-kill**：sidecar 在 session_id 捕获当下（crash/kill 之前的 mid-spawn 时刻）已写盘 → SIGKILL 也幸存（无 transition 也能 resume）。

## 决策

**选 B（sidecar）**。理由（§1.2 四把尺子）：
- **可维护**：session_id 生命周期全归 backend（write/read/clear），不混入 State；路径单一权威源 `infra/workspace.session_sidecar_path()`（L7，L3 stage + L5 backend 共用，不漂移）。
- **可扩展**：任何 agent spawn 的 session_id 自动持久化，不需逐 stage 配置。
- **可诊断**：sidecar 写/清有 `Logger.action`/`Logger.warn` 信号；session 过期降级有 warn。
- **架构合理**：session_id 是 backend/spawn 层概念（SDK session），落 backend 管的 run-dir（与 transcript 同级），不越层到 State（node 状态层）。

## 与 P29（19/20-resume-hardkill）的关系——互补、不重叠

| 维度 | P29（19/20） | 提案#1（本方案） |
|---|---|---|
| 持久化什么 | `node_status`（哪些节点已完成） | `session_id`（被中断节点内的 SDK session） |
| 落点 | `state_snapshot.json`（逐节点原子 flush） | `<run>/agents/<agent>.session.json`（sidecar） |
| 解决什么 | resume 知道**跳过哪些已完成节点** | 重入被中断节点时**续接 SDK session 推理记忆** |
| 写盘时机 | `_execute_node` 末尾（节点完成） | `_spawn` 捕获 session_id 当下（mid-spawn） |
| resume 权威 | snapshot（aa472e3：node_status sole authority） | sidecar（session_id sole authority） |

**互补**：hard-kill mid-codegen-spawn 时——P29 snapshot 有该节点未完成标记 → resume 重跑该节点；sidecar 有 session_id → 重跑节点的 codegen spawn 续接 SDK session（而非 fresh 丢推理记忆）。各一条通路、各管一责（§2.5 不冲突，**无第二 session_id 路径**——P29 不碰 session_id，本方案不碰 node_status）。

## 降级语义

- resume 门票**一次性**：codegen `actions` 读 sidecar 发 resume spawn 后，无论成败 backend 都清 sidecar（clean finish 清 / session-gone 降级清 / crash salvage 后 sidecar 仍在但下次 actions 再读——由 transition 不介入保证）。
- **session 过期降级**：`SDKBackend._spawn` 收到 `resume_session_id`，首次 query 报 session gone/expired（`_is_session_gone` marker：`"session not found"|"session expired"|"no such session"|"session does not exist"|"could not resume"|"unable to resume session"`）→ log warn + 清 resume + 降级 fresh spawn（原 prompt + options）。降级内聚在 backend，stage 不感知、不烧断路器（`attempt==1` guard，只首次降级）。

## 不向后兼容（§1.4）

- 新增 `SpawnAgent.resume_session_id`、`AgentBackend.spawn(resume_session_id=...)`——protocol 扩展，所有 fake backend 同步加 kwarg（29 处），不留旧签名包装。
- sidecar 是新机制，无旧路径需删（§2.5：唯一通路，无新旧并存）。
