# Sqrt

**页面ID:** atlasascendc_api_07_0345  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0345.html

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

根据mask对输入数据srcReg进行平方根操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0345_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, auto mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Sqrt(U& dstReg, U& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 |
| mode | 可配置为MaskMergeMode的枚举或SqrtSpecificMode的结构体指针。- MaskMergeMode，选择MERGING模式或ZEROING模式。  - ZEROING，mask未筛选的元素在dstReg中置零。  - MERGING，暂不支持。 - SqrtSpecificMode，定义如下：``` enum class SqrtAlgo {     INTRINSIC = 0,     FAST_INVERSE,     PRECISION_1ULP_FTZ_TRUE,     PRECISION_0ULP_FTZ_FALSE,     PRECISION_1ULP_FTZ_FALSE, }; struct SqrtSpecificMode {     MaskMergeMode mrgMode = MaskMergeMode::ZEROING,     bool precisionMode = false;     SqrtAlgo algo = SqrtAlgo::INTRINSIC; }; ```   - mrgMode：选择MERGING模式或ZEROING模式。  - precisionMode：用于配置精度模式。当precisionMode为true时，使能更高精度的Sqrt计算，使用快速求逆算法得出结果。适用于输入值在[0, 85070596800837026223494223584045301760]范围内的计算。在该范围内，算法保证输出的最大精度误差为0 ulp；当输入值大于85070596800837026223494223584045301760时，输出为0。该算法目前只针对float数据类型生效。   - algo：用于配置Subnormal模式。    - SqrtAlgo::INTRINSIC、SqrtAlgo::PRECISION_1ULP_FTZ_TRUE，使用单指令计算得出结果，最大精度误差为1 ulp。    - SqrtAlgo::FAST_INVERSE、SqrtAlgo::PRECISION_0ULP_FTZ_FALSE，使用快速求逆算法得出结果。适用于输入值在[0, 85070596800837026223494223584045301760]范围内的计算。在该范围内，算法保证输出的最大精度误差为0 ulp；当输入值大于85070596800837026223494223584045301760时，输出为0。目前，该算法仅支持float数据类型，并在该模式下支持Subnormal数据计算。    - SqrtAlgo::PRECISION_1ULP_FTZ_FALSE，仅支持half类型的Subnormal数据计算，此时最大精度误差为1 ulp。 |
| U | 源操作数和目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

如果srcReg中的数值为非正数，可能会产生未知结果。

#### 调用示例

```
template<typename T>
__simd_vf__ inline void SqrtVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;   
    // 高精度模式
    // static constexpr AscendC::Reg::SqrtSpecificMode mode = {MaskMergeMode::ZEROING, true};
    // Subnormal模式
    // static constexpr AscendC::Reg::SqrtSpecificMode mode = {MaskMergeMode::ZEROING, true, SqrtAlgo::PRECISION_0ULP_FTZ_FALSE};
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Sqrt(dstReg, srcReg, mask);
        // 高精度模式/Subnormal模式
        // AscendC::Reg::Sqrt<T, &mode>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```
