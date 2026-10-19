# CreateCcuTask

**页面ID:** atlasopapi_07_00788  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00788.html

---

#### 函数功能

创建一个CCU类型的Task。

#### 函数原型

```
static KernelLaunchInfo CreateCcuTask(const gert::ExeResGenerationContext *context, const std::vector<std::string>& groups)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| context | 输入 | GenerateTask函数的入参，保存了算子的基础信息。 |
| groups | 输入 | Ccu Task的组名，是算子设定的通信域名称集合。 |

#### 返回值说明

返回创建出来的Ccu Task信息。

#### 约束说明

无

#### 调用示例

```
graphStatus Mc2GenTaskCallback(const gert::ExeResGenerationContext *context,
    std::vector<std::vector<uint8_t>> &tasks) {
  ...
  //组装ccuGroups
  std::vector<std::string> ccuGroups = {"group_ep", "group"};
  ge::KernelLaunchInfo ccuTask = ge::KernelLaunchInfo::CreateCcuTask(context, ccuGroups);
  ...
}
```
