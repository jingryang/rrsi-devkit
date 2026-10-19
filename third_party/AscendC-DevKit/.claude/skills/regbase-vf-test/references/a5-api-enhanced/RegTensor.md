# RegTensor

**页面ID:** atlasascendc_api_07_0314  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0314.html

---

#### 功能说明

Reg矢量计算基本单元，RegTensor位宽为VL（Vector Length），具体值可能因不同AI处理器型号而异。

#### 定义原型

```
template <typename T, const RegTrait& regTrait = RegTraitNumOne> struct RegTensor;
```

#### 函数说明

模板参数T，支持的数据类型(宽度)为b8/b16/b32/b64。

| 数据类型宽度 | 数据类型 |
| --- | --- |
| b8 | 支持的数据类型为：bool/int8_t/uint8_t/fp4x2_e2m1_t/fp4x2_e1m2_t/hifloat8_t/fp8_e5m2_t/fp8_e4m3fn_t/fp8_e8m0_t（ fp4x2_e2m1_t/fp4x2_e1m2_t这两个b4类型在Vector侧的内存排布需要为两个一组，表现为b8类型；int4b_t也使用b8类型表达；bool数据类型只支持数据搬运）。 |
| b16 | 支持的数据类型为：int16_t/uint16_t/half/bfloat16_t。 |
| b32 | 支持的数据类型为：int32_t/uint32_t/float/complex32。 |
| b64 | 支持的数据类型为：int64_t/uint64_t/complex64。 |

模板参数regTrait，表示该RegTensor类型内部包含的矢量Reg数量。regTrait为RegTraitNumOne时，该RegTensor类型中包含1个相应数据类型的矢量Reg，长度为VL。regTrait为RegTraitNumTwo时，该RegTensor类型中包含2个相应数据类型的矢量Reg，总长度为2 * VL，每个矢量Reg长度为VL。

| 模板参数regTrait | 支持的数据类型宽度 |
| --- | --- |
| RegTraitNumOne | Atlas 350 加速卡，支持的数据类型宽度为：b8/b16/b32/b64。 |
| RegTraitNumTwo | Atlas 350 加速卡，支持的数据类型宽度为：b64/complex32。 |

#### 支持的型号

Atlas 350 加速卡（VL=256B）

#### 约束说明

无

#### 调用示例

- 示例一

```
AscendC::Reg::RegTensor<uint32_t> reg;
AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<uint32_t>();
AscendC::Reg::LoadAlign(reg, src, 0);
AscendC::Reg::Adds(reg, reg, 1);
AscendC::Reg::StoreAlign(dst, reg, 0, mask);
```

- 示例二

```
// 针对B64,可以传入RegTraitNumTwo
template<typename T, const AscendC::Reg::RegTrait& Trait = AscendC::Reg::RegTraitNumOne>
__simd_vf__ inline void AddVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T,Trait> srcReg0;
    AscendC::Reg::RegTensor<T,Trait> srcReg1;
    AscendC::Reg::RegTensor<T,Trait> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T,Trait>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Add(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 RegTensor 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **RegTensor 调用次数**: 38
- **参数模式**: `T1_A0_M0_TYPEint32_t+uint32_t`（实参 0 个，类型: int32_t, uint32_t）
- **语义**: 在 FP8 动态量化（非尾轴优化）中声明 uint32_t/uint16_t/float/uint8_t 等多类型 RegTensor 作为尾数、指数、scale 的寄存器中间量，配合 Cast/Compare/Mul/ShiftRights 完成从 FP32 到 FP8 的 scale 求解与数据值换算。

**片段 1** (行 419-438):

```cpp
// 尾数位
Reg::RegTensor<uint32_t> manFP32RegTensor;
Reg::RegTensor<uint32_t> scaleBias;
Reg::RegTensor<uint32_t> extractExpRegTensor;
Reg::RegTensor<uint16_t> tmp16RegTensor;
Reg::MaskReg p0;
Reg::MaskReg p1;
Reg::MaskReg zeroMask;
Reg::MaskReg infMask;

Reg::RegTensor<uint16_t> exp;
Reg::RegTensor<uint16_t> expMax;
Reg::RegTensor<uint16_t> reversedShareExpRegTensor;
Reg::RegTensor<float> reversedShareExpRegTensorFP32Zero;
Reg::RegTensor<float> reversedShareExpRegTensorFP32One;
Reg::RegTensor<uint32_t> nan;
Reg::RegTensor<uint8_t> outZero;
Reg::RegTensor<float> yZero;
Reg::RegTensor<float> yOne;
Reg::RegTensor<U> yZeroFP8;
```

**片段 2** (行 499-513):

```cpp
// 求scale
Reg::Interleave(expMax, tmp16RegTensor, expMax, tmp16RegTensor);
Reg::Cast<float, T, castTraitZero>((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<T>&)expMax, mask);

Reg::Compare<uint32_t, CMPMODE::LT>(infMask, maxFP32RegTensor, absMaskFP32RegTensor, mask);
Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, maxFP32RegTensor, fp32ZeroRegTensor, mask);

Reg::Maxs((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<float>&)maxFP32RegTensor,
          this->maxLowBound_, mask);

Reg::Mul((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<float>&)maxFP32RegTensor,
         (Reg::RegTensor<float>&)invMaxRegTensor, mask);
