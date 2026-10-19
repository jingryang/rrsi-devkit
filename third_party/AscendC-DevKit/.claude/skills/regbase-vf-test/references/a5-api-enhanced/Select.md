# Select

**页面ID:** atlasascendc_api_07_0337  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0337.html

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

给定两个源操作数src0和src1，根据mask的比特位值选取元素，得到目的操作数dst。选择的规则为：当mask的比特位是1时，从src0中选取对应位置的数，比特位是0时从src1选取对应位置的数。

#### 函数原型

```
__simd_callee__ inline void Select(MaskReg& dst, MaskReg& src0, MaskReg& src1, MaskReg& mask);
```

#### 参数说明

**表1 **参数说明

| 参数名 | 描述 |
| --- | --- |
| dst | 目的操作数。 |
| src0 | 源操作数。 |
| src1 | 源操作数。 |
| mask | 指示选择src0或src1。 |

#### 约束说明

无

#### 调用示例

```
template <typename T>
__simd_vf__ inline void SelectVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg maskFull = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg maskNone = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALLF>();
    AscendC::Reg::MaskReg newMask;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::Select(newMask, maskFull, maskNone, maskFull);
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Adds(srcReg, srcReg, 0, newMask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Select 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Select 调用次数**: 5
- **参数模式**: `T1_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: int32_t, uint32_t）
- **语义（待补充）**: 在 dynamic_mx_quant 非尾轴优化路径中，Select 按舍入掩码在「指数+1」与「原指数」间逐位选择，再用两次 Select 把 inf/nan、零值的异常指数替换为特殊值，最终拼成 E8M0 的 mxScale。

（行 512-544）

```cpp
// 右移获取指数位
Reg::ShiftRights(expFP32RegTensor, maxFP32RegTensor, FP32_SHR_NUM, mask);
// And获取尾数位
Reg::And(manFP32RegTensor, maxFP32RegTensor, manFP32RegTensor, mask);

Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32RegTensor, FP32_NUMBER_ZERO, mask);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32RegTensor, FP32_NUMBER_254, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32RegTensor, FP32_NUMBER_ZERO, p0);

Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, expFP32RegTensor, FP32_NUMBER_ZERO, mask);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32RegTensor, FP32_NUMBER_HALF, p1);

Reg::MaskOr(p0, p0, p1, mask);
Reg::Adds(extractExpRegTensor, expFP32RegTensor, 1, mask);
// 根据情况选择指数位是否加一
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, expFP32RegTensor, p0);

Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, invMaxRegTensor, infMask);
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, fp32ZeroRegTensor, zeroMask);
Reg::Pack(tmp16RegTensor, extractExpRegTensor);
Reg::Pack(outZero, tmp16RegTensor);
// 搬出mxScale
Reg::DataCopyUnAlign(mxScaleAddr, outZero, u1, dataLen);
Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);

// 求1/scale
Reg::ShiftLefts(extractExpRegTensor, extractExpRegTensor, FP32_SHR_NUM, mask);
Reg::Sub(extractExpRegTensor, scaleBias, extractExpRegTensor, mask);
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, nan, infMask);
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, fp32ZeroRegTensor, zeroMask);

Reg::Cast<bfloat16_t, float, castTraitFp32ToBf16>((Reg::RegTensor<bfloat16_t>&)reversedShareExpRegTensor,
                                                  (Reg::RegTensor<float>&)extractExpRegTensor, mask);
```

**要点**: 1) 第四参数为 MaskReg，比特位 1→src0、0→src1 逐元素选择，常与 CompareScalar/MaskOr 产出的 p0 配合；2) 典型三连用法：先选舍入结果、再选 inf/nan、最后选 zero，形成正常→异常→零的优先级覆盖链；3) 显式 Select<uint32_t> 保证指数位按 uint32 比特拷贝不丢精度。


### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Select 调用次数**: 12
- **参数模式**: `T1_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: int32_t, uint32_t）
- **语义（待补充）**: grouped_dynamic_mx_quant 中先用 CompareScalar+MaskAnd+MaskXor 构造「需向上取整」掩码 p1，再用 Select 在「指数+1」与「原指数」间选择，随后覆盖 inf/nan、zero，并对 1/scale 重复同一异常值覆盖模板。

（行 591-620）

```cpp
// 6. 条件向上取整
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, expAndreShareExpFP32RegTensor, NUMBER_ZERO, preMaskScale);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p2, expAndreShareExpFP32RegTensor, NUMBER_TWO_FIVE_FOUR,
                                          preMaskScale);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p3, manAndmxScaleFP32RegTensor, NUMBER_ZERO, preMaskScale);
Reg::MaskAnd(p1, p1, p2, preMaskScale);
Reg::MaskAnd(p1, p1, p3, preMaskScale);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p2, expAndreShareExpFP32RegTensor, NUMBER_ZERO, preMaskScale);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p3, manAndmxScaleFP32RegTensor, NUMBER_HALF, preMaskScale);
Reg::MaskAnd(p2, p2, p3, preMaskScale);
Reg::MaskXor(p1, p1, p2, preMaskScale);
Reg::Adds(expMaxAndAddOneFP32RegTensor, expAndreShareExpFP32RegTensor, 1, preMaskScale);
Reg::Select(manAndmxScaleFP32RegTensor, expMaxAndAddOneFP32RegTensor, expAndreShareExpFP32RegTensor, p1);
// 7. 异常值处理
Reg::Select<uint32_t>(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, fp8NanRegTensor32, infMask);
Reg::Select<uint32_t>(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, zeroRegTensor32, zeroMask);
// 8. 输出 mxscale（E8M0）
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(expScaleMxYZeroRegTensor,
                                                        manAndmxScaleFP32RegTensor);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(outZeromxScaleFp8, expScaleMxYZeroRegTensor);
