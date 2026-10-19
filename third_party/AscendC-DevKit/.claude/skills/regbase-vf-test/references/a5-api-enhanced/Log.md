# Log

**页面ID:** atlasascendc_api_07_0349  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0349.html

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

根据mask对输入数据srcReg进行求自然对数操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0349_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, auto mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Log(U& dstReg, U& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 |
| mode | 可配置为MaskMergeMode的枚举或LogSpecificMode的结构体指针。- MaskMergeMode，选择MERGING模式或ZEROING模式。  - ZEROING，mask未筛选的元素在dstReg中置零。  - MERGING，暂不支持。 - LogSpecificMode，定义如下：``` enum class LogAlgo {     INTRINSIC = 0,     PRECISION_1ULP_FTZ_TRUE,     PRECISION_1ULP_FTZ_FALSE, }; struct LogSpecificMode{     MaskMergeMode mrgMode = MaskMergeMode::ZEROING,     LogAlgo algo = LogAlgo::INTRINSIC; }; ```   - mrgMode：选择MERGING模式或ZEROING模式。  - algo：用于配置Subnormal模式。    - LogAlgo::INTRINSIC、LogAlgo::PRECISION_1ULP_FTZ_TRUE，使用单指令计算得出结果，所有Subnormal被近似为0。    - LogAlgo::PRECISION_1ULP_FTZ_FALSE，支持Subnormal数据计算。 |
| U | 源操作数和目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

src输入为-0时，输出-inf。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void LogVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    // Subnormal模式
    // static constexpr AscendC::Reg::LogSpecificMode mode = {MaskMergeMode::ZEROING, LogAlgo::PRECISION_1ULP_FTZ_FALSE};
    for (uint16_t i = 0; i < repeatTimes; i++) {     
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Log(dstReg, srcReg, mask);
        // Subnormal模式
        // AscendC::Reg::Log<DTYPE, &mode>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---

## 从 Ascend 950PR / arch35 算子源码提取的 Log 实例

### 实例 1：cdist::Reg::StoreUnAlignPost

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Add, CreateMask, Duplicate, Exp, ExpSpecificMode, LoadAlign, LogSpecificMode, MaskMergeMode, MaskPattern, MaskReg, Muls, ReduceSum, RegTensor, StoreUnAlign, StoreUnAlignPost, Sub, UnalignRegForStore, UpdateMask
- **Log 调用次数**: 3
- **参数模式**: `T2_A3_M1_TYPEfloat_MASKmask`（实参 3 个，含 mask/mode: mask，类型: float）
- **语义**: 在 cdist 的 L_p 距离计算中，对 |x1-x2| 取自然对数后乘以指数 p，再配合 Exp 还原为 |x1-x2|^p，是距离公式的核心步骤。

**片段 1** (行 619-627):

```cpp
__local_mem__ float * x2Offset = srcPtrX2 + b * rSize_ * MAlign_ + r * MAlign_ + vlLen_ * m;
Reg::LoadAlign(x1Reg, x1Offset);
Reg::LoadAlign(x2Reg, x2Offset);
Reg::Sub(subReg, x1Reg, x2Reg, maskAll);
Reg::Abs(absReg, subReg, maskAll);
Reg::Log<float, &modelog>(logReg, absReg, maskAll);
Reg::Muls(mulReg, logReg, (float)p_, maskAll);
Reg::Exp<float, &modeexp>(expReg, mulReg, maskAll);
Reg::ReduceSum(sumReg, expReg, maskAll);
```

**片段 2** (行 631-648):

```cpp
__local_mem__ float * x2Offset = srcPtrX2 + b * rSize_ * MAlign_ + r * MAlign_ + vlLen_ * loopNumM;
Reg::LoadAlign(x1Reg, x1Offset);
Reg::LoadAlign(x2Reg, x2Offset);
Reg::Sub(subReg, x1Reg, x2Reg, maskTail);
Reg::Abs(absReg, subReg, maskTail);
Reg::Log<float, &modelog>(logReg, absReg, maskTail);
Reg::Muls(mulReg, logReg, (float)p_, maskTail);
Reg::Exp<float, &modeexp>(expReg, mulReg, maskTail);
Reg::ReduceSum(sumReg, expReg, maskTail);
Reg::Add(dstReg, dstReg, sumReg, maskOne);
if (ubLoopNumM_ == 1) {
    Reg::Log<float, &modelog>(logReg, dstReg, maskOne);
    Reg::Muls(mulReg, logReg, (float)(1 / p_), maskOne);
    Reg::Exp<float, &modeexp>(expReg, mulReg, maskOne);
    Reg::StoreUnAlign(yOffset, expReg, uReg, BASE_ONE);
} else {
    Reg::StoreUnAlign(yOffset, dstReg, uReg, BASE_ONE);
}
```

**要点**: 1) 通过 `Log<float, &modelog>` 显式指定 float 类型与 LogSpecificMode（含 LogAlgo）模式；2) 用 maskAll/maskTail 区分满块与尾元素；3) 与 Abs→Log→Muls→Exp→ReduceSum 组合完成 |x1-x2|^p 的归约。

