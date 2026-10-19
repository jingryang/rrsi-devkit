# step-61 — 概设 review 闭环 — 实施方案（第四层）

> L3 见 `61-design-review-closure-analysis.md`；L1 见 `06-problems.md` P84。已实施（commit 3c80081）。

## 1. _DesignGate 公共基类（design_substages.py）

- 新增中间基类 `_DesignGate(_DesignSubstage)`，聚合 gate 通用方法：
  - `loopback_feedback(state)` → 本轮 blocking_issues 的 feedback dict。
  - `is_satisfied(state)` → 本轮无 blocking_issues。
  - `error_signature(state)` → `issue_fingerprint`（stagnation 检测）。
  - `resolve_condition(state)` → 内联共同路由（`_resolve_with_redirect` + `_route_from_issues`），mapping 由子类 `issue_target_mapping` 属性承载。
  - `_set_known_issues(state, new_state)` → 跨 gate 分区累积（见 §4）。
  - `fail_strategy = "continue"`；`issue_target_mapping: dict = {}`。
- `GeneralDesignReviewStage` / `AnchorConsistencyStage` / `ValidateStage` 改继承 `_DesignGate`（原 `_DesignSubstage`），删各自重复的 gate 方法 + `fail_strategy` 覆写，保留各自的 `issue_target_mapping` + `blocking_issues`。
- 非 gate substage 仍继承 `_DesignSubstage`（不携带 gate 语义）。
- 删 over-extraction 的 `_gate_condition` wrapper（一对一调用，无价值）。

## 2. review→generator 闭环（design_tree.py + design_substages.py）

- `_GENERAL_DESIGN_TRANSITION_TABLE["general-design-review"]` 加 `redo_generator: ("general-design-generator", "corrective")`。
- `GeneralDesignReviewStage.issue_target_mapping` = `{"generator": "redo_generator", "requirement": "design_input_invalid", "human": "human"}`。
- `prompt_intro` 的 target 列表 → "generator/requirement/human"。

## 3. review→requirement bubble 带 feedback（graph_executor.py + issue_render.py + requirement.py）

- graph_executor 提模块函数 `_capture_loopback_feedback(child, state)`：AtomicStage 且 stage 有 `loopback_feedback` → 注入 `state._loopback_feedback`。
- corrective-jump 路径 + escalation-bubble 路径都调它（原 corrective-only 内联替换为函数调用）。
- issue_render 提 `render_loopback_feedback_section(state) -> str | None`（渲染「## 上次反馈」）。
- `_DesignSubstage._feedback_section` + `RequirementStage._build_analysis_prompt` 都调该公共函数。

## 4. known_issues 跨 gate 累积（design_substages.py）

- `_DesignGate._set_known_issues(state, new_state)`：
  - `carried = [i for i in state.design_known_issues if i.get("source") != self.name]`
  - `fresh = [{**i, "source": self.name} for i in self.blocking_issues(new_state)]`
  - 返回 `carried + fresh`。
- `GeneralDesignReviewStage.transition`：`_parse_single` ok 时 `design_known_issues=self._set_known_issues(state, new_state)`。
- `ValidateStage.transition`：原 `design_known_issues=self.blocking_issues(new_state)` 改 `self._set_known_issues(state, new_state)`（clean pass 只清自己切片，不清别 gate 债）。
- issue 标 `source` 字段（stage 层补，不动 skill schema）。

## 5. SKILL target 指导 + 产物范式（ascendc-op-general-design-review）

- SKILL.md：
  - description / 职责 §5 / 输出契约 / 约束段：`checkpoints/general-design.json` → `general_design_reviewed.json`。
  - 「阻断条件」段（B1/B2/B3 markdown halt）→ 「无法就地修的问题：写 blocking_issues 走工程路由」+ target 根因归属判据表 + issue 字段（code/target/detail/verdict/acceptance/remediation）。
  - 步骤 1（B1）/ CR1 / CR2 / 步骤 3（B2）散点：「阻断」→「写 blocking_issues 带 target」。
  - 步骤 5 摘要：「阻断问题」→「未消解（写 blocking_issues 走工程路由）」。
  - 步骤 7：写 `general_design_reviewed.json`（status + blocking_issues + patched_nodes + review_summary），删旧 checkpoint 结构（step/review_result/key_parameters/self_check_summary）。
- schema/general_design_reviewed.json：description 教 target 根因归属 + acceptance；example 加一条 target=requirement 的完整 issue（含 severity/verdict/acceptance/remediation）+ review_summary。不加 `issue_required_keys`（review strict=False 不消费）。

## 6. 验证（TDD）

- 1170 orchestration UT + 全量 2318 UT passed / 7 skip，零回归。
- 新增守护用例：
  - review generator target → redo_generator corrective 闭环（max_corrective 耗尽才逃生）。
  - escalate-bubble 带 feedback（review design_input_invalid → state._loopback_feedback 注入）。
  - requirement prompt 渲染「## 上次反馈」+ issue code。
  - known_issues 跨 gate 累积（review populate + source 标记 / validate 不覆盖 review 遗留 / clean pass 只清自己切片）。
- heavy_llm e2e 未跑（§3.11：复现 review 真 blocking_issues 场景验证三向路由真实生效，待用户决策）。
