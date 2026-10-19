# Quantize

**页面ID:** atlasascendc_api_07_10168  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10168.html

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

按元素做量化计算，将高精度数据转换为低精度数据。本接口的量化策略包括PER_TENSOR，PER_CHANNEL，PER_TOKEN和PER_GROUP四种，每种量化策略均支持配置舍入模式。**本接口最多支持输入为二维数据，不支持更高维度的输入。**

Quantize与AscendQuant的功能类似，Quantize在PER_TENSOR、PER_CHANNEL量化场景，扩展了配置舍入模式的功能，因此推荐使用本接口。

- PER_TENSOR量化：整个srcTensor对应一个量化参数，scale和offset的shape为[1]。

![](images/atlasascendc_api_07_10168_img_001.png)

- PER_CHANNEL量化：srcTensor的shape为[m, n]，每个channel维度对应一个量化参数，scale和offset的shape为[1, n]。

![](images/atlasascendc_api_07_10168_img_002.png)

- PER_TOKEN量化：srcTensor的每组token（token为n方向，共有m组token）中的元素共享一个量化参数，srcTensor的shape为[m, n]时，scale和offset的shape为[m, 1]。

![](images/atlasascendc_api_07_10168_img_003.png)

- PER_GROUP量化：定义group的计算方向为k方向，srcTensor在k方向上每groupSize个元素共享一组scale和offset。srcTensor的shape为[m, n]时，如果kDim=0，表示k是m方向，scale和offset的shape为[(m + groupSize - 1) / groupSize, n]；如果kDim=1，表示k是n方向，scale和offset的shape为[m，(n + groupSize - 1) / groupSize]。根据输出数据类型的不同，PER_GROUP量化分为两种场景：fp4x2_e2m1_t/fp4x2_e1m2_t场景（后续内容中简称为float4场景）和int8_t/hifloat8_t/fp8_e5m2_t/fp8_e4m3fn_t场景（后续内容中简称为b8场景）。

  - fp4x2_e2m1_t/fp4x2_e1m2_t场景（float4场景）

    - kDim = 0:

![](images/atlasascendc_api_07_10168_img_004.png)

    - kDim = 1:

![](images/atlasascendc_api_07_10168_img_005.png)

  - int8_t/hifloat8_t/fp8_e5m2_t/fp8_e4m3fn_t场景（b8场景）

    - kDim = 0：

![](images/atlasascendc_api_07_10168_img_006.png)

    - kDim = 1:

![](images/atlasascendc_api_07_10168_img_007.png)

#### 函数原型

- 通过sharedTmpBuffer入参传入临时空间

```
template <const QuantizeConfig& config, typename DstT, typename SrcT, typename ScaleT, typename OffsetT>
__aicore__ inline void Quantize(const LocalTensor<DstT>& dstTensor, const LocalTensor<SrcT>& srcTensor, const LocalTensor<uint8_t>& sharedTmpBuffer, const ScaleT& scale, const OffsetT& offset, const QuantizeParams& params)
```

- 接口框架申请临时空间

```
template <const QuantizeConfig& config, typename DstT, typename SrcT, typename ScaleT, typename OffsetT>
__aicore__ inline void Quantize(const LocalTensor<DstT>& dstTensor, const LocalTensor<SrcT>& srcTensor,const ScaleT& scale, const OffsetT& offset, const QuantizeParams& params)
```

由于该接口的内部实现中涉及复杂的数学计算，需要额外的临时空间来存储计算过程中的中间变量。临时空间支持**接口框架申请**和开发者**通过sharedTmpBuffer入参传入**两种方式。

- 接口框架申请临时空间，开发者无需申请，但是需要预留临时空间的大小。

- 通过sharedTmpBuffer入参传入，使用该tensor作为临时空间进行处理，接口框架不再申请。该方式开发者可以自行管理sharedTmpBuffer内存空间，并在接口调用完成后，复用该部分内存，内存不会反复申请释放，灵活性较高，内存利用率也较高。

