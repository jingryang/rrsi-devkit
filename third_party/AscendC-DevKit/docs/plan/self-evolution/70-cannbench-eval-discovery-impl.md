# 70 — e2e cann-bench 评测算子发现链路：A 实施（已做）+ B 根治方向 + C 待查

> 层级：**L4 / 实施方案**。回答「改哪个函数、什么顺序、怎么验证」。
> 问题事实见 `06-problems.md` [[P95]]/[[P96]]/[[P97]]；选项取舍见 `70-cannbench-eval-discovery-analysis.md`。

## A（[[P95]]）— 已实施（commit `6fec78c5`）

### 改动

**文件**：`src/ascendc_devkit/orchestration/stages/cannbench_eval.py`

1. **新增 `_resolve_cann_bench_pkg_root(source_dir, repo_root)`**（`@staticmethod`）：从 `source_dir` 向上探测含 `cann_bench/` 子目录的祖先，限 `repo_root` 内（不越界），返回 example 根（`Path`）或 `None`。
2. **PYTHONPATH 构造重构**（原双分支 f-string → 统一列表 `pypath_parts`）：`[_tn_usercustomize_dir]` + `per_op_python`（非空才加）+ `kernel_eval_src` + `cann_bench_pkg_root`（探测到才加）+ `existing_pypath`（非空才加）。消除原双分支重复，顺带修了「per_op_python 为空时 existing_pypath 重复拼接」的隐患。

### 验证

- **6 个 UT**（`tests/ut/orchestration/test_cannbench_eval.py::TestCannBenchPkgRootOnPythonpath`）：
  - helper 4 边界：正常向上探测命中 example 根 / 无 cann_bench 祖先 → None / `source_dir==repo_root` 无 cann_bench → None / source_dir 在 repo 外（即便祖先有 cann_bench/）→ None（不越界）
  - PYTHONPATH 2 契约：探测到 → 列表含包目录；探测不到 → 无空段、不含 cann_bench
- `pytest tests/ut/orchestration/test_cannbench_eval.py` → **10/10 passed**（4 既有 + 6 新增）。
- **端到端实证**：修复后 eval 子进程 `import cann_bench` 成功、`scan_interfaces` 发现算子接口（不再 ModuleNotFoundError），根因 A 根除。

## B（[[P96]]）— 根治方向（待实施）

**目标**：workflow 在新增算子后自动重建 `cann_bench/_C.abi3.so`，使新算子 op_plugin 进 `PLUGIN_TARGET`（`ALL_PLUGIN_SRCS`）被 scan 发现。

**候选落点**（待定，需设计权衡）：
- **cannbench_adapt stage 增「重建 _C」步骤**：adapt 改 glue（`__init__.py` wrapper + CMakeLists）后，调 cann-bench `build.sh` clean rebuild `_C`。需考虑：clean rebuild 耗时（~1min 实测）与磁盘、build.sh 调用方式（soc 自动检测 / `--soc`）、与 eval `--skip-install` 的衔接（_C 重建后 eval 扫新 _C）。
- **或 deploy/adapt 与 eval 之间加独立 rebuild stage**。

**前置确认**：adapt 现有 rebuild opp（`cannbench_adapt.py:261` `_align_mdef_schema`）与 `_C` rebuild 是否可合并——cann-bench `build.sh` 一次 `build_run.sh` 同时编 opp + `_C`（顶层 CMakeLists 同一 build 树），若 adapt 已在调 build.sh，则只需确保它 clean rebuild（而非增量）即可顺带重建 `_C`。

**手动 workaround（当前可用）**：`rm -rf build_py && bash build.sh`（已实证 exp 进 `_C`、`torch.ops.cann_bench.exp` MISSING→EXISTS）。

## C（[[P97]]）— 待查

scan 发现 exp 但 `operators:[]`。下一步：读 cann-bench `kernel_eval/data/package_manager.py` 的 `scan_interfaces` → evaluator `operators` 纳入逻辑，定位匹配失配点。待查方向：
- `--operator Exp` 过滤 + tasks（`tasks/level1/exp/`）用例匹配逻辑；
- scan 第 2 路（`torch.ops.cann_bench`）发现的接口与 `__init__.py` wrapper 的关系——是否需 wrapper 才被认作可用接口（adapt 没跑、exp 无 wrapper）。

不阻塞 A/B 固化。
