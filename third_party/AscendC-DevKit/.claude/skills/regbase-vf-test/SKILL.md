---
name: regbase-vf-test
description: >
  用于编写 Ascend950 RegBase 的 VF 函数（SIMD `__simd_vf__` 与 SIMT `__simt_vf__` 两种模式），
  实现单元测试，调试以实现精度正确。
  不直接被调用——由 ascendc-vf-test-agent 作为唯一直接调用方 invoke。
argument-hint: >
  输入：output_dir 目录路径；vf_mode（simd/simt）；需要单元测试的 VF 函数功能，
  输入输出变量的 UB shape 情况
  输出：单元测试报告；单元测试 python 脚本。
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
skills:
  - ascendc-dev-knowledge
---

> **直接调用方限定**
>
> 本 Skill **不直接被调用**。`ascendc-vf-test-agent`（`agents/ascendc-vf-test-agent.md`）是**唯一直接 invoke 本 Skill 的 Agent**。其他任何 Agent / 开发者 / 上层流程均不直接 invoke 本 Skill，统一通过 `ascendc-vf-test-agent` 间接访问。
>
> **调用链路**（本 Skill 处于链路最低层，上层可有多种调用方）：
> - **上层调用方**（如 `ascendc-dev` 主 SKILL、开发者独立调试等）→ 调度 `ascendc-vf-test-agent`
> - `ascendc-vf-test-agent`（SubAgent）→ invoke 本 Skill（`regbase-vf-test`）
> - 任何上层调用方均**不直接 invoke 本 Skill**——统一经 `ascendc-vf-test-agent` 间接访问
>
> **典型使用场景**（用途有两种，但入口统一——都经 `ascendc-vf-test-agent`）：
> - **A5 Regbase 算子开发**（`ascendc-dev` 主流程内 `.VT.{M}` 步骤）：对 Compute 中每个 VF 函数逐个做精度预验证，产物落到 `$RECORD_DIR/vf_verified/kernel_test/`，供 s4-coding 集成 Compute 时使用（详见 `agents/ascendc-dev-s4-coding.md` §4.7）
> - **独立调试 VF 函数**：开发者触发 `ascendc-vf-test-agent` 并指定 `output_dir` + VF 规格（按 §3 表格填入输入输出名、UB shape、dtype），无需进入 `ascendc-dev` 算子开发主流程
>
> **不适用场景**：
> - A2 / A3 Membase 算子（应改用 `ascendc-testing` Simple / ATK / TTK 模式）
> - 完整算子（非单 VF 函数）的端到端测试（应改用 `ascendc-testing`）

# RegBase VF 单元测试 Skill

## 1, 概述

本 Skill 用于在 Ascend950 上对 RegBase 编写的 VF 函数进行单元测试，确保该 VF 函数精度正常。通过封装 AscendC 代码，实现从 python 直接完成算子编译和 NPU 环境运行。

**两种编程模式，规则互不通用**：VF 函数可能是 **SIMD（`__simd_vf__`，Reg 矢量计算）** 或 **SIMT（`__simt_vf__`，线程级并行）**。调用方必须显式传入 `vf_mode`；本 Skill 按模式走各自的示例、经验、指令/编程参考与约束（对照见 `references/simt/INDEX.md`）。

**核心目标**
- 验证 VF 函数的计算逻辑正确性
- 提供快速单元测试

## 2. 前提条件

1. 检查 `ttk` 并确保 `SingleOperatorLaunch` 可用

`SingleOperatorLaunch` 依赖 `ttk`，先检查 `ttk` 是否存在，禁止主动安装。

```bash
python3 -m ttk info
```

`SingleOperatorLaunch` 在 `skills/regbase-vf-test/SingleOperatorLaunch` 中，确保可用：

```bash
python -c "import SingleOperatorLaunch"
```

2. CANN 环境已正确配置（`ASCEND_HOME_PATH` 等）

## 2.1 调用参数接口（由 ascendc-vf-test-agent 传入）

本 Skill 由 `ascendc-vf-test-agent` 唯一调用，调用方必须传入以下参数：

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `record_dir` | string | 是 | 开发记录目录绝对路径，用于从 `meta.json` 读取 `ub_size`（UB 容量约束用） |
| `output_dir` | string | 是 | VF 验证根目录绝对路径，产物写入 `{output_dir}/kernel_test/` |
| `vf_mode` | string | **是** | VF 编程模式：`"simd"`（`__simd_vf__`，Reg 矢量计算）或 `"simt"`（`__simt_vf__`，线程级并行）。决定走哪套示例/经验/编程参考/合规约束 |
| `vf_function_name` | string | 是 | 原始 VF 函数名，仅用于日志、错误信息、历史记录 |
| `vf_func_snake` | string | 是 | snake_case 后的函数名，必须作为目录和文件名的基名 |
| `input_shapes` | list[dict] | 是 | 输入变量规格，schema 见下 |
| `output_shapes` | list[dict] | 是 | 输出变量规格，schema 见下 |
| `dtype_combinations` | list[dict] | **是** | 该 VF 必须验证的输入/输出 dtype 组合矩阵，schema 见下 |
| `vf_instruction_hints` | string (JSON) | 否 | 由调用方预查询 VF 指令/编程参考获得的关键结论，供生成本 VF 时优先遵循 |

`input_shapes` / `output_shapes` 元素 schema：

```json
{
  "name": "x",
  "io": "input",
  "shape": [2, 128],
  "dtype": "float32"
}
```

`dtype_combinations` 元素 schema：

```json
{
  "inputs": {"x": "float16"},
  "outputs": {"y": "float32"}
}
```

字段说明：
- `name`：变量名，与 `coding_index.md` 底部规格表一致；
- `io`：固定为 `"input"` 或 `"output"`；
- `shape`：整数列表，表示该变量在 UB 中的 shape（如一维 `[128]`、二维 `[2, 128]`）；
- `dtype`：数据类型，使用 numpy 风格字符串（`float32` / `float16` / `int32` 等）；
- `dtype_combinations`：必填，列出该 VF 必须支持的所有合法 dtype 组合。**skill 必须对该矩阵中每种组合都生成独立测试用例并验证精度**。即使只有一种组合，也须以单元素列表传入。

### 产物路径约定

所有产物必须放在：

```text
{output_dir}/kernel_test/{vf_func_snake}_test/
├── {vf_func_snake}_custom.cpp   # AscendC Kernel 源码
└── test_{vf_func_snake}.py      # Python 测试脚本
```

**禁止**使用 `vf_function_name` 作为目录名或文件名基名，否则上层 agent 的产出检查会失败。

### UB 容量读取

测试用例设计前，必须获取硬件 UB 大小：

1. 从 `{record_dir}/meta.json` 的 `ub_size` 字段（bytes，CodegenStage 写入）读取；
2. 整体 `pipe.InitBuffer` 总分配量必须满足 `< ub_size - 1KB`；
3. `ub_size` 缺失或为 0 时，回退默认值 248KB（253952）。

## 3. 核心工作逻辑

**0. 确认编程模式（`vf_mode`）并分流**：调用方已传入 `vf_mode`（`simd`/`simt`）。本 Skill 全流程按模式路由：

| 环节 | SIMD（`simd`） | SIMT（`simt`） |
|------|----------------|----------------|
| 示例参考 | `references/examples/`（§5.2 列表） | `references/examples_simt/`（§5.2 SIMT 列表） |
| 编程/指令参考 | `references/vf-instructions/` + `references/a5-api-enhanced/` | `references/simt/`（INDEX.md 导航） |
| 历史经验 | `vf_experiences/{类别}/` 通用条目（横切标签 `mask-tail`/`unaligned-2d` 等） | `vf_experiences/{类别}/` 中 SIMT 条目（横切标签 `simt-async`，gather-scatter 类别集中） |
| VF 函数体 | `__simd_vf__`：RegTensor + LoadAlign/StoreAlign + UpdateMask + uint16 硬件循环 | `__simt_vf__`：裸 `__gm__`/`__ubuf__` 指针 + threadIdx/blockIdx 映射 + stride 循环 |
| 数据搬入搬出 | GM→UB(MTE2)→VF→UB→GM(MTE3) | SIMT 可直读写 GM（DCache）；经 UB 时受 8KB 窗口约束 |
| 同步 | `LocalMemBar`（VF 内） | `SetFlag/WaitFlag<HardEvent::MTE2_V/V_MTE3>`（kernel 层） |

1. 从传入参数 `input_shapes` / `output_shapes` / `dtype_combinations` 中确认 VF 函数的输入输出及必须覆盖的 dtype 组合。示例如下：
    | name | io | shape | dtype |
    | ---- | ---- | ----- | ----- |
    | x | input | [m, nAlign] | float32 |
    | y | output | [m] | float32 |

    `dtype_combinations` 示例：
    | 组合 | inputs | outputs |
    | ---- | ------ | ------- |
    | 1 | {x: float16} | {y: float32} |
    | 2 | {x: bfloat16} | {y: float32} |
    | 3 | {x: float32} | {y: float32} |
