# Neg

**页面ID:** atlasascendc_api_07_0352  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0352.html

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

根据mask对输入数据srcReg进行取相反数操作，将结果写入dstReg。neg计算公式如下：

![](images/atlasascendc_api_07_0352_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Neg(U& dstReg, U& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/int16_t/int32_t/int64_t/half/float |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dstReg中置零。- MERGING，暂不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void NegVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Neg(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Neg 实例

### 实例 1：sinh::SinhCustomVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, CompareScalar, DataCopy, Div, DivSpecificMode, Duplicate, Exp, MaskMergeMode, MaskReg, Mul, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **Neg 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 sinh 算子的指数分支中，用 Neg 对 Exp 结果取相反数以恢复负输入的符号，得到 sign(x)·sinh(|x|)；溢出保护处再用 Neg 由 +inf 构造 -inf。

（行 113-143）

```cpp
// === Exp branch: offset-exp to avoid overflow ===
// shifted = |x| - ln2
AscendC::Reg::Adds(reg_temp, reg_abs, neg_ln2, mask);
// t = e^(|x| - ln2) = e^|x| / 2
AscendC::Reg::Exp(reg_exp, reg_temp, mask);
// inv_t = 0.25 / t = e^(-|x|) / 2
AscendC::Reg::Duplicate(reg_temp, quarter_val);
AscendC::Reg::Div<T, &divMode>(reg_temp, reg_temp, reg_exp, mask);
// exp_result = t - 0.25/t = e^|x|/2 - e^(-|x|)/2 = sinh(|x|)
AscendC::Reg::Sub(reg_exp, reg_exp, reg_temp, mask);
// reg_exp now holds Exp result (positive, = sinh(|x|))

// === Sign recovery for exp branch: x < 0 ? -exp_result : exp_result ===
// Must apply BEFORE branch selection because Taylor already has correct sign
AscendC::Reg::CompareScalar<T, CMPMODE::LT>(cmpMask0, reg_x, zero_val, mask);
AscendC::Reg::Neg(reg_temp, reg_exp, mask);
AscendC::Reg::Select(reg_exp, reg_temp, reg_exp, cmpMask0);
// reg_exp now holds signed exp result: sign(x) * sinh(|x|)

// === Branch selection: |x| < 1 ? Taylor : Exp ===
AscendC::Reg::CompareScalar<T, CMPMODE::LT>(cmpMask1, reg_abs, one_val, mask);
AscendC::Reg::Select(reg_result, reg_poly, reg_exp, cmpMask1);

// === Overflow guard: |x| >= 90 ? sign(x)*inf : result ===
AscendC::Reg::CompareScalar<T, CMPMODE::GE>(cmpMask1, reg_abs, ninety_val, mask);
// Create signed infinity: +inf for x >= 0, -inf for x < 0
AscendC::Reg::Duplicate(reg_temp, inf_val);          // +inf
AscendC::Reg::Neg(reg_exp, reg_temp, mask);          // -inf (reuse reg_exp)
AscendC::Reg::Select(reg_temp, reg_exp, reg_temp, cmpMask0); // sign(x)*inf
// Apply overflow: |x| >= 90 ? sign(x)*inf : branch_result
AscendC::Reg::Select(reg_result, reg_temp, reg_result, cmpMask1);
```

**要点**:
- Neg 用于符号恢复模式：CompareScalar 生成符号 mask → Neg 取反 → Select 选回，等价于三元运算 x<0?-x:x。
- dstReg 与 srcReg 可复用同一寄存器（reg_temp 既是输入又被后续覆盖），节省寄存器。
- Neg 调用次数 4，覆盖符号恢复与溢出保护两处取负需求。

### 实例 2：swish_grad::SwishGradCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, DataCopy, Div, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **Neg 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: swish 梯度计算中用 Neg 对缩放后的输入取相反数，得到 -x 后送入 Exp 计算 e^{-x}，构造 sigmoid 分母 1/(1+e^{-x})。

**片段 1** (行 63-82):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::DataCopy(vregInput2, (__ubuf__ T*)(src2Addr + loopIdx * vlSize));
    Reg::Muls(vregInput, vregInput, scale1, mask);
    Reg::Neg(vregInputMid, vregInput, mask);
    Reg::Exp(vregInputMid, vregInputMid, mask);
    Reg::Adds(vregInputMid, vregInputMid, (float)1.0, mask);
    Reg::Div(vregInputMid, vregValue1, vregInputMid, mask);

    Reg::Sub(vregOutput, vregValue1, vregInputMid, mask);
    Reg::Mul(vregOutput, vregOutput, vregInput, mask);
    Reg::FusedMulDstAdd(vregOutput, vregInputMid, vregInputMid, mask);
    Reg::Mul(vregOutput, vregOutput, vregInput2, mask);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), (Reg::RegTensor<T>&)vregOutput,
                       mask);
}
```

**片段 2** (行 91-116):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(
        vregInput16, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(
        vregInput162, (__ubuf__ T*)(src2Addr + loopIdx * vlSize));
    Reg::Cast<float, T, castTrait0>(vregInput, vregInput16, mask);
    Reg::Cast<float, T, castTrait0>(vregInput2, vregInput162, mask);

    Reg::Muls(vregInput, vregInput, scale1, mask);
    Reg::Neg(vregInputMid, vregInput, mask);
    Reg::Exp(vregInputMid, vregInputMid, mask);
    Reg::Adds(vregInputMid, vregInputMid, (float)1.0, mask);
    Reg::Div(vregInputMid, vregValue1, vregInputMid, mask);

    Reg::Sub(vregOutput, vregValue1, vregInputMid, mask);
    Reg::Mul(vregOutput, vregOutput, vregInput, mask);
    Reg::FusedMulDstAdd(vregOutput, vregInputMid, vregInputMid, mask);
    Reg::Mul(vregOutput, vregOutput, vregInput2, mask);

    Reg::Cast<T, float, castTrait1>(vregOutput16, vregOutput, mask);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_PACK_B32>((__ubuf__ T*)(dstAddr + loopIdx * vlSize),
                                                              vregOutput16, mask);
}
```

