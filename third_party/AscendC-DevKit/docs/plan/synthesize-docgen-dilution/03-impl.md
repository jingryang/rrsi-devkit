# 03 — 实施方案（L4）

> 本工作：`docs/plan/synthesize-docgen-dilution/`。回答「改哪个函数、什么顺序、怎么验证」。
> 依据 `02-analysis.md` 冻结的方案 A（docgen 独立成段）+ 方案 C（定向 respawn 兜底）。

## 关键调查结论（决定落点，比 L3 初判更简单）

1. **runner 层已有「output_contract 未满足 → 自动重试」**：`kernel/runner.py` 的迭代
   while 循环（`436-447` 未满足即继续；`473-475` 命名 `missing` 字段），直到
   `iterations.stages.<stage>` ceiling。
2. **已有「缺产物 → user_feedback → 下一轮提示」的雏形**：`design_substages.py` 的
   `_missing_artifact_error`（设 `user_feedback`，注释明言「re-spawn 就是为让 misplaced
   产物被定向 hint 纠正，不首 miss 就 halt」）。
3. **unique halt 的直接原因**：`SynthesizeStage.transition` 缺 md 用的是 `_error`
   （只设 `last_error`，feedback 无 skill 提示）→ 重试 N 次 agent 反复漏 docgen →
   iteration ceiling 耗尽 → `fail_strategy=halt` halt。
4. **结论**：方案 C **不新造 respawn 机制**，复用 runner 的「contract 未满足 → 重试」
   + 现有 user_feedback 通路，只补「skill 提示」。方案 A 拆段才是结构性改动主体。

---

## 方案 A — docgen 独立成段（根治）

### 改动顺序

**1. `design_substages.py`**
- `SynthesizeStage.transition`：删除「第 3 步 docgen 定位 md」（`glob("*_详细设计说明书.md")`）
  和「第 4 步 OpDef canonical 正向锚点兜底」两段；保留 integrate 职责（读 JSON +
  归一化 scalar/rank/param_type/inplace）。`SynthesizeStage` 的 `output_contract`
  改为 `provides=["design_spec", "tiling_strategy"]`、`optional_provides=["data_flow"]`。
- 新建 `DocgenStage(_DesignSubstage)`：
  - `name = "docgen"`、`agent_name = "ascendc-design-generator"`、`_schema_files = []`（md 非 schema）。
  - `input_contract` `requires=["design_spec", "tiling_strategy"]`；`output_contract`
    `provides=["design_doc"]`。
  - `transition`：从 `state` 读 `design_spec`/`tiling_strategy` → `glob("*_详细设计说明书.md")`
    → 缺则走方案 C 的反馈（非 `_error`）→ canonical 兜底（`_opdef_missing_canonical_anchors`）。

**2. `design_tree.py`**
- `build_detailed_design_group` children 在 `SynthesizeStage()` 后追加 `AtomicStage(DocgenStage())`。
- `output_contract_override` 不变（`design_doc` 仍由组提供，现由 docgen 段产出）。
- `_DETAILED_DESIGN_TRANSITION_TABLE` 不变（`dd-intake.short_circuit` 仍到 synthesize，docgen 线性后继）。

**3. `resources/orchestration-config.json`**
- `skills.stages`：`"synthesize": "ascendc-op-design-integrate"`（改，不再用门面）；
  新增 `"docgen": "ascendc-op-design-docgen"`。
- `skills.tail_calls`：删 `"ascendc-op-design-synthesize"` 条目（门面废弃）。
- `iterations.stages`：新增 `"docgen": 3`。

**4. `design_artifacts.py`（无需改，实施中确认）**
- design_doc 是 md 路径（非 JSON 契约产物），此前合并版也不在 `simple` 列表里
  （仅 runtime 经 `state.with_updates` 传递，resume 靠 docgen 段重生成）——§1.14 不新增不必要解析。

**5. skill 层（§2.5 唯一通路，删旧债）**
- 删门面 skill `.claude/skills/ascendc-op-design-synthesize/`（不再被任何 stage 引用）。
- `ascendc-op-design-integrate` / `ascendc-op-design-docgen` 保留。

### 连锁影响

- `tests/st/test_design_tui_selfclosure.py::TestSynthesizeFacadeSelfClosure`（门面自闭环）
  → 改写为「docgen 独立段自闭环」（读 synthesize 产物写 md），或删除（门面已废）。
- 其它引用 `ascendc-op-design-synthesize` 的测试/配置同步清理（grep 确认零残留）。

---

## 方案 C — 缺产物 feedback 加 skill 提示（兜底）

### 改动顺序

**1. 通用 skill 提示（base 层，不耦合具体 stage/skill）**
- 在 `_DesignSubstage`（或 base `Stage`）加一个通用 helper：
  `_missing_artifact_feedback(state, missing: list[str])`，措辞：

  > 缺了 {missing}。本阶段 skill 为 {skill_allowlist(STAGE_SKILL_MAP[self.name])}，
  > 可能是某 skill 未正确调用和执行，如果确认请继续完成 skill 任务。

- skill 来源 `skill_allowlist(STAGE_SKILL_MAP[self.name])`（复用现有配置，不新增映射）。
- `DocgenStage` 缺 md 走这个 helper（设 `user_feedback` + `last_error`，走 runner 重试），
  **不是 `_error` 裸 halt**。

**2. 有界重试**
- 复用现有 `iterations.stages.docgen` ceiling + runner 的 contract-未满足重试，不新增上限。

---

## 验证

- **UT**：
  - `DocgenStage`：缺 md → `user_feedback` 含 skill 提示、措辞含「可能」不武断断言「未调用」。
  - `SynthesizeStage`：不再检查 md（缺 md 不再 halt）。
  - `design_tree`：detailed-design children 序列含 docgen 段。
  - 配置加载期：`validate_skill_map` 对 synthesize→integrate、docgen→docgen 通过，门面条目已清。
- **heavy_llm**：用 `unique` 复现缺 md 场景，验证兜底定向补出 md 而非 halt（坐实 A+C 的唯一端到端证据）。
- 全量 UT + 非 heavy ST 绿（§3.2）。
