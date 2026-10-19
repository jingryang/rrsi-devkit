---
name: ascendc-precision-vf-debug
description: |
  Pipeline 叶子 skill（A5 Regbase 专用）：VF 函数精度调试阶段。
  前置：阶段 kernel_debug 返回 is_vf_issue=true 且 vf_functions[0] 指认了出错 VF 函数。
  对 DumpTensor 证据指认出错的单个 VF 函数做隔离单元测试并修复：按函数名读取规格 →
  VF 指令参考预查询 + 历史经验检索 → 参考算子级 golden_module_path 构造 VF 级期望值 →
  用 SingleOperatorLaunch（复用 regbase-vf-test 工具链）生成测试 kernel + 编译运行 + 精度验证 →
  单次合规性检查 → 必要时修复 → 回验。
  复用 regbase-vf-test 的 SingleOperatorLaunch 工具链与 references（PYTHONPATH + Read 引用，不 invoke 父 skill）。
  A5 VF 调试由独立编排驱动（A5 Regbase precision-debug 编排，独立 L4 实施），本 skill 仅定义 VF 测试方法。
  跑一次返回（阶段结论），不派下级 subagent，不做循环（阶段循环骨架在 Driver）。
  返回 vf_status ∈ {passed, failed} + code_modified + 结构化 JSON。
  vf_status=passed 时 Driver 触发「代码修改后处理」并回 PHASE_KERNEL_DEBUG verify；
  vf_status=failed 时 Driver vf_round++ 重派（注入 previous_error=本轮 next_hint）。
  STATUS=FAILED（ENV/OTH 硬失败或 INP 数据缺漏）时 Driver 直接 escalate。
triggers:
  - ascendc-precision-vf-debug
  - VF 函数精度调试
  - RegBase VF 单元测试
  - 出错 VF 函数定位修复
  - A5 VF 精度问题
allowed-tools: Read, Write, Bash, Glob, Grep, Edit
---

# Pipeline 叶子 Skill：A5 VF 函数精度调试（vf-debug）

## 定位

本 skill 是 **precision-debug stage** A5 Regbase 精度调试的**kernel_debug 的子阶段（VF 函数精度调试）**执行单元。
在 kernel_debug 阶段 DumpTensor 证据**明确指向某 VF 函数输出错误**（`is_vf_issue=true`）后，
对该出错 VF 函数做隔离单元测试，定位并修复 VF 内部逻辑问题。

**职责边界（叶子，单次返回）**：
- ✅ 按**函数名**读取 VF 函数规格（从 `coding_index.md` `## VF 函数规格` 节按函数名匹配——非 Stage4 的 `.VT.{M}` sub-stage 标题定位）
- ✅ VF 指令参考预查询 + 历史经验库检索（Read `skills/regbase-vf-test/references/vf-instructions/` 与 `vf_experiences/`）
- ✅ 参考算子级 `golden_module_path` + `vf_functions[0].function` 构造 VF 级 golden 期望值
- ✅ 用 `SingleOperatorLaunch`（PYTHONPATH 复用 regbase-vf-test 工具链）生成测试 kernel + 编译运行 + 精度验证
- ✅ 对生成的 VF 代码做**单次**合规性检查（6 项；无内部循环——不合规即返回失败结论，由 Driver 重试）
- ✅ 精度失败时基于 DumpTensor 证据 + 指令参考分析根因，写入 `next_hint` 供 Driver 下一轮 `previous_error` 注入
- ✅ `vf_status=passed` 时提炼归约经验到 `vf_experiences/{类别}/experience-*.md`（按计算模式定位类别，不按算子归档）
- ❌ **不**自带内部重试循环（循环骨架在 Driver，每轮 `vf_round` 派 fresh subagent）
- ❌ **不**派下级 subagent，不 invoke 父 skill
- ❌ **不**改 code_dir 下源码（VF 测试产物落 `{debug_dir}/vf-test`；算子 kernel 源码修复由「代码修改后处理」回 s4-coding 时处理）

**工具依赖**：复用 `regbase-vf-test` 的 `SingleOperatorLaunch` 工具链（`skills/regbase-vf-test/SingleOperatorLaunch/`）
与 `ops-test-kit` 的 ttk 包。本 skill 不重复维护工具链代码，通过 PYTHONPATH 引用；
不 invoke `regbase-vf-test` skill，Read 其 references 作为知识源。

> **与 Stage4 `ascendc-vf-test-agent` 的区别**：Stage4 在开发期按 `.VT.{M}` sub-stage 逐个 VF 预验证（自带 `MAX_RETRY=3` 内部循环 + Stage4 门控）；本 skill 在调试期按 kernel_debug 指认的函数名做隔离测试（无内部循环、无门控，单次返回）。两者共用 `SingleOperatorLaunch` 工具链 + `vf-instructions/` 指令参考 + `vf_experiences/` 类别经验库，但面向不同生命周期阶段，适配各自的编排契约。

