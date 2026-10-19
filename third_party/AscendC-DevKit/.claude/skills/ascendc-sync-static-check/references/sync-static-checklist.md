# 核内同步静态检查清单（完整版）

> 本清单是 ascendc-sync-static-check skill 的核心知识库。
> 覆盖 7 类核内同步缺陷的静态检查，按"致命→高危→可疑"优先级组织。
> 标注 ⚠️ 的是**会导致全0/卡死/数据竞争**的硬约束。
> **仅覆盖核内同步；核间同步（SyncAll/IBSet/CrossCoreFlag）不在本清单范围**。

---

## 0. 核心原理（必须先理解）

### 0.1 AI Core 并行流水模型

```
AI Core 内部并行流水
├── Scalar (PIPE_S) ──── 标量计算、Tensor GetValue/SetValue
├── Vector (PIPE_V) ──── 矢量计算
├── Matrix (PIPE_M) ──── 矩阵计算
├── DMA 搬入 (PIPE_MTE2) ── GM→UB / GM→L1
├── DMA 搬出 (PIPE_MTE3) ── UB→GM
├── L1↔L0 (PIPE_MTE1)
└── L0C→GM (PIPE_FIX)
```

### 0.2 自动同步 vs 手动同步边界

| 场景 | 谁负责 | 备注 |
|------|--------|------|
| PIPE_V 内部（同流水） | **编译器自动** | 开启自动同步时 |
| MTE2/MTE3 地址**无重叠** | **框架自动** | |
| MTE2/MTE3 地址**有重叠** | **⚠️ 开发者手动** | 必须插入同步 |
| PIPE_V / MTE2 / MTE3 / S 之间多流水 | **框架自动**（TQue EnQue/DeQue） | |
| 原子操作 Scalar ↔ MTE2/MTE3 的 GM 依赖 | **⚠️ 开发者手动** | AtomicAdd 等例外 |
| Cube 侧所有同步 | **框架自动** | 开发者无需介入 |

> **关键认知**：使用 TQue + EnQue/DeQue 编程模型时，框架自动处理同步。开发者**绕过框架**（手动 SetFlag/WaitFlag、直接 DataCopy 后 Compute、用 TBuf 搬运、GetValue/SetValue 跨流水）时才需要手动同步——而**这正是出 Bug 的地方**。

### 0.3 TQue 同步原理（EnQue/DeQue/Alloc 的实质）⭐

`EnQue`/`DeQue` 不是"魔法同步"，而是框架替开发者插入了对应的 HardEvent flag。

| 操作 | 实质插入的同步 | 语义 |
|------|--------------|------|
| 输入队列 `EnQue`（VECIN） | `MTE2_V` | V 流水等待 MTE2 把数据从 GM 搬到 UB 完成 |
| 输出队列 `EnQue`（VECOUT） | `V_MTE3` | MTE3 流水等待 V 把计算结果写完，再搬到 GM |
| `AllocTensor`（输入 buffer） | `V_MTE2`（FreeTensor 的反向） | alloc 等待上一轮 V 流水用完该 buffer 并 FreeTensor 释放 |

**关键推论**：
1. **AllocTensor 是 FreeTensor 的反向同步**：对输入 buffer，alloc 隐含"等上一轮 V 计算完释放"。这是 double buffer 轮替的基础——如果漏了 FreeTensor 或顺序错乱，alloc 会拿到未释放的脏 buffer。
2. **GetValue/SetValue 属于 Scalar(PIPE_S) 流水**，跨流水时同样需要 flag：
   - `GetValue`（从 UB 取值到标量）：需 `MTE2_S`（S 等 MTE2 搬入完成）
   - `SetValue`（标量写入 UB）：需 `S_MTE3`（MTE3 等 S 写完才能搬出）
