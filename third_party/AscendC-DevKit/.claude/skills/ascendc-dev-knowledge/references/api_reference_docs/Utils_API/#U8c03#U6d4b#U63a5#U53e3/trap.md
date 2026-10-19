# __trap

**页面ID:** atlasascendc_api_07_10429  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10429.html

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

在SIMT VF实现代码中调用此接口会中断算子的运行，适用于Kernel侧异常场景的调试。

#### 函数原型

```
__simt_callee__ inline void __trap()
```

#### 参数说明

无

#### 约束说明

无

#### 需要包含的头文件

使用该接口需要包含"utils/debug/asc_assert.h"头文件。

```
#include "utils/debug/asc_assert.h"
```

#### 调用示例

```
__simt_vf__ __launch_bounds__(1024) inline void SimtKernel(__gm__ bool* dst, __gm__ float* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    if (isnan(x[idx])) {
        __trap();
    }
    dst[idx] = x[idx];
}
```
