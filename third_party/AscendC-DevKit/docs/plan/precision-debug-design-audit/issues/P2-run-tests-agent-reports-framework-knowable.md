# P2: run_tests 让 agent 申报框架可算的确定性信号

**状态**: ✅ 已修（2026-08-22，统计信号面：total/failed/failure_type 聚合/status=passed/history 条目全部改为框架从 result.json 派生——transition 重跑 build-failed-case-queue.py 解析 stdout，agent `_summary` 收敛为仅 observed_issues；同日第二段实施收敛"发现"遗留面：`cascade_suspected`（runtime 失败率 >80%）/`crash_masking_probe_needed`（全量 runtime）改为 transition 纯算术派生，agent 不再申报，消费端（diagnose 读 control.json.observed_issues）零改动；方案见 [05-impl](../05-impl-run-tests-framework-stats.md) §8.7。`observed_issues[].blocking` 保留 agent 判定——属 LLM 语义（"问题是否使有效 case 无法被消费"需读日志理解），非遗留缺陷）
**层归**: L1 问题记录（只述事实，方案在 L3）

## 哪里坏了？

run_tests 阶段把**框架可确定性计算/观测的信号**委托给 agent 在 `_summary` 里申报，包括：`total_count`（用例总数）、`failure_type`（compilation/runtime 分类）、`blocking`（问题是否阻断）、`cascade_suspected`（失败率>80% 判定）、`crash_masking_probe_needed`（全量崩溃判定）。这些要么是纯算术（框架可算），要么是框架 CLI 可直接观测（run-cases 的输出），却让 LLM 申报——LLM 填不准就污染下游路由。

## 凭什么这么说？（证据）

### 事实 1：框架自有 `run-cases` CLI，用例总数/失败数是框架可观测的

`src/ascendc_devkit/cli/commands/debug.py:61` 定义 `ascendc-devkit run-cases`（P54 D11），框架调用它并**能拿到**：
- 用例总数（total）
- 每个 case 的 passed/failed/crashed
- 失败类型（compilation/runtime）
- 运行日志（run.log）

这些是**确定性事实**，框架 100% 可观测。

### 事实 2：但 SKILL.md 让 agent 申报这些信号

`run_tests` SKILL.md:
```
| `_summary` | **必须写**。字段：`failure_type` / `test_result` / `failed_count` / `total_count` / `max_err` / `last_run_log` |
```
`total_count` 来自 `_summary`（skill 契约强制）；缺则 0 → passed=0。**agent 不填 → passed 算错**。

### 事实 3：纯算术判定也交给 agent

run_tests SKILL.md:
```
- **级联崩溃检测（§P3-FIX）**：run_tests 完成后，若 `failed_count > 80% total` 且失败均为 `runtime`，在 `_summary.observed_issues` 中追加 `{category: "cascade_suspected", ...}`
- **全量崩溃精度探针**：若全部 case 均为 `failure_type=runtime`，追加 `{category: "crash_masking_probe_needed", ...}`
```
`failed_count > 80% total` 是**纯算术**，框架在 transition 里就能算（它已读取 failed_case_queue），却让 agent 判断并申报。

### 事实 4：`blocking` 暴露判定交给 agent

run_tests SKILL.md:
```
并由你显式判定 `blocking`——框架只检查该字段
```
"是否阻断"是**路由决策**（决定是否触发 scope_guard），却由 agent 主观判定。agent 判错 → scope_guard 误路由。

## 影响

- **确定性决策建立在不可靠申报上**（P1 同源）：agent 填错/不填 → passed 算错、路由误判。
- **§1.10 违背**：`blocking`/`cascade_suspected` 是业务语义判定（是否暴露/是否级联），但判据本可由框架从确定信号（失败率、失败类型）派生，却让 LLM 主观评。
- **§1.2 可诊断失败**：agent 申报的信号无值域校验（除 scope_verdict 有严格契约），错误静默流入路由。

## 与既有问题边界

- **P1（=R3）**：deploy_health 是"deploy 健康"申报；P2 是"用例统计/失败分类/暴露判定"申报。同源（确定性委托给 agent），不同信号面。
- **§P3-FIX / §addrmsnorm-P7**：这些是历史加的功能（级联检测、崩溃探针），但实现方式（让 agent 申报）违背原则。
