---
name: ascendc-precision-op-plugin-debug
description: |
  A5 precision_debug 的 op_plugin_debug phase —— op_plugin/aclnn 适配层修复循环
  （框架层级，非 per-case）。
  触发条件：baseline 交叉对比发现 run-cases 失败但 KernelLaunch 同 case 通过
  （error_layer=op_plugin）。
  对比 KernelLaunch 传给 kernel 的参数 vs op_plugin/aclnn 传给 kernel 的参数
  （dtype/shape/attr/tiling），定位适配层差异并修复，
  随后 run-cases + KernelLaunch 双跑验证直到收敛
   （RC 不报框架错误 + RC/KL 结果基本一致）。
   若适配层排查确认非适配层根因（或已修复）、残余失败在 kernel/tiling 层
   （run-cases 与 KernelLaunch 都失败）→ 报 `debug_status=need_kernel_debug` +
   `kernel_cases` 清单，由框架移交 kernel_debug 做 per-case 调试。
   收敛后回 baseline 重新交叉对比。
   框架 CompositeGroup 驱动，spawn 单次执行——读接力、写本 phase 产物、
   输出 RESULT 行即返回，不控制循环/路由。
triggers:
  - ascendc-precision-op-plugin-debug
  - A5 op_plugin debug phase
  - 适配层修复
  - op_plugin 调试
  - aclnn 接口修复
  - adapter layer debug
allowed-tools: Read, Write, Bash, Glob, Grep, Edit
---

# Pipeline 叶子 Skill：A5 op_plugin/aclnn 适配层修复（op_plugin_debug）

## 定位

本 skill 是 **precision-debug stage** A5 精度调试的**阶段5（op_plugin_debug）**执行单元。
当 run-cases 失败但 KernelLaunch 同 case 通过时，说明问题在 op_plugin/aclnn 适配层
（而非 kernel/tiling 层），进入此阶段修复适配层代码。

**定位**：这是**框架层修复循环**，不是 per-case 调试。op_plugin/aclnn 适配层是所有 case 共享的，
修好它才能让后续 per-case kernel 调试有意义。op_plugin_debug 的循环退出判据是**全局的**
（所有 case 的 run-cases 不报框架错误 + 结果与 KernelLaunch 一致），而非单个 case。

**职责边界（叶子，单次返回）**：
- ✅ 读双工具基线的 diff 差值（`max_diff_rc` vs `max_diff_kl`）+ run-cases 框架错误信息
- ✅ 按错误码表解码 run-cases 返回的错误码（161xxx / 561xxx）
- ✅ 按 op_plugin-checklist 逐项排查：注册宏、aclnn/C++ OpAPI 签名、dtype 转换、shape reshape、attr 传递、tiling 参数映射、`op_info.json` 字段
- ✅ 读 op_plugin 层代码（`{op_name}.cpp` C++ OpAPI 实现）+ aclnn 接口定义
- ✅ 对比 KernelLaunch 传给 kernel 的参数 vs op_plugin/aclnn 传给 kernel 的参数（dtype/shape/attr/tiling），找差异
- ✅ 修 op_plugin 代码 → redeploy 重编出包
- ✅ 双跑验证收敛（RC 不报框架错误 + RC/KL 结果一致 → `converged`）
- ✅ **kernel 层移交**：适配层逐项排查全部 pass / 已修复，且残余失败 case 在 run-cases
  与 KernelLaunch 下都失败 → 属 kernel/tiling 层问题 → `debug_status=need_kernel_debug`
  + `kernel_cases` 清单，框架把对应 case 改标 `error_layer=kernel` 移交 `kernel_debug`
  做 per-case 精度调试
- ✅ 收敛后回 baseline 重新交叉对比
- ❌ **不**改算子 kernel 源码（kernel_debug 改的是 kernel，op_plugin_debug 改的是适配层——两者文件不同，不冲突）
- ❌ **不**控制循环/路由（框架 transition 替做）
- ❌ **不**派下级 subagent

---

## 输入参数（由 Driver 注入）

