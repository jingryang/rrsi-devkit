# precision_debug 闭环控制 — 方案与实施（2026-07-18）

> 层级：**L3 方案分析 + L4 实施方案（合并）**。每个 P 自包含三段式：**问题 → 方案 → 实施**，与 L1 `01-problems.md` 的 P2–P9 一一对应。
> P1 为总体表现，由 P2–P9 的修复共同解决，不单独设节。
>
> 纪律：语义锚点为主（`类.方法` + 文件简称）；§1.4 不兼容直改；§2.5 删旧通路；§3.x TDD；不变式落框架、LLM 判定留 skill。

## 文件简称映射

| 简称 | 实际路径 |
|------|---------|
| `substages` | `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py` |
| `tree` | `src/ascendc_devkit/orchestration/precision_debug_tree.py` |
| `runner` | `src/ascendc_devkit/adapters/npu/runner.py` |
| `run_tests.md` / `init-checkpoint.py` / `build-failed-case-queue.py` | `ascendc-precision-run-tests` skill 下 |
| `fix.md` | `ascendc-precision-fix` skill 下 |
| `printf_location.md` / `gate3-printf-bisect.md` | `ascendc-precision-printf` skill 下 |
| `diagnose.md` | `ascendc-precision-diagnose` skill 下 |
| `scope-guard` | `ascendc-precision-scope-guard` skill |

## 总体策略

经四把尺子（§1.2）衡量，**不选纯止血、不选纯根治，选组合方案**：

- **正确改动（主修复）**：把直接导致空转的核心状态机不变式——收敛计数（P2）、case 推进（P3）、指标聚合（P4）、budget 语义（P5）——从 skill prompt/脚本**收回框架 transition 层**。这是 P9 的分阶段落地。
- **宽容兜底（last resort 防崩）**：框架层加收敛熔断（独立 `corrective_cycles` 计数器、attempt 上限强制推进），即使个别不变式临时失守，闭环也能在有限步内停机而非空转到 workflow 超时。
- **可观测性（不掩盖错误）**：分类指标（P4）、scope/printf 的 contract 校验（P7/P8）、deploy 健康度（P8），让「部分改善 / 回归 / deploy 失败」都留下信号。

---

## P2 — fix↔printf 小循环不推进 `rounds`，语义收敛锚点失效

### 问题

（详见 L1 `01-problems.md` P2）

`rounds` 计数器**只在 `RunTestsSubstage.transition` 中递增**；`FixSubstage.transition` 与 `PrintfLocateSubstage.transition` 仅透传。`tree` 的 transition_table 中 `fix.need_printf → printf_location` 与 `printf_location.located → fix` 构成**无计数器的双向边**。实际空转路径 `fix → need_printf → printf_location → located → fix` 完全不经过 `run_tests`，`rounds` 不增 → `rounds > max_iterations`（默认 30）永不触发 → 唯一兜底 `MAX_CORRECTIVE=200` 大到要跑数小时才触发。

### 方案

| 选项 | 描述 | 四尺子评估 |
|------|------|-----------|
| O1 把 rounds 移到 CompositeGroup | 每次完整 group 循环 +1 | 破坏现有 rounds 语义（「经 run_tests 的轮次」），波及面大 |
| **O2 独立 `corrective_cycles` 计数器** ✅ | fix↔printf 每次循环 +1，超阈值强制收敛；rounds 语义不变 | 可维护（新增独立计数，不动 rounds）/可扩展（未来新 stage 对共用）/可诊断（checkpoint 可见）/架构合理（收敛判定属框架） |
| O3 有限重试边 | printf 连续 N 次后强制回 run_tests | 把熔断耦合进 transition_table，不通用 |

**选取 O2**。新增 `corrective_cycles` 字段，在 `FixSubstage.transition` 与 `PrintfLocateSubstage.transition` 各 +1（经 run_tests 时归零），超 `max_corrective_cycles`（默认 8）→ `resolve_condition` 返回 `exhausted`。`_PRECISION_DEBUG_MAX_CORRECTIVE=200` 退为「防失控最后保险」，不作为常规收敛依据。

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 2a | `init-checkpoint.py`（control.json 初值区段） | 新增持久字段 `corrective_cycles: 0`、`max_corrective_cycles: 8` |
| 2b | `substages._extract_debug_checkpoint` | 透传 `corrective_cycles` / `max_corrective_cycles` 进 dc |
| 2c | `substages.FixSubstage.transition`（末尾，`_sync_debug_result` 前） | `cp["corrective_cycles"] += 1` + `_save_control` |
| 2d | `substages.PrintfLocateSubstage.transition`（末尾） | 同上 +1 |
| 2e | `substages.RunTestsSubstage.transition` | 经 run_tests 归零：`cp["corrective_cycles"] = 0`（表示「回到全量回归 = 有进展，重置小循环计数」） |
| 2f | `substages.FixSubstage.resolve_condition` | 新增前置：`if dc.get("corrective_cycles",0) >= dc.get("max_corrective_cycles",8): return "exhausted"` |
| 2g | `substages.PrintfLocateSubstage.resolve_condition` | 同上熔断（超限 → `"exhausted"`） |
| 2h | `tree._PRECISION_DEBUG_MAX_CORRECTIVE` 注释 | 更新：`corrective_cycles` 是主收敛锚点；`MAX_CORRECTIVE=200` 退为最后保险 |

**新增字段**：`control.json` 中 `corrective_cycles`（int）、`max_corrective_cycles`（int，默认 8）。

**验证（UT）**：
- 构造 `fix → need_printf → located → fix` 连续 8 次（不经 run_tests）→ 第 8 次 `resolve_condition` 返回 `exhausted`
- 中途插入一次 run_tests → `corrective_cycles` 归零，重新计数
- resume 后 `corrective_cycles` 不丢（持久化校验）

---

## P3 — case 推进死锁（precision 顶死队头 + resolved_pending 假阳性不回退）

### 问题

（详见 L1 `01-problems.md` P3）

