# Truncate(ISASI)

**页面ID:** atlasascendc_api_07_00258  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00258.html

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

将源操作数的浮点数元素截断到整数位，同时源操作数的数据类型保持不变。

#### 函数原型

```
template <typename T, RoundMode roundMode>
__aicore__ inline void Truncate(const LocalTensor<T> &dst, const LocalTensor<T> &src, const uint32_t count)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float、bfloat16_t。 |
| roundMode | 舍入模式，取值如下。 - **RoundMode::CAST_RINT**：返回最接近的整数，若存在两个同样接近的整数，则选择偶数。- **RoundMode::CAST_ROUND**：四舍五入取整。- **RoundMode::CAST_FLOOR**：向下取整。- **RoundMode::CAST_CEIL**：向上取整。- **RoundMode::CAST_TRUNC**：截断取整（直接舍弃小数部分）。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 |
| src | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 LocalTensor的起始地址需要32字节对齐。 源操作数的数据类型需要与目的操作数保持一致。 |
| count | 输入 | 参与计算的元素个数。 |

#### 约束说明

#### 调用示例

```
AscendC::Truncate<T, RoundMode::CAST_FLOOR>(dstLocal, srcLocal, 512);
```

结果示例如下：

```
输入数据srcLocal：[-37.063736    64.17277    -33.448692 ... ]
输出数据dstLocal：[-38  64 -34 ... ]
```
