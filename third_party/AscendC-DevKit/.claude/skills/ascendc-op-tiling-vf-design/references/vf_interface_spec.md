# VF 接口规范

每个 VF 的接口由四要素定义。

## 四要素

```
┌──────────────────────────────────────────────────┐
│  VF_N                                            │
│                                                  │
│  输入端口（input ports）                           │
│  ├── {name, dtype, from}                         │
│  │   from ∈ {copy_in, vf_M, tiling_data, scalar} │
│  │   dtype 可为单一类型或该端口支持的类型列表      │
│                                                  │
│  输出端口（output ports）                         │
│  ├── {name, dtype, to, storage}                  │
│  │   to ∈ {vf_M, copy_out}                       │
│  │   storage: UB buffer 名                       │
│  │   dtype 可为单一类型或该端口支持的类型列表      │
│                                                  │
│  支持的 dtype 组合矩阵                             │
│  └── supported_dtype_combinations[]              │
│      每个元素 = {inputs: {name→dtype}, outputs: {name→dtype}} │
│      vf-test 阶段必须对该矩阵中每种组合做精度验证  │
│                                                  │
│  计算公式（formula）                              │
│  └── 数学表达式                                   │
│                                                  │
│  计算操作序列（compute_ops）                       │
│  └── AscendC SIMD 操作列表，按执行顺序            │
│      (load) → op_1 → op_2 → ... → (store)        │
└──────────────────────────────────────────────────┘
```

## compute_ops 示例

| formula | compute_ops |
|---------|------------|
| `mean_sq = reduce_sum(x²) / D` | `[Mul(x,x), ReduceSum, Div(D)]` |
| `rstd = rsqrt(mean_sq + ε)` | `[Adds(mean_sq, ε), Rsqrt]` |
| `y = x * rstd * γ` | `[Mul(x, rstd), Mul(tmp, γ)]` |
| `y = max(x, 0)` | `[Maxs(x, 0)]` |
| `y = exp(x - max)` | `[Sub(x, max_brc), Exp]` |

## 代码 ↔ 接口映射规则

以消费上游 VF 输出的多输入 VF 为例：

### 代码 → VF 接口

| 代码元素 | → VF 接口字段 | 示例 |
|---------|-------------|------|
| `LocalTensor<T> xLocal`（只读） | `inputs: {name, from: copy_in_*, dtype: T}` | `{name: x, from: copy_in_x, dtype: fp16}` |
| `LocalTensor<T> yLocal`（只写） | `outputs: {name, to: copy_out, dtype: T}` | `{name: y, to: copy_out, dtype: fp16}` |
| `LocalTensor<float> rstdLocal`（只读，来自上游 VF） | `inputs: {name, from: vf_N, dtype: float}` | `{name: rstd, from: vf_1, dtype: fp32}` |
| `uint64_t curUbFactor` 等标量 | `inputs: {name, from: tiling_data, dtype: scalar}` | `{name: N, from: tiling_data, dtype: scalar}` |
| `LoadRegForDtype / DataCopy` | `compute_ops` 中的 Load 项 | `Load(x)` 或 `Load(rstd, BRC)` |
| `Mul / Add / Sub / ...` | `compute_ops` 中的计算项 | `Mul(x, rstd)` |
| `StoreRegForDtype / DataCopy` | `compute_ops` 中的 Store 项 | `Store(y)` |

### VF 接口 → 代码生成

| VF 接口字段 | → 生成的代码 |
|-----------|------------|
| `inputs: [{name: x, from: copy_in_x, dtype: fp16}]` | `LocalTensor<half> xLocal = inQueueX.DeQue<half>()` |
| `inputs: [{name: rstd, from: vf_1, dtype: fp32}]` | 函数参数 `LocalTensor<float> rstdLocal` |
| `outputs: [{name: y, to: copy_out, dtype: fp16}]` | 函数参数 `LocalTensor<half> yLocal`（写），后跟 `outQueueY.EnQue<half>(yLocal)` |
| `compute_ops: [Mul(x, rstd), Mul(tmp, γ)]` | `Mul(mul1Reg, xReg, RstdReg, mask); Mul(mul2Reg, mul1Reg, gammaReg, mask)` |

