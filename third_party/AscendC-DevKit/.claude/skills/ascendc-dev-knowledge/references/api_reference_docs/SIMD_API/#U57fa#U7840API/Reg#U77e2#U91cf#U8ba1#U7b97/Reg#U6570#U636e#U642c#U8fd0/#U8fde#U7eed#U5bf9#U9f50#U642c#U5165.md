# 连续对齐搬入

**页面ID:** atlasascendc_api_07_0319  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0319.html

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

Reg矢量计算数据搬运接口，适用于从UB连续对齐搬入RegTensor。单搬入模式下，可以将数据从UB搬运到一个目的寄存器，双搬入模式下，可以将数据从UB搬运到两个目的寄存器。

#### 函数原型

```
// 单搬入模式 POST_MODE_NORMAL场景
template <typename T = DefaultType, LoadDist dist = LoadDist::DIST_NORM, typename U>
__simd_callee__ inline void LoadAlign(U& dstReg, __ubuf__ T* srcAddr);

// 单搬入模式 POST_MODE_UPDATE场景
template <typename T = DefaultType, PostLiteral postMode, LoadDist dist = LoadDist::DIST_NORM, typename U>
__simd_callee__ inline void LoadAlign(U& dstReg, __ubuf__ T*& srcAddr, int32_t postUpdateStride);

// 单搬入模式 使用AddrReg存储偏移量
template <typename T = DefaultType, LoadDist dist = LoadDist::DIST_NORM, typename U>
__simd_callee__ inline void LoadAlign(U& dstReg, __ubuf__ T* srcAddr, AddrReg offset);

// 双搬入模式 POST_MODE_NORMAL场景
template <typename T = DefaultType, LoadDist dist, typename U>
__simd_callee__ inline void LoadAlign(U& dstReg0, U& dstReg1, __ubuf__ T* srcAddr);

// 双搬入模式 POST_MODE_UPDATE场景
template <typename T = DefaultType, PostLiteral postMode, LoadDist dist, typename U>
__simd_callee__ inline void LoadAlign(U& dstReg0, U& dstReg1, __ubuf__ T*& srcAddr, int32_t postUpdateStride);

// 双搬入模式使用 AddrReg存储偏移量
template <typename T = DefaultType, LoadDist dist, typename U>
__simd_callee__ inline void LoadAlign(U& dstReg0, U& dstReg1, __ubuf__ T* srcAddr, AddrReg offset);
```

#### 参数说明

**表1 **LoadDist模板参数说明（单搬入模式）

| **LoadDist**取值 | **含义** | **搬运对齐约束（Byte）** |
| --- | --- | --- |
| DIST_NORM | 正常模式，搬运VL数据 | 32 |
| DIST_BRC_B8 | 搬运一个b8类型的数据，并Broadcast到所有元素位置 | 1 |
| DIST_BRC_B16 | 搬运一个b16类型的数据，并Broadcast到所有元素位置 | 2 |
| DIST_BRC_B32 | 搬运一个b32类型的数据，并Broadcast到所有元素位置 | 4 |
| DIST_US_B8 | 数据2倍上采样，加载VL/2个数据，每个输入元素重复两次，数据类型为b8 | min(32, VL/2) |
| DIST_US_B16 | 数据2倍上采样，加载VL/2个数据，每个输入元素重复两次，数据类型为b16 | min(32, VL/2) |
| DIST_DS_B8 | 数据2倍下采样，加载2倍VL的数据，数据每隔一个保留，数据类型为b8 | 32 |
| DIST_DS_B16 | 数据2倍下采样，加载2倍VL的数据，数据每隔一个保留，数据类型为b16 | 32 |
| DIST_UNPACK_B8 | 解压缩模式，按无符号整型u8加载VL/2长度数据，unpack到VL长度u16类型，中间位置补0 例，VL=256B： src: [0x00, 0x01, 0x02, 0x03, ..., 0xFF, ...] dst:[0x0000, 0x0001, ..., 0x0007F] | min(32, VL/2) |
| DIST_UNPACK_B16 | 解压缩模式，按无符号整型u16加载VL/2长度数据，unpack到VL长度u32类型，中间位置补0 例，VL=256B： src: [0x0000, 0x0001, 0x0002, 0x0003, ..., 0x007F, ...] dst:[0x00000000, 0x00000001, ..., 0x000003F] | min(32, VL/2) |
| DIST_BLK | 读取一个DataBlock（32B），并广播到VL | 32 |
| DIST_E2B_B16 | 加载(VL/DataBlock)B的数据，并将每个元素（16bit）广播到一个DataBlock（32B）中。 | VL/16 |
| DIST_E2B_B32 | 加载(VL/DataBlock)B的数据，并将每个元素（32bit）广播到一个DataBlock（32B）中。 | VL/8 |
| DIST_UNPACK_B32 | 解压缩模式，按无符号整型u32加载VL/2长度数据，unpack到VL长度u64类型，中间位置补0 例，VL=256B： src: [0x00000000, 0x00000001, 0x00000002, ..., 0x000003F, ...] dst:[0x0000000000000000, 0x0000000000000001, ..., 0x000000000000001F] | min(32, VL/2) |
| DIST_UNPACK4_B8 | 解压缩模式，按无符号整型u8加载VL/4长度数据，unpack到VL长度u32类型，中间位置补0 例，VL=256B： src: [0x00, 0x01, 0x02, 0x03, ..., 0xFF, ...] dst:[0x00000000, 0x00000001, ..., 0x000003F] | min(32, VL/4) |

