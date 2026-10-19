# S3 实施方案 — stage 善终：teardown 钩子（D5）+ uninterruptible（D6）

> 层级：**L4 / 实施方案**。记录「改哪个函数、什么顺序、怎么验证」。
> 决策依据见 `02-analysis.md`（L3）D5（teardown）/ D6（uninterruptible）。**D8（report 收口）见末尾「D8 重 scope」——L3 原处方有缺陷，本切片不含，待用户确认重 scope。**

## 范围

- **D5 `Stage.teardown()` 钩子**：stage 被 spawn 硬墙杀（中断）瞬间的收尾（finally 语义，stage 自重载）。本切片落**hook + runner 触发 + 通用 UT**；具体 stage 重载（precision-debug `git reset`、codegen 清理）按 L3 约定在各 stage 自己的 L4 展开，不在本切片。
- **D6 `Stage.uninterruptible`**：声明式标志，保护「进行中不被 deadline 抢占」（cann-bench 硬超时也走完评测）。
- cann-bench 声明 `uninterruptible = True`；precondition（编译通过）由其 transition 的 `smoke_passed` 判断（已有，cannbench_eval.py:77），不需主流程特殊逻辑。

## 背景：两类 stage 的互补分工

| stage 类型 | 长耗时在哪 | 硬墙（S1）能否中断 | 善终机制 |
|---|---|---|---|
| spawn 型（precision-debug/codegen/design） | spawn 内 | 能（硬墙杀 spawn） | **D5 teardown**（spawn 被 abort 后收尾） |
| transition 型（cann-bench，子进程跑在 transition） | transition 内（阻塞，无检查点） | 不能（无 spawn） | **D6 uninterruptible**（边界检查不 raise，让 transition 跑完） |

cann-bench `actions()→[]`（确定性 stage），子进程 `subprocess.run` 在 `transition()`（自带 30min timeout :259）。**问题**：cann-bench iteration 起始的边界检查（runner.py:274）若发现 workflow deadline 已过 → raise → **跳过 cann-bench → 无 eval**。uninterruptible 解决：边界检查对 uninterruptible stage 不 raise（记 pending），让 transition 跑完；stage 结束后再 raise（eval_result 已在 state + dispatcher snapshot 保留）。

## D5 改动清单

### 1. `orchestration/base.py`（Stage 基类）
```python
class Stage(StageProtocol):
    ...
    uninterruptible: bool = False   # D6：见下

    def teardown(self, state: State, *, interrupt_reason: str) -> State:
        """被硬超时/中断时的收尾钩子（finally 语义，D5）。默认 no-op。

        runner 在 spawn 被硬墙杀（aborted≠None）后、stage 返回前调用。
        stage/substage 重载做善终（precision-debug fix→git reset --hard
        best_commit；codegen→清理 half-written 临时文件）。

        约定：秒级收尾，**必须 <60s**、必须 idempotent。重型操作（cann-bench
        评测）不进 teardown，走 uninterruptible（D6）。best-effort：异常不阻塞
        退出（runner try/except 兜住）。"""
        return state
```

### 2. `orchestration/kernel/runner.py`（触发点）
`_run_stage_body` 内 `result = self._execute_actions(...)`（:300）后、`transition`（:312）前：
```python
_agent_res = result.get("agent_result")
if _agent_res is not None and getattr(_agent_res, "aborted", None):
    # D5：spawn 被硬墙杀 = stage 被中断 → 跑 stage 收尾钩子（finally 语义），
    # 然后止步（不再迭代）。teardown best-effort：异常/超时只 log 不阻塞。
    result_state = self._run_stage_teardown(
        stage, result_state, _agent_res.aborted)
    result["is_terminal"] = True
```
新增 `_run_stage_teardown`：try/except 包 `stage.teardown(state, interrupt_reason=reason)`，记耗时，>60s warn；异常 log + 用原 state（不阻塞退出）。

> 注：`_agent_res` 在 :323（`_last_iter_ok` 更新）复用同一变量，避免重复读取。

## D6 改动清单

### 1. `orchestration/base.py`
`Stage.uninterruptible: bool = False`（D5 段已含）。

### 2. `orchestration/kernel/runner.py`
- `_run_stage_body` 起始存 `self._current_stage = stage`；重置 `self._pending_timeout_reason = None`。
- `_check_timeout`：deadline 命中时，若 `getattr(self._current_stage, "uninterruptible", False)` → 不 raise，记 `self._pending_timeout_reason = "workflow"|"stage"`，return。
- `_run_stage_body` 末尾（for 循环后、return 前）：若 `self._pending_timeout_reason` → raise 对应 `WorkflowTimeoutError`/`StageTimeoutError`（deferred；此时 stage 已跑完、产物在 state、dispatcher 会 snapshot）。

### 3. `orchestration/stages/cannbench_eval.py`
`CannbenchEvalStage` 加 `uninterruptible = True`。

## TDD 顺序

### D5
1. UT（红）：stage 的 spawn 被 abort → runner 调了 `stage.teardown`（用记录调用的 fake stage）+ stage 不再迭代（is_terminal）+ teardown 异常不阻塞（fake teardown raise → runner 仍正常返回）。
2. 加 `Stage.teardown` + runner `_run_stage_teardown` + 触发点 → 绿。

### D6
1. UT（红）：uninterruptible stage，边界检查时 workflow deadline 已过 → **不 raise**，stage transition 跑完；stage 结束后 → raise（deferred）。对比：普通 stage 同情况 → 边界即 raise（跳过 transition）。
2. 加 `uninterruptible` + `_check_timeout` 分支 + deferred raise → 绿。
3. cann-bench `uninterruptible = True`。

### 回归
全量 UT 零回归。

## 验证

- D5/D6 新 UT 绿；cann-bench 标志就位。
- 全量 UT 零回归。
- **不跑** heavy_llm ST（真机 cann-bench 硬超时走完 + precision-debug git reset 属 S5，§3.11 用户确认）。

## D8 重 scope（本切片不含，待确认）

L3 D8 原处方：「把 `_generate_report` 收进 `FinalizeStage.teardown()`，删 dispatcher 手写调用」。**深 probe 发现两处缺陷**：

1. `GenerateReport` action（FinalizeStage.actions:109）落 runner `else: pass`（runner.py:557「consumed by transition」），但 `FinalizeStage.transition` 不引用它 → **GenerateReport 是 inert marker**；真正 report 生成只在 dispatcher `_generate_report`（dispatcher.py:1048）。
2. dispatcher `_generate_report` 仅在 PreconditionError(:955) + 正常完成(:997) 调用；**timeout(:940)/env/card/sigint 路径无 report**（硬超时场景目前就无 report）。
3. FinalizeStage 只在 workflow 跑到 finalize 时执行；timeout / early-stage 中断时**没跑** → 收进其 teardown 覆盖不到异常路径 → 删 dispatcher 调用会**丢 PreconditionError 路径 report**，且不补 timeout 路径。

**「report on all graceful-exit paths」（硬超时优雅退出想要的）是 dispatcher 层 finally-block 的事，与 D8 原处方相反。** 建议 D8 重 scope 为：dispatcher `_generate_report` 改 `finally`（或每个 except 分支补调用），覆盖含 timeout 在内的所有退出路径；FinalizeStage 的 inert `GenerateReport` action 顺手删（§2.5 唯一通路）。待用户确认后单独切片。

## 不在 S3 范围

- 具体 stage teardown 重载（precision-debug git reset、codegen 清理）→ 各 stage L4。
- D8 report 收口重 scope → 待确认，单独切片。
- SIGTERM / 进程组 / atexit → S4。
- heavy_llm ST → S5。
