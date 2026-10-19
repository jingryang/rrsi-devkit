# InitBufPool

**页面ID:** atlasascendc_api_07_0124  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0124.html

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

通过Tpipe::InitBufPool接口可划分出整块资源，整块TbufPool资源可以继续通过TBufPool::InitBufPool接口划分成小块资源。

#### 函数原型

- 非共享模式

```
template <class T>
__aicore__ inline bool InitBufPool(T& bufPool, uint32_t len)
```

- 共享模式

```
template <class T, class U>
__aicore__ inline bool InitBufPool(T& bufPool, uint32_t len, U& shareBuf)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 说明 |
| --- | --- |
| T | bufPool参数的类型。 |
| U | shareBuf参数的类型。 |

**表2 **InitBufPool(T& bufPool, uint32_t len) 原型定义参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| bufPool | 输入 | 新划分的资源池，类型为TBufPool。 |
| len | 输入 | 新划分资源池长度，单位为字节，非32字节对齐会自动向上补齐至32字节对齐。 |

**表3 **InitBufPool(T& bufPool, uint32_t len, U& shareBuf) 原型定义参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| bufPool | 输入 | 新划分的资源池，类型为TBufPool。 |
| len | 输入 | 新划分资源池长度，单位为字节，非32字节对齐会自动向上补齐至32字节对齐。 |
| shareBuf | 输入 | 被复用资源池，类型为TBufPool，新划分资源池与被复用资源池共享起始地址及长度。 |

#### 约束说明

1. 新划分的资源池与被复用资源池的物理内存需要一致，两者共享起始地址及长度；
2. 输入长度需要小于等于被复用资源池长度；
3. 其他泛用约束参考TBufPool；

#### 调用示例

数据量较大且内存有限时，无法一次完成所有数据搬运，需要拆分成多个阶段计算，每次计算使用其中的一部分数据，可以通过TBufPool资源池进行内存地址复用。本例中，从Tpipe划分出资源池tbufPool0，tbufPool0为src0Gm分配空间后，继续分配了资源池tbufPool1，指定tbufPool1与tbufPool2复用并分别运用于第一、二轮计算，此时tbufPool1及tbufPool2共享起始地址及长度。

```
AscendC::TPipe pipe;
AscendC::TBufPool<AscendC::TPosition::VECCALC> tbufPool0, tbufPool1, tbufPool2;
// srcQue0、srcQue1、srcQue2为VECIN上的TQue，dstQue0、dstQue1为VECOUT上的TQue
// 从Tpipe划分出资源池tbufPool0
pipe.InitBufPool(tbufPool0, 131072);
// 给srcQue0分配空间
tbufPool0.InitBuffer(srcQue0, 1, 65536); // Total src0
// 通过tbufPool0给tbufPool1分配空间，并指定tbufPool1与tbufPool2复用同一块空间
tbufPool0.InitBufPool(tbufPool1, 65536);
tbufPool0.InitBufPool(tbufPool2, 65536, tbufPool1);
// 通过tbufPool1给srcQue1、dstQue0分配空间
tbufPool1.InitBuffer(srcQue1, 1, 32768);
tbufPool1.InitBuffer(dstQue0, 1, 32768);
// 切换资源池到tbufPool2，并通过tbufPool2给srcQue2、dstQue1分配空间
tbufPool1.Reset();
tbufPool2.InitBuffer(srcQue2, 1, 32768);
tbufPool2.InitBuffer(dstQue1, 1, 32768);
tbufPool2.Reset();
tbufPool0.Reset();
pipe.Reset();
```
