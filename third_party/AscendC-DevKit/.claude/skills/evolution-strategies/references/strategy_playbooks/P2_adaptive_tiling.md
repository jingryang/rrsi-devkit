# P2 Playbook: 自适应分块策略实操流程

> **强制流程**。P2 将固定 tile size 改造为基于 UB 容量、数据类型和输入 shape 的动态自适应分块。禁止硬编码常量。

## Step 1: 定位关键结构

```bash
# 1.1 固定分块值
grep -n "const.*tileSize\|const.*TILE_SIZE\|DEFAULT_TILE\|tile_length\|MAX_TILE" shared/original/op_host/*_tiling.cpp shared/original/op_kernel/*.cpp > /tmp/p2_loc.txt

# 1.2 BlockDim / 核数设置
grep -n "SetBlockDim\|BLOCK_DIM\|GetBlockNum\|coreNum" shared/original/op_host/*_tiling.cpp >> /tmp/p2_loc.txt

# 1.3 UB 相关常量和 buffer 分配
grep -n "InitBuffer\|ubSize\|UB_CAPACITY\|RESERVED_UB" shared/original/op_kernel/*.cpp shared/original/op_host/*_tiling.cpp >> /tmp/p2_loc.txt

# 1.4 循环结构
grep -n "for.*innerLoops\|for.*tile\|while.*loop" shared/original/op_kernel/*.cpp >> /tmp/p2_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **固定 tileSize/TILE_SIZE 定义位置**：文件 + 行号
- **SetBlockDim / BLOCK_DIM 位置**：文件 + 行号
- **主循环结构**：文件 + 行范围

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| tileSize / tile_length | 固定值 `?` | UB 动态计算 `?` | `?_tiling.cpp:L?` |
| BLOCK_DIM | 固定值 `?` | `min(dataNeedCores, platformCores)` | `?_tiling.cpp:L?` |
| UB 预算 | 未计算 | `platformUB - reserved - bufferOverhead` | `?_tiling.cpp:L?` |
| 循环结构 | `for i < innerLoops` | `for i < loops - 1 + tail` | `?_kernel.cpp:L?-L?` |
| 数据对齐 | 无 | `AlignUp(count, blockAlign)` | `?_tiling.cpp:L?` |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 简单行分块**（Element-wise / Norm）：按行切分，每核处理 rowsPerCore
- **形态 β — 多维分块**（Pool / Conv）：N/H/W/C 多维度尝试分块
- **形态 γ — 多策略选择**（LayerNorm / Softmax）：根据 shape 特征在多种 tiling 策略间选择

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α）

```cpp
// === 改造前 ===
const uint32_t TILE_SIZE = 2048;
uint32_t innerLoops = elementsPerCore / TILE_SIZE;

// === 改造后 ===
// Host tiling: 基于平台 UB 大小动态计算
auto ascendcPlatform = platform_ascendc::PlatformAscendC(platformInfo);
uint32_t ubSizePlatForm;
ascendcPlatform.GetCoreMemSize(platform_ascendc::CoreMemType::UB, ubSizePlatForm);

constexpr uint32_t RESERVED_UB_SIZE = 20480; // 20KB 栈预留
uint32_t alignNum = 32 / sizeof(T); // 32B 对齐
uint32_t maxDataCount = (ubSizePlatForm - RESERVED_UB_SIZE) / sizeof(T) / alignNum * alignNum;

uint32_t usedCoreNum = std::min((totalElems + maxDataCount - 1) / maxDataCount, platformCoreNum);
uint32_t elemsPerCore = (totalElems + usedCoreNum - 1) / usedCoreNum;
uint32_t loops = (elemsPerCore + maxDataCount - 1) / maxDataCount;
uint32_t tail = elemsPerCore - (loops - 1) * maxDataCount;

context->SetBlockDim(usedCoreNum);
```

### 3C. Variant Notes

- **形态 β（多维）**：按 N→H→W→C 优先级尝试分块，优先切分数据量最大维度
- **形态 γ（多策略）**：使用 `IsCapable()` 判断策略适用性，按优先级注册多个 tiling 类
- **若 UB 极小**：设置 `minTileSize` 阈值，低于阈值时退化为单核处理

## Step 4: 约束复核

**公式**：
```
tileSize = (ubSizePlatForm - reserved - idxBuffer - tmpBuffer) / dtypeSize / align * align
约束 1: tileSize >= minTileSize（通常 128-256 元素）
约束 2: tileSize * dtypeSize * bufferNum <= ubSizePlatForm * 0.8
约束 3: usedCoreNum <= platformCoreNum
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: 无硬编码固定 tileSize
grep -c "const.*tileSize.*=.*[0-9]\{4,\}\|const.*TILE_SIZE.*=.*[0-9]\{4,\}" modified_files/op_host/*_tiling.cpp
# 期望: == 0

# 检查 2: 使用了平台 UB 查询
grep -c "GetCoreMemSize\|ubSizePlatForm\|PlatformAscendC" modified_files/op_host/*_tiling.cpp modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 3: 使用了动态核数分配
grep -c "SetBlockDim.*usedCoreNum\|SetBlockDim.*min\|SetBlockDim.*std::min" modified_files/op_host/*_tiling.cpp
# 期望: >= 1

# 检查 4: 存在对齐计算
grep -c "AlignUp\|alignNum\|/ align\|/ ALIGN" modified_files/op_host/*_tiling.cpp modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 5: 存在尾块处理
grep -c "tail\|lastCount\|remainder\|extraLoop" modified_files/op_host/*_tiling.cpp modified_files/op_kernel/*.cpp
# 期望: >= 1
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：UB overflow | 回 Step 4 复算；增大 RESERVED_UB_SIZE 或减小 tileSize |
| 小数据量场景性能下降 | 检查 usedCoreNum 是否动态缩小；避免 1000 元素启动 30 核 |
| 尾块处理错误 | 确保 tail <= tileSize 且 tail > 0 时的边界正确 |
| 不同平台 UB 大小差异 | 使用 `GetCoreMemSize` 查询，禁止硬编码 UB 容量 |
| Tiling 计算 Host 侧开销大 | 将复杂计算移到 `DoOpTiling`，避免每次 kernel 调用重复计算 |
| 对齐后 tileSize 为 0 | 检查 `alignNum` 计算，确保 dtypeSize <= 32 |

---

**完成后在 `implementation_note.txt` 贴**：
```
[P2 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: UB calc passed (tileSize=... <= ...)
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