Reg::Duplicate(invMaxRegTensor, FP8_DEFAULT_MAX_EXP);
// 右移获取指数位
Reg::ShiftRights(expFP32RegTensor, maxFP32RegTensor, FP32_SHR_NUM, mask);
```

**片段 3** (行 560-578):

```cpp
// 求data value
for (uint16_t i = 0; i <= static_cast<uint16_t>(regLoop - 1); i++) {
    this->template LoadData<RoundMode::UNKNOWN, roundMode, true>(xAddr, i * dataLenSingleLoop, x, pnumMask);
    if constexpr (IsSame<T, half>::value) {
        Reg::Cast<float, T, castTraitZero>(yZero, x, pnumMask);
        Reg::Cast<float, T, castTraitOne>(yOne, x, pnumMask);
        Reg::Mul(yZero, yZero, reversedShareExpRegTensorFP32Zero, mask);
        Reg::Mul(yOne, yOne, reversedShareExpRegTensorFP32One, mask);
    } else if constexpr (IsSame<T, bfloat16_t>::value) {
        Reg::Mul(xBF16RegTensor, x, (Reg::RegTensor<bfloat16_t>&)reversedShareExpRegTensor, pnumMask);
        Reg::Cast<float, bfloat16_t, castTraitZero>(yZero, xBF16RegTensor, mask);
        Reg::Cast<float, bfloat16_t, castTraitOne>(yOne, xBF16RegTensor, mask);
    }
    Reg::Cast<U, float, castTrait32to8>(yZeroFP8, yZero, mask);
    Reg::Cast<U, float, castTrait32to8>(yOneFP8, yOne, mask);
    // 寄存器复用
    Reg::Pack(tmp16RegTensor, (Reg::RegTensor<uint32_t>&)yZeroFP8);
    Reg::Pack(exp, (Reg::RegTensor<uint32_t>&)yOneFP8);
    Reg::Interleave(tmp16RegTensor, exp, tmp16RegTensor, exp);
```

**要点**: RegTensor 通过模板参数指定位宽类型（uint32_t 做 FP32 位操作、uint16_t 取指数、U 为目标 FP8 类型）；同一算子内大量 Reg::Cast 在不同位宽间转换；mask 参数控制逐元素生效范围。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **RegTensor 调用次数**: 45
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 分组动态 MX 量化中用 RegTensor<T> 模板化承载输入与中间量，通过 LoadAlign/And/Max 求组内指数最大值，再 Cast 升精度到 FP32 做 Inf/Zero 校验与 scale 计算。

**片段 1** (行 508-527):

```cpp
Reg::RegTensor<T> xRegTensor1;
Reg::RegTensor<uint16_t> absMaskBF16Reg;
Reg::RegTensor<uint16_t> fullZeroReg;
Reg::RegTensor<uint32_t> zeroRegTensor32;
Reg::RegTensor<uint32_t> manMaskFP32Reg;
Reg::RegTensor<uint32_t> fp8NanRegTensor32;
Reg::RegTensor<uint32_t> biasRegTensor32;
Reg::RegTensor<uint32_t> nanRegTensor32;
Reg::RegTensor<uint16_t> expScaleMxYZeroRegTensor;
Reg::RegTensor<uint16_t> expMaxRegTensor;
Reg::RegTensor<uint16_t> expMaxRegTensor0;
Reg::RegTensor<uint16_t> expMaxRegTensor1;
Reg::RegTensor<uint16_t> expMaxreShareExpFP16YOneRegTensor;
Reg::RegTensor<uint32_t> expMaxAndAddOneFP32RegTensor;
Reg::RegTensor<uint32_t> expAndreShareExpFP32RegTensor;
Reg::RegTensor<uint32_t> manAndmxScaleFP32RegTensor;
Reg::RegTensor<float> yZero;
Reg::RegTensor<float> yOne;
Reg::RegTensor<float> reversedShareExpRegTensorFP32Zero;
Reg::RegTensor<float> reversedShareExpRegTensorFP32One;
```

**片段 2** (行 565-586):

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
```

**要点**: 用模板参数 T 使同一份代码适配 half/bfloat16；And+absMask 提取指数位；CompareScalar 针对 FP32 上界做 Inf/Zero 保护。

### 实例 3：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, StoreDist, Sub, UnalignReg, UpdateMask
- **RegTensor 调用次数**: 31
- **参数模式**: `T1_A0_M0_TYPEfloat`（实参 0 个，类型: float）
- **语义**: 动态量化 per-token 计算中用 Reg::RegTensor<float> 串联 abs→reduceMax→scale→div→offset 链路，再按目标 dtype 分支多级 Cast 回到 int8/hifloat8/fp8/int4。

**片段 1** (行 285-314):

```cpp
AscendC::Reg::RegTensor<float>
    vreg3; // cast成float之后的x，如果有smooth_scale，就是x*smooth_scales的结果
AscendC::Reg::RegTensor<float> vreg4; // cast成float之后的smooth_scales
AscendC::Reg::RegTensor<float> vreg6; // x的绝对值absvalue
AscendC::Reg::RegTensor<float> vreg7; // x的abs与-inf比较的结果，可以认为是x的absvalue的一些最大值

AscendC::Reg::RegTensor<float> vreg8; // reduceMax
AscendC::Reg::RegTensor<float> vreg9; // scale————isSymmetric可复用
AscendC::Reg::RegTensor<float>
    vreg10; // Duplicate之后的scale，为了和input一起得到y————isSymmetric可复用

AscendC::Reg::RegTensor<float> vreg16; // input/scale————isSymmetric可复用，作为input/scale+offset
AscendC::Reg::RegTensor<int16_t> vreg17;    // cast成最终y之前的int16类型
AscendC::Reg::RegTensor<half> vreg18;       // cast成最终y之前的half类型
AscendC::Reg::RegTensor<yCopyDtype> vreg19; // 最终y
AscendC::Reg::RegTensor<float> vregPosInf;

// isSymmetric == false
AscendC::Reg::RegTensor<float> vregMinX;
AscendC::Reg::RegTensor<float> vregReduceMaxX;
AscendC::Reg::RegTensor<float> vregReduceMinX;
AscendC::Reg::RegTensor<float> vregMaxSubMin;
AscendC::Reg::RegTensor<float> vregMaxDivScale;
AscendC::Reg::RegTensor<float> vregNegMaxDivScale;
AscendC::Reg::RegTensor<float> vregOffset;
AscendC::Reg::RegTensor<float> vregDupOffset;
AscendC::Reg::RegTensor<float> vregXDivScale;
AscendC::Reg::RegTensor<float> vregReduceMaxXTail;
AscendC::Reg::RegTensor<float> vregReduceMinXTail;
AscendC::Reg::RegTensor<float> vregFinalMax;
```

**片段 2** (行 415-432):

```cpp
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

**要点**: RegTensor 命名按用途编号（vreg3=cast 后 x，vreg8=reduceMax，vreg9=scale）；int4b_t 借助 Pack+Cast 两步完成；Cast 链依赖 castTrait 常量控制饱和/舍入。

### 实例 4：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Max, Min, PostLiteral, ReduceMax, RegLayout, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **RegTensor 调用次数**: 58
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 块量化单行 kernel 中用 RegTensor<IN_TYPE>/float 声明输入与 FP32 中间量，通过 UpdateMask 按 blockSize 动态生成掩码，And/Max/ReduceMax 求块 absMax，再 Div 得到 scale。

**片段 1** (行 286-305):

```cpp
AscendC::Reg::RegTensor<IN_TYPE> vReg1;
AscendC::Reg::RegTensor<IN_TYPE> vReg2;
AscendC::Reg::RegTensor<IN_TYPE> vReg3;
AscendC::Reg::RegTensor<IN_TYPE> vReg4;
AscendC::Reg::RegTensor<float> vReg5;
AscendC::Reg::RegTensor<float> vReg6;
AscendC::Reg::RegTensor<float> vReg7;
AscendC::Reg::RegTensor<float> vReg8;
AscendC::Reg::RegTensor<float> vReg9;
AscendC::Reg::RegTensor<float> vReg10;
AscendC::Reg::RegTensor<float> vReg11;
AscendC::Reg::RegTensor<float> vReg12;
AscendC::Reg::RegTensor<float> vReg13;
AscendC::Reg::RegTensor<float> vReg14;
AscendC::Reg::RegTensor<int16_t> vReg19;
AscendC::Reg::RegTensor<half> vReg20;
AscendC::Reg::RegTensor<OUT_TYPE> vReg15;
AscendC::Reg::RegTensor<OUT_TYPE> vReg16;
AscendC::Reg::MaskReg maskReg1;
AscendC::Reg::MaskReg maskReg2;
```

**片段 2** (行 338-357):

```cpp
curSize = tilingData_->blockSizeCol;
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
```

**片段 3** (行 399-418):

```cpp
for (uint16_t vlLoopIdx = 0; vlLoopIdx < tailLoopNum; vlLoopIdx++) {
    inputMaskReg = AscendC::Reg::UpdateMask<IN_TYPE>(curSize);
    AscendC::Reg::DataCopy(vReg0, xLocal + rowIdx * inputColAlign +
                                           normalColBlockLoop * tilingData_->blockSizeCol +
                                           vlLoopIdx * VL);
    AscendC::Reg::And((AscendC::Reg::RegTensor<uint32_t>&)vReg3,
                           (AscendC::Reg::RegTensor<uint32_t>&)vReg0,
                           (AscendC::Reg::RegTensor<uint32_t>&)vRegFp32Max, inputMaskReg);
    AscendC::Reg::Max<uint32_t, AscendC::Reg::MaskMergeMode::MERGING>(
        (AscendC::Reg::RegTensor<uint32_t>&)vReg2, (AscendC::Reg::RegTensor<uint32_t>&)vReg2,
        (AscendC::Reg::RegTensor<uint32_t>&)vReg3, inputMaskReg);
}

AscendC::Reg::ReduceMax<uint32_t>((AscendC::Reg::RegTensor<uint32_t>&)vReg3,
                                       (AscendC::Reg::RegTensor<uint32_t>&)vReg2, defaultMaskReg);

AscendC::Reg::Duplicate(vReg4, vReg3, defaultMaskReg);

// brc(input_max) - 位模式直接参与计算
AscendC::Reg::Div<float, &mode>(vReg8, (AscendC::Reg::RegTensor<float>&)vReg4, fp8MaxValue,
```

**要点**: UpdateMask<IN_TYPE>(curSize) 按剩余元素数生成尾块掩码；Max 用 MaskMergeMode::MERGING 累积跨 VL 最大值；ReduceMax 跨块归约后 Duplicate 广播。

### 实例 5：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, Select, ShiftLefts, ShiftRights, StoreDist, Sub, UnPack
- **RegTensor 调用次数**: 23
- **参数模式**: `T1_A0_M0_TYPEint16_t+uint16_t`（实参 0 个，类型: uint16_t, int16_t）
- **语义**: SwiGLU 双轴 MX 量化中用 RegTensor<uint16_t> 做 BF16 指数位操作，And 取绝对值后双轴 Max/ReduceMaxWithDataBlock 归约，再经 Cast 升 FP32、Compare/Select 做指数提取与就近舍入，Pack 回 b16/b8 存 scale。

**片段 1** (行 947-947):

```cpp
__VEC_SCOPE__
```

**片段 2** (行 992-1051):

```cpp
for (uint16_t i = 0; i < blockCount; i++) {
    Reg::DataCopy<xDtype, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
        x0, x1, xAddr, 256);

    // Absolute value (CLUB)
    Reg::And(x0Abs, (Reg::RegTensor<uint16_t>&)x0, absMask, maskAll);
    Reg::And(x1Abs, (Reg::RegTensor<uint16_t>&)x1, absMask, maskAll);

    // -1 axis: max of pair + reduce
    Reg::Max(absMaxDim1, x0Abs, x1Abs, maskAll);
    Reg::ReduceMaxWithDataBlock(absMaxDim1, absMaxDim1, maskAll); // -1轴 指数位计算结束 8个int16的数

    // -2 axis: accumulate column-wise max
    Reg::Max(absMax1Dim2, absMax1Dim2, x0Abs, maskAll); // -2轴最大值
    Reg::Max(absMax2Dim2, absMax2Dim2, x1Abs, maskAll); // -2轴最大值

    // ---- -1 axis CLUB scale: ZERO half (even positions after ReduceMax) ----
    Reg::UnPack((AscendC::Reg::RegTensor<uint32_t>&)absMaxDim1Unpack,
                     (AscendC::Reg::RegTensor<uint16_t>&)absMaxDim1);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>((Reg::RegTensor<float>&)max32, absMaxDim1Unpack,
                                                       maskAll);

    Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32, expMaskReg, maskAll32);
    Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32, zeroReg32, maskAll32);
    Reg::Mul((Reg::RegTensor<float>&)max32, (Reg::RegTensor<float>&)max32,
                  (Reg::RegTensor<float>&)invMax, maskAll32);
    Reg::ShiftRights(exp32, max32, SHR_NUM_FOR_FP32, maskAll32);
    Reg::And(man32, max32, manMaskReg, maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32, static_cast<uint32_t>(0), maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, exp32, EXP_254, maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, static_cast<uint32_t>(0), maskAll32);
    Reg::MaskAnd(p0, p0, p1, maskAll32);
    Reg::MaskAnd(p0, p0, p2, maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, exp32, static_cast<uint32_t>(0), maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, HALF_FOR_MAN, maskAll32);
    Reg::MaskAnd(p1, p1, p2, maskAll32);
    Reg::MaskOr(p0, p0, p1, maskAll32);

    Reg::Adds(expAddOne32, exp32, 1, maskAll32);
    Reg::Select(extractExp, expAddOne32, exp32, p0);
    Reg::Select<uint32_t>(extractExp, extractExp, fp8NanReg32, cmpResult);
    Reg::Select<uint32_t>(extractExp, extractExp, zeroReg32, zeroMask);

    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale16, extractExp); // -1轴scale结果

    Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, maskAll32);
    Reg::Sub(halfScale, scaleBiasReg, extractExp, maskAll32);
    Reg::Select<uint32_t>(halfScale, halfScale, nanReg32, cmpResult);
    Reg::Select<uint32_t>(halfScale, halfScale, zeroReg32, zeroMask);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(recip16Zero,
                                                                      halfScale); // -1轴int16 1/scale结束

    // ---- -1 axis CLUB scale: ONE half (odd positions after ReduceMax) ----
    Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(scale8Zero, scale16);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScale1Addr, scale8Zero, 32,
                                                                         maskReduceB8);
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScale1ReciprocalAddr, recip16Zero,
                                                                          16, maskReduceB16);
}
```

**要点**: UnPack+Cast 组合把 b16 还原成 FP32 做位级运算；CompareScalar+MaskAnd 构成“exp 在 (0,254] 且尾数>0”的舍入判断；Pack<HighLowPart::LOWEST> 取低半作为最终 b8 scale。

### 实例 6：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **RegTensor 调用次数**: 21
- **参数模式**: `T1_A0_M0_TYPEfloat`（实参 0 个，类型: float）
- **语义**: flat 量化 scale 计算中用 RegTensor<float> 承载 BF16 升精度后的 max，经 Mul/ShiftRights/And 拆指数与尾数，CompareScalar+MaskAnd 判定舍入，Select/Pack 产出 b16 scale 与倒数并 StoreAlign 落盘。

**片段 1** (行 459-459):

```cpp
float invDstTypeMax)
```

**片段 2** (行 500-539):

```cpp
for (uint16_t i = 0; i < repeatTimes; i++) {
    preMaskScale = AscendC::Reg::UpdateMask<uint32_t>(scaleNum);
    AscendC::Reg::LoadAlign<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                 AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16, srcPtr, vfLen32);

    AscendC::Reg::Cast<float, bfloat16_t, castTraitHalf2Float>(
        (AscendC::Reg::RegTensor<float>&)max32, (AscendC::Reg::RegTensor<bfloat16_t>&)max16,
        preMaskScale);
    AscendC::Reg::Compare<uint32_t, AscendC::CMPMODE::LT>(cmpResult, max32, expMask, preMaskScale);
    AscendC::Reg::Compare<uint32_t, AscendC::CMPMODE::NE>(zeroMask, max32, zeroRegTensor32, preMaskScale);

    AscendC::Reg::Mul((AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)max32, invMax, preMaskScale);
    AscendC::Reg::ShiftRights(exp32, max32, SHR_NUM_FOR_FP32, preMaskScale);
    AscendC::Reg::And(man32, max32, manMaskFP32, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, AscendC::CMPMODE::GT>(p0, exp32, NUMBER_ZERO, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, AscendC::CMPMODE::LT>(p1, exp32, NUMBER_TWO_FIVE_FOUR,
                                                                     preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, AscendC::CMPMODE::GT>(p2, man32, NUMBER_ZERO, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p1, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p2, preMaskScale);

    AscendC::Reg::Adds(expAddOne32, exp32, 1, preMaskScale);
    AscendC::Reg::Select(extractExp, expAddOne32, exp32, p0);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, fp4NanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(expOut, extractExp);

    AscendC::Reg::StoreAlign<uint16_t, AscendC::Reg::StoreDist::DIST_PACK_B16>(
        dstPtr + i * SCALE_STORE_STRIDE, expOut, dataMaskB16Half);

    AscendC::Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, preMaskScale);
    AscendC::Reg::Sub(halfScale, scaleBias, extractExp, preMaskScale);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, nanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(recExpOut, halfScale);

    AscendC::Reg::StoreAlign<uint16_t>(dst2Ptr + i * vfLen32, recExpOut, dataMaskB16Half);
}
```

**要点**: castTraitHalf2Float 把 BF16→FP32 做位运算；舍入逻辑用 exp∈(0,254] 且 man>0 双条件；expOut 与 recExpOut 两次 StoreAlign 分别存 scale 与 1/scale。

### 实例 7：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **RegTensor 调用次数**: 34
- **参数模式**: `T2_A0_M0_TYPEfloat`（实参 0 个，类型: float）
- **语义**: 复数取模算子中用 RegTensor<float, RegTraitNumOne> 声明单矢量寄存器中间量，对 subnormal 做 SCALE_UP 放大，提取指数因子后用归一化 sqrt(a²+b²) 计算模长并还原。

**片段 1** (行 41-70):

```cpp

using calcTypeInt = typename std::conditional<AscendC::Std::IsSame<T, half>::value, uint16_t, uint32_t>::type;

// 寄存器定义
Reg::RegTensor<T> vSrcReg0;
Reg::RegTensor<T> vSrcReg1;
Reg::RegTensor<float, Reg::RegTraitNumOne> vA;
Reg::RegTensor<float, Reg::RegTraitNumOne> vB;
Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vA0;
Reg::RegTensor<float, Reg::RegTraitNumOne> vA1;
Reg::RegTensor<float, Reg::RegTraitNumOne> vB1;
Reg::RegTensor<float, Reg::RegTraitNumOne> vAS;
Reg::RegTensor<float, Reg::RegTraitNumOne> vBS;
Reg::RegTensor<float, Reg::RegTraitNumOne> vA1Sq;
Reg::RegTensor<float, Reg::RegTraitNumOne> vB1Sq;
Reg::RegTensor<float, Reg::RegTraitNumOne> vSumSq;
Reg::RegTensor<float, Reg::RegTraitNumOne> vS;
Reg::RegTensor<T, Reg::RegTraitNumOne> vResult;
Reg::RegTensor<float, Reg::RegTraitNumOne> vResultS;

Reg::RegTensor<float, Reg::RegTraitNumOne> vAbsSrcReg0;
Reg::RegTensor<float, Reg::RegTraitNumOne> vAbsSrcReg1;

Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vMinNormalFloat;
Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vExpBias;
Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vZero;
Reg::RegTensor<float, Reg::RegTraitNumOne> vSCALE_UP;
Reg::RegTensor<float, Reg::RegTraitNumOne> vSCALE_DOWN;

uint32_t sreg = (uint32_t)count;
```

**片段 2** (行 123-152):

```cpp
Reg::Compare<uint32_t, CMPMODE::EQ>(preg4, (AscendC::Reg::RegTensor<uint32_t>&)vB, vZero,
                                    preg);

// subnormal处理
Reg::Compare<uint32_t, CMPMODE::LT>(preg3, (AscendC::Reg::RegTensor<uint32_t>&)vA,
                                    vMinNormalFloat, preg);
Reg::Mul(vAS, vA, vSCALE_UP, preg);
Reg::Mul(vBS, vB, vSCALE_UP, preg);
Reg::Select(vA, vAS, vA, preg3);
Reg::Select(vB, vBS, vB, preg3);
// 提取A的指数因子（对vAForExp操作）
Reg::ShiftRights(vA0, (AscendC::Reg::RegTensor<uint32_t>&)vA, SHR_NUM_FOR_FP32, preg);
Reg::ShiftLefts(vA0, vA0, SHR_NUM_FOR_FP32, preg);
Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA, vA0,
         preg);
Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB, vA0,
         preg);

Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA1, vExpBias,
         preg);
Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB1, vExpBias,
         preg);

