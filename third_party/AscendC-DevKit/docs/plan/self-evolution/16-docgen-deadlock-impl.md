# docgen→validate 死锁治理 — L4 实施方案

> 层级：**L4 / 实施方案**。配合 L3 `15-docgen-deadlock-analysis.md`。
> 记录「改哪个函数、什么顺序、怎么验证」。动手前写，按需产出。
> 覆盖范围：P13 + 兜底 A（validate `redo_doc` → 直接 halt）+ P17（均已实施）＋ P19（reviewer 移除 Glob）＋ P20（结构化吸收记录）。P18 立方案待 `redo_tiling` 频率数据（§3.6），不在本 L4 实施；兜底 B / §3.4 角色重定位仍后续。

---

## 改动 1 — P13：`DocgenStage` 装载 `kernel_pseudo_code`

### 1.1 测试先行（UT，TDD）

- 位置：`DocgenStage` 现有 UT（design_substages 测试集）。
- 用例：
  - 构造 `state.tiling_results = {"T1": {"buffer_kernel": {"kernel_pseudo_code": {overview, init, copy_in, compute, copy_out, main_loop, ...}}}}`。
  - 调 `DocgenStage()._render_detailed(state)`，断言返回 markdown：
    - 含「Kernel 架构」节标题；
    - 含 5 个函数名（init / copy_in / compute / copy_out / main_loop）；
    - 每个函数带 cpp 代码块（```cpp）。
  - 边界：`tiling_results` 缺 `kernel_pseudo_code` → 该节不崩、仅无 pseudocode 子段（graceful）。
  - 多模板：`tiling_results` 含 T1/T2 → 两段 pseudocode 各自带模板名标识。

### 1.2 代码改动

- 文件：`src/ascendc_devkit/orchestration/stages/design_substages.py`。
- 改 `DocgenStage._render_detailed`：「Kernel 架构」段在 dump `kernel_architecture` JSON 之前/之后，追加调用新方法 `_render_kernel_pseudocode(state)`。
- 新增 `_render_kernel_pseudocode(self, state) -> list[str]`：
  - 读 `state.tiling_results`（dict: `{tpl: {buffer_kernel: {kernel_pseudo_code: {...}}}}`）；为空或缺键返回 `[]`。
  - `kernel_pseudo_code` 结构（已在 L1 P13 验证）：`overview`（str）+ 5 函数节（每节 `{description: str, pseudo_code: [str]}`）+ `loop_invariant_audit`（dict）。
  - 单模板：渲染 `#### Kernel 伪代码` + overview + 每函数 `##### {func}` + description + cpp 代码块（`pseudo_code` 列表 `\n`.join）。
  - 多模板：每模板加 `### 模板《{tpl}》` 包裹。
- schema 不变：`design_doc.json` 的 `sections` / `mermaid_sources` 不动（pseudocode 只进 markdown，不进索引）。

### 1.3 验证

- UT 通过（1.1）。
- 手测：对本次 run 的 `tiling_results.json` 喂入渲染，确认 markdown「Kernel 架构」节含 5 函数完整伪码。

---

## 改动 2 — 兜底 A：validate `redo_doc` → 直接 halt（取代 error_signature 方案）

> 修订自原「`ValidateStage.error_signature`」设计（见 L3 `15-docgen-deadlock-analysis.md` §3.2 决策修订）。`ValidateStage.resolve_condition` **不改**；只改转移表的路由目标。

### 2.1 测试先行（UT，TDD）

- **用例 1（转移表断言）**：`tests/ut/orchestration/test_graph_executor.py::TestTablesPopulated.test_detailed_design_table_anchor_and_validate` 现有断言
  ```python
  assert t["validate"]["redo_doc"][0] == "docgen"
  ```
  改为
  ```python
  assert t["validate"]["redo_doc"] == ("__halt__", "escalation")
  ```
  （该行是当前唯一断言这条路由目标的地方，改这一处即完成"先测后码"中"测"的落点）。
