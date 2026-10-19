# Max

**页面ID:** atlasascendc_api_07_0360  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0360.html

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

根据mask对源操作数srcReg0、srcReg1进行按元素求最大值操作，将结果写入目的操作数dstReg。计算公式如下：

![](images/atlasascendc_api_07_0360_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Max(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/uint64_t/int64_t/half/float/bfloat16_t |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING, mask未筛选的元素在dstReg中置零。- MERGING, 当前不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

输入srcReg0为-0, srcReg1为+0的情况下，输出dstReg为+0。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MaxVf(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;   ;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Max(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Max 实例

### 实例 1：dynamic_mx_quant::AscendC::ScalarCountLeadingZero

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, Copy, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, DataCopyUnAlignPre, DeInterleave, Duplicate, Interleave, LocalMemBar, MaskMergeMode, MaskOr, MaskPattern, MaskReg, Maxs, MemType, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Max 调用次数**: 8
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: 在 dynamic_mx_quant 的 FP8 量化路径中，先按行循环用 Max 累积各数据块的指数位最大值，再通过 DataCopy+LocalMemBar 回读、配合 DataCopyUnAlign 做二分折叠，逐级用 Max 求出整行最大指数，作为后续 scale 计算的输入。

（行 466-497）

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(regLoop - 1); i++) {
    this->template LoadData<RoundMode::UNKNOWN, roundMode>(xAddr, i * dataLenSingleLoop, x, pnumMask);
    Reg::And(exp, (Reg::RegTensor<uint16_t>&)x, tmp16RegTensor, pnumMask);
    Reg::Max(expMax, expMax, exp, pnumMask);
}
this->template LoadData<RoundMode::UNKNOWN, roundMode>(xAddr, (regLoop - 1) * dataLenSingleLoop, x,
                                                       tailPnumMask);
Reg::And(exp, (Reg::RegTensor<uint16_t>&)x, tmp16RegTensor, tailPnumMask);
Reg::Max(exp, expMax, exp, tailPnumMask);
Reg::Copy<uint16_t, Reg::MaskMergeMode::MERGING>(expMax, exp, tailPnumMask);

// 二分法求rowsSingleLoop行中的最大行
Reg::DataCopy(maxExpAddr, expMax, pnumMask);
Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
uint32_t maskNum = dataLenSingleLoop - expOffset;
Reg::MaskReg mask = Reg::UpdateMask<uint16_t>(maskNum);
Reg::DataCopyUnAlignPre(u0, maxExpAddr + expOffset);
Reg::DataCopyUnAlign(exp, u0, maxExpAddr + expOffset);
Reg::Max(exp, expMax, exp, mask);
Reg::Copy<uint16_t, Reg::MaskMergeMode::MERGING>(expMax, exp, mask);
for (uint16_t i = 0; i < loopSize; i++) {
    Reg::DataCopy(maxExpAddr, expMax, pnumMask);
    Reg::LocalMemBar<Reg::MemType::VEC_STORE, Reg::MemType::VEC_LOAD>();
    expOffset /= DIGIT_TWO;
    maskNum = expOffset;
    mask = Reg::UpdateMask<uint16_t>(maskNum);
    Reg::DataCopyUnAlignPre(u0, maxExpAddr + expOffset);
    Reg::DataCopyUnAlign(exp, u0, maxExpAddr + expOffset);
    Reg::Max(expMax, expMax, exp, mask);
}
maskNum = static_cast<uint32_t>(dataLen);
mask = Reg::CreateMask<uint32_t>();
```

**要点**:
- Max 第 4 个实参 pnumMask/tailPnumMask/Mask 来自 UpdateMask，控制尾块有效元素；二分折叠阶段 mask 宽度随 expOffset 折半递减。
- 与 And 配合先取指数位（absForX 类掩码），Max 在 uint16_t 视图上比较指数位大小，等价于求浮点绝对值最大。
- 二分折叠每轮需 DataCopy 落盘 + LocalMemBar<VEC_STORE,VEC_LOAD> 做存储→加载同步，再 Max 合并，共 loopSize 轮。

### 实例 2：dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, CastTrait, Compare, CompareScalar, CreateMask, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, HighLowPart, Interleave, MaskAnd, MaskMergeMode, MaskPattern, MaskReg, MaskXor, Maxs, Mul, Muls, Pack, RegLayout, RegTensor, SatMode, Select, ShiftLefts, ShiftRights, Sub, UnalignReg, UpdateMask
- **Max 调用次数**: 4
- **参数模式**: `T0_A4_M0_TYPEint16_t+uint16_t`（实参 4 个，类型: uint16_t, int16_t）
- **语义（待补充）**: dynamic_mx_quant 非尾轴 FP8 路径中，按 block 循环 LoadData 取数，用 And 提取 BF16 指数位后，用 Max 在 uint16_t 视图上把当前块指数与累积最大值比较，逐块更新 expMaxreShareExpFP16YOneRegTensor 得到全行最大指数。

（行 554-561）

```cpp
for (uint16_t j = 1; j < static_cast<uint16_t>(blockCount); j++) {
    this->template LoadData<RoundMode::CAST_TRUNC, roundMode>(xAddr, j * dataLen + i * vfNum32, x, p0);
    Reg::And((Reg::RegTensor<uint16_t>&)expScaleMxYZeroRegTensor, (Reg::RegTensor<uint16_t>&)x, absMaskBF16,
             p0);
    Reg::Max(expMaxreShareExpFP16YOneRegTensor,
             (Reg::RegTensor<uint16_t>&)expMaxreShareExpFP16YOneRegTensor,
             (Reg::RegTensor<uint16_t>&)expScaleMxYZeroRegTensor, p0);
}
```

**要点**:
- Max 操作数以 (RegTensor<uint16_t>&) 强转视图比较指数位，源/目的类型一致（int16_t+uint16_t 组合）。
- 第 4 个实参 p0 为全量 mask（blockCount 内每块等宽），不随尾块变化。
- Max 累积写回同一寄存器 expMaxreShareExpFP16YOneRegTensor，形成 reduce-by-iteration 模式。

### 实例 3：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, Gather, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Max 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: SwiGLU 反向双轴 MX 量化中，对 DataCopy 交织搬入的相邻两路数据分别取绝对值，用 Max 先求两路配对最大值（-1 轴）并 ReduceMaxWithDataBlock 压缩，再用 Max 把两路各自累积到 absMax1Dim2/absMax2Dim2（-2 轴），实现双轴绝对值最大值统计。

（行 893-909）

```cpp
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
    Reg::Max(absMax2Dim2, absMax2Dim2, regU16_1, maskAll);
}
Reg::StoreUnAlignPost(tempMaxAddr, ureg, 0);
```

**要点**:
- Max 第 4 参 maskAll 为全 1 mask，配合 PostLiteral::POST_MODE_UPDATE 的 DataCopy 一次取 256B 交织数据。
- 三处 Max 分工：regU16_2=配对 max（送 ReduceMax）、absMax1Dim2/absMax2Dim2=逐列累积 max。
- 输出经 StoreUnAlign(post update) 按 8 元素步进写出，StoreUnAlignPost 收尾刷空缓存。

### 实例 4：dynamic_quant::ComputeVF

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, Adds, Cast, CreateMask, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Min, Mul, Muls, Pack, PostLiteral, ReduceMax, ReduceMin, RegTensor, StoreDist, Sub, UnalignReg, UpdateMask
- **Max 调用次数**: 8
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: dynamic_quant 逐 VF 求绝对最大/最小值：片段1 对 x*smooth 取 Abs 后用 Max 累积 vreg7，再 ReduceMax+Muls 得 scale；片段2 在非对称分支同时用 Max/Min 累积，尾块单独处理后再用 Max 合并主体与尾块 reduce 结果，得到最终 max/min 求 (max-min)。

**片段 1** (行 333-346):

```cpp
for (uint16_t j = 0; j < vfLoop; j++) {
    preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg1, xAddr + multiRow * rowCount + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, smoothAddr + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg0);
    AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg0);
    AscendC::Reg::Abs(vreg6, vreg3, preg0);
    AscendC::Reg::Max(vreg7, vreg6, vreg7, preg1);
}
AscendC::Reg::ReduceMax(vreg8, vreg7, preg1);
AscendC::Reg::Muls(vreg9, vreg8, maxValue, preg1);
```

**片段 2** (行 354-385):

```cpp
for (uint16_t j = 0; j < vfLoop - 1; j++) {
    preg0 = AscendC::Reg::UpdateMask<float>(sreg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg1, xAddr + multiRow * rowCount + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg0);
    AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg2, smoothAddr + j * VL);
    AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg0);
    AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg0);
    AscendC::Reg::Max(vreg7, vreg3, vreg7, preg1);
    AscendC::Reg::Min(vregMinX, vreg3, vregMinX, preg1);
}
AscendC::Reg::ReduceMax(vregReduceMaxX, vreg7, preg1);
AscendC::Reg::ReduceMin(vregReduceMinX, vregMinX, preg1);

