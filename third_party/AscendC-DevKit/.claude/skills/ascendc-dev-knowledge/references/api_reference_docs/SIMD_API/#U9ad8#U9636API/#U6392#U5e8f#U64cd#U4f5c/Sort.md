# Sort

**页面ID:** atlasascendc_api_07_0842  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0842.html

---

#### 产品支持情况

| 产品 | 是否支持 |
| --- | --- |
| Atlas 350 加速卡 | √ |
| Atlas A3 训练系列产品            /             Atlas A3 推理系列产品 | √ |
| Atlas A2 训练系列产品            /             Atlas A2 推理系列产品 | √ |
| Atlas 200I/500 A2 推理产品 | x |
| Atlas 推理系列产品            AI Core | √ |
| Atlas 推理系列产品            Vector Core | x |
| Atlas 训练系列产品 | x |

#### 功能说明

- 对应不带模板参数SortConfig的函数原型

排序函数，按照数值大小进行降序排序。排序后的数据按照如下排布方式进行保存：

Atlas 350 加速卡采用方式一。

         Atlas A3 训练系列产品
        /
         Atlas A3 推理系列产品
        采用方式一。

         Atlas A2 训练系列产品
        /
         Atlas A2 推理系列产品
        采用方式一。

         Atlas 推理系列产品
        AI Core采用方式二。

  - 排布方式一：
        一次迭代可以完成32个数的排序，排序好的score与其对应的index一起以（score, index）的结构存储在dst中。不论score为half还是float类型，dst中的（score, index）结构总是占据8Bytes空间。如下所示：

    - 当score为float，index为uint32类型时，计算结果中index存储在高4Bytes，score存储在低4Bytes。

![](images/atlasascendc_api_07_0842_img_001.png)

    - 当score为half，index为uint32类型时，计算结果中index存储在高4Bytes，score存储在低2Bytes， 中间的2Bytes保留。

![](images/atlasascendc_api_07_0842_img_002.png)

  - 排布方式二：Region Proposal排布
        输入输出数据均为Region Proposal，一次迭代可以完成16个region proposal的排序。每个Region Proposal占用连续8个half/float类型的元素，约定其格式：

```
[x1, y1, x2, y2, score, label, reserved_0, reserved_1]
```

对于数据类型half，每一个Region Proposal占16Bytes，Byte[15:12]是无效数据，Byte[11:0]包含6个half类型的元素，其中Byte[11:10]定义为label，Byte[9:8]定义为score，Byte[7:6]定义为y2，Byte[5:4]定义为x2，Byte[3:2]定义为y1，Byte[1:0]定义为x1。

如下图所示，总共包含16个Region Proposals。

![](images/atlasascendc_api_07_0842_img_003.png)

对于数据类型float，每一个Region Proposal占32Bytes，Byte[31:24]是无效数据，Byte[23:0]包含6个float类型的元素，其中Byte[23:20]定义为label，Byte[19:16]定义为score，Byte[15:12]定义为y2，Byte[11:8]定义为x2，Byte[7:4]定义为y1，Byte[3:0]定义为x1。

如下图所示，总共包含16个Region Proposals。

![](images/atlasascendc_api_07_0842_img_004.png)

- 对应带模板参数SortConfig的函数原型

仅在Atlas 350 加速卡上支持。

根据模板参数SortConfig，按其中指定的排序算法，对输入数据排序，排序结果可以指定升序或降序排序。

当函数原型带有输出索引dstIndexTensor参数，需要输出排序结果数据分别对应的索引；若输入带有索引srcIndexTensor参数，则输出索引即为原输入的索引，若输入不带有索引，则对输入数据从0开始生成所需排序数量的索引，最终输出索引即为对应输入数据的索引。如下两幅图，分别为输入带有索引和输入不带索引的数据排序示意图。

**图1 **输入带有索引srcIndex的排序样例
![](images/atlasascendc_api_07_0842_img_005.png)**图2 **输入不带索引srcIndex的排序样例
![](images/atlasascendc_api_07_0842_img_006.png)

#### 函数原型

- 不带SortConfig

```
template <typename T, bool isFullSort>
__aicore__ inline void Sort(const LocalTensor<T>& dst, const LocalTensor<T>& concat, const LocalTensor<uint32_t>& index, LocalTensor<T>& tmp, const int32_t repeatTime)
```

- 带SortConfig
     仅支持Atlas 350 加速卡。

  - 接口框架申请临时空间

    - 不带srcIndexTensor和dstIndexTensor参数

