# DeterministicLevel

**页面ID:** atlasopapi_07_00791  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00791.html

---

#### 函数功能

设置确定性计算级别。

#### 函数原型

```
OpTilingContextBuilder &DeterministicLevel(int32_t deterministic_level)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| deterministic_level | 输入 | 确定性计算级别（0为非确定性，1为确定性，2为强一致性）。 |

#### 返回值说明

OpTilingContextBuilder对象本身，用于链式调用。

#### 约束说明

- 在调用Build方法之前，必须调用本接口，否则构造出的TilingContext将包含未定义数据。
- 通过指针传入的参数（void*），其内存所有权归调用者所有；调用者必须确保指针在ContextHolder对象的生命周期内有效。
