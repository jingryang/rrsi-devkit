---
name: ascendc-precision-kernel-debug
description: |
  A5 precision_debug 闭环的 kernel_debug phase —— per-case kernel/tiling 层精度调试
  （修复当前 case 后批跑全量 KernelLaunch 验证，框架读 KL summary JSON 调和失败队列）。
  读 baseline 的 KernelLaunch 结果分析当前 case 失败模式，
  先调用 ascendc-sync-static-check 扫描同步缺陷，再调用 tiling_bounds_check.py 检查边界，
  随后在 kernel 中插 DumpTensor（desc 100-199 CopyIn / 200-299 非 VF 计算 / 300-399 CopyOut）
  二分定位中间数值错误，定位根因后修 kernel 并回验中间态正确。
  VF 黑盒约束：不得在 __simd_vf__ 函数体内插探针或修改 VF 代码，
  定位到 VF 输出错误时标 need_vf 交给 vf_test。
  框架 CompositeGroup 驱动，spawn 单次执行——读接力、写本 phase 产物、
  输出 RESULT 行即返回，不控制循环/路由。
triggers:
  - ascendc-precision-kernel-debug
  - A5 kernel debug phase
  - DumpTensor 二分定位
  - kernel 精度调试
  - per-case kernel 诊断
allowed-tools: Read, Write, Bash, Glob, Grep, Edit
---

# Pipeline 叶子 Skill：A5 Kernel Debug 精度调试（kernel_debug）

## 定位

本 skill 是 **precision-debug stage** A5 精度调试的**阶段2（kernel_debug）**执行单元。
读当前 case 的 KernelLaunch baseline 结果分析失败模式，
先执行静态扫描（同步检查 + tiling 边界检查），
再在 kernel 中插 DumpTensor 二分定位中间数值错误，定位根因后修 kernel 并回验。
**修复成功后就地批跑全量 KernelLaunch 验证**，
把 KL 结果写进本阶段产物，由框架读取 KL summary JSON 调和失败队列并推导路由。

**职责边界（叶子，单次返回）**：
- ✅ **Step 0：从 `{debug_dir}/checkpoint.json` 确认当前 case**（`failed_case_queue[current_case_index]`），本阶段只调试这一个 case
- ✅ 读 baseline 的 KernelLaunch + run-cases 结果，分析当前 case 失败模式
- ✅ **调用 `ascendc-sync-static-check` 扫描当前 kernel 代码的同步缺陷**（EnQue/DeQue 配对、SetFlag/WaitFlag、MTE2/MTE3 地址重叠、PipeBarrier、Mutex/TBuf、Scalar 流水）
- ✅ **调用 `tiling_bounds_check.py` 轻量脚本检查当前 case 的 tiling 边界/对齐/尾块**
- ✅ 据分析 + 静态扫描结果在 kernel 插 DumpTensor（desc 100-199 CopyIn / 200-299 非 VF 计算 / 300-399 CopyOut）
- ✅ KernelLaunch **仅重跑当前 case**（有探针；baseline 脚本无 `--case-id` 时用单 case wrapper），捕获 DumpTensor 输出
- ✅ 二分定位错误阶段（搬入错？非 VF 计算错？搬出错？）
- ✅ 定位根因 → 修 kernel → KernelLaunch 回验当前 case（确认中间态正确）→ `fixed`
- ✅ **`fixed` 后批跑全量 KernelLaunch**（`{debug_dir}/baseline/{op_name}_kernel_launch_test.py`，不跑 run-cases），在结果 JSON 写完整 `kl_result`；框架读 `result_{op_name}_summary.json` 调和失败队列（resolved/regressed/追加/advance）并推导路由（kl_all_pass→baseline / case_kl_fails→kernel_debug）
- ✅ VF 输入正确但输出错误 → `need_vf`
- ✅ VECTOR_ERROR crash → 转 `vector_error_debug`
- ✅ 在阶段结果中报告 `code_modified` 和验证证据；framework 创建可恢复 candidate commit
- ❌ **VF 黑盒约束**：不得在 `__simd_vf__` 内插 DumpTensor/printf；不得修改 `__simd_vf__` 代码
- ❌ **不跑 run-cases**：run-cases 权威双跑验收是 **baseline** 的职责；kernel_debug 的全量验证只跑 KernelLaunch
- ❌ **不**控制循环/路由（框架 transition 替做）
- ❌ **不**派下级 subagent

