# Maxs

**页面ID:** atlasascendc_api_07_0384  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0384.html

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

源操作数矢量内每个元素与标量相比，如果比标量大，则取源操作数值，比标量的值小，则取标量值。计算公式如下：

![](images/atlasascendc_api_07_0384_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, typename U, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void Maxs(S& dstReg, S& srcReg, U scalarValue, MaskReg& mask)
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
| scalarValue | 输入 | 源操作数。 类型为标量。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MaxsVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, T scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Maxs(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Maxs 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Maxs 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义（待补充）**: MX 量化求 scale 时，先归约得全块最大指数，再用 Maxs 将其下限钳到 maxLowBound_，避免后续乘 invMax 时出现 0 或极小值导致数值不稳定。

（行 486-510）

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
maskNum = static_cast<uint32_t>(dataLen);
mask = Reg::CreateMask<uint32_t>();
maskNum = static_cast<uint32_t>(dataLen);
// 求scale
Reg::Interleave(expMax, tmp16RegTensor, expMax, tmp16RegTensor);
Reg::Cast<float, T, castTraitZero>((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<T>&)expMax, mask);

Reg::Compare<uint32_t, CMPMODE::LT>(infMask, maxFP32RegTensor, absMaskFP32RegTensor, mask);
Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, maxFP32RegTensor, fp32ZeroRegTensor, mask);

Reg::Maxs((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<float>&)maxFP32RegTensor,
          this->maxLowBound_, mask);

Reg::Mul((Reg::RegTensor<float>&)maxFP32RegTensor, (Reg::RegTensor<float>&)maxFP32RegTensor,
         (Reg::RegTensor<float>&)invMaxRegTensor, mask);
```

**要点**: 1) dst==src 的 in-place 钳位，标量 maxLowBound_ 与矢量逐元素比较；2) 实参仅 1 个标量、类型 float，mask 由 CreateMask 全开；3) 与 Mul(invMax) 组合完成 scale 归一化，Maxs 是防除零前置保护。

### 实例 2：dynamic_mx_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub
- **Maxs 调用次数**: 4
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义（待补充）**: 高性能大 tail 路径按 calcMode 分支处理 mantissa：MODE_ONE 用 Maxs 把绝对值钳到 maxLowBound_ 再乘 invMax 求 scale；非 MODE_ONE 直接乘 dstTypeMaxReg。

（行 439-447）

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
```

**要点**: 1) Maxs 位于 calcMode==MODE_ONE 条件分支内，与 Mul(invMax) 配套；2) pregAll32 为全开谓词寄存器，无 mask 收窄；3) 同算子不同 calcMode 采用不同量化基准，Maxs 仅在 MODE_ONE 出现。

### 实例 3：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Maxs 调用次数**: 1
- **参数模式**: `T3_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 伪量化 TF Nudge 中，用 Maxs 将推得的 zero-point 下界钳到 qMin，再用 Mins 钳上界 qMax，得到 nudged_zp。

（行 403-421）

```cpp
// 2.3b invScaleSafe = qRange / diffSafe
//      TF Nudge() 独立计算 inv_scale = (qMax-qMin)/(max-min)，
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
```

**要点**: 1) 显式模板参数 <float,float,MaskMergeMode::ZEROING>，mode=ZEROING 时 mask 未选中元素在 dst 置零；2) Maxs/Mins 成对构成 clip(x,qMin,qMax)；3) 标量 qMin 与矢量逐元素比较，mask 控制有效元素。

### 实例 4：clipped_swiglu::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Div, Exp, LoadDist, MaskPattern, MaskReg, Mins, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **Maxs 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: clipped SwiGLU 中对 gate 路 vregX2DeF 先 Mins(clampLimit) 再 Maxs(negClampLimit) 做对称钳位 [-clampLimit, clampLimit]，保证激活有界后再加偏置。

（行 372-410）

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

AscendC::Reg::Mul(outFReg, sigmoidReg, vregX2DeF, mask);
```

