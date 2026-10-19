# e2e 稳定性 — L1 问题记录（2026-06-22）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/现象/根因/影响）。
> 修复方案见 `02-analysis.md`（L3）；实施方案见 `03-impl-*.md`（L4）。
>
> **状态：已收口 / superseded（2026-07-09）**。本文件 P1–P9 已全部解决——或直接修复、或并入现行权威 track `self-evolution/06-problems.md`。按 §1.8，「修复记录」产权转移至 self-evolution，本文件只保留「事实记录」产权。去向（于当前代码核实）：
> - P1（max_turns=15 截断 Agent）→ 直接修复：`SDKBackend` 默认 `max_turns=10000`
> - P2/P3（失败静默继续 + transition_table 盲区）→ 直接修复 + self-evo **P46/P51**：`_DesignSubstage.fail_strategy=halt`、halt 硬崩溃停管线、continue-stage 崩溃按根因路由（`_classify_uncaught`/`on_uncaught_failure`）
> - P4（`_collect_changed_sources` 设计/codegen 复用）→ 直接修复：设计改确定性声明文件名磁盘读，`_collect` 要求 git baseline
> - P5/P9（last_error 粘滞；codegen/verify 成功不清 own last_error）→ 直接修复：成功分支 `last_error=None`（commit `096563a`）
> - P6（template-division stall + RuntimeError）→ 直接修复：`aclose` 非致命 + 自适应停滞检测
> - P7（requirement-analyst 未注入完整 SKILL.md）→ 直接修复：`requirement.py` 前置 `/stage-requirement:` slash 注入
> - P8（review 截断误标 partial）→ 直接修复：`output_contract` 满足时 partial→ok 降级

本记录基于 `rope-e2e.log` 的实时日志只读分析 + 源码全量审查。运行命令类似上次 run（rotary_position_embedding 算子，mode=incremental / non-interactive）。

日志文件：`rope-e2e.log`
运行目录：`output/20260622-112641-e867db/`

**事后验证（2026-06-23）**：`run_20260623_152938.log` 全量执行（rotary_position_embedding 算子，design 阶段完整跑完）验证结果：

| 问题 | 原始现象 | 验证结果 |
|------|---------|---------|
| P1 (max_turns=15) | 所有 agent 约 45 轮截断 | ✅ 不再出现；`max_turns=10000` 已生效（max 达 53 轮均干净完成） |
| P2/P3 (失败静默继续) | template-division crash→跳过继续 | ✅ 不再出现；全部 13 个 stage 均 `✓` 完成 |
| P4 (产物收集) | 设计阶段产物走错收集路径 | ✅ 不再出现；产物列表均含正确文件（`tiling_split.json`、`general_design.json` 等） |
| P5 (last_error 粘滞) | 迭代 2 成功但有 sticky 误报 | ✅ 不再出现；全部 stage 状态一致性检查通过（无 partial/failed 伴随完整产物） |
| P6 (stall + RuntimeError) | 3 轮 stall + aclose() | ✅ 不再出现；全流程 0 次 stall / agent_resume / transient error |
| P7 (requirement SKILL.md) | agent 缺方法学 | ✅ step-10 L4-a schema 收口已落地（requirement SKILL.md 自包含） |
| P8 (partial 误标) | review 截断但产物完整标 partial | ✅ 不再出现；max_turns=10000 根除截断，partial 判定含 contract 满足性检查 |

---

## P1（严重）：max_turns=15 导致 Agent 普遍被截断

### 证据

所有 Agent 实际轮数远超 max_turns=15：

- `requirement`: 26 轮
- `gd-generate`: 38 轮
- `general-design-review`: 46 轮
- `template-division`: 45 轮
- `split` T1-T3: 41-45 轮
- `buffer-kernel` T1: 39+ 轮

多个阶段在约 45 轮触发 `Reached maximum number of turns (15)`（第 139 行、334 行、378 行）。

### 根因

`SDKBackend.__init__` 默认值 `max_turns: int = 15`（`sdk_backend.py:350`）。三处 dispatcher 构造 `SDKBackend` 均不传 `max_turns`。所有 agent manifest（`.claude/agents/*.md`）也未声明该字段。SDK 流式传输不按此截断，但 Claude Code 平台端达到硬限制时抛 ProcessError。

### 影响

tiling 阶段 design agent 在写产物前被截断 → 产物缺失或 partia、→ pipeline 断裂。

---

## P2（严重）：失败后 pipeline 静默继续

### 证据

`template-division` agent crash → 控制台 `✗ failed` → 但 pipeline 不中断，直接跳到 `tiling` fork-join 节点（第 209-218 行）。所有非 gate 阶段失败行为相同。

### 根因

