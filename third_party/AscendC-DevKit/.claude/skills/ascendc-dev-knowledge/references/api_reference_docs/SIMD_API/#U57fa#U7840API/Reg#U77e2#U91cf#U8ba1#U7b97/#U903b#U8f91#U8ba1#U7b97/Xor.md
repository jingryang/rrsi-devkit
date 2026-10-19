# Xor

**页面ID:** atlasascendc_api_07_0364  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0364.html

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

本节介绍两种接口，分别用于对RegTensor和MaskReg进行操作：

- 对RegTensor操作：

根据mask对输入数据srcReg0、srcReg1按元素异或（^）操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0364_img_001.png)

- 对MaskReg操作：

将两个输入MaskReg的有效bit进行逻辑异或运算得到新的MaskReg。

#### 函数原型

- 对RegTensor操作

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Xor(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

- 对MaskReg操作

```
__simd_callee__ inline void Xor(MaskReg& dst, MaskReg& src0, MaskReg& src1, MaskReg& mask)
```

#### 参数说明

- 对RegTensor操作

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：bool/uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/uint64_t/int64_t |
| mode | 选择MERGING模式或ZEROING模式。   - ZEROING，mask未筛选的元素在dst中置零。  - MERGING，当前不支持。 |
| U | srcReg0/srcReg1/dstReg RegTensor类型， 例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

- 对MaskReg操作

**表3 **参数说明

| 参数名 | 描述 |
| --- | --- |
| dst | 目的操作数。 |
| src0 | 源操作数。 |
| src1 | 源操作数。 |
| mask | 指示在计算过程中哪些bit有效。 |

#### 约束说明

无

#### 调用示例

- 对RegTensor操作

```
template <typename T>
__simd_vf__ inline void XorVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);       
        AscendC::Reg::Xor(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```

- 对MaskReg操作

```
template <typename T>
__simd_vf__ inline void XorVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg src0 = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALLF>();
    AscendC::Reg::MaskReg src1 = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALL>();
    AscendC::Reg::MaskReg dst;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < (uint16_t)repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Xor(dst, src0, src1, mask);
        AscendC::Reg::Adds(srcReg, srcReg, 0, dst);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask);
    }
}
```
