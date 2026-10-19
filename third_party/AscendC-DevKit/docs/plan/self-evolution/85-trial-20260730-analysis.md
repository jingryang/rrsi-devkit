# L3 方案分析 — trial-20260730 五算子批次缺陷修复

> **性质**：L3 方案分析。记录每个问题有哪些选项、推荐哪个、为什么（四把尺子：可维护 / 可扩展 / 可诊断 / 架构合理）。
> **配套 L1**：`85-trial-20260730-problems.md`（P125-P136 客观事实）。
> **状态**：**待评审**。用户明确要求「查证根因 + 出方案评审通过后再实施」——本文档是评审对象，**批准前不改任何代码**。
> **实施记录**：批准后另起 `85-trial-20260730-impl.md`（L4）。

---

## 总览：优先级与主题分组

| P | 严重度 | 主题 | 是否放大器 | 推荐方案 |
|---|---|---|---|---|
| P127 | **高** | ForkJoin resume 无分支内 checkpoint | ★ 最强放大器 | C（join 折内部 node_status + 硬杀路径分片 flush）|
| P125 | **高** | 无产物归因误报「写错目录」 | 掩盖真因 | A（归因前查 aborted）|
| P128 | 中 | ForkJoin 兄弟分支不取消 | 空烧放大器 | A（CancelToken 接线 + as_completed 早停）|
| P129 | 中 | partial-halt 无 reason | 掩盖真因 | A（从 agent_result 合成 last_error）|
| P126 | 中 | precision baseline commit 缺 git 身份 | 阻断 | A（commit 内联 `-c` 身份，不改用户配置）|
| P130 | 中 | turn_stall 对 stage 语义不对称 | 误杀 | ~~C+B~~→**关闭**（无复现+已被 P131 覆盖；不为未发生问题做预留通道）|
| P131 | 中 | turn_stall(300)=网关 timeout(300) 耦合 | 误杀 | ~~A(抬到900)~~→**A'**(克制阈值400–600+判infra+退避resume;抬阈值已被日志推翻)|
| P132 | 中 | message_timeout 3600 硬杀健康重 stage | 误杀 | B+C（默认关闭 deadline，靠 turn-stall + per-stage 覆盖）|
| P134 | 中 | report.json 假绿 | 掩盖真因 | A+B（stage_complete 带 status + report 用 node_status 覆盖）|
| P135 | 中 | anchor gate TilingKey 双作者盲区 | 一致性 | **B**（codegen 直读 template_division 单作者 + integrate 不碰路由 + 删死字段）→**已实施全绿** |
| P133 | 低 | e2e 脚本 banner 硬编码算子名 | 展示误导 | 直接从变量派生 |
| P136 | — | exp 精度（算子级非框架）| — | 不进框架清单，归 precision_debug |

**跨缺陷共同根因（评审重点）**：P125 / P129 / P134 是**同一种病**——「被外部控制流杀死 / halt 的真实原因，只存活在 `AgentResult.aborted` / `metrics[failure_reason]` / `node_status`，从未翻译进下游归因消费的 `error_type` / `last_error` / report status」。三者可共用一条「把权威失败信号向下游翻译」的修复思路，建议合并评审、分别落地。

---

## P127（高）: ForkJoin resume 无分支内 checkpoint

### 根因回顾
分支执行 `on_state_progress=None`（分支内进度不落盘）+ join 只留分支级 node_status（丢子键）+ resume pending 检测分支级 → 已完成 split 整条重跑。sigmoid split 重跑 6+ 次 → 80min 死循环。这是把「网关偶发抖动」放大成「每次 resume 全量重算」的最强放大器。

### 候选方案

**A — join 合并折叠失败分支的内部 node_status 子键（主修）**
- 做法：`merge_forkjoin` 除折叠 `provides` 外，把各分支内部已完成节点的 `node_status` 子键一并折进合并结果，写回 checkpoint；resume pending 检测能看到「分支内前 N 节点 completed」而跳过。
- 可维护 ✓：与现有 node_status 机制同构，只是补齐折叠维度。可扩展 ✓：任意深度 ForkJoin 自动受益。可诊断 ✓：resume 时能精确显示跳过了哪些子节点。架构合理 ✓：修在 join 合并这个职责正确的点。
- 风险：需确认分支内节点 key 命名在合并后不冲突（split 索引需进 key）。