3. **TBuf 本身没有同步**：TBuf（TBuffer）没有 EnQue/DeQue 机制。纯 V_V 计算时编译器能保证同流水顺序；但一旦用 TBuf 做 DataCopy 搬入/搬出（跨到 MTE2/MTE3），**必须手动补 SetFlag/WaitFlag**，否则读脏数据。

### 0.4 PIPE_ALL 的掩盖效应（调试陷阱）⚠️

`PipeBarrier<PIPE_ALL>()` 常被用作"临时调试同步问题"的手段，但它有一个**严重的副作用**：会导致 double buffer 失效。

**原理**：double buffer 的 UB 布局为 `(in0 | in1 | out0 | out1)` 四块空间。PIPE_ALL 强制全流水串行化，double buffer 退化为单 buffer，布局变为 `(in0 | out0)`。

**后果**：
- 原本 in0 越界到相邻 in1 的 bug，因 in1 消失而被**掩盖**
- 即"加 PIPE_ALL 后结果变对"有两种可能：
  - ① 同步问题确实被修复
  - ② 越界/相邻 buffer 数据竞争被掩盖（bug 仍在，只是不再触发）
- 这两种情况必须区分，否则修复是假修复

**调试建议**：用 PIPE_ALL 验证同步假设后，若改用 EnQue/DeQue 或定向 SetFlag 修复，需**再次验证**（移除 PIPE_ALL 后仍正确），以排除掩盖效应。

### 0.5 SetFlag/WaitFlag 核心语义（借鉴自 sync-incore-debug）

> 以下知识点借鉴自 ascendc-sync-incore-debug，已内化为本清单自有内容。

**SET + WAIT = 流水线屏障（Pipeline Barrier），不是简单计数！**

```cpp
SetFlag<HardEvent::V_MTE3>(event);
WaitFlag<HardEvent::V_MTE3>(event);
// 真正的含义：后面的 MTE3 操作必须等待前面的 V 操作全部完成
```

- `SetFlag`：标记"前面的操作已完成"
- `WaitFlag`：阻塞等待这个标记
- 执行完后，状态回到 UNSET，**可以立即重新使用同一个 event**

**状态流转**：
```
          SetFlag()              WaitFlag()
[UNSET] ─────────────► [SET] ─────────────────► [UNSET]
                              │
                              └──→ 此时执行后续操作
```

**关键理解**：
- SET 被 WAIT 消费后，状态立即回到 UNSET
- 同一个 event ID 可以在循环中反复使用：SET→WAIT→SET→WAIT→...
- **不同 HardEvent 类型是独立的同步通道**，Set/Wait 的 HardEvent 类型必须相同才能配对

**死锁条件**：

| 条件 | 说明 |
|------|------|
| SET→SET（无 WAIT 消费） | 信号堆积，可能导致后续行为异常 |
| UNSET→WAIT（无 SET 来源） | 等待永远不会到来的信号 — **立即死锁** |
| SET→WAIT（正常） | ✅ 正确的同步点用法 |
| 类型不匹配的 SET/WAIT | ❌ 不同 HardEvent 类型不能配对 |

**两种标准同步模式**：

模式一：流水线屏障模式
```cpp
SetFlag<HardEvent::MTE2_V>(event);   // MTE2 标记"数据已准备好"
WaitFlag<HardEvent::MTE2_V>(event);  // V 等待数据就绪
// V 操作...
```

模式二：反向同步模式（PingPong 双缓冲常用）
```cpp
// 初始化：SET 一次，确保第一次 WAIT 不阻塞
SetFlag<HardEvent::MTE3_MTE2>(event);
for (iter) {
    WaitFlag<HardEvent::MTE3_MTE2>(event);    // 等待上一次操作完成
    操作...                                     // 独占资源执行
    SetFlag<HardEvent::MTE3_MTE2>(event);     // 标记本次完成
}
WaitFlag<HardEvent::MTE3_MTE2>(event);        // 收尾消费最后一次 SET
```

---

## 1. 检查类别总表

