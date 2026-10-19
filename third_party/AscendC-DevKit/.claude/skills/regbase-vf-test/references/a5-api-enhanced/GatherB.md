# GatherB

**页面ID:** atlasascendc_api_07_0402  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0402.html

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

给定源操作数在UB中的基地址和索引，GatherB指令根据索引位置将源操作数按DataBlock收集到结果寄存器张量中。每个DataBlock长度为32Byte。收集过程如下图所示：

![](images/atlasascendc_api_07_0402_img_001.png)

#### 定义原型

```
template <typename T = DefaultType, typename U, typename S>
__simd_callee__ inline void GatherB(U& dstReg, __ubuf__ T* baseAddr, S& index, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数和源操作数的数据类型 |
| U | 目的操作数的RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写 |
| S | 索引值的RegTensor类型，例如RegTensor<uint32_t>，由编译器自动推导，用户不需要填写 |

**表2 **函数参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。          类型为RegTensor          Atlas 350 加速卡，dstReg/baseAddr支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/half/float/bfloat16_t/uint64_t/int64_t |
| baseAddr | 输入 | 源操作数在UB中的基地址。需要32B对齐。          类型为UB指针。          Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/half/float/bfloat16_t/uint64_t/int64_t |
| index | 输入 | dstReg中的每个DataBlock在UB中相对于baseAddr的索引位置。索引位置要大于等于0且32B对齐。          类型为RegTensor          Atlas 350 加速卡，支持的数据类型为：uint32_t |
| mask | 输入 | src element操作有效指示，详细说明请参考MaskReg |

#### 约束说明

- 目的操作数与源操作数的数据类型相同。
- 源操作数在UB中的基地址需要32B对齐。
- 索引位置要大于等于0且32B对齐。
- 索引寄存器中可以存在相同的值，即可以多次读取源操作数中同一个DataBlock的数据。

#### 调用示例

```
template<typename T, typename U>
__simd_vf__ inline void GatherBVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ U* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<U> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, src1Addr + i * oneRepeatSize);
        AscendC::Reg::GatherB(dstReg, src0Addr, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 GatherB 实例

**未发现使用实例**。扫描范围: ops-math、ops-nn，仅 arch35 / `_apt` 路径下的 `__simd_vf__` / `__VEC_SCOPE__` 上下文，已排除 Cube 相关算子；共 0 处 `GatherB` API 调用。

> 说明: 源码中出现的 `GatherB32B64` / `GatherB8B16`（dynamic_partition 算子）与 `VfGatherBeforeSecondSkalansky`（cumsum 算子）均为算子自定义函数名，并非对本 `GatherB` API 的调用；同名前缀的 `Gather` API（共 3 处 arch35 命中）属于另一个独立 API，不计入本索引。

