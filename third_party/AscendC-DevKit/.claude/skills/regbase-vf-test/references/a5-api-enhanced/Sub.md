# Sub

**页面ID:** atlasascendc_api_07_0357  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0357.html

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

根据mask对源操作数srcReg0、srcReg1进行按元素相减操作，将结果写入目的操作数dstReg。计算公式如下：

![](images/atlasascendc_api_07_0357_img_001.png)

若srcReg0，srcReg1相减产生借位结果时，在MaskReg carry中对应位置每4bit的最低位写0，否则写1。

具体的示例如下：

**表1 **示例说明

| 数据类型 | 是否借位 | 示例说明 |
| --- | --- | --- |
| int32_t数据类型 | 不产生借位 | a_i = 5, b_i = 2 dst_i = a_i - b_i = 3 carry中对应位置每4bit的最低位写1：carry_i = 1 |
| 产生借位 | a_i = 5, b_i = -7 dst_i = a_i - b_i  = 12 carry中对应位置每4bit的最低位写0：carry_i = 0 |  |
| uint32_t数据类型 | 不产生借位 | a_i = 5, b_i = 2, dst_i = a_i - b_i = 3 carry中对应位置每4bit的最低位写1：carry_i = 1 |
| 产生借位 | a_i = 5, b_i = 7 dst_i = a_i - b_i = -2 carry中对应位置每4bit的最低位写0：carry_i = 0 |  |

#### 函数原型

- 计算结果不保留进位

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Sub(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

- 计算结果保留进位

```
template <typename T = DefaultType, typename U>
__simd_callee__ inline void Sub(MaskReg& carry, U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表2 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/half/float/bfloat16_t/uint64_t/int64_t/complex32/complex64 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING, mask未筛选的元素在dstReg中置零。- MERGING, 当前不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表3 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| carry | 输出 | 目的操作数。输出进位值。 类型为MaskReg。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

- 计算结果不保留进位

```
template<typename T>
__simd_vf__ inline void SubVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Sub(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 计算结果保留进位

```
template <typename T>
__simd_vf__ inline void SubVF(__ubuf__ T* dst0Addr, __ubuf__ T* dst1Addr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t repeatTimes, uint16_t oneRepeatSize){

    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg0;
    AscendC::Reg::MaskReg mask;   
    AscendC::Reg::MaskReg carry = AscendC::Reg::CreateMask<uint8_t>();
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Sub(carry, dstReg0, srcReg0, srcReg1, mask);
        // 8*4B=32B align
        AscendC::Reg::StoreAlign<uint32_t, AscendC::Reg::MaskDist::DIST_NORM>((__ubuf__ uint32_t*)dst1Addr + i * 8, carry);
        AscendC::Reg::StoreAlign(dst0Addr + i * oneRepeatSize, dstReg0, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Sub 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, UnalignReg, UpdateMask
- **Sub 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 MX 量化求 1/scale 阶段，用 Sub 计算 scaleBias 减去移位后的指数，得到 scale 的倒数指数。

（行 524-542）

```cpp
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
```

**要点**: ①4 参带 mask 形式，对 mask 选中元素执行 scaleBias - extractExp；②配合 ShiftLefts 把指数移到 BF16 指数域后再做减法实现 1/scale；③结果经 Select 对 inf/nan、零值做特殊值替换。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, UnalignReg, UpdateMask
- **Sub 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: grouped MX 量化中计算 1/scale，用 Sub 执行 bias 减去移位后的尾数指数，配合异常值 Select 处理。

（行 600-619）

```cpp
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
```

**要点**: ①4 参带 mask（preMaskScale）形式；②先 ShiftLefts 把 E8M0 移到 BF16 指数位再用 Sub 求 1/scale；③对 inf/zero 用 Select 替换为 nan/zero 特殊值。

### 实例 3：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignReg
- **Sub 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: SwiGLU 反向双轴 MX 量化中，用 Reg::Sub 计算 scaleBias 减移位指数得到 1/scale 的半精度指数。

（行 951-968）

```cpp
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
```

**要点**: ①Reg:: 形式，4 参带 maskAll32；②配合 Adds/Select 实现指数进位与异常值替换；③Pack 串联 uint32→uint16→uint8 完成 E8M0 scale 输出。

### 实例 4：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, UnalignReg, UpdateMask
- **Sub 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 动态量化求 (max - min) 范围，用 Sub 计算最终最大值减最终最小值，作为缩放因子分母。

（行 370-389）

```cpp
AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
    vreg1, xAddr + multiRow * rowCount + (vfLoop - 1) * VL);
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
```

**要点**: ①4 参无选择性 mask，第 4 参 preg5 为全有效谓词寄存器；②配合 ReduceMax/ReduceMin 跨 block 归约得到全局极值；③结果经 Muls 得到 scale 后 DataCopyUnAlign 搬出。

### 实例 5：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, Interleave, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, UnalignReg, UpdateMask
- **Sub 调用次数**: 8
- **参数模式**: `T0_A4_M0_TYPEint16_t+uint16_t`（实参 4 个，类型: int16_t, uint16_t）
- **语义**: dynamic_mx_quant 在 half/bf16 路径下，用 Sub 计算 bias 减去移位后的指数（uint16 域），得到 1/scale 倒数指数。

**片段 1** (行 659-678):

```cpp
AscendC::Reg::Pack(mxScale, (Reg::RegTensor<uint16_t>&)expFP32Reg);
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
```

**片段 2** (行 693-713):

```cpp
AscendC::Reg::Pack(expBF16Reg, expFP32Reg);
AscendC::Reg::Pack(mxScale, expBF16Reg);
AscendC::Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, vfLen);
AscendC::Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);

