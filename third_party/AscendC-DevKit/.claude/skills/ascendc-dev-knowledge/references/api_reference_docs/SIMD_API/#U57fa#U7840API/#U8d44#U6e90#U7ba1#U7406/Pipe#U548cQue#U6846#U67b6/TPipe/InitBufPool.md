# InitBufPool

**页面ID:** atlasascendc_api_07_0119  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0119.html

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

初始化TBufPool内存资源池。本接口适用于内存资源有限时，希望手动指定UB/L1内存资源复用的场景。本接口初始化后在整体内存资源中划分出一块子资源池。划分出的子资源池TBufPool，提供了如下方式进行资源管理：

- TPipe::InitBufPool的重载接口指定与其他TBufPool子资源池复用;
- TBufPool::InitBufPool接口对子资源池继续划分；
- TBufPool::InitBuffer接口分配Buffer；

关于TBufPool的具体介绍及资源划分图示请参考TBufPool。

#### 函数原型

```
template <class T>
__aicore__ inline bool InitBufPool(T& bufPool, uint32_t len)
template <class T, class U>
__aicore__ inline bool InitBufPool(T& bufPool, uint32_t len, U& shareBuf)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | bufPool的类型。 |
| U | shareBuf的类型。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| bufPool | 输入 | 新划分的资源池，类型为TBufPool。 |
| len | 输入 | 新划分资源池长度，单位为Byte，非32Bytes对齐会自动补齐至32Bytes对齐。 |
| shareBuf | 输入 | 被复用资源池，类型为TBufPool，新划分资源池与被复用资源池共享起始地址及长度。 |

#### 约束说明

- 新划分的资源池与被复用资源池的硬件属性需要一致，两者共享起始地址及长度；
- 输入长度需要小于等于被复用资源池长度；
- 其他泛用约束参考TBufPool。

#### 调用示例

由于物理内存的大小有限，在计算过程没有数据依赖的场景或数据依赖串行的场景下，可以通过指定内存复用解决资源不足的问题。

```
// 声明一个指向TPipe管道对象的指针
AscendC::TPipe* pipe;
// 定义两个子资源池对象tbufPool1和tbufPool2
AscendC::TBufPool<AscendC::TPosition::VECCALC> tbufPool1, tbufPool2;
// 初始化第一个子资源池tbufPool1
pipe->InitBufPool(tbufPool1, BUF_SIZE * 3);
// 初始化第二个子资源池tbufPool2，并指定tbufPool2复用tbufPool1的起始地址及长度；
pipe->InitBufPool(tbufPool2, BUF_SIZE * 3, tbufPool1);

// 计算串行，不存在数据踩踏，实现了内存复用及自动同步的能力
tbufPool1.InitBuffer(queSrc0, 1, BUF_SIZE);
tbufPool1.InitBuffer(queSrc1, 1, BUF_SIZE);
tbufPool1.InitBuffer(queDst0, 1, BUF_SIZE);
CopyIn();
Compute(); 
CopyOut();
tbufPool1.Reset();
tbufPool2.InitBuffer(queSrc2, 1, BUF_SIZE);
tbufPool2.InitBuffer(queSrc3, 1, BUF_SIZE);
tbufPool2.InitBuffer(queDst1, 1, BUF_SIZE);
CopyIn1();
Compute1();
CopyOut1();
tbufPool2.Reset();
```
