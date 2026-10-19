# Dequantize

**页面ID:** atlasascendc_api_07_10164  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10164.html

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

按元素做反量化计算，比如将int32_t数据类型反量化为half/float等数据类型。**本接口最多支持输入为二维数据，不支持更高维度的输入。**

Dequantize与AscendDequant的功能类似，本接口在不同量化场景下的形式更统一，因此推荐使用本接口。

本接口的反量化策略包括PER_TENSOR，PER_CHANNEL，PER_TOKEN，PER_GROUP四种，反量化系数scale在PER_TENSOR场景下为标量，其余场景下为矢量，具体计算公式如下：

- PER_TENSOR场景 （按张量反量化）：scale和offset的shape为[1]。

![](images/atlasascendc_api_07_10164_img_001.png)

- PER_CHANNEL场景 （按通道反量化）：srcTensor的shape为[m, n]，每个channel维度对应一个量化参数，scale和offset的shape为[1, n]。

![](images/atlasascendc_api_07_10164_img_002.png)

- PER_TOKEN场景 （按token反量化）：srcTensor的每组token（token为n方向，共有m组token）中的元素共享一个量化参数，srcTensor的shape为[m, n]时，scale和offset的shape为[m, 1]。

![](images/atlasascendc_api_07_10164_img_003.png)

- PER_GROUP场景 （按组反量化）：定义group的计算方向为k方向，srcTensor在k方向上每groupSize个元素共享一组scale和offset。srcTensor的shape为[m, n]时，如果kDim=0，表示k是m方向，scale和offset的shape为[(m + groupSize - 1) / groupSize, n]；如果kDim=1，表示k是n方向，scale和offset的shape为[m，(n + groupSize - 1) / groupSize]。

  - k为m方向，即公式中i轴为group的计算方向（kDim=0）：

![](images/atlasascendc_api_07_10164_img_004.png)

  - k为n方向，即公式中j轴为group的计算方向（kDim=1）：

![](images/atlasascendc_api_07_10164_img_005.png)

#### 函数原型

- 通过sharedTmpBuffer入参传入临时空间

```
template <const DequantizeConfig& config, typename DstT, typename SrcT, typename ScaleT, typename OffsetT>
__aicore__ inline void Dequantize(const LocalTensor<DstT>& dstTensor, const LocalTensor<SrcT>& srcTensor, const ScaleT& scale, const OffsetT& offset, const LocalTensor<uint8_t>& sharedTmpBuffer, const DequantizeParams& params)
```

- 接口框架申请临时空间

```
template <const DequantizeConfig& config, typename DstT, typename SrcT, typename ScaleT, typename OffsetT>
__aicore__ inline void Dequantize(const LocalTensor<DstT>& dstTensor, const LocalTensor<SrcT>& srcTensor, const ScaleT& scale, const OffsetT& offset, const DequantizeParams& params)
```

由于该接口的内部实现中涉及复杂的数学计算，需要额外的临时空间来存储计算过程中的中间变量。临时空间支持**接口框架申请**和开发者**通过sharedTmpBuffer入参传入**两种方式。

  - 接口框架申请临时空间，开发者无需申请，但是需要预留临时空间的大小。

  - 通过sharedTmpBuffer入参传入，使用该tensor作为临时空间进行处理，接口框架不再申请。该方式开发者可以自行管理sharedTmpBuffer内存空间，并在接口调用完成后，复用该部分内存，内存不会反复申请释放，灵活性较高，内存利用率也较高。

接口框架申请的方式，开发者需要预留临时空间；通过sharedTmpBuffer传入的情况，开发者需要为sharedTmpBuffer申请空间。临时空间大小BufferSize的获取方式如下：通过GetDequantizeMaxMinTmpSize中提供的GetDequantizeMaxMinTmpSize接口获取需要预留空间的范围大小。

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| 用于配置反量化相关信息，DequantizeConfig类型，具体定义如下。 ``` struct DequantizeConfig {     DequantizePolicy policy;     bool hasOffset = false;     int32_t kDim = 1; } ```  - policy：用于配置量化策略，枚举类型，具体定义如下。``` enum class DequantizePolicy : int32_t {     PER_TENSOR,     PER_CHANNEL,     PER_TOKEN,     PER_GROUP } ```   - hasOffset：预留参数，目前仅支持配置为false。- kDim：group的计算方向，即k方向。仅在PER_GROUP场景有效，支持的取值如下。  - 0：k轴是第0轴，即m方向为group的计算方向。  - 1：k轴是第1轴，即n方向为group的计算方向。 |  |
| DstT | 目的操作数的数据类型。接口内根据入参dstTensor自动推导数据类型，开发者无需配置该参数，保证dstTensor满足表3 输入输出支持的数据类型组合即可。 |
| SrcT | 源操作数的数据类型。接口内根据入参srcTensor自动推导数据类型，开发者无需配置该参数，保证srcTensor满足表3 输入输出支持的数据类型组合即可。 |
| ScaleT | scale的数据类型。接口内根据入参scale自动推导数据类型，开发者无需配置该参数。ScaleT可以为标量数据类型或LocalTensor类型。 注意： - 对于PER_TENSOR场景，scale为标量，ScaleT只能为标量数据类型。- 对于PER_CHANNEL、PER_TOKEN、PER_GROUP场景，scale为矢量，ScaleT只能为LocalTensor类型。 |
| OffsetT | offset的数据类型。接口内根据入参offset自动推导数据类型，开发者无需配置该参数。OffsetT可以为标量数据类型或LocalTensor类型。 注意： - 对于PER_TENSOR量化策略，offset为标量，OffsetT只能为标量数据类型。- 对于PER_CHANNEL、PER_TOKEN、PER_GROUP量化策略，offset为矢量，OffsetT只能为LocalTensor类型。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstTensor | 输出 | 目的操作数。类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| srcTensor | 输入 | 源操作数。类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 假设srcTensor的shape为[m, n]，每行数据（即n个输入数据）所占字节数要求**32字节对齐**。 |
| scale | 输入 | 输入数据反量化时的缩放因子。 |
| offset | 输入 | 输入数据反量化时的偏移量。当前为预留参数，可配置为0或空Tensor。 |
| sharedTmpBuffer | 输入 | 临时缓存。类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 临时空间大小BufferSize的获取方式请参考GetDequantizeMaxMinTmpSize。 |
| 反量化接口的参数，DequantizeParams类型，定义如下。 ``` struct DequantizeParams {         uint32_t m;         uint32_t n;         uint32_t groupSize = 0; } ```  - m：m方向元素个数。- n：n方向元素个数。n值对应的数据大小需满足32字节对齐的要求，即shape最后一维为n的输入或输出均需要满足该维度上32字节对齐的要求。- groupSize：PER_GROUP场景有效，表示groupSize行/列数据共用一个scale。groupSize的取值必须大于0且是32的整倍数。 |  |  |

