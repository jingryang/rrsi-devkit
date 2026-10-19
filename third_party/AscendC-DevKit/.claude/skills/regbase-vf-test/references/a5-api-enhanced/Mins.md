# Mins

**页面ID:** atlasascendc_api_07_0385  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0385.html

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

源操作数矢量内每个元素与标量相比，如果比标量大，则取标量值，比标量小，则取源操作数。计算公式如下：

![](images/atlasascendc_api_07_0385_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, typename U, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void Mins(S& dstReg, S& srcReg, U scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 矢量目的操作数和源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/half/bfloat16_t/int32_t/uint32_t/float/int64_t/uint64_t |
| S | 标量源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/half/bfloat16_t/int32_t/uint32_t/float/int64_t/uint64_t |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dstReg中置零。- MERGING，暂不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| scalarValue | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MinsVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, T scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, src0Addr + i * oneRepeatSize);
        AscendC::Reg::Mins(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Mins 实例

### 实例 1：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Mins 调用次数**: 1
- **参数模式**: `T3_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: 在 per-channel 伪量化中，将零点 zp_from_min 先用 Maxs 取下界 qMin，再用 Mins 取上界 qMax 裁剪到 [qMin, qMax] 范围内，随后加 0.5 并 floor 得到 nudged_zp。

（行 405-423）

```cpp
//      而非 1/scale，避免 scale 的 fp32 舍入误差在取倒数时被放大。
//      diffSafe = (diff==0) ? 1.0 : diff（复用 maskScaleZero，因 scale==0 ⟺ diff==0）
AscendC::Reg::Select<float>(vregDiffSaved, vregOne, vregDiffSaved, maskScaleZero);
AscendC::Reg::Div<float, &kDivMode>(vregInvScaleSafe, vregQRange, vregDiffSaved, mask);

// 2.4 zp_from_min = qMin - min / scaleSafe
//     用 0-ULP Div：min/scaleSafe 在 zfm 落到 N+0.5 半整数边界时极易抖动 1 ULP，
//     与 floor(zfm+0.5) 叠加会让 nudged_zp 偏离 TF。
AscendC::Reg::Div<float, &kDivMode>(vregZpFromMin, vregMin, vregScaleSafe, mask);
AscendC::Reg::Muls<float>(vregZpFromMin, vregZpFromMin, -1.0f, mask);
AscendC::Reg::Adds<float>(vregZpFromMin, vregZpFromMin, qMin, mask);

// 2.5 nudged_zp = floor(clip(zp_from_min, qMin, qMax) + 0.5)
AscendC::Reg::Maxs<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(vregZpClipped, vregZpFromMin, qMin,
                                                                       mask);
AscendC::Reg::Mins<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(vregZpClipped, vregZpClipped, qMax,
                                                                       mask);
AscendC::Reg::Adds<float>(vregZpClipped, vregZpClipped, 0.5f, mask);
AscendC::Reg::Cast<int32_t, float, kCastFp32ToInt32Floor>(vregZpInt, vregZpClipped, mask);
```

**要点**:
1. Mins 与 Maxs 配对实现标量 clamp 到 [qMin, qMax]，模板参数 `<float, float, MaskMergeMode::ZEROING>` 显式指定类型与 merge 模式。
2. ZEROING 模式下 mask 未选中元素在 dstReg 置零，需保证 mask 覆盖全部有效元素。
3. 标量 qMax 作为上界，逐元素取 min 实现量化范围裁剪，是 per-channel 伪量化 nudged 零点推导的关键步骤。

### 实例 2：clipped_swiglu::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Div, Exp, LoadDist, MaskPattern, MaskReg, Maxs, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **Mins 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 clipped SwiGLU 激活中，对解交错后的输入 vregX1DeF 和门控 vregX2DeF 分别用 Mins 限制到上界 clampLimit（配合 Maxs 取下界 negClampLimit），实现 [-clampLimit, clampLimit] 双向 clamp，稳定后续 sigmoid 的数值范围。

（行 372-409）

```cpp
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
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddr,
                                                                                     srcIdxOffset);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX1DeF, vregX1, mask);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX2DeF, vregX2, mask);
    } else {
        // float
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX1DeF, x1UbAddr, srcIdxOffset);
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX2DeF, x2UbAddr, srcIdxOffset);
    }
}
AscendC::Reg::Mins(minsReg, vregX1DeF, clampLimit, mask);
AscendC::Reg::Muls(mulsReg, minsReg, negAlpha, mask);
AscendC::Reg::Exp(expReg, mulsReg, mask);
AscendC::Reg::Adds(addsReg, expReg, scalarOne, mask);
AscendC::Reg::Div(sigmoidReg, minsReg, addsReg, mask);

