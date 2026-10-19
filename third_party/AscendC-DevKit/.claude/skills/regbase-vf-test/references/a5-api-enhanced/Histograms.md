# Histograms

**页面ID:** atlasascendc_api_07_0425  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0425.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品            AI Core | x |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

对直方图数据进行统计，在目的操作数dstReg的基础数据上加上源操作数srcReg数据的统计结果，包括数据的频率统计和累计统计。

- 频率统计

如下图所示，在低位模式下，dstReg（即 dst0）用于统计srcReg中[0-127]范围内（前半部分）各个值的出现频率；而在高位模式下，dstReg（即dst1）则统计[128-255]范围内（后半部分）的频率。dst0和dst1中的第n位（bit）表示srcReg中数值n的出现次数，并在原始dstReg数据的基础上进行累加。

**图1 **频率统计
![](images/atlasascendc_api_07_0425_img_001.png)
- 累计统计

如下图所示，在低位模式下，目的寄存器dstReg（即dst0）会统计源寄存器srcReg中值落在低位区间[0-127]的数据分布情况；在高位模式下，目的寄存器dstReg（即dst1）则会统计srcReg中值落在高位区间[128-255]的数据分布情况。在dst0 和dst1中，第n位的数据表示srcReg中从0到n的所有数值在对应区间中出现的总频率。最终，统计结果会在目的寄存器原始数据的基础上进行累加。

**图2 **累计统计
![](images/atlasascendc_api_07_0425_img_002.png)

#### 函数原型

```
template <typename T = DefaultType, typename U = DefaultType, HistogramsBinType mode, HistogramsType type, typename S, typename V>
__simd_callee__ inline void Histograms(V& dstReg, S& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 源操作数的数据类型。          Atlas 350 加速卡，支持的数据类型为：uint8_t |
| U | 目的操作数的数据类型。          Atlas 350 加速卡，支持的数据类型为：uint16_t |
| mode | HistogramsBinType枚举类型，用于控制统计src的低位区间[0-127]（前半部分）或高位区间[128-255]（后半部分）的数据。VL长度为256Byte，dst数据类型为uint16_t，一个dst可以存储128个数据，因此需要两个dst。                     - BIN0表示低位模式，统计src中[0-127]范围内的数据写入dst0。           - BIN1表示高位模式，统计src中[128-255]范围内的数据写入dst1。 |
| type | HistogramsType 枚举类型，表示统计模式。                       - FREQUENCY：频率统计模式，统计src中[0, 255]每个数的数量。每个dst有128个元素，其中dst0中每个元素对应src中[0, 127]每个元素的累加个数，dst1中每个元素对应src中[128,255]每个元素的累加个数。            - ACCUMULATE：累计统计模式，统计src中x<=0、x<=1、x<=2、x<=3......x<=254、x<=255每个区间的元素个数。每个dst有128个元素，其中dst0中每个元素对应src中[0, 127]每个元素区间累加个数，dst1中每个元素对应src中[128，255]每个元素区间累加个数。 |
| S | 目的操作数RegTensor类型，由编译器自动推导，用户不需要填写。 |
| V | 源操作数RegTensor类型，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。          类型为RegTensor。 |
| srcReg | 输入 | 源操作数。          类型为RegTensor。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template <typename T, typename U>
__simd_vf__ inline void HistogramsVF(__ubuf__ U* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize, uint16_t repeatTimes, AscendC::Reg::HistogramsBinType mode, AscendC::Reg::HistogramsType type)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<U> dstReg;
    AscendC::Reg::MaskReg mask0 = AscendC::Reg::CreateMask<T>();
    AscendC::Reg::MaskReg mask1 = AscendC::Reg::CreateMask<T>();
    for (uint16_t i = 0; i < repeatTimes; ++i){
        AscendC::Reg::LoadAlign(srcReg, srcAddr + oneRepeatSize * i);
        AscendC::Reg::Histograms<T, U, mode, type>(dstReg, srcReg, mask0);
        AscendC::Reg::StoreAlign(dstAddr, dstReg, mask1);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Histograms 实例

### 实例 1：top_k_v2::GetCumSum

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, DeInterleave, Duplicate, HistogramsBinType, HistogramsType, MaskAnd, MaskPack, MaskReg, MaskSel, PostLiteral, RegTensor, ShiftRights, UpdateMask
- **Histograms 调用次数**: 2
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKmask`（实参 3 个，含 mask/mode: mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: 在 top_k_v2 的 GetCumSum 中，将 64 位输入右移并经三级 DeInterleave 压成 8 位基数字节，用 ACCUMULATE 累计模式对 BIN0/BIN1 双区间构建前缀和（cumsum），供基数排序排位使用。

