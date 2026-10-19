# ShiftRights

**页面ID:** atlasascendc_api_07_0387  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0387.html

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

源操作数内每个元素做右移，右移的位数由输入参数scalarValue决定。

对数据类型uint16_t/uint32_t的源操作数做逻辑右移，对数据类型int16_t/int32_t的源操作数做算术右移。

逻辑右移为去掉最低位，最高位填充为0。

算术右移为去掉最低位，最高位复制符号位。

例：数据类型uint16_t，二进制数 1010101010101010，逻辑右移一位结果为 0101010101010101；

数据类型int16_t，二进制数 1010101010101010，算术右移一位结果为 1101010101010101；

数据类型int16_t，二进制数 1010101010101010，算术右移三位结果为 1111010101010101。

#### 函数原型

```
template <typename T = DefaultType, typename U, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void ShiftRights(S& dstReg, S& srcReg, U scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 矢量目的操作数和源操作数的数据类型。 Atlas 350 加速卡，dstReg/srcReg支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/int32_t/uint32_t/int64_t/uint64_t |
| U | 标量源操作数的数据类型 Atlas 350 加速卡，dstReg/srcReg支持的数据类型为：int16_t |
| mode | 选择MERGING模式或ZEROING模式。当前仅支持ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。 |
| S | dstReg RegTensor类型， 例如RegTensor<uint16_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 不支持设置为负数。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T, typename U>
__simd_vf__ inline void ShiftRightsVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, U scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::ShiftRights(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 ShiftRights 实例

### 实例 1：dynamic_mx_quant::Reg::StoreAlign

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskOr, MaskReg, Maxs, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, StoreAlign, StoreDist, Sub, UpdateMask
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: tail 轴 FP8 量化算 scale 时，把归一化后的 FP32 最大值右移 FP32_SHR_NUM 位提取指数，再用 And 取尾数，配合 CompareScalar 做进位判断。

（行 732-751）

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

Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32, FP32_NUMBER_ZERO, maskFloat);
```

**要点**:
- scalarValue 为常量移位量（FP32_SHR_NUM=23），不可为负。
- 第四个参数 mask 使用 maskFloat（ZEROING 模式），mask 外元素置零。
- 典型组合：Cast→Mul(invMax)→ShiftRights→And→CompareScalar，用于浮点指数/尾数拆分。

### 实例 2：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, StoreDist, Sub, UnPack
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 双轴 swiglu 量化在 -1 轴算 CLUB scale 时，将归一化 FP32 最大值右移取指数，配合 And 取尾数，用于 FP4/E8M0 scale 计算。

（行 1003-1021）

```cpp

// -2 axis: accumulate column-wise max
Reg::Max(absMax1Dim2, absMax1Dim2, x0Abs, maskAll); // -2轴最大值
Reg::Max(absMax2Dim2, absMax2Dim2, x1Abs, maskAll); // -2轴最大值

// ---- -1 axis CLUB scale: ZERO half (even positions after ReduceMax) ----
Reg::UnPack((AscendC::Reg::RegTensor<uint32_t>&)absMaxDim1Unpack,
                 (AscendC::Reg::RegTensor<uint16_t>&)absMaxDim1);
Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>((Reg::RegTensor<float>&)max32, absMaxDim1Unpack,
                                                   maskAll);

Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32, expMaskReg, maskAll32);
Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32, zeroReg32, maskAll32);
Reg::Mul((Reg::RegTensor<float>&)max32, (Reg::RegTensor<float>&)max32,
              (Reg::RegTensor<float>&)invMax, maskAll32);
Reg::ShiftRights(exp32, max32, SHR_NUM_FOR_FP32, maskAll32);
Reg::And(man32, max32, manMaskReg, maskAll32);

Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32, static_cast<uint32_t>(0), maskAll32);
```

**要点**:
- 使用 Reg:: 命名空间形式，mask 为 maskAll32（全有效）。
- ShiftRights 与 And 配对实现“取指数+取尾数”的标准拆分。
- 先 UnPack 再 Cast，把 BF16 交织最大值还原为 FP32 再右移。

