# Muls

**页面ID:** atlasascendc_api_07_0383  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0383.html

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

矢量内每个元素与标量求积，计算公式如下，其中VL_T表示矢量计算单元一个迭代能够处理的元素个数。VL_T的取值参考RegTensor。

![](images/atlasascendc_api_07_0383_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, typename U, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void Muls(S& dstReg, S& srcReg, U scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 矢量目的操作数和源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int16_t/uint16_t/half/int32_t/uint32_t/float/complex32/int64_t/uint64_t/complex64 |
| S | 标量源操作数的数据类型 Atlas 350 加速卡，支持的数据类型为：int16_t/uint16_t/half/int32_t/uint32_t/float/complex32/int64_t/uint64_t/complex64 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dstReg中置零。- MERGING，暂不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MulsVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, T scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Muls(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Muls 实例

### 实例 1：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Muls 调用次数**: 4
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义（待补充）**: 在 BF16→FP32 类型转换后用 Muls 将最大绝对值乘以 inv_dtype_max（数据类型最大值的倒数），归一化得到 MX 量化的缩放因子 S_fp32。

（行 565-589）

```cpp
for (uint16_t j = 0; j <= static_cast<uint16_t>(blockCountLoop); j++) {
    Reg::LoadAlign(xRegTensor0, xAddr + j * dataLen + i * vfNum32);
    Reg::LoadAlign(xRegTensor1,
                   xAddr + (static_cast<uint16_t>(blockCount) - j - 1) * dataLen + i * vfNum32);
    Reg::And(expMaxRegTensor0, (Reg::RegTensor<uint16_t>&)xRegTensor0, absMaskBF16Reg, p0);
    Reg::And(expMaxRegTensor1, (Reg::RegTensor<uint16_t>&)xRegTensor1, absMaskBF16Reg, p0);
    Reg::Max(expMaxRegTensor, expMaxRegTensor0, expMaxRegTensor1, p0);
    Reg::Max(expMaxreShareExpFP16YOneRegTensor, expMaxRegTensor, expMaxreShareExpFP16YOneRegTensor, p0);
}
// 2. BF16→FP32
Reg::Interleave(expMaxreShareExpFP16YOneRegTensor, fullZeroReg, expMaxreShareExpFP16YOneRegTensor,
                fullZeroReg);
Reg::Cast<float, T, castTraitHalf2Float>((Reg::RegTensor<float>&)expMaxAndAddOneFP32RegTensor,
                                         (Reg::RegTensor<T>&)expMaxreShareExpFP16YOneRegTensor,
                                         preMaskScale);
// 3. Inf/Zero校验
Reg::CompareScalar<uint32_t, CMPMODE::LT>(infMask, expMaxAndAddOneFP32RegTensor, MAX_EXP_FOR_FP32,
                                          preMaskScale);
Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, expMaxAndAddOneFP32RegTensor, zeroRegTensor32, preMaskScale);
// 4. S_fp32 = Amax / Amax(DType)
Reg::Muls((Reg::RegTensor<float>&)expMaxAndAddOneFP32RegTensor,
          (Reg::RegTensor<float>&)expMaxAndAddOneFP32RegTensor, inv_dtype_max, preMaskScale);
// 5. 提取 Exp 和 Man
Reg::ShiftRights(expAndreShareExpFP32RegTensor, expMaxAndAddOneFP32RegTensor, SHR_NUM_FOR_FP32,
                 preMaskScale);
```

**要点**: ① dst 与 src 同寄存器（expMaxAndAddOneFP32RegTensor），原地相乘节省寄存器；② 标量 inv_dtype_max 为预计算倒数，避免运行时 Div 提升性能；③ 第 4 参数 preMaskScale 为 MaskReg，控制有效元素参与运算。

### 实例 2：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, HighLowPart, Interleave, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Muls 调用次数**: 4
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义（待补充）**: 在 MX 量化中先用 Maxs 对 FP32 最大值做下界兜底，再用 Muls 乘 inv_dtype_max 归一化缩放因子，随后 ShiftRights 提取 Exp 指数位。

（行 554-579）

```cpp
for (uint16_t j = 1; j < static_cast<uint16_t>(blockCount); j++) {
    this->template LoadData<RoundMode::CAST_TRUNC, roundMode>(xAddr, j * dataLen + i * vfNum32, x, p0);
    Reg::And((Reg::RegTensor<uint16_t>&)expScaleMxYZeroRegTensor, (Reg::RegTensor<uint16_t>&)x, absMaskBF16,
             p0);
    Reg::Max(expMaxreShareExpFP16YOneRegTensor,
             (Reg::RegTensor<uint16_t>&)expMaxreShareExpFP16YOneRegTensor,
             (Reg::RegTensor<uint16_t>&)expScaleMxYZeroRegTensor, p0);
}
Reg::Interleave(expMaxreShareExpFP16YOneRegTensor, fullZero, expMaxreShareExpFP16YOneRegTensor, fullZero);
Reg::Cast<float, T, castTraitHalf2Float>((Reg::RegTensor<float>&)expMaxAndAddOneFP32RegTensor,
                                         (Reg::RegTensor<T>&)expMaxreShareExpFP16YOneRegTensor,
                                         preMaskScale);
// 校验
Reg::CompareScalar<uint32_t, CMPMODE::LT>(infMask, expMaxAndAddOneFP32RegTensor, FP32_MX_MAX_EXP,
                                          preMaskScale);
Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, expMaxAndAddOneFP32RegTensor, zeroRegTensor32, preMaskScale);
Reg::Maxs((Reg::RegTensor<float>&)expMaxAndAddOneFP32RegTensor,
          (Reg::RegTensor<float>&)expMaxAndAddOneFP32RegTensor, this->maxLowBound_, preMaskScale);
Reg::Muls((Reg::RegTensor<float>&)expMaxAndAddOneFP32RegTensor,
          (Reg::RegTensor<float>&)expMaxAndAddOneFP32RegTensor, inv_dtype_max, preMaskScale);
Reg::ShiftRights(expAndreShareExpFP32RegTensor, expMaxAndAddOneFP32RegTensor, FP32_SHR_NUM,
                 preMaskScale);                                                                // Exp
Reg::And(manAndmxScaleFP32RegTensor, expMaxAndAddOneFP32RegTensor, manMaskFP32, preMaskScale); // Man
// 条件
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, expAndreShareExpFP32RegTensor, FP32_NUMBER_ZERO,
                                          preMaskScale);
```

**要点**: ① Maxs 兜底后再 Muls，避免极小值导致数值异常；② Muls→ShiftRights 链式提取浮点指数位；③ 与实例 1 同模式但增加下界保护，体现健壮性写法。

### 实例 3：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Muls 调用次数**: 6
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在 per-tensor 动态量化中用 Muls 计算 scale = ReduceMax × maxValue（或 (max-min) × offsetDivValue），并用 Muls 乘 NEGATIVE_ONE 得到负的 max/scale 用于零点反推。

**片段 1** (行 333-349):

```cpp
for (uint16_t j = 0; j < vfLoop; j++) {
    preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg1, xAddr + multiRow * rowCount + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, smoothAddr + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg0);
    AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg0);
    AscendC::Reg::Abs(vreg6, vreg3, preg0);
    AscendC::Reg::Max(vreg7, vreg6, vreg7, preg1);
}
AscendC::Reg::ReduceMax(vreg8, vreg7, preg1);
AscendC::Reg::Muls(vreg9, vreg8, maxValue, preg1);
AscendC::Reg::Duplicate(vreg10, vreg9, preg1);
AscendC::Reg::DataCopyUnAlign<float, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
    scaleAddr, vreg9, ureg0, 1);
```

**片段 2** (行 372-395):

```cpp
AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg4);
AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
    vreg2, smoothAddr + (vfLoop - 1) * VL);
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
AscendC::Reg::DataCopyUnAlign<float, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
    offsetAddr, vregOffset, ureg1, 1);
```

**要点**: ① 四参形式 Muls(dst, src, scalar, mask)，标量为运行时变量（maxValue/offsetDivValue/NEGATIVE_ONE）；② Muls 结果常配合 Duplicate 广播成整向量 scale；③ 同一算子内 Muls 既算正 scale 又算负 offset，体现标量乘多用途组合。

### 实例 4：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Muls 调用次数**: 3
- **参数模式**: `T1_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 在 per-channel 伪量化中用 Muls 乘 -1.0f 翻转零点符号，配合 Adds 拼出 (qBound - nudged_zp) 再乘 scaleSafe 得到 nudged 边界值。

（行 399-435）

```cpp
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

// 2.5 nudged_zp = floor(clip(zp_from_min, qMin, qMax) + 0.5)
AscendC::Reg::Maxs<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(vregZpClipped, vregZpFromMin, qMin,
                                                                       mask);
AscendC::Reg::Mins<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(vregZpClipped, vregZpClipped, qMax,
                                                                       mask);
AscendC::Reg::Adds<float>(vregZpClipped, vregZpClipped, 0.5f, mask);
AscendC::Reg::Cast<int32_t, float, kCastFp32ToInt32Floor>(vregZpInt, vregZpClipped, mask);
AscendC::Reg::Cast<float, int32_t, kCastInt32ToFp32>(vregNudgedZp, vregZpInt, mask);

// 2.6 nudged_min = (qMin - nudged_zp) * scaleSafe
//     nudged_max = (qMax - nudged_zp) * scaleSafe
AscendC::Reg::Muls<float>(vregNudgedMin, vregNudgedZp, -1.0f, mask);
AscendC::Reg::Adds<float>(vregNudgedMin, vregNudgedMin, qMin, mask);
AscendC::Reg::Mul<float>(vregNudgedMin, vregNudgedMin, vregScaleSafe, mask);

AscendC::Reg::Muls<float>(vregNudgedMax, vregNudgedZp, -1.0f, mask);
AscendC::Reg::Adds<float>(vregNudgedMax, vregNudgedMax, qMax, mask);
AscendC::Reg::Mul<float>(vregNudgedMax, vregNudgedMax, vregScaleSafe, mask);
```

**要点**: ① 模板显式指定 <float>（T1，1 个模板参数）；② 用 Muls×(-1) 实现取负（替代 Neg），便于统一标量乘流水线；③ mask 来自 Compares 的 scale==0 判断，对异常 lane 做屏蔽。

### 实例 5：tanh::TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, And, Cast, CompareScalar, DataCopy, Div, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Or, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Muls 调用次数**: 12
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: 用 Muls 乘预定义常数系数（0.015、2、-2 等）实现 tanh 的多项式逼近分支与 exp 分支中的各步标量乘。

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

**片段 2** (行 119-153):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
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
    Reg::Adds(vregInputMid, vregInputMid, FP32_ONE, mask);
    Reg::CompareScalar<float, CMPMODE::GE>(satMaskReg, vregInputAbs, FP32_SAT_BOUND, mask);
    Reg::Select(vregInputMid, vregOne, vregInputMid, satMaskReg);

    Reg::And(vregSign, vregSignMask, (Reg::RegTensor<uint32_t, Reg::RegTraitNumOne>&)vregInput, mask);
    Reg::Or((Reg::RegTensor<uint32_t, Reg::RegTraitNumOne>&)vregInputMid,
        (Reg::RegTensor<uint32_t, Reg::RegTraitNumOne>&)vregInputMid, vregSign, mask);

    Reg::CompareScalar<float, CMPMODE::GE>(cmpMaskReg, vregInputAbs, FP32_ZERO_6, mask);
    Reg::Select(vregOutput, vregInputMid, vregOutput, cmpMaskReg);

    Reg::Cast<T, float, castTrait1>(vregOutput16, vregOutput, mask);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_PACK_B32>((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput16, mask);
}
```

**要点**: ① Muls 大量用于乘多项式系数和常数，是激活函数逼近的典型用法；② 同一 kernel 内 fp32 与 bf16 两条路径对称使用 Muls；③ mask 由 UpdateMask 生成，处理尾部对齐元素。

### 实例 6：cdist::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, CreateMask, Duplicate, Exp, ExpSpecificMode, LoadAlign, Log, LogSpecificMode, MaskMergeMode, MaskPattern, MaskReg, ReduceSum, RegTensor, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore, UpdateMask
- **Muls 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 在 cdist 的 Lp 距离计算中用 Muls 将 log(|x1-x2|) 乘以阶数 p（或 1/p），再 Exp 还原为 |x1-x2|^p（或开 p 次根），实现可变阶 Lp 范数。

（行 619-646）

```cpp
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
```

**要点**: ① 标量为运行时强转的 (float)p_ / (float)(1/p_)，支持任意阶 Lp 距离；② Muls+Log+Exp 组合等价于幂运算 pow(x, p)；③ maskAll/maskOne 区分满块与单元素尾处理。

### 实例 7：avg_pool::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Arange, Cast, Copy, CreateMask, DataCopyGather, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, MaskMergeMode, MaskPattern, MaskReg, Pack, ReduceSum, RegTensor, UnPack, UnalignReg, UpdateMask
- **Muls 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在 avg_pool 中用 Muls 完成两处标量乘：把 Arange 生成的索引乘 channelNum 构造 gather 偏移；把 ReduceSum 结果乘 mulsFactor_（1/N）得到均值。

**片段 1** (行 605-655):

```cpp
{
    Reg::RegTensor<float> res;
    Reg::RegTensor<T> in;
    Reg::RegTensor<float> inFp32;
    Reg::RegTensor<uint16_t> v0;
    AscendC::Reg::UnalignReg u0;
    Reg::Arange((Reg::RegTensor<int16_t>&)v0, 0);
    uint32_t tailSreg = tailLoop;
    uint32_t mainSreg = repeatElm;
    uint32_t tailLen = tailLoop;
    uint32_t mainLen = repeatElm;
    Reg::MaskReg pTail = Reg::UpdateMask<T>(tailSreg);
    Reg::MaskReg pMain = Reg::UpdateMask<T>(mainSreg);
    Reg::MaskReg maskFp32 = Reg::UpdateMask<float>(mainLen);
    Reg::MaskReg tailMaskFp32 = Reg::UpdateMask<float>(tailLen);
    Reg::Muls(v0, v0, channelNum, pMain);
    for (uint16_t i = 0; i < loopNum; i++) {
        auto srcAddr = xLocalAddr + i;
        auto dstAddr = dstLocalAddr + i;
        auto sumAddr = sumLocalAddr + i;
        Reg::Duplicate(res, 0);
        for (uint16_t j = 0; j < repeatTimes; j++) {
            Reg::DataCopyGather(in, srcAddr + j * channelStride, v0, pMain);
            Reg::UnPack((Reg::RegTensor<uint32_t>&)in, (Reg::RegTensor<uint16_t>&)in);
            Reg::Cast<float, T, castTraitT2Fp32>(inFp32, in, maskFp32);
            Reg::Add(res, inFp32, res, maskFp32);
        }
        Reg::RegTensor<float> tmp;
        Reg::DataCopyGather(in, srcAddr + repeatTimes * channelStride, v0, pTail);
        Reg::UnPack((Reg::RegTensor<uint32_t>&)in, (Reg::RegTensor<uint16_t>&)in);
        Reg::Cast<float, T, castTraitT2Fp32>(inFp32, in, tailMaskFp32);
        Reg::Add(tmp, inFp32, res, tailMaskFp32);
        Reg::Copy<float, Reg::MaskMergeMode::MERGING>(res, tmp, tailMaskFp32);
        Reg::MaskReg maskAll = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
        Reg::ReduceSum(res, res, maskAll);
        if constexpr (MERGE) {
            // merge cur result with last result
            MergeSumRes<float>(res, sumAddr, 0);
        }
        if constexpr (!IS_LAST_LOOP) {
            Reg::DataCopyUnAlign(sumAddr, res, u0, 1);
            Reg::DataCopyUnAlignPost(sumAddr, u0, 0);
        } else {
            Reg::Muls(res, res, mulsFactor_, maskAll);
            Reg::Cast<T, float, castTraitFp322T>(in, res, maskAll);
            Reg::Pack((Reg::RegTensor<uint16_t>&)in, (Reg::RegTensor<uint32_t>&)in);
            Reg::DataCopyUnAlign(dstAddr, in, u0, 1);
            Reg::DataCopyUnAlignPost(dstAddr, u0, 0);
        }
    }
}
```

**片段 2** (行 644-653):

```cpp
if constexpr (!IS_LAST_LOOP) {
    Reg::DataCopyUnAlign(sumAddr, res, u0, 1);
    Reg::DataCopyUnAlignPost(sumAddr, u0, 0);
} else {
    Reg::Muls(res, res, mulsFactor_, maskAll);
    Reg::Cast<T, float, castTraitFp322T>(in, res, maskAll);
    Reg::Pack((Reg::RegTensor<uint16_t>&)in, (Reg::RegTensor<uint32_t>&)in);
    Reg::DataCopyUnAlign(dstAddr, in, u0, 1);
    Reg::DataCopyUnAlignPost(dstAddr, u0, 0);
}
```

**要点**: ① Muls 既用于地址索引缩放（v0×channelNum），也用于数值归一化（sum×1/N）；② mulsFactor_ 是预计算的 1/KernelSize 标量，避免运行时 Div；③ pMain/maskAll 区分主循环掩码与全有效掩码。

### 实例 8：max_pool_with_argmax::MaxPoolWithArgMaxGatherImpl

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Cast, Compare, CreateMask, DataCopyGather, DataCopyScatter, Duplicate, MaskNot, MaskOr, MaskPattern, MaskReg, MaskUnPack, Pack, RegTensor, Select, UpdateMask
- **Muls 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在 max_pool_with_argmax 中用 Muls 把 argmax 的 H/W 坐标乘以维度步长（wInput、cInput），配合 Add 拼接成扁平一维索引 argmaxRes = ((H*wInput+W)*cInput+cStart)。

（行 130-152）

```cpp
if constexpr (IS_PAD == 1) {
    // 修正argmax
    Reg::Adds(argmaxHRes, argmaxHRes, -padH, computeT2);
    Reg::Adds(argmaxWRes, argmaxWRes, -padW, computeT2);

    Reg::MaskReg hMask;
    Reg::MaskReg wMask;
    Reg::RegTensor<T2> argmaxZero;
    Reg::Duplicate(argmaxZero, 0);

    Reg::Compare<T2, CMPMODE::GE>(hMask, argmaxHRes, argmaxZero, computeT2);
    Reg::Select(argmaxHRes, argmaxHRes, argmaxZero, hMask);
    Reg::Compare<T2, CMPMODE::GE>(wMask, argmaxWRes, argmaxZero, computeT2);
    Reg::Select(argmaxWRes, argmaxWRes, argmaxZero, wMask);
}

Reg::RegTensor<T2> argmaxRes;
Reg::Muls(argmaxRes, argmaxHRes, wInput, computeT2);
Reg::Add(argmaxRes, argmaxRes, argmaxWRes, computeT2);
Reg::Muls(argmaxRes, argmaxRes, cInput, computeT2);
Reg::Add(argmaxRes, argmaxRes, argmaxCStart, computeT2);
// 最大值从未更新过对应索引修正为-1
Reg::Select(argmaxRes, argmaxRes, neg1Res, flagMask);
```

**要点**: ① Muls 用于多维索引展平（坐标×步长），是 gather/scatter 寻址的常见组合；② 两步 Muls+Add 串联完成 HWC→1D 索引换算；③ computeT2 为计算掩码，对 padding 修正后的负坐标先经 Select 清零。

### 实例 9：fake_quant_affine_cachemask::AscendC::LocalTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, DataCopy, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskReg, Maxs, Mins, Mul, MulDstAdd, RegTensor, StoreDist, Sub, UpdateMask
- **Muls 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 在 affine 伪量化的 cachemask 分支中用 Muls 乘 -1.0f 对量化值 vregQ 取负，配合 Adds 拼出 qMaxPlus1 - q 的上界 clamp 计算。

（行 380-397）

```cpp
if constexpr (HAS_ZP == 1) {
    Reg::MulDstAdd<float>(vregTmp, vregInvSc, vregZp, mask);
} else {
    Reg::Mul<float>(vregTmp, vregTmp, vregInvSc, mask);
}
Reg::Cast<int32_t, float, layoutZSatSMrgZRndR>(vregInt32, vregTmp, mask);
Reg::Cast<float, int32_t, layoutZMrgZRndR>(vregQ, vregInt32, mask);

// 用 in-place 形式（dst == src1）避免 cross-register Adds 在某些 lane
// 留下未写状态：先把 vregQ 复制到 vregM1，再 in-place 算
Reg::Adds<float, float>(vregM1, vregQ, 0.0f, mask); // vregM1 = vregQ
Reg::Adds<float, float>(vregM1, vregM1, -qMinMinus1F, mask);
Reg::Mins<float, float>(vregM1, vregM1, 1.0f, mask);
Reg::Maxs<float, float>(vregM1, vregM1, 0.0f, mask);
Reg::Muls<float, float>(vregM2, vregQ, -1.0f, mask); // vregM2 = -vregQ
Reg::Adds<float, float>(vregM2, vregM2, qMaxPlus1F, mask);
Reg::Mins<float, float>(vregM2, vregM2, 1.0f, mask);
Reg::Maxs<float, float>(vregM2, vregM2, 0.0f, mask);
```

**要点**: ① 模板显式 <float, float>（T2，双模板参数）；② Muls 取负后接 Mins/Maxs 做 [0,1] 裁剪；③ dst(vregM2) 与 src(vregQ) 不同寄存器，非原地写，避免 cross-register lane 未写问题。

### 实例 10：arg_max_with_value::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, HighLowPart, MaskAnd, MaskMergeMode, MaskNot, MaskOr, MaskPattern, MaskReg, Mul, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Muls 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: 在 arg_max 中用 Muls 将 Arange 生成的连续索引 (0..63) 乘以步长 dimNextA，生成按维度步进的扁平索引序列 (0, dimNextA, 2*dimNextA, ...) 用于后续比较定位。

（行 684-699）

```cpp
AscendC::Reg::RegTensor<uint32_t> indexResult32;
AscendC::Reg::UnalignReg uValue, uIndex, uSrc;
AscendC::Reg::RegTensor<T5> level0, level1, indexResult, helpIndex;

AscendC::Reg::MaskReg helpV0Mask, helpV1Mask, cmpMask;
AscendC::Reg::MaskReg oneMask = AscendC::Reg::CreateMask<T5, AscendC::Reg::MaskPattern::VL1>();
AscendC::Reg::MaskReg twoMask = AscendC::Reg::CreateMask<T5, AscendC::Reg::MaskPattern::VL2>();
AscendC::Reg::MaskReg allMask32 = AscendC::Reg::CreateMask<T5, AscendC::Reg::MaskPattern::ALL>();
AscendC::Reg::MaskReg newMask = AscendC::Reg::UpdateMask<T5>(tailSize);
AscendC::Reg::MaskReg addMask = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::VL1>();
AscendC::Reg::MaskReg b8Mask = AscendC::Reg::CreateMask<uint8_t, AscendC::Reg::MaskPattern::ALL>();

Duplicate(helpIndex, VALUE_ONE, allMask32);
Duplicate<T5, AscendC::Reg::MaskMergeMode::MERGING, T5>(helpIndex, VL, oneMask);
Arange(initIndex, 0);                            // (0, 1, 2, ... , 63)
Muls(initIndex, initIndex, dimNextA, allMask32); // (0, 1 *dimNextA, 2*dimNextA, ... , 63*dimNextA)
```

**要点**: ① Muls 用于索引缩放，Arange→Muls 是生成等差索引序列的常见组合；② 标量 dimNextA 为维度步长（运行时变量）；③ mask 用 allMask32 全有效，对整向量索引做缩放。

### 实例 11：add_rms_norm_dynamic_mx_quant::ComputeFP4FromHalf

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Compare, CompareScalar, CreateMask, Duplicate, MaskAnd, MaskOr, MaskPattern, MaskReg, Maxs, Mul, RegTensor, Select, ShiftLefts, ShiftRights, Truncate
- **Muls 调用次数**: 6
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在 fused RMSNorm+MX 量化的 FP4 编码中用 Muls 乘 FOUR/ONE_FOURTH 围绕 Truncate 做精度控制，并对指数位乘 NEG_ONE 实现指数翻转。

（行 589-611）

```cpp
if constexpr (IsSame<T_Y, fp4x2_e1m2_t>::value) {
    AscendC::Reg::Muls(Reg, Reg, FOUR, pregAll32);
    AscendC::Reg::CompareScalar<float, CMPMODE::LT>(specialMask, Reg, 0, pregAll32);
    AscendC::Reg::Truncate<float, roundMode>(Reg, Reg, pregAll32);
    AscendC::Reg::Muls(Reg, Reg, ONE_FOURTH, pregAll32);
} else {
    AscendC::Reg::Duplicate(maxExpFP32, MAX_EXP_FOR_FP32);
    AscendC::Reg::And(exp0FP32, (AscendC::Reg::RegTensor<int32_t>&)Reg, maxExpFP32, pregAll32);
    AscendC::Reg::ShiftRights(exp0FP32, exp0FP32, SHR_NUM_FOR_FP32, pregAll32);
    AscendC::Reg::Adds(exp0FP32, exp0FP32, FP32_BIAS_NEG, pregAll32);
    AscendC::Reg::Maxs(exp0FP32, exp0FP32, 0, pregAll32);
    AscendC::Reg::Adds(exp0FP32, exp0FP32, NEG_ONE, pregAll32);
    AscendC::Reg::Muls(exp1FP32, exp0FP32, NEG_ONE, pregAll32);
    AscendC::Reg::Adds(exp1FP32, exp1FP32, FP32_BIAS, pregAll32);
    AscendC::Reg::ShiftLefts(exp1FP32, exp1FP32, SHR_NUM_FOR_FP32, pregAll32);
    AscendC::Reg::Mul(Reg, Reg, (AscendC::Reg::RegTensor<float>&)exp1FP32, pregAll32);
    AscendC::Reg::Adds(exp0FP32, exp0FP32, FP32_BIAS, pregAll32);
    AscendC::Reg::ShiftLefts(exp0FP32, exp0FP32, SHR_NUM_FOR_FP32, pregAll32);
    AscendC::Reg::CompareScalar<float, CMPMODE::LT>(specialMask, Reg, 0, pregAll32);
    AscendC::Reg::Truncate<float, roundMode>(Reg, Reg, pregAll32);
    AscendC::Reg::Mul(Reg, Reg, (AscendC::Reg::RegTensor<float>&)exp0FP32, pregAll32);
}
```

**要点**: ① Muls×4→Truncate→Muls×(1/4) 是定点化精度截断的常见套路；② 标量 FOUR/ONE_FOURTH/NEG_ONE 均为预定义常数；③ 与 ShiftLefts/ShiftRights 配合重组浮点指数位。

### 实例 12：is_close::NanEqualCompare

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, Compare, DataCopy, Duplicate, FusedAbsSub, HighLowPart, MaskAnd, MaskOr, MaskPack, MaskReg, Pack, RegTensor, RegTraitNumOne, Select, UpdateMask
- **Muls 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: 在 is_close 中用 Muls 计算 |x2|×rtol，再 Adds atol 得到容差阈值 atol+rtol×|x2|，用于与 |x1-x2| 比较判定近似相等。

**片段 1** (行 87-105):

```cpp

// 计算结果1——equalCmpMask
Reg::Compare<float, CMPMODE::EQ>(equalCmpMask, x1Reg, x2Reg, mask);

// x1x2和自己对比，输出False的位置，为Nan的位置
Reg::Compare<float, CMPMODE::NE>(tmpMask1, x1Reg, x1Reg, mask);
Reg::Compare<float, CMPMODE::NE>(tmpMask2, x2Reg, x2Reg, mask);
// MaskAnd取x1x2都是Nan的位置---------------
Reg::MaskAnd(bothNanMask, tmpMask1, tmpMask2, mask);
// MaskOr取计算结果1、4都为True的位置，结果存储到tmpMask2
Reg::MaskOr(tmpMask2, bothNanMask, equalCmpMask, mask);

// 计算结果3
Reg::FusedAbsSub(absSubReg, x1Reg, x2Reg, mask); // 中间结果
Reg::Abs(x2AbsReg, x2Reg, mask);
Reg::Muls(rtolTmpReg, x2AbsReg, rtol, mask);
Reg::Adds(rtolReg, rtolTmpReg, atol, mask);
Reg::Compare<float, CMPMODE::LE>(funcCmpMask, absSubReg, rtolReg, mask);
```

**片段 2** (行 129-163):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    Reg::Duplicate(regTensorOne, (uint8_t)1.0f, mask);
    Reg::Duplicate(regTensorZero, (uint8_t)0.0f, mask);
    Reg::DataCopy(x1Reg, (__ubuf__ float*)(src1Addr + loopIdx * vlSize));
    Reg::DataCopy(x2Reg, (__ubuf__ float*)(src2Addr + loopIdx * vlSize));
    // 计算结果1——equalCmpMask
    Reg::Compare<float, CMPMODE::EQ>(equalCmpMask, x1Reg, x2Reg, mask);

    // 计算结果3
    Reg::FusedAbsSub(absSubReg, x1Reg, x2Reg, mask); // 中间结果
    Reg::Abs(x2AbsReg, x2Reg, mask);
    Reg::Muls(rtolTmpReg, x2AbsReg, rtol, mask);
    Reg::Adds(rtolReg, rtolTmpReg, atol, mask);
    Reg::Compare<float, CMPMODE::LE>(funcCmpMask, absSubReg, rtolReg, mask);
    // 计算结果4
    Reg::Duplicate(regTensorInfinity, (float)INF_CONST, mask);
    Reg::Compare<float, CMPMODE::LT>(finiteMask, x2AbsReg, regTensorInfinity, mask);

    // 其他处理
    // 符合公式且有限
    Reg::MaskAnd(tmpMask1, funcCmpMask, finiteMask, mask);
    // 符合上一条或者完全一致
    Reg::MaskOr(resultMask, equalCmpMask, tmpMask1, mask);

    Reg::Select(resultReg, regTensorOne, regTensorZero, resultMask);
    Reg::Pack(reguint16, (AscendC::Reg::RegTensor<uint32_t>&)resultReg);
    Reg::Pack(reguint8, reguint16);
    AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(tmpMask1, mask);
    AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(mask, tmpMask1);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ uint8_t*)(dstAddr + loopIdx * vlSize), reguint8, mask);
}
```

**要点**: ① Muls 实现 numpy.isclose 公式的 rtol×|x2| 项；② 标量 rtol/atol 为运行时传入参数；③ 标量版与循环版两条片段对称使用同一 Muls 模式。

### 实例 13：dynamic_quant::ComputeMaxRowScaleVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Cast, CreateMask, DataCopy, Duplicate, LoadDist, MaskPattern, MaskReg, Max, Min, Mul, ReduceMax, ReduceMin, RegTensor, StoreDist, UpdateMask
- **Muls 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义（待补充）**: 在对称 per-tensor 动态量化中用 Muls 将 Abs(x) 乘以 1/maxValue（预计算倒数），把绝对值归一化到 [-1,1] 区间再求 ReduceMax 得到 scale。

**片段 1** (行 344-363):

```cpp
for (uint16_t j = 0; j < static_cast<uint16_t>(vfLoop - 1); j++) {
    preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg1, inLocalAddr + i * rowCount + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg0);
    if constexpr (hasSmooth) {
        AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
            vreg2, smoothLocalAddr + j * VL);
        AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg0);
        AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg0);
    }
    if constexpr (isSymmertrical == false) {
        AscendC::Reg::Max(vreg7_1, vreg3, vreg7_1, preg0);
        AscendC::Reg::Min(vreg7_2, vreg3, vreg7_2, preg0);
    } else {
        AscendC::Reg::Abs(vreg6_1, vreg3, preg0);
        AscendC::Reg::Muls(vreg6_1, vreg6_1, float(1.0) / maxValue, preg0);
        AscendC::Reg::Max(vreg7_1, vreg6_1, vreg7_1, preg0);
    }
}
```

**片段 2** (行 381-391):

```cpp
if constexpr (isSymmertrical == false) {
    AscendC::Reg::ReduceMax(vreg7_1, vreg3, preg0);
    AscendC::Reg::ReduceMin(vreg7_2, vreg3, preg0);
    AscendC::Reg::Max(vreg8_1, vreg8_1, vreg7_1, preg0);
    AscendC::Reg::Min(vreg8_2, vreg8_2, vreg7_2, preg0);
} else {
    AscendC::Reg::Abs(vreg6_1, vreg3, preg0);
    AscendC::Reg::Muls(vreg6_1, vreg6_1, float(1.0) / maxValue, preg0);
    AscendC::Reg::ReduceMax(vreg7_1, vreg6_1, preg0);
    AscendC::Reg::Max(vreg8_1, vreg8_1, vreg7_1, preg0);
}
```

**要点**: ① 标量为强转的 float(1.0)/maxValue，预计算倒数避免运行时 Div；② Muls 在 if constexpr 对称/非对称分支中分别使用；③ 与 Abs→Muls→ReduceMax 组合求归一化最大值。

### 实例 14：swish_grad::SwishGradCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, DataCopy, Div, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Neg, RegTensor, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **Muls 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: 在 swish 反向中用 Muls 将输入乘以 scale1 标量做缩放，作为后续 Neg→Exp→Div 求 sigmoid 导数链路的起点。

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

**要点**: ① Muls 在梯度计算入口对输入做标量缩放（scale1）；② 之后接 Neg/Exp/Div 构建 sigmoid 分母，体现 Muls 在激活梯度流水中的预处理作用；③ fp32 与 bf16 两条路径对称使用。

### 实例 15：gather_nd::FixIndicesVfCoreVf

- **来源类型**: `__simd_vf__`
- **共现 API**: Add, AddrReg, Adds, Compare, CreateAddrReg, CreateMask, DataCopy, DataCopyGather, Duplicate, MaskMergeMode, MaskOr, MaskPattern, MaskReg, RegTensor, RegTraitNumTwo, UpdateMask
- **Muls 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在 gather_nd 的索引修正中用 Muls 把当前维度索引 curIndicesReg 乘以该维步长 strideDimKSize 累加进 indicesResReg，最终再乘 aMergeAxisSize 折算到合并轴的扁平偏移。

（行 122-157）

```cpp
for (uint16_t k = 0; k < rank; k++) {
    AscendC::Reg::Adds(curIndex, indexStart, (indicesOffset + k), pregAll);

    if constexpr (std::is_same<T3, int32_t>::value && std::is_same<T2, int32_t>::value) {
        AscendC::Reg::DataCopyGather(curIndicesReg, indicesAddr, curIndex, pregT2);
    } else if constexpr (std::is_same<T3, int32_t>::value && std::is_same<T2, int64_t>::value) {
        AscendC::Reg::RegTensor<T2, AscendC::Reg::RegTraitNumTwo> curIndicesRegTwo;
        AscendC::Reg::DataCopyGather(curIndicesRegTwo, indicesAddr, curIndex, pregT2);
        curIndicesReg = (AscendC::Reg::RegTensor<T3>&)curIndicesRegTwo.reg[0];
    } else if constexpr (std::is_same<T3, int64_t>::value && std::is_same<T2, int64_t>::value) {
        AscendC::Reg::DataCopyGather(curIndicesReg, indicesAddr, curIndex, pregT2);
    }

    T3 maxGatherDimKSize = maxGatherShapeAddr[k];
    if constexpr (NIS) {
        AscendC::Reg::Compare<T3, CMPMODE::LT>(tmpMask, curIndicesReg, zeroConstReg, preg);
        AscendC::Reg::Adds(tmpReg, curIndicesReg, maxGatherDimKSize, tmpMask);
        Copy<T3, AscendC::Reg::MaskMergeMode::MERGING>(curIndicesReg, tmpReg, tmpMask);
    }

    AscendC::Reg::Compare<T3, CMPMODE::LT>(tmpMask, curIndicesReg, zeroConstReg, preg);
    AscendC::Reg::MaskOr(overstepMask, overstepMask, tmpMask, preg);

    AscendC::Reg::Duplicate(upLimitConstReg, T3(maxGatherDimKSize));
    AscendC::Reg::Compare<T3, CMPMODE::GE>(tmpMask, curIndicesReg, upLimitConstReg, preg);
    AscendC::Reg::MaskOr(overstepMask, overstepMask, tmpMask, preg);

    T3 strideDimKSize = strideShapeAddr[k];
    AscendC::Reg::Muls(curIndicesReg, curIndicesReg, strideDimKSize, preg);
    AscendC::Reg::Add(indicesResReg, indicesResReg, curIndicesReg, preg);
}