### 实例 2：log_sigmoid::LogSigmoidCustom

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, CompareScalar, DataCopy, Div, Duplicate, Exp, MaskReg, Min, Mul, Muls, RegTensor, RegTraitNumOne, Select, Sub, UpdateMask
- **Log 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 log_sigmoid 中用 Log 计算 log(1+exp(-|x|))，配合 Exp/Adds/Div/Select 实现 log1p 等价的高精度公式，避免直接 log(sigmoid(x)) 的数值下溢。

（行 66-86）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    // regCopyIn
    mask = Reg::UpdateMask<T, Reg::RegTraitNumOne>(count);
    Reg::DataCopy(x, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::Min(minRes, x, zeroReg, mask);        // x1 = min(x, 0)
    Reg::Abs(xAbs, x, mask);                   // x2 = abs(x)
    Reg::Muls(xAbsNeg, xAbs, valNegOne, mask); // x3 = -x2
    Reg::Exp(expRes, xAbsNeg, mask);           // x4 = e^x3
    // log1p
    Reg::Adds(expResPlusOne, expRes, valPosOne, mask);              // y1 = 1 + x4
    Reg::Adds(expResPlusOneSubOne, expResPlusOne, valNegOne, mask); // y2 = y1 - 1
    Reg::Div(divRes, expRes, expResPlusOneSubOne, mask);            // y3 = x4 / y2
    Reg::Log(logExpXPlus1, expResPlusOne, mask);                    // y4 = log(y1)
    Reg::Mul(mulRes, logExpXPlus1, divRes, mask);                   // y5 = y4 * y3
    Reg::CompareScalar<T, CMPMODE::NE>(cmpLog1pPosMaskReg, expResPlusOne, valPosOne, mask);
    Reg::Select(selectRes, mulRes, expRes, cmpLog1pPosMaskReg); // z1 = select(x4, y5)
    Reg::Sub(ans, minRes, selectRes, mask);                     // z2 = x1 - z1
    // regCopyOut
    Reg::DataCopy((__ubuf__ T*)(dstAddr + loopIdx * vlSize), ans, mask);
}
```

**要点**: 1) Log 作用于 1+exp(-|x|)，配合 CompareScalar+Select 处理 x=0 边界；2) 全程用 mask 控制尾元素；3) 与 Exp/Muls/Div 组合实现数值稳定的 log_sigmoid。

### 实例 3：softmax_cross_entropy_with_logits::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Cast, CreateAddrReg, CreateMask, DataCopy, Div, LoadDist, MaskPattern, MaskReg, Mul, RegTensor, StoreDist, Sub, UpdateMask
- **Log 调用次数**: 4
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 在 softmax 交叉熵反向中，对归约和 sumReg 取 Log，再用 Sub 计算 log(sum)-sub 作为 softmax 概率的对数，配合 Mul 与 labels 相乘得到梯度。

**片段 1** (行 523-534):

```cpp
if constexpr (sizeof(T) == 2) {
    AscendC::Reg::Cast<T, float, castB32ToB16>(backPropReg, backPropReg32, pregMain);
    AscendC::Reg::DataCopy<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(
        backPropAddr, backPropReg, offsetT, pregMain);
} else {
    AscendC::Reg::DataCopy(backPropAddr, backPropReg32, offset, pregMain);
}
AscendC::Reg::DataCopy(subReg, subAddr, offset);
AscendC::Reg::Log(logReg, sumReg, pregMain);
AscendC::Reg::Sub(temp2Reg, logReg, subReg, pregMain);
AscendC::Reg::Mul(temp2Reg, temp2Reg, labelsReg32, pregMain);
AscendC::Reg::DataCopy(temp2Addr, temp2Reg, offset, pregMain);
```

**片段 2** (行 549-561):

```cpp
if constexpr (sizeof(T) == 2) {
    AscendC::Reg::Cast<T, float, castB32ToB16>(backPropReg, backPropReg32, preg);
    AscendC::Reg::DataCopy<T, AscendC::Reg::StoreDist::DIST_PACK_B32>(
        backPropAddr + i * rAlign + repeatTimes * vfLen, backPropReg, preg);
} else {
    AscendC::Reg::DataCopy(backPropAddr + i * rAlign + repeatTimes * vfLen, backPropReg32,
                                pregAlign);
}
AscendC::Reg::DataCopy(subReg, subAddr + i * rAlign + repeatTimes * vfLen);
AscendC::Reg::Log(logReg, sumReg, preg);
AscendC::Reg::Sub(temp2Reg, logReg, subReg, preg);
AscendC::Reg::Mul(temp2Reg, temp2Reg, labelsReg32, preg);
AscendC::Reg::DataCopy(temp2Addr + i * rAlign + repeatTimes * vfLen, temp2Reg, pregAlign);
```

**要点**: 1) 无 mask 参数（用 pregMain/preg 全量 predicate）；2) Log(sumReg) 是 softmax 归一化分母的对数，Sub 后得 log-softmax；3) 配合 AddrReg/CreateAddrReg 做按 repeat 的偏移寻址。

### 实例 4：log1p::Log1pCustom

- **来源类型**: `__aicore__`
- **共现 API**: Adds, Cast, CompareScalar, DataCopy, Div, Duplicate, LoadDist, MaskReg, Mul, RegTensor, RegTraitNumOne, Select, StoreDist, UpdateMask
- **Log 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 log1p 中用 log(1+x) 的等价高精度公式 log(1+x)≈log(1+x)+x-x/((1+x)-1)，通过 Adds→Div→Log→Mul→Select 计算，并用 CompareScalar 处理 1+x==1 与 1+x==inf 的边界。

**片段 1** (行 54-72):

```cpp
for (uint16_t loopIdx = 0; loopIdx < static_cast<uint16_t>(loopNum); loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

    Reg::Adds(vregInputAddOne, vregInput, FP32_ONE, mask);
    Reg::Adds(vregInputMid, vregInputAddOne, FP32_NEG_ONE, mask);
    Reg::Div(vregInputMid, vregInput, vregInputMid, mask);
    Reg::Log(vregOutput, vregInputAddOne, mask);
    Reg::Mul(vregOutput, vregOutput, vregInputMid, mask);
    Reg::CompareScalar<float, CMPMODE::NE>(cmpMaskReg, vregInputAddOne, FP32_ONE, mask);
    Reg::Select(vregOutput, vregOutput, vregInput, cmpMaskReg);
    Reg::CompareScalar<float, CMPMODE::NE>(cmpMaskReg, vregInputAddOne, FP32_INF, mask);
    Reg::Duplicate(vregInputMid, FP32_INF, mask);
    Reg::Select(vregOutput, vregOutput, vregInputMid, cmpMaskReg);

    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_NORM_B32>((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**片段 2** (行 78-98):

```cpp
for (uint16_t loopIdx = 0; loopIdx < static_cast<uint16_t>(loopNum); loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(vregInput16, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::Cast<float, T, castTrait0>(vregInput, vregInput16, mask);

    Reg::Adds(vregInputAddOne, vregInput, FP32_ONE, mask);
    Reg::Adds(vregInputMid, vregInputAddOne, FP32_NEG_ONE, mask);
    Reg::Div(vregInputMid, vregInput, vregInputMid, mask);
    Reg::Log(vregOutput, vregInputAddOne, mask);
    Reg::Mul(vregOutput, vregOutput, vregInputMid, mask);
    Reg::CompareScalar<float, CMPMODE::NE>(cmpMaskReg, vregInputAddOne, FP32_ONE, mask);
    Reg::Select(vregOutput, vregOutput, vregInput, cmpMaskReg);
    Reg::CompareScalar<float, CMPMODE::NE>(cmpMaskReg, vregInputAddOne, FP32_INF, mask);
    Reg::Duplicate(vregInputMid, FP32_INF, mask);
    Reg::Select(vregOutput, vregOutput, vregInputMid, cmpMaskReg);

    Reg::Cast<T, float, castTrait1>(vregOutput16, vregOutput, mask);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_PACK_B32>((__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput16, mask);
}
```

**要点**: 1) Log 作用于 vregInputAddOne(=1+x)，配合 Div(x, (1+x)-1) 得到修正项；2) 用 Select 在 x→0 时回退为 x，x→inf 时回退为 inf；3) 同时给出 float 与 half（经 Cast）两条数据路径。