// 计算归化值
Reg::Mul(vA1Sq, vA1, vA1, preg);
Reg::Mul(vB1Sq, vB1, vB1, preg);
Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
Reg::Sqrt(vS, vSumSq, preg);

Reg::Mul(vResult, vS, (AscendC::Reg::RegTensor<float>&)vA0, preg);
```

**要点**: 第二模板参数 RegTraitNumOne 表示单矢量 Reg（长度 VL）；subnormal 通过 Compare+Select 选择是否 SCALE_UP；归一化避免 a²+b² 溢出，最后乘回指数因子 vA0。

### 实例 8：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, Muls, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **RegTensor 调用次数**: 26
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: per-channel 伪量化的 VEC 计算上下文中 RegTensor 作为逐通道缩放/裁剪的寄存器载体，配合 Abs/Max/Min/Mul/Select 完成按通道 min-max 的仿射量化（本片段为 __VEC_SCOPE__ 入口）。

（行 329-329）

```cpp
__VEC_SCOPE__
```

**要点**: 该实例仅暴露 __VEC_SCOPE__ 入口，RegTensor 具体声明在算子其他片段；co-used Max/Min/Muls 体现 per-channel 上下界求解；DivSpecificMode 用于 scale 除法。

### 实例 9：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, Duplicate, Interleave, LoadAlign, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, SatMode, Select, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **RegTensor 调用次数**: 48
- **参数模式**: `T1_A0_M0_TYPEbfloat16+float`（实参 0 个，类型: bfloat16, float）
- **语义**: 分组动态 MX 量化（BF16 路径）中用 RegTensor<bfloat16_t>/float 承载输入与共享指数，按 T 分支用 Cast<float,T> 升精度后乘以 reversedShareExp，Interleave 重排再 Cast 到 FP8 并 Pack 输出。

**片段 1** (行 283-302):

```cpp
Reg::RegTensor<bfloat16_t> xBF16RegTensor0;
Reg::RegTensor<bfloat16_t> xBF16RegTensor1;
Reg::RegTensor<uint16_t> expMaxRegTensor0;
Reg::RegTensor<uint16_t> expMaxRegTensor1;
Reg::RegTensor<uint16_t> maxEleRegTensor;
Reg::RegTensor<uint16_t> fp8MaxExpRegTensor;
Reg::RegTensor<uint16_t> fp8NanRegTensor;
Reg::RegTensor<uint16_t> mxScaleRegTensor;
Reg::RegTensor<uint8_t> mxScale;
Reg::RegTensor<uint16_t> reversedShareExpRegTensor;
Reg::RegTensor<float> reversedShareExpRegTensorFP32Zero;
Reg::RegTensor<float> reversedShareExpRegTensorFP32One;
Reg::RegTensor<uint16_t> specialExpRegTensor;
Reg::RegTensor<uint16_t> biasRegTensor;
Reg::RegTensor<uint16_t> zeroRegTensor;
Reg::RegTensor<uint16_t> nanRegTensor;
Reg::RegTensor<uint16_t> yRegTensorZero;
Reg::RegTensor<uint16_t> yRegTensorOne;
Reg::RegTensor<uint8_t> outZero;
Reg::RegTensor<uint8_t> outOne;
```

**片段 2** (行 379-396):

```cpp
for (uint16_t j = 0; j < static_cast<uint16_t>(blockCount); j++) {
    Reg::LoadAlign(xRegTensor, xAddr + j * dataLen + i * vfLen);
    if constexpr (IsSame<T, half>::value) {
        Reg::Cast<float, T, castTraitZero>(yZero, xRegTensor, p0);
        Reg::Cast<float, T, castTraitOne>(yOne, xRegTensor, p0);
        Reg::Mul(yZero, yZero, reversedShareExpRegTensorFP32Zero, maskAll);
        Reg::Mul(yOne, yOne, reversedShareExpRegTensorFP32One, maskAll);
    } else {
        Reg::Mul(valueRegTensor, xRegTensor, (Reg::RegTensor<bfloat16_t>&)reversedShareExpRegTensor, p0);
        Reg::Cast<float, bfloat16_t, castTraitZero>(yZero, valueRegTensor, maskAll);
        Reg::Cast<float, bfloat16_t, castTraitOne>(yOne, valueRegTensor, maskAll);
    }
    Reg::Interleave(yZero, yOne, yZero, yOne);
    Reg::Cast<U, float, castTrait32to8>(yZeroFP8, yZero, maskAll);
    Reg::Cast<U, float, castTrait32to8>(yOneFP8, yOne, maskAll);
    Reg::Pack(yRegTensorZero, (Reg::RegTensor<uint32_t>&)yZeroFP8);
    Reg::Pack(outZero, yRegTensorZero);
    Reg::Pack(yRegTensorOne, (Reg::RegTensor<uint32_t>&)yOneFP8);
```

**要点**: bfloat16_t 模板参数走直接 And 取指数；half 路径需先 Cast 再 Mul 共享 exp；Interleave+Pack 把 zero/one 两路 FP8 结果交织打包成 b8 输出。

### 实例 10：complex_abs::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, Mul, RegLayout, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **RegTensor 调用次数**: 12
- **参数模式**: `T1_A0_M0_TYPEint32_t+uint32_t`（实参 0 个，类型: int32_t, uint32_t）
- **语义**: 复数取模算子的 VEC_SCOPE 片段中用 RegTensor<float/uint32_t> 完成大小交换、subnormal 放大、归一化 sqrt 求模，并乘回指数因子与 SCALE_DOWN 还原后 Cast 回 T 存储。

（行 108-155）

```cpp
    Reg::Mul(vA1Sq, vA, vA, preg);
    Reg::Mul(vB1Sq, vB, vB, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);
    Reg::Cast<T, float, castTrait32to16>(vResult, vS, preg);
    Reg::StoreAlign<T, Reg::StoreDist::DIST_PACK_B32>(dstAddr + i * vflen, vResult, preg);
} else {
    Reg::LoadAlign<T, Reg::LoadDist::DIST_DINTLV_B32>(vSrcReg0, vSrcReg1, srcAddr + i * vflen * 2);
    Reg::Abs(vAbsSrcReg0, vSrcReg0, preg);
    Reg::Abs(vAbsSrcReg1, vSrcReg1, preg);
    Reg::Compare<float, CMPMODE::GT>(preg2, vAbsSrcReg1, vAbsSrcReg0, preg);
    Reg::Select<float>(vA, vAbsSrcReg1, vAbsSrcReg0, preg2);
    Reg::Select<float>(vB, vAbsSrcReg0, vAbsSrcReg1, preg2);

    // 0的处理
    Reg::Compare<uint32_t, CMPMODE::EQ>(preg4, (AscendC::Reg::RegTensor<uint32_t>&)vB, vZero,
                                        preg);

    // subnormal处理
    Reg::Compare<uint32_t, CMPMODE::LT>(preg3, (AscendC::Reg::RegTensor<uint32_t>&)vA,
                                        vMinNormalFloat, preg);
    Reg::Mul(vAS, vA, vSCALE_UP, preg);
    Reg::Mul(vBS, vB, vSCALE_UP, preg);
    Reg::Select(vA, vAS, vA, preg3);
    Reg::Select(vB, vBS, vB, preg3);
    // 提取A的指数因子（对vAForExp操作）
    Reg::ShiftRights(vA0, (AscendC::Reg::RegTensor<uint32_t>&)vA, SHR_NUM_FOR_FP32, preg);
    Reg::ShiftLefts(vA0, vA0, SHR_NUM_FOR_FP32, preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA, vA0,
             preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB, vA0,
             preg);

    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA1, vExpBias,
             preg);
    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB1, vExpBias,
             preg);

    // 计算归化值
    Reg::Mul(vA1Sq, vA1, vA1, preg);
    Reg::Mul(vB1Sq, vB1, vB1, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);

    Reg::Mul(vResult, vS, (AscendC::Reg::RegTensor<float>&)vA0, preg);
    Reg::Mul(vResultS, vResult, vSCALE_DOWN, preg);
    Reg::Select(vResult, vResultS, vResult, preg3);
