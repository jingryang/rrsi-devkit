# step-78 — gate scope & ownership contract — L4 实施方案

> 性质：self-evolution 线 L4 实施方案，step 78。承接 L3 `78-gate-scope-ownership-contract-analysis.md`（已冻结）。
> 纪律：TDD（§3.1，每 slice 红→绿）；全覆盖（§3.2，UT + 非 heavy ST 全绿，heavy_llm 列清单 §3.11）；符号级落点。
> 不扩 halt（step-60 边界不动）；越界 issue drop+warn 不 carry；feedback-selfcheck 本次泛化。

---

## 0. 实施总览（slice 顺序，每 slice 独立 TDD 可验证）

| slice | 内容 | 依赖 | 状态 |
|---|---|---|---|
| 1 | 域模型 `GateScope`/`Capability` + 构造期约束 | — | ✅ 17 UT |
| 2 | loader（复用 SchemaLoader 路径约定读 `schema/gate_scope.json`/`capabilities.json`） | 1 | ✅ 8 UT |
| 3 | 加载期校验 INV-B（join + 唯一性 + channel 存在），挂 startup 链 | 1,2 | ✅ 9 UT |
| 4 | 运行期 INV-A + 多 issue 路由改造（`_DesignGate`） | 1,2 | ✅ 7 UT（含 step-76 字典序回归） |
| 5 | 数据声明：3 gate scope + N producer capabilities | 1,2,3 | ✅ 3 gate_scope.json + req capabilities |
| 6 | feedback-selfcheck 泛化（去 tiling 硬编码）+ tail_calls 挂载 | 3,5 | ✅ SKILL.md 4-producer 表 + 接线 UT + 加载期覆盖校验 |
| 7 | requirement `math-equiv-golden` 首例（capability + selfcheck，= step-76 主修-1） | 5,6 | ✅ SKILL.md 数值等价自检 |
| 8 | 回归 + heavy_llm 清单 | 全部 | ✅ UT 全绿 + heavy_llm 7/7（§9） |

slice 1–4 是机制（可先全绿，不带数据）；5–7 是数据 + 首例；8 验证。建议按此序，1–4 落地后机制可用、再用 5–7 填实。

> **实施完成（2026-07-28）**：slice 1–8 全绿。UT 回归——`ut/orchestration`+`ut/domain` 1860、`ut/adapters` 320（7 skip 需 NPU/CANN）、`ut/orchestration/test_graph_executor` 38、touched 层 253，全 pass。heavy_llm 7/7 PASSED（用户确认跑，§3.11；真实链路零回归，详见 §9）。step-76 自旋症状由 slice-4/5 确定性防住；slice-7 深度数学正确性是 LLM 自引导，建议集成期人工 spot-check。

---

## 1. 域模型（新建 `src/ascendc_devkit/domain/gate_scope.py`）

```
GateCheck(code, description, self_fixable: bool,
          fix_owner: str = "",        # target 词汇，与现 issue_target_mapping 一致：generator/requirement/human/tiling/docgen
          feedback_channel: str = "") # tail-call skill bare name
GateScope(skill: str, checks: list[GateCheck])
Capability(code, description)
CapabilitySet(skill: str, capabilities: list[Capability])
```

**构造期约束（`__post_init__`）**：`GateCheck.self_fixable=False ⇒ fix_owner 非空 AND feedback_channel 非空`，否则 `ValueError`。这让"越界且无反馈渠道"的检查在声明解析时就炸（§1.3）。

**共享 key = check `code`**（如 `GD-R1`/`math-equiv-golden`）：gate 声明"我查 code X、修不了则 fix_owner=Y"；producer Y 的 skill 声明 capabilities 含 code X。join 在 code 上，不另立 ID 名空间。

---

## 2. loader（扩展 `src/ascendc_devkit/adapters/schema/loader.py`）

复用现有 `_read_schema_json` + `_SKILLS_ROOT` + `lru_cache`，新增：
- `load_gate_scope_from_skill(skill) → GateScope`：读 `.claude/skills/<skill>/schema/gate_scope.json`。
- `load_capabilities_from_skill(skill) → CapabilitySet`：读 `.claude/skills/<skill>/schema/capabilities.json`。

