# L1 问题记录 — trial-20260730 五算子外部实跑批次

> **性质**：L1 问题/需求记录。只记录客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line、不引用会话临时文件）。方案/取舍在配套 `85-trial-20260730-analysis.md`（L3）。
> **来源**：`harbor_trial-{1..5}` 五个算子（exp / apply_rotary 等）在另一台服务器上跑 `self_evolve_op` 全流水的执行日志（run.log / opencode.log / artifacts）。部署代码非最新，部分问题当时可能已修；本记录逐一对当前 `main` 复核存续性。
> **编号衔接**：既有 P 编号已到 P124，本批次续接 **P125 起**。

---

## 判据前提（贯穿本批次的两条事实）

- **turn_stall 不是总时长封顶**：日志中 `apply_rotary` 单 stage 连续跑 3689s / 39 turns 正常收尾，未被 turn-stall 打断。turn-stall 计时器 `turn_ts` 仅在收到 `message.updated role=user` 时重置，只要 agent 持续产出新 turn（哪怕总时长很长）就不触发。所谓 `no new turn for 305s > turn_stall 300s` 是**单个 turn 内静默超过 300s**（多为网关侧 5xx/429 卡住导致本 turn 不再吐帧），非任务跑太久。
- **外部网关不稳定是主因，但框架缺陷放大它**：本批次多数失败的**触发源**是 litellm 网关侧 5xx/429/超时抖动（属 §1.11 外部基础设施，框架不为其本身修）。但框架存在若干真实缺陷，会把「一次网关抖动」放大成「80 分钟死循环重跑 / 误报错因 / 假绿」——这些放大器是框架产权，是本批次要解决的对象。

---

## P125: 无产物归因把「被外部杀死」误报成「写错目录」（missing_artifact 掩盖 aborted）

### 事实

- **观测**：某算子 design 阶段 agent 被 turn-stall watchdog 杀死后，框架报「产物未在正确目录找到 / 期望写到 X 目录」这类 missing_artifact 文案，误导排查方向去查目录/路径，而真实原因是 agent 被外部控制流中断、根本没跑完。
- **根因**：agent 被 stall / hardcap / 中途 interrupt 杀死时，真实原因只存活在 `AgentResult.aborted` 字段与 `metrics["failure_reason"]`；design 子阶段的归因逻辑只认 `error_type=="infra"` 才路由到 infra 错误，否则一律落到 missing_artifact 分支——`aborted` 从未参与归因判断，被中断的 agent 因「确实没产物」而套上「写错目录」的错误文案。
- **证据**：`base_backend._build_result` 仅在 `crashed=True` 时设 `error_type`；turn-stall / hard-timeout 走的是 clean-finish 路径（`crashed=False`），只置 `aborted`，`error_type` 为空 → 归因侧看不到中断信号 → 落 missing_artifact。
- **影响范围**：所有经 agent 产出文件契约的 stage（design 各子段为主）。凡 agent 被外部杀死且未落产物者，都会被误报为目录/路径问题。

### 关联
- 与 P128（partial-halt 无 reason）同根：被外部杀死的真实原因（`aborted`/`failure_reason`）从未翻译进下游归因消费的 `error_type`/`last_error`。§1.3 加载期/产出期应留可观测信号。

---

## P126: precision baseline 提交缺 git 身份 → `git commit` rc=128 中断精度基线

### 事实

- **观测**：precision_debug 阶段建立 codegen 基线时执行裸 `git commit`，返回 rc=128，报 `Author identity unknown`（`Please tell me who you are`），精度基线提交失败。
- **根因**：`precision_debug_substages` 的 `_entry_commit_codegen` 直接调用裸 `git commit`，未提供提交身份；运行该 stage 的执行环境（外部服务器 / CI worktree）未配置全局 `user.email` / `user.name`，git 拒绝生成提交。
- **证据**：日志中该 commit 步骤 rc=128 且 stderr 含 `Author identity unknown`；同环境其余 git 只读操作（status/diff）正常，仅 commit 因缺身份失败。
- **影响范围**：任何在未配置 git 身份的环境跑 precision_debug 的算子。基线提交失败会**降级**（非阻断）「基于 diff 的精度回退/对比」链路：best_commit 不含 codegen，回滚安全性打折。

