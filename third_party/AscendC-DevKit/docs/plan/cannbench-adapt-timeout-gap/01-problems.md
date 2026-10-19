# cannbench_adapt 超时盲区 — L1 问题记录

> 层级：**L1 / 问题记录**。只陈述「哪里坏、凭什么这么说」（证据/现象/影响）。
> **不提方案、不排顺序、不写决策**。方案分析见 `02-analysis.md`（L3）；实施方案见 `03-impl-*.md`（L4）。
>
> 与现有工作的边界：
> - `hard-timeout-and-graceful-shutdown/`（step-76）的 **D6** 引入 `Stage.uninterruptible` 机制，目的是「cann-bench 等重型 stage 硬超时也走完，不被 deadline 抢断」。该机制已作用于 `CannbenchEvalStage`（`cannbench_eval.py:61` `uninterruptible = True`）。**本记录指出 D6 的同一个 uninterruptible 机制在 `CannbenchAdaptStage` 上漏声明**，是 D6 落地的一个未覆盖点，不否定 D6 机制本身。
> - `precision-debug-closure-hardening/`（step-73）的软超时收敛 `_converge_to_best_commit` 在 precision_debug 退出前更新 `state.deploy_result`。本记录的 P1 描述「收敛之后、cannbench_eval 之前」的 cannbench_adapt 环节断裂，使收敛产物无法抵达评测。

---

## P1（中等）：cannbench_adapt 未声明 uninterruptible，workflow 级超时后再次 raise 退出，软放行链路断裂

### 现象

precision_debug 触发**工作流级超时**（`WorkflowTimeoutError`）后，按设计应「基于 best-commit 部署 → 流转 cannbench_adapt → cannbench_eval → finalize」拿到一次性 loss（self_evolve_op 的软放行语义）。实际走查表明：路由确实把控制权交到 cannbench_adapt，但 cannbench_adapt 进入后**立即再次 raise `WorkflowTimeoutError`**，其 transition（cann_bench wrapper 注入 + P10 m.def rename + clean rebuild）跑不到，后续 cannbench_eval / finalize 亦不可达。

### 证据

四条事实合起来构成断裂链（均已对照当前代码核实，2026-07-25）：

1. **workflow_deadline 在 precision_debug 捕获后不重置**。`_workflow_deadline` 仅在 `orchestration/kernel/runner.py:78`（初始化 `None`）、`:159-165`（设置 `now_mono + workflow_timeout_sec`）赋值；`graph_executor.py:366-376` 捕获 `(StageTimeoutError, WorkflowTimeoutError)` 后只做 `_converge_to_best_commit` + `_bubble_condition="exhausted"` + `break`，**不清除/顺延 deadline**（graph_executor 全文件无 `_workflow_deadline` 引用）。故进入 cannbench_adapt 时 `now > workflow_deadline` 仍成立。

2. **`_check_timeout` 在每个 stage 的 iteration 循环顶部、先于 transition 调用**。`runner.py:283` `self._check_timeout(stage.name)` 位于循环体首行；`actions()`（`:305`）与 `transition()`（`:332`）在其后。cannbench_adapt 的 `actions()` 返回 `[]`（`cannbench_adapt.py:275-281`，确定性无 agent stage），但仍走 `_run_stage_body` 的 iteration 循环，故 `:283` 必然先执行。

3. **`_check_timeout` 对 workflow_deadline 过期没有 Option A 软放过**。`runner.py` `_check_timeout`：`uninterruptible=False` 且 `now > workflow_deadline` → 直接 `raise WorkflowTimeoutError(...)`；Option A 软放过（`_last_iter_ok=True` 时 warn 不 raise）**只对 stage_deadline 生效**，workflow_deadline 无此豁免。