`runner.run_stage` 把失败信号消化了：`stage_status` 只用于控制台 `✓/⚠/✗`（`runner.py:306-312`），不抛异常、不设 `is_terminal`。`graph_executor._execute_sequential` 靠 `stage.resolve_condition()` → `transition_table` 决定路由，但仅 3 个 quality-gate 阶段覆盖此方法。其他阶段返回 `"default"` → transition_table 无匹配 → `i += 1` 线性跳过。

### 影响

上游阶段失败后下游在断链状态上继续运行，产出无意义或误导性结果。

---

## P3（严重）：transition_table 只覆盖 quality-gate 阶段

### 证据

`_DETAILED_DESIGN_TRANSITION_TABLE`（`design_tree.py:41-61`）只注册了 `dd-intake`、`anchor-check`、`validate` 的路由。`template-division`、`integrate`、`docgen` 及所有 tiling 段（split/buffer-kernel/precision-perf）均无条目，失败后直接跳到下一节点。

### 根因

transition_table 设计假设"只有 gate 阶段需要回退路由"，其余阶段线性推进即可。未考虑 agent crash / 产物缺失的路径。

### 影响

与 P2 叠加：P2 导致失败不中断，P3 导致失败后无路由可选 → 唯一路径是线性跳过。

---

## P4（严重）：设计阶段产物收集与 codegen 复用同一函数 `_collect_changed_sources`

### 证据

`SDKBackend._spawn` 通过 `_collect()` → `_collect_changed_sources()` 收集产物。该函数为 codegen 的"在真实仓库中做增量变更"场景设计（git diff + changed_files.json 并集），但设计阶段也被塞进同一函数。路径对比如下：

| | 设计阶段 | Codegen 阶段 |
|---|---|---|
| working_dir | `artifacts/design/gd-generate/`（空目录） | op_dir 下属源码目录（有存量） |
| SpawnAction 传参 | 无 `repo_baseline`/`repo_root` | 有 `repo_baseline`/`repo_root` |
| 实际收集策略 | `_scan_working_dir` 降级扫全目录 | git diff + ls-files 并集 |
| 风险 | 输入文件也被扫入，不校验 contract | — |

`_scan_working_dir`（`sdk_backend.py:142-154`）`rglob("*")` 扫目录下所有 `.json`/`.cpp`/`.py`——包括 `_materialize_inputs` 写入的输入文件（requirement.json、general_design.json 等），在 tiling 分支下还包括上游副本（template_division.json 等），这些输入文件会被误收入产物列表。

### 根因

`_collect_changed_sources` 没有区分"零基目录按声明文件名收集"（设计）和"存量仓库发现变更"（codegen）两种语义。

### 影响

产物列表混入输入文件；依赖降级路径，一旦 `has_baseline=True` 则返回空字典（见 `_collect_changed_sources:301-304`）。

---

## P5（中等）：last_error 跨迭代粘滞误报

### 证据

`template-division` 第 2 次迭代成功产出 `template_division.json`（76行/5169字节，文件系统确证），但控制台输出：
```
✗ template-division done (264.2s) [failed]
[WARN] → missing_artifact: template_division.json: required artifact not produced
```
（日志第 209/213 行）

### 根因

迭代 1 的 `_parse_single` 未能从 agent_result 取到产物 → 写入 `last_error = ErrorFeedback(stage_name="template-division", error_type="missing_artifact")`。迭代 2 成功时 `_parse_single` 不清理 `last_error`（`design_substages.py:336-338`，`with_updates` 无 `"last_error": None`）。`runner.run_stage:302-305` 读到 sticky last_error 且 stage_name 匹配 → 误报为失败。

### 影响

false alarm 噪音，且干扰后续决策（如果 fail_strategy 生效，会基于假信号 halt）。

---

## P6（中等）：template-division stall + RuntimeError

### 证据

```
[WARN] Agent ascendc-design-generator stalled: 3 consecutive turns with no new text
and no effective tool use (repeated/erroring calls).
RuntimeError: aclose(): asynchronous generator is already running
```
（日志第 157-160 行）

### 根因

agent 在 8 轮后陷入重复工具调用（反复读文件但不产出）。SDK stall 检测（`MAX_STALLED_TURNS=3`）触发提前终止。异步生成器关闭时竞态条件导致 `aclose()` RuntimeError。

### 影响

浪费迭代配额（第 1 次迭代无效 + 第 2 次从零重跑）。

---

## P7（中等）：requirement-analyst 未注入完整 SKILL.md

### 证据

`requirement.py` 通过 `SchemaLoader.load_contract_from_skill("stage-requirement", "ascendc-op-req-analysis")` 加载 schema 契约，但 spawn agent 的首条 prompt 未包含 slash command 触发词（如 `/stage-requirement:ascendc-op-req-analysis`）。

对比：所有设计子阶段 spawn 首条消息均以 `/stage-design:<skill>` 开头，CLI 展开注入完整 SKILL.md。

### 根因

