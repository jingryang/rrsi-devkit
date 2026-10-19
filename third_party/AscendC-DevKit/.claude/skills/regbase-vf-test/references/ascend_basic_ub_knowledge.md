# Ascend NPU UB（Unified Buffer）基础知识

UB 是 Ascend NPU 中 **AIV（Vector Core）** 核中的 SRAM，用于存储局部变量，输入输出数据和栈。


## 1. UB 在 NPU 多层内存架构中的位置

### 1.1 内存层级

AI Core 内部采用多级存储体系。**对于 AIV 核**其内存从外到内依次为：

```
Global Memory (GM)
    ↓
L2 Cache （软件层面不可见）
    ↓
Unified Buffer (UB)  ← Vector 计算单元的直接数据来源
    ↓
Register File（3510 架构新增，SIMD 可编程向量寄存器）
```

- **UB** 是 AI Core 内专为 **Vector（矢量）计算单元** 设计的片上 SRAM。
- Vector 计算的源数据和目的数据都必须存放在 UB 中；SIMD 模式下不支持直接从 GM 加载数据。
- 对于 Ascend950 芯片（3510架构），其 VF （SIMD VF） 函数必须从 UB 加载数据到 Reg 寄存器，然后在寄存器上操作，最后将结果由 Reg 寄存器写入 UB。
- 每个 AIV 拥有独立的 UB；不同版本的 Ascend NPU 具有不同的 UB 大小。

### 1.2 典型数据搬运通路

| 通路 | 搬运单元 | 说明 |
|------|---------|------|
| GM → UB | MTE2 | 数据从全局内存加载到 UB |
| UB → GM | MTE3 | 计算结果从 UB 写回全局内存 |
| L0C → UB | Fixpipe（3510 架构新增） | Cube 计算结果可直接搬运到 UB |
| UB ↔ L1 | DataCopy（3510 架构新增） | UB 与 L1 之间可直接搬运 |

---

## 2. UB 中 32 Byte 对齐的特点

### 2.1 对齐要求

在所有 NPU 架构版本（2002、2201、3510）中，UB 都有严格的 **32 Byte 对齐** 要求：

- **地址对齐**：UB 的访问首地址必须 32B 对齐。
- **操作长度对齐**：Vector 指令的操作长度、搬运数据大小需按 **DataBlock（32B）** 对齐。
- **Bank 行长度**：每个 bank 的每行固定为 **32B**，这也是最小访问粒度。


### 2.2 代码示例

#### 从 GM 中搬运 1D 数据到 UB
对于 GM 上位于 xGm 处的 1D 数据，其长度为 len，将其搬运到 UB 中需要给其申请 lenAlign 的 LocalTensor （存储在 UB 上的 Tensor） 进行存储。

```cpp
TPipe pipe;
TQue<TPosition::VECIN, 1> inQueueX;
constexpr uint32_t UB_BLOCK_SIZE = 32;

uint32_t lenAlign = AscendC::CeilDivision(len * sizeof(T), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(T);
pipe.InitBuffer(inQueueX, 1, lenAlign * sizeof(T));
LocalTensor<T> xLocal = inQueueX.AllocTensor<T>();  // xLocal 的大小为 lenAlign * sizeof(T)，满足 32Byte 对齐

template <typename T>
__aicore__ inline void DataCopyInTensor1D(LocalTensor<T>& dst, GlobalTensor<T>& gm, uint64_t gmOffset,
        uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),                  // blockCount
        static_cast<uint32_t>(len * sizeof(T)),    // blockLen
        static_cast<uint32_t>(0),                  // srcStride
        static_cast<uint32_t>(0),                  // dstStride
        0                                          // rsv
    };
    DataCopyPadExtParams<T> padParams{
        false,                   // isPad
        static_cast<uint8_t>(0), // leftPadding
        static_cast<uint8_t>(0), // rightPadding
        static_cast<T>(0.0)      // paddingValue
    };
    DataCopyPad(dst, gm[gmOffset], copyParams, padParams);
}

template <typename T>
__aicore__ inline void DataCopyOutTensor1D(GlobalTensor<T>& gm, LocalTensor<T>& src, uint64_t gmOffset,
        uint32_t len)
{
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(1),                  // blockCount
        static_cast<uint32_t>(len * sizeof(T)),    // blockLen
        static_cast<uint32_t>(0),                  // srcStride
        static_cast<uint32_t>(0),                  // dstStride
        0                                          // rsv
    };
    DataCopyPad(gm[gmOffset], src, copyParams);
}
```