---

## 输入参数（由 Driver 注入）

> **A5 CompositeGroup 注入来源**：`vf_functions[0].*` 由框架 `VfTestSubstage` 从最新
> `kernel_debug_round_*_result.json` 解析并注入（同时注入 `kernel_debug_result_path` 供你读全量证据）。
> `name` 是真实代码里的原始函数名，`dtype` / `input_shapes` / `failed_case_id` 来自当前失败 case。
> 若 prompt 中未出现这些字段或它们为空，先读 `kernel_debug_result_path` 获取全量证据，**禁止自行猜测被测对象**。

| 参数 | 必填 | 说明 |
|------|------|------|
| `op_name` | 是 | 算子名（snake_case） |
| `debug_dir` | 是 | precision debug 产物/日志根目录（VF 产物落 `{debug_dir}/vf-test/kernel_test/`） |
| `code_dir` | 是 | 算子源码目录（工作目录/cwd） |
| `dev_record_dir` | 是 | 开发记录目录（含 coding_index.md / tiling_vf_design.json 等设计产物） |
| `vf_functions[0].name` | 是 | 出错 VF 函数的**原始函数名**（kernel_debug 指认；用于规格匹配与日志） |
| `vf_functions[0].function` | 是 | 该 VF 函数的功能描述（承担的计算职责，如"对 x 做 per-element 平方后按行 reduce sum 到 y"） |
| `vf_functions[0].evidence` | 是 | DumpTensor 数值证据（该 VF 输入正确但输出错误的摘要） |
| `vf_functions[0].dtype` | 是 | 阶段2 从失败用例 cases.csv 提取的出错时的 dtype 组合（如 `fp16→fp16` 或 `输入 fp16 输出 fp32`）；VF 单测**必须**包含此 dtype 场景 |
| `vf_functions[0].input_shapes` | 是 | 阶段2 记录的出错时该 VF 的实际输入 UB shape（如 `[[128,64]]`）；VF 单测**必须**包含此 shape 场景 |
| `vf_functions[0].failed_case_id` | 是 | 触发该 VF 错误的 cases.csv 用例 case_id（如 `case_03`）；供溯源与日志关联 |
| `golden_module_path` | 是 | Golden 模块路径（golden.py 参考实现文件绝对路径，由 Driver 注入 `state.golden_path`；本 skill 参考其中对应计算逻辑段构造 VF 级期望值，**不**调用 load_golden 做端到端对比） |
| `design_doc` | 否 | 详设路径（参考来源） |
| `SKILL_ROOT` | 否 | ascendc-dev skill 根目录（定位 `skills/regbase-vf-test/` references）；若注入则用于解析 reference 相对路径 |
| `round` | 否 | `vf_round`（Driver 循环计数，用于产物命名/落盘） |
| `previous_error` | 否 | 上一轮 VF 测试失败结论（Driver 重试注入）；首轮为空 |
| `deploy_install_path` | 否 | Per-op OPP 安装路径，由 Driver 透传 deploy_result.install_path |
| `deploy_python_path` | 否 | Per-op Python wheel 安装路径，由 Driver 透传 deploy_result.python_path |
| `deploy_ld_path` | 否 | LD_LIBRARY_PATH 追加值，由 Driver 透传 deploy_result.ld_library_path_add |
| `build_command` | 是 | 编译出包+安装的统一 CLI 命令（Driver 注入） |

---

## 执行流程

### Step 0：环境与工具准备

1. 编译算子出包

执行 Driver 注入的编译部署命令，并自动完成自定义算子包环境变量配置：

```bash
{build_command}
```

2. 配置自定义算子包环境变量（由 Driver 透传 deploy_result）

`ascendc-devkit redeploy` 编译部署时将算子安装到 per-op 隔离目录，测试算子时需在 `deploy_install_path` 寻找 `bin/set_env.bash` 然后：

```bash
source {deploy_install_path}/vendors/custom_ops/bin/set_env.bash
```

3. 检查 `ttk` 并确保 `SingleOperatorLaunch` 可用

`SingleOperatorLaunch` 依赖 `ttk`，先检查 `ttk` 是否存在，禁止主动安装。

```bash
python3 -m ttk info
```

`SingleOperatorLaunch` 在 `skills/regbase-vf-test/SingleOperatorLaunch` 中，确保可用：

```bash
python -c "import SingleOperatorLaunch"
```

