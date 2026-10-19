# Compare

**页面ID:** atlasascendc_api_07_0393  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0393.html

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

逐元素比较两个Tensor大小，如果比较后的结果为真，则输出结果的对应比特位为1，否则为0。

#### 函数原型

```
template <typename T = DefaultType, CMPMODE mode = CMPMODE::EQ, typename U>
__simd_callee__ inline void Compare(MaskReg& dst, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/half/float/bfloat16_t/uint64_t/int64_t |
| mode | 比较模式。支持如下取值： - LT：小于（less than）- GT：大于（greater than） - GE：大于或等于（greater than or equal to）- EQ：等于（equal to）- NE：不等于（not equal to）- LE：小于或等于（less than or equal to） |
| U | 源操作数和目的操作数的RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | MaskReg类型，目的操作数。 |
| srcReg0、srcReg1 | 输入 | 源操作数。 类型为RegTensor。 两个源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

srcReg0和srcReg1可以是同一个RegTensor。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void CompareVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::MaskReg cmpMaskReg;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);        
        AscendC::Reg::Compare<T, AscendC::CMPMODE::EQ>(cmpMaskReg, srcReg0, srcReg1, mask);
        AscendC::Reg::Select(dstReg, srcReg0, srcReg1, cmpMaskReg);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Compare 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskPattern, MaskReg, Max, MemType, Mul, Pack, RegTensor, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Compare 调用次数**: 4
- **参数模式**: `T2_A4_M1_TYPEnone_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask）
- **语义（待补充）**: 在 dynamic_mx_quant 量化中用 Compare 检测 FP32/BF16 数据的 INF（NE infForXReg）和特殊值（EQ biasReg），配合 Select 将异常值替换为 NaN，保证量化缩放计算的数值安全。

（行 317-326）

```cpp
if constexpr (IsSame<T, half>::value) {
    Reg::Compare<calcTypeInt, CMPMODE::NE>(infMask, expFP32Reg, infForXReg, mask32);
    Reg::Compare<calcTypeInt, CMPMODE::EQ>(specialDataMask, expFP32Reg, biasReg, mask32);
    Reg::Sub(scaleReprocal, biasReg, expFP32Reg, mask32);
} else {
    Reg::Compare<calcTypeInt, CMPMODE::NE>(infMask, expBF16Reg, infForXReg, mask16);
    Reg::Compare<calcTypeInt, CMPMODE::EQ>(specialDataMask, expBF16Reg, biasReg, mask16);
    Reg::Sub(scaleReprocal, biasReg, expBF16Reg, mask16);
}
Reg::Select<calcTypeInt>(scaleReprocal, scaleReprocal, nan, infMask);
```

**要点**: 模板参数 calcTypeInt 指定比较的整型位宽，CMPMODE::NE 判 INF、EQ 判特殊值；半精度与全精度分支使用不同位宽掩码（mask16/mask32）；infMask 作为 Select 条件把 INF 位替换为 nan。

### 实例 2：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub, UnPack
- **Compare 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEint32_t+uint32_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: uint32_t, int32_t）
- **语义（待补充）**: 在 swiglu 双轴量化中对 -1 轴 ReduceMax 后的最大值用 Compare LT 检测上溢（max < expMaskReg）和 NE 检测零值，再配合 Mul、ShiftRights 提取指数位用于 scale 计算。

（行 999-1018）

```cpp

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
```

**要点**: 使用 Reg 命名空间调用 Compare，模板参数 uint32_t；maskAll32 为全 1 掩码控制全部元素参与比较；cmpResult 和 zeroMask 分别驱动后续 Select 替换 NaN 和零值。

### 实例 3：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Compare 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEint32_t+uint32_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: uint32_t, int32_t）
- **语义（待补充）**: 在 flat 量化中将 BF16 最大值转 FP32 后，用 Compare 检测上溢和零值，再用多次 CompareScalar 对指数范围（0~254）和尾数做条件判断，配合 MaskAnd/MaskOr 组合掩码驱动 Select 实现 FP4 指数提取与舍入。

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

