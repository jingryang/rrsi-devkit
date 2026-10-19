# GetSimtGridDim

**页面ID:** atlasopapi_07_00804  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00804.html

---

#### 函数功能

获取SIMT线程格的维度，即参与计算的Vector运算单元的线程格内部的线程块数量，用Dim3结构体表示。Dim3是包含了x、y、z三个uint32的字段的结构体，表示一个Grid线程格在x、y、z三个维度上的线程块数量。

例如：block_dim.x、block_dim.y、block_dim.z分别表示线程格在x、y、z三个维度上的线程块数量。

#### 函数原型

```
const Dim3 *GetSimtGridDim() const
```

#### 参数说明

无

#### 返回值说明

返回grid_dim。

#### 约束说明

无

#### 调用示例

```
ge::graphStatus Tiling4XXX(TilingContext* context) {
  auto grid_dim = context->GetSimtGridDim();
  // ...
}
```
