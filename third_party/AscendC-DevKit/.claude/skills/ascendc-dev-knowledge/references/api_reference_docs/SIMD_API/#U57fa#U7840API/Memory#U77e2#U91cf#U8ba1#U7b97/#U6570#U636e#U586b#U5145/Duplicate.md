# Duplicate

**页面ID:** atlasascendc_api_07_0088  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0088.html

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

将一个变量或立即数复制多次并填充到向量中。

针对Atlas 350 加速卡，为方便开发者使用，tensor前n个数据计算接口同时也支持直接传入Tensor，此时会将Tensor的第一个元素复制多次并填充到向量中。

#### 函数原型

- tensor前n个数据计算

  - 源操作数为标量

```
template <typename T>
__aicore__ inline void Duplicate(const LocalTensor<T>& dst, const T& scalarValue, const int32_t& count)
```

  - 源操作数为Tensor

```
template <typename T>
__aicore__ inline void Duplicate(const LocalTensor<T>& dst, const LocalTensor<T>& src, const int32_t& count)
```

- tensor高维切分计算

  - mask逐比特模式

```
template <typename T, bool isSetMask = true>
__aicore__ inline void Duplicate(const LocalTensor<T>& dst, const T& scalarValue, uint64_t mask[], const uint8_t repeatTime, const uint16_t dstBlockStride, const uint8_t dstRepeatStride)
```

  - mask连续模式

```
template <typename T, bool isSetMask = true>
__aicore__ inline void Duplicate(const LocalTensor<T>& dst, const T& scalarValue, uint64_t mask, const uint8_t repeatTime, const uint16_t dstBlockStride, const uint8_t dstRepeatStride)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。          Atlas 350 加速卡，支持的数据类型为：bool、int8_t、uint8_t、fp4x2_e2m1_t、fp4x2_e1m2_t、 hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、 fp8_e8m0_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、complex32、int64_t、uint64_t、complex64。                       Atlas A3 训练系列产品            /             Atlas A3 推理系列产品            ，支持的数据类型为：int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float。                       Atlas A2 训练系列产品            /             Atlas A2 推理系列产品            ，支持的数据类型为：int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float。                       Atlas 200I/500 A2 推理产品            ，支持的数据类型为：int16_t、uint16_t、half、int32_t、uint32_t、float。                       Atlas 推理系列产品            AI Core，支持的数据类型为：int16_t、uint16_t、half、int32_t、uint32_t、float。                       Atlas 训练系列产品            ，支持的数据类型为：int16_t、uint16_t、half、int32_t、uint32_t、float。 |
| isSetMask | 是否在接口内部设置mask。                     - true，表示在接口内部设置mask。           - false，表示在接口外部设置mask，开发者需要使用SetVectorMask接口设置mask值。这种模式下，本接口入参中的mask值必须设置为占位符MASK_PLACEHOLDER。 |

**表2 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。          LocalTensor的起始地址需要32字节对齐。 |
| scalarValue | 输入 | 被复制的源操作数，数据类型需与dst中元素的数据类型保持一致。 |
| src | 输入 | 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。          数据类型需与dst中元素的数据类型保持一致。          当传入该参数时，会将src[0]复制多次并填充到向量中。 |
| count | 输入 | 参与计算的元素个数。 |
| mask/mask[] | 输入 | mask用于控制每次迭代内参与计算的元素。                     - 逐bit模式：可以按位控制哪些元素参与计算，bit位的值为1表示参与计算，0表示不参与。            mask为数组形式，数组长度和数组元素的取值范围和操作数的数据类型有关。当操作数为16位时，数组长度为2，mask[0]、mask[1]∈[0, 264-1]并且不同时为0；当操作数为32位时，数组长度为1，mask[0]∈(0, 264-1]；当操作数为64位时，数组长度为1，mask[0]∈(0, 232-1]。            例如，mask=[8, 0]，8=0b1000，表示仅第4个元素参与计算。                               - 连续模式：表示前面连续的多少个元素参与计算。取值范围和操作数的数据类型有关，数据类型不同，每次迭代内能够处理的元素个数最大值不同。当操作数为16位时，mask∈[1, 128]；当操作数为32位时，mask∈[1, 64]；当操作数为64位时，mask∈[1, 32]。 |
| repeatTime | 输入 | 矢量计算单元，每次读取连续的8个datablock（每个block32Bytes，共256Bytes）数据进行计算，为完成对输入数据的处理，必须通过多次迭代（repeat）才能完成所有数据的读取与计算。repeatTime表示迭代的次数。 |
| dstBlockStride | 输入 | 单次迭代内，矢量目的操作数不同datablock间地址步长。 |
| dstRepeatStride | 输入 | 相邻迭代间，矢量目的操作数相同datablock地址步长。 |

#### 约束说明

- 针对Atlas 350 加速卡，bool、int8_t、uint8_t、fp4x2_e2m1_t、fp4x2_e1m2_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、 fp8_e8m0_t、complex32、int64_t、uint64_t、complex64数据类型仅支持tensor前n个数据计算接口。

#### 调用示例

- tensor高维切分计算样例-mask连续模式

```
uint64_t mask = 128;
half scalar = 18.0;
// repeatTime = 2, 128 elements one repeat, 256 elements total
// dstBlkStride = 1, no gap between blocks in one repeat
// dstRepStride = 8, no gap between repeats
AscendC::Duplicate(dstLocal, scalar, mask, 2, 1, 8 );
```

- tensor高维切分计算样例-mask逐bit模式

```
uint64_t mask[2] = { UINT64_MAX, UINT64_MAX };
half scalar = 18.0;
// repeatTime = 2, 128 elements one repeat, 256 elements total
// dstBlkStride = 1, no gap between blocks in one repeat
// dstRepStride = 8, no gap between repeats
AscendC::Duplicate(dstLocal, scalar, mask, 2, 1, 8 );
```

- tensor前n个数据计算样例，源操作数为标量

```
half inputVal(18.0);
int32_t srcDataSize = 256; // 参与计算的元素个数
AscendC::Duplicate<half>(dstLocal, inputVal, srcDataSize);
```

- tensor前n个数据计算样例，源操作数为Tensor

```
AscendC::Duplicate<half>(dstLocal, srcLocal, srcDataSize);
```

     结果示例如下：

```
scalar: 18.0
srcLocal: [18.0 1.0 2.0 ... 254.0 255.0]
dstLocal: [18.0 18.0 18.0 ... 18.0 18.0]
```
