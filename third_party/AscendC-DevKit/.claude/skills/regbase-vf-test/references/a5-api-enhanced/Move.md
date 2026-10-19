# Move

**页面ID:** atlasascendc_api_07_0334  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0334.html

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

将src中的元素复制到dst中的对应位置。如果有输入mask，则仅复制被mask选定的有效元素，无效元素填0。

#### 函数原型

- 有输入mask

```
__simd_callee__ inline void Move(MaskReg& dst, MaskReg& src, MaskReg& mask)
```

- 无输入mask

```
__simd_callee__ inline void Move(MaskReg& dst, MaskReg& src)
```

#### 参数说明

**表1 **参数说明

| 参数名 | 描述 |
| --- | --- |
| dst | 目的操作数。 |
| src | 源操作数。 |
| mask | 指示在复制过程中哪些bit有效。 |

#### 约束说明

无

#### 调用示例

```
template <typename T>
__simd_vf__ inline void MoveVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg src = AscendC::Reg::CreateMask<T, AscendC::Reg::MaskPattern::ALLF>();
    AscendC::Reg::MaskReg dst;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Move(dst, src, mask);
        AscendC::Reg::Adds(srcReg, srcReg, 0, dst);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Move 实例

### 实例 1：adaptive_pool3d_common::CalcRealIndex

- **来源类型**: `__aicore__`
- **共现 API**: Add, Adds, Cast, CreateMask, Duplicate, MaskPattern, MaskReg, Muls, RegTensor
- **Move 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 adaptive_pool3d 算子的 CalcRealIndex 中，Move 用于类型一致时按 mask 将源寄存器内容复制到目标寄存器，作为 Cast 类型转换的等价替代路径（无需转换时直接搬运）。

（行 148-189）

```cpp
if constexpr (IsSameType<UINDEX, int16_t>::value) {
    Reg::Cast<int32_t, int16_t, CASTB2TOB4>(regTmp, index, maskOne);
} else {
    Reg::Move(regTmp, index, maskOne);
}

// output index type use int64, need change to int64
if constexpr (IsSameType<TINDEX, int64_t>::value) {
    Reg::Cast<int64_t, int32_t, CASTB4TOB8>(resIndex, regTmp, maskOne);
} else {
    Reg::Move(resIndex, regTmp, maskOne);
}

if constexpr (SPLIT_MODE == SPLIT_W) {
    Reg::Adds(resIndex, resIndex, curOffset, maskOne);
} else if constexpr (SPLIT_MODE == SPLIT_H) {
    Reg::RegTensor<TINDEX> regOffset;
    Reg::RegTensor<TINDEX> regCurkW;
    Reg::RegTensor<TINDEX> regHOffset;
    Reg::Duplicate(regOffset, curOffset, maskOne);
    Reg::Duplicate(regCurkW, curkW, maskOne);
    CalcDivAndMod<TINDEX>(resIndex, regCurkW, regHOffset, resIndex);
    Reg::Muls(regHOffset, regHOffset, wInDim, maskOne);
    Reg::Add(resIndex, resIndex, regHOffset, maskOne);
    Reg::Add(resIndex, resIndex, regOffset, maskOne);
} else {
    Reg::RegTensor<TINDEX> regOffset;
    Reg::RegTensor<TINDEX> regCurkW;
    Reg::RegTensor<TINDEX> regCurkHW;
    Reg::RegTensor<TINDEX> regDOffset;
    Reg::RegTensor<TINDEX> regHOffset;
    Reg::Duplicate(regOffset, curOffset, maskOne);
    Reg::Duplicate(regCurkHW, curkHW, maskOne);
    Reg::Duplicate(regCurkW, curkW, maskOne);
    CalcDivAndMod<TINDEX>(resIndex, regCurkHW, regDOffset, resIndex);
    CalcDivAndMod<TINDEX>(resIndex, regCurkW, regHOffset, resIndex);
    Reg::Muls(regDOffset, regDOffset, inHW, maskOne);
    Reg::Muls(regHOffset, regHOffset, wInDim, maskOne);
    Reg::Add(resIndex, resIndex, regDOffset, maskOne);
    Reg::Add(resIndex, resIndex, regHOffset, maskOne);
    Reg::Add(resIndex, resIndex, regOffset, maskOne);
}
```

**要点**:
- 三参数形式 `Move(dst, src, mask)` 仅复制 mask 选定的有效元素，无效元素填 0。
- 与 `Cast` 配合：类型需转换时走 Cast，类型一致时走 Move，通过 `if constexpr` 按类型分派。
- 共现 Add/Adds/Muls/Duplicate 用于搬运后对索引做偏移与维度分解运算。

### Move 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| adaptive_pool3d_common | Add, Adds, Cast, CreateMask, Duplicate | `Move(dst, src, mask)` 按掩码搬运寄存器，配合 Cast 做类型分派、Add/Adds/Muls 做索引运算 | __aicore__ |