双因子死锁：
- **框架层**：`FixSubstage.transition` 的 case 推进块被外层守卫 `case.status not in ("resolved", "resolved_pending")` 屏蔽，且推进条件 `ftype in ("compilation", "runtime")` 对 `precision` 永假
- **skill 脚本层**：`build-failed-case-queue.py` 的 `merge_with_existing` 无条件 preserve 旧 `status`（含 `resolved_pending`），即便本轮 result.json 显示该 case 仍失败也不回退
- **状态升级缺失**：全仓无 `resolved_pending → resolved` 升级写点

### 方案

**框架层（主修复）**：
- **P3-F1**：把 case 推进逻辑从 status 守卫块中**提取为独立前置检查**——超 `max_attempts_per_case` 即推进，与 status 解耦
- **P3-F2**：去掉推进条件里的 `ftype in (compilation, runtime)` 限制，precision case 超限同样推进

**skill 脚本层（配合）**：
- **P3-S1**：`merge_with_existing` 改为**条件 preserve status**——本轮 result.json 显示该 case 仍失败 → 回退 `pending`；本轮通过 → 由框架写 `resolved`

**状态升级（补缺）**：
- **P3-U1**：run_tests 全量通过时，由**框架**（非 skill）把对应 case 的 status 写为 `resolved`，打通 `resolved_pending → resolved` 升级路径

四尺子：可维护（推进逻辑单一权威源）/可扩展（新 failure_type 自动归位）/可诊断（status 变更有迹可循）/架构合理（status 升级属框架职责）。

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 3a | `substages.FixSubstage.transition` | **提取推进为独立前置检查**：无论 status，`attempts >= max_attempts_per_case` 即 `_advance_current_case`；删除外层 status 守卫对推进的屏蔽 |
| 3b | 同上 | 删除 `ftype in ("compilation","runtime")` 限制 → precision 超限同样推进 |
| 3c | `build-failed-case-queue.py.merge_with_existing` | `status` 移出无条件 preserve；改为：本轮 result.json 显示该 case 仍失败 → 回退 `pending`；本轮通过 → 不写（留给框架 3d） |
| 3d | `substages.RunTestsSubstage.transition` | 全量通过时，框架把对应 case `status` 写 `resolved`（打通 `resolved_pending → resolved` 升级） |
| 3e | `substages._case_marked_resolved` | 保留路由等价（fix 单用例 pass → resolved_pending → 走 run_tests 回归），但 docstring 明确「resolved = 全量回归确认；resolved_pending = 单用例待确认」语义区分 |

**状态机**：`pending → resolved_pending →（run_tests 全量 pass）→ resolved`，或 `resolved_pending →（run_tests 仍失败）→ pending`。

**验证（UT）**：
- precision case `attempt_count=11 > max=10` → 推进（无论 status）
- `resolved_pending` case，本轮 run_tests 仍失败 → merge 回退 `pending`
- `resolved_pending` case，本轮 run_tests 全量 pass → 框架写 `resolved`
- 20 case 队列，case 0 卡死后第 11 次 attempt → `current_case_index` 推进到 1

**注意**：3c 触及 skill 脚本（§2.6 第 1 类耦合）；本轮先在脚本内改正，Phase 5（P9）把 merge 收回框架。

---

## P4 — `best_*` 指标模型失效（进展/回归均不可见）

### 问题

（详见 L1 `01-problems.md` P4）

三个独立缺陷：
1. **`best_commit` 写死为 `initial_commit`**：`run_tests` skill prompt 中 `cp["best_commit"] = cp.get("initial_commit")`，未实际取 HEAD
2. **单标量字典序 `(failed_count, max_err)`**：run-level `max_err` 取所有 case 的 MAX，一个 crash（999.0）就钉死全部
3. **`real_max_err` 作为第三维不可靠**：跨 case 的 max_err 不可比——case A（float16, 128×128）的 0.5 和 case B（float32, 4096×4096）的 100 是不同量纲，取全局 max 没有语义。fix 改善 19/20 case 但 worst case 不变 → 看起来"无进展"；fix 让 19/20 case 恶化但 worst case 巧合下降 → 看起来"有改善"（实际在倒退）

### 方案

| 缺陷 | 选项 | 选取 |
|------|------|------|
| best_commit 写死 initial | A1 skill 内真取 HEAD / **A2 收回框架 `git rev-parse`** ✅ | A2（不变式属框架） |
| 单标量字典序 | B1 加权分数 / **B2 分类字典序 `(failed_count, crashed_count)`** ✅ | B2（failed_count 和 crashed_count 是可靠的改善信号——case 从 fail→pass、crash→运行） |
| real_max_err 第三维不可靠 | C1 case-by-case Pareto 比较 / **C2 直接删除第三维** ✅ | C2：`(failed_count, crashed_count)` 平局时诚实说「无法判定谁更好」，不硬造不可靠信号。fix 是否继续由 corrective_cycles / attempt_count 熔断决定 |

**整体**：best_* 的比较与更新逻辑从 `run_tests` skill prompt（`_better()`）**收回框架 transition**（`_update_best_metrics`）。比较维度降为 `(failed_count, crashed_count)`，平局返回 False（不声称改善）。`best_real_max_err` 降级为纯可观测字段（human inspection），不参与比较。run_tests skill 只负责跑测试 + 产出 raw `result.json`，**不再碰 best_***。

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 4a | `substages._update_best_metrics` | 框架侧聚合：从 run_result 算 `(failed_count, crashed_count)`；字典序只比这两维；平局返回 `False`。crash（diff==999.0 或 elapsed_ms<0）计入 `crashed_count`，不参与 `real_max_err` |
| 4b | `substages.RunTestsSubstage.transition` | 调 `_update_best_metrics`；`best_commit` 用 `git rev-parse HEAD`（若 `is_git_repo`）真取 HEAD |
| 4c | `init-checkpoint.py` | 保留 `best_crashed_count`、`best_real_max_err`（纯可观测）；注释标注「best_real_max_err 不参与比较，human inspection only」 |
| 4d | `run_tests.md` | **删除** best_* 更新段；skill 只产 raw result.json，不碰 best_* |
| 4e | `substages._sync_debug_result` | `max_diff` 物化改用 `best_real_max_err`（仅可观测）；`best_max_err` 保留作可观测字段但不驱动决策 |
| 4f | `runner` 999.0 注入点 | 保留（标记 crash），但在 harness 模板 per-case 结构里显式标 `'crashed': True`，供框架识别 |