| 类别 | 优先级 | 核心关注 | 检查项数 |
|------|--------|---------|---------|
| A | 致命 | EnQue/DeQue 配对（编程模型层） | 6 |
| B | 致命/高危 | 手动 SetFlag/WaitFlag（含 eventID 资源） | 6 |
| C | 高危 | MTE2/MTE3 地址重叠 | 3 |
| D | 高危 | PipeBarrier 使用 | 2 |
| E | 高危 | Mutex 使用 | 3 |
| G | 致命 | Scalar 流水（GetValue/SetValue） | 3 |
| H | 致命 | TBuf 无同步容器 | 3 |
| I | 致命 | TBuf 跨流水搬运同步 | 3 |

---

## A. EnQue/DeQue 配对（致命，最高优先级）

> 底层原理见 §0.3。这是输出全0/随机错误的头号根因。

### A1：DataCopy 后 Compute 前缺少 EnQue/DeQue

**违反后果**：读脏数据 → 输出全0/随机 ⚠️

**检查方法**：搜索 `DataCopy`，检查后续是否有 EnQue/DeQue。

**错误模式**：
```cpp
// ❌ DataCopy 后直接计算，无同步
LocalTensor<T> x = inQueue.AllocTensor<T>();
DataCopy(x, xGm, count);
Cast<half, int8_t>(xHalf, x, ...);  // ⛔️ 数据可能未就绪
```

**正确模式**：
```cpp
// ✅ EnQue/DeQue 保证数据就绪
void CopyIn() {
    LocalTensor<T> x = inQueue.AllocTensor<T>();
    DataCopy(x, xGm, count);
    inQueue.EnQue(x);               // 通知：MTE2_V，数据可读
}
void Compute() {
    LocalTensor<T> x = inQueue.DeQue<T>();  // 等待搬入完成
    Cast<half, int8_t>(xHalf, x, ...);
    inQueue.FreeTensor(x);
}
```

### A2：AllocTensor 后直接使用（未经 DeQue）

**违反后果**：同 A1 ⚠️

**检查方法**：搜索 `AllocTensor`，检查后续路径是否有 DeQue。

### A3：DataCopy → 直接 Compute（无同步）

**违反后果**：同 A1 ⚠️

**检查方法**：正则匹配 `DataCopy.*\n.*(Add|Mul|Cast|Sub|Div|...)`，中间无 EnQue/DeQue。

### A4：用 PipeBarrier 临时调试但未替换为 EnQue/DeQue

**违反后果**：性能差、非正式修复；PIPE_ALL 有掩盖效应（§0.4）

**检查方法**：搜索 `PipeBarrier`，确认是否为正式代码（非 debug 残留）。

### A5：FreeTensor 在 DeQue 之前（提前释放）

**违反后果**：UB 复用 → 数据错乱（间歇性错误）

**检查方法**：搜索 `FreeTensor`，检查前面是否有 DeQue。

```cpp
// ❌ 提前释放
LocalTensor<T> x = inQueue.DeQue<T>();
inQueue.FreeTensor(x);    // ⛔️ 还在用就释放
Compute(x);

// ✅ 用完再释放
LocalTensor<T> x = inQueue.DeQue<T>();
Compute(x);
inQueue.FreeTensor(x);
```

### A6：AllocTensor 与 FreeTensor 不配对

**违反后果**：漏 FreeTensor → V_MTE2 反向同步错乱 → double buffer 轮替失败 → 间歇性脏数据 ⚠️

**检查方法**：统计每个 TQue 的 alloc/free 配对数。

### 快速验证模板（供修复建议引用）

临时加 `PipeBarrier<PIPE_ALL>()`，若结果正确**提示可能是同步问题**——但需注意 §0.4 掩盖效应：加 PIPE_ALL 后正确也可能是相邻 buffer 越界被掩盖，定向修复后必须移除再次验证。

---

## B. 手动 SetFlag/WaitFlag（致命/高危）

> 核心语义（SET+WAIT=屏障、状态流转、两种标准模式）见 §0.5。

