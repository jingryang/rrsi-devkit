# MulsCast

**页面ID:** atlasascendc_api_07_0388  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0388.html

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

src与scalar相乘再按照CAST_ROUND模式转换成half类型，根据mask将计算结果写入dst。计算公式如下：

![](images/atlasascendc_api_07_0388_img_001.png)

#### 函数原型

```
template <typename T0 = DefaultType, typename T1 = DefaultType, typename T2, RegLayout layout = RegLayout::ZERO, typename T3, typename T4>
__simd_callee__ inline void MulsCast(T3& dstReg, T4& srcReg, T2 scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T0 | 目的操作数数据类型。 Atlas 350 加速卡，支持的数据类型为：half |
| T1 | 源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：float |
| T2 | 标量源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：float |
| layout | RegLayout枚举类型。 本接口只支持RegLayout::ZERO、RegLayout::ONE。 src为half类型时使用，float时不生效，half类型时，RegLayout::ZERO表示从b16 RegTensor偶数位读取half元素转换成float，RegLayout::ONE表示从b16 RegTensor奇数位读取half元素转换成float。 |
| T3 | dstReg的RegTensor类型， 例如RegTensor<float>，由编译器自动推导，用户不需要填写。 |
| T4 | srcReg的RegTensor类型， 例如RegTensor<float>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 |
| scalarValue | 输入 | 源操作数。 类型为标量。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void MulsCastVF(__ubuf__ half* dstAddr, __ubuf__ float* srcAddr, float scalarValue, uint32_t count, uint32_t srcRepeatSize, uint32_t dstRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<float> srcReg0;
    AscendC::Reg::RegTensor<half> dstReg0;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<float>(count);
        AscendC::Reg::LoadAlign(srcReg0, srcAddr + i * srcRepeatSize);
        AscendC::Reg::MulsCast<half, float, float, AscendC::Reg::RegLayout::ZERO>(dstReg0, srcReg0, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * dstRepeatSize, dstReg0, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 MulsCast 实例

**未发现使用实例**。扫描范围: ops-math、ops-nn 仓内 `arch35` / `_apt` 路径（已排除 Cube 相关算子）；共 0 处使用。

