# SubAgent 通用协议

> 本文件统一定义所有 ascendc-dev SubAgent 的 4 项公共协议：必传字段校验、工作目录自检、失败处理记录、返回格式。各 SubAgent 文档只需一行引用本文件，无需重复完整规则。

---

## §A 必传字段校验（Fail-Safe）

主 SKILL 调度 SubAgent 时，部分字段为**必传**。如 prompt 中任一必传字段缺失或为空，SubAgent 立即返回 FAILED，不进入任何业务流程。

### 校验流程

```
1. 逐项检查必传字段表中的每个字段
2. IF 任一字段缺失或为空:
     返回 FAILED（格式见 §D RETURN 模板）
3. ELSE:
     校验通过，进入业务流程
```

### RETURN 模板（校验失败时）

```
## RETURN: status=FAILED, next_stage={上一个 Stage 编号}

状态: FAILED
失败原因: 主 SKILL 未传必传字段：{字段名}（{字段说明}）
建议: 主 SKILL 调度 s{N}-{name} 前应将 {字段名} 显式写入 prompt 的"输入"字段
```

### SubAgent 差异声明格式

各 SubAgent 只需列出**必传字段表**和**校验失败时的 next_stage 值**：

```markdown
## §0 Fail-Safe：必传字段校验

> 通用校验逻辑见 [`references/subagent-common-protocol.md`](../skills/ascendc-dev/references/subagent-common-protocol.md) §A。

| 字段 | 来源 | 缺失行为 |
|------|------|---------|
| {字段1} | 主 SKILL prompt | 返回 FAILED |

**校验失败时 next_stage = {N}**
```

**设计意图**：避免主 SKILL 漏传关键字段时，SubAgent 静默以"prompt 中隐含的字段"工作，导致后续 Stage 全部错位。

### 各 Stage 必传字段对比

| 字段 | s1 | s2 | s3 | s4 | s5 | vf-test | 说明 |
|------|----|----|----|----|----|----|----| 
| SKILL_ROOT | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | skill 根目录绝对路径，脚本调用前缀 |
| AGENT_ROOT | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 当前 SubAgent markdown 文件绝对路径，供 SubAgent 回看自身规范 |
| 开发记录目录 | — | ✓ | ✓ | ✓ | ✓ | ✓ | s1 新任务时尚未创建 |
| 算子名 | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | 全流程必传 |
| 开发模式 | ✓ | ✓ | — | — | — | — | Stage 3+ 从 dev record 读取即可 |
| 编程模型 | — | — | — | — | — | — | 统一从 dev record header 读取，不通过 prompt 传入 |
| current_sub_stage | — | — | — | ✓ | — | ✓ | Stage 4 循环中注入，如 `4.C.2.VT.0` |
| code_path | — | — | — | ✓ | — | — | s4-coding 需要写入最终 kernel；vf-test 产物在 output_dir，无需此字段 |

> **`ascendc-vf-test-agent`** 是 Stage 4 循环内调用的非 Stage 级 Agent（由编排层在遇到 `.VT.{M}` 步骤时触发）。它遵循本协议的 §A-§D 全部规范，固定返回 `next_stage=4`，由编排层 Stage 4 循环继续处理。

---

## §B SKILL_ROOT 与 AGENT_ROOT 自检

主 SKILL 调度 SubAgent 时通过 prompt 注入 `SKILL_ROOT`（skill 根目录绝对路径）和 `AGENT_ROOT`（当前 SubAgent markdown 文件绝对路径）。SubAgent 端做一次防御性自检，确保路径有效。

### 自检脚本模板

SubAgent 在第一次跑脚本之前，先执行以下自检（将 `{AGENT_ID}` 替换为实际标识符，如 `s1-env`、`s4-coding`）：

```bash
# 从 prompt 中获取 SKILL_ROOT 和 AGENT_ROOT（SubAgent 解析 prompt 后设置为变量）
SKILL_ROOT="{从prompt中解析的SKILL_ROOT值}"
AGENT_ROOT="{从prompt中解析的AGENT_ROOT值}"

# 快速预检（一行判定，失败才展开诊断）
if [ -d "$SKILL_ROOT/scripts" ] && [ -f "$AGENT_ROOT" ] && { [ "{AGENT_ID}" = "s1-env" ] && [ -z "$RECORD_PATH" ] || [ -n "$RECORD_PATH" ] && [ -w "$(dirname "$RECORD_PATH" 2>/dev/null)" ]; }; then
  : # 自检通过，继续业务逻辑
else
  # === 展开诊断 ===
  if [ ! -d "$SKILL_ROOT/scripts" ]; then
    echo "[{AGENT_ID} FATAL] SKILL_ROOT 无效：'$SKILL_ROOT/scripts' 不存在" >&2
    exit 1
  fi
  if [ ! -f "$AGENT_ROOT" ]; then
    echo "[{AGENT_ID} FATAL] AGENT_ROOT 无效：'$AGENT_ROOT' 不存在" >&2
    exit 1
  fi
  if [ "{AGENT_ID}" = "s1-env" ] && [ -z "$RECORD_PATH" ]; then
    echo "[s1-env INFO] 新任务模式，RECORD_PATH 将在 1.3 创建，跳过自检 2" >&2
  elif [ -z "$RECORD_PATH" ] || [ ! -w "$(dirname "$RECORD_PATH" 2>/dev/null)" ]; then
    echo "[{AGENT_ID} FATAL] RECORD_PATH 未设置或目录不可写：'$RECORD_PATH'" >&2
    exit 1
  fi
fi
```

