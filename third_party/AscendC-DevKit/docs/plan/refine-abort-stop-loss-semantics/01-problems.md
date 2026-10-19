# L1 问题记录 — precision_debug 止损语义缺陷（refine_cycles + abort 熔断）

> 层约定：L1 只记客观事实（哪里坏了、凭什么这么说），不提方案、不排顺序、不写决策。

## P1. refine_cycles 全程累计计数，被动进入也烧配额

- 事实（run `output/20260805-103606-4297d2/20260805-103606-0d7afa`，top_k）：
  - `diagnose_refine` 6 次 stage_enter/complete（跨 2 天），`control.json` 中 `refine_cycles` 只增不减（无任何清零点），最终 >3 触发 `exhausted` 退出组。
  - 进入 `diagnose_refine` 的路径分两类：主动（`fix.applied_partial` 路由，corrective）与被动（fix 的线性后继——路由被拒 / stagnation 拦截时落点）。
  - 代码事实（`precision_debug_substages.py`，修复前）：`DiagnoseRefineSubstage.transition` 无条件 `refine_cycles += 1`；无 reset；`resolve_condition` `> _DIAGNOSE_REFINE_MAX_CYCLES(3)` → `"exhausted"` → 转移表 `("__escalate__:exhausted", "validation")` 出组。
- 后果：① 被动落点（未真正剥皮）也消耗剥皮链配额——机制特征代理了业务语义（§1.10 反模式）；② 计数跨 run 全程累计，一次 run 内后续本可进行的剥皮链被历史计数误杀；③ 链满走 `exhausted` 出组——但「链剥到头」时 run 并未失败，`best_commit` 本应回归验证，直接出组丢失验证通道。

## P2. abort 熔断直接出组，abort 计数不可配置、触发后不清零

- 事实（同 run）：`consecutive_aborts ≥ 3`（`_ABORT_EXHAUST_THRESHOLD = 3` 硬编码）→ `abort_exhausted` → 转移表 `("__escalate__:exhausted", "validation")` 出组。
- 后果：① abort 是瞬态（agent 死亡/超时/上下文爆），熔断 ≠ 调试失败，直接出组浪费当前 best_commit 的修复进度；② 阈值写死不可调；③ 触发后计数不清零，若后续再次进入 spawn 链（如 run_tests 重跑后），残留计数会提前触发熔断。

## P3. fix → diagnose_refine 的 refine_pending 标记未持久化（PR #59 review B1）

- 事实（PR #59 review 实测）：`FixSubstage.transition` 置 `cp["refine_pending"] = True` 位于函数最后一个 `_save_control` 之后；后续唯一写盘 `_append_history` 内部 `_load_control` 从磁盘重载并写回磁盘快照，内存置位丢失。`diagnose_refine` 消费端 `cp.pop("refine_pending", False)` 恒 False。
- 后果：主动路径计数整体失效（P1 的修复目标不生效），剥皮链恢复为无止损连续剥皮。
- 证据：跨阶段测试 `test_fix_applied_partial_persists_refine_pending`（修复前红）。

## P4. abort 阈值注释漂移（PR #59 review M1）

- 事实：`precision_debug_tree.py` printf_location 块注释「consecutive_aborts（≥3 → abort_exhausted）」与 `_ABORT_EXHAUST_THRESHOLD = 2`（改后）不符；comment_bisect 块已用「≥阈值」正确写法。
