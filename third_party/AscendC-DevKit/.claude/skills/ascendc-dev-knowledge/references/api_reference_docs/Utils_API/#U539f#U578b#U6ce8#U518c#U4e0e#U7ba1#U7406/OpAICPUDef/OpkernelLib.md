# OpkernelLib

**页面ID:** atlasascendc_api_07_00215  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00215.html

---

#### 功能说明

配置算子调用的kernelLib，AICPU自定义算子调用的kernelLib固定为“CUSTAICPUKernel”。

#### 函数原型

```
OpAICPUDef &OpkernelLib(const char *value)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| value | 输入 | kernelLib值，算子调用的kernelLib固定为“CUSTAICPUKernel。 |

#### 返回值说明

OpAICPUDef算子定义，OpAICPUDef请参考OpAICPUDef。

#### 约束说明

无
