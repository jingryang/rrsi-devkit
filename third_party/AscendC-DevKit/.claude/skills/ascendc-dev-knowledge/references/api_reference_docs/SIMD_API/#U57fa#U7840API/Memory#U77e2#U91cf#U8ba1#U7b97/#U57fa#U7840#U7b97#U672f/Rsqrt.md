# Rsqrt

**页面ID:** atlasascendc_api_07_0030  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0030.html

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

按元素进行开方后取倒数的计算，公式如下：

![](images/atlasascendc_api_07_0030_img_001.png)

#### 函数原型

- tensor前n个数据计算

```
template <typename T, const RsqrtConfig& config = DEFAULT_RSQRT_CONFIG>
__aicore__ inline void Rsqrt(const LocalTensor<T>& dst, const LocalTensor<T>& src, const int32_t& count)
```

- tensor高维切分计算

  - mask逐bit模式

```
template <typename T, bool isSetMask = true, const RsqrtConfig& config = DEFAULT_RSQRT_CONFIG>
__aicore__ inline void Rsqrt(const LocalTensor<T>& dst, const LocalTensor<T>& src, uint64_t mask[], const uint8_t repeatTime, const UnaryRepeatParams& repeatParams)
```

  - mask连续模式

```
template <typename T, bool isSetMask = true, const RsqrtConfig& config = DEFAULT_RSQRT_CONFIG>
__aicore__ inline void Rsqrt(const LocalTensor<T>& dst, const LocalTensor<T>& src, uint64_t mask, const uint8_t repeatTime, const UnaryRepeatParams& repeatParams)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。                       Atlas 训练系列产品            ，支持的数据类型为：half、float。                       Atlas 推理系列产品            AI Core，支持的数据类型为：half、float。                       Atlas A2 训练系列产品            /             Atlas A2 推理系列产品            ，支持的数据类型为：half、float。                       Atlas A3 训练系列产品            /             Atlas A3 推理系列产品            ，支持的数据类型为：half、float。                       Atlas 200I/500 A2 推理产品            ，支持的数据类型为：half、float。          Atlas 350 加速卡，支持的数据类型为：half、float。 |
| isSetMask | 是否在接口内部设置mask。                     - true，表示在接口内部设置mask。           - false，表示在接口外部设置mask，开发者需要使用SetVectorMask接口设置mask值。这种模式下，本接口入参中的mask值必须设置为占位符MASK_PLACEHOLDER。 |
| 该参数仅支持Atlas 350 加速卡。          用于配置精度计算模式，RsqrtConfig类型，定义如下：                                                                                                                           ``` enum class RsqrtAlgo {     INTRINSIC = 0,     FAST_INVERSE,     PRECISION_1ULP_FTZ_TRUE,     PRECISION_0ULP_FTZ_FALSE,     PRECISION_1ULP_FTZ_FALSE, }; struct RsqrtConfig {     RsqrtAlgo algo = RsqrtAlgo::INTRINSIC; }; ```                                                                                      通过RsqrtConfig结构体的参数algo来配置精度计算模式。          algo取值如下：                     - RsqrtAlgo::INTRINSIC、RsqrtAlgo::PRECISION_1ULP_FTZ_TRUE，使用单指令计算得出结果，最大精度误差为1 ulp。           - RsqrtAlgo::FAST_INVERSE、RsqrtAlgo::PRECISION_0ULP_FTZ_FALSE，使用快速求逆算法得出结果。适用于输入值在[0, 85070596800837026223494223584045301760]范围内的计算。在该范围内，算法保证输出的最大精度误差为0 ulp；当输入值大于85070596800837026223494223584045301760时，输出为inf。目前，该算法支持float数据类型，并在该模式下支持Subnormal数据计算。           - RsqrtAlgo::PRECISION_1ULP_FTZ_FALSE，仅支持half类型的Subnormal数据计算，此时最大精度误差为1 ulp。                    该参数的默认值DEFAULT_RSQRT_CONFIG取值如下：                                                                                                                           ``` constexpr RsqrtConfig DEFAULT_RSQRT_CONFIG = { RsqrtAlgo::INTRINSIC }; ``` |  |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。          LocalTensor的起始地址需要32字节对齐。 |
| src | 输入 | 源操作数。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。          LocalTensor的起始地址需要32字节对齐。          源操作数的数据类型需要与目的操作数保持一致。 |
| count | 输入 | 参与计算的元素个数。 |
| mask[]/mask | 输入 | mask用于控制每次迭代内参与计算的元素。                     - 逐bit模式：可以按位控制哪些元素参与计算，bit位的值为1表示参与计算，0表示不参与。            mask为数组形式，数组长度和数组元素的取值范围和操作数的数据类型有关。当操作数为16位时，数组长度为2，mask[0]、mask[1]∈[0, 264-1]并且不同时为0；当操作数为32位时，数组长度为1，mask[0]∈(0, 264-1]；当操作数为64位时，数组长度为1，mask[0]∈(0, 232-1]。            例如，mask=[8, 0]，8=0b1000，表示仅第4个元素参与计算。                               - 连续模式：表示前面连续的多少个元素参与计算。取值范围和操作数的数据类型有关，数据类型不同，每次迭代内能够处理的元素个数最大值不同。当操作数为16位时，mask∈[1, 128]；当操作数为32位时，mask∈[1, 64]；当操作数为64位时，mask∈[1, 32]。 |
| repeatTime | 输入 | 重复迭代次数。矢量计算单元，每次读取连续的256Bytes数据进行计算，为完成对输入数据的处理，必须通过多次迭代（repeat）才能完成所有数据的读取与计算。repeatTime表示迭代的次数。          关于该参数的具体描述请参考高维切分API。 |
| repeatParams | 输入 | 控制操作数地址步长的参数。UnaryRepeatParams类型，包含操作数相邻迭代间相同DataBlock的地址步长，操作数同一迭代内不同DataBlock的地址步长等参数。          相邻迭代间的地址步长参数说明请参考repeatStride；同一迭代内DataBlock的地址步长参数说明请参考dataBlockStride。 |

#### 约束说明

- 如果src中的数值为非正数，可能会产生未知结果。
- 使用Rsqrt时，half的算子结果对比误差不满足双千分之一的要求，float的算子结果对比误差不满足双万分之一的要求，如果需要高精度，建议使用Div和Sqrt替代实现。

#### 调用示例

本样例的srcLocal和dstLocal均为half类型。

- tensor高维切分计算样例-mask连续模式

```
uint64_t mask = 256 / sizeof(half);
// repeatTime = 4, 128 elements one repeat, 512 elements total
// dstBlkStride, srcBlkStride = 1, no gap between blocks in one repeat
// dstRepStride, srcRepStride = 8, no gap between repeats
AscendC::Rsqrt(dstLocal, srcLocal, mask, 4, { 1, 1, 8, 8 });
```

- tensor高维切分计算样例-mask逐bit模式

```
uint64_t mask[2] = { UINT64_MAX, UINT64_MAX };
// repeatTime = 4, 128 elements one repeat, 512 elements total
// dstBlkStride, srcBlkStride = 1, no gap between blocks in one repeat
// dstRepStride, srcRepStride = 8, no gap between repeats
AscendC::Rsqrt(dstLocal, srcLocal, mask, 4, { 1, 1, 8, 8 });
```

- tensor前n个数据计算样例

```
AscendC::Rsqrt(dstLocal, srcLocal, 512);
// Rsqrt 0ulp
static constexpr RsqrtConfig config = { RsqrtAlgo::FAST_INVERSE };
Rsqrt<T, config>(dstLocal, srcLocal, 512);
// Rsqrt Subnormal
static constexpr RsqrtConfig config = { RsqrtAlgo::PRECISION_0ULP_FTZ_FALSE };
Rsqrt<T, config>(dstLocal, srcLocal, 512);
```

     结果示例如下：

```
输入数据srcLocal：[0.8335 2.2 2.672 ... 2.312 5.36]
输出数据dstLocal：[1.094 0.676 0.6113 ... 0.6562 0.4316]
```
