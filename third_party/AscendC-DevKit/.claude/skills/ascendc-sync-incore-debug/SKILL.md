---
name: ascendc-sync-incore-debug
description:
  Use when statically analyzing AscendC intra-core sync issues (SetFlag/WaitFlag/HardEvent) in a specific function
  or small code range (< 20 sync calls). Triggers on kernel hang, deadlock, "卡死", "死锁", "SetFlag", "WaitFlag",
  "HardEvent", "PingPong", "双缓冲", "流水线屏障". For cross-core sync use ascendc-sync-crosscore-debug.
---

# AscendC 核内同步问题调试

## 核心原则：流水线屏障语义（最重要！）

### ⚠️ 必须首先理解：SET + WAIT 的真正含义

**SET 紧跟 WAIT = 流水线屏障（Pipeline Barrier）**

```cpp
SetFlag<HardEvent::V_MTE3>(event);
WaitFlag<HardEvent::V_MTE3>(event);
// 真正的含义：后面的 MTE3 操作必须等待前面的 V 操作全部完成
```

**这不是简单的计数配对！这是一个同步点！**

- `SetFlag`：标记"前面的操作已完成"
- `WaitFlag`：阻塞等待这个标记
- 执行完后，状态回到 UNSET，**可以立即重新使用同一个 event**

### ⚠️ HardEvent 类型是同步语义的关键！

**HardEvent 类型决定了同步的方向和语义，必须重点关注！**

```cpp
// 标准API（不要使用算子自定义的宏！）
SetFlag<HardEvent::MTE2_V>(event);    // MTE2 → V：MTE2完成，通知V开始
WaitFlag<HardEvent::MTE2_V>(event);   // V 等待 MTE2 完成

SetFlag<HardEvent::V_MTE3>(event);    // V → MTE3：V完成，通知MTE3开始
WaitFlag<HardEvent::V_MTE3>(event);   // MTE3 等待 V 完成
```

**关键规则**：
- Set 和 Wait **必须是相同的 HardEvent 类型**才能配对
- `SetFlag<MTE2_V>` 只能与 `WaitFlag<MTE2_V>` 配对，不能与 `WaitFlag<V_MTE3>` 配对
- 不同 HardEvent 类型是**独立的同步通道**，互不干扰

### 通过上下文理解 HardEvent 语义

**分析方法**：观察 Set/Wait 前后的操作类型

```cpp
// 示例 1：MTE2_V
DataCopyPad(dst, src, ...);           // MTE2 操作（数据搬运）
SetFlag<HardEvent::MTE2_V>(event);    // 标记 MTE2 完成
WaitFlag<HardEvent::MTE2_V>(event);   // V 等待数据就绪
Cast(dst, src, ...);                  // V 操作（计算）

// 示例 2：V_MTE3
Add(dst, src, ...);                   // V 操作（计算）
SetFlag<HardEvent::V_MTE3>(event);    // 标记 V 完成
WaitFlag<HardEvent::V_MTE3>(event);   // MTE3 等待计算完成
DataCopyPad(gm, ub, ...);             // MTE3 操作（数据搬出）
```

**HardEvent 命名规则**：`TRIGGER_WAITER`，表示 TRIGGER 完成后通知 WAITER

| HardEvent 类型 | 触发方 | 等待方 | 语义 |
|----------------|--------|--------|------|
| `MTE2_V` | MTE2 | V | 数据搬运完成，可以开始计算 |
| `V_MTE3` | V | MTE3 | 计算完成，可以搬出结果 |
| `MTE3_MTE2` | MTE3 | MTE2 | 结果搬出完成，可以开始下一轮搬运 |
| `MTE2_MTE3` | MTE2 | MTE3 | 数据搬运完成，可以开始搬出 |

### 状态流转

```
         SetFlag()              WaitFlag()
[UNSET] ─────────────► [SET] ─────────────────► [UNSET]
                             │
                             └──→ 此时执行后续操作
```