4. **`CannbenchAdaptStage` 未声明 `uninterruptible`（默认 False），而 `CannbenchEvalStage` 声明了 `uninterruptible = True`**。
   - `cannbench_adapt.py:161` 类定义无 `uninterruptible` 字段 → 默认 False。
   - `cannbench_eval.py:61` `uninterruptible = True`，注释 `:54` 明确「kernel_eval subprocess 跑在 transition 里、无 spawn，backend 硬墙管不到；声明 uninterruptible 让 `_check_timeout` 延后 raise」。
   - `_check_timeout` 的 uninterruptible 分支：只记 `_pending_timeout_reason` 不 raise，让 stage 跑完。

**走查结论**：cannbench_adapt 进入 `_run_stage_body` → 首行 `_check_timeout`（`:283`）→ `uninterruptible=False` + `now > workflow_deadline` → `raise WorkflowTimeoutError`。异常回到根 `_execute_sequential`，因 `node.name != "precision_debug"` → `graph_executor.py:376` `raise` → workflow 终止。cannbench_adapt 的 transition 未执行，cannbench_eval / finalize 不可达。

### 影响范围

- **self_evolve_op 软放行链路在 cannbench_adapt 处断裂**：workflow 级超时后，step-73 收敛（`_converge_to_best_commit` 已更新 `state.deploy_result` 为 best_commit 重编 opp 包）的产物**无法抵达 cannbench_eval**，一次性 loss（`overall_score`）拿不到，self-evolution 无 loss 信号。
- **cannbench_eval 的 `uninterruptible=True` 形同虚设**（在此路径下）：它本是为「硬超时也走完评测」而设（step-76 D6 + P5），但前置 cannbench_adapt 先 raise，cannbench_eval 根本进不去。
- **收敛与评测脱节**：`_converge_to_best_commit` 在 precision_debug 内已完成（`graph_executor.py:373`，先于路由），但 cannbench_adapt 的 wrapper 注入 / clean rebuild（`cannbench_adapt.py:283-343` transition）被跳过 —— 即使后续能到 cannbench_eval，`deploy_result` 也缺 cann_bench wrapper（cann-bench `scan_interfaces` 发现不到算子 → score=0）。

### 触发条件（边界）

本问题仅在**工作流级超时**触发 precision_debug 收敛时暴露：

| 触发类型 | workflow_deadline 状态 | cannbench_adapt 命运 |
|---|---|---|
| **workflow_deadline 过期**（`WorkflowTimeoutError`） | 过期且不重置 | ❌ 再次 raise 退出（P1 暴露） |
| **precision_debug 的 stage_deadline 过期**（`StageTimeoutError`，workflow 仍有预算） | 未过期 | ✅ `_check_timeout` 不 raise，cannbench_adapt 正常跑完 |

`graph_executor.py:366` 对 `StageTimeoutError` 与 `WorkflowTimeoutError` 一视同仁地 converge+bubble，但二者下游 cannbench_adapt 的命运不同 —— 仅 stage_deadline 触发（workflow 未过期）时软放行链路完整。

---

## 关联事实（2026-07-25 实证补充，约束方案空间）

对候选修法「给 cannbench_adapt 加 `uninterruptible=True`」做了实证（两 uninterruptible stage 串行 + workflow_deadline 已过期，经 GraphExecutor 跑）：**第一个 stage 跑完后，`graph_executor._execute_node` 末尾的 `raise_deferred_timeout()` 立即抛 `WorkflowTimeoutError` → 工作流终止 → 第二个 stage 永远到不了**。

即 **deferred-raise-per-node 设计下，至多一个 uninterruptible stage 能跑过 deadline**。软放行链路有两个必须跑过去的 stage（adapt→eval），故「单给 adapt 加 uninterruptible」只把断点从「adapt 入口」挪到「adapt 跑完、eval 之前」，**不解决**。此事实约束 L3 方案空间：要么重置/顺延 deadline 让整条链路不再见过期 deadline，要么改变 deferred-raise 在软放行链路上的兑现时机。

## 证据汇总（关键代码定位）

