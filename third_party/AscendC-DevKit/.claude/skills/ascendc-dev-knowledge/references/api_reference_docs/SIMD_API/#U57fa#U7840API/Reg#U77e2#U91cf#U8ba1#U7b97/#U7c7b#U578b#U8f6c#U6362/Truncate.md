# Truncate

**页面ID:** atlasascendc_api_07_0399  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0399.html

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

将源操作数的浮点数元素截断到整数位，同时源操作数的数据类型保持不变。

#### 函数原型

```
template <typename T = DefaultType, RoundMode roundMode = RoundMode::CAST_NONE, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void Truncate(S& dstReg, S& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，dstReg/srcReg支持的数据类型为：half、float、bfloat16_t。 |
| roundMode | 舍入模式，取值如下： - RoundMode::CAST_NONE：默认值，在转换会导致精度丢失的场景下相当于CAST_RINT，其他场景下无效果；- RoundMode::CAST_RINT：返回最接近参数的整数，如果有2个整数同样接近，则会返回偶数的那个；- RoundMode::CAST_ROUND：round模式， 四舍五入求整；- RoundMode::CAST_FLOOR：floor模式，向下取整；- RoundMode::CAST_CEIL：ceil模式， 向上取整；- RoundMode::CAST_TRUNC：truncation模式， 向0取整，舍弃小数位。 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零- MERGING，当前不支持。 |
| S | srcReg/dstReg 类型，例如RegTensor<float>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 返回值

无

#### 约束说明

- 非饱和模式下，输入nan，输出nan; 输入值超出输入类型的最值范围，则输出+/-inf。
- 饱和模式下，输入nan, 输出为0，输入值超出输入类型的最值范围，则饱和为最值。
- float类型只支持不饱和模式。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void TruncVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::Truncate<T, AscendC::RoundMode::CAST_FLOOR, AscendC::Reg::MaskMergeMode::ZEROING>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```
