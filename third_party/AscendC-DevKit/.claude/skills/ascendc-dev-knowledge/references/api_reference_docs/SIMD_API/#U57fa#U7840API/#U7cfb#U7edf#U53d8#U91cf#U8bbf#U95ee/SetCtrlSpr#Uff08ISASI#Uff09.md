# SetCtrlSpr(ISASI)

**页面ID:** atlasascendc_api_07_00091  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00091.html

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

对CTRL寄存器（控制寄存器）的特定比特位进行设置。

#### 函数原型

```
template <int8_t startBit, int8_t endBit>
__aicore__ static inline void SetCtrlSpr(int64_t value)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| startBit | 起始比特位索引。 |
| endBit | 终止比特位索引。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| value | 输入 | 起止比特位上新设置的值。 |

**表3 **常用CTRL寄存器比特位说明

| CTRL寄存器比特位 | 功能 | 默认值 | 配合使用的API |
| --- | --- | --- | --- |
| CTRL[8:6] | 用于控制数据从L0C Buffer/Unified Buffer/L1 Buffer搬运至Global Memory时原子操作的使能及数据类型选择。 - 3'b000：不使能原子操作；- 3'b001：使能原子操作，数据类型为float；- 3'b010：使能原子操作，数据类型为half；- 3'b011：使能原子操作，数据类型为int16_t；- 3'b100：使能原子操作，数据类型为int32_t；- 3'b101：使能原子操作，数据类型为int8_t；- 3'b110：使能原子操作，数据类型为bfloat16_t。 | 3'b000 | 不涉及 |
| CTRL[10:9] | 用于控制原子操作的类型，仅在CTRL[8:6]使能原子操作时生效。 - 2'b00：选择ADD操作；- 2'b01：选择MAX操作；- 2'b10：选择MIN操作。 | 2'b00 | 不涉及 |
| CTRL[45] | 用于控制左右矩阵数据做Mmad计算时的处理方式。 - 1'b0：按照原数据类型进行处理；- 1'b1：左右矩阵数据均为fp8_e4m3fn_t时，数据视为hifloat8_t进行矩阵乘法计算。其他场景按照原数据类型进行处理。 | 1'b0 | 不涉及 |
| CTRL[48] | 用于控制浮点数计算和浮点数精度转换时的饱和模式，仅在CTRL[60]使能时生效。 - 1'b0：饱和模式，INF输出会被饱和为±MAX， NaN输出会被饱和为0；- 1'b1：非饱和模式，INF/NAN保持原输出。 该控制位仅支持如下数据类型： - 浮点数计算时支持half数据类型；- 浮点数精度转换时支持如下数据类型：hifloat8_t、fp8_e8m0_t、fp8_e5m2_t、fp8_e4m3fn_t、half、bfloat16_t。 | 1'b0 | 配合使用的API： - 矢量计算API- 原子操作API- 精度转换指令 使用约束： - 需要满足数据类型限制。- 执行原子操作过程中，如果需要重新配置该控制位，需要调用DataCacheCleanAndInvalid先清除当前Cache Line状态并将当前数据写出，防止饱和模式变更影响当前数据。具体调用示例可参考原子操作中，half类型配置全局非饱和模式示例。 |
| CTRL[50] | 用于控制浮点数精度转换时的NAN饱和模式，在CTRL[48]设置为饱和模式时生效。 1'b0：NAN输出会被转换为0.0； 1'b1：NAN输出会保持NAN。 该控制位仅支持如下数据类型： fp8_e8m0_t、fp8_e5m2_t、fp8_e4m3fn_t。 | 1'b0 | 精度转换指令（需要满足数据类型限制）。 |
| CTRL[53] | 用于控制整数计算指令的饱和模式。 1'b0：截断模式，溢出值按目标数据类型位数截断，保留低位，舍弃高位； 1'b1：饱和模式，溢出值饱和到±MAX。 | 1'b0 | 矢量计算API（输入输出数据类型为整数）。 |
| CTRL[59] | 用于控制浮点数转整数或整数转整数时的精度转换饱和模式，仅在CTRL[60]使能时生效。 1'b0：饱和模式：溢出值饱和到±MAX； 1'b1：截断模式：溢出值按目标数据类型位数截断，保留低位，舍弃高位。 | 1'b0 | 精度转换指令。 |
| CTRL[60] | 用于控制饱和模式的全局生效方式。 1'b0：单指令设置饱和； 1'b1：全局设置饱和。 | 1'b1 | 该控制位可与Reg矢量计算API Cast配合使用，或与CTRL[48]、CTRL[59]配合使用，具体配置信息参考表4。 |

**表4 **饱和模式全局或单指令生效配置表

| 全局使能位 | 控制位 | 功能描述 |
| --- | --- | --- |
| CTRL[60] = 1'b0 | Reg矢量计算Cast API的trait模板参数中satMode设置为SatMode::NO_SAT。 | 单指令非饱和模式。 |
| Reg矢量计算Cast API的trait模板参数中satMode设置为 SatMode::SAT。 | 单指令饱和模式。 |  |
| CTRL[60] = 1'b1 | CTRL[48] = 1'b1 | 全局非饱和模式（浮点数计算和浮点数精度转换）。 |
| CTRL[48] = 1'b0 | 全局饱和模式（浮点数计算和浮点数精度转换）。 |  |
| CTRL[59] = 1'b1 | 全局非饱和模式（浮点数转整数或整数转整数时的精度转换）。 |  |
| CTRL[59] = 1'b0 | 全局饱和模式（浮点数转整数或整数转整数时的精度转换）。 |  |

#### 约束说明

- 仅支持CTRL[8:6]、CTRL[10:9]、CTRL[45]、CTRL[48]、CTRL[50]、CTRL[53]、CTRL[59]、CTRL[60]比特位。
- 对于CTRL[8:6]和CTRL[10:9]的设置，已封装原子操作API，建议通过这些原子操作API进行配置。

  - SetAtomicType
  - DisableDmaAtomic
  - SetAtomicAdd
  - SetAtomicMax
  - SetAtomicMin

#### 调用示例

- 如下示例中使能原子操作模式，数据类型为float。

```
AscendC::SetCtrlSpr<6, 8>(1);
```

- 原子操作中，half类型配置全局非饱和模式示例。

```
AscendC::SetCtrlSpr<6, 8>(2);
AscendC::SetAtomicAdd<half>();
AscendC::DataCacheCleanAndInvalid<half, AscendC::CacheLine::ENTIRE_DATA_CACHE, AscendC::DcciDst::CACHELINE_ATOMIC>(dstTensor);
AscendC::SetCtrlSpr<48, 48>(1);
...
```
