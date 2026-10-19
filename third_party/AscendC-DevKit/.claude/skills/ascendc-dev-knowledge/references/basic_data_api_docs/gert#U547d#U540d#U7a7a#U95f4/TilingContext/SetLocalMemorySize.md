# SetLocalMemorySize

**页面ID:** atlasopapi_07_00250  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00250.html

---

#### 函数功能

SIMT算子用于设置需要使用的Dynamic Unified Buffer大小。不设置的情况下，默认为0，即算子不需要使用Dynamic Unified Buffer。

**该接口废弃，并将在后续版本移除，请使用**SetDynUBufSize设置所需Dynamic Unified Buffer大小。

#### 函数原型

**ge::graphStatus SetLocalMemorySize(const uint32_t local_memory_size)**

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| local_memory_size | 输入 | Local Memory大小。 |

#### 返回值说明

设置成功时返回“ge::GRAPH_SUCCESS”。

关于graphStatus的定义，请参见ge::graphStatus。

#### 约束说明

无。

#### 调用示例

```
ge::graphStatus Tiling4XXX(TilingContext* context) {
    // ...
    auto ret = context->SetLocalMemorySize(1024 * 128);
}
```