### 实例 3：flat_quant::ScaleVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskMergeMode, MaskReg, Mul, Pack, PostLiteral, RegLayout, RegTensor, SatMode, Select, ShiftLefts, StoreAlign, StoreDist, Sub, UpdateMask
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: flat 量化按 repeat 循环处理，对每个 block 的 FP32 归一化最大值右移取指数，再左移还原做 scale 偏置，产出 E8M0 scale 与倒数 scale 两个输出。

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

**要点**:
- 来源类型为 __simd_vf__（VF 内联函数），与 __VEC_SCOPE__ 调用形式一致。
- mask 变量名 preMaskScale，按 scaleNum 动态 UpdateMask 生成。
- ShiftRights 与 ShiftLefts 对称使用：先右移取指数、再左移回 BF16 位宽做减法。

### 实例 4：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: uint32_t, int32_t）
- **语义**: 复数绝对值计算中，对 subnormal 预放大后的 FP32 值右移取指数因子，再左移清掉尾数，用 Sub 分离出尾数部分供后续 Sqrt 近似使用。

（行 119-137）

```cpp
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
```

**要点**:
- 显式模板类型 uint32_t/int32_t，无 mask 参数（pattern A4_M0）。
- ShiftRights+ShiftLefts 对称：右移丢尾数、左移恢复指数位，相减得尾数。
- 来自 ops-math 仓库 complex_abs，是 ShiftRights 在数学算子中的代表用法。

### 实例 5：abs::AbscomplexCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, Sqrt, StoreAlign, StoreDist, Sub, UpdateMask
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: uint32_t, int32_t）
- **语义**: abs 算子的复数路径中，对放大后的 FP32 右移取指数因子（右移后左移清尾数），分别从 vA、vB 减去得到各自尾数，用于绝对值近似。

（行 119-137）

```cpp
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
```

**要点**:
- 与 complex_abs 同模式，但对 vA、vB 都做尾数分离。
- 无 mask 参数，使用谓词 preg 控制全元素操作。
- 体现 ShiftRights 在“指数/尾数拆分”中的通用性，跨算子复用。

### 实例 6：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, Duplicate, Interleave, LoadAlign, MaskMergeMode, MaskPattern, MaskReg, Max, Mul, Pack, RegLayout, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **ShiftRights 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 分组动态量化在 BF16 域内，将减去基准指数后的差值右移 SHR_NUM_FOR_BF16(7) 位得到 E8M0 的 mxScale，并对 inf/zero 用 Select 兜底。

（行 337-360）

```cpp
for (uint16_t j = 0; j <= static_cast<uint16_t>(blockCountLoop); j++) {
    Reg::LoadAlign(xRegTensor0, xAddr + j * dataLen + i * vfLen);
    Reg::LoadAlign(xRegTensor1, xAddr + (static_cast<uint16_t>(blockCount) - j - 1) * dataLen + i * vfLen);
    if constexpr (IsSame<T, half>::value) {
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16RegTensor0, xRegTensor0, p0);
        Reg::Cast<bfloat16_t, T, castTraitHalf2Bf16>(xBF16RegTensor1, xRegTensor1, p0);
        Reg::And(expMaxRegTensor0, (Reg::RegTensor<uint16_t>&)xBF16RegTensor0, maxEleRegTensor, p0);
        Reg::And(expMaxRegTensor1, (Reg::RegTensor<uint16_t>&)xBF16RegTensor1, maxEleRegTensor, p0);
    } else {
        Reg::And(expMaxRegTensor0, (Reg::RegTensor<uint16_t>&)xRegTensor0, maxEleRegTensor, p0);
        Reg::And(expMaxRegTensor1, (Reg::RegTensor<uint16_t>&)xRegTensor1, maxEleRegTensor, p0);
    }
    Reg::Max(expRegTensor, expMaxRegTensor0, expMaxRegTensor1, p0);
    Reg::Max(expMaxRegTensor, expRegTensor, expMaxRegTensor, p0);
}
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expMaxRegTensor, maxEleRegTensor, p0);
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expMaxRegTensor, zeroRegTensor, p0);
Reg::Compare<uint16_t, CMPMODE::LE>(invalidDataMask, expMaxRegTensor, fp8MaxExpRegTensor, p0);
Reg::Select<uint16_t>(expMaxRegTensor, fp8MaxExpRegTensor, expMaxRegTensor, invalidDataMask);
Reg::Sub(expMaxRegTensor, expMaxRegTensor, fp8MaxExpRegTensor, p0);
Reg::ShiftRights(mxScaleRegTensor, expMaxRegTensor, SHR_NUM_FOR_BF16, p0);
Reg::Select<uint16_t>(mxScaleRegTensor, mxScaleRegTensor, fp8NanRegTensor, infMask);
Reg::Select<uint16_t>(mxScaleRegTensor, mxScaleRegTensor, zeroRegTensor, zeroMask);
Reg::Pack(mxScale, mxScaleRegTensor);
```

