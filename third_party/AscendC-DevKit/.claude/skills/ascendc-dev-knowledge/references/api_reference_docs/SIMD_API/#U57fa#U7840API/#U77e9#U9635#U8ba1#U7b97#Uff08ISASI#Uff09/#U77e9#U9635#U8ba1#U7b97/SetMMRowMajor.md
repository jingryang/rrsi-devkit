# SetMMRowMajor

**页面ID:** atlasascendc_api_07_0260  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0260.html

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

设置Mmad计算时优先通过N方向，CUBE将首先通过N方向，然后通过M方向生成结果。

#### 函数原型

```
__aicore__ inline void SetMMRowMajor()
```

#### 参数说明

无

#### 约束说明

无

#### 调用示例

```
AscendC::SetMMRowMajor();// 设置Mmad优先计算输出矩阵的N方向，再计算M方向。
```
