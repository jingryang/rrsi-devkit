# GetAicpuBlockDim

**页面ID:** atlasopapi_07_00590  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00590.html

---

#### 函数功能

获取用户设置的可以调度的AI CPU核数。设置方式请参考SetAicpuBlockDim。

该参数后续版本会废弃，建议使用GetAicpuNumBlocks。

#### 函数原型

**uint32_t GetAicpuBlockDim() const**

#### 参数说明

无。

#### 返回值说明

用户设置的可以调度的AI CPU核数。

#### 约束说明

无。

#### 调用示例

```
ge::graphStatus Tiling4XXX(TilingContext* context) {
  auto block_dim = context->GetAicpuBlockDim();
  // ...
}
```
