# sqrt

**页面ID:** atlasascendc_api_07_10183  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10183.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

计算输入数据的平方根。

#### 函数原型

```
template <typename T>
__aicore__ inline T sqrt(const T src)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 含义 |
| --- | --- |
| T | 输入数据src的数据类型。当前支持的数据类型为float、int64_t。 |

**表2 **接口参数说明

| 参数名 | 输入/输出 | 含义 |
| --- | --- | --- |
| src | 输入 | 源操作数。 |

#### 约束说明

输入必须为非负数。若输入为负数，则接口返回值无意义。

#### 返回值说明

输入数据的平方根。

对于数据类型为int64_t的数据，其计算结果将被截断为整数。

#### 调用示例

```
int64_t src = 4;

int64_t result = AscendC::Std::sqrt(src); 
// result: 2
```