### B1：SetFlag 与 WaitFlag 不成对

**违反后果**：死锁或同步失效 ⚠️

**检查方法**：按 HardEvent 类型分组，统计同 eventID 的 Set/Wait 配对。

**注意**：不是机械计数！需理解每条执行路径（含条件分支、提前 return）。SET→SET（无 WAIT 消费）会信号堆积；UNSET→WAIT（无 SET 来源）会立即死锁。

### B2：eventID 硬编码（禁止自指定）⚠️

**违反后果**：与框架 TQue 自动分配的 eventID 冲突 → 信号错乱 / 卡死 ⚠️

**强制规则**：手动 `SetFlag`/`WaitFlag` **禁止使用硬编码 eventID 字面量**（如 `0`, `1`, `2`...）。必须通过 `GetTPipePtr()->FetchEventID()` 获取。

**检查方法**：搜索 `SetFlag<` 和 `WaitFlag<`，若其 eventID 参数为整数字面量（非函数返回值）→ CRITICAL。

**正确 API**：
```cpp
// ❌ 硬编码 eventID — CRITICAL，与框架冲突
SetFlag<HardEvent::MTE2_V>(0);
WaitFlag<HardEvent::MTE2_V>(0);

// ✅ FetchEventID 获取
int32_t eid = static_cast<int32_t>(
    GetTPipePtr()->FetchEventID(AscendC::HardEvent::MTE2_V));
SetFlag<HardEvent::MTE2_V>(eid);
WaitFlag<HardEvent::MTE2_V>(eid);
```

**注意**：`FetchEventID`（不是 `AllocEventID`）是正确的 API。同一对 Set/Wait 使用同一个 FetchEventID 返回值。

### B3：静态 Tensor 场景 eventID 误用 6/7

**违反后果**：未定义行为

**检查方法**：静态 Tensor 编程场景中，检查 eventID 字面量是否为 6 或 7。

### B4：HardEvent 方向与数据流不一致

**违反后果**：同步失效或死锁 ⚠️

**检查方法**：观察 SetFlag 前后的操作类型，验证 HardEvent 语义匹配。

**HardEvent 命名规则**：`TRIGGER_WAITER`，表示 TRIGGER 完成后通知 WAITER。

**操作类型→流水线对照表**：

| 操作类型 | 典型 API | 所属流水线 |
|---------|---------|-----------|
| 数据搬入 (GM → UB) | `DataCopy`, `DataCopyPad` | MTE2 |
| 数据搬出 (UB → GM) | `DataCopy`, `DataCopyPad` | MTE3 |
| 向量计算 | `Add`, `Mul`, `Cast`, `Muls`, `Sub` | V |
| 矩阵计算 | `MatMul`, `MMAD` | M (Cube) |
| 标量操作 | `GetValue`, `SetValue`, 标量运算 | S |

**方向判断法**：
```
数据流: GM --MTE2--> UB --V--> UB --MTE3--> GM
对应同步:
  DataCopy(gm→ub) 后要 Compute → SetFlag<MTE2_V>  (V 等 MTE2)
  Compute 后要 DataCopy(ub→gm)    → SetFlag<V_MTE3>  (MTE3 等 V)
  SetValue 后要 DataCopy           → SetFlag<S_MTE3>  (MTE3 等 S)
```

**错误示例**：
```cpp
// ✗ 错误：DataCopyPad 是 MTE2 操作，却用了 V_MTE3
DataCopyPad(ub, gm, ...);              // MTE2 操作
SetFlag<HardEvent::V_MTE3>(event);     // ✗ 应该是 MTE2_V
WaitFlag<HardEvent::V_MTE3>(event);
Add(dst, src, ...);                    // V 操作
```

### B5：TQueSync 的 src/dst 方向错误

**违反后果**：同 B4

**检查方法**：同 B4 逻辑。
```cpp
TQueSync<PIPE_MTE2, PIPE_V> sync;  // src=MTE2, dst=V，V 等 MTE2
```

