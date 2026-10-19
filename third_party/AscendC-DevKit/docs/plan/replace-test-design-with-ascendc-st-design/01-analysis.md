# 方案：用 ascendc-st-design 替换 DevKit test_design 三步

## Context

DevKit 当前 test_design 为三阶段 LLM 链（test-analyze → test-casedesign → test-casegen），存在问题：
1. 无测试分层（无 L0/L1/L2），无法区分门槛用例与全量覆盖
2. 约束推理完全依赖 LLM，无形式化约束求解器，覆盖质量不可控

`ascendc-st-design` skill（已从 cannbot-skills 迁移到 `.claude/skills/ascendc-st-design/`）提供：
- L0/L1/L2 三级测试分层（≤200 / 500~700 / ≤20）
- 确定性约束求解器（9 种约束类型，拓扑排序，锚点采样，逐层推导）
- 完整脚本链（6/8 步为 Python 脚本，非 LLM）

本方案将三阶段 CompositeGroup 替换为单一 AtomicStage，内部挂载 `ascendc-st-design` skill。

## 输入适配

`ascendc-st-design` 的 step 1-2 期望 ACLNN 接口文档（markdown），然后 LLM 提取参数定义。

DevKit 已有等价结构化数据：`requirement.json` + `design_spec.json`。

**方案：确定性转换脚本 `convert_to_param_def.py`**，从 JSON 生成 `03_参数定义.yaml`：

```
requirement.json + design_spec.json → convert_to_param_def.py → 03_参数定义.yaml
```

产出 `03_参数定义.yaml` 后，agent 从 step 3（`generate_test_factors.py`）开始执行。

## 改动清单

### 1. 新建 Stage 类

**文件**：`src/ascendc_devkit/orchestration/stages/ascendc_st_design.py`（新建）

继承 `_DesignSubstage`，注册为 `@register_stage`，`name = "ascendc-st-design"`。

- **agent_name**: `"ascendc-design-generator"`
- **input_contract**: `requires=["requirement", "design_spec"]`, `optional=["tiling_strategy", "cases_path", "last_error"]`
- **output_contract**: `provides=["test_cases", "test_design_report"]`
- **actions()**: 
  - `state.cases_path` 非空 → `NoOp(contract_satisfied=True)`
  - `state.cases_path` 为空 → 运行 `convert_to_param_def.py` → `SpawnAgent` 挂载 skill
- **transition()**: 
  - external cases: `load_cann_bench_cases()` → `test_cases=cases, cases_source="cannbench"`
  - LLM 路径: 从 CWD 定位 L0+L1 CSV → `list[TestCase]` → `test_cases=cases, test_design_report=path, cases_source="devkit"`
- **resolve_condition()**: 迭代耗尽且 `test_cases` 为空 → `"exhausted"`
- **prompt**: 指示 agent 从 step 3 开始，`03_参数定义.yaml` 已在 CWD，脚本用相对路径，输出到 CWD

**关键字段**（确保下游不 break）：
- `test_cases`: codegen 做 TDD、deploy smoke 取 `[0]`、precision_debug 跑 run-cases
- `cases_source`: `"cannbench"` / `"devkit"`，驱动 `CannbenchBackend.available()` 判定
- `test_design_report`: 人读报告路径

### 2. 新建转换脚本

**文件**：`.claude/skills/ascendc-st-design/scripts/convert_to_param_def.py`（新建）

纯 Python，无外部依赖。从 CWD 读 `requirement.json` + `design_spec.json`，写出 `03_参数定义.yaml`。

### 3. 修改 orchestration-config.json

- 添加 `"ascendc-st-design": "ascendc-st-design"` 到 `skills.stages`
- 删除 `"test-analyze"`, `"test-casedesign"`, `"test-casegen"` 三条旧映射

### 4. 修改 design_tree.py

- 删除 `_TEST_DESIGN_TRANSITION_TABLE`（行 250-254）
- 删除 `build_test_design_group()`（行 257-283）

