# DataCopyPad(ISASI)

**页面ID:** atlasascendc_api_07_0265  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0265.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | √ |
| Atlas 推理系列产品AI Core | x |
| Atlas 推理系列产品Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

该接口提供数据非对齐搬运的功能，其中从Global Memory搬运数据至Local Memory时，可以根据开发者的需要自行填充数据。

#### 函数原型

- dataCopyParams为DataCopyExtParams类型，相比于DataCopyParams类型，支持的操作数步长等参数取值范围更大

  - 通路：Global Memory->Local Memory

```
template <typename T, PaddingMode mode = PaddingMode::Normal>
__aicore__ inline void DataCopyPad(const LocalTensor<T>& dst, const GlobalTensor<T>& src, const DataCopyExtParams& dataCopyParams, const DataCopyPadExtParams<T>& padParams)
```

```
template <typename T>
__aicore__ inline void DataCopyPad(const LocalTensor<T>& dst, const GlobalTensor<T>& src, const DataCopyExtParams& dataCopyParams, const DataCopyPadExtParams<T>& padParams)
```

  - 通路：Local Memory->Global Memory

```
template <typename T, PaddingMode mode = PaddingMode::Normal>
__aicore__ inline void DataCopyPad(const GlobalTensor<T>& dst, const LocalTensor<T>& src, const DataCopyExtParams& dataCopyParams)
```

```
template <typename T>
__aicore__ inline void DataCopyPad(const GlobalTensor<T>& dst, const LocalTensor<T>& src, const DataCopyExtParams& dataCopyParams)
```

  - 通路：Local Memory->Local Memory，实际搬运过程是VECIN/VECOUT->GM->TSCM

```
template <typename T>
__aicore__ inline void DataCopyPad(const LocalTensor<T>& dst, const LocalTensor<T>& src, const DataCopyExtParams& dataCopyParams, const Nd2NzParams& nd2nzParams)
```

- dataCopyParams为DataCopyParams类型

  - 通路：Global Memory->Local Memory

```
template<typename T, PaddingMode mode = PaddingMode::Normal>
__aicore__ inline void DataCopyPad(const LocalTensor<T>& dst, const GlobalTensor<T>& src, const DataCopyParams& dataCopyParams, const DataCopyPadParams& padParams)
```

```
template<typename T>
__aicore__ inline void DataCopyPad(const LocalTensor<T>& dst, const GlobalTensor<T>& src, const DataCopyParams& dataCopyParams, const DataCopyPadParams& padParams)
```

  - 通路：Local Memory->Global Memory

```
template<typename T, PaddingMode mode = PaddingMode::Normal>
__aicore__ inline void DataCopyPad(const GlobalTensor<T>& dst, const LocalTensor<T>& src,const DataCopyParams& dataCopyParams)
```

```
template<typename T>
__aicore__ inline void DataCopyPad(const GlobalTensor<T>& dst, const LocalTensor<T>& src,const DataCopyParams& dataCopyParams)
```

  - 通路：Local Memory->Local Memory，实际搬运过程是VECIN/VECOUT->GM->TSCM

```
template<typename T>
__aicore__ inline void DataCopyPad(const LocalTensor<T>& dst, const LocalTensor<T>& src, const DataCopyParams& dataCopyParams, const Nd2NzParams& nd2nzParams)
```

不同产品型号对函数原型的支持存在差异，请参考下表中的支持度信息，选择产品型号支持的函数原型进行开发。

**表1 **不同产品型号对函数原型的支持度

| 产品型号 | 支持的数据传输通路 | 是否支持设置数据搬运模式mode（搬运模式包括单次搬运对齐和整块数据搬运对齐） |
| --- | --- | --- |
| Atlas 350 加速卡 | GM->VECIN/VECOUT、GM->A1/B1、GM->TSCM、VECIN/VECOUT->GM、A1/B1->GM、VECIN/VECOUT->TSCM、 GM->VECCALC | 是 |
| Atlas A3 训练系列产品/Atlas A3 推理系列产品 | GM->VECIN/VECOUT、VECIN/VECOUT->GM、VECIN/VECOUT->TSCM | 否 |
| Atlas A2 训练系列产品/Atlas A2 推理系列产品 | GM->VECIN/VECOUT、VECIN/VECOUT->GM、VECIN/VECOUT->TSCM | 否 |
| Atlas 200I/500 A2 推理产品 | GM->VECIN/VECOUT、VECIN/VECOUT->GM | 否 |

