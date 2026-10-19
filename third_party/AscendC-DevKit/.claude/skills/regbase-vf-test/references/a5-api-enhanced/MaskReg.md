# MaskReg

**页面ID:** atlasascendc_api_07_0315  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0315.html

---

#### 功能说明

MaskReg用于指示在计算过程中哪些元素参与计算，宽度为RegTensor的八分之一（VL/8）。

![](images/atlasascendc_api_07_0315_img_001.png)

#### 函数原型

```
template <typename T, MaskPattern mode = MaskPattern::ALL, const RegTrait& regTrait = RegTraitNumOne>
__simd_callee__ inline MaskReg CreateMask();

template <typename T, const RegTrait& regTrait = RegTraitNumOne>
__simd_callee__ inline MaskReg UpdateMask(uint32_t& scalarValue);
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| mode | 输入 | 创建MaskReg的模式，enum class类型。 ``` enum class MaskPattern {     ALL,      // 所有元素设置为True     VL1,      // 最低1个元素     VL2,      // 最低2个元素     VL3,      // 最低3个元素     VL4,      // 最低4个元素     VL8,      // 最低8个元素     VL16,     // 最低16个元素     VL32,     // 最低32个元素     VL64,     // 最低64个元素     VL128,    // 最低128个元素     M3,       // 3的倍数     M4,       // 4的倍数     H,        // 最低一半元素     Q,        // 最低四分之一元素     ALLF = 15 // 所有元素设置为false }; ``` |
| regTrait | 输入 | 当前仅针对b64/complex32数据类型生效，分为RegTraitNumOne和RegTraitNumTwo，含义和RegTensor的模板regTrait类型一致，配合RegTensor的regTrait一起使用。regTrait为RegTraitNumOne时，表明当前MaskReg的作用范围可覆盖至256B（一个VL的长度）。对于使用RegTraitNumOne的b64 RegTensor的指令，生成的b64 mask为每8位有效；RegTraitNumTwo表明当前MaskReg的作用范围可覆盖至512B（两个VL的长度），生成的b64 mask为每4位有效，作用于使用RegTraitNumTwo的b64 RegTensor的指令。该参数默认值为RegTraitNumOne。 |
| scalarValue | 输入/输出 | 矢量计算需要操作的元素的具体数量，生成对应的MaskReg，元素有效范围从0到VL_T（位宽为VL的T类型元素个数）。 执行完该函数后，scalarValue会减去VL_T。 scalarValue = (scalarValue < VL_T) ? 0 : (scalarValue - VL_T) |

#### 返回值说明

MaskReg

#### 支持的型号

Atlas 350 加速卡

#### 约束说明

无

#### 调用示例

```
AscendC::Reg::RegTensor<uint32_t> srcReg;
AscendC::Reg::MaskReg mask0 = AscendC::Reg::CreateMask<uint32_t,AscendC::Reg:: MaskPattern::ALL >();
AscendC::Reg::MaskReg mask1;
uint32_t scalarValue = 127;
for (uint16_t i = 0; i < 2; i++) {
    mask1 = AscendC::Reg::UpdateMask<uint32_t>(scalarValue);
    AscendC::Reg::LoadAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(srcReg, srcAddr, 0);
    AscendC::Reg::Adds(srcReg, srcReg, 1, mask0);
    AscendC::Reg::StoreAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(dst0Addr, srcReg, 0, mask0);
    AscendC::Reg::StoreAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(dst1Addr, srcReg, 0, mask1);
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 MaskReg 实例

### 实例 1：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **MaskReg 调用次数**: 6
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 动态量化算子 ComputeVF 中,在 __VEC_SCOPE__ 内用 CreateMask/UpdateMask 生成全使能与尾块掩码,驱动逐 token 的 abs->reduceMax->scale->clip 量化链。

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

**要点**: 1) CreateMask 生成全使能掩码、UpdateMask(scalarValue) 按剩余元素数生成尾块掩码;2) MaskMergeMode::ZEROING 使掩码外元素置零;3) 与 Abs/Cast/Div/ReduceMax 组合完成逐元素量化。


### 实例 2：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskUnPack, Max, Min, PostLiteral, ReduceMax, RegLayout, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **MaskReg 调用次数**: 6
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 块量化单行 kernel 中,声明多个 MaskReg 实例并用 CreateMask 生成默认全使能掩码,控制逐块缩放计算。

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

**要点**: 1) MaskReg 可默认构造后再由 Compare/CompareScalar 结果赋值;2) CreateMask 采用默认 MaskPattern::ALL 生成全使能掩码;3) 与 MaskUnPack/StoreUnAlign 配合处理块边界。


### 实例 3：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub, UnPack
- **MaskReg 调用次数**: 6
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: SwiGLU 双轴 MX 量化中,针对 xDtype/uint32/uint8 等不同类型与 VL8/VL16 reduce 宽度创建多档 MaskReg,支持分块绝对值最大值归约。

（行 947-986）

```cpp
__VEC_SCOPE__
{
    // ===== Register declarations =====
    Reg::RegTensor<xDtype> x0, x1;
    Reg::RegTensor<uint16_t> x0Abs, x1Abs;
    Reg::RegTensor<uint16_t> absMaxDim1;
    Reg::RegTensor<xDtype> absMaxDim1Unpack;
    Reg::RegTensor<uint16_t> absMax1Dim2, absMax2Dim2;

    // CLUB FP32 computation registers
    Reg::RegTensor<uint32_t> max32, exp32, man32, expAddOne32, extractExp;
    Reg::RegTensor<uint32_t> halfScale;
    Reg::RegTensor<uint16_t> scale16;
    Reg::RegTensor<uint8_t> scale8Zero, scale8One;
    Reg::RegTensor<uint16_t> recip16Zero, recip16One;

    // -2 axis output registers
    Reg::RegTensor<uint8_t> mxScale2ZeroB8, mxScale2OneB8;
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
```

**要点**: 1) CreateMask 的模板参数 T 决定掩码位宽(VL/8),需与被掩码 RegTensor 类型匹配;2) MaskPattern::VL8/VL16 仅使能最低 N 元素,适配 block 内 reduce;3) MaskAnd/MaskOr 组合多掩码实现条件分支。


### 实例 4：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **MaskReg 调用次数**: 7
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: flat_quant 的 ScaleVfcuBLAS 中,用 UpdateMask 按剩余元素数生成部分使能掩码,控制半精度缩放循环的尾块。

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

**要点**: 1) UpdateMask 接受 uint32_t& scalarValue,生成覆盖 [0,scalarValue) 元素的掩码并自动将 scalarValue 减去 VL_T;2) 适合处理不足一个 VL 的尾块;3) 与 Cast/Mul/StoreAlign 组合完成 fp 缩放。


### 实例 5：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **MaskReg 调用次数**: 11
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 双轴动态 MX 量化 base 中,高频使用 MaskReg(11 次)控制 -1/-2 轴的绝对值归约、指数提取与 scale 计算,配合 Interleave/DeInterleave 处理奇偶列。

（行 602-641）

```cpp
__VEC_SCOPE__
{
    // ========== 输入数据寄存器 ==========
    Reg::RegTensor<xDtype> x0;
    Reg::RegTensor<xDtype> x1;

    // ========== 绝对值和max寄存器 ==========
    Reg::RegTensor<uint16_t> absMax0;     // x0的绝对值
    Reg::RegTensor<uint16_t> absMax1;     // x1的绝对值
    Reg::RegTensor<uint16_t> absMaxDim1;  // -1轴方向block内绝对值max
    Reg::RegTensor<uint16_t> absMax1Dim2; // -2轴方向累积max (偶数列, 对应x0)
    Reg::RegTensor<uint16_t> absMax2Dim2; // -2轴方向累积max (奇数列, 对应x1)
    Reg::RegTensor<uint16_t> zeroB16;     // -1轴Interleave用零寄存器

    // ========== FP32计算寄存器 ==========
    // -1轴: Interleave-with-0后单次Cast Zero处理全部8个值，仅需一组FP32寄存器
    // -2轴: 仍需Zero/One两组独立处理
    Reg::RegTensor<uint32_t> maxFP32_0; // FP32表示, 链内复用为expPlusOne
    Reg::RegTensor<uint32_t> maxFP32_1; // -2轴奇数部分FP32表示
    Reg::RegTensor<uint32_t> expFP32_0; // FP32指数
    Reg::RegTensor<uint32_t> expFP32_1; // -2轴奇数部分FP32指数
    Reg::RegTensor<uint32_t> manFP32_0; // FP32尾数, 链内复用为extractExp
    Reg::RegTensor<uint32_t> manFP32_1; // -2轴奇数部分FP32尾数

    // scale输出寄存器 (循环后复用于-2轴scale输出)
    Reg::RegTensor<uint16_t> scale1B16_0;       // E8M0 uint16, 循环后复用为mxScale2ZeroB16
    Reg::RegTensor<uint16_t> scale1B16_1;       // -2轴奇数部分, 循环后复用为mxScale2OneB16
    Reg::RegTensor<uint16_t> scale1BF16;        // BF16指数格式, 循环后复用为scale2BF16
    Reg::RegTensor<uint8_t> mxScale1B8;         // uint8 scale, 循环后复用为mxScale2ZeroB8
    Reg::RegTensor<uint16_t> reversedShareExp1; // 1/scale BF16, 循环后复用为reversedShareExp2Zero

    // -2轴独立寄存器 (需与复用寄存器同时存活，无法复用)
    Reg::RegTensor<uint8_t> mxScale2OneB8; // 与mxScale1B8同时存活于最终DataCopy

    // ========== 常量寄存器 ==========
    Reg::RegTensor<uint16_t> absMask;
    Reg::Duplicate(absMask, ABS_MASK_FOR_16BIT);
    Reg::RegTensor<uint32_t> invMax;
    Reg::Duplicate(invMax, invDtypeMax_); // 1/Amax(DType), FP32表示
    Reg::RegTensor<uint32_t> manMaskFP32;
```

**要点**: 1) 高频 MaskReg 反映双轴 reduce 的多阶段掩码需求;2) MaskOr 合并多路掩码结果;3) 与 HighLowPart/Pack/ReduceMaxWithDataBlock 组合完成 block 级 amax->scale。


### 实例 6：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **MaskReg 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 复数绝对值算子中,声明带 RegTraitNumOne 的 float RegTensor,用 MaskReg 控制逐元素 Abs/Mul/Sqrt/Select 的掩码,处理 subnormal 缩放防溢出。

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

**要点**: 1) RegTraitNumOne 显式指定 mask 作用范围覆盖 256B(一个 VL);2) 与 Select/Compare 配合处理 subnormal 数的 SCALE_UP/SCALE_DOWN;3) MaskMergeMode 控制 mask 外元素语义。


### 实例 7：abs::AbscomplexCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **MaskReg 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 复数取绝对值算子(abs 复数版)中,与 complex_abs 结构一致,用 MaskReg 控制平方和开方链路的掩码。

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

**要点**: 1) 与 complex_abs 共享相同的 subnormal 处理与 RegTraitNumOne 用法;2) 体现同一掩码模式在不同算子中的复用;3) Compare/Select + MaskReg 实现条件置零。


### 实例 8：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, Max, Maxs, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **MaskReg 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 逐通道伪量化算子的整体结构,VL=64(fp32 256B),VF Compute 分 Load/Prepare/主公式三阶段,MaskReg 用于尾块与逐通道裁剪的掩码控制。

（行 21-60）

```cpp
 *   5. VF Compute 三阶段（同一 __VEC_SCOPE__ 内）：
 *      阶段 1 Load (x/min/max → RegTensor)
 *      阶段 2 Prepare 重算 (scale/scaleSafe/both/zpFromMin/nudgedZp/nudgedMin/nudgedMax 全 RegTensor)
 *      阶段 3 主公式 (clip/shift/div/floor/mul/add/bothMul)
 *   6. invQuantRange_ host 算好下发，避免 VF 内重复 Div
 *   7. CastTrait 仍集中在 _base.h（v2.1 已就绪）
 */
#ifndef _FAKE_QUANT_WITH_MIN_MAX_VARS_PER_CHANNEL_H_
#define _FAKE_QUANT_WITH_MIN_MAX_VARS_PER_CHANNEL_H_

#include "kernel_operator.h"
#include "kernel_tiling/kernel_tiling.h"
#include "fake_quant_with_min_max_vars_per_channel_tiling_data.h"
#include "fake_quant_with_min_max_vars_per_channel_base.h"

namespace NsFakeQuantPerChannel {

using namespace AscendC;

template <typename T>
class FakeQuantPerChannelNativePC {
    static constexpr int32_t BUF_NUM = 2; // Double Buffer
    static constexpr int64_t VL = 64;     // VL = 64 (fp32 = 256B)

public:
    __aicore__ inline FakeQuantPerChannelNativePC() {}

    __aicore__ inline void Init(GM_ADDR x, GM_ADDR minIn, GM_ADDR maxIn, GM_ADDR y,
                                const FakeQuantWithMinMaxVarsPerChannelTilingData* td);
    __aicore__ inline void Process();

private:
    __aicore__ inline void ProcessSegment(int64_t rowsThisBlk, int64_t baseRow);

    __aicore__ inline void CopyInMin(int64_t curLen, int64_t tailOff);
    __aicore__ inline void CopyInMax(int64_t curLen, int64_t tailOff);
    __aicore__ inline void CopyInX(int64_t curLen, int64_t xElemOff);
    __aicore__ inline void Compute(int64_t curLen, LocalTensor<T>& minSeg, LocalTensor<T>& maxSeg);
    __aicore__ inline void CopyOutY(int64_t curLen, int64_t yElemOff);
```

**要点**: 1) VL 由 VECTOR_REG_WIDTH/dtypeSize 推导,MaskReg 宽度随之确定为 VL/8;2) 三阶段在同一 __VEC_SCOPE__ 内复用 MaskReg;3) 与 Clip/Shift/Div/Floor 组合完成量化映射。


### 实例 9：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, Duplicate, Interleave, LoadAlign, MaskMergeMode, MaskPattern, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **MaskReg 调用次数**: 7
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 分组动态 MX 量化中,声明多个具名 MaskReg(infMask/zeroMask/invalidDataMask/specialDataMask)分别承载不同异常条件判定,配合 maskAll 全使能掩码。

（行 276-315）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<T> xRegTensor;
    Reg::RegTensor<uint16_t> expRegTensor;
    Reg::RegTensor<uint16_t> expMaxRegTensor;
    Reg::RegTensor<T> xRegTensor0;
    Reg::RegTensor<T> xRegTensor1;
    Reg::RegTensor<bfloat16_t> xBF16RegTensor0;
    Reg::RegTensor<bfloat16_t> xBF16RegTensor1;
    Reg::RegTensor<uint16_t> expMaxRegTensor0;
    Reg::RegTensor<uint16_t> expMaxRegTensor1;
    Reg::RegTensor<uint16_t> maxEleRegTensor;
    Reg::RegTensor<uint16_t> fp8MaxExpRegTensor;
    Reg::RegTensor<uint16_t> fp8NanRegTensor;
    Reg::RegTensor<uint16_t> mxScaleRegTensor;
    Reg::RegTensor<uint8_t> mxScale;
    Reg::RegTensor<uint16_t> reversedShareExpRegTensor;
    Reg::RegTensor<float> reversedShareExpRegTensorFP32Zero;
    Reg::RegTensor<float> reversedShareExpRegTensorFP32One;
    Reg::RegTensor<uint16_t> specialExpRegTensor;
    Reg::RegTensor<uint16_t> biasRegTensor;
    Reg::RegTensor<uint16_t> zeroRegTensor;
    Reg::RegTensor<uint16_t> nanRegTensor;
    Reg::RegTensor<uint16_t> yRegTensorZero;
    Reg::RegTensor<uint16_t> yRegTensorOne;
    Reg::RegTensor<uint8_t> outZero;
    Reg::RegTensor<uint8_t> outOne;
    Reg::RegTensor<float> yZero;
    Reg::RegTensor<float> yOne;
    Reg::RegTensor<U> yZeroFP8;
    Reg::RegTensor<U> yOneFP8;
    Reg::RegTensor<bfloat16_t> valueRegTensor;

    Reg::UnalignReg u0;
    Reg::MaskReg infMask;
    Reg::MaskReg zeroMask;
    Reg::MaskReg invalidDataMask;
    Reg::MaskReg specialDataMask;
    Reg::MaskReg maskAll = Reg::CreateMask<uint16_t, Reg::MaskPattern::ALL>();
```

**要点**: 1) MaskReg 既是运算掩码也是布尔条件寄存器,可由 Compare 结果赋值;2) 多个 MaskReg 分层表达 inf/zero/invalid 等异常分支;3) 与 Select/Pack/StoreUnAlign 组合按条件输出。


### 实例 10：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **MaskReg 调用次数**: 7
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: RMS Norm + MX 量化融合算子的 scale 计算 kernel,用多个 MaskReg(cmpResult/zeroMask/p0/p1/p2)承载指数比较的中间条件,驱动 NaN/FP8 边界处理。

（行 415-454）

```cpp
__aicore__ inline void MxQuantComputeScalecuBLAS(__ubuf__ uint16_t* maxExpAddr, __ubuf__ uint16_t* mxScaleLocalAddr,
                                                 __ubuf__ uint16_t* halfScaleLocalAddr, uint32_t totalScaleInUB,
                                                 uint16_t loopNumScale4NV)
{
    uint32_t dtypeMax;
    if constexpr (IsSame<T_Y, fp8_e4m3fn_t>::value) {
        dtypeMax = MX_FP8_E4M3_MAX;
    } else {
        dtypeMax = MX_FP8_E5M2_MAX;
    }
    __VEC_SCOPE__
    {
        AscendC::Reg::RegTensor<uint16_t> max16;
        AscendC::Reg::RegTensor<uint32_t> max32;
        AscendC::Reg::RegTensor<uint32_t> exp32;
        AscendC::Reg::RegTensor<uint32_t> man32;
        AscendC::Reg::RegTensor<uint32_t> expAddOne32;
        AscendC::Reg::RegTensor<uint32_t> extractExp;
        AscendC::Reg::RegTensor<uint16_t> expOut;
        AscendC::Reg::RegTensor<uint32_t> halfScale;
        AscendC::Reg::RegTensor<uint16_t> recExpOut;
        AscendC::Reg::RegTensor<uint32_t> invMax;
        AscendC::Reg::Duplicate(invMax, dtypeMax);
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
        AscendC::Reg::RegTensor<uint32_t> fp8NanRegTensor;
        AscendC::Reg::Duplicate(fp8NanRegTensor, MAX_EXP_FOR_FP8_IN_FP32);
        AscendC::Reg::MaskReg cmpResult;
        AscendC::Reg::MaskReg zeroMask;
        AscendC::Reg::MaskReg p0;
        AscendC::Reg::MaskReg p1;
        AscendC::Reg::MaskReg p2;
```

**要点**: 1) p0/p1/p2 作为分支条件掩码串联多级比较;2) CreateMask 生成全使能基础掩码供 Cast/Compare 使用;3) 与 HighLowPart/ShiftLefts 组合提取 FP32 指数与尾数。