preg4 = AscendC::Reg::UpdateMask<float>(tailNum);
AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
    vreg1, xAddr + multiRow * rowCount + (vfLoop - 1) * VL);
AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg3, vreg1, preg4);
AscendC::Reg::DataCopy<xDtype, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
    vreg2, smoothAddr + (vfLoop - 1) * VL);
AscendC::Reg::Cast<float, xDtype, castTraitB16ToB32>(vreg4, vreg2, preg4);
AscendC::Reg::Mul(vreg3, vreg3, vreg4, preg4);
AscendC::Reg::Max(vreg7, vreg3, vreg7, preg4);
AscendC::Reg::Min(vregMinX, vreg3, vregMinX, preg4);
AscendC::Reg::ReduceMax(vregReduceMaxXTail, vreg7, preg4);
AscendC::Reg::ReduceMin(vregReduceMinXTail, vregMinX, preg4);

AscendC::Reg::Max(vregFinalMax, vregReduceMaxX, vregReduceMaxXTail, preg5);
AscendC::Reg::Min(vregFinalMin, vregReduceMinX, vregReduceMinXTail, preg5);

AscendC::Reg::Sub(vregMaxSubMin, vregFinalMax, vregFinalMin, preg5);
```

**要点**:
- Max 第 4 参 preg0/preg1/preg4/preg5 分别对应主体循环、累积、尾块、合并不同宽度 mask，需按 UpdateMask 结果使用。
- 对称量化(isSymmetrical)只求 Max（配合 Abs+Muls），非对称量化同时求 Max+Min，最后 Max(max, maxTail) 合并尾块。
- 源操作数类型 float（先 Cast half/bf16→float），Max 在 float 视图上比较真实数值大小。

### 实例 5：dynamic_block_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, CompareScalar, CreateMask, DataCopy, Div, DivSpecificMode, Duplicate, HighLowPart, Interleave, MaskMergeMode, MaskReg, MaskUnPack, Min, PostLiteral, ReduceMax, RegLayout, RegTensor, SatMode, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **Max 调用次数**: 4
- **参数模式**: `T2_A4_M1_TYPEint32_t+uint32_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: uint32_t, int32_t）
- **语义（待补充）**: dynamic_block_quant 单行 kernel 中，按 VL 循环 DataCopy 取数，用 And 取指数位后，以显式模板 <uint32_t, MaskMergeMode::MERGING> 调用 Max 在 uint32_t 视图上累积块内绝对值最大值；片段2 对 fp16 输入用 IN_TYPE 模板参数版 Max 同样累积。

