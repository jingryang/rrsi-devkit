# RegLayout

**页面ID:** atlasascendc_api_07_00237  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00237.html

---

源操作数与目的操作数类型位宽不同时，可以分为两种情况：

1. 源操作数与目的操作数位宽比为1:2或2:1。
2. 源操作数与目的操作数位宽比为1:4或4:1。

该数据结构是为了在两种情况中决定读或写的位置，在情景1下，可以将一个256B大小的RegTensor分为两部分，对于每一字节，其索引为下标i%2；在情景2下，可以将一个256B大小的RegTensor分为四部分，对于每一字节，其索引为下标i%4。RegLayout的取值如下：

- RegLayout::ZERO，写入索引0的位置
- RegLayout::ONE，写入索引1的位置
- RegLayout::TWO，写入索引2的位置
- RegLayout::THREE，写入索引3的位置

```
enum class RegLayout {
    UNKNOWN = -1,
    ZERO,
    ONE,
    TWO,
    THREE
};
```

![](images/atlasascendc_api_07_00237_img_001.png)

如图所示，RegLayout::ZERO/RegLayout::ONE这2种模式仅在位宽比值1:2或2:1的情况下可以使用，例如float32转int16, 位宽比为2比1。例如，对于位宽为2:1的数据类型转换，可以通过RegLayout选定写入数据的位置。当选择RegLayout::ZERO时，数据写入索引为0的位置，当选择RegLayout::ONE时，数据写入索引为1的位置。

RegLayout::ZERO/RegLayout::ONE/RegLayout::TWO/RegLayout::THREE这4种模式仅在位宽比值1比4或4比1的情况下可以使用，例如float32转int8,位宽比为4比1。例如，对于位宽为4:1的数据类型转换，当选择RegLayout::ZERO时，数据写入索引为0的位置；当选择RegLayout::ONE时，数据写入索引为1的位置；当选择RegLayout::TWO时，数据写入索引为2的位置；当选择RegLayout::THREE时，数据写入索引为3的位置。


---
## 从 Ascend 950PR / arch35 算子源码提取的 RegLayout 实例

### 实例 1：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **RegLayout 调用次数**: 5
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 grouped_dynamic_mx_quant 的 FP8 量化主路径中，用 RegLayout::ZERO 构造 CastTrait，将 BF16/FP32 数据做位宽转换时写入 256B RegTensor 的索引 0 位置。

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

**要点**: 1) RegLayout::ZERO 表示写入 RegTensor 索引 0，与 SatMode/MaskMergeMode/RoundMode 共同构成 CastTrait 四元组；
2) 此处 SatMode::UNKNOWN、RoundMode::UNKNOWN 表示由 Cast 模板缺省值决定；
3) MaskMergeMode::ZEROING 表示掩码置零语义。

### 实例 2：dynamic_mx_quant::Reg::StoreAlign

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskOr, MaskReg, Maxs, Mul, Pack, PostLiteral, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **RegLayout 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴 FP8 量化中，对 uint16/BF16→FP32 的上采样转换用 RegLayout::ZERO 构造多个 CastTrait，把窄位宽数据写到 RegTensor 索引 0，再以 StoreAlign 回存。

