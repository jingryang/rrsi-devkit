# Truncate

**页面ID:** atlasascendc_api_07_0399  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0399.html

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

将源操作数的浮点数元素截断到整数位，同时源操作数的数据类型保持不变。

#### 函数原型

```
template <typename T = DefaultType, RoundMode roundMode = RoundMode::CAST_NONE, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void Truncate(S& dstReg, S& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，dstReg/srcReg支持的数据类型为：half、float、bfloat16_t。 |
| roundMode | 舍入模式，取值如下： - RoundMode::CAST_NONE：默认值，在转换会导致精度丢失的场景下相当于CAST_RINT，其他场景下无效果；- RoundMode::CAST_RINT：返回最接近参数的整数，如果有2个整数同样接近，则会返回偶数的那个；- RoundMode::CAST_ROUND：round模式， 四舍五入求整；- RoundMode::CAST_FLOOR：floor模式，向下取整；- RoundMode::CAST_CEIL：ceil模式， 向上取整；- RoundMode::CAST_TRUNC：truncation模式， 向0取整，舍弃小数位。 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零- MERGING，当前不支持。 |
| S | srcReg/dstReg 类型，例如RegTensor<float>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 返回值

无

#### 约束说明

- 非饱和模式下，输入nan，输出nan; 输入值超出输入类型的最值范围，则输出+/-inf。
- 饱和模式下，输入nan, 输出为0，输入值超出输入类型的最值范围，则饱和为最值。
- float类型只支持不饱和模式。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void TruncVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::Truncate<T, AscendC::RoundMode::CAST_FLOOR, AscendC::Reg::MaskMergeMode::ZEROING>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Truncate 实例

### 实例 1：add_rms_norm_dynamic_mx_quant::ComputeFP4FromHalf

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Compare, CompareScalar, CreateMask, Duplicate, MaskAnd, MaskOr, MaskPattern, MaskReg, Maxs, Mul, Muls, RegTensor, Select, ShiftLefts, ShiftRights
- **Truncate 调用次数**: 2
- **参数模式**: `T2_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义（待补充）**: 在 FP4（fp4x2_e1m2）量化路径中，将浮点指数部分经 Truncate 截断到整数位，配合 Muls/ShiftRights/And 等操作完成 FP32 指数的提取与重组；默认分支同样用 Truncate 对乘以 2 的幂后的值取整。

（行 589-612）

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

**要点**: ① 仅显式两个模板参数 `float` 与上层透传的 `roundMode`，第三实参用全 1 预测寄存器 `pregAll32` 充当 mask（等价无掩码全元素操作）；② if/else 两个分支各调用一次 Truncate，分别处理 fp4x2_e1m2 路径与默认 FP32 指数路径；③ roundMode 由上层模板参数透传，舍入策略可配置。

### 实例 2：cdist::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, CreateMask, Duplicate, LoadAlign, MaskMergeMode, MaskPattern, MaskReg, Mins, ReduceSum, RegTensor, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore, UpdateMask
- **Truncate 调用次数**: 2
- **参数模式**: `T3_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 在 cdist 距离计算中，对两点之差的绝对值用 CAST_CEIL 向上取整，再 Mins 截断到 1，最后 ReduceSum 累加，实现逐元素距离的上取整累加。

（行 517-538）

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
```

**要点**: ① 显式三模板参数 `float, RoundMode::CAST_CEIL, MaskMergeMode::ZEROING`，mask 未选中元素在 dst 中置零；② 循环体与尾段各调用一次，分别用 maskAllNorm0（全量）和 maskTailNorm0（尾段）掩码；③ Truncate 不改数据类型，float 输入仍输出 float。

### 实例 3：rsqrt_grad::RsqrtGradB8

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, DataCopy, Duplicate, LoadDist, MaskMergeMode, MaskReg, Mul, Muls, RegTensor, StoreDist, Sub, UpdateMask
- **Truncate 调用次数**: 1
- **参数模式**: `T3_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 在 rsqrt 反向传播中，用 CAST_TRUNC 向 0 取整实现 mod 256 运算：将浮点值乘以 1/256 后 Truncate 截断小数位，再乘回 256 做减法得到余数，用于 int8 溢出回绕计算。

（行 131-149）

```cpp
Reg::Cast<float, half, cutsomCastTrait0>(regTensor4, regTensor6, mask);

