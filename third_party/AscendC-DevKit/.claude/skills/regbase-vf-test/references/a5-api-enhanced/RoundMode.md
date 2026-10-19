# RoundMode

**页面ID:** atlasascendc_api_07_00241  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00241.html

---

控制舍入模式，可输入值：

RoundMode::CAST_RINT：返回最接近参数的整数，如果有2个整数同样接近，则会返回偶数的那个；

RoundMode::CAST_ROUND：round模式， 四舍五入求整；

RoundMode::CAST_FLOOR：floor模式，向下取整；

RoundMode::CAST_CEIL：ceil模式， 向上取整；

RoundMode::CAST_TRUNC：truncation模式， 截断取整；

RoundMode::CAST_ODD：向奇数的方向舍入，既当小数点后数值不为0时，如果整数位是偶数，则进位；

RoundMode::CAST_HYBRID：随机舍入，算子中目前特指输出结果是hif8数据时，会用到的一种随机舍入。

```
enum class RoundMode {
    CAST_NONE = 0,  // 在转换有精度损失时表示CAST_RINT模式，不涉及精度损失时表示不舍入
    CAST_RINT,      // rint，四舍六入五成双舍入
    CAST_FLOOR,     // floor，向负无穷舍入
    CAST_CEIL,      // ceil，向正无穷舍入
    CAST_ROUND,     // round，四舍五入舍入
    CAST_TRUNC,     // trunc，向零舍入
    CAST_ODD,       // Von Neumann rounding，最近邻奇数舍入
    CAST_HYBRID,    // hybrid，目前特指输出结果是hif8数据时，会用到的一种随机舍入 
};
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 RoundMode 实例

未发现使用实例。扫描范围: ops-math、ops-nn（仅 arch35 / `_apt` 文件，已排除 Cube 相关算子）；切片器共识别 0 处 RoundMode 调用。RoundMode 为 `enum class` 舍入模式枚举，源码中以 `RoundMode::CAST_RINT` 等形式作为 Cast 类 API 的模板/实参引用，不属于切片器的函数调用匹配范围，故无实例切出。
