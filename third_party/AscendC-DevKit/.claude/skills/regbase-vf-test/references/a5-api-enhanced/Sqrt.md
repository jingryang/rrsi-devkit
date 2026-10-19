# Sqrt

**页面ID:** atlasascendc_api_07_0345  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0345.html

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

根据mask对输入数据srcReg进行平方根操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0345_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, auto mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Sqrt(U& dstReg, U& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 |
| mode | 可配置为MaskMergeMode的枚举或SqrtSpecificMode的结构体指针。- MaskMergeMode，选择MERGING模式或ZEROING模式。  - ZEROING，mask未筛选的元素在dstReg中置零。  - MERGING，暂不支持。 - SqrtSpecificMode，定义如下：``` enum class SqrtAlgo {     INTRINSIC = 0,     FAST_INVERSE,     PRECISION_1ULP_FTZ_TRUE,     PRECISION_0ULP_FTZ_FALSE,     PRECISION_1ULP_FTZ_FALSE, }; struct SqrtSpecificMode {     MaskMergeMode mrgMode = MaskMergeMode::ZEROING,     bool precisionMode = false;     SqrtAlgo algo = SqrtAlgo::INTRINSIC; }; ```   - mrgMode：选择MERGING模式或ZEROING模式。  - precisionMode：用于配置精度模式。当precisionMode为true时，使能更高精度的Sqrt计算，使用快速求逆算法得出结果。适用于输入值在[0, 85070596800837026223494223584045301760]范围内的计算。在该范围内，算法保证输出的最大精度误差为0 ulp；当输入值大于85070596800837026223494223584045301760时，输出为0。该算法目前只针对float数据类型生效。   - algo：用于配置Subnormal模式。    - SqrtAlgo::INTRINSIC、SqrtAlgo::PRECISION_1ULP_FTZ_TRUE，使用单指令计算得出结果，最大精度误差为1 ulp。    - SqrtAlgo::FAST_INVERSE、SqrtAlgo::PRECISION_0ULP_FTZ_FALSE，使用快速求逆算法得出结果。适用于输入值在[0, 85070596800837026223494223584045301760]范围内的计算。在该范围内，算法保证输出的最大精度误差为0 ulp；当输入值大于85070596800837026223494223584045301760时，输出为0。目前，该算法仅支持float数据类型，并在该模式下支持Subnormal数据计算。    - SqrtAlgo::PRECISION_1ULP_FTZ_FALSE，仅支持half类型的Subnormal数据计算，此时最大精度误差为1 ulp。 |
| U | 源操作数和目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

如果srcReg中的数值为非正数，可能会产生未知结果。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void SqrtVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;   
    // 高精度模式
    // static constexpr AscendC::Reg::SqrtSpecificMode mode = {MaskMergeMode::ZEROING, true};
    // Subnormal模式
    // static constexpr AscendC::Reg::SqrtSpecificMode mode = {MaskMergeMode::ZEROING, true, SqrtAlgo::PRECISION_0ULP_FTZ_FALSE};
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Sqrt(dstReg, srcReg, mask);
        // 高精度模式/Subnormal模式
        // AscendC::Reg::Sqrt<T, &mode>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Sqrt 实例

### 实例 1：complex_abs::ComplexAbsCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Cast, CastTrait, Compare, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Mul, RegLayout, RegTensor, RegTraitNumOne, SatMode, Select, ShiftLefts, ShiftRights, StoreAlign, StoreDist, Sub, UpdateMask
- **Sqrt 调用次数**: 4
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 计算复数 a+bi 的模长 |a+bi|=sqrt(a²+b²)：先 Mul 求实部/虚部平方、Add 求和，再 Sqrt 得模长，最后 Cast 回 half 并 StoreAlign；对非 complex32 路径额外做 subnormal 归一化与 0 值处理。

**片段 1** (行 103-160):

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

**片段 2** (行 135-153):

```cpp
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
```

**要点**: 1) Sqrt 输入须为非负数（平方和 ≥ 0），代码用 Maxs/Select 兜底 0 与 subnormal；2) 3 实参形式 Reg::Sqrt(dst, src, preg)，preg 为 MaskReg；3) 复数与普通路径由 if constexpr (std::is_same<U, complex32>::value) 区分。

