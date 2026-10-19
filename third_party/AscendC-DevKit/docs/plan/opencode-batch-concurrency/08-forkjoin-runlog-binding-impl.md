# 08 — AU-8 实施（copy_context 流入 ThreadPoolExecutor）L4

> 对应 L1 `04-audit-followups.md` AU-8、L3 `07-forkjoin-runlog-binding-analysis.md`（已拍板 **方案 B**）。
> 范围：让 ForkJoin / SideTask 在 `ThreadPoolExecutor` pool worker 里跑的分支**继承** dispatch 线程的
> `contextvars` run.log/op_name binding，使分支的 `Logger` 行（含 opencode SSE `agent_stream`）落进 per-op
> run.log。**不动线程模型**（仍是既有 `ThreadPoolExecutor`），只让 context 流入 worker。

## 改动 1 — `infra/log_capture.py`：新增 `context_callable` helper

与既有 `spawn_context_thread`（给后台**线程**继承 context）成对：给**提交到 pool 的 callable** 继承 context。

```python
def context_callable(fn):
    """Wrap ``fn`` so a ``ThreadPoolExecutor`` worker runs it inside a copy of
    THIS thread's context — inheriting run.log/op_name bindings (AU-8).

    Pool workers start with an empty ``contextvars`` context, so without this
    wrap a ForkJoin/SideTask branch running in a worker cannot see the dispatch
    thread's ``bind_run_log`` binding → its ``Logger`` output (incl. opencode
    SSE ``agent_stream``) is dropped from per-op run.log.

    Contract: ``fn`` READS contextvars (the ForkJoin/SideTask case — branches
    read the binding; dispatch sets it once). Concurrent ``ctx.run`` of one
    shared Context is read-safe; verified no branch path SETS contextvars
    (grep: orchestration/kernel/capabilities 无 ``bind_run_log``/``_run_log_ctx.set``).
    """
    ctx = contextvars.copy_context()           # 捕获于提交线程（binding 在场）
    @functools.wraps(fn)
    def _runner(*args, **kwargs):
        return ctx.run(fn, *args, **kwargs)    # worker 在该 context 拷贝里执行 fn
    return _runner
```

- 导出加入 `__all__`。
- `import functools`（文件顶部）。

## 改动 2 — `orchestration/graph_executor.py`：两处 pool 提交包 `context_callable`

**2a. `_execute_forkjoin`**（并发分支，`pool.map(_run, pending)`）：

```python
with ThreadPoolExecutor(max_workers=max_workers) as pool:
    for idx, cstate in pool.map(context_callable(_run), pending):
        results[idx] = cstate
```

- `concurrency == "1"` 串行路径（`for ic in pending: _run(ic)`）**不动**——它跑在已 bind 的 dispatch
  线程内、本就有 binding（最小改动；统一走 `ctx.run` 无功能收益只增开销）。

**2b. `_launch_sidetask`**（`self._side_pool.submit(_run)`）：

```python
fut = self._side_pool.submit(context_callable(_run))
```

- SideTask 同型缺口（pool worker 跑 `branch_exec._execute_node`），一并修。

## 验证（TDD 先红后绿，§3.1）

**UT-1（infra 层，确定性）** — `tests/ut/infra/test_log_capture.py`，仿 `test_spawn_context_thread_inherits_caller_binding`：
- `test_context_callable_pool_worker_inherits_binding`：主线程 `bind_run_log` + `bind_op_name`，把
  `context_callable(_probe)` 提交到 `ThreadPoolExecutor`，断言 worker 里 `current_run_log_file()` ==
  主线程的句柄、`current_op_name()` == "MyOp"、`Logger.action(...)` 行落进 run.log。
- `test_plain_callable_in_pool_drops_binding`（对照，文档化 bug）：不包 `context_callable` 直接提交 →
  worker 里 `current_run_log_file() is None`、Logger 行**不落** run.log（证明为什么需要 helper）。

**UT-2（graph_executor 层，端到端）** — `tests/ut/orchestration/test_forkjoin.py`：
- `test_forkjoin_branch_logger_reaches_runlog`：`bind_run_log` 后跑一个 `concurrency="thread"` 的
  ForkJoinGroup（两分支），分支 stage 的 `transition` 里发 `Logger.action("agent_stream", <tag>)`；
  断言两 tag 都进了 run.log（red = 当前 pool worker 丢 binding；green = 改动 2a 后落盘）。

**回归**：`tests/ut/infra/test_log_capture.py`（含 P-BC1 `test_concurrent_threads_runlog_isolated`、
AU-6 `test_spawn_context_thread_*`）不变；`test_forkjoin.py` / `test_graph_executor.py` /
`test_tiling_forkjoin.py` 全绿。

**heavy_llm ST（§3.9 真实链路，交付前由用户按 §3.11 决策跑）**：真实 opencode ForkJoin（如 self_evolve_op
详设 tiling 两模板），断言 per-op run.log 含两分支 `agent_stream`。日常迭代靠 UT-1/UT-2 守护 pool 边界。

## 不做

- 不加「`Logger._emit` 无 binding 时 warn」兜底（合法无 binding 场景多，噪音 > 收益）。
- 不动 `concurrency == "1"` 串行路径（已有 binding，无需包）。
- 不抽通用「context-aware executor」（avoid-overdesign；当前两处用 `context_callable` 已收口，足够）。
