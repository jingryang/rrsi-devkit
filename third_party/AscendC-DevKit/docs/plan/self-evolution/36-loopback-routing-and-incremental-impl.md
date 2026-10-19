# P59/P60/P61 — 设计阶段 loopback 收敛慢：target 正交化 + 前向建议通道 + entry-kind + 定向重跑 — 实施方案（第四层）

> 范围：**P0 + P1-a + P1-b**（修 P59/P60/P61 三个根因）。**P1-c（delta 前传）降级为数据驱动 follow-up，不在本步落地**（L3 D3）；**P2（shift-left）排期最后**（L3 D5）。
> 层级：**第四层 / 实施方案**。改哪个符号、什么顺序、怎么验证（TDD）。
> 依据：L3 `35-loopback-routing-and-incremental-analysis.md`（冻结，D1-D9）。
> 约定：按符号定位（不写 file:line）；外部依赖只读；TDD 先红后绿。

---

## 0. 基线（已存在，复用，不重建）

- **route_type**：字符串字面量（无枚举类），散见于 transition_table 的 `(target, route_type)` 元组与 `graph_executor` 的处理分支。现有合法值 `corrective` / `escalation` / `validation`。本步新增 `advisory`（D1）。
- **transition_table**（`design_tree.py`）：`(stage, condition) → (target, route_type)`。anchor-consistency 现有 `"infeasible": ("tiling", "corrective")`。
- **`_invalidate_sequential_range` + `_rerun_targets_of`**（`graph_executor.py`）：loopback 清空原语，已接 group 的 `rerun_selector` 做 template-precise 回滚。
- **`_tiling_rerun_selector`**（`design_tree.py`）：读 `anchor_report.blocking_issues` 里 `target=tiling` 且带 `target_template` 的 issue → 返回模板名集合；无 `target_template` → 返回 None（全模板重跑 fallback）。**template-precise 机制已存在**，P1-b 复用、不另造。
- **`AnchorConsistencyStage.resolve_condition` + `_route_from_issues` + `_resolve_with_redirect`**（`design_substages.py`）：gate 路由，现 `mapping = {"tiling": "infeasible", "human": "human"}`，只按 `target` 映射、不看 `verdict`。
- **`ascendc-op-design-feedback-selfcheck` skill**（`stage-design` 插件）：读上游反馈报告逐条 `acceptance` 全量回验，触发判据 = 工作目录有反馈报告。主生成 skill 末尾用 Skill 工具调用。**P0/P1-a 不动它**。
- **`_INPUT_FILENAMES`**（`design_substages.py`）：产物字段 → 文件名映射（`tiling_results`→`tiling_results.json` 等）。entry-kind 判据「本产物是否存在」据此定位文件。
- **`output_contract.provides` + `state.has_all`**（`base.py` / `runner.py`）：产物存在性检查既有原语。
- **issue schema**（`anchor_report.json` / `blocking_status.json`）：issue 已有 `target` / `target_template` / `verdict` / `remediation` / `acceptance` / `iteration`；自定义描述式 schema（`description` + `example` + `required_keys`），加可选字段只需补描述 + example。

---

## 1. P0 — target 判定正交化 + 前向建议通道（route_type 加 `advisory`）

目标（双核）：
1. **正交化（D8，P0 真正核心）**：anchor-consistency 的 target 判定从「跨模板（blast-radius）→ 默认 `target=tiling`」改为按 **owner 能力矩阵**判（上游可修→tiling；整合层可修→integrate；需人→human；owner 不明→灰区）。标准写进 SKILL.md，归类动作仍由 LLM（语义，§1.5）但标准确定化。**verdict / blast-radius 是 skill 归类的推理输入，不进 router**——router 只机械映射 `target → condition`。
2. **前向通道（D1）**：owner 在下游 integrate 的非阻断 issue，经新增 `advisory` route_type 前向投递、integrate 就地吸收，不 backward 回 per-template 盲 tiling（修 P59）。

### 1.0 判定模型（P0 的判定地基，先于通道）

- **owner 能力矩阵**（写进 `ascendc-op-design-anchor-consistency/SKILL.md`，替代现有「跨模板→`target=tiling`」）：
  - AC3 子类归位：TilingKey/workspace/dtype 冲突 → 上游 tiling 可修 → `target=tiling`（+ `target_template`，localized）；字段命名/接口不一致 → 整合层统一 → `target=integrate`；需人裁定 → `target=human`。
  - 灰区（owner 归属不明）：`target=integrate`（design 链路默认 owner）+ 标 `owner_ambiguous: true`（D9）。