4. **硬件参数**：
   - `actual_UB_size`（UB 容量约束用）对于 Ascend950 为 248KB

### Step 1：按函数名读取 VF 函数规格

读取 `{dev_record_dir}/coding_index.md` 底部 `## VF 函数规格` 节，找到与 `vf_functions[0].name` **匹配的函数**（按函数名列匹配，**非**按 sub-stage 标题定位）。

从该函数的规格表中提取：
- `vf_function_name`：原始函数名（= `vf_functions[0].name`）
- `vf_declaration`：函数声明（`__aicore__ inline void` 完整签名，来自设计文档；用于构造测试 kernel 的 `__aicore__` wrapper 签名和调用接口）
- `vf_func_snake`：snake_case 后的基名（如 `SquareReduceSum` → `square_reduce_sum`），用于目录/文件命名
- 输入变量列表：名称、UB shape、dtype
- 输出变量列表：名称、UB shape、dtype
- 计算逻辑描述

> **与 Stage4 vf-test-agent 的差异**：Stage4 按 `### {current_sub_stage}` 三级标题定位（如 `### 4.C.2.VT.0`）；本 skill 按函数名匹配（Phase C+ 上下文中出错 VF 已由 kernel_debug 指认名字，无 sub-stage 概念）。

若 `coding_index.md` 无 `## VF 函数规格` 节，或该节中找不到 `vf_functions[0].name` → 返回 FAILED，`error_type=INP`，error_info 注明"coding_index.md 中未找到 VF 函数 {name} 的规格"。

### Step 2：VF 指令参考预查询（必做）

根据 `vf_functions[0].function` 的计算语义，Read VF 指令参考文档（位于 `skills/regbase-vf-test/references/vf-instructions/`）：

1. Read `skills/regbase-vf-test/references/vf-instructions/INDEX.md`，用决策树（Section 4）定位所需流水线 Pattern
2. 打开对应单指令文件查阅精确语义（`cast.md` / `interleave.md` / `load-align.md` / `store-align.md` / `ub-basics.md`）
3. **需要确认具体 API 调用形态/参数约束/完整示例时**，Read `skills/regbase-vf-test/references/a5-api-enhanced/{函数名}.md`（增强文档优先于官方签名；无对应文件回退 `ascendc-dev-knowledge` 官方 API）
4. 对照 `INDEX.md` Section 3（常见陷阱）检查

**查询产出**：将 Pattern、CastTrait、LoadDist/StoreDist 选型、Interleave 顺序等关键结论作为 `vf_instruction_hints`（JSON 字符串），供 Step 4 生成 VF 代码时优先遵循。

### Step 3：VF 类别经验库检索（必做）

按当前 VF 的**计算模式**定位 `skills/regbase-vf-test/references/vf_experiences/` 下已归档的类别级经验（**按计算语义组织，非按算子**）：

1. 先读 `vf_experiences/{类别}/INDEX.md` 判据（cast / dequant-quant / elementwise / reduce / gather-scatter / layout / sort-select / stateful-accumulator），判定当前 VF 所属类别
2. 按计算语义、dtype、横切特征（`simt-async` / `unaligned-2d` / `multi-dtype` / `mask-tail`）匹配该类别下 `experience-*.md` 条目，提取实现要点、坑位与对策、可复用模式

**复用层次**：
- **层次 A（跨算子经验库）**：按类别检索（即使本算子第一个 VF 也执行）
- **层次 B（算子内接力）**：若 `{debug_dir}/vf-test/kernel_test/{其他 vf_func_snake}_test/vf_lesson.md` 存在（Phase C 已验证 VF 或本循环前序轮次产出），Read 作上下文补充

匹配结论与 Step 2 指令参考交叉校验；冲突时以指令参考语义为准，偏差记录入 `vf_instruction_hints`。

### Step 4：构造 VF 级 golden 参考

**关键纪律**：VF 单测是**隔离**的，输入/输出 shape 与算子级不同。**禁止**直接用 `golden_module_path` 端到端输出作为 VF 单测期望值。

构造方式：
1. 以 `vf_functions[0].function`（功能描述）为语义来源
2. Read `golden_module_path`（`{golden_module_path}` 路径），对照其中**对应计算逻辑段**的实现
3. 提取该 VF 函数职责段的期望行为，构造单 VF 函数测试的期望值（shape/dtype 按 Step 1 规格表，非算子级 shape）

> 例：算子级 golden 含 `def golden(x, attrs): y = x.pow(2).sum(dim=-1); return y`，若出错 VF 是 `SquareReduceSum`（职责=平方后行归约），则 VF 级期望 = 对 UB shape `[m, nAlign]` 输入做平方后按行求和到 `[m]`——取算子级 golden 的 `.pow(2).sum(dim=-1)` 逻辑段，但输入 shape 换成 VF 规格 shape。