（行 66-108）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg histMask = Reg::UpdateMask<uint64_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, ONE_TIMES_B64_NUM);
    // get high bit value
    Reg::RegTensor<uint64_t> andValueZero;
    Reg::And(andValueZero, inputVectorOne, andMaskVector, histMask);
    // get same value
    Reg::MaskReg cmpValueMask;
    Reg::CompareScalar<uint64_t, CMPMODE::EQ>(cmpValueMask, andValueZero, involvedDataMask, histMask);
    // update mask for next step calc
    Reg::MaskReg newHistMask;
    Reg::MaskAnd(newHistMask, cmpValueMask, histMask, predicateDefaultB64);
    // is first round
    Reg::MaskReg finalMask, firstRoundMask;
    Reg::CompareScalar<uint64_t, CMPMODE::EQ>(firstRoundMask, firstRoundVector, newRound, histMask);
    // mask sel
    Reg::MaskSel(finalMask, histMask, newHistMask, firstRoundMask);
    // vshr
    Reg::RegTensor<uint64_t> shiftVecOne;
    Reg::ShiftRights<uint64_t, int16_t>(shiftVecOne, inputVectorOne, bitOffset, finalMask);
    // get 256 8bit
    // get u64 low bit
    Reg::RegTensor<uint32_t> shiftVecU64LowBitOne, shiftVecU64HighBitOne;
    Reg::DeInterleave(shiftVecU64LowBitOne, shiftVecU64HighBitOne, (Reg::RegTensor<uint32_t> &)shiftVecOne, (Reg::RegTensor<uint32_t> &)zeroVectorU64);
    // get u32 low bit
    Reg::RegTensor<uint16_t> shiftVecU16LowBitOne, shiftVecU16HighBitOne;
    Reg::DeInterleave(shiftVecU16LowBitOne, shiftVecU16HighBitOne, (Reg::RegTensor<uint16_t> &)shiftVecU64LowBitOne, (Reg::RegTensor<uint16_t> &)zeroVectorU32);
    // get u16 low bit
    Reg::RegTensor<uint8_t> shiftVecU8LowBit, shiftVecU8HighBit;
    Reg::DeInterleave(shiftVecU8LowBit, shiftVecU8HighBit, (Reg::RegTensor<uint8_t> &)shiftVecU16LowBitOne, (Reg::RegTensor<uint8_t> &)zeroVectorU16);
    // copy u16 mask
    Reg::MaskReg maskU8, maskU16, maskU32;
    Reg::MaskPack(maskU32, finalMask);
    Reg::MaskPack(maskU16, maskU32);
    Reg::MaskPack(maskU8, maskU16);
    // get hist
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::ACCUMULATE>(chistVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::ACCUMULATE>(chistVectorOne, shiftVecU8LowBit, maskU8);
}
StoreCumsumToUB<int32_t, uint16_t>(blockCumSumPtr, chistVectorZero, chistVectorOne, zeroVectorU16);
```

**要点**:
- 同时调用 `BIN0` 和 `BIN1` 两次 `ACCUMULATE`，分别统计 [0-127] 与 [128-255] 区间累计分布，得到两个 128 元素 dst。
- 64 位数据需 `U64→U32→U16→U8` 三级 DeInterleave 才能压缩成 Histograms 要求的 `uint8_t` 源。
- mask 经 `MaskPack` 三级压缩以匹配 8 位源粒度。

### 实例 2：top_k_v2::GetCumSum

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, DeInterleave, Duplicate, HistogramsBinType, HistogramsType, MaskAnd, MaskPack, MaskReg, MaskSel, PostLiteral, RegTensor, ShiftRights, UpdateMask
- **Histograms 调用次数**: 2
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKmask`（实参 3 个，含 mask/mode: mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: 16 位输入版的 GetCumSum，右移后仅需一次 DeInterleave 即得 8 位基数，用 ACCUMULATE 模式构建 BIN0/BIN1 双区间累计直方图。

（行 60-93）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg histMask = Reg::UpdateMask<uint16_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, ONE_TIMES_B16_NUM);
    // get high bit value
    Reg::RegTensor<uint16_t> andValueZero;
    Reg::And(andValueZero, inputVectorOne, andMaskVector, histMask);
    // get same value
    Reg::MaskReg cmpValueMask;
    Reg::CompareScalar<uint16_t, CMPMODE::EQ>(cmpValueMask, andValueZero, involvedDataMask, histMask);
    // update mask for next step calc
    Reg::MaskReg newHistMask;
    Reg::MaskAnd(newHistMask, cmpValueMask, histMask, predicateDefaultB16);
    // is first round
    Reg::MaskReg finalMask, firstRoundMask;
    Reg::CompareScalar<uint16_t, CMPMODE::EQ>(firstRoundMask, firstRoundVector, round, histMask);
    // mask sel
    Reg::MaskSel(finalMask, histMask, newHistMask, firstRoundMask);
    // vshr
    Reg::RegTensor<uint16_t> shiftVecOne;
    Reg::ShiftRights<uint16_t, int16_t>(shiftVecOne, inputVectorOne, bitOffset, finalMask);
    // get 256 8bit
    Reg::RegTensor<uint8_t> shiftVecU8LowBit, shiftVecU8HighBit;
    Reg::DeInterleave(shiftVecU8LowBit, shiftVecU8HighBit, (Reg::RegTensor<uint8_t> &)shiftVecOne, (Reg::RegTensor<uint8_t> &)zeroVector);
    // copy u16 mask
    Reg::MaskReg maskU8;
    Reg::MaskPack(maskU8, finalMask);
    // get hist
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::ACCUMULATE>(chistVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::ACCUMULATE>(chistVectorOne, shiftVecU8LowBit, maskU8);
}
StoreCumsumToUB<int32_t, uint16_t>(blockCumSumPtr, chistVectorZero, chistVectorOne, zeroVector);
```

**要点**:
- b16 路径只需一级 DeInterleave（`U16→U8`），相比 b64 三级大幅简化。
- mask 只需一次 `MaskPack`（`U16→U8`），元素粒度直接对齐。
- 仍同时调用 `BIN0`+`BIN1` 两次 `ACCUMULATE`，覆盖完整 [0-255] 范围。

### 实例 3：top_k_v2::ReverseInputData

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, DataCopy, DeInterleave, Duplicate, HistogramsBinType, HistogramsType, Interleave, MaskPack, MaskReg, PostLiteral, RegTensor, ShiftRights, Sub, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKmask`（实参 3 个，含 mask/mode: mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: 在 ReverseInputData 中对 16 位输入做块内基数排序，先用 FREQUENCY 统计当前基数字节频率、再用 ACCUMULATE 构建累计分布，各调 BIN0/BIN1 共 4 次，用于推导各桶排位偏移。