#### 参数说明

**表2 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数以及paddingValue（待填充数据值）的数据类型。 Atlas 350 加速卡，支持的数据类型为：bool/int8_t/uint8_t/int16_t/uint16_t/half/bfloat16_t/int32_t/uint32_t/float/complex32/int64_t/uint64_t/double/complex64 Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持的数据类型为：half/bfloat16_t/int16_t/uint16_t/float/int32_t/uint32_t/int8_t/uint8_t/int64_t/uint64_t/double Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持的数据类型为：half/bfloat16_t/int16_t/uint16_t/float/int32_t/uint32_t/int8_t/uint8_t/int64_t/uint64_t/double Atlas 200I/500 A2 推理产品，支持的数据类型为：int8_t/uint8_t/half/bfloat16_t/int16_t/uint16_t/float/int32_t/uint32_t |
| 配置数据搬运模式。PaddingMode类型，定义如下： ``` enum class PaddingMode : uint8_t {     Normal = 0,  // 默认模式，与原有数据搬运格式保持一致，每次数据搬运都会补齐至32字节对齐     Compact,     // 紧凑模式，允许单次搬运不对齐，统一在整块数据末尾补齐至32字节对齐 }; ``` |  |

**表3 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dst | 输出 | 目的操作数，类型为LocalTensor或GlobalTensor。 LocalTensor的起始地址需要保证32字节对齐。 GlobalTensor的起始地址无地址对齐约束。 |
| src | 输入 | 源操作数，类型为LocalTensor或GlobalTensor。 LocalTensor的起始地址需要保证32字节对齐。 GlobalTensor的起始地址无地址对齐约束。 |
| dataCopyParams | 输入 | 搬运参数。 - DataCopyExtParams类型，具体参数说明请参考表4。- DataCopyParams类型，具体参数说明请参考表5。 |
| padParams | 输入 | 从Global Memory搬运数据至Local Memory时，可以根据开发者需要，在搬运数据左边或右边填充数据。padParams是用于控制数据填充过程的参数。 - DataCopyPadExtParams类型，具体参数请参考表6。****- DataCopyPadParams类型，具体参数请参考表7。 |
| nd2nzParams | 输入 | 从VECIN/VECOUT->TSCM进行数据搬运时，可以进行ND到NZ的数据格式转换。nd2nzParams是用于控制数据格式转换的参数，Nd2NzParams类型，具体参数请参考表3。 **注意：Nd2NzParams的ndNum仅支持设置为1**。 |

下文表格中列出的结构体参数定义请参考${INSTALL_DIR}/include/ascendc/basic_api/interface/kernel_struct_data_copy.h，${INSTALL_DIR}请替换为CANN软件安装后文件存储路径。

**表4 **DataCopyExtParams结构体参数定义

| 参数名称 | 含义 |
| --- | --- |
| blockCount | 指定该指令包含的连续传输数据块个数，数据类型为uint16_t，取值范围：blockCount∈[1, 4095]。 |
| blockLen | 指定该指令每个连续传输数据块长度，**该指令支持非对齐搬运**，**每个连续传输数据块长度单位为字节**。数据类型为uint32_t，取值范围：blockLen∈[1, 2097151]。 |
| srcStride | 源操作数，相邻连续数据块的间隔（前面一个数据块的尾与后面数据块的头的间隔）。 **如果源操作数的逻辑位置为VECIN/VECOUT，则单位为dataBlock(32字节)。如果源操作数的逻辑位置为GM，则单位为字节**。 数据类型为uint32_t，srcStride不要超出该数据类型的取值范围。 特别地，针对如下型号： Atlas 350 加速卡 数据类型为int64_t，如果源操作数的逻辑位置为VECIN/VECOUT，取值范围为[0, 65535]；如果源操作数的逻辑位置为GM，取值范围为[-blockLen, 2^40-1]。 |
| dstStride | 目的操作数，相邻连续数据块间的间隔（前面一个数据块的尾与后面数据块的头的间隔）。 **如果目的操作数的逻辑位置为VECIN/VECOUT，则单位为dataBlock(32字节)，如果目的操作数的逻辑位置为GM，则单位为字节**。 数据类型为uint32_t，dstStride不要超出该数据类型的取值范围。 特别地，针对如下型号： Atlas 350 加速卡 数据类型为int64_t，如果目的操作数的逻辑位置为VECIN/VECOUT，取值范围为[0, 65535]；如果目的操作数的逻辑位置为GM，取值范围为[0, 2^40-1]。 |
| rsv | 保留字段。 |