**字段语义变更**：
- `best_failed_count`、`best_crashed_count`：比较维度（驱动 _update_best_metrics）
- `best_real_max_err`：**降级为纯可观测**（记录最佳轮次的误差幅度，不参与比较）
- `best_max_err`：**降级为纯可观测**（legacy compat，不参与比较）

**验证（UT）**：
- 1 precision(4056) + 19 crash → `best_crashed_count=19`（非 999.0 抹平）
- 全崩(20×999) vs 1precision(4056)+19crash → 后者 `(failed=20, crashed=19)` 优于前者 `(failed=20, crashed=20)`
- 同 `(failed, crashed)` + 不同 `real_max_err` → `_update_best_metrics` 返回 `False`（不声称改善）
- 首轮 → 总是记录

---

## P5 — `candidate_loop` budget 单调递增不复位，新 fixplan 永不被验证

### 问题

（详见 L1 `01-problems.md` P5）

`_candidate_pool_exhausted` 使用**绝对计数** `current_tried >= max_plans`，`current_tried` 只增不减。`printf_location` 新增 fixplan 入池时不复位 `current_tried`。`fix` skill 内部循环的 `while` 条件 `current_tried < max_plans` 在 budget 已耗尽时直接为 False——新入池的 fixplan 一进就被跳过。

### 方案

| 选项 | 描述 | 选取 |
|------|------|------|
| **O1 池空才算耗尽** ✅ | `_candidate_pool_exhausted` 改判 `len(pending) == 0`；`max_plans` 改为「同 case 累计 verified plan 数上限」 | 语义清晰（无 pending 才耗尽），新 plan 入池自然「复活」budget |
| O2 printf 入池部分复位 current_tried | 复位量难定，语义模糊 | 不选 |

**选取 O1**。`current_tried` 语义从「绝对尝试计数」改为「已 verified 计数」（只增，但只要有 pending 就不算耗尽）。`max_plans` 改为同 case 上限，超限 → 推进 case（P3-F1 已打通推进）。

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 5a | `substages._candidate_pool_exhausted` | 耗尽主判据改为 `len(pending) == 0`；`current_tried >= max_plans` 不再判 halt，改为「同 case verified 数达上限 → 触发推进」（复用 3a 推进路径） |
| 5b | `init-checkpoint.py`（candidate_loop 区段） | `max_plans` 语义注释改为「同 case 累计 verified plan 上限」；`current_tried` 注释改为「已 verified 计数（非绝对尝试）」 |
| 5c | `fix.md`（while 边界、各自增点） | `current_tried` 仅在 plan `verified ∈ {applied, refuted}` 后 +1；`while` 条件改为「pending 非空」驱动（不再用 `current_tried < max_plans` 作循环门） |

**语义重定义**：`candidate_loop.current_tried`（已 verified 计数）、`candidate_loop.max_plans`（同 case 上限）。

**验证（UT）**：
- 池有 pending → `_candidate_pool_exhausted` 返回 False（即使 current_tried 大）
- printf 新 plan 入池 → 下轮 fix 可验证（不被 budget 跳过）
- 同 case verified 达 max_plans → 推进到下一 case（不 halt）

---

## P6 — `candidate_pool` 无去重，同一 bug 被克隆成多个 fixplan

### 问题

（详见 L1 `01-problems.md` P6）

`_candidate_pool_exhausted` 只统计 `verified == "pending"` 的数量，对 hits 的**内容零检查**。`fix` skill 的 `tried_fixes` 仅在单次执行内按自然语言 `fix_desc` 软去重——跨轮无效，且 key 是可变措辞。本次运行中 `fixplan-017/018/019/020/021` 本质是同一个两行 `if/else` 分支交换，却作为 5 个独立 plan 存在。

### 方案

**后处理去重（不依赖 LLM agent 产出结构化 key）**：agent 照旧写 hit（自然语言），框架在 `DiagnoseSubstage.transition` / `PrintfLocateSubstage.transition` 读回 control.json 后按派生 canonical key 去重。

**canonical key 派生规则**（`_derive_candidate_key`）：
- 输入：hit 的 `target_file`、`target_function`、`fix_desc`
- 输出：`(target_file, target_function, fix_desc_first_80_chars_normalized)` 元组
- 任一字段缺失 → 返回 `None`（不去重，安全兜底）
- 归一化：去首尾空白、压缩连续空白

**去重规则**（`_deduplicate_candidate_pool`）：
- 同 key 只保留一条：优先 `verified != "refuted"`，其次 `priority` 最高的
- 被移除的 hit id 记入日志
- 返回移除数

| 选项 | 描述 | 选取 |
|------|------|------|
| **O1 框架后处理去重** ✅ | agent 写 hit 照旧，transition 中按 `(target_file, target_function, fix_desc)` 派生 key 去重 | 不要求 LLM 产出结构化 key，确定性逻辑，agent 已填的三个字段刚好够用 |
| O2 要求 agent 产出 `canonical_key` | LLM 非确定性使结构化 key 可靠性差 | 不选 |

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 6a | `substages` 新增 `_derive_candidate_key(hit) → tuple \| None` | 纯函数：从 `target_file`、`target_function`、`fix_desc` 首 80 字符归一化拼出 key；任一缺失返回 None |
| 6b | `substages` 新增 `_deduplicate_candidate_pool(cp) → int` | 遍历 `candidate_pool.hits`，按 key 分组；同 key 保留 `verified != "refuted"` + 最高 priority；返回移除数 |
| 6c | `substages.DiagnoseSubstage.transition` | `_load_control` 之后、`_save_control` 之前调用 `_deduplicate_candidate_pool(cp)` |
| 6d | `substages.PrintfLocateSubstage.transition` | 同上——printf 定位到新根因追加 hit 后，框架去重再保存 |
| 6e | `diagnose.md`、`printf_location.md` 写 hit 段 | 加说明：「`target_file`、`target_function`、`fix_desc` 是去重依据，必须如实填写」 |