### 判定（2026-07-31，三次修正 → 定案）：条件 fallback 合成身份（env 注入，不写 config）

**判定演进**：①「不改代码」（作废——"不阻断"≠"能正常推进"）→ ②「入口 fail-fast，不伪造身份」
（作废——与 §1.7 自闭环相悖：DevKit 目标是 bare CI/容器，框架内部 commit 不该要求人工先配 git）→
③**定案：条件 fallback 合成身份**（用户 2026-07-31「我赞同你的方案，继续吧」拍板）。

**深挖后果链（无 git 身份，三判定共识的事实基础，不变）**：
1. 入口 commit 失败（rc=128）→ HEAD 不含 codegen。
2. fix/printf agent 的 `git commit`（Bash 内）**同样失败** → 修复停留工作区未提交。
3. `best_commit`（`_snapshot_best_commit` = `git rev-parse HEAD`）只能钉在陈旧 HEAD。
4. 退出 `_converge_to_best_commit` 回滚陈旧 best_commit（`git checkout` + `git clean -fd`，
   RepoGuard.rollback）：untracked 算子 → `clean -fd` **删掉 codegen + 全部 fix**（破坏性，
   op_dir 清空）；in-repo 算子 → 回退 fix，交付「有 codegen 无修复」。

**定案修法（条件 fallback 合成身份）**：git `commit` 需要的是**身份元数据**（committer/author，
盖进 commit 对象、纯本地、不校验），与 fetch/push 的**凭证**（PAT/SSH，网络鉴权）是两回事——
故可在**不碰凭证、不写 git config** 前提下，仅当 git 无法解析身份时经 `GIT_AUTHOR_*`/
`GIT_COMMITTER_*` **环境变量**注入一个明显合成的框架身份
（`AscendC-DevKit precision_debug <devkit@ascendc-devkit.local>`）。
- **条件**：先 probe `git var GIT_COMMITTER_IDENT`（复现 commit 的身份解析）；rc==0（能解析）→
  不注入，保住真实开发者身份（env 优先级高于 config）；rc!=0（bare 容器）→ 才注入。判据 =
  「注入 ⟺ commit 否则会因缺身份失败」，无误伤。
- **两处注入**：入口 commit（`_entry_commit_codegen` 的 add/commit `env=`）+ agent Bash commit
  （opencode `_build_serve_env` 的 serve env）。
- **根因消解**：commit 成功 → best_commit 正确前进 → converge 安全前提恢复，故**不加**防御性
  converge 门（症状随根因消失）。
- **满足**：§1.7 自闭环（bare 环境框架自给自足）+ §1.13（不碰 golden/凭证/用户 config）+
  git_safety（绝不写 git config，仅子进程树 env 作用域）。
- **对「入口 fail-fast」的取代理由**：fail-fast 唯一动机（挡破坏性 converge）在本方案由「commit
  成功」从根因消解，无需 halt；且 fail-fast 要求人工配环境，违 §1.7。
- **状态**：**已实施 + 全绿**（2026-07-31）。实施详见 `85-trial-20260730-p126-impl.md`（L4）。
  测试：`test_p126_git_identity_fallback`（6，含端到端 bare 仓 commit）+ opencode_backend（65）+
  repo_guard/precision_debug（295）回归全通过。

---

## P127: ForkJoin resume 无分支内 checkpoint → 已完成 split 被重复重跑 6+ 次

### 事实