### 实例 5：sigmoid_cross_entropy_with_logits_v2::CalcBCEWithLogitsV2

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Adds, DataCopy, Duplicate, Exp, MaskReg, Mins, Mul, Neg, PostLiteral, RegTensor, Sub, UpdateMask
- **Log 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 在 BCE with logits v2 中，用 Log(1+exp(-|x|)) 得到 log-sigmoid 部分，配合 Min/Abs/Neg/Exp/Adds 计算，再 Sub 拼出数值稳定的 BCE 公式。

（行 87-100）

```cpp
if constexpr (HAS_POS_WEIGHT) {
    Reg::DataCopy<T, Reg::PostLiteral::POST_MODE_UPDATE>(regPosWeight, posWeightAddr,
                                                                   (int32_t)oneRepeat);
}

Reg::Mins(regMinVal, regX, (T)0.0f, pregUp);
Reg::Abs(regAbsX, regX, pregUp);
Reg::Neg(regNegAbsX, regAbsX, pregUp);
Reg::Exp(regExpNegAbsX, regNegAbsX, pregUp);
Reg::Adds(regOneAddExp, regExpNegAbsX, (T)1.0f, pregUp);
Reg::Log(regLog, regOneAddExp, pregUp);

Reg::Sub(regLogSigmoid, regMinVal, regLog, pregUp);
```