| 关注点 | 位置 |
|---|---|
| precision_debug 组捕获超时 → converge + bubble | `graph_executor.py:364-376`（converge `:373`、bubble `:374`、非 precision_debug `raise` `:376`） |
| `_converge_to_best_commit`（收敛 best_commit + redeploy） | `precision_debug_substages.py`（由 `graph_executor.py:373` 调用） |
| workflow_deadline 设置（无重置点） | `runner.py:78`（init）、`:159-165`（set） |
| `_check_timeout` 调用点（先于 transition） | `runner.py:283`（iteration 顶部） |
| `_check_timeout` 实现 | `runner.py` `_check_timeout`（uninterruptible 延迟 / workflow 立即 raise / stage Option A） |
| **cannbench_adapt 未声明 uninterruptible** | `cannbench_adapt.py:161`（类定义无该字段，默认 False） |
| cannbench_adapt 确定性无 agent（`actions() return []`） | `cannbench_adapt.py:275-281` |
| cannbench_adapt transition（wrapper + rebuild） | `cannbench_adapt.py:283-343` |
| **cannbench_eval 已声明 uninterruptible（对比）** | `cannbench_eval.py:61`（注释 `:54`） |
| deferred-raise 兑现点（per-node，约束方案） | `graph_executor.py:_execute_node` 末尾 `raise_deferred_timeout()`（c2b807e6/162c7f4e 引入） |
| step-76 D6 uninterruptible 机制（本问题的设计源头） | `docs/plan/hard-timeout-and-graceful-shutdown/02-analysis.md` D6 |
| step-73 软超时收敛（上游产物） | `docs/plan/precision-debug-closure-hardening/03-impl-best-commit-budget.md` |

---

## P2（轻度，架构债）：`_converge_to_best_commit` 调用点分裂 + graph_executor 越层 import 定制函数

> **状态（2026-07-25）：✅ 已修复** —— 同事 step-77（commit `c9508367` + `a3a6571d`，PR #30）引入 `_converge_precision_debug` helper（`graph_executor.py:155`，except + escalation 双通道复用，函数内 import 破循环依赖），消除了越层 import + 调用点分裂。rebase 时带入 main / v0.2.0。

### 现象

`_converge_to_best_commit`（`precision_debug_substages.py:785`，rollback best_commit + `Deployer.deploy` 重编 opp 包）是 precision_debug 组的「终态收敛」语义，但**两个调用点分裂**：

1. **正常终态**：`precision_debug_substages.py:936`，在 `_sync_debug_result` 内（precision_debug 自己的 transition 通路）。
2. **超时终态**：`graph_executor.py:373`，**graph_executor 直接 import 并调用**这个 precision_debug 专属函数。

后者越层：通用编排层（graph_executor）认识了具体领域函数（precision_debug 的 converge），违反 §1.6（编排持有 protocol、不持具体实现）/§1.7（代码仓自闭环）/§2.5（唯一通路，同一收敛语义两处调用）。

### 与 `teardown` 的边界（为何不进 stage.teardown）

converge 含 `Deployer.deploy()` 重编译（分钟级），违反 `Stage.teardown` 契约（`base.py:114-133`：<60s、idempotent、明文「Long work is NOT teardown — it belongs to an `uninterruptible` stage」）。`_PrecisionDebugSubstage.teardown`（`:1000`）已正确只做 `git reset --hard best_commit`（秒级回退、不含 redeploy）。故 converge 属「组级终态收敛」语义，不属于 stage 级 teardown。

### 正解方向（不在本次范围）

让 precision_debug 组暴露**组级终态收敛多态接口**（或让超时路径复用组自己的终态 transition 收敛通路，即 `:936` 那条），graph_executor 只调接口、不认识 converge 内容。统一双调用点 + 消除越层 import。

### 与 P1 的边界

P2 是相邻架构债，**不是 P1 的断裂点**（P1 断在 cannbench_adapt 入口 `_check_timeout`；converge 在 catch 里正常工作）。本次 P1 修复不依赖 P2。P2 单独跟踪。
