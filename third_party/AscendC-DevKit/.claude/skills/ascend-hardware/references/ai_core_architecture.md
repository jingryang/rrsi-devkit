# AI Core 架构通用知识

## AI Core 内部结构

AI Core 是 Ascend NPU 的基本计算单元，每个 AI Core 包含以下组件：

### 计算单元

| 单元 | 功能 | 特点 |
|------|------|------|
| **Scalar 计算单元** | 地址计算、循环控制、分支判断 | 顺序执行，延迟低但吞吐低 |
| **Vector 计算单元** | 向量运算（Add/Mul/Exp/Compare 等） | SIMD 并行，高吞吐，element-wise 算子的主力 |
| **Cube 计算单元** | 矩阵乘法（MatMul/Conv） | 专用矩阵运算，不适用于 element-wise |

### 数据搬运单元 (MTE - Memory Transfer Engine)

| 单元 | 功能 | 方向 |
|------|------|------|
| **MTE2** | 外部存储 → 本地存储 | GM → UB (搬入) |
| **MTE3** | 本地存储 → 外部存储 | UB → GM (搬出) |
| **MTE1** | L1 相关数据搬运 | L1 ↔ L0/UB |

### 流水线并行

```
理想的三级流水（完全重叠，无气泡）:

时间 →
MTE2:  [搬入 T0] [搬入 T1] [搬入 T2] [搬入 T3] ...
Vector:          [计算 T0] [计算 T1] [计算 T2] [计算 T3] ...
MTE3:                     [搬出 T0] [搬出 T1] [搬出 T2] ...

前提条件：
- bufferNum >= 2（双缓冲）
- 各阶段耗时相近
- 同步点最少化
```

## SPMD 编程模型

每个 AI Core 独立执行相同的 Kernel 代码，通过 `GetBlockIdx()` 获取核 ID 来处理不同的数据分片。核间无直接通信，通过 Host 端的 Tiling 策略分配各核的工作负载。

## 关键硬件约束

- **32 字节对齐**: 所有 DataCopy 和 Vector 操作的地址必须 32B 对齐
- **UB 容量有限**: 每核的 UB 空间有限（芯片相关），需通过 Tiling 分片处理
- **向量宽度固定**: Vector 单元每次处理固定宽度的数据（如 256B for fp16）
