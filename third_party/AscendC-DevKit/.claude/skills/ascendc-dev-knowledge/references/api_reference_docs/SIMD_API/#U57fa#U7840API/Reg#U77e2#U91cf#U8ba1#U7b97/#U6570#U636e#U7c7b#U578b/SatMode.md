# SatMode

**页面ID:** atlasascendc_api_07_00239  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00239.html

---

设置Cast类型转换饱和与不饱和模式，取值如下：

- SatMode::UNKNOWN，当转换类型不支持SatMode模式时，选择该模式；
- SatMode::NO_SAT，不饱和模式；
- SatMode::SAT，饱和模式。

```
enum class SatMode {
    UNKNOWN = -1,
    NO_SAT,
    SAT
};
```
