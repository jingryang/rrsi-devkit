# Max

**页面ID:** atlasascendc_api_07_00047  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00047.html

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

返回指定数据类型的最大有限值。

Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/half/bfloat16_t/uint32_t/int32_t/float。

#### 函数原型

- 标量接口，返回值为标量

```
constexpr __aicore__ static inline T Max()
```

- 矢量接口，为dst前count个元素赋最大有限值

```
__aicore__ static inline void Max(const LocalTensor<T>& dst, uint32_t count)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 |
| count | 输入 | 输入数据元素个数。 |

#### 返回值说明

标量接口返回值为对应数据类型的最大有限值。

矢量接口无返回值。

#### 约束说明

无。

#### 调用示例

- 标量接口

```
int32_t value = AscendC::NumericLimits<int32_t>::Max();
```

- 矢量接口

```
AscendC::NumericLimits<int32_t>::Max(dstLocal, 256); // 返回256个int32_t类型的最大值
```
