# precision_debug 收尾交付修复前代码 — L3 方案分析 v8（2026-09-04 修订）

> 层级：**L3 / 方案分析**。记录选项取舍与理由。**状态：待用户评审——评审通过后冻结，L4 另立。**
> 输入：`01-problems.md`（L1，F1-F13）。
>
> **v8 修订说明**（响应用户「机械做法会不会降容错」——确认会，撤回 v7 一处真缺陷）：
> v7 的「最优 = 测量史 argmax，**平局取最新**」**降低**了旧机制容错：旧 `_update_best_metrics` 是「严格大于
> 才更新、相等保留更早最优」的**刻意反向保护**（防 diagnose 改到一半、通过数没变但代码更差时，把差代码当
> best 交付）。v8 撤 latest-on-tie。
> 更关键的发现：**A3 循环「一次全量全过 → status=passed → 立即退出」**（substages:2221→:2348）——**同一会话
> 不会出现「两个都全过的 commit」**。故全过退出路径根本不需要 argmax/best_commit/tie-break：要交付的就是
> 「框架最近一次全过测量的被测 identity」，由退出条件构造性保证。事故恰是 passed 退出却用了被污染字段
> （549ba00），而非「框架最后一次全过测量 = iter-2 = b760254」。**全过路径直接交付最近全过测量的 identity，
> 字段污染无关——比删字段更彻底，连 argmax 都不需要。**
> v8 改为**双路径**：全过退出 → 用最近全过测量的 identity（无 tie-break）；非全过退出（timeout/exhausted/
> upstream）→ 才从测量史 argmax，**平局保留较早**（复现旧反向保护）。A5 专有机制不动（承 v7 边界）。

## 溯源注记（一句话，供后人不再踩）

1. **判据同源**：曾疑「debug 与 cann-bench 判据不一致」→ 查证误读一个外层显示字段——cann-bench 场景
   debug harness import **同一个** `compare_tensors`，golden fp64_cpu / eval_seed / proto 阈值与 eval 对齐，
   同源同函数，不存在两把尺。本事故与判据无关。
2. **best_commit 来源（用户质询「靠模型还是靠 Python」查证）**：A3 的 `_snapshot_best_commit` 是**纯 git
   探测**（`git rev-parse HEAD`，substages.py:1093），**不读 commit message、不由模型写**。A5 的 best_snapshot
   .commit 是**模型报告**（skill 写 `<commit hash>`、框架 phase_result.get 照单全收，precision_debug_a5.py:272），
   **无 Python 侧兜底**——A5 同源风险。A3 侧无「模型不遵守 message 约定」问题，因 A3 从不读 message。
   新方案全过路径交付「框架最近全过测量的 source_identity」（B），**模型彻底无法影响交付选择**。

## 问题本质

收尾（converge，正常退出路径）「交付哪个 commit」的锚点判定依赖**可被 agent 写入的共享字段** + **测后
HEAD 的时序巧合** + **callable smoke 的无质量信号**，三者叠加使 converge 在 debug 已验证修复后代码的
情况下，仍回滚并交付了修复前代码（L1 F6/F8）。用户拍板方向：**不搬家 control.json**（治 obscurity，root
藏不住、成本高），**保证 A3 正确性优先**——让任何 agent 写入对 A3 的最优判定无影响（删 A3 字段而非禁写），
交付物自带可验证来源，converge 只交付验证过的版本。teardown / resume 保持现状。**A5 专有机制不动。**

## 方案不变式

1. **A3 最优版本判定只信框架的测量史**——A3 的 `best_*` 字段删除，agent 无字段可写。
2. **每个交付物带来源标识（含脏指纹）**——deploy→source_identity、run_tests 记录被测 identity、eval 报告记被测 identity。
3. **converge 只交付「验证过」的版本，按退出路径分道**：全过退出 → 交付「框架最近一次全过测量的被测
   identity」（不读字段、无 argmax/tie-break）；非全过退出 → 从测量史 argmax（平局保留较早）。`_converge_
   to_best_commit` 实为纯 A3（A5 不调用、有独立 _a5_sync_debug_result），可直接改其从测量史现算。

