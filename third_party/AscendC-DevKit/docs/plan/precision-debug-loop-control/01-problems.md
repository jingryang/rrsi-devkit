# precision_debug 闭环控制 — L1 问题记录（2026-07-18）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/根因/影响）。
> **不提方案、不排顺序、不写决策**。方案分析见 `02-analysis.md`（L3）；实施方案见 `03-impl-*.md`（L4）。
> 纪律：遵守 `plan-doc-discipline`——语义锚点（函数/类/字段/机制名），**不写 file:line**；代码定位用语义，日志作为本次运行快照可引用行号。

## 本次运行的证据来源

- **算子**：`ai_infra_moe_init_routing_v3`（MOE Init Routing，AscendC，A2/ascend910b）
- **编排轨迹日志**：`<repo>/log.log`（8092 行，skill 编排器执行轨迹）
- **闭环权威状态**：`<op_dir>/.precision-fix/control.json`（1984 行）+ `report.json`（435 行）+ 各 phase 产物 `precision_diagnose.json` / `precision_fix.json` / `precision_printf.json` / `scope_verdict.json`
- **运行特征**：从 `run_tests` 起步，进入 `diagnose → fix → printf_location → scope_guard` 循环，共 8 轮；末尾 `scope_guard` 以 `[aborted]` 结束，伴随 `[ERROR] Timeout: Workflow timeout: exceeded 20000s budget (ran 20165.4s)`——即**闭环未自我收敛，由 workflow 20000s 硬预算强制终止**。
- **终态 best_***：`best_commit == initial_commit`、`best_max_err == 999.0`、`best_failed_count == 19`（11+ 轮无任何改善记录）。

> 下文 P1 为总体表现，P2–P8 为导致该表现的具体机制缺陷，P9 为架构层根因。严重度标注的是**影响严重度**（非修复顺序，顺序属 L2）。

---

## P1（严重）：precision_debug 闭环不自我收敛，仅靠 workflow 超时终止

### 证据

- `log.log` 末尾：`scope_guard/scope_guard done (0.0s) [aborted]` + `Timeout: Workflow timeout: exceeded 20000s budget (ran 20165.4s)`。
- 8 轮 `diagnose → fix → printf_location → scope_guard`，每轮 `stage_iteration ... done` 均正常返回，没有任何一轮触发 `exhausted` / `__halt__` / `upstream` 等收敛出口。
- `control.json` 终态：`best_commit == initial_commit`、`best_max_err == 999.0`、`best_failed_count == 19`；`report.json` 逐轮 `problem/solution/result` 显示多轮诊断结论与候选修复高度雷同。
- 失败的本质并非「精度数值不达标」，而是 20/20 用例在 kernel 执行阶段统一崩溃（`aicore exception 507015` / `DDR MTE address out of range`，`diff=999.0, elapsed_ms=-1.0`），连数值都未产出——即问题被塞进 `precision_debug` 闭环后，闭环在「运行时崩溃」上空转，从未触达真正的精度语义比对。

### 根因

- 闭环内部**缺少基于「进展」的收敛判定**（详见 P2/P4/P9）；唯一的语义收敛出口 `rounds > max_iterations` 在实际空转路径上失效（详见 P2），唯一兜底是刻意设高的 corrective quota（详见 P2），最终只能靠 workflow 层硬超时收场。

### 影响

- 单算子浪费约 5.6 小时算力，问题未解决。
- 该模式对任何「修复引入 universal 回归」或「case 卡死」的算子都会复现——非偶发。

---

## P2（严重）：fix↔printf 小循环不推进 `rounds`，语义收敛锚点失效

### 证据

