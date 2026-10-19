# gert_TilingContextBuilder_SetSimtGridDim

**页面ID:** atlasopapi_07_00806  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00806.html

---

#### 函数功能

使用OpTilingContextBuilder构造TilingContext时设置SIMT Grid维度，对应弱符号C接口，与OpTilingContextBuilder::SimtGridDim等价。

#### 函数原型

```
uint32_t __attribute__((weak)) gert_TilingContextBuilder_SetSimtGridDim(void *builder, const gert::Dim3 *grid_dim)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| builder | 输入 | OpTilingContextBuilder指针。 |
| grid_dim | 输入 | SIMT Grid维度。 |

#### 返回值说明

状态码，0表示设置成功。

#### 约束说明

无。

#### 调用示例

```
OpTilingContextBuilder ctx_builder;
gert::Dim3 grid_dim(4, 5);
ret = gert_TilingContextBuilder_SetSimtGridDim(reinterpret_cast<void *>(&ctx_builder4), &grid_dim);
```
