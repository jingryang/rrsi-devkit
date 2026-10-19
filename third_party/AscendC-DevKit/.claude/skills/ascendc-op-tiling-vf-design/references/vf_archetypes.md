# VF 编排典型模式图示（修订版）

VF 编排的几种典型模式，用于在 `generators/vf_layout_composer.md` 中合成新编排。

## 修订说明（v2）

1. **分清两层搬运**：外层 `AscendC::DataCopyPad`（真 mte2/mte3 引擎，GM ↔ UB）vs vf 内部 SIMD load/store（UB ↔ Reg）。
2. **明确 vf_N 的定义**：一个 `__VEC_SCOPE__` 块所在的函数，即一个完整的 SIMD 函数单元。ops-nn 命名约定为功能名 + 可选 `VF` 后缀（如 `CalculateRstdVF`、`ComputeYVF`）。
3. **合并模式 6**：原"单 VF 内多 stage"在 ops-nn 中无实例。多 VF 顺序编排（N≥4）作为模式 4 的推广子节，不再独立成章。
4. **补充 ops-nn 实例参照**：每个模式给出 ops-nn 中验证过的代表性算子。

### vf 内部搬运 API

vf 内部 load/store（UB ↔ Reg）使用 SIMD 指令，**不占** mte2/mte3 引擎。推荐 `Reg::LoadAlign` / `Reg::StoreAlign`，与旧 `MicroAPI::DataCopy` 功能完全等价，仅命名空间调整。老代码无需迁移。

---

## 模式 1：单 VF 串行

### 处理示意图

```
┌──────────────────────────────────────────────────────────────┐
│ Process                                                       │
│                                                               │
│   CopyIn0 ──────────→ Compute1 (vf_0) ──────────→ CopyOut2   │
│   DataCopyPad        __VEC_SCOPE__ {            DataCopyPad   │
│   真 mte2 引擎         load(UB→Reg)             真 mte3 引擎   │
│   GM ───→ UB           calc (SIMD)              UB ───→ GM    │
│                       store(Reg→UB)                            │
│                      }                                        │
│                                                               │
│   ←── 单 buffer (TQue<...,1>) , 无流水 ──→                    │
└──────────────────────────────────────────────────────────────┘
```

**vf_0 内部三阶段**：
- `load`：UB → Reg（`Reg::LoadAlign` 或 `MicroAPI::DataCopy`）
- `compute`：纯 SIMD 计算（`Muls`、`Exp`、`Adds`、`Div` 等）
- `store`：Reg → UB（`Reg::StoreAlign` 或 `MicroAPI::DataCopy`）

**适用**：极简 elementwise 算子（Cast、Swish、Sigmoid 等）、小 shape、UB 受限场景
**同步**：CopyIn→VF：`inQueue.EnQue` / VF 内 `inQueue.DeQue`（TQue 流水同步）；VF→CopyOut：VF 内 `outQueue.EnQue` / CopyOut `outQueue.DeQue`。单 VF 无 VF 间同步

**命名约定**：通常叫 `Compute` / `ComputeXxx`，单 VF 不一定带 `VF` 后缀。

---

## 模式 2：单 VF 双 Buffer（ping-pong 流水）

### 一句话核心

> - 📝 **程序员代码**：buf API 全部无 buf 编号（`AllocTensor` / `EnQue` / `DeQue` / `FreeTensor`）
> - ⚙️ **框架运行时**：根据 buf 状态机自动选 buf_0 或 buf_1
> - 🔄 **结果**：同一段代码，`TQue<..., 1>` 是线性，`TQue<..., 2>` 自动 ping-pong

### 程序员视角 vs 框架视角 对照表

| 维度 | 程序员视角（图示 1）| 框架视角（图示 2）|
|------|---------------------|---------------------|
| **buf 选择权** | ❌ 不指定 buf | ✅ 状态机自动选 |
| **AllocTensor 调用** | `inputQueue.AllocTensor<T>()` ← 无 buf 参数 | 内部选中 buf_0 或 buf_1 |
| **DeQue 调用** | `inputQueue.DeQue<T>()` ← 无 buf 参数 | 内部取"已写未读"的 buf |
| **EnQue / FreeTensor** | `EnQue(tensor)` / `FreeTensor(local)` ← 无 buf 参数 | 维护 buf 状态转换 |
| **Process 主循环** | CopyIn → Compute → CopyOut 线性代码 | 跨多轮 buf 切换形成 ping-pong 流水 |
| **可见性** | 只能看到队列深度 `TQue<..., 2>` 这一处 | 维护 buf_0/buf_1 的状态机 |