### 实例 2：cdist::VecScope_L403

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, Duplicate, LoadAlign, MaskMergeMode, MaskPattern, MaskReg, Mul, ReduceSum, RegTensor, SqrtSpecificMode, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore, UpdateMask
- **Sqrt 调用次数**: 1
- **参数模式**: `T2_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义**: cdist 距离归一化的最后一步：当单 UB 循环时用 Sqrt<float, &modesqrt>(result, dst, mask) 对平方和开方得到欧氏距离，否则直接存中间结果。

（行 438-443）

```cpp
if (ubLoopNumM_ == 1) {
    Reg::Sqrt<float, &modesqrt>(resultRegNorm2, dstRegNorm2, maskOneNorm2);
    Reg::StoreUnAlign(yOffsetNorm2, resultRegNorm2, uRegNorm2, BASE_ONE);
} else {
    Reg::StoreUnAlign(yOffsetNorm2, dstRegNorm2, uRegNorm2, BASE_ONE);
}
```

**要点**: 1) 通过 SqrtSpecificMode 结构体指针 &modesqrt 作为模板第二参传入，可配置 mrgMode/precisionMode/algo；2) 第三参 mask 为 MaskReg 控制尾元素；3) 与 StoreUnAlign/UnalignRegForStore 组合做非对齐存储。

### 实例 3：pow::ComputeRsqrt

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopy, Div, Duplicate, LoadDist, MaskMergeMode, MaskReg, RegTensor, StoreDist, UpdateMask
- **Sqrt 调用次数**: 2
- **参数模式**: `T2_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义**: 在 pow 算子里用 Sqrt<float, MaskMergeMode::ZEROING> 先开方、再 Div 用 1.0 除以开方结果，组合实现 rsqrt（1/sqrt(x)），供 pow 标量指数分支使用。

**片段 1** (行 361-371):

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = Reg::UpdateMask<float>(size);
    Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(
        vreg0, bufferIn0Addr + i * (VECTOR_REG_WIDTH / sizeof(float)));
    Reg::Duplicate<float, Reg::MaskMergeMode::ZEROING>(vreg1, static_cast<float>(1.0f),
                                                                 preg0);
    Reg::Sqrt<float, Reg::MaskMergeMode::ZEROING>(vreg2, vreg0, preg0);
    Reg::Div<float, Reg::MaskMergeMode::ZEROING>(vreg3, vreg1, vreg2, preg0);
    Reg::DataCopy<float, Reg::StoreDist::DIST_NORM_B32>(
        bufferOut0Addr + i * (VECTOR_REG_WIDTH / sizeof(float)), vreg3, preg0);
}
```

**片段 2** (行 385-397):

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = Reg::UpdateMask<float>(size);
    Reg::DataCopy<T1, Reg::LoadDist::DIST_UNPACK_B16>(
        vreg0, bufferIn0Addr + i * (VECTOR_REG_WIDTH / sizeof(float)));
    Reg::Cast<float, T1, castTrait0>(vreg1, vreg0, preg0);
    Reg::Duplicate<float, Reg::MaskMergeMode::ZEROING>(vreg2, static_cast<float>(1.0f),
                                                                 preg0);
    Reg::Sqrt<float, Reg::MaskMergeMode::ZEROING>(vreg3, vreg1, preg0);
    Reg::Div<float, Reg::MaskMergeMode::ZEROING>(vreg4, vreg2, vreg3, preg0);
    Reg::Cast<T1, float, castTrait1>(vreg5, vreg4, preg0);
    Reg::DataCopy<T1, Reg::StoreDist::DIST_PACK_B32>(
        bufferOut0Addr + i * (VECTOR_REG_WIDTH / sizeof(float)), vreg5, preg0);
}
```

**要点**: 1) 模板第二参显式传 MaskMergeMode::ZEROING，未选中元素置零；2) UpdateMask 生成 preg0 控制尾元素；3) rsqrt=Div(1,Sqrt(x)) 是 Sqrt+Div 经典组合，比直接 Rsqrt 更可控。

### 实例 4：random_common::BoxMullerFloatSIMD

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, Ln, LoadDist, MaskReg, Maxs, Muls, PostLiteral, RegTensor, UpdateMask
- **Sqrt 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: Box-Muller 正态采样：对均匀随机数 u1,u2 做 Sqrt(-2·ln(max(u1,eps))) 得到标准正态分布的半径分量，配合 Muls(2π·u2) 的角度分量，mask 控制尾元素。

