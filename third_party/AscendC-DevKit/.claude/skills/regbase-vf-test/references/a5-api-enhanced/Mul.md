# Mul

**页面ID:** atlasascendc_api_07_0358  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0358.html

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

根据mask对输入数据srcReg0、srcReg1按元素相乘操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0358_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Mul(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint16_t/int16_t/uint32_t/int32_t/half/float/bfloat16_t/uint64_t/int64_t/complex32/complex64 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING, mask未筛选的元素在dstReg中置零。- MERGING, 当前不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

结果为不饱和模式。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MulVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Mul(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Mul 实例


### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Mul 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 dynamic_mx_quant 非尾轴 FP8 量化中，用 Mul 将逐元素最大值乘以预广播常数 invMax 归一化到 [0,1) 以提取 FP8 指数/尾数位；并在 half/bfloat16 路径中将 Cast 拆出的零部/一部 FP32 分量分别乘以反向共享指数重建量化浮点值。

**片段 1** (行 486-513):

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
Reg::Duplicate(invMaxRegTensor, FP8_DEFAULT_MAX_EXP);
// 右移获取指数位
Reg::ShiftRights(expFP32RegTensor, maxFP32RegTensor, FP32_SHR_NUM, mask);
```

**片段 2** (行 563-572):

```cpp
if constexpr (IsSame<T, half>::value) {
    Reg::Cast<float, T, castTraitZero>(yZero, x, pnumMask);
    Reg::Cast<float, T, castTraitOne>(yOne, x, pnumMask);
    Reg::Mul(yZero, yZero, reversedShareExpRegTensorFP32Zero, mask);
    Reg::Mul(yOne, yOne, reversedShareExpRegTensorFP32One, mask);
} else if constexpr (IsSame<T, bfloat16_t>::value) {
    Reg::Mul(xBF16RegTensor, x, (Reg::RegTensor<bfloat16_t>&)reversedShareExpRegTensor, pnumMask);
    Reg::Cast<float, bfloat16_t, castTraitZero>(yZero, xBF16RegTensor, mask);
    Reg::Cast<float, bfloat16_t, castTraitOne>(yOne, xBF16RegTensor, mask);
}
```

**要点**: 1) dst 与 srcReg0 复用同一寄存器(maxFP32RegTensor)原地更新，配合 mask 只更新有效元素；2) invMaxRegTensor 通过 Reg::Duplicate 预广播常数，Mul 用它做标量式逐元素乘实现归一化；3) half 路径先 Cast 升 FP32 再 Mul，避免 half 乘法中间溢出。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Mul 调用次数**: 12
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: grouped_dynamic_mx_quant 的 FP8 路径中，half 类型先 Cast 升 FP32 再用 Mul 乘以反向共享指数重建量化值，bfloat16 路径则先在 BF16 上用 Mul 完成输入与共享指数相乘再 Cast 到 FP32，按 dtype 走不同精度策略。

（行 633-643）

```cpp
if constexpr (IsSame<T, half>::value) {
    Reg::Cast<float, T, castTraitZero>(yZero, xRegTensor, p0);
    Reg::Cast<float, T, castTraitOne>(yOne, xRegTensor, p0);
    Reg::Mul(yZero, yZero, reversedShareExpRegTensorFP32Zero, maskAll);
    Reg::Mul(yOne, yOne, reversedShareExpRegTensorFP32One, maskAll);
} else {
    Reg::Mul(valueRegTensor, xRegTensor, (Reg::RegTensor<bfloat16_t>&)expMaxreShareExpFP16YOneRegTensor,
             p0);
    Reg::Cast<float, bfloat16_t, castTraitZero>(yZero, valueRegTensor, maskAll);
    Reg::Cast<float, bfloat16_t, castTraitOne>(yOne, valueRegTensor, maskAll);
}
```

**要点**: 1) half 先 Cast 升精度再 Mul、bf16 先 Mul 再 Cast，体现先乘后升与先升后乘的精度策略差异；2) Mul 的 mask 用 maskAll 或 p0，通过 MaskReg 控制尾轴非对齐尾部；3) srcReg1 是预广播的共享指数寄存器，Mul 充当按指数缩放的逐元素乘。

### 实例 3：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Mul 调用次数**: 14
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: SwiGLU 反向双轴量化中，用 Mul 把激活输入 regA/regB 逐元素乘以量化 scale(scaleForMul)；half 路径先 Cast 到 FP32 再乘保证精度，其它类型直接在原类型上乘 FP16 scale，Mul 被复用 4 次配合 Cast 拆分的高低半部。

**片段 1** (行 924-924):

```cpp
for (uint16_t j = 0; j < batchCount; j++) {
```

**片段 2** (行 1007-1025):

```cpp
if constexpr (IsSameType<xDtype, half>::value) {
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x0ZeroFP32, regA, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x0OneFP32, regA, maskAll);
    Reg::Cast<float, bfloat16_t, CAST_X_TO_FP32_ZERO>(
        scaleForMulFP32, (Reg::RegTensor<bfloat16_t>&)scaleForMulFP16, maskAll);
    Reg::Mul(x0ZeroFP32, x0ZeroFP32, scaleForMulFP32, maskAll);
    Reg::Mul(x0OneFP32, x0OneFP32, scaleForMulFP32, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x1ZeroFP32, regB, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x1OneFP32, regB, maskAll);
    Reg::Mul(x1ZeroFP32, x1ZeroFP32, scaleForMulFP32, maskAll);
    Reg::Mul(x1OneFP32, x1OneFP32, scaleForMulFP32, maskAll);
} else {
    Reg::Mul(regA, regA, (Reg::RegTensor<xDtype>&)scaleForMulFP16, maskAll);
    Reg::Mul(regB, regB, (Reg::RegTensor<xDtype>&)scaleForMulFP16, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x0ZeroFP32, regA, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x0OneFP32, regA, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>(x1ZeroFP32, regB, maskAll);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ONE>(x1OneFP32, regB, maskAll);
}
```

**要点**: 1) 同一 scale 分别乘到 regA/regB 两个输入，Mul 复用 4 次(零部/一部乘两个输入)配合 Cast 拆分；2) Mul 的 dst 与 srcReg0 复用原地缩放；3) half 路径必须升 FP32 再 Mul 避免 FP16 乘法溢出。

### 实例 4：dynamic_mx_quant::Reg::StoreAlign

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskOr, MaskReg, Maxs, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Mul 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义**: dynamic_mx_quant 尾轴 FP8 量化中，将最大值 max32 乘以 invMax 归一化，再通过 ShiftRights/And 拆出 FP8 指数与尾数位生成 MX 量化 scale，等价于除以最大值的逐元素乘。

（行 732-749）

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
```

**要点**: 1) Mul 用 maskFloat(按 FP32 元素数生成的 MaskReg)控制有效元素，尾轴非对齐部分被 ZEROING 置零；2) dst=srcReg0=max32 原地更新，Mul 紧跟 Maxs 下界裁剪之后确保归一化前 max 已夹到合法范围；3) invMax 为预广播常数寄存器，等价于除以最大值。

