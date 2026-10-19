# step-9 L4-b — 输入物化成文件 + skill 链文件接力修复（F2/F3）（2026-06-17）

> **实施状态（2026-06-17）：✅ 已实施并验证。**
> - 任务1（输入物化）：`_TestDesignSubstage` 加 `_materialize_inputs`（actions 内 spawn 前把上游 State
>   产品写成 CWD 的 `<name>.json`）+ 覆写 `_inputs_section` 返回 ""（不再 prompt 注入）。analyze 物化
>   design_spec/tiling_strategy/kernel_architecture/requirement；casedesign/casegen 物化各自上游。
> - 任务2（接力修复）：三个 SKILL.md 改为「从 CWD 读上游产物文件 + 写本步产物 + 软下一步提示」，
>   删 workflow_context.json/强制 /clear；并新增结构化交接契约（test_analysis.json / test_casedesign.json）。
> - 任务3（落点）：物化在 substage actions()、收集走 transition().parse()，未新增 runner 机制（已拍板）。
> - 验证：`test_test_design_materialize.py` 5 测 + e2e 8 测；全量 UT 1258 passed。
> - 偏差说明：generate-case 的脚本解析 markdown（非 JSON），故其接力输入是 casedesign 的
>   markdown 报告（共享目录文件接力），`test_casedesign.json` 是 DevKit 侧结构化摘要——已在
>   generate-case SKILL.md 注明，保留确定性脚本不改写（T2）。

> 层级：**L4 / 实施方案**。依据 `02-analysis.md`（T1/T2 反转横幅）+
> `../first-principle-tui-compat/02-analysis.md`（§M 调和模型、F2/F3 解法、收敛-3 接力文件形态）。
> 前置：L4-a（substage/group/schema/SKILL.md 契约已就位）。
>
> 范围：① 输入从「注入 prompt」改为「物化成 CWD 输入文件」（F2）；② 修复 skill 链文件接力使其
> 在 TUI 自闭环（F3）；③ 敲定开放点 1（外层物化/收集落点）。

## 已核实事实（开工前提）

1. **物化落点候选**：substage `actions()`（`design_substages.py:85`）已 build prompt + 备 working_dir,
   spawn 在 runner `_execute_spawn_agent`（`runner.py:376`）。⇒ 输入文件物化的自然落点 = **substage
   `actions()` 内、spawn 前**（与 prompt 构造同处,同一 working_dir）。
2. **收集回灌已有范式**：spawn 后 `_collect`（sdk_backend）扫 working_dir;`transition().parse()` 用
   `artifact_contract` 解析产物（`_parse_single`，`design_substages.py:276`）。
3. **回灌装载器先例**：`design_artifacts.py:design_artifacts_to_state` 从盘上产物重建 State 字段,
   每 substage 用自己的 `artifact_contract().parse()`,schema 单一来源。test_design 可仿建。
4. **现 prompt 注入点**：`_inputs_section`（`design_substages.py:216`）把上游产物 dump 进 prompt
   「## 上游输入」段——**这正是 F2 要替换的**。

---

## 任务 1 — 输入物化成 CWD 文件（F2，替换 prompt 注入）

### 1.1 substage 物化上游输入为文件（actions 内、spawn 前）

- `_TestDesignSubstage` 新增 `_materialize_inputs(state, working_dir)`：把本步 `input_contract.requires`
  的上游 State 字段,按 skill schema 约定的文件名写进**共享 working_dir**（L4-a 收敛-3 的共享目录）：
  - TestAnalyzeStage：写 `design_spec.json` / `tiling_strategy.json` / `kernel_architecture.json` /
    `requirement.json`（从 `state.design_spec` 等序列化）。
  - TestCaseDesignStage：上游 `test_analysis.json` 已由 analyze 写在共享目录（接力,见任务 2）,
    **无需重复物化**——这是「输出文件即下一步输入文件」的体现。
  - TestCaseGenStage：同理 `test_casedesign.json` 已在共享目录。
- `actions()` 改：先 `self._materialize_inputs(state, wd)` 再 spawn。
- **prompt 改瘦**：删 `_inputs_section` 的「## 上游输入」JSON 注入,改为一行指针「从当前工作目录读
  约定输入文件（见 skill 契约）」。`_operator_section`（算子身份,轻量）保留。

### 1.2 这不违反 §M 边界纪律（自检）

- 物化发生在 spawn **前**、写的是 skill **输入数据文件**(非 prompt 旁路、非控制流)——符合 M3「可做」。
- DevKit 不在时（TUI）：用户/上游 skill 自己把这些文件放进 CWD,skill 行为不变（M2）。

