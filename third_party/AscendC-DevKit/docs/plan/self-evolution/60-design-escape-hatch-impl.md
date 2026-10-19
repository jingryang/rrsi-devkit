# 60 — 设计阶段逃生路径 + validate halt 三层根因修复（实施方案）（L4）

> L4 实施方案：改哪个函数/类、什么顺序、怎么验证。关联 L1：`06-problems.md` P81/P82/P83；L3：`60-design-escape-hatch-analysis.md`（决策冻结）。
> TDD：先写测试再改实现（§3.1）。依赖顺序 **A → C → B**（A 是 chip 真值、C 是逃生路径、B 是查证纪律）。
> 外部 run `20260717-070202-53f685`（同事机子）只读分析，不在本仓复现执行。

## 0. 改动总览（符号级）

| # | 模块 / 符号 | 改动 | 归属 |
|---|---|---|---|
| A1 | `application/dispatcher.py`（chip 解析后） | 入口兜底：CLI 没传 `--design-target-chip` 时 `design_chip = runtime canonical`，source=`runtime_default` | 修A |
| A2 | `stages/requirement.py` `transition` + 新增 `_read_design_chip_from_doc` | design_chip 改读需求文档**顶层 YAML `design_target_chip` 字段**（canonical 校验），不再从 agent 产的 constraint 取 | 修A |
| A3 | `domain/requirement.py` `Constraint` | 删死字段 `design_target_chip`（修A 后无消费者，§1.4 不留旧字段） | 修A |
| A4 | `skills/ascendc-op-req-analysis/`（SKILL.md + schema + references） | agent 不自行决议 chip、不写入 constraints；schema example 去 A5 真值污染 | 修A |
| C1 | `kernel/state.py` `State` | 新增 `design_known_issues: list` 字段 + `from_snapshot` new_field 登记 | 修C |
| C2 | `orchestration/design_tree.py` `_DETAILED_DESIGN_TRANSITION_TABLE["validate"]` | 删 `redo_doc`/`human`/`redo_general` 三个 halt/escalate 出口，**只留 `redo_tiling`**（corrective，跑配额） | 修C |
| C3 | `orchestration/workflow.py` `_DESIGN_GROUP_PIPELINE_ROUTES` | 删 `detailed-design` 的两条 pipeline routes（escape-forward 不冒泡，死配置 §1.4/§2.5）；`general-design` 保留 | 修C |
| C4 | `stages/design_substages.py` `ValidateStage.transition` | `_merge_issue_history` 后 populate `design_known_issues=self.blocking_issues(new_state)`（本轮未消解 issue） | 修C |
| C5 | `stages/codegen.py` `_materialize_inputs`/`_build_codegen_prompt` | 物化 `known_issues.json` + prompt 加「设计已知问题」段。**不加** `validation_report` 检查——产物完整性由既有 `validate_inputs`（design_spec.inputs/outputs）+ runner `has_all` 保证（见 §2 落点②撤回） | 修C |
| B1 | `skills/ascendc-op-design-shared/references/checkpoint_convention.md` | `verification` 判据明确（`derived` 含文档推导、`UNVERIFIED` 是 last resort 必填 why）+ `evidence` 结构化（source_pointer/attempt_log/why_unverifiable）+ `claim_type` 子类归属 + selfcheck 边界声明 | 修B |
| B2 | 3 个 tiling skill SKILL.md（buffer-kernel / split / precision-perf） | 产出方即查证：标 UNVERIFIED 前必须先查证源 | 修B |
| B3 | `skills/ascendc-op-tiling-buffer-kernel/SKILL.md` selfcheck + `ascendc-op-design-validate/SKILL.md` GV9-a | selfcheck 边界收窄（只判结构不判查证对错）+ GV9-a 语义匹配（`verification==UNVERIFIED` 且涉及硬件 API，含子类） | 修B |

---

## 1. 修A — design_chip 不再由 agent 决定

**根因**：`requirement-analyst` 把 skill schema example 里的 `A5` 当真值、当 ambiguity 自行决议，凭空产 `hardware constraint design_target_chip=A5`；`_apply_design_target_chip` 无条件信 agent constraint。

**修复（优先级 `CLI > 需求文档显式 canonical 字段 > runtime 兜底`；agent constraint 不参与）**：

