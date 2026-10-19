---
name: ascendc-precision-baseline
description: |
  A5 precision_debug 闭环的 baseline phase —— 双工具全量基线验证。
  首跑生成 KernelLaunch 测试脚本，随后 run-cases + KernelLaunch 双跑全量，
  逐 case 交叉对比隔离问题层（kernel/tiling vs op_plugin/aclnn），
  构建 failed_case_queue 并标注 error_layer。
  rc 与 kl 双工具全 pass 才判定精度交付通过、流程结束；
  性能测量 / DONE 总结同样只在双工具全 pass 时执行。
  框架 CompositeGroup 驱动，spawn 单次执行——读接力、写本 phase 产物、
  输出 RESULT 行即返回，不控制循环/路由（框架 BaselineSubstage.transition 替你做）。
triggers:
  - ascendc-precision-baseline
  - A5 baseline phase
  - 双工具基线
  - run-cases KernelLaunch 交叉对比
  - failed_case_queue 构建
allowed-tools: Read, Write, Bash, Glob, Grep, Edit
---

# Pipeline 叶子 Skill：A5 Baseline 双工具全量基线（baseline）

## 定位

本 skill 是 **precision-debug stage** A5 精度调试的**阶段1（baseline）**执行单元。
在 precision_debug 入口首次调用时，用 run-cases（交付通路）+ KernelLaunch（kernel 直测）
双跑全量，建立交叉对比基线，构建 `failed_case_queue` 并标注每 case 的归属层。

**职责边界（叶子，单次返回）**：
- ✅ 首跑生成 KernelLaunch 全量测试脚本（`{op_name}_kernel_launch_test.py`）
- ✅ 执行 `ascendc-devkit run-cases` 全量
- ✅ 执行 KernelLaunch 全量测试
- ✅ 逐 case 交叉对比，标 `error_layer`（`op_plugin` / `kernel`）
- ✅ 在 `baseline_result.json.cross_compare` 输出 queue 所需的逐 case 分类
- ✅ 输出完整 `rc_result` / `kl_result`，由 framework 刷新 `best_snapshot`
- ✅ run-cases **且** KernelLaunch **双工具全 pass** → 输出 `all_pass`（精度交付通过，流程结束）
- ✅ **rc 与 kl 双工具全 pass → 执行性能测量（cann-bench-eval，性能-only）并输出
  DONE 总结**（DONE / ACCURACY / PERFORMANCE / FINAL / SELF_ASSESSMENT，见 Step 6）
- ❌ **不**控制循环/路由（框架 transition 替做）
- ❌ **不**派下级 subagent

**工具依赖**：
- `ascendc-devkit run-cases`（交付通路全量执行）
- `ascendc-custom-op-precision`（KernelLaunch 脚本生成 + 上板执行，Read 其 SKILL.md 作为参考，不 invoke）
- `references/run-cases-result-json.md`（本 skill 目录内；run-cases result.json 解析逻辑：结构 / 失败权威判据 / failure_type 症状分类，Step 2/4 按需 Read）
- `cann-bench-eval`（**性能-only** 测量：kernel vs torch_npu 逐 case 时延，Read 其
  SKILL.md 作为方法参考，不 invoke——仅在 Step 6 双工具全 pass 时使用）

---

## 输入参数（由 Driver 注入）

| 参数 | 必填 | 说明 |
|------|------|------|
| `op_name` | 是 | 算子名（snake_case） |
| `debug_dir` | 是 | precision debug 产物/日志根目录 |
| `code_dir` | 是 | 算子源码目录 |
| `dev_record_dir` | 否 | 开发记录目录（coding_index.md 等） |
| `golden_module_path` | 是 | Golden 模块路径（用于 KernelLaunch 脚本生成时构造期望值） |
| `cases_csv_path` | 是 | 用例 CSV 路径（全量 case 列表） |
| `golden.entry` | 是 | golden 函数入口名（cann-bench 用算子名，如 `exp`；手写 fixture 用 `reference`） |
| `golden.input_type` | 是 | golden 函数期望的输入类型：`numpy` 或 `torch`（与 run-cases harness 的 `golden_input_type` 严格一致） |
| `deploy_install_path` | 否 | Per-op OPP 安装路径，由 Driver 透传 |
| `deploy_python_path` | 否 | Per-op Python wheel 安装路径 |
| `deploy_ld_path` | 否 | LD_LIBRARY_PATH 追加值 |
| `build_command` | 是 | 编译出包+安装的统一 CLI 命令（Driver 注入） |

---