// Compute z
Reg::Mul<float>(regTensor4, regTensor4, regTensor3, mask);
Reg::Mul<float>(regTensor3, regTensor3, regTensor3, mask);
Reg::Muls<float>(regTensor4, regTensor4, (float)(-0.5), mask);
Reg::Mul<float>(regTensor3, regTensor4, regTensor3, mask);

// Compute cast to int8 with overflow wraparound
Reg::Cast<int32_t, float, castTraitFLOAT2INT32>(regTensor1, regTensor3, mask);
Reg::And<int32_t, Reg::MaskMergeMode::ZEROING>(regTensor1, regTensor1, regTensor2, mask);
Reg::Cast<float, int32_t, castTraitINT322FLOAT>(regTensor3, regTensor1, mask);
Reg::Adds<float>(regTensor3, regTensor3, (float)128, mask);
// compute mod
Reg::Muls<float>(regTensor4, regTensor3, (float)(0.00390625), mask);
Reg::Truncate<float, RoundMode::CAST_TRUNC, Reg::MaskMergeMode::ZEROING>(regTensor4, regTensor4, mask);
Reg::Muls<float>(regTensor4, regTensor4, (float)(256), mask);
Reg::Sub<float>(regTensor3, regTensor3, regTensor4, mask);
Reg::Adds<float>(regTensor3, regTensor3, (float)(-128), mask);
```

**要点**: ① 三模板参数 `float, RoundMode::CAST_TRUNC, MaskMergeMode::ZEROING`，配 mask 逐元素操作；② Truncate 用于浮点取整实现模运算，是 int8 溢出回绕计算的关键一步；③ 输入输出均为 float，取整后小数位被丢弃但类型不变。

### 实例 4：acts_ulq::ClipBoundsVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, Adds, CreateAddrReg, Div, LoadAlign, MaskReg, Mul, RegTensor, StoreAlign, UpdateMask
- **Truncate 调用次数**: 1
- **参数模式**: `T2_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 在均匀量化 acts_ulq 中，将 `ori_clip_min / scale` 的除法结果用 CAST_RINT 就近取整得到量化格点偏移 offset，再乘回 scale 重建 clip_min/clip_max 边界。

（行 553-568）

```cpp
for (uint16_t i = 0; i < repeatTimes; ++i) {
    aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
    mask = AscendC::Reg::UpdateMask<T>(count);
    AscendC::Reg::LoadAlign(minReg, oriClipMinAddr, aReg);
    AscendC::Reg::LoadAlign(scaleReg, scaleAddr, aReg);
    // S4: offset = round(ori_clip_min / scale)
    AscendC::Reg::Div<T>(divReg, minReg, scaleReg, mask);
    AscendC::Reg::Truncate<float, AscendC::RoundMode::CAST_RINT>(roundReg, divReg, mask);
    // S5: clip_min = scale * offset
    AscendC::Reg::Mul<T>(cmReg, scaleReg, roundReg, mask);
    AscendC::Reg::StoreAlign(clipMinAddr, cmReg, aReg, mask);
    // S6: clip_max = scale * (offset + step)
    AscendC::Reg::Adds<T>(cxReg, roundReg, step, mask);
    AscendC::Reg::Mul<T>(cxReg, scaleReg, cxReg, mask);
    AscendC::Reg::StoreAlign(clipMaxAddr, cxReg, aReg, mask);
}
```

**要点**: ① Reg 命名空间两模板参数 `float, AscendC::RoundMode::CAST_RINT`，MaskMergeMode 走默认 ZEROING，第三实参传 mask；② 用 UpdateMask<T>(count) 按元素数生成掩码处理尾段；③ Truncate 完成浮点→整格点的就近舍入，是 clip 边界对齐量化的核心。

