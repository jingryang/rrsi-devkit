# P4: 多计数器交错失控——五个计数器互锁难维护

**状态**: 待修
**层归**: L1 问题记录（只述事实，方案在 L3）

## 哪里坏了？

precision_debug 用 5 个以上计数器管理循环，且它们**互相影响**（一个耗尽触发另一个重置），语义纠缠：
- `rounds`（run 级大循环）
- `corrective_cycles`（diagnose↔printf/comment_bisect 小循环）
- `refine_cycles`（剥皮链）
- `diagnose_stalls`（diagnose 无进展）
- `attempt_count`（case 级 stop-loss）
- `run_iter_counter`（目录编号）

## 凭什么这么说？（证据）

### 事实 1：计数器互锁逻辑

run_tests transition:
```python
cp["corrective_cycles"] = 0     # 全量回归 → 清零
cp["refine_cycles"] = 0         # 同语义清零
cp["diagnose_stalls"] = 0       # 同语义清零
```
diagnose transition:
```python
cp["corrective_cycles"] += 1
if cc >= max_corrective_cycles: _advance_past_failure_type; cc=0  # 耗尽→advance+reset
if diagnose_stalls >= _DIAGNOSE_STALL_THRESHOLD: 降级二分; cc=0   # stall→reset cc
```

### 事实 2：counter 语义依赖阶段流转

- `corrective_cycles` 在 run_tests 清零、在 diagnose 累加、耗尽 advance
- `refine_cycles` 在 run_tests 清零、在 diagnose_refine 累加
- `diagnose_stalls` 在 run_tests 清零、在 diagnose 累加、达阈触发二分降级

任何"清零点遗漏"或"累加点多增"都会让循环提前/延迟退出。历史 bug 已多次因此类问题（rms_norm 20260821 就是 deploy_fail_streak 计数误增）。

### 事实 3：预算语义互相覆盖

`max_corrective_cycles`、`max_iterations`、`max_attempts_per_case`、`time_budget_sec`、`cut_streak_threshold` 五个预算同时约束循环，语义重叠（cc 耗尽 vs stall vs rounds 超限都能退出），难以判断"实际由谁退出"。

## 影响

- **可维护性**：五个计数器 + 五份预算，改任何一个都要想清对其他四个的影响。
- **可诊断性**：循环退出时，日志难回答"为什么退"（cc 耗尽？stall？time budget？attempt？）。
- **违反 §1.2**：多计数器的语义本可收敛为单一"循环轮次 + 语义止损"（如只用 rounds + 一个 semantic stop signal）。

## 与既有问题边界

- **P3**（transition 过度复杂）：P4 的计数器交错是 P3 复杂度的一部分，但 P4 独立指"计数器语义"问题。
- **P1/P2**（agent 申报）：`deploy_fail_streak`（P1）是计数器之一，`attempt_count` 由 agent 的 case 状态驱动——计数器与 agent 申报耦合。
