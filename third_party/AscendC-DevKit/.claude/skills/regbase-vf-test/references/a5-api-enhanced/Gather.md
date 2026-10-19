# Gather

**页面ID:** atlasascendc_api_07_0401  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0401.html

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

- 收集UB中的元素

给定源操作数在UB中的基地址和索引，Gather指令根据索引位置将源操作数按元素收集到结果寄存器张量中。收集过程如下图所示：

![](images/atlasascendc_api_07_0401_img_001.png)

- 收集RegTensor中的元素

根据索引位置indexReg将源操作数srcReg按元素收集到结果dstReg中。收集过程如下图所示：

![](images/atlasascendc_api_07_0401_img_002.png)

#### 定义原型

- 收集UB中的元素

```
template <typename T0 = DefaultType, typename T1, typename T2 = DefaultType, typename T3, typename T4>
__simd_callee__ inline void Gather(T3& dstReg, __ubuf__ T1* baseAddr, T4& index, MaskReg& mask)
```

- 收集RegTensor中的元素

```
template <typename T = DefaultType, typename U = DefaultType, typename S, typename V>
__simd_callee__ inline void Gather(S& dstReg, S& srcReg, V& indexReg)
```

#### 参数说明

- 收集UB中的元素

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T0 | 目的操作数的数据类型。 |
| T1 | 源操作数的数据类型。 |
| T2 | 索引值的数据类型。 |
| T3 | 目的操作数的RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| T4 | 索引值的RegTensor类型，例如RegTensor<uint16_t>，由编译器自动推导，用户不需要填写。 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 T0数据类型需要与T1和T2数据类型配套使用。类型配套对应表详见约束说明。 支持的数据类型详见表5。 |
| baseAddr | 输入 | 源操作数在UB中的基地址。 类型为UB指针。 T1数据类型需要与T0和T2数据类型配套使用。类型配套对应表详见约束说明。 支持的数据类型详见表5。 |
| index | 输入 | dstReg中的每个元素在UB中相对于baseAddr的索引位置。地址偏移量要大于等于0。 类型为RegTensor。 T2数据类型需要与T0和T1数据类型配套使用。类型配套对应表详见约束说明。 支持的数据类型详见表5。 |
| mask | 输入 | src element操作有效指示，详细说明请参考MaskReg。 |

- 收集RegTensor中的元素

**表3 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数和源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：b8/b16/b32 |
| U | 索引值的数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t/uint16_t/uint32_t |
| S | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| V | 索引值的RegTensor类型，例如RegTensor<uint16_t>，由编译器自动推导，用户不需要填写。 |

**表4 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| indexReg | 输入 | 数据索引。 类型为RegTensor。 数据类型的位宽需要与目的操作数的位宽保持一致。 srcReg为RegTensor类型，位宽是固定的VL，存储的元素个数固定。如果indexReg中索引值超出当前RegTensor中能存储的最大数据元素个数时，按照如下方式处理：设定当前RegTensor所能存储的最大数据元素个数为vlLength，indexReg中索引值为i，索引值更新为i % vlLength。 |

#### 约束说明

- 收集UB中的元素

  - T0，T1和T2数据类型需要配套使用。配套关系如下表：

**表5 **Gather操作数数据类型对应表

| **T0数据类型** | **T1数据类型** | **T2数据类型** |
| --- | --- | --- |
| int16_t | int8_t | uint16_t |
| uint16_t | uint8_t |  |
| int16_t | int16_t |  |
| uint16_t | uint16_t |  |
| half | half |  |
| bfloat16_t | bfloat16_t |  |
| int32_t | int32_t | uint32_t |
| uint32_t | uint32_t |  |
| float | float |  |
| uint64_t | uint64_t | uint32_t |
| int64_t | int64_t |  |
| uint64_t | uint64_t | uint64_t |
| int64_t | int64_t |  |

  - 当T1为B8数据类型时，T0为B16类型，这种情况下目的操作数的低8位与源操作数相同，高8位自动补0。例如T1为int8数据类型：

40=0b00101000 -> 0b0000000000101000，扩充至16位后等于40；

-40=0b11011000 -> 0b0000000011011000，扩充至16位后等于216。

  - 当T1为B64数据类型时，T0，T1，T2，T4, T3数据类型只支持以下组合:

| **T0数据类型** | **T1数据类型** | **T2数据类型** | T4数据类型 | T3数据类型 | 备注 |
| --- | --- | --- | --- | --- | --- |
| B64 | B64 | uint32_t | RegTensor<uint32_t> | RegTensor<uint64_t, RegTraitNumOne> | index的前32个数有效 |
| RegTensor<int64_t, RegTraitNumOne> |  |  |  |  |  |
| RegTensor<uint64_t, RegTraitNumTwo> | - |  |  |  |  |
| RegTensor<int64_t, RegTraitNumTwo> |  |  |  |  |  |
| B64 | B64 | uint64_t | RegTensor<uint64_t, RegTraitNumOne> | RegTensor<uint64_t, RegTraitNumOne> | - |
| RegTensor<int64_t, RegTraitNumOne> |  |  |  |  |  |
| RegTensor<uint64_t, RegTraitNumTwo> | RegTensor<uint64_t, RegTraitNumOne> | index的前32个数有效 |  |  |  |
| RegTensor<int64_t, RegTraitNumOne> |  |  |  |  |  |
| RegTensor<uint64_t, RegTraitNumTwo> | - |  |  |  |  |
| RegTensor<int64_t, RegTraitNumTwo> |  |  |  |  |  |

- 收集RegTensor中的元素

无约束

#### 调用示例

- 收集UB中的元素

```
template <typename T, typename U>
__simd_vf__ inline void GatherVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ U* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<U> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Gather(dstReg, src0Addr, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 收集RegTensor中的元素

```
template <typename T, typename U>
__simd_vf__ inline void GatherVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ U* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0, dstReg;
    AscendC::Reg::RegTensor<U> srcReg1;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::LoadAlign(srcReg1, src1Addr);
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::Gather(dstReg, srcReg0, srcReg1);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Gather 实例

