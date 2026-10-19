# P7 Playbook: 32B 对齐 + DataCopyPad 实操流程

> **强制流程**。P7 将无对齐的 DataCopy 改造为 32B 对齐访问，必要时使用 DataCopyPad 处理尾部非对齐数据。

## Step 1: 定位关键结构

```bash
# 1.1 DataCopy 调用点
grep -n "DataCopy\\b\|DataCopyPad\|CopyIn\|CopyOut" shared/original/op_kernel/*.cpp > /tmp/p7_loc.txt

# 1.2 对齐相关代码
grep -n "Align\|align\|BLOCK_SIZE\|padding\|pad" shared/original/op_kernel/*.cpp shared/original/op_host/*_tiling.cpp >> /tmp/p7_loc.txt

# 1.3 tile size / 数据长度变量
grep -n "tileSize\|current_tile\|dataCount\|uValue\|count" shared/original/op_kernel/*.cpp >> /tmp/p7_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **DataCopy 调用位置**：文件 + 行号（所有调用点）
- **当前对齐处理**：如有，记录位置
- **数据长度变量**：文件 + 行号

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| DataCopy 方式 | 直接 `DataCopy(dst, src, count)` | 对齐后 `DataCopy` 或 `DataCopyPad` | `?_kernel.cpp:L?` |
| 对齐粒度 | 无 | `32 / sizeof(T)` 元素 | `?_kernel.cpp:L?` |
| 尾部处理 | 无 | `DataCopyPad` + rightPadding | `?_kernel.cpp:L?` |
| UB buffer 大小 | `count * sizeof(T)` | `AlignUp(count, align) * sizeof(T)` | `?_kernel.cpp:L?` |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 连续一维数据**（Element-wise）：单次 DataCopy，按 32B 对齐长度
- **形态 β — 多维 strided 数据**（Conv / Pool）：使用 DataCopyExtParams 配置 stride
- **形态 γ — 带 mask / padding**（Softmax / Attention）：对齐后填充 padding 区域为特定值

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α）

```cpp
// === 改造前 ===
AscendC::DataCopy(dstLocal, srcGm[offset], dataCount);

// === 改造后 ===
constexpr int32_t BLOCK_SIZE = 32; // 32 bytes
int32_t numPerBlock = BLOCK_SIZE / sizeof(T);
int32_t alignedCount = (dataCount + numPerBlock - 1) / numPerBlock * numPerBlock;

if (dataCount % numPerBlock == 0) {
    // 已对齐：直接 DataCopy
    AscendC::DataCopy(dstLocal, srcGm[offset], dataCount);
} else {
    // 未对齐：使用 DataCopyPad 填充尾部
    DataCopyExtParams copyParams{1, static_cast<uint32_t>(dataCount * sizeof(T)), 0, 0, 0};
    DataCopyPadExtParams<T> padParams{true, 0, static_cast<uint8_t>(alignedCount - dataCount), 0};
    AscendC::DataCopyPad(dstLocal, srcGm[offset], copyParams, padParams);
}
```

### 3C. Variant Notes

- **形态 β（多维 strided）**：使用 `DataCopyExtParams` 设置 `blockCount, blockLen, srcStride, dstStride`
- **形态 γ（带 padding 值）**：`padParams{paddingValue = MASK_VALUE / 0}`，计算后需 `Duplicate` 填充
- **若存在大量小数据量拷贝**：对齐开销占比高，仅在 `dataCount >= numPerBlock * 2` 时应用

## Step 4: 约束复核

**公式**：
```
numPerBlock = 32 / sizeof(T)
alignedCount = CeilDiv(dataCount, numPerBlock) * numPerBlock
约束 1: alignedCount * sizeof(T) <= tileSize * sizeof(T)（UB 内不越界）
约束 2: 若使用 DataCopyPad，dst buffer 按 alignedCount 分配
约束 3: padding 区域数据不参与计算（用 mask 或条件跳过）
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: 存在对齐计算
grep -c "numPerBlock\|BLOCK_SIZE\|align\|AlignUp" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 2: 存在 DataCopyPad 调用
grep -c "DataCopyPad" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 3: UB buffer 按对齐后大小分配
grep -c "alignedCount\|AlignUp.*tile\|align.*InitBuffer" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 4: 无裸 DataCopy 带变量长度（至少主要路径已改造）
grep -c "DataCopy(.*,.*,.*tileSize\|DataCopy(.*,.*,.*count)" modified_files/op_kernel/*.cpp
# 期望: == 0（或 <= 1 条保留路径）

# 检查 5: 存在条件分支区分对齐/非对齐
grep -c "if.*%.*numPerBlock\|if.*%.*align\|if.*== 0" modified_files/op_kernel/*.cpp
# 期望: >= 1
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：DataCopyPad 参数类型不匹配 | 确保 `DataCopyExtParams` 和 `DataCopyPadExtParams<T>` 类型正确 |
| padding 区域数据污染计算结果 | 用 `Duplicate` 填充 padding 为 0 或 mask 值；计算时用 `dataCount` 而非 `alignedCount` |
| 性能无提升 | 检查是否 `dataCount` 本身已 32B 对齐；若已对齐，DataCopyPad 是多余开销 |
| UB 溢出 | 对齐后 `alignedCount > tileSize` → 回 Step 4 检查 tileSize 是否按对齐分配 |
| 不同数据类型对齐粒度不同 | `numPerBlock = 32 / sizeof(T)`：FP32=8, FP16/BF16=16, INT8=32 |
| BF16 类型 DataCopyPad 不支持 | 先 Cast 到 FP16 或改用 `DataCopy` + 手动 `SetValue` 填充尾部 |

---

**完成后在 `implementation_note.txt` 贴**：
```
[P7 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: align check passed (alignedCount=... <= tileSize=...)
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
