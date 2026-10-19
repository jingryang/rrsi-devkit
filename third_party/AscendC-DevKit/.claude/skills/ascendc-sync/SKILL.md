---
name: ascendc-sync
description: "AscendC 同步机制指南 — 由 rules/ascendc-dev.md 在算子代码生成过程中强制调用。当生成的代码涉及同步 API（SetFlag/WaitFlag/PipeBarrier/SyncAll/IBSet/IBWait/CrossCoreSetFlag 等）或用户提到同步相关关键词（同步、死锁、卡死、数据竞争）时，rule 会 invoke 本 skill 以提供核内/核间/任务间同步的场景选型、正确代码模式和常见陷阱。API 完整参数规格引用自 ascendc-dev-knowledge 知识库的 api_reference_docs/基础API/同步控制/ 目录。NOT for: precision debugging (ascendc-dumptensor) or performance profiling (ascendc-profiling)."
---

# AscendC 同步机制指南

**IMPORTANT**: 本指南提供同步机制的场景选型、代码模式和常见陷阱。各 API 的完整参数规格请查阅 `ascendc-dev-knowledge` skill 知识库的 `api_reference_docs/基础API/同步控制/` 目录下的对应文件。

## 1. 同步机制总览

AscendC 同步控制分为三个层级：

| 层级 | 场景 | 机制 | 关键 API |
|------|------|------|----------|
| 核内单流水 | 同一流水线内指令间的数据依赖 | 阻塞同流水后续指令 | `PipeBarrier` |
| 核内多流水 | 不同流水线间的数据依赖 | 事件标志位 Set/Wait | `SetFlag`/`WaitFlag` |
| 核间 | 多核访问同一 GM 区域 | 软/硬全核屏障、点对点同步、确定性顺序 | `SyncAll`, `IBSet`/`IBWait`, `WaitPreBlock`/`NotifyNextBlock`, `CrossCoreSetFlag`/`CrossCoreWaitFlag` |
| 任务间 | SuperKernel 子 Kernel 间的并行 | 任务边界控制 | `SetNextTaskStart`, `WaitPreTaskEnd` |

### 自动同步 vs 手动同步

- **编译器自动同步**: PIPE_V 内部的单流水同步由编译器自动插入（需开启自动同步，Kernel 直调和自定义算子工程默认开启）
- **框架自动同步**: Cube 侧所有流水同步由 Ascend C 框架完成；PIPE_V/PIPE_MTE2/PIPE_MTE3/PIPE_S 之间的部分多流水同步也由编译器/框架完成
- **需要手动同步的场景**: PIPE_MTE2/PIPE_MTE3 搬运地址有重叠时的单流水同步；部分未被编译器覆盖的多流水同步；所有核间同步

> **原则**: 优先使用编程模型（TQue/TPipe 框架的 EnQue/DeQue），它自动处理大多数同步。仅在框架无法覆盖的场景下才手动插入同步。

## 2. 场景决策树

根据你的场景，快速定位应使用的同步 API：

```
需要同步？
├─ 同一个核内？
│   ├─ 同一条流水线内的指令有依赖？
│   │   └─ PipeBarrier<PIPE_xxx>()                    → §3.1
│   ├─ 不同流水线间的指令有依赖？
│   │   └─ SetFlag/WaitFlag + eventID                  → §3.2
│   └─ 需要等待所有内存访问完成（内存屏障）？
│       └─ DataSyncBarrier<MemDsbT::xxx>()             → §3.3
│
├─ 不同核之间？
│   ├─ 所有核都到达某一点后才继续？（全核屏障）
│   │   └─ SyncAll()                                    → §4.2
│   ├─ 核 A 完成后核 B 才能开始？（点对点依赖）
│   │   └─ IBSet/IBWait                                 → §4.1
│   ├─ 核按编号严格顺序执行？（确定性计算）
│   │   └─ InitDetermineComputeWorkspace +
│   │      WaitPreBlock/NotifyNextBlock                 → §4.3
│   └─ 分离模式（AIC/AIV 交叉）？
│       └─ CrossCoreSetFlag/CrossCoreWaitFlag           → §4.4
│
└─ SuperKernel 子 Kernel 之间？
    └─ SetNextTaskStart / WaitPreTaskEnd                → §5
```

## 3. 核内同步模式

### 3.1 单流水同步 — PipeBarrier

**适用场景**: 同一流水线内两条指令操作同一块 Local Memory（如 Add 的输出作为 Mul 的输入）。