接口框架申请的方式，开发者需要预留临时空间；通过sharedTmpBuffer传入的情况，开发者需要为sharedTmpBuffer申请空间。临时空间大小BufferSize的获取方式如下：通过GetQuantizeMaxMinTmpSize中提供的接口获取需要预留空间的范围大小。

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| 用于配置量化计算相关信息，QuantizeConfig类型，具体定义如下。 ``` struct QuantizeConfig {     QuantizePolicy policy;     bool hasOffset;     RoundMode roundMode = RoundMode::CAST_RINT;     int32_t kDim = 1;  } ```  - policy：用于配置量化策略，枚举类型，具体定义如下。``` enum class QuantizePolicy : int32_t {     PER_TENSOR,     PER_CHANNEL,     PER_TOKEN,     PER_GROUP } ```  - hasOffset：用于配置offset是否参与计算。  - true：表示offset参与计算。  - false：表示offset不参与计算。 - roundMode：量化过程中，数据由高精度数据类型转换为低精度数据类型的舍入模式，支持的取值有：CAST_RINT、CAST_ROUND、CAST_FLOOR、CAST_CEIL、CAST_TRUNC、CAST_HYBRID，各个舍入模式的详细介绍请参考精度转换规则。不同数据类型的量化支持不同的舍入模式，当量化过程中使用了不支持的舍入模式时，将回退到默认的舍入模式；例如，bfloat16_t数据类型量化为hifloat8_t数据类型时，如果配置的roundMode为不支持的CAST_RINT，实际执行量化时将回退到默认的roundMode（CAST_ROUND）。不同数据类型支持的舍入模式请见表3。- kDim：group的计算方向，即k方向。仅在PER_GROUP场景有效，支持的取值如下：  - 0：k轴是第0轴，即m方向为group的计算方向。  - 1：k轴是第1轴，即n方向为group的计算方向。 |  |
| DstT | 目的操作数的数据类型。接口内根据入参dstTensor自动推导数据类型，开发者无需配置该参数，保证dstTensor满足表3 输入输出支持的数据类型组合即可。 |
| SrcT | 源操作数的数据类型。接口内根据入参srcTensor自动推导数据类型，开发者无需配置该参数，保证srcTensor满足表3 输入输出支持的数据类型组合即可。 |
| ScaleT | 缩放因子scale的数据类型。接口内根据入参scale自动推导数据类型，开发者无需配置该参数。ScaleT可以为标量数据类型或LocalTensor类型。 注意： - 对于PER_TENSOR量化策略，scale为标量，ScaleT只能为标量数据类型。- 对于PER_CHANNEL、PER_TOKEN、PER_GROUP量化策略，scale为矢量，ScaleT只能为LocalTensor类型。 |
| OffsetT | offset的数据类型。接口内根据入参offset自动推导数据类型，开发者无需配置该参数。OffsetT可以为标量数据类型或LocalTensor类型。 注意： - 对于PER_TENSOR量化策略，offset为标量，OffsetT只能为标量数据类型。- 对于PER_CHANNEL、PER_TOKEN、PER_GROUP量化策略，offset可以是标量或者矢量，OffsetT可以为标量数据类型，也可以为LocalTensor类型。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstTensor | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| srcTensor | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| scale | 输入 | 输入数据量化时的缩放因子。 |
| offset | 输入 | 输入数据量化时的偏移量。 Atlas 350 加速卡，对于PER_GROUP量化的float4场景，offset不生效。 |
| sharedTmpBuffer | 输入 | 临时缓存。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 临时空间大小BufferSize的获取方式请参考GetQuantizeMaxMinTmpSize。 |
| 量化接口的参数，QuantizeParams类型，具体定义如下。 ``` struct QuantizeParams {         uint32_t m;         uint32_t n;         uint32_t groupSize = 0; } ```  - m：m方向元素个数。- n：n方向元素个数。n值对应的数据大小需满足32字节对齐的要求，即shape最后一维为n的输入或输出均需要满足该维度上32字节对齐的要求。- groupSize：PER_GROUP场景有效，表示groupSize行/列数据共用一个scale/offset。groupSize的取值必须大于0且是32的整倍数。 |  |  |