AscendC::Reg::ShiftLefts(expFP32Reg, expFP32Reg, FP32_SHR_NUM, preMaskScale);

// 求1/scale
AscendC::Reg::Compare<calcTypeInt, CMPMODE::NE>(infMask, expFP32Reg, infForXReg, preMaskScale);
AscendC::Reg::Compare<calcTypeInt, CMPMODE::EQ>(specialDataMask, expFP32Reg, biasReg, preMaskScale);
AscendC::Reg::Sub(scaleReprocal, biasReg, expFP32Reg, preMaskScale);
AscendC::Reg::Select<calcTypeInt>(scaleReprocal, scaleReprocal, nan, infMask);
AscendC::Reg::Select<calcTypeInt>(scaleReprocal, specialExp, scaleReprocal, specialDataMask);
// 求data value
for (uint16_t j = 0; j < static_cast<uint16_t>(blockCount); j++) {
    this->template LoadData<calcType>(xAddr, j * dataLen + i * vfLen, xReg, p0);
    CalcElement<roundMode, U, calcType, calcTypeInt>(xReg, scaleReprocal, infForXReg, out, p0);
    auto addr = yAddr + (j * outDataLenAlign + i * vfLen) / DIGIT_TWO;
    AscendC::Reg::DataCopyUnAlign(addr, out, u1, vfLen / DIGIT_TWO);
    AscendC::Reg::DataCopyUnAlignPost(addr, u1, 0);
}
```

**片段 3** (行 756-771):

```cpp
AscendC::Reg::Pack(mxScale, (Reg::RegTensor<uint16_t>&)expFP32Reg);
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

**要点**: ①4 参无选择性 mask（pregAll16 全有效），类型显式转 uint16；②三个片段对应头部/中间/尾部不同 vf 长度分支，模式一致；③结果经 Select 对 inf/特殊指数/零做替换。

### 实例 6：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, UnPack
- **Sub 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: SwiGLU 双轴 MX 量化 -1 轴求 1/scale，用 Reg::Sub 算 bias 减移位指数得到倒数指数。

（行 1024-1044）

```cpp
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
```

**要点**: ①4 参带 maskAll32；②先 Adds 进位 + Select 异常处理得 extractExp，再 ShiftLefts + Sub 得 1/scale；③两次 Pack 输出 scale 与 1/scale 的 int16 结果。

