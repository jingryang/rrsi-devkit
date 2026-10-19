---
name: ascendc-pta
description: PyTorch Adapter (PTA) 算子集成与接口开发。覆盖两大场景：(1) 为主线 AscendC 算子完成 PTA 的开发，包括完整的三仓集成出包流程（op-plugin + torchair + pytorch），含接口定义、C++ OpAPI 实现、meta 注册、GE converter、编译验证，支持 ops-transformer/ops-nn 主线仓；(2) 为自定义 AscendC 算子添加 Python 调用接口（torch.ops.custom.npu_xxx），支持 omni-ops 自定义算子仓。Use when users mention "PTA接口", "PTA 适配", "PTA 出包", "PTA 集成", "torch_npu", "torch_npu 出包", "torch_npu 集成", "torch.ops.custom", "npu_xxx接口", "Python调用算子", "注册算子到torch", "torch_ops_extension","op-plugin", "op-plugin 适配", "op-plugin 出包", "torchair", "torchair 适配", "适配层", "pytorch 适配层", or ask how to call a custom AscendC op from Python/PyTorch, or want to generate op-plugin + torchair + pytorch build code.
---

# AscendC PTA (PyTorch Adapter) Interface

Add a Python-callable interface to an already-built and installed AscendC operator.

## 入口路由

使用 AskUserQuestion 确定目标仓库类型：

```yaml
AskUserQuestion:
  question: "该算子的 PTA 接口要适配到哪个仓库？"
  header: "目标仓库"
  options:
    - label: "主线仓 (ops-transformer / ops-nn)"
      description: "CANN 主线仓 ops-transformer 或 ops-nn，PTA 适配位于 Ascend/pytorch 仓"
    - label: "自定义算子仓 (omni-ops)"
      description: "omni-ops 仓，通过 torch.ops.custom.npu_{op_name} 调用"
```

---

## 主线仓 PTA 适配

### 前置路径确认（强制）

**CRITICAL**: 在读取或修改任何文件之前，**必须先通过终端交互确认仓库路径**。

**终端交互**：
```
根据主线仓 PTA 适配规范，需要修改 op-plugin、torchair、pytorch 三个仓库。

请提供这三个仓库的父目录绝对路径（三个仓库应位于同一目录下）：

父目录路径: ____________
```

**执行规则**：
- 🚫 **严禁在确认前扫描文件系统**
- 用户确认路径后，验证 `{parent}/op-plugin`、`{parent}/torchair`、`{parent}/pytorch` 存在
- **路径未确认前，禁止执行任何文件操作**

