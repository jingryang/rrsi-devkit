# 验证模板与算子示例

## 一、安全操作规范

### 1.1 黄区代码安全原则

| 级别 | 规范 | 说明 |
|------|------|------|
| 🚨 **严禁** | 自动推送代码到远程 | AI 不得执行 `git push`，必须由用户手动确认后执行 |
| 🚨 **严禁** | mock 代码推送到远程 | `MOCK_ACLNN` 相关代码只能存在于本地 pytorch 仓 |
| ✅ **必须** | 用户手动执行 git push | 用户在确认代码正确性后手动推送 |

### 1.2 目录操作红线

| 操作 | 正确位置 | 错误位置 |
|------|----------|----------|
| 修改 yaml/meta/OpAPI | `{PTA_DIR}/op-plugin/` | - |
| 修改 GE converter | `{PTA_DIR}/torchair/` | - |
| 添加 mock 代码 | `{PTA_DIR}/pytorch/third_party/op-plugin/`（submodule）| `{PTA_DIR}/op-plugin/` |
| 编译验证 | `{PTA_DIR}/pytorch/` 目录 | `{PTA_DIR}/op-plugin/` 或 `{PTA_DIR}/torchair/` 独立目录 |

---

## 二、三阶段工作流程

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 1: 推送纯净代码                                                        │
│  ─────────────────────                                                        │
│  1. op-plugin 仓：保持无 mock 代码，推送至远程                                   │
│  2. torchair 仓：保持无 mock 代码，推送至远程                                    │
│  3. pytorch 仓：检查 .gitmodules 指向 fork 仓                                   │
│  4. pytorch 仓：同步子模块 → 验证为无 mock 代码                                  │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 2: Mock 验证（仅在 pytorch 本地进行）                                   │
│  ─────────────────────────────────────────                                   │
│  5. 在 pytorch/third_party/op-plugin 中添加 mock 代码（本地修改，不推送）          │
│  6. 修改 CMakeLists.txt 添加 -DMOCK_ACLNN                                     │
│  7. 编译 mock 包 → 运行 mock 测试 → 验证通过                                    │
└─────────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│  Phase 3: 正式出包                                                            │
│  ────────────────                                                             │
│  8. 再次同步 op-plugin/torchair 子模块 → 验证无 mock 代码                        │
│  9. 确认 CMakeLists.txt 无 -DMOCK_ACLNN                                       │
│  10. 编译正式包                                                              │
│  11. 生成真实通路验证代码                                                      │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 各阶段代码状态

| 阶段 | op-plugin 远程 | torchair 远程 | pytorch 本地子模块 | mock 代码 |
|------|---------------|---------------|-------------------|-----------|
| Phase 1 | 无 mock | 无 mock | 无 mock | ❌ 不存在 |
| Phase 2 | 无 mock | 无 mock | 本地添加 mock | ✅ 仅本地验证 |
| Phase 3 | 无 mock | 无 mock | 无 mock | ❌ 已清除 |

---

## 三、Phase 1: 推送纯净代码

### 3.1 op-plugin 仓

```bash
# 检查无 mock 代码
grep -n "MOCK_ACLNN" op_plugin/CMakeLists.txt && echo "ERROR: 包含 mock" || echo "OK: 无 mock"

# 提交并推送
git add -A
git commit -m "Add PTA interface for {算子名} operator"
git push origin $(git branch --show-current)
```

### 3.2 torchair 仓

```bash
# 检查无 mock 代码
grep -rn "MOCK_ACLNN" . && echo "ERROR: 包含 mock" || echo "OK: 无 mock"

# 提交并推送
git add -A
git commit -m "Add GE converter for {算子名} operator"
git push origin $(git branch --show-current)
```

### 3.3 pytorch 仓

【检查点 1】检查 .gitmodules 指向 fork 仓：

```bash
cat .gitmodules | grep -A 3 'op-plugin'
cat .gitmodules | grep -A 3 'torchair'
```

【检查点 2】同步子模块并验证为无 mock 代码：

