# Div

**页面ID:** atlasascendc_api_07_0359  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0359.html

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

根据mask对输入数据srcReg0、srcReg1执行按元素相除操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0359_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, auto mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Div(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint16_t、int16_t、half、uint32_t、int32_t、float、complex32、int64_t、uint64_t、complex64。 |
| mode | 可配置为MaskMergeMode的枚举或DivSpecificMode的结构体指针。 - 配置MaskMergeMode，选择MERGING模式或ZEROING模式。  - ZEROING，mask未筛选的元素在dstReg中置零。  - MERGING, 暂不支持。 - 配置DivSpecificMode``` enum class DivAlgo {     INTRINSIC = 0,     DIFF_COMPENSATION,     PRECISION_1ULP_FTZ_TRUE,     PRECISION_0ULP_FTZ_TRUE,     PRECISION_0ULP_FTZ_FALSE,     PRECISION_1ULP_FTZ_FALSE }; struct DivSpecificMode {     MaskMergeMode mrgMode = MaskMergeMode::ZEROING,     bool precisionMode = false;     DivAlgo algo = DivAlgo::INTRINSIC; }; ``` 当precisionMode为true时，使能更高精度的Div计算，使用差值补偿算法得出结果，最大精度误差为0 ulp。目前只针对float数据类型生效。  - algo：用于配置Subnormal模式。  - DivAlgo::INTRINSIC、DivAlgo::PRECISION_1ULP_FTZ_TRUE，使用单指令计算得出结果，最大精度误差为1 ulp。  - DivAlgo::DIFF_COMPENSATION、DivAlgo::PRECISION_0ULP_FTZ_TRUE，使用差值补偿算法得出结果，最大精度误差为0 ulp。目前，该算法支持float、complex64数据类型。  - DivAlgo::PRECISION_0ULP_FTZ_FALSE，支持Subnormal数据计算，使用差值补偿算法得出结果，最大精度误差为0 ulp。目前，该算法支持float数据类型。  - DivAlgo::PRECISION_1ULP_FTZ_FALSE，支持Subnormal数据计算，使用单指令计算得出结果，最大精度误差为1 ulp。目前，该算法支持half、float数据类型。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void DivVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    // 高精度模式
    // static constexpr AscendC::Reg::DivSpecificMode mode = {AscendC::Reg::MaskMergeMode::ZEROING, true};
    // Subnormal模式
    // static constexpr AscendC::Reg::DivSpecificMode mode = {AscendC::Reg::MaskMergeMode::ZEROING, true, DivAlgo::PRECISION_0ULP_FTZ_FALSE};
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Div(dstReg, srcReg0, srcReg1, mask);
        // 高精度模式/Subnormal模式
        // AscendC::Reg::Div<T, &mode>(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Div 实例

### 实例 1：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Div 调用次数**: 5
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义**: dynamic_quant 的逐元素量化：先用 Div<float, &mode>(vregMaxDivScale, vregFinalMax, vreg9, preg5) 由 max 除以 scale 得到对称量化偏移基准，再用 Div(vreg16, vreg3, vreg10, preg2) 把输入 x 除以 scale 完成量化；通过 DivSpecificMode 指针配置高精度/Subnormal 模式。

**片段 1** (行 375-393):

```cpp
AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg4);
AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg4);
AscendC::Reg::Max(vreg7, vreg3, vreg7, preg4);
AscendC::Reg::Min(vregMinX, vreg3, vregMinX, preg4);
AscendC::Reg::ReduceMax(vregReduceMaxXTail, vreg7, preg4);
AscendC::Reg::ReduceMin(vregReduceMinXTail, vregMinX, preg4);

AscendC::Reg::Max(vregFinalMax, vregReduceMaxX, vregReduceMaxXTail, preg5);
AscendC::Reg::Min(vregFinalMin, vregReduceMinX, vregReduceMinXTail, preg5);

AscendC::Reg::Sub(vregMaxSubMin, vregFinalMax, vregFinalMin, preg5);
AscendC::Reg::Muls(vreg9, vregMaxSubMin, offsetDivValue, preg5);
AscendC::Reg::Duplicate(vreg10, vreg9, preg1);
AscendC::Reg::DataCopyUnAlign<float, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
    scaleAddr, vreg9, ureg0, 1);
AscendC::Reg::Div<float, &mode>(vregMaxDivScale, vregFinalMax, vreg9, preg5);
AscendC::Reg::Muls(vregNegMaxDivScale, vregMaxDivScale, NEGATIVE_ONE, preg5);
AscendC::Reg::Adds(vregOffset, vregNegMaxDivScale, offsetValue, preg5); //
AscendC::Reg::Duplicate(vregDupOffset, vregOffset, preg1);
```

**片段 2** (行 409-432):

```cpp
if constexpr (isSymmetrical == true) {
    AscendC::Reg::Div(vreg16, vreg3, vreg10, preg2);
} else if constexpr (isSymmetrical == false) {
    AscendC::Reg::Div(vregXDivScale, vreg3, vreg10, preg2);
    AscendC::Reg::Add(vreg16, vregXDivScale, vregDupOffset, preg2);
}
if constexpr (IsSameType<yDtype, int8_t>::value) {
    AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vreg17, vreg16, preg2);
    AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vreg18, vreg17, preg2);
    AscendC::Reg::Cast<yDtype, half, castTraitF16ToI8>(vreg19, vreg18, preg2);
} else if constexpr (IsSameType<yDtype, hifloat8_t>::value) {
    AscendC::Reg::Cast<yDtype, float, castTraitF32toh8>(vreg19, vreg16, preg2);
} else if constexpr (IsSameType<yDtype, fp8_e4m3fn_t>::value || IsSameType<yDtype, fp8_e5m2_t>::value) {
    AscendC::Reg::Cast<yDtype, float, castTraitF32tofp8>(vreg19, vreg16, preg2);
} else if constexpr (IsSameType<yDtype, int4b_t>::value) {
    AscendC::Reg::RegTensor<uint16_t> vreg20;
    AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vreg17, vreg16, preg2);
    AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vreg18, vreg17, preg2);
    AscendC::Reg::Pack(vreg20, (AscendC::Reg::RegTensor<uint32_t>&)vreg18);
    AscendC::Reg::Cast<int4x2_t, half, castTraitF16ToI8>(
        (AscendC::Reg::RegTensor<int4x2_t>&)vreg19, (AscendC::Reg::RegTensor<half>&)vreg20,
        preg2);
    addr = yAddr + (multiRow * outAlignLen + j * VL) / 2;
}
```

**要点**:
- 模板参数 <float, &mode>：第二参数是 DivSpecificMode 结构体指针，控制精度算法（INTRINSIC/DIFF_COMPENSATION 等）。
- 无 mask 形参（M0）：本例用全量 predicate preg5/preg2，调用形如 Div<T, &mode>(dst, src0, src1, preg)。
- 对称/非对称分支：isSymmetrical 决定 x/scale 后是否再加 offset。

### 实例 2：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CompareScalar, CreateMask, DataCopy, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Max, Min, PostLiteral, ReduceMax, RegLayout, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **Div 调用次数**: 11
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: float）
- **语义**: dynamic_block_quant 的 block 级量化：片段 1 用 Div<float, &mode>(vReg8, vReg4, fp8MaxValue, defaultMaskReg) 由 input_max 除以 fp8Max 得 scale；片段 2 用 Div<float, &mode>(vReg13/vReg14, vReg11/vReg12, vReg8, defaultMaskReg) 对 interleave 后输入除以 scale 完成量化。

**片段 1** (行 339-362):

```cpp
for (uint16_t vlLoopIdx = 0; vlLoopIdx < normalLoopNum; vlLoopIdx++) {
    inputMaskReg = AscendC::Reg::UpdateMask<IN_TYPE>(curSize);
    AscendC::Reg::DataCopy(vReg0, xLocal + rowIdx * inputColAlign +
                                           colIdx * tilingData_->blockSizeCol + vlLoopIdx * VL);
    AscendC::Reg::And((AscendC::Reg::RegTensor<uint32_t>&)vReg3,
                           (AscendC::Reg::RegTensor<uint32_t>&)vReg0,
                           (AscendC::Reg::RegTensor<uint32_t>&)vRegFp32Max, inputMaskReg);
    AscendC::Reg::Max<uint32_t, AscendC::Reg::MaskMergeMode::MERGING>(
        (AscendC::Reg::RegTensor<uint32_t>&)vReg2,
        (AscendC::Reg::RegTensor<uint32_t>&)vReg2,
        (AscendC::Reg::RegTensor<uint32_t>&)vReg3, inputMaskReg);
}

AscendC::Reg::ReduceMax<uint32_t>((AscendC::Reg::RegTensor<uint32_t>&)vReg3,
                                       (AscendC::Reg::RegTensor<uint32_t>&)vReg2,
                                       defaultMaskReg);

AscendC::Reg::Duplicate(vReg4, vReg3, defaultMaskReg);

// brc(input_max) - 位模式直接参与计算
AscendC::Reg::Div<float, &mode>(vReg8, (AscendC::Reg::RegTensor<float>&)vReg4,
                                     fp8MaxValue, defaultMaskReg);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(
    scaleMaskReg, (AscendC::Reg::RegTensor<uint32_t>&)vReg8, infValue_, defaultMaskReg);
```

**片段 2** (行 500-536):

```cpp
for (uint16_t vlLoopIdx = 0; vlLoopIdx < normalLoopNum; vlLoopIdx++) {
    inputMaskReg = AscendC::Reg::UpdateMask<IN_TYPE>(curSize);
    AscendC::Reg::DataCopy(vReg0, xLocal + rowIdx * inputColAlign +
                                           colIdx * tilingData_->blockSizeCol + vlLoopIdx * VL);
    AscendC::Reg::Cast<float, IN_TYPE, castTraitZero>(vReg9, vReg0, defaultMaskReg);
    AscendC::Reg::Cast<float, IN_TYPE, castTraitOne>(vReg10, vReg0, defaultMaskReg);
    AscendC::Reg::Interleave(vReg11, vReg12, vReg9, vReg10);
    AscendC::Reg::Div<float, &mode>(vReg13, vReg11, vReg8, defaultMaskReg);
    AscendC::Reg::Div<float, &mode>(vReg14, vReg12, vReg8, defaultMaskReg);

    if constexpr (IsSameType<OUT_TYPE, hifloat8_t>::value) {
        AscendC::Reg::Cast<OUT_TYPE, float, castTrait32toh8Zero>(vReg15, vReg13,
                                                                      defaultMaskReg);
        AscendC::Reg::Cast<OUT_TYPE, float, castTrait32toh8Zero>(vReg16, vReg14,
                                                                      defaultMaskReg);
    } else if constexpr (IsSameType<OUT_TYPE, int8_t>::value) {
        AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vReg19, vReg13, defaultMaskReg);
        AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vReg20, vReg19, defaultMaskReg);
        AscendC::Reg::Cast<OUT_TYPE, half, castTraitF16ToI8>(vReg15, vReg20, defaultMaskReg);
        AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vReg19, vReg14, defaultMaskReg);
        AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vReg20, vReg19, defaultMaskReg);
        AscendC::Reg::Cast<OUT_TYPE, half, castTraitF16ToI8>(vReg16, vReg20, defaultMaskReg);
    } else {
        AscendC::Reg::Cast<OUT_TYPE, float, castTrait32tofp8>(vReg15, vReg13, defaultMaskReg);
        AscendC::Reg::Cast<OUT_TYPE, float, castTrait32tofp8>(vReg16, vReg14, defaultMaskReg);
    }

    AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::LOWEST>(maskReg2, inputMaskReg);
    AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::HIGHEST>(maskReg3, inputMaskReg);

    AscendC::Reg::DataCopy<OUT_TYPE, AscendC::Reg::StoreDist::DIST_PACK4_B32>(
        outLocal + rowIdx * colSizeAlign + colIdx * tilingData_->blockSizeCol + vlLoopIdx * VL,
        vReg15, maskReg2);
    AscendC::Reg::DataCopy<OUT_TYPE, AscendC::Reg::StoreDist::DIST_PACK4_B32>(
        outLocal + rowIdx * colSizeAlign + colIdx * tilingData_->blockSizeCol + vlLoopIdx * VL + 64,
        vReg16, maskReg3);
}
```

**要点**:
- &mode 为 DivSpecificMode 指针，defaultMaskReg 是全 1 mask（M1，mask 标记为 Mask）。
- 位模式直接参与计算：input_max 以 uint32 位模式 And/Max 归约，再以 float 语义 Div。
- 配合 Interleave/MaskUnPack/HighLowPart 做 B32 打包的 block 量化输出。

### 实例 3：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Div 调用次数**: 3
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: fake_quant_with_min_max_vars_per_channel 的 scale/zp 重算：用 Div<float, &kDivMode> 三步——scale=(max-min)/qRange、invScaleSafe=qRange/diffSafe、zpFromMin=min/scaleSafe；刻意用 0-ULP Div 替代乘倒数，使结果与 TF Nudge() 的 IEEE 单步除法一致。

（行 374-416）

```cpp
// -----------------------------------------------------------------
// 阶段 2：Prepare 重算（替代 PrepareChannelScalarsForSegment）
// -----------------------------------------------------------------

// 2.0 构造常量 vregZero / vregOne / vregQRange（寄存器内）
AscendC::Reg::Sub<float>(vregZero, vregMin, vregMin, mask);
AscendC::Reg::Adds<float>(vregOne, vregZero, 1.0f, mask);
AscendC::Reg::Adds<float>(vregQRange, vregZero, qRange, mask);

// 2.1 scale = (max - min) / qRange
//     用 0-ULP Div 替代 (max-min)*invR：避免 invR=1/(qMax-qMin) 在 fp32 上的
//     round-to-nearest 误差与 (max-min)*invR 的舍入叠加，使 scale 精确等于
//     `(max-min)/(qMax-qMin)` 的 IEEE 单步除法结果（与 TF 实现一致）。
AscendC::Reg::Sub<float>(vregScale, vregMax, vregMin, mask);
AscendC::Reg::Copy<float>(vregDiffSaved, vregScale, mask);
AscendC::Reg::Div<float, &kDivMode>(vregScale, vregScale, vregQRange, mask);

// 2.2 bothZero = (|min| + |max| > 0) ? 1.0 : 0.0
AscendC::Reg::Abs<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregAbsMin, vregMin, mask);
AscendC::Reg::Abs<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregAbsMax, vregMax, mask);
AscendC::Reg::Add<float>(vregAbsSum, vregAbsMin, vregAbsMax, mask);
AscendC::Reg::Compares<float, AscendC::CMPMODE::GT>(maskBoth, vregAbsSum, 0.0f, mask);
// Select: mask=1 → src0(vregOne); mask=0 → src1(vregZero)
AscendC::Reg::Select<float>(vregBoth, vregOne, vregZero, maskBoth);

// 2.3 scale==0 兜底：vregScaleSafe = (scale==0) ? 1.0 : scale
AscendC::Reg::Compares<float, AscendC::CMPMODE::EQ>(maskScaleZero, vregScale, 0.0f, mask);
AscendC::Reg::Select<float>(vregScaleSafe, vregOne, vregScale, maskScaleZero);

// 2.3b invScaleSafe = qRange / diffSafe
//      TF Nudge() 独立计算 inv_scale = (qMax-qMin)/(max-min)，
//      而非 1/scale，避免 scale 的 fp32 舍入误差在取倒数时被放大。
//      diffSafe = (diff==0) ? 1.0 : diff（复用 maskScaleZero，因 scale==0 ⟺ diff==0）
AscendC::Reg::Select<float>(vregDiffSaved, vregOne, vregDiffSaved, maskScaleZero);
AscendC::Reg::Div<float, &kDivMode>(vregInvScaleSafe, vregQRange, vregDiffSaved, mask);

// 2.4 zp_from_min = qMin - min / scaleSafe
//     用 0-ULP Div：min/scaleSafe 在 zfm 落到 N+0.5 半整数边界时极易抖动 1 ULP，
//     与 floor(zfm+0.5) 叠加会让 nudged_zp 偏离 TF。
AscendC::Reg::Div<float, &kDivMode>(vregZpFromMin, vregMin, vregScaleSafe, mask);
AscendC::Reg::Muls<float>(vregZpFromMin, vregZpFromMin, -1.0f, mask);
AscendC::Reg::Adds<float>(vregZpFromMin, vregZpFromMin, qMin, mask);
```

**要点**:
- &kDivMode 指向配置 PRECISION_0ULP_FTZ_TRUE 的 DivSpecificMode，保证 0 ulp 误差。
- scale==0 兜底：用 Select 把 diff 为 0 时的除数替换为 1.0，避免 0 除。
- invScale 独立计算（qRange/diff）而非 1/scale，避免 scale 舍入误差在取倒数时放大。

### 实例 4：tanh::TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, And, Cast, CompareScalar, DataCopy, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, Or, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Div 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: tanh 的有理逼近：在多项式分支后用 Div(vregInputMid, vregOne, vregInputMid, mask) 计算 1/(1+e^(2|x|))，再组合 1 - 2/(1+e^(2|x|)) 得到 tanh；用 CompareScalar 做饱和边界 satMask。

**片段 1** (行 80-98):

```cpp
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
```

**片段 2** (行 122-140):

```cpp
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
Reg::Adds(vregInputMid, vregInputMid, FP32_ONE, mask);
Reg::CompareScalar<float, CMPMODE::GE>(satMaskReg, vregInputAbs, FP32_SAT_BOUND, mask);
```

**要点**:
- 无显式模板参数（T0）：类型由 vregInput 推导，mask 来自 UpdateMask（M1）。
- vregOne 是预先 Duplicate(1.0f) 的常量寄存器，作为除数分子构造倒数。
- 配合 FusedMulDstAdd/Exp 构成 tanh 的混合多项式+指数逼近。

### 实例 5：clipped_swiglu::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Exp, LoadDist, MaskPattern, MaskReg, Maxs, Mins, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **Div 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: clipped_swiglu 的门控 sigmoid：用 Div(sigmoidReg, minsReg, addsReg, mask) 计算 sigmoid(min(x,clamp)/(1+e^(-α·min(x,clamp))))，再乘 clamp 后的 x2 得 SwiGLU 输出；先 Mins/Maxs 做 clamp。

（行 372-407）

```cpp
if constexpr (isInterleaved) {
    if constexpr (sizeof(T) == sizeof(half)) {
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddr,
                                                                                     srcIdxOffset);
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddr,
                                                                                     srcIdxOffset);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX1F, vregX1, mask);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX2F, vregX2, mask);
    } else {
        // float
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX1F, x1UbAddr, srcIdxOffset);
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX2F, x2UbAddr, srcIdxOffset);
    }
    AscendC::Reg::DeInterleave(vregX1DeF, vregX2DeF, vregX1F, vregX2F);
} else {
    if constexpr (sizeof(T) == sizeof(half)) {
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddr,
                                                                                     srcIdxOffset);
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddr,
                                                                                     srcIdxOffset);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX1DeF, vregX1, mask);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX2DeF, vregX2, mask);
    } else {
        // float
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX1DeF, x1UbAddr, srcIdxOffset);
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX2DeF, x2UbAddr, srcIdxOffset);
    }
}
AscendC::Reg::Mins(minsReg, vregX1DeF, clampLimit, mask);
AscendC::Reg::Muls(mulsReg, minsReg, negAlpha, mask);
AscendC::Reg::Exp(expReg, mulsReg, mask);
AscendC::Reg::Adds(addsReg, expReg, scalarOne, mask);
AscendC::Reg::Div(sigmoidReg, minsReg, addsReg, mask);

AscendC::Reg::Mins(vregX2DeF, vregX2DeF, clampLimit, mask);
AscendC::Reg::Maxs(vregX2DeF, vregX2DeF, negClampLimit, mask);
```

**要点**:
- 无显式模板参数（T0），mask 为 MaskReg（M1）。
- addsReg = 1 + e^(-α·clamped_x)，minsReg = min(x, clampLimit)，Div 实现 sigmoid 门控。
- 配合 DeInterleave/Cast 处理 half/float 与交错布局。

### 实例 6：swiglu_mx_quant::VecScope_L446

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Exp, LoadDist, MaskPattern, MaskReg, Maxs, Mins, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **Div 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: swiglu_mx_quant（axis_last）的 SwiGLU 门控：循环内用 Div(sigmoidReg, minsReg, addsReg, mask) 计算 clamped sigmoid，再 Mul(outFReg, sigmoidReg, vregX2DeF) 得门控输出；尾块用 mask1 处理边界。

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
- 无显式模板参数（T0），主循环 mask + 尾块 mask1（M1）。
- 与实例 5（clipped_swiglu）同构，区别在 axis_last 的 CreateAddrReg 偏移与 DIST_PACK_B32 输出布局。
- 配合 Mins/Muls/Exp/Adds 构造 x/(1+e^(-αx))。

### 实例 7：pool_3d_common::ComputeDivisorImplB64

- **来源类型**: `__aicore__`
- **共现 API**: AddrReg, Arange, CreateAddrReg, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, MaskPattern, MaskReg, Mul, RegTensor, RegTraitNumTwo, Sub, UnalignReg, UpdateMask
- **Div 调用次数**: 8
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: pool_3d_common 的池窗口坐标分解：用 Div(vd1, v0, v1, p0) 把线性索引 i 除以 outhw/outhw/outw，配合 Mul+Sub 取模，分解出 (didx, hidx, widx) 喂给 CalcWindowSize。

**片段 1** (行 1054-1075):

```cpp
for (uint16_t i = 0; i < loopNum; i++) {
    Reg::Arange(v0, i * oneRegLength + start);
    Reg::AddrReg resOffset = Reg::CreateAddrReg<float32_t>(i, oneRegLength);
    Reg::MaskReg pWrite = Reg::UpdateMask<float32_t>(sreg);
    Reg::Div(vd1, v0, v1, p0); // i / outhw  -> didx(vd1)
    CalcWindowSize<int64_t, countIncludePad>(dWindow, vd1, kD, sD, negFrontPad, dIn, dInAndBackendPad, p0);
    Reg::DataCopy(dstAddr, dWindow, resOffset, pWrite);
}
uint32_t sreg1 = oneBatchOut;
for (uint16_t i = 0; i < loopNum; i++) {
    Reg::Arange(v0, i * oneRegLength + start);
    Reg::AddrReg resOffset = Reg::CreateAddrReg<float32_t>(i, oneRegLength);
    Reg::MaskReg pWrite = Reg::UpdateMask<float32_t>(sreg1);
    Reg::Div(vd1, v0, v1, p0);  // i / outhw
    Reg::Mul(vd2, vd1, v1, p0); // (i / outhw * outhw)
    Reg::Sub(vd3, v0, vd2, p0); // i % outhw
    Reg::Div(vd2, vd3, v2, p0); // i % outhw / outh
    CalcWindowSize<int64_t, countIncludePad>(hWindow, vd2, kH, sH, negTopPad, hIn, hInAndBottomPad, p0);
    Reg::DataCopy(res, dstAddr, resOffset);
    Reg::Mul(res, res, hWindow, p0);
    Reg::DataCopy(dstAddr, res, resOffset, pWrite);
}
```

**片段 2** (行 1077-1089):

```cpp
for (uint16_t i = 0; i < loopNum; i++) {
    Reg::Arange(v0, i * oneRegLength + start);
    Reg::AddrReg resOffset = Reg::CreateAddrReg<float32_t>(i, oneRegLength);
    Reg::MaskReg pWrite = Reg::UpdateMask<float32_t>(sreg2);
    Reg::Div(vd3, v0, v2, p0);  // i / outw
    Reg::Mul(vd3, vd3, v2, p0); // (i / outhw * outhw)
    Reg::Sub(vd3, v0, vd3, p0); // i % outhw
    CalcWindowSize<int64_t, countIncludePad>(wWindow, vd3, kW, sW, negLeftPad, wIn, wInAndRightPad, p0);
    Reg::DataCopy(res, dstAddr, resOffset);
    Reg::Mul(res, res, wWindow, p0);
    Reg::DataCopy(dstAddr, res, resOffset, pWrite);
}
```

**要点**:
- 无显式模板参数、无 mask 形参（M0），用全量 p0 predicate。
- Arange 生成索引向量 v0，v1/v2 是 outhw/outw 常量寄存器。
- 索引除法（非数值量化），Div 用于 divmod 坐标分解。

### 实例 8：grouped_dynamic_block_quant::ops::IsSame

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CompareScalar, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, ReduceMax, RegTensor, StoreAlign, StoreDist, UpdateMask
- **Div 调用次数**: 10
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义**: grouped_dynamic_block_quant 的 block 量化：片段 1 用 Div((float&)scaleRegTensor, expMaxRegTensorFp32, fp8MaxRegTensor, scaleMask32) 由 amax 除以 fp8Max 得 scale；片段 2 用 Div((float&)yRegTensorFp32, yRegTensorFp32, scaleRegTensor, dataLenMask32) 把输入除以 scale 完成量化。

**片段 1** (行 355-374):

```cpp
for (uint16_t step128 = 0; step128 < static_cast<uint16_t>(normalStep128); step128++) {
    dataLenMask16 = AscendC::Reg::UpdateMask<uint16_t>(pnum16);
    AscendC::Reg::LoadAlign(xRegTensor, xAddr + stepBlock * blockDataNumOffset + step128 * vfLen);
    AscendC::Reg::And(xAbsRegTensor, (AscendC::Reg::RegTensor<uint16_t>&)xRegTensor,
                           absMaskRegTensor, dataLenMask16);
    AscendC::Reg::Max<uint16_t, AscendC::Reg::MaskMergeMode::MERGING>(
        expMaxRegTensor, expMaxRegTensor, xAbsRegTensor, dataLenMask16);
}
pnum16 = normalBlockDataNum;
dataLenMask16 = AscendC::Reg::UpdateMask<uint16_t>(pnum16);
AscendC::Reg::ReduceMax<uint16_t>(expMaxRegTensor, expMaxRegTensor, dataLenMask16);
AscendC::Reg::Cast<float, T, castTraitT2Float>(
    expMaxRegTensorFp32, (AscendC::Reg::RegTensor<T>&)expMaxRegTensor, dataLenMask16);

// scale
AscendC::Reg::Duplicate(expMaxRegTensorFp32, expMaxRegTensorFp32, scaleMask32);
AscendC::Reg::Div((AscendC::Reg::RegTensor<float>&)scaleRegTensor, expMaxRegTensorFp32,
                       fp8MaxRegTensor, scaleMask32);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(
    scaleMaskReg, (AscendC::Reg::RegTensor<uint32_t>&)scaleRegTensor, infValue_, scaleMask32);
```

**片段 2** (行 384-397):

```cpp
for (uint16_t step64 = 0; step64 < static_cast<uint16_t>(normalStep64); step64++) {
    dataLenMask32 = AscendC::Reg::UpdateMask<uint32_t>(pnum32);
    AscendC::Reg::LoadAlign<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        xRegTensor, xAddr + stepBlock * blockDataNumOffset + step64 * vfNum);
    AscendC::Reg::Cast<float, T, castTraitT2Float>(
        (AscendC::Reg::RegTensor<float>&)yRegTensorFp32, xRegTensor, dataLenMask32);
    AscendC::Reg::Div((AscendC::Reg::RegTensor<float>&)yRegTensorFp32,
                           (AscendC::Reg::RegTensor<float>&)yRegTensorFp32,
                           (AscendC::Reg::RegTensor<float>&)scaleRegTensor, dataLenMask32);
    AscendC::Reg::Cast<U, float, castTrait32to8>(
        yRegTensorFp8, (AscendC::Reg::RegTensor<float>&)yRegTensorFp32, dataLenMask32);
    AscendC::Reg::StoreAlign<U, Reg::StoreDist::DIST_PACK4_B32>(
        yOutAddr + stepBlock * blockDataNumOffset + step64 * vfNum, yRegTensorFp8, dataLenMask32);
}
```

**要点**:
- 指纹 arg_count=1 是解析器对 (RegTensor<float>&) 强转前缀的计数偏差，实际是标准 4 参 Div。
- 无模板 &mode（用默认 INTRINSIC），scaleMask32/dataLenMask32 为 MaskReg。
- 配合 LoadAlign+And+Max 做 uint16/half 位模式的 amax 归约。

### 实例 9：sinh::SinhCustomVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, CompareScalar, DataCopy, DivSpecificMode, Duplicate, Exp, MaskMergeMode, MaskReg, Mul, Neg, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **Div 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: sinh 的 exp 分支：用 Div<T, &divMode>(reg_temp, reg_temp, reg_exp, mask) 计算 inv_t = 0.25 / e^(|x|-ln2) = e^(-|x|)/2，再 Sub(reg_exp, reg_exp, reg_temp) 得 sinh(|x|) = e^|x|/2 - e^(-|x|)/2。

（行 105-123）

```cpp

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
// exp_result = t - 0.25/t = e^|x|/2 - e^(-|x|)/2 = sinh(|x|)
AscendC::Reg::Sub(reg_exp, reg_exp, reg_temp, mask);
```

**要点**:
- 模板 <T, &divMode>：T 由调用者推导，&divMode 指向高精度 DivSpecificMode（M1，mask）。
- 用 |x|-ln2 偏移 exp 防溢出，Div 构造倒数得到 e^(-|x|)/2。
- 小区用 Taylor 多项式分支，大区用 exp+Div 分支，Select 切换。

### 实例 10：fake_quant_affine_cachemask::AscendC::LocalTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, DataCopy, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskReg, Maxs, Mins, Mul, MulDstAdd, Muls, RegTensor, StoreDist, Sub, UpdateMask
- **Div 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: float）
- **语义**: fake_quant_affine_cachemask 的倒数求 invScale：用 Reg::Div<float, &divMode>(vregInvSc, vregOne, vregSc, fullMask) 计算 1/scale（invSc），供后续 affine 量化使用；vregSc 是 BRC_B32 广播的同值 scale。

（行 349-360）

```cpp
// vregSc 是 BRC_B32 全 VL 同值，需要先建立一个 mask 给 Div 使用
{
    uint32_t fullSreg = static_cast<uint32_t>(VL_FP32);
    Reg::MaskReg fullMask = Reg::UpdateMask<uint32_t>(fullSreg);
    Reg::Duplicate<float>(vregOne, 1.0f);
    static constexpr AscendC::Reg::DivSpecificMode divMode = {
        AscendC::Reg::MaskMergeMode::ZEROING, true};
    Reg::Div<float, &divMode>(vregInvSc, vregOne, vregSc, fullMask);
}
if constexpr (HAS_ZP == 1) {
    Reg::DataCopy<float, Reg::LoadDist::DIST_BRC_B32>(vregZp, zPtr + zpBaseOff + j);
}
```

**要点**:
- 模板 <float, &divMode>，&divMode 配 MaskMergeMode::ZEROING + precisionMode=true（M1，mask 标记 Mask）。
- 因 vregSc 是广播同值，先 UpdateMask(VL_FP32) 建 fullMask 给 Div 用。
- 求 1/scale 而非直接 x/scale，配合 MulDstAdd 做 affine 反量化。

### 实例 11：logsigmoid_grad::LogSigmoidGradCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, Cast, Compare, Duplicate, Exp, LoadAlign, LoadDist, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, Select, StoreAlign, StoreDist, UpdateMask
- **Div 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: logsigmoid_grad 的 sigmoid 梯度：用 Div(Answer, vregSelect, SelfAbsNegExpAdd, mask) 计算 select(x, e^-|x|)/(1+e^-|x|)，再 Mul(LastAnswer, Answer, gradOut) 得 log-sigmoid 反向梯度。

**片段 1** (行 65-83):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::LoadAlign(vregInputGradOut, (__ubuf__ T*)(src0Addr + loopIdx * vlSize));
    Reg::LoadAlign(vregInputSelf, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));
    // compute
    Reg::Abs(SelfAbs, vregInputSelf, mask);
    Reg::Muls(SelfAbsNeg, SelfAbs, (float)-1.0, mask);
    Reg::Exp(SelfAbsNegExp, SelfAbsNeg, mask);
    Reg::Adds(SelfAbsNegExpAdd, SelfAbsNegExp, (float)1.0, mask);

    Reg::Compare<float, CMPMODE::LT>(cmpMask, vregInputSelf, DataZero, mask);
    Reg::Select(vregSelect, DataOne, SelfAbsNegExp, cmpMask);
    Reg::Div(Answer, vregSelect, SelfAbsNegExpAdd, mask);
    Reg::Mul(LastAnswer, Answer, vregInputGradOut, mask);

    // OpCopyOut
    Reg::StoreAlign((__ubuf__ T*)(dstAddr + loopIdx * vlSize), LastAnswer, mask);
}
```

**片段 2** (行 95-113):

```cpp
// OpCopyIn
Reg::LoadAlign<T, Reg::LoadDist::DIST_UNPACK_B16>(
    vregInputGradOutT, (__ubuf__ T*)(src0Addr + loopIdx * vlSize));
