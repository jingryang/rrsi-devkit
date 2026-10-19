# 71 — regbase codegen manifest 兜底 symbol 修复（P98）实施方案

> 层级：**L4 / 实施方案**。回答「改哪个函数、什么顺序、怎么验证」。
> 问题事实见 `06-problems.md` [[P98]]；选项取舍见 `71-cannbench-smoke-symbol-drift-analysis.md`。

## 改动

### 1. 新增 `src/ascendc_devkit/domain/mdef_parse.py`（m.def 解析原语集中，§2.5）
- 从 cannbench_adapt 迁入（纯搬移，行为不变）：`_MDEF_RE`、`_PARAM_RE`、`_split_top_level`、`parse_mdef_params`、`_replace_param_name`、`rename_mdef_schema`。
- 新增 `parse_mdef_op_name(source) -> str | None`：从首个 `m.def("<name>(...")` 取 `(` 前末尾标识符（如 `npu_exp`）。

### 2. `src/ascendc_devkit/orchestration/stages/cannbench_adapt.py`
- 删本地 m.def 解析副本 → `from ascendc_devkit.domain.mdef_parse import parse_mdef_params, rename_mdef_schema`；删多余 `import re`。
- `align_schema_params`（依赖 op_spec）留本文件。
- 修正 cann-bench 适配指引 prompt：明确 `callable_target.symbol` 是 devkit deploy smoke 与 runner 的权威符号、须与 op_plugin `m.def` 实际注册名一致；wrapper 转发目标取 symbol 末段（真实注册名），**非** op_name；示例不再硬编码 `{OpName}=op_name`。

### 3. `src/ascendc_devkit/orchestration/stages/codegen.py`
- `_transition_regbase_s5` 兜底分支：调新增 `_resolve_registered_op_name(state, artifacts, op_name)` 取真实注册名构造 symbol（原盲拼 op_name）。
- 新增 `_resolve_registered_op_name`：查源顺序 = artifacts `op_plugin/<op>_plugin.cpp` → 任意 `op_plugin/*.cpp`（文件名 agent 决定不固定）→ 磁盘 `op_dir/op_plugin/<op>_plugin.cpp`；`parse_mdef_op_name` 解析；失败回退 op_name + warn（不静默）。

（Membase 路径已有 callable_target 缺失即 halt 校验，不受影响。）

## 验证

- **新 UT** `tests/ut/domain/test_mdef_parse.py`：`parse_mdef_op_name`（npu_exp / 多 m.def 取首 / 无 m.def / 无 `(` → None 等）+ 迁移函数回归。
- **新 UT** `tests/ut/orchestration/test_codegen_regbase_phases.py::TestS5CompileAndFinalize`：兜底从 artifacts op_plugin 解析 npu_exp；磁盘回退解析；无源回退 op_name（既有用例）。
- **回归**：`test_cannbench_adapt_schema.py`（P10 迁移后行为不变，import 改指 domain.mdef_parse + 修正过时 docstring）、`test_cannbench_eval.py`（P97 既有）。
- **结果**：`pytest tests/ut/orchestration tests/ut/domain` → **1589 passed**，0 回归。
- **e2e 复现（heavy_llm，待用户确认）**：exp 重跑 self-evolve 到 cannbench_adapt，确认 `torch.ops.cann_bench.npu_exp` resolved、smoke 通过。
