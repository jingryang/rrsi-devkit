# WholeReduceMin

**页面ID:** atlasascendc_api_07_0080  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0080.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品            AI Core | √ |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | √ |

#### 功能说明

每个repeat内所有数据求最小值以及其索引index，返回的索引值为每个repeat内部索引。归约指令的总体介绍请参考如何使用归约计算API。

#### 函数原型

- mask逐bit模式：

```
template <typename T, bool isSetMask = true>
__aicore__ inline void WholeReduceMin(const LocalTensor<T>& dst, const LocalTensor<T>& src, const uint64_t mask[], const int32_t repeatTime, const int32_t dstRepStride, const int32_t srcBlkStride, const int32_t srcRepStride, ReduceOrder order = ReduceOrder::ORDER_VALUE_INDEX)
```

- mask连续模式：

```
template <typename T, bool isSetMask = true>
__aicore__ inline void WholeReduceMin(const LocalTensor<T>& dst, const LocalTensor<T>& src, const int32_t mask, const int32_t repeatTime, const int32_t dstRepStride, const int32_t srcBlkStride, const int32_t srcRepStride, ReduceOrder order = ReduceOrder::ORDER_VALUE_INDEX)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。          Atlas 350 加速卡，支持的数据类型为：uint16_t、int16_t、uint32_t、int32_t、half、float                       Atlas A3 训练系列产品            /             Atlas A3 推理系列产品            ，支持的数据类型为：half/float                       Atlas A2 训练系列产品            /             Atlas A2 推理系列产品            ，支持的数据类型为：half/float                       Atlas 200I/500 A2 推理产品            ，支持的数据类型为：half/float                       Atlas 推理系列产品            AI Core，支持的数据类型为：half/float                       Atlas 训练系列产品            ，支持的数据类型为：half |
| isSetMask | 是否在接口内部设置mask。                     - true，表示在接口内部设置mask。           - false，表示在接口外部设置mask，开发者需要使用SetVectorMask接口设置mask值。这种模式下，本接口入参中的mask值必须设置为占位符MASK_PLACEHOLDER。 |

**表2 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。          LocalTensor的起始地址需要保证4字节对齐（针对half数据类型），8字节对齐（针对float数据类型）。 |
| src | 输入 | 源操作数。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。          LocalTensor的起始地址需要32字节对齐。          源操作数的数据类型需要与目的操作数保持一致。 |
| mask/mask[] | 输入 | mask用于控制每次迭代内参与计算的元素。                     - 逐bit模式：可以按位控制哪些元素参与计算，bit位的值为1表示参与计算，0表示不参与。            mask为数组形式，数组长度和数组元素的取值范围和操作数的数据类型有关。当操作数为16位时，数组长度为2，mask[0]、mask[1]∈[0, 264-1]并且不同时为0；当操作数为32位时，数组长度为1，mask[0]∈(0, 264-1]；当操作数为64位时，数组长度为1，mask[0]∈(0, 232-1]。            例如，mask=[8, 0]，8=0b1000，表示仅第4个元素参与计算。                               - 连续模式：表示前面连续的多少个元素参与计算。取值范围和操作数的数据类型有关，数据类型不同，每次迭代内能够处理的元素个数最大值不同。当操作数为16位时，mask∈[1, 128]；当操作数为32位时，mask∈[1, 64]；当操作数为64位时，mask∈[1, 32]。 |
| repeatTime | 输入 | 迭代次数。取值范围为[0, 255]。          关于该参数的具体描述请参考高维切分API。 |
| dstRepStride | 输入 | 目的操作数相邻迭代间的地址步长。以一个repeat归约后的长度为单位。          返回索引和最值时，单位为dst数据类型所占字节长度的两倍。比如当dst为half时，单位为4Bytes；          仅返回最值时，单位为dst数据类型所占字节长度；          仅返回索引时，单位为uint32_t类型所占字节长度。          注意，此参数值             Atlas 训练系列产品            不支持配置0。 |
| srcBlkStride | 输入 | 单次迭代内datablock的地址步长。详细说明请参考dataBlockStride。 |
| srcRepStride | 输入 | 源操作数相邻迭代间的地址步长，即源操作数每次迭代跳过的datablock数目。详细说明请参考repeatStride。 |
| order | 输入 | 使用order参数指定dst中index与value的相对位置以及返回结果行为，ReduceOrder类型，默认值为ORDER_VALUE_INDEX。取值范围如下：                     - ORDER_VALUE_INDEX：表示value位于低半部，返回结果存储顺序为[value, index]。           - ORDER_INDEX_VALUE：表示index位于低半部，返回结果存储顺序为[index, value]。           - ORDER_ONLY_VALUE：表示只返回最值，返回结果存储顺序为[value]。           - ORDER_ONLY_INDEX：表示只返回最值索引，返回结果存储顺序为[index]。                    Atlas 350 加速卡，支持ORDER_VALUE_INDEX、ORDER_INDEX_VALUE、ORDER_ONLY_VALUE、ORDER_ONLY_INDEX。                       Atlas A3 训练系列产品            /             Atlas A3 推理系列产品            ，支持ORDER_VALUE_INDEX、ORDER_INDEX_VALUE、ORDER_ONLY_VALUE、ORDER_ONLY_INDEX。                       Atlas A2 训练系列产品            /             Atlas A2 推理系列产品            ，支持ORDER_VALUE_INDEX、ORDER_INDEX_VALUE、ORDER_ONLY_VALUE、ORDER_ONLY_INDEX。                       Atlas 200I/500 A2 推理产品            ，支持ORDER_VALUE_INDEX、ORDER_ONLY_VALUE。                       Atlas 推理系列产品            AI Core，支持ORDER_VALUE_INDEX、ORDER_INDEX_VALUE。                       Atlas 训练系列产品            ，支持ORDER_VALUE_INDEX。 |

#### 约束说明

- dst结果存储顺序由order决定，默认为最值，最值索引。返回结果中索引index数据按照dst的数据类型进行存储，比如dst使用half类型时，index按照half类型进行存储，读取时需要使用reinterpret_cast方法转换到整数类型。若输入数据类型是half，需要使用reinterpret_cast<uint16_t*>，若输入是float，需要使用reinterpret_cast<uint32_t*>。比如调用示例中，前两个计算结果为[9.980e-01 5.364e-06]，5.364e-06需要使用reinterpret_cast方法转换得到索引值90。特别地，针对
        Atlas A2 训练系列产品
       /
        Atlas A2 推理系列产品
       、
        Atlas A3 训练系列产品
       /
        Atlas A3 推理系列产品
       ，ORDER_ONLY_INDEX（仅返回最值索引）情况下，读取index时都需要使用reinterpret_cast<uint32_t*>。针对Atlas 350 加速卡，ORDER_ONLY_INDEX（仅返回最值索引）情况下，当操作数数据类型为uint16_t/int16_t/half时，读取index都需要使用reinterpret_cast<uint32_t*>。
- 针对不同场景合理使用归约指令可以带来性能提升，相关介绍请参考选择低延迟指令，优化归约操作性能，具体样例请参考[ReduceCustom](https://gitcode.com/cann/asc-devkit/blob/9.0.0/examples/01_simd_cpp_api/03_libraries/04_reduce/reduce)。

#### 调用示例

- tensor高维切分计算样例-mask连续模式

```
// dstLocal,srcLocal均为half类型，srcLocal的计算数据量为512，连续排布，计算结果也需要连续排布，使用tensor高维切分计算接口，设定mask为最多的128个全部元素参与计算
// 根据以上信息，推断出repeatTime为4，dstRepStride为1，srcBlkStride为1，srcRepStride为8
// 若求最小值及索引，并且需要存储顺序为[value, index]的结果，可以使用默认order，接口示例为：AscendC::WholeReduceMin<half>(dstLocal, srcLocal, 128, 4, 1, 1, 8);

