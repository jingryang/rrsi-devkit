# BitwiseAnd

**页面ID:** atlasascendc_api_07_10249  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10249.html

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

逐比特对两个输入进行与操作。

![](images/atlasascendc_api_07_10249_img_001.png)

#### 函数原型

```
template <const BitwiseAndConfig& config = DEFAULT_BITWISE_AND_CONFIG, typename T>
__aicore__ inline void BitwiseAnd(const LocalTensor<T>& dst, const LocalTensor<T>& src0, const LocalTensor<T>& src1, const uint32_t count)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| config | BitwiseAnd算法的相关配置。此参数可选配，BitwiseAndConfig类型，具体定义如下方代码所示，其中参数的含义为： isReuseSource：该参数预留，传入默认值false即可。 |
| T | 操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t、uint8_t、int16_t、uint16_t、int32_t、uint32_t、int64_t、uint64_t。 |

```
struct BitwiseAndConfig {
    bool isReuseSource;
};
```

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| src0、src1 | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 源操作数的数据类型与目的操作数保持一致。 |
| count | 输入 | 参与计算的元素个数。 |

#### 约束说明

- **不支持源操作数与目的操作数地址重叠。**

#### 调用示例

完整样例请参考[bitwiseand算子样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/12_math/bitwiseand)。

```
AscendC::LocalTensor<uint16_t> dst, src0, src1;
uint32_t count = 512; // 参与计算的元素个数
AscendC::BitwiseAnd(dst, src0, src1, count);
```

结果示例如下：

```
输入数据（src0）: 
[93, 87, 99, 1, 87, 58, 6, 16, 85, 66, 56, 65, 24, 98, 96, 50, 18, 37, 0, ... 66]
输入数据（src1): 
[81, 12, 33, 47, 47, 18, 82, 44, 91, 34, 17, 99, 7, 82, 42, 85, 88, 99, 61, ... 81]
输出数据（dst）: 
[81, 4, 33, 1, 7, 18, 2, 0, 81, 2, 16, 65, 0, 66, 32, 16, 16, 33, 0, ... 64]
```