### 实例 5：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Mul 调用次数**: 8
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: dynamic_quant(MoE 全加载)中，用 Mul 将输入 x 与 smooth 因子逐元素相乘做平滑预处理(x*smooth)，再求绝对值最大/最小值确定量化 scale，主循环与尾部循环分别用动态 mask 控制有效元素。

**片段 1** (行 333-344):

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
```

**片段 2** (行 366-379):

```cpp
AscendC::Reg::ReduceMax(vregReduceMaxX, vreg7, preg1);
AscendC::Reg::ReduceMin(vregReduceMinX, vregMinX, preg1);

preg4 = AscendC::Reg::UpdateMask<float>(tailNum);
AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
    vreg1, xAddr + multiRow * rowCount + (vfLoop - 1) * VL);
AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg4);
AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
    vreg2, smoothAddr + (vfLoop - 1) * VL);
AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg4);
AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg4);
AscendC::Reg::Max(vreg7, vreg3, vreg7, preg4);
AscendC::Reg::Min(vregMinX, vreg3, vregMinX, preg4);
AscendC::Reg::ReduceMax(vregReduceMaxXTail, vreg7, preg4);
```

**片段 3** (行 399-440):

```cpp
for (uint16_t j = 0; j < vfLoop; j++) {
    auto addr = yAddr + multiRow * outAlignLen + j * VL;
    preg2 = AscendC::Reg::UpdateMask<float>(sreg1);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg1, xAddr + multiRow * rowCount + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg2);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vreg2,
                                                                                      smoothAddr + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg2);
    AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg2);
    if constexpr (isSymmetrical == true) {
        AscendC::Reg::Div(vreg16, vreg3, vreg10, preg2);
    } else if constexpr (isSymmetrical == false) {
        AscendC::Reg::Div(vregXDivScale, vreg3, vreg10, preg2);
        AscendC::Reg::Add(vreg16, vregXDivScale, vregDupOffset, preg2);
    }
    if constexpr (IsSameType<yDtype, int8_t>::value) {
        AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vreg17, vreg16, preg2);
        AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vreg18, vreg17, preg2);
        AscendC::Reg::Cast<yDtype, half, castTraitF16ToI8>(vreg19, vreg18, preg2);
    } else if constexpr (IsSameType<yDtype, hifloat8_t>::value) {
        AscendC::Reg::Cast<yDtype, float, castTraitF32toh8>(vreg19, vreg16, preg2);
    } else if constexpr (IsSameType<yDtype, fp8_e4m3fn_t>::value || IsSameType<yDtype, fp8_e5m2_t>::value) {
        AscendC::Reg::Cast<yDtype, float, castTraitF32tofp8>(vreg19, vreg16, preg2);
    } else if constexpr (IsSameType<yDtype, int4b_t>::value) {
        AscendC::Reg::RegTensor<uint16_t> vreg20;
        AscendC::Reg::Cast<int16_t, float, castTraitF32ToI16>(vreg17, vreg16, preg2);
        AscendC::Reg::Cast<half, int16_t, castTraitI16ToF16>(vreg18, vreg17, preg2);
        AscendC::Reg::Pack(vreg20, (AscendC::Reg::RegTensor<uint32_t>&)vreg18);
        AscendC::Reg::Cast<int4x2_t, half, castTraitF16ToI8>(
            (AscendC::Reg::RegTensor<int4x2_t>&)vreg19, (AscendC::Reg::RegTensor<half>&)vreg20,
            preg2);
        addr = yAddr + (multiRow * outAlignLen + j * VL) / 2;
    }
    if constexpr (IsSameType<yDtype, int4b_t>::value) {
        AscendC::Reg::DataCopy<yCopyDtype, AscendC::Reg::StoreDist::DIST_PACK4_B32>(addr, vreg19,
                                                                                              preg3);
    } else {
        AscendC::Reg::DataCopy<yCopyDtype, AscendC::Reg::StoreDist::DIST_PACK4_B32>(addr, vreg19,
                                                                                              preg2);
    }
}
```

**要点**: 1) Mul 在主循环和尾部循环分别用 preg0/preg4(动态 mask)控制尾轴非对齐尾部；2) Mul 紧接 Cast 之后始终在 FP32 域做乘法以保持精度；3) 指纹按未解析裸调用统计为无 mask，实际调用带动态 mask。

### 实例 6：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Mul 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义**: flat_quant 高性能版中，将 bf16 max 升到 FP32 后乘以 invMax 归一化，拆出指数/尾数，并通过一系列 Compare/Select 处理 NaN/0 边界后 Pack 成 FP4 scale 输出。

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

**要点**: 1) Mul 用 preMaskScale(按 scaleNum 动态生成)控制有效元素，适配可变 scale 长度；2) Mul 位于 Cast(BF16 转 FP32)之后、ShiftRights 之前，是归一化取指数流水线关键一步；3) dst=srcReg0 原地乘 invMax 等价于除以最大值。

### 实例 7：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **Mul 调用次数**: 16
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: complex_abs 算子中，用 Mul 计算复数实部/虚部平方(a*a、b*b)求和开方得模长 |z|=sqrt(a^2+b^2)；对 subnormal 输入先用 Mul 放大(×SCALE_UP)再在结尾用 Mul 缩回(×SCALE_DOWN)保证非规格化数精度。

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

**要点**: 1) Mul 做自乘求平方，dst 与两个 src 分别独立寄存器不复用 src；2) subnormal 路径用 Mul 乘 SCALE_UP 与乘 SCALE_DOWN 成对出现，配合 Select 选择是否缩放体现数值稳定性；3) complex32 与 complex64 两条分支都用 Mul 求平方，64 位路径多归一化放大缩小步骤。

### 实例 8：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Mul 调用次数**: 8
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义**: SwiGLU MX 量化非末轴 scale 计算中，对 dim0/dim1 两个维度的最大值 maxFP32_0/maxFP32_1 分别乘以 invMax 归一化，再 ShiftRights/And 拆出指数尾数生成 FP8 scale。

（行 322-340）

```cpp
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
Reg::And(manFP32_1, maxFP32_1, manMaskFP32, maskFP32);
```

**要点**: 1) Mul 被复用两次(dim0 和 dim1 各一次)处理双轴最大值归一化；2) Mul 紧接 Cast(half 转 float)之后在 FP32 域完成避免 half 精度损失；3) dst=srcReg0 原地更新，invMax 为预广播常数。

### 实例 9：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Mul 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义**: add_rms_norm_dynamic_mx_quant 的 MX scale 计算中，将 max16 升到 FP32 后乘以 invMax 归一化，拆出指数/尾数并处理 NaN/0 边界，生成 FP8 指数 scale 与 half 倒数 scale。

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

**要点**: 1) Mul 用 preMaskScale 控制按 VL_F32 对齐的有效元素，循环 loopNumScale4NV 次；2) Mul 位于 Cast 之后、ShiftRights 之前，是归一化取指数标准流水线一步；3) 与 swiglu 及 rms_norm 共用同一 invMax 归一化模板，差异在循环长度和边界常数。

### 实例 10：dynamic_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Adds, Cast, CreateMask, DataCopy, Div, DivSpecificMode, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Muls, ReduceMax, ReduceMin, RegTensor, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **Mul 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: dynamic_quant 大 shape 双 buffer 版中，若启用 smooth 则用 Mul 将输入 vreg1 逐元素乘以 smooth 因子 vreg3 做平滑，再按对称/非对称模式求绝对值最大或最大/最小值确定量化边界，主循环用 maskAll、尾部用部分 mask。

**片段 1** (行 459-473):

```cpp
if constexpr (hasSmooth == 1) {
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vreg2,
                                                                                 smoothLocalAddr + i * VL);
    AscendC::Reg::Cast<float, T, castTrait0>(vreg3, vreg2, maskAll);
    AscendC::Reg::Mul(vreg1, vreg1, vreg3, maskAll);
}