#### 从 GM 中搬运 2D 数据到 UB
例如 GM 上 2D 的数据 xGM，shape 为 [A, R]。为了后续在 R 轴上进行计算，就需要 R 轴上的数据都是完全可以访问的，如果将 GM 上连续的 [A, R] 连续的搬入 UB，则在访问其中某一行 R 的时候其起始地址不一定满足 32Byte 对齐的要求，这给后续处理带来了非对齐访问的困难。

解决办法：利用 `DataCopyPad` 的**多 block 模式**（`blockCount > 1`）+ DMA 自动对齐行为，一次调用完成 2D 搬运，每行自动对齐到 32B 边界。

##### ⚠️ 关键机制：DataCopyPad 的 DMA 自动对齐

`DataCopyPad` 在 UB（dst）侧有**自动 padding 行为**：

> **DMA 引擎会将每个 block 在 UB 侧的占用自动 pad 到 `ceil(blockLen, 32)` 字节。**

这意味着：
- 每个 block 搬入 `blockLen` 字节有效数据后，UB 侧该 block 的**实际占用**为 `ceil(blockLen, 32)` 字节
- 下一个 block 的 UB 起始地址 = 当前 block 起始 + `ceil(blockLen, 32)` + `dstStride × 32` 字节
- 当 `dstStride = 0` 时，相邻 block 在 UB 中间隔恰好为 `ceil(blockLen, 32)` 字节 = 自然 32B 对齐

##### ⚠️ stride 参数单位：32B block（非字节！）

`DataCopyExtParams` 中的 `srcStride` 和 `dstStride` 单位是 **32B block 个数**，不是字节：
- `dstStride = N` 表示 UB 侧相邻 block 之间，除了自动 pad 之外，还有 `N × 32` 字节的额外间隙
- `srcStride = N` 表示 GM 侧相邻 block 之间，除了 blockLen 之外，还有 `N × 32` 字节的额外间隙

**常见错误**：将 `dstStride` 设为字节数（如 `(colsAlign - cols) * sizeof(T)`），DMA 会将其乘以 32 导致行偏移严重错位！

##### 标准对齐场景（推荐写法，dstStride=0）

当 GM 中行数据是**紧密排布**（无间隙）时，只需 `dstStride=0`，DMA 自动对齐完成一切：

```cpp
TPipe pipe;
TQue<TPosition::VECIN, 1> inQueueX;
constexpr uint32_t UB_BLOCK_SIZE = 32;

// 计算对齐后的列数（UB 中每行实际占用的元素数）
uint32_t rAlign = AscendC::CeilDivision(R * sizeof(T), UB_BLOCK_SIZE) * UB_BLOCK_SIZE / sizeof(T);
pipe.InitBuffer(inQueueX, 1, A * rAlign * sizeof(T));
LocalTensor<T> xLocal = inQueueX.AllocTensor<T>();

// 一次 DataCopyPad 搬入所有行，DMA 自动对齐每行到 32B 边界
DataCopyExtParams copyInParams{
    static_cast<uint16_t>(A),                  // blockCount: A 行
    static_cast<uint32_t>(R * sizeof(T)),      // blockLen: 每行实际字节(可不对齐)
    static_cast<uint32_t>(0),                  // srcStride: GM 行紧密排布无间隙
    static_cast<uint32_t>(0),                  // dstStride: 依赖 DMA 自动 pad
    0
};
DataCopyPadExtParams<T> padParams{false, 0, 0, static_cast<T>(0.0)};
DataCopyPad(xLocal, xGm[0], copyInParams, padParams);
// 搬入后 UB 布局: xLocal[i * rAlign] 为第 i 行起始, 每行 32B 对齐
```

