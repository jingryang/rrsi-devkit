# GetSpr

**页面ID:** atlasascendc_api_07_00233  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00233.html

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

获取指定特殊寄存器的值，当前仅为预留接口。

#### 函数原型

```
template <SpecialPurposeReg spr>
__aicore__ inline int64_t GetSpr()
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| spr | 特殊寄存器，类型为SpecialPurposeReg枚举类，具体的取值请参考表2，当前暂不支持任何SpecialPurposeReg类型的取值。 |

**表2 **SpecialPurposeReg模板参数说明

| 取值 | 含义 |
| --- | --- |
| AR | 一个特殊的地址寄存器，通常配合SqueezeReg矢量计算API一起使用，SqueezeReg矢量计算API会存储有效元素的总字节数到AR寄存器。 |

#### 返回值说明

返回int64_t类型的特殊寄存器中的数值。

#### 约束说明

无

#### 调用示例

预留接口，无调用示例。
