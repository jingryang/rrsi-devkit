# MaskMergeMode

**页面ID:** atlasascendc_api_07_00240  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00240.html

---

决定mask未选择元素对于dst元素是否置0，取值如下：

- MaskMergeMode::UNKNOWN，当转换类型不支持MaskMergeMode模式时，选择该模式；
- MaskMergeMode::ZEROING，mask未选择的元素在dst中置零；
- MaskMergeMode::MERGING，mask未选择的元素对应dst元素中保留dst原值。

```
enum class MaskMergeMode {
    UNKNOWN,
    MERGING,
    ZEROING
};
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 MaskMergeMode 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **MaskMergeMode 调用次数**: 7
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 dynamic_mx_quant 非尾轴 FP8 优化路径中，用 `Reg::MaskMergeMode::ZEROING` 作为 `CastTrait` 的第 3 个成员，配置 Cast 到 FP32 时把 mask 未选中的 dst 元素置零，便于后续提取指数/尾数位。

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

**要点**: 1) `MaskMergeMode::ZEROING` 是 `CastTrait` 四元组（RegLayout/SatMode/MaskMergeMode/RoundMode）的第 3 成员；2) ZEROING 使 Cast 在 mask 之外的 dst 元素写 0，避免残留脏数据干扰指数位提取；3) 与 `RoundMode::UNKNOWN` 搭配表示该 Cast 不做显式舍入。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **MaskMergeMode 调用次数**: 5
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: grouped_dynamic_mx_quant 非尾轴 FP8 路径中，定义 `castTraitZero` 使用 `MaskMergeMode::ZEROING`，为分组场景下 Cast 到 FP32 时清零 mask 外元素。

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

**要点**: 1) 与非 grouped 版同模式，但用于 grouped（带组维度）量化；2) ZEROING 保证组间 mask 外元素不残留；3) 配合 `MaskReg`/`CreateMask` 控制有效元素范围。

### 实例 3：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, HighLowPart, Interleave, MaskAnd, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **MaskMergeMode 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 非尾轴 FP8 主路径（Ops::Base）中，用 `MaskMergeMode::ZEROING` 配置 `CastTrait`，Cast 时清零 mask 外元素以提取 FP8 指数/尾数。

（行 493-532）

```cpp
__VEC_SCOPE__
{
    if constexpr (IsSame<T, float>::value) {
        return;
    }
    Reg::RegTensor<T> x;
    Reg::RegTensor<uint16_t> absMaskBF16;
    Reg::RegTensor<uint16_t> fullZero;
    Reg::RegTensor<uint32_t> zeroRegTensor32;
    Reg::RegTensor<uint32_t> manMaskFP32;
    Reg::RegTensor<uint32_t> fp8Nan;
    Reg::RegTensor<uint32_t> bias;
    Reg::RegTensor<uint32_t> nan;

    Reg::RegTensor<uint16_t> expScaleMxYZeroRegTensor;
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

**要点**: 1) 与实例 1 同 API 不同函数（Ops::Base 主路径 vs ScalarCountLeadingZero 优化路径）；2) ZEROING 确保非参与元素为 0；3) `RoundMode::UNKNOWN` 表示不指定舍入模式。

### 实例 4：dynamic_mx_quant::Reg::StoreAlign

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Maxs, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **MaskMergeMode 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴 FP8 路径（StoreAlign 相关）中，定义 `castTrait2Float` 使用 `MaskMergeMode::ZEROING`，用于尾轴元素 Cast 到 FP32 时清零 mask 外元素。

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

**要点**: 1) 尾轴场景元素数非整 block，依赖 mask 控制有效元素；2) ZEROING 确保尾轴 mask 外 dst 写 0；3) 同时定义 `castTraitBf162Float` 等多个 CastTrait 复用同一 MaskMergeMode。

### 实例 5：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **MaskMergeMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_quant 的 ComputeVF 中，将 `Reg::MaskMergeMode::ZEROING` 作为 `DivSpecificMode` 的首成员，配置 Div 除法时 mask 外元素置零，第二成员 `true` 表示高精度模式。

（行 270-309）

