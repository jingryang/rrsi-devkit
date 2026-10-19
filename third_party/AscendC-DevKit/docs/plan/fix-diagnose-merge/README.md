# fix + diagnose 融合方案（L3 决策 + L4 实施）

## 一、问题（L1 摘要）

precision_debug loop 中 `diagnose` 与 `fix` 分立两阶段：diagnose 静态分析产出 candidate_pool 的 fix_plan，fix 再 spawn 一次 agent 读 pool、按优先级实施（Edit→build→test→commit/rollback）。fix 阶段存在两类浪费：

1. **上下文重建**：fix agent 重新读 control.json / 源码 / diagnose 产物，丢失 diagnose 刚建立的完整分析上下文。diagnose 已完成的根因定位在 fix 侧重新装载。
2. **空转 spawn**：candidate_pool 无 pending plan（pool_exhausted）时仍 spawn fix agent 做一次"检查空池"再路由到 printf/comment_bisect（实测 adaptive_avg_pool_3d 9 次 fix spawn 中 5 次 pool_exhausted 空转）。

## 二、关键事实（融合可行的根基）

`comment_bisect` 与 `printf_location` **均已自带 self-fix**：两者 `located_fixed` 在 transition_table 直连 `run_tests`（`precision_debug_tree.py:109/127`），prompt 明确"定位后自闭环 Edit→commit，不经过 fix phase"。故 **fix 阶段当前唯一的 plan 来源是 diagnose**（+ diagnose_refine `done`），定位类阶段不再回流 fix。

因此删 fix 只动"diagnose→fix→run_tests"内部链，**所有定位+修复路由（printf/comment_bisect/bounds_check/scope_guard）零改动**。

## 三、决策（L3）

### D1：融合形态 = diagnose 自实施，非"两阶段拼装"

diagnose agent 分析产出 plan 后**就地实施**（加 Edit 工具），不再写 plan 等下游 fix 消费。FixSubstage 整体并入 DiagnoseSubstage，**删除独立 fix 阶段**（§2.5 唯一通路、§1.4 不向后兼容）。

否决项："保留 fix 作为 comment_bisect plan 实施入口" —— comment_bisect 已 self-fix 直回 run_tests，不再产 plan 给 fix，该理由已不成立。

### D2：route_to 语义重定义

diagnose agent 仍写 `route_to`，但消费方从"路由到 fix stage"变为"diagnose 自身行为分叉"：

| route_to | 含义 | 路由 |
|---|---|---|
| `"printf_location"` | diagnose 自评需设备级 on-device 确认（RC5 防御性 printf 等） | `route_to_printf` → printf_location（不变） |
| `"fix"` 或缺省 | 进入实施模式：有 plan 就 apply，无 plan 走 pool_exhausted 路由 | 由合并后的 resolve_condition 决定 |

diagnose agent 的 route_to 写法不变，仅下游消费语义改变（最小改动，不破坏 agent 行为）。

### D3：abort bump 策略 = 统一 True

原 diagnose abort `bump_counters=False`（纯分析瞬态）；原 fix abort `bump_counters=True`（实施重）。融合后 diagnose 承担实施职责，abort 统一 `bump_counters=True`，与原 fix 一致——diagnose 不再是"纯分析"，abort 应消耗配额防无限重试。原 diagnose abort 测试断言相应调整。

### D4：实施模式由 route_to 门控

合并后的 DiagnoseSubstage.transition：

- `route_to == "printf_location"`：走原 diagnose 简单收尾路径（不 bump cc、不做 stop-loss、不 apply）。
- 否则（实施模式）：执行原 FixSubstage.transition 的全部横切逻辑（7 类，见 §四）。

abort 发生在 `_agent_produced_output` 检查时（无产出，读不到 route_to），故 abort 统一 bump（D3），不依赖 route_to 分叉。

## 四、横切逻辑搬迁清单（L4，一项不能漏）

FixSubstage.transition（`precision_debug_substages.py:2236-2370`）承载的 7 类控制逻辑，整体并入 DiagnoseSubstage.transition 的"实施模式"分支：

| # | 逻辑 | 源行 | 并入位置 |
|---|---|---|---|
| 1 | `attempt_count >= max_attempts` → `_advance_current_case`（case stop-loss） | `:2252-2258` | 实施分支 |
| 2 | `pool_exhausted + compilation` → skip case | `:2259-2273` | 实施分支 |
| 3 | `_merge_fix_into_ledger`（commit 入账） | `:2282` | 实施分支 |
| 4 | `already_resolved` → case `resolved_pending` | `:2287-2292` | 实施分支 |
| 5 | `partial_outputs` → 更新 outputs + partial 标记 | `:2297-2313` | 实施分支 |
| 6 | `corrective_cycles += 1` + cc 耗尽 → `_advance_past_failure_type` | `:2316-2336` | 实施分支 |
| 7 | `applied_partial`/`regression` 证据 → dc + `refine_pending` | `:2345-2364` | 实施分支 |

