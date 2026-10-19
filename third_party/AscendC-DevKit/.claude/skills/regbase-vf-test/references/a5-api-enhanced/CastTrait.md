# CastTrait

**页面ID:** atlasascendc_api_07_00238  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00238.html

---

类型转换模式结构体。

包括RegLayout、SatMode、MaskMergeMode、RoundMode。

```
struct CastTrait {
    RegLayout layoutMode = RegLayout::UNKNOWN;
    SatMode satMode = SatMode::UNKNOWN;
    MaskMergeMode mrgMode = MaskMergeMode::UNKNOWN;
    RoundMode roundMode = RoundMode::UNKNOWN;
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 CastTrait 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **CastTrait 调用次数**: 5
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 dynamic_mx_quant 非尾轴 FP8 量化路径中,用 CastTrait 定义置零转换配置 castTraitZero(RegLayout::ZERO + MaskMergeMode::ZEROING),配合 Reg::Cast 把寄存器清零。

（行 405-444）

```cpp
__VEC_SCOPE__
{
    if constexpr (IsSame<T, float>::value) {
        return;
    }
    Reg::RegTensor<T> x;
    Reg::RegTensor<bfloat16_t> xBF16RegTensor;

    Reg::RegTensor<uint32_t> absMaskFP32RegTensor;
    Reg::RegTensor<uint32_t> maxFP32RegTensor;
    Reg::RegTensor<uint32_t> invMaxRegTensor;
    Reg::RegTensor<uint32_t> fp32ZeroRegTensor;
    // 指数位
    Reg::RegTensor<uint32_t> expFP32RegTensor;
    // 尾数位
    Reg::RegTensor<uint32_t> manFP32RegTensor;
    Reg::RegTensor<uint32_t> scaleBias;
    Reg::RegTensor<uint32_t> extractExpRegTensor;
    Reg::RegTensor<uint16_t> tmp16RegTensor;
    Reg::MaskReg p0;
    Reg::MaskReg p1;
    Reg::MaskReg zeroMask;
    Reg::MaskReg infMask;

    Reg::RegTensor<uint16_t> exp;
    Reg::RegTensor<uint16_t> expMax;
    Reg::RegTensor<uint16_t> reversedShareExpRegTensor;
    Reg::RegTensor<float> reversedShareExpRegTensorFP32Zero;
    Reg::RegTensor<float> reversedShareExpRegTensorFP32One;
    Reg::RegTensor<uint32_t> nan;
    Reg::RegTensor<uint8_t> outZero;
    Reg::RegTensor<float> yZero;
    Reg::RegTensor<float> yOne;
    Reg::RegTensor<U> yZeroFP8;
    Reg::RegTensor<U> yOneFP8;
    Reg::UnalignReg u0;
    Reg::UnalignReg u1;

    static constexpr Reg::CastTrait castTraitZero = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                     Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
```

**要点**: 1) RegLayout::ZERO 表示输出布局取零;2) MaskMergeMode::ZEROING 表示掩码外位置清零;3) SatMode/RoundMode 取 UNKNOWN,因为本转换仅置零、不涉及饱和与舍入。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **CastTrait 调用次数**: 5
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 grouped_dynamic_mx_quant 非尾轴 FP8 路径中复用同一 castTraitZero 置零配置,并配合 CreateMask/UpdateMask 构建全量掩码 MaskPattern::ALL。

（行 504-543）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<T> xRegTensor;
    Reg::RegTensor<T> xRegTensor0;
    Reg::RegTensor<T> xRegTensor1;
    Reg::RegTensor<uint16_t> absMaskBF16Reg;
    Reg::RegTensor<uint16_t> fullZeroReg;
    Reg::RegTensor<uint32_t> zeroRegTensor32;
    Reg::RegTensor<uint32_t> manMaskFP32Reg;
    Reg::RegTensor<uint32_t> fp8NanRegTensor32;
    Reg::RegTensor<uint32_t> biasRegTensor32;
    Reg::RegTensor<uint32_t> nanRegTensor32;
    Reg::RegTensor<uint16_t> expScaleMxYZeroRegTensor;
    Reg::RegTensor<uint16_t> expMaxRegTensor;
    Reg::RegTensor<uint16_t> expMaxRegTensor0;
    Reg::RegTensor<uint16_t> expMaxRegTensor1;
    Reg::RegTensor<uint16_t> expMaxreShareExpFP16YOneRegTensor;
    Reg::RegTensor<uint32_t> expMaxAndAddOneFP32RegTensor;
    Reg::RegTensor<uint32_t> expAndreShareExpFP32RegTensor;
    Reg::RegTensor<uint32_t> manAndmxScaleFP32RegTensor;
    Reg::RegTensor<float> yZero;
    Reg::RegTensor<float> yOne;
    Reg::RegTensor<float> reversedShareExpRegTensorFP32Zero;
    Reg::RegTensor<float> reversedShareExpRegTensorFP32One;
    Reg::RegTensor<bfloat16_t> valueRegTensor;
    Reg::RegTensor<U> yZeroFP8;
    Reg::RegTensor<uint8_t> outZeromxScaleFp8;

    Reg::UnalignReg u1;
    Reg::MaskReg infMask;
    Reg::MaskReg zeroMask;
    Reg::MaskReg p0;
    Reg::MaskReg p1;
    Reg::MaskReg p2;
    Reg::MaskReg p3;
    Reg::MaskReg preMaskScale = Reg::CreateMask<uint32_t>();
    Reg::MaskReg maskAll = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();

    static constexpr Reg::CastTrait castTraitZero = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                     Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
```

**要点**: 1) 同一 CastTrait 配置跨算子复用,体现置零转换是量化算子的通用模式;2) MaskPattern::ALL 生成全 1 掩码覆盖全部元素。

### 实例 3：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, Compare, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskPattern, MaskReg, Max, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, Sub, UnalignReg, UpdateMask
- **CastTrait 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 非尾轴优化的另一计算分支,声明大量中间 RegTensor 与全量掩码 maskAll,CastTrait 作为 Reg::Cast 的转换特征传入,支撑 FP8 量化的指数提取与重排。

