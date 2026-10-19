# DeInterleave

**页面ID:** atlasascendc_api_07_0336  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0336.html

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

将源操作数src0和src1中的元素解交织存入目的操作数dst0和dst1中。解交织排列方式如下图所示，其中每个方格代表一个元素：

![](images/atlasascendc_api_07_0336_img_001.png)

#### 函数原型

```
template <typename T>
__simd_callee__ inline void DeInterleave(MaskReg& dst0, MaskReg& dst1, MaskReg& src0, MaskReg& src1)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | MaskReg所支持的数据类型，决定了解交织的位宽大小，例如对于uint32_t类型，解交织时以4bit为一组。          Atlas 350 加速卡支持的数据类型为：b8/b16/b32 |

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
## 从 Ascend 950PR / arch35 算子源码提取的 DeInterleave 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **DeInterleave 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在 fp8 动态量化求 mxScale 阶段，对 bfloat16 指数寄存器就地 DeInterleave，把高低半部分重排为连续顺序，便于按行 DataCopyUnAlign 搬出 scale。

（行 530-550）

```cpp
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
Reg::DeInterleave(reversedShareExpRegTensor, tmp16RegTensor, reversedShareExpRegTensor, tmp16RegTensor);
auto scaleAddr = maxExpAddr;
for (uint16_t i = 0; i < rowsSingleLoop; i++) {
    Reg::DataCopyUnAlign(scaleAddr, reversedShareExpRegTensor, u1, dataLen);
    Reg::DataCopyUnAlignPost(scaleAddr, u1, 0);
}
```

**要点**: 1) DeInterleave 第 1/3 参数与第 2/4 参数相同，实现就地解交织；2) 与 Interleave/Pack 配合完成 fp8 指数位的提取与排列；3) 解交织后通过循环按行搬出，每行对应一个 scale。

### 实例 2：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, Interleave, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **DeInterleave 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEint16_t+uint16_t`（实参 4 个，类型: uint16_t, int16_t）
- **语义（待补充）**: 在动态量化指数处理中，对两个 uint16_t 指数寄存器就地 DeInterleave，配合 Pack 将指数字节紧凑排列到 mxScale 输出。

（行 641-659）

```cpp
AscendC::Reg::ShiftRights(expFP32Reg2, xFP32MaxReg2, FP32_SHR_NUM, preMaskScale);
// And获取尾数位
AscendC::Reg::And(manFP32Reg, xFP32MaxReg, infForFP32Reg, preMaskScale);
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
```

**要点**: 1) 显式模板参数 <uint16_t> 指定 16 位解交织位宽；2) 输入输出同寄存器实现就地解交织；3) 与 ShiftRights/And/CompareScalar/Select 配合完成指数规整。

### 实例 3：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, ClearSpr, Compare, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, GatherMask, GatherMaskMode, Interleave, LoadDist, MaskInterleave, MaskReg, PostLiteral, RegTensor, SubCarryOut, SubCarryOuts, UnalignReg, UpdateMask
- **DeInterleave 调用次数**: 1
- **参数模式**: `T1_A1_M0_TYPEint32_t`（实参 1 个，类型: int32_t）
- **语义（待补充）**: sparse_slice 中对 int64 索引按 int32 模板 DeInterleave 拆成低/高 32 位两路，使 b64 GatherMask 可由两次 b32 GatherMask 实现，再 Interleave 还原。

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

**要点**: 1) DeInterleave<int32_t> 用于把 64 位数据拆成两个 32 位寄存器；2) 典型链路 DeInterleave→GatherMask→Interleave 实现 b64 gather；3) 同步对 mask 做 MaskInterleave 保持数据与掩码对齐。

### 实例 4：clipped_swiglu::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, Div, Exp, LoadDist, MaskPattern, MaskReg, Maxs, Mins, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **DeInterleave 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: clipped_swiglu 将加载并提升到 float 的两路输入就地 DeInterleave，分离奇偶通道供 SwiGLU 的 sigmoid 与门控分支分别计算。

（行 373-398）

```cpp
    if constexpr (sizeof(T) == sizeof(half)) {
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddr,
                                                                                     srcIdxOffset);
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddr,
                                                                                     srcIdxOffset);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX1F, vregX1, mask);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX2F, vregX2, mask);
    } else {
        // float
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX1F, x1UbAddr, srcIdxOffset);
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX2F, x2UbAddr, srcIdxOffset);
    }
    AscendC::Reg::DeInterleave(vregX1DeF, vregX2DeF, vregX1F, vregX2F);
} else {
    if constexpr (sizeof(T) == sizeof(half)) {
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddr,
                                                                                     srcIdxOffset);
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddr,
                                                                                     srcIdxOffset);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX1DeF, vregX1, mask);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX2DeF, vregX2, mask);
    } else {
        // float
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX1DeF, x1UbAddr, srcIdxOffset);
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX2DeF, x2UbAddr, srcIdxOffset);
    }
```

