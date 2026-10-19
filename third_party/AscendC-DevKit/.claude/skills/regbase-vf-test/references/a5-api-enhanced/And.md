# And

**页面ID:** atlasascendc_api_07_0362  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0362.html

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

根据mask对输入数据srcReg0、srcReg1执行按元素与( & )操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0362_img_001.png)

- 对MaskReg操作：

将两个输入MaskReg的有效bit进行逻辑与运算得到新的MaskReg。

#### 函数原型

- 对RegTensor操作

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void And(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

- 对MaskReg操作

```
__simd_callee__ inline void And(MaskReg& dst, MaskReg& src0, MaskReg& src1, MaskReg& mask)
```

#### 参数说明

- 对RegTensor操作

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：bool/uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/uint64_t/int64_t |
| mode | 选择MERGING模式或ZEROING模式。   - ZEROING, mask未筛选的元素在dst中置零。  - MERGING, 当前不支持。 |
| U | srcReg0/srcReg1/dstReg RegTensor类型， 例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 两个源操作数的数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 两个源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

- 对MaskReg操作

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
__simd_vf__ inline void AndVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);        
        AscendC::Reg::And(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 对MaskReg操作

```
template <typename T>
__simd_vf__ inline void AndVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg src0 = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALLF>();
    AscendC::Reg::MaskReg src1 = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg dst;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::And(dst, src0, src1, mask);
        AscendC::Reg::Adds(srcReg, srcReg, 0, dst);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 And 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **And 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEint16_t+uint16_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: uint16_t, int16_t）
- **语义**: 在 dynamic_mx_quant 的 FP8 量化取最大值循环中，先用 `And` 按位与绝对值掩码求 FP16 数据的绝对值，归一化后再用 `And` 提取 FP32 尾数位，配合 `ShiftRights` 取指数位完成 MX 浮点 scale 的分解。

**片段 1** (行 466-476):

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
```

**片段 2** (行 500-518):

```cpp
Reg::Interleave(expMax, tmp16RegTensor, expMax, tmp16RegTensor);
Reg::Cast<float, T, castTraitZero>((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<T>&)expMax, mask);

Reg::Compare<uint32_t, CMPMODE::LT>(infMask, maxFP32RegTensor, absMaskFP32RegTensor, mask);
Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, maxFP32RegTensor, fp32ZeroRegTensor, mask);

Reg::Maxs((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<float>&)maxFP32RegTensor,
          this->maxLowBound_, mask);

Reg::Mul((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<float>&)maxFP32RegTensor,
         (Reg::RegTensor<float>&)invMaxRegTensor, mask);
Reg::Duplicate(invMaxRegTensor, FP8_DEFAULT_MAX_EXP);
// 右移获取指数位
Reg::ShiftRights(expFP32RegTensor, maxFP32RegTensor, FP32_SHR_NUM, mask);
// And获取尾数位
Reg::And(manFP32RegTensor, maxFP32RegTensor, manFP32RegTensor, mask);

Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32RegTensor, FP32_NUMBER_ZERO, mask);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32RegTensor, FP32_NUMBER_254, p0);
```

**要点**: （1）`Reg::And(dst, src, absMask, mask)` 按位与绝对值掩码屏蔽符号位，是求绝对值的典型手法；（2）提取尾数位 `And(man, max, manMask, mask)` 紧跟 `ShiftRights(exp, max, FP32_SHR_NUM, mask)` 取指数，二者成对出现；（3）循环体用 pnumMask，尾循环用 tailPnumMask 收敛，配合 `Copy<...,MERGING>` 合并尾数最大值。

### 实例 2：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **And 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEint16_t+uint16_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: uint16_t, int16_t）
- **语义**: 在 swiglu_backward 双轴量化的 regbase 计算中，用 `Reg::And` 对搬入的 B16 数据按位与绝对值掩码 absMask，得到两条并行数据流的绝对值，再经 `Max`/`ReduceMaxWithDataBlock` 归约出 block 内最大幅度。

**片段 1** (行 893-907):

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
```

**片段 2** (行 924-924):

```cpp
for (uint16_t j = 0; j < batchCount; j++) {
```

**要点**: （1）`Reg::And(regU16, (RegTensor<uint16_t>&)regA, absMask, maskAll)` 中 absMask 是预先构造的指数+尾数掩码，屏蔽符号位实现取绝对值；（2）DataCopy 用 `DIST_DINTLV_B16` 交织搬运一次取两路数据，配合两次 And 实现双路并行绝对值；（3）maskAll 为全有效掩码，结果用 `StoreUnAlign` 以 8 元素步长写回 tempMaxAddr。

### 实例 3：dynamic_mx_quant::Reg::StoreAlign

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskOr, MaskReg, Maxs, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **And 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask）
- **语义**: 在 dynamic_mx_quant 尾轴 FP8 量化的 scale 计算中，对 maxExp 做 Inf/Zero 校验和归一化后，用 `Reg::And(man32, max32, manMaskFP32, maskFloat)` 提取 FP32 尾数位，用于后续 MX 指数/尾数分离与条件进位。

（行 732-752）

```cpp
if constexpr (IsSame<T, float>::value) {
    Reg::LoadAlign<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_NORM>(
        max32, maxExpAddr, VF_LEN_32);
} else {
    Reg::LoadAlign<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_UNPACK_B16>(
        max16, maxExpAddr, VF_LEN_32);
    Reg::Cast<float, T, castTrait2Float>((Reg::RegTensor<float>&)max32, (Reg::RegTensor<T>&)max16,
                                         maskFloat);
}
Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32, expMask, maskFloat);
Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32, zeroU32, maskFloat);