- **观测**：ForkJoin 结构（如多 shard 并行 codegen/eval）在 resume 时，已成功完成的某个 split 分支被反复重新执行（日志中同一 split 出现 6+ 次重跑），大量重复消耗 token 与时间。
- **根因**：ForkJoin 分支内部节点的进度不落盘——分支执行时 `on_state_progress=None`（分支级 progress 不持久化）；join 合并只保留分支级 `node_status`，分支**内部**已完成节点的状态不进 checkpoint；resume 时 pending 检测停留在分支级粒度，无法识别「分支内前 N 个节点已完成」，于是整条分支从头重跑。
- **证据**：`graph_executor` 分支执行传 `on_state_progress=None`；`node_forkjoin.merge_forkjoin` 折叠 `provides` 但**不折叠** `node_status`；resume pending 检测为分支级。三处叠加 → 分支内 checkpoint 全缺失。
- **影响范围**：所有含 ForkJoin 的流水（多 shard / 多 split 并行）。网关抖动导致分支中途失败、外部调度器 resume 时，已完成的昂贵子步骤全部白跑重来——是把「一次抖动」放大成「多轮重跑死循环」的最主要放大器。

### 关联
- 是本批次最高优先放大器：外部网关抖动（§1.11）本不可避免，但分支内无 checkpoint 使每次 resume 都全量重算，把偶发抖动变成 80 分钟量级的重复消耗。

### 判定（2026-07-31，已实施 + 全绿）：Fix A — join 折叠 ran 分支内部 node_status 子键

- **修法**：`_execute_forkjoin` 在重建 `ns`（分支级 node_status）时，除了打分支级 completed/failed 外，额外把每个 ran 分支返回态的**内部** node_status 子键（前缀匹配 `分支路径 + "/"`）折进 `ns`。分支 `_execute_node` 返回的 key 已是相对 join 路径的全限定名，前缀匹配恰好只带该分支子树。
- **根因消解**：`_execute_node`（:209）resume 时对**任意**节点（含内部）都查 `node_status.get(path)=="completed"` 决定是否跳过；此前内部完成态在 join 处被丢弃，故 resume 重跑整条分支。折叠后 `.../T1/split=completed` 进 checkpoint → resume 精确跳过已完成内部节点、只重跑失败的那个。
- **不改并发/取消**（那是 P128 的独立职责）；本 Fix 只补 checkpoint 粒度，纯增量、无回归面。
- **四尺子**：可维护（复用既有 `_path` + 前缀语义，与分支级打标同处）；可扩展（任意深度嵌套分支子键自动归位，非按已知结构特判）；可诊断（内部完成态可观测，resume 决策有据）；架构合理（落在 join 折叠职责点，与 merge_forkjoin 只折 provides 互补）。
- **状态**：已实施 + 全绿（2026-07-31）。测试 `test_resume_skips_completed_inner_node_of_failed_branch`（先证 pre-fix 缺 `tiling/T1/A` 键、后证 resume 只重跑 B）；orchestration UT 全量 1787 passed。

---

## P128: ForkJoin 一分支 halt 后同级分支不取消 → 兄弟分支空跑到底

### 事实

- **观测**：ForkJoin 某分支已判定 halt（失败/需人工）后，同级其它分支不被取消，继续跑到各自结束，浪费算力与 token。
- **根因**：`graph_executor` 的 ForkJoin 用 `pool.map` 等待全部分支完成（wait-all），无跨分支取消机制；`ExecContext` 中已存在 `CancelToken`（threading.Event）但**未接入** GraphExecutor 的分支执行，一分支失败无法通知兄弟分支提前退出。
- **证据**：`exec_context.CancelToken` 定义存在但 GraphExecutor 未 wire；分支调度为 `pool.map` 全等待，无 `as_completed` + 早停。
- **影响范围**：所有 ForkJoin 流水。一分支确定失败后，兄弟分支的剩余执行都是确定无用的空烧。

### 关联
- 与 P127 同处 ForkJoin 执行器；P127 是「失败后重跑浪费」，P128 是「失败后同批浪费」。

### 判定（2026-07-31，已实施 + 全绿）：Approach B — 共享 CancelToken 经 ctx 接线，协作式取消

