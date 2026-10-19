# GetAicpuNumBlocks

**页面ID:** atlasopapi_07_00800  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00800.html

---

#### 函数功能

获取用户设置的可以调度的AI CPU核数。设置方式请参考SetAicpuNumBlocks。

#### 函数原型

```
uint32_t GetAicpuNumBlocks() const
```

#### 参数说明

无

#### 返回值说明

用户设置的可以调度的AI CPU核数。

#### 约束说明

无

#### 调用示例

```
ge::graphStatus Tiling4XXX(TilingContext* context) {
  auto block_dim = context->GetAicpuNumBlocks();
  // ...
}
```
