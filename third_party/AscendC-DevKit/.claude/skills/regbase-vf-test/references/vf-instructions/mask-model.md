# Mask Model —— CreateMask / UpdateMask / MaskMergeMode / MaskPattern

> **概述**：`MaskReg` 是 A5 Regbase VF 的"计算控制层"——决定寄存器里哪些 lane 参与计算、未计算的 lane 是清零还是保留旧值、tail 场景如何自动收敛。量化和归一化路径里几乎所有精度陷阱都跟 mask 有关。

**本文档定位**：这是一份**行为原理型**指南，不重复官方 API 参考。官方文档见：
- [MaskReg](../../../ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/寄存器数据类型/MaskReg.md)（含 `CreateMask` / `UpdateMask` 签名）
- [MaskMergeMode](../../../ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/数据类型/MaskMergeMode.md)

---

## 1. 为什么 mask 是 A5 编程的核心

### 1.1 硬件视角：宽 SIMD × 不整齐的数据

A5 上一条 VF 指令的宽度固定为 **VL = 256 字节**，一次能处理的元素数是 `VL_T = VL / sizeof(T)`：

| 元素类型 | VL_T | 一次处理 |
|---|---|---|
| `uint8_t` / FP8 | 256 | 256 个元素 |
| `uint16_t` / `bfloat16_t` / `half` | 128 | 128 个元素 |
| `uint32_t` / `float` | 64 | 64 个元素 |
| `uint64_t` | 32 | 32 个元素 |

真实用户数据长度几乎不会正好是 VL_T 的整数倍。要么算多、要么算少——mask 就是**唯一的处理机制**。

### 1.2 编程视角：mask 替代 `if`

A5 Regbase 强制约束**`__simd_vf__` / `__simd_callee__` 循环体内禁止 `if/else`、禁止三元运算符**（详见 `ascend_regbase_programing_guide.md` §8 Hardware Loop 规范）。任何"条件计算"都必须转成 mask 表达：

```cpp
// A3 写法（禁止在 A5 VF 里出现）
for (int i = 0; i < N; i++) {
    if (x[i] > 0) y[i] = x[i]; else y[i] = 0;
}

// A5 写法（mask 化）
Compare<GT>(mask, xReg, zeroReg, allMask);
Select(yReg, xReg, zeroReg, mask);
```

**结论**：mask 是 A5 唯一的分支替代机制。凡是"某些元素做、某些不做"、"某些元素置 0、某些保留"的语义，都必须表达成 mask。

### 1.3 陷阱视角：mask 错了会**静默出错**

Mask 相关的错误**编译器不报错**，只在精度测试时暴露：

- **粒度不对**：B16→FP32 Cast 用 `UpdateMask<uint8_t>` 而非 `<bfloat16_t>` → 部分 lane 被清零，累加值偏低
- **合并模式错**：池化窗口累积用 `ZEROING` 而非 `MERGING` → tail 部分把已累积的值清空
- **初值错**：`MaskOr` 累积起点用 `ALL` 而非 `ALLF` → 初值全 1，累积失去意义

现有 vf_experiences 的 dequant-quant 类别条目 `experience-fp8-scale-decode.md` 已踩过粒度陷阱，需要 tail padding 到 255 才能规避。**这是量化路径的最高频精度错误来源**。

---

## 2. API 签名（自包含参考）

### 2.1 MaskReg 类型

```cpp
namespace AscendC::Reg {
    class MaskReg;  // 位宽 = VL/8 = 32 字节
}
```

**关键事实**：MaskReg 位宽是 **VL 的 1/8**（32 字节 = 256 位）。每一位对应寄存器里的一个可能 lane：

| RegTensor 数据类型 | 每个 MaskReg 位含义 | 有效位数 |
|---|---|---|
| `uint8_t` | 一个字节 lane | 256 位全用 |
| `uint16_t` / `bfloat16_t` | 一个 2 字节 lane | 每 2 位有效 1 位 |
| `uint32_t` / `float` | 一个 4 字节 lane | 每 4 位有效 1 位 |
| `uint64_t` | 一个 8 字节 lane | 每 8 位有效 1 位 |

`CreateMask<T>` 中 `T` 参数决定 mask 位的**有效稀疏度**——这就是 mask 粒度的物理来源。

### 2.2 CreateMask —— 静态构造

```cpp
template <typename T, MaskPattern mode = MaskPattern::ALL, const RegTrait& regTrait = RegTraitNumOne>
__simd_callee__ inline MaskReg CreateMask();
```

**特征**：编译期确定 pattern，运行时固定不变。适合**主循环 mask、常量 mask、pattern 特殊的 mask**（如 `H`、`M3`、`ALLF`）。

### 2.3 UpdateMask —— 循环内动态收敛

```cpp
template <typename T, const RegTrait& regTrait = RegTraitNumOne>
__simd_callee__ inline MaskReg UpdateMask(uint32_t& scalarValue);
```

**特征**：`scalarValue` 是**传入传出**参数，每次调用后自动递减 `VL_T`：

```
scalarValue = (scalarValue < VL_T) ? 0 : (scalarValue - VL_T)
```

适合**循环内 tail 处理**——不用手写 tail 分支，最后一轮自动收敛。

### 2.4 MaskPattern 15 种模式速查