**表5 **DataCopyParams结构体参数定义

| 参数名称 | 含义 |
| --- | --- |
| blockCount | 指定该指令包含的连续传输数据块个数，数据类型为uint16_t，取值范围：blockCount∈[1, 4095]。 |
| blockLen | 指定该指令每个连续传输数据块长度，**该指令支持非对齐搬运**，**每个连续传输数据块长度单位为字节**。数据类型为uint16_t，blockLen不要超出该数据类型的取值范围。 |
| srcStride | 源操作数，相邻连续数据块的间隔（前面一个数据块的尾与后面数据块的头的间隔），**如果源操作数的逻辑位置为VECIN/VECOUT，则单位为dataBlock(32字节)。如果源操作数的逻辑位置为GM，则单位为字节**。数据类型为uint16_t，srcStride不要超出该数据类型的取值范围。 |
| dstStride | 目的操作数，相邻连续数据块间的间隔（前面一个数据块的尾与后面数据块的头的间隔），**如果目的操作数的逻辑位置为VECIN/VECOUT，则单位为dataBlock(32字节)，如果目的操作数的逻辑位置为GM，则单位为****字节**。数据类型为uint16_t，dstStride不要超出该数据类型的取值范围。 |

**表6 **DataCopyPadExtParams<T>结构体参数定义

| 参数名称 | 含义 |
| --- | --- |
| isPad | 是否需要填充用户自定义的数据，取值范围：true，false。 true：填充padding value。 false：表示用户不需要指定填充值，会默认填充随机值。 |
| leftPadding | 连续搬运数据块左侧需要补充的数据范围，单位为元素个数。 **leftPadding、rightPadding所占的字节数均不能超过32字节。** |
| rightPadding | 连续搬运数据块右侧需要补充的数据范围，单位为元素个数。 **leftPadding、rightPadding所占的字节数均不能超过32字节。** |
| paddingValue | 左右两侧需要填充的数据值，需要保证在数据占用字节范围内。 数据类型和源操作数保持一致，T数据类型。 **当数据类型长度为64位时，该参数只能设置为0。** |

**表7 **DataCopyPadParams结构体参数定义

| 参数名称 | 含义 |
| --- | --- |
| isPad | 是否需要填充用户自定义的数据，取值范围：true，false。 true：填充padding value。 false：表示用户不需要指定填充值，会默认填充随机值。 |
| leftPadding | 连续搬运数据块左侧需要补充的数据范围，单位为元素个数。 **leftPadding、rightPadding所占的字节数均不能超过32字节。** |
| rightPadding | 连续搬运数据块右侧需要补充的数据范围，单位为元素个数。 **leftPadding、rightPadding所占的字节数均不能超过32字节。** |
| paddingValue | 左右两侧需要填充的数据值，需要保证在数据占用字节范围内。 uint64_t数据类型，要求源操作数为uint64_t数据类型，且该参数只能设置为0。 |

下面分别给出如下场景的配置示例：

- GM->VECIN/VECOUT
- VECIN/VECOUT->GM
- VECIN/VECOUT->TSCM
- 搬运模式的配置示例
- **GM**->**VECIN/VECOUT**

  - 参数解释

    - 当blockLen+leftPadding+rightPadding满足32字节对齐时，若isPad为false，左右两侧填充的数据值会默认为随机值；否则为paddingValue。
    - 当blockLen+leftPadding+rightPadding不满足32字节对齐时，框架会填充一些假数据dummy，保证左右填充的数据和blockLen、假数据为32字节对齐。若leftPadding、rightPadding都为0：dummy会默认填充待搬运数据块的第一个元素值；若leftPadding/rightPadding不为0：isPad为false，左右两侧填充的数据值和dummy值均为随机值；否则为paddingValue。

  - 配置示例1：

    - blockLen为64，每个连续传输数据块包含64字节；srcStride为1，因为源操作数的逻辑位置为GM，srcStride的单位为字节，也就是说源操作数相邻数据块之间间隔1字节；dstStride为1，因为目的操作数的逻辑位置为VECIN/VECOUT，dstStride的单位为DataBlock数量（每DataBlock为32字节），也就是说目的操作数相邻数据块之间间隔1个dataBlock。
    - blockLen+leftPadding+rightPadding满足32字节对齐，isPad为false，左右两侧填充的数据值会默认为随机值；否则为paddingValue。此处示例中，leftPadding、rightPadding均为0，则不填充。
    - blockLen+leftPadding+rightPadding不满足32字节对齐时，框架会填充一些假数据dummy，保证左右填充的数据和blockLen、假数据为32字节对齐。leftPadding/rightPadding不为0：若isPad为false，左右两侧填充的数据值和dummy值均为随机值；否则为paddingValue。

