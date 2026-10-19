# Add

**页面ID:** atlasascendc_api_07_0356  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0356.html

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

Add指令根据mask对源操作数srcReg0、srcReg1进行按元素求和操作，将结果写入目的操作数dstReg。计算公式如下：

![](images/atlasascendc_api_07_0356_img_001.png)

若srcReg0，srcReg1输入转换为uint32_t类型相加时超出uint32_t最大值，在carry（存放进位的MaskReg寄存器）中对应位置每4bit设置1，否则写0。

#### 函数原型

- 计算结果不保留进位

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Add(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

- 计算结果保留进位

```
template <typename T = DefaultType, typename U>
__simd_callee__ inline void Add(MaskReg& carry, U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/half/float/bfloat16_t/uint64_t/int64_t/complex32/complex64 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING, mask未筛选的元素在dstReg中置零。- MERGING, 当前不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| carry | 输出 | 目的操作数。存放进位的MaskReg寄存器。 类型为MaskReg。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

dstReg和srcReg0/srcReg1可以为同一个RegTensor。

#### 调用示例

- 计算结果不保留进位

```
template <typename T>
__simd_vf__ inline void AddVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);

       
        AscendC::Reg::Add(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 计算结果保留进位

```
template <typename T>
static __simd_vf__ inline void AddVF(__ubuf__ T* dst0Addr, __ubuf__ T* dst1Addr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint16_t repeatTimes, uint32_t oneRepeatSize){

    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg0;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::MaskReg carry = AscendC::Reg::CreateMask<uint8_t>();
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Add(carry, dstReg0, srcReg0, srcReg1, mask);
        // 8*4B=32B align
        AscendC::Reg::StoreAlign<uint32_t, AscendC::Reg::MaskDist::DIST_NORM>(dst1Addr + i * 8, carry);
        AscendC::Reg::StoreAlign(dst0Addr + i * oneRepeatSize, dstReg0, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Add 实例

### 实例 1：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Add 调用次数**: 6
- **参数模式**: `T0_A1_M0_TYPEint8_t+uint8_t`（实参 1 个，类型: uint8_t, int8_t）
- **语义（待补充）**: 将 4 个 fp8 子部分（由 CAST_32_TO_80/82/81/83 产生的 fp8Part0~3）通过逐次 Add 以 uint8_t 类型累加合并到 fp8Part0，得到最终 fp8 输出后再 DataCopy 存储。

（行 1007-1038）

```cpp
if constexpr (IsSameType<xDtype, half>::value) {
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x0ZeroFP32, regA, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x0OneFP32, regA, maskAll);
    Reg::Cast<float, bfloat16_t, CAST_X_TO_FP32_ZERO>(
        scaleForMulFP32, (Reg::RegTensor<bfloat16_t>&)scaleForMulFP16, maskAll);
    Reg::Mul(x0ZeroFP32, x0ZeroFP32, scaleForMulFP32, maskAll);
    Reg::Mul(x0OneFP32, x0OneFP32, scaleForMulFP32, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x1ZeroFP32, regB, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x1OneFP32, regB, maskAll);
    Reg::Mul(x1ZeroFP32, x1ZeroFP32, scaleForMulFP32, maskAll);
    Reg::Mul(x1OneFP32, x1OneFP32, scaleForMulFP32, maskAll);
} else {
    Reg::Mul(regA, regA, (Reg::RegTensor<xDtype>&)scaleForMulFP16, maskAll);
    Reg::Mul(regB, regB, (Reg::RegTensor<xDtype>&)scaleForMulFP16, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x0ZeroFP32, regA, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x0OneFP32, regA, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x1ZeroFP32, regB, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x1OneFP32, regB, maskAll);
}
AscendC::Reg::Cast<y1Dtype, float, CAST_32_TO_80>(fp8Part0, x0ZeroFP32, maskAll);
AscendC::Reg::Cast<y1Dtype, float, CAST_32_TO_82>(fp8Part1, x0OneFP32, maskAll);
AscendC::Reg::Cast<y1Dtype, float, CAST_32_TO_81>(fp8Part2, x1ZeroFP32, maskAll);
AscendC::Reg::Cast<y1Dtype, float, CAST_32_TO_83>(fp8Part3, x1OneFP32, maskAll);
AscendC::Reg::Add((Reg::RegTensor<uint8_t>&)fp8Part0, (Reg::RegTensor<uint8_t>&)fp8Part0,
                       (Reg::RegTensor<uint8_t>&)fp8Part1, maskAllB8);
