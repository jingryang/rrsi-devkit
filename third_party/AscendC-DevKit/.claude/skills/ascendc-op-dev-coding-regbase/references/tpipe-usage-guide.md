# TPipe 使用指南（Kernel 侧 UB 内存管理：TQue 流水 + TBuf 临时缓冲）

> **文档定位**：给 S4 编码阶段提供 **TPipe 管理下的 UB 内存使用 + 内在同步机制** 的一站式参考。覆盖 TPipe 下的两大 UB 内存组件——**TQue**（流水队列，有自动同步）和 **TBuf**（临时缓冲，无自动同步）。由 S2 在 `coding_index.md` 通过 `tpipe:XXX` 前缀引用。
>
> **适用范围**：A3 Membase 和 A5 Regbase 两种编程模型的 **Vector Pipeline** 场景。纯 Cube 算子不适用。
>
> **不覆盖**：核间同步（SyncAll/IBSet/CrossCoreSetFlag）→ 见 `ascendc-sync` skill；核内 VF 融合优化 → 见 `evolution-knowledge/a5/`。
>
> **文档结构**：§1-§6 讲 TQue（Vector Pipeline 主线，S4 必读），§7 讲 TBuf（Compute 内临时缓冲，按需读），§8-§10 陷阱/关系/协议合并汇总。

---

## §1 快速定位

| 场景 | 直接读本文档哪一节 |
|---|---|
| 写 Kernel 类框架（`Init` / `Process` / 三阶段函数骨架） | §2 样例 + §3.1 |
| 写 CopyIn 函数体 | §2 样例 + §3.2 CopyIn 同步语义 |
| 写 CopyOut 函数体 | §2 样例 + §3.2 CopyOut 同步语义 |
| 想理解 EnQue/DeQue 到底触发了什么 | §3 API→HardEvent 映射表 |
| 想理解或调整 DoubleBuffer（默认已开） | §4 depth / InitBuffer num / BUFFER_NUM 语义 |
| UB 不够/算法要求必须降为单缓冲 | §4.5 降级判定 |
| 需要在同一 Compute 里 DeQue 多个输入队列 | §5 多 TQue 顺序保证 |
| 想用手动 SetFlag/WaitFlag 替代 TQue | §6 选型决策树 |
| **Compute 内需要 tmp 缓冲**（bf16 cast/workspace/reduce/broadcast） | **§7 TBuf 临时缓冲** |
| **判断该用 TQue 还是 TBuf** | **§7.1 选型决策** |
| **跨流水读写 TBuf 时如何同步** | **§7.4 手动同步** |
| 编译能过但运行时挂死/结果不对 | §8 常见陷阱 |

---

## §2 可参考样例（Add 算子，DoubleBuffer 双缓冲）

**样例特征**：类结构组织、`BUFFER_NUM=2` 双缓冲（通过 `InitBuffer` 的 num 参数开启）、`Process` 循环切分 tile。这是 **Vector Pipeline 场景默认应有的形式**——TQue 编程模型的核心价值就在于自动流水，样例默认开启双缓冲，避免 S4 参考后遗漏这一升级点。

> **两个参数值取舍**：本样例 `TQue<..., 1>` 中的 template `depth=1` 是官方推荐（三阶段模式无连续 EnQue，编译器有特殊优化）；双缓冲通过 `InitBuffer(que, BUFFER_NUM=2, size)` 的 num 参数独立开启，与 depth 无关。其他常见写法（如入门教程 `TQue<..., BUFFER_NUM>`）能工作但非最优，见 §4.2 对比表。

