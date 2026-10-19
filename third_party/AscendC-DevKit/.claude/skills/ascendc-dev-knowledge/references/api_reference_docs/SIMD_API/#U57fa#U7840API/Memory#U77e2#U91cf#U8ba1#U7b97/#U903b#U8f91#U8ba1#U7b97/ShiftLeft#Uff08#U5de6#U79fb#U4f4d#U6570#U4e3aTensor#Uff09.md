# ShiftLeft（左移位数为Tensor）

**页面ID:** atlasascendc_api_07_00251  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00251.html

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

对源操作数中的每个元素进行左移操作。根据源操作数的数据类型，左移操作分为以下两种情况：

- 数据类型为无符号类型：执行逻辑左移。逻辑左移会将二进制数整体向左移动指定的位数，最高位被丢弃，最低位用0填充。例如，二进制数1010101010101010（uint16_t 类型）逻辑左移1位后，结果为0101010101010100。
- 数据类型为有符号类型：执行算术左移。算术左移会将二进制数整体向左移动指定的位数，次高位被丢弃，最低位用0填充。例如，二进制数1010101010101010（int16_t 类型）算术左移1位后，结果为1101010101010100；算术左移3位后，结果为1101010101010000。

#### 函数原型

```
template <typename T, typename U>
__aicore__ inline void ShiftLeft(const LocalTensor<T>& dst, const LocalTensor<T>& src0, const LocalTensor<U>& src1, const int32_t& count)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 源/目的操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t、uint8_t、int16_t、uint16_t、int32_t、uint32_t、int64_t、uint64_t。 |
| U | 源操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t、int16_t、int32_t、int64_t。 |

**表2 **参数说明

| **参数名称** | 输入/输出 | **说明** |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 |
| src0 | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 数据类型需要与目的操作数保持一致。 |
| src1 | 输入 | 存放左移位数的LocalTensor，数据类型的字节数需要与源src0操作数Tensor中的元素数据类型的字节数相匹配，不支持设置为负数。 |
| count | 输入 | 参与计算的元素个数。 |

#### 约束说明

- 对于逻辑位移（无符号数据类型），如果位移量大于数据类型位宽，则输出为0。
- 对于算数位移（有符号数据类型），如果src0小于0，src1小于0，并且位移量大于数据类型位宽，则输出-1；如果src0大于0，并且位移量大于数据类型位宽，则输出0。

#### 调用示例

```
AscendC::ShiftLeft(dstLocal, srcLocal0, srcLocal1, 512);
```

结果示例如下：

```
输入数据srcLocal0：[1 2 3 ... 512]
输入数据srcLocal1：[2 2 2 ... 2]
输出数据dstLocal：[4 8 12 ... 2048]
```