- **router 只机械映射**：`resolve_condition` 的 mapping 加 `"integrate": "advisory_integrate"`；`target=tiling` → 既有 `"infeasible"`；`target=human` → `"human"`。**mapping 不看 verdict/blast-radius**（那是 Route B 的错路——把语义判定漏进 router，正交化就是要堵掉它）。

### 1.1 改动（按顺序）

1. **anchor-consistency SKILL.md 正交化 target 判定标准**（`ascendc-op-design-anchor-consistency/SKILL.md`）：删「跨模板问题→`target=tiling`」默认，换成 §1.0 的 owner 能力矩阵。**AC code 结构不重排**（按问题类型分给 selfcheck/人看合理），只改 target 标注规则。domain 判定在 skill（§1.5）。
2. **transition_table 加 advisory 边**（`design_tree.py`）：anchor-consistency 的 transition_table 新增 `"advisory_integrate": ("integrate", "advisory")`。保留 `"infeasible": ("tiling", "corrective")`（真不可行仍回 tiling）。
3. **gate mapping 加 integrate 映射**（`AnchorConsistencyStage.resolve_condition` / `_route_from_issues`）：`mapping` 加 `"integrate": "advisory_integrate"`。**机械映射、不看 verdict**——skill 已按 owner 能力矩阵把该前向的 issue 标了 `target=integrate`，gate 只认 target。
4. **`State` 加前向队列字段**（`state.py`）：`pending_advisories: list`（默认空，frozen dataclass，随 `with_updates` 不可变更新）。元素结构 = issue 摘要（`code`/`target`/`detail`/`remediation`/`acceptance`/`owner_ambiguous`）。
5. **`graph_executor` 加 advisory 分支**：在 route 解析（`target_name, route_type = route`）之后、`__halt__` / scope 计数逻辑之前，插 `if route_type == "advisory":` 分支——**纯信息前流，不动控制流**：把 issue append 进 `state.pending_advisories`（`with_updates` 不可变），`i += 1; continue`（顺流水线前进，不回跳、不计 corrective/escalation 配额、不调 `_invalidate_sequential_range`）。`target_name` 在 advisory 里仅作归属 owner 标记。
6. **owner 吸收**（`IntegrateStage`，design 侧 integrate）：`_build_prompt` 读 `state.pending_advisories` 中 `target=integrate` 的条目，渲染成「待就地消解的 advisory 清单」段（统一两模板 R5 字段命名等）；agent 就地修产物。**不回跳、不产新 issue 路由**（advisory 单向投递，D1）。
7. **灰区用户裁定**（D9）：advisory 带 `owner_ambiguous` → 检测到时触发 `resolve_ambiguity` / human review 通道（复用既有 human 通道，不另造），用户裁定优先于 default integrate；**不静默吸收**。

### 1.2 TDD（先红后绿）

- **`test_anchor_consistency_advisory_condition`**（UT，gate 层）：mock blocking_issues 含 `target=integrate` 的 issue → `resolve_condition` 返回 `"advisory_integrate"`（机械映射）；含 `target=tiling` 真 infeasible → 仍返回 `"infeasible"`。**不测 verdict 分流**（router 不看 verdict）。
- **`test_advisory_routing`**（UT，graph_executor 层）：route_type=advisory → `corrective` 计数不变、`node_status` 不被 invalidate、`pending_advisories` 含该 issue、`i` 前进。
- **`test_integrate_consumes_advisory`**（UT，owner 层）：`pending_advisories` 非空 → integrate prompt 含 advisory 清单段；空 → 不含。
- **`test_advisory_owner_ambiguous_escalates`**（UT，灰区 D9）：advisory 带 `owner_ambiguous` → 触发 resolve_ambiguity / human 通道（不静默吸收）。
- **回归**：既有 `TestAnchorLoopback`（真 infeasible 仍回 tiling）+ `test_graph_executor` 全量不破。

---

## 2. P1-a — entry-kind 单点判据 + prompt 触发量改对

目标：把「已有产物→增量修改」从错挂在 `iteration>1` 换成显式 `entry_kind`，使 loopback 重入（iteration 被重置为 1）也走增量口径（修 P61）。

### 2.1 改动（按顺序）

