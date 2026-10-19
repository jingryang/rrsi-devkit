# SetReduceType

**页面ID:** atlasascendc_api_07_10041  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10041.html

---

#### 功能说明

设置Reduce操作类型，仅对有归约操作的通信任务生效。

#### 函数原型

```
uint32_t SetReduceType(uint32_t reduceType, uint8_t dstDataType = 0, uint8_t srcDataType = 0)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| reduceType | 输入 | 归约操作类型，仅对有归约操作的通信任务生效。uint32_t类型，取值详见表2参数说明。 |
| dstDataType | 输入 | 通信任务中输出数据的数据类型。uint8_t类型，该参数的取值范围请参考表1。 Atlas 350 加速卡，不同通信任务支持的输出数据类型不同，具体为： - 对于AllReduce、AllGather、AllToAll、AllToAllV、AllToAllVWrite通信任务：输出的数据类型必须与输入的数据类型一致。各通信任务支持的输入数据类型请参考srcDataType。- 对于ReduceScatter通信任务，当输入的数据类型为int16_t、int32_t、half、float、bfloat16_t时，输出的数据类型必须与其一致；当输入的数据类型为int8_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t时，输出的数据类型必须为half、bfloat16_t、float三者之一。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，该参数暂不支持，配置后不生效。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，该参数暂不支持，配置后不生效。 |
| srcDataType | 输入 | 通信任务中输入数据的数据类型。uint8_t类型，该参数的取值范围请参考表1。 Atlas 350 加速卡，不同通信任务支持的输入数据类型如下： - AllReduce通信任务：支持的输入类型为int16_t、half、bfloat16_t、int32_t、float。- AllGather、AllToAll、AllToAllV、AllToAllVWrite通信任务：支持的输入类型为int8_t、uint8_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、int64_t、double。- ReduceScatter通信任务：支持的输入类型为int8_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、int16_t、half、bfloat16_t、int32_t、float。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，该参数暂不支持，配置后不生效。 针对Atlas A2 训练系列产品/Atlas A2 推理系列产品，该参数暂不支持，配置后不生效。 |

#### 返回值说明

- 0表示设置成功。
- 非0表示设置失败。

#### 约束说明

无

#### 调用示例

本接口的调用示例请见调用示例。
