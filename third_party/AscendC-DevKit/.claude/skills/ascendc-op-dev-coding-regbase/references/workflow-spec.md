# 工作流规格说明

本文件定义 ascendc-dev skill 的工作流保障框架。

---

## 1. 系统模型

```
Input(需求) → [前置检查] → [Stage 执行] → [验收检查] → [门控判定] → Next Stage
                  ▲                                            │
                  │            反馈回路                         │
                  └────────── 纠正动作 ◄──────────────────────┘

                  ┌─────────────────────────────────────────┐
                  │  状态观测器（开发记录）                    │
                  │  · 进度表（progress.md，派生镜像）         │
                  │  · per-type 重试计数器（meta.json）       │
                  │  · Issue 注册表                          │
                  └─────────────────────────────────────────┘
```

---

## 2. 核心原则

### 2.1 反馈机制

每个 Stage 出口设置验收检查，测量输出是否满足标准。不达标则产生纠正动作（重试 / 回退 / 升级）。

### 2.2 稳定性保证

- 重试预算耗尽时升级处理，防止无限循环
- 升级决策由编排层确定性给出（per-type 计数器耗尽 → 按阶段/类别升级），见 [`error-handling.md`](error-handling.md) §6

### 2.3 状态可恢复

- 开发记录是系统的唯一状态载体
- 任何 session 仅凭开发记录即可完全重建系统状态
- 状态记录协议确保每次转换都写入记录

**状态完整性要求**：开发记录中以下字段必须始终有值：
1. 当前进度表（每个 Stage 的状态）
2. 重试计数器（各类已用次数）
3. 最后门控结果

### 2.4 进度可观测

- 从任意已记录状态，可计算到达完成态的路径
- 恢复协议：读取进度表 → 确定当前 Stage → 执行该 Stage 的前置检查 → 继续

**恢复保证**：
1. 开发记录模板覆盖所有状态维度
2. 每个 Stage 有明确的入口条件（前置检查）
3. `meta.json` 的 `current_stage` 记录当前 Stage，新 session 据此恢复（SKILL.md 场景 D）
4. 跨 session 恢复入口在 Stage 4.1 前置校验中定义

---

## 3. 阶段门控定义

### 3.1 门控类型

| 类型 | 标签 | 语义 | 失败行为 |
|---|---|---|---|
| 硬门控 | [必须] | 必须通过，不可跳过 | 阻塞，等待条件满足 |
| 软门控 | [可跳过] | 脚本失败降级时的 fallback 检查 | 向用户展示 warning，请求 override 后继续 |

### 3.2 各 Stage 门控配置

| Stage | Gate | 前置检查项 | 验收标准 |
|---|---|---|---|
| 1→2 | [必须] | CANN 环境变量已设置；硬件参数可获取；编译工具链可用 | 开发记录已创建；必选字段已填充；meta.json current_stage 已写入 |
| 2→3 | [必须] | Stage 1 ✅；代码路径可访问；需求文档可读 | 所有记录章节已填写；变更点列表非空；编码计划已生成 |
| 3→4 | [必须] | Stage 2 ✅；不明确项清单存在 | 所有不明确项状态="已澄清"；参考算子映射已确认 |
| 4→5 | [必须] | Stage 3 ✅ 或有效恢复记录；零"待澄清"项 | 自检表全部通过（不涉及项标 N/A）；用户已确认各 sub-stage；编码计划状态已更新 |
| 5→完成 | [必须] | Stage 4 ✅；编译指令可用 | 编译成功(exit 0)；记录已更新；meta.json current_stage 已推进到完成态 |

### 3.3 门控执行协议

```
gate_check(current_stage, next_stage):
  1. 执行验收检查所有检查项（不涉及项标 N/A）
  2. IF 全部通过:
       记录: "GATE_PASS | Gate {current}→{next}"
       执行 dev_record.sh set-progress 更新状态
       进入 next_stage
  3. IF 部分失败:
       记录: "GATE_FAIL | Gate {current}→{next} | 原因: {失败项}"
       触发纠正动作（参见 error-handling.md）
```

