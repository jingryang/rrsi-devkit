# 72 — deploy install_python pip 覆盖修复（P99）实施方案

> 层级：**L4 / 实施方案**。回答「改哪个函数、什么顺序、怎么验证」。
> 问题事实见 `06-problems.md` [[P99]]；选项见 `72-cannbench-redeploy-overwrite-analysis.md`。

## 改动

### `src/ascendc_devkit/orchestration/stages/deploy.py`
`_run_command` 的 install_python 分支（原只清 `__pycache__`）：改为 pip install 前**清空 `per_op_python_dir` 全部内容**——`iterdir()` 遍历，目录 `shutil.rmtree(ignore_errors=True)`、文件 `unlink(missing_ok=True)`。让新 whl 干净覆盖（不再残留旧 `__init__.py`）。`per_op_python_dir` 是 per-op 隔离 whl target dir（`_per_op_path`），清空安全。

## 验证

- **新 UT** `tests/ut/orchestration/test_deploy.py::TestInstallPythonReinstallOverwrite`（3 例）：
  - 清旧包：install_python 前置旧 `cann_bench/` + dist-info → 执行后全清（pip 干净覆盖的前提）。
  - 非 install_python（build）不清 per_op_python（保留）。
  - `per_op_python_dir` 不存在（首次 install）不崩。
- **回归**：`pytest tests/ut/orchestration tests/ut/domain` → **1592 passed**，0 退化。
- **e2e 复现（heavy，待用户确认）**：P98 修复后 rerun cannbench_adapt，确认 per-op `__init__.py` 被新 whl 覆盖（含 exp wrapper，mtime 更新）、eval `operators` 非空、算子被调起。