> **适用仓库**：
> - 算子实现仓：[ops-transformer](https://gitcode.com/cann/ops-transformer) / [ops-nn](https://gitcode.com/cann/ops-nn)
> - PTA 接口仓：[Ascend/pytorch](https://gitcode.com/Ascend/pytorch)

### PTA 算子集成

将自定义 NPU 算子集成到 torch_npu（PTA），覆盖 op-plugin、torchair、pytorch 三仓修改 + 编译出包 + 验证。

### 输入来源

使用 AskUserQuestion 让用户选择输入方式：

```yaml
AskUserQuestion:
  question: "请选择算子信息的输入方式"
  header: "输入方式"
  options:
    - label: "提供详细设计文档"
      description: "提供 xxx算子详细设计说明书.md 路径，自动解析 2.1/2.2 章节"
    - label: "终端输入"
      description: "按提示逐项提供算子信息"
```

### 信息完整性检查

在开始之前，必须确认以下信息（通过 AskUserQuestion 或用户主动提供）：

```yaml
CheckList:
  - PTA工作目录: 指向包含 pytorch/、op-plugin/、torchair/ 的父目录（**必须由用户手动输入**）
  - 算子接口名: **以设计文档为准**（设计文档中可能是 `_npu_xxx` 或 `npu_xxx` 或其他格式，**禁止凭经验假设**）
  - 每个输入Tensor的dtype: 必须明确
  - 输出shape推导: 必须有
  - 输出数据类型: 必须有
  - 目标芯片: Ascend950 / Ascend910 / Ascend910_93
```

**⚠️ 重要**：PTA工作目录必须由用户显式提供，禁止自动搜索猜测。

### 执行流程

四个阶段顺序执行，详细模板见 `references/mainline/` 目录。

**⚠️ 文件操作规则（重要）**：
1. **所有新增/修改的文件直接操作 PTA工作目录 下的独立工程目录**（`{PTA_DIR}/op-plugin/` 和 `{PTA_DIR}/torchair/`）
2. **🚫 禁止创建独立的 output 汇总目录**
3. **{PTA_DIR}/pytorch/third_party/ 下的子模块不做修改**（后续通过 git 同步）

**目录结构说明**：
```
{PTA_DIR}/                    # PTA工作目录（用户输入）
├── op-plugin/                # ← 代码生成目标（独立工作目录）
│   ├── config/
│   ├── ops/opapi/
│   └── ...
├── torchair/                 # ← 代码生成目标（独立工作目录）
│   ├── _ge_concrete_graph/
│   └── ...
└── pytorch/third_party/      # ← 不做修改（后续同步）
    ├── op-plugin/ -> 指向独立目录
    └── torchair/ -> 指向独立目录
```

**文件路径规范（相对于各独立工作目录）**：

| 阶段 | 文件路径 | 操作类型 |
|------|----------|----------|
| Stage 1 | `op-plugin/config/op_plugin_functions.yaml` | 追加 |
| Stage 1 | `op-plugin/ops/opapi/{OpName}KernelNpuOpApi.cpp` | 新建 |
| Stage 1 | `op-plugin/python/meta/_meta_registrations.py` | 追加 |
| Stage 1 | `op-plugin/test/core_tests/test_fake_tensor.py` | 追加 |
| Stage 1 | `op-plugin/test/core_tests/torch_npu_OpApi_schema_all.json` | 追加 |
| Stage 1 | `op-plugin/test/test_custom_ops/test_{op_name}.py` | 新建 |
| Stage 2 | `torchair/_ge_concrete_graph/auto_generated_ge_raw_ops.py` | 追加 |
| Stage 2 | `torchair/_ge_concrete_graph/ge_converter/custom/{op_name}.py` | 新建 |

> **⚠️ 文件操作关键规范**：追加文件禁止删除源文件内容，新建文件禁止创建临时文件。
> 详见 **references/mainline/op-plugin-templates.md §0.5** 和 **torchair-templates.md §2.3**

---

### Stage 1: op-plugin 仓修改

在 op-plugin 仓完成算子接口定义、C++ 实现、meta 注册和测试文件。

#### 1.1 接口定义（yaml）

**文件**：`op_plugin/config/op_plugin_functions.yaml`

在 `custom:` 段新增条目，定义函数签名：
- `*` 前为必选输入，`*` 后为可选输入（需默认值）
- `int?` 表示可选整型

#### 1.2 C++ OpAPI 实现

**文件**：`op_plugin/ops/opapi/{算子PascalCase名}KernelNpuOpApi.cpp`

实现要点：
1. **Shape 推导**：根据输入计算所有输出 shape
2. **输出分配**：`apply_tensor_without_format(shape, dtype)`
3. **参数转换**：字符串转 `char*`，dst_type 转 `aclDataType`
4. **执行调用**：`EXEC_NPU_CMD(aclnnXXX, ...)`

**Quant 类算子特殊处理**：详见 **references/mainline/op-plugin-templates.md § Quant 类算子特殊处理**

#### 1.3 meta 注册

**文件**：`op_plugin/python/meta/_meta_registrations.py`

让 FakeTensorMode 能正确推导输出 shape 和 dtype，逻辑必须与 C++ OpAPI 的 shape 推导一致。Quant 类算子的 dst_type 处理详见 **references/mainline/op-plugin-templates.md § 1.3**

#### 1.4 其他文件

| 文件 | 修改内容 |
|------|----------|
| `test/core_tests/test_fake_tensor.py` | 对比 eager 与 fake tensor 的 shape |
| `test/core_tests/torch_npu_OpApi_schema_all.json` | 新增 schema 条目 |
| `test/test_custom_ops/test_{接口名}.py` | 算子测试文件（golden 对比） |

详细模板见 **references/mainline/op-plugin-templates.md**。

---

### Stage 2: torchair 仓修改

在 torchair 仓完成 GE raw op 定义和 converter 实现。

#### 2.1 GE raw op 定义

**文件**：`torchair/_ge_concrete_graph/auto_generated_ge_raw_ops.py`

新增 GE raw op 函数，注意：
- `@auto_convert_to_tensor` 的两个列表长度 = `*` 前 Tensor 输入个数
- attr key 以 CANN OpDef 为准（如 `block_size` → `"blocksize"`）

#### 2.2 converter 实现

**文件**：`torchair/_ge_concrete_graph/ge_converter/custom/{接口名}.py`

实现要点：
1. 参数透传（大部分参数直接传给 GE op）
2. dst_type 转换（Python int → GE enum）
3. 图模式特殊处理（如 `output_rstd` 固定为 False）

详细模板见 **references/mainline/torchair-templates.md**。

---

### Stage 3: Mock 验证（无 NPU 环境）

**目的**：验证 Python → C++ → aclnn 参数传递正确性。

**前置条件**：op-plugin/torchair 已推送、无 mock 代码（详见 references 检查脚本）

**自动检测机制**：AI 自动从独立仓库获取分支名和 remote URL，智能更新 pytorch 的 .gitmodules，无需用户手动提供 fork 地址

**流程**：
1. 推送纯净代码 → 2. pytorch 本地加 mock → 3. 编译验证 → 4. 清理 mock

详细流程、检查脚本、submodule 同步注意点见 **references/mainline/verification-and-examples.md § Mock 全流程与常见错误**。

**安全红线**：
| 禁止 | 说明 |
|------|------|
| 🚨 AI 自动推送 | 用户手动执行 `git push` |
| 🚨 mock 代码入远程 | 仅在 `pytorch/third_party/op-plugin/` 本地 |
| 🚨 独立仓库加 mock | 必须在 pytorch submodule 中进行 |

详细流程、检查脚本、路径配置见 **references/mainline/verification-and-examples.md § Mock 全流程**。

---

### Stage 4: 正式全流程（需 NPU 环境）

**目的**：生成正式包并在真实 NPU 环境验证算子通路。

**完整流程**：

```
1. 重新同步纯净代码（关键步骤）
   └── 再次同步 op-plugin/torchair 子模块 → 验证无 mock 代码

2. 编译正式包
   └── 编译生成 torch_npu-*.whl（无 -DMOCK_ACLNN）

3. 真实 NPU 验证
   ├── op-plugin 通路验证：torch 直调模式
   ├── torchair 通路验证：图模式
   └── 精度验证：与 golden 对比
```

**重要**：必须重新同步子模块，确保 mock 代码未被打包到正式版本中。

详细命令和验证脚本模板见 **references/mainline/verification-and-examples.md § 正式全流程**。

---

### References

| 文件 | 内容 |
|------|------|
| `references/mainline/op-plugin-templates.md` | Stage 1 详细模板（yaml、OpAPI、meta、测试、接口修改指南） |
| `references/mainline/torchair-templates.md` | Stage 2 详细模板（GE raw op、converter） |
| `references/mainline/verification-and-examples.md` | Stage 3/4 验证流程 + 算子分类示例 |

---

## 自定义算子仓 (omni-ops) PTA 适配

> **Scope**: omni-ops repo（https://gitee.com/omniai/omni-ops），路径 `training/ascendc/torch_ops_extension`，注册为 `torch.ops.custom.npu_{op_name}`。

### Prerequisites

Before starting, confirm:
- [ ] Operator `.run` package is built and installed to `${ASCEND_OPP_PATH}`
- [ ] `aclnn{OpName}` symbol confirmed in `libcust_opapi.so`

Check the symbol:
```bash
# Locate libcust_opapi.so (path varies by installation: lib/ or op_api/lib/)
SO_PATH=$(find ${ASCEND_OPP_PATH}/vendors/omni_training_custom_ops -name "libcust_opapi.so" 2>/dev/null | head -1)
nm -D "$SO_PATH" | grep -F "aclnn{OpName}"
```

If symbol is missing → delete `build/` and rebuild the operator package from scratch before continuing.

---

### Repository Structure

```
torch_ops_extension/
└── omni_training_custom_ops/
    ├── csrc_base/
    │   ├── ops_def_registration.cpp  ← Step 3: add m.def() here
    │   ├── function.h                ← only for ops with custom autograd (skip for simple ops)
    │   └── ops_common.h              ← provides EXEC_NPU_CMD_V1 (already there, don't touch)
    └── ops_transformer/
        └── {category}/
            └── {op_name}/
                ├── __init__.py       ← Step 1: empty file
                ├── csrc/
                │   └── npu_{op_name}.cpp   ← Step 2: C++ binding
                └── test/
                    └── test_npu_{op_name}.py
```

`setup.py` auto-discovers `csrc/` files via glob `omni_training_custom_ops/*/*/*/csrc/*.cpp` — no manual registration needed beyond Step 3.

---

### Step 1: Create Directory Structure

```bash
OP_NAME="{op_name}"
CATEGORY="{category}"   # e.g., activation, normalization, attention
BASE="torch_ops_extension/omni_training_custom_ops/ops_transformer"

mkdir -p "$BASE/$CATEGORY/$OP_NAME/csrc"
mkdir -p "$BASE/$CATEGORY/$OP_NAME/test"
touch "$BASE/$CATEGORY/$OP_NAME/__init__.py"
```

The category directory likely already exists if other ops in the same category are present — `mkdir -p` handles this safely. The `__init__.py` stays empty.

---

### Step 2: Write `csrc/npu_{op_name}.cpp`

参照 [cpp-template.md](references/omni-ops/cpp-template.md) 生成 C++ binding 文件，含 Pattern A（单输出）、B（多输出）、C（autograd）三种模板。

关键规则：
- aclnn symbol = `aclnn{OpName}`（PascalCase，须与 `libcust_opapi.so` 中编译的符号一致）
- `TORCH_LIBRARY_IMPL` 必须在 `namespace custom {}` 内
- 输出 tensor 必须用 `at::empty_like` 预分配后再调 `EXEC_NPU_CMD_V1`

---

### Step 3: Register in `ops_def_registration.cpp`

在 `csrc_base/ops_def_registration.cpp` 的 `TORCH_LIBRARY_FRAGMENT(custom, m)` 块中添加 `m.def()` 行。签名模式见 [cpp-template.md](references/omni-ops/cpp-template.md)。

非明确要求不要动 `PYBIND11_MODULE`。

---

### Step 4: Build and Install

Only rebuild the whl when `csrc/` files or `ops_def_registration.cpp` change. If only the operator `.run` package changed (operator kernel rebuilt), no whl rebuild is needed.

```bash
# Find the torch_ops_extension directory and run the build script
cd {path/to/torch_ops_extension}
bash build_and_install.sh
```

The script runs: `rm -rf build → python3 setup.py build bdist_wheel → pip3 install *.whl --force-reinstall`

---

### Step 5: Write and Run Test

参照 [test-template.md](references/omni-ops/test-template.md) 生成测试脚本。

关键注意：
- `import omni_training_custom_ops` 须在 `import torch_npu` 之后
- 测试脚本须从 `torch_ops_extension/` **外部**运行（防止循环导入）
- 覆盖所有支持的 dtype（fp16, bf16, fp32）

---

### Troubleshooting

#### `ImportError: cannot import name 'custom_ops_lib'`

Running from inside `torch_ops_extension/` causes a circular import.

```bash
# Wrong
cd torch_ops_extension && python3 omni_training_custom_ops/.../test_npu_{op_name}.py

# Correct — use absolute path from outside
python3 /home/Code/omni-ops/training/ascendc/torch_ops_extension/omni_training_custom_ops/.../test_npu_{op_name}.py
```

#### `BinaryGetFunctionByEntry failed, funcEntry=N`

The kernel `.cpp` has a bare `else {}` branch that doesn't generate a binary entry for that tiling key. Every branch needs an explicit `TILING_KEY_IS`.

```cpp
// Wrong — funcEntry=2 will be missing
} else {
    KernelOp<float> op; ...
}

// Correct — explicit key for every branch
} else if (TILING_KEY_IS(CUSTOM_OP_FP32)) {
    KernelOp<float> op; ...
}
```

This is a kernel-side fix — rebuild the operator `.run` package after fixing, then reinstall.

#### `call aclnnCustomXxx failed` / symbol not found

`libcust_opapi.so` doesn't contain the aclnn symbol. Stale build cache.

```bash
rm -rf build/
bash build.sh -c "{chip_version}" -n "{op_name}"  # 910B→ascend910b, 910C→ascend910_93
```

Then reinstall with `--install-path=${ASCEND_OPP_PATH}`.

#### Wrong install path

用 `$ASCEND_OPP_PATH` 而非硬编码版本路径：

```bash
# Correct — use the env var
--install-path=${ASCEND_OPP_PATH}
# Wrong — versioned path doesn't affect the active toolkit
--install-path=/home/CANN/cann-8.5.0/opp/vendors
```

---

### Verification Checklist

**Before building:**
- [ ] aclnn symbol confirmed in `libcust_opapi.so`
- [ ] `__init__.py` created (empty)
- [ ] `npu_{op_name}.cpp`: `TORCH_LIBRARY_IMPL` inside `namespace custom {}`
- [ ] `npu_{op_name}.cpp`: outputs pre-allocated with `at::empty_like` before `EXEC_NPU_CMD_V1`
- [ ] `ops_def_registration.cpp`: `m.def()` added to `TORCH_LIBRARY_FRAGMENT` only (not `PYBIND11_MODULE`)

**After building:**
- [ ] `source set_env.bash` before running test
- [ ] Test run from outside `torch_ops_extension/` directory
- [ ] All dtypes tested (fp16, bf16, fp32)

---

### Reference Operators

| Type | Path |
|------|------|
| Simple forward | `torch_ops_extension/omni_training_custom_ops/ops_transformer/activation/custom_relu/` |
| With autograd | `torch_ops_extension/omni_training_custom_ops/ops_transformer/mhc/ai_infra_manifold_constrained_hyper_connection_post_grad/` |

### References

- [omni-ops/cpp-template.md](references/omni-ops/cpp-template.md): C++ binding 模板（Pattern A/B/C + 签名模式）
- [omni-ops/test-template.md](references/omni-ops/test-template.md): Python 测试脚本模板