**关键理解**：
- SET 被WAIT 消费后，状态立即回到 UNSET
- 同一个 event ID 可以在循环中反复使用：SET→WAIT→SET→WAIT→...
- 每次 SET+WAIT 都是独立的同步点，互不影响
- **不同 HardEvent 类型是独立的通道，可以并行使用不同的 event ID**

### 死锁条件

| 条件 | 说明 |
|------|------|
| SET→SET（无 WAIT 消费） | 多次执行信号堆积，可能导致后续行为异常 |
| UNSET→WAIT（无 SET 来源） | 等待永远不会到来的信号 — **立即死锁** |
| SET→WAIT（正常） | ✅ 正确的同步点用法 |
| 类型不匹配的 SET/WAIT | ❌ 不同 HardEvent 类型不能配对！ |

## 标准化分析流程（必须遵循）

分析 vec_op.h 等核内同步密集型文件时，必须按以下流程执行：

```
Step 1: 列出所有事件 ID（带行号和 AllocEventID 类型）
   ↓
Step 2: 按 HardEvent 类型分组（如 MTE3_MTE2、MTE2_MTE3、V_MTE3 等）
   ↓
Step 3: 逐个函数列出 Set/Wait 同步流程时序图
   ↓
Step 4: 画状态追踪表（必须！按函数分别追踪，每个函数一个表）
   ↓
Step 5: 验证每个 HardEvent 类型的 Set/Wait 数量平衡
   ↓
Step 6: 验证函数可重入性（入口 Flag 状态 = 出口 Flag 状态）
```

---

## Step 1: 列出所有事件 ID

**输出格式**：事件 ID 列表（包含分配位置和 HardEvent 类型）

```cpp
// InitUB 函数行 446-454
vWaitMte2         = AllocEventID<HardEvent::MTE2_V>();   // MTE2→V
vWaitMte2Pong     = AllocEventID<HardEvent::MTE2_V>();   // MTE2→V (Pong)
mte3WaitV         = AllocEventID<HardEvent::V_MTE3>();   // V→MTE3
mte2WaitMte3      = AllocEventID<HardEvent::MTE3_MTE2>(); // MTE3→MTE2
mte2WaitMte3Pong  = AllocEventID<HardEvent::MTE3_MTE2>(); // MTE3→MTE2 (Pong)
mte3WaitMte2      = AllocEventID<HardEvent::MTE2_MTE3>(); // MTE2→MTE3
mte3WaitMte2Pong  = AllocEventID<HardEvent::MTE2_MTE3>(); // MTE2→MTE3 (Pong)
sWaitMte2         = AllocEventID<HardEvent::MTE2_S>();    // MTE2→S
vWaitMte3         = AllocEventID<HardEvent::MTE3_V>();    // MTE3→V
```

---

## Step 2: 按 HardEvent 类型分组

**输出格式**：

| HardEvent 类型 | 事件 ID 列表 | 用途 |
|----------------|-------------|------|
| `MTE2_V` | `vWaitMte2`, `vWaitMte2Pong` | MTE2 完成通知 V |
| `MTE3_MTE2` | `mte2WaitMte3`, `mte2WaitMte3Pong` | MTE3 完成通知 MTE2 |
| `V_MTE3` | `mte3WaitV` | V 完成通知 MTE3 |
| `MTE2_MTE3` | `mte3WaitMte2`, `mte3WaitMte2Pong` | MTE2 完成通知 MTE3 |
| `MTE3_V` | `vWaitMte3` | MTE3 完成通知 V |
| `MTE2_S` | `sWaitMte2` | MTE2 完成通知 S |

---

## Step 3: 逐个函数列出同步流程时序图

**时序图格式**：使用 ASCII 艺术展示 MTE2/V/MTE3 之间的同步流

