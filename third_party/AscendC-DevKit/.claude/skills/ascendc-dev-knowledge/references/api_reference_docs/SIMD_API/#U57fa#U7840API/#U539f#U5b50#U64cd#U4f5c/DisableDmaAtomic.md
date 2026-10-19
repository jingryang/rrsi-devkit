# DisableDmaAtomic

**页面ID:** atlasascendc_api_07_0212  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0212.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | √ |

#### 功能说明

清空原子操作的状态。

#### 函数原型

```
__aicore__ inline void DisableDmaAtomic()
```

#### 参数说明

无

#### 约束说明

无

#### 调用示例

```
constexpr uint32_t totalLength = 256;    // 参与搬运的元素个数
AscendC::LocalTensor<float> src0Local;
AscendC::GlobalTensor<float> dstGlobal;
AscendC::SetAtomicAdd<float>();    // 开启原子累加，累加数据类型为float
AscendC::DataCopy(dstGlobal, src0Local, totalLength * sizeof(float));
AscendC::DisableDmaAtomic();    // 清空原子操作的状态
```
