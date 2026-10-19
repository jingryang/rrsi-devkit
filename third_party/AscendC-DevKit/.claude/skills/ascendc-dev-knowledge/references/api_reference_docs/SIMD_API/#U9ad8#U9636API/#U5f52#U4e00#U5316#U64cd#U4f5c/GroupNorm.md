# GroupNorm

**页面ID:** atlasascendc_api_07_0816  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0816.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

对一个特征进行标准化的一般公式如下所示：

![](images/atlasascendc_api_07_0816_img_001.png)

其中，i表示特征中的索引，![](images/atlasascendc_api_07_0816_img_002.png) 和 ![](images/atlasascendc_api_07_0816_img_003.png) 表示特征中每个值标准化前后的值，μ和σ表示特征的均值和标准差，计算公式如下所示：

![](images/atlasascendc_api_07_0816_img_004.png)

![](images/atlasascendc_api_07_0816_img_005.png)

其中，ε是一个很小的常数，S表示参与计算的数据的集合，m表示集合的大小。不同类型的特征标准化方法（BatchNorm、LayerNorm、InstanceNorm、GroupNorm等）的主要区别在于参与计算的数据集合的选取上。不同Norm类算子参与计算的数据集合的选取方式如下：

![](images/atlasascendc_api_07_0816_img_006.png)

对于一个shape为[N, C, H, W]的输入，GroupNorm将每个[C, H, W]在C维度上分为groupNum组，然后对每一组进行标准化。最后对标准化后的特征进行缩放和平移。其中缩放参数γ和平移参数β是可训练的。

![](images/atlasascendc_api_07_0816_img_007.png)

#### 函数原型

- 接口框架申请临时空间

```
template <typename T, bool isReuseSource = false>
__aicore__ inline void GroupNorm(const LocalTensor<T>& output, const LocalTensor<T>& outputMean, const LocalTensor<T>& outputVariance, const LocalTensor<T>& inputX, const LocalTensor<T>& gamma, const LocalTensor<T>& beta, const T epsilon, GroupNormTiling& tiling)
```

- 通过sharedTmpBuffer入参传入临时空间

```
template <typename T, bool isReuseSource = false>
__aicore__ inline void GroupNorm(const LocalTensor<T>& output, const LocalTensor<T>& outputMean, const LocalTensor<T>& outputVariance, const LocalTensor<T>& inputX, const LocalTensor<T>& gamma, const LocalTensor<T>& beta, const LocalTensor<uint8_t>& sharedTmpBuffer, const T epsilon, GroupNormTiling& tiling)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持的数据类型为：half、float。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持的数据类型为：half、float。 |
| isReuseSource | 是否允许修改源操作数，默认值为false。如果开发者允许源操作数被改写，可以使能该参数，使能后能够节省部分内存空间。 设置为**true**，则本接口内部计算时**复用**inputX的内存空间，节省内存空间；设置为**false**，则本接口内部计算时**不复用**inputX的内存空间。 对于float数据类型的输入支持开启该参数，half数据类型的输入不支持开启该参数。 isReuseSource的使用样例请参考更多样例。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| output | 输出 | 目的操作数，对标准化后的输入进行缩放和平移计算的结果。shape为[N, C, H, W]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| outputMean | 输出 | 目的操作数，均值。shape为[N, groupNum]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| outputVariance | 输出 | 目的操作数，方差。shape为[N, groupNum]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| inputX | 输入 | 源操作数。shape为[N, C, H, W]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| gamma | 输入 | 源操作数，缩放参数。该参数支持的取值范围为[-100, 100]。shape为[C]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| beta | 输入 | 源操作数，平移参数。该参数支持的取值范围为[-100, 100]。shape为[C]。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| sharedTmpBuffer | 输入 | 接口内部复杂计算时用于存储中间变量，由开发者提供。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 临时空间大小BufferSize的获取方式请参考GroupNorm Tiling。 |
| epsilon | 输入 | 防除0的权重系数。数据类型需要与inputX/output保持一致。 |
| tiling | 输入 | 输入数据的切分信息，Tiling信息的获取请参考GroupNorm Tiling。 |

#### 约束说明

- 当前仅支持ND格式的输入，不支持其他格式。

#### 调用示例

完整的调用样例可参考[GroupNorm样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/02_normalization/groupnorm)。

```
// output: 存放 GroupNorm 计算结果的 Tensor
// outputMean: 输出每个 group 的均值
// outputVariance: 输出每个 group 的方差
// inputX: 输入数据X，shape 为 [N, C, H, W]
// gamma: LayerNorm 的缩放参数 γ，shape 为 [C]
// beta: LayerNorm 的偏置参数 β，shape 为 [C]
// epsilon: 防除零系数ε
// tiling: 预计算的 Tiling 信息，包含分组数、维度等参数

