# Interleave

**页面ID:** atlasascendc_api_07_0335  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0335.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品            AI Core | x |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

将源操作数src0和src1中的元素交织存入目的操作数dst0和dst1中。交织排列方式如下图所示，其中每个方格代表一个元素：

![](images/atlasascendc_api_07_0335_img_001.png)

#### 函数原型

```
template <typename T>
__simd_callee__ inline void Interleave(MaskReg& dst0, MaskReg& dst1, MaskReg& src0, MaskReg& src1)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | MaskReg所支持的数据类型，决定了交织的位宽大小，例如对于uint32_t类型，交织时以4bit为一组。          Atlas 350 加速卡支持的数据类型为：b8/b16/b32 |

**表2 **参数说明

| 参数名 | 描述 |
| --- | --- |
| dst0 | 目的操作数。 |
| dst1 | 目的操作数。 |
| src0 | 源操作数。 |
| src1 | 源操作数。 |

#### 约束说明

无

#### 调用示例

```
template <typename T>
__simd_vf__ inline void MaskInterleaveDeInterleaveVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg maskFull = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg maskM3 = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::M3>();
    AscendC::Reg::MaskReg newMask0;
    AscendC::Reg::MaskReg newMask1;
    AscendC::Reg::Interleave<T>(newMask0, newMask1, maskFull, maskM3);
    AscendC::Reg::DeInterleave<T>(newMask0, newMask1, newMask0, newMask1);
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Adds(srcReg, srcReg, 0, newMask0);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Interleave 实例

### 实例 1：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Interleave 调用次数**: 8
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在分组动态 MX 量化中，先用 Interleave 将 BF16 最大值与全 0 寄存器交织（使 Cast castTraitZero 可一次取出全部有效值转 FP32），再用 Interleave 合并 yZero/yOne 两个 FP8 半部以恢复原始列顺序。

**片段 1** (行 565-579):

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
```

**片段 2** (行 633-647):

```cpp
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
```

**要点**: 1) `Interleave(reg, zeroReg, reg, zeroReg)` 模式把紧凑存放的有效值分散到偶数位，配合 `castTraitZero` 一次性取数转 FP32；2) `Interleave(yZero, yOne, yZero, yOne)` 把 Zero/One 两半合并回连续排列；3) 4 个参数均为 RegTensor，无 mask 参数。

### 实例 2：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, LocalMemBar, MaskMergeMode, MaskPattern, MaskReg, Max, MemType, Mul, Pack, RegTensor, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Interleave 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在 BF16 路径下用 Interleave 将 xMaxReg 与 zeroReg 交织，使后续 Cast castTraitZero 可一次性把最大值转为 FP32 进行缩放。

（行 289-296）

```cpp
if constexpr (IsSame<T, bfloat16_t>::value) {
    Reg::Interleave(xMaxReg, zeroReg, xMaxReg, zeroReg);
    Reg::Cast<float, T, castTraitZero>((Reg::RegTensor<float>&)xFP32MaxReg, (Reg::RegTensor<T>&)xMaxReg,
                                       mask16);
    Reg::Mul((Reg::RegTensor<float>&)xFP32MaxReg, (Reg::RegTensor<float>&)xFP32MaxReg, dstTypeMaxReg, mask32);
} else {
    Reg::Mul((Reg::RegTensor<float>&)xFP32MaxReg, (Reg::RegTensor<float>&)xMaxReg, dstTypeMaxReg, mask32);
}
```

**要点**: 1) 仅 `bfloat16_t` 分支需要 `Interleave` 与 0 交织，`half` 分支直接乘；2) 交织后 Cast Zero 取偶数位有效值；3) Interleave 模板参数 T 由调用点类型决定。

### 实例 3：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, MaskMergeMode, MaskReg, MaskUnPack, Max, Min, PostLiteral, ReduceMax, RegLayout, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **Interleave 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在逐行块量化循环中，用 Cast 把输入拆成 Zero/One 两个 FP32 半部，Interleave 重新交织后分别做 Div 求 scale，再按 OUT_TYPE 分支 Cast 回低精度。

（行 500-536）

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

**要点**: 1) `Interleave(vReg11, vReg12, vReg9, vReg10)` 把 Cast 产生的 Zero/One 半部重新交织为相邻排列；2) 交织后两路分别 Div 再 Cast，最终用 MaskUnPack 拆 mask 分段 Store；3) 使用 Reg 命名空间。

### 实例 4：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Interleave 调用次数**: 6
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 双轴量化中先用 Interleave 将 ReduceMax 紧凑存放的 8 个 max 与 0 交织（使 Cast Zero 一次取出全部 8 值转 FP32），再用 Interleave 合并 scale 的 Zero/One 半部恢复列顺序。

**片段 1** (行 697-712):

```cpp
Reg::Max(absMax2Dim2, absMax2Dim2, absMax1, maskAll);