**绘制规范**：
1. 每个流水线（MTE2/V/MTE3）占一行
2. 操作按时间顺序从左到右排列
3. 跨流水线同步用 `┬→ ↓ ─┘` 等连接符表示
4. SetFlag 和 WaitFlag 必须成对标注
5. Vector 计算操作写在 V 行上

**基本同步模式图例**：

```
// 模式 1: MTE2 → V 单向同步
MTE2: DataCopy ──→ SetFlag(X)
                          │
                          ↓
  V:  [等待] ──→ WaitFlag(X) ──→ Calc

// 模式 2: MTE2 → V → MTE3 三级流水线
MTE2: DataCopy ──→ SetFlag(A)
                          │
                          ↓
  V:  [等待] ──→ WaitFlag(A) ──→ Calc ──→ SetFlag(B)
                                                │
                                                ↓
MTE3:                                    [等待] ──→ WaitFlag(B) ──→ DataCopyOut

// 模式 3: PingPong 双缓冲
迭代 N (Ping):
MTE2: WAIT(X) → CopyIn ──→ SET(Y) ─────────┐
                              │             │
                              ↓             │
  V:  [等] → Calc ──→ SET(Z) ──→ WAIT(Z)   │
                              │             │
                              ↓             │
MTE3:                    [等] ← WAIT(Y) ←───┘
         │
         ↓ (切换 pingpongFlag)
迭代 N+1 (Pong):
MTE2: WAIT(X') → CopyIn ──→ SET(Y') ────────┐
                               │             │
                               ↓             │
  V:  [等] → Calc ──→ SET(Z') ──→ WAIT(Z')  │
                               │             │
                               ↓             │
MTE3:                   [等] ← WAIT(Y') ←────┘
```

**完整示例**：

```
函数名：CalRowsumAndSftCopyIn

MTE2: DataCopyPad(attentionGrad) ──┬→ SetFlag(vWaitMte2) ──────────→ DataCopyPad(max/sum) ──┬→ SetFlag(vWaitMte2)
                                   │                                                        │
                                   ↓                                                        ↓
  V:  [等待] ─────────────→ WaitFlag ──→ Cast → SoftmaxGradFront ──→ [等待] ─────→ WaitFlag ──→ Brcb

函数名：DealBmm1ResBaseBlock

MTE2: Wait(V_MTE2+ping) → DataCopy ──→ SetFlag(MTE2_V) ──────────→ SetFlag(V_MTE2+ping)
                                         │
                                         ↓
  V:  [等待] ──→ WaitFlag ──→ Elewise → Softmax → AmlaVec ──→ SetFlag(V_MTE3)
                                                                 │
                                                                 ↓
MTE3:                                                   [等待] ──→ WaitFlag ──→ DataCopy ──→ SetFlag(MTE3_V)
```

---

## Step 4: 画状态追踪表（按函数组织）

**重要**：每个函数需要一个独立的追踪表，因为函数是同步的基本单位，必须保证每个函数的入口和出口 Flag 状态一致。

**⚠️ 必须包含 HardEvent 类型列！** 这是验证同步正确性的关键。

**示例：GatherKV 函数状态追踪表**