**验证（UT）**：
- 同 `(file, function, fix_desc)` hit 出现两次 → 去重后剩 1 条（保留高 priority）
- `verified="refuted"` + 同 key 新 `pending` → 新 pending 覆盖 refuted
- `target_file` 缺失 → `key=None`，保留不去重
- 不同 `target_function` 相同 `fix_desc` → 不去重
- 空池去重 → 不移除，返回 0

---

## P7 — `scope_guard` 一次性首轮流，无重判、无收敛出口

### 问题

（详见 L1 `01-problems.md` P7）

`RunTestsSubstage.resolve_condition` 的 scope 门控是 `if not scope_checked`——**一次性**；`scope_checked` 一旦写入，后续不再路由回 `scope_guard`。`ScopeGuardSubstage.resolve_condition` 只有 `upstream` / `pass` 两个出口；异常值落入 `return "pass"` 兜底分支，**无 contract 校验**。无「连续 N 轮 has_failures 且 verdict=pass」就重判、或「无进展」就 reconsider 的机制。

### 方案

- **P7-O1（选取）**：`ScopeGuardSubstage.resolve_condition` 加 **contract 校验**（verdict ∈ {upstream, pass}，否则视为异常 → 重判或 halt）；引入「连续 K 轮 has_failures 且 best_* 无改善 → 重路由 scope_guard」（框架层，复用 P4 的 best_* 改善判定）。
- 不选「每轮都跑」（成本高，scope 性质不应频繁变）。

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 7a | `substages.ScopeGuardSubstage.resolve_condition` | 加 contract 校验：`scope_verdict` 不在 `{upstream, pass}` → 抛 `PrecisionDebugContractError`（[PD-CONTRACT]），不静默落 pass |
| 7b | `substages.RunTestsSubstage.resolve_condition` | scope 门控从一次性改为：`scope_checked and 连续 K 轮 has_failures 且 best_* 无改善` → 重路由 `needs_scope_check`（复用 P4 的 best_* 改善判定） |
| 7c | `tree` scope_guard 边 | 新增 `reconsider` 边（回 scope_guard）；RunTests 的 `needs_scope_check` 在 K 轮无改善时触发 |

**字段**：复用 `scope_checked` / `scope_verdict`；新增 transient「无改善轮次」计数（或复用 `corrective_cycles` 派生）。

**验证（UT）**：
- `scope_verdict="garbage"` → 抛 PD-CONTRACT（非 pass 兜底）
- 连续 K=3 轮 has_failures 且 best_real_max_err 无下降 → 重路由 scope_guard

---

## P8 — `printf_location` deploy 失败无框架感知，退化代码分析仍继续循环

### 问题

（详见 L1 `01-problems.md` P8）

`PrintfLocateSubstage.resolve_condition` 末尾 `return "continue"` 是**兜底黑洞**：deploy 失败（printf 探针编译不通过 / 内核运行崩溃无输出 / agent 退化为纯静态分析），**全部**被当作「继续二分」。`transition` 只检查 `printf_location_result == "exhausted"` 一个条件，不提取任何 deploy 健康度字段。`_extract_debug_checkpoint` 不把 deploy 状态读进 checkpoint。

### 方案

- **P8-O1（选取）**：`_extract_debug_checkpoint` 新增 `deploy_health` 字段（`build_ok` / `output_ok` / `agent_fallback`）和 `deploy_fail_streak`；`PrintfLocateSubstage.resolve_condition` 检查连续 deploy 失败计数，超阈值 → 返回 `deploy_broken`。
- `resolve_condition` 的优先级顺序：`corrective_cycles 超限` > `case_skipped` > **`located`（成功定位优先于 deploy 问题）** > `deploy_fail_streak >= 3` > `continue`
- 同时补 transition_table 缺的 `deploy_broken` 路由边。

**注意**：printf_location 不使用 msprof（那是性能 profiling 工具）。deploy 失败的三类信号是：

| 信号 | 含义 |
|------|------|
| `build_ok=false` | printf 插桩后的内核编译不通过 |
| `output_ok=false` | 编译过了但运行崩溃/超时，无 printf 日志产出 |
| `agent_fallback=true` | 上述失败后 agent 放弃二分，退化到纯静态分析读代码猜 |

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 8a | `printf_location.md` `_summary` 产出段 | printf agent 写 `deploy_health: {build_ok, output_ok, agent_fallback}` 到 control.json（或 phase JSON `_summary`）；编译/运行/fallback 失败时显式标记 |
| 8b | `substages._extract_debug_checkpoint` | 派生 `deploy_health` / `deploy_fail_streak`（连续 deploy 失败计数） |
| 8c | `substages.PrintfLocateSubstage.transition` | 从 agent 的 `_summary` 提取 `deploy_health`，更新 `deploy_fail_streak`：`build_ok=false` 或 `output_ok=false` → streak+1；正常 → streak 归零 |
| 8d | `substages.PrintfLocateSubstage.resolve_condition` | `return "continue"` 拆为显式分支：`located` 先于 `deploy_broken` 检查（定位成功不受 deploy 问题影响）；`deploy_fail_streak >= 3` → `return "deploy_broken"`；否则 `continue` |
| 8e | `tree` printf_location transition_table | **新增缺失边**：`"deploy_broken": ("__escalate__:deploy_broken", "validation")`（当前代码 bug——resolve_condition 已返回 `deploy_broken` 但 transition_table 无此 key） |