| 参数 | 必填 | 说明 |
|------|------|------|
| `op_name` | 是 | 算子名（snake_case） |
| `debug_dir` | 是 | precision debug 产物/日志根目录 |
| `code_dir` | 是 | 算子源码目录（含 op_plugin 层代码） |
| `golden_module_path` | 是 | Golden 模块路径（golden.py 参考实现文件绝对路径，由 Driver 注入 `state.golden_path`） |
| `golden.entry` | 是 | golden 函数入口名（cann-bench 用算子名；手写 fixture 用 `reference`） |
| `golden.input_type` | 是 | golden 函数期望的输入类型：`numpy` 或 `torch`（与 run-cases harness 的 `golden_input_type` 严格一致） |
| `failed_case_queue` | 是 | 当前 queue（含所有 `error_layer=op_plugin` 的 case） |
| `baseline_phase_json_path` | 否 | baseline 结果文件路径（默认 `{debug_dir}/baseline/baseline_result.json`） |
| `round` | 否 | `op_plugin_round`（Driver 循环计数，防死循环） |
| `max_rounds` | 否 | `max_op_plugin_rounds`（默认 10） |
| `previous_error` | 否 | 上一轮失败结论（Driver 重试注入） |
| `deploy_install_path` | 否 | Per-op OPP 安装路径 |
| `deploy_python_path` | 否 | Per-op Python wheel 安装路径 |
| `deploy_ld_path` | 否 | LD_LIBRARY_PATH 追加值 |
| `build_command` | 是 | 编译出包+安装的统一 CLI 命令（Driver 注入） |

---

## 执行流程

### Step 1：读双工具 diff + 分类问题

1. 读 `{debug_dir}/baseline/baseline_result.json`（或 `baseline_phase_json_path`），提取 `rc_result` 中 run-cases 的失败信息，分类：
   - **框架层错误**：crash / 编译错误 / 算子注册失败 / tiling 参数类型不匹配 → `framework_error` 非 `none`
   - **精度问题**：`max_diff` 有效数值
2. 读同文件中 `kl_result` 对应 case 的 KernelLaunch 结果
3. 计算 diff 差值：`diff_ratio = |max_diff_rc| / |max_diff_kl|`（若 KL pass 则 `max_diff_kl = 0`）
4. 输出 `diff_analysis` 摘要

### Step 2：按错误码表解码（框架层错误时）

若 run-cases 报框架层错误（`framework_error != "none"`），按错误码表解码：

Read `skills/ascendc-runtime-debug/references/error_codes.md`，映射：
- 161xxx → 环境配置问题
- 361xxx → Tiling 参数/数据类型不匹配
- 561xxx → Kernel 查找/注册失败

输出 `framework_error` 类型（`crash` / `compile` / `registration` / `tiling_mismatch` / `none`）。

### Step 3：逐项排查适配层（op_plugin-checklist）

按以下清单逐项检查 op_plugin 层代码：

| # | 检查项 | 检查内容 |
|---|--------|---------|
| 1 | 注册宏 | `REG_OP` 算子名是否与 kernel 一致；`REG_OP_HOST_SO` 注册路径是否正确 |
| 2 | aclnn 接口签名 | `aclnnOpName` 函数签名：输入/输出数量、dtype、shape 维度是否与 kernel 一致 |
| 3 | C++ OpAPI 实现 | `OpAdapter::Execute` 中 `InferShape`、`dtype` 转换、`format` 设置是否正确 |
| 4 | dtype 转换 | FP16→FP32、BF16→FP16 等隐式转换是否导致精度损失；`AclDataType` 映射是否正确 |
| 5 | shape reshape | `InferShape` 推导结果的 shape 是否与 kernel 预期一致；reshape/unsqueeze 是否正确 |
| 6 | attr 传递 | `SetAttr` / `GetAttr` 的 attr 名、类型、默认值是否与 kernel 一致 |
| 7 | tiling 参数映射 | `GetTilingFunc` 返回的 TilingData 字段是否与 host tiling 预期一致；int 溢出检查 |
| 8 | `op_info.json` | `op`/`input_desc`/`output_desc`/`attr`/`dtype` 字段是否与代码一致 |
| 9 | GE converter | 图引擎转换逻辑中算子类型映射是否正确 |
| 10 | **L2 executor 缓存键** | `aclnn<Op>GetWorkspaceSize` 首行 `L2_DFX_PHASE_1(aclnn<Op>, DFX_IN(...), DFX_OUT(...))` 的 `DFX_IN/DFX_OUT` 是否**包含全部 scalar attr**（及其它不改变输出 shape 的参数、meta 张量）——见下方「Step 3.5：L2 缓存键漏 attr 专项排查」 |

