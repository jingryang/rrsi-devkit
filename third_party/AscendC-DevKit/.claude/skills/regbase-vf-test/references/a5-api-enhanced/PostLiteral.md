# PostLiteral

**页面ID:** atlasascendc_api_07_00236  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00236.html

---

```
enum class PostLiteral {
    POST_MODE_NORMAL, // 正常场景，UB操作数地址不更新。LoadUnAlign针对连续非对齐搬入不支持POST_MODE_NORMAL模式。
    POST_MODE_UPDATE  // POST_MODE_UPDATE场景使用，UB地址同时作为输入和输出，每次调用会更新。
};
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 PostLiteral 实例

### 实例 1：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **PostLiteral 调用次数**: 9
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 blockCount 循环中，DataCopy 与 StoreUnAlign 均以 PostLiteral::POST_MODE_UPDATE 加载/存储，使 UB 源地址与临时最大值地址在每次迭代后自动递增，无需手动维护偏移。

（行 866-905）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<xDtype> regA, regB;
    Reg::RegTensor<uint16_t> regU16_0, regU16_1;
    Reg::RegTensor<uint16_t> regU16_2;
    Reg::RegTensor<uint16_t> absMax1Dim2, absMax2Dim2;

    Reg::RegTensor<uint32_t> expAddOne32, extractExp, halfScale;
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
```

**要点**:
- POST_MODE_UPDATE 用于循环搬入/搬出场景，UB 地址同时作输入输出，每次调用后自动更新，省去手动累加偏移。
- DataCopy 的第 2 模板参数填 PostLiteral，配合 LoadDist::DIST_DINTLV_B16 做双寄存器解交错加载。
- StoreUnAlign<uint16_t, POST_MODE_UPDATE> 末参 8 表示每次写出后地址偏移 8 个元素。


### 实例 2：dynamic_mx_quant::Reg::StoreAlign

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskOr, MaskReg, Maxs, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **PostLiteral 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: 在 dynamic_mx_quant 尾轴 fp8 量化的寄存器初始化段，PostLiteral 作为 DataCopy/Store 的模板参数控制 UB 地址在反复搬入搬出时是否自增，配合 CastTrait(MaskMergeMode::ZEROING) 完成 FP32 域缩放计算。

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

**要点**:
- PostLiteral 与 CastTrait、RegLayout、SatMode 同为量化算子模板参数族，共同决定数据搬移与类型转换的地址/饱和/掩码行为。
- 该函数用 ZEROING 模式的 MaskMergeMode，配合 PostLiteral 控制的地址更新策略处理尾轴非对齐尾部。
- 调用次数 2 表明本段内 PostLiteral 出现在加载与存储两处，分别控制读/写方向地址推进。


### 实例 3：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **PostLiteral 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_quant 的 ComputeVF 内，PostLiteral 作为 DataCopyUnAlign/UnAlignPost 系列模板参数，在对 x、smooth_scale 反复搬入与 scale/offset 写出时控制 UB 地址更新，支撑逐 VF 块的动态量化流水。

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

**要点**:
- __aicore__ 函数内嵌 __VEC_SCOPE__，PostLiteral 在内层矢量域使用。
- 与 DataCopyUnAlign + DataCopyUnAlignPost 配对：POST_MODE_UPDATE 逐次推进地址，最后用 UnAlignPost 收尾写回非对齐尾部。
- 配合 DivSpecificMode(ZEROING) 做除法掩码合并，量化 scale/offset 计算与搬移解耦。


### 实例 4：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Max, Min, ReduceMax, RegLayout, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **PostLiteral 调用次数**: 8
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_block_quant 单行 kernel 的矢量段内，PostLiteral（调用 8 次）高频出现在 DataCopy/StoreUnAlign/DataCopyUnAlign 等搬移 API 中，控制按 block 量化时的 UB 地址自增，配合 UnalignRegForStore 处理非对齐存储。

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

**要点**:
- 调用次数 8 表明本段对 PostLiteral 重度依赖，每个 block 的加载/存储都依赖地址自动推进。
- CastTrait 用 RegLayout::ZERO + SatMode::NO_SAT，与 PostLiteral 的地址策略正交，分别管布局/饱和/地址。
- UnalignRegForStore 与 StoreUnAlign/StoreUnAlignPost + POST_MODE_UPDATE 组合实现尾块非对齐写回。


