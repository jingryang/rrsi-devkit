# EXTERN_IMPL_BUFPOOL宏

**页面ID:** atlasascendc_api_07_0128  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0128.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | √ |

#### 功能说明

开发者可以通过TBufPool类手动管理Unified Buffer、L1 Buffer物理内存。

TBufPool类切分的内存块都是连续的，开发者可能有一些自定义的内存块分配需求，比如不连续内存块、内存块在不同TQue之间共享等，这时就需要开发者自定义一个TBufPool的实现。

为了简化开发者的自定义实现，提供EXTERN_IMPL_BUFPOOL宏来辅助用户自定义TBufPool。使用自定义TBufPool功能时，需要注意：

- 自定义TBufPool之前，必须通过TPipe::InitBufPool接口进行TBufPool内存资源池初始化。
- 自定义TBufPool需要开发者自行实现对TQue/TBuf内存块的分配、初始化、释放等操作。

EXTERN_IMPL_BUFPOOL宏内部定义的函数Reset、Init、GetBufHandle、SetCurAddr、GetCurAddr、SetCurBufSize、GetCurBufSize接口参见后续章节描述。使用该宏后，即可使用上述接口完成自定义TBufPool功能。

> **注意:** 

自定义TBufPool相关接口为试验接口，在后续版本中可能会调整或改进，不保证后续兼容性。请开发者在使用过程中关注后续版本更新。

#### 函数原型

```
// 省略宏定义具体内容
#define EXTERN_IMPL_BUFPOOL(EXT_BUFPOOL, POSITION, BUFID_SIZE) ...
```

#### 参数说明

**表1 **EXTERN_IMPL_BUFPOOL宏原型定义参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| EXT_BUFPOOL | 输入 | 自定义TBufPool类名。 |
| POSITION | 输入 | 自定义TBufPool逻辑位置，可以为VECIN、VECOUT、VECCALC、A1、B1、C1。关于TPosition的具体介绍请参考TPosition。 |
| BUFID_SIZE | 输入 | 自定义TBufPool分配的Buffer块数量，建议不超过16。 |

#### 约束说明

无

#### 调用示例

详细示例请参考[自定义TBufPool样例](https://gitcode.com/cann/asc-devkit/tree/master/examples/01_simd_cpp_api/02_features/03_basic_api/04_resource_management/customized_tbuf_pool)。

如下示例中，为tbufPool0划分65536 * 3大小的内存，然后自定义MyBufPool的InitBuffer函数，实现TQue和Tbuf的内存分配。

```
#include "kernel_operator.h"

class MyBufPool {
public:
    __aicore__ inline MyBufPool() {
        Init();
    }

    template<class T> 
    __aicore__ inline bool InitBuffer(T& que, uint8_t num, uint32_t len) {
    }

    template<AscendC::TPosition bufPos>
    __aicore__ inline bool InitBuffer(AscendC::TBuf<bufPos>& buf, uint32_t len) {
    }

    // MyBufPool，自定义TBufPool类名。自定义TBufPool逻辑位置选择VECCALC。
    // 自定义TBufPool分配的Buffer块数量为16
    EXTERN_IMPL_BUFPOOL(MyBufPool, AscendC::TPosition::VECCALC, 16);
};
```
