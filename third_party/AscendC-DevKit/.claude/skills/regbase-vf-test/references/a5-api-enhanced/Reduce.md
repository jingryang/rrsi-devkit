# Reduce

**页面ID:** atlasascendc_api_07_0412  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0412.html

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

支持归约求和、归约取最大值、归约取最小值。

#### 定义原型

```
template <ReduceType type = ReduceType::SUM, typename T = DefaultType, typename U = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S, typename V>
__simd_callee__ inline void Reduce(S& dstReg, V srcReg, MaskReg mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| type | ReduceType类型，支持SUM、MAX、MIN。 ``` enum class ReduceType {     SUM = 0,     MAX,     MIN, }; ``` |
| T | 目的操作数dstReg的数据类型。 - 当type = ReduceType::SUM时，支持的数据类型需与源操作数srcReg匹配，匹配关系如下，下文中的数据类型匹配关系按照<dstReg，srcReg>的顺序排布：Atlas 350 加速卡，支持的数据类型为：<int32_t，int16_t>，<int32_t，int32_t>，<half，half>，<uint32_t，uint16_t>，<uint32_t，uint32_t>，<float，float>，<uint64_t， uint64_t>，<int64_t， int64_t>  - 当type = ReduceType::MAX或type = ReduceType::MIN时：Atlas 350 加速卡，支持的数据类型为：int16_t/half/int32_t/float/uint16_t/uint32_t/uint64_t/int64_t |
| U | 源操作数srcReg的数据类型。 - 当type = ReduceType::SUM时，支持的数据类型需与目的操作数dstReg匹配。- 当type = ReduceType::MAX或type = ReduceType::MIN时，源操作数的数据类型和目的操作数相同。 Atlas 350 加速卡，支持的数据类型为：int16_t/half/int32_t/float/uint16_t/uint32_t/uint64_t/int64_t |
| mode | 选择MERGING模式或ZEROING模式。当前仅支持ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。 |
| S | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| V | 源操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

- 对于归约求最大值，当所有元素均不参与计算时，将该数据类型的最小值写入dstReg，当存在多个最大值时，会将第一个最大值的索引保存在dstReg中。
- 对于归约求最小值，当所有元素均不参与计算时，将该数据类型的最大值写入dstReg，当存在多个最小值时，会将第一个最小值的索引保存在dstReg中。
- 当归约求最小值或者归约求最大值时，源操作数的数据类型和目的操作数相同。

#### 调用示例

- 归约求和：

```
template<typename T, typename U>
__simd_vf__ inline void ReduceVF(__ubuf__ T* dstAddr, __ubuf__ U* srcAddr, uint32_t count, 
 uint32_t srcRepeatSize, uint32_t dstRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<U> srcReg;
    AscendC::Reg::RegTensor<T> dsrReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * srcRepeatSize);
        mask = AscendC::Reg::UpdateMask<U>(count);
        AscendC::Reg::Reduce<AscendC::Reg::ReduceType::SUM>(dsrReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * dstRepeatSize, dsrReg, mask);
    }
}
```

- 归约求最大值或者最小值

```
template<typename T>
__aicore__ inline void ReduceVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        // type = ReduceType::MAX
        AscendC::Reg::Reduce<AscendC::Reg::ReduceType::MAX>(dstReg, srcReg, mask);
        // type = ReduceType::MIN
        // AscendC::Reg::Reduce<AscendC::Reg::ReduceType::MIN>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, maskReg);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Reduce 实例