**要点**:
- 无 mask 字段（pattern A4_M0），第四个参数 p0 为谓词作 mask。
- ShiftRights 移位量 SHR_NUM_FOR_BF16=7，对应 BF16 指数 7 位。
- 先 Sub 再 ShiftRights 是“求指数差再压缩到 E8M0”的典型顺序。

### 实例 7：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, StoreDist, Sub
- **ShiftRights 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: swiglu 量化非末轴 scale 计算中，对归一化 FP32 最大值右移取指数，配合尾数与多级 CompareScalar 判断是否进位（exp+1），产出 scale1B16。

（行 324-342）

```cpp
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
Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0Odd, expFP32_1, ZERO_FOR_ALL, maskFP32);
Reg::CompareScalar<uint32_t, CMPMODE::LT>(p0Odd, expFP32_1, EXP_254, p0Odd);
```

**要点**:
- Reg:: 形式，mask=maskFP32。
- ShiftRights 后紧跟多组 CompareScalar 构建 MaskOr 进位条件，实现就近舍入。
- 同一函数内对 dim1/dim2 两个维度重复 ShiftRights 取指数。

### 实例 8：add_rms_norm_dynamic_mx_quant::MxQuantComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, StoreAlign, StoreDist, Sub, UpdateMask
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: add+rms_norm 融合算子的量化 scale 计算中，循环处理每个 block，右移取指数后做进位判断，同时产出 E8M0 scale 与倒数 scale 两个输出。

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

**要点**:
- mask=preMaskScale（Mask 大写 token），按 scaleNum 动态生成。
- ShiftRights 与 ShiftLefts 对称：取指数后左移回 BF16 位宽做 scale 偏置减法。
- 来自 norm 仓目录，体现 ShiftRights 在归一化+量化融合算子中的复用。

### 实例 9：rms_norm_dynamic_mx_quant::ComputeScalecuBLAS

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, StoreDist, Sub
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: rms_norm 量化算 scale 时，对归一化 FP32 最大值右移取指数，配合尾数与多级掩码逻辑做进位，产出 E8M0 scale 与倒数 scale。

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

**要点**:
- mask=preMaskScale，使用 DataCopy 而非 LoadAlign 加载。
- ShiftRights+And+CompareScalar+MaskOr 是 E8M0 scale 进位标准链路。
- 体现同一 ShiftRights 调用模式跨 norm 算子的复用。

### 实例 10：swiglu_backward_mx_quant_with_dual_axis::ComputeScaleCuBLASSecondLast

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, Sub
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: swiglu 反向双轴量化的次末轴 scale 计算中，右移取指数后做进位判断，产出 u8 精度的 E8M0 scale 与 u16 倒数 scale。

（行 810-848）

