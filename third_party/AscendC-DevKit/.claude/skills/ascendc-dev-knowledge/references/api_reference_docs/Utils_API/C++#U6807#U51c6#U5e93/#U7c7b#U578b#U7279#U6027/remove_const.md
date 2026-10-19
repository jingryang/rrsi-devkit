# remove_const

**页面ID:** atlasascendc_api_07_10437  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10437.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

在程序编译时，对传入的模板参数类型移除const限定符，可以用于在编译时进行类型转换。

#### 函数原型

```
template <typename Tp>
struct remove_const;
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 含义 |
| --- | --- |
| Tp | 需要处理的类型，包括基本类型（如int、float等）、复合类型（如数组、指针、引用）、用户自定义类型（如类、结构体等），以及const限定的类型。 |

#### 约束说明

无

#### 返回值说明

remove_const是一个结构体，其提供一个嵌套类型type，表示移除const限定符后的类型。通过remove_const<Tp>::type来访问该类型。

#### 调用示例

```
// Test non-const type
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const<int>::type, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const<double>::type, double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const<char>::type, char>));

// Test const type
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const<const int>::type, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const<const double>::type, double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const<const char>::type, char>));

ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const_t<int>, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const_t<double>, double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const_t<const int>, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_const_t<const double>, double>));
```