AscendC::Reg::Add((Reg::RegTensor<uint8_t>&)fp8Part0, (Reg::RegTensor<uint8_t>&)fp8Part0,
                       (Reg::RegTensor<uint8_t>&)fp8Part2, maskAllB8);
AscendC::Reg::Add((Reg::RegTensor<uint8_t>&)fp8Part0, (Reg::RegTensor<uint8_t>&)fp8Part0,
                       (Reg::RegTensor<uint8_t>&)fp8Part3, maskAllB8);
AscendC::Reg::DataCopy<uint8_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                            AscendC::Reg::StoreDist::DIST_NORM_B8>(
    y1Addr, (Reg::RegTensor<uint8_t>&)fp8Part0, dataLen, maskAllB8);
```

**要点**: ① Add 第一个参数同时作为目的和源（fp8Part0 自累加），符合"dstReg 与 srcReg 可为同一 RegTensor"约束；② 此处是 uint8_t 类型加法，用于 fp8 多片段拼接而非数值求和；③ 掩码使用 maskAllB8（按 8bit 元素全选）。

### 实例 2：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Add 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 非对称量化分支中先用 Div 求商 vregXDivScale，再用 Add(vreg16, vregXDivScale, vregDupOffset, preg2) 加上偏移量得到加偏后的量化值 vreg16。

（行 409-432）

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

**要点**: ① 4 参数形式 Add(dst, src0, src1, mask)，preg2 为谓词寄存器（MaskReg）控制有效元素；② 与 Adds（标量加）不同，Add 是两个 RegTensor 向量相加；③ 仅在 isSymmetrical==false 分支执行，对称量化直接用 Div 结果不加偏移。

### 实例 3：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **Add 调用次数**: 8
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 复数绝对值计算：complex32 分支用 Add 把实部平方与虚部平方求和得 vSumSq 再 Sqrt；通用分支用 Add 给指数位加偏置 vExpBias 并最终累加 a²+b²，实现 subnormal 归一化后的模长计算。

**片段 1** (行 103-160):

```cpp
if constexpr (std::is_same<U, complex32>::value) {
    preg2 = AscendC::Reg::CreateMask<uint16_t, AscendC::Reg::MaskPattern::ALL>();
    Reg::LoadAlign(vSrcReg0, srcAddr + i * vflen * 2);
    Reg::Cast<float, T, castTraitZero>(vA, vSrcReg0, preg2);
    Reg::Cast<float, T, castTraitOne>(vB, vSrcReg0, preg2);
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

    // 0的处理
    Reg::Select(vResult, vA, vResult, preg4);

    Reg::StoreAlign(dstAddr + i * vflen, vResult, preg);
}
```

**片段 2** (行 126-152):

```cpp
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

**要点**: ① Add 用于"平方和累加"（a²+b²），是 sqrt(a²+b²) 复数模长的核心步骤；② 多处 Add 操作 uint32_t 视图（位运算式指数偏置加法），通过 RegTensor<uint32_t>& 强转实现；③ 4 参数形式，preg 为全量掩码。

### 实例 4：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Add 调用次数**: 2
- **参数模式**: `T1_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 伪量化算子中两处使用 Add<float>：一处求 |min|+|max| 得 vregAbsSum 以判断 bothZero（全零兜底），另一处在反量化时将缩放结果加上 nudgedMin 偏置得到最终输出 vregOut。

**片段 1** (行 379-397):

```cpp
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
```

**片段 2** (行 440-459):

```cpp
AscendC::Reg::Min<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregClamped, vregX, vregNudgedMax, mask);
AscendC::Reg::Max<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregClamped, vregClamped, vregNudgedMin,
                                                               mask);