```
| 步骤 | 行号 | 操作类型 | HardEvent 类型    | 事件 ID              | Flag 变化   | 依赖来源 | 注释            |
|------|------|----------|-------------------|----------------------|-------------|----------|-----------------|
| 初始 | 690  | SET      | MTE3_MTE2         | mte2WaitMte3Pong     | →SET        | -        | 预设置 Ping     |
| 初始 | 691  | SET      | MTE3_MTE2         | mte2WaitMte3         | →SET        | -        | 预设置 Pong     |
| 1    | 716  | WAIT     | MTE3_MTE2         | mte2WaitMte3EventId  | SET→UNSET   | 初始     | 首次迭代等待    |
| 2    | 774  | SET      | MTE3_MTE2         | mte2WaitMte3EventId  | →SET        | -        | 为下次迭代准备  |
| 3    | 784  | WAIT     | MTE3_MTE2         | mte2WaitMte3EventId  | SET→UNSET   | 步骤 2   | 尾部迭代等待    |
| 4    | 803  | SET      | MTE3_MTE2         | mte2WaitMte3EventId  | →SET        | -        | 尾部 SET        |
| 5    | 810  | WAIT     | MTE3_MTE2         | mte2WaitMte3EventId  | SET→UNSET   | 步骤 4   | 剩余数据等待    |
| 6    | 823  | SET      | MTE3_MTE2         | mte2WaitMte3EventId  | →SET        | -        | 剩余数据 SET    |
| 收尾 | 827  | WAIT     | MTE3_MTE2         | mte2WaitMte3Pong     | SET→UNSET   | 初始     | 平衡初始化      |
| 收尾 | 828  | WAIT     | MTE3_MTE2         | mte2WaitMte3         | SET→UNSET   | 最后一次 | 平衡最后一次 SET |
```

**HardEvent 类型验证要点**：
- 每个 SET/WAIT 配对的 HardEvent 类型必须相同
- 如果发现同一 event ID 对应不同的 HardEvent 类型，说明分析有误或代码有问题
- HardEvent 类型与操作上下文匹配（见"通过上下文检测 HardEvent 类型错误"章节）

**平衡检查**（按 HardEvent 类型分组统计）：
- `MTE3_MTE2`: SET = 4 (初始 2 + 循环 2), Wait = 4 (循环 2 + 收尾 2) ✓
- `MTE2_MTE3`: SET = 2, Wait = 2 ✓

---

## Step 5: 验证每个 HardEvent 类型的 Set/Wait 数量平衡

**输出格式**：

| HardEvent 类型 | SET 总数 | Wait 总数 | 平衡检查 |
|----------------|----------|----------|----------|
| `MTE2_V` | 2 | 2 | ✓ |
| `MTE3_MTE2` | 4 | 4 | ✓ |
| `V_MTE3` | 1 | 1 | ✓ |

---

## Step 6: 验证函数可重入性

**输出格式**：

| 函数 | 入口 Flag 状态 | 出口 Flag 状态 | 可重入性 |
|------|---------------|---------------|----------|
| `CalRowsumAndSftCopyIn` | 全 UNSET | 全 UNSET | ✓ |
| `GatherKV` | 全 UNSET | 全 UNSET | ✓ |

## Step 7: 输出同步问题分析报告

完成所有分析步骤后，输出一份结构化的分析报告。

### 报告模板

```markdown
# 核内同步问题分析报告

## 1. 分析概要

- **分析文件**: <文件路径>
- **分析时间**: <时间戳>
- **结论**: ✅ 未发现同步问题 / ⚠️ 发现 N 个潜在问题

## 2. 事件 ID 汇总

| HardEvent 类型 | 事件 ID 数量 | 用途 |
|----------------|-------------|------|
| `MTE2_V` | 2 | MTE2 → V 同步 |
| `V_MTE3` | 1 | V → MTE3 同步 |
| ... | ... | ... |

## 3. 函数分析结果

### 3.1 函数: <函数名>

**同步模式**: 流水线屏障 / 反向同步 (PingPong) / 混合

**时序图**:
```
<MTE2/V/MTE3 时序图>
```

**状态追踪表**:

| 步骤 | 行号 | 操作 | HardEvent 类型 | 事件 ID | Flag 变化 | 状态 |
|------|------|------|----------------|---------|-----------|------|
| ... | ... | ... | ... | ... | ... | ... |

**平衡检查**:
- `MTE2_V`: SET = X, Wait = X ✓/❌
- `V_MTE3`: SET = X, Wait = X ✓/❌

**可重入性**: 入口=UNSET, 出口=UNSET ✓/❌

**HardEvent 语义检查**:
- SetFlag 前操作: <操作类型> ✓/❌
- WaitFlag 后操作: <操作类型> ✓/❌

---

## 4. 发现的问题

### 问题 1: <问题标题>

- **严重程度**: 🔴 严重 / 🟡 中等 / 🟢 轻微
- **位置**: 行 <行号>
- **问题描述**: <详细描述>
- **影响**: <可能的后果>
- **修复建议**: <具体的修复方案>

## 5. 总结

<总结分析结果，给出最终结论>
```