（行 174-213）

```cpp
__VEC_SCOPE__
{
    if constexpr (IsSame<T, float>::value) {
        return;
    }
    Reg::RegTensor<T> x;
    Reg::RegTensor<bfloat16_t> xBF16RegTensor;
    Reg::RegTensor<uint16_t> exp;
    Reg::RegTensor<uint16_t> expMax;
    Reg::RegTensor<uint16_t> maxEle;
    Reg::RegTensor<uint16_t> fp8Nan;
    Reg::RegTensor<uint16_t> fp8MaxExpRegTensor;
    Reg::RegTensor<uint16_t> shareExpRegTensor;
    Reg::RegTensor<uint16_t> mxScaleInt;
    Reg::RegTensor<uint8_t> mxScale;
    Reg::RegTensor<uint16_t> specialExp;
    Reg::RegTensor<uint16_t> reversedShareExpRegTensor;
    Reg::RegTensor<float> reversedShareExpRegTensorFP32Zero;
    Reg::RegTensor<float> reversedShareExpRegTensorFP32One;
    Reg::RegTensor<uint16_t> bias;
    Reg::RegTensor<uint16_t> zero;
    Reg::RegTensor<uint16_t> nan;
    Reg::RegTensor<uint8_t> outZero;
    Reg::RegTensor<uint8_t> outOne;
    Reg::RegTensor<uint16_t> yRegTensorZero;
    Reg::RegTensor<uint16_t> yRegTensorOne;
    Reg::RegTensor<float> yZero;
    Reg::RegTensor<float> yOne;
    Reg::RegTensor<U> yZeroFP8;
    Reg::RegTensor<U> yOneFP8;
    Reg::RegTensor<bfloat16_t> valueRegTensor;
    Reg::RegTensor<uint16_t> invalidMaskFp16;
    Reg::RegTensor<uint16_t> xSelectRegTensor;
    Reg::UnalignReg u0;
    Reg::UnalignReg u1;
    Reg::MaskReg zeroMask;
    Reg::MaskReg infMask;
    Reg::MaskReg invalidDataMask;
    Reg::MaskReg specialDataMask;
    Reg::MaskReg maskAll = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
```

**要点**: 1) 用 MaskPattern::ALL 创建全量掩码 maskAll 作为后续 Cast/Select 的默认掩码;2) CastTrait 与 Cast API 配套,决定类型转换时的布局/饱和/合并/舍入四元组行为。

### 实例 4：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Max, Min, PostLiteral, ReduceMax, RegLayout, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **CastTrait 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_block_quant 单行核函数中通过 AscendC::Reg::CastTrait 定义 castTraitZero(ZERO 布局 + NO_SAT 不饱和),用于 Reg::Cast 的块量化类型转换。