文件缺失处理区分：
- gate skill 无 `gate_scope.json` → **加载期 fail**（issue-routing gate 必须声明 scope，否则 INV-A 无据可依）。哪些 skill 是 gate 由 §3 的 gate 清单显式枚举（不靠启发）。
- producer 无 `capabilities.json` → 空 `CapabilitySet`（合法，表示该 skill 不承接任何 loopback 修复）。

---

## 3. 加载期校验 INV-B（扩展 `src/ascendc_devkit/orchestration/skill_config.py`）

新增 `validate_gate_scope(all_skills) → list[str]`（errors），挂 `application/dispatcher.py:816` startup 链（接既有 `agent_errors`/`skill_errors` 汇总，fail → `EX_CONFIG`，复用 `validate_skill_map` 风格）。

校验项：
1. **join（INV-B）**：每个 gate check `self_fixable=False` 的，`fix_owner` 经 `STAGE_SKILL_MAP`（target→stage→skill）解析出 producer skill，该 skill 的 `CapabilitySet` 必须含同 `code`。解析不出 / capability 缺 → error。
2. **capability code 全局唯一**（跨所有 producer）。
3. **feedback_channel 存在**：`self_fixable=False` 的 `feedback_channel` 必须是 `.claude/skills/` 下真实存在的 skill（复用 `_flat_skills_on_disk`）。
4. **gate 清单完备**：显式 gate 清单里每个 gate 都得有 `gate_scope.json`。

⇒ INV-B 由构造保证（声明时 join 死，加载期拦不一致）。

---

## 4. 运行期 INV-A + 多 issue 路由（改 `src/ascendc_devkit/orchestration/stages/design_substages.py`）

### 4.1 `_DesignGate` 加载自己的 GateScope
基类持有 `self.gate_scope`（构造时按 `self.name`→skill 经 `STAGE_SKILL_MAP` 解析 + `load_gate_scope_from_skill`）。

### 4.2 INV-A 校验（新 helper `_validate_issue_scope(issues) → (kept, dropped, warnings)`）
在 `transition()` 解析出 `blocking_issues` 后、路由前调用：
- `issue.code ∈ gate_scope.checks codes` → keep；若 `issue.target` ≠ 该 code 声明的 `fix_owner` → **以声明 fix_owner 覆写** + warn（declaration 权威，gate 自标 advisory）。
- `issue.code ∉` 声明范围（越界）→ **drop** + 醒目 warn（要求更新声明或修 skill 内容），**不 carry**（防毒性前逃）。

### 4.3 多 issue 路由（替换 `_route_from_issues` 字典序逻辑）
- 改为**按每 issue 的声明 fix_owner 逐条定 condition**（不再 `_route_from_issues` 按 mapping 插入序合并出一个）。
- 多 target：选**最上游 fixable target** 路由（requirement < generator < ...），其余 issue 进 `design_known_issues`（已有 `_set_known_issues`，不丢；下游 review 重跑自然再 surface）。
- 收敛复用现有 `max_corrective`/`max_escalations`/stagnation（`error_signature same>=2`），**不新造收敛逻辑**。
- `review_redirect`（`_resolve_with_redirect`）优先级保留不变。

---

## 5. 数据声明清单（slice 5）

**3 gate scope**（`.claude/skills/<skill>/schema/gate_scope.json`），按各 gate SKILL.md 实际职责枚举 checks：
- `ascendc-op-general-design-review`：CR1 四字段 + CR2 梯度公式 + CR3 详细度（**不含** math-equiv——那是 requirement 的）。自修的标 `self_fixable=True`；`target=requirement` 仅保留给"填 CR1 时发现缺信息"（schema example 本意）。
- `ascendc-op-design-anchor-consistency`：anchor 检查项（report-only，`self_fixable=False` + `fix_owner=tiling` + `feedback_channel=ascendc-op-design-feedback-selfcheck`）。
- `ascendc-op-design-validate`：GV 系列（redo_tiling 自修路径 + redo_doc/human 前逃）。

**N producer capabilities**（`.claude/skills/<skill>/schema/capabilities.json`）：
- `ascendc-op-req-analysis`：`math-equiv-golden` + 缺信息类。
- `ascendc-op-general-design`（generator）：CR1 字段补全类。
- `ascendc-op-tiling-*`：各 tiling 修复类（对应现有 feedback-selfcheck 消费的）。

