# Silu

**页面ID:** atlasascendc_api_07_0780  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0780.html

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

按元素做Silu运算，计算公式如下：

![](images/atlasascendc_api_07_0780_img_001.png)

![](images/atlasascendc_api_07_0780_img_002.png)

#### 函数原型

```
template <typename T, bool isReuseSource = false>
__aicore__ inline void Silu(const LocalTensor<T>& dstLocal, const LocalTensor<T>& srcLocal, uint32_t dataSize)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持的数据类型为：half、float。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持的数据类型为：half、float。 Atlas 推理系列产品AI Core，支持的数据类型为：half、float。 |
| isReuseSource | 是否允许修改源操作数。该参数预留，传入默认值false即可。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstLocal | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| srcLocal | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 源操作数的数据类型需要与目的操作数保持一致。 |
| dataSize | 输入 | 实际计算数据元素个数。 |

#### 约束说明

- 操作数地址偏移对齐要求请参见通用说明和约束。
- **不支持源操作数与目的操作数地址重叠。**
- 当前仅支持ND格式的输入，不支持其他格式。

#### 调用示例

完整的算子样例请参考[silu算子样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/01_activation/silu)。

```
// dstLocal: 存放Silu计算结果的Tensor
// srcLocal: 存放Silu计算输入的Tensor

// 需要参与计算的元素个数为512
AscendC::Silu(dstLocal, srcLocal, 512);
```

结果示例如下：

```
输入数据(srcLocal):
[-100.    -50.    -20.    -10.     -5.     -4.     -3.     -2.
   -1.     -0.5    -0.4    -0.3    -0.2    -0.1    -0.01    0.
    0.      0.01    0.1     0.2     0.3     0.4     0.5     1.
    2.      3.      4.      5.     10.     20.     50.    100.  ]
输出数据(dstLocal): 
[ -0.          -0.          -0.00000004  -0.00045398  -0.03346425  -0.07194484  -0.14227761  -0.23840587
  -0.2689414   -0.18877034  -0.16052495  -0.12766725  -0.0900332   -0.04750208  -0.004975     0.
   0.           0.005025     0.05249792   0.10996681   0.17233276   0.23947507   0.31122968   0.7310586
   1.761594     2.8577225    3.928055     4.9665356    9.999546    20.          50.         100.        ]
```