**片段 1** (行 339-350):

```cpp
for (uint16_t vlLoopIdx = 0; vlLoopIdx < normalLoopNum; vlLoopIdx++) {
    inputMaskReg = AscendC::Reg::UpdateMask<IN_TYPE>(curSize);
    AscendC::Reg::DataCopy(vReg0, xLocal + rowIdx * inputColAlign +
                                           colIdx * tilingData_->blockSizeCol + vlLoopIdx * VL);
    AscendC::Reg::And((AscendC::Reg::RegTensor<uint32_t>&)vReg3,
                           (AscendC::Reg::RegTensor<uint32_t>&)vReg0,
                           (AscendC::Reg::RegTensor<uint32_t>&)vRegFp32Max, inputMaskReg);
    AscendC::Reg::Max<uint32_t, AscendC::Reg::MaskMergeMode::MERGING>(
        (AscendC::Reg::RegTensor<uint32_t>&)vReg2,
        (AscendC::Reg::RegTensor<uint32_t>&)vReg2,
        (AscendC::Reg::RegTensor<uint32_t>&)vReg3, inputMaskReg);
}
```

**片段 2** (行 464-475):

```cpp
for (uint16_t vlLoopIdx = 0; vlLoopIdx < normalLoopNum; vlLoopIdx++) {
    inputMaskReg = AscendC::Reg::UpdateMask<IN_TYPE>(curSize);
    AscendC::Reg::DataCopy(vReg0, xLocal + rowIdx * inputColAlign +
                                           colIdx * tilingData_->blockSizeCol + vlLoopIdx * VL);
    AscendC::Reg::And((AscendC::Reg::RegTensor<uint16_t>&)vReg3,
                           (AscendC::Reg::RegTensor<uint16_t>&)vReg0,
                           (AscendC::Reg::RegTensor<uint16_t>&)vRegFp16Max, inputMaskReg);

    AscendC::Reg::Max<IN_TYPE, AscendC::Reg::MaskMergeMode::MERGING>(vReg2, vReg2, vReg3,
                                                                               inputMaskReg);
}
```

**要点**:
- 显式给出模板参数 <uint32_t, MaskMergeMode::MERGING>，是少数启用 MERGING 模式的实例（文档标注 MERGING 当前不支持，此处为源码中存在用法）。
- 两片段对应 fp32/fp16 两种输入精度，Max 累积寄存器 vReg2 跨循环复用，初始需置 0。
- mask inputMaskReg 由 UpdateMask<IN_TYPE>(curSize) 按当前列剩余长度生成，处理尾块对齐。

### 实例 6：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Compares, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Maxs, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Max 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义（待补充）**: fake_quant 逐通道量化中，先算 nudgedMin/nudgedMax，再用 Min+Max 做夹紧 clip：先 Min(x, nudgedMax) 截上界，再 Max(结果, nudgedMin) 截下界，得到 clamped 用于后续 shift 计算。

（行 426-444）

```cpp
// 2.6 nudged_min = (qMin - nudged_zp) * scaleSafe
//     nudged_max = (qMax - nudged_zp) * scaleSafe
AscendC::Reg::Muls<float>(vregNudgedMin, vregNudgedZp, -1.0f, mask);
AscendC::Reg::Adds<float>(vregNudgedMin, vregNudgedMin, qMin, mask);
AscendC::Reg::Mul<float>(vregNudgedMin, vregNudgedMin, vregScaleSafe, mask);

AscendC::Reg::Muls<float>(vregNudgedMax, vregNudgedZp, -1.0f, mask);
AscendC::Reg::Adds<float>(vregNudgedMax, vregNudgedMax, qMax, mask);
AscendC::Reg::Mul<float>(vregNudgedMax, vregNudgedMax, vregScaleSafe, mask);

// -----------------------------------------------------------------
// 阶段 3：主公式
// -----------------------------------------------------------------
// clip：clamped = min(max(x, nudgedMin), nudgedMax)
AscendC::Reg::Min<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregClamped, vregX, vregNudgedMax, mask);
AscendC::Reg::Max<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregClamped, vregClamped, vregNudgedMin,
                                                               mask);
// shift = clamped - nudgedMin
AscendC::Reg::Sub<float>(vregShift, vregClamped, vregNudgedMin, mask);
```

**要点**:
- 显式模板 <float, MaskMergeMode::ZEROING>，mask 未选元素置零（默认模式），符合文档支持。
- Max 与 Min 配对实现 clip(x, lo, hi)=Min(Max(x,lo),hi)，是典型的标量量化夹紧模式。
- 源/目均为 float RegTensor，操作真实数值非指数位视图；Max 调用次数仅 1（单次夹紧）。