2. 准备对应的 golden 实现方案
3. **检索历史 VF 经验**（每个 VF 都执行，包括同算子的第一个 VF）：按当前 VF 的**计算模式**定位经验库类别——先读 `$SKILL_ROOT/references/vf_experiences/{类别}/INDEX.md` 判据（cast / dequant-quant / elementwise / reduce / gather-scatter / layout / sort-select / stateful-accumulator），再读该类别下匹配的 `experience-*.md` 条目，提取相近 VF 的实现要点、问题与解决办法、可复用模式（详见 §5.3）。**按计算语义匹配，不按算子名匹配**；横切关注（SIMT 异步 / 对齐 / 多 dtype / mask-tail）通过条目横切标签定位。**SIMT VF 额外必读** `$SKILL_ROOT/references/simt/INDEX.md`（编程模型/内存/同步/坑位，见 §5.7）。
4. 在 `{output_dir}/kernel_test/{vf_func_snake}_test/` 目录下创建测试脚本
    - 目录名和文件名必须基于 `vf_func_snake`
     - 参考 `$SKILL_ROOT/SingleOperatorLaunch/` 下的 example 和 README.md
    - **脚本顶部必须包含稳健自举（self-bootstrap）**，这是硬性要求，不是可选：
        - 把 `$SKILL_ROOT/SingleOperatorLaunch` 加入 `sys.path`；
        - 部分环境 `PathFinder` 会被 editable finder 破坏、`sys.path` 目录搜索失效（表现：`sys.path.insert` 后 `from SingleOperatorLaunch import ...` 仍 `ModuleNotFoundError`）——此时必须用 `importlib` 按文件路径注册包绕过（见下方代码块）；
      ```python
      import importlib.util, os, sys
      # 生成脚本时用 $SKILL_ROOT 解析出的实际路径（绝对路径或到 skill 的正确相对路径）
      _SOL_DIR = "<SKILL_ROOT>/SingleOperatorLaunch"
      if _SOL_DIR not in sys.path:
          sys.path.insert(0, _SOL_DIR)
      if "SingleOperatorLaunch" not in sys.modules:
          _spec = importlib.util.spec_from_file_location(
              "SingleOperatorLaunch",
              os.path.join(_SOL_DIR, "__init__.py"),
              submodule_search_locations=[_SOL_DIR],
          )
          _mod = importlib.util.module_from_spec(_spec)
          sys.modules["SingleOperatorLaunch"] = _mod
          _spec.loader.exec_module(_mod)
      from SingleOperatorLaunch import DeviceInfo, SourceModule, pack_tiling_data
      ```
    - **编译产物目录（kernel_meta）策略**：`SourceModule` 默认把 `kernel_meta` 放在调用脚本所在目录（不是 cwd），并在每次编译前清理该 kernel 的旧产物（fresh-build，防止"改源码后仍跑旧二进制"）。测试脚本应**显式** `SourceModule(..., kernel_meta=os.path.join(os.path.dirname(os.path.abspath(__file__)), "kernel_meta"))`，并可在重跑前清理该目录。**禁止依赖 cwd 下的 `kernel_meta`**——agent 运行时 cwd 可能与脚本目录不一致，且无法被清理。
5. 完成测试数据的搬入搬出与 VF 编写，**按 `vf_mode` 走对应参考**：
   - **SIMD**：参考 `$SKILL_ROOT/references/ascend_basic_ub_knowledge.md`（GM→UB→Reg→UB→GM 搬运）；涉及 VF 指令组合模式与单指令语义时参考 `$SKILL_ROOT/references/vf-instructions/`（详见 §5.4）；**调用具体 RegBase API 时优先查阅 `$SKILL_ROOT/references/a5-api-enhanced/`**（含完整调用示例，详见 §5.5），找不到再去 `ascendc-dev-knowledge` 查官方 API 签名。
   - **SIMT**：参考 `$SKILL_ROOT/references/simt/`（§5.7）——`simt-programming-model.md`（两层结构 + `asc_vf_call` + `cce::dim3` + `__launch_bounds__`）、`simt-memory-access.md`（GM 直读写 / 8KB UB 窗口 / 指针转换）、`simt-sync.md`（`SetFlag/WaitFlag<HardEvent>`）、`simt-pitfalls.md`。kernel 入口 `extern "C" __global__ __aicore__`，体内用 `asc_vf_call<SimtImpl>(cce::dim3(256), ...)` 启动；`__simt_vf__` 需 `#include "simt_api/common_functions.h"`。
6. **对 `dtype_combinations` 中每种 dtype 组合生成独立测试用例**：
    - 测试脚本必须能遍历所有 dtype 组合，每种组合构造对应 dtype 的 numpy 输入/输出数组；当 dtype 为 `bfloat16 / int4 / float8 / float4` 等非原生 numpy 类型时，必须使用 `ttk.utilities.dtypes` 提供的构造器和转换函数（详见 §6.3 多 dtype numpy 支持）。
    - 若 VF 函数签名使用模板参数（如 `template <typename DX>`），测试脚本应按组合实例化为具体 dtype 的 kernel 并分别编译运行。
    - **禁止只测 `input_shapes`/`output_shapes` 中默认 dtype 对应的一种组合**；`dtype_combinations` 是验证契约，必须全覆盖。
7. 结合第 3 步检索到的历史经验，按 `vf_mode` 对应的编程模型完成 VF 函数的编写，完成精度调试。**精度是否达标一律以 §6.6 定义的生态精度判定为准**（`SingleOperatorLaunch.precision_check.compare_tensor`，MERE/MARE + per-dtype 阈值）；测试脚本里**禁止**再手写 `np.allclose(..., rtol=..., atol=...)` 作为过/不过判据（只可用作调试打印）。
8. 若测试通过（`STATUS=COMPLETED`），生成 VF 函数经验总结文档 `vf_lesson.md`（本算子内过程资产，供同算子后续 VF 接力，详见 §5.3）：
   - 记录函数职责、输入输出规格、分层结构
   - 记录实现要点（SIMD：mask 策略、对齐/非对齐处理、标量传递、归约折叠等；SIMT：线程映射/stride、GM 直写或 8KB 窗口、HardEvent 同步、寄存器预算等）
   - 记录本次开发中遇到的问题及解决办法
   - 记录可复用的代码模式与参考示例
   - 写入路径：`{output_dir}/kernel_test/{vf_func_snake}_test/vf_lesson.md`
9. **归档（必须，非推荐）**：将本次验证中**新增/修正的类别级经验**提炼归约到经验库对应类别条目 `$SKILL_ROOT/references/vf_experiences/{类别}/experience-*.md`（先读该类别 `INDEX.md` 判据确定类别；同类别同类目**并入既有条目**，不按算子新建文件）。归档原则：
   - **只沉淀抽象经验**（判据/实现要点/坑位与对策/最小骨架），**不放完整源码答案**（整段 VF 函数体 / kernel 入口 / 算子专属链）
   - 条目末尾保留 `实证来源`（**仅算子/函数标识，禁绝对路径**）：`{op} {vf_func}（{通过数}/{总}，max_diff=...）`，供追溯该经验出自哪类验证
   - **绝对路径禁令**：条目内（实证来源、坑位、要点、可复用模式各处）**禁止出现生成环境的绝对路径**（`/home/...`、`/app/...`、`$RECORD_DIR` / `$SKILL_ROOT` / 运行目录展开后的绝对路径等）；需要指向过程资产时用**相对**引用 `vf_verified/kernel_test/{vf_func_snake}_test/vf_lesson.md`（相对算子 record dir），或只写算子/函数标识不写路径
   - 不复制编译产物（`kernel_meta/`、`*.o`、`*.so`）；`vf_lesson.md` 只留算子 record dir（过程资产），不复制进经验库
   - **SIMT 新增/修正的类别级经验**并入 `vf_experiences/{类别}/` 对应条目时保留 `simt-async` 横切标签，供 SIMT VF 检索定位

## 4. 返回格式

本 Skill 执行完毕后，必须在最终回复的**前 5 行内**输出机器可读标记：

```markdown
## RETURN: status={STATUS}, error_type={ERROR_TYPE}
```

### STATUS

| 值 | 含义 |
|---|---|
| `COMPLETED` | 测试通过 |
| `FAILED` | 测试失败 / 编译失败 / 环境错误 / 其他错误 |

### ERROR_TYPE

`status=FAILED` 时必填，`status=COMPLETED` 时留空：

| 值 | 含义 | 触发场景 |
|---|---|---|
| `PREC` | 精度失败 | `precision_check` 生态精度判定未通过（MERE/MARE + per-dtype 阈值） |
| `COMPILE` | 编译失败 | kernel 编译报错 |
| `ENV` | 环境错误 | NPU 不可用、CANN 未配置、设备 Health 非 OK、PYTHONPATH 缺失等 |
| `OTH` | 其他错误 | 无法归入以上类别 |

### 返回前必须附加的信息

`status=COMPLETED` 时，在 `## RETURN:` 行之前输出：

```markdown
## VF_TEST_RESULT
status: COMPLETED
output_paths:
  - {output_dir}/kernel_test/{vf_func_snake}_test/{vf_func_snake}_custom.cpp
  - {output_dir}/kernel_test/{vf_func_snake}_test/test_{vf_func_snake}.py
  - {output_dir}/kernel_test/{vf_func_snake}_test/vf_lesson.md
dtype_combinations:
  - inputs: {{x: float16}}
    outputs: {{y: float32}}
    passed: true
    max_diff: 1.2e-6
  - inputs: {{x: bfloat16}}
    outputs: {{y: float32}}
    passed: true
    max_diff: 1.5e-6
test_summary: {passed}/{total} cases passed, max_diff={max_diff}
```

`status=FAILED` 时，在 `## RETURN:` 行之前输出：

```markdown
## VF_TEST_RESULT
status: FAILED
error_type: {ERROR_TYPE}
error_info: |
  {一句话概括错误}
  {关键日志片段或 max_diff}
dtype_combinations:
  - inputs: {{x: float16}}
    outputs: {{y: float32}}
    passed: false
    max_diff: 0.01
output_paths:
  - {output_dir}/kernel_test/{vf_func_snake}_test/{vf_func_snake}_custom.cpp
  - {output_dir}/kernel_test/{vf_func_snake}_test/test_{vf_func_snake}.py
  - {output_dir}/kernel_test/{vf_func_snake}_test/vf_lesson.md
```

即使失败，也应输出已生成的产物路径（如果已生成），方便 agent 做合规性检查或调试。失败时若 `vf_lesson.md` 尚未生成，可省略该路径。

### 示例

**测试通过：**

