# 环境快照与平台路由规范

> 本文件统一定义芯片检测→平台路由→环境快照的完整数据链。Stage 1 写入，Stage 3 可修正编程模型，Stage 4/5 只读。

---

## §1 平台对照表

| 平台代号 | 芯片型号 | 编程模型 | Vector Pipeline 特征 |
|---------|---------|---------|---------------------|
| **A2** | 310, 310P, 610, 910 | A3 Membase | `LocalTensor` + `DataCopy` + `TILING_KEY_IS` |
| **A3** | 910B, 910C | A3 Membase | 同上 |
| **A5** | 910D, 950PR, 950DT (351x) | A5 Regbase | `RegTensor` + `VF_CALL`/`asc_vf_call` + SIMD/SIMT 混合 |

> **重要说明**：A3 Membase 与 A5 Regbase 的差异**主要体现在 Vector Pipeline 的计算部分及相关 API**（如搬运接口 DataCopy vs LoadAlign/StoreAlign、内存模型 LocalTensor vs RegTensor）。纯 Cube/Matmul 算子（不经过 Vector Pipeline）的编程模型不受平台影响，高阶 API 在各平台通用。只有以下两类场景需要区分：
> 1. **纯 Vector 算子**（elementwise、reduction、activation 等）
> 2. **融合算子中的 Vector 部分**（如 GEMM + Add 中的 Add 部分）

---

## §2 路由判定逻辑

```
INPUT: chip_model（来自 ascend-hardware skill）, 算子类型（从需求/代码推断）
OUTPUT: 编程模型 字段值

# 规范化 chip_model：去掉首尾空白和 "Ascend" 前缀（如 Ascend950DT -> 950DT）
normalized_model = chip_model.strip()
if normalized_model.startswith("Ascend"):
    normalized_model = normalized_model[len("Ascend"):]

IF 算子不涉及 Vector Pipeline（纯 Cube/Matmul）:
  编程模型 = "不适用（纯 Cube）"
ELIF normalized_model ∈ {310, 310P, 610, 910, 910B, 910C} 或 normalized_model 以上述前缀开头:
  编程模型 = "A3 Membase"
ELIF normalized_model ∈ {910D, 950PR, 950DT, 351x} 或 normalized_model 以上述前缀开头:
  编程模型 = "A5 Regbase"
ELSE:
  报错：未知芯片型号，请用户确认
```

### 编码路径映射

| 编程模型 | s4-coding 路径 | Sub-stage 序列 | C 系列拆分模板 |
|---------|---------------|---------------|---------------|
| 不适用（纯 Cube） | 路径一 | 4.0 → A → B1 → B2 → C.0~C.n → E → F | C.0 入口+调度，C.1 Matmul/Conv 初始化与主循环（简单算子可合并） |
| A3 Membase | 路径二 | 4.0 → A → B1 → B2 → C.0~C.n → E → F | C.0 TILING_KEY_IS 路由，C.1 类框架，C.2 CopyIn，C.3 Compute，C.4 CopyOut |
| A5 Regbase | 路径三 | 4.0 → A → B1 → B2 → C.0~C.n → C.{N}.VT.{M}（按 VF 函数逐个调度）→ E → F | 4.0 一次性完成 A5 前置文档读取；C.0 入口，C.1 类框架，C.2 CopyIn，C.3 Compute（Regbase / VF_CALL），C.4 CopyOut |

原已废弃的独立 Kernel 入口行已被 `C.0` 吸收，不再单独存在。

### 各 Stage 的路由职责

| Stage | 路由相关动作 |
|-------|-------------|
| Stage 1 (s1-env) | **写入**：检测芯片 → 判定编程模型 → 写入 dev record header |
| Stage 3 (s3-clarify) | **可修正**：澄清中发现算子类型判断有误时修正编程模型 |
| Stage 4 (s4-coding) | **只读**：从 dev record header 读取，选择编码路径 |
| Stage 5 (s5-compile) | **只读**：无路由动作 |

### 字段格式（dev record header 必须严格匹配）

`编程模型` 字段只允许以下 3 个字面值（供门控和条件判断使用）：
- `A3 Membase`
- `A5 Regbase`
- `不适用（纯 Cube）`

任何其他值视为异常，Stage 3 快速通道将不触发（fallback 到正常 s3-clarify 流程）。

---

## §3 环境快照管理

### §3.1 为什么需要缓存

- `npu-smi info` 和 `asys info` 在 `/clear` 后虽然父 shell 保留，但每个 Stage 的 SubAgent 是独立 context
- 同一 dev record 在一天内通常环境不变，重查浪费 token 且用户体验差
- `/clear` 会清空活跃 context，但不会删除磁盘文件；快照放在 dev record 中可跨 `/clear` 恢复

### §3.2 缓存位置

`{OpName}算子开发记录_{YYYYMMDD_HHmmss}.md` 的 `## 元信息` 下的 `### Session 环境快照` 章节。

### §3.3 快照字段

