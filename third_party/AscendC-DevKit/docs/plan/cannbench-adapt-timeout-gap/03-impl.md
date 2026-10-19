# cannbench_adapt 超时盲区 — L4 实施方案

> 层级：**L4 / 实施方案**。记录改哪个函数、什么顺序、怎么验证。
> 方案见 `02-analysis.md`（L3，已冻结）。

## 改动清单（精确，3 处）

### 1. `runner.py` — 退役 per-node deferred-raise 机制

**a. `_check_timeout` defer 分支（`:578-585`）**：uninterruptible stage 跑过 deadline 改为 `Logger.warn`（可诊断），退役 `_pending_timeout_reason` 赋值。defer 行为（不 raise、让 stage 跑完）保留。

```python
if getattr(self._current_stage, "uninterruptible", False):
    # uninterruptible stage 跑过 deadline 不 raise（软放行链路贯通，L3 冻结方案）。
    # 仅 warn 留痕（§1.2 可诊断）。连续 uninterruptible 链全部跑完后，链路后第一个
    # 非 uninterruptible stage 入口 _check_timeout 真实检查 deadline → 自然 raise 终止。
    if (self._workflow_deadline is not None
            and now > self._workflow_deadline):
        self.Logger.warn(
            f"stage '{stage_name}' uninterruptible — ran past workflow "
            f"deadline (soft let-through)")
    elif (self._stage_deadline is not None
            and now > self._stage_deadline):
        self.Logger.warn(
            f"stage '{stage_name}' uninterruptible — ran past stage "
            f"deadline (soft let-through)")
    return
```

**b. 退役 `raise_deferred_timeout`（`:519-540`）** + `_pending_timeout_reason` 字段（`:105`）+ `_run_stage_body` 重置（`:174`）：per-node 兑现机制整体移除。B1（deferred raise 在 latest_state 捕获前丢产物）整类 bug 表面随之消失 —— 没有 deferred raise，就没有「丢产物」。

### 2. `graph_executor.py` — 去掉 per-node 兑现调用

**`_execute_node` 末尾（`:219-223`）**：删除 `self._runner.raise_deferred_timeout()` 调用 + 其上方的 D6 deferred-raise 注释块（注释描述的「在 persist 后兑现 deferred raise」不再成立）。

### 3. `cannbench_adapt.py` — 声明 `uninterruptible`

**`CannbenchAdaptStage`（`:175-178`，name / default_max_iterations / fail_strategy 处）**：加 `uninterruptible = True` + 注释（与 cannbench_eval 一致：确定性无 agent stage，属软放行收尾，超时后仍要走完）。

## 语义验证（为何这三处够）

走查 workflow 级超时触发后的链路（对照 01-problems.md P1）：

```
precision_debug 内子 stage 入口 _check_timeout（:283）：非 uninterruptible → workflow 过期 → raise WorkflowTimeoutError
  → precision_debug catch（graph_executor.py:366）→ converge + bubble exhausted + break   [不变]
  → 流转 cannbench_adapt
cannbench_adapt（uninterruptible=True）入口 _check_timeout（:283）：defer 分支 → warn，不 raise   [修法 3+1a]
  → transition 跑（wrapper 注入）→ _execute_node 末尾：无 raise_deferred_timeout（修法 2）→ 不 raise
  → 流转 cannbench_eval
cannbench_eval（uninterruptible=True）：同上 defer → transition 跑 kernel_eval（30min subprocess）→ 不 raise
  → 流转 finalize → 跑完 → execute() 正常返回
  → dispatcher 不 catch → 非 EX_TIMEOUT；report 标 overrun
```

链路贯通，P1 修复。情况 A/B（链路后新加非 uninterruptible stage）→ 入口 `:283` 真实检查拦。

## 验证

### UT（TDD，先红后绿）— `tests/ut/orchestration/test_hard_timeout_soft_letthrough.py`（新建）

1. **两 uninterruptible stage 串行 + workflow_deadline 已过期** → 两者 transition 都完整执行（替代原实证陷阱脚本）。构造 StubBackend + 两个 uninterruptible stage（`actions()=[]`，transition 各写一个 marker 到 state）+ `workflow_deadline=now-1` → 断言两个 marker 都在 state。
2. **对照：链后非 uninterruptible stage 入口被拦**。三 stage `uninterruptible(A) → uninterruptible(B) → 普通(C)`，workflow_deadline 过期 → A、B transition 跑完，C 入口 raise `WorkflowTimeoutError`。
3. **回归：单 uninterruptible stage（cannbench_eval 模拟）跑过 deadline 仍跑完 transition**（确保退役 raise 不破坏单 stage 场景）。

### 跑测试

- 新 UT：`pytest tests/ut/orchestration/test_hard_timeout_soft_letthrough.py --no-env-check`。
- runner 相关回归：`pytest tests/ut/orchestration -k "timeout or runner or stage" --no-env-check`。
- 相关 UT 全量：`pytest tests/ut/orchestration --no-env-check`。
- 非 heavy ST：`pytest tests/st -m "not heavy_llm"`（heavy_llm 按 §3.11 待用户确认）。

## 风险与回退

- **风险**：退役 `raise_deferred_timeout` 影响现有 uninterruptible stage（cannbench_eval）跑过 deadline 后的行为。新方案下它跑完不 raise、控制权流转 —— 若它是软放行链路最后（或 finalize 后无 stage），run 正常结束（符合软放行语义）；若后面有普通 stage，普通 stage 入口拦。UT 用例 2 + 3 覆盖。
- **回退**：改动集中在 3 处（runner defer 分支 / graph_executor 调用点 / cannbench_adapt 字段），`git revert` 即可。
