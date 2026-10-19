# Transpose

**页面ID:** atlasascendc_api_07_0865  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0865.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品            AI Core | √ |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

对输入数据进行数据排布及Reshape操作，具体功能如下：

【场景1：NZ2ND，1、2轴互换】

输入Tensor { shape:[B, N, H/N/16, S/16, 16, 16], origin_shape:[B, N, S, H/N], format:"NZ", origin_format:"ND"}

输出Tensor { shape:[B, S, N, H/N], origin_shape:[B, S, N, H/N], format:"ND", origin_format:"ND"}

**图1 **场景1数据排布变换
![](images/atlasascendc_api_07_0865_img_001.png)

【场景2：NZ2NZ，1、2轴互换】

输入Tensor { shape:[B, N, H/N/16, S/16, 16, 16], origin_shape:[B, N, S, H/N], format:"NZ", origin_format:"ND"}

输出Tensor { shape:[B, S, H/N/16, N/16, 16, 16], origin_shape:[B, S, N, H/N], format:"NZ", origin_format:"ND"}

**图2 **场景2数据排布变换
![](images/atlasascendc_api_07_0865_img_002.png)

【场景3：NZ2NZ，尾轴切分】

输入Tensor { shape:[B, H / 16, S / 16, 16, 16], origin_shape:[B, S, H], format:"NZ", origin_format:"ND"}

输出Tensor { shape:[B, N, H/N/16, S / 16, 16, 16], origin_shape:[B, N, S, H/N], format:"NZ", origin_format:"ND"}

**图3 **场景3数据排布变换
![](images/atlasascendc_api_07_0865_img_003.png)

【场景4：NZ2ND，尾轴切分】

输入Tensor { shape:[B, H / 16, S / 16, 16, 16], origin_shape:[B, S, H], format:"NZ", origin_format:"ND"}

输出Tensor { shape:[B, N, S, H/N], origin_shape:[B, N, S, H/N], format:"ND", origin_format:"ND"}

**图4 **场景4数据排布变换
![](images/atlasascendc_api_07_0865_img_004.png)

【场景5：NZ2ND，尾轴合并】

输入Tensor { shape:[B, N, H/N/16, S/16, 16, 16], origin_shape:[B, N, S, H/N], format:"NZ", origin_format:"ND"}

输出Tensor { shape:[B, S, H], origin_shape:[B, S, H], format:"ND", origin_format:"ND"}

**图5 **场景5数据排布变换
![](images/atlasascendc_api_07_0865_img_005.png)

【场景6：NZ2NZ，尾轴合并】

输入Tensor { shape:[B, N, H/N/16, S/16, 16, 16], origin_shape:[B, N, S, H/N], format:"NZ", origin_format:"ND"}

输出Tensor { shape:[B, H/16, S/16, 16, 16], origin_shape:[B, S, H], format:"NZ", origin_format:"ND"}

**图6 **场景6数据排布变换
![](images/atlasascendc_api_07_0865_img_006.png)

【场景7：二维转置】

支持在UB上对二维Tensor进行转置，其中srcShape中的H、W均是16的整倍。

**图7 **场景7数据排布变换
![](images/atlasascendc_api_07_0865_img_007.png)

【场景13：二维转置或者三维的后两维转置】

支持在UB上对二维Tensor进行转置或者对三维Tensor的最后两维进行转置，二维Tensor转置同场景7的数据排布变换。

**图8 **场景13三维Tensor数据排布变换
![](images/atlasascendc_api_07_0865_img_008.png)

【场景14：三维中的第一维和第二维互换】

支持在UB上对三维Tensor中的第一维和第二维互换。

**图9 **场景14三维Tensor的数据排布变换
![](images/atlasascendc_api_07_0865_img_009.png)

【场景15：三维中的第一维和第三维互换】

支持在UB上对三维Tensor中的第一维和第三维互换。

**图10 **场景15三维Tensor的数据排布变换
![](images/atlasascendc_api_07_0865_img_010.png)

【场景16：使用交织指令进行两维ND2NZ转置】