### B6：eventID 资源超限（910B）⚠️

**违反后果**：同步资源耗尽 → 后续 SetFlag 失效或行为未定义

**检查方法**：统计 eventID 占用总和。

**eventID 资源约束（910B）**：
- 910B 上 eventID **同时最多 8 个**（取值 0-7）
- 每个 double buffer（`BUFFER_NUM=2`）的 TQue 会占用 **2 个** eventID
- 使用 N 个 double-buffer TQue 时，框架占用 2N 个，剩余 `8 - 2N` 个供手动 SetFlag

**检查公式**：
```
eventID_占用 = 2 × (double_buffer_TQue数量) + 手动SetFlag使用的eventID数量
若 eventID_占用 > 8 → 高危：资源超限
```

**典型资源紧张场景**：
- 3 个 double-buffer TQue 占 6 个 → 仅剩 2 个给手动同步
- 4 个 double-buffer TQue 占满 8 个 → **手动 SetFlag 无可用 eventID**

### 条件分支修复注意事项（借鉴自 sync-incore-debug）

发现条件分支内的 SetFlag 问题时，**不要直接将 SetFlag 移出 if 块**：

```cpp
// ❌ 错误做法：直接移出（虽能解决同步问题，但性能下降）
WaitFlag<HardEvent::MTE3_MTE2>(event);
if (condition) {
    // 操作
}
SetFlag<HardEvent::MTE3_MTE2>(event);  // 移出后，Wait 会等不必要的操作

// ✅ 正确做法：保持原有位置，在 else 补 SetFlag
WaitFlag<HardEvent::MTE3_MTE2>(event);
if (condition) {
    // 操作
    SetFlag<HardEvent::MTE3_MTE2>(event);
} else {
    SetFlag<HardEvent::MTE3_MTE2>(event);  // 保持同步逻辑，性能不受影响
}
```

---

## C. MTE2/MTE3 地址重叠（高危）

> 简介文档明确指出：MTE2/MTE3 地址有重叠时需开发者手动插入同步。

### C1：多个 DataCopy 目标地址重叠且无同步

**违反后果**：数据竞争 → 部分对部分错 ⚠️

**检查方法**：分析多个 DataCopy 的目标 LocalTensor 是否使用同一 buffer 区域。

### C2：PIPE_MTE2/PIPE_MTE3 间地址重叠无手动同步

**违反后果**：同 C1 ⚠️

**检查方法**：确认 MTE2 和 MTE3 操作的目标/源地址是否有重叠，若有则检查是否有 SetFlag/WaitFlag 同步。

### C3：原子操作 Scalar ↔ MTE2/MTE3 的 GM 读写无同步

**违反后果**：数据竞争 ⚠️

**检查方法**：搜索 `SetAtomicAdd`/`AtomicAdd`，检查周围 Scalar 与 DMA 的跨流水同步。

> 简介文档：「涉及标量计算的原子操作接口，如果标量计算单元和搬运单元在读写 GM 时存在数据依赖，开发者需要插入同步」。

---

## D. PipeBarrier 使用（高危）

### D1：PipeBarrier<PIPE_S>()

**违反后果**：**硬件错误** ⚠️

**检查方法**：搜索 `PipeBarrier<PIPE_S`。

> API 文档约束：「Scalar 流水之间的同步由硬件自动保证，调用 PipeBarrier<PIPE_S>() 会引发硬件错误」。

### D2：过度使用 PipeBarrier<PIPE_ALL>()

**违反后果**：double buffer 失效 + 性能劣化 + 掩盖越界（§0.4）

**检查方法**：统计 PIPE_ALL 出现次数，评估是否应改为定向 SetFlag/WaitFlag 或 EnQue/DeQue。

---

## E. Mutex 使用（高危，仅 Atlas 350 支持）

### E1：Lock/Unlock 不配对或 pipe 不一致