AscendC::Reg::Mins(vregX2DeF, vregX2DeF, clampLimit, mask);
AscendC::Reg::Maxs(vregX2DeF, vregX2DeF, negClampLimit, mask);
AscendC::Reg::Adds(vregX2DeF, vregX2DeF, gluBias, mask);
```

**要点**:
1. Mins 在 SwiGLU 中用于 clamp 输入到 [-clampLimit, clampLimit]，避免 exp 溢出，是激活函数数值稳定的常见模式。
2. 4 参数形态 Mins(dst, src, scalar, mask)，scalar 为标量上界 clampLimit，无模板参数（类型由 RegTensor 推导）。
3. 与 Maxs 配对构成双向 clamp，对输入和门控两路分别截断后再做 sigmoid 运算。

### 实例 3：swiglu_mx_quant::VecScope_L446

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Div, Exp, LoadDist, MaskPattern, MaskReg, Maxs, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **Mins 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 MX 量化的 SwiGLU 计算中，对 deinterleave 后的 fp32 输入 minsReg 和门控 vregX2DeF 用 Mins 截断到 clampLimit，配合 Muls/Exp/Adds/Div 计算 clipped sigmoid，循环处理 dim1 维度的 VF 分块。

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

**要点**:
1. 主循环（片段 1）处理整块 dim1VfTimes 次，尾部循环（片段 2）处理 dim1TailTimes 次，用 mask1 处理尾部元素掩码。
2. 两路输入分别 Mins 截断到 clampLimit 后接 Muls/Exp/Adds/Div 计算 clipped sigmoid，是 SwiGLU 数值稳定的标准流程。
3. Mins+Maxs 双向 clamp 后 Cast 回 fp16/bf16 并 DataCopy 存储，mask 在两个片段中分别用 mask 与 mask1。

### 实例 4：fake_quant_affine_cachemask::AscendC::LocalTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, DataCopy, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskReg, Maxs, Mul, MulDstAdd, Muls, RegTensor, StoreDist, Sub, UpdateMask
- **Mins 调用次数**: 3
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: 在 affine 伪量化 cachemask 路径中，构造 m1 = clamp(q - qMinMinus1, 0, 1) 和 m2 = clamp(-q + qMaxPlus1, 0, 1) 两个 mask 因子，最后将量化结果 q 用 Maxs/Mins 裁剪到 [qMin, qMax]。

（行 380-405）

```cpp
if constexpr (HAS_ZP == 1) {
    Reg::MulDstAdd<float>(vregTmp, vregInvSc, vregZp, mask);
} else {
    Reg::Mul<float>(vregTmp, vregTmp, vregInvSc, mask);
}
Reg::Cast<int32_t, float, layoutZSatSMrgZRndR>(vregInt32, vregTmp, mask);
Reg::Cast<float, int32_t, layoutZMrgZRndR>(vregQ, vregInt32, mask);

// 用 in-place 形式（dst == src1）避免 cross-register Adds 在某些 lane
// 留下未写状态：先把 vregQ 复制到 vregM1，再 in-place 算
Reg::Adds<float, float>(vregM1, vregQ, 0.0f, mask); // vregM1 = vregQ
Reg::Adds<float, float>(vregM1, vregM1, -qMinMinus1F, mask);
Reg::Mins<float, float>(vregM1, vregM1, 1.0f, mask);
Reg::Maxs<float, float>(vregM1, vregM1, 0.0f, mask);
Reg::Muls<float, float>(vregM2, vregQ, -1.0f, mask); // vregM2 = -vregQ
Reg::Adds<float, float>(vregM2, vregM2, qMaxPlus1F, mask);
Reg::Mins<float, float>(vregM2, vregM2, 1.0f, mask);
Reg::Maxs<float, float>(vregM2, vregM2, 0.0f, mask);
Reg::Mul<float>(vregM1, vregM1, vregM2, mask);
Reg::DataCopy<float, Reg::StoreDist::DIST_NORM_B32>(m1Ptr + rowOffElems + i * VL_FP32, vregM1, mask);