支持在UB上使用交织指令对二维ND Tensor转置为NZ。

**图11 **场景16使用交织指令的ND2NZ转置
![](images/atlasascendc_api_07_0865_img_011.png)

#### 实现原理

对应Transpose的11种功能场景，每种功能场景的算法框图如图所示。

**图12 **场景1：NZ2ND，1、2轴互换
![](images/atlasascendc_api_07_0865_img_012.png)

计算过程分为如下几步：

先后沿H/N方向，N方向，B方向循环处理：

1. 第1次TransDataTo5HD步骤：沿S方向转置S/16个连续的16*16的方形到temp中，在temp中每个方形与方形之间连续存储；
2. 第2次TransDataTo5HD步骤：将temp中S/16个16*16的方形转置到dst中，在dst中是ND格式，来自同一个方形的连续2行数据在目的操作数上的地址偏移(H/N)*N个元素，沿H方向的每2个方形的同一行数据在目的操作数上的地址偏移16个元素。

**图13 **场景2：NZ2NZ，1、2轴互换
![](images/atlasascendc_api_07_0865_img_013.png)

计算过程分为如下几步：

先后沿H/N方向，N方向，B方向循环处理：

1. 第1次TransDataTo5HD步骤：沿S方向分别取S/16个连续的16*16的方形到temp中，在temp中每个方形与方形之间连续存储；
2. 第2次TransDataTo5HD步骤：将temp中S/16个16*16的方形转置到dst中，在dst中是NZ格式，来自同一个方形的连续2行数据在目的操作数上的地址偏移(H/N)*N个元素，沿H方向的每2个方形的同一行数据在目的操作数上的地址偏移N*16个元素。

**图14 **场景3：NZ2NZ，尾轴切分
![](images/atlasascendc_api_07_0865_img_014.png)

计算过程分为如下几步：

先后沿H方向，B方向循环处理：

1. 第1次TransDataTo5HD步骤：每次转置S/16个连续的16*16的方形到temp1中；
2. DataCopy步骤：当H/N<=16时，每次搬运H/N*S个元素到temp2中；当H/N>16时，前H/N/16次搬运16*S个元素到temp2中，最后一次搬运H/N%16*S个元素到temp2中；
3. 第2次TransDataTo5HD步骤：将temp2中的16*S的方形转置到dst中，在dst中是NZ格式，来自同一个方形的连续2行数据在目的操作数上的地址偏移16个元素，沿H方向的每2个方形的同一行数据在目的操作数上的地址偏移S*16个元素。

**图15 **场景4：NZ2ND，尾轴切分
![](images/atlasascendc_api_07_0865_img_015.png)

计算过程分为如下几步：

先后沿H方向，B方向循环处理：

1. 第1次TransDataTo5HD步骤：每次转置S/16个连续的16*16的方形到temp1中；
2. DataCopy步骤：当H/N<=16时，每次搬运H/N*S个元素到temp2中；当H/N>16时，前H/N/16次搬运16*S个元素到temp2中，最后一次搬运H/N%16*S个元素到tmp2中；
3. 第2次TransDataTo5HD步骤：将temp2中的数据转置到dst中，在dst中是ND格式，来自同一个方形的连续2行数据在目的操作数上的地址偏移(H/N+16-1)/16*16个元素，沿H方向的每2个方形的同一行数据在目的操作数上的地址偏移(H/N+16-1)/16*16*S个元素。

**图16 **场景5：NZ2ND，尾轴合并
![](images/atlasascendc_api_07_0865_img_016.png)

计算过程分为如下几步：

先后沿H方向，B方向循环处理：

1. 第1次TransDataTo5HD步骤：每次转置一个S*16的方形到temp1中；
2. DataCopy步骤：当H/N<=16时，每次搬运H/N*S个元素到temp2中；当H/N>16时，前H/N/16次搬运16*S个元素到temp2中，最后一次搬运H/N%16*S个元素到tmp2中；
3. 第2次TransDataTo5HD步骤：将temp2中的16*S的方形转置到dst中，在dst中是ND格式，来自同一个方形的连续2行数据在目的操作数上的地址偏移(H+16-1)/16*16个元素，沿H方向的每2个方形的同一行数据在目的操作数上的地址偏移H/N*S个元素。