---

## 输入参数（由 Driver 注入）

| 参数 | 必填 | 说明 |
|------|------|------|
| `op_name` | 是 | 算子名（snake_case） |
| `debug_dir` | 是 | precision debug 产物/日志根目录 |
| `code_dir` | 是 | 算子源码目录（kernel 代码所在） |
| `dev_record_dir` | 否 | 开发记录目录（coding_index.md 等） |
| `current_case` | 是 | 当前 case 上下文（`case_id`、`shape`、`dtype`、`error_layer`、`max_diff_rc`、`max_diff_kl`） |
| `baseline_phase_json_path` | 否 | baseline 结果文件路径（默认 `{debug_dir}/baseline/baseline_result.json`） |
| `golden_module_path` | 是 | Golden 模块路径（golden.py 参考实现文件绝对路径，由 Driver 注入 `state.golden_path`） |
| `round` | 否 | `attempt_count`（Driver 循环计数） |
| `previous_error` | 否 | 上一轮失败结论（Driver 重试注入） |
| `deploy_install_path` | 否 | Per-op OPP 安装路径 |
| `deploy_python_path` | 否 | Per-op Python wheel 安装路径 |
| `deploy_ld_path` | 否 | LD_LIBRARY_PATH 追加值 |
| `build_command` | 否 | 编译出包+安装的统一 CLI 命令（Driver 注入） |

---

## 执行流程

### Step 0：确认当前 case（必做，单一事实来源）

当前调试的是哪个 case，**以 `{debug_dir}/checkpoint.json` 为准**：

```bash
python3 -c "
import json
cp = json.load(open('{debug_dir}/checkpoint.json'))
q = cp['failed_case_queue']
cur = q[cp.get('current_case_index', 0)]
print(json.dumps(cur, ensure_ascii=False, indent=2))
"
```

据此得到 `current_case`（`case_id` / `shape` / `dtype` / `error_layer` / `failure_type` / `max_diff_rc` / `max_diff_kl`），本阶段所有分析与回验**只针对这一个 case**。

> ⚠️ **警惕 checkpoint 残留干扰**：`checkpoint.json` 可能携带历史阶段的 `vector_error_evidence` / `active_error_fingerprint` / `pipeline_*` 等旧字段（如 A3 遗留、已 aborted 的轮次）。这些**不代表当前 case**，不得据此改变本阶段对 `failed_case_queue[current_case_index]` 的调试目标。若当前 case 的 KL 结果是数值错误（非 crash），即便 checkpoint 里有旧 vector 指纹，也不应直接判 VECTOR_ERROR——除非本次回验确实复现 crash。

### Step 1：分析当前 case 失败模式（原 diagnose 职责）

读 `{debug_dir}/baseline/baseline_result.json`（或 `baseline_phase_json_path`），提取 `rc_result` 与 `kl_result` 中**当前 case（Step 0 确认）**的结果，分析失败模式：

| 症状 | 失败模式分类 | 诊断方向 |
|------|-------------|---------|
| KL OOB crash (VECTOR_ERROR) | `vector_error` | 转 vector_error_debug |
| KL 输出 NaN/Inf | `numerical_overflow` | 检查除零 / 未初始化 / dtype 范围 |
| KL vs golden diff 极大（>1.0） | `systematic` | 检查计算逻辑 / dtype 转换 / tiling 公式 |
| KL diff 集中在边界 case | `boundary` | 检查 tiling 尾块 / 边界处理 |
| KL diff 仅在特定 dtype | `dtype_specific` | 检查 FP16/FP32/BF16 转换 / cast 精度 |
| KL diff 局部少数位置 | `localized` | 检查特定计算段的 mask / stride |
| KL diff 随机 | `random` | 检查未初始化变量 / 同步竞争 |

