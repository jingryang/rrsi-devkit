# Trap

**页面ID:** atlasascendc_api_07_0196  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0196.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

在Kernel侧调用，NPU模式下会中断AI Core的运行，CPU模式下等同于assert。可用于Kernel侧异常场景的调试。

#### 函数原型

```
__aicore__ inline void Trap()
```

#### 参数说明

无

#### 约束说明

无。

#### 调用示例

```
AscendC::LocalTensor<half> src0Local;
AscendC::LocalTensor<half> src1Local;
AscendC::LocalTensor<half> dstLocal;
constexpr int32_t count = 512;    // 参与计算的元素个数
if (src1Local[0] == 0) {    // 如果除数为0，则报异常
    AscendC::Trap();
} else {
    AscendC::Divs(dstLocal, src0Local, src1Local[0], 512);
}
```
