# ClearSpr

**页面ID:** atlasascendc_api_07_00234  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00234.html

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

对指定的特殊寄存器进行清零。

#### 函数原型

```
template <SpecialPurposeReg spr>
__simd_callee__ inline void ClearSpr()
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| spr | 特殊寄存器，类型为SpecialPurposeReg枚举类。 |

#### 约束说明

无。

#### 调用示例

如下示例中Gather Reg矢量计算API会存储有效元素的总字节数到AR寄存器中，在宏函数内for循环开始前通过ClearSpr对AR寄存器进行清零。

```
template<typename T, typename U>
__simd_vf__ inline void VFDemo(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ U* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0, dstReg;
    AscendC::Reg::RegTensor<U> srcReg1;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::LoadAlign(srcReg1, src1Addr);
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::Gather(dstReg, srcReg0, srcReg1);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 ClearSpr 实例

### 实例 1：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, Compare, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, GatherMask, GatherMaskMode, Interleave, LoadDist, MaskInterleave, MaskReg, PostLiteral, RegTensor, SubCarryOut, SubCarryOuts, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在按维度循环处理 sparse_slice 稀疏切片前清零 AR 寄存器，为后续 DataCopyUnAlign(PostMode) 累加各维度输出字节数做准备。

（行 693-750）

```cpp
for (uint16_t dim = 0; dim < rankNum; dim++) {
    Reg::ClearSpr<SpecialPurposeReg::AR>();
    uint32_t sreg0 = count;
    __ubuf__ int64_t* yIndicesCurDimAddr = (__ubuf__ int64_t*)(yIndicesUbAddr) + dim * count;
    Reg::DataCopy<uint32_t, Reg::LoadDist::DIST_BRC_B32>(
        vregLowerBoundLowerHalf, (__ubuf__ uint32_t*)(sliceStartAddr) + dim * DIGIT_TWO);
    Reg::DataCopy<int32_t, Reg::LoadDist::DIST_BRC_B32>(
        vregLowerBoundHigherHalf, (__ubuf__ int32_t*)(sliceStartAddr) + dim * DIGIT_TWO + 1);
    carryOut = Reg::CreateMask<uint8_t>();
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
    AscendC::Reg::DataCopyUnAlignPost(yIndicesCurDimAddr, ureg0);
}
```

**要点**:
1. ClearSpr<AR>() 必须在 DataCopyUnAlignPost 之前调用，AR 记录非对齐拷贝的实际字节数
2. 每个 dim 循环开头清零一次 AR，保证各维度输出长度独立统计
3. 与 GatherMask 配合实现按 mask 压缩后再非对齐写出

### 实例 2：broadcast_gradient_args::CalcReduceAxes

- **来源类型**: `__aicore__`
- **共现 API**: AR, Adds, Arange, Cast, CompareScalar, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, GatherMask, GatherMaskMode, GetSpr, MaskPattern, MaskReg, Pack, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 broadcast_gradient_args 计算缩减轴索引前清零 AR 寄存器，为循环内 DataCopyUnAlign(PostMode) 累加写出元素数做准备。

（行 77-114）

```cpp
__VEC_SCOPE__
{
    uint32_t srg0 = xLen;
    Reg::RegTensor<int32_t> init_index_reg, calc_index_reg, x_int32_reg, dst_reg;
    Reg::RegTensor<T> in_reg;
    Reg::UnalignReg ureg;
    Reg::MaskReg maskCompare;
    Reg::MaskReg maskCalc;
    Reg::MaskReg maskAll = Reg::CreateMask<int32_t, Reg::MaskPattern::ALL>();
    Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();
    Reg::Arange(init_index_reg, 0);
    if constexpr (IsSameType<T, int64_t>::value) {
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
    } else {
        for (uint16_t i = 0; i < vLoopT; i++) {
            maskCalc = Reg::UpdateMask<int32_t>(srg0);
            Reg::Adds(calc_index_reg, init_index_reg, i * vlInput, maskAll);
            Reg::DataCopy(in_reg, x + i * vlInput);
            Reg::CompareScalar<int32_t, CMPMODE::EQ>(maskCompare, in_reg, 1, maskCalc);
            Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(dst_reg, calc_index_reg,
                                                                               maskCompare);
            Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(y, dst_reg, ureg);
        }
    }
    Reg::DataCopyUnAlignPost(y, ureg);
}
```

**要点**:
1. ClearSpr<AR>() 紧跟 CreateMask(ALL) 之后、Arange 之前调用
2. AR 配合 DataCopyUnAlignPost 在循环结束后一次性回写实际写出长度
3. 与 GetSpr 配对时可在循环后读取 AR 获取有效元素数

### 实例 3：embedding_dense_grad::UniqueGetElm

- **来源类型**: `__aicore__`
- **共现 API**: AR, Arange, Compare, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: embedding_dense_grad 去重获取唯一元素前清零 AR 寄存器，为循环内 DataCopyUnAlign(PostMode) 累加去重后索引写出量做准备。

（行 120-157）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<int32_t> orderReg;
    AscendC::Reg::RegTensor<int32_t> selReg;
    AscendC::Reg::RegTensor<U> indicesReg;
    AscendC::Reg::RegTensor<U> indicesShiftOneReg;

    AscendC::Reg::MaskReg cmpMask;
    AscendC::Reg::MaskReg maskRegUpdate;
    AscendC::Reg::UnalignReg u0;
    Reg::UnalignReg ureg;
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();

    for (uint16_t i = 0; i < loopCnt; ++i) {
        scalar = i * vfIndicesNum_;
        auto sortedIndicesAddrUpdate = sortedIndicesAddr + shiftOffset_ + i * vfIndicesNum_;
        AscendC::Reg::Arange(orderReg, scalar);
        maskRegUpdate = AscendC::Reg::UpdateMask<U>(counter);
        AscendC::Reg::DataCopy(indicesReg, sortedIndicesAddrUpdate);
        AscendC::Reg::DataCopyUnAlignPre(u0, sortedIndicesAddrUpdate - 1);
        AscendC::Reg::DataCopyUnAlign<U>(indicesShiftOneReg, u0, sortedIndicesAddrUpdate - 1);
        AscendC::Reg::Compare<U, CMPMODE::NE>(cmpMask, indicesReg, indicesShiftOneReg, maskRegUpdate);
        if constexpr (IsSameType<U, int64_t>::value) {
            AscendC::Reg::MaskReg maskHalf;
            AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(maskHalf, cmpMask);
            // vSQZ
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(
                selReg, orderReg, maskHalf);
        } else {
            // vSQZ
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(
                selReg, orderReg, cmpMask);
        }
        AscendC::Reg::DataCopyUnAlign<int32_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
            noDupResAddr, selReg, ureg);
        AscendC::Reg::DataCopyUnAlignPost(noDupResAddr, ureg);
    }
}
```

**要点**:
1. ClearSpr<AR>() 在 __VEC_SCOPE__ 入口、循环前调用
2. AR 记录 DataCopyUnAlign 累积写出字节数，供 DataCopyUnAlignPost 收尾
3. 配合 Compare(NE) 找相邻不同元素、GatherMask 压缩实现去重

### 实例 4：unsorted_segment_sum::UniqueGetElm

- **来源类型**: `__aicore__`
- **共现 API**: AR, Arange, Compare, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: unsorted_segment_sum 去重获取段索引前清零 AR 寄存器，为循环内非对齐拷贝累加写出量做准备。

（行 397-434）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<int32_t> orderReg;
    AscendC::Reg::RegTensor<int32_t> selReg;
    AscendC::Reg::RegTensor<Index> indicesReg;
    AscendC::Reg::RegTensor<Index> indicesShiftOneReg;

    AscendC::Reg::MaskReg cmpMask;
    AscendC::Reg::MaskReg maskRegUpdate;
    AscendC::Reg::UnalignReg u0;
    Reg::UnalignReg ureg;
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();

    for (uint16_t i = 0; i < loopCnt; ++i) {
        scalar = i * vfIndicesNum;
        auto sortedIndicesAddrUpdate = sortedIndicesAddr + shiftOffset + i * vfIndicesNum;
        AscendC::Reg::Arange(orderReg, scalar);
        maskRegUpdate = AscendC::Reg::UpdateMask<Index>(counter);
        AscendC::Reg::DataCopy(indicesReg, sortedIndicesAddrUpdate);
        AscendC::Reg::DataCopyUnAlignPre(u0, sortedIndicesAddrUpdate - 1);
        AscendC::Reg::DataCopyUnAlign<Index>(indicesShiftOneReg, u0, sortedIndicesAddrUpdate - 1);
        AscendC::Reg::Compare<Index, CMPMODE::NE>(cmpMask, indicesReg, indicesShiftOneReg, maskRegUpdate);
        if constexpr (IsSameType<Index, int64_t>::value) {
            AscendC::Reg::MaskReg maskHalf;
            AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(maskHalf, cmpMask);
            // vSQZ
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg, orderReg,
                                                                                                 maskHalf);
        } else {
            // vSQZ
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg, orderReg,
                                                                                                 cmpMask);
        }
        AscendC::Reg::DataCopyUnAlign<int32_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(noDupResAddr,
                                                                                                      selReg, ureg);
        AscendC::Reg::DataCopyUnAlignPost(noDupResAddr, ureg);
    }
}
```

