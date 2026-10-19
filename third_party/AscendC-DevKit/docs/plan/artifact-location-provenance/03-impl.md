# 产物落点误判的取证 + 用户决策门 — 实施方案（L4）

> 具体改哪个函数、什么顺序、怎么验证。方案见 `02-analysis.md`（决策 1-4 + 决策 3 修订）。

## 改动清单

1. `orchestration/kernel/state.py`：新增 `RelocationEvidence`（frozen dataclass：
   `stage_name`/`filename`/`wd`/`actual_path`）+ `State.pending_relocation: RelocationEvidence | None = None`。

2. `orchestration/stages/design_substages.py`：
   - 模块级新增 `_RELOCATE_KEEP`/`_RELOCATE_MOVE`（门禁选项文案常量，`actions()` 与
     `_read_disk_artifacts` 共享同一字面量）+ `_harvest_relocation_evidence(transcript, filename, wd)`
     （扫描 transcript jsonl 的 Write/Edit 调用，容错匹配文件名、落在 wd 外才算候选，取最后一条，
     best-effort 不抛异常）。
   - `_missing_artifact_error` 新增 `transcript=None` 形参：有证据 → 精确文案 + 写
     `pending_relocation`；无证据 → 原通用文案 + 显式清 `pending_relocation=None`（防止上一次残留误触发）。
   - `_read_disk_artifacts`：
     - 顶部新增决策回退分支——`wd is None and "decision" in result and state.pending_relocation`
       时消费 `AskUserQuestion` 的回答：`_RELOCATE_MOVE` 物理搬文件到 wd 后落入正常定位循环；
       `_RELOCATE_MOVE` 之外（即 `_RELOCATE_KEEP`）直接返回 `(None, state.with_updates(pending_relocation=None))`，
       `last_error`/`user_feedback` 保持不变，交下一轮沿用已记录的纠正提示重新 spawn。
     - 从 `result.get("agent_result")` 取 `transcript`，透传给全部 `_missing_artifact_error` 调用点。
   - `_DesignSubstage.actions()` 顶部新增门禁：`state.pending_relocation` 命中即**无条件**返回单个
     `AskUserQuestion(default_index=0)`（`on_decision` 的 default/abort 分支完全交给
     `runner._execute_ask_user_question` 处理，stage 层不重复判断——决策 3 修订记录的架构落地修正）。
   - 4 处成功路径补 `pending_relocation=None`（跨迭代残留清理）：`_parse_single`、`_success_updates`
     （覆盖其全部调用点）、`AnchorPerTemplateStage._parse_and_wrap`、`_TilingSegmentStage.transition`。

## 验证

- TDD：`tests/ut/orchestration/test_design_substages.py` 先写（`_harvest_relocation_evidence` 未实现
  时跑出 `ImportError`，确认红态），后实现至绿。
- `pytest tests/ut/orchestration/test_design_substages.py -q` → 148 passed。
- 全量 `pytest -m "not heavy_llm"` 待跑，确认无回归（收口前最后一步）。
