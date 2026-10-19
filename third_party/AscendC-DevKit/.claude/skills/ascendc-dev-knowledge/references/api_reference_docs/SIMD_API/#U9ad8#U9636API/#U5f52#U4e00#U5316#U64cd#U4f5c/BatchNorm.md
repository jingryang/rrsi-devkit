# BatchNorm

**页面ID:** atlasascendc_api_07_0806  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0806.html

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

BatchNorm是对于每一层的输入做规范化处理，使得每一层的分布尽可能的相同，从而加速训练过程和提高模型的泛化能力（有效减少梯度消失和梯度爆炸问题）。基本思想是对于每个batch中的样本，对其输入的每个特征在batch的维度上进行归一化。具体来说，对于输入特征x，BatchNorm的计算过程可以表示为：

1. 对输入特征x，在batch维度上计算均值μ和方差σ：

![](images/atlasascendc_api_07_0806_img_001.png)

2. 对于每个特征i，对输入特征x进行归一化：

![](images/atlasascendc_api_07_0806_img_002.png)

3. 对归一化后的特征进行缩放和平移：

![](images/atlasascendc_api_07_0806_img_003.png)

#### 函数原型

- 接口框架申请临时空间

```
template <typename T, bool isReuseSource = false, bool isBasicBlock = false>
__aicore__ inline void BatchNorm(const LocalTensor<T>& output, const LocalTensor<T>& outputMean, const LocalTensor<T>& outputVariance, const LocalTensor<T>& inputX, const LocalTensor<T>& gamm, const LocalTensor<T>& beta, const T epsilon, BatchNormTiling& tiling)
```

- 通过sharedTmpBuffer入参传入临时空间

```
template <typename T, bool isReuseSource = false, bool isBasicBlock = false>
__aicore__ inline void BatchNorm(const LocalTensor<T>& output, const LocalTensor<T>& outputMean, const LocalTensor<T>& outputVariance, const LocalTensor<T>& inputX, const LocalTensor<T>& gamm, const LocalTensor<T>& beta, const LocalTensor<uint8_t>& sharedTmpBuffer, const T epsilon, BatchNormTiling& tiling)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持的数据类型为：half、float。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持的数据类型为：half、float。 Atlas 推理系列产品AI Core，支持的数据类型为：half、float。 |
| isReuseSource | 是否允许修改源操作数。该参数预留，传入默认值false即可。 |
| isBasicBlock | inputX、output的shape信息和Tiling切分策略满足基本块要求的情况下，可以使能该参数用于提升性能，默认不使能。基本块要求如下： - originB是8的倍数；- S*H是64的倍数，但小于2048。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| output | 输出 | 目的操作数，shape为[B，S，H]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| outputMean | 输出 | 均值，目的操作数，shape为[S，H]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| outputVariance | 输出 | 方差，目的操作数，shape为[S，H]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| inputX | 输入 | 源操作数，shape为[B，S，H]。inputX的数据类型需要与目的操作数保持一致，S*H需要32B对齐。支持inputX与output地址重叠。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| gamm | 输入 | 源操作数，shape为[B]。gamm的数据类型需要与目的操作数保持一致，长度需要32B对齐。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| beta | 输入 | 源操作数，shape为[B]。beta的数据类型需要与目的操作数保持一致，长度需要32B对齐。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| sharedTmpBuffer | 输入 | 接口内部复杂计算时用于存储中间变量，由开发者提供。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 临时空间大小BufferSize的获取方式请参考BatchNorm Tiling。 |
| epsilon | 输入 | 防除0的权重系数。数据类型需要与inputX/output保持一致。 |
| tiling | 输入 | 输入数据的切分信息，Tiling信息的获取请参考BatchNorm Tiling。 |

#### 约束说明

- 当前仅支持ND格式的输入，不支持其他格式。
- 输入数据的S*H必须满足32B对齐的要求。

#### 调用示例

完整的调用样例可参考[BatchNorm样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/02_normalization/batchnorm)。

```
// outputLocal：存放BatchNorm计算结果的Tensor
// meanLocal：存放计算结果均值的Tensor
// varianceLocal：存放计算结果方差的Tensor
// inputXLocal：参与计算的输入Tensor
// gammaLocal：输入张量，归一化后数据的缩放系数γ
// betaLocal：输入张量，归一化后数据的平移系数β
// epsilon：防除0的权重系数ε
// batchNormTiling：Tiling数据，从Host侧获取

AscendC::BatchNorm<dataType, isReuseSource, isBasicBlock>(outputLocal, meanLocal,varianceLocal, 
                                                          inputXLocal, gammaLocal, betaLocal, 
                                                          (dataType)epsilon, batchNormTiling);
```

示例结果如下：

```
输入数据(inputXLocal, shape:[8, 4, 2]): 
[  0  1  2  3  4  5  6  7  
   8  9 10 11 12 13 14 15
  16 17 18 19 20 21 22 23 
  24 25 26 27 28 29 30 31 
  32 33 34 35 36 37 38 39 
  40 41 42 43 44 45 46 47 
  48 49 50 51 52 53 54 55 
  56 57 58 59 60 61 62 63 ]
输入数据(gammaLocal, shape:[4]): 
[ 0 1 2 3 4 5 6 7 ]
输入数据(betaLocal, shape:[4]): 
[ 0 1 2 3 4 5 6 7 ]
输出数据(dstLocal): 
[ 0. 0. 0. 0. 0. 0. 0. 0. 
  -0.091073155 -0.091073155 -0.091073155 -0.091073155 -0.091073155 -0.091073155 -0.091073155 -0.091073155 
  0.6907122 0.6907122 0.6907122 0.6907122 0.6907122 0.6907122 0.6907122 0.6907122 
  2.345356 2.345356 2.345356 2.345356 2.345356 2.345356 2.345356 2.345356 
  4.8728585 4.8728585 4.8728585 4.8728585 4.8728585 4.8728585 4.8728585 4.8728585 
  8.27322 8.27322 8.27322 8.27322 8.27322 8.27322 8.27322 8.27322 
  12.546439 12.546439 12.546439 12.546439 12.546439 12.546439 12.546439 12.546439 
  17.692516 17.692516 17.692516 17.692516 17.692516 17.692516 17.692516 17.692516 ]
输出数据(meanLocal): 
[ 28 29 30 31 32 33 34 35 ]
输出数据(varianceLocal): 
[ 336 336 336 336 336 336 336 336 ]
```
