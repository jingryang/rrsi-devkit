# P3: diagnose transition 过度复杂——190 行承载全部路由决策

**状态**: 待修
**层归**: L1 问题记录（只述事实，方案在 L3）

## 哪里坏了？

`DiagnoseSubstage.transition`（precision_debug_substages.py:2216-2402）约 **190 行**，在一个方法里承载了十几个业务状态的路由决策：route_to、attempt 耗尽、pool_exhausted、compilation skip、corrective_cycles 耗尽、refine、stall 检测、early-bisect 降级、regression、partial_output、already_resolved、run_iter_counter、case_skipped/more_cases。难以阅读、难以测试、难以修改。

## 凭什么这么说？（证据）

### 事实 1：transition 190 行，混合纯路由 + 副作用

`DiagnoseSubstage.transition` 同时做了：
- **读 agent 申报**（`route_to`/`error_migration_evidence`/`regression_evidence`/`partial_outputs`/`already_resolved`）
- **写 control.json**（`corrective_cycles`/`run_iter_counter`/`diagnose_stalls`/`refine_pending`/`case` 状态）
- **路由决策**（skip/advance/降级二分/stall 触发）
- **历史物化**（`_append_history`）

一个方法四种职责，违反 §1.2 可维护、§2.5 单一职责。

### 事实 2：多计数器在 transition 内交错递增

transition 内至少触碰 5 个计数器：
- `corrective_cycles`（+1，cc 耗尽 advance）
- `refine_cycles`（剥皮链）
- `diagnose_stalls`（无进展计数）
- `attempt_count`（case 级）
- `rounds`（run 级）
- `run_iter_counter`（目录级）

这些计数器互锁（stall 达阈 → 降级二分 → reset cc），任何一处错 → 路由错。

### 事实 3：逻辑层层嵌套难追踪

```
transition → _handle_abort? → _deduplicate → summary → route_to?
  → printf_location? → 纯分析收尾
  → 实施模式：case? → attempt 耗尽? → advance
    → pool_exhausted? → compilation? → advance
    → already_resolved? → resolved_pending
    → partial_output? → improved
    → cc+1 → cc 耗尽? → advance_past_failure_type
    → dc re-extract → stall 达阈? → 降级二分
    → _validate_phase_json → _append_history → _sync_phase_latest → _sync_debug_result
```

## 影响

- **可维护性差**：改一处路由要理解全 190 行上下文。
- **可诊断性差**：路由决策分散在 transition 各处，日志难对应"为什么走这条路由"。
- **测试困难**：覆盖 190 行的分支组合是天文数字。

## 与既有问题边界

- **P4**（多计数器交错）：P3 是"transition 太大"的结构问题，P4 是"计数器互锁"的语义问题，同源（过度复杂）。
- **P2**（agent 申报）：transition 里大量 `summary.get(...)` 读取 agent 申报信号，是 P2 的直接消费方。