Reg::Maxs((Reg::RegTensor<float>&)max32, (Reg::RegTensor<float>&)max32, maxLowBound_, maskFloat);

Reg::Mul((Reg::RegTensor<float>&)max32, (Reg::RegTensor<float>&)max32, (Reg::RegTensor<float>&)invMax,
         maskFloat);
Reg::ShiftRights(exp32, max32, FP32_SHR_NUM, maskFloat);
Reg::And(man32, max32, manMaskFP32, maskFloat);

Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32, FP32_NUMBER_ZERO, maskFloat);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, exp32, FP32_NUMBER_254, maskFloat);
```

**要点**: （1）按 `IsSame<T,float>` 分支选择 uint32 或 uint16+Cast 的加载路径，两条路径共用同一套尾数提取逻辑；（2）`And` 的 manMaskFP32 是 FP32 尾数位全 1 掩码，配合 `ShiftRights(exp32, max32, FP32_SHR_NUM, maskFloat)` 取指数；（3）Inf/Zero 用 Compare 产生掩码，供后续 Select 替换为 NaN/0。

### 实例 4：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskPattern, MaskReg, Max, MemType, Mul, Pack, RegTensor, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **And 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 在 dynamic_mx_quant 非尾轴优化路径中，循环内用 `Reg::And(absReg, xReg, absForXReg, pnumMask)` 求绝对值并二分归约行最大值；归一化后用 `And(manFP32Reg, xFP32MaxReg, manForFP32Reg, mask32)` 提取尾数位。

**片段 1** (行 254-264):

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(regLoop - 1); i++) {
    this->template LoadData<calcType>(xAddr, i * dataLenSingleLoop, xReg, pnumMask);
    Reg::And(absReg, (Reg::RegTensor<calcTypeInt>&)xReg, absForXReg, pnumMask);
    Reg::Max(xMaxReg, xMaxReg, absReg, pnumMask);
}
this->template LoadData<calcType>(xAddr, (regLoop - 1) * dataLenSingleLoop, xReg, tailPnumMask);
Reg::And(absReg, (Reg::RegTensor<calcTypeInt>&)xReg, absForXReg, tailPnumMask);
Reg::Max(absReg, xMaxReg, absReg, tailPnumMask);
Reg::Copy<calcTypeInt, Reg::MaskMergeMode::MERGING>(xMaxReg, absReg, tailPnumMask);
// 二分法求rowsSingleLoop行中的最大行
Reg::DataCopy(maxExpAddr, xMaxReg, pnumMask);
```

