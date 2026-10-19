# QuietNaN

**页面ID:** atlasascendc_api_07_00052  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00052.html

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

返回指定数据类型的安静NaN值（浮点尾数最高位为1）。

Atlas 350 加速卡，支持的数据类型为：half/bfloat16_t/float。

#### 函数原型

- 标量接口，返回值为标量

```
constexpr __aicore__ static inline T QuietNaN()
```

- 矢量接口，为dstLocal前count个元素赋安静NaN值

```
__aicore__ static inline void QuietNaN(const LocalTensor<T>& dstLocal, uint32_t count)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstLocal | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 |
| count | 输入 | 输入数据元素个数。 |

#### 返回值说明

标量接口返回值为对应数据类型的安静NaN值。

矢量接口无返回值。

#### 约束说明

无。

#### 调用示例

- 标量接口

```
float value = AscendC::NumericLimits<float>::QuietNaN();
```

- 矢量接口

```
AscendC::NumericLimits<float>::QuietNaN(dstLocal, 256); // 返回256个float类型的NaN值
```