## 方案明细（A–E）

> 每项附触发判据：**删掉它，本事故（L1 F 链）或同族是否复现**。全部基于实证，不再扩展未证实的问题。

### A. 删除 A3 `best_*` 字段；交付物按退出路径分道（修 F6/F9/F3 根子）

- **删除 control.json 的 `best_commit` / `best_passed_count` / `best_failed_count` / `best_crashed_count` /
  `best_real_max_err` / `best_total_count`。** agent 看不到、写不到——F3 的「尽责同步」触发源直接消失。
- 测量记录 = 现 history 的 run_tests 条目**增强**：每轮全量回归已 append 一条（`test_result` /
  `failed_count` / `total_count`），补充**被测 source_identity**（框架写，值来自 B 的 deploy stamp）。
  history 框架独占写、agent 禁写（本次实证 agent 遵守了 history 禁写），是可信测量史。
- **交付路径一（全过退出——本次事故路径）**：A3 循环「一次全量全过 → status=passed → 立即退出」
  （substages:2221→:2348），同一会话**不会出现两个都全过的 commit**。故全过退出时 converge 交付
  「**框架最近一次全过测量的被测 identity**」（来自 history 最新一条 passed==total 记录的 source_identity）。
  **由退出条件构造性保证，不读字段、无 argmax、无 tie-break——字段污染无关**。本次事故正是 passed 退出却
  用了被污染 best_commit（549ba00），而非框架最后一次全过测量 = iter-2 = b760254。
- **交付路径二（非全过退出——timeout/exhausted/upstream）**：从测量史取「已测 passed 最大者」，
  **平局保留较早**（复现旧 `_update_best_metrics` 的「严格大于才更新」反向保护——防 diagnose 改到一半、
  通过数没变但代码更差时把差代码当 best 交付）。quality/report 渲染同样从测量史现算派生。
- **共享 converge 的供给（澄清：`_converge_to_best_commit` 实为纯 A3）**：查证 A5 的子 stage name
  （init_baseline/pipeline_sync/dump_debug/vf_test/finalize）≠ "precision_debug"，故 graph_executor 的
  `node.name=="precision_debug"` 收敛 hook 只命中 A3 group；A5 有独立的 `_a5_sync_debug_result`，**不调用**
  `_converge_to_best_commit`、不引用 substages 的 best_* 函数。故 `_converge_to_best_commit` 只服务 A3，
  A3 删字段后可**直接改它**从测量史现算，不必绕 dc 契约保 A5——A5 边界比早先假设更干净，A5 完全不受影响。
- **注（teardown 覆盖，不单独改动）**：teardown 中断回滚现读 `best_commit` 字段 → A3 侧改从测量史现算。
  语义、时机、成本（读测量史，微秒级）不变。teardown 本身不动。
- **dispatcher 不受影响**：`dispatcher.py:1137` 读的是 **debug_result.best_passed_count（产物）**，非
  control.json 字段——debug_result 由 `_sync_debug_result` 从测量史派生后照常携带该字段，dispatcher 零改动。
- **判据**：删 A → F6（读脏值比较）随字段消失而消失；F9（平局不快照）被双路径设计消除（全过退出无平局；
  非全过平局保留较早）；F3 触发源（可见的过期计数）消失。全过路径只靠 A（不读字段、交付最近全过测量）即
  不再回退好代码。
- **A 依赖 B（强耦合，不能单独落地）**：history 的 run_tests 条目带 `source_identity` 才能交付/现算最优，
  identity 来自 B 的 deploy stamp。A 必须与 B 同批实施。

### A0. 容错对照（回应「机械做法会不会降容错」）

