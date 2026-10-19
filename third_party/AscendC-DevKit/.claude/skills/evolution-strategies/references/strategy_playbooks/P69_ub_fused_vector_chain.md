# P69 Playbook: UB 融合连续 Vector 计算链实操流程

> **强制流程**。P69 将多步 Vector 计算间的 GM 往返改造为 UB 内连续计算链，GM 搬运从 2n 次降至 2 次。

## Step 1: 定位关键结构

```bash
# 1.1 Vector 计算序列
grep -n "\bAdd\b\|\bMul\b\|\bSub\b\|\bCast\b\|\bExp\b\|\bAbs\b\|\bSqrt\b" shared/original/op_kernel/*.cpp > /tmp/p69_loc.txt

# 1.2 CopyIn / CopyOut 位置
grep -n "CopyIn\|CopyOut\|DataCopy.*Gm\|DataCopy.*outputGm" shared/original/op_kernel/*.cpp >> /tmp/p69_loc.txt

# 1.3 队列定义
grep -n "TQue.*VECIN\|TQue.*VECOUT\|TBuf.*VECCALC\|InitBuffer" shared/original/op_kernel/*.cpp shared/original/op_kernel/*.h >> /tmp/p69_loc.txt
```

**交付物**（`implementation_note.txt` "Playbook Step 1"）：
- **Vector 计算链**：文件 + 行范围（连续 Vector 指令）
- **CopyIn / CopyOut 位置**：文件 + 行号
- **队列定义**：文件 + 行号

## Step 2: 改造计划表（强制填写）

**不填完此表不得进入 Step 3**：

| 元素 | 当前值 | 目标值 | 修改位置 |
|---|---|---|---|
| 计算方式 | `CopyIn → Compute1 → CopyOut → CopyIn1 → Compute2 → CopyOut1` | `CopyIn → Compute1 → Compute2 → CopyOut` | `?_kernel.cpp:L?` |
| 中间结果存储 | GM | UB (VECCALC buffer) | `?_kernel.cpp:L?` |
| GM 搬运次数 | `2n` | `2` | `?_kernel.cpp:L?` |
| 队列结构 | VECIN + VECOUT | VECIN + VECCALC + VECOUT | `?_kernel.cpp:L?` |

## Step 3: 代码改造（核心）

### 3A. 形态识别

- **形态 α — 单输入多步计算**（Exp→Abs→Scale）：中间结果始终在 UB
- **形态 β — 多输入融合**（Add→Mul→Cast）：多输入搬入后全部计算在 UB 完成
- **形态 γ — 原地计算链**（x = f(g(x))）：输入 buffer 复用为输出 buffer

**必须在 implementation_note.txt 声明**：`form: alpha | beta | gamma`

### 3B. Canonical Template（形态 α）

```cpp
// === 改造前 ===
// GM → UB → Exp → UB → GM
CopyIn(0);
Exp(dstLocal, srcLocal, tileSize);
CopyOut(0);

// GM → UB → Abs → UB → GM
CopyIn1(0);
Abs(dstLocal1, srcLocal1, tileSize);
CopyOut1(0);

// === 改造后 ===
// 定义 VECCALC buffer
AscendC::TBuf<AscendC::TPosition::VECCALC> calcBuf;
pipe.InitBuffer(calcBuf, tileSize * sizeof(T));

// 一次 CopyIn
LocalTensor<T> srcLocal = inQueue.DeQue<T>();
LocalTensor<T> calcLocal = calcBuf.Get<T>();
LocalTensor<T> dstLocal = outQueue.AllocTensor<T>();

// UB 内连续计算链
Exp(calcLocal, srcLocal, tileSize);     // VECIN → VECCALC
Abs(dstLocal, calcLocal, tileSize);      // VECCALC → VECOUT (或继续链)

// 一次 CopyOut
outQueue.EnQue<T>(dstLocal);
inQueue.FreeTensor(srcLocal);
```

### 3C. Variant Notes

- **形态 β（多输入）**：所有输入 `CopyIn` 到 VECIN，计算链使用 VECCALC 中转，最终 VECOUT
- **形态 γ（原地）**：`dstLocal` 与 `srcLocal` 指向同一 UB 区域，无需额外 buffer
- **若计算链过长**：超过 3-4 步时 VECCALC buffer 可能不足，拆分为 2 个子链

## Step 4: 约束复核

**公式**：
```
UB 占用 = VECIN_size + VECCALC_size + VECOUT_size
         = tileSize * sizeof(T) * (input_count + 1 + output_count)
约束 1: UB 占用 <= UB_TOTAL * 0.8
约束 2: VECCALC buffer 32B 对齐：`tileSize * sizeof(T) % 32 == 0`
约束 3: 计算链中无数据依赖冲突（后一步输入是前一步输出）
```

在 `implementation_note.txt` 报告具体数值和是否通过。

## Step 5: 编码后自检（5 条 grep，全部必须过）

```bash
# 检查 1: 使用了 VECCALC buffer
grep -c "VECCALC\|TBuf.*VECCALC\|calcBuf\|intermediate" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 2: CopyIn / CopyOut 次数减少
grep -c "CopyIn\|CopyOut\|DataCopy.*Gm" modified_files/op_kernel/*.cpp
# 期望: <= 原始数量 * 0.6（显著减少）

# 检查 3: Vector 计算链连续（无中间 CopyOut）
grep -A2 "Exp\|Abs\|Add\|Mul" modified_files/op_kernel/*.cpp | grep -c "CopyOut\|DataCopy"
# 期望: == 0（Vector 计算间无 GM 搬运）

# 检查 4: 输入 DeQue 与输出 EnQue 配对
grep -c "DeQue.*EnQue\|AllocTensor.*EnQue" modified_files/op_kernel/*.cpp
# 期望: >= 1

# 检查 5: 无独立中间结果 CopyOut 残留
grep -c "outQueue.*EnQue.*calc\|CopyOut.*intermediate" modified_files/op_kernel/*.cpp
# 期望: == 0
```

任一失败 → 回 Step 3 重做。

## Step 6: Known Pitfalls

| 现象 | 修复 |
|---|---|
| 编译失败：UB overflow | 回 Step 4；减小 tileSize 或拆分计算链 |
| VECCALC buffer 未对齐 | `InitBuffer(calcBuf, AlignUp(tileSize * sizeof(T), 32))` |
| 数据竞争（计算未结束就 EnQue） | Vector 指令异步执行，需 `PipeBarrier<PIPE_V>()` 在 EnQue 前 |
| 计算链中有分支依赖 | 若某步结果决定下步路径（如条件判断），无法链式融合 |
| 精度错（中间结果截断） | 若输入 FP32、中间 FP16、输出 FP32，中间 Cast 可能损失精度 |
| 性能无提升 | 检查是否计算步骤 <2（单步计算无融合收益） |
| TQue 模板参数不匹配 | `TBuf<VECCALC>` 获取的 `LocalTensor<T>` 类型必须与计算指令一致 |

---

**完成后在 `implementation_note.txt` 贴**：
```
[P69 Playbook Completion]
Step 1: done
Step 2: plan table filled
Step 3: form = alpha/beta/gamma
Step 4: UB calc passed (VECCALC included, total <= UB_TOTAL*0.8)
Step 5: all 5 grep checks passed
Step 6: no pitfalls / {列出触发的}
```
