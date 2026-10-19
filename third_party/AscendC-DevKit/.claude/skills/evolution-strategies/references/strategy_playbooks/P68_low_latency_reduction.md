# P68 Playbook: 低延迟归约指令组合实操流程

> **强制流程**。P68 将纯 WholeReduceSum/Max 改造为 BlockReduceSum/Max + WholeReduceSum/Max 组合，降低归约延迟。

## Step 1: 定位关键结构

```bash
# 1.1 归约指令调用
grep -n "WholeReduceSum\|WholeReduceMax\|BlockReduceSum\|BlockReduceMax\|ReduceSum\|ReduceMax" shared/original/op_kernel/*.cpp > /tmp/p68_loc.txt

# 1.2 归约数据 shape
grep -n "hLength\|bsLength\|rowSize\|colSize\|numCol\|tileSize" shared/original/op_kernel/*.cpp >> /tmp/p68_loc.txt

# 1.3 Mask / Counter 模式
grep -n "SetVectorMask\|SetMaskCount\|MaskMode::COUNTER\|ResetMask" shared/original/op_kernel/*.cpp >> /tmp/p68_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **归约指令位置**：文件 + 行号
- **归约数据 shape**：每行长度、batch 数
- **现有 Mask 模式**：如有，记录位置

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| 归约方式 | `WholeReduceSum(dst, src, len)` | `BlockReduceSum` + `WholeReduceSum` | `?_kernel.cpp:L?` |
| 数据缩减 | 无 | 二分 Add 累加至 <=256B | `?_kernel.cpp:L?` |
| Mask 模式 | `SetMaskNorm` / 无 | `SetMaskCount` + `COUNTER` | `?_kernel.cpp:L?` |
| 临时 buffer | 无 | `halfNum` 中间结果 buffer | `?_kernel.cpp:L?` |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 单批次归约**（bs=1, h>256）：单条数据直接二分 + WholeReduce
- **形态 β — 多批次归约**（bs>1, h 任意）：外层 bs 循环，内层每批独立二分 + WholeReduce
- **形态 γ — 超长数据归约**（h>32K）：多级 BlockReduce，可能需要 workspace 辅助

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α + β）

```cpp
// === 改造前 ===
SetMaskNorm();
for (uint32_t i = 0; i < bsLength; i++) {
    WholeReduceSum<float, false>(dst[i], src[i * hLength], MASK_PLACEHOLDER, 1, ...);
}

// === 改造后 ===
SetMaskCount();
for (uint32_t i = 0; i < bsLength; i++) {
    LocalTensor<float> srcTmp = src[i * hLength];
    LocalTensor<float> dstTmp = dst[i];
    uint32_t totalNum = hLength / 16 * 16; // 对齐到 16 元素
    uint32_t remaining = hLength - totalNum;
    
    // 阶段 1: 二分累加至 <= ONE_REPEAT_FLOAT_SIZE (256B / 4B = 64)
    while (totalNum > ONE_REPEAT_FLOAT_SIZE) {
        uint32_t halfNum = DivCeil(totalNum, 16) * DEFAULT_REP_STRIDE;
        SetVectorMask<uint8_t, MaskMode::COUNTER>(0, totalNum - halfNum);
        Add<float, false>(dstTmp, srcTmp, srcTmp[halfNum], MASK_PLACEHOLDER, 1, binaryParams);
        totalNum = halfNum;
        srcTmp = dstTmp;
    }
    
    // 阶段 2: WholeReduceSum 完成最终归约
    SetVectorMask<uint8_t, MaskMode::COUNTER>(0, totalNum);
    WholeReduceSum<float, false>(dstTmp, srcTmp, MASK_PLACEHOLDER, 1, ...);
    
    // 处理剩余未对齐元素（如有）
    if (remaining > 0) {
        // 标量累加剩余元素
    }
}
ResetMask(); SetMaskNorm();
```

### 3C. Variant Notes

- **形态 β（多批次）**：外层 `bsLength` 循环，内层复用同一个临时 buffer
- **形态 γ（超长数据）**：多级 BlockReduce，中间结果存入 workspace；最后一级用 WholeReduce
- **若数据量 < 256B**：直接 `WholeReduceSum`，无需二分累加（ overhead 大于收益）

## Step 4: 约束复核

**公式**：
```
二分停止条件: totalNum <= ONE_REPEAT_FLOAT_SIZE (=64 for float32)
约束 1: halfNum = CeilDiv(totalNum, 16) * repStride，确保对齐
约束 2: MaskMode::COUNTER 的 count <= 256（硬件限制）
约束 3: BlockReduce + WholeReduce 总 cycle < 纯 WholeReduce cycle（数据量 > 256B 时成立）
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: 存在二分累加循环
grep -c "while.*totalNum\|halfNum\|DivCeil.*totalNum" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 2: 使用了 SetMaskCount / COUNTER
grep -c "SetMaskCount\|MaskMode::COUNTER\|SetVectorMask.*COUNTER" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 3: BlockReduce 或二分后接 WholeReduce
grep -c "WholeReduceSum\|WholeReduceMax" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 4: 存在 ResetMask 恢复
grep -c "ResetMask\|SetMaskNorm" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 5: 无纯 WholeReduce 大数据量残留（主要路径）
grep -c "WholeReduceSum(.*,.*,.*,.*,.*,.*,.*,.*)" modified_files/op_kernel/*.cpp
# 期望: == 0（或仅出现在最终归约阶段）
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：`MaskMode::COUNTER` 不支持 | 使用 `SetVectorMask<uint8_t, MaskMode::COUNTER>` 模板形式 |
| 精度错（累加顺序变了） | 二分和 WholeReduce 都改变累加顺序，浮点误差可能增大；对比基线精度 |
| 性能无提升 | 数据量 < 256B 时二分 overhead 大于收益；仅在 hLength > 256B 时应用 |
| Mask 未恢复导致后续指令错 | 必须 `ResetMask(); SetMaskNorm();` 在归约结束后恢复 |
| halfNum 计算导致 UB 越界 | `srcTmp[halfNum]` 必须 < buffer 总大小；检查 `halfNum * sizeof(T)` |
| 剩余未对齐元素遗漏 | `hLength` 可能不是 16 的倍数，剩余元素需单独处理 |
| 与 P67 Counter 模式冲突 | P68 使用 COUNTER mask，P67 使用 Counter 控制流；两者可共存 |

---

**完成后在 `implementation_note.txt` 贴**：
```
[P68 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: cycle check passed (dataSize > 256B)
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
