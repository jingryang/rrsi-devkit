# ExpSub(ISASI)

**页面ID:** atlasascendc_api_07_00254  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00254.html

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

src0与src1相减，将差值作为指数计算自然常数e的幂次， 并将计算结果写入dst。

源操作数数据类型为float类型时，计算公式如下：

![](images/atlasascendc_api_07_00254_img_001.png)

源操作数数据类型为half类型时，计算公式如下：

针对Atlas 350 加速卡：

![](images/atlasascendc_api_07_00254_img_002.png)

#### 函数原型

```
template <typename T, typename U>
__aicore__ inline void ExpSub(const LocalTensor<T>& dst, const LocalTensor<U>& src0, const LocalTensor<U>& src1, const uint32_t count)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 |
| U | 源操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 |
| src0、src1 | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 |
| count | 输入 | 参与计算的元素个数。 |

#### 约束说明

#### 调用示例

```
AscendC::ExpSub(dstLocal, src0Local, src1Local, 512);
```

结果示例如下：

```
输入数据src0Local：[1 2 4 ... 510]
输入数据src1Local：[1 1 2 ... 510]
输出数据dstLocal：[1 2.71828 7.38905 ... 1]
```
