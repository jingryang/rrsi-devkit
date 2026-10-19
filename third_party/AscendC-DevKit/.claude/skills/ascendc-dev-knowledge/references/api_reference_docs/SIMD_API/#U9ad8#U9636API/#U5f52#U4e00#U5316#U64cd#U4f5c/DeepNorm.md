# DeepNorm

**页面ID:** atlasascendc_api_07_0808  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0808.html

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

在深层神经网络训练过程中，执行层LayerNorm归一化时，可以使用DeepNorm进行替代，通过扩大残差连接来提高Transformer的稳定性。

本接口实现了对shape大小为[B，S，H]的输入数据的DeepNorm归一化，其计算公式如下：

DeepNorm(x) = LayerNorm(α * X + SubLayer(X))

SubLayer(X)通常是指在DeepNorm模型中的一个子层（sub-layer），用于实现自注意力机制（self-attention mechanism）。本接口中会整体作为一个输入Tensor传入。

其中LayerNorm的计算公式请参考LayerNorm。

#### 函数原型

- 通过sharedTmpBuffer入参传入临时空间

```
template <typename T, bool isReuseSrc = false, bool isBasicBlock = false>
__aicore__ inline void DeepNorm(const LocalTensor<T>& dstLocal, const LocalTensor<T>& meanLocal, const LocalTensor<T>& rstdLocal, const LocalTensor<T>& srcLocal, const LocalTensor<T>& gxLocal, const LocalTensor<T>& betaLocal, const LocalTensor<T>& gammaLocal, const LocalTensor<uint8_t>& sharedTmpBuffer, const T alpha, const T epsilon, DeepNormTiling& tiling)
```

- 接口框架申请临时空间

```
template <typename T, bool isReuseSrc = false, bool isBasicBlock = false>
__aicore__ inline void DeepNorm(const LocalTensor<T>& dstLocal, const LocalTensor<T>& meanLocal, const LocalTensor<T>& rstdLocal, const LocalTensor<T>& srcLocal, const LocalTensor<T>& gxLocal, const LocalTensor<T>& betaLocal, const LocalTensor<T>& gammaLocal, const T alpha, const T epsilon, DeepNormTiling& tiling)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持的数据类型为：half、float。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持的数据类型为：half、float。 Atlas 推理系列产品AI Core，支持的数据类型为：half、float。 |
| isReuseSrc | 是否允许修改源操作数，默认值为false。如果开发者允许源操作数被改写，可以使能该参数，使能后能够节省部分内存空间。 设置为**true**，则本接口内部计算时**复用**srcLocal的内存空间，节省内存空间；设置为**false**，则本接口内部计算时**不复用**srcLocal的内存空间。 对于float数据类型输入支持开启该参数，half数据类型输入不支持开启该参数。 isReuseSrc的使用样例请参考更多样例。 |
| isBasicBlock | srcTensor的shape信息满足基本块要求的情况下，可以使能该参数用于提升性能，默认不使能。基本块要求srcTensor的shape需要满足如下条件： - 尾轴即H的长度为64的倍数，但不超过2040；- 非尾轴长度（B*S）为8的倍数。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstLocal | 输出 | 目的操作数。shape为[B，S，H]。H长度不可超过2040。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| meanLocal | 输出 | 均值，目的操作数。shape为[B，S]。meanLocal的数据类型需要与dstLocal保持一致。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| rstdLocal | 输出 | 方差，目的操作数。shape为[B，S]。rstdLocal的数据类型需要与dstLocal保持一致。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| srcLocal | 输入 | 源操作数，shape为[B，S，H]。srcLocal的数据类型需要与目的操作数保持一致，尾轴长度需要32B对齐。H长度不可超过2040。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| gxLocal | 输入 | 源操作数，shape为[B，S，H]。gxLocal的数据类型需要与目的操作数保持一致，尾轴长度需要32B对齐。H长度不可超过2040。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 该参数对应计算公式中的SubLayer(X)的计算结果。 |
| betaLocal | 输入 | 源操作数，shape为[H]。betaLocal的数据类型需要与目的操作数保持一致，长度需要32B对齐。H长度不可超过2040。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| gammaLocal | 输入 | 源操作数，shape为[H]。gammaLocal的数据类型需要与目的操作数保持一致，长度需要32B对齐。H长度不可超过2040。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| sharedTmpBuffer | 输入 | 接口内部复杂计算时用于存储中间变量，由开发者提供。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 临时空间大小BufferSize的获取方式请参考DeepNorm Tiling。 |
| alpha | 输入 | 权重系数。数据类型需要与目的操作数一致。 |
| epsilon | 输入 | 权重系数， 用来防止除零错误。数据类型需要与目的操作数一致。 |
| tiling | 输入 | DeepNorm计算所需Tiling信息，Tiling信息的获取请参考DeepNorm Tiling。 |

#### 约束说明

- isReuseSrc模板参数为false时，srcLocal和dstLocal的Tensor空间不支持复用。
- 仅支持输入shape为ND格式。
- 输入数据不满足对齐要求时，开发者需要进行补齐，补齐的数据应设置为0，防止出现异常值从而影响网络计算。

#### 调用示例

完整的调用样例可参考[DeepNorm样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/02_normalization/deepnorm)。

```
// dstLocal: 存放 DeepNorm 计算结果的 Tensor
// meanLocal: 输出均值Tensor
// rstdLocal: 输出方差Tensor
// srcLocal: 输入的主数据 X，shape 为 [B, S, H]
// gxLocal: SubLayer(X) 的输出
// betaLocal: LayerNorm 的偏置系数β，shape 为 [H]
// gammaLocal: LayerNorm 的缩放系数γ，shape 为 [H]
// alpha: 残差连接的缩放系数α
// epsilon: 防除零系数ε
// tiling: Tiling 信息，包含维度、分块等参数

