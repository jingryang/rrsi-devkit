# Duplicate

**页面ID:** atlasascendc_api_07_0410  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0410.html

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

支持Scalar和Tensor两种模式：

- Scalar模式：将scalarValue广播到寄存器，并保存在dstReg中（如果有mask，则保存在dstReg中被mask筛选的位置）。
- Tensor模式：将srcReg的最低位元素广播到寄存器，并保存在dstReg中被mask筛选的位置。

#### 定义原型

- 将scalarValue广播到寄存器，不支持mask

```
template <typename T = DefaultType, typename U, typename S>
__simd_callee__ inline void Duplicate(S& dstReg, U scalarValue);
```

- 将scalarValue广播到寄存器，支持mask

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U, typename S>
__simd_callee__ inline void Duplicate(S& dstReg, U scalarValue, MaskReg& mask);
```

- 将srcReg的最低位元素广播到寄存器

```
template <typename T = DefaultType, HighLowPart pos = HighLowPart::LOWEST, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void Duplicate(S& dstReg, S& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：bool、int8_t、uint8_t、fp4x2_e2m1_t、fp4x2_e1m2_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、fp8_e8m0_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、complex32、int64_t、uint64_t、complex64。 |
| U | scalar的数据类型。 Atlas 350 加速卡，支持的数据类型为：bool、int8_t、uint8_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、complex32、int64_t、uint64_t、complex64。 |
| mode | 选择MERGING模式或ZEROING模式。 - MERGING，mask未筛选的元素在dst中保留原值。- ZEROING，mask未筛选的元素在dst中置零。 |
| pos | 默认为LOWEST，表示将srcReg中的最低位广播至dstReg（暂不支持其他取值）。 |
| S | 目的操作数的RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

**表3 **源操作数和目的操作数的数据类型约束

| dstReg数据类型 | scalar/srcReg数据类型 |
| --- | --- |
| bool | bool |
| int8_t | int8_t |
| uint8_t | uint8_t |
| fp4x2_e2m1_t | int8_t |
| fp4x2_e1m2_t | int8_t |
| hifloat8_t | int8_t |
| fp8_e5m2_t | int8_t |
| fp8_e4m3fn_t | int8_t |
| fp8_e8m0_t | int8_t |
| int16_t | int16_t |
| uint16_t | uint16_t |
| half | half |
| bfloat16_t | bfloat16_t |
| int32_t | int32_t |
| uint32_t | uint32_t |
| float | float |
| complex32 | complex32 |
| int64_t | int64_t |
| uint64_t | uint64_t |
| complex64 | complex64 |

#### 约束说明

无

#### 调用示例

- 示例一

```
template<typename T>
__simd_vf__ inline void DuplicateVF(__ubuf__ T* dstAddr, T scalarValue, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<T>();    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::Duplicate(dstReg, scalarValue);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 示例二

```
template<typename T>
__simd_vf__ inline void DuplicateVF(__ubuf__ T* dstAddr, T scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, src0Addr + i * oneRepeatSize);
        AscendC::Reg::Duplicate(dstReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 示例三

```
template<typename T>
__simd_vf__ inline void DuplicateVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, src0Addr + i * oneRepeatSize);
        AscendC::Reg::Duplicate(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Duplicate 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Duplicate 调用次数**: 18
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 dynamic_mx_quant 量化算子中，用 2 参形式 Duplicate 将一系列常量（NAN、最大指数、尾数掩码、零、偏置等）广播到寄存器，为后续按 mask 计算指数最大值做准备。

**片段 1** (行 449-470):

```cpp
static constexpr Reg::CastTrait castTraitHalf2Bf16 = {Reg::RegLayout::UNKNOWN, Reg::SatMode::UNKNOWN,
                                                      Reg::MaskMergeMode::ZEROING, RoundMode::CAST_TRUNC};
static constexpr Reg::CastTrait castTraitFp32ToBf16 = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                       Reg::MaskMergeMode::ZEROING, toBf16RoundMode};
Reg::Duplicate(nan, FP32_NAN_CUSTOM);
Reg::Duplicate(tmp16RegTensor, BF16_MAX);
Reg::Duplicate(absMaskFP32RegTensor, FP32_MX_MAX_EXP);
Reg::Duplicate(invMaxRegTensor, INV_DTYPE_MAX);
Reg::Duplicate(fp32ZeroRegTensor, 0);
Reg::Duplicate(manFP32RegTensor, FP32_MX_MAN_MASK);
Reg::Duplicate(scaleBias, FP32_MX_EXP_BIAS);

uint32_t pnum = dataLenSingleLoop;
uint32_t tailPnum = dataLenTailLoop;
Reg::MaskReg pnumMask = Reg::UpdateMask<uint16_t>(pnum);
Reg::MaskReg tailPnumMask = Reg::UpdateMask<uint16_t>(tailPnum);
Reg::Duplicate(expMax, 0);
for (uint16_t i = 0; i < static_cast<uint16_t>(regLoop - 1); i++) {
    this->template LoadData<RoundMode::UNKNOWN, roundMode>(xAddr, i * dataLenSingleLoop, x, pnumMask);
    Reg::And(exp, (Reg::RegTensor<uint16_t>&)x, tmp16RegTensor, pnumMask);
    Reg::Max(expMax, expMax, exp, pnumMask);
}
```

**片段 2** (行 496-515):

```cpp
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
// And获取尾数位
Reg::And(manFP32RegTensor, maxFP32RegTensor, manFP32RegTensor, mask);
```

**要点**:
- 2 参形式 `Duplicate(dstReg, scalarValue)` 不带 mask，整寄存器全部填充同一标量。
- 常用于初始化常量寄存器（absMask、zero、bias、nan 等），是量化算子常量准备的主要手段。
- 配合 UpdateMask 生成 pnumMask 后再进入按 mask 的指数最大值计算循环。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Duplicate 调用次数**: 18
- **参数模式**: `T0_A2_M1_TYPEnone_MASKMask`（实参 2 个，含 mask/mode: Mask）
- **语义**: 在 grouped 分组量化中用 Duplicate 广播绝对值掩码、零、尾数掩码、NAN、FP8 NAN、偏置等常量到寄存器，随后用 UpdateMask 生成分组有效元素掩码 p0。

**片段 1** (行 548-562):

```cpp
static constexpr Reg::CastTrait castTraitHalf2Bf16 = {Reg::RegLayout::UNKNOWN, Reg::SatMode::UNKNOWN,
                                                      Reg::MaskMergeMode::ZEROING, RoundMode::CAST_TRUNC};
static constexpr Reg::CastTrait castTraitHalf2Float = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                       Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};

