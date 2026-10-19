# Ascend 950 硬件基本单元与流水控制

## 一、硬件架构概述

Ascend 950（包括 Ascend 950PR 和 Ascend 950DT）采用**分离架构**设计，AI Core 分为两个独立的核：

- **AIC 核（Cube 核）**：负责矩阵计算
- **AIV 核（Vector 核）**：负责向量计算

每个核都有自己的 **Scalar 单元**，能独立加载自己的代码段。

---

## 二、硬件基本单元

### 2.1 计算单元

| 计算单元 | 所属核 | 功能说明 |
|---------|--------|---------|
| **Cube 计算单元** | AIC | 负责矩阵乘法等计算密集型任务 |
| **Vector 计算单元** | AIV | 负责向量计算，数据来自 Unified Buffer （UB），要求 32 字节对齐 |
| **Scalar 计算单元** | AIC/AIV | 读取指令序列，将指令发射到对应执行单元的指令队列 |

### 2.2 存储单元

| 存储单元 | 所属核 | 对齐要求 | 用途 |
|---------|--------|---------|------|
| **Unified Buffer (UB)** | AIV | 32 Byte | 向量计算单元的数据缓冲区 |
| **L0A Buffer** | AIC | 512 Byte | 存储左矩阵（矩阵乘） |
| **L0B Buffer** | AIC | 512 Byte | 存储右矩阵（矩阵乘） |
| **L0C Buffer** | AIC | 64 Byte | 存储矩阵乘的结果和中间结果 |
| **L1 Buffer** | AIC | 32 Byte | 数据缓存，推荐 FRACTAL_NZ 格式 |
| **Fixpipe Buffer** | AIC | 64 Byte | 随路计算加速（量化/反量化、激活函数、格式转换） |
| **Global Memory (GM)** | 共享 | - | AIC 与 AIV 之间的数据交换媒介 |

### 2.3 搬运单元（流水线）

Ascend 950 是多流水线硬件设备，内部并行执行单元包括：

| 流水类型 | 名称 | 功能说明 |
|---------|------|---------|
| **PIPE_S** | 标量流水线 | Scalar 计算，使用 Tensor GetValue 函数时为此流水 |
| **PIPE_V** | 矢量计算流水 | Vector 计算及部分 L0C→UB 数据搬运 |
| **PIPE_M** | 矩阵计算流水 | Cube 矩阵计算 |
| **PIPE_MTE1** | 数据搬运流水 | L1 → L0A/L0B 数据搬运 |
| **PIPE_MTE2** | 数据搬运流水 | GM → L1/UB 数据搬运（搬入） |
| **PIPE_MTE3** | 数据搬运流水 | UB → GM 数据搬运（搬出） |
| **PIPE_FIX** | 数据搬运流水 | L0C → GM/L1 数据搬运（随路计算） |

---

## 三、代码分发与执行机制

### 3.1 指令分发流程

AscendC 代码的执行遵循以下流程：

1. **Scalar 单元读取指令序列**：Scalar 计算单元读取算子指令序列
2. **指令发射到对应队列**：Scalar 将向量计算、矩阵计算、数据搬运指令发射给对应单元的指令队列
3. **各单元异步并行执行**：Vector 计算单元、Cube 计算单元、数据搬运单元异步并行执行接收到的指令

```
Scalar Unit → [Vector Queue] → Vector Unit (AIV)
            → [Cube Queue]   → Cube Unit (AIC)  
            → [MTE2 Queue]   → DMA 搬入单元
            → [MTE3 Queue]   → DMA 搬出单元
            → [MTE1 Queue]   → L1→L0 搬运单元
            → [FIX Queue]    → Fixpipe 单元
```

### 3.2 代码在 AIC 和 AIV 上的分发

- **AIC 核执行**：矩阵计算相关代码（`Matmul`、`Mmad` 等 Cube 运算）
- **AIV 核执行**：向量计算相关代码（`Add`、`Mul`、`Abs`、`Relu` 等 Vector 运算）
- **混合执行**：通过 `__gm__` 修饰符或 `KERNEL_TYPE_MIX` 配置，可在 AIC 和 AIV 上同时执行不同代码段

AIC 与 AIV 的数据交互必须通过 **Global Memory** 进行：