```cpp
enum class MaskPattern {
    ALL,      // 所有元素为 True（最常用）
    VL1,      // 最低 1 个元素
    VL2,      // 最低 2 个元素
    VL3,      // 最低 3 个元素
    VL4,      // 最低 4 个元素
    VL8,      // 最低 8 个元素
    VL16,     // 最低 16 个元素
    VL32,     // 最低 32 个元素
    VL64,     // 最低 64 个元素
    VL128,    // 最低 128 个元素
    M3,       // 3 的倍数下标
    M4,       // 4 的倍数下标
    H,        // 最低一半元素（Half）
    Q,        // 最低四分之一元素（Quarter）
    ALLF = 15 // 所有元素为 False（**累积起点专用**）
};
```

### 2.5 MaskMergeMode 三种合并模式

```cpp
enum class MaskMergeMode {
    UNKNOWN,   // API 不支持 mask 时的占位
    MERGING,   // mask=0 的 lane 保留 dst 原值
    ZEROING    // mask=0 的 lane 在 dst 中置零（默认，最常用）
};
```

---

## 3. 行为本质【核心】

### 3.1 MaskReg 位宽 = VL/8 的物理含义

一个 MaskReg 是 32 字节 = **256 位**寄存器。每位与目标 RegTensor 的一个字节 lane 对应：

```
MaskReg (256 bits):    [b255 b254 ... b3  b2  b1  b0 ]
                                                      │
                                                      ▼
RegTensor<uint8_t>:    [ ... byte3 byte2 byte1 byte0 ]  ← 每位对应一个 byte lane
RegTensor<bfloat16_t>: [ ...  bf16_1        bf16_0    ]  ← 每 2 位对应一个 bf16 lane
RegTensor<float>:      [ ...          float_0         ]  ← 每 4 位对应一个 float lane
```

**关键推论**：**同一个 MaskReg 用于 B16 计算时选中 128 个 lane（每 2 位有效 1 位），用于 B32 计算时选中 64 个 lane（每 4 位有效 1 位）**。这就是"mask 粒度必须与源类型对齐"的物理原因。

### 3.2 CreateMask vs UpdateMask 的时机差异

两者在循环里**扮演不同角色**，不能互相替代：

```
[__simd_vf__ 函数]
│
├─ MaskReg pregFull  = CreateMask<T, ALL>();     ← 编译期常量，作为主循环 mask
├─ MaskReg pregAllF  = CreateMask<T, ALLF>();    ← 累积起点，一次性
│
├─ uint32_t sreg = totalElements;                 ← 待处理元素总数
│
└─ for (uint16_t i = 0; i < loopNum; i++) {
       ├─ MaskReg pregLoop = UpdateMask<T>(sreg); ← 每轮新 mask，sreg 自动减 VL_T
       ├─ LoadAlign(xReg, ...);
       ├─ Compute(..., pregLoop);                 ← 用 tail mask
       └─ Store(..., pregFull);                   ← 或用主 mask（视需求）
    }
```

**判定原则**：
- **loop-invariant**（每轮不变）→ CreateMask
- **loop-variant**（每轮收敛）→ UpdateMask

**反面例子**：
```cpp
// ❌ 错误：把 CreateMask 放在循环内，浪费寄存器分配
for (i = 0; i < loopNum; i++) {
    MaskReg preg = CreateMask<T, ALL>();  // 每轮重新生成常量 mask
    ...
}

// ✅ 正确：CreateMask 提到循环外
MaskReg preg = CreateMask<T, ALL>();
for (i = 0; i < loopNum; i++) {
    ...
}
```

### 3.3 UpdateMask 的 scalarValue 自动递减语义

`UpdateMask` 是**唯一带副作用**的 MaskReg 构造函数——它会修改传入的 `scalarValue`：

```
初始：sreg = 300
      VL_T = 128（假设 T = bfloat16_t）

第 1 轮：pregLoop = UpdateMask<bfloat16_t>(sreg);
         → sreg = 300 - 128 = 172
         → pregLoop = ALL（128 个 lane 全 1）

第 2 轮：pregLoop = UpdateMask<bfloat16_t>(sreg);
         → sreg = 172 - 128 = 44
         → pregLoop = ALL（128 个 lane 全 1）

第 3 轮：pregLoop = UpdateMask<bfloat16_t>(sreg);
         → sreg = 44 < 128，所以 sreg = 0
         → pregLoop = 前 44 个 lane 为 1，后 84 个为 0

第 4 轮起：sreg = 0，pregLoop 全 0（继续调用无意义）
```

**关键推论**：`sreg` 必须是**循环内的局部变量或每次迭代重置**的变量，不能是持久状态。多次进入同一个 VF 函数时，每次都要重置：

```cpp
// ❌ 错误：函数级 sreg（假想）会在多次调用后耗尽
uint32_t sreg = totalCount;  // 只初始化一次
for (int outer = 0; outer < N; outer++) {
    for (int inner = 0; inner < loopNum; inner++) {
        mask = UpdateMask<T>(sreg);  // 第二轮 outer 时 sreg 已经是 0
    }
}

// ✅ 正确：每次外层循环重置 sreg
for (int outer = 0; outer < N; outer++) {
    uint32_t sreg = perOuterCount;   // 每轮重置
    for (int inner = 0; inner < loopNum; inner++) {
        mask = UpdateMask<T>(sreg);
    }
}
```

### 3.4 Mask 粒度与数据类型的对齐规则

这是**量化路径最重要的规则**。用同一寄存器做多类型计算时，mask 必须与"当前操作的源数据类型"对齐：