（行 283-322）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<IN_TYPE> vReg0;
    AscendC::Reg::RegTensor<IN_TYPE> vReg1;
    AscendC::Reg::RegTensor<IN_TYPE> vReg2;
    AscendC::Reg::RegTensor<IN_TYPE> vReg3;
    AscendC::Reg::RegTensor<IN_TYPE> vReg4;
    AscendC::Reg::RegTensor<float> vReg5;
    AscendC::Reg::RegTensor<float> vReg6;
    AscendC::Reg::RegTensor<float> vReg7;
    AscendC::Reg::RegTensor<float> vReg8;
    AscendC::Reg::RegTensor<float> vReg9;
    AscendC::Reg::RegTensor<float> vReg10;
    AscendC::Reg::RegTensor<float> vReg11;
    AscendC::Reg::RegTensor<float> vReg12;
    AscendC::Reg::RegTensor<float> vReg13;
    AscendC::Reg::RegTensor<float> vReg14;
    AscendC::Reg::RegTensor<int16_t> vReg19;
    AscendC::Reg::RegTensor<half> vReg20;
    AscendC::Reg::RegTensor<OUT_TYPE> vReg15;
    AscendC::Reg::RegTensor<OUT_TYPE> vReg16;
    AscendC::Reg::MaskReg maskReg1;
    AscendC::Reg::MaskReg maskReg2;
    AscendC::Reg::MaskReg maskReg3;
    AscendC::Reg::MaskReg scaleMaskReg;
    AscendC::Reg::MaskReg defaultMaskReg = AscendC::Reg::CreateMask<IN_TYPE>();
    AscendC::Reg::MaskReg inputMaskReg = AscendC::Reg::CreateMask<IN_TYPE>();

    AscendC::Reg::RegTensor<float> fp8MaxValue;
    AscendC::Reg::RegTensor<float> reciprocalScale;
    AscendC::Reg::RegTensor<float> minScaleReg;
    Reg::UnalignRegForStore ureg;
    AscendC::Reg::Duplicate(reciprocalScale, 1.0f);
    AscendC::Reg::Duplicate(minScaleReg, tilingData_->minScale);

    // FP_MAX
    AscendC::Reg::Duplicate(fp8MaxValue, fp8MaxValue_);

    static constexpr AscendC::Reg::CastTrait castTraitZero = {
        AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::NO_SAT,
```

**要点**: 1) 此处用 Reg 命名空间(区别于 Reg);2) SatMode::NO_SAT 明确关闭饱和,适用于块量化不希望截断的场景;3) CastTrait 以 constexpr 静态常量定义,零运行时开销。

### 实例 5：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **CastTrait 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: flat_quant 的 ScaleVfcuBLAS 函数中定义 castTraitHalf2Float,用于 half 到 float 的类型转换,配合后续指数/尾数拆解做 FP 缩放。

（行 457-496）

```cpp
static __simd_vf__ inline void ScaleVfcuBLAS(__ubuf__ uint16_t* dstPtr, __ubuf__ uint16_t* dst2Ptr,
                                             __ubuf__ uint16_t* srcPtr, uint32_t scaleNum, uint16_t repeatTimes,
                                             float invDstTypeMax)
{
    AscendC::Reg::RegTensor<uint16_t> max16;
    AscendC::Reg::RegTensor<uint32_t> max32;
    AscendC::Reg::RegTensor<uint32_t> exp32;
    AscendC::Reg::RegTensor<uint32_t> man32;
    AscendC::Reg::RegTensor<uint32_t> normalExp32;
    AscendC::Reg::RegTensor<uint32_t> expAddOne32;
    AscendC::Reg::RegTensor<uint32_t> extractExp;
    AscendC::Reg::RegTensor<uint16_t> expOut;
    AscendC::Reg::RegTensor<uint32_t> halfScale;
    AscendC::Reg::RegTensor<uint16_t> recExpOut;

    AscendC::Reg::RegTensor<uint32_t> manMaskFP32;
    AscendC::Reg::Duplicate(manMaskFP32, MAN_MASK_FLOAT);
    AscendC::Reg::RegTensor<uint32_t> expMask;
    AscendC::Reg::Duplicate(expMask, MAX_EXP_FOR_FP32);
    AscendC::Reg::RegTensor<uint32_t> zeroRegTensor32;
    AscendC::Reg::Duplicate(zeroRegTensor32, 0);
    AscendC::Reg::RegTensor<uint32_t> scaleBias;
    AscendC::Reg::Duplicate(scaleBias, FP32_EXP_BIAS_CUBLAS);
    AscendC::Reg::RegTensor<uint32_t> nanRegTensor;
    AscendC::Reg::Duplicate(nanRegTensor, NAN_CUSTOMIZATION_PACK);
    AscendC::Reg::RegTensor<uint32_t> fp4NanRegTensor;
    AscendC::Reg::Duplicate(fp4NanRegTensor, MAX_EXP_FOR_FP8_IN_FP32);
    AscendC::Reg::RegTensor<float> invMax;
    AscendC::Reg::Duplicate(invMax, invDstTypeMax);

    AscendC::Reg::MaskReg cmpResult;
    AscendC::Reg::MaskReg zeroMask;
    AscendC::Reg::MaskReg p0;
    AscendC::Reg::MaskReg p1;
    AscendC::Reg::MaskReg p2;
    AscendC::Reg::MaskReg preMaskScale;
    uint32_t SixtyFour = 64;
    AscendC::Reg::MaskReg dataMaskB16Half = AscendC::Reg::UpdateMask<uint16_t>(SixtyFour);

    static constexpr AscendC::Reg::CastTrait castTraitHalf2Float = {
```

**要点**: 1) 命名 castTraitHalf2Float 直观反映转换方向(half 到 float);2) UpdateMask<uint16_t>(64) 按元素数 64 更新掩码,控制 Cast 作用范围。

### 实例 6：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **CastTrait 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 复数取模算子 complex_abs 中,CastTrait 配合 Reg::Cast 完成 half 与 float 之间的精度转换,寄存器带 RegTraitNumOne 标记单元素 trait。

（行 31-70）

```cpp
    __aicore__ inline ComplexAbsCustom(LocalTensor<T>& dst, LocalTensor<U>& src, uint32_t count)
    {
#ifdef __CCE_AICORE__

        // 常量定义 - float精度
        constexpr uint32_t MIN_NORMAL_FLOAT = 0x00800000u;
        constexpr float SCALE_UP = 16777216.0f;
        constexpr float SCALE_DOWN = 5.9604644775390625e-8f;
        constexpr int16_t SHR_NUM_FOR_FP32 = 23;
        constexpr uint32_t EXP_BIAS = 0x3F800000u; // 1.0的浮点表示(指数127，尾数0)

        using calcTypeInt = typename std::conditional<AscendC::Std::IsSame<T, half>::value, uint16_t, uint32_t>::type;

        // 寄存器定义
        Reg::RegTensor<T> vSrcReg0;
        Reg::RegTensor<T> vSrcReg1;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vA;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vB;
        Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vA0;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vA1;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vB1;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vAS;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vBS;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vA1Sq;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vB1Sq;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vSumSq;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vS;
        Reg::RegTensor<T, Reg::RegTraitNumOne> vResult;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vResultS;

        Reg::RegTensor<float, Reg::RegTraitNumOne> vAbsSrcReg0;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vAbsSrcReg1;

        Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vMinNormalFloat;
        Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vExpBias;
        Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vZero;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vSCALE_UP;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vSCALE_DOWN;

        uint32_t sreg = (uint32_t)count;
```

**要点**: 1) RegTraitNumOne 表示该 RegTensor 携带单元素 trait 模板参数;2) CastTrait 在复数取模的缩放上下保护中间精度,避免溢出/下溢。

### 实例 7：abs::AbscomplexCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **CastTrait 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: abs 算子的复数取模实现 AbscomplexCustom,与 complex_abs 同构,CastTrait 用于 half 与 float 互转以支撑缩放算法。

（行 31-70）

```cpp
    __aicore__ inline AbscomplexCustom(LocalTensor<T>& dst, LocalTensor<U>& src, uint32_t count)
    {
#ifdef __CCE_AICORE__

        // 常量定义 - float精度
        constexpr uint32_t MIN_NORMAL_FLOAT = 0x00800000u;
        constexpr float SCALE_UP = 16777216.0f;
        constexpr float SCALE_DOWN = 5.9604644775390625e-8f;
        constexpr int16_t SHR_NUM_FOR_FP32 = 23;
        constexpr uint32_t EXP_BIAS = 0x3F800000u;      // 1.0的浮点表示(指数127，尾数0)

        using calcTypeInt = typename std::conditional<AscendC::Std::IsSame<T, half>::value, uint16_t, uint32_t>::type;

        // 寄存器定义
        Reg::RegTensor<T> vSrcReg0;
        Reg::RegTensor<T> vSrcReg1;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vA;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vB;
        Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vA0;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vA1;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vB1;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vAS;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vBS;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vA1Sq;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vB1Sq;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vSumSq;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vS;
        Reg::RegTensor<T, Reg::RegTraitNumOne> vResult;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vResultS;

        Reg::RegTensor<float, Reg::RegTraitNumOne> vAbsSrcReg0;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vAbsSrcReg1;

        Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vMinNormalFloat;
        Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vExpBias;
        Reg::RegTensor<uint32_t, Reg::RegTraitNumOne> vZero;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vSCALE_UP;
        Reg::RegTensor<float, Reg::RegTraitNumOne> vSCALE_DOWN;

        uint32_t sreg = (uint32_t)count;
```

**要点**: 1) 与 complex_abs 共享同一计算骨架,体现同类算子的 CastTrait 用法一致;2) 常量 EXP_BIAS 为 1.0 的浮点位模式(0x3F800000u),用于指数还原。

### 实例 8：dynamic_mx_quant::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CreateMask, DeInterleave, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, ShiftRights, StoreUnAlign, StoreUnAlignPost, UnalignReg
- **CastTrait 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴路径定义 castTraitFp32toBF16(ZERO + NO_SAT + ZEROING + CAST_TRUNC 截断),用于 FP32 到 BF16 转换后做指数最大值归约。

（行 507-546）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<float> x0ZeroFP32;
    Reg::RegTensor<float> x0OneFP32;
    Reg::RegTensor<float> x1ZeroFP32;
    Reg::RegTensor<float> x1OneFP32;
    Reg::RegTensor<uint32_t> x0MaxExpB32;
    Reg::RegTensor<uint32_t> x1MaxExpB32;
    Reg::RegTensor<uint32_t> xMaxExpB32;
    Reg::RegTensor<uint16_t> xMaxExpB16;

    Reg::RegTensor<uint32_t> expMask32Bit;
    Reg::Duplicate(expMask32Bit, FP32_MX_MAX_EXP);

    Reg::MaskReg MaskB32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg Mask = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
    Reg::UnalignReg ureg;
    static constexpr Reg::CastTrait castTraitFp32toBF16 = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                           Reg::MaskMergeMode::ZEROING, RoundMode::CAST_TRUNC};
    for (uint16_t i = 0; i < loopNum2VF; i++) {
        // x0ZeroFP32: 1,3,5,7,9,...,127        x1ZeroFP32: 2,4,6,8,10,...,128
        Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
            x0ZeroFP32, x1ZeroFP32, xLocalAddr, VF_LEN_32_DOUBLE);
        // x0OneFP32: 129,131,133,135,...,255  x1OneFP32: 130,132,134,136,...,256
        Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
            x0OneFP32, x1OneFP32, xLocalAddr, VF_LEN_32_DOUBLE);
        // x0ZeroFP32: 1,5,9,13,...,253    x0OneFP32: 3,7,11,15,...,255
        Reg::DeInterleave(x0ZeroFP32, x0OneFP32, x0ZeroFP32, x0OneFP32);
        // x1ZeroFP32: 2,6,10,14,...,254    x1OneFP32: 4,8,12,16,...,256
        Reg::DeInterleave(x1ZeroFP32, x1OneFP32, x1ZeroFP32, x1OneFP32);
        Reg::And((Reg::RegTensor<uint32_t>&)x0ZeroFP32, (Reg::RegTensor<uint32_t>&)x0ZeroFP32, expMask32Bit,
                 MaskB32);
        Reg::And((Reg::RegTensor<uint32_t>&)x0OneFP32, (Reg::RegTensor<uint32_t>&)x0OneFP32, expMask32Bit, MaskB32);
        Reg::And((Reg::RegTensor<uint32_t>&)x1ZeroFP32, (Reg::RegTensor<uint32_t>&)x1ZeroFP32, expMask32Bit,
                 MaskB32);
        Reg::And((Reg::RegTensor<uint32_t>&)x1OneFP32, (Reg::RegTensor<uint32_t>&)x1OneFP32, expMask32Bit, MaskB32);
        Reg::Max(x0MaxExpB32, (Reg::RegTensor<uint32_t>&)x0ZeroFP32, (Reg::RegTensor<uint32_t>&)x0OneFP32, MaskB32);
        Reg::Max(x1MaxExpB32, (Reg::RegTensor<uint32_t>&)x1ZeroFP32, (Reg::RegTensor<uint32_t>&)x1OneFP32, MaskB32);
        Reg::Max(xMaxExpB32, x0MaxExpB32, x1MaxExpB32, MaskB32);
        Reg::ReduceMaxWithDataBlock(xMaxExpB32, xMaxExpB32, MaskB32);
```

**要点**: 1) RoundMode::CAST_TRUNC 选择截断舍入,适配量化场景的确定性行为;2) 配合 DeInterleave/LoadAlign 做交错数据重排后再 And 提取指数位、Max 归约。

### 实例 9：swiglu_group_quant::VFComputeMaxExpMXFP4Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, Compare, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **CastTrait 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: swiglu_group_quant 最大指数计算函数中定义 castTraitHalf2Bf16(RegLayout::UNKNOWN + ZEROING + CAST_TRUNC),用于 half 到 bfloat16 转换以统一指数位宽,是 CastTrait 作为 Cast 模板实参的典型用法。

（行 275-314）

```cpp
__simd_vf__ inline void VFComputeMaxExpMXFP4Vf(__ubuf__ T* srcAddr, __ubuf__ uint16_t* maxExpAddr, uint32_t scaleNum,
                                               uint32_t onceXNum, uint32_t totalCountInUB, uint16_t loopNum)
{
    AscendC::Reg::RegTensor<T> vdExp0;
    AscendC::Reg::RegTensor<T> vdExp1;
    AscendC::Reg::RegTensor<bfloat16_t> vdExp0BF16;
    AscendC::Reg::RegTensor<bfloat16_t> vdExp1BF16;
    AscendC::Reg::RegTensor<uint16_t> vdExpExtract0;
    AscendC::Reg::RegTensor<uint16_t> vdExpExtract1;
    AscendC::Reg::RegTensor<uint16_t> vdExpSelect0;
    AscendC::Reg::RegTensor<uint16_t> vdExpSelect1;
    AscendC::Reg::RegTensor<uint16_t> expMaskBF16;
    AscendC::Reg::Duplicate(expMaskBF16, BF16_EMASK_AND_INF_VAL_MAXFP4);
    AscendC::Reg::RegTensor<uint16_t> invalidmaskfp16;
    AscendC::Reg::Duplicate(invalidmaskfp16, FP16_EMASK_AND_INF_VAL_MAXFP4);
    AscendC::Reg::RegTensor<uint16_t> vdMaxExp;
    AscendC::Reg::MaskReg scaleMask1;
    AscendC::Reg::MaskReg invalidDataMask0;
    AscendC::Reg::MaskReg invalidDataMask1;
    AscendC::Reg::UnalignRegForStore u1;
    static constexpr AscendC::Reg::CastTrait castTraitHalf2Bf16 = {
        AscendC::Reg::RegLayout::UNKNOWN, AscendC::Reg::SatMode::UNKNOWN, AscendC::Reg::MaskMergeMode::ZEROING,
        RoundMode::CAST_TRUNC};

    for (uint16_t i = 0; i < loopNum; i++) {
        scaleMask1 = AscendC::Reg::UpdateMask<T>(totalCountInUB);
        AscendC::Reg::LoadAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                AscendC::Reg::LoadDist::DIST_DINTLV_B16>(vdExp0, vdExp1, srcAddr, onceXNum);

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
```

**要点**: 1) RegLayout::UNKNOWN 表示沿用默认/上下文布局;2) CastTrait 作为模板参数传给 Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>,是 CastTrait 最典型的作为 Cast 模板实参用法。

### 实例 10：floor_div::FloorDivIntS8PostCompute

- **来源类型**: `__aicore__`
- **共现 API**: And, Cast, Compare, DataCopy, Duplicate, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, RegLayout, RegTensor, SatMode, Select, StoreDist, Sub, UpdateMask
- **CastTrait 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: floor_div 整型 int8 后处理中定义两个 CastTrait:castTraitT2ToHalf(CAST_ROUND 舍入)与 castTraitHalfToInt8(CAST_RINT 就近整数),串联完成 T2 到 half 到 int8 的两段转换。

（行 133-172）

```cpp
    __aicore__ inline FloorDivIntS8PostCompute(LocalTensor<T1>& dst, LocalTensor<T2>& input1, LocalTensor<T2>& input2,
                                               LocalTensor<T2>& div, const uint32_t& count)
    {
#ifdef __CCE_AICORE__
        SetCtrlSpr<SAT_POS, SAT_POS>(0);
        constexpr uint32_t VL_T = VECTOR_REG_WIDTH / sizeof(T2);
        __local_mem__ T2* input1Addr = (__local_mem__ T2*)input1.GetPhyAddr();
        __local_mem__ T2* input2Addr = (__local_mem__ T2*)input2.GetPhyAddr();
        __local_mem__ T2* divAddr = (__local_mem__ T2*)div.GetPhyAddr();
        __local_mem__ T1* dstAddr = (__local_mem__ T1*)dst.GetPhyAddr();
        uint16_t loopTimes = (count + VL_T - 1) / VL_T;

        constexpr static Reg::CastTrait castTraitT2ToHalf = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                                  Reg::MaskMergeMode::ZEROING,
                                                                  RoundMode::CAST_ROUND};
        constexpr static Reg::CastTrait castTraitHalfToInt8 = {
            Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT, Reg::MaskMergeMode::ZEROING,
            RoundMode::CAST_RINT};

        __VEC_SCOPE__
        {
            Reg::RegTensor<T2> zeroValue;
            Reg::RegTensor<T2> oneValue;
            Reg::RegTensor<T2> signValue;
            Reg::RegTensor<T2> input1Value;
            Reg::RegTensor<T2> input2Value;
            Reg::RegTensor<T2> divValue;
            Reg::RegTensor<T2> mulValue;
            Reg::RegTensor<T2> subValue;
            Reg::RegTensor<T2> resValue;
            Reg::RegTensor<T2> subValue1;
            Reg::RegTensor<half> halfValue;
            Reg::RegTensor<T1> int8Value;
            Reg::RegTensor<T2> input1SignValue;
            Reg::RegTensor<T2> input2SignValue;

            Reg::MaskReg preg;
            Reg::MaskReg negValue;
            Reg::MaskReg signNegValue;
            Reg::MaskReg resMaskValue;
```

**要点**: 1) 同一函数按转换方向定义多个 CastTrait,体现 RoundMode 需按目标类型选择(half 用 ROUND、int8 用 RINT);2) SetCtrlSpr<SAT_POS, SAT_POS> 设置饱和控制寄存器,与 CastTrait 的 SatMode 协同。

