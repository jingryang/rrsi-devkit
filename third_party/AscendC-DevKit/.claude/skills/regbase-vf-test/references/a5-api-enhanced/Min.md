# Min

**页面ID:** atlasascendc_api_07_0361  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0361.html

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

根据mask对源操作数srcReg0、srcReg1进行按元素求最小值操作，将结果写入目的操作数dstReg。计算公式如下：

![](images/atlasascendc_api_07_0361_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Min(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t、uint8_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、int64_t、uint64_t。 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING, mask未筛选的元素在dstReg中置零。- MERGING, 当前不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

输入srcReg0为-0, srcReg1为+0的情况下，输出dstReg为-0。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MinVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);

       
        AscendC::Reg::Min(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Min 实例

### 实例 1：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Min 调用次数**: 6
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 在 dynamic_quant 的 ComputeVF 中，Min 与 Max 配合逐元素累乘 smooth 项后的极值，ReduceMin/ReduceMax 归约后用 Min 合并 body 与 tail，最终 Sub(max,min) 推算量化 scale。

（行 354-386）

```cpp
for (uint16_t j = 0; j < vfLoop - 1; j++) {
    preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg1, xAddr + multiRow * rowCount + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, smoothAddr + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg0);
    AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg0);
    AscendC::Reg::Max(vreg7, vreg3, vreg7, preg1);
    AscendC::Reg::Min(vregMinX, vreg3, vregMinX, preg1);
}
AscendC::Reg::ReduceMax(vregReduceMaxX, vreg7, preg1);
AscendC::Reg::ReduceMin(vregReduceMinX, vregMinX, preg1);

preg4 = AscendC::Reg::UpdateMask<float>(tailNum);
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
```

**要点**: ① 实参 4 个、未显式给模板参数（T/mode 走默认），mask 为 UpdateMask 生成的 preg；② Min 与 Max 成对出现，配合 ReduceMin/ReduceMax 做逐元素极值 + 跨 block 归约两段式求极值；③ 末尾 Sub(vregFinalMax, vregFinalMin) 得 max-min 作量化范围。

### 实例 2：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Max, PostLiteral, ReduceMax, RegLayout, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **Min 调用次数**: 6
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: float）
- **语义**: 在 dynamic_block_quant 中用 Min<float, MERGING> 把 input_max/FP_MAX 与 1/minScale 取小，得到受限 scale，MERGING 保留未命中元素原值。

**片段 1** (行 353-368):

```cpp
                                       (AscendC::Reg::RegTensor<uint32_t>&)vReg2,
                                       defaultMaskReg);

AscendC::Reg::Duplicate(vReg4, vReg3, defaultMaskReg);

// brc(input_max) - 位模式直接参与计算
AscendC::Reg::Div<float, &mode>(vReg8, (AscendC::Reg::RegTensor<float>&)vReg4,
                                     fp8MaxValue, defaultMaskReg);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(
    scaleMaskReg, (AscendC::Reg::RegTensor<uint32_t>&)vReg8, infValue_, defaultMaskReg);
AscendC::Reg::Min<float, AscendC::Reg::MaskMergeMode::MERGING>(
    vReg8, vReg8, reciprocalScale, scaleMaskReg);

// copy out scale
Reg::StoreUnAlign<float, Reg::PostLiteral::POST_MODE_UPDATE>(scaleLocal, vReg8, ureg,
                                                                       static_cast<uint32_t>(1));
```

**片段 2** (行 480-495):

```cpp
AscendC::Reg::Duplicate(vReg4, vReg3, defaultMaskReg);

// cast_to_f32
AscendC::Reg::Cast<float, IN_TYPE, castTraitZero>(vReg5, vReg4, defaultMaskReg);

// input_max / FP_MAX
AscendC::Reg::Div<float, &mode>(vReg8, vReg5, fp8MaxValue, defaultMaskReg);
AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(
    scaleMaskReg, (AscendC::Reg::RegTensor<uint32_t>&)vReg8, infValue_, defaultMaskReg);
// Min(input_max / FP_MAX, 1 / minScale)
AscendC::Reg::Min<float, AscendC::Reg::MaskMergeMode::MERGING>(
    vReg8, vReg8, reciprocalScale, scaleMaskReg);

// copy out scale
Reg::StoreUnAlign<float, Reg::PostLiteral::POST_MODE_UPDATE>(scaleLocal, vReg8, ureg,
                                                                       static_cast<uint32_t>(1));
```

**要点**: ① 显式模板参数 <float, MaskMergeMode::MERGING>，第 4 实参 scaleMaskReg 由 CompareScalar<LT> 产生；② MERGING 模式未命中元素保留 dstReg 原值（注意：本 API 文档标注 Reg::Min 的 MERGING 当前不支持，arch35 实际可用形态在 Reg 命名空间下）；③ 与 CompareScalar 配合实现条件取小——仅 scale < inf 时取 reciprocalScale。

### 实例 3：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Min 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: 在 fake_quant 仿射量化中用 Min<float, ZEROING> 把 x 上限钳到 nudgedMax，再配合 Max 钳到 nudgedMin，实现 clip 到 [nudgedMin, nudgedMax]。

（行 425-444）

```cpp

// 2.6 nudged_min = (qMin - nudged_zp) * scaleSafe
//     nudged_max = (qMax - nudged_zp) * scaleSafe
AscendC::Reg::Muls<float>(vregNudgedMin, vregNudgedZp, -1.0f, mask);
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
```

**要点**: ① 显式 <float, MaskMergeMode::ZEROING>，mask 未选中元素在 dstReg 置零；② Min/Max 配对实现双向 clamp（先 min 上限再 max 下限）；③ 与 Muls/Adds/Mul 链先构造 nudgedMin/nudgedMax 再 clip。

### 实例 4：dynamic_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Adds, Cast, CreateMask, DataCopy, Div, DivSpecificMode, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Muls, ReduceMax, ReduceMin, RegTensor, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **Min 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 dynamic_quant 非对称分支中用 Min(vreg8, vreg1, vreg8, mask) 维护逐元素运行最小值，与 Max/ReduceMin 配合得到全量 min 用于量化 offset。

**片段 1** (行 466-481):

```cpp
    if constexpr (isSymmetrical) {
        AscendC::Reg::Abs(vreg5, vreg1, maskAll);
        AscendC::Reg::Muls(vreg5, vreg5, scaleMaxValue, maskAll);
        AscendC::Reg::Max(vreg6, vreg5, vreg6, maskAll);
    } else {
        AscendC::Reg::Max(vreg6, vreg1, vreg6, maskAll);
        AscendC::Reg::Min(vreg8, vreg1, vreg8, maskAll);
    }
}
{
    if constexpr (isSymmetrical) {
        AscendC::Reg::ReduceMax<float>(vregMax, vreg6, maskAll);
    } else {
        AscendC::Reg::ReduceMax<float>(vregMax, vreg6, maskAll);
        AscendC::Reg::ReduceMin<float>(vregMin, vreg8, maskAll);
    }
```

**片段 2** (行 475-507):

```cpp
{
    if constexpr (isSymmetrical) {
        AscendC::Reg::ReduceMax<float>(vregMax, vreg6, maskAll);
    } else {
        AscendC::Reg::ReduceMax<float>(vregMax, vreg6, maskAll);
        AscendC::Reg::ReduceMin<float>(vregMin, vreg8, maskAll);
    }
    mask = AscendC::Reg::UpdateMask<float>(tailNum);
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg0, inLocalAddr + (vfLoopNum - 1) * VL);
    AscendC::Reg::Cast<float, T, castTrait0>(vreg1, vreg0, mask);
    if constexpr (hasSmooth == 1) {
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
            vreg2, smoothLocalAddr + (vfLoopNum - 1) * VL);
        AscendC::Reg::Cast<float, T, castTrait0>(vreg3, vreg2, mask);
        AscendC::Reg::Mul(vreg1, vreg1, vreg3, mask);
    }
    if constexpr (isSymmetrical) {
        AscendC::Reg::Abs(vreg5, vreg1, mask);
        AscendC::Reg::Muls(vreg5, vreg5, scaleMaxValue, mask);
        AscendC::Reg::Max(vreg6, vreg5, vreg6, mask);
        AscendC::Reg::ReduceMax<float>(vregMaxTail, vreg6, mask);
        AscendC::Reg::Max(vregMax, vregMax, vregMaxTail, mask);
    } else {
        AscendC::Reg::Max(vreg6, vreg1, vreg6, mask);
        AscendC::Reg::Min(vreg8, vreg1, vreg8, mask);
        AscendC::Reg::ReduceMax<float>(vregMaxTail, vreg6, mask);
        AscendC::Reg::ReduceMin<float>(vregMinTail, vreg8, mask);
        AscendC::Reg::Max(vregMax, vregMax, vregMaxTail, mask);
        AscendC::Reg::Min(vregMin, vregMin, vregMinTail, mask);
    }
}
```

**要点**: ① 未显式模板参数，mask 实参为 maskAll/mask（UpdateMask 生成）；② Min 的 dstReg 与 srcReg0 复用同一寄存器 vreg8 实现原地累极值；③ isSymmetrical 编译期分支：对称走 Abs+Max，非对称走 Max+Min 双极值。

### 实例 5：grouped_dynamic_block_quant::ops::IsSame

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CompareScalar, CreateMask, Div, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, ReduceMax, RegTensor, StoreAlign, StoreDist, UpdateMask
- **Min 调用次数**: 4
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: float）
- **语义**: 在 grouped_dynamic_block_quant 中先 ReduceMax 求块内指数最大值，再用 Min<float, MERGING> 把 input_max/FP_MAX 与 1/minScale 取小得到分组 scale。

（行 355-380）

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
// Min(input_max / FP_MAX, 1 / minScale)
AscendC::Reg::Min<float, AscendC::Reg::MaskMergeMode::MERGING>(
    (AscendC::Reg::RegTensor<float>&)scaleRegTensor,
    (AscendC::Reg::RegTensor<float>&)scaleRegTensor, minScaleRegTensor, scaleMaskReg);
AscendC::Reg::StoreAlign<uint32_t, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
    scaleOutAddr + stepBlock * 8, scaleRegTensor, scaleMask32);
```

**要点**: ① <float, MaskMergeMode::MERGING>，第 4 实参 scaleMaskReg 由 CompareScalar<LT> 产生；② 与 dynamic_block_quant 同族，scale 计算逻辑一致（Min(x/FP_MAX, 1/minScale)）；③ StoreAlign::DIST_FIRST_ELEMENT_B32 只存 scale 第一个元素。

### 实例 6：log_sigmoid::LogSigmoidCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, CompareScalar, DataCopy, Div, Duplicate, Exp, Log, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **Min 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 log_sigmoid 中用 Min(minRes, x, zeroReg, mask) 计算 min(x, 0)，作为 log(1+e^x) 分段展开项，与 Exp/Log/Select 链组合得数值稳定的 log(sigmoid(x))。

（行 66-86）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    // regCopyIn
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    Reg::DataCopy(x, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::Min(minRes, x, zeroReg, mask);        // x1 = min(x, 0)
    Reg::Abs(xAbs, x, mask);                   // x2 = abs(x)
    Reg::Muls(xAbsNeg, xAbs, valNegOne, mask); // x3 = -x2
    Reg::Exp(expRes, xAbsNeg, mask);           // x4 = e^x3
    // log1p
    Reg::Adds(expResPlusOne, expRes, valPosOne, mask);              // y1 = 1 + x4
    Reg::Adds(expResPlusOneSubOne, expResPlusOne, valNegOne, mask); // y2 = y1 - 1
    Reg::Div(divRes, expRes, expResPlusOneSubOne, mask);            // y3 = x4 / y2
    Reg::Log(logExpXPlus1, expResPlusOne, mask);                    // y4 = log(y1)
    Reg::Mul(mulRes, logExpXPlus1, divRes, mask);                   // y5 = y4 * y3
    Reg::CompareScalar<T, CMPMODE::NE>(cmpLog1pPosMaskReg, expResPlusOne, valPosOne, mask);
    Reg::Select(selectRes, mulRes, expRes, cmpLog1pPosMaskReg); // z1 = select(x4, y5)
    Reg::Sub(ans, minRes, selectRes, mask);                     // z2 = x1 - z1

    // regCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), ans, mask);
}
```

**要点**: ① 未显式模板参数，第 3 实参 zeroReg 是预先 Duplicate 的 0 向量；② Min(min(x,0)) 是 log-sigmoid 分段公式的关键预处理；③ 与 Select 配合处理 x>0 分支（CMPMODE::NE 选 mulRes 或 expRes）。

### 实例 7：dynamic_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Cast, CreateMask, DataCopy, Div, Duplicate, LoadDist, MaskPattern, MaskReg, Max, Mul, RegTensor, StoreDist, Sub, UpdateMask
- **Min 调用次数**: 1
- **参数模式**: `T1_A4_M0_TYPEfloat`（实参 4 个，类型: float）
- **语义**: 在 dynamic_quant 逐通道量化中用 Min<float>(vregColMin, vregInFp32, vregColMin, preg0) 维护每列最小值，与 Max 配合得列级 max-min 作量化范围。

（行 378-392）

```cpp
for (uint16_t j = 0; j < mLoopNum; j++) {
    Reg::DataCopy<xDtype, Reg::LoadDist::DIST_UNPACK_B16>(
        vregIn, (__ubuf__ xDtype*)(inAddr + i * REG_LEN + (j + bIdx * mLen_) * nSize));
    Reg::Cast<float, xDtype, castTraitB16ToB32>(vregInFp32, vregIn, preg0);
    if constexpr (hasSmooth) {
        Reg::DataCopy<xDtype, Reg::LoadDist::DIST_BRC_B16>(
            vregSmooth, (__ubuf__ xDtype*)(smoothAddr + j));
        Reg::Cast<float, xDtype, castTraitB16ToB32>(vregSmoothFp32, vregSmooth, preg0);
        Reg::Mul<float>(vregInFp32, vregInFp32, vregSmoothFp32, preg0);
    }
    Reg::Max<float>(vregColMax, vregInFp32, vregColMax, preg0);
    Reg::Min<float>(vregColMin, vregInFp32, vregColMin, preg0);
}
Reg::Sub(vregResult, vregColMax, vregColMin, preg0);
Reg::Mul(vregOutScale, vregResult, vregOffsetDivVal, preg0);
```

**要点**: ① 显式 <float> 但未给 mode（走默认 ZEROING），第 4 实参 preg0 为全量 mask；② Min.dstReg 与 srcReg0 复用 vregColMin 实现原地列极值累加；③ hasSmooth 分支先 Mul smooth 再求极值。

### 实例 8：dynamic_quant::ComputeMaxColScaleVF

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, DataCopy, LoadDist, MaskPattern, MaskReg, Max, ReduceMax, ReduceMin, RegTensor, RegTraitNumOne, StoreDist, UpdateMask
- **Min 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 dynamic_quant 列级 scale 计算中，从 local mem 载入历史 min 后用 Min(vreg1_2, vreg0_2, vreg1_2, mask) 跨 block 累积最小值，再 ReduceMin 归约。

**片段 1** (行 447-458):

```cpp
if constexpr (isSymmertrical == false) {
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(vreg0_1,
                                                                               maxLocalAddr + i * VL);
    AscendC::Reg::Max(vreg1_1, vreg0_1, vreg1_1, mask);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(vreg0_2,
                                                                               minLocalAddr + i * VL);
    AscendC::Reg::Min(vreg1_2, vreg0_2, vreg1_2, mask);
} else {
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(vreg0_1,
                                                                               scaleLocalAddr + i * VL);
    AscendC::Reg::Max(vreg1_1, vreg0_1, vreg1_1, mask);
}
```

**片段 2** (行 470-488):

```cpp
if constexpr (isSymmertrical == false) {
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(vreg0_1,
                                                                               maxLocalAddr + i * VL);
    AscendC::Reg::Max(vreg1_1, vreg0_1, vreg1_1, mask);
    AscendC::Reg::ReduceMax<float>(vreg3_1, vreg1_1, mask);
    AscendC::Reg::Max(vreg3_1, vreg2_1, vreg3_1, mask);

    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(vreg0_2,
                                                                               minLocalAddr + i * VL);
    AscendC::Reg::Min(vreg1_2, vreg0_2, vreg1_2, mask);
    AscendC::Reg::ReduceMin<float>(vreg3_2, vreg1_2, mask);
    AscendC::Reg::Min(vreg3_2, vreg2_2, vreg3_2, mask);
} else {
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(vreg0_1,
                                                                               scaleLocalAddr + i * VL);
    AscendC::Reg::Max(vreg1_1, vreg0_1, vreg1_1, mask);
    AscendC::Reg::ReduceMax<float>(vreg3_1, vreg1_1, mask);
    AscendC::Reg::Max(vreg3_1, vreg2_1, vreg3_1, mask);
}
```

**要点**: ① 未显式模板参数，mask 为 UpdateMask 生成；② Min 用于载入-累极值-归约三步式跨 block 合并；③ 与 Max 镜像对称（vreg1_1/vreg3_1 走 max 路径）。

### 实例 9：dynamic_block_quant::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CompareScalar, DataCopy, Div, Duplicate, LoadDist, MaskMergeMode, MaskReg, RegTensor, StoreDist, UpdateMask
- **Min 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: float）
- **语义**: 在 dynamic_block_quant 大 blocksize 路径中，float32 走位模式直传快速路径，用 Min<float, MERGING> 把 input_max/FP_MAX 与 1/minScale 取小得到 scale。

（行 492-511）

```cpp
if constexpr (IsSameType<T, float>::value) {
    // float32: 位模式本身就是 float，不需要 Cast 和 UNPACK
    AscendC::Reg::DataCopy(vreg1, xLocalMaxTmp);
    // 位模式直接参与计算
    AscendC::Reg::Div<float, &mode>(vreg5, (AscendC::Reg::RegTensor<float>&)vreg1, vreg3, preg0);
} else {
    // FP16/BF16: 需要 UNPACK 和 Cast
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vreg1, xLocalMaxTmp);
    AscendC::Reg::Cast<float, T, castTrait0>(vreg2, vreg1, preg0);
    AscendC::Reg::Div<float, &mode>(vreg5, vreg2, vreg3, preg0);
}

AscendC::Reg::CompareScalar<uint32_t, CMPMODE::LT>(
    scaleMaskReg, (AscendC::Reg::RegTensor<uint32_t>&)vreg5, infValue_, preg0);
// Min(input_max / FP_MAX, 1 / minScale)
AscendC::Reg::Min<float, AscendC::Reg::MaskMergeMode::MERGING>(vreg5, vreg5, reciprocalScale,
                                                                         scaleMaskReg);

AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(scaleLocalTmp, vreg5,
                                                                                         preg0);
```

**要点**: ① <float, MaskMergeMode::MERGING>，scaleMaskReg 由 CompareScalar<LT> 产生；② IsSameType<T,float> 分支：float32 不需 Cast/UNPACK，位模式直接参与计算；③ 与 small_blocksize 路径逻辑一致，差异仅在 Cast 前处理。

### 实例 10：acts_ulq::ClampVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, CreateAddrReg, LoadAlign, MaskReg, Max, RegTensor, StoreAlign, UpdateMask
- **Min 调用次数**: 1
- **参数模式**: `T1_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 acts_ulq 的 ClampVF 中用 Min<T>(dstReg, tmpReg, cxReg, mask) 把 Max(data, clipMin) 的结果再上限钳到 clipMax，实现 clamp 到 [clipMin, clipMax]。

（行 599-613）

```cpp
{
    AscendC::Reg::RegTensor<T> dataReg, cmReg, cxReg, tmpReg, dstReg;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(dataReg, dataAddr, aReg);
        AscendC::Reg::LoadAlign(cmReg, clipMinAddr, aReg);
        AscendC::Reg::LoadAlign(cxReg, clipMaxAddr, aReg);
        AscendC::Reg::Max<T>(tmpReg, dataReg, cmReg, mask);
        AscendC::Reg::Min<T>(dstReg, tmpReg, cxReg, mask);
        AscendC::Reg::StoreAlign(dstAddr, dstReg, aReg, mask);
    }
}
```

**要点**: ① 显式 <T>（模板参数 T），mode 走默认 ZEROING，mask 由 UpdateMask 生成；② Max+Min 配对实现双向 clamp（先 max 下限再 min 上限）；③ 与 LoadAlign/StoreAlign/AddrReg 配合做按 repeat 的块状 clamp。

### 实例 11：atan2::Atan

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, And, Div, Mul, Or, RegTensor
- **Min 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 atan2 中两次用 Min：一次 Min(absReg, absReg, thresholdReg, mask) 把 |x| 钳到 threshold 防止除法溢出，一次 Min(yReg, tmpReg0, tmpReg1, mask) 在两条 atan 近似分支中取较小值。

（行 303-328）

```cpp
    {
        Reg::RegTensor<float> absReg;
        Reg::RegTensor<float> tmpReg0;
        Reg::RegTensor<float> tmpReg1;
        Reg::RegTensor<float> signReg;
        Reg::And(
            (Reg::RegTensor<uint32_t>&)signReg, (Reg::RegTensor<uint32_t>&)xReg, floatSignMaskReg,
            mask); // 取x2符号位
        Reg::Or(
            (Reg::RegTensor<uint32_t>&)signReg, (Reg::RegTensor<uint32_t>&)signReg, floatOneMaskReg,
            mask); // +/- 1
        Reg::Abs(absReg, xReg, mask);
        Reg::Min(absReg, absReg, thresholdReg, mask); // avoid overflow

        Reg::Adds(tmpReg0, absReg, -1.0f, mask);
        Reg::Adds(tmpReg1, absReg, 1.0f, mask);
        Reg::Div(tmpReg0, tmpReg0, tmpReg1, mask);
        Reg::Abs(tmpReg1, tmpReg0, mask);
        AtanLT1(tmpReg0, tmpReg1, addReg1, addReg3, addReg5, addReg7, addReg9, mask);
        Reg::Adds(tmpReg0, tmpReg0, PI_BY_4, mask);
        AtanLT1(tmpReg1, absReg, addReg1, addReg3, addReg5, addReg7, addReg9, mask);
        Reg::Min(yReg, tmpReg0, tmpReg1, mask);
        // recover sign
        Reg::Mul(yReg, yReg, signReg, mask);
#endif
    }
