# Abs

**页面ID:** atlasascendc_api_07_0342  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0342.html

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

对srcReg中的有效元素逐个取绝对值，并将结果写入dstReg中对应位置处。

#### 函数原型

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Abs(U& dstReg, U& srcReg, MaskReg& mask)

template <typename T = DefaultType, typename U = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S, typename V>
__simd_callee__ inline void Abs(S& dstReg, V& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/int16_t/int32_t/int64_t/half/float。 |
| U | 源操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：complex32/complex64；当U为complex32类型时，T必须是half类型；当U为complex64类型时，T必须是float类型。 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING模式下，mask未筛选的元素在dstReg中置零。- MERGING模式当前不支持。 |
| S | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| V | 源操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

整型数据的计算结果如果超出数据类型的表示范围会采取非饱和截断，比如int8类型，srcReg为-128，其绝对值128会被截断成-128。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void AbsVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask; 
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Abs(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}

template<typename T, typename U>
__simd_vf__ inline void AbsVF(__ubuf__ U* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<U> dstReg;
    AscendC::Reg::MaskReg mask; 
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Abs(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Abs 实例

### 实例 1：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Abs 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 在动态量化的缩放因子计算中，对平滑后的输入取绝对值，再用 Max 逐 repeat 累积最大绝对值，最后 ReduceMax 得到对称量化 amax。

（行 333-345）

```cpp
for (uint16_t j = 0; j < vfLoop; j++) {
    preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg1, xAddr + multiRow * rowCount + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, smoothAddr + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg0);
    AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg0);
    AscendC::Reg::Abs(vreg6, vreg3, preg0);
    AscendC::Reg::Max(vreg7, vreg6, vreg7, preg1);
}
AscendC::Reg::ReduceMax(vreg8, vreg7, preg1);
```

**要点**: 1) 无 mask 形态 Abs(vreg6, vreg3, preg0)，preg0 由 UpdateMask<float> 生成，处理尾部不足一个向量；2) Abs 结果不落盘，仅作为 Max 的输入求最大绝对值；3) 与 Mul(平滑)、Max、ReduceMax 组合构成 per-token amax。

### 实例 2：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **Abs 调用次数**: 4
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: complex64 模长计算中，对拆分后的两个分量寄存器分别取绝对值，配合 Compare/Select 把较大分量对齐到 vA，用于后续归一化数值稳定处理。

（行 103-160）

```cpp
if constexpr (std::is_same<U, complex32>::value) {
    preg2 = AscendC::Reg::CreateMask<uint16_t, AscendC::Reg::MaskPattern::ALL>();
    Reg::LoadAlign(vSrcReg0, srcAddr + i * vflen * 2);
    Reg::Cast<float, T, castTraitZero>(vA, vSrcReg0, preg2);
    Reg::Cast<float, T, castTraitOne>(vB, vSrcReg0, preg2);
    Reg::Mul(vA1Sq, vA, vA, preg);
    Reg::Mul(vB1Sq, vB, vB, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);
    Reg::Cast<T, float, castTrait32to16>(vResult, vS, preg);
    Reg::StoreAlign<T, Reg::StoreDist::DIST_PACK_B32>(dstAddr + i * vflen, vResult, preg);
} else {
    Reg::LoadAlign<T, Reg::LoadDist::DIST_DINTLV_B32>(vSrcReg0, vSrcReg1, srcAddr + i * vflen * 2);
    Reg::Abs(vAbsSrcReg0, vSrcReg0, preg);
    Reg::Abs(vAbsSrcReg1, vSrcReg1, preg);
    Reg::Compare<float, CMPMODE::GT>(preg2, vAbsSrcReg1, vAbsSrcReg0, preg);
    Reg::Select<float>(vA, vAbsSrcReg1, vAbsSrcReg0, preg2);
    Reg::Select<float>(vB, vAbsSrcReg0, vAbsSrcReg1, preg2);

    // 0的处理
    Reg::Compare<uint32_t, CMPMODE::EQ>(preg4, (AscendC::Reg::RegTensor<uint32_t>&)vB, vZero,
                                        preg);

    // subnormal处理
    Reg::Compare<uint32_t, CMPMODE::LT>(preg3, (AscendC::Reg::RegTensor<uint32_t>&)vA,
                                        vMinNormalFloat, preg);
    Reg::Mul(vAS, vA, vSCALE_UP, preg);
    Reg::Mul(vBS, vB, vSCALE_UP, preg);
    Reg::Select(vA, vAS, vA, preg3);
    Reg::Select(vB, vBS, vB, preg3);
    // 提取A的指数因子（对vAForExp操作）
    Reg::ShiftRights(vA0, (AscendC::Reg::RegTensor<uint32_t>&)vA, SHR_NUM_FOR_FP32, preg);
    Reg::ShiftLefts(vA0, vA0, SHR_NUM_FOR_FP32, preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA, vA0,
             preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB, vA0,
             preg);

    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA1, vExpBias,
             preg);
    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB1, vExpBias,
             preg);

    // 计算归化值
    Reg::Mul(vA1Sq, vA1, vA1, preg);
    Reg::Mul(vB1Sq, vB1, vB1, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);

    Reg::Mul(vResult, vS, (AscendC::Reg::RegTensor<float>&)vA0, preg);
    Reg::Mul(vResultS, vResult, vSCALE_DOWN, preg);
    Reg::Select(vResult, vResultS, vResult, preg3);

    // 0的处理
    Reg::Select(vResult, vA, vResult, preg4);

    Reg::StoreAlign(dstAddr + i * vflen, vResult, preg);
}
```