**函数原型**:
```cpp
template <pipe_t pipe>
void PipeBarrier();
```

**代码模板**:
```cpp
AscendC::Add(dst0Local, src0Local, src1Local, 512);
AscendC::PipeBarrier<PIPE_V>();           // 保证 Add 完成后 Mul 才执行
AscendC::Mul(dst1Local, dst0Local, src2Local, 512);
```

**关键说明**:
- `pipe` 参数: PIPE_V, PIPE_MTE2, PIPE_MTE3, PIPE_M 等。传 `PIPE_ALL` 阻塞所有流水
- **禁止** `PipeBarrier<PIPE_S>()` — Scalar 流水间同步由硬件自动保证，调用会引发硬件错误
- 开启自动同步时，PIPE_V 内部的同步由编译器自动插入，开发者通常无需手动添加
- PIPE_MTE2/PIPE_MTE3 搬运地址重叠时**需要手动插入**

**芯片支持**: Atlas A3/A2/200I 均支持（Vector Core 不支持）

> 详细参数: `api_reference_docs/基础API/同步控制/核内同步/PipeBarrier（ISASI）.md`

### 3.2 多流水同步 — SetFlag/WaitFlag

**适用场景**: 不同流水线间存在数据依赖（如 MTE2 搬入完成后 Vector 才能计算）。

**函数原型**:
```cpp
template <HardEvent event>
void SetFlag(int32_t eventID);

template <HardEvent event>
void WaitFlag(int32_t eventID);
```

**eventID 获取**: 必须通过 `AllocEventID` 或 `FetchEventID` 获取，**禁止自行指定**（会与框架冲突导致死锁）。

**代码模板** — S→MTE3 同步（SetValue 后搬出）:
```cpp
int32_t eventID = static_cast<int32_t>(
    GetTPipePtr()->FetchEventID(AscendC::HardEvent::S_MTE3));
AscendC::SetFlag<AscendC::HardEvent::S_MTE3>(eventID);
AscendC::WaitFlag<AscendC::HardEvent::S_MTE3>(eventID);
AscendC::DataCopy(dstGlobal, dstLocal, dataSize);
```

**HardEvent 枚举**（命名规则: `源流水_目标流水`，目标流水等待源流水）:

| 常用事件 | 含义 |
|----------|------|
| `MTE2_V` | MTE2 搬入完成后 Vector 才计算 |
| `V_MTE3` | Vector 计算完成后 MTE3 才搬出 |
| `MTE2_M` | MTE2 搬入完成后 Matrix 才计算 |
| `S_MTE3` | Scalar 写入完成后 MTE3 才搬出 |
| `S_V`    | Scalar 写入完成后 Vector 才计算 |

**eventID 范围**:
- Atlas 训练系列: 0-3
- Atlas A2/A3/推理系列 AI Core: 0-7

**关键约束**:
- SetFlag/WaitFlag **必须成对出现**
- Atlas 200I/500 A2 推理产品和 Vector Core **不支持**

> 详细参数: `api_reference_docs/基础API/同步控制/核内同步/SetFlag_WaitFlag（ISASI）.md`

### 3.3 内存屏障 — DataSyncBarrier

> ⚠️ **DataSyncBarrier 是内存屏障，不是流水间同步工具**。它等待"之前的内存访问指令执行完"（无 `源流水_目标流水` 方向），不能替代 `PipeBarrier`（单流水）/ `SetFlag`+`WaitFlag`（多流水）的流水间依赖同步。跨流水数据依赖（MTE2→V、V→MTE3 等）必须用 `PipeBarrier`/`SetFlag`+`WaitFlag`；`DataSyncBarrier` 仅用于等所有内存访问完成的内存屏障场景（如 Mmad→Fixpipe）。

**适用场景**: 需要等待所有之前的内存访问指令完成后才执行后续指令。

**函数原型**:
```cpp
template <MemDsbT arg0>
void DataSyncBarrier();
```

**MemDsbT 取值**:
- `ALL` — 等待所有内存访问指令
- `DDR` — 仅等待 GM 访问指令
- `UB` — 仅等待 UB 访问指令
- `SEQ` — 预留参数，暂未启用

**代码模板**:
```cpp
AscendC::Mmad(...);
AscendC::DataSyncBarrier<MemDsbT::ALL>();
AscendC::Fixpipe(...);
```

