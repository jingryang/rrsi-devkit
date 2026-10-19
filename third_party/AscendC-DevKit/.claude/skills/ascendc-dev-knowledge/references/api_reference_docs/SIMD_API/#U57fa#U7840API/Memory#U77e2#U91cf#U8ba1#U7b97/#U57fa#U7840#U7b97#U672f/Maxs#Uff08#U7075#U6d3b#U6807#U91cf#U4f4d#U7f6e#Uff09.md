# Maxs（灵活标量位置）

**页面ID:** atlasascendc_api_07_00249  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00249.html

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

提供灵活标量位置的接口，支持标量在前和标量在后两种场景。其中标量输入支持配置LocalTensor单点元素，计算公式如下，idx表示LocalTensor单点元素的位置系数。

![](images/atlasascendc_api_07_00249_img_001.png)

#### 函数原型

- tensor前n个数据计算

```
template <typename T = BinaryDefaultType, bool isSetMask = true, const BinaryConfig& config = DEFAULT_BINARY_CONFIG, typename U, typename S, typename V>
__aicore__ inline void Maxs(const U& dst, const S& src0, const V& src1, const int32_t& count)
```

- tensor高维切分计算

  - mask逐bit模式

```
template <typename T = BinaryDefaultType, bool isSetMask = true, const BinaryConfig& config = DEFAULT_BINARY_CONFIG, typename U, typename S, typename V>
__aicore__ inline void Maxs(const U& dst, const S& src0, const V& src1, uint64_t mask[], const uint8_t repeatTime, const UnaryRepeatParams& repeatParams)
```

  - mask连续模式