输出 `error_pattern`（`systematic` / `localized` / `random` / `huge` / `dtype_specific` / `none`）。

### Step 2：静态扫描（必做）

#### 2a. 同步静态检查

调用 `ascendc-sync-static-check` 扫描当前 kernel 代码，输出结构化 JSON 问题清单。覆盖：
- EnQue/DeQue 配对检查
- 手动 SetFlag/WaitFlag 配对检查
- MTE2/MTE3 地址重叠检查
- PipeBarrier 完备性
- Mutex 配对
- Scalar 流水竞争
- TBuf 无同步訪问

将扫描结果写入 `sync_check` 字段（问题清单 + 修复建议摘要）。

#### 2b. Tiling 边界检查

调用 `tiling_bounds_check.py`（`{debug_dir}/scripts/tiling_bounds_check.py`）。脚本 CLI 以 `--help` 为准，当前支持 `--op-dir` / `--case-json` / `--tiling-json` / `--dtype-size` / `--pretty`：

```bash
python3 {debug_dir}/scripts/tiling_bounds_check.py \
  --op-dir {code_dir} \
  --case-json '{"shape": [2, 128, 256, 256], "dtype": "bfloat16"}' \
  --dtype-size 2 \
  --pretty
```

- `--op-dir`：算子源码目录（kernel 代码所在，同 `{code_dir}`）。
- `--case-json`：当前 case 的主输入 shape 与 dtype（来自框架注入的 `current_case.shape` / `current_case.dtype`，shape 为 JSON 数组，dtype 为字符串如 `float16`/`float32`/`bfloat16`）。
- `--dtype-size`：元素字节数——`float16`/`bfloat16`→2、`float32`/`int32`/`uint32`→4、`float64`→8、`int8`/`uint8`→1。若拿不准按当前 case dtype 由上述映射确定。
- `--pretty`：人类可读 JSON 输出。

> 若脚本 CLI 与你记忆中的旧参数（`--code-path` / `--case-id` / `--shape` / `--dtype`）不符，以 `python3 {debug_dir}/scripts/tiling_bounds_check.py --help` 的当前输出为准——旧参数不存在，传了会 argparse 直接报错。

检查项：
- Main/Tail 分块边界对齐
- 尾块 mask 覆盖完整性
- strideK 与 oriK 一致性
- InitBuffer size 与 tiling 公式一致性
- 对齐要求（32B）满足性

将检查结果写入 `tiling_check` 字段。

### Step 3：插 DumpTensor 探针

据 Step 1 分析 + Step 2 扫描结果，在 kernel 中插 DumpTensor，**严格遵守 desc 编号规范**：

| desc 范围 | 阶段 | 说明 |
|-----------|------|------|
| 100-199 | CopyIn | 搬入后数据检查 |
| 200-299 | 非 VF 计算 | 非 `__simd_vf__` 的 Compute 段中间态 |
| 300-399 | CopyOut | 搬出前数据检查 |

**VF 黑盒约束（硬规则）**：
- **不得在 `__simd_vf__` 函数体内插任何 DumpTensor 或 printf**
- **不得修改 `__simd_vf__` 代码**
- DumpTensor 只能插在 CopyIn / 非 VF 的 Compute / CopyOut 段
- 定位到「VF 输入正确但 VF 输出错误」→ 标 `need_vf` 交给 vf_test

> **`need_vf` 交接契约（vf_test 的唯一输入，禁止只给一句话）**：标 `need_vf` 时必须把
> `vf_functions` 填成结构化数组（见返回格式），每项至少含：
> - `name`：出错 VF 在真实代码中的**原始函数名**（如 `CustomRegImpl::ReduceSumBinaryFold`，
>   须能在 `code_dir` 下 kernel 源文件按此名字直接定位；vf_test 会按它原样搬运实际函数体）
> - `function`：该 VF 的计算职责描述
> - `evidence`：VF 输入正确但输出错误的证据摘要（复用 dump_evidence 相关结论即可）
> - `dtype`：当前失败 case 的 dtype（从 Step 0 确认的 current_case 抄）
> - `input_shapes`：当前失败 case 的 shape 或该 VF 实际输入 UB shape
> - `failed_case_id`：当前失败 case 的 case_id
>
> dtype / input_shapes / failed_case_id 直接从 Step 0 确认的 current_case 抄，不另行推断。
> 缺字段会导致 vf_test 无法确定被测对象 → 返回 error_type=INP，白白浪费一轮。

