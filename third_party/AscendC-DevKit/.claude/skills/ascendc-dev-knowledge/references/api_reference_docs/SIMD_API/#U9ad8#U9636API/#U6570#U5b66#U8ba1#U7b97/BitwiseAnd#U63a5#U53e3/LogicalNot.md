# LogicalNot

**页面ID:** atlasascendc_api_07_10246  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10246.html

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

按元素进行取反操作。当输入的数据类型不是bool时，零被视为False，非零数据被视为True。

![](images/atlasascendc_api_07_10246_img_001.png)

#### 函数原型

```
template <const LogicalNotConfig& config = DEFAULT_LOGICAL_NOT_CONFIG, typename T, typename U>
__aicore__ inline void LogicalNot(const LocalTensor<T>& dst, const LocalTensor<U>& src, const uint32_t count)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| config | LogicalNot算法的相关配置。此参数可选配，LogicalNotConfig类型，具体定义如下方代码所示，其中参数的含义为： isReuseSource：该参数预留，传入默认值false即可。 |
| T | 目的操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：bool。 |
| U | 源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：bool、int8_t、uint8_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、int64_t、uint64_t。 |

```
struct LogicalNotConfig {
    bool isReuseSource;
};
```

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| src | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| count | 输入 | 参与计算的元素个数。 |

#### 约束说明

- **不支持源操作数与目的操作数地址重叠。**

#### 调用示例

完整样例请参考[logicalnot算子样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/12_math/logicalnot)。

```
AscendC::LocalTensor<bool> dst;
AscendC::LocalTensor<half> src;
uint32_t count = 512; // 参与计算的元素个数
AscendC::LogicalNot(dst, src, count);
```

结果示例如下：

```
输入数据（src）: 
[1, 2, 0, -1, -2, 0, 3, 4, 0, -3, -4, 0, 5, 6, 0, -5, -6, 0, ... 0]
输出数据（dst）: 
[False, False, True, False, False, True, False, False, True, False,
 False, True, False, False, True, False, False, True, ... True]
```