Reg::Maxs<float, float>(vregTmp, vregQ, qMinF, mask);
Reg::Mins<float, float>(vregTmp, vregTmp, qMaxF, mask);
if constexpr (HAS_ZP == 1) {
    Reg::Sub<float>(vregTmp, vregTmp, vregZp, mask);
}
```

**要点**:
1. Mins<float, float> 2 模板参形式，标量 1.0f 作为上界实现 [0,1] 裁剪，用于构造 cachemask 的两个因子 m1、m2。
2. in-place 形式（dst == src1）避免 cross-register Adds 在某些 lane 留下未写状态。
3. cachemask 中 Mins 既用于构造 mask 因子（裁剪到 [0,1]），又用于最终量化结果裁剪到 [qMin, qMax]。

### 实例 5：cdist::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, CreateMask, Duplicate, LoadAlign, MaskMergeMode, MaskPattern, MaskReg, ReduceSum, RegTensor, StoreUnAlign, StoreUnAlignPost, Sub, Truncate, UnalignRegForStore, UpdateMask
- **Mins 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: 在 cdist 距离计算中，对 |x1-x2| 的 truncate 结果用 Mins 取 min(·, 1.0) 限制到上界 1，然后 ReduceSum 累加得到 clamp 后的距离和。

（行 517-539）

```cpp
for (uint16_t m = 0; m < loopNumM; m++) {
    __local_mem__ float * x1OffsetNorm0 = srcPtrX1 + b * pSize_ * MAlign_ + p * MAlign_ + vlLen_ * m;
    __local_mem__ float * x2OffsetNorm0 = srcPtrX2 + b * rSize_ * MAlign_ + r * MAlign_ + vlLen_ * m;
    Reg::LoadAlign(x1RegNorm0, x1OffsetNorm0);
    Reg::LoadAlign(x2RegNorm0, x2OffsetNorm0);
    Reg::Sub(subRegNorm0, x1RegNorm0, x2RegNorm0, maskAllNorm0);
    Reg::Abs(absRegNorm0, subRegNorm0, maskAllNorm0);
    Reg::Truncate<float, RoundMode::CAST_CEIL, Reg::MaskMergeMode::ZEROING>(castRegNorm0, absRegNorm0, maskAllNorm0);
    Reg::Mins(minRegNorm0, castRegNorm0, (float)1, maskAllNorm0);
    Reg::ReduceSum(sumRegNorm0, minRegNorm0, maskAllNorm0);
    Reg::Add(dstRegNorm0, dstRegNorm0, sumRegNorm0, maskOneNorm0);
}
__local_mem__ float * x1OffsetNorm0 = srcPtrX1 + b * pSize_ * MAlign_ + p * MAlign_ + vlLen_ * loopNumM;
__local_mem__ float * x2OffsetNorm0 = srcPtrX2 + b * rSize_ * MAlign_ + r * MAlign_ + vlLen_ * loopNumM;
Reg::LoadAlign(x1RegNorm0, x1OffsetNorm0);
Reg::LoadAlign(x2RegNorm0, x2OffsetNorm0);
Reg::Sub(subRegNorm0, x1RegNorm0, x2RegNorm0, maskTailNorm0);
Reg::Abs(absRegNorm0, subRegNorm0, maskTailNorm0);
Reg::Truncate<float, RoundMode::CAST_CEIL, Reg::MaskMergeMode::ZEROING>(castRegNorm0, absRegNorm0, maskTailNorm0);
Reg::Mins(minRegNorm0, castRegNorm0, (float)1, maskTailNorm0);
Reg::ReduceSum(sumRegNorm0, minRegNorm0, maskTailNorm0);
Reg::Add(dstRegNorm0, dstRegNorm0, sumRegNorm0, maskOneNorm0);
Reg::StoreUnAlign(yOffsetNorm0, dstRegNorm0, uRegNorm0, BASE_ONE);
```

**要点**:
1. Mins 用于实现 min(|x1-x2|, 1) 上界截断，常见于 clamp 距离度量（如 clipped 距离），标量 (float)1 直接传入。
2. 4 参数无模板参形态 Reg::Mins(dst, src, (float)1, mask)，类型由 RegTensor 推导为 float。
3. 主循环用 maskAllNorm0，尾部块用 maskTailNorm0 分别处理对齐与尾部元素，累加后 StoreUnAlign 存回。

### 实例 6：adaptive_avg_pool2d_grad::VecScope_L466

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, Arange, CreateMask, DataCopy, Div, Duplicate, MaskPattern, MaskReg, Maxs, Mul, RegTensor, Sub, UpdateMask
- **Mins 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 在自适应平均池化反向计算中，将池化窗口结束位置 hEdGlobal 用 Mins 限制到 tile 边界 hTileEnd 内，配合 Maxs(hStGlobal, hTileStart) 实现窗口与 tile 的交集，避免窗口超出当前 tile 范围。

（行 482-500）

```cpp
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
```

**要点**:
1. Mins 用于将窗口结束索引限制到 tile 边界 hTileEnd，配合 Maxs(hStGlobal, hTileStart) 实现窗口与 tile 的交集裁剪。
2. 4 参数无模板参形态 Mins(dst, src, scalar, Mask)，注意 mask 形参标识符大写 Mask（INDEX 类型标量场景）。
3. 索引运算常用于池化窗口裁剪，hAllMask 为全量 predicate，hBatchMask 用于批次维度存储。

### 实例 7：sigmoid_cross_entropy_with_logits_v2::CalcBCEWithLogitsV2

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, DataCopy, Duplicate, Exp, Log, MaskReg, Mul, Neg, PostLiteral, RegTensor, Sub, UpdateMask
- **Mins 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 在 BCE with logits 损失中，用 Mins(regMinVal, regX, 0.0f) 取 min(x, 0) 得到 x 的负部，配合 Abs/Exp 计算 log-sum-exp 数值稳定形式的 sigmoid 损失。

（行 87-95）

```cpp
if constexpr (HAS_POS_WEIGHT) {
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(regPosWeight, posWeightAddr,
                                                                   (int32_t)oneRepeat);
}

