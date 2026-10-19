# Compares

**页面ID:** atlasascendc_api_07_0394  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0394.html

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

逐元素比较一个Tensor中的元素和另一个scalar的大小，如果比较后的结果为真，则输出结果的对应比特位为1，否则为0。

#### 函数原型

```
template <typename T = DefaultType, CMPMODE mode = CMPMODE::EQ, typename U, typename S>
__simd_callee__ inline void Compares(MaskReg& dst, U& srcReg, S scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 矢量源操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：int8_t、uint8_t、int16_t、uint16_t、half、bfloat16_t、int32_t、uint32_t、float、int64_t、uint64_t。 |
| mode | 比较模式。支持如下取值： - LT：小于（less than）- GT：大于（greater than） - GE：大于或等于（greater than or equal to）- EQ：等于（equal to）- NE：不等于（not equal to）- LE：小于或等于（less than or equal to） |
| U | 源操作数的RegTensor类型，由编译器自动推导，用户不需要填写。 |
| S | scalar数据类型。 Atlas 350 加速卡，支持的数据类型为：uint8_t/int8_t/uint16_t/int16_t/uint32_t/int32_t/half/float/bfloat16_t/uint64_t/int64_t |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | MaskReg类型，目的操作数。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void ComparesVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, T scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    AscendC::Reg::MaskReg cmpMaskReg;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);       
        AscendC::Reg::Compares<T, AscendC::CMPMODE::EQ>(cmpMaskReg, srcReg0, scalarValue, mask);
        AscendC::Reg::Select(dstReg, srcReg0, srcReg1, cmpMaskReg);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 Compares 实例

### 实例 1：fake_quant_with_min_max_vars_per_channel::VecScope_L21

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, Adds, Cast, Copy, Div, DivSpecificMode, LoadAlign, LoadDist, MaskMergeMode, MaskReg, Max, Maxs, Min, Mins, Mul, Muls, RegTensor, Select, StoreAlign, StoreDist, Sub, UpdateMask
- **Compares 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: 在伪量化 nudge 计算中，用 Compares 以 GT 判断 |min|+|max|>0 得到 bothZero 掩码、以 EQ 判断 scale==0 得到零值兜底掩码，再配合 Select 在多分支间挑选安全值。

（行 380-407）

```cpp
AscendC::Reg::Adds<float>(vregOne, vregZero, 1.0f, mask);
AscendC::Reg::Adds<float>(vregQRange, vregZero, qRange, mask);

// 2.1 scale = (max - min) / qRange
//     用 0-ULP Div 替代 (max-min)*invR：避免 invR=1/(qMax-qMin) 在 fp32 上的
//     round-to-nearest 误差与 (max-min)*invR 的舍入叠加，使 scale 精确等于
//     `(max-min)/(qMax-qMin)` 的 IEEE 单步除法结果（与 TF 实现一致）。
AscendC::Reg::Sub<float>(vregScale, vregMax, vregMin, mask);
AscendC::Reg::Copy<float>(vregDiffSaved, vregScale, mask);
AscendC::Reg::Div<float, &kDivMode>(vregScale, vregScale, vregQRange, mask);

// 2.2 bothZero = (|min| + |max| > 0) ? 1.0 : 0.0
AscendC::Reg::Abs<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregAbsMin, vregMin, mask);
AscendC::Reg::Abs<float, AscendC::Reg::MaskMergeMode::ZEROING>(vregAbsMax, vregMax, mask);
AscendC::Reg::Add<float>(vregAbsSum, vregAbsMin, vregAbsMax, mask);
AscendC::Reg::Compares<float, AscendC::CMPMODE::GT>(maskBoth, vregAbsSum, 0.0f, mask);
// Select: mask=1 → src0(vregOne); mask=0 → src1(vregZero)
AscendC::Reg::Select<float>(vregBoth, vregOne, vregZero, maskBoth);

// 2.3 scale==0 兜底：vregScaleSafe = (scale==0) ? 1.0 : scale
AscendC::Reg::Compares<float, AscendC::CMPMODE::EQ>(maskScaleZero, vregScale, 0.0f, mask);
AscendC::Reg::Select<float>(vregScaleSafe, vregOne, vregScale, maskScaleZero);