```bash
git submodule sync
git submodule update --init --recursive

cd {PTA_DIR}/pytorch/third_party/op-plugin
git checkout ${OP_PLUGIN_BRANCH}
git pull origin ${OP_PLUGIN_BRANCH}
grep -n "MOCK_ACLNN" op_plugin/CMakeLists.txt && echo "❌ FAIL" || echo "✅ PASS"

cd {PTA_DIR}/pytorch/third_party/torchair/torchair
git checkout ${TORCHAIR_BRANCH}
git pull origin ${TORCHAIR_BRANCH}
grep -rn "MOCK_ACLNN" . && echo "❌ FAIL" || echo "✅ PASS"
```

---

## 四、Phase 2: Mock 验证

### 4.1 添加 mock 代码

**文件 1**：`third_party/op-plugin/op_plugin/CMakeLists.txt`

```cmake
# 约在 32 行，修改为：
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -DCURRENT_VERSION=V${CMAKE_MATCH_1}R${CMAKE_MATCH_2} -DMOCK_ACLNN" PARENT_SCOPE)
```

**文件 2**：`third_party/op-plugin/op_plugin/ops/opapi/{算子PascalCase名}KernelNpuOpApi.cpp`

**情况一：新增接口（普通算子）**

```cpp
#ifdef MOCK_ACLNN
    MOCK_EXEC_NPU_NO_FORMAT_CHECK_CMD(aclnn{算子名}, input1, input2, ...);
#else
    EXEC_NPU_NO_FORMAT_CHECK_CMD(aclnn{算子名}, input1, input2, ...);
#endif
```

**情况二：修改接口（需要处理 std::variant<Tensor, TensorWrapper>）**

```cpp
std::visit([&](const auto& query_arg, const auto& key_arg) {
#ifdef MOCK_ACLNN
    MOCK_EXEC_NPU_NO_FORMAT_CHECK_CMD(aclnnQuantLightningIndexer, query_arg, key_arg, ...);
#else
    EXEC_NPU_NO_FORMAT_CHECK_CMD(aclnnQuantLightningIndexer, query_arg, key_arg, ...);
#endif
}, query_processed, key_processed);
```

**Mock 实现（放在 namespace 之前，include 之后）**：

> **⚠️ 代码位置**：mock 辅助函数和 `#define` 宏必须放在 `namespace op_api {` **之前**（include 之后），
> 确保宏在 namespace 内使用时已经被定义。放在文件末尾 namespace 外部会导致
> `'MOCK_EXEC_NPU_NO_FORMAT_CHECK_CMD' was not declared in this scope` 编译错误。

> **⚠️ 重要：以下代码仅为范式模板，不可直接照搬。** 必须结合具体算子的参数列表进行定制扩充：
> - 为每个参数使用**具体的参数名**作为 JSON key（如 `"scale_value"`, `"sparse_mode"`），而非通用的 `"param"`
> - 根据参数类型选择合适的序列化方式：
>   - **Tensor**：记录 `shape` + `dtype`
>   - **TensorWrapper**（hifloat8 等场景）：记录 `shape` + `dtype` + `wrapped:true`，用于验证 wrapper 是否正确生效
>   - **optional\<Tensor\>**：有值记录 shape/dtype，无值记录 `null`
>   - **scalar**（int64_t, double）：直接记录数值
>   - **string**（char*）：记录字符串值
> - 建议编写**专用 mock 函数**（如 `MockXxxOp(...)`），参数签名与 `EXEC_NPU_CMD` 调用一致，逐个记录每个参数名和值
> - Mock 测试脚本中应能根据参数名逐一校验传递正确性

**范式模板**（展示基本结构，实际使用时必须按上述要求定制）：