**要点**: 1) complex64 走 else 分支，LoadAlign<DIST_DINTLV_B32> 一次加载拆成 vSrcReg0/vSrcReg1；2) Abs 对两个分量分别取绝对值；3) Abs 用于分量大小比较（Select 大者到 vA），而非直接求模长。

### 实例 3：abs::AbscomplexCustom

- **来源类型**: `__aicore__`
- **共现 API**: Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **Abs 调用次数**: 4
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 复数取绝对值算子自身：对 complex64 拆分后的实/虚部分量寄存器分别 Abs，用于比较分量幅值并做 subnormal 归一化，最终拼回模长。

（行 103-156）

```cpp
if constexpr (std::is_same<U, complex32>::value) {
    preg2 = AscendC::Reg::CreateMask<uint16_t, AscendC::Reg::MaskPattern::ALL>();
    Reg::LoadAlign(vSrcReg0, srcAddr + i * vflen * 2);
    Reg::Cast<float, T, castTraitZero>(vA, vSrcReg0, preg2);
    Reg::Cast<float, T, castTraitOne>(vB, vSrcReg0, preg2);
    Reg::Mul(vA1Sq, vA, vA, preg);
    Reg::Mul(vB1Sq, vB, vB, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);
    Reg::Cast<T, float, castTrait32to16>(vResult, vS, preg);
    Reg::StoreAlign<T, Reg::StoreDist::DIST_PACK_B32>(dstAddr + i * vflen, vResult, preg);
} else {
    Reg::LoadAlign<T, Reg::LoadDist::DIST_DINTLV_B32>(vSrcReg0, vSrcReg1, srcAddr + i * vflen * 2);
    Reg::Abs(vAbsSrcReg0, vSrcReg0, preg);
    Reg::Abs(vAbsSrcReg1, vSrcReg1, preg);
    Reg::Compare<float, CMPMODE::GT>(preg2, vAbsSrcReg1, vAbsSrcReg0, preg);
    Reg::Select<float>(vA, vAbsSrcReg1, vAbsSrcReg0, preg2);
    Reg::Select<float>(vB, vAbsSrcReg0, vAbsSrcReg1, preg2);

    // 0的处理
    Reg::Compare<uint32_t, CMPMODE::EQ>(
        preg4, (AscendC::Reg::RegTensor<uint32_t>&)vB, vZero, preg);

    // subnormal处理
    Reg::Compare<uint32_t, CMPMODE::LT>(
        preg3, (AscendC::Reg::RegTensor<uint32_t>&)vA, vMinNormalFloat, preg);
    Reg::Mul(vAS, vA, vSCALE_UP, preg);
    Reg::Mul(vBS, vB, vSCALE_UP, preg);
    Reg::Select(vA, vAS, vA, preg3);
    Reg::Select(vB, vBS, vB, preg3);
    // 提取A的指数因子（对vAForExp操作）
    Reg::ShiftRights(vA0, (AscendC::Reg::RegTensor<uint32_t>&)vA, SHR_NUM_FOR_FP32, preg);
    Reg::ShiftLefts(vA0, vA0, SHR_NUM_FOR_FP32, preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA, vA0, preg);
    Reg::Sub((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB, vA0, preg);

    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vA1, (AscendC::Reg::RegTensor<uint32_t>&)vA1, vExpBias, preg);
    Reg::Add((AscendC::Reg::RegTensor<uint32_t>&)vB1, (AscendC::Reg::RegTensor<uint32_t>&)vB1, vExpBias, preg);

    // 计算归化值
    Reg::Mul(vA1Sq, vA1, vA1, preg);
    Reg::Mul(vB1Sq, vB1, vB1, preg);
    Reg::Add(vSumSq, vA1Sq, vB1Sq, preg);
    Reg::Sqrt(vS, vSumSq, preg);

    Reg::Mul(vResult, vS, (AscendC::Reg::RegTensor<float>&)vA0, preg);
    Reg::Mul(vResultS, vResult, vSCALE_DOWN, preg);
    Reg::Select(vResult, vResultS, vResult, preg3);

    // 0的处理
    Reg::Select(vResult, vA, vResult, preg4);

    Reg::StoreAlign(dstAddr + i * vflen, vResult, preg);
}
```

**要点**: 1) 与 complex_abs 同源逻辑，Abs 作用在拆分后的两个分量上而非整体；2) Abs 结果用于 Compare<GT> 选大分量、Subnormal 检测与 Scale 放缩；3) 最终模长由 Mul(vResult, vS, vA0) 乘回指数因子得到。