### 实例 7：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, UpdateMask
- **Sub 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: flat_quant 在 __simd_vf__ 上下文中，用 Reg::Sub 计算 bias 减移位指数得到 1/scale（fp4 量化路径）。

（行 519-536）

```cpp
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
```

**要点**: ①4 参带 preMaskScale（Mask 谓词）；②来源类型 __simd_vf__，配合 CompareScalar/MaskAnd 精确控制有效元素；③对 fp4Nan/zero 用 Select 替换。

### 实例 8：dynamic_mx_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights
- **Sub 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: dynamic_mx_quant 高性能大尾部版本中，在 BF16 域用 Sub 计算 biasU16 减 mxScaleBF16 得到 1/scale 的反向指数。

（行 467-511）

```cpp
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

// 求1/scale
Reg::Compare<uint16_t, CMPMODE::NE>(p0, mxScaleBF16, maxEleU16, pregAll16);
Reg::Compare<uint16_t, CMPMODE::EQ>(p1, mxScaleBF16, biasU16, pregAll16);
Reg::Sub(reversedShareExpBF16, biasU16, mxScaleBF16, pregAll16);
Reg::Select<uint16_t>(reversedShareExpBF16, reversedShareExpBF16, nanU16, p0);
Reg::Select<uint16_t>(reversedShareExpBF16, specialExpU16, reversedShareExpBF16, p1);
DataCopy(tmpAddr, reversedShareExpBF16, pregAll16);
```

**要点**: ①4 参无选择性 mask（pregAll16 全有效）；②先经 Maxs/Mul/ShiftRights/And 提取尾数与指数，再 Sub 求倒数；③结果 Select 对 nan/特殊值替换后 DataCopy 搬出。

### 实例 9：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, UpdateMask
- **Sub 调用次数**: 4
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: uint32_t, int32_t）
- **语义**: complex_abs 算子中，用 Sub 从浮点数中减去指数因子（vA - vA0）提取尾数部分，配合 subnormal 放大处理复数绝对值。

（行 121-142）

```cpp

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
```

**要点**: ①4 参带 preg（全有效谓词），操作 uint32 域位运算提取尾数；②两次 Sub 分别对 vA、vB 减去同一指数因子 vA0，统一对齐到同一指数空间；③配合 ShiftRights/ShiftLefts 隔离指数、Select 处理 subnormal。

### 实例 10：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, UpdateMask
- **Sub 调用次数**: 3
- **参数模式**: `T1_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: fake_quant 逐通道量化中，用显式 <float> 模板的 Sub 计算 clip 后的值减去 nudgedMin 得到 shift 偏移量。

**片段 1** (行 364-365):

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(outerLoop); ++i) {
```

**片段 2** (行 429-448):

```cpp
AscendC::Reg::Adds<float>(vregNudgedMin, vregNudgedMin, qMin, mask);
AscendC::Reg::Mul<float>(vregNudgedMin, vregNudgedMin, vregScaleSafe, mask);

AscendC::Reg::Muls<float>(vregNudgedMax, vregNudgedZp, -1.0f, mask);
AscendC::Reg::Adds<float>(vregNudgedMax, vregNudgedMax, qMax, mask);
AscendC::Reg::Mul<float>(vregNudgedMax, vregNudgedMax, vregScaleSafe, mask);

// -----------------------------------------------------------------
// 阶段 3：主公式
// -----------------------------------------------------------------
// clip：clamped = min(max(x, nudgedMin), nudgedMax)
AscendC::Reg::Min<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregClamped, vregX, vregNudgedMax, mask);
AscendC::Reg::Max<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregClamped, vregClamped, vregNudgedMin,
                                                               mask);
// shift = clamped - nudgedMin
AscendC::Reg::Sub<float>(vregShift, vregClamped, vregNudgedMin, mask);
// scaled = shift * invScaleSafe + 0.5
//        与 TF 一致：使用独立计算的 inv_scale = qRange/(max-min)，
//        而非 shift/scale（二次舍入误差）
AscendC::Reg::Mul<float>(vregScaled, vregShift, vregInvScaleSafe, mask);
```

