# MaskReg搬出

**页面ID:** atlasascendc_api_07_0326  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0326.html

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

Reg矢量计算数据搬运接口，适用于从MaskReg搬出到UB。

#### 函数原型

```
// MaskReg搬出使用AddrReg存储偏移量
template <typename T, MaskDist dist = MaskDist::DIST_NORM>
__simd_callee__ inline void StoreAlign(__ubuf__ T* dstAddr, MaskReg& mask, AddrReg offset);

// MaskReg搬出POST_MODE_NORMAL场景
template <typename T, MaskDist dist = MaskDist::DIST_NORM>
__simd_callee__ inline void StoreAlign(__ubuf__ T* dstAddr, MaskReg& mask);

// MaskReg搬出POST_MODE_UPDATE场景
template <typename T, PostLiteral postMode, MaskDist dist = MaskDist::DIST_NORM>
__simd_callee__ inline void StoreAlign(__ubuf__ T*& dstAddr, MaskReg& mask, int32_t offset);

// MaskReg非对齐搬出
template <typename T>
__simd_callee__ inline void StoreUnAlign(__ubuf__ T*& dstAddr, MaskReg& mask, UnalignRegForStore& ureg);
```

#### 参数说明

**表1 **MaskReg搬出使用AddrReg存储偏移量参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 支持的数据类型为b8/b16/b32。 |
| dist | 输入 | 搬运模式，MaskDist类型。取值如下： - DIST_NORM，对齐约束为VL/8Byte，正常模式，搬运VL/8Byte数据。- DIST_PACK，对齐约束为VL/16Byte，下采样模式，搬运VL/16Byte数据，每间隔1bit被舍弃。 |
| mask | 输入 | 源操作数，类型为MaskTensor。 |
| dstAddr | 输出 | 目的操作数在UB上的起始地址。 |
| offset | 输入 | 实际搬运UB起始地址为dstAddr + offset。 |

**表2 **MaskReg搬出POST_MODE_NORMAL场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 支持的数据类型为b8/b16/b32/b64。 |
| dist | 输入 | 搬运模式，MaskDist类型。取值如下： - DIST_NORM，对齐约束为VL/8Byte，正常模式，搬运VL/8Byte数据。- DIST_PACK，对齐约束为VL/16Byte，下采样模式，搬运VL/16Byte数据，每间隔1bit被舍弃。 |
| mask | 输入 | 源操作数，类型为MaskReg。 |
| dstAddr | 输出 | 目的操作数在UB上的起始地址。 |

**表3 **MaskReg搬出POST_MODE_UPDATE场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 支持的数据类型为b8/b16/b32/b64。 |
| dist | 输入 | 搬运模式，MaskDist类型。取值如下： - DIST_NORM，对齐约束为VL/8Byte，正常模式，搬运VL/8Byte数据。- DIST_PACK，对齐约束为VL/16Byte，下采样模式，搬运VL/16Byte数据，每间隔1bit被舍弃。 |
| postMode | 输入 | 用于控制是否使能post update。 - POST_MODE_NORMAL，正常场景，UB操作数地址不更新。 - POST_MODE_UPDATE，POST_MODE_UPDATE场景使用，UB地址同时作为输入和输出，每次调用会更新。 |
| mask | 输入 | 源操作数，类型为MaskTensor。 |
| dstAddr | 输出 | 目的操作数在UB上的起始地址。 |
| offset | 输入 | 当offset为int32_t类型时：POST_MODE_NORMAL与POST_MODE_UPDATE含义不一致。- POST_MODE_NORMAL场景：实际搬运UB起始地址为dstAddr + offset。- POST_MODE_UPDATE场景：实际搬运UB起始地址为dstAddr，搬运后执行地址更新dstAddr +=  offset。 |

**表4 **MaskReg非对齐搬出参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 支持的数据类型为b16/b32。 |
| mask | 输入 | 源操作数，类型为MaskTensor。 |
| dstAddr | 输出 | 目的操作数在UB上的起始地址。 |
| ureg | 输出 | UnalignRegForStore，非对齐寄存器，用于保存非对齐数据，长度32B。调用完StoreUnAlign（MaskReg非对齐搬出接口）后，需要调用StoreUnAlignPost接口，传入该非对齐寄存器，将未写出的数据写出到目的地址中。 |

#### 约束说明

无

#### 调用示例

```
template <typename T>
__simd_vf__ inline void StoreAlignVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);        
        AscendC::Reg::AddrReg offset = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        AscendC::Reg::LoadAlign(mask, srcAddr, offset);
        AscendC::Reg::StoreAlign(dstAddr, mask, offset);
    }
}
```
