# Exp

**页面ID:** atlasascendc_api_07_0344  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0344.html

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

根据mask对输入数据srcReg进行指数操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0344_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, auto mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Exp(U& dstReg, U& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 |
| mode | 可配置为MaskMergeMode的枚举或ExpSpecificMode的结构体指针。- MaskMergeMode，选择MERGING模式或ZEROING模式。  - ZEROING，mask未筛选的元素在dstReg中置零。  - MERGING，暂不支持。 - ExpSpecificMode，定义如下：``` enum class ExpAlgo {     INTRINSIC = 0,     PRECISION_1ULP_FTZ_TRUE,     PRECISION_1ULP_FTZ_FALSE, }; struct ExpSpecificMode{     MaskMergeMode mrgMode = MaskMergeMode::ZEROING,     ExpAlgo algo = ExpAlgo::INTRINSIC; }; ```   - mrgMode：选择MERGING模式或ZEROING模式。  - algo：用于配置Subnormal模式。    - ExpAlgo::INTRINSIC、ExpAlgo::PRECISION_1ULP_FTZ_TRUE，使用单指令计算得出结果，所有Subnormal被近似为0。    - ExpAlgo::PRECISION_1ULP_FTZ_FALSE，支持Subnormal数据计算。 |
| U | 源操作数和目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void ExpVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    // Subnormal模式
    // static constexpr AscendC::Reg::ExpSpecificMode mode = {Reg::MaskMergeMode::ZEROING, ExpAlgo::PRECISION_1ULP_FTZ_FALSE};
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Exp(dstReg, srcReg, mask);
        // Subnormal模式
        // AscendC::Reg::Exp<T, &mode>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Exp 实例

### 实例 1：tanh::TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, And, Cast, CompareScalar, DataCopy, Div, Duplicate, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, Or, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Exp 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 在 tanh 多项式逼近核中对 2|x| 调用 Exp 计算 e^{2|x|}，用于构造 tanh 有理逼近 (e^x-e^-x)/(e^x+e^-x) 并在大输入区间做饱和 Select。

**片段 1** (行 78-109):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

    Reg::Mul(vregInputSqr, vregInput, vregInput, mask);
    Reg::Muls(vregOutput, vregInputSqr, FP32_ZERO_015, mask);
    Reg::Adds(vregOutput, vregOutput, FP32_ZERO_NEG_052, mask);
    Reg::FusedMulDstAdd(vregOutput, vregInputSqr, vregValue1, mask);
    Reg::FusedMulDstAdd(vregOutput, vregInputSqr, vregValue2, mask);
    Reg::Mul(vregOutput, vregOutput, vregInputSqr, mask);
    Reg::FusedMulDstAdd(vregOutput, vregInput, vregInput, mask);

    Reg::Abs(vregInputAbs, vregInput, mask);
    Reg::Muls(vregInputMid, vregInputAbs, FP32_TWO, mask);
    Reg::Exp(vregInputMid, vregInputMid, mask);
    Reg::Adds(vregInputMid, vregInputMid, FP32_ONE, mask);
    Reg::Div(vregInputMid, vregOne, vregInputMid, mask);
    Reg::Muls(vregInputMid, vregInputMid, FP32_ZERO_NEG_TWO, mask);
    Reg::Adds(vregInputMid, vregInputMid, FP32_ONE, mask);
    Reg::CompareScalar<float, CMPMODE::GE>(satMaskReg, vregInputAbs, FP32_SAT_BOUND, mask);
    Reg::Select(vregInputMid, vregOne, vregInputMid, satMaskReg);

    Reg::And(vregSign, vregSignMask, (Reg::RegTensor<uint32_t, Reg::RegTraitNumOne>&)vregInput, mask);
    Reg::Or((Reg::RegTensor<uint32_t, Reg::RegTraitNumOne>&)vregInputMid,
        (Reg::RegTensor<uint32_t, Reg::RegTraitNumOne>&)vregInputMid, vregSign, mask);

    Reg::CompareScalar<float, CMPMODE::GE>(cmpMaskReg, vregInputAbs, FP32_ZERO_6, mask);
    Reg::Select(vregOutput, vregInputMid, vregOutput, cmpMaskReg);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_NORM_B32>((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**片段 2** (行 120-138):

```cpp
mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
// OpCopyIn
Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vregInput16, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
Reg::Cast<float, T, castTrait0>(vregInput, vregInput16, mask);

Reg::Mul(vregInputSqr, vregInput, vregInput, mask);
Reg::Muls(vregOutput, vregInputSqr, FP32_ZERO_015, mask);
Reg::Adds(vregOutput, vregOutput, FP32_ZERO_NEG_052, mask);
Reg::FusedMulDstAdd(vregOutput, vregInputSqr, vregValue1, mask);
Reg::FusedMulDstAdd(vregOutput, vregInputSqr, vregValue2, mask);
Reg::Mul(vregOutput, vregOutput, vregInputSqr, mask);
Reg::FusedMulDstAdd(vregOutput, vregInput, vregInput, mask);

Reg::Abs(vregInputAbs, vregInput, mask);
Reg::Muls(vregInputMid, vregInputAbs, FP32_TWO, mask);
Reg::Exp(vregInputMid, vregInputMid, mask);
Reg::Adds(vregInputMid, vregInputMid, FP32_ONE, mask);
Reg::Div(vregInputMid, vregOne, vregInputMid, mask);
Reg::Muls(vregInputMid, vregInputMid, FP32_ZERO_NEG_TWO, mask);
```

**要点**:
- 调用形式 Exp(dst, src, mask)，3 实参含 mask，模板参数 T/mode 由编译器推导（T0）
- 先 Muls(vregInputAbs, FP32_TWO) 再 Exp，等效计算 e^{2|x|}
- 大输入用 CompareScalar+Select 做饱和保护，避免 Exp 溢出

### 实例 2：cdist::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, CreateMask, Duplicate, ExpSpecificMode, LoadAlign, Log, LogSpecificMode, MaskMergeMode, MaskPattern, MaskReg, Muls, ReduceSum, RegTensor, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore, UpdateMask
- **Exp 调用次数**: 3
- **参数模式**: `T2_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 在 cdist 距离核的 softmax 归一化分支中，通过显式模板 Exp<float, &modeexp> 对 -dist² 求 exp，再用 ReduceSum 求和构造归一化分母。

（行 617-648）

```cpp
for (uint16_t m = 0; m < loopNumM; m++) {
    __local_mem__ float * x1Offset = srcPtrX1 + b * pSize_ * MAlign_ + p * MAlign_ + vlLen_ * m;
    __local_mem__ float * x2Offset = srcPtrX2 + b * rSize_ * MAlign_ + r * MAlign_ + vlLen_ * m;
    Reg::LoadAlign(x1Reg, x1Offset);
    Reg::LoadAlign(x2Reg, x2Offset);
    Reg::Sub(subReg, x1Reg, x2Reg, maskAll);
    Reg::Abs(absReg, subReg, maskAll);
    Reg::Log<float, &modelog>(logReg, absReg, maskAll);
    Reg::Muls(mulReg, logReg, (float)p_, maskAll);
    Reg::Exp<float, &modeexp>(expReg, mulReg, maskAll);
    Reg::ReduceSum(sumReg, expReg, maskAll);
    Reg::Add(dstReg, dstReg, sumReg, maskOne);
}
__local_mem__ float * x1Offset = srcPtrX1 + b * pSize_ * MAlign_ + p * MAlign_ + vlLen_ * loopNumM;
__local_mem__ float * x2Offset = srcPtrX2 + b * rSize_ * MAlign_ + r * MAlign_ + vlLen_ * loopNumM;
Reg::LoadAlign(x1Reg, x1Offset);
Reg::LoadAlign(x2Reg, x2Offset);
Reg::Sub(subReg, x1Reg, x2Reg, maskTail);
Reg::Abs(absReg, subReg, maskTail);
Reg::Log<float, &modelog>(logReg, absReg, maskTail);
Reg::Muls(mulReg, logReg, (float)p_, maskTail);
Reg::Exp<float, &modeexp>(expReg, mulReg, maskTail);
Reg::ReduceSum(sumReg, expReg, maskTail);
Reg::Add(dstReg, dstReg, sumReg, maskOne);
if (ubLoopNumM_ == 1) {
    Reg::Log<float, &modelog>(logReg, dstReg, maskOne);
    Reg::Muls(mulReg, logReg, (float)(1 / p_), maskOne);
    Reg::Exp<float, &modeexp>(expReg, mulReg, maskOne);
    Reg::StoreUnAlign(yOffset, expReg, uReg, BASE_ONE);
} else {
    Reg::StoreUnAlign(yOffset, dstReg, uReg, BASE_ONE);
}
```

**要点**:
- 唯一使用 ExpSpecificMode（&modeexp 结构体指针）配置 Subnormal 行为的实例，模板显式指定 float
- 三处调用分别用 maskAll/maskTail/maskOne 处理满块、尾块、单元素
- 与 ReduceSum 组合实现 exp+求和的 softmax 归一化

### 实例 3：swiglu_mx_quant::VecScope_L446

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Div, LoadDist, MaskPattern, MaskReg, Maxs, Mins, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **Exp 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 在 SwiGLU 的 sigmoid 分支中对线性变换结果调用 Exp 计算 e^x，配合 Adds+Div 构造 sigmoid 再做门控乘法。

**片段 1** (行 466-493):

```cpp
for (uint16_t dim1vfLoopIdx = 0; dim1vfLoopIdx < dim1VfTimes; dim1vfLoopIdx++) {
    AscendC::Reg::AddrReg srcIdxOffset = AscendC::Reg::CreateAddrReg<T>(
        dim0vfLoopIdx, alignDim1In, dim1vfLoopIdx, 128);
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddr,
                                                                                 srcIdxOffset);
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddr,
                                                                                 srcIdxOffset);
    AscendC::Reg::Cast<float, T, CAST_ZERO>(vregX1F, vregX1, mask);
    AscendC::Reg::Cast<float, T, CAST_ZERO>(vregX2F, vregX2, mask);

    AscendC::Reg::DeInterleave(vregX1DeF, vregX2DeF, vregX1F, vregX2F);
    AscendC::Reg::Mins(minsReg, vregX1DeF, clampLimit, mask);
    AscendC::Reg::Muls(mulsReg, minsReg, negAplha, mask);
    AscendC::Reg::Exp(expReg, mulsReg, mask);
    AscendC::Reg::Adds(addsReg, expReg, scalarOne, mask);
    AscendC::Reg::Div(sigmoidReg, minsReg, addsReg, mask);
    AscendC::Reg::Mins(vregX2DeF, vregX2DeF, clampLimit, mask);
    AscendC::Reg::Maxs(vregX2DeF, vregX2DeF, negClampLimit, mask);
    AscendC::Reg::Adds(vregX2DeF, vregX2DeF, gluBias, mask);

    AscendC::Reg::Mul(outFReg, sigmoidReg, vregX2DeF, mask);

    AscendC::Reg::Cast<T, float, CAST_FP32_TO_FP16_BF16>(outTReg, outFReg, mask);
    AscendC::Reg::AddrReg outOffset = AscendC::Reg::CreateAddrReg<T>(dim0vfLoopIdx, alignDim1Out,
                                                                               dim1vfLoopIdx, 64);
    DataCopy<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(swigluUbAddr, outTReg, outOffset, mask);
}
```

**片段 2** (行 496-518):

```cpp
for (uint16_t aa = 0; aa < dim1TailTimes; aa++) {
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddr1,
                                                                                 srcIdxOffset1);
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddr1,
                                                                                 srcIdxOffset1);
    AscendC::Reg::Cast<float, T, CAST_ZERO>(vregX1F, vregX1, mask);
    AscendC::Reg::Cast<float, T, CAST_ZERO>(vregX2F, vregX2, mask);

    AscendC::Reg::DeInterleave(vregX1DeF, vregX2DeF, vregX1F, vregX2F);
    AscendC::Reg::Mins(minsReg, vregX1DeF, clampLimit, mask1);
    AscendC::Reg::Muls(mulsReg, minsReg, negAplha, mask1);
    AscendC::Reg::Exp(expReg, mulsReg, mask1);
    AscendC::Reg::Adds(addsReg, expReg, scalarOne, mask1);
    AscendC::Reg::Div(sigmoidReg, minsReg, addsReg, mask1);
    AscendC::Reg::Mins(vregX2DeF, vregX2DeF, clampLimit, mask1);
    AscendC::Reg::Maxs(vregX2DeF, vregX2DeF, negClampLimit, mask1);
    AscendC::Reg::Adds(vregX2DeF, vregX2DeF, gluBias, mask1);

    AscendC::Reg::Mul(outFReg, sigmoidReg, vregX2DeF, mask1);
    AscendC::Reg::Cast<T, float, CAST_FP32_TO_FP16_BF16>(outTReg, outFReg, mask1);
    DataCopy<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(swigluUbAddr1, outTReg, outOffset1, mask2);
}
```

**要点**:
- 调用 AscendC::Reg::Exp(expReg, mulsReg, mask)，3 实参含 mask
- 两处调用分别用 mask 与 mask1 处理双轴切分的不同数据块
- sigmoid 由 Exp+Adds(1)+Div 组合实现

### 实例 4：sinh::SinhCustomVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, CompareScalar, DataCopy, Div, DivSpecificMode, Duplicate, MaskMergeMode, MaskReg, Mul, Neg, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **Exp 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 在 sinh 核中调用 Exp 计算 e^x，配合对 -x 的处理与 Sub/Add 实现 sinh=(e^x-e^-x)/2 公式。

（行 102-120）

```cpp
AscendC::Reg::Adds(reg_poly, reg_poly, c3, mask);        // + c3
AscendC::Reg::Mul(reg_poly, reg_poly, reg_x2, mask);     // * x2
AscendC::Reg::Adds(reg_poly, reg_poly, c2, mask);        // + c2