Reg::Duplicate(absMaskBF16Reg, ABS_FOR_UINT16);
Reg::Duplicate(zeroRegTensor32, 0);
Reg::Duplicate(manMaskFP32Reg, MAN_FOR_FP32);
Reg::Duplicate(fp8NanRegTensor32, MAX_EXP_FOR_FP8_IN_FP32);
Reg::Duplicate(biasRegTensor32, FP32_EXP_BIAS_CUBLAS);
Reg::Duplicate(nanRegTensor32, NAN_CUSTOMIZATION_PACK);
Reg::Duplicate(fullZeroReg, 0);

uint32_t pnum = vfNum32;
p0 = Reg::UpdateMask<T>(pnum);
```

**片段 2** (行 654-654):

```cpp
if (tailVfLen != 0) {
```

**要点**:
- 用于分组量化场景的常量寄存器初始化，Duplicate 之后通常紧跟 UpdateMask 设置分组有效元素掩码。
- 片段 2 仅含 `if (tailVfLen != 0)` 条件头，是尾块处理分支的入口判断。
- 同一函数内 18 次 Duplicate 说明分组量化所需常量数量较多。

### 实例 3：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Duplicate 调用次数**: 20
- **参数模式**: `T0_A2_M1_TYPEnone_MASKMASK+Mask`（实参 2 个，含 mask/mode: Mask, MASK）
- **语义**: 在 swiglu 反向双轴量化中，先用 Duplicate 初始化 absMask 和两路 absMax 为 0，进入循环对 x 做绝对值与最大值归约；循环后再用 Duplicate 初始化 invMax、尾数掩码、指数掩码等常量供后续 scale 计算。

（行 874-919）

```cpp
Reg::RegTensor<uint32_t> invMax, manMaskReg, expMaskReg, zeroReg32, scaleBiasReg;
Reg::RegTensor<uint32_t> nanReg32, fp8NanReg32;

Reg::RegTensor<uint8_t> scale8Reg, scale8Row, scale8Swapped;
Reg::RegTensor<uint16_t> recip16Row;
Reg::RegTensor<int8_t> indexShiftS8, extractIdx;
Reg::RegTensor<uint16_t> absMask;

Reg::MaskReg cmpResult, zeroMask, p0, p1, p2;
Reg::MaskReg maskAll = Reg::CreateMask<xDtype, Reg::MaskPattern::ALL>();
Reg::MaskReg maskAll32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
Reg::MaskReg maskReduceB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::VL8>();
Reg::MaskReg maskReduceB16 = Reg::CreateMask<uint8_t, Reg::MaskPattern::VL16>();
Reg::UnalignReg ureg;

Reg::Duplicate(absMask, ABS_MASK_FOR_16BIT);
Reg::Duplicate(absMax1Dim2, static_cast<uint16_t>(0));
Reg::Duplicate(absMax2Dim2, static_cast<uint16_t>(0));

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
```

**要点**:
- Duplicate 既用于循环前初始化累加器（absMax1Dim2/absMax2Dim2 = 0），也用于循环后初始化 scale 计算常量。
- 双轴场景需对 dim1/dim2 两路分别累积 absMax，故用两次 Duplicate 初始化两路累加器。
- 循环后配合 Arange 生成索引序列，进入 scale 提取阶段。

### 实例 4：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Interleave, LocalMemBar, MaskMergeMode, MaskPattern, MaskReg, Max, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, Sub, UnalignReg, UpdateMask
- **Duplicate 调用次数**: 18
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 BF16/FP8 混合精度量化中用 Duplicate 广播 BF16_MAX_EXP、FP8_BF16_MAX_EXP、NAN、偏置、零、特殊指数阈值、FP16_INVALID 等常量，再 UpdateMask 后进入求指数最大值的循环。

（行 218-248）

```cpp
static constexpr Reg::CastTrait castTrait32to8 = {Reg::RegLayout::ZERO, Reg::SatMode::SAT,
                                                  Reg::MaskMergeMode::ZEROING, RoundMode::CAST_RINT};
static constexpr Reg::CastTrait castTraitHalf2Bf16 = {Reg::RegLayout::UNKNOWN, Reg::SatMode::UNKNOWN,
                                                      Reg::MaskMergeMode::ZEROING, RoundMode::CAST_TRUNC};
Reg::Duplicate(fp8MaxExpRegTensor, FP8_BF16_MAX_EXP);
Reg::Duplicate(maxEle, BF16_MAX_EXP);
Reg::Duplicate(nan, BF16_NAN_CUSTOM);
Reg::Duplicate(fp8Nan, FP8_DEFAULT_MAX_EXP);
Reg::Duplicate(bias, BF16_EXP_BIAS);
Reg::Duplicate(zero, 0);
Reg::Duplicate(specialExp, BF16_SPECIAL_EXP_THRESHOLD);
Reg::Duplicate(invalidMaskFp16, FP16_INVALID);

uint32_t pnum = dataLenSingleLoop;
uint32_t tailPnum = dataLenTailLoop;
Reg::MaskReg pnumMask = Reg::UpdateMask<uint16_t>(pnum);
Reg::MaskReg tailPnumMask = Reg::UpdateMask<uint16_t>(tailPnum);
Reg::Duplicate(expMax, 0);
for (uint16_t i = 0; i < static_cast<uint16_t>(regLoop - 1); i++) {
    this->template LoadData<RoundMode::CAST_TRUNC, roundMode>(xAddr, i * dataLenSingleLoop, x, pnumMask);
    if constexpr (IsSame<T, half>::value) {
        Reg::And(xSelectRegTensor, (Reg::RegTensor<uint16_t>&)x, invalidMaskFp16, pnumMask);
        Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask, xSelectRegTensor, invalidMaskFp16, pnumMask);
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16RegTensor, x, pnumMask);
        Reg::And(exp, (Reg::RegTensor<uint16_t>&)xBF16RegTensor, maxEle, pnumMask);
        Reg::Select<uint16_t>(exp, exp, maxEle, invalidDataMask);
    } else if constexpr (IsSame<T, bfloat16_t>::value) {
        Reg::And(exp, (Reg::RegTensor<uint16_t>&)x, maxEle, pnumMask);
    }
    Reg::Max(expMax, expMax, exp, pnumMask);
}
```

**要点**:
- 针 BF16→FP8 混合精度量化，需同时准备 BF16（maxEle/bias/nan）和 FP8（fp8MaxExp/fp8Nan）两套指数常量。
- invalidMaskFp16（FP16_INVALID）用于 half 类型路径检测非法数据，配合 Select 做兜底。
- expMax 用 Duplicate 初始化为 0 作为后续指数归约的累加初值。

### 实例 5：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Duplicate 调用次数**: 10
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 在 dynamic_quant 动态量化中，对称模式用 3 参形式 `Duplicate(vreg10, vreg9, preg1)` 将归约后的 max 广播成 scale 向量；非对称模式用 `Duplicate(vregMinX, POS_INFINITY)` 初始化最小值，最终同样用 3 参形式广播 scale 与 offset。

**片段 1** (行 332-351):

```cpp
if constexpr (isSymmetrical == true) {
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
    AscendC::Reg::Muls(vreg9, vreg8, maxValue, preg1);
    AscendC::Reg::Duplicate(vreg10, vreg9, preg1);
    AscendC::Reg::DataCopyUnAlign<float, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        scaleAddr, vreg9, ureg0, 1);
}
```

**片段 2** (行 352-396):

```cpp
if constexpr (isSymmetrical == false) {
    AscendC::Reg::Duplicate(vregMinX, POS_INFINITY);
    for (uint16_t j = 0; j < vfLoop - 1; j++) {
        preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
        AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
            vreg1, xAddr + multiRow * rowCount + j * VL);
        AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg0);
        AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
            vreg2, smoothAddr + j * VL);
        AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg0);
        AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg0);
        AscendC::Reg::Max(vreg7, vreg3, vreg7, preg1);
        AscendC::Reg::Min(vregMinX, vreg3, vregMinX, preg1);
    }
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
    AscendC::Reg::ReduceMin(vregReduceMinXTail, vregMinX, preg4);

    AscendC::Reg::Max(vregFinalMax, vregReduceMaxX, vregReduceMaxXTail, preg5);
    AscendC::Reg::Min(vregFinalMin, vregReduceMinX, vregReduceMinXTail, preg5);

    AscendC::Reg::Sub(vregMaxSubMin, vregFinalMax, vregFinalMin, preg5);
    AscendC::Reg::Muls(vreg9, vregMaxSubMin, offsetDivValue, preg5);
    AscendC::Reg::Duplicate(vreg10, vreg9, preg1);
    AscendC::Reg::DataCopyUnAlign<float, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        scaleAddr, vreg9, ureg0, 1);
    AscendC::Reg::Div<float, &mode>(vregMaxDivScale, vregFinalMax, vreg9, preg5);
    AscendC::Reg::Muls(vregNegMaxDivScale, vregMaxDivScale, NEGATIVE_ONE, preg5);
    AscendC::Reg::Adds(vregOffset, vregNegMaxDivScale, offsetValue, preg5); //
    AscendC::Reg::Duplicate(vregDupOffset, vregOffset, preg1);
    AscendC::Reg::DataCopyUnAlign<float, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        offsetAddr, vregOffset, ureg1, 1);
}
```

**要点**:
- 3 参形式 `Duplicate(dstReg, srcReg, mask)` 是 Tensor 模式，把 srcReg 最低位广播到 dstReg 被 mask 选中的位置。
- 对称量化只需 scale（vreg10），非对称量化还需 offset（vregDupOffset），均用 3 参 Duplicate 广播。
- 非对称路径用 `Duplicate(vregMinX, POS_INFINITY)`（2 参）初始化最小值累加器，再循环 ReduceMin。

### 实例 6：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Interleave, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Duplicate 调用次数**: 28
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: 在 dynamic_mx_quant 尾轴处理中，先用 2 参 Duplicate 初始化大量常量寄存器（dstTypeMax、bias、abs、inf、nan、zero 等），尾轴分支用 3 参形式 `Duplicate(scaleReprocal, scaleReprocal, preMaskScale2)` 将 scale 自身广播到被 mask 选中的位置实现尾块覆盖。

**片段 1** (行 596-614):

```cpp
Reg::MaskReg p0;
Reg::MaskReg p1;
Reg::MaskReg pregAll16 = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();

