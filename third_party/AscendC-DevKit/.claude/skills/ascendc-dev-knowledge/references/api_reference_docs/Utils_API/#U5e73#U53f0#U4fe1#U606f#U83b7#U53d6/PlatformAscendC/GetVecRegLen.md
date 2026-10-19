# GetVecRegLen

**页面ID:** atlasascendc_api_07_00207  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00207.html

---

#### 功能说明

获取当前硬件平台芯片架构Vec计算单元位宽。

#### 函数原型

```
uint32_t GetVecRegLen(void) const
```

#### 参数说明

无

#### 返回值

- 对于RegBase硬件平台芯片架构，返回当前硬件平台Vector计算单元位宽。
- 对于非RegBase硬件平台芯片架构，返回0 。

#### 约束说明

无

#### 调用示例

```
void GetLayerNormMaxMinTmpSize(...)
{
       platform_ascendc::PlatformAscendC* platform = platform_ascendc::PlatformAscendCManager::GetInstance();
        ...
        const uint32_t vecLenB32 = platform->GetVecRegLen() / LAYERNORM_SIZEOF_FLOAT;
        const uint32_t vecLenB16 = platform->GetVecRegLen() / LAYERNORM_SIZEOF_HALF;
        ...
}
```