### 实例 11：swiglu_mx_quant::ComputeDataF4Last

- **来源类型**: `__aicore__`
- **共现 API**: Cast, CreateMask, DataCopy, HighLowPart, Interleave, LoadDist, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, StoreDist, UpdateMask
- **CastTrait 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: swiglu_mx_quant 末轴 FP4 量化中定义三个 CastTrait(通用转换、half 到 bf16、fp32 到 bf16),RoundMode 字段使用变量 roundMode/toBf16RoundMode 由上层模板参数决定,支撑多段精度链。

（行 736-775）

```cpp
__aicore__ inline void ComputeDataF4Last(__ubuf__ T* srcAddr, __ubuf__ uint16_t* halfScaleLocalAddr,
                                         __ubuf__ int8_t* outLocalAddr, int64_t dim0OnceSize, int64_t dim1AlignSize)
{
    uint32_t totalCountInUB = dim0OnceSize * dim1AlignSize;
    uint16_t loopNum = CeilDivision(totalCountInUB, QUANT_ONCE_NUM);
    int64_t elementAfterReduce = SCALE_ONCE_NUM;
    int64_t onceXNum = QUANT_ONCE_NUM;
    int64_t onceYNum = OUT_ELE_NUM_ONE_BLK;
    static constexpr AscendC::Reg::CastTrait castTrait = {AscendC::Reg::RegLayout::ZERO,
                                                               AscendC::Reg::SatMode::UNKNOWN,
                                                               AscendC::Reg::MaskMergeMode::ZEROING, roundMode};
    static constexpr AscendC::Reg::CastTrait castTraitHalf2Bf16 = {
        AscendC::Reg::RegLayout::UNKNOWN, AscendC::Reg::SatMode::UNKNOWN,
        AscendC::Reg::MaskMergeMode::ZEROING, toBf16RoundMode};
    static constexpr Reg::CastTrait castTraitFp32toBF16 = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                                Reg::MaskMergeMode::ZEROING, roundMode};
    __VEC_SCOPE__
    {
        AscendC::Reg::MaskReg dataMask1;
        AscendC::Reg::RegTensor<uint16_t> halfScaleForMul;
        AscendC::Reg::RegTensor<T> vdExp0, vdExp1;
        AscendC::Reg::RegTensor<U> vdExp0FP4, vdExp1FP4;
        Reg::RegTensor<float> halfScaleForMulFP32;
        Reg::RegTensor<float> vdExp0ZeroFP32, vdExp0OneFP32, vdExp1ZeroFP32, vdExp1OneFP32;
        Reg::RegTensor<bfloat16_t> vdExp0ZeroBF16, vdExp0OneBF16, vdExp1ZeroBF16, vdExp1OneBF16;
        AscendC::Reg::RegTensor<bfloat16_t> vdExp0BF16, vdExp1BF16;
        Reg::MaskReg dataMaskB16 = Reg::CreateMask<half>();
        Reg::MaskReg dataMaskB32 = Reg::CreateMask<float>();
        for (uint16_t i = 0; i < loopNum; i++) {
            dataMask1 = AscendC::Reg::UpdateMask<T>(totalCountInUB);
            AscendC::Reg::DataCopy<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                        AscendC::Reg::LoadDist::DIST_DINTLV_B16>(vdExp0, vdExp1, srcAddr,
                                                                                      onceXNum);
            AscendC::Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                                        AscendC::Reg::LoadDist::DIST_E2B_B16>(halfScaleForMul, halfScaleLocalAddr,
                                                                                   elementAfterReduce);
            if constexpr (IsSame<T, half>::value && roundMode == RoundMode::CAST_FLOOR) {
                AscendC::Reg::RegTensor<bfloat16_t> vdExp0BF16, vdExp1BF16;
                AscendC::Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(vdExp0BF16, vdExp0, dataMask1);
                AscendC::Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(vdExp1BF16, vdExp1, dataMask1);
```