Reg::Mins(regMinVal, regX, (T)0.0f, pregUp);
Reg::Abs(regAbsX, regX, pregUp);
Reg::Neg(regNegAbsX, regAbsX, pregUp);
Reg::Exp(regExpNegAbsX, regNegAbsX, pregUp);
```

**要点**:
1. Mins 在 __aicore__ 上下文中无 mask 形态 Mins(dst, src, 0.0f, pregUp)，pregUp 是全量 predicate 寄存器（非 MaskReg）。
2. 用于拆分 x 的正负部实现 log-sum-exp 稳定计算，是 BCE with logits loss 的标准 trick。
3. 标量 (T)0.0f 作为分界点，取 min(x, 0) 得到 x 的负部用于后续 max(x,0)+log(1+exp(-|x|)) 公式。

### 实例 8：swiglu_group_quant::VFProcessSwigluGroupQuantVf

- **来源类型**: `__simd_vf__`
- **共现 API**: Abs, Add, Adds, Div, LoadDist, MaskPattern, Max, Maxs, Mul, Muls, StoreDist, Sub
- **Mins 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 在 group 量化 SwiGLU 中，当 hasClampValue 为真时，对左右两路输入 x0Left/x0Right 和 x1Left/x1Right 用 Mins 截断到 clampValue 上界，配合 Maxs 取 -clampValue 下界，实现双向 clamp 后接 VFSwiGlu 计算。

（行 560-569）

```cpp
if constexpr (hasClampValue) {
    Mins(x0Left, x0Left, clampValue, pregMain);
    Mins(x0Right, x0Right, clampValue, pregMain);
    Maxs(x1Left, x1Left, -clampValue, pregMain);
    Mins(x1Left, x1Left, clampValue, pregMain);
    Maxs(x1Right, x1Right, -clampValue, pregMain);
    Mins(x1Right, x1Right, clampValue, pregMain);
}
VFSwiGlu(xLeft, x0Left, x1Left, one, tmp, pregMain);
VFSwiGlu(xRight, x0Right, x1Right, one, tmp, pregMain);
```

**要点**:
1. Mins 在 __simd_vf__ 中裸名调用 Mins(x0, x0, clampValue, pregMain)，无 AscendC::Reg::/Reg:: 前缀（VEC_SCOPE 内白名单匹配）。
2. 同一作用域对 4 路变量（左右 × 输入门控）分别 Mins+Maxs 双向 clamp，pregMain 是循环 predicate 寄存器。
3. clamp 后接 VFSwiGlu 计算 SwiGLU 输出，hasClampValue 为编译期 constexpr 分支控制是否启用 clamp。

### 实例 9：smooth_l1_loss_grad::SmoothL1LossGradVFBf16

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, DataCopy, LoadDist, MaskReg, Maxs, Mul, Muls, RegTensor, StoreDist, Sub, UpdateMask
- **Mins 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 smooth L1 loss 梯度计算中，对 diff = predict - label 用 Mins(cReg, diff, sigmaVal) 取上界 σ，配合 Maxs(cReg, -σ) 实现 [-σ, σ] 裁剪，再乘以 1/σ 得到分段梯度系数。

（行 99-118）

```cpp
for (uint16_t i = 0; i < repeatTimes; ++i) {
    mask = AscendC::Reg::UpdateMask<float>(count);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        predictRegB, predictAddr + i * fp32Lane);
    AscendC::Reg::Cast<float, bfloat16_t, g_castWiden>(predictRegF, predictRegB, mask);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(labelRegB,
                                                                                          labelAddr + i * fp32Lane);
    AscendC::Reg::Cast<float, bfloat16_t, g_castWiden>(labelRegF, labelRegB, mask);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(doutRegB,
                                                                                          doutAddr + i * fp32Lane);
    AscendC::Reg::Cast<float, bfloat16_t, g_castWiden>(doutRegF, doutRegB, mask);
    AscendC::Reg::Sub(diffReg, predictRegF, labelRegF, mask);
    AscendC::Reg::Mins(cReg, diffReg, sigmaVal, mask);
    AscendC::Reg::Maxs(cReg, cReg, negSigmaVal, mask);
    AscendC::Reg::Muls(sReg, cReg, recipSigmaVal, mask);
    AscendC::Reg::Mul(gradReg, sReg, doutRegF, mask);
    AscendC::Reg::Cast<bfloat16_t, float, g_castNarrow>(dstRegB, gradReg, mask);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::StoreDist::DIST_PACK_B32>(dstAddr + i * fp32Lane,
                                                                                         dstRegB, mask);
}
```

**要点**:
1. bf16 路径：先 DataCopy 加载 bf16 → Cast widen 到 fp32 → 计算 → Cast narrow 回 bf16 存储，Mins 在 fp32 域完成。
2. Mins+Maxs 实现将 diff 裁剪到 [-σ, σ]，是 smooth L1 (Huber) 梯度的核心：c = clamp(diff, -σ, σ)，s = c/σ。
3. 循环 UpdateMask<float>(count) 处理尾部元素，mask 每轮重新计算以覆盖剩余元素。

### 实例 10：relu6_d::Relu6DVFBf16

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, DataCopy, LoadDist, MaskReg, Maxs, RegTensor, StoreDist, UpdateMask
- **Mins 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 ReLU6 反向（relu6_d）中，对 widen 后的 fp32 输入用 Maxs 取下界 0，再用 Mins 取上界 6*scale（upperThr），实现 ReLU6 的 clamp(x, 0, 6*scale) 正向结果用于反向 mask 计算。

（行 91-105）

```cpp
for (uint16_t i = 0; i < repeatTimes; ++i) {
    uint32_t rem = count - static_cast<uint32_t>(i) * fp32Lane;
    mask = AscendC::Reg::UpdateMask<float>(rem);
    // 载入 bf16(2B) 到 fp32 lane 布局 → widen 到 fp32
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(srcRegB,
                                                                                          srcAddr + i * fp32Lane);
    AscendC::Reg::Cast<float, bfloat16_t, g_relu6dCastWiden>(regF, srcRegB, mask);
    // fp32 两步 clamp（float 标量，backend 原生支持）
    AscendC::Reg::Maxs(regF, regF, lowerBound, mask); // Step 1: max(x, 0)
    AscendC::Reg::Mins(regF, regF, upperThr, mask);   // Step 2: min(·, 6*scale)
    // narrow 回 bf16（CAST_RINT）→ 存回 2B
    AscendC::Reg::Cast<bfloat16_t, float, g_relu6dCastNarrow>(dstRegB, regF, mask);
    AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::StoreDist::DIST_PACK_B32>(dstAddr + i * fp32Lane,
                                                                                         dstRegB, mask);
}
```

**要点**:
1. bf16 路径：DataCopy 加载 bf16 → Cast widen 到 fp32 → Maxs/Mins clamp → Cast narrow 回 bf16 存储。
2. Mins(regF, regF, upperThr, mask) 实现上界 6*scale 截断，upperThr = 6*scale 是 ReLU6 的标准上界。
3. mask 来自 UpdateMask<float>(rem)，rem 按剩余元素数计算，处理尾部 repeat 不满的情况。

### 实例 11：acts_ulq::MinsVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, CreateAddrReg, LoadAlign, MaskReg, RegTensor, StoreAlign, UpdateMask
- **Mins 调用次数**: 1
- **参数模式**: `T1_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: acts_ulq 算子中封装的 MinsVF helper 函数，循环 repeatTimes 次：CreateAddrReg 计算偏移 → UpdateMask 计算掩码 → LoadAlign 加载 → Mins<T>(dstReg, srcReg, scalar, mask) 标量截断 → StoreAlign 存回。

