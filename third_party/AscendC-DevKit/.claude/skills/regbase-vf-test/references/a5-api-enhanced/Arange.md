# Arange

**页面ID:** atlasascendc_api_07_0408  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0408.html

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

以传入的scalar的值为起始值，生成递增/递减的索引，并将产生的索引保存在dstReg中。

#### 函数原型

```
template <typename T = DefaultType, IndexOrder order = IndexOrder::INCREASE_ORDER, typename U, typename S>
__simd_callee__ inline void Arange(S& dstReg, U scalarValue);
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/int16_t/int32_t/half/float/int64_t |
| U | 起始索引值的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/int16_t/int32_t/half/float/int64_t |
| S | 目的操作数的RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void ArangeVF(__ubuf__ T* dstAddr, T scalarValue, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    mask = AscendC::Reg::CreateMask<T>();
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::Arange(dstReg, scalarValue);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Arange 实例

### 实例 1：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Arange 调用次数**: 6
- **参数模式**: `T0_A2_M0_TYPEint8_t`（实参 2 个，类型: int8_t）
- **语义**: 在 SwiGLU 反向 MX 量化算子中，用 int8_t 起始值生成递增索引寄存器，作为 Gather 抽取 scale 与倒数 scale 行的索引基准。

**片段 1** (行 893-922):

```cpp
for (uint16_t i = 0; i < blockCount; i++) {
    Reg::DataCopy<xDtype, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
        regA, regB, xAddr, dataLen);

    Reg::And(regU16_0, (Reg::RegTensor<uint16_t>&)regA, absMask, maskAll);
    Reg::And(regU16_1, (Reg::RegTensor<uint16_t>&)regB, absMask, maskAll);

    Reg::Max(regU16_2, regU16_0, regU16_1, maskAll);
    Reg::ReduceMaxWithDataBlock(regU16_2, regU16_2, maskAll);
    // 8: 每次循环scale1偏移8个元素
    Reg::StoreUnAlign<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(tempMaxAddr, regU16_2, ureg, 8);

    Reg::Max(absMax1Dim2, absMax1Dim2, regU16_0, maskAll);
    Reg::Max(absMax2Dim2, absMax2Dim2, regU16_1, maskAll);
}
Reg::StoreUnAlignPost(tempMaxAddr, ureg, 0);

Reg::Duplicate(invMax, localInvDtypeMax);
Reg::Duplicate(manMaskReg, MAN_MASK_FLOAT);
Reg::Duplicate(expMaskReg, MAX_EXP_FOR_FP32);
Reg::Duplicate(zeroReg32, static_cast<uint32_t>(0));
Reg::Duplicate(scaleBiasReg, FP32_EXP_BIAS_CUBLAS);
Reg::Duplicate(nanReg32, static_cast<uint32_t>(NAN_CUSTOMIZATION));
Reg::Duplicate(fp8NanReg32, MAX_EXP_FOR_FP8_IN_FP32);

Reg::Arange(indexShiftS8, static_cast<int8_t>(scale1BIdx));

__ubuf__ uint16_t* readMaxAddr = mxScale2ReciprocalAddr;
// 8: 每次处理的数据元素个数=32 * 8
uint16_t batchCount = ops::CeilDiv(static_cast<uint16_t>(blockCount * 8), static_cast<uint16_t>(VF_LEN_FP32));
```

**片段 2** (行 971-989):

```cpp
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

**要点**:
1) 第二实参为 int8_t 起始 scalar，生成按 1 递增的索引，用作 Gather 的索引源；
2) 循环内通过 k*8、k*16 改变起始值，使每次循环索引步进 8 或 16，对应 scale 的字节粒度搬运偏移；
3) 与 Gather 组合实现按索引抽取 scale 行，索引值即元素偏移，需与 scale 数据布局（8/16 字节对齐）匹配。

### 实例 2：broadcast_gradient_args::CalcReduceAxes

- **来源类型**: `__aicore__`
- **共现 API**: AR, Adds, Cast, ClearSpr, CompareScalar, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, GatherMask, GatherMaskMode, GetSpr, MaskPattern, MaskReg, Pack, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Arange 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在广播梯度参数计算中，以 0 为起始值生成递增索引寄存器，作为各循环迭代绝对索引的基准。

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
1) 起始值传 0 生成 0,1,2,... 连续索引，循环内用 Adds 叠加 i*vl 块偏移得到全局索引；
2) 与 GatherMask 组合按 CompareScalar==1 的掩码抽取满足条件的索引输出；
3) 第二实参为标量起始值，类型由 RegTensor 模板参数推导（int32_t）。