```cpp
#include "kernel_operator.h"
using namespace AscendC;

constexpr uint32_t UB_BLOCK_SIZE  = 32;
constexpr uint32_t BUFFER_NUM     = 2;   // ← DoubleBuffer 关键：InitBuffer 的 num 参数生效于此

struct AddCustomTilingData {
    uint32_t totalLength;   // 每核处理总长度
    uint32_t tileLength;    // 每次 tile 处理长度（Host 侧已按 BUFFER_NUM 切分）
    uint32_t tileNum;       // 每核 tile 数（= totalLength / tileLength）
};

// ====== TilingData 搬入辅助 ======
template <typename T>
__aicore__ inline void CopyTilingData(T *tiling, GM_ADDR tilingGM) {
    auto *dst = reinterpret_cast<uint8_t *>(tiling);
    auto *src = reinterpret_cast<__gm__ uint8_t *>(tilingGM);
    for (size_t i = 0; i < sizeof(T); ++i) dst[i] = src[i];
}

// ====== GM ↔ UB 通用搬运封装（对齐/非对齐皆可） ======
template <typename T>
__aicore__ inline void DataCopyInTensor1D(LocalTensor<T>& dst, GlobalTensor<T>& gm,
                                          uint64_t gmOffset, uint32_t len) {
    DataCopyExtParams copyParams{1, static_cast<uint32_t>(len * sizeof(T)), 0, 0, 0};
    DataCopyPadExtParams<T> padParams{false, 0, 0, static_cast<T>(0)};
    DataCopyPad(dst, gm[gmOffset], copyParams, padParams);
}

template <typename T>
__aicore__ inline void DataCopyOutTensor1D(GlobalTensor<T>& gm, LocalTensor<T>& src,
                                           uint64_t gmOffset, uint32_t len) {
    DataCopyExtParams copyParams{1, static_cast<uint32_t>(len * sizeof(T)), 0, 0, 0};
    DataCopyPad(gm[gmOffset], src, copyParams);
}

// ====== KernelAdd 类：三阶段拆函数 + Process 循环 ======
class KernelAdd {
public:
    __aicore__ inline KernelAdd() {}

    __aicore__ inline void Init(GM_ADDR x, GM_ADDR y, GM_ADDR z, const AddCustomTilingData& tiling) {
        blockLength_ = tiling.totalLength;
        tileLength_  = tiling.tileLength;   // 每次 tile 长度（Host 侧已按 BUFFER_NUM 切分）
        tileNum_     = tiling.tileNum;      // = blockLength_ / tileLength_

        uint32_t tileLengthAlign =
            AscendC::CeilDivision(tileLength_ * sizeof(float), UB_BLOCK_SIZE)
            * UB_BLOCK_SIZE / sizeof(float);

        xGm_.SetGlobalBuffer((__gm__ float*)x + blockLength_ * GetBlockIdx(), blockLength_);
        yGm_.SetGlobalBuffer((__gm__ float*)y + blockLength_ * GetBlockIdx(), blockLength_);
        zGm_.SetGlobalBuffer((__gm__ float*)z + blockLength_ * GetBlockIdx(), blockLength_);

        // (关键) num = BUFFER_NUM = 2 开启双缓冲；每个 slot 大小为 tileLengthAlign * sizeof(float)
        pipe_.InitBuffer(inQueueX_,  BUFFER_NUM, tileLengthAlign * sizeof(float));
        pipe_.InitBuffer(inQueueY_,  BUFFER_NUM, tileLengthAlign * sizeof(float));
        pipe_.InitBuffer(outQueueZ_, BUFFER_NUM, tileLengthAlign * sizeof(float));
    }

    __aicore__ inline void Process() {
        // 每次循环处理一个 tile；双缓冲使 tile[i] 计算与 tile[i+1] 搬入并行
        for (uint32_t i = 0; i < tileNum_; ++i) {
            CopyIn(i);
            Compute();
            CopyOut(i);
        }
    }

private:
    __aicore__ inline void CopyIn(uint32_t tileIdx) {
        LocalTensor<float> xLocal = inQueueX_.AllocTensor<float>();  // 等待上一轮同 slot 的 FreeTensor
        LocalTensor<float> yLocal = inQueueY_.AllocTensor<float>();
        DataCopyInTensor1D<float>(xLocal, xGm_, tileIdx * tileLength_, tileLength_);
        DataCopyInTensor1D<float>(yLocal, yGm_, tileIdx * tileLength_, tileLength_);
        inQueueX_.EnQue(xLocal);   // 隐式 SetFlag<MTE2_V>：通知 Compute 该 tile 已就绪
        inQueueY_.EnQue(yLocal);
    }

    __aicore__ inline void Compute() {
        LocalTensor<float> xLocal = inQueueX_.DeQue<float>();   // 隐式 WaitFlag<MTE2_V>
        LocalTensor<float> yLocal = inQueueY_.DeQue<float>();
        LocalTensor<float> zLocal = outQueueZ_.AllocTensor<float>();
        Add(zLocal, xLocal, yLocal, tileLength_);
        outQueueZ_.EnQue<float>(zLocal);   // 隐式 SetFlag<V_MTE3>
        inQueueX_.FreeTensor(xLocal);      // 通知下一轮 AllocTensor 可以复用该 slot
        inQueueY_.FreeTensor(yLocal);
    }

    __aicore__ inline void CopyOut(uint32_t tileIdx) {
        LocalTensor<float> zLocal = outQueueZ_.DeQue<float>();  // 隐式 WaitFlag<V_MTE3>
        DataCopyOutTensor1D<float>(zGm_, zLocal, tileIdx * tileLength_, tileLength_);
        outQueueZ_.FreeTensor(zLocal);
    }

    TPipe pipe_;
    // template depth=1（AllocTensor/EnQue/DeQue/FreeTensor 顺序无连续 EnQue，官方推荐值）
    // 双缓冲通过 InitBuffer 的 num 参数（=BUFFER_NUM=2）开启，与 depth 独立，详见 §4
    TQue<TPosition::VECIN,  1> inQueueX_;
    TQue<TPosition::VECIN,  1> inQueueY_;
    TQue<TPosition::VECOUT, 1> outQueueZ_;
    GlobalTensor<float> xGm_, yGm_, zGm_;
    uint32_t blockLength_, tileLength_, tileNum_;
};

extern "C" __global__ __aicore__ void add_custom(
    GM_ADDR x, GM_ADDR y, GM_ADDR z, GM_ADDR workspace, GM_ADDR tiling)
{
    AddCustomTilingData tilingData_;
    CopyTilingData(&tilingData_, tiling);

    KernelAdd op;
    op.Init(x, y, z, tilingData_);
    op.Process();
}
```

**样例覆盖点检查表**（S4 参考样例时的自检项）：

- [ ] 类结构：`Init` 只做资源准备；`Process` 只做循环；三阶段各自成函数
- [ ] `TPipe` 与所有 TQue 都是**类成员变量**，作用域覆盖 `Process` 循环
- [ ] `TQue` template `depth` 参数使用 `1`（官方推荐；三阶段无连续 EnQue）
- [ ] `pipe_.InitBuffer(queue, BUFFER_NUM, tileLengthAlign * sizeof(T))` 的 **num 参数**设为 `BUFFER_NUM=2` 开启双缓冲
- [ ] Host 侧 Tiling 计算 `tileLength = 每核长度 / BUFFER_NUM`，Kernel 侧不再除
- [ ] `tileNum = blockLength / tileLength`，与 `BUFFER_NUM` **无关**（tileNum 是循环次数，不是 slot 数）
- [ ] `AllocTensor` 与 `FreeTensor` 数量匹配（每个 tile 一对）
- [ ] `EnQue` 与 `DeQue` 数量匹配
- [ ] `Compute` 后 `outQueue.EnQue` 在前，`inQueue.FreeTensor` 在后（让 CopyOut 尽早开始）
- [ ] **不加** `PipeBarrier<PIPE_ALL>`——EnQue/DeQue 已经完全同步，加了反而破坏流水
- [ ] 同一 `TPosition` 上的 **TQue Buffer 总数 ≤ 芯片 eventID 上限**（详见 §4.3）：Buffer 总数 = TQue 数量 × InitBuffer num；本样例 VECIN 上 2 个 TQue × num=2 = 4 buffer、VECOUT 上 1 个 TQue × num=2 = 2 buffer，均在上限内
- [ ] 样例假设 `totalLength` 能被 `tileLength` 整除；实际算子需要在 Tiling 处理尾块（详见 `basic_knowledge_docs/算子实践参考/SIMD算子实现/矢量编程/DoubleBuffer场景.md`）