### 实例 11：swiglu_mx_quant::ComputeScaleBLASLast

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **MaskReg 调用次数**: 4
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: SwiGLU MX 量化 last-axis scale 计算,用 CreateMask VL64 模式生成半使能掩码,配合循环 DataCopy 做分块指数提取。

（行 904-943）

```cpp
__aicore__ inline void ComputeScaleBLASLast(uint32_t dtypeMax, __ubuf__ uint16_t* maxExpAddr,
                                            __ubuf__ uint16_t* mxScaleLocalAddr, __ubuf__ uint16_t* halfScaleLocalAddr,
                                            int64_t dim0OnceSize, int64_t alignDim1Size)
{
    uint32_t totalScaleInUB = dim0OnceSize * (alignDim1Size / CONST_32);
    uint16_t loopNumScale = CeilDivision(totalScaleInUB, CONST_64);
    uint32_t manMaskFloat = MAN_MASK_FLOAT;
    uint32_t maxExpForFp32 = MAX_EXP_FOR_FP32;
    uint32_t fp32ExpBiasCublas = FP32_EXP_BIAS_CUBLAS;
    uint32_t nanCustomiZation = NAN_CUSTOMIZATION_PACK;
    uint32_t maxExpForFp8InFp32 = MAX_EXP_FOR_FP8_IN_FP32;
    uint32_t zeroForAll = ZERO_FOR_ALL;
    uint32_t Exp254 = EXP_254;
    uint32_t halfForMan = HALF_FOR_MAN;
    int64_t onceNum = CONST_64;
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
```

