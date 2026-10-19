# step-9 L4-a — 拆 substage + schema 迁 skill 目录 + SKILL.md 自带契约（2026-06-17）

> 层级：**L4 / 实施方案**。精确到改哪个函数、按什么顺序、每步怎么验证（TDD 先红后绿）。
> 决策依据见同目录 `02-analysis.md`（L3，T1/T3 + 第一准则横幅）+ `../first-principle-tui-compat/02-analysis.md`
> （L3 §M 调和模型 + F1 解法 + 收敛 1-3）。本片是 step-9 的结构地基,b/c/d 依赖它。
>
> 范围：① test_design 从 AtomicStage 拆成 CompositeGroup（3 substage，T3）；② testdesign 三 skill 的
> schema 从 DevKit 路径迁到 skill 目录 + SchemaLoader 改根（F1）；③ SKILL.md 自带 I/O 契约（F1）。
> **不含**：输入物化文件细节 / 接力修复（L4-b）、资源自包含 + 悬空清理（L4-c）、守护 ST（L4-d）。

## 实施状态（2026-06-17 更新）

- **任务 2（schema 迁 skill 目录）✅ 已实施并验证**：SchemaLoader 加 `load_spec_from_skill` /
  `load_contract_from_skill`（共用 `_build_spec`/`_read_schema_json`，不动旧签名）；三 substage 的
  schema 落各 skill `schema/*.json`；适配层 `_REQUIRED_COLUMNS` 改从 `testcase_csv.json` 同源读。
  adapter 全量 151 passed。
- **任务 1（拆 substage + group + 接入 + 删旧）✅ 已实施并验证**：分两步落地——
  - **1a（结构地基，无接入）**：3 substage 类（`test_design_substages.py`）、`build_test_design_group()`、
    STAGE_SKILL_MAP 增 3 行、§P4 校验泛化到任意 plugin、State 加 `test_analysis`/`test_casedesign`、
    10 新测。
  - **1b（切换拓扑 + 删旧）**：`_design_root` 加 `include_test_design`，full/dev 接 group、SE 不接；
    删旧 `TestDesignStage`（`test_design.py` 删除）+ registry/_PIPELINE/_DEV 列表清理；3 个受影响测试
    文件重写（workflow / review / stage 单测）；e2e stub 重写为 3-substage 驱动。
- **任务 3（SKILL.md 自带 I/O 契约）⏳ 未做**：移到与 L4-b/c 一起（同改 SKILL.md，避免反复改同文件）。

### 实施中发现并处理的事项（L4 配方原稿未预见，记录备查）

1. **generator agent 必须挂 stage-testdesign plugin**（02-analysis §T3-a 已预警的张力）：
   `ascendc-design-generator.md` 的 `plugins:` 原只有 `[stage-design, shared]`；不加 `stage-testdesign`
   则 `/stage-testdesign:<skill>` slash 触发落空 = §P9 skill-dead。已加，manifest validate 通过。
2. **§P4 一致性校验泛化**：`validate_skill_map` 原硬编码只校 `stage-design:*`，新 `stage-testdesign:*`
   会漏校。已改为按 `<plugin>:` 前缀分组、逐 plugin 校验（13 条全覆盖）。
3. **exhausted 安全链的精确机制**：旧单体 stage 的 resolve_condition 直接返回 `exhausted`，pipeline
   表 `test_design:{exhausted:__halt__}` 路由。拆 group 后必须让 `test-casegen` 的 `exhausted` 经
   group 的 `_TEST_DESIGN_TRANSITION_TABLE` 的 `__escalate__:exhausted` **冒泡**到 pipeline scope
   才触发 halt——否则末 substage 无路由会 `i+=1` 前进、把 test_cases=None 漏给 codegen。已加 escalate 边
   + casegen 的 resolve_condition（below-budget 返回 `default` 而非旧 `retry`，因 runner 已内部重试）。
4. **两处 linear stage 列表**：`_PIPELINE_STAGE_NAMES` 与 `_DEV_STAGE_NAMES` 都含 `test_design`，删旧
   stage 后两处都要去掉（否则 `get_stage("test_design")` KeyError）。
5. **顺带修复一个既有 test-isolation bug**：`test_runtime_config.py` 改 `STAGE_ITERATIONS` 后只重置为
   `{}` 不还原，污染后续文件的 config 相关用例（旧 review 测因 code_default 恰好等于配置值而被掩盖；
   新测 code_default=99 暴露之）。已加 autouse fixture 快照/还原 runtime_config 模块全局，根因修复。

