# LogicalAnds

**页面ID:** atlasascendc_api_07_10252  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10252.html

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

输入矢量内的每个元素与标量进行与操作。当输入矢量、标量的数据类型不是bool时，零被视为False，非零数据被视为True。接口中矢量与标量的顺序支持标量在前和标量在后两种场景，其中，标量支持配置为LocalTensor的单点元素。计算公式如下，idx表示LocalTensor单点元素的位置系数：

![](images/atlasascendc_api_07_10252_img_001.png)

#### 函数原型

```
template <const LogicalAndsConfig& config = DEFAULT_LOGICAL_ANDS_CONFIG, typename T, typename U, typename S>
__aicore__ inline void LogicalAnds(const LocalTensor<T>& dst, const U& src0, const S& src1, const uint32_t count)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| config | LogicalAnds算法的相关配置。此参数可选配，LogicalAndsConfig类型，具体定义如下方代码所示，其中参数的含义为： isReuseSource：该参数预留，传入默认值false即可。 scalarTensorIndex：当标量为LocalTensor的单点元素时，该参数用于指定标量作为与操作中的左操作数或右操作数，0表示左操作数，1（默认值）表示右操作数。 |
| T | 目的操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：bool。 |
| U | LocalTensor类型或标量类型。根据输入参数src0自动推导类型，开发者无需配置该参数，保证src0满足数据类型的约束即可。 Atlas 350 加速卡，支持的数据类型为：bool、int8_t、uint8_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、int64_t、uint64_t。 |
| S | LocalTensor类型或标量类型。根据输入参数src1自动推导类型，开发者无需配置该参数，保证src1满足数据类型的约束即可。 Atlas 350 加速卡，支持的数据类型为：bool、int8_t、uint8_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、int64_t、uint64_t。 |

```
struct LogicalAndsConfig {
    bool isReuseSource;
    int8_t scalarTensorIndex;
};
```

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| src0、src1 | 输入 | 源操作数。类型为标量或LocalTensor，类型为LocalTensor时，可以为矢量操作数或标量单点元素，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| count | 输入 | 参与计算的元素个数。 |

#### 约束说明

- 本接口与操作的左操作数及右操作数中必须有一个为矢量，当前不支持左右操作数同时为标量。
- 当传入LocalTensor的单点数据作为标量时，scalarTensorIndex参数需要传入编译期已知的常量，如果传入变量，则需要将该变量声明为constexpr。

- **不支持源操作数与目的操作数地址重叠。**

#### 调用示例

完整样例请参考[logicalands算子样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/12_math/logicalands)。

```
AscendC::LocalTensor<bool> dst;
AscendC::LocalTensor<half> src0, src1;
uint32_t count = 512; // 参与计算的元素个数
// 标量在后
AscendC::LogicalAnds(dst, src0, src1, count); 
// 标量在前
static constexpr AscendC::LogicalAndsConfig config = { false, 0 };
AscendC::LogicalAnds<config>(dst, src0, src1, count);
```

结果示例如下：

```
// 标量在后
输入数据（src0）: 
[1, 2, 0, -1, -2, 0, 3, 4, 0, -3, -4, 0, 5, 6, 0, -5, -6, 0, ... 0]
输入数据（src1）: 
[3.0]
输出数据（dst）: 
[ True,  True,  False,  True,  True,  False,  True,  True,  False,  True,
  True,  False,  True,  True,  False,  True,  True,  False,  ...  False]
// 标量在前
输入数据（src1）: 
[1, 2, 0, -1, -2, 0, 3, 4, 0, -3, -4, 0, 5, 6, 0, -5, -6, 0, ... 0]
输入数据（src0）: 
[3.0]
输出数据（dst）: 
[ True,  True,  False,  True,  True,  False,  True,  True,  False,  True,
  True,  False,  True,  True,  False,  True,  True,  False,  ...  False]
```