### 实例 3：pool_3d_common::ComputeDivisorImplB64

- **来源类型**: `__aicore__`
- **共现 API**: AddrReg, CreateAddrReg, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Div, Duplicate, MaskPattern, MaskReg, Mul, RegTensor, RegTraitNumTwo, Sub, UnalignReg, UpdateMask
- **Arange 调用次数**: 6
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 3D 池化除数计算中，按循环索引生成连续基准索引 v0，再用 Div/Mul/Sub 分解出 D/H/W 维度的窗口坐标。

**片段 1** (行 1054-1061):

```cpp
for (uint16_t i = 0; i < loopNum; i++) {
    Reg::Arange(v0, i * oneRegLength + start);
    Reg::AddrReg resOffset = Reg::CreateAddrReg<float32_t>(i, oneRegLength);
    Reg::MaskReg pWrite = Reg::UpdateMask<float32_t>(sreg);
    Reg::Div(vd1, v0, v1, p0); // i / outhw  -> didx(vd1)
    CalcWindowSize<int64_t, countIncludePad>(dWindow, vd1, kD, sD, negFrontPad, dIn, dInAndBackendPad, p0);
    Reg::DataCopy(dstAddr, dWindow, resOffset, pWrite);
}
```

**片段 2** (行 1063-1075):

```cpp
for (uint16_t i = 0; i < loopNum; i++) {
    Reg::Arange(v0, i * oneRegLength + start);
    Reg::AddrReg resOffset = Reg::CreateAddrReg<float32_t>(i, oneRegLength);
    Reg::MaskReg pWrite = Reg::UpdateMask<float32_t>(sreg1);
    Reg::Div(vd1, v0, v1, p0);  // i / outhw
    Reg::Mul(vd2, vd1, v1, p0); // (i / outhw * outhw)
    Reg::Sub(vd3, v0, vd2, p0); // i % outhw
    Reg::Div(vd2, vd3, v2, p0); // i % outhw / outh
    CalcWindowSize<int64_t, countIncludePad>(hWindow, vd2, kH, sH, negTopPad, hIn, hInAndBottomPad, p0);
    Reg::DataCopy(res, dstAddr, resOffset);
    Reg::Mul(res, res, hWindow, p0);
    Reg::DataCopy(dstAddr, res, resOffset, pWrite);
}
```

**片段 3** (行 1077-1089):

```cpp
for (uint16_t i = 0; i < loopNum; i++) {
    Reg::Arange(v0, i * oneRegLength + start);
    Reg::AddrReg resOffset = Reg::CreateAddrReg<float32_t>(i, oneRegLength);
    Reg::MaskReg pWrite = Reg::UpdateMask<float32_t>(sreg2);
    Reg::Div(vd3, v0, v2, p0);  // i / outw
    Reg::Mul(vd3, vd3, v2, p0); // (i / outhw * outhw)
    Reg::Sub(vd3, v0, vd3, p0); // i % outhw
    CalcWindowSize<int64_t, countIncludePad>(wWindow, vd3, kW, sW, negLeftPad, wIn, wInAndRightPad, p0);
    Reg::DataCopy(res, dstAddr, resOffset);
    Reg::Mul(res, res, wWindow, p0);
    Reg::DataCopy(dstAddr, res, resOffset, pWrite);
}
```

**要点**:
1) 起始值随循环 i*oneRegLength+start 递增，使每个寄存器块覆盖不同元素区间；
2) 生成的索引经 Div 求整除、Sub 求余数得到多维坐标（i/outhw、i%outhw 等）；
3) 与 AddrReg/CreateAddrReg 组合按计算的窗口值写入对应输出位置。

### 实例 4：pool_3d_common::AvgPoolDivBatchV1