![](images/atlasascendc_api_07_0265_img_001.png)

  - 配置示例2：

    - blockLen为47，每个连续传输数据块包含47字节；srcStride为1，表示源操作数相邻数据块之间间隔1字节；dstStride为1，表示目的操作数相邻数据块之间间隔1个dataBlock。
    - blockLen+leftPadding+rightPadding不满足32字节对齐，leftPadding、rightPadding均为0：dummy会默认填充待搬运数据块的第一个元素值。
    - blockLen+leftPadding+rightPadding不满足32字节对齐，leftPadding/rightPadding不为0：若isPad为false，左右两侧填充的数据值和dummy值均为随机值；否则为paddingValue。

![](images/atlasascendc_api_07_0265_img_002.png)

  - 配置示例3：

    - blockLen为48，每个连续传输数据块包含48字节；srcStride为-48，表示源操作数相邻数据块之间间隔-48字节，相当于每次传输的连续数据块都是同一块；dstStride为1，表示目的操作数相邻数据块之间间隔1个dataBlock。
    - blockLen+leftPadding+rightPadding不满足32字节对齐，leftPadding、rightPadding均为0：dummy会默认填充待搬运数据块的第一个元素值。
    - blockLen+leftPadding+rightPadding不满足32字节对齐，leftPadding/rightPadding不为0：若isPad为false，左右两侧填充的数据值和dummy值均为随机值；否则为paddingValue。

![](images/atlasascendc_api_07_0265_img_003.png)

- **VECIN/VECOUT**->**GM**

  - 当每个连续传输数据块长度blockLen为32字节对齐时，下图呈现了需要传入的DataCopyParams示例，blockLen为64，每个连续传输数据块包含64字节；srcStride为1，因为源操作数的逻辑位置为VECIN/VECOUT，srcStride的单位为dataBlock(32字节)，也就是说源操作数相邻数据块之间间隔1个dataBlock；dstStride为1，因为目的操作数的逻辑位置为GM，dstStride的单位为字节，也就是说目的操作数相邻数据块之间间隔1字节。

![](images/atlasascendc_api_07_0265_img_004.png)

  - 当每个连续传输数据块长度blockLen不满足32字节对齐，由于Unified Buffer要求32字节对齐，框架在搬出时会自动补充一些假数据来保证对齐，但在当搬到GM时会自动将填充的假数据丢弃掉。下图呈现了该场景下需要传入的DataCopyParams示例和假数据补齐的原理。blockLen为47，每个连续传输数据块包含47字节，不满足32字节对齐；srcStride为1，表示源操作数相邻数据块之间间隔1个dataBlock；dstStride为1，表示目的操作数相邻数据块之间间隔1字节。框架在搬出时会自动补充17字节的假数据来保证对齐，搬到GM时再自动将填充的假数据丢弃掉。

![](images/atlasascendc_api_07_0265_img_005.png)

- **VECIN/VECOUT****->TSCM**

**注意：**内部实现涉及AIC和AIV之间的通信，实际搬运路径为VECIN/VECOUT->GM->TSCM，**发送通信消息会有开销，性能会受到影响**。

