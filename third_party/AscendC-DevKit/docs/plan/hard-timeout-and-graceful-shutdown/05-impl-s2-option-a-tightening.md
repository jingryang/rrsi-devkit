# S2 实施方案 — Option A 软放开收紧（硬墙引入后的交互）

> 层级：**L4 / 实施方案**。记录「改哪个函数、什么顺序、怎么验证」。
> 决策依据见 `02-analysis.md`（L3）D7 的「Option A 软放开的收紧」条款。S1（backend 硬墙 + 协议 + runner 传 deadline + event）已落地；本切片补**硬墙与 Option A 软放开的交互修正**。

## 范围

S1a 已吸收原 L3「S2 信号 + 接线」切片的 `AgentResult.aborted` 字段、runner 算剩余预算传入、`agent_aborted` event。S1b 补了 claude 硬墙物理实现。**S2 剩余唯一项 = D7「Option A 软放开的收紧」**：修正硬墙引入后对 Option A 输出保留语义的回归。

## 问题（硬墙引入后的回归）

Option A（`runner._check_timeout`，runner.py:497-510）的设计：stage deadline 超时但**上一轮 agent 成功**（`_last_iter_ok=True`，有 salvageable 产物）→ **软放过**（warn + 继续），不 raise。因为 raise `StageTimeoutError` 会**丢弃** stage 的在途产物（`run_stage` 捕获后 re-raise 不返回 state，`graph_executor` 当控制异常上抛）。

`_last_iter_ok` 在每轮 iteration 末由 `agent_result.status == "ok"` 置位（runner.py:323-325）。

**硬墙引入后的回归**：硬墙到点把 spawn 杀成 `status="fatal", aborted="hard_timeout"`。该 fatal result 把 `_last_iter_ok` 翻成 `False` → **下一轮边界检查 raise `StageTimeoutError`** → **丢弃之前那轮的 salvageable 产物**。

- 硬墙**前**：spawn 会跑过 deadline 继续，Option A 持续软放过直到 stage 自然结束（`is_terminal` / `max_iterations`），salvageable 产物随 state 正常返回得以保留。
- 硬墙**后**：spawn 被杀成 fatal → `_last_iter_ok=False` → 下轮 raise → 产物丢。**硬墙把 Option A 的输出保留语义打破了。**

## 方案（D7「用 aborted 区分」的最小正确实现）

**硬墙杀（`aborted != None`）的 spawn 不更新 `_last_iter_ok`** —— abort 不携带 agent 证据（spawn 被 deadline 杀前没真跑/没产出），不该盖掉 prior ok 的 salvageable 信号。

```python
# runner.py:323-325（_run_stage_body 内）
_agent_res = result.get("agent_result")
if _agent_res is not None:
    # S2 (D7 Option A 收紧): 硬墙杀（aborted≠None）的 spawn 不携带 agent 证据
    # （deadline 杀前没真跑），不更新 _last_iter_ok —— 保留 prior ok 的 salvageable
    # 信号。否则硬墙回归 Option A：abort 翻 _last_iter_ok=False → 下轮边界 raise →
    # 丢弃 salvageable 产物（硬墙前 spawn 跑过 deadline、Option A 持续软放过保产物）。
    if not getattr(_agent_res, "aborted", None):
        self._last_iter_ok = (_agent_res.status == "ok")
```

### 为何不是「gate→raise」或「force-terminal」

- **gate `_last_iter_ok and not aborted` → raise**：raise 丢 salvageable 产物（`run_stage` re-raise 不返回 state）—— 与 Option A 保产物初衷相悖，否决。
- **abort 时 force `is_terminal`**：对 stuck 首 spawn（`_last_iter_ok=False`、无产物）会静默以空 state 终止，丢失「超时无产出」信号；不如维持现状（stuck → `_last_iter_ok=False` → 下轮 raise 给信号）。
- **本方案（不更新 `_last_iter_ok`）**：abort 后 `_last_iter_ok` 维持 True → 边界持续软放过 → loop 跑到 `max_iterations` 自然返回带 salvageable 产物的 state。**产物保留 ✓，无 raise-丢产物 ✓。** 副作用：abort 后每轮会再发一个「即刻被硬墙杀」的 spawn（doomed spawn），但由 `max_iterations` 有界 + 每个 spawn 即刻 abort（毫秒级），可接受。真正的「abort 后让 stage 善终止步」属 S3（teardown / stage 对 aborted 的消费），不在 S2。

### 边界正确性

- stuck 首 spawn 硬墙杀：`_last_iter_ok` 初值 `False`，abort 不更新 → 维持 `False` → 下轮边界 raise（给「超时无产出」信号）。✓
- 普通 fatal（`aborted=None`，真跑了但失败）：照旧更新 `_last_iter_ok=(status=="ok")=False` → 下轮 raise。✓（abort 豁免只针对 `aborted≠None`，不放宽所有 fatal）
- ok → abort：`_last_iter_ok` 维持 True → 持续软放过 → 跑到 max_iterations 返回带产物的 state。✓

## 改动清单

### `orchestration/kernel/runner.py`（唯一改动）

- `_run_stage_body` 内 `_last_iter_ok` 置位点（runner.py:323-325）：加 `if not getattr(_agent_res, "aborted", None):` 守卫，使硬墙杀的 spawn 不更新该标志。

## TDD 顺序

1. 写 UT（**红**）：
   - `test_last_iter_ok_preserved_after_hard_aborted_spawn`：2 轮（iter1 ok / iter2 `aborted="hard_timeout"`）→ run_stage 后 `_last_iter_ok is True`（abort 没盖掉 iter1 ok）。
   - `test_non_aborted_fatal_still_clears_last_iter_ok`：2 轮（iter1 ok / iter2 `status="fatal", aborted=None`）→ `_last_iter_ok is False`（普通 fatal 仍清，豁免只给 aborted）。
2. 跑 → 红（现状两个都 `False`，因为 fatal/abort 都盖 `_last_iter_ok`）。
3. 加 `aborted` 守卫 → 绿。
4. 全量 UT 回归。

## 验证

- 新增 2 个 UT 绿；现有 `TestSoftStageTimeout` 5 个 UT 不回归（`test_last_iter_ok_false_after_non_ok_agent` 用 `aborted=None` 的 partial，仍清 `_last_iter_ok`）。
- 全量 UT 零回归。
- **不跑** heavy_llm ST（真机硬超时属 S5，§3.11 用户确认）。

## 不在 S2 范围

- abort 后让 stage 善终止步（避免 doomed spawn 循环）→ S3（teardown / stage 消费 aborted）。
- `Stage.teardown()` / `uninterruptible` / cann-bench precondition gate → S3。
- SIGTERM / 进程组 / atexit → S4。
- heavy_llm ST → S5。