（行 690-729）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<uint16_t> max16;
    Reg::RegTensor<uint32_t> max32;
    Reg::RegTensor<uint32_t> exp32;
    Reg::RegTensor<uint32_t> man32;
    Reg::RegTensor<uint32_t> normalExp32;
    Reg::RegTensor<uint32_t> expAddOne32;
    Reg::RegTensor<uint32_t> extractExp;
    Reg::RegTensor<uint16_t> expOut;
    Reg::RegTensor<uint32_t> halfScale;
    Reg::RegTensor<uint16_t> recExpOut;

    Reg::RegTensor<uint32_t> invMax;
    Reg::Duplicate(invMax, dtypeMax_);
    Reg::RegTensor<uint32_t> manMaskFP32;
    Reg::Duplicate(manMaskFP32, FP32_MX_MAN_MASK);
    Reg::RegTensor<uint32_t> expMask;
    Reg::Duplicate(expMask, FP32_MX_MAX_EXP);
    Reg::RegTensor<uint32_t> zeroU32;
    Reg::Duplicate(zeroU32, 0);
    Reg::RegTensor<uint32_t> scaleBias;
    Reg::Duplicate(scaleBias, FP32_MX_EXP_BIAS_CUBLAS);
    Reg::RegTensor<uint32_t> nanU32;
    Reg::Duplicate(nanU32, FP32_NAN_PACK);
    Reg::RegTensor<uint32_t> fp8NanU32;
    Reg::Duplicate(fp8NanU32, FP8_MAX_EXP_IN_FP32);

    Reg::MaskReg cmpResult;
    Reg::MaskReg zeroMask;
    Reg::MaskReg p0;
    Reg::MaskReg p1;
    Reg::MaskReg p2;
    uint32_t SixtyFour = 64;
    Reg::MaskReg dataMaskB16Half = Reg::UpdateMask<uint16_t>(SixtyFour);
    Reg::MaskReg maskFloat = Reg::CreateMask<uint32_t>();

    static constexpr Reg::CastTrait castTrait2Float = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                       Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
    static constexpr Reg::CastTrait castTraitBf162Float = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