```

**要点**: 用 (RegTensor<uint32_t>&) 强转做 FP32 位级操作；Compare+Select 保证 a≥b 以稳定提取指数；SCALE_DOWN 在 subnormal 路径补偿先前的 SCALE_UP。

### 实例 11：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, Interleave, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, SatMode, Select, ShiftRights, Sub, UnalignReg, UpdateMask
- **RegTensor 调用次数**: 50
- **参数模式**: `T1_A0_M0_TYPEint16_t+uint16_t`（实参 0 个，类型: uint16_t, int16_t）
- **语义**: 动态 MX 量化非尾轴 BF16/half 路径中用 RegTensor<uint16_t> 取指数位，对 half 先 Cast 到 bfloat16 再 And，并用 Compare/Select 对 invalid 数据做兜底，循环 Max 累积块内 expMax。

**片段 1** (行 256-275):

```cpp
Reg::RegTensor<uint16_t> fp8MaxExp;
Reg::RegTensor<uint16_t> fp8Nan;
Reg::RegTensor<uint16_t> shareExp;
Reg::RegTensor<uint16_t> mxScaleInt;

Reg::RegTensor<uint16_t> reversedShareExp;
Reg::RegTensor<uint16_t> specialExp;
Reg::RegTensor<uint16_t> bias;
Reg::RegTensor<uint16_t> zero;
Reg::RegTensor<uint16_t> nan;
Reg::RegTensor<uint16_t> y0;
Reg::RegTensor<uint16_t> y1;
Reg::RegTensor<uint16_t> invalidMaskU16;
Reg::RegTensor<uint16_t> xSelect;