- **用例 2（GraphExecutor 集成，新增）**：仿 `test_graph_executor.py::TestHaltRouting.test_halt_stops_and_skips_downstream` 的写法（`_CondStage`/`_RecordStage` + `transition_table={"verify": {"exhausted": ("__halt__","escalation")}}` 那套 harness），在 `test_design_routing.py` 新增一个用真实 `_DETAILED_DESIGN_TRANSITION_TABLE` 驱动的用例：
  - 构造 `docgen = _Rec("docgen", log)`、`validate = _Cond("validate", "redo_doc", fail_times=99, log=log)`（validate 恒报 `redo_doc`，模拟 GV8-A 持续 blocking）；
  - `group = CompositeGroup(name="detailed-design", children=[AtomicStage(docgen), AtomicStage(validate)], transition_table=_DETAILED_DESIGN_TRANSITION_TABLE, max_escalations=5)`；
  - `root = SequentialGroup(name="pipeline", children=[group])`；
  - 执行后断言：`log.count("validate") == 1`（只跑一次，不再被 loopback 命中第二次）、`log.count("docgen") == 1`（初始一次，**没有**因 loopback 被再次调用）、`out.is_terminal is True`。
  - 对比现有 `TestAnchorLoopback`（anchor→tiling，真实走 corrective loop 3 次）——本用例要证明的是**相反**的行为：validate→docgen 这条边一次都不应该循环。

### 2.2 代码改动

- 文件：`src/ascendc_devkit/orchestration/design_tree.py`。
- `_DETAILED_DESIGN_TRANSITION_TABLE["validate"]["redo_doc"]` 由
  ```python
  "redo_doc":     ("docgen", "corrective"),
  ```
  改为
  ```python
  "redo_doc":     ("__halt__", "escalation"),
  ```
- 不改 `ValidateStage.resolve_condition`（仍返回 `"redo_doc"`）、不改 `GraphExecutor`（`__halt__` 已是既有原语，见 L3 §2 事实 7）、不新增 `ValidateStage.error_signature`（没有 loopback 发生，无停滞可检测）。

### 2.3 验证

- 用例 1、2 通过（2.1）。
- 回归 `test_design_routing.py::TestAnchorLoopback`（anchor→tiling 边不受影响，仍走 corrective 循环）、`TestReviewBubbleUp`（general-design 边不受影响）。
- 回归 `verify.error_signature` 相关 UT 不受影响（该 stage 不在本次改动范围）。

---

## 改动 3 — P17：docgen 确定性 stage 标 `skip_reason`

### 3.1 测试先行（UT）

- 用例：`DocgenStage` 空 `actions` 时，框架不再发「no actions with no skip_reason」WARN（改发「deterministic_render」类信息，或不发 WARN）。

### 3.2 代码改动

- 文件：框架侧「空 actions 预警」处（runner / graph_executor 中产生该 WARN 的位置）。
- 确定性 stage（`DocgenStage`）声明 `skip_reason = "deterministic_render"`（类属性或 `actions` 返回时附带）；框架侧：有 `skip_reason` 时不发「possible bug」WARN。
- 精确改点待实施时定位（本 L4 先记方向，避免在不确认预警源时硬写）。

### 3.3 验证

- UT：确定性 stage 空动作不再触发误报 WARN。

---

## 改动 4 — P19：reviewer 去 `Bash`+`Glob`、加 `Write`（升级版，已实施）

> 配合 L3 §3.7。原方案「只移 Glob」实施前升级——移 Glob 但留 Bash 仍有 `find`/`ls` 探测口子，故连 Bash 一并去掉、加 `Write` 写报告（reviewer 原本无 Write、靠 Bash `cat >` 写）。

### 4.1 实际改动

- **agent manifest（`ascendc-design-reviewer`）**：`allowed_tools` 由 `Read/Edit/Bash/Glob/Grep/Skill/mcp__engine__resolve_ambiguity` 改为 `Read/Edit/Write/Grep/Skill/mcp__engine__resolve_ambiguity`——去 `Bash`+`Glob`（探测工具连根去掉）、加 `Write`（写报告）。
- **角色提示（同 agent.md 工作方式）**：第 2 点改「靶向读取——输入已物化为已知文件，直接 Read，勿全仓探测」；第 3 点「`Write` 仅写评审报告、不得重写设计产物（设计产物改动走 Edit）」；第 4 点「用 Write 写到约定报告文件」。
- **两 skill 输出约定**：`ascendc-op-design-validate` 与 `ascendc-op-general-design-review` 的 SKILL.md「## 输出」段由「用 Bash(`cat`)写」改为「用 Write 写」。
- **不改 stage 代码**：`_materialize_inputs` 已物化输入（F2），工具集瘦身即可。

