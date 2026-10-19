# GetRuntimeUBSize

**页面ID:** atlasascendc_api_07_00190  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00190.html

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

获取运行时UB空间的大小，单位为byte。开发者根据UB的大小来计算循环次数等参数值。

#### 函数原型

```
__aicore__ inline uint32_t GetRuntimeUBSize()
```

#### 参数说明

无

#### 返回值说明

运行时UB空间的大小，单位为字节。

Atlas 350 加速卡架构下，SIMD与SIMT混合场景中，获取到的UB大小上限为216KB，非SIMD与SIMT混合场景返回值为固定值248KB。

#### 约束说明

无

#### 调用示例

本调用示例通过GetRuntimeUBSize获取的UB空间大小，来计算tileNum的值。

```
// 定义待处理数据的总长度（元素个数）
uint32_t totalLength = 126976;
// GetRuntimeUBSize() / sizeof(half) -> 计算 UB 能容纳多少个 half 类型元素
// 除2 -> 预留 50% 的 UB 空间
uint32_t tileLength = AscendC::GetRuntimeUBSize() / sizeof(half) / 2;
// 需要迭代的分片数量：126976 / 63488 = 2
uint32_t tileNum = totalLength / tileLength;
```