**要点**: Compare（向量 vs 向量）用于 INF/零检测，CompareScalar（向量 vs 标量）用于范围边界判断；多个 CompareScalar 结果通过 MaskAnd/MaskOr 组合为复合条件 p0；preMaskScale 控制实际参与运算的元素数（尾块掩码）。

### 实例 4：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Compare 调用次数**: 6
- **参数模式**: `T2_A4_M1_TYPEint16_t+uint16_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: uint16_t, int16_t）
- **语义（待补充）**: 在双轴动态 MX 量化中对每个轴的 BF16 scale 用 Compare NE 检测 INF、EQ 检测特殊值（biasE8M0），配合 Sub 计算 1/scale 并用 Select 将 INF 替换为 NaN、特殊值替换为 specialExp。

**片段 1** (行 724-743):

```cpp
Reg::MaskOr(p0, p0, p1, maskFP32);
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
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, scale1BF16, biasE8M0, maskAll);
Reg::Sub(reversedShareExp1, biasE8M0, scale1BF16, maskAll);
Reg::Select<uint16_t>(reversedShareExp1, reversedShareExp1, nanBF16, infMask);
Reg::Select<uint16_t>(reversedShareExp1, specialExp, reversedShareExp1, invalidDataMask);
```

**片段 2** (行 788-807):

```cpp
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

// 计算1/scale, 复用reversedShareExp1 (与原始DynamicMxQuant一致: 无零值检查)
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, scale1BF16, maxEleBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, scale1BF16, biasE8M0, maskAll);
Reg::Sub(reversedShareExp1, biasE8M0, scale1BF16, maskAll);
Reg::Select<uint16_t>(reversedShareExp1, reversedShareExp1, nanBF16, infMask);
Reg::Select<uint16_t>(reversedShareExp1, specialExp, reversedShareExp1, invalidDataMask);
```

**片段 3** (行 838-857):

```cpp
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
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, scale1BF16, biasE8M0, maskAll);
Reg::Sub(absMax0, biasE8M0, scale1BF16, maskAll);
Reg::Select<uint16_t>(absMax0, absMax0, nanBF16, infMask);
Reg::Select<uint16_t>(absMax0, specialExp, absMax0, invalidDataMask);
```

**要点**: 三段片段分别处理 -1 轴的 even/odd 子通道，复用 scale1BF16 寄存器；Compare 模板参数 uint16_t 对应 BF16 位宽，maskAll 为全使能掩码；infMask 与 invalidDataMask 两次 Select 形成优先级：先判 INF 再判特殊值。

### 实例 5：dynamic_mx_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub
- **Compare 调用次数**: 2
- **参数模式**: `T2_A4_M0_TYPEint16_t+uint16_t`（实参 4 个，类型: uint16_t, int16_t）
- **语义（待补充）**: 在 dynamic_mx_quant 高性能大尾块版本中先用多个 CompareScalar 对 FP32 指数和尾数做范围校验生成舍入条件 p2，再对 BF16 scale 用 Compare NE/EQ 做 INF 和特殊值检测，最终输出 mxScale 和 1/scale。

（行 467-510）

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
```

**要点**: 参数模式 M0 表示 Compare 调用未显式传 mask（使用默认全使能 pregAll16）；CompareScalar 的 GT/LT/EQ 组合实现「指数在 0~254 内且尾数非零」的复合条件；同一函数内同时使用 CompareScalar 和 Compare 两类比较。

### 实例 6：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **Compare 调用次数**: 3
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义（待补充）**: 在复数取模 complex_abs 中用 Compare GT 比较两个分量绝对值并配合 Select 交换使大者为 a（避免溢出），再用 EQ 检测零值、LT 检测次正规数，实现稳定的复数模长计算。

（行 103-160）

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

