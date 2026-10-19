# GetCtrlSpr(ISASI)

**页面ID:** atlasascendc_api_07_00092  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00092.html

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

读取CTRL寄存器（控制寄存器）特定比特位上的值。

#### 函数原型

```
template <int8_t startBit, int8_t endBit>
__aicore__ static inline int64_t GetCtrlSpr()
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| startBit | 起始比特位索引。 |
| endBit | 终止比特位索引。 |

#### 返回值说明

CTRL寄存器对应比特位上的值。

#### 约束说明

无

#### 调用示例

如下为读取CTRL[8:6]比特位数值的示例。

```
int64_t value = AscendC::GetCtrlSpr<6, 8>();
```
