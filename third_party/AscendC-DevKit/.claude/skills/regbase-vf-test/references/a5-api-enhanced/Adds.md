# Adds

**页面ID:** atlasascendc_api_07_0382  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0382.html

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

矢量内每个元素与标量求和，计算公式如下，其中VL_T表示矢量计算单元一个迭代能够处理的元素个数。VL_T的取值参考RegTensor。

![](images/atlasascendc_api_07_0382_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, typename U, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void Adds(S& dstReg, S& srcReg, U scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 矢量目的操作数和源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/half/bfloat16_t/int32_t/uint32_t/float/complex32/int64_t/uint64_t/complex64 |
| U | 标量源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/half/bfloat16_t/int32_t/uint32_t/float/complex32/int64_t/uint64_t/complex64 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dstReg中置零。- MERGING，暂不支持。 |
| S | dstReg RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void AddsVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, T scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    ;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Adds(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Adds 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Max, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Adds 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 在 dynamic_mx_quant FP8 量化中，提取 FP32 指数后用 Adds 对指数加 1，再通过 Select 实现 MX quant scale 的条件舍入（normal 与 subnormal 场景）。

（行 511-528）

```cpp
Reg::Duplicate(invMaxRegTensor, FP8_DEFAULT_MAX_EXP);
// 右移获取指数位
Reg::ShiftRights(expFP32RegTensor, maxFP32RegTensor, FP32_SHR_NUM, mask);
// And获取尾数位
Reg::And(manFP32RegTensor, maxFP32RegTensor, manFP32RegTensor, mask);

Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, expFP32RegTensor, FP32_NUMBER_ZERO, mask);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0, expFP32RegTensor, FP32_NUMBER_254, p0);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, manFP32RegTensor, FP32_NUMBER_ZERO, p0);

Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, expFP32RegTensor, FP32_NUMBER_ZERO, mask);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manFP32RegTensor, FP32_NUMBER_HALF, p1);

Reg::MaskOr(p0, p0, p1, mask);
Reg::Adds(extractExpRegTensor, expFP32RegTensor, 1, mask);
// 根据情况选择指数位是否加一
Reg::Select<uint32_t>(extractExpRegTensor, extractExpRegTensor, expFP32RegTensor, p0);
```

**要点**:
- scalarValue 取整数 1，作用于 uint32 视图下的 FP32 指数域。
- 配合 CompareScalar 生成 predicate p0/p1，由 Select 决定是否采用 exp+1 的舍入结果。
- mask 采用 ZEROING 模式，未选中元素在目的寄存器中置零。

### 实例 2：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, LoadAlign, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Adds 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: grouped_dynamic_mx_quant 对分组量化提取的 FP32 指数做条件加 1（向上取整），配合 MaskAnd/MaskXor/Select 处理 subnormal 与 INF/NaN 异常值。

（行 587-605）

```cpp
// 5. 提取 Exp 和 Man
Reg::ShiftRights(expAndreShareExpFP32RegTensor, expMaxAndAddOneFP32RegTensor, SHR_NUM_FOR_FP32,
                 preMaskScale);
Reg::And(manAndmxScaleFP32RegTensor, expMaxAndAddOneFP32RegTensor, manMaskFP32Reg, preMaskScale);
// 6. 条件向上取整
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, expAndreShareExpFP32RegTensor, NUMBER_ZERO, preMaskScale);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p2, expAndreShareExpFP32RegTensor, NUMBER_TWO_FIVE_FOUR,
                                          preMaskScale);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p3, manAndmxScaleFP32RegTensor, NUMBER_ZERO, preMaskScale);
Reg::MaskAnd(p1, p1, p2, preMaskScale);
Reg::MaskAnd(p1, p1, p3, preMaskScale);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p2, expAndreShareExpFP32RegTensor, NUMBER_ZERO, preMaskScale);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p3, manAndmxScaleFP32RegTensor, NUMBER_HALF, preMaskScale);
Reg::MaskAnd(p2, p2, p3, preMaskScale);
Reg::MaskXor(p1, p1, p2, preMaskScale);
Reg::Adds(expMaxAndAddOneFP32RegTensor, expAndreShareExpFP32RegTensor, 1, preMaskScale);
Reg::Select(manAndmxScaleFP32RegTensor, expMaxAndAddOneFP32RegTensor, expAndreShareExpFP32RegTensor, p1);
// 7. 异常值处理
Reg::Select<uint32_t>(manAndmxScaleFP32RegTensor, manAndmxScaleFP32RegTensor, fp8NanRegTensor32, infMask);
```

**要点**:
- 第 4 参数为 preMaskScale（MaskReg），区别于实例 1 的小写 mask 变量，对应 MASKMask 模式签名。
- Adds 调用 4 次，对应分组量化中多路指数的独立条件加 1。
- subnormal 与异常值通过 Select 兜底为 fp8NanRegTensor32，infMask 路由 INF 路径。

### 实例 3：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Adds 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEint32_t+uint32_t_MASKmask`（实参 4 个，含 mask/mode: mask，类型: int32_t, uint32_t）
- **语义**: swiglu_backward 双轴量化中对 uint32 指数域加 1，配合 Select 与 fp8Nan/zero 寄存器处理 INF/NaN/零值特殊路径。

（行 941-959）

```cpp
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, (Reg::RegTensor<uint32_t>&)regB,
                                               static_cast<uint32_t>(0), maskAll32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, (Reg::RegTensor<uint32_t>&)regB, EXP_254,
                                               maskAll32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, (Reg::RegTensor<uint32_t>&)regU16_1,
                                               static_cast<uint32_t>(0), maskAll32);
Reg::MaskAnd(p0, p0, p1, maskAll32);
Reg::MaskAnd(p0, p0, p2, maskAll32);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, (Reg::RegTensor<uint32_t>&)regB,
                                               static_cast<uint32_t>(0), maskAll32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, (Reg::RegTensor<uint32_t>&)regU16_1, HALF_FOR_MAN,
                                               maskAll32);
Reg::MaskAnd(p1, p1, p2, maskAll32);
Reg::MaskOr(p0, p0, p1, maskAll32);

Reg::Adds(expAddOne32, (Reg::RegTensor<uint32_t>&)regB, 1, maskAll32);
Reg::Select(extractExp, expAddOne32, (Reg::RegTensor<uint32_t>&)regB, p0);
Reg::Select<uint32_t>(extractExp, extractExp, fp8NanReg32, cmpResult);
Reg::Select<uint32_t>(extractExp, extractExp, zeroReg32, zeroMask);
```

**要点**:
- 模板/类型上下文含 int32_t 与 uint32_t，Adds 操作 uint32 视图的 FP32 指数位域，是本批实例中唯一带显式类型 token 的 mask 调用。
- maskAll32 为全 1 MaskReg，条件分支完全由 Select 链处理。
- INF/NaN/zero 三类特殊值分别通过 cmpResult、p0、zeroMask 路由到对应寄存器。

### 实例 4：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Adds 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: dynamic_quant 计算 PerTensor 量化的 offset：对 -max/scale 用 Adds 叠加 offsetValue 得到偏移标量并写回。

（行 377-395）

```cpp
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
```

**要点**:
- 第 4 参数 preg5 为全有效 predicate（M0 模式，无 mask token），Adds 用于 offset = -max/scale + offsetValue 的标量平移。
- 与 Muls 配合：先 Muls(...,NEGATIVE_ONE) 取负，再 Adds 叠加 offsetValue 得到量化偏移。
- 结果通过 DataCopyUnAlign + POST_MODE_UPDATE 写回 offsetAddr。

### 实例 5：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Adds 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: flat_quant 在 simd_vf 上下文中提取 FP32 指数后加 1，配合 Select 处理 fp4 格式的 NaN 与零值特殊值。

（行 508-526）

```cpp
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
```

**要点**:
- 来源类型 __simd_vf__，调用形式为 AscendC::Reg::Adds，与本批多数 __aicore__/__VEC_SCOPE__ 实例不同。
- 对 fp4 量化提取的指数加 1，NaN 用 fp4NanRegTensor 兜底（区别于 fp8 实例的 fp8Nan）。
- mask 为 preMaskScale（MaskMergeMode），对应 MASKMask 模式签名。

### 实例 6：dynamic_mx_quant::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Max, Maxs, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub
- **Adds 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: dynamic_mx_quant 高性能大尾分支中，用比较结果 predicate(p0) 作为第 4 参数对 mxScale 指数条件加 1（MODE_ONE 舍入），不使用 MaskReg。

（行 456-465）

```cpp
if constexpr (calcMode == MODE_ONE) {
    Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, mxScale0FP32, FP32_NUMBER_ZERO, pregAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1, manAbs0FP32, FP32_NUMBER_HALF, p1);
    Reg::MaskXor(p0, p0, p1, pregAll32);
}

Reg::Adds(manAbs0FP32, mxScale0FP32, 1, p0);
Reg::Select(mxScale0FP32, manAbs0FP32, mxScale0FP32, p0);

Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint16_t>&)mxScale0BF16, mxScale0FP32);
```

**要点**:
- 第 4 参数为 predicate 寄存器 p0（比较结果），非 MaskReg——条件加 1 由 p0 选通，是“predicate 作 mask”的典型写法。
- MODE_ONE 分支：先判断 mxScale==0 且 man>0.5 再决定加 1，MaskXor 翻转条件。
- 无 mask token（M0 模式），pregAll32 仅用于 CompareScalar 的全有效选通。

### 实例 7：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Adds 调用次数**: 8
- **参数模式**: `T1_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: fake_quant 显式使用 <float> 模板：Adds 构造 vregOne/vregQRange 常量、对 zpClipped 加 0.5f 实现向下取整、对 nudged_min/max 平移 qMin/qMax。

**片段 1** (行 371-387):

```cpp
AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(vregMin, minAddr + i * vfLen32);
AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(vregMax, maxAddr + i * vfLen32);

// -----------------------------------------------------------------
// 阶段 2：Prepare 重算（替代 PrepareChannelScalarsForSegment）
// -----------------------------------------------------------------

// 2.0 构造常量 vregZero / vregOne / vregQRange（寄存器内）
AscendC::Reg::Sub<float>(vregZero, vregMin, vregMin, mask);
AscendC::Reg::Adds<float>(vregOne, vregZero, 1.0f, mask);
AscendC::Reg::Adds<float>(vregQRange, vregZero, qRange, mask);

// 2.1 scale = (max - min) / qRange
//     用 0-ULP Div 替代 (max-min)*invR：避免 invR=1/(qMax-qMin) 在 fp32 上的
//     round-to-nearest 误差与 (max-min)*invR 的舍入叠加，使 scale 精确等于
//     `(max-min)/(qMax-qMin)` 的 IEEE 单步除法结果（与 TF 实现一致）。
AscendC::Reg::Sub<float>(vregScale, vregMax, vregMin, mask);
```

**片段 2** (行 420-434):

```cpp
AscendC::Reg::Mins<float, float, AscendC::Reg::MaskMergeMode::ZEROING>(vregZpClipped, vregZpClipped, qMax,
                                                                       mask);
AscendC::Reg::Adds<float>(vregZpClipped, vregZpClipped, 0.5f, mask);
AscendC::Reg::Cast<int32_t, float, kCastFp32ToInt32Floor>(vregZpInt, vregZpClipped, mask);
AscendC::Reg::Cast<float, int32_t, kCastInt32ToFp32>(vregNudgedZp, vregZpInt, mask);

// 2.6 nudged_min = (qMin - nudged_zp) * scaleSafe
//     nudged_max = (qMax - nudged_zp) * scaleSafe
AscendC::Reg::Muls<float>(vregNudgedMin, vregNudgedZp, -1.0f, mask);
AscendC::Reg::Adds<float>(vregNudgedMin, vregNudgedMin, qMin, mask);
AscendC::Reg::Mul<float>(vregNudgedMin, vregNudgedMin, vregScaleSafe, mask);

AscendC::Reg::Muls<float>(vregNudgedMax, vregNudgedZp, -1.0f, mask);
AscendC::Reg::Adds<float>(vregNudgedMax, vregNudgedMax, qMax, mask);
AscendC::Reg::Mul<float>(vregNudgedMax, vregNudgedMax, vregScaleSafe, mask);
```

**要点**:
- 显式 <float> 模板参数，scalarValue 为浮点字面量 1.0f/0.5f 与 qRange/qMin/qMax，是本批唯一带模板类型 token 的实例。
- 用于构造常量(vregOne/vregQRange)与零点取整(zpClipped+0.5f 后 Cast floor 取整)。
- 多次 Adds 完成 nudged_min/max 的平移，刻意避免 invR 舍入叠加误差以与 TF 实现对齐。

### 实例 8：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Adds 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: swiglu_mx_quant 非末轴 scale 计算中，对两路 FP32 指数分别加 1 后 Select+Pack+Interleave 交错打包成 B16 scale。

（行 332-350）

```cpp
Reg::Adds(maxFP32_0, expFP32_0, 1, maskFP32);
Reg::Select(manFP32_0, maxFP32_0, expFP32_0, p0);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_0, manFP32_0);
Reg::Cast<float, T, CAST_ONE>((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<T>&)absMax1Dim2,
                                   maskAll);
Reg::Mul((Reg::RegTensor<float>&)maxFP32_1, (Reg::RegTensor<float>&)maxFP32_1,
              (Reg::RegTensor<float>&)invMax, maskFP32);
Reg::ShiftRights(expFP32_1, maxFP32_1, SHR_NUM_FOR_FP32, maskFP32);
Reg::And(manFP32_1, maxFP32_1, manMaskFP32, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, expFP32_1, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0Odd, expFP32_1, EXP_254, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, manFP32_1, ZERO_FOR_ALL, p0Odd);
Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1Odd, expFP32_1, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p1Odd, manFP32_1, SPECIAL_EXP_THRESHOLD_FP32, p1Odd);
Reg::MaskOr(p0Odd, p0Odd, p1Odd, maskFP32);
Reg::Adds(maxFP32_1, expFP32_1, 1, maskFP32);
Reg::Select(manFP32_1, maxFP32_1, expFP32_1, p0Odd);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale1B16_1, manFP32_1);
Reg::Interleave(scale1B16_0, scale1B16_1, scale1B16_0, scale1B16_1);
```

**要点**:
- 双路(expFP32_0/expFP32_1)独立 Adds 加 1，配合 Pack+Interleave 交错为 B16，体现双轴量化 scale 打包。
- Adds 调用 8 次，odd 链复用 maxFP32_1 寄存器作为 expPlusOne 中间量以减少寄存器占用。
- maskFP32 为标量全有效 mask，subnormal 阈值用 SPECIAL_EXP_THRESHOLD_FP32。

### 实例 9：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: And, Cast, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Adds 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: add_rms_norm_dynamic_mx_quant 在 RMSNorm 后的 MX quant scale 提取中，对 FP32 指数加 1 并通过 Select 处理 fp8 NaN/零值。

（行 467-485）

```cpp
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
```

**要点**:
- norm+quant 融合算子，Adds 对 FP32 指数加 1 实现 MX quant scale 的条件舍入。
- 与 flat_quant 实例同构，但 mask 命名 preMaskScale、NaN 寄存器为 fp8NanRegTensor、常量前缀 CUBLAS_。
- zeroMask 由 Compare NE 生成，零值元素置零避免 scale 退化。

### 实例 10：dynamic_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Cast, CreateMask, DataCopy, Div, DivSpecificMode, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Max, Min, Mul, Muls, ReduceMax, ReduceMin, RegTensor, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **Adds 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: dynamic_quant 大形状 isFinal 分支计算量化 offset：对 -max/scale 用 Adds 叠加 offsetMaxValue，使用 RegTraitNumOne 单元素寄存器仅存首元素。

（行 512-534）

```cpp
if constexpr (isFinal) {
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg9;
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg10;
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg11;
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg12;
    AscendC::Reg::RegTensor<float, Reg::RegTraitNumOne> vreg13;
    AscendC::Reg::Sub(vreg9, vregMax, vregMin, maskAll);
    AscendC::Reg::Muls(vreg10, vreg9, scaleMaxValue, maskAll); // scale

    AscendC::Reg::Div<float, &mode>(vreg11, vregMax, vreg10, maskAll);
    AscendC::Reg::Muls(vreg12, vreg11, -1, maskAll);
    AscendC::Reg::Adds(vreg13, vreg12, offsetMaxValue, maskAll); // offset

    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        maxLocalAddr, vreg10, maskAll);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        minLocalAddr, vreg13, maskAll);
} else {
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        maxLocalAddr, vregMax, maskAll);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        minLocalAddr, vregMin, maskAll);
}
```

**要点**:
- isFinal 分支：Adds 计算 offset = -max/scale + offsetMaxValue，与实例 4 同语义但走 maskAll（MASKmask）路径。
- 使用 RegTraitNumOne 单元素寄存器，结果以 DIST_FIRST_ELEMENT_B32 仅存首元素（PerTensor 标量）。
- maskAll 为全有效 MaskReg，非 isFinal 分支直接存 max/min 不再算 offset。

### 实例 11：dynamic_mx_quant::Reg::Select

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, And, Cast, CastTrait, Compare, CreateMask, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, Max, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, Sub
- **Adds 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: dynamic_mx_quant 在 FP32→BF16 pack 前，提取舍入位后用 Adds 加 0x7FFF 舍入偏置，再 Add 回 maxU32 实现四舍五入。

（行 613-623）

```cpp
if constexpr (IsSame<xDtype, float>::value) {
    Reg::ShiftRights(roundBiasU32, maxU32, FP32_PACK_SHR_NUM, pregAll32);
    Reg::And(roundBiasU32, roundBiasU32, oneU32, pregAll32);
    Reg::Adds(roundBiasU32, roundBiasU32, 0x7FFF, pregAll32);
    Reg::Add(maxU32, maxU32, roundBiasU32, pregAll32);
    Reg::ShiftRights(maxU32, maxU32, FP32_PACK_SHR_NUM, pregAll32);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(maxU16, maxU32);
    Reg::And(expMaxU16, maxU16, maxEleU16, pregAll16);
} else {
    Reg::And(expMaxU16, maxU16, maxEleU16, pregAll16);
}
```

**要点**:
- FP32→BF16 舍入：先 ShiftRights 取舍入位，Adds 加 0x7FFF 偏置后 Add 回主值实现就近舍入。
- scalarValue 取 0x7FFF（BF16 尾数半单位），是 Adds 用于整数位域运算的典型场景。
- 第 4 参数 pregAll32 为全有效，无 mask token（M0 模式），仅 IsSame<xDtype,float> 分支执行。

### 实例 12：tanh::TanhCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, And, Cast, CompareScalar, DataCopy, Div, Duplicate, Exp, FusedMulDstAdd, LoadDist, MaskReg, Mul, Muls, Or, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Adds 调用次数**: 12
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: tanh 用有理多项式逼近：Adds 叠加多项式常数项（如 -0.052），并在 exp 路径用 Adds(...,FP32_ONE) 构造 1+e^{2|x|} 分母。

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

**要点**:
- 多项式逼近中 Adds 叠加常数项（FP32_ZERO_NEG_052 等）构造奇数次有理多项式。
- exp 路径两次 Adds(...,FP32_ONE) 构造 1+e^{2|x|}，进而得 2/(1+e^{2|x|})-1 的 tanh 近似。
- RegTraitNumOne 单元素寄存器，mask 由 UpdateMask 按尾块 count 生成。

### 实例 13：broadcast_gradient_args::CalcReduceAxes

- **来源类型**: `__aicore__`
- **共现 API**: AR, Arange, Cast, ClearSpr, CompareScalar, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, GatherMask, GatherMaskMode, GetSpr, MaskPattern, MaskReg, Pack, PostLiteral, RegTensor, UnalignReg, UpdateMask
- **Adds 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: broadcast_gradient_args 在循环中用 Adds(calc_index_reg, init_index_reg, i*vlInt64, maskAll) 生成等差索引序列，供 GatherMask 收集广播轴梯度。

**片段 1** (行 89-101):

```cpp
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
```

**片段 2** (行 103-111):

```cpp
for (uint16_t i = 0; i < vLoopT; i++) {
    maskCalc = Reg::UpdateMask<int32_t>(srg0);
    Reg::Adds(calc_index_reg, init_index_reg, i * vlInput, maskAll);
    Reg::DataCopy(in_reg, x + i * vlInput);
    Reg::CompareScalar<int32_t, CMPMODE::EQ>(maskCompare, in_reg, 1, maskCalc);
    Reg::GatherMask<int32_t, Reg::GatherMaskMode::STORE_REG>(dst_reg, calc_index_reg,
                                                                       maskCompare);
    Reg::DataCopyUnAlign<int32_t, Reg::PostLiteral::POST_MODE_UPDATE>(y, dst_reg, ureg);
}
```

**要点**:
- 循环内 Adds 生成等差索引：init_index_reg + i*vl，步长随循环变量变化，是 Adds 用于索引算术的典型场景。
- 第 4 参数 maskAll 为全有效，对尾块无影响（mask 未选位置置 0）。
- 配合 GatherMask 收集值为 1 的轴索引，实现广播梯度 reduce_axes 计算。

### 实例 14：clipped_swiglu::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Cast, CreateAddrReg, CreateMask, DataCopy, DeInterleave, Div, Exp, LoadDist, MaskPattern, MaskReg, Maxs, Mins, Mul, Muls, RegTensor, StoreDist, UpdateMask
- **Adds 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: clipped_swiglu 激活函数中，Adds(expReg, expReg, scalarOne) 构造 1+e^{-α·min(x,clamp)} 分母，Adds(vregX2DeF, vregX2DeF, gluBias) 给 GLU 路径加偏置。

**片段 1** (行 372-412):

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

**要点**:
- Adds(expReg, expReg, scalarOne) 构造 sigmoid 分母 1+e^{-α·min(x,clamp)}，是激活函数中 Adds 叠加常量 1 的典型用法。
- Adds(vregX2DeF, vregX2DeF, gluBias) 给 GLU 第二路加偏置后再 Mul 得输出。
- mask 处理尾块，Mins/Maxs 做 clamp 限幅保证数值稳定。

### 实例 15：max_pool_with_argmax::MaxPoolWithArgMaxGatherImpl

- **来源类型**: `__aicore__`
- **共现 API**: Add, Cast, Compare, CreateMask, DataCopyGather, DataCopyScatter, Duplicate, MaskNot, MaskOr, MaskPattern, MaskReg, MaskUnPack, Muls, Pack, RegTensor, Select, UpdateMask
- **Adds 调用次数**: 16
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: max_pool_with_argmax 用 Adds 累加 H/W 起始偏移、kernel 偏移与 pad 修正，生成 gather 读取索引与 scatter 写回索引。

**片段 1** (行 76-128):

```cpp
Reg::MaskReg maskAllT2 = Reg::CreateMask<T2, Reg::MaskPattern::ALL>();
Reg::MaskReg flagMask = Reg::CreateMask<T2, Reg::MaskPattern::ALLF>(); // 标志是否更新过最大值