- **修法**：`_execute_forkjoin` 建**一个** `CancelToken`；`pool.map`（wait-all）→ `submit` + `as_completed`。每个 branch_exec 挂 `_cancel_token`；`_execute_atomic` 当 token 存在时构造最小 `ExecContext(cancel_flag=token)` 传 `run_stage(..., ctx=)`（已核实 `_run_stage_body` 只读 `cancel_flag`+两 deadline，None deadline 回落自身逻辑，其余字段不读→token-only ctx 无副作用）。`as_completed` 每完成一分支：若其 outcome 为 failed/terminal（**业务语义判据**，§1.10）→ `token.cancel()`。
- **两个消费点**：`_run` 入口 check token（未起分支直接跳过、返回 None → 保持 pending）；runner 迭代边界 `_is_cancelled()`（loop-top）→ 在跑分支下一迭代边界 raise `RunnerCancelledError`，`_run` 在**分支边界吞掉**（仅当 token 已 cancel，否则重抛→可诊断不静默）→ 返回 None。
- **cancelled 分支处理**：None 态既非 ok 非 failed → 不进 merge、不折 P127 子键、`ns` 重建**跳过**（不标 completed）→ 保持 pending，resume 重跑（其已完成内部 checkpoint 若有由 P127 折叠续跑）。
- **serial 路径**（`concurrency=="1"`）：某分支 failed 后 `cancel()` → 后续 `_run` 短路成 None，不再启。
- **诚实局限（写进档）**：① **协作式**——正在飞行的单次 agent spawn（一 iteration 内分钟级 turn）**不硬杀**，取消在**下一迭代边界**生效；省的是"确定失败后兄弟继续起的后续 iteration"（正是 28min 空烧源），非硬中断当前 turn。② **嵌套 forkjoin**：内层覆盖 `_cancel_token`，外层取消不穿透进内层分支 atomic；当前无嵌套 forkjoin 用例（tiling 分支是 SequentialGroup of atomics），记为已知局限不现在处理。
- **四尺子**：可维护（复用 purpose-built CancelToken/ExecContext，非新造机制，非 forkjoin 路径 `ctx=None` 行为不变）；可扩展（任意 forkjoin 自动生效，无算子/结构特判）；可诊断（取消经 Logger 留信号，`RunnerCancelledError` 非 token 来源重抛不静默）；架构合理（判据在 join 编排层业务语义"分支 failed"，consumer 在 runner 迭代边界）。
- **状态**：已实施 + 全绿（2026-07-31，用户「按你的推荐来做」拍板 Approach B）。测试 `test_forkjoin_cancels_siblings_on_branch_halt`（fast 分支瞬 halt + slow 兄弟带 iteration 计数，pre-fix 兄弟跑满 12 iter、post-fix <12 且用例 0.24s 收尾）；forkjoin/tiling_forkjoin 32 passed。

---

## P129: partial-halt 无 reason 字符串 → halt 原因丢失

### 事实

- **观测**：stage 以 partial（部分分支失败）方式 halt 时，最终 halt 事件/报告缺少可读的失败原因字符串，只见「halt」不见「为何 halt」。
- **根因**：`runner` 组装 stage_status 时，`own_error` 只从**同 stage** 的 `last_error` 取；partial 情况下失败信息在各 agent 的 `failure_reason`/`aborted`，从不回填进 `last_error`；halt reason 由 `last_error` 派生 → partial 场景 reason 为空。
- **证据**：`runner` 中 own_error 仅来自 same-stage last_error；partial 分支不 backfill agent 的 failure_reason/aborted 到 last_error；`graph_executor` halt reason 从 last_error 取。
- **影响范围**：所有可能 partial halt 的 ForkJoin stage。halt 后无诊断线索，排查只能翻原始日志。

### 关联
- 与 P125 同根：agent 侧真实失败原因（aborted/failure_reason）未翻译进下游消费的 last_error。

---

## P130: turn_stall 计时对不同 stage 语义不对称（重推理 stage 易被误杀）

### 事实

- **观测**：统一 `turn_stall_s=300` 对所有 stage 一刀切。轻交互 stage 300s 足够，但重推理 stage（单 turn 内需长时间思考/大上下文生成）正常也可能单 turn 静默超 300s，被 watchdog 误判为卡死杀掉。
- **根因**：turn-stall 阈值是全局单值，不区分 stage 的推理负载语义；框架无「本 stage 属重推理、单 turn 允许更长静默」的业务语义声明。
- **证据**：`runtime_config` 中 `_DEFAULT_OPENCODE_TURN_STALL_S=300.0` 为全局默认；dispatcher 三个 dispatch 入口均传同一 turn_stall_s，无 per-stage 分流。
- **影响范围**：重推理 stage（design 综合、codegen 大文件生成等）。网关正常但本 turn 计算耗时长时，会被误杀。

