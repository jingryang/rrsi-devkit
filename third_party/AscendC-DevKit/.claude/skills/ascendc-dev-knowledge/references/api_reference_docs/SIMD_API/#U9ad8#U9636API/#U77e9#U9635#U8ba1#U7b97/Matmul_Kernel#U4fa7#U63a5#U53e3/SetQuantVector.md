# SetQuantVector

**页面ID:** atlasascendc_api_07_0650  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0650.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品            AI Core | √ |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

本接口提供对输出矩阵采用向量进行量化或反量化的功能，即对于输入shape为[1, N]的参数向量，N值为Matmul矩阵计算时M/N/K中的N值，对输出矩阵的每一列都采用该向量中对应列的系数进行量化或反量化。量化、反量化的详细内容请参考量化场景。

Matmul反量化场景：在Matmul计算时，左、右矩阵的输入为int8_t或int4b_t类型，输出为half类型；或者左、右矩阵的输入为int8_t类型，输出为int8_t类型。该场景下，输出C矩阵的数据从CO1搬出到Global Memory时，会执行反量化操作，将最终结果反量化为对应的half或int8_t类型。

Matmul量化场景：在Matmul计算时，左、右矩阵的输入为half或bfloat16_t类型，输出为int8_t类型。该场景下，输出C矩阵的数据从CO1搬出到Global Memory时，会执行量化操作，将最终结果量化为int8_t类型。

#### 函数原型

- 量化参数的存储位置为GM

```
__aicore__ inline void SetQuantVector(const GlobalTensor<uint64_t>& quantTensor)
```

- 量化参数的存储位置为L1 Buffer

```
__aicore__ inline void SetQuantVector(const LocalTensor<uint64_t>& quantTensor)
```

  - 
          Atlas 200I/500 A2 推理产品
         暂不支持量化参数的存储位置为L1 Buffer。
  - 
          Atlas 推理系列产品
         AI Core暂不支持量化参数的存储位置为L1 Buffer。

#### 参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| quantTensor | 输入 | 量化或反量化运算时的参数向量。参数向量的存储位置为GM或L1 Buffer。 |

将float数据类型的量化计算参数scale、offset转换为uint64类型的入参的计算公式如下：

1. quantTensor为64位格式，初始为0。
2. scale按bit位取高19位截断，存储于quantTensor的bit位32位处，并将46位修改为1。

*quantTensor = quantTensor ∣ (scale & 0xFFFFE000) ∣ (1 ≪ 46)*

3. 根据offset取值进行后续计算：

  - 若offset不存在，不再进行后续计算。
  - 若offset存在：

    1. 将offset值处理为int，范围为[-256, 255]。

*o**f**f**s**e**t **= **M**a**x**(**M**i**n**(**I**N**T**(**R**o**u**n**d**(**o**f**f**s**e**t**)), 255), −256)*

    2. 再将offset按bit位保留9位并存储于quantTensor的37到45位。

*quantTensor **= (quantTensor & 0**x**4000**F**F**F**F**F**F**F**F**) ∣ ((**o**f**f**s**e**t** & 0**x**1**F**F**) ≪ 37)*

#### 约束说明

需与SetDequantType保持一致。

本接口必须在Iterate或者IterateAll前调用。

#### 调用示例

完整样例请参考[matmul_quant样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/00_matrix/matmul_quant)。

```
REGIST_MATMUL_OBJ(&pipe, GetSysWorkSpacePtr(), mm, &tiling);

// quantTensor：量化或反量化运算时的Tensor，支持的存储位置为GM和L1
mm.SetQuantVector(quantTensor);

mm.SetTensorA(gm_a);
mm.SetTensorB(gm_b);
if (tiling.isBias) {
    matmulObj.SetBias(biasGlobal);
}
mm.IterateAll(gm_c);
mm.End();
```
