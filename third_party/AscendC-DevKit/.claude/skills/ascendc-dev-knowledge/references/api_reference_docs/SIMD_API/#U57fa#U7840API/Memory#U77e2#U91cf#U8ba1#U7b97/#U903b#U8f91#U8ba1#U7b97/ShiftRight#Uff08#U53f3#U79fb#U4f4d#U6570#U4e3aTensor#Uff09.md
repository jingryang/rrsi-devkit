# ShiftRight（右移位数为Tensor）

**页面ID:** atlasascendc_api_07_00252  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00252.html

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

源操作数内每个元素做右移。

对无符号数据类型的源操作数做逻辑右移，对有符号数据类型的源操作数做算术右移。

逻辑右移为去掉最低位，最高位填充为0。

算术右移为去掉最低位，最高位复制符号位。

例：数据类型uint16_t，二进制数 1010101010101010，逻辑右移一位结果为 0101010101010101；

数据类型int16_t，二进制数 1010101010101010，算术右移一位结果为 1101010101010101；

数据类型int16_t，二进制数 1010101010101010，算术右移三位结果为 1111010101010101。

#### 函数原型

```
template <typename T, typename U>
__aicore__ inline void ShiftRight(const LocalTensor<T>& dst, const LocalTensor<T>& src0, const LocalTensor<U>& src1, const int32_t& count)
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
| src1 | 输入 | 存放右移位数的LocalTensor，数据类型的字节数需要与源src0操作数Tensor中的元素数据类型的字节数相匹配，不支持设置为负数。 |
| count | 输入 | 参与计算的元素个数。 |

#### 约束说明

- 对于逻辑位移（无符号数据类型），如果位移量大于数据类型位宽，则输出为0。
- 对于算数位移（有符号数据类型），如果src0小于0，src1大于0，并且位移量大于数据类型位宽，则输出-1；如果src0大于0，并且位移量大于数据类型位宽，则输出0。

#### 调用示例

```
AscendC::ShiftRight(dstLocal, srcLocal0, srcLocal1, 512);
```

结果示例如下：

```
输入数据(srcLocal0): [1 2 3 ... 512]
输入数据(srcLocal1): [2 2 2 ... 2]
输出数据(dstLocal): [0 0 0 1 1 1 1 ... 128]
```