> **降级到单缓冲的场景判定见 §4.5**。默认保持双缓冲——TQue 的核心价值就是自动流水，无特殊约束不降级。

---

## §3 API → HardEvent 映射表（TQue 内在同步机制）

TQue 是**编程模型**层的封装，底层由编译器和运行时插入 `SetFlag<HardEvent::X>` / `WaitFlag<HardEvent::X>` 完成硬件事件同步。开发者**无需**也**不允许**手动写这些 flag——但理解等价关系有助于：

- 判断样例中每一行代码的同步动作
- 决策什么时候必须回退到手动同步（§6）
- 排查死锁/挂起（§7）

### §3.1 EnQue / DeQue（Producer-Consumer 同步）

| AscendC API | 语义 | 等价底层同步 |
|---|---|---|
| `inQueue.EnQue(t)` (VECIN) | 通知消费者：MTE2 搬入完成，可以做 Vector 计算 | `SetFlag<HardEvent::MTE2_V>` |
| `inQueue.DeQue<T>()` (VECIN) | 等待生产者：MTE2 搬入完成才开始 Vector 计算 | `WaitFlag<HardEvent::MTE2_V>` |
| `outQueue.EnQue(t)` (VECOUT) | 通知消费者：Vector 计算完成，可以搬出 | `SetFlag<HardEvent::V_MTE3>` |
| `outQueue.DeQue<T>()` (VECOUT) | 等待生产者：Vector 计算完成才开始 MTE3 搬出 | `WaitFlag<HardEvent::V_MTE3>` |

**规律**：`TPosition` 决定 HardEvent 类型：
- `VECIN`  → `MTE2_V`（GM→UB 搬入后交给 Vector）
- `VECOUT` → `V_MTE3`（Vector 算完后交给 MTE3 搬出）

### §3.2 AllocTensor / FreeTensor（Buffer 生命周期同步）

**关键理解**：`AllocTensor` 和 `FreeTensor` 也是同步 API，管的是 **UB Buffer 的可复用性**：

| API | 语义 | 等价底层同步 |
|---|---|---|
| `queue.AllocTensor<T>()` | 等待"上一轮 buffer 已被消费完成"才能分配 | `WaitFlag`（对应上次 `FreeTensor` 的 `SetFlag`）|
| `queue.FreeTensor(t)` | 通知"这个 buffer 可以重新分配了" | `SetFlag`（对应下次 `AllocTensor` 的 `WaitFlag`）|

**为什么样例里 Compute 后是 "先 EnQue outQueue → 再 FreeTensor inQueue"？**

因为：
1. `outQueue.EnQue(zLocal)` 通知 CopyOut 可以搬出（写后读同步）
2. `inQueue.FreeTensor(xLocal)` 通知下轮 CopyIn 可以覆盖 xLocal 所在的 UB Buffer（读后写同步）

这两个动作**方向不同**：一个是数据流向 CopyOut，一个是 Buffer 归还给 CopyIn。在单缓冲（`InitBuffer num=1`）时只是"释放动作"，在双缓冲（`InitBuffer num=2`）时构成流水的核心。

### §3.3 一次 tile 循环的同步序列

以样例 `Process` 循环内一次迭代为例（第 i 轮），展开成手动同步等价形式。**注意**：`AllocTensor`/`FreeTensor` 在双缓冲下承担核心流水角色——它们负责跨 tile 的 UB Slot 复用同步。

```cpp
// AscendC 样例代码                            // 等价手动同步（伪代码）
// ─── 第 i 轮 CopyIn ────────────────────────
inQueueX_.AllocTensor<float>();             // WaitFlag（等 slot (i mod 2) 上一轮 FreeTensor）
inQueueY_.AllocTensor<float>();             // WaitFlag
DataCopyPad(xLocal, xGm_[i*tile], ...);     // MTE2 搬运（PIPE_MTE2，与上一轮 Compute 并行）
DataCopyPad(yLocal, yGm_[i*tile], ...);     // MTE2 搬运
inQueueX_.EnQue(xLocal);                    // SetFlag<HardEvent::MTE2_V>
inQueueY_.EnQue(yLocal);                    // SetFlag<HardEvent::MTE2_V>

// ─── 第 i 轮 Compute ───────────────────────
inQueueX_.DeQue<float>();                   // WaitFlag<HardEvent::MTE2_V>
inQueueY_.DeQue<float>();                   // WaitFlag<HardEvent::MTE2_V>
outQueueZ_.AllocTensor<float>();            // WaitFlag（等 slot (i mod 2) 上一轮 zLocal FreeTensor）
Add(zLocal, xLocal, yLocal, tileLength_);   // Vector 计算（PIPE_V，与下一轮 CopyIn 并行）
outQueueZ_.EnQue<float>(zLocal);            // SetFlag<HardEvent::V_MTE3>
inQueueX_.FreeTensor(xLocal);               // SetFlag（通知下一轮 xLocal AllocTensor）
inQueueY_.FreeTensor(yLocal);               // SetFlag

// ─── 第 i 轮 CopyOut ───────────────────────
outQueueZ_.DeQue<float>();                  // WaitFlag<HardEvent::V_MTE3>
DataCopyPad(zGm_[i*tile], zLocal, ...);     // MTE3 搬运（PIPE_MTE3）
outQueueZ_.FreeTensor(zLocal);              // SetFlag（通知下一轮 zLocal AllocTensor）
```