### 实例 5：acts_ulq::QuantVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, CreateAddrReg, Div, LoadAlign, MaskReg, Muls, RegTensor, StoreAlign, Sub, UpdateMask
- **Truncate 调用次数**: 1
- **参数模式**: `T2_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: 在量化前向中，将 `clamped_x / scale` 的结果用 CAST_RINT 就近取整得到 round_x，再用 (round_x - raw_x) 计算量化损失。

（行 669-684）

```cpp
for (uint16_t i = 0; i < repeatTimes; ++i) {
    aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
    mask = AscendC::Reg::UpdateMask<T>(count);
    AscendC::Reg::LoadAlign(cxReg, clampedXAddr, aReg);
    AscendC::Reg::LoadAlign(scaleReg, scaleAddr, aReg);
    // S10: raw_x = clamped_x / scale
    AscendC::Reg::Div<T>(rawReg, cxReg, scaleReg, mask);
    // S11: round_x = round(raw_x)
    AscendC::Reg::Truncate<float, AscendC::RoundMode::CAST_RINT>(roundReg, rawReg, mask);
    // Store round_x
    AscendC::Reg::StoreAlign(roundXAddr, roundReg, aReg, mask);
    // S12a: clamped_loss = (round_x - raw_x) * inv_step
    AscendC::Reg::Sub<T>(diffReg, roundReg, rawReg, mask);
    AscendC::Reg::Muls<T>(lossReg, diffReg, invStep, mask);
    AscendC::Reg::StoreAlign(clampedLossAddr, lossReg, aReg, mask);
}
```

**要点**: ① 与实例 4 同属 acts_ulq 但函数不同（QuantVF vs ClipBoundsVF），均用 CAST_RINT 做格点对齐；② Reg 命名空间两模板参数 + mask 三实参调用形式；③ Truncate 输出 round_x 同时参与损失计算，体现"取整 + 残差"的典型量化模式。

### 实例 6：ceil::CeilCustom

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, MaskMergeMode, MaskReg, Or, RegTensor, RegTraitNumOne, UpdateMask
- **Truncate 调用次数**: 2
- **参数模式**: `T3_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 实现 ceil 算子：用 Truncate CAST_CEIL 对输入取整得到整数部分，再通过符号位 And/Or 拼接恢复负数向上取整的语义。

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

**要点**: ① 三模板参数 `T, RoundMode::CAST_CEIL, MaskMergeMode::ZEROING`，T 由上层模板推导；② Truncate 只截断小数位，负数 ceil 需配合 UINT32_SIGN 位运算补回符号语义；③ UpdateMask<T, RegTraitNumOne> 用单元素预测寄存器生成掩码。

### 实例 7：truncate_div::TruncCustom

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, MaskMergeMode, MaskReg, Or, RegTensor, RegTraitNumOne, UpdateMask
- **Truncate 调用次数**: 2
- **参数模式**: `T3_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 实现 truncate_div 算子：用 CAST_TRUNC 向 0 取整，再通过符号位 And/Or 处理负数截断方向，得到向零取整结果。

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

**要点**: ① 三模板参数 `T, RoundMode::CAST_TRUNC, MaskMergeMode::ZEROING`；② 与实例 6（ceil）结构一致，仅 roundMode 不同，体现 Truncate 作为多种取整算子统一底座的用法；③ DataCopy 加载/存储配合 mask 处理尾段。

### 实例 8：trunc::TruncCustom

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, MaskMergeMode, MaskReg, Or, RegTensor, RegTraitNumOne, UpdateMask
- **Truncate 调用次数**: 2
- **参数模式**: `T3_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 实现 trunc 算子：CAST_TRUNC 向 0 取整，配合符号位 And/Or 恢复截断后整数的位表示。

（行 49-61）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

    Reg::Truncate<T, RoundMode::CAST_TRUNC, Reg::MaskMergeMode::ZEROING>(vregOutput, vregInput, mask);
    Reg::Duplicate(vregOutInt, UINT32_SIGN, mask);
    Reg::And(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t> &)vregInput, mask);
    Reg::Or(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t> &)vregOutput, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), (Reg::RegTensor<T> &)vregOutInt, mask);
}
```

**要点**: ① 与实例 7（truncate_div）属不同算子但调用模式相同，验证 Truncate 在多个取整类算子中的复用；② 三模板参数 + mask，T 由模板推导；③ UINT32_SIGN And/Or 用于把浮点位模式的符号位拼回取整结果。

### 实例 9：round::RoundCustom

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, MaskMergeMode, MaskReg, Or, RegTensor, RegTraitNumOne, UpdateMask
- **Truncate 调用次数**: 2
- **参数模式**: `T3_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 实现 round 算子：CAST_RINT 就近取整（四舍六入五成偶），配合符号位 And/Or 得到 round 结果。

