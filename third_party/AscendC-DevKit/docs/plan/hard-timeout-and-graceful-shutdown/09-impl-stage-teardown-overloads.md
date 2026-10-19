# Stage teardown 重载实施方案 — precision-debug git reset（D5 具体重载）

> 层级：**L4 / 实施方案**。S3 落了 `Stage.teardown()` hook + runner 触发（`06-impl-s3`）；本切片补 L3 D5 约定的「具体 stage 重载在各 stage 自己的 L4 展开」。第一项：**precision-debug 回退到最后一个可用版本**。

## 范围

- **A3 precision-debug**：`_PrecisionDebugSubstage` 重载 `teardown` → 被硬超时中断时 `git reset --hard best_commit`，回退到最后一个全量验证通过的 commit（用户需求：「让 debugger 回退到最后一个可用版本」）。
- **A5 precision-debug**（`_A5PrecisionDebugSubstage`）：同一语义（best_commit + op_dir），但属 A5 侧——按 ownership 边界（memory `codegen-a5-ownership-boundary`：A5 侧改动先确认），**本切片不含，标记待同事确认**。
- **codegen 清理 half-written**：L3 D5 列的另一例，语义未定（哪些 half-written 文件、是否 git 级）——本切片不含，待 design/codegen 域明确后单独 L4。

## 背景：为何回退到 best_commit

precision-debug 的 constructive rollback 保证（memory `self-evolve-ac0-global-convergence` + `toolkit-home-...`）：
- `_snapshot_best_commit`（precision_debug_substages.py:672）在 **RunTestsSubstage 全量回归通过后**写 `git rev-parse HEAD` → `cp["best_commit"]`。故 best_commit 是「最后一个全量验证通过」的 commit。
- FixSubstage verify-then-commit：fix 改动先 verify 再 commit，但 best_commit 要等下一轮 RunTests 全量确认才更新。
- **中断瞬间**（硬超时杀 spawn）：工作树可能有半成品 fix（dirty）或 HEAD 已推进到「commit 但未全量验证」的 commit → 都不是 known-good。`git reset --hard best_commit` 回退到 known-good，让 resume/下一轮从干净态起步。

## 改动清单

### `orchestration/stages/precision_debug_substages.py`
`_PrecisionDebugSubstage` 加 `teardown`（所有 phase substage 继承：run_tests/diagnose/fix/printf_location/comment_bisect/bounds_check/scope_guard 任一被中断都回退）：
```python
def teardown(self, state, *, interrupt_reason: str) -> "State":
    import subprocess
    from ascendc_devkit.infra.logger import Logger
    cp = _load_control(state)
    best = cp.get("best_commit") if cp else None
    op_dir = _operator_dir(state)
    if not best or not op_dir:
        return state  # 无 known-good 锚点 / 无 op_dir → 无可回退，no-op
    try:
        subprocess.run(["git", "reset", "--hard", best], cwd=str(op_dir),
                       check=True, capture_output=True, timeout=30)
        Logger.warn(f"precision-debug teardown ({interrupt_reason}): rolled "
                    f"back op repo to best_commit {best[:8]}")
    except Exception as e:  # noqa: BLE001 — best-effort（runner 已 try/except 兜外层）
        Logger.warn(f"precision-debug teardown: git reset --hard "
                    f"{best[:8]} failed: {e}")
    return state
```
- idempotent（已在 best_commit 则 no-op）+ best-effort（失败只 warn）+ 秒级（git reset <30s timeout）。
- 无 best_commit / 无 op_dir → no-op（首跑未建立 known-good 锚点时安全）。

## TDD

1. UT（红→绿）：mock `subprocess.run`，构造 state（control.json best_commit=X + op_dir），调 `FixSubstage().teardown(state, interrupt_reason="hard_timeout")` → 断言 `git reset --hard X` 在 op_dir 被调用；best_commit 缺失 → 不调（no-op）。
2. 全量回归。

## 验证
- 新 UT 绿；全量 UT 零回归。
- **不跑** heavy_llm ST（真机 precision-debug 硬超时回退属 S5，§3.11 用户确认）。

## 不在本切片
- A5 precision-debug teardown（`_A5PrecisionDebugSubstage`）→ 待同事确认（ownership）。
- codegen half-written 清理 → 待语义明确，单独 L4。
- heavy_llm ST → S5。
