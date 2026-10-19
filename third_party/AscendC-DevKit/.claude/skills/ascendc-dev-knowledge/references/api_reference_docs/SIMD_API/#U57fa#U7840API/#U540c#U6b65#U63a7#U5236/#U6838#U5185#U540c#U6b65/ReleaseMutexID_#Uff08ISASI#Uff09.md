# ReleaseMutexID (ISASI)

**页面ID:** atlasascendc_api_07_00137  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00137.html

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

从框架释放一个MutexID，与AllocMutexID配合使用。

#### 函数原型

```
__aicore__ inline void ReleaseMutexID(MutexID id)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| id | 输入 | MutexID类型，应传入调用AllocMutexID获得的MutexID。 |

#### 约束说明

无

#### 调用示例

请参考调用示例。
