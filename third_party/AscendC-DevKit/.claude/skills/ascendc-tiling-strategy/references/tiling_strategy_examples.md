# Tiling 策略分析示例

### 示例1: 简单算子 — InitBuffer 到 UB 公式完整推导

#### 场景

根据 Kernel 端的 InitBuffer 调用，在 Tiling 端精确计算 UB 占用，实现 tileD 自适应分块。

#### 核心思路

UB 占用计算的本质是一个**双向对应关系**：
- **Kernel 端**（.h 文件）：通过 `pipe_->InitBuffer` 从 UB 上实际分配内存
- **Tiling 端**（tiling.cpp）：用公式预估这些 InitBuffer 总共会占多少 UB，从而反推出最大可用的 tile 尺寸

**两端必须严格一致。**

#### Kernel 端 InitBuffer

```cpp
template <typename T>
__aicore__ inline void Init() {
    // TQue 输入队列 (bf16/fp16)
    pipe_->InitBuffer(inQueueX, QUEUE_DEPTH, n_ * tileD_ * sizeof(T));
    pipe_->InitBuffer(inQueueGamma, QUEUE_DEPTH, tileD_ * sizeof(T));

    // TQue 输出队列 (bf16/fp16)
    pipe_->InitBuffer(outQueueY, QUEUE_DEPTH, tileD_ * sizeof(T));

    // TBuf 计算 buffer (float32)
    pipe_->InitBuffer(calcBuf, n_ * tileD_ * sizeof(float));
    pipe_->InitBuffer(tempBuf, tileD_ * sizeof(float));

    // 小 buffer（不随 tileD 缩放）
    pipe_->InitBuffer(smallBuf, alignedN_ * sizeof(float));
}
```

#### Step 1: InitBuffer 枚举表

| # | Buffer 名称 | 类型 | 数据类型 | 大小表达式 | 队列深度 | 分类 |
|---|------------|------|---------|-----------|---------|------|
| 1 | inQueueX | TQue | T(bf16) | n * tileD * sizeof(T) | 2 | A |
| 2 | inQueueGamma | TQue | T(bf16) | tileD * sizeof(T) | 2 | A |
| 3 | outQueueY | TQue | T(bf16) | tileD * sizeof(T) | 2 | A |
| 4 | calcBuf | TBuf | float32 | n * tileD * sizeof(float) | - | A |
| 5 | tempBuf | TBuf | float32 | tileD * sizeof(float) | - | A |
| 6 | smallBuf | TBuf | float32 | alignedN * sizeof(float) | - | B |

#### Step 2: UB 公式推导

```
A 类（随 tileD 缩放）:
  inQueueX:     QUEUE_DEPTH * n * sizeof(T) = 2 * 4 * 2 = 16 bytes/elem
  inQueueGamma: QUEUE_DEPTH * sizeof(T)     = 2 * 2     = 4  bytes/elem
  outQueueY:    QUEUE_DEPTH * sizeof(T)     = 2 * 2     = 4  bytes/elem
  calcBuf:      n * sizeof(float)           = 4 * 4     = 16 bytes/elem
  tempBuf:      sizeof(float)               = 4         = 4  bytes/elem
  ────────────────────────────────────────────────────────────
  bytesPerTileD = 16 + 4 + 4 + 16 + 4 = 44 bytes/elem

B 类（固定开销）:
  smallBuf:     alignedN * sizeof(float)    = 8 * 4     = 32 bytes
  ────────────────────────────────────────────────────────────
  smallBufferBytes = 32 bytes

availableUB  = 196608 - 32 = 196576 bytes
maxTileD     = 196576 / 44 = 4467
maxTileD     = AlignDown(4467, 16) = 4464
```

#### Step 3: 核数分配方案

```cpp
// BEFORE
const uint32_t BLOCK_DIM = 8;

// AFTER
auto ascendcPlatform = platform_ascendc::PlatformAscendC(context->GetPlatformInfo());
uint32_t hwCoreNum = ascendcPlatform.GetCoreNumAiv();
uint32_t numCore = std::min(hwCoreNum, totalRows);
context->SetBlockDim(numCore);
```

#### Step 4: Main/Tail 分配方案

```cpp
uint32_t mainBlockFactor = totalRows / numCore;
uint32_t tailRemainder = totalRows % numCore;
tiling.set_mainBlockFactor(mainBlockFactor);
tiling.set_tailRemainder(tailRemainder);
```

---

### 示例2: 复杂算子（LayerNormGrad）— 18 个 buffer UB 明细表

#### 场景

一个复杂算子的完整 UB 占用计算过程，包含多个 TQue 和 TBuf，以及详细的占用明细表。