### 实例 1：grouped_quant_max::AscendC::HardEvent

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Cast, CreateMask, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Mul, ReduceType, RegTensor, StoreAlign, StoreDist, UpdateMask
- **Reduce 调用次数**: 1
- **参数模式**: `T1_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 分组量化算子中，循环内用逐元素 Max 累积各 tile 的绝对值最大值，循环结束后用 Reduce<MAX> 配合全量 maskAll 把寄存器内多 lane 的最大值归约为单一分组最大值，再用 StoreAlign<DIST_FIRST_ELEMENT_B32> 只写出首 lane 的归约结果。

（行 253-311）

```cpp
{
    AscendC::Reg::RegTensor<T> vregX;
    AscendC::Reg::RegTensor<float> vregFloatAbsT;
    AscendC::Reg::RegTensor<float> vregTileMaxFp32;
    AscendC::Reg::RegTensor<float> vregFloatX;
    AscendC::Reg::RegTensor<float> vregS;
    AscendC::Reg::RegTensor<float> vregFloatY;
    AscendC::Reg::RegTensor<U> vregY;

    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<float>();
    AscendC::Reg::MaskReg maskAll = AscendC::Reg::CreateMask<float>();
    uint32_t countOne = 1;
    AscendC::Reg::MaskReg maskOne = AscendC::Reg::UpdateMask<float>(countOne);

    float currentGroupMax = maxLocal.GetValue(groupIndex);
    AscendC::Reg::Duplicate<float>(vregTileMaxFp32, currentGroupMax, mask);
    AscendC::Reg::Duplicate<float>(vregS, scaleValue_, mask);

    uint32_t count = dataCount;
    for (uint16_t i = 0; i < vfLoopNum; i++) {
        mask = AscendC::Reg::UpdateMask<float>(count);

        if constexpr (IsSameType<T, float>::value) {
            AscendC::Reg::LoadAlign<float, AscendC::Reg::LoadDist::DIST_NORM>(vregFloatX, xLocalAddr + i * VL_);
        } else if constexpr (IsSameType<T, half>::value) {
            AscendC::Reg::LoadAlign<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX, xLocalAddr + i * VL_);
            AscendC::Reg::Cast<float, half, GroupedQuantMaxBase<T, U, RoundMode>::CAST_TRAIT_HALF_TO_FP32>(
                vregFloatX, vregX, mask);
        } else if constexpr (IsSameType<T, bfloat16_t>::value) {
            AscendC::Reg::LoadAlign<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX,
                                                                                         xLocalAddr + i * VL_);
            AscendC::Reg::Cast<float, bfloat16_t, GroupedQuantMaxBase<T, U, RoundMode>::CAST_TRAIT_BF16_TO_FP32>(
                vregFloatX, vregX, mask);
        }

        AscendC::Reg::Abs<float>(vregFloatAbsT, vregFloatX, mask);
        AscendC::Reg::Max<float, AscendC::Reg::MaskMergeMode::MERGING>(vregTileMaxFp32, vregTileMaxFp32,
                                                                       vregFloatAbsT, mask);
        AscendC::Reg::Mul(vregFloatY, vregFloatX, vregS, mask);

        if constexpr (IsSameType<U, hifloat8_t>::value) {
            AscendC::Reg::Cast<U, float, GroupedQuantMaxBase<T, U, RoundMode>::CAST_TRAIT_FP32_TO_HIFP8>(
                vregY, vregFloatY, mask);
            AscendC::Reg::StoreAlign<U, Reg::StoreDist::DIST_PACK4_B32>(outLocalAddr + i * VL_, vregY, mask);
        } else if constexpr (IsSameType<U, fp8_e5m2_t>::value) {
            AscendC::Reg::Cast<U, float, GroupedQuantMaxBase<T, U, RoundMode>::CAST_TRAIT_FP32_TO_FP8E5M2>(
                vregY, vregFloatY, mask);
            AscendC::Reg::StoreAlign<U, Reg::StoreDist::DIST_PACK4_B32>(outLocalAddr + i * VL_, vregY, mask);
        } else if constexpr (IsSameType<U, fp8_e4m3fn_t>::value) {
            AscendC::Reg::Cast<U, float, GroupedQuantMaxBase<T, U, RoundMode>::CAST_TRAIT_FP32_TO_FP8E4M3>(
                vregY, vregFloatY, mask);
            AscendC::Reg::StoreAlign<U, Reg::StoreDist::DIST_PACK4_B32>(outLocalAddr + i * VL_, vregY, mask);
        }
    }

    AscendC::Reg::Reduce<Reg::ReduceType::MAX>(vregTileMaxFp32, vregTileMaxFp32, maskAll);
    AscendC::Reg::StoreAlign<float, Reg::StoreDist::DIST_FIRST_ELEMENT_B32>(
        ((__local_mem__ float*)maxAddr + groupIndex), vregTileMaxFp32, maskOne);
}
```

**要点**:
1. Reduce<ReduceType::MAX> 第三参传 maskAll（CreateMask 生成的全 1 mask），将寄存器内所有有效 lane 的最大值归约到同一寄存器。
2. 归约结果存于 vregTileMaxFp32，随后用 StoreAlign<DIST_FIRST_ELEMENT_B32> + maskOne（仅 1 个有效元素）把首 lane 的归约值写回 local memory 的 groupIndex 位置。
3. 与 Max（逐元素取大）配合：循环内 Max 做跨 repeat 的累积，循环外 Reduce 做跨 lane 的最终归约，两者层级不同不可混用。

### 实例 2：quant_max::AscendC::HardEvent

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Cast, CreateMask, DataCopy, Duplicate, LoadDist, MaskReg, Max, Mul, ReduceType, RegTensor, StoreDist, UpdateMask
- **Reduce 调用次数**: 1
- **参数模式**: `T1_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 单张量量化算子中，循环内逐 repeat 用 Max 累积各 tile 的绝对值最大值，循环结束后用 Reduce<MAX> 把寄存器内多 lane 归约为单一最大值，再整体 DataCopy 写回 tileMaxLocalAddr。

（行 162-214）