// 2.3b invScaleSafe = qRange / diffSafe
//      TF Nudge() 独立计算 inv_scale = (qMax-qMin)/(max-min)，
//      而非 1/scale，避免 scale 的 fp32 舍入误差在取倒数时被放大。
//      diffSafe = (diff==0) ? 1.0 : diff（复用 maskScaleZero，因 scale==0 ⟺ diff==0）
AscendC::Reg::Select<float>(vregDiffSaved, vregOne, vregDiffSaved, maskScaleZero);
```

**要点**:
- Compares 的 dst 是 MaskReg，按比特位指示比较真值，常与 Select 配对实现"标量条件多分支选择"。
- 同一函数内连续两次调用 Compares（GT、EQ）复用同一 mask，分别驱动不同 Select 分支。
- 模板参数 <float, CMPMODE::GT/EQ> 指定元素类型与比较模式，第 4 个参数 mask 控制参与比较的元素范围。

### 实例 2：threshold_grad_v2_d::ThresholdGradVFb16

- **来源类型**: `__simd_vf__`
- **共现 API**: Cast, CastTrait, Duplicate, LoadAlign, LoadDist, MaskMergeMode, MaskReg, RegLayout, RegTensor, SatMode, Select, StoreAlign, StoreDist, UpdateMask
- **Compares 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask，类型: float）
- **语义**: threshold_grad 反传中，用 Compares<float, LE> 将 self 与阈值 threshold 逐元素比较得到 cmpMask，再用 Select 在 zero 与 grad 间选择，实现 self<=阈值处置零、否则透传梯度（PyTorch 语义）。

（行 76-86）

```cpp
for (uint16_t i = 0; i < repeatTimes; ++i) {
    int32_t off = static_cast<int32_t>(i) * static_cast<int32_t>(vlF);
    uint32_t rem = count - (uint32_t)i * vlF;
    mask = AscendC::Reg::UpdateMask<float>(rem);
    AscendC::Reg::LoadAlign<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(selfReg, selfAddr + off);
    AscendC::Reg::Cast<float, T, kToFp32>(selfF, selfReg, mask);
    AscendC::Reg::Compares<float, AscendC::CMPMODE::LE>(cmpMask, selfF, threshold, mask);
    AscendC::Reg::LoadAlign<T, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(gradReg, gradAddr + off);
    AscendC::Reg::Select<T>(dstReg, zeroReg, gradReg, cmpMask);
    AscendC::Reg::StoreAlign<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(dstAddr + off, dstReg, mask);
}
```

**要点**:
- 先用 Cast 把 bfloat16 源提升到 float 再比较，保证 LE 比较精度。
- cmpMask 作为 Select 第 4 参数：mask=1 取 src0(zero)、mask=0 取 src1(grad)，对应"self<=th 置零"。
- 循环内每轮用 UpdateMask(rem) 重算 mask，处理尾部不满 repeat 的元素。

### 实例 3：power::AscendC::Axpy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, DataCopy, Duplicate, Exp, Log, MaskReg, Muls, RegTensor, RegTraitNumOne, Select, UpdateMask
- **Compares 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: 幂运算中用 Compares 两次分支选择：GT 判断 base>0 在 rawExp 与负底数值间选择，EQ 判断 base==0 在零广播值与上一步结果间选择，实现正/负/零三种底数的分情况求幂。

（行 167-198）

```cpp
mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
Reg::DataCopy(regBase, (__ubuf__ float*)(baseAddr + loopIdx * vl));

// ----- 主路径：rawExp = exp(power * log(|base|))，全程 in-place 复用 regMain -----
Reg::Abs (regMain, regBase, mask);              // regMain = |base|
Reg::Log (regMain, regMain, mask);              // regMain = log(|base|)
Reg::Muls(regMain, regMain, power, mask);       // regMain = power * log(|base|)
Reg::Exp (regMain, regMain, mask);              // regMain = rawExp

// ----- 负底数分支：regBranch = rawExp * negScalar -----
// 整数幂 power：negScalar 为 ±1，结果即 (-1)^power * rawExp；
// 非整数 power：negScalar 为 NaN（host 端预置），结果为 NaN（实数域未定义）。
Reg::Muls(regBranch, regMain, negScalar, mask);

// ----- 第 1 次合并：tmp = (base > 0 ? rawExp : negVal)，结果就地写回 regBranch -----
Reg::Compares<float, AscendC::CMPMODE::GT>(maskPos, regBase, ZERO_F, mask);
Reg::Select(regBranch, regMain, regBranch, maskPos);

