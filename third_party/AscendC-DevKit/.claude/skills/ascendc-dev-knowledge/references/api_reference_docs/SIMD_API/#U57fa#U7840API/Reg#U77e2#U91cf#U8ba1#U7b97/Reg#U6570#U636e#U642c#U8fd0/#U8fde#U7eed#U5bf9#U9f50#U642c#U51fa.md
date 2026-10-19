# 连续对齐搬出

**页面ID:** atlasascendc_api_07_0320  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0320.html

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

Reg矢量计算数据搬运接口，适用于从RegTensor连续对齐搬出到UB。

#### 函数原型

```
// 单搬出模式 POST_MODE_NORMAL场景
template <typename T = DefaultType, StoreDist dist = StoreDist::DIST_NORM, typename U>
__simd_callee__ inline void StoreAlign(__ubuf__ T* dstAddr, U& srcReg, MaskReg& mask);

// 单搬出模式 POST_MODE_UPDATE场景
template <typename T = DefaultType, PostLiteral postMode, StoreDist dist = StoreDist::DIST_NORM, typename U>
__simd_callee__ inline void StoreAlign(__ubuf__ T*& dstAddr, U& srcReg, int32_t postUpdateStride, MaskReg& mask);

// 单搬出模式 使用AddrReg存储偏移量
template <typename T = DefaultType, StoreDist dist = StoreDist::DIST_NORM, typename U>
__simd_callee__ inline void StoreAlign(__ubuf__ T* dstAddr, U& srcReg, AddrReg offset, MaskReg& mask);

// 双搬出模式 POST_MODE_NORMAL场景
template <typename T = DefaultType, StoreDist dist, typename U>
__simd_callee__ inline void StoreAlign(__ubuf__ T* dstAddr, U& srcReg0, U& srcReg1, MaskReg& mask);

// 双搬出模式 使用AddrReg 存储偏移量
template <typename T = DefaultType, StoreDist dist, typename U>
__simd_callee__ inline void StoreAlign(__ubuf__ T* dstAddr, U& srcReg0, U& srcReg1, AddrReg offset, MaskReg& mask);
```

#### 参数说明

**表1 **StoreDist模板参数说明（单搬出模式）

| **StoreDist** | **含义** | **对齐约束（****Byte****）** |
| --- | --- | --- |
| DIST_NORM_B8 | 正常模式，搬运VL数据，数据类型为b8。 | 32 |
| DIST_NORM_B16 | 正常模式，搬运VL数据，数据类型为b16。 | 32 |
| DIST_NORM_B32 | 正常模式，搬运VL数据，数据类型为b32。 | 32 |
| DIST_FIRST_ELEMENT_B8 | 忽略mask，向dst中搬运src第一个元素，数据类型为b8。 | 1 |
| DIST_FIRST_ELEMENT_B16 | 忽略mask，向dst中搬运src第一个元素，数据类型为b16。 | 2 |
| DIST_FIRST_ELEMENT_B32 | 忽略mask，向dst中搬运src第一个元素，数据类型为b32。 | 4 |
| DIST_PACK_B16 | 压缩模式，数据类型为b16，根据mask，将src中有效元素的低半部分bit数据连续存储于dst中 例：数据类型为uint16_t，mask配置为所有元素有效，dst长度需要为VL/2，执行结果如下： src: [0x3210, 0x7654, 0xBA98, 0xFEDC, ..., 0xFEDC, 0xBA98, 0x7654, 0x3210] dst: [0x5410, 0xDC98, ... 0x98DC, 0x1054] | min(32, VL/2) |
| DIST_PACK_B32 | 压缩模式，数据类型为b32，根据mask，将src中有效元素的低半部分bit数据连续存储于dst中。 | min(32, VL/2) |
| DIST_PACK_B64 | 压缩模式，数据类型为b64，根据mask，将src中有效元素的低半部分bit数据连续存储于dst中。 | min(32, VL/2) |
| DIST_PACK4_B32 | 压缩模式，数据类型为b32，根据mask，将src中有效元素的低8bit（四分之一）数据连续存储于dst中。 | min(32, VL/4) |
| DIST_NORM | 正常模式，搬运VL数据，支持数据类型b8/b16/b32，根据模板T确定。 | 32 |

**表2 **StoreDist模板参数说明（双搬出模式）

| **StoreDist** | **含义** | **对齐约束(Byte)** |
| --- | --- | --- |
| DIST_INTLV_B8 | 双搬出模式，数据类型为b8，忽略mask，将src0，src1中的元素交错存储于dst中，dst长度需要为VL*2。 例：数据类型为uint8_t： src0: [0, 2, 4, 6, ... 254, 0, 2, 4, ... 252, 254] src1: [1, 3, 5, 7, ... 255, 1, 3, 5, ... 253, 255] dst: [0, 1, 2, 3, ..., 254, 255, 0, 1, 2, 3, ... 253, 254, 255] | 32 |
| DIST_INTLV_B16 | 双搬出模式，数据类型为b16，忽略mask，将src0，src1中的元素交错存储于dst中，dst长度需要为VL*2。 | 32 |
| DIST_INTLV_B32 | 双搬出模式，数据类型为b32，忽略mask，将src0，src1中的元素交错存储于dst中，dst长度需要为VL*2。 | 32 |