### Step 3.5：L2 缓存键漏 attr 专项排查（必做）

> **高频根因**。凡是
> 「run-cases 失败但 KernelLaunch 通过」且失败表现为「同 shape 换 attr 结果等于第一次调用」、
> 「失败 case 号漂移」或伴随随机 `507035 device error` 的，优先按本小节排查。

**机制**：`L2_DFX_PHASE_1` 展开为
`op::internal::GetFromCache(executor, workspaceSize, #APIName, IN, OUT)`
（`op_dfx.h:452`），缓存键 = hash(apiName + opConfig + **DFX_IN 元组** + **DFX_OUT 元组**)
（`op_cache.h:114-129`）。`AddParamToBuf` 对 `aclTensor*` 只序列化 **shape/dtype/strides 等元信息**，
**不包含 tensor 数据、也不包含未列入元组的 scalar 参数**。因此：

- 第一次调用把 attr（iter_step / eps / dim / reduction …）**烘焙进 tiling/executor 图**并缓存；
- 之后**同 shape** 的调用命中缓存，直接复用**第一个 executor**，新 attr 被静默丢弃；
- 输入数据本身仍走缓存图流式执行（数据正确）→ 换 shape / 单 case 隔离跑**完全不复现**，
  只有「同进程 + 同 shape + 换 attr」才暴露——**正是 run-cases 批量跑的特征**。

**若算子为绕 tiling 缓存额外引入 `meta` 张量**（如 mhc_sinkhorn 把 `[iter_step, eps]` 塞进
fp32[2] 输入让 kernel 直读），`meta` **必须同样进 `DFX_IN`**；否则缓存命中的 executor 绑定
**第一次调用那个 meta 张量的地址**——kernel 读到旧值；该张量被回收后变成**读已释放 device
内存** → 随机 `507035 device error type 3`。

**检查**：
```cpp
// aclnn<Op>GetWorkspaceSize 首行
L2_DFX_PHASE_1(aclnnMhcSinkhorn, DFX_IN(comb), DFX_OUT(combOut));   // ❌ attr/meta 未入键
L2_DFX_PHASE_1(aclnnMhcSinkhorn, DFX_IN(comb, meta, iterStep, eps), DFX_OUT(combOut)); // ✅
```

**修复**：把所有影响 tiling / 计算结果、且**不改变输出 shape** 的参数（scalar attr、meta 张量）
一并放入 `DFX_IN`。仓内惯例：
```cpp
// gather / scatter / grid_sampler_3d 同款
L2_DFX_PHASE_1(aclnnGather, DFX_IN(x, index, dim), DFX_OUT(y));
const char* reduceKey = (reduce != nullptr) ? reduce : "null";   // 字符串 attr null 归一化
L2_DFX_PHASE_1(aclnnScatter, DFX_IN(data, indices, updates, dim, reduceKey), DFX_OUT(y));
```
`AddParamToBuf` 已提供 `int64_t/float/double/char*/aclScalar*/aclIntArray*` 等重载
（`op_cache.h:69-99`），标量可直接入元组。**特例**：attr 若改变输出 shape（如 `top_k` 的 `k`），
缓存键已含输出 shape 天然不会误命中，但仍建议统一显式列入。

**归零验证（同进程换 attr 探测）**：
```python
op = torch.ops.cann_bench.mhc_sinkhorn.default
x = torch.rand(1024,4,4).npu()
y1 = op(x, 1, 1e-6); y5 = op(x, 5, 1e-6)
assert not torch.allclose(y1, y5)          # 相等 → 缓存键漏了 iter_step
assert torch.allclose(y5, golden(x.cpu(), 5))
```