**要点**: 1) 无 mask（用 pregUp predicate）；2) Log 作用于 regOneAddExp(=1+exp(-|x|))；3) 配合 Mins 取 min(x,0) 与 Sub 拼出 BCE 公式。

### 实例 6：sigmoid_cross_entropy_with_logits::CalcSigmoidCrossEntropyWithLogits

- **来源类型**: `__aicore__`
- **共现 API**: Abs, Add, DataCopy, Duplicate, Exp, MaskReg, Maxs, Mul, Neg, RegTensor, RegTraitNumOne, Sub, UpdateMask
- **Log 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 sigmoid 交叉熵中，对 1+exp(-|x|) 取 Log 得到 log-sigmoid，配合 Maxs/Abs/Neg/Exp/Add 组合，再用 Mul(predict,target) 拼出 BCE 公式。

（行 70-88）

```cpp
Reg::DataCopy(vregPredict, (__ubuf__ T*)(src0Addr + loopIdx * vlSize));
Reg::DataCopy(vregTarget, (__ubuf__ T*)(src1Addr + loopIdx * vlSize));

Reg::Duplicate(vregOneAddExp, (T)1.0f, mask);

Reg::Maxs(vregMaxPredict, vregPredict, (T)0.0f, mask);

Reg::Abs(vregAbsPredict, vregPredict, mask);

Reg::Neg(vregNegAbsPredict, vregAbsPredict, mask);

Reg::Exp(vregExpNegAbs, vregNegAbsPredict, mask);

Reg::Add(vregOneAddExp, vregExpNegAbs, vregOneAddExp, mask);

Reg::Log(vregLog, vregOneAddExp, mask);

Reg::Mul(vregMulPredictTarget, vregPredict, vregTarget, mask);
```

**要点**: 1) 用 mask 控制尾元素；2) Log 作用于 vregOneAddExp，需先 Duplicate(1.0) 再 Add(exp(-|x|))；3) Maxs(x,0) 与 Abs/Neg/Exp 共同实现 exp(-|x|)。

### 实例 7：power::AscendC::Axpy

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Abs, Compares, DataCopy, Duplicate, Exp, MaskReg, Muls, RegTensor, RegTraitNumOne, Select, UpdateMask
- **Log 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 power 算子中用 Log(|base|)→Muls(power)→Exp 实现 base^power = exp(power*log(|base|))，并通过 Compares+Select 处理负底数与零底数分支。

（行 165-199）

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    // 更新尾元素 mask 并把当前 batch 的 base 搬入寄存器。
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
}
```

**要点**: 1) Log 作用于 Abs(base) 后的 regMain，全程 in-place 复用寄存器；2) 负底数用 negScalar(±1 或 NaN) 区分整数/非整数幂；3) 零底数用 zeroIsPos 编译期分支选 0 或 inf。

### 实例 8：sparse_softmax_cross_entropy_with_logits::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, CreateAddrReg, CreateMask, DataCopy, Div, MaskPattern, MaskReg, RegTensor, Sub, UpdateMask
- **Log 调用次数**: 4
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 在 sparse softmax 交叉熵中，对归约和 sumReg 取 Log，Sub(log(sum)-sub) 得到 log-softmax，配合 Div 做归一化，按 repeat 与 tailLoop 分两段处理。

（行 498-518）

```cpp
for (uint16_t j = 0; j < repeatTimes; j++) {
    AscendC::Reg::AddrReg offsetT = AscendC::Reg::CreateAddrReg<T1>(i, rAlign, j, vfLen);
    AscendC::Reg::AddrReg offset = AscendC::Reg::CreateAddrReg<float>(i, rAlign, j, vfLen);
    AscendC::Reg::DataCopy(temp1Reg, temp1Addr, offset);
    AscendC::Reg::DataCopy(subReg, subAddr, offset);
    AscendC::Reg::Div(temp1Reg, temp1Reg, sumReg, pregMain);
    AscendC::Reg::DataCopy(temp1Addr, temp1Reg, offset, pregMain);
    AscendC::Reg::Log(logReg, sumReg, pregMain);
    AscendC::Reg::Sub(temp2Reg, logReg, subReg, pregMain);
    AscendC::Reg::DataCopy(temp2Addr, temp2Reg, offset, pregMain);
}