**表3 **输入输出支持的数据类型组合

| SrcT | ScaleT/OffsetT | DstT | roundMode |
| --- | --- | --- | --- |
| half | half | fp8_e5m2_t/fp8_e4m3fn_t | - CAST_RINT(默认) |
| bfloat16_t | bfloat16_t |  |  |
| float | float |  |  |
| half | float |  |  |
| bfloat16_t | float |  |  |
| half | half | hifloat8_t | - CAST_ROUND(默认)- CAST_HYBRID |
| bfloat16_t | bfloat16_t |  |  |
| float | float |  |  |
| half | float |  |  |
| bfloat16_t | float |  |  |
| half | half | int8_t | - CAST_RINT(默认)- CAST_ROUND- CAST_FLOOR- CAST_CEIL- CAST_TRUNC |
| bfloat16_t | bfloat16_t |  |  |
| float | float |  |  |
| half | float |  |  |
| bfloat16_t | float |  |  |
| half | half | fp4x2_e1m2_t/fp4x2_e2m1_t （当前均只支持PER_GROUP场景） |  |
| bfloat16_t | bfloat16_t |  |  |
| float | float |  |  |
| half | float |  |  |
| bfloat16_t | float |  |  |

#### 约束说明

- **不支持源操作数与目的操作数地址重叠。**

- 输入输出操作数参与计算的数据长度要求32字节对齐。
- 连续计算方向（即n方向）的数据量要求32字节对齐。
- PER_GROUP量化的float4场景不支持offset，该场景下模板参数config中的hasOffset参数必须配置为false。

#### 调用示例

- PER_CHANNEL、PER_TOKEN、PER_GROUP模式

```
constexpr static QuantizePolicy tokenPolicy = QuantizePolicy::PER_TOKEN;
constexpr static QuantizePolicy channelPolicy = QuantizePolicy::PER_CHANNEL;
constexpr static QuantizePolicy groupPolicy = QuantizePolicy::PER_GROUP;
// 此处以PER_TOKEN模式为例，使能offset，舍入模式为CAST_ROUND；kDim仅PER_GROUP场景有效，表示group计算方向为n方向
constexpr static QuantizeConfig config = {tokenPolicy, true, RoundMode::CAST_ROUND, 1};
QuantizeParams params;
// m,n为外部传入参数，表示srcLocal实际参与的m、n方向的元素个数
params.m = m;
params.n = n;
params.groupSize = n; // 仅PER_GROUP场景有效，此处表示n方向所有元素共享一组scale和offset
// dstLocal为int8_t类型的LocalTensor，srcLocal、scale、offset为half类型的LocalTensor
Quantize<config>(dstLocal, srcLocal, scale, offset, params);
```

- PER_TENSOR模式

```
constexpr static QuantizePolicy tensorPolicy = QuantizePolicy::PER_TENSOR;
// 使能offset，舍入模式为CAST_ROUND
constexpr static QuantizeConfig config = {tensorPolicy, true, RoundMode::CAST_ROUND, -1};
QuantizeParams params;
// m,n为外部传入参数，表示srcLocal实际参与的m、n方向的元素个数
params.m = m;
params.n = n;
params.groupSize = 0; // 仅PER_GROUP场景有效
// dstLocal为int8_t类型的LocalTensor，srcLocal为half类型的LocalTensor，scale、offset为half类型的标量
Quantize<config>(dstLocal, srcLocal, scale, offset, params);
```

结果示例如下：

```
输入数据（srcLocal）: 
[-4.4, 2.5, -2.9, -3.1, -1.5, -4.8, 1.8, 3.5, 4.5, 1.1, -2.7, 0.5, ... 1.6]
输入数据（scale矢量）: 
[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, ... 1]
输入数据（scale标量）:
[1]
输入数据（offset矢量）: 
[0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, ... 0]
输入数据（offset标量）: 
[0]
输出数据（dstLocal）: 
[-4, 3, -3, -3, -1, -5, 2, 4, 5, 1, -3, 1, ... 2]
```
