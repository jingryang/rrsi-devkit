# AbsSub

**页面ID:** atlasascendc_api_07_0376  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0376.html

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

srcReg0与srcReg1相减再求绝对值， 根据mask将计算结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0376_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void AbsSub(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 源操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half/float/int64_t |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dstReg中置零。- MERGING，当前不支持。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void AbsSubVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::AbsSub(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 AbsSub 实例

### 实例 1：data_compare::AscendC::LocalTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Adds, Cast, Compare, Duplicate, LoadAlign, LoadDist, MaskReg, Muls, RegTensor, Select, StoreAlign, UpdateMask
- **AbsSub 调用次数**: 2
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义（待补充）**: 在 data_compare 算子中计算两个输入张量的绝对差值 |x1-x2|，作为浮点近似相等判定的左操作数，与 |x2|*rtol+atol 容差阈值配合 Compare 判断元素是否在容差范围内。

（行 565-594）

```cpp
if constexpr (kIsB16) {
    AscendC::Reg::RegTensor<D_T> b16Reg1, b16Reg2;
    AscendC::Reg::LoadAlign<D_T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(b16Reg1, x1Ptr + off);
    AscendC::Reg::LoadAlign<D_T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(b16Reg2, x2Ptr + off);
    AscendC::Reg::Cast<float, D_T, kCastTraitB16ToF32>(x1Reg, b16Reg1, mask);
    AscendC::Reg::Cast<float, D_T, kCastTraitB16ToF32>(x2Reg, b16Reg2, mask);
} else if constexpr (kIsB8) {
    AscendC::Reg::RegTensor<D_T> b8Reg1, b8Reg2;
    AscendC::Reg::LoadAlign<D_T, AscendC::Reg::LoadDist::DIST_UNPACK4_B8>(b8Reg1, x1Ptr + off);
    AscendC::Reg::LoadAlign<D_T, AscendC::Reg::LoadDist::DIST_UNPACK4_B8>(b8Reg2, x2Ptr + off);
    AscendC::Reg::RegTensor<half> h16Reg1, h16Reg2;
    AscendC::Reg::Cast<half, D_T, kCastTraitB8ToB16>(h16Reg1, b8Reg1, mask);
    AscendC::Reg::Cast<half, D_T, kCastTraitB8ToB16>(h16Reg2, b8Reg2, mask);
    AscendC::Reg::Cast<float, half, kCastTraitB16ToF32Int>(x1Reg, h16Reg1, mask);
    AscendC::Reg::Cast<float, half, kCastTraitB16ToF32Int>(x2Reg, h16Reg2, mask);
} else if constexpr (kIsI32) {
    AscendC::Reg::RegTensor<int32_t> iReg1, iReg2;
    AscendC::Reg::LoadAlign(iReg1, x1Ptr + off);
    AscendC::Reg::LoadAlign(iReg2, x2Ptr + off);
    AscendC::Reg::Cast<float, int32_t, kCastTraitI32ToF32>(x1Reg, iReg1, mask);
    AscendC::Reg::Cast<float, int32_t, kCastTraitI32ToF32>(x2Reg, iReg2, mask);
} else {
    AscendC::Reg::LoadAlign(x1Reg, reinterpret_cast<__ubuf__ float*>(x1Ptr) + off);
    AscendC::Reg::LoadAlign(x2Reg, reinterpret_cast<__ubuf__ float*>(x2Ptr) + off);
}

AscendC::Reg::AbsSub(diffReg, x1Reg, x2Reg, mask);
AscendC::Reg::Abs(absX2Reg, x2Reg, mask);
AscendC::Reg::Muls(threshReg, absX2Reg, rtolVal, mask);
AscendC::Reg::Adds(threshReg, threshReg, atolVal, mask);
```

**要点**:
1. `AbsSub(dstReg, srcReg0, srcReg1, mask)` 计算 |srcReg0-srcReg1| 并按 mask 写入 dstReg，等价于先 Sub 再 Abs，但由单条指令完成，省一次寄存器往返。
2. 本实例按 dtype（B16/B8/I32/float）分支 LoadAlign + Cast 归一到 float，再统一调用 AbsSub，体现多精度输入统一到目标精度后求绝对差的典型用法。
3. 与 Abs + Muls + Adds 组合构造 torch.isclose 风格的容差阈值 |x2|*rtol+atol，再经 Compare/Select 输出逐元素比较结果，mask 贯穿全程保证尾元素正确性。

### AbsSub 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| data_compare | Abs, Adds, Cast, Compare | 多 dtype 归一 float 后求绝对差，配合 Abs/Muls/Adds 构造容差阈值做近似相等判定 | __VEC_SCOPE__ |