### 问题严重程度定义

| 级别 | 含义 | 典型问题 |
|------|------|---------|
| 🔴 严重 | 会导致死锁或数据错误 | UNSET→WAIT 无 SET 来源、HardEvent 类型错误 |
| 🟡 中等 | 可能导致偶发问题 | 信号堆积、路径不平衡 |
| 🟢 轻微 | 代码风格或潜在风险 | 冗余同步、可读性问题 |

### 常见问题报告示例

**问题 1: HardEvent 类型与操作不匹配**

```markdown
### 问题 1: HardEvent 类型与操作不匹配

- **严重程度**: 🔴 严重
- **位置**: 行 512-514
- **问题描述**:
  SetFlag 前是 MTE2 操作 (DataCopyPad)，但 HardEvent 类型为 V_MTE3
  WaitFlag 后是 V 操作 (Cast)，但 HardEvent 类型为 V_MTE3
- **影响**: 同步语义错误，可能导致数据竞争或死锁
- **修复建议**:
  将 `SetFlag<HardEvent::V_MTE3>` 改为 `SetFlag<HardEvent::MTE2_V>`
  将 `WaitFlag<HardEvent::V_MTE3>` 改为 `WaitFlag<HardEvent::MTE2_V>`
```

**问题 2: 条件分支导致信号不平衡**

```markdown
### 问题 2: 条件分支 WAIT 无 SET 来源

- **严重程度**: 🔴 严重
- **位置**: 行 810
- **问题描述**:
  当主循环走 else 分支且 curGatherSize == 0 时，进入尾部处理
  尾部处理的 WAIT(行 810) 没有对应的 SET 来源
- **影响**: 死锁
- **修复建议**:
  在尾部处理前添加 SET，或修改条件分支逻辑确保 WAIT 有 SET 来源
```

## 关键概念

### 1. 事件 ID 可重复使用

同一事件 ID 可在多次 `SetFlag + WaitFlag` 配对中重复使用，每次配对都是独立的同步点。

```cpp
// 正确：同一事件 ID 被多次使用，每次都是完整的 Set+Wait 配对
SetFlag<HardEvent::MTE2_V>(vWaitMte2);
WaitFlag<HardEvent::MTE2_V>(vWaitMte2);  // 第一次同步
// ... 更多 MTE2 操作 ...
SetFlag<HardEvent::MTE2_V>(vWaitMte2);
WaitFlag<HardEvent::MTE2_V>(vWaitMte2);  // 第二次同步
```

### 2. 连续的 SetFlag + WaitFlag = 流水线屏障

```cpp
SetFlag<HardEvent::V_MTE3>(mte3WaitV);  // 标记"V 到这里已完成"
WaitFlag<HardEvent::V_MTE3>(mte3WaitV); // MTE3 必须等待所有该 SetFlag 之前的 V 操作完成
// MTE3 操作
```

这是一种**强同步点**，确保 MTE3 必须等待设置该信号之前的所有 V 操作执行完毕才能开始。

---

## 两种标准同步模式（必须理解！）

### 模式一：流水线屏障模式

```cpp
// SET 紧跟 WAIT = 同步点
SetFlag<HardEvent::MTE2_V>(event);   // MTE2 标记"数据已准备好"
WaitFlag<HardEvent::MTE2_V>(event);  // V 等待数据就绪
// V 操作...
```

**语义**：确保 WAIT 之后的操作必须等待 SET 之前的操作完成。

### 模式二：反向同步模式（PingPong 常用）