### Step 4：对比 KL vs op_plugin 传参差异（核心）

1. 读 KernelLaunch 测试脚本中传给 kernel 的参数（`set_input` 的 dtype+shape、`pack_tiling_data` 的 tiling 字段）
2. 读 op_plugin 层传给 kernel 的参数（通过读 C++ OpAPI 代码 + `GetTilingFunc` 实现推断）
3. 逐参数对比 diff 差异

### Step 5：修复 op_plugin 代码 + redeploy

1. 修 op_plugin 层代码（`{code_dir}/op_plugin/{op_name}.cpp` 或等价路径）——不改算子 kernel 源码
2. 重新编译出包：
   ```bash
   {build_command}
   ```

### Step 5.5：KernelLaunch 前置检查（必做）

在 Step 6 调用 `KernelLaunch` 双跑验证前，必须完成以下检查；任一失败即停止并报 `FAILED`（`error_type=ENV`）：

1. **确认已重新编译部署**：Step 5 修改 op_plugin 代码后必须执行 `{build_command}` 并确认成功结束；若未执行，先补执行。
2. **重新 source 环境变量**：source 算子包 set_env，确保 `ASCEND_OPP_PATH` 包含自定义算子 OPP 目录：
   ```bash
   source {deploy_install_path}/vendors/custom_ops/bin/set_env.bash
   ```
3. **ttk 可用**：
   ```bash
   python3 -m ttk info
   ```
4. **KernelLaunch 可导入**：在 `{debug_dir}/baseline/{op_name}_kernel_launch_test.py` 运行目录验证：
   ```bash
   cd {debug_dir}/baseline
   python3 -c "import sys; sys.path.insert(0, '.'); from KernelLaunch import KernelLauncher; print('KernelLaunch OK')"
   ```

> **关于 `KernelLaunch` 导入路径**：若第 4 步导入失败，说明 `KernelLaunch` 不在脚本运行目录的 Python 路径上。典型解决办法：
> - 在运行脚本前设置 `PYTHONPATH=<KernelLaunch 父目录>:$PYTHONPATH`；
> - 或在 `{debug_dir}/baseline/{op_name}_kernel_launch_test.py` 头部加入 `sys.path.insert(0, "<KernelLaunch 父目录>")`。

> 详细说明与故障排查参见 `skills/ascendc-custom-op-precision/SKILL.md` 第2节，以及 `skills/ascendc-custom-op-precision/KernelLaunch/README.md`。

> **golden 来源（KernelLaunch 精度比较）**：本阶段 Step 6 的 KernelLaunch 全量双跑
> 复用 baseline 生成的 `{debug_dir}/baseline/{op_name}_kernel_launch_test.py`，其 golden
> 与 run-cases 同源，来自 Driver 注入的 `golden_module_path`（golden.py 参考实现文件）。
> 脚本内已写死 `load_golden("{golden_module_path}", entry="{golden.entry}", input_type="{golden.input_type}")`
> 契约——`golden.entry` 为 golden 函数入口名（cann-bench 用算子名；手写 fixture 用 `reference`），
> `golden.input_type` 为 golden 期望输入类型（`numpy` 或 `torch`），均与 run-cases harness
> 完全一致。比较标准为 devkit `precision_compare.compare_outputs`（MERE/MARE + dtype-aware
> threshold，见 `skills/ascendc-custom-op-precision/KernelLaunch/golden_compare.py`）。
> **本阶段不重新生成/不重新加载 golden**——直接执行 baseline 脚本即可；若 baseline 脚本缺失
> 或损坏，参照 `skills/ascendc-precision-baseline/SKILL.md` Step 1 用同一契约重新生成。

### Step 6：双跑验证收敛 / kernel 层移交判定

1. 执行 run-cases 全量：
   ```bash
   {test_command} --label op_plugin_debug --iter {round}
   ```