```

**要点**: 1) 低位宽→高位宽转换（2:1 或 4:1）用 RegLayout::ZERO 选定写入位置；
2) 同一函数内多个 CastTrait 共用 RegLayout::ZERO 但 SatMode/RoundMode 不同；
3) 配合 StoreAlign/StoreDist 完成对齐回存。

### 实例 3：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, Interleave, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **RegLayout 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 非尾轴主计算路径入口，声明量化所需的 FP32/BF16/uint8 寄存器组，后续用 RegLayout 构造 CastTrait 完成 BF16↔FP32 的位宽转换。

（行 553-592）

```cpp
__VEC_SCOPE__
{
    if constexpr (IsSame<T, float>::value) {
        return;
    }
    Reg::RegTensor<calcType> xReg;
    Reg::RegTensor<calcTypeInt> absReg;
    Reg::RegTensor<calcTypeInt> xMaxReg;
    Reg::RegTensor<calcTypeInt> x2MaxReg;
    Reg::RegTensor<uint32_t> xFP32MaxReg;
    Reg::RegTensor<uint32_t> xFP32MaxReg2;
    Reg::RegTensor<uint32_t> expFP32Reg; // 指数
    Reg::RegTensor<uint32_t> expFP32Reg2;
    Reg::RegTensor<uint32_t> manFP32Reg; // 尾数
    Reg::RegTensor<uint32_t> manFP32Reg2;
    Reg::RegTensor<uint32_t> extractExpReg; // 指数 + 1
    Reg::RegTensor<uint32_t> extractExpReg2;
    Reg::RegTensor<uint16_t> expBF16Reg;
    Reg::RegTensor<uint16_t> expBF16Reg2;
    Reg::RegTensor<uint8_t> mxScale;
    Reg::RegTensor<uint8_t> out;
    Reg::RegTensor<calcTypeInt> scaleReprocal; // 1/scale
    Reg::RegTensor<uint32_t> zeroRegTensor32;
    Reg::RegTensor<uint16_t> zeroRegTensor16;
    Reg::RegTensor<float> invDstTypeMax;

    Reg::RegTensor<calcTypeInt> absForXReg;
    Reg::RegTensor<calcTypeInt> biasReg;
    Reg::RegTensor<calcTypeInt> infForXReg;
    Reg::RegTensor<uint32_t> infForFP32Reg;
    Reg::RegTensor<float> dstTypeMaxReg;
    Reg::RegTensor<calcTypeInt> nan;
    Reg::RegTensor<calcTypeInt> specialExp;
    Reg::RegTensor<uint32_t> expAndreShareExpFP32RegTensor;
    Reg::RegTensor<uint32_t> manAndmxScaleFP32RegTensor;

    Reg::UnalignReg u0;
    Reg::UnalignReg u1;
    Reg::MaskReg p2;
    Reg::MaskReg infMask;
```

**要点**: 1) 本片段为函数头部寄存器声明，RegLayout 在后续 CastTrait 中使用（调用次数 2）；
2) not_tail_axis 分支处理非末轴的 MX 量化；
3) 配合 UnalignReg/MaskReg 处理非对齐尾块。

### 实例 4：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Max, Min, PostLiteral, ReduceMax, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **RegLayout 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_block_quant 单行 kernel 中，用 RegLayout::ZERO 构造 CastTrait，在 FP8 量化时把输入数据类型转换写入 RegTensor 索引 0 位置。

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

**要点**: 1) 此处 SatMode::NO_SAT 明确不饱和，与实例 2 的 UNKNOWN 取值不同；
2) 配合 ReduceMax/Div 完成分块缩放计算；
3) 使用 Reg:: 完整命名空间形式定义 CastTrait。

### 实例 5：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **RegLayout 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: flat_quant 的 BLAS 缩放向量函数中，声明 CastTrait 用于 half→float 的位宽转换，RegLayout 控制窄位宽数据写入 RegTensor 的位置。

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

**要点**: 1) __simd_vf__ 内联函数，使用 Reg:: 完整命名空间；
2) 配合 LoadAlign/StoreAlign 处理连续 64 元素块；
3) 为 FP4/FP8 量化计算指数和尾数做准备。

### 实例 6：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **RegLayout 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: complex_abs 算子的复数绝对值计算（a+bi→sqrt(a²+b²)）入口，声明 FP32 寄存器组，后续用 RegLayout 构造 CastTrait 完成 half/bfloat16↔float 的位宽转换（2:1）。

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

**要点**: 1) 复数绝对值需把 half/bf16 提升到 float 做平方和开方，用 RegLayout::ZERO 写入索引 0；
2) RegTraitNumOne 标记单元素寄存器用于标量常量；
3) 配合 Sqrt/Mul/Add 完成数学运算。

### 实例 7：abs::AbscomplexCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **RegLayout 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: abs 算子的复数取绝对值实现，与 complex_abs 同构，用 RegLayout 构造 CastTrait 完成 half/bfloat16↔float 的位宽转换。

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

**要点**: 1) abs 复数版与 complex_abs 共用同一计算结构（平方和开方）；
2) RegLayout::ZERO 用于窄→宽位宽转换写入索引 0；
3) 配合 ScaleUp/ScaleDown 处理 subnormal 精度。

### 实例 8：dynamic_mx_quant::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, SatMode, ShiftRights, StoreUnAlign, StoreUnAlignPost, UnalignReg
- **RegLayout 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴非对齐回存路径，用 RegLayout::ZERO 构造 castTraitFp32toBF16，将 FP32 降采样得到的 BF16 结果写入 RegTensor 索引 0，再以 StoreUnAlign/StoreUnAlignPost 非对齐回存。

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

**要点**: 1) FP32→BF16 为 2:1 位宽转换，用 RegLayout::ZERO 选定写入位置；
2) RoundMode::CAST_TRUNC 截断舍入；
3) 配合 DeInterleave 把交错数据拆成偶/奇序列后取指数最大值。

### 实例 9：dynamic_mx_quant::Reg::Select

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Cast, CastTrait, Compare, CreateMask, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, Max, Pack, RegTensor, SatMode, Select, ShiftRights, Sub
- **RegLayout 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 高性能大尾块优化路径的 Select 计算段，声明 uint32/uint16/bf16 寄存器组，后续用 RegLayout 构造 CastTrait 完成位宽转换与特殊值选择。

（行 522-561）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<uint32_t> x0U32;
    Reg::RegTensor<uint32_t> x1U32;
    Reg::RegTensor<uint32_t> exp0U32;
    Reg::RegTensor<uint32_t> exp1U32;
    Reg::RegTensor<uint16_t> x0U16;
    Reg::RegTensor<uint16_t> x1U16;
    Reg::RegTensor<uint16_t> expMaxU16;
    Reg::RegTensor<uint32_t> expMaxU32;
    Reg::RegTensor<uint16_t> mxScaleBF16;
    Reg::RegTensor<uint16_t> reversedShareExpBF16;
    Reg::RegTensor<uint8_t> mxScale;
    Reg::RegTensor<uint16_t> x0AbsU16; // x绝对值
    Reg::RegTensor<uint16_t> x1AbsU16; // x绝对值
    Reg::RegTensor<uint32_t> x0AbsU32; // x绝对值
    Reg::RegTensor<uint32_t> x1AbsU32; // x绝对值
    Reg::RegTensor<uint16_t> maxU16;   // 绝对值最大值
    Reg::RegTensor<uint32_t> maxU32;   // 绝对值最大值

    Reg::RegTensor<uint16_t> specialExpU16;
    Reg::RegTensor<uint16_t> biasU16;
    Reg::RegTensor<uint16_t> zeroU16;
    Reg::RegTensor<uint16_t> nanU16;
    Reg::RegTensor<uint16_t> maxEleU16;
    Reg::RegTensor<uint32_t> maxEleU32;
    Reg::RegTensor<uint16_t> dtypeYMaxExp;
    Reg::RegTensor<uint16_t> subNumForScale;
    Reg::RegTensor<uint16_t> fp8NanU16;
    Reg::RegTensor<uint16_t> absForXU16;
    Reg::RegTensor<uint32_t> absForXU32;

    Reg::RegTensor<bfloat16_t> xBF16;
    Reg::RegTensor<uint32_t> roundBiasU32;
    Reg::RegTensor<uint32_t> oneU32;

    Reg::MaskReg infMask;
    Reg::MaskReg zeroMask;
    Reg::MaskReg invalidDataMask;
    Reg::MaskReg pregAll8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::ALL>();
```

**要点**: 1) high_perf_large_tail 分支针对大尾块优化，用 Select 处理 NaN/Inf 等特殊值；
2) RegLayout 在后续 CastTrait 中用于 bf16↔fp32 转换；
3) 配合 MaskPattern::ALL 全量掩码。