**要点**: 1) 无模板参数，按 RegTensor 默认位宽解交织；2) 解交织后 vregX1DeF 走 sigmoid、vregX2DeF 走门控钳位；3) half 输入需先 Cast 到 float 再解交织。

### 实例 5：swiglu_mx_quant::VecScope_L446

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, Div, Exp, LoadDist, MaskPattern, MaskReg, Maxs, Mins, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **DeInterleave 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: swiglu_mx_quant 末轴计算中，对 float 化的两路激活就地 DeInterleave，再依次 Mins/Muls/Exp/Adds/Div 求 sigmoid、Mins/Maxs/Adds 做门控钳位、Mul 合并输出。

**片段 1** (行 466-493):

```cpp
for (uint16_t dim1vfLoopIdx = 0; dim1vfLoopIdx < dim1VfTimes; dim1vfLoopIdx++) {
    AscendC::Reg::AddrReg srcIdxOffset = AscendC::Reg::CreateAddrReg<T>(
        dim0vfLoopIdx, alignDim1In, dim1vfLoopIdx, 128);
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddr,
                                                                                 srcIdxOffset);
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddr,
                                                                                 srcIdxOffset);
    AscendC::Reg::Cast<float, T, CAST_ZERO>(vregX1F, vregX1, mask);
    AscendC::Reg::Cast<float, T, CAST_ZERO>(vregX2F, vregX2, mask);

    AscendC::Reg::DeInterleave(vregX1DeF, vregX2DeF, vregX1F, vregX2F);
    AscendC::Reg::Mins(minsReg, vregX1DeF, clampLimit, mask);
    AscendC::Reg::Muls(mulsReg, minsReg, negAplha, mask);
    AscendC::Reg::Exp(expReg, mulsReg, mask);
    AscendC::Reg::Adds(addsReg, expReg, scalarOne, mask);
    AscendC::Reg::Div(sigmoidReg, minsReg, addsReg, mask);

    AscendC::Reg::Mins(vregX2DeF, vregX2DeF, clampLimit, mask);
    AscendC::Reg::Maxs(vregX2DeF, vregX2DeF, negClampLimit, mask);
    AscendC::Reg::Adds(vregX2DeF, vregX2DeF, gluBias, mask);

    AscendC::Reg::Mul(outFReg, sigmoidReg, vregX2DeF, mask);

    AscendC::Reg::Cast<T, float, CAST_FP32_TO_FP16_BF16>(outTReg, outFReg, mask);
    AscendC::Reg::AddrReg outOffset = AscendC::Reg::CreateAddrReg<T>(dim0vfLoopIdx, alignDim1Out,
                                                                               dim1vfLoopIdx, 64);
    DataCopy<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(swigluUbAddr, outTReg, outOffset, mask);
}
```

**片段 2** (行 496-518):

```cpp
for (uint16_t aa = 0; aa < dim1TailTimes; aa++) {
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddr1,
                                                                                 srcIdxOffset1);
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddr1,
                                                                                 srcIdxOffset1);
    AscendC::Reg::Cast<float, T, CAST_ZERO>(vregX1F, vregX1, mask);
    AscendC::Reg::Cast<float, T, CAST_ZERO>(vregX2F, vregX2, mask);

    AscendC::Reg::DeInterleave(vregX1DeF, vregX2DeF, vregX1F, vregX2F);
    AscendC::Reg::Mins(minsReg, vregX1DeF, clampLimit, mask1);
    AscendC::Reg::Muls(mulsReg, minsReg, negAplha, mask1);
    AscendC::Reg::Exp(expReg, mulsReg, mask1);
    AscendC::Reg::Adds(addsReg, expReg, scalarOne, mask1);
    AscendC::Reg::Div(sigmoidReg, minsReg, addsReg, mask1);

    AscendC::Reg::Mins(vregX2DeF, vregX2DeF, clampLimit, mask1);
    AscendC::Reg::Maxs(vregX2DeF, vregX2DeF, negClampLimit, mask1);
    AscendC::Reg::Adds(vregX2DeF, vregX2DeF, gluBias, mask1);

    AscendC::Reg::Mul(outFReg, sigmoidReg, vregX2DeF, mask1);
    AscendC::Reg::Cast<T, float, CAST_FP32_TO_FP16_BF16>(outTReg, outFReg, mask1);
    DataCopy<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(swigluUbAddr1, outTReg, outOffset1, mask2);
}
```