#### Kernel 端 InitBuffer

```cpp
// TQue 入 (bf16) — 3个带 tileD
pipe_->InitBuffer(gradOutTileQueue_,  QUEUE_DEPTH, n_ * tileD_ * sizeof(T));
pipe_->InitBuffer(hOutTileQueue_,     QUEUE_DEPTH, tileD_ * sizeof(T));
pipe_->InitBuffer(xTileQueue_,        QUEUE_DEPTH, n_ * tileD_ * sizeof(T));
// TQue 入 (f32) — 2个小 buffer
pipe_->InitBuffer(hPostQueue_,        QUEUE_DEPTH, alignedN_ * sizeof(float));
pipe_->InitBuffer(hResQueue_,         QUEUE_DEPTH, alignedNN_ * sizeof(float));

// TQue 出 (bf16) — 2个带 tileD
pipe_->InitBuffer(gradHOutTileQueue_, QUEUE_DEPTH, tileD_ * sizeof(T));
pipe_->InitBuffer(gradXTileQueue_,    QUEUE_DEPTH, n_ * tileD_ * sizeof(T));
// TQue 出 (f32) — 2个小 buffer
pipe_->InitBuffer(gradHPostQueue_,    QUEUE_DEPTH, alignedN_ * sizeof(float));
pipe_->InitBuffer(gradHResQueue_,     QUEUE_DEPTH, alignedNN_ * sizeof(float));

// TBuf f32 — 6个带 tileD
pipe_->InitBuffer(gradOutF32Buf_,     n_ * tileD_ * sizeof(float));
pipe_->InitBuffer(hOutF32Buf_,        tileD_ * sizeof(float));
pipe_->InitBuffer(xF32Buf_,           n_ * tileD_ * sizeof(float));
pipe_->InitBuffer(tempBuf_,           tileD_ * sizeof(float));
pipe_->InitBuffer(accumBuf_,          tileD_ * sizeof(float));
pipe_->InitBuffer(workBuf_,           tileD_ * sizeof(float));
// TBuf f32 — 2个小 buffer
pipe_->InitBuffer(gradHPostTileSumsBuf_, alignedN_ * sizeof(float));
pipe_->InitBuffer(gradHResTileSumsBuf_,  alignedNN_ * sizeof(float));
```

#### UB 公式推导（n=4, alignedN=8, alignedNN=16）

```
A 类 bytesPerTileD:
  TQue bf16: QUEUE_DEPTH * (3n + 2) * sizeof(T) = 2 * 14 * 2 = 56 bytes/elem
  TBuf f32: (2n + 4) * sizeof(float) = 12 * 4 = 48 bytes/elem
  bytesPerTileD = 56 + 48 = 104 bytes/elem

B 类 smallBufferBytes:
  TQue f32: QUEUE_DEPTH * (2*alignedN + 2*alignedNN) * sizeof(float) = 384 bytes
  TBuf f32: (alignedN + alignedNN) * sizeof(float) = 96 bytes
  smallBufferBytes = 384 + 96 = 480 bytes

availableUB  = 196608 - 480 = 196128 bytes
maxTileD     = 196128 / 104 = 1885
maxTileD     = AlignDown(1885, 16) = 1872
```

#### UB 占用明细表（tileD=1280, D=2560）

```
┌──────────────┬─────────────────────────────┬───────────────┐
│ Buffer 类别  │         Buffer 名称         │ 大小（bytes） │
├──────────────┼─────────────────────────────┼───────────────┤
│ TQue bf16 入 │ gradOutTileQueue (4×1280×2) │ 2×10240=20480 │
│              │ hOutTileQueue (1280×2)      │ 2×2560 = 5120 │
│              │ xTileQueue (4×1280×2)       │ 2×10240=20480 │
├──────────────┼─────────────────────────────┼───────────────┤
│ TQue bf16 出 │ gradHOutTileQueue (1280×2)  │ 2×2560 = 5120 │
│              │ gradXTileQueue (4×1280×2)   │ 2×10240=20480 │
├──────────────┼─────────────────────────────┼───────────────┤
│ TQue f32 入  │ hPostQueue (8×4)            │ 2×32 = 64     │
│              │ hResQueue (16×4)            │ 2×64 = 128    │
├──────────────┼─────────────────────────────┼───────────────┤
│ TQue f32 出  │ gradHPostQueue (8×4)        │ 2×32 = 64     │
│              │ gradHResQueue (16×4)        │ 2×64 = 128    │
├──────────────┼─────────────────────────────┼───────────────┤
│ TBuf f32     │ gradOutF32Buf (4×1280×4)    │ 20480         │
│              │ hOutF32Buf (1280×4)         │ 5120          │
│              │ xF32Buf (4×1280×4)          │ 20480         │
│              │ tempBuf (1280×4)            │ 5120          │
│              │ accumBuf (1280×4)           │ 5120          │
│              │ workBuf (1280×4)            │ 5120          │
├──────────────┼─────────────────────────────┼───────────────┤
│ TBuf f32 小  │ gradHPostTileSumsBuf (8×4)  │ 32            │
│              │ gradHResTileSumsBuf (16×4)  │ 64            │
├──────────────┼─────────────────────────────┼───────────────┤
│ 合计         │                             │ 133600 bytes  │
└──────────────┴─────────────────────────────┴───────────────┘

UB 总大小: 196608 bytes (192 KB)
实际使用:  133600 bytes
UB 占用率: 67.9%
tileD: 1280 (分 2 片处理 D=2560)
```

