# 连续非对齐搬出

**页面ID:** atlasascendc_api_07_0324  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0324.html

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

Reg矢量计算数据搬运接口，适用于从RegTensor连续非对齐搬出到UB。

#### 函数原型

```
// 场景1:使用uint32_t作为存储偏移量，使用post mode进行搬运，每调用一次接口更新目的操作数在UB上的地址
template <typename T = DefaultType, PostLiteral postMode = PostLiteral::POST_MODE_UPDATE, typename U>
__simd_callee__ inline void StoreUnAlign(__ubuf__ T*& dstAddr, U& srcReg, UnalignRegForStore& ureg, uint32_t postUpdateStride); 

// 处理非对齐搬运的尾块，适用于场景1
template <typename T, PostLiteral postMode = PostLiteral::POST_MODE_UPDATE>
__simd_callee__ inline void StoreUnAlignPost(__ubuf__ T*& dstAddr, UnalignRegForStore& ureg, int32_t postUpdateStride);

// 场景2：使用 AddrReg 存储偏移量进行搬运，使用post mode进行搬运，每调用一次接口更新目的操作数在UB上的地址
template <typename T = DefaultType, PostLiteral postMode = PostLiteral::POST_MODE_UPDATE, typename U>
__simd_callee__ inline void StoreUnAlign(__ubuf__ T*& dstAddr, U& srcReg, UnalignRegForStore& ureg, AddrReg& areg);
// 处理非对齐搬运的尾块，适用于场景2
template <typename T>
__simd_callee__ inline void StoreUnAlignPost(__ubuf__ T*& dstAddr, UnalignRegForStore& ureg, AddrReg& areg);

// 场景3：配合Squeeze使用，连续非对齐搬出，SqueezeReg矢量计算API会存储有效元素的总字节数到AR特殊寄存器，使用此接口会将AR寄存器中效元素个数作为存储偏移量
template <typename T = DefaultType, PostLiteral postMode = PostLiteral::POST_MODE_UPDATE, typename U>
__simd_callee__ inline void StoreUnAlign(__ubuf__ T* dstAddr, U& srcReg, UnalignRegForStore& ureg);

// 处理非对齐搬运的尾块，适用于场景3
template <typename T>
__simd_callee__ inline void StoreUnAlignPost(__ubuf__ T* dstAddr, UnalignRegForStore& ureg);
```

#### 参数说明

**表1 **连续非对齐搬出使用int32_t存储偏移量场景

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| postMode | 输入 | 用于控制是否使能post update，PostLiteral类型。 |
| U | 输入 | 模板参数，模板参数T支持的数据类型对应的RegTensor类型。 |
| ureg | 输出/输入 | UnalignRegForStore，非对齐寄存器，用于保存非对齐数据，长度32B。StoreUnAlign函数中作为输入/输出，StoreUnAlignPost函数中作为输入。 |
| srcReg | 输入 | 源操作数，类型为RegTensor。 |
| dstAddr | 输入/输出 | 目的操作数在UB上的起始地址。 |
| postUpdateStride | 输入 | POST_MODE_NORMAL与POST_MODE_UPDATE场景下postUpdateStride含义不一致。 - POST_MODE_NORMAL场景：实际搬运UB起始地址为dstAddr，搬运数量为postUpdateStride。- POST_MODE_UPDATE场景：实际搬运UB起始地址为dstAddr，搬运数量为postUpdateStride，搬运后执行地址更新dstAddr +=  postUpdateStride。 |

**表2 **连续非对齐搬出使用AddrReg存储偏移量场景

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| ureg | 输出/输入 | UnalignRegForStore，非对齐寄存器，用于保存非对齐数据，长度32B。StoreUnAlign函数中作为输入/输出，StoreUnAlignPost函数中作为输入。 |
| srcReg | 输入 | 源操作数，类型为RegTensor。 |
| dstAddr | 输入/输出 | 目的操作数在UB上的起始地址。 |
| areg | 输入 | 实际搬运UB起始地址为 AddrReg数据类型，存储地址偏移量offset。实际搬运UB起始地址为srcAddr + offset。 |

**表3 **配合Squeeze使用，连续非对齐搬出，使用AR寄存器中有效元素个数作为存储偏移量

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstAddr | 输入/输出 | 目的操作数在UB上的起始地址。 |
| ureg | 输出/输入 | UnalignRegForStore，非对齐寄存器，用于保存非对齐数据，长度32B。StoreUnAlign函数中作为输入/输出，StoreUnAlignPost函数中作为输入。 |
| srcReg | 输入 | 源操作数，类型为RegTensor。 |

#### 约束说明

- 该接口中的dstAddr不需要32B对齐。
- StoreUnAlign与StoreUnAlignPost接口组合使用。

#### 调用示例

```
// 连续非对齐搬出使用 uint32_t 存储偏移量场景
template <typename T>
__simd_vf__ inline void StoreUnAlignVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t postUpdateStride, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::UnalignRegForLoad ureg0;
    AscendC::Reg::UnalignRegForStore ureg1;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        AscendC::Reg::LoadUnAlignPre(ureg0, srcAddr + i * postUpdateStride);
        AscendC::Reg::LoadUnAlign(srcReg, ureg0, srcAddr + i * postUpdateStride);
        AscendC::Reg::StoreUnAlign(dstAddr, srcReg, ureg1, postUpdateStride);
    }
    AscendC::Reg::StoreUnAlignPost(dstAddr, ureg1, 0);
}

// 连续非对齐搬出使用 AddrReg 存储偏移量场景
template <typename T>
__simd_vf__ inline void StoreUnAlignVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;    
    AscendC::Reg::UnalignRegForLoad ureg0;
    AscendC::Reg::UnalignRegForStore ureg1;
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < (uint16_t)repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        AscendC::Reg::LoadUnAlignPre(ureg0, srcAddr, aReg);
        AscendC::Reg::LoadUnAlign(srcReg, ureg0, srcAddr, aReg, 0);
        AscendC::Reg::StoreUnAlign(dstAddr, srcReg, ureg1, aReg);
    }
    AscendC::Reg::StoreUnAlignPost(dstAddr, ureg1, aReg);
}

// 配合Squeeze使用，连续非对齐搬出，SqueezeReg矢量计算API会存储有效元素的总字节数到AR寄存器，使用AR寄存器中效元素个数作为存储偏移量
template <typename T>
__aicore__ inline void SqueezeVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::UnalignRegForStore ureg;
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::H>();
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        AscendC::Reg::LoadAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(srcReg0, srcAddr, oneRepeatSize);
        AscendC::Reg::Squeeze<T, AscendC::Reg::GatherMaskMode::STORE_REG>(srcReg1, srcReg0, mask);
        AscendC::Reg::StoreUnAlign<T, AscendC::Reg::PostLiteral::POST_MODE_UPDATE>(dstAddr, srcReg1, ureg);
     }
     AscendC::Reg::StoreUnAlignPost(dstAddr, ureg);
}
```
