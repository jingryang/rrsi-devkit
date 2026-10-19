# operator[]

**页面ID:** atlasascendc_api_07_00030  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00030.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | √ |
| Atlas 训练系列产品 | √ |

#### 功能说明

根据输入的offset偏移返回新的GlobalTensor。

#### 函数原型

```
__aicore__ inline GlobalTensor operator const
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| offset | 输入 | 偏移offset个元素。 |

#### 返回值说明

指定偏移量的GlobalTensor。

#### 约束说明

无。

#### 调用示例

```
// operator[]使用方法, aGlobal[4]为从起始地址开始偏移量为4的新tensor
auto gmA = aGlobal[4];
// 示例结果如下：
// 输入数据(aGlobal): [1 2 3 4 5 6 ... 100]
// 输出数据(gmA ): [5 6 7 8 ... 100]
```