## 执行流程

### Step 0：KernelLaunch 使用前置检查（必做）

在每次调用 `KernelLaunch` / 运行 `{op_name}_kernel_launch_test.py` 前，必须按顺序完成以下检查；任一失败即停止并报 `FAILED`（`error_type=ENV`）：

1. **算子包编译安装**：执行 `{build_command}` 完成编译安装，并确认成功结束；`{deploy_install_path}` 下存在 `vendors/custom_ops/bin/set_env.bash`。
2. **环境变量生效**：source 算子包 set_env，确保 `ASCEND_OPP_PATH` 包含自定义算子 OPP 目录（KernelLaunch 通过 `binary_kernel_match` 在该路径查找合法的 `.o` 文件）：
   ```bash
   source {deploy_install_path}/vendors/custom_ops/bin/set_env.bash
   ```
3. **CANN 基础环境已设置**：若尚未设置，先执行 `source ${ASCEND_HOME_PATH}/bin/setenv.bash`。
4. **ttk 可用**：
   ```bash
   python3 -m ttk info
   ```
5. **KernelLaunch 可导入**（在脚本运行目录验证 `KernelLaunch` 能正常导入，符号与 `run_exp_with_cannbench.py` 一致）：
   ```bash
   cd {debug_dir}/baseline
   python3 -c "import sys; sys.path.insert(0, '.'); from KernelLaunch import KernelLauncher, load_golden, load_cases, setup_log_separation; print('KernelLaunch OK')"
   ```
6. **NPU 设备可用**（上板时）：
   ```bash
   npu-smi info -t health
   ```
   或至少确认 `--device_id` 对应设备存在。

> **关于 `KernelLaunch` 导入路径**：若第 5 步导入失败，说明 `KernelLaunch` 不在脚本运行目录的 Python 路径上。典型解决办法：
> - 在运行脚本前设置 `PYTHONPATH=<KernelLaunch 父目录>:$PYTHONPATH`；
> - 或在生成脚本时加入 `sys.path.insert(0, "<KernelLaunch 父目录>")`。

> 详细说明与故障排查参见 `skills/ascendc-custom-op-precision/KernelLaunch/examples/run_exp_with_cannbench.py`（权威模板）和 `skills/ascendc-custom-op-precision/KernelLaunch/golden_compare.py`（`load_golden`/`load_cases`/`compare_outputs` 实现）。

### Step 1：首跑生成 KernelLaunch 测试脚本

> **核心原则：KernelLaunch 侧必须与 run-cases 使用同一套 golden 与同一套精度比较标准。**
> run-cases 通过 harness 的 `golden_contract`（`entry` + `input_type`）加载 golden.py，并用 devkit
> `precision_compare.compare_outputs`（MERE/MARE + dtype-aware threshold）做比较。KernelLaunch 侧
> **必须复用同一入口**（`load_golden(path, entry, input_type)`）和**同一比较标准**（`compare_outputs`，
> 其内部 delegate 到 devkit `precision_compare.compare_outputs`），否则交叉对比会因 golden 实现与
> 判定阈值不同而产生假性差异。
>
> "同一标准"不是一句口号，落在 **3 个可核对轴上**（与 rc harness `_harness_template.py` 的
> 实际比较口径逐项对齐，缺一即可能产生 rc-pass + kl-fail 假缺陷）：
> 1. **权威 golden 口径**：rc 默认 `golden_precision=fp64_cpu`——golden 在 **fp64 升精度输入**上跑作
>    权威真值，原生精度 golden 作 **native 同精度参考**（native_refs，#92 同精度兜底 ratio≤2）。
>    kl 侧若用 fp32 输入算 golden、或不提供同精度参考 → 判据**更严**（cpu_diff≡0 严格语义）。
> 2. **阈值表**：rc 生效阈值 = `DEFAULT_THRESHOLDS` ⊕ proto `precision_thresholds` 覆盖。kl 侧若只吃
>    默认表（如直接复用 `launcher.run_case` 内置默认比较）→ proto 覆盖丢（int 容差、fp8 等），判据错位。
> 3. **比较算法**：两侧都必须经同一 `precision_compare.compare_outputs`（MERE/MARE + 小值域/相消/
>    正常值域兜底）；kl 侧禁止退化为 `np.allclose` 等另一套算法。
>
> **默认怀疑顺序**：遇到 rc-pass + kl-fail，先按三轴怀疑 kl 脚本标准与 rc 不一致（Step 4.1 核查闭环），
> **不要**默认判 kernel 层缺陷——rc 交付通路已过，说明适配层与 kernel 数值在 rc 口径下正确。

