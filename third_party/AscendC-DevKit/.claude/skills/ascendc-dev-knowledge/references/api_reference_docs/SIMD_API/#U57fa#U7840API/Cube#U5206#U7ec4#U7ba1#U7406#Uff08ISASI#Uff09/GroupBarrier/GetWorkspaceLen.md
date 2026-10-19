# GetWorkspaceLen

**页面ID:** atlasascendc_api_07_0306  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0306.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

返回当前GroupBarrier所占用的Global Memory消息空间大小。

#### 函数原型

```
__aicore__ inline uint64_t GetWorkspaceLen()
```

#### 参数说明

无

#### 返回值说明

当前GroupBarrier所占用的Global Memory消息空间大小。

#### 约束说明

无

#### 调用示例

```
// 6个AIV等3个AIV Arrive后再开始后续业务，总共需要6*512B地址空间，起始地址为用户指定的startAddr。
AscendC::GroupBarrier<AscendC::PipeMode::MTE3_MODE> barA(startAddr, 3, 6);
uint64_t offset = barA.GetWorkspaceLen(); // 返回barA所占用的GlobalMemory空间。
```

结果示例如下：

```
占用的GlobalMemory空间(offset)的大小为: 3072
```
