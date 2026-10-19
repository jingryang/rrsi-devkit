# AddrReg

**页面ID:** atlasascendc_api_07_0317  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0317.html

---

#### 功能说明

AddrReg即为Address Register（地址寄存器），是用于存储地址偏移量的寄存器。AddrReg应该通过CreateAddrReg API初始化，然后在循环之中使用AddrReg存储地址偏移量。AddrReg在每层循环中根据所设置的stride进行自增。

#### 函数原型

```
// offset = index0 * stride0
template <typename T>
__simd_callee__ inline AddrReg CreateAddrReg(uint16_t index0, uint32_t stride0);

// offset = index0 * stride0 + index1 * stride1
template <typename T>
__simd_callee__ inline AddrReg CreateAddrReg(uint16_t index0, uint32_t stride0, uint16_t index1, uint32_t stride1);

// offset = index0 * stride0 + index1 * stride1 + index2 * stride2
template <typename T>
__simd_callee__ inline AddrReg CreateAddrReg(uint16_t index0, uint32_t stride0, uint16_t index1, uint32_t stride1, uint16_t index2, uint32_t stride2);

// offset = index0 * stride0 + index1 * stride1 + index2 * stride2 + index3 * stride3
template <typename T>
__simd_callee__ inline AddrReg CreateAddrReg(uint16_t index0, uint32_t stride0, uint16_t index1, uint32_t stride1, uint16_t index2, uint32_t stride2, uint16_t index3, uint32_t stride3);
```

#### 参数说明

| **参数** | **含义** |
| --- | --- |
| T | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| index0 | 计算偏移量时作为轴1（偏移量计算公式参考注释）。 |
| index1 | 计算偏移量时作为轴2（偏移量计算公式参考注释）。 |
| index2 | 计算偏移量时作为轴3（偏移量计算公式参考注释）。 |
| index3 | 计算偏移量时作为轴4（偏移量计算公式参考注释）。 |
| stride0 | 地址偏移量1 |
| stride1 | 地址偏移量2 |
| stride2 | 地址偏移量3 |
| stride3 | 地址偏移量4 |

#### 支持的型号

Atlas 350 加速卡

#### 约束说明

无

#### 调用示例

```
__simd_vf__ inline void CreateAddrRegVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<T>();
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        AscendC::Reg::LoadAlign(mask, srcAddr, aReg);
        AscendC::Reg::StoreAlign(dstAddr, mask, aReg);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 AddrReg 实例

### 实例 1：clipped_swiglu::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Div, Exp, LoadDist, MaskPattern, MaskReg, Maxs, Mins, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **AddrReg 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 clipped_swiglu 算子的双层 VF 循环中，用 4 参数 CreateAddrReg 计算 (dim0, dim1) 二维偏移，驱动 act 与 gate 两路数据的 DataCopy 加载。

（行 350-389）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<T> vregX1;
    AscendC::Reg::RegTensor<T> vregX2;
    AscendC::Reg::RegTensor<float> vregX1F;
    AscendC::Reg::RegTensor<float> vregX2F;

    AscendC::Reg::RegTensor<float> vregX1DeF;
    AscendC::Reg::RegTensor<float> vregX2DeF;
    AscendC::Reg::RegTensor<float> minsReg;
    AscendC::Reg::RegTensor<float> mulsReg;
    AscendC::Reg::RegTensor<float> expReg;
    AscendC::Reg::RegTensor<float> addsReg;
    AscendC::Reg::RegTensor<float> sigmoidReg;
    AscendC::Reg::RegTensor<float> outFReg;
    AscendC::Reg::RegTensor<T> outTReg;
    Reg::MaskReg mask = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
    Reg::MaskReg maskT = Reg::UpdateMask<float>(tail);
    for (uint16_t dim0vfLoopIdx = 0; dim0vfLoopIdx < dim0VfTimes; dim0vfLoopIdx++) {
        for (uint16_t dim1vfLoopIdx = 0; dim1vfLoopIdx < dim1VfTimes; dim1vfLoopIdx++) {
            AscendC::Reg::AddrReg srcIdxOffset = AscendC::Reg::CreateAddrReg<T>(
                dim0vfLoopIdx, alignDim1In, dim1vfLoopIdx, vfLen);
            if constexpr (isInterleaved) {
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
```

**要点**: ①4 参数形式 CreateAddrReg<T>(i, stride0, j, stride1) 计算 offset = i*stride0 + j*stride1，用于二维 block 索引；②与 LoadDist::DIST_UNPACK_B16 配合把 bfloat16/half 拆包加载到 32 位寄存器；③同一 srcIdxOffset 复用于 act 和 gate 两路加载，节省地址寄存器。

### 实例 2：pool_3d_common::ComputeDivisorImplB64

- **来源类型**: `__aicore__`
- **共现 API**: Arange, CreateAddrReg, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Div, Duplicate, MaskPattern, MaskReg, Mul, RegTensor, RegTraitNumTwo, Sub, UnalignReg, UpdateMask
- **AddrReg 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 3D 池化的除数预计算函数中，AddrReg 按 oneRegLength 步长遍历输出平面，把 d/h/w 窗口坐标经运算后写回 UB。

（行 1002-1041）

```cpp
__aicore__ inline void ComputeDivisorImplB64(__local_mem__ float* divAddr, const CalcDivisorParam& param, int32_t start,
                                             int32_t total)
{
    __local_mem__ float* dstAddr = divAddr;
    int64_t oneRegLength = platform::GetVRegSize() / sizeof(float32_t);
    int32_t oneBatchOut = param.outD * param.outH * param.outW;
    int32_t outPlane = param.outH * param.outW;
    int64_t totalNum = total;
    uint16_t loopNum = ops::CeilDiv(totalNum, oneRegLength);
    int64_t kD = param.kD;
    int64_t kH = param.kH;
    int64_t kW = param.kW;
    int64_t sD = param.sD;
    int64_t sH = param.sH;
    int64_t sW = param.sW;

    int64_t negFrontPad = -1 * param.frontPad;
    int64_t dInAndBackendPad = param.dIn + param.backendPad;
    int64_t negTopPad = -1 * param.topPad;
    int64_t hInAndBottomPad = param.hIn + param.bottomPad;
    int64_t negLeftPad = -1 * param.leftPad;
    int64_t wInAndRightPad = param.wIn + param.rightPad;
    int64_t dIn = param.dIn;
    int64_t hIn = param.hIn;
    int64_t wIn = param.wIn;
    int64_t outW = param.outW;
    int64_t outH = param.outH;
    __VEC_SCOPE__
    {
        using RegDstT = typename Reg::RegTensor<int64_t, Reg::RegTraitNumTwo>;
        RegDstT v0;
        RegDstT v1;
        RegDstT v2;
        RegDstT v3;
        RegDstT v4;

        RegDstT vd0;
        RegDstT vd1;
        RegDstT vd2;
        RegDstT vd3;
```

