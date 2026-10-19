# Div

**页面ID:** atlasascendc_api_07_0359  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0359.html

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

根据mask对输入数据srcReg0、srcReg1执行按元素相除操作，将结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0359_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, auto mode = MaskMergeMode::ZEROING, typename U>
__simd_callee__ inline void Div(U& dstReg, U& srcReg0, U& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：uint16_t、int16_t、half、uint32_t、int32_t、float、complex32、int64_t、uint64_t、complex64。 |
| mode | 可配置为MaskMergeMode的枚举或DivSpecificMode的结构体指针。 - 配置MaskMergeMode，选择MERGING模式或ZEROING模式。  - ZEROING，mask未筛选的元素在dstReg中置零。  - MERGING, 暂不支持。 - 配置DivSpecificMode``` enum class DivAlgo {     INTRINSIC = 0,     DIFF_COMPENSATION,     PRECISION_1ULP_FTZ_TRUE,     PRECISION_0ULP_FTZ_TRUE,     PRECISION_0ULP_FTZ_FALSE,     PRECISION_1ULP_FTZ_FALSE }; struct DivSpecificMode {     MaskMergeMode mrgMode = MaskMergeMode::ZEROING,     bool precisionMode = false;     DivAlgo algo = DivAlgo::INTRINSIC; }; ``` 当precisionMode为true时，使能更高精度的Div计算，使用差值补偿算法得出结果，最大精度误差为0 ulp。目前只针对float数据类型生效。  - algo：用于配置Subnormal模式。  - DivAlgo::INTRINSIC、DivAlgo::PRECISION_1ULP_FTZ_TRUE，使用单指令计算得出结果，最大精度误差为1 ulp。  - DivAlgo::DIFF_COMPENSATION、DivAlgo::PRECISION_0ULP_FTZ_TRUE，使用差值补偿算法得出结果，最大精度误差为0 ulp。目前，该算法支持float、complex64数据类型。  - DivAlgo::PRECISION_0ULP_FTZ_FALSE，支持Subnormal数据计算，使用差值补偿算法得出结果，最大精度误差为0 ulp。目前，该算法支持float数据类型。  - DivAlgo::PRECISION_1ULP_FTZ_FALSE，支持Subnormal数据计算，使用单指令计算得出结果，最大精度误差为1 ulp。目前，该算法支持half、float数据类型。 |
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
__simd_vf__ inline void DivVF(__ubuf__ T* dstAddr, __ubuf__ T* src0Addr, __ubuf__ T* src1Addr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg0;
    AscendC::Reg::RegTensor<T> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    // 高精度模式
    // static constexpr AscendC::Reg::DivSpecificMode mode = {AscendC::Reg::MaskMergeMode::ZEROING, true};
    // Subnormal模式
    // static constexpr AscendC::Reg::DivSpecificMode mode = {AscendC::Reg::MaskMergeMode::ZEROING, true, DivAlgo::PRECISION_0ULP_FTZ_FALSE};
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Div(dstReg, srcReg0, srcReg1, mask);
        // 高精度模式/Subnormal模式
        // AscendC::Reg::Div<T, &mode>(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```
