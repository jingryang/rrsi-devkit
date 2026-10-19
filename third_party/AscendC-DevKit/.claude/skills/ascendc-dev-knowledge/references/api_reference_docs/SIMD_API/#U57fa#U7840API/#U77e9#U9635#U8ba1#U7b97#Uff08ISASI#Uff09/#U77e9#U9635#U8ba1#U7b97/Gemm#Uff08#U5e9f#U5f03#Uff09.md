# Gemm（废弃）

**页面ID:** atlasascendc_api_07_0263  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0263.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | x |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | x |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | x |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品AI Core | √ |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | √ |

#### 功能说明

**该接口废弃，并将在后续版本移除，请不要使用该接口。**

根据输入的切分规则，将给定的两个输入张量做矩阵乘，输出至结果张量。将A和B两个输入矩阵乘法在一起，得到一个输出矩阵C。

#### 函数原型

- 功能接口：

```
template <typename T, typename U, typename S>
__aicore__ inline void Gemm(const LocalTensor<T>& dst, const LocalTensor<U>& src0, const LocalTensor<S>& src1, const uint32_t m, const uint32_t k, const uint32_t n, GemmTiling tilling, bool partialsum = true, int32_t initValue = 0)
```

- 切分方案计算接口：

```
template <typename T>
__aicore__ inline GemmTiling GetGemmTiling(uint32_t m, uint32_t k, uint32_t n)
```

#### 参数说明

**表1 **接口参数说明

| **参数名称** | **类型** | **说明** |
| --- | --- | --- |
| dst | 输出 | 目的操作数。 Atlas 训练系列产品，支持的TPosition为：CO1，CO2 Atlas 推理系列产品AI Core，支持的TPosition为：CO1，CO2 |
| src0 | 输入 | 源操作数，TPosition为A1。 |
| src1 | 输入 | 源操作数，TPosition为B1。 |
| m | 输入 | 左矩阵Src0Local有效Height，范围：[1, 4096]。 注意：m可以不是16的倍数。 |
| k | 输入 | 左矩阵Src0Local有效Width、右矩阵Src1Local有效Height。- 当输入张量Src0Local的数据类型为float时，范围：[1, 8192]- 当输入张量Src0Local的数据类型为half时，范围：[1, 16384]- 当输入张量Src0Local的数据类型为int8_t时，范围：[1, 32768]  注意：k可以不是16的倍数。 |
| n | 输入 | 右矩阵Src1Local有效Width，范围：[1, 4096]。 注意：n可以不是16的倍数。 |
| 切分规则，类型为GemmTiling，结构体具体定义为： ``` struct GemmTiling {     const uint32_t blockSize = 16;     LoopMode loopMode = LoopMode::MODE_NM;     uint32_t mNum = 0;     uint32_t nNum = 0;     uint32_t kNum = 0;     uint32_t roundM = 0;     uint32_t roundN = 0;     uint32_t roundK = 0;     uint32_t c0Size = 32;     uint32_t dtypeSize = 1;     uint32_t mBlockNum = 0;     uint32_t nBlockNum = 0;     uint32_t kBlockNum = 0;     uint32_t mIterNum = 0;     uint32_t nIterNum = 0;     uint32_t kIterNum = 0;     uint32_t mTileBlock = 0;     uint32_t nTileBlock = 0;     uint32_t kTileBlock = 0;     uint32_t kTailBlock = 0;     uint32_t mTailBlock = 0;     uint32_t nTailBlock = 0;     bool kHasTail = false;     bool mHasTail = false;     bool nHasTail = false;     bool kHasTailEle = false;     uint32_t kTailEle = 0; }; ```  参数说明请参考表3。 |  |  |
| partialsum | 输入 | 当dst参数所在的TPosition为CO2时，通过该参数控制计算结果是否搬出。- 取值0：搬出计算结果- 取值1：不搬出计算结果，可以进行后续计算 |
| initValue | 输入 | 表示dst是否需要初始化。- 取值0: dst需要初始化，dst初始矩阵保存有之前结果，新计算结果会累加前一次conv2d计算结果。- 取值1: dst不需要初始化，dst初始矩阵中数据无意义，计算结果直接覆盖dst中的数据。 |

