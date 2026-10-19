# step-79 L4 — design human 决策通道：用 in-flow `resolve_ambiguity` 替代 `__halt__`（实施方案 / as-built）

> 状态：**L4 已实施（2026-07-28）**——全量 UT **3119 passed/7 skip/1 deselected** 零回归；heavy_llm review GD-H* e2e **PASSED**（reviewer 真调 `resolve_ambiguity` + 前逃不 halt）；Q1 结构校验 ST 留 PR 前人工审计（断言不可行）。
> L3：`79-design-human-channel-analysis.md`（冻结，方案 X）。L1：`06-problems.md` P118。Plan：`/root/.claude/plans/dapper-herding-metcalfe.md`。

## 改动总览（as-built）

| 块 | 改动 | 文件 | 代码 |
|---|---|---|---|
| **R2** | 删 review human→halt 链（**保留 human target 语义**作前逃标记，对齐 validate step-60 修C） | `design_tree.py:44`（删 transition human）/ `workflow.py:264`（删 `design_needs_human→halt`）+ 注释 | 有 |
| **R1** | review SKILL：GD-H* 改 in-flow `resolve_ambiguity` 提问（options[0]=前逃项）；加「GD-H* 处理」小节 + `needs_human_decision` 字段；`prompt_intro` 同步 | `ascendc-op-general-design-review/SKILL.md`（L77/112/119/219 + 新节）/ `design_substages.py` prompt_intro | 无（纯引导） |
| **R3** | 【实现优化】原 plan「handler 加 decided_by」→ 方式 2：复用 `resolve_ambiguity` 首项契约（options[0]=pipeline-advancing 前逃项），**零 handler 改动** | （并入 R1） | 无 |
| **V1** | validate SKILL + gate_scope：GV7-B/GV9-b→`target=tiling`（redo_tiling）；GV7-A 保留 `target=human` 改措辞（前逃+反馈强化 requirement 自检） | `ascendc-op-design-validate/SKILL.md`（:78/86/113/176/231）+ `schema/gate_scope.json` routes | 无 |
| **A1** | 删 anchor human 死配置（owner_ambiguous 并入 integrate route description）+ `issue_target_mapping` human 死键 | `anchor-consistency/schema/gate_scope.json` + `design_substages.py:1625` | 有（删死键） |
| **Q1** | requirement `math-equiv-golden` 加结构校验子步（4b：修正项不得含位置下标）+ 常错点追加 + capabilities 自述补 | `ascendc-op-req-analysis/SKILL.md`（:182-186）+ `capabilities.json` | 无 |

## 关键设计决策（实施中澄清，偏离 plan 处）

1. **R3 方式 2（零 handler 改动）**：plan 原定 handler 加 `decided_by` 字段；实施时发现复用 `resolve_ambiguity`「options[0] = pipeline-advancing」契约（requirement-analyst 已用，`requirement-analyst.md:86-94`）更简——reviewer 把 options[0] 设为「前逃项」，default 自动选它→前逃，真人选其他→corrective（文本比较 `answer==options[0]`）。无「模型能否读顶层字段」技术风险（§1.2 最小改动 + §2.5 单一通路）。

2. **R2 保留 human target 语义（纠正过度删除）**：初版误删了 review `issue_target_mapping["human"]` + gate_scope human route，发现会让 target=human issue 被 INV-A drop（**静默前逃**，违 §4.4 受控非静默）。纠正为**对齐 validate（step-60 修C）**：保留 human target（过 INV-A → 进 `design_known_issues` **可观测前逃**），只删 halt 出口（transition table human 条目 + pipeline `design_needs_human`）。reviewer default 时写 `target=human`+`needs_human_decision:true`（前逃标记），真人决策写 `target=generator/requirement`（corrective）。

## 验证

- **全量 UT**：`pytest tests/ut/ --quick` → **3119 passed, 7 skipped, 1 deselected**（136.91s）零回归。
- 新增/更新守护用例：
  - `test_review_human_issue_carried_not_halt`（target=human 过 INV-A → 进 known_issues 前逃，不 halt）
  - `test_review_targets`（含 human→human condition）
  - `test_general_design_table_has_review_escalations`（transition 无 human）
  - `test_pipeline_table_has_group_routes`（`design_needs_human` 已删）
  - `test_advisory_routing`（anchor owner_ambiguous 删 human route 后仍走 integrate）+ gate_scope/validate loader 回归。
- **heavy_llm（§3.11）**：
  - ✅ **review GD-H* e2e PASSED（158.86s）**——`tests/st/test_review_target_routing_selfclosure.py::TestReviewGDHOutOfScopeRoutesToHuman`：seed「超出单算子范畴」（完整 Transformer encoder layer）→ reviewer 真判 GD-H*（`target=human`）+ **真调 `mcp__engine__resolve_ambiguity`**（日志 turn 15）→ default 返回 options[0]（前逃项）→ 写 `target=human` 前逃（不 halt）。R1/R2/R3 真实链路守护到位（非 mock）。
  - ⏸️ **requirement 结构校验 ST：评估断言不可行**——`math_formula` 是 string 无 AST（`op_spec_schema.md:100`），「修正项不含位置下标」无法可靠自动判定 + 触发依赖 agent 先产错再 catch（非确定）。Q1 是纯 SKILL 引导（4b），**留 PR 前人工审计**（跑含修正项反向 golden，人看 agent 是否 re-derive）；日常靠 SKILL 引导文本存在 + 真实 run 观察。

## 不改的（避免误伤）

- `graph_executor.py` `__halt__` 语义（`is_terminal=True`；改的是 design 路由不再导向它）
- `_DesignGate` 基类（`resolve_condition`/`loopback_feedback`/`_set_known_issues` 全复用，零改动）
- validate `issue_target_mapping` / transition table（已支持 tiling→redo_tiling，零改动）
- step-60 validate human halt 删除（已做）
