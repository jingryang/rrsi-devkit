# 问题索引：设计子阶段 missing_artifact 预算归并 + 重试不可观测

> 本文件是问题索引。每个问题一份独立文档，在 `issues/` 下，按 R 编号查看。
> 层归：本目录属于一次工作的 L1（问题记录）+ L3（方案分析）。索引本身不重复问题内容。

## 问题清单

| # | 标题 | 一句话 | 文档 | 状态 |
|---|------|--------|------|
| R1 | missing_artifact 烧稀缺的 iteration 预算，无独立重试通道 | 产物放错目录这种"确定性可纠正错误"与"模型迭代能力"共用同一预算，codegen 有独立 `artifact_max_retries` 而设计子阶段没有 | [R1](issues/R1-missing-artifact-burns-iteration-budget.md) | ✅ 方案 C runner 公共分支已实施（`test_artifact_retry_common.py` 4 绿 + orchestration 1820 绿） |
| R2 | 重试在 run.log / events.jsonl 中完全不可观测 | 重试只表现为 `agent_spawn`/`iteration_start` 重复，无 `retry-N` 标注、无剩余预算、无缺产物提示 | [R2](issues/R2-retry-invisible-in-logs.md) | ✅ `artifact_missing_retry` 事件已加（R2 事件测试绿） |

## 批跑背景速览

- 批跑 ID：`20260821-111953-bca2fa`
- 算子：rms_norm、moe_re_routing、add_rms_norm_dynamic_quant（3 算子并发）
- 证据算子：add_rms_norm_dynamic_quant（execution `20260821-111953-af8b09`）
- 后端：opencode（`agent_backend=opencode`）
- 模型：`pangu_ultra_moe`（`92bpangu` provider，非历史批的 glm-5.3）
- halt 位置：`detailed-design/tiling/T2/tiling/tiling`
- 证据原始位置：`output/20260821-111953-bca2fa/20260821-111953-af8b09/{run.log, events.jsonl, state_snapshot.json, agents/*.jsonl}`

## 事实证据（T2 完整轨迹）

**events.jsonl（权威源，iteration_start 事件）**：
```
11:38:35  iteration_start  iteration=1  reason=""
11:45:09  iteration_start  iteration=1  reason="contract unsatisfied: tiling_results"   ← silent-cut 恢复，iteration 不递增
11:52:34  iteration_start  iteration=2  reason="quality check not satisfied"            ← 第二次真正迭代
11:52:51  spawn_context / infra_backoff（spawn 失败，infra-retry 1/4）
11:55:20  stage_complete（halt）
```

**run.log 同段**：
```
19:38:35  stage_iteration tiling/T2 iteration 1/2
19:45:09  stage_iteration tiling/T2 iteration 1/2 (contract unsatisfied: tiling_results)
19:45:16  agent_resume ... (sidecar present — silent-cut recovery)
19:52:34  stage_iteration tiling/T2 iteration 2/2 (quality check not satisfied)
19:52:51  [ERROR] Agent ... opencode spawn failed: Remote end closed ...
19:52:51  infra_backoff ... (infra-retry 1/4)
19:55:20  [WARN] → missing_artifact: tiling: 产物 tiling_split.json 未在正确目录找到 ...
19:55:20  [WARN] Stage 'tiling' failed with fail_strategy=halt
19:57:57  [ERROR] Workflow halted: stage 'T2/tiling' failed with fail_strategy=halt
```

**配置**：`resources/orchestration-config.json`
- `iterations.stages.tiling = 2`（iteration 预算仅 2 次）
- `codegen.artifact_max_retries = 5`（codegen 有独立 artifact-retry，设计子阶段无）

## 解决方向（详见 L3 `02-analysis.md` 方案 C + L4 `03-impl-common-artifact-retry.md`）

- **R1+R2 同源修复**：方案 C——runner 层公共 artifact-retry 抽象。把"产物契约未满足 → 独立定向重试 → 不烧 iteration"从 codegen 专属实现上移为 runner 公共机制，design/codegen/precision 三阶段统一继承（§1.15 收敛）；重试加可观测信号（R2）。

## 责任划分摘要（详见 L3 `02-analysis.md`）

- **框架缺陷（主要）**：
  - R1：设计子阶段 missing_artifact 直接烧 iteration 预算，无独立重试通道（与 codegen 的 `artifact_max_retries` 不一致）。
  - R2：重试动作无独立日志语义，`agent_spawn`/`iteration_start` 重复即"重试"，读者无法区分"新起"与"重试"、无法看到剩余预算与重试原因。
- **模型/外部因素**：pangu_ultra_moe 吐字回合多（相对 glm-5.3），且本轮有 1 次 infra spawn 失败（网关瞬断）——但这些不是 R1/R2 的根因，只是放大效应。