- **A1 入口兜底**：dispatcher 解析 chip 后，`design_chip` 为空则取 `runtime canonical`（复用 detect probe 经 `domain/chip.py` canonical 化），source 记 `runtime_default`（可诊断）。
- **A2 文档字段为准**：`requirement.transition` 调 `_read_design_chip_from_doc`——读需求文档顶层 YAML `design_target_chip`，经 `is_known_generation` 校验通过才 override 入口兜底；命中即 `is_known_generation` 通过 → `_apply_design_target_chip`，否则保留兜底。**agent 产的 constraint 不再作为 chip 来源**。
- **A3 删死字段**：`Constraint.design_target_chip` 删除（无消费者）。
- **A4 skill 去污染**：req-analysis SKILL.md 改为「基于已确定的 design_target_chip 查硬件参数，不自行决议、不写入 constraints」；schema example + op_spec_schema 文档去掉 A5 真值。

**可扩展性（§1.2）**：加 A6 只改 `domain/chip.py` 单一源（canonical 表 + `to_soc_version`），入口/文档解析/requirement 零改动自动适配——UT `test_unknown_doc_chip_ignored` 守护「未知 chip 被忽略、保留兜底」。

**TDD**：`tests/ut/orchestration/test_requirement_design_target.py` 重写为文档字段源（5 用例：doc A5→state A5 / agent constraint 被忽略 / 无 doc chip 保留 entry / 未知 chip 忽略 / from_dict 丢弃未知字段）。

---

## 2. 修C — 设计阶段逃生路径（预算尽后放行，halt 仅 429）

**根因**：validate 的 `redo_doc → __halt__` 是**无条件 halt**——只要有 docgen target 的 blocking issue 就 halt（与预算无关）。

**核心洞察**：`__halt__`（`graph_executor._execute_sequential`）只在 transition_table **显式映射**时触发；condition 不在 table → `route=None` → 线性推进（`i+=1`）；corrective 配额耗尽也是线性推进。validate 是 detailed-design group **末节点** → 删 table 条目 → group completed → 线性后继 test_design → codegen。design group 是 codegen 的线性后继（`workflow._design_root` SequentialGroup），**无需加 codegen 边**。

**两个前提约束（用户拍板）**：
- ① 逃生前**跑完所有预算**：`redo_tiling`（真正可修的 corrective）保留，跑 group `max_corrective` 配额，耗尽才放行——UT `test_redo_tiling_remains_corrective_then_escapes` 守护（tiling 跑 初始+2 loopback=3 次后才放行）。
- ② **产物不能少**：产物完整性由既有 `validate_inputs`（design_spec.inputs/outputs 非空 → `PreconditionError`）+ runner `has_all`（input_contract provides 校验）保证。**撤回**原计划的 `validate_inputs` 加 `validation_report is None` 检查——它区分不了「validate 合法未跑」（incremental / `--detailed-design` 短路 / 单 stage 调试 / 直接测 codegen 等非 design 入口，validation_report 合法为 None）与「产物非法残缺」，四把尺子皆不利（越层校验上游 group 内部状态、不可扩展到不经 validate 的入口、误伤 13 个既有测试），属过度设计。约束②的本质由 design_spec 校验承载，validation_report 检查多余。

**放行机制**：
- `redo_doc`/`human`/`redo_general` 是 validate **自己解不了**的（docgen 确定性渲染重跑无意义 / human 需人 / redo_general 回概设是不收敛 escalation）→ 删出口 → route=None → 放行带 `design_known_issues`。
- `redo_tiling` 是**可修**的 corrective → 保留，跑配额。

**halt 仅限 429**：429 退避在 `capabilities/agent/_shared.py` + `sdk_backend.py` + `opencode_backend.py`（step-57），与 design gate（`design_tree.py`/`graph_executor.py`/`workflow.py`）**零文件重叠**——429 耗尽 → `AgentResult` fatal → `fail_strategy`/`last_error` 路径，不走 condition 路由。两层正交，修C 不动 429。

**known_issues 传递（独立字段，bypass advisory）**：不用 `pending_advisories`（advisory 按 target 过滤，validate 的 target=docgen/tiling/human 不命中 codegen）——用独立字段 `design_known_issues`，codegen 直接读 `state.design_known_issues`。