// x3 = x2 * x (reuse reg_temp)
AscendC::Reg::Mul(reg_temp, reg_x2, reg_x, mask);
// taylor = x + x3 * poly
AscendC::Reg::Mul(reg_poly, reg_poly, reg_temp, mask);   // x3 * P(x2)
AscendC::Reg::Add(reg_poly, reg_x, reg_poly, mask);      // x + x3*P(x2)
// reg_poly now holds Taylor result

// === Exp branch: offset-exp to avoid overflow ===
// shifted = |x| - ln2
AscendC::Reg::Adds(reg_temp, reg_abs, neg_ln2, mask);
// t = e^(|x| - ln2) = e^|x| / 2
AscendC::Reg::Exp(reg_exp, reg_temp, mask);
// inv_t = 0.25 / t = e^(-|x|) / 2
AscendC::Reg::Duplicate(reg_temp, quarter_val);
AscendC::Reg::Div<T, &divMode>(reg_temp, reg_temp, reg_exp, mask);
```

**要点**:
- 调用 Exp(reg_exp, reg_temp, mask)，3 实参含 mask
- sinh 公式需 e^x 与 e^-x，本例用单次 Exp 配合符号处理简化
- 与 Abs/Add 组合处理输入符号位

### 实例 5：swish_grad::SwishGradCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, DataCopy, Div, Duplicate, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, Neg, RegTensor, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **Exp 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 在 swish (x·sigmoid(x)) 梯度核中对中间值调用 Exp 计算 e^{...}，用于构造 sigmoid 导数项。

**片段 1** (行 63-82):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::DataCopy(vregInput2, (__ubuf__ T*)(src2Addr + loopIdx * vlSize));
    Reg::Muls(vregInput, vregInput, scale1, mask);
    Reg::Neg(vregInputMid, vregInput, mask);
    Reg::Exp(vregInputMid, vregInputMid, mask);
    Reg::Adds(vregInputMid, vregInputMid, (float)1.0, mask);
    Reg::Div(vregInputMid, vregValue1, vregInputMid, mask);
    Reg::Sub(vregOutput, vregValue1, vregInputMid, mask);
    Reg::Mul(vregOutput, vregOutput, vregInput, mask);
    Reg::FusedMulDstAdd(vregOutput, vregInputMid, vregInputMid, mask);
    Reg::Mul(vregOutput, vregOutput, vregInput2, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), (Reg::RegTensor<T>&)vregOutput,
                       mask);
}
```

