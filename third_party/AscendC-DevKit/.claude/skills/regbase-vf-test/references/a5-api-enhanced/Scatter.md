# Scatter

**页面ID:** atlasascendc_api_07_0403  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0403.html

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

给定源操作数的寄存器张量和索引张量，以及结果操作数在UB中的基地址，Scatter指令将源操作数按元素根据索引位置分散到UB中。分散过程如下图所示：

![](images/atlasascendc_api_07_0403_img_001.png)

#### 定义原型

```
template <typename T = DefaultType, typename U = DefaultType, typename S, typename V>
__simd_callee__ inline void Scatter(__ubuf__ T* baseAddr, S& srcReg, V& index, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数和源操作数的数据类型。 |
| U | 索引的数据类型。 |
| S | 源操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| V | 索引值的RegTensor类型，例如RegTensor<uint16_t>，由编译器自动推导，用户不需要填写。 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| baseAddr | 输出 | 目的操作数在UB中的基地址。          类型为UB指针。          Atlas 350 加速卡，支持的数据类型详见表3。 |
| srcReg | 输入 | 源操作数。          类型为RegTensor。          Atlas 350 加速卡，支持的数据类型详见表3。 |
| index | 输入 | srcReg中的每个元素在UB中相对于baseAddr的索引位置。索引值要大于等于0。          类型为RegTensor。          IndexT数据类型需要与目的操作数和源操作数的数据类型T配套使用。类型配套对应表详见约束说明。          Atlas 350 加速卡，支持的数据类型详见表3。 |
| mask | 输入 | src element操作有效指示，详细说明请参考MaskReg。 |

#### 约束说明

- 目的操作数和源操作数的数据类型T和U数据类型需要配套使用。类型配套对应表如下： 

**表3 **Scatter操作数数据类型对应表

| **T数据类型** | **U数据类型** |
| --- | --- |
| int8_t | uint16_t |
| uint8_t |  |
| int16_t |  |
| uint16_t |  |
| half |  |
| bfloat16_t |  |
| int32_t | uint32_t |
| uint32_t |  |
| float |  |
| uint64_t | uint32_t |
| int64_t |  |
| uint64_t | uint64_t |
| int64_t |  |

- 当T为b64数据类型时，T，U，V数据类型只支持以下组合： 

| **T数据类型** | **IndexT数据类型** | RegT数据类型 | RegIndexT数据类型 | 备注 |
| --- | --- | --- | --- | --- |
| b64 | uint32_t | RegTensor<uint64_t, RegTraitNumOne> | RegTensor<uint32_t> | index前32个数有效 |
| RegTensor<int64_t, RegTraitNumOne> |  |  |  |  |
| RegTensor<uint64_t, RegTraitNumTwo> | RegTensor<uint32_t> | - |  |  |
| RegTensor<int64_t, RegTraitNumTwo> |  |  |  |  |
| b64 | uint64_t | RegTensor<uint64_t, RegTraitNumOne> | RegTensor<uint64_t, RegTraitNumOne> | - |
| RegTensor<int64_t, RegTraitNumOne> |  |  |  |  |
| RegTensor<uint64_t, RegTraitNumOne> | RegTensor<uint64_t, RegTraitNumTwo> | index前32个数有效 |  |  |
| RegTensor<int64_t, RegTraitNumOne> |  |  |  |  |
| RegTensor<uint64_t,RegTraitNumTwo> | RegTensor<uint64_t, RegTraitNumTwo> | - |  |  |
| RegTensor<int64_t,RegTraitNumTwo> |  |  |  |  |

- 当T为int8或者uint8数据类型时，源操作数Tensor中仅偶数位Byte有效。最终存入UB结果地址的数据仅为源操作数Tensor偶数位Byte，即srcReg中的第0，2，4，...， 252，254位置数据会被分散存储到目的操作数中。
- index中不能有相同的值。若有2个或者2个以上的index中的数据相同，则只有其中一个值对应的数据是有效的，具体哪一个数据可能是未知的。
- 索引位置需要按照dtype_size（单个元素的Byte数）对齐，否则可能会造成数据分散结果错乱。

#### 调用示例

```
template<typename T, typename U>
 __simd_vf__ inline void ScatterVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ U* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<U> srcReg1;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Scatter(dstAddr, srcReg0, srcReg1, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Scatter 实例

扫描范围: ops-math、ops-nn，仅 arch35 / `_apt` 路径，已排除 Cube 相关算子（路径含 matmul/conv/cube 或内容含 Mmad/MatMul/Cube/mmad）。在上述范围内未发现 Scatter 的真实调用实例（共 0 处使用）。