若 `{debug_dir}/baseline/{op_name}_kernel_launch_test.py` 不存在，则生成。**直接参考**
`skills/ascendc-custom-op-precision/KernelLaunch/examples/run_exp_with_cannbench.py` 的写法，
**禁止**采用 `ascendc-custom-op-precision/SKILL.md §4.2` 模板（那个模板手写 `compute_golden`
并用 `np.allclose` 比较，是另一套标准，不适用于 baseline 交叉对比）。

生成步骤：

1. 读 `{golden_module_path}` 确认 golden 文件存在（不需读取函数体，加载交给 `load_golden`）。
2. 读 `{cases_csv_path}` 的前几行确认 CSV 列格式符合 cann-bench cases.csv 约定
   （`operator, case_id, input_shape, dtype, attrs, value_range, note`）。
3. 生成 `{op_name}_kernel_launch_test.py`，要点：
   - `import sys; sys.path.insert(0, ".")`（确保脚本运行目录下 `KernelLaunch` 可导入）。
   - 从 `KernelLaunch` 导入：
     ```python
     from KernelLaunch import (
         KernelLauncher, find_task_asset, load_cases, load_golden, setup_log_separation,
     )
     ```
   - `setup_log_separation(log_file="log_{op_name}.log", result_file="result_{op_name}.log")`。
   - **golden 加载**（与 run-cases harness 完全一致的契约）：
     ```python
     golden_fn = load_golden(
         "{golden_module_path}",
         entry="{golden.entry}",
         input_type="{golden.input_type}",
     )
     ```
     - `entry` 来自框架注入的 `golden.entry`（cann-bench 任务用算子名；手写 fixture 用 `reference`）。
     - `input_type` 来自框架注入的 `golden.input_type`（`numpy` 或 `torch`），与 run-cases 一致。
   - **用例加载**：`cases = load_cases("{cases_csv_path}")`。
   - **执行单 case**：`result = launcher.run_case(case, golden_fn)` —— launcher 内部
     生成输入（按 case 的 shape/dtype/value_range，固定 seed=42）、设置 attrs、启动 kernel、
     用 `golden_compare.compare_outputs` 与 golden 对比（delegate 到 devkit
     `precision_compare.compare_outputs`，MERE/MARE + dtype-aware threshold，**与 run-cases 同一标准**）。
   - **结果字段**（来自 `compare_outputs`，Step 3/4 解析时直接用这些字段）：
     `passed`、`mere`、`mare`、`max_diff`、`per_output[]`（每个 output 含
     `index/dtype/passed/threshold/mere/mare/max_diff/mismatch_count/total_count/error_msg`）。
   - `main()` 遍历 cases 全量执行并汇总 `rc_result`，可选 `--case 1,3,5` 支持子集运行。
   - **脚本末尾必须把全量 per-case 结果写为机器可读 JSON**（框架据此调和
     `failed_case_queue`：刷新 `max_diff_kl`、把 KL 已通过的 kernel 层 case 标
     `resolved`）——`main()` 收尾处追加：
     ```python
     import json
     summary = {
         "pass": n_pass, "total": n_total,
         "max_diff": max((r["max_diff"] for _, r in results
                          if r.get("max_diff") is not None), default=0.0),
         "per_case": [
             {"case_id": cid, "passed": r["passed"], "max_diff": r.get("max_diff")}
             for cid, r in results
         ],
     }
     with open(f"result_{OP_NAME}_summary.json", "w", encoding="utf-8") as f:
         json.dump(summary, f, indent=2, ensure_ascii=False)
     ```
      该文件落在 `{debug_dir}/baseline/result_{op_name}_summary.json`（脚本 cwd 即
     baseline 目录），是框架 `_load_latest_kl_data` 的首选读取路径——不写则框架
     调和恒空转（`max_diff_kl` 不刷新、KL 已通过的 case 不标 resolved）。
     kernel_debug 修复后批跑全量复用同一脚本，重跑会顺带刷新该文件。
     **模板中的 `OP_NAME` 必须是脚本内实际定义的算子名常量**（与
     `run_exp_with_cannbench.py` 的 `OP_NAME = "exp"` 同构）——summary 文件名必须
     精确等于 `result_{op_name}_summary.json`，变量名不一致会导致 NameError / 文件名
     对不上框架读取路径。
   - 构造时使用 `KernelLauncher("{op_name}", device_id=args.device_id)`（默认 `compile_mode="auto"`，
     优先匹配已安装的 binary kernel，**不要**用 `compile_mode="dynamic"` —— dynamic 会重编译，
     与 run-cases 实际跑的 OPP binary kernel 不是同一份二进制）。