如图1 VECIN/VECOUT->TSCM搬运示意图所示，展示了从VECIN/VECOUT搬运到GM，再搬运到TSCM的过程：示例中数据类型为half，单个datablock（32字节）含有16个half元素，源操作数中的A1~A6、B1~B6、C1~C6为需要进行搬运的数据。

  - 从VECIN/VECOUT->GM的搬运，数据存储格式没有发生转变，依然是ND。

    - **blockCount**为需要搬运的连续传输数据块个数，设置为3；
    - **blockLen**为一个连续传输数据块的大小（单位为字节），设置为6 * 32 = 192；
    - **srcStride**为源操作数相邻连续数据块的间隔（前面一个数据块的尾与后面数据块的头的间隔），源操作数逻辑位置为VECIN/VECOUT，其单位为datablock，两个连续传输数据块（A1~A6、B1~B6）中间相隔1个A7，因此srcStride设置为1；
    - **dstStride**为目的操作数，相邻连续数据块间的间隔（前面一个数据块的尾与后面数据块的头的间隔），目的操作数逻辑位置为GM，其单位为字节，两个连续传输数据块（A1~A6、B1~B6）中间相隔2个空白的datablock，因此dstStride设置为64字节。

  - 从GM->TSCM的搬运，数据存储格式由ND转换为NZ。

    - **ndNum**固定为1，即A1~A6、B1~B6、C1~C6视作一整个ndMatrix；
    - **nValue**为ndMatrix的行数，即为3行；
    - **dValue**为ndMatrix中一行包含的元素个数，即为6 * 16 = 96个元素；
    - **srcNdMatrixStride**为相邻ndMatrix之间的距离，因为仅涉及1个ndMatrix，所以可填为0；
    - **srcDValue**表明ndMatrix的第x行和第x+1行所相隔的元素个数，如A1~B1的距离，即为8个datablock，8 * 16 = 128个元素；
    - **dstNzC0Stride**为src同一行的相邻datablock在NZ矩阵中相隔datablock数，如A1~A2的距离，即为7个datablock （A1 + 空白 + B1 + 空白 + C1 + 空白 * 2）；
    - **dstNzNStride**为src中ndMatrix的相邻行在NZ矩阵中相隔多少个datablock，如A1~B1的距离，即为2个datablock（A1 + 空白）；
    - **dstNzMatrixStride**为相邻NZ矩阵之间的元素个数，因为仅涉及1个NZ矩阵，所以可以填为1。

**图1 **VECIN/VECOUT->TSCM搬运示意图
![](images/atlasascendc_api_07_0265_img_006.png)
- 搬运模式的配置示例

  - Normal模式

blockLen为48，每个连续传输数据块包含48字节；srcStride为0，因为源操作数的逻辑位置为GM，srcStride的单位为字节，即源操作数相邻数据块之间紧密排列；dstStride为0，因为目的操作数的逻辑位置为VECIN、VECOUT，dstStride的单位为DataBlock（32字节），目的操作数相邻数据块之间无间隔，注意数据块包含leftPadding/rightPadding数据。

blockLen + leftPadding + rightPadding满足32字节对齐，isPad为false，左右两侧填充的数据值会默认为随机值，否则为paddingValue。此处示例中，leftPadding为0，rightPadding为16，每个连续传输数据块都会在右侧填充16字节。目的操作数的总长度为192字节。

  - Compact模式

blockLen为48，每个连续传输数据块包含48字节；srcStride为0，因为源操作数的逻辑位置为GM，srcStride的单位为字节，即源操作数相邻数据块之间紧密排列；dstStride为0，因为目的操作数的逻辑位置为VECIN、VECOUT，dstStride的单位为DataBlock（32字节），目的操作数相邻数据块之间紧密排列，不会填充数据

blockLen * blockCount + leftPadding + rightPadding 满足32字节对齐，isPad为false，左右两侧填充的数据值会默认为随机值，否则为paddingValue。此处示例中，leftPadding为0，rightPadding为16，在最后一个数据块右侧填充16字节。目的操作数的总长度为160字节。

![](images/atlasascendc_api_07_0265_img_007.png)

#### 约束说明

- leftPadding、rightPadding的字节数均不能超过32字节。
- 针对Atlas 350 加速卡，VECIN/VECOUT->TSCM通路，仅支持如下数据类型：half、bfloat16_t、int16_t、uint16_t、float、int32_t、uint32_t、int8_t、uint8_t、int64_t、uint64_t、double。

#### 调用示例

本示例实现了GM->VECIN->GM的非对齐搬运过程。

```
AscendC::DataCopyExtParams copyParams{1, 20 * sizeof(half), 0, 0, 0}; 
AscendC::DataCopyPadExtParams<half> padParams{true, 0, 2, 0};
// 从GM->VECIN搬运40字节
AscendC::DataCopyPad(dstGlobal, src0Global, copyParams, padParams);
```

结果示例：

```
输入数据src0Global: [1 2 3 ... 32]
输出数据dstGlobal:[1 2 3 ... 20]
```
