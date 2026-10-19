# GetLocalMemorySize

**页面ID:** atlasopapi_07_00251  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00251.html

---

#### 函数功能

SIMT算子获取所需的Dynamic Unified Buffer大小。

**该接口废弃，并将在后续版本移除，请使用**GetDynUBufSize获取所需Dynamic Unified Buffer大小。

#### 函数原型

**uint32_t GetLocalMemorySize()**

#### 参数说明

无。

#### 返回值说明

返回Local Memory大小，如果之前没有调用SetLocalMemorySize进行设置，则返回0。

#### 约束说明

无。

#### 调用示例

```
ge::graphStatus Tiling4XXX(TilingContext* context) {
  auto local_memory_size = context->GetLocalMemorySize();
  // ...
}
```