**要点**:
- 典型指数取负模式：Muls 缩放 → Neg → Exp → Adds(+1) → Div，构造 sigmoid 函数。
- 两片段分别处理 fp32 与 fp16/bf16（经 Cast 转换），Neg 调用形式一致。
- mask 来自 UpdateMask，控制尾部不满 repeat 的有效元素。

### 实例 3：round::RoundIntCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, And, CompareScalar, DataCopy, Div, Duplicate, MaskAnd, MaskOr, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **Neg 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: round 算子中用 Neg 对常量寄存器 1 取反得到 -1，再通过 Select 按输入符号选择 ±1，实现对负数的符号化舍入修正。

（行 75-93）

```cpp
Reg::Mul(vregMul, vregDiv, vregPow, mask);
Reg::Sub(vregReUse, vregReUse, vregMul, mask);
Reg::Muls(vregMul, vregReUse, ConstTwo, mask);

// + 1
Reg::CompareScalar<T, CMPMODE::EQ>(cmpMaskReg0, vregMul, power, mask);
Reg::And(vregReUse, vregDiv, vregDupOne, mask);
Reg::CompareScalar<T, CMPMODE::EQ>(cmpMaskReg1, vregReUse, ConstOne, mask);
Reg::MaskAnd(cmpMaskReg0, cmpMaskReg0, cmpMaskReg1, mask);
Reg::CompareScalar<T, CMPMODE::GT>(cmpMaskReg1, vregMul, power, mask);
Reg::MaskOr(cmpMaskReg0, cmpMaskReg0, cmpMaskReg1, mask);
Reg::Select(vregMul, vregDupOne, vregDupZero, cmpMaskReg0);
Reg::Add(vregMul, vregDiv, vregMul, mask);

Reg::CompareScalar<T, CMPMODE::LT>(cmpMaskReg0, vregInput, ConstZero, mask);
Reg::Neg(vregReUse, vregDupOne, mask);
Reg::Select(vregDiv, vregReUse, vregDupOne, cmpMaskReg0);
Reg::Mul(vregMul, vregMul, vregDiv, mask);
Reg::Mul(vregReUse, vregMul, vregPow, mask);
```

