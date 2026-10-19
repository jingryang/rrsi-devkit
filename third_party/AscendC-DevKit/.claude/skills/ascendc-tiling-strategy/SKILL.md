---
name: ascendc-tiling-strategy
description: "AscendC Tiling 分核分块策略优化：UB 占用分析、自适应核数、Main/Tail 均衡、编译验证。Use when: tiling代码需要优化或审查（硬编码核数/UB、InitBuffer与Tiling公式不一致、分配不均衡），或提到 tiling策略、分核分块、UB占用、核数分配、maxTileD、bytesPerTileD、UB利用率。通过 Agent subagent 执行。"
---

# Tiling 分核分块策略分析

## 1. 概述与执行纪律

**定位**: 实现后 tiling 优化 skill — 分析已实现的 tiling 代码，执行针对性优化，编译验证。

- **语言**: 中文分析，英文代码/标识符
- **执行方式**: 通过 Agent 工具启动 subagent 执行（不在主对话上下文中运行）
- **前置依赖**: `ascend-hardware` skill 应先执行，硬件参数已获取并作为输入传入
- **输出**: Tiling Polishing Report + 修改后的代码文件 + 编译验证结果

### 输入要求

调用方通过 Agent prompt 传入以下信息：

| 必需 | 信息 | 说明 |
|------|------|------|
| YES | 项目路径、算子名 | 据此定位代码文件 |
| YES | 硬件参数 | UB_SIZE、core_num、alignment（来自 `ascend-hardware`） |
| YES | 编译脚本路径和命令 | build.sh 或等效脚本，用于编译验证 |
| NO | 需求描述/需求文档路径 | 如有则传入，优化时必须优先满足需求约束 |
| NO | 改动要点 | 如"新增了 XX buffer"、"改了 dtype 分支"等（如有则传入） |

### 修改原则

1. **需求优先**: 如果传入了需求文档/需求描述，tiling 优化必须在满足需求约束的前提下进行（如需求指定的数据类型、shape 范围、精度要求等），不得为了优化而违反需求
2. **先分析后设计**: 读取现有 Kernel Init() 和 Tiling 代码，理解当前策略（核数如何分配、tile 如何计算、buffer 如何布局）
3. **最小化改动**: 在现有代码结构上增量调整，避免大规模重构
4. **保持代码风格**: 变量命名、函数组织、注释风格必须与原有代码保持一致，不得引入新风格
5. **明确 diff**: Report 中的"代码修改记录"应清楚标注哪些是新增、哪些是替换，便于 review

### 激活条件

**默认: ALWAYS EXECUTE** — 被 invoke 时必须执行完整分析。

仅当以下 4 个条件**全部满足**时，才可跳过（这种情况极少出现，因为大多数手写 tiling 至少会在其中一条上有不足）：

| 编号 | 条件 | 检查方法 |
|------|------|----------|
| S1 | 核数自适应 | 使用 `PlatformAscendC::GetCoreNum()` 或 `GetCoreNumAiv()` 获取硬件核数，并基于数据规模动态计算 |
| S2 | UB 分块基于 Kernel InitBuffer 精确计算 | 存在 `bytesPerTileD` + `smallBufferBytes` 公式，与 Kernel Init() 中的 InitBuffer 严格对应 |
| S3 | Main/Tail 均衡分配已实现 | 有 mainBlockFactor / tailBlockFactor 或等效逻辑，前 tailLoops 个核多处理一个 block |
| S4 | 无硬编码硬件常量 | UB size、核数等全部来自 PlatformAscendC API，无 magic number |

**检查方法**: 读取 tiling 代码，逐条验证。如果发现**任何一条**不满足，必须执行完整分析。只要发现固定核数或简单分块，就必须替换为自适应方案。

## 2. 四步分析流程

### Step 1: Kernel InitBuffer 枚举

**目标**: 从 Kernel 端 `Init()` 函数中枚举所有 `pipe_->InitBuffer` 调用，建立 Buffer 清单。

**方法**:
1. 读取 `op_kernel/*.h` 文件，定位 `Init()` 函数
2. 找到所有 `pipe_->InitBuffer(...)` 调用
3. 记录每个 buffer 的信息

**输出 — Buffer 分类表**:

将每个 buffer 分为两类：

| 分类 | 说明 | 判定方法 |
|------|------|----------|
| **A 类（随 tile 缩放）** | 大小表达式包含 tileD 或等效维度变量 | 如 `n * tileD * sizeof(T)` |
| **B 类（固定开销）** | 大小为常量或仅依赖 shape 的非 tile 维度 | 如 `alignedN * sizeof(float)` |

每个 buffer 记录：

```
| Buffer 名称 | 类型(TQue/TBuf) | 数据类型 | 大小表达式 | 队列深度 | 分类(A/B) |
```