### 实例 1：swiglu_backward_mx_quant_with_dual_axis::ops::CeilDiv

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Adds, And, Arange, Cast, Compare, CompareScalar, CreateMask, DataCopy, Duplicate, HighLowPart, LoadDist, MaskAnd, MaskOr, MaskPattern, MaskReg, Max, Mul, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftLefts, ShiftRights, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignReg
- **Gather 调用次数**: 6
- **参数模式**: `T0_A3_M0_TYPEint8_t+uint8_t`（实参 3 个，类型: uint8_t, int8_t）
- **语义（待补充）**: 在 SwiGLU 反向的 MX 量化场景中，按 Arange 生成的连续/步长索引从 scale 寄存器收集 scale 元素，再经 DataCopy 搬运到 UB，供后续量化缩放使用。

（行 971-989）

```cpp
for (uint16_t k = 0; k < 8; k++) {
    // 8: scale1的搬运, 每次循环索引值的更新步长为8
    Reg::Arange(extractIdx, static_cast<int8_t>(k * 8));
    Reg::Gather(scale8Row, scale8Reg, (Reg::RegTensor<uint8_t>&)extractIdx);
    Reg::Gather(scale8Swapped, scale8Row, (Reg::RegTensor<uint8_t>&)indexShiftS8);

    // 32: 偏移32字节
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScaleA1Addr, scale8Row, 32,
                                                                         maskReduceB8);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScaleA2Addr, scale8Swapped, 32,
                                                                         maskReduceB8);

    // 16: 1/scale1的搬运, 每次循环索引值的更新步长为16
    Reg::Arange(extractIdx, static_cast<int8_t>(k * 16));
    Reg::Gather((Reg::RegTensor<uint8_t>&)recip16Row, (Reg::RegTensor<uint8_t>&)regU16_2,
                     (Reg::RegTensor<uint8_t>&)extractIdx);
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(mxScale1ReciprocalAddr,
                                                                          recip16Row, 16, maskReduceB16);
}
```

**要点**: 1) 索引由 Arange 生成（步长 8 或 16），Gather 据此从源 RegTensor 收集元素到目的 RegTensor；2) 二次 Gather 以第一次结果为源，实现索引重排/交换；3) 源/目类型为 uint8_t/int8_t，需与约束表类型配套关系一致。

### 实例 2：quant_sparse_flash_mla::ProcessVec1UpdateGeneralImpl128VF

- **来源类型**: `__simd_vf__`
- **共现 API**: Add, Cast, CreateMask, DataCopyMode, Duplicate, ExpSub, LoadAlign, LoadDist, LocalMemBar, MaskMergeMode, MaskPattern, MaskReg, Max, Muls, Or, PostLiteral, Reduce, ReduceType, RegTensor, Select, StoreAlign, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **Gather 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在稀疏 flash MLA 注意力的 exp 合并阶段，对 hifloat8_t 类型先用 Or 合并奇偶 exp，再按从 UB 加载的索引 Gather 重排元素后存回 UB。

（行 111-138）

```cpp
if constexpr (IsSameType<T2, bfloat16_t>::value) {
    AscendC::Reg::Cast<T2, T, castTraitZero>(vreg_exp_even_bf16, vreg_exp_even, preg_all);
    AscendC::Reg::Cast<T2, T, castTraitOne>(vreg_exp_odd_bf16, vreg_exp_odd, preg_all);
    AscendC::Reg::Or((RegTensor<uint16_t>&)vreg_exp_bf16, (RegTensor<uint16_t>&)vreg_exp_even_bf16,
        (RegTensor<uint16_t>&)vreg_exp_odd_bf16, preg_all_b16);
    AscendC::Reg::StoreAlign<T2, Reg::DataCopyMode::DATA_BLOCK_COPY, Reg::PostLiteral::POST_MODE_UPDATE>(
        ((__ubuf__ T2 *&)expUb), vreg_exp_bf16, blockStride, repeatStride, preg_n_b16);
} else if constexpr (IsSameType<T2, hifloat8_t>::value) {
    // hifloat8_t
    AscendC::Reg::RegTensor<hifloat8_t> vreg_exp_even_hifp8;
    AscendC::Reg::RegTensor<hifloat8_t> vreg_exp_odd_hifp8;
    AscendC::Reg::RegTensor<hifloat8_t> vreg_exp_merge_tmp_hifp8;
    AscendC::Reg::RegTensor<hifloat8_t> vreg_exp_hifp8;
    AscendC::Reg::RegTensor<uint8_t> vreg_exp_merge_hifp8_indexes;
    AscendC::Reg::MaskReg preg_all_b8 =
        AscendC::Reg::CreateMask<uint8_t, AscendC::Reg::MaskPattern::ALL>();
    uint32_t maskLen = 128;
    AscendC::Reg::MaskReg preg_all_b8_128 = UpdateMask<T2>(maskLen);
    AscendC::Reg::Cast<T2, T, castTraitZero>(vreg_exp_even_hifp8, vreg_exp_even, preg_all);
    AscendC::Reg::Cast<T2, T, castTraitTwo>(vreg_exp_odd_hifp8, vreg_exp_odd, preg_all);
    AscendC::Reg::Or((RegTensor<uint8_t> &)vreg_exp_merge_tmp_hifp8,
                          (RegTensor<uint8_t> &)vreg_exp_even_hifp8, (RegTensor<uint8_t> &)vreg_exp_odd_hifp8,
                          preg_all_b8);
    AscendC::Reg::LoadAlign(vreg_exp_merge_hifp8_indexes, indexesUb);
    AscendC::Reg::Gather(vreg_exp_hifp8, vreg_exp_merge_tmp_hifp8, vreg_exp_merge_hifp8_indexes);
    AscendC::Reg::StoreAlign<T2, Reg::DataCopyMode::DATA_BLOCK_COPY, Reg::PostLiteral::POST_MODE_UPDATE>(
        ((__ubuf__ T2 *&)expUb), vreg_exp_hifp8, blockStride, repeatStride, preg_all_b8_128);
}
```

