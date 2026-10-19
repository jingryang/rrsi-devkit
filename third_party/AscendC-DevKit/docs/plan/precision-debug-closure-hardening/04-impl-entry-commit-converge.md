# L4 — 实施方案：入口 commit + converge 双通道一致化 + HEAD fallback + teardown rollback

> 层级：L4（改哪个函数、什么顺序、怎么验证）。覆盖 L1 P5-P8。
> 决策见 `02-analysis-entry-commit-converge.md`。

## 改动总览

| # | 主题 | 覆盖 | 关键文件 |
|---|---|---|---|
| 1 | 入口 commit codegen 产物（根因） | P5 | `precision_debug_substages.py` `_entry_commit_codegen` |
| 2 | escalation 通道接 converge | P6 | `graph_executor.py` `__escalate__` 分支 |
| 3 | best_commit 缺失 HEAD fallback | P7 | `precision_debug_substages.py` `_converge_to_best_commit` + `_current_head` |
| 4 | teardown reset --hard → RepoGuard.rollback | P8 | `precision_debug_substages.py` `_PrecisionDebugSubstage.teardown` |
| 5 | converge helper 提取（F4） | D7 | `graph_executor.py` `_converge_precision_debug` |
| 6 | teardown HEAD fallback 注释（F5） | D4 | `precision_debug_substages.py` teardown |

## 改动 1 — 入口 commit codegen 产物（P5 根因）

**`_entry_commit_codegen(state) -> None`**（新增，`RunTestsSubstage.actions` 入口首调用）：
- gate：`_control_path(state).exists()` 为假（首轮，control.json 不存在 = init-checkpoint 未跑）。
- repo_root：`state.op_identity.repo_root`，fallback `op_dir`。
- 动作：`git -C <repo_root> add -- <op_dir>`（op_dir scoped）+ `git commit -m "precision_debug entry: snapshot codegen products"`。
- 非 git（`rev-parse --is-inside-work-tree` != true）→ skip；commit 失败 → 诊断（`git status --porcelain` 区分 benign nothing-to-commit vs 危险 dirty，§1.2 可诊断）+ warn 不阻断。
- 幂等：resume 时 run_tests 已 completed → actions 不重入；首轮中途 hard-kill 重入 → "nothing to commit" 被 try/except 吞。
- commit 模型前提已在 docstring 显式声明（见 L3 核心决策）。

## 改动 2 — escalation 通道接 converge（P6）

**`graph_executor.py` `__escalate__` 分支**（`_capture_loopback_feedback` 后、设 bubble 前）：
```python
if node.name == "precision_debug" and escalation_cond != "upstream":
    state = _converge_precision_debug(state, node)
```
条件取舍（D6）：exhausted/abort_exhausted/deploy_broken → converge；upstream 排除；passed 短路。

## 改动 3 — best_commit 缺失 HEAD fallback（P7）

**`_converge_to_best_commit`**：`best = dc.get("best_commit") or _current_head(repo_root)`，替代 `if not best: return state`。
**`_current_head(repo_root) -> str | None`**（新增模块级）：`git -C <repo_root> rev-parse HEAD`，try/except 返 None。

## 改动 4 — teardown reset --hard → RepoGuard.rollback（P8）

**`_PrecisionDebugSubstage.teardown`**：`git reset --hard best`（无 pathspec、动 HEAD，违 D4/R1）→ `RepoGuard().rollback(repo_root, op_dir, best)`（scoped checkout + clean，不动 HEAD，与 converge 同语义）。

## 改动 5 — converge helper 提取（F4）

**`graph_executor.py` 模块级 `_converge_precision_debug(state, node) -> State`**（新增）：
函数内 import `_converge_to_best_commit`（打破循环依赖），dc 提取 + 调用。except 通道 + escalation 通道共用。
`node.name == "precision_debug"` 判定留调用方（外围条件不同：except 无条件、escalation 排除 upstream）。

## 改动 6 — teardown HEAD fallback 注释（F5）

**teardown** `if not best or not op_dir: return state` 加注释：故意不 fallback HEAD（首轮 hard-kill 可能 HEAD 未含 codegen；converge 安全 fallback 是因只在入口 commit 后运行）。消除 teardown vs converge 不一致的读者疑惑。

## 复用（不新造）

- `RepoGuard.rollback`（scoped，与 converge / dispatcher / codegen 同一通路）
- `_snapshot_best_commit` / `_operator_dir` / `_load_control`（既有）
- except 通道 converge 模式（既有，本工作提为 helper）

## 验证（TDD，§3.1；前台跑，§3.3）

`tests/ut/orchestration/test_precision_debug_stage.py`：
- `TestEntryCommitCodegen`：首轮 commit / resume 跳过 / 非 git skip / nothing-to-commit benign / commit 后 HEAD = 入口 SHA。
- `TestConvergeHeadFallback`：best_commit 空 → `_current_head` 取 HEAD → rollback+redeploy 用 HEAD；非 git → return state。
- `TestPrecisionDebugTeardown`：rollback 调 RepoGuard（非 reset --hard）/ best 缺失 no-op / rollback 异常 best-effort。

`tests/ut/orchestration/test_graph_executor.py`：
- escalation converge：abort_exhausted/exhausted/deploy_broken → converge + bubble；upstream → 不 converge；passed → 短路。
- except converge：precision_debug 组超时 → converge + bubble=exhausted + break；非 precision_debug → raise。

## as-built（§10 回填）

- **入口 commit + converge 双通道一致化**：commit `15cb7120`（PR #30 head，base `upstream/v0.2.0 @ d0ce411d`）。
  4 改动（改动 1-4）+ 测试（TestEntryCommitCodegen 2 + TestConvergeHeadFallback + TestPrecisionDebugTeardown + escalation converge 6 条件 + except converge）。
- **F4 helper + F5 注释 + F3 文档**：本修复 commit（接 `15cb7120` 之后）。
- **UT**：`test_graph_executor.py` + `test_precision_debug_stage.py` 共 **222 passed**（1.25s，零回归）；
  全量 `tests/ut/` **3014 passed / 8 skipped**（PR review 时跑，147s，零回归；8 skipped 为既有 git 缺失等 skipif，非掩盖 §3.4）。
- **heavy_llm**：无端到端用例，按 §3.11 不默认跑；特性交付节点建议补 heavy_llm 守护 escalation/entry-commit 真实链路（§3.9）。