Reg::Duplicate(dstTypeMaxReg, this->dstTypeMax_);
Reg::Duplicate(biasReg, this->maxBias_);
Reg::Duplicate(absForXReg, this->absForX_);
Reg::Duplicate(infForXReg, this->maxExp_);
Reg::Duplicate(infForFP32Reg, FP32_MX_MAN_MASK);
Reg::Duplicate(nan, this->nanValue_);
Reg::Duplicate(specialExp, this->specialExp_);
Reg::Duplicate(zeroRegTensor32, 0);
Reg::Duplicate(zeroRegTensor16, 0);
Reg::Duplicate(xMaxReg, 0);
Reg::Duplicate(x2MaxReg, 0);
Reg::Duplicate(invDstTypeMax, invDstTypeMax_);

static constexpr Reg::CastTrait castTraitZero = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                 Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
```

**片段 2** (行 769-779):

```cpp
if constexpr (ISTAIL) {
    Reg::Duplicate(scaleReprocal, scaleReprocal, preMaskScale2);
}
for (uint16_t j = 0; j < static_cast<uint16_t>(blockCount); j += step) {
    this->template LoadData<calcType>(xAddr, regLoop * vfLen + j * dataLen, xReg, p2);
    CalcElement<roundMode, U, calcType, calcTypeInt>(xReg, scaleReprocal, infForXReg, out,
                                                     preMaskScale2);
    auto addr = yAddr + (regLoop * vfLen + j * outDataLenAlign) / DIGIT_TWO;
    Reg::DataCopyUnAlign(addr, out, u1, tailVfLen / DIGIT_TWO);
    Reg::DataCopyUnAlignPost(addr, u1, 0);
}
```

**要点**:
- 3 参 `Duplicate(dst, src, mask)` 是 Tensor 模式，此处 src==dst（scaleReprocal）实现尾块位置的覆写。
- 28 次 Duplicate 调用说明常量寄存器数量多，是初始化密集型实例。
- 尾轴分支用 `if constexpr (ISTAIL)` 包裹 3 参 Duplicate，仅尾块路径触发自广播覆写。

### 实例 7：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub, UnPack
- **Duplicate 调用次数**: 20
- **参数模式**: `T0_A2_M1_TYPEnone_MASKMASK+Mask`（实参 2 个，含 mask/mode: Mask, MASK）
- **语义**: 在 swiglu 双轴量化中用 Reg::Duplicate 连续初始化 absMask、两路 absMax=0、invMax、尾数掩码、指数掩码、零、偏置、NAN、FP8 NAN 等十余个常量寄存器，随后进入 scale 计算循环。

（行 965-989）

```cpp
Reg::RegTensor<uint16_t> recip2Zero, recip2One;