**要点**: 1) Maxs 标量为负值 negClampLimit，实现下界钳位 max(x,-clampLimit)；2) 与 Mins 配对构成对称 clip，是 clipped 激活典型用法；3) mask 由 UpdateMask/CreateMask 给出，控制尾块有效元素。

### 实例 5：swiglu_mx_quant::VecScope_L446

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Div, Exp, LoadDist, MaskPattern, MaskReg, Mins, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **Maxs 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: swiglu_mx_quant 末轴路径对 gate 路 vregX2DeF 用 Maxs 钳到 negClampLimit 下界，配合 Mins(clampLimit) 实现对称钳位后做 SwiGLU。

（行 469-487）

```cpp
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
```

**要点**: 1) 与实例 4 同属 clamp 模式但位于末轴处理文件；2) Maxs 标量为 negClampLimit（负），dst==src in-place；3) 钳位后紧跟 Adds(gluBias) 加偏置再 Mul 出 outFReg。

### 实例 6：fake_quant_affine_cachemask::AscendC::LocalTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, DataCopy, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskReg, Mins, Mul, MulDstAdd, Muls, RegTensor, StoreDist, Sub, UpdateMask
- **Maxs 调用次数**: 3
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: affine 伪量化中，先用 Maxs(...,0.0f) 把掩码中间量钳到非负，再用 Maxs(vregQ,qMinF)+Mins(qMaxF) 把量化输出 clip 到 [qMin,qMax]。

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

**要点**: 1) 同一 kernel 内 Maxs 多次出现，既做非负钳位又做量化范围 clip；2) 显式模板 <float,float>，mask 控制有效 lane；3) in-place 写法 dst==src1 避免 cross-register 未写状态。

### 实例 7：add_rms_norm_dynamic_mx_quant::ComputeFP4FromHalf

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Compare, CompareScalar, CreateMask, Duplicate, MaskAnd, MaskOr, MaskPattern, MaskReg, Mul, Muls, RegTensor, Select, ShiftLefts, ShiftRights, Truncate
- **Maxs 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: FP4 量化中提取 FP32 指数后，用 Maxs(...,0) 把指数下限钳到 0，防止负指数在后续 bias/shift 运算中产生异常值。

（行 589-611）

```cpp
if constexpr (IsSame<T_Y, fp4x2_e1m2_t>::value) {
    AscendC::Reg::Muls(Reg, Reg, FOUR, pregAll32);
    AscendC::Reg::CompareScalar<float, CMPMODE::LT>(specialMask, Reg, 0, pregAll32);
    AscendC::Reg::Truncate<float, roundMode>(Reg, Reg, pregAll32);
    AscendC::Reg::Muls(Reg, Reg, ONE_FOURTH, pregAll32);
} else {
    AscendC::Reg::Duplicate(maxExpFP32, MAX_EXP_FOR_FP32);
    AscendC::Reg::And(exp0FP32, (AscendC::Reg::RegTensor<int32_t>&)Reg, maxExpFP32, pregAll32);
    AscendC::Reg::ShiftRights(exp0FP32, exp0FP32, SHR_NUM_FOR_FP32, pregAll32);
    AscendC::Reg::Adds(exp0FP32, exp0FP32, FP32_BIAS_NEG, pregAll32);
    AscendC::Reg::Maxs(exp0FP32, exp0FP32, 0, pregAll32);
    AscendC::Reg::Adds(exp0FP32, exp0FP32, NEG_ONE, pregAll32);
    AscendC::Reg::Muls(exp1FP32, exp0FP32, NEG_ONE, pregAll32);
    AscendC::Reg::Adds(exp1FP32, exp1FP32, FP32_BIAS, pregAll32);
    AscendC::Reg::ShiftLefts(exp1FP32, exp1FP32, SHR_NUM_FOR_FP32, pregAll32);

    AscendC::Reg::Mul(Reg, Reg, (AscendC::Reg::RegTensor<float>&)exp1FP32, pregAll32);
    AscendC::Reg::Adds(exp0FP32, exp0FP32, FP32_BIAS, pregAll32);
    AscendC::Reg::ShiftLefts(exp0FP32, exp0FP32, SHR_NUM_FOR_FP32, pregAll32);
    AscendC::Reg::CompareScalar<float, CMPMODE::LT>(specialMask, Reg, 0, pregAll32);
    AscendC::Reg::Truncate<float, roundMode>(Reg, Reg, pregAll32);
    AscendC::Reg::Mul(Reg, Reg, (AscendC::Reg::RegTensor<float>&)exp0FP32, pregAll32);
}
```

