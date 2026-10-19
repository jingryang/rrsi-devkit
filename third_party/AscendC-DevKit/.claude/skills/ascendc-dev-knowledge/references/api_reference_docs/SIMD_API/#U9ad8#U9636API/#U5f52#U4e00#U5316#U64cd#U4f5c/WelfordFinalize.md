# WelfordFinalize

**页面ID:** atlasascendc_api_07_0814  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0814.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

Welford计算是一种在线计算均值和方差的方法。一方面，它可以在不存储所有样本的情况下，逐步计算所有样本的均值和方差，更适合处理海量数据；另一方面，它只需要对数据进行一次遍历，能减少访存次数，提高计算性能。本接口为Welford算法的后处理。

LayerNorm算法中Reduce轴较大的场景，可以通过切分Reduce轴，联合使用本接口与WelfordUpdate，能够实现等效计算LayerNorm。根据Reduce轴切分后是否有尾块，本接口分为如下两种计算公式：

- 不带尾块/不带counts参数场景：

![](images/atlasascendc_api_07_0814_img_001.png)

对于Atlas 350 加速卡，方差计算公式如下。

  - 方差系数未修正场景：

![](images/atlasascendc_api_07_0814_img_002.png)

  - 方差系数修正场景：

![](images/atlasascendc_api_07_0814_img_003.png)

其中，Mean为均值输出，Var为方差输出。

Meani代表输入的第i个均值，Vari代表输入的第i个方差。Ab代表Reduce轴切分后一次计算的大小，Rn代表Reduce轴按Ab拆分的次数，![](images/atlasascendc_api_07_0814_img_004.png)代表未修正的方差系数rRec，![](images/atlasascendc_api_07_0814_img_005.png)代表修正方差系数rRecWithCorrection。

- 带尾块/带counts参数场景：

![](images/atlasascendc_api_07_0814_img_006.png)

对于Atlas 350 加速卡，方差计算公式如下。

  - 方差系数未修正场景：

![](images/atlasascendc_api_07_0814_img_007.png)

  - 方差系数修正场景：

![](images/atlasascendc_api_07_0814_img_008.png)

除上述参数含义外，countsi代表Meani对应的系数，R代表未切分的原始Reduce轴长度，![](images/atlasascendc_api_07_0814_img_009.png)代表未修正的方差系数rRec，![](images/atlasascendc_api_07_0814_img_010.png)代表修正系数rRecWithCorrection。

#### 函数原型

- 通过sharedTmpBuffer入参传入临时空间

  - 不带counts参数场景

```
template <bool isReuseSource = false, const WelfordFinalizeConfig& config = WFFINALIZE_DEFAULT_CFG>
__aicore__ inline void WelfordFinalize(const LocalTensor<float>& outputMean, const LocalTensor<float>& outputVariance, const LocalTensor<float>& inputMean, const LocalTensor<float>& inputVariance, const LocalTensor<uint8_t>& sharedTmpBuffer, WelfordFinalizePara& para)
```

  - 带counts参数场景

```
template <bool isReuseSource = false, const WelfordFinalizeConfig& config = WFFINALIZE_DEFAULT_CFG>
__aicore__ inline void WelfordFinalize(const LocalTensor<float>& outputMean, const LocalTensor<float>& outputVariance, const LocalTensor<float>& inputMean, const LocalTensor<float>& inputVariance, const LocalTensor<int32_t>& counts, const LocalTensor<uint8_t>& sharedTmpBuffer, WelfordFinalizePara& para)
```

- 接口框架申请临时空间

  - 不带counts参数场景

```
template <bool isReuseSource = false, const WelfordFinalizeConfig& config = WFFINALIZE_DEFAULT_CFG>
__aicore__ inline void WelfordFinalize(const LocalTensor<float>& outputMean, const LocalTensor<float>& outputVariance, const LocalTensor<float>& inputMean, const LocalTensor<float>& inputVariance, WelfordFinalizePara& para)
```

  - 带counts参数场景

```
template <bool isReuseSource = false, const WelfordFinalizeConfig& config = WFFINALIZE_DEFAULT_CFG>
__aicore__ inline void WelfordFinalize(const LocalTensor<float>& outputMean, const LocalTensor<float>& outputVariance, const LocalTensor<float>& inputMean, const LocalTensor<float>& inputVariance, const LocalTensor<int32_t>& counts, WelfordFinalizePara& para)
```

由于该接口的内部实现中涉及复杂的计算，需要额外的临时空间来存储计算过程中的中间变量。临时空间支持**接口框架申请**和开发者**通过sharedTmpBuffer入参传入**两种方式。

- 接口框架申请临时空间，开发者无需申请，但是需要预留临时空间的大小。

- 通过sharedTmpBuffer入参传入，使用该tensor作为临时空间进行处理，接口框架不再申请。该方式开发者可以自行管理sharedTmpBuffer内存空间，并在接口调用完成后，复用该部分内存，内存不会反复申请释放，灵活性较高，内存利用率也较高。