```cpp
// 初始化：SET 一次，确保第一次 WAIT 不阻塞
SetFlag<HardEvent::MTE3_MTE2>(event);

for (iter) {
    WaitFlag<HardEvent::MTE3_MTE2>(event);    // 等待上一次操作完成
    操作...                                    // 独占资源执行
    SetFlag<HardEvent::MTE3_MTE2>(event);     // 标记本次完成，为下次准备
}

// 收尾：WAIT 一次，确保最后一次操作完成
WaitFlag<HardEvent::MTE3_MTE2>(event);
```

**语义**：保证每次循环中的操作是串行的，独占某种资源。

**关键理解**：
- 初始化的 SET 让第一次循环的 WAIT 可以立即通过
- 循环内 WAIT 等待的是**上一次**迭代 SET 标记的操作完成
- 收尾 WAIT 消费最后一次 SET，确保信号平衡

---

## ⚠️ 分析时的常见错误（避免！）

### 错误 1：机械地数 SET/WAIT 数量

**错误做法**：
```
看到 if 分支内 SET，else 分支没 SET，就认为有问题
```

**正确做法**：
```
理解每个分支的执行路径，分析 WAIT 依赖的是哪个 SET
- 如果尾部处理会自己 SET + WAIT，则主循环 else 分支不需要 SET
- 画出完整的状态追踪表，验证每条路径都正确
```

### 错误 2：认为同一 event 重复使用会冲突

**错误理解**：
```
"行 910-911 用了 vWaitMte2，行 914-915 又用它，会不会冲突？"
```

**正确理解**：
```
SET→WAIT 后状态回到 UNSET，可以立即重新使用
每次 SET+WAIT 都是独立的同步点，互不影响
```

### 错误 3：忽略条件分支的完整路径

**错误做法**：
```
只分析主循环，忽略尾部处理和收尾逻辑
```

**正确做法**：
```
必须分析所有可能的执行路径：
1. 主循环走 if 分支 → 尾部处理 → 收尾
2. 主循环走 else 分支 → 尾部处理 → 收尾
3. 提前 return 的路径
每条路径都要验证入口状态 = 出口状态
```

### 错误 4：碰到有问题的SET在if条件分支当中就直接将其移出
```cpp
    WaitFlag<HardEvent::MTE3_MTE2>(event);
    if (condition) {
        // xxx
        SetFlag<HardEvent::MTE3_MTE2>(event);
        // xxx
    }
```
**错误理解**：
```cpp
    WaitFlag<HardEvent::MTE3_MTE2>(event);
    if (condition) {
        // xxx
        // xxx 
    }
    SetFlag<HardEvent::MTE3_MTE2>(event); // 认为这里有问题，就直接移出 if 条件分支
```
这可能能解决同步问题，但是可能会影响性能, 因为后续WaitFlag会等待原SetFlag后不必要的操作，导致性能下降。
**正确理解**：
```cpp
    WaitFlag<HardEvent::MTE3_MTE2>(event);
    if (condition) {
        // xxx
        SetFlag<HardEvent::MTE3_MTE2>(event);
        // xxx 
    } else {
        SetFlag<HardEvent::MTE3_MTE2>(event); // 保持原有的同步逻辑，确保性能不受影响
    }
```
新增else分支添加SetFlag，可以保持原有的同步逻辑，同时性能不受影响。
---

## PingPong 双缓冲同步模式

**标准结构**：

