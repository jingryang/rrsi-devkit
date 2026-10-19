# db504b 同类一致性风险修复方案（HIGH + MEDIUM）

> 背景：复审 e9ed199e（db504b/P123）修的"requirement 信息流程不一致"是否有同类。
> 三路并行审计结论：**db504b 那个"字段恒 None 被 `or` 读死侧"的确切形态全仓只此一例，已删净**。
> 但同族（同一 fact 多表示 + 写读错位 / lossy 物化）残留 4 处。本方案覆盖 HIGH(#1) + MEDIUM(#2/#3/#4)。

---

## #1 HIGH — codegen 半修漏洞：staging/requirement.json 仍走 lossy asdict

### 现状（已实证）
- `CodegenStage._materialize_inputs`（`codegen.py:760`）用 `_json_text(state.requirement)` 写 `staging/requirement.json`；`_json_text`（`codegen.py:45-63`）内部 `asdict(Requirement)`。
- `Requirement` dataclass + `OperatorSpec` **不建模** `mutation_mode`/`math_formula`/`shape_formula`/输出 derivation，且结构 re-wrap 成 `{op_spec: {...}}`（非 flat）。
- codegen SKILL.md:64 声明该文件 = "**需求权威源**（IO/公式/约束）"；SKILL:197/276 in-place plugin 交付契约要读 `mutation_mode`。
- **对比**：db504b 的 M2 已给 general-design review gate 修好了——`_materialize_extra`（`design_substages.py:1279-1314`）用 `shutil.copyfile` 拷全量 on-disk `requirement.json`，canonical 路径缺失时 fallback 写 `_load_authoritative_requirement` 解析的完整 flat dict。codegen 是这个修复漏掉的第二个消费者。

### 后果
in-place 算子进 codegen，agent 读到的 requirement.json 无 `mutation_mode`/无公式 → 交付契约无从执行，静默失真无报错。这正是整个 P123 要守护的 codegen 保真度。

### 方案（照抄 review gate 的 reach-back，§2.5 单一通路）
1. **抽公共 helper**：`_load_authoritative_requirement`（现私有于 `design_substages.py:2017`）语义是"从 workspace artifacts 读权威 requirement.json"，与 stage 无关。上移到共享模块 `orchestration/design_artifacts.py`（已有的"读回物化产物"模块，职责吻合），`design_substages.py` 与 `codegen.py` 都从此导入。
   - 同时把 review gate 里"copyfile 全量 / fallback 写 flat dict"这段也抽成一个 `materialize_authoritative_requirement(state, dst) -> bool` helper，两个 stage 共用，避免复制第二份逻辑（§2.5 不留双通路）。
2. **改 codegen**：`_materialize_inputs` 中 `("requirement", "requirement.json")` 这一项**改为调用** `materialize_authoritative_requirement(state, wd / "requirement.json")`：
   - 成功（on-disk 权威文件可达或 flat dict 可写）→ 落全量文件。
   - 返回 False（无 `_workspace` / 文件不存在，如纯 UT 场景）→ **last-resort** 退回原 `_json_text(state.requirement)` asdict 路径，保证不回归、不静默丢文件（§1.2 宽容兜底做 last resort）。
3. **review gate 收敛**：`GeneralDesignReviewStage._materialize_extra` 改为调用同一 helper，删掉自己那份 copyfile/fallback 内联实现。

### 验证（TDD，§3.1）
- 新增 UT：codegen 场景带 `_workspace.artifacts/requirement/requirement.json`（含 `mutation_mode`/`math_formula`）→ 断言 staging 落的是**全量 flat 文件**（有 `mutation_mode`，非 `{op_spec:...}` wrap）。
- 改现有 UT `test_codegen_upstream_reuse.py::test_requirement_serializes_as_json_not_repr`（`:63`）：该用例无 `_workspace` → 现语义变为"验证 last-resort asdict 路径仍产出 dict"，断言不变但补注释说明这是兜底路径。
- review gate 现有 UT `test_design_review_proto_isolation.py::test_materialize_extra_copies_full_requirement_file` 应零改动通过（行为不变，只是实现收敛到 helper）。

---

## #2 MEDIUM — reconcile-by-name 漏掉"改名漂移"

### 现状（已实证）
- `_reconcile_param_types`（`design_substages.py:2058`）+ `_reconcile_inplace_outputs` 只按 **name 匹配**对齐 design_spec 到权威 requirement.json（docstring `:2075` 自陈"naming drift / requirement missing → untouched"）。
- design agent 若把 DYNAMIC 输入**改名**（`x1`→`x`）而非删字段/降级 param_type，则名字对不上 → `param_type` 永不恢复。
- 下游：codegen 有 `cannbench_adapt.rename_mdef_schema_if_needed`（`cannbench_adapt.py:190`）+ P10 warn（`codegen.py:1085`）部分兜底，但 **docgen OpDef `.ParamType(DYNAMIC)` 无兜底** → 出错签名。

### 后果
改名的 DYNAMIC 算子 docgen 生成非 `Tensor[]` 变长签名 / cann-bench 关键字调用绑定失败。属 db504b 同族（writer 按 name reconcile，reader 消费一个 writer 匹配不上的 name）。

### 方案（可观测优先，§1.3；不静默）
核心矛盾：requirement 与 design_spec 之间**没有稳定的跨表示对齐键**（name 会漂）。彻底"自动改名对齐"需要位置/语义推断，风险高（易误对齐）。按四把尺子取舍，选**可诊断兜底而非激进自动修**：
1. **加载期/reconcile 期告警（主修）**：在 `_reconcile_param_types` 后，对权威 requirement 里**存在但 design_spec 未命中**的 DYNAMIC/OPTIONAL 输入（按 count 或 param_type 集合比对），发 `Logger.warn`，明确报"design_spec 疑似改名了权威输入 `<name>`，param_type=`<X>` 未能对齐——docgen/cannbench 签名可能失真"。把今天静默的 name-drift 变成可观测信号。
2. **位置兜底对齐（次修，条件严格）**：仅当 design_spec 与 requirement 的 inputs **数量相等且仅个别 name 不同**时，按位置补齐缺失的 `param_type`（同 `runner.py` 的按位置语义）。数量不等/多个不匹配 → 不猜，只告警（§1.10 不用机制特征强行代理）。
3. 不做全局重命名回写（会污染 design agent 的合法命名意图）。

### 验证
- UT：requirement 有 DYNAMIC `x1`，design_spec 改名 `x` 且 count 相等 → 断言位置兜底补回 `param_type=DYNAMIC` + 发 warn。
- UT：count 不等（design 多一个 OPTIONAL）→ 断言**不**误对齐，只发 warn。

---

## #3 MEDIUM — harness 位置耦合无一致性自检

### 现状（已实证）
- `_validate_case_form`（`runner.py:44-72`）按下标 `test_cases.inputs[j] → op_spec.inputs[j]` 读 `param_type` 判 DYNAMIC。
- 两列表来自不同 writer（test_design 写 `state.test_cases` vs requirement 写 `requirement.op_spec`）、不同 on-disk 源。数量/顺序错位 → 读错 tensor 的 param_type → DYNAMIC 输入被当非 DYNAMIC 校验（拒合法 `[[...]]`）或反之。
- `_route` 修复只覆盖"op_spec.inputs 为空"，非空但**错位**仍裸奔。

### 方案（构造性自检，§2.9 本 stage 上下文可判、不越界）
在 `_validate_case_form` 按位置读 `op_spec.inputs[j]` **之前**，加一道 length 一致性前置检查：
- 若 `len(test_cases.inputs) != len(op_spec.inputs)` → 抛 `HarnessContractError`，明确报"test_cases 输入个数 `<m>` 与 op_spec 输入个数 `<n>` 不一致，按位置读 param_type 不可靠"。把静默错位变成确定性失败（§3.7 诚实报错 > 静默误判）。
- 这是 harness 本 stage 上下文（它同时持有两个列表），非越界查上游（§2.9 门不越界）。
- 不做"按 name 重排对齐"——test_cases 不一定带 name，且重排会掩盖真实的上游产物不一致（该由上游修）。

### 验证
- UT：test_cases 输入数 ≠ op_spec 输入数 → 断言抛 `HarnessContractError` 且消息含两个 count。
- UT：数量一致、DYNAMIC 正确按位置识别 → 现有行为不变（回归守护）。

---

## #4 MEDIUM — `op_dir` 双 writer 漂移风险（今日构造安全）

### 现状（已实证）
- `state.op_dir`（entry 写，`entry.py:107`）与 `op_identity.op_dir`（context 派生，`context.py:147/167`，`op_dir = Path(state.op_dir)`）。
- 兜底读序**正确**（`state.op_dir or state.op_identity.op_dir`，先读权威 top-level，与 db504b 相反）。今日构造一致：nested 永远从 top-level 派生。
- 风险纯属"未来若新增第二个独立 writer 改 `op_identity.op_dir` 而不同步 top-level"→ 兜底会静默取 stale top-level。

### 方案（不变式加载期守护，§1.3；轻改）
不改数据流（今日正确），只**固化不变式 + 加可观测**：
1. 在 `context.py` 构造 `OperatorIdentity` 处补注释，声明"`op_identity.op_dir` 必须派生自 `state.op_dir`，禁止独立 writer"（对齐 state.py 已有的 chip 派生说明风格）。
2. 加一个轻量一致性断言 UT（非运行期代码）：跑一个 entry→context 的状态流转，断言 `state.op_dir == state.op_identity.op_dir`，作为回归守护——未来谁加了第二 writer 会红。
- 不加运行期 assert（今日无 bug，运行期 assert 是噪音）；用测试守护不变式即可。

> 注：审计另发现两处**陈旧注释**（非 bug）——`state.py:168` 谎报 `requirement.test_cases` 是 fallback（实际无 reader 消费）；on-disk `design_spec.json` reconcile 后不回写。本方案**不含**这两项（纯文档/dormant），如需可另开小 PR，避免与本次正确性修复混淆。

---

## 实施顺序与总验证
1. #1（抽 helper + codegen/review gate 收敛）→ 2. #2（reconcile 告警+位置兜底）→ 3. #3（harness length 前置校验）→ 4. #4（不变式注释+守护 UT）。
- 每步先补/改 UT 再改实现（§3.1 TDD）。
- 全部完成后跑全量 UT（§3.6，前台，`pytest`），确认零回归（当前基线 3233 passed / 7 skipped）。
- heavy_llm 不在本次自动跑范围（§3.11）；#1/#2 涉及 design→codegen 真实链路，交付前是否跑一次 heavy_llm ST 由你在关键节点决策。