```cpp
for (uint16_t i = 0; i < times; i++) {
    Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE,
                       AscendC::Reg::LoadDist::DIST_UNPACK_B16>(max16Reg, mxScale2ReciprocalAddr,
                                                                     VF_LEN_FP32);
    Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>((Reg::RegTensor<float>&)max32Reg,
                                                       (Reg::RegTensor<xDtype>&)max16Reg, maskAll);
    Reg::Compare<uint32_t, CMPMODE::LT>(cmpResult, max32Reg, expMaskReg, maskAll32);
    Reg::Compare<uint32_t, CMPMODE::NE>(zeroMask, max32Reg, zero32Reg, maskAll32);
    Reg::Mul((Reg::RegTensor<float>&)max32Reg, (Reg::RegTensor<float>&)max32Reg,
                  (Reg::RegTensor<float>&)invMax, maskAll32);
    Reg::ShiftRights(exp32Reg, max32Reg, SHR_NUM_FOR_FP32, maskAll32);
    Reg::And(man32Reg, max32Reg, manMaskReg, maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p0, exp32Reg, static_cast<uint32_t>(0), maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::LT>(p1, exp32Reg, EXP_254, maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32Reg, static_cast<uint32_t>(0), maskAll32);
    Reg::MaskAnd(p0, p0, p1, maskAll32);
    Reg::MaskAnd(p0, p0, p2, maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::EQ>(p1, exp32Reg, static_cast<uint32_t>(0), maskAll32);
    Reg::CompareScalar<uint32_t, CMPMODE::GT>(p2, man32Reg, HALF_FOR_MAN, maskAll32);
    Reg::MaskAnd(p1, p1, p2, maskAll32);
    Reg::MaskOr(p0, p0, p1, maskAll32);
    Reg::Adds(expOne32Reg, exp32Reg, 1, maskAll32);
    Reg::Select(extractExp, expOne32Reg, exp32Reg, p0);
    Reg::Select<uint32_t>(extractExp, extractExp, fp8Nan32Reg, cmpResult);
    Reg::Select<uint32_t>(extractExp, extractExp, zero32Reg, zeroMask);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(scale16, extractExp);
    Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(scale8Zero, scale16);

    Reg::ShiftLefts(extractExp, extractExp, SHR_NUM_FOR_BF16, maskAll32);
    Reg::Sub(halfScale, scaleBiasReg, extractExp, maskAll32);
    Reg::Select<uint32_t>(halfScale, halfScale, nan32Reg, cmpResult);
    Reg::Select<uint32_t>(halfScale, halfScale, zero32Reg, zeroMask);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(recip16Zero, halfScale);
    Reg::DataCopy<uint8_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(mxScale2Addr, scale8Zero,
                                                                                  VF_LEN_FP32, maskB8);

    Reg::DataCopy<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        mxScale2ReciprocalOutAddr, recip16Zero, VF_LEN_FP32, maskB16);
}
```

**要点**:
- mask=maskAll32（全有效），Cast 使用 CAST_X_TO_FP32_ZERO 清零模式。
- ShiftRights 后 Pack 链路多做一次 u16→u8 Pack，适配更窄存储位宽。
- 反向算子复用与正向相同的 ShiftRights 取指数模式。

### 实例 11：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, And, Cast, Compare, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, StoreDist, Sub
- **ShiftRights 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: 双轴动态量化在 BF16 域计算 E8M0 scale 时，将减去 FP4 最大指数后的差值右移 SHR_NUM_FOR_BF16(7) 位得到 scale，对 inf/zero/subnormal 分别用 Select 兜底，-1/-2 两个轴各算一次。

**片段 1** (行 992-1011):

```cpp
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expOnly, expMaskBF16, maskAll);
// 零值检查
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expOnly, zero, maskAll);
// subnormal检查: 指数 < FP4_E2M1_BF16_MAX_EXP (注意使用LT，不是LE)
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expOnly, maxExpValue, maskAll);

// addValueBit进位: 将addValueBit加到完整BF16绝对值上
Reg::Add(addedVal, absMaxDim1, addValue, maskAll);
// 从进位后的结果中提取指数
Reg::And(addedVal, addedVal, expMaskBF16, maskAll);
// subnormal场景: 使用maxExpValue (FP4_E2M1_BF16_MAX_EXP)
Reg::Select<uint16_t>(addedVal, maxExpValue, addedVal, invalidDataMask);
// 减去FP4_E2M1_BF16_MAX_EXP得到指数差值
Reg::Sub(sharedExp, addedVal, maxExpValue, maskAll);
// 右移7位，将BF16指数移到低8位 → E8M0 scale
Reg::ShiftRights(scaleValue, sharedExp, SHR_NUM_FOR_BF16, maskAll);
// INF/NAN → NAN_FOR_FP8_E8M0 (0xFF)
Reg::Select<uint16_t>(scaleValue, scaleValue, nanE8M0, infMask);
// 零值 → 0
Reg::Select<uint16_t>(scaleValue, scaleValue, zero, zeroMask);
```

