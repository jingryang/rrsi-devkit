# BitwiseOr

**页面ID:** atlasascendc_api_07_10269  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10269.html

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

逐比特对两个输入进行或操作。

![](images/atlasascendc_api_07_10269_img_001.png)

#### 函数原型

```
template <const BitwiseOrConfig& config = DEFAULT_BITWISE_OR_CONFIG, typename T>
__aicore__ inline void BitwiseOr(const LocalTensor<T>& dst, const LocalTensor<T>& src0, const LocalTensor<T>& src1, const uint32_t count)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| config | BitwiseOr算法的相关配置。此参数可选配，BitwiseOrConfig类型，具体定义如下方代码所示，其中参数的含义为： isReuseSource：该参数预留，传入默认值false即可。 |
| T | 源操作数、目的操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t、uint8_t、int16_t、uint16_t、int32_t、uint32_t、int64_t、uint64_t。 |

```
struct BitwiseOrConfig {
    bool isReuseSource;
};
```

**表2 **参数说明

| **参数名称** | **类型** | **说明** |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| src0、src1 | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 数据类型需要与目的操作数保持一致。 |
| count | 输入 | 参与计算的元素个数。 |

#### 约束说明

- **不支持源操作数与目的操作数地址重叠。**
- 操作数地址偏移对齐要求请参见通用说明和约束。

#### 调用示例

完整样例请参考[bitwiseor算子样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/12_math/bitwiseor)。

```
AscendC::LocalTensor<uint32_t> src0, src1;
AscendC::LocalTensor<uint32_t> dst;
uint32_t count = 512; // 参与计算的元素个数
AscendC::BitwiseOr(dst, src0, src1, 512);
```

结果示例如下：

```
输入数据（src0）:
[-111, -83, 95, -52, ... -102]
输入数据（src1）:
[64, -44, 45, -117, ... -107]
输入数据（dst）:
[-47, -3, 127, -49, ... -97]
```