**要点**: ①4 参带 mask，显式模板参数 <float>；②配合 Min/Max 做 clip，再 Sub 得 shift，乘 invScale 得量化值；③使用 invScale 而非 shift/scale 避免二次舍入误差。

### 实例 11：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, UpdateMask
- **Sub 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: add_rms_norm 动态 MX 量化中，用 Reg::Sub 计算 scaleBias 减移位指数得到 1/scale 倒数指数。

（行 475-493）

```cpp
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
```

**要点**: ①4 参带 preMaskScale（Mask 谓词）；②配合 CompareScalar/MaskAnd/MaskOr 精确判定有效与进位元素；③Select 替换 inf/zero 后 Pack 输出。

### 实例 12：dynamic_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Adds, Cast, CreateMask, DataCopy, Div, DivSpecificMode, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, ReduceMax, ReduceMin, RegTensor, RegTraitNumOne, StoreDist, UpdateMask
- **Sub 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: dynamic_quant 大形状 isFinal 分支中，用 Sub 计算归约后的 max 减 min 得到量化范围，RegTraitNumOne 单元素寄存器。

（行 512-534）

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

**要点**: ①4 参带 maskAll（全有效），结果为单元素 RegTraitNumOne 寄存器；②仅 isFinal 分支算 scale/offset，非 final 直接搬出极值；③配合 Muls/Div/Adds 推导 scale 与 offset。

### 实例 13：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist
- **Sub 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: RMS Norm 动态 MX 量化中，用 Reg::Sub 计算 scaleBias 减移位指数得到 1/scale。

（行 441-459）

```cpp
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
```

**要点**: ①4 参带 preMaskScale（Mask 谓词）；②配合 Adds 进位、CompareScalar/MaskAnd/MaskOr 控制进位判定；③Select 替换异常值后 Pack 输出 scale 与 1/scale。

### 实例 14：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Compare, Copy, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, LocalMemBar, MaskMergeMode, MaskReg, Max, MemType, Pack, RegTensor, Select, ShiftRights, UnalignReg, UpdateMask
- **Sub 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: dynamic_mx_quant 的 fp4x2_e2m1_t 路径，用 Sub 先对最大指数做偏移修正（减 subNumForScale），再用 bias 减指数求 1/scale。

**片段 1** (行 472-477):

```cpp
if constexpr (IsSame<U, fp4x2_e2m1_t>::value) {
    Reg::Compare<calcTypeInt, CMPMODE::LT>(invalidDataMask, expMaxReg, fp4MaxExpReg, mask);
    Reg::Sub(expMaxReg, xMaxReg, subNumForScale, mask);
    Reg::Select<calcTypeInt>(expMaxReg, zeroReg, expMaxReg, invalidDataMask);
    Reg::And(expMaxReg, expMaxReg, infForXReg, mask);
}
```

**片段 2** (行 519-536):

```cpp
Reg::ShiftRights(mxScaleReg, expMaxReg, this->shrNum_, mask);
Reg::Select<calcTypeInt>(mxScaleReg, mxScaleReg, fp8Nan, infMask);
if constexpr (IsSame<T, half>::value) {
    Reg::Pack(fp16MxScale, mxScaleReg);
    Reg::Pack(mxScale, fp16MxScale);
} else {
    Reg::Pack(mxScale, mxScaleReg);
}
Reg::DataCopyUnAlign(mxScaleAddr, mxScale, u1, dataLen);
Reg::DataCopyUnAlignPost(mxScaleAddr, u1, 0);

// 求1/scale
Reg::Compare<calcTypeInt, CMPMODE::NE>(zeroMask, expMaxReg, zeroReg, mask);
Reg::Compare<calcTypeInt, CMPMODE::EQ>(specialDataMask, expMaxReg, bias, mask);
Reg::Sub(scaleReprocal, bias, expMaxReg, mask);
Reg::Select<calcTypeInt>(scaleReprocal, scaleReprocal, nan, infMask);
Reg::Select<calcTypeInt>(scaleReprocal, scaleReprocal, zeroReg, zeroMask);
Reg::Select<calcTypeInt>(scaleReprocal, specialExp, scaleReprocal, specialDataMask);
```