**要点**: 1) 三参 Gather：目的=合并后 exp RegTensor，源=Or 合并的临时 RegTensor，索引=LoadAlign 从 UB 取的 indexes；2) 索引寄存器经 LoadAlign 从 UB 加载，实现按外部索引表重排；3) 配合 UpdateMask(128) 控制 b8 元素有效长度。

### 实例 3：lightning_indexer::FindHighTargetBinVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: AR, Arange, ClearSpr, Compare, CreateMask, Duplicate, GatherMaskMode, LoadAlign, LoadDist, LocalMemBar, MaskPattern, MaskReg, MemType, PostLiteral, RegTensor, Select, ShiftRights, Squeeze, StoreAlign, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore
- **Gather 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: maskReg, mask）
- **语义（待补充）**: 在 lightning indexer 的 TopK 桶查找中，将高 8 位索引右移得到上一个桶号，带 maskReg 用 Gather 从直方图 UB 收集该桶的历史值。

（行 116-134）

```cpp
Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idxHigh, idxHighBuf);

Reg::RegTensor<uint8_t> idxAll1Reg;
Reg::RegTensor<uint32_t> idxPrev0Reg;
Reg::RegTensor<uint32_t> prevBinValueReg;
Reg::Duplicate(idxAll1Reg, 1);

Reg::RegTensor<uint32_t> zeroAllReg;
Reg::Duplicate(zeroAllReg, 0);

Reg::MaskReg preg0 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
Reg::Compare<uint32_t, CMPMODE::EQ>(preg0, idxHigh, zeroAllReg, maskRegB32);
Reg::Sub(idxPrev0Reg, idxHigh, (Reg::RegTensor<uint32_t>&)idxAll1Reg, maskRegB32);
Reg::ShiftRights(idxPrev0Reg, idxPrev0Reg, (int16_t)24, maskRegB32);

Reg::Gather(prevBinValueReg, histogramsBuf, idxPrev0Reg, maskRegB32);
Reg::Select(prevBinValueReg, zeroAllReg, prevBinValueReg, preg0);

Reg::RegTensor<uint32_t> nextK;
```

**要点**: 1) 四参+mask 形式 Gather(dst, baseAddr, index, maskReg)，mask 控制有效元素；2) 索引由 Sub+ShiftRights 计算（桶号减 1 后右移 24 位）；3) Gather 后接 Select 对 idxHigh==0 位置置零，处理边界。

### 实例 4：quant_lightning_indexer_v2::FindHighTargetBinVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: AR, Arange, ClearSpr, Compare, CreateMask, Duplicate, GatherMaskMode, LoadAlign, LoadDist, LocalMemBar, MaskPattern, MaskReg, MemType, PostLiteral, RegTensor, Select, ShiftRights, Squeeze, StoreAlign, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore
- **Gather 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在量化 lightning indexer v2 的 TopK 桶查找中，按右移得到的上一桶号从直方图 UB 收集历史值，再 Select 处理 idxHigh==0 的边界。

（行 105-123）

```cpp
Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idxHigh, idxHighBuf);

Reg::RegTensor<uint8_t> idxAll1;
Reg::RegTensor<uint32_t> idxPrev0;
Reg::RegTensor<uint32_t> prevBinValue;
Reg::Duplicate(idxAll1, 1);

Reg::RegTensor<uint32_t> zeroAll;
Reg::Duplicate(zeroAll, 0);

Reg::MaskReg preg0 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
Reg::Compare<uint32_t, CMPMODE::EQ>(preg0, idxHigh, zeroAll, pregB32);
Reg::Sub(idxPrev0, idxHigh, (Reg::RegTensor<uint32_t>&)idxAll1, pregB32);
Reg::ShiftRights(idxPrev0, idxPrev0, (int16_t)24, pregB32);

Reg::Gather(prevBinValue, histogramsBuf, idxPrev0, pregB32);
Reg::Select(prevBinValue, zeroAll, prevBinValue, preg0);

Reg::RegTensor<uint32_t> nextK;
```

**要点**: 1) 四参 Gather(dst, baseAddr, index, pregB32)，索引来自 Sub+ShiftRights 计算；2) 与实例 3 同逻辑但无显式 mask token，体现同场景不同写法；3) Gather+Select 组合处理首桶边界。

### 实例 5：stem_indexer::FindHighTargetBinVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: AR, Arange, ClearSpr, Compare, CreateMask, Duplicate, GatherMaskMode, LoadAlign, LoadDist, LocalMemBar, MaskPattern, MaskReg, MemType, PostLiteral, RegTensor, Select, ShiftRights, Squeeze, StoreAlign, StoreDist, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore
- **Gather 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义（待补充）**: 在 stem indexer 的 TopK 桶查找中，按上一桶号从直方图 UB 收集历史值，Select 处理首桶边界。

（行 107-125）

```cpp
Reg::LoadAlign<uint32_t, Reg::LoadDist::DIST_BRC_B8>(idxHigh, idxHighBuf);

Reg::RegTensor<uint8_t> idxAll1;
Reg::RegTensor<uint32_t> idxPrev0;
Reg::RegTensor<uint32_t> prevBinValue;
Reg::Duplicate(idxAll1, 1);

Reg::RegTensor<uint32_t> zeroAll;
Reg::Duplicate(zeroAll, 0);

Reg::MaskReg preg0 = Reg::CreateMask<uint32_t, Reg::MaskPattern::ALL>();
Reg::Compare<uint32_t, CMPMODE::EQ>(preg0, idxHigh, zeroAll, pregB32);
Reg::Sub(idxPrev0, idxHigh, (Reg::RegTensor<uint32_t>&)idxAll1, pregB32);
Reg::ShiftRights(idxPrev0, idxPrev0, (int16_t)24, pregB32);

Reg::Gather(prevBinValue, histogramsBuf, idxPrev0, pregB32);
Reg::Select(prevBinValue, zeroAll, prevBinValue, preg0);

Reg::RegTensor<uint32_t> nextK;
```

**要点**: 1) 四参 Gather 从直方图 UB 按计算索引收集；2) 索引由 idxHigh 减 1 再右移 24 位得到；3) 与 lightning_indexer 系列同构，体现跨算子复用。

