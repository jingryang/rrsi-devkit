# Or

**页面ID:** atlasascendc_api_07_0363  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0363.html

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

本节介绍两种接口，分别用于对RegTensor和MaskReg进行操作：

- 对RegTensor操作：

根据mask对输入数据srcReg0、srcReg1按元素求或（|）操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0363_img_001.png)

- 对MaskReg操作：

将两个输入MaskReg的有效bit进行逻辑或运算得到新的MaskReg。

#### 函数原型

- 对RegTensor操作

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Or(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

- 对MaskReg操作

```
__simd_callee__ inline void Or(MaskReg& dst, MaskReg& src0, MaskReg& src1, MaskReg& mask)
```

#### 参数说明

- 对RegTensor操作

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：bool/uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/uint64_t/int64_t |
| mode | 选择MERGING模式或ZEROING模式。   - ZEROING，mask未筛选的元素在dst中置零。  - MERGING，当前不支持。 |
| U | srcReg0/srcReg1/dstReg RegTensor类型， 例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

- 对MaskReg操作

**表3 **参数说明

| 参数名 | 描述 |
| --- | --- |
| dst | 目的操作数。 |
| src0 | 源操作数。 |
| src1 | 源操作数。 |
| mask | 指示在计算过程中哪些bit有效。 |

#### 约束说明

无

#### 调用示例

- 对RegTensor操作

```
template <typename T>
__simd_vf__ inline void OrVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::Or(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 对MaskReg操作

```
template <typename T>
__simd_vf__ inline void OrVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg src0 = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALLF>();
    AscendC::Reg::MaskReg src1 = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg dst;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Or(dst, src0, src1, mask);
        AscendC::Reg::Adds(srcReg, srcReg, 0, dst);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Or 实例

### 实例 1：tanh::TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, And, Cast, CompareScalar, DataCopy, Div, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Or 调用次数**: 4
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: uint32_t, int32_t）
- **语义（待补充）**: tanh 算子中用 Or 把输入符号位回注到中间计算结果：先用 And 抽取输入符号位，再用 Or 把符号位合并回中间值，配合 satMask 饱和与 Select 恢复带符号的 tanh 输出。

（行 87-105）

```cpp
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
```

**要点**: 通过 `(RegTensor<uint32_t, RegTraitNumOne>&)` 强转把 float 当 uint32 做位运算；Or 的 dst 与 src0 复用同一寄存器实现原地符号位合并；mask 为 ZEROING 模式，未选中元素置零。

### 实例 2：scatter_nd_common::ComputeOutOfsetVF

- **来源类型**: `__simd_vf__`
- **共现 API**: Add, Adds, Arange, Cast, CompareScalar, CreateMask, DataCopy, DataCopyGather, Duplicate, MaskPattern, MaskReg, Muls, RegTensor, RegTraitNumTwo, Select, UpdateMask
- **Or 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: scatter_nd 索引计算中，对每个索引分别做 <0 与 >=outputShape 两次越界比较，用 Or 把两次的 cmpMask 累积合并到 invalidMask，得到统一的非法索引标志。

（行 263-278）

```cpp
if constexpr (IsSameType<U, int32_t>::value && IsSameType<OFFSET_T, int64_t>::value) {
    AscendC::Reg::RegTensor<int32_t> castReg;
    AscendC::Reg::DataCopyGather(castReg, indicesLocalPtr, indexReg, pregLoop);
    Reg::Cast<int64_t, int32_t, castTraitB322B64>(inReg, castReg, pregLoop);
} else {
    AscendC::Reg::DataCopyGather(inReg, indicesLocalPtr, indexReg, pregLoop);
}
AscendC::Reg::CompareScalar<OFFSET_T, CMPMODE::LT>(cmpMask, inReg, static_cast<OFFSET_T>(0),
                                                        pregLoop);
AscendC::Reg::Or(invalidMask, invalidMask, cmpMask, pregLoop);
AscendC::Reg::CompareScalar<OFFSET_T, CMPMODE::GE>(
    cmpMask, inReg, static_cast<OFFSET_T>(outputShapeValue), pregLoop);
AscendC::Reg::Or(invalidMask, invalidMask, cmpMask, pregLoop);

AscendC::Reg::Muls(inReg, inReg, strideValue, pregLoop);
AscendC::Reg::Add(outReg, inReg, outReg, pregLoop);
```

**要点**: `Or(dst, dst, src, mask)` 形式做 mask 累积，等价逻辑或归约；4 实参含 mask，pregLoop 作逐元素有效指示；合并后的 invalidMask 供后续 Select 决定是否写回。

### 实例 3：random_common::Uint16ToBfloat16

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, CreateMask, DataCopy, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, PostLiteral, RegTensor, StoreDist, UpdateMask
- **Or 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEint16_t_MASKmask`（实参 4 个，含 mask/mode: mask，类型: int16_t）
- **语义（待补充）**: 随机数生成中先用 And 取随机整数低位、Or 把高位随机比特拼到结果，构造 bfloat16 尾数位模式，再 Adds 加偏移生成最终随机浮点值。

（行 184-195）

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(repeatTimes); ++i) {
    mask = Reg::UpdateMask<float>(sReg1);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_NORM>(
        vRegT, ubPhilox, offSet);
    Reg::Cast<int16_t, int32_t, castTraitTf>(vReg0, vRegT, mask);
    Reg::And<int16_t, Reg::MaskMergeMode::ZEROING>(vReg2, vReg0, vReg1, mask);
    Reg::Or<int16_t, Reg::MaskMergeMode::ZEROING>(vReg4, vReg2, vReg3, mask);
    vReg5 = (Reg::RegTensor<bfloat16_t>&)vReg4;
    Reg::Adds<bfloat16_t, bfloat16_t, Reg::MaskMergeMode::ZEROING>(vReg6, vReg5, sReg4, mask);
    Reg::DataCopy<bfloat16_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::StoreDist::DIST_PACK_B32>(
        ubOut, vReg6, offSet, mask);
}
```

**要点**: 显式模板参数 `<int16_t, MaskMergeMode::ZEROING>`；Or/And 配合做位拼接是随机数浮点构造的典型模式；mask 来自 `UpdateMask<float>`，逐 repeat 控制有效元素。

### 实例 4：random_common::Uint32ToFloat

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, CreateMask, DataCopy, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, PostLiteral, RegTensor, StoreDist, UpdateMask
- **Or 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEint32_t_MASKmask`（实参 4 个，含 mask/mode: mask，类型: int32_t）
- **语义（待补充）**: 随机数生成中 And 取随机整数位、Or 拼接成 float 的位模式，再 Adds 加指数偏移得到 [0,1) 均匀分布浮点。

（行 90-100）

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(repeatTimes); ++i) {
    mask = Reg::UpdateMask<float>(sReg1);
    Reg::DataCopy<int32_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_NORM>(
        vReg0, ubPhilox, offSet);
    Reg::And<int32_t, Reg::MaskMergeMode::ZEROING>(vReg2, vReg0, vReg1, mask);
    Reg::Or<int32_t, Reg::MaskMergeMode::ZEROING>(vReg4, vReg2, vReg3, mask);
    vReg5 = (Reg::RegTensor<float>&)vReg4;
    Reg::Adds<float, float, Reg::MaskMergeMode::ZEROING>(vReg6, vReg5, sReg4, mask);
    Reg::DataCopy<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::StoreDist::DIST_NORM_B32>(
        ubOut, vReg6, offSet, mask);
}
```

**要点**: 模板参数 `<int32_t, ZEROING>` 对应 32 位拼接，与实例 3 同构仅位宽不同；结果转 `(RegTensor<float>&)` 后做浮点加法；位拼接 + 指数偏移是均匀分布生成的标准套路。

### 实例 5：cast::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CreateMask, DataCopy, DeInterleave, Duplicate, MaskMergeMode, MaskReg, PostLiteral, RegTensor, ShiftLefts, UpdateMask
- **Or 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: cast 算子对交错数据 DeInterleave 后，ShiftLefts 把第二路左移 4 位、And 取第一路低 4 位，Or 合并两路 nibble 成完整 8 位结果，完成 int4→int8 类型转换。

（行 1473-1485）

```cpp
for (uint16_t loopIdx = 0; loopIdx < regLoop; loopIdx++) {
    Reg::DataCopy<MST, Reg::PostLiteral::POST_MODE_UPDATE, ldDist>(vregIn1, srcAddr, regCopyInStep);
    Reg::DataCopy<MST, Reg::PostLiteral::POST_MODE_UPDATE, ldDist>(vregIn2, srcAddr, regCopyInStep);

    Reg::DeInterleave<MMT>(vregDeinter1, vregDeinter2, vregIn1, vregIn2);
    Reg::And<MMT, Reg::MaskMergeMode::ZEROING>(vregMid1, vregDeinter1, vreg4Bit, maskAll);
    Reg::ShiftLefts(vregMid2, vregDeinter2, SHIFT_FOUR_BITS, maskAll);
    Reg::Or<MMT, Reg::MaskMergeMode::ZEROING>(vregOut, vregMid1, vregMid2, maskAll);

    mask = Reg::UpdateMask<MMT>(count);
    Reg::DataCopy<MMT, Reg::PostLiteral::POST_MODE_UPDATE, stDist>(dstAddr,
        vregOut, regCopyOutStep, mask);
}
```

**要点**: 4 实参含 mask，`<MMT, ZEROING>` 模板；Or 用于半字节拼接，是 int4→int8 转换的核心步骤；maskAll 全有效，UpdateMask 在写出前刷新尾元素 mask。

### 实例 6：adaptive_pool3d_common::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Compare, CreateMask, DataCopy, Duplicate, HighLowPart, MaskReg, RegTensor, Select, UnPack
- **Or 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: 自适应 maxpool 中 Compare NE 检测 NaN（inputReg≠inputReg 为真即 NaN），Or 把 NaN mask 合入 GT 比较 mask，使 NaN 也触发 Select 更新，避免 NaN 被静默忽略。

（行 436-453）

```cpp
for (uint16_t k = 1; k < kernelSize; k++) {
    Reg::DataCopy(inputReg, srcOfset + k * vfLen);
    Reg::Compare<T, CMPMODE::GT>(cmpMask, inputReg, maxReg, fullMask);
    Reg::Compare<T, CMPMODE::NE>(cmpMaskNan, inputReg, inputReg, fullMask);
    Reg::Or(cmpMask, cmpMask, cmpMaskNan, fullMask);
    AscendC::Reg::Select(maxReg, inputReg, maxReg, cmpMask);

    Reg::Adds(inputIndexReg, inputIndexReg, static_cast<int32_t>(1), indexMask);
    if constexpr (IsSameType<T, float>::value) {
        AscendC::Reg::Select(maxIndexReg, inputIndexReg, maxIndexReg, cmpMask);
    } else {
        AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::LOWEST>(cmpIndexMask, cmpMask);
        AscendC::Reg::Select(maxIndexReg, inputIndexReg, maxIndexReg, cmpIndexMask);

        AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::HIGHEST>(cmpIndexMask, cmpMask);
        AscendC::Reg::Select(maxIndexReg1, inputIndexReg, maxIndexReg1, cmpIndexMask);
    }
}
```

**要点**: `Or(cmpMask, cmpMask, cmpMaskNan, fullMask)` 把"更大"和"是 NaN"两种需更新的情况合并；fullMask 全有效；合并后 cmpMask 驱动 Select 更新最大值与最大值索引。

### 实例 7：glu::ComputeSigmoidAndMulCore

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, DataCopy, Div, Exp, MaskMergeMode, Mul, Muls, RegTensor
- **Or 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint16_t+uint16_t`（实参 1 个，类型: uint16_t, int16_t）
- **语义（待补充）**: GLU 算子把 sigmoid 路与乘积路两路 half 结果用 Or 拼合符号位与尾数，复用同一输出寄存器写入 UB。

（行 95-113）

```cpp
AscendC::Reg::Div<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg4, vreg0, vreg3, maskAll8);