> **关键事实**：ping-pong 逻辑是**框架自动管理**的，程序员代码层面看不到 buf_0/buf_1 的切换。所有 buf 选择都由 `TQue<..., 2>` 的 AllocTensor / DeQue / EnQue / FreeTensor 运行时调度。

### 处理示意图

```
┌──────────────────────────────────────────────────────────────┐
│ Process (loopCount ≥ 2, 多轮 ping-pong)                       │
│                                                               │
│   CopyIn(i) ──────→ Compute(vf_0) ──────────→ CopyOut(i)     │
│   DataCopyPad       __VEC_SCOPE__ {            DataCopyPad    │
│   真 mte2 引擎        load(UB→Reg)             真 mte3 引擎    │
│   GM ───→ UB          calc (SIMD)              UB ───→ GM     │
│                      store(Reg→UB)                             │
│                     }                                         │
│                                                               │
│   ←── 双 buffer (TQue<...,2>) , 框架自动 ping-pong ──→        │
│       CopyIn(i+1) 与 Compute(i) 并行（buf 切换由状态机管理）    │
└──────────────────────────────────────────────────────────────┘
```

### 图示 1：代码视角（程序员看到的）

> ⚠️ **本图重点**：buf API（`AllocTensor` / `EnQue` / `DeQue` / `FreeTensor`）**全部无 buf 编号**——队列深度 `DB_BUFFER`（典型值 2）只是告诉框架"准备 2 个 buf"，buf_0/buf_1 的运行时选择由框架状态机决定（见 图示 2 / 对照解读）。

**结构概览**（非可执行代码，仅示意各函数的职责和调用关系）：

```
Kernel 类结构:

  InitBuffer:
    TPipe pipe_;
    TQue<VECIN,  2> inQueueX_;     // 双 buffer 输入队列
    TQue<VECOUT, 2> outQueueY_;    // 双 buffer 输出队列
    GlobalTensor<T> xGm_, yGm_;

  Init():
    pipe_.InitBuffer(inQueueX_, 2, bufSize);   // 分配 2 个 UB buffer
    pipe_.InitBuffer(outQueueY_, 2, bufSize);
    xGm_.SetGlobalBuffer(...);                 // 绑定 GM 地址

  Process():
    for (i = 0; i < loopCount; i++)
        CopyIn(i)   →   Compute(i)   →   CopyOut(i)
        // 双 buffer 自动 ping-pong：CopyIn(i+1) 与 Compute(i) 并行

  CopyIn:   AllocTensor → DataCopyPad(GM→UB) → EnQue
  Compute:  DeQue → AllocTensor → __VEC_SCOPE__{ load→calc→store } → FreeTensor → EnQue
  CopyOut:  DeQue → DataCopyPad(UB→GM) → FreeTensor
```

> 📝 `AllocTensor` / `DeQue` / `EnQue` / `FreeTensor` 均不指定 buf 编号，buf_0/buf_1 的运行时调度由框架状态机自动完成。

### 图示 2：框架视角（运行时实际发生的事）

```
                 时间 →
         ┌────────────┬────────────┬────────────┬────────────┐
         │   轮 0     │   轮 1     │   轮 2     │   轮 3     │
┌────────┼────────────┼────────────┼────────────┼────────────┤
│ buf_0  │ CopyIn_0   │ Compute_0  │ CopyIn_2   │ Compute_2  │
│        │ AllocTensor│ DeQue      │ AllocTensor│ DeQue      │
│        │ → 写       │ → 读       │ → 写       │ → 读       │
├────────┼────────────┼────────────┼────────────┼────────────┤
│ buf_1  │  (空闲)    │ CopyIn_1   │ Compute_1  │ CopyIn_3   │
│        │            │ AllocTensor│ DeQue      │ AllocTensor│
│        │            │ → 写       │ → 读       │ → 写       │
└────────┴────────────┴────────────┴────────────┴────────────┘
                          ↑                ↑
            buf_0/buf_1 同一时刻必然一个在读（Compute）
                          一个在写（CopyIn）
                          资源不冲突 → 流水掩盖
```