```
场景：B16 xReg (128 个 bfloat16 lane)  →  Cast  →  FP32 xFp32Reg (64 个 float lane)

CreateMask<bfloat16_t, ALL>  →  mask 有效位 = 128（每 2 位选 1）
                                适用于：以 B16 为源类型的操作
                                        （B16 Add/Mul/Cast<FP32, BF16>）

CreateMask<uint32_t, ALL>    →  mask 有效位 = 64（每 4 位选 1）
                                适用于：以 B32 为源类型的操作
                                        （FP32 Add/Mul/Cast<BF16, FP32>）
```

**判定口诀**：**看当前指令的源操作数是什么类型，mask 就用什么类型构造**。目标类型的宽度**不影响** mask 粒度。

**极端场景**（多次跨类型宽度切换）：

```cpp
MaskReg maskAll16 = CreateMask<bfloat16_t, ALL>();  // 128 个 B16 lane
MaskReg maskAll32 = CreateMask<uint32_t,   ALL>();  //  64 个 B32 lane

Cast<float, bfloat16_t, traitZERO>(xFp32, xBf16, maskAll16);  // 源 B16 → 用 mask16
Div (xFp32, xFp32, scaleFp32,      maskAll32);                // 源 B32 → 用 mask32
Cast<bfloat16_t, float, traitZERO>(xBf16, xFp32, maskAll32);  // 源 B32 → 用 mask32
```

**每次跨宽度切换，mask 也随之切换**。真实案例见 §5.3。

### 3.5 MaskMergeMode 三种语义对比

假设 `dstReg` 原始值为 `[?, ?, ?, ?, ?, ?, ?, ?]`（未定义），`srcReg` 计算结果为 `[a, b, c, d, e, f, g, h]`，`mask` 选中第 0、2、4、6 位（偶数下标）：

```
【ZEROING】：mask=0 的 lane 在 dst 中置 0
    dstReg = [a, 0, c, 0, e, 0, g, 0]

【MERGING】：mask=0 的 lane 保留 dst 原值
    假设 dstReg 原值 = [1, 2, 3, 4, 5, 6, 7, 8]
    dstReg = [a, 2, c, 4, e, 6, g, 8]

【UNKNOWN】：不指定或不支持 mask 时的占位
    (API 不使用 mask 参数)
```

**使用场景对照**：

| 语义 | 何时用 ZEROING | 何时用 MERGING |
|---|---|---|
| 计算类型 | Cast / Duplicate / 一般 element-wise | 跨轮累积 / 部分更新 |
| dst 是否已有数据 | 一次性覆写 | 需要保留旧值 |
| 是否 tail 场景 | tail 部分正常清零 | tail 部分**必须保留已累积值** |
| 代表算子 | 反量化路径的 Cast | 池化窗口的累加 / max_pool 的 argmax |

**关键陷阱**：默认 CastTrait 里 `MaskMergeMode` 字段推荐填 `ZEROING`，因为多布局 Cast + Add 合并偶奇下标时**必须**清空未选中的槽位（否则合并结果被垃圾数据污染）。见 `cast.md §6`。

---

## 4. 关键参数深度解析

### 4.1 MaskPattern 选型决策表

| Pattern | 语义 | 典型场景 |
|---|---|---|
| `ALL` | 全 1 | 主循环 mask、CreateMask 默认值 |
| `ALLF` | 全 0 | **累积起点**（MaskOr 初值、Select 全走另一路） |
| `VL1` | 最低 1 个 lane | 单元素存储（reduce 结果 store） |
| `VL2`~`VL128` | 最低 N 个 lane | 固定长度的部分处理 |
| `M3` | 3 的倍数下标 | 稀疏采样、每 3 个取 1 |
| `M4` | 4 的倍数下标 | 4-layout Cast 后的下标筛选 |
| `H` | 前半（`Half`） | Int4 存储（有效 lane = FP32 lane 的一半）、拆分处理 |
| `Q` | 前 1/4（`Quarter`） | Int8 极端压缩场景 |

**判定策略**：
1. 数据整齐、全宽度处理 → `ALL`
2. Tail 场景 → 用 `UpdateMask` 而不是特定 `VL_N`（除非知道确切数量）
3. 累积计算的初值 → `ALLF`
4. 输出宽度小于计算宽度（如 Int4 / Int8 压缩） → `H` / `Q`
5. 需要稀疏采样 → `M3` / `M4`

### 4.2 MaskMergeMode 选型决策表

| 场景 | 选 | 原因 |
|---|---|---|
| 一次性 Cast/Mul/Add | `ZEROING` | 未选中 lane 无意义，清零便于后续 Interleave/Pack 合并 |
| 多布局 Cast + Add 合并 | `ZEROING` | 必须清 0，否则合并被污染（`cast.md §6`） |
| 归约后广播 | `ZEROING` | 广播完毕，其他 lane 无用 |
| 池化窗口累积 max/sum | `MERGING` | tail 位置的已累积值不能丢 |
| 状态跨迭代更新 | `MERGING` | mask=0 的 lane 保持上一轮状态 |
| Reduce 累加中间态 | `MERGING` | 累积过程中未参与本轮的 lane 保留旧值 |

### 4.3 T 类型的作用（决定粒度）

`CreateMask<T, ...>` 里的 T 决定**mask 位有多"稀疏"**：

```
CreateMask<uint8_t,   ALL>()  →  256 位全 1     →  作用于 B8  RegTensor 的 256 个 lane
CreateMask<uint16_t,  ALL>()  →  256 位每 2 位 1  →  作用于 B16 RegTensor 的 128 个 lane
CreateMask<uint32_t,  ALL>()  →  256 位每 4 位 1  →  作用于 B32 RegTensor 的  64 个 lane
CreateMask<uint64_t,  ALL>()  →  256 位每 8 位 1  →  作用于 B64 RegTensor 的  32 个 lane
```

