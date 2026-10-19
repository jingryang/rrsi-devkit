# P8 Playbook: UB 内存分区管理实操流程

> **强制流程**。P8 将独立的 UB buffer 改造为分区复用布局，提升 UB 利用率，支持更大 tile。

## Step 1: 定位关键结构

```bash
# 1.1 InitBuffer / TQue / TBuf 定义
grep -n "InitBuffer\|TQue\|TBuf" shared/original/op_kernel/*.cpp shared/original/op_kernel/*.h > /tmp/p8_loc.txt

# 1.2 现有 buffer 大小
grep -n "tileSize.*sizeof\|BUFFER_SIZE\|UB_BUFFER" shared/original/op_kernel/*.cpp shared/original/op_host/*_tiling.cpp >> /tmp/p8_loc.txt

# 1.3 数据类型和 LocalTensor 分配
grep -n "LocalTensor\|AllocTensor\|DeQue\|EnQue" shared/original/op_kernel/*.cpp >> /tmp/p8_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **InitBuffer 调用位置**：文件 + 行号（所有调用点）
- **每个 buffer 的用途**：输入 / 输出 / 临时 / 计算
- **当前 UB 总占用**：各 buffer 大小之和

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| Buffer 数量 | `N` 个独立 buffer | `M` 个复用区（`M < N`） | `?_kernel.cpp:L?` |
| 分配方式 | `InitBuffer(queue, N, size)` | `InitBuffer(pool, 1, totalSize)` + offset | `?_kernel.cpp:L?` |
| 索引计算 | 无 | `buf[OFFSET_X * numPerLoop]` | `?_kernel.cpp:L?` |
| UB 总占用 | `sum(size_i)` | `max(concurrent_size)` | `?_kernel.cpp:L?` |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 输入+输出+临时三区**（Element-wise）：3 个 queue 可复用为 1 个 pool
- **形态 β — 多阶段计算链**（Norm / Softmax）：多临时 buffer 按阶段复用
- **形态 γ — 原地修改**（Foreach）：输入输出地址相同时跳过 DataCopy

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α）

```cpp
// === 改造前 ===
pipe.InitBuffer(inQueueX, 1, tileSize * sizeof(T));
pipe.InitBuffer(inQueueY, 1, tileSize * sizeof(T));
pipe.InitBuffer(outQueue, 1, tileSize * sizeof(T));
pipe.InitBuffer(tmpBuf, tileSize * sizeof(T));
// UB 占用 = 4 * tileSize * sizeof(T)

// === 改造后 ===
static constexpr uint32_t BUF_FACTOR = 3; // X, Y, output 复用
static constexpr uint32_t OFFSET_X = 0;
static constexpr uint32_t OFFSET_Y = 1;
static constexpr uint32_t OFFSET_OUT = 2;

pipe.InitBuffer(calc_buf_, BUF_FACTOR * tileSize * sizeof(T) + 32);

AscendC::LocalTensor<T> xLocal = calc_buf_.Get<T>();
AscendC::LocalTensor<T> yLocal = calc_buf_.Get<T>(OFFSET_Y * tileSize);
AscendC::LocalTensor<T> outLocal = calc_buf_.Get<T>(OFFSET_OUT * tileSize);
// UB 占用 = 3 * tileSize * sizeof(T) + 32
```

### 3C. Variant Notes

- **形态 β（多阶段复用）**：定义 `OFFSET_STAGE1, OFFSET_STAGE2, OFFSET_STAGE3`，阶段 2 复用阶段 1 的 buffer
- **形态 γ（原地修改）**：`if (dstLocal.GetPhyAddr() != srcLocal.GetPhyAddr())` 才执行 DataCopy
- **若 UB 仍紧张**：使用 `TBuf<VECCALC>` 存中间结果，不与 `VECIN/VECOUT` 争用 UB

## Step 4: 约束复核

**公式**：
```
新 UB 占用 = max_concurrent_buffers * tileSize * sizeof(T) + alignment_padding
约束 1: 新 UB 占用 <= 旧 UB 占用 * 0.9（必须节省空间）
约束 2: 各 offset 之间 32B 对齐：`offset * tileSize * sizeof(T) % 32 == 0`
约束 3: 不重叠的 buffer 生命周期不交错（阶段 1 结束才能复用给阶段 2）
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: 使用了 BUF_FACTOR / OFFSET 模式
grep -c "BUF_FACTOR\|OFFSET_\|offset.*numPerLoop" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 2: InitBuffer 数量减少
grep -c "InitBuffer" modified_files/op_kernel/*.cpp
# 期望: <= 原始数量（或明显减少）

# 检查 3: 使用了 buffer pool 获取 LocalTensor
grep -c "calc_buf_.Get\|buf_.Get\|pool.Get" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 4: 无独立 TQue 残留（主要路径）
grep -c "TQue.*VECIN.*,.*1\|TQue.*VECOUT.*,.*1" modified_files/op_kernel/*.cpp
# 期望: == 0（或 <= 1 条保留路径）

# 检查 5: 存在原地修改检测（形态 γ）
grep -c "GetPhyAddr\|phyAddr\|phy_addr" modified_files/op_kernel/*.cpp
# 期望: >= 1（形态 γ）或 == 0（形态 α/β）
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：UB overflow | 回 Step 4 检查 offset 计算；确保 alignment_padding 不过大 |
| 数据竞争（buffer 内容被覆盖） | 确保复用 buffer 的前一个使用者在后一个使用者之前完成（加 PipeBarrier） |
| offset 计算错误导致越界 | `offset * tileSize * sizeof(T)` 必须 < `InitBuffer` 的总大小 |
| 对齐 padding 导致 UB 浪费 | 每个 offset 独立 32B 对齐，而非整体对齐一次 |
| 原地修改检测失败 | `GetPhyAddr()` 只在同核内有效，跨核比较无意义 |
| Buffer 生命周期交错 | 画出各 buffer 的生命周期图，确保复用的 buffer 无时间重叠 |

---

**完成后在 `implementation_note.txt` 贴**：
```
[P8 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: UB saving check passed (new=... <= old=... * 0.9)
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
