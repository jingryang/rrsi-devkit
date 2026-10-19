# 07 — ForkJoin 并发分支 run.log binding 缺失（AU-8）L3 方案分析

> 对应 L1 `04-audit-followups.md` **AU-8**。
> 阶段：**已拍板（方案 B），已实施**——见 L4 `08-forkjoin-runlog-binding-impl.md`（UT + §3.9 真链路 `@llm` 用例均绿）。以下为调研期候选评估留档。

## 1. 问题陈述

ForkJoin 并发分支（详设 `tiling` / `anchor-forkjoin` 的标准结构，每模板一支）整段执行
（`agent_spawn`/`agent_session`/`stage_iteration`/`agent_stream`/`✓done`）在 per-op `run.log` 不可见。
AU-6 修复（opencode SSE daemon 经 `spawn_context_thread` 继承调用线程 binding）对 **单 spawn** 与
**批跑 op 间并发** 有效，对 **ForkJoin 单 op 内分支并发** 无效——实测 run `20260727-020230-bec0db`
（gelu，**已含 AU-6 修复 `527f0f1`**，本仓 `output/` 下只读分析）ForkJoin 段仍 0 条分支日志。

## 2. 根因（代码层已确认）

- `bind_run_log` 把 run.log 句柄写入 contextvars `_run_log_ctx`，绑定在 **exec/dispatch 线程**
  （`infra/log_capture.py` docstring：bound "in the exec's worker thread"）。
- 顺序阶段跑在绑定线程内 → Logger 行落 run.log；opencode SSE daemon 经 `spawn_context_thread`
  → `copy_context().run()` 继承 binding（AU-6）→ `agent_stream` 也落 run.log。
- **ForkJoin 分支不同**：`graph_executor._execute_forkjoin` 在 `concurrency != "1"` 时用
  `ThreadPoolExecutor.pool.map(_run, pending)` 并发跑分支。`_run` 在 pool worker 里执行，而
  **Python `concurrent.futures` 的 pool worker 是独立线程、contextvars context 为空**（`log_capture.py`
  docstring 明示：plain new `Thread` / pool worker 各自空 context，正是 P-BC1 要的 sibling 隔离）
  → pool worker 里 `current_run_log_file()` 返回 `None` → 该分支所有 `Logger._emit` 只写
  console/batch log、不落 per-op run.log。

**根因的讽刺**：让 P-BC1（批跑 sibling 隔离）和 AU-6（SSE daemon 继承）成立的**同一套 contextvars
设计**，恰好把 ForkJoin 分支留空——因为 ForkJoin 分支跑在 pool worker 里、且 `_run` **没有（再）
bind**。批跑 exec worker 之所以有 binding，是 dispatch 层对每个 op 显式 `bind_run_log`；ForkJoin 的
`_run` 没有等价动作。

**关键区分（与 P-BC1 不冲突）**：P-BC1 要的是**跨 op** 隔离（不同 op 写不同 run.log）；ForkJoin 分支是
**同一 op 内**的并发，本就该共享同一 per-op run.log。给 ForkJoin 分支建立 binding 不违 P-BC1。

## 3. 候选方案（§1.2 四把尺子）

| # | 方案 | 落点 | 可维护 | 可扩展 | 可诊断 | 架构合理 | 评估 |
|---|---|---|---|---|---|---|---|
| **B** | **copy_context 流入 pool**：`_execute_forkjoin` 提交前 `ctx = copy_context()`，`pool.map(lambda x: ctx.run(_run, x), pending)` | `graph_executor`（L3 orchestration） | ✓ 复用 AU-6 的 `copy_context` 模式，单一心智 | ✓ 结构性：分支自动继承**所有**当前 contextvars（`run_log` + `op_name` + 未来新增），新并发结构无需记得加 bind | ✓ | ✓ graph_executor 不直接调 infra bind API，只「让 context 流过去」——infra 拥有 binding、orchestration 只消费，分层干净 | **主修复** |
| A | `_run` 内显式 re-bind：dispatch 线程先捕获 `run_log_path`/`op_name`，`_run` 起手 `bind_run_log(path)` + `bind_op_name(...)` | `graph_executor` | ✓ 显式、表意清晰 | △ 每个并发结构都要记得 re-bind；新增 contextvar 要同步加 bind 点（易漏） | ✓ | △ graph_executor 直接依赖 infra `log_capture` 的 bind API（轻微跨层） | 备选 |
| D | branch Runner / `branch_exec` 自己 bind | Runner 层 | ✗ Runner 不该知道 run.log 路径 | ✗ | △ | ✗ 把 infra 关注点塞进 Runner，职责错层 | 否决 |
| 兜底 | `Logger._emit` 无 binding 时 warn | infra | — | — | ✓ 留信号 | △ 合法无 binding 场景多，噪音 > 收益 | 仅作可观测兜底，非主修复 |

