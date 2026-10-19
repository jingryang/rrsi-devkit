# IsFinite

**页面ID:** atlasascendc_api_07_10021  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10021.html

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

按元素判断输入的浮点数是否非NAN、非±INF，输出结果为浮点数或者布尔值。对于非NAN或者非±INF的输入数据，当输出为浮点类型时，对应位置的结果为该浮点类型的1，反之为0；当输出为bool类型时，对应位置的结果为true，反之为false。计算公式如下：

![](images/atlasascendc_api_07_10021_img_001.png)

- 当输出为浮点类型时：

![](images/atlasascendc_api_07_10021_img_002.png)

- 当输出为bool类型时：

![](images/atlasascendc_api_07_10021_img_003.png)

#### 函数原型

```
template<typename T, typename U>
__aicore__ inline void IsFinite(const LocalTensor<U>& dst, const LocalTensor<T>& src, uint32_t calCount)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：half、bfloat16_t、float。 |
| U | 目的操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：bool、half、bfloat16_t、float。 |

**表2 **接口参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 目的操作数的数据类型和源操作数保持一致，或者目的操作数的数据类型为bool类型。当前支持的数据类型组合请见表3。 |
| src | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| calCount | 输入 | 参与计算的元素个数。 |

**表3 **输入输出支持的数据类型组合

| srcDtype | dstDtype |
| --- | --- |
| half | half |
| half | bool |
| float | float |
| float | bool |
| bfloat16_t | bfloat16_t |
| bfloat16_t | bool |

#### 约束说明

- **不支持源操作数与目的操作数地址重叠。**
- 操作数地址偏移对齐要求请参见通用说明和约束。

#### 调用示例

完整算子样例请参考[isfinite算子样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/12_math/isfinite)。

```
// dstLocal: 存放IsFinite计算结果的Tensor
// srcLocal：存放IsFinite计算的输入Tensor
// 需要参与计算的元素个数为8
AscendC::IsFinite(dstLocal, srcLocal, 8);
```

结果示例如下：

```
输入的数据类型为float，输出的数据类型为bool
输入数据(src):
[1.0,+inf,3.0,4.0,nan,6.0,-inf,8.0]
输出数据(dst):
[true,false,true,true,false,true,false,true]
```