（行 491-502）

```cpp
{
    AscendC::Reg::RegTensor<T> srcReg, dstReg;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, dstAddr, aReg);
        AscendC::Reg::Mins<T>(dstReg, srcReg, scalar, mask);
        AscendC::Reg::StoreAlign(dstAddr, dstReg, aReg, mask);
    }
}
```

**要点**:
1. 唯一的 T1 模板参形态 Mins<T>(dst, src, scalar, mask)，仅显式指定数据类型 T，其余模板参由编译器推导。
2. 这是与官方调用示例最接近的最小封装形态，展示 LoadAlign/Mins/StoreAlign 标准三联。
3. AddrReg + oneRepeatSize 实现按 repeat 步进，UpdateMask<T>(count) 处理尾部元素掩码。

### 实例 12：avg_pool_v2_grad::ComputeDivisor

- **来源类型**: `__aicore__`
- **共现 API**: Adds, MaskReg, Max, RegTensor, Sub, UpdateMask
- **Mins 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 avg_pool_v2_grad 的 ComputeDivisor 中，计算池化窗口结束位置 wEndReg = wStart + kW，用 Mins(wEndReg, wEndReg, wOutput+padRightW) 限制不超过右 padding 边界，COUNT_PAD=0 时再 Mins(wEndReg, wOutput) 限制到输出宽度。

