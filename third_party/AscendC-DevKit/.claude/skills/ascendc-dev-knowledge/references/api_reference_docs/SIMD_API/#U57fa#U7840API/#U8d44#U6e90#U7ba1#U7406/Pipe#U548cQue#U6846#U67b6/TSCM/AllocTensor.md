# AllocTensor

**页面ID:** atlasascendc_api_07_00040  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_00040.html

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

从TSCM中分配tensor，tensor所占大小为InitBuffer时设置的每块内存长度。注意，分配的tensor内容并非全0，可能会是随机值。

#### 函数原型

```
template <typename T>
__aicore__ inline LocalTensor<T> AllocTensor()
```

#### 参数说明

无

#### 约束说明

无

#### 返回值说明

LocalTensor对象。

#### 调用示例

```
AscendC::TPipe pipe;
AscendC::TSCM<AscendC::TPosition::VECIN, 1> tscm;
int num = 4;
int len = 1024;
pipe.InitBuffer(tscm, num, len); // InitBuffer分配内存块数为4，每块大小为1024Bytes
AscendC::LocalTensor<half> tensor1 = que.AllocTensor<half>(); // AllocTensor分配Tensor长度为1024Bytes
que.EnQue(tensor1);
tensor1 = que.DeQue<half>();
que.FreeTensor(tensor1);
```