**芯片支持**: **仅 Atlas A2 训练/推理系列和 200I/500 A2** 支持。Atlas A3、Atlas 推理系列 AI Core、训练系列均**不支持**。

> 详细参数: `api_reference_docs/基础API/同步控制/核内同步/DataSyncBarrier（ISASI）.md`

## 4. 核间同步模式

### 4.1 IBSet/IBWait — 点对点核间同步

**适用场景**: 核 A 完成操作后核 B 才能开始（读后写/写后读/写后写依赖）。

**函数原型**:
```cpp
template <bool isAIVOnly = true>
void IBSet(const GlobalTensor<int32_t>& gmWorkspace,
           const LocalTensor<int32_t>& ubWorkspace,
           int32_t blockIdx, int32_t eventID);

template <bool isAIVOnly = true>
void IBWait(const GlobalTensor<int32_t>& gmWorkspace,
            const LocalTensor<int32_t>& ubWorkspace,
            int32_t blockIdx, int32_t eventID);
```

**代码模板** — 核 0 计算后核 1 读取核 0 的结果:
```cpp
void Process() {
    if (blockIdx == 1) {
        auto sync_buf = vecIn.AllocTensor<int32_t>();
        AscendC::IBWait(sync_gm, sync_buf, 0, 0);   // 核 1 等待核 0
        vecIn.FreeTensor(sync_buf);
    }
    CopyIn();
    Compute();
    CopyOut();
    if (blockIdx == 0) {
        auto sync_buf = vecIn.AllocTensor<int32_t>();
        AscendC::IBSet(sync_gm, sync_buf, 0, 0);    // 核 0 通知完成
        vecIn.FreeTensor(sync_buf);
    }
}
```

**Workspace 大小要求**:
- `gmWorkspace` >= 核数 * 32B * eventID_max + blockIdx_max * 32B + 32B
  - AIVOnly 模式: 核数 = GetBlockNum()
  - MIX 模式: 核数 = GetBlockNum() * 2
- `ubWorkspace` >= 32B
- `gmWorkspace` 的值**必须初始化为 0**

**芯片支持**: Atlas A3/A2/推理系列 AI Core/训练系列（200I/500 A2 和 Vector Core 不支持）

> 详细参数: `api_reference_docs/基础API/同步控制/核间同步/IBSet.md`, `核间同步/IBWait.md`

### 4.2 SyncAll — 全核屏障

**适用场景**: 所有核都完成当前阶段后才能进入下一阶段（如多核累加）。

**函数原型**:
```cpp
// 软同步
template <bool isAIVOnly = true>
void SyncAll(const GlobalTensor<int32_t>& gmWorkspace,
             const LocalTensor<int32_t>& ubWorkspace,
             const int32_t usedCores = 0);

// 硬同步（仅 A2/A3）
template <bool isAIVOnly = true>
void SyncAll();
```

**代码模板** — 多核累加:
```cpp
// 各核先完成自己的计算
FirstCompute();
CopyToWorkGlobal();

// 全核同步：等待所有核完成计算
LocalTensor<int32_t> workLocal = workQueue.AllocTensor<int32_t>();
AscendC::SyncAll(syncGlobal, workLocal);
workQueue.FreeTensor(workLocal);

// 同步后：每个核读取其他核的结果进行累加
for (int i = 0; i < blockNum; i++) {
    if (i != blockIdx) {
        CopyFromOtherCore(i);
        Accumulate(dstLocal);
    }
}
```

**软同步 vs 硬同步**:
| 维度 | 软同步 | 硬同步 |
|------|--------|--------|
| 需要 workspace | 是 | 否 |
| isAIVOnly=false | 不支持 | 支持（A2/A3） |
| 芯片支持 | A3/A2/推理 AI Core/训练系列 | 仅 A3/A2 |
| 分离模式建议 | 不建议（仅纯 Vector，性能低） | 推荐 |

**Workspace 大小要求**（软同步）:
- `gmWorkspace` >= 核数 * 32B，值**必须初始化为 0**
- `ubWorkspace` >= 核数 * 32B

**关键约束**:
- `usedCores` 不能超过算子调用时指定的逻辑 `blockDim`
- 分离模式下使用硬同步时需设置 Kernel 类型为 `KERNEL_TYPE_MIX_AIV_1_0` 或 `KERNEL_TYPE_MIX_AIC_1_0`

> 详细参数: `api_reference_docs/基础API/同步控制/核间同步/SyncAll.md`