**要点**: 1) DeInterleave 在 Cast 到 float 之后执行，保证计算精度；2) 主循环与 tail 循环共用同一解交织模式，仅 mask 不同；3) 输出经 Cast 回 half/bf16 后按 DIST_PACK_B32 存储。

### 实例 6：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Compare, CreateMask, DataCopy, Duplicate, LoadDist, LocalMemBar, MaskAnd, MaskPattern, MaskReg, MaskSel, MemType, ReduceSum, RegTensor, Select, StoreDist, UpdateMask
- **DeInterleave 调用次数**: 1
- **参数模式**: `T1_A4_M0_TYPEint32_t`（实参 4 个，类型: int32_t）
- **语义（待补充）**: sparse_slice 对 int64 索引按 int32 DeInterleave 拆成低/高半，分别与下界/上界 Compare+MaskSel 做范围判断，再 MaskAnd 合并。

（行 475-516）

```cpp
for (uint16_t loopIndex = 0; loopIndex < loopNum; loopIndex++) {
    // use b32 updatemask since there's twice copyin of int64 from ub to register
    pregIndicesB32 = Reg::UpdateMask<int32_t>(sreg0);
    Reg::DataCopy(vregInputOne,
                       (__ubuf__ int64_t*)(indicesUbAddr + dim * offsetPerLoop + loopIndex * vl));
    Reg::DataCopy(vregInputTwo,
                       (__ubuf__ int64_t*)(indicesUbAddr + dim * offsetPerLoop + loopIndex * vl + vlSize));

    // copyin b8 mask and unpack it to b32 mask
    Reg::DataCopy<int8_t, Reg::LoadDist::DIST_UNPACK4_B8>(
        vregInMask, (__ubuf__ int8_t*)(maskUbAddr + loopIndex * vl));

    // split lower part and higher part to compare
    Reg::DeInterleave<int32_t>(vregInputLowerHalf, vregInputHigherHalf,
                                    (Reg::RegTensor<int32_t>&)vregInputOne,
                                    (Reg::RegTensor<int32_t>&)vregInputTwo);
    // lower bound compare
    Reg::Compare<uint32_t, CMPMODE::GE>(flagLowerCmp,
                                             (Reg::RegTensor<uint32_t>&)vregInputLowerHalf,
                                             vregLowerBoundLowerHalf, pregB32All);
    Reg::Compare<int32_t, CMPMODE::GE>(flagHigherCmp, vregInputHigherHalf, vregLowerBoundHigherHalf,
                                            pregB32All);
    Reg::Compare<int32_t, CMPMODE::EQ>(flagHigherEqual, vregInputHigherHalf, vregLowerBoundHigherHalf,
                                            pregB32All);
    Reg::MaskSel(flagResultB32, flagLowerCmp, flagHigherCmp, flagHigherEqual);
    // upper bound compare
    Reg::Compare<uint32_t, CMPMODE::LT>(flagLowerCmp,
                                             (Reg::RegTensor<uint32_t>&)vregInputLowerHalf,
                                             vregUpperBoundLowerHalf, pregB32All);
    Reg::Compare<int32_t, CMPMODE::LT>(flagHigherCmp, vregInputHigherHalf, vregUpperBoundHigherHalf,
                                            pregB32All);
    Reg::Compare<int32_t, CMPMODE::EQ>(flagHigherEqual, vregInputHigherHalf, vregUpperBoundHigherHalf,
                                            pregB32All);
    Reg::MaskSel(flagResultB32Two, flagLowerCmp, flagHigherCmp, flagHigherEqual);

    Reg::MaskAnd(flagResultB32, flagResultB32, flagResultB32Two, pregIndicesB32);

    Reg::Select((Reg::RegTensor<int32_t>&)vregOutMask, (Reg::RegTensor<int32_t>&)vregInMask,
                     vregZeros, flagResultB32);
    Reg::DataCopy<int8_t, Reg::StoreDist::DIST_PACK4_B32>(
        (__ubuf__ int8_t*)(maskUbAddr + loopIndex * vl), vregOutMask, pregIndicesB32);
}
```

**要点**: 1) DeInterleave<int32_t> 拆 64 位索引以支持 32 位比较指令；2) 低位用 uint32_t 比较、高位用 int32_t 比较，再 EQ 判等组合；3) 结果经 Select 写回 b8 mask。