**要点**:
1. ClearSpr<AR>() 在循环前调用，保证 AR 从 0 开始累加
2. 与 DataCopyUnAlign(PostMode) + DataCopyUnAlignPost 配对统计实际写出长度
3. int64 场景需 MaskPack(LOWEST) 将 mask 折半后再 GatherMask

### 实例 5：non_zero::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, Adds, Arange, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, GatherMask, GatherMaskMode, HighLowPart, MaskPattern, MaskReg, MaskUnPack, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: non_zero 求非零元素索引前清零 AR 寄存器，为循环内多次 DataCopyUnAlign(PostMode) 累加写出索引数做准备。

（行 1001-1047）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<T1> xSrcReg;
    uint32_t sreg = processNum;
    AscendC::Reg::ClearSpr<SpecialPurposeReg::AR>();
    AscendC::Reg::MaskReg preg, preg1, cmpReg, pregLower, pregHigher, maskReg1, maskReg2, maskReg3, maskReg4;
    AscendC::Reg::UnalignReg ureg0;
    RegTensor<int32_t> vsqzReg;
    RegTensor<int32_t> idsReg;
    preg1 = AscendC::Reg::CreateMask<int32_t, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::Arange(idsReg, startIdx);
    for (uint16_t i = 0; i < repeatTimes; i++) {
        preg = AscendC::Reg::UpdateMask<T1>(sreg);
        DataCopy(xSrcReg, xUbPtr + i * repeatElmB8);
        CompareScalar<T1, CMPMODE::NE>(cmpReg, xSrcReg, (T1)0, preg);

        AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::LOWEST>(pregLower, cmpReg);
        AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::LOWEST>(maskReg1, pregLower);
        AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::HIGHEST>(maskReg2, pregLower);

        AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::HIGHEST>(pregHigher, cmpReg);
        AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::LOWEST>(maskReg3, pregHigher);
        AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::HIGHEST>(maskReg4, pregHigher);

        AscendC::Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(vsqzReg, idsReg, maskReg1);
        AscendC::Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(yUbPtr, vsqzReg,
                                                                                             ureg0);

        AscendC::Reg::Adds(idsReg, idsReg, offsetNum64, preg1);
        AscendC::Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(vsqzReg, idsReg, maskReg2);
        AscendC::Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(yUbPtr, vsqzReg,
                                                                                             ureg0);

        AscendC::Reg::Adds(idsReg, idsReg, offsetNum64, preg1);
        AscendC::Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(vsqzReg, idsReg, maskReg3);
        AscendC::Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(yUbPtr, vsqzReg,
                                                                                             ureg0);

        AscendC::Reg::Adds(idsReg, idsReg, offsetNum64, preg1);
        AscendC::Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(vsqzReg, idsReg, maskReg4);
        AscendC::Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(yUbPtr, vsqzReg,
                                                                                             ureg0);

        AscendC::Reg::Adds(idsReg, idsReg, offsetNum, preg1);
    }
    AscendC::Reg::DataCopyUnAlignPost(yUbPtr, ureg0);
}
```

**要点**:
1. ClearSpr<AR>() 在 CreateMask(ALL)/Arange 之前调用
2. AR 跨多次 DataCopyUnAlign 累加（每轮 4 次写出），最终由 DataCopyUnAlignPost 收尾
3. 大 mask 场景用 MaskUnPack 将掩码拆成 4 份分别 GatherMask

### 实例 6：segment_sum::platform::GetUbBlockSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, Arange, Compare, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: segment_sum 求段边界前清零 AR 寄存器，为循环内 DataCopyUnAlign(PostMode) 累加写出段位置数做准备。

（行 105-142）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<int32_t> orderReg;
    AscendC::Reg::RegTensor<int32_t> selReg;
    AscendC::Reg::RegTensor<Index> indicesReg;
    AscendC::Reg::RegTensor<Index> indicesShiftOneReg;
    AscendC::Reg::MaskReg cmpMask;
    AscendC::Reg::MaskReg maskRegUpdate;
    AscendC::Reg::UnalignReg u0;
    Reg::UnalignReg ureg;
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();
    int32_t vciStart = 0;
    for (uint16_t i = 0; i < loopCnt; ++i) {
        vciStart = i * vl;
        auto segIdsOffset = segmentIdsAddr + offset + i * vl;
        AscendC::Reg::Arange(orderReg, vciStart);
        maskRegUpdate = AscendC::Reg::UpdateMask<Index>(maskCount);
        AscendC::Reg::DataCopy(indicesReg, segIdsOffset);
        AscendC::Reg::DataCopyUnAlignPre(u0, segIdsOffset - 1);
        AscendC::Reg::DataCopyUnAlign<Index>(indicesShiftOneReg, u0, segIdsOffset - 1);
        AscendC::Reg::Compare<Index, CMPMODE::NE>(cmpMask, indicesReg, indicesShiftOneReg, maskRegUpdate);

        if constexpr (IsSameType<Index, int64_t>::value) {
            AscendC::Reg::MaskReg maskHalf;
            AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(maskHalf, cmpMask);
            // vSQZ
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg, orderReg,
                                                                                                 maskHalf);
        } else {
            // vSQZ
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg, orderReg,
                                                                                                 cmpMask);
        }
        AscendC::Reg::DataCopyUnAlign<int32_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(segIdsPosAddr,
                                                                                                      selReg, ureg);
    }
    AscendC::Reg::DataCopyUnAlignPost(segIdsPosAddr, ureg);
}
```