```cpp
__aicore__ inline void ComputeVF(__local_mem__ xDtype* xAddr, __local_mem__ xDtype* smoothAddr,
                                 __local_mem__ yCopyDtype* yAddr, __local_mem__ float* scaleAddr,
                                 __local_mem__ float* offsetAddr, int32_t multiRow)
{
    uint32_t dtypeSize = sizeof(float);
    uint16_t VL = AscendC::VECTOR_REG_WIDTH / dtypeSize;
    uint32_t rowCount = sizeHalfLen;
    uint16_t vfLoop = (rowCount + VL - 1) / VL;

    __VEC_SCOPE__
    {
        static constexpr AscendC::Reg::DivSpecificMode mode = {AscendC::Reg::MaskMergeMode::ZEROING,
                                                                    true};
        AscendC::Reg::RegTensor<xDtype> vreg1; // 搬入的x
        AscendC::Reg::RegTensor<xDtype> vreg2; // 搬入的smooth_scales
        AscendC::Reg::RegTensor<float>
            vreg3; // cast成float之后的x，如果有smooth_scale，就是x*smooth_scales的结果
        AscendC::Reg::RegTensor<float> vreg4; // cast成float之后的smooth_scales
        AscendC::Reg::RegTensor<float> vreg6; // x的绝对值absvalue
        AscendC::Reg::RegTensor<float> vreg7; // x的abs与-inf比较的结果，可以认为是x的absvalue的一些最大值

        AscendC::Reg::RegTensor<float> vreg8; // reduceMax
        AscendC::Reg::RegTensor<float> vreg9; // scale————isSymmetric可复用
        AscendC::Reg::RegTensor<float>
            vreg10; // Duplicate之后的scale，为了和input一起得到y————isSymmetric可复用

        AscendC::Reg::RegTensor<float> vreg16; // input/scale————isSymmetric可复用，作为input/scale+offset
        AscendC::Reg::RegTensor<int16_t> vreg17;    // cast成最终y之前的int16类型
        AscendC::Reg::RegTensor<half> vreg18;       // cast成最终y之前的half类型
        AscendC::Reg::RegTensor<yCopyDtype> vreg19; // 最终y
        AscendC::Reg::RegTensor<float> vregPosInf;

        // isSymmetric == false
        AscendC::Reg::RegTensor<float> vregMinX;
        AscendC::Reg::RegTensor<float> vregReduceMaxX;
        AscendC::Reg::RegTensor<float> vregReduceMinX;
        AscendC::Reg::RegTensor<float> vregMaxSubMin;
        AscendC::Reg::RegTensor<float> vregMaxDivScale;
        AscendC::Reg::RegTensor<float> vregNegMaxDivScale;
        AscendC::Reg::RegTensor<float> vregOffset;
```

**要点**: 1) `MaskMergeMode` 不仅用于 Cast，也作为 `DivSpecificMode`/`ExpSpecificMode`/`LogSpecificMode` 等 *SpecificMode 的成员；2) ZEROING 在 Div 中使除法结果 mask 外元素为 0；3) 第二成员 `true` 控制是否高精度。

### 实例 6：complex_abs::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskPattern, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **MaskMergeMode 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: complex_abs 的 VF 计算中并行定义三个 `CastTrait`：`castTraitZero`/`castTraitOne`（均 `MaskMergeMode::ZEROING`，RoundMode::UNKNOWN）用于复数实/虚部 Cast 到 FP32，`castTrait32to16`（ZEROING + `RoundMode::CAST_RINT`）用于结果 Cast 回 half。

（行 82-121）

```cpp
__VEC_SCOPE__
{
    // 加载常量
    Reg::Duplicate(vMinNormalFloat, MIN_NORMAL_FLOAT);
    Reg::Duplicate(vExpBias, EXP_BIAS);
    Reg::Duplicate(vSCALE_UP, SCALE_UP);
    Reg::Duplicate(vSCALE_DOWN, SCALE_DOWN);
    Reg::Duplicate(vZero, 0);

    static constexpr AscendC::Reg::CastTrait castTraitZero = {
        AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::UNKNOWN,
        AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
    static constexpr AscendC::Reg::CastTrait castTraitOne = {
        AscendC::Reg::RegLayout::ONE, AscendC::Reg::SatMode::UNKNOWN,
        AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
    static constexpr AscendC::Reg::CastTrait castTrait32to16 = {
        AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::SAT,
        AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::CAST_RINT};

    for (uint16_t i = 0; i < repeatTime; i++) {
        preg = Reg::UpdateMask<float, Reg::RegTraitNumOne>(sreg);
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
```

