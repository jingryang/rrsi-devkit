# Compares（灵活标量位置）

**页面ID:** atlasascendc_api_07_00256  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00256.html

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

![](images/atlasascendc_api_07_00256_img_001.png)

支持多种比较模式：

- LT：小于（less than）
- GT：大于（greater than）

- GE：大于或等于（greater than or equal to）
- EQ：等于（equal to）
- NE：不等于（not equal to）
- LE：小于或等于（less than or equal to）

#### 函数原型

- tensor前n个数据计算

```
template <typename T0 = BinaryDefaultType, typename T1 = BinaryDefaultType, bool isSetMask = true, const BinaryConfig &config = DEFAULT_BINARY_CONFIG, typename T2, typename T3, typename T4>
__aicore__ inline void Compares(const T2& dst, const T3& src0, const T4& src1, CMPMODE cmpMode, uint32_t count)
```

- tensor高维切分计算

  - mask逐bit模式

```
template <typename T0 = BinaryDefaultType, typename T1 = BinaryDefaultType, bool isSetMask = true, const BinaryConfig &config = DEFAULT_BINARY_CONFIG, typename T2, typename T3, typename T4>
__aicore__ inline void Compares(const T2& dst, const T3& src0, const T4& src1, CMPMODE cmpMode, const uint64_t mask[], uint8_t repeatTime, const UnaryRepeatParams& repeatParams)
```

  - mask连续模式