**片段 2** (行 289-303):

```cpp
if constexpr (IsSame<T, bfloat16_t>::value) {
    Reg::Interleave(xMaxReg, zeroReg, xMaxReg, zeroReg);
    Reg::Cast<float, T, castTraitZero>((Reg::RegTensor<float>&)xFP32MaxReg, (Reg::RegTensor<T>&)xMaxReg,
                                       mask16);
    Reg::Mul((Reg::RegTensor<float>&)xFP32MaxReg, (Reg::RegTensor<float>&)xFP32MaxReg, dstTypeMaxReg, mask32);
} else {
    Reg::Mul((Reg::RegTensor<float>&)xFP32MaxReg, (Reg::RegTensor<float>&)xMaxReg, dstTypeMaxReg, mask32);
}
// 右移获取指数位
Reg::ShiftRights(expFP32Reg, xFP32MaxReg, FP32_SHR_NUM, mask32);
// And获取尾数位
Reg::And(manFP32Reg, xFP32MaxReg, manForFP32Reg, mask32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32Reg, FP32_NUMBER_ZERO, mask32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32Reg, FP32_NUMBER_254, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32Reg, FP32_NUMBER_ZERO, p0);
```

**要点**: （1）absForXReg 是与数据位宽匹配的绝对值掩码，屏蔽符号位实现取绝对值；（2）尾循环用 tailPnumMask 收敛，并用 `Copy<calcTypeInt, MERGING>` 合并到 xMaxReg；（3）bfloat16_t 分支先 Interleave 再 Cast 到 FP32，half 分支直接 Mul，两条路径都汇入相同的 ShiftRights+And 指数/尾数分解。

### 实例 5：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Max, Min, PostLiteral, ReduceMax, RegLayout, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **And 调用次数**: 8
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: int32_t, uint32_t）
- **语义**: 在 dynamic_block_quant 单行 kernel 中，按 IN_TYPE 用 `Reg::And` 对搬入数据按位与 Fp32Max/Fp16Max 掩码取绝对值，再用 `Max<...,MERGING>` 累积 block 内最大幅度，为分块量化提供 amax。

**片段 1** (行 339-350):

```cpp
for (uint16_t vlLoopIdx = 0; vlLoopIdx < normalLoopNum; vlLoopIdx++) {
    inputMaskReg = AscendC::Reg::UpdateMask<IN_TYPE>(curSize);
    AscendC::Reg::DataCopy(vReg0, xLocal + rowIdx * inputColAlign +
                                           colIdx * tilingData_->blockSizeCol + vlLoopIdx * VL);
    AscendC::Reg::And((AscendC::Reg::RegTensor<uint32_t>&)vReg3,
                           (AscendC::Reg::RegTensor<uint32_t>&)vReg0,
                           (AscendC::Reg::RegTensor<uint32_t>&)vRegFp32Max, inputMaskReg);
    AscendC::Reg::Max<uint32_t, AscendC::Reg::MaskMergeMode::MERGING>(
        (AscendC::Reg::RegTensor<uint32_t>&)vReg2,
        (AscendC::Reg::RegTensor<uint32_t>&)vReg2,
        (AscendC::Reg::RegTensor<uint32_t>&)vReg3, inputMaskReg);
}
```

**片段 2** (行 464-474):