**片段 2** (行 91-116):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(
        vregInput16, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(
        vregInput162, (__ubuf__ T*)(src2Addr + loopIdx * vlSize));
    Reg::Cast<float, T, castTrait0>(vregInput, vregInput16, mask);
    Reg::Cast<float, T, castTrait0>(vregInput2, vregInput162, mask);

    Reg::Muls(vregInput, vregInput, scale1, mask);
    Reg::Neg(vregInputMid, vregInput, mask);
    Reg::Exp(vregInputMid, vregInputMid, mask);
    Reg::Adds(vregInputMid, vregInputMid, (float)1.0, mask);
    Reg::Div(vregInputMid, vregValue1, vregInputMid, mask);
    Reg::Sub(vregOutput, vregValue1, vregInputMid, mask);
    Reg::Mul(vregOutput, vregOutput, vregInput, mask);
    Reg::FusedMulDstAdd(vregOutput, vregInputMid, vregInputMid, mask);
    Reg::Mul(vregOutput, vregOutput, vregInput2, mask);

    Reg::Cast<T, float, castTrait1>(vregOutput16, vregOutput, mask);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_PACK_B32>((__ubuf__ T*)(dstAddr + loopIdx * vlSize),
                                                              vregOutput16, mask);
}
```

**要点**:
- 调用 Exp(vregInputMid, vregInputMid, mask)，原地更新（dst==src）
- 两处 Exp 对应不同片段的 sigmoid 导数计算
- swish 梯度=sigmoid+x·sigmoid·(1-sigmoid)，依赖 Exp 构造 sigmoid

### 实例 6：mish::MishCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Axpy, Cast, CompareScalar, DataCopy, Div, LoadDist, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Exp 调用次数**: 8
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 在 mish 核中四次调用 Exp 分别计算 e^x、e^{2x}、e^{-x}、e^{-2x}，组合 softplus 与 tanh 实现 mish=x·tanh(softplus(x))。

（行 73-96）

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

**要点**:
- 四次 Exp 覆盖正负、单双倍指数，是 Exp 用量最大的实例
- softplus=ln(1+e^x) 由 Exp+Adds+Log 组合实现
- tanh 部分由 e^{2x}/e^{-2x} 比值构造

### 实例 7：cross_entropy_loss_grad::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, AddrReg, Cast, CreateAddrReg, CreateMask, DataCopy, LoadDist, MaskPattern, MaskReg, Mul, Muls, RegTensor, StoreDist, Sub, UpdateMask
- **Exp 调用次数**: 4
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在交叉熵损失梯度核中对 log 概率调用 Exp 还原概率，用于 softmax 梯度的 exp(log_prob) 计算。

**片段 1** (行 188-205):

```cpp
if constexpr (!IsSameType<T1, float>::value) {
    Reg::DataCopy<T1, Reg::LoadDist::DIST_UNPACK_B16>(regLogProb, logProbAddr, srcOffset);
    Reg::Cast<float, T1, castTrait0>(regLogProbB32, regLogProb, regAllFp32);
} else {
    Reg::DataCopy(regLogProbB32, logProbAddr, srcOffset);
}
Reg::DataCopy(regXGrad, xGradTmpAddr, outOffset);
Reg::Exp(regLogProbB32, regLogProbB32, regAllFp32);
if constexpr (isWeight == 1) {
    Reg::Mul(regSmoothB32, regLogProbB32, regSmoothGradSum, regAllFp32);
    Reg::DataCopy(regWeight, weightAddr, srcOffset1);
    Reg::Mul(regWeight, regSmoothGrad, regWeight, regAllFp32);
    Reg::Sub(regSmoothB32, regSmoothB32, regWeight, regAllFp32);
} else {
    Reg::Muls(regSmoothGradSum, regSmoothGrad, smoothGradreduceSum, regAllFp32);
    Reg::Mul(regSmoothB32, regLogProbB32, regSmoothGradSum, regAllFp32);
    Reg::Sub(regSmoothB32, regSmoothB32, regSmoothGrad, regAllFp32);
}
```

**片段 2** (行 216-234):

```cpp
if constexpr (!IsSameType<T1, float>::value) {
    Reg::DataCopy<T1, Reg::LoadDist::DIST_UNPACK_B16>(
        regLogProb, logProbAddr + ni * totalCLenAlign + vfLen * repeatTimes);
    Reg::Cast<float, T1, castTrait0>(regLogProbB32, regLogProb, pregUp);
} else {
    Reg::DataCopy(regLogProbB32, logProbAddr + ni * totalCLenAlign + vfLen * repeatTimes);
}
Reg::DataCopy(regXGrad, xGradTmpAddr + ni * totalCLenAlign + vfLen * repeatTimes);
Reg::Exp(regLogProbB32, regLogProbB32, pregUp);
if constexpr (isWeight == 1) {
    Reg::Mul(regSmoothB32, regLogProbB32, regSmoothGradSum, regAllFp32);
    Reg::DataCopy(regWeight, weightAddr + vfLen * repeatTimes);
    Reg::Mul(regWeight, regSmoothGrad, regWeight, pregUp);
    Reg::Sub(regSmoothB32, regSmoothB32, regWeight, pregUp);
} else {
    Reg::Muls(regSmoothGradSum, regSmoothGrad, smoothGradreduceSum, pregUp);
    Reg::Mul(regSmoothB32, regLogProbB32, regSmoothGradSum, pregUp);
    Reg::Sub(regSmoothB32, regSmoothB32, regSmoothGrad, pregUp);
}
```

**要点**:
- 调用 Exp(regLogProbB32, regLogProbB32, pregUp)，无 mask 参数（M0 模式，3 实参 dst/src/pred）
- 两处分别用 regAllFp32 与 pregUp 两种全量 predicate
- 由 log 域 exp 回概率域，配合梯度公式

### 实例 8：gelu_grad::GeluGradCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Axpy, Compare, DataCopy, Div, DivSpecificMode, Duplicate, MaskMergeMode, MaskReg, Mul, RegTensor, RegTraitNumOne, Select, UpdateMask
- **Exp 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 在 GELU 梯度核中对输入调用 Exp 计算 e^{...}，用于 erf/高斯近似形式的梯度项。

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

**要点**:
- 调用 Exp(vregInputPX, vregInputPX, mask)，原地更新
- GELU 梯度含 x·φ'(x) 项，φ 近似用到高斯 exp
- 与 Add/Axpy/Compare 组合完成梯度累加

### 实例 9：softplus_v2_grad::SoftplusV2GradVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, Adds, Compare, CreateAddrReg, Div, LoadAlign, MaskReg, Mul, Muls, Neg, RegTensor, Select, StoreAlign, Sub, UpdateMask
- **Exp 调用次数**: 2
- **参数模式**: `T1_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义（待补充）**: 在 softplus_v2 梯度核中按 S3: Exp(T2)→T3 步骤对中间 tensor 调用 Exp，实现 sigmoid=exp/(1+exp) 梯度。

