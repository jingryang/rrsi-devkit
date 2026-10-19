# L4 实施方案：用 ascendc-st-design 替换 DevKit test_design 三步

> 依据：`docs/plan/replace-test-design-with-ascendc-st-design/01-analysis.md`（L3 方案分析）
> 状态：已完成 ✅（as-built 偏差见 §10，PR-76 review 后全部收敛）

## 改动清单

### 1. 新建 `convert_to_param_def.py`

**文件**：`.claude/skills/ascendc-st-design/scripts/convert_to_param_def.py`

确定性转换脚本：从 `requirement.json` + `design_spec.json` → `03_参数定义.yaml`。

### 2. 新建 `AscendCSTDesignStage`

**文件**：`src/ascendc_devkit/orchestration/stages/ascendc_st_design.py`

单 AtomicStage，继承 `_DesignSubstage`，`agent_name="ascendc-design-generator"`，`name="ascendc-st-design"`。

### 3. 修改 `registry.py`

删除 `TestAnalyzeStage, TestCaseDesignStage, TestCaseGenStage` 导入，添加 `AscendCSTDesignStage` 导入。

### 4. 修改 `orchestration-config.json`

删除 3 条旧 skill 映射（test-analyze/test-casedesign/test-casegen），添加 `"ascendc-st-design": "ascendc-st-design"`。

### 5. 修改 `design_tree.py`

删除 `_TEST_DESIGN_TRANSITION_TABLE` + `build_test_design_group()`，新增 `build_ascendc_st_design_node()`。

### 6. 修改 `workflow.py`

`_design_root()` 替换调用；删除 `GenerateAscendCWorkflow` 和 `GenerateAscendCDevWorkflow` 的 `"test_design"` TRANSITION_TABLE 条目。

### 7. 修改 `design_substages.py`

删除 `_INPUT_FILENAMES` 中 `test_analysis`/`test_casedesign` 条目。

### 8. 删除旧代码

- `test_design_substages.py`
- `AIInfra-OP-testdesign-analyze-skill/`
- `AIInfra-OP-testdesign-generate-casedesign-skill/`
- `AIInfra-OP-testdesign-generate-case-skill/`

### 9. State 字段

`test_analysis`/`test_casedesign` 保留不删（兼容旧 snapshots）。

## 验证

1. `python -c "from ascendc_devkit.orchestration.registry import get_stage; get_stage('ascendc-st-design')"`
2. `pytest tests/ -x -q` 确认无 break

## as-built 回填（PR-76 review 后，§D7）

初版验证项 2「`pytest tests/ -x -q` 确认无 break」**并未真实通过**——PR-76 review
发现 UT `test_short_dtypes_raises_contract_error` 失败（dtype 契约校验被静默删成 zip
截断）。以下为实际偏差与收口记录：

| # | 偏差（review finding） | 根因 | 修复 |
|---|---|---|---|
| B1 | `convert_to_param_def.py` 静默永不执行 | `parents[6]` 定位仓库根错误（→ `/home/g00944280/code`），脚本路径恒不存在；且脚本在输入物化之前跑 | `parents[4]`；`actions()` 先 `_materialize_inputs` 再跑脚本；失败写 `user_feedback` 进 prompt；输出对齐 skill `design/03_参数定义.yaml` 约定；补 ST 回归 |
| B2 | UT 失败（dtype 契约） | `_flat_inputs` 用 `n=min` zip 静默截断，删了 §1.3 加载期校验 | 恢复校验（分组前统一），`_flat_inputs` 去 zip 截断；UT 18/18 |
| M1 | 耗竭 halt vs 文档「前逃 codegen_init」矛盾 | 继承 `_DesignSubstage.fail_strategy="halt"` | `fail_strategy="continue"`，前逃 codegen_init；ST 改区分断言；UT 守护 |
| M2 | SKILL.md 残留旧布局路径（`skills/...`、`operators/{op}/tests/st/`） | 从 cannbot-skills 迁移未清理 | 输出改 CWD 相对（`./design/` `./testcases/`），脚本调用 `<skill_dir>/scripts/` 约定，清 `</rewrite>` 残留 |
| M3 | 外部 cases 分支零测试 + 旧真实 LLM 守护未重建 | 删 9 个测试文件未补新守护 | 外部 cases 4 用例 + 双后端 skill 注入用例 + TUI 自闭环 heavy_llm 新建 |
| M5 | `_locate_csv` 靠 mtime 猜、扫子目录中间产物 | `rglob` + mtime 排序 | 精确文件名优先 + 仅 wd 根扫描，确定性优先级；4 回归用例 |

**测试基线**：修复后 `tests/ut/adapters/` + orchestration UT + PR 相关 ST 全绿
（2637 passed / 3 skipped / 3 deselected）；heavy_llm（TUI 自闭环 + skill 注入）
Anthropic 未配置时诚实 skip（§3.7/§3.11），待用户确认跑。
