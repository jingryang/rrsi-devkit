# L3 方案分析 — teardown 回退判据完备化：teardown 只在循环真退出时触发

> 状态：**调研态·修订（2026-08-27，初版 D1(resuming 参数) 被用户质疑后重设计为 B 案，待拍板）**。
> 本工作 L1 于 2026-08-16 立项后孤儿化（L1 P4），2026-08-27 批 99c4c0 复现后复活并补证。

## 0. 本质

teardown rollback 的设计目的 = 「debug **真退出**时清理未验证的半成品，让下游
（converge/eval）拿到 best_commit」。现状把该语义挂在「发生了 abort」上（runner
:383 对每次 abort 调 teardown，**先于**重试判定 :384），而 infra-retry 时代任何
abort 后都会 re-spawn+resume——rollback×resume 组合 = 系统性制造「会话记忆 vs
工作树」发散，agent 工作被反复蒸发重做（L1 P2：w1 25min 重做被销毁 → w3 花 35min
重做 → w4 根因修复 6d59046 被剥）。

正确不变式（用户 2026-08-27）：**resume ⇒ 绝不动代码；只有 debug 真退出进入
teardown 才 rollback。**

## 1. B 案（修订主修复）：teardown 调用位移到「循环真退出」分支

`_run_stage_teardown` 全工程**唯一调用位**是 runner.py:383，在 infra-retry 循环内、
重试判定（:384 `_is_cancelled() or not _infra_backoff_retry()`）**之前**。修法 =
把调用移进 terminal 分支（判定之后）：

```python
while True:
    result = self._execute_actions(actions, result_state)
    _ares = result.get("agent_result")
    if not is_infra_failure(_ares):
        break                                  # 干净成功，不 teardown（现状保持）
    _abort = getattr(_ares, "aborted", None)
    if _is_cancelled() or not self._infra_backoff_retry(stage):
        result["is_terminal"] = True
        if _abort:
            result_state = self._run_stage_teardown(   # ← 仅循环真退出时触发
                stage, result_state, _abort)
        break
    self._check_timeout(stage.name)            # 将重试（re-spawn+resume）
    actions = stage.actions(result_state, iteration)   # ← 树原样保留，构造性不回退
```

- **零新参数、零 stage 侧分支**：teardown 语义回归纯粹的「stage 正在退出」
  finally 钩子；「resume ⇒ 不动代码」由**调用位置构造性保证**（retry 分支根本
  不调 teardown），不靠每个 stage 正确 honor 一个布尔（不变式由约定→由结构，
  §1.2）；
- precision teardown 本体不动（仍无条件 rollback——它只在真退出时被调到）；
- :375-380 的旧注释（「每次 kill 前触发一次，保证重采样从 known-good baseline
  起步」）随修订删除。

## 2. 旧 D5 理由的证伪记录（为何当初每次 kill 都回退）

- :375-380 注释的理由「重采样从 known-good baseline 起步」写于**跨 run resume
  存在之前**；step-37 sidecar auto-resume（20260810 批）落地后，每次 re-spawn
  实际都 resume 同一 session（turn-stall-resume-escalation L1 P1 实证「永不进入
  Phase 2 fresh」）——两个机制独立落地、未考虑交互，同该 L1 记录的交互缺口模式；
- 99c4c0 实证 resume 主导下「baseline 回退」= 记忆/树发散 + 成果蒸发（L1 P2）
  ——为已不存在的形态（fresh 重采样）付出真实代价。

## 3. 边界与代价（诚实记录）

- **异常出口绕过 terminal 分支（反面质疑补，语义变化白纸黑字）**：backoff
  通过后 `_check_timeout`（:389）抛出（deadline 恰在退避睡眠后到）——异常直接
  冲出循环，terminal 分支不执行，**teardown 不触发**，带脏树退出 stage。现状
  （先 teardown 再判定）此路径有回退。B 案下该路径**故意保留树**：(a) 后续
  resume：sidecar 在、session 记忆与树一致（正是本工作要的不变式）；(b) 真
  halt/收尾：退出清洁由 converge 自己的 `_converge_to_best_commit`
  （checkout best）兜底——那是下游消费 best 的权威点位，非新增兜底。此行为
  需以 UT 固化（异常出口 → 树未被 teardown 触碰）；
- **fresh re-spawn 失去 known-good baseline**：若某次 re-spawn 不 resume（sidecar
  不存在/session-gone 退化 fresh），新 agent 会看到上一被杀会话的未提交残留。
  现状该路径不在迭代内发生（resume 主导）；真退出由 terminal teardown 兜底清洁；
  会话内由 agent 自身 commit 纪律覆盖。**若未来实现 Phase-2 退化 fresh**
  （turn-stall-resume-escalation 的待办），需重开「下一次 spawn 将看到什么」
  判据——记录为演进前提，不预建机制（§1.14）；
- terminal 判定本身（`_infra_backoff_retry` 预算耗尽 / cancelled）不动——本方案
  只改 teardown 与它的先后关系；
- 与 step-97 互补分工不变：97 让 kill-3 形态根本不 kill；本项兜真退出语义。

## 4. 初版 A 案（resuming 参数）的否决记录

初版提议 `teardown(..., resuming: bool)` 由 runner 传值、stage 分支。否决理由
（用户质疑成立）：把「循环去向」知识压进钩子参数，**不变式靠每个 stage 正确
honor 布尔来维持**——约定式而非构造性；B 案在调用位上直接消灭「会 continue 还
调了 teardown」这个状态，A 案只是让 stage 知道后自己躲开。

## 5. 原则对照

§1.2 四尺子（可维护=调用位单点/可扩展=新 abort 种类自动归位（循环退出与否唯一
判据）/可诊断=teardown 日志语义纯化/架构=生命周期层持钩子语义）；§1.15（teardown
触发单点）；§1.14（构造性保证优先）。

## 6. 待拍板

1. B 案本身（调用位移）是否认可；
2. `interrupt_reason` 参数保留现状（teardown 内部仅日志用，precision 未用——
   保留不影响；是否顺手清理留实施期定）。
