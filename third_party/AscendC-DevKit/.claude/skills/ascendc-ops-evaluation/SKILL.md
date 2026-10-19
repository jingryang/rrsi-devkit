---
name: ascendc-ops-evaluation
description: Build, deploy, and evaluate AscendC operators from ops-nn/cv/math/transformer repositories, omni-ops repositories, and cann-recipes-spatial-intelligence (RSI) repositories, comparing baseline vs evolved performance.
---

## What I do

Build ops repository operators using `build.sh` or `setup.py`, install to specified paths or current Python environment, generate PyBind bindings (when needed), run correctness verification and performance profiling, and compare baseline vs evolved versions.

Supports three repository types:
- **Standard ops repositories** (ops-nn/cv/math/transformer)
- **omni-ops repositories**
- **RSI (cann-recipes-spatial-intelligence) repositories** — 3DGS operators via whl package

## When to use me

Use this in the ops repository operator evolution optimization scenario, when you need to evaluate performance differences between the pre-optimization (baseline) and post-optimization (evolved) versions of an operator.

## Workflow

**Python environment**: Always use `.venv/bin/python3` instead of `python3` (unless .venv is not available).

**MANDATORY: Follow ALL steps below in order. Do NOT write your own evaluation scripts or skip any step.**

### Step 1: Build and install operator

#### Option A: Standard ops / omni-ops repository

Call `build_ops.py` to build and install the operator from the ops repository.

```bash
python3 skills/ascendc-ops-evaluation/scripts/build_ops.py \
    --repo-root {REPO_ROOT} \
    --op-name {custom_op_name} \
    --soc {soc} \
    --install-path {absolute_install_path}
```

**Important:** You must use an **absolute path** for `--install-path`. Relative paths will cause installation failures.

The script internally executes:
```bash
cd {REPO_ROOT}
rm -rf build/ build_out/
bash build.sh --pkg --vendor_name=custom --soc={soc} --ops={custom_op_name} -j$(nproc)
./build_out/cann-ops-*-custom-linux.*.run --install-path={install_path}
```

For omni-ops repositories (auto-detected), the script internally executes:
```bash
cd {REPO_ROOT}
rm -rf build/ build_out/ output/
bash build.sh -n "{op_name}" -c "{soc}"
# .run file found in output/ directory
./output/CANN-*.run --install-path={install_path}
```

You must build separately for baseline and evolved versions:
1. Build baseline first (original code in repository)
2. Apply modified code to the repository
3. Build evolved version to a different install path
4. Restore original code via `git checkout`

#### Option B: RSI (cann-recipes-spatial-intelligence) repository

Call `build_recipes.py` to build and install the operator from the RSI repository.

```bash
python3 skills/ascendc-ops-evaluation/scripts/build_recipes.py \
    --repo-root {REPO_ROOT} \
    --python-version {PY_VERSION}
```

Parameters:
- `--repo-root`: RSI repository root directory (absolute path)
- `--python-version`: Python version (e.g., 3.8), auto-detected if omitted

The script internally executes:
```bash
# 1. Build custom NPU operators
cd {REPO_ROOT}/ops/ascendc
bash build.sh --python={PY_VERSION}

# 2. Install whl package
pip install dist/*.whl --force-reinstall

# 3. Install Python dependencies
cd {REPO_ROOT}/algorithms/gaussian_splatting
pip install -r requirements.txt
```

You must build separately for baseline and evolved versions:
1. Build baseline first (original code in repository), whl is installed globally
2. Apply modified code to the repository
3. Build evolved version, whl is installed globally (overwrites baseline whl)
4. Restore original code via `git checkout`

**Note:** RSI uses `pip install` to the current Python environment, not `--install-path`. The baseline vs evolved comparison relies on subprocess isolation in `evaluate_ops_ext.py` to ensure each version is evaluated in a fresh Python process.

### Step 2: Generate PyBind

#### Standard ops / omni-ops repository

Run `generate_pybind.py` to generate PyBind bindings and install the whl.