```
template <typename T0 = BinaryDefaultType, typename T1 = BinaryDefaultType, bool isSetMask = true, const BinaryConfig &config = DEFAULT_BINARY_CONFIG, typename T2, typename T3, typename T4>
__aicore__ inline void Compares(const T2& dst, const T3& src0, const T4& src1, CMPMODE cmpMode, const uint64_t mask, uint8_t repeatTime, const UnaryRepeatParams& repeatParams)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T0 | 对于固定标量位置接口，表示源操作数数据类型。          特别地，对于灵活标量位置接口，为预留参数，暂未启用，为后续的功能扩展做保留，需要指定时，传入默认值BinaryDefaultType即可。 |
| T1 | 对于固定标量位置接口，表示目的操作数数据类型。          特别地，对于灵活标量位置接口，为预留参数，暂未启用，为后续的功能扩展做保留，需要指定时，传入默认值BinaryDefaultType即可。 |
| isSetMask | 是否在接口内部设置mask。                     - true，表示在接口内部设置mask。           - false，表示在接口外部设置mask，开发者需要使用SetVectorMask接口设置mask值。这种模式下，本接口入参中的mask值必须设置为占位符MASK_PLACEHOLDER。 |
| 类型为BinaryConfig，当标量为LocalTensor单点元素类型时生效，用于指定单点元素操作数位置。默认值DEFAULT_BINARY_CONFIG，表示右操作数为标量。                                                                                                                           ``` struct BinaryConfig {     int8_t scalarTensorIndex = 1; // 用于指定标量为LocalTensor单点元素时标量的位置，0表示左操作数，1表示右操作数 }; constexpr BinaryConfig DEFAULT_BINARY_CONFIG = {1}; ``` |  |
| T2 | LocalTensor类型，根据输入参数dst自动推导相应的数据类型，开发者无需配置该参数，保证dst满足数据类型的约束即可。 |
| T3 | LocalTensor类型或标量类型，根据输入参数src0自动推导相应的数据类型，开发者无需配置该参数，保证src0满足数据类型的约束即可。 |
| T4 | LocalTensor类型或标量类型，根据输入参数src1自动推导相应的数据类型，开发者无需配置该参数，保证src1满足数据类型的约束即可。 |

**表2 **接口参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。          LocalTensor的起始地址需要32字节对齐。          dst用于存储比较结果，将dst中uint8_t类型的数据按照bit位展开，由左至右依次表征对应位置的src0和src1的比较结果，如果比较后的结果为真，则对应比特位为1，否则为0。          Atlas 350 加速卡，支持的数据类型为：uint8_t |
| src0/src1 | 输入 | 灵活标量位置接口中源操作数。                     - 类型为LocalTensor时，支持当作矢量操作数或标量单点元素，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。            Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/half/bfloat16_t/float/int32_t/uint32_t/int64_t/uint64_t/double（double只支持CMPMODE::EQ）           - 类型为标量时：            Atlas 350 加速卡，支持的数据类型为：int8_t/uint8_t/int16_t/uint16_t/half/bfloat16_t/float/int32_t/uint32_t/int64_t/uint64_t/double（double只支持CMPMODE::EQ）                    数据类型需要与目的操作数保持一致。 |
| cmpMode | 输入 | CMPMODE类型，表示比较模式，包括EQ，NE，GE，LE，GT，LT。                     - LT:src0小于（less than）src1           - GT:src0大于（greater than）src1           - GE：src0大于或等于（greater than or equal to）src1           - EQ：src0等于（equal to）src1           - NE：src0不等于（not equal to）src1           - LE：src0小于或等于（less than or equal to）src1 |
| mask/mask[] | 输入 | mask用于控制每次迭代内参与计算的元素。                     - 连续模式：表示前面连续的多少个元素参与计算。取值范围和操作数的数据类型有关，数据类型不同，每次迭代内能够处理的元素个数最大值不同。当操作数为16位时，mask∈[1, 128]；当操作数为32位时，mask∈[1, 64]。                               - 逐bit模式：可以按位控制哪些元素参与计算，bit位的值为1表示参与计算，0表示不参与。参数类型为长度为2或者4的uint64_t类型数组。            例如，mask=[8, 0]，8=0b1000，表示仅第4个元素参与计算。            参数取值范围和操作数的数据类型有关，数据类型不同，每次迭代内能够处理的元素个数最大值不同。当操作数为16位时，mask[0]、mask[1]∈[0, 264-1]并且不同时为0；当操作数为32位时，mask[1]为0，mask[0]∈(0, 264-1]。 |
| repeatTime | 输入 | 重复迭代次数。矢量计算单元，每次读取连续的256Bytes数据进行计算，为完成对输入数据的处理，必须通过多次迭代（repeat）才能完成所有数据的读取与计算。repeatTime表示迭代的次数。          关于该参数的具体描述请参考高维切分API。 |
| repeatParams | 输入 | 控制操作数地址步长的参数。UnaryRepeatParams类型，包含操作数相邻迭代间相同DataBlock的地址步长，操作数同一迭代内不同DataBlock的地址步长等参数。          相邻迭代间的地址步长参数说明请参考repeatStride；同一迭代内DataBlock的地址步长参数说明请参考dataBlockStride。 |
| count | 输入 | 参与计算的元素个数。**设置count时，需要保证count个元素所占空间256字节对齐。** |

#### 约束说明

- 调用灵活标量位置接口且源操作数为LocalTensor单点元素的场景，不支持源操作数和目的操作数地址重叠。

- dst按照小端顺序排序成二进制结果，对应src中相应位置的数据比较结果。
- **使用tensor前n个数据参与计算的接口，设置count时，需要保证count个元素所占空间256字节对齐。**
- 针对Atlas 350 加速卡，int8_t/uint8_t/uint64_t/int64_t/double数据类型仅支持tensor前n个数据计算接口，double只支持CMPMODE::EQ。
- 左操作数及右操作数中，必须有一个为矢量；当前不支持左右操作数同时为标量。
- 本接口传入LocalTensor单点数据作为标量时，idx参数需要传入编译期已知的常量，传入变量时需要声明为constexpr。

#### 调用示例

对于灵活标量位置接口，支持直接传入立即数或单点LocalTensor作为标量，并且支持标量在前和在后两种调用方式，调用示例如下；

- tensor前n个数据计算接口样例

```
// 标量在后，src1Local[0]作为标量
AscendC::Compares(dstLocal, src0Local, src1Local[0], AscendC::CMPMODE::LT, srcDataSize);

// 标量在前，src0Local[0]作为标量
static constexpr AscendC::BinaryConfig config = { 0 };
AscendC::Compares<BinaryDefaultType, BinaryDefaultType, true, config>(dstLocal, src0Local[0], src1Local, AscendC::CMPMODE::LT, srcDataSize);
```

- tensor高维切分计算-mask连续模式

```
uint64_t mask = 256 / sizeof(float); // 256为每个迭代处理的字节数
int repeat = 4;
AscendC::UnaryRepeatParams repeatParams = { 1, 1, 8, 8 };
// repeat = 4, 64 elements one repeat, 256 elements total
// dstBlkStride, srcBlkStride = 1, no gap between blocks in one repeat
// dstRepStride, srcRepStride = 8, no gap between repeats
// 标量在后，src1Local[0]作为标量
AscendC::Compares(dstLocal, src0Local, src1Local[0], AscendC::CMPMODE::LT, mask, repeat, repeatParams);

// 标量在前，src0Local[0]作为标量
static constexpr AscendC::BinaryConfig config = { 0 };
AscendC::Compares<BinaryDefaultType, BinaryDefaultType, true, config>(dstLocal, src0Local[0], src1Local, AscendC::CMPMODE::LT, mask, repeat, repeatParams);
```

- tensor高维切分计算-mask逐bit模式

```
uint64_t mask[2] = { UINT64_MAX, 0};
int repeat = 4;
AscendC::UnaryRepeatParams repeatParams = { 1, 1, 8, 8 };
// repeat = 4, 64 elements one repeat, 256 elements total
// srcBlkStride, = 1, no gap between blocks in one repeat
// dstRepStride, srcRepStride = 8, no gap between repeats
// 标量在后，src1Local[0]作为标量
AscendC::Compares(dstLocal, src0Local, src1Local[0], AscendC::CMPMODE::LT, mask, repeat, repeatParams);

// 标量在前，src0Local[0]作为标量
static constexpr AscendC::BinaryConfig config = { 0 };
AscendC::Compares<BinaryDefaultType, BinaryDefaultType, true, config>(dstLocal, src0Local[0], src1Local, AscendC::CMPMODE::LT, mask, repeat, repeatParams);
```