**B — 分支执行传真实 on_state_progress + 硬杀路径分片 flush（兜硬杀）**
- 做法：分支执行不再传 None，接入带锁的分片 flush，硬杀（SIGKILL/hardcap）也能把已完成子节点落盘。
- 单独 B 的问题：硬杀时 flush 时机不保证；且与 A 有重叠（A 在 join 已折叠，B 在分支内实时 flush）。

**推荐：C = A（主修）+ 窄化 B（仅硬杀路径的锁保护分片 flush）**
- A 覆盖正常/软失败 resume（绝大多数）；B 只补 A 覆盖不到的硬杀窗口。四尺子最平衡：A 保住不变式（node_status 唯一权威），B 做 last resort 防硬杀丢进度，二者不重复职责。

### 待评审确认点
- 分支内节点 key 是否已含 split 索引（决定 A 折叠是否会撞 key）——实施前需读 `node_forkjoin` / `graph_executor` 确认 key 生成规则。

---

## P125（高）: 无产物归因误报「写错目录」

### 根因回顾
agent 被 stall/hardcap/interrupt 杀死时真因在 `AgentResult.aborted` / `failure_reason`；design 子阶段归因只认 `error_type=="infra"`，否则落 missing_artifact「写错目录」文案。`aborted` 从不参与归因。

### 候选方案

**A — 归因前先查 `aborted`，命中则报 `_aborted_no_product_error`（推荐）**
- 做法：design 子阶段归因分支入口，先判 `agent_result.aborted`（stall/hard_timeout/interrupt）是否置位；置位则走新增的 `_aborted_no_product_error`（文案如「agent 被<原因>中断，未产出产物」），不再落 missing_artifact。
- 可维护 ✓：新增一条前置判断，不动既有 missing_artifact 语义。可扩展 ✓：任何新的中断类型只要置 `aborted` 即自动正确归位（§1.10 业务语义驱动，不认 stage 身份）。可诊断 ✓：把被掩盖的真因显式暴露。架构合理 ✓：归因逻辑消费 agent 已产出的权威信号，而非猜目录。
- 与 P129/P134 合流：三者共用「aborted/failure_reason 向下游翻译」思路，可在同一 PR 里以一致方式落地。

**B — 让 base_backend 在 stall/hardcap 也设 error_type**
- 做法：`_build_result` 在 aborted 置位时同步派生 error_type（如 `error_type="aborted"`）。
- 权衡：更根上，但会改动 error_type 的既有语义边界（当前只在 crashed 时设），可能波及其它消费 error_type 的点，风险面更大。

**推荐：A 为主**（局部、低风险、直达误报点），可选叠加 B 的思路但需先普查 error_type 所有消费方。

---

## P128（中）: ForkJoin 兄弟分支不取消

### 根因回顾
`pool.map` wait-all，无跨分支取消；`CancelToken` 基建已存在但未接入 GraphExecutor。softmax 某分支 halt 后兄弟分支空跑 28min。

### 候选方案

**A — CancelToken 接线 + submit/as_completed 早停（推荐）**
- 做法：ForkJoin 改 `pool.map` 为 `submit` + `as_completed`；共享一个 `CancelToken`；某分支返回 failed/halt 时 `cancel_flag.set()`，其余分支在 checkpoint 点检查 token 提前退出。取消判据用**业务语义**（分支 result 为 failed/halt），不用机制特征（§1.10）。
- 可维护 ✓：复用已有 CancelToken 基建（runner 消费点已就绪）。可扩展 ✓：任意 ForkJoin 自动早停。可诊断 ✓：被取消的分支留「因兄弟分支<原因>取消」信号。架构合理 ✓：修在执行器调度层，职责正确。
- 风险：需确认 agent 执行是否有可响应取消的 checkpoint 点（长 turn 中途可能无法立即响应，取消粒度到 turn 边界，可接受）。

**待评审确认点**：取消是否需区分「failed 才取消」vs「halt(需人工) 也取消」——建议两者都取消（兄弟分支结果都将被丢弃），但请确认无「一分支需人工、其余仍需产出」的合法场景。

---

## P129（中）: partial-halt 无 reason 字符串

### 根因回顾
runner 组装 stage_status 时 `own_error` 只从同 stage `last_error` 取；partial 情况下真因在各 agent 的 `failure_reason`/`aborted`，从不回填 `last_error`；halt reason 由 last_error 派生 → partial 场景 reason 空。

### 候选方案