```cpp
#ifdef MOCK_ACLNN
#include <fstream>
#include <sstream>

// --- 辅助函数（可复用） ---

// 获取 Tensor shape 字符串
static std::string TensorShapeStr(const at::Tensor& t) {
    std::ostringstream ss;
    ss << "[";
    for (int64_t i = 0; i < t.dim(); i++) {
        if (i > 0) ss << ",";
        ss << t.size(i);
    }
    ss << "]";
    return ss.str();
}

// 获取 Tensor 或 TensorWrapper 信息
template <typename T>
static std::string TensorOrWrapperInfo(const T& arg) {
    std::ostringstream ss;
    if constexpr (std::is_same_v<T, at::Tensor>) {
        ss << "{\"shape\":" << TensorShapeStr(arg)
           << ",\"dtype\":\"" << arg.scalar_type() << "\""
           << ",\"wrapped\":false}";
    } else {
        ss << "{\"shape\":" << TensorShapeStr(arg.tensor_)
           << ",\"dtype\":\"" << arg.tensor_.scalar_type() << "\""
           << ",\"wrapped\":true}";
    }
    return ss.str();
}

// 获取 optional<Tensor> 信息
static std::string OptTensorInfo(const c10::optional<at::Tensor>& t) {
    if (!t.has_value() || !t->defined()) return "null";
    std::ostringstream ss;
    ss << "{\"shape\":" << TensorShapeStr(t.value())
       << ",\"dtype\":\"" << t->scalar_type() << "\"}";
    return ss.str();
}

// --- 专用 mock 函数（必须针对具体算子定制） ---
// 示例：以下函数的参数列表和 JSON key 必须与目标算子的 EXEC_NPU_CMD 调用完全对应
template <typename KeyT, typename ValueT>
static void MockXxxOp(
    const char* json_path,
    const at::Tensor& input,
    const KeyT& key_arg,        // 可能是 Tensor 或 TensorWrapper
    const ValueT& value_arg,    // 可能是 Tensor 或 TensorWrapper
    double scale_value,
    int64_t mode,
    const c10::optional<at::Tensor>& optional_input,
    const char* layout_ptr,
    const at::Tensor& output)
{
    std::ofstream f(json_path);
    f << "{\n";
    f << "  \"input\":{\"shape\":" << TensorShapeStr(input) << ",\"dtype\":\"" << input.scalar_type() << "\"},\n";
    f << "  \"key\":" << TensorOrWrapperInfo(key_arg) << ",\n";
    f << "  \"value\":" << TensorOrWrapperInfo(value_arg) << ",\n";
    f << "  \"scale_value\":" << scale_value << ",\n";
    f << "  \"mode\":" << mode << ",\n";
    f << "  \"optional_input\":" << OptTensorInfo(optional_input) << ",\n";
    f << "  \"layout\":\"" << layout_ptr << "\",\n";
    f << "  \"output\":{\"shape\":" << TensorShapeStr(output) << ",\"dtype\":\"" << output.scalar_type() << "\"}\n";
    f << "}\n";
    f.close();
}

// Mock 宏：调用专用 mock 函数
#define MOCK_EXEC_NPU_NO_FORMAT_CHECK_CMD(aclnn_api, ...) \
    MockXxxOp("/tmp/mock_aclnn_" #aclnn_api ".json", __VA_ARGS__)

#define MOCK_EXEC_NPU_CMD(aclnn_api, ...) \
    MockXxxOp("/tmp/mock_aclnn_" #aclnn_api ".json", __VA_ARGS__)
#endif
```

**关键说明**：
1. **新增接口**：直接调用宏，不需要 `std::visit`
2. **修改接口**：需要 `std::visit` 处理 variant 时，才使用情况二的写法
3. **宏命名**：`MOCK_EXEC_NPU_NO_FORMAT_CHECK_CMD` 和 `MOCK_EXEC_NPU_CMD`
4. **定制要求**：`MockXxxOp` 函数名、参数列表、JSON key 必须根据具体算子的 `EXEC_NPU_CMD` 调用参数逐一对应，不可使用通用 variadic 模板将所有参数写入同一个 key

### 4.2 编译 mock 包

**编译前检查**：

```bash
# 1. 检查 Python 版本
python3 --version

# 2. 检查 CANN 环境变量
echo "ASCEND_TOOLKIT_HOME: ${ASCEND_TOOLKIT_HOME:-NOT SET}"
echo "ASCEND_HOME_PATH: ${ASCEND_HOME_PATH:-NOT SET}"
echo "ASCEND_OPP_PATH: ${ASCEND_OPP_PATH:-NOT SET}"
```

**编译命令**：

```bash
# 在 pytorch 目录下执行
cd {PTA_DIR}/pytorch

# 获取当前 Python 版本（动态获取，不写死版本号）
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')

# 执行编译
bash ci/build.sh --python=${PYTHON_VERSION}
```

**说明**：
- 编译超时设置为 40 分钟
- 如果编译失败，检查 CANN 环境是否正确激活

### 4.3 运行 mock 测试