- **来源类型**: `__aicore__`
- **共现 API**: AddrReg, Cast, CreateAddrReg, CreateMask, DataCopy, DataCopyGather, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Div, Duplicate, MaskPattern, MaskReg, Pack, RegTensor, UnalignReg, UpdateMask
- **Arange 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t`（实参 1 个，类型: int32_t）
- **语义**: 在池化通道广播分支中，以 0 起始生成 int32_t 连续索引，再除以通道数得到通道内偏移索引。

（行 1302-1308）

```cpp
if constexpr (CHANNEL_BROADACAST) {
    Reg::Arange((Reg::RegTensor<int32_t>&)index, 0);
    Reg::RegTensor<uint32_t> channelDiv;
    Reg::MaskReg p0 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
    Reg::Duplicate(channelDiv, channel, p0);
    Reg::Div(index, index, channelDiv, p0);
}
```

**要点**:
1) 显式 cast 目的寄存器为 RegTensor<int32_t>&，起始值传 0 生成 0,1,2,... 索引；
2) 索引经 Div(index, channelDiv) 得到通道内位置，用于通道广播场景；
3) 仅在 CHANNEL_BROADACAST 编译分支内使用，体现按条件启用的索引构造。

### 实例 5：cumsum::Reg::Adds

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, Copy, CreateMask, DataCopyGather, DataCopyScatter, Div, Duplicate, LocalMemBar, MaskPattern, MaskReg, MemType, Muls, RegTensor, Sub, UpdateMask
- **Arange 调用次数**: 4
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在累加和（cumsum）两阶段计算中，用 Arange(sIdx, 0) 将 scatter 索引重置为 0 起始的连续递增序列，作为第二阶段 Gather/Scatter 的索引基准。

**片段 1** (行 709-709):

```cpp
__VEC_SCOPE__
```

**片段 2** (行 746-761):

```cpp
for (uint16_t rIdx = 0; rIdx < rLpNum; rIdx++) {
    Reg::DataCopyGather(
        (Reg::RegTensor<CastType>&)xSrc, srcPtr, (Reg::RegTensor<IdxType>&)gIdx, comMask);
    Reg::Add(yDst, yDst, xSrc, comMask);
    Reg::DataCopyScatter(dstPtr, yDst, (Reg::RegTensor<IdxType>&)sIdx, comMask);
    Reg::Adds(gIdx, gIdx, phs1LpOffset, idxMask);
    Reg::Adds(sIdx, sIdx, phs1LpOffset, idxMask);
}
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();