**要点**: 1) 同一 VF 内可定义多个 CastTrait，MaskMergeMode 统一用 ZEROING 但 RoundMode 按需不同（UNKNOWN vs CAST_RINT）；2) ZEROING 保证中间 Cast 的非有效元素为 0，避免累加误差；3) `castTraitOne` 用 RegLayout::ONE 取虚部，配合 ZEROING 清零其余。

### 实例 7：dynamic_mx_quant::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, ShiftRights, StoreUnAlign, StoreUnAlignPost, UnalignReg
- **MaskMergeMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴（StoreUnAlignPost）路径中，定义 `castTraitFp32toBF16` 使用 `MaskMergeMode::ZEROING` + `RoundMode::CAST_TRUNC` + `SatMode::NO_SAT`，把 FP32 中间结果 Cast 回 BF16 时清零 mask 外元素并截断舍入。

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

**要点**: 1) ZEROING 与 `RoundMode::CAST_TRUNC`（截断）搭配用于反向量化降精度；2) `SatMode::NO_SAT` 表示不饱和；3) 尾轴用 `StoreUnAlignPost` 非对齐写回，依赖 mask 处理边界。

### 实例 8：dynamic_mx_quant::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, UnalignReg
- **MaskMergeMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴另一函数中，定义 `castTraitHalf2Bf16` 用 `MaskMergeMode::ZEROING` + `RoundMode::CAST_RINT`，把 half Cast 到 BF16 时清零 mask 外元素并就近舍入。

（行 561-600）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<T> xExp0;
    Reg::RegTensor<T> xExp1;
    Reg::RegTensor<uint16_t> xMaxExp;
    Reg::RegTensor<bfloat16_t> xExp0BF16;
    Reg::RegTensor<bfloat16_t> xExp1BF16;
    Reg::RegTensor<uint16_t> xExpSelect0;
    Reg::RegTensor<uint16_t> xExpSelect1;
    Reg::RegTensor<uint16_t> xExpExtract0;
    Reg::RegTensor<uint16_t> xExpExtract1;

    Reg::RegTensor<uint16_t> expMaskBF16;
    Reg::Duplicate(expMaskBF16, BF16_MAX_EXP);
    Reg::RegTensor<uint16_t> invalidMaskFP16;
    Reg::Duplicate(invalidMaskFP16, FP16_INVALID);
    Reg::RegTensor<uint16_t> absMask16Bit;
    Reg::Duplicate(absMask16Bit, BF16_ABS_MASK);

    Reg::MaskReg Mask = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg invalidDataMask0;
    Reg::MaskReg invalidDataMask1;
    Reg::UnalignReg ureg;

    static constexpr Reg::CastTrait castTraitHalf2Bf16 = {Reg::RegLayout::UNKNOWN, Reg::SatMode::UNKNOWN,
                                                          Reg::MaskMergeMode::ZEROING, RoundMode::CAST_RINT};

    for (uint16_t i = 0; i < loopNum2VF; i++) {
        Reg::LoadAlign<T, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
            xExp0, xExp1, xLocalAddr, VF_LEN_16_DOUBLE);
        Reg::And(xExpSelect0, (Reg::RegTensor<uint16_t>&)xExp0, invalidMaskFP16, Mask);
        Reg::And(xExpSelect1, (Reg::RegTensor<uint16_t>&)xExp1, invalidMaskFP16, Mask);
        Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask0, xExpSelect0, invalidMaskFP16, Mask);
        Reg::Compare<uint16_t, CMPMODE::NE>(invalidDataMask1, xExpSelect1, invalidMaskFP16, Mask);
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xExp0BF16, xExp0, Mask);
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xExp1BF16, xExp1, Mask);
        Reg::And(xExpExtract0, (Reg::RegTensor<uint16_t>&)xExp0BF16, absMask16Bit, Mask);
        Reg::And(xExpExtract1, (Reg::RegTensor<uint16_t>&)xExp1BF16, absMask16Bit, Mask);
        Reg::Select<uint16_t>(xExpExtract0, xExpExtract0, expMaskBF16, invalidDataMask0);
        Reg::Select<uint16_t>(xExpExtract1, xExpExtract1, expMaskBF16, invalidDataMask1);
