# SubAgent 通用协议

> 本文件统一定义所有 ascendc-dev SubAgent 的 3 项公共协议：输入参数要求、失败处理记录、返回格式。各 SubAgent 文档只需一行引用本文件，无需重复完整规则。

---

## §A 输入参数要求

主 SKILL 调度 SubAgent 时，以下字段随 prompt 注入供 SubAgent 使用。SubAgent **不做输入缺失的运行时校验**，直接按约定使用注入参数；缺失时的行为由各 SubAgent 业务逻辑按需兜底（如从 dev record 读取、向用户确认）。

### 各 SubAgent 声明格式

各 SubAgent 只需列出**输入参数表**（参数名 / 来源 / 说明），无需描述校验行为：

```markdown
## §0 输入要求

> 输入参数约定见 [`references/subagent-common-protocol.md`](../skills/ascendc-dev/references/subagent-common-protocol.md) §A。

| 参数 | 来源 | 说明 |
|------|------|------|
| {参数1} | 主 SKILL prompt | {用途说明} |
```

### 各 SubAgent 输入参数对比

| 参数 | s1 | s2 | s3 | s4 | s5 | vf-test | 说明 |
|------|----|----|----|----|----|----|----| 
| SKILL_ROOT | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | skill 根目录绝对路径，脚本调用前缀 |
| AGENT_ROOT | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 当前 SubAgent markdown 文件绝对路径，供 SubAgent 回看自身规范 |
| 开发记录目录 | — | ✓ | ✓ | ✓ | ✓ | ✓ | s1 新任务时尚未创建 |
| 算子名 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 全流程注入 |
| 开发模式 | ✓ | ✓ | — | — | — | — | Stage 3+ 从 dev record 读取即可 |
| 编程模型 | — | — | — | — | — | — | 统一从 dev record header 读取，不通过 prompt 传入 |
| current_sub_stage | — | — | — | ✓ | — | ✓ | Stage 4 循环中注入，如 `4.C.2.VT.0` |
| code_path | — | — | — | ✓ | — | — | s4-coding 需要写入最终 kernel；vf-test 产物在 output_dir，无需此字段 |

> **`ascendc-vf-test-agent`** 是 Stage 4 循环内调用的非 Stage 级 Agent（由编排层在遇到 `.VT.{M}` 步骤时触发）。它遵循本协议的 §A-§D 全部规范，固定返回 `next_stage=4`，由编排层 Stage 4 循环继续处理。

---

## §C 失败处理协议

本 SubAgent 在任一阶段返回 `status=FAILED` / `status=ROLLBACK` / `status=PAUSED` 之前，**必须**在开发记录的 `9.3 迭代记录` 表格中追加一行 ERROR 事件（即使最终回复中已说明，仍要写回记录）。

**写入格式**（统一 3 列表格格式）：

```
| {YYYY-MM-DD HH:mm} | ERROR | {错误代码}: {一句话原因} |
```

**示例**：
```
| 2025-06-10 14:32 | ERROR | C-SYM: tiling.h 中字段 blockSize 未在 kernel 中声明 |
| 2025-06-10 15:01 | ERROR | AMB: 用户未明确 tail block 处理方式 |
```

**解析约定**（供主 SKILL / 编排层按 per-type 上限 + per-substage 重试预算决策）：
- 事件类型列 = `ERROR` 时，描述列的**冒号前部分**为错误代码（需与 `error-handling.md` §7 映射表中的代码严格匹配）
- 错误代码 → 类别 → per-substage 计数器/升级决策由编排层（`codegen_s4.py:check_retry_exceeded`）消费，SubAgent 只返回语义正确的代码，不感知权重

**主 SKILL 调度决策依赖 9.3 迭代记录读取错误类型以决定重试/回退策略。如 9.3 缺失，主 SKILL 会误判。**

### 错误代码注册规则

> 完整注册表见 [`error-handling.md` §7](error-handling.md)。E(t) 加权累计已移除。