（行 87-125）

```cpp
for (uint16_t i = 0; i < rep; i++) {
    aReg = AscendC::Reg::CreateAddrReg<T>(i, VL);
    padMask = AscendC::Reg::UpdateMask<T>(count);

    // --- Load: UB → Reg ---
    AscendC::Reg::LoadAlign(src0Reg, src0, aReg); // 读 input_features
    AscendC::Reg::LoadAlign(src1Reg, src1, aReg); // 读 input_gradients

    // S1: Mul(beta, input_features) → T1
    //     T1 = beta * input_features
    AscendC::Reg::Muls<T>(regT1, src0Reg, beta, padMask);

    // S2: Neg(T1) → T2
    AscendC::Reg::Neg<T>(regT2, regT1, padMask);

    // S3: Exp(T2) → T3
    AscendC::Reg::Exp<T>(regT3, regT2, padMask);

    // S4: Adds(T3, 1.0f) → T4
    AscendC::Reg::Adds<T>(regT4, regT3, static_cast<T>(1.0f), padMask);

    // S5: Div(input_gradients, T4) → T5
    AscendC::Reg::Div<T>(regT5, src1Reg, regT4, padMask);

    // S6: Sub(T1, T1) → regZero（零寄存器）
    AscendC::Reg::Sub<T>(regT2, regT1, regT1, padMask);

    // S7: Adds(regZero, threshold) → regThresh（阈值寄存器）
    AscendC::Reg::Adds<T>(regThresh, regT2, threshold, padMask);

    // S8: Compare(T1, regThresh, GT) → cmpMask
    AscendC::Reg::Compare<T, AscendC::CMPMODE::GT>(cmpMask, regT1, regThresh, padMask);

    // S9: Select(cmpMask, input_gradients, T5) → dstReg
    AscendC::Reg::Select<T>(dstReg, src1Reg, regT5, cmpMask);

    // --- Store: Reg → UB ---
    AscendC::Reg::StoreAlign(dst, dstReg, aReg, padMask);
}
```

