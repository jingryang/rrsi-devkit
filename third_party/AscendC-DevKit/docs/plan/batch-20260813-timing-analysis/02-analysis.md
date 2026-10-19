# L3 — 单算子生成时间优化方案分析（目标 <2h/算子）

> 关联 L1：`01-problems.md`（P1-P9）
> 本文件记录选项、取舍与决策，调研中演进、拍板后冻结（§1.8 L3 边界）。
> 基线：resize_bilinear 全链 459m（7.66h），其中 codegen 267m 占 58%。

---

## 0. 时间预算总览

### 0.1 现状（resize_bilinear，最优算子）

| 环节 | 耗时 | 占比 | 对应 L1 |
|---|---|---|---|
| 设计（requirement→概设→详设→测试设计） | ~165m | 36% | P7 回炉 |
| **codegen** | **267m** | **58%** | P2/P3/P4 |
| precision + eval | ~22m | 5% | P9 |
| **总计** | **459m** | | |

### 0.2 目标拆解（完整方案见 §6）

| 环节 | 现状 | 第一批后（R1+R3+R4）| 第二批后（+R5+R6+R10）| 削减手段 |
|---|---|---|---|
| 设计 | ~165m | ~130m（R1 死等 -8m + R3 减 AC2）| **~90m** | R1 死等 + R5 消 AC3 + R6 定向 AC2 + R10 读取纪律 |
| codegen | 267m | **~40m** | ~40m | R1 早期 resume + R3 API 知识前置 + R4 首稿纪律 |
| precision + eval | 22m | ~22m | ~22m | 保持 |
| **总计** | **459m** | **~192m（3.2h）** | **~152m（2.5h）** | |

**判断**：第一批（R1+R3+R4）codegen 从 267m→40m，设计也因 R1（设计侧 8 次 stall 死等 -64m）+ R3（减 AC2）下降，单算子 ~3.2h。第二批（R5 彻底消 AC3 + R6 定向 AC2 + R10 读取纪律）设计到 ~90m，总计 ~2.5h。**「tiling 子阶段合并」撤回**（缺乏占比证明数据，属盲目合并）；要严格 <2h 需在 R10 落地后，用数据重新评估是否还有子阶段合并空间。

---

## 1. 选项 A — codegen 会话瘦身（根治 P2/P6 上下文膨胀）

**问题**：coder 单会话 30-212 turn、上下文到 25 万 token。turn 间隔 22-37s 是被大上下文拖慢的；turn 数量爆炸是 skill 驱动下的行为问题。

**选项**：
- **A1 按文件分会话**：tiling/host、kernel、op_api+plugin 各一个 coder 会话（当前一个会话干全部）。每会话 <50 turn、<100k 上下文。
  - 收益：上下文小→turn 快（10-15s）；单个会话死亡损失小；可并行。
  - 代价：跨文件一致性需在会话间接力（§2.3 文件接力机制已存在）；拆分点需要按 skill 定义。
- **A2 会话内 turn 预算**：coder 会话设 turn 上限（如 60），超限强制收尾提交当前进度并换会话续。防 185-turn 单会话空转。
  - 收益：上限硬约束；实现简单（框架层 action 计数）。
  - 代价：强制换会话可能打断关键上下文。
- **A3 维持单会话但禁止过度思考**：降低思考预算。

**取舍**：A1 是根治（与 §1.12「机制通用」一致：会话切分是通用结构，不绑定具体算子）；A2 是兜底。**推荐 A1 为主 + A2 兜底**。

**预期**：codegen turn 数 478→~120（3 会话 × 40 turn），turn 间隔 22s→12s，codegen ~35m。省 ~230m。

---

## 2. 选项 B — 消灭 silent-cut（根治 P3 零写盘）

**问题**：coder 首轮 78 read + 55 bash + 0 Write，只调研不写码；silent-cut 后下一轮从零重探。

**选项**：
- **B1 skill 强制「先写首稿」**：coder 首动作必须是按脚手架模板落全套文件（允许有错），之后针对编译错误迭代；禁止先探索。参考目标仓现成模板（§2.7 脚手架外移给 LLM）直接生成。
  - 收益：消灭 0-Write 轮（每轮省 24-42m × N 轮）。
  - 代价：首稿可能有系统性错误，但编译错误比零产出好修。
- **B2 框架传递上一轮探索结论**：silent-cut 判定后，把上一轮 transcript 摘要注入下一轮 prompt（「已查过 X，勿重复」）。
  - 收益：避免从零重探。
  - 代价：需实现摘要注入（structured 产物字段，§2.10）。
- **B3 silent-cut 计数降级**：连续 silent-cut 2 次即换更强制首稿的 prompt。

**取舍**：B1 是根因修复（skill 流程问题）；B2 是框架补充。**推荐 B1 + B2 组合**。

**预期**：省 2-3 轮零产出 ≈ 60-90m。

---

## 3. 选项 C — 网关健康与上下文控制（缓解 P5/P6）

**问题**：thinking 模式 400（`content[].thinking must be passed back`）、429、validation error；上下文 25 万 token 放大慢/错。

**选项**：
- **C1 codegen 阶段关闭 thinking 模式**：写码/改码不需要深度思考，且当前网关对 thinking 回传有 bug。改为非思考模型（快模式）。
  - 收益：消灭 400 错误源；turn 明显变快（无大 thinking 块）。
  - 代价：可能损失复杂 kernel 的推理质量（需在 A5 复杂算子验证）。
- **C2 网关侧修复**：上游修复 thinking 回传 + usage.output_tokens 校验。
  - 收益：根治。
  - 代价：外部依赖，非本仓可控（§1.11/外部基础设施）。
- **C3 上下文压缩**：coder 每 N turn 用摘要压缩历史（agent 已有 transcript 机制）。

**取舍**：C1 是本仓可立即做的（runtime_config 层开关），C2 需推动外部。**推荐 C1 落地 + C2 上报**。

**预期**：codegen turn 间隔 22s→12s（省 ~1h），消灭 resume/backoff 开销。

---

## 4. 选项 D — 设计回炉收敛（缓解 P7）

**问题**：anchor 对质发现问题后**全量重跑**该模板全部 tiling 子阶段（split→buffer-kernel→precision-perf→anchor），每次回炉 35-105m；resize 2 轮、grid 3 轮。

**选项**：
- **D1 anchor 报告定向化**：anchor（ascendc-op-design-anchor-per-template）产出按 claim 定位的报告（哪个 template 的哪个 tiling claim 不可行），框架据此只重跑被指认的子阶段。
  - 收益：回炉从全量→定向，每次省 ~60-70%。
  - 代价：anchor 报告需结构化字段（claim_id → stage 映射），改 anchor skill + 框架 transition。
- **D2 tiling 契约前置校验**（§1.3 加载期校验）：`contract unsatisfied: tiling_results` 说明 tiling 产物缺字段在跑完后才发现。前置校验缺字段避免整轮重跑。
  - 收益：省 P7 中契约类重跑（resize/unique 各 1 次）。