// second operation, get result
Reg::Copy(xSrc, bakSrc);
Reg::Arange(sIdx, (RangeType)0);
Reg::Copy(gIdx, sIdx);
Reg::Adds(gIdx, gIdx, phs2SrcBegIdx, idxMask);
Reg::Adds(sIdx, sIdx, phs2DstBegIdx, idxMask);
```

**要点**:
1) 起始值传 (RangeType)0 生成 0,1,2,... 连续索引，用于 DataCopyGather/DataCopyScatter 的索引对齐；
2) 索引经 Adds 叠加 phs2SrcBegIdx/phs2DstBegIdx 偏移得到第二阶段全局源/目索引；
3) 与 Copy 配合实现 gIdx = sIdx + 偏移，体现 Arange 作为索引初值生成器的典型用法。

### 实例 6：cross_entropy_loss_grad::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, AddrReg, Cast, CreateAddrReg, CreateMask, DataCopy, DataCopyGather, DataCopyScatter, Duplicate, MaskPattern, MaskReg, Mul, Pack, RegTensor, Sub, UpdateMask
- **Arange 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在交叉熵损失反向中，以 0 起始生成连续索引并乘以类别对齐长度，得到每行的基地址偏移，叠加到 target 索引上做 Gather/Scatter。

（行 319-373）

```cpp
__VEC_SCOPE__
{
    Reg::MaskReg regAllGather;
    Reg::RegTensor<T2> regTarget;
    Reg::RegTensor<int32_t> regTargetB32Tmp;
    Reg::RegTensor<int32_t> regTargetB32;
    Reg::RegTensor<int32_t> regIndex1;
    Reg::RegTensor<int32_t> regIndex0;
    Reg::RegTensor<float> regGather1;
    Reg::RegTensor<float> regGather;
    Reg::RegTensor<float> regLogProbB32;
    Reg::RegTensor<float> regNllLossGrad;
    Reg::MaskReg regAllB32 = Reg::CreateMask<int32_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregUp = Reg::UpdateMask<uint32_t>(tailNum);
    Reg::Arange(regIndex1, 0);
    Reg::Duplicate(regIndex0, totalCLenAlign, regAllB32);
    Reg::Mul(regIndex1, regIndex0, regIndex1, regAllB32);
    for (uint16_t loop = 0; loop < repeatTimes; loop++) {
        Reg::AddrReg srcOffset = Reg::CreateAddrReg<T2>(loop, vfLen);
        Reg::AddrReg outOffset = Reg::CreateAddrReg<float>(loop, vfLen);
        if constexpr (IsSameType<T2, int64_t>::value) {
            Reg::DataCopy(regTarget, targetAddr, srcOffset);
            Reg::Cast<int32_t, T2, castS642S32>(regTargetB32Tmp, regTarget, regAllB32);
            Reg::Pack((Reg::RegTensor<uint32_t>&)regTargetB32,
                           (Reg::RegTensor<uint64_t>&)regTargetB32Tmp);
            regAllGather = Reg::CreateMask<int32_t, Reg::MaskPattern::H>();
        } else {
            Reg::DataCopy(regTargetB32, targetAddr, srcOffset);
            regAllGather = Reg::CreateMask<int32_t, Reg::MaskPattern::ALL>();
        }
        Reg::Add(regTargetB32, regTargetB32, regIndex1, regAllB32);
        Reg::DataCopy(regNllLossGrad, nllLossGradAddr, outOffset);
        Reg::DataCopyGather(regGather, xGradTmpAddr + loop * vfLen * totalCLenAlign,
                                 (Reg::RegTensor<uint32_t>&)regTargetB32, regAllGather);
        Reg::Sub(regGather1, regGather, regNllLossGrad, regAllB32);
        Reg::DataCopyScatter(xGradTmpAddr + loop * vfLen * totalCLenAlign, regGather1,
                                  (Reg::RegTensor<uint32_t>&)regTargetB32, regAllGather);
    }
    for (uint16_t k = 0; k < tailLoopNums; k++) {
        if constexpr (IsSameType<T2, int64_t>::value) {
            Reg::DataCopy(regTarget, targetAddrT);
            Reg::Cast<int32_t, T2, castS642S32>(regTargetB32Tmp, regTarget, regAllB32);
            Reg::Pack((Reg::RegTensor<uint32_t>&)regTargetB32,
                           (Reg::RegTensor<uint64_t>&)regTargetB32Tmp);
        } else {
            Reg::DataCopy(regTargetB32, targetAddrT);
        }
        Reg::Add(regTargetB32, regTargetB32, regIndex1, regAllB32);
        Reg::DataCopy(regNllLossGrad, nllLossGradAddrT);
        Reg::DataCopyGather(regGather, xGradTmpAddrT, (Reg::RegTensor<uint32_t>&)regTargetB32, pregUp);
        Reg::Sub(regGather1, regGather, regNllLossGrad, regAllB32);
        Reg::DataCopyScatter(xGradTmpAddrT, regGather1, (Reg::RegTensor<uint32_t>&)regTargetB32, pregUp);
    }
}
```

**要点**:
1) Arange(regIndex1, 0) 生成 0,1,2,... 再 Mul(totalCLenAlign) 得到行步进偏移序列；
2) 偏移叠加到 target 索引后用于 DataCopyGather/DataCopyScatter 定位 xGrad 的行内位置；
3) int64_t 分支需先 Cast+Pack 把 target 压成 int32_t 再做索引运算。

### 实例 7：embedding_dense_grad::UniqueGetElm

- **来源类型**: `__aicore__`
- **共现 API**: AR, ClearSpr, Compare, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Arange 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在嵌入反向去重中，按循环 i*vfIndicesNum_ 起始值生成连续 orderReg 索引，作为唯一性筛选后保留原始序号的索引源。

（行 133-156）

```cpp
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
```

**要点**:
1) 起始值随循环 scalar = i*vfIndicesNum_ 递增，每个寄存器块对应不同元素区间的序号；
2) orderReg 经 Compare(NE) 比较相邻索引找段边界，再 GatherMask 抽取段首序号（vSQZ）；
3) 与 ClearSpr(AR)/UpdateMask 配合，掩码控制尾块有效元素数。

### 实例 8：non_zero::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, Adds, ClearSpr, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, GatherMask, GatherMaskMode, HighLowPart, MaskPattern, MaskReg, MaskUnPack, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Arange 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在非零元素提取中，以 startIdx 起始值生成连续索引 idsReg，循环内按偏移递增并配合比较掩码 GatherMask 出非零位置的索引。

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
1) 起始值传 startIdx（非 0），支持多核/多块拼接时索引连续化；
2) 循环内 Adds(offsetNum64) 每轮推进一个 repeat 的元素数，保证跨块索引递增；
3) 用 MaskUnPack 把比较掩码拆成 4 个子掩码，分别 GatherMask 输出 4 路非零索引。

### 实例 9：segment_sum::platform::GetUbBlockSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, ClearSpr, Compare, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Arange 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在段求和中，按循环 i*vl 起始值生成连续 orderReg 序号，配合相邻段 ID 比较找段边界并 GatherMask 输出段起始序号。

（行 117-140）

```cpp
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
```

**要点**:
1) 起始值 vciStart = i*vl 随循环递增，每个寄存器块对应不同元素区间的序号；
2) orderReg 经 Compare(NE) 比较相邻 segmentId 找段边界，GatherMask 抽取段首序号；
3) int64_t 分支用 MaskPack 取低半掩码做 32 位 GatherMask。

### 实例 10：cross_entropy_loss::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Cast, CompareScalar, CreateMask, DataCopy, DataCopyGather, Duplicate, MaskPattern, MaskReg, Mul, Muls, Pack, RegTensor, Select, UpdateMask
- **Arange 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在交叉熵损失前向中，以 0 起始生成连续索引并乘以 rAlign 行步进，得到每行基地址偏移，叠加 target 索引做 log_prob 的 Gather。

（行 717-767）

```cpp
AscendC::Reg::RegTensor<float> reg0;
AscendC::Reg::RegTensor<float> reg1;
AscendC::Reg::Duplicate(reg0, 0.0f);
AscendC::Reg::Duplicate(reg1, 1.0f);
AscendC::Reg::RegTensor<float> weightGatherReg;
AscendC::Reg::RegTensor<float> weightDestReg;
AscendC::Reg::RegTensor<float> lossOutGatherReg;
AscendC::Reg::RegTensor<float> lossOutDestReg;
AscendC::Reg::RegTensor<float> smoothLossReg;
AscendC::Reg::RegTensor<float> smoothLossDestReg;
AscendC::Reg::RegTensor<int32_t> indexReg0;
AscendC::Reg::RegTensor<int32_t> indexReg1;
AscendC::Reg::RegTensor<int32_t> indexReg2;
AscendC::Reg::RegTensor<int32_t> targetDstReg;
AscendC::Reg::Duplicate(indexReg0, static_cast<int32_t>(rAlign));
AscendC::Reg::Arange(indexReg1, 0);
AscendC::Reg::Mul(indexReg2, indexReg0, indexReg1, regAll);