// 至此 regMain 中的 rawExp 已用完，复用为 zeroBcast（base==0 时的取值）。
// zeroIsPos 在编译期已知，编译器会消去未走的 if 分支。
if constexpr (zeroIsPos == 1) {
    Reg::Duplicate(regMain, ZERO_F, mask);
} else {
    Reg::Duplicate(regMain, INF_F, mask);
}

// ----- 第 2 次合并：y = (base == 0 ? zeroBcast : tmp)，结果就地写回 regBranch -----
Reg::Compares<float, AscendC::CMPMODE::EQ>(maskZero, regBase, ZERO_F, mask);
Reg::Select(regBranch, regMain, regBranch, maskZero);

// 把当前 batch 的最终结果写回 UB。
Reg::DataCopy((__ubuf__ float*)(dstAddr + loopIdx * vl), regBranch, mask);
```

**要点**:
- Compares 产出的 maskPos / maskZero 是两次独立 Select 的控制掩码，体现"比较-选择"两段式条件赋值。
- ZERO_F 作为标量比较基准，配合 EQ 精确捕获 base==0 分支。
- Reg 命名空间下 Compares 用法与 AscendC::Reg 一致，模板参数 <float, CMPMODE::GT/EQ>。

### 实例 4：power::PowerGenericCompute

- **来源类型**: `__aicore__`
- **共现 API**: Abs, DataCopy, Duplicate, Exp, Log, MaskReg, Muls, RegTensor, RegTraitNumOne, Select, UpdateMask
- **Compares 调用次数**: 2
- **参数模式**: `T2_A4_M1_TYPEfloat_MASKmask`（实参 4 个，含 mask/mode: mask，类型: float）
- **语义**: 与实例 3 同一段 power 计算逻辑，但在 __aicore__ 顶层入口函数中调用，用 Compares 的 GT/EQ 两次比较驱动 Select 完成正/负/零底数分支。

（行 167-198）

```cpp
mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
Reg::DataCopy(regBase, (__ubuf__ float*)(baseAddr + loopIdx * vl));

// ----- 主路径：rawExp = exp(power * log(|base|))，全程 in-place 复用 regMain -----
Reg::Abs (regMain, regBase, mask);              // regMain = |base|
Reg::Log (regMain, regMain, mask);              // regMain = log(|base|)
Reg::Muls(regMain, regMain, power, mask);       // regMain = power * log(|base|)
Reg::Exp (regMain, regMain, mask);              // regMain = rawExp

// ----- 负底数分支：regBranch = rawExp * negScalar -----
// 整数幂 power：negScalar 为 ±1，结果即 (-1)^power * rawExp；
// 非整数 power：negScalar 为 NaN（host 端预置），结果为 NaN（实数域未定义）。
Reg::Muls(regBranch, regMain, negScalar, mask);

// ----- 第 1 次合并：tmp = (base > 0 ? rawExp : negVal)，结果就地写回 regBranch -----
Reg::Compares<float, AscendC::CMPMODE::GT>(maskPos, regBase, ZERO_F, mask);
Reg::Select(regBranch, regMain, regBranch, maskPos);

// 至此 regMain 中的 rawExp 已用完，复用为 zeroBcast（base==0 时的取值）。
// zeroIsPos 在编译期已知，编译器会消去未走的 if 分支。
if constexpr (zeroIsPos == 1) {
    Reg::Duplicate(regMain, ZERO_F, mask);
} else {
    Reg::Duplicate(regMain, INF_F, mask);
}

// ----- 第 2 次合并：y = (base == 0 ? zeroBcast : tmp)，结果就地写回 regBranch -----
Reg::Compares<float, AscendC::CMPMODE::EQ>(maskZero, regBase, ZERO_F, mask);
Reg::Select(regBranch, regMain, regBranch, maskZero);