**要点**:
- Neg 作用于常量寄存器 vregDupOne 生成 -1，用于后续带符号乘法修正。
- 与 CompareScalar(LT,0) + Select 组合实现负数取 -1、正数取 +1 的符号选择。
- mask 控制逐元素有效性，符合带掩码矢量运算语义。

### 实例 4：softplus_v2_grad::SoftplusV2GradVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, Adds, Compare, CreateAddrReg, Div, Exp, LoadAlign, MaskReg, Mul, Muls, RegTensor, Select, StoreAlign, Sub, UpdateMask
- **Neg 调用次数**: 2
- **参数模式**: `T1_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: softplus_v2_grad 中先 Muls 得 β·x，再用 Neg 取反得到 -βx，送入 Exp 构造 e^{-βx}，进而算 1+e^{-βx} 的梯度，并配合阈值分支选择输出。

（行 87-125）

```cpp
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

    // S8: Compare(T1, regThresh, GT) → cmpMask
    AscendC::Reg::Compare<T, AscendC::CMPMODE::GT>(cmpMask, regT1, regThresh, padMask);

    // S9: Select(cmpMask, input_gradients, T5) → dstReg
    AscendC::Reg::Select<T>(dstReg, src1Reg, regT5, cmpMask);

    // --- Store: Reg → UB ---
    AscendC::Reg::StoreAlign(dst, dstReg, aReg, padMask);
}
```

**要点**:
- 显式带模板参数 Neg<T>，来源类型 __simd_vf__（Reg 命名空间），与 Reg 风格不同。
- 参数模式 T1（含 1 个模板参数）+ Mask 形参，使用 LoadAlign/StoreAlign 地址寄存器流。
- 经 Compare+Select 做阈值分支：当 βx 超阈值时直接取 input_gradients，跳过数值不稳定区间。

### 实例 5：sigmoid_cross_entropy_with_logits_v2::CalcBCEWithLogitsV2

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, DataCopy, Duplicate, Exp, Log, MaskReg, Mins, Mul, PostLiteral, RegTensor, Sub, UpdateMask
- **Neg 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: BCE 损失中用 Neg 对 |x| 取反得 -|x|，再 Exp+Adds(+1)+Log 构造 log(1+e^{-|x|})，实现数值稳定的 log-sigmoid。

（行 87-97）

```cpp
if constexpr (HAS_POS_WEIGHT) {
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(regPosWeight, posWeightAddr,
                                                                   (int32_t)oneRepeat);
}