Reg::StoreUnAlign(mxScaleAddr, outZeromxScaleFp8, u1, vfNum32);
Reg::StoreUnAlignPost(mxScaleAddr, u1, 0);
// 9. 求 1/scale
Reg::ShiftLefts(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, SHR_NUM_FOR_BF16, preMaskScale);
Reg::Sub(expAndreShareExpFP32RegTensor, biasRegTensor32, manAndmxScaleFP32RegTensor, preMaskScale);
Reg::Select<uint32_t>(expAndreShareExpFP32RegTensor, expAndreShareExpFP32RegTensor, nanRegTensor32,
                      infMask);
Reg::Select<uint32_t>(expAndreShareExpFP32RegTensor, expAndreShareExpFP32RegTensor, zeroRegTensor32,
                      zeroMask);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(expMaxreShareExpFP16YOneRegTensor,
```

**要点**: 1) Select 与 MaskXor 配合实现「尾数>0.5 且指数非零时进位」的条件选择；2) 同一寄存器既作 dst 又作 src0，实现条件成立则改、不成立则保持的原地更新；3) scale 与 1/scale 两段复用同一套 Select 异常值覆盖模板。


### 实例 3：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Select 调用次数**: 6
- **参数模式**: `T1_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: int32_t, uint32_t）
- **语义（待补充）**: swiglu_backward 双轴场景下，Reg::Select 从「指数+1」与「原指数」取舍入结果并覆盖 inf/nan、zero，再用 Gather+DataCopy 把 scale 与 1/scale 按索引交错搬出，实现双轴 mxScale 输出。

（行 943-989）

```cpp
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, (Reg::RegTensor<uint32_t>&)regB, EXP_254,
                                               maskAll32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, (Reg::RegTensor<uint32_t>&)regU16_1,
                                               static_cast<uint32_t>(0), maskAll32);
Reg::MaskAnd(p0, p0, p1, maskAll32);
Reg::MaskAnd(p0, p0, p2, maskAll32);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, (Reg::RegTensor<uint32_t>&)regB,
                                               static_cast<uint32_t>(0), maskAll32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, (Reg::RegTensor<uint32_t>&)regU16_1, HALF_FOR_MAN,
                                               maskAll32);
Reg::MaskAnd(p1, p1, p2, maskAll32);
Reg::MaskOr(p0, p0, p1, maskAll32);

Reg::Adds(expAddOne32, (Reg::RegTensor<uint32_t>&)regB, 1, maskAll32);
Reg::Select(extractExp, expAddOne32, (Reg::RegTensor<uint32_t>&)regB, p0);
Reg::Select<uint32_t>(extractExp, extractExp, fp8NanReg32, cmpResult);
Reg::Select<uint32_t>(extractExp, extractExp, zeroReg32, zeroMask);

Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(regU16_2, extractExp);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(scale8Reg, regU16_2);

Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, maskAll32);
Reg::Sub(halfScale, scaleBiasReg, extractExp, maskAll32);
Reg::Select<uint32_t>(halfScale, halfScale, nanReg32, cmpResult);
Reg::Select<uint32_t>(halfScale, halfScale, zeroReg32, zeroMask);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(regU16_2, halfScale);

// 8: 一个RegTensor可容纳64个fp32元素，每次循环处理8个元素
for (uint16_t k = 0; k < 8; k++) {
    // 8: scale1的搬运, 每次循环索引值的更新步长为8
    Reg::Arange(extractIdx, static_cast<int8_t>(k * 8));
    Reg::Gather(scale8Row, scale8Reg, (Reg::RegTensor<uint8_t>&)extractIdx);
    Reg::Gather(scale8Swapped, scale8Row, (Reg::RegTensor<uint8_t>&)indexShiftS8);

    // 32: 偏移32字节
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScaleA1Addr, scale8Row, 32,
                                                                         maskReduceB8);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScaleA2Addr, scale8Swapped, 32,
                                                                         maskReduceB8);

    // 16: 1/scale1的搬运, 每次循环索引值的更新步长为16
    Reg::Arange(extractIdx, static_cast<int8_t>(k * 16));
    Reg::Gather((Reg::RegTensor<uint8_t>&)recip16Row, (Reg::RegTensor<uint8_t>&)regU16_2,
                     (Reg::RegTensor<uint8_t>&)extractIdx);
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScale1ReciprocalAddr,
                                                                          recip16Row, 16, maskReduceB16);
}
```

**要点**: 1) 使用 Reg:: 前缀调用 Select，与 Reg:: 等价，第四参数为掩码 p0/cmpResult/zeroMask；2) Select 后接 Pack<uint16_t,uint32_t,LOWEST> 把 uint32 指数压成 uint16 再 uint8 的 E8M0 字节；3) Arange+Gather 按 k*8/k*16 步长取数，Select 产出的 scale 是 Gather 重排的源。