**要点**: 1) CastTrait 的 RoundMode 字段可使用变量(roundMode/toBf16RoundMode)而非固定枚举,由上层模板参数决定;2) RegLayout::ZERO/UNKNOWN 混用,按是否需要置零选择。

### 实例 12：dynamic_mx_quant::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CreateMask, HighLowPart, Interleave, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, StoreAlign, StoreDist
- **CastTrait 调用次数**: 5
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴 FP4 路径定义 5 个 CastTrait,其中 castTraitF16toFp32Zero(RegLayout::ZERO)与 castTraitF16toFp32One(RegLayout::ONE)成对出现,把交错数据的偶数位/奇数位分别展开到 FP32。

（行 1132-1171）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<uint16_t> halfScaleForMul;
    Reg::RegTensor<T> xExp0;
    Reg::RegTensor<T> xExp1;
    Reg::RegTensor<T> xExp0Convert;
    Reg::RegTensor<T> xExp1Convert;
    Reg::RegTensor<float> halfScaleForMulFP32;
    Reg::RegTensor<float> xExp0ZeroFP32;
    Reg::RegTensor<float> xExp0OneFP32;
    Reg::RegTensor<float> xExp1ZeroFP32;
    Reg::RegTensor<float> xExp1OneFP32;
    Reg::RegTensor<bfloat16_t> xExp0ZeroBF16;
    Reg::RegTensor<bfloat16_t> xExp0OneBF16;
    Reg::RegTensor<bfloat16_t> xExp1ZeroBF16;
    Reg::RegTensor<bfloat16_t> xExp1OneBF16;

    Reg::RegTensor<bfloat16_t> xExp0BF16;
    Reg::RegTensor<bfloat16_t> xExp1BF16;

    Reg::RegTensor<U> xExp0FP4;
    Reg::RegTensor<U> xExp1FP4;

    Reg::RegTensor<bfloat16_t> xBF16Exp0FP4;
    Reg::RegTensor<bfloat16_t> xBF16Exp1FP4;

    Reg::MaskReg dataMaskB16 = Reg::CreateMask<half>();
    Reg::MaskReg dataMaskB32 = Reg::CreateMask<float>();

    static constexpr Reg::CastTrait castTrait = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                 Reg::MaskMergeMode::ZEROING, roundMode};
    static constexpr Reg::CastTrait castTraitHalf2Bf16 = {Reg::RegLayout::UNKNOWN, Reg::SatMode::UNKNOWN,
                                                          Reg::MaskMergeMode::ZEROING, toBf16RoundMode};
    static constexpr Reg::CastTrait castTraitF16toFp32Zero = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                              Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
    static constexpr Reg::CastTrait castTraitF16toFp32One = {Reg::RegLayout::ONE, Reg::SatMode::UNKNOWN,
                                                             Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
    static constexpr Reg::CastTrait castTraitFp32toBF16 = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                           Reg::MaskMergeMode::ZEROING, roundMode};