### 4.3 WaitPreBlock/NotifyNextBlock — 确定性顺序执行

**适用场景**: 核按编号严格顺序执行同一操作（如确定性累加——核 0→核 1→核 2→...）。

**使用流程**:
1. 调用 `InitDetermineComputeWorkspace` 初始化共享内存
2. 在临界区前调用 `WaitPreBlock` 等待前一个核完成
3. 执行临界区操作（如原子累加）
4. 在临界区后调用 `NotifyNextBlock` 通知下一个核

**代码模板** — 确定性累加:
```cpp
void Process() {
    LocalTensor<int32_t> ubWorkspace = m_queTmp.AllocTensor<int32_t>();
    AscendC::InitDetermineComputeWorkspace(m_gmWorkspace, ubWorkspace);

    for (int64_t i = 0; i < m_tileNum; i++) {
        // Copy in
        LocalTensor<T> srcLocal = m_que.AllocTensor<T>();
        AscendC::DataCopy(srcLocal, m_srcGlobal[i * m_tileCount], m_tileCount);

        // 等待前一个核完成
        AscendC::WaitPreBlock(m_gmWorkspace, ubWorkspace);
        AscendC::SetAtomicAdd<T>();
        AscendC::DataCopy(m_dstGlobal[i * m_tileCount], srcLocal, m_tileCount);
        AscendC::SetAtomicNone();
        // 通知下一个核
        AscendC::NotifyNextBlock(m_gmWorkspace, ubWorkspace);

        m_que.FreeTensor(srcLocal);
    }
    m_queTmp.FreeTensor(ubWorkspace);
}
```

**Workspace 大小要求**:
- `gmWorkspace` >= blockNum * 32B
- `ubWorkspace` >= blockNum * 32 + 32B

**关键约束**:
- 每个核调用 WaitPreBlock 和 NotifyNextBlock 的**次数必须相同**
- 分离模式下仅对 AIV 核生效，WaitPreBlock 和 NotifyNextBlock 之间仅支持矢量计算指令
- **芯片限制**: 仅 Atlas A2 训练/推理系列和推理系列 AI Core 支持。**A3 不支持**

> 详细参数: `api_reference_docs/基础API/同步控制/核间同步/InitDetermineComputeWorkspace.md`, `核间同步/WaitPreBlock.md`, `核间同步/NotifyNextBlock.md`

### 4.4 CrossCoreSetFlag/CrossCoreWaitFlag — 分离模式核间同步

**适用场景**: 分离模式下 AIC 与 AIV 之间、AIV 与 AIV 之间、AIC 与 AIC 之间的同步。

**函数原型**:
```cpp
template <uint8_t modeId, pipe_t pipe>
void CrossCoreSetFlag(uint16_t flagId);

template <uint8_t modeId = 0, pipe_t pipe = PIPE_S>
void CrossCoreWaitFlag(uint16_t flagId);
```

**三种同步模式**:

| modeId | 模式 | 说明 |
|--------|------|------|
| 0 | AI Core 核间 | AIC 场景同步所有 AIC 核；AIV 场景同步所有 AIV 核 |
| 1 | AIV 核内 | 同一 AI Core 内的两个 AIV 子核之间同步 |
| 2 | AIC↔AIV | AIC 核与 AIV 核之间的交叉同步 |

**代码模板** — AIC 完成 Matmul 后通知 AIV 做后处理:
```cpp
// AIC 侧
if (g_coreType == AscendC::AIC) {
    // Matmul 计算...
    AscendC::CrossCoreSetFlag<0x2, PIPE_FIX>(0x8);
}

// AIV 侧
if (g_coreType == AscendC::AIV) {
    AscendC::CrossCoreWaitFlag(0x8);  // 等待 AIC 完成
    // Vector 后处理...
}
```

**关键约束**:
- 同一 `flagId` 的计数器**最多设置 15 次**
- `flagId` 取值范围: 0-10（A2 和 A3）
- 需设置 Kernel 类型: `KERNEL_TYPE_MIX_AIV_1_0` 或 `KERNEL_TYPE_MIX_AIC_1_0`
- **不建议与 Matmul 高阶 API 同时使用**（flagID 冲突风险）
- **芯片限制**: 仅 Atlas A2/A3 训练/推理系列支持。推理系列 AI Core、Vector Core、训练系列均**不支持**