AscendC::Reg::Mul<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg7, vreg4, vreg5, maskAll8);

AscendC::Reg::Muls<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vreg11, vreg9, static_cast<float>(-1), maskAll8);
AscendC::Reg::Exp<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg12, vreg11, maskAll8);
AscendC::Reg::Adds<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(
    vreg13, vreg12, static_cast<float>(1), maskAll8);
AscendC::Reg::Div<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg14, vreg0, vreg13, maskAll8);

AscendC::Reg::Mul<float, AscendC::Reg::MaskMergeMode::ZEROING>(vreg10, vreg14, vreg6, maskAll8);

AscendC::Reg::Cast<T, float, castTrait11>(vreg15, vreg7, maskAll8);
AscendC::Reg::Cast<T, float, castTrait12>(vreg16, vreg10, maskAll8);
AscendC::Reg::Or((Reg::RegTensor<uint16_t>&)vregOutput, (Reg::RegTensor<uint16_t>&)vreg15,
                 (Reg::RegTensor<uint16_t>&)vreg16, maskAll8);

AscendC::Reg::DataCopy(outLocalPtr + loopIdx * vlSize, vregOutput, preg0);
```

**要点**: 16 位类型，`Or((RegTensor<uint16_t>&)...)` 强转 half 为 uint16 位运算；maskAll8 全有效；此处 Or 做位拼接而非逻辑或，合并两路 half 的位模式到输出。

### 实例 8：ceil::CeilCustom

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, MaskMergeMode, MaskReg, RegTensor, RegTraitNumOne, Truncate, UpdateMask
- **Or 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEint32_t+uint32_t_MASKmask`（实参 4 个，含 mask/mode: mask，类型: uint32_t, int32_t）
- **语义（待补充）**: ceil 算子中 Duplicate 出符号位掩码 UINT32_SIGN，And 取输入原符号位，Truncate 做向上取整，Or 把原符号位合并回取整结果，保证负数 ceil 后符号正确。