// shift = clamped - nudgedMin
AscendC::Reg::Sub<float>(vregShift, vregClamped, vregNudgedMin, mask);
// scaled = shift * invScaleSafe + 0.5
//        与 TF 一致：使用独立计算的 inv_scale = qRange/(max-min)，
//        而非 shift/scale（二次舍入误差）
AscendC::Reg::Mul<float>(vregScaled, vregShift, vregInvScaleSafe, mask);
AscendC::Reg::Adds<float>(vregScaled, vregScaled, 0.5f, mask);
// floor 语义：fp32 → int32 (CAST_FLOOR) → fp32 (UNKNOWN)
AscendC::Reg::Cast<int32_t, float, kCastFp32ToInt32Floor>(vregFlrInt, vregScaled, mask);
AscendC::Reg::Cast<float, int32_t, kCastInt32ToFp32>(vregFloored, vregFlrInt, mask);
// out = floored * scaleSafe + nudgedMin
AscendC::Reg::Mul<float>(vregOut, vregFloored, vregScaleSafe, mask);
AscendC::Reg::Add<float>(vregOut, vregOut, vregNudgedMin, mask);
// out *= bothZero（兜底：当 |min|+|max|==0 时 out=0）
AscendC::Reg::Mul<float>(vregOut, vregOut, vregBoth, mask);
// Store
AscendC::Reg::StoreAlign<float, AscendC::Reg::StoreDist::DIST_NORM_B32>(yAddr + i * vfLen32, vregOut, mask);
```

**要点**: ① 显式模板 Add<float>（4 参数 + mask），mask 控制有效元素；② Add 与 Adds 区别：Adds 是标量加，Add 是两个向量相加；③ 第一处 Add 用于条件判断前的数值合成，第二处用于反量化偏置叠加。

### 实例 5：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, Compare, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreDist, Sub
- **Add 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: MX 量化中用"进位法"实现四舍五入：Add 将舍入位 addValue 加到 BF16 绝对值 absMaxDim1 上，借助浮点尾数进位自动完成指数舍入，再 And 提取指数。

（行 984-1003）

```cpp
//    ReduceMax后8个绝对值max紧凑存储在位置0-7
//    使用addValueBit进位法: 将addValueBit加到完整BF16绝对值上，
//    通过尾数进位自动实现指数的四舍五入
// ============================================================

// 提取指数位 (仅用于INF/NAN、零值、subnormal检查)
Reg::And(expOnly, absMaxDim1, expMaskBF16, maskAll);
// INF/NAN检查: 指数全1
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expOnly, expMaskBF16, maskAll);
// 零值检查
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expOnly, zero, maskAll);
// subnormal检查: 指数 < FP4_E2M1_BF16_MAX_EXP (注意使用LT，不是LE)
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expOnly, maxExpValue, maskAll);