**图17 **场景6：NZ2NZ，尾轴合并
![](images/atlasascendc_api_07_0865_img_017.png)

计算过程分为如下几步：

先后沿H方向，B方向循环处理：

1. 第1次TransDataTo5HD步骤：每次转置一个S*16的方形到temp1中；
2. DataCopy步骤：当H/N<=16时，每次搬运H/N*S个元素到temp2中；当H/N>16时，前H/N/16次搬运16*S个元素到temp2中，最后一次搬运H/N%16*S个元素到tmp2中；
3. 第2次TransDataTo5HD步骤：将temp2中的16*S的方形转置到dst中，在dst中是NZ格式，来自同一个方形的连续2行数据在目的操作数上的地址偏移16个元素，沿H方向的每2个方形的同一行数据在目的操作数上的地址偏移S*16个元素。

**图18 **场景7：二维转置
![](images/atlasascendc_api_07_0865_img_018.png)

计算过程如下：

1. 调用TransDataTo5HD，通过设置不同的源操作数地址序列和目的操作数地址序列，将[H, W]转置为[W, H]，src和dst均是ND格式。

**图19 **场景13 : 二维转置或者三维的后两维转置
![](images/atlasascendc_api_07_0865_img_019.png)

计算过程如下：

1. 调用内部计算逻辑，通过设置不同的源操作数地址序列，连续写入目的操作数地址中，将[H, W]转置为[W, H]，或者将[N, H, W]转置为[N, W, H]，src和dst均是ND格式。

场景14、场景15的转换过程和上述场景13中三维转置的转换过程基本一致，只是指定转置的维度不同。

**图20 **场景16 ：使用交织指令进行两维ND2NZ转置
![](images/atlasascendc_api_07_0865_img_020.png)

计算过程如下：

1. 调用内部计算逻辑，通过设置不同的源操作数地址序列，连续写入目的操作数地址中，将[H, W] ND格式转置为[W1,H1,H0,W0] NZ格式，H = H1 * H0，W = W1 * W0，H0=16，W0=2，src是ND格式，dst是NZ格式。

#### 函数原型

由于该接口的内部实现中涉及复杂的计算，需要额外的临时空间来存储计算过程中的中间变量。临时空间大小BufferSize的获取方法：通过Transpose Tiling中提供的**GetTransposeMaxMinTmpSize**接口获取所需最大和最小临时空间大小，最小空间可以保证功能正确，最大空间用于提升性能。

临时空间支持**接口框架申请**和开发者**通过sharedTmpBuffer入参传入**两种方式，因此Transpose接口的函数原型有两种：

- 通过sharedTmpBuffer入参传入临时空间

```
template <typename T>
__aicore__ inline void Transpose(const LocalTensor<T>& dst, const LocalTensor<T>& src, const LocalTensor<uint8_t> &sharedTmpBuffer, TransposeType transposeType, ConfusionTransposeTiling& tiling)
```

该方式下开发者需自行申请并管理临时内存空间，并在接口调用完成后，复用该部分内存，内存不会反复申请释放，灵活性较高，内存利用率也较高。

- 接口框架申请临时空间

```
template <typename T>
__aicore__ inline void Transpose(const LocalTensor<T>& dst, const LocalTensor<T>& src, TransposeType transposeType, ConfusionTransposeTiling& tiling)
```