### 关联
- §1.10：横切控制流（turn-stall）该不该作用应由**业务语义显式声明**（stage 声明重推理），不用全局单阈值代理。与 P131/P132 同属超时配置族。

### 判定（2026-07-31，用户拍板）：关闭 —— 无复现 + 已被 P131 覆盖，不做预留通道

- **无复现**：五个 trial 全部 turn_stall abort 均为**网关持续吐 429/503 错误帧**导致的空等（外因，§1.11），**无一例**是「重推理 stage 正常单轮静默超阈值被误杀」。找不到任何 stage 真的需要 >600s 静默轮。
- **已被 P131 覆盖**：turn_stall 300→600 已解耦网关 timeout(300)；跨-run 退避 resume 已回收 turn_stall abort（重采样新网关窗口）。这次**实际发生**的问题已闭合。
- **不为未发生的问题做预留通道**（工程原则）：原推荐 C+B 会新增「重推理」声明通道（`heavy_reasoning` stage 属性 + per-stage config + 加载期校验），但今天**零 stage 需要**、**零复现**——那是为尚未发生的问题铺管线，违背本原则，故不落地（连休眠机制也不加）。
- **§1.10 不构成现在落地的理由**：§1.10 反代理要求存在**语义相反、共享机制特征、必有一类被静默误判**的现实二分；本条「重推理被误杀」一侧目前是空集（全局 600 无观测误判），不构成该二分。将来真观测到某重 stage 被误杀，再按 §1.10 加声明（一行 stage 标志或一个 config 键，无需现在铺管线）。
- **状态**：关闭（won't-fix / 已被 P131 覆盖）。不新增任何代码或配置。

---

## P131: turn_stall_s(300) 与网关 request_timeout(300) 同值耦合 → 一次网关超时即触发 stall

### 事实

- **观测**：turn-stall 阈值 300s 与 litellm 网关侧单请求超时 300s 恰好相等。网关侧一次请求打满 300s 超时（返回慢或 5xx），本 turn 正好静默满 300s，watchdog 立即触发 turn-stall，二者同时到点、相互叠加。
- **根因**：两个独立系统的超时值巧合相等，无安全裕度。turn-stall 本应容纳「网关重试若干次」的时间窗，但等于单次网关超时意味着「网关刚超时一次、还没来得及重试」就被框架判 stall。
- **证据**：`runtime_config` turn_stall_s=300；网关 request_timeout 亦为 300（部署配置）。日志中 turn-stall 触发点与网关请求超时点高度重合。
- **证据（trial-4 opencode.log 实证，2026-07-31 补）**：每条 stall 前的 `message="stream error"` 均为 `litellm.Timeout: APITimeoutError - Request timed out ... timeout: 300.0. Model Group=glm-5.2-thinking`——即**网关 litellm 等 GLM 后端的单请求超时正是 300.0**。turn-stall 触发文案 `no new turn for 30Xs > turn_stall 300s — last turn N`**均不带 block_types**（activity 无 `: tool:xxx`），证明 stall 时 agent 不在长 tool 调用中，而是**卡在等这一个 completion 返回**。因此「turn>300s」的触发源是 **glm-5.2-thinking 单次推理 + 后端过载**；框架 turn_stall 也配 300s，故在网关刚 timeout 抛错的**同一刻**框架判 stall 并 kill，一次重试窗都不留。
- **证据（五算子全量复核，2026-07-31 订正——推翻"抬阈值能跑完"）**：五个 trial **keepalive/idle（SSE 真静默）abort = 0 次**，全部是 turn_stall abort；同期 trial-5 有 `429×174 / 503×65 / ServiceUnavailable×74 / APITimeoutError×25 / RateLimit×24 / stream-error×80`。合起来证明：**连接没死、也不是 thinking 慢——是网关在整个 stall 窗口内持续吐 429/503 错误帧（错误帧维持 SSE 活性使 keepalive 不触发），但从无一帧是"完成的 turn"**，故 turn_stall 一路空等到点。外层 harbor 把阈值 300→900→1800 逐次抬高（每次 resume 注入，日志可见），但 **trial-5 实证 `no new turn for 1803s > turn_stall 1800s — last turn 20` 仍 abort（且 900s 档亦 abort）**，五算子最终无一交付（report.json 全 `status:ok` 是 P134 假绿本身，不可当交付证据）。**结论订正**：网关持续拒绝时，抬高阈值只是**更久的空等**，`阈值 > 网关 timeout` 并不能"跑完"；真正需要的是"尽早判死 → 标 infra → 带退避 resume 采样新窗口"，而非把 turn_stall 往 900/1800 抬。当前环境≠当时网关状态，**无法重放印证**，以上均为原始运行日志的直接读取。
- **影响范围**：所有走 opencode + litellm 网关的 stage。网关单次超时不留重试窗即被框架终结；持续过载时抬阈值无效、只是空等更久。