> **AGENT_ROOT 用途**：SubAgent 规范较长时，若 context 被 compact 压缩，可重新 `Read "$AGENT_ROOT"` 恢复关键约束；规范中要求"完成前必读自身文档"时也可直接定位。

> **设计意图**：正常路径（自检通过）只执行一行条件判断，开销极小。仅在失败时才展开诊断输出具体错误原因。

### 失败处理分支

| 情况 | 处理 |
|------|------|
| **SKILL_ROOT 为空**（主 SKILL 未注入或注入值为空） | **不尝试写 9.3**；RETURN 消息中明确提示"主 SKILL 未正确注入 SKILL_ROOT，请检查 SKILL_ROOT 获取逻辑（见 SKILL.md §SKILL_ROOT 与 AGENT_ROOT 约定）"；主 SKILL 收到后按 fallback 链重试获取或返回 PAUSED |
| **AGENT_ROOT 为空或无效** | 返回 FAILED，提示"主 SKILL 未正确注入 AGENT_ROOT"；SubAgent 仍可尝试执行业务逻辑，但不得依赖 AGENT_ROOT 回看自身规范 |
| **自检 1 失败**（SKILL_ROOT 非空但路径无效，RECORD_PATH 可能有效） | 尝试写 9.3：`echo "ERROR | 自检 | OTH | SKILL_ROOT/scripts 不存在" >> "$RECORD_PATH"`（RECORD_PATH 无效则静默失败）；然后返回 FAILED |
| **自检 2 失败**（RECORD_PATH 无效） | **不尝试写 9.3**（目标不可写）；仅通过 RETURN 消息附带错误原因；主 SKILL 从 `## RETURN:` 行和人类可读摘要获取失败信息 |
| **自检 2 跳过**（s1-env 新任务模式，RECORD_PATH 为空） | 正常继续业务流程；9.3 在 1.3 创建开发记录后才可写，1.3 之前的错误通过 RETURN 消息传递 |

除 s1-env 新任务模式外，其余情况均返回 FAILED，不进入本 Stage 的业务流程。

**设计意图**：自检 2 验证的恰恰是"9.3 能否写入"，因此自检 2 失败时不能要求写 9.3（逻辑悖论）。错误信息通过 stderr + RETURN 消息传递给主 SKILL，保证错误不丢失。SKILL_ROOT 通过 prompt 注入（而非依赖 cwd），彻底消除 Bash 工具不保留 shell 状态导致的 cd 丢失问题。

---

## §C 失败处理协议

本 SubAgent 在任一阶段返回 `status=FAILED` / `status=ROLLBACK` / `status=PAUSED` 之前，**必须**在开发记录的 `9.3 迭代记录` 表格中追加一行 ERROR 事件（即使最终回复中已说明，仍要写回记录）。

**写入格式**（统一 4 列表格格式）：

```
| {YYYY-MM-DD HH:mm} | ERROR | {错误代码}: {一句话原因} | {当前 V(t)} |
```

**示例**：
```
| 2025-06-10 14:32 | ERROR | C-SYM: tiling.h 中字段 blockSize 未在 kernel 中声明 | 0.60 |
| 2025-06-10 15:01 | ERROR | AMB: 用户未明确 tail block 处理方式 | 0.60 |
```

**解析约定**（供主 SKILL 恢复时重算 E(t)）：
- 事件类型列 = `ERROR` 时，描述列的**冒号前部分**为错误代码（需与 `error-handling.md` §7 映射表中的代码严格匹配）
- 主 SKILL 按 `错误代码 → 5 大类 → 权重` 映射后累加

**主 SKILL 调度决策依赖 9.3 迭代记录读取错误类型以决定重试/回退策略。如 9.3 缺失，主 SKILL 会误判。**

### E(t) 映射规则

> 完整映射表见 [`error-handling.md` §7](error-handling.md)。