> 详细参数: `api_reference_docs/基础API/同步控制/核间同步/CrossCoreSetFlag（ISASI）.md`, `核间同步/CrossCoreWaitFlag（ISASI）.md`

## 5. 任务间同步（SuperKernel）

**适用场景**: SuperKernel 二进制融合场景下，子 Kernel 之间的并行优化。

### SetNextTaskStart

在子 Kernel 尾部调用，允许后续指令与下一个子 Kernel 并行执行。

```cpp
template <pipe_t AIV_PIPE = PIPE_MTE3, pipe_t AIC_PIPE = PIPE_FIX>
void SetNextTaskStart();
```

**推荐位置**: 算子最后一条搬运指令后调用。

```cpp
void CopyOut() {
    LocalTensor<half> dstLocal = outQueueDst.DeQue<half>();
    AscendC::DataCopy(dstGlobal, dstLocal, 512);
    AscendC::SetNextTaskStart();  // 最后一条搬运后插入
    outQueueDst.FreeTensor(dstLocal);
}
```

### WaitPreTaskEnd

在子 Kernel 头部调用，允许调用前的指令与前一个子 Kernel 并行执行。

```cpp
void WaitPreTaskEnd();
```

**推荐位置**: 算子第一条搬运指令前调用。

```cpp
void CopyIn() {
    LocalTensor<half> src0Local = inQueueSrc0.AllocTensor<half>();
    AscendC::WaitPreTaskEnd();  // 第一条搬运前插入
    AscendC::DataCopy(src0Local, src0Global, 512);
    ...
}
```

**关键约束**:
- 仅 **Atlas A3** 上功能生效，其他芯片仅编译兼容
- 需启用 SuperKernel 特性（TorchAir 图模式）
- 每个核上**仅能调用一次**
- 若某 TilingKey 分支调用了此接口，则**所有可能运行的 TilingKey 分支都必须调用**，否则同步指令不匹配导致卡死

> 详细参数: `api_reference_docs/基础API/同步控制/任务间同步/SetNextTaskStart.md`, `任务间同步/WaitPreTaskEnd.md`

## 6. 芯片兼容性速查表

| API | Atlas A3 | Atlas A2 | 200I/500 A2 | 推理 AI Core | 推理 Vector Core | 训练系列 |
|-----|----------|----------|-------------|-------------|------------------|----------|
| PipeBarrier | Y | Y | Y | Y | N | Y |
| SetFlag/WaitFlag | Y | Y | N | Y | N | Y |
| DataSyncBarrier | N | Y | Y | N | N | N |
| IBSet/IBWait | Y | Y | N | Y | N | Y |
| SyncAll（软同步） | Y | Y | N | Y | N | Y |
| SyncAll（硬同步） | Y | Y | N | N | N | N |
| InitDetermineComputeWorkspace | N | Y | N | Y | N | N |
| WaitPreBlock/NotifyNextBlock | N | Y | N | Y | N | N |
| CrossCoreSetFlag/WaitFlag | Y | Y | N | N | N | N |
| SetNextTaskStart* | Y | 编译兼容 | 编译兼容 | 编译兼容 | 编译兼容 | 编译兼容 |
| WaitPreTaskEnd* | Y | 编译兼容 | 编译兼容 | 编译兼容 | 编译兼容 | 编译兼容 |

> *: 仅 Atlas A3 上功能实际生效

## 7. 常见陷阱与调试

> 详细内容见 `references/common-pitfalls.md`，以下为速查摘要。

| # | 陷阱 | 关键点 |
|---|------|--------|
| 1 | eventID 手动指定 | 必须用 `FetchEventID`/`AllocEventID`，禁止硬编码 |
| 2 | SetFlag/WaitFlag 不成对 | 遗漏任一方导致永久阻塞 |
| 3 | SyncAll workspace 未初始化为 0 | gmWorkspace 值必须初始化为 0 |
| 4 | blockDim 超过实际核数 | 框架多轮调度会插入异常同步致卡死 |
| 5 | WaitPreBlock/NotifyNextBlock 次数不一致 | 每个核调用次数必须相同 |
| 6 | CrossCore flagId 溢出 | 同一 flagId 最多设置 15 次 |
| 7 | 分离模式用软 SyncAll | 应使用硬同步 + MIX Kernel 类型 |
| 8 | SuperKernel TilingKey 分支不一致 | 所有分支都必须调用同步接口 |
| 9 | CrossCore 与 Matmul 高阶 API 冲突 | flagID 冲突风险 |