**注意**:
- TQue 的实际 UB 占用 = `QUEUE_DEPTH * 单 buffer 大小`（双缓冲时 QUEUE_DEPTH=2）
- TBuf 无队列深度，占用 = 单 buffer 大小
- 如果存在条件分支（不同 dtype/算法路径使用不同 buffer），需分别列出每个分支的 buffer 集合

### Step 2: UB 占用公式推导

**目标**: 基于 Step 1 的 Buffer 分类表，推导 UB 占用公式并计算 maxTileD。

**方法**:

```
bytesPerTileD = Σ(A 类 buffer 的每元素开销)
  = Σ(系数_i × sizeof(type_i) × QUEUE_DEPTH_if_TQue)

smallBufferBytes = Σ(B 类 buffer 的实际大小)

availableUB  = UB_SIZE - smallBufferBytes
maxTileD     = availableUB / bytesPerTileD
maxTileD     = AlignDown(maxTileD, ALIGN_SIZE)
```

**对齐规则**:

| 数据类型 | sizeof | 对齐元素数 | 32字节对齐 |
|----------|--------|-----------|-----------|
| bf16/fp16 | 2 | 16 | 32B / 2B = 16 |
| float32 | 4 | 8 | 32B / 4B = 8 |
| int8/uint8 | 1 | 32 | 32B / 1B = 32 |
| int32 | 4 | 8 | 32B / 4B = 8 |

**输出 — UB 占用明细表**:

```
┌──────────────┬─────────────────────┬─────────┬──────────────┐
│ Buffer 类别  │ Buffer 名称         │ 分类    │ 大小(bytes)   │
├──────────────┼─────────────────────┼─────────┼──────────────┤
│ ...          │ ...                 │ A / B   │ ...          │
├──────────────┼─────────────────────┼─────────┼──────────────┤
│ 合计         │                     │         │ xxxxx bytes  │
└──────────────┴─────────────────────┴─────────┴──────────────┘

bytesPerTileD    = xxx bytes/elem
smallBufferBytes = xxx bytes
maxTileD         = xxx (对齐后)
UB 占用率        = xx.x%
```

**常见错误**:
- 忘记 TQue 的 QUEUE_DEPTH 乘数（双缓冲 ×2）
- 将 B 类 buffer 误归为 A 类（导致 maxTileD 偏小）
- 对齐方向错误：maxTileD 应 AlignDown（向下），alignedD 应 AlignUp（向上）
- sizeof 类型与 Kernel 端不一致（如 Kernel 用 float 计算但 Tiling 按 bf16 计算）

### Step 3: 核数分配策略

**目标**: 设计自适应核数计算方案，替换硬编码核数。

**方法**:

```cpp
// 获取硬件核数
auto ascendcPlatform = platform_ascendc::PlatformAscendC(context->GetPlatformInfo());
uint32_t hwCoreNum = ascendcPlatform.GetCoreNumAiv();  // 或 GetCoreNum()

// 计算总工作量（根据算子特征确定）
uint32_t totalWork = ...;  // 例如总行数、总 block 数等

// 自适应核数：不超过硬件核数，也不超过任务所需
uint32_t numCore = std::min(hwCoreNum, totalWork);

context->SetBlockDim(numCore);
```

**设计要点**:
- 总工作量的定义取决于算子的并行维度（行、batch、block 等）
- `MIN_WORK_PER_CORE` 可选：避免任务过轻（每核工作量太少，调度开销 > 计算收益）
- 对于 AIC/AIV 分离模式，使用 `GetCoreNumAiv()` 获取 AIV 核数

**Before/After 对比**:

```cpp
// BEFORE — 硬编码
const uint32_t BLOCK_DIM = 8;
context->SetBlockDim(BLOCK_DIM);

// AFTER — 自适应
uint32_t hwCoreNum = ascendcPlatform.GetCoreNumAiv();
uint32_t numCore = std::min(hwCoreNum, totalWork);
context->SetBlockDim(numCore);
```

### Step 4: Main/Tail 分配方案

**目标**: 设计均衡的工作分配方案，使各核负载尽可能均匀。

**方法**:

```cpp
// 均衡分配模式
uint32_t mainBlockFactor = totalWork / numCore;
uint32_t tailRemainder = totalWork % numCore;

// 前 tailRemainder 个核多处理 1 个 work unit
// Kernel 端判断：
//   if (blockIdx < tailRemainder)
//       myWork = mainBlockFactor + 1;
//   else
//       myWork = mainBlockFactor;
```

**设计要点**:
- 均衡分配优于"前 N-1 核等量 + 最后一核处理余量"的简单方案
- Kernel 端需要接收 `mainBlockFactor`、`tailRemainder`（或等效字段），并通过 `GetBlockIdx()` 判断自己属于哪类核
- Tiling 数据结构中需要添加对应字段

