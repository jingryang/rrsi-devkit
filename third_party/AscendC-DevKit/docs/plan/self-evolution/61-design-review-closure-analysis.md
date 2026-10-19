# step-61 — 概设 review 闭环——三向路由 + known_issues 跨 gate 累积 + SKILL target 根因归属 — 方案分析（第三层）

> 对偶于 step-60 修C（详设 validate escape）。step-60 解决详设 validate 无逃生，本步补全概设 review 同类问题：review 只能 halt 写 markdown、工程三向路由从未触发、known_issues 只 validate populate、SKILL 产物范式断裂。L1 见 `06-problems.md` P84。

## 0. 核心原则（用户拍板）

- **review 与 validate 同构**：概设 review 复用详设 validate 的逃生范式——问题写 blocking_issues 走工程路由，预算耗尽才逃生，不 halt 写 markdown。
- **target 按根因归属，不按表象**：判据是「generator 凭现有需求能否独立修好」——能→generator；根因在需求规格→requirement；连需求层都定不了→human。
- **不重复造轮子**：review 闭环复用详设 redo_tiling 同款范式（gate→产出方 corrective）；gate 通用方法提公共基类；反馈渲染提公共函数。
- **诚实记录**：review 与 validate 的未消解 issue 累积进 design_known_issues 且不互覆盖，进 codegen 时为所有 gate 未消解之和。

## 1. 公共抽象：gate 方法提 _DesignGate 基类

- **拍板**：review/anchor/validate 三 gate 的 `loopback_feedback` / `is_satisfied` / `error_signature` / `resolve_condition`（除 mapping）一字不差，纯通用零差异 → 用继承（中间基类 `_DesignGate`）消除样板；`resolve_condition` 的 mapping 差异由子类 `issue_target_mapping` 属性承载，共同路由逻辑内联复用既有 `_resolve_with_redirect` / `_route_from_issues`。单继承链（`_DesignGate → _DesignSubstage → Stage`），非 gate substage 仍继承 `_DesignSubstage` 不携带 gate 语义。
- 不选 Mixin（单继承已够，无收益）；不选继续各 gate 重复（DRY 违反）。

**抽象边界（避免 over-extraction）**：纯通用零差异方法→继承；有差异但共享逻辑的方法→内联共同逻辑 + 子类属性承载差异，不提取单行 wrapper；`_set_known_issues`（跨 gate 零差异）→ 基类公共方法。曾误提 `_gate_condition`（一对一 wrapper）→ 删除。

## 2. review 三向路由：target → condition

目标态 `GeneralDesignReviewStage.issue_target_mapping`：

| target | condition | 工程路由 |
|---|---|---|
| generator | redo_generator | 回 general-design-generator corrective 闭环修（跑 max_corrective，耗尽才逃生） |
| requirement | design_input_invalid | bubble 到 pipeline 层 requirement（带 feedback） |
| human | human | halt 交人 |

generator 闭环复用详设 redo_tiling 同款范式（gate→产出方 corrective）：概设层可修的问题不越层，自闭环优先，预算耗尽才逃生。requirement 走既有 escalate 机制。human 保留 halt（真需人决策，非可修类）。

## 3. known_issues 跨 gate 累积：按来源分区

- **拍板**：issue 标 `source`，`_set_known_issues(state, new_state)` 保留别 gate 遗留（`source != self.name`）+ 用本轮 blocking_issues 替换自己切片（标 `source=self.name`）。review 与 validate 串行写入不互覆盖；clean pass 只清自己切片；进 codegen 时 = 所有 gate 未消解之和。
- 不选覆盖式（冲掉别 gate 遗留）；不选追加式（多轮 corrective 重复累积同一 issue）；不选按 target/code 区分 scope（target 跨 gate 重叠如 human，不稳）。

`_set_known_issues` 是 gate 通用语义，落 `_DesignGate` 基类；review/validate 各自在 transition 调用（transition 本身不统一——各 gate 读不同 report）。

## 4. review→requirement bubble 带 feedback

- graph_executor 提模块函数 `_capture_loopback_feedback(child, state)`，在 corrective-jump **和** escalation-bubble 两条路径都注入 `state._loopback_feedback`（gate 的 blocking_issues）。
- issue_render 提公共函数 `render_loopback_feedback_section(state)` 渲染「## 上次反馈」；`_DesignSubstage._feedback_section` + `RequirementStage._build_analysis_prompt` 都调它（requirement 非 `_DesignSubstage` 但消费 feedback → 提函数复用而非继承设计子 stage 机器）。

## 5. SKILL target 指导 + 产物范式收敛

**target 归属判据（核心，用户拍板）**：generator 凭现有需求能否独立修好？
- 能（根因在概设产物本身：章节缺失但 §2 需求完整、结构不全、公式推导不足）→ generator。
- 不能（根因在需求规格：缺 dtype 矩阵、缺算子公式、需求矛盾）→ requirement。
- 连需求层都定不了（方向歧义）→ human。

要点（用户纠正）：「章节缺失」不必然归 requirement——先看 §2 需求规格：需求对、章节缺→generator（没产够）；需求本身缺信息→requirement。能闭环修的优先 generator，不轻易上抛或交人。human 仅用于连需求层都无法定的方向性决策。

**产物范式收敛**：SKILL.md 删 B1/B2/B3 markdown 阻断 halt → 写 blocking_issues 带 target+acceptance 走工程路由；步骤 7 / 职责 / 约束 / 输出契约从 `checkpoints/general-design.json`（旧 checkpoint 范式）收敛到 `general_design_reviewed.json`；schema description + example 教 target/acceptance，**不加** `issue_required_keys`（review `strict=False` 不消费 errors，避免死配置——schema 契约主引导 + strict 宽容兜底组合）；删 B3 路径项（路径解析是工程层 `_read_disk_artifacts` 职责）。

## 6. 实施顺序与依赖

1. `_DesignGate` 公共基类（地基）。
2. `issue_target_mapping` 加 generator→redo_generator（review→generator 闭环）。
3. `_capture_loopback_feedback` 扩展到 escalation-bubble + requirement 读 feedback（review→requirement 闭环）。
4. `_set_known_issues` 跨 gate 累积（review + validate 都 populate）。
5. SKILL target 指导 + 产物范式收敛。

## 7. 不改的（避免误伤）

- validate 的 `issue_required_keys=["acceptance"]`（详设 strict，现状正确）。
- `checkpoint_convention.md` manifest 拓扑段（独立遗留，P84 客观事实 5 记录，本次不动）。
- 非 gate substage 的 `fail_strategy=halt`（产物残缺走 contract，逃生只放行 gate blocking_issues）。
