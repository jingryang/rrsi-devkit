# LoadDataUnzip

**页面ID:** atlasascendc_api_07_0243  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0243.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | x |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

将GM上的数据解压并搬运到A1/B1/B2上。执行该API前需要执行LoadUnzipIndex加载压缩索引表。

#### 函数原型

```
template <typename T>
__aicore__ inline void LoadDataUnzip(const LocalTensor<T>& dst, const GlobalTensor<T>& src)
```

#### 参数说明

**表1 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| dst | 输出 | 目的操作数，类型为LocalTensor，支持的TPosition为A1/B1/B2。 LocalTensor的起始地址需要保证：TPosition为A1/B1时，32字节对齐；TPosition为B2时，512B对齐。 支持的数据类型为：int8_t。 |
| src | 输入 | 源操作数，类型为GlobalTensor。数据类型需要与dst保持一致。 |

#### 约束说明

#### 调用示例

该调用示例支持的运行平台为Atlas 推理系列产品AI Core。

```
uint32_t srcLen = 896, dstLen = 1024, numOfIndexTabEntry = 1;
AscendC::LocalTensor<int8_t> weightB1 = inQueueB1.AllocTensor<int8_t>();
AscendC::LoadUnzipIndex(indexGlobal, numOfIndexTabEntry); // 加载索引数据，加载GM上的压缩索引表到内部寄存器
AscendC::LoadDataUnzip(weightB1, weGlobal); // 根据内部寄存器里的索引表加载数据
```
