# Engine

**页面ID:** atlasascendc_api_07_00211  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00211.html

---

#### 功能说明

配置算子调用的引擎，入参固定为“DNN_VM_AICPU”。

#### 函数原型

```
OpAICPUDef &Engine(const char *value)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| value | 输入 | 配置算子调用的引擎名称。 |

#### 返回值说明

OpAICPUDef算子定义，OpAICPUDef请参考OpAICPUDef。

#### 约束说明

无