核心原则：
- 每个 SubAgent 只写入 `error-handling.md` §7 映射表中已列出的错误代码
- 不允许 SubAgent 自定义未列出的代码（需新增时同步更新 error-handling.md + 各 SubAgent 文档）
- **一次 FAILED 只写入一条 ERROR 事件**；如该 FAILED 涉及多个错误代码，应选取权重最高的那一个写入，避免单次 FAILED 被多次累加
- 主 SKILL / `dev_record.sh calc-et` 以 `history.log` 中连续且 `V(t)` 相同的 ERROR 行作为同一 FAILED 批次，批次内取最高权重累加

### 权重速查

> 完整权重表见 [`error-handling.md` §6](error-handling.md)。速查：编译 +1、自检 +2、环境 +3、歧义 +2、设计 +3、INP/OTH +0。

### SubAgent 差异声明格式

各 SubAgent 只需列出**本 Stage 可能触发的错误代码**：

```markdown
**本 Stage 可触发的错误代码：**
- `XXX` — {说明}（→ E(t) 大类：{类名}，权重 +N）
- `YYY` — {说明}（→ E(t) 大类：{类名}，权重 +N）
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

## §E Stage 完成后标准动作（Memory 指针同步）

SubAgent 返回 `status=COMPLETED` 前，**必须**执行 Memory 指针同步。本协议统一定义写入规则，各 SubAgent 不再重复描述具体操作。

> **Memory 指针同步是 `COMPLETED` 的前提条件**。若因文件系统不可写、路径缺失等原因无法完成同步，SubAgent 不得返回 `COMPLETED`；应返回 `status=FAILED`（错误代码 `OTH`）并说明原因。

### 中间 Stage（Stage 1–4）：更新

按以下顺序执行（写入顺序不可调换，保证 dev_ 永远 ≥ MEMORY.md）：

1. **更新 `dev_{OpName}.md`**：将"当前 Stage"字段改为 `Stage {N} ✅`
2. **更新 `MEMORY.md` 索引行**：用 Edit 将末尾 `(Stage {N-1} ✅)` 替换为 `(Stage {N} ✅)`

### 最终 Stage（Stage 5）：清理

流程完成后移除 Memory 指针（避免断链索引）：

1. **移除 `MEMORY.md`** 中对应的索引行
2. **删除 `dev_{OpName}.md`** 文件

> **顺序不可调换**：若先删 `dev_{OpName}.md`，`MEMORY.md` 的索引行将指向不存在的文件，造成断链。必须先清索引、再删本体，与中间 Stage 的写入顺序（先写本体、再写索引）对称。

### SubAgent 引用格式

各 SubAgent 的"通过后操作"只需写：

```markdown
**通过后操作：**
- 标记 Stage {N} ✅
- 执行 Memory 指针同步（见 [`subagent-common-protocol.md`] §E）
- 迭代记录追加：`STAGE_COMPLETE | Stage {N} 完成`
```

### 快速通道场景（主 SKILL 直接执行）

当 Stage 3 快速通道触发时，Memory 指针同步由主 SKILL 直接执行，写入规则同中间 Stage。完整步骤见 [`orchestrator-logic.md` §3](orchestrator-logic.md)。

---

## §F 状态文件读写效率协议

为避免 SubAgent 在单次执行中反复读取/写入状态文件造成不必要的调用开销，统一约定以下效率规则。

### 状态文件定义

本协议中的状态文件指开发记录目录下的：

- `meta.json` —— 算子元信息、当前 Stage、V(t)/E(t) 等
- `progress.md` —— Stage 完成状态表
- `history.log` —— 迭代事件日志
- `coding_plan.md` —— 文件级编码计划状态
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

> SKILL_ROOT 自检（§B）+ 失败处理（§C）+ 状态文件读写效率协议（§F）见 [`references/subagent-common-protocol.md`](subagent-common-protocol.md)。
```

---

## §H NEEDS_AGENT 协议

### 使用场景

当 SubAgent 需要调用某个**必须通过 Agent 工具启动**的能力（如 `ascendc-tiling-strategy`）时，由于 Claude Code 禁止 SubAgent 嵌套调用 Agent，SubAgent 应返回 `NEEDS_AGENT` 状态，由主 SKILL（Orchestrator）代为启动目标 Agent。

### SubAgent 职责

1. **完成前序准备**：在返回 `NEEDS_AGENT` 前，完成所有可以在 SubAgent 内安全完成的步骤（如条件判定、备份文件、收集上下文）。
2. **在开发记录中写入标记**（推荐）：追加 `NEEDS_AGENT` 事件到 `history.log`，说明目标 Agent 和原因：
   ```
   [{YYYY-MM-DD HH:mm}] [NEEDS_AGENT] agent={agent_name} reason={原因} | V(t)={vt}
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