**要点**: 1) MaskPattern::VL64 仅使能最低 64 元素,对应一个 block 的 reduce 范围;2) CreateMask 默认 ALL 用于全使能中间计算;3) 与 Cast/Compare/Max 组合完成 amax->exp->scale。


### 实例 12：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **MaskReg 调用次数**: 7
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: RMS Norm 动态 MX 量化的 scale 计算,与 add_rms_norm 同构,用一组 MaskReg 承载指数比较条件,处理 fp8_e4m3/e5m2 的 dtypeMax 分派。

（行 369-408）

```cpp
__aicore__ inline void ComputeScalecuBLAS(__ubuf__ uint16_t* maxExpAddr, __ubuf__ uint16_t* mxScaleLocalAddr,
                                          __ubuf__ uint16_t* halfScaleLocalAddr, uint32_t totalScaleInUB,
                                          uint16_t loopNumScale4NV)
{
    static constexpr uint32_t zeroForAll = 0x00000000;
    static constexpr uint32_t Exp254 = 0x000000fe;
    static constexpr uint32_t halfForMan = 0x00400000;

    uint32_t dtypeMax = 0; // 算法暂不支持fp4量化
    if constexpr (IsSameType<T2, fp8_e4m3fn_t>::value) {
        dtypeMax = FP8_E4M3_MAX;
    } else if constexpr (IsSameType<T2, fp8_e5m2_t>::value) {
        dtypeMax = FP8_E5M2_MAX;
    }

    __VEC_SCOPE__
    {
        AscendC::Reg::RegTensor<uint16_t> max16;
        AscendC::Reg::RegTensor<uint16_t> expOut;
        AscendC::Reg::RegTensor<uint16_t> recExpOut;
        AscendC::Reg::RegTensor<uint32_t> max32;
        AscendC::Reg::RegTensor<uint32_t> exp32;
        AscendC::Reg::RegTensor<uint32_t> man32;
        AscendC::Reg::RegTensor<uint32_t> expAddOne32;
        AscendC::Reg::RegTensor<uint32_t> extractExp;
        AscendC::Reg::RegTensor<uint32_t> halfScale;
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
```

