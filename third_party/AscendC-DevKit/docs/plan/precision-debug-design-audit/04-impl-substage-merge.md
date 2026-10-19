# L4 实施方案：precision_debug substage 合并（超长上下文信息不丢）

> 对应 L1 [01-problems.md](01-problems.md)（P3/P4）+ L3 [02-analysis.md](02-analysis.md) + [03-analysis-overweight-model-capability.md](03-analysis-overweight-model-capability.md)。
> 参照先例：设计阶段 TilingStage 合并（`tiling_current_template.json` 接力文件防长上下文信息丢失，§2.9 构造性消解跨段不一致）。
> 范围：仅 A3（A5 按用户指示保持原样）。

## 0. 目标

把 7 个 substage 合并为 5 个，减少 agent 会话切分，减轻模型负担（§1.14）。**核心约束：合并后 agent 会话可能变长，必须用"接力文件落盘"保证信息不丢**（参照 TilingStage）。

```
现在（7）：run_tests → scope_guard → bounds_check → diagnose → diagnose_refine → printf_location → comment_bisect
合并后（5）：run_tests → scope_guard → bounds_check → diagnose(含refine循环) → device_bisect(printf+comment_bisect)
```

## 1. 合并候选与理由

### 合并 1：diagnose_refine → 并入 diagnose（同 agent，最明确）

**现状**：`DiagnoseRefineSubstage` 用 `ascendc-precision-diagnose` agent（同 agent 不同 mode），经 `applied_partial` 路由另起会话做增量诊断。

**合并**：diagnose agent 在**同一会话内**完成"诊断 → 剥皮（refine）→ 再诊断"的循环（tail-call diagnose_refine 方法），不再经框架路由切会话。

**构造性收益（§2.9）**：evidence 传递（diagnose 产 error_migration_evidence → refine 消费）在同一上下文内完成，不可能跨会话丢失/漂移。

### 合并 2：printf_location + comment_bisect → device_bisect（同模式二分）

**现状**：两个 substage 都是二分定位（printf 定位精度发散 / 注释消融定位崩溃），共用相同路由（located_fixed/continue/case_more/case_done），仅信号不同。

**合并**：一个 `device_bisect` substage，agent 按 failure_type 选方法（precision→printf、runtime→comment_bisect），同一会话内 tail-call 对应 skill。

**构造性收益**：方法选择（printf vs comment_bisect）由 failure_type 确定性决定（§1.10 业务语义），不依赖两个并列 agent 自评。

### 不合并（诚实）

- **run_tests**：确定性阶段（跑测试+统计），与诊断（语义）性质不同，合并无构造性收益。
- **scope_guard**：轻量 AI 判定，只跑首轮，独立职责。
- **bounds_check**：一次性结构检查，独立。

## 2. 超长上下文信息不丢的核心设计（参照 TilingStage）

### 机制：接力文件 `debug_relay.json`

参照 TilingStage 的 `tiling_current_template.json`——**每完成一段，把该段的关键结论合并进接力文件，下一段只读接力文件，不重读全上下文**。

**合并 1（diagnose 含 refine）的接力**：

`diagnose` 会话内，每轮剥皮后更新 `precision_diagnose_refine.json`（已存在，作为接力）：
```json
{
  "refine_verdict": "refined_fix_plan",   // 剥皮结果
  "causal_chain": [...],                  // 已确认的因果链（累积）
  "error_migration_evidence": {...},      // 剥皮后的新 evidence（覆盖旧）
  "peeled_layers": ["layer1", "layer2"],  // 已剥层（避免重复）
  "all_attempted_fixes": [...]            // 已试 fix（避免重复）
}
```

下一轮 diagnose（仍在同会话）**只读接力文件**拿到"已剥层 + 已试 fix"，不重读全上下文。模型上下文即使超长，关键状态都落盘。

**合并 2（device_bisect）的接力**：

复用现有的 `tried_bisect_paths`（printf/comment_bisect skill 已有）作为接力：
```json
{
  "tried_bisect_paths": [...],   // 已试路径（累积，避免重复二分）
  "method": "printf|comment",    // 当前方法（由 failure_type 决定）
  "located_roots": [...],        // 已定位根因（多根因场景）
  "current_bisect_region": "...",// 当前二分区域
}
```

### 为什么这样能防长上下文信息丢

| 机制 | 作用 |
|---|---|
| **接力文件落盘** | 关键状态（已剥层/已试 fix/已定位根因）在磁盘，不依赖模型上下文记忆 |
| **只读接力不重读全上下文** | 超长上下文下，模型不需要记得所有中间细节，只读接力文件 |
| **schema 约束** | 接力文件有 schema（required_keys），落盘即校验，防字段漂移 |
| **每步自检** | 合并 skill 的自检项含"接力文件已更新"（参照 tiling 自检），防忘更新 |

