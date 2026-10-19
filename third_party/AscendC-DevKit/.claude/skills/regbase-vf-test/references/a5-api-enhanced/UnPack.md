# UnPack

**页面ID:** atlasascendc_api_07_0339  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0339.html

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

根据所选的低位模式或高位模式，将输入MaskReg的低半部分或高半部分展开到输出MaskReg。展开方式为：将每bit展开为2bit，高位置零。

#### 函数原型

```
template <HighLowPart part = HighLowPart::LOWEST> 
__simd_callee__ inline void UnPack(MaskReg& dst, MaskReg& src);
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| part | 枚举类型，低位模式或高位模式。 - LOWEST  低位模式；- HIGHEST 高位模式。 |

**表2 **参数说明

| 参数名 | 描述 |
| --- | --- |
| dst | 目的操作数。 |
| src | 源操作数。 |

#### 约束说明

无

#### 调用示例

```
template <typename T>
__simd_vf__ inline void UnpackVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg maskFull = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg mask0;
    AscendC::Reg::MaskReg mask1;
    AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::LOWEST>(mask0, maskFull);
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask1 = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Adds(srcReg, srcReg, 0, mask0);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask1);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 UnPack 实例


### 实例 1：swiglu_mx_quant_with_dual_axis::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, And, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, Sub
- **UnPack 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: int32_t, uint32_t）
- **语义**: 在 SwiGLU 量化算子的逐通道缩放中，将 int16 的逐通道绝对最大值结果 UnPack 成 int32，便于随后 Cast 到 float32 做指数位缩放计算。

（行 995-1012）

```cpp

// Absolute value (CLUB)
Reg::And(x0Abs, (Reg::RegTensor<uint16_t>&)x0, absMask, maskAll);
Reg::And(x1Abs, (Reg::RegTensor<uint16_t>&)x1, absMask, maskAll);

// -1 axis: max of pair + reduce
Reg::Max(absMaxDim1, x0Abs, x1Abs, maskAll);
Reg::ReduceMaxWithDataBlock(absMaxDim1, absMaxDim1, maskAll); // -1轴 指数位计算结束 8个int16的数

// -2 axis: accumulate column-wise max
Reg::Max(absMax1Dim2, absMax1Dim2, x0Abs, maskAll); // -2轴最大值
Reg::Max(absMax2Dim2, absMax2Dim2, x1Abs, maskAll); // -2轴最大值

// ---- -1 axis CLUB scale: ZERO half (even positions after ReduceMax) ----
Reg::UnPack((AscendC::Reg::RegTensor<uint32_t>&)absMaxDim1Unpack,
                 (AscendC::Reg::RegTensor<uint16_t>&)absMaxDim1);
Reg::Cast<float, xDtype, CAST_X_TO_FP32_ZERO>((Reg::RegTensor<float>&)max32, absMaxDim1Unpack,
                                                   maskAll);
```

**要点**:
- 默认低位模式（未显式传 part），把 uint16 低半部分零扩展到 uint32，配合 CAST_X_TO_FP32_ZERO 得到偶数位（ZERO half）的 fp32。
- 同一寄存器 in-place 风格 (RegTensor<uint32_t>&)dst, (RegTensor<uint16_t>&)src 强转引用，dst/src 为同一段数据的两种位宽视图。
- 位于 -1 轴 ReduceMaxWithDataBlock 之后的指数位计算阶段，UnPack 是 b16→b32 升位宽链路的入口。

### 实例 2：avg_pool::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Arange, Cast, Copy, CreateMask, DataCopyGather, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, MaskMergeMode, MaskPattern, MaskReg, Muls, Pack, ReduceSum, RegTensor, UnalignReg, UpdateMask
- **UnPack 调用次数**: 4
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: int32_t, uint32_t）
- **语义**: avg_pool 大核 NHWC 计算中，将 DataCopyGather 取出的 uint16 输入原地 UnPack 成 uint32，再 Cast 到 float32 累加，实现 fp16/bf16 池化的精度提升。

（行 626-637）

```cpp
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
```

**要点**:
- 典型三连链路 DataCopyGather → UnPack(uint16→uint32) → Cast<float>，把 16 位数据升宽到 32 位再转 fp32 累加，避免低精度累加误差。
- 循环体内每次 repeat 都调用一次 UnPack，UnPack 调用次数=4（主循环 + tail 残部）。
- tail 段用 Copy<MaskMergeMode::MERGING> 合并残部结果，UnPack 之后必须用对应的有效 mask（tailMaskFp32）做 Cast/Add。