**新增字段**：`deploy_health`、`deploy_fail_streak`。

**验证（UT）**：
- deploy 连续失败 3 次 → `resolve_condition` 返回 `deploy_broken`（非 continue）
- `located=true` + `deploy_fail_streak=5` → 仍返回 `located`（定位成功优先）
- deploy 正常（build_ok=true, output_ok=true）→ `located`/`continue` 路径不变

---

## P9 — 不变式维护散落于 skill，框架被动消费（架构根因）

### 问题

（详见 L1 `01-problems.md` P9）

闭环的核心不变式——`best_*` 单调改善、`resolved` 只升不降、`candidate_loop` 一致性、`resolved_pending` 假阳性可回退——其**实现权分散在多个 skill 的 prompt 模板与脚本中**，由非确定性的 LLM agent 在执行 prompt 时维护；框架仅被动消费 agent 写回的 `control.json`。与 CLAUDE.md §1.1（Event Sourcing，状态权威在框架）+ §2.5（唯一通路）存在张力。

### 方案

| 选项 | 描述 | 四尺子评估 |
|------|------|-----------|
| O1 维持现状 + 打补丁 | skill 继续维护不变式 | 可维护性差，P2–P8 复发 |
| **O2 核心不变式收回框架（分阶段）** ✅ | P2–P6 已逐步收回收敛/推进/指标/budget/去重；Phase 5 固化为文档 + 删 skill 旧通路 | §1.1 Event Sourcing / §2.5 唯一通路 |
| O3 全部收回（一次性） | 周期长风险高 | 过度 |

**选取 O2**。Phase 5 把 P2–P8 中已落在 `substages.py` transition 层的不变式明确标记为「Invariant Layer」；删除 skill prompt/脚本里的 `best_*` 更新指令、`current_tried` 自增、status 无条件 preserve 等**旧通路**（§2.5 不留旧债）。不新建独立 class（避免为内聚而内聚——当前 module-level 纯函数调用关系已清晰）。

### skill 边界重划

| 职责 | 当前归属 | 目标归属 |
|------|---------|---------|
| 跑测试、解析 result.json | run_tests skill | run_tests skill（保留） |
| 构建 failed_case_queue（merge/status） | run_tests 脚本 | **框架 RunTestsSubstage.transition**（merge 有条件 preserve） |
| best_* 更新与比较 | run_tests skill（`_better()`） | **框架 `_update_best_metrics`** |
| 比较维度 | `(failed, max_err)` 含 999.0 哨兵污染 | **`(failed_count, crashed_count)`，平局诚实说无法判断** |
| rounds / corrective_cycles | 缺失 / 散落 | **框架** |
| case 推进 / status 升级 | FixSubstage（被守卫屏蔽） | **框架**（解耦） |
| candidate_pool 去重 | 无 | **框架 `_deduplicate_candidate_pool`** |
| current_tried 语义 | fix skill prompt | **框架**（重定义） |
| LLM 判定 scope/根因/修复 | 各 skill | 各 skill（保留，领域核心） |
| deploy 健康度提取 | 无 | **框架** |

判据（§2.7）：**状态机不变式属「框架核心」；LLM 判定属「skill 领域核心」**。

### 实施 — Part A：删 skill 旧通路

| # | 文件 | 当前内容 | 改法 |
|---|------|---------|------|
| 9b | `run_tests.md:19,47` | 职责表写「best_commit / best_max_err / best_failed_count 每轮更新最佳版本」 | 改为「best_* 指标由框架 `_update_best_metrics` 维护，agent 只产出 raw result.json，不写 best_* 字段」 |
| 9c | `build-failed-case-queue.py:204-209` | `merge_with_existing` 无条件 preserve `status` | P3 3c：`status` 移出 preserve 列表；本轮 result 仍失败 → 回退 `pending`；本轮通过 → 保留旧 status（框架 3d 写 `resolved`） |
| 9d | `fix.md:20,38,56,154` | `current_tried >= max_plans` 做循环门；agent 自增 `current_tried` | 循环门改为「pending 非空」驱动；`current_tried` 加注「由框架维护」；`FIX_NEED_BISECT` 条件去掉 `current_tried >= max_plans` |
| 9e | 各 skill SKILL.md 开头 | 无边界说明 | 加一句：「本 skill 只产 raw 执行结果 + LLM 判定，**不维护状态机不变式**（best_* / case 推进 / candidate_loop / corrective_cycles 属框架）」 |

### 实施 — Part B：缺漏补齐

| # | 位置 | 说明 |
|---|------|------|
| B1 | `tree` printf_location transition_table | 新增 `"deploy_broken": ("__escalate__:deploy_broken", "validation")`（当前 bug：resolve_condition 已返回此值但无路由边） |
| B2 | `printf_location.md` `_summary` 产出段 | agent 写 `deploy_health: {build_ok, output_ok, agent_fallback}`；框架 transition 已有提取逻辑（8c），只差 agent 侧产出 |

### 实施 — Part C：不变式文档收敛（轻量）

不新建 `_PrecisionDebugInvariants` 类。在 `substages.py` 模块 docstring 加「Invariant Layer」区块注释，标注各函数职责：

| 函数 | 不变式 | 来源 |
|------|--------|------|
| `_update_best_metrics` | `(failed_count, crashed_count)` 字典序比较，平局不声称改善 | P4 |
| `_candidate_pool_exhausted` | 池空判定 = `len(pending) == 0` | P5 |
| `_deduplicate_candidate_pool` | 按 `(target_file, target_function, fix_desc)` 去重 | P6 |
| `_advance_current_case` | case 推进：skip 当前 + index+1 + 重置 debug_state | P3 |
| `_bump_corrective_cycles` / reset | fix↔printf 小循环 +1，run_tests 归零 | P2 |
| `deploy_fail_streak`（在 `_extract_debug_checkpoint`） | printf deploy 连续失败计数 | P8 |

**验证**：
- UT 全绿（P2–P8 不变式仍成立，且单一权威源）
- grep 确认 skill prompt/脚本中不再有 best_*/merge status/current_tried 自增逻辑