**要点**: ①RegTraitNumTwo 配合 RegTensor<int64_t> 表示双字寄存器，AddrReg 按其步长寻址；②CreateAddrReg 的 stride 取 oneRegLength = GetVRegSize()/sizeof(float32_t)，与 VF 长度对齐；③同一函数内对 d/h/w 三个维度复用 AddrReg 模式分别写回。

### 实例 3：avg_pool::AvgPoolDivBatchV1

- **来源类型**: `__aicore__`
- **共现 API**: Arange, Cast, CreateAddrReg, CreateMask, DataCopy, DataCopyGather, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Div, Duplicate, MaskPattern, MaskReg, Pack, RegTensor, UnalignReg, UpdateMask
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 avg_pool 的批量归一化分支中，用 2 参数 CreateAddrReg 按批次内序号 j 寻址除数表 divAddr，配合 DataCopyGather 实现通道广播除法。

（行 1149-1188）

```cpp
__aicore__ inline void AvgPoolDivBatchV1(__local_mem__ T* dstAddr, __local_mem__ float32_t* srcAddr,
                                         __local_mem__ float32_t* divAddr, uint32_t batchNum, uint32_t batchElement,
                                         uint32_t channel = 1)
{
    uint32_t oneRegChannel = Ops::Base::GetVRegSize() / sizeof(float32_t) / channel;
    uint16_t oneRegNum = oneRegChannel * channel;
    uint16_t loopNum = batchElement / oneRegChannel;
    uint16_t tailNum = (batchElement - loopNum * oneRegChannel) * channel;
    uint16_t loopBatch = batchNum;
    __VEC_SCOPE__
    {
        Reg::RegTensor<float32_t> src;
        Reg::RegTensor<float32_t> div;
        Reg::RegTensor<float32_t> tmp;
        Reg::RegTensor<T> res;
        Reg::RegTensor<uint32_t> index;
        Reg::UnalignReg u0, u1;
        auto curSrcAddr = srcAddr;
        auto curDstAddr = dstAddr;

        uint32_t mainSreg = oneRegNum;
        uint32_t tailSreg = tailNum;
        Reg::MaskReg pMask = Reg::UpdateMask<float32_t>(mainSreg);
        Reg::MaskReg pMaskTail = Reg::UpdateMask<float32_t>(tailSreg);
        Reg::DataCopyUnAlignPre(u0, curSrcAddr);
        if constexpr (CHANNEL_BROADACAST) {
            Reg::Arange((Reg::RegTensor<int32_t>&)index, 0);
            Reg::RegTensor<uint32_t> channelDiv;
            Reg::MaskReg p0 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
            Reg::Duplicate(channelDiv, channel, p0);
            Reg::Div(index, index, channelDiv, p0);
        }
        for (uint16_t i = 0; i < loopBatch; i++) {
            uint32_t sreg = batchElement;
            for (uint16_t j = 0; j < loopNum; j++) {
                Reg::AddrReg divOffset = Reg::CreateAddrReg<float32_t>(j, oneRegNum);
                Reg::DataCopyUnAlign(src, u0, curSrcAddr, oneRegNum);
                if constexpr (CHANNEL_BROADACAST) {
                    Reg::DataCopyGather(div, divAddr + j * oneRegChannel, index, pMask);
                } else {
```

**要点**: ①2 参数形式 CreateAddrReg<float32_t>(j, oneRegNum) 计算 offset = j*oneRegNum，一维顺序寻址；②与 DataCopyGather + Arange 构造的 index 寄存器配合实现 channel broadcast 取数；③CHANNEL_BROADACAST 编译期分支决定是否构造 index 做 gather，否则直接顺序 DataCopy。

### 实例 4：gather_nd::FixIndicesVfCoreVf

- **来源类型**: `__simd_vf__`
- **共现 API**: Add, Adds, Compare, CreateAddrReg, CreateMask, DataCopy, DataCopyGather, Duplicate, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Muls, RegTensor, RegTraitNumTwo, UpdateMask
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 gather_nd 的索引修正核函数中，AddrReg 承载索引起始偏移，配合 Adds 递推 curIndex 并经 DataCopyGather 聚合，用 MaskOr 累积越界掩码。

（行 92-131）

