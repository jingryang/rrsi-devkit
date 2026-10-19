# 问题索引：20260820-103324-793414 批跑兜底重试失效

> 本文件是问题索引。每个问题一份独立文档，在 `issues/` 下，按 F 编号查看。
> 层归：本目录属于一次工作的 L1（问题记录）+ L3（方案分析）。索引本身不重复问题内容。

## 问题清单

| # | 标题 | 一句话 | 文档 | 状态 |
|---|------|--------|------|
| F1 | 孤儿产物对框架不可见，契约永远不满足 | 产物写错目录后框架完全感知不到，只能靠重试耗尽 | [F1](issues/F1-orphan-artifacts-invisible.md)  ✅ F3 全局收口 |
| F2 | 框架已精确定位孤儿产物，却只注入反馈、不驱动收集 | `_harvest_relocation_evidence` 拿到 `actual_path` 只用于反馈文本 | [F2](issues/F2-evidence-not-fed-to-collection.md)  ✅ F3/F7 统一 |
| F3 | 非交互 batch 下 pending_relocation 自动选 KEEP（不搬回） | 框架明知文件在哪，却默认不搬，修复寄托 LLM 自觉 | [F3](issues/F3-relocation-defaults-keep-in-batch.md)  ✅ 19f377f3 |
| F4 | silent-cut 与 resume 计数脱节，cut-resume 循环不触发 fresh | `resume_fails` 不统计"resume 后仍 cut"，fresh 重开永不触发 | [F4](issues/F4-silent-cut-resume-decoupled.md)  ✅ 62819c42 |
| F5 | `empty_artifacts` 在 runner 与 codegen 两处语义冲突 | runner 视为 ok，codegen 视为失败熔断 | [F5](issues/F5-empty-artifacts-semantics-conflict.md)  ✅ f1533e6f |
| F6 | stage_complete status 与最终 state 脱节（成功却记 failed） | d8d4d9 requirement 实际成功，events 记 failed | [F6](issues/F6-stage-status-detached-from-state.md)  ✅ bc871c85 |
| F7 | 契约检查与产物收集两套逻辑，不共享证据 | 定位证据不反哺收集，信息孤岛 | [F7](issues/F7-collection-and-locating-disconnected.md)  ✅ 9c958ce1 |
| F8 | 纠正反馈机制没有执行保障 | 反馈文本正确但只改 prompt，模型不遵守即白给 | [F8](issues/F8-feedback-no-enforcement.md)  ✅ d071dc30 |
| F9 | "read-only 空产出"被判定为合法，静默吞掉 | 读 26 次文件零写盘被当"合法 read-only"，不报警 | [F9](issues/F9-readonly-empty-swallowed.md)  ✅ d6dddf6e |
| F10 | 各 stage 重试预算与失败模式不匹配 | 预算只表达"最多几次"，不区分失败模式与策略 | [F10](issues/F10-budget-vs-failure-mode.md)  ✅ 4a7af7db |
| F11 | silent-cut 不消耗 iteration 计数，日志读数误导 | `iteration 1/10` 从不变化，实际已重试多次 | [F11](issues/F11-silent-cut-not-counted-in-iteration.md)  ✅ 73a85f75 |

## 批跑背景速览

- 批跑 ID：`20260820-103324-793414`
- 算子：rms_norm、moe_re_routing、add_rms_norm_dynamic_quant（3/3 全失败）
- 后端：opencode（`agent_backend=opencode`）
- 模型：`pangu_ultra_moe`
- 证据原始位置：`output/20260820-103324-793414/<run_dir>/{run.log, events.jsonl, state_snapshot.json, agents/*.jsonl}`

## 责任划分摘要（详见 L3 `02-analysis.md`）

- **模型能力**：写孤儿目录（路径幻觉）、巨量 thinking 空转、收到纠正反馈仍不遵守。
- **框架缺陷**：F1-F11（见上表）。核心是"检测到错误却无法确定性修复"（F1/F2/F3）与"无效重试无法识别"（F4/F9）。