- `rounds` 计数器**只在 `RunTestsSubstage.transition` 中递增**；`FixSubstage.transition` 与 `PrintfLocateSubstage.transition` 仅 `.get("rounds", 0)` 透传，不自增。
- `precision_debug_tree.py` 的 scoped transition_table 中，`fix.need_printf → printf_location` 与 `printf_location.located → fix` 构成**无计数器的双向边**。
- 同文件的 `_PRECISION_DEBUG_MAX_CORRECTIVE`（=200）上方注释明确写出设计假设：*「semantic loop bound is the framework-side round counter (RunTestsSubstage.transition increments it; rounds > checkpoint.max_iterations → escalate exhausted). Set well above max_rounds so the framework quota never silently preempts the sub-stage's exhaustion signal.」*——即设计者**假设闭环会频繁回到 `run_tests`**（经 `fix.resolved` / `skip_done` / `printf_done`），从而 `rounds` 稳步推进。

### 根因

- 实际空转路径 `fix → need_printf → printf_location → located → fix` **完全不经过 `run_tests`**，设计假设的「`rounds` 随循环推进」在该路径上不成立。
- 后果链：`rounds` 不增 → `rounds > max_iterations`（默认 30）永不触发 → 设计上刻意高于 `max_rounds` 的 `MAX_CORRECTIVE=200` 成为**唯一**内部兜底，而它大到要跑数小时才触发。

### 影响

- 闭环一旦进入 fix↔printf 小循环，语义收敛（`max_iterations`）与配额兜底（`MAX_CORRECTIVE`）**两道防线都失守**，只能靠 workflow 超时——这正是 P1「5.6h 空转」的直接机制。

---

## P3（严重）：case 推进死锁——precision case 顶死队头，runtime case 永不轮到

### 证据

- `control.json` 全程 `current_case_index` 停在 case 2（`failure_type=precision`，`status=resolved_pending`，`attempt_count=11 > max_attempts_per_case=10`）；其余 19 个 runtime case 的 `attempt_count` 全程为 0。
- `log.log` 中 `agent_spawn` 分布：`ascendc-precision-diagnose` / `fix` / `printf-locate` 各 10 次、`scope-guard` 9 次——全部围绕同一 case。

### 根因（双因子）

- **框架层**：`FixSubstage.transition` 的 case 推进块被外层守卫 `case.status not in ("resolved", "resolved_pending")` 屏蔽——一旦 case 被标 `resolved_pending`，整个推进块（含 `attempt_count >= max_attempts` 的 stop-loss）跳过；且推进的另一条件 `pool_done and ftype in ("compilation", "runtime")` 对 `precision` 类型**永假**。
- **skill 脚本层**：`build-failed-case-queue.py` 的 `merge_with_existing` 在 run_tests 全量回归后重建队列时，**无条件 preserve 旧 `status`**（含 `resolved_pending`）——即便本轮 `result.json` 明确显示该 case 仍失败，也不回退为 `pending`。
- **状态升级缺失**：`_case_marked_resolved` 把 `resolved` 与 `resolved_pending` 一视同仁（路由等价），但代码中**没有任何位置把 `resolved_pending` 升级为 `resolved`**——run_tests 全量通过时也不写 per-case `resolved`。

### 影响

- case 2 单点死磕，19 个 runtime case 群体永远等不到 fix。
- `resolved_pending` 成为「假阳性粘滞态」：单用例通过的临时标记一旦写上，全量回归证伪也无法清除。

---

## P4（严重）：`best_*` 指标模型失效——进展不可见、回归不可见

### 证据

- `control.json` 终态 `best_commit == initial_commit`、`best_max_err == 999.0`，11+ 轮无更新。
- `best_*` 的比较与更新逻辑**位于 `run_tests` skill 的 prompt 模板**（`_better()` 函数），**框架 transition 完全不碰**；框架侧 `_extract_debug_checkpoint` 只透传 `best_*`，`_sync_debug_result` 仅把它物化进终态 `PrecisionDebugResult.max_diff`。

### 根因（三个独立缺陷）

