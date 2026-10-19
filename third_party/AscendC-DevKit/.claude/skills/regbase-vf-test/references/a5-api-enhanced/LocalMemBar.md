# LocalMemBar

**页面ID:** atlasascendc_api_07_00231  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00231.html

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

Reg矢量计算宏函数内不同流水线之间的同步指令。该同步指令指定src源流水线和dst目的流水线，如下图所示，目的流水线将等待源流水线上所有指令完成才进行执行。读写场景下，当读指令使用的寄存器和写指令使用的寄存器相同时，可以触发寄存器保序，指令将会按照代码顺序执行，不需要插入同步指令，而当使用的寄存器不同时，如果要确保读写指令顺序执行，则需要插入同步指令，写写场景同理。

**图1 **流水线等待示意图
![](images/atlasascendc_api_07_00231_img_001.png)

#### 函数原型

```
template <MemType src, MemType dst> 
__simd_callee__ inline void LocalMemBar()
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| src | 源流水线，类型为MemType，具体参见表2 MemType取值说明。 |
| dst | 目的流水线，类型为MemType，具体参见表2 MemType取值说明。 |

**表2 **MemType取值说明

| MemType取值 | 含义 |
| --- | --- |
| VEC_STORE | SIMD_VF函数内矢量写UB流水线。 对应寄存器到UB的搬运指令，如StoreAlign、StoreUnAlign、Store。 |
| VEC_LOAD | SIMD_VF函数内矢量读UB流水线。 对应UB到寄存器的搬运指令，如LoadAlign、LoadUnAlign、Load。 |
| SCALAR_STORE | SIMD_VF函数内标量写UB流水线。 对应标量写入UB的指令，如Duplicate。 |
| SCALAR_LOAD | SIMD_VF函数内标量读UB流水线。 对应UB读取标量的指令，如GetValue。 |
| VEC_ALL | SIMD_VF函数内所有矢量读写UB流水线。 |
| SCALAR_ALL | SIMD_VF函数内所有标量读写UB流水线。 |

**表3 **src和dst组合取值说明

| src | dst |
| --- | --- |
| VEC_STORE | VEC_LOAD |
| VEC_LOAD | VEC_STORE |
| VEC_STORE | VEC_STORE |
| VEC_STORE | SCALAR_LOAD |
| VEC_STORE | SCALAR_STORE |
| VEC_LOAD | SCALAR_STORE |
| SCALAR_STORE | VEC_LOAD |
| SCALAR_STORE | VEC_STORE |
| SCALAR_LOAD | VEC_STORE |
| VEC_ALL | VEC_ALL |
| VEC_ALL | SCALAR_ALL |
| SCALAR_ALL | VEC_ALL |

#### 约束说明

无

#### 调用示例

如下示例中dstPtr和src0Ptr为同一个UB地址，for循环中第二次循环中读UB矢量搬运和第一次循环中写UB矢量搬运操作了同一块UB地址空间，因此第二次循环中读UB矢量搬运需要等待第一次循环中写UB矢量搬运执行完成后才能执行，需要插入VEC_LOAD等待VEC_STORE的同步。

```
template<typename T>
__simd_vf__ inline void AddVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;   
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE, AscendC::Reg::MemType::VEC_LOAD>();
        AscendC::Reg::LoadAlign(srcReg0, src0Addr);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Add(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 LocalMemBar 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **LocalMemBar 调用次数**: 3
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在动态 MX 量化按二分法求每行最大指数的归约中，先用 DataCopy 把寄存器里的 expMax 写回 UB，再插入 VEC_STORE→VEC_LOAD 同步，确保随后 DataCopyUnAlignPre 从同一 UB 地址读到的已是最新最大值，避免读到旧数据导致归约错误。

**片段 1** (行 466-482):

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(regLoop - 1); i++) {
    this->template LoadData<RoundMode::UNKNOWN, roundMode>(xAddr, i * dataLenSingleLoop, x, pnumMask);
    Reg::And(exp, (Reg::RegTensor<uint16_t>&)x, tmp16RegTensor, pnumMask);
    Reg::Max(expMax, expMax, exp, pnumMask);
}
this->template LoadData<RoundMode::UNKNOWN, roundMode>(xAddr, (regLoop - 1) * dataLenSingleLoop, x,
                                                       tailPnumMask);
Reg::And(exp, (Reg::RegTensor<uint16_t>&)x, tmp16RegTensor, tailPnumMask);
Reg::Max(exp, expMax, exp, tailPnumMask);
Reg::Copy<uint16_t, Reg::MaskMergeMode::MERGING>(expMax, exp, tailPnumMask);

// 二分法求rowsSingleLoop行中的最大行
Reg::DataCopy(maxExpAddr, expMax, pnumMask);
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
uint32_t maskNum = dataLenSingleLoop - expOffset;
Reg::MaskReg mask = Reg::UpdateMask<uint16_t>(maskNum);
Reg::DataCopyUnAlignPre(u0, maxExpAddr + expOffset);
```

**片段 2** (行 486-495):

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    Reg::DataCopy(maxExpAddr, expMax, pnumMask);
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
    expOffset /= DIGIT_TWO;
    maskNum = expOffset;
    mask = Reg::UpdateMask<uint16_t>(maskNum);
    Reg::DataCopyUnAlignPre(u0, maxExpAddr + expOffset);
    Reg::DataCopyUnAlign(exp, u0, maxExpAddr + expOffset);
    Reg::Max(expMax, expMax, exp, mask);
}
```

**片段 3** (行 547-559):

```cpp
for (uint16_t i = 0; i < rowsSingleLoop; i++) {
    Reg::DataCopyUnAlign(scaleAddr, reversedShareExpRegTensor, u1, dataLen);
    Reg::DataCopyUnAlignPost(scaleAddr, u1, 0);
}
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
Reg::DataCopy(reversedShareExpRegTensor, maxExpAddr);
mask = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
if constexpr (IsSame<T, half>::value) {
    Reg::Cast<float, bfloat16_t, castTraitZero>(
        reversedShareExpRegTensorFP32Zero, (Reg::RegTensor<bfloat16_t>&)reversedShareExpRegTensor, pnumMask);
    Reg::Cast<float, bfloat16_t, castTraitOne>(
        reversedShareExpRegTensorFP32One, (Reg::RegTensor<bfloat16_t>&)reversedShareExpRegTensor, pnumMask);
}
```

