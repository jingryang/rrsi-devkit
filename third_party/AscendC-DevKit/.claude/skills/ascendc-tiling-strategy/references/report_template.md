# Tiling Polishing Report 输出模板

分析和修改完成后，**必须**按以下格式输出 Tiling Polishing Report：

```markdown
## Tiling Polishing Report

### 1. 算子概况
- **算子名称**: {op_name}
- **并行维度**: {哪个维度用于多核并行}
- **tile 维度**: {哪个维度用于 UB 内分块}
- **数据类型**: {主要数据类型}
- **当前问题**: {发现的问题，如硬编码核数/固定 tile 大小/不均衡分配}

### 2. UB 占用分析

#### 2.1 InitBuffer 枚举表

| # | Buffer 名称 | 类型 | 数据类型 | 大小表达式 | 队列深度 | 分类 |
|---|------------|------|---------|-----------|---------|------|
| 1 | ...        | TQue | bf16    | ...       | 2       | A    |
| 2 | ...        | TBuf | float32 | ...       | -       | B    |

#### 2.2 UB 公式推导

```
bytesPerTileD    = {公式} = {数值} bytes/elem
smallBufferBytes = {公式} = {数值} bytes
availableUB      = {UB_SIZE} - {smallBufferBytes} = {数值} bytes
maxTileD         = {availableUB} / {bytesPerTileD} = {数值}
maxTileD(aligned) = AlignDown({数值}, {ALIGN}) = {最终值}
```

#### 2.3 UB 占用明细表

（带具体 tileD 值的明细表，格式见 SKILL.md Step 2）

### 3. 核数分配方案

（包含 Before/After 代码片段）

### 4. Main/Tail 分配方案

（包含 Before/After 代码片段）

### 5. TilingKey 编码（如适用）

（仅当存在多路径时输出）

### 6. 需修改的文件及修改要点

| 文件 | 修改要点 |
|------|---------|
| `op_host/*_tiling.h` | 新增/修改 tiling 数据字段 |
| `op_host/*_tiling.cpp` | 替换核数计算、UB 分块公式、Main/Tail 分配 |
| `op_kernel/*.h` | 适配新 tiling 字段（如有） |
| `op_kernel/*.cpp` | 适配 blockDim 变化（如有） |

### 7. 双向一致性校验结果

- [ ] 每个 InitBuffer 在 Tiling 公式中有对应项
- [ ] Tiling 公式中每一项在 Kernel InitBuffer 中有来源
- [ ] 数值代入校验通过（actualUB ≤ UB_SIZE）
- [ ] 无硬编码硬件常量

### 8. 代码修改记录

| 文件 | 修改类型 | 修改内容摘要 |
|------|---------|-------------|
| `op_host/*_tiling.cpp` | 替换 | 核数计算改为自适应、UB 公式精确化 |
| `op_host/*_tiling.h` | 新增字段 | mainBlockFactor, tailRemainder |

### 9. 编译验证结果

- [ ] 编译通过（build.sh）
- 修复轮次: X/3
- 修复内容: {如有编译错误，记录修复过程}
```