// addValueBit进位: 将addValueBit加到完整BF16绝对值上
Reg::Add(addedVal, absMaxDim1, addValue, maskAll);
// 从进位后的结果中提取指数
Reg::And(addedVal, addedVal, expMaskBF16, maskAll);
// subnormal场景: 使用maxExpValue (FP4_E2M1_BF16_MAX_EXP)
Reg::Select<uint16_t>(addedVal, maxExpValue, addedVal, invalidDataMask);
```

**要点**: ① Add 用于位级进位技巧（不是常规数值加），借助浮点尾数进位实现 round；② 操作前已用 Compare 检查 INF/NAN/零值/subnormal 并以 Select 兜底；③ maskAll 全量掩码，4 参数形式。

### 实例 6：dynamic_mx_quant::Reg::Select

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CreateMask, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, Max, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, Sub
- **Add 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: float 类型 MX 量化中，构造舍入偏置 roundBiasU32（掩码最低位 +0x7FFF），用 Add 把它加到 maxU32 上实现 round-to-nearest，再 ShiftRights 右移得到量化指数。

（行 613-623）

```cpp
if constexpr (IsSame<xDtype, float>::value) {
    Reg::ShiftRights(roundBiasU32, maxU32, FP32_PACK_SHR_NUM, pregAll32);
    Reg::And(roundBiasU32, roundBiasU32, oneU32, pregAll32);
    Reg::Adds(roundBiasU32, roundBiasU32, 0x7FFF, pregAll32);
    Reg::Add(maxU32, maxU32, roundBiasU32, pregAll32);
    Reg::ShiftRights(maxU32, maxU32, FP32_PACK_SHR_NUM, pregAll32);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(maxU16, maxU32);
    Reg::And(expMaxU16, maxU16, maxEleU16, pregAll16);
} else {
    Reg::And(expMaxU16, maxU16, maxEleU16, pregAll16);
}
```

**要点**: ① Add(dst, src0, src1, mask) 中 dst==src0（maxU32 自累加），符合同 RegTensor 约束；② 与 Adds 配合完成"加偏置再缩放"的整数舍入；③ pregAll32 全量 32 位掩码。

### 实例 7：cdist::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, CreateMask, Duplicate, Exp, ExpSpecificMode, LoadAlign, Log, LogSpecificMode, MaskMergeMode, MaskPattern, MaskReg, Muls, ReduceSum, RegTensor, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore, UpdateMask
- **Add 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: cdist 距离计算中，每个分块用 ReduceSum 求块内和 sumReg，再用 Add 累加到 dstReg（maskOne 标量掩码），循环结束后对累加结果做 Log/Exp 得到 p-范数距离。

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

**要点**: ① Add(dstReg, dstReg, sumReg, maskOne) 是"标量累加"，maskOne 仅选 1 个元素做归约和累加；② 主块用 maskAll、尾块用 maskTail，但累加都用 maskOne；③ 与 Sub/Abs/Log/Exp/ReduceSum 组合实现闵可夫斯基距离。

### 实例 8：arg_max_with_value::HardEvent::V_MTE3

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, MaskPattern, MaskReg, Mul, PostLiteral, ReduceMax, ReduceMin, RegTensor, RegTraitNumTwo, Select, UnalignReg, UpdateMask
- **Add 调用次数**: 3
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: argmax 算子中 Add 用于两类索引计算：一是循环内 Add(level1, level1, vregIndicesAdd1) 递增候选索引；二是末尾用两次 Add 把相对索引回溯为绝对索引（idx = idx + idxAdd + startR）。

**片段 1** (行 229-240):

```cpp
for (uint16_t r = 0; r < loopTime; r++) {
    AscendC::Reg::DataCopyUnAlign<T1, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(value1, uSrc, (__local_mem__ T1*&)src, VL);
    // 微指令 AscendC::Reg::Duplicate(level1, r + 1, fullMask);
    Add(level1, level1, vregIndicesAdd1, fullMask);
    if constexpr (isMin) {
        AscendC::Reg::Compare<T1, CMPMODE::LE>(cmpMask, value0, value1, fullMask);
    } else {
        AscendC::Reg::Compare<T1, CMPMODE::GE>(cmpMask, value0, value1, fullMask);
    }
    AscendC::Reg::Select(value0, value0, value1, cmpMask);
    AscendC::Reg::Select(level0, level0, level1, cmpMask);
}
```

**片段 2** (行 224-273):

```cpp
for (uint16_t a = 0; a < dimA; a++) {
    AscendC::Reg::DataCopyUnAlign<T1, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(value0, uSrc, (__local_mem__ T1*&)src, offset1);
    AscendC::Reg::Duplicate(level0, VALUE_ZERO, fullMask);
    AscendC::Reg::Duplicate(level1, VALUE_ZERO, fullMask);
    // 载入i+1片数据，初始化i+1片索引，比较 i and i+1
    for (uint16_t r = 0; r < loopTime; r++) {
        AscendC::Reg::DataCopyUnAlign<T1, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(value1, uSrc, (__local_mem__ T1*&)src, VL);
        // 微指令 AscendC::Reg::Duplicate(level1, r + 1, fullMask);
        Add(level1, level1, vregIndicesAdd1, fullMask);
        if constexpr (isMin) {
            AscendC::Reg::Compare<T1, CMPMODE::LE>(cmpMask, value0, value1, fullMask);
        } else {
            AscendC::Reg::Compare<T1, CMPMODE::GE>(cmpMask, value0, value1, fullMask);
        }
        AscendC::Reg::Select(value0, value0, value1, cmpMask);
        AscendC::Reg::Select(level0, level0, level1, cmpMask);
    }

    // 载入尾快，与主块比较
    for (uint16_t r = 0; r < tailLoop; r++) {
        AscendC::Reg::DataCopyUnAlign<T1, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(value1, uSrc, (__local_mem__ T1*&)src, offsetTail);
        AscendC::Reg::Duplicate(level1, mainLoop, fullMask);
        if constexpr (isMin) {
            AscendC::Reg::Compare<T1, CMPMODE::LT>(cmpMask, value1, value0, tailMask);
        } else {
            AscendC::Reg::Compare<T1, CMPMODE::GT>(cmpMask, value1, value0, tailMask);
        }
        AscendC::Reg::Select(value0, value1, value0, cmpMask);
        AscendC::Reg::Select(level0, level1, level0, cmpMask);
    }

    // 输出最终值 + 相对索引
    if constexpr (isMin) {
        AscendC::Reg::ReduceMin(valueResult, value0, fullMask);
    } else {
        AscendC::Reg::ReduceMax(valueResult, value0, fullMask);
    }
    AscendC::Reg::DataCopyUnAlign<T1, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        (__local_mem__ T1*&)valueDst, valueResult, uValue, 1);
    // 相对索引回溯绝对索引 idx = idx + level_Y[idx] * A
    AscendC::Reg::Duplicate(valueResult, valueResult, fullMask);
    AscendC::Reg::Compare<T1, CMPMODE::EQ>(cmpMask, valueResult, value0, fullMask);
    AscendC::Reg::ReduceMin(indexResult, level0, cmpMask);
    AscendC::Reg::Mul(indexMulResult, helpIndex, indexResult, fullMask);
    AscendC::Reg::DeInterleave(indexResult, indexAddResult, indexMulResult, helpIndex);
    Add(indexResult, indexResult, indexAddResult, oneMask);
    Add(indexResult, indexResult, vregIndicesAddStartR, oneMask);
    AscendC::Reg::DataCopyUnAlign<T2, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        (__local_mem__ T2*&)indexDst, (AscendC::Reg::RegTensor<T2> &)indexResult, uIndex, 1);
}
```

**要点**: ① Add 用于整数索引递增/累加，操作索引寄存器而非数据；② oneMask/fullMask 区分标量级与向量级累加；③ 与 DeInterleave/Mul/ReduceMin 组合实现"按值定位索引"。

### 实例 9：max_pool_with_argmax::MaxPoolWithArgMaxGatherImpl

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, Compare, CreateMask, DataCopyGather, DataCopyScatter, Duplicate, MaskNot, MaskOr, MaskPattern, MaskReg, MaskUnPack, Muls, Pack, RegTensor, Select, UpdateMask
- **Add 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: max_pool_with_argmax 中用 Add 将三维索引合并为一维：先 Muls(argmaxRes, argmaxHRes, wInput) 得 h*wInput，Add 加 argmaxWRes，再 Muls*cInput 后 Add 加 argmaxCStart，得到 flatten 后的输出偏移。

（行 130-153）

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

**要点**: ① Add 用于索引合成的逐维累加（h*wInput + w 再 *cInput + cStart）；② 配合 Adds 修正 padding 偏移（IS_PAD 分支）；③ computeT2 为该数据类型的全量谓词掩码。

### 实例 10：sinh::SinhCustomVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, CompareScalar, DataCopy, Div, DivSpecificMode, Duplicate, Exp, MaskMergeMode, MaskReg, Mul, Neg, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **Add 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: sinh 用 Taylor 多项式近似：先用 Adds 做 Horner 法求 P(x²)，再 Add(reg_poly, reg_x, reg_poly) 计算 x + x³·P(x²) 得到 Taylor 主项。

（行 95-115）

```cpp
AscendC::Reg::Mul(reg_x2, reg_x, reg_x, mask);