**要点**: 首次 Compare 使用 float 类型直接比较绝对值，后续两次 Compare 将 float 重解释为 uint32_t 做位级比较；preg2/preg3/preg4 三个掩码分别记录「需交换」「次正规」「零值」三种条件；CMPMODE::GT 结果直接作为 Select 条件掩码实现条件交换。

### 实例 7：abs::AbscomplexCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **Compare 调用次数**: 3
- **参数模式**: `T2_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义（待补充）**: 在 abs 算子的复数取模分支中用 Compare GT 比较两分量绝对值并 Select 交换，再用 EQ 和 LT 分别检测零值和次正规数，与 complex_abs 采用相同数值稳定策略。

（行 103-156）

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
    Reg::Compare<uint32_t, CMPMODE::EQ>(
        preg4, (AscendC::Reg::RegTensor<uint32_t>&)vB, vZero, preg);

    // subnormal处理
    Reg::Compare<uint32_t, CMPMODE::LT>(
        preg3, (AscendC::Reg::RegTensor<uint32_t>&)vA, vMinNormalFloat, preg);
    Reg::Mul(vAS, vA, vSCALE_UP, preg);
    Reg::Mul(vBS, vB, vSCALE_UP, preg);
    Reg::Select(vA, vAS, vA, preg3);
    Reg::Select(vB, vBS, vB, preg3);
    // 提取A的指数因子（对vAForExp操作）
    Reg::ShiftRights(vA0, (AscendC::Reg::RegTensor<uint32_t>&)vA, SHR_NUM_FOR_FP32, preg);
    Reg::ShiftLefts(vA0, vA0, SHR_NUM_FOR_FP32, preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA, vA0, preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB, vA0, preg);

    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA1, vExpBias, preg);
    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB1, vExpBias, preg);

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

**要点**: 与 complex_abs 共用同一套比较-选择模式，区别在于算子入口；float→uint32_t 重解释后做位级 EQ/LT 比较，用于 subnormal 和 zero 的精确判定；preg3（次正规掩码）驱动 SCALE_UP/SCALE_DOWN 的条件缩放。

### 实例 8：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CreateMask, Duplicate, Interleave, LoadAlign, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Compare 调用次数**: 8
- **参数模式**: `T2_A4_M1_TYPEint16_t+uint16_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: uint16_t, int16_t）
- **语义（待补充）**: 在 grouped_dynamic_mx_quant 中对分组最大指数用 Compare NE 检测 INF 和零值、LE 检测超出 FP8 指数上限的非法值，配合 Select 钳位后右移生成 mxScale，再对 1/scale 用 EQ 检测特殊值。

**片段 1** (行 337-368):

