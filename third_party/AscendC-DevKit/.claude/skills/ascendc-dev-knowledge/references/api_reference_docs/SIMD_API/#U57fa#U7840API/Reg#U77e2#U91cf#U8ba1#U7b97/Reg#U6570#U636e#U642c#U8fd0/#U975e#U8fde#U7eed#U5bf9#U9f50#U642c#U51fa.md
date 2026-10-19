# 非连续对齐搬出

**页面ID:** atlasascendc_api_07_0322  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0322.html

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

Reg矢量计算数据搬运接口，适用于从RegTensor非连续对齐搬出到UB（以DataBlock为单位）。

#### 函数原型

```
// 正常场景
template <typename T = DefaultType, DataCopyMode dataMode, typename U>
__simd_callee__ inline void StoreAlign(__ubuf__ T* dstAddr, U& srcReg, uint32_t dataBlockStride, MaskReg& mask);
// POST_MODE_UPDATE场景
template <typename T = DefaultType, DataCopyMode dataMode, PostLiteral postMode, typename U>
__simd_callee__ inline void StoreAlign(__ubuf__ T*& dstAddr, U& srcReg, uint32_t dataBlockStride, uint32_t repeatStride, MaskReg& mask);
```

#### 参数说明

**表1 **DataCopyMode模板参数说明

| DataCopyMode取值 | 含义 |
| --- | --- |
| DATA_BLOCK_COPY | 用来在非连续对齐场景选择搬运模式。当前仅支持DataBlock搬运模式，即以DataBlock为粒度进行搬运。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32。 |
| postMode | 输入 | 用于控制是否使能post update，PostLiteral类型。 |
| U | 输入 | RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| srcReg | 输入 | 源操作数，类型为RegTensor。 |
| dstAddr | 输入 | 目的操作数在UB上的起始地址。 |
| dataBlockStride | 输入 | 单次搬运相邻DataBlock间的间隔（前面一个DataBlock的头与后面DataBlock的头的间隔），单位为DataBlock。 |
| repeatStride | 输入 | POST_MODE_NORMAL与POST_MODE_UPDATE场景下repeatStride含义不一致。 - POST_MODE_NORMAL场景：实际搬运UB起始地址为dstAddr + repeatStride * 32。- POST_MODE_UPDATE场景：实际搬运UB起始地址为dstAddr，搬运后执行地址更新dstAddr +=  repeatStride * 32。 |
| mask | 输入 | MaskReg类型，指示在搬运过程中哪些元素有效。 某个DataBlock对应的32bit全为0时，即使该UB越界也不会报错。 |

#### 约束说明

无

#### 调用示例

```
__simd_vf__ inline void Compute(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<T>();
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        AscendC::Reg::LoadAlign<T, AscendC::Reg::DataCopyMode::DATA_BLOCK_COPY, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(srcReg, srcAddr, 1, i * 8, mask);
        AscendC::Reg::StoreAlign<T, AscendC::Reg::DataCopyMode::DATA_BLOCK_COPY, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(dstAddr, srcReg, 1, i * 8, mask);
    }
}
```
