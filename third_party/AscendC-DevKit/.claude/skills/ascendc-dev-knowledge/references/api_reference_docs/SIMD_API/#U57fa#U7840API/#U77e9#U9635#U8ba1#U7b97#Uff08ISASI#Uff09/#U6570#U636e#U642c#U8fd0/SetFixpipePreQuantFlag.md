# SetFixpipePreQuantFlag

**页面ID:** atlasascendc_api_07_0254  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0254.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

DataCopy（CO1->GM、CO1->A1）过程中进行随路量化时，通过调用该接口设置量化流程中标量量化参数。

#### 函数原型

```
template<template T>
__aicore__ inline void SetFixpipePreQuantFlag(uint64_t config)
```

#### 参数说明

**表1 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| config | 输入 | 量化过程中使用到的标量量化参数。 |

#### 约束说明

无

#### 调用示例

完整示例可参考完整示例。

```
float tmp = (float)0.5;
// 将float的tmp转换成uint64_t的deqScalar
uint64_t deqScalar = static_cast<uint64_t>(*reinterpret_cast<int32_t*>(&tmp)); 
AscendC::SetFixpipePreQuantFlag(deqScalar);  // 设置量化参数
AscendC::PipeBarrier<PIPE_FIX>();
```