```

**要点**: 1) RegLayout::ZERO/ONE 是 CastTrait 体现交错拆分语义的关键:ZERO 取偶数位、ONE 取奇数位,两者配合 Interleave/DeInterleave 使用;2) SatMode::NO_SAT 用于 FP32 到 BF16 避免截断失真。

### 实例 13：dynamic_mx_quant::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CreateMask, HighLowPart, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, StoreDist, UpdateMask
- **CastTrait 调用次数**: 6
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 大尾轴高性能路径定义 6 个 CastTrait,覆盖 bf16 到 fp4(SAT 饱和)、xdtype 到 fp32 的 ZERO/ONE 拆分、fp32 到 ydtype(SAT + CAST_RINT)、fp32 到 bf16 的 ZERO/ONE 拆分,是 CastTrait 字段组合最丰富的实例。

（行 994-1033）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<xDtype> x;
    Reg::RegTensor<bfloat16_t> valueBF16;
    Reg::RegTensor<bfloat16_t> x0BF16;
    Reg::RegTensor<bfloat16_t> x1BF16;
    Reg::RegTensor<float> x0FP32;
    Reg::RegTensor<float> x1FP32;
    Reg::RegTensor<uint16_t> reversedShareExpBF16;
    Reg::RegTensor<float> reversedShareExp0FP32;
    Reg::RegTensor<float> reversedShareExp1FP32;
    Reg::RegTensor<uint32_t> yZeroU32;
    Reg::RegTensor<uint16_t> yZeroU16;
    Reg::RegTensor<uint8_t> yZeroU8;
    Reg::RegTensor<yDtype> yZeroFP8;
    Reg::RegTensor<yDtype> yOneFP8;
    Reg::RegTensor<yDtype> yZeroFP4;
    Reg::MaskReg pregAll8;
    Reg::MaskReg pregAll16 = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregAll32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();

    uint32_t maskLen = dataLen32Align_;
    static constexpr Reg::CastTrait castTraitBf16toFp4 = {Reg::RegLayout::ZERO, Reg::SatMode::SAT,
                                                          Reg::MaskMergeMode::ZEROING, roundMode};
    static constexpr Reg::CastTrait castTraitXdtypetoFp32Zero = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                                 Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
    static constexpr Reg::CastTrait castTraitXdtypetoFp32One = {Reg::RegLayout::ONE, Reg::SatMode::UNKNOWN,
                                                                Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
    static constexpr Reg::CastTrait castTraitFp32toYdtype = {Reg::RegLayout::ZERO, Reg::SatMode::SAT,
                                                             Reg::MaskMergeMode::ZEROING, RoundMode::CAST_RINT};
    static constexpr Reg::CastTrait castTraitFp32toBF16Zero = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                               Reg::MaskMergeMode::ZEROING, roundMode};
    static constexpr Reg::CastTrait castTraitFp32toBF16One = {Reg::RegLayout::ONE, Reg::SatMode::NO_SAT,
                                                              Reg::MaskMergeMode::ZEROING, roundMode};

    DataCopy<uint16_t, Reg::LoadDist::DIST_UNPACK_B16>((Reg::RegTensor<uint16_t>&)reversedShareExp0FP32, tmpAddr);
    Reg::Cast<float, bfloat16_t, castTraitXdtypetoFp32Zero>(
        reversedShareExp0FP32, (Reg::RegTensor<bfloat16_t>&)reversedShareExp0FP32, pregAll16);

    for (uint16_t j = 0; j < blockCount; j++) {
```

