# Nop

**页面ID:** atlasascendc_api_07_0182  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0182.html

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

用户输入延迟的个数，实现延迟若干个cycle。

#### 函数原型

```
template <int count = 1>
__aicore__ inline void Nop()
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| count | 输入 | 延迟count个cycle。 |

#### 约束说明

无

#### 调用示例

如下样例中，延迟10个cycle。

```
Nop<10>();
```
