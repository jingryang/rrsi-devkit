# hexp

**页面ID:** atlasascendc_api_07_10402  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10402.html

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

指定输入x，获取e的x次方。

![](images/atlasascendc_api_07_10402_img_001.png)

#### 函数原型

```
inline half hexp(half x)
```

```
inline bfloat16_t hexp(bfloat16_t x)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| x | 输入 | 源操作数。 |

#### 返回值说明

e的x次方。

- 当x为inf时，返回值为inf。
- 当x为-inf时，返回值为0。
- 当x为nan时，返回值为nan。

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用half类型接口需要包含"simt_api/asc_fp16.h"头文件，使用bfloat16_t类型接口需要包含"simt_api/asc_bf16.h"头文件。

```
#include "simt_api/asc_fp16.h"
```

```
#include "simt_api/asc_bf16.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void KernelExp(__gm__ half* dst, __gm__ half* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = hexp(x[idx]);
}
```
