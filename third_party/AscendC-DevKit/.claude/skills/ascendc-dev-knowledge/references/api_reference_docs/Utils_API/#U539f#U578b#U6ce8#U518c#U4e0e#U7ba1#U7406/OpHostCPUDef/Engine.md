# Engine

**页面ID:** atlasascendc_api_07_00221  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00221.html

---

#### 功能说明

配置算子调用的引擎，入参固定为“DNN_VM_HOST_CPU”。

#### 函数原型

```
OpHostCPUDef &Engine(const char *value)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| value | 输入 | 配置算子调用的引擎名称。 |

#### 返回值说明

OpHostCPUDef算子定义，OpHostCPUDef请参考OpHostCPUDef。

#### 约束说明

无