**框架内部维护的状态机**：
| buf 状态 | AllocTensor 时 | DeQue 时 |
|---------|--------------|----------|
| 空闲 | 选中该 buf，状态变为"已写未读" | 跳过 |
| 已写未读 | 跳过 | 选中该 buf，状态变为"已读可释放" |
| 已读可释放 | 跳过 | 跳过（等 FreeTensor 释放）|

→ AllocTensor 和 DeQue **总是选不同的 buf**（如果 buf_0 已写未读，AllocTensor 会选 buf_1），从而实现 ping-pong

### 对照解读：同一段代码 → ping-pong 状态机

下图把图示 1（程序员代码）和图示 2（框架运行时）按执行顺序逐行对齐。**左边是程序员写的代码（buf API 隐藏在 CopyIn/Compute/CopyOut 内部），右边是框架在每次调用时实际选择的 buf**：

| 轮次 | 程序员代码 | 框架在 inputQueue 内部的 buf 选择 | 框架在 outputQueue 内部的 buf 选择 |
|------|-----------|--------------------------------|----------------------------------|
| 0 | `CopyIn(0)` 内的 `AllocTensor` + 写 | **选 buf_0**（空闲）→ 写完后状态：已写未读 | - |
| 0 | `Compute(0)` 内的 `DeQue` | **取 buf_0**（已写未读）→ 读完状态：已读可释放 | `AllocTensor` 选 output 槽 |
| 0 | `CopyOut(0)` 内的 `DeQue` | - | 取 output → `FreeTensor` 释放 |
| 1 | `CopyIn(1)` 内的 `AllocTensor` | **选 buf_1**（空闲，buf_0 已读可释放）→ 写完后：已写未读 | - |
| 1 | `Compute(1)` 内的 `DeQue` | **取 buf_1**（已写未读）→ 读完状态：已读可释放 | 同上 |
| 2 | `CopyIn(2)` 内的 `AllocTensor` | **选 buf_0**（已读可释放→重置为空闲）→ 写完后：已写未读 | - |
| 2 | `Compute(2)` 内的 `DeQue` | **取 buf_0**（已写未读）→ 读完状态：已读可释放 | - |
| 3 | `CopyIn(3)` 内的 `AllocTensor` | **选 buf_1**（已读可释放→重置为空闲） | - |
| ... | | | |

**核心规律**（这也是 ping-pong 的本质）：
- 🔄 `AllocTensor` 永远选"空闲"或"已读可释放"的 buf（找到一个能写的）
- 🔄 `DeQue` 永远选"已写未读"的 buf（找到一个能读的）
- 🔄 因为 ping-pong 流水掩盖，`AllocTensor` 时上轮 `DeQue` 的 buf 必然已是"已读可释放"（已被 `FreeTensor` 释放回空闲池），所以**自动轮转到另一个 buf**
- 🔄 程序员写的线性 `CopyIn → Compute → CopyOut` 代码完全没变，是**框架的状态机**把同一个 buf_0/buf_1 在多轮间来回调度

### 关键元素

- `inputQueue = TQue<VECIN, 2>`：**深度 2 是 ping-pong 的核心信号**，框架据此分配 2 个 buf
- `outputQueue = TQue<VECOUT, N>`：**深度 N 取决于算法**：
  - 简单 elementwise（relu6、swish）：N = 1（Compute 后立即 CopyOut，output 不需要缓冲）
  - 复杂多阶段（rms_norm）：N = 2（`DOUBLE_BUFFER_NUM`，与 input 同样 ping-pong 流水掩盖）

  > ⚠️ **纠正**：之前的版本说"outputQueue 深度 1，不需要双 buffer"是**过度简化**。实际 rms_norm 中 `outQueueY`、`outQueueRstd` 都是深度 2。