**片段 2** (行 1037-1056):

```cpp
// ---------- 处理absMax1Dim2 (偶数列, -2轴scale的交织第一部分) ----------
// 复用expOnly为dim2ExpOnly
Reg::And(expOnly, absMax1Dim2, expMaskBF16, maskAll);
// INF/NAN检查
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expOnly, expMaskBF16, maskAll);
// 零值检查
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expOnly, zero, maskAll);
// subnormal检查: 指数 < FP4_E2M1_BF16_MAX_EXP
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expOnly, maxExpValue, maskAll);

// 复用addedVal为dim2SubResult
Reg::Sub(addedVal, absMax1Dim2, subNumForScale, maskAll);
// subnormal → 0
Reg::Select<uint16_t>(addedVal, zero, addedVal, invalidDataMask);
// 右移7位 → E8M0 scale, 复用scaleValue为mxScale2B16
Reg::ShiftRights(scaleValue, addedVal, SHR_NUM_FOR_BF16, maskAll);
// INF/NAN → NAN
Reg::Select<uint16_t>(scaleValue, scaleValue, nanE8M0, infMask);
// 零值 → 0
Reg::Select<uint16_t>(scaleValue, scaleValue, zero, zeroMask);
```

**片段 3** (行 1065-1083):

```cpp
Reg::Sub(reversedShareExp1, biasE8M0, sharedExp, maskAll);
Reg::Select<uint16_t>(reversedShareExp1, reversedShareExp1, nanBF16, infMask);
Reg::Select<uint16_t>(reversedShareExp1, reversedShareExp1, zero, zeroMask);
Reg::Select<uint16_t>(reversedShareExp1, specialExp, reversedShareExp1, invalidDataMask);

// ---------- 处理absMax2Dim2 (奇数列, -2轴scale的交织第二部分) ----------
// 再次复用expOnly, addedVal, sharedExp, scaleValue
Reg::And(expOnly, absMax2Dim2, expMaskBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expOnly, expMaskBF16, maskAll);
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expOnly, zero, maskAll);
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expOnly, maxExpValue, maskAll);

Reg::Sub(addedVal, absMax2Dim2, subNumForScale, maskAll);
Reg::Select<uint16_t>(addedVal, zero, addedVal, invalidDataMask);
// 复用scaleValue为mxScale2OneB16
Reg::ShiftRights(scaleValue, addedVal, SHR_NUM_FOR_BF16, maskAll);
Reg::Select<uint16_t>(scaleValue, scaleValue, nanE8M0, infMask);
Reg::Select<uint16_t>(scaleValue, scaleValue, zero, zeroMask);
```

**要点**:
- mask=maskAll（全有效），ShiftRights 移位量 SHR_NUM_FOR_BF16=7。
- 3 个片段展示对 dim1/dim2 复用同一组寄存器（expOnly/addedVal/scaleValue）的交织处理。
- Select 兜底顺序：ShiftRights 后先 inf→nan、再 zero→0，是 E8M0 scale 标准收尾。

### 实例 12：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Compare, Copy, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, Duplicate, LocalMemBar, MaskMergeMode, MaskReg, Max, MemType, Pack, RegTensor, Select, Sub, UnalignReg, UpdateMask
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 动态量化 optimize 路径中，直接对 BF16 指数最大值右移 shrNum_ 位得到 mxScale，再按数据类型 Pack 成对应位宽，是 ShiftRights 的最简调用形态。

（行 519-526）

```cpp
Reg::ShiftRights(mxScaleReg, expMaxReg, this->shrNum_, mask);
Reg::Select<calcTypeInt>(mxScaleReg, mxScaleReg, fp8Nan, infMask);
if constexpr (IsSame<T, half>::value) {
    Reg::Pack(fp16MxScale, mxScaleReg);
    Reg::Pack(mxScale, fp16MxScale);
} else {
    Reg::Pack(mxScale, mxScaleReg);
}
```