**验证基线**：全量 UT 1232 passed（较 1a 后的 1231 再 +1，含新测与重写测净增）；test_design + design
stub ST 14 passed。无回归。


## 已核实事实（开工前提，全部对照源码）

1. **现状 test_design = 单 AtomicStage**：`workflow.py:283` 用 `AtomicStage(get_stage(n)())` 把
   `after_names` 里的 `test_design` 挂成扁平 stage；`test_design.py` 是单 `TestDesignStage`，
   `actions()` 一次 spawn `test-designer` agent 串调 3 skill（§P9 实测 skill-dead）。
2. **design group 范式可复用**：`design_tree.py:122/140 build_*_group()` 用
   `CompositeGroup(name, children=[AtomicStage(...)], transition_table, output_contract_override,
   max_corrective, max_escalations)`；substage 继承 `_DesignSubstage`（`design_substages.py:61`）。
3. **STAGE_SKILL_MAP 配置位**：`resources/orchestration-config.json` 的 `skills.stages`，loader
   `skill_config.py`；design substage `actions()` 用 `skills=[STAGE_SKILL_MAP.get(name)]` + `_with_trigger`
   首消息 slash（`design_substages.py:85-96`）。
4. **SchemaLoader 现状**：`adapters/schema/loader.py:_SCHEMAS_ROOT = resources/schemas`；
   `load_contract(stage, [filenames])` 从 `resources/schemas/<stage>/<file>.json` 读
   `{required, required_keys, description, example}`。**无 test_design 目录**。
5. **CSV 适配层**：`adapters/testdesign/csv_to_testcases.py:parse_testcase_csv`，13 列，
   `_REQUIRED_COLUMNS=(op_name, stc_inputs, stc_input_dtypes, ...)`，失败抛 ValueError。
6. **workflow 接入点**：`workflow.py:293 _PIPELINE_STAGE_NAMES` 含 test_design；`:335` test_design 的
   exhausted→halt transition；`:380 after_names=[test_design, codegen, ...]`。

---

## 任务 1 — 三个 test substage 类 + test-design CompositeGroup

### 1.1 新增 substage 类（`stages/test_design_substages.py`，仿 design_substages 范式）

- `class _TestDesignSubstage(_DesignSubstage)`：复用 design 基类的 `_with_trigger`/`_skill_trigger`/
  `_operator_section`/`_inputs_section`/`_parse_single`/可观测性（stage_name/branch_label）。
  覆写 `_working_dir`：**返回 group 共享目录**（不带 `<substage>` 子目录）——收敛-3 要求 test 链
  共享同一 CWD 让文件接力跑通（与 design 的 per-substage 隔离相反）。
  ```python
  def _working_dir(self, state):
      if not state._workspace:
          return None
      return state._workspace.artifacts / "test_design"   # 三 substage 共享
  ```
- `class TestAnalyzeStage(_TestDesignSubstage)`：`name="test-analyze"`，
  `agent_name="ascendc-design-generator"`（L4 §T3-a 复用 generator 角色），
  `prompt_intro="按测试分析方法学,从设计产物与需求产出结构化测试分析报告"`。
  `input_contract requires=[requirement, design_spec, tiling_strategy, kernel_architecture]`（T1）；
  `output_contract provides=["test_analysis"]`。
- `class TestCaseDesignStage(_TestDesignSubstage)`：`name="test-casedesign"`，requires=[test_analysis]，
  provides=["test_casedesign"]。
- `class TestCaseGenStage(_TestDesignSubstage)`：`name="test-casegen"`，requires=[test_casedesign]，
  provides=["test_cases", "test_design_report"]。transition 复用现 `TestDesignStage.transition` 的
  CSV 定位+`parse_testcase_csv`+report 定位逻辑（搬过来，定位改读本步物化产物）。
- 三个类的 `validate_inputs`：TestAnalyzeStage 加三件套内容级校验（T1 fail-fast，禁裸上下文）。

### 1.2 build group（`design_tree.py` 仿 build_*_group 加 `build_test_design_group()`）

```python
def build_test_design_group() -> CompositeGroup:
    from ascendc_devkit.orchestration.runtime_config import design_group_quota  # 复用配额机制
    children = [
        AtomicStage(TestAnalyzeStage()),
        AtomicStage(TestCaseDesignStage()),
        AtomicStage(TestCaseGenStage()),
    ]
    quota = design_group_quota("test_design_group")   # 在 orchestration-config 加该配额
    return CompositeGroup(
        name="test_design",                            # 组名沿用 test_design,主链命名不变
        children=children,
        transition_table=_TEST_DESIGN_TRANSITION_TABLE,  # 内部线性 + 末步失败 exhausted→halt
        output_contract_override=StageIOContract(
            provides=["test_cases", "test_design_report"]),
        max_corrective=quota["max_corrective"],
        max_escalations=quota["max_escalations"],
    )
```
- `_TEST_DESIGN_TRANSITION_TABLE`：内部 analyze→casedesign→casegen 线性；casegen 失败且配额耗尽
  → 复用现 `workflow.py:335` 的 exhausted→halt（不回退 design）。

