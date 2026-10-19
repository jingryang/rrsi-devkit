# Scatter(ISASI)

**页面ID:** atlasascendc_api_07_0235  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0235.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品            AI Core | √ |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | x |

> **注意:** 

该API不支持
>          Atlas A2 训练系列产品
>         /
>          Atlas A2 推理系列产品
>         、
>          Atlas A3 训练系列产品
>         /
>          Atlas A3 推理系列产品
>         ，如果需要在上述AI处理器实现数据离散功能，建议参考[Scatter兼容样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/05_compatibility_guide/scatter)进行适配。

#### 功能说明

给定一个连续的输入张量和一个目的地址偏移张量，Scatter指令根据偏移地址生成新的结果张量后将输入张量分散到结果张量中。

将源操作数src中的元素按照指定的位置（由dst_offset和base_addr共同作用）分散到目的操作数dst中。

#### 函数原型

- tensor前n个数据计算

```
template <typename T>
__aicore__ inline void Scatter(const LocalTensor<T>& dst, const LocalTensor<T>& src, const LocalTensor<uint32_t>& dstOffset, const uint32_t dstBaseAddr, const uint32_t count)
```

- tensor高维切分计算

  - mask逐bit模式

```
template <typename T>
__aicore__ inline void Scatter(const LocalTensor<T>& dst, const LocalTensor<T>& src, const LocalTensor<uint32_t>& dstOffset, const uint32_t dstBaseAddr, const uint64_t mask[], const uint8_t repeatTime, const uint8_t srcRepStride)
```

  - mask连续模式

```
template <typename T>
__aicore__ inline void Scatter(const LocalTensor<T>& dst, const LocalTensor<T>& src, const LocalTensor<uint32_t>& dstOffset, const uint32_t dstBaseAddr, const uint64_t mask, const uint8_t repeatTime, const uint8_t srcRepStride)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。          Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/half/bfloat16_t/uint32_t/int32_t/float/uint64_t/int64_t                       Atlas 200I/500 A2 推理产品            ，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/half/uint32_t/int32_t/float                       Atlas 推理系列产品            AI Core，支持的数据类型为：uint16_t/uint32_t/float/half |

**表2 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| dst | 输出 | 目的操作数，类型为LocalTensor。LocalTensor的起始地址需要32字节对齐。 |
| src | 输入 | 源操作数，类型为LocalTensor。数据类型需与dst保持一致。 |
| dstOffset | 输入 | 用于存储源操作数的每个元素在dst中对应的地址偏移。偏移基于dst的基地址dstBaseAddr计算，以字节为单位，取值应保证按dst数据类型位宽对齐，否则会导致非预期行为。          针对以下型号，地址偏移的取值范围不超出uint32_t的范围即可。                       Atlas 推理系列产品            AI Core          针对以下型号，地址偏移的取值范围如下：当操作数为8位时，取值范围为[0, 216-1]；当操作数为16位时，取值范围为[0, 217-1]，当操作数为32位或者64位时，不超过uint32_t的范围即可。超出取值范围可能导致非预期输出。                       Atlas 200I/500 A2 推理产品                      Atlas 350 加速卡 |
| dstBaseAddr | 输入 | dst的起始偏移地址，单位是字节。取值应保证按dst数据类型位宽对齐，否则会导致非预期行为。 |
| count | 输入 | 执行处理的数据个数。 |
| mask/mask[] | 输入 | mask用于控制每次迭代内参与计算的元素。                     - 连续模式：表示前面连续的多少个元素参与计算。取值范围和操作数的数据类型有关，数据类型不同，每次迭代内能够处理的元素个数最大值不同。当操作数为8位或16位时，mask∈[1, 128]；当操作数为32位时，mask∈[1, 64]；当操作数为64位时，mask∈[1, 32]。                               - 逐bit模式：可以按位控制哪些元素参与计算，bit位的值为1表示参与计算，0表示不参与。参数类型为长度为2的uint64_t类型数组。            例如，mask=[8, 0]，8=0b1000，表示仅第4个元素参与计算。            参数取值范围和操作数的数据类型有关，数据类型不同，每次迭代内能够处理的元素个数最大值不同。当操作数为8位或16位时，mask[0]、mask[1]∈[0, 264-1]并且不同时为0；当操作数为32位时，mask[1]为0，mask[0]∈(0, 264-1]；当操作数为64位时，mask[1]为0，mask[0]∈(0, 232-1]。 |
| repeatTime | 输入 | 指令迭代次数，每次迭代完成8个datablock的数据收集，数据范围：repeatTime∈[0,255]。                     特别地，针对以下型号：                       -                Atlas 200I/500 A2 推理产品                          - Atlas 350 加速卡                               操作数为**8位**时，每次迭代完成**4个datablock**（32Bytes）的数据收集。 |
| srcRepStride | 输入 | 相邻迭代间的地址步长，单位是datablock。 |

#### 约束说明

- dstOffset中的偏移地址不能有相同值，如果存在2个或者多个偏移重复的情况，行为是不可预期的。
- 针对Atlas 350 加速卡，uint8_t/int8_t数据类型仅支持tensor前n个数据计算接口。

#### 调用示例

```
uint32_t m_elementCount = 128;
AscendC::Scatter(dstLocal, srcLocal, dstOffsetLocal, (uint32_t)0, m_elementCount); // dstOffsetLocal 用于存储源操作数的每个元素在dst中对应的地址偏移
```

     结果示例：

```
输入数据dstOffsetLocal:
[254 252 250 ... 4 2 0]
输入数据srcLocal（128个half类型数据）: 
[0 1 2 ... 125 126 127]
输出数据dstGlobal:
[127 126 125 ... 2 1 0]
```