```cpp
for (uint16_t vlLoopIdx = 0; vlLoopIdx < normalLoopNum; vlLoopIdx++) {
    inputMaskReg = AscendC::Reg::UpdateMask<IN_TYPE>(curSize);
    AscendC::Reg::DataCopy(vReg0, xLocal + rowIdx * inputColAlign +
                                           colIdx * tilingData_->blockSizeCol + vlLoopIdx * VL);
    AscendC::Reg::And((AscendC::Reg::RegTensor<uint16_t>&)vReg3,
                           (AscendC::Reg::RegTensor<uint16_t>&)vReg0,
                           (AscendC::Reg::RegTensor<uint16_t>&)vRegFp16Max, inputMaskReg);
    AscendC::Reg::Max<IN_TYPE, AscendC::Reg::MaskMergeMode::MERGING>(vReg2, vReg2, vReg3,
                                                                               inputMaskReg);
}
```

**要点**: （1）两条片段分别对应 uint32（FP32 路径）和 uint16（FP16/BF16 路径）的绝对值掩码，模板实参随位宽变化；（2）`UpdateMask<IN_TYPE>(curSize)` 生成尾部有效掩码 inputMaskReg，And/Max 均受其控制保证非整 block 不越界；（3）And+Max 组合是 amax 归约的标准子模式，结果存入 vReg2 累加。

### 实例 6：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **And 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 在 flat_quant 高性能路径的 scale 计算中，把搬入的 BF16 转 FP32、归一化后用 `Reg::And(man32, max32, manMaskFP32, preMaskScale)` 提取尾数位，配合 `CompareScalar`/`MaskAnd`/`Select` 完成指数进位与 NaN/Zero 替换。

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

**要点**: （1）`UpdateMask<uint32_t>(scaleNum)` 生成的 preMaskScale 贯穿 And/Compare/Select，是逐元素掩码的核心；（2）And 提取尾数后用三次 CompareScalar 产生 p0/p1/p2 掩码，再 MaskAnd 组合成进位判定；（3）`Pack<...,LOWEST>` 把 uint32 指数压成 uint16 写回，体现 flat_quant 的紧凑存储。

### 实例 7：dynamic_mx_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub
- **And 调用次数**: 12
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 在 dynamic_mx_quant 大尾轴高性能路径中，循环内对正反向两路 x0/x1 用 `Reg::And(x0AbsU32, x0U32, absForXU32, pregAll32)` 求绝对值并取 max，归一化后再用 `And` 提取 FP32 尾数位。

**片段 1** (行 415-431):

```cpp
    for (uint16_t j = 0; j <= loopNum; j++) {
        DataCopy((Reg::RegTensor<xDtype>&)x0U32, xAddr + j * dataLen8Align_);
        DataCopy((Reg::RegTensor<xDtype>&)x1U32, xAddr + (blockCount - j - 1) * dataLen8Align_);
        Reg::And(x0AbsU32, x0U32, absForXU32, pregAll32);
        Reg::And(x1AbsU32, x1U32, absForXU32, pregAll32);
        Reg::Max(x0AbsU32, x1AbsU32, x0AbsU32, pregAll32);
        Reg::Max(manAbs0FP32, manAbs0FP32, x0AbsU32, pregAll32);
    }
} else {
    for (uint16_t j = 0; j <= loopNum; j++) {
        DataCopy((Reg::RegTensor<xDtype>&)x0U16, xAddr + j * dataLen16Align_);
        DataCopy((Reg::RegTensor<xDtype>&)x1U16, xAddr + (blockCount - j - 1) * dataLen16Align_);
        Reg::And(x0AbsU16, x0U16, absForXU16, pregAll16);
        Reg::And(x1AbsU16, x1U16, absForXU16, pregAll16);
        Reg::Max(x0AbsU16, x1AbsU16, x0AbsU16, pregAll16);
        Reg::Max(maxU16, maxU16, x0AbsU16, pregAll16);
    }
```

**片段 2** (行 439-454):

