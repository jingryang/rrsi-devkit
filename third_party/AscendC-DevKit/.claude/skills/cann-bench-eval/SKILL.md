---
name: cann-bench-eval
description: |
  AscendC 自定义算子性能-only 评测：对已编译安装的算子，逐 case 测量自定义算子
  （PTA 交付通路，与 run-cases 同一调用入口）与 torch_npu 参考实现（golden entry
  在 NPU 张量上执行）的时延，聚合 kernel_mean / torch_npu_mean / geo_speedup /
  faster，落盘结构化 perf_result.json。只测性能——不做精度比对、不做官方评分、
  不控制任何流程路由。
  Use when: 性能测试、性能评测、latency 测量、kernel vs torch_npu 时延对比、
  geo_speedup、faster 用例统计、perf_result.json。
triggers:
  - 性能测试
  - 性能评测
  - performance-only
  - kernel vs torch_npu
  - geo_speedup
allowed-tools: Bash, Read, Write, Glob, Grep
---

# Pipeline 叶子 Skill：cann-bench-eval 性能-only 评测

## 定位

本 skill 是**性能-only** 测量单元：对一个已编译安装（OPP + Python 包）的 AscendC
自定义算子，逐 case 测量双侧时延并产出速度比统计，供精度调试收尾总结（或任何需要
性能证据的场景）消费。

**测量口径**（双侧同经 torch dispatch，保证可比）：
- **kernel_mean_us**：自定义算子经其 PTA 符号（`torch.ops.<ns>.<op>` 或 pybind
  绑定）调用的平均时延——与 run-cases 交付通路同一调用入口；
- **torch_npu_mean_us**：golden entry 在 NPU 张量上执行的平均时延——golden 以
  torch 算子书写时在 NPU 上即分发 torch_npu 内置算子，即主线参考实现时延；
- **speedup**（逐 case）= torch_npu_mean_us / kernel_mean_us（>1 表示 kernel 更快）。

**聚合口径**：
- `kernel_mean_us` / `torch_npu_mean_us`：逐 case 均值的算术平均；
- `geo_speedup`：逐 case speedup 的几何平均；
- `faster_cases` / `complete_cases`：kernel 更快的 case 数 / 双侧均有测量值的 case 数。

**职责边界（叶子，单次返回）**：
- ✅ 逐 case 双侧时延测量 + 聚合统计 + 落盘结构化 `perf_result.json`
- ❌ 不做精度比对（归 run-cases / KernelLaunch）
- ❌ 不做编译出包、官方评分、rounds / checkpoint 管理
- ❌ 不派 subagent、不控制循环/路由

## 输入参数（调用方注入或现场解析）

| 参数 | 必填 | 说明 |
|------|------|------|
| `op_name` | 是 | 算子名（snake_case） |
| `cases_csv_path` | 是 | 用例 CSV（cann-bench 约定列：operator, case_id, input_shape, dtype, attrs, value_range, note） |
| `golden_module_path` | 是 | golden 模块路径 |
| `golden.entry` | 是 | golden 函数入口名（cann-bench 用算子名；手写 fixture 用 `reference`） |
| `code_dir` | 是 | 算子源码目录（用于解析 PTA 符号） |
| `deploy_install_path` | 是 | 算子包安装根（含 `vendors/…/bin/set_env.bash`） |
| `deploy_python_path` | 否 | 算子 Python 包路径（PYTHONPATH 注入以注册 torch.ops 符号） |
| `deploy_ld_path` | 否 | LD_LIBRARY_PATH 追加值 |
| `device_id` | 否 | NPU 设备号（默认 0） |
| `output_dir` | 否 | 产物目录（perf_result.json 落此；baseline 场景为 `{debug_dir}/baseline/`） |
| `warmup` / `repeat` | 否 | 预热 / 计时次数（默认 10 / 50） |

## 执行流程

### Step 0：前置检查（必做）

任一失败即停止并如实报错（不降级、不造数）：

1. **算子包已编译安装**：`{deploy_install_path}/vendors/custom_ops/bin/set_env.bash` 存在。
2. **环境变量生效**（与 KernelLaunch 前置检查同源）：
   ```bash
   source {deploy_install_path}/vendors/custom_ops/bin/set_env.bash
   source ${ASCEND_HOME_PATH}/bin/setenv.bash        # 若 CANN 基础环境未设
   export PYTHONPATH={deploy_python_path}:$PYTHONPATH   # 注册 torch.ops 符号
   export LD_LIBRARY_PATH={deploy_ld_path}:$LD_LIBRARY_PATH  # 若注入了该值
   ```