**要点**:
- 模板参数 T1（1 个模板参数），mask 形参为 Mask（大写 MaskReg 类型）
- softplus 梯度即 sigmoid，由 Exp+Adds+Div 组合
- 注释 S3: Exp(T2)→T3 标明 Exp 在流水线中的阶段

### 实例 10：glu_grad::ComputeGluGradCore

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Cast, CastTrait, DataCopy, Div, DivSpecificMode, MaskMergeMode, Mul, Muls, RegLayout, RegTensor, SatMode, Sub
- **Exp 调用次数**: 3
- **参数模式**: `T2_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义（待补充）**: 在 GLU 梯度核中通过显式模板 Exp<float, MaskMergeMode::ZEROING> 对中间值求 exp，构造 sigmoid 导数用于门控梯度。

**片段 1** (行 80-96):

```cpp
constexpr static AscendC::Reg::CastTrait castFromFloatOdd = {
    AscendC::Reg::RegLayout::ONE, AscendC::Reg::SatMode::NO_SAT,
    AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::CAST_RINT};

AscendC::Reg::RegTensor<T> vregOutAT;
AscendC::Reg::RegTensor<T> vregOutBT;

AscendC::Reg::Cast<float, T, castToFloatEven>(vregAF, vregA, maskAll8);
AscendC::Reg::Cast<float, T, castToFloatEven>(vregBF, vregB, maskAll8);
AscendC::Reg::Cast<float, T, castToFloatEven>(vregGradF, vregGrad, maskAll8);