// Constants
Reg::RegTensor<uint16_t> absMask;
Reg::RegTensor<uint32_t> invMax, manMaskReg, expMaskReg, zeroReg32, scaleBiasReg;
Reg::RegTensor<uint32_t> nanReg32, fp8NanReg32;

// Masks
Reg::MaskReg cmpResult, zeroMask, p0, p1, p2;
Reg::MaskReg maskAll = Reg::CreateMask<xDtype, Reg::MaskPattern::ALL>();
Reg::MaskReg maskAll32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
Reg::MaskReg maskB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::ALL>();
Reg::MaskReg maskReduceB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::VL8>();
Reg::MaskReg maskReduceB16 = Reg::CreateMask<uint8_t, Reg::MaskPattern::VL16>();

Reg::Duplicate(absMask, ABS_MASK_FOR_16BIT);
Reg::Duplicate(absMax1Dim2, static_cast<uint16_t>(0));
Reg::Duplicate(absMax2Dim2, static_cast<uint16_t>(0));
Reg::Duplicate(invMax, localInvDtypeMax);
Reg::Duplicate(manMaskReg, MAN_MASK_FLOAT);
Reg::Duplicate(expMaskReg, MAX_EXP_FOR_FP32);
Reg::Duplicate(zeroReg32, static_cast<uint32_t>(0));
Reg::Duplicate(scaleBiasReg, FP32_EXP_BIAS_CUBLAS);
Reg::Duplicate(nanReg32, static_cast<uint32_t>(NAN_CUSTOMIZATION));
Reg::Duplicate(fp8NanReg32, MAX_EXP_FOR_FP8_IN_FP32);
```

**要点**:
- 双轴场景需两路 absMax（absMax1Dim2/absMax2Dim2）分别用 Duplicate 初始化为 0。
- Duplicate 是常量寄存器初始化的主要手段，此处一次初始化十余个常量。
- 配合多种 MaskReg（maskAll/maskAll32/maskB8/maskReduceB8/maskReduceB16）应对不同位宽归约。

### 实例 8：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Duplicate 调用次数**: 30
- **参数模式**: `T0_A2_M1_TYPEnone_MASKMASK+Mask`（实参 2 个，含 mask/mode: Mask, MASK）
- **语义**: 在双轴 MX 量化中用 Duplicate 初始化 absMask、invMax、FP32 尾数掩码、偏置、NAN，以及 FP8 E8M0 的 NAN/偏置、BF16 的 NAN/specialExp/maxEle 等常量，并初始化两路 absMax 和 zeroB16 为 0。

**片段 1** (行 638-666):

```cpp
Reg::Duplicate(absMask, ABS_MASK_FOR_16BIT);
Reg::RegTensor<uint32_t> invMax;
Reg::Duplicate(invMax, invDtypeMax_); // 1/Amax(DType), FP32表示
Reg::RegTensor<uint32_t> manMaskFP32;
Reg::Duplicate(manMaskFP32, MAN_MASK_FLOAT); // FP32尾数掩码
Reg::RegTensor<uint32_t> scaleBiasFP32;
Reg::Duplicate(scaleBiasFP32, FP32_EXP_BIAS_CUBLAS); // BF16偏移在uint32
Reg::RegTensor<uint32_t> nanPackFP32;
Reg::Duplicate(nanPackFP32, NAN_CUSTOMIZATION_PACK);

