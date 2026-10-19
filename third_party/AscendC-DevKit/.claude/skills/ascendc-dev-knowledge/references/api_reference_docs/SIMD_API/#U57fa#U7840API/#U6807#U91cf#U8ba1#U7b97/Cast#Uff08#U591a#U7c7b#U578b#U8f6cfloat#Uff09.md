# Cast（多类型转float）

**页面ID:** atlasascendc_api_07_0022  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0022.html

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

将输入数据转换为float类型。

#### 函数原型

- bfloat16_t类型转换为float类型

```
__aicore__ inline float Cast(const bfloat16_t& bVal)
```

- 支持多种数据类型转换为float类型

```
template <typename T, typename U = float,
          typename = Std::enable_if_t<
          (Std::is_same<T, bfloat16_t>::value || Std::is_same<T, hifloat8_t>::value ||
           Std::is_same<T, fp8_e5m2_t>::value || Std::is_same<T, fp8_e4m3fn_t>::value ||
           Std::is_same<T, fp4x2_e1m2_t>::value || Std::is_same<T, fp4x2_e2m1_t>::value), 
          void>>
__aicore__ constexpr inline U Cast(T bVal)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：fp4x2_e2m1_t、fp4x2_e1m2_t、hifloat8_t、fp8_e5m2_t、fp8_e4m3fn_t、bfloat16_t。 fp4x2_e1m2_t和fp4x2_e2m1_t类型为了满足1byte数据大小，构造时由两个四位标量数据拼接生成。转换时，被转换的是fp4x2_e1m2_t和fp4x2_e2m1_t标量数据中低位4bit的值，即[0:3]位。 |
| U | 返回值数据类型，仅支持float。 |

**表2 **接口参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| bVal | 输入 | 待转换的标量数据。 |

#### 返回值说明

转换后的float类型标量数据。

#### 约束说明

无

#### 调用示例

```
// 将srcLocal的第一个元素通过Cast转换成float类型，并将结果赋值给fValue
float fValue = AscendC::Cast(srcLocal.GetValue(0));
// 将标量fValue 填充到dstLocal的前 32 个位置
AscendC::Duplicate(dstLocal, fValue, 32);
```

结果示例如下：

```
输入数据(srcLocal):
[21.3750, 74.0000, 57.2500,  ...,  2.4062, 72.5000, 67.5000]
输出数据(dstLocal):
[21.375 21.375 21.375 ... 21.375 21.375 21.375]
```

```
// 如下是一个输入类型fp4x2_e1m2_t的示例：
float fValue = AscendC::Cast<T, float>(srcLocal.GetValue(0));
AscendC::Duplicate(dstLocal, fValue, bufferSize);

// 输入数据(srcLocal)（二进制表达）: [0b10001111 0b10001111 0b10001111 ...]
// 输出数据(dstLocal): [-1.75 -1.75 -1.75 ...]
```