### 实例 4：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Abs 调用次数**: 2
- **参数模式**: `T2_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义**: 逐通道伪量化中用 Abs<float, MaskMergeMode::ZEROING> 分别对 min、max 取绝对值并求和，判定 bothZero（min 与 max 是否同时为 0）以避免除零。

（行 377-397）

```cpp

// 2.0 构造常量 vregZero / vregOne / vregQRange（寄存器内）
AscendC::Reg::Sub<float>(vregZero, vregMin, vregMin, mask);
AscendC::Reg::Adds<float>(vregOne, vregZero, 1.0f, mask);
AscendC::Reg::Adds<float>(vregQRange, vregZero, qRange, mask);

// 2.1 scale = (max - min) / qRange
//     用 0-ULP Div 替代 (max-min)*invR：避免 invR=1/(qMax-qMin) 在 fp32 上的
//     round-to-nearest 误差与 (max-min)*invR 的舍入叠加，使 scale 精确等于
//     `(max-min)/(qMax-qMin)` 的 IEEE 单步除法结果（与 TF 实现一致）。
AscendC::Reg::Sub<float>(vregScale, vregMax, vregMin, mask);
AscendC::Reg::Copy<float>(vregDiffSaved, vregScale, mask);
AscendC::Reg::Div<float, &kDivMode>(vregScale, vregScale, vregQRange, mask);

// 2.2 bothZero = (|min| + |max| > 0) ? 1.0 : 0.0
AscendC::Reg::Abs<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregAbsMin, vregMin, mask);
AscendC::Reg::Abs<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregAbsMax, vregMax, mask);
AscendC::Reg::Add<float>(vregAbsSum, vregAbsMin, vregAbsMax, mask);
AscendC::Reg::Compares<float, AscendC::CMPMODE::GT>(maskBoth, vregAbsSum, 0.0f, mask);
// Select: mask=1 → src0(vregOne); mask=0 → src1(vregZero)
AscendC::Reg::Select<float>(vregBoth, vregOne, vregZero, maskBoth);
```

**要点**: 1) 显式给出两个模板参数 <float, MaskMergeMode::ZEROING>，ZEROING 模式下 mask 外元素置零；2) Abs 两次（vregAbsMin、vregAbsMax）后 Add 求和，再 Compares<GT,0> 得到 bothZero 掩码；3) bothZero 经 Select 决定后续量化分支，防止 scale=0。

### 实例 5：dynamic_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, CreateMask, DataCopy, Div, DivSpecificMode, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, ReduceMax, ReduceMin, RegTensor, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **Abs 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 对称量化分支中用 Abs(vreg5, vreg1, maskAll) 取输入绝对值，乘以 scaleMaxValue 后用 Max 求最大值，作为对称量化的缩放上界。

**片段 1** (行 466-473):

```cpp
if constexpr (isSymmetrical) {
    AscendC::Reg::Abs(vreg5, vreg1, maskAll);
    AscendC::Reg::Muls(vreg5, vreg5, scaleMaxValue, maskAll);
    AscendC::Reg::Max(vreg6, vreg5, vreg6, maskAll);
} else {
    AscendC::Reg::Max(vreg6, vreg1, vreg6, maskAll);
    AscendC::Reg::Min(vreg8, vreg1, vreg8, maskAll);
}
```

**片段 2** (行 492-505):

```cpp
if constexpr (isSymmetrical) {
    AscendC::Reg::Abs(vreg5, vreg1, mask);
    AscendC::Reg::Muls(vreg5, vreg5, scaleMaxValue, mask);
    AscendC::Reg::Max(vreg6, vreg5, vreg6, mask);
    AscendC::Reg::ReduceMax<float>(vregMaxTail, vreg6, mask);
    AscendC::Reg::Max(vregMax, vregMax, vregMaxTail, mask);
} else {
    AscendC::Reg::Max(vreg6, vreg1, vreg6, mask);
    AscendC::Reg::Min(vreg8, vreg1, vreg8, mask);
    AscendC::Reg::ReduceMax<float>(vregMaxTail, vreg6, mask);
    AscendC::Reg::ReduceMin<float>(vregMinTail, vreg8, mask);
    AscendC::Reg::Max(vregMax, vregMax, vregMaxTail, mask);
    AscendC::Reg::Min(vregMin, vregMin, vregMinTail, mask);
}
```

**要点**: 1) 通过 if constexpr (isSymmetrical) 在编译期选择 Abs 路径，非对称走 Max/Min 双路；2) Abs 后立即 Muls(scaleMaxValue) 把绝对值折算回量化范围，再 Max 累积；3) 两个片段展示 maskAll（整向量）与 mask（尾部）两种 mask 用法。

### 实例 6：tanh::TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, CompareScalar, DataCopy, Div, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, Or, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Abs 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: tanh 多项式逼近中用 Abs 求输入绝对值，既用于 2*abs(x) 的 exp 计算，又用于饱和门限与分段选择。

**片段 1** (行 78-109):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

    Reg::Mul(vregInputSqr, vregInput, vregInput, mask);
    Reg::Muls(vregOutput, vregInputSqr, FP32_ZERO_015, mask);
    Reg::Adds(vregOutput, vregOutput, FP32_ZERO_NEG_052, mask);
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

    Reg::CompareScalar<float, CMPMODE::GE>(cmpMaskReg, vregInputAbs, FP32_ZERO_6, mask);
    Reg::Select(vregOutput, vregInputMid, vregOutput, cmpMaskReg);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_NORM_B32>((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**片段 2** (行 119-153):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vregInput16, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::Cast<float, T, castTrait0>(vregInput, vregInput16, mask);

    Reg::Mul(vregInputSqr, vregInput, vregInput, mask);
    Reg::Muls(vregOutput, vregInputSqr, FP32_ZERO_015, mask);
    Reg::Adds(vregOutput, vregOutput, FP32_ZERO_NEG_052, mask);
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

    Reg::CompareScalar<float, CMPMODE::GE>(cmpMaskReg, vregInputAbs, FP32_ZERO_6, mask);
    Reg::Select(vregOutput, vregInputMid, vregOutput, cmpMaskReg);

    Reg::Cast<T, float, castTrait1>(vregOutput16, vregOutput, mask);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_PACK_B32>((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput16, mask);
}
```