Reg::Adds(argmaxHRes, argmaxHStart, argmaxHOffset, computeT2);
Reg::Adds(argmaxWRes, argmaxWStart, argmaxWOffset, computeT2);

for (uint16_t hIdx = 0; hIdx < kH; hIdx++) {
    int32_t hKernelOffset = hIdx * rowStrideInUb;
    T2 argmaxHKernelOffset = hIdx + argmaxHOffset;

    for (uint16_t wIdx = 0; wIdx < kW; wIdx++) {
        int32_t wKernelOffset = wIdx * alignedC;
        T2 argmaxWKernelOffset = wIdx + argmaxWOffset;

        int32_t gatterIndexOffsetTotal = gatterIndexOffset + hKernelOffset + wKernelOffset;
        Reg::Adds(gatterIndexReg, gatterStartIdx, gatterIndexOffsetTotal, computeU32);

        if constexpr (std::is_same<T1, float>::value) {
            Reg::DataCopyGather(vd1, xAddr, gatterIndexReg, computeT1);
        } else {
            Reg::Cast<uint16_t, uint32_t, castTraitU32U16>(gatterIdxU16Reg, gatterIndexReg, computeU32);
            Reg::Pack(gatterIdxU16Reg, (Reg::RegTensor<uint32_t>&)gatterIdxU16Reg);
            Reg::DataCopyGather(vd1, xAddr, gatterIdxU16Reg, computeT1);
        }

        if constexpr (NANPROP == 1) {
            Reg::Compare<T1, CMPMODE::LE>(gtMask, vd1, vd0, computeT1);
            Reg::MaskNot(gtMask, gtMask, computeT1);
        } else {
            Reg::Compare<T1, CMPMODE::GT>(gtMask, vd1, vd0, computeT1);
        }

        Reg::Adds(argmaxUpdateHVreg, argmaxHStart, argmaxHKernelOffset, computeT2);
        Reg::Adds(argmaxUpdateWVreg, argmaxWStart, argmaxWKernelOffset, computeT2);
        if constexpr (sizeof(T2) / sizeof(T1) == 1) {
            Reg::Select(argmaxHRes, argmaxUpdateHVreg, argmaxHRes, gtMask);
            Reg::Select(argmaxWRes, argmaxUpdateWVreg, argmaxWRes, gtMask);
            Reg::MaskOr(flagMask, flagMask, gtMask, computeT2);
        } else if constexpr (sizeof(T2) / sizeof(T1) == DOUBLE) {
            Reg::MaskUnPack(gtMaskT2, gtMask);
            Reg::Select(argmaxHRes, argmaxUpdateHVreg, argmaxHRes, gtMaskT2);
            Reg::Select(argmaxWRes, argmaxUpdateWVreg, argmaxWRes, gtMaskT2);
            Reg::MaskOr(flagMask, flagMask, gtMaskT2, computeT2);
        } else {
            Reg::MaskUnPack(gtMaskT2, gtMask);
            Reg::MaskUnPack(gtMaskT4, gtMaskT2);
            Reg::Select(argmaxHRes, argmaxUpdateHVreg, argmaxHRes, gtMaskT4);
            Reg::Select(argmaxWRes, argmaxUpdateWVreg, argmaxWRes, gtMaskT4);
            Reg::MaskOr(flagMask, flagMask, gtMaskT4, computeT2);
        }
        Reg::Select(vd0, vd1, vd0, gtMask);
    }
}
```

**片段 2** (行 130-163):

```cpp
if constexpr (IS_PAD == 1) {
    // 修正argmax
    Reg::Adds(argmaxHRes, argmaxHRes, -padH, computeT2);
    Reg::Adds(argmaxWRes, argmaxWRes, -padW, computeT2);

    Reg::MaskReg hMask;
    Reg::MaskReg wMask;
    Reg::RegTensor<T2> argmaxZero;
    Reg::Duplicate(argmaxZero, 0);

    Reg::Compare<T2, CMPMODE::GE>(hMask, argmaxHRes, argmaxZero, computeT2);
    Reg::Select(argmaxHRes, argmaxHRes, argmaxZero, hMask);
    Reg::Compare<T2, CMPMODE::GE>(wMask, argmaxWRes, argmaxZero, computeT2);
    Reg::Select(argmaxWRes, argmaxWRes, argmaxZero, wMask);
}