**表2 **LoadDist模板参数说明（双搬入模式）

| **LoadDist**取值 | **含义** | **搬运对齐约束（Byte）** |
| --- | --- | --- |
| DIST_DINTLV_B8 | 双搬入模式，基于元素的交错搬运，从src中读取2*VL长度数据，将偶数索引的元素存入dst0，将奇数索引的元素存入dst1，数据类型为b8 | 32 |
| DIST_DINTLV_B16 | 双搬入模式，基于元素的交错搬运，从src中读取2*VL长度数据，将偶数索引的元素存入dst0，将奇数索引的元素存入dst1，数据类型为b16 | 32 |
| DIST_DINTLV_B32 | 双搬入模式，基于元素的交错搬运，从src中读取2*VL长度数据，将偶数索引的元素存入dst0，将奇数索引的元素存入dst1，数据类型为b32 | 32 |

**表3 **单搬入模式POST_MODE_NORMAL场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 操作数数据类型，支持的数据类型为b8/b16/b32/b64。 |
| dist | 输入 | 搬运模式，LoadDist类型，具体的取值请参考表1。 |
| U | 输入 | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstReg | 输出 | 目的操作数，类型为RegTensor。 |
| srcAddr | 输入 | 源操作数在UB上的起始地址。 |

**表4 **单搬入模式POST_MODE_UPDATE场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| postMode | 输入 | 用于控制是否使能post update，PostLiteral类型。 |
| dist | 输入 | 搬运模式，LoadDist类型，具体的取值请参考表1。 |
| U | 输入 | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstReg | 输出 | 目的操作数，类型为RegTensor。 |
| srcAddr | 输入/输出 | 源操作数在UB上的起始地址。 |
| postUpdateStride | 输入 | 实际搬运UB起始地址为srcAddr，搬运后执行地址更新：srcAddr +=  postUpdateStride。 |

**表5 **单搬入模式使用AddrReg存储偏移量场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| dist | 输入 | 搬运模式，LoadDist类型，具体的取值请参考表1。 |
| U | 输入 | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstReg | 输出 | 目的操作数，类型为RegTensor。 |
| offset | 输入 | 实际搬运地址UB为srcAddr + offset。 |
| srcAddr | 输入/输出 | 源操作数在UB上的起始地址。 |

**表6 **双搬入模式POST_MODE_NORMAL场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32。 |
| dist | 输入 | 搬运模式，LoadDist类型，具体的取值请参考表2。 |
| U | 输入 | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstReg0 | 输出 | 第一个目的操作数，类型为RegTensor。 |
| dstReg1 | 输出 | 第二个目的操作数，类型为RegTensor。 |
| srcAddr | 输入/输出 | 源操作数在UB上的起始地址。 |

**表7 **双搬入模式POST_MODE_UPDATE场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| postMode | 输入 | 用于控制是否使能post update，PostLiteral类型。 |
| dist | 输入 | 搬运模式，LoadDist类型，具体的取值请参考表2。 |
| U | 输入 | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstReg0 | 输出 | 第一个目的操作数，类型为RegTensor。 |
| dstReg1 | 输出 | 第二个目的操作数，类型为RegTensor。 |
| srcAddr | 输入/输出 | 源操作数在UB上的起始地址。 |
| postUpdateStride | 输入 | 实际搬运UB起始地址为srcAddr，搬运后执行地址更新：srcAddr +=  postUpdateStride。 |

**表8 **双搬入模式使用AddrReg存储偏移量场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32。 |
| dist | 输入 | 搬运模式，LoadDist类型，具体的取值请参考表2。 |
| U | 输入 | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| dstReg0 | 输出 | 第一个目的操作数，类型为RegTensor。 |
| dstReg1 | 输出 | 第二个目的操作数，类型为RegTensor。 |
| offset | 输入 | 实际搬运地址UB为srcAddr + offset。 |
| srcAddr | 输入/输出 | 源操作数在UB上的起始地址。 |

#### 约束说明

b64数据类型只支持LoadDist中的DIST_NORM模式。

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
        AscendC::Reg::LoadAlign<T, AscendC::Reg::LoadDist::DIST_DINTLV_B8>(srcReg0, srcReg1, srcAddr + i * oneRepeatSize);
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
