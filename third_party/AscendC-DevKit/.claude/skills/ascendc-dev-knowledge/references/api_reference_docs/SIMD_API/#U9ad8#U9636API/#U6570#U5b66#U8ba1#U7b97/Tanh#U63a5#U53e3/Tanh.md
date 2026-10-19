# Tanh

**页面ID:** atlasascendc_api_07_0492  
**来源:** https://www.hiascend.com/document/detail/zh/CANNCommunityEdition/900/API/ascendcopapi/atlasascendc_api_07_0492.html

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

按元素做逻辑回归Tanh，计算公式如下：

![](images/atlasascendc_api_07_0492_img_001.png)

![](images/atlasascendc_api_07_0492_img_002.png)

#### 函数原型

- 通过sharedTmpBuffer入参传入临时空间

  - 源操作数Tensor全部/部分参与计算

```
template <typename T, bool isReuseSource = false, const TanhConfig& config = DEFAULT_TANH_CONFIG>
__aicore__ inline void Tanh(const LocalTensor<T>& dstTensor, const LocalTensor<T>& srcTensor, const LocalTensor<uint8_t>& sharedTmpBuffer, const uint32_t calCount)
```

  - 源操作数Tensor全部参与计算

```
template <typename T, bool isReuseSource = false, const TanhConfig& config = DEFAULT_TANH_CONFIG>
__aicore__ inline void Tanh(const LocalTensor<T>& dstTensor, const LocalTensor<T>& srcTensor, const LocalTensor<uint8_t>& sharedTmpBuffer)
```

- 接口框架申请临时空间

  - 源操作数Tensor全部/部分参与计算

```
template <typename T, bool isReuseSource = false, const TanhConfig& config = DEFAULT_TANH_CONFIG>
__aicore__ inline void Tanh(const LocalTensor<T>& dstTensor, const LocalTensor<T>& srcTensor, const uint32_t calCount)
```

  - 源操作数Tensor全部参与计算

```
template <typename T, bool isReuseSource = false, const TanhConfig& config = DEFAULT_TANH_CONFIG>
__aicore__ inline void Tanh(const LocalTensor<T>& dstTensor, const LocalTensor<T>& srcTensor)
```

由于该接口的内部实现中涉及复杂的数学计算，需要额外的临时空间来存储计算过程中的中间变量。临时空间支持开发者**通过sharedTmpBuffer入参传入**和**接口框架申请**两种方式。

  - 通过sharedTmpBuffer入参传入，使用该tensor作为临时空间进行处理，接口框架不再申请。该方式开发者可以自行管理sharedTmpBuffer内存空间，并在接口调用完成后，复用该部分内存，内存不会反复申请释放，灵活性较高，内存利用率也较高。
  - 接口框架申请临时空间，开发者无需申请，但是需要预留临时空间的大小。

通过sharedTmpBuffer传入的情况，开发者需要为tensor申请空间；接口框架申请的方式，开发者需要预留临时空间。临时空间大小BufferSize的获取方式如下：通过GetTanhMaxMinTmpSize中提供的接口获取需要预留空间范围的大小。

#### 参数说明

**表1 **模板参数说明

| 参数名 | 描述 |
| --- | --- |
| T | 操作数的数据类型。 Atlas 350 加速卡，支持的数据类型为：half、float。 Atlas A3 训练系列产品/Atlas A3 推理系列产品，支持的数据类型为：half、float。 Atlas A2 训练系列产品/Atlas A2 推理系列产品，支持的数据类型为：half、float。 Atlas 推理系列产品AI Core，支持的数据类型为：half、float。 |
| isReuseSource | 是否允许修改源操作数。该参数预留，传入默认值false即可。 |
| config | 该参数仅支持Atlas 350 加速卡。 Tanh算法的相关配置。此参数可选配，TanhConfig类型，具体定义如下方代码所示，其中参数的含义为： algo：Tanh内部实现使用的算法。TanhAlgo类型，支持的取值如下：- INTRINSIC：默认值。该算法直接计算公式y = (e^(2x)-1)/(e^(2x)+1)，性能更好。- SUBSECTION_COMPENSATION：该算法通过误差补偿实现Tanh，精度更高。 |

```
enum class TanhAlgo {
  INTRINSIC = 0,
  SUBSECTION_COMPENSATION,
};
struct TanhConfig {
  TanhAlgo algo = TanhAlgo::INTRINSIC;
};
```

**表2 **接口参数说明

| 参数名 | 输入/输出 | 描述 |
| --- | --- | --- |
| dstTensor | 输出 | 目的操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 |
| srcTensor | 输入 | 源操作数。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 源操作数的数据类型需要与目的操作数保持一致。 |
| sharedTmpBuffer | 输入 | 临时缓存。 类型为LocalTensor，支持的TPosition为VECIN/VECCALC/VECOUT。 用于Tanh内部复杂计算时存储中间变量，由开发者提供。 临时空间大小BufferSize的获取方式请参考GetTanhMaxMinTmpSize。 |
| calCount | 输入 | 参与计算的元素个数。 |

#### 约束说明

- **不支持源操作数与目的操作数地址重叠。**
- 不支持sharedTmpBuffer与源操作数和目的操作数地址重叠。

#### 调用示例

```
// dstLocal: 存放Tanh计算结果的Tensor
// srcLocal: 存放Tanh计算输入的Tensor
// sharedTmpBuffer: 存放Tanh计算过程中临时缓存的Tensor

// 接口框架申请临时空间，全部参与计算
AscendC::Tanh(dstLocal, srcLocal);
// 接口框架申请临时空间，部分参与计算, 需要参与计算的元素个数为512
AscendC::Tanh(dstLocal, srcLocal, 512);

// 通过sharedTmpBuffer入参传入临时空间，全部参与计算
AscendC::Tanh(dstLocal, srcLocal, sharedTmpBuffer);
// 通过sharedTmpBuffer入参传入临时空间，部分参与计算, 需要参与计算的元素个数为512
AscendC::Tanh(dstLocal, srcLocal, sharedTmpBuffer, 512);
static constexpr AscendC::TanhAlgo algo = AscendC::TanhAlgo::SUBSECTION_COMPENSATION;
static constexpr AscendC::TanhConfig config = { algo };
AscendC::Tanh<half, false, config>(dstLocal, srcLocal, sharedTmpBuffer, 512);
```

结果示例如下：

```
输入数据(srcLocal): 
[-2.56 -2.55 -2.54 ... 0. ... 2.53  2.54  2.55]
输出数据(dstLocal): 
[-0.98813187 -0.9878992 -0.98761402 ... 0. ... 0.98737127 0.98761402 0.9878992]
```