（行 48-62）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

    Reg::Truncate<T, RoundMode::CAST_CEIL, Reg::MaskMergeMode::ZEROING>(
        vregOutput, vregInput, mask);
    Reg::Duplicate(vregOutInt, UINT32_SIGN, mask);
    Reg::And(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t>&)vregInput, mask);
    Reg::Or(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t>&)vregOutput, mask);

    // OpCopyOut
    Reg::DataCopy(
        (__ubuf__ T*)(dstAddr + loopIdx * vlSize), (Reg::RegTensor<T>&)vregOutInt, mask);
}
```

**要点**: 4 实参含 mask，`<T,...,ZEROING>` + RegTraitNumOne；And+Or 组合保留原值符号位是定点取整算子的通用模式；dst 与 src 复用 vregOutInt 实现原地合并。

### 实例 9：truncate_div::TruncCustom

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, MaskMergeMode, MaskReg, RegTensor, RegTraitNumOne, Truncate, UpdateMask
- **Or 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEint32_t+uint32_t_MASKmask`（实参 4 个，含 mask/mode: mask，类型: uint32_t, int32_t）
- **语义（待补充）**: truncate_div 中 And 取被除数符号位、Truncate 做截断取整、Or 把符号位合并回结果，保证向零截断后符号不丢。