for (uint16_t i = 0; i < repeatTimes; i++) {
    if constexpr (sizeof(T2) == sizeof(int64_t)) {
        Reg::DataCopy(srcReg, targetUbAddr + i * vfLen);
        Reg::Cast<int32_t, T2, castTrait1>(tempReg, srcReg, regAll);
        Reg::Pack((RegTensor<uint32_t>&)targetReg, (RegTensor<uint64_t>&)tempReg);
        regGather = AscendC::Reg::CreateMask<int32_t, AscendC::Reg::MaskPattern::H>();
    } else {
        Reg::DataCopy(targetReg, targetUbAddr + i * vfLen);
        regGather = AscendC::Reg::CreateMask<int32_t, AscendC::Reg::MaskPattern::ALL>();
    }
    Reg::CompareScalar<int32_t, CMPMODE::EQ>(dstMask, targetReg, ignoreData, regAll);

    if constexpr (isWeight == 1) {
        Reg::DataCopyGather(weightGatherReg, weightAddr, (Reg::RegTensor<uint32_t>&)targetReg,
                                 regGather);
        Reg::Select(weightDestReg, reg0, weightGatherReg, dstMask);
        Reg::DataCopy(weightYnAddr + i * vfLen, weightDestReg, regGather);
    } else {
        Reg::Select(weightDestReg, reg0, reg1, dstMask);
        Reg::DataCopy(weightYnAddr + i * vfLen, weightDestReg, regGather);
    }
    if constexpr (labelS != 0) {
        Reg::DataCopy(smoothLossReg, smoothSumAddr + i * vfLen);
        Reg::Muls(smoothLossReg, smoothLossReg, -1.0f, regAll);
        Reg::Select(smoothLossDestReg, reg0, smoothLossReg, dstMask);
        Reg::DataCopy(smoothLossAddr + i * vfLen, smoothLossDestReg, regGather);
    }
    Reg::Add(targetDstReg, indexReg2, targetReg, regAll);
    Reg::DataCopyGather(lossOutGatherReg, logPropAddr + i * vfLen * rAlign,
                             (Reg::RegTensor<uint32_t>&)targetDstReg, regGather);
    Reg::Select(lossOutDestReg, reg0, lossOutGatherReg, dstMask);
    Reg::DataCopy(lossOutAddr + i * vfLen, lossOutDestReg, regGather);
}
```

**要点**:
1) Arange(indexReg1, 0) 生成 0,1,2,...，Mul(rAlign) 得到行步进偏移序列；
2) 偏移叠加 target 索引后 DataCopyGather 抽取对应行的 log_prob；
3) 与 Select/CompareScalar 组合处理 ignore_index 掩码对权重与损失的选择。

### 实例 11：arg_max_with_value::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, HighLowPart, MaskAnd, MaskMergeMode, MaskNot, MaskOr, MaskPattern, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Arange 调用次数**: 1
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 argmax 取最大值中，以 0 起始生成 0..63 连续索引，再乘以 dimNextA 得到按维度的跨步索引，作为比较扫描的基准位置。

（行 683-699）

```cpp
AscendC::Reg::RegTensor<T4> value0, value1, valueResult;
AscendC::Reg::RegTensor<uint32_t> indexResult32;
AscendC::Reg::UnalignReg uValue, uIndex, uSrc;
AscendC::Reg::RegTensor<T5> level0, level1, indexResult, helpIndex;