AscendC::Reg::Muls<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vregTemp, vregBF, static_cast<float>(-1), preg0);
AscendC::Reg::Exp<float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vregSub, vregTemp, preg0);
AscendC::Reg::Adds<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vregTemp, vregSub, static_cast<float>(1), preg0);
```

**片段 2** (行 107-124):

```cpp
AscendC::Reg::Mul<float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vregTemp, vregTemp, vregAF, preg0);
AscendC::Reg::Mul<float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vregGradB, vregTemp, vregGradF, preg0);

AscendC::Reg::Cast<T, float, castFromFloatEven>(vregOutputA, vregGradA, maskAll8);
AscendC::Reg::Cast<T, float, castFromFloatEven>(vregOutputB, vregGradB, maskAll8);

AscendC::Reg::Cast<float, T, castToFloatOdd>(vregAF, vregA, maskAll8);
AscendC::Reg::Cast<float, T, castToFloatOdd>(vregBF, vregB, maskAll8);
AscendC::Reg::Cast<float, T, castToFloatOdd>(vregGradF, vregGrad, maskAll8);

AscendC::Reg::Muls<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vregTemp, vregBF, static_cast<float>(-1), preg0);
AscendC::Reg::Exp<float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vregSub, vregTemp, preg0);
AscendC::Reg::Adds<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vregTemp, vregSub, static_cast<float>(1), preg0);
```

**片段 3** (行 139-156):

```cpp

    AscendC::Reg::Cast<T, float, castFromFloatOdd>(vregOutAT, vregGradA, maskAll8);
    AscendC::Reg::Cast<T, float, castFromFloatOdd>(vregOutBT, vregGradB, maskAll8);

    AscendC::Reg::Add<T, AscendC::Reg::MaskMergeMode::ZEROING>(
        vregOutputA, vregOutputA, vregOutAT, preg0);
    AscendC::Reg::Add<T, AscendC::Reg::MaskMergeMode::ZEROING>(
        vregOutputB, vregOutputB, vregOutBT, preg0);

    AscendC::Reg::DataCopy(outALocalPtr + loopIdx * vlSize, vregOutputA, preg0);
    AscendC::Reg::DataCopy(outBLocalPtr + loopIdx * vlSize, vregOutputB, preg0);
} else {
    AscendC::Reg::Muls<T, T, AscendC::Reg::MaskMergeMode::ZEROING>(
        vregTemp, vregB, static_cast<T>(-1), preg0);
    AscendC::Reg::Exp<T, AscendC::Reg::MaskMergeMode::ZEROING>(
        vregSub, vregTemp, preg0);
    AscendC::Reg::Adds<T, T, AscendC::Reg::MaskMergeMode::ZEROING>(
        vregTemp, vregSub, static_cast<T>(1), preg0);
```

**要点**:
- 无 mask 实参（M0 模式），但模板显式指定 float 类型与 ZEROING 模式
- 三处 Exp 跨片段多行书写，处理不同 half/float 数据路径
- 模板显式 Exp<float,...> 是本例与裸 Exp(...) 的关键区别

### 实例 11：elu::EluCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, Cast, CompareScalar, DataCopy, LoadDist, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Exp 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 在 ELU 激活核中对负值分支调用 Exp 计算 e^x，实现 elu(x)=α(e^x-1)（x<0）的指数项。

**片段 1** (行 75-94):

```cpp
Reg::Muls(vregNeg, vregInput, inputScale, mask);

// Polynomial expm1(z) = z + z^2/2 + z^3/6 + z^4/24 + z^5/120 for |z| < threshold
// Horner: T1 = T1 * z + coeff, then poly = T1 * z
Reg::Muls(vregT1, vregNeg, coeff5, mask);
Reg::Adds(vregT1, vregT1, coeff4, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff3, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff2, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff1, mask);
Reg::Mul(vregPoly, vregT1, vregNeg, mask);

// exp(z) - 1 for |z| >= threshold
Reg::Exp(vregExp, vregNeg, mask);
Reg::Adds(vregExp, vregExp, constNegOne, mask);

// Select expm1 result based on |z|
Reg::Abs(vregAbsZ, vregNeg, mask);
```

**片段 2** (行 114-133):

```cpp
Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
Reg::Cast<float, T, castTrait0>(vregInputFloat, vregInput, mask);
Reg::Muls(vregNeg, vregInputFloat, inputScale, mask);

// Polynomial expm1(z) = z + z^2/2 + z^3/6 + z^4/24 for |z| < threshold
// Horner: T1 = T1 * z + coeff, then poly = T1 * z
Reg::Muls(vregT1, vregNeg, coeff4, mask);
Reg::Adds(vregT1, vregT1, coeff3, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff2, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff1, mask);
Reg::Mul(vregPoly, vregT1, vregNeg, mask);

// exp(z) - 1 for |z| >= threshold
Reg::Exp(vregExp, vregNeg, mask);
Reg::Adds(vregExp, vregExp, constNegOne, mask);

// Select expm1 result based on |z|
Reg::Abs(vregAbsZ, vregNeg, mask);
```

**要点**:
- 调用 Exp(vregExp, vregNeg, mask)，对取负后的输入求 exp
- 两处 Exp 对应不同片段，配合 CompareScalar 做正负分支选择
- 正值透传、负值走 α(e^x-1)，Exp 仅作用于负分支

### 实例 12：silu_grad::Compute2

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Cast, CreateMask, DataCopy, Div, Duplicate, LoadDist, MaskMergeMode, Mul, Muls, StoreDist, Sub, UpdateMask
- **Exp 调用次数**: 1
- **参数模式**: `T2_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义（待补充）**: 在 silu (x·sigmoid(x)) 梯度核中通过显式模板 Exp<float, ZEROING> 对中间值求 exp，构造 sigmoid 导数。

（行 137-158）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<float>(size);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, bfloat16_t, castTrait0>(vreg1, vreg0, preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg3, bufferIn1Addr + i * (AscendC::VECTOR_REG_WIDTH / 4));
    AscendC::Reg::Cast<float, half, castTrait0>(vreg4, vreg3, preg0);
    AscendC::Reg::Muls<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
        vreg5, vreg4, static_cast<float>(-1), preg0);
    AscendC::Reg::Exp<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg6, vreg5, preg0);
    AscendC::Reg::Adds<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
        vreg7, vreg6, static_cast<float>(1), preg0);
    AscendC::Reg::Div<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg8, vreg2, vreg7, preg0);
    AscendC::Reg::Sub<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg9, vreg2, vreg8, preg0);
    AscendC::Reg::Mul<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg10, vreg9, vreg4, preg0);
    AscendC::Reg::Add<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg11, vreg2, vreg10, preg0);
    AscendC::Reg::Mul<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg12, vreg8, vreg11, preg0);
    AscendC::Reg::Mul<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg13, vreg1, vreg12, preg0);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_NORM_B32>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / 4), vreg13, preg0);
}
```

**要点**:
- 无 mask 实参（M0 模式），模板显式 float + ZEROING
- silu 梯度=sigmoid+x·sigmoid·(1-sigmoid)，Exp 用于 sigmoid
- 单次 Exp 调用，与 Div/Adds 组合

### 实例 13：mish_grad::MishCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Axpy, CompareScalar, DataCopy, Div, LoadDist, MaskReg, Muls, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Exp 调用次数**: 8
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 在 mish 梯度核中四次调用 Exp 计算 e^{-x}、e^{-2x} 及中间项，用于 softplus/tanh 的导数链。

（行 109-138）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(vregInput,
                                                         (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

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

    Reg::CompareScalar<float, CMPMODE::LT>(cmpMaskReg, vregInput, FP32_ZERO, mask);
    Reg::Select(vregOutput, vregInputMid, vregOutput, cmpMaskReg);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_NORM_B32>((__ubuf__ T*)(dstAddr + loopIdx * vlSize),
                                                              vregOutput, mask);
}
```