### 实例 7：grouped_dynamic_mx_quant::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CastTrait, Compare, CreateMask, Duplicate, Interleave, LoadAlign, MaskMergeMode, MaskPattern, MaskReg, Mul, Pack, RegLayout, RegTensor, SatMode, Select, ShiftRights, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg, UpdateMask
- **Max 调用次数**: 8
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 分组动态 MX 量化非尾轴 FP8 路径中，按 block 循环 LoadAlign 取相邻两路 xRegTensor0/1，half 输入先 Cast→BF16 再 And 取指数位，用 Max 先求两路配对最大值再累积到 expMaxRegTensor，循环结束后用 Compare 检测 inf/zero。

（行 337-353）

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
```

**要点**:
- 两步 Max：expRegTensor=max(x0,x1) 配对，expMaxRegTensor=max(expRegTensor,expMaxRegTensor) 累积，等价于逐块 reduce。
- half 与 bfloat16_t 走不同 And 取指数路径，但 Max 调用统一在 uint16_t 视图上比较指数位。
- 第 4 参 p0 为全量 mask（blockCountLoop 内等宽），循环后 Compare<NE> 判定 inf/零用于后续特殊值处理。

### 实例 8：swiglu_mx_quant::ComputeScaleCuBLASNotLastAxis

- **来源类型**: `__aicore__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, Interleave, LoadDist, MaskOr, MaskPattern, MaskReg, Mul, Pack, PostLiteral, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **Max 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: SwiGLU MX 量化非末轴路径中，DataCopy 交织搬入 x0/x1 后 And 取绝对值，用 Max 把两路绝对值分别累积到 absMax1Dim2/absMax2Dim2（-2 轴逐列统计），循环结束后再 Cast→float 处理 absMax1Dim2。

（行 310-321）

```cpp
for (uint16_t i = 0; i < blockCount; i++) {
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
        x0, x1, xAddr, 256);
    Reg::And(absMax0, (Reg::RegTensor<uint16_t>&)x0, absMask, maskAll);
    Reg::And(absMax1, (Reg::RegTensor<uint16_t>&)x1, absMask, maskAll);
    Reg::Max(absMax1Dim2, absMax1Dim2, absMax0, maskAll);
    Reg::Max(absMax2Dim2, absMax2Dim2, absMax1, maskAll);
}

// process absMax1Dim2
Reg::Cast<float, T, CAST_ZERO>((Reg::RegTensor<float>&)maxFP32_0,
                                    (Reg::RegTensor<T>&)absMax1Dim2, maskAll);
```

**要点**:
- Max 第 4 参 maskAll 全 1，DataCopy 带 POST_MODE_UPDATE+DIST_DINTLV_B16 一次取 256B 交织数据。
- 两路独立累积 absMax1Dim2/absMax2Dim2，与实例 3 的配对 Max+ReduceMax 双轴模式形成对照（此处无配对 Max）。
- 累积结果需 Cast<T→float> 转 fp32 才能做后续除法/scale 计算。

### 实例 9：dynamic_quant::AscendC::VECTOR_REG_WIDTH

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Adds, Cast, CreateMask, DataCopy, Div, DivSpecificMode, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Min, Mul, Muls, ReduceMax, ReduceMin, RegTensor, RegTraitNumOne, StoreDist, Sub, UpdateMask
- **Max 调用次数**: 12
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: dynamic_quant 大 shape double-buffer 路径，逐 VF 循环：对称量化用 Abs+Muls+Max 累积绝对最大，非对称用 Max/Min 同时累积；尾块单独处理后用 Max(max, maxTail) 合并主体与尾块 reduce 结果，最终得 vregMax。