1. **`best_commit` 写死为 `initial_commit`**：`run_tests` skill prompt 的 best_* 更新段中，`cp["best_commit"] = cp.get("initial_commit")`——注释声称「若是 git 仓且本轮有新 commit，取当前 HEAD」，但**代码未实际取 HEAD**，无条件回填 `initial_commit`。
2. **`best_*` 判据是单标量字典序 `(failed_count, max_err)`**：run-level `max_err` 取所有 case 的 `MAX`。只要存在一个 runtime crash（`max_err=999.0` 哨兵），聚合即被钉死 999.0；精度 case 即便从 4056.0 改善到 1e-6 也被 `max(999.0, 1e-6)=999.0` 完全掩盖。
3. **999.0 哨兵无特殊处理**：全仓 grep 不到 `sentinel` / `crash_err` / `is_crash` 类判定；999.0 作为普通数值参与 `<` 比较——会导致「全崩（20×999，聚合 999.0）」假装比「1 precision(4056) + 19 crash（聚合 4056.0）」**更好**（999 < 4056）。999.0 的注入点全部在 `runner.py` 的子进程级/单 case 级 fallback。

### 影响

- 调度层与报告层均被 999.0 污染：无法识别「部分改善」或「回归」，无法据此提前停机/换策略/回滚。
- 终态 `PrecisionDebugResult.max_diff` 上报 999.0，把任何部分进展抹成「零进展」。

---

## P5（中等）：`candidate_loop` budget 单调递增不复位，新 fixplan 永不被验证

### 证据

- `control.json` 中 `candidate_loop.current_tried` 单调递增到 ≥ `max_plans`(=10)；多轮 `fix` 的 outcome 为 `FIX_NEED_BISECT`，随后 `printf_location` 产出新 fixplan 入池，下一轮 `fix` 仍是 `FIX_NEED_BISECT`。
- `report.json` 中可见多个由 printf bisect 产生、`verified=pending` 但始终未被验证的 fixplan。

### 根因

- `_candidate_pool_exhausted` 使用**绝对计数** `current_tried >= max_plans`，且 `current_tried` 只增不减。
- `current_tried` 的自增只发生在 `fix` skill 的内部循环；**`printf_location` 新增 fixplan 入池时不复位 `current_tried`**（`gate3-printf-bisect` 只往 `candidate_pool.hits` 追加，不碰 `candidate_loop`）。
- `fix` skill 内部循环的 `while` 条件 `current_tried < max_plans` 在 budget 已耗尽时直接为 False——新入池的 fixplan 一进就被跳过，**永远不会被验证**。

### 影响

- `fix → need_printf → located → fix` 死循环：printf 产出的修复方案永远不被消费，却持续占用闭环轮次。

---

## P6（中等）：`candidate_pool` 无去重，同一 bug 被克隆成多个 fixplan

### 证据

- `report.json` / `control.json` 中 `fixplan-017 / 018 / 019 / 020 / 021` 本质是同一个两行 `if/else` 分支交换（`ProcessReductionT2` 的 flag/type 优先级），却作为 5 个独立 plan 存在，各自被 refute。

### 根因

- `_candidate_pool_exhausted` 只统计 `verified == "pending"` 的数量，对 hits 的**内容零检查**。
- `fix` skill 的 `tried_fixes` 仅在**单次执行内**按自然语言 `fix_desc` 软去重——跨轮无效，且 key 是可变措辞（换种说法即绕过）。
- `candidate_pool` 的写入由 `diagnose` / `fix` / `printf_location` 各 agent 自主决定（混合切分协议），框架为「被动消费者」，照单全收。

### 影响

- 同一改动反复入池、反复 refute，耗尽 budget 并制造「有进展」的错觉。

---

## P7（中等）：`scope_guard` 一次性首轮流，无重判、无收敛出口

### 证据

- `log.log` 中 `scope_guard` 多次执行，每轮 `scope_verdict=pass`、`scope_reason` 文案逐字相同（均为「All 20 cases universal 507015 / 19 runtime + 1 precision / firmly within precision_debug scope」）。

### 根因