2. 执行 KernelLaunch 全量：
   ```bash
   cd {debug_dir}/baseline
   python3 ./{op_name}_kernel_launch_test.py
   ```
3. 判定收敛（两项都满足）：
   - **run-cases 不报框架层错误**（无 crash/编译错误/注册失败）→ `rc_no_framework_error = true`
   - **run-cases 结果与 KernelLaunch 结果基本一致**（同 case 的 pass/fail 状态一致，或精度误差在同量级）→ `rc_kl_consistent = true`
   - 收敛 → `debug_status = "converged"`；未收敛 → `debug_status = "retry"`

### Step 6.5：kernel/tiling 层移交判定（适配层非根因时）

当下列情况**同时**成立时，问题不在适配层，而在 kernel/tiling 层：

1. 适配层逐项排查（Step 3）**全部 pass**，或已修复且确认不再引入差异；
2. 对比 KL 传给 kernel 的参数 vs op_plugin/aclnn 传给 kernel 的参数（Step 4）**无差异**；
3. 双跑验证（Step 6）中，存在残余失败 case 在 **run-cases 与 KernelLaunch 下都失败**
   （`rc_no_framework_error=true` 且 `rc_kl_consistent=true`，但仍有 RC 与 KL 一致的失败 case）。

此时报 `debug_status = "need_kernel_debug"`，并把所有这类残余失败 case 的 `case_id`
填进 `kernel_cases` 数组。框架会把它们改标 `error_layer=kernel` 并移交 `kernel_debug`
做 per-case 精度调试（DumpTensor 二分 / VF 移交 / vector_error 路由都在该阶段）。

> **判别要点**：`need_kernel_debug` 是**诚实出口**——适配层已排查完毕，再自循环 retry
> 只会空烧 `max_op_plugin_rounds` 后 escalated 杀死整个精度流程。相反，
> **若仍有 case 只在 run-cases 失败而 KernelLaunch 通过**（RC/KL 不一致）→ 仍是适配层
> 问题，应 `retry` 继续修，**不得**报 `need_kernel_debug`。

---

## 返回格式

### 结构化产物落盘

`{debug_dir}/op-plugin-debug/op_plugin_round_{round}_result.json`：

```json
{
  "phase": "op_plugin_debug",
  "debug_status": "converged | retry | exhausted | need_kernel_debug",
  "conclusion": "{一段话总结本阶段排查结论，如 '适配层逐项排查全 pass，KL 与 op_plugin 传参无差异，确认非适配层根因；残余失败 case 在 RC/KL 双跑下都失败，属 kernel 层，已移交 kernel_debug'}",
  "framework_error": "crash | compile | registration | tiling_mismatch | none",
  "diff_analysis": "{diff 差值分析摘要}",
  "root_cause": "{适配层问题根因}",
  "code_modified": true,
  "fix_summary": "{修复说明}",
  "kernel_cases": [
    "level2/softmax_1",
    "level2/softmax_3"
  ],
  "checked_items": {
    "registration": "pass | fail",
    "aclnn_signature": "pass | fail",
    "op_api_impl": "pass | fail",
    "dtype_convert": "pass | fail",
    "shape_reshape": "pass | fail",
    "attr_pass": "pass | fail",
    "tiling_map": "pass | fail",
    "op_info_json": "pass | fail",
    "ge_converter": "pass | fail"
  },
  "convergence_check": {
    "rc_no_framework_error": true,
    "rc_kl_consistent": false
  }
}
```

> **`kernel_cases` 字段**（仅 `debug_status=need_kernel_debug` 时必填）：
> 残余失败且 RC/KL 一致的 case_id 列表（即判定为 kernel/tiling 层问题、需要移交
> kernel_debug 的 case）。缺省/为空时框架默认把全部残余失败视为 kernel 层移交。
> `debug_status` 取值须与 `## RETURN:` 行的 `debug_status` 一致，否则被判为
> agent 自报状态异常并重试。