```cpp
if constexpr (calcMode == MODE_ONE) {
    Reg::Maxs((Reg::RegTensor<float>&)manAbs0FP32, (Reg::RegTensor<float>&)manAbs0FP32, maxLowBound_,
              pregAll32);
    Reg::Mul((Reg::RegTensor<float>&)manAbs0FP32, (Reg::RegTensor<float>&)manAbs0FP32,
             (Reg::RegTensor<float>&)invMax, pregAll32);
} else {
    Reg::Mul((Reg::RegTensor<float>&)manAbs0FP32, (Reg::RegTensor<float>&)manAbs0FP32, dstTypeMaxReg,
             pregAll32);
}

Reg::ShiftRights(mxScale0FP32, manAbs0FP32, FP32_SHR_NUM, pregAll32);
// 提取尾数
Reg::And(manAbs0FP32, manAbs0FP32, manForFP32, pregAll32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, mxScale0FP32, FP32_NUMBER_ZERO, pregAll32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, mxScale0FP32, FP32_NUMBER_254, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manAbs0FP32, FP32_NUMBER_ZERO, p0);
```

**要点**: （1）pregAll32/pregAll16 是全有效掩码（非 UpdateMask 生成），用于整 block 处理场景，参数模式记为 M0；（2）uint32 与 uint16 两条数据通路分别用 absForXU32/absForXU16 掩码，And 调用 12 次密集出现；（3）calcMode==MODE_ONE 时先 Maxs 设下界再 Mul 归一化，否则直接 Mul 缩放，两条分支共用 And 取尾数。

### 实例 8：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CastTrait, Compare, CreateMask, Duplicate, Interleave, LoadAlign, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **And 调用次数**: 16
- **参数模式**: `T0_A4_M0_TYPEint16_t+uint16_t`（实参 4 个，类型: uint16_t, int16_t）
- **语义**: 在 grouped_dynamic_mx_quant 非尾轴 FP8 路径中，先 `LoadAlign` 取两路 xRegTensor，half 分支先 Cast 到 BF16，再用 `Reg::And(expMaxRegTensor, xBF16RegTensor, maxEleRegTensor, p0)` 提取指数/最大值位，非 half 分支直接 And 原始数据。

（行 340-350）

```cpp
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
```

**要点**: （1）maxEleRegTensor 是指数+尾数掩码（不含符号位），And 后即得绝对值对应的指数域，And 调用 16 次；（2）half→BF16 的 Cast 是为了统一到 BF16 位宽再做掩码，体现类型归一化策略；（3）两路 And 结果用 `Max(expRegTensor, ...)` 归约成单路 expMaxRegTensor，为后续 scale 计算供数。

### 实例 9：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **And 调用次数**: 12
- **参数模式**: `T0_A4_M1_TYPEint16_t+uint16_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: uint16_t, int16_t）
- **语义**: 在 swiglu_mx_quant 非末轴 scale 计算中，用 `Reg::And(absMax0, x0, absMask, maskAll)` 求两路 B16 绝对值，归约后转 FP32 归一化，再用 `And(manFP32_0, maxFP32_0, manMaskFP32, maskFP32)` 提取尾数位并做条件进位。

**片段 1** (行 310-339):

```cpp
for (uint16_t i = 0; i < blockCount; i++) {
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
        x0, x1, xAddr, 256);
    Reg::And(absMax0, (Reg::RegTensor<uint16_t>&)x0, absMask, maskAll);
    Reg::And(absMax1, (Reg::RegTensor<uint16_t>&)x1, absMask, maskAll);
    Reg::Max(absMax1Dim2, absMax1Dim2, absMax0, maskAll);
    Reg::Max(absMax2Dim2, absMax2Dim2, absMax1, maskAll);
}

// process absMax1Dim2
Reg::Cast<float, T, CAST_ZERO>((Reg::RegTensor<float>&)maxFP32_0,
                                    (Reg::RegTensor<T>&)absMax1Dim2, maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_0, (Reg::RegTensor<float>&)maxFP32_0,
              (Reg::RegTensor<float>&)invMax, maskFP32);