**Before/After 对比**:

```cpp
// BEFORE — 不均衡（最后一核可能负载很重或很轻）
tiling.set_coreCount(numCore - 1);
tiling.set_coreFactor(totalWork / numCore);
tiling.set_tailFactor(totalWork - (numCore - 1) * (totalWork / numCore));

// AFTER — 均衡
tiling.set_numCore(numCore);
tiling.set_mainBlockFactor(totalWork / numCore);
tiling.set_tailRemainder(totalWork % numCore);
// Kernel 端: blockIdx < tailRemainder ? mainBlockFactor+1 : mainBlockFactor
```

## 3. 双向一致性校验

**关键原则**: Kernel 端的 `pipe_->InitBuffer` 与 Tiling 端的 UB 占用公式必须**严格一一对应**。

### 校验方法

1. **正向校验**（Kernel → Tiling）: 每个 InitBuffer 在 Tiling 端公式中都有对应项
2. **反向校验**（Tiling → Kernel）: Tiling 公式中的每一项都能在 Kernel InitBuffer 中找到来源
3. **数值校验**: 将具体的 tileD 值代入 Tiling 公式，计算的总 UB 占用应与 Kernel 端实际分配一致

### 常见不一致场景

| 场景 | 表现 | 修复 |
|------|------|------|
| Kernel 新增了 buffer 但 Tiling 未更新 | 运行时 UB 溢出 | 在 Tiling 公式中增加对应项 |
| Tiling 多算了某个 buffer | maxTileD 偏小，性能损失 | 移除 Tiling 中多余的项 |
| sizeof 类型不一致 | UB 利用率异常 | 统一 Kernel/Tiling 的类型计算 |
| TQue 忘记乘 QUEUE_DEPTH | 低估 UB，运行时溢出 | 补上 ×QUEUE_DEPTH |

## 4. 多算法 TilingKey 编码

当算子存在多种处理路径时（不同 dtype、是否启用某功能、slice/non-slice 模式等），需要设计 TilingKey。

### 编码方式

使用位运算编码多个维度：

```cpp
uint32_t CalcTilingKey(ge::DataType dtype, bool featureA, bool featureB) {
    uint32_t key = 0;
    key = (key << 1) | (featureB ? 1 : 0);   // bit 0
    key = (key << 1) | (featureA ? 1 : 0);   // bit 1
    key = (key << 6) | static_cast<uint32_t>(dtype);  // bits 2-7
    return key;
}
```

### 何时需要 TilingKey

- Kernel 端有 `#if TILING_KEY_IS(...)` 或模板参数选择不同路径
- 不同数据类型使用不同 buffer 集合
- 有条件功能开关影响 UB 布局

### 何时不需要

- 所有路径使用相同的 buffer 集合和相同的 UB 公式
- 仅通过 tiling 数据中的字段区分路径

## 5. 编译验证

代码修改完成后，执行编译验证：

1. 调用项目的 build.sh（或 CMake 编译命令）
2. 如果编译失败，分析错误信息并针对性修复
3. 最多 3 轮自动修复
4. 如果 3 轮后仍失败，输出错误信息，交由开发者处理

### 常见编译错误及修复模式

| 错误模式 | 典型报错 | 修复方法 |
|----------|---------|---------|
| 缺少头文件 | `fatal error: xxx.h: No such file` | 添加对应 `#include`，tiling 相关常见: `platform_ascendc.h`, `tiling_api.h` |
| 类型不匹配 | `cannot convert 'uint64_t' to 'uint32_t'` | 添加显式 `static_cast`，注意 `GetCoreNum()` 返回值类型 |
| 未定义字段 | `has no member named 'xxx'` | 检查 tiling.h 中的 `BEGIN_TILING_DATA_DEF` 是否已添加新字段 |
| set 方法名错误 | `has no member named 'set_xxx'` | tiling data 字段名与 set_ 后缀必须一致（驼峰 vs 下划线） |
| PlatformAscendC 用法 | `no matching function` | 检查构造参数: `PlatformAscendC(context->GetPlatformInfo())` |
| 重复定义 | `multiple definition of` | 检查 tiling.h 中的 inline 函数是否有 `inline` 修饰 |

## 6. 输出报告

分析和修改完成后，按模板格式输出 Tiling Polishing Report。

报告模板详见 [references/report_template.md](references/report_template.md)。

## References

- 报告输出模板：[references/report_template.md](references/report_template.md)
- 示例和完整推导过程：[references/tiling_strategy_examples.md](references/tiling_strategy_examples.md)
- UB 分析检查清单：[references/ub_analysis_checklist.md](references/ub_analysis_checklist.md)
