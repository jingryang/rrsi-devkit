---
name: ascendc-dev-dev-record-template
description: "ascendc-dev skill 开发记录的总览模板。当前开发记录已目录化为多个文件（requirements.md / clarification.md / coding_plan.md / progress.md / history.log / env_snapshot.md / coding_index.md），本文件作为各章节格式参考，标注每个章节实际写入的目标文件。"
---

# {OpName} 算子开发记录（总览模板）

> **重要说明**：本模板是**格式参考**。当前 `ascendc-dev` skill 的开发记录已采用**目录化结构**：
> ```
> {OpName}_dev_{YYYYMMDD_HHmmss}/
> ├── meta.json              # 结构化元信息
> ├── env_snapshot.md        # Session 环境快照（对应本模板 §元信息 → Session 环境快照）
> ├── requirements.md        # 需求摘要 + 架构概述 + 参考算子映射 + 变更点明细（对应 §1~§5）
> ├── clarification.md       # ⚠️ 不明确项清单 + 澄清记录（对应 §⚠️ 和 §9.1）
> ├── coding_index.md        # Stage 4 步骤级编码导航索引
> ├── coding_plan.md         # 文件级编码状态跟踪（见 coding-plan-template.md）
> ├── progress.md            # 当前进度表（对应 §7）
> ├── history.log            # 纯文本历史追加（对应 §9 中 ERROR/NEEDS_AGENT/CTX_DRIFT 等事件）
> └── issues/                # Issue 文件目录
> ```
> 各 SubAgent 应把对应内容写入上述目标文件，而不是生成单个 monolithic 文档。

---

## 元信息

> **实际写入文件**：`meta.json`（结构化字段）+ `env_snapshot.md`（Session 环境快照章节）。

```markdown
> **生成时间**: {YYYY-MM-DD HH:mm:ss}
> **最后更新**: {YYYY-MM-DD HH:mm:ss}
> **生成工具**: ascendc-dev skill
> **开发模式**: {存量改造 / 新增开发}
> **算子名称**: {OpName}
> **代码路径**: {code_path}
> **目标芯片**: {chip_model}
> **编程模型**: {A3 Membase / A5 Regbase / 不适用（纯 Cube）}
> **UB 大小**: {ub_size} bytes
> **核数**: {core_num}
> **编译指令**: {编译命令 / 待确认}
> **重试计数器**:
>   - Stage5 编译重试已用: 0 / 累计上限 24
>   - Stage4 自检重试已用: 0 / 累计上限 8
>   - s5_rollback 回退已用: 0 / 累计上限 2
> **当前 Stage**: 1
> **最后门控结果**: -
```

### Session 环境快照

> **实际写入文件**：`env_snapshot.md`
> 由 Stage 1 (s1-env) 写入，Stage 4/5 读取复用。> 复用规则见 [`env-and-platform.md`](env-and-platform.md) §3.5；用户说"重新检查环境"时整段删除，由 s1-env 重建。

- 写入时间: {YYYY-MM-DD HH:MM:SS}
- 缓存日期: {YYYY-MM-DD}  <!-- 复用判定以写入时间距今 < 24h 为准 -->
- 芯片型号: {chip_name}  <!-- npu-smi info / asys info -->
- 芯片代号: {A2 | A3 | A5}  <!-- d802→A2, d803→A3, d806→A5 -->
- 编程模型: {A3 Membase | A5 Regbase | 不适用（纯 Cube）}
- 驱动库路径: {driver_dir}  <!-- /usr/local/Ascend/driver/lib64/driver -->
- LD_LIBRARY_PATH 状态: {OK | MISSING}
  - 若 MISSING：请在父 shell 中执行 `export LD_LIBRARY_PATH={driver_dir}:$LD_LIBRARY_PATH`（Bash 工具内 export 不会跨调用保留）
- ASCEND_TOOLKIT_HOME: {path}
- ASCEND_HOME_PATH: {path | NOT SET}
- ASCEND_OPP_PATH: {path | NOT SET}
- UB 大小: {UB_SIZE}
- 核数: {CORE_NUM}
- 带宽: {BANDWIDTH}
- 对齐要求: {ALIGN}  <!-- 例: 32B -->

---

## ⚠️ 不明确项清单

> **实际写入文件**：`clarification.md`（置顶）
> 所有项必须在 Stage 3 中逐一澄清后才能进入 Stage 4 编码。