```cpp
// 初始化：预设置两个 Flag，确保第一次 Wait 不阻塞
SetFlag<HardEvent::MTE3_MTE2>(mte2WaitMte3Pong);
SetFlag<HardEvent::MTE3_MTE2>(mte2WaitMte3);

for (iter) {
    // 根据 PingPong 标志选择事件
    event_t eventId = pingPongIdx ? mte2WaitMte3Pong : mte2WaitMte3;

    WaitFlag<HardEvent::MTE3_MTE2>(eventId);      // 等待上一次 MTE3 完成
    DataCopyPad(...);                             // MTE2 CopyIn
    SetFlag<HardEvent::MTE2_MTE3>(otherEventId);  // 通知 MTE3
    WaitFlag<HardEvent::MTE2_MTE3>(otherEventId); // 等待 MTE3 完成
    DataCopyPad(...);                             // MTE3 CopyOut
    SetFlag<HardEvent::MTE3_MTE2>(eventId);       // 标记本次完成
    pingPongIdx = 1 - pingPongIdx;                // 切换
}

// 收尾：必须等待所有 Flag，确保信号平衡！
WaitFlag<HardEvent::MTE3_MTE2>(mte2WaitMte3Pong);
WaitFlag<HardEvent::MTE3_MTE2>(mte2WaitMte3);
```

**验证要点**：
1. 初始化预设置了所有 PingPong 事件
2. 每次迭代的 WAIT 依赖上一次的 SET（反向同步）
3. **收尾 WAIT 所有 Flag** — 确保函数退出时信号平衡
4. 函数入口状态 = 函数出口状态（通常全 UNSET）

---

## 关键检查清单

**每个函数必须满足**：
- [ ] 理解每个 SET/WAIT 的语义，而不是机械计数
- [ ] 分析所有可能的执行路径（包括条件分支、提前 return）
- [ ] 函数入口 Flag 状态 = 函数出口 Flag 状态
- [ ] 每个 WAIT 都有对应的 SET 来源（考虑所有路径）
- [ ] **SET 和 WAIT 的 HardEvent 类型必须相同**

**HardEvent 类型语义检查（重要！）**：
- [ ] SetFlag 前的操作类型是否与 HardEvent 的触发方匹配？
- [ ] WaitFlag 后的操作类型是否与 HardEvent 的等待方匹配？
- [ ] 例如：`SetFlag<V_MTE3>` 前应该是 V 操作，`WaitFlag<V_MTE3>` 后应该是 MTE3 操作

**PingPong 场景额外检查**：
- [ ] 初始化预设置了所有 PingPong 事件
- [ ] 收尾 WAIT 了所有 PingPong 事件
- [ ] 条件分支内的事件 ID 选择逻辑一致

---

## 通过上下文检测 HardEvent 类型错误

**这是一种重要的同步问题检测方法！**

### 检查方法

观察 SetFlag/WaitFlag 前后的代码，验证操作类型是否与 HardEvent 语义匹配：

```cpp
// 正确示例：V_MTE3
Add(dst, src, ...);                    // ← V 操作
SetFlag<HardEvent::V_MTE3>(event);     // ✓ V 完成，触发
WaitFlag<HardEvent::V_MTE3>(event);    // ✓ MTE3 等待
DataCopyPad(gm, ub, ...);              // ← MTE3 操作

// 错误示例：HardEvent 类型写错
DataCopyPad(ub, gm, ...);              // ← MTE2 操作（CopyIn）
SetFlag<HardEvent::V_MTE3>(event);     // ✗ 错误！应该是 MTE2_V
WaitFlag<HardEvent::V_MTE3>(event);    // ✗ 后面如果是 V 操作，类型就错了
Add(dst, src, ...);                    // ← V 操作
```

### 常见操作类型对照表

| 操作类型 | 典型 API | 所属流水线 |
|---------|---------|-----------|
| 数据搬入 (GM → UB) | `DataCopy`, `DataCopyPad` | MTE2 |
| 数据搬出 (UB → GM) | `DataCopy`, `DataCopyPad` | MTE3 |
| 向量计算 | `Add`, `Mul`, `Cast`, `Muls`, `Sub` | V |
| 矩阵计算 | `MatMul`, `MMAD` | M (Cube) |
| 标量操作 | 标量运算 | S |

### 错误检测示例

**场景**：怀疑 HardEvent 类型写错