- **D3 接受回炉为设计质量成本**：复杂算子多轮对质是合理的，只优化单轮时长。

**取舍**：D1 是「正确改动」（定位→定向修复，符合 §1.2 可诊断），D2 是 §1.3 落地。**推荐 D1 + D2**。

**预期**：设计从 ~165m→~110m（消 1 轮回炉）。

---

## 5. 选项 E — 快速失败预算（缓解 P8 超时截断）

**问题**：unique 单会话 212 turn 触发 hard_timeout；codegen loop 上限 1000 次无实质产出判据。

**选项**：
- **E1 首稿预算**：codegen 前 N 轮（如 3）`generated_sources` 仍空（silent-cut）→ 提前 fail-fast 或切换 B1 强制首稿模式，不耗 1000 轮。
  - 收益：避免 silent-cut 死循环烧批预算。
  - 代价：需防误杀（resize 是 iter5 成功，但 iter1-2 是 silent-cut——首稿预算 3 轮内未出的，第 3 轮转强制首稿而非 fail）。
- **E2 turn 预算**：会话 >N turn 强制收尾（同 A2）。

**取舍**：E1 收敛到「转强制首稿」而非「直接失败」，与 B1 衔接。**推荐 E1（转场式）**。

---

## 6. 完整优化方案（按根因组织，非补丁堆叠）

### 6.1 诊断总纲

单算子 7.66h（resize）的时间去向，按**根因**归集：

| 根因 | 直接代价 | 归属 | 端侧能否根治 |
|---|---|---|---|
| 网关不吐字（turn_stall 死等 600s） | ~110m（11 次 × 600s） | 外部代理 | ⚠️ 不能根治，但可**快速失败**（缩到 120s）|
| coder 机械试错（silent-cut + build 循环 + API 盲区） | ~180m（185-turn 会话只写 6 次码） | **本仓（skill 缺 API 知识 + 无首稿纪律）** | ✅ 能根治 |
| 设计回炉 AC3（证据缺失） | ~55m | **本仓（跨模板门越界查 → 字段漂移）** | ✅ 已根治（删除越界门，见 Q16/R5）|
| 设计回炉 AC2（真实设计问题） | ~60m | 本仓（设计需修正）| ⚠️ **fallback 不能保证解决（Q13 证据）**；根因分两层——**方案层 gather 建模错（Q15，主）** + API 层约束盲区（Q14，次），靠 R3 新建 gather 范式（治本）+ 单元素搬运知识（治标）+ R6 定向降低代价 |
| 正常设计 + precision + eval | ~90m | — | 合理成本 |

**结论**：能根治的是「coder 机械试错」（API 知识前置 + 首稿纪律）、「AC3 回炉」（删除越界门——字段漂移根因，见 Q16/R5）、「AC2 的源头」（R3 新建 gather 建模范式治本 + API 知识前置治标——fallback 打地鼠不能根治，见 Q13/Q15）；网关 turn_stall 只能「快速失败」缩到 ~22m。全部落地后 ≈ **2.5h**（见 §0.2）。

### 6.2 方案清单（按依赖排序）

| # | 方案 | 对应根因/P | 层/位置 | 预期省时 | 性质 |
|---|---|---|---|---|---|
| **R1** | **早期 resume**：turn_stall 阈值 600s→120s（模型生成阶段不吐字）。工具执行阶段误判风险低（deploy build 不误判、coder 试探编译短命，见 P17），不必做 block_types 分阶段 | 网关不吐流 / P11 | `runtime_config.opencode_turn_stall_s` | ~88m（设计 8 次×480s=64m + codegen 2×480s=16m + precision 1×480s=8m）| ✅ 确定性，端侧最有效动作，设计/ codegen 两侧都受益 |
| **R2** | **resume 通路统一**：删除 `codegen.py:602-626` 的 stage 层 sidecar resume，统一走 backend 层（含 resume_fails 累计 + degrade）| 设计不一致 / P15 | `codegen.py` | 修 bug（恢复坏 session 的 degrade），非省时 | ✅ 修 §2.5 违反 |
| **R3** | **API 最佳实践前置 + 缺项新建**：移植 `ascendc-api-best-practices`（212K，SKILL + 16 个 API 主题 references）到本仓；codegen/design agent 先查最佳实践、查不到再进大库。本批 AC2 暴露的缺口**不改现有文档打补丁，而按主题新建独立最佳实践**，且分两层——**「间接索引 gather 建模范式」（优先，Q15：AC2 根因是 gather 被建模成逐元素搬运，属方案层错误，按结构特征定义 §1.12）** + **「单元素/标量搬运」（降级，Q14：只覆盖 offset 表等确需标量写的小规模合法场景，明确排除大规模逐元素 gather）** | API 盲区 + **gather 建模走偏** → 机械试错 + AC2 设计错误 / P3+P4+P12+P13 | 移植到 `.claude/skills/ascendc-api-best-practices/`（SKILL + 16 references）+ **`knowledge_policy.md` 强制查证门优先级调整**（先 best-practices → 再 Tier 3）+ **新增 `references/api-gather.md`**（API 用法层；概要设计模式层归 `G01_gather-vector.md` 补采样/插值变体，见 L4 草案） | ~120m（codegen cast/constexpr）+ 从源头减少设计 AC2 回炉 | ✅ 根治「不知道 API 约束」+「gather 建模错」；缺失主题**新建独立最佳实践**，不补丁式改现有文档 |
| **R4** | **首稿纪律（补缺）**：coding skill 已有「参考来源纪律 + 落盘纪律」，缺「首动作先落全套脚手架文件（允许有错）、再迭代」的显式纪律——补 Step 4 首动作约束 | silent-cut 零写盘 / P3 | `ascendc-op-dev-coding` skill Step 4 | ~60m（消灭 0-Write 轮）| ✅ 根治零写盘（已 60% 落地，补首动作约束）|
| **R5** | **删除越界门（已实施）**：坐实「段空」根因 = `_extract_shared_summary` 提取白名单字段漂移（越界查上游的必然结果，Q16）→ 删除「跨模板一致性判定」+ `_extract_shared_summary`，一致性由「单一作者 + 下游忠实消费」构造性保证（§2.9），补 `TemplateDivisionStage` 的「tiling_key 唯一」自检 | AC3 回炉 / P13 | `design_substages.py` + `anchor-consistency/SKILL.md` | ~55m（消 AC3 回炉）| ✅ 已实施（196 UT），字段漂移在机制上不再发生 |
| **R6** | **anchor 定向回炉**：**已实现**——`design_tree.py` 的 `_tiling_rerun_selector`/`_anchor_rerun_selector` 已落地，`rerun_selector` 接入 `ForkJoinGroup` + `graph_executor`（AC2 只重跑被指认 `target_template`，缺 target_template 才退化全量）。无需实施，仅剩「观察 AC2 缺 target_template 退化全量的频率」 | AC2 回炉 / P13 | 已实现（`design_tree.py`/`node_forkjoin.py`/`graph_executor.py`）| 已生效 | ✅ 已实现 |
| R7 | **deploy 构建超时动态化（预防性，本批未坐实）**：本批 build 走「增量命令」的 `if [ -f build/CMakeCache.txt ]` 门，但**增量未生效**（CMake GLOB 全量重编 51 个 .o，见 P16/Q11），实测全量重编 ~34s，**无 >600s 超时案例**。「600s 误判」是「防未来复杂算子编译超时」的预防性假设，非本批已发生 bug → 降级预防性、暂缓 | 构建超时误判 / P17（预防性）| `deploy.py` `_run_command` | 0（本批无超时）| ⚠️ 预防性，本批 build ~34s <600s |
| **R10** | **读取纪律（补缺）**：design/coding skill 已有「输入路径清单 + 禁自行搜罗」，缺「每文件读一次（去重）+ 禁 `ls/cd/find` 目录侦查」的显式约束 | 读取失控 / P18 | design/codegen skill 输入获取章节 | ~30-60m（73 read 去重 31、ls/cd/find 30 次）| ✅ 实证（已 50% 落地，补去重 + 禁侦查）|
| R8 | 首稿预算兜底：N 轮无 generated_sources → 转 R4 强制首稿而非无限重试 | 超时 / P8 | 框架 action 计数 | 防超时 | 兜底 |
| R9 | 网关健康上报（不产流/400/429）| 外部 | — | turn_stall 根治 | ⚠️ 本仓不可修 |