（行 256-267）

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(repeatTimes); ++i) {
    mask = Reg::UpdateMask<float>(sreg1);
    Reg::DataCopy<float, Reg::LoadDist::DIST_DINTLV_B32>(
        vreg0, vreg1, uniformRes + i * offset * DOUBLE_UNIFORM_RESULT);
    Reg::Maxs(vreg2, vreg0, epsScalar, mask);
    Reg::Ln(vreg3, vreg2, mask);
    Reg::Muls(vreg4, vreg1, doublePiScalar, mask);
    Reg::Muls(vreg5, vreg3, -DOUBLE_MULTIPLE, mask);
    Reg::Sqrt(vreg6, vreg5, mask);
    Reg::DataCopy<float, Reg::PostLiteral::POST_MODE_UPDATE>(ubV1Out, vreg4, offset, mask);
    Reg::DataCopy<float, Reg::PostLiteral::POST_MODE_UPDATE>(ubU2Out, vreg6, offset, mask);
}
```

**要点**: 1) Sqrt 前先用 Maxs 把输入夹到 eps 以上，避免 ln(0)/sqrt(负数)；2) 3 实参带 mask 形式 Reg::Sqrt(dst, src, mask)；3) 与 Ln、Muls 组合完成极坐标变换。

### 实例 5：rsqrt::RsqrtCustom

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, Div, DivSpecificMode, Duplicate, MaskMergeMode, MaskReg, RegTensor, RegTraitNumOne, UpdateMask
- **Sqrt 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: rsqrt 算子本身：先 Sqrt(vregSqrt, vregInput, mask) 求平方根，再用 Div<T, &mode>(ones, vregSqrt, mask) 做 1/sqrt，通过 DivSpecificMode 实现高精度。

（行 47-58）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    // OpCopyIn0
    Reg::DataCopy(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    // compute rsqrt
    Reg::Duplicate(ones, (T)1.0, mask);
    Reg::Sqrt(vregSqrt, vregInput, mask);
    // high precision mode div
    Reg::Div<T, &mode>(vregOutput, ones, vregSqrt, mask);
    // OpCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**要点**: 1) rsqrt = Div(1, Sqrt(x)) 两步法，Div 的 mode 指定高精度算法；2) Duplicate(ones, 1.0) 构造被除数；3) UpdateMask<T, RegTraitNumOne> 生成按 count 对齐的掩码。

### 实例 6：stateless_random_normal_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: DataCopy, Ln, LoadDist, MaskReg, Maxs, Muls, PostLiteral, RegTensor, UpdateMask
- **Sqrt 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: stateless_random_normal_v2 的 Box-Muller 变换：Sqrt(-2·ln(max(u1,eps))) 产生正态分布半径，与角度 2π·u2 一起输出 (u,v) 对，mask 控制尾元素。

（行 263-274）

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(repeatTimes); ++i) {
    mask = Reg::UpdateMask<float>(sreg1);
    Reg::DataCopy<float, Reg::LoadDist::DIST_DINTLV_B32>(
        vreg0, vreg1, uniformRes + i * offset * DOUBLE_UNIFORM_RESULT);
    Reg::Maxs(vreg2, vreg0, epsScalar, mask);
    Reg::Ln(vreg3, vreg2, mask);
    Reg::Muls(vreg4, vreg1, doublePiScalar, mask);
    Reg::Muls(vreg5, vreg3, -DOUBLE_MULTIPLE, mask);
    Reg::Sqrt(vreg6, vreg5, mask);
    Reg::DataCopy<float, Reg::PostLiteral::POST_MODE_UPDATE>(ubV1Out, vreg4, offset, mask);
    Reg::DataCopy<float, Reg::PostLiteral::POST_MODE_UPDATE>(ubU2Out, vreg6, offset, mask);
}
```

**要点**: 1) 与 random_common 同源逻辑，区别在 __VEC_SCOPE__ 上下文；2) Maxs 防 ln(0)/sqrt(负数)；3) DataCopy 用 POST_MODE_UPDATE 带后更新地址。

### 实例 7：pow::ComputeSqrt

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopy, LoadDist, MaskMergeMode, MaskReg, RegTensor, StoreDist, UpdateMask
- **Sqrt 调用次数**: 2
- **参数模式**: `T2_A3_M0_TYPEfloat`（实参 3 个，类型: float）
- **语义**: pow 算子的直接开方分支：Sqrt<float, MaskMergeMode::ZEROING>(vreg, src, preg0) 对输入逐元素开方并存储；half 输入先 Cast 到 float 再开方。