if constexpr (isSymmetrical) {
    AscendC::Reg::Abs(vreg5, vreg1, maskAll);
    AscendC::Reg::Muls(vreg5, vreg5, scaleMaxValue, maskAll);
    AscendC::Reg::Max(vreg6, vreg5, vreg6, maskAll);
} else {
    AscendC::Reg::Max(vreg6, vreg1, vreg6, maskAll);
    AscendC::Reg::Min(vreg8, vreg1, vreg8, maskAll);
}
```

**片段 2** (行 486-505):

```cpp
if constexpr (hasSmooth == 1) {
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, smoothLocalAddr + (vfLoopNum - 1) * VL);
    AscendC::Reg::Cast<float, T, castTrait0>(vreg3, vreg2, mask);
    AscendC::Reg::Mul(vreg1, vreg1, vreg3, mask);
}
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

**要点**: 1) Mul 用 maskAll(主循环)和 mask(尾部)两套 mask，主循环全有效、尾部按剩余元素数生成部分 mask；2) Mul 紧跟 Cast 之后在 FP32 域执行，平滑因子先从 bf16 升精度再相乘；3) hasSmooth 通过 constexpr 分支控制是否调用 Mul，编译期裁剪无用代码。

### 实例 11：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Mul 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEfloat`（实参 1 个，类型: float）
- **语义**: rms_norm_dynamic_mx_quant 的 MX scale 计算中，将 RMS 归一化后的最大值乘以 invMax 归一化，拆指数/尾数并处理边界，输出 FP8 指数 scale 和 half 倒数 scale，与 add_rms_norm 共用同一归一化模板。

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

