# SetAtomicMin(ISASI)

**页面ID:** atlasascendc_api_07_0285  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0285.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

原子操作函数，设置后续从VECOUT传输到GM的数据是否执行原子比较，将待拷贝的内容和GM已有内容进行比较，将最小值写入GM。

可通过设置模板参数来设定不同的数据类型。

#### 函数原型

```
template <typename T>
__aicore__ inline void SetAtomicMin()
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 设定不同的数据类型。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持int8_t/int16_t/half/bfloat16_t/int32_t/float。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持int8_t/int16_t/half/bfloat16_t/int32_t/float。 Atlas 350 加速卡，支持int8_t/int16_t/half/bfloat16_t/int32_t/float。 |

#### 约束说明

使用完后，建议通过DisableDmaAtomic关闭原子最小操作，以免影响后续相关指令功能。

#### 调用示例

```
#include "kernel_operator.h"

uint32_t size = 256;
AscendC::LocalTensor<half> dst0Local = queueDst0.DeQue<half>();
AscendC::LocalTensor<half> dst1Local = queueDst1.DeQue<half>();
AscendC::DataCopy(dstGlobal, dst1Local, size);
AscendC::PipeBarrier<PIPE_MTE3>();
AscendC::SetAtomicMin<half>();
AscendC::DataCopy(dstGlobal, dst0Local, size);
queueDst0.FreeTensor(dst0Local);
queueDst1.FreeTensor(dst1Local);
AscendC::DisableDmaAtomic();

每个核的输入数据为: 
Src0: [1,1,1,1,1,...,1] // 256个1
Src1: [2,2,2,2,2,...,2] // 256个2
最终输出数据: [1,1,1,1,1,...,1] // 256个1
```