// Horner: P(x2) = ((c5 * x2 + c4) * x2 + c3) * x2 + c2
AscendC::Reg::Duplicate(reg_poly, c5);
AscendC::Reg::Mul(reg_poly, reg_poly, reg_x2, mask);     // c5*x2
AscendC::Reg::Adds(reg_poly, reg_poly, c4, mask);        // + c4
AscendC::Reg::Mul(reg_poly, reg_poly, reg_x2, mask);     // * x2
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
```

**要点**: ① Add 完成 Taylor 展开的"x + 高阶项"合成；② 与 Adds（标量 Horner 系数累加）配合，Add 只做最后的向量相加；③ mask 为该数据类型全量谓词。

### 实例 11：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Compare, CreateMask, DataCopy, DeInterleave, Duplicate, LoadDist, LocalMemBar, MaskAnd, MaskPattern, MaskReg, MaskSel, MemType, ReduceSum, RegTensor, Select, StoreDist, UpdateMask
- **Add 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: sparse_slice 中循环对每块 mask 数据 ReduceSum 求非零个数，再用 Add 累加到 vregCounterIn 得到累计计数，最后 DataCopy 写出。

（行 522-530）

```cpp
for (uint16_t loopIndex = 0; loopIndex < loopNum; loopIndex++) {
    pregIndicesB32 = Reg::UpdateMask<int32_t>(sreg0);
    Reg::DataCopy<int8_t, Reg::LoadDist::DIST_UNPACK4_B8>(
        vregInMask, (__ubuf__ int8_t*)(maskUbAddr + loopIndex * vl));
    Reg::ReduceSum<int32_t>(reduceResult, (Reg::RegTensor<int32_t>&)vregInMask, pregIndicesB32);
    Reg::Add(vregCounterIn, vregCounterIn, reduceResult, pregB32First);
}
Reg::DataCopy<int32_t, Reg::StoreDist::DIST_NORM>((__ubuf__ int32_t*)(counterUbAddr), vregCounterIn,
                                                            pregB32First);
