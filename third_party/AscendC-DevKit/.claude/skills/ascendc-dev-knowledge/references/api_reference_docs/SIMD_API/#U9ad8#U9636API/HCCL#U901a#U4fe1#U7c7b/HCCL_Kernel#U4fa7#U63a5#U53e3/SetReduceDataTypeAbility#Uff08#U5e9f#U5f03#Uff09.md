# SetReduceDataTypeAbility（废弃）

**页面ID:** atlasascendc_api_07_10400  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10400.html

---

> **注意:** 

该接口废弃，并将在后续版本移除，请不要使用该接口。请使用SetReduceType进行设置。

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

设置Reduce操作类型、目的数据类型和源数据类型，仅对有归约操作的通信任务生效。

#### 函数原型

```
__aicore__ inline bool SetReduceDataTypeAbility(HcclReduceOp op, HcclDataType dstDataType, HcclDataType srcDataType)
```

#### 参数说明

**表1 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| op | 输入 | 归约操作类型，仅对有归约操作的通信任务生效。uint32_t类型，取值详见表2参数说明。 |
| dstDataType | 输入 | 通信任务中输出数据的数据类型。uint8_t类型，该参数的取值范围请参考表1。 不同通信任务支持的输出数据类型不同，具体为： - 对于AllReduce、AllGather、AlltoAllV、AlltoAllvWrite通信任务：输出的数据类型必须与输入的数据类型一致。各通信任务支持的输入数据类型请参考srcDataType。- 对于ReduceScatter通信任务，当输入的数据类型为int16_t、int32_t、half、float、bfloat16_t时，输出的数据类型必须与其一致；当输入的数据类型为int8_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t时，输出的数据类型必须为half、bfloat16_t、float三者之一。 |
| srcDataType | 输入 | 通信任务中输入数据的数据类型。uint8_t类型，该参数的取值范围请参考表1。 不同通信任务支持的输入数据类型如下： - AllReduce通信任务：支持的输入类型为int16_t、half、bfloat16_t、int32_t、float。- AllGather、AlltoAllV通信任务：支持的输入类型为int8_t、uint8_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、int64_t、double。- ReduceScatter通信任务：支持的输入类型为int8_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、int16_t、half、bfloat16_t、int32_t、float。- AlltoAllvWrite通信任务：支持的输入类型为int8_t、uint8_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、int64_t、double。 |

#### 返回值说明

返回是否设置成功。

#### 约束说明

无

#### 调用示例

```
Hccl<HcclServerType::HCCL_SERVER_TYPE_CCU> hccl;
GM_ADDR contextGM = GetHcclContext<HCCL_GROUP_ID_0>();
hccl.InitV2(contextGM, &tilingData);
auto ret = hccl.SetCcTilingV2(offsetof(AllReduceCustomTilingData, mc2CcTiling));
if (ret) {
    return;
}

hccl.SetReduceDataTypeAbility(HcclReduceOp::HCCL_REDUCE_RESERVED, AscendC::HcclDataType::HCCL_DATA_TYPE_BFP16, AscendC::HcclDataType::HCCL_DATA_TYPE_BFP16);
```