> **`conclusion`（必填，一段话字符串）**：本阶段结论，框架会把它物化到跨阶段接力文件
> `{debug_dir}/conclusions.json`（`conclusions_path`），后续阶段 agent 开工前读它即可
> 看到流程中其他 agent 的结论。请用自然语言写一段话，覆盖：本阶段干了什么、发现了什么、
> 得出什么结论。

### 返回标记（机器可读标记必须英文/ASCII）

```markdown
## OP_PLUGIN_DEBUG_RESULT
status: PASSED|FAILED
debug_status: converged|retry|exhausted|need_kernel_debug
framework_error: {framework_error}
rc_kl_consistent: true|false
code_modified: true|false
kernel_cases: [case_id, ...]（debug_status=need_kernel_debug 时填写）
output_paths:
  - {debug_dir}/op-plugin-debug/op_plugin_round_{round}_result.json
error_info: ...（FAILED 时填）

## RETURN: status=COMPLETED, phase=op_plugin_debug, debug_status={converged|retry|exhausted|need_kernel_debug}, code_modified={true|false}
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
| `STATUS=COMPLETED, debug_status=converged` | → `baseline`（重新双跑建立新基线，此时 `error_layer` 标注会重新计算） |
| `STATUS=COMPLETED, debug_status=need_kernel_debug` | → `kernel_debug`（框架把 `kernel_cases` 改标 `error_layer=kernel` + `pending`，移交 per-case kernel 精度调试） |
| `STATUS=COMPLETED, debug_status=retry` | → 自循环（`op_plugin_round++`） |
| `STATUS=COMPLETED, debug_status=exhausted` | → `__escalate__:exhausted`（适配层修不了，`op_plugin_round >= max_op_plugin_rounds`） |
| `STATUS=FAILED` | → 直接 escalate |

### 死循环防护

`baseline → op_plugin_debug → converged → baseline → op_plugin_debug → ...` 路径
由框架全局 `op_plugin_round` 计数器（跨 baseline 回归不重置）防护：
- `op_plugin_round >= max_op_plugin_rounds`（默认 10）且 agent 仍报 `retry` → 钳制为 `exhausted` 退出
- `converged` / `need_kernel_debug` 是正向决策出口，不受轮次上限钳制（`need_kernel_debug` 移交
  kernel_debug 后，kernel_debug 修复后批跑全量 KL → baseline 会重新交叉对比，残余适配层问题会再次暴露）
- 计数在框架 transition 中递增，一次 precision_debug 运行内 op_plugin_debug 总调用次数有硬上限

---

## 参考文档

### 适配层领域知识
- `skills/ascendc-pta/SKILL.md` — op_plugin / aclnn 层的代码结构知识（C++ OpAPI 实现写法、aclnn 接口签名约定、GE converter、tiling 参数映射）——核心领域知识
- `skills/ascendc-dev-knowledge/SKILL.md` — aclnn API 规格 / op_plugin 注册机制查证

### 错误码 + 调试
- `skills/ascendc-runtime-debug/SKILL.md` — 运行时错误调试流程 + plog 解析
- `skills/ascendc-runtime-debug/references/error_codes.md` — 错误码表（161xxx/361xxx/561xxx 完整码）

### 双跑验证
- `skills/ascendc-precision-baseline/SKILL.md` — 双跑执行 + 交叉对比逻辑（同源复用）
- `skills/ascendc-custom-op-precision/SKILL.md` — KernelLaunch 上板脚本模板 + 前置环境检查（Read 参考，不 invoke）
- `skills/ascendc-custom-op-precision/KernelLaunch/README.md` — `KernelLauncher` 构造参数、`compile_mode`、OOB 检测、`kernel_meta` 说明（Read 参考，不 invoke）

### 上下游阶段
- `skills/ascendc-precision-kernel-debug/SKILL.md` — 下游阶段（与 kernel_debug 边界：op_plugin_debug 改适配层，kernel_debug 改 kernel 源码，文件不同不冲突；`need_kernel_debug` 时移交该阶段做 per-case 调试）
- `skills/ascendc-precision-baseline/SKILL.md` — 触发源（baseline 交叉对比发现 error_layer=op_plugin）
