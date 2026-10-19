# 问题索引：precision_debug 整体设计原则符合性排查

> 本文件是问题索引。每个问题一份独立文档，在 `issues/` 下，按 P 编号查看。
> 层归：本目录属于一次工作的 L1（问题记录）+ L3（方案分析）。索引本身不重复问题内容。
> 排查背景：20260821 批 rms_norm eval 0 分根因（R3 deploy_health null 误熔断）触发对 precision_debug 整体设计的系统排查。

## 问题清单

| # | 标题 | 一句话 | 文档 | 状态 |
|---|------|--------|------|
| P1 | deploy_health 职责错位 | 确定性信号（build/run 结果）委托给 agent 申报，null 误触发熔断 | [P1](issues/R3-deploy-health-responsibility-misplaced.md) | ✅ 完整版已修（2026-08-22，框架从 last_deploy.json 自算+删除 comment_bisect 漏删的活 bug override，见 [07-impl](07-impl-deploy-health-framework.md)） |
| P2 | run_tests 让 agent 申报框架可算的确定性信号 | `total_count`/`failure_type`/`blocking`/`cascade_suspected` 纯算术或框架 CLI 可观测，却让 LLM 申报 | [P2](issues/P2-run-tests-agent-reports-framework-knowable.md) | ✅ 已修（2026-08-22，统计面框架派生 + cascade/probe 发现框架派生；`blocking` 属 LLM 语义保留 agent，见 [05-impl](05-impl-run-tests-framework-stats.md) §8.7） |
| P3 | diagnose transition 过度复杂 | ~190 行 transition 承载全部路由决策，多计数器交错难维护 | [P3](issues/P3-diagnose-transition-overcomplex.md) | ✅ 已修（2026-08-22 阶段A 拆分：`_handle_printf_route`/`_apply_evidence_flags`/`_handle_stall`，见 [04-impl](04-impl-substage-merge.md)） |
| P4 | 多计数器交错失控 | corrective_cycles/refine_cycles/diagnose_stalls/attempt_count/rounds 五计数器互锁 | [P4](issues/P4-multiple-counters-interlock.md) | 部分缓解（阶段A 拆分提升可维护性；计数器语义未变，彻底收敛待后续评估） |
| P5 | A3/A5 双实现重复 | 同职责写两遍（_sync_debug_result/_common_context/transition 模板），且 A5 缺 teardown/entry-commit/schema | [P5](issues/P5-a3-a5-duplication.md) | 不动（A5 归同事，用户指示保持原样） |
| P6 | agent 自评路由（route_to）影响关键控制流 | 路由决策（fix vs printf_location）由 agent 自评，无值域校验时静默默认 | [P6](issues/P6-agent-self-routed-route-to.md) | ✅ 已修（2026-08-22，值域校验+违约 WARN，判断权保留 agent） |
| P7 | A5 is_vf_issue 确定性路由纯 LLM 自评 | 是否进 vf_test 的门控完全依赖 LLM，无校验/无默认/无违约日志 | [P7](issues/P7-a5-is-vf-issue-routing.md) | 不动（A5 归同事） |
| P8 | A5 best_snapshot 让 skill 成为精度权威 | per-round 精度数字本可从 result JSON 确定性读，却让 LLM 先写、框架再核对 | [P8](issues/P8-a5-best-snapshot-authority.md) | 不动（A5 归同事） |
| P9 | turn_stall 看门狗误杀深推理模型 | 无新 token 超 120s 即中断，而 pangu 单 turn 深推理可达 1300s+，正常思考被误判卡死（moe 20260822 实证） | [P9](issues/P9-turn-stall-kills-deep-reasoning.md) | ✅ 已修（2026-08-22，tool 界让位 + 600s + aborted 去冒充，见 [06-impl](06-impl-turn-stall-deep-reasoning.md)） |

## 排查方法

- 通读 `precision_debug_tree.py`（路由表）+ `precision_debug_substages.py`（A3 7 子阶段）+ `precision_debug_a5.py`（A5 5 子阶段）
- 逐条对照 CLAUDE.md §1.2/§1.3/§1.10/§1.14/§1.15/§2.9/§2.10
- 证据链：rms_norm 20260821 批（deploy_health null → deploy_broken 熔断 → eval 0 分）

## 方案文档

- [02-analysis.md](02-analysis.md) — 三类根因 + 修复方向
- [03-analysis-overweight-model-capability.md](03-analysis-overweight-model-capability.md) — 过重限制模型能力分析（§1.14 对照）
- [04-impl-substage-merge.md](04-impl-substage-merge.md) — substage 合并方案（7→5，参照 TilingStage 接力文件防长上下文丢信息）
- [05-impl-run-tests-framework-stats.md](05-impl-run-tests-framework-stats.md) — P2：run_tests 确定性信号框架接管（agent 只填路径，框架从 result.json 读数据）
- [06-impl-turn-stall-deep-reasoning.md](06-impl-turn-stall-deep-reasoning.md) — P9：turn_stall 看门狗误杀修正（tool 界让位 + 600s + aborted 去冒充）
- [07-impl-deploy-health-framework.md](07-impl-deploy-health-framework.md) — P1 完整版：deploy_health 框架自算（last_deploy.json + spawn 窗口戳；顺带删 comment_bisect 漏删的活 bug override）

## 责任划分摘要

- **框架缺陷（主要）**：P1-P6——确定性信号委托给 agent、transition 过度复杂、计数器交错、双实现重复。
- **模型/外部**：agent 填 null / 不填 route_to（LLM 不可靠）只是暴露了框架把这些信号设为 agent 申报的缺陷。