**片段 1** (行 456-474):

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(vfLoopNum - 1); i++) {
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vreg0, inLocalAddr + i * VL);
    AscendC::Reg::Cast<float, T, castTrait0>(vreg1, vreg0, maskAll);
    if constexpr (hasSmooth == 1) {
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vreg2,
                                                                                     smoothLocalAddr + i * VL);
        AscendC::Reg::Cast<float, T, castTrait0>(vreg3, vreg2, maskAll);
        AscendC::Reg::Mul(vreg1, vreg1, vreg3, maskAll);
    }

    if constexpr (isSymmetrical) {
        AscendC::Reg::Abs(vreg5, vreg1, maskAll);
        AscendC::Reg::Muls(vreg5, vreg5, scaleMaxValue, maskAll);
        AscendC::Reg::Max(vreg6, vreg5, vreg6, maskAll);
    } else {
        AscendC::Reg::Max(vreg6, vreg1, vreg6, maskAll);
        AscendC::Reg::Min(vreg8, vreg1, vreg8, maskAll);
    }
}
```

**片段 2** (行 475-506):

```cpp
{
    if constexpr (isSymmetrical) {
        AscendC::Reg::ReduceMax<float>(vregMax, vreg6, maskAll);
    } else {
        AscendC::Reg::ReduceMax<float>(vregMax, vreg6, maskAll);
        AscendC::Reg::ReduceMin<float>(vregMin, vreg8, maskAll);
    }
    mask = AscendC::Reg::UpdateMask<float>(tailNum);
    AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
        vreg0, inLocalAddr + (vfLoopNum - 1) * VL);
    AscendC::Reg::Cast<float, T, castTrait0>(vreg1, vreg0, mask);
    if constexpr (hasSmooth == 1) {
        AscendC::Reg::DataCopy<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
            vreg2, smoothLocalAddr + (vfLoopNum - 1) * VL);
        AscendC::Reg::Cast<float, T, castTrait0>(vreg3, vreg2, mask);
        AscendC::Reg::Mul(vreg1, vreg1, vreg3, mask);
    }
    if constexpr (isSymmetrical) {
        AscendC::Reg::Abs(vreg5, vreg1, mask);
        AscendC::Reg::Muls(vreg5, vreg5, scaleMaxValue, mask);
        AscendC::Reg::Max(vreg6, vreg5, vreg6, mask);
        AscendC::Reg::ReduceMax<float>(vregMaxTail, vreg6, mask);
        AscendC::Reg::Max(vregMax, vregMax, vregMaxTail, mask);
    } else {
        AscendC::Reg::Max(vreg6, vreg1, vreg6, mask);
        AscendC::Reg::Min(vreg8, vreg1, vreg8, mask);
        AscendC::Reg::ReduceMax<float>(vregMaxTail, vreg6, mask);
        AscendC::Reg::ReduceMin<float>(vregMinTail, vreg8, mask);
        AscendC::Reg::Max(vregMax, vregMax, vregMaxTail, mask);
        AscendC::Reg::Min(vregMin, vregMin, vregMinTail, mask);
    }
}
```

**要点**:
- Max 第 4 参 maskAll 为全量 mask，尾块改用 UpdateMask(tailNum) 生成的 mask，合并用 preg5。
- isSymmetrical 分支决定是否先 Abs：对称走 Abs→Muls→Max，非对称直接 Max（保留符号）。
- 片段2 末尾 Max(vregMax, vregMax, vregMaxTail) 把尾块 reduce 结果并回主体，是“尾块合并”标准用法。

### 实例 10：dynamic_mx_quant::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CastTrait, CreateMask, DeInterleave, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Pack, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, ShiftRights, StoreUnAlign, StoreUnAlignPost, UnalignReg
- **Max 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEint32_t+uint32_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: uint32_t, int32_t）
- **语义（待补充）**: dynamic_mx_quant 尾轴 FP32 路径中，LoadAlign 交织取 4 路数据后 DeInterleave 重排，And 取 32 位指数位，用 Max 两两求最大（x0/x1 内部配对、再 x0max/x1max 合并），最后 ReduceMaxWithDataBlock+ShiftRights+Pack 得到每 32 元素块的指数最大值。

（行 528-548）

```cpp
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
Reg::ShiftRights(xMaxExpB32, xMaxExpB32, FP32_PACK_SHR_NUM, MaskB32);
Reg::Pack<uint16_t, uint32_t, Reg::HighLowPart::LOWEST>(xMaxExpB16, xMaxExpB32);
```

**要点**:
- 三级 Max 树形归约：x0MaxExpB32=max(x0Zero,x0One)、x1MaxExpB32=max(x1Zero,x1One)、xMaxExpB32=max(x0max,x1max)，再 ReduceMaxWithDataBlock。
- 操作数以 (RegTensor<uint32_t>&) 视图比较 fp32 指数位，mask MaskB32 为 32 位块全量 mask。
- 配合 DeInterleave 把交织数据重排成偶/奇组，是尾轴处理特有的数据排布转换。

### 实例 11：dynamic_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, And, Cast, Compare, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskPattern, MaskReg, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreDist, Sub
- **Max 调用次数**: 6
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: 双轴动态 MX 量化中，half 输入先检 INF/NAN、Cast→BF16(RINT)、And 取绝对值、Select 把 INF/NAN 位替换为 BF16 INF，再用 Max 求 -1 轴配对最大值（+ReduceMaxWithDataBlock）和 -2 轴逐列累积（absMax1Dim2/absMax2Dim2）。

（行 953-981）

```cpp
if constexpr (IsSameType<xDtype, half>::value) {
    // FP16输入: 先检查INF/NAN，再转BF16(RINT)，取绝对值，INF/NAN替换为BF16 INF
    Reg::And(expOnly, (Reg::RegTensor<uint16_t>&)x0, expMaskFP16, maskAll);
    Reg::Compare<uint16_t, CMPMODE::NE>(infNanDataMask0, expOnly, expMaskFP16, maskAll);
    Reg::And(expOnly, (Reg::RegTensor<uint16_t>&)x1, expMaskFP16, maskAll);
    Reg::Compare<uint16_t, CMPMODE::NE>(infNanDataMask1, expOnly, expMaskFP16, maskAll);
    // 转BF16 (使用CAST_RINT四舍五入，不同于OCP的CAST_TRUNC截断)
    Reg::Cast<bfloat16_t, xDtype, castTraitHalf2BF16Rint>(x0BF16, x0, maskAll);
    Reg::Cast<bfloat16_t, xDtype, castTraitHalf2BF16Rint>(x1BF16, x1, maskAll);
    // 取绝对值
    Reg::And(absVal0, (Reg::RegTensor<uint16_t>&)x0BF16, absMask, maskAll);
    Reg::And(absVal1, (Reg::RegTensor<uint16_t>&)x1BF16, absMask, maskAll);
    // INF/NAN位置替换为BF16的INF (0x7f80)
    Reg::Select<uint16_t>(absVal0, absVal0, expMaskBF16, infNanDataMask0);
    Reg::Select<uint16_t>(absVal1, absVal1, expMaskBF16, infNanDataMask1);
} else {
    // BF16输入: 直接取绝对值
    Reg::And(absVal0, (Reg::RegTensor<uint16_t>&)x0, absMask, maskAll);
    Reg::And(absVal1, (Reg::RegTensor<uint16_t>&)x1, absMask, maskAll);
}

// 3. -1轴: 偶奇Max + ReduceMaxWithDataBlock，得到每32个元素的绝对值max
Reg::Max(absMaxDim1, absVal0, absVal1, maskAll);
Reg::ReduceMaxWithDataBlock(absMaxDim1, absMaxDim1, maskAll);

