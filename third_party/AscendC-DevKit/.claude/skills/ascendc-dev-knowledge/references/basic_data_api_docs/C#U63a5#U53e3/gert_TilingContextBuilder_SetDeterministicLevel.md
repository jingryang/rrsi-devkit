# gert_TilingContextBuilder_SetDeterministicLevel

**页面ID:** atlasopapi_07_00793  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/maintenref/basicdataapi/atlasopapi_07_00793.html

---

#### 函数功能

使用OpTilingContextBuilder构造TilingContext时设置确定性计算级别，对应弱符号C接口，与OpTilingContextBuilder::DeterministicLevel等价。

#### 函数原型

```
uint32_t __attribute__((weak)) gert_TilingContextBuilder_SetDeterministicLevel(void *builder, int32_t deterministic_level)
```

#### 参数说明

| 参数 | 输入/输出 | 说明 |
| --- | --- | --- |
| builder | 输入 | OpTilingContextBuilder指针。 |
| deterministic_level | 输入 | 确定性计算级别。 |

#### 返回值说明

状态码，0表示设置成功。

#### 约束说明

无。

#### 调用示例

```
OpTilingContextBuilder ctx_builder;
auto ret = gert_TilingContextBuilder_SetDeterministicLevel(reinterprete_cast<void *>(&ctx_builder), 2);
```
