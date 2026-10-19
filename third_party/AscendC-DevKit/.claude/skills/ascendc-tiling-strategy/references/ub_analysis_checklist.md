# UB 分析检查清单

在完成 Tiling Strategy Report 前，逐项检查以下 6 个域。

### 1. InitBuffer 枚举检查

- [ ] 已读取 `op_kernel/*.h` 的 `Init()` 函数
- [ ] 所有 `pipe_->InitBuffer(...)` 调用已列入枚举表
- [ ] 每个 buffer 记录了：名称、类型（TQue/TBuf）、数据类型、大小表达式、队列深度
- [ ] 条件分支中的 buffer（如不同 dtype 路径）已分别列出

### 2. 分类检查（A 类 / B 类）

- [ ] A 类（随 tile 缩放）：大小表达式包含 tileD 或等效维度变量
- [ ] B 类（固定开销）：大小为常量或仅依赖非 tile 维度
- [ ] 无遗漏：每个 buffer 都已归类
- [ ] 无误归：仔细检查边界情况（如 `n * sizeof(float)` 中 n 是否为常量）

### 3. UB 公式检查

- [ ] `bytesPerTileD` 公式正确：
  - TQue 项已乘 QUEUE_DEPTH
  - TBuf 项无 QUEUE_DEPTH
  - sizeof 类型与 Kernel 端一致
- [ ] `smallBufferBytes` 公式正确：
  - TQue 小 buffer 已乘 QUEUE_DEPTH
  - 数值与 Kernel 端大小表达式一致
- [ ] `maxTileD = (UB_SIZE - smallBufferBytes) / bytesPerTileD`
- [ ] `maxTileD` 已向下对齐（AlignDown）

### 4. 对齐规则

- [ ] bf16/fp16: 对齐到 16 元素（32B / 2B）
- [ ] float32/int32: 对齐到 8 元素（32B / 4B）
- [ ] int8/uint8: 对齐到 32 元素（32B / 1B）
- [ ] maxTileD 使用 AlignDown（向下取整）
- [ ] alignedD 使用 AlignUp（向上取整）
- [ ] 所有 buffer 基地址满足 32 字节对齐

### 5. 双向一致性

- [ ] **正向**：每个 Kernel InitBuffer → Tiling 公式中有对应项
- [ ] **反向**：Tiling 公式中每一项 → Kernel InitBuffer 中有来源
- [ ] **数值校验**：代入具体 tileD 值，计算 actualUB ≤ UB_SIZE
- [ ] **类型一致**：Kernel sizeof(T) 与 Tiling sizeof 使用相同类型

### 6. 核数分配 + Main/Tail 检查

- [ ] 核数来自 `PlatformAscendC::GetCoreNum()` 或 `GetCoreNumAiv()`，非硬编码
- [ ] `numCore = min(hwCoreNum, totalWork)` 防止核数超过工作量
- [ ] Main/Tail 均衡分配：`mainFactor = totalWork / numCore`, `tailRemainder = totalWork % numCore`
- [ ] Kernel 端正确使用 `GetBlockIdx()` 区分 main/tail 核
- [ ] `context->SetBlockDim(numCore)` 已设置