核心原则：
- 每个 SubAgent 只写入 `error-handling.md` §7 映射表中已列出的错误代码
- 不允许 SubAgent 自定义未列出的代码（需新增时同步更新 error-handling.md + 各 SubAgent 文档）
- **一次 FAILED 只写入一条 ERROR 事件**；如该 FAILED 涉及多个错误代码，选取最贴合语义的那一个写入（避免单次 FAILED 被重复计数）

### SubAgent 差异声明格式

各 SubAgent 只需列出**本 Stage 可能触发的错误代码**：

```markdown
**本 Stage 可触发的错误代码：**
- `XXX` — {说明}
- `YYY` — {说明}
```

---

## §D 返回格式

### 机器可读标记（必须）

**强制要求**：最终回复的**前 5 行内**必须输出机器可读标记（主 SKILL 解析用，允许行首有空白）：

```
## RETURN: status={STATUS}, next_stage={NEXT}
```

### status 取值

| 值 | 含义 |
|----|------|
| `COMPLETED` | 本 Stage 全部验收通过 |
| `FAILED` | 本 Stage 执行失败（已写 9.3 ERROR 事件） |
| `ROLLBACK` | 需回退到更早的 Stage |
| `PAUSED` | 等待外部条件（用户操作/环境修复） |
| `NEEDS_AGENT` | 需要主 SKILL 代为启动一个 Agent（如 ascendc-tiling-strategy），本 SubAgent 不能直接调用 |
| `PARTIAL` | 通常情况下：compact 中断导致部分完成（仅由主 SKILL 从 dev record 判定，SubAgent 不主动返回此状态）。<br>**例外**：`ascendc-vf-test-agent` 作为 Stage 4 子阶段 Agent，在 VF 精度/编译失败且内部重试未耗尽时，可主动返回 `PARTIAL`，请求主 SKILL 重新调度当前 `.VT.{M}` 步骤。 |

### next_stage 取值

| 值 | 含义 |
|----|------|
| `1`–`5` | 下一步应执行的 Stage 编号 |
| `DONE` | 全流程完成（仅 Stage 5 COMPLETED 时使用） |

### 人类可读摘要（紧跟标记行之后）

第二行起为人类可读摘要，保留供主 SKILL 透传给用户。通用结构：

**成功时：**
```
## RETURN: status=COMPLETED, next_stage={N+1 或 DONE}

Stage {N} 执行摘要
================
状态: COMPLETED
开发记录目录: {record_dir}
算子名: {OpName}
当前 Stage: {N} ✅
{...本 Stage 特有字段...}
下一步: Stage {N+1}
```

**失败时：**
```
## RETURN: status=FAILED, next_stage={N}

状态: FAILED
失败原因: {描述}
{...本 Stage 特有字段（如错误类型、重试次数）...}
建议: {下一步操作}
```

**回退时：**
```
## RETURN: status=ROLLBACK, next_stage={目标 Stage}

状态: ROLLBACK
回退目标: Stage {目标}
原因: {描述}
```

**暂停时：**
```
## RETURN: status=PAUSED, next_stage={当前 Stage}

状态: PAUSED
原因: {描述}
当前进度: Stage {N} {进行中的步骤}
需要用户: {具体操作}
```

**需要主 SKILL 代调 Agent 时：**
```
## RETURN: status=NEEDS_AGENT, next_stage={当前 Stage}, agent_name={Agent 类型名}

状态: NEEDS_AGENT
原因: {为什么需要外部 Agent}
目标 Agent: {agent_name}
恢复后动作: {Agent 完成后本 SubAgent 应继续执行的步骤}
【Agent 上下文】
- 开发记录目录: {record_dir}
- 算子名: {OpName}
- 项目路径: {project_path}
- 编译指令: {compile_cmd}
- 硬件参数: {hw_params}
- 改动摘要: {change_summary}
- 需求文档路径: {design_doc}
```

### SubAgent 差异声明格式

各 SubAgent 只需列出本 Stage 的**特有返回字段**：