`_build_analysis_prompt` 未调用 `_with_trigger()` 注入 slash command。requirement 阶段没有走 STAGE_SKILL_MAP 机制。

### 影响

requirement analyst agent 拿不到 SKILL.md 中的完整分析方法（输入规范、输出 schema 之外的方法学），仅靠 contract 约束产出格式。

---

## P8（中等）：general-design-review 截断但产物完整，误标 partial

### 证据

```
[ERROR] Agent ascendc-design-reviewer query attempt 1 failed: Reached maximum number of turns (15)
⚠ general-design-review done (198.7s) [partial]
```
（日志第 139-140 行）

但 `general_design_reviewed.json` 实际产出完整：`status: "completed"`, `blocking_issues: []`, `patched_nodes` 含 3 项已完成的就地修复。

### 根因

review agent 在过程中完成全部修复和校验，第 46 轮 hit max_turns 抛异常。`agent_status="partial"` → `stage_status="partial"`，未检查 `output_contract` 是否已被满足。

### 影响

gate 阶段被误标为失败，下游可能以此为信号做错误决策。

---

## P9（严重）：codegen/verify 成功分支不清 own last_error，resume 误判 failed（P5 同类回归）

### 证据

run 29a24f（self_evolve_op）：codegen 实际成功——产出全部源文件 + 完整 codegen_manifest（callable_target{kind, symbol} 齐备）+ codegen_consecutive_failures 复位为 0；权威 events.jsonl 记 codegen stage_complete result=ok。但最终 node_status 与 halt 判定 codegen=failed，整条 pipeline 中止。result=ok 与 failed 自相矛盾。

### 根因

P5 的同一不变式（stage 成功必须清自己的 last_error）未全链路收口：P5 当时只修了 design_substages._parse_single，codegen / verify 的成功分支漏修。一次失败的 codegen 写入 last_error(stage_name=codegen)；resume 重跑成功后，残留 own last_error 仍在，runner 的 own_error 判定（stage_name 匹配即 failed，且先于 output_contract 满足性检查）据此误判 failed。verify 同类：成功分支（build passed）不清 own last_error，codegen loopback 修复后重进 verify 会被残留 compile_error 钉成死循环。P5 的 2026-06-23 事后验证只覆盖 design 子阶段，未验 codegen/verify，故漏网至今。

### 影响

resume 场景成功 stage 被误判 failed → pipeline 无故 halt（29a24f）；verify 路径死循环。

---

## 完整日志补充（第 461-1660 行）

完整日志覆盖 anchor-check → integrate → validate → test-analyze → test-casedesign → test-casegen → halt 全流程。补充观察如下，**均已由 P1-P4 方案覆盖，无需新增独立问题**：

| 补充现象 | 日志行号 | 覆盖方案 |
|---------|---------|---------|
| split/T2、split/T3 产物列表只有输入文件，缺失 tiling_split.json | 635-638, 715-718 | P4：确定性磁盘读取不走 `_collect_changed_sources` |
| anchor-check 3 轮 max_turns 截断后直接进入 integrate | 1080-1085 | P2/P3：gate 阶段 `fail_strategy="continue"` 由 blocking_issues 路由 |
| integrate 2 轮 max_turns 截断后直接进入 docgen | 1180-1188 | P2/P3：`_DesignSubstage.fail_strategy="halt"` 生效后 integrate 失败会 halt |
| test-analyze 3 轮耗尽后进入 test-casedesign → test-casegen | 1356-1362+ | P2/P3：`_TestDesignSubstage` 继承 `_DesignSubstage`，halt 覆盖 |
| anchor_report.json JSON 格式错误（`Expecting ',' delimiter`） | 1084 | P4：`_parse_single` JSONDecodeError catch 已处理 |
| precision-perf/T3 stall + RuntimeError（8 轮后） | 831-834 | P6：同 template-division stall，后期跟进 |
|最终 halt 消息 "build/precision failure"，实为设计阶段 agent 全链路 crash | 1660 | dispatcher/finalize 报告逻辑，DFX 问题，不影响正确性 |
| fork-join 并发下 turn 延迟暴涨至 400-500s | 709-712, 805, 845 | LLM API/relay 基础设施，非代码可修 |

## 证据索引

| 证据 | 日志行号 |
|------|---------|
| general-design-review crash | 139 |
| template-division stall | 157-160 |
| template-division failed + missing_artifact | 209, 213 |
| split partial 3 路 | 379 |
| buffer-kernel 进行中 | 384+ |
| general_design_reviewed.json 完整 | 产物文件验证 |
| template_division.json 存在于文件系统 | 产物文件验证 |
| anchor-check 3 轮全截断 | 969, 1029, 1079 |
| split/T3 产物列表只有上游输入 | 715-718 |
| integrate 3 件套全缺失 | 1180-1185 |
| test 全链路 partial | 1358-1660 |