1. **新增单点函数 `entry_kind(state, stage) → "generate" | "modify"`**（落 `base.py` 或 design 侧共享处）：判据 = 本 stage `output_contract.provides` 对应的产物文件（经 `_INPUT_FILENAMES` 映射）在工作目录已存在。tiling fork-join segment 用本模板的产物文件判。**单点**：所有「生成 vs 修改」口径只调它，不散落。
2. **替换三处 `if iteration > 1`**（`design_substages.py`，三处「重试上下文：基于已有产物增量修复」段）：改为 `if entry_kind(state, self) == "modify":`。段落文案从「第 N 次尝试」改为「工作目录已有上一轮产物，基于已有产物 + feedback 增量修改，勿从零扫描」。
3. **不改** `requirement.py`（`iteration > 1 and state.unclear_items`）与 `codegen.py`（`iteration > 1 and state.last_error`）——这两处是 **stage 内真自迭代**语义（producer 自判不合格再迭代），非 loopback 重入，`iteration>1` 是其正确触发量。

### 2.2 TDD（先红后绿）

- **`test_entry_kind`**（UT）：首次（工作目录无本产物）→ `"generate"`；有产物 → `"modify"`。
- **`test_tiling_segment_modify_prompt_on_loopback`**（UT）：tiling segment loopback 重入（`start_iteration=1` 但工作目录有上一轮产物）→ `_build_prompt` 含增量修改段（现状因 `iteration=1` 不含 → 红）；首次生成 → 不含。
- **回归**：自迭代第 2+ 轮（iteration=2 且有上轮产物）→ 仍含增量段（entry-kind=modify，行为不退化）。

---

## 3. P1-b — 定向重跑范围（gate 带 blast-radius，复用既有 rerun_selector）

目标：单模板 localized issue 只重跑涉事模板（修 P60 的单模板场景）。机制已有（`_tiling_rerun_selector` 读 `target_template`），本步只补 gate 产 issue 时带好定位字段 + schema 守护。

### 3.1 改动（按顺序）

1. **issue schema 补 `blast-radius`**（`anchor_report.json` / `blocking_status.json`）：`description` 增字段说明 + `example` 补 `blast-radius: localized|structural`。`localized` = 单模板可定位（必带 `target_template`）；`structural` = 跨模板/结构性（无 single template，正解走 P0 前向，罕走 tiling 重跑）。可选字段，缺失编排兜底 `structural`。
2. **anchor-consistency skill 指导**（`ascendc-op-design-anchor-consistency/SKILL.md`）：产 issue 时按问题边界带 `blast-radius` + `target_template`（localized 时）。domain 判定在 skill，§1.5（算子知识/判定不进 Python）。
3. **（可选）加载期校验**（§1.3）：parse issue 时，`blast-radius=localized` 但缺 `target_template` → 告警/拒绝（localized 必须可定位）。
4. **不改** `_tiling_rerun_selector` / `_invalidate_sequential_range`——既有 template-precise 回滚已读 `target_template`，localized issue 带上即生效。

### 3.2 TDD（先红后绿）

- **`test_localized_issue_template_precise_rerun`**（UT）：localized issue 带 `target_template=T1` → loopback 只清 T1 子树（既有 `_tiling_rerun_selector` 行为，加 blast-radius 字段守护）。
- **`test_structural_issue_routes_forward`**（UT）：structural 跨模板 issue → 走 P0 advisory 前 integrate，不回 tiling（与 §1 闭环）。
- **加载期校验**：`blast-radius=localized` 缺 `target_template` → 拒绝（§1.3）。

---

## 4. 不在本步落地

- **P1-c（delta 前传）**：数据驱动 follow-up（L3 D3）。P0+P1-a+P1-b 落地后跑 e2e 测收敛曲线定去留；若做，复用 P0 的 `advisory` 通道（payload 扩 `issue | delta`，L3 D6），不另造通路。
- **P2（shift-left producer 自检）**：按回跳频率实测后排期（L3 D5）。

---

## 5. 验证矩阵

- **UT**：§1.2 / §2.2 / §3.2 全部先红后绿；既有 `TestAnchorLoopback` / `test_graph_executor` / design routing 全量回归（§3.6 默认范围）。
- **非 heavy ST**：design 链路路由相关 ST（anchor-consistency → tiling/integrate 分流）。
- **heavy_llm e2e（§3.11，PR 前节点，用户决策跑）**：真实 self_evolve_op design 链路，验证「跨模板 verified issue 前向 integrate 就地消解、不再全量重跑 tiling」+「loopback 重入走增量口径」的端到端收敛曲线（为 P1-c 去留提供数据）。

## 6. 实施顺序

P0（§1）→ P1-a（§2）→ P1-b（§3），各自 TDD 闭环后合入下一项。P0 独立、ROI 最高先做；P1-a 是 P1-b 的 modify 口径地基（P1-b 的 localized 重跑产物由 modify 口径增量修复）。
