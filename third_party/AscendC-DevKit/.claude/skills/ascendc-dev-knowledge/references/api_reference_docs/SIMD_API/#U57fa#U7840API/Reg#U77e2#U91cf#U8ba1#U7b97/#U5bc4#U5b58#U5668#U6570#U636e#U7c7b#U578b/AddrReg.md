# AddrReg

**页面ID:** atlasascendc_api_07_0317  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0317.html

---

#### 功能说明

AddrReg即为Address Register（地址寄存器），是用于存储地址偏移量的寄存器。AddrReg应该通过CreateAddrReg API初始化，然后在循环之中使用AddrReg存储地址偏移量。AddrReg在每层循环中根据所设置的stride进行自增。

#### 函数原型

```
// offset = index0 * stride0
template <typename T>
__simd_callee__ inline AddrReg CreateAddrReg(uint16_t index0, uint32_t stride0);

// offset = index0 * stride0 + index1 * stride1
template <typename T>
__simd_callee__ inline AddrReg CreateAddrReg(uint16_t index0, uint32_t stride0, uint16_t index1, uint32_t stride1);

// offset = index0 * stride0 + index1 * stride1 + index2 * stride2
template <typename T>
__simd_callee__ inline AddrReg CreateAddrReg(uint16_t index0, uint32_t stride0, uint16_t index1, uint32_t stride1, uint16_t index2, uint32_t stride2);

// offset = index0 * stride0 + index1 * stride1 + index2 * stride2 + index3 * stride3
template <typename T>
__simd_callee__ inline AddrReg CreateAddrReg(uint16_t index0, uint32_t stride0, uint16_t index1, uint32_t stride1, uint16_t index2, uint32_t stride2, uint16_t index3, uint32_t stride3);
```

#### 参数说明

| **参数** | **含义** |
| --- | --- |
| T | 模板参数，支持的数据类型为b8/b16/b32/b64。 |
| index0 | 计算偏移量时作为轴1（偏移量计算公式参考注释）。 |
| index1 | 计算偏移量时作为轴2（偏移量计算公式参考注释）。 |
| index2 | 计算偏移量时作为轴3（偏移量计算公式参考注释）。 |
| index3 | 计算偏移量时作为轴4（偏移量计算公式参考注释）。 |
| stride0 | 地址偏移量1 |
| stride1 | 地址偏移量2 |
| stride2 | 地址偏移量3 |
| stride3 | 地址偏移量4 |

#### 支持的型号

Atlas 350 加速卡

#### 约束说明

无

#### 调用示例

```
__simd_vf__ inline void CreateAddrRegVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::MaskReg mask = AscendC::Reg::CreateMask<T>();
    AscendC::Reg::AddrReg aReg;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        aReg = AscendC::Reg::CreateAddrReg<T>(i, oneRepeatSize);
        AscendC::Reg::LoadAlign(mask, srcAddr, aReg);
        AscendC::Reg::StoreAlign(dstAddr, mask, aReg);
    }
}
```