```markdown
## VF_TEST_RESULT
status: COMPLETED
output_paths:
  - /path/to/vf_verified/kernel_test/square_reduce_sum_test/square_reduce_sum_custom.cpp
  - /path/to/vf_verified/kernel_test/square_reduce_sum_test/test_square_reduce_sum.py
  - /path/to/vf_verified/kernel_test/square_reduce_sum_test/vf_lesson.md
dtype_combinations:
  - inputs: {x: float16}
    outputs: {y: float32}
    passed: true
    max_diff: 1.2e-6
  - inputs: {x: float32}
    outputs: {y: float32}
    passed: true
    max_diff: 9.0e-7
test_summary: 10/10 cases passed, max_diff=1.2e-6

## RETURN: status=COMPLETED, error_type=
```

**编译失败：**

```markdown
## VF_TEST_RESULT
status: FAILED
error_type: COMPILE
error_info: |
  Kernel 编译失败：error in backend: Do not know how to split the result of this operator!
  可能原因：__simd_vf__ 函数未标记 inline 或 RegTensor 数量超限
output_paths:
  - /path/to/vf_verified/kernel_test/square_reduce_sum_test/square_reduce_sum_custom.cpp
  - /path/to/vf_verified/kernel_test/square_reduce_sum_test/test_square_reduce_sum.py

## RETURN: status=FAILED, error_type=COMPILE
```

**精度失败：**

```markdown
## VF_TEST_RESULT
status: FAILED
error_type: PREC
error_info: |
  精度验证失败：shape=[3, 100] 时 MARE=0.0153 > mare_threshold=9.77e-3（float16），max_diff=0.0153
  可能原因：尾块 mask 处理有误
output_paths:
  - /path/to/vf_verified/kernel_test/square_reduce_sum_test/square_reduce_sum_custom.cpp
  - /path/to/vf_verified/kernel_test/square_reduce_sum_test/test_square_reduce_sum.py

## RETURN: status=FAILED, error_type=PREC
```

**环境错误：**

```markdown
## VF_TEST_RESULT
status: FAILED
error_type: ENV
error_info: |
  NPU 设备不可用：DeviceInfo 显示 device 0 Health=CRITICAL
output_paths: []

## RETURN: status=FAILED, error_type=ENV
```

## 5. 参考文档

### 5.1 RegBase 编程参考

编写 VF 测试代码前，**先按 `vf_mode` 分流**：

- **SIMD（`vf_mode="simd"`）**：阅读以下 RegBase 核心知识：
  - **`$SKILL_ROOT/references/ascend_regbase_programing_guide.md`** — 三层调用链（`__aicore__` → `__simd_vf__` → `__simd_callee__`）、Hardware Loop 规范、核心 API（`UpdateMask`、`LoadAlign`、`StoreAlign` 等）、寄存器管理、VF 融合优化
  - **`$SKILL_ROOT/references/ascend950_hardware_and_pipeline_control.md`** — 流水线同步与 PipeBarrier 使用规范
- **SIMT（`vf_mode="simt"`）**：阅读 `$SKILL_ROOT/references/simt/`（§5.7）——编程模型/内存/同步/坑位自成体系。

**单元测试中的 VF 函数**：
- SIMD：`__aicore__` 层作为 Python 调用侧入口，`__simd_vf__` 层作为实际被编译为 VF 的测试目标。
- SIMT：`__aicore__` 层作为 Python 调用侧入口（kernel 入口），`__simt_vf__` 层经 `asc_vf_call` 启动的测试目标。

### 5.2 示例代码参考

编码 VF 函数前，先分析当前 VF 函数计算特点，然后**按 `vf_mode` 选示例目录**：

- **SIMD** → `$SKILL_ROOT/references/examples/`
- **SIMT** → `$SKILL_ROOT/references/examples_simt/`

该目录下每个算子示例包含：

- `{op}.cpp`：AscendC Kernel 源码，展示 VF 函数实现、数据搬运模式（SIMD：mask 管理；SIMT：线程映射/stride/同步）。
- `test_{op}.py`：配套 Python 测试脚本，展示 `SingleOperatorLaunch` 编译、tiling 打包与精度验证用法。
- 部分算子仍保留辅助头文件（如 `cast_common.h`），用于类型转换等公共工具函数。

**SIMD 示例**（`references/examples/`）：
- **`$SKILL_ROOT/references/examples/muls.cpp`** / **`test_muls.py`** — 标量乘法 (MulsRegImpl)，展示基本的 `__simd_vf__` → `__aicore__` 两层结构、mask 处理、LoadAlign/StoreAlign 用法
- **`$SKILL_ROOT/references/examples/adds.cpp`** / **`test_adds.py`** — 标量加法 (AddsRegImpl)，与 muls 类似的标准二元标量运算模板
- **`$SKILL_ROOT/references/examples/reducesum.cpp`** / **`test_reducesum.py`** — 归约求和 (ReduceSumImpl)，展示多路分支处理（cols <= vl / vl < cols <= 2vl / cols > 2vl）、二分累加折叠、tmp 缓冲区使用
- **`$SKILL_ROOT/references/examples/mul.cpp`** / **`test_mul.py`** — 逐元素乘法
- **`$SKILL_ROOT/references/examples/duplicate.cpp`** / **`test_duplicate.py`** — 广播填充
- **`$SKILL_ROOT/references/examples/broadcast.cpp`** / **`test_broadcast.py`** — 广播运算
- **`$SKILL_ROOT/references/examples/cast.cpp`** / **`test_cast.py`** / **`cast_common.h`** — 类型转换。**涉及任何 dtype 转换时先读 [`cast_index.md`](references/examples/cast_index.md)**（速查表 + Trait 全集 + 红线 + 搬运模板：源→目标 dtype 一行定位 helper + 行号）。各 helper 的**使用场景/代码片段/红线已内联在 `cast_common.h` 对应函数上方注释**，写代码时 Read 头文件即得完整上下文（**一次整读后本会话内复用，勿多轮反复整读**）。`LoadTensorForDtypeTIn` / `StoreTensorForDtypeTOut` / `LoadScalarForDtypeTIn` 三件套已覆盖 fp32/fp16/bf16/int8/int32/fp8/hifp8/fp4，可优先直接调用或整段复制；也可自行写 `Cast<>`（4B→2B 窄化尤其易错，见 cast_index.md §6 红线）
- **`$SKILL_ROOT/references/examples/abs.cpp`** / **`test_abs.py`** — 绝对值
- **`$SKILL_ROOT/references/examples/rsqrt.cpp`** / **`test_rsqrt.py`** / **`rsqrt.h`** — 反平方根
- **`$SKILL_ROOT/references/examples/sigmoid.cpp`** / **`test_sigmoid.py`** / **`sigmoid.h`** — Sigmoid 激活
- **`$SKILL_ROOT/references/examples/reducemax.cpp`** / **`test_reducemax.py`** — 归约取最大

这些示例文件（`.cpp`）均采用 `CustomRegImpl` 命名空间，包含完整的函数签名、mask 管理、数据搬运模式，可直接作为编写对应 VF 函数的模板。

**SIMT 示例**（`references/examples_simt/`）：
- **`$SKILL_ROOT/references/examples_simt/gather.cpp`** / **`test_gather.py`** — 间接读 gather：线程每行 + stride 循环、GM 直读直写（index 表 + 输入矩阵）、越界钳制；含 `[20001,1023]` + 12288 行参考规模
- **`$SKILL_ROOT/references/examples_simt/adds.cpp`** / **`test_adds.py`** — 逐元素标量加：线程每元素 + stride 循环、GM 直写，与 SIMD `adds` 对应的 SIMT 模板
- **`$SKILL_ROOT/references/examples_simt/scatter.cpp`** / **`test_scatter.py`** — 间接写 scatter：线程每元素 + 越界钳制；与 gather 互为反向

这些 SIMT 示例（`.cpp`）均采用 `CustomRegImpl` 命名空间，展示 `__simt_vf__ __launch_bounds__(256)` + `asc_vf_call`(cce::dim3) + 线程映射/stride 循环 + GM 直写模式，可直接作为编写 SIMT VF 的模板。完整结构模板见 `references/simt/simt-examples-map.md`。

### 5.3 VF 历史经验（过程资产 vf_lesson.md + 终态类别经验库）

**两类资产，职责不同**：

- **过程资产 `vf_lesson.md`**：每个 VF 测试通过后必须生成在 `{output_dir}/kernel_test/{vf_func_snake}_test/vf_lesson.md`。它是本算子开发**过程中**的记录，供同算子后续 VF 接力（`previous_vf_results`、s2/s4 兄弟目录 Glob）使用。**不复制进经验库**。
- **终态经验库 `$SKILL_ROOT/references/vf_experiences/`**：跨算子/跨 session 复用的类别级抽象经验。**按 VF 计算模式组织**（非按算子）：

```
references/vf_experiences/
  cast/            # 类型转换/位宽（INDEX.md + experience-*.md）
  dequant-quant/   # FP8/FP4 反量化
  elementwise/     # 逐元素/标量
  reduce/          # 归约/累加
  gather-scatter/  # 索引聚集（含 SIMT 异步基础设施，跨类别共享）
  layout/          # 布局变换
  sort-select/     # 排序/选择（构键/bitonic/双流）
  stateful-accumulator/  # 状态张量生命周期（init 填充 / rmw 累加）
```

#### 检索（两个层次，对所有 VF 均生效，包括同算子的第一个 VF）

