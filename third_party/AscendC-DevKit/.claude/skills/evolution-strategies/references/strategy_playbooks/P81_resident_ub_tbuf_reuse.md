# P81 Playbook: UB/TBuf 常驻 Buffer 复用实操流程

> **强制流程**。P81 将循环内重复搬运的小参数/状态数据改造为循环外一次搬运、循环内反复复用。

## Step 1: 定位关键结构

```bash
# 1.1 循环内 DataCopy
grep -n "for.*{[^}]*DataCopy\|for.*{[^}]*CopyIn\|while.*{[^}]*DataCopy" shared/original/op_kernel/*.cpp > /tmp/p81_loc.txt

# 1.2 小参数/权重引用
grep -n "weightGm\|scaleGm\|gammaGm\|betaGm\|biasGm\|paramGm" shared/original/op_kernel/*.cpp >> /tmp/p81_loc.txt

# 1.3 循环结构
grep -n "for.*bIdx\|for.*sIdx\|for.*loop\|while.*block" shared/original/op_kernel/*.cpp >> /tmp/p81_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **循环内 DataCopy 位置**：文件 + 行号
- **小参数引用位置**：文件 + 行号
- **循环嵌套层次**：外层循环 + 内层循环

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| 参数搬运位置 | 循环内每次迭代 | 循环外 `Process()` 开头一次 | `?_kernel.cpp:L?` |
| buffer 生命周期 | 循环内 Alloc/Free | `Process()` 级常驻 | `?_kernel.cpp:L?` |
| Cast/Broadcast | 循环内每次执行 | 循环外一次执行 | `?_kernel.cpp:L?` |
| 复用次数 | 0（每次重新搬运） | `outerLoops * innerLoops` | — |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 小权重常驻**（Norm / Linear）：`weight/gamma/scale` 在 Process 开头搬入，全循环复用
- **形态 β — 状态累加器常驻**（Optimizer）：`accum/var` 状态在循环外初始化，循环内读写
- **形态 γ — 参数 Cast 后常驻**（Quant）：FP32→FP16 Cast 后常驻 UB，避免每轮重复 Cast

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α）

```cpp
// === 改造前 ===
__aicore__ inline void Process() {
    for (int64_t bIdx = 0; bIdx < baseB; ++bIdx) {
        for (int64_t sIdx = 0; sIdx < baseS; ++sIdx) {
            // 每次内循环都搬运 + Cast 权重
            DataCopyPad(weightLocal, weightGm, copyParams, padParams);
            Cast(weightFp32, weightLocal, RoundMode::CAST_NONE, alignBaseH);
            Compute(xLocalFp32, weightFp32, y0Fp32, y1Fp32, y2Fp32);
        }
    }
}

// === 改造后 ===
__aicore__ inline void Process() {
    // 循环外一次搬运 + Cast
    LocalTensor<float> weightFp32 = this->inQueueW.AllocTensor<float>();
    DataCopyPad(weightLocal, weightGm, copyParams, padParams);
    Cast(weightFp32, weightLocal, RoundMode::CAST_NONE, alignBaseH);
    
    for (int64_t bIdx = 0; bIdx < baseB; ++bIdx) {
        for (int64_t sIdx = 0; sIdx < baseS; ++sIdx) {
            // 内循环直接复用 UB 中的权重
            Compute(xLocalFp32, weightFp32, y0Fp32, y1Fp32, y2Fp32);
        }
    }
    
    // Process 结束前释放
    this->inQueueW.FreeTensor(weightFp32);
}
```

### 3C. Variant Notes

- **形态 β（状态累加器）**：状态 buffer 在 `Init()` 或首次循环初始化，后续循环读取+更新
- **形态 γ（Cast 后常驻）**：若参数需 Cast，循环外 Cast 一次；注意 Cast 后的 buffer 类型匹配
- **若参数尺寸 > UB 预算**：放弃常驻，改用 P34 权重一次加载（L1 常驻）或 P8 UB 分区

## Step 4: 约束复核

**公式**：
```
常驻 buffer 大小 = paramSize * sizeof(paramType)
约束 1: 常驻 buffer + 主数据 tile * bufferNum <= UB_TOTAL * 0.8
约束 2: 复用次数 >= 4（搬运开销摊平阈值）
约束 3: 常驻期间参数不会被其他核修改（无并发写）
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: 存在循环外 AllocTensor / DataCopy
grep -c "AllocTensor.*Process\|DataCopy.*Process\|Cast.*Process" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 2: 循环内无参数 DataCopy 残留
grep -c "for.*{[^}]*DataCopy.*weight\|for.*{[^}]*DataCopy.*scale\|for.*{[^}]*DataCopy.*gamma" modified_files/op_kernel/*.cpp
# 期望: == 0

# 检查 3: 存在循环外 FreeTensor
grep -c "FreeTensor.*Process\|FreeTensor.*loop" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 4: 参数在循环内被复用
grep -c "weightFp32\|scaleLocal\|gammaLocal.*Compute\|paramLocal.*loop" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 5: 无循环内 Cast 残留（主要参数）
grep -c "for.*{[^}]*Cast.*weight\|for.*{[^}]*Cast.*scale" modified_files/op_kernel/*.cpp
# 期望: == 0
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：UB overflow | 回 Step 4；常驻 buffer 过大时放弃 P81，改用 P34 L1 常驻 |
| 数据竞争（参数被覆盖） | TBuf/VECCALC 不受队列同步保护，需 `PipeBarrier<PIPE_V>()` 在复用前 |
| 参数在循环中被修改 | 常驻 buffer 只读；若需更新（如优化器状态），用形态 β 读写模式 |
| 多核间参数不一致 | 各核独立搬运一份参数到 UB，不共享（天然一致） |
| Cast 开销未摊平 | 复用次数 <4 时，循环外 Cast 的 overhead 可能不划算 |
| TQue 生命周期管理 | `AllocTensor` 在 `Process()` 开头，`FreeTensor` 在结尾，禁止循环内 Alloc/Free |
| 与 P1 双缓冲冲突 | 常驻 buffer 压缩了双缓冲可用空间，需同步减小 tileSize |

---

**完成后在 `implementation_note.txt` 贴**：
```
[P81 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: UB calc passed (resident=... + tile=... <= UB_TOTAL*0.8)
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