// ============================================================
// 5. 计算-1轴CuBALS Scale (FP32精度)
//    ReduceMaxWithDataBlock后，8个max紧凑存储在寄存器前8个位置
//    与0交织后，Cast Zero一次处理全部8个值转为FP32
//    (与原始DynamicMxQuant的ComputeCuBLAS一致)
// ============================================================

// 与0交织: [v0,0,v1,0,...,v7,0,...] → Cast Zero可一次取出全部8个有效值
Reg::Interleave(absMaxDim1, zeroB16, absMaxDim1, zeroB16);
Reg::Cast<float, xDtype, castTraitXdtypetoFp32Zero>((Reg::RegTensor<float>&)maxFP32_0,
                                                         (Reg::RegTensor<xDtype>&)absMaxDim1, maskAll);
// 乘以 1/Amax(DType): max * invDtypeMax
Reg::Mul((Reg::RegTensor<float>&)maxFP32_0, (Reg::RegTensor<float>&)maxFP32_0,
              (Reg::RegTensor<float>&)invMax, maskFP32);
```

**片段 2** (行 782-800):

```cpp
Reg::ShiftRights(expFP32_1, maxFP32_1, SHR_NUM_FOR_FP32, maskFP32);
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

**要点**: 1) `Interleave(absMaxDim1, zeroB16, absMaxDim1, zeroB16)` 把 [v0..v7] 扩展为 [v0,0,v1,0,...] 供 Cast Zero 取数；2) `Interleave(scale1B16_0, scale1B16_1, ...)` 合并奇偶半部恢复列顺序；3) 寄存器复用降低开销。

### 实例 5：dynamic_mx_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub
- **Interleave 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在高吞吐大尾部场景的 FP32 精度 scale 计算中，用 Pack 取低位 BF16 后 Interleave 合并 mxScale0/mxScale1 两个半部，再 ShiftLefts 得到 BF16 指数格式。

（行 467-500）

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
```

**要点**: 1) `Interleave(mxScale0BF16, mxScale1BF16, ...)` 合并相邻两路 scale；2) 交织在 Pack 取低位之后、ShiftLefts 之前；3) 仅 `xDtype != float` 分支执行。

### 实例 6：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Interleave 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: SwiGLU 量化算 CuBALS scale 时，先对奇数半做指数/尾数拆分与舍入判断，Pack 取低位后用 Interleave 合并 scale0/scale1 奇偶半部，再 ShiftLefts 与 Pack 输出 uint8 scale。

（行 335-353）

```cpp
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
```

**要点**: 1) `Interleave(scale1B16_0, scale1B16_1, ...)` 合并 Zero/One 半部恢复列顺序；2) 使用 Reg 命名空间、`__aicore__` 上下文；3) 交织后立即 ShiftLefts 定 BF16 指数格式并 Pack 成 uint8。

### 实例 7：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, ClearSpr, Compare, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, GatherMask, GatherMaskMode, LoadDist, MaskInterleave, MaskReg, PostLiteral, RegTensor, SubCarryOut, SubCarryOuts, UnalignReg, UpdateMask
- **Interleave 调用次数**: 1
- **参数模式**: `T1_A4_M0_TYPEint32_t`（实参 4 个，类型: int32_t）
- **语义（待补充）**: 稀疏切片中先做 int64 减法产生 carry，GatherMask 按选择掩码聚集高低半，再用 Interleave<int32_t> 把高低半交织合并为完整结果，并用 MaskInterleave 同步处理掩码。

（行 720-737）

```cpp

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

// vreg interleave and mask interleave
Reg::Interleave<int32_t>(vregGatherResult0, vregGatherResult1, vregGatherLowerHalf,
                              vregGatherHigherHalf);