### 实例 7：arg_max_with_value::HardEvent::V_MTE3

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, MaskPattern, MaskReg, Mul, PostLiteral, ReduceMax, ReduceMin, RegTensor, RegTraitNumTwo, Select, UnalignReg, UpdateMask
- **DeInterleave 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: arg_max_with_value 在 ReduceMin/Mul 后对 indexMulResult 与 helpIndex 做 DeInterleave，把相对索引回溯为绝对索引 idx=idx+level_Y*A。

（行 256-272）

```cpp
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
```

**要点**: 1) DeInterleave 用于把乘积与基准索引重新对位求和；2) 配合 Add/Adds 完成索引回溯；3) 结果按 DataCopyUnAlign 搬出。

### 实例 8：top_k_v2::GetCumSum

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, Histograms, HistogramsBinType, HistogramsType, MaskAnd, MaskPack, MaskReg, MaskSel, PostLiteral, RegTensor, ShiftRights, UpdateMask
- **DeInterleave 调用次数**: 6
- **参数模式**: `T0_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: int32_t, uint32_t）
- **语义（待补充）**: top_k_v2 基数排序中，对 uint64 移位结果级联 DeInterleave（u64→u32→u16→u8）提取最低 8 位作为直方图 bin。

（行 75-99）

```cpp
Reg::CompareScalar<uint64_t, CMPMODE::EQ>(cmpValueMask, andValueZero, involvedDataMask, histMask);
// update mask for next step calc
Reg::MaskReg newHistMask;
Reg::MaskAnd(newHistMask, cmpValueMask, histMask, predicateDefaultB64);
// is first round
Reg::MaskReg finalMask, firstRoundMask;
Reg::CompareScalar<uint64_t, CMPMODE::EQ>(firstRoundMask, firstRoundVector, newRound, histMask);
// mask sel
Reg::MaskSel(finalMask, histMask, newHistMask, firstRoundMask);
// vshr
Reg::RegTensor<uint64_t> shiftVecOne;
Reg::ShiftRights<uint64_t, int16_t>(shiftVecOne, inputVectorOne, bitOffset, finalMask);
// get 256 8bit
// get u64 low bit
Reg::RegTensor<uint32_t> shiftVecU64LowBitOne, shiftVecU64HighBitOne;
Reg::DeInterleave(shiftVecU64LowBitOne, shiftVecU64HighBitOne, (Reg::RegTensor<uint32_t> &)shiftVecOne, (Reg::RegTensor<uint32_t> &)zeroVectorU64);
// get u32 low bit
Reg::RegTensor<uint16_t> shiftVecU16LowBitOne, shiftVecU16HighBitOne;
Reg::DeInterleave(shiftVecU16LowBitOne, shiftVecU16HighBitOne, (Reg::RegTensor<uint16_t> &)shiftVecU64LowBitOne, (Reg::RegTensor<uint16_t> &)zeroVectorU32);
// get u16 low bit
Reg::RegTensor<uint8_t> shiftVecU8LowBit, shiftVecU8HighBit;
Reg::DeInterleave(shiftVecU8LowBit, shiftVecU8HighBit, (Reg::RegTensor<uint8_t> &)shiftVecU16LowBitOne, (Reg::RegTensor<uint8_t> &)zeroVectorU16);
// copy u16 mask
Reg::MaskReg maskU8, maskU16, maskU32;
Reg::MaskPack(maskU32, finalMask);
```

**要点**: 1) 用 zero 向量做第二源实现取半解交织；2) 三级 DeInterleave 逐级窄化位宽；3) 配合 MaskPack 生成对应位宽的 mask。

### 实例 9：gather_elements::ComputeDim8Vf

- **来源类型**: `__aicore__`
- **共现 API**: Add, Arange, Copy, CreateMask, DataCopy, Div, Duplicate, MaskPattern, MaskReg, Mul, Muls, RegTensor, Sub, UpdateMask
- **DeInterleave 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: gather_elements 对 int64 索引寄存器就地 DeInterleave 拆成 uint32 高低半，必要时再拆到 uint16，以适配下游窄位宽 gather。

（行 766-776）

```cpp
if constexpr (std::is_same<INDEX_T, int64_t>::value) {
    Reg::RegTensor<uint32_t> RegUint32Index;
    Reg::DeInterleave(RegIndextmp, RegUint32Index, RegIndextmp, RegIndextmp);
}
if constexpr (std::is_same<OFFSET_T, uint16_t>::value) {
    Reg::RegTensor<uint16_t> RegUint16Index;
    Reg::DeInterleave(RegIndex, RegUint16Index, (Reg::RegTensor<uint16_t>&)RegIndextmp,
                           (Reg::RegTensor<uint16_t>&)RegIndextmp);
} else {
    Reg::Copy(RegIndex, RegIndextmp, maskReg);
}
```

**要点**: 1) 通过 if constexpr 按 INDEX_T/OFFSET_T 类型选择解交织位宽；2) 就地解交织（输入输出同寄存器）；3) 非 uint16 路径直接 Copy 跳过解交织。

### 实例 10：pool_3d_common::AvgPoolSingleChannelB16

- **来源类型**: `__aicore__`
- **共现 API**: Add, Cast, CreateAddrReg, CreateMask, DataCopy, Div, Duplicate, Interleave, MaskPattern, MaskReg, RegTensor, UnalignReg, UpdateMask
- **DeInterleave 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 3D 平均池化中，加载后用 Interleave 拆左右、fp32 累加除法再 Cast 回 b16，最后 DeInterleave 将左右半重排回连续结果寄存器搬出。

（行 1503-1547）

```cpp
{
    Reg::RegTensor<M> res;
    Reg::RegTensor<M> vd0;
    Reg::RegTensor<M> zero;
    Reg::RegTensor<float32_t> tmpRes1;
    Reg::RegTensor<float32_t> tmpRes2;
    Reg::RegTensor<float32_t> left;
    Reg::RegTensor<float32_t> right;
    Reg::RegTensor<float32_t> divisorReg;
    Reg::RegTensor<M> tmpLeft;
    Reg::RegTensor<M> tmpRight;

    Reg::Duplicate(tmpRes1, (float32_t)0);
    Reg::Duplicate(tmpRes2, (float32_t)0);
    Reg::Duplicate((Reg::RegTensor<float16_t>&)zero, (float16_t)0);
    uint32_t num = repeatElms;
    Reg::MaskReg p0 = Reg::UpdateMask<U>(num);
    Reg::UnalignReg u0;
    __local_mem__ M* curSrcAddr = srcLocalAddr;
    Reg::MaskReg defaultMask = Reg::CreateMask<M, Reg::MaskPattern::ALL>();

    Reg::Duplicate(res, (float32_t)0);

    for (uint16_t dIdx = 0; dIdx < kD; dIdx++) {
        for (uint16_t hIdx = 0; hIdx < kH; hIdx++) {
            for (uint16_t wIdx = 0; wIdx < kW; wIdx++) {
                auto aReg = Reg::CreateAddrReg<U>(dIdx, depStrideInUb, hIdx, rowStrideInub, wIdx, alignChannels);
                Reg::DataCopy(vd0, curSrcAddr, aReg);
                Reg::Interleave(tmpLeft, tmpRight, vd0, zero);
                Reg::Cast<float32_t, M, castTraitB16ToB32>(left, tmpLeft, defaultMask);
                Reg::Cast<float32_t, M, castTraitB16ToB32>(right, tmpRight, defaultMask);
                Reg::Add(tmpRes1, tmpRes1, left, defaultMask);
                Reg::Add(tmpRes2, tmpRes2, right, defaultMask);
            }
        }
    }
    Reg::Duplicate(divisorReg, divisor);
    Reg::Div(tmpRes1, tmpRes1, divisorReg, defaultMask);
    Reg::Div(tmpRes2, tmpRes2, divisorReg, defaultMask);
    Reg::Cast<M, float32_t, castTraitB32ToB16>(tmpLeft, tmpRes1, defaultMask);
    Reg::Cast<M, float32_t, castTraitB32ToB16>(tmpRight, tmpRes2, defaultMask);
    Reg::DeInterleave(res, zero, tmpLeft, tmpRight);
    Reg::DataCopy(dstLocalAddr, res, p0);
}
```

**要点**: 1) DeInterleave 与 Interleave 互为逆操作，用于左右半合并回连续数据；2) 第二源用 zero 寄存器占位；3) 先 Cast 到 fp32 求和再 Cast 回保证精度。

### 实例 11：avg_pool::AvgPoolSingleChannelB16

- **来源类型**: `__aicore__`
- **共现 API**: Add, Cast, CreateAddrReg, CreateMask, DataCopy, Div, Duplicate, Interleave, MaskPattern, MaskReg, RegTensor, UnalignReg, UpdateMask
- **DeInterleave 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 平均池化单通道实现中，DeInterleave 把 Cast 回 b16 的左右累加结果合并为连续输出寄存器，再 DataCopy 搬出。

（行 360-404）

```cpp
{
    Reg::RegTensor<M> res;
    Reg::RegTensor<M> vd0;
    Reg::RegTensor<M> zero;
    Reg::RegTensor<float32_t> tmpRes1;
    Reg::RegTensor<float32_t> tmpRes2;
    Reg::RegTensor<float32_t> left;
    Reg::RegTensor<float32_t> right;
    Reg::RegTensor<float32_t> divisorReg;
    Reg::RegTensor<M> tmpLeft;
    Reg::RegTensor<M> tmpRight;

    uint32_t num = repeatElms;
    Reg::MaskReg p0 = Reg::UpdateMask<U>(num);
    Reg::UnalignReg u0;
    __local_mem__ M* curSrcAddr = srcLocalAddr;
    Reg::MaskReg defaultMask = Reg::CreateMask<M, Reg::MaskPattern::ALL>();

    Reg::Duplicate((Reg::RegTensor<float16_t>&)zero, (float16_t)0);
    Reg::Duplicate(res, (float32_t)0);

    Reg::Duplicate(tmpRes1, (float32_t)0);
    Reg::Duplicate(tmpRes2, (float32_t)0);

    for (uint16_t hIdx = 0; hIdx < kH; hIdx++) {
        for (uint16_t wIdx = 0; wIdx < kW; wIdx++) {
            auto aReg = Reg::CreateAddrReg<U>(hIdx, rowStrideInUb, wIdx, alignChannels);
            Reg::DataCopy(vd0, curSrcAddr, aReg);
            Reg::Interleave(tmpLeft, tmpRight, vd0, zero);
            Reg::Cast<float32_t, M, castTraitB16ToB32>(left, tmpLeft, defaultMask);
            Reg::Cast<float32_t, M, castTraitB16ToB32>(right, tmpRight, defaultMask);
            Reg::Add(tmpRes1, tmpRes1, left, defaultMask);
            Reg::Add(tmpRes2, tmpRes2, right, defaultMask);
        }
    }

    Reg::Duplicate(divisorReg, divisor);
    Reg::Div(tmpRes1, tmpRes1, divisorReg, defaultMask);
    Reg::Div(tmpRes2, tmpRes2, divisorReg, defaultMask);
    Reg::Cast<M, float32_t, castTraitB32ToB16>(tmpLeft, tmpRes1, defaultMask);
    Reg::Cast<M, float32_t, castTraitB32ToB16>(tmpRight, tmpRes2, defaultMask);
    Reg::DeInterleave(res, zero, tmpLeft, tmpRight);
    Reg::DataCopy(dstLocalAddr, res, p0);
}
```

**要点**: 1) 与实例 10 同构，仅缺少 depth 维循环；2) Interleave 拆分→fp32 求和→DeInterleave 合并的标准模式；3) 第二源 zero 占位。

### 实例 12：sort::GetGlobalExcusiveSumB64

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, DataCopy, Duplicate, Histograms, HistogramsBinType, HistogramsType, MaskReg, PostLiteral, RegTensor, ShiftRights, UpdateMask
- **DeInterleave 调用次数**: 14
- **参数模式**: `T0_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: int32_t, uint32_t）
- **语义（待补充）**: sort 基数排序对 8 路 uint64 移位结果做两级 DeInterleave（u64→u32、u32→u16、u16→u8）提取 8 位 bin 送直方图统计。