**违反后果**：死锁 ⚠️

**检查方法**：检查同 MutexID 的 Lock/Unlock 配对，且 pipe 模板参数相同。

> API 文档约束：「对于同一个 MutexID，必须按照 Lock/Unlock 配套使用，且指定的 pipe 也需相同」。

### E2：自定义 MutexID 时同时使用 TQue

**违反后果**：**禁止混用**，未定义行为 ⚠️

**检查方法**：检查同文件是否同时出现自定义 MutexID（字面量）和 TQue/TQueBind/TBufPool。

> API 文档约束：「用户在使用 Lock/Unlock 且自定义 MutexID 情况时，禁止同时使用 TQue、TQueBind、TBufPool 中的相关接口」。

### E3：AllocMutexID 后无 ReleaseMutexID

**违反后果**：MutexID 耗尽

**检查方法**：检查 AllocMutexID/ReleaseMutexID 配对。

---

## G. Scalar 流水同步（GetValue/SetValue）⭐

> GetValue/SetValue 操作的是 PIPE_S（标量）流水，与 MTE2/MTE3/V 跨流水时框架**不自动同步**。原理见 §0.3。

### G1：GetValue 前缺少 MTE2_S 同步

**违反后果**：读到未搬入的脏数据/旧值 ⚠️

**检查方法**：搜索 `GetValue`，检查其数据来源 LocalTensor 是否有 `MTE2_S` 同步或等价的 EnQue/DeQue。

```cpp
// ❌ GetValue 读 UB 前 MTE2 未完成
DataCopy(xLocal, xGm, size);
int32_t val = xLocal.GetValue(0);  // ⛔️ MTE2 可能未搬完

// ✅ 同步后读取
DataCopy(xLocal, xGm, size);
SetFlag<HardEvent::MTE2_S>(eid);
WaitFlag<HardEvent::MTE2_S>(eid);
int32_t val = xLocal.GetValue(0);
```

### G2：SetValue 后搬出缺少 S_MTE3 同步

**违反后果**：搬出未写入/半写入数据 ⚠️

**检查方法**：搜索 `SetValue`，检查后续 DataCopy 前是否有 `S_MTE3` 同步。

```cpp
// ❌ SetValue 后直接搬出
dstLocal.SetValue(0, 0);
DataCopy(dstGlobal, dstLocal, dataSize);  // ⛔️ S 可能未写完

// ✅ 同步后搬出（SetFlag 文档示例）
dstLocal.SetValue(0, 0);
SetFlag<HardEvent::S_MTE3>(eid);
WaitFlag<HardEvent::S_MTE3>(eid);
DataCopy(dstGlobal, dstLocal, dataSize);
```

### G3：SetValue 写入的 tensor 同时被 V 读取

**违反后果**：数据竞争 ⚠️

**检查方法**：分析 SetValue 的目标 LocalTensor 是否被后续 Compute 读取，若有则需 `S_V` 同步。

---

## H. TBuf 无同步容器 ⭐

> TBuf（TBuffer）**没有 EnQue/DeQue 机制**，框架不提供任何自动同步。原理见 §0.3。

### H1：TBuf DataCopy 搬入后直接 V 计算无同步

**违反后果**：读脏数据 → 全0/随机 ⚠️

**检查方法**：搜索 TBuf 相关的 `DataCopy`，检查后续 Compute 前是否有 SetFlag<MTE2_V>/WaitFlag。

```cpp
// ❌ TBuf 搬入后直接计算
TBuf<QuePosition::VECIN> tBuf;
LocalTensor<T> x = tBuf.Get<T>();
DataCopy(x, xGm, size);
Add(dst, x, ...);  // ⛔️ TBuf 无自动同步，数据可能未就绪

// ✅ 手动补同步
TBuf<QuePosition::VECIN> tBuf;
LocalTensor<T> x = tBuf.Get<T>();
DataCopy(x, xGm, size);
SetFlag<HardEvent::MTE2_V>(eid);
WaitFlag<HardEvent::MTE2_V>(eid);
Add(dst, x, ...);
```