## dtype 组合矩阵

每个 VF 必须声明其**支持的 dtype 组合矩阵** `supported_dtype_combinations`，作为 vf-test 阶段的验证契约：

- 矩阵中的每一行代表一种需要独立验证的输入/输出 dtype 组合。
- 同种组合下，所有输入端口、输出端口的 dtype 必须同时确定。
- 当算子接口要求支持多种输入 dtype（如 fp16、bf16、fp32）或多种输出 dtype（如归约结果 fp32/fp16）时，矩阵必须穷举所有合法组合。
- vf-test 阶段**不得只测最简单的一种组合**；未在矩阵中声明的组合不应由 s4-coding 通过修改 VF 函数体来临时支持。

**示例**：某归约 VF 支持输入 fp16/bf16/fp32，输出固定 fp32：

```yaml
supported_dtype_combinations:
  - inputs: {x: fp16}
    outputs: {y: fp32}
  - inputs: {x: bf16}
    outputs: {y: fp32}
  - inputs: {x: fp32}
    outputs: {y: fp32}
```

## 函数签名规范

每个 VF 必须输出完整的 `__aicore__ inline void` 函数签名，格式对标 AscendC RegBase 规范。

### 签名模板

```cpp
// 新增 VF 函数
template <typename DX, typename DG>                          // 模板参数（如有）
__aicore__ inline void ComputeXxx(                           // 函数名: 功能名 + 可选 VF 后缀
    LocalTensor<DX>& xLocal,                                 // 只读输入: LocalTensor<T>&
    LocalTensor<float>& dstLocal,                            // 只写输出: LocalTensor<T>&
    LocalTensor<float>& tmpLocal,                            // 临时空间: LocalTensor<T>&
    uint16_t rows,                                           // tiling 标量参数
    uint32_t stride,                                         // tiling 标量参数
    ...)
```

### 参数类型约定

| 参数角色 | AscendC 类型 | 传递方式 | 示例 |
|---------|-------------|---------|------|
| UB 输入 (只读) | `LocalTensor<T>&` | 引用 | `LocalTensor<DX>& xLocal` |
| UB 输出 (只写) | `LocalTensor<T>&` | 引用 | `LocalTensor<float>& dstLocal` |
| UB 临时空间 | `LocalTensor<T>&` | 引用 | `LocalTensor<float>& tmpLocal` |
| Tiling 标量 | `uint16_t` / `uint32_t` / `uint64_t` / `float` | 值 | `uint16_t rows` |
| UB buffer (备选) | `TBuf<TPosition::VECCALC>&` | 引用 | `TBuf<...>& tmpBuf` |

### 函数定位标注

每个 VF 均为本算子新增函数，需给出完整的签名 + 参数表 + 伪代码。
VF 设计方案是独立文档，所有函数在本算子文件内自包含定义，不引用外部算子 helper。

### 调用点示例 (在 Process 主循环内)

```cpp
// 每个 VF 独立调用，调用方负责 buffer 的 AllocTensor / FreeTensor
LocalTensor<float> sumSqLocal = sumSqBuf.AllocTensor<float>();
CalculateAddSquareReduceVF<DX>(
    x1Local, x2Local, xFp32Local, sumSqLocal,
    currentRows, numColAlign, numCol, colLoopFactor, blockSizeB32);
```

## 关键约束

- VF 不分配 UB——UB 由 Process 调用方通过 `AllocTensor` 分配，VF 只接收 `LocalTensor<T>` 或 `__local_mem__ T*`
- VF 间数据通过 UB 传递，不经过 GM
- 输入/输出端口一一对应到 UB buffer，buffer 命名与 `ub_layout` 一致
- `compute_ops` 是代码生成的核心输入——每个 op 直接映射到一条 AscendC SIMD 指令
- **函数签名风格**：`LocalTensor<T>&` 传引用，tiling 标量传值