Reg::RegTensor<uint16_t> nanE8M0;
Reg::Duplicate(nanE8M0, NAN_FOR_FP8_E8M0);
Reg::RegTensor<uint16_t> biasE8M0;
Reg::Duplicate(biasE8M0, BF16_EXP_BIAS);
Reg::RegTensor<uint16_t> zero;
Reg::Duplicate(zero, 0);
Reg::RegTensor<uint16_t> nanBF16;
Reg::Duplicate(nanBF16, NAN_CUSTOMIZATION);
Reg::RegTensor<uint16_t> specialExp;
Reg::Duplicate(specialExp, SPECIAL_EXP_THRESHOLD);
Reg::RegTensor<uint16_t> maxEleBF16;
Reg::Duplicate(maxEleBF16, EXP_MASK_BF16);

Reg::Duplicate(absMax1Dim2, 0);
Reg::Duplicate(absMax2Dim2, 0);
Reg::Duplicate(zeroB16, 0);

// ========== Mask定义 ==========
Reg::MaskReg maskAll = Reg::CreateMask<xDtype, Reg::MaskPattern::ALL>();
```

**片段 2** (行 749-756):

```cpp

// ========================================================================
// 循环结束后，计算-2轴CuBALS Scale
// absMax1Dim2: 128个偶数列的累积绝对值max
// absMax2Dim2: 128个奇数列的累积绝对值max
// 每个需要拆分为Zero/One两半分别做FP32计算，再合并
// ========================================================================
```

**要点**:
- 同时准备 FP32（uint32：invMax/manMaskFP32/scaleBiasFP32/nanPackFP32）和 BF16（uint16：nanE8M0/biasE8M0/nanBF16/specialExp/maxEleBF16）两套常量。
- 30 次 Duplicate 调用，是本批实例中常量初始化最密集的。
- 片段 2 是循环后 -2 轴 CuBLAS Scale 计算的注释说明，描述两路 absMax 拆分合并逻辑。

### 实例 9：dynamic_mx_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, HighLowPart, Interleave, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub
- **Duplicate 调用次数**: 26
- **参数模式**: `T0_A2_M1_TYPEnone_MASKMASK`（实参 2 个，含 mask/mode: MASK）
- **语义**: 在 high_perf large_tail 优化路径中用 Duplicate 初始化 BF16/FP32 绝对值掩码、FP16 INF、尾数掩码、invMax、dstTypeMax、maxU16、maxEle、bias、zero、nan、specialExp 等常量，再按 float/BF16 分支进入循环求绝对值最大值。

（行 396-437）

```cpp
static constexpr Reg::CastTrait castTraitZero = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                 Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
static constexpr Reg::CastTrait castTraitOne = {Reg::RegLayout::ONE, Reg::SatMode::UNKNOWN,
                                                Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};

Reg::Duplicate(absForXU16, BF16_ABS_MASK);
Reg::Duplicate(absForXU32, FP32_ABS_MASK);
Reg::Duplicate(maxEleFP16, FP16_INF);
Reg::Duplicate(manForFP32, FP32_MX_MAN_MASK);
Reg::Duplicate(invMax, invDtypeMax_);
Reg::Duplicate(dstTypeMaxReg, invDstTypeMax_);
Reg::Duplicate(maxU16, 0);
Reg::Duplicate(maxEleU16, BF16_MAX_EXP);
Reg::Duplicate(biasU16, BF16_EXP_BIAS);
Reg::Duplicate(zeroU16, 0);
Reg::Duplicate(nanU16, BF16_NAN_CUSTOM);
Reg::Duplicate(specialExpU16, BF16_SPECIAL_EXP_THRESHOLD);
if constexpr (IsSame<xDtype, float>::value) {
    Reg::Duplicate(manAbs0FP32, 0);
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

    Reg::Cast<float, xDtype, castTraitZero>((Reg::RegTensor<float>&)manAbs0FP32,
                                            (Reg::RegTensor<xDtype>&)maxU16, pregAll16);
    Reg::Cast<float, xDtype, castTraitOne>((Reg::RegTensor<float>&)manAbs1FP32, (Reg::RegTensor<xDtype>&)maxU16,
                                           pregAll16);
}
```

**要点**:
- 通过 `if constexpr (IsSame<xDtype, float>::value)` 区分 FP32 与 BF16 两条路径，各自使用对应位宽的绝对值掩码。
- FP32 路径用 manAbs0FP32 累积，BF16 路径用 maxU16 累积，最终 BF16 路径再 Cast 到 FP32 拆 Zero/One。
- Duplicate 初始化的常量覆盖了两种精度所需的全部掩码与边界值。

### 实例 10：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, HighLowPart, Interleave, LoadDist, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Duplicate 调用次数**: 28
- **参数模式**: `T0_A2_M1_TYPEnone_MASKMASK+Mask`（实参 2 个，含 mask/mode: Mask, MASK）
- **语义**: 在双轴 MX 量化 Custom Scale 路径中用 Duplicate 初始化 absMask、invDstTypeMax、FP32 尾数/偏置常量，以及 FP8 E8M0、BF16 的 NAN/偏置/specialExp/maxEle 等常量，并初始化两路 absMax 与 zeroB16 为 0。

**片段 1** (行 1147-1175):

```cpp
// ========== 常量寄存器 ==========
Reg::RegTensor<uint16_t> absMask;
Reg::Duplicate(absMask, ABS_MASK_FOR_16BIT);
Reg::RegTensor<float> invDstTypeMaxReg;
Reg::Duplicate(invDstTypeMaxReg, invDstTypeMax_); // 1/dstTypeMax, FP32表示
Reg::RegTensor<uint32_t> manMaskFP32;
Reg::Duplicate(manMaskFP32, MAN_MASK_FLOAT); // FP32尾数掩码
Reg::RegTensor<uint32_t> scaleBiasFP32;
Reg::Duplicate(scaleBiasFP32, FP32_EXP_BIAS_CUBLAS); // BF16偏移在uint32