### Step 5：生成测试 kernel + 编译运行 + 精度验证

在 `{debug_dir}/vf-test/kernel_test/{vf_func_snake}_test/` 目录下：

> **被测 VF 来源（硬规则，防假通过）**：
> 被测对象必须是 `{code_dir}` 实际 kernel 代码里的 `__simd_vf__` 函数。
> 1. 按 `vf_functions[0].name`（如 `CustomRegImpl::ReduceSumBinaryFold`）在 `{code_dir}/op_kernel/*.{h,cpp}`
>    （或 `{code_dir}` 下其它 kernel 源文件）中定位**真实实现**；
> 2. 把该 `__simd_vf__` 函数体**原样搬运**进测试 kernel 的 `__simd_vf__` 层——只能在此基础上外加
>    `__aicore__` wrapper 与测试数据的搬入/搬出，**不得改写函数内部逻辑、不得按设计文档重建**；
> 3. **禁止**把 `{code_dir}/vf_verified/`（开发期已测脚本）或 `references/examples/` 模板里的 VF
>    实现当作被测对象——它们只可作 harness/wrapper 写法参考，不可作为被测 VF 函数体来源
>    （测理想重建而非真实实现会让真实缺陷逃逸）；
> 4. 生成 `{vf_func_snake}_custom.cpp` 后，**对搬运的 VF 函数体与真实源码做 diff 核对**，
>    逐处差异（函数名/参数/常量/CastTrait/循环/掩码/地址偏移）记录进 `compliance` 报告；
>    差异未消除 → 视为不合规（`vf_status=failed`，`error_type=COMPL`），由 Driver 重试。

1. **生成 `{vf_func_snake}_custom.cpp`**（AscendC Kernel 源码）：
   - 被测 VF 函数体按上述硬规则从 `{code_dir}` 真实源码搬运；
   - `__aicore__` Impl 层 / 测试搬数逻辑可参考 `skills/regbase-vf-test/SingleOperatorLaunch/` 的
     example、README，以及 `references/examples/` 下语义最相近的 `.cpp` 模板（仅作 harness 写法参考）；
   - 三层调用链：`__aicore__` Impl 层（`LocalTensor<T>` → `GetPhyAddr()` → `__simd_vf__`）→ `__simd_vf__` RegImpl 层（Load→Compute→Store 循环）→ 可选 `__simd_callee__` Core 层
   - 应用 Step 2/3 的 `vf_instruction_hints`
   - 完成必要测试数据的搬入搬出（参考 `skills/regbase-vf-test/references/ascend_basic_ub_knowledge.md`）

2. **生成 `test_{vf_func_snake}.py`**（Python 测试脚本，从同目录 `_custom.cpp` 读源码传给 `SourceModule`）：
   - 用 Step 4 构造的 VF 级 golden 作期望值
   - **【第一优先级：阶段2 失败场景复现（强制）】**：
     - **必须**包含 `vf_functions[0].dtype`（阶段2 出错时的 dtype 组合，如 fp16→fp16）作为至少一个用例
     - **必须**包含 `vf_functions[0].input_shapes`（阶段2 出错时的 VF 实际输入 UB shape，如 [[128,64]]）作为至少一个用例
     - 若 `input_shapes` 为空，则从 `dump_evidence` 中推断出错的 shape 范围，至少包含一个近似 shape 的用例
     - **这是阶段2.1 存在的根本价值**——验证并修复阶段2 已实际发现的 VF 错误。仅跑通用多 shape 而遗漏阶段2 发现错误的具体场景，会导致 VF 单测假性通过（与阶段2 失败信息脱节），阶段2.1 失去存在意义
   - **【第二优先级：通用多 shape 覆盖（强制）】**：在第一优先级的失败场景之外，额外覆盖：32B 对齐 / 非对齐（验尾块 mask）/ 极小（< REPEAT_STRIDE，验单轮 partial mask）/ 大 shape（验循环边界）；dtype 与算子一致
   - **多 dtype numpy 支持**：当 `vf_functions[0].dtype` 包含 `bfloat16 / int4 / float8 / float4` 等非原生 numpy dtype 时，测试脚本必须使用 `ttk.utilities.dtypes` 提供的构造器和转换函数构造输入/输出数组；具体写法参见 `skills/regbase-vf-test/references/multi-dtype-numpy.md`。
   - 调用 kernel 时通过 `output_indices` 启用OOB 检测（哨兵 + 数据不变双重越界检测）
   - **UB 容量约束（强制）**：每 test_case 的 `pipe.InitBuffer` 总量 < `actual_UB_size - 1KB`

