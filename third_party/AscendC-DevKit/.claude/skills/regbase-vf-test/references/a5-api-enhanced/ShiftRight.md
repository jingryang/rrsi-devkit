# ShiftRight

**页面ID:** atlasascendc_api_07_0375  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0375.html

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

根据mask，对输入数据srcReg0按照srcReg1对应元素进行右移操作，将结果写入dstReg。

#### 函数原型

```
template <typename T = DefaultType, typename U = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S, typename V>
__simd_callee__ inline void ShiftRight(S& dstReg, S& srcReg0, V& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 源操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/uint64_t/int64_t |
| U | 右移参数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/int16_t/int32_t/int64_t 源操作数和目的操作数的数据类型约束参考表3。 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。- MERGING，当前不支持。 |
| S | srcReg0/dstReg的RegTensor类型， 例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写。 |
| V | srcReg1的RegTensor类型， 例如RegTensor<int32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 不支持设置为负数。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

**表3 **源操作数和目的操作数的数据类型约束

| srcReg0/dstReg数据类型 | srcReg1数据类型 |
| --- | --- |
| uint8_t | int8_t |
| uint16_t | int16_t |
| uint32_t | int32_t |
| uint64_t | int64_t |
| int8_t | int8_t |
| int16_t | int16_t |
| int32_t | int32_t |
| int64_t | int64_t |

#### 约束说明

- 对于逻辑位移（无符号数据类型），如果位移量大于数据类型位宽，则输出为0。
- 对于算术位移（有符号数据类型），如果srcReg0小于0，srcReg1大于0，并且位移量大于数据类型位宽，则输出-1；如果srcReg0大于0，并且位移量大于数据类型位宽，则输出0。

#### 调用示例

```
template<typename T, typename U>
__simd_vf__ inline void ShiftRightVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ U* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<U> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);       
        AscendC::Reg::ShiftRight(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 ShiftRight 实例

### 实例 1：right_shift::RightShiftCustom16

- **来源类型**: `__aicore__`
- **共现 API**: Compare, CreateMask, DataCopy, Duplicate, MaskPattern, MaskReg, RegTensor, RegTraitNumOne, Select, UpdateMask
- **ShiftRight 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: right_shift 算子 int16/uint16 版本：循环内用 UpdateMask 生成 mask，加载 xReg/yReg 后先用 Compare+Select 把移位量钳制到合法范围，再调用 ShiftRight 按 mask 做右移。

（行 112-127）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    Reg::DataCopy(xReg, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));
    Reg::DataCopy(yReg, (__ubuf__ T*)(src2Addr + loopIdx * vlSize));

    if constexpr (std::is_same_v<T, int16_t>) {
        Reg::Compare<T, CMPMODE::GE>(calcMask, yReg, zeroReg, mask);
        Reg::Select(yReg, yReg, zeroReg, calcMask);
        Reg::ShiftRight(zReg, xReg, (Reg::RegTensor<T>&)yReg, mask);
    } else if constexpr (std::is_same_v<T, uint16_t>) {
        Reg::Compare<T, CMPMODE::LE>(calcMask, yReg, sizeReg, mask);
        Reg::Select(yReg, yReg, sizeReg, calcMask);
        Reg::ShiftRight(zReg, xReg, (Reg::RegTensor<int16_t>&)yReg, mask);
    }
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), zReg, mask);
}
```

**要点**:
- srcReg1（移位量）不支持负数，需用 Compare(GE,yReg,zeroReg)+Select 将负值置 0。
- 无符号位移量超过位宽时结果为 0，故用 Compare(LE,yReg,sizeReg)+Select 钳位到 sizeReg。
- 第 4 参数 mask 控制 per-element 有效性，未选中元素在 dst 中置零（ZEROING 模式）。

### 实例 2：right_shift::RightShiftCustom32

- **来源类型**: `__aicore__`
- **共现 API**: Compare, CreateMask, DataCopy, Duplicate, MaskPattern, MaskReg, RegTensor, RegTraitNumOne, Select, UpdateMask
- **ShiftRight 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: right_shift 算子 int32/uint32 版本：与 16 位版本同构，按 mask 右移前用 Compare+Select 钳制移位量，并用 (RegTensor<int32_t>&) 强转 srcReg1 满足表3 类型约束。

（行 166-181）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    Reg::DataCopy(xReg, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));
    Reg::DataCopy(yReg, (__ubuf__ T*)(src2Addr + loopIdx * vlSize));

    if constexpr (std::is_same_v<T, int32_t>) {
        Reg::Compare<T, CMPMODE::GE>(calcMask, yReg, zeroReg, mask);
        Reg::Select(yReg, yReg, zeroReg, calcMask);
        Reg::ShiftRight(zReg, xReg, (Reg::RegTensor<T>&)yReg, mask);
    } else if constexpr (std::is_same_v<T, uint32_t>) {
        Reg::Compare<T, CMPMODE::LE>(calcMask, yReg, sizeReg, mask);
        Reg::Select(yReg, yReg, sizeReg, calcMask);
        Reg::ShiftRight(zReg, xReg, (Reg::RegTensor<int32_t>&)yReg, mask);
    }
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), zReg, mask);
}
```