**T 选择的原则**：**与当前指令的源操作数类型对齐**（不是目标类型）。

### 4.4 regTrait 参数

大多数场景使用默认值 `RegTraitNumOne`。仅在处理 b64/complex32 且需要 512B 作用范围时使用 `RegTraitNumTwo`。

| RegTrait | 作用范围 | 生效场景 |
|---|---|---|
| `RegTraitNumOne`（默认） | 256B（一个 VL） | 大多数场景 |
| `RegTraitNumTwo` | 512B（两个 VL） | b64 或 complex32 需要覆盖两个 VL 的指令 |

**判定规则**：与配对的 RegTensor 的 regTrait 保持一致。

---

## 5. 场景化使用示例（基于 ops-nn 真实代码）

### 5.1 场景 A：基础 tail 处理 —— ALL 主 mask + UpdateMask tail

**来源**：`activation/swiglu_group/op_kernel/arch35/swiglu_group_base.h:198-222`

```cpp
template <typename T, bool withUbReduce = false>
__simd_vf__ inline void VFProcessGroupIndexSmallVf(
    __ubuf__ T* yLocalAddr, __ubuf__ T* xLocalAddr,
    uint16_t curColNum, uint16_t vlLen, uint16_t loopCount)
{
    RegTensor<T> x;
    RegTensor<T> sum;
    // 主循环 mask（loop-invariant）
    MaskReg pregMain  = CreateMask<T, MaskPattern::ALL>();
    // 单元素 store mask
    MaskReg pregMerge = CreateMask<T, MaskPattern::VL1>();

    Duplicate(sum, static_cast<T>(0), pregMain);
    uint32_t sreg = curColNum;

    MaskReg pregLoop;
    for (uint16_t i = 0; i < loopCount; i++) {
        pregLoop = UpdateMask<T>(sreg);                    // tail mask
        LoadAlign(x, xLocalAddr + i * vlLen);
        Adds(x, x, static_cast<T>(0), pregLoop);           // tail 位清零
        Add(sum, sum, x, pregMain);                        // 全宽度累加
    }
    ReduceSum(sum, sum, pregMain);
    // ...
    StoreAlign(yLocalAddr, sum, pregMerge);                // 只 store 1 个元素
}
```

**要点分析**：
- `pregMain` 用 `CreateMask<T, ALL>` 建立"整寄存器全 1" mask，作为**循环内累加 sum 的 mask** —— 每轮 sum 都是完整 VL 宽度累加
- `pregLoop = UpdateMask<T>(sreg)` 在**每次迭代内更新** tail mask —— `sreg` 自动递减，最后一轮只有前 `curColNum % VL` 位为 1
- `Adds(x, x, 0, pregLoop)` **借用"加零"这个 no-op 触发 mask 生效**（默认 ZEROING），把 tail 位置的 x 清零，避免污染 sum
- `pregMerge = CreateMask<T, VL1>` 用于最后单元素 store —— 三种 mask 各司其职

### 5.2 场景 B：多 Pattern 分层设计 —— ALL / VL1 / H 并存

**来源**：`norm/rms_norm_quant_v2/op_kernel/arch35/rms_norm_quant_v2_regbase_full_load.h:575-614`

```cpp
RegTensor<float> xReg, rstdReg, gammaReg, betaReg;
RegTensor<float> scales1Reg, zeroPoints1Reg;
RegTensor<float> mul1Reg, mul2Reg;

// 三种 mask 各司其职
MaskReg pregFull  = CreateMask<float, MaskPattern::ALL>();  // 主宽度
MaskReg pregOne   = CreateMask<float, MaskPattern::VL1>();  // 单元素
MaskReg mask4Int4 = CreateMask<float, MaskPattern::H>();    // Int4 输出宽度

// 加载 loop-invariant 的 scale / zero_point（全宽度）
LoadScalarForDtypeTIn(scales1Addr,      scales1Reg,     pregFull, 0);
LoadScalarForDtypeTIn(zeroPoints1Addr,  zeroPoints1Reg, pregFull, 0);

for (uint16_t i = 0; i < loopsA; i++) {
    uint32_t sregElewiseNum = numR;
    LoadScalarForDtypeTIn(rstdAddr, rstdReg, pregFull, i);

    for (uint16_t j = 0; j < loopsR; j++) {
        // 每轮 tail mask
        MaskReg pregCurLoop = UpdateMask<float>(sregElewiseNum);

        LoadTensorForDtypeTIn(xAddr, xReg, pregCurLoop,
                              (i * sregxGammaBetaAlign + j * vectorLenB32));
        Mul(mul1Reg, xReg, rstdReg,     pregCurLoop);
        LoadTensorForDtypeTIn(gammaAddr, gammaReg, pregCurLoop, (j * vectorLenB32));
        Mul(mul2Reg, gammaReg, mul1Reg, pregCurLoop);
        // ... 量化到 Int4 时使用 mask4Int4
    }
}
```

**要点分析**：
- **一个函数一次性声明 3 个 mask**：`ALL`（主宽度）、`VL1`（单元素）、`H`（Int4 输出宽度 = FP32 lane 的一半）
- `H` 模式的物理含义：Int4 元素宽度是 FP32 的 1/8，打包后有效 lane 数正好是 FP32 的 1/2
- Mask 的**分层原则**：跨函数不变的用 CreateMask 一次建立，编译器可优化；每次迭代变化的用 UpdateMask，循环内动态
- 类似组合参考：`matmul/weight_quant_batch_matmul_v2_vf.h:933-936` 用 `ALL + Q + MaskNot` 拼出"低 32 位为 0、高 96 位为 1"的自定义 border mask（跨 group 权重边界）