该方式下开发者无需申请，但是需要预留临时空间的大小。

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数的数据类型。          Atlas 350 加速卡，场景1到场景7支持的数据类型为：int16_t、uint16_t、half、int32_t、uint32_t、float；场景13到场景15支持的数据类型为：int8_t、uint8_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float；场景16支持的数据类型为：int8_t、uint8_t。                       Atlas A3 训练系列产品            /             Atlas A3 推理系列产品            ，支持的数据类型为：int16_t、uint16_t、half、int32_t、uint32_t、float。                       Atlas A2 训练系列产品            /             Atlas A2 推理系列产品            ，支持的数据类型为：int16_t、uint16_t、half、int32_t、uint32_t、float。                       Atlas 推理系列产品            AI Core，支持的数据类型为：int16_t、uint16_t、half、int32_t、uint32_t、float。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | 目的操作数，LocalTensor数据结构的定义请参考LocalTensor。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| src | 输入 | 源操作数，LocalTensor数据结构的定义请参考LocalTensor。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| sharedTmpBuffer | 输入 | 共享缓冲区，用于存放API内部计算产生的临时数据。该方式开发者可以自行管理sharedTmpBuffer内存空间，并在接口调用完成后，复用该部分内存，内存不会反复申请释放，灵活性较高，内存利用率也较高。共享缓冲区大小的获取方式请参考Transpose Tiling。          类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| 数据排布及reshape的类型，类型为TransposeType枚举类。                                                                                                                           ``` enum class TransposeType : uint8_t {     TRANSPOSE_TYPE_NONE,            // default value     TRANSPOSE_NZ2ND_0213,           // 场景1：NZ2ND，1、2轴互换     TRANSPOSE_NZ2NZ_0213,           // 场景2：NZ2NZ，1、2轴互换     TRANSPOSE_NZ2NZ_012_WITH_N,     // 场景3：NZ2NZ，尾轴切分     TRANSPOSE_NZ2ND_012_WITH_N,     // 场景4：NZ2ND，尾轴切分     TRANSPOSE_NZ2ND_012_WITHOUT_N,  // 场景5：NZ2ND，尾轴合并     TRANSPOSE_NZ2NZ_012_WITHOUT_N,  // 场景6：NZ2NZ，尾轴合并     TRANSPOSE_ND2ND_ONLY,           // 场景7：二维转置      TRANSPOSE_ND_UB_GM,             // 当前不支持     TRANSPOSE_GRAD_ND_UB_GM,        // 当前不支持     TRANSPOSE_ND2ND_B16,            // 当前不支持     TRANSPOSE_NCHW2NHWC,            // 当前不支持     TRANSPOSE_NHWC2NCHW,            // 当前不支持     TRANSPOSE_ND2ND_021,            // 场景13：二维转置或者三维中后两维转置，该参数仅支持Atlas 350 加速卡     TRANSPOSE_ND2ND_102,            // 场景14：三维中第一维和第二维互换，该参数仅支持Atlas 350 加速卡     TRANSPOSE_ND2ND_210,            // 场景15：三维中第一维和第三维互换，该参数仅支持Atlas 350 加速卡      TRANSPOSE_ND2NZ_WITH_INTLV      // 场景16：使用交织指令进行两维ND2NZ转置，该参数仅支持Atlas 350 加速卡                  }; ``` |  |  |
| tiling | 输入 | 计算所需tiling信息，Tiling信息的获取请参考Transpose Tiling。 |

#### 约束说明

- 场景13到场景16仅在Atlas 350 加速卡上支持。
- Atlas 350 加速卡，场景13到场景16不支持dst和src空间复用。

#### 调用示例

本示例为场景1（NZ2ND，1、2轴互换）示例：

输入Tensor { shape:[B, N, H/N/16, S/16, 16, 16], origin_shape：[B, N, S, H/N], format:"NZ", origin_format:"ND"}

输出Tensor { shape:[B, S, N, H/N], origin_shape:[B, S, N, H/N], format:"ND", origin_format:"ND"}

B=1，N=2, S=64, H/N=32，输入数据类型均为half。更多完整样例请参考[Transpose样例](https://gitcode.com/cann/asc-devkit/blob/9.0.0/examples/01_simd_cpp_api/03_libraries/08_transpose/transpose)。

```
// dst：输入Tensor
// src：输出Tensor
// NZ2ND，1、2轴互换
AscendC::Transpose(dst, src, AscendC::TransposeType::TRANSPOSE_NZ2ND_0213, this->tiling);
```