```cpp
// 代码片段
DataCopyPad(tensorA, gmA, ...);        // MTE2 操作
DataCopyPad(tensorB, gmB, ...);        // MTE2 操作
SetFlag<HardEvent::MTE2_V>(event);     // ✓ 正确：MTE2 完成
WaitFlag<HardEvent::MTE2_V>(event);    // ✓ 正确：V 等待
Cast(tensorA_fp32, tensorA, ...);      // V 操作
```

**如果发现**：
```cpp
SetFlag<HardEvent::MTE3_V>(event);     // ✗ 错误！MTE3_V 是"V等MTE3"
// 应该是 MTE2_V："MTE2完成通知V"
```

### 检查步骤

1. **识别 SetFlag 前的操作**：确定是 MTE2/V/MTE3 中的哪一种
2. **识别 WaitFlag 后的操作**：确定是 MTE2/V/MTE3 中的哪一种
3. **验证 HardEvent 类型**：
   - SetFlag 的触发方 = 前面的操作类型
   - WaitFlag 的等待方 = 后面的操作类型
4. **发现不匹配**：报告 HardEvent 类型错误

---

## 常见问题模式

| 模式 | 检测方法 | 修复 |
|------|---------|------|
| 真正的条件 SET 漏 else | 分析所有路径，发现某路径 WAIT 无 SET 来源 | 在 else 中补 SET |
| 初始化漏预设置 | PingPong 循环前没有 SET | 补全初始化 SET |
| 收尾漏 WAIT | 循环后没有 WAIT 所有 event | WAIT 所有 Flag |
| 提前 return 漏同步 | return 前检查 Flag 状态 | return 前补同步 |

**注意**：不是所有条件分支都是问题！需要具体分析每条路径。

---

## HardEvent 类型参考

| HardEvent 类型 | 方向 | 典型用途 |
|----------------|------|---------|
| `MTE2_V` | MTE2→V | MTE2 数据拷贝完成，通知 V 开始计算 |
| `V_MTE3` | V→MTE3 | V 计算完成，通知 MTE3 搬运结果 |
| `MTE3_MTE2` | MTE3→MTE2 | MTE3 搬运完成，通知 MTE2 开始下一轮 |
| `MTE2_MTE3` | MTE2→MTE3 | MTE2 搬运完成，通知 MTE3 开始搬运 |
| `MTE3_V` | MTE3→V | MTE3 搬运完成，通知 V 开始计算 |
| `MTE2_S` | MTE2→S | MTE2 完成，通知 Scalar 单元 |

---

## 快速检查清单

执行顺序：先全部检查，后一次性报告。

### 1. 提取同步点（1 分钟）

```bash
grep -n "SetFlag\|WaitFlag" file.h
```

标记可疑点：只 Wait 不 Set、只 Set 不 Wait。

### 2. 验证配对（1 分钟）

**核内**：每个 WaitFlag 前必有对应 HardEvent 类型的 SetFlag

### 3. 检查提前 return（1 分钟）

```bash
grep -n "return" file.h
```

检查 return 前是否漏同步。

---

## 反模式速查

| 错误做法 | 正确做法 |
|---------|---------|
| 机械地数 SET/WAIT 数量 | 理解每个 SET/WAIT 的语义和依赖关系 |
| 看到条件分支就认为有问题 | 分析每条路径的完整执行流程 |
| 认为 SET+WAIT 会死锁 | 理解这是流水线屏障 |
| 发现一个问题就报告 | 完整分析所有路径后一次性报告 |
| 认为同一 event 重复使用会冲突 | 理解 SET→WAIT 后状态回到 UNSET，可重复使用 |
| 忽略尾部处理和收尾逻辑 | 必须分析所有可能的执行路径 |
| 凭直觉分析 | 必须用状态追踪表，画出每条路径 |

---

## References

- [跨核动态调试 skill](../ascendc-sync-crosscore-debug/SKILL.md) - 使用 printf 追踪法进行跨核同步动态调试
