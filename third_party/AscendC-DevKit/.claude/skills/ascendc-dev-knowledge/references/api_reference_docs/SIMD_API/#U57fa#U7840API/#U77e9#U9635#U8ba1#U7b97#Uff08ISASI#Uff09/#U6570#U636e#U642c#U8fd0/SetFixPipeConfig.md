# SetFixPipeConfig

**页面ID:** atlasascendc_api_07_0252  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0252.html

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

DataCopy（CO1->GM、CO1->A1）过程中进行随路量化时，通过调用该接口设置量化流程中tensor量化参数。

#### 函数原型

```
template <typename T>
__aicore__ inline void SetFixPipeConfig(const LocalTensor<T>& reluPre, const LocalTensor<T>& quantPre, bool isUnitFlag = false)
template <typename T, bool setRelu = false>
__aicore__ inline void SetFixPipeConfig(const LocalTensor<T>& preData, bool isUnitFlag = false)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数的数据类型。 |
| setRelu | 针对设置一个tensor的情况，当setRelu为true时，设置reluPre；反之设置quantPre。setRelu当前仅支持设置为false。 |

**表2 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| reluPre | 输入 | 源操作数，relu操作时参与计算的tensor，类型为LocalTensor，支持的TPosition为C2PIPE2GM。 reluPre为预留参数，暂未启用，为后续的功能扩展做保留，传入一个空LocalTensor即可。 |
| quantPre | 输入 | 源操作数，quant tensor，量化操作时参与计算的tensor，类型为LocalTensor，支持的TPosition为C2PIPE2GM。 |
| isUnitFlag | 输入 | UnitFlag配置项，默认值为false。 - false：关闭UnitFlag配置。- true：打开UnitFlag配置。 |
| preData | 输入 | 支持设置一个Tensor，通过开关控制是relu Tensor还是quant Tensor，支持的TPosition为C2PIPE2GM。当前仅支持传入quant Tensor。 |

#### 约束说明

quantPre和reluPre必须是Fixpipe Buffer上的Tensor。

#### 调用示例

完整示例可参考完整示例。

```
__aicore__inline void SetFPC(const LocalTensor <int32_t>& reluPreTensor, const LocalTensor <int32_t>& quantPreTensor)
{

    AscendC::LocalTensor<uint64_t> workA1 = inQueueDeqA1.AllocTensor<uint64_t>();
    uint16_t deqSize = 128; // deq tensor的size
    AscendC::DataCopy(workA1, deqGlobal, deqSize); // deqGlobal为量化系数的gm地址
    AscendC::LocalTensor<uint64_t> deqFB = inQueueDeqFB.AllocTensor<uint64_t>(); // deq tensor在Fix上的地址
    uint16_t fbufBurstLen = deqSize / 128;  // l1->fix, burst_len unit is 128Bytes
    AscendC::DataCopyParams dataCopyParams(1, fbufBurstLen, 0, 0);
    AscendC::DataCopy(deqFB, workA1, dataCopyParams); 通过DataCopy搬入C2PIPE2GM。
    AscendC::SetFixPipeConfig(deqFB); // 设置量化tensor
    AscendC::PipeBarrier<PIPE_FIX>();
}
```