**双缓冲流水的关键观察**：

- 第 i 轮的 `MTE2 DataCopyPad` 与第 i-1 轮的 `Vector Add`**并行**——因为它们在不同 pipe 且使用不同 UB Slot
- 第 i 轮的 `Vector Add` 与第 i-1 轮的 `MTE3 DataCopyPad` **并行**——同理
- `AllocTensor` 的 `WaitFlag` 才是双缓冲流水控制的核心：它保证第 i 轮不会踩到第 i-2 轮尚未 Free 的 slot
- 单缓冲（InitBuffer num=1）时 `AllocTensor` 每次都要等本轮 `FreeTensor`，实质是串行——这就是为什么样例默认走双缓冲

---

## §4 depth、InitBuffer num 与 BUFFER_NUM 语义澄清

这是最容易混淆的三个概念，来源不同、职责不同、上限不同。**权威来源**：`ascendc-dev-knowledge/references/api_reference_docs/SIMD_API/基础API/资源管理/Pipe和Que框架/TQue/TQue简介.md`。

### §4.1 三者定义与区别

| 概念 | 出现位置 | 语义 | 官方推荐值 |
|---|---|---|---|
| `depth`（template 参数） | `TQue<TPosition, depth>` | **连续 EnQue 次数**（中间没有 DeQue） | **1**（非 Tensor 原地操作场景，编译器有特殊优化） |
| `num`（InitBuffer 参数） | `pipe.InitBuffer(que, num, size)` | 队列**实际分配的 UB Slot 数**（决定是否双缓冲） | 双缓冲用 2，单缓冲用 1 |
| `BUFFER_NUM`（用户常量） | `constexpr uint32_t BUFFER_NUM = 2;` | 编程约定：与 InitBuffer num 保持一致，同时用于 Tiling 侧 `tileLength / BUFFER_NUM` 切分 | 2 |

**关键结论**（引用 `TQue简介.md` §模板参数原文）：

> 这里的队列深度和 double buffer 无关，队列机制用于实现流水线并行，double buffer 在此基础上进一步提高流水线的利用率。**即使队列的深度为 1，仍可以开启 double buffer。**
>
> 非 Tensor 原地操作的场景下，队列的深度设置为 1 时，编译器对这种场景做了特殊优化，**性能通常更好，推荐设置为 1**。

**三阶段模式下 depth 恒为 1**：因为 `AllocTensor → EnQue → DeQue → FreeTensor` 每次 EnQue 之后立即 DeQue，不存在"连续 EnQue"，所以 depth 语义等于 1。双缓冲由 `InitBuffer` 的 num=2 独立开启。

### §4.2 三种典型写法对比

| 写法 | template depth | InitBuffer num | 效果 | 备注 |
|---|---|---|---|---|
| 官方推荐（本样例 §2） | `1` | `BUFFER_NUM=2` | 双缓冲 + depth=1 特殊优化 | ✅ 最优 |
| 官方入门教程 Add 写法 | `BUFFER_NUM=2` | `BUFFER_NUM=2` | 双缓冲，但跳过 depth=1 优化 | ⚠️ 可用但非最优；占 2 倍 eventID 资源 |
| 单缓冲 | `1` | `1` | 无双缓冲，串行流水 | 仅用于 §4.5 降级场景 |
| Preload 场景（罕见） | `2` | `2` | 连续搬入两块，中间不 DeQue | 官方原文列为极少数场景 |

**S4 编码规则**：新写算子按官方推荐（template depth=1 + InitBuffer num=2）；参考现有算子时如果看到 template depth=2 写法（入门教程 Add 风格），**不强制改回**——保持一致性优先。

### §4.3 硬件资源上限：TQue Buffer 总数

`TQue Buffer 总数 = TQue 数量 × InitBuffer num`，受**同一 TPosition** 上硬件 eventID 数量限制（不是"所有 TQue depth 之和"）。

**权威来源**：`TQue简介.md` §TQue Buffer限制：

| 芯片型号 | 每 TPosition 上 eventID 数（= Buffer 总数上限） |
|---|---|
| Atlas 训练系列 | **4** |
| Atlas 推理系列（AI Core / Vector Core） | 8 |
| Atlas A2 训练/推理 | 8 |
| Atlas A3 训练/推理 | 8 |
| Atlas 200I/500 A2 推理 | 8 |

**换算示例**（在 8 eventID 平台）：
- 全部单缓冲（num=1）→ 每 TPosition 最多 **8 个** TQue
- 全部双缓冲（num=2）→ 每 TPosition 最多 **4 个** TQue
- 混合：`Σ (每个 TQue 的 InitBuffer num) ≤ 8`

**跨 TPosition 独立**：VECIN 上的上限和 VECOUT 上的上限分开计算。

**超限处理**：调用 `queue.FreeAllEvent()` 释放该队列所有事件后可继续申请（`TQue简介.md` §"多次申请TQue"）。

### §4.4 DoubleBuffer 流水时序

```
时刻: t=1     t=2     t=3     t=4     t=5
──────────────────────────────────────────
MTE2:  Load₁   Load₂   Load₃   Load₄
         ↓       ↓       ↓       ↓
V:             Comp₁   Comp₂   Comp₃   Comp₄
                 ↓       ↓       ↓       ↓
MTE3:                  Store₁  Store₂  Store₃  Store₄
```