```cpp
for (uint16_t j = 0; j <= static_cast<uint16_t>(blockCountLoop); j++) {
    Reg::LoadAlign(xRegTensor0, xAddr + j * dataLen + i * vfLen);
    Reg::LoadAlign(xRegTensor1, xAddr + (static_cast<uint16_t>(blockCount) - j - 1) * dataLen + i * vfLen);
    if constexpr (IsSame<T, half>::value) {
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16RegTensor0, xRegTensor0, p0);
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16RegTensor1, xRegTensor1, p0);
        Reg::And(expMaxRegTensor0, (Reg::RegTensor<uint16_t>&)xBF16RegTensor0, maxEleRegTensor, p0);
        Reg::And(expMaxRegTensor1, (Reg::RegTensor<uint16_t>&)xBF16RegTensor1, maxEleRegTensor, p0);
    } else {
        Reg::And(expMaxRegTensor0, (Reg::RegTensor<uint16_t>&)xRegTensor0, maxEleRegTensor, p0);
        Reg::And(expMaxRegTensor1, (Reg::RegTensor<uint16_t>&)xRegTensor1, maxEleRegTensor, p0);
    }
    Reg::Max(expRegTensor, expMaxRegTensor0, expMaxRegTensor1, p0);
    Reg::Max(expMaxRegTensor, expRegTensor, expMaxRegTensor, p0);
}
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expMaxRegTensor, maxEleRegTensor, p0);
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expMaxRegTensor, zeroRegTensor, p0);
Reg::Compare<uint16_t, CMPMODE::LE>(invalidDataMask, expMaxRegTensor, fp8MaxExpRegTensor, p0);
Reg::Select<uint16_t>(expMaxRegTensor, fp8MaxExpRegTensor, expMaxRegTensor, invalidDataMask);
Reg::Sub(expMaxRegTensor, expMaxRegTensor, fp8MaxExpRegTensor, p0);
Reg::ShiftRights(mxScaleRegTensor, expMaxRegTensor, SHR_NUM_FOR_BF16, p0);
Reg::Select<uint16_t>(mxScaleRegTensor, mxScaleRegTensor, fp8NanRegTensor, infMask);
Reg::Select<uint16_t>(mxScaleRegTensor, mxScaleRegTensor, zeroRegTensor, zeroMask);
Reg::Pack(mxScale, mxScaleRegTensor);
Reg::StoreUnAlign(mxScaleAddr, mxScale, u0, vfLen);
Reg::StoreUnAlignPost(mxScaleAddr, u0, 0);

// 求1/scale
Reg::Compare<uint16_t, CMPMODE::EQ>(specialDataMask, expMaxRegTensor, biasRegTensor, p0);
Reg::Sub(reversedShareExpRegTensor, biasRegTensor, expMaxRegTensor, p0);
Reg::Select<uint16_t>(reversedShareExpRegTensor, reversedShareExpRegTensor, nanRegTensor, infMask);
Reg::Select<uint16_t>(reversedShareExpRegTensor, reversedShareExpRegTensor, zeroRegTensor, zeroMask);
```

**片段 2** (行 410-442):

```cpp
for (uint16_t k = 0; k <= static_cast<uint16_t>(blockCountLoop); k++) {
    Reg::LoadAlign(xRegTensor0, xAddr + k * dataLen + regLoop * vfLen);
    Reg::LoadAlign(xRegTensor1,
                   xAddr + (static_cast<uint16_t>(blockCount) - k - 1) * dataLen + regLoop * vfLen);
    if constexpr (IsSame<T, half>::value) {
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16RegTensor0, xRegTensor0, p1);
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16RegTensor1, xRegTensor1, p1);
        Reg::And(expMaxRegTensor0, (Reg::RegTensor<uint16_t>&)xBF16RegTensor0, maxEleRegTensor, p1);
        Reg::And(expMaxRegTensor1, (Reg::RegTensor<uint16_t>&)xBF16RegTensor1, maxEleRegTensor, p1);
    } else {
        Reg::And(expMaxRegTensor0, (Reg::RegTensor<uint16_t>&)xRegTensor0, maxEleRegTensor, p1);
        Reg::And(expMaxRegTensor1, (Reg::RegTensor<uint16_t>&)xRegTensor1, maxEleRegTensor, p1);
    }
    Reg::Max(expRegTensor, expMaxRegTensor0, expMaxRegTensor1, p1);
    Reg::Max(expMaxRegTensor, expRegTensor, expMaxRegTensor, p1);
}
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expMaxRegTensor, maxEleRegTensor, p1);
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expMaxRegTensor, zeroRegTensor, p1);
Reg::Compare<uint16_t, CMPMODE::LE>(invalidDataMask, expMaxRegTensor, fp8MaxExpRegTensor, p1);
Reg::Select<uint16_t>(expMaxRegTensor, fp8MaxExpRegTensor, expMaxRegTensor, invalidDataMask);
Reg::Sub(expMaxRegTensor, expMaxRegTensor, fp8MaxExpRegTensor, p1);
Reg::ShiftRights(mxScaleRegTensor, expMaxRegTensor, SHR_NUM_FOR_BF16, p1);
Reg::Select<uint16_t>(mxScaleRegTensor, mxScaleRegTensor, fp8NanRegTensor, infMask);
Reg::Select<uint16_t>(mxScaleRegTensor, mxScaleRegTensor, zeroRegTensor, zeroMask);
Reg::Pack(mxScale, mxScaleRegTensor);
Reg::StoreUnAlign(mxScaleAddr, mxScale, u0, tailVfLen);
Reg::StoreUnAlignPost(mxScaleAddr, u0, 0);

// 求1/scale
Reg::Compare<uint16_t, CMPMODE::EQ>(specialDataMask, expMaxRegTensor, biasRegTensor, p1);
Reg::Sub(reversedShareExpRegTensor, biasRegTensor, expMaxRegTensor, p1);
Reg::Select<uint16_t>(reversedShareExpRegTensor, specialExpRegTensor, reversedShareExpRegTensor,
                      specialDataMask);
```

