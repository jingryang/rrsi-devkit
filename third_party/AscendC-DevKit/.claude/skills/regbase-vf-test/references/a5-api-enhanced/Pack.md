# Pack

**页面ID:** atlasascendc_api_07_0338  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0338.html

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

根据所选的低位模式或高位模式，将输入MaskReg的偶数位bit提取到输出MaskReg的低半部分或高半部分。

#### 函数原型

```
template <HighLowPart part = HighLowPart::LOWEST> 
__simd_callee__ inline void Pack(MaskReg& dst, MaskReg& src)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| part | 枚举类型，低位模式或高位模式。 - LOWEST  低位模式；- HIGHEST 高位模式。 |

**表2 **参数说明

| 参数名 | 描述 |
| --- | --- |
| dst | 目的操作数。 |
| src | 源操作数。 |

#### 约束说明

无

#### 调用示例

```
template <typename T>
__simd_vf__ inline void PackVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg maskFull = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg mask0;
    AscendC::Reg::MaskReg mask1;
    AscendC::Reg::Pack<AscendC::Reg::HighLowPart::LOWEST>(mask0, maskFull);
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask1 = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Adds(srcReg, srcReg, 0, mask0);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask1);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Pack 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Pack 调用次数**: 10
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 dynamic_mx_quant 的 FP8 量化中，先用 Pack 将 uint32 指数压缩为 uint16，再 Pack 为 uint8 的 mxScale 输出；对量化后的 yZero/yOne 用 Pack+Interleave+Pack 交织合并后搬出。

**片段 1** (行 516-535):

```cpp

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
```

**片段 2** (行 563-582):

```cpp
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
Reg::Pack(outZero, tmp16RegTensor);
auto addr0 = yAddr + i * dataLenSingleLoop;
Reg::DataCopyUnAlign(addr0, outZero, u1, dataLenSingleLoop);
Reg::DataCopyUnAlignPost(addr0, u1, 0);
```

**要点**: ①Pack 可级联使用（uint32→uint16→uint8）逐级压缩位宽；②与 Interleave 配合实现奇偶元素交织存放；③无模板参数时由编译器按 RegTensor 类型自动推导。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Pack 调用次数**: 14
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t+uint16_t+uint32_t`（实参 2 个，类型: int16_t, uint16_t, int32_t, uint32_t, LOWEST, HighLowPart, LOW）
- **语义**: grouped_dynamic_mx_quant 中显式指定模板参数 <uint16_t,uint32_t,HighLowPart::LOWEST> 将 FP32 尾数+指数 Pack 成 uint16 E8M0 scale，再 Pack 成 uint8 输出。

（行 605-651）

```cpp
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
                                                        expAndreShareExpFP32RegTensor);