```

**要点**: ① Add(dst, dst, src) 自累加统计计数，pregB32First 为 32 位首元素标量掩码；② 与 UpdateMask/ReduceSum 组合实现稀疏计数；③ 操作 int32_t 视图。

### 实例 12：cumsum::Reg::Adds

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Arange, Copy, CreateMask, DataCopyGather, DataCopyScatter, Div, Duplicate, LocalMemBar, MaskPattern, MaskReg, MemType, Muls, RegTensor, Sub, UpdateMask
- **Add 调用次数**: 12
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: cumsum 前缀和算子中 Add 高频使用（12 次）：一处构造 gather 索引（gIdx = i%k + i//k*n*k），另一处在 DataCopyGather 后 Add(yDst, yDst, xSrc) 完成前缀和的逐块累加。

**片段 1** (行 715-733):

```cpp
Reg::RegTensor<RangeType> tmp1;
Reg::RegTensor<RangeType> tmp2;
Reg::RegTensor<RangeType> gComIdx;
Reg::MaskReg idxMask = Reg::CreateMask<RangeType, Reg::MaskPattern::ALL>();

// get gather index: i - i//k*k + i//k*n*k
Reg::Arange(gIdx, (RangeType)0);
Reg::Duplicate(tmp1, (RangeType)rightALen);
Reg::Div(tmp1, gIdx, tmp1, idxMask);
Reg::Muls(tmp2, tmp1, splitRASize, idxMask);
Reg::Muls(tmp1, tmp1, (RangeType)rightALen, idxMask); // tmp1 is i//k*k
Reg::Sub(gIdx, gIdx, tmp1, idxMask);
// the index result format is: (0, 1, 2, 0, 1, 2, 0, 1, 2, ...), concat last loop backup result
Reg::Copy(gComIdx, gIdx); // backup gComIdx
// the index result format is: (0, 1, 2, 6, 7, 8, ...)
Reg::Add(gIdx, gIdx, tmp2, idxMask); // backup gIdx

// get last loop result
Reg::RegTensor<T> bakSrc;
```

**片段 2** (行 767-782):

```cpp
for (uint16_t srIdx = 0; srIdx < sndRLpCnt; srIdx++) {
    Reg::Adds(gIdx, gIdx, phs2LpOffset, idxMask);
    Reg::Adds(sIdx, sIdx, phs2LpOffset, idxMask);
    Reg::DataCopyGather(
        (Reg::RegTensor<CastType>&)yDst, dstPtr, (Reg::RegTensor<IdxType>&)gIdx, comMask);
    Reg::Add(yDst, yDst, xSrc, comMask);
    Reg::DataCopyScatter(dstPtr, yDst, (Reg::RegTensor<IdxType>&)sIdx, comMask);
}
Reg::Adds(gIdx, gIdx, phs2TLpOffset, idxMask);
Reg::Adds(sIdx, sIdx, phs2TLpOffset, idxMask);
Reg::DataCopyGather(
    (Reg::RegTensor<CastType>&)yDst, dstPtr, (Reg::RegTensor<IdxType>&)gIdx, sndLpLeftMask);
