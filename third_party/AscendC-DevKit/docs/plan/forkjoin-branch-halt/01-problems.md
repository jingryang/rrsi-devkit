# ForkJoin 分支失败在 join 点无处理 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：真实 run `20260716-121432-97ea5a`（`self_evolve_op` 全流程，本仓 `output/` 下只读分析，
> 不在本仓复现执行）。该 run.log 内实为**两次进程**：Run 1（20:14 起）在 tiling fork-join 的
> join 合并点抛未捕获 `StateConflictError` 崩溃退出；Run 2（20:46 起 resume）tiling 全过、推进到
> anchor-forkjoin 后在 agent 运行中被中断（无结束事件、无 traceback、无 halt）。
> 本记录只登记 Run 1 暴露的**框架缺陷**；Run 2 的中断是运行环境问题（进程被杀/容器停），非代码缺陷。

## 背景：tiling fork-join 的结构

`detailed-design` 组内 `template-division → tiling[ForkJoin] → anchor-forkjoin[ForkJoin]`。
`tiling` 是动态 ForkJoinGroup（`design_tree.py:_build_tiling_node` + `tiling_branch_factory`），
每个计算模板一条分支（本 run 为 `T1_large_reduce_split` / `T2_small_reduce_whole`），
每条分支是 `split → buffer-kernel → precision-perf` 的 SequentialGroup。各分支在独立线程（独立
`GraphExecutor` + 独立 branch state）跑，`_execute_forkjoin` 用 `ThreadPoolExecutor.map` 等全部
返回后调 `merge_forkjoin` 合并各分支的 `tiling_results` 回主 state。

## 触发事件（agent 产物投递失败；未写 vs 写错目录当前不可判定）

Run 1 中 `T1_large_reduce_split` 的 `split` 子阶段跑满 3 次迭代仍未在指定 cwd 产出
`tiling_split.json`，`contract unsatisfied: tiling_results` → `fail_strategy=halt` 触发
（run.log line 68–74）。三次迭代 `iteration_complete` 均 `result: ok`（agent 正常返回、未崩），
即 cwd 里始终没有该文件。同一时刻 `T2_small_reduce_whole` 分支仍在跑且**最终成功**（20:40:00 完成，
晚于 T1 的 20:37:26 halt）；Run 2 resume 时 T1 的 split 一次即成功。

**定性（更正）**：本触发事件是 **agent 侧产物投递失败**——文件始终没到 cwd。至于具体是
「agent 根本没写」还是「写到了 op_dir/仓根等别处」，**当前无法判定**，且这不是本次分析取证不足，
而是系统性缺口：`_missing_artifact_error` 只在 cwd 内 glob，两种失败产生**完全相同的信号**
（见 `artifact-location-provenance` step 51 P1）。step 51 已实现从 transcript 回收 Write/Edit 的
`file_path` 来区分二者，但该取证**对本次实际使用的 opencode 后端失效**（transcript schema 不兼容 +
tool_use 采集不完整，另见 `opencode-artifact-provenance` step 66）——故本 run 的真实落点已不可复原。
**不将其定性为「非确定性抖动」**（前稿措辞，无直接证据、已更正）：Run 2/T2 成功只能旁证 agent 成功时
瞄准 cwd，说不了失败几轮的行为。

本触发根因（层次 A，落点取证方向）与本文档 P1/P2（fork-join join 点健壮性兜底，层次 B）正交：
即便根因侧完全查清，P1/P2 仍是「任一分支失败后 join 不崩、干净停」的框架刚需。

## P1 — `merge_forkjoin` 把「失败分支从未写入的字段（值为 None）」误判为「非 dict 写入」，与成功兄弟的 dict 冲突而崩溃

**现象**：Run 1 在 join 合并点抛未捕获异常，进程打印 traceback 退出（run.log line 104–152）：

```
ascendc_devkit.orchestration.node_forkjoin.StateConflictError:
ForkJoin child 'T2_small_reduce_whole' writes dict 'tiling_results'
already written as non-dict by a sibling
```