Reg::RegTensor<T2> argmaxRes;
Reg::Muls(argmaxRes, argmaxHRes, wInput, computeT2);
Reg::Add(argmaxRes, argmaxRes, argmaxWRes, computeT2);
Reg::Muls(argmaxRes, argmaxRes, cInput, computeT2);
Reg::Add(argmaxRes, argmaxRes, argmaxCStart, computeT2);
// 最大值从未更新过对应索引修正为-1
Reg::Select(argmaxRes, argmaxRes, neg1Res, flagMask);

Reg::Adds(scatterIndexReg, scatterStartIdx, scatterOffset, computeU32);

Reg::DataCopyScatter(argmaxAddr, argmaxRes, scatterIndexReg, computeT2);
if constexpr (std::is_same<T1, float>::value) {
    Reg::DataCopyScatter(maxValueAddr, vd0, scatterIndexReg, computeT1);
} else {
    Reg::Cast<uint16_t, uint32_t, castTraitU32U16>(scatterIdxU16Reg, scatterIndexReg, computeU32);
    Reg::Pack(scatterIdxU16Reg, (Reg::RegTensor<uint32_t>&)scatterIdxU16Reg);
    Reg::DataCopyScatter(maxValueAddr, vd0, scatterIdxU16Reg, computeT1);
}
```

**要点**:
- Adds 累加坐标偏移：argmaxHStart+argmaxHOffset、+kernelOffset、-padH 修正，是 Adds 用于整数索引算术的高频场景（本实例 Adds 调用 16 次）。
- 第 4 参数 computeT2/computeU32 为全有效 mask（M0 模式，无 mask token），按数据位宽选择 compute mask。
- 索引既用于 DataCopyGather 读取输入，也用于 DataCopyScatter 写回 argmax 与最大值。

### Adds 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | And, Cast, CastTrait, Compare | FP32 指数提取后用 Adds 对指数加 1，配合 Select 实现 MX quant scale 条件舍入（ZEROING mask） | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | And, Cast, CastTrait, Compare | 分组 MX quant 中对指数条件加 1（向上取整），配合 MaskAnd/MaskXor/Select 处理 subnormal 与异常值 | __VEC_SCOPE__ |
| swiglu_backward_mx_quant_with_dual_axis | Add, And, Arange, Cast | uint32 指数域加 1，配合 Select 做条件舍入，处理 INF/NaN/zero 特殊值 | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Cast, CreateMask | 计算量化 offset：对 -max/scale 用 Adds 叠加 offsetValue 得偏移标量（M0 无 mask） | __aicore__ |
| flat_quant | And, Cast, CastTrait, Compare | simd_vf 上下文提取 FP32 指数后加 1，配合 Select 处理 fp4 NaN/zero | __simd_vf__ |
| dynamic_mx_quant | And, Cast, CastTrait, Compare | 用比较结果 predicate(p0) 作 mask 对 mxScale 指数条件加 1（MODE_ONE 舍入），无 MaskReg | __VEC_SCOPE__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Cast, Compares | 显式 <float> 模板：构造 vregOne/vregQRange 常量、zpClipped+0.5f 取整、nudged_min/max 平移 | __VEC_SCOPE__ |
| swiglu_mx_quant | And, Cast, Compare, CompareScalar | 双轴 scale 计算：两路指数分别加 1 后 Select+Pack+Interleave 交错打包 B16 | __aicore__ |
| add_rms_norm_dynamic_mx_quant | And, Cast, Compare, CompareScalar | RMSNorm+MX quant 中指数加 1 条件舍入，配合 Select 处理 fp8 NaN/zero | __aicore__ |
| dynamic_quant | Abs, Cast, CreateMask, DataCopy | isFinal 分支计算 offset：-max/scale + offsetMaxValue，RegTraitNumOne 单元素寄存器存首元素 | __VEC_SCOPE__ |
| dynamic_mx_quant | Add, And, Cast, CastTrait | FP32→BF16 舍入修正：提取舍入位后 Adds 加 0x7FFF 偏置再 Add 回主值做四舍五入 | __VEC_SCOPE__ |
| tanh | Abs, And, Cast, CompareScalar | 有理多项式逼近：Adds 叠加常数项；exp 路径 Adds(...,FP32_ONE) 构造 1+e^{2|x|} 分母 | __aicore__ |
| broadcast_gradient_args | AR, Arange, Cast, ClearSpr | 循环内 Adds 生成等差索引序列(start+i*vl)，供 GatherMask 收集广播轴梯度 | __aicore__ |
| clipped_swiglu | AddrReg, Cast, CreateAddrReg, CreateMask | Adds(exp+scalarOne) 构造 1+e^{-α·min(x,clamp)} 分母；Adds(vregX2DeF,gluBias) 加 GLU 偏置 | __VEC_SCOPE__ |
| max_pool_with_argmax | Add, Cast, Compare, CreateMask | 池化 argmax 坐标运算：Adds 累加 H/W offset、kernel offset、pad 修正生成 gather/scatter 索引 | __aicore__ |