```

**要点**: 1) 与实例 7 同算子同文件不同函数，RoundMode 不同（CAST_RINT vs CAST_TRUNC）；2) RegLayout::UNKNOWN 表示不指定布局；3) ZEROING 保证 mask 外元素为 0。

### 实例 9：dynamic_mx_quant::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, Interleave, LoadAlign, LoadDist, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, StoreAlign, StoreDist
- **MaskMergeMode 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 尾轴主计算中定义三个 `CastTrait`，均 `MaskMergeMode::ZEROING`，但 RoundMode 取自外部变量 `roundMode`/`toBf16RoundMode`，实现 BF16↔FP32 双向 Cast 的可配置舍入。

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

**要点**: 1) RoundMode 可由模板参数/变量传入，MaskMergeMode 固定 ZEROING；2) 升精度（BF16→FP32）用 UNKNOWN，降精度（FP32→BF16）用可配置舍入；3) ZEROING 确保所有 Cast 的 mask 外元素统一清零。

### 实例 10：cdist::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, CreateMask, Duplicate, Exp, ExpSpecificMode, LoadAlign, Log, LogSpecificMode, MaskPattern, MaskReg, Muls, ReduceSum, RegTensor, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore, UpdateMask
- **MaskMergeMode 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: cdist 距离计算中，把 `MaskMergeMode::ZEROING` 作为 `ExpSpecificMode`/`LogSpecificMode` 的首成员，配置 Exp/Log 运算时 mask 外元素置零，第二成员指定 1ULP 精度算法。

（行 596-635）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<float> x1Reg;
    Reg::RegTensor<float> x2Reg;
    Reg::RegTensor<float> subReg;
    Reg::RegTensor<float> absReg;
    Reg::RegTensor<float> logReg;
    Reg::RegTensor<float> mulReg;
    Reg::RegTensor<float> expReg;
    Reg::RegTensor<float> sumReg;
    Reg::RegTensor<float> resultReg;
    Reg::RegTensor<float> dstReg;
    Reg::MaskReg maskAll = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
    Reg::MaskReg maskTail;
    Reg::MaskReg maskOne;
    Reg::UnalignRegForStore uReg;
    maskTail = Reg::UpdateMask<float>(maksTailNum);
    maskOne = Reg::UpdateMask<float>(maskOneNum);
    Reg::Duplicate(dstReg, (float)0);
    static constexpr Reg::ExpSpecificMode modeexp = {Reg::MaskMergeMode::ZEROING,ExpAlgo::PRECISION_1ULP_FTZ_FALSE};
    static constexpr Reg::LogSpecificMode modelog = {Reg::MaskMergeMode::ZEROING,LogAlgo::PRECISION_1ULP_FTZ_FALSE};
    for (uint16_t m = 0; m < loopNumM; m++) {
        __local_mem__ float * x1Offset = srcPtrX1 + b * pSize_ * MAlign_ + p * MAlign_ + vlLen_ * m;
        __local_mem__ float * x2Offset = srcPtrX2 + b * rSize_ * MAlign_ + r * MAlign_ + vlLen_ * m;
        Reg::LoadAlign(x1Reg, x1Offset);
        Reg::LoadAlign(x2Reg, x2Offset);
        Reg::Sub(subReg, x1Reg, x2Reg, maskAll);
        Reg::Abs(absReg, subReg, maskAll);
        Reg::Log<float, &modelog>(logReg, absReg, maskAll);
        Reg::Muls(mulReg, logReg, (float)p_, maskAll);
        Reg::Exp<float, &modeexp>(expReg, mulReg, maskAll);
        Reg::ReduceSum(sumReg, expReg, maskAll);
        Reg::Add(dstReg, dstReg, sumReg, maskOne);
    }
    __local_mem__ float * x1Offset = srcPtrX1 + b * pSize_ * MAlign_ + p * MAlign_ + vlLen_ * loopNumM;
    __local_mem__ float * x2Offset = srcPtrX2 + b * rSize_ * MAlign_ + r * MAlign_ + vlLen_ * loopNumM;
    Reg::LoadAlign(x1Reg, x1Offset);
    Reg::LoadAlign(x2Reg, x2Offset);
    Reg::Sub(subReg, x1Reg, x2Reg, maskTail);
    Reg::Abs(absReg, subReg, maskTail);
```

