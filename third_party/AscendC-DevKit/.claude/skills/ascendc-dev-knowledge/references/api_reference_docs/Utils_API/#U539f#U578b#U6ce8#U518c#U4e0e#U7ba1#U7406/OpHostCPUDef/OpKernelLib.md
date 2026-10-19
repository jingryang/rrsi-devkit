# OpKernelLib

**页面ID:** atlasascendc_api_07_00225  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00225.html

---

#### 功能说明

配置算子调用的kernelLib，HostCPU自定义算子调用的kernelLib固定为“CUSTHOSTCPUKernel”。

#### 函数原型

```
OpHostCPUDef &OpkernelLib(const char *value)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| value | 输入 | kernelLib值，算子调用的kernelLib固定为“CUSTHOSTCPUKernel。 |

#### 返回值说明

OpHostCPUDef算子定义，OpHostCPUDef请参考OpHostCPUDef。

#### 约束说明

无