---

### 示例3: 自适应核数 + Main/Tail 分配

#### Before（固定核数 + 不均衡分配）

```cpp
// 问题1: 硬编码核数
const uint32_t BLOCK_DIM = 8;
context->SetBlockDim(BLOCK_DIM);

// 问题2: 不均衡分配 — 最后一核负载可能很重
uint32_t rowsPerCore = numRow / BLOCK_DIM;
uint32_t tailRows = numRow - (BLOCK_DIM - 1) * rowsPerCore;
// 如果 numRow=100, BLOCK_DIM=8: rowsPerCore=12, tailRows=100-84=16 (多33%)
```

#### After（自适应 + 均衡）

```cpp
// 获取硬件核数
auto ascendcPlatform = platform_ascendc::PlatformAscendC(context->GetPlatformInfo());
uint32_t hwCoreNum = ascendcPlatform.GetCoreNumAiv();

// 自适应核数
uint32_t numCore = std::min(hwCoreNum, numRow);

// 均衡分配
uint32_t mainBlockFactor = numRow / numCore;
uint32_t tailRemainder = numRow % numCore;

// Tiling 数据
tiling.set_numCore(numCore);
tiling.set_mainBlockFactor(mainBlockFactor);
tiling.set_tailRemainder(tailRemainder);

context->SetBlockDim(numCore);

// Kernel 端使用：
// uint32_t blockIdx = GetBlockIdx();
// uint32_t myRows = (blockIdx < tailRemainder) ? mainBlockFactor + 1 : mainBlockFactor;
// uint32_t myOffset = blockIdx * mainBlockFactor + std::min(blockIdx, tailRemainder);
```

#### 效果对比（numRow=100）

| 方案 | 核数 | 前 N-1 核 | 最后一核 | 负载差异 |
|------|------|----------|---------|---------|
| Before | 8(固定) | 12 行 | 16 行 | 33% |
| After (hwCore=20) | 20(自适应) | 5 行 | 5 行 | 0% |
| After (hwCore=8) | 8(自适应) | 12 或 13 行 | 12 行 | ≤8% |

---

### 示例4: TilingKey 位编码方案设计

#### 编码设计

```cpp
// 位编码布局:
// bits [0]   : gemmaMode (1 bit)
// bits [1]   : useBeta   (1 bit)
// bits [2]   : highPrec  (1 bit)
// bits [3]   : useSlice  (1 bit)
// bits [4-9] : dtype     (6 bits, 支持 ge::DataType 枚举)

uint32_t CalcTilingKey(
    ge::DataType dtype,
    bool useBeta,
    bool highPrecision,
    bool useSlice,
    bool gemmaMode) {

    uint32_t key = 0;
    key = (key << 1) | (gemmaMode ? 1 : 0);         // bit 0
    key = (key << 1) | (useBeta ? 1 : 0);            // bit 1
    key = (key << 1) | (highPrecision ? 1 : 0);      // bit 2
    key = (key << 1) | (useSlice ? 1 : 0);           // bit 3
    key = (key << 6) | static_cast<uint32_t>(dtype);  // bits 4-9
    return key;
}
```

---

### 关键要点

1. **双向一致性**: Kernel 端的 InitBuffer 和 Tiling 端的计算公式必须严格对应
2. **分类计算**: 将 buffer 分为"随 tileD 缩放"（A类）和"固定开销"（B类）两类分别计算
3. **对齐处理**: bf16/fp16 对齐到 16 元素，float32 对齐到 8 元素，int8 对齐到 32 元素
4. **队列深度**: TQue 的实际 UB 占用 = QUEUE_DEPTH × 单 buffer 大小
5. **分片均衡**: 当需要分片时，尽量使各分片大小均衡（CeilDiv + AlignUp 重新分配）
6. **占用率目标**: 尽量使 UB 占用率达到 90% 以上，充分利用硬件资源
