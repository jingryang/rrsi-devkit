# SatMode

**页面ID:** atlasascendc_api_07_00239  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00239.html

---

设置Cast类型转换饱和与不饱和模式，取值如下：

- SatMode::UNKNOWN，当转换类型不支持SatMode模式时，选择该模式；
- SatMode::NO_SAT，不饱和模式；
- SatMode::SAT，饱和模式。

```
enum class SatMode {
    UNKNOWN = -1,
    NO_SAT,
    SAT
};
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 SatMode 实例

### 实例 1：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **SatMode 调用次数**: 5
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在分组动态 MX 量化算子的 VF 计算中，定义 castTraitZero 时将 SatMode 设为 UNKNOWN，表示该类型转换不适用饱和模式（多为宽位到中间态的拆包转换）。

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

**要点**: (1) SatMode::UNKNOWN 用于转换类型本身不支持饱和语义的场景；(2) CastTrait 四元组顺序固定为 RegLayout、SatMode、MaskMergeMode、RoundMode；(3) 与 RegLayout::ZERO、MaskMergeMode::ZEROING 组合，掩码外通道清零。


### 实例 2：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Max, Min, PostLiteral, ReduceMax, RegLayout, RegTensor, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **SatMode 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在动态分块量化算子中，定义 castTraitZero 时使用 SatMode::NO_SAT，表示类型转换不进行饱和钳位，溢出数据不被截断到目标类型范围。

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

**要点**: (1) SatMode::NO_SAT 表示不饱和，转换溢出时不钳位到目标类型上下限；(2) 适用于中间计算不需要饱和钳位的场景；(3) 与 RegLayout::ZERO 组合，未激活通道置零。


### 实例 3：incre_flash_attention::SoftmaxFlashV2_base512_update

- **来源类型**: `__aicore__`
- **共现 API**: Add, Cast, CastTrait, CreateMask, DataCopy, DataCopyMode, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, FusedExpSub, LocalMemBar, MaskMergeMode, MaskReg, Max, MemType, Muls, Or, ReduceMax, ReduceSum, RegLayout, RegTensor, Select, UnalignReg, UpdateMask
- **SatMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在增量 Flash Attention 的 Softmax 更新中，通过 CastTrait 携带 SatMode 控制 FP32 与低精度类型间的转换饱和策略，服务于 max/exp/sum 归约的数值稳定计算。

（行 575-614）

```cpp
__aicore__ inline void SoftmaxFlashV2_base512_update(
    const LocalTensor<T1>& dstTensor, const LocalTensor<T>& expSumTensor, const LocalTensor<T>& maxTensor,
    const LocalTensor<T>& srcTensor, const LocalTensor<T>& expMaxTensor, const LocalTensor<T>& inExpSumTensor,
    const LocalTensor<T>& inMaxTensor, const LocalTensor<uint8_t>& sharedTmpBuffer, const T scale,
    const uint32_t maskSizeAlignPFA, const LocalTensor<uint8_t>& maskTensor, const LocalTensor<PSE_SHIFT_T>& pseTensor,
    const uint32_t& profileG, const SoftMaxShapeInfo& softmaxShapeInfo = {})
{
    const uint32_t originN = softmaxShapeInfo.oriSrcK;  // N轴实际数据长度，为SInnerLoop切块的 S/act_seq_len
    const uint32_t fixSrcN = 512;
    const uint32_t floatRepSize = 64;         // 寄存器一次可以加载64个元素（fp32类型，对应256B）
    const uint32_t reduceN = 32 / sizeof(T);  // m每行的结果存为8个重复元素（32B对齐）
    const uint16_t rows = static_cast<uint16_t>(softmaxShapeInfo.srcM);  // 总行数
    const uint32_t fixSrcG = profileG;

    __VEC_SCOPE__
    {
        __ubuf__ float* expSumUb = (__ubuf__ T*)expSumTensor.GetPhyAddr();
        __ubuf__ float* maxUb = (__ubuf__ T*)maxTensor.GetPhyAddr();
        __ubuf__ float* srcUb = (__ubuf__ T*)srcTensor.GetPhyAddr();
        __ubuf__ float* expMaxUb = (__ubuf__ T*)expMaxTensor.GetPhyAddr();
        __ubuf__ float* inExpSumUb = (__ubuf__ T*)inExpSumTensor.GetPhyAddr();
        __ubuf__ float* inMaxUb = (__ubuf__ T*)inMaxTensor.GetPhyAddr();
        __ubuf__ float* tmpExpSumUb = (__ubuf__ T*)sharedTmpBuffer.GetPhyAddr();
        __ubuf__ float* tmpMaxUb = tmpExpSumUb + 16; // 16 x sum + 16 x max
        __ubuf__ float* tmpExpSumUb2 = tmpExpSumUb;
        __ubuf__ float* tmpMaxUb2 = tmpMaxUb;
        __ubuf__ uint8_t* maskUb = (__ubuf__ uint8_t*)maskTensor.GetPhyAddr();
        __ubuf__ uint8_t* maskBandUb;
        if constexpr (isBand) {
            maskBandUb = (__ubuf__ uint8_t*)maskTensor[rows * maskSizeAlignPFA].GetPhyAddr();
        }
        __ubuf__ PSE_SHIFT_T* pseUb = (__ubuf__ PSE_SHIFT_T*)pseTensor.GetPhyAddr();

        __ubuf__ T1* expUb = (__ubuf__ T1*)dstTensor.GetPhyAddr();
        __ubuf__ T1* expUb1 = expUb + (fixSrcG + 1) * 128;     // 第二大块NZ的偏移是(profileG + 1) * 128
        __ubuf__ T1* expUb2 = expUb + 2 * (fixSrcG + 1) * 128; // 第三大块NZ的偏移是2 * (profileG + 1) * 128
        __ubuf__ T1* expUb3 = expUb + 3 * (fixSrcG + 1) * 128; // 第四大块NZ的偏移是3 * (profileG + 1) * 128

        uint16_t blockStride = fixSrcG + 1;  // 加1是为了解写写ub bank冲突
        uint16_t repeatStride = 1;      //  每次nd2nz写完之后ub往后偏移1个block
```

**要点**: (1) Softmax 涉多次 max/exp/sum 归约，类型转换频繁，SatMode 决定中间结果是否饱和；(2) SatMode 出现在 __aicore__ 作用域内的 __VEC_SCOPE__ 子块中；(3) 与 DataCopy、ReduceMax、ReduceSum 协同完成 softmax 数值稳定。


### 实例 4：mla_prolog::ComputeVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: Abs, Cast, CastTrait, CreateMask, Div, DivSpecificMode, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Muls, PostLiteral, Reduce, ReduceType, RegLayout, RegTensor, StoreAlign, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **SatMode 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 MLA Prolog 动态量化算子中，针对不同转换方向定义 4 个 CastTrait，完整展示 SatMode 三种取值：b16→f32 宽位用 UNKNOWN、f32→int8/hif8 窄位用 SAT 饱和钳位、f32→half 用 NO_SAT。

（行 44-83）

```cpp
__simd_vf__ void ComputeVFImpl(__ubuf__ T *xAddr, __ubuf__ O *yAddr, __ubuf__ float *scaleAddr, uint32_t rowIndex,
                               uint32_t rowCount, uint32_t dtypeSize, uint16_t VL, uint16_t vfLoop,
                               const float alphaValue)
{
    constexpr static AscendC::Reg::CastTrait castTraitB16ToF32 = {
        AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::UNKNOWN,
        AscendC::Reg::MaskMergeMode::ZEROING, AscendC::RoundMode::UNKNOWN};
    constexpr static AscendC::Reg::CastTrait castTraitPack2 = {
        AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::SAT, AscendC::Reg::MaskMergeMode::ZEROING,
        RoundMode::CAST_RINT};
    constexpr static AscendC::Reg::CastTrait castTraitF32ToHalf = {
        AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::NO_SAT,
        AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::CAST_ODD};
    constexpr static AscendC::Reg::CastTrait castTraitF32ToHif8 = {
        AscendC::Reg::RegLayout::ZERO, AscendC::Reg::SatMode::SAT, AscendC::Reg::MaskMergeMode::ZEROING,
        RoundMode::CAST_ROUND};
    static constexpr AscendC::Reg::DivSpecificMode mode = {AscendC::Reg::MaskMergeMode::ZEROING, true};
    AscendC::Reg::RegTensor<T> xInput;         // 搬入的x
    AscendC::Reg::RegTensor<float> xFp32;      // cast成float之后的x
    AscendC::Reg::RegTensor<float> xFp32Abs;   // x的绝对值absvalue
    AscendC::Reg::RegTensor<float> xMaxAbs;    // x的abs与-inf比较的结果，可以认为是x的absvalue的一些最大值
    AscendC::Reg::RegTensor<float> xReduceMax; // reduceMax
    AscendC::Reg::RegTensor<float> xScale;     // scale
    AscendC::Reg::RegTensor<float> xScaleDup;  // Duplicate之后的scale，为了和input一起得到y
    AscendC::Reg::RegTensor<float> xNorm;      // input/scale
    AscendC::Reg::RegTensor<half> yHalf;       // float-->half-->int8
    AscendC::Reg::RegTensor<O> yOutput;        // 最终y

    AscendC::Reg::MaskReg validMask0; // 有效掩码
    AscendC::Reg::MaskReg fullMask1 =
        AscendC::Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>(); // 启用所有通道，全掩码
    AscendC::Reg::MaskReg validMask2;

    AscendC::Reg::UnalignRegForStore ureg0;
    AscendC::Reg::Duplicate(xMaxAbs, NEG_INFINITY, fullMask1);
    uint32_t sreg0 = rowCount;

    // 计算量化参数
    for (uint16_t j = 0; j < vfLoop; j++) {
        validMask0 = AscendC::Reg::UpdateMask<float>(sreg0); // 有效元素
```

**要点**: (1) 同一函数按转换方向差异化选择 SatMode：宽变窄无饱和语义用 UNKNOWN、窄化需钳位用 SAT、不希望钳位用 NO_SAT；(2) SAT 模式将溢出值钳位到目标类型范围，避免窄化时数据越界；(3) CastTrait 作为模板参数传入 Reg::Cast<dst, src, castTrait>(...) 调用。


### 实例 5：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **SatMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 flat_quant 的 BLAS 缩放 VF 函数中，定义 castTraitHalf2Float 等 CastTrait 控制 half→float 宽位转换的饱和模式，服务于 MX/FP4 量化的指数缩放计算。

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

**要点**: (1) half→float 为宽位转换，通常 SatMode 设为 UNKNOWN（无需饱和）；(2) CastTrait 与 MaskReg、Duplicate 配合，先做位运算提取指数/尾数再转换；(3) SatMode 选择影响最终量化数值精度。


### 实例 6：abs::AbscomplexCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **SatMode 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在复数绝对值算子中，通过 CastTrait 携带 SatMode 控制 float 与输入窄类型间的双向转换，窄化回写时使用 SAT 饱和钳位。

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

**要点**: (1) 复数模长 sqrt(a²+b²) 用 float 中间精度，回写窄类型需 SatMode::SAT 饱和钳位；(2) 使用 RegTraitNumOne 单元素寄存器变体处理标量级运算；(3) 与 Sqrt、Mul、Add 组合实现模长计算。


### 实例 7：complex_abs::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, Mul, RegLayout, RegTensor, RegTraitNumOne, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **SatMode 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在复数绝对值算子的 VEC_SCOPE 中，按转换方向定义 3 个 CastTrait：T→float 宽位用 SatMode::UNKNOWN（RegLayout::ZERO/ONE 分别取实虚部），float→T 窄位回写用 SatMode::SAT 配合 CAST_RINT 舍入。

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

**要点**: (1) 宽位转换（T→float）用 SatMode::UNKNOWN，无需饱和；(2) 窄位回写（float→T）用 SatMode::SAT + CAST_RINT，饱和并就近偶数舍入；(3) RegLayout::ZERO/ONE 配合 LoadAlign 解交织分别取复数实部与虚部。


### 实例 8：compressor::RmsNormVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: Add, Adds, CastTrait, CreateMask, Div, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, Muls, Reduce, ReduceType, RegLayout, RegTensor, Sqrt, StoreAlign, StoreDist
- **SatMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 compressor 算子的 RMSNorm VF 实现中，定义 castTraitB162B32 将 SatMode 设为 UNKNOWN，用于 bfloat16→float 宽位转换（无需饱和）。

（行 22-61）

```cpp
__simd_vf__ void RmsNormVFImpl(__ubuf__ T * inputBuf, __ubuf__ GammaType * gammaBuf, __ubuf__ T * outputBuf, 
                               uint32_t repeatTimes, float reciprocal, float epsilon)
{
    Reg::RegTensor<T> vregSum;
    Reg::RegTensor<T> vregSumReduce;
    Reg::RegTensor<T> vregDiv;
    Reg::RegTensor<T> vregSquareRoot;

    Reg::MaskReg maskAll = Reg::CreateMask<T, Reg::MaskPattern::ALL>();
    Reg::MaskReg maskFirst = Reg::CreateMask<T, Reg::MaskPattern::VL1>();

    static constexpr Reg::CastTrait castTraitB162B32 = {Reg::RegLayout::ZERO,
        Reg::SatMode::UNKNOWN, Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};

    Reg::Duplicate<T,T>(vregSum, 0.0f);

    for(uint32_t i = 0; i < repeatTimes; ++i){
        Reg::RegTensor<T> vregX;
        Reg::RegTensor<T> vregXSquare;
        uint64_t loopOffset = i * FLOAT_REP_SIZE;

        Reg::LoadAlign<T, Reg::LoadDist::DIST_NORM>(vregX, inputBuf + loopOffset);
        Reg::Mul(vregXSquare, vregX, vregX, maskAll);
        Reg::Add(vregSum, vregXSquare, vregSum, maskAll);
    }

    Reg::Reduce<Reg::ReduceType::SUM, T, T, Reg::MaskMergeMode::ZEROING>(vregSumReduce, vregSum, maskAll);
    Reg::Muls<T, T, Reg::MaskMergeMode::ZEROING>(vregSumReduce, vregSumReduce, reciprocal, maskFirst);
    Reg::Adds<T, T, Reg::MaskMergeMode::ZEROING>(vregSumReduce, vregSumReduce, epsilon, maskFirst);
    Reg::Sqrt(vregSquareRoot, vregSumReduce, maskFirst);
    Reg::Duplicate<T, Reg::HighLowPart::LOWEST, Reg::MaskMergeMode::ZEROING>(vregDiv, vregSquareRoot, maskAll);

    for(uint32_t i = 0; i < repeatTimes; ++i){
        Reg::RegTensor<T> vregX;
        Reg::RegTensor<T> vregGammaCast;
        uint16_t loopOffset = i * FLOAT_REP_SIZE;

        Reg::LoadAlign<T, Reg::LoadDist::DIST_NORM>(vregX, inputBuf + loopOffset);
        Reg::LoadAlign<GammaType, Reg::LoadDist::DIST_NORM>(vregGammaCast, gammaBuf + loopOffset);
```

**要点**: (1) bfloat16→float 为宽位转换，SatMode::UNKNOWN 表示不适用饱和；(2) RMSNorm 涉 Reduce 求和、Sqrt、Div，中间均用 float 精度；(3) 与 MaskPattern::ALL/VL1 配合控制全通道与首通道掩码。


### 实例 9：indexer_quant_cache::vfComputeMaxExpMXFP4

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, PostLiteral, ReduceDataBlock, ReduceType, RegLayout, RegTensor, Select, StoreUnAlign, StoreUnAlignPost, UnalignReg, UpdateMask
- **SatMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 indexer_quant_cache 的 MXFP4 指数提取中，定义 castTraitHalf2Bf16 将 SatMode 设为 UNKNOWN，用于 half→bfloat16 转换并配合 CAST_TRUNC 截断舍入。

（行 89-128）

```cpp
__simd_vf__ inline void vfComputeMaxExpMXFP4(__ubuf__ T* srcAddr, __ubuf__ uint16_t* maxExpAddr,
    uint32_t totalCountInUB, uint16_t loopNum, uint32_t vlForB16, uint32_t numUbBlocksPerVReg)
{
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
        AscendC::Reg::MaskReg scaleMask2;
        AscendC::Reg::MaskReg invalidDataMask0;
        AscendC::Reg::MaskReg invalidDataMask1;
        AscendC::Reg::UnalignReg u1;
        static constexpr AscendC::Reg::CastTrait castTraitHalf2Bf16 = {
            AscendC::Reg::RegLayout::UNKNOWN, AscendC::Reg::SatMode::UNKNOWN,
            AscendC::Reg::MaskMergeMode::ZEROING, RoundMode::CAST_TRUNC};
        for (uint16_t i = 0; i < loopNum; i++) {
            scaleMask1 = AscendC::Reg::UpdateMask<T>(totalCountInUB);
            scaleMask2 = AscendC::Reg::UpdateMask<T>(totalCountInUB);
            AscendC::Reg::LoadAlign<
                T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE, AscendC::Reg::LoadDist::DIST_DINTLV_B16>(
                vdExp0, vdExp1, srcAddr, vlForB16 * DIGIT_TWO_MAXFP4);

            if constexpr (IsSameType<T, half>::value) {
                AscendC::Reg::And(
                    vdExpSelect0, (AscendC::Reg::RegTensor<uint16_t>&)vdExp0, invalidmaskfp16, scaleMask1);
                AscendC::Reg::And(
                    vdExpSelect1, (AscendC::Reg::RegTensor<uint16_t>&)vdExp1, invalidmaskfp16, scaleMask1);
                AscendC::Reg::Compare<uint16_t, CMPMODE::NE>(
                    invalidDataMask0, vdExpSelect0, invalidmaskfp16, scaleMask1);
                AscendC::Reg::Compare<uint16_t, CMPMODE::NE>(
```

**要点**: (1) half→bfloat16 为同位宽转换，SatMode::UNKNOWN 表示不饱和；(2) RegLayout::UNKNOWN 用于不需要特定布局的转换；(3) 与 And、Compare、Select 配合提取并校验指数位，过滤无效数据。


### 实例 10：dynamic_mx_quant::Reg::RegTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, Interleave, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, StoreAlign, StoreDist
- **SatMode 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 dynamic_mx_quant 尾轴量化中，定义 3 个 CastTrait：bf16→fp32 宽位用 SatMode::UNKNOWN，fp32→bf16 窄位用 SatMode::NO_SAT 不饱和（配合自定义舍入模式，由后续逻辑处理越界）。

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

**要点**: (1) bf16→fp32 宽位转换用 SatMode::UNKNOWN；(2) fp32→bf16 窄位转换选择 SatMode::NO_SAT 而非 SAT，表示该场景不希望钳位；(3) CastTrait 通过模板参数传入 Reg::Cast<dst, src, castTrait>(...) 调用。


### 实例 11：lightning_indexer_v2::HistogramsLastVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, DeInterleave, Duplicate, Histograms, HistogramsBinType, HistogramsType, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, RegLayout, RegTensor, StoreAlign, StoreDist
- **SatMode 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 lightning_indexer_v2 的 topk 直方图 VF 实现中，定义 uint16→uint32 的 CastTrait（EVEN），SatMode 设为 UNKNOWN，配合 RegLayout::ZERO 提取偶数通道元素。

（行 392-431）

```cpp
__simd_vf__ void HistogramsLastVFImpl(__ubuf__ uint32_t* histogramsBuf, __ubuf__ uint32_t* inputBuf,
                                      __ubuf__ uint32_t* idx0Buf, __ubuf__ uint32_t* idx1Buf,
                                      __ubuf__ uint32_t* idx2Buf, uint16_t vfLoop, bool init)
{
    Reg::MaskReg pregB32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregB16 = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::ALL>();

    // 计算直方图0-127 128-255
    Reg::RegTensor<uint16_t> cout0;
    Reg::RegTensor<uint16_t> cout1;
    Reg::Duplicate(cout0, 0);
    Reg::Duplicate(cout1, 0);

    Reg::RegTensor<uint32_t> cout0U32Even;
    Reg::RegTensor<uint32_t> cout0U32Odd;
    Reg::RegTensor<uint32_t> cout1U32Even;
    Reg::RegTensor<uint32_t> cout1U32Odd;

    Reg::RegTensor<uint32_t> idx0;
    Reg::RegTensor<uint32_t> idx1;
    Reg::RegTensor<uint32_t> idx2;
    // 0x000000fc -> 0xfcfcfcfc
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx0, idx0Buf);
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx1, idx1Buf);
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx2, idx2Buf);

    Reg::RegTensor<uint32_t> vreg0U16;
    Reg::RegTensor<uint32_t> vreg1U16;
    Reg::RegTensor<uint32_t> vreg2U16;
    Reg::RegTensor<uint32_t> vreg3U16;

    Reg::RegTensor<uint8_t> vreg0;
    Reg::RegTensor<uint8_t> vreg1;
    Reg::RegTensor<uint8_t> vreg2;
    Reg::RegTensor<uint8_t> vreg3;

    static constexpr Reg::CastTrait CAST_TRAIT_UINT16_TOUINT32_EVEN = {Reg::RegLayout::ZERO,
                Reg::SatMode::UNKNOWN, Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
```

**要点**: (1) uint16→uint32 为宽位转换，SatMode::UNKNOWN 不适用饱和；(2) RegLayout::ZERO 取偶数位通道，配合 DeInterleave 解交织；(3) 与 Histograms、Compare、And 配合统计直方图并 gather topk。


### 实例 12：stem_indexer::HistogramsLastVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, DeInterleave, Duplicate, Histograms, HistogramsBinType, HistogramsType, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, RegLayout, RegTensor, StoreAlign, StoreDist
- **SatMode 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 stem_indexer 的 topk 直方图 VF 实现中，定义 uint16→uint32 的 CastTrait（EVEN），SatMode 设为 UNKNOWN，配合 RegLayout::ZERO 提取偶数通道元素。

（行 392-431）

```cpp
__simd_vf__ void HistogramsLastVFImpl(__ubuf__ uint32_t* histogramsBuf, __ubuf__ uint32_t* inputBuf,
                                      __ubuf__ uint32_t* idx0Buf, __ubuf__ uint32_t* idx1Buf,
                                      __ubuf__ uint32_t* idx2Buf, uint16_t vfLoop, bool init)
{
    Reg::MaskReg pregB32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregB16 = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::ALL>();

    // 计算直方图0-127 128-255
    Reg::RegTensor<uint16_t> cout0;
    Reg::RegTensor<uint16_t> cout1;
    Reg::Duplicate(cout0, 0);
    Reg::Duplicate(cout1, 0);

    Reg::RegTensor<uint32_t> cout0U32Even;
    Reg::RegTensor<uint32_t> cout0U32Odd;
    Reg::RegTensor<uint32_t> cout1U32Even;
    Reg::RegTensor<uint32_t> cout1U32Odd;

    Reg::RegTensor<uint32_t> idx0;
    Reg::RegTensor<uint32_t> idx1;
    Reg::RegTensor<uint32_t> idx2;
    // 0x000000fc -> 0xfcfcfcfc
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx0, idx0Buf);
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx1, idx1Buf);
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx2, idx2Buf);

    Reg::RegTensor<uint32_t> vreg0U16;
    Reg::RegTensor<uint32_t> vreg1U16;
    Reg::RegTensor<uint32_t> vreg2U16;
    Reg::RegTensor<uint32_t> vreg3U16;

    Reg::RegTensor<uint8_t> vreg0;
    Reg::RegTensor<uint8_t> vreg1;
    Reg::RegTensor<uint8_t> vreg2;
    Reg::RegTensor<uint8_t> vreg3;

    static constexpr Reg::CastTrait CAST_TRAIT_UINT16_TOUINT32_EVEN = {Reg::RegLayout::ZERO,
                Reg::SatMode::UNKNOWN, Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
```

**要点**: (1) uint16→uint32 宽位转换，SatMode::UNKNOWN 不饱和；(2) RegLayout::ZERO 取偶数通道；(3) 与 Histograms、DeInterleave 配合完成直方图统计。


### 实例 13：quant_lightning_indexer::HistogramsLastVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, DeInterleave, Duplicate, Histograms, HistogramsBinType, HistogramsType, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, RegLayout, RegTensor, StoreAlign, StoreDist
- **SatMode 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 quant_lightning_indexer 的 topk 直方图 VF 实现中，定义 uint16→uint32 的 EVEN/ODD 两个 CastTrait，SatMode 均设为 UNKNOWN，配合 RegLayout::ZERO/ONE 分别提取偶数与奇数通道。

（行 367-406）

```cpp
__simd_vf__ void HistogramsLastVFImpl(__ubuf__ uint32_t* histogramsBuf, __ubuf__ uint32_t* inputBuf, __ubuf__ uint32_t* idx0Buf, __ubuf__ uint32_t* idx1Buf, __ubuf__ uint32_t* idx2Buf, uint16_t vfLoop, bool init)
{
    Reg::MaskReg pregB32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregB16 = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::ALL>();

    // 计算直方图0-127 128-255 
    Reg::RegTensor<uint16_t> cout0;
    Reg::RegTensor<uint16_t> cout1;
    Reg::Duplicate(cout0, 0);
    Reg::Duplicate(cout1, 0);

    Reg::RegTensor<uint32_t> cout0U32Even;
    Reg::RegTensor<uint32_t> cout0U32Odd;
    Reg::RegTensor<uint32_t> cout1U32Even;
    Reg::RegTensor<uint32_t> cout1U32Odd;

    Reg::RegTensor<uint32_t> idx0;
    Reg::RegTensor<uint32_t> idx1;
    Reg::RegTensor<uint32_t> idx2;
    // 0x000000fc -> 0xfcfcfcfc
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx0, idx0Buf);
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx1, idx1Buf);
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx2, idx2Buf);

    Reg::RegTensor<uint32_t> vreg0U16;
    Reg::RegTensor<uint32_t> vreg1U16;
    Reg::RegTensor<uint32_t> vreg2U16;
    Reg::RegTensor<uint32_t> vreg3U16;

    Reg::RegTensor<uint8_t> vreg0;
    Reg::RegTensor<uint8_t> vreg1;
    Reg::RegTensor<uint8_t> vreg2;
    Reg::RegTensor<uint8_t> vreg3;

    static constexpr Reg::CastTrait CAST_TRAIT_UINT16_TOUINT32_EVEN = {Reg::RegLayout::ZERO,
                Reg::SatMode::UNKNOWN, Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};

    static constexpr Reg::CastTrait CAST_TRAIT_UINT16_TOUINT32_ODD = {Reg::RegLayout::ONE,
                Reg::SatMode::UNKNOWN, Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};
```

**要点**: (1) uint16→uint32 宽位转换，SatMode::UNKNOWN 不适用饱和；(2) RegLayout::ZERO/ONE 区分偶数位与奇数位通道；(3) EVEN/ODD 两个 CastTrait 配合 DeInterleave 解交织提取数据。


### 实例 14：lightning_indexer::HistogramsLastVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, DeInterleave, Duplicate, Histograms, HistogramsBinType, HistogramsType, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, RegLayout, RegTensor, StoreAlign, StoreDist
- **SatMode 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 lightning_indexer 的 topk 直方图 VF 实现中，定义 uint16→uint32 的 EVEN/ODD 两个 CastTrait，SatMode 均设为 UNKNOWN，配合 RegLayout::ZERO/ONE 分别提取偶数与奇数通道元素。

（行 383-422）

```cpp
__simd_vf__ void HistogramsLastVFImpl(__ubuf__ uint32_t* histogramsBuf, __ubuf__ uint32_t* inputBuf,
                                      __ubuf__ uint32_t* idx0Buf, __ubuf__ uint32_t* idx1Buf,
                                      __ubuf__ uint32_t* idx2Buf, uint16_t vfLoop, bool init)
{
    Reg::MaskReg pregB32Reg6 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregB16Reg3 = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg pregB8Reg3 = Reg::CreateMask<uint8_t, Reg::MaskPattern::ALL>();

    // 计算直方图0-127 128-255
    Reg::RegTensor<uint16_t> cout0, cout1;
    Reg::Duplicate(cout0, 0);
    Reg::Duplicate(cout1, 0);

    Reg::RegTensor<uint32_t> cout0U32Even, cout0U32Odd, cout1U32Even, cout1U32Odd;

    Reg::RegTensor<uint32_t> idx0, idx1, idx2;
    // 0x000000fc -> 0xfcfcfcfc
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx0, idx0Buf);
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx1, idx1Buf);
    Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idx2, idx2Buf);

    Reg::RegTensor<uint32_t> vreg0U16, vreg1U16, vreg2U16, vreg3U16;

    Reg::RegTensor<uint8_t> vreg0, vreg1, vreg2, vreg3;

    static constexpr Reg::CastTrait CAST_TRAIT_UINT16_TOUINT32_EVEN = {Reg::RegLayout::ZERO,
                Reg::SatMode::UNKNOWN, Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};

    static constexpr Reg::CastTrait CAST_TRAIT_UINT16_TOUINT32_ODD = {Reg::RegLayout::ONE,
                Reg::SatMode::UNKNOWN, Reg::MaskMergeMode::ZEROING, RoundMode::UNKNOWN};

    for (uint16_t i = 0; i < vfLoop; ++i) {
        Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_DINTLV_B16>(vreg1U16, vreg0U16, inputBuf + i * 256);
        Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_DINTLV_B16>(vreg3U16, vreg2U16,
                                                                           inputBuf + (i * 256) + 128);

        Reg::DeInterleave(vreg1, vreg0, (Reg::RegTensor<uint8_t>&)vreg0U16,
                               (Reg::RegTensor<uint8_t>&)vreg2U16);
        Reg::DeInterleave(vreg3, vreg2, (Reg::RegTensor<uint8_t>&)vreg1U16,
                               (Reg::RegTensor<uint8_t>&)vreg3U16);
```

**要点**: (1) uint16→uint32 宽位转换，SatMode::UNKNOWN 不饱和；(2) RegLayout::ZERO/ONE 区分偶/奇通道；(3) 与 Histograms、DeInterleave 配合统计直方图并 gather topk。


### 实例 15：swiglu_group_quant::VFComputeMaxExpMXFP4Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, Select, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **SatMode 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 SwiGLU 分组量化的 MXFP4 指数提取中，定义 castTraitHalf2Bf16 将 SatMode 设为 UNKNOWN，用于 half→bfloat16 转换并配合 CAST_TRUNC 截断舍入。

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

**要点**: (1) half→bfloat16 同位宽转换，SatMode::UNKNOWN 不饱和；(2) 与 And、Compare、Select、Cast 链式配合提取指数并过滤无效值；(3) 用于 MXFP4 量化标尺的最大指数计算。


### SatMode 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| grouped_dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | CastTrait 中 SatMode::UNKNOWN，配合 RegLayout::ZERO / MaskMergeMode::ZEROING 用于不适用饱和的类型转换 | __VEC_SCOPE__ |
| dynamic_block_quant | And, Cast, CastTrait, CompareScalar, CreateMask | CastTrait 中 SatMode::NO_SAT，不饱和转换，配合 RegLayout::ZERO 用于中间计算 | __VEC_SCOPE__ |
| incre_flash_attention | Add, Cast, CastTrait, CreateMask, DataCopy | CastTrait 携带 SatMode 用于 Softmax 多次类型转换的饱和控制 | __aicore__ |
| mla_prolog | Abs, Cast, CastTrait, CreateMask, Div | 同一函数按转换方向差异化使用 SAT / NO_SAT / UNKNOWN 三种 SatMode，窄化用 SAT 饱和钳位 | __simd_vf__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | castTraitHalf2Float 用于 half→float 宽位转换，SatMode::UNKNOWN | __simd_vf__ |
| abs | Abs, Add, Cast, CastTrait, Compare | CastTrait 携带 SatMode 用于复数模长的 float↔窄类型转换，回写用 SAT | __aicore__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | 宽位转换 SatMode::UNKNOWN、窄位回写 SatMode::SAT+CAST_RINT，RegLayout::ZERO/ONE 取实虚部 | __VEC_SCOPE__ |
| compressor | Add, Adds, CastTrait, CreateMask, Div | castTraitB162B32 用于 bfloat16→float 宽位转换，SatMode::UNKNOWN | __simd_vf__ |
| indexer_quant_cache | And, Cast, CastTrait, Compare, Duplicate | castTraitHalf2Bf16 用于 half→bfloat16 转换，SatMode::UNKNOWN + CAST_TRUNC | __simd_vf__ |
| dynamic_mx_quant | Cast, CastTrait, CreateMask, DeInterleave, Duplicate | bf16→fp32 用 SatMode::UNKNOWN，fp32→bf16 窄位用 SatMode::NO_SAT 不饱和 | __VEC_SCOPE__ |
| lightning_indexer_v2 | And, Cast, CastTrait, Compare, CreateMask | uint16→uint32 宽位转换 SatMode::UNKNOWN，RegLayout::ZERO 取偶通道 | __simd_vf__ |
| stem_indexer | And, Cast, CastTrait, Compare, CreateMask | uint16→uint32 宽位转换 SatMode::UNKNOWN，RegLayout::ZERO 取偶通道 | __simd_vf__ |
| quant_lightning_indexer | And, Cast, CastTrait, Compare, CreateMask | uint16→uint32 宽位转换 SatMode::UNKNOWN，RegLayout::ZERO/ONE 取偶/奇通道 | __simd_vf__ |
| lightning_indexer | And, Cast, CastTrait, Compare, CreateMask | uint16→uint32 宽位转换 SatMode::UNKNOWN，RegLayout::ZERO/ONE 取偶/奇通道 | __simd_vf__ |
| swiglu_group_quant | And, Cast, CastTrait, Compare, Duplicate | castTraitHalf2Bf16 用于 half→bfloat16 转换，SatMode::UNKNOWN + CAST_TRUNC | __simd_vf__ |