---

## 4. 进度度量（已移除）

> V(t) 进度度量与 calc-vt 已随 E(t) 一并移除。状态可观测性由进度表（progress.md，派生镜像）、
> per-type 重试计数器（meta.json `retries`）与 history.log 事件日志承载。

---

## 5. 重试与回退规则

> 完整规则（阈值表、回退约束、重试计数器持久化、梯度递进策略、SubAgent/主SKILL 职责划分）见 [`error-handling.md`](error-handling.md) §6-§8。

---

## 6. 状态记录协议

### 6.1 记录时机

每次以下事件发生时，必须写入开发记录的"9.3 迭代记录"表格（3 列：`| 时间 | 事件类型 | 描述 |`）：

| 事件 | 事件类型 | 描述列格式 |
|---|---|---|
| Stage 完成 | `STAGE_COMPLETE` | `Stage {N} 完成` |
| Gate 通过 | `GATE_PASS` | `Gate {N}→{N+1}` |
| Gate 失败 | `GATE_FAIL` | `Gate {N}→{N+1}: {失败原因}` |
| Gate Override | `GATE_OVERRIDE` | `Gate {N}→{N+1}: 用户确认跳过` |
| 错误发生 | `ERROR` | `{错误代码}: {一句话原因}` |
| 实现偏离 | `CTX_DRIFT` | `{偏离源}: {偏离描述} - {实际做法} - {原因}` |
| 受控回退 | `REGRESSION` | `从 Stage {X} 回退到 Stage {Y}: {原因}` |
| Session 恢复 | `RESUME` | `从 Stage {N} 恢复` |
| 暂停 | `PAUSED` | `Stage {N}: {原因分类} - {一句话原因}` |

> **注**：`CTX_DRIFT` 实际写入 `history.log`，使用方括号格式 `[{time}] [CTX_DRIFT:{severity}] {描述}`，不写入 9.3 迭代记录表格。

**写入行格式**（所有事件统一）：

```
| {YYYY-MM-DD HH:mm} | {事件类型} | {描述} |
```

**示例**：
```
| 2025-06-10 10:05 | STAGE_COMPLETE | Stage 1 完成 |
| 2025-06-10 11:30 | ERROR | C-SYM: kernel 中未声明 blockSize 字段 |
| 2025-06-10 11:45 | GATE_PASS | Gate 4→5 |
```

**ERROR 事件解析约定**：描述列的冒号前部分为错误代码，供主 SKILL / 编排层按 per-type 重试预算决策（`error-handling.md` §7 注册表）。

### 6.2 完整性检查

新 session 恢复时，必须验证开发记录的完整性：
1. 进度表中每个已完成 Stage 都有对应的 GATE_PASS 记录
2. 重试计数器与进度表一致
3. 无"进行中"状态超过 1 个 Stage

---

## 7. 脚本调用规范

### 7.1 调用约定

```bash
# 通用调用格式
bash "$SKILL_ROOT/scripts/<script>.sh" [参数...]

# 返回值约定
# exit 0 = 检查通过
# exit 1 = 检查失败（输出 JSON 到 stdout 描述失败原因）
# exit 2 = 脚本自身错误（非业务失败）
```

### 7.2 输出格式

所有脚本输出 JSON 到 stdout：

```json
{
  "pass": true|false,
  "details": { ... }
}
```

### 7.3 失败处理

```
script_result = execute_script(script, args)
IF script_result.exit_code == 0:
  继续流程
ELIF script_result.exit_code == 1:
  解析 JSON 获取失败原因
  IF gate == [必须]:
    阻塞，报告失败原因
  ELIF gate == [可跳过]:
    向用户展示，请求 override
ELIF script_result.exit_code == 2:
  记录脚本错误
  降级为 agent 语义检查（脚本不可用时的 fallback）
```

---

## 8. 恢复协议

> 完整恢复流程（跨 session 8 步、compact 恢复、中断保证）见 [`orchestrator-logic.md`](orchestrator-logic.md) §4-§6。