**片段 1** (行 313-320):

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = Reg::UpdateMask<float>(size);
    Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(
        vreg0, bufferIn0Addr + i * (VECTOR_REG_WIDTH / sizeof(float)));
    Reg::Sqrt<float, Reg::MaskMergeMode::ZEROING>(vreg1, vreg0, preg0);
    Reg::DataCopy<float, Reg::StoreDist::DIST_NORM_B32>(
        bufferOut0Addr + i * (VECTOR_REG_WIDTH / sizeof(float)), vreg1, preg0);
}
```

**片段 2** (行 332-341):

```cpp
for (uint16_t i = 0; i < vfLoopNum; i++) {
    preg0 = Reg::UpdateMask<float>(size);
    Reg::DataCopy<T1, Reg::LoadDist::DIST_UNPACK_B16>(
        vreg0, bufferIn0Addr + i * (VECTOR_REG_WIDTH / sizeof(float)));
    Reg::Cast<float, T1, castTrait0>(vreg1, vreg0, preg0);
    Reg::Sqrt<float, Reg::MaskMergeMode::ZEROING>(vreg2, vreg1, preg0);
    Reg::Cast<T1, float, castTrait1>(vreg3, vreg2, preg0);
    Reg::DataCopy<T1, Reg::StoreDist::DIST_PACK_B32>(
        bufferOut0Addr + i * (VECTOR_REG_WIDTH / sizeof(float)), vreg3, preg0);
}
```

**要点**: 1) 模板第二参 ZEROING 决定 mask 外元素置零；2) half 路径需 Cast 到 float 才能开方，再 Cast 回原类型；3) DataCopy 配合 StoreDist::DIST_NORM_B32 / DIST_PACK_B32 做对齐打包存储。

### 实例 8：global_lp_pool::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Exp, Ln, LoadAlign, MaskReg, Muls, RegTensor, UpdateMask
- **Sqrt 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: global_lp_pool 的最终开方：对累乘/累加得到的 root 寄存器做 AscendC::Reg::Sqrt(f32Reg, f32Reg, mask) 得到 Lp 范数的 1/p 次幂结果，再 PostCastAndStoreVf 输出。

（行 420-431）

```cpp
{
    AscendC::Reg::RegTensor<float> f32Reg;
    AscendC::Reg::MaskReg mask;
    uint32_t remaining = laneN;
    for (uint16_t i = 0; i < repeatTime; ++i) {
        int32_t off = static_cast<int32_t>(i) * VF_VL_F32;
        mask = AscendC::Reg::UpdateMask<float>(remaining);
        AscendC::Reg::LoadAlign(f32Reg, rootPtr + off);
        AscendC::Reg::Sqrt(f32Reg, f32Reg, mask);
        PostCastAndStoreVf<D_T, kNeedCast>(f32Reg, mask, outPtr, off);
    }
}
```

**要点**: 1) float 寄存器原位开方 (dst==src)；2) UpdateMask<float>(remaining) 处理尾批不对齐；3) 与 LoadAlign/Muls/Ln 组合完成 Lp 池化的指数还原。

### 实例 9：euclidean_norm::PostElewiseVfImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, LoadAlign, MaskReg, RegTensor, StoreAlign, StoreDist, UpdateMask
- **Sqrt 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: euclidean_norm 的最后一步：对 reduce 得到的平方和 rootPtr 做 Sqrt(f32Reg, f32Reg, mask) 得到 L2 范数，再按输出类型 Cast 后 StoreAlign。

（行 185-203）

```cpp
for (uint16_t i = 0; i < repeatTime; ++i) {
    int32_t off = static_cast<int32_t>(i) * static_cast<int32_t>(kRepF32);
    mask = AscendC::Reg::UpdateMask<float>(remaining);

    AscendC::Reg::LoadAlign(f32Reg, rootPtr + off);
    AscendC::Reg::Sqrt(f32Reg, f32Reg, mask);

    if constexpr (IsFp32) {
        AscendC::Reg::StoreAlign(outPtr + off, f32Reg, mask);
    } else if constexpr (IsB16) {
        AscendC::Reg::RegTensor<DType> b16Reg;
        AscendC::Reg::Cast<DType, float, kCastTraitFromFp32Fp16>(b16Reg, f32Reg, mask);
        AscendC::Reg::StoreAlign<DType, AscendC::Reg::StoreDist::DIST_PACK_B32>(outPtr + off, b16Reg, mask);
    } else {
        AscendC::Reg::RegTensor<int32_t> iReg;
        AscendC::Reg::Cast<int32_t, float, kCastTraitFromFp32Int32>(iReg, f32Reg, mask);
        AscendC::Reg::StoreAlign(outPtr + off, iReg, mask);
    }
}
```

**要点**: 1) __simd_vf__ 上下文，使用 AscendC::Reg:: 前缀；2) 支持 fp32/b16/int32 三种输出，分别走不同 Cast + StoreDist 分支；3) UpdateMask<float>(remaining) 控制尾元素。

### 实例 10：batch_norm::CalculateRunningMeanVar

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Div, Mul, Muls
- **Sqrt 调用次数**: 1
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: batch_norm 的 rstd 计算：Adds(var, var, eps) 后 Div(r, 1, var) 再 Sqrt(y, r, pregLoop) 得到 1/sqrt(var+eps) 初值，随后用 Newton-Raphson (1.5-0.5xy) 迭代精修 rstd。

（行 801-824）

```cpp
if (vfUseRunningMeanVar) {
    LoadTensorForDtypeT<T2>(runningVar, runningVarInUbAddr, pregLoop, k * VL_FP32);
    Muls(runningVar, runningVar, oneSubMomentumVf, pregLoop);
    Add(saveVar, saveVar, runningVar, pregLoop);
}

