# step-64 — general_design.json 契约拍平 — 实施方案（第四层）

> L3 见 `64-general-design-json-contract-analysis.md`；L1 见 `06-problems.md` P87。

## 1. schema 拍平：`.claude/skills/ascendc-op-general-design/schema/general_design.json`

- `required_keys`：`["op_name", "sections"]` → `["op_name", "split_axis_priority", "tiling_data", "loop_framework", "buffer_eval"]`
- 删 `sections` 包裹层，四字段提到顶层（值结构：数组/数组/字符串/对象）。
- `gradient_formula` 保留顶层可选（CR2 条件性，本就不在 required_keys）。
- 新增顶层可选 `narrative` 字符串字段（CR3 扫描源 + 人读散文）。
- `description`/`example` 同步改为拍平后顶层结构。

## 2. review schema 键名收敛：`.claude/skills/ascendc-op-general-design-review/schema/general_design_reviewed.json`

- `cr1` example 键：`split_axis_priority_3_4`/`tiling_data_4_2`/`loop_framework_4_3`/`buffer_feasibility_5_1` → 裸字段名 `split_axis_priority`/`tiling_data`/`loop_framework`/`buffer_eval`。
- `patched_nodes` example：`["§3.4 切分轴优先级"]` → `["split_axis_priority"]`。
- `blocking_issues[].detail`/`acceptance` example：去 §号后缀残留（"§2 缺 dtype 矩阵...产出 §4.2" → "需求规格缺 dtype 矩阵...产出 tiling_data 字段"）。

## 3. general-design SKILL.md 重写：`.claude/skills/ascendc-op-general-design/SKILL.md`

读写介质从"markdown 章节"改为"JSON 顶层字段"，判断/生成方法论不变：

- 开场白/输出表：产物 `general_design.json`，`required_keys` 列拍平后 5 字段；声明"唯一产物是 general_design.json，不再单独产 markdown"。
- "概设内容组织（八段式）"：重述为内容组织指引（非文档章节骨架），八段表加"落入字段"列（结构化字段 vs `narrative`）。
- 步骤 1 概设完整性判断：检查内容语义齐全（不绑文件格式）→ 检查 4 顶层字段 + narrative。
- 步骤 3.5 输出分类结果：设计路径分类写入 `narrative`（无独立字段，与 CR3 `general_design_level` 区分）。
- 步骤 4 读取 op_spec：素材落 `narrative`；归一化层梯度公式另写 `gradient_formula`。
- 步骤 6/7.1-7.3/7.5/8.1/8.4/9.2-9.3/10/11：→ `narrative`。
- 步骤 7.4 多核切分轴优先级 → `split_axis_priority`。
- 步骤 8.2 TilingData 字段定义 → `tiling_data`；步骤 8.3 各模板循环结构 → `loop_framework`。
- 步骤 9.1 Buffer 可行性评估 → `buffer_eval`。
- 步骤 12 组装文档：组装 `general_design.json`（Write 一次，顶层字段 + narrative）。
- 步骤 13 质量自检：检查 JSON 字段存在/非空；自检摘要写入 `narrative` 末尾（修正 stale `checkpoints/general-design.json` → `general_design_reviewed.json`）。
- 文档维护约定末段备注：review 直接读 JSON 字段，不依赖章节号作解析锚点。

## 4. review SKILL.md 重写：`.claude/skills/ascendc-op-general-design-review/SKILL.md`

- CR1 表"章节位置"列（§3.4/§4.2/§4.3/§5.1）→ "字段"列（`split_axis_priority`/`tiling_data`/`loop_framework`/`buffer_eval`）。
- CR1 修复原则：行内批注 `[由 general-design-review 自动补入]` 废弃，`patched_nodes[]` 为审计轨迹。
- CR2：读 `gradient_formula` 字段（缺失/空 = N/A）；修正即 Edit 覆写该字段值。
- CR3：扫描 `narrative` 字段（非"总体设计之后的章节"）；`section` 为 narrative 内文案 free-text 锚点。
- 无法就地修 target 表：`§3~§5`→四结构化字段；`§2`→`requirement.json`。
- 步骤 0：`general_design.md` → `general_design.json`（修文件内自身不一致）。
- 步骤 1：章节存在预检 → 4 顶层字段存在/非空预检。
- 步骤 2（CR1 四子项）：搜索章节 + 插入批注 → 直接读字段 + Edit 赋值 + `patched_nodes` 记录。
- 步骤 3（CR2）：搜索 markdown 梯度公式 → 读 `gradient_formula` 字段。
- 步骤 4（CR3）：扫描"总体设计之后章节" → 扫描 `narrative`。
- 步骤 5：取消"覆写概设文档 + 插入摘要块"——就地修改已在 2/3 落盘，摘要冗余于 `review_summary`。
- 步骤 6 自检：判字段存在/非空 + `patched_nodes` 记录（删行内批注 checklist 项）。
- 步骤 7 inline JSON 模板：`cr1` 键去 §号后缀（与 schema example 对齐）；`patched_nodes`/`section` example 同步。
- 约束段：行内"标注来源" → `patched_nodes` 审计轨迹。
- 知识引用策略：`§5.1`/`§5 附录` → `buffer_eval`/`narrative`。