### 实例 10：dynamic_mx_quant::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, Interleave, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegTensor, SatMode, StoreAlign, StoreDist
- **RegLayout 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴 FP4 量化中，同时定义 BF16→FP32（上采样）和 FP32→BF16（下采样）两套 CastTrait，均用 RegLayout::ZERO 控制写入位置，再用 Cast 模板执行类型转换。

（行 1300-1339）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<uint16_t> halfScaleForMul;
    Reg::RegTensor<float> floatScaleForMul;
    Reg::RegTensor<float> x0Zero;
    Reg::RegTensor<float> x0One;
    Reg::RegTensor<float> x1Zero;
    Reg::RegTensor<float> x1One;

    Reg::RegTensor<bfloat16_t> x0ZeroBF16;
    Reg::RegTensor<bfloat16_t> x0OneBF16;
    Reg::RegTensor<bfloat16_t> x1ZeroBF16;
    Reg::RegTensor<bfloat16_t> x1OneBF16;

    Reg::RegTensor<U> xExp0FP4;
    Reg::RegTensor<U> xExp1FP4;

    Reg::MaskReg maskFP32 = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
    Reg::MaskReg maskB16 = Reg::CreateMask<half, Reg::MaskPattern::ALL>();

    static constexpr Reg::CastTrait castTraitBf16ToFp32 = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                           Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
    static constexpr Reg::CastTrait castTrait = {Reg::RegLayout::ZERO, Reg::SatMode::UNKNOWN,
                                                 Reg::MaskMergeMode::ZEROING, roundMode};
    static constexpr Reg::CastTrait castTraitFp32toBF16 = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                           Reg::MaskMergeMode::ZEROING, toBf16RoundMode};

    Reg::RegTensor<int32_t> maxEleReg;
    Reg::Duplicate(maxEleReg, FP32_MX_MAX_EXP);

    for (uint16_t i = 0; i < loopNum2VF; i++) {
        Reg::LoadAlign<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_E2B_B16>(
            halfScaleForMul, recipScaleLocalAddr, ELEMENT_AFTER_REDUCE_);
        Reg::Cast<float, bfloat16_t, castTraitBf16ToFp32>(floatScaleForMul,
                                                          (Reg::RegTensor<bfloat16_t>&)halfScaleForMul, maskFP32);

        Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
            x0Zero, x1Zero, xLocalAddr, VF_LEN_32_DOUBLE);
        Reg::LoadAlign<float, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B32>(
            x0One, x1One, xLocalAddr, VF_LEN_32_DOUBLE);