---

## P10 — control.json 部分写入（agent 幻视新建 dict 覆盖全部字段）

### 问题

（详见 L1 `01-problems.md` P10）

`RunTestsSubstage._phase_prompt` 中读写契约写为「更新 control.json：status / failed_case_queue / best_commit / best_max_err / best_failed_count」。agent 按字面理解 → 新建只包含这 5 个 key 的 dict → `json.dump` 写回 → 覆盖 init-checkpoint.py 初始化的全部 20 个 required key。框架 `_assert_control_contract` 检测到 missing keys → `PrecisionDebugContractError` → pipeline halt。

### 方案

| 选项 | 描述 | 四尺子评估 |
|------|------|-----------|
| O1 仅 prompt 修正 | 只改 run_tests agent prompt，加「先 json.load → 修改 → json.dump」模式 | 可维护（改 prompt 简单）但不可扩展（下次其他 agent 同样可能幻视）；无框架兜底 |
| **O2 prompt 修正 + 框架 auto-repair** ✅ | prompt 明确 read→modify→write；同时框架 `_assert_control_contract` 改为 `_ensure_control_contract`：missing keys → auto-fill 安全默认值 + warn；forbidden D3 keys 仍 raise | 可维护（prompt 治本 + 框架兜底治标）/ 可扩展（任意 agent 的 partial write 都可恢复）/ 可诊断（warn 留下信号）/ 架构合理（框架持有 contract 最终权威） |
| O3 retry 机制 | 检测异常后重新 spawn agent | 复杂度高、token 成本大、收益小（retry 不保证 agent 不再犯） |

**选取 O2**。两层防御：
1. **Prompt 层（预防）**：改写为「先 json.load 整个文件 → 只修改上述 5 个 key → json.dump 写回。**禁止新建 dict 只包这 5 个 key 后写回**」
2. **框架层（兜底）**：`_ensure_control_contract(cp, control_path)` — missing keys → auto-fill `_CONTROL_DEFAULTS` + Logger.warn + 写回磁盘；forbidden D3 stale keys → 仍 raise（真正数据损坏）；type mismatch → auto-coerce

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 10a | `substages.RunTestsSubstage._phase_prompt` | 读写契约段改写：「更新 control.json 中以下字段（只改这 5 个，**保留其他所有已有字段不变**）…先 json.load 整个文件 → 只修改上述 5 个 key → json.dump 写回。**禁止新建 dict 只包这 5 个 key 后写回**」 |
| 10b | `substages` 新增 `_CONTROL_DEFAULTS` | dict：所有 20 个 required key → 安全默认值（`debug_state="fresh"`、`failed_case_queue=[]`、`current_case_index=0`、`candidate_pool={...}`、`best_max_err=999.0` 等） |
| 10c | `substages._assert_control_contract` → `_ensure_control_contract(cp, control_path) → dict` | missing keys → auto-fill defaults + warn + 写回；forbidden keys → raise；type mismatch → coerce + warn |
| 10d | `substages` 中所有调用点 | `_ensure_control_contract(cp, control_path)` 替换原 `_assert_control_contract(cp)`；接收返回的 repaired dict |

**验证（UT）**：
- control.json 缺失 14 个 required key → auto-fill defaults，返回完整 dict
- control.json 含 D3 禁止字段 → 仍 raise
- control.json `current_case_index` 为字符串 → auto-coerce 为 int
- 空 dict → auto-fill 全部 defaults

---

## P11 — schema/contract validation 一律 fatal halt → 分层容错

### 问题

（详见 L1 `01-problems.md` P11）

`_assert_control_contract` 和 `_validate_phase_json` 对 **所有** schema 违规统一 raise——不区分「可安全修复」（missing key → 填默认值）与「真正损坏」（forbidden keys / unparseable JSON）。任何 agent 的一次 prompt 偏差 → pipeline 立刻终止，无自愈能力。

### 方案

**P11 的方案已分别由 P10（control.json）和 P13（phase JSON）承载：**

- **control.json 层**：`_assert_control_contract` → `_ensure_control_contract`（P10 O2）
- **phase JSON 层**：`_validate_phase_json` 改造——missing required keys → auto-fill `_PHASE_DEFAULTS` + warn + 写回；仅 unparseable JSON 才 raise（P13 O2）

**通用原则**：contract 校验分三层响应——
1. **可安全修复**（missing key，有已知安全默认值）→ auto-fill + warn + 继续
2. **可降级修复**（type mismatch，可安全 coercion）→ auto-coerce + warn + 继续
3. **不可修复**（forbidden D3 key / unparseable JSON / 默认值缺位）→ raise

### 实施

（已在 P10、P13 各自实施段覆盖，本节仅记录跨问题通用原则。）

| # | 位置 | 改法 |
|---|------|------|
| 11a | `substages` 模块 docstring | 加 «Contract Validation Tiers» 注释区块，文档化「auto-fill → coerce → raise」三层响应模型 |

---

## P12 — A 级 printf 验证缺入口活体探针 → 误判

### 问题

（详见 L1 `01-problems.md` P12）

A 级 printf 验证只插入 FIX_BEFORE / FIX_AFTER 两个业务探针，grep 不到输出时无法区分「printf 环境不工作」与「探针代码路径未执行」，一律判 refuted——可能把环境问题误判为修复无效。

### 方案

| 选项 | 描述 | 选取 |
|------|------|------|
| **O1 入口活体探针** ✅ | 在 kernel 入口函数第一行插 `printf("[LIVENESS_CHECK]\n");`，compile+run 后先 grep LIVENESS_CHECK 确认 printf 生效，再 grep FIX_BEFORE/AFTER | 简单、确定性、无歧义 |
| O2 环境探测脚本 | 独立脚本跑 printf 用例验证环境 | 多一步操作，且不保证与当前 kernel 相同的编译/运行环境 |

**选取 O1**。判定矩阵扩展为三维：