- **层次 A：经验库检索（跨算子/跨 session，§3 步骤 3 执行）**：按当前 VF 的**计算模式**定位类别——先读 `{类别}/INDEX.md` 判据（含指令链选型、结构模板、常见陷阱），再读匹配的 `experience-*.md` 条目。**匹配锚点是计算语义/结构信号，不是算子名或函数名**；横切关注（SIMT 异步共享内存窗口 / 非对齐 / 多 dtype / mask-tail）按条目横切标签定位。**SIMT VF 优先匹配 `simt-async` 标签条目**（gather-scatter 类别集中：`experience-simt-async-infra.md`、`experience-simt-gather.md`）。
- **层次 B：算子内接力（`previous_vf_results`，仅非首 VF 生效）**：`ascendc-vf-test-agent` 通过 `previous_vf_results` 读取**同一算子本次开发**中已通过 VF 的 `vf_lesson.md`（过程资产），作为上下文补充。

> 两层次互补：层次 A 提供跨算子的类别级长期沉淀，层次 B 提供本算子内的近期接力。检索结论应与对应模式的参考交叉校验：SIMD 对照 `vf-instructions/`，SIMT 对照 `references/simt/`；若与参考语义冲突，以参考为准。

#### 归档规则（vf 测试通过后）

1. `vf_lesson.md` 保留在 `{output_dir}/kernel_test/{vf_func_snake}_test/`（过程资产，算子内接力用）。
2. **提炼归约**本次验证中**新增/修正的类别级经验**进对应类别条目：
   - 先读 `{类别}/INDEX.md` 判据确定类别（本 VF 的计算模式）；
   - 同类目经验**并入既有 `experience-*.md` 条目**（补坑位/补模式/补证据），**不按算子新建文件**；
   - 条目只承载抽象经验（判据/要点/坑位与对策/最小骨架），**不放完整源码答案**；
   - 条目末尾更新 `实证来源`（**仅算子/函数标识，禁绝对路径**）：`{op} {vf_func}（{通过数}/{总}，max_diff=...）`；
   - **绝对路径禁令**：条目内禁止出现生成环境的绝对路径（`/home/...`、`/app/...`、`$RECORD_DIR` / `$SKILL_ROOT` 展开后的绝对路径等）；指向过程资产用相对引用 `vf_verified/kernel_test/{vf_func_snake}_test/vf_lesson.md` 或不写路径。
3. 若某类别尚无对应条目，按 `INDEX.md` 模板新建 `experience-<主题>.md`。
4. 算子开发结束后无需批量同步——过程资产留在 record dir，终态经验已按 VF 随写随归。

### 5.4 VF 指令参考（组合模式与单指令语义）—— **SIMD 专用**

> **本目录仅适用于 SIMD（`vf_mode="simd"`）**。SIMT VF 无 Reg 指令组合，改用 `references/simt/`（§5.7）。先按 `vf_mode` 分流再查阅。

编写或调试 SIMD VF 函数前，根据当前 VF 函数的计算语义查阅 VF 指令参考文档，获取对应的 VF 指令组合模式、`CastTrait`、`LoadDist`/`StoreDist` 选型、Interleave 参数顺序等关键结论。参考文档位于 `$SKILL_ROOT/references/vf-instructions/`：

| 文件 | 内容 |
|------|------|
| `INDEX.md` | 组合模式、使用场景、决策树、常见陷阱、速查表、扩展指南 |
| `ub-basics.md` | UB 基础知识：内存层级、32B 对齐、DataCopyPad 1D/2D 搬运、各芯片 UB 大小及分配策略 |
| `cast.md` | `Reg::Cast`：多布局语义（ZERO/ONE/TWO/THREE/UNKNOWN）、类型转换寄存器扩展矩阵、`CastTrait` 声明模式及单指令用法。**要写 Cast 代码时先看 `references/examples/cast_index.md`**（速查定位 + 可直接搬运的 helper），cast.md 讲原理、index/reference 给代码 |
| `interleave.md` | `Reg::Interleave`：API 语义、粒度控制、参数顺序规则、原地用法、两级交错模式、Src0/Src1 参数顺序陷阱 |
| `load-align.md` | `Reg::LoadAlign`：单/双寄存器加载、`PostLiteral` 地址更新模式、`LoadDist` 广播/解交错/解包模式及地址对齐要求 |
| `store-align.md` | `Reg::StoreAlign`：单寄存器存储、`PostLiteral` 地址更新模式、`StoreDist` 模式、掩码用法及对齐要求 |

**查询方式**：

1. 先读 `INDEX.md`：用决策树（Section 4）定位所需流水线，再打开对应单指令文件查看精确语义。
2. 常见入口：
   - FP8/FP4 反量化、scale 预处理、布局转换 → 查 `INDEX.md` Section 1（组合模式）。
   - 具体指令签名与陷阱 → 查对应单指令文件（`cast.md` / `interleave.md` / `load-align.md` / `store-align.md`）。
3. 编码前务必对照 `INDEX.md` Section 3（常见陷阱）检查。

**与 §2.4 合规性检查的关系**：VF 指令参考提供指令语义/组合模式参考，不替代合规性检查；若查询结论与生成的代码存在偏差，以指令参考语义为准。

### 5.5 A5 RegBase API 增强文档（优先查阅）—— **SIMD 专用**

> **本目录仅适用于 SIMD（`vf_mode="simd"`）**（Reg 矢量计算 API）。SIMT VF 无 Reg API，改用 `references/simt/`（§5.7）。

本 Skill 本地预置了一套 A5 RegBase API 增强文档，位于 `$SKILL_ROOT/references/a5-api-enhanced/`。每个文档包含：

- **API 基础说明**：函数原型、模板参数、输入输出参数说明、约束条件（与官方文档一致）
- **调用示例**：完整可编译的代码示例，展示实际使用方式和参数传递模式
- **注意事项**：常见陷阱与最佳实践

**查找优先级（与官方 API 的关系）**：

| 参考源 | 关注点 | 优先级 |
|--------|--------|--------|
| `$SKILL_ROOT/references/vf-instructions/` | 本 Skill 沉淀的 VF 指令组合模式、常见陷阱、可复用代码模式 | **最高** — 编码实现时优先 |
| `$SKILL_ROOT/references/a5-api-enhanced/` | 增强版 API 文档：含完整调用示例、参数说明、约束条件 | **高** — 查阅具体 API 用法时优先使用 |
| `ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/` | 官方 API 精确签名、参数、约束、数据类型 | **兜底** — 增强文档中找不到时使用 |

**查询规则**：

1. 编写 VF 函数需要调用某个 RegBase API 时，**首先**在 `$SKILL_ROOT/references/a5-api-enhanced/` 中按 API 名称查找（如 `Muls.md`、`Cast.md`、`LoadAlign` 在 `load-align.md` 等）
2. 增强文档中找不到对应 API 时，**回退**到 `ascendc-dev-knowledge` 知识库查阅官方 API 签名
3. 若增强文档与官方文档存在冲突，以**增强文档**为准（增强文档经过实际验证和补充）

**文档结构与读取纪律（必须遵守，控制上下文开销）**：

> 每个 `a5-api-enhanced/*.md` 是**整档**：单文件 40~90KB / 700~1100 行。结构固定——前部（约 1~70/220 行，止于 `## 从 Ascend 950PR / arch35 算子源码提取的 {Api} 实例`）为 **API 本体**（产品支持情况 / 功能说明 / 函数原型 / 参数说明 / 约束说明 / 调用示例），后部为 **op 源码提取的"实例"区**（每个实例含完整可编译代码块，末尾常附 `{Api} 使用模式归纳`）。

- **禁止一次性整文件 `Read` 本目录文档**（实例区占文档主体但通常与当前 VF 无关）。历史上 argmax 归约 VF 单测一次整读 6 个大档（Select/Compare/Max/Arange/Reduce/ReduceDataBlock，合计 ~278KB）即为最大上下文开销来源。
- **正确读法**：
  1. 先 `Grep "^#### 函数原型|^#### 参数说明|^#### 约束说明|^## 从 Ascend|^### 实例|使用模式归纳" <file>` 取行号地图（实例标题自带算子+函数名，可判断相关性）；
  2. 只需 API 语义/签名/dtype 约束 → `Read` 首段：`offset=1, limit=<实例区起始行>-1`；
  3. 需真实用法实例 → 按行号地图只读命中实例行段；需归纳 → 只读末尾 `使用模式归纳` 段。
- 示例/经验等**小文件**（`vf-instructions/*.md`、`vf_experiences/*.md`、`examples/*.cpp` < 25KB）允许整读，但**同一文件不得多轮重复整读**（内容已在本轮上下文时直接复用）。

**当前覆盖的 API（72 个）**：

`Abs AbsSub Add AddC AddrReg Adds And Arange Axpy Cast CastTrait ClearSpr Compare Compares DeInterleave Div Duplicate Exp ExpSub Gather GatherB GetSpr Histograms Interleave LeakyRelu Ln LocalMemBar Log Log10 Log2 MaskMergeMode MaskReg Max Maxs Min Mins Move MoveMask Mul MulAddDst MulDstAdd Mull Muls MulsCast Neg Not Or Pack PairReduceElem PostLiteral Prelu Reduce ReduceDataBlock RegLayout RegTensor Relu RoundMode SatMode Scatter Select ShiftLeft ShiftLefts ShiftRight ShiftRights Sqrt Squeeze Sub SubC Truncate UnPack Unsqueeze Xor`

### 5.6 查询 A5 RegBase 官方 API（ascendc-dev-knowledge 知识库）

更多 Regbase 编程参考应通过同项目下的 `ascendc-dev-knowledge` skill。相关资料集中在：

```text
.claude/skills/ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/
```

#### 关键入口文档