```cpp
__simd_vf__ inline void FixIndicesVfCoreVf(__ubuf__ T2* indicesAddr, __ubuf__ T3* maxGatherShapeAddr,
                                           __ubuf__ T3* strideShapeAddr, uint16_t computeSizeT3, uint16_t repeatimes,
                                           uint32_t repeatStride, __ubuf__ uint32_t* helpAddr, int32_t indicesNumPro,
                                           uint16_t rank, T3 aMergeAxisSize)
{
    AscendC::Reg::RegTensor<uint32_t> indexStart;
    AscendC::Reg::RegTensor<uint32_t> curIndex;

    AscendC::Reg::RegTensor<T3> zeroConstReg;
    AscendC::Reg::RegTensor<T3> upLimitConstReg;
    AscendC::Reg::Duplicate(zeroConstReg, T3(0));

    AscendC::Reg::RegTensor<T3> indicesResReg;
    AscendC::Reg::RegTensor<T3> tmpReg;
    AscendC::Reg::RegTensor<T3> curIndicesReg;
    AscendC::Reg::MaskReg tmpMask;
    AscendC::Reg::MaskReg pregAll = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::ALL>();
    uint32_t indicesMask = indicesNumPro;
    uint32_t indicesMaskU32 = indicesNumPro;

    AscendC::Reg::DataCopy<uint32_t>(indexStart, helpAddr);

    for (uint16_t i = 0; i < repeatimes; i++) {
        uint32_t indicesOffset = i * repeatStride;
        AscendC::Reg::Duplicate(indicesResReg, T3(0));

        AscendC::Reg::MaskReg preg = AscendC::Reg::UpdateMask<T3>(indicesMask);
        AscendC::Reg::MaskReg pregT2 = GenT2Mask<T2, T3>(indicesMaskU32);
        AscendC::Reg::MaskReg
            overstepMask = AscendC::Reg::CreateMask<T3, AscendC::Reg::MaskPattern::ALLF>();
        for (uint16_t k = 0; k < rank; k++) {
            AscendC::Reg::Adds(curIndex, indexStart, (indicesOffset + k), pregAll);

            if constexpr (std::is_same<T3, int32_t>::value && std::is_same<T2, int32_t>::value) {
                AscendC::Reg::DataCopyGather(curIndicesReg, indicesAddr, curIndex, pregT2);
            } else if constexpr (std::is_same<T3, int32_t>::value && std::is_same<T2, int64_t>::value) {
                AscendC::Reg::RegTensor<T2, AscendC::Reg::RegTraitNumTwo> curIndicesRegTwo;
                AscendC::Reg::DataCopyGather(curIndicesRegTwo, indicesAddr, curIndex, pregT2);
                curIndicesReg = (AscendC::Reg::RegTensor<T3>&)curIndicesRegTwo.reg[0];
            } else if constexpr (std::is_same<T3, int64_t>::value && std::is_same<T2, int64_t>::value) {
```

**要点**: ①AddrReg 承载 indexStart 起始偏移，配合 Adds 递推 curIndex；②MaskMergeMode + MaskOr 累积越界掩码 overstepMask，用于后续屏蔽；③RegTraitNumTwo 分支处理 int64_t 索引与 int32_t 索引的 DataCopyGather 类型适配。

### 实例 5：cross_entropy_loss_grad::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Arange, Cast, CreateAddrReg, CreateMask, DataCopy, DataCopyGather, DataCopyScatter, Duplicate, MaskPattern, MaskReg, Mul, Pack, RegTensor, Sub, UpdateMask
- **AddrReg 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在交叉熵梯度反向中，为 target 和 grad 各建一个 2 参数 AddrReg（模板类型分别为 T2 与 float），驱动 DataCopy 取数与 DataCopyScatter 散播回写。

（行 319-358）

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
```

**要点**: ①同一循环内声明两个 AddrReg（srcOffset/outOffset），模板类型按目标张量元素类型选择（T2 vs float）；②int64_t target 需 Pack 成 uint32_t 再做 DataCopyGather；③DataCopyScatter 用相同 AddrReg 把梯度写回 xGradTmp 对应位置。

### 实例 6：sparse_softmax_cross_entropy_with_logits::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, Copy, CreateAddrReg, CreateMask, DataCopy, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, Max, ReduceMax, RegTensor, StoreDist, UnPack, UpdateMask
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在稀疏 softmax 交叉熵的 max 归约阶段，用 4 参数 CreateAddrReg 按二维 (i, j) 寻址 featuresAddr，循环取数做逐块 Max 累积。

（行 344-383）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<T1> featuresReg1;
    AscendC::Reg::RegTensor<float> maxReg;
    AscendC::Reg::RegTensor<T1> featuresReg;
    AscendC::Reg::RegTensor<T1> featuresRegLowest;
    AscendC::Reg::RegTensor<T1> featuresRegHighest;
    AscendC::Reg::RegTensor<float> featuresRegLowest32;
    AscendC::Reg::RegTensor<float> featuresRegHighest32;
    AscendC::Reg::RegTensor<float> maxRegTemp;

    AscendC::Reg::MaskReg pregMain = AscendC::Reg::CreateMask<T1, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg preg = AscendC::Reg::UpdateMask<T1>(tailNum);
    AscendC::Reg::MaskReg
        pregReduce = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg mergePreg = AscendC::Reg::CreateMask<float, MaskPattern::VL1>();
    AscendC::Reg::MaskReg comparePreg;

    for (uint16_t i = 0; i < aTimes; i++) {
        AscendC::Reg::Duplicate(featuresReg, minVal);
        AscendC::Reg::DataCopy(featuresReg1, featuresAddr + i * rAlign + repeatTimes * vfLen);
        AscendC::Reg::Max(featuresReg1, featuresReg, featuresReg1, preg);
        AscendC::Reg::Copy<T1, AscendC::Reg::MaskMergeMode::MERGING>(featuresReg, featuresReg1, preg);
        for (uint16_t j = 0; j < repeatTimes; j++) {
            AscendC::Reg::AddrReg offset = AscendC::Reg::CreateAddrReg<T1>(i, rAlign, j, vfLen);
            AscendC::Reg::DataCopy(featuresReg1, featuresAddr1, offset);
            AscendC::Reg::Max(featuresReg, featuresReg1, featuresReg, pregMain);
        }
        if constexpr (sizeof(T1) == 2) {
            AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::LOWEST>(
                (AscendC::Reg::RegTensor<int32_t>&)featuresRegLowest,
                (AscendC::Reg::RegTensor<int16_t>&)featuresReg);
            AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::HIGHEST>(
                (AscendC::Reg::RegTensor<int32_t>&)featuresRegHighest,
                (AscendC::Reg::RegTensor<int16_t>&)featuresReg);
            AscendC::Reg::Cast<float, T1, castB16ToB32>(featuresRegLowest32, featuresRegLowest, pregReduce);
            AscendC::Reg::Cast<float, T1, castB16ToB32>(featuresRegHighest32, featuresRegHighest, pregReduce);
            AscendC::Reg::Max(maxRegTemp, featuresRegLowest32, featuresRegHighest32, pregReduce);
            AscendC::Reg::ReduceMax(maxReg, maxRegTemp, pregReduce);
        } else {
```