**TDD**：`tests/ut/orchestration/test_design_escape_hatch.py`（10 用例：transition table 只留 redo_tiling / redo_doc 放行不 halt / human 放行不 halt [带 pipeline routes 证明不冒泡] / redo_tiling 跑配额后放行 / ValidateStage.transition populate known_issues / clean pass 清空 / codegen materialize+prompt）；`test_design_routing.py` `TestValidateDocgenHalt`→`TestValidateDocgenEscape`；`test_design_workflow_integration.py` detailed-design pipeline routes 断言改「不在 table」；`test_stages.py` 两个 requirement chip 测试重写为文档字段驱动（修A 后 agent constraint 不再是 chip 来源）。

---

## 3. 修B — UNVERIFIED 加消费者 + selfcheck 边界

**根因**：`derived` 判据太窄（只「数学推导」，不含文档推导）→ VC-BK-3 读了 `platform_diff.md` 做映射推理本该 `derived`，却标 `UNVERIFIED`；UNVERIFIED 标了无消费者升级；selfcheck 越界判查证对错（数值对比真值表）。

**修复（claims 的 `verification` 是查证唯一权威，§2.5）**：

- **B1 权威定义（checkpoint_convention.md）**：
  - `derived` 明确含**文档推导**（读已查证源 + 映射/等价推理，结论可复算）。
  - `UNVERIFIED` 是 **last resort**：标之前必须先查证，必填 `evidence.why_unverifiable`。
  - `evidence` 裸字符串 → 结构化 `{source_pointer, attempt_log, why_unverifiable}`。
  - `claim_type` 明确 `hardware_api_capability` 含子类（a5_vf_split 等），不得自造新值。
  - selfcheck 边界：只判结构/逻辑，**不判查证充分性**；不因 claim UNVERIFIED 而 fail，不因 selfcheck 通过而提升 verification。
- **B2 产出方即查证（3 tiling skill）**：标 UNVERIFIED 前必须先查证源（`platform_diff.md`/`ascendc-dev-knowledge`），查到升 `derived`/`api_checked`，查不到才 UNVERIFIED 附 why。
- **B3 边界收窄 + 语义匹配**：buffer-kernel selfcheck「数值对比真值表」改为「只判有命名来源、非裸数」（对错归 claims）；validate GV9-a 字面 `claim_type==hardware_api_capability` 改**语义匹配** `verification==UNVERIFIED 且涉及硬件 API`（含子类），堵 a5_vf_split 漏网。

**无 UT（纯 skill guidance）**：工程层不解析 `verifiable_claims`（grep 确认无 Python 读 claim_type/verification/evidence），claim 纪律靠 agent 遵守 + heavy_llm e2e 守护（§3.9）。buffer-kernel schema 的 `required_keys` 是 `[template, buffer_kernel]`，selfcheck 不在 schema，无需改。

---

## 4. 验证

- **修A UT**：`test_requirement_design_target.py`（5）+ chip 相关回归（`test_chip_decision_event`/`test_state_chip_fields`/`test_run_chip_flags`/`test_predesign_chip_gate`/`test_context_chain_e2e`/`test_requirement_proto`）55 passed。
- **修C UT**：`test_design_escape_hatch.py`（10）+ design routing/graph/groups/workflow/substages/state/codegen 回归 230 passed。
- **修B**：纯文档，无 UT（靠 heavy_llm 守护）。
- **全量**：UT + 非 heavy ST + 可达性预检（`-m "not heavy_llm"`）= **2423 passed / 7 skipped / 12 deselected（heavy_llm），零回归**（撤回 validation_report 检查后恢复 13 个被误伤的既有测试）。
- **heavy_llm（§3.11，跑前确认）**：e2e 复现本次场景（A2 环境 + 无 chip 声明的需求），验证逃生路径真实生效、codegen 拿到 known_issues 继续。

## 不改的（避免误伤）

- `domain/chip.py`（单一源，故意不留 alias）。
- `graph_executor.py` corrective/escalate/halt 执行语义（已正确，修C 只删 table 条目借力既有 route=None 线性推进）。
- `runner.py` `has_all` contract 校验。
- `capabilities/agent/*` 429 退避（与 design gate 正交）。
- corrective loop / `is_satisfied` / `max_corrective`（保留，先跑完预算）。
- `general-design` group 的 halt（概设结构问题 halt 合理——无概设谈不上进 codegen，与详设不完美逃生区分）。