**要点**: 1) Abs 结果 vregInputAbs 被复用三次：Muls(2) 送 Exp、CompareScalar<GE,SAT_BOUND> 判饱和、CompareScalar<GE,0.6> 选分段；2) 与 And/Or 提取并回填符号位，保证 tanh 奇函数性质；3) mask 由 UpdateMask<float,RegTraitNumOne> 生成，覆盖尾部元素。

### 实例 7：cdist::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, Duplicate, Exp, ExpSpecificMode, LoadAlign, Log, LogSpecificMode, MaskMergeMode, MaskPattern, MaskReg, Muls, ReduceSum, RegTensor, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore, UpdateMask
- **Abs 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: cdist 距离计算中对两点差 Sub 取 Abs 得到距离绝对值，再经 Log*Muls(p)→Exp 计算 p 范数的幂次项。

（行 619-626）

```cpp
__local_mem__ float * x2Offset = srcPtrX2 + b * rSize_ * MAlign_ + r * MAlign_ + vlLen_ * m;
Reg::LoadAlign(x1Reg, x1Offset);
Reg::LoadAlign(x2Reg, x2Offset);
Reg::Sub(subReg, x1Reg, x2Reg, maskAll);
Reg::Abs(absReg, subReg, maskAll);
Reg::Log<float, &modelog>(logReg, absReg, maskAll);
Reg::Muls(mulReg, logReg, (float)p_, maskAll);
Reg::Exp<float, &modeexp>(expReg, mulReg, maskAll);
```

**要点**: 1) Sub→Abs 是 cdist 求绝对差的标准前缀，absReg 作为 Log 的输入；2) Abs 用 maskAll（全有效掩码）保证整向量参与；3) 与 ExpSpecificMode/LogSpecificMode 配合处理 p 范数的指数运算。

### 实例 8：is_close::NanEqualCompare

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Compare, DataCopy, Duplicate, FusedAbsSub, HighLowPart, MaskAnd, MaskOr, MaskPack, MaskReg, Muls, Pack, RegTensor, RegTraitNumOne, Select, UpdateMask
- **Abs 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: is_close 判定中除 FusedAbsSub 求 abs(x1-x2) 外，再用 Abs 取 x2 绝对值，乘 rtol 加 atol 得到比较阈值。

**片段 1** (行 86-104):

```cpp
Reg::DataCopy(x2Reg, (__ubuf__ float*)(src2Addr + loopIdx * vlSize));

// 计算结果1——equalCmpMask
Reg::Compare<float, CMPMODE::EQ>(equalCmpMask, x1Reg, x2Reg, mask);

// x1x2和自己对比，输出False的位置，为Nan的位置
Reg::Compare<float, CMPMODE::NE>(tmpMask1, x1Reg, x1Reg, mask);
Reg::Compare<float, CMPMODE::NE>(tmpMask2, x2Reg, x2Reg, mask);
// MaskAnd取x1x2都是Nan的位置---------------
Reg::MaskAnd(bothNanMask, tmpMask1, tmpMask2, mask);
// MaskOr取计算结果1、4都为True的位置，结果存储到tmpMask2
Reg::MaskOr(tmpMask2, bothNanMask, equalCmpMask, mask);

// 计算结果3
Reg::FusedAbsSub(absSubReg, x1Reg, x2Reg, mask); // 中间结果
Reg::Abs(x2AbsReg, x2Reg, mask);
Reg::Muls(rtolTmpReg, x2AbsReg, rtol, mask);
Reg::Adds(rtolReg, rtolTmpReg, atol, mask);
Reg::Compare<float, CMPMODE::LE>(funcCmpMask, absSubReg, rtolReg, mask);
```