// 4. -2轴: 逐行累积偶数列和奇数列的BF16绝对值max
Reg::Max(absMax1Dim2, absMax1Dim2, absVal0, maskAll);
Reg::Max(absMax2Dim2, absMax2Dim2, absVal1, maskAll);
```

**要点**:
- Max 第 4 参 maskAll 全 1；-1 轴用 Max(absVal0,absVal1) 配对，-2 轴用 Max(累积,absVal) 逐列累积。
- half 输入经 CAST_RINT 四舍五入转 BF16（区别于 OCP 的 CAST_TRUNC），INF/NAN 用 Select 替换为定值再参与 Max。
- BF16 输入直接 And 取绝对值，省去 Cast 步骤，两条路径汇合后 Max 调用一致。

### 实例 12：dynamic_block_mx_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, Compare, CreateMask, Duplicate, Gather, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreAlign, Sub
- **Max 调用次数**: 7
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: dynamic_block_mx_quant 中，先 Duplicate 初始化各掩码常量，按行循环 LoadAlign 交织取数，half 输入检 INF/NAN 后 Cast→BF16、And 取指数、Select 替换特殊值，用 Max 逐行累积 expMax1Dim2/expMax2Dim2，循环后 Max 合并两路并 ReduceMaxWithDataBlock 得每 32×32 块最大指数。

（行 645-695）

```cpp
Reg::MaskReg maskAll = Reg::CreateMask<T, Reg::MaskPattern::ALL>();

Reg::Duplicate(zero, 0);
Reg::Duplicate(expMax1Dim2, 0);
Reg::Duplicate(expMax2Dim2, 0);
Reg::Duplicate(expMaskBF16, EXP_MASK_BF16);
Reg::Duplicate(expMaskFP16, EXP_MASK_FP16);
Reg::Duplicate(nanE8M0, NAN_FOR_FP8_E8M0);
Reg::Duplicate(nanBF16, NAN_CUSTOMIZATION);
Reg::Duplicate(biasE8M0, BF16_EXP_BIAS);
Reg::Duplicate(absForX, ABS_FOR_UINT16);
Reg::Duplicate(yMaxExp, dtypeYMaxExp_);
Reg::Duplicate(specialExp, SPECIAL_EXP_THRESHOLD);
Reg::Duplicate(mantissaForMax, bitForMantissa_);

// comput Max(x)
for (uint16_t i = 0; i < rowNum; i++) {
    // 交织搬运，一次搬256个B16
    Reg::LoadAlign<T, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_DINTLV_B16>(
        x0, x1, xAddr, vlForHalfNumber_ * DIGIT_TWO);

    if constexpr (IsSameType<T, half>::value) {
        // 求绝对值
        Reg::And(x0ExpFP16, (Reg::RegTensor<uint16_t>&)x0, absForX, maskAll);
        Reg::And(x1ExpFP16, (Reg::RegTensor<uint16_t>&)x1, absForX, maskAll);
        // 比较INF/NAN数据
        Reg::Compare<uint16_t, CMPMODE::LT>(infNanDataMask0, x0ExpFP16, expMaskFP16, maskAll);
        Reg::Compare<uint16_t, CMPMODE::LT>(infNanDataMask1, x1ExpFP16, expMaskFP16, maskAll);
        // 原始数据转成bf16
        Reg::Cast<bfloat16_t, T, castTraitHalf2BF16Ddr>(x0BF16, x0, maskAll);
        Reg::Cast<bfloat16_t, T, castTraitHalf2BF16Ddr>(x1BF16, x1, maskAll);
        // 提取指数位
        Reg::And(x0ExpBF16, (Reg::RegTensor<uint16_t>&)x0BF16, absForX, maskAll);
        Reg::And(x1ExpBF16, (Reg::RegTensor<uint16_t>&)x1BF16, absForX, maskAll);
        // 选择数据，INF/NAN数据时设成BF的INF/NAN
        Reg::Select<uint16_t>(x0ExpBF16, x0ExpBF16, expMaskBF16, infNanDataMask0);
        Reg::Select<uint16_t>(x1ExpBF16, x1ExpBF16, expMaskBF16, infNanDataMask1);
    } else {
        // 求绝对值
        Reg::And(x0ExpBF16, (AscendC::Reg::RegTensor<uint16_t>&)x0, absForX, maskAll);
        Reg::And(x1ExpBF16, (AscendC::Reg::RegTensor<uint16_t>&)x1, absForX, maskAll);
    }
    Reg::Max(expMax1Dim2, expMax1Dim2, x0ExpBF16, maskAll);
    Reg::Max(expMax2Dim2, expMax2Dim2, x1ExpBF16, maskAll);
}

