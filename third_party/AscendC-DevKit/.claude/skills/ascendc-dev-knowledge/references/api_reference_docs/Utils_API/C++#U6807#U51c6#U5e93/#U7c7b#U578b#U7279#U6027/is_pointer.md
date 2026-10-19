# is_pointer

**页面ID:** atlasascendc_api_07_10434  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10434.html

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

在程序编译时，判断一个类型是否为指针类型，可以用于在编译时进行类型检查和条件处理。

#### 函数原型

```
template <typename Tp>
struct is_pointer;
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 含义 |
| --- | --- |
| Tp | 需要检测的类型，包括基本类型（如int、float等）、复合类型（如数组、函数类型）、用户自定义类型（如类、结构体等），以及指针类型本身。 |

#### 约束说明

无

#### 返回值说明

is_pointer的静态常量成员value用于获取返回的布尔值，is_pointer<Tp>::value取值如下：

- true：Tp是指针类型。
- false：Tp不是指针类型。

#### 调用示例

```
// 自定义测试类型
struct MyStruct{int val;};
// 函数类型
using FuncType = void(int);

// Legitimate pointer types
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<int*>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<char**>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<void*>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<MyStruct*>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<int(*)[5]>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<void(*)(int)>::value);

// Pointer types limited by CV
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<const int*>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<int* const>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<volatile char*>::value);

// non-pointer types
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<int>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<int&>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<int[5]>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<double>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<MyStruct>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<FuncType>::value);
AscendC::printf("AscendC::Std::is_pointer::value:%d\n", AscendC::Std::is_pointer<void>::value);
```

```
// 执行结果：
AscendC::Std::is_pointer::value:1
AscendC::Std::is_pointer::value:1
AscendC::Std::is_pointer::value:1
AscendC::Std::is_pointer::value:1
AscendC::Std::is_pointer::value:1
AscendC::Std::is_pointer::value:1
AscendC::Std::is_pointer::value:1
AscendC::Std::is_pointer::value:1
AscendC::Std::is_pointer::value:1
AscendC::Std::is_pointer::value:0
AscendC::Std::is_pointer::value:0
AscendC::Std::is_pointer::value:0
AscendC::Std::is_pointer::value:0
AscendC::Std::is_pointer::value:0
AscendC::Std::is_pointer::value:0
AscendC::Std::is_pointer::value:0
```