关键点：
- Load₂ 和 Comp₁ **并行**（PIPE_MTE2 和 PIPE_V 是独立流水线）
- 由 `InitBuffer num=2` 提供两个 UB Slot，事件同步确保 Comp₁ 用的是 Load₁ 的数据、Comp₂ 用的是 Load₂ 的数据
- 开启 DoubleBuffer 后**不需要**加 `PipeBarrier`——EnQue/DeQue 已经完全同步

### §4.5 何时必须降级到单缓冲（num=1）

**默认走双缓冲**（即 §2 样例形式，InitBuffer num=2）。仅在以下场景考虑降级：

| 场景 | 判定方法 | 处理 |
|---|---|---|
| UB 容量放不下两份 tile | `Σ (每队列 tileSize × sizeof(dtype)) × 2 > UB 可用容量 − 系统预留`（系统预留通常 1KB~8KB，A5 SIMD+SIMT 混合场景需额外扣除 32KB DCache）| 降 `BUFFER_NUM=1`，或减小 `tileSize` |
| 单次 tile 已必须占满 UB | 算子要求整块处理（如某些归约、单次 Softmax 全序列） | 保持 num=1，无 `Process` 循环 |
| 同 TPosition 上 Buffer 总数超硬件 eventID 上限 | `Σ (每个 TQue 的 InitBuffer num) > 8`（Atlas 推理/A2/A3/200I/500 A2）或 `> 4`（Atlas 训练系列） | 减少 TQue 数量，或降低部分队列 num |

降级到单缓冲的最小改动（相对 §2 样例）：

```cpp
constexpr uint32_t BUFFER_NUM = 1;  // 改这里

// TQue template depth 保持 1（三阶段模式恒为 1）
TQue<TPosition::VECIN,  1> inQueueX_;
TQue<TPosition::VECIN,  1> inQueueY_;
TQue<TPosition::VECOUT, 1> outQueueZ_;

// InitBuffer num 参数变 1，size 保持不变
pipe_.InitBuffer(inQueueX_,  1, tileLengthAlign * sizeof(float));
// ... 其余代码完全不变（Init/Process/CopyIn/Compute/CopyOut 结构保持）
```

**关键：不要因为"看起来简单"而降级**。TQue 双缓冲是编程模型的默认能力，降级只出于容量或算法约束。

---

## §5 多 TQue 之间的顺序保证

### §5.1 独立性

**每个 TQue 有独立的事件池**：`inQueueX` 和 `inQueueY` 的 EnQue/DeQue 各自使用独立的 HardEvent，互不阻塞。

在样例的 Compute 阶段：
```cpp
xLocal = inQueueX.DeQue<float>();  // 只等 inQueueX 的 MTE2_V
yLocal = inQueueY.DeQue<float>();  // 只等 inQueueY 的 MTE2_V
```

两个 `DeQue` 是**顺序阻塞调用**（先等 X 就绪再等 Y 就绪），但它们**等待的是独立事件**——如果 Y 的数据比 X 先到，等 X 的时间不会额外拉长 Y 的就绪；真正的并行发生在**流水线之间**（MTE2 搬入与 V 计算跨 tile 重叠），不是两个 DeQue 之间。

### §5.2 什么时候需要跨 TQue 同步

以下场景 TQue 无法自动覆盖，需要手动 `PipeBarrier` 或 `SetFlag/WaitFlag`：

| 场景 | 处理方式 |
|---|---|
| 同一 Vector 计算内需要 A 队列的 Compute 结果作为 B 队列的输入 | 中间加 `PipeBarrier<PIPE_V>` |
| 多个 Vector 流水 pipe 交叉（PIPE_V 与 PIPE_S 交叉）| 手动 `SetFlag<HardEvent::V_S>` / `WaitFlag<HardEvent::S_V>` |
| MTE2 和 MTE3 对同一 GM 地址访问 | 手动 `SetFlag<HardEvent::MTE3_MTE2>` |

详见 `ascendc-sync` skill。

---

## §6 TQue vs 手动同步选型决策树

```
是否核内 Vector Pipeline？
├─ 是
│   ├─ 单方向线性数据流（CopyIn → Compute → CopyOut）
│   │   → 使用 TQue                          【本文档主场景】
│   ├─ 多方向交叉、部分 pipe 未覆盖、部分 pipe 手写
│   │   → 使用手动 SetFlag/WaitFlag           【见 ascendc-sync】
│   └─ 需要跨 TPosition 复用同一 UB Buffer
│       → 使用 TQueBind + 手动 PipeBarrier    【见官方 EnQue 文档】
└─ 否（涉及核间同步）
    → 使用 SyncAll / IBSet/IBWait / CrossCoreSetFlag/WaitFlag
      【见 ascendc-sync 核间同步节】
```

**判定原则**：**只要能用 TQue，就用 TQue**。TQue 自动同步覆盖 95% 的 Vector Pipeline 场景，避免手动 eventID 管理带来的死锁风险。

---

## §7 TBuf 临时缓冲（Compute 内 tmp）

> **本节定位**：TBuf 是 UB 内存管理的另一种方式，用于**同 pipe 内的临时缓冲**（bf16 cast 中间产物、SoftMax workspace、Reduce 累加 buf、bias 广播等）。与 TQue 互补——TQue 管流水队列（自动同步），TBuf 管临时缓冲（**无自动同步**）。

### §7.1 选型：什么时候用 TQue，什么时候用 TBuf