**要点**: ①同一 UB 地址先 StoreAlign/DataCopy 写后 LoadAlign/DataCopy 读，必须插 VEC_STORE→VEC_LOAD 同步；②二分归约每轮都重复"写 UB→同步→读 UB"模式，循环内同步不可省；③循环外把 scale 写回 UB 后，再次读回做 Cast 前也要插一次同步。

### 实例 2：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Compare, CreateMask, DataCopy, DeInterleave, Duplicate, LoadDist, MaskAnd, MaskPattern, MaskReg, MaskSel, MemType, ReduceSum, RegTensor, Select, StoreDist, UpdateMask
- **LocalMemBar 调用次数**: 2
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: sparse_slice 维度遍历中，先用 DataCopy 把 sliceStart/sliceEnd 边界按 DIST_BRC_B32 广播到寄存器，再插 VEC_STORE→VEC_LOAD 同步，保证随后循环里按 int64 indices 读 UB 时边界值已就绪；reduce 阶段把 b8 掩码打包结果写回 UB 后再插一次同步，确保 ReduceSum 读到最新掩码计数。

**片段 1** (行 462-517):

```cpp
for (uint16_t dim = 0; dim < rankNum; dim++) {
    uint32_t sreg0 = count;
    Reg::DataCopy<uint32_t, Reg::LoadDist::DIST_BRC_B32>(
        vregLowerBoundLowerHalf, (__ubuf__ uint32_t*)(sliceStartAddr) + dim * DIGIT_TWO);
    Reg::DataCopy<int32_t, Reg::LoadDist::DIST_BRC_B32>(
        vregLowerBoundHigherHalf, (__ubuf__ int32_t*)(sliceStartAddr) + dim * DIGIT_TWO + 1);
    Reg::DataCopy<uint32_t, Reg::LoadDist::DIST_BRC_B32>(
        vregUpperBoundLowerHalf, (__ubuf__ uint32_t*)(sliceEndAddr) + dim * DIGIT_TWO);
    Reg::DataCopy<int32_t, Reg::LoadDist::DIST_BRC_B32>(
        vregUpperBoundHigherHalf, (__ubuf__ int32_t*)(sliceEndAddr) + dim * DIGIT_TWO + 1);

    AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE,
                                   AscendC::Reg::MemType::VEC_LOAD>();
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
}
```

**片段 2** (行 518-528):

```cpp
// reduce part
AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE, AscendC::Reg::MemType::VEC_LOAD>();
uint32_t sreg0 = count;
Reg::DataCopy<int32_t, Reg::LoadDist::DIST_NORM>(vregCounterIn, (__ubuf__ int32_t*)(counterUbAddr));
for (uint16_t loopIndex = 0; loopIndex < loopNum; loopIndex++) {
    pregIndicesB32 = Reg::UpdateMask<int32_t>(sreg0);
    Reg::DataCopy<int8_t, Reg::LoadDist::DIST_UNPACK4_B8>(
        vregInMask, (__ubuf__ int8_t*)(maskUbAddr + loopIndex * vl));
    Reg::ReduceSum<int32_t>(reduceResult, (Reg::RegTensor<int32_t>&)vregInMask, pregIndicesB32);
    Reg::Add(vregCounterIn, vregCounterIn, reduceResult, pregB32First);
}
```

**要点**: ①边界常量广播写入寄存器后，读 indices 前必须插 VEC_STORE→VEC_LOAD 同步；②reduce 阶段掩码写回 UB 后再插同步，确保 ReduceSum 读到最新掩码；③配合 LoadDist::DIST_BRC_B32 / DIST_UNPACK4_B8 实现 int64 边界与 b8 掩码的高效处理。

### 实例 3：cumsum::Reg::Adds

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, Arange, Copy, CreateMask, DataCopyGather, DataCopyScatter, Div, Duplicate, MaskPattern, MaskReg, MemType, Muls, RegTensor, Sub, UpdateMask
- **LocalMemBar 调用次数**: 4
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: cumsum 分阶段累加中，DataCopyGather 读上轮结果 bakSrc 后插 VEC_LOAD→VEC_STORE 同步，确保随后 DataCopyScatter 写回 dstPtr 不与刚读的 gather 乱序；循环内每轮"读 UB→Add 累加→写回 UB"后再插 VEC_STORE→VEC_LOAD 同步，保证下一轮 gather 读到上一轮 scatter 的最新累加值。

**片段 1** (行 724-742):

```cpp
Reg::Muls(tmp2, tmp1, splitRASize, idxMask);
Reg::Muls(tmp1, tmp1, (RangeType)rightALen, idxMask); // tmp1 is i//k*k
Reg::Sub(gIdx, gIdx, tmp1, idxMask);
// the index result format is: (0, 1, 2, 0, 1, 2, 0, 1, 2, ...), concat last loop backup result
Reg::Copy(gComIdx, gIdx); // backup gComIdx
// the index result format is: (0, 1, 2, 6, 7, 8, ...)
Reg::Add(gIdx, gIdx, tmp2, idxMask); // backup gIdx

// get last loop result
Reg::RegTensor<T> bakSrc;
Reg::RegTensor<RangeType> gBakIdx;
Reg::Adds(gBakIdx, gComIdx, bakBegAddr, idxMask);
Reg::MaskReg comMask = Reg::UpdateMask<T>(comLpMaskVal);
Reg::DataCopyGather(
    (Reg::RegTensor<CastType>&)bakSrc, dstPtr, (Reg::RegTensor<IdxType>&)gBakIdx, comMask);
Reg::LocalMemBar<Reg::MemType::VEC_LOAD, Reg::MemType::VEC_STORE>();

// first operation, split R
Reg::Duplicate(yDst, (T)0, comMask);
```