- `RunTestsSubstage.resolve_condition` 的 scope 门控是 `if not scope_checked`——**一次性**；`scope_checked` 一旦写入，后续不再路由回 `scope_guard`。
- `ScopeGuardSubstage.resolve_condition` 只有 `upstream` / `pass` 两个出口；`scope_verdict` 为异常值或空时落入 `return "pass"` 兜底分支，**无 contract 校验**。
- 无「连续 N 轮 has_failures 且 verdict=pass」就重判、或「无进展」就 reconsider 的机制。

### 影响

- 首轮误判 `pass` 后永不重审——尤其对「修复新引入的 universal 回归」这类**运行中才出现的上游性质变化**完全盲眼。

---

## P8（中等）：`printf_location` deploy 失败无框架感知，退化代码分析仍继续循环

### 证据

- `report.json` 后期 `printf_location` 条目：*「Deploy infrastructure broken (profile=null) — 4 recovery approaches exhausted (cmake rebuild+copy, state fix, direct Python, cmake install). Fell back to CODE ANALYSIS + extensive history」*，仍标记 `printf_location_result=located` 并产出新 fixplan。

### 根因

- `PrintfLocateSubstage.resolve_condition` 末尾 `return "continue"` 是**兜底黑洞**：deploy 失败、`profile=null`、build 崩溃、agent 自行 fallback 到纯静态分析，**全部**被当作「继续二分」。
- `PrintfLocateSubstage.transition` 只检查 `printf_location_result == "exhausted"` 一个条件，**不提取任何 deploy 健康度字段**。
- `_extract_debug_checkpoint` 不把 deploy 状态读进 checkpoint。

### 影响

- printf 阶段失去运行时证据能力后仍持续产出「定位结论」，`fix` 据此验证**无运行时证据支撑的 plan**，大概率 refute，又回 printf——同态 deploy 失败下无限循环。

---

## P9（架构 / 根因）：闭环状态机不变式的维护散落于 skill prompt 与脚本，框架被动消费

### 证据

- `best_*` 的更新逻辑在 `run_tests` skill 的 prompt 模板（`_better()`）；`failed_case_queue` 的 `status` preserve 与 merge 在 `build-failed-case-queue.py`；`candidate_loop.current_tried` 的自增在 `fix` skill 的 prompt；`control.json` 的 schema 形状校验在 `_assert_control_contract`。
- 框架侧 5 个子 stage 的 `transition` 职责统一为「读 cp → 物化 `_debug_checkpoint` → 写 history」，**不持有任何状态机不变式**。

### 根因

- 闭环的核心不变式——`best_*` 单调改善、`resolved` 只升不降、`candidate_loop` 一致性、`resolved_pending` 假阳性可回退——其**实现权分散在多个 skill 的 prompt 模板与脚本中**，由非确定性的 LLM agent 在执行 prompt 时维护；框架仅被动消费 agent 写回的 `control.json`。

### 影响

- 不变式无法被保证，agent 执行 prompt 时的实现偏差直接成为线上 bug：`best_commit` 写错（P4）、`merge_with_existing` 无条件 preserve（P3）、`current_tried` 不复位（P5）均属此类。
- 框架层无法识别「闭环在空转」，只能靠纯计数兜底（`rounds` / `MAX_CORRECTIVE`），而这些计数本身又存在 P2 的失效路径。
- 与 CLAUDE.md §1.1（Event Sourcing，状态权威在框架）+ §2.5（唯一通路，不留旧债）存在张力：权威状态的更新通路目前是多条的（散落于各 skill），而非框架单一持有。

---

---

## P10（严重）：control.json 部分写入——agent 幻视新建 dict 覆盖全部字段 → `PrecisionDebugContractError` halt

### 证据

