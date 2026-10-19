# SetScheduleMode

**页面ID:** atlasopapi_07_00248  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00248.html

---

#### 函数功能

设置算子在NPU上执行时的调度模式。

#### 函数原型

**ge****::****graphStatus********SetScheduleMode(****const********uint32_t**** s****chedule_mode****)**

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| **s****chedule_mode** | 输入 | 0：普通模式，只要有空闲的AI Core核，系统便会将算子计算任务调度到空闲核上进行计算，比如一个AI Core算子需要4个核， 当出现一个空闲的AI Core核时，便会开始执行此算子，将其中的一个计算切片调度提前调度到那个空闲的核上计算，其他的计算切片等待其余空闲的核出现时，才开始计算，默认情况下为普通模式。 1：batchmode模式，需要等待有足够个数AI Core核空闲时，才会调度此算子开始计算，比如一个AI Core算子需要4个AI Core核，只有空闲出4个核时，才会开始执行此算子。 |

#### 返回值说明

设置成功时返回“ge::GRAPH_SUCCESS”。

设置失败时返回 “ge::GRAPH_FAILED”。

关于graphStatus的定义，请参见ge::graphStatus。

#### 约束说明

在使用多核同步功能时，如果算子运行在多stream场景下，必须通过SetScheduleMode(1)使能batchmode模式，否则会触发死锁问题，导致流程卡死。

在多stream场景下，当某stream的SyncAll算子分配到n个物理核，而其他stream抢占其中m个核（m<n）时，未使能batchmode会导致：先启动的n-m个核执行到多核同步时等待剩余m核完成，而剩余m核因资源被抢占尚未启动，形成死锁。

#### 调用示例

```
ge::graphStatus TilingForAdd(TilingContext *context) {
  uint32_t batch_mode = 1U;
  auto ret = context->SetScheduleMode(batch_mode);  
  GE_ASSERT_SUCCESS(ret);
  ...
}
```