**要点**:
- 实参仅 3 个（pattern A3_M1），是本批唯一的 3 参形态。
- 移位量 this->shrNum_ 为运行时成员变量（非常量），仍需 >=0。
- 调用后立即 Select 做 inf→nan 兜底，再 Pack 输出。

### 实例 13：dynamic_block_mx_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, Compare, CreateMask, Duplicate, Gather, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, StoreAlign, Sub
- **ShiftRights 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: block 级动态量化中，先 ReduceMaxWithDataBlock 跨 block 归约最大值，再减去尾数进位后右移 SHR_NUM_FOR_BF16(7) 位得到 E8M0 scale，对 inf/zero 兜底。

（行 694-712）

```cpp
Reg::ReduceMaxWithDataBlock(expMaxDim, expMaxDim, maskAll);

Reg::And(expTmpMaxDim, expMaxDim, expMaskBF16, maskAll);

// inf/nan值单独处理，结果为E8M0的nan
Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expTmpMaxDim, expMaskBF16, maskAll);
// 0值单独处理，结果为0
Reg::Compare<uint16_t, CMPMODE::NE>(zeroMask, expTmpMaxDim, zero, maskAll);
// 指数位不足被量化类型的ele_max时，为invalid场景，结果为0
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expTmpMaxDim, yMaxExp, maskAll);
Reg::Select<uint16_t>(expMaxDim, mantissaForMax, expMaxDim, invalidDataMask);

// 尾数位进位
Reg::Sub(expMaxDim, expMaxDim, mantissaForMax, maskAll);
// 右移7位，BF16的指数位移到了末8位
Reg::ShiftRights(mxScaleB16, expMaxDim, SHR_NUM_FOR_BF16, maskAll);
Reg::Select<uint16_t>(mxScaleB16, mxScaleB16, nanE8M0, infMask);
Reg::Select<uint16_t>(mxScaleB16, mxScaleB16, zero, zeroMask);
```

**要点**:
- mask=maskAll，ShiftRights 移位量 SHR_NUM_FOR_BF16=7。
- 与 ReduceMaxWithDataBlock 配合，是 block 级 scale 计算的代表。
- Gather 共现，说明该算子用 Gather 做分块索引后统一 ShiftRights 取 scale。

### 实例 14：dynamic_mx_quant::Reg::Select

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Cast, CastTrait, Compare, CreateMask, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, Max, Pack, RegLayout, RegTensor, SatMode, Select, Sub
- **ShiftRights 调用次数**: 6
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 大 tail 高性能路径中，ShiftRights 被复用两次：第一次右移取舍入偏置、加 0x7FFF 后加回实现就近舍入；第二次对舍入后指数右移 BF16_SHR_NUM(7) 位得 E8M0 scale。

（行 613-634）

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

Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expMaxU16, maxEleU16, pregAll16);
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expMaxU16, dtypeYMaxExp, pregAll16);

Reg::Sub(expMaxU16, maxU16, subNumForScale, pregAll16);

Reg::Select<uint16_t>(expMaxU16, zeroU16, expMaxU16, invalidDataMask);
Reg::ShiftRights(mxScaleBF16, expMaxU16, BF16_SHR_NUM, pregAll16);
Reg::Select<uint16_t>(mxScaleBF16, mxScaleBF16, fp8NanU16, infMask);

Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>((Reg::RegTensor<uint8_t>&)mxScale, mxScaleBF16);
```

**要点**:
- 无 mask（pattern A4_M0），使用 pregAll32/pregAll16 全有效谓词。
- 同函数内 ShiftRights 两次复用：先做舍入、再做 scale 压缩。
- float 分支独有舍入逻辑，非 float 分支直接取指数。

### 实例 15：dynamic_mx_quant::Reg::Select

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, Max, Pack, RegLayout, RegTensor, SatMode, Select, StoreDist, Sub
- **ShiftRights 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 大 tail 高性能路径中，先对 FP32 指数右移 FP32_PACK_SHR_NUM 位并 Pack 成 BF16，再做 inf/subnormal 判断与减基准，最后右移 BF16_SHR_NUM(7) 位得 E8M0 scale 并 DataCopy 输出。

（行 740-754）

```cpp
if constexpr (IsSame<xDtype, float>::value) {
    Reg::ShiftRights(expMaxU32, expMaxU32, FP32_PACK_SHR_NUM, pregAll32);
    Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(expMaxU16, expMaxU32);
}