**A — partial 且无 own_error 时，从 agent_result 合成 last_error（推荐）**
- 做法：runner 组装收尾处，若判定 partial halt 且本 stage own_error 为空，遍历分支 agent_result 的 `failure_reason`/`aborted`，合成一条可读 last_error（如「N 个分支失败：<各分支原因摘要>」）。
- 可维护 ✓：只在 own_error 为空的兜底位补，不动正常路径。可扩展 ✓：任意分支失败原因自动汇入。可诊断 ✓（本条核心目的）：halt 后有明确原因串。架构合理 ✓：runner 是 stage_status 产权方，在此翻译最恰当。
- 与 P125 同根同思路，建议合并评审。

---

## P126（中）: precision baseline commit 缺 git 身份

### 根因回顾
`_entry_commit_codegen` 裸 `git commit`，环境无全局 user.email/user.name → rc=128 `Author identity unknown`。

### 候选方案

**A — commit 命令内联 `-c user.email=... -c user.name=...`（推荐）**
- 做法：该 commit 调用改为 `git -c user.email=<devkit-bot> -c user.name=<devkit-bot> commit ...`，仅对本次 commit 提供身份，**不写全局/仓库 git config**（遵守「保持 git config 不变」的安全约束）。
- 可维护 ✓：单点改动。可扩展 ✓：任何缺身份环境自动成功。可诊断 ✓：不再 rc=128 中断。架构合理 ✓：身份是本次 commit 的局部参数，用 `-c` 内联最贴切，不污染环境配置。

**B（可选叠加）— verify-env 预检提示缺 git 身份**
- 做法：环境自检阶段若检出无 git 身份，给出提示（非阻断）。属加载期校验（§1.3）的锦上添花，非必需。

**推荐：A 为主**（直接根治 rc=128），B 视精力可选。

---

## P130 / P131 / P132（中）: 超时配置族

三条同属「横切超时判据」，建议合并评审、一致落地。核心原则 §1.10：超时该不该作用用**业务语义**声明，不用全局单值代理。

### P131 — turn_stall(300) = 网关 timeout(300) 耦合

> **2026-07-31 订正（推翻原"抬到 900"方案）**：五算子全量复核证明——0 次 keepalive/idle abort + 整窗 429/503/ServiceUnavailable 错误帧风暴 → **连接没死、非 thinking 慢，是网关持续拒绝**；且 trial-5 实证阈值抬到 1803s 仍 abort、五算子无一交付。故「抬 turn_stall 到 900/1800 就留出重试窗能跑完」被日志直接反驳——网关持续过载时抬阈值只是**更久的空等**。原 A 方案（提到 900）撤回。

**A' — turn_stall 保持克制（略高于网关 timeout，仅容一次内部重试）+ 尽早判死 + 带退避 resume（订正推荐）**
- 做法：① turn_stall 从与网关 timeout **恰好相等（300=300，零重试窗）** 调到**略高于**网关 timeout（约 400–600s），只为容纳「网关超时一次 → 内部重试一次 → 吐出完成」这一个窗口，**不往 900/1800 抬**；② turn_stall 触发时经 P125 正确归类 `error_type=infra` → runner 短路终止本轮 → resume；③ resume **带退避**采样新时间窗，**不做阈值升级**（阈值升级被证明是错杠杆）。
- 判据（§1.10 业务语义）：turn_stall 的职责是「判定本 turn 已死」，不是「等到网关自愈」——网关自愈由 resume 退避重采样承担，二者职责分离。
- 可维护 ✓：改默认值 + 注释与网关 timeout 的关系（略大而非 ×3）。可扩展 ✓：网关 timeout 变化时按"略高于"规则调。可诊断 ✓：不再把网关单次超时误判 stall，也不空等 30min。架构合理 ✓：判死 vs 自愈分层。
- **深层放大器（超出 P131 本身，登记待评审）**：真正把「一次 503」滚成「30min / 174 次 429」的是 **opencode 内部 SessionRetry 无界重试**（P117 邻域）——它对着已限流的网关猛捶。理想修复是让 opencode 内部重试有界 + 退避后向框架抛干净 infra 错误，框架据此更快判死 resume。opencode 不可改的现状下，靠 turn_stall（克制阈值）+ P125（判 infra）+ 退避 resume 三者兜。
- **待评审**：① 400–600s 具体取值；② resume 退避策略（固定 vs 指数）由外层 harbor 承载还是框架内建——需与 harbor 侧对齐（当前 harbor 是"阈值升级"，应改为"退避重采样"）。