**要点**:
1. ClearSpr<AR>() 在循环前调用，vciStart 跟踪每轮起始索引
2. AR 累积非对齐拷贝写出量，循环结束后 DataCopyUnAlignPost 收尾
3. int64 索引需 MaskPack(LOWEST) 折半 mask 后再 GatherMask

### 实例 7：scatter_nd::ComputeUniqueIdNumVecImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: AR, Arange, Compare, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: scatter_nd 计算唯一 ID 数前清零 AR 寄存器，为循环内 DataCopyUnAlign(PostMode) 累加写出唯一索引数做准备。

（行 450-485）

```cpp
{
    AscendC::Reg::RegTensor<int32_t> orderReg;
    AscendC::Reg::RegTensor<U> sortedIdxReg;
    AscendC::Reg::RegTensor<U> sortedIdxShiftOneReg;
    AscendC::Reg::RegTensor<int32_t> selReg0;
    AscendC::Reg::MaskReg cmpMask;
    AscendC::Reg::MaskReg maskRegUpdate;
    AscendC::Reg::UnalignReg u0;
    AscendC::Reg::UnalignReg u1;
    AscendC::Reg::UnalignReg ureg0;
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();

    for (uint16_t i = 0; i < loopCnt; ++i) {
        AscendC::Reg::Arange(orderReg, i * vfLen);
        maskRegUpdate = AscendC::Reg::UpdateMask<U>(counter);
        auto startAddr = sortedIndicesAddr + i * vfLen;
        DataCopy(sortedIdxReg, startAddr);
        AscendC::Reg::DataCopyUnAlignPre(u1, startAddr - 1);
        AscendC::Reg::DataCopyUnAlign<U>(sortedIdxShiftOneReg, u1, startAddr - 1);

        AscendC::Reg::Compare<U, CMPMODE::NE>(cmpMask, sortedIdxReg, sortedIdxShiftOneReg, maskRegUpdate);
        if constexpr (std::is_same<int64_t, U>::value) {
            AscendC::Reg::MaskReg maskHalf;
            AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(maskHalf, cmpMask);
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg0, orderReg,
                                                                                                 maskHalf);
        } else {
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg0, orderReg,
                                                                                                 cmpMask);
        }

        AscendC::Reg::DataCopyUnAlign<int32_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
            uniqueIdCountsAddr, selReg0, ureg0);
    }
    AscendC::Reg::DataCopyUnAlignPost(uniqueIdCountsAddr, ureg0);
}
```

