# SimtGridDim

**页面ID:** atlasopapi_07_00796  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00796.html

---

#### 函数功能

设置SIMT线程格的维度，即参与计算的Vector运算单元的线程格内部的线程块数量，用Dim3结构体表示。Dim3是包含了x、y、z三个uint32的字段的结构体，表示一个Grid线程格在x、y、z三个维度上的线程块数量。算子Tiling函数可通过该Builder类构造的上下文TilingContext获取相应的Dim3指针。

例如：block_dim.x、block_dim.y、block_dim.z分别表示线程格在x、y、z三个维度上的线程块数量。

#### 函数原型

```
OpTilingContextBuilder &SimtGridDim(const gert::Dim3 *grid_dim)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| grid_dim | 输入 | 设置输入grid dim指针。 |

#### 返回值说明

OpTilingContextBuilder对象本身，用于链式调用。

#### 约束说明

- 在调用Build方法之前，必须设置InputTensors，否则构造出的TilingContext将包含未定义数据。
- 通过指针传入的参数（gert::Dim3*），其内存所有权归调用者所有；调用者必须确保指针在ContextHolder对象的生命周期内有效。
