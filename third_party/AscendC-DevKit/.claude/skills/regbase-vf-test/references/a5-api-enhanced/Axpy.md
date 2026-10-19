# Axpy

**页面ID:** atlasascendc_api_07_00056  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00056.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

根据mask对输入数据dstReg、srcReg、scalarValue按元素做乘加操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_00056_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, typename U, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void Axpy(S& dstReg, S& srcReg, const U scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half/float/uint64_t/int64_t |
| U | 标量源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：half/float/uint64_t/int64_t |
| mode | 选择MERGING模式或ZEROING模式。当前仅支持ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。仅支持该模式。 |
| S | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数和源操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 两个源操作数的数据类型需要与目的操作数保持一致。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 两个源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

dstReg和srcReg可以为同一个RegTensor。

#### 调用示例

```
template<typename T, typename U>
static __simd_vf__ inline void AxpyVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, U scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(dstReg, dstAddr + i * oneRepeatSize);
        AscendC::Reg::Axpy(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Axpy 实例

### 实例 1：mish::MishCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Cast, CompareScalar, DataCopy, Div, Exp, LoadDist, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Axpy 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: 在 Mish 前向计算中，用 Axpy 把 e^x 乘系数 2 后累加到 e^2x 上，得到分子 e^2x + 2e^x，将 Mul+Add 合为单条向量指令。

（行 73-97）

```cpp
if constexpr (std::is_same_v<T, float>) {
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(vregInput,
                                                         (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
} else {
    Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(
        vregInput16, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::Cast<float, T, castTrait0>(vregInput, vregInput16, mask);
}
Reg::Muls(vregInputNegNumerator, vregInput, FP32_NEG_ONE, mask);             // -x
Reg::Muls(vregInputNegDenominator, vregInput, FP32_NEG_TWO, mask);           // -2x
Reg::Exp(vregInputNegNumerator, vregInputNegNumerator, mask);                // e^-x
Reg::Exp(vregInputNegDenominator, vregInputNegDenominator, mask);            // e^-2x
Reg::Muls(vregInputNegNumerator, vregInputNegNumerator, FP32_TWO, mask);     // 2e^-x
Reg::Adds(vregInputNegNumerator, vregInputNegNumerator, FP32_ONE, mask);     // 2e^-x + 1
Reg::Muls(vregInputNegDenominator, vregInputNegDenominator, FP32_TWO, mask); // 2e^-2x
Reg::Add(vregInputNegDenominator, vregInputNegNumerator, vregInputNegDenominator, mask);
Reg::Div(vregOutput, vregInputNegNumerator, vregInputNegDenominator, mask);

Reg::Muls(vregInputNumerator, vregInput, FP32_TWO, mask);            // 2x
Reg::Exp(vregInputNumerator, vregInputNumerator, mask);              // e^2x
Reg::Exp(vregInputDenominator, vregInput, mask);                     // e^x
Reg::Axpy(vregInputNumerator, vregInputDenominator, FP32_TWO, mask); // e^2x + 2e^x
Reg::Adds(vregInputDenominator, vregInputNumerator, FP32_TWO, mask); // e^2x + 2e^x + 2
Reg::Div(vregInputNumerator, vregInputNumerator, vregInputDenominator, mask);
```

**要点**: 1) Axpy(dst,src,scalar,mask) 语义为 dst = src*scalar + dst，dst 同时是输入和输出。2) 与 Exp/Muls/Adds 组合完成 mish 公式 softplus(2x) 分子构造。3) mask 来自 UpdateMask 按 count 控制尾批有效元素。

### 实例 2：gelu_grad::GeluGradCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Compare, DataCopy, Div, DivSpecificMode, Duplicate, Exp, MaskMergeMode, MaskReg, Mul, RegTensor, RegTraitNumOne, Select, UpdateMask
- **Axpy 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: GeluGrad 的 erf 近似多项式求值中，先用 Duplicate 把寄存器初始化为常数(BETAN/BETA)，再用 Axpy 累加 x²·系数 项，实现 ax²+b 的融合乘加。

（行 71-100）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    Reg::Duplicate(vregInputPX, BETAN);
    // OpCopyIn
    Reg::DataCopy(vregInputDy, (__ubuf__ T*)(src0Addr + loopIdx * vlSize));
    Reg::DataCopy(vregInputX, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));
    // compute
    Reg::Mul(vregInputXSqr, vregInputX, vregInputX, mask);
    Reg::Axpy(vregInputPX, vregInputXSqr, AN, mask);
    Reg::Mul(vregInputPX, vregInputPX, vregInputX, mask);
    Reg::Exp(vregInputPX, vregInputPX, mask);

    Reg::Duplicate(vregInputRes0, BETA);
    Reg::Axpy(vregInputRes0, vregInputXSqr, A3, mask);
    Reg::Mul(vregInputRes0, vregInputRes0, vregInputX, mask);

    Reg::Adds(vregInputT, vregInputPX, (float)1.0, mask);
    Reg::Div(vregInputDiv, vregInputOne, vregInputT, mask);

    Reg::Mul(vregInputResp, vregInputPX, vregInputDiv, mask);
    Reg::Mul(vregInputResp, vregInputResp, vregInputRes0, mask);
    Reg::Mul(vregInputResp, vregInputResp, vregInputDiv, mask);
    Reg::Compare<T, CMPMODE::EQ>(cmpMask, vregInputResp, vregInputResp, mask);
    Reg::Select<T>(vregSelect, vregInputResp, vregInputZero, cmpMask);
    Reg::Add(vregInputResp, vregSelect, vregInputDiv, mask);
    Reg::Mul(vregOutput, vregInputDy, vregInputResp, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**要点**: 1) 常与 Duplicate 配对：Duplicate 设初值，Axpy 累加 src*scalar 项。2) 一段循环内可多次 Axpy 对不同寄存器做独立多项式。3) mask 贯穿所有 vector 指令保证尾批正确。

### 实例 3：mish_grad::MishCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, CompareScalar, DataCopy, Div, Exp, LoadDist, MaskReg, Muls, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Axpy 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: Mish 反向中，用 Axpy 把 e^x 乘 2 累加到 e^2x 上得到 e^2x+2e^x 作为分母构造项，配合 Muls/Exp/Div 完成梯度公式。

（行 114-132）

```cpp

Reg::Muls(vregInputNeg, vregInput, FP32_NEG_ONE, mask);
Reg::Muls(vregInputNeg2, vregInput, FP32_NEG_TWO, mask);
Reg::Exp(vregInputNeg, vregInputNeg, mask);   // x = e^(-x)
Reg::Exp(vregInputNeg2, vregInputNeg2, mask); // x = e^(-2x)

Reg::Muls(vregInputNeg, vregInputNeg, FP32_TWO, mask);
Reg::Adds(vregInputNeg, vregInputNeg, FP32_ONE, mask); // x = 2e^(-x)+1
Reg::Muls(vregInputNeg2, vregInputNeg2, FP32_TWO, mask);
Reg::Add(vregInputNeg2, vregInputNeg2, vregInputNeg, mask);
Reg::Div(vregOutput, vregInputNeg, vregInputNeg2, mask);

Reg::Muls(vregInputMid, vregInput, FP32_TWO, mask);
Reg::Exp(vregInputMid, vregInputMid, mask);
Reg::Exp(vregInputExp, vregInput, mask);
Reg::Axpy(vregInputMid, vregInputExp, FP32_TWO, mask);
Reg::Adds(vregInputExp, vregInputMid, FP32_TWO, mask);
Reg::Div(vregInputMid, vregInputMid, vregInputExp, mask);
```

**要点**: 1) 同一融合乘加模式在 forward/grad 中复用。2) dst(vregInputMid) 既是输入也是输出。3) 配合 Adds 再加常数完成 softplus 分母。

### 实例 4：gelu_grad_v2::GeluGradV2TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Compare, DataCopy, Div, Duplicate, Exp, MaskReg, Mul, RegTensor, RegTraitNumOne, Select, UpdateMask
- **Axpy 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: GeluGradV2(tanh 版) 多项式求值，Duplicate 设常数初值后用 Axpy 累加 x²·系数项，与实例 2 同构但系数(AN/A3)不同。

（行 134-163）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    Reg::Duplicate(vregInputPX, BETAN);
    // OpCopyIn
    Reg::DataCopy(vregInputDy, (__ubuf__ T*)(src0Addr + loopIdx * vlSize));
    Reg::DataCopy(vregInputX, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));
    // compute
    Reg::Mul(vregInputXSqr, vregInputX, vregInputX, mask);
    Reg::Axpy(vregInputPX, vregInputXSqr, AN, mask);
    Reg::Mul(vregInputPX, vregInputPX, vregInputX, mask);
    Reg::Exp(vregInputPX, vregInputPX, mask);

    Reg::Duplicate(vregInputRes0, BETA);
    Reg::Axpy(vregInputRes0, vregInputXSqr, A3, mask);
    Reg::Mul(vregInputRes0, vregInputRes0, vregInputX, mask);

    Reg::Adds(vregInputT, vregInputPX, (float)1.0, mask);
    Reg::Div(vregInputDiv, vregInputOne, vregInputT, mask);

    Reg::Mul(vregInputResp, vregInputPX, vregInputDiv, mask);
    Reg::Mul(vregInputResp, vregInputResp, vregInputRes0, mask);
    Reg::Mul(vregInputResp, vregInputResp, vregInputDiv, mask);
    Reg::Compare<T, CMPMODE::EQ>(cmpMask, vregInputResp, vregInputResp, mask);
    Reg::Select<T>(vregSelect, vregInputResp, vregInputZero, cmpMask);
    Reg::Add(vregInputResp, vregSelect, vregInputDiv, mask);
    Reg::Mul(vregOutput, vregInputDy, vregInputResp, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**要点**: 1) 与 gelu_grad 共享 Duplicate+Axpy 多项式模板。2) Axpy 把 Mul(x²,系数) 与 Add(初值) 合为单条指令。3) mask 来自 UpdateMask<RegTraitNumOne>。

### 实例 5：gelu::GeluCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, DataCopy, Div, Exp, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, UpdateMask
- **Axpy 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: Gelu 的 tanh 近似中，用 Axpy 把 x 乘 TANH_APPROX_FACTOR 累加到 x³ 上，得到 x³ + factor·x 作为后续 exp/Div 的输入。

（行 52-66）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::Mul(vregInputSqr, vregInput, vregInput, mask);
    Reg::Mul(vregInputCub, vregInputSqr, vregInput, mask);
    Reg::Axpy(vregInputCub, vregInput, TANH_APPROX_FACTOR, mask);
    Reg::Muls(vregInputCub, vregInputCub, NEG_SQRT_EIGHT_OVER_PI, mask);
    Reg::Exp(vregInputCub, vregInputCub, mask);
    Reg::Adds(vregInputCub, vregInputCub, (float)1.0, mask);
    Reg::Div(vregOutput, vregInput, vregInputCub, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**要点**: 1) Axpy 合并 x³ 与 factor·x 的乘加为一条指令。2) 顺序：先 Mul×2 算 x²/x³，再 Axpy 加一次项。3) mask 控制尾批。

### 实例 6：gelu_quant::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, DataCopy, Div, Exp, LoadDist, Mul, Muls, RegTraitNumOne, UpdateMask
- **Axpy 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: 量化 Gelu 中，先把 half 输入 Cast 到 float，再用与实例 5 相同的 Axpy 模式构造 x³+factor·x 完成 tanh 近似。

（行 223-239）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vregInput16,
                                                               (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::Cast<float, T, castTrait0>(vregInput, vregInput16, mask);
    Reg::Mul(vregInputSqr, vregInput, vregInput, mask);
    Reg::Mul(vregInputCub, vregInputSqr, vregInput, mask);
    Reg::Axpy(vregInputCub, vregInput, TANH_APPROX_FACTOR, mask);
    Reg::Muls(vregInputCub, vregInputCub, NEG_SQRT_EIGHT_OVER_PI, mask);
    Reg::Exp(vregInputCub, vregInputCub, mask);
    Reg::Adds(vregInputCub, vregInputCub, 1.0f, mask);
    Reg::Div(vregOutput, vregInput, vregInputCub, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ float*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**要点**: 1) half 路径需 Cast<float,T> 提升后再 Axpy。2) UpdateMask 显式指定 float。3) Axpy 在 float 寄存器上运算。

### 实例 7：inplace_index_add::ComputeSumSingleRowVf

- **来源类型**: `__simd_vf__`
- **共现 API**: Add, CreateMask, DataCopy, MaskReg, Muls, RegTensor, UpdateMask
- **Axpy 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: maskReg, mask）
- **语义（待补充）**: inplace_index_add 按行累加中，对 half/bfloat16 路径用 Axpy 一步完成 sum += updates·alpha 的乘加；int8/bool 等不支持 Axpy 的类型退化为 Muls+Add 两步。

（行 253-270）

```cpp
if constexpr (IsSameType<VAR_T, half>::value || IsSameType<VAR_T, bfloat16_t>::value) {
    ops_vf::LoadOneTensorForDtypeT<VAR_T>(updatesAddr + i * vfLen, castReg, maskReg, 0);
    AscendC::Reg::DataCopy(sumReg, updateSumAddr + i * vfLen);
    AscendC::Reg::Axpy(sumReg, castReg, alpha, maskReg);
    AscendC::Reg::DataCopy(updateSumAddr + i * vfLen, sumReg, maskReg);
} else if constexpr (IsSameType<VAR_T, int8_t>::value || IsSameType<VAR_T, bool>::value) {
    LoadOneTensorForDtypeInt<VAR_T>(updatesAddr, castReg, maskReg, i * vfLen);
    LoadOneTensorForDtypeInt<VAR_T>(updateSumAddr, sumReg, maskReg, i * vfLen);
    AscendC::Reg::Muls(castReg, castReg, alpha, maskReg);
    AscendC::Reg::Add(sumReg, sumReg, castReg, maskReg);
    StoreOneTensorForDtypeInt<VAR_T>(updateSumAddr, sumReg, maskReg, i * vfLen);
} else {
    AscendC::Reg::DataCopy(sumReg, updateSumAddr + i * vfLen);
    AscendC::Reg::DataCopy(castReg, updatesAddr + i * vfLen);
    AscendC::Reg::Muls(castReg, castReg, alpha, maskReg);
    AscendC::Reg::Add(sumReg, sumReg, castReg, maskReg);
    AscendC::Reg::DataCopy(updateSumAddr + i * vfLen, sumReg, maskReg);
}
```

**要点**: 1) Axpy 的 mask 形参此处用 maskReg(由 CreateMask/UpdateMask 生成)。2) 类型分支：仅浮点/bfloat16 走 Axpy 快路径。3) Axpy 后用带 mask 的 DataCopy 存回。

### 实例 8：lin_space::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, DataCopy, Duplicate, MaskReg, RegTensor, RegTraitNumOne, UpdateMask
- **Axpy 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: lin_space 用 Duplicate 设首值 firstValue，Axpy 把 (input+offset)·step 累加到首值上，生成等差数列元素。

（行 132-146）

```cpp
{
    AscendC::Reg::RegTensor<C, AscendC::Reg::RegTraitNumOne> vregInput;
    AscendC::Reg::RegTensor<C, AscendC::Reg::RegTraitNumOne> vregAdd;
    AscendC::Reg::RegTensor<C, AscendC::Reg::RegTraitNumOne> vregFloat;
    AscendC::Reg::MaskReg mask;

    for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
        mask = AscendC::Reg::UpdateMask<C, AscendC::Reg::RegTraitNumOne>(count);
        AscendC::Reg::DataCopy(vregInput, (__ubuf__ C*)(srcAddr + loopIdx * vlSize));
        AscendC::Reg::Adds(vregAdd, vregInput, offset, mask);
        AscendC::Reg::Duplicate(vregFloat, firstValue, mask);
        AscendC::Reg::Axpy(vregFloat, vregAdd, stepValue, mask);
        ops::StoreOneTensorForDtypeT<S>(dstAddr, vregFloat, mask, loopIdx * vlSize);
    }
}
```

**要点**: 1) Axpy(dst=初值, src=索引+偏移, scalar=步长) 生成等差序列。2) Duplicate 与 Axpy 配对设初值。3) 带 AscendC::Reg:: 前缀的全限定调用。

### 实例 9：atan2::TaylorSeriesExpansion

- **来源类型**: `__aicore__`
- **共现 API**: Duplicate, Mul, MulDstAdd, RegTensor
- **Axpy 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: atan2 用泰勒展开近似 arctan，Axpy 作为 horner 内层起点 y = x²·(1/13) + (-1/11)，后续 MulDstAdd 逐层嵌套乘 x² 并加系数。

（行 261-275）

```cpp
{
    // x - 1/3*x^3 + 1/5*x^5 - 1/7*x^7 + 1/9*x^9 - 1/11*x^11 + 1/13*x^13
    // x(1 - x^2(1/3 - x^2(1/5 - x^2(1/7 - x^2(1/9 - x^2(1/11 - x^2/13))))))
    Reg::RegTensor<float> xSquarReg;
    Reg::Mul(xSquarReg, xReg, xReg, mask);

    Reg::Duplicate(yReg, -1.0f / 11.0f, mask);
    Reg::Axpy(yReg, xSquarReg, 1.0f / 13.0f, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg9, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg7, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg5, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg3, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg1, mask);
    Reg::Mul(yReg, yReg, xReg, mask);
}
```

**要点**: 1) Axpy 与 MulDstAdd 配合实现 horner 多项式。2) Duplicate 设 -1/11 初值，Axpy 加 1/13·x²。3) mask 控制有效元素。

### 实例 10：foreach_addcmul_scalar::Compute

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **Axpy 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: maskReg, mask）
- **语义（待补充）**: foreach_addcmul_scalar 用 Axpy 一步实现 addcmul：先 Mul 算 b·c，再 Axpy 把 b·c·scalar 累加到输入 a 上，得到 a + scalar·b·c。

（行 74-84）

```cpp
for (uint16_t i = 0; i < (uint16_t)repeatTimes; i++) {
    maskReg = UpdateMask<float>(sreg);
    ops::LoadOneTensorForDtypeT<T>(inUbAddr, inRegToFloat, maskReg, i * dataCountPerLoop);
    ops::LoadOneTensorForDtypeT<T>(tensorOneUbAddr, tensorOneRegToFloat, maskReg, i * dataCountPerLoop);
    ops::LoadOneTensorForDtypeT<T>(tensorTwoUbAddr, tensorTwoRegToFloat, maskReg, i * dataCountPerLoop);

    Mul(tensorOneRegToFloat, tensorOneRegToFloat, tensorTwoRegToFloat, maskReg);
    Axpy(inRegToFloat, tensorOneRegToFloat, scalarVal, maskReg);

    ops::StoreOneTensorForDtypeT<T>(outUbAddr, inRegToFloat, maskReg, i * dataCountPerLoop);
}
```

**要点**: 1) Axpy 第三参为标量 scalarVal，第四参 maskReg。2) 裸名 Axpy(无 Reg:: 前缀)在 foreach regbase 内使用。3) Mul+Axpy 两步即 addcmul。

### 实例 11：foreach_lerp_scalar::DoCompute

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **Axpy 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: maskReg, mask）
- **语义（待补充）**: foreach_lerp_scalar 用 Sub 算差值(b-a)或(a-b)，再用 Axpy 把差值乘权重 weight 累加到基准上，按 needExchange 分支选择基准寄存器实现 lerp。

（行 67-80）

```cpp
for (uint16_t i = 0; i < (uint16_t)repeatTimes; i++) {
    maskReg = UpdateMask<float>(sreg);
    ops::LoadOneTensorForDtypeT<T>(tensorOneUbAddr, tensorOneRegToFloat, maskReg, i * dataCountPerLoop);
    ops::LoadOneTensorForDtypeT<T>(tensorTwoUbAddr, tensorTwoRegToFloat, maskReg, i * dataCountPerLoop);
    if constexpr (needExchange) {
        Sub(tensorTwoRegToFloat, tensorTwoRegToFloat, tensorOneRegToFloat, maskReg);
        Axpy(tensorOneRegToFloat, tensorTwoRegToFloat, weightVal_, maskReg);
        ops::StoreOneTensorForDtypeT<T>(outUbAddr, tensorOneRegToFloat, maskReg, i * dataCountPerLoop);
    } else {
        Sub(tensorOneRegToFloat, tensorTwoRegToFloat, tensorOneRegToFloat, maskReg);
        Axpy(tensorTwoRegToFloat, tensorOneRegToFloat, weightVal, maskReg);
        ops::StoreOneTensorForDtypeT<T>(outUbAddr, tensorTwoRegToFloat, maskReg, i * dataCountPerLoop);
    }
}
```

**要点**: 1) Axpy(dst=基准, src=差值, scalar=权重) 实现 lerp。2) if constexpr 分支决定 dst/src 交换。3) 一次循环内 2 次 Axpy(分支互斥)。

### 实例 12：foreach_utils::ComputeFloatPath

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **Axpy 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: maskReg, mask）
- **语义（待补充）**: foreach_utils 通用 addc 路径，按 OP 模板参数选 Mul 或 Div 算中间量，再用 Axpy 把中间量乘 scalar 累加到输入，支持 addcmul/addcdiv 两类。

（行 56-74）

```cpp
{
    MaskReg maskReg;
    RegTensor<float> inRegToFloat;
    RegTensor<float> tensorOneRegToFloat;
    RegTensor<float> tensorTwoRegToFloat;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        maskReg = UpdateMask<float>(sreg);
        ops::LoadOneTensorForDtypeT<T>(inUbAddr, inRegToFloat, maskReg, i * dataCountPerLoop);
        ops::LoadOneTensorForDtypeT<T>(tensorOneUbAddr, tensorOneRegToFloat, maskReg, i * dataCountPerLoop);
        ops::LoadOneTensorForDtypeT<T>(tensorTwoUbAddr, tensorTwoRegToFloat, maskReg, i * dataCountPerLoop);
        if constexpr (OP == AddcOp::MUL) {
            Mul(tensorOneRegToFloat, tensorOneRegToFloat, tensorTwoRegToFloat, maskReg);
        } else {
            Div(tensorOneRegToFloat, tensorOneRegToFloat, tensorTwoRegToFloat, maskReg);
        }
        Axpy(inRegToFloat, tensorOneRegToFloat, scalarVal, maskReg);
        ops::StoreOneTensorForDtypeT<T>(outUbAddr, inRegToFloat, maskReg, i * dataCountPerLoop);
    }
}
```

**要点**: 1) Axpy 配合 if constexpr(MUL/Div) 复用同一累加结构。2) 裸名 API + ops:: 辅助加载。3) maskReg 来自 UpdateMask<float>。

### 实例 13：group_norm_grad::HardEvent::S_V

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: (无)
- **Axpy 调用次数**: 1
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: group_norm_grad 重算路径中，先用 Muls 把 x 乘 C2，再用 Axpy 把 dy 乘 dyMulScalar 累加到 x，完成 x = C2·x + scalar·dy，随后 Adds 常数 C3。

（行 458-466）

```cpp
for (uint16_t i = 0; i < (uint16_t)repeatTimes; ++i) {
    preg = UpdateMask<float>(sreg);
    LoadOneTensorForDtypeT<T>(ubX, vregX, preg, i * sregvl);
    LoadOneTensorForDtypeT<T>(ubDy, vregDy, preg, i * sregvl);
    Muls(vregX, vregX, C2, preg);
    Axpy(vregX, vregDy, dyMulScalar, preg);
    Adds(vregX, vregX, C3, preg);
    StoreOneTensorForDtypeT<T>(ubDst, vregX, preg, i * sregvl);
}
```

**要点**: 1) Axpy 第四参 preg 来自 UpdateMask<float>(sreg)，是元素掩码寄存器(变量名 preg 非 mask)。2) Axpy 紧跟 Muls 形成线性组合 C2·x+scalar·dy。3) 裸名 Axpy 调用。

### 实例 14：group_norm_grad::TPosition::VECOUT

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: (无)
- **Axpy 调用次数**: 1
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: group_norm_grad 基础路径中，用 Axpy 把 dbeta 乘 negMeanScalar 累加到 ds，得到 ds - mean·dbeta，再 Muls rstdScalar 算 dgamma。

（行 588-595）

```cpp
for (uint16_t i = 0; i < (uint16_t)repeatTimes; ++i) {
    preg = UpdateMask<float>(sreg);
    DataCopy(vregDs, ubDs + i * sregvl);
    DataCopy(vregDbeta, ubDbeta + i * sregvl);
    Axpy(vregDs, vregDbeta, negMeanScalar, preg);
    Muls(vregDs, vregDs, rstdScalar, preg);
    StoreOneTensorForDtypeT<OUT>(ubDgamma, vregDs, preg, i * sregvl);
}
```

**要点**: 1) Axpy 实现减法等价：dst + src·(负标量) = dst - mean·src。2) preg 为掩码寄存器。3) 与 DataCopy/Muls 组合完成 dgamma 归约。

### 实例 15：power::MulAddDstScalar

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **Axpy 调用次数**: 1
- **参数模式**: `T0_A4_M0_TYPEint32_t`（实参 4 个，类型: int32_t）
- **语义（待补充）**: power 算子用高层 AscendC::Axpy 实现 fused MulAdd：先 Duplicate 把 shift 广播到 dst，再 Axpy 一步完成 dst = src·scaleScalar + shift，第 4 参为元素数 count(int32_t) 而非掩码。

（行 88-99）

```cpp
struct MulAddDstScalar : public Vec::ElemwiseTernaryOP<T, T, T, T> {
    __aicore__ inline MulAddDstScalar(
        LocalTensor<T>& dst, LocalTensor<T>& src, T scaleScalar, T shiftScalar, uint32_t count)
    {
#ifdef __CCE_AICORE__
        // 第 1 步：dst = shift  （广播 shift 标量到所有 lanes，作为 Axpy 的累加初值）
        AscendC::Duplicate(dst, shiftScalar, static_cast<int32_t>(count));
        // 第 2 步：dst = src * scaleScalar + dst  （fused MulAdd，单条向量指令）
        AscendC::Axpy(dst, src, scaleScalar, static_cast<int32_t>(count));
#endif
    }
};
```

**要点**: 1) 高层 Axpy 第 4 参是 int32_t 元素数，与 Reg::Axpy 的 MaskReg 掩码重载不同。2) Duplicate+Axpy 组合等价 dst = a·src+b。3) 用于幂运算的标量 fused MulAdd 路径。

### Axpy 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| mish | Add, Adds, Cast, CompareScalar | Axpy(dst,src,2,mask) 累加构造 e^2x+2e^x 分子 | __aicore__ |
| gelu_grad | Add, Adds, Compare, DataCopy | Duplicate 设常数 + Axpy 累加 x²·系数 做多项式求值 | __aicore__ |
| mish_grad | Add, Adds, CompareScalar, DataCopy | Axpy(dst,src,2,mask) 累加构造 e^2x+2e^x 梯度分母 | __aicore__ |
| gelu_grad_v2 | Add, Adds, Compare, DataCopy | Duplicate+Axpy 多项式求值(系数 AN/A3) | __aicore__ |
| gelu | Adds, DataCopy, Div, Exp | Mul 算 x³ + Axpy 累加 factor·x 构造 tanh 近似输入 | __aicore__ |
| gelu_quant | Adds, Cast, DataCopy, Div | Cast half→float + Axpy 累加 factor·x 量化 gelu | __VEC_SCOPE__ |
| inplace_index_add | Add, CreateMask, DataCopy, MaskReg | 按 dtype 分支：half/bf16 走 Axpy 一步乘加，其余 Muls+Add | __simd_vf__ |
| lin_space | Adds, DataCopy, Duplicate, MaskReg | Duplicate 设首值 + Axpy(dst,idx+off,step,mask) 生成等差数列 | __VEC_SCOPE__ |
| atan2 | Duplicate, Mul, MulDstAdd, RegTensor | Duplicate+Axpy+MulDstAdd 链做 horner 泰勒展开 | __aicore__ |
| foreach_addcmul_scalar |  | Mul(b,c)+Axpy(a,bc,scalar,maskReg) 实现 addcmul | __aicore__ |
| foreach_lerp_scalar |  | Sub 算差值 + Axpy(基准,差值,weight,maskReg) 实现 lerp | __aicore__ |
| foreach_utils |  | if constexpr 选 Mul/Div + Axpy 通用 addc 累加 | __aicore__ |
| group_norm_grad |  | Muls+Axpy(x,dy,scalar,preg) 线性组合，掩码变量 preg | __VEC_SCOPE__ |
| group_norm_grad |  | Axpy(ds,dbeta,negMean,preg) 等价减法 + Muls 算 dgamma | __VEC_SCOPE__ |
| power |  | 高层 AscendC::Axpy(dst,src,scale,count) 第4参为元素数，Duplicate 设 shift 做 fused MulAdd | __aicore__ |