### 关联
- 与 P130/P132 同为超时配置族；此条是「阈值选值」问题，P130 是「阈值是否该分 stage」问题。
- **已解决（2026-07-31）**：方向 A（框架内跨-run 退避 resume，非 harbor 阈值抬高）。turn_stall 300→600 解耦；
  in-session 软重试集扩到 503/ServiceUnavailable/APITimeout；runner 新增 cross-run 退避 resume（`aborted`
  瞬态 infra → 有界退避重采样新网关窗口，耗尽落回 P116）。实施详见 `85-trial-20260730-impl.md`。

---

## P132: message_timeout(3600) 硬封顶会杀掉仍在推进的重 stage

### 事实

- **观测**：`message_timeout=3600s` 是永不重置的硬封顶（deadline）。重 stage 即便**持续正常产出 turn**（未 stall、网关健康），只要总时长跨过 3600s 也被硬杀。
- **根因**：deadline 计时器不随任何事件重置，是「无论进展与否」的总时长闸。对确实需要 >1h 的重 stage（如 apply_rotary 已见 3689s），该闸与「正常推进」语义冲突——它杀的是进展中的任务，不是卡死的任务。
- **证据**：`opencode_backend` 中 `eff_msg_timeout` 为固定 deadline，不随 SSE 帧或 turn 重置；`apply_rotary` 实测 3689s 收尾（>3600），若 deadline 生效即会被误杀。
- **影响范围**：所有单次执行可能 >1h 的重 stage。与 turn-stall 语义正交：turn-stall 杀「卡住的」，deadline 杀「跑得久的」，后者对进展中的任务是误杀。

### 关联
- 与 P130/P131 同族。turn-stall（杀卡死）已足够守护「真卡死」，deadline 额外杀「跑得久但健康」的语义可疑。
- **已解决（2026-07-31）**：message_timeout 默认 3600→14400（4h runaway 兜底，不再逐-turn 停滞门误杀健康重
  stage）；与 P131 同批落地。实施详见 `85-trial-20260730-impl.md`。

---

## P133: e2e_self_evolve.sh banner 硬编码算子名

### 事实

- **观测**：`e2e_self_evolve.sh` 的 banner 标题硬编码为某具体算子名（`moe_re_routing operator`），即使经 env 覆盖 OP_DIR/GOLDEN 跑别的算子，banner 仍显示旧算子名，误导。
- **根因**：banner 标题写死字面量，未从 OP_DIR/GOLDEN 变量派生。
- **证据**：脚本 banner 行为常量字符串，而同脚本 OP_DIR/GOLDEN/GOLDEN_ENTRY 均可 env 覆盖——数据与展示不一致。
- **影响范围**：所有用该脚本跑非 moe_re_routing 算子的场景（纯展示误导，不影响执行结果）。

### 关联
- §1.12：脚本展示层耦合具体算子名，属实例数据泄漏进流程脚手架。

