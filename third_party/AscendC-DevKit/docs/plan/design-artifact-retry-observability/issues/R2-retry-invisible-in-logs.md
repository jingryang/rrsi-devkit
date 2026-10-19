# R2: 重试在 run.log / events.jsonl 中完全不可观测

**状态**: 待修
**层归**: L1 问题记录（只述事实，不提方案）

## 哪里坏了？

"有限次重试"发生了，但**从 run.log 完全看不出来**——重试只表现为 `agent_spawn` / `iteration_start` 的重复，无 `retry-N` 标注、无剩余预算、无重试原因。读者看到的是"spawn → 沉默 → spawn → 沉默 → halt"，无法区分"新起一个 agent"与"重试上一次失败"。

## 凭什么这么说？（证据）

**事实 1：run.log 里 T2 的重试无任何 retry 字样**

`output/20260821-111953-bca2fa/20260821-111953-af8b09/run.log` T2 段全部非 agent_stream 行：
```
19:38:35  agent_spawn [T2] starting (opencode serve :45989)
19:45:09  agent_spawn [T2] starting (opencode serve :48091)
19:45:16  agent_resume [T2] auto-resuming session ... (sidecar present — silent-cut recovery)
19:52:34  agent_spawn [T2] starting (opencode serve :41317)
19:53:11  agent_spawn [T2] starting (opencode serve :56101)
19:53:18  agent_resume [T2] auto-resuming session ...
```
4 次 `agent_spawn` = 4 次重试，但没有任何一次标注"retry"。`agent_resume`（silent-cut 恢复）与 `agent_spawn`（iteration 重试）外观几乎相同。

**事实 2：events.jsonl 的 iteration_start 无显式重试语义**

`events.jsonl` 里 T2 的 `iteration_start` 事件：
```json
{"ts":"11:38:35","type":"iteration_start","stage":".../T2/...","iteration":1,"reason":""}
{"ts":"11:45:09","type":"iteration_start","stage":".../T2/...","iteration":1,"reason":"contract unsatisfied: tiling_results"}
{"ts":"11:52:34","type":"iteration_start","stage":".../T2/...","iteration":2,"reason":"quality check not satisfied"}
```
- `iteration=1` 出现两次（silent-cut 不递增）——第 2 次实为**重试**，但事件类型仍是 `iteration_start`，无 `retry-N` 字段。
- 无"剩余预算"字段（读者不知 2/2 后即 halt）。
- `reason` 只有 `contract unsatisfied` / `quality check`，**不含**"产物缺失：tiling_split.json"这个真正的失败原因——缺产物的事实只在最终 halt 时由 run.log 报出。

**事实 3：missing_artifact 的重试过程静默**

缺产物（`tiling_split.json 未在正确目录找到`）只在**最终 halt** 时报一次（run.log 19:55:20）。重试期间（19:45→19:52）框架完全没提"产物缺失"，agent 拿到的 `user_feedback` 位置提示只在 spawn 的 prompt 里，不落日志。

**事实 4：events.jsonl 无 retry 事件类型**

`events.jsonl` 的 T2 事件类型集合：`stage_enter / iteration_start / spawn_context / infra_backoff / stage_complete`。**没有** `artifact_retry` / `retry` / `missing_artifact` 事件类型。`infra_backoff` 有独立类型（且带 `infra-retry 1/4` 计数），而 missing_artifact 重试没有。

## 影响

- **可诊断性归零（§1.2 四把尺子之"可诊断"）**：用户/维护者无法从任何日志判断"重试是否发生、发生了几次、还剩几次、为什么重试"。重试对观测者等于不存在。
- **误导计数**：`iteration 1/2` 重复出现让读者以为没重试（F11 已修 silent-cut 计数，但 R2 是**非 cut** 重试的剩余盲区）。
- **与 infra_backoff 形成反差**：infra 重试有独立事件类型 + `infra-retry 1/4` 计数，missing_artifact 重试却完全无迹——同属"异常路径重试"，可观测性天壤之别。

## 与既有问题编号的边界

- **F11**（silent-cut-not-counted-in-iteration, 73a85f75）：F11 修的是"silent-cut 不烧预算但日志不递增 iteration"，R2 是**非 cut 重试**（contract unsatisfied / missing_artifact 触发的 iteration 重试）**完全不可观测**——iteration 编号在日志里是有的（1/2→2/2），但"重试"这个语义没有被任何日志事件表达。F11 已让 cut 日志带两套计数，R2 要求**所有重试**（含 missing_artifact）都有独立、可读的日志信号。
- **R1**（预算归并）：R1 是"重试预算的分配"问题，R2 是"重试的观测"问题，二者正交但同源——都源于设计子阶段的 missing_artifact 处理被当作普通迭代对待。