**片段 2** (行 746-757):

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
```

**片段 3** (行 786-805):

```cpp
for (uint16_t comIdx = 1; comIdx < (uint16_t)comRightA; comIdx++) {
    for (uint16_t srIdx = 0; srIdx < sndRLpCnt; srIdx++) {
        Reg::Adds(gIdx, gIdx, phs2LpOffset, idxMask);
        Reg::Adds(sIdx, sIdx, phs2LpOffset, idxMask);
        Reg::DataCopyGather(
            (Reg::RegTensor<CastType>&)yDst, dstPtr, (Reg::RegTensor<IdxType>&)gIdx, comMask);
        Reg::Add(yDst, yDst, xSrc, comMask);
        Reg::DataCopyScatter(dstPtr, yDst, (Reg::RegTensor<IdxType>&)sIdx, comMask);
    }
    Reg::Adds(gIdx, gIdx, phs2TLpOffset, idxMask);
    Reg::Adds(sIdx, sIdx, phs2TLpOffset, idxMask);
    Reg::DataCopyGather(
        (Reg::RegTensor<CastType>&)yDst, dstPtr, (Reg::RegTensor<IdxType>&)gIdx, sndLpLeftMask);
    Reg::Add(yDst, yDst, xSrc, sndLpLeftMask);
    Reg::DataCopyScatter(dstPtr, yDst, (Reg::RegTensor<IdxType>&)sIdx, sndLpLeftMask);
    Reg::Adds(gComIdx, gComIdx, curBakBegAdd, idxMask);
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
    Reg::DataCopyGather(
        (Reg::RegTensor<CastType>&)xSrc, dstPtr, (Reg::RegTensor<IdxType>&)gComIdx, comMask);
}
```

**要点**: ①VEC_LOAD→VEC_STORE 用于"读 UB→改→写回同址"的读后写保序；②VEC_STORE→VEC_LOAD 用于"scatter 写回 UB→下轮 gather 读 UB"的写后读同步；③DataCopyGather/Scatter 按索引随机访问 UB 时尤其需要显式同步。

### 实例 4：gelu_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Cast, CreateMask, DataCopy, Div, Duplicate, MaskPattern, MaskReg, Max, MemType, Mul, Muls, ReduceMax, RegTensor, StoreDist, UpdateMask
- **LocalMemBar 调用次数**: 1
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: gelu 动态量化中，先 ReduceMax 求 abs 最大值并 Duplicate 出 vregOutScale 写回 scaleOutAddr，再插 VEC_STORE→VEC_LOAD 同步，保证随后第二段循环重新 DataCopy 读 vregOutScale 做 Div 量化时读到的是已写回的缩放因子而非寄存器旧值。

（行 306-340）

```cpp
    preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
    AscendC::Reg::DataCopy(vregInput, xAddr + i * endAxisActualAlignLen_ + j * vl);
    // compute smoothscale
    AscendC::Reg::DataCopy(vregSmoothScale, smoothScaleAddr + j * vl);
    AscendC::Reg::Mul(vregInput, vregInput, vregSmoothScale, preg0);
    AscendC::Reg::Abs(vregAbs, vregInput, preg0);
    AscendC::Reg::Max(vregMax, vregAbs, vregMax, preg1);
}
{
    AscendC::Reg::ReduceMax(vregReduceMax, vregMax, preg1);
    AscendC::Reg::Muls(vregReduceMax, vregReduceMax, maxValue_, preg1);
    AscendC::Reg::Duplicate(vregOutScale, vregReduceMax, preg1);
    AscendC::Reg::DataCopy(scaleOutAddr + i * FP32_BLOCK_NUM, vregOutScale, preg1);
}
uint32_t sreg1 = endAxisLen_;
AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE,
                               AscendC::Reg::MemType::VEC_LOAD>();
