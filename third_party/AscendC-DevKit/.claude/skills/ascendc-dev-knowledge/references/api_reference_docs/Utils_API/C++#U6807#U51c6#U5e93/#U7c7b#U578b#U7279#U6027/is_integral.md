# is_integral

**页面ID:** atlasascendc_api_07_10431  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10431.html

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

在程序编译时，检测一个类型是否为整数类型，可以用于在编译时进行类型检查和条件处理。

#### 函数原型

```
template <typename T>
struct is_integral;
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 含义 |
| --- | --- |
| T | 需要检测的类型，包括基本数据类型、修饰类型等。 |

#### 约束说明

无

#### 返回值说明

is_integral的静态常量成员value用于获取返回的布尔值，is_integral<T>::value取值如下：

- true：Tp是数组类型。
- false：Tp不是数组类型。

#### 调用示例

```
// 自定义测试类型
struct MyStruct{};
using FuncType = int(int);

// legal integer type
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<bool>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<char>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<int>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<long long>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<unsigned int>::value);

// Integer type limited by CV
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<const int>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<volatile long>::value);

// non-integer type
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<float>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<double>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<int*>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<int&>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<int[5]>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<FuncType>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<MyStruct>::value);
AscendC::printf("AscendC::Std::is_integral::value:%d\n", AscendC::Std::is_integral<void>::value);
```

```
// 执行结果：
AscendC::Std::is_integral::value:1
AscendC::Std::is_integral::value:1
AscendC::Std::is_integral::value:1
AscendC::Std::is_integral::value:1
AscendC::Std::is_integral::value:1
AscendC::Std::is_integral::value:1
AscendC::Std::is_integral::value:1
AscendC::Std::is_integral::value:0
AscendC::Std::is_integral::value:0
AscendC::Std::is_integral::value:0
AscendC::Std::is_integral::value:0
AscendC::Std::is_integral::value:0
AscendC::Std::is_integral::value:0
AscendC::Std::is_integral::value:0
AscendC::Std::is_integral::value:0
```
