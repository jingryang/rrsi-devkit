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