```cpp
{
    AscendC::Reg::RegTensor<T> vregX;
    AscendC::Reg::RegTensor<float> vregFloatAbsT;
    AscendC::Reg::RegTensor<float> vregTileMaxFp32;
    AscendC::Reg::RegTensor<float> vregFloatX;
    AscendC::Reg::RegTensor<float> vregS;
    AscendC::Reg::RegTensor<float> vregFloatY;
    AscendC::Reg::RegTensor<U> vregY;

    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<float>();
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(vregTileMaxFp32, tileMaxLocalAddr);

    AscendC::Reg::Duplicate<float>(vregS, scaleValue_, mask);

    uint32_t count = dataCount;
    for (uint16_t i = 0; i < vfLoopNum; i++) {
        mask = AscendC::Reg::UpdateMask<float>(count);

        if constexpr (IsSameType<T, float>::value) {
            AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_NORM>(vregFloatX, xLocalAddr + i * VL);
        } else if constexpr (IsSameType<T, half>::value) {
            AscendC::Reg::DataCopy<half, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX, xLocalAddr + i * VL);
            AscendC::Reg::Cast<float, half, QuantMaxBase<T, U, RoundMode>::CAST_TRAIT_HALF_TO_FP32>(vregFloatX,
                                                                                                    vregX, mask);
        } else if constexpr (IsSameType<T, bfloat16_t>::value) {
            AscendC::Reg::DataCopy<bfloat16_t, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(vregX, xLocalAddr + i * VL);
            AscendC::Reg::Cast<float, bfloat16_t, QuantMaxBase<T, U, RoundMode>::CAST_TRAIT_BF16_TO_FP32>(
                vregFloatX, vregX, mask);
        }

        AscendC::Reg::Abs<float>(vregFloatAbsT, vregFloatX, mask);
        AscendC::Reg::Max<float>(vregTileMaxFp32, vregTileMaxFp32, vregFloatAbsT, mask);
        AscendC::Reg::Mul(vregFloatY, vregFloatX, vregS, mask);

        if constexpr (IsSameType<U, hifloat8_t>::value) {
            AscendC::Reg::Cast<U, float, QuantMaxBase<T, U, RoundMode>::CAST_TRAIT_FP32_TO_HIFP8>(vregY, vregFloatY,
                                                                                                  mask);
            AscendC::Reg::DataCopy<U, AscendC::Reg::StoreDist::DIST_PACK4_B32>(outLocalAddr + i * VL, vregY, mask);
        } else if constexpr (IsSameType<U, fp8_e5m2_t>::value) {
            AscendC::Reg::Cast<U, float, QuantMaxBase<T, U, RoundMode>::CAST_TRAIT_FP32_TO_FP8E5M2>(
                vregY, vregFloatY, mask);
            AscendC::Reg::DataCopy<U, AscendC::Reg::StoreDist::DIST_PACK4_B32>(outLocalAddr + i * VL, vregY, mask);
        } else if constexpr (IsSameType<U, fp8_e4m3fn_t>::value) {
            AscendC::Reg::Cast<U, float, QuantMaxBase<T, U, RoundMode>::CAST_TRAIT_FP32_TO_FP8E4M3>(
                vregY, vregFloatY, mask);
            AscendC::Reg::DataCopy<U, AscendC::Reg::StoreDist::DIST_PACK4_B32>(outLocalAddr + i * VL, vregY, mask);
        }
    }

    AscendC::Reg::Reduce<AscendC::Reg::ReduceType::MAX>(vregTileMaxFp32, vregTileMaxFp32, mask);
    AscendC::Reg::DataCopy<float, AscendC::Reg::StoreDist::DIST_NORM>(tileMaxLocalAddr, vregTileMaxFp32, mask);
}
```

**要点**:
1. Reduce<MAX> 第三参复用循环最后一次 UpdateMask<float>(count) 得到的 mask（按 dataCount 截断的有效 lane），而非全量 mask，适合尾部 count 非满 lane 的场景。
2. 归约结果通过 DataCopy<DIST_NORM> 整寄存器写回 tileMaxLocalAddr，与实例 1「只写首元素」的策略不同，对应不同的下游消费方式。
3. 与实例 1 共用「Max 累积 + Reduce 归约」两段式，但 mask 选择（partial vs all）和写出方式（整寄存器 vs 首元素）体现了 Reduce 输出语义对场景的适配。

### Reduce 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| grouped_quant_max | Abs, Cast, CreateMask, Duplicate, LoadAlign | Reduce<MAX> 全量 maskAll 归约 + StoreAlign 取首元素写回 | __VEC_SCOPE__ |
| quant_max | Abs, Cast, CreateMask, DataCopy, Duplicate | Reduce<MAX> 复用尾部 mask 归约 + DataCopy 整寄存器写回 | __VEC_SCOPE__ |