// 计算x0和x1的最大值，相当于计算原始相邻两个数据的最大值
Reg::Max(expMaxDim, expMax1Dim2, expMax2Dim2, maskAll);
// ReduceMax一个block，即16个数，配合上一步，可以计算出每32*32个数的最大值，一共256/32个
Reg::ReduceMaxWithDataBlock(expMaxDim, expMaxDim, maskAll);
```

**要点**:
- 大量 Duplicate 预置常量（absForX/expMask/nan 等）作为 Max 前置 And/Select 的掩码，是 block 量化的典型初始化模式。
- 两路 Max 累积（expMax1Dim2/expMax2Dim2）+ 循环后一次配对 Max + ReduceMaxWithDataBlock，构成“-2 轴累积→-1 轴配对→block 归约”三级结构。
- half 与 BF16 走不同指数提取路径，但 Max 在 uint16_t 视图上统一比较。

### 实例 13：swiglu_group_quant::VFComputeMaxExpMXFP4Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: And, Cast, CastTrait, Compare, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, PostLiteral, ReduceMaxWithDataBlock, RegLayout, RegTensor, SatMode, Select, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **Max 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义（待补充）**: swiglu_group_quant 的 VF 计算函数中，half 输入先 And/Compare 检 INF/NAN、Cast→BF16、And 取指数、Select 替换特殊值，用 Max 求两路指数配对最大值 vdMaxExp，再 ReduceMaxWithDataBlock 压缩，StoreUnAlign 写出每块最大指数。

（行 304-324）

```cpp
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
} else {
    AscendC::Reg::And(vdExpExtract0, (AscendC::Reg::RegTensor<uint16_t>&)vdExp0, expMaskBF16, scaleMask1);
    AscendC::Reg::And(vdExpExtract1, (AscendC::Reg::RegTensor<uint16_t>&)vdExp1, expMaskBF16, scaleMask1);
}

AscendC::Reg::Max(vdMaxExp, vdExpExtract0, vdExpExtract1, scaleMask1);
AscendC::Reg::ReduceMaxWithDataBlock(vdMaxExp, vdMaxExp, scaleMask1);

AscendC::Reg::StoreUnAlign<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(maxExpAddr, vdMaxExp, u1,
                                                                                  scaleNum);
```

**要点**:
- 来源类型 __simd_vf__（VF 函数级），与多数 __VEC_SCOPE__ 实例的上下文层级不同。
- Max 第 4 参 scaleMask1 由上层传入的 scale 区间 mask，控制参与求最大的元素范围。
- 配对 Max+ReduceMaxWithDataBlock 是“相邻两数据→block 归约”的标准两步，结果按 scaleNum 步进 StoreUnAlign 写出。

### 实例 14：grouped_dynamic_block_quant::ops::IsSame

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, CompareScalar, CreateMask, Div, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, Min, ReduceMax, RegTensor, StoreAlign, StoreDist, UpdateMask
- **Max 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEint16_t+uint16_t_MASKMask`（实参 4 个，含 mask/mode: Mask，类型: uint16_t, int16_t）
- **语义（待补充）**: 分组动态 block 量化小 block 路径中，按 step128 循环 LoadAlign 取数、And 取绝对值，以显式模板 <uint16_t, MaskMergeMode::MERGING> 调用 Max 把当前块绝对值累积到 expMaxRegTensor，循环结束恢复 pnum16 为整块宽度。

（行 355-363）

```cpp
for (uint16_t step128 = 0; step128 < static_cast<uint16_t>(normalStep128); step128++) {
    dataLenMask16 = AscendC::Reg::UpdateMask<uint16_t>(pnum16);
    AscendC::Reg::LoadAlign(xRegTensor, xAddr + stepBlock * blockDataNumOffset + step128 * vfLen);
    AscendC::Reg::And(xAbsRegTensor, (AscendC::Reg::RegTensor<uint16_t>&)xRegTensor,
                           absMaskRegTensor, dataLenMask16);
    AscendC::Reg::Max<uint16_t, AscendC::Reg::MaskMergeMode::MERGING>(
        expMaxRegTensor, expMaxRegTensor, xAbsRegTensor, dataLenMask16);
}
pnum16 = normalBlockDataNum;
```

**要点**:
- 显式模板 <uint16_t, MaskMergeMode::MERGING>，mask 未选元素保留原值（累积 reduce 时需 MERGING 防止置零破坏累积）。
- Max 累积寄存器 expMaxRegTensor 跨 step128 循环复用，需在循环外置初值 0。
- mask dataLenMask16 由 UpdateMask<uint16_t>(pnum16) 按当前 step 剩余元素生成，处理尾步对齐。

### 实例 15：max_pool_with_argmax_v3::MaxPoolWithArgMaxV3GatherImpl

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Cast, Compare, CreateMask, DataCopyGather, DataCopyScatter, Duplicate, MaskOr, MaskPattern, MaskReg, MaskUnPack, Muls, Pack, RegTensor, Select, UpdateMask
- **Max 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: max_pool_with_argmax_v3 的 Gather 实现中，按 kernel 的 h/w 双重循环用 DataCopyGather 取出滑动窗口元素 vd1，用 Compare(GT) 生成“新值更大”掩码并 Select 更新 argmax 索引，最后用 Max(vd0, vd1, vd0) 累积当前窗口最大值到 vd0。

（行 78-121）