| 场景 | 选择 | 理由 |
|---|---|---|
| GM ↔ UB 搬运的输入/输出 | **TQue** | 需要跨流水自动同步 |
| Compute 内的 tmp 中间结果（同 pipe 内） | **TBuf** | 无跨流水，不需要同步；不占 eventID |
| 高阶 API 传入的 workspace（SoftMax/LayerNorm） | **TBuf** | 官方要求；不参与流水 |
| Reduce 类算子的中间累加 buffer | **TBuf** | 只在 Compute 内使用 |
| bias/scale 广播复用（跨 tile 只搬一次） | **TBuf** | 数据搬一次多次读；Init 后进入 Process 需手动同步（见 §7.4）|

**决策规则**：**只要 UB 数据跨流水传递 → TQue；仅在同 pipe 内使用 → TBuf**。

### §7.2 API 差异（vs TQue）

| 维度 | TQue | TBuf |
|---|---|---|
| InitBuffer 签名 | `pipe.InitBuffer(que, num, size)` **三参数** | `pipe.InitBuffer(buf, size)` **两参数** |
| 入队/出队 | `EnQue` / `DeQue`（触发 HardEvent）| **无** |
| Alloc/Free | `AllocTensor` + `FreeTensor` 需成对 | **`Get` 无对应 Free** |
| 自动同步 | ✅ EnQue/DeQue/Alloc/Free 均触发 SetFlag/WaitFlag | ❌ **零同步事件**——跨流水读写要手动 |
| 占用 eventID | ✅ 每个 buffer 占 1 个 | ❌ **不占用** |
| 生命周期 | AllocTensor 分配、FreeTensor 释放 | TPipe 销毁时自动释放 |
| 硬件上限 | 同 TPosition ≤ 芯片 eventID 数（4 或 8）| Kernel 总 Buffer 数（TQue+TBuf）≤ **64**（`TPipe/InitBuffer.md` L94）|

**关键含义**：**TBuf 不占用 eventID**——这对多临时缓冲的复杂算子（LayerNorm、Attention）非常重要，可以突破 TQue 的 4/8 上限。

### §7.3 参考样例（关键片段，bf16 cast tmp）

TBuf 场景基于 §2 样例扩展，只需增加两个关键片段：

```cpp
// 类成员：TBuf 无 depth 模板参数、无 BUFFER_NUM
TBuf<TPosition::VECCALC> tmpBufX_;   // fp32 中间产物
TBuf<TPosition::VECCALC> tmpBufY_;

// Init：InitBuffer 两参数版本，size 单位为字节；未对齐时 API 自动补齐到 32B
pipe_.InitBuffer(tmpBufX_, tileLenAlign * sizeof(float));
pipe_.InitBuffer(tmpBufY_, tileLenAlign * sizeof(float));

// Compute：Get 无同步、无 eventID 消耗；无需 FreeTensor
LocalTensor<float> tmp0 = tmpBufX_.Get<float>();
LocalTensor<float> tmp1 = tmpBufY_.Get<float>();
Cast(tmp0, xLocal, RoundMode::CAST_NONE, tileLength_);       // PIPE_V
Cast(tmp1, yLocal, RoundMode::CAST_NONE, tileLength_);       // PIPE_V
Add(tmp0, tmp0, tmp1, tileLength_);                          // PIPE_V
Cast(zLocal, tmp0, RoundMode::CAST_RINT, tileLength_);       // PIPE_V
// 全部操作在 PIPE_V 内，同 pipe in-order，无需 PipeBarrier
```

**样例来源**：`ascendc-dev-knowledge/basic_knowledge_docs/算子实践参考/SIMD算子实现/矢量编程/TBuf的使用.md`（bf16 → fp32 → bf16 Add）。

### §7.4 手动同步（TBuf 的核心风险点）

TBuf 上的读写**没有自动同步**。核心规则：

- `PipeBarrier<PIPE_X>()` **只阻塞相同 pipe** 内的先后指令（同流水依赖）
- **跨流水必须**用 `SetFlag<HardEvent::A_B>` + `WaitFlag<HardEvent::A_B>`（PipeBarrier<单 pipe> 无法阻塞另一 pipe）
- `PipeBarrier<PIPE_ALL>()` 可作为兜底（阻塞所有流水，粒度粗）

**典型跨流水场景与正确同步**：

| 场景 | 类型 | 正确同步 |
|---|---|---|
| Vector 写 TBuf → MTE3 读 TBuf 搬出 | V→MTE3 | `SetFlag<HardEvent::V_MTE3>` + `WaitFlag<HardEvent::V_MTE3>` |
| MTE2 搬入 TBuf → Vector 读 TBuf 计算 | MTE2→V | `SetFlag<HardEvent::MTE2_V>` + `WaitFlag<HardEvent::MTE2_V>` |
| Scalar 写 TBuf → Vector 读 TBuf | S→V | `SetFlag<HardEvent::S_V>` + `WaitFlag<HardEvent::S_V>` |
| 同 pipe 内两次 Vector 计算（读写同段 TBuf）| V→V | 通常无需（同 pipe in-order）；地址别名等特殊情况用 `PipeBarrier<PIPE_V>()` |

**陷阱示例**（改自 `evolution-knowledge/common_pitfalls.md` #8）：

```cpp
// ❌ 错误 1：完全无同步，race condition
Compute(tmp);                     // PIPE_V 写 tmpBuf
DataCopy(gm, tmp, len);           // PIPE_MTE3 读 tmpBuf ← 可能读到未写完的数据

// ❌ 错误 2（常见误解）：PipeBarrier<PIPE_V> 无法阻塞 MTE3
Compute(tmp);
PipeBarrier<PIPE_V>();            // 只阻塞 V，MTE3 仍可能提前启动
DataCopy(gm, tmp, len);

// ✅ 正确：跨流水事件同步
Compute(tmp);
event_t evt = pipe.FetchEventID(HardEvent::V_MTE3);
SetFlag<HardEvent::V_MTE3>(evt);
WaitFlag<HardEvent::V_MTE3>(evt);
DataCopy(gm, tmp, len);
```

