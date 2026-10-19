# L4 实施方案 — diagnose 设计上下文注入（TDD）

> 对应 L3 冻结版方案 A。改哪个函数、什么顺序、怎么验证。

## 改动清单

### 改动 1（框架）：`_common_context` 注入 `design_paths`

`src/ascendc_devkit/orchestration/stages/precision_debug_substages.py` `_PrecisionDebugSubstage._common_context`：

- 新增模块级 helper `_design_paths(state) -> dict[str, str]`：读 `state._workspace.artifacts / "staging"` 下实际存在的文件，映射为 `{"design_spec": <path>, "tiling_strategy": <path>, "kernel_architecture": <path>}`（只含存在者；workspace 缺失 / staging 缺失 → `{}`）。
- ctx 增加 `"design_paths": _design_paths(state)`。

单一来源：staging 文件（codegen 同源，§2.5），不做任何复制。

### 改动 2（框架）：`DiagnoseSubstage._phase_prompt` 渲染

- 参数区：`design_paths` 非空时逐行注入 `- design_paths（设计产物，全局理解必读）: <name>=<path>`；为空时不渲染该段（TUI adapter / 无设计场景优雅降级）。
- 正文「全局理解」表述补设计层：理解顺序 = 设计意图（存在时）→ 实现 → golden；假设空间含「实现与设计偏差」方向。
- 结构断言一行：结构变化与设计一致或记录 `design_deviation`。

### 改动 3（skill）：`.claude/skills/ascendc-precision-diagnose/SKILL.md`

- 输入表加 `design_paths` 行（可选；通用语义，含 TUI 降级说明）。
- 第 0 步三层认知 + 「实现与设计偏差」假设方向。
- 输出节 `fix_code_log` 增加 `design_deviation` 说明。
- 实施纪律（就地实施 / Step 3 附近）加结构完备性断言。

§2.1/§2.6/§2.11/§2.12 红线：不写 staging 布局字面量（路径来自 prompt 参数）、不引算子名/编号、断言可判定、按内容类型描述设计产物。

### 改动 4（manifest）：`.claude/agents/ascendc-precision-diagnose.md`

- Input 表加 `design_paths` 行；Step 1 Read context 加「读设计产物（存在时）」；Step 3 实施纪律加结构断言一句。与 SKILL.md 同步但保持 manifest 级摘要粒度。

### 改动 5（schema）：`schema/precision_diagnose.json`

- `fix_code_log` fields 描述更新 + 新增 `fix_code_log.design_deviation` 字段条目（type object，可选：`{dimension, reason}` 数组或单对象——见 §不做清单：transition 不消费）。

## 不做清单（实施红线）

1. **`design_deviation` 不得成为 transition 校验点**——缺字段不拒收、不 retry、不路由；仅 run 外（eval/人工）消费。违反即退化成控模型结构（§1.14）。
2. **不加 upstream halt**：不给 `upstream_stage` 加 `design` 值、不加设计冲突 halt 分支（L3 方案 C 否决理由）。
3. **不复制设计产物**进 debug_artifacts_dir（单一来源 staging，§2.5）。
4. **不动 A5**（`precision_debug_a5.py` 及 A5 侧 agent/skill，产权边界）。
5. **不动 run_tests substage**（纯 Python 测量无认知需求）。
6. **不 inline 设计内容进 prompt**（只传路径，§2.8）。

## 验证（TDD，先红后绿）

新增 `tests/ut/orchestration/test_diagnose_design_context.py`：

1. `test_design_paths_from_staging`：workspace + staging 三文件齐 → ctx.design_paths 含三项映射。
2. `test_design_paths_partial`：staging 只有一份 → 只含该项。
3. `test_design_paths_empty_without_workspace`：无 `_workspace` → `{}`；prompt 不含设计参数段。
4. `test_design_paths_empty_without_staging`：有 workspace 无 staging → `{}`；prompt 不含设计参数段。
5. `test_prompt_renders_design_paths`：三文件齐 → prompt 含各路径与「全局理解必读」标注。
6. `test_prompt_has_three_layer_cognition`：prompt 含设计意图→实现→golden 的理解顺序与「实现与设计偏差」方向。
7. `test_prompt_has_structure_assertion`：prompt 含结构完备性断言（design_deviation 记录要求）。
8. `test_design_deviation_schema_field`：schema json 含 `fix_code_log.design_deviation` 条目。

既有回归：`tests/ut/orchestration/` 全量 + skill/agent 文档一致性无 UT（文档），跑全量 `tests/ut/`。

heavy_llm（真实 agent 读设计调试全流程）不在本次自动跑，§3.11 待用户决策；下一批跑自然对照（L3 §5）。

## as-built（2026-08-25）

- **改动 1**：`_DESIGN_STAGING_FILES` + `_design_paths(state)` 落 `precision_debug_substages.py`（`_control_path` 后）；`_common_context` 注入 `"design_paths"`。
- **改动 2**：`DiagnoseSubstage._phase_prompt`——`design_param_lines`（存在才渲染进参数区）+ `design_block`（三层认知 / 偏差假设方向 / golden 冲突规则 / 结构完备性断言，置于 product_block 后）；`design_paths` 为空时两段整体省略（`test_prompt_no_design_section_without_staging` 守护）。读写契约节的 fix_code_log 字段列表**未加** design_deviation——无设计场景下提该字段无意义，保持降级干净（断言只在 design_block 内出现）。
- **改动 3**：SKILL.md——输入表加 `design_paths` 可选行（通用语义：框架注入 / TUI 接力目录 / 工程根 / 都没有则不寻找）；第 0 步三层认知；新增「## 结构保真」节（维度值域 `tiling/pipeline/data-movement/precision-strategy`）；输出节 fix_code_log 加 design_deviation。未动 frontmatter description。
- **改动 4**：manifest——Input 加 `design_paths`；Step 2.1 三层认知 + 偏差方向；Step 3 加结构保真行。
- **改动 5**：schema `fix_code_log` 描述更新 + 新增 `fix_code_log.design_deviation`（type array，`{dimension, reason}`；描述显式声明「框架 transition 不校验、不路由、不拒收，禁止做成控制流判据」——不做清单 1 的文本锚）。
- **验证**：TDD 先红（ImportError）后绿；`test_diagnose_design_context.py` 10 passed；targeted precision 套件 185 passed；全量 `tests/ut --quick` **3611 passed / 3 deselected / 0 failed** 零回归。
- **ST（非 heavy_llm，§3.2/§3.6 默认范围）全绿**：主跑 `tests/st -m "not heavy_llm"` **117 passed**（修正后模型配置）；期间两处非本项目环境问题已定位排除——①旧配置弱模型致 LLM ST 零回合撞 180s 硬顶（`exceeded 180s hard cap, turn 0`，agent jsonl 实证 §1.11），用户换模型后全绿；②source 泛用 `ascend-toolkit/set_env.sh` 缺 `libhccl.so` 致 preflight 1 fail + 6 skip（torch_npu↔CANN 配套，记忆同源），改 source `cann-9.1.0-beta.3/set_env.sh` 后 preflight 3/3、npu+external 12/12 零 skip。heavy_llm 未跑（§3.11 待用户决策）；效果验证留下一批跑自然对照[rounds-to-fix/eval 性能分/design_deviation 频率]。