**要点**:
- 钳位策略同 16 位版本，针对 32 位数据类型。
- srcReg1 类型受表3 约束（uint32_t 配 int32_t），用 (RegTensor<int32_t>&) 强转。
- 算术位移超位宽输出 -1，逻辑位移超位宽输出 0。

### 实例 3：right_shift::RightShiftCustom64

- **来源类型**: `__aicore__`
- **共现 API**: Compare, CreateMask, DataCopy, Duplicate, MaskPattern, MaskReg, RegTensor, RegTraitNumOne, Select, UpdateMask
- **ShiftRight 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: right_shift 算子 int64/uint64 版本：按 mask 右移前用 Compare+Select 钳制移位量，(RegTensor<int64_t>&) 强转 srcReg1 满足表3 类型约束。

（行 220-235）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    Reg::DataCopy(xReg, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));
    Reg::DataCopy(yReg, (__ubuf__ T*)(src2Addr + loopIdx * vlSize));

    if constexpr (std::is_same_v<T, int64_t>) {
        Reg::Compare<T, CMPMODE::GE>(calcMask, yReg, zeroReg, mask);
        Reg::Select(yReg, yReg, zeroReg, calcMask);
        Reg::ShiftRight(zReg, xReg, (Reg::RegTensor<T>&)yReg, mask);
    } else if constexpr (std::is_same_v<T, uint64_t>) {
        Reg::Compare<T, CMPMODE::LE>(calcMask, yReg, sizeReg, mask);
        Reg::Select(yReg, yReg, sizeReg, calcMask);
        Reg::ShiftRight(zReg, xReg, (Reg::RegTensor<int64_t>&)yReg, mask);
    }
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), zReg, mask);
}
```

**要点**:
- 64 位数据的算术/逻辑右移，钳位策略同前。
- 移位量超位宽时：算术位移且 srcReg0<0 输出 -1，逻辑位移输出 0。
- (RegTensor<int64_t>&) 强转满足表3 类型约束。

### 实例 4：right_shift::RightShiftCustom8

- **来源类型**: `__aicore__`
- **共现 API**: Compare, CreateMask, DataCopy, Duplicate, MaskPattern, MaskReg, RegTensor, RegTraitNumOne, Select, UpdateMask
- **ShiftRight 调用次数**: 4
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: right_shift 算子 int8/uint8 版本：按 mask 右移前用 Compare+Select 钳制移位量，(RegTensor<int8_t>&) 强转 srcReg1 满足表3 类型约束。

（行 58-73）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    Reg::DataCopy(xReg, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));
    Reg::DataCopy(yReg, (__ubuf__ T*)(src2Addr + loopIdx * vlSize));

    if constexpr (std::is_same_v<T, int8_t>) {
        Reg::Compare<T, CMPMODE::GE>(calcMask, yReg, zeroReg, mask);
        Reg::Select(yReg, yReg, zeroReg, calcMask);
        Reg::ShiftRight(zReg, xReg, (Reg::RegTensor<T>&)yReg, mask);
    } else if constexpr (std::is_same_v<T, uint8_t>) {
        Reg::Compare<T, CMPMODE::LE>(calcMask, yReg, sizeReg, mask);
        Reg::Select(yReg, yReg, sizeReg, calcMask);
        Reg::ShiftRight(zReg, xReg, (Reg::RegTensor<int8_t>&)yReg, mask);
    }
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), zReg, mask);
}
```

**要点**:
- 8 位数据位宽最小，移位量极易超限，钳位尤其关键。
- srcReg1 用 int8_t（按表3），(RegTensor<int8_t>&) 强转。
- 钳位策略与其它位宽版本一致，体现模板多态分发。