Reg::Mins(regMinVal, regX, (T)0.0f, pregUp);
Reg::Abs(regAbsX, regX, pregUp);
Reg::Neg(regNegAbsX, regAbsX, pregUp);
Reg::Exp(regExpNegAbsX, regNegAbsX, pregUp);
Reg::Adds(regOneAddExp, regExpNegAbsX, (T)1.0f, pregUp);
Reg::Log(regLog, regOneAddExp, pregUp);
```

**要点**:
- 参数模式 M0（无 mask 形参，用 pregUp 全量掩码）。
- Neg 与 Abs+Exp+Log 组合实现 log(1+e^{-|x|})，避免大 x 直接计算 e^x 溢出。
- 与 Mins 配合取 min(x,0) 处理符号侧，保证正向损失非负。

### 实例 6：sigmoid_cross_entropy_with_logits::CalcSigmoidCrossEntropyWithLogits

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, DataCopy, Duplicate, Exp, Log, MaskReg, Maxs, Mul, RegTensor, RegTraitNumOne, Sub, UpdateMask
- **Neg 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: sigmoid 交叉熵中用 Neg 对 |predict| 取反得 -|predict|，Exp 后加 1 再 Log，得到 log(1+e^{-|p|})，与 max(p,0)-p·t 组合得最终损失。

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

**要点**:
- 与 Maxs/Abs/Exp/Log 组合，标准 log(1+e^{-|x|}) 数值稳定写法。
- mask 来自 UpdateMask，控制尾部不满 repeat 的元素。
- Neg 是该公式链中取负入指数、避免正向溢出的关键一步。

### 实例 7：softmax_grad::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, MaskMergeMode, MaskPattern, MaskReg, Mul, RegTensor, UpdateMask
- **Neg 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: softmax 反向中用 Neg 对输入 reg0 取反，配合 MulAddDst 一步计算 grad·x - x·sum，等价于 x·(grad-sum) 的融累加形式。

（行 197-220）

```cpp
for (uint16_t i = 0; i < loopTimes; i++) {
    LoadTensorForDtypeTIn(x0, reg0, pFull, i * rAligned);
    LoadTensorForDtypeTIn(x1, reg1, pFull, i * rAligned);
    LoadTensorForDtypeTIn(x0_1, reg0_1, pMask, i * rAligned);
    LoadTensorForDtypeTIn(x1_1, reg1_1, pMask, i * rAligned);

    Mul(reg2, reg0, reg1, pFull);
    Mul(reg2_1, reg0_1, reg1_1, pMask);

    Add<float, AscendC::Reg::MaskMergeMode::ZEROING>(reg2_1, reg2, reg2_1, pMask);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(reg2, reg2_1, pMask);
    ReduceSum(reg2, reg2, pFull);
    Duplicate(reg2, reg2, pFull);

    Mul(reg1, reg0, reg1, pFull);
    Neg(reg0, reg0, pFull);
    MulAddDst(reg1, reg0, reg2, pFull);
    StoreTensorForDtypeTOut(dst, reg1, pFull, i * rAligned);

    Mul(reg1_1, reg0_1, reg1_1, pMask);
    Neg(reg0_1, reg0_1, pMask);
    MulAddDst(reg1_1, reg0_1, reg2, pMask);
    StoreTensorForDtypeTOut(dst, reg1_1, pMask, i * rAligned + VL_FP32);
}
```

**要点**:
- 参数模式 M0（无 mask 形参，用 pFull/pMask 两套掩码）。
- Neg+MulAddDst 组合实现 grad·x - x·sum 的融累加，比分开 Mul/Sub 更高效。
- 同时处理 full 与 mask 两套寄存器（reg0/reg0_1），覆盖完整与尾部元素。

### 实例 8：softmax_grad::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, MaskMergeMode, MaskPattern, MaskReg, Mul, RegTensor, UpdateMask
- **Neg 调用次数**: 1
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: softmax 反向（full_load 版本）按 maskOri 分块加载 x0/x1，Neg 取反 x0 后 MulAddDst 累加 -x0·sum 到 x1，输出梯度。

（行 405-416）

```cpp
for (uint16_t j = 0; j < rLoopCount; j++) {
    maskOri = AscendC::Reg::UpdateMask<float>(sreg0);
    uint32_t offset = j * VL_FP32 + i * oriRAligned;

    LoadTensorForDtypeTIn(x0, reg0, maskOri, offset);
    LoadTensorForDtypeTIn(x1, reg1, maskOri, offset);

    Mul(reg1, reg0, reg1, maskOri);
    Neg(reg0, reg0, maskOri);
    MulAddDst(reg1, reg0, reg2, maskOri);
    StoreTensorForDtypeTOut(dst, reg1, maskOri, offset);
}
```

**要点**:
- 参数模式 M1+mask，mask 来自 UpdateMask<float>(sreg0) 按剩余长度生成。
- 与实例 13 同算子同模式但带显式 mask 形参，处理尾部分块。
- Neg 调用次数 1，单次取负即完成梯度公式中的减法项。

### 实例 9：scatter_add::NegateUpdateVf

- **来源类型**: `__simd_vf__`
- **共现 API**: DataCopy, Duplicate, MaskReg, Mul, RegTensor, UpdateMask
- **Neg 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask+maskReg`（实参 3 个，含 mask/mode: mask, maskReg）
- **语义**: scatter_add 的 bfloat16 分支用 Mul×(-1) 代替 Neg，而通用类型分支直接用 Neg 对 updates 取反实现负更新。

（行 108-133）