### 实例 5：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub, UnPack
- **PostLiteral 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: swiglu_mx_quant 双轴 regbase 的矢量段，PostLiteral 用于 -1/-2 双轴缩放计算中的 DataCopy/Store，控制 UB 地址在双轴循环中的自动更新，配合 MaskPattern::ALL/VL8/VL16 做块内归约。

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

**要点**:
- 双轴（-1 轴 block 内、-2 轴累积）场景下 PostLiteral 控制两方向地址推进，调用 3 次对应加载与双轴存储。
- 与 ReduceMaxWithDataBlock 配合：先 DataCopy(POST_MODE_UPDATE) 加载，再块内归约求绝对值最大。
- maskReduceB8/VL8、maskReduceB16/VL16 用于 E8M0 scale 的 8/16 元素归约掩码，与 PostLiteral 地址策略独立。


### 实例 6：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **PostLiteral 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: flat_quant 的 ScaleVfcuBLAS SIMD 矢量函数内，PostLiteral 作为单次搬移 API 的模板参数控制 UB 地址更新，配合 UpdateMask(64) 处理 64 元素半块掩码完成 FP32 域缩放。

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

**要点**:
- __simd_vf__ 上下文中 PostLiteral 用法与 __VEC_SCOPE__ 一致，作为 LoadAlign/StoreAlign 的模板参数。
- UpdateMask<uint16_t>(SixtyFour) 限定 64 元素有效宽度，与 PostLiteral 地址推进配合处理半块对齐数据。
- 调用次数 1 表明本段仅一处搬移使用地址更新，其余为寄存器常量初始化。


### 实例 7：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **PostLiteral 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_mx_quant_with_dual_axis 的矢量段，PostLiteral 用于双轴 MX 量化的数据搬入，控制 UB 地址在 -1/-2 轴循环中自动推进，配合 Interleave-with-0 与 Zero 布局处理奇偶列。

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

**要点**:
- 寄存器复用注释详尽（-1 轴 Interleave-with-0、-2 轴 Zero/One 两组），PostLiteral 控制的地址更新是循环推进的基础。
- 调用 1 次对应主数据加载，scale 输出寄存器在循环后复用于 -2 轴。
- absMask/invMax/manMaskFP32 等常量寄存器与 PostLiteral 无关，仅服务于 FP32 缩放计算。


### 实例 8：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **PostLiteral 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: swiglu_mx_quant 非末轴缩放计算中，DataCopy 以 PostLiteral::POST_MODE_UPDATE 为模板参数加载 x0/x1 双寄存器，使 xAddr 在 blockCount 循环里每次自动前进 256 元素，配合 DIST_DINTLV_B16 解交错。

（行 274-313）

```cpp
__aicore__ inline void ComputeScaleCuBLASNotLastAxis(uint16_t blockCount, __ubuf__ T* xAddr,
                                                     __ubuf__ uint8_t* mxScaleAddr,
                                                     __ubuf__ uint16_t* mxScaleReciprocalAddr, uint32_t invDtypeMax)
{
    __VEC_SCOPE__
    {
        Reg::RegTensor<T> x0, x1;
        Reg::RegTensor<uint16_t> absMax0, absMax1;
        Reg::RegTensor<uint16_t> absMax1Dim2, absMax2Dim2;
        Reg::RegTensor<uint32_t> maxFP32_0, maxFP32_1;
        Reg::RegTensor<uint32_t> expFP32_0, expFP32_1;
        Reg::RegTensor<uint32_t> manFP32_0, manFP32_1;
        Reg::RegTensor<uint16_t> scale1B16_0, scale1B16_1;
        Reg::RegTensor<uint16_t> scale1BF16;
        Reg::RegTensor<uint8_t> mxScale1B8;
        Reg::RegTensor<uint8_t> mxScale2B8;

        Reg::RegTensor<uint16_t> absMask;
        Reg::Duplicate(absMask, ABS_MASK_FOR_16BIT);
        Reg::RegTensor<uint32_t> invMax, manMaskFP32;
        Reg::Duplicate(invMax, invDtypeMax);
        Reg::Duplicate(manMaskFP32, MAN_MASK_FLOAT);
        Reg::RegTensor<uint16_t> biasE8M0, nanBF16, specialExp, maxEleBF16;
        Reg::Duplicate(biasE8M0, BF16_EXP_BIAS);
        Reg::Duplicate(nanBF16, NAN_CUSTOMIZATION);
        Reg::Duplicate(specialExp, SPECIAL_EXP_THRESHOLD);
        Reg::Duplicate(maxEleBF16, MAX_EXP_FOR_BF16);

        Reg::Duplicate(absMax1Dim2, 0);
        Reg::Duplicate(absMax2Dim2, 0);

        Reg::MaskReg maskAll = Reg::CreateMask<T, Reg::MaskPattern::ALL>();
        Reg::MaskReg maskB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::ALL>();
        Reg::MaskReg maskFP32 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
        Reg::MaskReg p0, p1, p0Odd, p1Odd, infMask, invalidDataMask;

        for (uint16_t i = 0; i < blockCount; i++) {
            Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
                x0, x1, xAddr, 256);
            Reg::And(absMax0, (Reg::RegTensor<uint16_t>&)x0, absMask, maskAll);
```