Reg::ShiftRights(expFP32_0, maxFP32_0, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_0, maxFP32_0, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_0, EXP_254, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_0, ZERO_FOR_ALL, p0);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32_0, SPECIAL_EXP_THRESHOLD_FP32, p1);
Reg::MaskOr(p0, p0, p1, maskFP32);
Reg::Adds(maxFP32_0, expFP32_0, 1, maskFP32);
Reg::Select(manFP32_0, maxFP32_0, expFP32_0, p0);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);
Reg::Cast<float, T, CAST_ONE>((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<T>&)absMax1Dim2,
                                   maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<float>&)maxFP32_1,
              (Reg::RegTensor<float>&)invMax, maskFP32);
Reg::ShiftRights(expFP32_1, maxFP32_1, SHR_NUM_FOR_FP32, maskFP32);
```

**片段 2** (行 365-383):

```cpp
Reg::And(manFP32_0, maxFP32_0, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32_0, EXP_254, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32_0, ZERO_FOR_ALL, p0);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, expFP32_0, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32_0, SPECIAL_EXP_THRESHOLD_FP32, p1);
Reg::MaskOr(p0, p0, p1, maskFP32);
Reg::Adds(maxFP32_0, expFP32_0, 1, maskFP32);
Reg::Select(manFP32_0, maxFP32_0, expFP32_0, p0);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);
Reg::Cast<float, T, CAST_ONE>((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<T>&)absMax2Dim2,
                                   maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<float>&)maxFP32_1,
              (Reg::RegTensor<float>&)invMax, maskFP32);
Reg::ShiftRights(expFP32_1, maxFP32_1, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_1, maxFP32_1, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, expFP32_1, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0Odd, expFP32_1, EXP_254, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, manFP32_1, ZERO_FOR_ALL, p0Odd);
```

**要点**: （1）DataCopy 用 `DIST_DINTLV_B16` 交织搬运 256 元素拆成 x0/x1 两路，And 对两路并行取绝对值；（2）manMaskFP32 与 ShiftRights(SHR_NUM_FOR_FP32) 配合完成指数/尾数分离，是 MX 量化的固定子模式；（3）MaskOr(p0,p1) 合并"指数==0 且尾数大于阈值"的特殊进位分支，Select 决定是否 exp+1。

### 实例 10：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **And 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 在 add_rms_norm_dynamic_mx_quant 的 scale 计算中，把搬入的 B16 最大值转 FP32 归一化后，用 `Reg::And(man32, max32, manMaskFP32, preMaskScale)` 提取尾数位，配合三组 `CompareScalar` + `MaskAnd`/`MaskOr` 判定进位并 `Select` 出最终指数。

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

**要点**: （1）preMaskScale 由 UpdateMask 生成，是 norm 类算子逐循环的有效元素掩码；（2）And 取尾数后，p0=(exp>0)&(exp<254)&(man>0) 做常规进位，p1=(exp==0)&(man>half) 做特殊进位，MaskOr 合并；（3）结果经 Pack 压成 B16 写 mxScaleLocal，ShiftLefts+Sub 算出 1/scale 写 halfScaleLocal。

### 实例 11：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **And 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 在 rms_norm_dynamic_mx_quant 的 scale 计算中，用 `Reg::And(man32, max32, manMaskFP32, preMaskScale)` 从归一化后的 FP32 最大值中提取尾数位，配合 `CompareScalar`/`MaskAnd`/`MaskOr` 做指数进位判定，最终 Pack 成 B16 scale 写回。

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

**要点**: （1）与 add_rms_norm 路径结构同构，差异在用 DataCopy(`DIST_UNPACK_B16`) 而非 LoadAlign 搬运；（2）And 的 manMaskFP32 是 FP32 尾数位掩码，与 ShiftRights(SHR_NUM_FOR_FP32) 成对使用；（3）进位掩码 p0/p1 经 MaskAnd 合并后 MaskOr 得最终 p0，Select 在 expOne 与 exp 间选择，NaN/Zero 用 Select 兜底。

### 实例 12：swiglu_backward_mx_quant_with_dual_axis::ComputeScaleCuBLASSecondLast

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, Sub
- **And 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask）
- **语义**: 在 swiglu_backward 双轴量化倒数第二轴的 scale 计算中，对 mxScale2 倒数用 `Reg::And(man32Reg, max32Reg, manMaskReg, maskAll32)` 提取尾数位，配合进位掩码与 `Select` 产出 FP8 scale 及其倒数。

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

**要点**: （1）maskAll32 为全有效掩码（mask_tokens 同时记录 Mask 与 mask，体现掩码寄存器命名混用）；（2）And 取尾数后 p0=(exp>0)&(exp<254)&(man>0)、p1=(exp==0)&(man>HALF_FOR_MAN)，与实例 10/11 同构；（3）结果先 Pack 成 uint16 再 Pack 成 uint8（scale8Zero），体现 FP8 scale 的双级压缩存储。

### 实例 13：dynamic_block_mx_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, Compare, CreateMask, Duplicate, Gather, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreAlign, Sub
- **And 调用次数**: 16
- **参数模式**: `T0_A4_M1_TYPEint16_t+uint16_t_MASKmask`（实参 4 个，含 mask/mode: mask，类型: uint16_t, int16_t）
- **语义**: 在 dynamic_block_mx_quant 中 `Reg::And` 高频出现：先用 absForX 取 FP16/BF16 绝对值、用 expMaskBF16 提取指数位、对 `ReduceMax` 后的结果再次 And 取指数域，完成 block 级 amax 到 E8M0 scale 的换算。

（行 661-720）

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
// compute  1/scale
// 只有在E1M2时，yMaxExp=0，xTmp0ExpBF16可能会等于biasE8M0
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, expTmpMaxDim, biasE8M0, maskAll);
```

