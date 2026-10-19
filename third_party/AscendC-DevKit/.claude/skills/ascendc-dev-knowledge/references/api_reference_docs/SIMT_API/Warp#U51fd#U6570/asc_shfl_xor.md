# asc_shfl_xor

**页面ID:** atlasascendc_api_07_10394  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10394.html

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

获取Warp内当前线程LaneId与输入lane_mask做异或操作（LaneId^lane_mask）得到的dstLaneId对应线程输入的用于交换的var值；如果目标线程是非活跃状态，获取到寄存器中未初始化的值。其中，参数width用于划分Warp内线程的分组。参数width设置参与交换的32个线程的分组宽度，默认值为32，即所有线程分为1组。

在多个分组场景（width小于32）下，每个线程获取位于本组内或线程编号更小的组内的dstLaneId对应线程的var值；也就是说，如果dstLaneId小于当前线程所在分组的起始LaneId，dstLaneId对应的线程位于线程编号更小的组内，则可以获取该dstLaneId线程的var值；如果dstLaneId大于当前线程所在分组的最大LaneId，则返回当前线程的var值。

例如，Warp内32个活跃线程调用asc_shfl_xor(LaneId, 1, 16)接口，每个线程的返回值为当前线程LaneId^1对应线程的var值。

**图1 **asc_shfl_xor结果示意图
![](images/atlasascendc_api_07_10394_img_001.png)

#### 函数原型

```
inline int32_t asc_shfl_xor(int32_t var, int32_t lane_mask, int32_t width = warpSize)
```

```
inline uint32_t asc_shfl_xor(uint32_t var, int32_t lane_mask, int32_t width = warpSize)
```

```
inline float asc_shfl_xor(float var, int32_t lane_mask, int32_t width = warpSize)
```

```
inline int64_t asc_shfl_xor(int64_t var, int32_t lane_mask, int32_t width = warpSize)
```

```
inline uint64_t asc_shfl_xor(uint64_t var, int32_t lane_mask, int32_t width = warpSize)
```

```
inline half asc_shfl_xor(half var, int32_t lane_mask, int32_t width = warpSize)
```

```
inline half2 asc_shfl_xor(half2 var, int32_t lane_mask, int32_t width = warpSize)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| var | 输入 | 线程用于交换的输入操作数。 |
| lane_mask | 输入 | 与当前线程LaneId做异或运算的操作数。取值范围为[0, 32)，且小于width。 |
| width | 输入 | Warp内参与交换的线程的分组宽度，默认值为32。width的取值范围为(0, 32]，width必须是2的倍数。 |

#### 返回值说明

- Warp内指定线程的var值
- 未初始化undefined的值

#### 约束说明

无

#### 需要包含的头文件

使用除half、half2类型之外的接口需要包含"simt_api/device_warp_functions.h"头文件，使用half和half2类型接口需要包含"simt_api/asc_fp16.h"头文件。

```
#include "simt_api/device_warp_functions.h"
```

```
#include "simt_api/asc_fp16.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

```
__simt_vf__ __launch_bounds__(1024) inline void KernelShflXor(__gm__ int32_t* dst)
{
    // asc_vf_call参数：dim3{1024, 1, 1}
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    int32_t laneId = idx % 32;
    // 0-15线程返回值分别为{1,0,3,2,5,4,7,6,9,8,11,10,13,12,15,14}
    // 16-31线程返回值为{17,16,19,18,21,20,23,22,25,24,27,26,29,28,31,30}
     int32_t result = asc_shfl_xor(laneId, 1, 16);
     dst[idx] = result;
}

// asc_shfl_xor实现reducesum
__simt_vf__ __launch_bounds__(1024) inline void KernelShflXorReduceSum(__gm__ int32_t* dst)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    int32_t laneId = idx % 32;
    int32_t value = laneId;

    value += asc_shfl_xor(value, 1, 31);  // 1
    value += asc_shfl_xor(value, 2, 31);  // 2
    value += asc_shfl_xor(value, 4, 31);  // 4
    value += asc_shfl_xor(value, 8, 31);  // 8
    value += asc_shfl_xor(value, 16, 31); // 16

    dst[idx] = value;
}
```
