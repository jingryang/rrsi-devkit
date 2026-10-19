# 20 — resume 强杀续跑：实施方案（L4）

> 工作线：step-16（覆盖问题 P29）
> 状态：**已实施**（2026-07-04）
> 关联 L3：`19-resume-hardkill-analysis.md`；L1：`06-problems.md` P29

## 决策摘要（见 L3）

逐节点原子 flush state snapshot——让 snapshot 真正耐用、继续作 resume 唯一权威。不重引入 events-rebuild（违反 `aa472e3` + §2.5）。前向修复：新 run 强杀可续；旧 run（snapshot 已停留初始态）不在救援范围。

## 改动（函数级）

### `orchestration/graph_executor.py`
1. **`__init__`**：新增 `on_state_progress=None` 参数 → `self._on_state_progress`。注释说明：仅主 executor 接收；branch_exec 传 None（避免并发/局部态竞争 snapshot 文件）。
2. **`_execute_node`**：重构为单一 chokepoint——resume-skip 仍提前 return（无变化不 flush）；其余 dispatch 到 atomic/forkjoin/sequential 后，捕获 `prev_ns = dict(state.node_status)`，dispatch 完成后若 `state.node_status != prev_ns` 则**同步更新 `self.latest_state = state`**（关键：使 dispatcher 的控制异常 handler——Ctrl+C/cancel/timeout/decision-pending——snapshot 的是「最后已完成节点」的完成态，而非滞后态）并 `_persist_progress(state)`。SideTask 走 else 分支（`_launch_sidetask` 后 state 不变，guard 自动跳过 flush）。
3. **新增 `_persist_progress`**：best-effort——回调存在则调用，`try/except` 包裹，失败只 `Logger.warn` 不中断 run（§1.2 可诊断、不掩盖；持久化 hiccup 不崩主流程）。
4. **branch_exec 两处自构造**（`_execute_forkjoin` 与 `_launch_sidetask` 内）：显式传 `on_state_progress=None`——ForkJoin 分支在线程池跑、局部 state 非规范态；只有主 executor 在 `merge_forkjoin` 后由 `_execute_node` 末尾 flush 一次。

### `application/dispatcher.py`
1. **`import os`**（原先未导入）。
2. **`_write_state_snapshot`**：改原子写——写 `state_snapshot_path.with_suffix(".tmp")` 再 `os.replace(tmp, final)`。POSIX 原子 rename：mid-write 强杀最坏保留上一份完整 snapshot，绝不截断/清空。
3. **GraphExecutor 主构造**（`dispatch` 内）：传 `on_state_progress=lambda s: _write_state_snapshot(workspace, s)`。
4. `dispatch_single_stage`（respond 路径）不经 GraphExecutor、自带 snapshot 写，**不动**。

### 测试（TDD，先红后绿）
新增到 `tests/ut/orchestration/test_graph_executor.py`：
- `TestStateProgressFlush`：`test_on_state_progress_called_per_node`（3 叶 + group = 4 次 flush、node_status 单调增长）、`test_on_state_progress_skipped_for_resume_skip`（预置 completed 的节点不触发 flush）、`test_forkjoin_flushes_only_merged_once`（多分支只 flush 1 次）、`test_persist_failure_is_non_fatal`（回调抛异常 run 仍完成）。
- `TestResumeAfterKill`：`test_kill_then_resume_skips_completed`（**核心不变式**：`_KillStage` 首次抛 KeyboardInterrupt 模拟强杀 → 回调用真 `_write_state_snapshot` 落盘 → 捕获后从盘 load node_status → 重 execute 断言 a 被 skip、只重跑 b/c）、`test_latest_state_current_after_interrupt`（**Ctrl+C 不变式**：KeyboardInterrupt 后 `executor.latest_state` 必须带最后已完成节点的 completed 标记——否则 dispatcher 的 handler 用滞后态覆盖逐节点 flush）、`test_write_state_snapshot_is_atomic`（写后合法 JSON + 无 `.tmp` 残留）。
- **dispatch 层中断→持久化→resume**（`tests/ut/application/test_application.py::TestInterruptResumePersistence`，parametrized）：`_RaisingBackend` 在第一个 agent spawn（requirement 阶段）抛指定控制异常 → dispatch 捕获 → 断言 snapshot 含 `entry/context` completed（持久化不变式，Ctrl+C 曾坏在此）→ `dispatch(resume_from)` 断言 entry/context 未被重入（events `stage_enter` 计数仍为 1）。覆盖 **Ctrl+C（KeyboardInterrupt→EX_SIGINT）/ cancel（RunnerCancelledError→EX_SIGINT）/ timeout（WorkflowTimeoutError→EX_TIMEOUT）** 三种 handler 型中断。

### 中断→resume 矩阵覆盖

| 中断原因 | snapshot 写入者 | 覆盖 |
|---|---|---|
| SIGKILL / OOM / 断电 | 仅逐节点 flush（handler 捕获不到） | ✅ GraphExecutor UT `test_kill_then_resume_skips_completed`（在 executor 边界抓异常、直读 flush snapshot，绕过所有 dispatcher handler）+ 原子写 UT |
| SIGINT（Ctrl+C） | dispatcher KeyboardInterrupt handler（`latest_state`）+ flush | ✅ dispatch UT `keyboard` + GraphExecutor `test_latest_state_current_after_interrupt` |
| 显式 cancel（RunnerCancelledError） | dispatcher handler + flush | ✅ dispatch UT `cancel` |
| WorkflowTimeout / StageTimeout | dispatcher handler + flush | ✅ dispatch UT `timeout` |
| DecisionPending | dispatcher handler + flush（+ respond） | ✅ 同 handler 写机制（与上三条共享代码路径）+ Runner 级 `TestDecisionPendingResumeLoop` |

## 验证（前台实跑，§3.3）

- 新测试先红（5 fail：`GraphExecutor.__init__() got an unexpected keyword argument 'on_state_progress'`）→ 实现后全绿；`test_latest_state_current_after_interrupt` 先红（`latest_state.node_status` 为空）→ latest_state 修复后绿。graph_executor 共 23 passed。
- 聚焦回归集（graph_resume / dispatcher_resume_bridge / stage_failure_status / forkjoin / tiling_precise_rollback / graph_executor）：55 passed。
- **全量 UT `tests/ut/`：1523 passed**（含 3 个 dispatch 层中断 parametrized 用例），0 回归。
- 相关 ST（stub/mock-backed，非 heavy）：`test_design_pipeline_e2e` 6（含 resume）+ `test_integration` 28（含 snapshot/resume/eventlog）= 34 passed。

## 诚实边界（§3.11 / §3.9）

- **已覆盖（确定性 UT，过 dispatch 全路径 + 真 snapshot IO）**：Ctrl+C / cancel / timeout 的「中断→handler 写 snapshot→resume 跳过」闭环；强杀的「无 handler、仅逐节点 flush→resume 跳过」+ 原子写抗截断。SIGINT 经 Python 默认转 `KeyboardInterrupt`，UT 抛的就是 handler 实际捕获的同型异常。
- **未跑（heavy_llm / 真实链路，§3.11 需用户跑前确认）**：真实 OS 信号端到端——`scripts/e2e_self_evolve.sh` 拉起 → 中途 `kill -9`（SIGKILL）/ Ctrl+C → `ascendc-devkit run --resume <id>` 验断点续跑。NPU 当前被占，列为 PR 合并前节点（§3.9 真实链路守护）。
- 旧 run `20260704-053333-c2911b` 不在本修复救援范围（snapshot 已停留初始态）；用户按既定路 A 重跑。