（行 119-131）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vl));

    Reg::Truncate<T, RoundMode::CAST_RINT, Reg::MaskMergeMode::ZEROING>(vregOutput, vregInput, mask);
    Reg::Duplicate(vregOutInt, UINT32_SIGN, mask);
    Reg::And(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t> &)vregInput, mask);
    Reg::Or(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t> &)vregOutput, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vl), (Reg::RegTensor<T> &)vregOutInt, mask);
}
```

**要点**: ① 三模板参数 `T, RoundMode::CAST_RINT, MaskMergeMode::ZEROING`；② 与实例 6/7/8 同结构，仅切换 roundMode 即可实现不同取整语义，凸显 Truncate roundMode 参数的通用性；③ 使用 vl 而非 vlSize 作为步长，说明不同算子的寄存器宽度配置可能不同。

### 实例 10：rint::RintCalc

- **来源类型**: `__aicore__`
- **共现 API**: And, Duplicate, LoadAlign, MaskMergeMode, MaskReg, Or, RegTensor, StoreAlign, UpdateMask
- **Truncate 调用次数**: 2
- **参数模式**: `T3_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: 实现 rint 算子：用 LoadAlign 加载、Truncate CAST_RINT 取整、StoreAlign 存储，并通过符号位 And/Or 拼接得到 rint 结果。

（行 48-57）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T>(count);
    Reg::LoadAlign(inputReg, srcAddr + loopIdx * vlSize);
    Reg::Truncate<T, RoundMode::CAST_RINT, Reg::MaskMergeMode::ZEROING>(outReg, inputReg,
                                                                                  mask);
    Reg::Duplicate(resultReg, UINT32_SIGN, mask);
    Reg::And(resultReg, resultReg, (Reg::RegTensor<uint32_t>&)inputReg, mask);
    Reg::Or(resultReg, resultReg, (Reg::RegTensor<uint32_t>&)outReg, mask);
    Reg::StoreAlign(dstAddr + loopIdx * vlSize, (Reg::RegTensor<T>&)resultReg, mask);
}
```

**要点**: ① 三模板参数 `T, RoundMode::CAST_RINT, MaskMergeMode::ZEROING`；② 与实例 9（round）语义相近但用 LoadAlign/StoreAlign 而非 DataCopy，体现两种访存路径的等价写法；③ UpdateMask<T>(count) 不带 RegTraitNumOne，按默认预测寄存器策略生成掩码。

### 实例 11：floor::Compute1

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, LoadDist, MaskMergeMode, Or, StoreDist, UpdateMask
- **Truncate 调用次数**: 1
- **参数模式**: `T3_A3_M0_TYPEbfloat16+float`（实参 3 个，类型: float, bfloat16）
- **语义（待补充）**: 实现 bfloat16 的 floor 算子：用 Truncate CAST_FLOOR 向下取整，再通过 BF16 符号位 And/Or 拼接得到向下取整结果。

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

**要点**: ① 三模板参数 `bfloat16_t, RoundMode::CAST_FLOOR, MaskMergeMode::ZEROING`，第三实参用 UpdateMask<bfloat16_t> 生成的 preg0（非 MaskReg mask）；② DataCopy 走 LoadDist::DIST_NORM 加载、StoreDist::DIST_NORM_B16 存储，适配 bf16 位宽；③ Truncate 不改类型，bf16 输入输出仍为 bf16。

### 实例 12：floor::Compute1

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, LoadDist, MaskMergeMode, Or, StoreDist, UpdateMask
- **Truncate 调用次数**: 1
- **参数模式**: `T3_A3_M0_TYPEhalf`（实参 3 个，类型: half）
- **语义（待补充）**: 实现 half 的 floor 算子：Truncate CAST_FLOOR 向下取整 + FP16 符号位 And/Or 拼接。

（行 92-106）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<half>(size);
    AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / sizeof(half)));
    AscendC::Reg::Truncate<
        half, AscendC::RoundMode::CAST_FLOOR, AscendC::Reg::MaskMergeMode::ZEROING>(
        vreg1, vreg0, preg0);
    AscendC::Reg::Duplicate(vreg2, FP16_SIGN1, preg0);
    AscendC::Reg::Duplicate(vreg3, FP16_SIGN2, preg0);
    AscendC::Reg::And(vreg2, vreg2, (RegTensor<uint16_t>&)vreg0, preg0);
    AscendC::Reg::And(vreg3, vreg3, (RegTensor<uint16_t>&)vreg1, preg0);
    AscendC::Reg::Or(vreg3, vreg2, vreg3, preg0);
    AscendC::Reg::DataCopy<half, AscendC::Reg::StoreDist::DIST_NORM_B16>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / sizeof(half)), (RegTensor<half>&)vreg3, preg0);
}
```