**要点**:
- 四次 Exp 调用，与正向 mish (实例 6) 对称覆盖正负指数
- 梯度涉及 softplus'·tanh + softplus·tanh'，两项都依赖 Exp
- 与 Axpy/CompareScalar 组合完成梯度累加

### 实例 14：swiglu_backward_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, DataCopy, Div, Duplicate, LoadDist, MaskReg, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **Exp 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 在 SwiGLU 反向量化核中对 sigmoid 中间结果调用 Exp，构造 sigmoid 导数用于门控梯度反向传播。

（行 557-592）

```cpp
for (uint16_t dim1vfLoopIdx = 0; dim1vfLoopIdx < dim1VfTimes + dim1TailTimes; dim1vfLoopIdx++) {
    mask = Reg::UpdateMask<float>(length);
    Reg::AddrReg srcIdxOffset = Reg::CreateAddrReg<xDtype>(dim0vfLoopIdx, alignDim1In,
                                                                     dim1vfLoopIdx, VF_LEN_FP32);
    Reg::DataCopy<xDtype, Reg::LoadDist::DIST_UNPACK_B16>(regHalf, actAddr, srcIdxOffset);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(regA, regHalf, mask);
    Reg::DataCopy<xDtype, Reg::LoadDist::DIST_UNPACK_B16>(regHalf, gateAddr, srcIdxOffset);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(regB, regHalf, mask);
    Reg::DataCopy<xDtype, Reg::LoadDist::DIST_UNPACK_B16>(regHalf, yGradAddr, srcIdxOffset);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(regGrad, regHalf, mask);

    Reg::Muls(regSig, regA, negScalarOne, mask);
    Reg::Exp(regSig, regSig, mask);
    Reg::Adds(regSig, regSig, scalarOne, mask);
    Reg::Duplicate(regOut, scalarOne, mask);
    Reg::Div(regSig, regOut, regSig, mask);

    Reg::Muls(regOut, regSig, negScalarOne, mask);
    Reg::Adds(regOut, regOut, scalarOne, mask);
    Reg::Mul(regOut, regOut, regA, mask);
    Reg::Adds(regOut, regOut, scalarOne, mask);
    Reg::Mul(regOut, regOut, regB, mask);
    Reg::Mul(regOut, regOut, regSig, mask);
    Reg::Mul(regOut, regOut, regGrad, mask);

    Reg::AddrReg outOffsetA = Reg::CreateAddrReg<xDtype>(dim0vfLoopIdx, outAllNum, dim1vfLoopIdx,
                                                                   VF_LEN_FP32);
    Reg::Cast<xDtype, float, CAST_FP32_TO_FP16_BF16>(regHalf, regOut, mask);
    DataCopy<xDtype, Reg::StoreDist::DIST_PACK_B32>(gradXAddr, regHalf, outOffsetA, mask);

    Reg::Mul(regSig, regSig, regGrad, mask);
    Reg::Mul(regSig, regSig, regA, mask);

    Reg::Cast<xDtype, float, CAST_FP32_TO_FP16_BF16>(regHalf, regSig, mask);
    DataCopy<xDtype, Reg::StoreDist::DIST_PACK_B32>(gradXAddr + dataLenAB, regHalf, outOffsetA, mask);
}
```