**要点**: CMPMODE::LE 用于「指数 ≤ fp8MaxExp」的非法值检测，超出时 Select 钳位为 fp8MaxExp；两个片段分别处理 i 循环和 regLoop 循环的数据块，使用不同掩码 p0/p1；INF→fp8Nan、零值→0、特殊值→specialExp 三类 Select 形成完整异常值处理链。

### 实例 9：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Compare 调用次数**: 4
- **参数模式**: `T2_A4_M1_TYPEint16_t+uint16_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: uint16_t, int16_t）
- **语义（待补充）**: 在 swiglu_mx_quant 中先用多个 CompareScalar 对 FP32 指数和尾数做范围校验生成舍入条件 p0Odd，再对 BF16 scale 用 Compare NE/EQ 检测 INF 和特殊值，配合 Sub 和 Select 输出 1/scale。

（行 339-357）

```cpp
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
Reg::Select<uint16_t>(absMax0, absMax0, nanBF16, infMask);
Reg::Select<uint16_t>(absMax0, specialExp, absMax0, invalidDataMask);
```

**要点**: CompareScalar 的复合条件通过 MaskOr 合并为 p0Odd，驱动 Select 在 exp 和 exp+1 间舍入选择；Compare 模板参数 uint16_t 对应 BF16 scale 的位宽；maskAll 掩码全使能，maskFP32 用于 FP32 域运算。

### 实例 10：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Compare 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEint32_t+uint32_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: uint32_t, int32_t）
- **语义（待补充）**: 在 add_rms_norm_dynamic_mx_quant 中将 BF16 最大值转 FP32 后用 Compare LT 检测上溢、NE 检测零值，再用 CompareScalar 对指数范围和尾数做条件判断，配合 MaskAnd/MaskOr 组合掩码驱动 Select 提取 FP8 指数。

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

**要点**: Compare 与 CompareScalar 配合：前者检测异常值（INF/零），后者做范围边界判断；preMaskScale 为尾块掩码，控制非完整 block 的元素数；两路 Select 分别处理 extractExp 和 halfScale，共享 cmpResult 和 zeroMask 条件。

### 实例 11：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Compare 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEint32_t+uint32_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: uint32_t, int32_t）
- **语义（待补充）**: 在 rms_norm_dynamic_mx_quant 中用 Compare LT 检测指数上溢、NE 检测零值，再通过多个 CompareScalar 对指数和尾数做范围校验，配合 MaskAnd/MaskOr 组合条件驱动 Select 提取 FP8 量化指数和倒数 scale。

（行 419-463）

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

**要点**: 与 add_rms_norm_dynamic_mx_quant 结构一致，区别在于无 Add 前置运算；DataCopy 带 POST_MODE_UPDATE 实现搬运后地址自增；maskHalf 控制半数元素存储（FP8 scale 为 uint8，Pack 后 B16 存储取半）。

### 实例 12：swiglu_backward_mx_quant_with_dual_axis::ComputeScaleCuBLASSecondLast

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, Sub
- **Compare 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEint32_t+uint32_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: uint32_t, int32_t）
- **语义（待补充）**: 在 swiglu_backward 双轴量化的反向计算中对 1/scale 倒数用 Compare LT 检测上溢、NE 检测零值，再用 CompareScalar 对指数和尾数做范围校验，配合 MaskAnd/MaskOr 驱动 Select 提取 FP8 指数并输出 mxScale2 和倒数。

（行 810-848）

```cpp
for (uint16_t i = 0; i < times; i++) {
    Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                       AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16Reg, mxScale2ReciprocalAddr,
                                                                     VF_LEN_FP32);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>((Reg::RegTensor<float>&)max32Reg,
                                                       (Reg::RegTensor<xDtype>&)max16Reg, maskAll);
    Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32Reg, expMaskReg, maskAll32);
    Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32Reg, zero32Reg, maskAll32);
    Reg::Mul((Reg::RegTensor<float>&)max32Reg, (Reg::RegTensor<float>&)max32Reg,
                  (Reg::RegTensor<float>&)invMax, maskAll32);
    Reg::ShiftRights(exp32Reg, max32Reg, SHR_NUM_FOR_FP32, maskAll32);
    Reg::And(man32Reg, max32Reg, manMaskReg, maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32Reg, static_cast<uint32_t>(0), maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, exp32Reg, EXP_254, maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32Reg, static_cast<uint32_t>(0), maskAll32);
    Reg::MaskAnd(p0, p0, p1, maskAll32);
    Reg::MaskAnd(p0, p0, p2, maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, exp32Reg, static_cast<uint32_t>(0), maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32Reg, HALF_FOR_MAN, maskAll32);
    Reg::MaskAnd(p1, p1, p2, maskAll32);
    Reg::MaskOr(p0, p0, p1, maskAll32);
    Reg::Adds(expOne32Reg, exp32Reg, 1, maskAll32);
    Reg::Select(extractExp, expOne32Reg, exp32Reg, p0);
    Reg::Select<uint32_t>(extractExp, extractExp, fp8Nan32Reg, cmpResult);
    Reg::Select<uint32_t>(extractExp, extractExp, zero32Reg, zeroMask);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale16, extractExp);
    Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(scale8Zero, scale16);

    Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, maskAll32);
    Reg::Sub(halfScale, scaleBiasReg, extractExp, maskAll32);
    Reg::Select<uint32_t>(halfScale, halfScale, nan32Reg, cmpResult);
    Reg::Select<uint32_t>(halfScale, halfScale, zero32Reg, zeroMask);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(recip16Zero, halfScale);
    Reg::DataCopy<uint8_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(mxScale2Addr, scale8Zero,
                                                                                  VF_LEN_FP32, maskB8);

    Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        mxScale2ReciprocalOutAddr, recip16Zero, VF_LEN_FP32, maskB16);
}
```

**要点**: maskAll32 为 FP32 域全使能掩码，与 maskB8/maskB16 分属不同位宽的存储掩码；两路 Pack（uint32→uint16→uint8）实现 FP8 scale 的位宽压缩；cmpResult 和 zeroMask 同时驱动 extractExp 和 halfScale 两条 Select 链。

### 实例 13：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, ClearSpr, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, GatherMask, GatherMaskMode, Interleave, LoadDist, MaskInterleave, MaskReg, PostLiteral, RegTensor, SubCarryOut, SubCarryOuts, UnalignReg, UpdateMask
- **Compare 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEint32_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: int32_t）
- **语义（待补充）**: 在 sparse_slice 稀疏切片中用 Compare EQ 将 int8 掩码值与全 1 向量比较生成选择谓词 pregSelect，驱动 GatherMask 按谓词聚集有效索引，再对聚集结果用 Compare EQ 校验生成最终谓词 pregGathered。

（行 702-748）

```cpp
for (uint16_t loopIndex = 0; loopIndex < loopNum; loopIndex++) {
    pregIndices = Reg::UpdateMask<int32_t>(sreg0);
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

    // vreg interleave and mask interleave
    Reg::Interleave<int32_t>(vregGatherResult0, vregGatherResult1, vregGatherLowerHalf,
                                  vregGatherHigherHalf);
    Reg::MaskInterleave<int32_t>(pregSelectFinal0, pregSelectFinal1, pregGathered, pregGathered);

    // additional gathermask to save real copyout data len
    Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(vregGatherOutput0, vregGatherResult0,
                                                                       pregSelectFinal0);
    Reg::DataCopyUnAlign<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        (__ubuf__ int64_t*)(yIndicesCurDimAddr), (Reg::RegTensor<int64_t>&)vregGatherResult0, ureg0);

    Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(vregGatherOutput1, vregGatherResult1,
                                                                       pregSelectFinal1);
    Reg::DataCopyUnAlign<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        (__ubuf__ int64_t*)(yIndicesCurDimAddr), (Reg::RegTensor<int64_t>&)vregGatherResult1, ureg0);
}
```

**要点**: 模板参数 int32_t，掩码值经 unpack 后扩展为 int32 比较；两次 Compare 形成「掩码筛选→GatherMask 聚集→结果校验」的三级谓词链；pregSelect 同时控制 SubCarryOut 等运算，实现按谓词的条件计算。

### 实例 14：dynamic_block_mx_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CreateMask, Duplicate, Gather, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreAlign, Sub
- **Compare 调用次数**: 6
- **参数模式**: `T2_A4_M1_TYPEint16_t+uint16_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: uint16_t, int16_t）
- **语义（待补充）**: 在 dynamic_block_mx_quant 块量化中先用 Compare LT 检测 FP16 数据的 INF/NAN，对块最大指数再用 Compare NE/EQ/LT 分别检测 INF、零值和非法指数，配合 Select 输出 E8M0 格式 scale。

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