（行 245-277）

```cpp
Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in4, inXPtr, VF_LEN_B64);
Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in5, inXPtr, VF_LEN_B64);
Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in6, inXPtr, VF_LEN_B64);
Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in7, inXPtr, VF_LEN_B64);
Reg::RegTensor<uint64_t> shift0, shift1, shift2, shift3, shift4, shift5, shift6, shift7;
Reg::ShiftRights<uint64_t, int16_t>(shift0, in0, bitOffset, maskB64);
Reg::ShiftRights<uint64_t, int16_t>(shift1, in1, bitOffset, maskB64);
Reg::ShiftRights<uint64_t, int16_t>(shift2, in2, bitOffset, maskB64);
Reg::ShiftRights<uint64_t, int16_t>(shift3, in3, bitOffset, maskB64);
Reg::ShiftRights<uint64_t, int16_t>(shift4, in4, bitOffset, maskB64);
Reg::ShiftRights<uint64_t, int16_t>(shift5, in5, bitOffset, maskB64);
Reg::ShiftRights<uint64_t, int16_t>(shift6, in6, bitOffset, maskB64);
Reg::ShiftRights<uint64_t, int16_t>(shift7, in7, bitOffset, maskB64);
Reg::RegTensor<uint32_t> deInter0, deInter1, deInter2, deInter3, deInter4, deInter5, deInter6,
    deInter7;
Reg::DeInterleave(deInter0, deInter1, (Reg::RegTensor<uint32_t>&)shift0,
                       (Reg::RegTensor<uint32_t>&)shift1);
Reg::DeInterleave(deInter2, deInter3, (Reg::RegTensor<uint32_t>&)shift2,
                       (Reg::RegTensor<uint32_t>&)shift3);
Reg::DeInterleave(deInter4, deInter5, (Reg::RegTensor<uint32_t>&)shift4,
                       (Reg::RegTensor<uint32_t>&)shift5);
Reg::DeInterleave(deInter6, deInter7, (Reg::RegTensor<uint32_t>&)shift6,
                       (Reg::RegTensor<uint32_t>&)shift7);
Reg::RegTensor<uint16_t> deInter0B16, deInter1B16, deInter2B16, deInter3B16;
Reg::DeInterleave(deInter0B16, deInter1B16, (Reg::RegTensor<uint16_t>&)deInter0,
                       (Reg::RegTensor<uint16_t>&)deInter2);
Reg::DeInterleave(deInter2B16, deInter3B16, (Reg::RegTensor<uint16_t>&)deInter4,
                       (Reg::RegTensor<uint16_t>&)deInter6);
Reg::RegTensor<uint8_t> deInter0B8, deInter1B8;
Reg::DeInterleave(deInter0B8, deInter1B8, (Reg::RegTensor<uint8_t>&)deInter0B16,
                       (Reg::RegTensor<uint8_t>&)deInter2B16);
Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputB8UbPtr, deInter0B8, VF_LEN_B8,
                                                                     histMask);
```