**要点**: 1) 与 add_rms_norm 共用同一 invMax 归一化模板，Mul 在流水线中位置和作用一致；2) Mul 用 preMaskScale 按 VL_FP32 对齐控制有效元素；3) dst=srcReg0=max32 原地乘 invMax 等价于除以最大值。

### 实例 12：tanh::TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, And, Cast, CompareScalar, DataCopy, Div, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Muls, Or, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Mul 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: tanh 算子用多项式逼近加大值分支实现：先用 Mul 计算输入平方 x^2，再用 Mul 将多项式结果乘以 x^2 做奇函数展开，小值走多项式、大值走 Exp 指数路径饱和到正负1。

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

**要点**: 1) Mul 做自乘求平方和多项式乘 x^2 两种用途，是 tanh 多项式逼近的核心乘法；2) 两段代码(float 直存与 half 转 Cast 存)结构相同，Mul 用同一 mask 控制有效元素；3) Mul 配合 FusedMulDstAdd 组成多项式 Horner 求值链减少独立乘法指令数。

### 实例 13：dynamic_mx_quant::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, Interleave, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Pack, PostLiteral, RegLayout, RegTensor, SatMode, StoreAlign, StoreDist
- **Mul 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: dynamic_mx_quant 尾轴 FP4 量化中，用 Mul 将 DeInterleave 拆出的 4 路 FP32 输入(x0Zero/x1Zero/x0One/x1One)逐元素乘以倒数 scale(floatScaleForMul)做反量化缩放，再转 FP4 输出，Mul 连续调用 4 次原地更新。