**片段 2** (行 661-717):

```cpp
for (uint16_t i = 0; i < rowNum; i++) {
    // 交织搬运，一次搬256个B16
    Reg::LoadAlign<T, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
        x0, x1, xAddr, vlForHalfNumber_ * DIGIT_TWO);

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
    Reg::Max(expMax1Dim2, expMax1Dim2, x0ExpBF16, maskAll);
    Reg::Max(expMax2Dim2, expMax2Dim2, x1ExpBF16, maskAll);
}

// 计算x0和x1的最大值，相当于计算原始相邻两个数据的最大值
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
```

**要点**: 两次 Compare LT 分别作用于 FP16 和 BF16 域的指数位，配合 half→BF16 的 Cast 转换；ReduceMaxWithDataBlock 计算块最大值后三路 Compare（NE/EQ/LT）覆盖 INF/零/非法三种异常；maskAll 全使能控制全部元素参与比较。

### 实例 15：swiglu_group_quant::VFComputeMaxExpMXFP4Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **Compare 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEint16_t+uint16_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: uint16_t, int16_t）
- **语义（待补充）**: 在 swiglu_group_quant 分组量化中对 FP16 数据的指数位用 Compare NE 与非法掩码比较生成 invalidDataMask，配合 Cast 转 BF16 后 Select 将非法指数替换为 expMaskBF16，保证后续块最大值计算的数值正确。