> **为何用 `run_case` 而非手写 `compute_golden` + `np.allclose`**：
> - golden 来源统一：`load_golden` 与 run-cases harness 走同一个 `entry`/`input_type` 契约。
> - 比较标准统一：`compare_outputs` 内部就是 devkit `precision_compare.compare_outputs`，
>   MERE/MARE + per-dtype threshold（float16=2^-10、bfloat16=2^-7、float32=2^-13、int8=bit-exact …）。
>   `np.allclose(rtol, atol)` 是单一固定阈值，与 run-cases 不一致，会引入假性 pass/fail。
>
> **注意「同一标准」并非天然保证**：`launcher.run_case` 走默认阈值表，而 rc harness 可能叠加
> proto `precision_thresholds` 覆盖 / native 同精度兜底——两者不一致时 rc-pass + kl-fail 会以
> 「假 kernel 缺陷」出现。生成脚本后如遇此类分歧，按 **Step 4.1** 对齐 kl 判据到 rc 再判，
> 不要把「脚本是照 run_case 写的」当作已对齐的免检证据。

### Step 2：执行 run-cases 全量

```bash
{test_command} --label baseline --iter 0
```

解析 `result.json` 或 stdout 输出，提取：
- `pass` / `total`（通过/总用例数）
- `failed_cases[]`（每失败 case：`case_id`、`shape`、`dtype`、`max_diff`、`failure_type`）
- 框架层错误（crash/编译错误/注册失败）

**用例来源拆分（run-cases 跑全量，需分来源统计）**：run-cases 的 `state.test_cases`
是全量合并集 = **cann-bench 原有用例**（`cases.csv`）+ **st-design 生成用例**
（test_design 合并的 L0/L1/L2）。两者在各自 loader 构造 `TestCase` 时已打 `source`
标记（`cannbench` / `devkit`），编排层会把权威组成计数注入 prompt
（`test_case_source_composition`）。按每 case 的 `case` 字段（`{name}:{shape}`）取
`name`，与 `cases.csv` 的 `{operator}_{case_id}` 集合比对：命中 → cannbench，未命中
→ devkit（st-design）。据此产出：
- `rc_result.by_source` = `{cannbench:{pass,total}, devkit:{pass,total}}`；
- `## BASELINE_RESULT` 的 `rc_pass: {pass}/{total}` 行 = **`by_source.cannbench`**（与
  `kl_pass` 同基、可直接交叉对比；**不是** rc 全量合并总计）；`st-design-case: {pass}/{total}`
  行 = `by_source.devkit`。
- `rc_result.pass/total`（JSON）仍是 **run-cases 全量合并总计**（cannbench + devkit），供
  框架双工具验收门使用。关系：`rc_pass`(cannbench) + `st-design-case`(devkit) = `rc_result` 全量。

> `devkit.total` 必须等于编排注入的 `devkit(st-design)` 组成计数（框架会复核，不一致
> 留 WARN）。KernelLaunch 按 Step 1/3 只跑 `cases_csv_path`（cann-bench），故
> `kl_result` 无 st-design 拆分。

### Step 3：执行 KernelLaunch 全量

> 执行前必须完成 Step 0 的前置检查，确保环境变量已 source、`KernelLaunch` 可导入、且 `./kernel_meta/` 已清理。
> 在脚本所在目录运行，确保 `sys.path.insert(0, ".")` 与 `kernel_meta` 路径符合预期。

```bash
cd {debug_dir}/baseline
python3 {op_name}_kernel_launch_test.py
```

解析 `result_{op_name}.log` / stdout，提取每 case 的 `compare_outputs` 返回字段：
- `passed`（bool）— 该 case 是否通过（所有 output 的 AND）
- `mare` / `mere` / `max_diff`（float）— 最大相对误差 / 平均相对误差 / 最大绝对差
- `per_output[]` — 每个 output 的 `passed`/`threshold`/`mare`/`mere`/`max_diff`/`mismatch_count`/`error_msg`
- crash / 非零退出 → 标 `failure_type: "vector_error"`（OOB / 非法访存）

> 脚本运行结束会自动写出 `result_{op_name}_summary.json`（per_case 全量，见 Step 1
> 生成要点）；你只需从 log 解析出 `kl_result` 汇总写进 `baseline_result.json`，
> **不要手工维护 summary 文件**——它是脚本产物，由框架读取调和 `failed_case_queue`。