// 把当前 batch 的最终结果写回 UB。
Reg::DataCopy((__ubuf__ float*)(dstAddr + loopIdx * vl), regBranch, mask);
```

**要点**:
- 同一 kernel 文件中 VEC_SCOPE 与 aicore 两个入口共享同一份向量计算体，Compares 调用完全一致。
- 来源类型 __aicore__ 表示该函数为核函数顶层入口，可被调度直接调用。
- 两次 Compares 复用同一 mask，零值与正值的分支互斥。

### 实例 5：logical_or::LogicalOrFloatCustom

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, Duplicate, LoadDist, MaskReg, Or, RegTensor, Select, StoreDist, UpdateMask
- **Compares 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 逻辑或算子中，对两路输入做位 Or 后用 Compares<T, NE> 判断 Or 结果 != 0 产出 cmpMask，再 Duplicate 1/0 并用 Select 转成 uint8 布尔输出。

（行 64-89）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    preg = Reg::UpdateMask<T>(sregMask);
    // 以浮点类型 T 加载输入
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src1Value, src1Addr + VL_T * j);
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src2Value, src2Addr + VL_T * j);

    // 位OR操作：当作对应位宽的整形处理
    Reg::Or((Reg::RegTensor<IntT>&)orRes, (Reg::RegTensor<IntT>&)src1Value, (Reg::RegTensor<IntT>&)src2Value, preg);

    // Compare: OR结果 != 0 (NE模式)
    Reg::Compares<T, CMPMODE::NE>(cmpMask, orRes, static_cast<T>(0), preg);

    // Select: 根据cmpMask选择1或0 (uint8_t)
    Reg::Duplicate(oneReg, static_cast<uint8_t>(1));
    Reg::Duplicate(zeroReg, static_cast<uint8_t>(0));
    Reg::Select<uint8_t>(dstReg, oneReg, zeroReg, cmpMask);

    // 存储uint8 BOOL结果
    if constexpr (sizeof(T) == sizeof(half)) {
        Reg::DataCopy<uint8_t, Reg::StoreDist::DIST_PACK_B16>(
        dstAddr + VL_T * j, dstReg, preg);
    } else {
        Reg::DataCopy<uint8_t, Reg::StoreDist::DIST_PACK4_B32>(
        dstAddr + VL_T * j, dstReg, preg);
    }
}
```

**要点**:
- Compares 的 NE 模式把数值比较转化为布尔掩码，是实现"非零即真"的标准手法。
- 标量基准用 static_cast<T>(0)，与输入类型一致避免精度问题。
- 输出按 sizeof(T) 选择 DIST_PACK_B16 或 DIST_PACK4_B32 存储打包方式。

### 实例 6：logical_or::Vec::ElemwiseBinaryOP

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: DataCopy, Duplicate, LoadDist, MaskReg, Or, RegTensor, Select, StoreDist, UpdateMask
- **Compares 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: 与实例 5 同一 logical_or 向量计算体，在 __VEC_SCOPE__ 入口中用 Compares<T, NE> 把 Or 结果转成非零布尔掩码，配合 Select 输出 uint8。

（行 64-89）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    preg = Reg::UpdateMask<T>(sregMask);
    // 以浮点类型 T 加载输入
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src1Value, src1Addr + VL_T * j);
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(src2Value, src2Addr + VL_T * j);

    // 位OR操作：当作对应位宽的整形处理
    Reg::Or((Reg::RegTensor<IntT>&)orRes, (Reg::RegTensor<IntT>&)src1Value, (Reg::RegTensor<IntT>&)src2Value, preg);

    // Compare: OR结果 != 0 (NE模式)
    Reg::Compares<T, CMPMODE::NE>(cmpMask, orRes, static_cast<T>(0), preg);

    // Select: 根据cmpMask选择1或0 (uint8_t)
    Reg::Duplicate(oneReg, static_cast<uint8_t>(1));
    Reg::Duplicate(zeroReg, static_cast<uint8_t>(0));
    Reg::Select<uint8_t>(dstReg, oneReg, zeroReg, cmpMask);

    // 存储uint8 BOOL结果
    if constexpr (sizeof(T) == sizeof(half)) {
        Reg::DataCopy<uint8_t, Reg::StoreDist::DIST_PACK_B16>(
        dstAddr + VL_T * j, dstReg, preg);
    } else {
        Reg::DataCopy<uint8_t, Reg::StoreDist::DIST_PACK4_B32>(
        dstAddr + VL_T * j, dstReg, preg);
    }
}
```

**要点**:
- 同一算子的 aicore 入口与 VEC_SCOPE 入口复用同一向量段，Compares 调用一致。
- 模板参数 T 由外层传入，Compares 自动适配 half/float 等位宽。
- NE 比较 + Duplicate(1, cmpMask) 是把比较掩码落到具体数值的常见二步。

### 实例 7：threshold_grad_v2_d::ThresholdGradVF

- **来源类型**: `__simd_vf__`
- **共现 API**: AddrReg, CreateAddrReg, Duplicate, LoadAlign, MaskReg, RegTensor, Select, StoreAlign, UpdateMask
- **Compares 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEnone_MASKMask+mask`（实参 4 个，含 mask/mode: Mask, mask）
- **语义**: threshold_grad 的 fp 路径，用 Compares<T, LE> 比较 self 与 threshold 得 cmpMask，Select 在 zero 与 grad 间选择；gateMode 在编译期已知时走恒透传/恒置零分支，仅动态分支调用 Compares。

