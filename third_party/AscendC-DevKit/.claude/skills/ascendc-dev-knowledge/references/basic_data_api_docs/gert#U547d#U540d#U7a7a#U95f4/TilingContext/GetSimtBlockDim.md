# GetSimtBlockDim

**页面ID:** atlasopapi_07_00802  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00802.html

---

#### 函数功能

获取SIMT线程块的维度，即参与计算的Vector运算单元的线程块内部的线程数量，用Dim3结构体表示。Dim3是包含了x、y、z三个uint32的字段的结构体，表示一个Block线程块在x、y、z三个维度上的线程数量。

例如：block_dim.x、block_dim.y、block_dim.z分别表示线程块在x、y、z三个维度上的线程数量。

#### 函数原型

```
const Dim3 *GetSimtBlockDim() const
```

#### 参数说明

无

#### 返回值说明

返回block_dim。

#### 约束说明

无

#### 调用示例

```
ge::graphStatus Tiling4XXX(TilingContext* context) {
  auto block_dim = context->GetSimtBlockDim();
  // ...
}
```