```
template <typename T = BinaryDefaultType, bool isSetMask = true, const BinaryConfig& config = DEFAULT_BINARY_CONFIG, typename U, typename S, typename V>
__aicore__ inline void Maxs(const U& dst, const S& src0, const V& src1, uint64_t mask, const uint8_t repeatTime, const UnaryRepeatParams& repeatParams)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。          对于灵活标量位置接口，为预留参数，暂未启用，为后续的功能扩展做保留，需要指定时，传入默认值BinaryDefaultType即可。 |
| isSetMask | 是否在接口内部设置mask模式和mask值。                     - true，表示在接口内部设置。            tensor高维切分计算API/tensor前n个数据计算API内部使用了mask的Normal模式/Counter模式，一般情况下保持isSetMask默认值即可，表示在API内部根据开发者传入的mask/count参数进行mask模式和mask值的设置。           - false，表示在接口外部设置。                           - 针对tensor高维切分计算接口，对性能要求较高的部分场景下，开发者需要使用SetMaskNorm/SetMaskCount设置mask模式，并通过SetVectorMask接口设置mask值。本接口入参中的mask值必须设置为MASK_PLACEHOLDER。               - 针对tensor前n个数据计算接口，对性能要求较高的部分场景下，开发者需要使用SetMaskCount设置mask模式为Counter模式，并通过SetVectorMask接口设置mask值。本接口入参中的count不生效，建议设置成1。                                针对以下型号，tensor前n个数据计算API中的isSetMask参数不生效，保持默认值即可。                     - 针对Atlas 350 加速卡           -               Atlas 200I/500 A2 推理产品 |
| 类型为BinaryConfig，当标量为LocalTensor单点元素类型时生效，用于指定单点元素操作数位置。默认值DEFAULT_BINARY_CONFIG，表示右操作数为标量。                                                                                                                           ``` struct BinaryConfig {     int8_t scalarTensorIndex = 1; // 用于指定标量为LocalTensor单点元素时标量的位置，0表示左操作数，1表示右操作数 }; constexpr BinaryConfig DEFAULT_BINARY_CONFIG = {1}; ``` |  |
| U | LocalTensor类型，根据输入参数dst自动推导相应的数据类型，开发者无需配置该参数，保证dst满足数据类型的约束即可。 |
| S | LocalTensor类型或标量类型，根据输入参数src0自动推导相应的数据类型，开发者无需配置该参数，保证src0满足数据类型的约束即可。 |
| V | LocalTensor类型或标量类型，根据输入参数src1自动推导相应的数据类型，开发者无需配置该参数，保证src1满足数据类型的约束即可。 |

**表2 **参数说明

| **参数名称** | **类型** | **说明** |
| --- | --- | --- |
| dst | 输出 | 目的操作数。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。          LocalTensor的起始地址需要32字节对齐。          Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/half/bfloat16_t/int16_t/float/int32_t/uint64_t/int64_t |
| src0/src1 | 输入 | 灵活标量位置接口中源操作数。                     - 类型为LocalTensor时，支持当作矢量操作数或标量单点元素，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。            Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/half/bfloat16_t/int16_t/float/int32_t/uint64_t/int64_t           - 类型为标量时：            Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/half/bfloat16_t/int16_t/float/int32_t/uint64_t/int64_t                    数据类型需要与目的操作数保持一致。 |
| count | 输入 | 参与计算的元素个数。 |
| mask/mask[] | 输入 | mask用于控制每次迭代内参与计算的元素。                     - 逐bit模式：可以按位控制哪些元素参与计算，bit位的值为1表示参与计算，0表示不参与。            mask为数组形式，数组长度和数组元素的取值范围和操作数的数据类型有关。当操作数为16位时，数组长度为2，mask[0]、mask[1]∈[0, 264-1]并且不同时为0；当操作数为32位时，数组长度为1，mask[0]∈(0, 264-1]；当操作数为64位时，数组长度为1，mask[0]∈(0, 232-1]。            例如，mask=[8, 0]，8=0b1000，表示仅第4个元素参与计算。                               - 连续模式：表示前面连续的多少个元素参与计算。取值范围和操作数的数据类型有关，数据类型不同，每次迭代内能够处理的元素个数最大值不同。当操作数为16位时，mask∈[1, 128]；当操作数为32位时，mask∈[1, 64]；当操作数为64位时，mask∈[1, 32]。 |
| repeatTime | 输入 | 重复迭代次数。 矢量计算单元，每次读取连续的256Bytes数据进行计算，为完成对输入数据的处理，必须通过多次迭代（repeat）才能完成所有数据的读取与计算。repeatTime表示迭代的次数。          关于该参数的具体描述请参考高维切分API。 |
| repeatParams | 输入 | 元素操作控制结构信息，具体请参考UnaryRepeatParams。 |

#### 约束说明

- 调用灵活标量位置接口且源操作数为LocalTensor单点元素的场景，不支持和目的操作数地址重叠。

- 针对Atlas 350 加速卡，int8_t/uint8_t/uint64_t/int64_t数据类型仅支持tensor前n个数据计算接口。
- 左操作数及右操作数中，必须有一个为矢量；当前不支持左右操作数同时为标量。
- 本接口传入LocalTensor单点数据作为标量时，idx参数需要传入编译期已知的常量，传入变量时需要声明为constexpr。

#### 调用示例

- tensor高维切分计算样例-mask连续模式

```
uint64_t mask = 128;
// repeatTime = 4, 单次迭代处理128个数，计算512个数需要迭代4次
// dstBlkStride, srcBlkStride = 1, 每个迭代内src0参与计算的数据地址间隔为1个datablock，表示单次迭代内数据连续读取和写入
// dstRepStride, srcRepStride = 8, 相邻迭代间的地址间隔为8个datablock，表示相邻迭代间数据连续读取和写入
// 标量在后示例
AscendC::Maxs(dstLocal, src0Local, src1Local[0], mask, 4, { 1, 1, 8, 8 });

// 标量在前示例
static constexpr AscendC::BinaryConfig config = { 0 };
AscendC::Maxs<BinaryDefaultType, true, config>(dstLocal, src0Local[0], src1Local, mask, 4, { 1, 1, 8, 8 });
```

- tensor高维切分计算样例-mask逐bit模式

```
uint64_t mask[2] = { UINT64_MAX, UINT64_MAX };
// repeatTime = 4, 单次迭代处理128个数，计算512个数需要迭代4次
// dstBlkStride, srcBlkStride = 1, 每个迭代内src0参与计算的数据地址间隔为1个datablock，表示单次迭代内数据连续读取和写入
// dstRepStride, srcRepStride = 8, 相邻迭代间的地址间隔为8个datablock，表示相邻迭代间数据连续读取和写入
// 标量在后示例
AscendC::Maxs(dstLocal, src0Local, src1Local[0], mask, 4, {1, 1, 8, 8});

// 标量在前示例
static constexpr AscendC::BinaryConfig config = { 0 };
AscendC::Maxs<BinaryDefaultType, true, config>(dstLocal, src0Local[0], src1Local, mask, 4, { 1, 1, 8, 8 });
```

- tensor前n个数据计算样例

```
// 标量在后示例
AscendC::Maxs(dstLocal, src0Local, src1Local[0], 512);

// 标量在前示例
static constexpr AscendC::BinaryConfig config = { 0 };
AscendC::Maxs<BinaryDefaultType, true, config>(dstLocal, src0Local[0], src1Local, 512);
```

     结果示例如下：

```
输入数据src0Local：[1 2 3 ... 512]
输入数据src1Local：[2 2 2 ... 2]
// 标量在前，src0Local[0]作为标量
输出数据dstLocal：[2 2 2 ... 2]
// 标量在后，src1Local[0]作为标量
输出数据dstLocal：[2 2 3 ... 512]
```
