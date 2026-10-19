# AtomicExch

**页面ID:** atlasascendc_api_07_00263  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00263.html

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

在GM内存中执行原子交换操作。具体来说，它读取指定GM地址上的数据，并将新的值存储回同一地址。函数返回旧值。

#### 函数原型

```
template <typename T>
__aicore__ inline T AtomicExch(__gm__ T *address, T value)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint32_t/uint64_t |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| address | 输入 | 输入GM的地址。 |
| value | 输入 | 标量值，支持数据类型和address指向的数据类型保持一致。 |

#### 返回值说明

GM地址上做原子操作前的数据。

#### 约束说明

原子操作涉及标量计算，如果标量计算单元和搬运单元（MTE2/MTE3）在读写GM时存在数据依赖，开发者需要根据实际情况插入同步。

#### 调用示例

```
// 传入全局数据地址，初始化dstGlobal与dstLocal
dstGlobal.SetGlobalBuffer(reinterpret_cast<__gm__ T *>(dstGm), dataSize);

LocalTensor<T> dstLocal = inQueueX.AllocTensor<T>();
uint32_t value = 2;
uint32_t a = AscendC::AtomicExch(reinterpret_cast<__gm__ uint32_t *>(dstGm), values);
// 先执行完原子操作之后才能进行搬运操作，有数据依赖
event_t eventIdSToMte2 = static_cast<event_t>(GetTPipePtr()->AllocEventID<HardEvent::S_MTE2>());
// 手动插入MTE2等待Scalar的同步
SetFlag<HardEvent::S_MTE2>(eventIdSToMte2);
WaitFlag<HardEvent::S_MTE2>(eventIdSToMte2);
DataCopy(dstLocal, dstGlobal, dataSize);
// ...
```

假设上述函数在3个核上执行，核1、核2、核3依次调度，结果示例如下：

```
原GM数据dst: [1,1,1,1,1,...,1] 
核1：
原子计算后GM数据dst: [2,1,1,1,1,...,1] 
返回值 a: 1
核2：
原子计算后GM数据dst: [2,1,1,1,1,...,1] 
返回值 a: 2
核3：
原子计算后GM数据dst: [2,1,1,1,1,...,1] 
返回值 a: 2
```