**要点**: 1) 单函数内 14 次 DeInterleave 调用，体现批量解交织模式；2) 两两配对逐级窄化位宽；3) 最终 b8 结果送 Histograms 做频率/累加统计。

### 实例 13：kth_value::Reg::HistogramsType

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, Select, ShiftRights, UpdateMask
- **DeInterleave 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEint8_t+uint8_t`（实参 4 个，类型: uint8_t, int8_t）
- **语义（待补充）**: kth_value 基数选择中对移位后的两路 uint16 就地 DeInterleave<uint8_t> 取低字节，同时对 flag 做同位解交织，保证数据与有效标志对齐送直方图。

（行 485-504）

```cpp
for (uint16_t i = 0; i < repeats; ++i) {
    Reg::MaskReg histMask = Reg::UpdateMask<uint8_t>(remain);
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(input0, keyPtr, VF_LEN_B16);
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(input1, keyPtr, VF_LEN_B16);
    Reg::And(masked0, input0, prefixMaskReg, maskB16);
    Reg::And(masked1, input1, prefixMaskReg, maskB16);
    Reg::MaskReg selected0, selected1;
    Reg::CompareScalar<uint16_t, CMPMODE::EQ>(selected0, masked0, prefixKey, maskB16);
    Reg::CompareScalar<uint16_t, CMPMODE::EQ>(selected1, masked1, prefixKey, maskB16);
    Reg::Select(flag0, one, zero, selected0);
    Reg::Select(flag1, one, zero, selected1);
    Reg::ShiftRights<uint16_t, int16_t>(shifted0, input0, shift, maskB16);
    Reg::ShiftRights<uint16_t, int16_t>(shifted1, input1, shift, maskB16);
    Reg::RegTensor<uint8_t> bytes, highBytes, flagBytes, highFlags;
    Reg::DeInterleave(bytes, highBytes, (Reg::RegTensor<uint8_t>&)shifted0,
                           (Reg::RegTensor<uint8_t>&)shifted1);
    Reg::DeInterleave(flagBytes, highFlags, (Reg::RegTensor<uint8_t>&)flag0,
                           (Reg::RegTensor<uint8_t>&)flag1);
    AddSelectedByteHistogram(hist0, hist1, bytes, flagBytes, histMask);
}
```

**要点**: 1) DeInterleave<uint8_t> 显式指定 8 位解交织；2) 数据与 mask flag 各做一次 DeInterleave 保持对位；3) 配合 ShiftRights 取当前基数位。

### 实例 14：cast::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CreateMask, DataCopy, Duplicate, MaskMergeMode, MaskReg, Or, PostLiteral, RegTensor, ShiftLefts, UpdateMask
- **DeInterleave 调用次数**: 1
- **参数模式**: `T1_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: cast 实现中对两路加载结果 DeInterleave<MMT>，再用 And 取低 4 位、ShiftLefts 移高 4 位、Or 合并，完成 4 位打包类型转换。

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