### 实例 4：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskPattern, MaskReg, Max, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, ShiftRights, Sub, UnalignReg, UpdateMask
- **Select 调用次数**: 7
- **参数模式**: `T1_A4_M1_TYPEint16_t+uint16_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: int16_t, uint16_t）
- **语义（待补充）**: half/bf16 路径下，Select<uint16_t> 先把无效数据的指数替换为 maxEle，再在 1/scale 计算中依次覆盖 inf→nan、zero→0、special→specialExp，处理 BF16 域倒数。

**片段 1** (行 238-246):

```cpp
if constexpr (IsSame<T, half>::value) {
    Reg::And(xSelectRegTensor, (Reg::RegTensor<uint16_t>&)x, invalidMaskFp16, pnumMask);
    Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask, xSelectRegTensor, invalidMaskFp16, pnumMask);
    Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16RegTensor, x, pnumMask);
    Reg::And(exp, (Reg::RegTensor<uint16_t>&)xBF16RegTensor, maxEle, pnumMask);
    Reg::Select<uint16_t>(exp, exp, maxEle, invalidDataMask);
} else if constexpr (IsSame<T, bfloat16_t>::value) {
    Reg::And(exp, (Reg::RegTensor<uint16_t>&)x, maxEle, pnumMask);
}
```

**片段 2** (行 291-309):

```cpp
Reg::ShiftRights(mxScaleInt, expMax, BF16_SHR_NUM, mask);
Reg::Select<uint16_t>(mxScaleInt, mxScaleInt, fp8Nan, infMask);
Reg::Pack(mxScale, mxScaleInt);
Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, dataLen);
Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);

// 求1/scale
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expMax, zero, mask);
Reg::Compare<uint16_t, CMPMODE::EQ>(specialDataMask, expMax, bias, mask);
Reg::Sub(reversedShareExpRegTensor, bias, expMax, mask);
Reg::Select<uint16_t>(reversedShareExpRegTensor, reversedShareExpRegTensor, nan, infMask);
Reg::Select<uint16_t>(reversedShareExpRegTensor, reversedShareExpRegTensor, zero, zeroMask);
Reg::Select<uint16_t>(reversedShareExpRegTensor, specialExp, reversedShareExpRegTensor, specialDataMask);

auto scaleAddr = maxExpAddr;
for (uint16_t i = 0; i < rowsSingleLoop; i++) {
    Reg::DataCopyUnAlign(scaleAddr, reversedShareExpRegTensor, u1, dataLen);
    Reg::DataCopyUnAlignPost(scaleAddr, u1, 0);
}
```

**要点**: 1) 模板参数显式写 Select<uint16_t>，因 half/bf16 指数位按 uint16 比特操作；2) 第四参数既可为 MaskReg 变量也可为 Compare 直接产出的掩码；3) specialDataMask 分支用 Select 选 specialExp，是 MX 量化指数等于 bias 的特殊值专属处理。


### 实例 5：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, Interleave, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, RegTensor, SatMode, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Select 调用次数**: 14
- **参数模式**: `T1_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: dynamic_mx_quant 非尾轴主路径中，AscendC::Reg::Select<calcTypeInt> 用于 1/scale 的异常值覆盖：先按 infMask 选 nan，再按 specialDataMask 选 specialExp，并配合 Duplicate 处理尾轴对齐。

**片段 1** (行 660-679):

```cpp
    AscendC::Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, vfLen);
    AscendC::Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);
    AscendC::Reg::ShiftLefts((Reg::RegTensor<uint16_t>&)expFP32Reg, (Reg::RegTensor<uint16_t>&)expFP32Reg,
                             BF16_SHR_NUM, pregAll16);
    AscendC::Reg::Compare<calcTypeInt, CMPMODE::NE>(infMask, (Reg::RegTensor<uint16_t>&)expFP32Reg,
                                                    infForXReg, pregAll16);
    AscendC::Reg::Compare<calcTypeInt, CMPMODE::EQ>(specialDataMask, (Reg::RegTensor<uint16_t>&)expFP32Reg,
                                                    biasReg, pregAll16);
    AscendC::Reg::Sub(scaleReprocal, biasReg, (Reg::RegTensor<uint16_t>&)expFP32Reg, pregAll16);
    AscendC::Reg::Select<calcTypeInt>(scaleReprocal, scaleReprocal, nan, infMask);
    AscendC::Reg::Select<calcTypeInt>(scaleReprocal, specialExp, scaleReprocal, specialDataMask);
    for (uint16_t j = 0; j < static_cast<uint16_t>(blockCount); j++) {
        this->template LoadData<calcType>(xAddr, j * dataLen + i * vfLen, xReg, p0);
        CalcElement<roundMode, U, calcType, calcTypeInt>(xReg, scaleReprocal, infForXReg, out,
                                                         preMaskScale2);
        auto addr = yAddr + (j * outDataLenAlign + i * vfLen) / DIGIT_TWO;
        AscendC::Reg::DataCopyUnAlign(addr, out, u1, vfLen / DIGIT_TWO);
        AscendC::Reg::DataCopyUnAlignPost(addr, u1, 0);
    }
} else if constexpr (IsSame<T, half>::value) {
```

**片段 2** (行 757-771):