AscendC::Reg::Muls(indicesResReg, indicesResReg, aMergeAxisSize, preg);
AscendC::Reg::Duplicate(tmpReg, T3(-1), overstepMask);
Copy<T3, AscendC::Reg::MaskMergeMode::MERGING>(indicesResReg, tmpReg, overstepMask);
```

**要点**: ① Muls 用于多维索引步长累加（索引×步长→Add 累加），是 gather 寻址核心；② 标量 strideDimKSize/aMergeAxisSize 为运行时维度步长；③ 越界索引通过 overstepMask + Select 置 -1。

### Muls 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 标量倒数归一化（dst==src 原地乘 inv_dtype_max，配 mask） | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 标量倒数归一化 + 下界兜底（Maxs→Muls→ShiftRights） | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | scale 计算 + 取负（Muls 算 scale 与 -scale，配 Duplicate 广播） | __aicore__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | 取负 + 边界拼接（Muls×(-1.0f)→Adds→Mul，mask 屏蔽异常 lane） | __VEC_SCOPE__ |
| tanh | Abs, Adds, And, Cast, CompareScalar | 多项式系数乘法 + 常数缩放（激活函数逼近，fp32/bf16 双路径） | __aicore__ |
| cdist | Abs, Add, CreateMask, Duplicate, Exp | 幂运算组合（Log→Muls×p→Exp，可变阶 Lp 范数） | __VEC_SCOPE__ |
| avg_pool | Add, Arange, Cast, Copy, CreateMask | 索引缩放 + 均值归一化（Arange→Muls 与 ReduceSum→Muls×1/N） | __VEC_SCOPE__ |
| max_pool_with_argmax | Add, Adds, Cast, Compare, CreateMask | 多维索引展平（Muls×步长→Add 拼接，配 padding 修正） | __aicore__ |
| fake_quant_affine_cachemask | Adds, Cast, DataCopy, Div, DivSpecificMode | 取负 + 上下界裁剪（Muls×(-1.0f)→Adds→Mins/Maxs） | __VEC_SCOPE__ |
| arg_max_with_value | Adds, Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost | 等差索引生成（Arange→Muls×步长，全掩码） | __VEC_SCOPE__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Compare, CompareScalar, CreateMask | 精度截断套件 + 指数翻转（Muls×4→Truncate→Muls×1/4，Muls×(-1)） | __aicore__ |
| is_close | Abs, Adds, Compare, DataCopy, Duplicate | 容差阈值计算（Abs→Muls×rtol→Adds atol→Compare） | __aicore__ |
| dynamic_quant | Abs, Cast, CreateMask, DataCopy, Duplicate | 归一化求 max（Abs→Muls×(1/maxValue)→ReduceMax，对称量化分支） | __aicore__ |
| swish_grad | Adds, Cast, DataCopy, Div, Duplicate | 梯度入口缩放（Muls×scale1→Neg→Exp→Div 求 sigmoid 导数） | __aicore__ |
| gather_nd | Add, AddrReg, Adds, Compare, CreateAddrReg | 多维索引步长累加（Muls×步长→Add 累加→Muls×合并轴步长） | __simd_vf__ |