// 10. 量化
if constexpr (IsSame<T, half>::value) {
    Reg::Cast<float, bfloat16_t, castTraitZero>(
        reversedShareExpRegTensorFP32Zero, (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor,
        p0);
    Reg::Cast<float, bfloat16_t, castTraitOne>(
        reversedShareExpRegTensorFP32One, (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor,
        p0);
}
for (uint16_t j = 0; j < static_cast<uint16_t>(blockCount); j++) {
    Reg::LoadAlign(xRegTensor, xAddr + j * dataLen + i * vfNum32);
    if constexpr (IsSame<T, half>::value) {
        Reg::Cast<float, T, castTraitZero>(yZero, xRegTensor, p0);
        Reg::Cast<float, T, castTraitOne>(yOne, xRegTensor, p0);
        Reg::Mul(yZero, yZero, reversedShareExpRegTensorFP32Zero, maskAll);
        Reg::Mul(yOne, yOne, reversedShareExpRegTensorFP32One, maskAll);
    } else {
        Reg::Mul(valueRegTensor, xRegTensor, (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor,
                 p0);
        Reg::Cast<float, bfloat16_t, castTraitZero>(yZero, valueRegTensor, maskAll);
        Reg::Cast<float, bfloat16_t, castTraitOne>(yOne, valueRegTensor, maskAll);
    }
    Reg::Interleave(yZero, yOne, yZero, yOne);
    Reg::Cast<U, float, castTrait32to8>(yZeroFP8, yZero, maskAll);
    Reg::Pack(expScaleMxYZeroRegTensor, (Reg::RegTensor<uint32_t>&)yZeroFP8);
    Reg::Pack(outZeromxScaleFp8, expScaleMxYZeroRegTensor);
    auto addr = yAddr + (j * outDataLenAlign + i * vfNum32);
    Reg::StoreUnAlign(addr, outZeromxScaleFp8, u1, singleLoopNum);
    Reg::StoreUnAlignPost(addr, u1, 0);
}
```

**要点**: ①显式三模板参数 <dstT,srcT,part> 控制目标位宽与高低位；②LOWEST 写入低半部分；③级联 Pack 实现 uint32→uint16→uint8 两级压缩。

### 实例 3：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, HighLowPart, Interleave, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Muls, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Pack 调用次数**: 14
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int8_t+uint16_t+uint8_t`（实参 2 个，类型: uint8_t, int8_t, int16_t, uint16_t, LOWEST, HighLowPart, LOW）
- **语义**: dynamic_mx_quant(FP8) 中用 <uint8_t,uint16_t,LOWEST> 和 <uint16_t,uint32_t,LOWEST> 两种 Pack 模板，分别完成 uint16→uint8 与 uint32→uint16 的 scale 压缩。

**片段 1** (行 597-635):

```cpp
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(outZeromxScaleFp8, expScaleMxYZeroRegTensor);
Reg::DataCopyUnAlign(mxScaleAddr, outZeromxScaleFp8, u1, vfNum32); // 从寄存器搬到UB
Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);
// 求1/scale
Reg::ShiftLefts(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, BF16_SHR_NUM, preMaskScale);
Reg::Sub(expAndreShareExpFP32RegTensor, bias, manAndmxScaleFP32RegTensor, preMaskScale);
// 校验
Reg::Select<uint32_t>(expAndreShareExpFP32RegTensor, expAndreShareExpFP32RegTensor, nan, infMask);
Reg::Select<uint32_t>(expAndreShareExpFP32RegTensor, expAndreShareExpFP32RegTensor, zeroRegTensor32,
                      zeroMask);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(expMaxreShareExpFP16YOneRegTensor,
                                                        expAndreShareExpFP32RegTensor);
// 求data value
for (uint16_t j = 0; j < static_cast<uint16_t>(blockCount); j++) {
    this->template LoadData<toBf16RoundMode, roundMode, true>(xAddr, j * dataLen + i * vfNum32, x, p0);
    if constexpr (IsSame<T, half>::value) {
        Reg::Cast<float, T, castTraitZero>(yZero, x, p0);
        Reg::Cast<float, T, castTraitOne>(yOne, x, p0);
        Reg::Cast<float, bfloat16_t, castTraitZero>(
            reversedShareExpRegTensorFP32Zero,
            (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor, p0);
        Reg::Cast<float, bfloat16_t, castTraitOne>(
            reversedShareExpRegTensorFP32One,
            (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor, p0);
        Reg::Mul(yZero, yZero, reversedShareExpRegTensorFP32Zero, maskAll);
        Reg::Mul(yOne, yOne, reversedShareExpRegTensorFP32One, maskAll);
    } else if constexpr (IsSame<T, bfloat16_t>::value) {
        Reg::Mul(valueRegTensor, x, (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor, p0);
        Reg::Cast<float, bfloat16_t, castTraitZero>(yZero, valueRegTensor, maskAll);
        Reg::Cast<float, bfloat16_t, castTraitOne>(yOne, valueRegTensor, maskAll);
    }
    Reg::Interleave(yZero, yOne, yZero, yOne);
    Reg::Cast<U, float, castTrait32to8>(yZeroFP8, yZero, maskAll);
    Reg::Pack(expScaleMxYZeroRegTensor, (Reg::RegTensor<uint32_t>&)yZeroFP8);
    Reg::Pack(outZeromxScaleFp8, expScaleMxYZeroRegTensor);
    auto addr = yAddr + (j * outDataLenAlign + i * vfNum32);
    Reg::DataCopyUnAlign(addr, outZeromxScaleFp8, u1, singleLoopNum);
    Reg::DataCopyUnAlignPost(addr, u1, 0);
}
```

**片段 2** (行 678-697):

```cpp
Reg::MaskAnd(p2, p2, p3, preMaskScale);
Reg::MaskXor(p1, p1, p2, preMaskScale);
// 向上取整
Reg::Adds(expMaxAndAddOneFP32RegTensor, expAndreShareExpFP32RegTensor, 1, preMaskScale);
Reg::Select(manAndmxScaleFP32RegTensor, expMaxAndAddOneFP32RegTensor, expAndreShareExpFP32RegTensor, p1);
// 校验
Reg::Select<uint32_t>(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, fp8Nan, infMask);
Reg::Select<uint32_t>(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, zeroRegTensor32, zeroMask);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(expScaleMxYZeroRegTensor,
                                                        manAndmxScaleFP32RegTensor);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(outZeromxScaleFp8, expScaleMxYZeroRegTensor);
Reg::DataCopyUnAlign(mxScaleAddr, outZeromxScaleFp8, u1, tailVfLen); // 从寄存器搬到UB
Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);
// 求1/scale
Reg::ShiftLefts(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, BF16_SHR_NUM, preMaskScale);
Reg::Sub(expAndreShareExpFP32RegTensor, bias, manAndmxScaleFP32RegTensor, preMaskScale);
// 校验
Reg::Select<uint32_t>(expAndreShareExpFP32RegTensor, expAndreShareExpFP32RegTensor, nan, infMask);
Reg::Select<uint32_t>(expAndreShareExpFP32RegTensor, expAndreShareExpFP32RegTensor, zeroRegTensor32,
                      zeroMask);
```

**片段 3** (行 707-729):

```cpp
if constexpr (IsSame<T, half>::value) {
    Reg::Cast<float, T, castTraitZero>(yZero, x, p0);
    Reg::Cast<float, T, castTraitOne>(yOne, x, p0);
    Reg::Cast<float, bfloat16_t, castTraitZero>(
        reversedShareExpRegTensorFP32Zero,
        (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor, p0);
    Reg::Cast<float, bfloat16_t, castTraitOne>(
        reversedShareExpRegTensorFP32One,
        (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor, p0);
    Reg::Mul(yZero, yZero, reversedShareExpRegTensorFP32Zero, maskAll);
    Reg::Mul(yOne, yOne, reversedShareExpRegTensorFP32One, maskAll);
} else if constexpr (IsSame<T, bfloat16_t>::value) {
    Reg::Mul(valueRegTensor, x, (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor, p0);
    Reg::Cast<float, bfloat16_t, castTraitZero>(yZero, valueRegTensor, maskAll);
    Reg::Cast<float, bfloat16_t, castTraitOne>(yOne, valueRegTensor, maskAll);
}
Reg::Interleave(yZero, yOne, yZero, yOne);
Reg::Cast<U, float, castTrait32to8>(yZeroFP8, yZero, maskAll);
Reg::Pack(expScaleMxYZeroRegTensor, (Reg::RegTensor<uint32_t>&)yZeroFP8);
Reg::Pack(outZeromxScaleFp8, expScaleMxYZeroRegTensor);
auto addr = yAddr + (regLoop * vfNum32 + j * outDataLenAlign);
Reg::DataCopyUnAlign(addr, outZeromxScaleFp8, u1, singleTailLoopNum);
Reg::DataCopyUnAlignPost(addr, u1, 0);
```

**要点**: ①uint8/uint16 组合用于最终输出单字节 E8M0 scale；②与 uint16/uint32 组合级联覆盖完整压缩链；③类型组合由源/目标 RegTensor 决定。

### 实例 4：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Pack 调用次数**: 3
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t+uint16_t+uint32_t`（实参 2 个，类型: int16_t, uint16_t, int32_t, uint32_t, LOWEST, HighLowPart, LOW）
- **语义**: swiglu_backward 双轴量化中，用 Pack 将提取的指数压缩为 uint16 再到 uint8 scale，配合 Gather/Arange 重排 scale 字节序后搬出。

（行 947-989）

```cpp
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

**要点**: ①Pack 后常接 Gather 做字节重排；②Reg:: 命名空间与 Reg:: 等价；③双轴场景对 -1/-2 轴分别 Pack 输出。

### 实例 5：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Pack 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEint32_t+uint32_t`（实参 2 个，类型: int32_t, uint32_t）
- **语义**: dynamic_quant 的 int4 量化分支中，用 Pack 将 half 寄存器压缩为 uint16，再 Cast 成 int4x2_t 实现两个 int4 拼接到一个字节。

（行 415-432）

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

**要点**: ①Pack 可作为 int4x2 拼接的前置步骤（half→uint16→int4x2）；②无显式模板参数，靠 cast 推导；③aicore 上下文同样可用 Reg::Pack。

### 实例 6：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, Interleave, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Pack 调用次数**: 12
- **参数模式**: `T0_A2_M0_TYPEint16_t+uint16_t`（实参 2 个，类型: int16_t, uint16_t）
- **语义**: dynamic_mx_quant（非 FP8）中，对 DeInterleave 后的 uint16 指数用 Pack 生成 mxScale；half 分支用两次 Pack（uint32→uint16→输出）完成 scale 压缩。

**片段 1** (行 644-663):

```cpp
AscendC::Reg::And(manFP32Reg2, xFP32MaxReg2, infForFP32Reg, preMaskScale);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, expFP32Reg, FP32_NUMBER_ZERO, preMaskScale);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, expFP32Reg, FP32_NUMBER_254, p1);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32Reg, FP32_NUMBER_ZERO, p1);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, expFP32Reg2, FP32_NUMBER_ZERO, preMaskScale);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(p2, expFP32Reg2, FP32_NUMBER_254, p2);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, manFP32Reg2, FP32_NUMBER_ZERO, p2);
AscendC::Reg::Adds(extractExpReg, expFP32Reg, 1, preMaskScale);
AscendC::Reg::Adds(extractExpReg2, expFP32Reg2, 1, preMaskScale);
// 根据情况选择指数位是否加一
AscendC::Reg::Select<uint32_t>(expFP32Reg, extractExpReg, expFP32Reg, p1);
AscendC::Reg::Select<uint32_t>(expFP32Reg2, extractExpReg2, expFP32Reg2, p2);
AscendC::Reg::DeInterleave(
    (Reg::RegTensor<uint16_t>&)expFP32Reg, (Reg::RegTensor<uint16_t>&)expFP32Reg2,
    (Reg::RegTensor<uint16_t>&)expFP32Reg, (Reg::RegTensor<uint16_t>&)expFP32Reg2);
AscendC::Reg::Pack(mxScale, (Reg::RegTensor<uint16_t>&)expFP32Reg);
AscendC::Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, vfLen);
AscendC::Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);
AscendC::Reg::ShiftLefts((Reg::RegTensor<uint16_t>&)expFP32Reg, (Reg::RegTensor<uint16_t>&)expFP32Reg,
                         BF16_SHR_NUM, pregAll16);
```

**片段 2** (行 671-697):

```cpp
    for (uint16_t j = 0; j < static_cast<uint16_t>(blockCount); j++) {
        this->template LoadData<calcType>(xAddr, j * dataLen + i * vfLen, xReg, p0);
        CalcElement<roundMode, U, calcType, calcTypeInt>(xReg, scaleReprocal, infForXReg, out,
                                                         preMaskScale2);
        auto addr = yAddr + (j * outDataLenAlign + i * vfLen) / DIGIT_TWO;
        AscendC::Reg::DataCopyUnAlign(addr, out, u1, vfLen / DIGIT_TWO);
        AscendC::Reg::DataCopyUnAlignPost(addr, u1, 0);
    }
} else if constexpr (IsSame<T, half>::value) {
    AscendC::Reg::Mul((AscendC::Reg::RegTensor<float>&)xFP32MaxReg,
                      (AscendC::Reg::RegTensor<float>&)xMaxReg, invDstTypeMax, preMaskScale);
    // 右移获取指数位
    AscendC::Reg::ShiftRights(expFP32Reg, xFP32MaxReg, FP32_SHR_NUM, preMaskScale);
    // And获取尾数位
    AscendC::Reg::And(manFP32Reg, xFP32MaxReg, infForFP32Reg, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, expFP32Reg, FP32_NUMBER_ZERO, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, expFP32Reg, FP32_NUMBER_254, p1);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32Reg, FP32_NUMBER_ZERO, p1);
    AscendC::Reg::Adds(extractExpReg, expFP32Reg, 1, preMaskScale);
    // 根据情况选择指数位是否加一
    AscendC::Reg::Select<uint32_t>(expFP32Reg, extractExpReg, expFP32Reg, p1);

    AscendC::Reg::Pack(expBF16Reg, expFP32Reg);
    AscendC::Reg::Pack(mxScale, expBF16Reg);
    AscendC::Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, vfLen);
    AscendC::Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);
```

**片段 3** (行 780-799):

```cpp

} else if constexpr (IsSame<T, half>::value) {
    AscendC::Reg::Mul((Reg::RegTensor<float>&)xFP32MaxReg, (Reg::RegTensor<float>&)x2MaxReg, invDstTypeMax,
                      preMaskScale);
    Reg::ShiftRights(expFP32Reg, xFP32MaxReg, FP32_SHR_NUM, preMaskScale);

    // And获取尾数位
    AscendC::Reg::And(manFP32Reg, xFP32MaxReg, infForFP32Reg, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, expFP32Reg, FP32_NUMBER_ZERO, preMaskScale);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, expFP32Reg, FP32_NUMBER_254, p1);
    AscendC::Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32Reg, FP32_NUMBER_ZERO, p1);
    AscendC::Reg::Adds(extractExpReg, expFP32Reg, 1, preMaskScale);
    // 根据情况选择指数位是否加一
    AscendC::Reg::Select<uint32_t>(expFP32Reg, extractExpReg, expFP32Reg, p1);

    AscendC::Reg::Pack(expBF16Reg, expFP32Reg);
    AscendC::Reg::Pack(mxScale, expBF16Reg);
    AscendC::Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, tailVfLen);
    AscendC::Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);
```

**要点**: ①Pack 常接 DeInterleave 还原元素顺序后再压缩；②类型为 int16_t/uint16_t 时无显式模板，编译器推导；③同一函数内 half/bf16 分支共用 Pack 模式。

### 实例 7：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Pack 调用次数**: 2
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t+uint16_t+uint32_t`（实参 2 个，类型: int16_t, uint16_t, int32_t, uint32_t, LOWEST, HighLowPart, LOW）
- **语义**: flat_quant 在 __simd_vf__ 作用域中，循环内用 <uint16_t,uint32_t,LOWEST> Pack 把 scale 与 1/scale 压成 uint16，配合 StoreAlign<DIST_PACK_B16> 按打包布局搬出。

（行 500-539）

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

**要点**: ①Pack 后接 StoreAlign<DIST_PACK_B16> 匹配打包存储布局；②__simd_vf__ 上下文使用 AscendC::Reg:: 前缀；③scale 与 1/scale 各用一次 Pack 分别输出。

### 实例 8：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Pack 调用次数**: 8
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t+uint16_t+uint32_t`（实参 2 个，类型: int16_t, uint16_t, int32_t, uint32_t, LOWEST, HighLowPart, LOW）
- **语义**: 双轴量化中对 -1 轴的 Zero/One 两路分别 Pack 成 uint16 scale，Interleave 合并后再 Pack 成 uint8 输出，兼顾两路数据的交织与位宽压缩。

**片段 1** (行 725-739):

```cpp
// 执行条件加1
Reg::Adds(maxFP32_0, expFP32_0, 1, maskFP32);
Reg::Select(manFP32_0, maxFP32_0, expFP32_0, p0);
// Pack到uint16 (INF/NAN→0xFF, zero→0 自然通过条件舍入保持, 在BF16域1/scale中统一处理)
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);

// 左移7位，将E8M0值定位到BF16指数域 (用于计算1/scale)
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);

// --- 输出-1轴scale (uint8) ---
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scale1B16_0);
Reg::DataCopy<uint8_t>(mxScale1Addr + i * oneBlockCountB8_, mxScale1B8, maskReduceB8);

// --- 计算并输出-1轴 1/scale (与原始DynamicMxQuant一致: inf→nan, special→specialExp, 无零值检查) ---
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, scale1BF16, maxEleBF16, maskAll);
```

**片段 2** (行 783-800):

```cpp
Reg::And(manFP32_1, maxFP32_1, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, expFP32_1, NUMBER_ZERO_U32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0Odd, expFP32_1, NUMBER_TWO_FIVE_FOUR, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, manFP32_1, NUMBER_ZERO_U32, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1Odd, expFP32_1, NUMBER_ZERO_U32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1Odd, manFP32_1, NUMBER_HALF_U32, p1Odd);
Reg::MaskOr(p0Odd, p0Odd, p1Odd, maskFP32);
// 链内复用: maxFP32_1→expPlusOne, manFP32_1→extractExp
Reg::Adds(maxFP32_1, expFP32_1, 1, maskFP32);
Reg::Select(manFP32_1, maxFP32_1, expFP32_1, p0Odd);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_1, manFP32_1);

// 合并Zero和One，恢复原始列顺序
Reg::Interleave(scale1B16_0, scale1B16_1, scale1B16_0, scale1B16_1);
// 左移7位得到BF16指数格式 (用于计算1/scale), 复用scale1BF16
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);
// 输出scale (uint8), 复用mxScale1B8
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scale1B16_0);
```

**片段 3** (行 834-853):

```cpp
Reg::And(manFP32_1, maxFP32_1, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, expFP32_1, NUMBER_ZERO_U32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0Odd, expFP32_1, NUMBER_TWO_FIVE_FOUR, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, manFP32_1, NUMBER_ZERO_U32, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1Odd, expFP32_1, NUMBER_ZERO_U32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1Odd, manFP32_1, NUMBER_HALF_U32, p1Odd);
Reg::MaskOr(p0Odd, p0Odd, p1Odd, maskFP32);
// 链内复用: maxFP32_1→expPlusOne, manFP32_1→extractExp
Reg::Adds(maxFP32_1, expFP32_1, 1, maskFP32);
Reg::Select(manFP32_1, maxFP32_1, expFP32_1, p0Odd);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_1, manFP32_1);

// 合并Zero和One
Reg::Interleave(scale1B16_0, scale1B16_1, scale1B16_0, scale1B16_1);
// 复用scale1BF16
Reg::ShiftLefts(scale1BF16, scale1B16_0, SHR_NUM_FOR_BF16, maskAll);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale2OneB8, scale1B16_0);

// 计算1/scale, 复用absMax0 (循环后已死亡) (与原始DynamicMxQuant一致: 无零值检查)
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, scale1BF16, maxEleBF16, maskAll);
```

**要点**: ①Pack 与 Interleave 交替使用实现两路合并压缩；②同一寄存器复用（scale1BF16/mxScale1B8）减少寄存器占用；③uint16→uint8 Pack 输出最终 E8M0 scale。

### 实例 9：dynamic_mx_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub
- **Pack 调用次数**: 3
- **参数模式**: `T3_A1_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t+uint16_t+uint32_t`（实参 1 个，类型: int16_t, uint16_t, int32_t, uint32_t, LOWEST, HighLowPart, LOW）
- **语义**: dynamic_mx_quant 高性能大 tail 分支中，对两路 FP32 scale 分别 Pack 成 uint16 再 Interleave 合并，最后 Pack 成 uint8 mxScale 输出；含 MODE_ONE 条件进位逻辑。

（行 456-504）

```cpp
if constexpr (calcMode == MODE_ONE) {
    Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, mxScale0FP32, FP32_NUMBER_ZERO, pregAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manAbs0FP32, FP32_NUMBER_HALF, p1);
    Reg::MaskXor(p0, p0, p1, pregAll32);
}

Reg::Adds(manAbs0FP32, mxScale0FP32, 1, p0);
Reg::Select(mxScale0FP32, manAbs0FP32, mxScale0FP32, p0);

Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)mxScale0BF16, mxScale0FP32);

if constexpr (!IsSame<xDtype, float>::value) {
    if constexpr (calcMode == MODE_ONE) {
        Reg::Maxs((Reg::RegTensor<float>&)manAbs1FP32, (Reg::RegTensor<float>&)manAbs1FP32, maxLowBound_,
                  pregAll32);
        Reg::Mul((Reg::RegTensor<float>&)manAbs1FP32, (Reg::RegTensor<float>&)manAbs1FP32,
                 (Reg::RegTensor<float>&)invMax, pregAll32);
    } else {
        Reg::Mul((Reg::RegTensor<float>&)manAbs1FP32, (Reg::RegTensor<float>&)manAbs1FP32, dstTypeMaxReg,
                 pregAll32);
    }

    Reg::ShiftRights(mxScale1FP32, manAbs1FP32, FP32_SHR_NUM, pregAll32);
    // 提取尾数
    Reg::And(manAbs1FP32, manAbs1FP32, manForFP32, pregAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, mxScale1FP32, FP32_NUMBER_ZERO, pregAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::LT>(p2, mxScale1FP32, FP32_NUMBER_254, p2);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, manAbs1FP32, FP32_NUMBER_ZERO, p2);

    if constexpr (calcMode == MODE_ONE) {
        Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p3, mxScale1FP32, FP32_NUMBER_ZERO, pregAll32);
        Reg::CompareScalar<uint32_t, CMPMODE::GT>(p3, manAbs1FP32, FP32_NUMBER_HALF, p3);
        Reg::MaskXor(p2, p3, p2, pregAll32);
    }

    Reg::Adds(manAbs1FP32, mxScale1FP32, 1, p2);
    Reg::Select(mxScale1FP32, manAbs1FP32, mxScale1FP32, p2);

    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)mxScale1BF16,
                                                            mxScale1FP32);

    Reg::Interleave(mxScale0BF16, mxScale1BF16, mxScale0BF16, mxScale1BF16);
}

Reg::ShiftLefts(mxScaleBF16, mxScale0BF16, BF16_SHR_NUM, pregAll16);
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint8_t>&)mxScale, mxScale0BF16);

DataCopy(mxScaleAddr, mxScale, pregAll8);
```

**要点**: ①显式 <uint16_t,uint32_t,LOWEST> 与 <uint8_t,uint16_t,LOWEST> 级联压缩；②与 Interleave 配合合并两路 scale；③条件进位（MaskXor+Adds+Select）决定 Pack 前的指数值。

### 实例 10：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Pack 调用次数**: 6
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t+uint16_t+uint32_t`（实参 2 个，类型: int16_t, uint16_t, int32_t, uint32_t, LOWEST, HighLowPart, LOW）
- **语义**: swiglu_mx_quant 非末轴 scale 计算中，对两路 FP32 指数分别 Pack 成 uint16，Interleave 恢复列序后再 Pack 成 uint8，并计算 1/scale。

（行 334-355）

```cpp
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);
Reg::Cast<float, T, CAST_ONE>((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<T>&)absMax1Dim2,
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
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scale1B16_0);
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, scale1BF16, maxEleBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, scale1BF16, biasE8M0, maskAll);
Reg::Sub(absMax0, biasE8M0, scale1BF16, maskAll);
```

**要点**: ①非末轴场景两路 Pack+Interleave 恢复原始列顺序；②aicore 上下文用 Reg:: 前缀；③scale 与 1/scale 分别用 Pack 输出 uint8/uint16。

### 实例 11：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Pack 调用次数**: 2
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t+uint16_t+uint32_t`（实参 2 个，类型: int16_t, uint16_t, int32_t, uint32_t, LOWEST, HighLowPart, LOW）
- **语义**: rms_norm_dynamic_mx_quant 中，对 RMS 归一化后的 max 计算 E8M0 scale，用 <uint16_t,uint32_t,LOWEST> Pack 输出 scale 与 1/scale，配合 DIST_PACK_B16 搬出。

（行 434-462）

```cpp
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

**要点**: ①norm 类算子复用 quant 的 Pack scale 模式；②条件舍入（CompareScalar+MaskOr）决定 Pack 前指数；③scale/1/scale 各 Pack 一次并 DataCopy 搬出。

### 实例 12：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, And, Cast, Compare, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskPattern, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreDist, Sub
- **Pack 调用次数**: 3
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int8_t+uint16_t+uint8_t`（实参 2 个，类型: uint8_t, int8_t, int16_t, uint16_t, LOWEST, HighLowPart, LOW）
- **语义**: 双轴量化（FP4_E2M1）中，对 -1 轴和 -2 轴的奇/偶列分别用 <uint8_t,uint16_t,LOWEST> Pack 输出 uint8 E8M0 scale，含 subnormal/inf/zero 特殊值处理。

**片段 1** (行 999-1017):

```cpp
Reg::Add(addedVal, absMaxDim1, addValue, maskAll);
// 从进位后的结果中提取指数
Reg::And(addedVal, addedVal, expMaskBF16, maskAll);
// subnormal场景: 使用maxExpValue (FP4_E2M1_BF16_MAX_EXP)
Reg::Select<uint16_t>(addedVal, maxExpValue, addedVal, invalidDataMask);
// 减去FP4_E2M1_BF16_MAX_EXP得到指数差值
Reg::Sub(sharedExp, addedVal, maxExpValue, maskAll);
// 右移7位，将BF16指数移到低8位 → E8M0 scale
Reg::ShiftRights(scaleValue, sharedExp, SHR_NUM_FOR_BF16, maskAll);
// INF/NAN → NAN_FOR_FP8_E8M0 (0xFF)
Reg::Select<uint16_t>(scaleValue, scaleValue, nanE8M0, infMask);
// 零值 → 0
Reg::Select<uint16_t>(scaleValue, scaleValue, zero, zeroMask);

// 输出-1轴scale (uint8)
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scaleValue);
Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScale1Addr, mxScale1B8,
                                                                     oneBlockCountB8_, maskReduceB8);
```

**片段 2** (行 1044-1063):

```cpp
// subnormal检查: 指数 < FP4_E2M1_BF16_MAX_EXP
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expOnly, maxExpValue, maskAll);

// 复用addedVal为dim2SubResult
Reg::Sub(addedVal, absMax1Dim2, subNumForScale, maskAll);
// subnormal → 0
Reg::Select<uint16_t>(addedVal, zero, addedVal, invalidDataMask);
// 右移7位 → E8M0 scale, 复用scaleValue为mxScale2B16
Reg::ShiftRights(scaleValue, addedVal, SHR_NUM_FOR_BF16, maskAll);
// INF/NAN → NAN
Reg::Select<uint16_t>(scaleValue, scaleValue, nanE8M0, infMask);
// 零值 → 0
Reg::Select<uint16_t>(scaleValue, scaleValue, zero, zeroMask);

// 输出scale (uint8) — mxScale1B8复用为mxScale2ZeroB8
Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, scaleValue);

// 计算-2轴1/scale — reversedShareExp1复用为reversedShareExp2Zero
// 复用sharedExp为dim2ExpExtract
Reg::And(sharedExp, addedVal, expMaskBF16, maskAll);
```

**片段 3** (行 1069-1087):

```cpp

// ---------- 处理absMax2Dim2 (奇数列, -2轴scale的交织第二部分) ----------
// 再次复用expOnly, addedVal, sharedExp, scaleValue
Reg::And(expOnly, absMax2Dim2, expMaskBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expOnly, expMaskBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expOnly, zero, maskAll);
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expOnly, maxExpValue, maskAll);

Reg::Sub(addedVal, absMax2Dim2, subNumForScale, maskAll);
Reg::Select<uint16_t>(addedVal, zero, addedVal, invalidDataMask);
// 复用scaleValue为mxScale2OneB16
Reg::ShiftRights(scaleValue, addedVal, SHR_NUM_FOR_BF16, maskAll);
Reg::Select<uint16_t>(scaleValue, scaleValue, nanE8M0, infMask);
Reg::Select<uint16_t>(scaleValue, scaleValue, zero, zeroMask);

Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale2OneB8, scaleValue);

// 计算-2轴1/scale — absVal0复用为reversedShareExp2One (循环后死亡，与reversedShareExp1不冲突)
Reg::And(sharedExp, addedVal, expMaskBF16, maskAll);
```

**要点**: ①uint8/uint16 Pack 用于 FP4 量化的单字节 scale 输出；②双轴场景对 -1/-2 轴分别 Pack；③寄存器复用（scaleValue/mxScale1B8）减少占用。

### 实例 13：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Compare, Copy, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, LocalMemBar, MaskMergeMode, MaskReg, Max, MemType, RegTensor, Select, ShiftRights, Sub, UnalignReg, UpdateMask
- **Pack 调用次数**: 6
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: dynamic_mx_quant 中按数据类型分支 Pack：half 类型需两次 Pack（经 fp16MxScale 中转）压缩位宽，其他类型直接一次 Pack 输出 mxScale。

（行 521-528）

```cpp
if constexpr (IsSame<T, half>::value) {
    Reg::Pack(fp16MxScale, mxScaleReg);
    Reg::Pack(mxScale, fp16MxScale);
} else {
    Reg::Pack(mxScale, mxScaleReg);
}
Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, dataLen);
Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);
```

**要点**: ①half 分支需两级 Pack 中转压缩；②编译期 if constexpr 按类型选择 Pack 路径；③无模板参数形式由编译器推导源/目标类型。

### 实例 14：dynamic_block_mx_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, Compare, CreateMask, Duplicate, Gather, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreAlign, Sub
- **Pack 调用次数**: 1
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int8_t+uint16_t+uint8_t`（实参 2 个，类型: uint8_t, int8_t, int16_t, uint16_t, LOWEST, HighLowPart, LOW）
- **语义**: dynamic_block_mx_quant 中，对 BF16 指数做进位和右移后，用 <uint8_t,uint16_t,LOWEST> Pack 生成 uint8 scale，再 Gather 按索引重排后 StoreAlign 搬出。

（行 698-716）

```cpp
// inf/nan值单独处理，结果为E8M0的nan
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expTmpMaxDim, expMaskBF16, maskAll);
// 0值单独处理，结果为0
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expTmpMaxDim, zero, maskAll);
// 指数位不足被量化类型的ele_max时，为invalid场景，结果为0
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expTmpMaxDim, yMaxExp, maskAll);
Reg::Select<uint16_t>(expMaxDim, mantissaForMax, expMaxDim, invalidDataMask);