**要点**: 1) SatMode::SAT 在降精度(到 FP4/到 ydtype)时启用饱和,防止溢出;2) CAST_RINT 就近舍入适配 FP8 量化;3) ZERO/ONE 成对拆分再次出现,是该算子高频模式。

### 实例 14：dynamic_mx_quant::Reg::StoreAlign

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CreateMask, Interleave, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, PostLiteral, RegLayout, RegTensor, SatMode, StoreAlign, StoreDist
- **CastTrait 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴路径定义 3 个 CastTrait,串联 half 到 bf16 到乘 scale 到 bf16 到 FP4 的量化链,castTraitFp32toBF16Data 用于中间 FP32 到 BF16 回写。

（行 1032-1071）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<T> xExp0;
    Reg::RegTensor<T> xExp1;
    Reg::RegTensor<T> xExp0Convert;
    Reg::RegTensor<T> xExp1Convert;
    Reg::RegTensor<uint16_t> halfScaleForMul;
    Reg::RegTensor<bfloat16_t> xExp0BF16;
    Reg::RegTensor<bfloat16_t> xExp1BF16;
    Reg::RegTensor<bfloat16_t> xBF16Exp0FP4;
    Reg::RegTensor<bfloat16_t> xBF16Exp1FP4;
    Reg::RegTensor<U> xExp0FP4;
    Reg::RegTensor<U> xExp1FP4;

    Reg::MaskReg Mask = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();

    static constexpr Reg::CastTrait castTrait = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                 Reg::MaskMergeMode::ZEROING, roundMode};
    static constexpr Reg::CastTrait castTraitHalf2Bf16 = {Reg::RegLayout::UNKNOWN, Reg::SatMode::UNKNOWN,
                                                          Reg::MaskMergeMode::ZEROING, toBf16RoundMode};
    static constexpr Reg::CastTrait castTraitFp32toBF16Data = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                               Reg::MaskMergeMode::ZEROING, roundMode};

    for (uint16_t i = 0; i < loopNum2VF; i++) {
        Reg::LoadAlign<T, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
            xExp0, xExp1, xLocalAddr, VF_LEN_16_DOUBLE);
        Reg::LoadAlign<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_E2B_B16>(
            halfScaleForMul, recipScaleLocalAddr, ELEMENT_AFTER_REDUCE_);

        if constexpr (roundMode == RoundMode::CAST_RINT) {
            ComputeFP4FromHalf(xExp0, xExp0, Mask);
            ComputeFP4FromHalf(xExp1, xExp1, Mask);
        }
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xExp0BF16, xExp0, Mask);
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xExp1BF16, xExp1, Mask);
        Reg::Mul(xExp0BF16, xExp0BF16, (Reg::RegTensor<bfloat16_t>&)halfScaleForMul, Mask);
        Reg::Mul(xExp1BF16, xExp1BF16, (Reg::RegTensor<bfloat16_t>&)halfScaleForMul, Mask);
        Reg::Interleave(xExp0BF16, xExp1BF16, xExp0BF16, xExp1BF16);
        Reg::Cast<U, bfloat16_t, castTrait>(xExp0FP4, xExp0BF16, Mask);
        Reg::Cast<U, bfloat16_t, castTrait>(xExp1FP4, xExp1BF16, Mask);