**要点**: ① 三模板参数 `half, RoundMode::CAST_FLOOR, MaskMergeMode::ZEROING`；② 与实例 11 结构相同，仅 T 切换为 half、符号常量改用 FP16_SIGN1/FP16_SIGN2；③ 体现 Truncate 对 half/float/bfloat16_t 三种支持类型的统一调用方式。

### 实例 13：floor::Compute1

- **来源类型**: `__aicore__`
- **共现 API**: And, DataCopy, Duplicate, LoadDist, MaskMergeMode, Or, StoreDist, UpdateMask
- **Truncate 调用次数**: 1
- **参数模式**: `T3_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义（待补充）**: 实现 float 的 floor 算子：Truncate CAST_FLOOR 向下取整 + FP32 符号位 And/Or 拼接。

（行 91-105）

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = AscendC::Reg::UpdateMask<float>(size);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(
        vreg0, bufferIn0Addr + i * (AscendC::VECTOR_REG_WIDTH / sizeof(float)));
    AscendC::Reg::Truncate<
        float, AscendC::RoundMode::CAST_FLOOR, AscendC::Reg::MaskMergeMode::ZEROING>(
        vreg1, vreg0, preg0);
    AscendC::Reg::Duplicate(vreg2, FP32_SIGN1, preg0);
    AscendC::Reg::Duplicate(vreg3, FP32_SIGN2, preg0);
    AscendC::Reg::And(vreg2, vreg2, (RegTensor<uint32_t>&)vreg0, preg0);
    AscendC::Reg::And(vreg3, vreg3, (RegTensor<uint32_t>&)vreg1, preg0);
    AscendC::Reg::Or(vreg3, vreg2, vreg3, preg0);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_NORM_B32>(
        bufferOut0Addr + i * (AscendC::VECTOR_REG_WIDTH / sizeof(float)), (RegTensor<float>&)vreg3, preg0);
}
```

**要点**: ① 三模板参数 `float, RoundMode::CAST_FLOOR, MaskMergeMode::ZEROING`；② 与实例 11/12 同构，T=float、符号常量 FP32_SIGN1/FP32_SIGN2、StoreDist::DIST_NORM_B32；③ 实例 11/12/13 合起来覆盖 Truncate 支持的全部三种数据类型（half/float/bfloat16_t）的 floor 实现。

### 实例 14：truncate_div::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, DataCopy, Duplicate, MaskMergeMode, Or, RegTensor, RegTraitNumOne, UpdateMask
- **Truncate 调用次数**: 1
- **参数模式**: `T3_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: truncate_div 算子的 __VEC_SCOPE__ 上下文版本，用 CAST_TRUNC 向 0 取整 + 符号位 And/Or，与实例 7（__aicore__ 版）逻辑等价但作用域不同。

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

**要点**: ① 三模板参数 `T, RoundMode::CAST_TRUNC, MaskMergeMode::ZEROING`，与 __aicore__ 版完全一致；② 同一算子在 __aicore__ 与 __VEC_SCOPE__ 两种作用域下均有 Truncate 调用，说明该 API 跨作用域通用；③ 函数名标记为 Reg::RegTensor（抽取器按调用点所在函数/类型命名），实际属 truncate_div 的向量计算段。

### 实例 15：round::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, DataCopy, Duplicate, MaskMergeMode, Or, RegTensor, RegTraitNumOne, UpdateMask
- **Truncate 调用次数**: 1
- **参数模式**: `T3_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义（待补充）**: round 算子的 __VEC_SCOPE__ 上下文版本，CAST_RINT 就近取整 + 符号位拼接，与实例 9（__aicore__ 版）等价。