## 3. 改动清单（按实施顺序）

### 阶段 A：先拆 diagnose transition（P3）——合并的前提

`diagnose` 190 行 transition 拆分：
- `_read_agent_summary`（读 agent 申报）→ 独立
- `_route_decision`（路由决策）→ 独立
- `_apply_fix`（实施模式）→ 独立
- `_update_counters`（计数器）→ 独立

**必须先拆**：否则合并 diagnose_refine 只是"把 190 行 + 40 行塞进一个 transition"。

### 阶段 B：合并 diagnose_refine → diagnose

- 删 `DiagnoseRefineSubstage` 类 + tree 路由表条目 + `precision_diagnose_refine.json` 独立 schema（合并进 diagnose）
- diagnose transition 内加 refine 循环（applied_partial → 就地 refine → 更新接力文件 → 再诊断）
- 删 `refine_cycles` 计数器（归入 diagnose 的 rounds 语义）

### 阶段 C：合并 printf_location + comment_bisect → device_bisect

- 新建 `DeviceBisectSubstage`，agent 按 failure_type 选 printf/comment_bisect 方法
- 合并两个路由表为 device_bisect 一张（located_fixed/continue/case_more/case_done/deploy_broken）
- 保留两个 skill 文件（`ascendc-precision-printf`/`ascendc-precision-comment-bisect`），device_bisect agent 按需 tail-call
- 统一 `tried_bisect_paths` 接力文件

### 阶段 D：更新 tree + 测试

- `precision_debug_tree.py`：7 children → 5 children，路由表合并
- 更新/新增测试：合并后路由（applied_partial 就地 refine / failure_type 选 bisect 方法 / 接力文件落盘）

## 4. 验证（TDD）

### 现有 300 测试守护

合并后 300 个测试应**全绿**（合并不改变对外行为：路由结果相同，只是会话切分减少）。新增：

### 新增回归测试

1. **合并 1**：diagnose 会话内 refine 循环——applied_partial → 就地剥皮 → 更新接力文件 → 下一轮读接力文件（断言不重读全上下文）
2. **合并 2**：device_bisect 按 failure_type 选方法（precision→printf、runtime→comment_bisect）
3. **接力文件**：长上下文场景下，接力文件落盘完整（已剥层/已试 fix 不丢）
4. **路由不变**：合并后的 5 substage 路由与原来 7 substage 等价

## 5. 风险与缓解

| 风险 | 缓解 |
|---|---|
| diagnose 会话变长（合并 refine 后单会话更多轮） | 接力文件落盘保证信息不丢（核心设计）；超长有 message_timeout 兜底（P9 一并修） |
| device_bisect 合并两个 skill 方法 | 保留两个 skill 文件，按 failure_type tail-call；统一接力文件 |
| 300 测试可能有断言依赖 substage 数 | 先跑全量，定位后更新（合并是行为等价，断言应只依赖路由不依赖 substage 数） |

## 6. 完成判据

- [x] **阶段 A**（拆 diagnose transition）：`_handle_printf_route` / `_apply_evidence_flags` / `_handle_stall` 三个方法抽出，310 测试全绿
- [x] **阶段 C**（合并 printf+comment_bisect）：`_DeviceBisectSubstage` 基类收敛重复 transition/resolve_condition，两个子类只留 `_result_field` + 方法 prompt，310 测试全绿 + orchestration 1820 全绿
- [ ] **阶段 B**（合并 diagnose_refine→diagnose）：**暂缓**（2026-08-22 决策）——diagnose_refine 独立会话隔离剥皮循环，防主 diagnose 会话超长；合并收益被会话变长代价抵消，且 error_migration_evidence 接力已防信息丢失
- [x] 全量验证：`tests/ut/orchestration/` 1820 全绿

## 7. 实施记录（2026-08-22）

- 阶段 A：diagnose transition 190 行 → 主流程 + 3 方法（`_handle_printf_route` / `_apply_evidence_flags` / `_handle_stall`）
- 阶段 C：新增 `_DeviceBisectSubstage`（继承 `_PrecisionDebugSubstage`），PrintfLocate/CommentBisect 继承它，删除各自 ~100 行重复 transition/resolve_condition，只声明 `_result_field` / `_case_more_route` / `_case_done_route`
- 阶段 B：用户确认暂缓（独立会话有防超长价值）
- 后续候选：P1（框架自算 deploy_health）/ P2（框架读 run-cases 统计）/ P9（turn_stall 阈值）