for (uint16_t k = 0; k < tailLoop; k++) {
    AscendC::Reg::DataCopy(temp1Reg, temp1Addr + i * rAlign + repeatTimes * vfLen);
    AscendC::Reg::DataCopy(subReg, subAddr + i * rAlign + repeatTimes * vfLen);
    AscendC::Reg::Div(temp1Reg, temp1Reg, sumReg, preg);
    AscendC::Reg::DataCopy(temp1Addr + i * rAlign + repeatTimes * vfLen, temp1Reg, preg);
    AscendC::Reg::Log(logReg, sumReg, preg);
    AscendC::Reg::Sub(temp2Reg, logReg, subReg, preg);
    AscendC::Reg::DataCopy(temp2Addr + i * rAlign + repeatTimes * vfLen, temp2Reg, preg);
}
```

**要点**: 1) 无 mask（pregMain/preg predicate）；2) Log(sumReg) 为 softmax 分母对数；3) 配合 CreateAddrReg 做按 j 的偏移寻址，tailLoop 处理尾块。

### 实例 9：cross_entropy_loss::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, CreateAddrReg, CreateMask, DataCopy, MaskPattern, MaskReg, RegTensor, Sub, UpdateMask
- **Log 调用次数**: 4
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 在 cross_entropy_loss 中，对归约和 sumReg 取 Log，Sub 得 log-softmax（log(sum)-sub），按 repeat/tailLoop 两段写出，配合 CreateAddrReg 偏移寻址。

（行 448-460）

```cpp
for (uint16_t j = 0; j < repeatTimes; j++) {
    AscendC::Reg::AddrReg offset = AscendC::Reg::CreateAddrReg<float>(i, AlignC, j, vfLen);
    AscendC::Reg::DataCopy(subReg, subAddr, offset);
    AscendC::Reg::Log(logReg, sumReg, pregMain);
    AscendC::Reg::Sub(tempReg, subReg, logReg, pregMain);
    AscendC::Reg::DataCopy(tempAddr, tempReg, offset, pregMain);
}
for (uint16_t k = 0; k < tailLoop; k++) {
    AscendC::Reg::DataCopy(subReg, subAddr + i * AlignC + repeatTimes * vfLen);
    AscendC::Reg::Log(logReg, sumReg, preg);
    AscendC::Reg::Sub(tempReg, subReg, logReg, preg);
    AscendC::Reg::DataCopy(tempAddr + i * AlignC + repeatTimes * vfLen, tempReg, preg);
}
```

**要点**: 1) 无 mask（pregMain/preg）；2) Log(sumReg) 与 Sub 构成 log-softmax 核心；3) repeat 段用 AddrReg 偏移，tailLoop 段用裸指针偏移。

### 实例 10：log::LogCustom

- **来源类型**: `__aicore__`
- **共现 API**: Cast, DataCopy, LoadDist, MaskReg, RegTensor, RegTraitNumOne, StoreDist, UpdateMask
- **Log 调用次数**: 4
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 log 算子本身中，直接对输入 vregInput 取 Log 写到 vregOutput，是 Log API 最直接的逐元素调用，给出 float 与 half（经 Cast）两条路径。

**片段 1** (行 58-68):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_NORM>(
        vregInput, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));

    Reg::Log(vregOutput, vregInput, mask);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_NORM_B32>(
        (__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput, mask);
}
```

**片段 2** (行 75-88):

```cpp
for (uint16_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {
    mask = Reg::UpdateMask<float, Reg::RegTraitNumOne>(count);
    // OpCopyIn
    Reg::DataCopy<T, Reg::LoadDist::DIST_UNPACK_B16>(
        vregInput16, (__ubuf__ T*)(srcAddr + loopIdx * vlSize));
    Reg::Cast<float, T, castTrait0>(vregInput, vregInput16, mask);

    Reg::Log(vregOutput, vregInput, mask);

    Reg::Cast<T, float, castTrait1>(vregOutput16, vregOutput, mask);
    // OpCopyOut
    Reg::DataCopy<T, Reg::StoreDist::DIST_PACK_B32>(
        (__ubuf__ T*)(dstAddr + loopIdx * vlSize), vregOutput16, mask);
}
```

**要点**: 1) 用 UpdateMask<float,RegTraitNumOne> 生成 mask 控制尾元素；2) half 路径需 Cast 到 float 再 Log 再 Cast 回；3) DataCopy 的 LoadDist/StoreDist 区分 NORM 与 PACK_B32。

### 实例 11：log_softmax_v2::AscendC::Reg

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: CreateMask, Exp, MaskMergeMode, MaskPattern, MaskReg, RegTensor, Sub, UpdateMask
- **Log 调用次数**: 1
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 在 log_softmax_v2 中，对归约和 dReg(=sum) 取 Log，再用 Sub(x-log(sum)) 得到 log-softmax，配合 Exp/ReduceSum/Duplicate 完成 softmax 归约。