（行 304-318）

```cpp
if constexpr (IsSameType<T, half>::value) {
    AscendC::Reg::And(vdExpSelect0, (AscendC::Reg::RegTensor<uint16_t>&)vdExp0, invalidmaskfp16, scaleMask1);
    AscendC::Reg::And(vdExpSelect1, (AscendC::Reg::RegTensor<uint16_t>&)vdExp1, invalidmaskfp16, scaleMask1);
    AscendC::Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask0, vdExpSelect0, invalidmaskfp16, scaleMask1);
    AscendC::Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask1, vdExpSelect1, invalidmaskfp16, scaleMask1);
    AscendC::Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(vdExp0BF16, vdExp0, scaleMask1);
    AscendC::Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(vdExp1BF16, vdExp1, scaleMask1);
    AscendC::Reg::And(vdExpExtract0, (AscendC::Reg::RegTensor<uint16_t>&)vdExp0BF16, expMaskBF16, scaleMask1);
    AscendC::Reg::And(vdExpExtract1, (AscendC::Reg::RegTensor<uint16_t>&)vdExp1BF16, expMaskBF16, scaleMask1);
    AscendC::Reg::Select<uint16_t>(vdExpExtract0, vdExpExtract0, expMaskBF16, invalidDataMask0);
    AscendC::Reg::Select<uint16_t>(vdExpExtract1, vdExpExtract1, expMaskBF16, invalidDataMask1);
} else {
    AscendC::Reg::And(vdExpExtract0, (AscendC::Reg::RegTensor<uint16_t>&)vdExp0, expMaskBF16, scaleMask1);
    AscendC::Reg::And(vdExpExtract1, (AscendC::Reg::RegTensor<uint16_t>&)vdExp1, expMaskBF16, scaleMask1);
}
```