### 5. 修改 workflow.py

- `_design_root()` 行 309-311：`build_test_design_group()` → `AtomicStage(get_stage("ascendc-st-design")())`
- 删除 `GenerateAscendCWorkflow.TRANSITION_TABLE` 的 `"test_design"` 键（行 394-401）
- 删除 `GenerateAscendCDevWorkflow.TRANSITION_TABLE` 的 `"test_design"` 键（行 554-556）
- `SelfEvolveOpWorkflow.TRANSITION_TABLE` 无 `test_design` 键，无需改动

### 6. 修改 _INPUT_FILENAMES (design_substages.py)

删除 `test_analysis` 和 `test_casedesign` 映射（旧三步中间产物，新 stage 不产出）

### 7. 修改 registry.py

- 删除 `TestAnalyzeStage, TestCaseDesignStage, TestCaseGenStage` 导入
- 添加 `AscendCSTDesignStage` 导入

### 8. 删除旧代码

- 删除 `src/ascendc_devkit/orchestration/stages/test_design_substages.py`
- 删除 `.claude/skills/AIInfra-OP-testdesign-analyze-skill/`
- 删除 `.claude/skills/AIInfra-OP-testdesign-generate-casedesign-skill/`
- 删除 `.claude/skills/AIInfra-OP-testdesign-generate-case-skill/`

### 9. State 字段清理

`kernel/state.py` 中 `test_analysis` 和 `test_casedesign` 字段仅旧三步使用，可保留（无副作用）或在后续 PR 清理。

## 影响分析

| 改动 | 影响范围 |
|------|---------|
| 新 Stage 类 | `self_evolve_op` / `generate_ascendc` / `generate_ascendc_dev` 三条 workflow |
| 删除 test_design_substages.py | `_TestDesignSubstage` 仅被旧三步使用，无其他消费者 |
| 删除旧 skills | 仅在 `STAGE_SKILL_MAP` 被引用，已删除映射 |
| TRANSITION_TABLE 删键 | 新 stage 是单 AtomicStage，`exhausted` → route=None → 线性前逃到 codegen_init |
| convert_to_param_def.py | 仅新 Stage 的 actions() 中调用 |

## 下游兼容性保证

| 下游消费者 | 依赖字段 | 新 stage 是否满足 |
|-----------|---------|:---:|
| codegen `_build_codegen_prompt` | `state.test_cases` | ✅ 通过 transition() 填充 |
| deploy smoke harness | `state.test_cases[0]` | ✅ |
| precision_debug run-cases | `state.test_cases` + `cases_source` | ✅ |
| CannbenchBackend selector | `cases_source == "cannbench"` | ✅ |
| cannbench_eval | 不直接读 test_cases（读自己 CSV） | ✅ N/A |
| Runner contract validation | `output_contract.provides` | ✅ `["test_cases", "test_design_report"]` |

## 行为变化

| 场景 | 旧行为 | 新行为 |
|------|--------|--------|
| external cases 存在 | 三步全 NoOp 跳过 | 单步 NoOp 跳过 |
| 无 external cases | 三个 LLM agent 串行 | 一个 LLM agent + 6 个确定性脚本 |
| 输出格式 | 单 13 列 CSV | L0/L1/L2 三级 CSV + coverage_report |
| 测试覆盖 | LLM 隐式推理 | L0 单因子 + L1 两两组合 + L2 异常 |
| test_design 耗竭 | GenerateAscendC→halt, SelfEvolve→前逃 | 统一前逃到 codegen_init |

## 验证

1. 运行现有 UT: `pytest tests/ -k "test_design"` 确认无残留引用
2. 运行 ST: `pytest tests/st/test_self_evolution_stages.py`
3. stub 模式验证拓扑: `ascendc-devkit run --workflow self_evolve_op --mode new --enable-stubbed`
4. skill TUI 自闭环: `cd /tmp && /ascendc-st-design`