### 6.3 实施顺序与预期

- **第一批（本仓可立即做，收益最大）**：R1 早期 resume（~88m，设计+codegen 两侧）+ R3 API 知识前置（~120m）+ R4 首稿纪律（~60m）。codegen 从 267m → ~40m。
- **第二批（修缺陷 + 设计收敛）**：R2 resume 通路统一（修 P15）+ R5 删除越界门（彻底消灭 AC3 回炉 ~55m）+ R6 anchor 定向回炉（减少 AC2 代价 ~30m）+ R7 deploy 构建超时动态化 + R10 读取纪律（~30-60m）。设计从 165m → ~110m。
- **撤回项**：「tiling 子阶段合并」暂不做——缺乏「spawn 开销 + 上下文重建占比」的证明数据，属盲目合并（用户判断）。若 R10 读取纪律落地后子阶段仍慢，再补数据评估合并。
- **落地后预期**：≈ **2.5h/算子**（见 §0.2）。要严格 <2h 需在 R10 落地后，用数据重新评估是否还有子阶段合并空间，或接受设计为新的瓶颈单独优化。

**诚实结论**：R1 是最直接的确定性收益（省 88m 死等），R3+R4 是根治 codegen 机械试错（省 ~180m），R5 是设计回炉的一劳永逸解。turn_stall 的根治仍在网关（R9 外部），端侧 R1 只是把它从「600s 死等」缩到「120s 快速恢复」。deploy 构建超时（R7）是独立于 turn_stall 的另一层，框架有精确信号可修。

---

## 7. 验证方法

- 每项改动后，用**同 3 个算子**重跑 batch（或单算子 `ascendc-devkit run`），对比 `events.jsonl` 阶段墙钟 + coder turn 计数。
- 量化指标：codegen 墙钟、coder 会话数/turn 数、silent-cut 次数、build 失败次数、turn 间隔分布、turn_stall 次数。
- 回归守护：既有 UT/ST（§3）；对 skill 改动（B1）用 §2.1 即插即用判据（skill 单独取出单跑）。
- 与 baseline（本文档 P1 表格）对比，逐项验证收益与无回归。

---

## 8. 深挖根因与问题回答（session 日志实证）

### Q1 — turn_stall 根因是什么？模型真没响应还是网关问题？

**根因：网关（三方代理）对新鲜会话不产流。inotify 曾被误列为根因，经反证已排除。**

证据链：
1. **时序**：GLM 时代（8/9-8/11）314 个 serve 全 0 inotify 错误、无此量级 stall；换三方代理（deepseek-v4-flash @ 1.95.37.146:3000）后（8/12 起）turn_stall 出现。**与换代理严格对应**。
2. **逻辑排除 inotify**：turn_stall 检测器只监控 `sse.state["turn_ts"]`（模型 SSE 流活性）与 chars（`opencode_backend.py:1577-1601`）；inotify 是文件监听路径，与 SSE 流完全独立——inotify 失败不可能触发「600s 无 SSE」判定。且 101 个 inotify 错 serve 仅 11 次 stall，带错 serve 绝大多数正常工作。
3. **同源网关错误**：`content[].thinking must be passed back`（400）、`usage.output_tokens` 校验失败、429（P5）——全是代理层问题。
4. **stall 形态**：9/11 次卡 `last turn 2`——新鲜 spawn 后首个真实模型响应 600s 无任何 SSE（thinking/text 都无，`chars static 610s`）。

5. **坐实：判死后恢复链路（run.log 硬证据）**：每次 turn_stall 判死后，紧接 `infra_backoff sleeping 20s then re-spawning to sample a fresh gateway window` + `agent_resume cross-run resume`，**立即成功恢复**（无一例反复卡死在 resume 环节）。且 11 次 stall 无一例「600s 内自发恢复」（若有慢请求会在判死前恢复，run.log 不会出现 turn_stall 判死）。这坐实了：**stall 是「新鲜会话永久不产流」（last turn 2），非「可恢复的慢请求」；恢复靠「判死 + resume 重采样」，不靠「等待 600s」**。故缩到 120s 只是把「判死 + resume」提前 480s，不误杀任何「可恢复的慢请求」（本批无此案例），省 ~88m 成立。

**inotify ENOSPC 是什么**：不是磁盘满。`inotify_add_watch` 的 ENOSPC = 每用户 watch 数达 `max_user_watches=8192` 上限（`max_user_instances=128` 是另一上限，报在 init）。主仓 28.2 万文件（output/ 占 97%，35 批累积）使 watch 数压力大。它是**独立的环境资源现象**，与换代理时序相关（代理慢响应→serve 存活久→并发多→watch 压力大）但**非因果、非 stall 原因**。

**结论**：不是「模型拒绝响应」也不是「任务太难」，是**三方代理网关对部分请求不产流**。这是外部基础设施问题（§1.11）。端侧最有效的动作是 **R1 早期 resume**：把 turn_stall 死等从 600s 缩到 120s（仅对「模型生成阶段」无 `tool:` block；「工具执行阶段」保持 600s），11 次 stall 死等从 ~110m 缩到 ~22m。数据佐证：11 次 stall 全部是「模型生成阶段不吐字」（block_types 空），无工具执行误杀风险。此方案不需关 thinking（避免分阶段开关的控制复杂性），只动检测器阈值 + block_types 分支。

### Q2 — turn 数量爆炸根因？任务太复杂？

**三类行为叠加，不单是复杂度：**