### 5.3 场景 C：多类型宽度切换 —— maskAll16 / maskAll32 精准配对

**来源**：`quant/dynamic_dual_level_mx_quant/op_kernel/arch35/dynamic_dual_level_mx_quant_base.h:561-596`

```cpp
template <typename xDtype, RoundMode roundMode, bool needSmoothScale>
__simd_callee__ inline void CalcXTmp(
    __ubuf__ xDtype* xTmpUbAddr,
    RegTensor<float> level0ScaleReg,
    RegTensor<xDtype> xReg,
    RegTensor<float>& xZeroFP32,
    RegTensor<float>& xOneFP32)
{
    RegTensor<xDtype> xZero, xOne, zero;
    MaskReg zeroMask;

    // 关键：两个不同粒度的 mask
    MaskReg maskAll16 = CreateMask<xDtype,   MaskPattern::ALL>();  // B16 粒度
    MaskReg maskAll32 = CreateMask<uint32_t, MaskPattern::ALL>();  // B32 粒度

    Duplicate(zero, 0);

    // 【B16 域】：源 = xDtype (BF16/half)
    Compare<xDtype, CMPMODE::EQ>(zeroMask, xReg, zero, maskAll16);
    Cast<float, xDtype, castTraitXdtypetoFp32Zero>(xZeroFP32, xReg, maskAll16);  // 源 B16
    Cast<float, xDtype, castTraitXdtypetoFp32One>(xOneFP32,  xReg, maskAll16);   // 源 B16

    // 【B32 域】：源 = float
    Div(xZeroFP32, xZeroFP32, level0ScaleReg, maskAll32);
    Div(xOneFP32,  xOneFP32,  level0ScaleReg, maskAll32);

    // 【回 B16 域】：源 = float, 目标 = BF16 —— 注意 mask 仍用 maskAll32（源 B32）
    Cast<xDtype, float, castTraitFp32toBF16>(xZero, xZeroFP32, maskAll32);
    Cast<xDtype, float, castTraitFp32toBF16>(xOne,  xOneFP32,  maskAll32);

    // ... Interleave 合并
    Select<xDtype>(xZero, xReg, xZero, zeroMask);   // 保留原 zero 位置

    DataCopy(xTmpUbAddr, xZero, maskAll16);         // B16 搬出
}
```

**要点分析**：
- `maskAll16` 有效 128 个 lane（每 2 位有效 1 位），用于所有**源类型是 xDtype (B16)** 的操作
- `maskAll32` 有效 64 个 lane（每 4 位有效 1 位），用于所有**源类型是 float (B32)** 的操作
- **注意 Cast<xDtype, float>（B32 → B16）用 maskAll32** —— 因为源操作数是 float，不是 xDtype
- **每次跨类型宽度切换，mask 也切换** —— 这是量化路径最容易搞错的地方，也是最常见的静默精度错误来源

**CastTrait 配套定义**（同文件 88-101 行）：
```cpp
static constexpr CastTrait castTraitXdtypetoFp32Zero = {
    RegLayout::ZERO, SatMode::UNKNOWN, MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
static constexpr CastTrait castTraitFp32toBF16 = {
    RegLayout::ZERO, SatMode::NO_SAT, MaskMergeMode::ZEROING, RoundMode::CAST_RINT};
```
**所有 CastTrait 固定用 ZEROING**——不清 0 的话，多布局 Cast 后 Interleave 合并会被污染。

### 5.4 场景 D：MaskOr 累积 —— 池化窗口跨迭代记录状态

**来源**：`pooling/max_pool_with_argmax/op_kernel/arch35/max_pool_with_argmax_nhwc_small_c.h:59-128`

```cpp
MaskReg gtMask, gtMaskT2;
MaskReg computeT1  = UpdateMask<T1>(numT1);
MaskReg computeT2  = UpdateMask<T2>(numT2);
MaskReg maskAllU32 = CreateMask<uint32_t, MaskPattern::ALL>();
MaskReg maskAllT2  = CreateMask<T2,       MaskPattern::ALL>();

// 【关键】：flagMask 初值必须是 ALLF（全 0），累积起点
MaskReg flagMask = CreateMask<T2, MaskPattern::ALLF>();

for (each pooling window position) {
    // 生成本轮 GT mask（瞬时）
    if constexpr (NANPROP == 1) {
        Compare<T1, CMPMODE::LE>(gtMask, vd1, vd0, computeT1);
        MaskNot(gtMask, gtMask, computeT1);  // NaN 传播技巧
    } else {
        Compare<T1, CMPMODE::GT>(gtMask, vd1, vd0, computeT1);
    }

    // 更新真实数据
    Select(argmaxHRes, argmaxUpdateHVreg, argmaxHRes, gtMask);
    Select(argmaxWRes, argmaxUpdateWVreg, argmaxWRes, gtMask);

    // 【关键】：累积到 flagMask —— 只要窗口内至少一次 GT 成立，flagMask 就置 1
    MaskOr(flagMask, flagMask, gtMask, computeT2);

    // 更新当前最大值
    Select(vd0, vd1, vd0, gtMask);
}
```