```
AIC (L0C Buffer) → DataCopy → GM → DataCopy → AIV (Unified Buffer)
AIV (Unified Buffer) → DataCopy → GM → DataCopy → AIC (L1/L0A/L0B)
```

---

### 3.3 kernel 代码与流水线关系
kernel代码中不同代码会分发到不同的流水线上进行执行。
- `AscendC::Add`, `AscendC::Duplicate`, `AscendC::Cast`, `AscendC::ReduceSum` 和 `AscendC::Reg` 命名空间的函数（只能在 `__simd_vf__` 和 `__simd_calle__` 函数中） 等纯向量运算分发到 PIPE_V
- `AscendC::DataCopy` 和 `AscendC::DataCopyPad` 分发到 PIPE_MTE1, PIPE_MTE2 或 PIPE_MTE3
- `AscendC::Fixpipe` 分发到 PIPE_FIX
- `AscendC::Matmul`, `AscendC::Mmad` 分发到 PIPE_M
- 其他 `__aicore__` 中的标量运算和逻辑控制逻辑分发到 PIPE_S，其负责分发其他流水线指令。

## 四、流水控制与同步机制

### 4.1 为什么需要同步

AI Core 内部的执行单元（如 MTE2 搬运单元、Vector 计算单元等）以**异步并行**的方式运行。在读写 Local Memory（如 Unified Buffer）时，可能存在数据依赖关系：

- **读后写（RAW）**：后续指令需要读取前序指令写入的数据
- **写后读（WAR）**：后续指令写入的数据不能被前序指令读取覆盖
- **写后写（WAW）**：多个写入操作需要按顺序完成

为确保数据一致性及计算正确性，需通过同步控制协调操作时序。

### 4.2 同步控制分类

#### 4.2.1 多流水同步（不同流水线之间）（重点）

通过 `SetFlag/WaitFlag` 进行不同流水线间的同步控制：

- **SetFlag**：当前序指令的所有读写操作都完成之后，将硬件中的对应标志位设置为 1
- **WaitFlag**：当执行到该指令时，如果发现对应标志位为 0，该队列的后续指令将一直被阻塞；如果发现对应标志位为 1，则将对应标志位设置为 0，同时后续指令开始执行

#### 4.2.2 单流水同步（同一流水线内部）

通过 `PipeBarrier(ISASI)` 完成同一流水线内的同步控制，用于在同一流水线内部约束执行顺序，保证前序指令中所有数据的读写工作全部完成，后序指令才能执行。

### 4.3 同步事件类型（HardEvent）

Ascend 950 支持的同步事件类型：

```cpp
enum class HardEvent : uint8_t {
    // 名称格式：源流水_目标流水
    // 例如 MTE2_V 代表 PIPE_MTE2 为源流水，PIPE_V 为目标流水
    // 标识从 PIPE_MTE2 到 PIPE_V 的同步，PIPE_V 等待 PIPE_MTE2
    
    MTE2_MTE1,  // MTE2 → MTE1
    MTE1_MTE2,  // MTE1 → MTE2
    MTE1_M,     // MTE1 → M (Cube)
    M_MTE1,     // M → MTE1
    MTE2_V,     // MTE2 → V (Vector)
    V_MTE2,     // V → MTE2
    MTE3_V,     // MTE3 → V
    V_MTE3,     // V → MTE3
    M_V,        // M → V
    V_M,        // V → M
    V_V,        // V → V
    MTE3_MTE1,  // MTE3 → MTE1
    MTE1_MTE3,  // MTE1 → MTE3
    MTE1_V,     // MTE1 → V
    MTE2_M,     // MTE2 → M
    M_MTE2,     // M → MTE2
    V_MTE1,     // V → MTE1
    M_FIX,      // M → FIX
    FIX_M,      // FIX → M
    MTE2_FIX,   // MTE2 → FIX
    FIX_MTE2,   // FIX → MTE2
    MTE3_MTE2,  // MTE3 → MTE2
    MTE2_MTE3,  // MTE2 → MTE3
    S_V,        // S → V
    V_S,        // V → S
    S_MTE2,     // S → MTE2
    MTE2_S,     // MTE2 → S
    S_MTE3,     // S → MTE3
    MTE3_S,     // MTE3 → S
    FIX_S,      // FIX → S
    M_S,        // M → S
    FIX_MTE3,   // FIX → MTE3
};
```