（行 354-372）

```cpp
for (uint16_t i = 0; i < loopTimes; ++i) {
    DataCopy(aReg, (__local_mem__ float*)src0 + i * stride);
    DataCopy(bReg, (__local_mem__ float*)src1 + i * stride);
    Exp(aReg, aReg, pFull);
    Exp(bReg, bReg, pMask);
    Add<float, AscendC::Reg::MaskMergeMode::ZEROING>(cReg, aReg, bReg, pMask);
    Copy<float, AscendC::Reg::MaskMergeMode::MERGING>(aReg, cReg, pMask);
    ReduceSum(bReg, aReg, pFull);
    Duplicate(dReg, bReg, pFull);
    Log(dReg, dReg, pFull);
    uint32_t sreg0 = static_cast<uint32_t>(oriR);
    for (uint16_t j = 0; j < rLoopCount; ++j) {
        maskOri = AscendC::Reg::UpdateMask<float>(sreg0);
        uint32_t addrPtr = j * VL_FP32 + i * oriRAligned;
        DataCopy(eReg, ((__local_mem__ float*)oriSrc + addrPtr));
        Sub(eReg, eReg, dReg, maskOri);
        StoreTensorForDtypeTOut(dst, eReg, maskOri, addrPtr);
    }
}
```

**要点**: 1) 无 mask（pFull/pMask predicate）；2) 先 Exp→Add(ZEROING/MERGING)→ReduceSum→Duplicate 再 Log(sum)；3) 内层按 rLoopCount 用 UpdateMask 处理 oriR 尾部。

### 实例 12：cross_entropy_loss::AscendC::DataCopyPad

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: Cast, CreateAddrReg, CreateMask, DataCopy, LoadDist, Mul, Sub
- **Log 调用次数**: 2
- **参数模式**: `T0_A3_M1_TYPEnone_MASKmask`（实参 3 个，含 mask/mode: mask）
- **语义**: 在 cross_entropy_loss ar_big_c 路径中，对 xSum 取 Log(logReg=Log(sum))，再用 Sub(src-max-log(sum)) 实现 log-softmax，配合 Cast 处理 half/float，按 repeat 与 tail 两段处理。

（行 1044-1093）

```cpp
__VEC_SCOPE__
{
    RegTensor<float> maxReg, sumReg, logReg, srcRegFp32, subMaxReg, dstReg, weightReg;
    RegTensor<T1> srcReg, dstRegB16;
    MaskReg maskAll = Reg::CreateMask<float, MaskPattern::ALL>();
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_BRC_B32>(maxReg, xMaxPtr);
    AscendC::Reg::DataCopy<float, AscendC::Reg::LoadDist::DIST_BRC_B32>(sumReg, xSumPtr);
    AscendC::Reg::Log(logReg, sumReg, maskAll);
    MaskReg pMask = UpdateMask<float>(sreg);
    for (uint16_t j = 0; j < repeatTimes; ++j) {
        AddrReg srcOffsetJ = AscendC::Reg::CreateAddrReg<T1>(j, vfLenB32);
        AddrReg srcOffsety = AscendC::Reg::CreateAddrReg<float>(j, vfLenB32);
        if constexpr (sizeof(T1) == sizeof(half)) {
            AscendC::Reg::DataCopy<T1, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(srcReg, srcUbAddr,
                                                                                          srcOffsetJ);
            AscendC::Reg::Cast<float, T1, castB16ToB32>(srcRegFp32, srcReg, maskAll);
        } else {
            AscendC::Reg::DataCopy(srcRegFp32, srcUbAddrB32, srcOffsety);
        }
        AscendC::Reg::Sub(subMaxReg, srcRegFp32, maxReg, maskAll);
        AscendC::Reg::Sub(dstReg, subMaxReg, logReg, maskAll);
        if constexpr (isWeight == 1) {
            AscendC::Reg::DataCopy(weightReg, weightUbAddr, srcOffsety);
            AscendC::Reg::Mul(weightReg, dstReg, weightReg, maskAll);
            AscendC::Reg::DataCopy(tmpUbAddr, weightReg, srcOffsety, maskAll);
        } else {
            AscendC::Reg::DataCopy(tmpUbAddr, dstReg, srcOffsety, maskAll);
        }

        AscendC::Reg::DataCopy(yAddr, dstReg, srcOffsety, maskAll);
    }
    MaskReg pMask1 = UpdateMask<float>(sreg1);
    if constexpr (sizeof(T1) == sizeof(half)) {
        AscendC::Reg::DataCopy<T1, AscendC::Reg::LoadDist::DIST_UNPACK_B16>(
            srcReg, srcUbAddr + repeatTimes * vfLenB32);
        AscendC::Reg::Cast<float, T1, castB16ToB32>(srcRegFp32, srcReg, pMask);
    } else {
        AscendC::Reg::DataCopy(srcRegFp32, srcUbAddrB32 + repeatTimes * vfLenB32);
    }
    AscendC::Reg::Sub(subMaxReg, srcRegFp32, maxReg, pMask);
    AscendC::Reg::Sub(dstReg, subMaxReg, logReg, pMask);
    if constexpr (isWeight == 1) {
        AscendC::Reg::DataCopy(weightReg, weightUbAddr + repeatTimes * vfLenB32);
        AscendC::Reg::Mul(weightReg, dstReg, weightReg, pMask);
        AscendC::Reg::DataCopy(tmpUbAddr + repeatTimes * vfLenB32, weightReg, pMask1);
    } else {
        AscendC::Reg::DataCopy(tmpUbAddr + repeatTimes * vfLenB32, dstReg, pMask1);
    }
    AscendC::Reg::DataCopy(yAddr + repeatTimes * vfLenB32, dstReg, pMask);
}
```