### 实例 6：quant_sparse_flash_mla::ProcessVec1UpdateImpl64VF

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, CreateMask, DataCopyMode, DeInterleave, ExpSub, LoadAlign, LoadDist, LocalMemBar, MaskMergeMode, MaskPattern, MaskReg, Max, Muls, PostLiteral, Reduce, ReduceType, RegTensor, StoreAlign, StoreDist, StoreUnAlign, StoreUnAlignPost, UnalignRegForStore, UpdateMask
- **Gather 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在 64 VF 块的稀疏 flash MLA exp 处理中，对 hifloat8_t 类型按从 UB 加载的索引 Gather 重排 exp 元素后存回。

（行 91-108）

```cpp
if constexpr (IsSameType<T2, bfloat16_t>::value) {
     AscendC::Reg::Cast<T2, T, castTraitZero>(vreg_exp_bf16, vreg_exp, preg_all_b16);
     AscendC::Reg::DeInterleave(vreg_dst_even_bf16, vreg_dst_odd_bf16,
             vreg_exp_bf16, vreg_exp_bf16);
     AscendC::Reg::StoreAlign<T2, Reg::DataCopyMode::DATA_BLOCK_COPY, Reg::PostLiteral::POST_MODE_UPDATE>(
         ((__ubuf__ T2 *&)expUb), vreg_dst_even_bf16, blockStride, repeatStride, preg_src_n_b16);
 } else if constexpr (IsSameType<T2, hifloat8_t>::value) {
     AscendC::Reg::RegTensor<hifloat8_t> vreg_exp_hifp8;
     AscendC::Reg::RegTensor<uint8_t> vreg_exp_merge_hifp8_indexes;
     AscendC::Reg::RegTensor<hifloat8_t> vreg_exp_merge_hifp8;
     uint32_t maskLen = 128;
     AscendC::Reg::MaskReg preg_all_b8_128 = UpdateMask<T2>(maskLen);
     AscendC::Reg::Cast<T2, T, castTraitZero>(vreg_exp_hifp8, vreg_exp, preg_all);
     AscendC::Reg::LoadAlign(vreg_exp_merge_hifp8_indexes, indexesUb);
     AscendC::Reg::Gather(vreg_exp_merge_hifp8, vreg_exp_hifp8, vreg_exp_merge_hifp8_indexes);
     AscendC::Reg::StoreAlign<T2, Reg::DataCopyMode::DATA_BLOCK_COPY, Reg::PostLiteral::POST_MODE_UPDATE>(
         ((__ubuf__ T2 *&)expUb), vreg_exp_merge_hifp8, blockStride, repeatStride, preg_all_b8_128);
 }
```

**要点**: 1) 三参 Gather(dst, src RegTensor, index RegTensor)，源为 Cast 后的 exp；2) 索引由 LoadAlign 从 UB 加载；3) 配合 DeInterleave（bf16 分支）与 Gather（hifp8 分支）按类型分派。

### 实例 7：dynamic_block_mx_quant::AscendC::RoundMode

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, Cast, Compare, CreateMask, Duplicate, HighLowPart, LoadAlign, LoadDist, MaskPattern, MaskReg, Max, Pack, PostLiteral, ReduceMaxWithDataBlock, RegTensor, Select, ShiftRights, StoreAlign, Sub
- **Gather 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在动态分块 MX 量化中，按从 UB 加载的 gatherIndex 用 Gather 从打包后的 b8 scale 寄存器收集 scale 元素并存储。

（行 700-720）

```cpp
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

Reg::Pack<uint8_t, uint16_t, Reg::HighLowPart::LOWEST>(mxScale1B8, mxScaleB16);
Reg::LoadAlign(gatherIndex, gatherIndexAddr);
Reg::Gather(mxScale2B8, mxScale1B8, gatherIndex);
Reg::StoreAlign(mxScale2Addr, mxScale2B8, maskB8);
Reg::And(expTmpMaxDim, expMaxDim, expMaskBF16, maskAll);
// compute  1/scale
// 只有在E1M2时，yMaxExp=0，xTmp0ExpBF16可能会等于biasE8M0
Reg::Compare<uint16_t, CMPMODE::EQ>(invalidDataMask, expTmpMaxDim, biasE8M0, maskAll);
```

**要点**: 1) 三参 Gather(dst b8, src b8, index)，源是 Pack 得到的 b8 scale；2) 索引 gatherIndex 由 LoadAlign 从 UB 加载；3) 前置 Pack(LOWEST) 把 b16 scale 压成 b8，再 Gather 重排。

### 实例 8：common::AntiquantVFImplFP4_unalign

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, CreateMask, DataCopyMode, Duplicate, LoadAlign, LoadDist, LoadUnAlign, LoadUnAlignPre, MaskGenWithRegTensor, MaskMergeMode, MaskPattern, MaskReg, Mul, PostLiteral, RegTensor, StoreAlign, UnalignRegForLoad, Unsqueeze
- **Gather 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在 FP4 反量化的逐行循环中，按前缀和索引 prefixSum 用 Gather 从 scale 寄存器收集对应 scale 元素，再与权重相乘完成反量化。