搬入后，VF 函数使用 `rAlign` 作为行间 stride、`R` 作为实际处理列数：
```cpp
// VF 函数签名分离 stride 和实际计算数
VfFunc(dstUb, srcUb, rows, rAlign/*stride*/, R/*actual cols*/);
```

##### 完整搬入搬出工具函数

```cpp
// 搬入: GM [rows, cols] 紧密 → UB [rows, colsAlign] 对齐
template <typename T>
__aicore__ inline void DataCopyInTensor2D(LocalTensor<T>& dst, GlobalTensor<T>& gm, uint64_t gmOffset,
        uint32_t rows, uint32_t cols, uint32_t colsAlign)
{
    // 额外 stride = (colsAlign 字节 - 自动pad字节) / 32
    // 对于标准对齐 colsAlign = ceil(cols*sizeof(T), 32)/sizeof(T)，此值为 0
    uint32_t dstStride = (colsAlign * sizeof(T) - 
        ((cols * sizeof(T) + UB_BLOCK_SIZE - 1) / UB_BLOCK_SIZE) * UB_BLOCK_SIZE) / UB_BLOCK_SIZE;
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(rows),               // blockCount
        static_cast<uint32_t>(cols * sizeof(T)),   // blockLen
        static_cast<uint32_t>(0),                  // srcStride: GM紧密
        static_cast<uint32_t>(dstStride),          // dstStride: 标准对齐时=0
        0
    };
    DataCopyPadExtParams<T> padParams{false, 0, 0, static_cast<T>(0.0)};
    DataCopyPad(dst, gm[gmOffset], copyParams, padParams);
}

// 搬出: UB [rows, colsAlign] 对齐 → GM [rows, cols] 紧密
template <typename T>
__aicore__ inline void DataCopyOutTensor2D(GlobalTensor<T>& gm, LocalTensor<T>& src, uint64_t gmOffset,
        uint32_t rows, uint32_t cols, uint32_t colsAlign)
{
    uint32_t srcStride = (colsAlign * sizeof(T) - 
        ((cols * sizeof(T) + UB_BLOCK_SIZE - 1) / UB_BLOCK_SIZE) * UB_BLOCK_SIZE) / UB_BLOCK_SIZE;
    DataCopyExtParams copyParams{
        static_cast<uint16_t>(rows),               // blockCount
        static_cast<uint32_t>(cols * sizeof(T)),   // blockLen
        static_cast<uint32_t>(srcStride),          // srcStride: 跳过UB对齐padding
        static_cast<uint32_t>(0),                  // dstStride: GM紧密
        0
    };
    DataCopyPad(gm[gmOffset], src, copyParams);
}
```

##### 常见陷阱总结

| 错误写法 | 错误原因 | 正确做法 |
|---------|---------|---------|
| `dstStride = (colsAlign - cols) * sizeof(T)` | stride 单位是 32B block 不是字节，值被放大 32 倍 | 除以 `UB_BLOCK_SIZE`，或标准对齐场景直接写 0 |
| `dstStride = (colsAlign - cols)` | 忘记单位换算 | 同上 |
| GM 行非紧密排布时 `srcStride=0` | GM 行间有间隙时需设置 srcStride | `srcStride = gmRowGap / UB_BLOCK_SIZE` |
| UB 分配按 `rows * cols` 字节 | 未考虑每行 pad 后的实际占用 | 按 `rows * colsAlign * sizeof(T)` 分配 |

## 3. UB 在不同 NPU 版本上大小的差异
| SOC名称 | UB 总大小 |
|---------|----------|
| Ascend 910B / 910 | **192 KB** |
| Ascend 950PR / 950DT | **248 KB** |