3. **编译运行**：
   ```bash
   python3 {debug_dir}/vf-test/kernel_test/{vf_func_snake}_test/test_{vf_func_snake}.py --device_id 0
   ```
   选 `Health:OK` 的设备（先 `DeviceInfo()` 查状态）。

4. **解析精度结果**：`np.allclose` 是否通过，`max_diff`、failed_cases（shape/dtype/max_diff）。

### Step 6：单次合规性检查（精度通过后执行）

> 检查规则基于 `skills/regbase-vf-test/references/ascend_regbase_programing_guide.md`，验证前先 Read 该文档。
>
> **与 Stage4 vf-test-agent 的差异**：Stage4 在合规性失败时内部循环重新生成（`MAX_RETRY=3`）；本 skill **单次执行**——不合规即形成 `vf_status=failed` 结论（附详细不合规报告），由 Driver 决定重试（下一轮 `vf_round` 注入 `previous_error`）。

对 `{vf_func_snake}_custom.cpp` 做以下 6 项检查：

#### 检查项 1：函数修饰符与调用链结构

| 核对点 | 预期 |
|--------|------|
| `__aicore__` Impl 层 | 接收 `LocalTensor<T>`，`GetPhyAddr()` 提取 `__ubuf__ T *` 后调 `__simd_vf__` |
| `__simd_vf__` RegImpl 层 | 参数全为 `__ubuf__ T *` + 标量（calCount/rows/cols），含 Load→Compute→Store 循环 |
| `__simd_callee__` Core 层（可选） | 仅复合逻辑（如 Rsqrt=Sqrt+Div），被 `__simd_vf__` 调用，只操作 RegTensor |

#### 检查项 2：Hardware Loop 规范

| 核对点 | 预期 |
|--------|------|
| 迭代变量类型 | `uint16_t` |
| 起始值 | 从 0 开始 |
| 步长 | 递增 1（`++i`/`i++`） |
| 循环内分支 | 禁止 `if/else`/三元 `?:`；`if constexpr` 除外 |
| 嵌套层数 | ≤ 4 层 |
| 运行时条件 | 用 `for(uint16_t i=0; i<hasTail; i++)` 替代 `if` |

#### 检查项 3：RegBase 数据搬运与计算 API

| 核对点 | 预期 |
|--------|------|
| 对齐加载 | `AscendC::Reg::LoadAlign<T>(reg, srcAddr + offset)` |
| 非对齐加载 | `LoadUnAlignPre` + `LoadUnAlign` 配对 |
| 对齐存储 | `AscendC::Reg::StoreAlign<T, StoreDist>(dstAddr + offset, reg, mask)` |
| 非对齐存储 | `StoreUnAlign` + `StoreUnAlignPost` 成对 |
| 计算指令 | `AscendC::Reg::Mul/Add/Sub/Muls/Adds/Div/Sqrt` 等 |
| 标量传递 | 标量作 VF 参数，`Reg::Duplicate` 广播；禁止先广播到 UB 再 Load |
| 禁止行为 | `__simd_vf__` 内禁调 `DataCopy/DataCopyPad/PipeBarrier/SetFlag/WaitFlag` |

#### 检查项 4：Mask 处理与 shape 正确性

| 核对点 | 预期 |
|--------|------|
| `UpdateMask` 参数 | `scalarValue` 为剩余元素数（传入传出，调用后递减 VL_T） |
| `repeatTime` | `= ceil(calCount * sizeof(T) / VL)`，VL=256B；float 时 `REPEAT_STRIDE=64` |
| 循环内偏移 | `srcAddr + i * REPEAT_STRIDE`（单位元素数，非字节） |
| `oriK` vs `strideK` | mask/repeatTime 用 `oriK`；地址偏移用对齐后 `strideK` |
| 累积操作保护 | ReduceMax/ReduceSum 用 main+tail 分离避免 partial mask 清零已累积值 |
| UB 对齐 | `CeilDiv(len * sizeof(T), 32) * 32` |

#### 检查项 5：寄存器资源与代码规范

| 核对点 | 预期 |
|--------|------|
| RegTensor 数量 | 单 `__simd_vf__` 内 ≤ 32 |
| MaskReg 数量 | ≤ 8 |
| 循环不变外提 | `Duplicate`/`CreateMask` 等提到循环外 |
| 成员变量预取 | tiling 成员预取到 `uint16_t` 局部变量 |

#### 检查项 6：测试覆盖度与 UB 容量

确认 `test_{vf_func_snake}.py` 含：