## 5. 测试更新

- `tests/ut/adapters/test_design_schemas.py::test_general_design_missing_key_fails`：断言 `"sections" in e` → `"split_axis_priority" in e`（拍平后字段名）。
- ST 种子文件（罐装 `general_design.json` 载荷）从 `{"sections": {...}}` 改为拍平后顶层结构：
  - `tests/st/test_design_tui_selfclosure.py`（2 处：`_seed_integrate_inputs` / `_seed_tiling_with_feedback`）
  - `tests/st/test_design_docgen_tui_selfclosure.py`（1 处）
  - `tests/st/test_predesign_chip_gate_resume.py`（1 处 stub spawn canned content）
  - `tests/st/test_design_claims_anchor_selfclosure.py`（1 处）
  - `tests/st/test_design_pipeline_e2e.py`（`_ARTIFACTS` 文件载荷 1 处 + 2 处 `State(...)` 构造）
  - `tests/st/test_self_evolution_stages.py`（1 处 `State(...)` 构造）
- 其余 UT 文件里 `State(general_design={"sections": ...})` 构造（test_state_design_fields / test_design_substages / test_design_artifacts_reinjection / test_codegen_upstream_reuse / test_decision_log）——`state.general_design` 是未类型化 dict，bypass `validate_payload`，**不需要改**（实证：226 design UT 全绿）。

## 6. 验证

- **schema 层**：`test_design_schemas.py`（含 `test_example_satisfies_own_schema` 参数化跑全部 15 schema + 改写后的 `test_general_design_missing_key_fails`）全绿。
- **全量 UT**：`pytest tests/ut/` → **2333 passed, 7 skipped**，零回归。
- **grep 残留实证**（两份 SKILL.md + 两份 schema）：
  - `general_design.md`（排除合法的 `existing_general_design.md` 输入引用）= 0
  - `§3.4`/`§4.2`/`§4.3`/`§5.1`（§号后缀 cr1 键）= 0
  - `"sections"` 包裹 = 0
  - `§1.3` 残留（CLAUDE.md 引用，合法）/ `[由 general-design-review 自动补入]` 残留（说明该标注已废弃的元文本，合法）——这两项是 intentional。
- **heavy_llm 适用性判断 + 实跑**（比照 step-63）：本次工程侧行为不变（两 stage 类零改动），但 schema `required_keys` 变严格（4 字段从未强制→现在强制），存在"agent 遵新 SKILL.md 产拍平结构"的真实链路需验证，不能纯靠零改动豁免。经用户确认（§3.11）后实跑三组 heavy_llm e2e，**全绿**：
  - **契约回归**（`test_design_tui_selfclosure.py` + `test_design_docgen_tui_selfclosure.py`，design pipeline 读拍平 general_design.json 自闭环 + docgen 继承）：**4 passed in 670s**——拍平后下游 template-division/integrate/docgen 端到端零回归。
  - **#19 req-analysis 自闭环**（`test_req_analysis_selfclosure.py`，验证 step-63 改名后真 LLM 产 requirement.json 非 op_spec.json + 过 schema）：**1 passed in 304s**。
  - **#18 review 三向路由**（`test_review_target_routing_selfclosure.py`，P84 target 根因表第一次真 LLM 验证：requirement 缺 dtype→target=requirement / 需求完整+概设缺 loop_framework→target=generator）：**2 passed in 801s**——review 真按根因判 target，三向路由不空转。