**要点**: 1) if constexpr 按 T2 类型选择 dtypeMax,掩码逻辑不变;2) preMaskScale 作为 reduce 前的预掩码;3) 与 MaskAnd/MaskOr 组合多条件。


### 实例 13：swiglu_backward_mx_quant_with_dual_axis::ComputeScaleCuBLASSecondLast

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, Sub
- **MaskReg 调用次数**: 5
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: SwiGLU 反向双轴量化的次末轴 scale 计算,针对 xDtype/uint32/uint8/uint16 四种类型创建不同位宽与使能宽度的 MaskReg。

（行 778-817）

```cpp
__aicore__ inline void SwigluBackwardMxQuantWithDualAxisBase<xDtype, y1Dtype, mode, roundMode, scaleAlg, isGroupIdx>::
    ComputeScaleCuBLASSecondLast(uint16_t dataLen, uint32_t localInvDtypeMax, __ubuf__ uint16_t* mxScale2ReciprocalAddr,
                                 __ubuf__ uint8_t* mxScale2Addr)
{
    uint16_t times = dataLen / VF_LEN_FP32;
    __ubuf__ uint16_t* mxScale2ReciprocalOutAddr = mxScale2ReciprocalAddr;
    __VEC_SCOPE__
    {
        Reg::RegTensor<uint16_t> max16Reg;
        Reg::RegTensor<uint32_t> max32Reg;
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
        for (uint16_t i = 0; i < times; i++) {
            Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                               AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16Reg, mxScale2ReciprocalAddr,
                                                                             VF_LEN_FP32);
            Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>((Reg::RegTensor<float>&)max32Reg,
                                                               (Reg::RegTensor<xDtype>&)max16Reg, maskAll);
            Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32Reg, expMaskReg, maskAll32);
            Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32Reg, zero32Reg, maskAll32);
```