### 4.2 测试

- **UT（已绿）**：`test_capabilities::TestProjectAgentManifests::test_design_reviewer_no_probe_tools_write_for_reports`——断言 `allowed_tools` 不含 `Bash`/`Glob`、含 `Read`/`Edit`/`Write`/`Grep`。
- **heavy_llm ST（用户确认后跑，已绿）**：`test_design_tui_selfclosure` 真实 design+review（4:53，4 用例）——reviewer 用 Write 写报告、不再 Bash/Glob 探测。

### 4.3 验证

- UT + heavy_llm ST 全绿；reviewer 写报告（Write）+ 就地修（Edit）能力不受影响。

---

## 改动 5 — P20：design_doc 角色重定位大修（已实施）

> 配合 L3 §3.8。原 P20 小修（仅 GV8-B 核 inherited_design_points）实施前升级为 §3.4 落地——经核实 `design_doc` 无下游代码消费者（codegen.requires 不含它）、是 docgen 确定性渲染的人类交付物，GV8-A/GV8-B 把判定落点绑在它身上是架构错位。大修把 GV8-A/GV8-B/GV5 全部脱离终稿、design_doc 降级。

### 5.1 实际改动

- **validate SKILL.md**：
  - GV8 整段从「产物→终稿保真」改为「产物自洽」（终稿由 docgen 确定性渲染、其保真归渲染器自检）。
  - **GV8-A**：落点从「核终稿 Kernel设计节函数」改为「核 `tiling_results.<tpl>.buffer_kernel` 产物函数清单完整」，`target=tiling`（不再是 docgen）。
  - **GV8-B**：改核 `tiling_results.<tpl>.<segment>.inherited_design_points`（按 `stage` 路由 segment；多模板任一命中即吸收，`unique_design_points` 是概设级不区分模板），删「核对终稿 `[继承自概设独有设计]` 标注字符串」路径，`target=tiling`。
  - **GV5**：标注「终稿格式归 docgen，pipeline(all) 不 blocking，仅 `--stage doc` 复核」；mapping 表 all 不含 GV5。
  - 输入说明：`design_doc.json` 从「待校验主体，必须」降为「人类可读交付物，可选」；`tiling_results.json` 升为核对主体。
- **tiling 三段 schema**：`tiling_split`/`tiling_buffer_kernel`/`tiling_precision_perf` 各段 example 加可选 `inherited_design_points: [{point_ref, section, note}]`（description 注明用途）。`point_ref` 键联 `unique_design_points[].section`。
- **tiling 三段 SKILL.md**：split=R7 / buffer_kernel=R8 / precision_perf=R4 吸收 `unique_design_points` 时除 markdown 留标注外，**回写结构化 `<segment>.inherited_design_points`**（无所属独有点 → 空数组）；各 self_check 加「回写 inherited_design_points」。
- **ValidateStage 代码**：`input_contract` 由 `requires=["design_doc"]` 改为 `requires=[design_spec, tiling_results, anchor_report, template_division, general_design]`、design_doc 降 optional；`_upstream_inputs` 物化产物、不物化 design_doc（reviewer 不核终稿；transition 仍读 `state.design_doc` 折叠 validation_report——那是 state 字段、非物化输入）。

### 5.2 测试

- **UT（已绿）**：`test_design_substages::TestValidateInputs`（input_contract 核产物/optional design_doc + _upstream_inputs 物化产物不含 design_doc）；`test_design_schemas::TestTilingInheritedDesignPoints`（三段 schema example 含 inherited_design_points + point_ref）。
- **heavy_llm ST（用户确认后跑，已绿）**：`test_design_tui_selfclosure` 真实 design+review 链路。
- **回归（已绿）**：`test_design_pipeline_e2e`（stub 编排含 ValidateStage 改动）；GV8-A/GV8-B N/A 语义不变；tiling schema 向后兼容（新字段可选）。

### 5.3 验证

- UT 1496 + 非 heavy ST 101 + heavy_llm ST 4 全绿；`design_doc` 不再是 validate 的 blocking 核对对象，GV8-A/B/GV5 落点全部归位产物。

---

## 改动 6 — P18：用户决策不修（方案删除）

