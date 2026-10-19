# 01 — 问题记录（L1）

> 本工作：`docs/plan/synthesize-docgen-dilution/`。只记**客观事实**（哪里坏、凭什么这么说），不提方案、不排顺序、不写决策（那些归 L3/L4）。

## P1 — synthesize 门面串行 tail-call 下，docgen 子 skill 在长上下文被稀释/遗忘，缺 md → halt

### 现象

- batch `20260816-163138` 三算子端到端：`unique` 在 synthesize 阶段 halt，错误
  `skill produced no *_详细设计说明书.md`；`grid_sampler_3d` / `resize_bilinear` 同阶段成功产出 md。
- unique 的 integrate 产物齐全（`design_spec.json` / `tiling_strategy.json` / `data_flow.json`），
  唯独缺 docgen 子 skill 的 `<op>_详细设计说明书.md`。

### 证据（transcript）

- 03 会话（最长一次 spawn）的 skill 调用只有 2 次：`ascendc-op-design-synthesize`（门面）
  + `ascendc-op-design-integrate`；之后 20+ 个 turn 全在 bash `jq`/`python` 探查 `tiling_results.json`。
- 03/04/05 三次 spawn 的最终自检总结里，产物清单均**无 md**——agent 主动收尾并声称
  「合成完成、全部自检通过」，非被强制终止。
- unique `tiling_results.json` 90KB（radix sort 双模板 T1-bitmap + T2-radix，跨模板统一
  22 字段 TilingData）。

### 根因（事实层）

- **非时间预算耗尽**（agent 是主动写 decision_log 收尾），是**长上下文稀释**：门面指令
  「按序 tail-call integrate → docgen」里，排在后面的 docgen 在执行 integrate 的过程中从
  agent 的任务认知里整体消失（连自检清单「md 已生成」这一项也一并丢失）。
- **复杂度触发**：unique 的 integrate 工作量爆炸（22 字段跨模板统一），上下文快速累积到
  触发稀释；grid/resize 单模板、integrate 几步收敛，上下文未达触发阈值，故不暴露。