```markdown
## 返回格式

> 通用格式见 [`references/subagent-common-protocol.md`](../skills/ascendc-dev/references/subagent-common-protocol.md) §D。

**本 Stage 特有字段：**
- 成功时额外输出：{字段}: {说明}
- 失败时额外输出：{字段}: {说明}
```

---

## §E Stage 完成后标准动作（开发记录状态推进）

SubAgent 返回 `status=COMPLETED` 前，**必须**将本 Stage 完成状态写入开发记录。本协议统一定义写入规则，各 SubAgent 不再重复描述具体操作。

> **状态推进是 `COMPLETED` 的前提条件**。若因文件系统不可写、路径缺失等原因无法完成写入，SubAgent 不得返回 `COMPLETED`；应返回 `status=FAILED`（错误代码 `OTH`）并说明原因。

### 中间 Stage（s2 / s4 / s5）：更新

按以下顺序执行：

1. **标记 Stage 完成**：`dev_record.sh set-progress "$RECORD_DIR" {stage} "✅"`
2. **同步 `meta.json` 的 `current_stage`**：`dev_record.sh set-meta "$RECORD_DIR" current_stage {N}`

> `current_stage` 是跨 session 恢复的入口指针（SKILL.md 场景 D），随每次 Stage 完成更新；s4 子阶段推进不更新它（仅保持为 4）。

### 流程完成（Step 3）：无指针清理

流程完成后**不需要**删除任何外部指针文件（无 Memory 指针结构）；开发记录保留在 `$RECORD_DIR` 供审计，状态以 `meta.json` + `orchestration_plan.json` 为准。

### SubAgent 引用格式

各 SubAgent 的"通过后操作"只需写：

```markdown
**通过后操作：**
- 标记 Stage {N} ✅（dev_record.sh set-progress）
- 同步 `meta.json` current_stage（dev_record.sh set-meta）
- 迭代记录追加：`STAGE_COMPLETE | Stage {N} 完成`
```

### 快速通道场景（主 SKILL 直接执行）

当 Stage 3 快速通道触发时，状态推进由主 SKILL 直接执行，写入规则同中间 Stage。完整步骤见 [`orchestrator-logic.md` §3](orchestrator-logic.md)。

---

## §F 状态文件读写效率协议

为避免 SubAgent 在单次执行中反复读取/写入状态文件造成不必要的调用开销，统一约定以下效率规则。

### 状态文件定义

本协议中的状态文件指开发记录目录下的：

- `meta.json` —— 算子元信息、当前 Stage、per-type 重试计数器 等
- `orchestration_plan.json` —— **Stage 4 状态转移唯一权威**（sub-stage 序列/检查点组/交付物/状态；编排层状态机读取）
- `progress.md` —— Stage 完成状态表（**派生镜像**，由 orchestration_plan.json 重新生成，不参与状态转移）
- `history.log` —— 迭代事件日志
- `coding_plan.md` —— 文件级编码计划状态（human/agent 参考）
- `coding_index.md` —— 步骤级编码索引

### 读取预算原则

1. **单次读取原则**：SubAgent 进入业务逻辑前读取一次状态文件获取初始状态；业务逻辑中除非明确怀疑上一步写入失败，否则禁止用 Read 工具反复确认。
2. **信任脚本输出**：通过 `dev_record.sh` 更新状态后，以脚本返回的 `OK: ...` 作为成功依据，禁止紧接着再用 Read 读取同一文件二次确认。
3. **批量更新优先**：需要连续修改多个 `meta.json` 字段时，优先使用 `dev_record.sh set-meta-batch <目录> key1=val1 [key2=val2 ...]`，而非多次调用 `set-meta`。
4. **写后验证例外**：仅在出现以下情况时允许进行一次验证性读取：
   - 脚本返回非 0 退出码或异常输出
   - 后续步骤强依赖该文件内容的精确一致性
   - 必须在最终返回前确认某字段已正确写入

   进行验证性读取时，应在返回摘要中简要说明原因。

### 常见反模式

