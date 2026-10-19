# add_volatile

**页面ID:** atlasascendc_api_07_10443  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10443.html

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

在程序编译时，为指定类型添加volatile限定符，可以用于在编译时进行类型转换。

#### 函数原型

```
template <typename Tp>
struct add_volatile;
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 含义 |
| --- | --- |
| Tp | 需要处理的类型，包括基本类型（如int、float等）、复合类型（如数组、指针、引用）、用户自定义类型（如类、结构体等），以及带有volatile限定符的类型。 |

#### 约束说明

无

#### 返回值说明

add_volatile是一个结构体，其提供一个嵌套类型type，表示添加volatile限定符后的类型。通过add_volatile<Tp>::type来访问该类型。

#### 调用示例

```
// Test non-volatile type
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile<int>::type, volatile int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile<double>::type, volatile double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile<char>::type, volatile char>));
// Test volatile type
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile<volatile int>::type, volatile int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile<volatile double>::type, volatile double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile<volatile char>::type, volatile char>));

ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile_t<int>, volatile int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile_t<double>, volatile double>));

ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile_t<volatile int>, volatile int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::add_volatile_t<volatile double>, volatile double>));
```