```cpp
if constexpr (IsSameType<T, bfloat16_t>::value) {
    Reg::RegTensor<bfloat16_t> updatesValue;
    Reg::RegTensor<bfloat16_t> scalarReg;
    Reg::RegTensor<bfloat16_t> dstReg;
    Reg::MaskReg maskReg;
    uint32_t count = dataLen;
    bfloat16_t scalarValue = -1;
    Reg::Duplicate(scalarReg, scalarValue);
    for (uint16_t j = 0; j < loopTimes; j++) {
        maskReg = Reg::UpdateMask<T>(count);
        Reg::DataCopy(updatesValue, updatesAddr + loopSize * j);
        Reg::Mul(dstReg, updatesValue, scalarReg, maskReg);
        Reg::DataCopy(updatesAddr + loopSize * j, dstReg, maskReg);
    }
} else {
    Reg::RegTensor<T> updatesValue;
    Reg::RegTensor<T> negValue;
    Reg::MaskReg maskReg;
    uint32_t count = dataLen;
    for (uint16_t j = 0; j < loopTimes; j++) {
        maskReg = Reg::UpdateMask<T>(count);
        Reg::DataCopy(updatesValue, updatesAddr + loopSize * j);
        Reg::Neg(negValue, updatesValue, maskReg);
        Reg::DataCopy(updatesAddr + loopSize * j, negValue, maskReg);
    }
}
```

**要点**:
- 参数模式独特：mask+maskReg（同时含 MaskReg 与 mask 形参）。
- 展示 Neg 与 Mul 标量 -1 两种取负等价写法：bf16 因类型不支持 Neg 走 Mul 路径。
- __simd_vf__ 来源，Reg 命名空间风格，循环内 UpdateMask 后逐块取负存回。

### 实例 10：softmax_grad::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, MaskPattern, MaskReg, Mul, RegTensor, UpdateMask
- **Neg 调用次数**: 1
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: softmax 反向（mask 路径）用 Neg 对 reg0 取反，配合 MulAddDst 计算 grad·x - x·sum 的 mask 分支版本。

（行 167-180）

```cpp
for (uint16_t i = 0; i < loopTimes; i++) {
    LoadTensorForDtypeTIn(x0, reg0, pMask, i * rAligned);
    LoadTensorForDtypeTIn(x1, reg1, pMask, i * rAligned);
    Mul(reg2, reg0, reg1, pMask);

    ReduceSum(reg2, reg2, pMask);
    Duplicate(reg2, reg2, pFull);

    Mul(reg1, reg0, reg1, pMask);
    Neg(reg0, reg0, pMask);
    MulAddDst(reg1, reg0, reg2, pMask);

    StoreTensorForDtypeTOut(dst, reg1, pMask, i * rAligned);
}
```

**要点**:
- 参数模式 MASKMask（形参名 Mask），用 pMask 控制部分元素。
- 与实例 13 同算子不同分块路径，仅 mask 分支无 full，先 ReduceSum+Duplicate 广播 sum。
- Neg+MulAddDst 完成梯度，mask 保证尾部正确性。

### 实例 11：softmax_grad::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: DataCopy, LoadDist, MaskReg, Mul, RegTensor, UpdateMask
- **Neg 调用次数**: 1
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: softmax 反向（recompute 版本）按 pregMask 分块加载，Neg 取反 x0Reg 后 MulAddDst 累加到 x1Reg，输出梯度。

（行 274-284）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    pregMask = AscendC::Reg::UpdateMask<float>(sreg);
    uint32_t offset = j * VL_FP32;
    LoadTensorForDtypeT(x0Local, x0Reg, pregMask, offset);
    LoadTensorForDtypeT(x1Local, x1Reg, pregMask, offset);

    Mul(x1Reg, x0Reg, x1Reg, pregMask);
    Neg(x0Reg, x0Reg, pregMask);
    MulAddDst(x1Reg, x0Reg, sumReg, pregMask);
    StoreTensorForDtypeTOut(yLocal, x1Reg, pregMask, offset);
}
```

**要点**:
- 来源文件 softmax_grad_ar_recompute.h，与 full_load/small_r 同族不同实现策略。
- 共现 API 含 LoadDist，走 DataCopy 带分发加载路径。
- Neg+MulAddDst 模式与其它 softmax_grad 实例一致，差异在分块与重计算策略。

### 实例 12：neg::NegCustom

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, MaskReg, RegTensor, RegTraitNumOne, UpdateMask
- **Neg 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: neg 算子自身的实现：DataCopy 加载输入 → Neg 取反 → DataCopy 存回，是最直接的原生 Neg 用法。

（行 42-50）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = AscendC::Reg::UpdateMask<T, AscendC::Reg::RegTraitNumOne>(count);
    // OpCopyIn0
    AscendC::Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

    AscendC::Reg::Neg(vregOutput, vregInput, mask);
    // OpCopyOut
    AscendC::Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**要点**:
- Neg 算子的原生实现，调用形式 Reg::Neg(dst, src, mask)。
- mask 来自 UpdateMask<T, RegTraitNumOne>(count)，处理尾部不满 repeat 的元素。
- 共现 API 最少（仅 DataCopy/UpdateMask），体现 Neg 的独立原子性。

### 实例 13：spence::std::is_same_v

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Div, Sub
- **Neg 调用次数**: 1
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: spence 函数中根据 y 的区间分支，当 y<0.5 时用 Neg 取反 y 得 -y 作为 w，是分段多项式选择的预处理。

（行 211-229）

```cpp
Div(t2Reg, t2Reg, xsReg, mask);
Select<float>(yReg, xsReg, t2Reg, cmpMask1);