3. **NPU 设备可用**：`npu-smi info -t health`，或确认 `--device` 对应设备存在。

### Step 1：解析 PTA callable 符号

从算子源码的 Python 绑定解析自定义算子的 PTA 调用符号（现场解析，脚本不猜）：
- grep `{code_dir}` 中 `TORCH_LIBRARY` / `m.def(` 注册 → 形如 `torch.ops.<ns>.<op_name>`；
- pybind 绑定 → 形如 `<package>.<function>`；
- 符号必须与 run-cases 交付通路实际调用的入口一致（同一份已安装实现）。

找不到 PTA 符号（如仅支持 KernelLaunch 直调的场景）→ verdict=no，如实记录原因，
**不得**改用其他入口冒充交付通路时延。

### Step 2：执行测量脚本

```bash
cd {output_dir}
python3 {skill_dir}/scripts/perf_eval.py \
    --cases-csv {cases_csv_path} \
    --golden-module {golden_module_path} \
    --golden-entry {golden.entry} \
    --callable-symbol {Step 1 解析的 PTA 符号} \
    --output perf_result.json \
    --device {device_id}
```

脚本行为（自包含，不 import 本仓其他 skill / 工程代码）：
- 输入生成与 KernelLaunch 测试脚本同约定（固定 seed、float32 载体 + `.to(目标
  dtype)`、NaN/Inf 哨兵处理）；
- 每 case 双侧 warmup + `torch.npu.Event` 设备侧计时，取 mean_us（附
  median/min/max/cv 供噪声诊断）；
- 单 case 某侧测量失败（如 golden 为纯 numpy 无法在 NPU 张量上执行）→ 该 case
  记 `kernel_error` / `ref_error`，其余 case 继续，不中断；
- 退出码：`0` = 至少一个 case 双侧完整；`1` = 无完整 case（verdict=no）；`2` =
  环境 / 符号 / golden 加载失败（stdout JSON 带 error）。

### Step 3：读取产物

`{output_dir}/perf_result.json`（结构化主体）：

```json
{
  "ok": true,
  "verdict": "measured",
  "kernel_mean_us": 12.34,
  "torch_npu_mean_us": 45.67,
  "geo_speedup": 3.70,
  "faster_cases": 8,
  "complete_cases": 10,
  "total_cases": 10,
  "per_case": [
    {
      "case_id": 1, "dtype": "float16", "shape": [1024],
      "kernel":     {"mean_us": 12.3, "median_us": 12.1, "min_us": 12.0,
                     "max_us": 13.0, "cv_pct": 2.1, "n": 50},
      "torch_npu":  {"mean_us": 45.6, "median_us": 45.5, "min_us": 45.0,
                     "max_us": 46.2, "cv_pct": 1.2, "n": 50},
      "speedup": 3.71, "faster": true,
      "kernel_error": null, "ref_error": null
    }
  ]
}
```

## 输出契约

- **文件**：`{output_dir}/perf_result.json`（机器可读主体，字段路径确定）。
- **消费方式**：上游（如 ascendc-precision-baseline 的 DONE 总结）从
  `kernel_mean_us` / `torch_npu_mean_us` / `geo_speedup` / `faster_cases` /
  `complete_cases` 确定性取数填 PERFORMANCE 段——**禁止从自由文本中找数字**。
- `verdict=no` 时 `reason` 字段给出失败原因，上游如实降级（PERFORMANCE verdict=no），
  不编造数字。

## 失败语义

| 场景 | 行为 |
|------|------|
| torch / torch_npu 不可导入 | 退出码 2，stdout JSON 带 error |
| PTA 符号无法解析 / golden 加载失败 | 退出码 2 |
| 单 case 某侧测量失败 | 该 case 记 error，其余继续；complete_cases < total_cases 如实可见 |
| 全部 case 无法完整测量 | verdict=no + reason，退出码 1 |
| dtype 不受当前 torch 支持（如 hifloat32 缺失） | 该 case kernel_error 记录，不静默降级 |