**要点分析**：
- `gtMask` 是**瞬时 mask**（只反映本轮 Compare 结果）
- `flagMask` 是**累积 mask**（跨轮 OR，记录窗口内是否 GT 过）
- **累积起点必须用 `ALLF`（全 0）**——如果用 `ALL`（全 1）初始化，OR 累积没有意义（永远是 1）
- Select 用 gtMask 更新真实数据，MaskOr 用同一个 gtMask 更新元数据 flagMask —— **两条路径共享同一 mask**
- NANPROP 分支：`Compare<LE>` + `MaskNot` 让 NaN 也参与 argmax 更新（因为 NaN 参与任何比较都是 false，取反后 NaN 位置变 true）

### 5.5 场景 E：MERGING 保留旧值 —— 池化窗口累积

**来源**：`pooling/avg_pool/op_kernel/arch35/avg_pool_common.h:1362-1375`（相同思路见 `pooling/max_pool_v3/op_kernel/arch35/max_pool_v3_common.h:965-983`）

```cpp
template <bool MaskMergeModeEnable, typename T, typename U>
__aicore__ inline void SumWithGather(
    RegTensor<T>& res, __local_mem__ T* srcAddr,
    RegTensor<U>& index, MaskReg& mask)
{
    RegTensor<T> vd1;
    DataCopyGather(vd1, srcAddr, index, mask);

    if constexpr (MaskMergeModeEnable) {
        RegTensor<T> tmp;
        Add(tmp, vd1, res, mask);
        // 【关键】：Copy 用 MERGING —— tmp 覆盖 mask=1 的 lane，mask=0 的 lane 保留 res 旧值
        Copy<T, MaskMergeMode::MERGING>(res, tmp, mask);
    } else {
        // Add 内建 mask 语义时，直接用 mask
        Add(res, vd1, res, mask);
    }
}
```

**要点分析**：
- **场景痛点**：池化窗口跨多次 Gather 累积到同一 `res`。当 tail 迭代 mask 只覆盖部分 lane 时，如果用 ZEROING，那些"未参与本轮"的 lane 会被清零 —— 但它们其实存着**上一轮已累积的值**，不能丢
- **解决方案**：先 `Add(tmp, ...)`（默认 ZEROING）算出新值，再用 `Copy<MERGING>(res, tmp, mask)` **把新值写到 mask=1 的位置，mask=0 位置保留 res 旧值**
- MERGING 的核心语义：**"选择性覆写" 而非 "清零覆写"**
- 也可以直接用 `Add(res, vd1, res, mask)` 让 Add API 走 MERGING 模式（当 API 支持 mask 参数时），代码中 `else` 分支就是这样。两种写法等价，但 `Copy<MERGING>` 更清晰地表达"我在做部分寄存器更新"

### 5.6 场景 F：GatherMask + AR 变长输出

**来源**：`index/index_fill/op_kernel/arch35/index_fill_common.h:144-189`

```cpp
template<typename INDEX_TYPE>
__simd_callee__ inline void ComputeUniqueIdNumInt32(
    __ubuf__ INDEX_TYPE* sortedInputAddr,
    __ubuf__ int32_t* uniqueIndicesAddr,
    uint16_t loopCnt, int64_t dataLen)
{
    uint32_t counter = dataLen + 1;
    RegTensor<int32_t> orderReg, selReg;
    RegTensor<INDEX_TYPE> sortedIdxReg, sortedIdxShiftOneReg;
    MaskReg cmpMask, maskReg;
    UnalignReg u0, uOut;

    for (uint16_t i = 0; i < loopCnt; ++i) {
        Arange(orderReg, i * VFLEN_INT32);           // 生成 [iVL, iVL+1, ..., iVL+VL-1]
        maskReg = UpdateMask<INDEX_TYPE>(counter);   // tail mask

        auto startAddr = sortedInputAddr + i * VFLEN_INT32;
        DataCopy(sortedIdxReg, startAddr);
        DataCopyUnAlignPre(u0, startAddr - 1);
        DataCopyUnAlign<INDEX_TYPE>(sortedIdxShiftOneReg, u0, startAddr - 1);

        // 【关键】：Compare 生成"与前一个不相等"的 mask（唯一值起点）
        Compare<INDEX_TYPE, CMPMODE::NE>(cmpMask, sortedIdxReg, sortedIdxShiftOneReg, maskReg);

        // 【关键】：GatherMask<STORE_REG> 把 cmpMask=1 的位置压缩到 selReg 低位
        //         同时 AR 寄存器自动累加实际写入的字节数
        GatherMask<int32_t, GatherMaskMode::STORE_REG>(selReg, orderReg, cmpMask);

        DataCopyUnAlign<int32_t, PostLiteral::POST_MODE_UPDATE>(
            uniqueIndicesAddr, selReg, uOut);
    }
    DataCopyUnAlignPost(uniqueIndicesAddr, uOut);
}

// __aicore__ 侧读取实际输出长度
__aicore__ inline uint32_t ComputeUniqueIdNum(...)
{
    ClearSpr<SpecialPurposeReg::AR>();      // 清零 AR 计数器
    ComputeUniqueIdNumVf<INDEX_TYPE>(...);
    // 从 AR 读取总字节数，除以元素大小得到实际输出个数
    uint32_t uniqueIdNum = (GetSpr<SpecialPurposeReg::AR>() / sizeof(int32_t)) - 1;
    return uniqueIdNum;
}
```