- `log2.log` 第 50–52 行：`[WARN] [PD-CONTRACT] control.json missing 14 required key(s)...Auto-initializing` + `[aborted]` + `[ERROR] Stage 'run_tests' failed: name '_write_json_atomic' is not defined`
- control.json 在 `init-checkpoint.py` 初始化时写入了全部 20 个 required key；run_tests agent 执行后只剩 7 个 key（丢失 13 个）
- 丢失的 key 包括 `debug_state`、`failed_case_queue`、`current_case_index`、`candidate_pool`、`best_*`、`rounds` 等框架路由与状态追踪所需的核心字段

### 根因

- `RunTestsSubstage._phase_prompt` 中 run_tests agent 的读写契约写为「更新 control.json：status / failed_case_queue / best_commit / best_max_err / best_failed_count」
- agent 按字面理解 → 新建一个只包含这 5 个 key 的 dict → `json.dump` 写回 → **覆盖**了 init-checkpoint.py 初始化的全部其他字段
- prompt 未强调「先 json.load 整个文件 → 只修改上述 key → json.dump 写回」的原子 read→modify→write 模式

### 影响

- control.json 丢失核心路由字段 → 框架 `_assert_control_contract` 检测到 missing required keys → 抛 `PrecisionDebugContractError` → pipeline halt
- 即便不 halt，`debug_state` 丢失也会导致下一 stage 无法路由（`resolve_condition` 读不到 debug_state → 默认路由错误 → 闭环瘫痪）

### 性质

Agent prompt 指令歧义 + 框架缺少对 partial write 的容错兜底。

---

## P11（严重）：schema/contract validation 一律 fatal halt——对模型幻视零容错

### 证据

- P10 的 control.json missing keys 触发 `_assert_control_contract` → `PrecisionDebugContractError` → pipeline halt
- P13 的 `precision_printf.json` missing `tried_bisect_paths` 触发 `_validate_phase_json` → `PrecisionDebugContractError` → pipeline halt
- 两处 halt 的根因都是 **agent 未按要求写全字段**（prompt 歧义或遗漏），而非数据确实损坏到不可恢复

### 根因

- `_assert_control_contract(cp)` 对 **所有** schema 违规（missing keys、forbidden keys、type mismatch）统一 raise——不区分「可安全修复」（missing key → 填默认值）与「真正损坏」（forbidden D3 stale keys）
- `_validate_phase_json` 同样：phase JSON 缺一个 required key 就直接 raise，不尝试 auto-fill 安全默认值后继续
- 设计假设是「agent 产出永远符合 schema」，未考虑 LLM 非确定性导致的合规偏差

### 影响

- 任何 agent 的一次 prompt 理解偏差 → pipeline 立刻终止，无自愈能力
- 与 §1.2「方案合理性优先」矛盾：修复 prompt 能解决下一次，但无法防止下一次**不同**的幻视；框架层不兜底 = 健壮性靠运气
- 与 §1.8「加载期校验优于运行期暴露」一致方向但实现过度——校验后应分类处理（可修复 → auto-fill + warn；不可修复 → raise），而非一刀切 raise

### 性质

框架 contract 校验缺少分层容错——将「可安全修复的合规偏差」与「真正数据损坏」同等对待。

---

## P12（中等）：A 级 printf 验证「refuted」误判——缺少入口活体探针区分「printf 不生效」与「探针未到达」

### 证据

- A 级 printf 验证流程（`ascendc-precision-fix` skill）：在 kernel 中插入 FIX_BEFORE / FIX_AFTER 两个探针 → compile + run → grep 输出
- 判定逻辑：FIX_BEFORE 未输出 → refuted（崩溃在目标行之前）；FIX_BEFORE 输出 + FIX_AFTER 未输出 → confirmed
- 但 **grep 不到任何输出** 存在两种可能：(a) printf 本身不生效（日志未开启 / 编译优化移除 / 输出重定向）；(b) 探针所在代码路径未执行（真正的 refuted）
- 原流程无法区分 (a) 和 (b)，一律判 refuted——可能把「printf 环境问题」误判为「修复无效」

### 根因