| 路径 | 用途 |
|------|------|
| `910D_knowledge_extra/INDEX.md` | A5/RegBase 专属文档索引（2029 篇） |
| `910D_knowledge_extra/RegTensor.md` | RegTensor 数据类型与约束 |
| `910D_knowledge_extra/Reg数据搬运.md` | UB ↔ 寄存器搬运 |
| `910D_knowledge_extra/连续非对齐场景优化.md` | 非对齐寄存器缓存机制 |
| `api_reference_docs/SIMD_API/基础API/Reg矢量计算/寄存器数据类型/RegTensor.md` | 官方 `RegTensor` API 签名与示例 |
| `api_reference_docs/SIMD_API/基础API/Reg矢量计算/Reg数据搬运/` | `LoadAlign` / `StoreAlign` / `Move` 等 |
| `api_reference_docs/SIMD_API/基础API/Reg矢量计算/基础算术/` | `Add` / `Sub` / `Mul` / `Exp` / `Sqrt` / `Relu` 等 |
| `api_reference_docs/SIMD_API/基础API/Reg矢量计算/数据类型/CastTrait.md` | 类型转换 trait |

#### 与增强文档及本地 VF 指令参考的关系

完整的查找优先级与查询规则见 **§5.5**（增强文档 → 官方 API 的三级优先级体系）。本节的 `ascendc-dev-knowledge` 作为**兜底层**，仅在增强文档（`$SKILL_ROOT/references/a5-api-enhanced/`）中没有对应 API 时使用。**§5.5/§5.6 均为 SIMD Reg API；SIMT VF 的官方 API（`asc_syncthreads`/`asc_threadfence*`/`asc_atomic_*` 等）查 `ascendc-dev-knowledge/references/api_reference_docs/SIMT_API/`。**

### 5.7 SIMT VF 编程参考（自成体系）

> 本 Skill 为 SIMT（`vf_mode="simt"`）提供**独立成体系的编程参考**，位于 `$SKILL_ROOT/references/simt/`，与 SIMD 的 `vf-instructions/` 并列。SIMT VF 一律走本参考，不套用 SIMD 规则。

| 文件 | 内容 |
|------|------|
| `INDEX.md` | SIMD/SIMT 判据与核心差异对照表、文档导航、检索路径 |
| `simt-programming-model.md` | 两层结构（`__aicore__` wrapper → `__simt_vf__`）、线程架构/内置变量、`__launch_bounds__`、`asc_vf_call` + `cce::dim3`、`__simt_vf__`/`__simt_callee__` 约束 |
| `simt-memory-access.md` | GM 直读直写（DCache）、**SIMT UB 8KB 窗口硬约束**、对齐、地址空间指针 `uintptr_t` 中转 |
| `simt-sync.md` | `SetFlag/WaitFlag<HardEvent::MTE2_V/V_MTE3>`、TQue 不覆盖 async SIMT、线程级 `asc_syncthreads`/`asc_threadfence*` |
| `simt-pitfalls.md` | SIMT 高频坑位与对策表（8KB 越界、同步竞态、指针 cast、`dim3` 命名空间、寄存器预算等） |
| `simt-examples-map.md` | `references/examples_simt/` 样例清单、`.cpp`/`.py` 结构模板、SIMD/SIMT 样例对照 |

**SIMT 关键约束速查（与 SIMD 的本质差异）**：

| 约束 | SIMT |
|------|------|
| 硬件循环规则（`uint16_t`/无分支/步长 1） | **不适用**——普通 `uint32_t`/`uint64_t` 循环、运行时分支、指针下标均合法 |
| Mask/尾块（`UpdateMask`） | **不适用**——用 `if (threadIdx.x >= n) return;` 空转保护 |
| 32B 对齐（GM） | **不适用**——标量寻址自由；UB 消费方为 SIMD 时才需对齐 |
| UB 容量（InitBuffer < ub_size-1KB） | **替换为 8KB 窗口约束**：SIMT 可见 UB = 绝对 `[0,8192B)`；或 GM 直写避开 |
| 数据搬运（GM→UB→Reg→UB→GM） | **可直读写 GM**（DCache）；需走 UB 时排单 8KB 窗口 |
| 同步 | `SetFlag/WaitFlag<HardEvent>`（kernel 层）；VF 内无 Reg 同步 |
| 头文件 | `#include "simt_api/common_functions.h"`（`asc_vf_call` dim3 重载） |
| 启动 | `asc_vf_call<SimtImpl>(cce::dim3(256), __gm__ ptr..., __ubuf__ ptr..., 标量...)` |

## 6. 完整示例：VF 函数单元测试（MulsReg）

> 以下示例演示 SIMD VF（`MulsRegImpl`）的端到端单元测试。**SIMT VF 的端到端单元测试结构与此相同**（kernel 入口 `extern "C" __global__ __aicore__` + `SourceModule` + `test_*.py`），差异仅在 VF 层为 `__simt_vf__` + `asc_vf_call`——可直接参考 `references/examples_simt/gather.cpp` / `test_gather.py`（见 §5.2 SIMT 示例）。

以下示例演示如何使用 `SingleOperatorLaunch` 对 RegBase 编写的 `MulsRegImpl` 进行端到端单元测试。

> **示例与实际调用的关系**：以下示例以 `muls_reg` 演示完整流程。实际由 `ascendc-vf-test-agent` 调用时，`muls_reg` 应替换为传入的 `vf_func_snake`，且以下三者必须一致：
> - 文件名：`{vf_func_snake}_custom.cpp`
> - kernel 入口函数名：`{vf_func_snake}_custom`
> - `SourceModule` 的 `kernel_name="{vf_func_snake}_custom"`

### 6.1 目录结构

```
{output_dir}/kernel_test/muls_reg_test/
├── test_muls_reg.py          # Python 测试脚本
├── muls_reg_custom.cpp       # AscendC Kernel 源码
└── kernel_meta/              # 编译产物（自动生成）
```


### 6.2 AscendC Kernel 源码（从文件读取）

将 Kernel 源码保存到 `muls_reg_custom.cpp`，便于 IDE 语法高亮、文件修改：

```cpp
// muls_reg_custom.cpp
#include "kernel_operator.h"

using namespace AscendC;
constexpr uint32_t UB_BLOCK_SIZE = 32;

// ====== Tiling 结构体 ======
struct MulsRegTilingData {
    uint32_t totalLength;
    float    scalar;
};

// ====== 数据搬运辅助函数 ======
template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    uint8_t *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) {
        dst[i] = src[i];
    }
}

template <typename T>
__aicore__ inline void DataCopyInTensor1D(LocalTensor<T>& dst, GlobalTensor<T>& gm, uint64_t gmOffset,
        uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),
        static_cast<uint32_t>(len * sizeof(T)),
        static_cast<uint32_t>(0),
        static_cast<uint32_t>(0),
        0
    };
    DataCopyPadExtParams<T> padParams{
        false,
        static_cast<uint8_t>(0),
        static_cast<uint8_t>(0),
        static_cast<T>(0.0)
    };
    DataCopyPad(dst, gm[gmOffset], copyParams, padParams);
}

template <typename T>
__aicore__ inline void DataCopyOutTensor1D(GlobalTensor<T>& gm, LocalTensor<T>& src, uint64_t gmOffset,
        uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),
        static_cast<uint32_t>(len * sizeof(T)),
        static_cast<uint32_t>(0),
        static_cast<uint32_t>(0),
        0
    };
    DataCopyPad(gm[gmOffset], src, copyParams);
}

// ====== RegBase VF 实现 ======
constexpr uint32_t REPEAT_STRIDE_B32 = 64; // 256 / sizeof(float)

// Layer 2: __simd_vf__ — 融合循环层
template <typename T>
__simd_vf__ inline void MulsRegImpl(__ubuf__ T *dst, __ubuf__ T *src, T scalarValue,
    const uint32_t calCount)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    uint32_t count = calCount;
    AscendC::Reg::MaskReg mask;
    uint16_t repeatTime = static_cast<uint16_t>(
        (calCount + REPEAT_STRIDE_B32 - 1) / REPEAT_STRIDE_B32);

    for (uint16_t i = 0; i < repeatTime; ++i) {
        mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTensor<T>::trait>(count);
        AscendC::Reg::LoadAlign(srcReg, src + i * REPEAT_STRIDE_B32);
        AscendC::Reg::Muls<T, T, AscendC::Reg::MaskMergeMode::ZEROING>(
            dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dst + i * REPEAT_STRIDE_B32, dstReg, mask);
    }
}

// Layer 1: __aicore__ — 调度层
template <typename T>
__aicore__ inline void MulsImpl(const AscendC::LocalTensor<T> &dst,
    const AscendC::LocalTensor<T> &src, const T &scalarValue,
    const int32_t calCount)
{
    __ubuf__ T *dstUb = (__ubuf__ T *)dst.GetPhyAddr();
    __ubuf__ T *srcUb = (__ubuf__ T *)src.GetPhyAddr();
    MulsRegImpl<T>(dstUb, srcUb, scalarValue, static_cast<uint32_t>(calCount));
}

// ====== Kernel 入口 ======
extern "C" __global__ __aicore__ void muls_reg_custom(
    GM_ADDR x, GM_ADDR y, GM_ADDR workspace, GM_ADDR tiling)
{
    MulsRegTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);

    uint32_t blockLength = tilingData_.totalLength / GetBlockNum();
    uint32_t blockLengthAlign = AscendC::CeilDivision(
        blockLength * sizeof(float), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(float);

    TPipe pipe;
    TQue<TPosition::VECIN, 1> inQueueX;
    TQue<TPosition::VECOUT, 1> outQueueY;
    GlobalTensor<float> xGm;
    GlobalTensor<float> yGm;

    xGm.SetGlobalBuffer((__gm__ float*)x + blockLength * GetBlockIdx(), blockLength);
    yGm.SetGlobalBuffer((__gm__ float*)y + blockLength * GetBlockIdx(), blockLength);

    pipe.InitBuffer(inQueueX, 1, blockLengthAlign * sizeof(float));
    pipe.InitBuffer(outQueueY, 1, blockLengthAlign * sizeof(float));

    // GM -> UB
    LocalTensor<float> xLocal = inQueueX.AllocTensor<float>();
    DataCopyInTensor1D<float>(xLocal, xGm, 0, blockLength);
    inQueueX.EnQue(xLocal);

    // 计算
    xLocal = inQueueX.DeQue<float>();
    LocalTensor<float> yLocal = outQueueY.AllocTensor<float>();

    // 确保在这里之前计算所需的输入输出 UB 内存已经准备完毕，直接调用对应的 VF 函数进行单元测试
    MulsImpl<float>(yLocal, xLocal, tilingData_.scalar, blockLength);

    // UB -> GM
    outQueueY.EnQue<float>(yLocal);
    inQueueX.FreeTensor(xLocal);
    yLocal = outQueueY.DeQue<float>();
    DataCopyOutTensor1D<float>(yGm, yLocal, 0, blockLength);
    outQueueY.FreeTensor(yLocal);
}
```