```
template <typename T, bool isReuseSource = false, const SortConfig& config = DEFAULT_SORT_CONFIG>
__aicore__ inline void Sort(LocalTensor<T>& dstTensor, const LocalTensor<T>& srcTensor, const uint32_t calCount)
```

    - 不带srcIndexTensor参数，带有dstIndexTensor参数

```
template <typename T, bool isReuseSource = false, const SortConfig& config = DEFAULT_SORT_CONFIG>
__aicore__ inline void Sort(LocalTensor<T>& dstTensor, LocalTensor<uint32_t>& dstIndexTensor, const LocalTensor<T>& srcTensor, const uint32_t calCount)
```

    - 带有srcIndexTensor和dstIndexTensor参数

```
template <typename T, typename U, bool isReuseSource = false, const SortConfig& config = DEFAULT_SORT_CONFIG>
__aicore__ inline void Sort(const LocalTensor<T>& dstTensor, const LocalTensor<U>& dstIndexTensor, const LocalTensor<T>& srcTensor, const LocalTensor<U>& srcIndexTensor, const uint32_t calCount)
```

  - 通过sharedTmpBuffer入参传入临时空间

    - 不带srcIndexTensor和dstIndexTensor参数

```
template <typename T, bool isReuseSource = false, const SortConfig& config = DEFAULT_SORT_CONFIG>
__aicore__ inline void Sort(LocalTensor<T>& dstTensor, const LocalTensor<T>& srcTensor, const LocalTensor<uint8_t>& sharedTmpBuffer, const uint32_t calCount)
```

    - 不带srcIndexTensor参数，带有dstIndexTensor参数

```
template <typename T, bool isReuseSource = false, const SortConfig& config = DEFAULT_SORT_CONFIG>
__aicore__ inline void Sort(LocalTensor<T>& dstTensor, LocalTensor<uint32_t>& dstIndexTensor, const LocalTensor<T>& srcTensor, const LocalTensor<uint8_t>& sharedTmpBuffer, const uint32_t calCount)
```

    - 带有srcIndexTensor和dstIndexTensor参数

```
template <typename T, typename U, bool isReuseSource = false, const SortConfig& config = DEFAULT_SORT_CONFIG>
__aicore__ inline void Sort(LocalTensor<T>& dstTensor, LocalTensor<U>& dstIndexTensor, const LocalTensor<T>& srcTensor, const LocalTensor<U>& srcIndexTensor, const LocalTensor<uint8_t>& sharedTmpBuffer, const uint32_t calCount)
```

      由于该接口的内部实现中涉及复杂的数学计算，需要额外的临时空间来存储计算过程中的中间变量。临时空间支持开发者**通过sharedTmpBuffer入参传入**和**接口框架申请**两种方式。

  - 通过sharedTmpBuffer入参传入，使用该tensor作为临时空间进行处理，接口框架不再申请。该方式开发者可以自行管理sharedTmpBuffer内存空间，并在接口调用完成后，复用该部分内存，内存不会反复申请释放，灵活性较高，内存利用率也较高。
  - 接口框架申请临时空间，开发者无需申请，但是需要预留临时空间的大小。

#### 参数说明

- 对应不带SortConfig的函数原型 

**表1 **模板参数说明

| 参数名 | 含义 |
| --- | --- |
| T | 操作数的数据类型。            Atlas 350 加速卡，支持的数据类型为：half、float。                           Atlas A3 训练系列产品              /               Atlas A3 推理系列产品              ，支持的数据类型为：half、float。                           Atlas A2 训练系列产品              /               Atlas A2 推理系列产品              ，支持的数据类型为：half、float。                           Atlas 推理系列产品              AI Core，支持的数据类型为：half、float。 |
| isFullSort | 是否开启全排序模式。全排序模式指将全部输入降序排序，非全排序模式下，排序方式请参考表2中的repeatTime说明。 |