**要点**: （1）`And(x0ExpFP16, x0, absForX, maskAll)` 取绝对值、`And(x0ExpBF16, x0BF16, absForX, maskAll)` 取 BF16 指数域，同一掩码 absForX 复用两种语义；（2）`And(expTmpMaxDim, expMaxDim, expMaskBF16, maskAll)` 在 ReduceMax 后二次提取指数，用于 inf/nan 与 invalid 判定；（3）half 分支先取 FP16 指数、Cast 到 BF16 后再取 BF16 指数并用 Select 替换 inf/nan，非 half 分支直接取 BF16 指数。

### 实例 14：tanh::TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, Cast, CompareScalar, DataCopy, Div, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, Or, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **And 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEint32_t+uint32_t_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: int32_t, uint32_t）
- **语义**: 在 tanh 数学算子中，先用多项式逼近算出 |x| 的 tanh 值，再用 `Reg::And(vregSign, vregSignMask, vregInput, mask)` 从原始输入提取符号位，最后 `Or` 把符号位贴回结果，恢复带符号的 tanh。

（行 86-104）

```cpp
Reg::FusedMulDstAdd(vregOutput, vregInputSqr, vregValue1, mask);
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
```

**要点**: （1）vregSignMask 是仅符号位为 1 的掩码，And 提取符号位是与 Or 配对的"取符号-贴符号"标准模式；（2）tanh 用 |x| 计算（Abs+satMask 饱和到 SAT_BOUND），再按符号还原，避免负数直接多项式逼近的精度问题；（3）`RegTraitNumOne` 标注单元素寄存器语义，And/Or 的类型实参为 uint32_t，对应文档 int32_t/uint32_t 模板组合。