**要点**: ①4 参数形式用于二维 (batch, repeat) 寻址，offset = i*rAlign + j*vfLen；②b16 类型走 UnPack HIGHEST/LOWEST 拆成两个 int32 再 Cast float 做 ReduceMax；③Copy<MERGING> 在尾块合并 max 结果保持尾部干净。

### 实例 7：cross_entropy_loss::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, Copy, CreateAddrReg, CreateMask, DataCopy, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, Max, ReduceMax, RegTensor, StoreDist, UnPack, UpdateMask
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在交叉熵前向的 max 归约中，用 4 参数 CreateAddrReg 按 (i, j) 二维寻址 inputAddr，逐 VF 块取数做 Max 累积。

（行 549-588）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<T1> inputReg1;
    AscendC::Reg::RegTensor<float> maxReg;
    AscendC::Reg::RegTensor<T1> inputReg;
    AscendC::Reg::RegTensor<T1> inputRegLowest;
    AscendC::Reg::RegTensor<T1> inputRegHighest;
    AscendC::Reg::RegTensor<float> inputRegLowest32;
    AscendC::Reg::RegTensor<float> inputRegHighest32;
    AscendC::Reg::RegTensor<float> maxRegTemp;

    AscendC::Reg::MaskReg pregMain = AscendC::Reg::CreateMask<T1, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg preg = AscendC::Reg::UpdateMask<T1>(tailNum);
    AscendC::Reg::MaskReg
        pregReduce = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg mergePreg = AscendC::Reg::CreateMask<float, MaskPattern::VL1>();
    AscendC::Reg::MaskReg comparePreg;

    for (uint16_t i = 0; i < aTimes; i++) {
        AscendC::Reg::Duplicate(inputReg, minValue);
        AscendC::Reg::DataCopy(inputReg1, inputAddr + i * AlignC + repeatTimes * vfLen);
        AscendC::Reg::Max(inputReg1, inputReg, inputReg1, preg);
        AscendC::Reg::Copy<T1, AscendC::Reg::MaskMergeMode::MERGING>(inputReg, inputReg1, preg);
        for (uint16_t j = 0; j < repeatTimes; j++) {
            AscendC::Reg::AddrReg offset = AscendC::Reg::CreateAddrReg<T1>(i, AlignC, j, vfLen);
            AscendC::Reg::DataCopy(inputReg1, inputAddr1, offset);
            AscendC::Reg::Max(inputReg, inputReg1, inputReg, pregMain);
        }
        if constexpr (sizeof(T1) == 2) {
            AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::LOWEST>(
                (AscendC::Reg::RegTensor<int32_t>&)inputRegLowest,
                (AscendC::Reg::RegTensor<int16_t>&)inputReg);
            AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::HIGHEST>(
                (AscendC::Reg::RegTensor<int32_t>&)inputRegHighest,
                (AscendC::Reg::RegTensor<int16_t>&)inputReg);
            AscendC::Reg::Cast<float, T1, castB16ToB32>(inputRegLowest32, inputRegLowest, pregReduce);
            AscendC::Reg::Cast<float, T1, castB16ToB32>(inputRegHighest32, inputRegHighest, pregReduce);
            AscendC::Reg::Max(maxRegTemp, inputRegLowest32, inputRegHighest32, pregReduce);
            AscendC::Reg::ReduceMax(maxReg, maxRegTemp, pregReduce);
        } else {
```

**要点**: ①与 sparse_softmax 同构，stride 用 AlignC（对齐通道数）而非 rAlign；②b16 路径需 UnPack HIGHEST/LOWEST 双半再 ReduceMax；③Duplicate(inputReg, minValue) 初始化为极小值，保证首次 Max 取到真实值。

### 实例 8：softmax_cross_entropy_with_logits::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, Copy, CreateAddrReg, CreateMask, DataCopy, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, Max, ReduceMax, RegTensor, StoreDist, UnPack, UpdateMask
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 softmax 交叉熵的 max 归约阶段，用 4 参数 CreateAddrReg 按 (batch, repeat) 寻址 featuresAddr1，逐块取数做 Max 累积。

（行 356-395）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<T> featuresReg1;
    AscendC::Reg::RegTensor<float> maxReg;
    AscendC::Reg::RegTensor<T> featuresReg;
    AscendC::Reg::RegTensor<T> featuresRegLowest;
    AscendC::Reg::RegTensor<T> featuresRegHighest;
    AscendC::Reg::RegTensor<float> featuresRegLowest32;
    AscendC::Reg::RegTensor<float> featuresRegHighest32;
    AscendC::Reg::RegTensor<float> maxRegTemp;

    AscendC::Reg::MaskReg pregMain = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg preg = AscendC::Reg::UpdateMask<T>(tailNum);
    AscendC::Reg::MaskReg
        pregReduce = AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg mergePreg = AscendC::Reg::CreateMask<float, MaskPattern::VL1>();
    AscendC::Reg::MaskReg comparePreg;

    for (uint16_t i = 0; i < aTimes; i++) {
        AscendC::Reg::Duplicate(featuresReg, minValue);
        AscendC::Reg::DataCopy(featuresReg1, featuresAddr + i * rAlign + repeatTimes * vfLen);
        AscendC::Reg::Max(featuresReg1, featuresReg, featuresReg1, preg);
        AscendC::Reg::Copy<T, AscendC::Reg::MaskMergeMode::MERGING>(featuresReg, featuresReg1, preg);
        for (uint16_t j = 0; j < repeatTimes; j++) {
            AscendC::Reg::AddrReg offset = AscendC::Reg::CreateAddrReg<T>(i, rAlign, j, vfLen);
            AscendC::Reg::DataCopy(featuresReg1, featuresAddr1, offset);
            AscendC::Reg::Max(featuresReg, featuresReg1, featuresReg, pregMain);
        }
        if constexpr (sizeof(T) == 2) {
            AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::LOWEST>(
                (AscendC::Reg::RegTensor<int32_t>&)featuresRegLowest,
                (AscendC::Reg::RegTensor<int16_t>&)featuresReg);
            AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::HIGHEST>(
                (AscendC::Reg::RegTensor<int32_t>&)featuresRegHighest,
                (AscendC::Reg::RegTensor<int16_t>&)featuresReg);
            AscendC::Reg::Cast<float, T, castB16ToB32>(featuresRegLowest32, featuresRegLowest, pregReduce);
            AscendC::Reg::Cast<float, T, castB16ToB32>(featuresRegHighest32, featuresRegHighest, pregReduce);
            AscendC::Reg::Max(maxRegTemp, featuresRegLowest32, featuresRegHighest32, pregReduce);
            AscendC::Reg::ReduceMax(maxReg, maxRegTemp, pregReduce);
        } else {
```

**要点**: ①4 参数二维寻址 offset = i*rAlign + j*vfLen；②Copy<MERGING> 在尾块保留有效元素、屏蔽尾部 padding；③b16 与 float 的 if constexpr 分支统一用同一 AddrReg 寻址。

### 实例 9：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, CreateAddrReg, CreateMask, DataCopy, Div, Exp, LoadDist, MaskPattern, MaskReg, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **AddrReg 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在双轴 swiglu 量化中，为加载和存储各建一个 4 参数 AddrReg（stride 分别为 alignDim1In 与 outAllNum），驱动 act/gate 读取与 swiglu 结果写回。

（行 588-627）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<xDtype> vregAct;
    Reg::RegTensor<xDtype> vregGate;
    Reg::RegTensor<float> vregActF;
    Reg::RegTensor<float> vregGateF;
    Reg::RegTensor<float> negReg;
    Reg::RegTensor<float> expReg;
    Reg::RegTensor<float> addsReg;
    Reg::RegTensor<float> sigmoidReg;
    Reg::RegTensor<float> outFReg;
    Reg::RegTensor<xDtype> outTReg;

    Reg::MaskReg mask = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
    Reg::MaskReg mask1 = Reg::UpdateMask<float>(mask1Num);
    Reg::MaskReg mask2 = Reg::UpdateMask<float>(mask2Num);
    Reg::MaskReg mask3 = Reg::UpdateMask<xDtype>(mask3Num);

    for (uint16_t dim0vfLoopIdx = 0; dim0vfLoopIdx < dim0VfTimes; dim0vfLoopIdx++) {
        // Full VF iterations (no tail)
        for (uint16_t dim1vfLoopIdx = 0; dim1vfLoopIdx < dim1VfTimes; dim1vfLoopIdx++) {
            Reg::AddrReg srcIdxOffset = Reg::CreateAddrReg<xDtype>(dim0vfLoopIdx, alignDim1In,
                                                                             dim1vfLoopIdx, 64);
            Reg::DataCopy<xDtype, Reg::LoadDist::DIST_UNPACK_B16>(vregAct, actAddr, srcIdxOffset);
            Reg::DataCopy<xDtype, Reg::LoadDist::DIST_UNPACK_B16>(vregGate, gateAddr, srcIdxOffset);

            Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(vregActF, vregAct, mask);
            Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(vregGateF, vregGate, mask);

            Reg::Muls(negReg, vregActF, negScalarOne, mask);
            Reg::Exp(expReg, negReg, mask);
            Reg::Adds(addsReg, expReg, scalarOne, mask);
            Reg::Div(sigmoidReg, vregActF, addsReg, mask);
            Reg::Mul(outFReg, sigmoidReg, vregGateF, mask);

            Reg::Cast<xDtype, float, CAST_FP32_TO_FP16_BF16>(outTReg, outFReg, mask);
            Reg::AddrReg outOffset = Reg::CreateAddrReg<xDtype>(dim0vfLoopIdx, outAllNum, dim1vfLoopIdx,
                                                                          64);
            DataCopy<xDtype, Reg::StoreDist::DIST_PACK_B32>(swigluOutAddr, outTReg, outOffset, mask);
        }
```

**要点**: ①同一迭代声明 srcIdxOffset 与 outOffset 两个 AddrReg，输入输出步长不同（64 对齐输入 vs outAllNum 输出）；②LoadDist::DIST_UNPACK_B16 加载 + StoreDist::DIST_PACK_B32 存储，AddrReg 同时承载两端偏移；③UpdateMask 的 mask1/2/3 处理尾部三段对齐。

### 实例 10：flat_quant::QuantVf

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, CastTrait, CreateAddrReg, DataCopy, Interleave, LoadDist, MaskMergeMode, MaskReg, Mul, PostLiteral, RegLayout, RegTensor, SatMode, StoreDist, UpdateMask
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 flat_quant 的量化核函数中，循环外声明 AddrReg aReg，循环内用 2 参数 CreateAddrReg 按块序号 i 重新计算偏移，配合 POST_MODE_UPDATE 自增搬运。

（行 542-581）

```cpp
static __simd_vf__ inline void QuantVf(__ubuf__ int8_t* dstPtr, __ubuf__ bfloat16_t* srcPtr,
                                       __ubuf__ uint16_t* src2Ptr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::MaskReg dataMask1;
    AscendC::Reg::MaskReg dataMask2;
    AscendC::Reg::RegTensor<uint16_t> halfScaleForMul;
    AscendC::Reg::RegTensor<bfloat16_t> vdExp0;
    AscendC::Reg::RegTensor<bfloat16_t> vdExp1;
    AscendC::Reg::RegTensor<bfloat16_t> vdExp0Convert;
    AscendC::Reg::RegTensor<bfloat16_t> vdExp1Convert;

    AscendC::Reg::RegTensor<bfloat16_t> vdExp0BF16;
    AscendC::Reg::RegTensor<bfloat16_t> vdExp1Bf16;

    AscendC::Reg::RegTensor<fp4x2_e2m1_t> vdExp0FP4;
    AscendC::Reg::RegTensor<fp4x2_e2m1_t> vdExp1FP4;

    AscendC::Reg::RegTensor<bfloat16_t> vdBf16Exp0FP4;
    AscendC::Reg::RegTensor<bfloat16_t> vdBf16Exp1FP4;

    AscendC::Reg::AddrReg aReg;
    static constexpr AscendC::Reg::CastTrait castTrait = {
        AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::UNKNOWN,
        AscendC::Reg::MaskMergeMode::ZEROING, AscendC::RoundMode::CAST_RINT};
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
```

**要点**: ①AddrReg 在循环外声明、循环内赋值，配合 PostLiteral::POST_MODE_UPDATE 让 DataCopy 自增源地址；②CastTrait 结构体（RegLayout/SatMode/MaskMergeMode/RoundMode）作为 Cast 模板参数固化量化策略；③Interleave 在量化前重排 bf16 数据，AddrReg 寻址与重排解耦。

### 实例 11：tensor_equal::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Compare, CreateAddrReg, CreateMask, DataCopy, Duplicate, HighLowPart, MaskOr, MaskPattern, MaskReg, MaskUnPack, ReduceMax, RegTensor, UnPack, UpdateMask
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 tensor_equal 中，用 2 参数 CreateAddrReg<uint8_t> 按块序号寻址 inputX/inputY，逐块 Compare 累积不等掩码，最终 ReduceMax 判等。

（行 128-166）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<InputType> xReg, yReg;
    AscendC::Reg::RegTensor<uint16_t> tmpU16Reg, tmpU16RegAdd;
    AscendC::Reg::RegTensor<uint32_t> tmpU32Reg;
    AscendC::Reg::AddrReg offSetReg;
    AscendC::Reg::MaskReg bakMaskRegHigh, bakMaskRegLow, maskReg, cmpMaskReg;
    AscendC::Reg::MaskReg
        allMaskReg = AscendC::Reg::CreateMask<uint8_t, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg
        bakMaskReg = AscendC::Reg::CreateMask<uint8_t, AscendC::Reg::MaskPattern::ALLF>();
    for (uint16_t i = 0; i < repeatTimes; i++) {
        offSetReg = AscendC::Reg::CreateAddrReg<uint8_t>(i, strideVReg);
        AscendC::Reg::DataCopy(xReg, inputXAddr, offSetReg);
        AscendC::Reg::DataCopy(yReg, inputYAddr, offSetReg);
        maskReg = AscendC::Reg::UpdateMask<uint8_t>(dataLenVf);
        AscendC::Reg::Compare<InputType, CMPMODE::NE>(cmpMaskReg, xReg, yReg, maskReg);
        AscendC::Reg::MaskOr(bakMaskReg, bakMaskReg, cmpMaskReg, allMaskReg);
    }
    if constexpr (std::is_same<InputType, uint8_t>::value) {
        AscendC::Reg::Duplicate(tmpU16Reg, 1);
        AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::HIGHEST>(bakMaskRegHigh, bakMaskReg);
        AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::LOWEST>(bakMaskRegLow, bakMaskReg);
        AscendC::Reg::ReduceMax(tmpU16RegAdd, tmpU16Reg, bakMaskRegHigh);
        AscendC::Reg::ReduceMax(tmpU16Reg, tmpU16Reg, bakMaskRegLow);
        AscendC::Reg::Add(tmpU16Reg, tmpU16Reg, tmpU16RegAdd, allMaskReg);
        AscendC::Reg::UnPack<uint32_t, uint16_t, AscendC::Reg::HighLowPart::LOWEST>(tmpU32Reg, tmpU16Reg);
        AscendC::Reg::DataCopy(resultAddr, tmpU32Reg, allMaskReg);
    } else if constexpr (std::is_same<InputType, half>::value) {
        AscendC::Reg::Duplicate(tmpU16Reg, 1);
        AscendC::Reg::ReduceMax(tmpU16Reg, tmpU16Reg, bakMaskReg);
        AscendC::Reg::UnPack<uint32_t, uint16_t, AscendC::Reg::HighLowPart::LOWEST>(tmpU32Reg, tmpU16Reg);
        AscendC::Reg::DataCopy(resultAddr, tmpU32Reg, allMaskReg);
    } else {
        AscendC::Reg::Duplicate(tmpU32Reg, 1);
        AscendC::Reg::ReduceMax(tmpU32Reg, tmpU32Reg, bakMaskReg);
        AscendC::Reg::DataCopy(resultAddr, tmpU32Reg, allMaskReg);
    }
}
```

**要点**: ①模板参数用 uint8_t（最小粒度），strideVReg 按 VF 长度对齐；②同一 offSetReg 复用于 x 和 y 两路 DataCopy；③MaskUnPack HIGHEST/LOWEST 把掩码拆半再 ReduceMax，适配 uint8_t/half/float 三种类型的判等归约。

### 实例 12：non_zero::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, Adds, ClearSpr, CreateAddrReg, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, GatherMask, GatherMaskMode, HighLowPart, MaskPack, MaskPattern, PostLiteral, UnalignReg
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 non_zero 的压缩输出阶段，用 2 参数 CreateAddrReg<int64_t> 按序号 i 寻址掩码块，配合 GatherMask 按 MaskHalf 聚合非零索引并自增写出。

（行 442-464）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::ClearSpr<SpecialPurposeReg::AR>();
    AscendC::Reg::UnalignReg ureg0;
    RegTensor<int32_t> vsqzReg;
    RegTensor<int32_t> idsReg;
    MaskReg maskReg, maskHalf;
    MaskReg preg;
    preg = AscendC::Reg::CreateMask<int32_t, AscendC::Reg::MaskPattern::ALL>();
    Arange(idsReg, scalar);
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::AddrReg offset = AscendC::Reg::CreateAddrReg<int64_t>(i, 4);
        AscendC::Reg::DataCopy(maskReg, maskUbPtr, offset);
        AscendC::Reg::MaskPack<Reg::HighLowPart::LOWEST>(maskHalf, maskReg);

        AscendC::Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(vsqzReg, idsReg, maskHalf);
        AscendC::Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(dstPtr, vsqzReg,
                                                                                             ureg0);

        AscendC::Reg::Adds(idsReg, idsReg, repeatElm, preg);
    }
    AscendC::Reg::DataCopyUnAlignPost(dstPtr, ureg0);
}
```

**要点**: ①stride=4 对应 int64_t 元素步长，AddrReg 模板类型与元素类型一致；②ClearSpr<SpecialPurposeReg::AR> 清零地址寄存器后用 DataCopyUnAlignPost 收尾非对齐写回；③MaskPack<LOWEST> 取掩码低半位配合 GatherMask<STORE_REG> 做压缩存储。

### 实例 13：max_pool_grad::ComputeSingleArgmax

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Arange, Compare, CreateAddrReg, CreateMask, Duplicate, LocalMemBar, MaskPattern, MaskReg, MaskXor, MemType, RegTensor, Select, UpdateMask
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 max_pool_grad 的 argmax 计算中，AddrReg 配合 Arange 生成的索引逐块取数比较，用 Select 与 MaskXor 更新最大值及其索引。

（行 330-369）

```cpp
__aicore__ inline void ComputeSingleArgmax(int64_t dataCount, int64_t curKw, int64_t curOriginIndex,
                                           int64_t bufferOffset)
{
    LocalTensor<T1> xLocal = inputQue_.DeQue<T1>();

    __local_mem__ T1* xLocalAddr = (__local_mem__ T1*)xLocal.GetPhyAddr();

    LocalTensor<int32_t> argmaxLocal = Base::argmaxBuf_.template Get<int32_t>();
    __local_mem__ int32_t* argmaxAddr = (__local_mem__ int32_t*)argmaxLocal.GetPhyAddr();

    LocalTensor<float> maxValLocal = maxValBuf_.template Get<float>();
    __local_mem__ float* maxValAddr = (__local_mem__ float*)maxValLocal.GetPhyAddr();

    const float negInf = AscendC::NumericLimits<float>::NegativeInfinity();

    constexpr uint32_t repeatElm = platform::GetVRegSize() / sizeof(float);
    const uint16_t repeatTimes = static_cast<uint16_t>((dataCount + repeatElm - 1) / repeatElm);
    uint32_t num = repeatTimes * repeatElm;
    const uint32_t padNum = num - dataCount;
    constexpr int32_t padIndex = -1;

    __VEC_SCOPE__
    {
        DuplicateNegInf<T1>(xLocalAddr, padNum, dataCount);

        Reg::RegTensor<float> res;
        Reg::RegTensor<int32_t> resIndex;
        Reg::RegTensor<int32_t> index;
        Reg::RegTensor<float> vd0;

        Reg::MaskReg nanMaskReg;
        Reg::MaskReg cmpMaskReg;
        Reg::MaskReg maskAll = Reg::CreateMask<float, Reg::MaskPattern::ALL>();

        Reg::Duplicate(resIndex, padIndex);
        Reg::Duplicate(res, negInf);
        Reg::Arange(index, 0);

        for (uint16_t i = 0; i < repeatTimes; ++i) {
            uint32_t maskNum = num;
```

**要点**: ①Duplicate(resIndex, padIndex=-1) + Duplicate(res, negInf) 初始化，AddrReg 承载逐块数据偏移；②MaskXor 累积本轮比较结果，配合 Select 原地更新 res/resIndex；③LocalMemBar<MemType> 在归约写回前插入内存屏障保证 UB 一致性。

### 实例 14：softplus_v2_grad::SoftplusV2GradVF

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, Compare, CreateAddrReg, Div, Exp, LoadAlign, MaskReg, Muls, Neg, RegTensor, Select, StoreAlign, Sub, UpdateMask
- **AddrReg 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在 softplus_v2_grad 的 VF 核函数中，用 AscendC::Reg 命名空间的 2 参数 CreateAddrReg<T> 按块序号 i 寻址，配合 LoadAlign/StoreAlign 完成加载与梯度写回。

（行 76-115）

```cpp
__simd_vf__ inline void SoftplusV2GradVF(__ubuf__ T* dst, __ubuf__ T* src0, __ubuf__ T* src1, uint32_t count,
                                         uint32_t VL, uint16_t rep, float beta, float threshold)
{
    // 寄存器声明
    AscendC::Reg::RegTensor<T> src0Reg, src1Reg;
    AscendC::Reg::RegTensor<T> regT1, regT2, regT3, regT4, regT5, dstReg;
    AscendC::Reg::RegTensor<T> regThresh;
    AscendC::Reg::MaskReg padMask;
    AscendC::Reg::MaskReg cmpMask;
    AscendC::Reg::AddrReg aReg;

    for (uint16_t i = 0; i < rep; i++) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, VL);
        padMask = AscendC::Reg::UpdateMask<T>(count);

        // --- Load: UB → Reg ---
        AscendC::Reg::LoadAlign(src0Reg, src0, aReg); // 读 input_features
        AscendC::Reg::LoadAlign(src1Reg, src1, aReg); // 读 input_gradients

        // S1: Mul(beta, input_features) → T1
        //     T1 = beta * input_features
        AscendC::Reg::Muls<T>(regT1, src0Reg, beta, padMask);

        // S2: Neg(T1) → T2
        AscendC::Reg::Neg<T>(regT2, regT1, padMask);

        // S3: Exp(T2) → T3
        AscendC::Reg::Exp<T>(regT3, regT2, padMask);

        // S4: Adds(T3, 1.0f) → T4
        AscendC::Reg::Adds<T>(regT4, regT3, static_cast<T>(1.0f), padMask);

        // S5: Div(input_gradients, T4) → T5
        AscendC::Reg::Div<T>(regT5, src1Reg, regT4, padMask);

        // S6: Sub(T1, T1) → regZero（零寄存器）
        AscendC::Reg::Sub<T>(regT2, regT1, regT1, padMask);

        // S7: Adds(regZero, threshold) → regThresh（阈值寄存器）
        AscendC::Reg::Adds<T>(regThresh, regT2, threshold, padMask);
```

**要点**: ①使用 AscendC::Reg:: 命名空间（区别于其他实例的 Reg），AddrReg 模板类型 T 与数据元素一致；②LoadAlign/StoreAlign 配合同一 aReg 实现对齐读写，stride=VL 为向量长度；③阈值分支用 Compare + Select 在寄存器内选择梯度或原值，AddrReg 仅负责寻址不参与计算。

### 实例 15：stateless_random_normal_v3::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Cast, CreateAddrReg, CreateMask, DataCopy, Duplicate, LoadDist, MaskPattern, MaskReg, Mul, RegTensor, StoreDist, UpdateMask
- **AddrReg 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义（待补充）**: 在正态随机数后处理中按类型分支：float 用单个 2 参数 AddrReg 寻址；b16 用 aRegT/aRegF 两个 AddrReg 分别按 T 与 float 步长寻址，做缩放叠加并写回。

（行 270-302）

```cpp
__VEC_SCOPE__
{
    if constexpr (AscendC::IsSameType<T, float>::value) {
        Reg::RegTensor<float> vRegY, vRegStdev, vRegTmp, vRegResult, vRegMean;
        Reg::MaskReg maskAll = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
        Reg::Duplicate(vRegMean, scaleMean, maskAll);
        for (uint16_t i = 0; i < looptimes; i++) {
            Reg::MaskReg curMask = Reg::UpdateMask<float>(Count);
            AscendC::Reg::AddrReg aReg = AscendC::Reg::CreateAddrReg<float>(i, loopsize);
            Reg::DataCopy(vRegY, yOutputAddr, aReg);
            Reg::DataCopy(vRegStdev, stdevAddr, aReg);
            Reg::Mul(vRegTmp, vRegY, vRegStdev, curMask);
            Reg::Add(vRegResult, vRegTmp, vRegMean, curMask);
            Reg::DataCopy(yOutputAddr, vRegResult, aReg, curMask);
        }
    } else {
        Reg::RegTensor<T> vRegY, vRegStdev, vRegTmp, vRegResult, vRegMean;
        Reg::RegTensor<float> vRegStdevF;
        Reg::MaskReg maskAll = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
        Reg::Duplicate(vRegMean, scaleMean, maskAll);
        for (uint16_t i = 0; i < looptimes; i++) {
            Reg::MaskReg curMask = Reg::UpdateMask<float>(Count);
            AscendC::Reg::AddrReg aRegT = AscendC::Reg::CreateAddrReg<T>(i, loopsize);
            AscendC::Reg::AddrReg aRegF = AscendC::Reg::CreateAddrReg<float>(i, loopsize);
            Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vRegY, yOutputAddr, aRegT);
            Reg::DataCopy(vRegStdevF, stdevAddr, aRegF);
            Reg::Cast<T, float, castTraitB32ToB16>(vRegStdev, vRegStdevF, curMask);
            Reg::Mul(vRegTmp, vRegY, vRegStdev, curMask);
            Reg::Add(vRegResult, vRegTmp, vRegMean, curMask);
            Reg::DataCopy<T, Reg::StoreDist::DIST_PACK_B32>(yOutputAddr, vRegResult, aRegT, curMask);
        }
    }
}
```

**要点**: ①float 路径单 AddrReg 复用于 yOutput/stdev 的读和结果写；②b16 路径声明 aRegT(T 步长) 与 aRegF(float 步长) 两个 AddrReg，因 stdev 是 float 需按 float 寻址再 Cast；③Duplicate(vRegMean, scaleMean) 广播均值，AddrReg 仅管地址，Mul/Add 完成仿射变换。

### AddrReg 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| clipped_swiglu | Adds, Cast, CreateAddrReg, CreateMask | 4参数二维偏移驱动 act/gate 双路 DataCopy 加载 + DeInterleave | __VEC_SCOPE__ |
| pool_3d_common | Arange, CreateAddrReg, CreateMask, DataCopy | int64_t 双字寄存器按 oneRegLength 步长写回 d/h/w 窗口坐标 | __aicore__ |
| avg_pool | Arange, Cast, CreateAddrReg, CreateMask | 2参数一维寻址除数表 + DataCopyGather 通道广播 | __aicore__ |
| gather_nd | Add, Adds, Compare, CreateAddrReg | AddrReg 承载索引偏移 + DataCopyGather 聚合 + MaskOr 累积越界掩码 | __simd_vf__ |
| cross_entropy_loss_grad | Add, Arange, Cast, CreateAddrReg | 双 AddrReg(T2/float) 驱动 DataCopy 取数 + DataCopyScatter 散播回写 | __VEC_SCOPE__ |
| sparse_softmax_cross_entropy_with_logits | Cast, Copy, CreateAddrReg, CreateMask | 4参数二维寻址 features + Max 逐块归约 + UnPack 拆半 | __VEC_SCOPE__ |
| cross_entropy_loss | Cast, Copy, CreateAddrReg, CreateMask | 4参数二维寻址 input + Max 归约 + Copy<MERGING> 尾块合并 | __VEC_SCOPE__ |
| softmax_cross_entropy_with_logits | Cast, Copy, CreateAddrReg, CreateMask | 4参数二维寻址 features + Max 归约 + b16/float 统一分支 | __VEC_SCOPE__ |
| swiglu_mx_quant_with_dual_axis | Adds, Cast, CreateAddrReg, CreateMask | 双 4参数 AddrReg(输入/输出不同步长) + LoadDist/StoreDist 配对 | __VEC_SCOPE__ |
| flat_quant | Cast, CastTrait, CreateAddrReg, DataCopy | 循环外声明+循环内赋值 + PostLiteral 自增搬运 + CastTrait 量化 | __simd_vf__ |
| tensor_equal | Add, Compare, CreateAddrReg, CreateMask | 2参数 uint8_t 寻址 + Compare 累积不等掩码 + MaskUnPack 归约判等 | __VEC_SCOPE__ |
| non_zero | AR, Adds, ClearSpr, CreateAddrReg | 2参数 int64_t stride=4 寻址掩码 + GatherMask 压缩非零索引 | __VEC_SCOPE__ |
| max_pool_grad | Adds, Arange, Compare, CreateAddrReg | AddrReg 配合 Arange 索引 + Select/MaskXor 更新 argmax | __aicore__ |
| softplus_v2_grad | Adds, Compare, CreateAddrReg, Div | Reg:: 命名空间 2参数寻址 + LoadAlign/StoreAlign 对齐读写 | __simd_vf__ |
| stateless_random_normal_v3 | Add, Cast, CreateAddrReg, CreateMask | 类型分支: float 单 AddrReg / b16 双 AddrReg(T+float) 仿射变换 | __VEC_SCOPE__ |