**要点分析**：
- **背景**：Unique / non_zero / scatter_nd 等**输出长度未知**的算子，kernel 无法预知输出个数
- `Arange(orderReg, i * VFLEN)` 生成"位置索引"寄存器 `[i*VL, i*VL+1, ..., i*VL+VL-1]`
- `Compare<NE>` 找出"与前一个不相等"的位置——排序后这些位置就是唯一值起点
- `GatherMask<STORE_REG>` **把 cmpMask=1 的 orderReg 值压缩到 selReg 低位**，同时 **AR 寄存器自动累加实际写入的字节数**
- 循环结束后 `GetSpr<SpecialPurposeReg::AR>()` 读出总字节数——**这是 CANN vector 侧变长输出的通用范式**
- 使用前必须 `ClearSpr<AR>()` 清零 AR 计数器

---

## 6. 常见陷阱（错误 vs 正确）

### 6.1 Mask 粒度与源类型不匹配

**症状**：B16→FP32 Cast 后，奇数下标 lane 输出为 0 或垃圾值。精度 `atol=1e-5` 掩盖时会假通过，输入值大时暴露。

```cpp
// ❌ 错误：BF16→FP32 用 uint8_t 粒度 mask
MaskReg mask = UpdateMask<uint8_t>(count);
Cast<float, bfloat16_t, castTrait_1>(xFp32One, xBf16, mask);
// mask 每 1 位对应 1 个 lane，用于 B16 时 count < VL 时会误清零

// ✅ 正确：与源类型对齐
MaskReg mask = CreateMask<bfloat16_t, MaskPattern::ALL>();
Cast<float, bfloat16_t, castTrait_1>(xFp32One, xBf16, mask);
```

**追加防护**（若 count 是不确定的 tail 值）：
```cpp
// 若必须处理 tail：对最后一个 loop 做 padding，把逻辑长度扩展到 VL
// 见 vf_experiences/dequant-quant/experience-fp8-scale-decode.md
```

**根因**：多布局 Cast 的 mask 语义要求**每一位对应一个源元素**。用 `<uint8_t>` 时 mask 每 1 位对应 1 个 B8 lane，作用在 B16 计算上时高 lane 被误认为"未选中"。

### 6.2 ZEROING vs MERGING 用错

**症状**：池化累积、状态跨轮更新时，tail 部分把已累积的值清空。

```cpp
// ❌ 错误：池化窗口累积 max 用 ZEROING
MaskReg mask = UpdateMask<float>(count);
for (window) {
    Max(res, vd1, res, mask);  // 默认 ZEROING，tail 位 res 被清空！
}

// ✅ 正确：用 MERGING 保留旧值
for (window) {
    RegTensor<float> tmp;
    Max(tmp, vd1, res, mask);
    Copy<float, MaskMergeMode::MERGING>(res, tmp, mask);
}

// ✅ 或：API 直接支持 mask 语义
for (window) {
    Max(res, vd1, res, mask);  // 若 Max 支持内建 MERGING
}
```

### 6.3 累积起点用 ALL 而非 ALLF

**症状**：MaskOr 累积后 flagMask 永远全 1，起不到"记录曾经 GT 过"的作用。

```cpp
// ❌ 错误：Or 累积初值全 1
MaskReg flagMask = CreateMask<T, MaskPattern::ALL>();
for (window) {
    Compare<GT>(gtMask, vd1, vd0, mask);
    MaskOr(flagMask, flagMask, gtMask, mask);  // 永远全 1
}

// ✅ 正确：累积初值全 0
MaskReg flagMask = CreateMask<T, MaskPattern::ALLF>();
for (window) {
    Compare<GT>(gtMask, vd1, vd0, mask);
    MaskOr(flagMask, flagMask, gtMask, mask);  // 只要一次 GT 就置 1
}
```

**根因**：`ALLF = 15` 是**为累积场景专门设计的"全 0" pattern**。而 `ALL` 是"全 1"（默认值），适合作为主循环 mask。

### 6.4 UpdateMask 循环外调用 / scalarValue 已耗尽

**症状**：多次进入 VF 函数后，第二次调用的 mask 全 0，计算不生效。

```cpp
// ❌ 错误：sreg 定义在外层，第二次外层循环时已经是 0
uint32_t sreg = totalCount;  // 只初始化一次
for (int outer = 0; outer < N; outer++) {
    for (int inner = 0; inner < loopNum; inner++) {
        mask = UpdateMask<T>(sreg);  // 第二轮 outer 时 sreg = 0
    }
}

// ✅ 正确：每次外层循环重置
for (int outer = 0; outer < N; outer++) {
    uint32_t sreg = perOuterCount;  // 每轮重置
    for (int inner = 0; inner < loopNum; inner++) {
        mask = UpdateMask<T>(sreg);
    }
}
```

**根因**：`UpdateMask` 有副作用（`scalarValue` 自动递减）。必须确保每次进入循环时 `scalarValue` 是正确的初值。

### 6.5 多布局 Cast 缺 ZEROING

**症状**：多布局 Cast 后 Interleave 合并的结果里，未选中 lane 是垃圾数据（污染 Add 合并）。

