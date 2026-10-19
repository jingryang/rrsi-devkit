# D1 Playbook: 混合精度架构实操流程

> **强制流程**。D1 将单精度（FP32）算子扩展为支持 FP16/BF16/FP32 多类型的模板实现，以节省带宽并适配现代推理框架。

## Step 1: 定位关键结构

```bash
# 1.1 数据类型注册
grep -n "DataType\|DT_FLOAT\|DT_FLOAT16\|DT_BF16" shared/original/op_host/*.cpp shared/original/op_kernel/*.h > /tmp/d1_loc.txt

# 1.2 模板参数（如有）
grep -n "template.*typename T\|template.*class T" shared/original/op_kernel/*.cpp shared/original/op_kernel/*.h >> /tmp/d1_loc.txt

# 1.3 计算类型和 Cast 操作
grep -n "Cast\|calcType\|float32\|RoundMode" shared/original/op_kernel/*.cpp >> /tmp/d1_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **当前支持的 DataType**：列出所有 `ge::DT_*` 值
- **模板参数位置**：文件 + 行号
- **Cast 调用位置**：文件 + 行号

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| 输入 DataType | `ge::DT_FLOAT` | `ge::DT_FLOAT16, ge::DT_FLOAT, ge::DT_BF16` | `?_host.cpp:L?` |
| Kernel 模板 | 无 / 硬编码 `float` | `template <typename T>` | `?_kernel.h:L?` |
| 计算精度 | `T` 直接计算 | `calcType = std::conditional_t<is_fp16, float, T>` | `?_kernel.cpp:L?` |
| Cast 策略 | 无 | FP16→FP32 计算→FP16；BF16 视场景而定 | `?_kernel.cpp:L?` |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 简单 Element-wise**：`template <typename T>` + 输入输出同类型
- **形态 β — 需要高精度中间计算**（Norm / Reduce）：`calcType = float` 中间计算，结果 Cast 回 T
- **形态 γ — BF16 特殊处理**：BF16 直接计算或 FP32 中间计算，取决于精度要求

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α + β）

```cpp
// === OpDef / Host 注册改造 ===
this->Input("x")
    .ParamType(REQUIRED)
    .DataType({ge::DT_FLOAT16, ge::DT_FLOAT, ge::DT_BF16})
    .Format({ge::FORMAT_ND, ge::FORMAT_ND, ge::FORMAT_ND})
    .AutoContiguous();

// === Kernel 模板改造 ===
template <typename T>
class MyOpKernel {
    using calcType = typename std::conditional<
        std::is_same_v<T, half>, float,
        typename std::conditional<std::is_same_v<T, bfloat16_t>, float, T>::type
    >::type;

    __aicore__ inline void Compute(...) {
        LocalTensor<T> xLocal = inQueue.DeQue<T>();
        LocalTensor<T> outLocal = outQueue.AllocTensor<T>();
        
        if constexpr (std::is_same_v<T, half> || std::is_same_v<T, bfloat16_t>) {
            // FP16/BF16: Cast -> FP32 计算 -> Cast 回
            LocalTensor<calcType> xFp32 = calcBuf.Get<calcType>();
            LocalTensor<calcType> outFp32 = calcBuf.Get<calcType>(tileSize);
            Cast(xFp32, xLocal, RoundMode::CAST_NONE, tileSize);
            Add(outFp32, xFp32, scalarFp32, tileSize); // 用 calcType 计算
            Cast(outLocal, outFp32, RoundMode::CAST_RINT, tileSize);
        } else {
            // FP32: 直接计算
            Add(outLocal, xLocal, scalar, tileSize);
        }
        
        outQueue.EnQue<T>(outLocal);
        inQueue.FreeTensor(xLocal);
    }
};
```

### 3C. Variant Notes

- **形态 β（高精度中间计算）**：所有 Vector 计算在 `calcType` 上进行，仅在 CopyIn/CopyOut 时 Cast
- **形态 γ（BF16）**：若精度允许，BF16 可直接计算（无需 Cast）；若需高精度，按 FP16 路径处理
- **多 Kernel 实例**：`REGISTER_OP_TYPE(MyOp, FP16, MyOpKernel<half>)` 等方式注册

## Step 4: 约束复核

**公式**：
```
calcType size = sizeof(float) = 4B（FP16/BF16 场景）
额外 UB 占用 = tileSize * sizeof(calcType) * calcBufferCount
约束 1: 原 UB + 额外 UB <= UB_TOTAL * 0.8
约束 2: FP16→FP32 Cast 吞吐量损失 < 20%（通常可接受）
约束 3: BF16 路径避免重复 Cast（BF16→FP32→BF16 比 FP16 更省）
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: Host 端注册了多类型
grep -c "DT_FLOAT16.*DT_FLOAT\|DT_FLOAT.*DT_FLOAT16\|DT_BF16" modified_files/op_host/*.cpp
# 期望: >= 1

# 检查 2: Kernel 使用了模板参数 T
grep -c "template.*typename T\|template.*class T" modified_files/op_kernel/*.cpp modified_files/op_kernel/*.h
# 期望: >= 1

# 检查 3: 存在条件类型推导（calcType）
grep -c "std::conditional\|calcType\|is_same_v.*half\|is_same_v.*bfloat16" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 4: 存在 Cast 操作（FP16/BF16 路径）
grep -c "Cast.*RoundMode\|CAST_NONE\|CAST_RINT" modified_files/op_kernel/*.cpp
# 期望: >= 2

# 检查 5: 无硬编码 float 残留（主要计算路径）
grep -c "LocalTensor<float>.*=.*DeQue\|LocalTensor<float>.*=.*Alloc" modified_files/op_kernel/*.cpp
# 期望: == 0（或仅出现在 calcBuf 路径）
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：`half` / `bfloat16_t` 未定义 | 包含 `#include "tiling/platform/platform_ascendc.h"` |
| 精度退化（FP16 累加误差） | 确保中间计算用 `float`，仅在最后 Cast 回 `half` |
| BF16 直接计算精度不足 | 对 Reduce / Norm 类算子，BF16 也应走 FP32 中间路径 |
| UB 溢出（calcBuffer 过大） | 回 Step 4；考虑用 `TBuf<VECCALC>` 存 calcBuffer |
| 注册类型与实现不匹配 | Host `DataType` 列表必须与 Kernel 模板实例化一致 |
| Cast 模式错误 | `CAST_NONE` 截断，`CAST_RINT` 四舍五入；输出用 `CAST_RINT` |
| 性能无提升 | 检查是否框架侧已做 FP16→FP32 转换；若已转，D1 收益为 0 |

---

**完成后在 `implementation_note.txt` 贴**：
```
[D1 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: UB calc passed (extra=... <= UB_TOTAL*0.8)
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