AscendC::Reg::MaskReg helpV0Mask, helpV1Mask, cmpMask;
AscendC::Reg::MaskReg oneMask = AscendC::Reg::CreateMask<T5, AscendC::Reg::MaskPattern::VL1>();
AscendC::Reg::MaskReg twoMask = AscendC::Reg::CreateMask<T5, AscendC::Reg::MaskPattern::VL2>();
AscendC::Reg::MaskReg allMask32 = AscendC::Reg::CreateMask<T5, AscendC::Reg::MaskPattern::ALL>();
AscendC::Reg::MaskReg newMask = AscendC::Reg::UpdateMask<T5>(tailSize);
AscendC::Reg::MaskReg addMask = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::VL1>();
AscendC::Reg::MaskReg b8Mask = AscendC::Reg::CreateMask<uint8_t, AscendC::Reg::MaskPattern::ALL>();

Duplicate(helpIndex, VALUE_ONE, allMask32);
Duplicate<T5, AscendC::Reg::MaskMergeMode::MERGING, T5>(helpIndex, VL, oneMask);
Arange(initIndex, 0);                            // (0, 1, 2, ... , 63)
Muls(initIndex, initIndex, dimNextA, allMask32); // (0, 1 *dimNextA, 2*dimNextA, ... , 63*dimNextA)
```

**要点**:
1) Arange(initIndex, 0) 生成 0..63（一个寄存器长度），Muls(dimNextA) 缩放为维度跨步索引；
2) 生成的索引用作 argmax 比较的初始位置序列，配合 MaskAnd/MaskOr/MaskNot 做逐对比较；
3) 用 VL1/VL2 等特殊 MaskPattern 控制单元素/双元素比较的掩码。

### 实例 12：scatter_nd::ComputeUniqueIdNumVecImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: AR, ClearSpr, Compare, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskReg, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Arange 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 scatter_nd 去重计数中，按循环 i*vfLen 起始值生成连续 orderReg 序号，配合相邻排序索引比较找唯一边界并 GatherMask 输出。

（行 462-483）

```cpp
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
```

**要点**:
1) 起始值随循环 i*vfLen 递增，每个寄存器块对应不同元素区间的序号；
2) orderReg 经 Compare(NE) 比较相邻 sortedIdx 找唯一边界，GatherMask 抽取边界序号；
3) int64_t 分支用 MaskPack 取低半掩码做 32 位 GatherMask。

### 实例 13：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, DataCopy, DataCopyScatter, Div, Duplicate, HighLowPart, MaskPack, MaskPattern, MaskReg, Mul, RegTensor, Sub, UnPack, UpdateMask
- **Arange 调用次数**: 1
- **参数模式**: `T1_A2_M0_TYPEint32_t`（实参 2 个，类型: int32_t）
- **语义**: 在稀疏切片中，显式指定 <int32_t> 模板参数按循环偏移生成连续源索引，再用 Div/Mul/Sub 分解出行列偏移用于 DataCopyScatter。

（行 901-913）

```cpp
for (uint16_t loopIndex = 0; loopIndex < loopNum; loopIndex++) {
    preg = Reg::UpdateMask<int64_t>(sreg0);
    Reg::MaskPack<Reg::HighLowPart::LOWEST>(pregB32, preg);
    Reg::DataCopy(vregInput, yIndicesTransposedAddr + loopIndex * vlSize);
    Reg::Arange<int32_t>(vregSrcIndex, (int32_t)(loopIndex * vlSize));
    Reg::Div(vreg0, vregSrcIndex, vregCol, pregB32);
    Reg::Mul(vreg1, vreg0, vregCol, pregB32);
    Reg::Sub(vreg2, vregSrcIndex, vreg1, pregB32);
    Reg::Mul(vreg3, vreg2, vregRow, pregB32);
    Reg::Add(vregDstIndex, vreg3, vreg0, pregB32);
    Reg::UnPack<int64_t, int32_t, Reg::HighLowPart::LOWEST>(vregDstIndexB64, vregDstIndex);
    Reg::DataCopyScatter(yIndicesAddr, vregInput, (Reg::RegTensor<uint64_t>&)vregDstIndexB64, preg);
}
```

**要点**:
1) 显式模板参数 Arange<int32_t>，目的寄存器为 int32_t，起始值 (int32_t)(loopIndex*vlSize) 随循环递增；
2) 生成的索引经 Div(vregCol)、Sub 取余分解为行、列偏移，再 Mul(vregRow)+Add 拼成目标线性索引；
3) 索引经 UnPack<int64_t,LOWEST> 压成 int64_t 供 DataCopyScatter 按掩码散写。

### 实例 14：gather_elements::ComputeDim8Vf

- **来源类型**: `__aicore__`
- **共现 API**: Add, Copy, CreateMask, DataCopy, DeInterleave, Div, Duplicate, MaskPattern, MaskReg, Mul, Muls, RegTensor, Sub, UpdateMask
- **Arange 调用次数**: 4
- **参数模式**: `T0_A1_M0_TYPEint16_t`（实参 1 个，类型: int16_t）
- **语义**: 在 gather_elements 中，按偏移类型分支生成 int16_t 或 int32_t 索引，起始值随循环 idxOffset + i*oneRepeatSize 递增，再除以 stride 得到元素内偏移。

（行 777-783）

```cpp
if constexpr (std::is_same<OFFSET_T, uint16_t>::value) {
    Reg::Arange((Reg::RegTensor<int16_t>&)RegArange, (int16_t)idxOffset + i * oneRepeatSize);
} else {
    Reg::Arange((Reg::RegTensor<int32_t>&)RegArange, (int32_t)idxOffset + i * oneRepeatSize);
}
Reg::Duplicate(RegIdxStride, (OFFSET_T)indexStrideArr0);
Reg::Div(Regtmp, RegArange, RegIdxStride, maskReg);
```

**要点**:
1) 用 if constexpr (is_same<OFFSET_T, uint16_t>::value) 分支选择 int16_t/int32_t 目的类型并 cast 目的寄存器；
2) 起始值 (int16_t)idxOffset + i*oneRepeatSize 随循环推进，覆盖不同 repeat 的元素区间；
3) 生成的索引经 Div(RegIdxStride) 得到按 stride 划分的组内偏移，供后续 Gather 使用。

### 实例 15：adaptive_avg_pool2d_grad::VecScope_L466

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, CreateMask, DataCopy, Div, Duplicate, MaskPattern, MaskReg, Maxs, Mins, Mul, RegTensor, Sub, UpdateMask
- **Arange 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在自适应平均池化反向中，以 hBaseIdx 起始值生成高度方向连续索引 hIdx，经 Mul/Div/Add 计算每个输出行的起止与覆盖范围。

（行 466-503）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<INDEX> hIdx;
    Reg::Arange(hIdx, hBaseIdx);

    Reg::MaskReg hAllMask = Reg::CreateMask<INDEX, Reg::MaskPattern::ALL>();
    Reg::MaskReg hBatchMask = Reg::UpdateMask<INDEX>(hBatchCountMask);

    Reg::RegTensor<INDEX> hRegOut;
    Reg::Duplicate(hRegOut, hOutput);

    Reg::RegTensor<INDEX> hRegIn;
    Reg::Duplicate(hRegIn, hGradInput);

    Reg::RegTensor<INDEX> hStGlobal;
    Reg::Mul(hStGlobal, hIdx, hRegOut, hAllMask);
    Reg::Div(hStGlobal, hStGlobal, hRegIn, hAllMask);

    Reg::RegTensor<INDEX> hEdGlobal;
    Reg::Adds(hEdGlobal, hIdx, INDEX(1), hAllMask);
    Reg::Mul(hEdGlobal, hEdGlobal, hRegOut, hAllMask);
    Reg::Add(hEdGlobal, hEdGlobal, hRegIn, hAllMask);
    Reg::Adds(hEdGlobal, hEdGlobal, INDEX(-1), hAllMask);
    Reg::Div(hEdGlobal, hEdGlobal, hRegIn, hAllMask);

    Reg::RegTensor<INDEX> hCover;
    Reg::Sub(hCover, hEdGlobal, hStGlobal, hAllMask);

    Reg::Maxs(hStGlobal, hStGlobal, hTileStart, hAllMask);
    Reg::Adds(hStGlobal, hStGlobal, INDEX(-hTileStart), hAllMask);

    Reg::Mins(hEdGlobal, hEdGlobal, hTileEnd, hAllMask);
    Reg::Adds(hEdGlobal, hEdGlobal, INDEX(-hTileStart), hAllMask);

    Reg::DataCopy(stHAddr, hStGlobal, hBatchMask);
    Reg::DataCopy(edHAddr, hEdGlobal, hBatchMask);
    Reg::DataCopy(coverHAddr, hCover, hBatchMask);
}
```