**要点**: 1) 显式模板参数 MMT 控制解交织位宽；2) DeInterleave→And→ShiftLefts→Or 是 nibble 打包的标准链路；3) 与 DataCopy 的 ldDist/stDist 配合处理非对齐搬运。

### 实例 15：glu::ComputeSigmoidAndMulWithDeInterleave

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, DataCopy, Duplicate, MaskMergeMode, MaskPattern, MaskReg, RegTensor, UpdateMask
- **DeInterleave 调用次数**: 1
- **参数模式**: `T1_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: glu 将连续加载的两路输入就地 DeInterleave<T> 拆成门控与值两路，送 ComputeSigmoidAndMulCore 完成 sigmoid×value。

（行 192-200）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    preg0 = AscendC::Reg::UpdateMask<T>(size);
    AscendC::Reg::DataCopy(vregInput1, (__ubuf__ T*)(xLocalPtr + loopIdx * 2 * vlSize));
    AscendC::Reg::DataCopy(vregInput2, (__ubuf__ T*)(xLocalPtr + loopIdx * 2 * vlSize + vlSize));

    Reg::DeInterleave<T>(vreg1, vreg2, vregInput1, vregInput2);

    ComputeSigmoidAndMulCore<T>(vreg1, vreg2, vregOutput, outLocalPtr, loopIdx, vlSize, preg0, maskAll8, vreg0);
}
```