// 若求最小值及索引，并且需要存储顺序为[index, value]的结果，接口示例为：
AscendC::WholeReduceMin<half>(dstLocal, srcLocal, 128, 4, 1, 1, 8, AscendC::ReduceOrder::ORDER_INDEX_VALUE);

// 若只求最小值，并且需要存储[value]的结果，接口示例为：
AscendC::WholeReduceMin<half>(dstLocal, srcLocal, 128, 4, 1, 1, 8, AscendC::ReduceOrder::ORDER_ONLY_VALUE);

// 若只求索引，并且需要存储[index]的结果，接口示例为：
AscendC::WholeReduceMin<half>(dstLocal, srcLocal, 128, 4, 1, 1, 8, AscendC::ReduceOrder::ORDER_ONLY_INDEX);
```

- tensor高维切分计算样例-mask逐bit模式

```
// dstLocal,srcLocal均为half类型，srcLocal的计算数据量为512，连续排布，计算结果也需要连续排布，使用tensor高维切分计算接口，设定mask为最多的128个全部元素参与计算
uint64_t mask[2] = { 0xFFFFFFFFFFFFFFFF, 0xFFFFFFFFFFFFFFFF };

// 根据以上信息，推断出repeatTime为4，dstRepStride为1，srcBlkStride为1，srcRepStride为8
// 若求最小值及索引，并且需要存储顺序为[value, index]的结果，使用默认order，接口示例为：
AscendC::WholeReduceMin<half>(dstLocal, srcLocal, mask, 4, 1, 1, 8);