### 实例 3：softmax_cross_entropy_with_logits::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Cast, Copy, CreateAddrReg, CreateMask, DataCopy, Duplicate, HighLowPart, MaskMergeMode, MaskPattern, MaskReg, Max, ReduceMax, RegTensor, StoreDist, UpdateMask
- **UnPack 调用次数**: 2
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t`（实参 2 个，类型: int32_t, int16_t, LOWEST, HighLowPart, LOW）
- **语义**: 对 fp16/bf16 的 features 做 ReduceMax 前的位宽提升——分别用 LOWEST 和 HIGHEST 两次 UnPack 把一个 int16 寄存器的低/高半部分拆成两个 int32，再各自 Cast 成 float32 求最大。

（行 384-397）

```cpp
if constexpr (sizeof(T) == 2) {
    AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::LOWEST>(
        (AscendC::Reg::RegTensor<int32_t>&)featuresRegLowest,
        (AscendC::Reg::RegTensor<int16_t>&)featuresReg);
    AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::HIGHEST>(
        (AscendC::Reg::RegTensor<int32_t>&)featuresRegHighest,
        (AscendC::Reg::RegTensor<int16_t>&)featuresReg);
    AscendC::Reg::Cast<float, T, castB16ToB32>(featuresRegLowest32, featuresRegLowest, pregReduce);
    AscendC::Reg::Cast<float, T, castB16ToB32>(featuresRegHighest32, featuresRegHighest, pregReduce);
    AscendC::Reg::Max(maxRegTemp, featuresRegLowest32, featuresRegHighest32, pregReduce);
    AscendC::Reg::ReduceMax(maxReg, maxRegTemp, pregReduce);
} else {
    AscendC::Reg::ReduceMax(maxReg, featuresReg, pregReduce);
}
```

**要点**:
- 显式三模板参数 UnPack<int32_t,int16_t,HighLowPart::LOWEST/HIGHEST>，LOWEST 取低半、HIGHEST 取高半，二者配合可还原完整 b16 向量到两个 b32 向量。
- if constexpr (sizeof(T)==2) 分支表明该 UnPack 链路仅对 16 位类型生效，32 位类型直接 ReduceMax 跳过。
- 拆半后两路分别 Cast<float> + Max 再 ReduceMax，等价于对原 b16 向量做跨半区 reduce-max（因 bf16 不支持 vcmax）。

### 实例 4：tensor_equal::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, AddrReg, Compare, CreateAddrReg, CreateMask, DataCopy, Duplicate, HighLowPart, MaskOr, MaskPattern, MaskReg, MaskUnPack, ReduceMax, RegTensor, UpdateMask
- **UnPack 调用次数**: 2
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t+uint16_t+uint32_t`（实参 2 个，类型: int32_t, uint32_t, int16_t, uint16_t, LOWEST, HighLowPart, LOW）
- **语义**: tensor_equal 的结果归约中，先对 mask 做 MaskUnPack 拆半归约得到 uint16 计数，再用 UnPack<uint32_t,uint16_t,LOWEST> 把计数升宽到 uint32 写回结果地址。

（行 147-165）

```cpp
if constexpr (std::is_same<InputType, uint8_t>::value) {
    AscendC::Reg::Duplicate(tmpU16Reg, 1);
    AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::HIGHEST>(bakMaskRegHigh, bakMaskReg);
    AscendC::Reg::MaskUnPack<AscendC::Reg::HighLowPart::LOWEST>(bakMaskRegLow, bakMaskReg);
    AscendC::Reg::ReduceMax(tmpU16RegAdd, tmpU16Reg, bakMaskRegHigh);
    AscendC::Reg::ReduceMax(tmpU16Reg, tmpU16Reg, bakMaskRegLow);
    AscendC::Reg::Add(tmpU16Reg, tmpU16Reg, tmpU16RegAdd, allMaskReg);
    AscendC::Reg::UnPack<uint32_t, uint16_t, AscendC::Reg::HighLowPart::LOWEST>(tmpU32Reg, tmpU16Reg);
    AscendC::Reg::DataCopy(resultAddr, tmpU32Reg, allMaskReg);
} else if constexpr (std::is_same<InputType, half>::value) {
    AscendC::Reg::Duplicate(tmpU16Reg, 1);
    AscendC::Reg::ReduceMax(tmpU16Reg, tmpU16Reg, bakMaskReg);
    AscendC::Reg::UnPack<uint32_t, uint16_t, AscendC::Reg::HighLowPart::LOWEST>(tmpU32Reg, tmpU16Reg);
    AscendC::Reg::DataCopy(resultAddr, tmpU32Reg, allMaskReg);
} else {
    AscendC::Reg::Duplicate(tmpU32Reg, 1);
    AscendC::Reg::ReduceMax(tmpU32Reg, tmpU32Reg, bakMaskReg);
    AscendC::Reg::DataCopy(resultAddr, tmpU32Reg, allMaskReg);
}
```

**要点**:
- 同一函数里 MaskUnPack（操作 MaskReg）与 UnPack（操作 RegTensor）并存，二者模板参数形式不同：MaskUnPack 只需 part，UnPack 需 <dstT,srcT,part>。
- uint8 输入分支用 LOWEST+HIGHEST 两次 MaskUnPack 把 mask 拆成两半归约，half 分支只需一次；UnPack 统一用 LOWEST 把 u16 计数升到 u32。
- dst/src 用 (RegTensor<uint32_t>&)/(RegTensor<uint16_t>&) 强转引用，升位宽后用 allMaskReg 整体 DataCopy 输出。

