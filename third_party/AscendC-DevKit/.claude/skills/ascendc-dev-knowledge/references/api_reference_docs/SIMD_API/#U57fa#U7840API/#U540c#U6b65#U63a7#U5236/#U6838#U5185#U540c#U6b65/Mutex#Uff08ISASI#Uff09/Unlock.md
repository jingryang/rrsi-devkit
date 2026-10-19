# Unlock

**页面ID:** atlasascendc_api_07_00135  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00135.html

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

直到前置当前流水指令退出后，根据MutexID释放对应Mutex。

#### 函数原型

```
template <pipe_t pipe>
static __aicore__ inline void Unlock(MutexID id)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| pipe | 模板参数，表示流水类别。 支持的流水参考硬件流水类型。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| id | 输入 | 进行流水同步管理的MutexID。 该id可通过用户自定义（范围为0-27）或者通过AllocMutexID/ReleaseMutexID进行申请释放。 |

#### 约束说明

- 用户在使用Lock/Unlock时且自定义MutexID情况时，禁止同时使用TQue、TQueBind、TBufPool中的相关接口。
- 对于同一个MutexID，必须按照Lock/Unlock配套使用，且指定的pipe也需相同，即当且只有完成一个流水的Lock/Unlock之后，才能进行其余流水的操作。
- 相同流水之间存在数据依赖的场景，这种情况建议使用PipeBarrier接口。

#### 调用示例

参考调用示例。