// 使用 DeepNorm 接口实现 DeepNorm(x) = LayerNorm(α * X + SubLayer(X))
// 若尾轴的长度（H）不超过2040且为64的倍数，同时非尾轴长度（B*S）为8的倍数，可设置isBasicBlock = true提升性能
// 若数据类型T为float且允许修改srcLocal，可设置isReuseSrc = true复用srcLocal内存空间以节省内存
AscendC::DeepNorm<T, isReuseSrc, isBasicBlock>(
    dstLocal,     // 输出：归一化后的结果
    meanLocal,    // 输出：均值 mean
    rstdLocal,    // 输出：倒数标准差 rstd
    srcLocal,     // 输入：原始输入 X
    gxLocal,      // 输入：子层输出 SubLayer(X)
    betaLocal,    // 输入：LayerNorm 偏置系数β
    gammaLocal,   // 输入：LayerNorm 缩放系数γ
    alpha,        // 输入：残差路径缩放系数 α
    epsilon,      // 输入：防除零系数 ε
    tiling        // 输入：Tiling 信息
);
```

示例结果如下：

```
输入数据(srcLocal, shape:[4, 2, 8]): 
[  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
  16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 
  32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 
  48 49 50 51 52 53 54 55 56 57 58 59 60 61 62 63 ]
输入数据(gxLocal, shape:[4, 2, 8]): 
[  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15
  16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 
  32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 
  48 49 50 51 52 53 54 55 56 57 58 59 60 61 62 63 ]
输入数据(gammaLocal, shape:[4]): 
[ 0 1 2 3 4 5 6 7 ]
输入数据(betaLocal, shape:[4]): 
[ 0 1 2 3 4 5 6 7 ]
输出数据(dstLocal): 
[ 0. 1.0439204 2.0527046 3.0263522 3.9648638 4.868239 5.7364774 6.56958
  0. 1.0439204 2.0527046 3.0263522 3.9648638 4.868239 5.7364774 6.56958
  0. 1.0439204 2.0527046 3.0263522 3.9648638 4.868239 5.7364774 6.56958
  0. 1.0439204 2.0527046 3.0263522 3.9648638 4.868239 5.7364774 6.56958
  0. 1.0439204 2.0527046 3.0263522 3.9648638 4.868239 5.7364774 6.56958
  0. 1.0439204 2.0527046 3.0263522 3.9648638 4.868239 5.7364774 6.56958
  0. 1.0439204 2.0527046 3.0263522 3.9648638 4.868239 5.7364774 6.56958
  0. 1.0439204 2.0527046 3.0263522 3.9648638 4.868239 5.7364774 6.56958 ]
输出数据(meanLocal): 
[ -15.75 -51.75 -87.75 -123.75 -159.75 -195.75 -231.75 -267.75 ]
输出数据(rstdLocal): 
[ 106.3125 106.3125 106.3125 106.3125 106.3125 106.3125 106.3125 106.3125 ]
```