### 6.3 Python 测试脚本

Python 脚本从同目录的 `muls_reg_custom.cpp` 读取 Kernel 源码，再传给 `SourceModule`：

```python
import argparse
import os
import sys
import numpy as np
# 稳健自举（硬性要求，见 §3.4）：sys.path 目录搜索可能被 editable finder 破坏，
# 用 importlib 按文件路径注册 SingleOperatorLaunch，避免 ModuleNotFoundError。
import importlib.util
# 生成脚本时用 $SKILL_ROOT 解析出的实际路径（绝对路径或到 skill 的正确相对路径）
_SOL_DIR = "<SKILL_ROOT>/SingleOperatorLaunch"
if _SOL_DIR not in sys.path:
    sys.path.insert(0, _SOL_DIR)
if "SingleOperatorLaunch" not in sys.modules:
    _spec = importlib.util.spec_from_file_location(
        "SingleOperatorLaunch",
        os.path.join(_SOL_DIR, "__init__.py"),
        submodule_search_locations=[_SOL_DIR],
    )
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["SingleOperatorLaunch"] = _mod
    _spec.loader.exec_module(_mod)
from SingleOperatorLaunch import DeviceInfo, SourceModule, pack_tiling_data, setup_log_separation
# 配置日志分离：系统日志 -> log.txt，print 结果 -> 屏幕 + result.txt
setup_log_separation(log_file="log_muls.txt", result_file="result_muls.txt")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
KERNEL_SRC_PATH = os.path.join(SCRIPT_DIR, "muls_reg_custom.cpp")


def test_muls_reg(muls_reg_func, mod, total_length, scalar):
    """测试 MulsRegImpl VF 函数精度。"""
    # 1. 准备输入输出数据
    x = np.random.randn(total_length).astype(np.float32)
    y = np.zeros(total_length, dtype=np.float32)
    golden = x * scalar

    # 2. 打包 tiling 数据
    tiling_data = pack_tiling_data(
        [("totalLength", np.uint32), ("scalar", np.float32)],
        {"totalLength": total_length, "scalar": float(scalar)},
    )

    # 3. 调用 kernel，通过指定 output_indices 为输出变量下标开启 OOB 检查
    muls_reg_func(x, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1})

    # 4. 精度验证（生态精度标准，见 §6.6）
    print(f"  Input x (first 8): {x[:8]}")
    print(f"  Output y (first 8): {y[:8]}")
    print(f"  Golden  (first 8): {golden[:8]}")

    from SingleOperatorLaunch.precision_check import compare_tensor
    verdict = compare_tensor(y, golden.astype(np.float64), dtype="float32")
    if verdict.passed:
        print(f"  [PASS] Shape [{total_length}] scalar={scalar} passed! "
              f"(MERE={verdict.mere:.3e}, MARE={verdict.mare:.3e})")
    else:
        print(f"  [FAIL] Shape [{total_length}] scalar={scalar}: "
              f"MARE={verdict.mare:.3e}, max_diff={verdict.max_diff:.3e}, "
              f"{verdict.error_msg}")
    return verdict.passed

def main():
    parser = argparse.ArgumentParser(description="MulsReg VF unit test")
    parser.add_argument("--device_id", type=int, default=0, help="Target NPU device id")
    parser.add_argument("--kernel_src", type=str, default=KERNEL_SRC_PATH,
                        help="Path to AscendC kernel source file")
    args = parser.parse_args()

    dev = DeviceInfo()
    print("=" * 60)
    print(dev)
    print("=" * 60)

    # 测试多种 shape 和 scalar，覆盖尾块、对齐、非对齐场景
    test_cases = [
        (4,   2.0),    # 极小，尾块
        (37,  -1.5),   # 非对齐
        (64,  0.5),    # 对齐边界
        (1024, 3.14),  # 常规
        (1453, 0.01),  # 大非对齐
    ]
    block_dim = 1

    # 1. 从文件读取 Kernel 源码
    with open(args.kernel_src, "r", encoding="UTF-8") as f:
        kernel_src = f.read()

    # 2. 编译 Kernel
    mod = SourceModule(
        source=kernel_src,
        kernel_name="muls_reg_custom",
        block_dim=block_dim,
        core_type="VectorCore",
        ascendc_dump=True,
        workspace_sizes=1024,
        device_id=args.device_id,
        # 显式指定编译产物目录到测试脚本同目录，保证 fresh-build 与可清理（见 §3.4）
        kernel_meta=os.path.join(SCRIPT_DIR, "kernel_meta"),
    )
    print(f"  Compiled kernel metadata dir: {mod.kernel_meta}")

    # 3. 获取可调用函数
    muls_reg_func = mod.get_function()

    results = []
    for shape, scalar in test_cases:
        print(f"\nTesting shape: total_length={shape}, scalar={scalar}")
        results.append(test_muls_reg(muls_reg_func, mod, shape, scalar))

    if all(results):
        print("\n[ALL PASSED] All MulsReg tests passed!")
    else:
        print("\n[ SOME FAILED ] Some MulsReg tests failed!")


if __name__ == "__main__":
    main()
```

### 6.4 运行方式与关键验证点

#### 真实 NPU 上运行

```bash
# 默认使用 device 0，需保证该设备 Health:OK
python3 {output_dir}/kernel_test/muls_reg_test/test_muls_reg.py

# 指定其他健康设备
python3 {output_dir}/kernel_test/muls_reg_test/test_muls_reg.py --device_id 1
```

#### 关键验证点

| 验证项 | 说明 |
|--------|------|
| **尾块精度** | `total_length` 不是 64 的倍数时，`UpdateMask` 是否正确掩码 |
| **对齐搬运** | UB 分配使用 `CeilDivision(..., 32)` 保证 32B 对齐 |
| **标量传入** | `scalar` 通过 `pack_tiling_data` 打包成 bytes，经 `tiling_data` 关键字参数传入 |
| **硬件循环** | `for (uint16_t i = 0; i < repeatTime; ++i)` 满足 Hardware Loop 条件 |
| **多 shape 覆盖** | 包含极小、对齐、非对齐、大 shape，确保泛化性 |
| **OOB 检查** | 调用 kernel 时通过 `output_indices={i}` 启用越界检测，详见 §9 |

### 6.5 多数据类型的 numpy 支持

VF 单元测试经常需要覆盖 `bfloat16 / float16 / int8 / int4 / float8_e5m2 / float8_e4m3fn / float8_e8m0 / float4_e2m1 / float4_e1m2` 等多种 dtype。numpy 本身不原生支持所有低精度类型，需要借助 `ttk.utilities.dtypes` 中的构造器和辅助函数。

详细用法（dtype 构造、width 计算、golden 比较、4-bit 打包、FP8 E8M0 编码等）见：

- **`$SKILL_ROOT/references/multi-dtype-numpy.md`**

本节只保留两条核心原则：

1. **Kernel 侧与 Python 侧 dtype 必须一致**：Python 用 `ttk.utilities.dtypes` 构造出的 dtype 对象创建 numpy 数组，Kernel 侧模板参数/tiling/UB 分配按 `get_dtype_width()` 同步计算。
2. **4-bit 类型必须手动打包**：`int4 / float4` 在 numpy 中每个元素占 1 字节，NPU 期望 2 个元素打包在 1 个 `uint8` 中，必须通过 `pack_4bits` / `trans_np_bfloat16_tensor_to_fp4_*` 转换后再传给 `SingleOperatorLaunch`。

### 6.6 精度判定标准（VF 单元测试，唯一通路）

VF 单测的精度验收**只认一条通路**：`SingleOperatorLaunch.precision_check.compare_tensor`。
它按**生态算子开源精度标准**（与 cann-bench RelativeErrorChecker / devkit `precision_compare`
同语义）判过，测试脚本里**禁止**再手写 `np.allclose(..., rtol=..., atol=...)` 做通过判据
（`np.allclose` 只可用于调试打印）。

**判定语义**（逐输出按 `dtype` 查阈值）：

| dtype | 阈值（MERE） | 说明 |
|---|---|---|
| float16 | 2^-10 | |
| bfloat16 | 2^-7 | |
| float32 / float64 | 2^-13 | |
| hifloat32 | 2^-11 | |
| float8_e4m3fn / float8_e5m2 | 2^-3 / 2^-2 | |
| 整数 | 0（exact / abs-diff） | |

- **浮点**：`MERE < threshold AND MARE < 10*threshold` → 通过（stage-1）；
  stage-1 不过再走小值域 / 相消 / 正常值域同精度二阶段兜底。
  golden 传入**更高精度**数组即可，函数内部先截断到 output dtype 再比
  （模拟算子输出的精度限制）。NaN 位置不匹配 / Inf 符号不匹配 → 失败。
- **整数 / 布尔**：精确匹配，不等再按 abs-diff 容差判定。
- **bit-exact**：某输出需要位级一致时传 `threshold=0.0`（区分 ±0.0 / NaN
  payload / Inf 符号），如纯搬运（gather/scatter/duplicate）类 VF。