### Step 4：交叉对比 + 构建 failed_case_queue

对比两份结果，逐 case 判定并构建 `failed_case_queue`：

| 判定 | `error_layer` | 含义 |
|------|---------------|------|
| run-cases pass + KernelLaunch pass | — | 双工具全过 → 流程结束条件之一（见 Step 5） |
| run-cases fail + KernelLaunch fail | `kernel` | 问题在 kernel/tiling 层 |
| run-cases fail + KernelLaunch pass | `op_plugin` | 问题在 op_plugin/aclnn 适配层 |
| run-cases pass + KernelLaunch fail | `kernel` | KL 直测 binary 失败 → kernel/tiling 层；rc 虽过仍阻断——但**判 kernel 前必须先过 Step 4.1 标准一致性核查**（rc-pass+kl-fail 极可能是 kl 判据与 rc 不一致，先对齐再判） |
| run-cases fail + KernelLaunch crash | `kernel` + `failure_type: "vector_error"` | OOB / 非法访存 |

> **双工具门槛**：任一 case 在 rc 或 kl 任一工具失败即构成阻断（入
> `failed_case_queue` 并标 `error_layer`）。rc 全过但 kl 有失败（rc pass + kl fail）
> 属于 kernel 层阻断：不得因「rc 交付通路通过」就判非缺陷跳过——rc 通过只说明
> 适配层无错，kernel 直测仍暴露问题，须进 kernel_debug 处理。**但"kl 直测可信"
> 有一个隐含前提：kl 测试脚本用的是与 rc 相同的精度判据。rc-pass + kl-fail 的
> 大概率原因是 kl 脚本判据与 rc 不一致（KL 判得更严/更粗），必须先按 Step 4.1
> 对齐标准并重跑，对齐后仍失败才算真 kernel 缺陷。**

### Step 4.1：rc-pass + kl-fail 标准一致性核查（先怀疑 kl 判据，不直接判 kernel）

命中「rc pass + kl fail」的 case，**在标 `error_layer=kernel` 入队之前**，先做一次
标准一致性核查——kl 直测 binary 的结论只有在它使用 rc 同一精度标准时才成立
（Step 1 三轴：权威 golden 口径 / 阈值表 / 比较算法，§1.13 golden 是唯一权威，
两侧判据必须同源同一）：

1. **核对 kl 判据 vs rc 判据**：打开 `{op_name}_kernel_launch_test.py` 与 rc harness
   实际生效的判据（可从 run-cases result.json 反查 rc 每 dtype 真实阈值：
   `case_details[].output_results[].threshold`，结构见
   `references/run-cases-result-json.md`），逐项对照：
   - golden 是否按 rc 同口径升精度（fp64 权威）+ 原生 golden 同精度兜底；
   - 阈值表是否含 proto `precision_thresholds` 覆盖（KL 走 `compare_outputs` 默认表时会丢）；
   - 比较算法是否与 rc 同一 `compare_outputs`（禁 `np.allclose` 等另一套）。
2. **发现不一致 → 修 KL 脚本对齐 rc → 重跑全量 KL**：把 kl 判据改成与 rc 逐项一致
   （如把 rc 实际生效的 per-dtype 阈值作为 `thresholds` 传入 `compare_outputs`、补上
   proto 覆盖与同精度语义），重跑 `{op_name}_kernel_launch_test.py` 刷新
   `result_{op_name}_summary.json` / log。
3. **按对齐后的新 kl 结果重建 cross_compare**：
   - 对齐后该 case kl 通过 → **原 kl-fail 是标准不一致造成的假失败**：不判 kernel；
     该 case 双工具全过（`rc_pass=true, kl_pass=true`），不入 `failed_case_queue`；
   - 对齐后仍失败 → 真 kernel 层缺陷：`error_layer=kernel` 入队。
4. **一致性已确认仍失败**（脚本本就是 rc 同判据）→ 直接按 kernel 入队，无需重跑。
5. **留痕**：在 cross_compare 该 case 上加 `standard_check: "aligned" | "reconciled"`
   与 `max_diff_kl`（对齐后值），并同步更新 `kl_result` 计数——framework 以 cross_compare
   与 `kl_result` 为准构建队列，别让假失败流进 kernel_debug（白烧预算）。

`failed_case_queue` 每项：
```json
{
  "case_id": "...",
  "shape": "...",
  "dtype": "...",
  "max_diff_rc": 1.2e-4,
  "max_diff_kl": 1.1e-6,
  "error_layer": "op_plugin | kernel",
  "failure_type": "precision | runtime | vector_error",
  "status": "pending",
  "attempt_count": 0
}
```

