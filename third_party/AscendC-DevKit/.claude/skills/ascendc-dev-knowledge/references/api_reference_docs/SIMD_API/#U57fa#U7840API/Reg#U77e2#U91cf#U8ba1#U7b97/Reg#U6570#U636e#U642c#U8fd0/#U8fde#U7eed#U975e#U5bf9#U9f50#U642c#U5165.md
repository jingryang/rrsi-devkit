# 连续非对齐搬入

**页面ID:** atlasascendc_api_07_0323  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0323.html

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

Reg矢量计算数据搬运接口，适用于从UB非32B对齐地址起始连续搬入RegTensor。

#### 函数原型

```
// LoadUnAlignPre接口用于在进行非对齐搬入前的初始化，适用于场景1和场景2
template <typename T>
__simd_callee__ inline void LoadUnAlignPre(UnalignRegForLoad& ureg, __ubuf__ T* srcAddr);

// LoadUnAlignPre接口用于在进行非对齐搬入前的初始化，适用于场景3
template <typename T>
__simd_callee__ inline void LoadUnAlignPre(UnalignRegForLoad& ureg, __ubuf__ T* srcAddr, AddrReg& areg);

// 场景1:使用uint32_t作为偏移量，使用post mode搬运 ，每调用一次接口更新源操作数在UB上的地址
template <typename T = DefaultType, PostLiteral postMode = PostLiteral::POST_MODE_UPDATE, typename U>
__simd_callee__ inline void LoadUnAlign(U& dstReg, UnalignRegForLoad& ureg, __ubuf__ T*& srcAddr, uint32_t postUpdateStride);

// 场景2:调用接口不改变源操作数在UB上的地址，每次Repeat需要手动更新源操作数在UB上的地址
template <typename T = DefaultType, typename U>
__simd_callee__ inline void LoadUnAlign(U& dstReg, UnalignRegForLoad& ureg, __ubuf__ T* srcAddr);

// 场景3:使用 AddrReg 存储偏移量进行数据搬运
template <typename T = DefaultType, typename U>
__simd_callee__ inline void LoadUnAlign(U& dstReg, UnalignRegForLoad& ureg, __ubuf__ T*& srcAddr, AddrReg& areg, uint32_t inc);
```

#### 参数说明

**表1 **连续非对齐搬入使用uint32_t存储偏移量场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| postMode | 输入 | 用于控制是否使能post update，PostLiteral类型。 |
| U | 输入 | 模板参数，支持的数据类型对应的RegTensor类型。 |
| ureg | 输出/输入 | UnalignRegForLoad，非对齐寄存器，用于保存非对齐数据，长度32B。LoadUnAlignPre函数中作为输出，LoadUnAlign函数中作为输入/输出。 |
| dstReg | 输出 | 目的操作数，类型为RegTensor。 |
| srcAddr | 输入/输出 | 源操作数在UB上的起始地址。 |
| postUpdateStride | 输入 | 仅支持POST_MODE_UPDATE场景：实际搬运UB起始地址为srcAddr，搬运后执行地址更新srcAddr +=  postUpdateStride。 |

**表2 **连续非对齐搬入使用AddrReg存储偏移量场景参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| ureg | 输出/输入 | UnalignRegForLoad，非对齐寄存器，用于保存非对齐数据，长度32B。LoadUnAlignPre函数中作为输出，LoadUnAlign函数中作为输入/输出。 |
| dstReg | 输出 | 目的操作数，类型为RegTensor。 |
| srcAddr | 输入/输出 | 源操作数在UB上的起始地址。 |
| areg | 输入 | AddrReg数据类型，存储地址偏移量offset。实际搬运UB起始地址为srcAddr + offset。 |
| inc | 输入 | 搬运完成后offset 在自增前被更新为offset + inc。 |

#### 约束说明

- 该接口中的srcAddr不需要32B对齐。
- LoadUnAlignPre与LoadUnAlign接口需要组合使用。

#### 调用示例

```
// 连续非对齐搬入使用 uint32_t 存储偏移量场景
template <typename T>
__simd_vf__ inline void LoadUnAlignVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t postUpdateStride, uint16_t repeatTimes)
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

// 连续非对齐搬入使用 AddrReg 存储偏移量场景
template <typename T>
__simd_vf__ inline void LoadUnAlignVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::UnalignRegForLoad ureg0;
    AscendC::Reg::UnalignRegForStore ureg1;
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        AscendC::Reg::LoadUnAlignPre(ureg0, srcAddr, aReg);
        AscendC::Reg::LoadUnAlign(srcReg, ureg0, srcAddr, aReg, 0);
        AscendC::Reg::StoreUnAlign(dstAddr, srcReg, ureg1, aReg);
    }
    AscendC::Reg::StoreUnAlignPost(dstAddr, ureg1, aReg);
}
```