接口框架申请的方式，开发者需要预留临时空间；通过sharedTmpBuffer传入的情况，开发者需要为tensor申请空间。临时空间大小BufferSize的获取方式如下：通过WelfordFinalize Tiling中提供的GetWelfordFinalizeMaxMinTmpSize接口获取所需最大和最小临时空间大小，最小空间可以保证功能正确，最大空间用于提升性能。

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| isReuseSource | 该参数预留，传入默认值false即可。 |
| 该参数仅支持Atlas 350 加速卡。 结构体模板参数，用于配置相关信息，WelfordFinalizeConfig类型，具体定义如下： ``` struct WelfordFinalizeConfig {      bool isCorrection = false; } ```  - isCorrection：计算方差时，是否使用修正系数，取值如下：  - false：不使用修正系数，即方差系数为rRec。  - true：使用修正系数rRecWithCorrection。  配置示例如下。 ``` constexpr WelfordFinalizeConfig WFFINALIZE_DEFAULT_CFG = { false }; ``` |  |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| outputMean | 输出 | 均值目的操作数，数据类型为float。输出的均值为1个数，需要sizeof(float)大小的空间进行保存，根据存储单元的对齐要求，开发者实际需要为outputMean分配32字节对齐的内存空间。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| outputVariance | 输出 | 方差目的操作数，数据类型为float。输出的方差为1个数，需要sizeof(float)大小的空间进行保存，根据存储单元的对齐要求，开发者实际需要为outputVariance分配32字节对齐的内存空间。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| inputMean | 输入 | 均值源操作数，数据类型为float。shape为[abLength]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| inputVariance | 输入 | 方差源操作数，数据类型为float。shape为[abLength]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| counts | 输入 | 源操作数，数据类型为int32_t。shape为[abLength]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| sharedTmpBuffer | 输入 | 临时空间，数据类型为uint8_t。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 接口内部复杂计算时用于存储中间变量，由开发者提供。 临时空间大小BufferSize的获取方式请参考WelfordFinalize Tiling。 |
| 计算所需的参数信息。WelfordFinalizePara类型，定义如下。 ``` struct WelfordFinalizePara {     uint32_t rnLength;     uint32_t abLength;     uint32_t headCount;     uint32_t headCountLength;     uint32_t tailCount;     uint32_t tailCountLength;     float abRec;     float rRec;     float rRecWithCorrection; }; ```  - rnLength：输入的Reduce轴，按abLength为一次计算的大小，拆分的次数。如果拆分后有尾块，则次数向上取整。- abLength：Reduce轴拆分的大小。在不带counts参数的接口中，abLength=headCountLength+tailCountLength。- headCount：在不带counts参数的接口中使能该参数，作为公式中非尾块的counts系数，headCount值。- headCountLength：在不带counts参数的接口中使能该参数，headCount值对应的长度。- tailCount：在不带counts参数的接口中使能该参数，作为公式中尾块的counts系数，tailCount值。- tailCountLength：在不带counts参数的接口中使能该参数，tailCount值对应的长度。- abRec：abLength的倒数，即为1/abLength的值。- rRec：输入的Reduce轴拆分后，若没有尾块，表示1/(rnLength*abLength)的值，若有尾块，表示1/R的值。- rRecWithCorrection：输入的方差修正系数，当模板参数config中的isCorrection为true时生效。该参数仅支持Atlas 350 加速卡。 |  |  |

#### 约束说明

- 接口参数para.abLength的取值必须为32/sizeof(float)的整数倍。
- 接口参数para.headCountLength与para.tailCountLength的和必须等于参数para.abLength。
- 接口处理逻辑以参数para中设置的具体参数值为准，不依赖源操作数的shape信息。
- 接口参数para.tailCount为0时，禁止配置para.tailCountLength为非0值。
- 不支持源操作数与目的操作数地址重叠。
- 不支持sharedTmpBuffer与源操作数和目的操作数地址重叠。

#### 调用示例

完整的调用样例可参考[WelfordFinalize样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/02_normalization/welford_finalize)。

```
pipe.InitBuffer(sharedTmpBuffer, stackBufferSize);        
AscendC::LocalTensor<uint8_t> tmpLocalTensor = sharedTmpBuffer.Get<uint8_t>();         
struct AscendC::WelfordFinalizePara para = {rnLength, abLength, head, headLength, tail, tailLength, abRec, rRec};
AscendC::WelfordFinalize<false>(meanLocal, varianceLocal, inputMeanLocal, inputVarianceLocal, inputCountsLocal, tmpLocalTensor, para);
```

```
// meanLocal：均值目的操作数
// varianceLocal：方差目的操作数
// inmeanLocal：均值源操作数
// invarLocal：方差源操作数
// inputXLocal：源操作数
// para：计算所需参数信息，WelfordFinalizePara类型

// 计算方差时不使用修正系数
static constexpr AscendC::WelfordFinalizeConfig CONFIG = {false};
AscendC::WelfordFinalizePara para = { rnLength, abLength, head, headLength, tail, tailLength, abRec, rRec, rRecWithCorrection};
AscendC::WelfordFinalize<false, CONFIG>(meanLocal, varianceLocal, inmeanLocal, invarLocal, inputXLocal, para);
```

示例结果如下：

```
输入数据(inmeanLocal, shape:[1, 32]): 
[  0.0  1.0  2.0  3.0  4.0  5.0  6.0  7.0  8.0  9.0 10.0 11.0 12.0 13.0 14.0 15.0 
  16.0 17.0 18.0 19.0 20.0 21.0 22.0 23.0 24.0 25.0 26.0 27.0 28.0 29.0 30.0 31.0 ]
输入数据(invarLocal, shape:[1, 32]): 
[  0.0  1.0  2.0  3.0  4.0  5.0  6.0  7.0  8.0  9.0 10.0 11.0 12.0 13.0 14.0 15.0 
  16.0 17.0 18.0 19.0 20.0 21.0 22.0 23.0 24.0 25.0 26.0 27.0 28.0 29.0 30.0 31.0 ]
输入数据(inputX, shape:[1, 32]): 
[ 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 4 ]
输出数据(meanLocal): 
[ 0.484375 0.       0.       0.       0.       0.       0.       0.      ]
输出数据(varianceLocal): 
[ 9.831062 0.       0.       0.       0.       0.       0.       0.      ]
```