Reg::RegTensor<uint16_t> nanE8M0;
Reg::Duplicate(nanE8M0, NAN_FOR_FP8_E8M0);
Reg::RegTensor<uint16_t> biasE8M0;
Reg::Duplicate(biasE8M0, BF16_EXP_BIAS);
Reg::RegTensor<uint16_t> zero;
Reg::Duplicate(zero, 0);
Reg::RegTensor<uint16_t> nanBF16;
Reg::Duplicate(nanBF16, NAN_CUSTOMIZATION);
Reg::RegTensor<uint16_t> specialExp;
Reg::Duplicate(specialExp, SPECIAL_EXP_THRESHOLD);
Reg::RegTensor<uint16_t> maxEleBF16;
Reg::Duplicate(maxEleBF16, EXP_MASK_BF16);

Reg::Duplicate(absMax1Dim2, 0);
Reg::Duplicate(absMax2Dim2, 0);
Reg::Duplicate(zeroB16, 0);

// ========== Mask定义 ==========
Reg::MaskReg maskAll = Reg::CreateMask<xDtype, Reg::MaskPattern::ALL>();
```

**片段 2** (行 1256-1263):

```cpp

// ========================================================================
// 循环结束后，计算-2轴Custom Scale
// absMax1Dim2: 128个偶数列的累积绝对值max
// absMax2Dim2: 128个奇数列的累积绝对值max
// 每个需要拆分为Zero/One两半分别做FP32计算，再合并
// ========================================================================
```

**要点**:
- 与实例 8 同文件不同函数（1147-1175 vs 638-666），常量集合一致但用于 Custom Scale 计算。
- 片段 2 是循环后 -2 轴 Custom Scale 的注释说明，描述两路 absMax 拆分合并逻辑。
- 28 次 Duplicate 调用说明常量规模较大。

### 实例 11：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, Interleave, LoadAlign, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Duplicate 调用次数**: 16
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 grouped 量化 FP8 路径中用 Duplicate 初始化 BF16 最大指数、FP8 最大指数、FP8 NAN、偏置、零、NAN、特殊指数阈值、expMax=0 等常量寄存器。

（行 320-333）

```cpp
static constexpr Reg::CastTrait castTrait32to8 = {Reg::RegLayout::ZERO, Reg::SatMode::SAT,
                                                  Reg::MaskMergeMode::ZEROING, RoundMode::CAST_RINT};
static constexpr Reg::CastTrait castTraitHalf2Bf16 = {Reg::RegLayout::UNKNOWN, Reg::SatMode::UNKNOWN,
                                                      Reg::MaskMergeMode::ZEROING, RoundMode::CAST_TRUNC};

