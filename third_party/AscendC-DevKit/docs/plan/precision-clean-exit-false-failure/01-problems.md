# L1 问题记录 — precision 干净退出被误标失败（incident 20260825-153847-ccad38）

> 记录客观事实，不提方案。run：`output/20260825-153847-065ba7/20260825-153847-ccad38`
> （batch_id UTC 20260825-153847 = CST 23:38 启动，晚于 step-88/89/90 全部提交——**修复后代码的行为**）。

## P1：成功/软门升级被无条件标 failed（P40 升级标记越权）

**现象**（run.log 2662 行终态）：

```
[ERROR] Workflow completed with failed stages: ['self_evolve_op',
 'self_evolve_op/precision_debug', 'self_evolve_op/precision_debug/run_tests']
```

dispatcher 非零退出（EX_DATAERR），batch 按失败计数。

**与事实的矛盾**（三源交叉）：

- events.jsonl（权威源）：`18:08:06 iteration_complete run_tests ok` + `stage_complete`，无 halt/escalate/stalled 事件；
- report.json：`self_evolve_op/precision_debug/run_tests/run_tests -> ok`（551.2s）；
- `run_tests_iter-0/result.json`：`golden_used: True`，20 case 全过（0 failed）→ 首轮全过，无 diagnose spawn（正确路由）；
- state_snapshot.json：`node_status` 中 `.../precision_debug/run_tests` = **failed**（叶子与其两个祖先传播）。

**机理**：

1. precision composite 内部路由（`precision_debug_tree.py`）：
   `"run_tests": {"all_pass": ("__escalate__:passed", "validation"), "exhausted": ("__escalate__:exhausted", ...)}` —— 终态靠升级冒泡出组；
2. 根表（workflow.py）：`precision_debug` 的 `passed` **无条目**（线性前进 cannbench_adapt）、`exhausted → cannbench_adapt`（D9 软门，设计上前进评分）；
3. graph_executor 升级分支（P40）对**任何** `__escalate__` 的 bubbling 原子叶无条件 `node_status["failed"]` —— 注释声称的目的是「bubbled **halt** 的 resume 权威」，但 `passed`/`exhausted` 根本不 halt；
4. `_group_status` 把 failed 传播到组与根 → dispatcher 出口 `failed_nodes` 非空 → ERROR + EX_DATAERR。

**历史对照**：20260802-171400-794e81（旧五阶段树 scope_guard/bounds_check/fix）无此终态——该树不经过 composite 的 `__escalate__:passed` 出口。本次是新 composite 树**首次干净 all_pass 退出**触发（此前批跑或经 diagnose/exhausted 出口、或被截断）。

**波及面**（`__escalate__` 全量生产者）：

- `precision_debug_tree.py`：`passed`（线性前进）/`exhausted`（软门）→ 被误标；
- `precision_debug_a5.py`：同形（`baseline_passed`/`all_pass`/`exhausted`）→ 同病；
- `design_tree.py` + workflow 根表：design 组 `exhausted → __halt__` → 该类**本该**标（resume 需重入 halt 源）。

## P2：scorer 超时误冠「前置环境缺失」（错误冒充）

同 run 02:41:37：`CannbenchScorer: eval timed out (30 min)` → WARN
`→ infra: cann-bench eval 前置环境缺失 (op 'unique'): eval timed out (30 min)`。

`subprocess.TimeoutExpired`（eval 子进程 30 分钟不退出，kernel/driver hang 类）被套上
`_infra_error` 的「前置环境缺失」前缀——两个**不同的外部故障类**（环境缺依赖 vs 进程挂死）
互相冒充，违反 §1.10（诊断信号分层）。error_type=infra 本身正确，仅 message 失真。

## P3（关联事实）：eval 30 分钟超时无留档

run 目录 `subprocess/` 为空——eval 子进程的 stdout/stderr 未落 run 目录（超时路径直接
return，无 dump）；后续诊断只能依赖 op worktree 侧 cann-bench 自有日志。

**边界归属事实**：超时属外部 infra（kernel/driver hang 类）。是否处置的决策见 L3 边界节。

## 关联

- 同 run 另一缺陷（step-90 租约写 control.json 抢跑 init-checkpoint）产权在
  `card-isolation-subprocess-fix/01-problems.md` P4——事故同源发现、分属两工作线。

## P4：eval 超时丢弃子进程 partial 输出

`subprocess/` 为空的真相：`_log_eval_failure` 只对 returncode≠0 落盘（且只落 stderr）；
`TimeoutExpired` 分支直接 return，异常自带超时前捕获的 stdout/stderr（kernel hang 前最后
在跑哪个 case——定位唯一线索）全部丢弃。

## P5：all_pass 退出背靠背双 converge

ccad38 实证：transition 内 `_sync_debug_result` 终态收敛（rollback+redeploy+smoke），
GE 升级分支**又**收敛一次——同 commit 秒级间隔两次全量收敛 ~46s 空烧。`_converge_to_best_commit`
的「始终 rollback+redeploy」理由（跨迭代编译非确定性，507035）成立，但不覆盖秒级连发场景。

## P6：eval 超时 dump 的 bytes 写文件 + dump 未防护（20260826 回放实证）

回放 ccad38（修复后代码真实重跑）在 eval 30 分钟超时点炸出
`[ERROR] Stage 'cannbench_eval' failed: data must be str, not bytes`——
`TimeoutExpired.output/stderr` 部分路径是 **bytes**（即使 subprocess text=True），
`_write_stream.write_text` 写 bytes 抛 uncaught，把本应干净 return infra 的超时路径
变成 stage failed/aborted。P4 的落盘引入（P4 dump 是新的，bytes 是它的具体 bug）；
且 dump 自身失败未防护——可观测性步骤绝不该把错误路径变成硬崩溃。