（行 877-901）

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(dealRowCount); i++) { 
    Reg::LoadAlign<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE, Reg::LoadDist::DIST_UNPACK4_B8>
      ((Reg::RegTensor<uint8_t>&)w_nd_f4, ubSrcTemp, baseSize / 2); // 每次ub往后偏移baseSize / 2

    // cast操作
    Reg::Cast<bfloat16_t, KV_T, castTraitW4>(w_nd_bf16, (Reg::RegTensor<KV_T>&)w_nd_f4, preg_0);
    // 加载 scale
    Reg::LoadUnAlignPre(u0, (__ubuf__ bfloat16_t *&)ubScalerSrcAddrTemp);
    Reg::LoadUnAlign<bfloat16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        scale, u0, (__ubuf__ bfloat16_t *&)ubScalerSrcAddrTemp, scaleStride);
    Reg::Gather(scale, scale, prefixSum);
    // mul操作
    Reg::Mul<bfloat16_t, Reg::MaskMergeMode::ZEROING>(v_mul_res, scale, w_nd_bf16, preg_0);

    if constexpr (std::is_same<Q_T, bfloat16_t>::value) {
      // 将输出结果copy到UB
      Reg::StoreAlign<Q_T, Reg::DataCopyMode::DATA_BLOCK_COPY, 
          Reg::PostLiteral::POST_MODE_UPDATE>(ubDstAddrTmp, v_mul_res, blockStride, repeatStride, preg_0);
    } else {
      Reg::Cast<half, bfloat16_t, castTraitW4_1>(w_nd_f16, v_mul_res, preg_0);
      // 将输出结果copy到UB
      Reg::StoreAlign<half, Reg::DataCopyMode::DATA_BLOCK_COPY, 
          Reg::PostLiteral::POST_MODE_UPDATE>(ubDstAddrTmp, w_nd_f16, blockStride, repeatStride, preg_0);
    }
}
```

**要点**: 1) 三参 Gather(dst, src, prefixSum)，用前缀和索引对 scale 重排/广播；2) 源和目同名（scale），实现原地按索引重排；3) 后接 Mul(ZEROING) 做 scale×weight 反量化。

### 实例 9：mhc_sinkhorn_backward::MhcSinkhornBackwardSimd::CalcRowBackward

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CreateMask, DataCopy, DataCopyGather, DataCopyScatter, Div, LoadAlign, LoadDist, LocalMemBar, MaskPattern, MaskReg, MemType, Mul, ReduceSumWithDataBlock, RegTensor, Sub, UpdateMask
- **Gather 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEint32_t+uint32_t`（实参 3 个，类型: int32_t, uint32_t）
- **语义（待补充）**: 在 Sinkhorn 反向中，用 Gather 把每行归约后的 sum 按 broadcastReg 索引广播到各元素，再做减法和除法归一化。

（行 180-196）

```cpp
for (uint16_t k = 0; k < static_cast<uint16_t>(nSize_); k++) {
    // 根据索引位置将输入gradYAddr对应元素搬入gradYReg
    Reg::DataCopyGather(gradYReg, gradYAddr + j * repeatSize * nSize_ * nSize_ + k * nSize_,
        (Reg::RegTensor<uint32_t> &)(indexReg), CalcMaskReg);
    Reg::DataCopy(normReg, normAddr + k * perloopSize * nAlignSize_ + j * repeatSize * nAlignSize_);
    Reg::DataCopy<float, Reg::LoadDist::DIST_E2B_B32>(sumReg,
        sumAddr + k * perloopSizePad + j * repeatSize);

    Reg::Mul(dotProdReg, gradYReg, normReg, CalcMaskReg);
    Reg::ReduceSumWithDataBlock(sumGradYReg, dotProdReg, CalcMaskReg);
    Reg::Gather(sumBrcbReg, sumGradYReg, (Reg::RegTensor<uint32_t> &)(broadcastReg));
    Reg::Sub(dotProdReg, gradYReg, sumBrcbReg, CalcMaskReg);
    Reg::Div(dotProdReg, dotProdReg, sumReg, CalcMaskReg);

    Reg::DataCopyScatter(gradYAddr + j * repeatSize * nSize_ * nSize_ + k * nSize_,
        dotProdReg, (Reg::RegTensor<uint32_t> &)(indexReg), CalcMaskReg);
}
```

**要点**: 1) 三参 Gather(dst, src, broadcastReg)，类型 int32_t/uint32_t 配套；2) Gather 把 ReduceSum 标量结果按广播索引展开到 RegTensor；3) 与 DataCopyGather/DataCopyScatter 形成 gather→compute→scatter 链。

### 实例 10：lightning_indexer::MulWeightAndReduceSum

- **来源类型**: `__aicore__`
- **共现 API**: Cast, CastTrait, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskPattern, MaskReg, MulAddDst, RegLayout, RegTensor, Relu, SatMode, StoreAlign, StoreDist
- **Gather 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在 lightning indexer 的加权归约中，按循环索引 i（Duplicate 生成）用 Gather 从权重 regW 广播收集到 regwBrc，再做乘累加。

（行 230-241）

```cpp
for (uint16_t i = (uint16_t)(0); i < (uint16_t)(gSize); ++i) {
    AscendC::Reg::Duplicate(brcGatherIndex, i);
    AscendC::Reg::LoadAlign<float>(regQK[0], qk0 + 128 * i);
    AscendC::Reg::LoadAlign<float>(regQK[1], qk1 + 128 * i);
    AscendC::Reg::Gather(regwBrc, regW, brcGatherIndex);

    AscendC::Reg::Relu(regQK[0], regQK[0], maskAll);
    AscendC::Reg::Relu(regQK[1], regQK[1], maskAll);

    AscendC::Reg::MulAddDst(regSum[0], regQK[0], regwBrc, maskAll);
    AscendC::Reg::MulAddDst(regSum[1], regQK[1], regwBrc, maskAll);
}
```

**要点**: 1) 三参 Gather(dst, src RegTensor, index)，索引由 Duplicate 设为循环变量 i；2) Gather 实现按标量索引广播同一权重到整个 RegTensor；3) 后接 Relu+MulAddDst 完成 QK×w 乘累加。

### 实例 11：common::ProcessVec1UpdateGeneralImpl128Mxfp8FullquantVFSubloop1

- **来源类型**: `__simd_vf__`
- **共现 API**: CastTrait, DataCopyMode, HighLowPart, LoadAlign, LoadDist, MaskDist, MaskMergeMode, Pack, PostLiteral, ReduceType, RegLayout, RegTensor, SatMode, StoreDist
- **Gather 调用次数**: 3
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在 mxfp8 fullquant 的 exp 合并中，对 fp8_e4m3 与 hifloat8 类型分别用 Or 合并奇偶 exp，再按从 UB 加载的索引 Gather 重排后存回。

**片段 1** (行 671-687):