| 反模式 | 说明 | 修正方式 |
|--------|------|----------|
| 每次 Write 后 Read meta.json 确认 | 不信任 Write/脚本结果 | 删除冗余 Read，必要时只在 Stage 末尾验证一次 |
| 用多次 `set-meta` 更新多个字段 | 每次调用都读/写 meta.json | 改用 `set-meta-batch` |
| 在循环中重新读取 meta.json | 把 meta.json 当实时状态中心 | 把需要的字段缓存到上下文中 |

### SubAgent 文档引用格式

各 SubAgent 文档只需在"执行流程"开头引用本协议：

```markdown
### 通用协议（必做，先于所有业务逻辑）

> 失败处理（§C）+ 状态文件读写效率协议（§F）见 [`references/subagent-common-protocol.md`](subagent-common-protocol.md)。
```

---

## §H NEEDS_AGENT 协议

### 使用场景

当 SubAgent 需要调用某个**必须通过 Agent 工具启动**的能力（如 `ascendc-tiling-strategy`）时，由于 Claude Code 禁止 SubAgent 嵌套调用 Agent，SubAgent 应返回 `NEEDS_AGENT` 状态，由主 SKILL（Orchestrator）代为启动目标 Agent。

### SubAgent 职责

1. **完成前序准备**：在返回 `NEEDS_AGENT` 前，完成所有可以在 SubAgent 内安全完成的步骤（如条件判定、备份文件、收集上下文）。
2. **在开发记录中写入标记**（推荐）：追加 `NEEDS_AGENT` 事件到 `history.log`，说明目标 Agent 和原因：
   ```
   [{YYYY-MM-DD HH:mm}] [NEEDS_AGENT] agent={agent_name} reason={原因}
   ```
3. **返回完整上下文**：在 `## RETURN:` 行和随后的摘要中提供目标 Agent 所需的全部上下文，避免主 SKILL 二次收集。
4. **不得自行调用 Agent**：即使 `tools` 列表包含 `Agent`，也禁止在 SubAgent 内使用。

### 主 SKILL 职责

1. 解析 `agent_name` 和 Agent 上下文。
2. 使用 **Agent tool** 启动目标 Agent（`subagent_type={agent_name}`）。
3. 目标 Agent 返回 `COMPLETED` 后：
   - 在 `history.log` 追加 `AGENT_COMPLETE` 事件
   - 重新调度原 SubAgent（注入 `agent_completed: true` 和必要上下文）
4. 目标 Agent 返回 `FAILED` / `PAUSED` 后：
   - 按目标 Agent 的错误类型处理，或向用户展示暂停原因
   - 不自动重试，等待用户决策或升级处理

### RETURN 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `status` | 是 | 固定为 `NEEDS_AGENT` |
| `next_stage` | 是 | 当前 Stage 编号，主 SKILL 完成后需回到该 Stage |
| `agent_name` | 是 | 目标 Agent 的 `subagent_type`，如 `ascendc-tiling-strategy` |
| `resume_point` | 否 | Agent 完成后原 SubAgent 应恢复到的子步骤，如 `5.3.2-recompile` |
| `agent_context` | 是 | 启动 Agent 所需的关键参数，建议以结构化列表提供 |

### 示例

```
## RETURN: status=NEEDS_AGENT, next_stage=5, agent_name=ascendc-tiling-strategy, resume_point=5.3.2-recompile

状态: NEEDS_AGENT
原因: Stage 4 新增了大量 Tiling 变更，需要 ascendc-tiling-strategy 优化分核分块策略
目标 Agent: ascendc-tiling-strategy
恢复后动作: Agent 完成后，s5-compile 继续执行 5.3.2 二次编译验证
【Agent 上下文】
- 开发记录目录: {record_dir}
- 算子名: {OpName}
- 项目路径: {code_path}
- 编译指令: {compile_cmd}
- 硬件参数: UB={ub_size}, core_num={core_num}, alignment={alignment}
- 改动摘要: 新增 XX buffer、调整 tileD 计算逻辑
- 需求文档路径: {design_doc}
```