```bash
pip3 install dist/torch_npu-*.whl --force-reinstall
python3 mock_verify_aclnn_params.py
```

**mock_verify_aclnn_params.py 模板**：

```python
#!/usr/bin/env python3
"""Mock test for {算子名}"""
import json
import torch
import torch_npu

def test_mock_params():
    # 构造测试输入
    x1 = torch.randn(2, 4, 64, dtype=torch.float16)
    x2 = torch.randn(2, 4, 64, dtype=torch.float16)
    gamma = torch.randn(64, dtype=torch.float16)

    # 调用算子（触发 mock）
    try:
        torch_npu.{接口名}(x1, x2, gamma, epsilon=1e-5, scale_alg=1,
                          round_mode="floor", dst_type=torch_npu.float4_e2m1fn_x2)
    except Exception as e:
        print(f"Expected in mock mode: {e}")

    # 读取并验证 mock 输出
    with open("/tmp/mock_aclnn_{算子名}.json", 'r') as f:
        mock_data = json.load(f)

    # 验证参数
    expected = {
        "epsilon": 1e-5,
        "scale_alg": 1,
        "round_mode": "floor",
        "dst_type": 40,
        "output_rstd": False
    }

    for key, expected_val in expected.items():
        actual_val = mock_data.get(key)
        if key == "epsilon":
            assert abs(actual_val - expected_val) < 1e-10
        else:
            assert actual_val == expected_val
        print(f"PASS: {key} = {actual_val}")

    print("\n✅ Mock test PASSED!")
    return 0

if __name__ == "__main__":
    exit(test_mock_params())
```

> **⚠️ Mock 测试脚本注意事项**：
> 1. **Tensor 必须放到 NPU**：mock 模式下 tensor 也必须 `.npu()`，CPU tensor 在 dispatch 阶段就会被拒绝，根本不会走到 mock 函数
> 2. **int8 tensor 不能用 `torch.randn`**：`torch.randn()` 不支持整型 dtype，应使用 `torch.randint(-128, 127, shape, dtype=torch.int8)`
> 3. **避免循环导入**：测试脚本不能在 pytorch 源码目录下执行，必须复制到 `/tmp` 等非源码目录运行

---

## 五、Phase 3: 正式出包

【检查点 3】再次同步子模块，确保无 mock 代码：

```bash
cd {PTA_DIR}/pytorch/third_party/op-plugin
git fetch origin
git checkout origin/${OP_PLUGIN_BRANCH}
grep -n "MOCK_ACLNN" op_plugin/CMakeLists.txt && echo "ERROR" || echo "PASS"

cd {PTA_DIR}/pytorch/third_party/torchair/torchair
git fetch origin
git checkout origin/${TORCHAIR_BRANCH}
grep -rn "MOCK_ACLNN" . && echo "ERROR" || echo "PASS"
```

【检查点 4】确认 OpAPI 文件无 mock 代码：

```bash
grep -n "MOCK_ACLNN" third_party/op-plugin/op_plugin/ops/opapi/*KernelNpuOpApi.cpp \
    && echo "ERROR" || echo "PASS"
```

编译正式包：

```bash
rm -rf build dist
bash ci/build.sh --python={PYTHON_VERSION}
```

---

## 六、检查点清单

| 检查点 | 时机 | 检查内容 | 验证命令 |
|--------|------|---------|----------|
| 1 | Phase 1 前 | .gitmodules 指向 fork 仓 | `cat .gitmodules \| grep url` |
| 2 | Phase 1 后 | 子模块为无 mock 代码 | `grep "MOCK_ACLNN" CMakeLists.txt` |
| 3 | Phase 3 前 | 再次同步子模块无 mock | `git checkout origin/{分支}` |
| 4 | Phase 3 前 | OpAPI 文件无 mock | `grep "MOCK_ACLNN" *KernelNpuOpApi.cpp` |

---

## 七、最终 NPU 验证（用户在真实机器执行）

**目的**：在真实 NPU 机器上验证算子通路（能跑通即可），不验证精度/功能。

### 7.1 op-plugin 通路验证

```python
import torch
import torch_npu

def test_{接口名}(x_dtype, ...):
    x = torch.randn((...), dtype=x_dtype).npu()
    y, ... = torch_npu.{接口名}(x, ...)
    print(f"{接口名} result:")
    print("x:\n", x)
    print("y:\n", y.cpu())

if __name__ == "__main__":
    test_{接口名}(torch.bfloat16, ...)
```