// 尾数位进位
Reg::Sub(expMaxDim, expMaxDim, mantissaForMax, maskAll);
// 右移7位，BF16的指数位移到了末8位
Reg::ShiftRights(mxScaleB16, expMaxDim, SHR_NUM_FOR_BF16, maskAll);
Reg::Select<uint16_t>(mxScaleB16, mxScaleB16, nanE8M0, infMask);
Reg::Select<uint16_t>(mxScaleB16, mxScaleB16, zero, zeroMask);

Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, mxScaleB16);
Reg::LoadAlign(gatherIndex, gatherIndexAddr);
Reg::Gather(mxScale2B8, mxScale1B8, gatherIndex);
Reg::StoreAlign(mxScale2Addr, mxScale2B8, maskB8);
```

**要点**: ①Pack 后接 Gather 实现按索引重排 scale；②block 量化与 mx 量化共用 Pack uint8 输出模式；③inf/zero/subnormal 特殊值在 Pack 前用 Select 处理。

### 实例 15：broadcast_gradient_args::CalcReduceAxes

- **来源类型**: `__aicore__`
- **共现 API**: AR, Adds, Arange, Cast, ClearSpr, CompareScalar, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, GatherMask, GatherMaskMode, GetSpr, MaskPattern, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Pack 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: int32_t, uint32_t）
- **语义**: broadcast_gradient_args 中，将 int64 索引 Cast 成 int32 后用 Pack 把两个 int32 拼装进一个 uint32 寄存器，再 CompareScalar 找值为 1 的轴并用 GatherMask 收集梯度索引。

（行 89-101）

```cpp
for (uint16_t i = 0; i < vLoopInt64; i++) {
    Reg::Adds(calc_index_reg, init_index_reg, i * vlInt64, maskAll);
    Reg::DataCopy(in_reg, x + i * vlInt64);
    maskCalc = Reg::UpdateMask<int64_t>(srg0);
    // mask未选择位置会置0，对尾块无影响
    Reg::Cast<int32_t, int64_t, castTraitB642B32>(x_int32_reg, in_reg, maskCalc);
    Reg::Pack((Reg::RegTensor<uint32_t>&)x_int32_reg,
                   (Reg::RegTensor<uint64_t>&)x_int32_reg);
    Reg::CompareScalar<int32_t, CMPMODE::EQ>(maskCompare, x_int32_reg, 1, maskAll);
    Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(dst_reg, calc_index_reg,
                                                                       maskCompare);
    Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(y, dst_reg, ureg);
}
```

**要点**: ①Pack 可用于 int64→int32 的元素拼装（非量化场景）；②与 GatherMask 配合实现按条件收集；③index 类算子也复用 Pack 做位宽压缩。

### Pack 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 级联 Pack 压缩指数(uint32→uint16→uint8)，配合 Interleave 交织 yZero/yOne | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 显式三模板参数 Pack<uint16,uint32,LOWEST> 级联压缩 scale | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | uint8/uint16 与 uint16/uint32 两种 Pack 模板完成 scale 压缩链 | __VEC_SCOPE__ |
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Arange, Cast | Pack 指数为 uint8 scale，配合 Gather/Arange 重排字节序 | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | int4 量化分支用 Pack(half→uint16) 前置 int4x2 拼接 | __aicore__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | DeInterleave 后 Pack 生成 mxScale，half 分支两级 Pack | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | 循环内 Pack<uint16,uint32,LOWEST> + StoreAlign<DIST_PACK_B16> 输出 scale/1÷scale | __simd_vf__ |
| dynamic_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 两路 Pack+Interleave 合并后 Pack uint8 输出，寄存器复用 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 两路 FP32 scale 分别 Pack uint16→Interleave→Pack uint8，含条件进位 | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | 非末轴两路 Pack+Interleave 恢复列序，再 Pack uint8 | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | norm 后 Pack<uint16,uint32,LOWEST> 输出 scale/1÷scale + DIST_PACK_B16 | __aicore__ |
| dynamic_mx_quant_with_dual_axis | Add, And, Cast, Compare, CreateMask | FP4 双轴对 -1/-2 轴奇偶列分别 Pack<uint8,uint16,LOWEST> 输出 | __VEC_SCOPE__ |
| dynamic_mx_quant | And, Compare, Copy, DataCopy, DataCopyUnAlign | 按数据类型分支：half 两级 Pack 中转，其他直接一次 Pack | __VEC_SCOPE__ |
| dynamic_block_mx_quant | And, Cast, Compare, CreateMask, Duplicate | Pack<uint8,uint16,LOWEST> 生成 scale + Gather 按索引重排 | __VEC_SCOPE__ |
| broadcast_gradient_args | AR, Adds, Arange, Cast, ClearSpr | int64→int32 Cast 后 Pack 拼装 uint32，配合 GatherMask 收集梯度索引 | __aicore__ |