（行 1330-1382）

```cpp
for (uint16_t i = 0; i < loopNum2VF; i++) {
    Reg::LoadAlign<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_E2B_B16>(
        halfScaleForMul, recipScaleLocalAddr, ELEMENT_AFTER_REDUCE_);
    Reg::Cast<float, bfloat16_t, castTraitBf16ToFp32>(floatScaleForMul,
                                                      (Reg::RegTensor<bfloat16_t>&)halfScaleForMul, maskFP32);

    Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
        x0Zero, x1Zero, xLocalAddr, VF_LEN_32_DOUBLE);
    Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
        x0One, x1One, xLocalAddr, VF_LEN_32_DOUBLE);
    Reg::DeInterleave(x0Zero, x0One, x0Zero, x0One);
    Reg::DeInterleave(x1Zero, x1One, x1Zero, x1One);

    Reg::Mul(x0Zero, x0Zero, floatScaleForMul, maskFP32);
    Reg::Mul(x1Zero, x1Zero, floatScaleForMul, maskFP32);
    Reg::Mul(x0One, x0One, floatScaleForMul, maskFP32);
    Reg::Mul(x1One, x1One, floatScaleForMul, maskFP32);

    ComputeFP4FromFp32<toBf16RoundMode, roundMode>(x0Zero);
    ComputeFP4FromFp32<toBf16RoundMode, roundMode>(x0One);
    ComputeFP4FromFp32<toBf16RoundMode, roundMode>(x1Zero);
    ComputeFP4FromFp32<toBf16RoundMode, roundMode>(x1One);

    Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(x0ZeroBF16, x0Zero, maskFP32);
    Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(x0OneBF16, x0One, maskFP32);
    Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(x1ZeroBF16, x1Zero, maskFP32);
    Reg::Cast<bfloat16_t, float, castTraitFp32toBF16>(x1OneBF16, x1One, maskFP32);

    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)x0ZeroBF16,
                                                            (Reg::RegTensor<uint32_t>&)x0ZeroBF16);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)x0OneBF16,
                                                            (Reg::RegTensor<uint32_t>&)x0OneBF16);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)x1ZeroBF16,
                                                            (Reg::RegTensor<uint32_t>&)x1ZeroBF16);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)x1OneBF16,
                                                            (Reg::RegTensor<uint32_t>&)x1OneBF16);

    // Merge zero+one bf16 per group
    Reg::Interleave(x0ZeroBF16, x0OneBF16, x0ZeroBF16, x0OneBF16);
    Reg::Interleave(x1ZeroBF16, x1OneBF16, x1ZeroBF16, x1OneBF16);

    // Merge group 0+1 bf16
    Reg::Interleave(x0ZeroBF16, x1ZeroBF16, x0ZeroBF16, x1ZeroBF16);

    Reg::Cast<U, bfloat16_t, castTrait>(xExp0FP4, x0ZeroBF16, maskB16);
    Reg::Cast<U, bfloat16_t, castTrait>(xExp1FP4, x1ZeroBF16, maskB16);

    // DIST_PACK4_B32 output (required for fp4x2 format)
    Reg::StoreAlign<int8_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::StoreDist::DIST_PACK4_B32>(
        yLocalAddr, (Reg::RegTensor<int8_t>&)xExp0FP4, FP4_OUT_ELE_PER_BLK, maskB16);
    Reg::StoreAlign<int8_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::StoreDist::DIST_PACK4_B32>(
        yLocalAddr, (Reg::RegTensor<int8_t>&)xExp1FP4, FP4_OUT_ELE_PER_BLK, maskB16);
}
```

