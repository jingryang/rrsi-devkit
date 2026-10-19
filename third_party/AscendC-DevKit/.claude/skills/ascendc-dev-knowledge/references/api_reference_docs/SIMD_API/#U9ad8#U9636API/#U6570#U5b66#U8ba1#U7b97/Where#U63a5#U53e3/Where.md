# Where

**页面ID:** atlasascendc_api_07_10260  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10260.html

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

根据指定的条件，从两个源操作数中选择元素，生成目标操作数。两个源操作数均可以是LocalTensor或标量。

![](images/atlasascendc_api_07_10260_img_001.png)

#### 函数原型

```
template <typename T, typename U, typename S, typename V>
__aicore__ inline void Where(const LocalTensor<T>& dst, const U& src0, const S& src1, const LocalTensor<V>& condition, const uint32_t count)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：bool、int8_t、uint8_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、int64_t、uint64_t。 |
| U | LocalTensor类型或标量类型。根据输入参数src0自动推导类型，开发者无需配置该参数，保证src0的数据类型与目的操作数保持一致即可。 |
| S | LocalTensor类型或标量类型。根据输入参数src1自动推导类型，开发者无需配置该参数，保证src1的数据类型与目的操作数保持一致即可。 |
| V | 条件的数据类型，当前支持的数据类型为：bool。 |

**表2 **参数说明

| **参数名称** | **类型** | **说明** |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| src0、src1 | 输入 | 源操作数。类型为标量或LocalTensor，当类型为LocalTensor时，支持的TPosition为VECIN/VECCALC/VECOUT。 数据类型需要与目的操作数保持一致。 |
| condition | 输入 | 条件操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| count | 输入 | 参与计算的元素个数。 |

#### 约束说明

- **不支持源操作数与目的操作数地址重叠。**
- 操作数地址偏移对齐要求请参见通用说明和约束。

#### 调用示例

完整样例请参考[where算子样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/12_math/where)。

```
AscendC::LocalTensor<half> dst, src0, src1;
AscendC::LocalTensor<bool> condition;
uint32_t count = 512; // 参与计算的元素个数
AscendC::Where(dst, src0, src1,  condition, count);
```

结果示例如下：

```
输入数据（src0）:
[1, 2, 3, ... 511, 512]
输入数据（src1）:
[-1, -2, -3, ... -511, -512]
条件输入数据（condition），为0时选择src1，为1时选择src0:
[0, 1, 0, ... 0, 1]
输出数据（dst）:
[-1, 2, -3, ... -511, 512]
```