**表3 **单搬出模式POST_MODE_NORMAL场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| dist | 输入 | StoreDist模板参数，enum class类型，具体的取值请参考表1。 |
| U | 输入 | RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstAddr | 输出 | 目的操作数在UB上的起始地址。 |
| srcReg | 输入 | 源操作数，类型为RegTensor。 |
| mask | 输入 | MaskReg类型，指示在搬运过程中哪些元素有效。 |

**表4 **单搬出模POST_MODE_UPDATE场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| postMode | 输入 | 用于控制是否使能post update，PostLiteral类型。 |
| dist | 输入 | StoreDist模板参数，enum class类型，具体的取值请参考表1。 |
| U | 输入 | RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstAddr | 输入/输出 | 目的操作数在UB上的起始地址。 |
| srcReg | 输入 | 源操作数，类型为RegTensor。 |
| postUpdateStride | 输入 | 实际搬运UB起始地址为dstAddr，搬运后自动执行地址更新：dstAddr +=  postUpdateStride。 |
| mask | 输入 | MaskReg类型，指示在搬运过程中哪些元素有效。 |

**表5 **单搬出模式使用AddrReg存储偏移量场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| dist | 输入 | StoreDist模板参数，enum class类型，具体的取值请参考表1。 |
| U | 输入 | RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstAddr | 输入/输出 | 目的操作数。 |
| srcReg | 输入 | 源操作数，类型为RegTensor。 |
| offset | 输入 | 实际搬运地址UB为dstAddr + offset。 |
| mask | 输入 | MaskReg类型，指示在搬运过程中哪些元素有效。 |

**表6 **双搬出模式POST_MODE_NORMAL场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| dist | 输入 | StoreDist模板参数，enum class类型，具体的取值请参考表2。 |
| U | 输入 | RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstAddr | 输出 | 目的操作数在UB上的起始地址。 |
| srcReg0 | 输入 | 第一个源操作数，类型为RegTensor。 |
| srcReg1 | 输入 | 第二个源操作数，类型为RegTensor。 |
| mask | 输入 | MaskReg类型，指示在搬运过程中哪些元素有效。 |

**表7 **双搬出模式使用AddrReg存储偏移量场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32。 |
| dist | 输入 | StoreDist模板参数，enum class类型，具体的取值请参考表2。 |
| U | 输入 | RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstAddr | 输出 | 目的操作数在UB上的起始地址。 |
| srcReg0 | 输入 | 第一个源操作数，类型为RegTensor。 |
| srcReg1 | 输入 | 第二个源操作数，类型为RegTensor。 |
| offset | 输入 | 实际搬运地址UB为dstAddr + offset。 |
| mask | 输入 | MaskReg类型，指示在搬运过程中哪些元素有效。 |

#### 约束说明

b64数据类型只支持StoreDist中的DIST_NORM模式。

#### 调用示例

```
// 单搬入/单搬出 POST_MODE_NORMAL 场景
__simd_vf__ inline void ComputeMode01(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t dstSize,
    uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(dstSize);
        AscendC::Reg::LoadAlign(dstReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}

// 单搬入/单搬出 POST_MODE_UPDATE 场景
__simd_vf__ inline void ComputeMode02(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t dstSize,
    uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(dstSize);
        AscendC::Reg::LoadAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(dstReg, srcAddr, oneRepeatSize);
        AscendC::Reg::StoreAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(dstAddr, dstReg, oneRepeatSize, mask);
    }
}

// 单搬入/单搬出使用 AddrReg 存储偏移量场景
__simd_vf__ inline void ComputeMode03(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<T>();
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        AscendC::Reg::LoadAlign(dstReg, srcAddr, aReg);
        AscendC::Reg::StoreAlign(dstAddr, dstReg, aReg, mask);
    }
}

// 双搬入/双搬出 POST_MODE_NORMAL 场景
__simd_vf__ inline void ComputeMode04(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize,
    uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<uint8_t, AscendC::Reg::MaskPattern::ALL>();
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        AscendC::Reg::LoadAlign<T, AscendC::Reg::LoadDist::DIST_DINTLV_B8>(srcReg0, srcReg0, srcAddr + i * oneRepeatSize);
        AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_INTLV_B8>(dstAddr + i * oneRepeatSize, srcReg0, srcReg1, mask);
    }
}

// 双搬入/双搬出使用 AddrReg 存储偏移量场景
__simd_vf__ inline void ComputeMode05(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<T>();
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        AscendC::Reg::LoadAlign<T, AscendC::Reg::LoadDist::DIST_DINTLV_B8>(srcReg0, srcReg1, srcAddr, aReg);
        AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_INTLV_B8>(dstAddr, srcReg0, srcReg1, aReg, mask);
    }
}
```