**表2 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| dst | 输出 | 目的操作数，shape为[2n]。            类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。 |
| concat | 输入 | 源操作数，即接口功能说明中的score，shape为[n]。            类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。            此源操作数的数据类型需要与目的操作数保持一致。 |
| index | 输入 | 源操作数，shape为[n]。            类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。            此源操作数固定为uint32_t数据类型。 |
| tmp | 输入 | 临时空间。接口内部复杂计算时用于存储中间变量，由开发者提供，临时空间大小BufferSize的获取方式请参考GetSortTmpSize。数据类型与源操作数保持一致。            类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。 |
| repeatTime | 输入 | 重复迭代次数，int32_t类型。                           - Atlas 350 加速卡：每次迭代完成32个元素的排序，下次迭代concat和index各跳过32个elements，dst跳过32*8 Byte空间。取值范围：repeatTime∈[0,255]。                                       -                 Atlas A3 训练系列产品               /                Atlas A3 推理系列产品               ：每次迭代完成32个元素的排序，下次迭代concat和index各跳过32个elements，dst跳过32*8 Byte空间。取值范围：repeatTime∈[0,255]。               -                 Atlas A2 训练系列产品               /                Atlas A2 推理系列产品               ：每次迭代完成32个元素的排序，下次迭代concat和index各跳过32个elements，dst跳过32*8 Byte空间。取值范围：repeatTime∈[0,255]。               -                 Atlas 推理系列产品               AI Core：每次迭代完成16个region proposal的排序，下次迭代concat和dst各跳过16个region proposal。取值范围：repeatTime∈[0,255]。 |

- 对应带SortConfig的函数原型 

**表3 **模板参数说明

| 接口 | 功能 |
| --- | --- |
| T | 操作数srcTensor和dstTensor的数据类型。            Atlas 350 加速卡，RADIX_SORT排序算法支持的数据类型为：uint8_t、int8_t、uint16_t、int16_t、uint32_t、int32_t、half、bfloat16_t、float、uint64_t、int64_t，MERGE_SORT排序算法支持的数据类型为：half、float。 |
| U | 操作数srcIndexTensor和dstIndexTensor的数据类型。            Atlas 350 加速卡，RADIX_SORT排序算法支持的数据类型为：uint32_t、int32_t、uint64_t、int64_t，MERGE_SORT排序算法支持的数据类型为：uint32_t。 |
| isReuseSource | 可选参数。是否可以复用输入的Tensor空间。 |
| 可选参数。Sort接口的相应配置：选择的排序算法，排序结果的升降序。数据类型SortConfig，定义如下。                                                                                                                                             ``` struct SortConfig {     SortType type = SortType::RADIX_SORT; // 排序算法     bool isDescend = false; // 是否降序排序，默认值为false，输出结果升序排序 }; ```                                                                                                    其中，排序算法的数据类型SortType取值如下。                                                                                                                                             ``` enum class SortType {     RADIX_SORT,  // 使用基排序算法实现     MERGE_SORT   // 使用归并排序算法实现 }; ```                                                                                                    Sort提供了两种不同的排序算法，MERGE_SORT归并排序算法和RADIX_SORT基排序算法。两种算法在执行速度、时间复杂度和算法稳定性上表现不同。                           - MERGE_SORT是一种稳定的排序算法，在所有情况下算法的时间复杂度都是O(nlogn)。               - RADIX_SORT算法的时间复杂度是O(n)，在处理大量数据时，如果最大数字的位数较少，该算法的效率很高，可以接近线性时间复杂度。但是如果最大数字的位数很大，时间复杂度会接近O(n^2)。                        config的默认值DEFAULT_SORT_CONFIG取值如下，使用基排序RADIX_SORT，对排序结果升序排序。                                                                                                                                             ``` constexpr SortConfig DEFAULT_SORT_CONFIG = {SortType::RADIX_SORT, false}; ``` |  |

**表4 **参数说明

| 参数名称 | 输入/输出 | 含义 |
| --- | --- | --- |
| dstTensor | 输出 | 值目的操作数，shape为[n]。MERGE_SORT算法下输出数据的每个元素需要按8Byte申请空间。            类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。 |
| dstIndexTensor | 输出 | 索引目的操作数，shape为[n]。当输入不带srcIndexTensor时，只支持uint32_t类型。            类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。 |
| srcTensor | 输入 | 值源操作数，shape为[n]。            类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。            此源操作数的数据类型需要与值目的操作数保持一致。 |
| srcIndexTensor | 输入 | 索引源操作数，shape为[n]。            类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。            此源操作数的数据类型需要与索引目的操作数保持一致。 |
| sharedTmpBuffer | 输入 | 临时空间。接口内部复杂计算时用于存储中间变量，由开发者提供，临时空间大小BufferSize的获取方式请参考GetSortMaxMinTmpSize。数据类型为uint8_t。            类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。            LocalTensor的起始地址需要32字节对齐。 |
| calCount | 输入 | 需要进行排序的数据元素个数。uint32_t类型。 |

#### 约束说明

- 当存在score[i]与score[j]相同时，如果i>j，则score[j]将首先被选出来，排在前面，即index的顺序与输入顺序一致。
- 非全排序模式下，每次迭代内的数据会进行排序，不同迭代间的数据不会进行排序。