（行 71-102）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg histMask = Reg::UpdateMask<uint16_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        inputVectorOne, inputXValuePtrCopy, ONE_TIMES_B16_NUM);
    // vshr
    Reg::RegTensor<uint16_t> shiftVecOne;
    Reg::ShiftRights<uint16_t, int16_t>(shiftVecOne, inputVectorOne, bitOffset, predicateDefaultB16);
    // 256 uint8 num
    // get 256 8bit
    Reg::RegTensor<uint8_t> shiftVecU8LowBit, shiftVecU8HighBit;
    Reg::DeInterleave(
        shiftVecU8LowBit, shiftVecU8HighBit, (Reg::RegTensor<uint8_t>&)shiftVecOne,
        (Reg::RegTensor<uint8_t>&)zeroVector);
    // copy u16 mask
    Reg::MaskReg maskU8;
    Reg::MaskPack(maskU8, histMask);
    // get hist
    Reg::Histograms<
        uint8_t, uint16_t, Reg::HistogramsBinType::BIN0, Reg::HistogramsType::FREQUENCY>(
        histVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<
        uint8_t, uint16_t, Reg::HistogramsBinType::BIN1, Reg::HistogramsType::FREQUENCY>(
        histVectorOne, shiftVecU8LowBit, maskU8);
    // get cusum
    Reg::Histograms<
        uint8_t, uint16_t, Reg::HistogramsBinType::BIN0, Reg::HistogramsType::ACCUMULATE>(
        chistVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<
        uint8_t, uint16_t, Reg::HistogramsBinType::BIN1, Reg::HistogramsType::ACCUMULATE>(
        chistVectorOne, shiftVecU8LowBit, maskU8);
}
```

**要点**:
- 典型"频率统计+累计统计"组合：`FREQUENCY` 得各值计数，`ACCUMULATE` 得前缀和，二者配合实现基数排序 scatter 偏移。
- 一次循环内 4 次 Histograms（`BIN0`/`BIN1` × `FREQUENCY`/`ACCUMULATE`）。
- 输入经 `ShiftRights` 取当前基数位后 DeInterleave 成 `uint8_t` 再送入 Histograms。

### 实例 4：top_k_v2::ReverseInputData

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, DataCopy, DeInterleave, Duplicate, HistogramsBinType, HistogramsType, Interleave, MaskPack, MaskReg, PostLiteral, RegTensor, ShiftRights, Sub, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKmask`（实参 3 个，含 mask/mode: mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: 64 位版 ReverseInputData，逻辑与 16 位版相同，但需三级 DeInterleave 与 MaskPack 压缩到 8 位基数，mask 链路更长；同样 4 次 Histograms 构建 freq+cumsum。

（行 81-114）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    Reg::MaskReg histMask = Reg::UpdateMask<uint64_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtrCopy, ONE_TIMES_B64_NUM);
    // vshr
    Reg::RegTensor<uint64_t> shiftVecOne;
    Reg::ShiftRights<uint64_t, int16_t>(shiftVecOne, inputVectorOne, bitOffset, predicateDefault);
    // get u64 low bit
    Reg::RegTensor<uint32_t> shiftVecU32LowBitOne, shiftVecU32HighBitOne;
    Reg::DeInterleave(shiftVecU32LowBitOne, shiftVecU32HighBitOne, (Reg::RegTensor<uint32_t> &)shiftVecOne, (Reg::RegTensor<uint32_t> &)zeroVectorU64);
    // get u32 low bit
    Reg::RegTensor<uint16_t> shiftVecU16LowBitOne, shiftVecU16HighBitOne;
    Reg::DeInterleave(shiftVecU16LowBitOne, shiftVecU16HighBitOne, (Reg::RegTensor<uint16_t> &)shiftVecU32LowBitOne, (Reg::RegTensor<uint16_t> &)zeroVectorU32);
    // get u16 low bit
    Reg::RegTensor<uint8_t> shiftVecU8LowBit, shiftVecU8HighBit;
    Reg::DeInterleave(shiftVecU8LowBit, shiftVecU8HighBit, (Reg::RegTensor<uint8_t> &)shiftVecU16LowBitOne, (Reg::RegTensor<uint8_t> &)zeroVector);
    // copy u32 mask
    Reg::MaskReg maskU8, maskU16, maskU32;
    Reg::MaskPack(maskU32, histMask);
    Reg::MaskPack(maskU16, maskU32);
    Reg::MaskPack(maskU8, maskU16);
    // get hist
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::FREQUENCY>(histVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::FREQUENCY>(histVectorOne, shiftVecU8LowBit, maskU8);
    // get cusum
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::ACCUMULATE>(chistVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::ACCUMULATE>(chistVectorOne, shiftVecU8LowBit, maskU8);
}
// get excusive sum
Reg::RegTensor<uint16_t> excusiveSumZero, excusiveSumOne;
```

**要点**:
- 64 位数据三级 DeInterleave（`U64→U32→U16→U8`）压缩到 8 位基数。
- mask 三级 `MaskPack` 压缩以匹配 8 位源粒度。
- 频率+累计双统计模式组合，覆盖 `BIN0`/`BIN1` 全区间。

### 实例 5：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, DeInterleave, Duplicate, HistogramsBinType, HistogramsType, MaskPack, MaskReg, PostLiteral, RegTensor, ShiftRights, Sub, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKmask`（实参 3 个，含 mask/mode: mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: 块排序的 DataCopy 场景，将 16 位输入右移拆成 8 位基数后，额外用带 mask 的 DataCopy 把基数字节落盘到 UB 供后续 scatter，再用 4 次 Histograms 构建 freq/cumsum。

（行 241-276）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg histMask = Reg::UpdateMask<uint16_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        inputVectorOne, inputXValuePtr, ONE_TIMES_B16_NUM);
    // vshr
    Reg::RegTensor<uint16_t> shiftVecOne;
    Reg::ShiftRights<uint16_t, int16_t>(shiftVecOne, inputVectorOne, bitOffset, predicateDefaultB16);
    // 256 uint8 num
    // get 256 8bit
    Reg::RegTensor<uint8_t> shiftVecU8LowBit, shiftVecU8HighBit;
    Reg::DeInterleave(
        shiftVecU8LowBit, shiftVecU8HighBit, (Reg::RegTensor<uint8_t>&)shiftVecOne,
        (Reg::RegTensor<uint8_t>&)zeroVector);
    // copy u16 mask
    Reg::MaskReg maskU8;
    Reg::MaskPack(maskU8, histMask);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        inputX8BitValuePtr, shiftVecU8LowBit, ONE_TIMES_B16_NUM, maskU8);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(
        inputX8BitValueCopyPtr, shiftVecU8LowBit, ONE_TIMES_B16_NUM, maskU8);
    // get hist
    Reg::Histograms<
        uint8_t, uint16_t, Reg::HistogramsBinType::BIN0, Reg::HistogramsType::FREQUENCY>(
        histVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<
        uint8_t, uint16_t, Reg::HistogramsBinType::BIN1, Reg::HistogramsType::FREQUENCY>(
        histVectorOne, shiftVecU8LowBit, maskU8);
    // get cusum
    Reg::Histograms<
        uint8_t, uint16_t, Reg::HistogramsBinType::BIN0, Reg::HistogramsType::ACCUMULATE>(
        chistVectorZero, shiftVecU8LowBit, maskU8);
    Reg::Histograms<
        uint8_t, uint16_t, Reg::HistogramsBinType::BIN1, Reg::HistogramsType::ACCUMULATE>(
        chistVectorOne, shiftVecU8LowBit, maskU8);
}
```

**要点**:
- 相比实例 3，多了两次带 mask 的 `DataCopy` 将 `shiftVecU8LowBit` 写回 UB，便于后续重用基数字节。
- mask 直接由 `histMask` 一次 `MaskPack` 得到（b16 路径）。
- 仍为 `FREQUENCY`+`ACCUMULATE` × `BIN0`/`BIN1` 的 4 次调用组合。

### 实例 6：top_k_v2::ReverseInputData

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, CreateMask, DataCopy, Duplicate, HistogramsBinType, HistogramsType, Interleave, MaskReg, PostLiteral, RegTensor, Sub, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: 8 位最简路径——源本身就是基数字节，无需 ShiftRights/DeInterleave，直接对原始输入调用 4 次 Histograms（BIN0/BIN1 × FREQUENCY/ACCUMULATE）。

（行 81-97）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg histMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, ONE_TIMES_B8_NUM);
    // get hist
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::FREQUENCY>(histVectorZero, inputVectorOne, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::FREQUENCY>(histVectorOne, inputVectorOne, histMask);
    // get cusum
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::ACCUMULATE>(chistVectorZero, inputVectorOne, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::ACCUMULATE>(chistVectorOne, inputVectorOne, histMask);
}
// get excusive sum
Reg::RegTensor<uint16_t> excusiveSumZero, excusiveSumOne;
```

