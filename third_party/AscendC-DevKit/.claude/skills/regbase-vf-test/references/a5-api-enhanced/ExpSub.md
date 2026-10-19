# ExpSub

**页面ID:** atlasascendc_api_07_0378  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0378.html

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

srcReg0与srcReg1相减，差值作为e的指数计算， 根据mask将计算结果写入dstReg。

srcReg为float类型时：![](images/atlasascendc_api_07_0378_img_001.png)

srcReg为half类型时：![](images/atlasascendc_api_07_0378_img_002.png)

#### 函数原型

```
template <typename T = DefaultType, typename U = DefaultType, RegLayout layout = RegLayout::ZERO, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S, typename V>
__simd_callee__ inline void ExpSub(S& dstReg, V& srcReg0, V& srcReg1, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：float |
| U | 源操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half/float |
| layout | RegLayout枚举类型： ``` enum class RegLayout {     UNKNOWN = -1,     ZERO,     ONE,     TWO,     THREE }; ``` 本接口只支持RegLayout::ZERO、RegLayout::ONE。src类型为half类型时使用，float时不生效，half类型时，RegLayout::ZERO表示从b16 RegTensor偶数位读取half元素转换成float，RegLayout::ONE表示从b16 RegTensor奇数位读取half元素转换成float。 |
| mode | 选择MERGING模式或ZEROING模式。 - ZEROING，mask未筛选的元素在dst中置零。- MERGING，当前不支持。 |
| S | dstReg RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |
| V | srcReg0/srcReg1 RegTensor类型， 例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg0 | 输入 | 源操作数。 类型为RegTensor。 |
| srcReg1 | 输入 | 源操作数。 类型为RegTensor。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

src为half类型时，Vector计算单元一次计算只处理最多VL/sizeof(float)个half元素，mask只有偶数位有效，参考下图：

![](images/atlasascendc_api_07_0378_img_003.png)

#### 调用示例

```
template<typename T, typename U>
static __simd_vf__ inline void ExpSubVF(__ubuf__ T* dstAddr, __ubuf__ U* src0Addr, __ubuf__ U* src1Addr, uint32_t count, uint32_t srcRepeatSize, uint32_t dstRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<U> srcReg0;
    AscendC::Reg::RegTensor<U> srcReg1;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<U>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * srcRepeatSize);
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * srcRepeatSize);
        AscendC::Reg::ExpSub<T, U, AscendC::Reg::RegLayout::ZERO, AscendC::Reg::MaskMergeMode::ZEROING>(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * dstRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 ExpSub 实例

扫描范围: ops-math、ops-nn（仅 arch35 / `_apt`，已排除 Cube 相关算子）；共 0 处使用 ExpSub 的实例。