Reg::LoadAlign<T, Reg::LoadDist::DIST_UNPACK_B16>(
    vregInputSelfT, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));
Reg::Cast<float, T, castTrait0>(vregInputGradOut, vregInputGradOutT, mask);
Reg::Cast<float, T, castTrait0>(vregInputSelf, vregInputSelfT, mask);
// compute
Reg::Abs(SelfAbs, vregInputSelf, mask);
Reg::Muls(SelfAbsNeg, SelfAbs, (float)-1.0, mask);
Reg::Exp(SelfAbsNegExp, SelfAbsNeg, mask);
Reg::Adds(SelfAbsNegExpAdd, SelfAbsNegExp, (float)1.0, mask);

Reg::Compare<float, CMPMODE::LT>(cmpMask, vregInputSelf, DataZero, mask);
Reg::Select(vregSelect, DataOne, SelfAbsNegExp, cmpMask);
Reg::Div(Answer, vregSelect, SelfAbsNegExpAdd, mask);
Reg::Mul(LastAnswer, Answer, vregInputGradOut, mask);

Reg::Cast<T, float, castTrait1>(LastAnswerT, LastAnswer, mask);
```

**要点**:
- 无显式模板参数（T0），mask 来自 UpdateMask（M1）。
- Select(DataOne, SelfAbsNegExp, cmpMask) 按 x<0 选分子，避免 exp 溢出。
- half 输入走 Cast→float 计算，再 Cast 回 half（片段 2）。

### 实例 12：dynamic_block_quant::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CompareScalar, CreateMask, DataCopy, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, ReduceMax, RegTensor, StoreDist, UpdateMask
- **Div 调用次数**: 6
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: dynamic_block_quant（small_blocksize）的三步量化：Div<float, &mode>(reciprocalScale, 1.0f, minScaleReg) 求 1/minScale 上限、Div(scaleReg, expMax, fp8Max) 求 scale=amax/fp8Max、Div(yReg3, yReg1, scaleReg) 做 x/scale 量化。

**片段 1** (行 381-395):

```cpp
// comput scale - float32 直接用位模式参与计算
AscendC::Reg::ReduceMax<uint32_t>(expMaxRegTensor, expMaxRegTensor, maskAll);
AscendC::Reg::Duplicate(expMaxRegTensor, expMaxRegTensor, maskAll);
AscendC::Reg::Duplicate(fp8MaxReg, fp8MaxValue_);
AscendC::Reg::Duplicate(reciprocalScale, 1.0f);
AscendC::Reg::Duplicate(minScaleReg, minScale_);