Reg::Duplicate(maxEleRegTensor, MAX_EXP_FOR_BF16);
Reg::Duplicate(fp8MaxExpRegTensor, FP8_BF16_MAX_EXP);
Reg::Duplicate(fp8NanRegTensor, MAX_EXP_FOR_FP8);
Reg::Duplicate(biasRegTensor, BF16_EXP_BIAS);
Reg::Duplicate(zeroRegTensor, 0);
Reg::Duplicate(nanRegTensor, NAN_CUSTOMIZATION);
Reg::Duplicate(specialExpRegTensor, SPECIAL_EXP_THRESHOLD);
Reg::Duplicate(expMaxRegTensor, 0);
```

**要点**:
- 与实例 2 同文件不同函数（320-333 vs 548-562），是无 mask 的 2 参形式。
- expMaxRegTensor 用 Duplicate 初始化为 0，作为后续指数归约的累加初值。
- 常量组合对应 BF16→FP8 量化所需的指数/掩码/边界值。

### 实例 12：swiglu_mx_quant::ComputeScaleBLASLast

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Duplicate 调用次数**: 14
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 swiglu 量化 last axis scale 计算中用 Duplicate 初始化 invMax、尾数掩码、指数掩码、零、偏置、NAN、FP8 NAN 等常量，随后进入循环对 max16 做比较/乘/移位/选择以提取指数和 scale。

（行 919-975）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<uint16_t> max16, expOut;
    AscendC::Reg::RegTensor<uint32_t> max32, exp32, man32, normalExp32, expAddOne32, extractExp;
    AscendC::Reg::RegTensor<uint32_t> halfScale;
    AscendC::Reg::RegTensor<uint16_t> recExpOut;
    AscendC::Reg::RegTensor<uint32_t> invMax, manMaskFP32, expMask, zeroRegTensor32, scaleBias;
    AscendC::Reg::RegTensor<uint32_t> nanRegTensor, fp8NanRegTensor;
    AscendC::Reg::Duplicate(invMax, dtypeMax);
    AscendC::Reg::Duplicate(manMaskFP32, manMaskFloat);
    AscendC::Reg::Duplicate(expMask, maxExpForFp32);
    AscendC::Reg::Duplicate(zeroRegTensor32, 0);
    AscendC::Reg::Duplicate(scaleBias, fp32ExpBiasCublas);
    AscendC::Reg::Duplicate(nanRegTensor, nanCustomiZation);
    AscendC::Reg::Duplicate(fp8NanRegTensor, maxExpForFp8InFp32);
    AscendC::Reg::MaskReg cmpResult, zeroMask, p0, p1, p2;
    AscendC::Reg::MaskReg maskHalf = AscendC::Reg::CreateMask<uint16_t, Reg::MaskPattern::VL64>();
    AscendC::Reg::MaskReg preMaskScale = AscendC::Reg::CreateMask<uint32_t>();
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<uint16_t>();
    for (uint16_t i = 0; i < loopNumScale; i++) {
        AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                    AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16, maxExpAddr, onceNum);
        AscendC::Reg::Cast<float, T, CAST_ZERO>((AscendC::Reg::RegTensor<float>&)max32,
                                                     (AscendC::Reg::RegTensor<T>&)max16, preMaskScale);
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
                                    AscendC::Reg::StoreDist::DIST_PACK_B16>(mxScaleLocalAddr, expOut, CONST_32,
                                                                                 maskHalf);
        AscendC::Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, preMaskScale);
        AscendC::Reg::Sub(halfScale, scaleBias, extractExp, preMaskScale);
        AscendC::Reg::Select<uint32_t>(halfScale, halfScale, nanRegTensor, cmpResult);
        AscendC::Reg::Select<uint32_t>(halfScale, halfScale, zeroRegTensor32, zeroMask);
        AscendC::Reg::Pack<uint16_t, uint32_t, AscendC::Reg::HighLowPart::LOWEST>(recExpOut, halfScale);
        AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
            halfScaleLocalAddr, recExpOut, onceNum, mask);
    }
}
```

**要点**:
- 使用 `Reg::Duplicate` 前缀形式初始化 scale 计算所需的 7 个常量寄存器。
- 循环内用 CompareScalar 生成 p0/p1/p2 掩码并用 MaskAnd/MaskOr 组合，再用 Select 选择进位或原值实现四舍五入。
- 最终用 `Pack<..., LOWEST>` 取低 16 位输出 E8M0 scale 与 1/scale。

### 实例 13：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Duplicate 调用次数**: 14
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 RMSNorm+MX 量化 scale 计算中用 Duplicate 初始化 invMax、FP32 尾数掩码、指数掩码、零、偏置、NAN、FP8 NAN 等常量寄存器，再创建 preMaskScale/maskHalf 掩码进入循环。

（行 395-418）

```cpp
AscendC::Reg::RegTensor<uint32_t> invMax;
AscendC::Reg::RegTensor<uint32_t> manMaskFP32;
AscendC::Reg::RegTensor<uint32_t> expMask;
AscendC::Reg::RegTensor<uint32_t> zeroRegTensor32;
AscendC::Reg::RegTensor<uint32_t> scaleBias;
AscendC::Reg::RegTensor<uint32_t> nanRegTensor;
AscendC::Reg::RegTensor<uint32_t> fp8NanRegTensor;

AscendC::Reg::MaskReg cmpResult;
AscendC::Reg::MaskReg zeroMask;
AscendC::Reg::MaskReg p0;
AscendC::Reg::MaskReg p1;
AscendC::Reg::MaskReg p2;
AscendC::Reg::MaskReg preMaskScale;
AscendC::Reg::MaskReg maskHalf;
AscendC::Reg::Duplicate(invMax, dtypeMax);
AscendC::Reg::Duplicate(manMaskFP32, MAN_MASK_FLOAT);
AscendC::Reg::Duplicate(expMask, MAX_EXP_FOR_FP32);
AscendC::Reg::Duplicate(zeroRegTensor32, 0);
AscendC::Reg::Duplicate(scaleBias, FP32_EXP_BIAS_CUBLAS);
AscendC::Reg::Duplicate(nanRegTensor, NAN_CUSTOMIZATION_PACK);
AscendC::Reg::Duplicate(fp8NanRegTensor, MAX_EXP_FOR_FP8_IN_FP32);
preMaskScale = AscendC::Reg::CreateMask<uint32_t>();
maskHalf = AscendC::Reg::CreateMask<uint16_t>();
```

**要点**:
- 来自 norm 子类（非 quant），展示 Duplicate 在归一化算子中的常量初始化用法。
- 常量集合与量化算子类似（invMax/manMask/expMask/zero/bias/nan/fp8Nan）。
- Duplicate 之后紧跟 CreateMask 生成 preMaskScale（uint32 全量）与 maskHalf（uint16）掩码。

### 实例 14：swiglu_backward_mx_quant_with_dual_axis::ComputeScaleCuBLASSecondLast

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, Sub
- **Duplicate 调用次数**: 14
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 swiglu 反向双轴量化 second last axis scale 计算中用 Duplicate 初始化偏置、指数掩码、零、invMax、尾数掩码、FP8 NAN、NAN 等常量，并创建 maskAll/maskAll32/maskB8/maskB16 多种位宽掩码。