| # | 维度 | 问题描述 | 状态 | 澄清结论 |
|---|------|----------|------|----------|
| 1 | 条件分支 | {例：对齐 vs 非对齐场景是否都需要支持？} | 待澄清 | - |
| 2 | 边界情况 | {例：tail block 如何处理？} | 待澄清 | - |
| 3 | 回退行为 | {例：可选输入缺失时的默认行为？} | 待澄清 | - |
| 4 | 并行策略 | {例：多核分核策略？} | 待澄清 | - |
| 5 | 默认值 | {例：新增属性的默认值？} | 待澄清 | - |

**维度说明**：
- **条件分支**: 条件分支路径（对齐/非对齐、可选输入有无、不同 dtype 处理）
- **边界情况**: 边界/边缘情况（tail blocks、空 tensor、零长度维度、单元素输入）
- **回退行为**: 回退行为（可选输入缺失、属性不存在时的处理）
- **并行策略**: 并行策略（单核 vs 多核、分核方式、核间数据依赖）
- **默认值**: 默认值（新增属性、配置项的初始值）

---

## 1. 基本信息

> **实际写入文件**：`requirements.md`

| 项目 | 内容 |
|------|------|
| 开发模式 | {存量改造 / 新增开发} |
| 算子名称 | {OpName} |
| 代码路径 | {code_path} |
| 芯片型号 | {chip_model} |
| UB 大小 | {ub_size} bytes |
| 核数 | {core_num} |
| 设计文档来源 | {详设文档路径 / 简易文档路径 / 其他} |
| Golden 参考实现 | {路径 / 无} |
| 编译指令 | {编译命令 / 待确认} |

---

## 📌 参考算子映射

> **实际写入文件**：`requirements.md`> Stage 1.2 #3 收集、Stage 2 细化、Stage 3 确认。记录本次变更点与参考算子实现的对应关系。如无参考算子，标注"无参考算子"。

| # | 变更点/特性 | 参考算子 | 参考文件路径 | 起始行号 | 参考内容说明 | 复用/调整 |
|---|-----------|---------|-------------|---------|-------------|---------|
| 1 | {特性名/模块名} | {参考算子名} | {文件路径} | {行号} | {参考了什么} | 直接复用/需调整：{说明} |

---

## 2. 需求摘要

> **实际写入文件**：`requirements.md`

### 2.1 需求概述

{一段话描述本次开发的整体目标和背景}

### 2.2 变更点列表

| # | 变更点名称 | 变更类型 | 简要描述 |
|---|-----------|----------|---------|
| 1 | {名称} | 新增/修改/删除 | {一句话描述} |

---

## 3. 代码架构概述

> **实际写入文件**：`requirements.md`

### 3.1 文件清单

| 文件路径 | 用途 | 关键内容 |
|----------|------|---------|
| `op_host/{op}_tiling.h` | TilingData 定义 | {现有字段概要} |
| `op_host/{op}_tiling.cpp` | Tiling 策略 | {现有策略概要} |
| `op_host/{op}_def.cpp` | OpDef 定义 | {输入/输出/属性概要} |
| `op_kernel/{op}.h` | Kernel 实现 | {处理流程概要} |
| `op_kernel/{op}.cpp` | Kernel 入口 | {TilingKey 分支概要} |
| `CMakeLists.txt` | 构建配置 | {依赖概要} |

### 3.2 现有 TilingData 结构

```cpp
// 从 *_tiling.h 中提取
{现有 TilingData 结构体定义}
```

### 3.3 现有 Tiling 策略

{描述现有的分核分块策略、TilingKey 设置逻辑}

### 3.4 Kernel 处理流程

{描述现有的 Init → CopyIn → Compute → CopyOut 流程}

---

## 4. 变更点明细

> **实际写入文件**：`requirements.md`

### 4.1 变更点: {名称}

- **影响文件**:
  - `{file1}` — {修改内容}
  - `{file2}` — {修改内容}
- **变更类型**: 新增/修改/删除
- **设计决策**: {为什么这样设计，考虑了哪些替代方案}
- **实现要点**:
  - {要点 1}
  - {要点 2}
- **注意事项**: {对齐要求、同步需求、与其他变更点的依赖关系}

<!-- 每个变更点一个子章节，按 4.1, 4.2, 4.3... 编号 -->

---

## 5. 用例数据流分析