| 行为 | 证据 | 归属 |
|---|---|---|
| silent-cut 探索 | 首轮 78 read + 55 bash + 0 write | 与复杂度无关，skill 纪律问题（P3） |
| **机械编译修复循环** | resize sess4（185 turn）：125 bash + 51 read + **仅 6 write/edit**，自建 `/tmp/opencode/rbcheck` 沙箱 g++ -fsyntax-only 反复试 cast | 与复杂度无关，试错式修复（P12） |
| 真实设计复杂度 | grid 8 个 AC2 阻断问题需真修（P13） | 真复杂度，合理多轮 |

**结论**：resize 的 185-turn 会话是**机械编译修复循环**（代码逻辑来自设计，只差语法），不是复杂度；grid 的多轮是真实设计复杂度。**大头是可避免的机械循环，不是复杂度。**

### Q3 — turn 间隔 22-37s 是否正常？

**否，异常慢 3-5 倍。** 同模型同网关对比：design-generator avg 7-8s / p90 11-16s，coder avg 22-37s / p90 46-74s（P14）。

原因：
1. **上下文膨胀**：coder 会话 250k token，每 turn 处理上下文远大于设计 agent → 生成变慢。
2. **重型 bash 工具执行**：编译 30s-2min，计入 turn 间隔。

**结论**：22-37s 是被上下文 + bash 执行拉高的**异常值**。修上下文（分会话瘦身）+ 首稿纪律（减少 bash 试探）后可回落到 ~7-15s。

### Q4 — codegen 解的什么 bug？kernel 问题吗？有明确思路还是靠猜？precision debug 能更好吗？

- **bug 类别**：机械性 AscendC/C++ 编译错误（`(uint32_t)d` C 风格 cast 被 kernel 编译器拒、非 constexpr 表达式），**不是 kernel 逻辑 bug**——语义正确仅语法不合格（build_ascendc.log 实证）。
- **解法**：**试错式**（沙箱 g++ 反复试），非一次性系统应用。因 coder 未预载 AscendC 编译约束知识，靠编译错误逐个发现。
- **precision debug 能否更好？不能。** 编译错误不是精度问题；precision 的 scope_guard 对编译失败会 halt（上游缺陷）。编译修复属 codegen（或独立 compile-fix 阶段）。
- **改进**：把 AscendC 编译约束（cast/constexpr 规则）预载进 coder reference（skill 侧），或加确定性 lint 预检，首稿即避免此类错误。

### Q5 — 为什么 codegen 修正后 precision 不需要工作？是设计比较好吗？

**是——设计好，代码真实正确。**
- resize 代码真实正确：devkit run_tests 1M 元素 0 失配 max_abs_diff=0 + cann-bench eval genuine_pass_rate 1.0（20/20）。
- 归因到设计：resize tiling **无 AC2 阻断**（仅 AC3 证据缺失，P13）；grid 有 8 个 AC2 → 精度 18/20 真实失败。**设计正确 → 代码正确 → precision 无事可做**。
- **澄清误读**：控制台 `(no golden)`/`golden_first10: []` 是 harness **显示层**未取 golden 张量（_harness_template.py:687），评分路径（cann-bench compare.py）做了真实 1M 元素对比——**不是假通过**。

### Q6 — thinking 耗时分析；「关 thinking」是否该做？

- **规模**：coder 平均 thinking 块 4679-9546 chars（design 3826-4748），最大 100k+（P14）。结合「185-turn 会话仅 6 次写码」——大量 thinking 未转化为有效行动。
- **结论：不把「分阶段关 thinking」作为首要方案**。理由（用户判断 + 本文评估一致）：
  - 分阶段开关 thinking 引入控制复杂性（何时开/关、按 stage 还是按 turn 判据），收益只是「缓解」thinking 400 与慢 turn，不根治。
  - thinking 慢的**真正根因是上下文大 + API 盲区导致的机械试错**（P6+P12），应直接治这两个（R3 API 知识前置 + 首稿纪律），而非压 thinking 开关。
  - thinking 400 是网关 bug（外部），靠「少用 thinking」规避是间接缓解；更直接的端侧动作是 R1 早期 resume（网关不吐字快速恢复）。
- **保留作为可选二级手段**：若 R3/R4 落地后 thinking 仍是瓶颈，再评估「编译修复阶段关 thinking」（该阶段错误是确定性编译错误，thinking 价值低）。但这不作为第一批，避免控制复杂性。

### Q7 — anchor 定向回炉 + tiling 契约前置校验：有详细分析和方案吗？

> 注：本节 AC3 根因（「段空」）是当时的分析，已被 Q16 更新为「字段漂移/越界查上游」。D2（契约前置校验）也已被 R5（删除越界门）取代。

**没有既有分析，但已实证出方案依据（P13）：**
- **回炉两类根因**：AC2（真实设计问题，grid 8 个）vs AC3（证据缺失，resize/grid 各 8 个）。
- **AC3 根因**：`tiling_shared_summary.json` 的 split/buffer_kernel 段为空（无 TilingKey 字段、workspace 记录、dtype 路由表）→ anchor 无法对质 → 全量重跑。**违反 §1.3（加载期校验优于运行期暴露）**——本可在 tiling 产出时校验段非空。
- **方案**：
  - **D2 tiling 契约前置校验**：tiling 产出后校验 shared summary 各段非空（TilingKey 字段定义、workspace 分配、dtype 路由表），缺失即时补全/报错。**消灭全部 AC3 类回炉**（resize 整轮回炉、grid 部分）。
  - **D1 anchor 定向回炉**：anchor 已产结构化 issue code（AC2/AC3 + detail + claim 定位），按 code 路由：AC2 → 只重跑被指认子阶段；AC3 → 走 D2 契约补全而非全量重跑。
- **待补**：具体改哪个函数/校验器，见后续 L4 实施方案（`NN-impl-*.md`）。

### Q8 — 质疑复盘：inotify 不是根因（用户反问驱动的修正）

**用户质疑**：inotify 问题在改用三方代理后出现，早先 GLM 并发更大也无此问题，怀疑不在端侧。所有方案须经反问。

**修正过程与证据**：
1. **时序反证**：历史 serve 日志显示 GLM 时代 8/9（314 serve）、8/10（38）、8/11（50）**全 0 inotify 错误**；8/12 14:32（4 serve 3 错）起出现，与换代理吻合。
2. **逻辑排除**：turn_stall 检测器只读 SSE 流状态（`sse.state["turn_ts"]`/chars），inotify 是文件监听路径，两者独立——inotify 失败**无法**触发「600s 无 SSE」判定。且 101 个 inotify 错 serve 仅 11 次 stall，带错 serve 绝大多数正常工作。
3. **同源证据**：代理的 `content[].thinking` 400、`usage.output_tokens` 校验失败、429——全是代理层问题，与 inotify 无关。
4. **inotify 报错本质**：ENOSPC = 每用户 watch 数超 `max_user_watches=8192`（非磁盘满）；主仓 28.2 万文件（output/ 占 97%）是压力源。它是**独立环境现象**，与换代理时序相关（代理慢响应→serve 存活久→并发多→watch 压力大）但非因果。