Reg::MaskInterleave<int32_t>(pregSelectFinal0, pregSelectFinal1, pregGathered, pregGathered);
```

**要点**: 1) 显式模板 `Interleave<int32_t>`，4 个实参，类型 token int32_t；2) 与 GatherMask/MaskInterleave 配合完成稀疏数据重组；3) DeInterleave 为其逆操作。

### 实例 8：dynamic_mx_quant::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, StoreAlign, StoreDist
- **Interleave 调用次数**: 6
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 尾轴量化中把 FP32 结果 Cast 成 BF16 后 Pack 取低位，用三次 Interleave 逐级合并（先合 zero+one 各组、再合组 0+1），最终 Cast 到 FP4。

（行 1353-1375）

```cpp
Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(x0ZeroBF16, x0Zero, maskFP32);
Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(x0OneBF16, x0One, maskFP32);
Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(x1ZeroBF16, x1Zero, maskFP32);
Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(x1OneBF16, x1One, maskFP32);

Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)x0ZeroBF16,
                                                        (Reg::RegTensor<uint32_t>&)x0ZeroBF16);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)x0OneBF16,
                                                        (Reg::RegTensor<uint32_t>&)x0OneBF16);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)x1ZeroBF16,
                                                        (Reg::RegTensor<uint32_t>&)x1ZeroBF16);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)x1OneBF16,
                                                        (Reg::RegTensor<uint32_t>&)x1OneBF16);

// Merge zero+one bf16 per group
Reg::Interleave(x0ZeroBF16, x0OneBF16, x0ZeroBF16, x0OneBF16);
Reg::Interleave(x1ZeroBF16, x1OneBF16, x1ZeroBF16, x1OneBF16);

// Merge group 0+1 bf16
Reg::Interleave(x0ZeroBF16, x1ZeroBF16, x0ZeroBF16, x1ZeroBF16);