（行 317-334）

```cpp
{
    uint32_t numT = count;
    AscendC::Reg::MaskReg maskT = AscendC::Reg::UpdateMask<T, Trait>(numT);
    AscendC::Reg::RegTensor<T, Trait> wStartReg;
    AscendC::Reg::RegTensor<T, Trait> wEndReg;

    AscendC::Reg::Adds(wStartReg, outWStart, T(-padW), maskT);
    AscendC::Reg::Adds(wEndReg, wStartReg, T(kW), maskT);
    AscendC::Reg::Mins(wEndReg, wEndReg, T(wOutput + padRightW), maskT);

    if constexpr (COUNT_PAD == 0) {
        AscendC::Reg::Max(wStartReg, wStartReg, zeroConstRegT, maskT);
        AscendC::Reg::Mins(wEndReg, wEndReg, wOutput, maskT);
    }

    AscendC::Reg::Sub(divisorW, (AscendC::Reg::RegTensor<int32_t>&)wEndReg,
                           (AscendC::Reg::RegTensor<int32_t>&)wStartReg, maskT);
}
```

**要点**:
1. Mins 用于将窗口结束索引裁剪到 [wOutput+padRightW] 或 [wOutput] 边界，是池化窗口计算的标准用法。
2. __aicore__ 上下文，4 参数无模板参形态，T 由 RegTensor<T, Trait> 推导，Trait 携带类型 trait 信息。
3. 两次 Mins 实现不同 pad 模式下的窗口边界约束：COUNT_PAD=0 时额外限制到 wOutput，再 Sub 得到有效窗口大小。