```cpp
// ❌ 错误：CastTrait 用 MERGING（默认写法不当）
static constexpr CastTrait traitBad = {
    RegLayout::ZERO,
    SatMode::UNKNOWN,
    MaskMergeMode::MERGING,   // ← 保留旧数据
    RoundMode::UNKNOWN};

Cast<bf16, float, traitBad>(vdEven, vdSrc, mask);
Cast<bf16, float, traitBad>(vdOdd,  vdSrc, mask);
Add(vdEven, vdEven, vdOdd, mask);  // 两侧未选中 lane 都是垃圾，合并被污染

// ✅ 正确：CastTrait 用 ZEROING
static constexpr CastTrait traitGood = {
    RegLayout::ZERO,
    SatMode::UNKNOWN,
    MaskMergeMode::ZEROING,   // ← 未选中 lane 清零
    RoundMode::UNKNOWN};

Cast<bf16, float, traitGood>(vdEven, vdSrc, mask);
Cast<bf16, float, traitGood>(vdOdd,  vdSrc, mask);
Add(vdEven, vdEven, vdOdd, mask);  // 未选中 lane 是 0，合并干净
```

详见 `cast.md §6 关键规则：ZEROING 掩码`。

### 6.6 循环内反复 CreateMask

**症状**：性能损失（编译器可能不做常量折叠，运行时反复构造）。

```cpp
// ❌ 错误：CreateMask 是编译期常量，放循环内浪费
for (i = 0; i < loopNum; i++) {
    MaskReg preg = CreateMask<T, MaskPattern::ALL>();
    Compute(..., preg);
}

// ✅ 正确：CreateMask 提到循环外
MaskReg preg = CreateMask<T, MaskPattern::ALL>();
for (i = 0; i < loopNum; i++) {
    Compute(..., preg);
}
```

**判定原则**：**loop-invariant 的 CreateMask 都应提到循环外**（详见 `ascend_regbase_programing_guide.md` §13 循环内优化）。

---

## 7. 相关模式

Mask 在几乎所有 VF Pattern 里都是核心组件：

| Pattern | 用到的 Mask 特性 | 位置 |
|---|---|---|
| Pattern 1.1（FP8→FP32） | 多布局 Cast + ZEROING | INDEX.md § 1.1 |
| Pattern 1.2（FP8→BF16 with Add 合并） | ZERO/ONE + ZEROING + Add | INDEX.md § 1.2 |
| Pattern 1.3（FP4 手动解码） | maskAll + M3 稀疏 | INDEX.md § 1.3 |
| Pattern 1.4（FP4 快速解码） | maskU8 单粒度 | INDEX.md § 1.4 |
| Pattern 1.5（FP8_E8M0 Scale 预处理） | maskAll16 单一 mask | INDEX.md § 1.5 |
| Pattern 1.7（Self-Interleave 广播扩展） | maskAll16 | INDEX.md § 1.7 |

**未来 Pattern**（待建）：
- Pattern 2.x（element-wise + DAG）：主要用 `ALL + UpdateMask tail` 模式
- Pattern 3.x（Reduce+Broadcast norm）：`ALL` + `VL1`（reduce 结果 store）
- Pattern 4.x（Softmax 3-pass）：`ALL` + `ALLF`（累积起点）
- Pattern 10.x（GatherMask 变长输出）：`ALLF` + `MaskOr` 累积
- Pattern 11.x（Bitmask 累积 Pooling/Argmax）：MERGING + MaskOr

---

## 8. 相关知识源

- 官方 API：[MaskReg](../../../ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/寄存器数据类型/MaskReg.md)（含 `CreateMask` / `UpdateMask` 签名）
- 官方 API：[MaskMergeMode](../../../ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/Reg矢量计算/数据类型/MaskMergeMode.md)
- Mask 相关运算：`MaskReg计算/` 目录（Interleave / DeInterleave / Pack / UnPack / Select / Move / MoveMask）
- 硬件约束：[ascend_regbase_programing_guide.md](../ascend_regbase_programing_guide.md) § 8 Hardware Loop 规范、§ 11 寄存器资源管理
- 历史经验：[experience-fp8-scale-decode.md](../vf_experiences/dequant-quant/experience-fp8-scale-decode.md)（B16→FP32 Cast 的 mask 粒度陷阱）
- 相关单指令文档：[cast.md](cast.md) § 6（ZEROING 关键规则）、[interleave.md](interleave.md)、[load-align.md](load-align.md)、[store-align.md](store-align.md)

---

## 9. 引用协议（S2 使用）

| 引用前缀 | 定位章节 | 使用时机 |
|---|---|---|
| `vf-instructions:mask-model` | 本文档整体 | Compute 涉及 Mask 构造/使用/合并模式的场景 |
| `vf-instructions:mask-model#tail` | § 5.1 tail 处理 | 循环 tail 场景 |
| `vf-instructions:mask-model#粒度` | § 3.4 + § 6.1 | 多类型宽度切换的量化路径 |
| `vf-instructions:mask-model#merge-mode` | § 3.5 + § 6.2 | 累积计算、状态更新场景 |
| `vf-instructions:mask-model#accumulate` | § 5.4 + § 6.3 | MaskOr/MaskAnd 累积场景 |
| `vf-instructions:mask-model#gather-mask` | § 5.6 | 变长输出场景 |

**触发规则**（供 s2-analysis 判断）：

| 算子设计特征 | 应追加 | 追加到哪一行 |
|---|---|---|
| Compute 包含 CreateMask / UpdateMask（几乎所有 A5 算子）| `vf-instructions:mask-model` | C.3 Compute |
| Compute 有跨类型宽度切换（B16 ↔ B32） | 追加 `#粒度` | C.3 Compute |
| Compute 有池化窗口累积 / 状态跨轮更新 | 追加 `#merge-mode` | C.3 Compute |
| Compute 有 MaskOr/MaskAnd 累积 | 追加 `#accumulate` | C.3 Compute |
| 算子有变长输出（Unique/TopK/SparseSlice） | 追加 `#gather-mask` | C.3 Compute |