### 4.4 SetFlag/WaitFlag 使用示例

#### 基本用法

```cpp
// 1. 获取 EventID（推荐通过 AllocEventID 或 FetchEventID）
int32_t eventID = static_cast<int32_t>(
    GetTPipePtr()->FetchEventID(AscendC::HardEvent::S_MTE3)
);

// 2. 设置标志位（前序指令完成后设置）
AscendC::SetFlag<AscendC::HardEvent::S_MTE3>(eventID);

// 3. 等待标志位（后续指令阻塞等待）
AscendC::WaitFlag<AscendC::HardEvent::S_MTE3>(eventID);
```
#### 典型场景：Vector 计算与 Scalar 同步（V_S）（重点，容易遗漏）

`V_S` 同步用于确保 **Vector 计算单元完成写操作后，Scalar 单元才能读取结果**。典型场景包括：

- **Reduce 后读取极值/索引**：Vector 执行 `ReduceMax`/`ReduceMin` 后，Scalar 需要读取最大值、最小值及其索引位置
- **条件分支控制**：Vector 计算结果决定 Scalar 的循环次数或分支走向
- **标量计算的原子操作**：Vector 修改的数据需被 Scalar 正确感知

```cpp
// 场景：Vector 执行 ReduceMax 后，Scalar 读取最大值索引
AscendC::LocalTensor<float> ubTensor;
AscendC::LocalTensor<float> ubWorkBuffer;  // Reduce 需要的临时空间

// 1. Vector 执行归约计算，结果写入 ubTensor[0]（最大值）
AscendC::ReduceMax(ubTensor, ubSrc, ubWorkBuffer, params);

// 2. 同步：确保 Vector 计算完成后，Scalar 才能安全读取
// 注意：如果不加 V_S 同步，Scalar 可能读取到旧数据或中间结果
int32_t eventIdVToS = static_cast<int32_t>(
    GetTPipePtr()->FetchEventID(AscendC::HardEvent::V_S)
);
AscendC::SetFlag<AscendC::HardEvent::V_S>(eventIdVToS);
AscendC::WaitFlag<AscendC::HardEvent::V_S>(eventIdVToS);

// 3. Scalar 读取 Reduce 结果（安全，因为 V_S 已保证 Vector 写完成）
float maxVal = ubTensor.GetValue(0);       // 读取最大值
int32_t maxIdx = static_cast<int32_t>(ubTensor.GetValue(1));  // 读取索引

// 4. Scalar 根据结果做后续逻辑判断
if (maxVal > threshold) {
    // ... 根据 maxVal 或 maxIdx 执行分支逻辑
}
```

**关键说明**：

- `V_S` 表示 **PIPE_V（Vector 流水线）→ PIPE_S（Scalar 流水线）** 的同步
- 当 Scalar 使用 `GetValue()`、`SetValue()` 或访问 Vector 计算结果时，若结果刚由 Vector 指令产生，则必须插入 `V_S` 同步
- 同理，若 Scalar 先设置值（如通过 `SetValue`）供 Vector 使用，则需要 `S_V` 同步

---

#### 典型场景：Vector 计算数据流 （可以通过 TQue 进行管理）

通过使用 TQue 的 AllocTensor/EnQue/DeQue/FreeTensor 来确保数据同步。

EnQue -> DeQue 之间构成同步关系，DeQue 会等待 EnQue 完成。

FreeTensor -> 第二次 AllocTensor 之间构成同步，第二次 AllocTensor 会等待 FreeTensor 完成。

```cpp
// 场景：GM → UB → Vector计算 → GM
// 需要确保：搬运完成后再计算，计算完成后再搬出
AscendC::GlobalTensor<half> srcGlobal, dstGlobal;
AscendC::LocalTensor<half> srcLocal, dstLocal;
AscendC::TQue<AscendC::QuePosition::VECIN, BUFFER_NUM> inQueue;
AscendC::TQue<AscendC::QuePosition::VECOUT, BUFFER_NUM> outQueue;

// 1. 从 GM 搬运数据到 UB
srcLocal = inQueue.AllocTensor<half>();
AscendC::DataCopy(srcLocal, srcGlobal, dataSize);
inQueue.EnQue(srcLocal);

// ------------------ 

// 3. Vector 计算
srcLocal = inQueue.DeQue<half>();
dstLocal = outQueue.AllocTensor<half>();
AscendC::Abs(dstLocal, srcLocal, dataSize);
outQueue.EnQue(dstLocal);
inQueue.FreeTensor(srcLocal);

// ------------------ 

// 5. 从 UB 搬运结果到 GM
dstLocal = outQueue.DeQue<half>();
AscendC::DataCopy(dstGlobal, dstLocal, dataSize);
outQueue.FreeTensor(dstLocal);
```