**证据**（`node_forkjoin.py:merge_forkjoin` 逐分支扫 `provides` 字段）：
- T1（失败分支）：`split` 就 halt 了，`buffer-kernel`/`precision-perf` 未跑，其 branch state 的
  `tiling_results` **从未被写入**，值仍是 fork 入口 base 的 `None`。`isinstance(None, dict)` 为
  False → 走非 dict 分支 → `nondict_fields.add("tiling_results")`（line 130）。
- T2（成功分支）：`tiling_results` 是 dict `{T2_small_reduce_whole: {...}}` →
  `isinstance(val, dict)` 为 True → 命中 `if f in nondict_fields`（line 112）→ 抛
  `StateConflictError`（line 113–115）。

即那个「非 dict」值**就是 `None`**——merge 逻辑没有区分「分支主动写了非 dict 值」与「失败分支
根本没写、字段停留在 base 的 None」，把后者当成了合法的冲突写入。异常从 `merge_forkjoin` raise，
经 `_execute_forkjoin`→`_execute_node`→`_execute_sequential`→`dispatch`→`main` **一路无 try/except**
冒泡，直接 traceback 退出（run.log line 123–152）。

**影响**：本该以 `fail_strategy=halt` 语义优雅停止的一次运行，退化成未捕获异常崩溃；终止无
`halt_reason`、无点名失败分支、无正常 halt 落盘路径。

## P2 — fork-join 的 join 点丢弃分支内部的 halt 信号（`is_terminal`/`_stage_failed`/`halt_reason`），失败分支不能使流程干净停止

**现象**：T1 分支内 `split` 触发的 `fail_strategy=halt`（run.log line 74 已打准确 WARN，点名
`split` + 落盘位置错误原因），其停止意图**没有传出 join**。

**证据**：
- `merge_forkjoin`（`node_forkjoin.py` 全文）对 `is_terminal`/`_stage_failed`/`halt_reason`
  **零处理**（grep 确认 0 命中）——分支 state 的这三个信号在合并时被整体丢弃，不进 merged state。
- `_execute_forkjoin`（`graph_executor.py:605–674`）先在 line 651 调 `merge_forkjoin`，
  之后 line 656–668 才把 failed 分支路径标 `"failed"`、把 group 标 `"failed"`；但**全程不设**
  merged state 的 `is_terminal`/`halt_reason`。
- 父 `_execute_sequential`（`graph_executor.py:324–368`）的循环只在 `is_terminal`（line 333）
  或 `_stage_failed`（line 342）为真时 break；对一个仅 `node_status="failed"` 的子 group 不停。
- `_resolve_condition`（`graph_executor.py:598–603`）对 ForkJoinGroup 恒返回 `"default"`，
  而 tiling 组在 transition 表（`design_tree.py`）里没有 `"default"` 路由（表内只有 anchor 回跳用
  的 `infeasible`/`redo_tiling`）→ route=None → 父 sequential **线性前进到下一个子节点
  `anchor-forkjoin`**。

**推论（关键）**：正因 P1 的崩溃先发生，Run 1 才被动停住。若 `merge_forkjoin` 不崩（例如仅对
None 宽容而不补别的），则一个 failed 的 tiling 组在缺少 `is_terminal` 时**不会停，会带着残缺的
`tiling_results`（缺 T1）继续前进到 anchor-forkjoin 及下游**，错误被推到更深、更难定位处。
即：当前那个 `StateConflictError` 崩溃恰是唯一阻止流程带病前进的机制。

**影响**：`fail_strategy=halt`（及分支内任何 halt/terminal 信号）在 fork-join 边界内失效——
既无法让流程干净停止，也无法把「哪个分支、什么原因」传给 dispatcher 的终止诊断。这是 P1
崩溃之外、独立存在的第二个缺陷：即便修好 P1 的 merge 崩溃，缺 P2 会让 fork-join 静默带病前进。