**要点**: 1) 标量为整型 0，矢量 exp0FP32 为 float，pregAll32 全开无 mask；2) Maxs 是指数归一化链 And→ShiftRights→Adds→Maxs 的一环；3) 与 ShiftLefts/Adds 组合重建 FP32 浮点表示。

### 实例 8：adaptive_avg_pool2d_grad::VecScope_L466

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, Arange, CreateMask, DataCopy, Div, Duplicate, MaskPattern, MaskReg, Mins, Mul, RegTensor, Sub, UpdateMask
- **Maxs 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: 自适应平均池化反向中，用 Maxs 把全局起始索引 hStGlobal 钳到不小于 tile 起点 hTileStart，随后减去 hTileStart 转为局部索引。

（行 479-497）

```cpp

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
```

**要点**: 1) 索引类型 INDEX 上调用 Maxs（非浮点），mask 名 hAllMask（大写 M，全开）；2) Maxs→Adds(-hTileStart) 组合完成钳位再偏移的区间映射；3) 与 Mins(hTileEnd) 配对限定 [tileStart,tileEnd]。

### 实例 9：sigmoid_cross_entropy_with_logits::CalcSigmoidCrossEntropyWithLogits

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, DataCopy, Duplicate, Exp, Log, MaskReg, Mul, Neg, RegTensor, RegTraitNumOne, Sub, UpdateMask
- **Maxs 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: 数值稳定的 sigmoid 交叉熵中，用 Maxs(vregPredict,0.0f) 计算 max(predict,0)，作为公式 max(x,0)-x*z+log(1+exp(-|x|)) 的一项。

（行 67-93）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);

    Reg::DataCopy(vregPredict, (__ubuf__ T*)(src0Addr + loopIdx * vlSize));
    Reg::DataCopy(vregTarget, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));

    Reg::Duplicate(vregOneAddExp, (T)1.0f, mask);

    Reg::Maxs(vregMaxPredict, vregPredict, (T)0.0f, mask);

    Reg::Abs(vregAbsPredict, vregPredict, mask);
    Reg::Neg(vregNegAbsPredict, vregAbsPredict, mask);

    Reg::Exp(vregExpNegAbs, vregNegAbsPredict, mask);

    Reg::Add(vregOneAddExp, vregExpNegAbs, vregOneAddExp, mask);

    Reg::Log(vregLog, vregOneAddExp, mask);

    Reg::Mul(vregMulPredictTarget, vregPredict, vregTarget, mask);

    Reg::Sub(vregOutput, vregMaxPredict, vregMulPredictTarget, mask);
    Reg::Add(vregOutput, vregOutput, vregLog, mask);

    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**要点**: 1) 标量为 (T)0.0f，实现 ReLU 式下界钳位；2) 与 Abs/Neg/Exp/Log 组合构成数值稳定损失；3) mask 由 UpdateMask+RegTraitNumOne 给出。

### 实例 10：swiglu_group_quant::VFProcessSwigluGroupQuantVf