**要点**:
1. ClearSpr<AR>() 在 __simd_vf__ 函数体开头、循环前调用
2. AR 配合 DataCopyUnAlignPost 统计实际写出的唯一 ID 个数
3. 相邻比较(Compare NE) + GatherMask 压缩实现去重

### 实例 8：scatter_add::ComputeUniqueIdNumVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AR, Arange, Compare, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: scatter_add 计算唯一 ID 数前清零 AR 寄存器，为循环内非对齐拷贝累加写出量做准备。

（行 294-328）

```cpp
{
    AscendC::Reg::RegTensor<int32_t> orderReg;
    AscendC::Reg::RegTensor<U> sortedIdxReg;
    AscendC::Reg::RegTensor<U> sortedIdxShiftOneReg;
    AscendC::Reg::RegTensor<int32_t> selReg0;
    AscendC::Reg::MaskReg cmpMask;
    AscendC::Reg::MaskReg maskRegUpdate;
    AscendC::Reg::UnalignReg u0;
    AscendC::Reg::UnalignReg u1;
    AscendC::Reg::UnalignReg ureg0;
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();
    for (uint16_t i = 0; i < loopCnt; ++i) {
        AscendC::Reg::Arange(orderReg, i * vfLen);
        maskRegUpdate = AscendC::Reg::UpdateMask<U>(counter);
        auto startAddr = sortedIndicesAddr + i * vfLen;
        DataCopy(sortedIdxReg, startAddr);
        AscendC::Reg::DataCopyUnAlignPre(u1, startAddr - 1);
        AscendC::Reg::DataCopyUnAlign<U>(sortedIdxShiftOneReg, u1, startAddr - 1);

        AscendC::Reg::Compare<U, CMPMODE::NE>(cmpMask, sortedIdxReg, sortedIdxShiftOneReg, maskRegUpdate);
        if constexpr (std::is_same<int64_t, U>::value) {
            AscendC::Reg::MaskReg maskHalf;
            AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(maskHalf, cmpMask);
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg0, orderReg,
                                                                                                 maskHalf);
        } else {
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg0, orderReg,
                                                                                                 cmpMask);
        }
        AscendC::Reg::DataCopyUnAlign<int32_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
            uniqueIdCountsAddr, selReg0, ureg0);
    }
    AscendC::Reg::DataCopyUnAlignPost(uniqueIdCountsAddr, ureg0);
}
```

