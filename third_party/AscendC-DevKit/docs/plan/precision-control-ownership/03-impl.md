# step-119 precision-control-ownership — L4 实施方案

> 层级：**L4 / 实施方案**。记录「改哪个函数、什么顺序、怎么验证」。
> 上游：`docs/plan/precision-control-ownership/01-problems.md`（L1）+ `02-analysis.md`（L3 v8，已评审方向）。
> 状态：**实施中（2026-09-04）。B/A/C1/D 代码完成，E 测试迁移完成，F 全量验证进行中。**
> 原则：**A3 正确性优先，不动 A5 专有内容**（已证 A5 不碰 A3 的 `_converge_to_best_commit`/
> `_extract_debug_checkpoint`，彻底删字段不波及 A5）。

## 总体顺序（依赖链）

B（已完成，470 UT 绿）→ A（本文件核心）→ C1 → D1/D2 → E（测试迁移+新增）→ F（全量验证）。

## B. deploy source_identity provenance（已完成）

- `domain/verification.py`: `DeployResult` 加 `source_identity: str = ""`。
- `orchestration/stages/deploy.py`: 加 `_source_identity(source_dir)`（纯 git 探测 `{HEAD12}-{clean|dirty-n}`）；
  `_ResolvedInputs` 加字段；`_resolve` 里对 `source_dir` 计算；成功 DeployResult 构造点（build_install 尾部 /
  _run_smoke_phase 成功+失败）注入。`asdict` 自动持久化进 last_deploy.json。
- **验证**：470 UT（deploy+domain）绿。

## A. 删 best_* + 双路径交付（核心）

### A-1 测量记录增强：history 的 run_tests content 加 source_identity

**现状**：history run_tests 条目 content 有 `{failure_type, test_result, failed_count, total_count, max_err}`，
但**无 source_identity**。A 需 history 带 identity 才能现算「最近全过测量 / argmax 的 commit」。

**改 `RunTestsSubstage.transition`**（substages.py ~:2300，构造 run_result / _append_history 处）：
- 读 `state.deploy_result.source_identity`（B 已提供），写入 history content 的 `source_identity`。
- deploy_result 缺失/空 → source_identity=""（诚实）。

### A-2 删除 best_* 字段初始化

**现状**：control schema（~:349 `_CONTROL_KEYS` / ~:383 init dict）声明 best_commit/best_passed_count/
best_failed_count/best_crashed_count/best_real_max_err/best_total_count。

**改**：
- init dict 删除这 6 个字段。
- `_CONTROL_KEYS`（校验）同步删。

### A-3 `_update_best_metrics` / `_snapshot_best_commit` 删除，改派生

**现状**：`:1001 _update_best_metrics`（严格大于才返回 True）+ `:1050 _snapshot_best_commit`（rev-parse HEAD 写
cp.best_commit）。transition 在 `_update_best_metrics` 返回 True 时调 `_snapshot_best_commit`（:2322-2323）。

**改**：
- 删这两个函数。
- transition 里改为：无条件把本次测量（含 source_identity）追加进 history（A-1），不再「严格大于才记 best」。
- 「最优」不再存字段，由下游从 history 现算（见 A-4/A-5）。

### A-4 新增纯函数：从 history 现算最优

新增（A3 内部）：
```
def _best_identity_from_history(history) -> str:
    """从 history 的 run_tests 测量记录派生最优被测 identity。
    双路径：
      - 若存在全过测量（content.failed_count==0 且 total_count>0）→ 取最近一条的 source_identity
        （全过退出路径，无 argmax/tie-break）。
      - 否则 → 取 content 里 passed(=total-failed) 最大者；平局保留较早。
    history 无 run_tests 测量 / source_identity 空 → 返回 ""（调用方 fallback）。
    """
```

### A-5 改 `_converge_to_best_commit`（纯 A3）从测量史现算

**现状**（:1238）：`best = dc.get("best_commit") or _current_head(...)`。
**改**：
- `best` 改为从 `history` 现算（A-4），history 无结果则 fallback `_current_head`（保留现有语义）。
- 其余（rollback→deploy→smoke→quality 分类）不变。
- 签名不变（dc 仍传，但 best_commit 不再从 dc 读——从 dc/history 读 history）。

**注意**：`_classify_best_quality(dc)`（:1212）读 dc 的 best_passed/failed——改为从 history 现算 passed/total。

### A-6 改 teardown（:1500）从测量史现算

**现状**：`best = cp.get("best_commit")`。
**改**：从 history 现算（A-4），无则保留「无 anchor → 跳过」保守语义。

### A-7 改 `_extract_debug_checkpoint`（:896）不读 best_* 字段

**现状**：把 cp.best_commit/best_real_max_err/best_failed_count/best_crashed_count 透出到 dc。
**改**：dc 里这几个键改为从 history 现算（保持下游 report/_sync_debug_result 读 dc 不变）。

### A-8 改 `_sync_debug_result`（:1340）产物仍带 best_*（从 history 现算）

**现状**：`PrecisionDebugResult`（debug_result）带 best_commit/best_passed_count/best_quality/best_real_max_err
——**dispatcher 读 debug_result.best_passed_count 展示 quality**（:1137）。这是产物不是 control 字段。
**改**：debug_result 的值从 history 现算填充，字段保留（dispatcher 零改动）。`failing_cases` 照旧。

### A-9 改 report 渲染（:743 `_write_precision_report_impl` / :643 `_report_total` / :693 `_report_fix_rows`）

**现状**：读 cp.best_commit / best_passed_count / best_total_count。
**改**：从 history 现算填充（含「最优 commit」「通过/失败」「最大误差」等展示）。渲染 (identity, passed) 对。

### A-10 dispatcher 不变

`dispatcher.py:1137` 读 debug_result.best_passed_count（A-8 保留产物字段）——零改动。

## C1. converge 交接断言（依赖 A+B）

`_converge_to_best_commit` 末尾：断言 `deploy_result.source_identity == 判定最优 identity`；不等 → WARN +
debug_result 标记「eval 将用非最优 source 旧包」。判定最优 identity 从 A-4 现算结果取。

## D1/D2. 加固

- **D1**：diagnose 的 phase schema `precision_diagnose.json` 的 fix `_summary.git_commit` 设 required；transition
  加载校验，缺 → product_feedback 打回（weak-model B）。
- **D2**：`ascendc-precision-diagnose` SKILL.md 写契约删 best_* 提及；prompt（substages:2522）同步。

## E. 测试迁移 + 新增

- 迁移 11 个 A3 UT：`test_precision_debug_stage.py` / `test_step96_converge_quality.py` / `test_graph_executor.py` /
  `test_step96_terminal_quality.py` / `test_build_failed_case_queue.py` 等——从「断言 cp/dc.best_* 字段」迁为
  「断言 history 测量史 + 现算派生」。**A5 相关测试不动**。
- 新增 UT：A-4 双路径（全过取最近全过/非全过 argmax 平局保留较早）、A-5 converge 从 history 现算、A-8 debug_result
  从 history 现算、source_identity 进 history、B 默认值兼容、C1 交接断言、D1 schema 打回。

## F. 全量验证

- 全量 UT + 非 heavy ST（§3.2/§3.6）。
- 端到端验收（下批真实 run）：eval 报告可见被测 binary source_identity；人为注入写 best_passed_count → 无字段。
- 实施后回填 README/L2 状态。

## 验证判据

- 全量 UT 绿（A3 迁移后 + A5 原测试不动）。
- 本次事故场景 fixture：iter-0 1/20 → diagnose 修 b760254 → 全量 20/20 → converge 交付 identity==b760254。