| 核对点 | 预期 |
|--------|------|
| 32B 对齐场景 | `cols * sizeof(dtype) % 32 == 0`，≥ 1 个 |
| 非对齐场景 | `cols * sizeof(dtype) % 32 != 0`，≥ 1 个（验尾块 mask） |
| 极小 shape | < `REPEAT_STRIDE`（验单轮 partial mask） |
| 大 shape | 多轮循环（验循环边界） |
| dtype 覆盖 | 与算子 dtype 一致 |
| UB 容量 | 每 test_case 的 `pipe.InitBuffer` 总量 < `actual_UB_size - 1KB` |

#### 合规性结论

- **6 项全合规** → 继续 Step 7 形成结论（`vf_status=passed`）
- **任一不合规** → 形成结论 `vf_status=failed`，`error_type=COMPL`，error_info 含：哪个检查项、哪行代码、期望 vs 实际、修改建议（供 Driver 下一轮 `previous_error` 注入）

### Step 7：形成 vf_status 结论 + 归档

综合 Step 5（精度结果）+ Step 6（合规性检查）形成结论：

| 精度结果 | 合规性检查 | 结论 `vf_status` | `error_type` | 说明 |
|---------|-----------|-----------------|--------------|------|
| allclose 通过 | 6 项全合规 | `passed` | 空 | VF 修复并验证通过 |
| allclose 通过 | 任一不合规 | `failed` | `COMPL` | 合规性问题，本轮未通过（Driver 可重试） |
| allclose 失败 | — | `failed` | `PREC` | 精度失败（Driver 可重试） |
| 编译失败 | — | `failed` | `COMPILE` | 编译失败（Driver 可重试） |
| 设备/CANN 错误 | — | `failed`（硬失败 STATUS=FAILED） | `ENV` | Driver 直接 escalate |
| 其他无法归类 | — | `failed`（硬失败 STATUS=FAILED） | `OTH` | Driver 直接 escalate |

**`code_modified` 判定**：只要生成了 `{vf_func_snake}_custom.cpp`（含修复/新生成的 VF 实现），即 `code_modified=true`——Driver 据此触发「代码修改后处理」（s5-compile + deploy force-reinstall）同步 cann-bench 通路。环境错误（ENV）下未产出源码则 `code_modified=false`。

**经验归档**（`vf_status=passed` 时执行）：
1. 生成 `{debug_dir}/vf-test/kernel_test/{vf_func_snake}_test/vf_lesson.md`（本算子内过程资产：函数职责、实现要点、mask 策略、对齐/非对齐处理、问题与解决办法、可复用代码模式、参考文档）
2. **提炼归约**本次验证中**新增/修正的类别级经验**进 `skills/regbase-vf-test/references/vf_experiences/{类别}/experience-*.md`：先读 `INDEX.md` 判据确定类别，同类目**并入既有条目**；只沉淀抽象经验（不放完整源码答案），条目末尾更新 `实证来源`（**仅算子/函数标识 + 通过数/max_diff，禁绝对路径**）；`vf_lesson.md` 不复制进经验库
   - **绝对路径禁令**：条目内禁止出现生成环境绝对路径（`/home/...`、`/app/...`、`$RECORD_DIR`/`$SKILL_ROOT` 展开路径等）

> **checkpoint 写入边界（强制）**：`checkpoint.json` 由框架唯一写者维护——包括 `best_snapshot`。
> agent 不得读取/比较/改写 `checkpoint.json` 的任何字段（`best_snapshot`、`status`、`phase`、
> `*_round`、`*_status`、`history` 等）。VF 单测的精度结果只写入本 phase 的
> `{debug_dir}/vf-test/vf_round_{round}_result.json`；框架 `transition` 从该文件提取
> 数值结果并按 `_snapshot_better` 决定是否刷新 `best_snapshot`。

---

## 返回格式

本 skill 执行完毕后，必须先落盘结构化 JSON，再在最终回复前 5 行内输出机器可读标记。

### 结构化产物落盘

`{debug_dir}/vf-test/vf_round_{round}_result.json`：

