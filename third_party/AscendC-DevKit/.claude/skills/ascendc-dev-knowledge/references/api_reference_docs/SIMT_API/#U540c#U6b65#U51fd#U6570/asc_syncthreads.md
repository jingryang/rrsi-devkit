# asc_syncthreads

**页面ID:** atlasascendc_api_07_10306  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10306.html

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

等待当前线程块内所有线程代码都执行到该函数位置。

#### 函数原型

```
inline void asc_syncthreads()
```

#### 参数说明

无

#### 约束说明

SIMT编程场景当前不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/device_sync_functions.h"头文件。

```
#include "simt_api/device_sync_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void KernelSyncThreads(__gm__ float* dst, int count)
{
     int idx = threadIdx.x;
     if (idx > 0 && idx < count) {
         dst[idx] = 1;
     }

     // 等待block内所有thread都执行到当前代码
     asc_syncthreads();

     if (idx == 0) {
         dst[0] = 0;
         for(int i = 1023; i > 0; i--) {
             dst[0] += dst[i];
         }
     }
}
```

```
输出结果:
[1023, 1, 1, 1 …]
```