（行 60-74）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

    Reg::Truncate<T, RoundMode::CAST_TRUNC, Reg::MaskMergeMode::ZEROING>(vregOutput,
                                                                                   vregInput, mask);
    Reg::Duplicate(vregOutInt, UINT32_SIGN, mask);
    Reg::And(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t>&)vregInput, mask);
    Reg::Or(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t>&)vregOutput, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), (Reg::RegTensor<T>&)vregOutInt,
                       mask);
}
```

**要点**: 与 ceil/round/rint 同构的"符号位保留"模式，仅 RoundMode 不同（CAST_TRUNC）；UINT32_SIGN 常量提供符号位掩码；Or 负责把原符号位拼回截断后的绝对值。

### 实例 10：logical_or::LogicalOrFloatCustom

- **来源类型**: `__aicore__`
- **共现 API**: Compares, DataCopy, Duplicate, LoadDist, MaskReg, RegTensor, Select, StoreDist, UpdateMask
- **Or 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEnone`（实参 1 个）
- **语义（待补充）**: logical_or 算子直接用 Or 对两路 float 做按位或（强转为整型 IntT），再 Compare NE 0 得 bool，Select 输出 uint8 的 1/0。

（行 64-89）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    preg = Reg::UpdateMask<T>(sregMask);
    // 以浮点类型 T 加载输入
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src1Value, src1Addr + VL_T * j);
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src2Value, src2Addr + VL_T * j);

    // 位OR操作：当作对应位宽的整形处理
    Reg::Or((Reg::RegTensor<IntT>&)orRes, (Reg::RegTensor<IntT>&)src1Value, (Reg::RegTensor<IntT>&)src2Value, preg);

    // Compare: OR结果 != 0 (NE模式)
    Reg::Compares<T, CMPMODE::NE>(cmpMask, orRes, static_cast<T>(0), preg);

    // Select: 根据cmpMask选择1或0 (uint8_t)
    Reg::Duplicate(oneReg, static_cast<uint8_t>(1));
    Reg::Duplicate(zeroReg, static_cast<uint8_t>(0));
    Reg::Select<uint8_t>(dstReg, oneReg, zeroReg, cmpMask);

    // 存储uint8 BOOL结果
    if constexpr (sizeof(T) == sizeof(half)) {
        Reg::DataCopy<uint8_t, Reg::StoreDist::DIST_PACK_B16>(
        dstAddr + VL_T * j, dstReg, preg);
    } else {
        Reg::DataCopy<uint8_t, Reg::StoreDist::DIST_PACK4_B32>(
        dstAddr + VL_T * j, dstReg, preg);
    }
}
```

**要点**: 4 实参无模板参数，preg 作 mask；Or 在这里是逻辑或的位级实现（任意非零即真）；sizeof(T)==sizeof(half) 时用 DIST_PACK_B16 存 bool，否则 DIST_PACK4_B32。

### 实例 11：index_put_with_sort_v2::HardEvent::MTE2_S

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, AddrReg, Cast, CreateAddrReg, DataCopy, LoadDist, MaskReg, RegTensor, UpdateMask
- **Or 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: index_put 累加时，bool 类型用 Or 累积（逻辑或），非 bool 用 Add，通过 if constexpr 按类型分派。

（行 236-240）

```cpp
if constexpr (IsSameType<SELF_TYPE, bool>::value) {
    AscendC::Reg::Or(valueSumReg, valueReg, valueSumReg, valueMaskReg);
} else {
    AscendC::Reg::Add(valueSumReg, valueReg, valueSumReg, valueMaskReg);
}
```

**要点**: `Or(valueSumReg, valueReg, valueSumReg, valueMaskReg)` 等价 bool 累加（任意一次为真即真）；4 实参含 mask；体现 Or 作为布尔归约的语义，与 Add 形成类型分派对照。

### 实例 12：atan2::PostProcess

- **来源类型**: `__aicore__`
- **共现 API**: And, CompareScalar, MaskAnd, MaskNot, MaskReg, MaskXor, RegTensor, Select
- **Or 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEint32_t+uint32_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: uint32_t, int32_t）
- **语义（待补充）**: atan2 边界处理中，And 取 x1/x2 符号位，Or 把符号位与全 1 mask 合并归一到 ±1，再 Compare EQ 判定正负，驱动后续象限分支。

（行 172-204）

```cpp
Reg::MaskReg x1NegZeroMask;
Reg::MaskReg x1PosInfMask;
Reg::MaskReg x1NegInfMask;