Reg::RegTensor<uint8_t> mxScale;
Reg::RegTensor<uint8_t> outZero;
Reg::RegTensor<uint8_t> outOne;
Reg::RegTensor<bfloat16_t> valueRegTensor;
Reg::RegTensor<float> reversedShareExpRegTensorFP32Zero;
```

**片段 2** (行 314-335):

```cpp
if constexpr (IsSame<T, half>::value) {
    Reg::And(xSelect, (Reg::RegTensor<uint16_t>&)x, invalidMaskU16, p0);
    Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask, xSelect, invalidMaskU16, p0);
    Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16, x, p0);
    Reg::And(expMax, (Reg::RegTensor<uint16_t>&)xBF16, maxEle, p0);
    Reg::Select<uint16_t>(expMax, expMax, maxEle, invalidDataMask);
} else if constexpr (IsSame<T, bfloat16_t>::value) {
    Reg::And(expMax, (Reg::RegTensor<uint16_t>&)x, maxEle, p0);
}
for (uint16_t j = 1; j < static_cast<uint16_t>(blockCount); j++) {
    this->template LoadData<RoundMode::CAST_TRUNC, roundMode>(xAddr, j * dataLen + i * vfNum16, x, p0);
    if constexpr (IsSame<T, half>::value) {
        Reg::And(xSelect, (Reg::RegTensor<uint16_t>&)x, invalidMaskU16, p0);
        Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask, xSelect, invalidMaskU16, p0);
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16, x, p0);
        Reg::And(exp, (Reg::RegTensor<uint16_t>&)xBF16, maxEle, p0);
        Reg::Select<uint16_t>(exp, exp, maxEle, invalidDataMask);
    } else if constexpr (IsSame<T, bfloat16_t>::value) {
        Reg::And(exp, (Reg::RegTensor<uint16_t>&)x, maxEle, p0);
    }
    Reg::Max(expMax, expMax, exp, p0);
}
```

**要点**: half→bfloat16 用 castTraitHalf2Bf16 中转再取指数；invalidMaskU16+Compare 标记非法值并用 maxEle 兜底；循环 LoadData+Max 跨块累积最大指数。

### 实例 12：dynamic_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Adds, Cast, CreateMask, DataCopy, Div, DivSpecificMode, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, ReduceMax, ReduceMin, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **RegTensor 调用次数**: 16
- **参数模式**: `T2_A0_M0_TYPEfloat`（实参 0 个，类型: float）
- **语义**: 动态量化大 shape 场景中用 RegTensor<float, RegTraitNumOne> 计算 per-token 的 scale 与 offset：Sub 求 max-min、Muls 缩放、Div 得 scale、取负加偏置得 offset，再用 FIRST_ELEMENT_B32 存储标量结果。

**片段 1** (行 432-432):

```cpp
__VEC_SCOPE__
```

**片段 2** (行 512-534):

```cpp
if constexpr (isFinal) {
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg9;
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg10;
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg11;
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg12;
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg13;
    AscendC::Reg::Sub(vreg9, vregMax, vregMin, maskAll);
    AscendC::Reg::Muls(vreg10, vreg9, scaleMaxValue, maskAll); // scale
    AscendC::Reg::Div<float, &mode>(vreg11, vregMax, vreg10, maskAll);
    AscendC::Reg::Muls(vreg12, vreg11, -1, maskAll);
    AscendC::Reg::Adds(vreg13, vreg12, offsetMaxValue, maskAll); // offset

    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        maxLocalAddr, vreg10, maskAll);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        minLocalAddr, vreg13, maskAll);
} else {
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        maxLocalAddr, vregMax, maskAll);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        minLocalAddr, vregMin, maskAll);
}
```

**要点**: RegTraitNumOne 单矢量 Reg 适合 reduce 后的标量化计算；DataCopy<DIST_FIRST_ELEMENT_B32> 只存寄存器首个元素即标量；isFinal 分支决定是否再算 offset。

### 实例 13：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **RegTensor 调用次数**: 21
- **参数模式**: `T1_A0_M0_TYPEfloat`（实参 0 个，类型: float）
- **语义**: RMS-Norm 联合 MX 量化的 scale 计算中用 RegTensor<float> 承载升精度后的 max，经 Mul/ShiftRights/And 拆位、CompareScalar+MaskAnd 判舍入、Select/Pack 产出 b16 scale 与倒数并 DataCopy 落盘。

**片段 1** (行 384-384):

```cpp
__VEC_SCOPE__
```

**片段 2** (行 419-463):

```cpp
for (uint16_t i = 0; i < loopNumScale4NV; i++) {
    AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16, maxExpAddr, VL_FP32);

    AscendC::Reg::Cast<float, T1, castTraitHalf2Float>(
        (AscendC::Reg::RegTensor<float>&)max32, (AscendC::Reg::RegTensor<T1>&)max16, preMaskScale);
    AscendC::Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32, expMask, preMaskScale);
    AscendC::Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32, zeroRegTensor32, preMaskScale);

    AscendC::Reg::Mul((AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)invMax, preMaskScale);
    AscendC::Reg::ShiftRights(exp32, max32, SHR_NUM_FOR_FP32, preMaskScale);
    AscendC::Reg::And(man32, max32, manMaskFP32, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32, zeroForAll, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, exp32, Exp254, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, zeroForAll, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p1, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p2, preMaskScale);

    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, exp32, zeroForAll, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, halfForMan, preMaskScale);
    AscendC::Reg::MaskAnd(p1, p1, p2, preMaskScale);
    AscendC::Reg::MaskOr(p0, p0, p1, preMaskScale);

    AscendC::Reg::Adds(expAddOne32, exp32, 1, preMaskScale);
    AscendC::Reg::Select(extractExp, expAddOne32, exp32, p0);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, fp8NanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(expOut, extractExp);

    AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                AscendC::Reg::StoreDist::DIST_PACK_B16>(mxScaleLocalAddr, expOut,
                                                                             VL_FP32 / NUM_TWO, maskHalf);

    AscendC::Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, preMaskScale);
    AscendC::Reg::Sub(halfScale, scaleBias, extractExp, preMaskScale);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, nanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(recExpOut, halfScale);

    AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        halfScaleLocalAddr, recExpOut, VL_FP32, maskHalf);
}
```

**要点**: castTraitHalf2Float 把 b16 max 升到 FP32 做位运算；舍入双条件 exp∈(0,254] 且 man>0；expOut 与 recExpOut 经 DIST_PACK_B16 与普通 DataCopy 分别存 scale/倒数。

### 实例 14：dynamic_mx_quant::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegLayout, SatMode, ShiftRights, StoreUnAlign, StoreUnAlignPost, UnalignReg
- **RegTensor 调用次数**: 21
- **参数模式**: `T1_A0_M0_TYPEfloat`（实参 0 个，类型: float）
- **语义**: 动态 MX 量化尾轴场景中用 RegTensor<float> 双路 LoadAlign+DeInterleave 重排数据，And 提取指数后 Max/ReduceMaxWithDataBlock 归约块内最大指数，Pack 成 b16 后用 StoreUnAlign/StoreUnAlignPost 非对齐落盘。

**片段 1** (行 507-553):

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<float> x0ZeroFP32;
    Reg::RegTensor<float> x0OneFP32;
    Reg::RegTensor<float> x1ZeroFP32;
    Reg::RegTensor<float> x1OneFP32;
    Reg::RegTensor<uint32_t> x0MaxExpB32;
    Reg::RegTensor<uint32_t> x1MaxExpB32;
    Reg::RegTensor<uint32_t> xMaxExpB32;
    Reg::RegTensor<uint16_t> xMaxExpB16;

    Reg::RegTensor<uint32_t> expMask32Bit;
    Reg::Duplicate(expMask32Bit, FP32_MX_MAX_EXP);

    Reg::MaskReg MaskB32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg Mask = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
    Reg::UnalignReg ureg;
    static constexpr Reg::CastTrait castTraitFp32toBF16 = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                           Reg::MaskMergeMode::ZEROING, RoundMode::CAST_TRUNC};
    for (uint16_t i = 0; i < loopNum2VF; i++) {
        // x0ZeroFP32: 1,3,5,7,9,...,127        x1ZeroFP32: 2,4,6,8,10,...,128
        Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
            x0ZeroFP32, x1ZeroFP32, xLocalAddr, VF_LEN_32_DOUBLE);
        // x0OneFP32: 129,131,133,135,...,255  x1OneFP32: 130,132,134,136,...,256
        Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
            x0OneFP32, x1OneFP32, xLocalAddr, VF_LEN_32_DOUBLE);
        // x0ZeroFP32: 1,5,9,13,...,253    x0OneFP32: 3,7,11,15,...,255
        Reg::DeInterleave(x0ZeroFP32, x0OneFP32, x0ZeroFP32, x0OneFP32);
        // x1ZeroFP32: 2,6,10,14,...,254    x1OneFP32: 4,8,12,16,...,256
        Reg::DeInterleave(x1ZeroFP32, x1OneFP32, x1ZeroFP32, x1OneFP32);
        Reg::And((Reg::RegTensor<uint32_t>&)x0ZeroFP32, (Reg::RegTensor<uint32_t>&)x0ZeroFP32, expMask32Bit,
                 MaskB32);
        Reg::And((Reg::RegTensor<uint32_t>&)x0OneFP32, (Reg::RegTensor<uint32_t>&)x0OneFP32, expMask32Bit, MaskB32);
        Reg::And((Reg::RegTensor<uint32_t>&)x1ZeroFP32, (Reg::RegTensor<uint32_t>&)x1ZeroFP32, expMask32Bit,
                 MaskB32);
        Reg::And((Reg::RegTensor<uint32_t>&)x1OneFP32, (Reg::RegTensor<uint32_t>&)x1OneFP32, expMask32Bit, MaskB32);
        Reg::Max(x0MaxExpB32, (Reg::RegTensor<uint32_t>&)x0ZeroFP32, (Reg::RegTensor<uint32_t>&)x0OneFP32, MaskB32);
        Reg::Max(x1MaxExpB32, (Reg::RegTensor<uint32_t>&)x1ZeroFP32, (Reg::RegTensor<uint32_t>&)x1OneFP32, MaskB32);
        Reg::Max(xMaxExpB32, x0MaxExpB32, x1MaxExpB32, MaskB32);
        Reg::ReduceMaxWithDataBlock(xMaxExpB32, xMaxExpB32, MaskB32);
        Reg::ShiftRights(xMaxExpB32, xMaxExpB32, FP32_PACK_SHR_NUM, MaskB32);
        Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(xMaxExpB16, xMaxExpB32);
        Reg::StoreUnAlign<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(maxExpAddr, xMaxExpB16, ureg,
                                                                        ELEMENT_AFTER_REDUCE_);
    }
    Reg::StoreUnAlignPost(maxExpAddr, ureg, 0);
}
```