**表2 **feature_map、weight和dst的数据类型组合

| src0.dtype | src1.dtype | dst.dtype |
| --- | --- | --- |
| int8_t | int8_t | int32_t |
| half | half | float |
| half | half | half |

**表3 **GemmTiling结构内参数说明

| **参数名称** | **类型** | **说明** |
| --- | --- | --- |
| blockSize | uint32_t | 固定值，恒为16，一个维度内存放的元素个数。 |
| 遍历模式，结构体具体定义为： ``` enum class LoopMode {     MODE_NM = 0,     MODE_MN = 1,     MODE_KM = 2,     MODE_KN = 3 }; ``` |  |  |
| mNum | uint32_t | M轴等效数据长度参数值，范围：[1, 4096]。 |
| nNum | uint32_t | N轴等效数据长度参数值，范围：[1, 4096]。 |
| kNum | uint32_t | K轴等效数据长度参数值。- 当输入张量Src0Local的数据类型为float时，范围：[1, 8192]- 当输入张量Src0Local的数据类型为half时，范围：[1, 16384]- 当输入张量Src0Local的数据类型为int8_t时，范围：[1, 32768] |
| roundM | uint32_t | M轴等效数据长度参数值且以blockSize为倍数向上取整，范围：[1, 4096] |
| roundN | uint32_t | N轴等效数据长度参数值且以blockSize为倍数向上取整，范围：[1, 4096] |
| roundK | uint32_t | K轴等效数据长度参数值且以c0Size为倍数向上取整。- 当输入张量Src0Local的数据类型为float时，范围：[1, 8192]- 当输入张量Src0Local的数据类型为half时，范围：[1, 16384]- 当输入张量Src0Local的数据类型为int8_t时，范围：[1, 32768] |
| c0Size | uint32_t | 一个block的字节长度，范围：[16或者32]。 |
| dtypeSize | uint32_t | 传入的数据类型的字节长度，范围：[1, 2]。 |
| mBlockNum | uint32_t | M轴Block个数，mBlockNum = mNum / blockSize。 |
| nBlockNum | uint32_t | N轴Block个数，nBlockNum = nNum / blockSize。 |
| kBlockNum | uint32_t | K轴Block个数，kBlockNum = kNum / blockSize。 |
| mIterNum | uint32_t | 遍历维度数量，范围：[1, 4096]。 |
| nIterNum | uint32_t | 遍历维度数量，范围：[1, 4096]。 |
| kIterNum | uint32_t | 遍历维度数量，范围：[1, 4096]。 |
| mTileBlock | uint32_t | M轴切分块个数，范围：[1, 4096]。 |
| nTileBlock | uint32_t | N轴切分块个数，范围：[1, 4096]。 |
| kTileBlock | uint32_t | K轴切分块个数，范围：[1, 4096]。 |
| kTailBlock | uint32_t | K轴尾块个数，范围：[1, 4096]。 |
| mTailBlock | uint32_t | M轴尾块个数，范围：[1, 4096]。 |
| nTailBlock | uint32_t | N轴尾块个数，范围：[1, 4096]。 |
| kHasTail | bool | K轴是否存在尾块。 |
| mHasTail | bool | M轴是否存在尾块。 |
| nHasTail | bool | N轴是否存在尾块。 |
| kHasTailEle | bool | 是否存在尾块元素。 |
| kTailEle | uint32_t | K轴尾块元素，范围：[1, 4096]。 |

#### 约束说明

- 参数m，k，n可以不是16对齐，但因硬件原因，操作数dst，Src0Local和Src1Local的shape需满足对齐要求，即m方向，n方向要求向上16对齐，k方向根据操作数数据类型按16或32向上对齐。