for (uint16_t j = 0; j < loopNum; j++) {
    auto yOutAddr = yAddr + i * endAxisLenAlignTo8_ + j * vl;
    preg2 = AscendC::Reg::UpdateMask<float>(sreg1);
    AscendC::Reg::DataCopy(vregInput, xAddr + i * endAxisActualAlignLen_ + j * vl);
    AscendC::Reg::DataCopy(vregSmoothScale, smoothScaleAddr + j * vl);
    AscendC::Reg::Mul(vregInput, vregInput, vregSmoothScale, preg2);
    AscendC::Reg::Div(vregQuantRes, vregInput, vregOutScale, preg2);

    if constexpr (IsSameType<dstType, int8_t>::value) {
        AscendC::Reg::Cast<half, float, castTraitF32ToF16>(vregHalf, vregQuantRes, preg2);
        AscendC::Reg::Cast<dstType, half, castTraitF16ToI8Rint>(vregY, vregHalf, preg2);
    } else if constexpr (IsSameType<dstType, fp8_e4m3fn_t>::value ||
                         IsSameType<dstType, fp8_e5m2_t>::value) {
        AscendC::Reg::Cast<dstType, float, castTraitF32ToF8>(vregY, vregQuantRes, preg2);
    } else if constexpr (IsSameType<dstType, hifloat8_t>::value &&
                         roundMode == AscendC::RoundMode::CAST_HYBRID) {
        AscendC::Reg::Cast<dstType, float, castTraitF32ToH8Hybrid>(vregY, vregQuantRes, preg2);
    } else if constexpr (IsSameType<dstType, hifloat8_t>::value &&
```

**要点**: ①ReduceMax→Duplicate→DataCopy 写 scale 后必须同步再读，保证 Div 用到最新 scale；②量化阶段依赖同步后的缩放因子逐元素 Div；③是"先归约求 scale，再读 scale 逐元素量化"两段式计算的典型同步点。

### 实例 5：batch_norm_grad::CalcDgammaFoldVF

- **来源类型**: `__aicore__`
- **共现 API**: Add, Copy, CreateMask, DataCopy, LoadDist, MaskMergeMode, MaskPattern, MaskReg, MemType, Mul, ReduceSum, RegTensor, StoreDist, Sub, UpdateMask
- **LocalMemBar 调用次数**: 2
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: batch_norm_grad 求 dgamma 折叠时，先把每轮 ReduceSum 结果用 DIST_FIRST_ELEMENT_B32 写入 local_mem 的 binaryAdd 缓冲，循环结束后插 VEC_STORE→VEC_LOAD 同步，再进入二分归约树反复"读两处 UB→Add→写回一处 UB"，每层归约后再次插同步保证下一层读到合并结果。

（行 1706-1742）

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(binaryAddQuotientLoop - binaryAddRemainderLoop); i++) {
    Reg::MaskReg pregTailLoop = Reg::UpdateMask<float>(sreg1);
    LoadOneTensor<DY_TYPE>(dyAddr, binaryAddQ1, pregMain, (i + binaryAddRemainderLoop) * VL_FP32);
    LoadOneTensor<DY_TYPE>(dyAddr, binaryAddQ1Tail, pregTailLoop,
                           (i + binaryAddRemainderLoop) * VL_FP32 + halfXBufOffset_);
    LoadOneTensor<DY_TYPE>(xAddr, binaryAddQ2, pregMain, (i + binaryAddRemainderLoop) * VL_FP32);
    LoadOneTensor<DY_TYPE>(xAddr, binaryAddQ2Tail, pregTailLoop,
                           (i + binaryAddRemainderLoop) * VL_FP32 + halfXBufOffset_);
    Reg::Sub(binaryAddQ2, binaryAddQ2, meanValue, pregMain);
    Reg::Mul(binaryAddQ2, binaryAddQ2, binaryAddQ1, pregMain);
    Reg::Mul(binaryAddQ1, rstdValue, binaryAddQ2, pregMain);

    Reg::Sub(binaryAddQ2Tail, binaryAddQ2Tail, meanValue, pregTailLoop);
    Reg::Mul(binaryAddQ2Tail, binaryAddQ2Tail, binaryAddQ1Tail, pregTailLoop);
    Reg::Mul(binaryAddQ1Tail, rstdValue, binaryAddQ2Tail, pregTailLoop);
    Reg::Add(tmp1, binaryAddQ1, binaryAddQ1Tail, pregTailLoop);
    Reg::Copy<float, Reg::MaskMergeMode::MERGING>(binaryAddQ1, tmp1, pregTailLoop);

    Reg::ReduceSum(vlSum, binaryAddQ1, pregMain);
    Reg::DataCopy<float, Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        (__local_mem__ float*)binaryAdd + binaryAddRemainderLoop + i, vlSum, pregMerge);
}
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
uint16_t curBinaryAddLoop = binaryAddLoop;
for (uint16_t i = 0; i < binaryAddKLoop; i++) {
    curBinaryAddLoop = curBinaryAddLoop / DIGIT_TWO;
    for (uint16_t j = 0; j < curBinaryAddLoop; j++) {
        Reg::DataCopy(binaryAddQ1, (__local_mem__ float*)(binaryAdd) + j * VL_FP32);
        Reg::DataCopy(binaryAddR1,
                           (__local_mem__ float*)(binaryAdd) + (j + curBinaryAddLoop) * VL_FP32);
        Reg::Add(binaryAddQ1, binaryAddQ1, binaryAddR1, pregMain);
        Reg::DataCopy(((__local_mem__ float*)binaryAdd) + j * VL_FP32, binaryAddQ1, pregMain);
    }
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
}
uint32_t sreg3 = binaryAddParam.binaryAddLastNum;
Reg::MaskReg pregLast = Reg::UpdateMask<float>(sreg3);
```

**要点**: ①二分归约树每完成一层都要插 VEC_STORE→VEC_LOAD 同步，保证下层读到上层合并结果；②StoreDist::DIST_FIRST_ELEMENT_B32 把归约标量集中写 UB 头部，便于后续两两合并；③ReduceSum + binaryAdd 树是 reduce 类算子典型套路。

### 实例 6：max_pool_grad::ComputeSingleArgmax

- **来源类型**: `__aicore__`
- **共现 API**: AddrReg, Adds, Arange, Compare, CreateAddrReg, CreateMask, Duplicate, MaskPattern, MaskReg, MaskXor, MemType, RegTensor, Select, UpdateMask
- **LocalMemBar 调用次数**: 1
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: max_pool_grad 合并相邻批次 argmax 时，用 LoadOneElement 从 local_mem 标量读上一批 max/index，与当前批 Compare/Select 比较后更新 res/realResIndex，再插 VEC_LOAD→VEC_STORE 同步，确保随后 StoreOneElement 把最终 argmax 写回 local_mem 时与前面的标量读不乱序。

（行 389-409）

```cpp
if constexpr (MERGE) {
    Reg::RegTensor<int32_t> lastResIndex;
    LoadOneElement<int32_t, int32_t>(argmaxAddr, lastResIndex, pregOne, bufferOffset);

    Reg::RegTensor<float> lastRes;
    LoadOneElement<float, float>(maxValAddr, lastRes, pregOne, 0);

    Reg::MaskReg curNanMaskReg;
    Reg::MaskReg selReg;

    Reg::Compare<float, CMPMODE::NE>(curNanMaskReg, res, res, maskAll);
    Reg::Compare<float, CMPMODE::GT>(selReg, res, lastRes, maskAll);
    Reg::MaskXor(selReg, selReg, curNanMaskReg, maskAll);

    Reg::Select(res, res, lastRes, selReg);
    Reg::Select(realResIndex, realResIndex, lastResIndex, selReg);

    Reg::LocalMemBar<Reg::MemType::VEC_LOAD, Reg::MemType::VEC_STORE>();
}

StoreOneElement<int32_t, int32_t>(argmaxAddr, realResIndex, pregOne, bufferOffset);
```

**要点**: ①VEC_LOAD→VEC_STORE 用于"读 local_mem 标量→比较选择→写回 local_mem"的读后写同步；②用 Compare NE 检测 NaN、MaskXor 排除 NaN 干扰 GT 比较；③标量级（pregOne/VL1）读改写场景同样需要显式同步。

### 实例 7：stateless_random_choice_with_mask::StatelessRandomChoiceWithMask::ComputePrefixSum

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, Arange, Copy, CreateMask, DataCopy, DataCopyGather, DataCopyScatter, Duplicate, MaskPattern, MaskReg, MemType, Muls, RegTensor
- **LocalMemBar 调用次数**: 2
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 前缀和计算中，循环内 DataCopyGather 读 + Add + DataCopyScatter 写同一 countLocalAddr，循环结束插 VEC_STORE→VEC_LOAD 同步，再 DataCopy 读整行末尾累计值加到下一行；跨行时插 VEC_STORE→SCALAR_LOAD 同步，使后续标量读 countLocalAddr[i*cols-1] 能拿到矢量写回的最新值。

（行 416-438）

```cpp
for (uint16_t j = 0; j < static_cast<uint16_t>(cols); j++) {
    AscendC::Reg::Adds(index, sequence, (uint64_t)j, pregFull);
    AscendC::Reg::DataCopyGather(reg0, countLocalAddr, index, pregFull);
    AscendC::Reg::Add(reg1, reg0, tmpReg, pregFull);
    AscendC::Reg::Copy(tmpReg, reg1, pregFull);
    AscendC::Reg::DataCopyScatter(countLocalAddr, reg1, index, pregFull);
}

AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE, AscendC::Reg::MemType::VEC_LOAD>();

AscendC::Reg::DataCopy(reg1, countLocalAddr);
AscendC::Reg::Adds(reg1, reg1, maxValue, pregFull);
AscendC::Reg::DataCopy(countLocalAddr, reg1, pregFull);
__local_mem__ int64_t* countAddr = countLocalAddr;
for (uint16_t i = 1; i < static_cast<uint16_t>(rows); i++) {
    AscendC::Reg::LocalMemBar<AscendC::Reg::MemType::VEC_STORE, AscendC::Reg::MemType::SCALAR_LOAD>();
    int64_t max = countLocalAddr[i * cols - 1];
    int64_t maxValue1 = max;
    countAddr += ALIGNMENT_32;
    AscendC::Reg::DataCopy(reg1, countAddr);
    AscendC::Reg::Adds(reg1, reg1, maxValue1, pregFull);
    AscendC::Reg::DataCopy(countAddr, reg1, pregFull);
}
```

**要点**: ①同一 UB 数组 Gather/Scatter 累加后必须 VEC_STORE→VEC_LOAD 同步再读汇总值；②跨行用 VEC_STORE→SCALAR_LOAD 让矢量写对随后标量读可见；③展示矢量写→标量读这一较少见的同步方向组合。

### 实例 8：cross_entropy_loss_grad::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, AddrReg, CreateAddrReg, CreateMask, DataCopy, LoadDist, MaskPattern, MaskReg, MemType, Mul, RegTensor, UpdateMask
- **LocalMemBar 调用次数**: 2
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 带 weight 的 softmax 反向中，循环内 DataCopy 读 smGradAddr 旧值，Add 累加 regWeight 后插 VEC_LOAD→VEC_STORE 同步，再 DataCopy 写回 smGradAddr 同一地址，保证"读旧值→算新值→写回"按顺序执行不乱序；主循环与 tail 循环都重复此模式。

（行 274-294）

```cpp
for (uint16_t i = 0; i < nTimes; i++) {
    Reg::DataCopy<float, Reg::LoadDist::DIST_BRC_B32>(regSmoothGrad, smoothAddr + i);
    for (uint16_t loop = 0; loop < repeatTimes1; loop++) {
        Reg::AddrReg srcOffset = Reg::CreateAddrReg<float>(loop, vfLen);
        Reg::AddrReg dstOffset = Reg::CreateAddrReg<float>(i, cOnceNum, loop, vfLen);
        Reg::DataCopy(regWeight, weightAddr, srcOffset);
        Reg::Mul(regWeight, regWeight, regSmoothGrad, copyOutReg);
        Reg::DataCopy(regOut, smGradAddr, dstOffset);
        Reg::Add(regOutAdd, regWeight, regOut, copyOutReg);
        Reg::LocalMemBar<Reg::MemType::VEC_LOAD, Reg::MemType::VEC_STORE>();
        Reg::DataCopy(smGradAddr, regOutAdd, dstOffset, copyOutReg);
    }
    for (uint16_t loopT = 0; loopT < tailLoopTimes; loopT++) {
        Reg::DataCopy(regWeight, weightTailAddr);
        Reg::Mul(regWeight, regWeight, regSmoothGrad, preg);
        Reg::DataCopy(regOut, smGradTailAddr + i * cOnceNum);
        Reg::Add(regOutAdd, regWeight, regOut, preg);
        Reg::LocalMemBar<Reg::MemType::VEC_LOAD, Reg::MemType::VEC_STORE>();
        Reg::DataCopy(smGradTailAddr + i * cOnceNum, regOutAdd, preg);
    }
}
```

**要点**: ①VEC_LOAD→VEC_STORE 用于"读 UB→改→写回 UB 同址"的读后写保序；②AddrReg/CreateAddrReg 生成偏移实现按 stride 访问；③每轮读改写都成对插同步，是 in-place 累加的典型用法。

### 实例 9：dynamic_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Cast, DataCopy, LoadDist, MaskReg, Max, MemType, Mul, Muls, RegTensor, UpdateMask
- **LocalMemBar 调用次数**: 1
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_quant 逐通道求 colMax 时，循环开始先插 VEC_STORE→VEC_LOAD 同步，确保 DataCopy 读到的 colMaxLocalAddr 是上一轮（或上一块）写回的最大值，随后 Abs/Max 更新 colMax 并写回 UB，为下一轮或 isLastBlock 的 scale 计算做准备。

（行 484-509）

```cpp
for (uint16_t nIdx = 0; nIdx < nLoopNum; nIdx++) {
    mask = Reg::UpdateMask<float>(currColNum);
    // 从ub中读入colMax
    // 插入ub同步
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
    Reg::DataCopy<float>(vregColMax, (__ubuf__ float*)(colMaxLocalAddr + nIdx * elementNumPerLoop));
    for (uint16_t mIdx = 0; mIdx < mLoopNum; mIdx++) {
        Reg::DataCopy<xDtype, Reg::LoadDist::DIST_UNPACK_B16>(
            vregIn, (__ubuf__ xDtype*)(xAddr + mIdx * blockColNum + nIdx * elementNumPerLoop));
        Reg::Cast<float, xDtype, castTraitB16ToB32>(vregInFp32, vregIn, mask);
        if constexpr (hasSmooth) {
            Reg::DataCopy<xDtype, Reg::LoadDist::DIST_BRC_B16>(vregSmooth,
                                                                         (__ubuf__ xDtype*)(smoothAddr + mIdx));
            Reg::Cast<float, xDtype, castTraitB16ToB32>(vregSmoothFp32, vregSmooth, mask);
            Reg::Mul<float>(vregInFp32, vregInFp32, vregSmoothFp32, mask);
        }
        Reg::Abs<float>(vregAbs, vregInFp32, mask);
        Reg::Max<float>(vregColMax, vregAbs, vregColMax, mask);
    }
    // 局部colMax写入ub，为后续计算做准备
    Reg::DataCopy<float>((__ubuf__ float*)colMaxLocalAddr + nIdx * elementNumPerLoop, vregColMax, mask);
    if constexpr (isLastBlock) {
        Reg::Muls(vregColMax, vregColMax, scalar, mask);
        Reg::DataCopy<float>((__ubuf__ float*)scaleAddr + nIdx * elementNumPerLoop, vregColMax, mask);
    }
}
```

**要点**: ①循环入口插同步读上一轮写入的 colMax，确保滚动更新初值正确；②Abs+Max 滚动更新列最大值并写回 UB；③isLastBlock 时 Muls 缩放并写 scaleAddr 输出最终 scale。

### 实例 10：global_lp_pool::GeneralPowerVf

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Exp, Ln, LoadAlign, MaskReg, MemType, Muls, RegTensor, StoreAlign, UpdateMask
- **LocalMemBar 调用次数**: 3
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: global_lp_pool 求 x^p 时分四段 in-place 改写 UB：Abs→写回、Ln→写回、Muls×p→写回、Exp→写回，每段都用"循环 LoadAlign→计算→StoreAlign 写回同址"模式，段与段之间插 VEC_STORE→VEC_LOAD 同步，确保下一段 LoadAlign 读到上一段 StoreAlign 的最新结果。

（行 300-332）

```cpp
for (uint16_t i = 0; i < pwrLoopNum; i++) {
    mask = Reg::UpdateMask<float>(remain);
    Reg::LoadAlign<float>(vx, pwrAddr + static_cast<int32_t>(i) * VF_VL_F32);
    Reg::Abs(vx, vx, mask);
    Reg::StoreAlign<float>(pwrAddr + static_cast<int32_t>(i) * VF_VL_F32, vx, mask);
}
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
// Ln
remain = pwrRemaining;
for (uint16_t i = 0; i < pwrLoopNum; i++) {
    mask = Reg::UpdateMask<float>(remain);
    Reg::LoadAlign<float>(vx, pwrAddr + static_cast<int32_t>(i) * VF_VL_F32);
    Reg::Ln(vx, vx, mask);
    Reg::StoreAlign<float>(pwrAddr + static_cast<int32_t>(i) * VF_VL_F32, vx, mask);
}
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
// Muls
remain = pwrRemaining;
for (uint16_t i = 0; i < pwrLoopNum; i++) {
    mask = Reg::UpdateMask<float>(remain);
    Reg::LoadAlign<float>(vx, pwrAddr + static_cast<int32_t>(i) * VF_VL_F32);
    Reg::Muls(vx, vx, static_cast<float>(pVal), mask);
    Reg::StoreAlign<float>(pwrAddr + static_cast<int32_t>(i) * VF_VL_F32, vx, mask);
}
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
// Exp
remain = pwrRemaining;
for (uint16_t i = 0; i < pwrLoopNum; i++) {
    mask = Reg::UpdateMask<float>(remain);
    Reg::LoadAlign<float>(vx, pwrAddr + static_cast<int32_t>(i) * VF_VL_F32);
    Reg::Exp(vx, vx, mask);
    Reg::StoreAlign<float>(pwrAddr + static_cast<int32_t>(i) * VF_VL_F32, vx, mask);
}
```

**要点**: ①in-place 多段变换每段之间必须 VEC_STORE→VEC_LOAD 同步，保证下段读到上段写回结果；②LoadAlign/StoreAlign 配对访问同一段 UB 地址；③用 Ln+Muls+Exp 实现 power 运算的拆分流水，每段写回后都需同步。

### 实例 11：pool_3d_common::MergeMaxParaRes

- **来源类型**: `__aicore__`
- **共现 API**: Add, CreateMask, DataCopyUnAlign, DataCopyUnAlignPre, MaskPattern, MaskReg, Max, MemType, RegTensor, UnalignReg
- **LocalMemBar 调用次数**: 2
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 多核并行池化结果合并时，先插 VEC_STORE→VEC_LOAD 同步确保读到前一次写回 dstLocalAddr 的 lastRes，DataCopyUnAlign 读出 lastRes 后与当前 res 做 Max/Add 合并，再插 VEC_LOAD→VEC_STORE 同步保证随后下一次调用写入 dstLocalAddr 时与本轮读取不乱序。

（行 242-282）

```cpp
__aicore__ inline void MergeMaxParaRes(Reg::RegTensor<T>& res, __local_mem__ T* dstLocalAddr, int32_t num)
{
    // merge cur result with pre result
    Reg::MaskReg pregAll = Reg::CreateMask<T, Reg::MaskPattern::ALL>();
    Reg::RegTensor<T> lastRes;
    AscendC::Reg::UnalignReg u0;
    auto curSrcAddr = dstLocalAddr;
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
    AscendC::Reg::DataCopyUnAlignPre(u0, curSrcAddr);
    AscendC::Reg::DataCopyUnAlign(lastRes, u0, curSrcAddr, num);
    if constexpr (OP_TYPE == OP_TYPE_MAX_POOL_3D) {
        Reg::Max(res, res, lastRes, pregAll);
    } else {
        Reg::Add(res, res, lastRes, pregAll);
    }
    Reg::LocalMemBar<Reg::MemType::VEC_LOAD, Reg::MemType::VEC_STORE>();
}

template <typename T>
__aicore__ inline constexpr T GetNegInf()
{
    T negInf = 0;
    if constexpr (std::is_same<T, int32_t>::value) {
        negInf = MIN_INT32;
    } else if constexpr (std::is_same<T, int64_t>::value) {
        negInf = MIN_INT64;
    } else if constexpr (std::is_same<T, uint8_t>::value) {
        negInf = MIN_UINT8;
    } else if constexpr (std::is_same<T, int16_t>::value) {
        negInf = MIN_INT16;
    } else if constexpr (std::is_same<T, int8_t>::value) {
        negInf = MIN_INT8;
    } else if constexpr (std::is_same<T, uint16_t>::value) {
        negInf = MIN_UINT16;
    } else if constexpr (std::is_same<T, float>::value) {
        negInf = *reinterpret_cast<const float*>(&FLOAT32_NEG_INF);
    } else {
        negInf = *reinterpret_cast<const half*>(&FLOAT16_NEG_INF);
    }
    return negInf;
}
```

**要点**: ①进入 merge 即插 VEC_STORE→VEC_LOAD 同步读上次写回的 lastRes；②合并完插 VEC_LOAD→VEC_STORE 同步保护下次写回 dstLocalAddr；③同一函数内两个方向同步成对出现，体现"读旧→合并→写回"完整闭环。

### 实例 12：softmax_grad_ext::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, DataCopy, LoadDist, MaskReg, MemType, MulAddDst, RegTensor, StoreDist, UpdateMask
- **LocalMemBar 调用次数**: 1
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: softmax_grad_ext 小 r 分支中，外层循环每轮开始先插 VEC_STORE→VEC_LOAD 同步，保证 DataCopy 读到的 xSumLocalAddr 是上一轮 MulAddDst 累加后写回的 sum，再用 vregX0/vregX1 做 MulAddDst 累加并写回 xSumLocalAddr。

（行 237-262）

```cpp
for (uint16_t i = 0; i < rLen; i++) {
    uint32_t sreg = curTileALen;
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
    for (uint16_t k = 0; k < loopA0Num; k++) {
        pregMask = Reg::UpdateMask<float>(sreg);
        uint32_t xOffset = i * aLen + k * VL_FP32;
        Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(vregSum,
                                                                 (__ubuf__ float*)xSumLocalAddr + k * VL_FP32);
        if constexpr (xIsFp32_) {
            Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(vregX0,
                                                                     (__ubuf__ float*)gradLocalAddr + xOffset);
            Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(vregX1,
                                                                     (__ubuf__ float*)x1LocalAddr + xOffset);
        } else { // fp16, bf16
            Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vregX0B16,
                                                                       ((__ubuf__ T*)gradLocalAddr + xOffset));
            Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vregX1B16,
                                                                       ((__ubuf__ T*)x1LocalAddr + xOffset));
            Reg::Cast<float, T, castTraitFp16ToFp32>(vregX0, vregX0B16, pregMask);
            Reg::Cast<float, T, castTraitFp16ToFp32>(vregX1, vregX1B16, pregMask);
        }
        Reg::MulAddDst(vregSum, vregX0, vregX1, pregMask);
        Reg::DataCopy<float, Reg::StoreDist::DIST_NORM>((__ubuf__ float*)xSumLocalAddr + k * VL_FP32,
                                                                  vregSum, pregMask);
    }
}
```

**要点**: ①每轮外层循环入口插同步读上一轮累加和，保证滚动累加正确；②MulAddDst 实现 sum += x0*x1 的融合累加；③fp16/bf16 走 DIST_UNPACK_B16 + Cast 到 fp32 再参与计算。

### 实例 13：max_pool3d_with_argmax_v2::MergeMaxAndIndex

- **来源类型**: `__aicore__`
- **共现 API**: Compare, CompareScalar, CreateMask, MaskPattern, MaskReg, MaskXor, MemType, RegTensor, Select
- **LocalMemBar 调用次数**: 1
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 3D max pooling 带 argmax 的相邻结果合并中，LoadOneNum 读上一批 lastRes/lastResIndex，Compare GT + MaskXor 排除 NaN 后 Select 更新 res/realResIndex，插 VEC_LOAD→VEC_STORE 同步，保证随后把更新结果写回 dstLocalAddr/indexLocalAddr 时与刚才标量读不乱序。

（行 174-198）

```cpp
    Reg::MaskReg maskAll = Reg::CreateMask<T, Reg::MaskPattern::ALL>();
    Reg::MaskReg notNanMaskReg;
    Reg::MaskReg nanMaskReg;
    Reg::MaskReg pregOne = Reg::CreateMask<U, Reg::MaskPattern::VL1>();
    Reg::RegTensor<U> lastRes;
    Reg::RegTensor<TINDEX> lastResIndex;
    LoadOneNum<T, U>(dstLocalAddr, lastRes, pregOne, offset);
    Reg::Compare<U, CMPMODE::NE>(nanMaskReg, res, res, maskAll);        // cur nan
    Reg::Compare<U, CMPMODE::GT>(notNanMaskReg, res, lastRes, maskAll); // cur large > last
    Reg::MaskXor(notNanMaskReg, notNanMaskReg, nanMaskReg, maskAll);    // gt & nan
    Reg::Select(res, res, lastRes, notNanMaskReg);                      // nan index
    LoadOneNum<TINDEX, TINDEX>(indexLocalAddr, lastResIndex, pregOne, offset);
    Reg::CompareScalar<TINDEX, CMPMODE::EQ>(nanMaskReg, lastResIndex, isPadValue, maskAll);
    Reg::Select(lastResIndex, realResIndex, lastResIndex, nanMaskReg);
    Reg::Select(realResIndex, realResIndex, lastResIndex, notNanMaskReg);
    Reg::LocalMemBar<Reg::MemType::VEC_LOAD, Reg::MemType::VEC_STORE>();
}

template <typename T1, typename TINDEX>
class MaxPool3DWithArgmaxV2BigKernelRegbase {
public:
    __aicore__ inline MaxPool3DWithArgmaxV2BigKernelRegbase(
        TPipe* pipe,
        const MaxPool3DWithArgmaxV2Tiling::MaxPool3DWithArgmaxV2BigKernelRegbaseTilingData* __restrict tiling)
        : pipe_(pipe), tilingData_(tiling){};
```

**要点**: ①VEC_LOAD→VEC_STORE 用于"读 local_mem→比较选择→写回 local_mem"的读后写同步；②CompareScalar EQ 判断 isPadValue 处理 pad 索引，避免 pad 索引覆盖真实 argmax；③与 max_pool_grad 同属 merge-max-with-argmax 模式。

### 实例 14：avg_pool::MergeAvgParaRes

- **来源类型**: `__aicore__`
- **共现 API**: Add, CreateMask, DataCopyUnAlign, DataCopyUnAlignPre, MaskPattern, MaskReg, MemType, RegTensor, UnalignReg
- **LocalMemBar 调用次数**: 2
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: avg_pool 多核并行结果合并时，先插 VEC_STORE→VEC_LOAD 同步读到前一次写回的 lastRes，DataCopyUnAlign 读出后与当前 res 做 Add 累加，再插 VEC_LOAD→VEC_STORE 同步保护下次写回；与 MergeMaxParaRes 结构一致，仅把 Max 换成 Add。

（行 1347-1368）

```cpp
__aicore__ inline void MergeAvgParaRes(Reg::RegTensor<T>& res, __local_mem__ T* dstLocalAddr, int32_t num)
{
    // merge cur result with pre result
    Reg::MaskReg pregAll = Reg::CreateMask<T, Reg::MaskPattern::ALL>();
    Reg::RegTensor<T> lastRes;
    AscendC::Reg::UnalignReg u0;
    auto curSrcAddr = dstLocalAddr;
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
    AscendC::Reg::DataCopyUnAlignPre(u0, curSrcAddr);
    AscendC::Reg::DataCopyUnAlign(lastRes, u0, curSrcAddr, num);
    Reg::Add(res, res, lastRes, pregAll);
    Reg::LocalMemBar<Reg::MemType::VEC_LOAD, Reg::MemType::VEC_STORE>();
}

template <typename T, typename RegDstT>
__aicore__ inline void LoadOneElement(const __local_mem__ void* input, RegDstT& dst, uint32_t offset)
{
    Reg::UnalignReg u0;
    auto srcAddr = (__local_mem__ T*)(input) + offset;
    Reg::DataCopyUnAlignPre(u0, srcAddr);
    Reg::DataCopyUnAlign(dst, u0, srcAddr, 1);
}
```

**要点**: ①avg merge 用 Add 累加，max merge 用 Max 取大，同步结构完全一致；②进入 merge 插 VEC_STORE→VEC_LOAD 读上次结果，合并完插 VEC_LOAD→VEC_STORE 保护下次写；③DataCopyUnAlignPre/DataCopyUnAlign 处理非对齐 lastRes 读取。

### 实例 15：avg_pool_v2_grad::DoMulCNhwc

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, MaskReg, MemType, Muls, RegTensor, UpdateMask
- **LocalMemBar 调用次数**: 1
- **参数模式**: `T2_A0_M0_TYPEnone`（实参 0 个）
- **语义**: avg_pool 反向 NHWC 格式梯度累加中，双重循环按 hIdx/wIdx 遍历核窗口，每轮用 Adds 算 scatterIndexOffset 并调用 GradientAcc 把梯度 scatter 累加到 yAddr，整个双重循环结束后插一次 VEC_STORE→VEC_LOAD 同步，确保所有 scatter 写回完成后再返回/进入下一次调用。

（行 422-449）

```cpp
    for (uint16_t hIdx = 0; hIdx < kH; hIdx++) {
        int32_t hKernelOffset = hIdx * wOutputActual * cOutputAligned;
        for (uint16_t wIdx = 0; wIdx < kW; wIdx++) {
            uint32_t gradMask = gradMaskCount;
            AscendC::Reg::MaskReg pregRes = AscendC::Reg::UpdateMask<int32_t>(gradMask);

            int32_t scatterIndexOffsetTotal = nOffset + hKernelOffset + wIdx * cOutputAligned;
            AscendC::Reg::Adds(scatterIndexReg, scatterStartIdxReg, scatterIndexOffsetTotal, pregRes);

            if constexpr (IS_CHECK_RANGE == 1) {
                AscendC::Reg::RegTensor<int32_t> wCurIndexReg;
                AscendC::Reg::RegTensor<int32_t> hCurIndexReg;
                AscendC::Reg::Adds(wCurIndexReg, tmplWRegIdx, int32_t(wIdx), pregRes);
                AscendC::Reg::Adds(hCurIndexReg, hIndexReg, int32_t(hIdx), pregRes);
                FilterMask(pregRes, hCurIndexReg, wCurIndexReg, zeroConstReg, wMaxReg, hMaxReg);
            }

            GradientAcc(yAddr, gradReg, scatterIndexReg, divisorReg, pregRes);
        }
    }
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
}

template <typename T, const Reg::RegTrait& Trait = Reg::RegTraitNumOne>
__aicore__ inline void GenRepeatIndices(Reg::RegTensor<T, Trait>& indexReg, uint16_t repeatCount,
                                        uint16_t repeatSize)
{
    AscendC::Reg::Arange(indexReg, 0);
```

**要点**: ①双重核窗口循环结束后插一次 VEC_STORE→VEC_LOAD 同步，汇总所有 scatter 写回；②Adds 计算 scatter 偏移、UpdateMask 控制尾块元素数；③IS_CHECK_RANGE 分支用 FilterMask 裁剪越界核位置后再累加梯度。

### LocalMemBar 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 二分归约求行最大：DataCopy 写 UB→同步→DataCopyUnAlign 读 UB | __VEC_SCOPE__ |
| sparse_slice | Add, Compare, CreateMask, DataCopy, DeInterleave | 边界广播写 UB→同步→按 indices 读 UB；掩码写回→同步→ReduceSum | __VEC_SCOPE__ |
| cumsum | Add, Adds, Arange, Copy, CreateMask | Gather/Scatter 索引累加：读 UB→同步→写回；写回→同步→下轮读 | __VEC_SCOPE__ |
| gelu_quant | Abs, Cast, CreateMask, DataCopy, Div | ReduceMax 求 scale 写 UB→同步→读 scale 做 Div 量化 | __VEC_SCOPE__ |
| batch_norm_grad | Add, Copy, CreateMask, DataCopy, LoadDist | ReduceSum 写 binaryAdd 缓冲→同步→二分树逐层读改写 | __aicore__ |
| max_pool_grad | AddrReg, Adds, Arange, Compare, CreateAddrReg | 标量读 local_mem→比较选择→同步→标量写回（读后写保序） | __aicore__ |
| stateless_random_choice_with_mask | Add, Adds, Arange, Copy, CreateMask | Gather/Scatter 前缀和→同步读汇总；跨行 VEC_STORE→SCALAR_LOAD | __VEC_SCOPE__ |
| cross_entropy_loss_grad | Add, AddrReg, CreateAddrReg, CreateMask, DataCopy | 读 UB 旧值→Add 累加→同步→写回同址（in-place 读改写） | __VEC_SCOPE__ |
| dynamic_quant | Abs, Cast, DataCopy, LoadDist | 循环入口同步读上轮 colMax→Abs/Max 更新→写回 UB | __VEC_SCOPE__ |
| global_lp_pool | Abs, Exp, Ln, LoadAlign | 多段 in-place 变换：LoadAlign→计算→StoreAlign→段间同步 | __aicore__ |
| pool_3d_common | Add, CreateMask, DataCopyUnAlign, DataCopyUnAlignPre | merge：同步读 lastRes→Max/Add 合并→同步保护下次写 | __aicore__ |
| softmax_grad_ext | Cast, DataCopy, LoadDist, MaskReg | 外层循环入口同步读上轮 sum→MulAddDst 累加→写回 | __VEC_SCOPE__ |
| max_pool3d_with_argmax_v2 | Compare, CompareScalar, CreateMask, MaskPattern | merge-max-with-argmax：读 local_mem→NaN 比较→同步→写回 | __aicore__ |
| avg_pool | Add, CreateMask, DataCopyUnAlign, DataCopyUnAlignPre | merge-avg：同步读 lastRes→Add 累加→同步保护下次写 | __aicore__ |
| avg_pool_v2_grad | Add, Adds, MaskReg, MemType | 双重核窗口 scatter 累加→循环结束同步汇总所有写 | __aicore__ |