**片段 2** (行 526-551):

```cpp
for (uint16_t i = 0; i < loopNum2VF; i++) {
    // x0ZeroFP32: 1,3,5,7,9,...,127        x1ZeroFP32: 2,4,6,8,10,...,128
    Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
        x0ZeroFP32, x1ZeroFP32, xLocalAddr, VF_LEN_32_DOUBLE);
    // x0OneFP32: 129,131,133,135,...,255  x1OneFP32: 130,132,134,136,...,256
    Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
        x0OneFP32, x1OneFP32, xLocalAddr, VF_LEN_32_DOUBLE);
    // x0ZeroFP32: 1,5,9,13,...,253    x0OneFP32: 3,7,11,15,...,255
    Reg::DeInterleave(x0ZeroFP32, x0OneFP32, x0ZeroFP32, x0OneFP32);
    // x1ZeroFP32: 2,6,10,14,...,254    x1OneFP32: 4,8,12,16,...,256
    Reg::DeInterleave(x1ZeroFP32, x1OneFP32, x1ZeroFP32, x1OneFP32);
    Reg::And((Reg::RegTensor<uint32_t>&)x0ZeroFP32, (Reg::RegTensor<uint32_t>&)x0ZeroFP32, expMask32Bit,
             MaskB32);
    Reg::And((Reg::RegTensor<uint32_t>&)x0OneFP32, (Reg::RegTensor<uint32_t>&)x0OneFP32, expMask32Bit, MaskB32);
    Reg::And((Reg::RegTensor<uint32_t>&)x1ZeroFP32, (Reg::RegTensor<uint32_t>&)x1ZeroFP32, expMask32Bit,
             MaskB32);
    Reg::And((Reg::RegTensor<uint32_t>&)x1OneFP32, (Reg::RegTensor<uint32_t>&)x1OneFP32, expMask32Bit, MaskB32);
    Reg::Max(x0MaxExpB32, (Reg::RegTensor<uint32_t>&)x0ZeroFP32, (Reg::RegTensor<uint32_t>&)x0OneFP32, MaskB32);
    Reg::Max(x1MaxExpB32, (Reg::RegTensor<uint32_t>&)x1ZeroFP32, (Reg::RegTensor<uint32_t>&)x1OneFP32, MaskB32);
    Reg::Max(xMaxExpB32, x0MaxExpB32, x1MaxExpB32, MaskB32);
    Reg::ReduceMaxWithDataBlock(xMaxExpB32, xMaxExpB32, MaskB32);
    Reg::ShiftRights(xMaxExpB32, xMaxExpB32, FP32_PACK_SHR_NUM, MaskB32);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(xMaxExpB16, xMaxExpB32);
    Reg::StoreUnAlign<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(maxExpAddr, xMaxExpB16, ureg,
                                                                    ELEMENT_AFTER_REDUCE_);
}
```