```

**要点**: 1) 同一作用域定义 3 个 CastTrait，RegLayout::ZERO 一致但 SatMode/RoundMode 各异；
2) Cast<float, bfloat16_t, castTraitBf16ToFp32> 把 CastTrait 作为非类型模板参数传入；
3) 配合 LoadAlign+PostLiteral::POST_MODE_UPDATE 实现地址自增加载。

### 实例 11：swiglu_group_quant::VFComputeMaxExpMXFP4Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **RegLayout 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: swiglu_group_quant 的 MXFP4 指数最大值计算中，用 RegLayout::UNKNOWN 构造 castTraitHalf2Bf16（half→bfloat16 同为 16bit、位宽比 1:1，故 layout 留空），配合掩码选择处理非法值。

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

**要点**: 1) half→bfloat16 位宽比 1:1，RegLayout::UNKNOWN 表示不指定写入位置；
2) CastTrait 作为 Cast 模板参数 castTraitHalf2Bf16 传入；
3) 配合 Compare+Select 屏蔽 NaN/Inf 后提取指数。

### 实例 12：floor_div::FloorDivIntS8PostCompute

- **来源类型**: `__aicore__`
- **共现 API**: And, Cast, CastTrait, Compare, DataCopy, Duplicate, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, RegTensor, SatMode, Select, StoreDist, Sub, UpdateMask
- **RegLayout 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: floor_div 整数除法后处理中，用 RegLayout::ZERO 构造两套 CastTrait：T2→half（上采样，CAST_ROUND）和 half→int8（下采样 4:1，CAST_RINT），分别用于中间计算与最终输出。

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

**要点**: 1) T2(half/bf16)→half 为同位宽或 2:1，half→int8 为 4:1 位宽转换，均用 RegLayout::ZERO；
2) 两个 CastTrait 的 RoundMode 不同（ROUND 用于上采样、RINT 用于下采样取整）；
3) 配合 SetCtrlSpr 设置饱和控制、Mul/Sub 完成除法修正。

### 实例 13：swiglu_mx_quant::ComputeDataF4Last

- **来源类型**: `__aicore__`
- **共现 API**: Cast, CastTrait, CreateMask, DataCopy, HighLowPart, Interleave, LoadDist, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegTensor, SatMode, StoreDist, UpdateMask
- **RegLayout 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: swiglu_mx_quant 末轴 FP4 量化中，定义 3 个 CastTrait 覆盖 half↔bfloat16（UNKNOWN，同位宽）与 FP32→BF16（ZERO，2:1）转换，用 RegLayout 区分是否需要指定写入位置。

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

**要点**: 1) 同位宽转换用 RegLayout::UNKNOWN，跨位宽转换用 RegLayout::ZERO；
2) DataCopy+PostLiteral::POST_MODE_UPDATE 自增加载输入；
3) 配合 Interleave/Pack/HighLowPart 完成 FP4 打包。

### 实例 14：swiglu_mx_quant::ComputeYFP16ToFP4NotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Cast, CastTrait, CreateMask, DataCopy, HighLowPart, Interleave, LoadDist, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegTensor, SatMode, StoreDist
- **RegLayout 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: swiglu_mx_quant 非末轴 FP16→FP4 量化中，用 RegLayout::ZERO 构造 FP32→BF16 与 BF16→FP4 两个 CastTrait（后者 SatMode::SAT 饱和），并通过 CAST_ZERO/CAST_ONE 宏分别取偶/奇位置转换，实现 4:1 位宽压缩。

（行 482-521）

```cpp
__aicore__ inline void ComputeYFP16ToFP4NotLastAxis(int64_t dataLen, uint16_t blockCount, __ubuf__ T* xAddr,
                                                    __ubuf__ uint16_t* mxScale2ReciprocalAddr, __ubuf__ uint8_t* y2Addr)
{
    static constexpr Reg::CastTrait castTraitFp32toBF16 = {Reg::RegLayout::ZERO, Reg::SatMode::NO_SAT,
                                                                Reg::MaskMergeMode::ZEROING, roundMode};
    static constexpr Reg::CastTrait castTraitBF16toFp4 = {Reg::RegLayout::ZERO, Reg::SatMode::SAT,
                                                               Reg::MaskMergeMode::ZEROING, roundMode};
    __VEC_SCOPE__
    {
        Reg::MaskReg dataMaskB8 = Reg::CreateMask<uint8_t>();
        Reg::MaskReg dataMaskB16 = Reg::CreateMask<half>();
        Reg::MaskReg dataMaskB32 = Reg::CreateMask<float>();
        Reg::RegTensor<T> x0, x1;
        Reg::RegTensor<float> x0ZeroFP32, x0OneFP32, x1ZeroFP32, x1OneFP32;
        Reg::RegTensor<float> reversedShareExp0ZeroFP32, reversedShareExp0OneFP32;
        Reg::RegTensor<float> reversedShareExp1ZeroFP32, reversedShareExp1OneFP32;
        Reg::RegTensor<float> dim0x0ZeroFP32, dim0x0OneFP32, dim0x1ZeroFP32, dim0x1OneFP32;
        Reg::RegTensor<bfloat16_t> dim0x0ZeroBF16, dim0x0OneBF16, dim0x1ZeroBF16, dim0x1OneBF16;
        Reg::RegTensor<uint16_t> reversedShareExp0, reversedShareExp1;
        Reg::RegTensor<U> dim0x0FP4, dim0x1FP4;
        Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
            reversedShareExp0, reversedShareExp1, mxScale2ReciprocalAddr, 256);
        Reg::Cast<float, bfloat16_t, CAST_ZERO>(reversedShareExp0ZeroFP32,
                                                     (Reg::RegTensor<bfloat16_t>&)reversedShareExp0, dataMaskB16);
        Reg::Cast<float, bfloat16_t, CAST_ONE>(reversedShareExp0OneFP32,
                                                    (Reg::RegTensor<bfloat16_t>&)reversedShareExp0, dataMaskB16);
        Reg::Cast<float, bfloat16_t, CAST_ZERO>(reversedShareExp1ZeroFP32,
                                                     (Reg::RegTensor<bfloat16_t>&)reversedShareExp1, dataMaskB16);
        Reg::Cast<float, bfloat16_t, CAST_ONE>(reversedShareExp1OneFP32,
                                                    (Reg::RegTensor<bfloat16_t>&)reversedShareExp1, dataMaskB16);
        for (uint16_t i = 0; i < blockCount; i++) {
            Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
                x0, x1, xAddr, 256);
            Reg::Cast<float, T, CAST_ZERO>(x0ZeroFP32, x0, dataMaskB16);
            Reg::Cast<float, T, CAST_ONE>(x0OneFP32, x0, dataMaskB16);
            Reg::Cast<float, T, CAST_ZERO>(x1ZeroFP32, x1, dataMaskB16);
            Reg::Cast<float, T, CAST_ONE>(x1OneFP32, x1, dataMaskB16);
            Reg::Mul(dim0x0ZeroFP32, reversedShareExp0ZeroFP32, x0ZeroFP32, dataMaskB32);
            Reg::Mul(dim0x0OneFP32, reversedShareExp0OneFP32, x0OneFP32, dataMaskB32);
            ComputeFP4FromHalf<U, roundMode>(dim0x0ZeroFP32, dataMaskB32);
```

**要点**: 1) CAST_ZERO/CAST_ONE 是 RegLayout::ZERO/ONE 的预定义 CastTrait 宏别名，用于 4:1 位宽转换的偶/奇位置拆分；
2) BF16→FP4 用 SatMode::SAT 饱和防溢出；
3) 配合 Mul+ComputeFP4FromHalf 完成缩放与量化。

### 实例 15：glu_grad::ComputeGluGradCore

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Cast, CastTrait, DataCopy, Div, DivSpecificMode, Exp, MaskMergeMode, Mul, Muls, RegTensor, SatMode, Sub
- **RegLayout 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: glu_grad 反向计算中，对 bfloat16/half↔float 的 2:1 位宽转换，用 RegLayout::ZERO（偶位置）和 RegLayout::ONE（奇位置）分别构造 Even/Odd 两套 CastTrait，实现成对数据的拆分与合并。

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

**要点**: 1) 这是 RegLayout::ONE 的典型用法——2:1 位宽转换时用 ZERO/ONE 把相邻两元素分别写到索引 0 和 1；
2) Even 用 RegLayout::ZERO、Odd 用 RegLayout::ONE，来回转换保持配对；
3) 配合 Sigmoid/Mul/Sub 完成 GLU 梯度公式。

### RegLayout 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | CastTrait{ZERO,UNKNOWN,ZEROING,UNKNOWN} 用于 BF16/FP32→FP8 量化的位宽转换写入索引0 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | CastTrait{ZERO,…}×多条 用于尾轴FP8 uint16/BF16→FP32 上采样写入索引0 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 非尾轴主路径寄存器声明，后续 CastTrait{ZERO} 用于 BF16↔FP32 转换 | __VEC_SCOPE__ |
| dynamic_block_quant | And, Cast, CastTrait, CompareScalar, CreateMask | CastTrait{ZERO,NO_SAT,…} 用于 FP8 量化输入类型转换写入索引0 | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | CastTrait 用于 half→float 上采样，RegLayout 控制写入位置 | __simd_vf__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | CastTrait{ZERO} 用于 half/bf16→float 复数绝对值计算的位宽转换 | __aicore__ |
| abs | Abs, Add, Cast, CastTrait, Compare | CastTrait{ZERO} 用于 half/bf16→float 复数取绝对值，同构 complex_abs | __aicore__ |
| dynamic_mx_quant | And, CastTrait, CreateMask, DeInterleave, Duplicate | CastTrait{ZERO,NO_SAT,ZEROING,CAST_TRUNC} 用于 FP32→BF16 下采样+非对齐回存 | __VEC_SCOPE__ |
| dynamic_mx_quant | Add, Adds, And, Cast, CastTrait | 高性能大尾块路径寄存器声明，后续 CastTrait{ZERO} 用于 bf16↔fp32 转换+Select | __VEC_SCOPE__ |
| dynamic_mx_quant | Cast, CastTrait, CreateMask, DeInterleave, Duplicate | 3 个 CastTrait{ZERO} 覆盖 BF16→FP32/FP32→BF16 双向转换，Cast 模板传参 | __VEC_SCOPE__ |
| swiglu_group_quant | And, Cast, CastTrait, Compare, Duplicate | CastTrait{UNKNOWN,…} 用于 half→bfloat16 同位宽转换（位宽比1:1） | __simd_vf__ |
| floor_div | And, Cast, CastTrait, Compare, DataCopy | 两套 CastTrait{ZERO}：T2→half(ROUND) 上采样 + half→int8(RINT) 4:1 下采样 | __aicore__ |
| swiglu_mx_quant | Cast, CastTrait, CreateMask, DataCopy, HighLowPart | 3 个 CastTrait：UNKNOWN(同位宽) + ZERO(FP32→BF16 2:1)，区分是否需写入位置 | __aicore__ |
| swiglu_mx_quant | Cast, CastTrait, CreateMask, DataCopy, HighLowPart | CastTrait{ZERO} 用于 FP32→BF16 与 BF16→FP4(SAT)，CAST_ZERO/CAST_ONE 拆偶奇 | __aicore__ |
| glu_grad | Add, Adds, Cast, CastTrait, DataCopy | CastTrait{ZERO}/CastTrait{ONE} 成对使用，2:1 位宽转换拆分偶/奇位置 | __aicore__ |