**片段 2** (行 129-163):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    Reg::Duplicate(regTensorOne, (uint8_t)1.0f, mask);
    Reg::Duplicate(regTensorZero, (uint8_t)0.0f, mask);
    Reg::DataCopy(x1Reg, (__ubuf__ float*)(src1Addr + loopIdx * vlSize));
    Reg::DataCopy(x2Reg, (__ubuf__ float*)(src2Addr + loopIdx * vlSize));
    // 计算结果1——equalCmpMask
    Reg::Compare<float, CMPMODE::EQ>(equalCmpMask, x1Reg, x2Reg, mask);

    // 计算结果3
    Reg::FusedAbsSub(absSubReg, x1Reg, x2Reg, mask); // 中间结果
    Reg::Abs(x2AbsReg, x2Reg, mask);
    Reg::Muls(rtolTmpReg, x2AbsReg, rtol, mask);
    Reg::Adds(rtolReg, rtolTmpReg, atol, mask);
    Reg::Compare<float, CMPMODE::LE>(funcCmpMask, absSubReg, rtolReg, mask);

    // 计算结果4
    Reg::Duplicate(regTensorInfinity, (float)INF_CONST, mask);
    Reg::Compare<float, CMPMODE::LT>(finiteMask, x2AbsReg, regTensorInfinity, mask);

    // 其他处理
    // 符合公式且有限
    Reg::MaskAnd(tmpMask1, funcCmpMask, finiteMask, mask);
    // 符合上一条或者完全一致
    Reg::MaskOr(resultMask, equalCmpMask, tmpMask1, mask);

    Reg::Select(resultReg, regTensorOne, regTensorZero, resultMask);
    Reg::Pack(reguint16, (AscendC::Reg::RegTensor<uint32_t>&)resultReg);
    Reg::Pack(reguint8, reguint16);
    AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(tmpMask1, mask);
    AscendC::Reg::MaskPack<AscendC::Reg::HighLowPart::LOWEST>(mask, tmpMask1);

    // OpCopyOut
    Reg::DataCopy((__ubuf__ uint8_t*)(dstAddr + loopIdx * vlSize), reguint8, mask);
}
```

**要点**: 1) Abs(x2) 与 FusedAbsSub 并存：前者构造 rtol*abs(x2)+atol 阈值，后者提供 abs(x1-x2)；2) Compare<LE> 比较两者得到 funcCmpMask；3) 还用 Abs(x2) 与 INF 常量 Compare<LT> 判有限性，组合 MaskAnd/MaskOr 得到最终 resultMask。

### 实例 9：log_sigmoid::LogSigmoidCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, CompareScalar, DataCopy, Div, Duplicate, Exp, Log, MaskReg, Min, Mul, Muls, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **Abs 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: log_sigmoid 数值稳定实现中用 Abs(x) 取输入绝对值，构造 exp(-abs(x)) 并用 log1p 公式避免大 x 时的数值溢出。

（行 66-86）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    // regCopyIn
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    Reg::DataCopy(x, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::Min(minRes, x, zeroReg, mask);        // x1 = min(x, 0)
    Reg::Abs(xAbs, x, mask);                   // x2 = abs(x)
    Reg::Muls(xAbsNeg, xAbs, valNegOne, mask); // x3 = -x2
    Reg::Exp(expRes, xAbsNeg, mask);           // x4 = e^x3
    // log1p
    Reg::Adds(expResPlusOne, expRes, valPosOne, mask);              // y1 = 1 + x4
    Reg::Adds(expResPlusOneSubOne, expResPlusOne, valNegOne, mask); // y2 = y1 - 1
    Reg::Div(divRes, expRes, expResPlusOneSubOne, mask);            // y3 = x4 / y2
    Reg::Log(logExpXPlus1, expResPlusOne, mask);                    // y4 = log(y1)
    Reg::Mul(mulRes, logExpXPlus1, divRes, mask);                   // y5 = y4 * y3
    Reg::CompareScalar<T, CMPMODE::NE>(cmpLog1pPosMaskReg, expResPlusOne, valPosOne, mask);
    Reg::Select(selectRes, mulRes, expRes, cmpLog1pPosMaskReg); // z1 = select(x4, y5)
    Reg::Sub(ans, minRes, selectRes, mask);                     // z2 = x1 - z1

    // regCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), ans, mask);
}
```

**要点**: 1) Min(x,0) 与 Abs(x) 分别得到负部与绝对值，配合 Exp(-abs(x)) 构造 1/(1+e^{-abs(x)}) 形式；2) Abs 后 Muls(-1) 再 Exp，再用 Adds±1 与 Div 实现 log1p 的泰勒修正；3) CompareScalar<NE,1> 选择是否启用 log1p 修正分支。

