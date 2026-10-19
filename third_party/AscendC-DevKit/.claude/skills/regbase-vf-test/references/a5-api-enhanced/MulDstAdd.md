# MulDstAdd

**页面ID:** atlasascendc_api_07_00007  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00007.html

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

dstReg与srcReg0相乘后与srcReg1相加， 根据mask将计算结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_00007_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, MaskMergeMode mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void MulDstAdd(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half/bfloat16_t/float |
| mode | 选择MERGING模式或ZEROING模式。当前只支持ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。 |
| U | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MulDstAddVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, __ubuf__ T* src2Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(dstReg, src2Addr + i * oneRepeatSize);
        AscendC::Reg::MulDstAdd(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 MulDstAdd 实例

### 实例 1：fake_quant_affine_cachemask::AscendC::LocalTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Adds, Cast, DataCopy, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskReg, Maxs, Mins, Mul, Muls, RegTensor, StoreDist, Sub, UpdateMask
- **MulDstAdd 调用次数**: 1
- **参数模式**: `T1_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: 仿射量化反量化阶段，当存在零点（HAS_ZP==1）时用 MulDstAdd 一步完成 `vregTmp = vregTmp * vregInvSc + vregZp`（乘反尺度再加零点），替代分开的 Mul+Add，无零点时回退到单独 Mul。

（行 380-384）

```cpp
if constexpr (HAS_ZP == 1) {
    Reg::MulDstAdd<float>(vregTmp, vregInvSc, vregZp, mask);
} else {
    Reg::Mul<float>(vregTmp, vregTmp, vregInvSc, mask);
}
```

**要点**: ①dstReg 同时为输入与输出，语义为 dst = dst*src0 + src1，故 dstReg 须先持有有效值；②显式模板实参 `<float>` 指定类型，mask 控制逐元素生效；③与 Mul 分支按 HAS_ZP 编译期分流，零点路径走融合乘加、无零点路径仅 Mul。

### 实例 2：fake_quant_affine_cachemask::AscendC::LocalTensor

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Add, Cast, DataCopy, Div, DivSpecificMode, Duplicate, LoadDist, MaskMergeMode, MaskReg, Mul, RegTensor, UpdateMask
- **MulDstAdd 调用次数**: 1
- **参数模式**: `T1_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: 同算子的另一 kernel 文件，先 DataCopy 载入零点 vregZp，再用 MulDstAdd 融合“乘反尺度 + 加零点”；上方注释保留了等价的 Mul+Add 两步写法以对比融合收益。

（行 279-286）

```cpp
if constexpr (HAS_ZP == 1) {
    Reg::DataCopy<float, Reg::LoadDist::DIST_NORM>(vregZp, zPtr + i * VL_FP32);
    // Reg::Mul<float>(vregTmp, vregTmp, vregInvSc, mask);
    // Reg::Add<float>(vregTmp, vregTmp, vregZp, mask);
    Reg::MulDstAdd<float>(vregTmp, vregInvSc, vregZp, mask);
} else {
    Reg::Mul<float>(vregTmp, vregTmp, vregInvSc, mask);
}
```

**要点**: ①注释展示 MulDstAdd 等价于 `Mul(vregTmp,vregTmp,vregInvSc)+Add(vregTmp,vregTmp,vregZp)`，融合省一条指令；②dstReg(vregTmp) 与 srcReg0(vregInvSc) 不同源，避免读后写相关；③srcReg1 为刚 DataCopy 载入的 vregZp，零点须先就绪。

### 实例 3：atan2::TaylorSeriesExpansion

- **来源类型**: `__aicore__`
- **共现 API**: Axpy, Duplicate, Mul, RegTensor
- **MulDstAdd 调用次数**: 10
- **参数模式**: `T0_A4_M1_TYPEnone_MASKmask`（实参 4 个，含 mask/mode: mask）
- **语义**: atan2 用 Horner 法展开泰勒级数，连续 5 次 MulDstAdd 实现 `y = y * x² + aₙ` 的链式嵌套累加，最后乘以 x 得到近似值，dstReg(yReg) 作为滚动累加器反复读写。

（行 261-276）

```cpp
{
    // x - 1/3*x^3 + 1/5*x^5 - 1/7*x^7 + 1/9*x^9 - 1/11*x^11 + 1/13*x^13
    // x(1 - x^2(1/3 - x^2(1/5 - x^2(1/7 - x^2(1/9 - x^2(1/11 - x^2/13))))))
    Reg::RegTensor<float> xSquarReg;
    Reg::Mul(xSquarReg, xReg, xReg, mask);

    Reg::Duplicate(yReg, -1.0f / 11.0f, mask);
    Reg::Axpy(yReg, xSquarReg, 1.0f / 13.0f, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg9, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg7, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg5, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg3, mask);
    Reg::MulDstAdd(yReg, xSquarReg, addReg1, mask);
    Reg::Mul(yReg, yReg, xReg, mask);
}
```

**要点**: ①dstReg(yReg) 作跨步累加器，体现 Horner 嵌套求值，复用同一寄存器；②srcReg0 固定为 xSquarReg(x²)，srcReg1 为各级系数寄存器 addRegN；③10 次调用本片段展示 5 次，与 Axpy/Duplicate 配合构成多项式核。

### 实例 4：group_norm_grad::StoreDist::DIST_NORM

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: MaskMergeMode, MulAddDst
- **MulDstAdd 调用次数**: 1
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: group_norm_grad 余块处理，`MulDstAdd(vregXR, vregDyR, vregXQ)` 在尾块把主块部分积 vregXQ 累加进余块 dgamma 候选 vregXR，随后用 MERGING Copy 合并主/余块结果完成二路归约。

（行 1522-1540）

```cpp
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDgamma + i, vregDgamma, pregMerge);
    ReduceSum(vregDbeta, vregDyQ, pregLoop);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDbeta + i, vregDbeta, pregMerge);
}
{
    MaskReg pregLoop = UpdateMask<float>(sreg0);
    DataCopyUnAlignPre(uSrcX, curUbX);
    DataCopyUnAlignPre(uSrcXR, curUbXR);
    DataCopyUnAlignPre(uSrcDy, curUbDy);
    DataCopyUnAlignPre(uSrcDyR, curUbDyR);
    LoadUnAlignOneTensor<T>(curUbX, vregXQ, uSrcX, pregMain, sregvl);
    LoadUnAlignOneTensor<T>(curUbXR, vregXR, uSrcXR, pregLoop, sregvl);
    LoadUnAlignOneTensor<T>(curUbDy, vregDyQ, uSrcDy, pregMain, sregvl);
    LoadUnAlignOneTensor<T>(curUbDyR, vregDyR, uSrcDyR, pregLoop, sregvl);
    Mul(vregXQ, vregXQ, vregDyQ, pregMain);
    MulDstAdd(vregXR, vregDyR, vregXQ, pregLoop);
    Add(tempDy, vregDyQ, vregDyR, pregLoop);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregXQ, vregXR, pregLoop);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDyQ, tempDy, pregLoop);
```

**要点**: ①pregLoop 为尾块掩码，仅处理剩余元素；②dstReg(vregXR) 与累加源 vregXQ 来自不同 Load，体现“主+余”二路归约；③紧接 `Copy<...,MERGING>` 合并，是 group_norm 尾块标准套件。

### 实例 5：group_norm_grad::VecScope_L714

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: MaskMergeMode, MulAddDst
- **MulDstAdd 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: group_norm_grad 尾块 step2 将最后 ≤64 块归约成 1，对 dbeta/dgamma 分别用 MulDstAdd 把主块部分积（Q 寄存器）累加到余块寄存器（R）上，再 MERGING Copy 合并后 ReduceSum。

（行 750-771）

```cpp
// step2: the tail (last 64 or less than 64) blocks reduce to 1.
{
    MaskReg pregLoop = UpdateMask<float>(sreg0);
    LoadTwoTensorForDtypeT<float>(ubDbeta, ubDbeta, vregDbetaQ, vregDbetaR, pregMain, pregLoop,
                                  remainderGeneral * sregvl, remainderGeneral * sregvl + binaryQuotientOffset);
    LoadTwoTensorForDtypeT<float>(ubDgamma, ubDgamma, vregDgammaQ, vregDgammaR, pregMain, pregLoop,
                                  remainderGeneral * sregvl, remainderGeneral * sregvl + binaryQuotientOffset);
    LoadTwoTensorForDtypeT<float>(ubGamma, ubGamma, vregGammaQ, vregGammaR, pregMain, pregLoop,
                                  remainderGeneral * sregvl, remainderGeneral * sregvl + binaryQuotientOffset);
    Mul(vregDbetaQ, vregGammaQ, vregDbetaQ, pregMain);
    Mul(vregDgammaQ, vregGammaQ, vregDgammaQ, pregMain);
    MulDstAdd(vregDbetaR, vregGammaR, vregDbetaQ, pregLoop);
    MulDstAdd(vregDgammaR, vregGammaR, vregDgammaQ, pregLoop);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDbetaQ, vregDbetaR, pregLoop);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDgammaQ, vregDgammaR, pregLoop);
    ReduceSum(vregSumDgamma, vregDgammaQ, pregMain);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDgamma + remainderGeneral, vregSumDgamma,
                                                       pregMerge);
    ReduceSum(vregSumDbeta, vregDbetaQ, pregMain);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDbeta + remainderGeneral, vregSumDbeta,
                                                       pregMerge);
}
```

**要点**: ①连续两条 MulDstAdd 对称处理 dbetaR 与 dgammaR；②srcReg1 为对应主块寄存器 vregDbetaQ/vregDgammaQ；③配合 LoadTwoTensorForDtypeT 双路加载与 ReduceSum 完成尾块规约。

### 实例 6：group_norm_grad::VecScope_L191

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: MaskMergeMode
- **MulDstAdd 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: group_norm_grad 重计算路径用两段循环处理 overlap 与 remainder：片段 1 在 overlap 段把 fold 部分积 vregXF 累加进 main 的 vregXM；片段 2 在 remainder 段反向把 main 部分积累加进 fold 的 vregXF，两段均用 MulDstAdd 完成乘加融合。

**片段 1** (行 205-216):

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(overLapLoopTimes); i++) {
    MaskReg pregLoop = UpdateMask<float>(sreg0);
    LoadTwoTensorForDtypeT<T>(ubXMain, ubXFold, vregXM, vregXF, pregMain, pregLoop, i * sregvl, i * sregvl);
    LoadTwoTensorForDtypeT<T>(ubDyMain, ubDyFold, vregDyM, vregDyF, pregMain, pregLoop, i * sregvl, i * sregvl);
    Mul(vregXF, vregXF, vregDyF, pregLoop);
    MulDstAdd(vregXM, vregDyM, vregXF, pregMain);
    Add(vregDyM, vregDyM, vregDyF, pregMain);
    ReduceSum(vregDgamma, vregXM, pregLoop);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDgamma + i, vregDgamma, pregMerge);
    ReduceSum(vregDbeta, vregDyM, pregLoop);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDbeta + i, vregDbeta, pregMerge);
}
```

**片段 2** (行 218-234):

```cpp
for (uint16_t i = 0; i < static_cast<uint16_t>(remainerLoopTimes); i++) {
    MaskReg pregLoop = UpdateMask<float>(sreg0);
    LoadTwoTensorForDtypeT<T>(ubXMain, ubXFold, vregXM, vregXF, pregMain, pregLoop, overLapLoopTimes * sregvl,
                              overLapLoopTimes * sregvl);
    LoadTwoTensorForDtypeT<T>(ubDyMain, ubDyFold, vregDyM, vregDyF, pregMain, pregLoop,
                              overLapLoopTimes * sregvl, overLapLoopTimes * sregvl);
    Mul(vregXM, vregXM, vregDyM, pregMain);
    MulDstAdd(vregXF, vregDyF, vregXM, pregLoop);
    Add(tempDy, vregDyM, vregDyF, pregLoop);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregXM, vregXF, pregLoop);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDyM, tempDy, pregLoop);
    ReduceSum(vregDgamma, vregXM, pregMain);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDgamma + overLapLoopTimes, vregDgamma,
                                                       pregMerge);
    ReduceSum(vregDbeta, vregDyM, pregMain);
    DataCopy<float, StoreDist::DIST_FIRST_ELEMENT_B32>(ubBinaryDbeta + overLapLoopTimes, vregDbeta, pregMerge);
}
```

**要点**: ①片段 1 `MulDstAdd(vregXM, vregDyM, vregXF)` 以主块为 dst；片段 2 `MulDstAdd(vregXF, vregDyF, vregXM)` 以余块为 dst，方向相反；②与 Add + MERGING Copy 配套做 dgamma/dbeta 双归约；③pregMain/pregLoop 区分满块与尾块掩码。

### 实例 7：group_norm_grad::VFComputeDbetaDs

- **来源类型**: `__aicore__`
- **共现 API**: MaskMergeMode
- **MulDstAdd 调用次数**: 1
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: group_norm_grad 的 VFComputeDbetaDs 在 repeat 循环里用 `MulDstAdd(vregX, vregDy, vregDgamma)` 滚动累加 dgamma = x*dy + dgamma_running，随后用 MERGING Copy 把结果回写到累加器。

（行 271-279）

```cpp
for (uint16_t i = 0; i < (uint16_t)repeatTimes; ++i) {
    preg = UpdateMask<float>(sreg);
    LoadUnAlignOneTensor<T>(curUbX, vregX, uSrcX, preg, sregvl);
    LoadUnAlignOneTensor<T>(curUbDy, vregDy, uSrcDy, preg, sregvl);
    MulDstAdd(vregX, vregDy, vregDgamma, preg);
    Add(tempDbeta, vregDbeta, vregDy, preg);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDbeta, tempDbeta, preg);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDgamma, vregX, preg);
}
```

**要点**: ①dstReg(vregX) 既是乘加结果又作为下一轮 dgamma 初值；②preg 由 UpdateMask 按剩余元素动态生成；③与 Add(tempDbeta)+Copy 配合同时维护 dbeta/dgamma 两个累加器。

### 实例 8：group_norm_grad::VecScope_L302

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: MaskMergeMode
- **MulDstAdd 调用次数**: 1
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 小组数全载入路径的 VFComputeDbetaDs，先用 Duplicate 清零累加器，再在循环内 `MulDstAdd(vregX, vregDy, vregDs)` 滚动累加 ds = x*dy + ds_running，MERGING Copy 回写。

（行 313-331）

```cpp
MaskReg preg;
uint32_t sreg = (uint32_t)eleNumPerC;
uint32_t sregvl = (uint32_t)this->VecLen_;
uint32_t ubOffSet = idx * eleNumPerC;
MaskReg pregAll = CreateMask<float, MaskPattern::ALL>();
curUbX = ubX + ubOffSet;
curUbDy = ubDy + ubOffSet;
Duplicate(vregDbeta, 0, pregAll);
Duplicate(vregDs, 0, pregAll);
DataCopyUnAlignPre(uSrcX, curUbX);
DataCopyUnAlignPre(uSrcDy, curUbDy);

