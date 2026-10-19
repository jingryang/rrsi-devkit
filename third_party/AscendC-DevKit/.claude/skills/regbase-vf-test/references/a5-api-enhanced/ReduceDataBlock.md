# ReduceDataBlock

**页面ID:** atlasascendc_api_07_0415  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0415.html

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

当ReduceType 为SUM，将每个DataBlock（32B）中参与计算的元素相加，并将最终的计算结果依次保存在dstReg的最低位。

当ReduceType 为MAX，将每个DataBlock（32B）中的最大值，并将最终的计算结果依次保存在dstReg中的最低位。

当ReduceType 为MIN，将每个DataBlock（32B）中的最小值，并将最终的计算结果依次保存在dstReg中的最低位。

#### 定义原型

```
template <ReduceType type = ReduceType::SUM, typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void ReduceDataBlock(U& dstReg, U srcReg, MaskReg mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| type | ReduceType类型，支持SUM、MAX、MIN。 ``` enum class ReduceType {     SUM = 0,     MAX,     MIN, }; ``` |
| T | 目的操作数和源操作数的数据类型。 Atlas 350 加速卡, 支持的数据类型为：int16_t/uint16_t/half/int32_t/uint32_t/float |
| mode | 选择MERGING模式或ZEROING模式。当前仅支持ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。 |
| U | 目的操作数和源操作数的RegTensor类型， 例如RegTensor<int32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void ReduceDataBlockVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        // type = ReduceType::SUM
        AscendC::Reg::ReduceDataBlock<AscendC::Reg::ReduceType::SUM>(dstReg, srcReg, mask);
        // type = ReduceType::MAX
        // AscendC::Reg::ReduceDataBlock<AscendC::Reg::ReduceType::MAX>(dstReg, srcReg, mask);
        // type = ReduceType::MIN
        // AscendC::Reg::ReduceDataBlock<AscendC::Reg::ReduceType::MIN>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask); 
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 ReduceDataBlock 实例

### 实例 1：flat_quant::ExpMaxVf

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, And, CreateAddrReg, Duplicate, LoadAlign, LoadDist, MaskReg, Max, PostLiteral, ReduceType, RegTensor, StoreUnAlign, StoreUnAlignPost, UnalignReg, UpdateMask
- **ReduceDataBlock 调用次数**: 1
- **参数模式**: `T1_A3_M1_TYPEnone_MASKmask+maskReg`（实参 3 个，含 mask/mode: mask, maskReg）
- **语义**: flat_quant 算子的 ExpMaxVf 函数逐 repeat 求每个 DataBlock（32B）内的最大指数值：先以 LoadAlign 交错载入 bfloat16 源数据，用 And 配合 expMaskBF16 提取指数位，Max 求两路寄存器的逐元素最大，再用 ReduceDataBlock<MAX> 将一个 DataBlock 内的最大指数归约到 vdMaxExp 最低位，供逐 DataBlock 量化缩放使用。

（行 287-301）

```cpp
for (uint16_t i = 0; i < repeatTimes; i++) {
    aReg = AscendC::Reg::CreateAddrReg<uint32_t>(i, oneRepeatSize);
    maskReg = AscendC::Reg::UpdateMask<bfloat16_t>(count);

    AscendC::Reg::LoadAlign<bfloat16_t, AscendC::Reg::LoadDist::DIST_DINTLV_B16>(vSrcReg0, vSrcReg1,
                                                                                           srcPtr, aReg);
    AscendC::Reg::And(vExpExtract0, (AscendC::Reg::RegTensor<uint16_t>&)vSrcReg0, expMaskBF16,
                           maskReg);
    AscendC::Reg::And(vExpExtract1, (AscendC::Reg::RegTensor<uint16_t>&)vSrcReg1, expMaskBF16,
                           maskReg);
    AscendC::Reg::Max(vdMaxExp, vExpExtract0, vExpExtract1, maskReg);
    AscendC::Reg::ReduceDataBlock<AscendC::Reg::ReduceType::MAX>(vdMaxExp, vdMaxExp, maskReg);
    AscendC::Reg::StoreUnAlign<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        dstPtr, vdMaxExp, u1, STORE_UNALIGN_STRIDE_BYTES);
}
```

**要点**:
1. 模板参数固定为 `ReduceType::MAX`，对 32B DataBlock 内元素求最大值，结果落在 dstReg 最低位。
2. dstReg 与 srcReg 复用同一寄存器 vdMaxExp（原地归约），归约后仅最低位为有效结果，高位元素不应再使用。
3. maskReg 由 `UpdateMask<bfloat16_t>(count)` 生成，控制尾块参与归约的元素数；mode 默认 ZEROING，未选中元素置零。

### 实例 2：flat_quant::ExpMaxVfcuBLAS

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, And, CreateAddrReg, Duplicate, LoadAlign, LoadDist, MaskReg, Max, PostLiteral, ReduceType, RegTensor, StoreUnAlign, StoreUnAlignPost, UnalignReg, UpdateMask
- **ReduceDataBlock 调用次数**: 1
- **参数模式**: `T1_A3_M1_TYPEnone_MASKmask+maskReg`（实参 3 个，含 mask/mode: mask, maskReg）
- **语义**: flat_quant 算子的 cuBLAS 路径变体 ExpMaxVfcuBLAS，逐 repeat 求每个 DataBlock 内的最大绝对值：用 And 配合 absMask16Bit 取 bfloat16 的绝对值位，Max 求两路最大后，ReduceDataBlock<MAX> 将 DataBlock 内最大绝对值归约到 vdMaxExp 最低位，供 cuBLAS 路径的逐 DataBlock 量化缩放使用。

（行 319-335）

```cpp
for (uint16_t i = 0; i < repeatTimes; i++) {
    aReg = AscendC::Reg::CreateAddrReg<uint32_t>(i, oneRepeatSize);
    maskReg = AscendC::Reg::UpdateMask<bfloat16_t>(count);

    AscendC::Reg::LoadAlign<bfloat16_t, AscendC::Reg::LoadDist::DIST_DINTLV_B16>(vSrcReg0, vSrcReg1,
                                                                                           srcPtr, aReg);
    AscendC::Reg::And((AscendC::Reg::RegTensor<uint16_t>&)vSrcReg0,
                           (AscendC::Reg::RegTensor<uint16_t>&)vSrcReg0, absMask16Bit, maskReg);
    AscendC::Reg::And((AscendC::Reg::RegTensor<uint16_t>&)vSrcReg1,
                           (AscendC::Reg::RegTensor<uint16_t>&)vSrcReg1, absMask16Bit, maskReg);
    AscendC::Reg::Max(vdMaxExp, (AscendC::Reg::RegTensor<uint16_t>&)vSrcReg0,
                           (AscendC::Reg::RegTensor<uint16_t>&)vSrcReg1, maskReg);

    AscendC::Reg::ReduceDataBlock<AscendC::Reg::ReduceType::MAX>(vdMaxExp, vdMaxExp, maskReg);
    AscendC::Reg::StoreUnAlign<uint16_t, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(
        dstPtr, vdMaxExp, u1, STORE_UNALIGN_STRIDE_BYTES);
}
```

**要点**:
1. 与实例 1 同为 `ReduceType::MAX`、原地归约（dst=src=vdMaxExp），区别在前置 And 用 absMask16Bit 取绝对值而非 expMaskBF16 取指数位。
2. 共现 API 组合（LoadAlign+And+Max+ReduceDataBlock+StoreUnAlign）与实例 1 完全一致，体现 ReduceDataBlock 在"逐 DataBlock 求极值→写回标量"模式中的稳定位置。
3. StoreUnAlign 采用 `POST_MODE_UPDATE` 自增 dstPtr，配合 ReduceDataBlock 只把结果写入最低位的特性，逐 DataBlock 输出单个标量结果。

### ReduceDataBlock 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| flat_quant | AddrReg, And, CreateAddrReg, Duplicate, LoadAlign | LoadAlign 交错载入→And 提取指数位→Max 逐元素求最大→ReduceDataBlock<MAX> 归约到 DataBlock 内最大指数（原地）→StoreUnAlign 写回 | __simd_vf__ |
| flat_quant | AddrReg, And, CreateAddrReg, Duplicate, LoadAlign | LoadAlign 交错载入→And 取绝对值→Max 逐元素求最大→ReduceDataBlock<MAX> 归约到 DataBlock 内最大绝对值（原地）→StoreUnAlign 写回 | __simd_vf__ |

