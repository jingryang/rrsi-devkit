# SubC

**页面ID:** atlasascendc_api_07_0369  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0369.html

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

根据mask对源操作数srcReg0、srcReg1以及进位数据carrySrc进行按元素相减的操作，将结果写入目的操作数dstReg。srcReg0、srcReg1、carrySrc相减时如果产生借位，在MaskReg carry中对应位置每4bit的最低位写0，否则写1。计算公式如下：

![](images/atlasascendc_api_07_0369_img_001.png)

具体的示例如下：

**表1 **示例说明

| 数据类型 | 是否借位 | 示例说明 |
| --- | --- | --- |
| int32_t数据类型 | 不产生借位 | a_i = 5，b_i = 2, carrySrc_i = 1 dst_i = a_i - b_i - carrySrc_i  = 2 carryp中对应位置每4bit的最低位写1：carry_i = 1 |
| 产生借位 | a_i = 5, b_i = -7, carrySrc_i = 1 dst_i = a_i - b_i - carrySrc_i  = 11 carryp中对应位置每4bit的最低位写0：carry_i = 0 |  |
| uint32_t数据类型 | 不产生借位 | a_i = 5, b_i = 2, carrySrc_i = 1 dst_i = a_i - b_i - carrySrc_i  = 2 carryp中对应位置每4bit的最低位写1：carry_i = 1 |
| 产生借位 | a_i = 5, b_i = 7, carrySrc_i = 1 dst_i = a_i - b_i - carrySrc_i  = -3 carryp中对应位置每4bit的最低位写0：carry_i = 0 |  |

#### 函数原型

```
template <typename T = DefaultType, typename U>
__simd_callee__ inline void SubC(MaskReg& carry, U& dstReg, U& srcReg0, U& srcReg1, MaskReg& carrySrc, MaskReg& mask)
```

#### 参数说明

**表2 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 矢量目的操作数和源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：uint32_t/int32_t |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表3 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| carrySrc | 输入 | 源操作数。输入进位值。 类型为MaskReg。 |
| carry | 输出 | 目的操作数。输出进位值。 类型为MaskReg。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template <typename T>
__simd_vf__ inline void SubC(__ubuf__ T* dst0Addr, __ubuf__ T* dst1Addr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint16_t repeatTimes, uint32_t oneRepeatSize){

    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg0;
    AscendC::Reg::MaskReg mask; 
    AscendC::Reg::MaskReg maskZero = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALLF>();
    AscendC::Reg::MaskReg carry = AscendC::Reg::CreateMask<uint8_t>();
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::SubC(carry, dstReg0, srcReg0, srcReg1, maskZero, mask);
        // 8*4B=32B align
        AscendC::Reg::StoreAlign<uint32_t, AscendC::Reg::MaskDist::DIST_NORM>((__ubuf__ uint32_t*)dst1Addr + i * 8, carry);
        AscendC::Reg::StoreAlign(dst0Addr + i * oneRepeatSize, dstReg0, mask);
    }
}
```