```cpp
AscendC::Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, tailVfLen);
AscendC::Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);

AscendC::Reg::ShiftLefts((Reg::RegTensor<uint16_t>&)expFP32Reg, (Reg::RegTensor<uint16_t>&)expFP32Reg,
                         BF16_SHR_NUM, pregAll16);
AscendC::Reg::Compare<calcTypeInt, CMPMODE::NE>(infMask, (Reg::RegTensor<uint16_t>&)expFP32Reg,
                                                infForXReg, pregAll16);
AscendC::Reg::Compare<calcTypeInt, CMPMODE::EQ>(specialDataMask, (Reg::RegTensor<uint16_t>&)expFP32Reg,
                                                biasReg, pregAll16);
AscendC::Reg::Sub(scaleReprocal, biasReg, (Reg::RegTensor<uint16_t>&)expFP32Reg, pregAll16);
AscendC::Reg::Select<calcTypeInt>(scaleReprocal, scaleReprocal, nan, infMask);
AscendC::Reg::Select<calcTypeInt>(scaleReprocal, specialExp, scaleReprocal, specialDataMask);
if constexpr (ISTAIL) {
    Reg::Duplicate(scaleReprocal, scaleReprocal, preMaskScale2);
}
```

**片段 3** (行 796-810):

```cpp
AscendC::Reg::Pack(mxScale, expBF16Reg);
AscendC::Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, tailVfLen);
AscendC::Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);

AscendC::Reg::ShiftLefts(expFP32Reg, expFP32Reg, FP32_SHR_NUM, preMaskScale);
// 求1/scale
AscendC::Reg::Compare<calcTypeInt, CMPMODE::NE>(infMask, expFP32Reg, infForXReg, preMaskScale);
AscendC::Reg::Compare<calcTypeInt, CMPMODE::EQ>(specialDataMask, expFP32Reg, biasReg, preMaskScale);
AscendC::Reg::Sub(scaleReprocal, biasReg, expFP32Reg, preMaskScale);

AscendC::Reg::Select<calcTypeInt>(scaleReprocal, scaleReprocal, nan, infMask);
AscendC::Reg::Select<calcTypeInt>(scaleReprocal, specialExp, scaleReprocal, specialDataMask);
if constexpr (ISTAIL) {
    Reg::Duplicate(scaleReprocal, scaleReprocal, preMaskScale);
}
```

**要点**: 1) 用全限定名 AscendC::Reg::Select 调用，与裸名 Reg::Select 等价，适用于未 using 命名空间的文件；2) 三处片段重复 Sub 求 1/scale→Select inf→Select special 模板，体现 Select 在异常值兜底中的高频复用；3) ISTAIL 分支用 Duplicate 广播 scale，Select 在此之前已完成逐元素选择。


### 实例 6：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Select 调用次数**: 6
- **参数模式**: `T1_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: int32_t, uint32_t）
- **语义（待补充）**: flat_quant 高精度路径中，Reg::Select 按掩码 p0 在「指数+1」与「原指数」间选择并覆盖 fp4 的 nan 与 zero，再对 1/scale 重复 nan/zero 覆盖后 StoreAlign 搬出。

（行 509-538）

```cpp
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
```

**要点**: 1) Select 紧跟 Adds(expAddOne32, exp32, 1)，实现满足条件则取进位值的逐元素条件加一；2) flat_quant 用 fp4NanRegTensor 而非 fp8Nan，Select 的 src2 随量化格式变化；3) 1/scale 段同样用两次 Select 覆盖 nan/zero，与 scale 段对称。


### 实例 7：dynamic_mx_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Pack, RegLayout, RegTensor, SatMode, ShiftLefts, ShiftRights, Sub
- **Select 调用次数**: 6
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: dynamic_mx_quant 高性能大尾轴路径中，Select 省略模板参数（T0），根据 MaskXor 产出的 p0 在「尾数+1」与「原值」间选择，实现 MX 量化的舍入进位。

（行 456-466）

```cpp
if constexpr (calcMode == MODE_ONE) {
    Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, mxScale0FP32, FP32_NUMBER_ZERO, pregAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manAbs0FP32, FP32_NUMBER_HALF, p1);
    Reg::MaskXor(p0, p0, p1, pregAll32);
}

Reg::Adds(manAbs0FP32, mxScale0FP32, 1, p0);
Reg::Select(mxScale0FP32, manAbs0FP32, mxScale0FP32, p0);

Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)mxScale0BF16, mxScale0FP32);
```

**要点**: 1) calcMode==MODE_ONE 时额外用 CompareScalar+MaskXor 修正 p0，Select 直接消费该掩码；2) Select 省略模板参数由编译器按寄存器类型推断，与显式 Select<uint32_t> 等价；3) Select 后接 Pack<uint16_t,uint32_t,LOWEST> 把 uint32 指数压成 BF16 scale。


### 实例 8：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **Select 调用次数**: 10
- **参数模式**: `T1_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义（待补充）**: complex_abs 算子中，Reg::Select<float> 按「b 的绝对值大于 a 的绝对值」的比较掩码 preg2 把较大值选入 vA、较小值选入 vB，再用 Select 处理 subnormal 放缩与零值结果，实现复数绝对值的稳定计算。

**片段 1** (行 116-135):

```cpp
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
```

**片段 2** (行 103-160):

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

