# __ushort_as_half

**页面ID:** atlasascendc_api_07_10809  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10809.html

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

将unsigned short int的数据按位重新解释为half，即将unsigned short int的数据存储的位按照half的格式进行读取。

#### 函数原型

```
inline half __ushort_as_half(const unsigned short int x)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |

#### 返回值说明

unsigned short int的数据按位重新解释为half的值。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/asc_fp16.h"头文件。

```
#include "simt_api/asc_fp16.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void kernel__ushort_as_half(__gm__ half * dst, __gm__ unsigned short int* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = __ushort_as_half(x[idx]);
}
```