### 实例 5：bucketize_v2::BinaryQueryVF

- **来源类型**: `__simd_vf__`
- **共现 API**: Add, Adds, Compare, Duplicate, MaskNot, MaskReg, RegTensor, Select, Sub, UpdateMask
- **ShiftRight 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: bucketize_v2 二分查找中用 ShiftRight 把区间差值右移 1 位求中点索引，配合 Sub/Add/Compare/Select 收缩左右边界完成单次迭代。

（行 150-165）

```cpp
for (uint16_t j = 0; j < maxIter; j++) {
    Reg::Compare<INDICES_T, CMPMODE::NE>(pReg, leftReg, rightReg, pReg);
    Reg::Sub(subReg, rightReg, leftReg, pReg);
    Reg::ShiftRight(tmpReg, subReg, shiftReg, pReg);
    Reg::Add(midIndicesReg, leftReg, tmpReg, pReg);
    LoadMidValue<B_T, RegT, Reg::RegTensor<INDICES_T>>(midValueReg, boundPtr, midIndicesReg, pReg);
    if constexpr (RIGHT) {
        Reg::Compare<COMPUTE_T, CMPMODE::GT>(cmpMaskReg, midValueReg, xReg, pReg);
    } else {
        Reg::Compare<COMPUTE_T, CMPMODE::GE>(cmpMaskReg, midValueReg, xReg, pReg);
    }
    Reg::MaskNot(cmpMaskReg, cmpMaskReg, pReg);
    Reg::Adds(midOneReg, midIndicesReg, 1, pReg);
    Reg::Select(leftReg, midOneReg, leftReg, cmpMaskReg);
    Reg::Select(rightReg, rightReg, midIndicesReg, cmpMaskReg);
}
```

**要点**:
- 第 4 参数 pReg 为全有效 MaskReg，等价无 mask 过滤，全元素参与。
- ShiftRight 用于除以 2 的整数运算，是二分查找中点计算的经典用法。
- 与 Sub 求差、Add 加左边界、Compare+Select 收缩边界组合完成单次迭代。

### 实例 6：scatter_nd_add::IndexStatisticInt32Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 5
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: scatter_nd_add 索引排序中用 ShiftRight 把 uint32 索引右移 lastDimShiftAmount 位以分离维度，配合 Xor/Muls/Histograms 做 FNV-32 哈希分桶。

**片段 1** (行 50-86):

```cpp
for (uint16_t i = 0; i < mainLoop; i++) {
    RegTensor<uint32_t> vectorIndex0, vectorIndex1, vectorIndex2, vectorIndex3;
    RegTensor<uint16_t> vectorB16Tmp0, vectorB16Tmp1, vectorB16Tmp2, vectorB16Tmp3;
    RegTensor<uint8_t> vectorB8Hash0, vectorB8Hash1;

    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex1, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex2, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex3, srcM, 64);

    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex1, vectorIndex1, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex2, vectorIndex2, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex3, vectorIndex3, lastDimShiftAmount, patAllB32);

    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Xor(vectorIndex1, vectorIndex1, xorOffset, patAllB32);
    Xor(vectorIndex2, vectorIndex2, xorOffset, patAllB32);
    Xor(vectorIndex3, vectorIndex3, xorOffset, patAllB32);

    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex1, vectorIndex1, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex2, vectorIndex2, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex3, vectorIndex3, FNV_PRIME_B32, patAllB32);

    DeInterleave(vectorB16Tmp0, vectorB16Tmp1, (RegTensor<uint16_t>&)vectorIndex0,
                 (RegTensor<uint16_t>&)vectorIndex1);
    DeInterleave(vectorB16Tmp2, vectorB16Tmp3, (RegTensor<uint16_t>&)vectorIndex2,
                 (RegTensor<uint16_t>&)vectorIndex3);
    DeInterleave(vectorB8Hash0, vectorB8Hash1, (RegTensor<uint8_t>&)vectorB16Tmp0,
                 (RegTensor<uint8_t>&)vectorB16Tmp2);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(histVector0, vectorB8Hash0,
                                                                                      patAllB8);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(histVector1, vectorB8Hash0,
                                                                                      patAllB8);
}
```

**片段 2** (行 88-100):

```cpp
for (uint16_t i = 0; i < tailLoop; i++) {
    MaskReg maskReg = UpdateMask<uint32_t>(tailNum);
    RegTensor<uint32_t> vectorIndex0;
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
}
```