### 实例 13：pool_3d_common::CalcWindowSize

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, Maxs, Muls, Sub
- **Mins 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 3D 池化窗口大小计算中，INCLUDE_PAD 模式下用 Mins(tmp1, tmp1, dInAndBackendPad) 将窗口结束限制到输入+后端 pad，非 pad 模式下用 Mins(tmp1, tmp1, dIn) 限制到输入尺寸。

（行 890-901）

```cpp
if constexpr (INCLUDE_PAD) {
    Reg::Mins(tmp1, tmp1, dInAndBackendPad, mask);
} else {
    Reg::Maxs(tmp2, tmp2, (T)0, mask);
    Reg::Mins(tmp1, tmp1, dIn, mask);
}
Reg::Sub(tmp1, tmp1, tmp2, mask);
if constexpr (std::is_same<T, int32_t>::value) {
    Reg::Cast<float, T, CAST_INT32_TO_FP32>(res, tmp1, mask);
} else {
    Reg::Cast<float, T, CAST_INT64_TO_FP32>(res, tmp1, mask);
}
```

**要点**:
1. Mins 在 if constexpr INCLUDE_PAD 分支中实现两种窗口边界策略：pad 时裁剪到 dInAndBackendPad，非 pad 时裁剪到 dIn。
2. 4 参数无模板参形态，mask 全量；配合 Sub/Maxs 计算有效窗口大小（end - start）。
3. 结果按 int32_t/int64_t 类型分别 Cast 到 fp32 输出，是池化窗口归一化除数的预处理步骤。

### 实例 14：avg_pool::CalcWindowSize

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, Maxs, Muls, Sub
- **Mins 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 avg_pool 的 CalcWindowSize 中，结构与 pool_3d_common 一致：INCLUDE_PAD 时 Mins(tmp1, dInAndBackendPad)，否则 Mins(tmp1, dIn)，得到有效窗口大小后 Sub 计算并 Cast 到 fp32。

（行 836-847）

```cpp
if constexpr (INCLUDE_PAD) {
    Reg::Mins(tmp1, tmp1, dInAndBackendPad, mask);
} else {
    Reg::Maxs(tmp2, tmp2, 0, mask);
    Reg::Mins(tmp1, tmp1, dIn, mask);
}
Reg::Sub(tmp1, tmp1, tmp2, mask);
if constexpr (std::is_same<T, int32_t>::value) {
    Reg::Cast<float, T, CAST_INT32_TO_FP32>(res, tmp1, mask);
} else {
    Reg::Cast<float, T, CAST_INT64_TO_FP32>(res, tmp1, mask);
}
```

**要点**:
1. 与 pool_3d_common 相同的窗口边界裁剪模式，体现 Mins 在 2D/3D 池化算子中的复用。
2. 非 pad 分支 Maxs(tmp2, 0, mask) 标量 0 直接传入（无 (T) 强转），与 pool_3d_common 的 (T)0 写法略有差异但语义等价。
3. __aicore__ 上下文，与 Cast 配合完成整数到浮点的转换，用于后续 avg_pool 归一化除法。

### 实例 15：swiglu_group::VFProcessSwigluVf