preg = UpdateMask<float>(sreg);
LoadUnAlignOneTensor<T>(curUbX, vregX, uSrcX, preg, sregvl);
LoadUnAlignOneTensor<T>(curUbDy, vregDy, uSrcDy, preg, sregvl);
MulDstAdd(vregX, vregDy, vregDs, preg);
Add(tempDbeta, vregDbeta, vregDy, preg);
Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDbeta, tempDbeta, preg);
Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDs, vregX, preg);
```

**要点**: ①pregAll=CreateMask<ALL> 用于初始化清零，preg=UpdateMask 处理尾块；②MulDstAdd 的 srcReg1(vregDs) 是跨 repeat 的滚动累加器；③全载入场景 eleNumPerC 一次到位，循环只处理 repeat 维度。

### 实例 9：group_norm_grad::VFComputeDbetaDs

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: MaskMergeMode
- **MulDstAdd 调用次数**: 1
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: 与实例 7 同一函数体，但在 __VEC_SCOPE__ 上下文中被抽取，`MulDstAdd(vregX, vregDy, vregDgamma)` 完成 dgamma 的滚动乘加，是 group_norm_grad 反向规约的核心单步。

（行 271-279）

```cpp
for (uint16_t i = 0; i < (uint16_t)repeatTimes; ++i) {
    preg = UpdateMask<float>(sreg);
    LoadUnAlignOneTensor<T>(curUbX, vregX, uSrcX, preg, sregvl);
    LoadUnAlignOneTensor<T>(curUbDy, vregDy, uSrcDy, preg, sregvl);
    MulDstAdd(vregX, vregDy, vregDgamma, preg);
    Add(tempDbeta, vregDbeta, vregDy, preg);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDbeta, tempDbeta, preg);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregDgamma, vregX, preg);
}
```

**要点**: ①与实例 7 代码相同，仅来源作用域标签不同（__aicore__ vs __VEC_SCOPE__）；②dstReg 复用为累加器；③配套 MERGING Copy 把 tempDbeta/vregX 回写至 vregDbeta/vregDgamma。

### 实例 10：group_norm_grad::HardEvent::V_S

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: MaskMergeMode
- **MulDstAdd 调用次数**: 2
- **参数模式**: `T0_A4_M0_TYPEnone`（实参 4 个）
- **语义**: group_norm_grad 末段在 repeat 循环内对 dbeta/ds 两条线分别 MulDstAdd：dbeta = dbeta*gamma + sumDbeta、ds = ds*gamma + sumDs，再用 MERGING Copy 把结果回写为新的滚动和。

（行 858-867）

```cpp
for (uint16_t i = 0; i < (uint16_t)repeatTimes; ++i) {
    MaskReg preg = UpdateMask<float>(sreg);
    DataCopy(vregGamma, ubGamma + i * sregvl);
    DataCopy(vregDbeta, ubDbeta + i * sregvl);
    DataCopy(vregDs, ubDs + i * sregvl);
    MulDstAdd(vregDbeta, vregGamma, vregSumDbeta, preg);
    MulDstAdd(vregDs, vregGamma, vregSumDs, preg);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregSumDbeta, vregDbeta, preg);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(vregSumDs, vregDs, preg);
}
```

**要点**: ①两条 MulDstAdd 对称处理 vregDbeta/vregDs，srcReg0 同为 vregGamma；②滚动累加器 vregSumDbeta/vregSumDs 通过 Copy 回写更新；③DataCopy 预取 gamma/dbeta/ds 三路输入，循环紧凑。

### MulDstAdd 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| fake_quant_affine_cachemask | Adds, Cast, DataCopy, Div, DivSpecificMode | 反量化“乘反尺度+加零点”融合（HAS_ZP 编译期分流） | __VEC_SCOPE__ |
| fake_quant_affine_cachemask | Add, Cast, DataCopy, Div, DivSpecificMode | 反量化融合乘加，注释对比 Mul+Add 等价写法 | __VEC_SCOPE__ |
| atan2 | Axpy, Duplicate, Mul, RegTensor | Horner 法泰勒展开链式 y=y*x²+aₙ | __aicore__ |
| group_norm_grad | MaskMergeMode, MulAddDst | 尾块 dgamma 主+余累加 + MERGING 合并 | __VEC_SCOPE__ |
| group_norm_grad | MaskMergeMode, MulAddDst | 尾块 dbeta/dgamma 双路累加归约 | __VEC_SCOPE__ |
| group_norm_grad | MaskMergeMode | recompute overlap/remainder 双向乘加融合 | __VEC_SCOPE__ |
| group_norm_grad | MaskMergeMode | VFComputeDbetaDs 滚动累加 dgamma | __aicore__ |
| group_norm_grad | MaskMergeMode | 小组数全载入 ds 滚动累加 | __VEC_SCOPE__ |
| group_norm_grad | MaskMergeMode | VFComputeDbetaDs 滚动累加 dgamma（VEC 作用域） | __VEC_SCOPE__ |
| group_norm_grad | MaskMergeMode | 末段 dbeta/ds 按 gamma 滚动乘加回写 | __VEC_SCOPE__ |