Reg::Add(yDst, yDst, xSrc, sndLpLeftMask);
Reg::DataCopyScatter(dstPtr, yDst, (Reg::RegTensor<IdxType>&)sIdx, sndLpLeftMask);
Reg::Adds(gComIdx, gComIdx, curBegAddrBase, idxMask);
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
```

**要点**: ① Add 既用于索引变换又用于数据前缀累加，是 cumsum 核心算子；② idxMask/comMask 为不同掩码控制有效元素；③ 与 Arange/Div/Muls/DataCopyGather 组合实现分段前缀和。

### 实例 13：gather_nd::FixIndicesVfCoreVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, Adds, Compare, CreateAddrReg, CreateMask, DataCopy, DataCopyGather, Duplicate, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Muls, RegTensor, RegTraitNumTwo, UpdateMask
- **Add 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: gather_nd 索引计算：循环每维 Muls(curIndicesReg, curIndicesReg, strideDimKSize) 得该维偏移，Add 累加到 indicesResReg 得到多维 flatten 索引，供 DataCopyGather 使用。

（行 122-154）

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
```

**要点**: ① Add 用于多维索引的逐维偏移累加（indicesResReg += idx_k * stride_k）；② 来源类型 __simd_vf__（与多数 __VEC_SCOPE__ 不同）；③ preg 为该上下文全量谓词。

### 实例 14：mish::MishCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Axpy, Cast, CompareScalar, DataCopy, Div, Exp, LoadDist, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Add 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: mish 激活函数中 Add 合成分母：vregInputNegDenominator = (2e^-x+1) + 2e^-2x，再 Div 得到 softplus 项，与 x 相乘得 mish(x)=x*tanh(softplus(x))。

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

**要点**: ① Add 合成两个指数项相加分母，是 mish 公式的关键步骤；② 与 Exp/Muls/Adds/Div 组合；③ mask 全量谓词，4 参数形式。

### 实例 15：top_k_v2::ReverseInputData

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, DeInterleave, Duplicate, Histograms, HistogramsBinType, HistogramsType, Interleave, MaskPack, MaskReg, PostLiteral, RegTensor, ShiftRights, Sub, UpdateMask
- **Add 调用次数**: 24
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: top_k_v2 基数排序中 Add 高频使用（24 次）：将每个 block 的 exclusive sum（excusiveSumXB64A/B）累加到全局 exclusive sum（excusiveSumGlobalX），实现跨 block 的前缀和合并。

**片段 1** (行 115-115):

```cpp
if constexpr (IsSameType<T_INDEX, int32_t>::value) {
```

**片段 2** (行 170-195):