**要点**:
- patAllB32 为全有效 32 位 mask pattern，等价无元素过滤，4 路并行处理 vectorIndex0-3。
- ShiftRight 用于位域提取（按位移分离多维索引的维度分量）。
- 尾块片段用 UpdateMask<uint32_t>(tailNum) 生成 maskReg 处理非整块元素。

### 实例 7：scatter_update::IndexStatisticInt32Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 5
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: scatter_update 索引排序中的 ShiftRight 维度分离 + FNV-32 哈希，复用同一 IndexStatisticInt32Vf 工具函数。

**片段 1** (行 52-88):

```cpp
for (uint16_t i = 0; i < mainLoop; i++) {
    RegTensor<uint32_t> vectorIndex0, vectorIndex1, vectorIndex2, vectorIndex3;
    RegTensor<uint16_t> vectorB16Tmp0, vectorB16Tmp1, vectorB16Tmp2, vectorB16Tmp3;
    RegTensor<uint8_t> vectorB8Hash0, vectorB8Hash1;

    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex1, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex2, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex3, srcM, 64);

    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex1, vectorIndex1, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex2, vectorIndex2, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex3, vectorIndex3, lastDimShiftAmount, patAllB32);

    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Xor(vectorIndex1, vectorIndex1, xorOffset, patAllB32);
    Xor(vectorIndex2, vectorIndex2, xorOffset, patAllB32);
    Xor(vectorIndex3, vectorIndex3, xorOffset, patAllB32);

    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex1, vectorIndex1, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex2, vectorIndex2, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex3, vectorIndex3, FNV_PRIME_B32, patAllB32);

    DeInterleave(vectorB16Tmp0, vectorB16Tmp1, (RegTensor<uint16_t>&)vectorIndex0,
                 (RegTensor<uint16_t>&)vectorIndex1);
    DeInterleave(vectorB16Tmp2, vectorB16Tmp3, (RegTensor<uint16_t>&)vectorIndex2,
                 (RegTensor<uint16_t>&)vectorIndex3);
    DeInterleave(vectorB8Hash0, vectorB8Hash1, (RegTensor<uint8_t>&)vectorB16Tmp0,
                 (RegTensor<uint8_t>&)vectorB16Tmp2);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(histVector0, vectorB8Hash0,
                                                                                      patAllB8);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(histVector1, vectorB8Hash0,
                                                                                      patAllB8);
}
```

**片段 2** (行 90-102):

```cpp
for (uint16_t i = 0; i < tailLoop; i++) {
    MaskReg maskReg = UpdateMask<uint32_t>(tailNum);
    RegTensor<uint32_t> vectorIndex0;
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
}
```

**要点**:
- 调用模式与实例 6 完全一致，仅算子宿主不同（scatter_update）。
- 体现 indices_sort_utils 工具函数跨 scatter 类算子的复用。

### 实例 8：scatter_nd_update::IndexStatisticInt32Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 5
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: scatter_nd_update 索引排序中的 ShiftRight 维度分离 + FNV-32 哈希，复用 IndexStatisticInt32Vf 工具函数。

**片段 1** (行 52-88):

```cpp
for (uint16_t i = 0; i < mainLoop; i++) {
    RegTensor<uint32_t> vectorIndex0, vectorIndex1, vectorIndex2, vectorIndex3;
    RegTensor<uint16_t> vectorB16Tmp0, vectorB16Tmp1, vectorB16Tmp2, vectorB16Tmp3;
    RegTensor<uint8_t> vectorB8Hash0, vectorB8Hash1;

    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex1, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex2, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex3, srcM, 64);

    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex1, vectorIndex1, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex2, vectorIndex2, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex3, vectorIndex3, lastDimShiftAmount, patAllB32);

    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Xor(vectorIndex1, vectorIndex1, xorOffset, patAllB32);
    Xor(vectorIndex2, vectorIndex2, xorOffset, patAllB32);
    Xor(vectorIndex3, vectorIndex3, xorOffset, patAllB32);

    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex1, vectorIndex1, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex2, vectorIndex2, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex3, vectorIndex3, FNV_PRIME_B32, patAllB32);

    DeInterleave(vectorB16Tmp0, vectorB16Tmp1, (RegTensor<uint16_t>&)vectorIndex0,
                 (RegTensor<uint16_t>&)vectorIndex1);
    DeInterleave(vectorB16Tmp2, vectorB16Tmp3, (RegTensor<uint16_t>&)vectorIndex2,
                 (RegTensor<uint16_t>&)vectorIndex3);
    DeInterleave(vectorB8Hash0, vectorB8Hash1, (RegTensor<uint8_t>&)vectorB16Tmp0,
                 (RegTensor<uint8_t>&)vectorB16Tmp2);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(histVector0, vectorB8Hash0,
                                                                                      patAllB8);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(histVector1, vectorB8Hash0,
                                                                                      patAllB8);
}
```