**要点**: 1) DeInterleave<T> 显式按数据类型 T 解交织；2) 就地拆分后两路对应 GLU 的 gate 与 input；3) 与 UpdateMask/DataCopy 配套按 vl 循环处理。

### DeInterleave 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 就地解交织指数寄存器并按行搬出 mxScale（fp8 量化） | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 显式 <uint16_t> 就地解交织指数位 + Pack 紧凑输出 | __VEC_SCOPE__ |
| sparse_slice | AR, ClearSpr, Compare, CreateMask, DataCopy | DeInterleave<int32_t> 拆 64 位索引配合 GatherMask/Interleave 实现 b64 gather | __VEC_SCOPE__ |
| clipped_swiglu | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | half→float 提升 + 就地 DeInterleave 分离 SwiGLU 奇偶通道 | __VEC_SCOPE__ |
| swiglu_mx_quant | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | Cast 到 float 后就地 DeInterleave，配合 sigmoid/钳位/Mul 完成末轴 SwiGLU | __VEC_SCOPE__ |
| sparse_slice | Add, Compare, CreateMask, DataCopy | DeInterleave<int32_t> 拆 64 位索引做上下界范围判断（MaskSel+MaskAnd） | __VEC_SCOPE__ |
| arg_max_with_value | Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre | DeInterleave 重对位乘积与基准索引，回溯绝对索引 | __VEC_SCOPE__ |
| top_k_v2 | And, CompareScalar, CreateMask, DataCopy | 与 zero 配对的三级 DeInterleave（u64→u32→u16→u8）取基数 bin | __VEC_SCOPE__ |
| gather_elements | Add, Arange, Copy, CreateMask, DataCopy | 按 INDEX_T/OFFSET_T 类型选择位宽就地 DeInterleave 收窄索引 | __aicore__ |
| pool_3d_common | Add, Cast, CreateAddrReg, CreateMask, DataCopy | Interleave 拆分→fp32 池化→DeInterleave 合并回连续输出 | __aicore__ |
| avg_pool | Add, Cast, CreateAddrReg, CreateMask, DataCopy | Interleave 拆分→fp32 池化→DeInterleave 合并（无 depth 维） | __aicore__ |
| sort | CreateMask, DataCopy, Duplicate, Histograms | 8 路两级 DeInterleave（u64→u8）批量取基数 bin 送直方图 | __aicore__ |
| kth_value | And, CompareScalar, CreateMask, DataCopy | <uint8_t> 数据与 flag 双路就地 DeInterleave 取字节送直方图 | __VEC_SCOPE__ |
| cast | And, CreateMask, DataCopy, Duplicate | DeInterleave<MMT> + And/ShiftLefts/Or 完成 4 位 nibble 打包转换 | __VEC_SCOPE__ |
| glu | CreateMask, DataCopy, Duplicate, MaskMergeMode | <T> 就地 DeInterleave 拆 gate/value 两路完成 GLU | __aicore__ |


