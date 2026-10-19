# h2rint

**页面ID:** atlasascendc_api_07_10504  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10504.html

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

获取与输入数据各元素最接近的整数，若存在两个同样接近的整数，则取其中的偶数。

#### 函数原型

```
inline half2 h2rint(half2 x)
```

```
inline bfloat16x2_t h2rint(bfloat16x2_t x)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |

#### 返回值说明

与输入各元素最接近的整数值。特别场景说明如下：

- 当输入元素为0时，返回值为0。
- 当输入元素为0.5时，返回值为0。
- 当输入元素为1.5时，返回值为2。
- 当输入元素为nan时，返回值为nan。
- 当输入元素为inf时，返回值为inf。
- 当输入元素为-inf时，返回值为-inf。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用half2类型接口需要包含"simt_api/asc_fp16.h"头文件，使用bfloat16x2_t类型接口需要包含"simt_api/asc_bf16.h"头文件。

```
#include "simt_api/asc_fp16.h"
```

```
#include "simt_api/asc_bf16.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void KernelRint(__gm__ half2* dst, __gm__ half2* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = h2rint(x[idx]);
}
```