AscendC::Reg::Div<float, &mode>(reciprocalScale, reciprocalScale, minScaleReg, maskAll);

// 位模式本身就是 float32 格式，直接参与计算
AscendC::Reg::Div<float, &mode>(scaleRegTensor, (AscendC::Reg::RegTensor<float>&)expMaxRegTensor,
                                     fp8MaxReg, ymaskAll);

AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(
    scaleMaskReg, (AscendC::Reg::RegTensor<uint32_t>&)scaleRegTensor, infValue_, ymaskAll);
```

**片段 2** (行 402-418):

```cpp
for (uint16_t i = 0; i < vfLoop; i++) {
    yMaskReg0 = AscendC::Reg::UpdateMask<float>(outputNum);
    AscendC::Reg::DataCopy(yReg1, xAddr + i * vfNum);
    AscendC::Reg::Div<float, &mode>(yReg3, yReg1, scaleRegTensor, yMaskReg0);

    if constexpr (IsSameType<U, hifloat8_t>::value) {
        AscendC::Reg::Cast<U, float, castTrait32toh8>(outReg, yReg3, yMaskReg0);
    } else if constexpr (IsSameType<U, int8_t>::value) {
        AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(int16Reg, yReg3, yMaskReg0);
        AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(halfReg, int16Reg, yMaskReg0);
        AscendC::Reg::Cast<U, half, castTraitF16ToI8>(outReg, halfReg, yMaskReg0);
    } else {
        AscendC::Reg::Cast<U, float, castTrait32tofp8>(outReg, yReg3, yMaskReg0);
    }
    AscendC::Reg::DataCopy<U, Reg::StoreDist::DIST_PACK4_B32>(yOutAddr + i * vfNum, outReg,
                                                                        yMaskReg0);
}
```

**片段 3** (行 442-456):

```cpp
AscendC::Reg::ReduceMax<uint16_t>(expMaxRegTensor, expMaxRegTensor, maskAll);
AscendC::Reg::Duplicate(expMaxRegTensor, expMaxRegTensor, maskAll);
AscendC::Reg::Duplicate(fp8MaxReg, fp8MaxValue_);
AscendC::Reg::Duplicate(reciprocalScale, 1.0f);
AscendC::Reg::Duplicate(minScaleReg, minScale_);