### 实例 5：sparse_slice::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Arange, CreateMask, DataCopy, DataCopyScatter, Div, Duplicate, HighLowPart, MaskPack, MaskPattern, MaskReg, Mul, RegTensor, Sub, UpdateMask
- **UnPack 调用次数**: 1
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int32_t+int64_t`（实参 2 个，类型: int64_t, int32_t, LOWEST, HighLowPart, LOW）
- **语义**: 稀疏切片转置索引计算中，把算好的 int32 目标下标用 UnPack<int64_t,int32_t,LOWEST> 升宽为 int64，作为 DataCopyScatter 的 64 位散列下标。

（行 883-914）

```cpp
{
    Reg::RegTensor<int64_t> vregInput;
    Reg::RegTensor<int32_t> vregSrcIndex;
    Reg::RegTensor<int32_t> vregDstIndex;
    Reg::RegTensor<int64_t> vregDstIndexB64;
    Reg::RegTensor<int32_t> vreg0;
    Reg::RegTensor<int32_t> vreg1;
    Reg::RegTensor<int32_t> vreg2;
    Reg::RegTensor<int32_t> vreg3;
    Reg::RegTensor<int32_t> vregCol;
    Reg::RegTensor<int32_t> vregRow;
    Reg::MaskReg preg;
    Reg::MaskReg pregB32;
    Reg::MaskReg pregB32ALL = Reg::CreateMask<int32_t, Reg::MaskPattern::ALL>();

    Reg::Duplicate(vregCol, colNum, pregB32ALL);
    Reg::Duplicate(vregRow, rowNum, pregB32ALL);

    for (uint16_t loopIndex = 0; loopIndex < loopNum; loopIndex++) {
        preg = Reg::UpdateMask<int64_t>(sreg0);
        Reg::MaskPack<Reg::HighLowPart::LOWEST>(pregB32, preg);
        Reg::DataCopy(vregInput, yIndicesTransposedAddr + loopIndex * vlSize);
        Reg::Arange<int32_t>(vregSrcIndex, (int32_t)(loopIndex * vlSize));
        Reg::Div(vreg0, vregSrcIndex, vregCol, pregB32);
        Reg::Mul(vreg1, vreg0, vregCol, pregB32);
        Reg::Sub(vreg2, vregSrcIndex, vreg1, pregB32);
        Reg::Mul(vreg3, vreg2, vregRow, pregB32);
        Reg::Add(vregDstIndex, vreg3, vreg0, pregB32);
        Reg::UnPack<int64_t, int32_t, Reg::HighLowPart::LOWEST>(vregDstIndexB64, vregDstIndex);
        Reg::DataCopyScatter(yIndicesAddr, vregInput, (Reg::RegTensor<uint64_t>&)vregDstIndexB64, preg);
    }
}
```

**要点**:
- 唯一的 int32→int64 升宽用法：UnPack<int64_t,int32_t,HighLowPart::LOWEST>(vregDstIndexB64, vregDstIndex)，把 32 位下标零扩展到 64 位以满足 DataCopyScatter 的 64 位地址要求。
- 配套 MaskPack<LOWEST> 把 64 位元素的 mask 压成 32 位 mask（pregB32），用于前置的 Div/Mul/Sub/Add 等 32 位整型运算。
- UnPack 在循环末尾、DataCopyScatter 之前执行，是 32 位算地址 → 升 64 位 → 散列拷贝 链路的桥接点。

### 实例 6：avg_pool::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, AddrReg, Cast, CreateAddrReg, DataCopy, DataCopyUnAlign, DataCopyUnAlignPost, Duplicate, MaskReg, Muls, Pack, RegTensor, UnalignReg, UpdateMask
- **UnPack 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: int32_t, uint32_t）
- **语义**: avg_pool 大核的另一条加载路径：用 CreateAddrReg 构造偏移做 DataCopy，取到的 uint16 输入原地 UnPack 成 uint32 再 Cast 到 float32 累加。

（行 560-566）

```cpp
for (uint16_t j = 0; j < loopNum; j++) {
    Reg::AddrReg offset = Reg::CreateAddrReg<T>(j, channelStride);
    Reg::DataCopy(in, srcAddr, offset);
    Reg::UnPack((Reg::RegTensor<uint32_t>&)in, (Reg::RegTensor<uint16_t>&)in);
    Reg::Cast<float, T, castTraitT2Fp32>(inFp32, in, p0);
    Reg::Add(resFp32, inFp32, resFp32, p0);
}
```

**要点**:
- 与实例 2 同属 avg_pool 但加载方式不同——本例用 CreateAddrReg<T>(j, channelStride) 生成 AddrReg 偏移做 DataCopy，而非 DataCopyGather。
- 同样的 UnPack(uint16→uint32)→Cast<float>→Add 三连链路，UnPack 默认低位模式、单实参（仅传 dst/src，part 取默认 LOWEST）。
- UnPack 升宽后用 p0 mask 做 Cast/Add，p0 是按 fp32 元素数生成的有效 mask。

### 实例 7：arg_max_with_value::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, CreateAddrReg, DataCopyUnAlign, DataCopyUnAlignPre, HighLowPart, MaskOr, MaskReg, PostLiteral, RegTensor, Select, UnalignReg, UpdateMask
- **UnPack 调用次数**: 2
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int32_t+uint32_t`（实参 2 个，类型: int32_t, uint32_t, LOWEST, HighLowPart, LOW）
- **语义**: argmax 取值时对 fp16/bf16 的索引寄存器用 LOWEST/HIGHEST 两次 UnPack 拆成两路 uint32 索引，分别加起始偏置后写回，实现一个 b16 寄存器容纳双倍索引的拆分输出。