```

**要点**: ① 未显式模板参数，mask 为入参 MaskReg；② Min 既做防溢出钳位又做分支选择，是 atan2 数值稳定的核心；③ 与 Abs/And/Or 配合先恢复符号位再做极值钳位。

### 实例 12：scatter_nd_common::ComputeSumWithOutCastVF

- **来源类型**: `__simd_vf__`
- **共现 API**: CreateMask, DataCopy, Duplicate, MaskReg, Max, RegTensor, UpdateMask
- **Min 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: mask, maskReg）
- **语义**: 在 scatter_nd_common 的 MODE_MIN 分支中用 Min(sumReg, sumReg, updateReg, maskReg) 做散射累加的最小值归约，MODE_MAX 分支则用 Max。

（行 538-548）

```cpp
for (uint16_t k = 0; k < idRepeatTimes; k++) {
    auto updatesOffet = updatesOriginIdexAddr[idLocation + k] * colLenAlignSize + j * vfLen;
    auto startAddr = updatesAddr + updatesOffet;
    AscendC::Reg::DataCopy(updateReg, startAddr);
    if constexpr (Mode == MODE_MAX) {
        AscendC::Reg::Max(sumReg, sumReg, updateReg, maskReg);
    } else {
        AscendC::Reg::Min(sumReg, sumReg, updateReg, maskReg);
    }
}
auto updateSumAddrOfst = updateSumAddr + i * colLenAlignSize + j * vfLen;
```

**要点**: ① 未显式模板参数，第 4 实参 maskReg 为运行时掩码（非全量 mask）；② 通过 if constexpr (Mode == MODE_MAX) 编译期选择 Min/Max，体现 Min 作为 scatter 归约算子；③ 与 DataCopy(updateReg, startAddr) 配合载入散布更新值后做极值归约。

### 实例 13：scatter_nd_common::SingleColAddVF

- **来源类型**: `__simd_vf__`
- **共现 API**: DataCopy, MaskReg, Max, RegTensor, UpdateMask
- **Min 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: mask, maskReg）
- **语义**: 在 scatter_nd_common 单列累加的 MODE_MIN 分支中用 Min(sumReg, sumReg, updateReg, maskReg) 做单列散布最小值归约。

（行 711-717）

```cpp
if constexpr (Mode == MODE_MAX) {
    AscendC::Reg::Max(sumReg, sumReg, updateReg, maskReg);
} else {
    AscendC::Reg::Min(sumReg, sumReg, updateReg, maskReg);
}
auto updateSumAddrOfst = updateSumAddr + j * vfLen;
AscendC::Reg::DataCopy(updateSumAddrOfst, sumReg, maskReg);
```

**要点**: ① 与 ComputeSumWithOutCastVF 同文件同模式，差异在 SingleColAddVF 只处理单列、循环更简；② 第 4 实参 maskReg 为运行时掩码；③ Min 后直接 DataCopy(updateSumAddrOfst, sumReg, maskReg) 写回。

### 实例 14：atan2::AtanLT1

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, Div, Muls, RegTensor
- **Min 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 atan2 的 AtanLT1 子函数中用 Min(yReg, tmpReg0, tmpReg1, mask) 在两条泰勒展开近似结果中取较小值，保证 atan 分段单调。

（行 282-328）

```cpp
    {
        Reg::RegTensor<float> tmpReg0;
        Reg::RegTensor<float> tmpReg1;
        Reg::Muls(tmpReg0, xReg, TAN_PI_BY_8, mask);
        Reg::Adds(tmpReg0, tmpReg0, 1.0f, mask);
        Reg::Adds(tmpReg1, xReg, -TAN_PI_BY_8, mask);
        Reg::Div(tmpReg0, tmpReg1, tmpReg0, mask);
        Reg::Abs(tmpReg1, tmpReg0, mask);
        TaylorSeriesExpansion(tmpReg0, tmpReg1, addReg1, addReg3, addReg5, addReg7, addReg9, mask);
        Reg::Adds(tmpReg0, tmpReg0, PI_BY_8, mask);
        TaylorSeriesExpansion(tmpReg1, xReg, addReg1, addReg3, addReg5, addReg7, addReg9, mask);
        Reg::Min(yReg, tmpReg0, tmpReg1, mask);
    }

    __aicore__ inline void Atan(
        Reg::RegTensor<float>& yReg, Reg::RegTensor<float>& xReg,
        Reg::RegTensor<uint32_t>& floatSignMaskReg, Reg::RegTensor<uint32_t>& floatOneMaskReg,
        Reg::RegTensor<float>& thresholdReg, Reg::RegTensor<float>& addReg1,
        Reg::RegTensor<float>& addReg3, Reg::RegTensor<float>& addReg5,
        Reg::RegTensor<float>& addReg7, Reg::RegTensor<float>& addReg9,
        Reg::MaskReg& mask)
    {
        Reg::RegTensor<float> absReg;
        Reg::RegTensor<float> tmpReg0;
        Reg::RegTensor<float> tmpReg1;
        Reg::RegTensor<float> signReg;
        Reg::And(
            (Reg::RegTensor<uint32_t>&)signReg, (Reg::RegTensor<uint32_t>&)xReg, floatSignMaskReg,
            mask); // 取x2符号位
        Reg::Or(
            (Reg::RegTensor<uint32_t>&)signReg, (Reg::RegTensor<uint32_t>&)signReg, floatOneMaskReg,
            mask); // +/- 1
        Reg::Abs(absReg, xReg, mask);
        Reg::Min(absReg, absReg, thresholdReg, mask); // avoid overflow

        Reg::Adds(tmpReg0, absReg, -1.0f, mask);
        Reg::Adds(tmpReg1, absReg, 1.0f, mask);
        Reg::Div(tmpReg0, tmpReg0, tmpReg1, mask);
        Reg::Abs(tmpReg1, tmpReg0, mask);
        AtanLT1(tmpReg0, tmpReg1, addReg1, addReg3, addReg5, addReg7, addReg9, mask);
        Reg::Adds(tmpReg0, tmpReg0, PI_BY_4, mask);
        AtanLT1(tmpReg1, absReg, addReg1, addReg3, addReg5, addReg7, addReg9, mask);
        Reg::Min(yReg, tmpReg0, tmpReg1, mask);
        // recover sign
        Reg::Mul(yReg, yReg, signReg, mask);
#endif
    }