### 7.2 torchair 通路验证

```python
import torch
import torch_npu
import torchair

class {模型名}(torch.nn.Module):
    def __init__(self):
        super().__init__()
    def forward(self, x, ...):
        return torch_npu.{接口名}(x, ...)

def test_{接口名}(x_dtype, ...):
    x = torch.randn((...), dtype=x_dtype).npu()
    model = {模型名}().to('npu')
    config = torchair.CompilerConfig()
    npu_backend = torchair.get_npu_backend(compiler_config=config)
    model = torch.compile(model, backend=npu_backend, dynamic=True, fullgraph=True)
    y, ... = model(x, ...)
    print(f"{接口名} result:")
    print("x:\n", x)
    print("y:\n", y.cpu())

if __name__ == "__main__":
    test_{接口名}(torch.bfloat16, ...)
```

**关键注意点**：
- `forward()` 参数默认值必须与 `op_plugin_functions.yaml` 完全一致
- yaml 中 `int dst_type=296` 对应 Python 中 `dst_type=torch_npu.float4_e2m1fn_x2`（296）
- 仅验证通路（不报错即可），精度/功能在后续阶段验证

---

## 第四部分：算子分类参考

### Quant 类

**特征**：算子名含 quant/quantize/dequant/anti_quant

**处理方式**：
- 使用 `TensorWrapper` 绑定真实 aclDataType
- 使用 `c10_npu::GetAclDataType(dst_type)` 转换
- FP4 输出用 uint8 承载，shape 尾轴减半

**参考算子**：DynamicMxQuantWithDualAxis, DynamicQuant, QuantMatmul

**参考文件**：
- OpAPI: `op_plugin/ops/opapi/DynamicMxQuantWithDualAxisKernelNpuOpApi.cpp`
- meta: `op_plugin/python/meta/_meta_registrations.py`
- GE: `torchair/_ge_concrete_graph/ge_converter/custom/npu_dynamic_mx_quant_with_dual_axis.py`

### Norm 类

**特征**：算子名含 norm/rms_norm/layer_norm（不含 quant）

**处理方式**：
- **不使用** `TensorWrapper`
- **不使用** `GetAclDataType`
- 标准 FP16/BF16/FP32 处理

**参考算子**：RmsNorm, LayerNorm

### Attention 类

**分类**：
- 纯 Attention（不含 quant）：不使用 TensorWrapper
- Quant+Attention：使用 TensorWrapper

**参考算子**：FlashAttention（纯）, FlashAttentionV2（含 quant）

### Matmul 类

**分类**：
- 纯 Matmul：不使用 TensorWrapper
- Quant+Matmul：使用 TensorWrapper

**参考算子**：Matmul（纯）, QuantMatmul（含 quant）

### 混合类

**特征**：Norm + Quant, Add + RmsNorm + Quant 等

**处理原则**：只要含 Quant 逻辑，就按 Quant 类处理

**参考算子**：AddRmsNormQuant, RmsNormQuant

---

## 第五部分：TensorWrapper 使用速查

| 算子类别 | 使用 TensorWrapper |
|----------|-------------------|
| Quant 类（所有） | ✅ 是 |
| Norm 类（纯） | ❌ 否 |
| Attention（纯） | ❌ 否 |
| Attention（含 Quant） | ✅ 是 |
| Matmul（纯） | ❌ 否 |
| Matmul（含 Quant） | ✅ 是 |
| 混合类（含 Quant） | ✅ 是 |

---

## 第六部分：submodule 同步与常见错误

### 6.1 完整流程

以下命令均相对于 pytorch 仓库根目录执行：

```bash
# 1. 修改 .gitmodules
# 将 op-plugin 和 torchair 的 url 改为用户的 fork 地址

# 2. 同步 submodule 配置
git submodule sync

# 3. 拉取 submodule（注意：这会 checkout 到 pytorch 记录的固定 commit）
git submodule update --init --recursive

# 4. ⚠️ 关键：切换到目标分支并拉取最新代码
# git submodule update 不会自动跟踪分支，必须手动执行
cd {PTA_DIR}/pytorch/third_party/op-plugin
git checkout {op-plugin分支名}
git pull origin {op-plugin分支名}

cd {PTA_DIR}/pytorch/third_party/torchair/torchair
git checkout {torchair分支名}
git pull origin {torchair分支名}

# 5. 验证同步结果
git -C {PTA_DIR}/pytorch/third_party/op-plugin log --oneline -3
git -C {PTA_DIR}/pytorch/third_party/torchair/torchair log --oneline -3
```

