# __asc_cvt_float2_to_fp8x2

**页面ID:** atlasascendc_api_07_10634  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10634.html

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

将float2类型数据的两个分量，按照CAST_RINT模式转换为指定类型（float8_e4m3x2_t和float8_e5m2x2_t）的8位浮点数，并根据指定的饱和模式（饱和或非饱和）进行溢出处理。转换结果以位级打包形式存储为__asc_fp8x2_storage_t类型，该类型为16位无符号整数unsigned short int，用于存储float8_e4m3x2_t或float8_e5m2x2_t类型的数据。

#### 函数原型

```
__asc_fp8x2_storage_t __asc_cvt_float2_to_fp8x2(const float2 x, const __asc_saturation_t saturate, const __asc_fp8_interpretation_t fp8_interpretation)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |
| saturate | 输入 | 控制饱和行为，支持的取值为：__ASC_NOSAT、__ASC_SATFINITE。 __ASC_NOSAT表示使用非饱和模式，__ASC_SATFINITE表示使用饱和模式。 |
| fp8_interpretation | 输入 | 指定转换类型，支持的取值为：__ASC_E4M3、__ASC_E5M2。 __ASC_E4M3表示转换为float8_e4m3x2_t格式的浮点数，__ASC_E5M2表示转换为float8_e5m2x2_t格式的浮点数。 |

#### 返回值说明

输入的两个分量遵循CAST_RINT模式，根据指定的8位浮点数类型和指定的饱和模式，转换成的__asc_fp8x2_storage_t类型数据。

- float8_e4m3_t数据类型没有inf值，非饱和模式下输入超出该类型所能表示的范围时，其溢出结果为nan，饱和模式下溢出结果为该类型表示的最大值或最小值。
- float8_e5m2_t类型则有inf值，非饱和模式下输入超出该类型所能表示的范围，转换结果为对应符号的inf值，饱和模式下溢出结果为该类型表示的最大值或最小值。
- 饱和模式下，对于float8_e5m2_t和float8_e4m3_t数据类型，当寄存器CTRL[50]=0时，nan值会被转换为0，当寄存器CTRL[50]=1时，nan值被转化为fp8类型下的nan值。CTRL寄存器值可通过GetCtrlSpr(ISASI)接口获取。

#### 约束说明

使用此接口前需将CTRL[60]寄存器设置为0，否则饱和行为控制不生效。设置方式请参见控制饱和行为的方式。

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/asc_fp8.h"头文件。

```
#include "simt_api/asc_fp8.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
// 使用小向量可提升数据搬运效率
__simt_vf__ __launch_bounds__(1024) inline void simt_asc_cvt_float2_to_fp8x2(__gm__ float2* input, __gm__ uint16_t* output, uint32_t input_total_length)
{
    uint32_t idx = blockIdx.x * blockDim.x + threadIdx.x;
    // 每个线程处理1个float2类型的数据，即2个float类型的数据，因此idx >= input_total_length / 2的线程不处理数据
    if (idx >= input_total_length / 2) {
        return;
    }
    output[idx] = __asc_cvt_float2_to_fp8x2(input[idx], __ASC_NOSAT, __ASC_E4M3);
}
__global__ __vector__ void cast_kernel(__gm__ float* input, __gm__ uint16_t* output, uint32_t input_total_length)
{
    asc_vf_call<simt_asc_cvt_float2_to_fp8x2>(dim3(1024), (__gm__ float2*)input, output, input_total_length);
}
```
