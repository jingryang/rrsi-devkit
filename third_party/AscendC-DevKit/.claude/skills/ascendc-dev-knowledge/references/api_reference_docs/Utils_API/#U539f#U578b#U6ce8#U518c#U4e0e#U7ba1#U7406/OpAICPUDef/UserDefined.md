# UserDefined

**页面ID:** atlasascendc_api_07_00218  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00218.html

---

#### 功能说明

配置该算子是否为用户自定义算子，AICPU自定义算子的userDefined仅支持配置为“True”，若开发者没有配置的情况下，该参数会被默认设置为“True”。

#### 函数原型

```
OpAICPUDef &UserDefined(bool flag)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| flag | 输入 | AICPU自定义算子的userDefined仅支持配置为“True”，若开发者没有配置的情况下，该参数会被默认设置为“True”。 |

#### 返回值说明

OpAICPUDef算子定义，OpAICPUDef请参考OpAICPUDef。

#### 约束说明

无