（行 971-984）

```cpp
if constexpr (IsSameType<T1, half>::value || (!isBfloat16Casted && IsSameType<T1, bfloat16_t>::value)) {
    maskLower = AscendC::Reg::UpdateMask<uint32_t>(sregMask);
    AscendC::Reg::UnPack<uint32_t, T5, AscendC::Reg::HighLowPart::LOWEST>(indicesLower, vregIndices0);
    AscendC::Reg::UnPack<uint32_t, T5, AscendC::Reg::HighLowPart::HIGHEST>(indicesHigher, vregIndices0);
    Adds(indicesLower, indicesLower, startR, maskLower);
    DataCopy(indexDst, (AscendC::Reg::RegTensor<int32_t> &)indicesLower, indicesOffset, maskLower);
    maskHigher = AscendC::Reg::UpdateMask<uint32_t>(sregMask);
    Adds(indicesHigher, indicesHigher, startR, maskHigher);
    DataCopy(indexDst + repeatElmB32, (AscendC::Reg::RegTensor<int32_t> &)indicesHigher, indicesOffset,
        maskHigher);
} else {
    Adds(vregIndices0, vregIndices0, startR, mask);
    DataCopy(indexDst, (AscendC::Reg::RegTensor<int32_t> &)vregIndices0, indicesOffset, mask);
}
```

**要点**:
- UnPack<uint32_t,T5,HighLowPart::LOWEST/HIGHEST> 把同一 vregIndices0 拆成 indicesLower/indicesHigher 两路 32 位索引。
- 拆半后各自 Adds(_,_,startR,maskLower/maskHigher) 加行起始号，再 DataCopy 到 indexDst 与 indexDst+repeatElmB32 两个相邻段——半区拆分配对输出。
- mask 通过 UpdateMask<uint32_t>(sregMask) 重新生成，因为 UnPack 后元素位宽翻倍、元素个数减半，mask 必须按 32 位重新计算。