（行 788-809）

```cpp
Reg::RegTensor<uint16_t> absMask;
Reg::RegTensor<uint32_t> invMax, manMaskReg, expMaskReg, zero32Reg, scaleBiasReg;
Reg::RegTensor<uint32_t> nan32Reg, fp8Nan32Reg;

Reg::MaskReg cmpResult, zeroMask, p0, p1, p2;
Reg::RegTensor<uint32_t> exp32Reg, man32Reg, expOne32Reg, extractExp;
Reg::RegTensor<uint32_t> halfScale;
Reg::RegTensor<uint16_t> scale16;
Reg::RegTensor<uint8_t> scale8Zero;
Reg::RegTensor<uint16_t> recip16Zero;

Reg::MaskReg maskAll = Reg::CreateMask<xDtype, Reg::MaskPattern::ALL>();
Reg::MaskReg maskAll32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
Reg::MaskReg maskB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::VL64>();
Reg::MaskReg maskB16 = Reg::CreateMask<uint16_t, Reg::MaskPattern::VL64>();
Reg::Duplicate(scaleBiasReg, FP32_EXP_BIAS_CUBLAS);
Reg::Duplicate(expMaskReg, MAX_EXP_FOR_FP32);
Reg::Duplicate(zero32Reg, static_cast<uint32_t>(0));
Reg::Duplicate(invMax, localInvDtypeMax);
Reg::Duplicate(manMaskReg, MAN_MASK_FLOAT);
Reg::Duplicate(fp8Nan32Reg, MAX_EXP_FOR_FP8_IN_FP32);
Reg::Duplicate(nan32Reg, static_cast<uint32_t>(NAN_CUSTOMIZATION));
```

**要点**:
- 与实例 3 同算子不同函数（788-809 vs 874-919），是 second last axis 的 scale 计算。
- 准备 4 种位宽掩码（maskAll/maskAll32/maskB8 VL64/maskB16 VL64）应对不同归约粒度。
- 14 次 Duplicate 调用集中在常量初始化，常量集合与实例 3 循环后阶段一致。

### 实例 15：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, ClearSpr, Compare, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, GatherMask, GatherMaskMode, Interleave, LoadDist, MaskInterleave, MaskReg, PostLiteral, RegTensor, SubCarryOut, SubCarryOuts, UnalignReg, UpdateMask
- **Duplicate 调用次数**: 2
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: 在 sparse_slice 稀疏切片算子中用 `Reg::Duplicate(vregOnes, 1)` 将常量 1 广播到 int32 寄存器，生成全 1 向量用于后续索引计算与 GatherMask 选择。

（行 676-692）

```cpp

Reg::RegTensor<int32_t> vregOnes;

Reg::MaskReg pregIndices;
Reg::MaskReg pregSelect;
Reg::MaskReg carryOut;
Reg::MaskReg pregSelectFinal0;
Reg::MaskReg pregSelectFinal1;

Reg::MaskReg pregGathered;
Reg::MaskReg pregGatheredTwo;

uint16_t rankNum = rn;
Reg::UnalignReg ureg0;

Reg::Duplicate(vregOnes, 1);
```

**要点**:
- 来自 index 子类（非 quant/norm），展示 Duplicate 的基础用法——生成全 1 向量。
- 仅 2 次 Duplicate 调用，是本批实例中最简洁的用法。
- vregOnes 配合 SubCarryOut/SubCarryOuts 做索引减法与进位处理，再用 GatherMask 选择切片元素。

### Duplicate 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 2参无mask，批量初始化常量寄存器（NAN/掩码/零/偏置），配合UpdateMask进入指数最大值循环 | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 2参含mask场景，初始化绝对值/尾数/NAN常量后用UpdateMask生成分组掩码p0 | __VEC_SCOPE__ |
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Arange, Cast | 2参含MASK，循环前初始化absMax=0累加器，循环后初始化invMax/掩码常量，配合Arange生成索引 | __VEC_SCOPE__ |
| dynamic_mx_quant | And, Cast, CastTrait, Compare, Copy | 2参无mask，BF16/FP8双套指数常量初始化，FP16_INVALID检测非法值 | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | 3参Tensor模式，将归约max广播成scale/offset向量，对称/非对称两路 | __aicore__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 3参含mask，尾轴用Duplicate(dst,src,mask)自广播覆写尾块，28次常量初始化 | __VEC_SCOPE__ |
| swiglu_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 2参含MASK+Mask，初始化十余个常量+两路absMax=0，多位宽MaskReg | __VEC_SCOPE__ |
| dynamic_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 2参含MASK+Mask，FP32/BF16/E8M0三套常量初始化，30次Duplicate调用 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 2参含MASK，float/BF16分支初始化全套掩码与边界值后归约absMax | __VEC_SCOPE__ |
| dynamic_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 2参含MASK+Mask，Custom Scale路径常量初始化，与实例8同文件不同函数 | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | And, Cast, CastTrait, Compare, CreateMask | 2参无mask，BF16→FP8常量初始化，expMax=0作归约初值 | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | 2参无mask，Reg前缀初始化scale常量，循环内CompareScalar+Select提取指数 | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | 2参无mask，norm算子中初始化invMax/掩码常量后CreateMask | __aicore__ |
| swiglu_backward_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 2参无mask，second last axis scale常量初始化，4种位宽掩码 | __aicore__ |
| sparse_slice | AR, ClearSpr, Compare, CreateMask, DataCopy | 2参无mask，Duplicate(vregOnes,1)生成全1向量用于索引计算 | __VEC_SCOPE__ |