---

## 任务 2 — skill 链文件接力修复（F3，撤销 step-9 T2 初稿的「彻底剥离」）

> 核心:让 analyze→casedesign→casegen 在**共享 CWD**靠文件接力闭环,TUI 无框架也能跑通。

### 2.1 接力文件形态（收敛-3：输出文件即输入文件 + 极简 chain_context.json）

- **主接力 = 产物文件本身**：analyze 写 `test_analysis.json` → casedesign 直接读它;casedesign 写
  `test_casedesign.json` → casegen 读它。无需独立「接力棒」文件。
- **极简 `chain_context.json`（仅数据指针）**：放共享 CWD,记链级元信息——`{op_name, output_dir,
  produced: [test_analysis.json, ...]}`。**禁止**含「阶段完成标志/重试计数/门控状态」（控制流归外层,M4）。
  每个 skill 末尾追加自己的产物到 `produced`。

### 2.2 三个 SKILL.md 接力段改写（删坏的旧接力，写自洽新接力）

- **删除**（F3 + T2）：阶段1.0「检测读取 workflow_context.json」、阶段4.2/5.2「workflow_context.json
  已更新」、强制 `/clear` 硬指令、「请输入：执行 XX-skill」人机推进话术中的**框架假设**部分。
- **保留并修自洽**（F3）：
  - 输入：从 CWD 读上一 skill 的产物文件（analyze 读 design_spec.json 等;casedesign 读
    test_analysis.json;casegen 读 test_casedesign.json）。
  - 输出：写本步产物 + 追加 chain_context.json 的 produced。
  - **软下一步提示**（保留,改软）：末尾「下一步可运行 `/AIInfra-OP-testdesign-generate-casedesign-skill`
    （TUI）或由编排驱动（DevKit）」——TUI 人类据此推进,DevKit 忽略。删强制 `/clear`,改「如上下文紧张
    可自行清理」。

### 2.3 DevKit 外层沿用同一接力（M2）

- DevKit 驱动时:analyze substage 跑完,其 `test_analysis.json` 留在共享 CWD;casedesign substage
  spawn 时 working_dir 同目录,直接读到——**外层不另做注入,沿用 skill 自己的接力文件**。
- transition 收集:各 substage `transition` 用 `artifact_contract().parse()` 读本步产物进 State
  （供主链 verify 消费 + 可观测）。即「skill 接力跑链 + 外层顺带收集进 State」并行不悖。

---

## 任务 3 — 敲定开放点 1（外层物化/收集落点）

### 决策（已拍板）

- **物化输入**：在 **substage `actions()` 内、spawn 前**（任务 1.1）。理由:与 prompt 构造、working_dir
  准备同处,数据流向清晰;不污染 runner（runner 保持「执行 action」的纯粹,不懂领域产物）。
- **收集产物**：沿用现 `transition().parse()` + `_collect`,**不新增机制**。
- **回灌调试**：仿 `design_artifacts_to_state` 建 `test_design_artifacts_to_state`,从共享 CWD 的
  `test_analysis.json`/`test_casedesign.json`/CSV 重建 State,支持 `stage run --name test-casegen` 单步。
- **否决**「在 runner spawn 前后统一物化」：runner 不应懂领域 schema/字段映射,越层。

---

## 验证（先红后绿）

- 红测 `test_test_design_substages.py`：
  - `_materialize_inputs` 把三件套写成 CWD 文件;prompt 不再含「## 上游输入」JSON。
  - analyze 产物文件被 casedesign 的 working_dir 读到（接力,共享目录生效）。
  - chain_context.json 只含数据指针,无控制流字段（断言无 status/retry 键）。
- 红测 `test_testdesign_skill_relay.py`（skill 正文层）：三 SKILL.md 无 workflow_context.json 读写、
  无强制 /clear;有「从 CWD 读上游产物文件」+ 软下一步提示。
- 回灌：`test_design_artifacts_to_state` 从盘重建 State（仿 design 回灌测试）。
- 全量回归 + `test_test_design_e2e.py`（stub）链路打通。

## 与后续片交接

- **L4-c**：F4 资源自包含 + common-rules 悬空清理 + 知识库路径 `references/`。
- **L4-d**：§P9 真实注入守护（`@pytest.mark.llm`）+ 「TUI 自闭环」守护 + SKILL.md⇄schema lint +
  「接力文件无控制流字段」纳入守护。