**要点**:
1. ClearSpr<AR>() 在循环前调用，AR 从 0 累加
2. 与 DataCopyUnAlign(PostMode) + DataCopyUnAlignPost 配对统计写出长度
3. int64 索引需 MaskPack(LOWEST) 折半 mask 后再 GatherMask

### 实例 9：scatter_nd_add::ComputeUniqueIdNumDeterVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AR, Arange, Compare, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: scatter_nd_add 确定性计算唯一 ID 数前清零 AR 寄存器，为循环内非对齐拷贝累加写出量做准备。

（行 74-106）

```cpp
{
    AscendC::Reg::RegTensor<int32_t> orderReg;
    AscendC::Reg::RegTensor<U> sortedIdxReg;
    AscendC::Reg::RegTensor<U> sortedIdxShiftOneReg;
    AscendC::Reg::RegTensor<int32_t> selReg;
    AscendC::Reg::MaskReg cmpMask;
    AscendC::Reg::MaskReg maskReg;
    AscendC::Reg::UnalignReg u0;
    AscendC::Reg::UnalignReg uOut;
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();

    for (uint16_t i = 0; i < loopCnt; ++i) {
        AscendC::Reg::Arange(orderReg, i * vfLen);
        maskReg = AscendC::Reg::UpdateMask<U>(counter);
        auto startAddr = indicesAddr + i * vfLen;
        DataCopy(sortedIdxReg, startAddr);
        AscendC::Reg::DataCopyUnAlignPre(u0, startAddr - 1);
        AscendC::Reg::DataCopyUnAlign<U>(sortedIdxShiftOneReg, u0, startAddr - 1);
        AscendC::Reg::Compare<U, CMPMODE::NE>(cmpMask, sortedIdxReg, sortedIdxShiftOneReg, maskReg);
        if constexpr (std::is_same<int64_t, U>::value) {
            AscendC::Reg::MaskReg maskHalf;
            AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(maskHalf, cmpMask);
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg, orderReg,
                                                                                                 maskHalf);
        } else {
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg, orderReg,
                                                                                                 cmpMask);
        }
        AscendC::Reg::DataCopyUnAlign<int32_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
            uniqueIdCountsAddr, selReg, uOut);
    }
    AscendC::Reg::DataCopyUnAlignPost(uniqueIdCountsAddr, uOut);
}
```