**要点**:
- DataCopy 第 2 模板参数为 PostLiteral::POST_MODE_UPDATE，第 3 为 LoadDist，二者共同决定加载地址推进与解交错模式。
- POST_MODE_UPDATE 使 xAddr 每轮自动 +=256，免去循环内手动累加偏移，是 regbase 量化算子的典型加载范式。
- 加载后立即 And 取绝对值掩码，PostLiteral 仅影响地址，不影响数据内容。


### 实例 9：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, RegTensor, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **PostLiteral 调用次数**: 1
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: add_rms_norm_dynamic_mx_quant 的缩放计算函数内，先按 T_Y 是 fp8_e4m3 还是 e5m2 选 dtypeMax，再以 PostLiteral 作为内层搬移 API 模板参数控制 UB 地址在 scale 循环中更新，完成 MX 缩放 E8M0 输出。

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

**要点**:
- if constexpr 按 fp8 子类型选 dtypeMax，与 PostLiteral 地址策略正交，分别管数值上界与搬移地址。
- __aicore__ 函数内 __VEC_SCOPE__ 使用 PostLiteral，体现外层 aicore + 内层矢量域的典型结构。
- 调用 1 次对应 scale 写出或 max 读入，配合 UpdateMask 处理尾块。


### 实例 10：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **PostLiteral 调用次数**: 3
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: rms_norm_dynamic_mx_quant 的缩放计算中，PostLiteral（调用 3 次）用于 max 读入、scale/halfScale 写出的地址控制，在 loopNumScale4NV 循环里自动推进 UB 地址，配合 E8M0 缩放常量完成归一化量化。

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

**要点**:
- 调用 3 次对应读入 + 两次写出（scale 与 halfScale），均用 POST_MODE_UPDATE 逐次推进。
- zeroForAll/Exp254/halfForMan 等 constexpr 常量服务于 FP32 尾数舍入，与 PostLiteral 地址策略无关。
- 仅支持 fp8_e4m3/e5m2（dtypeMax 分支），fp4 量化不支持（dtypeMax=0 注释）。


### 实例 11：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AR, ClearSpr, Compare, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DeInterleave, Duplicate, GatherMask, GatherMaskMode, Interleave, LoadDist, MaskInterleave, MaskReg, RegTensor, SubCarryOut, SubCarryOuts, UnalignReg, UpdateMask
- **PostLiteral 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: sparse_slice 维度切片的矢量段，PostLiteral 用于 DataCopyUnAlign 的地址更新，配合 GatherMask/SubCarryOut 完成稀疏索引的按掩码聚集与非对齐搬出。

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

**要点**:
- 先 ClearSpr<AR>() 清特殊寄存器，PostLiteral 控制的地址推进服务于后续 GatherMask 的索引计算。
- DataCopyUnAlign + POST_MODE_UPDATE 使输出地址 y 随每批聚集结果自动前进，最后 DataCopyUnAlignPost 收尾。
- 与 SubCarryOut/SubCarryOuts 配合处理索引下溢借位，PostLiteral 仅管地址不管数值。


### 实例 12：dynamic_block_mx_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, Compare, CreateMask, Duplicate, Gather, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, Pack, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreAlign, Sub
- **PostLiteral 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: dynamic_block_mx_quant 的矢量段，PostLiteral 用于 DataCopy/Store 的地址控制，配合 Gather 按索引聚集与 ReduceMaxWithDataBlock 块内归约，完成 block 级 MX 缩放。

（行 604-643）