**要点**:
- 调用 Exp(regSig, regSig, mask)，原地更新
- 与正向 swiglu (实例 3) 配对，反向需 sigmoid 导数 sig·(1-sig)
- 配合 CreateAddrReg/Adds/DataCopy 完成双轴量化反传

### 实例 15：sigmoid_cross_entropy_with_logits_v2::CalcBCEWithLogitsV2

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, DataCopy, Duplicate, Log, MaskReg, Mins, Mul, Neg, PostLiteral, RegTensor, Sub, UpdateMask
- **Exp 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在 BCE-with-logits 核中对 -|x| 调用 Exp 计算 e^{-|x|}，用于数值稳定的 sigmoid 概率计算。

（行 87-98）

```cpp
if constexpr (HAS_POS_WEIGHT) {
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(regPosWeight, posWeightAddr,
                                                                   (int32_t)oneRepeat);
}

Reg::Mins(regMinVal, regX, (T)0.0f, pregUp);
Reg::Abs(regAbsX, regX, pregUp);
Reg::Neg(regNegAbsX, regAbsX, pregUp);
Reg::Exp(regExpNegAbsX, regNegAbsX, pregUp);
Reg::Adds(regOneAddExp, regExpNegAbsX, (T)1.0f, pregUp);
Reg::Log(regLog, regOneAddExp, pregUp);
```

**要点**:
- 调用 Exp(regExpNegAbsX, regNegAbsX, pregUp)，无 mask 实参（M0），用 predicate pregUp
- 用 -|x|=-|logit| 形式保证 exp 不溢出（数值稳定技巧）
- 配合 Log+Adds+Abs 组合实现 BCE 损失

### Exp 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| tanh | Abs, Adds, And, Cast, CompareScalar | 多项式逼近中 Exp(2|x|) 构造 e^{±x} 比值，配 Select 做饱和 | __aicore__ |
| cdist | Abs, Add, CreateMask, Duplicate | Exp<float,&modeexp> 显式 Subnormal 模式，配 ReduceSum 做 softmax 归一化 | __VEC_SCOPE__ |
| swiglu_mx_quant | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | Exp(expReg, mulsReg, mask) 计算 e^x 构造 sigmoid 门控 | __VEC_SCOPE__ |
| sinh | Abs, Add, Adds, CompareScalar, DataCopy | Exp(reg_exp, reg_temp, mask) 实现 (e^x-e^-x)/2 | __aicore__ |
| swish_grad | Adds, Cast, DataCopy, Div, Duplicate | Exp 原地更新构造 sigmoid 导数项 | __aicore__ |
| mish | Add, Adds, Axpy, Cast, CompareScalar | 四次 Exp 覆盖 e^{±x,±2x} 构造 softplus+tanh | __aicore__ |
| cross_entropy_loss_grad | Add, AddrReg, Cast, CreateAddrReg, CreateMask | 无 mask 的 Exp(log_prob) 由 log 域回概率域 | __VEC_SCOPE__ |
| gelu_grad | Add, Adds, Axpy, Compare, DataCopy | Exp 原地更新构造 erf/高斯梯度项 | __aicore__ |
| softplus_v2_grad | AddrReg, Adds, Compare, CreateAddrReg, Div | 模板 T1+Mask，Exp(T2→T3) 流水线阶段构造 sigmoid | __simd_vf__ |
| glu_grad | Add, Adds, Cast, CastTrait, DataCopy | 显式 Exp<float,ZEROING> 无 mask，多路径 sigmoid 导数 | __aicore__ |
| elu | Abs, Adds, Cast, CompareScalar, DataCopy | Exp(vregExp, vregNeg, mask) 仅负分支计算 α(e^x-1) | __aicore__ |
| silu_grad | Add, Adds, Cast, CreateMask, DataCopy | 显式 Exp<float,ZEROING> 无 mask 构造 sigmoid 导数 | __aicore__ |
| mish_grad | Add, Adds, Axpy, CompareScalar, DataCopy | 四次 Exp 对称覆盖正负指数构造 mish 导数链 | __aicore__ |
| swiglu_backward_mx_quant_with_dual_axis | AddrReg, Adds, Cast, CreateAddrReg, DataCopy | Exp(regSig, regSig, mask) 原地更新构造 sigmoid 反传导数 | __VEC_SCOPE__ |
| sigmoid_cross_entropy_with_logits_v2 | Abs, Adds, DataCopy, Duplicate | 无 mask Exp(-|x|) 数值稳定构造 sigmoid | __aicore__ |