- 缺少一个**独立于业务逻辑的活体探针**来验证 printf 环境本身是否工作
- 判定矩阵缺少维度：`printf 环境是否正常` 是 FIX_BEFORE/AFTER 判定的前置条件

### 影响

- 「printf 不生效」被错误归因为「修复无效」→ fix agent 放弃有效的修复方案 → 增加无效闭环轮次
- 尤其影响首次使用 printf 验证的场景（环境配置问题概率高）

### 性质

判定矩阵缺维——前置条件未验证即进入业务判定，导致误判类别混淆。

---

## P13（严重）：`precision_printf.json` 缺失 `tried_bisect_paths` → contract halt

### 证据

- `log2.log` 第 704–707 行：`[ERROR] Stage 'printf_location' failed: [PD-CONTRACT] precision_printf.json failed schema validation: precision_printf.json: missing required key 'tried_bisect_paths'` → `fail_strategy=halt` → pipeline 终止
- `precision_printf.json` 的 schema（`ascendc-precision-printf/schema/precision_printf.json`）声明 `tried_bisect_paths` 为 required key
- printf_location agent prompt（`ascendc-precision-printf-locate.md`）只在 **exhausted 分支**提到此字段：「Archive this decomposition path into precision_printf.json.tried_bisect_paths」
- **fresh** 和 **bisecting** 分支均未提及此字段 → agent 初始化（fresh）和续探（bisecting）时都不写 `tried_bisect_paths`

### 根因

- Schema 要求字段**始终存在**（所有分支），但 agent prompt 只在单分支（exhausted）提到——fresh/bisecting 分支 agent 不知道要写
- `_validate_phase_json` 对该违规直接 raise（同 P11），无 auto-fill 兜底

### 影响

- printf_location 首轮（fresh）直接 contract halt → 闭环无法进入 bisect → 精度定位能力完全失效
- 与 P10/P11 同模式：prompt 覆盖不全 + 框架零容错 = pipeline 阻断

### 性质

Agent prompt 分支覆盖不全（schema required key 未在全部 state 分支写入）+ 框架 contract 校验零容错。

---

## 问题汇总矩阵

| 问题 | 影响严重度 | 性质 | 核心锚点 |
|------|-----------|------|---------|
| P1 闭环不收敛，靠 workflow 超时终止 | 严重 | 总体表现 | `log.log` timeout / `best_*` 终值 |
| P2 fix↔printf 不推进 `rounds`，语义收敛锚点失效 | 严重 | 机制缺失 | `RunTestsSubstage.transition` 独占 `rounds` 递增；transition_table 双向边无计数 |
| P3 case 推进死锁（precision 顶死队头 + resolved_pending 假阳性不回退） | 严重 | 机制缺失 + 状态升级缺失 | `FixSubstage.transition` status 守卫；`merge_with_existing` 无条件 preserve status |
| P4 `best_*` 指标模型失效（进展/回归均不可见） | 严重 | 实现 bug + 模型缺陷 | `run_tests` skill prompt 的 `_better()` / best_commit 写死 / 999.0 哨兵无处理 |
| P5 `candidate_loop` budget 单调不复位 | 中等 | 机制缺失 | `_candidate_pool_exhausted` 绝对计数；printf 入池不复位 |
| P6 `candidate_pool` 无去重 | 中等 | 机制缺失 | `_candidate_pool_exhausted` 只数 pending；`tried_fixes` 软去重可绕过 |
| P7 `scope_guard` 一次性首轮流 | 中等 | 机制缺失 | `resolve_condition` scope 门控一次性；verdict 无 contract 校验 |
| P8 `printf_location` deploy 失败无感知 | 中等 | 机制缺失 | `resolve_condition` `return continue` 黑洞；无 deploy 健康度字段 |
| P9 不变式维护散落于 skill，框架被动消费 | 严重（架构） | 架构根因 | `best_*`/`merge`/`current_tried` 更新散落 prompt 与脚本 |
| P10 control.json 部分写入（agent 幻视新建 dict 覆盖全部字段） | 严重 | agent prompt 歧义 + 框架无容错兜底 | `RunTestsSubstage._phase_prompt` 读写契约不明确；agent 新建 dict 覆盖 init-checkpoint 产物 |
| P11 schema/contract validation 一律 fatal halt——对模型幻视零容错 | 严重 | 框架校验缺分层容错 | `_assert_control_contract` / `_validate_phase_json` 对所有违规统一 raise |
| P12 A 级 printf 验证缺少入口活体探针——「printf 不生效」误判为「refuted」 | 中等 | 判定矩阵缺维 | `ascendc-precision-fix` A 级验证流程只有 FIX_BEFORE/AFTER 两探针 |
| P13 `precision_printf.json` 缺失 `tried_bisect_paths` → contract halt | 严重 | agent prompt 分支覆盖不全 + 框架零容错 | printf_location agent prompt 只在 exhausted 分支写 `tried_bisect_paths`；schema 要求所有分支必填 |