- **同步机制**：AllocTensor → EnQue → DeQue → FreeTensor 构成生产者-消费者对，框架内部保证时序正确
- **程序员只写线性代码**，无需（也无法）手动指定 buf_0/buf_1
- 单 vf_0（带 `__VEC_SCOPE__`），但通过双 buffer 队列实现 CopyIn/Compute/CopyOut 三段流水

**适用**：Elementwise 算子（数据量大时）、loopCount ≥ 2 场景
**同步**：CopyIn→VF：`inQueue.EnQue` / VF 内 `inQueue.DeQue`（TQue 流水同步）；VF→CopyOut：VF 内 `outQueue.EnQue` / CopyOut `outQueue.DeQue`。`EnQue`/`DeQue` 管理双 buffer 切换
**ops-nn 实例**：

Process 预取模式示意（说明 ping-pong 时序，非完整可执行代码）：
```cpp
// 首轮预取
CopyIn(0);
for (i = 0; i < loopCount; i++) {
    Compute(i);                           // 当前轮计算
    CopyOut(i);                           // 当前轮写出
    if (i < loopCount - 1) CopyIn(i + 1); // 预取下一轮（与 Compute 并行）
}
```
> 📝 预取模式的关键：第 i 轮的 Compute/CopyOut 与第 i+1 轮的 CopyIn 在时间上重叠，由双 buffer 队列自动调度。

---

## 模式 3：双 VF（算法阶段 1 + 算法阶段 2）

### 处理示意图

```
┌──────────────────────────────────────────────────────────────────┐
│ Process                                                           │
│                                                                   │
│   CopyIn ──→ vf_stage_A ──→ vf_stage_B ──→ CopyOut               │
│   GM→UB     __VEC_SCOPE__ {  __VEC_SCOPE__ {      UB→GM          │
│   (mte2)     load(UB→Reg)    load(UB→Reg)        (mte3)           │
│              calc (reduce)   calc (normalize)                     │
│              store(Reg→UB)   store(Reg→UB)                        │
│              }               }                                    │
│                                                                   │
│   ←── VF 间同 V 引擎顺序执行，无显式同步；依赖由 data_flow 表达 ──→│
└──────────────────────────────────────────────────────────────────┘
```

**关键元素**：
- **2 个独立 VF**，**每个 VF 都是完整的算法计算单元**（内部含 [load → compute → store] 三段，不是"一个负责 Load、一个负责 Compute"的拆分）
- **VF 间是算法阶段依赖**：vf_stage_B 的输入依赖 vf_stage_A 的输出（reduce → normalize），同 V 引擎顺序执行保证数据可见
- **跨引擎同步**：CopyIn (mte2)→vf_stage_A：`inQueue.EnQue` / VF 内 `inQueue.DeQue`；vf_stage_B→CopyOut (mte3)：VF 内 `outQueue.EnQue` / CopyOut `outQueue.DeQue`

**与模式 2 的关键区别**：

| 维度 | 模式 2 | 模式 3 |
|------|--------|--------|
| 拆分对象 | **时间维度**（同一算法的不同轮次）| **算法维度**（同一轮内的不同阶段）|
| VF 数量 | 1 个（同一个 Compute 在多轮间切换）| 2 个（两个不同的算法 VF 串联）|
| 双 buffer 必要性 | 必需（否则掩盖不了 Load 时间）| 非必需（即使单 buffer 也成立）|
| 数据依赖 | 每轮独立（elementwise）| 跨阶段（reduce → normalize）|
| 典型算子 | elementwise（relu6, swish）| 有 reduce + normalize 两阶段的算子 |

**适用**：有 reduce + normalize 两阶段算法的算子（Softmax、LayerNorm 的 reduce 阶段、RmsNorm 的 square-reduce + normalize 等）

**同步**：仅跨引擎边界 — CopyIn(mte2)→vf_A：`inQueue.EnQue` / VF 内 `inQueue.DeQue`；vf_B→CopyOut(mte3)：VF 内 `outQueue.EnQue` / CopyOut `outQueue.DeQue`。VF 间同 V 引擎，无显式同步

**ops-nn 实例**：

| 算子 | vf_stage_A（阶段 1）| vf_stage_B（阶段 2）| 对应文件 |
|------|---------------------|---------------------|----------|
| `softmax` | `FirstNormCompute`（求 max + sum）| `SecondNormCompute`（normalize）| `softmax_v2_ar_full_load.h` |