```cpp
    RegTensor<fp8_e4m3fn_t> vreg_exp_even_f8e4m3;
    RegTensor<fp8_e4m3fn_t> vreg_exp_odd_f8e4m3;
    RegTensor<fp8_e4m3fn_t> vreg_exp_merge_tmp_f8e4m3;
    RegTensor<fp8_e4m3fn_t> vreg_exp_merge_f8e4m3;
    RegTensor<uint8_t> vreg_exp_merge_f8e4m3_indexes;
    MaskReg preg_all_b8 = CreateMask<T2, MaskPattern::ALL>();
    uint32_t maskLen = 128;
    MaskReg preg_all_b8_128 = UpdateMask<T2>(maskLen);
    Cast<T2, T, castTraitRintZero>(vreg_exp_even_f8e4m3, vreg_exp_even, preg_all);
    Cast<T2, T, castTraitRintTwo>(vreg_exp_odd_f8e4m3, vreg_exp_odd, preg_all);
    Or((RegTensor<uint8_t> &)vreg_exp_merge_tmp_f8e4m3, (RegTensor<uint8_t> &)vreg_exp_even_f8e4m3,
       (RegTensor<uint8_t> &)vreg_exp_odd_f8e4m3, preg_all_b8);
    LoadAlign(vreg_exp_merge_f8e4m3_indexes, indexesUb);
    Gather(vreg_exp_merge_f8e4m3, vreg_exp_merge_tmp_f8e4m3, vreg_exp_merge_f8e4m3_indexes);
    StoreAlign<T2, Reg::DataCopyMode::DATA_BLOCK_COPY, Reg::PostLiteral::POST_MODE_UPDATE>(
        ((__ubuf__ T2 *&)expUb), vreg_exp_merge_f8e4m3, blockStride, dupStride, preg_all_b8_128);
} else if constexpr (IsSameType<T2, int8_t>::value) {
```

**片段 2** (行 711-727):

```cpp
    RegTensor<hifloat8_t> vreg_exp_even_hif8;
    RegTensor<hifloat8_t> vreg_exp_odd_hif8;
    RegTensor<hifloat8_t> vreg_exp_merge_tmp_hif8;
    RegTensor<hifloat8_t> vreg_exp_merge_hif8;
    RegTensor<uint8_t> vreg_exp_merge_hif8_indexes;
    MaskReg preg_all_b8 = CreateMask<T2, MaskPattern::ALL>();
    uint32_t maskLen = 128;
    MaskReg preg_all_b8_128 = UpdateMask<T2>(maskLen);
    Cast<T2, T, castTraitZero>(vreg_exp_even_hif8, vreg_exp_even, preg_all);
    Cast<T2, T, castTraitTwo>(vreg_exp_odd_hif8, vreg_exp_odd, preg_all);
    Or((RegTensor<uint8_t> &)vreg_exp_merge_tmp_hif8, (RegTensor<uint8_t> &)vreg_exp_even_hif8,
       (RegTensor<uint8_t> &)vreg_exp_odd_hif8, preg_all_b8);
    LoadAlign(vreg_exp_merge_hif8_indexes, indexesUb);
    Gather(vreg_exp_merge_hif8, vreg_exp_merge_tmp_hif8, vreg_exp_merge_hif8_indexes);
    StoreAlign<T2, Reg::DataCopyMode::DATA_BLOCK_COPY, Reg::PostLiteral::POST_MODE_UPDATE>(
        ((__ubuf__ T2 *&)expUb), vreg_exp_merge_hif8, blockStride, dupStride, preg_all_b8_128);
} else {
```

**要点**: 1) 两段片段按类型分派，Gather 用法一致：三参，索引来自 LoadAlign；2) 配合 CastTrait(Zero/Two) 处理奇偶 exp 的类型转换；3) UpdateMask(128) 控制 b8 有效长度。

### 实例 12：lightning_indexer::FindRealIndexVFImpl