> 配合 L3 §3.6。原「立方案待频率数据」升级为「主动删除」——用户决策：成本不抵收益。

### 6.1 决策

- 兜底 A 后 P18 仅剩 `redo_tiling` 合法回路、`max_corrective=3` 有上限、触发频率未知；选项 A（注入 `rule_results` + 产物指纹）需为每条 GV 规则维护「核对产物子集」映射，属过度设计。
- **不实施**：从方案删除。若未来 event_log 证实 `redo_tiling` 高频，再按原选项 A（`rule_results` + 产物指纹 + loopback 注入 + 规则-产物映射）立项——该实施清单已从本 L4 移除，需要时查 git 历史取回。

### 6.2 未做动作

- 不改代码、不动 schema、不加 `rule_results`。L1 P18 标「不修（主动删除方案）」。

---

## 回归与验收

- design 组全量 UT + ST（§3.2；heavy_llm 按 §3.11 用户确认）。
- 重放死锁场景（等价 UT）：validate 遇 GV8-A（target=docgen）时**直接 halt**（`is_terminal=True`），不再 loopback（兜底 A）；GV8-A 在 P13 修复后终稿有内容时本不触发。
- `test_design_routing.py::TestAnchorLoopback`/`TestReviewBubbleUp`/`TestValidateDocgenHalt` 不受影响。
- `verify.error_signature`/stagnation 机制不受影响（未触碰）。
- **P19 回归**：reviewer 去 Bash/Glob、加 Write 后，gd-review / validate 仍能完成就地 Edit + Write 写 `*_reviewed.json`/`blocking_status.json`（heavy_llm ST `test_design_tui_selfclosure` 验证）。
- **P20 回归**：GV8-A/GV8-B 脱终稿、落点改产物；GV8-B N/A 语义不变；tiling schema 向后兼容（`inherited_design_points` 可选）；design_doc 不再是 blocking 核对对象。
- **实际测试结果**：UT `tests/ut/` **1496 passed**；非 heavy_llm ST **101 passed**（design_pipeline_e2e 等）；heavy_llm ST（design_tui_selfclosure + skill_invocation，用户确认）**4 passed**；test_npu（@npu @slow 真机）**10 passed**。
- **heavy_llm 未覆盖**（用户决策不跑，§3.11 诚实记录）：testdesign_tui_selfclosure(2)、testdesign_skill_invocation(1)、smoke(2)、decision_transcript(2)——特性交付/合并前可补跑。
- 兜底 B（加载期可达性校验）仍留拍板；**P18 用户决策不修**（改动 6）。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | L4 立项：P13（_render_kernel_pseudocode 内化装载）、兜底 A（ValidateStage.error_signature 接入已有 stagnation）、P17（确定性 stage skip_reason）。TDD：每改动先测后码。兜底 B/P18/P19/角色重定位不在本 L4。 |
| 2026-07-03 | **改动 2 修订**：废弃 `ValidateStage.error_signature` 方案（违反 §1.2，见 L3 §3.2）。改为 `design_tree.py` 一行改动——`_DETAILED_DESIGN_TRANSITION_TABLE["validate"]["redo_doc"]` 由 `("docgen","corrective")` 改 `("__halt__","escalation")`。测试改为：转移表断言（改 `test_graph_executor.py` 现有一行）+ `GraphExecutor` 集成新用例（`test_design_routing.py`，仿 `TestHaltRouting` 写法）。`ValidateStage.resolve_condition` 不变。 |
| 2026-07-03 | **改动 4/5/6 实施完成**（原立方案，实施前 P19 升级 / P20 升级大修 / P18 改删除）：P19 reviewer 去 `Bash`+`Glob`、加 `Write` + 两 skill 输出约定 Bash→Write（UT `test_design_reviewer_no_probe_tools_write_for_reports`）；P20 大修 §3.4 落地（GV8-A/GV8-B 脱终稿改核产物、GV5 降级、tiling `inherited_design_points`+R7-8 回写、ValidateStage input_contract 改产物/design_doc 降 optional，UT `TestValidateInputs`+`TestTilingInheritedDesignPoints`）；P18 用户决策删除（不修）。heavy_llm ST 按 CLAUDE.md §3.11（本次新增）用户确认后跑。UT 1496 + 非 heavy ST 101 + heavy_llm 4 + test_npu 10 全绿。 |