**命名约定**：`CalculateXxxVF` / `ComputeXxxVF` / `FirstNormCompute` / `SecondNormCompute`（带 `VF` 后缀或算法阶段名）。

---

## 模式 4：三 VF 全流水

### 处理示意图

```
┌──────────────────────────────────────────────────────────────────────┐
│ Process                                                               │
│                                                                       │
│  CopyIn ──→ vf_1 ──→ vf_2 ──→ vf_3 ──→ CopyOut                      │
│  GM→UB    __VEC_SCOPE__ {                                            │
│  (mte2)    load(UB→Reg)                                              │
│            calc                                                       │
│           store(Reg→UB)                                               │
│           }                                                           │
│                                                                       │
│  ←── VF 间同 V 引擎顺序执行，无显式同步 ──→                           │
└──────────────────────────────────────────────────────────────────────┘
```

**关键元素**：
- **3 个独立 vf**（3 个 `__VEC_SCOPE__` 函数），按 vf_1 → vf_2 → vf_3 顺序编排
- 跨引擎同步：CopyIn→vf_1：`inQueue.EnQue` / VF 内 `inQueue.DeQue`；vf_3→CopyOut：VF 内 `outQueue.EnQue` / CopyOut `outQueue.DeQue`

**适用**：大数据量、流水深度可掩盖的场景；多阶段计算（如 quant 的 scale 计算 + offset 计算 + quantize）
**同步**：仅跨引擎边界 — CopyIn(mte2)→vf_1：`inQueue.EnQue` / VF 内 `inQueue.DeQue`；vf_3→CopyOut(mte3)：VF 内 `outQueue.EnQue` / CopyOut `outQueue.DeQue`。VF 间同 V 引擎，无显式同步
**ops-nn 实例**：

3 VF 全流水的典型函数命名（仅示意 VF 编排结构）：
```cpp
__aicore__ inline void ComputeMaxRowScaleVF(...) { /* VF1: max/scale */ }
__aicore__ inline void ComputeScaleSymVF(...)     { /* VF2: scale sym */ }
__aicore__ inline void ComputeYVF(...)            { /* VF3: quantize */ }
```

**`pooling/max_pool3d_grad_with_argmax/max_pool3d_grad_with_argmax_simd_full_load.h`**（31 个 `__VEC_SCOPE__`，典型多阶段全流水）。

**3 VF 顺序编排范式**（以 reduce→rstd→normalize 三阶段为例）：
```cpp
for (uint64_t i = 0; i < curBlockLoops; i++) {
    CalculateSquareReduceVF(xLocal, sumSqLocal, ...);   // VF_0: square + reduce
    ComputeRstdVF(sumSqLocal, rstdLocal, ...);          // VF_1: rsqrt
    ComputeYVF(xLocal, rstdLocal, gammaLocal, yLocal);  // VF_2: normalize
}
```

> ⚠️ **norm 全载模板的 VF_0（square-reduce）内部是二分累加**，不是逐段顺序归约——
> 规约轴全载（R ≤ 4VL²）时按四分支组织（≤VL 一步 / ≤2VL 两段并行 / >2VL 按
> **二分折叠点**折叠，详见 `ascendc-op-design-shared/references/a5_regbase_design.md`
> §8bis，VF_0 内部结构规范以该节为准）。vf-design 层只需保证**接口契约**：per-VF 的
> `function_signature` / `interface_params` 必须显式包含 `fold_point`（host tiling
> 整数法算好写入 TilingData）——接口缺参则 codegen 无从拿到该字段，折叠循环失去
> 寻址依据。其它规约类 VF（row-max、row-scale 等）不适用二分，按各自语义设计。
> 📝 rms_norm 的 `inQueueX`、`outQueueY` 等配置了 `TQue<..., DOUBLE_BUFFER_NUM>`（深度 2），用于多轮循环间掩盖 CopyIn/CopyOut 延迟。**队列深度是通用配置项，与 VF 数量无关**。

### 推广：N≥4

N≥4 的 VF 顺序编排是模式 3（N=2）和模式 4（N=3）的推广，实际 ops-nn 中极少（<5 个文件）：