### H2：TBuf DataCopy 搬出前无 V_MTE3 同步

**违反后果**：搬出未完成计算的数据 ⚠️

**检查方法**：搜索 TBuf 的 `DataCopy(., gm, .)`，检查前面 Compute 后是否有 SetFlag<V_MTE3>/WaitFlag。

### H3：TBuf buffer 被 MTE2 和 V 同时访问无同步

**违反后果**：数据竞争 ⚠️

**检查方法**：分析 TBuf 的 Get<T>() 返回 tensor 的读写者。

### TBuf vs TQue 对照

| 容器 | 自动同步范围 | 搬入搬出时 |
|------|------------|-----------|
| TQue（VECIN/VECOUT） | EnQue/DeQue 自动管 MTE2_V / V_MTE3 | 框架自动 |
| TBuf（TBuffer） | **无** | **必须手动 SetFlag/WaitFlag** |

---

## I. TBuf (VECCALC) 跨流水搬运同步 ⭐

> TBuf 使用 `TPosition::VECCALC`，**无 EnQue/DeQue 机制**，框架不提供任何自动同步。
> 一旦 TBuf 通过 DataCopy/DataCopyPad 参与 GM↔UB 搬运（跨到 MTE2/MTE3 流水），**所有同步必须手动**。
>
> **原则：尽可能不用 TBuf 参与 GM 搬运。**
> 能用 TQue(VECIN/VECOUT) + EnQue/DeQue 自动同步的场景，不要用 TBuf 手动 SetFlag/WaitFlag。
> TBuf 只应用于纯 VECCALC 场景（中间临时 buffer，不接触 GM）。

### I1：TBuf 搬入后缺 MTE2_V 同步

**违反后果**：读脏数据 → 全0/随机 ⚠️

**检查方法**：搜索 TBuf 相关的 `DataCopy`/`DataCopyPad`（GM→UB），检查后续 V 计算（Mul/Add/Cast）前是否有 `SetFlag<MTE2_V>/WaitFlag<MTE2_V>`。

```cpp
// ❌ TBuf 搬入后直接计算
TBuf<TPosition::VECCALC> tBuf;
LocalTensor<T> x = tBuf.Get<T>();
DataCopy(x, xGm, size);           // MTE2 搬入，异步
Add(dst, x, ...);                 // ⛔️ 数据可能未就绪

// ✅ 手动补 MTE2_V
TBuf<TPosition::VECCALC> tBuf;
LocalTensor<T> x = tBuf.Get<T>();
DataCopy(x, xGm, size);
int32_t eid = GetTPipePtr()->FetchEventID(HardEvent::MTE2_V);
SetFlag<HardEvent::MTE2_V>(eid);
WaitFlag<HardEvent::MTE2_V>(eid);
Add(dst, x, ...);
```

### I2：TBuf 循环中计算后搬出缺 V_MTE2 同步

**违反后果**：搬出未完成计算的数据（V 还在写，MTE 就开始读） ⚠️

**检查方法**：循环体内，TBuf 被 V 指令（Add/Mul/Cast）写入后、再次被 DataCopy 搬到 GM 前，检查是否有 `SetFlag<V_MTE2>/WaitFlag<V_MTE2>`。

> **注意是 V_MTE2 不是 V_MTE3**：MTE2 同时负责 GM→UB 和 UB→GM 两个方向的数据搬运。V 计算完成后，后续的 DataCopy(UB→GM) 走 MTE2 流水，所以用 `V_MTE2`（MTE2 等 V 写完）。