**要点**: 1) 用 CreateMask<ALL> 生成 maskAll，tail 用 UpdateMask(sreg)；2) Log 作用于 sumReg（归约和），Sub(dst=subMax-logReg) 为 log-softmax；3) isWeight 编译期分支决定是否 Mul 权重。

### 实例 13：softmax_cross_entropy_with_logits::AscendC::ReduceSum

- **来源类型**: `__VEC_SCOPE__`
- **共现 API**: AddrReg, Copy, CreateAddrReg, DataCopy, MaskReg, RegTensor, UpdateMask
- **Log 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 在 softmax 交叉熵 split_r 路径中，对 srcReg0 取 Log 写入 logReg0，同时 Copy 出 sumReg0，按 repeat 用 CreateAddrReg 偏移寻址，将 log/sum 分别写出供后续重计算。

（行 721-729）

```cpp
for (uint16_t j = 0; j < repeatTimes1; j++) {
    preg = AscendC::Reg::UpdateMask<float>(nSize1);
    AscendC::Reg::AddrReg srcOffset = AscendC::Reg::CreateAddrReg<float>(j, vfLen);
    AscendC::Reg::DataCopy(srcReg0, cacheUbAddr, srcOffset);
    AscendC::Reg::Log(logReg0, srcReg0, preg);
    AscendC::Reg::Copy(sumReg0, srcReg0, preg);
    AscendC::Reg::DataCopy(logUbAddr, logReg0, srcOffset, preg);
    AscendC::Reg::DataCopy(sumUbAddr, sumReg0, srcOffset, preg);
}
```

**要点**: 1) 无 mask（preg predicate，UpdateMask(nSize1)）；2) Log 与 Copy 同源 srcReg0，分离 log 与 sum 两路；3) 配合 AddrReg/CreateAddrReg 按 j 偏移。

### 实例 14：binary_cross_entropy::CalcYLogX

- **来源类型**: `__aicore__`
- **共现 API**: Maxs, Mul, RegTensor
- **Log 调用次数**: 2
- **参数模式**: `T0_A3_M0_TYPEnone`（实参 3 个）
- **语义**: 在 binary_cross_entropy 的 y*log(x) 子函数中，对 regX 取 Log 后用 Maxs 裁剪到 -100 下限避免 log(0)→-inf，再 Mul(regY) 得到 y*log(x)。

（行 39-45）

```cpp
{
    Reg::RegTensor<U> regLogX;
    Reg::RegTensor<U> regClipLogX;
    Reg::Log(regLogX, regX, pregUp);
    Reg::Maxs(regClipLogX, regLogX, (U)-100.0, pregUp);
    Reg::Mul(regYLogX, regClipLogX, regY, pregUp);
}
```

**要点**: 1) 无 mask（pregUp predicate）；2) Log 后立即 Maxs(regLogX, -100) 做数值裁剪，防止 log(0) 爆 inf；3) 共现 API 极简（仅 Maxs/Mul），是 Log 配合裁剪的典型安全用法。

### 实例 15：log_softmax_v2::CalcOutput

- **来源类型**: `__aicore__`
- **共现 API**: Sub
- **Log 调用次数**: 1
- **参数模式**: `T0_A3_M1_TYPEnone_MASKMask`（实参 3 个，含 mask/mode: Mask）
- **语义**: 在 log_softmax_v2 ara 重计算路径的 CalcOutput 中，对归约和 sumReg 取 Log，再用 Sub(x-max-sum_log) 得到 log-softmax，按 loopA0Num 与 curTileRLenVl 双层循环，pregMask 控制尾元素。

（行 356-377）