> **注意**：`{PYTORCH_DIR}` 为 pytorch 仓库根目录的绝对路径，请根据实际环境替换。

### 6.2 常见错误与强制同步

#### 错误点清单

| 错误 | 现象 | 原因 | 后果 |
|------|------|------|------|
| Remote URL 错位 | `git remote -v` 显示错误仓库 | `git submodule sync` 后未验证实际 remote | op-plugin 目录指向 torchair.git，反之亦然 |
| 跨仓库强制同步 | 同步后找不到预期代码 | 在 op-plugin 目录执行了 torchair 的 reset | 两个 submodule 内容错乱 |
| 虚假成功确认 | 声称同步成功但文件不存在 | 未验证关键文件实际存在 | 后续编译找不到算子接口 |
| 目录切换混乱 | 命令在错误位置执行 | 依赖 shell 当前目录而非绝对路径 | 同步操作无效 |

#### 强制同步命令模板

```bash
# 1. 在 op-plugin submodule 目录强制同步 op-plugin 代码
cd {PTA_DIR}/pytorch/third_party/op-plugin
git remote set-url origin https://gitcode.com/{用户名}/op-plugin.git
git fetch origin {分支名}
git reset --hard origin/{分支名}

# 2. 在 torchair submodule 目录强制同步 torchair 代码
cd {PTA_DIR}/pytorch/third_party/torchair/torchair
git remote set-url origin https://gitcode.com/{用户名}/torchair.git
git fetch origin {分支名}
git reset --hard origin/{分支名}

# 3. 验证关键文件存在
ls -la {PTA_DIR}/pytorch/third_party/op-plugin/op_plugin/ops/opapi/{OpName}KernelNpuOpApi.cpp
ls -la {PTA_DIR}/pytorch/third_party/torchair/torchair/python/torchair/_ge_concrete_graph/ge_converter/custom/{op_name}.py
```

> **变量说明**：
> - `{PTA_DIR}`: PTA工作目录（如 `/home/user/workspace/PTA`）
> - `{PYTORCH_DIR}`: pytorch 仓库根目录（`{PTA_DIR}/pytorch`）
> - `{用户名}`: gitcode/gitee 用户名
> - `{分支名}`: 代码所在分支（如 `ARNDMQ`）
> - `{OpName}`: 算子 PascalCase 名称（如 `AddRmsNormDynamicMxQuant`）
> - `{op_name}`: 算子 snake_case 名称（如 `npu_add_rms_norm_dynamic_mx_quant`）

| 错误现象 | 原因 | 解决 |
|---------|------|------|
| 找不到 meta 注册 | submodule 停留在旧 commit | 执行步骤 4 切换到分支最新 |
| Mock 未生效 | CMakeLists.txt 修改未同步 | 同上 |
| 编译找不到 aclnn | CANN 环境未激活 | `source {CANN路径}/set_env.sh` |

---

## 第七部分：注意事项汇总

### Mock 验证流程关键要点

#### 1. 代码安全红线（绝对禁止）

| 禁止事项 | 原因 | 后果 |
|----------|------|------|
| AI 自动执行 `git push` | 无法确认代码正确性 | 可能推送错误代码到远程 |
| mock 代码推送到 op-plugin/torchair 远程 | 污染主线代码 | 安全检查失败，代码回退 |
| 在独立 op-plugin/torchair 目录添加 mock | mock 只能在 pytorch submodule 中进行 | 无法编译验证 |

#### 2. 目录操作边界

| 操作 | 正确位置 | 错误位置 |
|------|----------|----------|
| 修改 yaml/meta/OpAPI | `{PTA_DIR}/op-plugin/` | - |
| 修改 GE converter | `{PTA_DIR}/torchair/` | - |
| 添加 mock 代码 | `{PTA_DIR}/pytorch/third_party/op-plugin/`（submodule）| `{PTA_DIR}/op-plugin/` |
| 编译验证 | `{PTA_DIR}/pytorch/` 目录 | `{PTA_DIR}/op-plugin/` 或 `{PTA_DIR}/torchair/` 独立目录 |