**要点**:
1. ClearSpr<AR>() 在循环前调用
2. AR 配合 DataCopyUnAlignPost 统计写出长度
3. int64 索引需 MaskPack(LOWEST) 折半 mask 后再 GatherMask

### 实例 10：scatter_nd_update::ComputeUniqueIdNumVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AR, Arange, Compare, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: scatter_nd_update 计算唯一 ID 数前清零 AR 寄存器，为循环内非对齐拷贝累加写出量做准备。

（行 59-91）

```cpp
{
    AscendC::Reg::RegTensor<int32_t> orderReg;
    AscendC::Reg::RegTensor<OFFSET_T> sortedIdxReg;
    AscendC::Reg::RegTensor<OFFSET_T> sortedIdxShiftOneReg;
    AscendC::Reg::RegTensor<int32_t> selReg;
    AscendC::Reg::MaskReg cmpMask;
    AscendC::Reg::MaskReg maskReg;
    AscendC::Reg::UnalignReg u0;
    AscendC::Reg::UnalignReg uOut;
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();

    for (uint16_t i = 0; i < loopCnt; ++i) {
        AscendC::Reg::Arange(orderReg, i * vfLen);
        maskReg = AscendC::Reg::UpdateMask<OFFSET_T>(counter);
        auto startAddr = indicesAddr + i * vfLen;
        DataCopy(sortedIdxReg, startAddr);
        AscendC::Reg::DataCopyUnAlignPre(u0, startAddr - 1);
        AscendC::Reg::DataCopyUnAlign<OFFSET_T>(sortedIdxShiftOneReg, u0, startAddr - 1);
        AscendC::Reg::Compare<OFFSET_T, CMPMODE::NE>(cmpMask, sortedIdxReg, sortedIdxShiftOneReg, maskReg);
        if constexpr (std::is_same<int64_t, OFFSET_T>::value) {
            AscendC::Reg::MaskReg maskHalf;
            AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(maskHalf, cmpMask);
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg, orderReg,
                                                                                                 maskHalf);
        } else {
            AscendC::Reg::GatherMask<int32_t, AscendC::Reg::GatherMaskMode::STORE_REG>(selReg, orderReg,
                                                                                                 cmpMask);
        }
        AscendC::Reg::DataCopyUnAlign<int32_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
            uniqueIdCountsAddr, selReg, uOut);
    }
    AscendC::Reg::DataCopyUnAlignPost(uniqueIdCountsAddr, uOut);
}
```

