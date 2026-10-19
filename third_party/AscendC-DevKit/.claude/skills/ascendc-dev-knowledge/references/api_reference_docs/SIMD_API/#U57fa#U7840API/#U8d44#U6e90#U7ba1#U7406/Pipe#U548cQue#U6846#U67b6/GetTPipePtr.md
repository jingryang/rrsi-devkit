# GetTPipePtr

**页面ID:** atlasascendc_api_07_0120  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0120.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | √ |

#### 功能说明

创建TPipe对象时，对象初始化会设置全局唯一的TPipe指针。本接口用于获取该指针，获取该指针后，可进行TPipe相关的操作。

#### 函数原型

```
__aicore__ inline AscendC::TPipe* GetTPipePtr()
```

#### 约束说明

无

#### 调用示例

如下样例中，在核函数入口处创建TPipe对象，对象初始化会设置全局唯一的TPipe指针。在调用KernelAdd类Init函数时，无需显式传入TPipe指针，而是在函数内直接使用GetTPipePtr获取全局TPipe指针，用来做InitBuffer等操作。

```
// inQueueX、inQueueY为VECIN上的TQue，outQueueZ为VECOUT上的TQue
// 获取全局TPipe指针，使用TPipe的InitBuffer接口给TQue分配内存
GetTPipePtr()->InitBuffer(inQueueX, 2, 128 * sizeof(half));
GetTPipePtr()->InitBuffer(inQueueY, 2, 128 * sizeof(half));
GetTPipePtr()->InitBuffer(outQueueZ, 2, 128 * sizeof(half));
```