// 若求最小值及索引，并且需要存储顺序为[index, value]的结果，接口示例为：
AscendC::WholeReduceMin<half>(dstLocal, srcLocal, mask, 4, 1, 1, 8, AscendC::ReduceOrder::ORDER_INDEX_VALUE);

// 若只求最小值，并且需要存储[value]的结果，接口示例为：
AscendC::WholeReduceMin<half>(dstLocal, srcLocal, mask, 4, 1, 1, 8, AscendC::ReduceOrder::ORDER_ONLY_VALUE);

// 若只求索引，并且需要存储[index]的结果，接口示例为：
AscendC::WholeReduceMin<half>(dstLocal, srcLocal, mask, 4, 1, 1, 8, AscendC::ReduceOrder::ORDER_ONLY_INDEX);
```

示例结果如下：

```
输入数据src_gm：
[10   10   10   10   10   10   10   10   10   10   10   10   10   10   10   10
 10   10   10   10   10   10   10   10   10   10   10   10   10   10   10   10
 10   10   10   10   10   10   10   10   10   10   10   10   10   10   10   10
 10   10   10   10   **1**   10   10   10   10   10   10   10   10   10   10   10
 10   10   10   10   10   10   10   10   10   10   10   10   10   10   10   10
 10   10   10   10   10   10   10   10   10   10   10   10   10   10   10   10
 10   10   10   10   10   10   10   10   10   10   10   10   10   10   10   10
 10   10   10   10   10   10   10   10   10   10   10   10   10   10   10   10
 20   20   20   20   20   20   20   20   20   20   20   20   20   20   20   20
 20   20   20   20   20   20   20   20   20   20   20   20   20   20   20   20
 20   20   20   20   20   20   20   20   20   20   20   20   20   20   20   20
 20   20   20   20   20   20   20   20   20   20   20   20   20   20   20   20
 20   20   20   20   20   20   20   20   20   20   20   20   20   20   20   20
 20   20   20   20   20   20   20   20   20   20   20   20   20   20   20   20
 20   20   20   20   **2**   20   20   20   20   20   20   20   20   20   20   20
 20   20   20   20   20   20   20   20   20   20   20   20   20   20   20   20
 ...
 30   30   30   30   30   30   30   30   30   30   30   30   30   30   30   30
 30   30   30   **3**   30   30   30   30   30   30   30   30   30   30   30   30
 30   30   30   30   30   30   30   30   30   30   30   30   30   30   30   30
 30   30   30   30   30   30   30   30   30   30   30   30   30   30   30   30
 30   30   30   30   30   30   30   30   30   30   30   30   30   30   30   30
 30   30   30   30   30   30   30   30   30   30   30   30   30   30   30   30
 30   30   30   30   30   30   30   30   30   30   30   30   30   30   30   30
 30   30   30   30   30   30   30   30   30   30   30   30   30   30   30   30]

若ReduceOrder类型为ORDER_VALUE_INDEX或默认，则输出数据dst_gm：
[1 3.09944e-06 2 5.96046e-06 ... 3 1.13249e-06]
若ReduceOrder类型为ORDER_INDEX_VALUE，则输出数据dst_gm：
[3.09944e-06 1 5.96046e-06 2 ... 1.13249e-06 3]
若ReduceOrder类型为ORDER_ONLY_VALUE，则输出数据dst_gm：
[1 2 ... 3 0 0 0 ...]
若ReduceOrder类型为ORDER_ONLY_VALUE，则输出数据dst_gm：
[3.09944e-06 0 5.96046e-06 0 ... 1.13249e-06 0]

其中，index的值为int数值的二进制，在half中的表达，以上述结果为例：
前128个数中，11的位置在对应的repeat中为52，十六进制为0x3400，对应half值为3.09944e-06。
第二个128个数中，12的位置在对应的repeat中为100，十六进制为0x6400，对应half值为5.96046e-06。
最后128个数中，13的位置在对应的repeat中为19，十六进制为0x1300，对应half值为1.13249e-06。
```