```cpp
for (uint16_t k = 0; k < loopA0Num; k++) {
    pregMask = UpdateMask<float>(sreg);
    DataCopy<float, LoadDist::DIST_NORM>(sumReg, (__local_mem__ float*)xSumLocal + k * VL_FP32);
    DataCopy<float, LoadDist::DIST_NORM>(maxReg, (__local_mem__ float*)xMaxLocal + k * VL_FP32);
    Log(sumReg, sumReg, pregMask);
    for (uint16_t i = 0; i < curTileRLenVl; i++) {
        uint32_t xOffset = i * tileA0Len + k * VL_FP32;
        LoadTensorForDtypeT1(xLocal, xReg, pregMask, xOffset);

        Sub(xReg, xReg, maxReg, pregMask);
        Sub(yReg, xReg, sumReg, pregMask);

        // copy out
        if constexpr (IsSameType<T2, float>::value) {
            DataCopy(((__local_mem__ float*)yLocal) + xOffset, yReg, pregMask);
        } else { // fp16、bf16
            RegTensor<T2> xFp16;
            Cast<T2, float, castTraitFp32ToFp16>(xFp16, yReg, pregMask);
            DataCopy<T2, StoreDist::DIST_PACK_B32>(((__local_mem__ T2*)yLocal) + xOffset, xFp16, pregMask);
        }
    }
}
```

**要点**: 1) 用 UpdateMask<float>(sreg) 生成 pregMask（mask token 为 Mask）；2) Log(sumReg) 为归约和对数，Sub(xReg-maxReg-sumReg) 减去 max 提升数值稳定性；3) fp16/bf16 经 Cast 回写，区分 IsSameType 分支。

### Log 使用模式归纳

| 算子 | 组合 API | 使用模式 | 来源类型 |
|---|---|---|---|
| cdist | Abs, Add, CreateMask, Duplicate, Exp | 显式模板 `<float, &modelog>` + mask 控制的 lp 距离幂运算 | __VEC_SCOPE__ |
| log_sigmoid | Abs, Adds, CompareScalar, DataCopy, Div | mask 控制的 log(1+exp(-\|x\|)) 数值稳定实现 | __aicore__ |
| softmax_cross_entropy_with_logits | AddrReg, Cast, CreateAddrReg, CreateMask, DataCopy | 无 mask 全量 predicate，Log(sum)-sub 求 log-softmax | __VEC_SCOPE__ |
| log1p | Adds, Cast, CompareScalar, DataCopy, Div | mask 控制 + Adds/Div/Select 边界修正的 log(1+x) 高精度实现 | __aicore__ |
| sigmoid_cross_entropy_with_logits_v2 | Abs, Adds, DataCopy, Duplicate, Exp | 无 mask predicate，Log(1+exp(-\|x\|)) 拼 BCE-with-logits | __aicore__ |
| sigmoid_cross_entropy_with_logits | Abs, Add, DataCopy, Duplicate, Exp | mask 控制，1+exp(-\|x\|) 的 Log 求 log-sigmoid 拼 BCE | __aicore__ |
| power | Abs, Compares, DataCopy, Duplicate, Exp | mask 控制，exp(power\*log(\|base\|)) + 负底数/零底数分支选择 | __VEC_SCOPE__ |
| sparse_softmax_cross_entropy_with_logits | AddrReg, CreateAddrReg, CreateMask, DataCopy, Div | 无 mask predicate，Log(sum)-sub 求 log-softmax + AddrReg 偏移寻址 | __VEC_SCOPE__ |
| cross_entropy_loss | AddrReg, CreateAddrReg, CreateMask, DataCopy | 无 mask predicate，Log(sum)-sub 求 log-softmax + repeat/tail 两段寻址 | __VEC_SCOPE__ |
| log | Cast, DataCopy, LoadDist, MaskReg | mask 控制的逐元素 Log，half 经 Cast 中转 float | __aicore__ |
| log_softmax_v2 | CreateMask, Exp, MaskMergeMode, MaskPattern | 无 mask predicate，Exp+ReduceSum 归约后 Log(sum) 再 Sub 得 log-softmax | __VEC_SCOPE__ |
| cross_entropy_loss | Cast, CreateAddrReg, CreateMask, DataCopy, LoadDist | mask(CreateMask+UpdateMask) 控制，Log(sum) 后 Sub(max) 求 log-softmax + 权重分支 | __VEC_SCOPE__ |
| softmax_cross_entropy_with_logits | AddrReg, Copy, CreateAddrReg, DataCopy | 无 mask predicate，Log+Copy 分离 log/sum 两路 + AddrReg 偏移 | __VEC_SCOPE__ |
| binary_cross_entropy | Maxs, Mul, RegTensor | 无 mask predicate，Log 后 Maxs(-100) 裁剪防 inf 再 Mul | __aicore__ |
| log_softmax_v2 | Sub | pregMask 控制，Log(sum) 后 Sub(x-max-sum) 求 log-softmax + 多精度回写 | __aicore__ |