### Step 3.5：KernelLaunch 前置检查（必做）

在调用 `KernelLaunch` 重跑当前 case 前，必须完成以下检查；任一失败即停止并报 `FAILED`（`error_type=ENV`）：

1. **重新 source 环境变量**：每次重新编译部署后，重新 source 算子包 set_env，确保 `ASCEND_OPP_PATH` 包含自定义算子 OPP 目录：
   ```bash
   source {deploy_install_path}/vendors/custom_ops/bin/set_env.bash
   ```
2. **ttk 可用**：
   ```bash
   python3 -m ttk info
   ```
3. **KernelLaunch 可导入**：在 `{debug_dir}/baseline/{op_name}_kernel_launch_test.py` 运行目录验证：
   ```bash
   cd {debug_dir}/baseline
   python3 -c "import sys; sys.path.insert(0, '.'); from KernelLaunch import KernelLauncher; print('KernelLaunch OK')"
   ```

> **关于 `KernelLaunch` 导入路径**：若第 3 步导入失败，说明 `KernelLaunch` 不在 `{debug_dir}/baseline/{op_name}_kernel_launch_test.py` 运行目录的 Python 路径上。典型解决办法：
> - 在运行脚本前设置 `PYTHONPATH=<KernelLaunch 父目录>:$PYTHONPATH`；
> - 或在 `{debug_dir}/baseline/{op_name}_kernel_launch_test.py` 头部加入 `sys.path.insert(0, "<KernelLaunch 父目录>")`。

> 详细说明与故障排查参见 `skills/ascendc-custom-op-precision/SKILL.md` 第2节，以及 `skills/ascendc-custom-op-precision/KernelLaunch/README.md`。

> **golden 来源（KernelLaunch 精度比较）**：本阶段 KernelLaunch 回验用的 golden 与
> baseline 同源，来自 Driver 注入的 `golden_module_path`（golden.py 参考实现文件）。
> 具体加载走 baseline 生成的 `{debug_dir}/baseline/{op_name}_kernel_launch_test.py`
> 内已写死的 `load_golden("{golden_module_path}", entry="{golden.entry}", input_type="{golden.input_type}")`
> 契约——`golden.entry` 为 golden 函数入口名（cann-bench 用算子名；手写 fixture 用 `reference`），
> `golden.input_type` 为 golden 期望输入类型（`numpy` 或 `torch`），均与 run-cases harness
> 完全一致。比较标准为 devkit `precision_compare.compare_outputs`（MERE/MARE + dtype-aware
> threshold，见 `skills/ascendc-custom-op-precision/KernelLaunch/golden_compare.py`）。
> **本阶段不重新生成/不重新加载 golden**——只复用 baseline 脚本（或从它改写的单 case wrapper）
> 重跑当前 case；若 baseline 脚本缺失或损坏，参照 `skills/ascendc-precision-baseline/SKILL.md`
> Step 1 用同一契约重新生成。

### Step 4：KernelLaunch 重跑 + DumpTensor 捕获

1. 确保 kernel 已重新编译部署：
   ```bash
   {build_command}
   ```
2. 用 KernelLaunch **只重跑当前 case（Step 0 确认的 case_id）**（有探针），捕获 DumpTensor 输出。

   baseline 生成的 `{op_name}_kernel_launch_test.py` **可能没有 `--case-id` 过滤参数**。若没有，**不要直接跑全量脚本**，改为在 `{debug_dir}/baseline/` 下写一个单 case wrapper（可复制 `run_case1.py` 之类的既有 wrapper，改 `case_id`），只构造当前 case 的输入、只 launch 一次：

   ```bash
   cd {debug_dir}/baseline
   python3 ./run_case{case_num}.py   # 单 case wrapper，内部只跑 current_case
   ```

   > wrapper 可从 baseline 脚本改造：解析 `cases.csv` → 过滤出 `current_case` → 走同一 `KernelLauncher` 逻辑，输出 `max_diff` / OOB 结果。

