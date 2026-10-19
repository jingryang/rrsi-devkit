# SetPadValue(ISASI)

**页面ID:** atlasascendc_api_07_0266  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0266.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

设置DataCopyPad需要填充的数值。支持的通路如下：

- GM->VECIN/GM->VECOUT

#### 函数原型

```
template <typename T, TPosition pos = TPosition::MAX>
__aicore__ inline void SetPadValue(T paddingValue)
```

#### 参数说明

**表1 **模板参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| T | 输入 | 填充值的数据类型，与DataCopyPad接口搬运的数据类型一致。 |
| pos | 输入 | 用于指定DataCopyPad接口搬运过程中从GM搬运数据到哪一个目的地址，目的地址通过逻辑位置来表达。默认值为TPosition::MAX，等效于TPosition::VECIN或TPosition::VECOUT。 支持的取值为： - TPosition::VECIN、TPosition::VECOUT、TPosition::MAX |

**表2 **参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| paddingValue | 输入 | DataCopyPad接口填充的数值，数据与DataCopyPad接口搬运的数据类型一致。 |

#### 约束说明

无

#### 调用示例

```
uint32_t m_n1 = 32;
uint32_t m_n2 = 31;
uint32_t m_n2Align = n2 % 32 == 0 ? n2 : (n2 / 32 + 1) * 32;

AscendC::LocalTensor<float> srcLocal = m_queInSrc.AllocTensor<float>();
AscendC::DataCopyExtParams dataCopyExtParams;
AscendC::DataCopyPadExtParams<float> padParams;

dataCopyExtParams.blockCount = m_n1; // Block个数，拷贝的的次数
dataCopyExtParams.blockLen = m_n2 * sizeof(float); // 一次拷贝多少个32B
dataCopyExtParams.srcStride = 0;
dataCopyExtParams.dstStride = 0;

padParams.isPad = true;
padParams.leftPadding = 0;
padParams.rightPadding = 1;

AscendC::SetPadValue((float)37); // 设置Pad的值为37
AscendC::DataCopyPad(srcLocal, m_srcGlobal, dataCopyExtParams, padParams);
```

```
输入数据（srcGm, shape = [32, 31]）：[[1, 1, 1, ..., 1], [1, 1, 1, ..., 1], ... , [1, 1, 1, ..., 1]]
输出数据（dstGm, shape = [32, 32]）：[[1, 1, 1, ..., 1, 37], [1, 1, 1, ..., 1, 37], ... , [1, 1, 1, ..., 1, 37]]
```

```
// 对于不支持使用立即数进行赋值和初始化的数据类型，如下是一个输入类型bfloat16_t的示例：
AscendC::SetPadValue(m_srcGlobal.GetValue(0));
AscendC::DataCopyPad(srcLocal, m_srcGlobal, dataCopyExtParams, padParams);

输入数据（srcGm, shape = [32, 31]）：[[1, 2, 3, ..., 31], [1, 2, 3, ..., 31], ... , [1, 2, 3, ..., 31]]
输出数据（dstGm, shape = [32, 32]）：[[1, 2, 3, ..., 31, 1], [1, 2, 3, ..., 31, 1], ... , [1, 2, 3, ..., 31, 1]]
```