#### 3. 检查点速查表

执行 push 前：
```bash
# op-plugin 仓
grep -n "MOCK_ACLNN" op_plugin/CMakeLists.txt && echo "❌ 含 mock" || echo "✅ 无 mock"
git diff --stat

# torchair 仓
grep -rn "MOCK_ACLNN" . && echo "❌ 含 mock" || echo "✅ 无 mock"
git diff --stat
```

同步子模块后：
```bash
cd pytorch/third_party/op-plugin
grep -n "MOCK_ACLNN" op_plugin/CMakeLists.txt && echo "❌ 含 mock" || echo "✅ 无 mock"

cd ../torchair/torchair
grep -rn "MOCK_ACLNN" . && echo "❌ 含 mock" || echo "✅ 无 mock"
```

#### 4. 用户必须手动执行的命令

以下命令必须由用户在确认代码正确后手动执行，AI 只负责生成和提示：

1. `git push origin {分支名}`
2. `bash ci/build.sh --python={版本}`（在 pytorch 目录）
3. `pip3 install dist/torch_npu-*.whl`

#### 5. 典型问题排查

**问题 1**：`git submodule update` 后代码未更新
- **原因**：submodule 默认不跟踪分支，停留在固定 commit
- **解决**：手动 `git checkout {分支} && git pull origin {分支}`，详见第六部分

**问题 2**：编译时找不到新添加的算子接口
- **原因**：子模块未同步到最新代码
- **解决**：检查 `third_party/op-plugin` 是否包含最新 yaml 和 OpAPI，详见第六部分

---

## 第八部分：常见编译错误与修复

### OpAPI 编译错误速查表

| 错误信息 | 位置 | 原因 | 修复方案 |
|----------|------|------|----------|
| `conversion from 'c10::SmallVector<...>' to non-scalar type 'std::vector<...>' requested` | `array_to_small_vector` 返回值赋值 | `op_infer::array_to_small_vector()` 返回 `c10::SmallVector`，不能直接赋值给 `std::vector` | 添加中间变量手动转换：<br>`auto vec = op_infer::array_to_small_vector(...);`<br>`std::vector<int64_t> sizes(vec.begin(), vec.end());` |
| `no matching function for call to 'GetAclDataType(c10::ScalarType&)'` | `c10_npu::GetAclDataType()` 调用 | `GetAclDataType()` 只接受 `int64_t` 或 `DType`，不接受 `ScalarType` | 改用 `npu_preparation::convert_to_acl_data_type(scalar_type)` |
| `dst_type - 256` 硬编码转换错误 | EXEC_NPU_CMD 参数 | 当 `dst_type=296` (FP4) 时，转换后为40，但FP4应该用 `ACL_UINT8` | 延后转换：先判断FP4类型设置 `y_scalar_type`，再用 `convert_to_acl_data_type()` 统一转换 |
| `fatal error: tensor_wrapper.h: No such file or directory` | `#include` 语句 | `TensorWrapper` 和 `make_wrapper` 定义在 `op_api_common.h` 中，不存在独立的 `tensor_wrapper.h` | 删除该 include，确认 `op_api_common.h` 已包含 |
| `use of deleted function 'std::variant<Tensor, TensorWrapper>::operator='` | `std::variant` 赋值 | `TensorWrapper` 的移动赋值运算符被编译器删除 | 用构造初始化 `variant(tensor)` + `emplace<TensorWrapper>(...)` 替代 `=` 赋值 |
| `'MOCK_EXEC_NPU_NO_FORMAT_CHECK_CMD' was not declared in this scope` | mock 宏调用处 | mock 宏定义在 namespace 外部（文件末尾），但使用在 namespace 内部 | 将 `#ifdef MOCK_ACLNN` 整块移到 `namespace op_api` **之前** |
| `undefined reference to 'op_api::xxx'` + `hidden symbol isn't defined`（链接阶段） | 链接 `libtorch_npu.so` | OpAPI 函数签名中 `c10::optional<int64_t>` 使用了 `const &` 引用传递，与 codegen 生成的按值传递签名不匹配 | `int?` 类型必须按值传递：`c10::optional<int64_t> key_dtype`，不加 `const &` |
| `cannot bind non-const lvalue reference of type 'long int&' to an rvalue of type 'long int'` | `EXEC_NPU_NO_FORMAT_CHECK_CMD` 宏参数 | 宏内部日志宏 `generate_log_infos` 通过非 const 左值引用接收参数，而 `optional::value_or(0)`、`static_cast<T>(x)`、三元表达式等返回右值 | **`EXEC_NPU_*` 宏的所有参数必须是具名左值变量**，不能传入临时表达式。将结果提取为局部变量：<br>`int64_t key_dtype_val = key_dtype.value_or(0);`<br>然后传入 `key_dtype_val` |