```cpp
Reg::DataCopy<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    excusiveSumGlobalZeroB, blockExcusivePtrRead, ONE_TIMES_B64_NUM);
Reg::DataCopy<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    excusiveSumGlobalOneA, blockExcusivePtrRead, ONE_TIMES_B64_NUM);
Reg::DataCopy<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    excusiveSumGlobalOneB, blockExcusivePtrRead, ONE_TIMES_B64_NUM);
Reg::DataCopy<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    excusiveSumGlobalTwoA, blockExcusivePtrRead, ONE_TIMES_B64_NUM);
Reg::DataCopy<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    excusiveSumGlobalTwoB, blockExcusivePtrRead, ONE_TIMES_B64_NUM);
Reg::DataCopy<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    excusiveSumGlobalThreeA, blockExcusivePtrRead, ONE_TIMES_B64_NUM);
Reg::DataCopy<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    excusiveSumGlobalThreeB, blockExcusivePtrRead, ONE_TIMES_B64_NUM);
// add block ans to global excusive
Reg::Add(excusiveSumGlobalZeroA, excusiveSumGlobalZeroA, excusiveSumZeroB64A, predicateDefault);
Reg::Add(excusiveSumGlobalZeroB, excusiveSumGlobalZeroB, excusiveSumZeroB64B, predicateDefault);
Reg::Add(excusiveSumGlobalOneA, excusiveSumGlobalOneA, excusiveSumOneB64A, predicateDefault);
Reg::Add(excusiveSumGlobalOneB, excusiveSumGlobalOneB, excusiveSumOneB64B, predicateDefault);
Reg::Add(excusiveSumGlobalTwoA, excusiveSumGlobalTwoA, excusiveSumTwoB64A, predicateDefault);
Reg::Add(excusiveSumGlobalTwoB, excusiveSumGlobalTwoB, excusiveSumTwoB64B, predicateDefault);
Reg::Add(excusiveSumGlobalThreeA, excusiveSumGlobalThreeA, excusiveSumThreeB64A, predicateDefault);
Reg::Add(excusiveSumGlobalThreeB, excusiveSumGlobalThreeB, excusiveSumThreeB64B, predicateDefault);
// vsts to global
Reg::DataCopy<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    blockExcusivePtrWrite, excusiveSumGlobalZeroA, ONE_TIMES_B64_NUM, predicateDefault);
```

**要点**: ① Add(dst, dst, src) 自累加实现 block 间 exclusive sum 合并，是基数排序散列定位的核心；② predicateDefault 为默认全量谓词；③ 操作 int64_t 索引，与 Histograms/DeInterleave 组合。

### Add 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| swiglu_backward_mx_quant_with_dual_axis | Adds, And, Arange, Cast | fp8 多片段 uint8_t 加法合并（dst 自累加拼接 4 个 CAST 子部分） | __VEC_SCOPE__ |
| dynamic_quant | Abs, Adds, Cast, CreateMask | 非对称量化加偏移：Div 求商后 Add 偏移量得量化值 | __aicore__ |
| complex_abs | Abs, Cast, CastTrait, Compare | 复数模长平方和 a²+b² 累加 + 指数偏置 uint32_t 视图加法 | __aicore__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Adds, Cast, Compares | Add<float> 求 |min|+|max| 判零 + 反量化加 nudgedMin 偏置 | __VEC_SCOPE__ |
| dynamic_mx_quant_with_dual_axis | And, Cast, Compare, CreateMask | 进位法四舍五入：Add 舍入位到 BF16 绝对值借尾数进位 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait | 构造 roundBias 后 Add 自累加实现 round-to-nearest | __VEC_SCOPE__ |
| cdist | Abs, CreateMask, Duplicate, Exp | 分块 ReduceSum 后 Add 标量累加得距离和（maskOne） | __VEC_SCOPE__ |
| arg_max_with_value | Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost | 索引递增与绝对索引回溯的整数 Add 累加 | __VEC_SCOPE__ |
| max_pool_with_argmax | Adds, Cast, Compare, CreateMask | 三维索引逐维 Add 合并为一维 flatten 偏移 | __aicore__ |
| sinh | Abs, Adds, CompareScalar, DataCopy | Taylor 展开 x + x³·P(x²) 的向量 Add 合成 | __aicore__ |
| sparse_slice | Compare, CreateMask, DataCopy, DeInterleave | ReduceSum 后 Add 自累加统计稀疏非零计数 | __VEC_SCOPE__ |
| cumsum | Adds, Arange, Copy, CreateMask | 索引变换 + 前缀和逐块 Add 累加（高频 12 次） | __VEC_SCOPE__ |
| gather_nd | AddrReg, Adds, Compare, CreateAddrReg | 多维索引逐维偏移 Add 累加得 flatten 索引 | __simd_vf__ |
| mish | Adds, Axpy, Cast, CompareScalar | 合成 mish 分母 (2e^-x+1)+2e^-2x 的指数项 Add | __aicore__ |
| top_k_v2 | CreateMask, DataCopy, DeInterleave, Duplicate | 基数排序 block 间 exclusive sum 自累加合并（高频 24 次） | __VEC_SCOPE__ |
