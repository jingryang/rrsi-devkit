# LeakyRelu

**页面ID:** atlasascendc_api_07_0389  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0389.html

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

源操作数srcReg大于0的情况下直接将srcReg写入目的操作数dstReg， 否则将srcReg*scalarValue的结果写入dstReg。计算公式如下：

![](images/atlasascendc_api_07_0389_img_001.png)

#### 函数原型

```
template <typename T = DefaultType, typename U, MaskMergeMode mode = MaskMergeMode::ZEROING, typename S>
__simd_callee__ inline void LeakyRelu(S& dstReg, S& srcReg, U scalarValue, MaskReg& mask)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 目的操作数和源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：half/float |
| U | 标量源操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：half/float |
| mode | - 选择MERGING模式或ZEROING模式。  - ZEROING，mask未选中/未被映射的元素在dstReg中置零。  - MERGING，暂不支持。 |
| S | 目的操作数的RegTensor类型，例如RegTensor<half>，由编译器自动推导，用户不需要填写。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstReg | 输出 | 目的操作数。 类型为RegTensor。 |
| srcReg | 输入 | 源操作数。 类型为RegTensor。 数据类型需要与目的操作数保持一致。 |
| scalarValue | 输入 | 源操作数。 类型为标量，数据类型需要与目的操作数保持一致。 |
| mask | 输入 | 源操作数元素操作的有效指示，详细说明请参考MaskReg。 |

#### 约束说明

无

#### 调用示例

```
template<typename T>
__simd_vf__ inline void LeakyRelu(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, T scalarValue, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::RegTensor<T> dstReg;
    AscendC::Reg::MaskReg mask;    
    for (uint16_t i = 0; i < repeatTimes; i++) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::LeakyRelu(dstReg, srcReg, scalarValue, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 LeakyRelu 实例

**扫描范围**: ops-math、ops-nn 算子源码仓，仅 arch35 / `_apt` 路径，已排除 Cube 相关算子（路径含 matmul/conv/cube 或内容含 Mmad/MatMul/Cube/mmad）。

**共 0 处使用**：在上述扫描范围内未发现 LeakyRelu 的真实调用实例。本 API 仅依据官方文档（签名 / 参数 / 官方调用示例）进行 QA 生成，不涉及 arch35 真实场景题。

