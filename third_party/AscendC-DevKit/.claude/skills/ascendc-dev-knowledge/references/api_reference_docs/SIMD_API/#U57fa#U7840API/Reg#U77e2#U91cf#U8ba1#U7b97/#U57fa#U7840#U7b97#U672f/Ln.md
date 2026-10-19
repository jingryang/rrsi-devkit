# Ln

**页面ID:** atlasascendc_api_07_0348  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0348.html

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

根据mask对输入数据src进行求自然对数操作，将结果写入dst。计算公式如下：

![](images/atlasascendc_api_07_0348_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, auto mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Ln(U& dstReg, U& srcReg, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 |
| mode | 可配置为MaskMergeMode的枚举或LnSpecificMode的结构体指针。- MaskMergeMode，选择MERGING模式或ZEROING模式。  - ZEROING，mask未筛选的元素在dstReg中置零。  - MERGING，暂不支持。 - LnSpecificMode，定义如下：``` enum class LnAlgo {     INTRINSIC = 0,     PRECISION_1ULP_FTZ_TRUE,     PRECISION_1ULP_FTZ_FALSE, }; struct LnSpecificMode{     MaskMergeMode mrgMode = MaskMergeMode::ZEROING,     LnAlgo algo = LnAlgo::INTRINSIC; }; ```   - mrgMode：选择MERGING模式或ZEROING模式。  - algo：用于配置Subnormal模式。    - LnAlgo::INTRINSIC、LnAlgo::PRECISION_1ULP_FTZ_TRUE，使用单指令计算得出结果，所有Subnormal被近似为0。    - LnAlgo::PRECISION_1ULP_FTZ_FALSE，支持Subnormal数据计算。 |
| U | 源操作数和目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 源操作数的数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

- src输入为-0时，输出-inf

#### 调用示例

```
template<typename T>
__simd_vf__ inline void LnVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, 
 uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    // Subnormal模式
    // static constexpr AscendC::Reg::LnSpecificMode mode = {MaskMergeMode::ZEROING, LnAlgo::PRECISION_1ULP_FTZ_FALSE};
    for (uint16_t i = 0; i < repeatTimes; i++) {     
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Ln(dstReg, srcReg, mask);
        // Subnormal模式
        // AscendC::Reg::Ln<T, &mode>(dstReg, srcReg, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```
