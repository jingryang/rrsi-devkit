# P13 Playbook: 特殊算法与高阶 API 实操流程

> **强制流程**。P13 将手动 Vector 指令序列替换为高阶 AscendC API（DAGSch / ElementwiseSch / SoftMax / LayerNorm），利用自动流水和内存优化。

## Step 1: 定位关键结构

```bash
# 1.1 手动 Vector 指令序列
grep -n "\bAdd\b\|\bMul\b\|\bSub\b\|\bDiv\b\|\bCast\b\|\bExp\b\|\bSqrt\b\|\bAbs\b" shared/original/op_kernel/*.cpp > /tmp/p13_loc.txt

# 1.2 队列管理代码
grep -n "AllocTensor\|DeQue\|EnQue\|FreeTensor\|InitBuffer.*TQue\|InitBuffer.*TBuf" shared/original/op_kernel/*.cpp >> /tmp/p13_loc.txt

# 1.3 循环结构
grep -n "for.*Process\|for.*Compute\|while.*loop" shared/original/op_kernel/*.cpp >> /tmp/p13_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **Vector 指令序列**：文件 + 行范围（完整计算链）
- **队列管理位置**：文件 + 行号
- **循环边界**：文件 + 行范围

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| 计算方式 | 手动 Vector 指令 | 高阶 API / DAGSch | `?_kernel.cpp:L?` |
| 内存管理 | 手动 TQue/TBuf | API 自动分配 | `?_kernel.cpp:L?` |
| 同步方式 | 手动 PipeBarrier | API 自动同步 | `?_kernel.cpp:L?` |
| 指令序列 | 5-10 条 Vector 指令 | 1 条 API 调用 | `?_kernel.cpp:L?` |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 简单逐元素链**（Foreach / Element-wise）：`ElementwiseSch` 自动融合多指令
- **形态 β — 归一化计算**（LayerNorm / RMSNorm）：`LayerNorm` 高阶 API 替代手动 mean/var
- **形态 γ — Softmax 类**：`SoftMax` / `SoftMaxGrad` 高阶 API 替代手动 exp/sum/div

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α）

```cpp
// === 改造前 ===
__aicore__ inline void Compute(...) {
    LocalTensor<float> varLocal = varQueue.DeQue<float>();
    LocalTensor<float> accumLocal = accumQueue.DeQue<float>();
    LocalTensor<float> gradLocal = gradQueue.DeQue<float>();
    LocalTensor<float> outLocal = outQueue.AllocTensor<float>();
    
    Mul(gradPowerLocal, gradLocal, gradLocal, tileSize);
    Add(accumOutLocal, accumLocal, gradPowerLocal, tileSize);
    Sqrt(accumSqrtLocal, accumOutLocal, tileSize);
    Div(varOutLocal, gradLocal, accumSqrtLocal, tileSize);
    
    outQueue.EnQue<float>(outLocal);
}

// === 改造后 ===
// 定义 DAG
using OpGradPower = Bind<Vec::Mul<T>, OpGrad, OpGrad>;
using OpAccumOut = Bind<Vec::Add<T>, OpAccum, OpGradPower>;
using OpAccumSqrt = Bind<Vec::Sqrt<T>, OpAccumOut>;
using OpVarOut = Bind<Vec::Div<T>, OpGrad, OpAccumSqrt>;
using Outputs = Elems<OpVarOut, OpAccumOut>;
using MemCfg = MemOptCfg<MemLevel::LEVEL_2>;
using OpDag = DAGSch<Outputs, void, MemCfg>;

// Kernel 中执行
__aicore__ inline void Compute(...) {
    ElementwiseSch<schMode, MyOp::OpDag> sch(&(tilingData.baseTiling), &pipe);
    sch.Init(var, accum, grad, var_out, accum_out);
    sch.Process();
}
```

### 3C. Variant Notes

- **形态 β（LayerNorm）**：使用 `AscendC::LayerNorm` API，传入 `xLocal, gammaLocal, betaLocal, yLocal, meanLocal, varLocal`
- **形态 γ（Softmax）**：使用 `AscendC::SoftMax` API，注意需要临时 buffer；使用 `GetSoftMaxMaxTmpSize` 查询
- **若 API 不支持特定操作**：保留手动实现，但将其封装为 `Bind` 节点插入 DAG

## Step 4: 约束复核

**公式**：
```
高阶 API 临时 buffer 需求 = API::GetMaxTmpSize(shape, dataType)
总 UB = 输入 buffer + 输出 buffer + API tmp buffer
约束 1: 总 UB <= UB_TOTAL * 0.8
约束 2: 高阶 API 支持的数据类型覆盖算子需求
约束 3: tilingData 需适配高阶 API 的 tiling 格式
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: 使用了高阶 API 或 DAGSch
grep -c "DAGSch\|ElementwiseSch\|SoftMax\|LayerNorm\|MatmulImpl" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 2: 手动 Vector 指令数量减少
grep -c "\bAdd\b\|\bMul\b\|\bSub\b\|\bDiv\b\|\bCast\b" modified_files/op_kernel/*.cpp
# 期望: <= 原始数量 * 0.5（大幅减少）

# 检查 3: 无手动队列 Alloc/Free（主要路径）
grep -c "AllocTensor\|FreeTensor\|DeQue\|EnQue" modified_files/op_kernel/*.cpp
# 期望: == 0（或仅保留输入/输出边界）

# 检查 4: 存在 API tiling 参数传递
grep -c "baseTiling\|softmaxTiling\|layerNormTiling" modified_files/op_kernel/*.cpp modified_files/op_host/*_tiling.cpp
# 期望: >= 1

# 检查 5: 无手动 PipeBarrier 残留（主要路径）
grep -c "PipeBarrier" modified_files/op_kernel/*.cpp
# 期望: == 0（或 <= 2 条边界同步）
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：DAGSch 模板参数不匹配 | 检查 `Bind<>` 的输入输出类型与实际的 `LocalTensor` 类型一致 |
| 精度退化（高阶 API 内部实现差异） | 对比基线精度，若偏差 > 1e-5，保留手动实现的关键路径 |
| UB 溢出（API tmp buffer 过大） | 回 Step 4；减小 tileSize 或换用手动实现分块 |
| 性能无提升 | 检查是否数据量过小（<1K），高阶 API 调度开销可能抵消收益 |
| tilingData 格式不匹配 | 高阶 API 需要特定 tiling 字段（如 `baseTiling`），需适配 |
| 不支持 BF16 | 部分高阶 API 仅支持 FP16/FP32，BF16 需手动路径 fallback |
| 调试困难（API 内部黑盒） | 先用 Simple 测试验证正确性，再评估性能 |

---

**完成后在 `implementation_note.txt` 贴**：
```
[P13 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: API tmp buffer check passed
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