helper（`_advance_current_case` / `_advance_past_failure_type` / `_candidate_pool_exhausted` / `_merge_fix_into_ledger` / `_extract_debug_checkpoint`）保留不动（bounds_check 仍用 `_merge_fix_into_ledger`）。

## 五、路由影响（现有解决问题路由全保留）

| 现有路由 | 融合后 | 影响 |
|---|---|---|
| run_tests has_failures → diagnose | 不变 | ✅ |
| run_tests direct_comment_bisect → comment_bisect | 不变 | ✅ |
| diagnose route_to_printf → printf_location | 不变 | ✅ |
| printf_location located_fixed/continue/printf_more/printf_done | 不变（self-fix） | ✅ |
| comment_bisect located_fixed/continue/case_more/case_done | 不变（self-fix） | ✅ |
| bounds_check fixed/fix_failed/not_found | not_found→diagnose 不变 | ✅ |
| scope_guard pass/pass_done | 不变 | ✅ |
| diagnose_refine done | 原→fix，现→**diagnose**（语义不变） | 改目标名 |
| fix need_printf → printf | diagnose 输出 need_printf | ✅ |
| fix need_comment_bisect → comment_bisect | diagnose 输出 need_comment_bisect | ✅ |
| fix applied_partial → diagnose_refine | diagnose 输出 applied_partial | ✅ |

## 六、收敛性证明

三道收敛闸全部迁移到 diagnose，语义不变：

1. `corrective_cycles >= max_corrective_cycles` → advance past failure_type（原 fix↔printf → diagnose↔printf）。
2. `attempt_count >= max_attempts_per_case` → advance case。
3. `run_tests rounds >= max_iterations` → exhausted（在 RunTestsSubstage，不受影响）。

corrective quota 计量对象从 fix 节点移到 diagnose 节点：`retry/need_printf/skip_more/regression` 仍标 `corrective`，框架 `max_corrective` backstop 行为一致。

## 七、改动文件清单（L4）

### 核心代码
- `src/ascendc_devkit/orchestration/stages/precision_debug_substages.py`
  - DiagnoseSubstage.transition：合并 FixSubstage 横切逻辑（route_to 门控实施分支）
  - DiagnoseSubstage.resolve_condition：合并 FixSubstage 路由（resolved/applied_partial/regression/partial_output/case_skipped/pool_exhausted/retry）
  - DiagnoseSubstage._phase_prompt：追加实施段（build/test/commit/API红线/返回协议）
  - DiagnoseSubstage abort：bump_counters=True（D3）
  - **删除 FixSubstage 类（:2162-2422）**
  - schema 映射（:159/:351）：删 precision_fix.json 条目
- `src/ascendc_devkit/orchestration/precision_debug_tree.py`
  - import 删 FixSubstage；children 删 AtomicStage(FixSubstage())
  - transition_table 删 fix 节点；diagnose 节点并入原 fix 条件；diagnose_refine done→diagnose
  - docstring 更新

### agent / skill / schema
- `.claude/agents/ascendc-precision-diagnose.md`：allowed_tools 加 Edit
- **删** `.claude/agents/ascendc-precision-fix.md`
- `ascendc-precision-fix` skill 实施方法并入 `ascendc-precision-diagnose` skill；**删** fix skill 目录
- `precision_diagnose.json` schema 加 fix_code_log；**删** precision_fix.json schema
- **保留** `.precision-fix/` 目录（run_tests artifact 路径，与 fix skill 无关）

### 测试（迁移 FixSubstage → DiagnoseSubstage，行为不变）
- `tests/ut/orchestration/test_precision_debug_stage.py`（TestFixSubstage 等）
- `tests/ut/orchestration/test_per_output_sinking.py`
- `tests/ut/orchestration/test_precision_debug_agent_abort.py`（abort bump 断言调整）
- `tests/ut/orchestration/test_precision_debug_runtime_refine.py`
- `tests/ut/adapters/test_schema_loader.py`（删 ascendc-precision-fix 用例）
- `tests/ut/skills/test_precision_debug_selfcontained.py`（删 ascendc-precision-fix）

### docstring 清理
- workflow.py / runtime_config.py / base.py / precision_debug.py 提到 fix stage 的注释

## 八、验证（§3.1 TDD）

UT（StubBackend，不依赖 NPU/LLM）：
- 路由回归：printf/comment_bisect/bounds_check/scope_guard transition_table 零变化（快照断言）
- 收敛闸：cc_cap → advance_past_failure_type；attempt_cap → advance_current_case
- 实施路由：resolved/applied_partial/regression/partial_output/need_printf/need_comment_bisect/retry
- route_to 门控：printf_location 不进实施分支；fix 缺省进实施分支
- diagnose_refine done → diagnose
- abort bump=True

## 九、收益定位（诚实）

