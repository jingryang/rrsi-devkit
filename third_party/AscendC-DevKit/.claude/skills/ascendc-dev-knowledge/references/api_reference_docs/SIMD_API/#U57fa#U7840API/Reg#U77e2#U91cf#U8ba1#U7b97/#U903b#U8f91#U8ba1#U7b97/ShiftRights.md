# ShiftRights

**页面ID:** atlasascendc_api_07_0387  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0387.html

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

源操作数内每个元素做右移，右移的位数由输入参数scalarValue决定。

对数据类型uint16_t/uint32_t的源操作数做逻辑右移，对数据类型int16_t/int32_t的源操作数做算术右移。

逻辑右移为去掉最低位，最高位填充为0。

算术右移为去掉最低位，最高位复制符号位。

例：数据类型uint16_t，二进制数 1010101010101010，逻辑右移一位结果为 0101010101010101；

数据类型int16_t，二进制数 1010101010101010，算术右移一位结果为 1101010101010101；

数据类型int16_t，二进制数 1010101010101010，算术右移三位结果为 1111010101010101。

#### 函数原型

```
template <typename T = DefaultType, typename U, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void ShiftRights(S& dstReg, S& srcReg, U scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 矢量目的操作数和源操作数的数据类型。 Atlas 350 加速卡，dstReg/srcReg支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/int32_t/uint32_t/int64_t/uint64_t |
| U | 标量源操作数的数据类型 Atlas 350 加速卡，dstReg/srcReg支持的数据类型为：int16_t |
| mode | 选择MERGING模式或ZEROING模式。当前仅支持ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。 |
| S | dstReg RegTensor类型， 例如RegTensor<uint16_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 不支持设置为负数。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T, typename U>
__simd_vf__ inline void ShiftRightsVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, U scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::ShiftRights(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```