**片段 2** (行 90-102):

```cpp
for (uint16_t i = 0; i < tailLoop; i++) {
    MaskReg maskReg = UpdateMask<uint32_t>(tailNum);
    RegTensor<uint32_t> vectorIndex0;
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
}
```

**要点**:
- 调用模式同实例 6，算子宿主为 scatter_nd_update。
- 同一工具函数跨算子复用，ShiftRight 用法稳定一致。

### 实例 9：scatter_nd_common::IndexStatisticInt32VF

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 5
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: scatter_nd_common 索引排序中的 ShiftRight 维度分离 + FNV-32 哈希，复用 IndexStatisticInt32VF 工具函数。

**片段 1** (行 51-87):

```cpp
for (uint16_t i = 0; i < mainLoop; i++) {
    RegTensor<uint32_t> vectorIndex0, vectorIndex1, vectorIndex2, vectorIndex3;
    RegTensor<uint16_t> vectorB16Tmp0, vectorB16Tmp1, vectorB16Tmp2, vectorB16Tmp3;
    RegTensor<uint8_t> vectorB8Hash0, vectorB8Hash1;

    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex1, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex2, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex3, srcM, 64);

    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex1, vectorIndex1, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex2, vectorIndex2, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex3, vectorIndex3, lastDimShiftAmount, patAllB32);

    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Xor(vectorIndex1, vectorIndex1, xorOffset, patAllB32);
    Xor(vectorIndex2, vectorIndex2, xorOffset, patAllB32);
    Xor(vectorIndex3, vectorIndex3, xorOffset, patAllB32);

    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex1, vectorIndex1, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex2, vectorIndex2, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex3, vectorIndex3, FNV_PRIME_B32, patAllB32);

    DeInterleave(vectorB16Tmp0, vectorB16Tmp1, (RegTensor<uint16_t>&)vectorIndex0,
                 (RegTensor<uint16_t>&)vectorIndex1);
    DeInterleave(vectorB16Tmp2, vectorB16Tmp3, (RegTensor<uint16_t>&)vectorIndex2,
                 (RegTensor<uint16_t>&)vectorIndex3);
    DeInterleave(vectorB8Hash0, vectorB8Hash1, (RegTensor<uint8_t>&)vectorB16Tmp0,
                 (RegTensor<uint8_t>&)vectorB16Tmp2);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(histVector0, vectorB8Hash0,
                                                                                      patAllB8);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(histVector1, vectorB8Hash0,
                                                                                      patAllB8);
}
```

**片段 2** (行 89-101):

```cpp
for (uint16_t i = 0; i < tailLoop; i++) {
    MaskReg maskReg = UpdateMask<uint32_t>(tailNum);
    RegTensor<uint32_t> vectorIndex0;
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
}
```

**要点**:
- 调用模式同实例 6，算子宿主为 scatter_nd_common。
- 函数名 IndexStatisticInt32VF（大写 VF）与其它算子的 Int32Vf 为同一模板实例化。

### 实例 10：inplace_index_add::IndexStatisticInt32Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 5
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: inplace_index_add 索引排序中的 ShiftRight 维度分离 + FNV-32 哈希，复用 IndexStatisticInt32Vf 工具函数。

**片段 1** (行 50-86):