| 维度 | 旧方案（可写 best_commit 字段） | v8（双路径 + 测量史派生） | 容错变化 |
|---|---|---|---|
| **全过退出交付** | 读 best_commit 字段（可污染 → 本次事故） | 交付「框架最近一次全过测量的 identity」（不读字段） | **提高**（事故根除，且不依赖删字段的 argmax） |
| **反向保护（防越改越差）** | 严格大于才更新，相等保留更早最优 | 非全过路径 argmax，平局保留较早（复现） | **不变**（v7 的 latest-on-tie 撤回） |
| **被测代码 vs 记录代码一致** | **不一致**（测后 rev-parse HEAD ≠ 被测代码，F6，交错时序下最脆弱） | 绑定「测量时 identity」（B） | **提高**（旧方案这里其实最脆弱） |
| 崩溃中断可回滚 | best_commit 持久值 | history 同样持久于 control.json | 不变 |
| 无测量 / 非 git | fallback HEAD / skip converge | 同样 fallback | 不变 |
| 模型影响交付 | 可写字段污染比较基线 | 全过路径无字段可读；非全过只读框架测量史 | **消除** |

结论：v8 **不是**用「机械派生」换掉「可写字段」然后变脆弱——它修掉了旧方案最脆弱处（测后 HEAD 记错身份），
且保留了反向保护与持久化容错。真正的降容错点（v7 的 latest-on-tie）已撤回。

### A0.1 对弱指令模型的鲁棒性 + 零轨迹开销（方案价值论证）

**本方案最重要的价值：把「交付正确性」从「依赖模型遵守指令」改为「结构保证」。**

- **旧机制最脆弱的一环**：converge 正确性依赖「agent 遵守『别写 best_*』这个指令」——本次事故就是 agent
  没遵守（或契约没说清）→ 写 → converge 读污染值 → 交付错。对指令尊重性差的模型，这一环**必然反复出问题**
  ——靠「模型自觉」守护安全不变量，是脆弱设计。
- **v8 移除这一环**：全过路径 converge 交付「框架自己测的 source_identity」（agent 写了也读不到）；非全过只读
  框架测量史 argmax。**agent 想越权、写错、漏写都改变不了交付结果**——交付决策不经过 agent 的任何输出。
  这比 prompt 写得再严厉都稳。

**诚实边界（不夸大）**：
- 提升的是**「流程/交付正确性对模型遵守度的鲁棒性」**，不是「模型解题能力」——diagnose 能否找到 bug 并改对，
  仍依赖模型，方案不碰。
- **D1 是例外**：git_commit 必填**增加**「模型必须填字段」的依赖。但它把 F10 的静默丢失（ledger 空置、无反馈、
  报告断链）变成显式打回（带 feedback 重派）——**显式失败优于静默**。弱模型漏填会触发打回被看见纠正，而非无声丢信息。

**对 agent 轨迹（耗时）的影响：零增长**。A/B/C1 全是框架侧、agent 零感知：
- A 双路径消费**既有**全量 run_tests 测量记录，不加新测试/新往返；
- B source_identity stamp 在 deploy 时框架读 git，agent 不参与；
- C1 converge 后纯比对，无 agent；
- D1 模型本就知道自己 commit 的 hash，填是低成本，仅漏填触发一次打回重派；
- D2 契约清晰 → 减少误解 → 可能略短。
**方案不新增任何 agent 往返阶段**（对比否决的「溶解」引入「声明→apply」两段式会增加往返）。净效应：轨迹不变长，
D2 可能略短。真正决定 diagnose 轨迹长短的是修复难度与模型能力，不是这套机制——它的价值是「让跑完的 debug
可靠变成正确交付」，不是「让 debug 更快」。

### B. provenance：交付物带来源标识（修 F1/F7）

- `Deployer.deploy` 构建时 stamp `source_identity` 进 deploy_result / last_deploy。
- **字段默认值（dataclass 兼容）**：`DeployResult` 加 `source_identity: str = ""`（带默认）。`read_last_deploy`
  是 `DeployResult(**json.load(f))`——中途升级残留的旧 last_deploy.json 无此键，不带默认会 TypeError 崩 run。
- run_tests 记录「本次被测的 source_identity」（供 A 的测量记录引用）。
- eval 报告记录被测 binary 的 source_identity——本次靠 git 考古 + 误差逐位比对才证明「eval 跑的是修复前
  binary」（F1）；有此字段一眼可见。
- **dirty-tree 陷阱（必须处理）**：本次 deploy(16:47) 在 commit(16:52) 前、工作区 dirty。source_identity
  必须含脏指纹（`HEAD-dirty-<op_dir 状态指纹>` 或等价），不能是裸 `rev-parse HEAD`——否则指到修复前 commit，
  provenance 假安全。**§1.4/§1.9 禁 reset --hard，故走指纹不走强制 clean。**
