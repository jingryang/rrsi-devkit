# SetSimtBlockDim

**页面ID:** atlasopapi_07_00801  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00801.html

---

#### 函数功能

设置SIMT线程块的维度，即参与计算的Vector运算单元的线程块内部的线程数量，用Dim3结构体表示。Dim3是包含了x、y、z三个uint32的字段的结构体，表示一个Block线程块在x、y、z三个维度上的线程数量。

例如：block_dim.x、block_dim.y、block_dim.z分别表示线程块在x、y、z三个维度上的线程数量。

#### 函数原型

```
ge::graphStatus SetSimtBlockDim(const Dim3 &block_dim)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| block_dim | 输入 | 线程块的维度；用Dim3结构体表示。Dim3是包含了x、y、z三个uint32的字段的结构体，表示一个Block线程块在x、y、z三个维度上的线程数量。 |

Dim3结构体定义如下：

```
struct Dim3 {
  uint32_t x, y, z;
  Dim3(const uint32_t dim3_x, const uint32_t dim3_y = 1, const uint32_t dim3_z = 1) : x(dim3_x), y(dim3_y), z(dim3_z) {
  }
};
```

说明：Dim3是包含了x、y、z三个uint32字段的结构体。在SIMT中，可以表示一个Block线程块在x、y、z三个维度上的线程数量；也可以表示一个Grid线程格在x、y、z三个维度上的线程块数量。

#### 返回值说明

设置成功时返回“ge::GRAPH_SUCCESS”。

关于graphStatus的定义，请参见ge::graphStatus。

#### 约束说明

无

#### 调用示例

```
gert::Dim3 block_dim(2, 3);
ge::graphStatus Tiling4XXX(TilingContext* context) {
  auto ret = context->SetSimtBlockDim(block_dim);
  // ...
}
```
