# L1 — 问题记录：precision_debug 配置冗余 + 无 per-run 配置层 + 默认值过大

> 层级：L1（客观事实，不提方案/不排顺序/不写决策）。方案见 `03-impl-config-refactor.md`。
> 关联：[[precision-debug-loop-control]] P5（candidate_loop budget）的根治演进；
> [[precision-debug-closure-hardening]] P4（墙钟预算硬编码）的配置层补全。

## Pc1 — candidate_loop 字段冗余：无门控读者，与 attempt_count 语义重复（中等，技术债）

**事实**：`control.json` 顶层的 `candidate_loop`（`max_plans` / `current_tried` / `tried_plan_ids`）三个字段在整个 precision_debug 闭环中**没有任何门控逻辑读取它们做路由决策**。它们是死数据，且与 per-case 字段语义重复。

**证据**：
- `_candidate_pool_exhausted`（`precision_debug_substages.py`）的判定**纯为 `len(pending_hits) == 0`**（[[precision-debug-loop-control]] P5 已把绝对计数 `current_tried >= max_plans` 改成纯 pending 判定）——从不读 `candidate_loop.current_tried` / `max_plans`。
- case 级止损实际由框架 `FixSubstage.transition` 读 `attempt_count >= max_attempts_per_case` 做 advance；`candidate_loop.current_tried`（"已 verified 计数"）与 `attempt_count`（"已尝试次数"）语义重复。
- `candidate_loop.tried_plan_ids` 与 `current_case.tried_fix_plan_ids` 语义重复（都记已试 plan id）。
- [[precision-debug-loop-control]] P5 选了"语义重定义"方案（O1：current_tried=verified 计数），**保留了 candidate_loop 字段**但此后已无门控读者——违 §2.5（唯一通路，不留旧债）：保留一个无人读的字段即是旧债。

**影响**：fix skill prompt（`fix.md`）维护 candidate_loop 的 while 循环边界（`current_tried < max_plans`）、8 处 `current_tried += 1` / `tried_plan_ids.append` 写回——全是维护死数据的无用功，且给 agent 制造"有预算约束"的错觉（实际约束是 `pending == 0` + `max_attempts_per_case`）。

## Pc2 — 4 个 loop knob 无 per-run 配置层，配置散落（中等）

**事实**：precision_debug 闭环的 4 个可调参数——`max_iterations`（大循环上限）、`max_corrective_cycles`（fix↔printf 小循环上限）、`max_attempts_per_case`（case 止损）、`time_budget_sec`（墙钟预算）——配置来源散落、无统一的 per-run 配置层：
- `time_budget_sec` 在 [[precision-debug-closure-hardening]] P4 配置化了，但放在 `orchestration-config.json` 的 `timeouts` 段（与其他 3 knob 分离）。
- `max_iterations` / `max_corrective_cycles` / `max_attempts_per_case` 是模块硬编码常量 / control.json 散落默认值，无统一全局配置入口。
- 无"全局配置 → 每次运行配置 → 硬编码常量"的三层所有权；用户无法在不改代码的情况下针对单次运行调参（如某次 run 想放宽 max_iterations）。

**证据**：
- 旧 `precision_debug_substages.py`：`_DEFAULT_PRECISION_MAX_ITERATIONS` 等模块常量；`max_attempts_per_case` 由 `build-failed-case-queue.py` per-case 写死 `10`。
- `orchestration-config.json`：只有 `timeouts.precision_debug_time_budget_sec`，无 `max_iterations` 等的配置入口。
- 用户诉求：4 knob 应「既可以全局配置（`orchestration-config.json`）又可以 pre-run 配置（`control.json`）；pre-run 初始值 = 全局配置；手动修改 control.json 后 pre-run 优先级更高」。

**影响**：调参需改代码；单次 run 无法独立调参；4 knob 配置位置不统一（time_budget 在 `timeouts`，其他散落），认知负担。

## Pc3 — 默认值过大（轻微）

**事实**：3 个 loop knob 的默认值偏大，单次 precision_debug run 耗时/成本过高。
- `max_iterations=30`（大循环 30 轮）、`max_corrective_cycles=8`、`max_attempts_per_case=10`。
- 用户指定调整为 `15` / `6` / `8`（`time_budget_sec=12000` 不变）。

**影响**：默认配置下单次 run 烧满预算的概率高，NPU/LLM 成本大。

## 关联问题

- [[precision-debug-loop-control]] P5（candidate_loop budget）——本工作 Pc1 是其根治演进：从"语义重定义 + 保留字段"到"识别冗余 + 彻底移除"。
- [[precision-debug-closure-hardening]] P4（墙钟预算硬编码）——本工作 Pc2 把 time_budget 从 `timeouts` 段迁到 `precision_debug` 顶级段，与另 3 knob 聚合，补全三层配置。