### 实例 8：embedding_bag::ComputeBagSize

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopy, DataCopyUnAlign, DataCopyUnAlignPre, MaskMergeMode, MaskPack, MaskReg, RegTensor, Sub, UnalignReg, UpdateMask
- **UnPack 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEnone`（实参 1 个）
- **语义**: embedding_bag 计算 bag size 时，当索引类型 I 是 32 位、元素类型 E 是 16 位（sizeof(I)/sizeof(E)==2）时，把加载到的 16 位偏移原地 UnPack 成 32 位再做 int32→int64 Cast 与 DataCopy。

（行 364-371）

```cpp
if constexpr (sizeof(I) / sizeof(E) == DIGIT_2) {
    AscendC::Reg::UnPack((AscendC::Reg::RegTensor<I>&)offsetsShiftOneReg,
                              (AscendC::Reg::RegTensor<E>&)offsetsShiftOneReg);
    AscendC::Reg::Cast<I, E, castTraitInt32Int64>(bagSizeReg, offsetsShiftOneReg, maskIRegUpdate);
    AscendC::Reg::DataCopy(bagSizeLocalAddrUpdate, bagSizeReg, maskIRegUpdate);
} else {
    AscendC::Reg::DataCopy(bagSizeLocalAddrUpdate, offsetsShiftOneReg, maskERegUpdate);
}
```

**要点**:
- 无显式模板类型参数 UnPack((RegTensor<I>&)dst,(RegTensor<E>&)src)，dst/src 类型由 I/E 隐式推导——I=32 位、E=16 位时即 uint16→uint32 升宽。
- 紧接 Cast<I,E,castTraitInt32Int64> 把 32 位升到 64 位 bagSize，体现 UnPack 升宽 → Cast 再升宽 的两级位宽提升链路。
- if constexpr (sizeof(I)/sizeof(E)==DIGIT_2) 编译期分流：仅当 I 恰好是 E 的两倍位宽时才走 UnPack 路径，否则直接 DataCopy。

### 实例 9：cummin::Ops::Base

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Compare, CreateMask, DataCopy, Duplicate, HighLowPart, MaskPattern, MaskReg, RegTensor, Select, UpdateMask
- **UnPack 调用次数**: 6
- **参数模式**: `T1_A2_M1_TYPEHighLowPart+LOW+LOWEST_MASKMask`（实参 2 个，含 mask/mode: Mask，类型: LOWEST, HighLowPart, LOW）
- **语义**: cummin 算子用 UnPack<HighLowPart::LOWEST/HIGHEST> 把整 mask 拆成低/高两个半 mask，分别驱动 argmin 与 x 的两路 Select，实现一个 mask 寄存器对双半区数据的分别选择。

（行 456-496）

```cpp
        AscendC::Reg::DataCopy(selectXAddr + tmpOffset, xReg, yMaskReg);
        AscendC::Reg::DataCopy(selectargminAddr + tmpOffset, argminReg, yMaskReg);
    }
} else {
    Reg::RegTensor<X> xReg;
    Reg::RegTensor<X> yReg;
    Reg::RegTensor<int32_t> argminReg1;
    Reg::RegTensor<int32_t> argminReg2;
    Reg::RegTensor<int32_t> dupReg;
    AscendC::Reg::MaskReg yMaskReg =
        AscendC::Reg::CreateMask<X, AscendC::Reg::MaskPattern::ALL>();

    AscendC::Reg::MaskReg argminMaskReg1;
    AscendC::Reg::MaskReg argminMaskReg2;
    AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::LOWEST>(argminMaskReg1, yMaskReg);
    AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::HIGHEST>(argminMaskReg2, yMaskReg);

    AscendC::Reg::MaskReg cmpReg;
    AscendC::Reg::MaskReg cmpReg1;
    AscendC::Reg::MaskReg cmpReg2;
    for (int i = 0; i < regComputeTimes; i++) {
        if (i == regComputeTimes - 1 && reservedRegComputeTimes != 0) {
            yMaskReg = Reg::UpdateMask<X>(reservedRegComputeTimes);
            AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::LOWEST>(argminMaskReg1, yMaskReg);
            AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::HIGHEST>(argminMaskReg2, yMaskReg);
        }
        int64_t tmpOffset = i * VREGTENSOR_SIZE / dSize;
        AscendC::Reg::DataCopy(xReg, selectXAddr + tmpOffset);
        AscendC::Reg::DataCopy(argminReg1, selectargminAddr + tmpOffset);
        AscendC::Reg::DataCopy(argminReg2, selectargminAddr + tmpOffset + 64);
        for (int j = 0; j < computeTimes; j++) {
            auto yOffset = tmpOffset + j * allocLength;
            AscendC::Reg::DataCopy(yReg, yAddr + yOffset);
            AscendC::Reg::Duplicate(dupReg, j + duplicate);

            AscendC::Reg::Compare<X, CMPMODE::LT>(cmpReg, xReg, yReg, yMaskReg);
            AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::LOWEST>(cmpReg1, cmpReg);
            AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::HIGHEST>(cmpReg2, cmpReg);

            AscendC::Reg::Select(xReg, xReg, yReg, cmpReg);
            AscendC::Reg::Select(argminReg1, argminReg1, dupReg, cmpReg1);
```

**要点**:
- 唯一的 MaskReg 重载用法：UnPack<HighLowPart::LOWEST>(argminMaskReg1,yMaskReg)，仅一个模板参数（part），dst/src 均为 MaskReg——对应文档原型 void UnPack(MaskReg& dst, MaskReg& src)。
- 对比较结果 cmpReg 同样做 LOWEST/HIGHEST 拆半得到 cmpReg1/cmpReg2，分别 Select argminReg1/argminReg2，对应高/低半区各自的最小值与下标更新。
- 末尾元素不足整寄存器时用 UpdateMask<X>(reservedRegComputeTimes) 重置 yMaskReg 后再次 UnPack 拆半，保证残部 mask 与全量逻辑一致。

### 实例 10：adaptive_pool3d_common::platform::GetVRegSize

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Compare, CreateMask, DataCopy, Duplicate, HighLowPart, MaskReg, Or, RegTensor, Select
- **UnPack 调用次数**: 2
- **参数模式**: `T1_A2_M1_TYPEHighLowPart+LOW+LOWEST_MASKMask`（实参 2 个，含 mask/mode: Mask，类型: LOWEST, HighLowPart, LOW）
- **语义**: 自适应 3D 最大池化的非 float 路径中，对比较 mask cmpMask 用 LOWEST/HIGHEST 两次 UnPack 拆成两个半 mask，分别 Select 更新 maxIndexReg 与 maxIndexReg1（对应低/高半区的最大值下标）。

（行 436-453）

```cpp
for (uint16_t k = 1; k < kernelSize; k++) {
    Reg::DataCopy(inputReg, srcOfset + k * vfLen);
    Reg::Compare<T, CMPMODE::GT>(cmpMask, inputReg, maxReg, fullMask);
    Reg::Compare<T, CMPMODE::NE>(cmpMaskNan, inputReg, inputReg, fullMask);
    Reg::Or(cmpMask, cmpMask, cmpMaskNan, fullMask);
    AscendC::Reg::Select(maxReg, inputReg, maxReg, cmpMask);

    Reg::Adds(inputIndexReg, inputIndexReg, static_cast<int32_t>(1), indexMask);
    if constexpr (IsSameType<T, float>::value) {
        AscendC::Reg::Select(maxIndexReg, inputIndexReg, maxIndexReg, cmpMask);
    } else {
        AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::LOWEST>(cmpIndexMask, cmpMask);
        AscendC::Reg::Select(maxIndexReg, inputIndexReg, maxIndexReg, cmpIndexMask);

        AscendC::Reg::UnPack<AscendC::Reg::HighLowPart::HIGHEST>(cmpIndexMask, cmpMask);
        AscendC::Reg::Select(maxIndexReg1, inputIndexReg, maxIndexReg1, cmpIndexMask);
    }
}
```

**要点**:
- if constexpr (IsSameType<T,float>::value) 分流：float 直接用整 mask Select，非 float（b16）需 UnPack 拆半——因为 b16 一个寄存器装双倍元素，下标选择必须按半区分别进行。
- UnPack<HighLowPart::LOWEST>(cmpIndexMask,cmpMask) 复用同一 cmpIndexMask 变量先后装低半、高半 mask，两次 Select 之间不冲突。
- 与实例 9 同属 mask 拆半模式，但本例只拆 cmpMask 用于下标通道，maxReg 仍用整 cmpMask Select——值与下标走不同 mask 路径。

### 实例 11：cross_entropy_loss::GetRowMax

- **来源类型**: `__aicore__`
- **共现 API**: Cast, Copy, CreateAddrReg, DataCopy, Duplicate, HighLowPart, MaskMergeMode, Max, ReduceMax
- **UnPack 调用次数**: 2
- **参数模式**: `T3_A2_M0_TYPEHighLowPart+LOW+LOWEST+int16_t+int32_t`（实参 2 个，类型: int32_t, int16_t, LOWEST, HighLowPart, LOW）
- **语义**: 交叉熵求行最大值时，因 bf16 不支持 vcmax、fp32 无需拆半，仅对 16 位类型用 LOWEST/HIGHEST 两次 UnPack 把 maxReg 拆成两个 int32 再 Cast float 求 Max+ReduceMax。

（行 285-297）

```cpp
if constexpr (sizeof(T1) == sizeof(half)) {
    // 再做reducemax操作，因为bf16不支持vcmax, FP32不用做这个unpack操作
    AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::LOWEST>(
        (RegTensor<int32_t>&)maxLowReg, (RegTensor<int16_t>&)maxReg);
    AscendC::Reg::UnPack<int32_t, int16_t, AscendC::Reg::HighLowPart::HIGHEST>(
        (RegTensor<int32_t>&)maxHighReg, (RegTensor<int16_t>&)maxReg);
    AscendC::Reg::Cast<float, T1, castB16ToB32>(maxLowRegFp32, maxLowReg, preg2);
    AscendC::Reg::Cast<float, T1, castB16ToB32>(maxHighRegFp32, maxHighReg, preg2);
    AscendC::Reg::Max(maxRegFp32, maxLowRegFp32, maxHighRegFp32, preg2);
    AscendC::Reg::ReduceMax(maxRegLast, maxRegFp32, preg2);
} else {
    AscendC::Reg::ReduceMax((RegTensor<T1>&)maxRegLast, maxReg, preg);
}
```

**要点**:
- 注释明确动机：再做 reducemax 操作，因为 bf16 不支持 vcmax, FP32 不用做这个 unpack 操作——UnPack 是为绕过 bf16 无 vcmax 指令而做的位宽提升。
- UnPack<int32_t,int16_t,LOWEST/HIGHEST> 拆半后各自 Cast<float,T1,castB16ToB32>，再 Max 取两者大值、ReduceMax 归约，等价于对原 b16 行求 max。
- 与实例 3（softmax CE）同模式，差别仅在上下文（行最大值 vs reduce-max 前置）和 aicore 来源类型。

### 实例 12：avg_pool_v2_grad::GetContinuousInput

- **来源类型**: `__aicore__`
- **共现 API**: Cast, CreateMask, DataCopy, MaskPattern, MaskReg, RegTensor
- **UnPack 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: int32_t, uint32_t）
- **语义**: avg_pool 反向梯度的非 float 路径中，把加载到的 16 位梯度原地 UnPack 成 uint32，再 Cast 到 computeType（float）做后续计算。

（行 299-310）

```cpp
if constexpr (std::negation<std::is_same<T1, float>>::value) {
    AscendC::Reg::RegTensor<T1> gradRegT1;
    AscendC::Reg::MaskReg
        allMaskU32 = AscendC::Reg::CreateMask<uint32_t, AscendC::Reg::MaskPattern::ALL>();

    AscendC::Reg::DataCopy(gradRegT1, gradAddr + gradOffset);
    AscendC::Reg::UnPack((AscendC::Reg::RegTensor<uint32_t>&)gradRegT1,
                              (AscendC::Reg::RegTensor<uint16_t>&)gradRegT1);
    AscendC::Reg::Cast<computeType, T1, castTraitT1ComputeType>(gradReg, gradRegT1, allMaskU32);
} else {
    AscendC::Reg::DataCopy(gradReg, gradAddr + gradOffset);
}
```

**要点**:
- if constexpr (std::negation<std::is_same<T1,float>>::value) 分流：非 float 梯度才走 UnPack 升宽，float 直接 DataCopy。
- 先 CreateMask<uint32_t,ALL> 生成全 1 的 32 位 mask，UnPack 后用该 mask 做 Cast——因升宽后元素按 32 位计。
- (RegTensor<uint32_t>&)gradRegT1, (RegTensor<uint16_t>&)gradRegT1 同一变量两种位宽视图的 in-place 升宽写法。

### 实例 13：batch_norm_v3::GatherRunningParamForDtypeT

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopyGather, Pack, UpdateMask
- **UnPack 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: int32_t, uint32_t）
- **语义**: batch_norm 取运行参数的非 float 路径中，先用 Pack 把 32 位 paramOffset 压成 16 位做 DataCopyGather 取数，再 UnPack 把取到的 16 位 srcB16 升回 32 位、Cast float。

（行 124-136）

```cpp
if constexpr (IsSameType<T_RUNNING_MEAN, float>::value) {
    AscendC::Reg::DataCopyGather(dst, (__local_mem__ float*)src, paramOffset, preg);
} else {
    MaskReg pregSrc = AscendC::Reg::UpdateMask<T_RUNNING_MEAN>(calcLen);
    RegTensor<uint16_t> paramOffsetB16;
    RegTensor<T_RUNNING_MEAN> srcB16;
    RegTensor<T_RUNNING_MEAN> srcB16Unpack;
    AscendC::Reg::Pack(paramOffsetB16, paramOffset);
    AscendC::Reg::DataCopyGather(srcB16, ((__local_mem__ T_RUNNING_MEAN*)src), paramOffsetB16, pregSrc);
    AscendC::Reg::UnPack((RegTensor<uint32_t>&)srcB16Unpack, (RegTensor<uint16_t>&)srcB16);
    AscendC::Reg::Cast<float, T_RUNNING_MEAN, castTraitB162B32>(
        dst, srcB16Unpack, preg);
}
```

**要点**:
- 典型 Pack → DataCopyGather → UnPack → Cast 链路：Pack 压位宽以适配 16 位 gather 取数，UnPack 再升回 32 位——Pack/UnPack 互为逆操作配对使用。
- UnPack((RegTensor<uint32_t>&)srcB16Unpack,(RegTensor<uint16_t>&)srcB16) 默认 LOWEST、单实参，把 gather 来的 16 位运行参数零扩展到 32 位。
- if constexpr (IsSameType<T_RUNNING_MEAN,float>::value) 分流：float 直接 DataCopyGather 跳过 Pack/UnPack，仅 16 位参数走升宽路径。

### 实例 14：apply_adam_w::LoadOneTensor

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopy, PostLiteral, RegTensor
- **UnPack 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t`（实参 1 个，类型: int32_t）
- **语义**: apply_adam_w 加载某一 tensor 时，当目标类型 U 是 float 而源 T 不是 float 时，把加载到的 int16 数据 UnPack 成 int32 再 Cast 到 U(float)。

（行 50-56）

```cpp
if constexpr (IsSameType<U, float>::value && !IsSameType<T, U>::value) {
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(regCopyIn, input, (int32_t)oneRepeat);
    Reg::UnPack((RegTensor<int32_t>&)regTmp, (RegTensor<int16_t>&)regCopyIn);
    Reg::Cast<U, T, castTrait0>(dst, regTmp, pregUp);
} else {
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(dst, input, (int32_t)oneRepeat);
}
```

**要点**:
- 唯一的纯 int32 类型签名 T0_A1_M0_TYPEint32_t：UnPack((RegTensor<int32_t>&)regTmp,(RegTensor<int16_t>&)regCopyIn)，int16→int32 升宽，无 uint32 参与。
- DataCopy<T,PostLiteral::POST_MODE_UPDATE> 带 POST_MODE_UPDATE 后处理模式加载，UnPack 紧接其后做位宽提升，再 Cast<U,T,castTrait0>。
- if constexpr (IsSameType<U,float>::value && !IsSameType<T,U>::value) 分流：仅当 U/T 不同且 U 为 float 时走 UnPack+Cast，否则直接 DataCopy 到 dst。

### 实例 15：group_norm_grad::LoadUnAlignOneTensor

- **来源类型**: `__aicore__`
- **共现 API**: (无)
- **UnPack 调用次数**: 2
- **参数模式**: `T0_A1_M0_TYPEint32_t+uint32_t`（实参 1 个，类型: int32_t, uint32_t）
- **语义**: group_norm 反向加载非对齐 tensor 时，对 half/bf16 输入用 DataCopyUnAlign 取数后 UnPack 升宽到 uint32，再 Cast float；float 输入直接 DataCopyUnAlign。

（行 113-127）

```cpp
if constexpr (IsSameType<T, half>::value) {
    RegTensor<half> xFp16;
    RegTensor<half> xFp16UnPack;
    DataCopyUnAlign(xFp16, uSrc, input, postUpdateStride);
    UnPack((RegTensor<uint32_t>&)xFp16UnPack, (RegTensor<uint16_t>&)xFp16);
    Cast<float, half, castTraitB162B32>(dst, xFp16UnPack, preg);
} else if constexpr (IsSameType<T, bfloat16_t>::value) {
    RegTensor<bfloat16_t> xBf16;
    RegTensor<bfloat16_t> xBf16UnPack;
    DataCopyUnAlign(xBf16, uSrc, input, postUpdateStride);
    UnPack((RegTensor<uint32_t>&)xBf16UnPack, (RegTensor<uint16_t>&)xBf16);
    Cast<float, bfloat16_t, castTraitB162B32>(dst, xBf16UnPack, preg);
} else {
    DataCopyUnAlign(dst, uSrc, input, postUpdateStride);
}
```

**要点**:
- 共现 API 仅有 UnPack 自身（无其他共现）——最精简的 UnPack 用法，纯粹做 b16→b32 位宽提升后 Cast fp32。
- half 与 bfloat16_t 两个分支结构完全对称：各自声明 16 位临时寄存器 → DataCopyUnAlign → UnPack(uint16→uint32) → Cast<float>，体现 UnPack 对 half/bf16 的通用性。
- UnPack((RegTensor<uint32_t>&)xFp16UnPack,(RegTensor<uint16_t>&)xFp16) 默认 LOWEST、单实参，与实例 12/13 同属 加载 16 位 → 升 32 位 → Cast fp32 的标准升宽链路。

### UnPack 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| swiglu_mx_quant_with_dual_axis | Adds, And, Cast, Compare, CompareScalar | b16→b32 升宽 + Cast fp32（逐通道缩放 ZERO half） | __VEC_SCOPE__ |
| avg_pool | Add, Arange, Cast, Copy, CreateMask | DataCopyGather→UnPack(u16→u32)→Cast fp32 累加 | __VEC_SCOPE__ |
| softmax_cross_entropy_with_logits | AddrReg, Cast, Copy, CreateAddrReg, CreateMask | LOWEST+HIGHEST 拆半升 int32 再 Cast fp32 求 ReduceMax | __VEC_SCOPE__ |
| tensor_equal | Add, AddrReg, Compare, CreateAddrReg, CreateMask | MaskUnPack 归约计数 + UnPack(u16→u32) 写结果 | __VEC_SCOPE__ |
| sparse_slice | Add, Arange, CreateMask, DataCopy, DataCopyScatter | UnPack(int32→int64) 升宽做 DataCopyScatter 64 位下标 | __VEC_SCOPE__ |
| avg_pool | Add, AddrReg, Cast, CreateAddrReg, DataCopy | AddrReg 偏移加载→UnPack(u16→u32)→Cast fp32 累加 | __VEC_SCOPE__ |
| arg_max_with_value | AddrReg, CreateAddrReg, DataCopyUnAlign, DataCopyUnAlignPre, HighLowPart | LOWEST+HIGHEST 拆半索引 + 加偏置分段写回 | __VEC_SCOPE__ |
| embedding_bag | Cast, DataCopy, DataCopyUnAlign, DataCopyUnAlignPre, MaskMergeMode | 隐式类型 UnPack(I/E)→Cast int32→int64 | __aicore__ |
| cummin | Compare, CreateMask, DataCopy, Duplicate, HighLowPart | MaskReg UnPack 拆半 mask 驱动双半区 Select | __VEC_SCOPE__ |
| adaptive_pool3d_common | Adds, Compare, CreateMask, DataCopy, Duplicate | 非float 分支 UnPack 拆半 mask 选下标 | __VEC_SCOPE__ |
| cross_entropy_loss | Cast, Copy, CreateAddrReg, DataCopy, Duplicate | bf16 无 vcmax，UnPack 拆半升 int32 Cast fp32 求 Max | __aicore__ |
| avg_pool_v2_grad | Cast, CreateMask, DataCopy, MaskPattern, MaskReg | 非float 梯度 UnPack(u16→u32)→Cast computeType | __aicore__ |
| batch_norm_v3 | Cast, DataCopyGather, Pack, UpdateMask | Pack→DataCopyGather→UnPack→Cast 取 16 位运行参数 | __aicore__ |
| apply_adam_w | Cast, DataCopy, PostLiteral, RegTensor | int16→int32 UnPack + Cast float（U≠T 分支） | __aicore__ |
| group_norm_grad |  | DataCopyUnAlign→UnPack(u16→u32)→Cast fp32（half/bf16 对称） | __aicore__ |