（行 47-56）

```cpp
if (gateMode == 1) { // 恒透传 grad
    dstReg = gradReg;
} else if (gateMode == 2) { // 恒置 0
    dstReg = zeroReg;
} else { // PyTorch: self<=th -> 0 ; 否则(含 NaN, NaN<=th 为 false) grad
    AscendC::Reg::LoadAlign(selfReg, selfAddr, aReg);
    AscendC::Reg::Compares<T, AscendC::CMPMODE::LE>(cmpMask, selfReg, threshold, mask);
    AscendC::Reg::Select<T>(dstReg, zeroReg, gradReg, cmpMask);
}
AscendC::Reg::StoreAlign(dstAddr, dstReg, aReg, mask);
```

**要点**:
- 使用 AddrReg 变体（LoadAlign 带 aReg 地址寄存器）加载源，Compares 接收 RegTensor 源与标量 threshold。
- gateMode==1/2 分支不调用 Compares，编译期常量折叠消去比较开销。
- NaN<=th 为 false，因此 NaN 输入走透传 grad 分支，与 PyTorch 一致。

### 实例 8：reduce_any::CastB32Any

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Compares 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: reduce_any 的类型转换核中，用 Compares<R, NE> 判断 srcReg != 0.0f 得 cmpMask，再用 Duplicate 先置 0、再按 cmpMask 置 1，把任意类型归一为 0/1 布尔。

（行 51-59）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    InMask = Reg::UpdateMask<R>(InSize);
    OutMask = Reg::UpdateMask<T>(OutSize);
    Reg::DataCopy<R, Reg::PostLiteral::POST_MODE_UPDATE>(srcReg, srcAddr, VL_B32);
    Reg::Compares<R, CMPMODE::NE>(cmpMask, srcReg, 0.0f, InMask);
    Reg::Duplicate(dstReg, 0);
    Reg::Duplicate(dstReg, 1, cmpMask);
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(dstAddr, dstReg, VL_B32, OutMask);
}
```

**要点**:
- Compares 的 NE 标量基准 0.0f，把非零元素标记为真。
- Duplicate(dstReg, 1, cmpMask) 是带掩码的标量广播，等价于"真位置 1、假位置保持 0"。
- 输入用 POST_MODE_UPDATE 带地址自增的 DataCopy 加载，循环处理多 batch。

### 实例 9：reduce_all::CastZeroOne

- **来源类型**: `__aicore__`
- **共现 API**: DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Compares 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: reduce_all 的 0/1 归一核中，用 Compares<R, NE> 判断 srcReg != 0 得 cmpMask，再 Duplicate 0/1 转成布尔，语义与 reduce_any 的转换段一致但服务于"全与"归约。

（行 52-60）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    InMask = Reg::UpdateMask<R>(InSize);
    OutMask = Reg::UpdateMask<T>(OutSize);
    Reg::DataCopy<R, Reg::PostLiteral::POST_MODE_UPDATE>(srcReg, srcAddr, VL_LENGTH);
    Reg::Compares<R, CMPMODE::NE>(cmpMask, srcReg, 0.0f, InMask);
    Reg::Duplicate(dstReg, 0);
    Reg::Duplicate(dstReg, 1, cmpMask);
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(dstAddr, dstReg, VL_LENGTH, OutMask);
}
```

**要点**:
- 与 reduce_any 共用同一比较-广播模式，差别仅在归约语义（any vs all）在上层处理。
- VL_LENGTH 作为加载长度，Compares 用 InMask 控制有效元素。
- cmpMask 直接驱动 Duplicate 的掩码广播，无需 Select。

### 实例 10：reduce_any::Vec::ElemwiseUnaryOP

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Compares 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: reduce_any 的 VEC_SCOPE 入口，与实例 8 同一转换体，用 Compares<R, NE> 把 srcReg 非零判断转为 cmpMask，Duplicate 落到 0/1。