**要点**:
1. ClearSpr<AR>() 在循环前调用
2. AR 配合 DataCopyUnAlignPost 统计写出长度
3. int64 索引需 MaskPack(LOWEST) 折半 mask 后再 GatherMask

### 实例 11：unsorted_segment_common::UniqueGetElmVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AR
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: unsorted_segment_common 计算唯一 ID 数前清零 AR 寄存器，为后续按索引类型分派的去重子流程提供干净初始值。

（行 408-420）

```cpp
{
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();

    if constexpr (std::is_same<int64_t, IDX_T>::value) {
        ComputeUniqueIdNumInt64<IDX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else if constexpr (std::is_same<int32_t, IDX_T>::value) {
        ComputeUniqueIdNumInt32<IDX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else if constexpr (std::is_same<int16_t, IDX_T>::value) {
        ComputeUniqueIdNumInt16<IDX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else { // uint8
        ComputeUniqueIdNumUint8<IDX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    }
}
```

**要点**:
1. ClearSpr<AR>() 在按类型 if constexpr 分派前调用一次
2. AR 由被调用的 ComputeUniqueIdNumInt* 子函数内部累加
3. 实参 0 个，仅通过模板参数指定要清零的特殊寄存器

### 实例 12：scatter_update::ComputeUniqueIdNumVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AR
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: scatter_update 计算唯一 ID 数前清零 AR 寄存器，为后续按索引类型分派的去重子流程提供干净初始值。

（行 195-207）

```cpp
{
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();

    if constexpr (std::is_same<int64_t, INX_T>::value) {
        ComputeUniqueIdNumInt64<INX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else if constexpr (std::is_same<int32_t, INX_T>::value) {
        ComputeUniqueIdNumInt32<INX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else if constexpr (std::is_same<int16_t, INX_T>::value) {
        ComputeUniqueIdNumInt16<INX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else {
        ComputeUniqueIdNumUint8<INX_T>(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    }
}
```

**要点**:
1. ClearSpr<AR>() 在按类型 if constexpr 分派前调用
2. AR 由 ComputeUniqueIdNumInt* 子函数内部累加
3. 仅清零、不在本函数内读取

### 实例 13：inplace_index_add::ComputeUniqueIdNumVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AR
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: inplace_index_add 计算唯一 ID 数前清零 AR 寄存器，为后续按索引类型分派的去重子流程提供干净初始值。

（行 461-473）

```cpp
{
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();

    if constexpr (std::is_same<int64_t, CAST_T>::value) {
        ComputeUniqueIdNumInt64(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else if constexpr (std::is_same<int32_t, CAST_T>::value) {
        ComputeUniqueIdNumInt32(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else if constexpr (std::is_same<int16_t, CAST_T>::value) {
        ComputeUniqueIdNumInt16(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else { // uint8
        ComputeUniqueIdNumUint8(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    }
}
```

**要点**:
1. ClearSpr<AR>() 在按类型 if constexpr 分派前调用
2. AR 由 ComputeUniqueIdNumInt* 子函数内部累加
3. 仅清零、不在本函数内读取

### 实例 14：scatter_nd_common::ComputeUniqueIdNumVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AR
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: scatter_nd_common 计算唯一 ID 数前清零 AR 寄存器，为后续按索引类型分派的去重子流程提供干净初始值。

（行 442-453）

```cpp
{
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();
    if constexpr (std::is_same<int64_t, CAST_T>::value) {
        ComputeUniqueIdNumInt64(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else if constexpr (std::is_same<int32_t, CAST_T>::value) {
        ComputeUniqueIdNumInt32(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else if constexpr (std::is_same<int16_t, CAST_T>::value) {
        ComputeUniqueIdNumInt16(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    } else {
        ComputeUniqueIdNumUint8(indicesAddr, uniqueIdCountsAddr, loopCnt, dataLen);
    }
}
```