Reg::Compare<uint16_t, CMPMODE::NE>(infMask, expMaxU16, maxEleU16, pregAll16);
Reg::Compare<uint16_t, CMPMODE::LT>(invalidDataMask, expMaxU16, dtypeYMaxExp, pregAll16);

Reg::Sub(expMaxU16, expMaxU16, subNumForScale, pregAll16);

Reg::Select<uint16_t>(expMaxU16, zeroU16, expMaxU16, invalidDataMask);
Reg::ShiftRights(mxScaleBF16, expMaxU16, BF16_SHR_NUM, pregAll16);
Reg::Select<uint16_t>(mxScaleBF16, mxScaleBF16, fp8NanU16, infMask);

DataCopy<uint8_t, Reg::StoreDist::DIST_PACK_B16>(mxScaleAddr, (Reg::RegTensor<uint8_t>&)mxScaleBF16, pregAll8);
```

**要点**:
- 无 mask（pattern A4_M0），pregAll 系列全有效谓词。
- ShiftRights 两次复用：FP32→BF16 位宽压缩、BF16→E8M0 scale 压缩。
- 输出用 DataCopy 直接存 u8，与 StoreAlign 路径形成对比。

### ShiftRights 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 归一化 FP32 右移取指数 + And 取尾数（mask=maskFloat, ZEROING） | __VEC_SCOPE__ |
| swiglu_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 双轴 -1 轴 CLUB scale 取指数（Reg, maskAll32） | __VEC_SCOPE__ |
| flat_quant | Adds, And, Cast, CastTrait, Compare | repeat 循环右移取指数 + 左移还原做 scale 偏置（__simd_vf__, preMaskScale） | __simd_vf__ |
| complex_abs | Abs, Add, Cast, CastTrait, Compare | subnormal 放大后右移取指数因子 + 左移清尾数（无 mask, ops-math） | __aicore__ |
| abs | Abs, Add, Cast, CastTrait, Compare | 复数路径 vA/vB 尾数分离（右移+左移+Sub, 无 mask, ops-math） | __aicore__ |
| grouped_dynamic_mx_quant | And, Cast, CastTrait, Compare, CreateMask | BF16 域减基准指数后右移得 E8M0 scale（无 mask, p0 谓词） | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | 非末轴 scale 取指数 + 多级 CompareScalar 进位（Reg, maskFP32） | __aicore__ |
| add_rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | norm 融合算子循环取指数 + 进位 + E8M0/倒数双输出（preMaskScale） | __aicore__ |
| rms_norm_dynamic_mx_quant | Adds, And, Cast, Compare, CompareScalar | rms_norm 循环取指数 + 进位（DataCopy 加载, preMaskScale） | __aicore__ |
| swiglu_backward_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | 反向双轴次末轴取指数 + u8 Pack 输出（maskAll32） | __aicore__ |
| dynamic_mx_quant_with_dual_axis | Add, And, Cast, Compare, CreateMask | 双轴 BF16 域减 FP4 最大指数后右移得 E8M0（maskAll, 3 片段交织） | __VEC_SCOPE__ |
| dynamic_mx_quant | And, Compare, Copy, DataCopy, DataCopyUnAlign | 最简形态直接右移得 mxScale + Select 兜底（3 参, shrNum_ 运行时） | __VEC_SCOPE__ |
| dynamic_block_mx_quant | And, Cast, Compare, CreateMask, Duplicate | block 级 ReduceMax 后右移得 E8M0 scale（maskAll, Gather 分块） | __VEC_SCOPE__ |
| dynamic_mx_quant | Add, Adds, And, Cast, CastTrait | 大 tail 路径 ShiftRights 两次复用：舍入偏置 + scale 压缩（无 mask） | __VEC_SCOPE__ |
| dynamic_mx_quant | And, Cast, CastTrait, Compare, CreateMask | 大 tail 路径 FP32→BF16→E8M0 两级右移压缩（无 mask, DataCopy 输出） | __VEC_SCOPE__ |