### 实例 10：grouped_quant_max::AscendC::HardEvent

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Mul, Reduce, ReduceType, RegTensor, StoreAlign, StoreDist, UpdateMask
- **Abs 调用次数**: 1
- **参数模式**: `T1_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义**: 分组量化求最大值中，在 half/bfloat16 多类型分发并 Cast 到 float 后，用 Abs<float> 求绝对值，再用 Max 累积组内最大绝对值。

（行 275-291）

```cpp
if constexpr (IsSameType<T, float>::value) {
    AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(vregFloatX, xLocalAddr + i * VL_);
} else if constexpr (IsSameType<T, half>::value) {
    AscendC::Reg::LoadAlign<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX, xLocalAddr + i * VL_);
    AscendC::Reg::Cast<float, half, GroupedQuantMaxBase<T, U, RoundMode>::CAST_TRAIT_HALF_TO_FP32>(
        vregFloatX, vregX, mask);
} else if constexpr (IsSameType<T, bfloat16_t>::value) {
    AscendC::Reg::LoadAlign<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX,
                                                                                 xLocalAddr + i * VL_);
    AscendC::Reg::Cast<float, bfloat16_t, GroupedQuantMaxBase<T, U, RoundMode>::CAST_TRAIT_BF16_TO_FP32>(
        vregFloatX, vregX, mask);
}

AscendC::Reg::Abs<float>(vregFloatAbsT, vregFloatX, mask);
AscendC::Reg::Max<float, AscendC::Reg::MaskMergeMode::MERGING>(vregTileMaxFp32, vregTileMaxFp32,
                                                               vregFloatAbsT, mask);
AscendC::Reg::Mul(vregFloatY, vregFloatX, vregS, mask);
```

**要点**: 1) 显式模板 <float>，因为输入已统一 Cast 到 float；2) Abs<float> 仅取绝对值，结果交 Max<MaskMergeMode::MERGING> 累积组内最大值；3) 量化缩放用原值 vregFloatX 乘 vregS，Abs 只服务 max 搜索。

### 实例 11：elu::EluCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, CompareScalar, DataCopy, Exp, LoadDist, MaskReg, Mul, Muls, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Abs 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: elu 的 expm1 实现中用 Abs 求参数绝对值，与 expm1Threshold 比较来选择多项式逼近或 exp(z)-1 分支。

**片段 1** (行 79-97):

```cpp
Reg::Muls(vregT1, vregNeg, coeff5, mask);
Reg::Adds(vregT1, vregT1, coeff4, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff3, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff2, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff1, mask);
Reg::Mul(vregPoly, vregT1, vregNeg, mask);

// exp(z) - 1 for |z| >= threshold
Reg::Exp(vregExp, vregNeg, mask);
Reg::Adds(vregExp, vregExp, constNegOne, mask);

// Select expm1 result based on |z|
Reg::Abs(vregAbsZ, vregNeg, mask);
Reg::CompareScalar<T, CMPMODE::LT>(cmpExpm1, vregAbsZ, expm1Threshold, mask);
Reg::Select<T>(vregNeg, vregPoly, vregExp, cmpExpm1);
```

**片段 2** (行 118-136):

```cpp
// Polynomial expm1(z) = z + z^2/2 + z^3/6 + z^4/24 for |z| < threshold
// Horner: T1 = T1 * z + coeff, then poly = T1 * z
Reg::Muls(vregT1, vregNeg, coeff4, mask);
Reg::Adds(vregT1, vregT1, coeff3, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff2, mask);
Reg::Mul(vregT1, vregT1, vregNeg, mask);
Reg::Adds(vregT1, vregT1, coeff1, mask);
Reg::Mul(vregPoly, vregT1, vregNeg, mask);

// exp(z) - 1 for |z| >= threshold
Reg::Exp(vregExp, vregNeg, mask);
Reg::Adds(vregExp, vregExp, constNegOne, mask);

// Select expm1 result based on |z|
Reg::Abs(vregAbsZ, vregNeg, mask);
Reg::CompareScalar<float, CMPMODE::LT>(cmpExpm1, vregAbsZ, expm1Threshold, mask);
Reg::Select<float>(vregNeg, vregPoly, vregExp, cmpExpm1);
```

**要点**: 1) Abs 结果只用于分支选择（CompareScalar<LT>），不参与多项式求值本身；2) 两个片段对应不同精度/类型的 Horner 多项式，但 Abs+Compare+Select 的分支结构一致；3) 阈值 expm1Threshold 控制 abs(z)<阈值 走多项式、否则走 expm1。

### 实例 12：sigmoid_cross_entropy_with_logits_v2::CalcBCEWithLogitsV2

- **来源类型**: `__aicore__`
- **共现 API**: Adds, DataCopy, Duplicate, Exp, Log, MaskReg, Mins, Mul, Neg, PostLiteral, RegTensor, Sub, UpdateMask
- **Abs 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: BCE with logits v2 的数值稳定实现中用 Abs 取 logits 绝对值，构造 exp(-abs(x)) 用于 log(1+e^{-abs(x)}) 项。

（行 87-96）

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
```