```json
{
  "phase": "vf-test",
  "vf_status": "passed | failed",
  "conclusion": "{一段话总结 VF 隔离测试结论，如 'CustomRegImpl::ReduceSumBinaryFold 在 fp16 2x32x64x64x64 下精度通过，max_diff=6e-3，VF 输出与 golden 一致，可回 kernel_debug 继续'}",
  "vf_func": "{vf_function_name}",
  "vf_func_snake": "{vf_func_snake}",
  "code_modified": true,
  "failed_case_id": "{阶段2 注入的触发用例 case_id，供溯源}",
  "failed_dtype": "{阶段2 注入的出错 dtype 组合}",
  "failed_input_shapes": "{阶段2 注入的出错 input_shapes}",
  "dump_evidence": "{kernel_debug 阶段注入的 DumpTensor 证据摘要}",
  "compliance": "all_passed | {不合规检查项编号与摘要}",
  "precision_result": {"pass": N, "total": M, "max_diff": ..., "failed_cases": [{"shape", "dtype", "max_diff"}]},
  "fix_summary": "{根因分析 + 修复说明 or empty}",
  "output_paths": ["{debug_dir}/vf-test/kernel_test/{vf_func_snake}_test/{vf_func_snake}_custom.cpp", ".../test_{vf_func_snake}.py", ".../vf_lesson.md"],
  "error_type": "VECTOR_ERROR|PREC|COMPL|COMPILE|ENV|INP|OTH|",
  "vector_error_evidence": {
    "case_id": "",
    "error_code": "",
    "fingerprint": "",
    "run_log": "",
    "stderr_excerpt": ""
  },
  "script_path": "{test_*.py 路径}",
  "test_summary": "{passed}/{total} cases passed, max_diff={max_diff}",
  "next_hint": "{供 Driver 下一轮 previous_error 注入的失败结论摘要（vf_status=failed 时填）}"
}
```

> **`conclusion`（必填，一段话字符串）**：本阶段结论，框架会把它物化到跨阶段接力文件
> `{debug_dir}/conclusions.json`（`conclusions_path`），后续阶段 agent 开工前读它即可
> 看到流程中其他 agent 的结论。请用自然语言写一段话，覆盖：本阶段干了什么、发现了什么、
> 得出什么结论。

### 返回标记（机器可读标记必须英文/ASCII）

```markdown
## VF_TEST_RESULT
status: PASSED|FAILED
vf_func: {vf_function_name}
output_paths:
  - {debug_dir}/vf-test/kernel_test/{vf_func_snake}_test/{vf_func_snake}_custom.cpp
  - {debug_dir}/vf-test/kernel_test/{vf_func_snake}_test/test_{vf_func_snake}.py
  - {debug_dir}/vf-test/kernel_test/{vf_func_snake}_test/vf_lesson.md（passed 时）
test_summary: {passed}/{total} cases passed, max_diff={max_diff}
error_info: ...（FAILED 时填）

## RETURN: status={STATUS}, phase=vf-test, vf_status={passed|failed}, code_modified={true|false}, error_type={...}
```

> **`## RETURN:` 行为强制完成信号（编排层路由判据之一）**：最后一行必须输出该
> 行，且 `status` / `phase` / `vf_status` 必须与 result JSON 一致。缺失或与
> result JSON 不一致会被编排层判为 agent 自报状态异常并**重试本 agent**。
>
> **语言硬要求**：`RESULT` 行、`## RETURN:` 行及其全部字段名（`status=` /
> `phase=` / `vf_status=` …）必须与模板**逐字英文/ASCII**，不得意译为中文（如
> `状态=`）。编排层按固定英文字段名做确定性解析——字段名写成中文会令完成信号
> 解析失败/错位（历史实证：`状态=COMPLETED` 未被识别时，`vf_status=fixed` 中的
> `status=fixed` 子串被误读为状态，整轮结果废弃并重派本 agent）。自然语言说明
> 文字（`conclusion` / `error_info` 等）可用中文，机器可读标记一律英文。

| 字段 | 值 |
|------|----|
| `STATUS`（外层） | `COMPLETED`（本轮得出明确结论，含 passed/failed；vf_status 由字段给出）/ `FAILED`（硬失败无法继续：`ENV`/`OTH` 环境/未知硬失败，或 `INP` 数据缺漏——均直接 escalate 不重试） |
| `phase` | 固定 `vf-test` |
| `vf_status` | `passed`（VF 修复并验证通过）/ `failed`（本轮未通过，Driver 可重试）。STATUS=FAILED（硬失败）时可留空 |
| `code_modified` | `true` / `false`（生成了 VF 源码则 true） |
| `error_type` | STATUS=COMPLETED 且 vf_status=passed 时留空；否则填 `VECTOR_ERROR`/`PREC`/`COMPL`/`COMPILE`/`ENV`/`INP`/`OTH` 之一 |

### Driver 状态机映射