3. **调试期只重跑当前 case**（如直接 `python3 {op_name}_kernel_launch_test.py` 带
   `--case-id` 过滤或单 case wrapper）。全量 KernelLaunch 批跑只在 **Step 7
   （`fixed` 后）** 执行——调试过程中想确认"修复可能影响其他 case"时，只补充抽查
   当前 case 相邻 shape，不做全量（避免在探针还在时污染全量 summary）。

### Step 5：二分定位错误阶段

按 DumpTensor desc 顺序二分：
1. 先检查 100-199（CopyIn）→ 数据是否正确搬入
2. CopyIn 正确 → 检查 200-299（非 VF 计算中间态）→ 非 VF 计算是否正确
3. 非 VF 计算正确 + VF 输入正确 → 检查 300-399（CopyOut）→ 输出是否正确
4. 非 VF 计算正确 + VF 输入正确 + VF 输出错误 → `need_vf`

**二分法**：先插中间点，正确则向前推，错误则向后查，收敛到错误段。

### Step 6：修复 + 回验

定位到根因后：
1. 修 kernel 代码（不碰 `__simd_vf__`）
2. 重新编译部署 kernel
3. KernelLaunch **重跑当前 case（Step 0 确认的 case_id）**，**先清探针**（仅在需要时保留关键探针验证中间态）；仍走单 case wrapper，不跑全量
4. 中间态正确 → `debug_status = "fixed"` → 进入 Step 7 批跑全量 KernelLaunch

### Step 7：修复后全量 KernelLaunch 验证（`fixed` 必做）

`debug_status=fixed` 时，**必须**批跑全量 KernelLaunch 验证修复在全部 case 上成立。

1. **重新编译部署**（kernel_debug 修改了 kernel 源码，先执行 `{build_command}` 并确认成功结束）。
2. **前置检查**（同 Step 3.5）：source 算子包 set_env、`python3 -m ttk info`、`KernelLaunch` 可导入——任一失败即报 `FAILED`（`error_type=ENV`）。
3. **批跑全量**（复用 baseline 生成的脚本，不跑 run-cases）：
   ```bash
   cd {debug_dir}/baseline
   python3 ./{op_name}_kernel_launch_test.py
   ```
   > 脚本会自动把 per_case 全量结果写入 `{debug_dir}/baseline/result_{op_name}_summary.json`
   > （`{debug_dir}/baseline/{op_name}_kernel_launch_test.py` 生成时已内置 dump）。
   > **不要手工写 summary 文件**——它是脚本产物，由框架读取调和 `failed_case_queue`
   > （刷新 `max_diff_kl`、KL 已通过的 kernel 层 case 标 `resolved`、KL 失败的
   > `resolved` case 标回 `debugging`（regressed）、不在队列的失败 case 追加 `pending`）。
4. **解析 KL 结果**汇总成 `kl_result`（`pass`/`total`/`max_diff`/`failed_cases`）
   写进本阶段结果 JSON：
   - `passed`（bool）— 单 case 是否通过（所有 output 的 AND）
   - `mare` / `mere` / `max_diff`（float）— 用于 best_snapshot 比较
   - crash / 非零退出 → 标 `error_type=VECTOR_ERROR`（转 vector_error_debug）
5. **路由由框架推导**（框架读 KL summary，§1.13 权威，不以你转述为准）：
   - KL 全过 → `kl_all_pass` → 回 baseline 做权威双跑验收
   - KL 有任一失败 → `case_kl_fails` → 回 kernel_debug 修下一个失败 case
   - VECTOR_ERROR → `vector_error` → 转 vector_error_debug
   `new_failed_cases` 字段仅作**佐证**（框架交叉校验，不一致以 KL 实测为准并留痕），可留空。

---

## 返回格式

### 结构化产物落盘

`{debug_dir}/kernel-debug/kernel_debug_round_{round}_result.json`：