**要点**: ①4 参带 mask，两处 Sub 分别做指数修正与求倒数；②fp4x2_e2m1_t 特殊路径用 Compare LT 判定 invalid 后 Select 置零；③1/scale 经 Select 对 inf/特殊/零值替换。

### 实例 15：dynamic_block_mx_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, Compare, CreateMask, Duplicate, Gather, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreAlign
- **Sub 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: dynamic_block_mx_quant 中，用 Sub 做尾数进位修正（expMax - mantissaForMax）并求 1/scale（bias - exp）。

（行 692-724）

```cpp
Reg::Max(expMaxDim, expMax1Dim2, expMax2Dim2, maskAll);
// ReduceMax一个block，即16个数，配合上一步，可以计算出每32*32个数的最大值，一共256/32个
Reg::ReduceMaxWithDataBlock(expMaxDim, expMaxDim, maskAll);

Reg::And(expTmpMaxDim, expMaxDim, expMaskBF16, maskAll);

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
Reg::And(expTmpMaxDim, expMaxDim, expMaskBF16, maskAll);
// compute  1/scale
// 只有在E1M2时，yMaxExp=0，xTmp0ExpBF16可能会等于biasE8M0
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, expTmpMaxDim, biasE8M0, maskAll);
Reg::Sub(reversedExp, biasE8M0, expTmpMaxDim, maskAll);
Reg::Select<uint16_t>(reversedExp, reversedExp, nanBF16, infMask);
Reg::Select<uint16_t>(reversedExp, reversedExp, zero, zeroMask);
Reg::Select<uint16_t>(reversedExp, specialExp, reversedExp, invalidDataMask);
```

**要点**: ①4 参带 maskAll，两次 Sub 分别用于进位与求倒数；②配合 ReduceMaxWithDataBlock 跨 block 归约最大指数；③Gather 按索引收集 scale 后再求 1/scale，Select 处理 inf/zero/invalid。

### Sub 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 移位后 bias 减指数求 1/scale，Select 替换 inf/nan/zero | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | E8M0 移位后 Sub 求 1/scale，分组异常值处理 | __VEC_SCOPE__ |
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Arange, Cast | Reg 双轴 Sub 求 1/scale，Pack 链输出 E8M0 | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | Sub 求 max-min 量化范围，配合 Reduce 极值归约 | __aicore__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | uint16 域 bias 减指数求 1/scale，头/尾多分支一致 | __VEC_SCOPE__ |
| swiglu_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | Reg -1 轴 Sub 求 1/scale，双 Pack 输出 | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | __simd_vf__ 中 Sub 求 1/scale（fp4 路径），MaskAnd 控制有效元素 | __simd_vf__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | BF16 域 biasU16 减 mxScaleBF16 求 1/scale，高性能大尾部 | __VEC_SCOPE__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | Sub 减指数因子提取尾数，subnormal 放大对齐 | __aicore__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | <float> 模板 Sub 算 clip 偏移 shift，invScale 量化 | __VEC_SCOPE__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | Reg Sub 求 1/scale，CompareScalar 控制进位 | __aicore__ |
| dynamic_quant | Abs, Adds, Cast, CreateMask, DataCopy | isFinal 分支 Sub 求 max-min，RegTraitNumOne 单元素 | __VEC_SCOPE__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | Reg Sub 求 1/scale，Adds 进位 | __aicore__ |
| dynamic_mx_quant | And, Compare, Copy, DataCopy, DataCopyUnAlign | fp4x2_e2m1_t 路径双 Sub（指数修正 + 求 1/scale） | __VEC_SCOPE__ |
| dynamic_block_mx_quant | And, Cast, Compare, CreateMask, Duplicate | Sub 尾数进位 + 1/scale，ReduceMaxWithDataBlock 跨 block 归约 | __VEC_SCOPE__ |