```python
from SingleOperatorLaunch.precision_check import compare_tensor

# dtype 可显式传（bfloat16/fp8 等建议显式），缺省按 y.dtype 推断
verdict = compare_tensor(y, golden.astype(np.float64), dtype="float16")
if verdict.passed:
    print(f"  [PASS] ... MERE={verdict.mere:.3e}, MARE={verdict.mare:.3e}")
else:
    print(f"  [FAIL] ... MARE={verdict.mare:.3e}, max_diff={verdict.max_diff:.3e}, "
          f"mismatch={verdict.mismatch_count}/{verdict.total_count}, {verdict.error_msg}")
```

- 阈值表与二阶段细节以 `SingleOperatorLaunch/precision_check.py` 为唯一权威源
  （含 `DEFAULT_THRESHOLDS` / `merge_thresholds` / `threshold_for_dtype`）；
  低精度 dtype 的数组构造与打包见 `references/multi-dtype-numpy.md`（§6.5）。
- 每个 dtype 组合的最终判定结果（passed / max_diff 等）须在 `## VF_TEST_RESULT` 的
  `dtype_combinations` 中如实上报（§4）。

## 7. 常见调试技巧
1. **使用 `AscendC::printf / AscendC::DumpTensor` 在 Kernel 内打印信息**：
    在进行单元测试时可以在 `__simd_vf__` 函数外调用 `printf / DumpTensor` 打印中间结果。
    ```cpp
    // printf 使用
    float value = xLocal.GetValue(0);
    AscendC::printf("value = %f\n", value);
    AscendC::printf("repeatTime = %d, count = %d\n", repeatTime, count);

    // DumpTensor 使用
    LocalTensor<float> srcLocal;
    AscendC::DumpTensor(srcLocal, 5, dataLen);  // 打印 srcLocal 中 dataLen 个元素
    ```
    参考文档（本仓知识库）：
        - `ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/调试接口/上板打印/DumpTensor.md`
        - `ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/调试接口/上板打印/printf.md`

2. **添加流水同步探针（排查流水竞态用）**

    在调用 VF 函数前后插入对应的**显式流水同步**，以确认是否是流水问题导致的错误：
    - VF 前（MTE2 搬入 → V 计算）：`SetFlag/WaitFlag<HardEvent::MTE2_V>(0)`
    - VF 后（V 计算 → MTE3 搬出）：`SetFlag/WaitFlag<HardEvent::V_MTE3>(0)`
    - 注意：Ascend 950 上 `PipeBarrier<PIPE_V>` 不需要、应删除；相邻 Vector 之间无需 barrier（见 `references/ascend_regbase_programing_guide.md` §10）。

3. **寄存器超限排查**：

    若出现 `fatal error: error in backend: Do not know how to split the result of this operator!`，检查 `__simd_vf__` / `__simd_callee__` 修饰符是否正确使用。

 4. **精度 diff 定位**

    先对比 golden 和 output 的首尾元素，确认是系统性偏差还是局部越界。

5. **printf 敏感 = 流水同步竞态（最高优先级判据）**

    若同一份源码"加 `printf`/`DumpTensor` 就 PASS、移除后就 FAIL"，或同一用例多轮运行结果不稳定（非确定性），**先锁定为流水同步竞态**，而不是 Cast 精度/布局/掩码问题：
    - **SIMD**：`__aicore__` 层 VF 调用**前后**都补显式流水同步（前：`SetFlag/WaitFlag<HardEvent::MTE2_V>(0)` 保证 MTE2 搬入对 VF `LoadAlign` 可见；后：`SetFlag/WaitFlag<HardEvent::V_MTE3>(0)` 保证 VF `StoreAlign` 对 MTE3 `CopyOut` 可见）；
    - **SIMT**：补 `SetFlag/WaitFlag<HardEvent::MTE2_V>(0)`（前，搬入对 SIMT 可见）与 `<HardEvent::V_MTE3>(0)`（后，SIMT 写对 MTE3 可见）；TQue EnQue/DeQue 不保证 async SIMT 完成；
    - VF 内"写 UB → 读同址"（in-place 累加 / Cast 落 scratch 再读回）必须插 `LocalMemBar<VEC_STORE, VEC_LOAD>`；
    - 依次排查完同步后，**再**去查 kernel_meta 新鲜度（见下条）与精度/布局。方向反了会浪费大量时间在假线索上。

6. **kernel_meta 新鲜度（改源码后结果"没变"先查这个）**

    修改 `.cpp` 后重跑，若结果与旧版一致/时对时错，先确认编译产物是最新的：`SourceModule` 每次会清理该 kernel 的旧 `.o` 并重新编译（fresh-build），默认 `kernel_meta` 在**调用脚本所在目录**。排查命令：`ls -la kernel_meta/` 比对 `.o` 的 mtime 是否晚于 `.cpp`；不要依赖 cwd 下的 `kernel_meta`（agent 的 cwd 可能与脚本目录不一致）。

7. **编译/执行链路解剖与快速排查（先查地图，勿逆向 ttk 源码）**

    遇到编译失败 / arch / include / dtype 支持疑问时，先读 `references/vf-compile-debug-chain.md`——含编译链路全貌（`SourceModule → _compile_kernel → CceManualCompile._compile_cce/_ld`，arch 由 ttk 从 soc_version 自动映射）、include 路径来源（`ASCEND_HOME_PATH`）、SDK API 签名查证路径（`asc/include/basic_api/reg_compute/*.h`）与编译失败排查表。**不要 `inspect.getsource(CceManualCompile)` 逆向 ttk 源码去推编译参数**（历史上 argmax 归约 VF 单测为此多耗上百轮）。

**参考文档读取纪律与上下文复用（token 经济性，预查询与调试循环均适用，优先于逐条技巧）**：

VF 单测调试的上下文开销集中在 **Read 大文档**，遵守以下纪律：
- **`a5-api-enhanced/*.md` 绝不整文件 Read**（单档 40~90KB）：先 Grep 行号地图，API 语义只读首段（`offset=1, limit=<实例区起始行>-1`），实例按需单段读。结构细节见 §5.5"文档结构与读取纪律"。
- **SKILL.md 全文只经 Skill 工具加载一次**，调试中复核某一节用 Grep 定位 + offset/limit 精读，**禁止二次整读**。
- **调试迭代循环内不整文件重读**：反复修改的是同一份 `{vf_func_snake}_custom.cpp`，其内容已在本轮上下文且 edit diff 可见；需要确认当前状态时只 Read 改动点行段（offset/limit），不重复整读。
- 辅助头文件（如 `examples/cast_common.h`）同理：一次整读后在本轮上下文复用，或 Grep 定位所需 helper 行段，**不反复整读**。
- **SDK 头文件查签名/实现只用 Grep 具体函数名，不整读**（见 `references/vf-compile-debug-chain.md` §3；历史上整读 58KB 的 `arg_max_with_value_base.h`、impl 头也属此类浪费）。
- 已读文件内容可直接引用本上下文中的结论，不需要"重读确认"。

经验基线：一次 argmax 归约 VF 单测中，a5-api-enhanced 整读 6 档（~278KB）+ SKILL.md 双份加载（~150KB）+ 同一文件反复整读（`cast_common.h` 3 次、自写 `.cpp` 5 次）累计吃掉 1.25MB 的 read 输出；上述纪律可将其压缩一个数量级。

## 8. 非对齐数据搬运与设备选择（重要经验）

> **适用性**：本节 §8.2~8.4 是 **SIMD 专属**（`LoadAlign` 32B 对齐语义）。SIMT 的"对齐"问题完全不同：GM 直读直写无 32B 约束；UB 访问受 8KB 窗口约束（见 `references/simt/simt-memory-access.md`）。§8.1 设备选择对两种模式通用。

### 8.1 设备选择

创建 `SourceModule` 时**必须选择健康设备**。先通过 `DeviceInfo()` 查看设备状态，选择 `Health:OK` 的设备：

```python
dev = DeviceInfo()
print(dev)  # 查看哪些设备是 OK 的
# 如果 device 0 是 CRITICAL，选择 Health:OK 的 device
mod = SourceModule(..., device_id=1)
```

### 8.2 非 32B 对齐的 2D 数据搬入（核心知识点）

当 VF 函数需要处理 2D 数据（如 `[rows, cols]` 按行归约），且 `cols` 不是 8 的倍数（即 `cols * sizeof(float)` 不是 32B 对齐）时，**必须在 kernel 内完成对齐**，否则 `LoadAlign` 会因非对齐地址产生错误结果。

#### 核心设计模式

```
Python 侧传入原始 numCol（可任意值如 235）
    ↓
Kernel 内计算 numColAlign = ceil(numCol * sizeof(T), 32) / sizeof(T)
    ↓
UB 按 [rows, numColAlign] 分配
    ↓
DataCopyPad 搬入时利用 DMA 自动对齐（dstStride=0）
    ↓
VF 函数用 numColAlign 做行间 stride、numCol 做实际处理列数
```

#### DataCopyPad 自动对齐机制

`DataCopyPad` 的 DMA 引擎在 UB（dst）侧有**自动 padding 行为**：

> 每个 block 搬入 `blockLen` 字节后，UB 侧该 block 实际占用 `ceil(blockLen, 32)` 字节。

因此，当 GM 行紧密排列时，只需设置 `dstStride=0`，一次 `DataCopyPad` 调用即可完成全部行的对齐搬入：

```cpp
// Kernel 内计算对齐
uint32_t numColAlign = ((numCol + ALIGN_ELEM - 1) / ALIGN_ELEM) * ALIGN_ELEM;
// ALIGN_ELEM = UB_BLOCK_SIZE / sizeof(T), 对 float 就是 8

// UB 分配按对齐后的总量
pipe.InitBuffer(inQueueX, 1, batchRows * numColAlign * sizeof(float));

// 一次 DataCopyPad 搬入所有行
DataCopyExtParams copyInParams{
    static_cast<uint16_t>(batchRows),           // blockCount: 行数
    static_cast<uint32_t>(numCol * sizeof(T)),  // blockLen: 每行实际字节(可不对齐)
    static_cast<uint32_t>(0),                   // srcStride: GM 行紧密无间隙
    static_cast<uint32_t>(0),                   // dstStride: DMA 自动 pad 到 32B
    0
};
DataCopyPadExtParams<T> padParams{false, 0, 0, static_cast<T>(0.0)};
DataCopyPad(xLocal, xGm, copyInParams, padParams);
```