**要点**: 1) Select 用于按比较结果两路择一，dst=src0 当 mask=1，常成对使用（vA 取大、vB 取小）；2) subnormal 处理 Select(vA, vAS, vA, preg3) 在放缩值与原值间选择，避免次正规数精度丢失；3) 结果段 Select(vResult, vA, vResult, preg4) 实现输入为零时直接输出 a 的绝对值。


### 实例 9：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, Muls, RegTensor, StoreAlign, StoreDist, Sub, UpdateMask
- **Select 调用次数**: 3
- **参数模式**: `T1_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: fake_quant 逐通道量化中，Reg::Select<float> 用 Compares 产出的掩码实现 bothZero、scaleSafe、diffSafe 三处条件兜底：min/max 同为零时输出 0、scale 为零时回退 1.0、diff 为零时分母回退 1.0。

（行 382-413）

```cpp

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
```

**要点**: 1) Select 的 mask 参数由 Compares（标量比较版）直接产出，区别于 Compare 的寄存器版本；2) 用 Select 构造安全值是量化算子避免除零/NaN 的通用手法（vregOne vs vregZero/vregScale）；3) 第四参数 maskBoth/maskScaleZero 复用同一套比较掩码，Select 实现逐元素条件常数注入。


### 实例 10：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, ShiftLefts, ShiftRights, StoreDist, Sub
- **Select 调用次数**: 16
- **参数模式**: `T1_A4_M1_TYPEint16_t+uint16_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: int16_t, uint16_t）
- **语义（待补充）**: 双轴 MX 量化中，Reg::Select<uint16_t> 用于 1/scale 的 inf/special 覆盖，并在 Zero 半与 One 半分别用 Select 完成指数进位选择，配合 Interleave 把两半 scale 交织输出。

**片段 1** (行 1234-1254):

```cpp
// Pack到uint16 (INF/NAN→0xFF, zero→0 自然通过条件舍入保持, 在BF16域1/scale中统一处理)
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);

// 左移7位，将E8M0值定位到BF16指数域 (用于计算1/scale)
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);

// --- 输出-1轴scale (uint8) ---
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scale1B16_0);
Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScale1Addr, mxScale1B8,
                                                                     oneBlockCountB8_, maskReduceB8);

// --- 计算并输出-1轴 1/scale (与原始DynamicMxQuant一致: inf→nan, special→specialExp, 无零值检查) ---
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, scale1BF16, maxEleBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, scale1BF16, biasE8M0, maskAll);
Reg::Sub(reversedShareExp1, biasE8M0, scale1BF16, maskAll);
Reg::Select<uint16_t>(reversedShareExp1, reversedShareExp1, nanBF16, infMask);
Reg::Select<uint16_t>(reversedShareExp1, specialExp, reversedShareExp1, invalidDataMask);
Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    mxScale1ReciprocalAddr, reversedShareExp1, oneBlockCountB16_, maskReduceB16);
// 恢复zeroB16 (Interleave会修改dst1)
Reg::Duplicate(zeroB16, 0);
```

**片段 2** (行 1306-1335):

```cpp
Reg::Select<uint16_t>(reversedShareExp1, reversedShareExp1, nanBF16, infMask);
Reg::Select<uint16_t>(reversedShareExp1, specialExp, reversedShareExp1, invalidDataMask);

// ---------- 处理absMax2Dim2 (奇数列, -2轴scale的交织第二部分) ----------
// Zero半 — 复用循环体偶数部分寄存器
Reg::Cast<float, xDtype, castTraitXdtypetoFp32Zero>((Reg::RegTensor<float>&)maxFP32_0,
                                                         (Reg::RegTensor<xDtype>&)absMax2Dim2, maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_0, (Reg::RegTensor<float>&)maxFP32_0, invDstTypeMaxReg,
              maskFP32);
Reg::ShiftRights(expFP32_0, maxFP32_0, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_0, maxFP32_0, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_0, NUMBER_ZERO_U32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_0, NUMBER_TWO_FIVE_FOUR, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_0, NUMBER_ZERO_U32, p0);
Reg::Adds(maxFP32_0, expFP32_0, 1, maskFP32);
Reg::Select(expFP32_0, maxFP32_0, expFP32_0, p0);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, expFP32_0);

// One半 — 复用循环体奇数部分寄存器
Reg::Cast<float, xDtype, castTraitXdtypetoFp32One>((Reg::RegTensor<float>&)maxFP32_1,
                                                        (Reg::RegTensor<xDtype>&)absMax2Dim2, maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<float>&)maxFP32_1, invDstTypeMaxReg,
              maskFP32);
Reg::ShiftRights(expFP32_1, maxFP32_1, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_1, maxFP32_1, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_1, NUMBER_ZERO_U32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_1, NUMBER_TWO_FIVE_FOUR, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_1, NUMBER_ZERO_U32, p0);
Reg::Adds(maxFP32_1, expFP32_1, 1, maskFP32);
Reg::Select(expFP32_1, maxFP32_1, expFP32_1, p0);
```

**要点**: 1) Zero 半与 One 半各用独立掩码 p0/p0Odd，Select 在两半并行执行相同进位逻辑；2) Select<uint16_t>(reversedShareExp1, reversedShareExp1, nanBF16, infMask) 是 1/scale 异常值覆盖的标准写法；3) Interleave 在 Select 之后把两半结果交织，Select 产出是交织的输入。