| 字段 | 必填 | 来源 |
|------|------|------|
| 写入时间 | 是 | `YYYY-MM-DD HH:MM:SS`（快照生成时刻） |
| 缓存日期 | 是 | `YYYY-MM-DD`（保留用于人类可读；复用判定以 `写入时间` 距今 < 24h 为准） |
| 芯片型号 | 是 | `npu-smi info` 或 `asys info` |
| 芯片代号 | 是 | 归一化：d802→A2, d803→A3, d806→A5 |
| 编程模型 | 是 | 由芯片代号决定：A3 Membase / A5 Regbase / 不适用（纯 Cube） |
| 驱动库路径 | 是 | `/usr/local/Ascend/driver/lib64/driver` |
| LD_LIBRARY_PATH 状态 | 是 | `OK` 或 `MISSING` |
| LD_LIBRARY_PATH 设置提示 | 条件 | 当状态为 `MISSING` 时给出可执行命令 |
| ASCEND_TOOLKIT_HOME | 是 | env 取值 |
| ASCEND_HOME_PATH | 是 | env 取值（NOT SET 时显式标注） |
| ASCEND_OPP_PATH | 是 | env 取值（NOT SET 时显式标注） |
| UB 大小 | 是 | `ascend-hardware` skill 输出 |
| 核数 | 是 | `ascend-hardware` skill 输出 |
| 带宽 | 是 | `ascend-hardware` skill 输出 |
| 对齐要求 | 是 | `ascend-hardware` skill 输出 |

### §3.3.1 快照内容模板

`s1-env` 必须一次性将以下内容写入 `env_snapshot.md`（可直接复制本模板并替换占位符），**禁止留空文件**：

```markdown
### Session 环境快照

- 写入时间: {YYYY-MM-DD HH:MM:SS}
- 缓存日期: {YYYY-MM-DD}
- 芯片型号: {chip_model}
- 芯片代号: {A2 | A3 | A5}
- 编程模型: {A3 Membase | A5 Regbase | 不适用（纯 Cube）}
- 驱动库路径: /usr/local/Ascend/driver/lib64/driver
- LD_LIBRARY_PATH 状态: {OK | MISSING}
- LD_LIBRARY_PATH 设置提示: {若 MISSING，填入 `export LD_LIBRARY_PATH=/usr/local/Ascend/driver/lib64/driver:$LD_LIBRARY_PATH`}
- ASCEND_TOOLKIT_HOME: {值 或 NOT SET}
- ASCEND_HOME_PATH: {值 或 NOT SET}
- ASCEND_OPP_PATH: {值 或 NOT SET}
- UB 大小: {ub_size}
- 核数: {core_num}
- 带宽: {peak_bw_gbps}
- 对齐要求: {alignment_bytes}
```

> **非空校验**：s1-env 返回 `COMPLETED` 前必须确认 `env_snapshot.md` 包含上述全部字段；缺失任一字段视为验收失败。

**仅 `ascendc-dev-s1-env`（Stage 1 SubAgent）可写入或覆盖快照**。

- 场景 A（新任务）：s1-env 完成完整环境检查后写入快照
- 场景 B 恢复且快照缺失/过期：如当前 Stage == 1，s1-env 写入快照
- s4-coding / s5-compile **只读不写**

### §3.5 缓存读取/复用规则

**复用判定**：快照 `写入时间` 距当前时间 **< 24 小时** 即视为可用（不再以日期边界判断，避免跨午夜工作时快照突然过期）。

| 条件 | 主 SKILL 动作 | SubAgent 动作 |
|------|---------------|---------------|
| 快照存在，写入时间距今 < 24h | 将快照内容注入 SubAgent prompt | s4/s5 直接读取并使用；s1 跳过检查 |
| 快照存在，写入时间距今 ≥ 24h | 标记"快照过期" | Stage 1：s1-env 重查覆盖；Stage 4/5：按 SubAgent 内部逻辑按需检查 |
| 快照不存在 | 标记"快照缺失" | 同"过期"处理 |
| 用户说"重新检查环境" | 主 SKILL 用 Edit 删除快照所在章节 | 重调度 s1-env，由其重建快照 |

### §3.6 LD_LIBRARY_PATH 特别提示

Bash 工具的 `export` **不会跨调用保留**（这是 Claude Code Bash tool 的既定行为）。因此：

- 若 `LD_LIBRARY_PATH 状态 = MISSING`：dev record 中的"LD_LIBRARY_PATH 设置提示"必须给出**父 shell 可执行**的命令（如 `export LD_LIBRARY_PATH=/usr/local/Ascend/driver/lib64/driver:$LD_LIBRARY_PATH`），并注明需在**启动 claude 的父 shell** 中执行，而不是在 Bash tool 中 export。
- 若用户希望每次 Bash 调用都自动带环境变量，应使用 `CLAUDE_ENV_FILE` 或 `SessionStart` hook——这不在本 Skill 范围内，可在用户遇到环境问题时口头提示。

### §3.7 失效边界

- **24h 窗口复用**：以 `写入时间` 字段与当前时间比较，差值 < 24h 即复用（跨午夜不会突然失效）
- **跨 session 复用**：dev record 文件存在即可复用（只要写入时间在 24h 内）
- **跨 `/clear` 复用**：快照在磁盘文件中，`/clear` 不影响
- **跨机器 / 多终端**：只要读到同一 dev record（例如同一 Git 仓库 checkout），即按文件内快照复用
