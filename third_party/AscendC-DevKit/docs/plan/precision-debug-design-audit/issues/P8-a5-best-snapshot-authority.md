# P8: A5 best_snapshot 让 skill 成为精度数字权威来源

**状态**: 待修
**层归**: L1 问题记录（只述事实，方案在 L3）

## 哪里坏了？

A5 的 `best_snapshot`（每轮最优精度快照）由 **skill 写 checkpoint.json**，框架注释明确"the skill is the authoritative source of per-round precision numbers"（L162-163）。框架虽在 `_merge_best_snapshot` 做交叉核对（L223-232）+ 漏写重建（L233-239），但**信任方向仍偏斜**——per-round 精度数字（max_err/passed/failed）本可从 result JSON 确定性读取，却让 LLM 先写、框架再核对。

## 凭什么这么说？（证据，来自 A5 深度审计）

### 事实 1：skill 写 best_snapshot，框架只核对

`precision_debug_a5.py`:
- `best_snapshot`（含 max_err/commit/passed/failed_cases）由 skill 写（L157-284）
- `_merge_best_snapshot`（L191-253）交叉核对：skill 声称的失败数与 result JSON 不一致 → 以 result JSON 为准
- skill 漏写时从 result JSON 重建（L233-239）

### 事实 2：交叉核对方向反了

框架**已有** result JSON（确定性精度数字来源），却让 skill 先写 best_snapshot、框架再"核对"——这比直接"框架从 result JSON 读精度数字"多了一层 LLM 申报 + 核对，是**不必要的中间层**。

### 事实 3：正确方向（对照 A3）

A3 的 run_tests transition 已经从 result JSON 读 `max_err`/`passed_count` 计算 best_*（`_update_best_metrics`），**框架自己算**，不依赖 agent 申报精度数字。A5 反而倒退让 skill 申报。

## 影响

- **§1.10 违背**：per-round 精度数字是确定性事实（result JSON 有），却让 LLM 先写。
- **双源不一致**：skill 写的 best_snapshot 与 result JSON 可能冲突，框架虽以 result 为准，但 agent 白写一层。
- **§1.2 可诊断**：核对逻辑（L223-232）只在不一致时报 warn，但"为什么 skill 写错"被静默。

## 与既有问题边界

- **P2**（A3 run_tests 申报 total_count）：P2 是 A3 的同类，P8 是 A5 的同类——框架能确定性读取却让 agent 申报。
- **P7**（A5 is_vf_issue）：P7 是路由、P8 是精度权威，A5 两个委托面。