### Step 5：判定 baseline_status（rc + kl 双工具全过才算通过）

- run-cases **且** KernelLaunch **双工具全 pass** → `baseline_status = "passed"`（精度交付通过）
- 任一工具存在失败 → `baseline_status = "failed"`

### Step 6：rc+kl 全 pass → 性能测量与 DONE 总结（仅此条件触发）

当 `rc_result.pass == rc_result.total` **且** `kl_result.pass == kl_result.total`
（rc 与 kl 两种状态的精度全部 pass）时，本 phase 即精度调试闭环的收尾点。在落盘
`baseline_result.json` 之前，必须完成：

1. **性能测量**：Read `.claude/skills/cann-bench-eval/SKILL.md`（性能-only skill），
   按其方法执行——前置检查 → 解析算子 PTA 符号 → 跑 `scripts/perf_eval.py` → 读
   `{debug_dir}/baseline/perf_result.json`。
2. **输出 DONE 总结**（最终消息中、`## RETURN:` 行之前，**精确按以下格式，必须使用英文**）：

```text
DONE: {op_name}
ACCURACY:
- cases: {通过用例数}/{用例数}
- by_dtype:
  - {dtype}: {通过数}/{总数} pass, tol={该 dtype 实际生效容差}
- verdict: pass|no
PERFORMANCE:
- summary: kernel_mean={x}us torch_npu_mean={y}us geo_speedup={z} faster={性能优化的用例数}/{可完整测量用例数}
- verdict: measured|no
FINAL: compile={pass|no} load={pass|no} accuracy={pass|no} perf={measured|no} reason={verified|no}: compile+load+accuracy {passed|no}
SELF_ASSESSMENT: {pass|no}
```

> 模板块内是**输出格式本体**（只含占位符，不含说明文字）。`by_dtype` 的填法：
> dtype 由实际测试用例决定（float16 / bfloat16 / float32 / hifloat32 / fp8_e4m3 /
> fp8_e5m2 / int8 …，**不限于固定清单**，由 cases.csv 实际出现的 dtype 决定），
> 逐 dtype 一行并列明该 dtype 实际生效容差；无该 dtype 用例则不出现该行。

**字段来源**：

| 字段 | 来源 |
|------|------|
| ACCURACY.cases | `rc_result.pass/total`（走到本步即双工具全 pass） |
| ACCURACY.by_dtype | cases.csv 逐 case dtype 分组计数 + 该 dtype 实际生效容差（优先取 result.json `case_details[].outputs[].threshold`；无逐输出数据时查 devkit `precision_compare.DEFAULT_THRESHOLDS`） |
| ACCURACY.verdict | 双工具全 pass → `pass`；否则 `no` |
| PERFORMANCE.summary | `perf_result.json` 的 `kernel_mean_us` / `torch_npu_mean_us` / `geo_speedup` / `faster_cases` / `complete_cases` |
| PERFORMANCE.verdict | `perf_result.json.verdict`（measured / no） |
| FINAL.compile | Step 0 第 1 项（build_command 编译安装成功且 set_env 存在） |
| FINAL.load | Step 0 第 2–6 项全过（环境生效、ttk / KernelLaunch 可用、NPU 设备可用、binary 匹配成功） |
| FINAL.accuracy | 双工具精度全 pass（本步前置条件） |
| FINAL.perf | PERFORMANCE.verdict |
| FINAL.reason | `verified` = 总结中每个数字都能在落盘产物（result.json / `result_{op_name}_summary.json` / perf_result.json）中找到出处；`no` = 存在缺失或假设 |
| FINAL 尾部 | compile + load + accuracy 三者全 pass → `passed`，否则 `no` |
| SELF_ASSESSMENT | 自检通过 → `pass`：格式精确匹配、数字全部有产物出处、无编造；任一不满足 → `no` |

3. **结构化落盘**：把总结各字段同步写入 `baseline_result.json.summary`（见 Step 8
   的 schema）。

**性能测量失败不阻塞收尾**：环境缺失 / PTA 符号无法解析 / golden 无法上 NPU 时，
PERFORMANCE.verdict=no、FINAL.perf=no，如实记录原因——**禁止编造数字**，也不得因
性能测不出而改判精度结论（accuracy 与 perf 相互独立）。

### Step 7：输出数值契约

