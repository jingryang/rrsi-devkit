# P1 timeout 归位 pause 家族 — L4 实施方案（2026-08-30）

> 层级：**L4 / 实施方案**。改哪个函数、什么顺序、怎么验证。
> 上游：`01-problems.md` P1（事实）、`02-analysis.md`（决策：选项 (a)，已拍板冻结）。
> 涉及文件：`src/ascendc_devkit/application/dispatcher.py`、
> `tests/ut/application/test_application.py`。runner/stage/backend 层**零改动**。

## 改动 1：preserve 家族收敛为单点 helper（§1.15/§2.5，先做——为 timeout 加入铺路）

**新增**（`dispatcher.py`，置于 `_preserve_repo_with_hint` 之后）：

```python
def _terminate_preserving(executor, workspace, state) -> State:
    """§1.15 pause 家族单点：非代码缺陷终止的统一收尾。

    latest_state 兜底 → 保留 op_dir 改动（含手动回滚提示）→ 原子落 state
    snapshot（resume 输入）。各分支只保留自己的差异部分（日志 / flag /
    exit code），本三步不许再散点复制。
    """
    state = executor.latest_state or state
    _preserve_repo_with_hint(state)
    _write_state_snapshot(workspace, state)
    return state
```

**替换 5 处既有散点**（行为等价收敛，每分支的日志/flag/return 原样保留在分支内）：

| 分支 | 分支内保留的差异部分 |
|---|---|
| RunnerCancelledError | `Logger.warn` + `return EX_SIGINT` |
| DecisionPendingError | respond/resume 提示 + `_report_on_exit = False`（**先设 flag 再调 helper**）+ `return EX_DECISION_PENDING` |
| EnvironmentNotAvailableError | `Logger.error` + `return EX_CONFIG` |
| CardAcquireTimeout | 卡池耗尽日志 + `return EX_TEMPFAIL` |
| KeyboardInterrupt | `runner.cancel()` + `Logger.warn` + helper 后 `_print_resume_hint` + `return EX_SIGINT` |

**明确不动**：PreconditionError 分支（halt 家族唯一成员，`latest_state →
_rollback_repo_if_needed → snapshot` 原样保留）；`_rollback_repo_if_needed` /
`_preserve_repo_with_hint` 函数本体不改。

## 改动 2：timeout 分支迁移（P1 修复本体）

```python
except (WorkflowTimeoutError, StageTimeoutError) as e:
    Logger.error(f"Timeout: {e}")
    state = _terminate_preserving(executor, workspace, state)
    _print_resume_hint(workspace, output_root)   # 对齐 KeyboardInterrupt 分支的可诊断性
    return EX_TIMEOUT
```

要点：
- `_rollback_repo_if_needed(state)` 调用**删除**（§2.5 不留旧通路）；
- `_print_resume_hint` 让超时用户拿到确切的续跑命令（单算子场景此前无任何续跑指引；
  批场景 batch 脚本已有提示，不冲突）；
- exit code 仍为 `EX_TIMEOUT`：批侧对 124 的既有处理（RESUME 提示、状态归档）不变。

## 实施顺序（TDD，§3.1）

1. **红测 ①** `test_timeout_preserves_not_rolls_back`（镜像
   `test_env_failure_preserves_not_rolls_back` 的结构）：patch
   `GraphExecutor.execute` side_effect=`WorkflowTimeoutError`，断言
   `_preserve_repo_with_hint.called_once`、`_rollback_repo_if_needed.not_called`、
   `exit == EX_TIMEOUT`。改前必红。
2. **红测 ②** `test_timeout_prints_resume_hint`：同结构 patch
   `_print_resume_hint`，断言被调。改前必红。
3. 实施改动 1 → 既有 preserve 族用例全绿（行为等价收敛的回归网：
   `test_env_failure_preserves_not_rolls_back`、`test_preserve_does_not_call_rollback`、
   `TestInterruptResumePersistence` 参数化三例）。
4. 实施改动 2 → 红测 ①② 转绿。
5. 回归确认：`_rollback_repo_if_needed` 的直接单测（`test_rollback_invokes_guard_on_hard_failure`
   / `test_rollback_noop_without_baseline`）与 ST `test_report_generated_on_timeout_path`
   保持绿（后者只断言 report 生成，与树处理无耦合，已核实）。

## 验证

```bash
# 定向（前台执行，§3.3）
PYTHONPATH=src pytest tests/ut/application/test_application.py \
  -k "preserve or rollback or interrupt or timeout"
# 全量 UT（CANN 环境按 §3.6 预检；本仓 pytest 必须 PYTHONPATH=src，见共享机 editable 陷阱）
PYTHONPATH=src pytest tests/ut
# 相关 ST
PYTHONPATH=src pytest tests/st/test_integration.py -k "timeout"
```

不新增 heavy_llm 用例（本改动无 LLM 链路）。真实链路验证由下批批跑的自然 RESUME 场景承担
（对 20260829-142941-49134b 批 `RESUME=1` 复跑 logcumsumexp/interpolate 即是端到端判据：
resume 后 coder 在保住的树上续写而非从零重来）。

## 判据（完成的定义）

- UT/ST 全绿，无 skip 掩盖（§3.4）；
- timeout 后 op_dir 未被 checkout/clean（UT 断言 + 下批实证）；
- resume 该 exec 不产生「记忆-代码分叉」（下批实证：coder 首轮即确认已有文件在场）；
- dispatcher 中 preserve 三步无散点（§1.15 判据：grep `latest_state or state` 仅存在于
  helper 与 PreconditionError 分支）。

## 风险清单（实施时核对）

| 风险 | 缓解 |
|---|---|
| helper 收敛改动 5 个分支引入行为漂移 | 每分支差异部分（flag/日志/return）留在分支内；既有分支用例作回归网 |
| 既有测试 mock 的是 `disp._preserve_repo_with_hint` 模块属性 | helper 以模块级名字调用，mock 依然拦截（已核对 `test_env_failure` 的 patch 方式） |
| 非 worktree 场景树留脏 | 既有先例（cancelled/env/card）；preserve 消息含精确手动回滚命令 |