```json
{
  "phase": "kernel_debug",
  "debug_status": "fixed | need_vf | retry | exhausted",
  "conclusion": "{一段话总结本阶段定位与修复结论，如 'case_3 在 CopyIn 后的 padding 区读到未初始化 UB，根因是 tail 块 mask 未覆盖 padding，已修 kernel 并回验中间态正确'}",
  "is_vf_issue": true,
  "vf_functions": [
    {
      "name": "CustomRegImpl::ReduceSumBinaryFold",
      "function": "{该 VF 承担的计算职责描述，如 '对 xWin 窗口做 fp16->fp32 Cast + fp32 ReduceSum 累加，写 partialOut[0]'}",
      "evidence": "{DumpTensor/验证证据摘要：VF 输入正确但输出错误}",
      "dtype": "{当前失败 case 的 dtype 组合，如 fp16->fp16 或 输入 fp16 输出 fp32}",
      "input_shapes": "{当前失败 case 的 shape，如 2x32x64x64x64 或该 VF 的实际输入 UB shape [[512]]}",
      "failed_case_id": "{触发该 VF 错误的 case_id，如 case_1}"
    }
  ],
  "dump_evidence": "{DumpTensor 中间态证据摘要}",
  "code_modified": true,
  "fix_summary": "{根因分析 + 修复说明}",
  "error_type": "VECTOR_ERROR | PREC | (空)",
  "error_pattern": "systematic | localized | random | huge | dtype_specific | none",
  "sync_check": {
    "issues_found": 0,
    "issues": "[...]",
    "summary": "..."
  },
  "tiling_check": {
    "issues_found": 0,
    "issues": "[...]",
    "summary": "..."
  },
  "vector_error_evidence": {
    "case_id": "",
    "error_code": "",
    "fingerprint": "",
    "run_log": "",
    "stderr_excerpt": ""
  },
  "verification": {
    "case_id": 1,
    "before_max_diff_kl": 65506.017578125,
    "after_max_diff_kl": 0.0009765625,
    "after_mere_kl": 1.4e-07,
    "after_mare_kl": 0.0009718157,
    "after_mismatch_count": 4,
    "after_total_count": 1048576,
    "after_passed": true,
    "crash": null,
    "kl_log": "{debug_dir}/baseline/result_{op_name}_summary.json"
  },
  "kl_result": {
    "pass": 10,
    "total": 10,
    "max_diff": 0.0,
    "failed_cases": []
  },
  "new_failed_cases": []
}
```

> **`verification`（必填，KernelLaunch 回验结果）**：框架 transition 会把
> `verification.after_max_diff_kl` **回写**到 `failed_case_queue[current].max_diff_kl`，
> 使注入的「当前待处理 case」块的 `max_diff_kl` 反映最新 KL 测量而非 baseline 冻结值
> （§1.13 数据忠实：框架只转发你实测的值）。`before_*` 为修复前、`after_*` 为修复后/当前
> kernel 代码的实测值；`after_passed` 为回验单 case 是否通过。

> **`kl_result`（`debug_status=fixed` 时必填，Step 7 全量 KL 汇总）**：只填
> `pass`/`total`/`max_diff`/`failed_cases` 四个字段；per-case 明细由 KL 脚本自己
> dump 到 `result_{op_name}_summary.json`，框架读它调和队列与推导路由。队列的
> resolved / regressed / 追加 / index 推进全部由 framework 从 KL 实测推导
> （§8/§9 文件契约），你的 `new_failed_cases` 仅佐证，可留空。

> **`conclusion`（必填，一段话字符串）**：本阶段结论，框架会把它物化到跨阶段接力文件
> `{debug_dir}/conclusions.json`（`conclusions_path`），后续阶段 agent 开工前读它即可
> 看到流程中其他 agent 的结论。请用自然语言写一段话，覆盖：本阶段干了什么、发现了什么、
> 得出什么结论。

### 返回标记（机器可读标记必须英文/ASCII）