> **2026-07-31 拍板（用户决策：选项 A 框架内建）**：cross-run 退避重跑**归框架 runner 内建**（§1.7 代码仓自闭环——恢复能力不依赖另一台服务器上 harbor 的行为正确）。落地拆两层：
> - **in-session 软退避（backend 层，已有 429 循环）**：扩 `_RATE_LIMIT_MARKERS`（或新增软退避集）纳入 `503 / ServiceUnavailable / APITimeoutError`——它们同属 burst 过载、session 存活、可退避重发"继续"，与 429 同类。
> - **cross-run 退避重跑（runner 层，新增）**：turn_stall→P125 判 infra→node_status failed 后，runner **自身** sleep 退避（复用 `compute_backoff_seconds` 一源，§2.5）再重跑本 stage 采样新网关窗口，**不再靠 harbor 的阈值升级**。有界（复用 rate_limit_backoff cap 语义或独立 cap），耗尽则真 halt 留 actionable reason。
> - **turn_stall 解耦**：默认从 300（=网关 timeout，零窗+掐死优雅退避）提到 ~600；重推理 stage 靠 P130 per-stage 再上调，不全局抬到 1800。
> - **深层放大器登记**：opencode 内部 SessionRetry 挂住时从不 surface 错误 → 框架 429 退避循环够不着 → 只有 turn_stall 能打断。opencode 不可改，故 turn_stall（打断）+ P125（判 infra）+ runner 退避重跑（恢复）三者是本 backend 下的现实恢复链。

### P130 — turn_stall 对 stage 语义不对称

**定案（2026-07-31，用户拍板）：关闭，不做预留通道。**

- **推翻原推荐 C+B**：C+B 会新增一条「重推理」声明通道（stage 属性 `heavy_reasoning` + per-stage config + 加载期校验），但它是**为尚未发生的问题预留通道**——本工程原则明确「**不为未发生的问题做预留通道**」。
- **无复现事实**：五个 trial 全部 turn_stall abort 都是**网关持续吐 429/503 错误帧**导致的空等（外因，§1.11），**无一例**是「重推理 stage 正常单轮静默 >阈值被误杀」。找不到任何 stage 真的需要 >600s 的静默轮。
- **已被 P131 覆盖**：turn_stall 300→600 已解耦网关 timeout 300；跨-run 退避 resume 已回收 turn_stall abort（重采样新网关窗口）。这次实际发生的问题已闭合。
- **§1.10 不构成落地理由**：§1.10 的反代理要求需存在**语义相反且共享机制特征、必有一类被静默误判**的实例。本条中「重推理被误杀」这一侧目前是**空集**（无复现），不构成「必有一类被误判」的现实二分——现状全局 600 无观测误判。将来真观测到某重 stage 被误杀，再按 §1.10 加声明通道（一行 stage 标志或一个 config 键即可，无需现在铺管线）。
- **结论**：P130 关闭为「已被 P131 覆盖 / 无复现」，**不新增任何代码或配置**。

### P132 — message_timeout 3600 硬杀健康重 stage

**B + C — 默认关闭 deadline，靠 turn-stall 守护 + per-stage 覆盖（推荐）**
- 做法：`message_timeout_s` 默认设 0（关闭硬封顶），把「杀卡死」的职责完全交给 turn-stall（它只杀真卡死，不杀健康推进）；确需硬上限的 stage 用 per-stage 覆盖显式设值。
- 理由：deadline 不随进展重置，杀的是「跑得久但健康」的任务（apply_rotary 3689s 即例），与「杀卡死」语义正交且有害。turn-stall 已足够守护真卡死。
- 四尺子：架构合理 ✓（消除「杀健康任务」的语义）；可诊断 ✓（不再有「莫名 3600 被杀」）。
- **待评审**：是否有「必须有绝对上限防失控烧钱」的诉求需保留一个很大的 deadline（如 4h）而非完全关闭——请裁定。

---

## P134（中）: report.json 假绿

### 根因回顾
`Report.generate` 只读 events.jsonl，见 `stage_complete` 即无条件 status=ok；stage_complete 事件无 status 字段；真实状态在 node_status（blocked）未被消费。

### 候选方案