**要点**: 1) `MaskMergeMode` 是 `ExpSpecificMode`/`LogSpecificMode` 等 *SpecificMode 结构的首成员；2) ZEROING 使 Exp/Log 的 mask 外结果为 0；3) 通过 `Log<...,&modelog>`/`Exp<...,&modeexp>` 以模板引用传入模式。

### 实例 11：swiglu_group_quant::VFComputeMaxExpMXFP4Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, Duplicate, LoadAlign, LoadDist, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **MaskMergeMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: swiglu_group_quant（激活+量化）的 VF 中，定义 `castTraitHalf2Bf16` 用 `MaskMergeMode::ZEROING` + `RoundMode::CAST_TRUNC`，half→BF16 Cast 时清零 mask 外元素并截断。

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

**要点**: 1) `__simd_vf__` 上下文中 `AscendC::Reg::` 命名空间下使用 MaskMergeMode；2) ZEROING + CAST_TRUNC 用于 FP4 量化前提取指数；3) 与 `Select`/`Compare` 配合处理非法数据掩码。

### 实例 12：dynamic_mx_quant::Reg::Select

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, Duplicate, HighLowPart, MaskPattern, MaskReg, Max, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, StoreDist, Sub
- **MaskMergeMode 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant 高性能大尾轴优化路径中，定义 `castTraitOcpHalf2Bf16` 用 `MaskMergeMode::ZEROING` + `RoundMode::CAST_TRUNC`，half→BF16 Cast 时清零 mask 外元素。

（行 654-693）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<uint32_t> x0U32;
    Reg::RegTensor<uint32_t> x1U32;
    Reg::RegTensor<uint32_t> exp0U32;
    Reg::RegTensor<uint32_t> exp1U32;
    Reg::RegTensor<uint32_t> expMaxU32;
    Reg::RegTensor<uint16_t> x0U16;
    Reg::RegTensor<uint16_t> x1U16;
    Reg::RegTensor<uint16_t> exp0U16;
    Reg::RegTensor<uint16_t> exp1U16;
    Reg::RegTensor<uint16_t> expMaxU16;
    Reg::RegTensor<uint16_t> mxScaleBF16;
    Reg::RegTensor<uint16_t> reversedShareExpBF16;
    Reg::RegTensor<uint8_t> mxScale;
    Reg::RegTensor<uint16_t> absU16; // x绝对值
    Reg::RegTensor<uint16_t> maxU16; // 绝对值最大值

    Reg::RegTensor<uint16_t> specialExpU16;
    Reg::RegTensor<uint16_t> biasU16;
    Reg::RegTensor<uint16_t> zeroU16;
    Reg::RegTensor<uint16_t> nanU16;
    Reg::RegTensor<uint16_t> maxEleU16;
    Reg::RegTensor<uint32_t> maxEleU32;
    Reg::RegTensor<uint16_t> maxEleFP16;
    Reg::RegTensor<uint16_t> dtypeYMaxExp;
    Reg::RegTensor<uint16_t> subNumForScale;
    Reg::RegTensor<uint16_t> fp8NanU16;
    Reg::RegTensor<uint16_t> absForXU16;

    Reg::MaskReg infMask;
    Reg::MaskReg zeroMask;
    Reg::MaskReg invalidDataMask;
    Reg::MaskReg pregAll8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregAll16 = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregAll32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();

    static constexpr Reg::CastTrait castTraitOcpHalf2Bf16 = {Reg::RegLayout::UNKNOWN, Reg::SatMode::UNKNOWN,
                                                             Reg::MaskMergeMode::ZEROING,
                                                             AscendC::RoundMode::CAST_TRUNC};
