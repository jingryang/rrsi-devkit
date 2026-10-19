# assert

**页面ID:** atlasascendc_api_07_10428  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_10428.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

本接口在SIMD和SIMT VF调试场景下（SIMT VF仅支持Atlas 350 加速卡）提供assert断言功能。在算子Kernel侧的实现代码中，如果assert的内部条件判断不为真，则会输出assert条件，并将输入的信息格式化打印在屏幕上，同时算子运行失败。

在算子Kernel侧代码的适当位置使用assert进行断言检查，并格式化输出一些调试信息。示例如下：

```
int assertFlag = 10;

assert(assertFlag == 10);
```

打印信息示例如下：

```
[ASSERT] /home/.../add_custom.cpp:44: : Assertion `assertFlag != 10' failed.
```

请注意，assert接口的打印功能对算子的实际运行性能有影响。

#### 函数原型

```
assert(expr)
```

#### 参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| expr | 输入 | assert断言是否终止程序的条件。条件为true则程序继续执行，条件为false则终止程序。 |

#### 约束说明

- 该接口当前仅支持融合编译场景。
- SIMD场景，如果开发者需要包含标准库头文件<cassert>，请在"utils/debug/asc_assert.h"头文件之前包含，避免assert符号冲突。

#### 需要包含的头文件

使用该接口需要包含"utils/debug/asc_assert.h"头文件。

```
#include "utils/debug/asc_assert.h"
```

#### SIMD调用示例

```
// SIMD
__global__ __cube__ void simp_test_equal(int a)
{
    // input a is 7
    assert(a == 6);
}
```

程序运行时会触发assert，打印效果如下：

```
[ASSERT] test_assert.asc:41: : Assertion `a == 6' failed.
```

#### SIMT调用示例

```
//SIMT VF
__simt_vf__ __launch_bounds__(1024) inline void AddCustom(__gm__ bool* dst, __gm__ float* x)
{
    int idx = threadIdx.x + blockIdx.x * blockDim.x;
    assert(!isnan(x[idx]));
    dst[idx] = x[idx];
}
```

程序运行时会触发assert，打印效果如下：

```
[ASSERT] /home/.../add_custom.cpp:44: : Assertion `!isnan(x[idx])' failed.
```