StoreTensorForDtypeT<T2>(runningVarOutUbAddr, saveVar, pregLoop, k * VL_FP32);

// rstd
Adds(var, var, epsilon, pregLoop);
Div(r, one, var, pregLoop);
Sqrt(y, r, pregLoop);
Muls(t, var, float(-0.5), pregLoop);
Mul(t, t, y, pregLoop);                // -0.5 * x * y
Mula(t1, t, y, pregLoop);              // 1.5 + (-0.5 * x * y) * y
Mul(rstd, y, t1, pregLoop);            // y = y * (1.5 - 0.5 * x * y)
Muls(t3, var, float(-1.0), pregLoop);  // -1 * x
Mula(s, t3, r, pregLoop);              // 1 + (-1) * x * r
Muls(t4, rstd, float(-1.0), pregLoop); // (-1) * y
Mula(r, t4, rstd, pregLoop);           // r + (-1) * y * y
Mula(s, var, r, pregLoop);             // s + x * t
Mul(s, s, rstd, pregLoop);             // e * y
Mula(rstd, s, scalar1, pregLoop);      // y + y * e * 0.5
CompareScalar(cmpRegZero, var, POS_INF, pregLoop);
```

**要点**: 1) 2 实参形式 Sqrt(y, r, preg)（无独立类型模板参），dst 与 src 均为 RegTensor；2) Sqrt 只求初值，精度靠后续 Mula/Mul 牛顿迭代；3) 配合 CompareScalar 处理 var=POS_INF 边界。

### 实例 11：batch_norm_v3::CalculateRunningMeanVarWithRstdVF

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Div, Mul, Muls
- **Sqrt 调用次数**: 1
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: batch_norm_v3 的 rstd：与 batch_norm 同模式，Adds(var)+Div(r,1,var)+Sqrt(y,r) 求 1/sqrt(var+eps) 初值后牛顿迭代；本片段先做 saveVar 的 half/float 分支存储。

（行 979-993）

```cpp
if constexpr (!IsSameType<T_RUNNING_MEAN, float>::value) {
    RegTensor<T_RUNNING_MEAN> saveVarTmp;
    Cast<T_RUNNING_MEAN, float, NormCommon::castTraitB322B16>(saveVarTmp, saveVar, pregLoop);
    DataCopy<T_RUNNING_MEAN, StoreDist::DIST_PACK_B32>(
        ((__local_mem__ T_RUNNING_MEAN*)runningVarOutUbAddr + k * vectorLen), saveVarTmp, pregLoop);
} else {
    DataCopy(((__local_mem__ float*)runningVarOutUbAddr + k * vectorLen), saveVar, pregLoop);
}