Reg::MaskReg x2ZeroMask;
Reg::MaskReg x2NegMask;
Reg::MaskReg x2PosMask;
Reg::MaskReg x2NegZeroMask;
Reg::MaskReg x2PosInfMask;
Reg::MaskReg x2NegInfMask;

Reg::CompareScalar<float, CMPMODE::EQ>(x1ZeroMask, x1Reg, 0.0f, mask); // x1 = ±0.0
Reg::And(
    (Reg::RegTensor<uint32_t>&)xSignReg, (Reg::RegTensor<uint32_t>&)x1Reg, floatSignMaskReg,
    mask); // 取x1符号位
Reg::Or(
    (Reg::RegTensor<uint32_t>&)xSignReg, (Reg::RegTensor<uint32_t>&)xSignReg, floatOneMaskReg,
    mask); // +/- 1
Reg::CompareScalar<float, CMPMODE::EQ>(x1NegMask, xSignReg, -1.0f, mask); // x1 is neg
Reg::MaskAnd(x1NegZeroMask, x1ZeroMask, x1NegMask, mask);  // x1 = -0.0
Reg::MaskXor(x1PosZeroMask, x1ZeroMask, x1NegZeroMask, mask);  // x1 = +0.0

Reg::CompareScalar<float, CMPMODE::EQ>(x2ZeroMask, x2Reg, 0.0f, mask); // x2 = ±0.0
Reg::And(
    (Reg::RegTensor<uint32_t>&)xSignReg, (Reg::RegTensor<uint32_t>&)x2Reg, floatSignMaskReg,
    mask); // 取x2符号位