**A + B — stage_complete 事件带 status + report 用 node_status 权威覆盖（推荐）**
- 做法：① `stage_complete` 事件补 `status` 字段（ok/blocked/halt），Report 按事件 status 定绿而非「事件存在即绿」；② Report 生成时用 node_status 作权威覆盖层，二者不一致以 node_status 为准并留信号。
- 可维护 ✓：事件加字段 + report 加覆盖层。可扩展 ✓：新状态类型自动反映。可诊断 ✓（核心）：消除假绿。架构合理 ✓：§2.9 下游 report 忠实消费权威状态（node_status），不用弱信号自判。
- **待评审**：A 与 B 是否都要，还是 B（node_status 覆盖）已足够、A（事件加 status）为冗余保险——建议以 B 为主修（node_status 是权威），A 为可读性增强。

---

## P135（中）: anchor gate TilingKey 双作者盲区

### 根因回顾
TilingKey 有两个独立作者：template_division.json（权威）与 integrate（再 author routing）；IntegrateStage input_contract 不要求 template_division；`_extract_shared_summary` 提取的 tiling_key 是 dead field（tiling 段不写）。

### 候选方案

**A — integrate 从 template_division 派生 tiling_key（放进 design_spec）+ 删 dead field**
- 做法：IntegrateStage input_contract 纳入 template_division；integrate 不再自行 author，而是从 `templates[].tiling_key` **派生并写进 design_spec**；删死字段。
- 局限：integrate 仍在路由数据链路上（把 template_division 的路由**镜像**进 design_spec）。镜像即第二副本，template_division↔design_spec 仍可 drift（副本未同步），只是把「双作者」降级为「主 + 镜像」，未彻底消除跨产物一致性面。

**B — codegen 直读 template_division 单作者 + integrate 完全不碰路由 + 删死字段（选定）**
- 做法：确立 template_division 为路由**唯一作者**；integrate 既不 author 也不镜像路由（连 design_spec 里的 `tiling_key_router` 幻象字段一并去除）；codegen 直接读 template_division 的 `templates[].tiling_key`+`route_condition` 生成分发；删死字段；validate integration 门不回检路由。
- 四尺子：**零镜像零 drift**——路由只此一份、下游 codegen 忠实消费，一致性由「单作者 + 构造性消费」构造性保证，无需任何跨产物门（§2.9 构造性保证优先于检查门 + 门不越界查上游产物）。可维护 ✓（消除幻象字段+重复作者，路径最短）；可扩展 ✓（多模板自动归位 template_division）；可诊断 ✓（单一真相源，冲突面结构性消除）；架构合理 ✓（作者=template_division 决策点、消费=codegen、门不越界）。
- **对 A 的取代理由**：A 的镜像仍留一条 template_division→design_spec 的同步义务（潜在 drift 面）；B 直接砍掉镜像，codegen 上游本就投递 template_division（codegen.py 已有管线，无需新增），故 B 用更少的移动件拿到更强的构造性保证。

### 定案（2026-07-31，用户拍板「B(推荐)」）：已实施 + 全绿
- 落地清单与验证见 L1 `85-trial-20260730-problems.md` P135 判定块（Python: 删死字段 + 注释订正；skills: integrate/coding/validate/integration_schema 四处；测试 `test_extract_shared_summary_filters_keys` + orchestration UT 全量 1788 passed）。
- 作用域边界：仅 self_evolve_op 设计流水；交互/regbase-coding 簇的 design_spec `tiling_key_router` 表述属另一条流水、未在本批次分析，不改（避免跨流水 scope creep）。

---

## P133（低）: e2e 脚本 banner 硬编码算子名

**直接修**：banner 标题从 OP_DIR/GOLDEN 变量派生（如取 OP_DIR basename），不再写死 `moe_re_routing`。低风险、纯展示，评审通过即改。

---

## P136（算子级，不进框架清单）

exp 精度 fp32 算成 exp(2/3·x)，属算子实现常量/换底错误，归 precision_debug 流程或算子重跑闭合，**非框架代码缺陷**（§1.13 golden 权威，工程未忠实对齐）。此处仅登记，不列入框架修改。

---

## 实施顺序建议（评审通过后落 L4）

1. **共同根因组**（P125 + P129 + P134）：一条「权威失败信号向下游翻译」主线，一并落地，收益最大且互相印证。
2. **ForkJoin 组**（P127 + P128）：同处执行器，最强放大器，优先。
3. **超时配置族**（P130 + P131 + P132）：配置 + stage 语义声明，一致落地。
4. **独立小修**（P126 + P135 + P133）：各自单点。
5. P136 转 precision_debug，不在本清单。

各组落地前按「待评审确认点」逐条与用户对齐，再写对应 L4 impl 文档。