Reg::Cast<U, bfloat16_t, castTrait>(xExp0FP4, x0ZeroBF16, maskB16);
Reg::Cast<U, bfloat16_t, castTrait>(xExp1FP4, x1ZeroBF16, maskB16);
```

**要点**: 1) 三级 Interleave 级联合并：组内 zero/one → 组间 group0/group1；2) 每次 Interleave 前都先 Cast+Pack 取 BF16 低位；3) 合并后一次 Cast 到 FP4 输出。

### 实例 9：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, ClearSpr, CompareScalar, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, GatherMask, GatherMaskMode, HighLowPart, MaskInterleave, MaskPack, MaskUnPack, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Interleave 调用次数**: 1
- **参数模式**: `T1_A1_M0_TYPEint32_t`（实参 1 个，类型: int32_t）
- **语义（待补充）**: int64 路径下先 MaskUnPack 解包选择掩码，DeInterleave 把输入拆成高低半，GatherMask 聚集后用 Interleave<int32_t> 重新交织合并为完整结果。

（行 810-829）

```cpp
if constexpr (sizeof(T1) == sizeof(int64_t)) {
    Reg::MaskUnPack<Reg::HighLowPart::LOWEST>(pregSelected, pregSelectB8);
    Reg::MaskUnPack<Reg::HighLowPart::LOWEST>(pregSelected, pregSelected);
    Reg::DeInterleave<int32_t>(vregInputLowerHalf, vregInputHigherHalf,
                                    (Reg::RegTensor<int32_t>&)vregInput,
                                    (Reg::RegTensor<int32_t>&)vregInput);
    Reg::GatherMask<int32_t, Reg::GatherMaskMode::NO_STORE_REG>(vregGatherLowerHalf,
                                                                          vregInputLowerHalf, pregSelected);
    Reg::GatherMask<int32_t, Reg::GatherMaskMode::NO_STORE_REG>(
        vregGatherHigherHalf, vregInputHigherHalf, pregSelected);
    Reg::Interleave<int32_t>((Reg::RegTensor<int32_t>&)vregGathered, vregGatherTemp,
                                  vregGatherLowerHalf, vregGatherHigherHalf);
} else if constexpr (sizeof(T1) == sizeof(int8_t)) {
    pregSelected = pregSelectB8;
} else if constexpr (sizeof(T1) == sizeof(int16_t)) {
    Reg::MaskUnPack<Reg::HighLowPart::LOWEST>(pregSelected, pregSelectB8);
} else if constexpr (sizeof(T1) == sizeof(int32_t)) {
    Reg::MaskUnPack<Reg::HighLowPart::LOWEST>(pregSelected, pregSelectB8);
    Reg::MaskUnPack<Reg::HighLowPart::LOWEST>(pregSelected, pregSelected);
}
```

**要点**: 1) `Interleave<int32_t>` 单实参形式（参数模式 T1_A1）；2) DeInterleave 与 Interleave 互为逆操作，先拆后合；3) 通过 `sizeof(T1)` 编译期分派不同位宽路径。

### 实例 10：top_k_v2::ReverseInputData

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, DataCopy, DeInterleave, Duplicate, Histograms, HistogramsBinType, HistogramsType, MaskPack, MaskReg, PostLiteral, RegTensor, ShiftRights, Sub, UpdateMask
- **Interleave 调用次数**: 12
- **参数模式**: `T0_A4_M0_TYPEint16_t+uint16_t`（实参 4 个，类型: int16_t, uint16_t）
- **语义（待补充）**: Top-K 基数排序中把 B16 直方图累加和通过 Interleave 与 zeroVector 交织扩展为 B32/B64，实现位宽提升以便后续全局前缀和与存储。

（行 121-162）

```cpp
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        excusiveSumGlobalOne, blockExcusivePtrRead, ONE_TIMES_B32_NUM);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        excusiveSumGlobalTwo, blockExcusivePtrRead, ONE_TIMES_B32_NUM);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        excusiveSumGlobalThree, blockExcusivePtrRead, ONE_TIMES_B32_NUM);
    // add block ans to global excusive
    Reg::Add(excusiveSumGlobalZero, excusiveSumGlobalZero, excusiveSumZeroB32, predicateDefault);
    Reg::Add(excusiveSumGlobalOne, excusiveSumGlobalOne, excusiveSumOneB32, predicateDefault);
    Reg::Add(excusiveSumGlobalTwo, excusiveSumGlobalTwo, excusiveSumTwoB32, predicateDefault);
    Reg::Add(excusiveSumGlobalThree, excusiveSumGlobalThree, excusiveSumThreeB32, predicateDefault);
    // vsts to global
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        blockExcusivePtrWrite, excusiveSumGlobalZero, ONE_TIMES_B32_NUM, predicateDefault);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        blockExcusivePtrWrite, excusiveSumGlobalOne, ONE_TIMES_B32_NUM, predicateDefault);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        blockExcusivePtrWrite, excusiveSumGlobalTwo, ONE_TIMES_B32_NUM, predicateDefault);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        blockExcusivePtrWrite, excusiveSumGlobalThree, ONE_TIMES_B32_NUM, predicateDefault);
} else {
    // cast B32 to B64
    Reg::RegTensor<int64_t> excusiveSumZeroB64A, excusiveSumZeroB64B, excusiveSumOneB64A,
        excusiveSumOneB64B;
    Reg::RegTensor<int64_t> excusiveSumTwoB64A, excusiveSumTwoB64B, excusiveSumThreeB64A,
        excusiveSumThreeB64B;
    Reg::Interleave(
        (Reg::RegTensor<uint16_t>&)excusiveSumZeroB64A,
        (Reg::RegTensor<uint16_t>&)excusiveSumZeroB64B,
        (Reg::RegTensor<uint16_t>&)excusiveSumZeroB32, zeroVector);
    Reg::Interleave(
        (Reg::RegTensor<uint16_t>&)excusiveSumOneB64A,
        (Reg::RegTensor<uint16_t>&)excusiveSumOneB64B,
        (Reg::RegTensor<uint16_t>&)excusiveSumOneB32, zeroVector);
    Reg::Interleave(
        (Reg::RegTensor<uint16_t>&)excusiveSumTwoB64A,
        (Reg::RegTensor<uint16_t>&)excusiveSumTwoB64B,
        (Reg::RegTensor<uint16_t>&)excusiveSumTwoB32, zeroVector);
    Reg::Interleave(
        (Reg::RegTensor<uint16_t>&)excusiveSumThreeB64A,
        (Reg::RegTensor<uint16_t>&)excusiveSumThreeB64B,
        (Reg::RegTensor<uint16_t>&)excusiveSumThreeB32, zeroVector);
```

**要点**: 1) `Interleave((RegTensor<uint16_t>&)B32A, B32B, B16, zeroVector)` 把 16 位值与 0 交织扩展到 32 位；2) 多次 Interleave 处理 zero/one/two/three 四路；3) 类型 token int16_t+uint16_t，4 实参。

### 实例 11：top_k_v2::ReverseInputData

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, DataCopy, DeInterleave, Duplicate, Histograms, HistogramsBinType, HistogramsType, MaskPack, MaskReg, PostLiteral, RegTensor, ShiftRights, Sub, UpdateMask
- **Interleave 调用次数**: 12
- **参数模式**: `T0_A1_M0_TYPEint16_t+uint16_t`（实参 1 个，类型: int16_t, uint16_t）
- **语义（待补充）**: B64 路径的 Top-K 基数排序中，用 Interleave 把 B16 累加和先扩展到 B32，再进一步交织扩展到 B64，配合 DataCopy 完成全局前缀和累加与回写。

（行 104-151）

```cpp
        Reg::HistogramsType::FREQUENCY>(histVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::FREQUENCY>(histVectorOne, shiftVecU8LowBit, maskU8);
    // get cusum
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::ACCUMULATE>(chistVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::ACCUMULATE>(chistVectorOne, shiftVecU8LowBit, maskU8);
}
// get excusive sum
Reg::RegTensor<uint16_t> excusiveSumZero, excusiveSumOne;
Reg::Sub(excusiveSumZero, chistVectorZero, histVectorZero, predicateDefaultB16);
Reg::Sub(excusiveSumOne, chistVectorOne, histVectorOne, predicateDefaultB16);
// case B16 to B32
Reg::RegTensor<int32_t> excusiveSumZeroB32, excusiveSumOneB32, excusiveSumTwoB32, excusiveSumThreeB32;
Reg::Interleave((Reg::RegTensor<uint16_t> &)excusiveSumZeroB32, (Reg::RegTensor<uint16_t> &)excusiveSumOneB32, excusiveSumZero, zeroVector);
Reg::Interleave((Reg::RegTensor<uint16_t> &)excusiveSumTwoB32, (Reg::RegTensor<uint16_t> &)excusiveSumThreeB32, excusiveSumOne, zeroVector);
if constexpr (IsSameType<T_INDEX, int32_t>::value) {
    // load global excusive
    Reg::RegTensor<int32_t> excusiveSumGlobalZero, excusiveSumGlobalOne, excusiveSumGlobalTwo, excusiveSumGlobalThree;
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(excusiveSumGlobalZero, blockExcusivePtrRead, ONE_TIMES_B32_NUM);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(excusiveSumGlobalOne, blockExcusivePtrRead, ONE_TIMES_B32_NUM);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(excusiveSumGlobalTwo, blockExcusivePtrRead, ONE_TIMES_B32_NUM);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(excusiveSumGlobalThree, blockExcusivePtrRead, ONE_TIMES_B32_NUM);
    // add block ans to global excusive
    Reg::Add(excusiveSumGlobalZero, excusiveSumGlobalZero, excusiveSumZeroB32, predicateDefaultB32);
    Reg::Add(excusiveSumGlobalOne, excusiveSumGlobalOne, excusiveSumOneB32, predicateDefaultB32);
    Reg::Add(excusiveSumGlobalTwo, excusiveSumGlobalTwo, excusiveSumTwoB32, predicateDefaultB32);
    Reg::Add(excusiveSumGlobalThree, excusiveSumGlobalThree, excusiveSumThreeB32, predicateDefaultB32);
    // vsts to global
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(blockExcusivePtrWrite, excusiveSumGlobalZero, ONE_TIMES_B32_NUM, predicateDefaultB32);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(blockExcusivePtrWrite, excusiveSumGlobalOne, ONE_TIMES_B32_NUM, predicateDefaultB32);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(blockExcusivePtrWrite, excusiveSumGlobalTwo, ONE_TIMES_B32_NUM, predicateDefaultB32);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(blockExcusivePtrWrite, excusiveSumGlobalThree, ONE_TIMES_B32_NUM, predicateDefaultB32);
} else {
    // cast B32 to B64
    Reg::RegTensor<int64_t> excusiveSumZeroB64A, excusiveSumZeroB64B, excusiveSumOneB64A, excusiveSumOneB64B;
    Reg::RegTensor<int64_t> excusiveSumTwoB64A, excusiveSumTwoB64B, excusiveSumThreeB64A, excusiveSumThreeB64B;
    Reg::Interleave((Reg::RegTensor<uint16_t> &)excusiveSumZeroB64A, (Reg::RegTensor<uint16_t> &)excusiveSumZeroB64B,
                        (Reg::RegTensor<uint16_t> &)excusiveSumZeroB32, zeroVector);
    Reg::Interleave((Reg::RegTensor<uint16_t> &)excusiveSumOneB64A, (Reg::RegTensor<uint16_t> &)excusiveSumOneB64B,
                        (Reg::RegTensor<uint16_t> &)excusiveSumOneB32, zeroVector);
    Reg::Interleave((Reg::RegTensor<uint16_t> &)excusiveSumTwoB64A, (Reg::RegTensor<uint16_t> &)excusiveSumTwoB64B,
                        (Reg::RegTensor<uint16_t> &)excusiveSumTwoB32, zeroVector);
    Reg::Interleave((Reg::RegTensor<uint16_t> &)excusiveSumThreeB64A, (Reg::RegTensor<uint16_t> &)excusiveSumThreeB64B,
                        (Reg::RegTensor<uint16_t> &)excusiveSumThreeB32, zeroVector);
    // load global excusive
    Reg::RegTensor<int64_t> excusiveSumGlobalZeroA, excusiveSumGlobalZeroB, excusiveSumGlobalOneA, excusiveSumGlobalOneB;
```

**要点**: 1) 两级 Interleave：B16→B32、B32→B64；2) 单实参形式（T0_A1）；3) 与 Histograms/Sub/Add 配合完成排序前缀和。

### 实例 12：swiglu_mx_quant::ComputeYFP16ToFP4NotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Cast, CastTrait, CreateMask, DataCopy, HighLowPart, LoadDist, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, StoreDist
- **Interleave 调用次数**: 6
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: SwiGLU 非末轴 FP4 量化中，对 dim0/dim1 两路分别 Cast 拆 Zero/One、ComputeFP4、Cast 到 BF16、Pack 取低位后 Interleave 合并半部，最后跨 dim Interleave 合并两路再 Cast 到 FP4 输出。

（行 515-545）

```cpp
Reg::Cast<float, T, CAST_ZERO>(x0ZeroFP32, x0, dataMaskB16);
Reg::Cast<float, T, CAST_ONE>(x0OneFP32, x0, dataMaskB16);
Reg::Cast<float, T, CAST_ZERO>(x1ZeroFP32, x1, dataMaskB16);
Reg::Cast<float, T, CAST_ONE>(x1OneFP32, x1, dataMaskB16);
Reg::Mul(dim0x0ZeroFP32, reversedShareExp0ZeroFP32, x0ZeroFP32, dataMaskB32);
Reg::Mul(dim0x0OneFP32, reversedShareExp0OneFP32, x0OneFP32, dataMaskB32);
ComputeFP4FromHalf<U, roundMode>(dim0x0ZeroFP32, dataMaskB32);
ComputeFP4FromHalf<U, roundMode>(dim0x0OneFP32, dataMaskB32);
Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(dim0x0ZeroBF16, dim0x0ZeroFP32, dataMaskB32);
Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(dim0x0OneBF16, dim0x0OneFP32, dataMaskB32);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(
    (Reg::RegTensor<uint16_t>&)dim0x0ZeroBF16, (Reg::RegTensor<uint32_t>&)dim0x0ZeroBF16);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(
    (Reg::RegTensor<uint16_t>&)dim0x0OneBF16, (Reg::RegTensor<uint32_t>&)dim0x0OneBF16);
Reg::Interleave(dim0x0ZeroBF16, dim0x0OneBF16, dim0x0ZeroBF16, dim0x0OneBF16);
Reg::Mul(dim0x1ZeroFP32, reversedShareExp1ZeroFP32, x1ZeroFP32, dataMaskB32);
Reg::Mul(dim0x1OneFP32, reversedShareExp1OneFP32, x1OneFP32, dataMaskB32);
ComputeFP4FromHalf<U, roundMode>(dim0x1ZeroFP32, dataMaskB32);
ComputeFP4FromHalf<U, roundMode>(dim0x1OneFP32, dataMaskB32);
Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(dim0x1ZeroBF16, dim0x1ZeroFP32, dataMaskB32);
Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(dim0x1OneBF16, dim0x1OneFP32, dataMaskB32);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(
    (Reg::RegTensor<uint16_t>&)dim0x1ZeroBF16, (Reg::RegTensor<uint32_t>&)dim0x1ZeroBF16);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(
    (Reg::RegTensor<uint16_t>&)dim0x1OneBF16, (Reg::RegTensor<uint32_t>&)dim0x1OneBF16);
Reg::Interleave(dim0x1ZeroBF16, dim0x1OneBF16, dim0x1ZeroBF16, dim0x1OneBF16);
Reg::Interleave(dim0x0ZeroBF16, dim0x1ZeroBF16, dim0x0ZeroBF16, dim0x1ZeroBF16);
Reg::Cast<U, bfloat16_t, castTraitBF16toFp4>(dim0x0FP4, dim0x0ZeroBF16, dataMaskB16);
Reg::Cast<U, bfloat16_t, castTraitBF16toFp4>(dim0x1FP4, dim0x1ZeroBF16, dataMaskB16);
Reg::DataCopy<uint8_t, Reg::StoreDist::DIST_PACK4_B32>(
    y2Addr + (i * dataLen / 2), (Reg::RegTensor<uint8_t>&)dim0x0FP4, dataMaskB8);
```

**要点**: 1) 三级 Interleave：组内 zero/one → 跨 dim0/dim1；2) 每次 Interleave 前都 Cast→Pack 取 BF16 低位；3) 使用 Reg、`__aicore__` 上下文。

### 实例 13：flat_quant::QuantVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, Cast, CastTrait, CreateAddrReg, DataCopy, LoadDist, MaskMergeMode, MaskReg, Mul, PostLiteral, RegLayout, RegTensor, SatMode, StoreDist, UpdateMask
- **Interleave 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 扁平量化 VF 中用 DataCopy 双块加载（DIST_DINTLV_B16）取 vdExp0/vdExp1，各自乘 scale 后 Interleave 合并，再 Cast 到 FP4 并按 PACK4 存储。

（行 566-590）

```cpp
for (uint16_t i = 0; i < repeatTimes; i++) {
    aReg = AscendC::Reg::CreateAddrReg<uint16_t>(i, oneRepeatSize);
    dataMask1 = AscendC::Reg::UpdateMask<bfloat16_t>(oneRepeatSize);
    dataMask2 = AscendC::Reg::UpdateMask<bfloat16_t>(oneRepeatSize);

    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                AscendC::Reg::LoadDist::DIST_DINTLV_B16>(
        vdExp0, vdExp1, srcPtr, 128 * 2); // copy two chunks from srcAddr to regbase
    AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                AscendC::Reg::LoadDist::DIST_E2B_B16>(halfScaleForMul, src2Ptr, 8);
    AscendC::Reg::Mul(vdExp0, vdExp0, (AscendC::Reg::RegTensor<bfloat16_t>&)halfScaleForMul,
                           dataMask1);
    AscendC::Reg::Mul(vdExp1, vdExp1, (AscendC::Reg::RegTensor<bfloat16_t>&)halfScaleForMul,
                           dataMask1);
    AscendC::Reg::Interleave(vdExp0, vdExp1, vdExp0, vdExp1);
    AscendC::Reg::Cast<fp4x2_e2m1_t, bfloat16_t, castTrait>(vdExp0FP4, vdExp0, dataMask1);
    AscendC::Reg::Cast<fp4x2_e2m1_t, bfloat16_t, castTrait>(vdExp1FP4, vdExp1, dataMask2);
    AscendC::Reg::DataCopy<int8_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                AscendC::Reg::StoreDist::DIST_PACK4_B32>(
        dstPtr, (AscendC::Reg::RegTensor<int8_t>&)vdExp0FP4, 64, dataMask1);
    AscendC::Reg::DataCopy<int8_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                AscendC::Reg::StoreDist::DIST_PACK4_B32>(
        dstPtr, (AscendC::Reg::RegTensor<int8_t>&)vdExp1FP4, 64, dataMask2);
}
```

**要点**: 1) `Interleave(vdExp0, vdExp1, vdExp0, vdExp1)` 合并两路 BF16；2) `__simd_vf__` 上下文，使用 AddrReg 管理循环地址；3) 交织后分别 Cast 到 FP4 用不同 mask 存储。

### 实例 14：swiglu_group_quant::VFComputeDataMXFP4Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, CastTrait, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Mul, PostLiteral, RegLayout, RegTensor, SatMode, StoreAlign, StoreDist, UpdateMask
- **Interleave 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: SwiGLU 分组量化 VF 中，half 路径先 FP16Convert 再 Cast 到 BF16、乘 scale、Interleave 合并 vdExp0/vdExp1，最后 Cast 到 FP4；非 half 路径直接乘后 Interleave。

（行 451-467）

```cpp
if constexpr (IsSameType<T, half>::value) {
    FP16Convert<T, U>(vdExp0, vdExp0, dataMask1);
    FP16Convert<T, U>(vdExp1, vdExp1, dataMask1);
    AscendC::Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(vdExp0BF16, vdExp0, dataMask1);
    AscendC::Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(vdExp1BF16, vdExp1, dataMask1);
    AscendC::Reg::Mul(vdExp0BF16, vdExp0BF16, (AscendC::Reg::RegTensor<bfloat16_t>&)halfScaleForMul, dataMask1);
    AscendC::Reg::Mul(vdExp1BF16, vdExp1BF16, (AscendC::Reg::RegTensor<bfloat16_t>&)halfScaleForMul, dataMask1);
    AscendC::Reg::Interleave(vdExp0BF16, vdExp1BF16, vdExp0BF16, vdExp1BF16);
    AscendC::Reg::Cast<U, bfloat16_t, castTrait>(vdExp0FP4, vdExp0BF16, dataMask1);
    AscendC::Reg::Cast<U, bfloat16_t, castTrait>(vdExp1FP4, vdExp1BF16, dataMask1);
} else {
    AscendC::Reg::Mul(vdExp0, vdExp0, (AscendC::Reg::RegTensor<T>&)halfScaleForMul, dataMask1);
    AscendC::Reg::Mul(vdExp1, vdExp1, (AscendC::Reg::RegTensor<T>&)halfScaleForMul, dataMask1);
    AscendC::Reg::Interleave(vdExp0, vdExp1, vdExp0, vdExp1);
    AscendC::Reg::Cast<U, T, castTrait>(vdExp0FP4, vdExp0, dataMask1);
    AscendC::Reg::Cast<U, T, castTrait>(vdExp1FP4, vdExp1, dataMask1);
}
```

**要点**: 1) `Interleave(vdExp0BF16, vdExp1BF16, ...)` 合并两路 BF16 半部；2) `__simd_vf__` 上下文；3) half 与非 half 分支均以 Interleave 合并后 Cast 到 FP4。

### 实例 15：pool_3d_common::AvgPoolSingleChannelB16

- **来源类型**: `__aicore__`
- **共现 API**: Add, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Div, Duplicate, MaskPattern, MaskReg, RegTensor, UnalignReg, UpdateMask
- **Interleave 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 3D 平均池化单通道 B16 中，用 Interleave 把加载的 vd0 与 zero 交织拆成左右两半，分别 Cast 到 FP32 后累加，实现双倍并行累加。

（行 1528-1536）

```cpp
for (uint16_t wIdx = 0; wIdx < kW; wIdx++) {
    auto aReg = Reg::CreateAddrReg<U>(dIdx, depStrideInUb, hIdx, rowStrideInub, wIdx, alignChannels);
    Reg::DataCopy(vd0, curSrcAddr, aReg);
    Reg::Interleave(tmpLeft, tmpRight, vd0, zero);
    Reg::Cast<float32_t, M, castTraitB16ToB32>(left, tmpLeft, defaultMask);
    Reg::Cast<float32_t, M, castTraitB16ToB32>(right, tmpRight, defaultMask);
    Reg::Add(tmpRes1, tmpRes1, left, defaultMask);
    Reg::Add(tmpRes2, tmpRes2, right, defaultMask);
}
```

**要点**: 1) `Interleave(tmpLeft, tmpRight, vd0, zero)` 把数据与 0 交织拆成偶/奇两路；2) 拆后各自 Cast B16→B32 再 Add 累加；3) 与 DeInterleave 配合做池化窗口遍历。

### Interleave 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 与0交织配合Cast取值 + Zero/One半部合并 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | 与0交织使Cast Zero一次取全部有效值 | __VEC_SCOPE__ |
| dynamic_block_quant | And, Cast, CastTrait, CompareScalar, CreateMask | Cast拆Zero/One半部→Interleave交织→Div求scale→Cast回低精度 | __VEC_SCOPE__ |
| dynamic_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 与0交织取紧凑max + scale奇偶半部合并 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | Pack取低位→Interleave合并scale半部→ShiftLefts定格式 | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | scale奇偶半部Interleave合并→ShiftLefts→Pack输出uint8 | __aicore__ |
| sparse_slice | AR, ClearSpr, Compare, CreateMask, DataCopy | GatherMask聚集高低半→Interleave<int32_t>合并→MaskInterleave同步 | __VEC_SCOPE__ |
| dynamic_mx_quant | Cast, CastTrait, CreateMask, DeInterleave, Duplicate | Cast→Pack取低位→三级Interleave级联合并→Cast到FP4 | __VEC_SCOPE__ |
| sparse_slice | AR, ClearSpr, CompareScalar, DataCopy, DataCopyUnAlign | MaskUnPack→DeInterleave拆半→GatherMask→Interleave<int32_t>合并 | __VEC_SCOPE__ |
| top_k_v2 | Add, CreateMask, DataCopy, DeInterleave, Duplicate | B16直方图累加和与0交织扩展为B32/B64 | __VEC_SCOPE__ |
| top_k_v2 | Add, CreateMask, DataCopy, DeInterleave, Duplicate | 两级Interleave级联B16→B32→B64位宽扩展 | __VEC_SCOPE__ |
| swiglu_mx_quant | Cast, CastTrait, CreateMask, DataCopy, HighLowPart | 两路Cast→Pack→组内Interleave→跨dim Interleave→Cast到FP4 | __aicore__ |
| flat_quant | AddrReg, Cast, CastTrait, CreateAddrReg, DataCopy | 双块DataCopy加载→乘scale→Interleave合并→Cast到FP4→PACK4存储 | __simd_vf__ |
| swiglu_group_quant | Cast, CastTrait, LoadAlign, LoadDist | half→Cast到BF16→乘scale→Interleave合并→Cast到FP4 | __simd_vf__ |
| pool_3d_common | Add, Cast, CreateAddrReg, CreateMask, DataCopy | 与0交织拆左右两半→Cast到FP32→双路累加 | __aicore__ |