**要点**: 1) 同一 kernel 内为不同 dtype 各建一档 MaskReg,保证 mask 位宽与 RegTensor 匹配;2) VL64 用于 b8/b16 的 block reduce;3) 与 Cast/Compare/DataCopy(POST_MODE_UPDATE) 组合循环处理。


### 实例 14：dynamic_mx_quant::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, ShiftRights, StoreUnAlign, StoreUnAlignPost, UnalignReg
- **MaskReg 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 动态 MX 量化尾轴处理,用 CreateMask 生成 b32/b16 两档全使能掩码,配合 DeInterleave/And/Max/ReduceMaxWithDataBlock 做 block 内指数最大值归约。

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

**要点**: 1) 同一作用域内为 uint32 与 uint16 分别建 MaskReg,对应不同位宽运算;2) ReduceMaxWithDataBlock 依赖 MaskReg 限定 reduce 范围;3) 与 UnalignReg/StoreUnAlignPost 处理非对齐尾块输出。


### 实例 15：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, ClearSpr, Compare, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, GatherMask, GatherMaskMode, Interleave, LoadDist, MaskInterleave, PostLiteral, RegTensor, SubCarryOut, SubCarryOuts, UnalignReg, UpdateMask
- **MaskReg 调用次数**: 7
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 稀疏切片算子中,MaskReg 作为索引/选择条件的布尔寄存器(pregIndices/pregSelect/carryOut 等),配合 GatherMask 实现按掩码聚集元素。