Adds(var, var, epsilon, pregLoop);
Div(r, one, var, pregLoop);
Sqrt(y, r, pregLoop);
Muls(t, var, float(-0.5), pregLoop);
Mul(t, t, y, pregLoop);
Mula(t1, t, y, pregLoop);
```

**要点**: 1) 2 实参 Sqrt；2) if constexpr (!IsSameType<T_RUNNING_MEAN, float>::value) 分支决定 runningVar 是否需 Cast；3) rstd 精修链与 batch_norm 一致。

### 实例 12：instance_norm::CalculateRstd

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Div, Maxs, Mul, Muls
- **Sqrt 调用次数**: 1
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: instance_norm 的 rstd：循环每行 Adds(var,eps)→Maxs→Div(r,1,var)→Sqrt(y,r) 求 1/sqrt(var+eps) 初值，牛顿迭代后用 Select 处理 var=0/inf 把 rstd 置 0/inf。

（行 636-666）

```cpp
for (uint16_t i = 0; i < loopRows; ++i) {
    pregLoop = UpdateMask<float>(sreg);
    Duplicate(scalarInf, POS_INF, pregLoop);
    Duplicate(scalarZero, float(0.0), pregLoop);
    Duplicate(one, float(1.0), pregLoop);
    Duplicate(scalar1, SCALAR3, pregLoop);
    Duplicate(t1, SCALAR2, pregLoop);
    Duplicate(s, float(1.0), pregLoop);
    // rstd
    DataCopy(var, varUb + i * VL_FP32);
    Adds(var, var, epsilon, pregLoop);
    Maxs(var, var, SCALAR0, pregLoop);
    Div(r, one, var, pregLoop);
    Sqrt(y, r, pregLoop);
    Muls(t, var, SCALAR1, pregLoop);
    Mul(t, t, y, pregLoop);                // -0.5 * x * y
    Mula(t1, t, y, pregLoop);              // 1.5 + (-0.5 * x * y) * y
    Mul(rstd, y, t1, pregLoop);            // y = y * (1.5 - 0.5 * x * y)
    Muls(t3, var, float(-1.0), pregLoop);  // -1 * x
    Mula(s, t3, r, pregLoop);              // 1 + (-1) * x * r
    Muls(t4, rstd, float(-1.0), pregLoop); // (-1) * y
    Mula(r, t4, rstd, pregLoop);           // r + (-1) * y * y
    Mula(s, var, r, pregLoop);             // s + x * t
    Mul(s, s, rstd, pregLoop);             // e * y
    Mula(rstd, s, scalar1, pregLoop);      // y + y * e * 0.5
    CompareScalar(cmpRegZero, var, POS_INF, pregLoop);
    Select(rstd, scalarZero, rstd, cmpRegZero);
    CompareScalar(cmpRegInf, var, float(0.0), pregLoop);
    Select(rstd, scalarInf, rstd, cmpRegInf);
    DataCopy(rstdInUb + i * VL_FP32, rstd, pregLoop);
}
```

**要点**: 1) 2 实参 Sqrt；2) Maxs(var, SCALAR0) 防 var 过小导致开方异常；3) CompareScalar+Select 双重边界处理（0 与 POS_INF）。

### 实例 13：group_norm_silu::CalRstdByHighPrecision

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Div, MaskPattern, Mul, Muls
- **Sqrt 调用次数**: 1
- **参数模式**: `T0_A2_M0_TYPEnone`（实参 2 个）
- **语义**: group_norm_silu 的高精度 rstd：用 CreateMask<float, MaskPattern::VL1>() 生成单元素全掩码 pregMerge，Sqrt(y, r, pregMerge) 求 1/sqrt(var+eps) 初值后牛顿迭代。

（行 187-214）

```cpp
RegTensor<float> t3;
RegTensor<float> t4;
MaskReg cmpReg1;
MaskReg cmpReg2;
MaskReg pregMerge = CreateMask<float, AscendC::Reg::MaskPattern::VL1>();

Duplicate(one, float(1.0), pregMerge);
Duplicate(scalar1, SCALAR3, pregMerge);
Duplicate(scalar2, POS_INF, pregMerge);
Duplicate(scalar3, ZERO, pregMerge);
Duplicate(t1, SCALAR2, pregMerge);
Duplicate(s, float(1.0), pregMerge);