> **实际写入文件**：`requirements.md`> 如无用例规格，本章节可标注"暂无"。

| 用例规格 | 变更前 TilingKey | 变更后 TilingKey | 变更前 Kernel 路径 | 变更后 Kernel 路径 | 变化说明 |
|----------|-----------------|-----------------|-------------------|-------------------|---------|
| `{shape, dtype, ...}` | KEY_0 | KEY_1 | {路径描述} | {路径描述} | {说明} |

**边界用例关注点**：
- [ ] tail block 场景是否覆盖
- [ ] 极小 shape 场景是否覆盖
- [ ] 特殊 dtype 场景是否覆盖

---

## 6. 编码计划

> **实际写入文件**：`coding_plan.md`> 详见 [`coding-plan-template.md`](coding-plan-template.md)。本章节在 monolithic 模板中保留，实际已拆分到独立文件。

| 序号 | 文件 | Sub-stage | 状态 | 备注 |
|------|------|-----------|------|------|
| 1 | `*_tilingdata.h` | A | 待开始 | |
| 2 | `*_def.cpp` | B1 | 待开始 | |
| 3 | `*_tiling.h` | B2 | 待开始 | |
| 4 | `*_tiling.cpp` | B2 | 待开始 | |
| 5 | `op_kernel/*.cpp` | C.0 | 待开始 | |
| 6 | `op_kernel/*.h` | C.1~C.n | 待开始 | |
| 7 | `CMakeLists.txt` | E | 待开始 | |

---

## 7. 当前进度

> **实际写入文件**：`progress.md`
> 由 `dev_record.sh init` 初始化，`dev_record.sh set-progress` 更新。

| Stage | 状态 | 完成时间 | 备注 |
|-------|------|---------|------|
| 1 环境确认 | ❌ | - | - |
| 2 需求分析 | ❌ | - | - |
| 3 需求澄清 | ❌ | - | - |
| 4.0 编码前置 | ❌ | - | - |
| 4.A 数据结构层（TilingData） | ❌ | - | - |
| 4.B1 OpDef + InferShape | ❌ | - | - |
| 4.B2 Host Tiling | ❌ | - | - |
| 4.C Kernel 实现 | ❌ | - | 由 `expand-kernel` 展开为 C.0~C.n |
| 4.E 构建配置（CMakeLists） | ❌ | - | - |
| 4.F 编码后自检 | ❌ | - | - |
| 5 编译出包 | ❌ | - | - |

**状态说明**: ✅ 已完成 | ⏳ 进行中 | ❌ 未开始 | 🔄 需重做

---

## 8. Issue 注册表

> **实际写入文件**：`requirements.md` 或独立 `issues/issue_{YYYYMMDD}_{关键词}.md`
> 复杂问题创建独立 Issue 文件后在此注册。

| # | 创建时间 | 关键词 | 错误类型 | 状态 | Issue 文件 |
|---|---------|--------|---------|------|-----------|

---

## 9. 历史记录

> **实际写入文件**：`history.log`（纯文本追加）+ `progress.md` / `clarification.md` / `requirements.md` 中的对应表格。
> `history.log` 格式：`[{YYYY-MM-DD HH:mm}] [事件类型] 描述`。

### 9.1 澄清记录

> **实际写入文件**：`clarification.md`

| 时间 | 不明确项# | 问题 | 澄清结论 |
|------|----------|------|----------|

### 9.2 编译记录

> **实际写入文件**：`requirements.md`

| 时间 | 编译指令 | 结果 | 错误类型 | 错误信息 | 根因分析 | 修复方案 | 重试# |
|------|---------|------|---------|---------|---------|---------|------|

### 9.3 迭代记录

> **实际写入文件**：`requirements.md` 或 `history.log`
> 状态观测协议：每次状态转换追加一行。
> 事件类型: `STAGE_START` / `STAGE_COMPLETE` / `GATE_PASS` / `GATE_FAIL` / `GATE_OVERRIDE` / `ERROR` / `REGRESSION` / `RESUME` / `PAUSED` / `NEEDS_AGENT` / `AGENT_COMPLETE`。

| 时间 | 事件类型 | 描述 |
|------|---------|------|

### 9.4 Tiling 优化记录

> **实际写入文件**：`requirements.md`
> `ascendc-tiling-strategy` skill 执行后追加。

| 时间 | 优化内容 | 优化前指标 | 优化后指标 |
|------|---------|-----------|-----------|
