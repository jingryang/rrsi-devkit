# SetFixpipeNz2ndFlag

**页面ID:** atlasascendc_api_07_0253  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0253.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

DataCopy（CO1->GM、CO1->A1）过程中进行随路格式转换（NZ格式转换为ND格式）时，通过调用该接口设置格式转换的相关配置。

#### 函数原型

```
__aicore__ inline void SetFixpipeNz2ndFlag(uint16_t ndNum, uint16_t srcNdStride, uint16_t dstNdStride)
// 如下原型仅支持Atlas 350 加速卡
__aicore__ inline void SetFixpipeNz2ndFlag(uint16_t ndNum, uint16_t srcNdStride, uint32_t dstNdStride)
```

#### 参数说明

**表1 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| ndNum | 输入 | nd的数量，类型是uint16_t，取值范围：ndNum∈[1, 65535]。 |
| srcNdStride | 输入 | 以分形大小为单位的源步长，源相邻nz矩阵的偏移（头与头）。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，srcNdStride∈[1, 512]，单位：fractal_size 1024B。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，srcNdStride∈[1, 512]，单位：fractal_size 1024B。 Atlas 200I/500 A2 推理产品，srcNdStride∈[1, 512]，单位：fractal_size 1024B。 Atlas 350 加速卡，srcNdStride∈[0, 65535]，单位：C0_SIZE。 |
| dstNdStride | 输入 | 目的相邻nd矩阵的偏移（头与头）。单位为元素。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，dstNdStride∈[1, 65535]。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，dstNdStride∈[1, 65535]。 Atlas 200I/500 A2 推理产品，dstNdStride∈[1, 65535]。 Atlas 350 加速卡，dstNdStride∈[1, 232 -1]。 |

#### 约束说明

无

#### 调用示例

完整示例可参考完整示例。

```
uint16_t ndNum = 2;
uint16_t srcNdStride = 2;
uint16_t dstNdStride = 1;
AscendC::SetFixpipeNz2ndFlag(ndNum, srcNdStride, dstNdStride); // 设置FIX搬运NZ格式到ND格式转换的参数
```
