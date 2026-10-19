# P4 Playbook: 多核负载均衡实操流程

> **强制流程**。P4 将简单均匀分改造为精细化负载均衡（former/tail 或 head/tail core），最小化核间等待。

## Step 1: 定位关键结构

```bash
# 1.1 分核逻辑
grep -n "SetBlockDim\|BLOCK_DIM\|coreNum\|GetBlockNum\|GetBlockIdx" shared/original/op_host/*_tiling.cpp shared/original/op_kernel/*.cpp > /tmp/p4_loc.txt

# 1.2 简单均匀分代码
grep -n "elems_per_core\|rowsPerCore\|/ coreNum\|/ BLOCK_DIM\|/ GetBlockNum" shared/original/op_host/*_tiling.cpp shared/original/op_kernel/*.cpp >> /tmp/p4_loc.txt

# 1.3 尾块/边界处理
grep -n "blockIdx == GetBlockNum\|blockIdx < GetBlockNum\|tail\|remainder" shared/original/op_kernel/*.cpp >> /tmp/p4_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **SetBlockDim 位置**：文件 + 行号
- **均匀分代码位置**：文件 + 行范围
- **现有尾块处理（如有）**：文件 + 行号

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| 分核算法 | 简单除法 `total / coreNum` | former/tail 均衡分 | `?_tiling.cpp:L?` |
| 每核数据量 | 固定值 | `formerLength` / `tailLength` | `?_tiling.cpp:L?` |
| 核数使用 | 固定 BLOCK_DIM | `min(needCores, maxCores)` | `?_tiling.cpp:L?` |
| Kernel 端边界 | 无特殊处理 | `blockIdx < formerNum` 分支 | `?_kernel.cpp:L?-L?` |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 1D 数据均分**（Element-wise / Norm）：按元素/行数均衡分配
- **形态 β — 2D 网格分**（Matmul）：M×N 网格按对角线或块分配
- **形态 γ — 多维分层分**（Pool / Conv）：NC / DHW 多维度分层分配

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α）

```cpp
// === 改造前 ===
uint32_t BLOCK_DIM = 16;
uint32_t elemsPerCore = (totalElems + BLOCK_DIM - 1) / BLOCK_DIM;
context->SetBlockDim(BLOCK_DIM);

// Kernel:
uint32_t start = blockIdx * elemsPerCore;
uint32_t end = start + elemsPerCore;

// === 改造后 ===
// Host tiling:
uint32_t usedCoreNum = std::min((totalElems + MIN_PER_CORE - 1) / MIN_PER_CORE, maxCoreNum);
uint32_t formerNum = totalElems % usedCoreNum;
uint32_t tailNum = usedCoreNum - formerNum;
uint32_t formerLength = totalElems / usedCoreNum + 1;
uint32_t tailLength = totalElems / usedCoreNum;
context->SetBlockDim(usedCoreNum);

// Kernel:
uint32_t myLength = (blockIdx < formerNum) ? formerLength : tailLength;
uint32_t start = (blockIdx < formerNum) 
    ? blockIdx * formerLength 
    : formerNum * formerLength + (blockIdx - formerNum) * tailLength;
```

### 3C. Variant Notes

- **形态 β（2D 网格）**：M 维度分 `coreNumM` 组，N 维度分 `coreNumN` 组，`coreNumM * coreNumN = usedCoreNum`
- **形态 γ（多维分层）**：优先切分最大维度，剩余维度在组内再分；使用 `CeilDiv` 计算每维切分数
- **数据量 < 核数**：`usedCoreNum = totalElems`（每核 1 个元素，避免空转）

## Step 4: 约束复核

**公式**：
```
最大不均衡度 = formerLength - tailLength = 1（理想）
约束 1: usedCoreNum <= platformCoreNum
约束 2: formerLength >= 1（每核至少 1 个元素）
约束 3: formerNum * formerLength + tailNum * tailLength == totalElems
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: 使用了动态核数分配
grep -c "SetBlockDim.*usedCoreNum\|SetBlockDim.*std::min" modified_files/op_host/*_tiling.cpp
# 期望: >= 1

# 检查 2: 存在 former/tail 或 head/tail 逻辑
grep -c "formerLength\|tailLength\|headCoreNum\|tailCoreNum\|preCoreNum" modified_files/op_host/*_tiling.cpp modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 3: Kernel 端根据 blockIdx 选择数据量
grep -c "blockIdx.*former\|blockIdx.*tail\|GetBlockIdx.*<" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 4: 无简单均匀分残留
grep -c "elems_per_core.*=.*total.*core\|rowsPerCore.*=.*total.*core" modified_files/op_host/*_tiling.cpp modified_files/op_kernel/*.cpp
# 期望: == 0

# 检查 5: 负载总和等于总量
grep -c "formerNum.*formerLength\|headCoreNum.*lineHeadCore" modified_files/op_host/*_tiling.cpp
# 期望: >= 1
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：`blockIdx` 未定义 | Kernel 中使用 `AscendC::GetBlockIdx()` |
| 尾核数据量为 0 | 检查 `tailLength == 0` 时 `usedCoreNum = formerNum` |
| 数据量 < 核数时性能差 | `usedCoreNum = min(totalElems, maxCoreNum)`，禁止空转 |
| 2D 分核时 M×N 不匹配 | 确保 `coreNumM * coreNumN <= platformCoreNum` |
| 精度错（边界数据重复/遗漏） | 核间数据范围必须连续无重叠：`start_{i+1} == start_i + length_i` |
| Tiling 参数过大 | 减少 TilingData 字段数，将计算移到 Host 侧 `DoOpTiling` |

---

**完成后在 `implementation_note.txt` 贴**：
```
[P4 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: balance check passed (max_delta=1)
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