AscendC::Reg::Div<float, &mode>(reciprocalScale, reciprocalScale, minScaleReg, maskAll);
AscendC::Reg::Cast<float, T, castTrait0>(scaleRegTensor,
                                              (AscendC::Reg::RegTensor<T>&)expMaxRegTensor, maskAll);

AscendC::Reg::Div<float, &mode>(scaleRegTensor, scaleRegTensor, fp8MaxReg, ymaskAll);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(
    scaleMaskReg, (AscendC::Reg::RegTensor<uint32_t>&)scaleRegTensor, infValue_, ymaskAll);
AscendC::Reg::Min<float, AscendC::Reg::MaskMergeMode::MERGING>(scaleRegTensor, scaleRegTensor,
                                                                         reciprocalScale, scaleMaskReg);
```

**要点**:
- 模板 <float, &mode>，maskAll/ymaskAll 为全 1 MaskReg（M1，mask 标记 mask）。
- 用 Min(scale, reciprocalScale) 把 scale 钳到 minScale 上限，防止 block 过小放大 scale。
- 位模式归约：expMax 以 uint16/uint32 位模式 ReduceMax，再 Cast 成 float 做 Div。

### 实例 13：swish_grad::SwishGradCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, DataCopy, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, Neg, RegTensor, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **Div 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: swish_grad 的反向：用 Div(vregInputMid, vregValue1, vregInputMid, mask) 计算 1/(1+e^-x)，再组合 (1 - sigmoid)·x + sigmoid 的 swish 导数，乘 gradOut 输出。

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
- 无显式模板参数（T0），mask 为 MaskReg（M1）。
- vregValue1 是常量 1.0 寄存器，Div 构造 sigmoid 倒数。
- 配合 FusedMulDstAdd 融合乘加，half 走 Cast→float→Cast（片段 2）。

### 实例 14：gelu_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Cast, CreateMask, DataCopy, Duplicate, LocalMemBar, MaskPattern, MaskReg, Max, MemType, Mul, Muls, ReduceMax, RegTensor, StoreDist, UpdateMask
- **Div 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: gelu_quant 的量化除法：用 Div(vregQuantRes, vregInput, vregOutScale, preg2) 把（已乘 smoothScale 的）输入除以 outScale 完成量化，再按目标类型（int8/fp8/hifloat8）Cast 输出。

（行 323-346）

```cpp
for (uint16_t j = 0; j < loopNum; j++) {
    auto yOutAddr = yAddr + i * endAxisLenAlignTo8_ + j * vl;
    preg2 = AscendC::Reg::UpdateMask<float>(sreg1);
    AscendC::Reg::DataCopy(vregInput, xAddr + i * endAxisActualAlignLen_ + j * vl);
    AscendC::Reg::DataCopy(vregSmoothScale, smoothScaleAddr + j * vl);
    AscendC::Reg::Mul(vregInput, vregInput, vregSmoothScale, preg2);
    AscendC::Reg::Div(vregQuantRes, vregInput, vregOutScale, preg2);

    if constexpr (IsSameType<dstType, int8_t>::value) {
        AscendC::Reg::Cast<half, float, castTraitF32ToF16>(vregHalf, vregQuantRes, preg2);
        AscendC::Reg::Cast<dstType, half, castTraitF16ToI8Rint>(vregY, vregHalf, preg2);
    } else if constexpr (IsSameType<dstType, fp8_e4m3fn_t>::value ||
                         IsSameType<dstType, fp8_e5m2_t>::value) {
        AscendC::Reg::Cast<dstType, float, castTraitF32ToF8>(vregY, vregQuantRes, preg2);
    } else if constexpr (IsSameType<dstType, hifloat8_t>::value &&
                         roundMode == AscendC::RoundMode::CAST_HYBRID) {
        AscendC::Reg::Cast<dstType, float, castTraitF32ToH8Hybrid>(vregY, vregQuantRes, preg2);
    } else if constexpr (IsSameType<dstType, hifloat8_t>::value &&
                         roundMode == AscendC::RoundMode::CAST_ROUND) {
        AscendC::Reg::Cast<dstType, float, castTraitF32ToH8Round>(vregY, vregQuantRes, preg2);
    }
    AscendC::Reg::DataCopy<dstType, AscendC::Reg::StoreDist::DIST_PACK4_B32>(yOutAddr, vregY,
                                                                                       preg2);
}
```

**要点**:
- 无显式模板参数、无 mask 形参（M0），用 preg2 predicate。
- gelu 与量化融合：Div 是量化步，outScale 为量化 scale。
- roundMode（CAST_HYBRID/CAST_ROUND）只影响 hifloat8 的 Cast，不影响 Div。

### 实例 15：round::RoundIntCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, And, CompareScalar, DataCopy, Duplicate, MaskAnd, MaskOr, MaskReg, Mul, Muls, Neg, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **Div 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: round 的最近邻余数分解：用 Div(vregDiv, vregReUse, vregPow, mask) 计算 x/pow，Mul(vregDiv, vregPow) 还原后 Sub 取余数，再按 CompareScalar 判断半整数边界做 round-half-up 修正。

（行 68-97）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vl));
    Reg::DataCopy(vregReUse, (__ubuf__ T*)(absAddr + loopIdx * vl));

    Reg::Div(vregDiv, vregReUse, vregPow, mask);
    Reg::Mul(vregMul, vregDiv, vregPow, mask);
    Reg::Sub(vregReUse, vregReUse, vregMul, mask);
    Reg::Muls(vregMul, vregReUse, ConstTwo, mask);

    // + 1
    Reg::CompareScalar<T, CMPMODE::EQ>(cmpMaskReg0, vregMul, power, mask);
    Reg::And(vregReUse, vregDiv, vregDupOne, mask);
    Reg::CompareScalar<T, CMPMODE::EQ>(cmpMaskReg1, vregReUse, ConstOne, mask);
    Reg::MaskAnd(cmpMaskReg0, cmpMaskReg0, cmpMaskReg1, mask);
    Reg::CompareScalar<T, CMPMODE::GT>(cmpMaskReg1, vregMul, power, mask);
    Reg::MaskOr(cmpMaskReg0, cmpMaskReg0, cmpMaskReg1, mask);
    Reg::Select(vregMul, vregDupOne, vregDupZero, cmpMaskReg0);
    Reg::Add(vregMul, vregDiv, vregMul, mask);

    Reg::CompareScalar<T, CMPMODE::LT>(cmpMaskReg0, vregInput, ConstZero, mask);
    Reg::Neg(vregReUse, vregDupOne, mask);
    Reg::Select(vregDiv, vregReUse, vregDupOne, cmpMaskReg0);
    Reg::Mul(vregMul, vregMul, vregDiv, mask);
    Reg::Mul(vregReUse, vregMul, vregPow, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vl), (Reg::RegTensor<T> &)vregReUse, mask);
}
```

