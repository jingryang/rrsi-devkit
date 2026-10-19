# UnPack

**页面ID:** atlasascendc_api_07_0423  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0423.html

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

对于无符号整型，将源操作数srcReg中低半部分或高半部分的元素以高位填0扩充位宽的方式写入dstReg。对于有符号整型，将源操作数srcReg中低半部分或高半部分的元素以保持符号位扩充位宽的方式写入dstReg。

#### 函数原型

```
template <typename T = DefaultType, typename U = DefaultType, HighLowPart part = HighLowPart::LOWEST, typename S, typename V>
__simd_callee__ inline void UnPack(S& dstReg, V& srcReg)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int16_t/uint16_t/int32_t/uint32_t/int64_t/uint64_t 源操作数和目的操作数的数据类型约束参见表3。 |
| U | 源操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/int32_t/uint32_t |
| part | 枚举类型，用于控制读取srcReg的低半部分还是高半部分。 - HighLowPart::LOWEST，低位模式，读取srcReg的低半部分。- HighLowPart::HIGHEST，高位模式，读取srcReg的高半部分。 注：RegTraitNumTwo只支持LOWEST模式。 |
| S | 目的操作数RegTensor类型。 |
| V | 源操作数RegTensor类型。 |

**表2 **函数参数说明

| 参数名 | 描述 |
| --- | --- |
| dstReg | 目的操作数。 类型为RegTensor。 |
| srcReg | 源操作数。 类型为RegTensor。 |

**表3 **源操作数和目的操作数的数据类型对应表

| **T数据类型** | **U数据类型** |
| --- | --- |
| int16_t | int8_t |
| uint16_t | uint8_t |
| int32_t | int16_t |
| uint32_t | uint16_t |
| uint64_t | uint32_t |
| int64_t | int32_t |

#### 约束说明

无

#### 调用示例

```
template<typename T, typename U, int32_t mode>
__simd_vf__ inline void UnPackVF(__ubuf__ T* dstAddr, __ubuf__ U* srcAddr, uint32_t oneDstRepSize, uint16_t repeatTimes, uint32_t oneSrcRepSize)
{
    AscendC::Reg::RegTensor<U> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneSrcRepSize);
        if constexpr (mode == 0) {
            AscendC::Reg::UnPack<T, U, AscendC::Reg::HighLowPart::LOWEST>(dstReg, srcReg);
        } else if constexpr (mode == 1) {
            AscendC::Reg::UnPack<T, U, AscendC::Reg::HighLowPart::HIGHEST>(dstReg, srcReg);
        }
        AscendC::Reg::StoreAlign(dstAddr + i * oneDstRepSize, dstReg, mask);
    }
}
```