---

## 证据索引

| 证据 | 来源（语义锚点） |
|------|-----------------|
| workflow 20000s 超时终止、scope_guard `[aborted]` | `log.log` 末尾 |
| 8 轮 diagnose→fix→printf→scope_guard 循环、各 agent spawn 次数 | `log.log` stage_iteration / agent_spawn 全文 |
| best_* 终值（=initial / 999.0 / 19）、current_case_index 停滞、attempt_count 分布 | `control.json` |
| 逐轮 problem/solution/result、printf deploy fallback、fixplan 克隆 | `report.json` |
| `rounds` 仅 RunTestsSubstage 递增；transition_table 双向边；MAX_CORRECTIVE 注释假设 | `precision_debug_tree.py`、`precision_debug_substages.py` |
| best_* 更新在 skill prompt、best_commit 写死 initial、`_better()` 字典序 | `ascendc-precision-run-tests` skill（prompt + `init-checkpoint.py` + `build-failed-case-queue.py`） |
| current_tried 自增/不复位、单用例验证禁全量、tried_fixes 软去重 | `ascendc-precision-fix` skill prompt |
| printf 入池不复位 budget、deploy 无兜底 | `ascendc-precision-printf` skill（`gate3-printf-bisect`） |
| 999.0 哨兵注入点、全仓无 sentinel 处理 | `adapters/npu/runner.py` |
| control.json 14 missing keys auto-initializing + `_write_json_atomic` 未定义 | `log2.log` 第 50–52 行 |
| precision_printf.json missing required key tried_bisect_paths → halt | `log2.log` 第 704–707 行 |
| A 级 printf 验证流程（FIX_BEFORE/AFTER 双探针判定表） | `ascendc-precision-fix` skill（SKILL.md + `references/prompts/fix.md`） |
| printf_location agent prompt fresh/bisecting 分支未写 tried_bisect_paths | `agents/ascendc-precision-printf-locate.md` 第 49、59 行 |
| `_assert_control_contract` 实现（统一 raise，无分层） | `precision_debug_substages.py` |
| `_validate_phase_json` schema 违规直接 raise | `precision_debug_substages.py` |
| precision_printf.json schema required_keys 声明 | `ascendc-precision-printf/schema/precision_printf.json` |

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-18 | 初版：基于 `ai_infra_moe_init_routing_v3` 一次完整运行（`log.log` + `.precision-fix/`）记录 P1–P9。P1 为总体表现，P2–P8 为具体机制缺陷，P9 为架构层根因。仅陈述事实，不含方案。 |
| 2026-07-18 | **追加 P10–P13**：基于 `log2.log` 二次运行发现的 contract/schema validation 层问题——control.json 部分写入（agent 幻视）、schema 验证 fatal halt 无容错、A 级 printf 验证缺少活体探针、phase JSON 缺失 required key。与 P1–P9（loop control 层）正交但同属 precision_debug 子系统。 |