- **来源类型**: `__simd_vf__`
- **共现 API**: Abs, Add, Adds, Div, LoadDist, MaskPattern, Max, Mins, Mul, Muls, StoreDist, Sub
- **Maxs 调用次数**: 3
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 两处 Maxs：片段1用 Maxs(...,-clampValue) 对 SwiGLU gate 做对称钳位；片段2用 Maxs(scale,0.0001f) 给 amax 缩放因子设下限 1e-4 防止除零。

**片段 1** (行 560-568):

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
```

**片段 2** (行 579-608):

```cpp
    StoreOutputData<T1>(yOriginLocalAddr, xLeft, pregMain, 2 * j * VL_FP32 + i * curColNumAlign);
    StoreOutputData<T1>(yOriginLocalAddr, xRight, pregMain, (2 * j + 1) * VL_FP32 + i * curColNumAlign);
}
Muls(xAbsLeft, xLeft, 0.0f, pregMain);
Compare<float, CMPMODE::NE>(compareLeft, xAbsLeft, xAbsLeft, pregMain);
MaskNot(compareLeft, compareLeft, pregMain);
Abs(xAbsLeft, xLeft, compareLeft);
ReduceMax(scale0, xAbsLeft, pregMain);

Muls(xAbsRight, xRight, 0.0f, pregMain);
Compare<float, CMPMODE::NE>(compareRight, xAbsRight, xAbsRight, pregMain);
MaskNot(compareRight, compareRight, pregMain);
Abs(xAbsRight, xRight, compareRight);
ReduceMax(scale1, xAbsRight, pregMain);
Max(scale, scale0, scale1, pregMerge);
Maxs(clampScale, scale, 0.0001f, pregMerge); // amax