**修正后的结论**：
- turn_stall 根因 = **三方代理网关不产流**（外部，§1.11），非端侧。
- inotify 报错 = 独立环境资源警告，**不是 stall 原因**，不当作根因方案（降为 I0 资源卫生）。
- 端侧能做的是**减少对代理慢/错的暴露面**（R1 早期 resume 快速恢复 + 分会话缩短请求 + 首稿纪律减少 turn），而非修 inotify。

**教训**：初次分析把「时序相关的环境警告」误判为「根因」，未做「机制是否可达」验证。修正方法：检查根因候选到现象的**因果路径是否可达**（inotify→SSE 不独立），并用历史数据做时序反证。后续所有根因判断先过这两关。

### Q9 — 同样 turn_stall，codegen 为什么走不同 resume 路径？符合设计一致性吗？

**不符合设计一致性——这是真实的设计不一致（技术债），不是有意的特殊原因。**

代码实证的两条 resume 通路：
- **backend 层通用 resume**（`opencode_backend.py:563-599`）：spawn 时 framework 未传 `resume_session_id` → backend 读 sidecar（session_id + `resume_fails`）→ `resume_fails >= 3` 退化 fresh，否则 resume。design 阶段走这条。
- **codegen stage 层显式 resume**（`codegen.py:602-626`）：`actions()` 自己读 sidecar（**只读 session_id、不读 resume_fails**）→ `return [SpawnAgent(resume_session_id=_sid)]`。codegen 走这条。

**为什么 codegen 有 stage 层 resume**：历史遗留（代码注释「existing, unchanged」）。当初 codegen 需要「跨 iteration 续同一个 coder session」（build 失败重试时让 coder 看到上次的编译错误），把 resume 决策提前到 stage 层。但它与 backend 层 resume **职责重叠**（§2.5 违反），且实现**不完整**——没跟上 backend 层后来加上的 `resume_fails` 累计 + degrade 演进。

**后果（真实缺陷）**：codegen stage 层只读 session_id、不读 resume_fails；显式传 `resume_session_id` 后 backend 走 `if resume_session_id:` 分支，`_resume_fails=0` 写回 sidecar → **覆盖 crash-salvage 累加的 resume_fails**。导致 codegen 的坏 session 反复 stall 时 `resume_fails` 永远归零、**永不退化 fresh**，违背 094d60e7「resume 数次不成功退化 spawn」的设计意图。本次批跑未触发（resume 后 session 都恢复），但这是潜在死循环风险。

**修复方向（R2）**：删除 `codegen.py` 的 stage 层 sidecar 读取，统一走 backend 层 resume（读 resume_fails + degrade）。codegen 的「跨 iteration 续 session」需求由 backend 层 sidecar 机制自然满足（sidecar 在 spawn 间持久，不因 iteration 边界丢失）。

### Q10 — 移植 ascendc-api-best-practices 增强 API 知识，是否合理？

**合理，且正是根治「coder 机械试错」的关键。**

证据：本批 codegen 的机械试错（P12 的 185-turn 会话只写 6 次码、P4 的 cast/constexpr 编译错误），根因是 **coder 没有预载 AscendC API 的编译约束与语义知识**，靠编译错误逐个发现。

移植源 `/home/x00584171/code/cannbot-skills/ops/ascendc-api-best-practices`（212K / 19 文件）内容高度契合：
- `api-restrictions.md`：编译期限制（禁 std:: 计算函数、cast 规则、constexpr）——**正好对应 P4 的 cast/constexpr 编译错误**
- `api-datacopy.md`：DataCopyPad 语义与非对齐约束——**正好对应 grid 的 AC2（DataCopyPad 标量搬运语义）**
- `api-quickref.md`：API 参数速查表

**当前差距**：codegen skill 已引用 `ascendc-dev-knowledge`，但路径深长（`basic_knowledge_docs/.../api_reference_docs/...`），agent 要在大库里 grep；而 best-practices 是**精炼的避坑清单**（直接给出「禁止/替代/限制」）。

**移植方案**：
- 归位到 `resources/`（§1.5 算子知识不进代码，best-practices 属 API 知识资源），或 codegen/design skill 的 `references/`（§2.2 资源归属 skill 目录）。
- 改写 codegen skill 的查证顺序（Step 3）：**先查 best-practices（精炼避坑），查不到再进 ascendc-dev-knowledge 大库**。
- 注意 §1.12：best-practices 只写「API 判据 + 抽象范式」，不把具体算子名当分类锚点（当前 best-practices 的「典型场景」列含 Softmax/LayerNorm 等，需审查是否符合 §1.12 的结构信号驱动要求，还是应改为「结构特征描述」）。

**预期收益（R3）**：coder 首稿即避免 cast/constexpr/DataCopyPad 语义错误，机械试错从「逐个编译错误试探」转为「按清单避坑」，codegen turn 数大幅下降（~120m）。

### Q11 — 增量构建是否生效？工具执行期间框架能否知道「正在构建」？

**（1）增量构建：配置了，但 CMake 层未生效（全量重编 .o）**

证据（P16）：
- cann-bench profile 有 `incremental_command_template`（`[ -f build/CMakeCache.txt ]` 门 + `cmake --build build`），意图复用 build/ 增量。
- 但 build 日志显示 `cmake --build build` 触发 re-configure 后，**从 [3%]→[97%] 全量编译 add/sqrt/resize_bilinear 三个算子共 51 个 .o**。
- 根因：cann-bench CMakeLists 用 GLOB 收集 `csrc/ops/` 所有算子源文件，coder 每次改文件 → GLOB 变化 → re-configure + 全量重编。
- **影响分层**：host .o 编译快（并行 ~30s），不是瓶颈；真正的耗时是 **kernel TBE 编译**（`.h` → kernel binary，失败那次 62s 报 cast 错误）。成功 build 12s 那次 kernel 未重编（前次已成功，只重新打包），说明 **kernel 层有缓存、host .o 层无增量**。
- **结论**：增量构建在 host .o 层未生效（GLOB 全量），但这不是 codegen 慢的主因（.o 快）；主因是 kernel TBE 编译 + coder 机械试错反复触发 build。若要让增量真正生效，需改 cann-bench CMakeLists（GLOB 改显式列文件，或加 CONFIGURE_DEPENDS），属 cann-bench 侧、非本仓可改（memory `cann-bench-local-only-code-must-go`）。

**（2）「构建编译」是框架自己跑的，不依赖 opencode SSE——此前混淆已修正**

**核心澄清（经用户纠正）**：codegen 阶段有两种「编译」，此前分析把它们混为一谈：

| | deploy build（正规构建） | coder bash 工具编译（试探） |
|---|---|---|
| 谁跑的 | **框架 `subprocess.run(timeout=600, capture_output=True)` 直接跑** | opencode 的 bash 工具 |
| 框架可见性 | **完全可见**：Popen/poll + `build_ascendc.log` 完整落盘 + `TimeoutExpired` 处理 | 仅 SSE 知道「发了 tool:bash」 |
| 是否被 turn_stall 误判 | **否**（时序不重叠，有自己的 `_BUILD_TIMEOUT=600`） | 可能（agent 会话内 bash 编译 >600s） |