```cpp
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
            AscendC::Reg::Cast<uint16_t, uint32_t, castTraitU32U16>(gatterIdxU16Reg, gatterIndexReg,
                                                                         computeU32);
            AscendC::Reg::Pack(gatterIdxU16Reg, (AscendC::Reg::RegTensor<uint32_t>&)gatterIdxU16Reg);
            AscendC::Reg::DataCopyGather(vd1, xAddr, gatterIdxU16Reg, computeT1);
        }

        AscendC::Reg::Compare<T1, CMPMODE::GT>(gtMask, vd1, vd0, computeT1);
        AscendC::Reg::Compare<T1, CMPMODE::NE>(neMask, vd1, vd1, computeT1);
        AscendC::Reg::MaskOr(gtMask, gtMask, neMask, computeT1);

        Reg::Adds(argmaxUpdateHVreg, argmaxHStart, argmaxHKernelOffset, computeT2);
        Reg::Adds(argmaxUpdateWVreg, argmaxWStart, argmaxWKernelOffset, computeT2);
        if constexpr (sizeof(T2) / sizeof(T1) == 1) {
            AscendC::Reg::Select(argmaxHRes, argmaxUpdateHVreg, argmaxHRes, gtMask);
            AscendC::Reg::Select(argmaxWRes, argmaxUpdateWVreg, argmaxWRes, gtMask);
        } else if constexpr (sizeof(T2) / sizeof(T1) == DOUBLE) {
            AscendC::Reg::MaskUnPack(gtMaskT2, gtMask);
            AscendC::Reg::Select(argmaxHRes, argmaxUpdateHVreg, argmaxHRes, gtMaskT2);
            AscendC::Reg::Select(argmaxWRes, argmaxUpdateWVreg, argmaxWRes, gtMaskT2);
        } else {
            AscendC::Reg::MaskUnPack(gtMaskT2, gtMask);
            AscendC::Reg::MaskUnPack(gtMaskT4, gtMaskT2);
            AscendC::Reg::Select(argmaxHRes, argmaxUpdateHVreg, argmaxHRes, gtMaskT4);
            AscendC::Reg::Select(argmaxWRes, argmaxUpdateWVreg, argmaxWRes, gtMaskT4);
        }

        Reg::Max(vd0, vd1, vd0, computeT1);
    }
}
```

**要点**:
- Max 第 4 参 computeT1 为按数据类型宽度的全量计算 mask，无尾块裁剪（窗口内全有效）。
- 与 Compare+Select 配合：Compare 产生 gtMask 决定是否更新 argmax 索引，Max 始终更新数值最大值，两者并行维护“值+索引”。
- 来源类型 __aicore__ 且属于 pooling 域（非 quant），展示 Max 在非量化场景的通用滑动窗口归约用法。

### Max 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 按行循环 Max 累积指数位最大值 + DataCopy/LocalMemBar 二分折叠逐级求全行最大指数 | __VEC_SCOPE__ |
| dynamic_mx_quant | Adds, And, Cast, CastTrait, Compare | 按 block 循环 LoadData→And 取指数→Max 累积全行最大指数（uint16_t 视图，int16+uint16 类型组合） | __VEC_SCOPE__ |
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Arange, Cast | DataCopy 交织取两路→And 取绝对值→Max 配对(-1 轴)+ReduceMax、Max 逐列累积(-2 轴)双轴统计 | __VEC_SCOPE__ |
| dynamic_quant | Abs, Add, Adds, Cast, CreateMask | 逐 VF 取 Abs→Max 累积绝对最大→ReduceMax→Muls 求 scale；非对称同时 Max/Min，尾块 Max 合并 | __aicore__ |
| dynamic_block_quant | And, Cast, CastTrait, CompareScalar, CreateMask | 显式 <uint32_t,MERGING> 模板 Max 累积块内绝对值最大，fp32/fp16 两片段对应不同精度 | __VEC_SCOPE__ |
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast, Compares | Min+Max 配对实现 clip(x, nudgedMin, nudgedMax) 夹紧，float + ZEROING 模式 | __VEC_SCOPE__ |
| grouped_dynamic_mx_quant | And, Cast, CastTrait, Compare, CreateMask | LoadAlign 取相邻两路→(half:Cast→BF16)→And 取指数→Max 配对+Max 累积，循环后 Compare 检 inf/zero | __VEC_SCOPE__ |
| swiglu_mx_quant | Adds, And, Cast, Compare, CompareScalar | DataCopy 交织→And 取绝对值→Max 逐列累积 absMax1Dim2/absMax2Dim2（-2 轴），无配对 Max | __aicore__ |
| dynamic_quant | Abs, Adds, Cast, CreateMask, DataCopy | 逐 VF 循环对称(Abs+Muls+Max)/非对称(Max+Min)累积，尾块单独处理后 Max 合并主体与尾块 reduce | __VEC_SCOPE__ |
| dynamic_mx_quant | And, CastTrait, CreateMask, DeInterleave, Duplicate | LoadAlign 交织+DeInterleave 重排→And 取 32 位指数→三级 Max 树形归约→ReduceMaxWithDataBlock+Pack | __VEC_SCOPE__ |
| dynamic_mx_quant_with_dual_axis | Add, And, Cast, Compare, CreateMask | half 检 INF/NAN→Cast BF16(RINT)→And 取绝对值→Select 替换特殊值→Max 配对(-1 轴)+Max 累积(-2 轴) | __VEC_SCOPE__ |
| dynamic_block_mx_quant | And, Cast, Compare, CreateMask, Duplicate | Duplicate 预置常量→按行 LoadAlign 交织→(half:检 INF/NAN+Cast)→And 取指数→Max 逐行累积→配对 Max+ReduceMaxWithDataBlock | __VEC_SCOPE__ |
| swiglu_group_quant | And, Cast, CastTrait, Compare, Duplicate | VF 函数内 half 检 INF/NAN→Cast BF16→And 取指数→Max 配对+ReduceMaxWithDataBlock→StoreUnAlign 写出 | __simd_vf__ |
| grouped_dynamic_block_quant | And, Cast, CompareScalar, CreateMask, Div | 显式 <uint16_t,MERGING> 模板 Max 累积块内绝对值最大，按 step128 循环尾步对齐 | __VEC_SCOPE__ |
| max_pool_with_argmax_v3 | Add, Adds, Cast, Compare, CreateMask | 滑动窗口 DataCopyGather 取元素→Compare(GT)+Select 更新 argmax→Max 累积窗口最大值（非量化场景） | __aicore__ |