```cpp
__VEC_SCOPE__
{
    Reg::RegTensor<T> x0;
    Reg::RegTensor<T> x1;
    Reg::RegTensor<bfloat16_t> x0BF16;
    Reg::RegTensor<bfloat16_t> x1BF16;
    Reg::RegTensor<uint16_t> x0ExpFP16;
    Reg::RegTensor<uint16_t> x1ExpFP16;
    Reg::RegTensor<uint16_t> x0ExpBF16;
    Reg::RegTensor<uint16_t> x1ExpBF16;
    Reg::RegTensor<uint16_t> expMaxDim;
    Reg::RegTensor<uint16_t> expTmpMaxDim;
    Reg::RegTensor<uint16_t> expMaxDim1;
    Reg::RegTensor<uint16_t> expMax1Dim2;
    Reg::RegTensor<uint16_t> expMax2Dim2;
    Reg::RegTensor<uint16_t> expMaskBF16;
    Reg::RegTensor<uint16_t> expMaskFP16;

    Reg::RegTensor<uint16_t> nanE8M0;
    Reg::RegTensor<uint16_t> biasE8M0;
    Reg::RegTensor<uint16_t> zero;
    Reg::RegTensor<uint16_t> specialExp;
    Reg::RegTensor<uint16_t> nanBF16;
    Reg::RegTensor<uint16_t> mxScaleB16;
    Reg::RegTensor<uint8_t> mxScale1B8;
    Reg::RegTensor<uint8_t> mxScale2B8;
    Reg::RegTensor<uint16_t> yMaxExp;
    Reg::RegTensor<uint16_t> reversedExp;
    Reg::RegTensor<uint16_t> absForX;
    Reg::RegTensor<uint16_t> mantissaForMax;
    Reg::RegTensor<uint8_t> gatherIndex;

    Reg::MaskReg infMask;
    Reg::MaskReg zeroMask;
    Reg::MaskReg infNanDataMask0;
    Reg::MaskReg infNanDataMask1;
    Reg::MaskReg invalidDataMask;

    Reg::MaskReg maskB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::ALL>();
    Reg::MaskReg maskReduceB8 = Reg::CreateMask<uint8_t, Reg::MaskPattern::VL8>();
```

**要点**:
- 调用 2 次对应数据加载与 scale 写出，POST_MODE_UPDATE 使地址逐 block 推进。
- gatherIndex 寄存器 + Gather 用于按 block 索引取值，与 PostLiteral 地址策略正交。
- expMaxDim/expMax1Dim2/expMax2Dim2 体现 -1/-2 双轴指数最大值累积，PostLiteral 支撑其循环搬移。


### 实例 13：swiglu_group_quant::VFComputeMaxExpMXFP4Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **PostLiteral 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: swiglu_group_quant 的 MXFP4 最大指数计算的 SIMD 函数内，LoadAlign 以 PostLiteral::POST_MODE_UPDATE 加载 vdExp0/vdExp1 双寄存器，使 srcAddr 在 loopNum 循环里按 onceXNum 自动前进，配合 invalidDataMask 滤除非法值。

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

**要点**:
- LoadAlign<T, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_DINTLV_B16> 是 regbase 量化加载的三模板参数范式（类型+地址模式+解交错）。
- POST_MODE_UPDATE 使 srcAddr 每次 += onceXNum，scaleMask1 用 UpdateMask(totalCountInUB) 处理尾块有效宽度。
- half/bfloat16 双路径（if constexpr IsSameType<T,half>）做指数提取，PostLiteral 仅控制地址推进。


### 实例 14：broadcast_gradient_args::CalcReduceAxes

- **来源类型**: `__aicore__`
- **共现 API**: AR, Adds, Arange, Cast, ClearSpr, CompareScalar, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, GatherMask, GatherMaskMode, GetSpr, MaskPattern, MaskReg, Pack, RegTensor, UnalignReg, UpdateMask
- **PostLiteral 调用次数**: 2
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: broadcast_gradient_args 的 CalcReduceAxes 内，DataCopyUnAlign 以 PostLiteral::POST_MODE_UPDATE 将 GatherMask 选出的索引写回 y，使 y 地址随每批结果自动前进，配合 DataCopyUnAlignPost 收尾，int64/int32 双路径处理。

（行 75-114）