### 实例 11：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, RegTensor, ShiftLefts, ShiftRights, StoreDist, Sub
- **Select 调用次数**: 12
- **参数模式**: `T1_A4_M0_TYPEint16_t+uint16_t`（实参 4 个，类型: int16_t, uint16_t）
- **语义（待补充）**: swiglu_mx_quant 非末轴场景，Reg::Select 在 absMax2Dim1/Dim2 两路分别完成指数进位与 1/scale 的 inf/special 覆盖，再用 Interleave+DataCopy DIST_INTLV 把双轴 scale 交织搬出。

（行 343-401）

```cpp
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, manFP32_1, ZERO_FOR_ALL, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1Odd, expFP32_1, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1Odd, manFP32_1, SPECIAL_EXP_THRESHOLD_FP32, p1Odd);
Reg::MaskOr(p0Odd, p0Odd, p1Odd, maskFP32);
Reg::Adds(maxFP32_1, expFP32_1, 1, maskFP32);
Reg::Select(manFP32_1, maxFP32_1, expFP32_1, p0Odd);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_1, manFP32_1);
Reg::Interleave(scale1B16_0, scale1B16_1, scale1B16_0, scale1B16_1);
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scale1B16_0);
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, scale1BF16, maxEleBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, scale1BF16, biasE8M0, maskAll);
Reg::Sub(absMax0, biasE8M0, scale1BF16, maskAll);
Reg::Select<uint16_t>(absMax0, absMax0, nanBF16, infMask);
Reg::Select<uint16_t>(absMax0, specialExp, absMax0, invalidDataMask);

// process absMax2Dim2
Reg::Cast<float, T, CAST_ZERO>((Reg::RegTensor<float>&)maxFP32_0,
                                    (Reg::RegTensor<T>&)absMax2Dim2, maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_0, (Reg::RegTensor<float>&)maxFP32_0,
              (Reg::RegTensor<float>&)invMax, maskFP32);
Reg::ShiftRights(expFP32_0, maxFP32_0, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_0, maxFP32_0, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_0, EXP_254, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_0, ZERO_FOR_ALL, p0);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32_0, SPECIAL_EXP_THRESHOLD_FP32, p1);
Reg::MaskOr(p0, p0, p1, maskFP32);
Reg::Adds(maxFP32_0, expFP32_0, 1, maskFP32);
Reg::Select(manFP32_0, maxFP32_0, expFP32_0, p0);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);
Reg::Cast<float, T, CAST_ONE>((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<T>&)absMax2Dim2,
                                   maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<float>&)maxFP32_1,
              (Reg::RegTensor<float>&)invMax, maskFP32);
Reg::ShiftRights(expFP32_1, maxFP32_1, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_1, maxFP32_1, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, expFP32_1, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0Odd, expFP32_1, EXP_254, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, manFP32_1, ZERO_FOR_ALL, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1Odd, expFP32_1, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1Odd, manFP32_1, SPECIAL_EXP_THRESHOLD_FP32, p1Odd);
Reg::MaskOr(p0Odd, p0Odd, p1Odd, maskFP32);
Reg::Adds(maxFP32_1, expFP32_1, 1, maskFP32);
Reg::Select(manFP32_1, maxFP32_1, expFP32_1, p0Odd);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_1, manFP32_1);
Reg::Interleave(scale1B16_0, scale1B16_1, scale1B16_0, scale1B16_1);
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale2B8, scale1B16_0);
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, scale1BF16, maxEleBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, scale1BF16, biasE8M0, maskAll);
Reg::Sub(absMax1, biasE8M0, scale1BF16, maskAll);
Reg::Select<uint16_t>(absMax1, absMax1, nanBF16, infMask);
Reg::Select<uint16_t>(absMax1, specialExp, absMax1, invalidDataMask);

Reg::DataCopy<uint8_t, Reg::StoreDist::DIST_INTLV_B8>(mxScaleAddr, mxScale1B8, mxScale2B8, maskB8);
Reg::DataCopy<uint16_t, Reg::StoreDist::DIST_INTLV_B16>(mxScaleReciprocalAddr, absMax0, absMax1,
                                                                  maskAll);
```

**要点**: 1) 同一函数内两组 Select（absMax0/absMax1）对称处理两个轴，掩码 p0/p0Odd 独立；2) Select 后接 Pack<uint8_t> 把 uint16 scale 压成 uint8 E8M0 再 DataCopy 交织搬出；3) 1/scale 段 Select(..., nanBF16, infMask) 与 Select(..., specialExp, invalidDataMask) 成对覆盖异常值。