**要点**: LoadAlign<DIST_DINTLV_B32> 一次加载双路交织数据；DeInterleave 把 zero/one 两路二次重排；StoreUnAlign+StoreUnAlignPost 组合完成非对齐尾存储；CastTrait 显式指定 ZERO/SAT/MergeMode/Round。

### 实例 15：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, ClearSpr, Compare, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, GatherMask, GatherMaskMode, Interleave, LoadDist, MaskInterleave, MaskReg, PostLiteral, SubCarryOut, SubCarryOuts, UnalignReg, UpdateMask
- **RegTensor 调用次数**: 25
- **参数模式**: `T1_A0_M0_TYPEint32_t`（实参 0 个，类型: int32_t）
- **语义**: 稀疏切片算子中用 RegTensor<int32_t> 承载 int64 索引的高低半部，通过 Compare 生成 mask 选择谓词、GatherMask 聚合有效元素，DeInterleave+SubCarryOut 实现 b64 带借位减法后再次 GatherMask 聚合结果。

**片段 1** (行 651-651):

```cpp
__VEC_SCOPE__
```

**片段 2** (行 704-731):

```cpp
Reg::DataCopy(vregInputOne, (__ubuf__ int64_t*)(indicesUbAddr + dim * count + loopIndex * vl));
Reg::DataCopy(vregInputTwo,
                   (__ubuf__ int64_t*)(indicesUbAddr + dim * count + loopIndex * vl + vlSize));
Reg::DataCopy<int8_t, Reg::LoadDist::DIST_UNPACK4_B8>(
    vregInMask, (__ubuf__ int8_t*)(maskUbAddr + loopIndex * vl));
Reg::Compare<int32_t, CMPMODE::EQ>(pregSelect, (Reg::RegTensor<int32_t>&)vregInMask, vregOnes,
                                        pregIndices);

Reg::GatherMask<int32_t, Reg::GatherMaskMode::NO_STORE_REG>(
    vregInMaskGathered, (Reg::RegTensor<int32_t>&)vregInMask, pregSelect);
Reg::Compare<int32_t, CMPMODE::EQ>(pregGathered, vregInMaskGathered, vregOnes, pregIndices);

// deinterleave -> gathermask -> interleave to implement b64 gathermask
Reg::DeInterleave<int32_t>((Reg::RegTensor<int32_t>&)vregInputLowerHalf, vregInputHigherHalf,
                                (Reg::RegTensor<int32_t>&)vregInputOne,
                                (Reg::RegTensor<int32_t>&)vregInputTwo);

// do int64 sub before gathermask
Reg::SubCarryOut(carryOut, vregInputLowerHalf, vregInputLowerHalf, vregLowerBoundLowerHalf,
                      pregSelect);
Reg::SubCarryOuts(carryOut, vregInputHigherHalf, vregInputHigherHalf, vregLowerBoundHigherHalf,
                       carryOut, pregSelect);

// gather mask
Reg::GatherMask<int32_t, Reg::GatherMaskMode::NO_STORE_REG>(
    vregGatherLowerHalf, (Reg::RegTensor<int32_t>&)vregInputLowerHalf, pregSelect);
Reg::GatherMask<int32_t, Reg::GatherMaskMode::NO_STORE_REG>(vregGatherHigherHalf,
                                                                      vregInputHigherHalf, pregSelect);
```