**要点**: 1) Mul 连续调用 4 次对 4 路拆分输入用同一 floatScaleForMul 缩放，dst=srcReg0 原地更新；2) Mul 在 Cast(bf16 转 FP32)之后、ComputeFP4FromFp32 之前，是升精度缩放降精度流水线中间步；3) maskFP32 控制 FP32 元素有效位，尾轴非对齐部分置零。

### 实例 14：clipped_swiglu::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Adds, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Div, Exp, LoadDist, MaskPattern, MaskReg, Maxs, Mins, Muls, RegTensor, StoreDist, UpdateMask
- **Mul 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: clipped_swiglu 算子中，用 Mul 将 sigmoid(x1) 逐元素乘以被 clamp 加 bias 处理后的 x2，完成 SwiGLU 门控相乘 out=sigmoid(x1)*x2，两段对应 interleave 与非 interleave 两种布局。

**片段 1** (行 372-418):

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
AscendC::Reg::AddrReg outOffset = AscendC::Reg::CreateAddrReg<T>(dim0vfLoopIdx, alignDim1Out,
                                                                           dim1vfLoopIdx, VF_LEN_FP32);
if constexpr (sizeof(T) == sizeof(half)) {
    AscendC::Reg::Cast<T, float, CAST_FP32_TO_FP16_BF16>(outTReg, outFReg, mask);
    DataCopy<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(swigluUbAddr, outTReg, outOffset, mask);
} else {
    DataCopy(swigluUbAddr, (Reg::RegTensor<T>&)outFReg, outOffset, mask);
}
```

**片段 2** (行 423-467):

```cpp
if constexpr (isInterleaved) {
    if constexpr (sizeof(T) == sizeof(half)) {
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddrT,
                                                                                     srcIdxOffset1);
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddrT,
                                                                                     srcIdxOffset1);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX1F, vregX1, mask);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX2F, vregX2, mask);
    } else {
        // float
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX1F, x1UbAddrT, srcIdxOffset1);
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX2F, x2UbAddrT, srcIdxOffset1);
    }
    AscendC::Reg::DeInterleave(vregX1DeF, vregX2DeF, vregX1F, vregX2F);
} else {
    if constexpr (sizeof(T) == sizeof(half)) {
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX1, x1UbAddrT,
                                                                                     srcIdxOffset1);
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX2, x2UbAddrT,
                                                                                     srcIdxOffset1);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX1DeF, vregX1, mask);
        AscendC::Reg::Cast<float, T, CAST_BF16_FP16_TO_FP32>(vregX2DeF, vregX2, mask);
    } else {
        // float
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX1DeF, x1UbAddrT, srcIdxOffset1);
        AscendC::Reg::DataCopy((Reg::RegTensor<T>&)vregX2DeF, x2UbAddrT, srcIdxOffset1);
    }
}
AscendC::Reg::Mins(minsReg, vregX1DeF, clampLimit, maskT);
AscendC::Reg::Muls(mulsReg, minsReg, negAlpha, maskT);
AscendC::Reg::Exp(expReg, mulsReg, maskT);
AscendC::Reg::Adds(addsReg, expReg, scalarOne, maskT);
AscendC::Reg::Div(sigmoidReg, minsReg, addsReg, maskT);

