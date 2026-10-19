# ResetCtrlSpr(ISASI)

**页面ID:** atlasascendc_api_07_00093  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00093.html

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

对CTRL寄存器（控制寄存器）的特定比特位做重置。

#### 函数原型

```
template <int8_t startBit, int8_t endBit>
__aicore__ static inline void ResetCtrlSpr()
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| startBit | 起始比特位索引。 |
| endBit | 终止比特位索引。 |

#### 约束说明

仅支持CTRL[8:6]、CTRL[10:9]、CTRL[48]、CTRL[50]、CTRL[53]、CTRL[59]、CTRL[60]比特位。

#### 调用示例

如下示例中重置CTRL[8:6]比特位，不使能原子操作。

```
AscendC::SetCtrlSpr<6, 8>(1);
...
AscendC::ResetCtrlSpr<6, 8>();
```
