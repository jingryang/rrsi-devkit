# GetSimdNumBlocks

**页面ID:** atlasopapi_07_00798  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00798.html

---

#### 函数功能

获取SIMD Blocks数量，即参与计算的Vector或者Cube核数。num_blocks的详细概念和设置方式请参考SetSimdNumBlocks。

#### 函数原型

```
uint32_t GetSimdNumBlocks() const
```

#### 参数说明

无

#### 返回值说明

返回num_blocks。

#### 约束说明

无

#### 调用示例

```
ge::graphStatus Tiling4XXX(TilingContext* context) {
  auto block_dim = context->GetSimdNumBlocks();
  // ...
}
```