### 类型转换最佳实践

#### SmallVector → std::vector

```cpp
// ❌ 错误：不能直接赋值
auto x1_sizes = op_infer::array_to_small_vector(x1.sizes());  // 返回 SmallVector
std::vector<int64_t> y_shape = x1_sizes;  // 编译错误

// ✅ 正确：使用构造函数转换
auto x1_sizes_vec = op_infer::array_to_small_vector(x1.sizes());
std::vector<int64_t> x1_sizes(x1_sizes_vec.begin(), x1_sizes_vec.end());
std::vector<int64_t> y_shape = x1_sizes;  // 现在可以赋值了
```

#### ScalarType → aclDataType

```cpp
// ❌ 错误：GetAclDataType 不接受 ScalarType
at::ScalarType y_scalar_type = at::ScalarType::Byte;
aclDataType y_acltype = c10_npu::GetAclDataType(y_scalar_type);  // 编译错误

// ✅ 正确：使用 convert_to_acl_data_type
aclDataType y_acltype = npu_preparation::convert_to_acl_data_type(y_scalar_type);
```

#### int64_t (dst_type) → aclDataType（Quant类算子）

```cpp
// ❌ 错误：硬编码减法，FP4处理不当
int64_t dst_type = 296;  // float4_e2m1fn_x2
aclDataType y_acltype = static_cast<int>(dst_type - 256);  // 得到40，但FP4应该用UINT8

// ✅ 正确：先处理特殊类型，再统一转换
at::ScalarType y_scalar_type;
if (dst_type == 296 || dst_type == 297) {  // FP4特殊处理
    y_scalar_type = at::ScalarType::Byte;  // FP4用uint8承载
} else {
    y_scalar_type = x1.scalar_type();  // 非FP4用输入类型
}
aclDataType y_acltype = npu_preparation::convert_to_acl_data_type(y_scalar_type);
```

### 循环导入错误

**现象**：在pytorch源码目录执行 `import torch_npu` 报错：
```
ImportError: cannot import name '_C' from partially initialized module 'torch_npu'
```

**原因**：当前目录包含torch_npu源码，Python优先从当前目录导入而非site-packages

**解决**：切换到其他目录再执行验证：
```bash
cd /tmp  # 或其他非源码目录
python3 -c "import torch_npu; print(torch_npu.__version__)"
```

### pip安装优化

**问题**：`--force-reinstall` 耗时过长

**解决**：先卸载再安装，或使用 `--no-deps`：
```bash
# 方式1：先卸载再安装
pip uninstall torch_npu -y
pip install dist/torch_npu-*.whl

# 方式2：使用 --no-deps 跳过依赖检查
pip install dist/torch_npu-*.whl --force-reinstall --no-deps
```

### 文件路径注意事项

**关键区别**：pytorch编译使用的是子模块路径，而非独立仓库路径

```
{PTA_DIR} = PTA工作目录（如 /home/user/workspace/PTA）
{PTA_DIR}/pytorch = pytorch仓库根目录

❌ 错误：修改此路径不会生效
{OP_PLUGIN_DIR}/op_plugin/ops/opapi/

✅ 正确：必须修改子模块路径
{PTA_DIR}/pytorch/third_party/op-plugin/op_plugin/ops/opapi/
```

**建议**：修改前先确认当前文件路径：
```bash
# 在独立仓库中修改后，需同步到子模块
cd {PTA_DIR}/pytorch/third_party/op-plugin
git checkout origin/{分支名}  # 或手动复制修改后的文件
```