**要点**:
- b8 路径最简：源已是 `uint8_t`，省去右移与解交织，Histograms 直接消费原始输入。
- mask 直接用 `UpdateMask<uint8_t>` 生成，无需 `MaskPack` 压缩。
- 4 次 Histograms 共用同一 `histMask` 与 `inputVectorOne`。

### 实例 7：sort::GetGlobalExcusiveSumB64

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, DataCopy, DeInterleave, Duplicate, HistogramsBinType, HistogramsType, MaskReg, PostLiteral, RegTensor, ShiftRights, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: sort 算子全局排位计算，一次加载 8 个 B64 向量，右移并多级 DeInterleave 压成单路 B8，再构建 BIN0/BIN1 的频率与累计直方图，用于多核全局 exclusive sum。

（行 238-289）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    histMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // Load eight B64 vectors, shift out the current radix byte, then compact it to B8 for histogram/scatter.
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in0, inXPtr, VF_LEN_B64);
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in1, inXPtr, VF_LEN_B64);
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in2, inXPtr, VF_LEN_B64);
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in3, inXPtr, VF_LEN_B64);
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in4, inXPtr, VF_LEN_B64);
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in5, inXPtr, VF_LEN_B64);
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in6, inXPtr, VF_LEN_B64);
    Reg::DataCopy<uint64_t, Reg::PostLiteral::POST_MODE_UPDATE>(in7, inXPtr, VF_LEN_B64);
    Reg::RegTensor<uint64_t> shift0, shift1, shift2, shift3, shift4, shift5, shift6, shift7;
    Reg::ShiftRights<uint64_t, int16_t>(shift0, in0, bitOffset, maskB64);
    Reg::ShiftRights<uint64_t, int16_t>(shift1, in1, bitOffset, maskB64);
    Reg::ShiftRights<uint64_t, int16_t>(shift2, in2, bitOffset, maskB64);
    Reg::ShiftRights<uint64_t, int16_t>(shift3, in3, bitOffset, maskB64);
    Reg::ShiftRights<uint64_t, int16_t>(shift4, in4, bitOffset, maskB64);
    Reg::ShiftRights<uint64_t, int16_t>(shift5, in5, bitOffset, maskB64);
    Reg::ShiftRights<uint64_t, int16_t>(shift6, in6, bitOffset, maskB64);
    Reg::ShiftRights<uint64_t, int16_t>(shift7, in7, bitOffset, maskB64);
    Reg::RegTensor<uint32_t> deInter0, deInter1, deInter2, deInter3, deInter4, deInter5, deInter6,
        deInter7;
    Reg::DeInterleave(deInter0, deInter1, (Reg::RegTensor<uint32_t>&)shift0,
                           (Reg::RegTensor<uint32_t>&)shift1);
    Reg::DeInterleave(deInter2, deInter3, (Reg::RegTensor<uint32_t>&)shift2,
                           (Reg::RegTensor<uint32_t>&)shift3);
    Reg::DeInterleave(deInter4, deInter5, (Reg::RegTensor<uint32_t>&)shift4,
                           (Reg::RegTensor<uint32_t>&)shift5);
    Reg::DeInterleave(deInter6, deInter7, (Reg::RegTensor<uint32_t>&)shift6,
                           (Reg::RegTensor<uint32_t>&)shift7);
    Reg::RegTensor<uint16_t> deInter0B16, deInter1B16, deInter2B16, deInter3B16;
    Reg::DeInterleave(deInter0B16, deInter1B16, (Reg::RegTensor<uint16_t>&)deInter0,
                           (Reg::RegTensor<uint16_t>&)deInter2);
    Reg::DeInterleave(deInter2B16, deInter3B16, (Reg::RegTensor<uint16_t>&)deInter4,
                           (Reg::RegTensor<uint16_t>&)deInter6);
    Reg::RegTensor<uint8_t> deInter0B8, deInter1B8;
    Reg::DeInterleave(deInter0B8, deInter1B8, (Reg::RegTensor<uint8_t>&)deInter0B16,
                           (Reg::RegTensor<uint8_t>&)deInter2B16);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputB8UbPtr, deInter0B8, VF_LEN_B8,
                                                                         histMask);
    // Build both the frequency histogram and the inclusive cumulative histogram for this tile.
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::FREQUENCY>(hist0, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::FREQUENCY>(hist1, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::ACCUMULATE>(chist0, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::ACCUMULATE>(chist1, deInter0B8, histMask);
}
ComputeSumChist<T3>(chist0, chist1, hist0, hist1, maskB16, maskB32, blockExcusiveUbRPtr, blockExcusiveUbWPtr,
                    histUbPtr, histCumsumUbPtr);
```

**要点**:
- 来源类型为 `__aicore__`（sort 算子顶层核函数内的全局统计，非 `__VEC_SCOPE__`）。
- 8 路 B64 并行加载 + 两级 DeInterleave 合流成一路 B8，是 B64 路径的典型展开。
- 4 次 Histograms 后接 `ComputeSumChist` 做跨核累加。

### 实例 8：sort::GetGlobalExcusiveSumB32

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, DataCopy, DeInterleave, Duplicate, HistogramsBinType, HistogramsType, MaskReg, PostLiteral, RegTensor, ShiftRights, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: sort 算子 32 位版全局排位统计，加载 4 个 B32 向量，右移后两级 DeInterleave 压成 B8，构建频率与累计双区间直方图。

（行 174-208）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    histMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // Load four B32 vectors, shift out the current radix byte, then compact it to B8 for histogram/scatter.
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(in0, inXPtr, VF_LEN_B32);
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(in1, inXPtr, VF_LEN_B32);
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(in2, inXPtr, VF_LEN_B32);
    Reg::DataCopy<uint32_t, Reg::PostLiteral::POST_MODE_UPDATE>(in3, inXPtr, VF_LEN_B32);
    Reg::RegTensor<uint32_t> shift0, shift1, shift2, shift3;
    Reg::ShiftRights<uint32_t, int16_t>(shift0, in0, bitOffset, maskB32);
    Reg::ShiftRights<uint32_t, int16_t>(shift1, in1, bitOffset, maskB32);
    Reg::ShiftRights<uint32_t, int16_t>(shift2, in2, bitOffset, maskB32);
    Reg::ShiftRights<uint32_t, int16_t>(shift3, in3, bitOffset, maskB32);
    Reg::RegTensor<uint16_t> deInter0, deInter1, deInter2, deInter3;
    Reg::DeInterleave(deInter0, deInter1, (Reg::RegTensor<uint16_t>&)shift0,
                           (Reg::RegTensor<uint16_t>&)shift1);
    Reg::DeInterleave(deInter2, deInter3, (Reg::RegTensor<uint16_t>&)shift2,
                           (Reg::RegTensor<uint16_t>&)shift3);

    Reg::RegTensor<uint8_t> deInter0B8, deInter1B8;
    Reg::DeInterleave(deInter0B8, deInter1B8, (Reg::RegTensor<uint8_t>&)deInter0,
                           (Reg::RegTensor<uint8_t>&)deInter2);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputB8UbPtr, deInter0B8, VF_LEN_B8,
                                                                         histMask);
    // Build both the frequency histogram and the inclusive cumulative histogram for this tile.
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::FREQUENCY>(hist0, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::FREQUENCY>(hist1, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::ACCUMULATE>(chist0, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::ACCUMULATE>(chist1, deInter0B8, histMask);
}
ComputeSumChist<T3>(chist0, chist1, hist0, hist1, maskB16, maskB32, blockExcusiveUbRPtr, blockExcusiveUbWPtr,
                    histUbPtr, histCumsumUbPtr);
```

**要点**:
- B32 路径加载 4 路向量（B64 是 8 路），DeInterleave 两级（`U32→U16→U8`）。
- `__aicore__` 上下文，用于全局 exclusive sum。
- `BIN0`/`BIN1` × `FREQUENCY`/`ACCUMULATE` 四次调用。

### 实例 9：sort::GetGlobalExcusiveSumB16

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, DataCopy, DeInterleave, Duplicate, HistogramsBinType, HistogramsType, MaskReg, PostLiteral, RegTensor, ShiftRights, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: sort 算子 16 位版全局排位统计，加载 2 个 B16 向量，右移后一次 DeInterleave 即得 B8 基数，构建频率与累计双区间直方图，接 ComputeSumChist 做跨核累加。

（行 319-342）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    histMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // Load two B16 vectors, shift out the current radix byte, then compact it to B8 for histogram/scatter.
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(in0, inputXValuePtr, VF_LEN_B16);
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(in1, inputXValuePtr, VF_LEN_B16);
    Reg::ShiftRights<uint16_t, int16_t>(shift0, in0, bitOffset, maskB16);
    Reg::ShiftRights<uint16_t, int16_t>(shift1, in1, bitOffset, maskB16);
    Reg::RegTensor<uint8_t> deInter0B8, deInter1B8;
    Reg::DeInterleave(deInter0B8, deInter1B8, (Reg::RegTensor<uint8_t>&)shift0,
                           (Reg::RegTensor<uint8_t>&)shift1);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputB8UbPtr, deInter0B8, VF_LEN_B8,
                                                                         histMask);
    // Build both the frequency histogram and the inclusive cumulative histogram for this tile.
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::FREQUENCY>(hist0, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::FREQUENCY>(hist1, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::ACCUMULATE>(chist0, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::ACCUMULATE>(chist1, deInter0B8, histMask);
}
ComputeSumChist<T3>(chist0, chist1, hist0, hist1, maskB16, maskB32, blockExcusiveUbRPtr, blockExcusiveUbWPtr,
                    histUbPtr, histCumsumUbPtr);
```

**要点**:
- B16 路径最短：2 路加载 + 一级 DeInterleave（`U16→U8`）。
- `__aicore__` 上下文，配合 `ComputeSumChist` 做全局排位。
- 4 次 Histograms 覆盖 `BIN0`/`BIN1` × `FREQUENCY`/`ACCUMULATE`。

### 实例 10：sort::GetGlobalExcusiveSumB16

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, DeInterleave, Duplicate, HistogramsBinType, HistogramsType, MaskReg, PostLiteral, RegTensor, ShiftRights, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: 与实例 9 同函数同位宽，但来源类型为 __VEC_SCOPE__（矢量作用域内的局部块内统计），代码逻辑一致，用于块内排位而非全局排位。

（行 319-342）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    histMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // Load two B16 vectors, shift out the current radix byte, then compact it to B8 for histogram/scatter.
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(in0, inputXValuePtr, VF_LEN_B16);
    Reg::DataCopy<uint16_t, Reg::PostLiteral::POST_MODE_UPDATE>(in1, inputXValuePtr, VF_LEN_B16);
    Reg::ShiftRights<uint16_t, int16_t>(shift0, in0, bitOffset, maskB16);
    Reg::ShiftRights<uint16_t, int16_t>(shift1, in1, bitOffset, maskB16);
    Reg::RegTensor<uint8_t> deInter0B8, deInter1B8;
    Reg::DeInterleave(deInter0B8, deInter1B8, (Reg::RegTensor<uint8_t>&)shift0,
                           (Reg::RegTensor<uint8_t>&)shift1);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputB8UbPtr, deInter0B8, VF_LEN_B8,
                                                                         histMask);
    // Build both the frequency histogram and the inclusive cumulative histogram for this tile.
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::FREQUENCY>(hist0, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::FREQUENCY>(hist1, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::ACCUMULATE>(chist0, deInter0B8, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::ACCUMULATE>(chist1, deInter0B8, histMask);
}
ComputeSumChist<T3>(chist0, chist1, hist0, hist1, maskB16, maskB32, blockExcusiveUbRPtr, blockExcusiveUbWPtr,
                    histUbPtr, histCumsumUbPtr);
```

**要点**:
- 与实例 9 的区别仅在 source_type（`__VEC_SCOPE__` vs `__aicore__`），体现同一函数在不同作用域被复用。
- B16 路径：2 路加载 + 一级 DeInterleave。
- 保留以展示 source_type 维度的调用差异。

### 实例 11：kth_value::VecScope_L442

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: And, CompareScalar, CreateMask, DataCopy, Duplicate, HistogramsBinType, HistogramsType, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Histograms 调用次数**: 2
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: kth_value 算子基数选择，先用 And+CompareScalar 从输入中筛出与前缀 key 相等的元素得到 selectedMask，再用 FREQUENCY 模式对被选中元素构建 BIN0/BIN1 频率直方图，用于第 k 小值判定。

（行 451-462）

```cpp
for (uint16_t i = 0; i < repeats; ++i) {
    Reg::MaskReg validMask = Reg::UpdateMask<uint8_t>(remain);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(input, keyPtr, VF_LEN_B8);
    Reg::And(masked, input, prefixMaskReg, validMask);
    Reg::MaskReg selectedMask;
    Reg::CompareScalar<uint8_t, CMPMODE::EQ>(selectedMask, masked, prefixKey, validMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::FREQUENCY>(hist0, input, selectedMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::FREQUENCY>(hist1, input, selectedMask);
}
StoreRadixByteHistogram(histogramPtr, hist0, hist1, maskB16);
```

**要点**:
- 只用 `FREQUENCY`（无 `ACCUMULATE`），因为 kth_value 只需各桶计数而非前缀和。
- mask 由 `CompareScalar` 动态生成的 `selectedMask`，而非 `UpdateMask`，体现"按谓词筛选后统计"的用法。
- `BIN0`+`BIN1` 两次调用覆盖 [0-255] 全区间。

### 实例 12：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, Duplicate, HistogramsBinType, HistogramsType, MaskReg, PostLiteral, RegTensor, Sub, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: top_k_v2 块排序 b8 路径，源已是 uint8_t，额外用带 mask 的 DataCopy 把基数字节写回 UB，再用 4 次 Histograms 构建 freq/cumsum。

（行 195-214）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg histMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, ONE_TIMES_B8_NUM);
    // get uint8 data
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputX8BitValuePtr, inputVectorOne, ONE_TIMES_B8_NUM, histMask);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputX8BitValueCopyPtr, inputVectorOne, ONE_TIMES_B8_NUM, histMask);
    // get hist
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::FREQUENCY>(histVectorZero, inputVectorOne, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::FREQUENCY>(histVectorOne, inputVectorOne, histMask);
    // get cusum
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::ACCUMULATE>(chistVectorZero, inputVectorOne, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::ACCUMULATE>(chistVectorOne, inputVectorOne, histMask);
}
// get excusive sum
Reg::RegTensor<uint16_t> excusiveSumZero, excusiveSumOne;
```

**要点**:
- b8 最简路径 + 两次带 mask 的 `DataCopy` 落盘（区别于实例 6 的纯统计）。
- mask 直接 `UpdateMask<uint8_t>`，无需压缩。
- `FREQUENCY`+`ACCUMULATE` × `BIN0`/`BIN1` 四次调用。

### 实例 13：sort::GetGlobalExcusiveSumB8

- **来源类型**: `__aicore__`
- **共现 API**: CreateMask, DataCopy, Duplicate, HistogramsBinType, HistogramsType, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Histograms 调用次数**: 4
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: sort 算子 b8 路径全局排位统计，B8 输入已是基数字节，省去右移与解交织，直接构建频率与累计双区间直方图后送 ComputeSumChist。

（行 372-388）

```cpp
for (uint16_t i = 0; i < repeatTime; i++) {
    histMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // B8 input already is the radix byte for this round; save it and build histogram/cumsum directly.
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(in0, inXPtr, VF_LEN_B8);
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputB8UbPtr, in0, VF_LEN_B8,
                                                                         histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::FREQUENCY>(hist0, in0, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::FREQUENCY>(hist1, in0, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
                         Reg::HistogramsType::ACCUMULATE>(chist0, in0, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
                         Reg::HistogramsType::ACCUMULATE>(chist1, in0, histMask);
}
ComputeSumChist<T3>(chist0, chist1, hist0, hist1, maskB16, maskB32, blockExcusiveUbRPtr, blockExcusiveUbWPtr,
                    histUbPtr, histCumsumUbPtr);
```

**要点**:
- B8 路径最简：无 `ShiftRights`/DeInterleave，Histograms 直接消费 `in0`。
- `__aicore__` 上下文，全局 exclusive sum。
- 4 次 Histograms（`BIN0`/`BIN1` × `FREQUENCY`/`ACCUMULATE`）。

### 实例 14：top_k_v2::Reg::DataCopy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, DataCopy, Duplicate, HistogramsBinType, HistogramsType, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Histograms 调用次数**: 2
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: top_k_v2 的 radix_sort_topk_b8 中，仅用 ACCUMULATE 累计模式构建 BIN0/BIN1 双区间前缀和（2 次调用），不含 FREQUENCY，直接得到 cumsum 供排位。

（行 73-83）

```cpp
for (uint16_t i = 0; i < repateTime; i++) {
    Reg::MaskReg histMask = Reg::UpdateMask<uint8_t>(inputElementNum);
    // load input
    Reg::DataCopy<uint8_t, Reg::PostLiteral::POST_MODE_UPDATE>(inputVectorOne, inputXValuePtr, ONE_TIMES_B8_NUM);
    // get hist
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0,
        Reg::HistogramsType::ACCUMULATE>(chistVectorZero, inputVectorOne, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1,
        Reg::HistogramsType::ACCUMULATE>(chistVectorOne, inputVectorOne, histMask);
}
StoreCumsumToUB<int32_t, uint16_t>(blockCumSumPtr, chistVectorZero, chistVectorOne, zeroVector);
```

**要点**:
- 只用 `ACCUMULATE`（无 `FREQUENCY`），是"仅需前缀和"的最简调用形态，2 次 Histograms。
- b8 路径，源直接为 `uint8_t` 输入。
- 与实例 12 对比：同一算子 b8 路径下，按是否需要频率统计选择 2 次或 4 次调用。

### 实例 15：kth_value::AddSelectedByteHistogram

- **来源类型**: `__aicore__`
- **共现 API**: CompareScalar, HistogramsBinType, HistogramsType, MaskReg
- **Histograms 调用次数**: 2
- **参数模式**: `T4_A3_M1_TYPEint16_t+int8_t+uint16_t+uint8_t_MASKMask`（实参 3 个，含 mask/mode: Mask，类型: int8_t, uint8_t, int16_t, uint16_t）
- **语义（待补充）**: kth_value 算子中最精简的 Histograms 用法——仅用 CompareScalar 生成 selectedMask 后，对被选中的字节做 FREQUENCY 频率统计（BIN0+BIN1 两次），共现 API 仅 4 个，是最小依赖调用样例。

（行 76-84）

```cpp
{
    Reg::MaskReg selectedMask;
    Reg::CompareScalar<uint8_t, CMPMODE::EQ>(selectedMask, flagBytes, 1, histMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN0, Reg::HistogramsType::FREQUENCY>(
        hist0, bytes, selectedMask);
    Reg::Histograms<uint8_t, uint16_t, Reg::HistogramsBinType::BIN1, Reg::HistogramsType::FREQUENCY>(
        hist1, bytes, selectedMask);
}
```

**要点**:
- 最小共现 API 组合（仅 `CompareScalar`/`HistogramsBinType`/`HistogramsType`/`MaskReg`），体现 Histograms 可独立于 `DataCopy`/`ShiftRights` 使用。
- mask 来自 `CompareScalar` 的谓词结果，按值筛选后统计。
- 只用 `FREQUENCY` 模式，2 次 `BIN0`/`BIN1` 调用。

### Histograms 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| top_k_v2 | And, CompareScalar, CreateMask, DataCopy, DeInterleave | b64 ACCUMULATE 双区间累计统计 | __VEC_SCOPE__ |
| top_k_v2 | And, CompareScalar, CreateMask, DataCopy, DeInterleave | b16 ACCUMULATE 双区间累计统计 | __VEC_SCOPE__ |
| top_k_v2 | Add, CreateMask, DataCopy, DeInterleave, Duplicate | b16 FREQUENCY+ACCUMULATE 四次统计 | __VEC_SCOPE__ |
| top_k_v2 | Add, CreateMask, DataCopy, DeInterleave, Duplicate | b64 FREQUENCY+ACCUMULATE 四次统计 | __VEC_SCOPE__ |
| top_k_v2 | CreateMask, DataCopy, DeInterleave, Duplicate | b16 频率+累计+基数落盘 | __VEC_SCOPE__ |
| top_k_v2 | Add, CreateMask, DataCopy, Duplicate | b8 FREQUENCY+ACCUMULATE 最简路径 | __VEC_SCOPE__ |
| sort | CreateMask, DataCopy, DeInterleave, Duplicate | b64 八路加载全局排位统计 | __aicore__ |
| sort | CreateMask, DataCopy, DeInterleave, Duplicate | b32 四路加载全局排位统计 | __aicore__ |
| sort | CreateMask, DataCopy, DeInterleave, Duplicate | b16 两路加载全局排位统计 | __aicore__ |
| sort | CreateMask, DataCopy, DeInterleave, Duplicate | b16 块内排位统计(VEC_SCOPE) | __VEC_SCOPE__ |
| kth_value | And, CompareScalar, CreateMask, DataCopy, Duplicate | 谓词筛选后 FREQUENCY 频率统计 | __VEC_SCOPE__ |
| top_k_v2 | CreateMask, DataCopy, Duplicate, HistogramsBinType | b8 频率+累计+基数落盘 | __VEC_SCOPE__ |
| sort | CreateMask, DataCopy, Duplicate, HistogramsBinType | b8 全局排位最简路径 | __aicore__ |
| top_k_v2 | CreateMask, DataCopy, Duplicate, HistogramsBinType | b8 仅 ACCUMULATE 双区间累计 | __VEC_SCOPE__ |
| kth_value | CompareScalar, HistogramsBinType, HistogramsType, MaskReg | 最小依赖 FREQUENCY 频率统计 | __aicore__ |