**要点**:
- 无显式模板参数（T0），mask 为 MaskReg（M1）。
- Div 用于 divmod 分解而非数值量化：x - (x/pow)*pow 得到余数。
- 用 MaskAnd/MaskOr/Select 处理 round-half-even 的边界判断。

### Div 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | max/scale 与 x/scale 量化除法（无 mask，DivSpecificMode 指针） | __aicore__ |
| dynamic_block_quant | And, Cast, CastTrait, CompareScalar, CreateMask | amax/fp8Max 求 scale + x/scale 量化（全 mask + Interleave 打包） | __VEC_SCOPE__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | (max-min)/qRange、qRange/diff、min/scale 三步 0-ULP 高精度除法 | __VEC_SCOPE__ |
| tanh | Abs, Adds, And, Cast, CompareScalar | 1/(1+e^(2|x|)) 倒数用于 tanh 有理逼近 | __aicore__ |
| clipped_swiglu | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | sigmoid = x/(1+e^(-αx)) 门控除法（clamped） | __VEC_SCOPE__ |
| swiglu_mx_quant | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | clamped sigmoid = x/(1+e^(-αx)) 门控除法（axis_last 尾块 mask） | __VEC_SCOPE__ |
| pool_3d_common | AddrReg, Arange, CreateAddrReg, CreateMask, DataCopy | 索引除法 i/outhw、i%outhw/outh、i/outw 分解池窗口坐标 | __aicore__ |
| grouped_dynamic_block_quant | And, Cast, CompareScalar, CreateMask | amax/fp8Max 求 scale + x/scale 量化（block 量化，强转前缀） | __VEC_SCOPE__ |
| sinh | Abs, Add, Adds, CompareScalar, DataCopy | 0.25/e^(|x|-ln2) 倒数用于 sinh exp 分支（&divMode） | __aicore__ |
| fake_quant_affine_cachemask | Adds, Cast, DataCopy, DivSpecificMode | 1/scale 求倒数（invSc）用于 affine 量化（BRC 广播） | __VEC_SCOPE__ |
| logsigmoid_grad | Abs, Adds, Cast, Compare | select/(1+e^-|x|) sigmoid 梯度除法 | __aicore__ |
| dynamic_block_quant | And, Cast, CompareScalar, CreateMask, DataCopy | 1/minScale + amax/fp8Max + x/scale 三步量化除法（small block） | __VEC_SCOPE__ |
| swish_grad | Adds, Cast, DataCopy, Duplicate | 1/(1+e^-x) 倒数用于 swish 反向 | __aicore__ |
| gelu_quant | Abs, Cast, CreateMask, DataCopy | x/outScale 量化除法（gelu+quant 融合，无 mask） | __VEC_SCOPE__ |
| round | Add, And, CompareScalar, DataCopy | x/pow 除法用于 round-to-nearest 余数分解 | __aicore__ |