```markdown
## KERNEL_DEBUG_RESULT
status: PASSED|FAILED
debug_status: fixed|need_vf|retry|exhausted
current_case: {case_id}
is_vf_issue: true|false
code_modified: true|false
error_pattern: {error_pattern}
sync_issues: <count>
tiling_issues: <count>
output_paths:
  - {debug_dir}/kernel-debug/kernel_debug_round_{round}_result.json
error_info: ...（FAILED 时填）

## RETURN: status=COMPLETED, phase=kernel_debug, debug_status={fixed|need_vf|retry|exhausted}, code_modified={true|false}, error_type={...}
```

> **`## RETURN:` 行为强制完成信号（编排层路由判据之一）**：最后一行必须输出该
> 行，且 `status` / `phase` / `debug_status` 必须与 result JSON 一致。缺失或与
> result JSON 不一致会被编排层判为 agent 自报状态异常并**重试本 agent**。
>
> **语言硬要求**：`RESULT` 行、`## RETURN:` 行及其全部字段名（`status=` /
> `phase=` / `debug_status=` …）必须与模板**逐字英文/ASCII**，不得意译为中文
> （如 `状态=`）。编排层按固定英文字段名做确定性解析——字段名写成中文会令完成
> 信号解析失败/错位（历史实证：`状态=COMPLETED` 未被识别时，`debug_status=fixed`
> 中的 `status=fixed` 子串被误读为状态，整轮结果废弃并重派本 agent）。自然语言
> 说明文字（`conclusion` / `error_info` 等）可用中文，机器可读标记一律英文。

### Driver 状态机映射

| 返回 | 编排动作 |
|------|----------|
| `STATUS=COMPLETED, debug_status=fixed` + KL 全过 | → `baseline`（权威双跑验收：rc 与 kl 双双全过才 escalate:passed） |
| `STATUS=COMPLETED, debug_status=fixed` + KL 有失败 | → `kernel_debug`（队列已由框架 KL 调和：当前 case 通过标 resolved、失败追加/regressed；spawn reconcile 推进到下一个失败 case） |
| `STATUS=COMPLETED, debug_status=need_vf` | → `vf_test`（VF 隔离单测） |
| `STATUS=COMPLETED, error_type=VECTOR_ERROR` | → `vector_error_debug` |
| `STATUS=COMPLETED, debug_status=retry` | → 自循环（attempt_count++） |
| `STATUS=COMPLETED, debug_status=exhausted` | → `__case_advance__` |
| `STATUS=FAILED` | → 直接 escalate |

> **路由判据（fixed 后）**：`kl_all_pass` / `case_kl_fails` / `vector_error` 三态由
> 框架从 KL summary（`result_{op_name}_summary.json`）per_case 全量实测推导
> （§1.13 权威，不以你转述为准）。你在 RETURN 行只需报 `debug_status` 与
> `error_type`；队列维护与路由全部由框架完成。

---

## 参考文档

### KernelLaunch + DumpTensor 参考
- `skills/ascendc-custom-op-precision/SKILL.md` — KernelLaunch 高级用法（DumpTensor 插入、GetValue、多 dtype）、前置环境检查
- `skills/ascendc-custom-op-precision/KernelLaunch/README.md` — `KernelLauncher` 构造参数、`compile_mode`、OOB 检测、`kernel_meta` 说明
- `skills/ascendc-dumptensor/SKILL.md` — DumpTensor 调试方法（7步法）、desc 编号规范

### 静态扫描
- `skills/ascendc-sync-static-check/SKILL.md` — 核内同步缺陷 7 类静态检查（EnQue/DeQue、SetFlag/WaitFlag、MTE2/MTE3、PipeBarrier、Mutex、TBuf、Scalar 流水）

### 领域知识
- `skills/ascendc-dev-knowledge/SKILL.md` — AscendC API 查证（修 kernel 时确认 API 签名/dtype）
- `skills/ascendc-tips/SKILL.md` — 31 条编程陷阱

### 上下游阶段
- `skills/ascendc-precision-baseline/SKILL.md` — 上游阶段1，产出 baseline 交叉对比结果；KL 全过后的权威双跑验收目标
- `skills/ascendc-precision-vf-debug/SKILL.md` — VF 隔离单测（need_vf 时触发）
- `skills/ascendc-precision-vector-error-debug/SKILL.md` — VECTOR_ERROR crash 定位