```
vf_0 ──→ vf_1 ──→ ... ──→ vf_{N-1}
__VEC__{                                                    __VEC__{
load(UB→Reg)                                                load(UB→Reg)
calc                                                        calc
store(Reg→UB)                                               store(Reg→UB)
}                                                           }
←── N 个 VF 同 V 引擎顺序执行，依赖由 data_flow 表达，无 VF 间显式同步 ──→
```

唯一实例：**`norm/layer_norm_v3/layer_norm_v3_welford.h`**（5 VF）：
```cpp
ResetCache → RefreshCache → WelfordInitialize → ProcessWelfordUpdate → ProcessNormalize
```

---

## 模式 5：多 VF 独立（VF 间无依赖）

> **定位**：与模式 3/4 对比——区别不在 VF 数量，在 **VF 之间有无数据依赖**。有依赖→必须按依赖链顺序（模式 3/4），无依赖→各 VF 独立，顺序任意（模式 5）。
> 所有 VF 仍在**同一 V 引擎上顺序执行**，这一点与模式 3/4 相同。区别仅在于执行顺序是否受数据约束。

### 处理示意图

```
┌──────────────────────────────────────────────────────────────┐
│ Process（单核内）                                               │
│                                                               │
│  CopyIn_a ──┐            ┌── CopyIn_b    ← M≥2 路并行 (mte2) │
│  GM→UB      ├────────────┤  GM→UB                            │
│             ▼            ▼                                    │
│      vf_0 ──→ vf_1 ──→ ... ──→ vf_N-1     ← 同 V 引擎顺序     │
│    __VEC__{  __VEC__{        __VEC__{        但顺序无约束       │
│    calc(A)   calc(B)         calc(...)      （可任意排列）       │
│    }         }               }                                │
│      │         │               │                               │
│      └─────────┼── N≥2 路 VF，各算各的，互不消费对方输出 ──────┘  │
│                ▼                                              │
│           CopyOut (UB→GM)                                      │
│                                                               │
│  ←── M≥2 路 CopyIn + N≥2 路 VF 独立，VF 间无依赖 ──→         │
└──────────────────────────────────────────────────────────────┘
```

**关键元素**：
- **M≥2 路 CopyIn 并行**（多输入，各自独立搬运，之间无同步）
- **N≥2 路 VF 独立**——核心特征：**VF 之间无数据依赖**（`data_flow` 中无 VF→VF 边），各自从 CopyIn 读数据、写到 CopyOut，互不消费对方输出
- **与模式 3/4 的关键区别**：模式 3/4 的 `data_flow` 有 VF→VF 边（依赖链约束顺序），模式 5 没有（顺序无约束）

| 维度 | 模式 3/4（串行多 VF）| 模式 5（多 VF 独立）|
|------|---------------------|---------------------|
| VF 间数据依赖 | **有**（vf_B 消费 vf_A 的输出）| **无**（各 VF 独立，互不消费对方输出）|
| data_flow | 有 VF→VF 边 | 无 VF→VF 边（全部来自 copy_in） |
| 执行顺序 | 受依赖链约束（A→B→C 不可变）| 无约束（可任意排列） |
| CopyIn | 通常 1 路 | M≥2 路并行 |
| 典型场景 | reduce→normalize（算法阶段串联）| 多输入各自独立变换 |

**适用**：多路输入各自经过独立计算后汇总输出的场景（如 token embedding + position embedding 各自变换后相加）
**同步**：CopyIn 全部完成→`EnQue` / VF `DeQue`→VF 顺序执行（顺序任意）→全部完成→VF `EnQue` / CopyOut `DeQue`；VF 之间无 barrier
**ops-nn 实例**：RegBase 中模式 5 暂无成熟实例。多数看似"多路并行"的算子实为 `if constexpr` 分支互斥选择（仅一路执行），不作为本模式参考。

---

## 模式选择决策树

