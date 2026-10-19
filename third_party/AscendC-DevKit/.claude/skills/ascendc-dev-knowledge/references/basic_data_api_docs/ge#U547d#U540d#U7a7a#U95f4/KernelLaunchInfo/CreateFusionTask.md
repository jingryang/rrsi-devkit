# CreateFusionTask

**页面ID:** atlasopapi_07_00789  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00789.html

---

#### 函数功能

创建一个Fusion类型的Task，Fusion类型的Task指融合类型的Task，目前支持AI Core Task和CCU Task组成一个Fusion Task。

#### 函数原型

```
static KernelLaunchInfo CreateFusionTask(const gert::ExeResGenerationContext *context, const std::vector<KernelLaunchInfo>& sub_tasks)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| context | 输入 | GenerateTask函数的入参，保存了算子的基础信息。 |
| sub_tasks | 输入 | KernelLaunchInfo序列，包含AI Core和CCU类型的KernelLaunchInfo。 |

#### 返回值说明

返回创建出来的Fusion Task信息。

#### 约束说明

sub_tasks目前暂时仅支持AI Core Task+CCU Task的序列组合。

#### 调用示例

```
graphStatus Mc2GenTaskCallback(const gert::ExeResGenerationContext *context,
    std::vector<std::vector<uint8_t>> &tasks) {
  ...
  //创建ccuTask和aicoreTask的sub_tasks序列
  std::vector<ge::KernelLaunchInfo> sub_tasks= {CcuTask, AicoreTask};
  ge::KernelLaunchInfo fusionTask = ge::KernelLaunchInfo::CreateFusionTask(context, sub_tasks);
  ...
}
```