- **来源类型**: `__simd_vf__`
- **共现 API**: Add, Adds, Compares, CreateMask, LoadAlign, LoadDist, MaskPattern, MaskReg, RegTensor, StoreAlign, StoreDist, Xor
- **Gather 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEint32_t+uint32_t`（实参 4 个，类型: int32_t, uint32_t）
- **语义（待补充）**: 在 lightning indexer 的真实索引查找中，按当前 tmpIdx 用带 mask 的 Gather 从历史索引 UB 收集对应历史索引，再叠加偏移得到真实索引。

（行 360-374）

```cpp
for (uint16_t i = 0; i < (uint16_t)(vfLoop); ++i) {
    Reg::LoadAlign<uint16_t, Reg::LoadDist::DIST_UNPACK_B16>(tmpIdx, tmpIdxBuf + i * 64);

    Reg::Compares<uint32_t, CMPMODE::GT>(pregNow,
        (Reg::RegTensor<uint32_t>&)tmpIdx, topK - 1, maskRegB32);
    Reg::Xor(pregHis, pregNow, maskRegB32, maskRegB32);

    Reg::Gather(outputGatherIdx, hisIdxBuf, (Reg::RegTensor<uint32_t>&)tmpIdx, pregHis);
    Reg::Adds(outputAddsIdx, (Reg::RegTensor<uint32_t>&)tmpIdx, loopIndex, pregNow);

    Reg::Add(outputGatherIdx, outputGatherIdx, outputAddsIdx, maskRegB32);

    Reg::StoreAlign<uint32_t, Reg::StoreDist::DIST_NORM>(outputIdxBuf + i * 64,
        outputGatherIdx, maskRegB32);
}
```

**要点**: 1) 四参 Gather(dst, baseAddr, index, mask)，mask 由 Compares+Xor 生成控制有效元素；2) 索引 tmpIdx 从 UB 加载，类型 uint32；3) Gather 后 Adds 叠加 loopIndex 偏移，处理越界分支。

### 实例 13：lightning_indexer_v2::MulWeightAndReduceSum

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, Duplicate, LoadAlign, LoadDist, MaskPattern, MaskReg, MulAddDst, RegTensor, Relu, StoreAlign, StoreDist
- **Gather 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在 lightning indexer v2 的加权归约中，按循环索引 i 用 Gather 从权重 regW 广播收集，再 Relu+MulAddDst 乘累加。

（行 97-108）

```cpp
for (uint16_t i = (uint16_t)(0); i < (uint16_t)(gSize); ++i) {
    AscendC::Reg::Duplicate(brcGatherIndex, i);
    AscendC::Reg::LoadAlign<float>(regQK[0], qk0 + 128 * i);
    AscendC::Reg::LoadAlign<float>(regQK[1], qk1 + 128 * i);
    AscendC::Reg::Gather(regwBrc, regW, brcGatherIndex);

    AscendC::Reg::Relu(regQK[0], regQK[0], maskAll);
    AscendC::Reg::Relu(regQK[1], regQK[1], maskAll);

    AscendC::Reg::MulAddDst(regSum[0], regQK[0], regwBrc, maskAll);
    AscendC::Reg::MulAddDst(regSum[1], regQK[1], regwBrc, maskAll);
}
```

**要点**: 1) 三参 Gather，索引由 Duplicate 设为循环变量；2) 实现按标量索引广播权重；3) 与实例 10 同构，跨算子复用。

### 实例 14：mhc_pre_backward::Reg::StoreAlign

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CreateMask, Duplicate, LoadAlign, LoadDist, MaskPattern, MaskReg, Mul, RegTensor, StoreAlign, UpdateMask
- **Gather 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: 在 mhc_pre_backward 中，用 Gather 把 hPre 的单个值按偏移索引广播到整个 RegTensor，再与 hIn 梯度相乘。

（行 1145-1162）

```cpp
for (uint16_t tIdx = 0; tIdx < (uint16_t)currentChunkSize; tIdx++) {
    uint32_t lenND = copySizeND;
    uint32_t hInOffset = tIdx * copySizeND;

    // Load hPre [1] -> [copySizeND]
    Reg::Duplicate(hPreIndexReg, hPreOffset, maskAll);
    Reg::Gather(hPreFullReg, hPreUbAddr, hPreIndexReg, maskAll);
    for (uint16_t vfBlockIdx = 0; vfBlockIdx < vfLoopCnt; vfBlockIdx++) {
        mask = Reg::UpdateMask<P>(lenND);
        // hIn B16 -> B32
        Reg::LoadAlign<T, Reg::LoadDist::DIST_UNPACK_B16>(hInReg, hInGradInBufAddr + hInOffset);
        Reg::Cast<float, T, ctHalf2Fp32Zero>(hInFP32Reg, hInReg, mask);
        Reg::Mul(hInFP32Reg, hInFP32Reg, hPreFullReg, mask);
        Reg::StoreAlign(xGradVec3BufAddr + hInOffset, hInFP32Reg, mask);
        hInOffset += eleNumPerVf_;
    }
    hPreOffset += N_;
}
```

**要点**: 1) 四参+mask Gather(dst, baseAddr, index, maskAll)，索引由 Duplicate 设为偏移；2) Gather 把 UB 中某个 hPre 值广播到全 RegTensor；3) 内层循环用 UpdateMask 处理尾块长度。

### 实例 15：quant_block_sparse_attn::ProcessVec1UpdateGeneralImpl128VF

- **来源类型**: `__simd_vf__`
- **共现 API**: DataCopyMode, LoadAlign, LoadDist, MaskDist, MaskMergeMode, PostLiteral, ReduceType, StoreDist
- **Gather 调用次数**: 3
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义（待补充）**: 在 block sparse attention 的 exp 合并中，对 fp8_e5m2/e4m3/hifloat8 三种类型分别用 Or 合并奇偶 exp，按从 UB 加载的索引 Gather 重排后存回。

（行 166-214）

```cpp
if constexpr (IsSameType<T2, fp8_e5m2_t>::value) {
    RegTensor<fp8_e5m2_t> vreg_exp_even_f8e5m2;
    RegTensor<fp8_e5m2_t> vreg_exp_odd_f8e5m2;
    RegTensor<fp8_e5m2_t> vreg_exp_merge_tmp_f8e5m2;
    RegTensor<fp8_e5m2_t> vreg_exp_merge_f8e5m2;
    RegTensor<uint8_t> vreg_exp_merge_f8e5m2_indexes;
    MaskReg preg_all_b8 = CreateMask<T2, MaskPattern::ALL>();
    uint32_t maskLen = 128;
    MaskReg preg_all_b8_128 = UpdateMask<T2>(maskLen);
    Cast<T2, T, castTraitRintZero>(vreg_exp_even_f8e5m2, vreg_exp_even, preg_all);
    Cast<T2, T, castTraitRintTwo>(vreg_exp_odd_f8e5m2, vreg_exp_odd, preg_all);
    Or((RegTensor<uint8_t>&)vreg_exp_merge_tmp_f8e5m2, (RegTensor<uint8_t>&)vreg_exp_even_f8e5m2, (RegTensor<uint8_t>&)vreg_exp_odd_f8e5m2, preg_all_b8);
    LoadAlign(vreg_exp_merge_f8e5m2_indexes, indexesUb);
    Gather(vreg_exp_merge_f8e5m2, vreg_exp_merge_tmp_f8e5m2, vreg_exp_merge_f8e5m2_indexes);
    StoreAlign<T2, Reg::DataCopyMode::DATA_BLOCK_COPY, Reg::PostLiteral::POST_MODE_UPDATE>(
        ((__ubuf__ T2 *&)expUb), vreg_exp_merge_f8e5m2, blockStride, repeatStride, preg_all_b8_128);
} else if constexpr (IsSameType<T2, fp8_e4m3fn_t>::value) {
    RegTensor<fp8_e4m3fn_t> vreg_exp_even_f8e4m3;
    RegTensor<fp8_e4m3fn_t> vreg_exp_odd_f8e4m3;
    RegTensor<fp8_e4m3fn_t> vreg_exp_merge_tmp_f8e4m3;
    RegTensor<fp8_e4m3fn_t> vreg_exp_merge_f8e4m3;
    RegTensor<uint8_t> vreg_exp_merge_f8e4m3_indexes;
    MaskReg preg_all_b8 = CreateMask<T2, MaskPattern::ALL>();
    uint32_t maskLen = 128;
    MaskReg preg_all_b8_128 = UpdateMask<T2>(maskLen);
    Cast<T2, T, castTraitRintZero>(vreg_exp_even_f8e4m3, vreg_exp_even, preg_all);
    Cast<T2, T, castTraitRintTwo>(vreg_exp_odd_f8e4m3, vreg_exp_odd, preg_all);
    Or((RegTensor<uint8_t>&)vreg_exp_merge_tmp_f8e4m3, (RegTensor<uint8_t>&)vreg_exp_even_f8e4m3, (RegTensor<uint8_t>&)vreg_exp_odd_f8e4m3, preg_all_b8);
    LoadAlign(vreg_exp_merge_f8e4m3_indexes, indexesUb);
    Gather(vreg_exp_merge_f8e4m3, vreg_exp_merge_tmp_f8e4m3, vreg_exp_merge_f8e4m3_indexes);
    StoreAlign<T2, Reg::DataCopyMode::DATA_BLOCK_COPY, Reg::PostLiteral::POST_MODE_UPDATE>(
        ((__ubuf__ T2 *&)expUb), vreg_exp_merge_f8e4m3, blockStride, repeatStride, preg_all_b8_128);
} else if constexpr (IsSameType<T2, hifloat8_t>::value) {
    RegTensor<hifloat8_t> vreg_exp_even_hif8;
    RegTensor<hifloat8_t> vreg_exp_odd_hif8;
    RegTensor<hifloat8_t> vreg_exp_merge_tmp_hif8;
    RegTensor<hifloat8_t> vreg_exp_merge_hif8;
    RegTensor<uint8_t> vreg_exp_merge_hif8_indexes;
    MaskReg preg_all_b8 = CreateMask<T2, MaskPattern::ALL>();
    uint32_t maskLen = 128;
    MaskReg preg_all_b8_128 = UpdateMask<T2>(maskLen);
    Cast<T2, T, castTraitZero>(vreg_exp_even_hif8, vreg_exp_even, preg_all);
    Cast<T2, T, castTraitTwo>(vreg_exp_odd_hif8, vreg_exp_odd, preg_all);
    Or((RegTensor<uint8_t>&)vreg_exp_merge_tmp_hif8, (RegTensor<uint8_t>&)vreg_exp_even_hif8, (RegTensor<uint8_t>&)vreg_exp_odd_hif8, preg_all_b8);
    LoadAlign(vreg_exp_merge_hif8_indexes, indexesUb);
    Gather(vreg_exp_merge_hif8, vreg_exp_merge_tmp_hif8, vreg_exp_merge_hif8_indexes);
    StoreAlign<T2, Reg::DataCopyMode::DATA_BLOCK_COPY, Reg::PostLiteral::POST_MODE_UPDATE>(
        ((__ubuf__ T2 *&)expUb), vreg_exp_merge_hif8, blockStride, repeatStride, preg_all_b8_128);
}
```

**要点**: 1) 三参 Gather，三种类型分支写法一致，索引来自 LoadAlign；2) castTrait 按类型选择（RintZero/RintTwo 或 Zero/Two）；3) UpdateMask(128) 控制 b8 有效长度。


### Gather 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| swiglu_backward_mx_quant_with_dual_axis | Add, Adds, And, Arange, Cast | 按 Arange 生成的连续/步长索引从 scale 寄存器收集元素并搬运到 UB | __VEC_SCOPE__ |
| quant_sparse_flash_mla | Add, Cast, CreateMask, DataCopyMode, Duplicate | 按从 UB 加载的索引表对 Or 合并后的 exp 寄存器重排 | __simd_vf__ |
| lightning_indexer | AR, Arange, ClearSpr, Compare, CreateMask | 带 maskReg 按计算的桶号从直方图 UB 收集历史值 | __simd_vf__ |
| quant_lightning_indexer_v2 | AR, Arange, ClearSpr, Compare, CreateMask | 按计算的桶号从直方图 UB 收集历史值并 Select 处理边界 | __simd_vf__ |
| stem_indexer | AR, Arange, ClearSpr, Compare, CreateMask | 按计算的桶号从直方图 UB 收集历史值 | __simd_vf__ |
| quant_sparse_flash_mla | Cast, CreateMask, DataCopyMode, DeInterleave, ExpSub | 按从 UB 加载的索引对 exp 寄存器重排（64 VF 块） | __simd_vf__ |
| dynamic_block_mx_quant | And, Cast, Compare, CreateMask, Duplicate | 按从 UB 加载的索引收集 Pack 后的 b8 scale | __VEC_SCOPE__ |
| common | Cast, CreateMask, DataCopyMode, Duplicate | 按前缀和索引重排 scale 后与权重相乘反量化 | __simd_vf__ |
| mhc_sinkhorn_backward | And, CreateMask, DataCopy, DataCopyGather, DataCopyScatter | 按广播索引展开归约结果后做归一化 | __VEC_SCOPE__ |
| lightning_indexer | Cast, CastTrait, CreateMask, Duplicate | 按循环索引广播权重后乘累加 | __aicore__ |
| common | CastTrait, DataCopyMode, HighLowPart, LoadAlign | 按从 UB 加载的索引对合并后的 fp8/hifloat8 exp 重排 | __simd_vf__ |
| lightning_indexer | Add, Adds, Compares, CreateMask | 带 mask 按当前索引从历史索引 UB 收集并叠加偏移 | __simd_vf__ |
| lightning_indexer_v2 | CreateMask, Duplicate, LoadAlign, LoadDist | 按循环索引广播权重后乘累加 | __aicore__ |
| mhc_pre_backward | Cast, CreateMask, Duplicate, LoadAlign | 带 mask 按偏移索引广播 hPre 后与梯度相乘 | __VEC_SCOPE__ |
| quant_block_sparse_attn | DataCopyMode, LoadAlign, LoadDist, MaskDist | 按从 UB 加载的索引对合并后的多类型 exp 重排 | __simd_vf__ |