（行 651-690）

```cpp
__VEC_SCOPE__
{
    // clear special AR for GatherMask
    Reg::RegTensor<int64_t> vregInputOne;
    Reg::RegTensor<int64_t> vregInputTwo;

    Reg::RegTensor<uint32_t> vregLowerBoundLowerHalf;
    Reg::RegTensor<int32_t> vregLowerBoundHigherHalf;

    Reg::RegTensor<uint32_t> vregInputLowerHalf;
    Reg::RegTensor<int32_t> vregInputHigherHalf;

    Reg::RegTensor<uint32_t> vregInputSubLower;
    Reg::RegTensor<int32_t> vregInputSubHigher;

    Reg::RegTensor<int32_t> vregGatherLowerHalf;
    Reg::RegTensor<int32_t> vregGatherHigherHalf;

    Reg::RegTensor<int32_t> vregGatherOutput0;
    Reg::RegTensor<int32_t> vregGatherOutput1;
    Reg::RegTensor<int32_t> vregGatherResult0;
    Reg::RegTensor<int32_t> vregGatherResult1;

    Reg::RegTensor<int8_t> vregInMask;
    Reg::RegTensor<int32_t> vregInMaskGathered;

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
```

**要点**: 1) MaskReg 在非量化场景下作为 GatherMask 的选择掩码与 SubCarryOut 的进位寄存器;2) pregSelectFinal0/1 体现掩码可分高低位并行;3) 与 GatherMaskMode/MaskInterleave 组合完成稀疏 gather。


