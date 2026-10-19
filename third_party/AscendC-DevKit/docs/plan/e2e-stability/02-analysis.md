# e2e 稳定性 — L3 方案分析

> 层级：**L3 / 方案分析**。陈述可选方案、权衡、选择理由。
> 问题来源：`01-problems.md`（L1）。实施方案见 `03-impl-*.md`（L4）。

---

## 全局架构问题：三层失败信号的隔离

P2+P3+P4 共同指向同一结构缺陷：

```
Layer 3: transition_table 路由层  — 只有 3 个 gate 阶段覆盖
Layer 2: runner stage_status 判断  — 只打日志，不抛异常
Layer 1: _execute_atomic 异常捕获  — 只捕获控制异常
```

三层互不感知。修改需在 Layer 2 与 Layer 3 间建立失败信号管道。

---

## P1+P8：max_turns 与 partial 误判

### 方案 A：全局提高默认 max_turns

改 `sdk_backend.py:350`：`max_turns: int = 15` → `10000`。

| 优点 | 缺点 |
|------|------|
| 最小改动 | 硬编码值仍然不灵活 |
| 立即消除截断 | 真正死循环会烧更久 |

### 方案 B：agent manifest 逐文件声明 + 配置文件驱动

在 `orchestration-config.json` 加 `agent.max_turns`，每 agent 在 `.md` 声明。

| 优点 | 缺点 |
|------|------|
| 不同 agent 可用不同预算 | 改动点多，维护负担 |

**选择**：✅ 方案 A（已完成）。P1 的 max_turns 截断是本次最频繁可避故障，方案 A 最小改动覆盖全部路径。后期如需精细控制可升级到方案 B。

### partial 误判修复

`runner.run_stage` 中当 `agent_status=="partial"` 时检查 `output_contract`：若 `result_state.has_all()` 则标记 `stage_status="ok"`。

---

## P2+P3：fail_strategy 全局方案

### 方案 A：transition_table 补全所有阶段路由

在 `_DETAILED_DESIGN_TRANSITION_TABLE` 中为每个可能失败的阶段注册 `"default": ("__halt__", "halt")`。

| 优点 | 缺点 |
|------|------|
| 不改 runner 逻辑 | 语义不明确（"default" 含义过载） |
| 纯配置 | halt 决策分散在各表 |

### 方案 B：Stage 声明 fail_strategy

`Stage` 基类增 `fail_strategy: str = "continue"`。生成型阶段覆写为 `"halt"`。runner 在 `stage_status != "ok"` 且 `fail_strategy == "halt"` 时注入 `_stage_failed=True`。graph_executor 读该标志 → `is_terminal=True` → break。

| 优点 | 缺点 |
|------|------|
| 决策点在阶段自身声明 | 需改 base.py + runner + graph_executor 三处 |
| halt/continue 二态清晰 | 引入新 State 字段 |
| quality-gate 不受影响 | — |

**选择**：✅ 方案 B。清晰二态，与现有 transition_table 路由正交（gate 阶段 `fail_strategy="continue"` 后仍由 blocking_issues 决定路由）。

### 分配表

| 阶段类别 | 阶段 | fail_strategy | 理由 |
|---------|------|--------------|------|
| 生成型（设计） | gd-generate, template-division, split, buffer-kernel, precision-perf, integrate | halt | 产物是下游强依赖 |
| 审核型（gate） | general-design-review, anchor-check, validate | continue | 由 blocking_issues 路由 |
| 验证型 | verify, perf | continue | 由 TRANSITION_TABLE 路由 |
| 入口型 | entry, context, requirement, dd-intake | continue | 纯 pass-through |
| 测试设计 | test-analyze, test-casedesign, test-casegen | halt | `_TestDesignSubstage` 继承 `_DesignSubstage`（`test_design_substages.py:35`），自动继承 halt |

---

## P4：设计阶段产物收集

### 方案 A：保留当前共享函数，增强降级路径

在 `_collect_changed_sources` 中为设计阶段补 `changed_files.json` 自报告 + 传递 `repo_baseline`。

| 优点 | 缺点 |
|------|------|
| 不改收集架构 | 4 层条件分支更复杂 |
| | 语义混用持续 |

### 方案 B：设计阶段直接从磁盘读文件（确定性路径）

`_parse_single` 增加路径：从 `working_dir` 按 `artifact_contract` 声明直接读文件。不走 `_collect` / `_collect_changed_sources`。

| 优点 | 缺点 |
|------|------|
| 文件名已知，确定性读 | 需 runner 传 `_working_dir` 到 result |
| 不扫全目录，不混入输入文件 | contract 文件缺失时无回退 |
| 不依赖 git | — |

**选择**：✅ 方案 B。设计阶段产物文件名由 `artifact_contract` 声明，收集应直接从声明驱动。runner 传 `result["_working_dir"] = action.working_dir`。

### Codegen 的 git 策略

**git diff + ls-files 并集保留**。覆盖全新增（`ls-files --others`）和增量（`git diff`）场景。**git 不可用或不在仓库 → 报错**（抛 PreconditionError），不降级到 `_scan_working_dir`。

---

## P5：last_error 粘滞

### 方案

所有 `_parse_single` 成功返回路径增加 `"last_error": None`。解决一次，无替代方案。

---

## P6：stall + RuntimeError

### 方案

`runner._execute_spawn_agent` 增加 `aclose()` 保护；`_build_prompt` 增加 iteration 上下文避免 agent 重复扫描。优先级低于 P1-P4，可后期跟进。

---

## P7：requirement-analyst SKILL.md

### 方案

`_build_analysis_prompt` 调用 `_with_trigger()`，首条消息以 `/stage-requirement:ascendc-op-req-analysis` 开头。与设计子阶段一致。

---

## 决策汇总

| # | 问题 | 选择方案 | 理由 |
|---|------|---------|------|
| P1 | max_turns | A（全局提高默认值） | 最小改动 |
| P2+P3 | 失败策略 | B（fail_strategy 声明） | 清晰二态，与 transition_table 正交 |
| P4 | 产物收集 | B（确定性磁盘读取） | 文件名已知，不需要 git diff |
| P5 | last_error | 清除 | 唯一方案 |
| P6 | stall | 保护 + 上下文 | 后期跟进 |
| P7 | SKILL.md | slash command 触发 | 与设计阶段一致 |
| P8 | partial 误判 | 检查 contract | 简单可靠 |