在 `baseline_result.json` 的 `rc_result` 和 `kl_result` 中完整输出
`pass`、`total`、`max_diff`、`failed_cases`。禁止写 `checkpoint.json`；framework
以 RC 全量结果构造并比较 `best_snapshot`，在改善时提交并更新 `best_commit`。

> `rc_result.pass/total` 是 run-cases 的 **全量合并总计**（cann-bench + st-design），
> 框架双工具验收门以它为准。`## BASELINE_RESULT` 标记里的 `rc_pass` 行只取 cann-bench
> 子集（与 `kl_pass` 同基），**不是**这里的 `rc_result.pass/total`（见 Step 2 / Step 8）。

### Step 8：落盘 baseline_result.json

写入 `{debug_dir}/baseline/baseline_result.json`：

```json
{
  "phase": "baseline",
  "baseline_status": "passed | failed",
  "conclusion": "{一段话总结双工具基线结果与分流结论，如 '20 case 中 7 个 kernel 层失败、7 个 cann-bench 相对误差误报被剔除，路由 op_plugin_debug 修适配层'}",
  "rc_result": {"pass": N, "total": M, "max_diff": 0.0, "failed_cases": [...],
    "by_source": {
      "cannbench": {"pass": N, "total": M},
      "devkit": {"pass": N, "total": M}
    }
  },
  "kl_result": {"pass": N, "total": M, "max_diff": 0.0, "failed_cases": [...]},
  "cross_compare": [
    {
      "case_id": "...",
      "rc_pass": true,
      "kl_pass": false,
      "max_diff_rc": null,
      "max_diff_kl": 1.2e-4,
      "error_layer": "kernel",
      "failure_type": "precision",
      "standard_check": "aligned | reconciled"
    }
  ],
  "summary": {
    "op_name": "...",
    "accuracy": {
      "pass": N, "total": M,
      "by_dtype": [{"dtype": "float16", "pass": N, "total": M, "tol": 0.0009765625}],
      "verdict": "pass"
    },
    "performance": {
      "kernel_mean_us": 12.34, "torch_npu_mean_us": 45.67,
      "geo_speedup": 3.70, "faster_cases": 8, "complete_cases": 10,
      "verdict": "measured"
    },
    "final": {
      "compile": "pass", "load": "pass", "accuracy": "pass",
      "perf": "measured", "reason": "verified", "compile_load_accuracy": "passed"
    },
    "self_assessment": "pass"
  }
}
```

> **`rc_result.by_source`（必填）**：按来源拆分 run-cases 结果——`cannbench` = cann-bench
> 原有用例（cases.csv），`devkit` = st-design 生成用例（test_design 合并的 L0/L1/L2 CSV）。
> `devkit.total` 必须等于编排层注入的 `devkit(st-design)` 组成计数；`kl_result` 按 skill
> 约定只跑 cann-bench cases.csv，故无 st-design 拆分。`## BASELINE_RESULT` 的
> `st-design-case: {N}/{M}` 行即 `by_source.devkit`（N=pass，M=total）；而同节的
> `rc_pass: {N}/{M}` 行是 **cann-bench 子集**（= `by_source.cannbench`，与 `kl_pass`
> 同基可比），**不是** `rc_result.pass/total` 的全量合并总计。

> **`standard_check`（可选，仅 rc-pass + kl-fail 的 case 填，见 Step 4.1）**：
> `aligned` = 核查确认 kl 判据与 rc 一致后仍失败（真 kernel 缺陷）；`reconciled` =
> 原 kl 判据与 rc 不一致、已对齐并重跑 kl 后按新结果填报（对齐后 kl 通过则不入
> queue、`kl_pass` 应为 true；对齐后仍失败才 `error_layer=kernel` 且 `kl_pass=false`）。
> framework 以 `cross_compare`/`kl_result` 的实测为准构建队列，`standard_check` 仅留痕。

> **`summary`（仅 rc+kl 双工具全 pass 时写入，见 Step 6）**：DONE 总结的结构化
> 副本，字段与 Step 6 文本格式一一对应，供框架/下游确定性消费。perf 未测出时
> `performance.verdict="no"` 且数值字段为 null，并附 `reason`。

> **`conclusion`（必填，一段话字符串）**：本阶段结论，框架会把它物化到跨阶段接力文件
> `{debug_dir}/conclusions.json`（`conclusions_path`），后续阶段 agent 开工前读它即可
> 看到流程中其他 agent 的结论。请用自然语言写一段话，覆盖：本阶段干了什么、发现了什么、
> 得出什么结论。

---

## 返回格式

### 结构化产物落盘