---

## 6. feedback-selfcheck 泛化（slice 6）

改 `.claude/skills/ascendc-op-design-feedback-selfcheck/SKILL.md`：
- **去 tiling 硬编码**：报告源参数化（不只 `validation_report`/`anchor_report`，按本 producer 上游 gate 报告读）、过滤参数化（不只 `target=tiling`，按 fix_owner）、修复对象参数化（不限 tiling 段，按本 producer 产物）。
- 保留通用模式：读**全历史轮** issue + 逐条 `acceptance` 回验（不臆造判据）+ 能修就地 Edit + 修不了标 unresolved + 复用既有 stagnation halt。
- 挂载：`resources/orchestration-config.json` 的 `skills.tail_calls` 给所有 `self_fixable=False` producer 加 `ascendc-op-design-feedback-selfcheck`（经 `STAGE_TAIL_CALL_MAP`）。

必要性：声明的 `feedback_channel` 必须有真消费者，否则虚假闭环（§2.9）。这是 INV-B 落地的配套闭环。

---

## 7. requirement `math-equiv-golden` 首例（slice 7 = step-76 主修-1 纳入）

- `ascendc-op-req-analysis/schema/capabilities.json` 声明 `math-equiv-golden`。
- `ascendc-op-req-analysis/SKILL.md` 自检环节（L165-173 既有闭环）加：math_formula 产出处自检数值等价 golden（确定性脚本：小张量数值反例比对），不等就地 re-derive，真冲突走 resolve_ambiguity→human。
- general-design-review 的 gate_scope **不含** math-equiv → review 越界查 math 被 INV-A drop（step-76 直接根治）。

---

## 8. TDD 用例（每 slice 红→绿）

- **slice 1**：`GateCheck.self_fixable=False` 缺 fix_owner/channel → `ValueError`；`GateScope`/`CapabilitySet` 构造。
- **slice 2**：loader 读 gate_scope/capabilities；gate 无 gate_scope.json → fail；producer 无 capabilities.json → 空 set。
- **slice 3**：`validate_gate_scope` 正例通过；反例——fix_owner 的 producer capability 缺 code / capability code 重复 / feedback_channel skill 不存在 / gate 清单缺 gate_scope.json → 各自 error。
- **slice 4**：INV-A——越界 code 被 drop+warn（不进 known_issues）；target 标错以声明覆写；多 issue 路由选最上游 fixable、其余进 known_issues（**专门覆盖 step-76 字典序优先级 bug**：同轮 generator+requirement 不再 generator 永远赢）。
- **slice 6**：泛化 selfcheck 对非 tiling producer 也能读报告 + acceptance 回验。

---

## 9. 验证

- **UT 全量** 全绿（§3.2，0 回归）：`ut/orchestration`+`ut/domain` 1860 pass、`ut/adapters` 320 pass / 7 skip（需 NPU/CANN）、`test_graph_executor` 38 pass、touched 层（gate_scope/loader/validate_gate_scope/gate_scope_runtime/skill_config/design_substages/loopback_summary/review_redirect）253 pass。环境缺 NPU/CANN，UT 经 `--quick` 跑（排除 llm/npu/slow/cann）；design-pipeline 的 gate/loopback 逻辑由 UT 充分覆盖，非 heavy ST 无额外用例。
- **heavy_llm 守护评估（§3.11，交付/合并前用户决策跑）**——按 §3.9 逐链路核真实守护，诚实记录**未新写**的 heavy_llm 及理由：
  - **slice-4（INV-A + 多 issue 路由）→ 无需新 heavy_llm**。确定性守护：`test_gate_scope_runtime`（UT，加载**真实 gate_scope.json**，含 `test_requirement_wins_over_generator_when_both_present` step-76 回归）；真实链路守护：既有 `test_review_target_routing_selfclosure`（B-req/B-gen，review 真 LLM 产 target=requirement/generator）。多 issue 优先级是**框架路由**（非 LLM 行为），UT + 真实 gate_scope 即正确守护层级。
  - **slice-6（vf-design 反馈消费）→ 既有 heavy_llm 已守护机制**。确定性：`test_skill_config` 断言 vf-design→feedback-selfcheck 接线闭包；真实链路：既有 `TestDesignFeedbackConsumption::test_tiling_consumes_seeded_feedback` 守护反馈消费**机制**（vf-design 用同一 skill + 同一 tail_call，产物文件不同）。vf-design 专属用例（并行 seed）为可选增量，优先级低。
  - **slice-7（requirement math-equiv 自检）→ 建议集成期人工 spot-check，不写 brittle ST**。math_equiv 自检是**纯 LLM 自引导**，其深度正确性（如 h_post 作用域）从自由文本 requirement 输出**无法稳健机器断言**（eval 任意公式文本不可行；子串匹配 LLM 复述数学是 flaky 弱守护）。**关键**：step-76 的**自旋症状**已由 slice-4/5 **确定性防住**（review gate_scope 不含 math-equiv → INV-A drop 任何越界 math issue → 不空转），UT 守护；slice-7 是**源头质量改进**（错 math 不出 requirement），其深度验证靠集成期人工 spot-check（seed step-76 算子，确认 requirement math ≡ golden）。
  - **现有 7 个 heavy_llm（design/review/req/vfdesign TUI 自闭环 + 反馈消费）collect 干净**，未因本次改动破坏。