**TQue + TBuf 混用的隐性陷阱**：`DeQue` 一个 TQue Tensor **不保证** TBuf 上的操作与之有序——`DeQue` 的 `WaitFlag<MTE2_V>` 只针对该 TQue 的 tensor。如果 CopyIn 阶段有数据搬到 TBuf，进入 Compute 前需为 TBuf 单独同步。**推荐做法**：GM→UB 搬运都走 TQue，让 TBuf 只做**同 pipe 内**的临时缓冲，从架构上避免跨流水混用。

### §7.5 五大典型场景速览

| 场景 | 特征 | 详细来源 |
|---|---|---|
| **bf16/fp16 → fp32 → bf16/fp16 类型转换** | Cast 中间产物存 TBuf；Compute 内同 pipe 全走 PIPE_V | `basic_knowledge_docs/.../TBuf的使用.md` |
| **高阶 API workspace 共享** | SoftMax/LayerNorm 等 workspace **多算子共享一个 TBuf** 分时复用，UB 利用率翻倍 | `basic_knowledge_docs/.../算子与高阶API共享临时Buffer.md` |
| **Reduce 中间累加缓冲** | ReduceSum/ReduceMax 二分折叠时的中间产物；tmp 大小按最大分支预算 | `regbase-vf-test/SingleOperatorLaunch/examples/reducesum_custom.cpp` |
| **bias/scale 广播复用** | Init 阶段一次搬入，Process 循环内跨 tile 复用；**Init 后进 Process 前需手动同步** | `evolution-knowledge/a3/algorithm_insights/elementwise_fusion.md` |
| **TBufPool 分时复用** | 多阶段 tmp 复用同一段物理 UB；**不要**为 TBufPool 手写同步（`TBufPool简介.md` L30）| `api_reference_docs/.../TBufPool/` |

---

## §8 常见陷阱

| # | 陷阱 | 症状 | 正确做法 |
|---|------|------|---------|
| 1 | `EnQue` / `DeQue` 数量不匹配 | Kernel 卡死（队列空或队列满） | 每次 `AllocTensor + EnQue` 必须对应一次 `DeQue + FreeTensor` |
| 2 | 忘记 `FreeTensor` | UB 用尽死锁 | `Compute` 后立即 `FreeTensor` 释放输入 Buffer |
| 3 | 在 TQue 场景手动指定 eventID | 与框架 eventID 冲突，死锁或结果错误 | TQue 场景**禁止**手动 `SetFlag/WaitFlag`；如需手动，改用 `TBuf` + 完全手写 |
| 4 | 内层循环 `FetchEventID` | 芯片有限 eventID 池（4 或 8）快速回绕，与 TQue 冲突 | 手动 eventID 只用于外层，不在 inner loop 反复获取 |
| 5 | 同 TPosition 上 TQue Buffer 总数超硬件 eventID 上限 | 编译报错或 `AllocTensor` 运行时失败 | `Σ (每个 TQue 的 InitBuffer num) ≤ 8`（Atlas 推理/A2/A3/200I/500 A2）或 `≤ 4`（Atlas 训练系列），同一 TPosition 独立计算；详见 §4.3 |
| 6 | 双缓冲下加 `PipeBarrier<PIPE_ALL>` | 破坏流水，性能反而下降 | DoubleBuffer 场景**移除**所有多余 PipeBarrier，让 EnQue/DeQue 自动同步 |
| 7 | `InitBuffer` size 未按 32B 对齐 | DataCopy 报错或结果错乱 | `size = CeilDivision(len × sizeof(T), 32) × 32 / sizeof(T)` |
| 8 | `AllocTensor` 于 VECOUT 队列未先 InitBuffer | Kernel 编译过但运行崩溃 | 所有 TQue 必须先 `pipe.InitBuffer(queue, num, size)` |
| 9 | `outQueue.EnQue` 后立即用 `zLocal` | 已被 EnQue 的 Tensor 不能再写 | EnQue 之后不能再修改该 Tensor 内容 |
| 10 | Compute 后先 `FreeTensor(x)`，再 `outQueue.EnQue(z)` | 正确性不变但延迟 CopyOut 启动，损失流水机会 | 顺序应为先 `outQueue.EnQue` 再 `inQueue.FreeTensor`；原理详见 §3.2 |
| **TBuf 相关**：↓ |||
| 11 | 同一 TBuf 连续 `Get` 期望不同地址 | 两个 LocalTensor 指向同一首地址，数据互相覆盖 | 用 `GetWithOffset(len, offset)` 或对 tensor 做偏移 `tensor[N]`；见 `TBuf/Get.md` L76 |
| 12 | Vector 写 TBuf 后 MTE3/MTE2 立即读 | 结果错乱（race condition）| 跨流水同步：`SetFlag<HardEvent::V_MTE3>+WaitFlag<HardEvent::V_MTE3>` 或 `PipeBarrier<PIPE_ALL>()`；**不能用 `PipeBarrier<PIPE_V>`**（只阻塞同流水，见 §7.4）|
| 13 | Init 阶段 DataCopy 到 TBuf，Process 内直接用 | 首个 tile 结果错乱 | Init 完成后加 `SetFlag<HardEvent::MTE2_V>+WaitFlag<HardEvent::MTE2_V>` 或 `PipeBarrier<PIPE_ALL>()`；见 §7.5 |
| 14 | 调用 `pipe.InitBuffer(tbuf, BUFFER_NUM, size)` 三参数 | 编译报错（重载不匹配） | TBuf 只有两参数：`pipe.InitBuffer(tbuf, size)` |
| 15 | 期望 `TBuf.Get` 返回的 Tensor 需要 `FreeTensor` | 编译报错或运行时崩溃 | TBuf 的 Tensor **无需 Free**；TPipe 销毁时自动释放 |
| 16 | Kernel 中 Buffer 总数超 64 | 编译报错 | `Σ (TQue.InitBuffer_num) + Σ TBuf 数 ≤ 64`；见 §7.2 |
| 17 | TQue / TBuf 选型错误（该用 TQue 用了 TBuf，或反之）| 前者需大量手动同步或产生 race；后者浪费 eventID | 按 §7.1 决策：**跨流水 → TQue（自动同步）**；**同 pipe 内临时 → TBuf（不占 eventID）** |
| 18 | 同一 TBuf 内两个 tensor 生命周期重叠（如 `auto a = tbuf.Get<T>(); auto b = tbuf.Get<T>(); Add(a, a, b);`）| Undefined behavior，a/b 内存重叠 | 使用独立 TBuf 或顺序生命周期 |