```
几个 VF（__VEC_SCOPE__ 块）？

├─ 1 个 VF
│   ├─ loopCount == 1 → 模式 1（单 VF 串行）
│   └─ loopCount ≥ 2 → 模式 2（单 VF 双 buffer ping-pong）
│
├─ ≥2 个 VF
│   ├─ VF 间有数据依赖（串行）
│   │   ├─ N=2 → 模式 3（双 VF，算法阶段依赖）
│   │   ├─ N=3 → 模式 4（三 VF 全流水）
│   │   └─ N≥4 → 模式 4 推广（N VF 顺序编排）
│   │
│   └─ VF 间无依赖（独立）
│       → 模式 5（多 VF 独立，顺序无约束）
```

---

## 模式选择映射

| 条件 | 推荐模式 |
|------|---------|
| `pipeline_stages=1` | 模式 1 |
| `pipeline_stages=1` + loopCount≥2 | 模式 2 |
| `pipeline_stages=2`（2 个 VF，算法阶段依赖）| 模式 3 |
| `pipeline_stages=3`（3 个 VF 全流水）| 模式 4 |
| `topology=independent`（VF 间无依赖，顺序无约束）| 模式 5 |
| `topology=composite` 或 ≥4 个 VF | 模式 4 推广 |

---

## 关键概念澄清

### 1. vf_N 的精确定义

**`vf_N` = 一个 `__VEC_SCOPE__ { }` 块**，位于 Compute 函数内部。

```cpp
__aicore__ inline void Compute(...) {
    LocalTensor<T> xLocal = inQueueX_.DeQue<T>();   // buffer 管理
    LocalTensor<T> yLocal = outQueueY_.AllocTensor<T>();

    __VEC_SCOPE__ {                                   // ← vf_0 从这里开始
        // load:    UB → Reg
        // compute: SIMD 计算（Muls / Exp / Adds / Div 等）
        // store:   Reg → UB
    }                                                 // ← vf_0 到这里结束

    inQueueX_.FreeTensor(xLocal);                    // buffer 管理
    outQueueY_.EnQue(yLocal);
}
```

- **vf_N** 只包含 `__VEC_SCOPE__ { }` 块内的 load / compute / store
- **Compute 函数** = buffer 管理（`DeQue` / `AllocTensor` / `FreeTensor` / `EnQue`）+ vf_N
- **CopyIn / CopyOut** 是独立的外层函数，使用 `DataCopyPad`（真 mte2/mte3），不属于 Compute

### 2. 两层搬运的区分

| 层级 | 搬运类型 | API | 引擎 | 位置 |
|------|---------|-----|------|------|
| **外层 Process** | GM ↔ UB | `AscendC::DataCopyPad` | **真 mte2 / mte3 引擎** | CopyIn / CopyOut 函数 |
| **vf 内部** | UB ↔ Reg | `Reg::LoadAlign` / `Reg::StoreAlign` 等 | **SIMD load/store 指令**（不占 mte2/mte3） | `__VEC_SCOPE__ { }` 块内 |

### 3. vf 命名约定

ops-nn 中的 VF 函数命名通常为：
- **功能名 + VF 后缀**（明确标识是 VF）：`CalculateRstdVF`、`CalculateNormalizeVF`、`ComputeYVF`、`ComputeMaxRowScaleVF`
- **仅功能名**（不带 VF）：`FirstNormCompute`、`SecondNormCompute`、`Compute`、`ComputeSingle`

DAG 编码中继承 `Vec::ElemwiseUnaryOP<T,T>` / `ElemwiseBinaryOP<T,T,T>` 的子类也算 VF（如 `GeluCustom`、`CalcBinaryYLogX`）。

### 4. 常见误区

| 误区 | 正确理解 |
|------|---------|
| "vf_0 是 vec compute 那一段" | vf_0 是整个 `__VEC_SCOPE__` 块（含 load / compute / store 三阶段）|
| "CopyIn 函数是 VF" | CopyIn 用 `DataCopyPad`（mte2 引擎），不含 `__VEC_SCOPE__`，**不是 VF** |
| "双 buffer = 模式 2" | 队列深度是可独立配置的通用项，与 VF 数量无关 |
| "N≥4 需要独立模式" | N=2/3 覆盖绝大多数场景（模式 3/4），N≥4 作为模式 4 推广子节 |
| "vf 内 load/store 占用 mte2/mte3" | vf 内的 load/store 是 SIMD 指令，**不占** mte2/mte3 引擎 |

---