```

**要点**: 1) 高性能大尾轴变体复用 ZEROING+CAST_TRUNC 模式；2) Ocp 命名暗示面向特定精度配置；3) ZEROING 保证大尾轴 mask 外元素清零。

### 实例 13：pool_3d_common::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Arange, Cast, Copy, CreateMask, DataCopyGather, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, MaskPattern, MaskReg, Muls, Pack, ReduceSum, RegTensor, UnPack, UnalignReg, UpdateMask
- **MaskMergeMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: pool_3d_common 池化累加中，用 `Reg::Copy<float, Reg::MaskMergeMode::MERGING>(res, tmp, tailMaskFp32)` 拷回尾轴部分和时，对 mask 未选中元素保留 `res` 原值（MERGING），避免覆盖主轴已累加的结果。

（行 725-764）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<float> res;
    Reg::RegTensor<T> in;
    Reg::RegTensor<float> inFp32;
    Reg::RegTensor<uint16_t> v0;
    AscendC::Reg::UnalignReg u0;
    Reg::Arange((Reg::RegTensor<int16_t>&)v0, 0);
    uint32_t tailSreg = tailLoop;
    uint32_t mainSreg = repeatElm;
    uint32_t tailLen = tailLoop;
    uint32_t mainLen = repeatElm;
    Reg::MaskReg pTail = Reg::UpdateMask<T>(tailSreg);
    Reg::MaskReg pMain = Reg::UpdateMask<T>(mainSreg);
    Reg::MaskReg maskFp32 = Reg::UpdateMask<float>(mainLen);
    Reg::MaskReg tailMaskFp32 = Reg::UpdateMask<float>(tailLen);
    Reg::Muls(v0, v0, channelNum, pMain);
    for (uint16_t i = 0; i < loopNum; i++) {
        auto srcAddr = xLocalAddr + i;
        auto dstAddr = dstLocalAddr + i;
        auto sumAddr = sumLocalAddr + i;
        Reg::Duplicate(res, 0);
        for (uint16_t j = 0; j < repeatTimes; j++) {
            Reg::DataCopyGather(in, srcAddr + j * channelStride, v0, pMain);
            Reg::UnPack((Reg::RegTensor<uint32_t>&)in, (Reg::RegTensor<uint16_t>&)in);
            Reg::Cast<float, T, castTraitT2Fp32>(inFp32, in, maskFp32);
            Reg::Add(res, inFp32, res, maskFp32);
        }
        Reg::RegTensor<float> tmp;
        Reg::DataCopyGather(in, srcAddr + repeatTimes * channelStride, v0, pTail);
        Reg::UnPack((Reg::RegTensor<uint32_t>&)in, (Reg::RegTensor<uint16_t>&)in);
        Reg::Cast<float, T, castTraitT2Fp32>(inFp32, in, tailMaskFp32);
        Reg::Add(tmp, inFp32, res, tailMaskFp32);
        Reg::Copy<float, Reg::MaskMergeMode::MERGING>(res, tmp, tailMaskFp32);
        Reg::MaskReg maskAll = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
        Reg::ReduceSum(res, res, maskAll);
        if constexpr (MERGE) {
            // merge cur result with last result
            MergeMaxRes<float, OP_TYPE>(res, sumAddr, 0);
        }
```

**要点**: 1) `MaskMergeMode::MERGING` 作为 `Copy` 的模板参数，使 mask 外 dst 元素保留原值；2) 与 ZEROING 不同：MERGING 不清零，适合部分更新/累加场景；3) 尾轴用 tailMaskFp32 控制有效元素，MERGING 保护主轴已算结果。

### 实例 14：avg_pool::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Arange, Cast, Copy, CreateMask, DataCopyGather, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, MaskPattern, MaskReg, Muls, Pack, ReduceSum, RegTensor, UnPack, UnalignReg, UpdateMask
- **MaskMergeMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: avg_pool 均值池化累加中，用 `Copy<float, MaskMergeMode::MERGING>(res, tmp, tailMaskFp32)` 拷回尾轴部分和时，mask 外元素保留 `res` 原值，保护主轴累加结果。