### 判定（2026-07-31，已实施 + 全绿）：banner 从 OP_DIR 派生

- **修法**：`OP_NAME="$(basename "$OP_DIR")"`（在 OP_DIR 定义后立即派生），banner 标题 `moe_re_routing operator` → `$OP_NAME operator`。OP_DIR 是主覆盖点、也是 codegen 实际生成源码的目录，`basename` 恰是算子名单一真相源。
- **根因消解**：banner 不再写死字面量，env 覆盖 OP_DIR 跑别的算子时 banner 随之正确，展示与执行一致。头部注释仍保留 moe_re_routing 作为「默认场景文档」（描述默认值，非运行期展示，不构成自相矛盾）。
- **验证**：`bash -n` 语法通过；默认 → `moe_re_routing operator`，`OP_DIR=.../ops/exp` → `exp operator`。纯展示层，无执行路径改动。
- **状态**：已实施 + 全绿（2026-07-31）。

---

## P134: report.json 假绿 — stage_complete 无条件 status=ok，与 node_status blocked 不一致

### 事实

- **观测**：最终 `report.json` 把某个实际 blocked/halt 的 stage 报成 `status=ok`，报告与真实执行状态矛盾（假绿）。
- **根因**：`Report.generate` 只读 `events.jsonl`，见到 `stage_complete` 事件即无条件置 `status="ok"`；而 `stage_complete` 事件本身**不带 status 字段**，report 无从区分「正常完成」与「halt 后也发了 complete」；真实状态在 `node_status`（blocked），report 不消费它。
- **证据**：`event.py` 中 `stage_complete` 事件无 status 字段；`report.py` 的 generate 对 stage_complete 一律 status=ok；node_status 权威状态未被 report 覆盖。
- **影响范围**：所有 halt/blocked 收尾的算子。report 假绿会让「批跑总览」误判为成功，掩盖真实失败。

### 关联
- §2.9：report 作为下游消费者应忠实反映权威状态（node_status），不该用弱信号（stage_complete 存在与否）自行判绿。

---

## P135: anchor gate 对 TilingKey 覆盖盲区 — TilingKey 有两个独立作者

### 事实

- **观测**：anchor 一致性门（AnchorConsistencyStage）对 TilingKey 存在覆盖盲区，TilingKey 的取值一致性未被有效守护。
- **根因**：TilingKey 有**两个独立作者**——`template_division.json`（template_division schema 的 `templates[].tiling_key` 是权威）与 integrate 阶段（integrate SKILL.md 再次自行 author routing/tiling_key）。IntegrateStage 的 input_contract 不要求 template_division 作为输入，integrate 重新编写 routing，二者可分叉；`_extract_shared_summary` 虽从 tiling 段提取 `tiling_key`，但 tiling 段从不写该字段（dead field），提取恒空。
- **证据**：`template_division.json` schema `templates[].tiling_key` 为权威；IntegrateStage input_contract 无 template_division 要求；integrate SKILL.md 再 author routing；`design_substages._extract_shared_summary` 提取的 tiling_key 是 dead field（tiling 段不产该字段）；AnchorConsistencyStage 在 IntegrateStage 之前运行。
- **影响范围**：所有需要 TilingKey routing 的算子（多 template 分支）。两作者分叉时 codegen 拿到不一致的 tiling_key → 入图/编译错配。

### 关联
- §2.9「构造性保证优先于检查门」：integrate 的 tiling_key 本应由上游 template_division 派生（下游消费上游既定前提），而非独立再 author；当前是「独立双作者 + 提取 dead field」的反模式。

### 判定（2026-07-31，已实施 + 全绿）：方案 B —— template_division 单作者 + codegen 直读 + 删死字段