**要点**: int64 索引拆成两个 RegTensor<int32_t> 高低半处理；GatherMaskMode::NO_STORE_REG 只聚合不落盘以便后续运算；SubCarryOut+SubCarryOuts 链式传递借位完成 64 位减法。

### RegTensor 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 多类型 RegTensor 声明 + Cast/Compare/Mul 求 FP8 scale | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 模板 RegTensor<T> + LoadAlign/And/Max 求组内 expMax | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | RegTensor<float> 串联 reduceMax/scale/cast 量化链 | __aicore__ |
| dynamic_block_quant | And, Cast, CastTrait, CompareScalar, CreateMask | UpdateMask 动态掩码 + And/Max/ReduceMax 求块 absMax | __VEC_SCOPE__ |
| swiglu_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | BF16 指数 And/Max 双轴归约 + Cast/Select 舍入 | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | BF16→FP32 升精度 + 位拆分舍入 + 双 StoreAlign 存 scale/倒数 | __simd_vf__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | RegTraitNumOne 单矢量 Reg + subnormal 放大 + 归一化 sqrt 求模 | __aicore__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | per-channel min-max 仿射量化（VEC_SCOPE 入口） | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | And, Cast, CastTrait, Compare, CreateMask | BF16/half 分支 Cast 升精度 + 共享 exp 乘 + Interleave/Pack FP8 | __VEC_SCOPE__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | 大小交换 + subnormal + 归一化 sqrt 求模并还原 | __VEC_SCOPE__ |
| dynamic_mx_quant | And, Cast, CastTrait, Compare, CreateMask | half/bf16 分支 And 取指数 + invalid 兜底 + 循环 Max 累积 expMax | __VEC_SCOPE__ |
| dynamic_quant | Abs, Adds, Cast, CreateMask, DataCopy | RegTraitNumOne 标量化算 scale/offset + FIRST_ELEMENT 存标量 | __VEC_SCOPE__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | b16→FP32 升精度 + 位拆分舍入 + 双 DataCopy 存 scale/倒数 | __aicore__ |
| dynamic_mx_quant | And, CastTrait, CreateMask, DeInterleave, Duplicate | 双路 LoadAlign/DeInterleave + 指数归约 + StoreUnAlign 非对齐存储 | __VEC_SCOPE__ |
| sparse_slice | AR, ClearSpr, Compare, CreateMask, DataCopy | int64 拆高低半 + Compare/GatherMask 聚合 + SubCarryOut 带借位减 | __VEC_SCOPE__ |