// 使用 GroupNorm 接口实现 Group Normalization
// 若数据类型T为float且允许修改inputX，可设置isReuseSource = true复用inputX内存空间以节省内存
AscendC::GroupNorm<T, isReuseSource>(
    output,           // 输出：归一化并缩放平移后的结果
    outputMean,       // 输出：每组的均值
    outputVariance,   // 输出：每组的方差
    inputX,           // 输入：原始特征图
    gamma,            // 输入：缩放参数 γ
    beta,             // 输入：偏置参数 β
    epsilon,          // 输入：防止除零的系数 ε
    tiling            // 输入：Tiling 调度信息
);
```

示例结果如下：

```
输入数据(inputXLocal, shape:[2, 8, 4, 2]): 
[  0  1  2  3  4  5  6  7  8  9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 
  32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 60 61 62 63
  64 65 66 67 68 69 70 71 72 73 74 75 76 77 78 79 80 81 82 83 84 85 86 87 88 89 90 91 92 93 94 95 
  96 97 98 99 100 101 102 103 104 105 106 107 108 109 110 111 112 113 114 115 116 117 118 119 120 121 122 123 124 125 126 127 ]
输入数据(gammaLocal, shape:[8]): 
[ 0 1 2 3 4 5 6 7 ]
输入数据(betaLocal, shape:[8]): 
[ 0 1 2 3 4 5 6 7 ]
输出数据(dstLocal): 
[ 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 
  1.1084652 1.3253956 1.542326 1.7592564 1.9761869 2.1931171 2.4100475 2.6269782 
  -1.2539563 -0.8200953 -0.38623452 0.047626257 0.48148715 0.91534793 1.3492088 1.7830696 
  3.3253956 3.9761868 4.626978 5.277769 5.9285607 6.579352 7.230143 7.8809347 
  -2.5079126 -1.6401906 -0.77246904 0.095252514 0.9629743 1.8306959 2.6984177 3.5661392 
  5.542326 6.626978 7.71163 8.796282 9.880934 10.965586 12.050238 13.134891 
  -3.7618694 -2.4602861 -1.1587038 0.14287853 1.4444613 2.7460437 4.0476265 5.349209 
  7.7592564 9.277769 10.796282 12.314795 13.833308 15.351821 16.870335 18.388847 
  0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0 
  1.1084652 1.3253956 1.542326 1.7592564 1.9761869 2.1931171 2.4100475 2.6269782 
  -1.2539563 -0.8200953 -0.38623452 0.047626257 0.48148715 0.91534793 1.3492088 1.7830696 
  3.3253956 3.9761868 4.626978 5.277769 5.9285607 6.579352 7.230143 7.8809347 
  -2.5079126 -1.6401906 -0.77246904 0.095252514 0.9629743 1.8306959 2.6984177 3.5661392 
  5.542326 6.626978 7.71163 8.796282 9.880934 10.965586 12.050238 13.134891 
  -3.7618694 -2.4602861 -1.1587038 0.14287853 1.4444613 2.7460437 4.0476265 5.349209 
  7.7592564 9.277769 10.796282 12.314795 13.833308 15.351821 16.870335 18.388847 ]
输出数据(meanLocal): 
[ 7.5 23.5 39.5 55.5 71.5 87.5 103.5 119.5 ]
输出数据(varianceLocal): 
[ 21.25 21.25 21.25 21.25 21.25 21.25 21.25 21.25 ]
```
