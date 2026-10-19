# MoveMask

**页面ID:** atlasascendc_api_07_0340  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0340.html

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

从特殊寄存器SPR{MASK1, MASK0}读取mask值并根据数据类型格式写入函数返回值MaskReg。

#### 函数原型

```
template <typename T> 
__simd_callee__ inline MaskReg MoveMask()
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 数据类型，决定mask值写入格式： - 对于b16类型，会读取完整的128bit {MASK1, MASK0}数据，并将每bit复制为2bit，写入函数返回值MaskReg。- 对于b32类型，会读取64bit MASK0数据，并将每bit复制为4bit，写入函数返回值MaskReg。 |

#### 返回值说明

特殊寄存器中读取的MaskReg。

#### 约束说明

无

#### 调用示例

```
template <typename T>
__simd_vf__ inline void MoveMaskVF(__ubuf__ T* dstAddr, __ubuf__ T* srcAddr, uint32_t count, uint32_t oneRepeatSize, uint16_t repeatTimes)
{
    AscendC::Reg::RegTensor<T> srcReg;
    AscendC::Reg::MaskReg addMask = AscendC::Reg::MoveMask<T>();
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<T>(count);
        AscendC::Reg::LoadAlign(srcReg, srcAddr + i * oneRepeatSize);
        AscendC::Reg::Adds(srcReg, srcReg, 0, addMask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, srcReg, mask);
    }
}
```


---
## 从 Ascend 950PR / arch35 算子源码提取的 MoveMask 实例

扫描范围: ops-math、ops-nn 仓库 arch35 / `_apt` 路径（已排除 Cube 相关算子）；共 0 处使用 MoveMask 的实例。