（行 51-59）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    InMask = Reg::UpdateMask<R>(InSize);
    OutMask = Reg::UpdateMask<T>(OutSize);
    Reg::DataCopy<R, Reg::PostLiteral::POST_MODE_UPDATE>(srcReg, srcAddr, VL_B32);
    Reg::Compares<R, CMPMODE::NE>(cmpMask, srcReg, 0.0f, InMask);
    Reg::Duplicate(dstReg, 0);
    Reg::Duplicate(dstReg, 1, cmpMask);
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(dstAddr, dstReg, VL_B32, OutMask);
}
```

**要点**:
- aicore 与 VEC_SCOPE 两个入口共享同一 unary 向量段，Compares 调用一致。
- VL_B32 为 b32 类型加载长度，InMask/OutMask 分别控制输入比较与输出写回。
- NE 模式 + 0.0f 基准是布尔化的标准组合。

### 实例 11：reduce_all::Vec::ElemwiseUnaryOP

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: DataCopy, Duplicate, MaskReg, PostLiteral, RegTensor, UpdateMask
- **Compares 调用次数**: 1
- **参数模式**: `T2_A4_M1_TYPEnone_MASKMask`（实参 4 个，含 mask/mode: Mask）
- **语义**: reduce_all 的 VEC_SCOPE 入口，与实例 9 同一转换体，用 Compares<R, NE> 判断非零并 Duplicate 为 0/1 布尔输出。

（行 52-60）

```cpp
for (uint16_t j = 0; j < loopTimes; j++) {
    InMask = Reg::UpdateMask<R>(InSize);
    OutMask = Reg::UpdateMask<T>(OutSize);
    Reg::DataCopy<R, Reg::PostLiteral::POST_MODE_UPDATE>(srcReg, srcAddr, VL_LENGTH);
    Reg::Compares<R, CMPMODE::NE>(cmpMask, srcReg, 0.0f, InMask);
    Reg::Duplicate(dstReg, 0);
    Reg::Duplicate(dstReg, 1, cmpMask);
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(dstAddr, dstReg, VL_LENGTH, OutMask);
}
```

**要点**:
- 与 aicore 入口共享向量段，Compares 调用一致，仅来源类型不同。
- VL_LENGTH 加载长度，OutMask 控制输出写回范围。
- NE 比较 + 掩码广播是 reduce 类算子布尔化的通用范式。

### Compares 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| fake_quant_with_min_max_vars_per_channel | Abs, Add, Adds, Cast | 标量 GT/EQ 比较产掩码 → Select 多分支兜底（bothZero、scale==0 安全值选择） | __VEC_SCOPE__ |
| threshold_grad_v2_d | Cast, CastTrait, Duplicate, LoadAlign | LE 比较阈值 → Select 置零/透传梯度（先 Cast 提精度） | __simd_vf__ |
| power | Abs, DataCopy, Duplicate, Exp | GT(base>0)+EQ(base==0) 两次比较 → Select 三分支求幂 | __VEC_SCOPE__ |
| power | Abs, DataCopy, Duplicate, Exp | GT(base>0)+EQ(base==0) 两次比较 → Select 三分支求幂（aicore 入口） | __aicore__ |
| logical_or | DataCopy, Duplicate, LoadDist, MaskReg | NE 判断 Or 结果非零 → Select 输出 uint8 布尔 | __aicore__ |
| logical_or | DataCopy, Duplicate, LoadDist, MaskReg | NE 判断 Or 结果非零 → Select 输出 uint8 布尔（VEC_SCOPE 入口） | __VEC_SCOPE__ |
| threshold_grad_v2_d | AddrReg, CreateAddrReg, Duplicate, LoadAlign | LE 比较阈值 → Select 置零/透传，gateMode 编译期分流 | __simd_vf__ |
| reduce_any | DataCopy, Duplicate, MaskReg, PostLiteral | NE 非零判断 → Duplicate 掩码广播为 0/1 布尔 | __aicore__ |
| reduce_all | DataCopy, Duplicate, MaskReg, PostLiteral | NE 非零判断 → Duplicate 掩码广播为 0/1 布尔 | __aicore__ |
| reduce_any | DataCopy, Duplicate, MaskReg, PostLiteral | NE 非零判断 → Duplicate 掩码广播为 0/1 布尔（VEC_SCOPE 入口） | __VEC_SCOPE__ |
| reduce_all | DataCopy, Duplicate, MaskReg, PostLiteral | NE 非零判断 → Duplicate 掩码广播为 0/1 布尔（VEC_SCOPE 入口） | __VEC_SCOPE__ |