```bash
python3 skills/ascendc-ops-evaluation/scripts/generate_pybind.py {op_name} \
    --work-dir {install_path_dir}
```

PyBind only needs to be generated **once** (the aclnn interfaces are the same for baseline and evolved).

**omni-ops exception**: For omni-ops repositories, skip this step entirely. omni-ops uses its own `torch_ops_extension` wheel with `EXEC_NPU_CMD_V1` + `dlopen()` mechanism. Ensure the wheel is pre-installed (`python3 -c "import omni_custom_ops"`).

#### RSI repository

Skip this step entirely. RSI operators are packaged as a Python wheel (`meta_gauss_render`) with built-in bindings. The whl is already installed in Step 1.

### Step 3: Evaluate correctness and performance

#### Standard ops / omni-ops repository

Use the original `evaluate_ops.py` (unchanged):

```bash
python3 skills/ascendc-ops-evaluation/scripts/evaluate_ops.py {op_name} \
    --baseline-path {baseline_install_path} \
    --evolved-path {evolved_install_path} \
    --reference-py {path_to_reference.py} \
    --custom-py {path_to_custom.py} \
    --device-id {device_id} \
    --task-type {vector|cube}
```

The script uses **subprocess isolation** to evaluate each version separately (CANN runtime cannot switch OPP libraries once loaded):
- Subprocess 1: `ASCEND_CUSTOM_OPP_PATH={baseline}/vendors/{vendor_subdir}` -> correctness + profiling
- Subprocess 2: `ASCEND_CUSTOM_OPP_PATH={evolved}/vendors/{vendor_subdir}` -> correctness + profiling

Options(`evaluate_ops.py`):
- `--device-id`: NPU device ID (default: 0)
- `--task-type`: Operator type for profiling analysis (`vector`, `cube`, `cv-mix`, `unknown`)
- `--output`: Path for evaluation results JSON (default: `evaluation_results.json` in evolved path)
- `--num-trials`: Number of profiling trials (default: 20)

#### RSI repository (or unified evaluation for all repo types)

Use the extended `evaluate_ops_ext.py` (new file, supports all repo types including RSI):

```bash
python3 skills/ascendc-ops-evaluation/scripts/evaluate_ops_ext.py {op_name} \
    --baseline-path {baseline_repo_root} \
    --evolved-path {evolved_repo_root} \
    --reference-py {path_to_reference.py} \
    --custom-py {path_to_custom.py} \
    --device-id {device_id} \
    --task-type {vector|cube} \
    --repo-type rsi
```

**RSI specific:** For RSI repositories, `--baseline-path` and `--evolved-path` should point to the repository root directories (used only for profiling output directory calculation). The actual operator is loaded from the globally installed `meta_gauss_render` package.

Options (`evaluate_ops_ext.py`):
- `--device-id`: NPU device ID (default: 0)
- `--task-type`: Operator type for profiling analysis (`vector`, `cube`, `cv-mix`, `unknown`)
- `--repo-type`: Repository type (`nn`, `cv`, `math`, `transformer`, `omni`, `rsi`). Empty string for auto-detection.
- `--output`: Path for evaluation results JSON (default: `evaluation_results.json` in evolved path)
- `--num-trials`: Number of profiling trials (default: 50)

### Step 4: Compare output

The script automatically merges profiling data from both versions and generates a comparison report `evaluation_results.json`.

## Output Format

`evaluation_results.json`:
```json
{
  "op_name": "ada_layer_norm",
  "repo_type": "nn",
  "soc": "ascend910b",
  "baseline": {
    "install_path": "output/.../baseline",
    "time_us": 456.5,
    "precision_passed": true,
    "profiling_dir": "output/.../baseline_profiling/",
    "pipeline": {"mte2_pct": 38.0, "vec_pct": 47.0, "scalar_pct": 12.0, "mte3_pct": 18.0},
    "bottleneck": "memory_bound"
  },
  "evolved": {
    "install_path": "output/.../evolved",
    "time_us": 233.8,
    "precision_passed": true,
    "profiling_dir": "output/.../evolved_profiling/",
    "pipeline": {"mte2_pct": 28.0, "vec_pct": 49.0, "scalar_pct": 8.0, "mte3_pct": 15.0},
    "bottleneck": "balanced"
  },
  "comparison": {
    "speedup": 1.95,
    "time_delta_us": -222.7,
    "bottleneck_change": "memory_bound -> balanced",
    "compilation_success": true,
    "precision_passed": true
  }
}
```

