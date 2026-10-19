# AddC

**页面ID:** atlasascendc_api_07_0367  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0367.html

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

根据mask对输入数据srcReg0、srcReg1以及进位数据carrySrc进行按元素相加操作，将结果写入dstReg。如果srcReg0, srcReg1输入转换为uint32_t类型，加上进位值carrySrc相加时超出uint32_t最大值，在MaskReg carry中对应位置每4bit大小写1，否则写0。计算公式如下：

![](images/atlasascendc_api_07_0367_img_001.png)

对carry的操作示例如下：

- int32_t类型，a_i, b_i∈[-2147483648, 2147483647]

  - 假设a_i = -2147483648, b_i = -2, carrySrc_i = 1

(uint32_t)a_i + (uint32_t)b_i + (uint32_t)carrySrc_i = (uint64_t)uint_dst_i

因为uint_dst_i >> 32 大于0，所以carry[(i%64):4*(i%64)] = 1

  - 假设a_i = 2, b_i = 5, carrySrc_i = 1

(uint32_t)a_i + (uint32_t)b_i + (uint32_t)carrySrc_i = (uint64_t)uint_dst_i

因为uint_dst_i >> 32 等于0，所以carry[(i%64):4*(i%64)] = 0

- uint32_t类型，a_i, b_i∈[0, 4294967295]

  - 假设a_i = 4294967295, b_i = 2, carrySrc_i = 0

(uint32_t)a_i + (uint32_t)b_i + (uint32_t)carrySrc_i = (uint64_t)uint_dst_i

因为uint_dst_i >> 32 大于0，所以carry[(i%64):4*(i%64)] = 1

  - 假设a_i = 3, b_i = 2, carrySrc_i = 0

(uint32_t)a_i + (uint32_t)b_i + (uint32_t)carrySrc_i = (uint64_t)uint_dst_i

因为uint_dst_i >> 32 等于0，所以carry[(i%64):4*(i%64)] = 0

#### 函数原型

```
template <typename T = DefaultType, typename U>
__simd_callee__ inline void AddC(MaskReg& carry, U& dstReg, U& srcReg0, U& srcReg1, MaskReg& carrySrc, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint32_t/int32_t。 |
| U | 操作数RegTensor类型， 例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| carry | 输出 | 目的操作数 类型为MaskReg。 |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 三个源操作数的数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 三个源操作数的数据类型需要与目的操作数保持一致。 |
| carrySrc | 输入 | 源操作数。输入进位值。 类型为MaskReg。 三个源操作数的数据类型需要与目的操作数保持一致。 Atlas 350 加速卡，支持的数据类型为：uint32_t/int32_t。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template <typename T>
static __simd_vf__ inline void AddVF(__ubuf__ T* dst0Addr, __ubuf__ T* dst1Addr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint16_t repeatTimes, uint32_t oneRepeatSize){

    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg0;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::MaskReg carry = AscendC::Reg::CreateMask<uint8_t>();
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Add(carry, dstReg0, srcReg0, srcReg1, mask);
        // 8*4B=32B align
        AscendC::Reg::StoreAlign<uint32_t, AscendC::Reg::MaskDist::DIST_NORM>((__ubuf__ uint32_t*)dst1Addr + i * 8, carry);
        AscendC::Reg::StoreAlign(dst0Addr + i * oneRepeatSize, dstReg0, mask);
    }
}
```