### 1.3 workflow 接入改造（`workflow.py`）

- `_design_root`（:268）：`after_names` 里的 `test_design` 不再经 `AtomicStage(get_stage("test_design"))`
  挂载，改为挂 `build_test_design_group()`。需让 `_design_root` 支持「after 段中某名是 group」——
  仿 design group 的挂法（`before/after` 用扁平名，group 单独插）。具体：把 test_design 从 after_names
  移除，在 design group 与 codegen 之间显式插入 `build_test_design_group()`。
- `_PIPELINE_STAGE_NAMES`（:293）：test_design 作为 group 名保留（flat_stages 展开为 3 substage）。
- 删除旧 `@register_stage TestDesignStage`（`test_design.py`）——其职责拆进 3 substage。其
  transition 的 CSV/report 定位逻辑搬到 TestCaseGenStage。**CLAUDE.md「不留过渡层」：直接删,不留兼容。**

### 1.4 STAGE_SKILL_MAP 增三行（`resources/orchestration-config.json` skills.stages）

```json
"test-analyze":     "stage-testdesign:AIInfra-OP-testdesign-analyze-skill",
"test-casedesign":  "stage-testdesign:AIInfra-OP-testdesign-generate-casedesign-skill",
"test-casegen":     "stage-testdesign:AIInfra-OP-testdesign-generate-case-skill"
```
- §P4 一致性校验（`skill_config.py:validate`）扩到 stage-testdesign 插件（现只校 stage-design）。

### 验证（先红后绿）

- 红测 `tests/ut/orchestration/test_test_design_group.py`：group 拓扑含 3 substage 且线性；
  flat_stages 展开正确；STAGE_SKILL_MAP 三键解析到真实 skill；§P4 校验通过。
- 回归：现有 `test_test_design_e2e.py` / `test_workflow.py` 适配新结构（旧单 stage 测试改 group）。


---

## 任务 2 — testdesign schema 迁到 skill 目录 + SchemaLoader 改根（F1）

> 现状:design 的 schema 在 `resources/schemas/design/*.json`;test_design **尚无** schema 目录
> （现 CSV 适配层直接硬解析 13 列,无 schema 文件）。本任务为三 substage 建 schema,且**直接按第一准则
> 落到 skill 目录**（不走 `resources/schemas/` 弯路,避免建了又迁）。

### 2.1 为三 substage 产物建 schema 文件（直接放 skill 目录）

- `analyze-skill/schema/test_analysis.json`：`{required, required_keys, description, example}`，
  描述测试分析报告的结构化字段（特性/精度链/边界/泛化维度的 required_keys）。
- `generate-casedesign-skill/schema/test_casedesign.json`：用例设计方案结构。
- `generate-case-skill/schema/testcase_csv.json`：13 列 CSV 的列契约（列名 + 必填列 +
  repr-tuple 格式说明 + example 行），与 `csv_to_testcases.py:_REQUIRED_COLUMNS` 对齐——
  ⇒ 适配层与 skill schema **同源**（适配层改为从该 schema 读必填列,不再 Python 硬编码列名）。

### 2.2 SchemaLoader 支持「skill 目录根」（F1 核心改动）

- `adapters/schema/loader.py`：**新增** `load_spec_from_skill(plugin, skill, filename)` +
  `load_contract_from_skill(plugin, skill, filenames)`，从
  `.claude/plugins/<plugin>/skills/<skill>/schema/<filename>` 读 schema（新增 `_PLUGINS_ROOT` 常量；
  构造逻辑与 `load_spec` 同构，抽 `_build_spec(data, filename)` 私有函数共用，两公开方法各挂 `lru_cache`）。
  **不动** `load_spec`/`load_contract` 现签名（避免触动 design/requirement 现有 10 处调用方）。
- substage 的 `artifact_contract()`：`return SchemaLoader.load_contract_from_skill(
  "stage-testdesign", "<skill>", ["<file>.json"])`。