### 实例 12：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Select 调用次数**: 6
- **参数模式**: `T1_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: int32_t, uint32_t）
- **语义（待补充）**: add_rms_norm_dynamic_mx_quant 的 scale 循环中，Reg::Select 在每次迭代完成「指数进位→inf 覆盖→zero 覆盖」三连选择，再对 1/scale 重复 nan/zero 覆盖，StoreAlign 搬出 mxScale 与 halfScale。

（行 461-495）

```cpp
for (uint16_t i = 0; i < loopNumScale4NV; i++) {
    AscendC::Reg::LoadAlign<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                 AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16, maxExpAddr, VL_F32);
    AscendC::Reg::Cast<float, T_X, castTraitHalf2Float>(
        (AscendC::Reg::RegTensor<float>&)max32, (AscendC::Reg::RegTensor<T_X>&)max16, preMaskScale);
    AscendC::Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32, expMask, preMaskScale);
    AscendC::Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32, zeroRegTensor32, preMaskScale);
    AscendC::Reg::Mul((AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)max32,
                           (AscendC::Reg::RegTensor<float>&)invMax, preMaskScale);
    AscendC::Reg::ShiftRights(exp32, max32, SHR_NUM_FOR_FP32, preMaskScale);
    AscendC::Reg::And(man32, max32, manMaskFP32, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32, CUBLAS_ZERO_FOR_ALL, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, exp32, CUBLAS_EXP254, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, CUBLAS_ZERO_FOR_ALL, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p1, preMaskScale);
    AscendC::Reg::MaskAnd(p0, p0, p2, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, exp32, CUBLAS_ZERO_FOR_ALL, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32, CUBLAS_HALF_FOR_MAN, preMaskScale);
    AscendC::Reg::MaskAnd(p1, p1, p2, preMaskScale);
    AscendC::Reg::MaskOr(p0, p0, p1, preMaskScale);
    AscendC::Reg::Adds(expAddOne32, exp32, 1, preMaskScale);
    AscendC::Reg::Select(extractExp, expAddOne32, exp32, p0);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, fp8NanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(extractExp, extractExp, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(expOut, extractExp);
    AscendC::Reg::StoreAlign<uint16_t, AscendC::Reg::StoreDist::DIST_PACK_B16>(
        mxScaleLocalAddr + i * ThirtyTwo, expOut, maskHalf);
    AscendC::Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, preMaskScale);
    AscendC::Reg::Sub(halfScale, scaleBias, extractExp, preMaskScale);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, nanRegTensor, cmpResult);
    AscendC::Reg::Select<uint32_t>(halfScale, halfScale, zeroRegTensor32, zeroMask);
    AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(recExpOut, halfScale);
    AscendC::Reg::StoreAlign<uint16_t>(halfScaleLocalAddr + i * VL_F32, recExpOut, maskHalf);
}
```

**要点**: 1) Select 位于 LoadAlign+Cast+Mul 之后的指数提取段，掩码 p0 由多级 CompareScalar+MaskAnd+MaskOr 合成；2) 循环内 Select 每轮独立执行，dst 寄存器 extractExp/halfScale 跨 Select 链式复用；3) cmpResult 与 zeroMask 分别驱动 inf/zero 的 Select 覆盖。


### 实例 13：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, ShiftLefts, ShiftRights, StoreDist, Sub
- **Select 调用次数**: 6
- **参数模式**: `T1_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: int32_t, uint32_t）
- **语义（待补充）**: rms_norm_dynamic_mx_quant 中，Reg::Select 从「指数+1」与「原指数」选择进位结果并覆盖 fp8 的 nan 与 zero，再对 1/scale 重复 nan/zero 覆盖，DataCopy 搬出 scale 与 halfScale。

（行 431-462）

```cpp
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
```

**要点**: 1) Select 与 Adds(expAddOne32, exp32, 1) 配对，实现逐元素条件进位；2) 两次 Select<uint32_t>(extractExp, ..., fp8NanRegTensor/zeroRegTensor32, ...) 完成 inf/zero 异常值覆盖；3) 1/scale 段 Select(halfScale, halfScale, nanRegTensor/zeroRegTensor32, ...) 与 scale 段对称。