**要点**:
1) 起始值传 hBaseIdx（非 0）生成高度方向连续索引，后续用 Adds(hIdx, 1) 得到 end = start+1 的端点；
2) 索引经 Mul(hOutput)/Div(hGradInput) 计算输出空间到输入空间的映射起止位置；
3) 用 Maxs/Mins 裁剪到 tile 范围，得到最终 stH/edH/cover 写出。

### Arange 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Cast | 以 int8_t 起始值生成递增索引，循环内按 8/16 步进作 Gather 抽取 scale 行的索引源 | __VEC_SCOPE__ |
| broadcast_gradient_args | AR, Adds, Cast, ClearSpr | 以 0 起始生成连续索引，循环内 Adds 叠加块偏移得全局索引，配合 GatherMask 按掩码输出 | __aicore__ |
| pool_3d_common | AddrReg, CreateAddrReg, CreateMask, DataCopy | 按循环偏移生成连续索引，Div/Sub 分解为 D/H/W 窗口坐标，配合 AddrReg 定位输出 | __aicore__ |
| pool_3d_common | AddrReg, Cast, CreateAddrReg, CreateMask | 通道广播分支中以 0 起始生成 int32_t 索引，Div 通道数得通道内偏移 | __aicore__ |
| cumsum | Add, Adds, Copy, CreateMask | 以 0 起始生成连续索引重置 scatter 索引，Adds 叠加相位偏移得全局源/目索引 | __VEC_SCOPE__ |
| cross_entropy_loss_grad | Add, AddrReg, Cast, CreateAddrReg | 以 0 起始生成索引并乘类别对齐长度的行步进偏移，叠加 target 索引做 Gather/Scatter | __VEC_SCOPE__ |
| embedding_dense_grad | AR, ClearSpr, Compare, DataCopy | 按循环偏移生成连续 orderReg 序号，Compare 找段边界后 GatherMask 抽取段首序号 | __aicore__ |
| non_zero | AR, Adds, ClearSpr, CreateMask | 以 startIdx 起始生成连续索引，循环 Adds 偏移推进，掩码拆分 GatherMask 输出非零位置 | __VEC_SCOPE__ |
| segment_sum | AR, ClearSpr, Compare, DataCopy | 按循环偏移生成连续 orderReg 序号，Compare 相邻段 ID 找边界，GatherMask 输出段首序号 | __VEC_SCOPE__ |
| cross_entropy_loss | Add, Cast, CompareScalar, CreateMask | 以 0 起始生成索引乘 rAlign 行步进，叠加 target 索引做 log_prob 的 Gather | __VEC_SCOPE__ |
| arg_max_with_value | Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost | 以 0 起始生成 0..63 索引，Muls dimNextA 缩放为维度跨步索引作 argmax 比较基准 | __VEC_SCOPE__ |
| scatter_nd | AR, ClearSpr, Compare, DataCopyUnAlign | 按循环偏移生成连续 orderReg 序号，Compare 相邻排序索引找唯一边界，GatherMask 输出 | __simd_vf__ |
| sparse_slice | Add, CreateMask, DataCopy, DataCopyScatter | 显式 <int32_t> 按循环偏移生成源索引，Div/Sub 分解行列偏移，UnPack 后 DataCopyScatter 散写 | __VEC_SCOPE__ |
| gather_elements | Add, Copy, CreateMask, DataCopy | 按偏移类型分支生成 int16_t/int32_t 索引，循环推进起始值，Div stride 得组内偏移 | __aicore__ |
| adaptive_avg_pool2d_grad | Add, Adds, CreateMask, DataCopy | 以 hBaseIdx 起始生成高度连续索引，Mul/Div/Add 计算输出行起止覆盖，Maxs/Mins 裁剪到 tile | __VEC_SCOPE__ |