**要点**:
1. ClearSpr<AR>() 在按类型 if constexpr 分派前调用
2. AR 由 ComputeUniqueIdNumInt* 子函数内部累加
3. 仅清零、不在本函数内读取

### 实例 15：index_fill::ComputeUniqueIdNumVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AR
- **ClearSpr 调用次数**: 1
- **参数模式**: `T1_A0_M0_TYPEnone`（实参 0 个）
- **语义**: index_fill 计算唯一 ID 数前清零 AR 寄存器，为后续按索引类型分派的去重子流程提供干净初始值。

（行 179-186）

```cpp
{
    AscendC::Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();
    if constexpr (std::is_same<int64_t, INDEX_TYPE>::value) {
        ComputeUniqueIdNumInt64<INDEX_TYPE>(sortedInputAddr, uniqueIndicesAddr, loopCnt, dataLen);
    } else if constexpr (std::is_same<int32_t, INDEX_TYPE>::value) {
        ComputeUniqueIdNumInt32<INDEX_TYPE>(sortedInputAddr, uniqueIndicesAddr, loopCnt, dataLen);
    }
}
```

**要点**:
1. ClearSpr<AR>() 在按类型 if constexpr 分派前调用
2. 仅支持 int64/int32 两种索引类型分派
3. AR 由 ComputeUniqueIdNumInt* 子函数内部累加

### ClearSpr 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| sparse_slice | AR, Compare, CreateMask, DataCopy | 清零 AR 供 DataCopyUnAlign(PostMode) 累加各维度写出字节数 | __VEC_SCOPE__ |
| broadcast_gradient_args | AR, Adds, Arange, Cast | 清零 AR 供 DataCopyUnAlign(PostMode) 累加缩减轴索引写出数 | __aicore__ |
| embedding_dense_grad | AR, Arange, Compare, DataCopy | 清零 AR 供去重循环 DataCopyUnAlign(PostMode) 累加写出量 | __aicore__ |
| unsorted_segment_sum | AR, Arange, Compare, DataCopy | 清零 AR 供去重循环 DataCopyUnAlign(PostMode) 累加写出量 | __aicore__ |
| non_zero | AR, Adds, Arange, CreateMask | 清零 AR 供循环内多次 DataCopyUnAlign(PostMode) 累加索引写出数 | __VEC_SCOPE__ |
| segment_sum | AR, Arange, Compare, DataCopy | 清零 AR 供段边界查找循环 DataCopyUnAlign(PostMode) 累加写出量 | __VEC_SCOPE__ |
| scatter_nd | AR, Arange, Compare, DataCopyUnAlign | 清零 AR 供唯一 ID 计算循环 DataCopyUnAlign(PostMode) 累加写出量 | __simd_vf__ |
| scatter_add | AR, Arange, Compare, DataCopyUnAlign | 清零 AR 供唯一 ID 计算循环 DataCopyUnAlign(PostMode) 累加写出量 | __simd_vf__ |
| scatter_nd_add | AR, Arange, Compare, DataCopyUnAlign | 清零 AR 供确定性唯一 ID 计算循环 DataCopyUnAlign(PostMode) 累加写出量 | __simd_vf__ |
| scatter_nd_update | AR, Arange, Compare, DataCopyUnAlign | 清零 AR 供唯一 ID 计算循环 DataCopyUnAlign(PostMode) 累加写出量 | __simd_vf__ |
| unsorted_segment_common | AR | 清零 AR 供按类型分派的去重子函数累加写出量 | __simd_vf__ |
| scatter_update | AR | 清零 AR 供按类型分派的去重子函数累加写出量 | __simd_vf__ |
| inplace_index_add | AR | 清零 AR 供按类型分派的去重子函数累加写出量 | __simd_vf__ |
| scatter_nd_common | AR | 清零 AR 供按类型分派的去重子函数累加写出量 | __simd_vf__ |
| index_fill | AR | 清零 AR 供按类型分派的去重子函数(int64/int32)累加写出量 | __simd_vf__ |