Adds(var, var, epsilon, pregMerge);
Div(r, one, var, pregMerge);
Sqrt(y, r, pregMerge);
Muls(t, var, SCALAR1, pregMerge);
Mul(t, t, y, pregMerge);                // -0.5 * x * y
Mula(t1, t, y, pregMerge);              // 1.5 + (-0.5 * x * y) * y
Mul(rstd, y, t1, pregMerge);            // y = y * (1.5 - 0.5 * x * y)
Muls(t3, var, float(-1.0), pregMerge);  // -1 * x
Mula(s, t3, r, pregMerge);              // 1 + (-1) * x * r
Muls(t4, rstd, float(-1.0), pregMerge); // (-1) * y
Mula(r, t4, rstd, pregMerge);           // r + (-1) * y * y
Mula(s, var, r, pregMerge);             // s + x * t
Mul(s, s, rstd, pregMerge);             // e * y
Mula(rstd, s, scalar1, pregMerge);      // y + y * e * 0.5
CompareScalar(cmpReg1, var, POS_INF, pregMerge);
```

**要点**: 1) 2 实参 Sqrt，VL1 掩码表示逐标量计算；2) 高精度路径与 group_norm 共用牛顿迭代模板；3) Duplicate 预置 one/SCALAR3/POS_INF 等常量寄存器。

### 实例 14：apply_adam_d::CalcLr

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Div, Duplicate, Muls, RegTensor
- **Sqrt 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: apply_adam_d 的学习率偏差校正：Sqrt(regSqrtBeta2Power, 1-beta2^t, pregUp) 求 sqrt(1-beta2^t)，再 Muls·Div 组合得 lr_t = lr·sqrt(1-beta2^t)/(1-beta1^t)。

（行 38-57）

```cpp
{
    Reg::RegTensor<U> regBeta1Power;
    Reg::RegTensor<U> regBeta2Power;
    Reg::RegTensor<U> regNegBeta2Power;
    Reg::RegTensor<U> regAddBeta2Power;
    Reg::RegTensor<U> regSqrtBeta2Power;
    Reg::RegTensor<U> regNegBeta1Power;
    Reg::RegTensor<U> regAddBeta1Power;
    Reg::RegTensor<U> regMulLrSqrt;

    Reg::Duplicate(regBeta1Power, beta1PowerUp, pregUp);
    Reg::Duplicate(regBeta2Power, beta2PowerUp, pregUp);
    Reg::Muls(regNegBeta2Power, regBeta2Power, -1.0f, pregUp);
    Reg::Adds(regAddBeta2Power, regNegBeta2Power, 1.0f, pregUp);
    Reg::Sqrt(regSqrtBeta2Power, regAddBeta2Power, pregUp);
    Reg::Muls(regNegBeta1Power, regBeta1Power, -1.0f, pregUp);
    Reg::Adds(regAddBeta1Power, regNegBeta1Power, 1.0f, pregUp);
    Reg::Muls(regMulLrSqrt, regSqrtBeta2Power, lrUp, pregUp);
    Reg::Div(regLrT, regMulLrSqrt, regAddBeta1Power, pregUp);
}
```

**要点**: 1) 3 实参 Sqrt(dst, src, preg)，输入由 Adds(1, -beta2^t) 构造；2) Duplicate 把标量 beta1Power/beta2Power 装进寄存器；3) Sqrt 结果与 lr 相乘后除以 (1-beta1^t) 完成两步偏差校正。

### 实例 15：add_rms_norm::ComputeFormerImplV1MultiN

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Div, Muls
- **Sqrt 调用次数**: 3
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: add_rms_norm 的 rstd：对均方 ReduceSum→Muls(avgFactor)→Adds(eps) 后 Sqrt(vMean, vMean, pregMerge) 得到 sqrt(mean(x²)+eps)，再 Div(1, vMean) 得 rstd=1/sqrt(...)，unroll 多段并行。

**片段 1** (行 566-589):

```cpp
LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();
{
    pregMask = UpdateMask<float>(meanSreg);
    DataCopy(mainA, workAddr + 0);
    ReduceSum(vMean, mainA, pregMask);
    Muls(vMean, vMean, avgFactor, pregMerge);
    Adds(vMean, vMean, epsilon, pregMerge);
    Sqrt(vMean, vMean, pregMerge);
    Duplicate(vDupReg, float(1.0), pregMerge);
    Div(rstdReg, vDupReg, vMean, pregMerge);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(rstdAddr + offset, rstdReg, pregMerge);
}
// unroll part
{
    pregMask1 = UpdateMask<float>(meanSreg1);
    DataCopy(mainA3, workAddr1 + 0);
    ReduceSum(vMean3, mainA3, pregMask1);
    Muls(vMean3, vMean3, avgFactor, pregMerge1);
    Adds(vMean3, vMean3, epsilon, pregMerge1);
    Sqrt(vMean3, vMean3, pregMerge1);
    Duplicate(vDupReg3, float(1.0), pregMerge1);
    Div(rstdReg3, vDupReg3, vMean3, pregMerge1);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(rstdAddr1 + offset, rstdReg3, pregMerge1);
}
```

**片段 2** (行 665-676):

```cpp
LocalMemBar<MemType::VEC_STORE, MemType::VEC_LOAD>();
{
    pregMask1 = UpdateMask<float>(meanSreg1);
    DataCopy(mainA1, workAddr1 + 0);
    ReduceSum(vMean1, mainA1, pregMask1);
    Muls(vMean1, vMean1, avgFactor, pregMerge1);
    Adds(vMean1, vMean1, epsilon, pregMerge1);
    Sqrt(vMean1, vMean1, pregMerge1);
    Duplicate(vDupReg1, float(1.0), pregMerge1);
    Div(rstdReg1, vDupReg1, vMean1, pregMerge1);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(rstdAddr1 + tailOffset, rstdReg1, pregMerge1);
}
```

**要点**: 1) 3 实参原位开方 (dst==src=vMean)；2) LocalMemBar 保证 VEC_STORE→VEC_LOAD 顺序后再读；3) StoreDist::DIST_FIRST_ELEMENT_B32 只存首元素（rstd 为标量）。

### Sqrt 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| complex_abs | Abs, Add, Cast, CastTrait, Compare | 复数模长 sqrt(re²+im²)，含 subnormal 归一化与 0 值兜底 | __aicore__ |
| cdist | Add, CreateMask, Duplicate, LoadAlign, MaskMergeMode | 带 SqrtSpecificMode 结构体指针 + mask 的距离开方 | __VEC_SCOPE__ |
| pow | Cast, DataCopy, Div, Duplicate, LoadDist | 模板<float,ZEROING> 开方后 Div 求 rsqrt | __aicore__ |
| random_common | DataCopy, Ln, LoadDist, MaskReg, Maxs | Box-Muller sqrt(-2·ln(max(u,eps)))，mask 控制尾元素 | __aicore__ |
| rsqrt | DataCopy, Div, DivSpecificMode, Duplicate, MaskMergeMode | Sqrt + Div(1,sqrt) 高精度 rsqrt，DivSpecificMode 控算法 | __aicore__ |
| stateless_random_normal_v2 | DataCopy, Ln, LoadDist, MaskReg, Maxs | Box-Muller sqrt(-2·ln(u))，__VEC_SCOPE__ 上下文 | __VEC_SCOPE__ |
| pow | Cast, DataCopy, LoadDist, MaskMergeMode, MaskReg | 模板<float,ZEROING> 直接开方，half 先 Cast 到 float | __aicore__ |
| global_lp_pool | Exp, Ln, LoadAlign, MaskReg, Muls | Lp 池化最终开方 (dst==src 原位)，mask 控制尾批 | __VEC_SCOPE__ |
| euclidean_norm | Cast, LoadAlign, MaskReg, RegTensor | L2 范数开方 + 多类型 Cast/StoreAlign 分支 | __simd_vf__ |
| batch_norm | Add, Adds, Div, Mul, Muls | 2 实参 Sqrt 求 rstd 初值，牛顿迭代精修 | __aicore__ |
| batch_norm_v3 | Add, Adds, Div, Mul, Muls | 2 实参 Sqrt 求 rstd 初值，half/float 分支存储 saveVar | __aicore__ |
| instance_norm | Adds, Div, Maxs, Mul, Muls | 2 实参 Sqrt 求 rstd，Maxs 防过小 + Select 处理 0/inf | __aicore__ |
| group_norm_silu | Adds, Div, MaskPattern, Mul, Muls | 2 实参 Sqrt + VL1 单元素掩码，高精度牛顿 rstd | __aicore__ |
| apply_adam_d | Adds, Div, Duplicate, Muls, RegTensor | Adam 偏差校正 sqrt(1-beta2^t) 算 lr_t | __aicore__ |
| add_rms_norm | Add, Adds, Div, Muls | RMSNorm rstd=1/sqrt(mean(x²)+eps)，原位开方 | __aicore__ |
