# GetDeterministicLevel

**页面ID:** atlasopapi_07_00792  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00792.html

---

#### 函数功能

获取确定性计算级别配置选项。

#### 函数原型

```
int32_t GetDeterministicLevel() const
```

#### 参数说明

无

#### 返回值说明

0：未开启确定性配置选项。

1：开启确定性配置选项。

2：开启强一致性配置选项。

#### 约束说明

无

#### 调用示例

```
ge::graphStatus Tiling4XXX(TilingContext* context) {
  int32_t ret = context->GetDeterministicLevel();
  // ...
}
```