### MaskReg 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | 全使能 + UpdateMask 尾块掩码驱动逐 token 量化链 | __aicore__ |
| dynamic_block_quant | And, Cast, CastTrait, CompareScalar, CreateMask | 默认构造多 MaskReg + CreateMask 全使能掩码 | __VEC_SCOPE__ |
| swiglu_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 多 dtype/多 VL 档位 CreateMask 支持双轴 block reduce | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | UpdateMask(scalarValue) 按元素数生成尾块掩码 | __simd_vf__ |
| dynamic_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 高频 MaskReg + MaskOr 合并多路掩码做双轴 amax->scale | __VEC_SCOPE__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | RegTraitNumOne 显式 256B 作用域掩码 + Select 处理 subnormal | __aicore__ |
| abs | Abs, Add, Cast, CastTrait, Compare | 复用 complex_abs 掩码模式做复数平方和开方 | __aicore__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | VL=64 三阶段 VF 复用 MaskReg 做逐通道裁剪 | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | And, Cast, CastTrait, Compare, CreateMask | 多具名 MaskReg 承载 inf/zero/invalid 异常条件分支 | __VEC_SCOPE__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | p0/p1/p2 串联多级比较掩码驱动指数提取与 NaN 边界 | __aicore__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | CreateMask VL64 半使能掩码 + 循环 DataCopy 分块算 scale | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | preMaskScale 预掩码 + if constexpr 分派 fp8 dtypeMax | __aicore__ |
| swiglu_backward_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 四档 dtype MaskReg + VL64 block reduce 循环 | __aicore__ |
| dynamic_mx_quant | And, CastTrait, CreateMask, DeInterleave, Duplicate | b32/b16 双档全使能掩码 + ReduceMaxWithDataBlock 归约指数 | __VEC_SCOPE__ |
| sparse_slice | AR, ClearSpr, Compare, CreateMask, DataCopy | MaskReg 作 GatherMask 选择掩码与 SubCarryOut 进位寄存器 | __VEC_SCOPE__ |