**所以「构建编译」完全在框架控制下**——有日志（`build_ascendc.log`）、有 poll、有自己的超时（`_BUILD_TIMEOUT=600`），**根本不需要依赖 opencode SSE 来判断**。

**关键澄清（决定性证据）**：`codegen.py:671` 注释明言「**coder 不自己 build，框架在 transition 直调 Deployer.deploy**」。因此「agent 调用框架进行编译」这个场景**不存在**——编译是框架在 coder 返回后、transition 里跑的 subprocess，此时 agent message POST 已结束（`_post_message_watched` 返回），turn_stall 窗口已关闭。**turn_stall 改 120s 不会误杀 deploy build**（框架编译），它有自己的 `_BUILD_TIMEOUT=600`。唯一会被 120s 误杀的是 coder 会话内**自发**的 bash 工具试探编译（如沙箱 g++，非 skill 指导、非框架编译），但单文件试探编译短命、本批从未 >120s。

**真正的 600s 风险，落点重新定位**：
1. **coder bash 工具编译**（opencode 跑的，试探 g++）：若 >600s 会被 turn_stall 误判。但试探编译短命（单文件 g++ 几秒-几十秒），风险低。本批 11 次 stall 全是「模型不吐字」的 turn 2，无一次工具执行误判。
2. **deploy `_BUILD_TIMEOUT=600`（`deploy.py:61`）硬编码**：复杂算子（多模板/大 kernel）编译 >600s 时，**框架在 deploy 层判为超时失败**——这才是「600s 不合理」的精确落点，也是**本仓能精确修的**（不像 turn_stall 只能从 SSE 猜）：deploy 有 poll + build 日志，可改为「按 build 日志/poll 判断是否真卡死」或「按算子复杂度/模板数动态放宽超时」。

**修订后的 R1（简化）**：
- turn_stall 误判「coder bash 工具编译」是低风险，**不必为它做复杂的 block_types 分阶段**。核心仍是「模型不吐字快速 trip」：turn_stall 阈值 600s→120s（模型生成阶段不吐字）。
- **真正要修的是 deploy 的 `_BUILD_TIMEOUT=600` 硬编码**（新增 R7，见下）：复杂算子编译 >600s 应在 deploy 层放宽/动态化，而非在 turn_stall 层打补丁。

**新增方案 R7（deploy 构建超时动态化）**：`_BUILD_TIMEOUT` 从硬编码 600 改为「按 build 日志增长/poll 存活判断是否真卡死」——deploy 层有精确信号（subprocess poll + build_ascendc.log 逐行增长），可区分「编译进行中（日志持续增长）」vs「编译卡死（日志静止）」，避免复杂算子长编译被 600s 误判。这与 turn_stall 无关，是 deploy 层自己的超时策略问题。

### Q12 — 回炉的问题能够彻底解决吗？

**分两类，可解决性完全不同（根因见 P13）：**

**AC3 类（证据缺失）——能彻底解决，且应该彻底解决。**
- 根因（Q16 坐实修正）：表面是「`tiling_shared_summary.json` 段为空」，实际是 `_extract_shared_summary` 提取白名单字段漂移——「跨模板一致性判定」越界查上游（§2.9 违反），手工字段名白名单跟上上游 schema 演进漂移，提取恒空 → AC3 unverified 噪音。
- R5（删除越界门）**一劳永逸**：删除「跨模板一致性判定」+ `_extract_shared_summary`，一致性由「单一作者 + 下游忠实消费」构造性保证（§2.9），字段漂移在机制上不再可能发生。
- resize 的回炉**全是 AC3**（0 个 AC2），因此 resize 的回炉能被彻底消灭。

**AC2 类（真实设计错误）——不能彻底解决，但能大幅减少。**
- 根因：设计 agent 在 tiling 时用了错误的 API 假设（如「DataCopyPad 单元素搬运」「8 邻域 gather 超 UB 预算」），anchor 对质发现真实错误。
- **这类是 LLM 设计总会犯错**（每个新算子遇到新 API 的新约束），anchor 发现错误是正确且必要的（设计质量门的工作）。
- 但两个方向收敛：
  1. **R3（API 知识前置）从源头减少**：AC2 与 codegen 的 cast 错误**同源**（都是「不知道 API 约束」）。`api-datacopy.md` 讲最小搬运粒度、`api-buffer.md` 讲 UB 预算——设计 agent 产出 tiling 时就避开。
  2. **R6（anchor 定向回炉）降低残留代价**：AC2 只重跑被指认子阶段，不全量重跑。

**结论**：「总有漏网之鱼、每次新算子都出问题、收敛太难」本质是 AC2 类。彻底消除 AC2 = 让 LLM 设计永不犯错，不可能。但 R3 把「API 约束」前置到设计产出时，比「事后 anchor 对质→回炉」更根本：从「发现错误再修」变成「产出时就避开」。AC3 则靠 R5 构造性保证彻底归零。

### Q13 — AC2 发现的 API 问题，fallback 回炉真的能解决吗？

**不能保证解决，grid 是完整反例（证据链）：**

1. grid 第一轮 anchor 发现 8 个 AC2（DataCopyPad 相关为主）。
2. 回炉 2-3 轮后 AC2 减到 2 个，但这 2 个「DataCopyPad」问题**一路残留**——`tiling/T2` → `anchor-consistency` → `integrate` → `validate` 四阶段 `anchor_report.json` 都是这 2 个 AC2（`severity=blocker, verdict=infeasible`）。
3. `validate/anchor_report.json` 的 `status="blocked"`，但流程继续走到 codegen → 精度 **18/20 失败（pass_rate 10%）**。

**根因（fallback 是「打地鼠」）**：
- 残留 AC2 内容：「逐位置标量 GM→UB DataCopyPad 直写 yTile[p]（单元素搬运）」「A2 不支持设置 data copy mode」。
- anchor feedback 只说「**claim 不可行**」（DataCopyPad 不支持单元素搬运），**没说「正确替代方案」**（批量搬运+掩码？Gather？）。
- 回炉是「让同一个设计 agent（同样的 API 知识）重新设计」。agent 没有 DataCopyPad 约束知识，就无法自己找替代方案——要么还用错误假设，要么改到另一个错误用法。
- 所以 2 个 DataCopyPad 核心问题 2-3 轮都无法自愈，root cause（「不知道正确替代」）没变。

**结论（修正方案定位）**：
- **R6（anchor 定向回炉）只降低「回炉代价」**（只重跑被指认子阶段），**不解决 API 问题本身**。
- **R3（API 知识前置）才是解决 AC2 的根治手段**——让设计 agent 产出时就拥有 DataCopyPad 约束（最小搬运粒度、对齐约束、mode 支持），从源头不用「单元素搬运」的错误假设。
- **R3 不是可选项，是解决 AC2 的唯一根本路径**；靠 fallback 打地鼠，AC2 会残留，残次设计流进 codegen、精度失败。

