# DeQue

**页面ID:** atlasascendc_api_07_00043  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00043.html

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

将tensor从队列中取出，用于后续处理。

#### 函数原型

```
template <typename T>
__aicore__ inline LocalTensor<T> DeQue()
```

#### 参数说明

无

#### 约束说明

无

#### 返回值说明

从队列中取出的LocalTensor。

#### 调用示例

参考调用示例。