`{debug_dir}/baseline/baseline_result.json` + 若首跑：`{op_name}_kernel_launch_test.py`
+ 若 rc+kl 全 pass：`{debug_dir}/baseline/perf_result.json`（cann-bench-eval 产物）。

### 返回标记（必须采用英文回复）

```markdown
## BASELINE_RESULT
status: PASSED|FAILED
all_pass: true|false
rc_pass: {N}/{M}
kl_pass: {N}/{M}
st-design-case: {N}/{M}
op_plugin_cases: <count>
kernel_cases: <count>
output_paths:
  - {debug_dir}/baseline/baseline_result.json
  - {debug_dir}/baseline/{op_name}_kernel_launch_test.py
  - {debug_dir}/baseline/perf_result.json（仅 rc+kl 全 pass 时）
error_info: ...（FAILED 时填）

## DONE_SUMMARY
（仅 rc+kl 双工具全 pass 时输出此节——按 Step 6 的精确格式：DONE: / ACCURACY: /
PERFORMANCE: / FINAL: / SELF_ASSESSMENT:。任一工具未全 pass 则整节省略。）

## RETURN: status=COMPLETED, phase=baseline, baseline_status={passed|failed}, code_modified=false
```

> **`## RETURN:` 行为强制完成信号（编排层路由判据之一）**：最后一行必须输出该
> 行，且 `status` / `phase` / `baseline_status` 必须与 result JSON 一致。缺失或
> 与 result JSON 不一致会被编排层判为 agent 自报状态异常并**重试本 agent**。

### Driver 状态机映射

| 返回 | 编排动作 |
|------|----------|
| `STATUS=COMPLETED, baseline_status=passed` | → `__escalate__:passed`（精度交付通过，流程结束） |
| `STATUS=COMPLETED, baseline_status=failed` | → 按 `error_layer` 分流（`has_kernel_failures` 优先 → `kernel_debug` 解 kernel/tiling 层精度问题；仅剩 `op_plugin` 失败 → `op_plugin_debug` 修适配层） |
| `STATUS=FAILED` | → 直接 escalate |

> **分流优先级**：kernel 层失败优先于 op_plugin 层（决策 Q6 修订）——出现精度问题
> 时优先调度 `ascendc-precision-kernel-debug`。混合队列（两类失败同时存在）路由
> `kernel_debug` 时，per-case 阶段的队列推进会跳过 `op_plugin` case；kernel 工作
> 收敛（KL 全过或止损）后回 baseline 重跑双工具，残余的适配层失败再分流到
> `op_plugin_debug`，不会被 kernel_debug 误吃。

---

## 参考文档

### KernelLaunch 参考（baseline 测试脚本模板）
- `skills/ascendc-custom-op-precision/KernelLaunch/examples/run_exp_with_cannbench.py` — **baseline 测试脚本的权威模板**（`load_golden` + `load_cases` + `run_case`，golden 与比较标准与 run-cases 完全对齐）
- `skills/ascendc-custom-op-precision/KernelLaunch/golden_compare.py` — `load_golden`/`load_cases`/`compare_outputs` 实现，`compare_outputs` 内部 delegate 到 devkit `precision_compare.compare_outputs`（MERE/MARE + dtype-aware threshold，与 run-cases 同一标准）
- `skills/ascendc-custom-op-precision/KernelLaunch/README.md` — `KernelLauncher` 构造参数、`compile_mode`、OOB 检测、`kernel_meta` 说明

> **注意**：`skills/ascendc-custom-op-precision/SKILL.md §4.2` 的模板（手写 `compute_golden` + `np.allclose`）是单算子独立验证用的，**不适用于 baseline 交叉对比** —— 它的 golden 来源和比较阈值都与 run-cases 不一致。baseline 必须用 `run_exp_with_cannbench.py` 模式。

### run-cases 参考
- `references/run-cases-result-json.md`（本 skill 目录内）— run-cases 执行与产物位置、result.json 结构与失败权威判据、failure_type 症状分类规则、指标提取与硬错误处理

### 性能测量参考（Step 6 专用）
- `skills/cann-bench-eval/SKILL.md` — **性能-only** skill：kernel vs torch_npu 逐 case 时延测量，`perf_result.json` 为 PERFORMANCE 段唯一证据源

### 下游阶段
- `skills/ascendc-precision-kernel-debug/SKILL.md` — kernel 层 per-case 调试 + 修复后批跑全量 KernelLaunch
- `skills/ascendc-precision-op-plugin-debug/SKILL.md` — 适配层修复循环