### Q14 — 移植 API 最佳实践不正是为了解决 DataCopyPad 等 API 问题吗？

**是，但姿势不是「改现有文档补负面约束」，而是「缺项新建独立最佳实践」。**

**核心判断（用户修正，替代上版「反哺补现有文档」）**：`api-datacopy.md` 没写「单元素搬运」约束，**不是文档遗漏，而是 DataCopyPad 语义上就不支持单元素搬运**——它按 block/tile 搬运，dst LocalTensor 有 32B 对齐约束。给一个「正面讲怎么用」的 API 文档补「它不支持 X」的负面清单，是打补丁式修改，会污染文档语义；正确姿势是**先查是否有其他最佳实践正面覆盖「单元素搬运该怎么做」，没有就新建一个专门主题**。

**查证结果（实测 `ascendc-api-best-practices`，SKILL + 16 个 API 主题 references，212K）**：
- 「单元素/标量搬运」当前**零散分散、无正面集中入口**：
  - `api-datacopy.md:31-45` 只讲「`GlobalTensor::SetValue/GetValue` 效率极低、仅调试、禁止生产用」，替代指向 `DataCopyPad`——但**没回答「当必须逐位置标量读写时，DataCopyPad 也不行，正确姿势是什么」**。
  - `api-gathermask.md` 有 GatherMask 替代逐元素 SetValue/GetValue（RoPE 奇偶拆分/interleaved 提取），是**一个**正面方案，但挂在 gathermask 主题下，不是「单元素搬运」入口。
  - `api-transpose.md:229` 有「逐元素 GetValue/SetValue → 标量 UB 读写吞吐极差 → `DataCopy/DataCopyPad + vector route`」，也是**一个**正面方案，同样散落。
- 结论：**「单元素/标量搬运」是独立主题，但缺一个正面、集中的最佳实践**回答「必须逐位置标量读写时，怎么选 API（LocalTensor 标量语义 vs GatherMask vs DataCopyPad+vector route 重构 vs 整块+mask）」。

**结论（R3 的修正）**：R3 从「移植 + 反哺补现有文档」改为「**移植 + 缺项新建独立主题最佳实践**」——本批 AC2/cast 暴露的「单元素/标量搬运」缺口，**新建一个专门的最佳实践**（如 `api-scalar-move.md`），正面讲「何时禁止 GlobalTensor::SetValue、何时 LocalTensor 标量写合法、何时用 GatherMask / DataCopyPad+vector route 重构」；DataCopyPad 的对齐边界作为「为何这样选」的**原因**写进新主题，而非作为「DataCopyPad 不支持 X」的负面补丁挂在 api-datacopy.md 下。同理，「A2 mode 不支持」这类代际差异若查无对应最佳实践，也按主题新建或归到已有平台差异文档，不打补丁。

**诚实的现状**：本批 grid 的 2 个残余 DataCopyPad 问题**并未真正解决**（AC2 判 blocked 后携带至 precision 18/20 fail，见 Q13），故「单元素搬运的正确替代方案」目前**尚未从 golden/API 规格确立**。新建的最佳实践先写「已知边界 + 已确立的替代（GatherMask / vector route）」，未确立的部分保持「待确立」显式标记，不硬凑。

**闭环**：AC2/cast 暴露「某主题缺失正面最佳实践」→ 新建独立主题 → 下次 design/codegen 查该主题直接拿到「正确姿势」。这才是根治，而非「拷贝可能不完整的知识库 + 给现有文档打负面补丁」。

**但更根本的见 Q15**：对「按运行时索引间接寻址采样」这类 gather 算子（结构特征，§1.12 不点名），「单元素搬运」本身可能就是建模错误——正确方案根本不需要它。Q14 的「新建单元素搬运最佳实践」默认了「单元素搬运合法」，若该算子本不该做单元素搬运，则真正该新建的是「gather 建模范式」而非「单元素搬运」。两者不冲突：先按 Q15 判「是不是 gather 建模错」，是则归 gather 范式；否（确需小规模标量写，如 offset 表）才归单元素搬运。

### Q15 — 会不会是方案的问题：这个算子根本不需要单元素搬运？

**答案：是。这是方案层（算法分解）的问题，比 Q14 的 API 层更深，才是 AC2 的真正根因。**

**算法本质**：`grid_sampler_3d = torch.nn.functional.grid_sample(x, grid)`（golden 直接调 PyTorch）。语义是**按 grid 坐标 gather + 三线性插值**：输出每个元素 = 输入里 8 个角点（d/h/w 的 floor/ceil 组合）的加权和。golden 是 CPU 逐元素参考（逐元素循环是 CPU 自然写法），但 **NPU 实现必须向量化 gather**——golden 定行为（§1.13），「怎么做」映射到硬件是设计职责，逐元素照搬到 NPU 就是方案走偏。（注：`grid_sampler_3d` 此处仅作 L1/L3 实例追溯；落到 skill 的最佳实践须用结构特征描述「按运行时索引间接寻址采样的算子」，不得以算子名当分类锚点，§1.12。）

**方案走偏的实证**（`grid_sampler_3d.h:442-544`，anchor 回炉后落地版）：
```cpp
// GatherTrilinear / GatherNearest 核心循环
for k in 0..7, for p in 0..F:
    DataCopyPad(slot, xGm_[planeBase + addr], {blockLen=1元素});  // 逐元素 GM→UB
    val = slot.GetValue(0);
    xN.SetValue(k*F+p, val);   // 标量写
```
每输出点 8 次 DataCopyPad + 8 次 GetValue + 8 次 SetValue，全标量（PIPE_S）。DataCopyPad 每次只搬 1 元素，但 A2 Normal 模式逐事务补 32B → 带宽浪费 32×；且这是 api-datacopy.md 明令「仅调试」的标量路径在**大规模生产路径**上使用。

**anchor 的 remediation 给了两条路**：
- 路 A：降 F（按 32B 窗口重推 UB 预算）——治标，保留逐元素方案，只绕 UB 预算。
- 路 B：**「改用不依赖逐元素标量事务的 gather 路径（按 32B 对齐窗口整块搬入 + UB 内 Gather/掩码提取）」**——治本，向量化 gather。
- 落地只采纳 A + 固定 slot（逐元素搬到固定 32B slot 再标量移到目标），**未采纳 B**。所以「逐元素搬运」方案根本没变，只是绕开了「dst 对齐」「UB 预算」两个硬约束。

**后果**：2 个残余 DataCopyPad 问题携带到 precision 18/20 fail（Q13）。