- **新旧两条根的并存是限时手段（CLAUDE.md 纪律二，强制收口）**：本片让 testdesign 走 skill-dir 根、
  design/requirement 暂留 `resources/schemas/` 旧根——这是过渡态，**不是长期并存**。收口承诺：
  **step-10 的 design 回溯必须删除 `resources/schemas/` 旧根 + `load_spec`/`load_contract` 旧方法 +
  `_SCHEMAS_ROOT` 常量，把全部 stage 收敛到唯一 `*_from_skill` 通路**（已登记进 step-10 收口项）。
  在旧根删除前，仅允许这一处受控并存，不得新增第二处走旧根的 testdesign 代码。
- design 阶段（step-8 已完成）的 `resources/schemas/design/*` **本片不动**，但其消亡是确定的
  （step-10 删旧根时一并迁移到各 design skill 目录）。

### 2.3 适配层与 schema 同源（消除 F1 在 CSV 侧的残留）

- `csv_to_testcases.py`：`_REQUIRED_COLUMNS` 改为从 `generate-case-skill/schema/testcase_csv.json`
  的 `required_keys` 读取（加载期一次),不再 Python 硬编码。保证「skill 拿到 TUI 用同一列契约」
  与「DevKit 适配层解析」同源。

### 验证

- 红测 `tests/ut/adapters/test_schema_loader_skilldir.py`：`load_spec_from_skill` 能从 skill 目录读
  schema;缺失抛 `SchemaNotFoundError`（沿用现行为）。
- 红测扩 `test_csv_to_testcases.py`：必填列来自 schema 文件、与 CSV 解析一致；改 schema 必填列
  → 适配层行为随动（证明同源）。

---

## 任务 3 — SKILL.md 自带 I/O 契约（F1 + 收敛-1）

> 目标:slash 注入 SKILL.md 时,契约一并到达 agent;TUI 里没有工程 prompt 渲染器也能拿到契约。

### 3.1 三个 SKILL.md 各加「## 输入 / ## 输出」契约段（人类可读，指向本目录 schema）

- analyze SKILL.md：
  - `## 输入`：从 CWD 读 `design_spec.json` / `tiling_strategy.json` / `kernel_architecture.json`
    （由上游 substage 或 DevKit 物化,或 TUI 用户放置）+ `requirement.json`。**删除**原「从两篇散文
    说明书/workflow_context.json 读」（F2/F3 在 L4-b 完成接力修复,本片先把契约写对）。
  - `## 输出`：产 `test_analysis.json`（指向 `schema/test_analysis.json`,复述 required_keys + example）
    + 接力文件（L4-b 定具体形态,本片占位）。
- casedesign SKILL.md：输入 `test_analysis.json`，输出 `test_casedesign.json`。
- generate-case SKILL.md：输入 `test_casedesign.json`，输出 13 列 CSV（指向 `schema/testcase_csv.json`）。

### 3.2 契约同源自检

- SKILL.md 的 required_keys 复述必须与本目录 `schema/*.json` 一致;L4-d 加一个 lint 守护
  （比对 SKILL.md 内联契约 ⇄ schema 文件,防漂移）。本片只写,守护在 d。

### 验证

- 红测 `tests/ut/skills/test_testdesign_skill_contract.py`：三 SKILL.md 含「## 输入/## 输出」段;
  其引用的 `schema/*.json` 在 skill 目录存在;required_keys 复述与 schema 文件一致。

---

## L4-a 实施顺序（先红后绿，逐任务回归）

1. 任务 2.2 SchemaLoader 加 skill-dir 能力（地基,无行为变更,纯新增）→ 绿。
2. 任务 2.1/2.3 建 testdesign schema 文件 + 适配层改读 schema → 绿 + 回归 CSV 测试。
3. 任务 1 拆 substage + group + workflow 接入 + STAGE_SKILL_MAP → 绿 + 回归 workflow/e2e。
4. 任务 3 SKILL.md 自带契约 → 绿。
5. 全量回归 `pytest tests/ut tests/st/test_test_design_e2e.py -q`。

> 不可逆性:全程无删数据;删 `TestDesignStage` 类是代码删除(可逆,git)。schema 新建在 skill 目录。
> Write/Edit 单次 <50 行/分块。

## 与后续片的交接

- **L4-b**（输入物化 + 接力修复 F2/F3）：填本片占位的「接力文件具体形态」+ DevKit 外层物化输入文件
  的落点（开放点 1：runner spawn 前后 vs stage actions/transition）。
- **L4-c**（资源自包含 + 悬空清理 F4）：common-rules 悬空引用处置 + 知识库路径改 `references/`。
- **L4-d**（守护 ST）：§P9 真实注入守护 + TUI 自闭环守护 + SKILL.md⇄schema lint。