**表3 **输入输出支持的数据类型组合

| 量化策略 | dstTensor | srcTensor | scale/offset |
| --- | --- | --- | --- |
| PER_TENSOR | bfloat16_t | int32_t | bfloat16_t |
| bfloat16_t | int32_t | float |  |
| float | int32_t | bfloat16_t |  |
| float | int32_t | float |  |
| PER_CHANNEL | half | int32_t | uint64_t 注意：当scale的数据类型是uint64_t时，其中的低32位数据是参与计算的float类型数据，高32位本接口不使用。 |
| float | int32_t | float |  |
| float | int32_t | bfloat16_t |  |
| bfloat16_t | int32_t | bfloat16_t |  |
| bfloat16_t | int32_t | float |  |
| PER_TOKEN/PER_GROUP | half | int32_t | half |
| bfloat16_t | int32_t | bfloat16_t |  |
| float | int32_t | float |  |
| half | int32_t | float |  |
| bfloat16_t | int32_t | float |  |
| half | float | half |  |
| bfloat16_t | float | bfloat16_t |  |
| float | float | float |  |
| half | float | float |  |
| bfloat16_t | float | float |  |

#### 约束说明

- **不支持源操作数与目的操作数地址重叠。**

- 连续计算方向（即n方向）的数据量要求32字节对齐。

#### 调用示例

- PER_CHANNEL、PER_TOKEN、PER_GROUP模式

```
constexpr static DequantizePolicy tokenPolicy = DequantizePolicy::PER_TOKEN; 
constexpr static DequantizePolicy channelPolicy = DequantizePolicy::PER_CHANNEL;
constexpr static DequantizePolicy groupPolicy = DequantizePolicy::PER_GROUP;
// 此处以PER_CHANNEL模式为例，不使能offset；kDim仅PER_GROUP场景有效，表示group计算方向为n方向
constexpr static DequantizeConfig config = {channelPolicy, false, 1};
DequantizeParams params;
// m,n为外部传入参数，表示srcLocal实际参与的m、n方向的元素个数
params.m = m;
params.n = n;
params.groupSize = n;  // 仅PER_GROUP场景下生效，此处表示n方向所有元素共享一组scale和offset
// srcLocal为int32_t类型的LocalTensor，dstLocal、scaleLocal、offsetLocal为float类型的LocalTensor
Dequantize<config>(dstLocal, srcLocal, scaleLocal, offsetLocal, params);  // offsetLocal为预留参数，可配置为空Tensor;
```

- PER_TENSOR模式

```
constexpr static DequantizePolicy tensorPolicy = DequantizePolicy::PER_TENSOR;
// 不使能offset
constexpr static DequantizeConfig config = {tensorPolicy, false, -1};
DequantizeParams params;
// m,n为外部传入参数，表示srcLocal实际参与的m、n方向的元素个数
params.m = m;
params.n = n;
params.groupSize = 0;  // 仅PER_GROUP场景下生效
// srcLocal为int32_t类型的LocalTensor，dstLocal为float类型的LocalTensor，scale、offset为float类型的标量
Dequantize<config>(dstLocal, srcLocal, scale, offset, params);  // offset为预留参数，可配置为0;
```

结果示例如下：

```
输入数据（srcLocal）: 
[-4, 2, -2, -3, -1, -4, 1, 3, 4, 1, -2, 0, ... 1]
输入数据（scale矢量）: 
[1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, ... 1]
输入数据（scale标量）:
[1]
输出数据（dstLocal），此时dstLocal = srcLocal: 
[-4, 2, -2, -3, -1, -4, 1, 3, 4, 1, -2, 0, ... 1]
```