Mul(scale, clampScale, (RegTensor<float>&)coeff, pregMerge);
if constexpr (!hasRoundScale) {
    Div(invScale, invCoeff, clampScale, pregMerge);
    StoreAlign<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        (__ubuf__ float*)scaleLocalAddr + j + i * scaleColNum, scale, pregMerge); // copy out scale
} else {
    // bits == (RegTensor<uint32_t>&)scale
    ShiftRights(scale2, (RegTensor<uint32_t>&)scale, static_cast<int16_t>(FAST_LOG_SHIFT_BITS), pregMerge);
    And(scale2, scale2, tmp0, pregMerge);                      // exp
    And(scale3, (RegTensor<uint32_t>&)scale, tmp1, pregMerge); // man_bits
    Compare<uint32_t, AscendC::CMPMODE::NE>(compareMask0, scale3, zeroUint32, pregMerge);
    Select(tmp2, oneUint32, zeroUint32, compareMask0); // man_bits != 0
    Sub(scale3, scale2, tmp3, pregMerge);              // exp - 127
```

**要点**: 1) 同一 VF 函数内 Maxs 兼做激活钳位与除零保护两种用途；2) 片段2标量为浮点字面量 0.0001f，pregMerge 全开；3) clampScale 之后接 Mul(coeff)/Div(invScale) 完成量化缩放。

### 实例 11：smooth_l1_loss_grad::SmoothL1LossGradVFBf16

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, DataCopy, LoadDist, MaskReg, Mins, Mul, Muls, RegTensor, StoreDist, Sub, UpdateMask
- **Maxs 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: smooth L1 损失梯度中，对 predict-label 差值先 Mins(sigma) 再 Maxs(negSigmaVal) 实现 clip(diff,-sigma,sigma)，把差值限制在线性区间。

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

**要点**: 1) Maxs 标量为 negSigmaVal（-sigma），与 Mins(sigmaVal) 配对成对称 clip；2) bf16 输入先 Cast 到 float 再做 Maxs，最后窄回 bf16；3) clip 后 Muls(recipSigmaVal) 得梯度系数。

### 实例 12：dequantize::DequantizeMinFirstOffsetPreVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, CreateAddrReg, Div, LoadAlign, MaskReg, Muls, RegTensor, StoreAlign, Sub, UpdateMask
- **Maxs 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: min-first 反量化中，对 (max-min) 范围用 Maxs(rangeReg,1e-30f) 设下限，防止后续 Div(tmpReg,rangeReg) 除零。

（行 62-72）

```cpp
for (uint16_t i = 0; i < repeatTimes; ++i) {
    aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
    mask = AscendC::Reg::UpdateMask<T>(count);
    AscendC::Reg::LoadAlign(minReg, minAddr, aReg);
    AscendC::Reg::LoadAlign(maxReg, maxAddr, aReg);
    AscendC::Reg::Sub(rangeReg, maxReg, minReg, mask);
    AscendC::Reg::Maxs(rangeReg, rangeReg, 1e-30f, mask);
    AscendC::Reg::Muls(tmpReg, minReg, -255.0f, mask);
    AscendC::Reg::Div(tmpReg, tmpReg, rangeReg, mask);
    AscendC::Reg::StoreAlign(tempAddr, tmpReg, aReg, mask);
}
```

**要点**: 1) 标量为极小浮点 1e-30f，是典型除零保护下限；2) 用 CreateAddrReg/LoadAlign 按偏移加载 min/max 再 Sub 求范围；3) mask 由 UpdateMask(count) 处理尾块。

### 实例 13：relu6_d::Relu6DVF

- **来源类型**: `__simd_vf__`
- **共现 API**: LoadAlign, MaskReg, Mins, RegTensor, StoreAlign, UpdateMask
- **Maxs 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: relu6 反向中，用 Maxs(dstReg,srcReg,lowerBound) 做下截断 max(x,0)，再用 Mins 上截断到 6*scale，实现 relu6=clip(x,0,6*scale)。

（行 61-68）

```cpp
for (uint16_t i = 0; i < repeatTimes; ++i) {
    uint32_t rem = count - static_cast<uint32_t>(i) * oneRepeatSize;
    mask = AscendC::Reg::UpdateMask<T>(rem);
    AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
    AscendC::Reg::Maxs(dstReg, srcReg, lowerBound, mask); // Step 1: 下截断 max(x, 0)
    AscendC::Reg::Mins(dstReg, dstReg, upperThr, mask);   // Step 2: 上截断 min(·, 6*scale)
    AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
}
```

**要点**: 1) Maxs+Mins 经典 clip 组合，lowerBound 通常为 0；2) 用 LoadAlign/StoreAlign 对齐加载存储，UpdateMask(rem) 处理尾块；3) dst!=src（非 in-place），结果写入新寄存器。

### 实例 14：instance_norm::CalculateRstd

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Div, Mul, Muls, Sqrt
- **Maxs 调用次数**: 1
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: instance_norm 求 rstd 时，对 var+epsilon 用 Maxs(var,var,SCALAR0) 设下限，保证后续 Div(1/var) 与 Sqrt 不会因 var 为 0 或负而异常。

（行 636-666）

```cpp
for (uint16_t i = 0; i < loopRows; ++i) {
    pregLoop = UpdateMask<float>(sreg);
    Duplicate(scalarInf, POS_INF, pregLoop);
    Duplicate(scalarZero, float(0.0), pregLoop);
    Duplicate(one, float(1.0), pregLoop);
    Duplicate(scalar1, SCALAR3, pregLoop);
    Duplicate(t1, SCALAR2, pregLoop);
    Duplicate(s, float(1.0), pregLoop);
    // rstd
    DataCopy(var, varUb + i * VL_FP32);
    Adds(var, var, epsilon, pregLoop);
    Maxs(var, var, SCALAR0, pregLoop);
    Div(r, one, var, pregLoop);
    Sqrt(y, r, pregLoop);
    Muls(t, var, SCALAR1, pregLoop);
    Mul(t, t, y, pregLoop);                // -0.5 * x * y
    Mula(t1, t, y, pregLoop);              // 1.5 + (-0.5 * x * y) * y
    Mul(rstd, y, t1, pregLoop);            // y = y * (1.5 - 0.5 * x * y)
    Muls(t3, var, float(-1.0), pregLoop);  // -1 * x
    Mula(s, t3, r, pregLoop);              // 1 + (-1) * x * r
    Muls(t4, rstd, float(-1.0), pregLoop); // (-1) * y
    Mula(r, t4, rstd, pregLoop);           // r + (-1) * y * y
    Mula(s, var, r, pregLoop);             // s + x * t
    Mul(s, s, rstd, pregLoop);             // e * y
    Mula(rstd, s, scalar1, pregLoop);      // y + y * e * 0.5
    CompareScalar(cmpRegZero, var, POS_INF, pregLoop);
    Select(rstd, scalarZero, rstd, cmpRegZero);
    CompareScalar(cmpRegInf, var, float(0.0), pregLoop);
    Select(rstd, scalarInf, rstd, cmpRegInf);
    DataCopy(rstdInUb + i * VL_FP32, rstd, pregLoop);
}
```

**要点**: 1) SCALAR0 为下限常量，pregLoop 按行更新（无 mask 收窄参数）；2) Maxs 是 Newton-Raphson rsqrt 迭代前的数值保护；3) 之后用 Select 对 var==inf/0 做 rstd 特殊值兜底。

### 实例 15：binary_cross_entropy::CalcYLogX

- **来源类型**: `__aicore__`
- **共现 API**: Log, Mul, RegTensor
- **Maxs 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 二值交叉熵中，对 Log(x) 结果用 Maxs(...,-100.0) 钳到下限 -100，防止 x→0 时 log(x)=-inf 污染 y*log(x) 计算。

（行 39-94）

```cpp
{
    Reg::RegTensor<U> regLogX;
    Reg::RegTensor<U> regClipLogX;
    Reg::Log(regLogX, regX, pregUp);
    Reg::Maxs(regClipLogX, regLogX, (U)-100.0, pregUp);
    Reg::Mul(regYLogX, regClipLogX, regY, pregUp);
}
#endif
template <typename U = float>
struct CalcBinaryYLogX : public Ops::Base::Vec::ElemwiseBinaryOP<U, U, U> {
    __aicore__ inline CalcBinaryYLogX(Ops::Base::LocalTensor<U>& yLogX, Ops::Base::LocalTensor<U>& x,
                                      Ops::Base::LocalTensor<U>& y, int32_t count)
    {
#ifdef __CCE_AICORE__

        uint32_t oneRepeat = VECTOR_LENGTH / sizeof(U);
        uint32_t totalLen = count;
        uint32_t repeatTimes = Ops::Base::CeilDiv<uint32_t>(totalLen, oneRepeat);

        __ubuf__ U* xAddr = (__ubuf__ U*)x.GetPhyAddr();
        __ubuf__ U* yAddr = (__ubuf__ U*)y.GetPhyAddr();
        __ubuf__ U* yLogXTAddr = (__ubuf__ U*)yLogX.GetPhyAddr();

        __VEC_SCOPE__
        {
            Reg::MaskReg pregUp;
            Reg::RegTensor<U> regX;
            Reg::RegTensor<U> regY;
            Reg::RegTensor<U> regTensorOne;
            Reg::RegTensor<U> regOneSubX;
            Reg::RegTensor<U> regOneSubY;
            Reg::RegTensor<U> regOneSubYLogX;
            Reg::RegTensor<U> regYLogX;
            Reg::RegTensor<U> regDataSum;
            Reg::RegTensor<U> regBinaryYLogX;

            for (uint16_t loop = 0; loop < (uint16_t)repeatTimes; loop++) {
                pregUp = Reg::UpdateMask<U>(totalLen);
                Reg::DataCopy<U, Reg::PostLiteral::POST_MODE_UPDATE>(regX, xAddr, (int32_t)oneRepeat);
                Reg::DataCopy<U, Reg::PostLiteral::POST_MODE_UPDATE>(regY, yAddr, (int32_t)oneRepeat);

                CalcYLogX<U>(regYLogX, regX, regY, pregUp);
                Reg::Duplicate(regTensorOne, (U)1.0f, pregUp);
                Reg::Sub(regOneSubX, regTensorOne, regX, pregUp);
                Reg::Sub(regOneSubY, regTensorOne, regY, pregUp);
                CalcYLogX<U>(regOneSubYLogX, regOneSubX, regOneSubY, pregUp);
                Reg::Add(regDataSum, regYLogX, regOneSubYLogX, pregUp);
                Reg::Muls(regBinaryYLogX, regDataSum, (U)-1.0f, pregUp);

                Reg::DataCopy<U, Reg::PostLiteral::POST_MODE_UPDATE>(yLogXTAddr, regBinaryYLogX,
                                                                               (int32_t)oneRepeat, pregUp);
            }
        }
#endif
    }
};
```

**要点**: 1) 标量为 (U)-100.0（大负数），是 log 裁剪典型下限；2) 仅 RegTensor/Log/Mul 共现，结构极简；3) pregUp 为谓词寄存器，无显式 mask 收窄参数（T0_A4_M0）。

### Maxs 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 指数归约后 Maxs 钳下限 maxLowBound_，配合 Mul(invMax) 求 scale | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 按 calcMode 分支用 Maxs 钳 mantissa 下限，再乘 invMax/dstTypeMaxReg | __VEC_SCOPE__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | Maxs+Mins 对 zero-point 做 clip(x,qMin,qMax)，显式 ZEROING mode | __VEC_SCOPE__ |
| clipped_swiglu | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | Mins(clampLimit)+Maxs(negClampLimit) 对称钳位 gate 路 | __VEC_SCOPE__ |
| swiglu_mx_quant | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | Mins+Maxs(negClampLimit) 对称钳位 gate，末轴变体 | __VEC_SCOPE__ |
| fake_quant_affine_cachemask | Adds, Cast, DataCopy, Div, DivSpecificMode | Maxs(...,0) 非负钳位 + Maxs(qMin)+Mins(qMax) 量化范围 clip | __VEC_SCOPE__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Compare, CompareScalar, CreateMask | Maxs(...,0) 钳 FP32 指数下限，指数归一化链一环 | __aicore__ |
| adaptive_avg_pool2d_grad | Add, Adds, Arange, CreateMask, DataCopy | Maxs(idx,tileStart) 钳全局索引下限再偏移为局部索引 | __VEC_SCOPE__ |
| sigmoid_cross_entropy_with_logits | Abs, Add, DataCopy, Duplicate, Exp | Maxs(x,0) 求 max(x,0)，数值稳定损失公式一项 | __aicore__ |
| swiglu_group_quant | Abs, Add, Adds, Div, LoadDist | Maxs(-clamp) 激活对称钳位 + Maxs(scale,1e-4) amax 除零保护 | __simd_vf__ |
| smooth_l1_loss_grad | Cast, DataCopy, LoadDist, MaskReg | Mins(sigma)+Maxs(negSigma) 对差值对称 clip 到线性区 | __simd_vf__ |
| dequantize | AddrReg, CreateAddrReg, Div, LoadAlign, MaskReg | Maxs(range,1e-30) 给 (max-min) 设下限防 Div 除零 | __simd_vf__ |
| relu6_d | LoadAlign, MaskReg, Mins, RegTensor | Maxs(x,0)+Mins(6*scale) 经典 relu6 clip | __simd_vf__ |
| instance_norm | Adds, Div, Mul, Muls | Maxs(var,SCALAR0) 给 var+epsilon 设下限，保护 rsqrt | __aicore__ |
| binary_cross_entropy | Log, Mul, RegTensor | Maxs(log(x),-100) 钳 log 下限防 -inf | __aicore__ |