**要点**: 1) 无 mask 形态，pregUp 为全有效上掩码；2) Abs→Neg→Exp→Adds(1) 构成 1+e^{-abs(x)}，配合 Mins(x,0) 得到 max(x,0)-x*t+log(1+e^{-abs(x)}) 形式；3) HAS_POS_WEIGHT 用 constexpr 分支单独加载 posWeight。

### 实例 13：dynamic_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CreateMask, DataCopy, Div, Duplicate, LoadDist, MaskPattern, MaskReg, Max, Mul, RegTensor, StoreDist, UpdateMask
- **Abs 调用次数**: 1
- **参数模式**: `T1_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义**: 逐通道动态量化中，对 Cast 到 float 的输入用 Abs<float> 取绝对值，再用 Max 逐列累积最大绝对值作为量化 scale。

（行 289-302）

```cpp
for (uint16_t j = 0; j < mLoopNum; j++) {
    Reg::DataCopy<xDtype, Reg::LoadDist::DIST_UNPACK_B16>(
        vregIn, (__ubuf__ xDtype*)(inAddr + i * REG_LEN + j * nSize + bIdx * mLen_ * nSize));
    Reg::Cast<float, xDtype, castTraitB16ToB32>(vregInFp32, vregIn, preg0);
    if constexpr (hasSmooth) {
        Reg::DataCopy<xDtype, Reg::LoadDist::DIST_BRC_B16>(
            vregSmooth, (__ubuf__ xDtype*)(smoothAddr + j));
        Reg::Cast<float, xDtype, castTraitB16ToB32>(vregSmoothFp32, vregSmooth, preg0);
        Reg::Mul<float>(vregInFp32, vregInFp32, vregSmoothFp32, preg0);
    }
    Reg::Abs<float>(vregAbs, vregInFp32, preg0);
    Reg::Max<float>(vregColMax, vregAbs, vregColMax, preg0);
}
Reg::Mul(vregOutScale, vregColMax, vregMaxFactor, preg0);
```

**要点**: 1) 显式模板 <float>、无 mask 形态，preg0 由 UpdateMask<float> 生成；2) 可选 smooth 分支先 Mul 平滑再 Abs；3) Abs→Max→Mul(maxFactor) 构成逐列 amax→scale 的标准链路。

### 实例 14：sigmoid_cross_entropy_with_logits::CalcSigmoidCrossEntropyWithLogits

- **来源类型**: `__aicore__`
- **共现 API**: Add, DataCopy, Duplicate, Exp, Log, MaskReg, Maxs, Mul, Neg, RegTensor, RegTraitNumOne, Sub, UpdateMask
- **Abs 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: BCE with logits 中用 Abs 取预测值绝对值，构造 exp(-abs(x)) 用于 log(1+e^{-abs(x)}) 数值稳定项。

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

**要点**: 1) 带 mask 形态，与实例 25 的无 mask 版本形成对照（同一数学公式不同 mask 写法）；2) Abs→Neg→Exp→Add(1)→Log 得到 log(1+e^{-abs(x)})，配合 Maxs(x,0) 与 -x*t 拼出 BCE；3) mask 由 UpdateMask<T,RegTraitNumOne> 生成。

### 实例 15：data_compare::AscendC::LocalTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AbsSub, Adds, Cast, Compare, Duplicate, LoadAlign, LoadDist, MaskReg, Muls, RegTensor, Select, StoreAlign, UpdateMask
- **Abs 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: data_compare 的浮点比较中用 AbsSub 求 abs(x1-x2)，再用 Abs 取 x2 绝对值构造 rtol*abs(x2)+atol 阈值，Compare<GT> 得到差异掩码。

（行 565-595）

```cpp
if constexpr (kIsB16) {
    AscendC::Reg::RegTensor<D_T> b16Reg1, b16Reg2;
    AscendC::Reg::LoadAlign<D_T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(b16Reg1, x1Ptr + off);
    AscendC::Reg::LoadAlign<D_T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(b16Reg2, x2Ptr + off);
    AscendC::Reg::Cast<float, D_T, kCastTraitB16ToF32>(x1Reg, b16Reg1, mask);
    AscendC::Reg::Cast<float, D_T, kCastTraitB16ToF32>(x2Reg, b16Reg2, mask);
} else if constexpr (kIsB8) {
    AscendC::Reg::RegTensor<D_T> b8Reg1, b8Reg2;
    AscendC::Reg::LoadAlign<D_T, AscendC::Reg::LoadDist::DIST_UNPACK4_B8>(b8Reg1, x1Ptr + off);
    AscendC::Reg::LoadAlign<D_T, AscendC::Reg::LoadDist::DIST_UNPACK4_B8>(b8Reg2, x2Ptr + off);
    AscendC::Reg::RegTensor<half> h16Reg1, h16Reg2;
    AscendC::Reg::Cast<half, D_T, kCastTraitB8ToB16>(h16Reg1, b8Reg1, mask);
    AscendC::Reg::Cast<half, D_T, kCastTraitB8ToB16>(h16Reg2, b8Reg2, mask);
    AscendC::Reg::Cast<float, half, kCastTraitB16ToF32Int>(x1Reg, h16Reg1, mask);
    AscendC::Reg::Cast<float, half, kCastTraitB16ToF32Int>(x2Reg, h16Reg2, mask);
} else if constexpr (kIsI32) {
    AscendC::Reg::RegTensor<int32_t> iReg1, iReg2;
    AscendC::Reg::LoadAlign(iReg1, x1Ptr + off);
    AscendC::Reg::LoadAlign(iReg2, x2Ptr + off);
    AscendC::Reg::Cast<float, int32_t, kCastTraitI32ToF32>(x1Reg, iReg1, mask);
    AscendC::Reg::Cast<float, int32_t, kCastTraitI32ToF32>(x2Reg, iReg2, mask);
} else {
    AscendC::Reg::LoadAlign(x1Reg, reinterpret_cast<__ubuf__ float*>(x1Ptr) + off);
    AscendC::Reg::LoadAlign(x2Reg, reinterpret_cast<__ubuf__ float*>(x2Ptr) + off);
}