AscendC::Reg::Mins(vregX2DeF, vregX2DeF, clampLimit, maskT);
AscendC::Reg::Maxs(vregX2DeF, vregX2DeF, negClampLimit, maskT);
AscendC::Reg::Adds(vregX2DeF, vregX2DeF, gluBias, maskT);

AscendC::Reg::Mul(outFReg, sigmoidReg, vregX2DeF, maskT);
if constexpr (sizeof(T) == sizeof(half)) {
    AscendC::Reg::Cast<T, float, CAST_FP32_TO_FP16_BF16>(outTReg, outFReg, maskT);
    DataCopy<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(swigluUbAddrT, outTReg, outOffset1, maskT);
} else {
    DataCopy(swigluUbAddrT, (Reg::RegTensor<T>&)outFReg, outOffset1, maskT);
}
```

**要点**: 1) Mul 是 SwiGLU 核心门控乘法(sigmoid 乘 x2)，dst=outFReg 独立于两个 src；2) 两段 Mul 分别用 mask 和 maskT(不同尾部 mask)适配两路输出非对齐尾部；3) Mul 紧接 Mins/Maxs/Exp/Div 之后，输入已做 clamp 和 bias 预处理保证门控值域安全。

### 实例 15：arg_max_with_value::HardEvent::V_MTE3

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, MaskPattern, MaskReg, PostLiteral, ReduceMax, ReduceMin, RegTensor, RegTraitNumTwo, Select, UnalignReg, UpdateMask
- **Mul 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: arg_max_with_value 算子中，用 Mul 将层级索引 indexResult 乘以步长系数 helpIndex 回溯绝对索引(idx=idx+level_Y[idx]*A)，配合 ReduceMin/DeInterleave/Add 完成多级归约的索引重建。

（行 256-270）

```cpp
if constexpr (isMin) {
    AscendC::Reg::ReduceMin(valueResult, value0, fullMask);
} else {
    AscendC::Reg::ReduceMax(valueResult, value0, fullMask);
}
AscendC::Reg::DataCopyUnAlign<T1, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
    (__local_mem__ T1*&)valueDst, valueResult, uValue, 1);