- 带SortConfig的接口：

  - 仅支持Atlas 350 加速卡。
  - 基排序RadixSort和归并排序MergeSort都为稳定排序，即相同值在排序后的先后顺序保持不变。
  - 值目的操作数、值源操作数、索引目的操作数、索引源操作数的元素个数相同，且calCount参数值不能超过元素个数。
  - 不支持源操作数与目的操作数地址重叠。
  - 不支持sharedTmpBuffer与源操作数和目的操作数地址重叠。
  - 操作数地址对齐要求请参见通用地址对齐约束。
  - 使用MERGE_SORT算法排序时，待排序的元素个数必须是32的倍数。若不是32的倍数，用户需要手动将数据量补齐到32的倍数。

#### 调用示例

算子样例工程请通过[sort样例](https://gitcode.com/cann/asc-devkit/tree/9.0.0/examples/01_simd_cpp_api/03_libraries/05_sort/sort)链接获取。

- 处理128个half类型数据。

该样例适用于：

Atlas 350 加速卡

         Atlas A2 训练系列产品
        /
         Atlas A2 推理系列产品

         Atlas A3 训练系列产品
        /
         Atlas A3 推理系列产品

```
// sortedLocal：排序结果
// concatLocal：待排序数据的预处理结果
// indexLocal：索引数据
// sortTmpLocal：临时空间
// 待排序元素数量
uint32_t elementCount = 128;
// 迭代次数，每次迭代完成32个元素的排序
uint32_t m_sortRepeatTimes = m_elementCount / 32;
uint32_t m_extractRepeatTimes = m_elementCount / 32;
// 预处理
AscendC::Concat(concatLocal, valueLocal, concatTmpLocal, m_concatRepeatTimes);
// 执行排序
AscendC::Sort<T, isFullSort>(sortedLocal, concatLocal, indexLocal, sortTmpLocal, m_sortRepeatTimes);
AscendC::Extract(dstValueLocal, dstIndexLocal, sortedLocal, m_extractRepeatTimes);
```

```
示例结果
输入数据（srcValueGm）: 128个half类型数据
[31 30 29 ... 2 1 0
 63 62 61 ... 34 33 32
 95 94 93 ... 66 65 64
 127 126 125 ... 98 97 96]
输入数据（srcIndexGm）:
[31 30 29 ... 2 1 0
 63 62 61 ... 34 33 32
 95 94 93 ... 66 65 64
 127 126 125 ... 98 97 96]
输出数据（dstValueGm）:
[127 126 125 ... 2 1 0]
输出数据（dstIndexGm）:
[127 126 125 ... 2 1 0]
```

- 处理64个half类型数据。

该样例适用于：

         Atlas 推理系列产品
        AI Core

```
uint32_t elementCount = 64;
uint32_t m_sortRepeatTimes = m_elementCount / 16;
uint32_t m_extractRepeatTimes = m_elementCount / 16;
AscendC::Concat(concatLocal, valueLocal, concatTmpLocal, m_concatRepeatTimes);
AscendC::Sort<T, isFullSort>(sortedLocal, concatLocal, indexLocal, sortTmpLocal, m_sortRepeatTimes);
AscendC::Extract(dstValueLocal, dstIndexLocal, sortedLocal, m_extractRepeatTimes);
```

```
示例结果
输入数据（srcValueGm）: 64个half类型数据
[15 14 13 ... 2 1 0
 31 30 29 ... 18 17 16
 47 46 45 ... 34 33 32
 63 62 61 ... 50 49 48]
输入数据（srcIndexGm）:
[15 14 13 ... 2 1 0
 31 30 29 ... 18 17 16
 47 46 45 ... 34 33 32
 63 62 61 ... 50 49 48]
输出数据（dstValueGm）:
[63 62 61 ... 2 1 0]
输出数据（dstIndexGm）:
[63 62 61 ... 2 1 0]
```

- 带SortConfig

  - 处理1024个half类型数据，输入索引和输出索引为1024个uint32_t类型数据。

该样例适用于：

Atlas 350 加速卡

```
static constexpr AscendC::SortConfig config = {AscendC::SortType::RADIX_SORT, false};
Sort<T, false, config>(dstLocal, dstIndexLocal, srcLocal, 1024);
```

```
示例结果
输入数据（srcGm）: 1024个half类型数据
[1023 1022 ... 2 1 0]
输入数据（srcIndexGm）: 1024个uint32_t类型数据
[0 1 2 ... 1022 1023]
输出数据（dstGm）:
[0 1 2 ... 1022 1023]
输出数据（dstIndexGm）:
[1023 1022 ... 2 1 0]
```