## 五、核间同步（AIC 与 AIV 之间）

当不同核（AIC 和 AIV）之间操作同一块全局内存时，存在数据依赖，需要进行核间同步。

### 5.1 CrossCoreSetFlag / CrossCoreWaitFlag

```cpp
// AIC 核执行
AscendC::CrossCoreSetFlag<0x2, PIPE_MTE3>(flagId);  // 模式2：AIC 与 AIV 同步

// AIV 核执行
AscendC::CrossCoreWaitFlag(flagId);
```

### 5.2 同步模式

| 模式 | 说明 |
|------|------|
| **模式 0** | AIC 核间或 AIV 核间同步（同类型核全部到达后才继续） |
| **模式 1** | AIV 核之间同步（两个 AIV 都执行到 SetFlag 后才继续） |
| **模式 2** | AIC 与 AIV 之间同步（AIC 执行 SetFlag 后，AIV 才能继续；两个 AIV 都执行 SetFlag 后，AIC 才能继续） |
| **模式 4** | AIC 与单个 AIV 同步（AIV0 与 AIV1 可单独触发 AIC 等待） |

---

## 六、关键约束与最佳实践

### 6.1 约束说明

1. **SetFlag/WaitFlag 必须成对出现**，且参数必须完全一致（包括模板参数和事件 ID）
2. **EventID 范围**：Ascend 950 上为 0-7，不可手动指定 6 和 7（可能被系统预留）
3. **在 TPipe/TQue 编程场景中**，禁止自行指定 eventID，必须通过 `AllocEventID` 或 `FetchEventID` 获取，否则容易与框架同步事件冲突导致卡死
4. **不允许连续设置同一个 EventID**，否则可能导致事件状态混乱
5. **使用完后立即释放 EventID**，避免 EventID 耗尽

### 6.2 最佳实践

1. **优先使用编程模型**：推荐使用 TPipe/TQue 编程模型，框架会自动处理大部分同步，降低编程复杂度
2. **仅在必要时手动同步**：以下场景需要开发者手动插入同步：
   - 使用涉及标量计算的原子操作接口时（如 `AtomicAdd`），标量计算单元和搬运单元在读写 GM 时存在数据依赖
   - MTE2/MTE3 搬运地址有重叠时
   - 自定义复杂数据流时
3. **核间同步注意**：Matmul 高阶 API 内部已使用 CrossCoreSetFlag/CrossCoreWaitFlag，不建议开发者同时使用，否则有 flagId 冲突风险
4. **性能优化**：合理使用双缓冲和流水线并行，隐藏搬运延迟

---

## 七、总结

Ascend 950 作为多流水线硬件设备，通过 AIC（矩阵计算）和 AIV（向量计算）分离的架构实现高效并行计算。不同 AscendC 代码根据计算类型分发到不同硬件单元执行：

- **AIC 核**：执行 Cube 矩阵计算、Fixpipe 随路计算
- **AIV 核**：执行 Vector 向量计算
- **Scalar 单元**：统一调度，将指令发射到各执行单元的指令队列

由于各执行单元异步并行，必须通过 `SetFlag/WaitFlag` 进行同步控制，确保数据依赖的正确性。正确使用同步机制的关键在于：

1. **理解数据流**：明确数据在各存储单元间的流动路径
2. **识别依赖点**：找出存在读后写、写后读、写后写的操作
3. **成对使用同步**：SetFlag 和 WaitFlag 必须成对出现，参数完全一致
4. **合理管理 EventID**：通过框架接口获取和释放，避免冲突和泄漏
5. **利用硬件并行**：在确保正确性的前提下，最大化流水线的并行度