## Error Guide

- `ASCEND custom OPP directory not found`: Check that `--install-path` uses an absolute path (standard/omni only)
- Build failure: Check that `ASCEND_HOME_PATH` is set; check that `--ops=` operator name is correct
- Repository type auto-detection: Detected via `.run` filename keywords (`ops-nn`/`ops-cv`/`ops-math`) or `REPOSITORY_NAME` in `build.sh`. omni-ops detected via `-n`/`--op-name` flags in `build.sh` + `src/` directory presence. RSI detected via `ops/ascendc/build.sh` + `setup.py` presence.
- `Cannot switch OPP path at runtime`: The evaluate_ops.py script handles this via subprocess isolation; do not try to evaluate both versions in the same process

### RSI specific errors
- `RSI 构建需要 build_recipes.py，但未找到`: Ensure `build_recipes.py` is in the same `scripts/` directory as `build_ops.py`
- `ASCEND_OPP_PATH not set`: Execute `source /path/to/cann/set_env.sh` to set CANN environment
- `CANN version mismatch`: Requires CANN 8.2.RC1, check installed CANN version
- `torch version mismatch`: Requires torch==2.1.0 and torch_npu==2.1.0.post12
- `build.sh failed`: Check CANN environment and CMake installation
- `whl not found after build`: Check `ops/ascendc/dist/` directory
- `import meta_gauss_render failed`: Check whl installation and Python version compatibility

## build.sh Notes

**CRITICAL**: In docker+tmux environments, the ops repository's `build.sh` should be called directly (not via `source`), as it is designed to be run as a standalone script unlike the custom operator's `build.sh`.

## Directory Structure

After full evaluation (standard/omni):
```
output/{op_name}_ops_evo_{timestamp}/
├── baseline/                        # Baseline install directory
│   └── vendors/custom_nn/...       # standard ops repos
│   └── vendors/omni_custom_transformer/...  # omni-ops repos
├── evolved/                         # Evolved install directory
│   └── vendors/custom_nn/...       # standard ops repos
│   └── vendors/omni_custom_transformer/...  # omni-ops repos
├── baseline_profiling/              # Baseline profiling data
├── evolved_profiling/               # Evolved profiling data
└── evaluation_results.json          # Comparison report
```

After full evaluation (RSI):
```
output/{op_name}_ops_evo_{timestamp}/
├── baseline/                        # Baseline repo root (placeholder)
├── evolved/                         # Evolved repo root (placeholder)
├── baseline_profiling/              # Baseline profiling data
├── evolved_profiling/               # Evolved profiling data
└── evaluation_results.json          # Comparison report
```

## Forge framework (experimental, disabled by default)

实验性的 forge 测试框架已落地，作为未来评测后端的备选实现，**当前默认禁用**，不接通任何调用方。

### 涉及文件

```
scripts/
├── forge_run.py            # 统一入口（封装 resolver + evaluator）
├── forge_evaluator.py      # forge 评测执行器
└── forge_test_resolver.py  # 测试脚本解析器
config/
└── zsearch_op_filter_map.json  # 算子名映射表
```

### 启用方式

`forge_run.py` 入口默认禁用，直接调用会以 `exit=2` 退出并提示。强制启用需设置环境变量：

```bash
export ZSEARCH_FORGE_ENABLE=1
python3 skills/ascendc-ops-evaluation/scripts/forge_run.py \
    --op-name {custom_op_name} \
    --repo-root {REPO_ROOT} \
    --install-path {install_path} \
    --mode {build|accuracy|perf|both} \
    --output {output_path}
```