```cpp
__aicore__ inline int64_t CalcReduceAxes(__local_mem__ T* x, __local_mem__ int32_t* y, uint32_t xLen)
{
    __VEC_SCOPE__
    {
        uint32_t srg0 = xLen;
        Reg::RegTensor<int32_t> init_index_reg, calc_index_reg, x_int32_reg, dst_reg;
        Reg::RegTensor<T> in_reg;
        Reg::UnalignReg ureg;
        Reg::MaskReg maskCompare;
        Reg::MaskReg maskCalc;
        Reg::MaskReg maskAll = Reg::CreateMask<int32_t, Reg::MaskPattern::ALL>();
        Reg::ClearSpr<AscendC::SpecialPurposeReg::AR>();
        Reg::Arange(init_index_reg, 0);
        if constexpr (IsSameType<T, int64_t>::value) {
            for (uint16_t i = 0; i < vLoopInt64; i++) {
                Reg::Adds(calc_index_reg, init_index_reg, i * vlInt64, maskAll);
                Reg::DataCopy(in_reg, x + i * vlInt64);
                maskCalc = Reg::UpdateMask<int64_t>(srg0);
                // mask未选择位置会置0，对尾块无影响
                Reg::Cast<int32_t, int64_t, castTraitB642B32>(x_int32_reg, in_reg, maskCalc);
                Reg::Pack((Reg::RegTensor<uint32_t>&)x_int32_reg,
                               (Reg::RegTensor<uint64_t>&)x_int32_reg);
                Reg::CompareScalar<int32_t, CMPMODE::EQ>(maskCompare, x_int32_reg, 1, maskAll);
                Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(dst_reg, calc_index_reg,
                                                                                   maskCompare);
                Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(y, dst_reg, ureg);
            }
        } else {
            for (uint16_t i = 0; i < vLoopT; i++) {
                maskCalc = Reg::UpdateMask<int32_t>(srg0);
                Reg::Adds(calc_index_reg, init_index_reg, i * vlInput, maskAll);
                Reg::DataCopy(in_reg, x + i * vlInput);
                Reg::CompareScalar<int32_t, CMPMODE::EQ>(maskCompare, in_reg, 1, maskCalc);
                Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(dst_reg, calc_index_reg,
                                                                                   maskCompare);
                Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(y, dst_reg, ureg);
            }
        }
        Reg::DataCopyUnAlignPost(y, ureg);
    }
```

**要点**:
- DataCopyUnAlign<int32_t, PostLiteral::POST_MODE_UPDATE>(y, dst_reg, ureg) —— y 地址每次写出后自动 += 实际写出元素数。
- GatherMask 按比较掩码聚集索引，PostLiteral 仅控制输出地址，聚集逻辑由 GatherMaskMode::STORE_REG 决定。
- 尾块用 UpdateMask<int64_t/int32_t>(srg0) 限定有效宽度，循环结束 DataCopyUnAlignPost(y, ureg) 写回非对齐余数。


### 实例 15：arg_max_with_value::HardEvent::V_MTE3

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, MaskPattern, MaskReg, Mul, ReduceMax, ReduceMin, RegTensor, RegTraitNumTwo, Select, UnalignReg, UpdateMask
- **PostLiteral 调用次数**: 5
- **参数模式**: `T0_A0_M0_TYPEnone`（实参 0 个）
- **语义**: arg_max_with_value 的矢量段（ops-math 仓），PostLiteral（调用 5 次）高频用于 DataCopyUnAlignPre/DataCopyUnAlign 的地址更新，使 src 在 dimA×loopTime 双层循环里按 VL 自动推进，配合 RegTraitNumTwo 双元素寄存器做带索引的 argmax 归约。