```cpp
for (uint16_t i = 0; i < mainLoop; i++) {
    RegTensor<uint32_t> vectorIndex0, vectorIndex1, vectorIndex2, vectorIndex3;
    RegTensor<uint16_t> vectorB16Tmp0, vectorB16Tmp1, vectorB16Tmp2, vectorB16Tmp3;
    RegTensor<uint8_t> vectorB8Hash0, vectorB8Hash1;

    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex1, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex2, srcM, 64);
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex3, srcM, 64);

    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex1, vectorIndex1, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex2, vectorIndex2, lastDimShiftAmount, patAllB32);
    ShiftRight(vectorIndex3, vectorIndex3, lastDimShiftAmount, patAllB32);

    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Xor(vectorIndex1, vectorIndex1, xorOffset, patAllB32);
    Xor(vectorIndex2, vectorIndex2, xorOffset, patAllB32);
    Xor(vectorIndex3, vectorIndex3, xorOffset, patAllB32);

    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex1, vectorIndex1, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex2, vectorIndex2, FNV_PRIME_B32, patAllB32);
    Muls(vectorIndex3, vectorIndex3, FNV_PRIME_B32, patAllB32);

    DeInterleave(vectorB16Tmp0, vectorB16Tmp1, (RegTensor<uint16_t>&)vectorIndex0,
                 (RegTensor<uint16_t>&)vectorIndex1);
    DeInterleave(vectorB16Tmp2, vectorB16Tmp3, (RegTensor<uint16_t>&)vectorIndex2,
                 (RegTensor<uint16_t>&)vectorIndex3);
    DeInterleave(vectorB8Hash0, vectorB8Hash1, (RegTensor<uint8_t>&)vectorB16Tmp0,
                 (RegTensor<uint8_t>&)vectorB16Tmp2);

    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(histVector0, vectorB8Hash0,
                                                                                      patAllB8);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(histVector1, vectorB8Hash0,
                                                                                      patAllB8);
}
```

**片段 2** (行 88-100):

```cpp
for (uint16_t i = 0; i < tailLoop; i++) {
    MaskReg maskReg = UpdateMask<uint32_t>(tailNum);
    RegTensor<uint32_t> vectorIndex0;
    DataCopy<uint32_t, PostLiteral::POST_MODE_UPDATE, LoadDist::DIST_NORM>(vectorIndex0, srcM, 64);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, patAllB32);
    Xor(vectorIndex0, vectorIndex0, xorOffset, patAllB32);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B32, patAllB32);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
}
```

**要点**:
- 调用模式同实例 6，算子宿主为 inplace_index_add。
- 同一工具函数跨算子复用。

### 实例 11：scatter_nd_common::IndexStatisticInt64VF

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: mask, maskReg）
- **语义**: scatter_nd_common 的 int64 索引排序中用 ShiftRight 分离维度，配合 Xor/Muls 做 FNV-64 哈希，maskReg 处理尾块。

（行 157-169）

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    MaskReg maskReg = UpdateMask<uint64_t>(dataLen);
    DataCopy(vectorIndex0, srcM);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, maskReg);
    Xor(vectorIndex0, vectorIndex0, xorOffset, maskReg);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B64, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Max(maxValue, histVector0, histVector1, patAllB16);
}
```

**要点**:
- 第 4 参数 maskReg 由 UpdateMask<uint64_t>(dataLen) 生成，处理尾块非整块元素。
- FNV_PRIME_B64 对应 64 位哈希常量，单路处理（对比 int32 版本的 4 路）。
- ShiftRight 用法为位域提取，与 int32 版本一致但数据宽度不同。

### 实例 12：scatter_nd_add::IndexStatisticInt64Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: mask, maskReg）
- **语义**: scatter_nd_add 的 int64 索引排序 ShiftRight 维度分离 + FNV-64 哈希，带 maskReg 尾块处理。

（行 129-141）

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    MaskReg maskReg = UpdateMask<uint64_t>(dataLen);
    DataCopy(vectorIndex0, srcM);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, maskReg);
    Xor(vectorIndex0, vectorIndex0, xorOffset, maskReg);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B64, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Max(maxValue, histVector0, histVector1, patAllB16);
}
```

**要点**:
- 调用模式同实例 11，算子宿主为 scatter_nd_add。
- 复用 IndexStatisticInt64Vf 工具函数，maskReg 处理尾块。

### 实例 13：inplace_index_add::IndexStatisticInt64Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: mask, maskReg）
- **语义**: inplace_index_add 的 int64 索引排序 ShiftRight 维度分离 + FNV-64 哈希，带 maskReg 尾块处理。