// ============================================================
// Step 2: w based on y
//   w = 1/y - 1  if y > 1.5
//   w = -y       if y < 0.5
//   w = y - 1    if 0.5 ≤ y ≤ 1.5
// ============================================================
// w_gt = 1/y - 1
Duplicate(t1Reg, 1.0f, mask);
Div(t1Reg, t1Reg, yReg, mask);
Adds(t1Reg, t1Reg, -1.0f, mask);

// w_lt = -y
Neg(t2Reg, yReg, mask);

// w_ge = y - 1
RegTensor<float> wGeReg;
```

**要点**:
- Neg 用于分段函数的负分支取值，配合 Select 选择不同 w 表达式。
- 共现 API 极简（Adds/Div/Sub），Reg 命名空间风格。
- mask 控制逐元素，因 spence 按元素分段独立计算。

### 实例 14：softmax_grad::CalcOutput

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopy, StoreDist
- **Neg 调用次数**: 1
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: softmax 反向（small_r 版本）对 x0 取反后 MulAddDst 累加 -x0·sum 到 x1，并按数据类型 Cast 回 fp16/bf16 输出。

（行 178-193）

```cpp
for (uint16_t i = 0; i < curTileRLenVl; i++) {
    uint32_t xOffset = i * tileA0LenLocal + k * VL_FP32;
    LoadTensorForDtypeT(x0Local, x0Reg, pregMask, xOffset);

    DataCopy(x1Reg, tmpAddr2 + xOffset);
    Neg(x0Reg, x0Reg, pregMask);
    MulAddDst(x1Reg, x0Reg, sumReg, pregMask);

    if constexpr (xToFp32_) {
        Reg::DataCopy(tmpAddrTy + xOffset, x1Reg, pregMask);
    } else { // fp16、bf16
        RegTensor<T> xFp16;
        Reg::Cast<T, float, castTraitFp32ToFp16>(xFp16, x1Reg, pregMask);
        Reg::DataCopy<T, Reg::StoreDist::DIST_PACK_B32>(tmpAddrTy + xOffset, xFp16, pregMask);
    }
}
```

**要点**:
- 来源 small_r.h，处理小 r 场景，含 Cast+StoreDist 类型回写。
- Neg 后 MulAddDst，再 if constexpr 分类型 DataCopy/Cast 输出。
- pregMask 控制当前 tile 有效长度。

### 实例 15：softmax_grad::CalcOutput

- **来源类型**: `__aicore__`
- **共现 API**: Mul
- **Neg 调用次数**: 1
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: softmax 反向（ara_recompute 版本）加载 x0/x1，先 Mul 再 Neg 取反 x0，MulAddDst 累加得梯度，分类型输出。

（行 274-291）

```cpp
for (uint16_t i = 0; i < curTileRLenVl; i++) {
    uint32_t xOffset = i * tileA0Len + k * VL_FP32;
    LoadTensorForDtypeT(x0Local, x0Reg, pregMask, xOffset);
    LoadTensorForDtypeT(x1Local, x1Reg, pregMask, xOffset);

    Mul(x1Reg, x0Reg, x1Reg, pregMask);
    Neg(x0Reg, x0Reg, pregMask);
    MulAddDst(x1Reg, x0Reg, sumReg, pregMask);

    // copy out
    if constexpr (IsSameType<T, float>::value) {
        DataCopy(((__local_mem__ float*)yLocal) + xOffset, x1Reg, pregMask);
    } else { // fp16、bf16
        RegTensor<T> xFp16;
        Cast<T, float, castTraitFp32ToFp16>(xFp16, x1Reg, pregMask);
        DataCopy<T, StoreDist::DIST_PACK_B32>(((__local_mem__ T*)yLocal) + xOffset, xFp16, pregMask);
    }
}
```

**要点**:
- 与实例 22 同算子同模式，差异在 recompute 路径含 Mul(x0,x1) 先乘再取反。
- 共现 API 最简（仅 Mul），体现 Neg+MulAddDst 的核心组合。
- Cast+DataCopy 按类型回写，pregMask 控制有效元素。

### Neg 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| sinh | Abs, Add, Adds, CompareScalar, DataCopy | 符号恢复——CompareScalar 生成 mask + Neg 取反 + Select 选择，实现条件取负；溢出处构造 -inf | __aicore__ |
| swish_grad | Adds, Cast, DataCopy, Div, Duplicate | 指数取负——Muls 缩放后 Neg 取反再 Exp，构造 1/(1+e^{-x}) 类 sigmoid 分母 | __aicore__ |
| round | Add, And, CompareScalar, DataCopy, Div | 符号常量构造——Neg 对常量寄存器取反生成 -1，配合 Select 实现带符号修正 | __aicore__ |
| softplus_v2_grad | AddrReg, Adds, Compare, CreateAddrReg, Div | softplus 梯度——Muls 缩放 + Neg 取负 + Exp + Adds(+1) + Div，并配合 Compare/Select 阈值分支 | __simd_vf__ |
| sigmoid_cross_entropy_with_logits_v2 | Abs, Adds, DataCopy, Duplicate, Exp | 数值稳定 log-sigmoid——Abs 取绝对值 + Neg 取负 + Exp + Adds(+1) + Log 构造 log(1+e^{-|x|}) | __aicore__ |
| sigmoid_cross_entropy_with_logits | Abs, Add, DataCopy, Duplicate, Exp | 交叉熵稳定公式——Abs + Neg + Exp + Adds(+1) + Log 构造 log(1+e^{-|p|}) | __aicore__ |
| softmax_grad | CreateMask, MaskMergeMode, MaskPattern, MaskReg, Mul | softmax 反向融累加——Neg 取负 + MulAddDst 一步完成 grad·x - x·sum | __VEC_SCOPE__ |
| softmax_grad | CreateMask, MaskMergeMode, MaskPattern, MaskReg, Mul | softmax 反向分块——UpdateMask 生成 mask + Neg 取负 + MulAddDst 累加 | __VEC_SCOPE__ |
| scatter_add | DataCopy, Duplicate, MaskReg, Mul | 取负等价改写——通用类型用 Neg，bf16 用 Mul×(-1) 实现取反 | __simd_vf__ |
| softmax_grad | CreateMask, MaskPattern, MaskReg, Mul | softmax 反向 mask 分支——ReduceSum 广播 + Neg + MulAddDst | __VEC_SCOPE__ |
| softmax_grad | DataCopy, LoadDist, MaskReg, Mul | softmax 反向重计算——UpdateMask + Load + Neg + MulAddDst 分块累加 | __VEC_SCOPE__ |
| neg | DataCopy, MaskReg, RegTensor, RegTraitNumOne | 原生取负——DataCopy 加载 + Neg 取反 + DataCopy 存回 | __aicore__ |
| spence | Adds, Div, Sub | 分段函数负分支——Neg 取反构造 -y，配合 Select 做分段选择 | __VEC_SCOPE__ |
| softmax_grad | Cast, DataCopy, StoreDist | softmax 反向小 r——Neg + MulAddDst + Cast 分类型回写 | __aicore__ |
| softmax_grad | Mul | softmax 反向重计算——Mul 先乘 + Neg 取负 + MulAddDst 累加 | __aicore__ |