- **来源类型**: `__simd_vf__`
- **共现 API**: LoadDist, Maxs, Mul
- **Mins 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 在 swiglu_group 算子中，hasClampValue 时对输入 x0 用 Mins(x0, x0, clampValue, pregFixed) 截断到上界，对门控 x1 用 Maxs(-clampValue)+Mins(clampValue) 双向 clamp，然后 VFSwiGlu 计算输出。

（行 118-126）

```cpp
if constexpr (hasClampValue) {
    Mins(x0, x0, clampValue, pregFixed);
    Maxs(x1, x1, -clampValue, pregFixed);
    Mins(x1, x1, clampValue, pregFixed);
}
VFSwiGlu(y, x0, x1, tmp, pregFixed);
if constexpr (hasTopkWeight) {
    Mul(y, y, weight, pregFixed);
}
```

**要点**:
1. Mins 裸名调用，pregFixed 是固定 predicate（非循环），与实例 8 的 pregMain 循环 predicate 形成对比。
2. 最小共现 API（仅 LoadDist/Maxs/Mul），展示 Mins 在简洁 SwiGLU clamp 中的纯粹用法。
3. clamp + VFSwiGlu + 可选 Mul(topk weight) 的标准模式，hasClampValue/hasTopkWeight 均为编译期 constexpr 分支。

### Mins 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | Mins+Maxs 标量 clamp 量化范围 [qMin,qMax]，3 模板参 ZEROING | __VEC_SCOPE__ |
| clipped_swiglu | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | Mins+Maxs 双向 clamp 输入到 [-clampLimit,clampLimit] 稳定 sigmoid | __VEC_SCOPE__ |
| swiglu_mx_quant | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | 循环分块 Mins+Maxs clamp 后接 SwiGLU，处理 dim1 维 VF 尾部 | __VEC_SCOPE__ |
| fake_quant_affine_cachemask | Adds, Cast, DataCopy, Div, DivSpecificMode | Mins 构造 [0,1] mask 因子 + 量化范围裁剪，2 模板参 float | __VEC_SCOPE__ |
| cdist | Abs, Add, CreateMask, Duplicate, LoadAlign | Mins(·,1.0) 截断距离上界 + ReduceSum 累加，无模板参 | __VEC_SCOPE__ |
| adaptive_avg_pool2d_grad | Add, Adds, Arange, CreateMask, DataCopy | Mins 窗口索引裁剪到 tile 边界 hTileEnd，Mask 大写标识 | __VEC_SCOPE__ |
| sigmoid_cross_entropy_with_logits_v2 | Abs, Adds, DataCopy, Duplicate, Exp | Mins(x,0) 拆分正负部做 log-sum-exp 稳定 BCE，无 mask | __aicore__ |
| swiglu_group_quant | Abs, Add, Adds, Div, LoadDist | 裸名 Mins 4 路双向 clamp 后 VFSwiGlu，simd_vf 无 mask | __simd_vf__ |
| smooth_l1_loss_grad | Cast, DataCopy, LoadDist, MaskReg, Maxs | bf16 widen 后 Mins+Maxs 裁剪 diff 到 [-σ,σ] 算 huber 梯度 | __simd_vf__ |
| relu6_d | Cast, DataCopy, LoadDist, MaskReg, Maxs | bf16 widen 后 Maxs(0)+Mins(6*scale) 实现 ReLU6 clamp | __simd_vf__ |
| acts_ulq | AddrReg, CreateAddrReg, LoadAlign, MaskReg | MinsVF helper：LoadAlign/Mins<T>/StoreAlign 标准三联，1 模板参 | __simd_vf__ |
| avg_pool_v2_grad | Adds, MaskReg, Max, RegTensor | Mins 窗口结束索引裁剪到 wOutput 边界，aicore 无模板参 | __aicore__ |
| pool_3d_common | Adds, Cast, Maxs, Muls | Mins 池化窗口边界（INCLUDE_PAD 双分支），aicore | __aicore__ |
| avg_pool | Adds, Cast, Maxs, Muls | Mins 池化窗口边界（与 pool_3d_common 同模式），aicore | __aicore__ |
| swiglu_group | LoadDist, Maxs, Mul | 最小 Mins+Maxs clamp + VFSwiGlu，simd_vf 裸名无 mask | __simd_vf__ |