```cpp
// ❌ 循环中计算后直接搬出
for (int i = 0; i < N; ++i) {
    Mul(outLocal, x, y, count);    // V 写入 outLocal
    DataCopy(outGm, outLocal, s);  // ⛔️ V 可能未写完
}

// ✅ 补 V_MTE2
for (int i = 0; i < N; ++i) {
    Mul(outLocal, x, y, count);    // V 写入
    int32_t eid = GetTPipePtr()->FetchEventID(HardEvent::V_MTE2);
    SetFlag<HardEvent::V_MTE2>(eid);
    WaitFlag<HardEvent::V_MTE2>(eid);
    DataCopy(outGm, outLocal, s);  // 等 V 写完再搬
}
```

### I3：循环中计算→搬运→计算 — 两个同步缺一不可 ⚠️

**违反后果**：数据竞争 / 间歇性脏数据 / 结果随机 ⚠️

TBuf 在循环中参与 DataCopy（MTE2）和 V 计算交替时，**每个迭代需要两个同步点**，即使只有一个 DataCopy：

| 同步点 | 位置 | HardEvent | 语义 |
|--------|------|-----------|------|
| ① 算完搬 | DataCopy 之前 | `V_MTE2` | MTE2 等上一轮 V 算完，不读脏数据 |
| ② 搬完算 | DataCopy 之后、V 计算之前 | `MTE2_V` | V 等 MTE2 把数据搬进 UB |

**检查方法**：循环体内 TBuf 有 DataCopy 与 V 计算交替时，检查 DataCopy 前后是否各有一对 SetFlag/WaitFlag。缺任意一个 → CRITICAL。

```cpp
// ✅ 标准模式：算完搬(V_MTE2) → DataCopy → 搬完算(MTE2_V) → 计算
// FetchEventID 放在循环内，每次迭代动态获取，SetFlag→WaitFlag 消费后自动回收，
// 比循环外一次获取 + 复用整个循环更节省 eventID 资源。
for (int64_t core = 1; core < sCoreNum_; ++core) {
    int32_t eidV2M = static_cast<int32_t>(
        GetTPipePtr()->FetchEventID(AscendC::HardEvent::V_MTE2));
    AscendC::SetFlag<AscendC::HardEvent::V_MTE2>(eidV2M);  // ─┐ ① 算完搬
    AscendC::WaitFlag<AscendC::HardEvent::V_MTE2>(eidV2M); // ─┘

    DataCopyPad(tempBuf, workspaceGm_[core * slotElems], ...);  // MTE2 搬入

    int32_t eidM2V = static_cast<int32_t>(
        GetTPipePtr()->FetchEventID(AscendC::HardEvent::MTE2_V));
    AscendC::SetFlag<AscendC::HardEvent::MTE2_V>(eidM2V);  // ─┐ ② 搬完算
    AscendC::WaitFlag<AscendC::HardEvent::MTE2_V>(eidM2V); // ─┘

    Add(reduceBuf, reduceBuf, tempBuf, ...);     // V 计算
}
```

---


## 附：搜索关键词速查

```bash
# A类 EnQue/DeQue
grep -n "EnQue\|DeQue\|AllocTensor\|FreeTensor\|DataCopy\|DataCopyPad" op_kernel/*.h

# B类 手动同步
grep -n "SetFlag\|WaitFlag\|TQueSync\|HardEvent\|FetchEventID\|AllocEventID" op_kernel/*.h

# C类 地址重叠/原子操作
grep -n "SetAtomicAdd\|AtomicAdd\|SetAtomic" op_kernel/*.h

# D类 PipeBarrier
grep -n "PipeBarrier\|PIPE_S\|PIPE_ALL" op_kernel/*.h

# E类 Mutex
grep -n "Mutex\|Lock\|Unlock\|AllocMutexID\|ReleaseMutexID" op_kernel/*.h

# G类 Scalar
grep -n "GetValue\|SetValue" op_kernel/*.h

# H类 TBuf
grep -n "TBuf\|TBuffer\|Get<" op_kernel/*.h

# I类 TBuf 跨流水搬运同步
grep -n "VECCALC\|DataCopy.*TBuf\|TBuf.*DataCopy" op_kernel/*.h
```