### 实例 14：dynamic_block_mx_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, Compare, CreateMask, Duplicate, Gather, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, ShiftRights, StoreAlign, Sub
- **Select 调用次数**: 8
- **参数模式**: `T1_A4_M1_TYPEint16_t+uint16_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: int16_t, uint16_t）
- **语义（待补充）**: dynamic_block_mx_quant 中，Reg::Select<uint16_t> 先把 half 输入的 INF/NAN 位置替换为 BF16 的 INF 指数，再在 1/scale 段用 Select 覆盖 inf→nan、zero→0、special→specialExp，并用 Gather 按索引重排 block scale。

**片段 1** (行 666-686):

```cpp
if constexpr (IsSameType<T, half>::value) {
    // 求绝对值
    Reg::And(x0ExpFP16, (Reg::RegTensor<uint16_t>&)x0, absForX, maskAll);
    Reg::And(x1ExpFP16, (Reg::RegTensor<uint16_t>&)x1, absForX, maskAll);
    // 比较INF/NAN数据
    Reg::Compare<uint16_t, CMPMODE::LT>(infNanDataMask0, x0ExpFP16, expMaskFP16, maskAll);
    Reg::Compare<uint16_t, CMPMODE::LT>(infNanDataMask1, x1ExpFP16, expMaskFP16, maskAll);
    // 原始数据转成bf16
    Reg::Cast<bfloat16_t, T, castTraitHalf2BF16Ddr>(x0BF16, x0, maskAll);
    Reg::Cast<bfloat16_t, T, castTraitHalf2BF16Ddr>(x1BF16, x1, maskAll);
    // 提取指数位
    Reg::And(x0ExpBF16, (Reg::RegTensor<uint16_t>&)x0BF16, absForX, maskAll);
    Reg::And(x1ExpBF16, (Reg::RegTensor<uint16_t>&)x1BF16, absForX, maskAll);
    // 选择数据，INF/NAN数据时设成BF的INF/NAN
    Reg::Select<uint16_t>(x0ExpBF16, x0ExpBF16, expMaskBF16, infNanDataMask0);
    Reg::Select<uint16_t>(x1ExpBF16, x1ExpBF16, expMaskBF16, infNanDataMask1);
} else {
    // 求绝对值
    Reg::And(x0ExpBF16, (AscendC::Reg::RegTensor<uint16_t>&)x0, absForX, maskAll);
    Reg::And(x1ExpBF16, (AscendC::Reg::RegTensor<uint16_t>&)x1, absForX, maskAll);
}
```

**片段 2** (行 707-729):

```cpp
Reg::Sub(expMaxDim, expMaxDim, mantissaForMax, maskAll);
// 右移7位，BF16的指数位移到了末8位
Reg::ShiftRights(mxScaleB16, expMaxDim, SHR_NUM_FOR_BF16, maskAll);
Reg::Select<uint16_t>(mxScaleB16, mxScaleB16, nanE8M0, infMask);
Reg::Select<uint16_t>(mxScaleB16, mxScaleB16, zero, zeroMask);

Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, mxScaleB16);
Reg::LoadAlign(gatherIndex, gatherIndexAddr);
Reg::Gather(mxScale2B8, mxScale1B8, gatherIndex);
Reg::StoreAlign(mxScale2Addr, mxScale2B8, maskB8);
Reg::And(expTmpMaxDim, expMaxDim, expMaskBF16, maskAll);
// compute  1/scale
// 只有在E1M2时，yMaxExp=0，xTmp0ExpBF16可能会等于biasE8M0
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, expTmpMaxDim, biasE8M0, maskAll);
Reg::Sub(reversedExp, biasE8M0, expTmpMaxDim, maskAll);
Reg::Select<uint16_t>(reversedExp, reversedExp, nanBF16, infMask);
Reg::Select<uint16_t>(reversedExp, reversedExp, zero, zeroMask);
Reg::Select<uint16_t>(reversedExp, specialExp, reversedExp, invalidDataMask);
// -1轴scale循环搬出
for (uint16_t i = 0; i < rowNum; i++) {
    Reg::StoreAlign<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScale1Addr, mxScale1B8,
                                                                 ubBlockSize_ / sizeof(uint8_t), maskReduceB8);
}
```

**要点**: 1) half 路径 Select<uint16_t>(x0ExpBF16, x0ExpBF16, expMaskBF16, infNanDataMask0) 把异常数据指数统一替换为 INF 编码；2) 1/scale 三连 Select：inf→nan、zero→0、special→specialExp，覆盖优先级由掩码互斥保证；3) Gather 在 Select 产出后按索引重排，Select 是 Gather 的数据源。


### 实例 15：tanh::TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, And, Cast, CompareScalar, DataCopy, Div, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, Or, RegTensor, RegTraitNumOne, StoreDist, UpdateMask
- **Select 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: tanh 算子中，Reg::Select 用于两处分段选择：当输入绝对值≥饱和阈值时 Select 输出 1.0 实现饱和，当输入绝对值≥0.6 时 Select 选用指数式近似结果，实现多项式与指数式近似的无缝切换。

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

**片段 2** (行 126-152):

```cpp
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
```

**要点**: 1) Select(vregInputMid, vregOne, vregInputMid, satMaskReg) 实现饱和段直接输出 1.0；2) Select(vregOutput, vregInputMid, vregOutput, cmpMaskReg) 在指数近似与多项式近似间按输入绝对值≥0.6 切换；3) 第四参数为 CompareScalar 产出的掩码，Select 模板参数省略（T0）按 float 寄存器推断。

### Select 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 指数进位选择 + inf/nan/zero 异常值三连覆盖（FP32 E8M0） | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | MaskXor 驱动向上取整 + 异常值覆盖（fp8） | __VEC_SCOPE__ |
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Arange, Cast | 指数进位 + Gather 交错搬出双轴 scale | __VEC_SCOPE__ |
| dynamic_mx_quant | And, Cast, CastTrait, Compare, Copy | half/bf16 无效数据指数替换 + 1/scale 异常覆盖 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | AscendC::Reg 全限定 1/scale inf/special 覆盖 + Duplicate 尾轴 | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | 指数进位 + fp4 nan/zero 覆盖 + StoreAlign 搬出 | __simd_vf__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | MaskXor 修正掩码 + 无模板参数舍入进位 | __VEC_SCOPE__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | 按比较两路择大/择小 + subnormal 放缩 + 零值结果选择 | __aicore__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | Compares 掩码构造 bothZero/scaleSafe/diffSafe 安全值兜底 | __VEC_SCOPE__ |
| dynamic_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | Zero/One 半并行进位 + Interleave 交织 1/scale 异常覆盖 | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | 双轴对称进位 + Interleave+DIST_INTLV 交织搬出 | __aicore__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | scale 循环内三连选择 + StoreAlign 搬出 | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | 指数进位 + fp8 nan/zero 覆盖 + DataCopy 搬出 | __aicore__ |
| dynamic_block_mx_quant | And, Cast, Compare, CreateMask, Duplicate | half INF/NAN 指数替换 + Gather 重排 block scale | __VEC_SCOPE__ |
| tanh | Abs, Adds, And, Cast, CompareScalar | 饱和段+分段阈值双 Select 切换（多项式/指数式） | __aicore__ |
