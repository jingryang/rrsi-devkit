# FunctionName

**页面ID:** atlasascendc_api_07_00227  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00227.html

---

#### 功能说明

配置自定义算子调用的kernel函数接口名称，functionName固定为“RunCpuKernel”。

#### 函数原型

```
OpHostCPUDef &FunctionName(const char *value)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| value | 输入 | 算子调用的kernel函数接口名称，functionName固定为“RunCpuKernel”。 |

#### 返回值说明

OpHostCPUDef算子定义，OpHostCPUDef请参考OpHostCPUDef。

#### 约束说明

无
