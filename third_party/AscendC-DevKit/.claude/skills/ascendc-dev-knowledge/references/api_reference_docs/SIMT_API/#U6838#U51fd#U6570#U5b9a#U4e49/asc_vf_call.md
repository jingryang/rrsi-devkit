# asc_vf_call

**页面ID:** atlasascendc_api_07_10303  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10303.html

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

在SIMD与SIMT混合编程场景，启动SIMT VF（Vector Function）子任务，通过参数配置，启动指定数目的线程，执行指定的SIMT核函数。

> **注意:** 

asc_vf_call启动SIMT VF子任务时，子任务函数不能是类的成员函数，推荐使用普通函数或类静态函数，且入口函数必须使用__simt_vf__修饰宏。

asc_vf_call启动SIMT VF子任务时，传递的参数只支持裸指针，常见基本数据类型。不支持传递结构体，数组等。

#### 函数原型

```
template <auto funcPtr, typename... Args>
__aicore__ inline void asc_vf_call(dim3 threadNums, Args &&...args)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| funcPtr | 用于指定SIMT入口核函数。 |
| Args | 定义可变参数，用于传递实参到SIMT入口核函数。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| threadNums | 输入 | dim3结构，定义为{dimx，dimy，dimz}，用于指定SIMT线程块内线程数量。线程总数为dimx * dimy * dimz，该值的大小必须小于等于2048。 |
| args | 输入 | 可变参数，用于传递实参到SIMT入口核函数。 |

#### 约束说明

SIMT编程场景不支持使用该接口。

#### 需要包含的头文件

使用该接口需要包含"simt_api/common_functions.h"头文件。

```
#include "simt_api/common_functions.h"
```

#### 调用示例

SIMD与SIMT混合编程场景：

对Global Memory数据做加法计算。

```
__simt_vf__ __launch_bounds__(2048) inline void SimtCompute(
    __gm__ float* dst, __gm__ float* src0, __gm__ float* src1, int count) const
{
    // simt 代码
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    dst[idx] = src0[idx] + src1[idx];
}

__global__ __vector__ void SimtComputeShell(__gm__ float* x, __gm__ float* y, __gm__ float* z, const int size)
{
    __gm__ float* dst = x;
    __gm__ float* src0 = y;
    __gm__ float* src1 = z;
    // asc_vf_call启动SIMT VF子任务
    asc_vf_call<SimtCompute>(dim3{1024, 1, 1}, dst, src0, src1, size);
}
```