```

**要点**: ① 未显式模板参数，mask 为入参；② tmpReg0/tmpReg1 分别由 TaylorSeriesExpansion 对不同输入展开，Min 选较小者；③ 与 Atan 主函数共享同一 mask，保证符号/掩码一致。

### 实例 15：foreach_non_finite_check_and_unscale::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Max, Muls
- **Min 调用次数**: 3
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: mask, maskReg）
- **语义**: 在 foreach_non_finite_check_and_unscale 中用 Min(min, min, x, maskReg) 逐循环累积最小值，末尾 ReduceMin 归约并与上一 block 的 lastMin 再 Min 合并，用于检测非有限值。

（行 203-240）

```cpp
{
    RegTensor<float> min;
    RegTensor<float> max;
    RegTensor<float> x;
    RegTensor<float> y;
    RegTensor<float> lastMin;
    RegTensor<float> lastMax;
    MaskReg pregMain = CreateMask<float, MaskPattern::ALL>();
    MaskReg pregMerge = CreateMask<float, MaskPattern::VL1>();
    MaskReg maskReg;
    Duplicate(min, float(0.0), pregMain);
    Duplicate(max, float(0.0), pregMain);
    for (uint16_t i = 0; i < repeatTimes - 1; i++) {
        maskReg = UpdateMask<float>(sreg);
        ops::LoadOneTensorForDtypeT<T>(inUbAddr, x, maskReg, i * dataCountPerLoop);
        Max(max, max, x, maskReg);
        Min(min, min, x, maskReg);
        Muls(y, x, invScaleVal, maskReg);
        ops::StoreOneTensorForDtypeT<T>(outUbAddr, y, maskReg, i * dataCountPerLoop);
    }
    {
        maskReg = UpdateMask<float>(sreg);
        ops::LoadOneTensorForDtypeT<T>(inUbAddr, x, maskReg, (repeatTimes - 1) * dataCountPerLoop);
        Adds(x, x, float(0.0), maskReg);
        Max(max, max, x, pregMain);
        Min(min, min, x, pregMain);
        Muls(y, x, invScaleVal, maskReg);
        ops::StoreOneTensorForDtypeT<T>(outUbAddr, y, maskReg, (repeatTimes - 1) * dataCountPerLoop);
    }
    DataCopy(lastMin, (__local_mem__ float*)(minUbAddr));
    DataCopy(lastMax, (__local_mem__ float*)(maxUbAddr));
    ReduceMax(max, max, pregMain);
    ReduceMin(min, min, pregMain);
    Max(lastMax, lastMax, max, pregMain);
    Min(lastMin, lastMin, min, pregMain);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(((__local_mem__ float*)minUbAddr), lastMin, pregMerge);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(((__local_mem__ float*)maxUbAddr), lastMax, pregMerge);
}
```

**要点**: ① 未显式模板参数，掩码混合 maskReg（运行时）与 pregMain（CreateMask 全量）；② Min 与 Max 镜像配对同时跑 min/max 两条累极值链；③ 末尾 ReduceMin + Min(lastMin,...) 实现跨 block 极值合并，结果存 local mem 第一个元素。

### Min 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | 逐元素 Min 累积极值 + ReduceMin 归约 + 跨 block Min 合并 | __aicore__ |
| dynamic_block_quant | And, Cast, CastTrait, CompareScalar, CreateMask | Min<float,MERGING> 条件取小（CompareScalar 掩码）限幅 scale | __VEC_SCOPE__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | Min<float,ZEROING> 上限钳位 + Max 下限钳位（双向 clamp） | __VEC_SCOPE__ |
| dynamic_quant | Abs, Adds, Cast, CreateMask, DataCopy | 非对称分支 Min 原地累运行最小值 + ReduceMin | __VEC_SCOPE__ |
| grouped_dynamic_block_quant | And, Cast, CompareScalar, CreateMask, Div | Min<float,MERGING> 限幅分组 scale（同 dynamic_block_quant 族） | __VEC_SCOPE__ |
| log_sigmoid | Abs, Adds, CompareScalar, DataCopy, Div | Min(x, 0) 作分段公式预处理 + Select 分支 | __aicore__ |
| dynamic_quant | Add, Cast, CreateMask, DataCopy, Div | Min<float> 原地累每列最小值 + Sub(max,min) 求量化范围 | __VEC_SCOPE__ |
| dynamic_quant | CreateMask, DataCopy, LoadDist, MaskPattern, MaskReg | 载入-Min 累极值-ReduceMin 三步跨 block 合并 | __aicore__ |
| dynamic_block_quant | Cast, CompareScalar, DataCopy, Div, Duplicate | Min<float,MERGING> 限幅 scale（float32 位模式快速路径） | __VEC_SCOPE__ |
| acts_ulq | AddrReg, CreateAddrReg, LoadAlign, MaskReg, Max | Max+Min 配对双向 clamp 到 [clipMin, clipMax] | __simd_vf__ |
| atan2 | Abs, Adds, And, Div | Min 双用——防溢出钳位 + 分支选择 | __aicore__ |
| scatter_nd_common | CreateMask, DataCopy, Duplicate, MaskReg, Max | MODE_MIN 分支 Min 散射最小值归约 | __simd_vf__ |
| scatter_nd_common | DataCopy, MaskReg, Max, RegTensor | MODE_MIN 分支单列 Min 散射归约 | __simd_vf__ |
| atan2 | Abs, Adds, Div, Muls | Min 选两条泰勒展开较小值保单调 | __aicore__ |
| foreach_non_finite_check_and_unscale | Adds, Max, Muls | Min 逐循环累极值 + ReduceMin + 跨 block Min 合并 | __VEC_SCOPE__ |