AscendC::Reg::AbsSub(diffReg, x1Reg, x2Reg, mask);
AscendC::Reg::Abs(absX2Reg, x2Reg, mask);
AscendC::Reg::Muls(threshReg, absX2Reg, rtolVal, mask);
AscendC::Reg::Adds(threshReg, threshReg, atolVal, mask);
AscendC::Reg::Compare<float, AscendC::CMPMODE::GT>(cmpMask, diffReg, threshReg, mask);
```

**要点**: 1) 与 is_close 同公式，但用 Reg:: 命名空间且做了 B16/B8/I32 多类型 Cast 分发后再比较；2) Abs(x2) 结果 Muls(rtolVal) 再 Adds(atolVal) 得到阈值；3) Abs 与 AbsSub 配对，是 isclose 类算子的标准阈值构造模式。

### Abs 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_quant | Add, Adds, Cast, CreateMask | 无 mask：Abs 后接 Max/ReduceMax 求对称量化 amax | __aicore__ |
| complex_abs | Add, Cast, CastTrait, Compare | 无 mask：对 complex 拆分寄存器分别 Abs，配合 Compare/Select 做分量排序 | __aicore__ |
| abs | Add, Cast, CastTrait, Compare | 无 mask：complex 模长中对拆分分量 Abs，用于幅值排序与归一化 | __aicore__ |
| fake_quant_with_min_max_vars_per_channel | Add, Adds, Cast, Compares | 显式模板 <float,ZEROING> + mask：对 min/max 取 Abs 求和判定 bothZero | __VEC_SCOPE__ |
| dynamic_quant | Adds, Cast, CreateMask, DataCopy | mask + constexpr 分支：对称量化 Abs→Muls(scale)→Max 求缩放上界 | __VEC_SCOPE__ |
| tanh | Adds, And, Cast, CompareScalar | mask：Abs 求输入绝对值用于饱和门限与分段选择 | __aicore__ |
| cdist | Add, CreateMask, Duplicate, Exp | mask：Sub 后 Abs 取距离绝对值，接 Log/Exp 计算 p 范数 | __VEC_SCOPE__ |
| is_close | Adds, Compare, DataCopy, Duplicate | mask：配合 FusedAbsSub 与 Abs(x2) 计算 isclose 阈值 abs(x1-x2)≤rtol*abs(x2)+atol | __aicore__ |
| log_sigmoid | Adds, CompareScalar, DataCopy, Div | mask：Abs(x) 用于 log-sigmoid 的 exp(-abs(x)) 与 log1p 稳定分支 | __aicore__ |
| grouped_quant_max | Cast, CreateMask, Duplicate, LoadAlign | 显式模板 <float> + mask：多类型分发后 Abs 求 group 最大绝对值 | __VEC_SCOPE__ |
| elu | Adds, Cast, CompareScalar, DataCopy | mask：Abs(z) 与阈值比较选择多项式/expm1 分支 | __aicore__ |
| sigmoid_cross_entropy_with_logits_v2 | Adds, DataCopy, Duplicate, Exp | 无 mask：Abs(x) 配合 Neg/Exp 构造 BCE with logits 的 log(1+e^{-abs(x)}) | __aicore__ |
| dynamic_quant | Cast, CreateMask, DataCopy, Div | 显式模板 <float> 无 mask：逐列 Abs→Max 求分组量化最大绝对值 | __VEC_SCOPE__ |
| sigmoid_cross_entropy_with_logits | Add, DataCopy, Duplicate, Exp | mask：Abs(predict) 配合 Neg/Exp 构造 BCE with logits 的 log(1+e^{-abs(x)}) | __aicore__ |
| data_compare | AbsSub, Adds, Cast, Compare | mask：配合 AbsSub 与 Abs(x2) 计算比较阈值 abs(x1-x2)>rtol*abs(x2)+atol | __VEC_SCOPE__ |