### 实例 15：swiglu_group_quant::VFComputeMaxExpMXFP4Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, CastTrait, Compare, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **And 调用次数**: 12
- **参数模式**: `T0_A4_M1_TYPEint16_t+uint16_t_MASKMask+mask`（实参 4 个，含 mask/mode: mask, Mask，类型: uint16_t, int16_t）
- **语义**: 在 swiglu_group_quant 的 MXFP4 最大指数计算中，half 分支先用 `Reg::And(vdExpSelect0, vdExp0, invalidmaskfp16, scaleMask1)` 检测 INF/NAN，Cast 到 BF16 后再用 `And` 提取指数域，非 half 分支直接 And 取指数。

（行 304-320）

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

AscendC::Reg::Max(vdMaxExp, vdExpExtract0, vdExpExtract1, scaleMask1);
```

**要点**: （1）invalidmaskfp16 与 expMaskBF16 是两种不同掩码：前者定位非法值，后者提取指数位，And 同一 API 承担两种语义；（2）half 分支先用 And 比对非法掩码产生 invalidDataMask，再用 Select 在提取结果与 expMaskBF16 间选择以屏蔽 INF/NAN；（3）两路指数用 `Max(vdMaxExp, vdExpExtract0, vdExpExtract1, scaleMask1)` 归约，scaleMask1 控制有效元素。

### And 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, Cast, CastTrait, Compare | FP16 绝对值（And+absMask）+ FP32 尾数提取（And+manMask）配 ShiftRights 取指数 | __VEC_SCOPE__ |
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, Arange, Cast | Reg::And 双路并行取绝对值 + Max/ReduceMaxWithDataBlock 归约 block amax | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, Cast, CastTrait, Compare | FP32 尾数提取（And+manMaskFP32）配 ShiftRights 取指数，Inf/Zero 用 Compare+Select 兜底 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, Cast, Compare, CompareScalar | 通用 calcType 绝对值（And+absForXReg）+ 二分行最大归约 + FP32 尾数提取 | __VEC_SCOPE__ |
| dynamic_block_quant | Cast, CastTrait, CompareScalar, CreateMask | 按 IN_TYPE 选 uint32/uint16 掩码，And 取绝对值 + Max&lt;MERGING&gt; 累积 amax | __VEC_SCOPE__ |
| flat_quant | Adds, Cast, CastTrait, Compare | BF16→FP32 归一化后 And 取尾数，CompareScalar+MaskAnd 进位判定 | __simd_vf__ |
| dynamic_mx_quant | Adds, Cast, CastTrait, Compare | 全有效掩码 pregAll32 下双路 And 取绝对值 + And 取尾数，uint32/uint16 双通路 | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Cast, CastTrait, Compare, CreateMask | half→BF16 Cast 后 And 提取指数域，两路 And+Max 归约 expMax | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, Cast, Compare, CompareScalar | 交织搬运双路 And 取绝对值 + FP32 尾数提取，MaskOr 合并特殊进位 | __aicore__ |
| add_rms_norm_dynamic_mx_quant | Adds, Cast, Compare, CompareScalar | norm 类逐循环掩码下 And 取 FP32 尾数，三组 CompareScalar+MaskAnd/MaskOr 进位 | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, Cast, Compare, CompareScalar | DataCopy 搬运后 And 取尾数，进位掩码同构于 add_rms_norm | __aicore__ |
| swiglu_backward_mx_quant_with_dual_axis | Adds, Cast, Compare, CompareScalar | 倒数第二轴 scale，And 取尾数 + 双级 Pack（uint16→uint8）压缩 FP8 scale | __aicore__ |
| dynamic_block_mx_quant | Cast, Compare, CreateMask, Duplicate | And 高频复用：absForX 取绝对值 / expMaskBF16 取指数，ReduceMax 后再 And 取指数 | __VEC_SCOPE__ |
| tanh | Abs, Adds, Cast, CompareScalar | And 提取符号位（符号掩码）+ Or 贴回，对 abs(x) 多项式逼近后按符号还原 | __aicore__ |
| swiglu_group_quant | Cast, CastTrait, Compare, Duplicate | half 分支 And 检 INF/NAN + Cast 后 And 取指数，Select 屏蔽非法值 | __simd_vf__ |

