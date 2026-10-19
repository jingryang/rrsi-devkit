# asc_vf_call

**页面ID:** atlasascendc_api_07_00267  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00267.html

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

在SIMD编程场景下使用。用于启动SIMD VF（Vector Function）子任务。

> **注意:** 

asc_vf_call启动SIMD VF子任务时，子任务函数不能是类的成员函数，推荐使用普通函数或类静态函数，且入口函数必须使用__simd_vf__修饰宏。

asc_vf_call启动SIMD VF子任务时，传递的参数只支持裸指针，常见基本数据类型。不支持传递结构体，数组等。

#### 函数原型

```
template <auto funcPtr, typename... Args>
__aicore__ inline void asc_vf_call(Args &&...args)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| funcPtr | 用于指定SIMD入口核函数。 |
| Args | 定义可变参数，用于传递实参到SIMD入口核函数。 |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| args | 输入 | 可变参数，用于传递实参到SIMD入口核函数。 |

#### 约束说明

无

#### 调用示例

对Global Memory数据做加法计算。

```
// SIMD函数
__simd_vf__ inline void AddVF(__ubuf__ float* dstAddr, __ubuf__ float* src0Addr, __ubuf__ float* src1Addr, uint32_t count,  uint32_t oneRepeatSize, uint16_t repeatTimes) 
{     
    AscendC::Reg::RegTensor<float> srcReg0;
    AscendC::Reg::RegTensor<float> srcReg0;
    AscendC::Reg::RegTensor<float> dstReg;
    AscendC::Reg::MaskReg mask;
    for (uint16_t i = 0; i < repeatTimes; ++i) {
        mask = AscendC::Reg::UpdateMask<float>(count);
        AscendC::Reg::LoadAlign(srcReg0, src0Addr + i * oneRepeatSize);  
        AscendC::Reg::LoadAlign(srcReg1, src1Addr + i * oneRepeatSize);
        AscendC::Reg::Add(dstReg, srcReg0, srcReg1, mask);
        AscendC::Reg::StoreAlign(dstAddr + i * oneRepeatSize, dstReg , mask);
    }
}

__aicore__ inline void SimdComputeShell()      
{  
     AscendC::LocalTensor<float> dst = outQueueZ.AllocTensor<float>();     
     AscendC::LocalTensor<float> src0 = inQueueX.DeQue<float>();
     AscendC::LocalTensor<float> src1 = inQueueY.DeQue<float>();
     constexpr uint32_t oneRepeatSize = AscendC::GetVecLen()/sizeof(float);
     uint32_t count = 512;
     // 向上取整，计算repeat
     uint16_t repeatTimes = AscendC::CeilDivision(count, oneRepeatSize);
     __ubuf__ float* dstAddr = (__ubuf__ float*)dst.GetPhyAddr();
     __ubuf__ float* src0Addr = (__ubuf__ float*)src0.GetPhyAddr();
     __ubuf__ float* src1Addr = (__ubuf__ float*)src1.GetPhyAddr();
     asc_vf_call<AddVF>(dstAddr, src0Addr, src1Addr, count, oneRepeatSize, repeatTimes);
     outQueueZ.EnQue(dst);
     inQueueX.FreeTensor(src0);
     inQueueY.FreeTensor(src1);
}
```