**平台差异与架构认知修正（§1.9 / §1.12，两处都要准确）**：
- **先纠正一个常识错误（上版表述有误）**：「src 须经 UB」**不是** Gather 的特例或缺陷，而是 A2/A3 Vector 模型下**所有矢量计算 API 的通用前置**——数据链路是 GM → 搬运 API（DataCopy 等）→ UB → 矢量计算 API → UB → CopyOut → GM。例外只有两类：搬运 API（直接 GM↔UB）与 A5 SIMT 的 Reg 操作。设计时「数据经 UB 做矢量计算」是默认前提，**绝不会把「经 UB」当特例处理**。
- **Gather 在本例被排除的真因是数据量/UB 预算，不是「src 须 UB」**：本例「8 邻域」索引地址跨 D/H/W 维（d 与 d+1 相隔一整行/整平面），要对「能覆盖全部 8 邻域」的源范围直接 gather，需把大范围输入常驻 UB（整平面 128KB+ 超 UB 预算，anchor 已查证）。这是「gather 范围放不进 UB」的**数据量问题**，与任何大张量算子要分块 tiling 是同一类问题，非 Gather 特有。A2/A3 的 `Gather`（ISASI）支持 fp16/fp32，本身可用；`Gatherb`（仅 uint16/uint32）、`GatherMask`（仅固定间隔）则因粒度/间隔限制不适合本例。
- **「自己封装」≠「绕开 Gather 的特例」**：它就是标准的「分块搬入 + UB 内偏移索引」——向量化 DataCopy 把输入按 tile 搬进 UB，再用掩码/移位等基础原语在 UB 内做 8 邻域偏移提取；分块后的小范围也可用 `Gather`。
- **A5（950，Regbase/SIMT 模型）**：有 `Gather`（srcReg 寄存器为源）+ `GatherB`，寄存器间接寻址对 scatter/gather 类随机访问更友好——但这也只是「另一套编程模型的原语」，不是「A2/A3 缺了某个能力」。
- 因此「gather 建模范式」缺的**不是**「告诉设计 gather 要经 UB」（那是常识），而是**「按运行时索引间接寻址的算子，输入如何分块（沿哪维切、切多细）才能让跨维偏移的 8 邻域在 UB 分块内仍可正确索引 + 用基础原语实现偏移提取」**。具体分块粒度与掩码/移位组合仍需查证落实，但**方向确定**：GM 访问向量化整块、分块搬入，偏移索引放 UB 内用基础原语，绝不逐元素 GM→UB。

**结论（对 Q14/R3 的修正）**：
- 「单元素搬运」对这个算子**不是合法需求，是建模错误**。Q14 说「新建单元素搬运最佳实践」是**治标**——它默认了「单元素搬运合法」，教「怎么做对」。
- 真正该新建的是 **「间接索引 gather 建模范式」最佳实践**（优先级高于「单元素搬运」）：正面讲「按运行时索引间接寻址采样的算子（输出每元素 = 输入里若干非连续位置的加权组合）的正确分解 = 向量化整块 DataCopy + UB 内掩码/移位封装（A2/A3）或 Reg 为源 Gather（A5），禁止逐元素 GM→UB 单元素事务」。此主题按**结构特征**定义（§1.12），不绑定任何具体算子名。
- 「单元素搬运最佳实践」仍保留，但**定位降级**为「覆盖 offset 表等确实需标量写的小规模合法场景」，并**明确把『大规模逐元素 gather』排除在外**，指到「gather 建模范式」。
- 普适工程判断：**AC2 的表面是「DataCopyPad 约束没算对」（API 层），根因是「gather 被错误建模为逐元素搬运」（方案层）**。修 API 知识只能让「逐元素搬运」不崩，修建模范式才能让「gather」一开始就不走错路。

> 「gather」知识的**分层落地 + 波及面**已落 L4 `03-gather-paradigm-skill-draft.md`：API 用法层 → `.claude/skills/ascendc-api-best-practices/references/api-gather.md`，概要设计模式层 → `G01_gather-vector.md`（补「采样/插值」变体——现有 G01 语料缺坐标采样类）；**波及 `knowledge_policy.md` 的「骨架级 API 强制查证门」优先级调整**（先 best-practices → 再 Tier 3，这是 AC2 查证门「查了签名没查用法坑」的深层根因），含跨算子验证记录。

### Q16 — 字段漂移反复发生的系统根因（不限于 AC3）

**现象**：`_extract_shared_summary` 提取白名单字段名反复漂移——P135 修了 `tiling_key` 死字段，本批又发现 `tiling_data_fields/workspace/dtype/buffer_allocation` 4 个死字段。用户指出「类似问题做过多次分析还是反复出现」，说明是**系统性根因**，非「一个个字段修」能了结。

**系统根因：anchor-consistency 的「跨模板一致性判定」是越界查上游（§2.9 违反）**：
- 它查的 3 个维度都归**上游单一作者**：TilingKey 归 `template_division`（`templates[].tiling_key` + `route_condition`）、workspace 归 `buffer_kernel`（可选字段）、dtype 路由归 `template_division` 的 `route_condition`。
- 这些「一致性」本可由「**单一作者 + 下游忠实消费**」构造性保证（§2.9 构造性保证优先），**不需要下游跨模板门查**。
- 门为查它们，手工维护「字段名白名单」提取上游字段 → 跟上游 schema 演进**漂移** → 提取恒空 → AC3 `unverified` 噪音。
- **P135 只修了「tiling_key 一个字段」，没修「越界查」这个设计本身**，所以其他字段继续漂移。

**证据（代码层与 skill 层不一致）**：`ascendc-op-design-anchor-consistency/SKILL.md` §3 仍在查「TilingKey 定义一致性 / Workspace 分配不重叠 / Dtype 路由表一致性」，但 `_extract_shared_summary` 的 docstring 已写「路由一致性由『单作者 + 下游忠实消费』构造性保证（§2.9），不在此门重复检查（门不越界查上游 template_division 的产物）」——**代码层（P135）移除了 tiling_key，skill 层（SKILL.md §3）没跟上**。

**彻底解决（符合 §2.9「构造性保证优先 + 门不越界查上游」）**：
1. **删除「跨模板一致性判定」（AC3 跨模板 tiling 类）**：TilingKey/workspace/dtype 一致性由「单一作者 + 下游忠实消费」构造性保证；下游违反契约由「下游产出校验」（tiling 段产出时校验与 template_division 一致）承担，非跨模板门。
2. **AC0 骨架级 API 判定改从算子语义源头**：SKILL.md §1 当前「从 `tiling_shared_summary` 判定算子是否含骨架级 API」也是判定来源漂移——「骨架级 API」是算子语义事实，归 general_design（LP 分类）/golden 单一作者，不从 tiling 段产物摘要判定。
3. **删除 `_extract_shared_summary` + `tiling_shared_summary` 提取**：耦合点消失，字段漂移不再发生。anchor-consistency 只保留「汇总 per-template 报告」（§2），输入仅 `anchor_template_reports`。

**附带发现**：AC0 的「骨架级 API」判定（SKILL.md §1）是第二个「判定来源漂移」——「骨架级 API」是算子语义事实，但当前从 tiling 段产物摘要判定，而 tiling 段根本不记录「算子是否含骨架级 API」（它记录 axis/tile 等）。