（行 203-240）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<T1, AscendC::Reg::RegTraitNumTwo> value0, value1, valueResult;
    AscendC::Reg::RegTensor<T2, AscendC::Reg::RegTraitNumTwo> level0, level1, indexResult, helpIndex, indexMulResult, indexAddResult;

    AscendC::Reg::MaskReg fullMask = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg tailMask = AscendC::Reg::UpdateMask<uint32_t>(tailSize);
    AscendC::Reg::MaskReg oneMask = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::VL1>();
    AscendC::Reg::MaskReg cmpMask;

    AscendC::Reg::Duplicate(helpIndex, VALUE_ONE, fullMask);
    vdup((AscendC::Reg::RegTensor<uint32_t>&)helpIndex.reg[0], VL, oneMask, MODE_MERGING);

    // 用于加法的寄存器
    AscendC::Reg::RegTensor<T2, AscendC::Reg::RegTraitNumTwo> vregIndicesAdd1, vregIndicesAddStartR;
    AscendC::Reg::Duplicate(vregIndicesAdd1, VALUE_ONE, fullMask);
    AscendC::Reg::Duplicate(vregIndicesAddStartR, startR, fullMask);

    // 主块, 载入i片数据，初始化i片索引
    AscendC::Reg::UnalignReg uValue, uIndex, uSrc;
    AscendC::Reg::DataCopyUnAlignPre(uSrc, (__local_mem__ T1*&)src);
    for (uint16_t a = 0; a < dimA; a++) {
        AscendC::Reg::DataCopyUnAlign<T1, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(value0, uSrc, (__local_mem__ T1*&)src, offset1);
        AscendC::Reg::Duplicate(level0, VALUE_ZERO, fullMask);
        AscendC::Reg::Duplicate(level1, VALUE_ZERO, fullMask);
        // 载入i+1片数据，初始化i+1片索引，比较 i and i+1
        for (uint16_t r = 0; r < loopTime; r++) {
            AscendC::Reg::DataCopyUnAlign<T1, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(value1, uSrc, (__local_mem__ T1*&)src, VL);
            // 微指令 AscendC::Reg::Duplicate(level1, r + 1, fullMask);
            Add(level1, level1, vregIndicesAdd1, fullMask);
            if constexpr (isMin) {
                AscendC::Reg::Compare<T1, CMPMODE::LE>(cmpMask, value0, value1, fullMask);
            } else {
                AscendC::Reg::Compare<T1, CMPMODE::GE>(cmpMask, value0, value1, fullMask);
            }
            AscendC::Reg::Select(value0, value0, value1, cmpMask);
            AscendC::Reg::Select(level0, level0, level1, cmpMask);
        }
```

**要点**:
- DataCopyUnAlignPre(uSrc, src) 预取 + DataCopyUnAlign<T1, POST_MODE_UPDATE>(value0, uSrc, src, offset1) 主加载，POST_MODE_UPDATE 使 src 每次自动 += VL/offset1。
- 调用 5 次覆盖预取、主块加载、相邻块加载等多处地址推进，是 argmax 流水的核心。
- Compare(GE/LE) + Select 更新 value0/level0，PostLiteral 只管读地址，极值与索引由比较选择逻辑维护。


### PostLiteral 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Arange, Cast | DataCopy/StoreUnAlign + POST_MODE_UPDATE，循环内 UB 地址自动递增 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | CastTrait(ZEROING) + PostLiteral 控制尾轴 fp8 量化搬移地址 | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | DataCopyUnAlign + POST_MODE_UPDATE + UnAlignPost 收尾，逐 VF 块动态量化 | __aicore__ |
| dynamic_block_quant | And, Cast, CastTrait, CompareScalar, CreateMask | 高频(8次) PostLiteral 控制 block 量化加载/非对齐存储地址 | __VEC_SCOPE__ |
| swiglu_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 双轴缩放 DataCopy + POST_MODE_UPDATE + ReduceMaxWithDataBlock 归约 | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | __simd_vf__ 单次 LoadAlign/StoreAlign + POST_MODE_UPDATE + UpdateMask(64) 半块 | __simd_vf__ |
| dynamic_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 双轴 MX 量化主数据加载 + POST_MODE_UPDATE + Interleave-with-0 | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | DataCopy<T,POST_MODE_UPDATE,DIST_DINTLV_B16>(x0,x1) 循环加载 256 元素 | __aicore__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | __aicore__+__VEC_SCOPE__，按 fp8 子类型选 dtypeMax，PostLiteral 控制 scale 循环搬移 | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | 读入 + scale/halfScale 双写出(3次) + POST_MODE_UPDATE 逐次推进 | __aicore__ |
| sparse_slice | AR, ClearSpr, Compare, CreateMask, DataCopy | DataCopyUnAlign + POST_MODE_UPDATE + GatherMask 稀疏索引聚集搬出 | __VEC_SCOPE__ |
| dynamic_block_mx_quant | And, Cast, Compare, CreateMask, Duplicate | DataCopy/Store + POST_MODE_UPDATE + Gather + ReduceMaxWithDataBlock 归约 | __VEC_SCOPE__ |
| swiglu_group_quant | And, Cast, CastTrait, Compare, Duplicate | LoadAlign<T,POST_MODE_UPDATE,DIST_DINTLV_B16> + UpdateMask 尾块 + 指数提取 | __simd_vf__ |
| broadcast_gradient_args | AR, Adds, Arange, Cast, ClearSpr | DataCopyUnAlign<int32_t,POST_MODE_UPDATE> 写回聚集索引 + UnAlignPost 收尾 | __aicore__ |
| arg_max_with_value | Compare, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre | DataCopyUnAlignPre + DataCopyUnAlign<T1,POST_MODE_UPDATE> 双层循环 argmax 流水 | __VEC_SCOPE__ |