```

**要点**: 1) CastTrait 与 Mul/Interleave 组合体现先转换、再缩放、再量化的标准流水;2) ComputeFP4FromHalf 在 CAST_RINT 模式下做特殊 FP4 处理,与 CastTrait 的 RoundMode 分支协同。

### 实例 15：glu_grad::ComputeGluGradCore

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Cast, DataCopy, Div, DivSpecificMode, Exp, MaskMergeMode, Mul, Muls, RegLayout, RegTensor, SatMode, Sub
- **CastTrait 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: glu_grad 反向算子中定义 4 个 CastTrait:castToFloatEven/Odd(RegLayout::ZERO/ONE)把 bf16/half 偶/奇位提升到 float,castFromFloatEven/Odd(CAST_RINT)再转回,用于高精度 GLU 梯度计算。

（行 43-82）

```cpp
__aicore__ inline void ComputeGluGradCore(
    AscendC::Reg::RegTensor<T>& vregA,
    AscendC::Reg::RegTensor<T>& vregB,
    AscendC::Reg::RegTensor<T>& vregGrad,
    AscendC::Reg::RegTensor<T>& vregOutputA,
    AscendC::Reg::RegTensor<T>& vregOutputB,
    __local_mem__ T* outALocalPtr,
    __local_mem__ T* outBLocalPtr,
    uint16_t loopIdx,
    uint32_t vlSize,
    AscendC::Reg::MaskReg& preg0,
    AscendC::Reg::MaskReg& maskAll8,
    AscendC::Reg::RegTensor<float>& vregOne)
{
    AscendC::Reg::RegTensor<float> vregSigmoidB;
    AscendC::Reg::RegTensor<float> vregGradA;
    AscendC::Reg::RegTensor<float> vregTemp;
    AscendC::Reg::RegTensor<float> vregSub;
    AscendC::Reg::RegTensor<float> vregGradB;

    static constexpr AscendC::Reg::DivSpecificMode highPrecisionDivMode = {
        AscendC::Reg::MaskMergeMode::ZEROING, true};

    if constexpr (std::is_same_v<T, bfloat16_t> || std::is_same_v<T, half>) {
        AscendC::Reg::RegTensor<float> vregAF;
        AscendC::Reg::RegTensor<float> vregBF;
        AscendC::Reg::RegTensor<float> vregGradF;

        constexpr static AscendC::Reg::CastTrait castToFloatEven = {
            AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::NO_SAT,
            AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
        constexpr static AscendC::Reg::CastTrait castToFloatOdd = {
            AscendC::Reg::RegLayout::ONE, AscendC::Reg::SatMode::NO_SAT,
            AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
        constexpr static AscendC::Reg::CastTrait castFromFloatEven = {
            AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::NO_SAT,
            AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::CAST_RINT};
        constexpr static AscendC::Reg::CastTrait castFromFloatOdd = {
            AscendC::Reg::RegLayout::ONE, AscendC::Reg::SatMode::NO_SAT,
            AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::CAST_RINT};
```

**要点**: 1) Even/Odd(ZERO/ONE)成对 CastTrait 是处理交错低精度数据的通用范式;2) DivSpecificMode 也以 MaskMergeMode::ZEROING 初始化,说明 MaskMergeMode 不仅用于 CastTrait,也是其它 trait 结构体的通用字段。

### CastTrait 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, Compare | ZERO 布局置零转换(castTraitZero) | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, Cast, Compare | ZERO 布局置零转换 + 全量掩码(MaskPattern::ALL) | __VEC_SCOPE__ |
| dynamic_mx_quant | And, Cast, Compare, Copy | 全量掩码 + CastTrait 作为 Cast 模板特征 | __VEC_SCOPE__ |
| dynamic_block_quant | And, Cast, CompareScalar, CreateMask | Reg 命名空间 ZERO+NO_SAT 块量化转换 | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, Compare | half 到 float 转换(castTraitHalf2Float) | __simd_vf__ |
| complex_abs | Abs, Add, Cast, Compare | half 与 float 互转(RegTraitNumOne 单元素) | __aicore__ |
| abs | Abs, Add, Cast, Compare | half 与 float 互转(同 complex_abs 骨架) | __aicore__ |
| dynamic_mx_quant | And, CreateMask, DeInterleave, Duplicate | FP32 到 BF16 截断转换 + 指数归约 | __VEC_SCOPE__ |
| swiglu_group_quant | And, Cast, Compare, Duplicate | half 到 bf16 转换(UNKNOWN 布局 + 截断) | __simd_vf__ |
| floor_div | And, Cast, Compare, DataCopy | T2 到 half 到 int8 两段转换(ROUND/RINT) | __aicore__ |
| swiglu_mx_quant | Cast, CreateMask, DataCopy, HighLowPart | 三段精度链(变量 RoundMode) | __aicore__ |
| dynamic_mx_quant | Cast, CreateMask, HighLowPart, Interleave | ZERO/ONE 成对拆分(F16 到 FP32) | __VEC_SCOPE__ |
| dynamic_mx_quant | Cast, CreateMask, HighLowPart, LoadDist | 6 个 CastTrait 全字段组合(SAT+RINT+ZERO/ONE) | __VEC_SCOPE__ |
| dynamic_mx_quant | Cast, CreateMask, Interleave, LoadAlign | half 到 bf16 到 FP4 量化链 + 缩放 | __VEC_SCOPE__ |
| glu_grad | Add, Adds, Cast, DataCopy | Even/Odd 成对提升/回转 float | __aicore__ |