**要点**: 模板参数 uint16_t 对应 FP16/BF16 位宽，scaleMask1 为元素使能掩码；half 分支先 And 提取 FP16 指数再 Compare，BF16 分支直接 And 提取；invalidDataMask 驱动 Select 在正常指数和 expMaskBF16 间选择，用于 INF/NAN 保护。

### Compare 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CompareScalar | Compare NE/EQ 检测 INF 和特殊值 + Select 替换异常值（无显式类型，mask32/mask16） | __VEC_SCOPE__ |
| swiglu_mx_quant_with_dual_axis | Adds, And, Cast, CompareScalar | Compare LT 上溢检测 + NE 零值检测 + Mul/ShiftRights 提取指数（Reg, maskAll32） | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait | Compare INF/零检测 + CompareScalar 范围校验 + MaskAnd/MaskOr 组合 + Select 舍入 | __simd_vf__ |
| dynamic_mx_quant_with_dual_axis | Adds, And, Cast, CompareScalar | Compare NE/EQ 异常值检测 + Sub 求 1/scale + Select 优先级替换（多片段轴处理） | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait | CompareScalar 指数范围校验 + Compare NE/EQ 异常值检测（无 mask 参数 M0） | __VEC_SCOPE__ |
| complex_abs | Abs, Add, Cast, CastTrait | Compare GT 分量绝对值交换 + EQ 零值 + LT 次正规检测 + Select 条件缩放 | __aicore__ |
| abs | Abs, Add, Cast, CastTrait | Compare GT 分量交换 + EQ/LT 特殊值检测 + Select 条件缩放（同 complex_abs 模式） | __aicore__ |
| grouped_dynamic_mx_quant | And, Cast, CastTrait, CreateMask | Compare NE/LE 异常值检测（INF/零/非法指数）+ Select 钳位 + EQ 特殊值求 1/scale | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Cast, CompareScalar | CompareScalar 范围校验舍入 + Compare NE/EQ INF/特殊值检测 + Select 1/scale | __aicore__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Cast, CompareScalar | Compare LT/NE 异常检测 + CompareScalar 范围校验 + MaskAnd/MaskOr + Select 提取指数 | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, CompareScalar | Compare LT/NE 异常检测 + CompareScalar 范围校验 + MaskAnd/MaskOr + Select 提取指数 | __aicore__ |
| swiglu_backward_mx_quant_with_dual_axis | Adds, And, Cast, CompareScalar | Compare LT/NE 异常检测 + CompareScalar 范围校验 + MaskAnd/MaskOr + Select 提取 FP8 指数 | __aicore__ |
| sparse_slice | AR, ClearSpr, CreateMask, DataCopy | Compare EQ 掩码筛选生成谓词 + GatherMask 聚集 + Compare EQ 结果校验（三级谓词链） | __VEC_SCOPE__ |
| dynamic_block_mx_quant | And, Cast, CreateMask, Duplicate | Compare LT INF/NAN 检测 + Compare NE/EQ/LT 异常值三路检测 + Select E8M0 输出 | __VEC_SCOPE__ |
| swiglu_group_quant | And, Cast, CastTrait, Duplicate | Compare NE 非法指数检测 + Select 替换为 expMaskBF16（half/BF16 双分支） | __simd_vf__ |