Reg::Or(
    (Reg::RegTensor<uint32_t>&)xSignReg, (Reg::RegTensor<uint32_t>&)xSignReg, floatOneMaskReg,
    mask); // +/- 1
Reg::CompareScalar<float, CMPMODE::EQ>(x2NegMask, xSignReg, -1.0f, mask); // x2 is neg
Reg::MaskNot(x2PosMask, x2NegMask, mask); // x2 is pos
Reg::MaskAnd(x2NegZeroMask, x2ZeroMask, x2NegMask, mask);  // x2 = -0.0 
```

**要点**: 4 实参含 mask；`Or(xSignReg, xSignReg, floatOneMaskReg, mask)` 把符号位与全 1 尾数合并成 ±1.0f 的位模式；与 MaskAnd/MaskXor 组合做 ±0 与正负判定。

### 实例 13：floor::Compute1

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, LoadDist, MaskMergeMode, StoreDist, Truncate, UpdateMask
- **Or 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: bf16 floor 中两个 And 分别取原值符号段和截断值符号段，Or 合并成带正确符号的 floor 结果。

（行 91-106）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<bfloat16_t>(size);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / sizeof(half)));
    AscendC::Reg::Truncate<
        bfloat16_t, AscendC::RoundMode::CAST_FLOOR, AscendC::Reg::MaskMergeMode::ZEROING>(
        vreg1, vreg0, preg0);
    AscendC::Reg::Duplicate(vreg2, BF16_SIGN1, preg0);
    AscendC::Reg::Duplicate(vreg3, BF16_SIGN2, preg0);
    AscendC::Reg::And(vreg2, vreg2, (RegTensor<uint16_t>&)vreg0, preg0);
    AscendC::Reg::And(vreg3, vreg3, (RegTensor<uint16_t>&)vreg1, preg0);
    AscendC::Reg::Or(vreg3, vreg2, vreg3, preg0);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::StoreDist::DIST_NORM_B16>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / sizeof(half)), (RegTensor<bfloat16_t>&)vreg3,
        preg0);
}
```

**要点**: 4 实参但无 mask 字段（preg0 作第 4 参，pattern A4_M0）；BF16_SIGN1/BF16_SIGN2 为 16 位符号掩码；bf16 走 DIST_NORM_B16 存储，与 32 位取整算子的符号位合并同构。