- **slice-6 缺口类的确定性回归守（补强，§1.3）**：新增加载期 validator `validate_tailcall_skill_coverage()`（挂 dispatcher 启动链，与 `validate_skill_map`/`validate_gate_scope` 同跑）——断言每个 tail-call feedback-selfcheck 的 producer 都在其 SKILL.md producer→product 表中。堵「接线了但 skill 没覆盖 → corrective rerun 静默 no-op selfcheck」回归（vf-design 曾这么漏）。查稳定 bare 名（非自由文本匹配，不 flaky）。UT：`test_skill_config::TestValidateTailcallSkillCoverage`（live 一致 + 反例 phantom producer 被抓 + 边界）。
- **heavy_llm 实际执行（2026-07-28，用户确认跑，§3.11）**：7/7 PASSED（1869s ≈ 31min，exit 0）——
  - `test_review_target_routing_selfclosure`（B-req/B-gen）2/2 PASS → **slice-4 review 路由改造未破坏真实链路**（review 仍按根因判 target=requirement/generator）。
  - `test_vf_design_skill_selfcloses_a5_rmsnorm` PASS + `test_tiling_consumes_seeded_feedback` PASS → **slice-6 feedback-selfcheck 泛化 + vf-design 接线真实链路通**。
  - `test_req_analysis_selfclosure` PASS + `test_design_tui_selfclosure`（integrate/chain relay）3/3 PASS → requirement 产出 + design 链路自闭环未回归。
  - 真实链路零回归；无 §3.4 修复项。
  - **诚实边界**：slice-7 的「错 math_formula → 自检 re-derive → 等价」深度自检**仍无专属 heavy_llm**（自由文本 requirement 的深度 scope 无法稳健机器断言，专属 seed-wrong-math 用例会 flaky）；#3（req 产 requirement）只确认 requirement 产出通，未专项验 math-equiv 自检触发。step-76 **自旋症状**已由 INV-A 确定性防住（不依赖该自检触发），故此边界不阻塞——slice-7 深度正确性建议集成期人工 spot-check（seed step-76 算子，确认 requirement math ≡ golden）。
- 命名/静态校验（gate 清单与 STAGE_SKILL_MAP 一致；无残留字典序路由）。

> §3.9 落实：每条真实链路均有真实守护——slice-4 路由（既有 review heavy_llm + UT）、slice-6 反馈（既有 tiling heavy_llm + 接线 UT）、slice-7 requirement 产出（既有 req heavy_llm）+ step-76 自旋症状确定性防住。slice-7 深度数学正确性是 LLM 自引导的固有局限，诚实标注不机器断言。

---

## 10. 边界与风险

- **不能解决 LLM 把已声明检查判错**（声明保证"查该查的、路由到能修的"，不保证"查得对"）。
- **主要成本在 slice 6（feedback-selfcheck 泛化）**，声明/校验（1–4）复用现成机器很轻。
- **不扩 halt**：INV-A drop、INV-B join fail 是加载期/运行期校验，不是 halt。
- step-76 收口：本步 §7 覆盖 step-76 主修-1、§4.3 结构性修掉字典序 bug；step-76 的 L4 实施并进本步。
