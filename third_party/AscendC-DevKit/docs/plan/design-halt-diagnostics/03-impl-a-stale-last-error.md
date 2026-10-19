# 详设阶段假性 halt — 实施（L4）：P1 stale last_error 共享清理入口

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md` 决策 1，事实见 `01-problems.md` P1。

## 改动 1 — `_DesignSubstage` 新增成功路径共享方法

在 `orchestration/stages/design_substages.py` 的 `_DesignSubstage` 基类上新增一个方法（与既有
`_missing_artifact_error`/`_read_disk_artifacts` 同级的基类工具方法），职责单一：产出一个
`state.with_updates(...)`，无条件带上 `last_error=None`，其余字段由调用方透传。命名与
`_parse_single` 里 `# P5: 清除 sticky error` 的注释呼应，说明两者是同一条约定的两个入口。

## 改动 2 — 三处自定义 `transition` 的成功路径改用该方法

- `IntegrateStage.transition`：无 schema 错误的成功分支，`updates` 字典的构造改经这个共享方法生成
  （即最终仍是同一份 `design_spec`/`tiling_strategy`/`data_flow`/`decision_logs`/`user_feedback`/
  `pending_advisories`，但显式带上 `last_error=None`）。**不改** schema 错误分支——该分支本就要保留
  `last_error=schema_violation`，不能被这次改动清空。
- `DetailedDesignIntakeStage.transition`：成功分支的 `state.with_updates(design_spec=..., ...)`
  改经共享方法。
- `ValidateStage.transition`：成功分支的 `state.with_updates(validation_report=..., ...)` 改经
  共享方法。

## 验证

- TDD：先写失败用例再改代码。新增/改造针对三个 stage 的单测，各构造「第 1 轮产出
  `last_error=missing_artifact`（`stage_name` 命中自身）→ 第 2 轮产物齐全成功」的场景，断言：
  - `transition` 返回的 `state.last_error` 为 `None`；
  - 若同一场景喂给 `runner.run_stage`（或等价的 stage-status 派生逻辑），配合
    `fail_strategy="halt"`，`stage_status` 不应为 `"failed"`，管线不应被判定终止。
- 回归：`IntegrateStage`/`DetailedDesignIntakeStage`/`ValidateStage` 既有成功路径/schema 错误路径
  的既有用例须保持全绿，确认改动没有影响错误路径原有的 `last_error=schema_violation` 行为。
- 全量 UT + 非 heavy ST（CLAUDE.md §3.6）。