### 实例 14：ceil::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, DataCopy, Duplicate, MaskMergeMode, RegTensor, RegTraitNumOne, Truncate, UpdateMask
- **Or 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEint16_t+uint16_t_MASKmask`（实参 4 个，含 mask/mode: mask，类型: uint16_t, int16_t）
- **语义（待补充）**: half 精度 ceil 的符号位保留分支，UINT16_SIGN + And 取原符号 + Or 合并到 Truncate 结果，16 位版本的符号位保留模式。

（行 68-82）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

    Reg::Truncate<T, RoundMode::CAST_CEIL, Reg::MaskMergeMode::ZEROING>(
        vregOutput, vregInput, mask);
    Reg::Duplicate(vregOutInt, UINT16_SIGN, mask);
    Reg::And(vregOutInt, vregOutInt, (Reg::RegTensor<uint16_t>&)vregInput, mask);
    Reg::Or(vregOutInt, vregOutInt, (Reg::RegTensor<uint16_t>&)vregOutput, mask);

    // OpCopyOut
    Reg::DataCopy(
        (__ubuf__ T*)(dstAddr + loopIdx * vlSize), (Reg::RegTensor<T>&)vregOutInt, mask);
}
```

**要点**: 与实例 8 同构但 16 位（uint16_t/int16_t）；体现 Or 在不同位宽取整算子中的复用；`<T, CAST_CEIL, ZEROING>` 模板，符号掩码改用 UINT16_SIGN。