（行 604-643）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<float> res;
    Reg::RegTensor<T> in;
    Reg::RegTensor<float> inFp32;
    Reg::RegTensor<uint16_t> v0;
    AscendC::Reg::UnalignReg u0;
    Reg::Arange((Reg::RegTensor<int16_t>&)v0, 0);
    uint32_t tailSreg = tailLoop;
    uint32_t mainSreg = repeatElm;
    uint32_t tailLen = tailLoop;
    uint32_t mainLen = repeatElm;
    Reg::MaskReg pTail = Reg::UpdateMask<T>(tailSreg);
    Reg::MaskReg pMain = Reg::UpdateMask<T>(mainSreg);
    Reg::MaskReg maskFp32 = Reg::UpdateMask<float>(mainLen);
    Reg::MaskReg tailMaskFp32 = Reg::UpdateMask<float>(tailLen);
    Reg::Muls(v0, v0, channelNum, pMain);
    for (uint16_t i = 0; i < loopNum; i++) {
        auto srcAddr = xLocalAddr + i;
        auto dstAddr = dstLocalAddr + i;
        auto sumAddr = sumLocalAddr + i;
        Reg::Duplicate(res, 0);
        for (uint16_t j = 0; j < repeatTimes; j++) {
            Reg::DataCopyGather(in, srcAddr + j * channelStride, v0, pMain);
            Reg::UnPack((Reg::RegTensor<uint32_t>&)in, (Reg::RegTensor<uint16_t>&)in);
            Reg::Cast<float, T, castTraitT2Fp32>(inFp32, in, maskFp32);
            Reg::Add(res, inFp32, res, maskFp32);
        }
        Reg::RegTensor<float> tmp;
        Reg::DataCopyGather(in, srcAddr + repeatTimes * channelStride, v0, pTail);
        Reg::UnPack((Reg::RegTensor<uint32_t>&)in, (Reg::RegTensor<uint16_t>&)in);
        Reg::Cast<float, T, castTraitT2Fp32>(inFp32, in, tailMaskFp32);
        Reg::Add(tmp, inFp32, res, tailMaskFp32);
        Reg::Copy<float, Reg::MaskMergeMode::MERGING>(res, tmp, tailMaskFp32);
        Reg::MaskReg maskAll = Reg::CreateMask<float, Reg::MaskPattern::ALL>();
        Reg::ReduceSum(res, res, maskAll);
        if constexpr (MERGE) {
            // merge cur result with last result
            MergeSumRes<float>(res, sumAddr, 0);
        }
```

**要点**: 1) 与实例 13 同模式（MERGING 作为 Copy 模板参数），用于不同池化算子；2) MERGING 适合尾轴部分更新+主轴全量的累加结构；3) avg_pool 后续用 MergeSumRes 合并。

### 实例 15：sinh::SinhCustomVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, CompareScalar, DataCopy, Div, DivSpecificMode, Duplicate, Exp, MaskReg, Mul, Neg, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **MaskMergeMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: sinh 算子的 VF 实现中，将 `Reg::MaskMergeMode::ZEROING` 作为 `DivSpecificMode` 的首成员，配置 Taylor 展开中的 Div 使 mask 外元素置零，`true` 表示高精度。

（行 47-86）

```cpp
    __aicore__ inline SinhCustomVF(LocalTensor<T>& dst, LocalTensor<T>& src, uint32_t count)
    {
#ifdef __CCE_AICORE__
        // Taylor coefficients (matching PTX hex constants)
        constexpr T c2 = T(0.16666667f);         // 0x3E2AAAAB, 1/6
        constexpr T c3 = T(0.008333347f);         // 0x3C08889A, 1/120
        constexpr T c4 = T(0.00019841270f);       // 0x394FFF49, 1/5040
        constexpr T c5 = T(0.0000027557319f);     // 0x363D0ADA, 1/362880

        constexpr T one_val = T(1.0f);
        constexpr T ninety_val = T(90.0f);
        constexpr T zero_val = T(0.0f);
        constexpr T quarter_val = T(0.25f);
        constexpr T neg_ln2 = T(-0.6931471805599453f);
        const T inf_val = T(__builtin_huge_valf());  // +infinity

        uint32_t VL = AscendC::VECTOR_REG_WIDTH / sizeof(T);
        uint16_t loopNum = CeilDivision(count, VL);

        static constexpr AscendC::Reg::DivSpecificMode divMode = {
            AscendC::Reg::MaskMergeMode::ZEROING, true  // high precision
        };

        __VEC_SCOPE__
        {
            __ubuf__ T* srcAddr = (__ubuf__ T*)src.GetPhyAddr();
            __ubuf__ T* dstAddr = (__ubuf__ T*)dst.GetPhyAddr();

            AscendC::Reg::RegTensor<T, AscendC::Reg::RegTraitNumOne> reg_x;
            AscendC::Reg::RegTensor<T, AscendC::Reg::RegTraitNumOne> reg_abs;
            AscendC::Reg::RegTensor<T, AscendC::Reg::RegTraitNumOne> reg_x2;
            AscendC::Reg::RegTensor<T, AscendC::Reg::RegTraitNumOne> reg_poly;
            AscendC::Reg::RegTensor<T, AscendC::Reg::RegTraitNumOne> reg_temp;
            AscendC::Reg::RegTensor<T, AscendC::Reg::RegTraitNumOne> reg_exp;
            AscendC::Reg::RegTensor<T, AscendC::Reg::RegTraitNumOne> reg_result;
            AscendC::Reg::MaskReg mask;
            AscendC::Reg::MaskReg cmpMask0;
            AscendC::Reg::MaskReg cmpMask1;

            for (uint16_t i = 0; i < loopNum; i++) {
```

**要点**: 1) 数学算子（sinh）用 `DivSpecificMode` + ZEROING 控制除法 mask 行为；2) 与实例 5（dynamic_quant）同模式，证明 ZEROING 是 DivSpecificMode 的通用默认；3) `true` 第二成员开启 high precision。

### MaskMergeMode 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | CastTrait 第3成员=ZEROING，Cast 时 mask 外 dst 置零 | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | CastTrait 第3成员=ZEROING（grouped 变体） | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | CastTrait 第3成员=ZEROING（非尾轴主路径） | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | CastTrait 第3成员=ZEROING（尾轴 StoreAlign） | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | DivSpecificMode 首成员=ZEROING + 高精度 | __aicore__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | 多 CastTrait 均 ZEROING，RoundMode 按需（UNKNOWN/CAST_RINT） | __VEC_SCOPE__ |
| dynamic_mx_quant | And, CastTrait, CreateMask, DeInterleave, Duplicate | CastTrait ZEROING + CAST_TRUNC + NO_SAT（FP32→BF16） | __VEC_SCOPE__ |
| dynamic_mx_quant | And, Cast, CastTrait, Compare, CreateMask | CastTrait ZEROING + CAST_RINT（half→BF16） | __VEC_SCOPE__ |
| dynamic_mx_quant | Cast, CastTrait, CreateMask, DeInterleave, Duplicate | 多 CastTrait ZEROING，RoundMode 由变量传入 | __VEC_SCOPE__ |
| cdist | Abs, Add, CreateMask, Duplicate, Exp | ExpSpecificMode/LogSpecificMode 首成员=ZEROING | __VEC_SCOPE__ |
| swiglu_group_quant | And, Cast, CastTrait, Compare, Duplicate | CastTrait ZEROING + CAST_TRUNC（simd_vf 激活量化） | __simd_vf__ |
| dynamic_mx_quant | And, Cast, CastTrait, Compare, CreateMask | CastTrait ZEROING + CAST_TRUNC（高性能大尾轴） | __VEC_SCOPE__ |
| pool_3d_common | Add, Arange, Cast, Copy, CreateMask | Copy 模板参数=MERGING，mask 外保留 dst 原值 | __VEC_SCOPE__ |
| avg_pool | Add, Arange, Cast, Copy, CreateMask | Copy 模板参数=MERGING（avg_pool 累加） | __VEC_SCOPE__ |
| sinh | Abs, Add, Adds, CompareScalar, DataCopy | DivSpecificMode 首成员=ZEROING + 高精度（数学算子） | __aicore__ |