**copy_context 的隔离语义**（B 的关键安全性）：`ctx.run()` 的写隔离于该次 run——分支 `set` contextvars
不泄漏给兄弟分支、不回写 dispatch（反而**强化**隔离，优于裸共享）。故 B 不会让分支互相串扰 run.log。

## 4. 推荐（§1.2 组合原则）

> **B（主修复，copy_context 流入 pool）+ 真实 ST 守护（补 §3.9）**。

- **B** 结构性消除「ForkJoin 分支无 binding」，复用 AU-6 既定模式，自动覆盖 `op_name`（顺带修 AU-7 在
  ForkJoin 下的归属），未来新增 contextvar 零成本继承。唯一短板「可诊断」由 ST 守护补上。
- **不加**「无 binding warn」兜底（合法无 binding 场景多，噪音 > 收益）；改以 ST 守护回归。
- **不选 A**：表意清晰但每个并发结构都要记得 re-bind，新增 contextvar 易漏——可扩展性劣于 B，与 §1.2
  「同类新情况能自动正确归位」相悖。

## 5. 验证（B + ST）

- **UT（确定性，复现 pool 边界，不需真 LLM）**：stub backend 在 ForkJoin（`concurrency != "1"`）下从
  pool worker 发 Logger 行 → 断言该 op 的 run.log 含分支的 `spawn`/`stream` 行（red 复现 AU-8 → green
  修复后通过）。重点测 `ThreadPoolExecutor` 边界 + `copy_context` 继承。
- **heavy_llm ST（§3.9 真实链路，交付前）**：真实 opencode ForkJoin（如 `self_evolve_op` 详设 tiling 两
  模板），断言 per-op run.log 含两分支 `agent_stream`（由用户按 §3.11 决策跑）。
- **回归**：P-BC1 sibling 隔离 UT（`test_concurrent_threads_runlog_isolated`）不变；AU-6 single-spawn ST
  不变；`concurrency == "1"` 串行路径行为不变（本就有 binding）。

## 6. 与现有修复的关系

- **B 与 P-BC1**：不冲突。P-BC1 是跨 op 隔离（不同 op 不同 run.log，靠各自 dispatch 线程 bind）；B 是
  同 op 内分支共享 binding。B 的 `ctx.run()` 写隔离反而强化而非破坏隔离。
- **B 与 AU-6**：同模式（`copy_context`），互补（AU-6 管 SSE daemon 线程，B 管 ForkJoin pool worker）。
- **B 与 AU-7**：`op_name` 也是 contextvar，随 `copy_context` 自动继承 → ForkJoin 分支的 `agent_stream`
  attribution（`[op/stage/branch]`）一并正确。

## 7. 开放问题（实施前确认）

1. **`copy_context()` 捕获时机**：`_execute_forkjoin` 入口即可（此时 dispatch 线程的 binding 已在场）。
2. **`concurrency == "1"` 串行路径**：本就跑在绑定线程内、有 binding；B 可选择统一走 `ctx.run`（无害）
   或仅并发路径加——倾向统一，减少分支差异。
3. **ST 形态**：UT（stub pool 边界，确定性）是否即够，还是必须 heavy_llm 真实 opencode ForkJoin
  （§3.11 用户决策）——倾向 UT 守护 pool 边界 + 交付前补一次 heavy_llm。