省：上下文重建（~15min×有效 fix 次数）+ 空转 spawn + 路由/agent/skill/schema 复杂度。**非 10h 耗时大头**（大头是判据错位 ~3h + run_tests 全量 ~3h）。此融合是架构简化 + 结构性省时，与判据对齐并行推进。

## 十、实施状态与验证结果（落地记录）

**状态：代码 / agent / skill / schema / 测试全部落地，UT 全绿。**

### 代码层
- `precision_debug_substages.py`：`DiagnoseSubstage.transition` 合并 FixSubstage 7 类横切逻辑（route_to 门控实施分支，`_route_to` 缺省 → 实施模式并留 warn 日志 §1.3）；`resolve_condition` 合并实施路由；`_phase_prompt` 追加实施段；abort `bump_counters=True`（D3）；**FixSubstage 类已删**；schema 映射删 `precision_fix.json`。
- `precision_debug_tree.py`：children 7 子阶段（无 fix）；transition_table `diagnose` 节点并入原 fix 条件（resolved/applied_partial/regression/partial_output/skip_more/skip_done/need_printf/need_comment_bisect/retry + 新增 route_to_printf）；`diagnose_refine.done → ("diagnose","corrective")`。

### 测试迁移（FixSubstage → DiagnoseSubstage）
按 §七清单迁移 6 文件 + 实施中发现并补迁第 7 文件：

| 文件 | 关键改动 |
|---|---|
| `test_precision_debug_stage.py` | TestFixSubstage→TestDiagnoseSubstageImpl；`_PHASE_DEFAULTS`/expected_phases 删 precision_fix.json；vortex 涡旋测试 seed route_to=fix 显式进实施模式 |
| `test_per_output_sinking.py` | transition_table `["fix"]`→`["diagnose"]`（partial_output） |
| `test_precision_debug_agent_abort.py` | 删 test_diagnose_abort_preserves_corrective_cycles（D3 废止 light 契约）；test_diagnose_abort 断言 cc==1 |
| `test_precision_debug_runtime_refine.py` | `_write_fix_phase`→`_write_diagnose_impl_phase`；transition_table self-loop 目标 fix→diagnose |
| `test_schema_loader.py` | precision_fix 用例 → diagnose fix_code_log optional 用例 |
| `test_precision_debug_selfcontained.py` | _PHASE_SKILLS/_SUB_AGENTS 删 ascendc-precision-fix |
| **`test_precision_debug_routing.py`**（任务#1 调研漏，全量 UT 兜出） | `test_group_has_eight_substages_in_root_tree`→seven，删 "fix" |

### 实施时确认的语义调整（诚实记录）
- **D3 落地**：diagnose abort `bump_counters=True`，原「diagnose preserves corrective_cycles」light 契约废止（diagnose 从 light 迁入 redeploy-heavy）。
- **resolve_condition 路由信号修正**：`resolved` 路由看 dc.`case_resolved`（由 transition 从 `case.status=resolved_pending` 派生），非 `already_resolved`（后者是 agent _summary 字段，transition 消费它设 case.status）。原 `test_resolve_already_resolved` 误用 dc.already_resolved 字段 → 改为 transition 端到端验证（summary.already_resolved → case.resolved_pending → resolve=="resolved"），顺带补上此前缺失的 transition 覆盖。
- **裸 checkpoint fall-through**：diagnose 退出由 `_time_budget_exhausted` 控制（墙钟），rounds 是 run_tests 框架计数、diagnose 仅透传；原 test_resolve_done_linear_to_fix（断言无条件 "done"→交 fix）契约随合并移除，裸 checkpoint 现 fall-through 到 "retry"（实施模式默认：等 agent 产出实施证据）。

### 验证结果
- **全量 UT：3713 passed**（排除 heavy_llm，§3.11；含本合并新增/迁移用例）。
- precision_debug 相关 7 文件：329 passed。
- LLM 预检通过（`claude_agent_sdk` 可达）。
- 合并不触及 NPU/CANN 真实链路（纯编排层 + skill 文档）；precision_debug 无专门非 heavy_llm ST（端到端属 heavy_llm）。

### 未覆盖（诚实）
- **heavy_llm 端到端未跑**（§3.11）：precision_debug 真实 agent 全流程（diagnose 自实施 build/test/commit）需用户确认后跑；日常迭代靠 UT + 非 heavy ST + 预检兜底，特性交付/PR 合并前应由用户在关键节点决策跑一次。

### 遗留（非本问题产权，仅记录）
- `tests/ut/domain/test_support_domain.py:22` 硬编码 `/home/x00584171/...` 绝对产物路径 → collection error（§1.7 违规，预存，与本合并无关）。
- `.claude/skills/ascendc-precision-adapter/`（TUI 驱动）仍引用 fix 阶段（transition.py + SKILL.md:141），预存的 5 对 7 阶段分歧；需单独同步或废弃决策。
