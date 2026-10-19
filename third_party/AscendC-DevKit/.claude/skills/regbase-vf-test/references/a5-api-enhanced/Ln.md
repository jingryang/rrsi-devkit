# Ln

**页面ID:** atlasascendc_api_07_0348  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0348.html

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

根据mask对输入数据src进行求自然对数操作，将结果写入dst。计算公式如下：

![](images/atlasascendc_api_07_0348_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, auto mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Ln(U& dstReg, U& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 |
| mode | 可配置为MaskMergeMode的枚举或LnSpecificMode的结构体指针。- MaskMergeMode，选择MERGING模式或ZEROING模式。  - ZEROING，mask未筛选的元素在dstReg中置零。  - MERGING，暂不支持。 - LnSpecificMode，定义如下：``` enum class LnAlgo {     INTRINSIC = 0,     PRECISION_1ULP_FTZ_TRUE,     PRECISION_1ULP_FTZ_FALSE, }; struct LnSpecificMode{     MaskMergeMode mrgMode = MaskMergeMode::ZEROING,     LnAlgo algo = LnAlgo::INTRINSIC; }; ```   - mrgMode：选择MERGING模式或ZEROING模式。  - algo：用于配置Subnormal模式。    - LnAlgo::INTRINSIC、LnAlgo::PRECISION_1ULP_FTZ_TRUE，使用单指令计算得出结果，所有Subnormal被近似为0。    - LnAlgo::PRECISION_1ULP_FTZ_FALSE，支持Subnormal数据计算。 |
| U | 源操作数和目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

- src输入为-0时，输出-inf

#### 调用示例

```
template<typename T>
__simd_vf__ inline void LnVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    // Subnormal模式
    // static constexpr AscendC::Reg::LnSpecificMode mode = {MaskMergeMode::ZEROING, LnAlgo::PRECISION_1ULP_FTZ_FALSE};
    for (uint16_t i = 0; i < repeatTimes; i++) {     
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Ln(dstReg, srcReg, mask);
        // Subnormal模式
        // AscendC::Reg::Ln<T, &mode>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Ln 实例

### 实例 1：xlog1py::Xlog1pyVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, Adds, Compare, CreateAddrReg, LoadAlign, MaskReg, Mul, RegTensor, Select, StoreAlign, Sub, UpdateMask
- **Ln 调用次数**: 3
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 xlog1py 算子中按 mask 对 y+1 求自然对数，作为 x·log(1+y) 的中间结果，并配合 Compare/Select 处理 x=0 与 y=NaN 的边界。

（行 299-329）

```cpp
for (uint16_t i = 0; i < repeatTimes; ++i) {
    aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
    mask = AscendC::Reg::UpdateMask<T>(count);

    AscendC::Reg::LoadAlign(regX, srcXAddr, aReg);
    AscendC::Reg::LoadAlign(regY, srcYAddr, aReg);

    // S1: Adds(y, 1.0) → y+1
    AscendC::Reg::Adds(regYp1, regY, scalar_one, mask);

    // S2: Ln(y+1) → log(1+y)
    AscendC::Reg::Ln(regLogY, regYp1, mask);

    // S3: Mul(x, log_y) → mul_res
    AscendC::Reg::Mul(regMul, regX, regLogY, mask);

    // S4: Compare(x, 0, EQ) → mask_eq
    AscendC::Reg::Sub(regZero, regX, regX, mask);
    AscendC::Reg::Compare<float, AscendC::CMPMODE::EQ>(maskEq, regX, regZero, mask);

    // S5: Select(mask_eq, 0, mul_res) → res0
    AscendC::Reg::Select<float>(regRes0, regZero, regMul, maskEq);

    // S6: Compare(y, y, EQ) → mask_nan (NaN≠NaN → mask=0)
    AscendC::Reg::Compare<float, AscendC::CMPMODE::EQ>(maskNaN, regY, regY, mask);

    // S7: Select(mask_nan, res0, y) → final
    AscendC::Reg::Select<float>(regFinal, regRes0, regY, maskNaN);

    AscendC::Reg::StoreAlign(dstAddr, regFinal, aReg, mask);
}
```

**要点**: ①先用 Adds(regYp1, regY, 1.0) 再 Ln 得到 log(1+y)，对应 log1p 语义；②Ln 使用 3 实参形式 (dstReg, srcReg, mask)，未显式传 mode 故走默认 ZEROING；③通过 Compare(y,y,EQ) 检测 NaN（NaN≠NaN→mask=0）并用 Select 兜底输出 y，避免 NaN 污染。

### 实例 2：xlogy::XlogyVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, Compare, CreateAddrReg, LoadAlign, MaskReg, Mul, RegTensor, Select, StoreAlign, Sub, UpdateMask
- **Ln 调用次数**: 3
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 xlogy 算子中按 mask 对 y 求自然对数，再与 x 相乘得到 x·log(y)，并用 Compare/Select 处理 x=0 与 y=NaN 的边界。

（行 337-364）

```cpp
for (uint16_t i = 0; i < repeatTimes; ++i) {
    aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
    mask = AscendC::Reg::UpdateMask<T>(count);

    AscendC::Reg::LoadAlign(regX, srcXAddr, aReg);
    AscendC::Reg::LoadAlign(regY, srcYAddr, aReg);

    // S1: Ln(y) → log_y
    AscendC::Reg::Ln(regLogY, regY, mask);

    // S2: Mul(x, log_y) → mul_res
    AscendC::Reg::Mul(regMul, regX, regLogY, mask);

    // S3: Compare(x, 0, EQ) → mask_eq
    AscendC::Reg::Sub(regZero, regX, regX, mask);  // regZero = x - x = 0
    AscendC::Reg::Compare<float, AscendC::CMPMODE::EQ>(maskEq, regX, regZero, mask);

    // S4: Select(mask_eq, 0, mul_res) → res0  (maskEq? zero : mul_res)
    AscendC::Reg::Select<float>(regRes0, regZero, regMul, maskEq);

    // S5: Compare(y, y, EQ) → mask_nan (NaN≠NaN → mask=0)
    AscendC::Reg::Compare<float, AscendC::CMPMODE::EQ>(maskNaN, regY, regY, mask);

    // S6: Select(mask_nan, res0, y) → final  (maskNaN? res0 : y)
    AscendC::Reg::Select<float>(regFinal, regRes0, regY, maskNaN);

    AscendC::Reg::StoreAlign(dstAddr, regFinal, aReg, mask);
}
```

**要点**: ①直接 Ln(regLogY, regY, mask) 求 log(y)（区别于 xlog1py 的 y+1）；②x=0 时通过 Compare(x,0,EQ)+Select 强制输出 0，避免 0·log(0)=0·(−inf) 产生 NaN；③y=NaN 时用 Compare(y,y,EQ) 检测并 Select 输出 y=NaN。

### 实例 3：global_lp_pool::GeneralPowerVf

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Exp, LoadAlign, LocalMemBar, MaskReg, MemType, Muls, RegTensor, StoreAlign, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 global Lp pooling 的幂变换阶段，对向量 vx 逐元素求自然对数（in-place），为后续按 p 次幂求和做准备，即 ‖x‖_p 的对数化处理。

（行 309-315）

```cpp
for (uint16_t i = 0; i < pwrLoopNum; i++) {
    mask = Reg::UpdateMask<float>(remain);
    Reg::LoadAlign<float>(vx, pwrAddr + static_cast<int32_t>(i) * VF_VL_F32);
    Reg::Ln(vx, vx, mask);
    Reg::StoreAlign<float>(pwrAddr + static_cast<int32_t>(i) * VF_VL_F32, vx, mask);
}
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
```

**要点**: ①Ln(vx, vx, mask) 原地写回，源/目寄存器复用同一 RegTensor；②按 UpdateMask(remain) 处理尾部不足一个 repeat 的元素；③循环后用 LocalMemBar<VEC_STORE, VEC_LOAD> 保证 store 完成后再 load，避免 RAW 冒险。

### 实例 4：global_lp_pool::GeneralPowerVf

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Exp, LoadAlign, LocalMemBar, MaskReg, MemType, Muls, RegTensor, StoreAlign, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 同实例 3 的 Lp pooling 幂变换逻辑，但位于 __VEC_SCOPE__ 上下文，使用裸名 Reg::Ln 调用，对 vx 原地求自然对数。

（行 309-315）

```cpp
for (uint16_t i = 0; i < pwrLoopNum; i++) {
    mask = Reg::UpdateMask<float>(remain);
    Reg::LoadAlign<float>(vx, pwrAddr + static_cast<int32_t>(i) * VF_VL_F32);
    Reg::Ln(vx, vx, mask);
    Reg::StoreAlign<float>(pwrAddr + static_cast<int32_t>(i) * VF_VL_F32, vx, mask);
}
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
```

**要点**: ①与实例 3 代码相同，仅来源类型为 __VEC_SCOPE__（裸名 Reg:: 前缀）；②Ln 用 3 实参 (dst, src, mask) 默认 ZEROING；③LocalMemBar 同步 store/load 屏障。

### 实例 5：log_softmax_v2::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CreateMask, DataCopy, LoadDist, MaskPattern, MaskReg, RegTensor, StoreDist, Sub, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 log_softmax_v2 中对求和寄存器 sumReg 求 ln(sum)，作为 softmax 归一化对数域的减项，后续每个元素减去 max 与 ln(sum) 得到 log-softmax 输出。

（行 328-365）

```cpp
__VEC_SCOPE__
{
    AscendC::Reg::RegTensor<Tx> vreg0;
    AscendC::Reg::RegTensor<float> sumReg, lnReg, maxReg, vreg1, vreg2, vreg3;
    AscendC::Reg::RegTensor<Ty> vreg4;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::MaskReg maskAll = Reg::CreateMask<float, AscendC::Reg::MaskPattern::ALL>();

    uint32_t width = ubFactor;
    uint16_t repeatTimes = CeilDivision(ubFactor, VL_FP32);

    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_BRC_B32>(maxReg, xMaxPtr);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_BRC_B32>(sumReg, xSumPtr);
    AscendC::Reg::Ln(lnReg, sumReg, maskAll);

    for (uint16_t j = 0; j < repeatTimes; j++) {
        mask = AscendC::Reg::UpdateMask<float>(width);
        auto xAddr = xPtr + j * VL_FP32;
        auto yAddr = yPtr + j * VL_FP32;

        if constexpr (xToFp32_) {
            AscendC::Reg::DataCopy<Tx, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vreg0, xAddr);
            AscendC::Reg::Cast<float, Tx, castTraitFp16ToFp32>(vreg1, vreg0, mask);
        } else {
            AscendC::Reg::DataCopy(vreg1, xAddr);
        }

        AscendC::Reg::Sub(vreg2, vreg1, maxReg, mask);
        AscendC::Reg::Sub(vreg3, vreg2, lnReg, mask);

        if constexpr (yToFp32_) {
            AscendC::Reg::DataCopy(yAddr, vreg3, mask);
        } else {
            AscendC::Reg::Cast<Ty, float, castTraitFp32ToFp16>(vreg4, vreg3, mask);
            AscendC::Reg::DataCopy<Ty, AscendC::Reg::StoreDist::DIST_PACK_B32>(yAddr, vreg4, mask);
        }
    }
}
```

**要点**: ①先 DataCopy 广播载入 maxReg/sumReg，再 Reg::Ln(lnReg, sumReg, maskAll) 求全量 mask 的 ln(sum)；②循环内 Sub(vreg2, x, max) 再 Sub(vreg3, vreg2, lnReg) 完成 log_softmax = x − max − ln(sum)；③配合 Cast 处理 fp16/fp32 类型转换。

### 实例 6：random_common::BoxMullerFloatSIMD

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, LoadDist, MaskReg, Maxs, Muls, PostLiteral, RegTensor, Sqrt, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 Box-Muller 正态随机数生成中，对均匀分布样本 u 先 Maxs 截断到 ≥ε 再 Ln 求 ln(u)，配合 Muls/Sqrt 得到标准正态分布的极坐标变换半径 √(−2·ln(u))。

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

**要点**: ①Maxs(vreg2, vreg0, epsScalar) 防止 u=0 导致 ln(0)=−inf；②Ln(vreg3, vreg2, mask) 求 ln(u)；③Muls(vreg5, vreg3, −2.0) 再 Sqrt 得 √(−2·ln(u))，与 Muls(vreg4, vreg1, 2π) 组合为 Box-Muller 极坐标变换。

### 实例 7：random_common::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: DataCopy, LoadDist, MaskReg, Maxs, Muls, PostLiteral, RegTensor, Sqrt, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 同实例 6 的 Box-Muller 正态采样逻辑，位于 __VEC_SCOPE__ 上下文，对截断后的均匀样本求 ln(u) 并组合 Muls/Sqrt 生成标准正态分布。

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

**要点**: ①与实例 6 代码相同，来源类型为 __VEC_SCOPE__；②Maxs 保证 ln 的定义域 u>0；③Ln 与 Muls/Sqrt 构成极坐标半径 √(−2·ln(u))。

### 实例 8：stateless_random_normal_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: DataCopy, LoadDist, MaskReg, Maxs, Muls, PostLiteral, RegTensor, Sqrt, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在无状态随机正态分布算子中复用 Box-Muller 变换，对均匀分布样本截断后求 ln(u)，再 Muls/Sqrt 得到标准正态样本。

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

**要点**: ①Maxs 截断到 ≥ε 避免 ln(0)=−inf；②Ln(vreg3, vreg2, mask) 求 ln(u)；③与 Muls(2π) 和 Muls(−2)+Sqrt 组合输出极坐标形式的正态样本。

### 实例 9：log_softmax_v2::CalcOutput

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopy, LoadDist, MaskReg, RegTensor, StoreDist, Sub, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 log_softmax_v2 的 CalcOutput 中对每列求和 sumReg 求 ln(sum)，再让每个元素减去 ln(sum) 完成对数 softmax 归一化。

（行 177-197）

```cpp
for (uint16_t j = 0; j < aLoopTimes; j++) { // 列
    mask = Reg::UpdateMask<float>(sreg);
    Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(sumReg,
                                                             (__local_mem__ float*)sumAddr + j * VL_FP32);
    Reg::Ln(lnReg, sumReg, mask);

    for (uint16_t i = 0; i < rLoopTimes; i++) { // 行
        uint32_t offset = j * VL_FP32 + i * tileA0LenLocal;

        Reg::DataCopy(reg1, tmpAddr2 + offset);
        Reg::Sub(reg1, reg1, lnReg, mask);

        if constexpr (yToFp32_) {
            Reg::DataCopy(tmpAddrTy + offset, reg1, mask);
        } else { // fp16、bf16
            Reg::RegTensor<Ty> xFp16;
            Reg::Cast<Ty, float, castTraitFp32ToFp16>(xFp16, reg1, mask);
            Reg::DataCopy<Ty, Reg::StoreDist::DIST_PACK_B32>(tmpAddrTy + offset, xFp16, mask);
        }
    }
}
```

**要点**: ①按列循环 UpdateMask 后 DataCopy 载入 sumReg，Reg::Ln(lnReg, sumReg, mask) 求列和的对数；②内层行循环 Sub(reg1, reg1, lnReg) 逐元素减 ln(sum)；③配合 Cast 处理 fp16/bf16 输出类型。

### 实例 10：log_softmax_v2::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, DataCopy, LoadDist, MaskReg, RegTensor, StoreDist, Sub, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 同实例 9 的 log_softmax 归一化逻辑，位于 __VEC_SCOPE__ 上下文，对列和求 ln(sum) 后逐元素相减。

（行 177-197）

```cpp
for (uint16_t j = 0; j < aLoopTimes; j++) { // 列
    mask = Reg::UpdateMask<float>(sreg);
    Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(sumReg,
                                                             (__local_mem__ float*)sumAddr + j * VL_FP32);
    Reg::Ln(lnReg, sumReg, mask);

    for (uint16_t i = 0; i < rLoopTimes; i++) { // 行
        uint32_t offset = j * VL_FP32 + i * tileA0LenLocal;

        Reg::DataCopy(reg1, tmpAddr2 + offset);
        Reg::Sub(reg1, reg1, lnReg, mask);

        if constexpr (yToFp32_) {
            Reg::DataCopy(tmpAddrTy + offset, reg1, mask);
        } else { // fp16、bf16
            Reg::RegTensor<Ty> xFp16;
            Reg::Cast<Ty, float, castTraitFp32ToFp16>(xFp16, reg1, mask);
            Reg::DataCopy<Ty, Reg::StoreDist::DIST_PACK_B32>(tmpAddrTy + offset, xFp16, mask);
        }
    }
}
```

**要点**: ①与实例 9 代码相同，来源类型 __VEC_SCOPE__；②Ln(lnReg, sumReg, mask) 求列和对数；③Sub 减去 ln(sum) 配合 Cast 输出。

### 实例 11：global_lp_pool::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Exp, LoadAlign, MaskReg, Muls, RegTensor, Sqrt, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 global Lp pooling 中对向量 f32Reg 原地求 ln(x)，再 Muls(invP) 缩放后 Exp 还原，实现 x^(1/p) 的对数域幂变换。

（行 438-446）

```cpp
for (uint16_t i = 0; i < repeatTime; ++i) {
    int32_t off = static_cast<int32_t>(i) * VF_VL_F32;
    mask = AscendC::Reg::UpdateMask<float>(remaining);
    AscendC::Reg::LoadAlign(f32Reg, rootPtr + off);
    AscendC::Reg::Ln(f32Reg, f32Reg, mask);
    AscendC::Reg::Muls(f32Reg, f32Reg, static_cast<float>(invPVal), mask);
    AscendC::Reg::Exp(f32Reg, f32Reg, mask);
    PostCastAndStoreVf<D_T, kNeedCast>(f32Reg, mask, outPtr, off);
}
```

**要点**: ①Ln(f32Reg, f32Reg, mask) 原地求 log(x)；②Muls(f32Reg, f32Reg, invPVal) 得 (1/p)·log(x)；③Exp(f32Reg, f32Reg, mask) 还原为 x^(1/p)，即 ‖x‖_p 的逐元素开 p 次方。

### 实例 12：global_lp_pool::PostElewiseVfBody

- **来源类型**: `__aicore__`
- **共现 API**: Exp, LoadAlign, MaskReg, Muls, RegTensor, Sqrt, UpdateMask
- **Ln 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 同实例 11 的 Lp pooling 幂变换逻辑（Ln→Muls(1/p)→Exp），位于 __aicore__ 上下文，对 f32Reg 原地求对数后还原为 x^(1/p)。

（行 438-446）

```cpp
for (uint16_t i = 0; i < repeatTime; ++i) {
    int32_t off = static_cast<int32_t>(i) * VF_VL_F32;
    mask = AscendC::Reg::UpdateMask<float>(remaining);
    AscendC::Reg::LoadAlign(f32Reg, rootPtr + off);
    AscendC::Reg::Ln(f32Reg, f32Reg, mask);
    AscendC::Reg::Muls(f32Reg, f32Reg, static_cast<float>(invPVal), mask);
    AscendC::Reg::Exp(f32Reg, f32Reg, mask);
    PostCastAndStoreVf<D_T, kNeedCast>(f32Reg, mask, outPtr, off);
}
```

**要点**: ①与实例 11 代码相同，来源类型 __aicore__；②Ln 原地写回，配合 Muls/Exp 在对数域完成开 p 次方；③UpdateMask(remaining) 处理尾部元素。

### Ln 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| xlog1py | AddrReg, Adds, Compare, CreateAddrReg | Adds 预处理 y+1 → Ln 求 log(1+y) → Mul 缩放，配合 Compare/Select 处理 x=0 与 NaN 边界（log1p 实现） | __simd_vf__ |
| xlogy | AddrReg, Compare, CreateAddrReg, LoadAlign | Ln 求 log(y) → Mul 与 x 相乘，配合 Compare/Select 处理 x=0 与 NaN 边界（xlogy 实现） | __simd_vf__ |
| global_lp_pool | Abs, Exp, LoadAlign, LocalMemBar | 对向量原地 Ln 求 log(x)，配合 Muls/Exp 完成 Lp 范数的幂变换（global_lp_pool） | __aicore__ |
| global_lp_pool | Abs, Exp, LoadAlign, LocalMemBar | 同 aicore 版本，__VEC_SCOPE__ 下裸名 Reg::Ln 原地求 log(x) 做 Lp 幂变换（global_lp_pool） | __VEC_SCOPE__ |
| log_softmax_v2 | Cast, CreateMask, DataCopy, LoadDist | Ln(sumReg) 求全量 ln(sum) → 循环内 Sub 逐元素 x−max−ln(sum)（log_softmax_v2） | __VEC_SCOPE__ |
| random_common | DataCopy, LoadDist, MaskReg, Maxs | Maxs 截断 ε → Ln 求 ln(u) → Muls(−2) → Sqrt 得 √(−2lnu)，Box-Muller 正态采样（random_common） | __aicore__ |
| random_common | DataCopy, LoadDist, MaskReg, Maxs | 同 aicore 版本，__VEC_SCOPE__ 下 Box-Muller：Maxs→Ln→Muls(−2)→Sqrt（random_common） | __VEC_SCOPE__ |
| stateless_random_normal_v2 | DataCopy, LoadDist, MaskReg, Maxs | Maxs→Ln(lnu)→Muls(−2)→Sqrt，Box-Muller 生成无状态正态分布（stateless_random_normal_v2） | __VEC_SCOPE__ |
| log_softmax_v2 | Cast, DataCopy, LoadDist, MaskReg | 按列 Ln(sum) → 行循环 Sub 逐元素减 ln(sum)（log_softmax_v2 CalcOutput） | __aicore__ |
| log_softmax_v2 | Cast, DataCopy, LoadDist, MaskReg | 同 aicore 版本，__VEC_SCOPE__ 下按列 Ln(sum) → Sub 减 ln(sum)（log_softmax_v2） | __VEC_SCOPE__ |
| global_lp_pool | Exp, LoadAlign, MaskReg, Muls | Ln(x) → Muls(1/p) → Exp 还原 x^(1/p)，Lp 池化的对数域幂变换（global_lp_pool） | __VEC_SCOPE__ |
| global_lp_pool | Exp, LoadAlign, MaskReg, Muls | 同 __VEC_SCOPE__ 版本，__aicore__ 下 Ln→Muls(1/p)→Exp 实现 x^(1/p)（global_lp_pool） | __aicore__ |