| LIVENESS_CHECK | FIX_BEFORE | FIX_AFTER | 判定 |
|---|---|---|---|
| 未输出 | — | — | **printf 不生效** → 分析原因 + 恢复（≥2 种手段），不进入业务判定 |
| 输出 | 输出 | 未输出 | **confirmed**（探针生效，目标行确实是崩溃点） |
| 输出 | 未输出 | — | **refuted**（崩溃在目标行之前） |
| 输出 | 输出 | 输出 | **refuted**（目标行不是崩溃点，假设不成立） |

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 12a | `ascendc-precision-fix/SKILL.md` A 级 printf 验证流程 | 新增 step 1：定位 kernel 入口函数（`Kernel<...>::Process()` 或 `__global__`），插入 `printf("[LIVENESS_CHECK]\n");`。Verification 阶段先 grep LIVENESS_CHECK → 未输出则分析 printf 环境问题 |
| 12b | `ascendc-precision-fix/references/prompts/fix.md` 内部循环伪代码 | 新增 `insert_entry_printf("printf(\"[LIVENESS_CHECK]\\n\");")` 步骤 + `if not grep("LIVENESS_CHECK"):` 分支（printf 故障恢复流程） |
| 12c | `agents/ascendc-precision-fix.md` A 级验证段 | 判定表更新为三维（+LIVENESS_CHECK 列） |

**验证（ST / npu）**：
- LIVENESS_CHECK 未输出 + FIX_BEFORE 有/无 → 进入 printf 故障恢复流程（不判 refuted）
- LIVENESS_CHECK 输出 + FIX_BEFORE 输出 + FIX_AFTER 未输出 → confirmed
- LIVENESS_CHECK 输出 + FIX_BEFORE 未输出 → refuted

---

## P13 — `precision_printf.json` 缺失 `tried_bisect_paths` → contract halt

### 问题

（详见 L1 `01-problems.md` P13）

`precision_printf.json` schema 声明 `tried_bisect_paths` 为 required key（所有分支都必须存在），但 printf_location agent prompt 只在 **exhausted** 分支提到此字段。fresh/bisecting 分支 agent 不知道要写 → 首轮直接 contract halt。

### 方案

| 选项 | 描述 | 选取 |
|------|------|------|
| O1 仅 prompt 修正 | 在 fresh/bisecting 分支补写 `tried_bisect_paths` | 治标——下次其他 phase 可能同模式 fail |
| **O2 prompt 修正 + 框架 `_PHASE_DEFAULTS` auto-repair** ✅ | prompt 三分支都明确写；同时 `_validate_phase_json` 改造：missing required keys → auto-fill `_PHASE_DEFAULTS` + warn + 写回磁盘 | 两层防御；与 P10 control.json auto-repair 模式一致 |

**选取 O2**。两层：
1. **Agent prompt 修正**：fresh 分支新增 `tried_bisect_paths: []`（必填）；bisecting 分支新增「保留 `tried_bisect_paths` 不变」；Atomic write 段强调 mandatory
2. **框架 `_PHASE_DEFAULTS`**：`{"tried_bisect_paths": []}`——missing keys → auto-fill + warn + 写回；仅 unparseable JSON 才 raise

### 实施

| # | 位置 | 改法 |
|---|------|------|
| 13a | `agents/ascendc-precision-printf-locate.md` fresh 分支（第 49 行） | 新增 `tried_bisect_paths: []`（必填，初始化为空数组；schema required key，不写会触发 contract halt） |
| 13b | 同上 bisecting 分支（第 59 行） | 新增「**保留 `tried_bisect_paths` 不变**（schema required key，必须一直存在）」 |
| 13c | 同上 Atomic write 段（第 88 行） | 强调「**tried_bisect_paths（必填，schema required key，所有分支都必须写）**」 |
| 13d | `substages.PrintfLocateSubstage._phase_prompt` | 读写契约段新增 `tried_bisect_paths` 必填要求 |
| 13e | `substages` 新增 `_PHASE_DEFAULTS` | dict：5 个 phase JSON → required keys 安全默认值 |
| 13f | `substages._validate_phase_json` | missing required keys → auto-fill `_PHASE_DEFAULTS` + warn + 写回；仅 unparseable JSON 才 raise |

**`_PHASE_DEFAULTS` 内容**：
```python
_PHASE_DEFAULTS = {
    "precision_printf.json": {"tried_bisect_paths": []},
    "precision_run_tests.json": {"last_result_json": "", "last_run_log": ""},
    "precision_diagnose.json": {"arch_gaps": [], "diagnose_done": False},
    "precision_fix.json": {"fix_code_log": {}},
    "scope_verdict.json": {"scope_verdict": None},
}
```

**验证（UT）**：
- `precision_printf.json` 缺失 `tried_bisect_paths` → auto-fill `[]`，不 raise
- 各 phase JSON 缺失各自 required key → auto-fill 对应默认值
- unparseable JSON（语法错误）→ 仍 raise PrecisionDebugContractError
- 所有 5 个 phase 的 `_PHASE_DEFAULTS` 覆盖全部 required keys（新增 test_phase_defaults_covers_all_five_phases）

---

## P10–P13 架构层面的统一收获

| 维度 | 修复前 | 修复后 |
|------|--------|--------|
| control.json 契约 | `_assert_control_contract`：missing → fatal halt | `_ensure_control_contract`：missing → auto-fill defaults + warn |
| phase JSON 契约 | `_validate_phase_json`：schema 违规 → fatal halt | 同上模式：missing keys → auto-fill `_PHASE_DEFAULTS` + warn |
| A 级 printf 验证 | 2 探针（FIX_BEFORE/AFTER），无法区分「printf 不生效」vs「探针未到达」 | 3 探针（+LIVENESS_CHECK 入口活体），先确认 printf 生效再判定 |
| 通用原则 | agent 幻视 = pipeline 炸掉 | agent 幻视 = 框架 auto-repair + warn + 继续跑（不可恢复才 halt） |
| 防御层次 | 单层（靠 agent prompt 保证正确性） | 双层（prompt 预防 + 框架容错兜底） |