### 实例 15：sort::ScatterBlockHist2Global

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, DataCopy, Duplicate, Interleave, MaskReg, PostLiteral, RegTensor
- **Or 调用次数**: 24
- **参数模式**: `T0_A4_M1_TYPEint64_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: int64_t）
- **语义（待补充）**: 基数排序中 Or 把 aggregateReadyMask（前缀就绪状态位）合并到 histogram 的 int64 数据高 bit，随数据一起 DataCopy 发布，标记该块已就绪。

**片段 1** (行 745-745):

```cpp
if constexpr (IsSameType<T3, uint32_t>::value) {
```

**片段 2** (行 776-800):

```cpp
Reg::Interleave(lookaheadOutOneB64A, lookaheadOutOneB64B, lookaheadOutOne, zeroVector);
Reg::Interleave(lookaheadOutTwoB64A, lookaheadOutTwoB64B, lookaheadOutTwo, zeroVector);
Reg::Interleave(lookaheadOutThreeB64A, lookaheadOutThreeB64B, lookaheadOutThree, zeroVector);
Reg::RegTensor<int64_t> lookaheadOutZeroMaskB64A, lookaheadOutZeroMaskB64B;
Reg::RegTensor<int64_t> lookaheadOutOneMaskB64A, lookaheadOutOneMaskB64B;
Reg::RegTensor<int64_t> lookaheadOutTwoMaskB64A, lookaheadOutTwoMaskB64B;
Reg::RegTensor<int64_t> lookaheadOutThreeMaskB64A, lookaheadOutThreeMaskB64B;
Reg::Or(lookaheadOutZeroMaskB64A, (Reg::RegTensor<int64_t>&)lookaheadOutZeroB64A,
             aggregateReadyMask, predicateDefault);
Reg::Or(lookaheadOutZeroMaskB64B, (Reg::RegTensor<int64_t>&)lookaheadOutZeroB64B,
             aggregateReadyMask, predicateDefault);
Reg::Or(lookaheadOutOneMaskB64A, (Reg::RegTensor<int64_t>&)lookaheadOutOneB64A,
             aggregateReadyMask, predicateDefault);
Reg::Or(lookaheadOutOneMaskB64B, (Reg::RegTensor<int64_t>&)lookaheadOutOneB64B,
             aggregateReadyMask, predicateDefault);
Reg::Or(lookaheadOutTwoMaskB64A, (Reg::RegTensor<int64_t>&)lookaheadOutTwoB64A,
             aggregateReadyMask, predicateDefault);
Reg::Or(lookaheadOutTwoMaskB64B, (Reg::RegTensor<int64_t>&)lookaheadOutTwoB64B,
             aggregateReadyMask, predicateDefault);
Reg::Or(lookaheadOutThreeMaskB64A, (Reg::RegTensor<int64_t>&)lookaheadOutThreeB64A,
             aggregateReadyMask, predicateDefault);
Reg::Or(lookaheadOutThreeMaskB64B, (Reg::RegTensor<int64_t>&)lookaheadOutThreeB64B,
             aggregateReadyMask, predicateDefault);
Reg::DataCopy<int64_t, Reg::PostLiteral::POST_MODE_UPDATE>(
    blockHistWithFlagPtr, lookaheadOutZeroMaskB64A, VF_LEN_B64, predicateDefault);
```

**要点**: 4 实参含 mask（predicateDefault）；Or 调用 24 次（多 lookahead 通道），是状态位拼接而非数值或；int64 类型，B64 存储，把就绪标志随数据写入全局。

### Or 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| tanh | Abs, Adds, And, Cast, CompareScalar | 符号位回注——And 取符号位 + Or 合并回中间结果，配合 satMask 饱和 | __aicore__ |
| scatter_nd_common | Add, Adds, Arange, Cast, CompareScalar | 索引越界检测——多次 CompareScalar 产生越界 mask，Or 累积成 invalidMask | __simd_vf__ |
| random_common | Adds, And, Cast, CreateMask, DataCopy | 随机数位拼接——And 取低位 + Or 合并高位，生成 bfloat16 尾数 | __aicore__ |
| random_common | Adds, And, CreateMask, DataCopy, Duplicate | 随机数位拼接——And/Or 组合把随机整数位拼成 float | __aicore__ |
| cast | And, CreateMask, DataCopy, DeInterleave, Duplicate | 4-bit 拼接——ShiftLefts 移位 + And 取低 4 位 + Or 合并高低 nibble | __VEC_SCOPE__ |
| adaptive_pool3d_common | Adds, Compare, CreateMask, DataCopy, Duplicate | NaN-aware maxpool——Compare NE 检测 NaN，Or 合入比较 mask，Select 更新最大值 | __VEC_SCOPE__ |
| glu | Adds, Cast, DataCopy, Div, Exp | 半精度符号位合并——Or 拼合两路 half 结果的符号位与尾数 | __aicore__ |
| ceil | And, DataCopy, Duplicate, MaskMergeMode, MaskReg | 符号位保留——And 取原值符号位 + Or 合并到 Truncate 取整结果 | __aicore__ |
| truncate_div | And, DataCopy, Duplicate, MaskMergeMode, MaskReg | 符号位保留——And 取符号位 + Or 合并到 CAST_TRUNC 结果 | __aicore__ |
| logical_or | Compares, DataCopy, Duplicate, LoadDist, MaskReg | 位或运算——float 当整型 Or，再 Compare !=0 得 bool | __aicore__ |
| index_put_with_sort_v2 | Add, AddrReg, Cast, CreateAddrReg, DataCopy | bool 累加——bool 用 Or 累积（逻辑或），非 bool 用 Add | __VEC_SCOPE__ |
| atan2 | And, CompareScalar, MaskAnd, MaskNot, MaskReg | 符号位归一——And 取符号位 + Or 与全 1 mask 合并成 ±1 判定正负 | __aicore__ |
| floor | And, DataCopy, Duplicate, LoadDist, MaskMergeMode | bf16 符号位合并——两个 And 取符号段 + Or 合并 | __aicore__ |
| ceil | And, DataCopy, Duplicate, MaskMergeMode | 16 位符号位保留——UINT16_SIGN + And + Or，half ceil 符号处理 | __VEC_SCOPE__ |
| sort | CreateMask, DataCopy, Duplicate, Interleave, MaskReg | 前缀就绪标志位拼接——Or 把 aggregateReadyMask 合并到 histogram 高 bit | __aicore__ |
