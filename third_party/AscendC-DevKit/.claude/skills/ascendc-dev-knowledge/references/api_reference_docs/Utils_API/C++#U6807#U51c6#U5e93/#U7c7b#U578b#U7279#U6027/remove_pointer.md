# remove_pointer

**页面ID:** atlasascendc_api_07_10441  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10441.html

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

在程序编译时，从给定类型中移除指针限定符，可以用于在编译时进行类型转换。

#### 函数原型

```
template <typename Tp>
struct remove_pointer;
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 含义 |
| --- | --- |
| Tp | 需要处理的类型，包括基本类型（如int、float等）、复合类型（如数组、引用）、用户自定义类型（如类、结构体等），以及指针类型本身。 |

#### 约束说明

无

#### 返回值说明

remove_pointer是一个结构体，其提供一个嵌套类型type，表示移除指针限定符后的类型。通过remove_pointer<Tp>::type来访问该类型。

#### 调用示例

```
// Test non-pointer type
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<int>::type, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<double>::type, double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<char>::type, char>));
// Test pointer type
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<int*>::type, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<double*>::type, double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<char*>::type, char>));
// Test const pointer type
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<int* const>::type, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<double* const>::type, double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<char* const>::type, char>));
// Test volatile type
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<int* volatile>::type, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<double* volatile>::type, double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<char* volatile>::type, char>));
// Test const and volatile type
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<int* const volatile>::type, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<double* const volatile>::type, double>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer<char* const volatile>::type, char>));

ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<int>, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<double>, double>));

ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<int*>, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<double*>, double>));

ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<int* const>, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<double* const>, double>));

ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<int* volatile>, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<double* volatile>, double>));

ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<int* const volatile>, int>));
ascendc_assert((AscendC::Std::is_same_v<AscendC::Std::remove_pointer_t<double* const volatile>, double>));
```