搬入后 UB 布局：`xLocal[row * numColAlign]` 为第 row 行起始，每行首地址天然 32B 对齐。

#### VF 函数设计：分离 stride 和实际列数

VF 函数签名**必须同时接受** `colAlign`（行间 stride）和 `cols`（实际处理列数）：

```cpp
template <typename T>
__simd_vf__ inline void MyVfFunc(
    __ubuf__ float* dstUb,
    __ubuf__ T* srcUb,
    uint16_t rows,
    uint32_t colAlign,   // UB 行间 stride（32B 对齐）— 用于地址偏移
    uint32_t cols)       // 实际处理列数 — 用于 UpdateMask 计算
{
    for (uint16_t row = 0; row < rows; ++row) {
        uint32_t baseOffset = row * colAlign;  // 对齐的偏移
        uint32_t sreg = cols;                  // 实际列数传给 UpdateMask
        // ... LoadAlign(x, srcUb + baseOffset) ...
        // ... UpdateMask 自动处理尾部 mask ...
    }
}
```

#### __aicore__ 适配层

```cpp
__aicore__ inline void MyVfImpl(
    const AscendC::LocalTensor<float> &dst,
    const AscendC::LocalTensor<float> &src,
    uint32_t rows, uint32_t colAlign, uint32_t cols)
{
    __ubuf__ float *dstUb = (__ubuf__ float *)dst.GetPhyAddr();
    __ubuf__ float *srcUb = (__ubuf__ float *)src.GetPhyAddr();
    MyVfFunc<float>(dstUb, srcUb, static_cast<uint16_t>(rows), colAlign, cols);
}
```

### 8.3 常见陷阱

| 陷阱 | 症状 | 正确做法 |
|------|------|---------|
| Python 侧要求 numCol 必须对齐 | 限制了测试覆盖度 | Kernel 内计算对齐，Python 可传任意值 |
| `dstStride` 设为字节数 | stride 单位是 32B block，值被放大 | 标准对齐场景直接设 0 |
| VF 函数只用 `colAlign` 做 mask | 会处理 padding 区域的垃圾数据 | 用实际 `cols` 传给 `UpdateMask` |
| VF 函数只用 `cols` 做 stride | 第二行起 `LoadAlign` 地址非对齐 | 用 `colAlign` 做行间偏移 |
| UB 按 `rows * cols` 字节分配 | 分配不足，越界 | 按 `rows * colAlign * sizeof(T)` 分配 |
| 硬编码 `device_id=0` | Device 0 CRITICAL 直接报错 | 先查设备状态，选 OK 的设备 |

### 8.4 测试用例设计规则

#### 8.4.1 UB 容量约束（强制）

测试用例对应的 kernel 中**整体申请的 UB 总大小**（所有 `pipe.InitBuffer` 的 size 之和）必须满足：

```
UB_total_alloc < ub_size - 1KB
```

- `ub_size` 从 `{record_dir}/meta.json` 读取（bytes，CodegenStage 写入；缺失或为 0 时回退默认值 248KB / 253952）
- 预留 1KB 用于系统栈和 DCache 保护
- 设计 shape 时需提前计算 UB 占用：`UB_total = sum(rows * colAlign * sizeof(dtype))` 对所有输入/输出 buffer
- 示例：Ascend950DT 的 VectorCore UB 为 253952 bytes（约 248KB），则可用上限为 252928 bytes

#### 8.4.2 对齐覆盖（强制）

测试用例**必须同时包含** 32B 对齐和非对齐的样例：

```python
test_cases = [
    # 32B 对齐场景（cols * sizeof(dtype) % 32 == 0）
    (2, 128),   # 已对齐（128 * 4 = 512B，512 % 32 == 0）
    (4, 64),    # 刚好 1 个 VL（64 * 4 = 256B）
    # 非对齐场景（cols * sizeof(dtype) % 32 != 0）
    (2, 235),   # 非对齐（235 % 8 == 3）
    (3, 100),   # 非对齐（100 % 8 == 4）
    (1, 17),    # 极小非对齐（17 % 8 == 1）
    # 边界场景
    (1, 32),    # 小于 1 个 VL
    (1, 1),     # 最小有效输入
]
```

#### 8.4.3 设计流程

1. 根据 VF 函数的 I/O shape 规格（来自 `coding_plan.md` §6），确定每个 buffer 的维度
2. 计算每个 test_case 的 UB 总占用，确认不超过 §8.4.1 约束
3. 确保至少包含 5 个 32B 对齐 5 个非对齐 case
4. 建议覆盖：极小值、单 VL、多 VL、非对齐尾块等典型场景


## 9. OOB 检查与内存安全

`SingleOperatorLaunch` 内置 OOB（Out-of-Bound）检测机制，可在 kernel 执行后自动检查是否发生 HBM 内存越界。VF 单元测试应默认启用该机制，以及时发现非法内存访问。

### 9.1 两种 OOB 检测机制

`SingleOperatorLaunch/diagnostics.py` 提供两种独立检测：

1. **哨兵越界检测（Sentinel OOB）**
   - 每个 HBM 缓冲区尾部追加 288 字节 guard region（含 256B `0x02` 哨兵）
   - kernel 执行后校验 guard region 是否被覆盖
   - 可检测 kernel 写入超出缓冲区尾部 ≤256B 的越界

2. **数据不变越界检测（Silent OOB / Data-change）**
   - 执行前保存 output HBM 快照，执行后对比
   - 若 output 缓冲区内容完全未变，说明 kernel 写到了错误地址
   - 可检测跳过 guard 区域、写入完全错误地址的静默越界

参考实现：`$SKILL_ROOT/SingleOperatorLaunch/diagnostics.py:124`

### 9.2 如何在测试中启用 OOB 检查

调用 kernel 函数时通过 `output_indices` 参数指定输出参数的下标集合：

```python
muls_reg_func(x, y, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1})
```

- `output_indices={1}` 表示第 1 个参数（从 0 开始）`y` 是输出
- 指定 `output_indices` 后，会同时启用哨兵越界检测和数据不变越界检测
- 不指定时仅检查哨兵越界

多个输出时传入多个下标，例如 kernel 签名为 `(x, y, z, workspace, tiling)` 且 `y`、`z` 均为输出：

```python
add_func(x, y, z, *mod.workspace_arrays, tiling_data=tiling_data, output_indices={1, 2})
```

### 9.3 OOB 报错示例与排查

**哨兵越界：**

```
Arg 2 (float32(1007,), 4028 bytes) memory out of bound (sentinel corrupted) !!
Guard region at [0x10004c600fc0, 0x10004c6010e0): 60/288 bytes != 2 (expected).
```

触发原因通常是：
- kernel 中 DataCopyOut 写入长度大于 numpy output 数组实际长度
- UB 到 GM 搬运逻辑有误

排查方向：
- 检查 Python 侧 output 数组大小是否与 kernel 预期一致
- 检查对应的 `DataCopyPad` 逻辑

**数据不变越界：**

```
Arg 2 (float32(1023,), 4092 bytes) memory out of bound (data unchanged) !!
The kernel wrote NOTHING to the expected output buffer.
=> Identical. Kernel wrote to a different GM address.
```

触发原因通常是：
- `SetGlobalBuffer` 基址计算错误，写到了无关地址
- GM 偏移量设置错误
- 多核场景下 block 偏移计算错误

排查方向：
- 检查 `SetGlobalBuffer((__gm__ float*)y + blockLength * GetBlockIdx(), blockLength)` 等偏移计算
- 检查 output 参数在 kernel 签名中的顺序

### 9.4 最佳实践

1. **所有 VF 单元测试都应启用 OOB 检查**：在调用 kernel 时传入 `output_indices`
2. **output 下标必须准确**：与 kernel 入口参数顺序严格对应，从 0 开始计数
3. **不要把 tiling 或 workspace 传入 output_indices**：只标记真正的 GM 输出参数
4. **OOB 报错不等于精度失败**：OOB 报错说明内存访问异常，应优先排查地址/长度/偏移，而不是计算逻辑

## 10. 注意事项

**SIMD（`vf_mode="simd"`）**：
- VF 函数功能必须完全在 `__simd_vf__` 中实现，不得将计算逻辑外移到 `__aicore__` 中
- `__simd_vf__` 中不得使用 `[]` / `*` 直接访问指针，对于 `__ubuf__` 修饰的内存访问必须使用 `AscendC::Reg` 函数进行
- 完成 VF 函数精度测试后，需要确保删除调试信息

**SIMT（`vf_mode="simt"`）**：
- SIMT 计算逻辑完全在 `__simt_vf__` 中实现；`__aicore__` 只做 GM 指针提取与 `asc_vf_call` 启动
- `__simt_vf__` 必须 `#include "simt_api/common_functions.h"`；启动用 `cce::dim3(threads)`（裸 `dim3` 可能 undeclared）
- 需走 UB 时遵守 8KB 窗口（`[0,8192B)`）硬约束；能直写 GM 就直写 GM
- 与后续 MTE3/SIMD 之间显式 `SetFlag/WaitFlag<HardEvent::MTE2_V/V_MTE3>`；TQue EnQue/DeQue 不保证 async SIMT 完成
- 跨地址空间指针禁止 C-style cast，用 `reinterpret_cast<uintptr_t>` 中转
- 越界防护：入口空转保护 + index 越界钳制（SIMT 允许运行时分支）
- 完成 VF 函数精度测试后，需要确保删除调试信息