（行 155-167）

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    MaskReg maskReg = UpdateMask<uint64_t>(dataLen);
    DataCopy(vectorIndex0, srcM);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, maskReg);
    Xor(vectorIndex0, vectorIndex0, xorOffset, maskReg);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B64, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Max(maxValue, histVector0, histVector1, patAllB16);
}
```

**要点**:
- 调用模式同实例 11，算子宿主为 inplace_index_add。
- 复用 IndexStatisticInt64Vf 工具函数。

### 实例 14：scatter_update::IndexStatisticInt64Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: mask, maskReg）
- **语义**: scatter_update 的 int64 索引排序 ShiftRight 维度分离 + FNV-64 哈希，带 maskReg 尾块处理。

（行 130-142）

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    MaskReg maskReg = UpdateMask<uint64_t>(dataLen);
    DataCopy(vectorIndex0, srcM);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, maskReg);
    Xor(vectorIndex0, vectorIndex0, xorOffset, maskReg);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B64, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Max(maxValue, histVector0, histVector1, patAllB16);
}
```

**要点**:
- 调用模式同实例 11，算子宿主为 scatter_update。
- 复用 IndexStatisticInt64Vf 工具函数。

### 实例 15：scatter_nd_update::IndexStatisticInt64Vf

- **来源类型**: `__simd_vf__`
- **共现 API**: Xor
- **ShiftRight 调用次数**: 1
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask+maskReg`（实参 4 个，含 mask/mode: mask, maskReg）
- **语义**: scatter_nd_update 的 int64 索引排序 ShiftRight 维度分离 + FNV-64 哈希，带 maskReg 尾块处理。

（行 131-143）

```cpp
for (uint16_t i = 0; i < loopSize; i++) {
    MaskReg maskReg = UpdateMask<uint64_t>(dataLen);
    DataCopy(vectorIndex0, srcM);
    ShiftRight(vectorIndex0, vectorIndex0, lastDimShiftAmount, maskReg);
    Xor(vectorIndex0, vectorIndex0, xorOffset, maskReg);
    Muls(vectorIndex0, vectorIndex0, FNV_PRIME_B64, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN0, HistogramsType::FREQUENCY>(
        histVector0, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Histograms<uint8_t, uint16_t, HistogramsBinType::BIN1, HistogramsType::FREQUENCY>(
        histVector1, (RegTensor<uint8_t>&)vectorIndex0, maskReg);
    Max(maxValue, histVector0, histVector1, patAllB16);
}
```

**要点**:
- 调用模式同实例 11，算子宿主为 scatter_nd_update。
- 复用 IndexStatisticInt64Vf 工具函数。

### ShiftRight 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| right_shift | Compare, CreateMask, DataCopy, Duplicate, MaskPattern | mask 右移 + 移位量钳制（int16/uint16） | __aicore__ |
| right_shift | Compare, CreateMask, DataCopy, Duplicate, MaskPattern | mask 右移 + 移位量钳制（int32/uint32） | __aicore__ |
| right_shift | Compare, CreateMask, DataCopy, Duplicate, MaskPattern | mask 右移 + 移位量钳制（int64/uint64） | __aicore__ |
| right_shift | Compare, CreateMask, DataCopy, Duplicate, MaskPattern | mask 右移 + 移位量钳制（int8/uint8） | __aicore__ |
| bucketize_v2 | Add, Adds, Compare, Duplicate, MaskNot | 二分查找右移 1 位求中点（pReg 全有效） | __simd_vf__ |
| scatter_nd_add | Xor | 维度分离右移 + FNV-32 哈希（patAllB32 全有效，4 路） | __simd_vf__ |
| scatter_update | Xor | 维度分离右移 + FNV-32 哈希（patAllB32，4 路） | __simd_vf__ |
| scatter_nd_update | Xor | 维度分离右移 + FNV-32 哈希（patAllB32，4 路） | __simd_vf__ |
| scatter_nd_common | Xor | 维度分离右移 + FNV-32 哈希（patAllB32，4 路） | __simd_vf__ |
| inplace_index_add | Xor | 维度分离右移 + FNV-32 哈希（patAllB32，4 路） | __simd_vf__ |
| scatter_nd_common | Xor | 维度分离右移 + FNV-64 哈希（maskReg 尾块，单路） | __simd_vf__ |
| scatter_nd_add | Xor | 维度分离右移 + FNV-64 哈希（maskReg 尾块，单路） | __simd_vf__ |
| inplace_index_add | Xor | 维度分离右移 + FNV-64 哈希（maskReg 尾块，单路） | __simd_vf__ |
| scatter_update | Xor | 维度分离右移 + FNV-64 哈希（maskReg 尾块，单路） | __simd_vf__ |
| scatter_nd_update | Xor | 维度分离右移 + FNV-64 哈希（maskReg 尾块，单路） | __simd_vf__ |

