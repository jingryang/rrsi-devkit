# PopStackBuffer

**页面ID:** atlasascendc_api_07_0173  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0173.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | √ |
| Atlas 训练系列产品 | √ |

#### 功能说明

在指定position（逻辑位置）申请临时空间，空间大小为指定position的全部剩余空间。

#### 函数原型

```
template <typename T, TPosition pos>
__aicore__ inline bool PopStackBuffer(LocalTensor<T>& popLocal)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | popLocal的数据类型，支持的数据类型如下：uint8_t、int8_t、int16_t、uint16_t、int32_t、uint32_t、int64_t、uint64_t、float、half。 |
| pos | 需要申请临时空间的position，数据类型为TPosition。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| popLocal | 输出 | 申请临时空间对应的Tensor，Tensor大小为对应position的剩余全部空间。 |

#### 返回值说明

表示函数执行的结果，true表示成功，false表示失败。

#### 约束说明

- 该接口不支持嵌套使用，比如函数A中调用了PopStackBuffer，那么调用函数A的其他函数中则不可以再调用PopStackBuffer。
- 因为当前高阶API内部实现中会使用到本接口，所以算子实现中调用了高阶API的场景，不支持调用该接口。

#### 调用示例

```
AscendC::LocalTensor<int16_t> popBuffer;
bool ret = AscendC::PopStackBuffer<int16_t, AscendC::TPosition::VECCALC>(popBuffer);
```