**新增**：
- `corrective_cycles`、`max_corrective_cycles`（P2 收敛计数）
- `best_crashed_count`（P4 分类指标——比较维度）
- `deploy_health`、`deploy_fail_streak`（P8 printf 健康度）

**语义重定义**：
- `candidate_loop.current_tried`：绝对尝试计数 → 已 verified 计数
- `candidate_loop.max_plans`：全局上限 → 同 case 上限
- `case.status`：`resolved_pending → resolved` 升级路径明确（run_tests 全量通过时由框架写）

**降级为纯可观测**（不参与比较/决策）：
- `best_real_max_err`：记录最佳轮次的非 crashed 最大误差，human inspection only
- `best_max_err`：legacy compat，同上

**删除（Phase 5 / P9）**：
- skill prompt 内的 `_better()`、best_commit 写死、merge status 无条件 preserve、current_tried 自增逻辑

---

## 当前进度与待办

### ✅ 已完成

| 阶段 | 覆盖问题 | 状态 |
|------|---------|------|
| Phase 0 合约容错 | P10 control.json auto-repair（`_ensure_control_contract` + `_CONTROL_DEFAULTS`）、P13 phase JSON auto-repair（`_PHASE_DEFAULTS` + `_validate_phase_json` 改造）、P12 A 级 printf LIVENESS_CHECK 活体探针 | ✅ 全部 UT 通过（114 用例，0.57s） |
| Phase 1 止血 | P2 corrective_cycles（9 UT）、P3 case 推进（6 UT）、P5 budget 重定义（5 UT） | ✅ |
| Phase 2 指标 | P4 `_update_best_metrics` None→0 归一化 + 降维 `(failed_count,crashed_count)`（5 UT）+ P4 fix agent "already resolved" 检测（4 文件：agent def / skill method / prompt / framework substage）+ P5 RT agent abort 检测（2 处：transition guard + resolve_condition） | ✅ |
| Phase 3 可观测 | P7 scope_guard re-entry guard + P8 printf deploy_broken 路由（3 workflow TRANSITION_TABLE：`GenerateAscendCWorkflow` / `DevWorkflow` / `SelfEvolveOpWorkflow`）| ✅ |
| Phase 4 质量 | P6 `_deduplicate_candidate_pool` 按 `(target_file,target_function,fix_desc)` 去重（框架 + skill 文档） | ✅ |
| Phase 5 架构收敛 | P9 `_append_history` 加 `corrective_cycles` 字段 + skill 边界声明（fix agent / fix SKILL.md / fix prompt / diagnose prompt）+ P6 去重 skill 说明 | ✅ |

### 无待办 — 全部 P2–P9 已完成

所有代码修复已落地，UT 全量通过，非 heavy ST 绿。heavy_llm e2e 按 §3.11 交付前用户决策跑一次。

### 实际实施顺序

```
Phase 1（P2 corrective_cycles + P3 case 推进 + P5 budget 重定义）
→ Phase 2（P4 best_* 框架化 + P4 already_resolved 检测 + P5 RT abort 检测）
→ Phase 3（P7 scope_guard + P8 deploy_broken 路由 + P3 printf_location exhausted exit）
→ Phase 4（P6 candidate_pool 去重）
→ Phase 5（P9 history corrective_cycles + skill 边界声明）

---

## 测试策略总表

| 层级 | 覆盖 | 标记 |
|------|------|------|
| UT | 每个 transition/resolve_condition 的纯逻辑（corrective_cycles 递增、case 推进解耦、best_* 比较、去重、contract 校验、deploy 熔断） | 无依赖（StubBackend） |
| ST | 真实闭环小算子（构造可复现的空转场景，验证有限步停机） | npu |
| heavy_llm | 端到端真实算子闭环（如本次 moe_init_routing） | llm + heavy_llm（§3.11 用户确认） |

**TDD（§3.1）**：每个 Phase 先写 UT（失败用例固化不变式），再改框架。

---

## 变更记录

| 日期 | 内容 |
|------|------|
| 2026-07-18 | 初版：合并 L3+L4，按 P2–P9 逐问题三段式（问题→方案→实施）。Phase 1–3 must，4–5 should。 |
| 2026-07-18 | **O2 修正**：P4 `_update_best_metrics` 第三维 `real_max_err` 删除——跨 case 不可比，平局诚实说无法判断。P8 `deploy_health` 修正：`profile_ok`→`output_ok`（printf 不用 msprof）。补 P8 B1/B2 缺口。更新实施顺序与进度。 |
| 2026-07-18 | **追加 P10–P13**：基于 `log2.log` 二次运行发现的 contract/schema validation 层问题与修复方案。P10（control.json auto-repair）、P11（分层容错原则）、P12（printf LIVENESS_CHECK）、P13（phase JSON `_PHASE_DEFAULTS`）。P10/P12/P13 已全部实现（Phase 0，114 UT 全绿）。 |
| 2026-07-19 | **P2–P9 全部实施完成**：P2（corrective_cycles + RunTestsSubstage 归零）/ P3（case 推进解耦 + merge_with_existing 条件 preserve + run_tests 全量通过写 resolved）/ P4（None→0 归一化 + 降维 (failed_count,crashed_count) + RT agent abort 检测 + fix agent already_resolved 检测）/ P5（candidate_pool_exhausted 改判 len(pending)==0）/ P6（_deduplicate_candidate_pool 去重 + skill 文档）/ P7（scope_guard re-entry guard）/ P8（deploy_broken 3 workflow TRANSITION_TABLE）/ P9（_append_history 加 corrective_cycles + skill 边界声明）。代码改动覆盖 6 文件（substages / tree / workflow / fix agent def / fix SKILL.md / fix prompt / diagnose prompt）。UT 全量绿，非 heavy ST 绿。L2 全局总纲 step-55 更新为已完成。 |