- **修法（B）**：确立 `template_division.json` 为 TilingKey 路由（`templates[].tiling_key` + `route_condition`）**唯一权威作者**，消除第二作者：
  1. **删死字段**：`design_substages._extract_shared_summary` 的提取白名单去掉 `"tiling_key"`（tiling 段从不写该字段，提取恒空的 dead field）；`_upstream_inputs` 注释同步订正。
  2. **integrate 不碰路由**：`ascendc-op-design-integrate/SKILL.md` 删「TilingKey 路由完整性验证」执行步骤 + 自检项，改为显式声明「路由不归 integrate，唯一作者是 template_division，不重新 author/验证」；其 `references/integration_schema.md` 删 §4「TilingKey 路由完整性」输出段。
  3. **codegen 直读单作者**：`ascendc-op-dev-coding/SKILL.md` 把 design_spec 的幻象 `tiling_key_router` 字段去除（改标「路由不在此」），`template_division.json` 从「可选」升为「多模板必需 + TilingKey 路由唯一权威源」，codegen 据 `templates[].tiling_key`+`route_condition` 生成分发。codegen.py 已在 `state.template_division` 非空时投递该产物到 working_dir（无需新增管线）。
  4. **validate 门不回检**：`ascendc-op-design-validate/SKILL.md` `--stage integration` 自检删「TilingKey 路由完整性验证通过」（保留「共享 TilingData 字段检查」——那是 integrate 自身产物的合法跨段对齐），改为声明路由完整性归 template_division 自检、本门不越界回检（§2.9 门不越界查上游产物）。
- **根因消解**：路由从「双作者可分叉 + dead 提取」变为「单作者 template_division + 下游 codegen 忠实消费」，一致性由「单作者 + 构造性消费」保证，无需 anchor/validate 跨产物门守护（§2.9 构造性保证优先于检查门）。
- **四尺子**：可维护（消除幻象字段/重复作者，与「上游派生、下游消费」哲学一致）；可扩展（任意多模板算子路由自动归位 template_division，无算子特判）；可诊断（路由单一真相源，冲突面结构性消除，无需门事后发现）；架构合理（作者归 template_division 决策点、消费归 codegen，门不越界）。
- **作用域边界（诚实记档）**：本修覆盖 self_evolve_op 设计流水（template_division→integrate→codegen→validate）。交互/增量开发 + regbase-coding 簇（`ascendc-dev-s2-analysis` / `ascendc-dev` / `ascendc-dev-interactive` / `coding-regbase phase-c`）仍留有 design_spec `tiling_key_router` 表述——那是**另一条流水**、design_spec 授权模型未在本批次分析，不属 P135 self_evolve 范围，未改动（避免跨流水 scope creep）。
- **状态**：已实施 + 全绿（2026-07-31，用户拍板「B(推荐)」）。测试：`test_extract_shared_summary_filters_keys`（TDD 断言 tiling_key 不再被提取）；orchestration UT 全量 **1788 passed**（含 validate_gate_scope / validate_skill_scope_contract 未回归）。

---

## P136（算子级，非框架代码）: exp 精度 18/20 fail — fp32 计算 exp(2/3·x)

### 事实

- **观测**：exp 算子精度 18/20 case fail。kernel 中 Compute 用 `AscendC::Exp` 限定名（命名冲突已自愈），但 fp32 路径实际计算的是 `exp(2/3·x)` 而非 `exp(x)`，疑似 `log2(e)` 常量写错（2/3 ≈ 0.667 vs log2(e)≈1.4427 的错误换底）。
- **根因**：属算子实现层的精度缺陷（常量/换底错误），是 precision_debug 阶段该闭合的算子正确性问题，**不是框架代码缺陷**。golden 是权威（§1.13），工程实现未忠实对齐 golden 的 exp 语义。
- **证据**：`app_artifacts` 中 exp kernel 的 Compute 段 fp32 分支含 2/3 系数；golden exp 无此系数。
- **影响范围**：仅 exp 该次实现。记录在此仅为批次完整性，解决归 precision_debug 流程 / 算子重跑，不进框架修改清单。

### 关联
- §1.13：golden 永远权威，工程只忠实读取/对齐/传递，不得用工程逻辑修正/猜测。本条是「未忠实对齐」的算子级实例，非框架结构问题。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-31 | 初版：记录 P125-P136（trial-20260730 五算子外部实跑批次），来自 harbor_trial-{1..5} 执行日志复核。方案见 `85-trial-20260730-analysis.md` |