| 返回 | 编排动作（见 A5 Regbase precision-debug 编排独立 L4 文档） |
|------|------------------------------------------------------------------|
| `STATUS=COMPLETED, vf_status=passed, code_modified=true` | [代码修改后处理] → 回 PHASE_DUMP_DEBUG verify |
| `STATUS=COMPLETED, vf_status=passed, code_modified=false` | → 回 PHASE_DUMP_DEBUG verify |
| `STATUS=COMPLETED, vf_status=failed` | vf_round++；>= max_vf_rounds → escalate；否则重派本 skill（注入 `previous_error`=本轮 `next_hint`） |
| `STATUS=FAILED, error_type=ENV/OTH` | 直接 escalate（不通过 vf_round 重试） |
| `STATUS=FAILED, error_type=INP` | 直接 escalate（不重试）——INP 是**数据缺漏**（`kernel_debug_result_path` 缺失/不可读，或 `coding_index.md` 缺 VF 规格）：重试同一 agent 不会修复缺字段（注入来自框架读上游产物），框架据此 escalate 留痕为框架侧问题（§1.2 可诊断），而非让 agent 空转 |

### VECTOR_ERROR 交接规则

VF 隔离运行或算子回验出现 device vector exception 时：

1. 设置 `vf_status=failed`、`error_type=VECTOR_ERROR`。
2. `vector_error_evidence` 至少填写 case、错误码和日志。
3. 立即落盘并返回，由 Driver 切换到 vector-error 定位。
4. 不继续生成普通 VF 精度候选，不更新 `best_snapshot`。

### 示例

**VF 修复通过：**
```markdown
## VF_TEST_RESULT
status: PASSED
vf_func: SquareReduceSum
output_paths:
  - /path/vf_verified/kernel_test/square_reduce_sum_test/square_reduce_sum_custom.cpp
  - /path/vf_verified/kernel_test/square_reduce_sum_test/test_square_reduce_sum.py
  - /path/vf_verified/kernel_test/square_reduce_sum_test/vf_lesson.md
test_summary: 10/10 cases passed, max_diff=1.2e-6

## RETURN: status=COMPLETED, phase=vf-test, vf_status=passed, code_modified=true, error_type=
```

**精度失败（Driver 可重试）：**
```markdown
## VF_TEST_RESULT
status: FAILED
vf_func: SquareReduceSum
error_info: |
  精度失败：shape=[3,100] max_diff=0.0153 > atol=1e-5
  可能原因：尾块 mask 处理有误（UpdateMask 累积模式误用 ZEROING）
output_paths:
  - /path/vf_verified/kernel_test/square_reduce_sum_test/square_reduce_sum_custom.cpp
  - /path/vf_verified/kernel_test/square_reduce_sum_test/test_square_reduce_sum.py

## RETURN: status=COMPLETED, phase=vf-test, vf_status=failed, code_modified=true, error_type=PREC
```

**环境错误（硬失败）：**
```markdown
## VF_TEST_RESULT
status: FAILED
vf_func: SquareReduceSum
error_info: NPU 设备不可用：DeviceInfo Health=CRITICAL
output_paths: []

## RETURN: status=FAILED, phase=vf-test, vf_status=failed, code_modified=false, error_type=ENV
```

---

## 参考文档

### RegBase 编程参考
- `skills/regbase-vf-test/references/ascend_regbase_programing_guide.md` — 三层调用链、Hardware Loop、核心 API、寄存器管理、VF 融合
- `skills/regbase-vf-test/references/ascend950_hardware_and_pipeline_control.md` — 流水线同步与 PipeBarrier

### VF 指令参考
- `skills/regbase-vf-test/references/vf-instructions/` — INDEX.md（决策树）+ cast/interleave/load-align/store-align/ub-basics 单指令语义

### 示例代码
- `skills/regbase-vf-test/references/examples/` — muls/adds/reducesum/mul/duplicate/broadcast/cast/abs/rsqrt/sigmoid/reducemax `.cpp` 模板 + `test_*.py` 脚本

### VF 类别经验库
- `skills/regbase-vf-test/references/vf_experiences/` — 按 VF 计算模式组织的类别条目（`{类别}/INDEX.md` + `experience-*.md`），跨算子复用

### 工具链
- `skills/regbase-vf-test/SingleOperatorLaunch/` — SourceModule / DeviceInfo / pack_tiling_data / diagnostics(OOB)，PYTHONPATH 引用
- `skills/regbase-vf-test/references/ascend_basic_ub_knowledge.md` — UB 搬入搬出知识
- `skills/regbase-vf-test/references/multi-dtype-numpy.md` — 多 dtype numpy 支持（dtype 构造、4-bit 打包、golden 比较）

### 调用链上游
- `skills/regbase-vf-test/SKILL.md` — 工具链与参考文档的来源（本 skill PYTHONPATH/Read 引用其资产，不 invoke）
- A5 Regbase precision-debug 编排独立 L4 文档 — Driver 注入本 skill 的 prompt 模板与状态机
- `skills/ascendc-precision-kernel-debug/SKILL.md` — 上游 kernel_debug 阶段，产出 `vf_functions`（name/function/evidence）触发本 skill