- **source_identity 来源确定性（不靠模型）**：deploy 构建时框架读 op_dir 的 `git rev-parse HEAD` + 工作区
  `git status --porcelain` 计数，拼成 `{HEAD 短12}-{clean|dirty-{n}}`——纯 git 探测（复用 `infra/provenance.py`
  的 `_git()` 思路但针对 op_dir），**不读 commit message、不由模型写**。A3 的最优 = 框架测的 identity，模型
  彻底无法影响交付选择（见溯源注记 2）。
- 判据：删 B → F7 原样（last_deploy 无来源）；RCA 仍靠考古；A 的测量记录缺 identity 无法交付/现算最优。

### C. converge 交接断言：收敛动作完整性自检（修「rollback 失败静默 keep 旧坏包」族）

- converge 结束时**断言** `deploy_result.source_identity == 判定的最优 identity`；不等（最典型：rollback
  失败走 keep-current fallback，deploy_result 仍是部署阶段留下的旧坏 source）→ WARN + 在 debug_result 明确
  标记「eval 将用非最优 source 的旧包」，使 eval 报告 / 用户可见。
- **这是收敛动作自身的自检，不是重新验质量**（§2.9 构造性保证）：最优 commit 的精度已由 run_tests 全量
  golden 验证闭合，converge 不复验（step-96 D1/D2 哲学）。
- 无耗时（纯读 identity 比对）、纯框架侧。**依赖 A+B**。
- 判据：删 C1 → rollback 失败路径上 deploy_result 可能静默指向非最优 source、eval 用错包而无人察觉
  （§1.2 可诊断缺口）。

### D. 加固：git_commit 必填 + A3 教学单通路（辅助，非防线）

- **D1（git_commit 必填，修 F10）**：fix 声明 schema 的 `git_commit` 设 required，transition 加载校验，
  违规走既有 product_feedback 打回（weak-model B 机制复用）。修 F10（本次实证：diagnose commit 了 b760254
  但 root_cause_ledger 空置、报告修复史 commit 列为 `-`——因 `_summary.git_commit` 可选未填，ledger 由
  `_merge_fix_into_ledger` 静默 no-op）。
- **D2（A3 教学单通路，防 F5 族栅栏漂移复发）**：把「写 control.json 的契约」收敛成单一来源，**仅覆盖
  A3**（A5 的 skill 契约不动——A5 专有）：
  - `ascendc-precision-diagnose` 的 SKILL.md 写契约 + prompt（substages:2522）——删 best_* 提及、写明
    「最优判定只信框架的 history 派生，case.status 等本 phase 字段按契约写」。教学双通路收口成一条。
  - 范围明确**不含** A5 的 dump-debug / finalize / pipeline-sync-debug（其 best_snapshot 写指令是 A5 专有，
    保留）。
- 判据：删 D → 越权写概率回到当前水平 + 教学双通路历史性分裂仍在 + F10 报告断链仍在；但**不是防线**——
  防线是 A（无字段可写）。

### E. 回归测试 + 文档闭环

- **fixture 复现本次完整序列**：iter-0 1/20 → diagnose 修复+commit+声明 → loopback 全量 20/20 →
  converge，断言交付 identity == 修复 commit、eval 拿到修复代码。
- **UT 清单**：A 双路径（路径一：全过退出 → 交付最近全过测量的 identity；路径二：非全过 → 测量史 argmax
  **平局保留较早**）；agent 写入失效三态；共享 converge 走 dc.best_commit 契约不变；B 脏指纹 + `source_identity`
  字段默认值兼容（旧 last_deploy.json 无键不崩）；C1 交接断言（rollback 失败 keep 旧坏包 → WARN + 标记）；
  D1 schema 打回 + D2 契约文本无回潮扫描。