> **非陷阱但需注意的写法**：新写算子建议按官方推荐 `TQue<..., 1>` + `InitBuffer(que, 2, size)`；见过参考代码使用 `TQue<..., BUFFER_NUM=2>` 时无需强制改回。差异分析见 §4.2。

---

## §9 与其他知识源的关系

| 知识层 | 关系 |
|---|---|
| `ascendc-dev-knowledge` 官方文档 | 本文档 TQue 部分提炼自 `编程模型设计原理.md` + `TQue简介.md` + `基于TPipe和TQue编程.md`；TBuf 部分提炼自 `TBuf简介.md` + `Get.md`/`GetWithOffset.md` + `TBuf的使用.md` + `算子与高阶API共享临时Buffer.md` + `TBufPool简介.md`；深入 API 语义请查官方文档 |
| `ascendc-sync` skill | 本文档专注 TQue 自动同步 + TBuf 典型同步；复杂场景（多 pipe 交叉、eventID 手动管理、`FetchEventID` 详细语义、核间同步）查此 skill |
| `evolution-knowledge/a3/optimization_patterns/double_buffering.md` | 本文档 §4 讲 DoubleBuffer 机制；性能优化决策查此文档 |
| `evolution-knowledge/a3/ascendc_api/common_pitfalls.md` | #3（TBuf Lifetime Overlap）→ 本文档陷阱 18；#8（V write → MTE3 read）→ 本文档陷阱 12 + §7.4。**注意**：#8 原例使用 `PipeBarrier<PIPE_V>` 作为"正确"同步方式，本文档依据官方 `PipeBarrier（ISASI）.md` 语义（"阻塞相同流水"）判断该写法**无法阻塞 MTE3**，建议采用 `SetFlag/WaitFlag<HardEvent::V_MTE3>` 跨流水事件同步；若与 evolution-knowledge 冲突，以官方文档为准 |
| `evolution-knowledge/a3/algorithm_insights/elementwise_fusion.md` | bias broadcast 场景来源；本文档 §7.5 已收纳 |
| `ascendc-tips` MM 类别 | 本文档陷阱清单涵盖了 MM-3（TBuf 别传 BUFFER_NUM）、MM-6（Tile length 算 TBuf 占用）、CA-8（bf16 fp32 cast tmp）主要 tips |
| `regbase-vf-test` SKILL.md §6 及 `SingleOperatorLaunch/examples/` | A5 Regbase 场景的 TQue + VF 融合样例；`reducesum_custom.cpp` 是本文档 §7.5 Reduce 场景的完整实战 |

---

## §10 引用协议（S2 使用）

S2 在生成 `coding_index.md` 时，通过 `tpipe:XXX` 前缀引用本文档：

**TQue 流水相关**：

| 前缀 | 指向章节 | 使用场景 |
|---|---|---|
| `tpipe:类框架同步映射` | §2 + §3 | Kernel 类框架（C.1）默认强制填入 |
| `tpipe:CopyIn同步` | §3.1 + §3.2 | CopyIn 函数体（C.2）按需追加 |
| `tpipe:CopyOut同步` | §3.1 + §3.2 | CopyOut 函数体（C.4）按需追加 |
| `tpipe:双缓冲` | §4.2 + §4.4 | Compute 或 Tiling 涉及 DoubleBuffer 时追加 |
| `tpipe:硬件上限` | §4.3 | 需要核对 TQue 数量是否超 eventID 上限时追加 |
| `tpipe:单缓冲降级` | §4.5 | 明确需要降级到单缓冲时追加 |
| `tpipe:多队列` | §5 | 有多个输入 TQue 时追加 |
| `tpipe:选型` | §6 | 需要判断是否走 TQue 时追加 |

**TBuf 临时缓冲相关**：

| 前缀 | 指向章节 | 使用场景 |
|---|---|---|
| `tpipe:tbuf选型` | §7.1 | 需要判断走 TQue 还是 TBuf 时 |
| `tpipe:tbuf-API差异` | §7.2 | 需要查 InitBuffer / Get / eventID 差异时 |
| `tpipe:tbuf样例` | §7.3 | Compute 内需要写 tmp 缓冲时 |
| `tpipe:tbuf手动同步` | §7.4 | 涉及跨流水 TBuf 读写时（**关键，必读**） |
| `tpipe:tbuf场景速览` | §7.5 | bf16 cast / workspace / Reduce / broadcast / TBufPool 场景 |

**通用**：

| 前缀 | 指向章节 | 使用场景 |
|---|---|---|
| `tpipe:陷阱清单` | §8 | 自检关注点补充（TQue 陷阱 1-10 + TBuf 陷阱 11-18）|

S4 解析 `tpipe:XXX` 时：Read `${SKILL_ROOT}/references/tpipe-usage-guide.md`，定位到对应章节。
