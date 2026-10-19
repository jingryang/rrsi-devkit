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