- **既有 UT 迁移（A 删字段破坏面，§3.4）**：实证 A3 侧 11 个测试文件断言 `best_*`/`best_commit`
  （`test_precision_debug_stage.py` / `test_step96_converge_quality.py` / `test_graph_executor.py` /
  `test_step96_terminal_quality.py` / `test_build_failed_case_queue.py` 等）——删字段后全部迁移为
  「测量史现算」断言。**A5 相关测试（断言 best_snapshot / legacy 回写）不动**（A5 机制保留）。
- 端到端验收（下批真实 run）：eval 报告可见被测 binary 的 source_identity；debug 全过的 run，eval 与
  debug 测同一 identity；人为注入 agent 写 `best_passed_count` → 无字段可写、WARN 记录、判定不变。
- §1.8：L1/L3 冻结后 L4；实施后回填。

## 明确不做（用户拍板收敛 + 防过度，§1.14）

- **不动 A5 专有内容**（核心原则）：A5 的 checkpoint.json / best_snapshot 机制 / skill 写指令 /
  legacy best_commit/best_max_err 镜像——全保留，本次不改。A5 侧同源风险归 A5 自身演进范畴。
- **不搬家 control.json**：治 obscurity、root 藏不住、迁移 10 处消费者 + 双分支 + 存量批 RESUME 兼容 +
  引入「声明→apply」静默窗口——成本高、防御力增量有限，用户已否决为主修方向。
- **不改 teardown / resume**：teardown 是收尾不该做耗时操作；resume 基于中断时上下文续跑、代码须与上下文
  对应，不在中断路径改代码。teardown 锚点可信化由 A 覆盖，无需单独动。
- **不做「converge 重验精度 / 单 case golden 探测」**：质量验证已在 run_tests 全量闭合（step-96 D1/D2），
  converge 只自检「收敛动作落在选中 source 上」，不重验（§2.9）。
- **不做「debug 与 eval 判据对齐」**：已确认同源同函数（见溯源注记），非本事故因素。
- 不做字段级签名机制、不做文件权限游戏、不做通用 agent 沙箱、不设无依据告警阈值。

## 待评审决策点（用户拍板项，每项含背景）

> 决策点①的背景已在上文 dirty-tree 陷阱 + B 段说明；②的背景在 C 段；③的背景在 A 段双路径。这里只把
> 决策本身和推荐列清。

| # | 决策点 | 背景一句话 | 推荐 |
|---|---|---|---|
| ① | **source_identity 格式** | deploy 先于 commit、工作区 dirty，裸 HEAD 会指错（F6/F7） | `{HEAD 短12}-{clean\|dirty-{n}}`，纯 git 探测不靠模型（见 B 段） |
| ② | **C1「非最优即标记」强度** | converge rollback 失败会 keep 旧坏包、eval 悄悄用错 source（真实静默路径） | 仅 WARN + debug_result 标记放行，不阻断 eval（eval 本不以 deploy 为门，坏包如实跑更能暴露差异） |
| ③ | ~~双路径结果交给共享 converge 的落点~~（**已消解**） | 查证 `_converge_to_best_commit` 实为纯 A3（A5 有独立 `_a5_sync_debug_result`，不调用它）——无需绕 dc 契约保 A5，可直接改该函数从测量史现算 | 直接改 `_converge_to_best_commit`（方案 B） |

## 与历史步骤的关系

- **step-96（converge-tail-reverification）**：D1/D2/D3 修「收尾不重复发现已知坏」；本次 A/C 修「收尾
  选错锚点 + 验证无质量信号」——同在 converge 链，正交互补。
- **P79 / step-40（CannbenchComparer / EvaluationBackend）**：判据同源机制实证在跑（见注记），本次不动。
- **P2/P4（framework-owned best_*）**：方向对；本次把它推进到终态——不再「收口字段」而是「删字段 + 测量史推导」。
- **N1（run_tests 纯 Python）**：A 的测量记录增强落在 N1 的确定性测量线上，扩展而非推翻。
- **A5 流水线**：本次不触碰 A5 专有机制，仅保证共享 converge 在 A3 改来源后 A5 走同一函数无感。

## 验证策略（预告，细则进 L4）

- TDD：E 项红测先行（§3.1）。
- 全量 UT + 非 heavy ST（§3.2/§3.6）；端到端验收见 E 项。
