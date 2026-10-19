# EnQue

**页面ID:** atlasascendc_api_07_00042  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00042.html

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

将tensor push到队列。

#### 函数原型

```
template <typename T>
__aicore__ inline bool EnQue(const LocalTensor<T>& tensor)
```

#### 参数说明

**表1 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| tensor | 输入 | 指定的tensor。 |

#### 约束说明

无。

#### 返回值说明

- true - 表示Tensor加入Queue成功
- false - 表示Queue已满，入队失败

#### 调用示例

参考调用示例。