// 相对索引回溯绝对索引 idx = idx + level_Y[idx] * A
AscendC::Reg::Duplicate(valueResult, valueResult, fullMask);
AscendC::Reg::Compare<T1, CMPMODE::EQ>(cmpMask, valueResult, value0, fullMask);
AscendC::Reg::ReduceMin(indexResult, level0, cmpMask);
AscendC::Reg::Mul(indexMulResult, helpIndex, indexResult, fullMask);
AscendC::Reg::DeInterleave(indexResult, indexAddResult, indexMulResult, helpIndex);
Add(indexResult, indexResult, indexAddResult, oneMask);
Add(indexResult, indexResult, vregIndicesAddStartR, oneMask);
```

**要点**: 1) Mul 做索引乘步长的整数乘法，dst=indexMulResult 独立寄存器，fullMask 全有效；2) Mul 紧接 ReduceMin(找最小索引)之后，是相对索引转绝对索引的关键一步；3) mask 参数名为 fullMask(全有效 MaskReg)，与一般 mask 命名不同但语义同为 MaskReg。

### Mul 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 用预广播 invMax 常数寄存器对最大值做归一化乘法(max×invMax)，half/bf16 路径用 Mul 乘共享指数重建量化值 | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | half 先 Cast 升 FP32 再 Mul 共享指数、bf16 先 Mul 再 Cast，按 dtype 分支重建量化浮点值 | __VEC_SCOPE__ |
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Arange, Cast | 用 Mul 将两个激活输入 regA/regB 分别乘以量化 scale，half 升 FP32 再乘、其它类型直接乘 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 尾轴 FP8 量化中 max32×invMax 归一化后 ShiftRights/And 拆指数尾数生成 scale | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | 用 Mul 做 x×smooth 平滑预处理，主循环 maskAll、尾部动态 mask 控制有效元素 | __aicore__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | bf16 max 升 FP32 后 ×invMax 归一化，拆指数尾数并处理 NaN/0 边界生成 FP4 scale | __simd_vf__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | 用 Mul 求实部/虚部平方(a^2、b^2)开方得模长，subnormal 路径 Mul 放大/缩小保精度 | __aicore__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | 双轴最大值分别 ×invMax 归一化，FP32 域拆指数尾数生成 FP8 scale | __aicore__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | RMS max 升 FP32 后 ×invMax 归一化，生成 FP8 指数 scale 与 half 倒数 scale | __aicore__ |
| dynamic_quant | Abs, Adds, Cast, CreateMask, DataCopy | 大 shape 双 buffer，hasSmooth 时 Mul 做 x×smooth 平滑，对称/非对称分支求量化边界 | __VEC_SCOPE__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | RMS max ×invMax 归一化，与 add_rms_norm 共用模板生成 FP8/half scale | __aicore__ |
| tanh | Abs, Adds, And, Cast, CompareScalar | 用 Mul 求 x^2 与多项式×x^2，配合 FusedMulDstAdd 做 Horner 多项式逼近 tanh | __aicore__ |
| dynamic_mx_quant | Cast, CastTrait, CreateMask, DeInterleave, Duplicate | 尾轴 FP4 量化，4 路 DeInterleave 输入分别 ×floatScaleForMul 反量化缩放后转 FP4 | __VEC_SCOPE__ |
| clipped_swiglu | AddrReg, Adds, Cast, CreateAddrReg, CreateMask | 用 Mul 做门控相乘 out=sigmoid(x1)×x2，两段对应 interleave/非 interleave 布局 | __VEC_SCOPE__ |
| arg_max_with_value | Add, Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost | 用 Mul 做索引×步长回溯绝对索引，配合 ReduceMin/DeInterleave 完成多级归约索引重建 | __VEC_SCOPE__ |
