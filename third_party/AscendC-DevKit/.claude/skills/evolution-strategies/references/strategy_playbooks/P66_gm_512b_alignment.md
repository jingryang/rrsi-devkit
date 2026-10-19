# P66 Playbook: GM 512B 对齐带宽优化实操流程

> **强制流程**。P66 将 GM 地址偏移改造为 512B 对齐，最大化内存带宽利用率（32B 对齐→512B 对齐可提升带宽最高 30%）。

## Step 1: 定位关键结构

```bash
# 1.1 GM 地址设置和偏移
grep -n "SetGlobalBuffer\|offset.*=\|tileStart\|coreOffset\|blockIdx.*stride" shared/original/op_kernel/*.cpp > /tmp/p66_loc.txt

# 1.2 DataCopy / Fixpipe 调用
grep -n "DataCopy.*Gm\|Fixpipe\|CopyIn\|CopyOut" shared/original/op_kernel/*.cpp >> /tmp/p66_loc.txt

# 1.3 现有对齐处理
grep -n "AlignUp\|align\|512\|256\|64" shared/original/op_kernel/*.cpp shared/original/op_host/*_tiling.cpp >> /tmp/p66_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **SetGlobalBuffer 位置**：文件 + 行号
- **GM 偏移计算位置**：文件 + 行范围
- **DataCopy/Fixpipe 调用点**：文件 + 行号

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| GM 偏移 | `offset = idx * stride` | `offset = AlignUp(idx * stride, 512)` | `?_kernel.cpp:L?` |
| DataCopy 长度 | `count * sizeof(T)` | `AlignUp(count * sizeof(T), 512)` | `?_kernel.cpp:L?` |
| 地址对齐检查 | 无 | `assert(addr % 512 == 0)` 或运行时检查 | `?_kernel.cpp:L?` |
| Tiling 参数 | 无 | `outputStride` 按 512B 对齐 | `?_tiling.cpp:L?` |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 连续一维 GM 访问**（Element-wise / Norm）：偏移量按元素索引 × 元素大小
- **形态 β — 多维 strided GM 访问**（Conv / Pool）：stride 参数需 512B 对齐
- **形态 γ — Fixpipe 输出**（Matmul）：输出地址和 workspace 地址必须 512B 对齐

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α）

```cpp
// === 改造前 ===
uint32_t offset = blockIdx * elemsPerCore + loopIdx * tileSize;
DataCopy(ubLocal, gmTensor[offset], tileSize);

// === 改造后 ===
constexpr uint32_t GM_ALIGN = 512; // 512 bytes

// Host tiling: 确保每核起始地址 512B 对齐
uint32_t bytesPerCore = elemsPerCore * sizeof(T);
uint32_t alignedBytesPerCore = (bytesPerCore + GM_ALIGN - 1) / GM_ALIGN * GM_ALIGN;

// Kernel:
uint32_t gmOffset = blockIdx * alignedBytesPerCore / sizeof(T);
uint32_t gmOffsetBytes = blockIdx * alignedBytesPerCore;
// 验证: gmOffsetBytes % GM_ALIGN == 0

// 数据长度对齐到 512B
uint32_t copyBytes = tileSize * sizeof(T);
uint32_t alignedCopyBytes = (copyBytes + GM_ALIGN - 1) / GM_ALIGN * GM_ALIGN;

DataCopy(ubLocal, gmTensor[gmOffset], alignedCopyBytes / sizeof(T));
```

### 3C. Variant Notes

- **形态 β（多维 strided）**：`srcStride` 和 `dstStride` 需为 512B 的整数倍
- **形态 γ（Fixpipe）**：workspace 分配时使用 `AlignUp(size, 512)`；`SetGlobalBuffer` 地址需 512B 对齐
- **若输入数据本身未对齐**：在 Host 侧 `AutoContiguous` 处理，或在 Tiling 阶段调整起始偏移

## Step 4: 约束复核

**公式**：
```
alignedBytes = CeilDiv(bytes, 512) * 512
约束 1: gmOffsetBytes % 512 == 0（地址对齐）
约束 2: copyBytes % 512 == 0 或 alignedCopyBytes <= tileSize * sizeof(T) + paddingBudget
约束 3: 对齐后总 GM 占用增加 <= 原始占用的 10%（避免过度 padding）
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: 存在 512 对齐计算
grep -c "512\|GM_ALIGN\|AlignUp.*512" modified_files/op_kernel/*.cpp modified_files/op_host/*_tiling.cpp
# 期望: >= 1

# 检查 2: GM 偏移计算使用了字节对齐
grep -c "alignedBytes\|gmOffsetBytes\|/ sizeof.*\* sizeof" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 3: DataCopy 长度按对齐后计算
grep -c "alignedCopyBytes\|AlignUp.*copyBytes\|/ 512 \* 512" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 4: workspace / 输出地址对齐（形态 γ）
grep -c "workspace.*Align\|output.*Align.*512\|SetGlobalBuffer.*Align" modified_files/op_kernel/*.cpp modified_files/op_host/*_tiling.cpp
# 期望: >= 1（形态 γ）或 == 0（形态 α/β）

# 检查 5: 无直接按未对齐索引访问 GM
grep -c "gmTensor\[blockIdx \* .*\]\|gmTensor\[coreIdx \* .*\]" modified_files/op_kernel/*.cpp
# 期望: == 0（或已对齐后访问）
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：DataCopy 长度超过 tileSize | `alignedCopyBytes / sizeof(T)` 必须 <= tileSize 的 buffer 分配 |
| GM 占用暴增 | 对齐 padding 导致 GM 增加 >10% → 回 Step 4 评估是否值得 |
| 数据错位 | `alignedBytesPerCore / sizeof(T)` 可能不是整数个元素，需用字节偏移 |
| Fixpipe 地址未对齐 | `fixpipe_ratio` 高是地址未对齐的直接信号，检查 workspace 分配 |
| 多核场景地址冲突 | 各核的 `gmOffset` 需连续且不重叠，检查 `alignedBytesPerCore * numCores <= totalBytes` |
| 与 P7（32B 对齐）冲突 | P7 是必要条件，P66 是充分优化；两者互补，先 P7 后 P66 |
| 小数据量无收益 | `copyBytes < 512` 时对齐无意义；仅在大数据量（>4KB）场景应用 |

---

**完成后在 `implementation_note.txt` 贴**：
```
[P66 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: align check passed (gmOffset % 512 == 0, copyBytes aligned)
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