（行 119-131）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vl));

    Reg::Truncate<T, RoundMode::CAST_RINT, Reg::MaskMergeMode::ZEROING>(vregOutput, vregInput, mask);
    Reg::Duplicate(vregOutInt, UINT32_SIGN, mask);
    Reg::And(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t> &)vregInput, mask);
    Reg::Or(vregOutInt, vregOutInt, (Reg::RegTensor<uint32_t> &)vregOutput, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vl), (Reg::RegTensor<T> &)vregOutInt, mask);
}
```

**要点**: ① 三模板参数 `T, RoundMode::CAST_RINT, MaskMergeMode::ZEROING`；② 与实例 9 对照，体现同一取整逻辑在两种作用域下的复用；③ 与实例 14（truncate_div VEC）共同覆盖 __VEC_SCOPE__ 作用域下的 Truncate 调用样例。

### Truncate 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| add_rms_norm_dynamic_mx_quant | Adds, And, Compare, CompareScalar, CreateMask | Reg 双模板 float+roundMode，pregAll32 全量掩码，FP4 量化指数截断 | __aicore__ |
| cdist | Abs, Add, CreateMask, Duplicate, LoadAlign | Reg 三模板 float+CAST_CEIL+ZEROING，mask 逐元素，距离上取整累加 | __VEC_SCOPE__ |
| rsqrt_grad | Adds, And, Cast, DataCopy, Duplicate | Reg 三模板 float+CAST_TRUNC+ZEROING，mask 逐元素，浮点 mod 运算 | __aicore__ |
| acts_ulq | AddrReg, Adds, CreateAddrReg, Div, LoadAlign | Reg 双模板 float+CAST_RINT，mask 三实参，量化格点就近取整 | __simd_vf__ |
| acts_ulq | AddrReg, CreateAddrReg, Div, LoadAlign, MaskReg | Reg 双模板 float+CAST_RINT，mask 三实参，量化取整+残差损失 | __simd_vf__ |
| ceil | And, DataCopy, Duplicate, MaskMergeMode, MaskReg | Reg 三模板 T+CAST_CEIL+ZEROING，符号位 And/Or 拼 ceil | __aicore__ |
| truncate_div | And, DataCopy, Duplicate, MaskMergeMode, MaskReg | Reg 三模板 T+CAST_TRUNC+ZEROING，符号位 And/Or 拼 trunc | __aicore__ |
| trunc | And, DataCopy, Duplicate, MaskMergeMode, MaskReg | Reg 三模板 T+CAST_TRUNC+ZEROING，与 truncate_div 同构 | __aicore__ |
| round | And, DataCopy, Duplicate, MaskMergeMode, MaskReg | Reg 三模板 T+CAST_RINT+ZEROING，符号位拼接四舍六入五成偶 | __aicore__ |
| rint | And, Duplicate, LoadAlign, MaskMergeMode, MaskReg | Reg 三模板 T+CAST_RINT+ZEROING，LoadAlign/StoreAlign 路径 | __aicore__ |
| floor | And, DataCopy, Duplicate, LoadDist, MaskMergeMode | Reg 三模板 bfloat16_t+CAST_FLOOR+ZEROING，preg0 掩码 | __aicore__ |
| floor | And, DataCopy, Duplicate, LoadDist, MaskMergeMode | Reg 三模板 half+CAST_FLOOR+ZEROING，preg0 掩码 | __aicore__ |
| floor | And, DataCopy, Duplicate, LoadDist, MaskMergeMode | Reg 三模板 float+CAST_FLOOR+ZEROING，preg0 掩码 | __aicore__ |
| truncate_div | And, DataCopy, Duplicate, MaskMergeMode, Or | Reg 三模板 T+CAST_TRUNC+ZEROING，__VEC_SCOPE__ 作用域 | __VEC_SCOPE__ |
| round | And, DataCopy, Duplicate, MaskMergeMode, Or | Reg 三模板 T+CAST_RINT+ZEROING，__VEC_SCOPE__ 作用域 | __VEC_SCOPE__ |
