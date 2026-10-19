# P64 codegen A5 侧：消费 design 态 vf_design 的修改方案（转交 A5 codegen 负责人决策）

> 本文档由 **design 侧**（vf-design 移植）产出，记录 A5 codegen 消费侧的修改方案，
> 供 **A5 codegen 负责人**自决是否/如何实施。design 侧不越权改 A5 codegen——
> 曾越界改的两处已回退（commit d19bdb33），方案记录于此供参考。

## 背景（P64）

P64：A5 Regbase 的 **VF 函数设计在详设阶段原不存在**，VF 拆分被 codegen 的
`s2-analysis` 子代理**临场发明**（`.VT.{M}` 步骤的 VF 划分在 codegen 期现推），
与上游设计脱节——codegen 期的 VF 拆分无设计态依据，可能与 Buffer/Kernel 设计矛盾。

**design 侧已闭环**（vf-design 移植：commit `08d5ca22` + 后续收口 `c1e222d8`/`9b158300`/`2e110ae7`）：
- 新增详设 stage `TilingVfDesignStage`（A5 门控、A2/A3 自跳过），流水线位置
  `split → vf-design → buffer-kernel → precision-perf`。
- 产物 `tiling_vf_design.json`（schema 权威源：`ascendc-op-tiling-vf-design`）。
- `buffer-kernel`（design 侧）已消费 `vf_design`，Compute 伪码用 `VF_CALL` 表达。
- 真链路已验：`tests/st/test_vfdesign_tui_selfclosure`（A5 RmsNorm，9min20s，PASS）。

**codegen A5 侧仍是 P64 的缺口**：`s2-analysis` 的 `.VT.{M}` 生成仍临场发明 VF，
未消费 design 态 `vf_design`。是否消费、如何消费，**由 A5 codegen 负责人决策**。

## 交接契约：staging `tiling_results.json` 的 `vf_design` 段

`CodegenStage._prepare_staging` 已物化 `tiling_results.json`（design 态产物），
A5 模板下含 `vf_design` 段。形状（权威源：
`.claude/skills/ascendc-op-tiling-vf-design/schema/tiling_vf_design.json`）：

```json
{"<模板名>": {
  "split": {...},
  "vf_design": {
    "pattern": 4, "pattern_name": "...", "vf_count": 3,
    "has_dependency": true, "loop_count": 1, "rationale": "...",
    "data_flow": "copy_in → vf_0 → vf_1 → vf_2 → copy_out",
    "vfs": [
      {"name": "ComputeXxx",
       "function_signature": "__aicore__ inline void ComputeXxx(LocalTensor<half>& ...)",
       "interface_params": {"inputs": [...], "outputs": [...]},
       "inputs": [{"name":"x","from":"copy_in_x"}], "outputs": [...],
       "compute_ops": [...], "pseudocode": "..."}
    ]
  },
  "buffer_kernel": {...}, "precision_perf": {...}
}}
```

**供 codegen 消费的关键字段**：
- `vfs[].name` → `.VT.{M}` 标题函数名
- `vfs[].function_signature` / `interface_params` / `inputs` / `outputs` → VF 接口规格（dtype/UB shape）
- `vfs[].compute_ops` → 计算语义
- `data_flow` → VF 依赖顺序 → `.VT.{M}` 的 M 编号顺序

## 曾被 design 侧越界改动、现已回退的方案（供 A5 负责人参考）

commit `08d5ca22` 曾改了两处 A5 codegen（**未确认权责**），现已回退（`d19bdb33`），
方案记录于此供参考（非强加，A5 侧可自由采用/改写/拒绝）：

1. **`ascendc-dev-s2-analysis.md` §2.4.0「VF 精度预验证步骤生成（仅 A5 Regbase）」**：
   - step 1-2 由「识别 VF 需求 / 拆分 VF 函数（临场发明）」→「读取 design 态
     `vf_design` / 映射为 `.VT.{M}` 规格（消费，不重新拆分）」。
   - 跳过条件由「设计文档未给 dtype/shape」→「staging 无 `vf_design` 段 →
     `clarification` 标注缺失，**不得自行发明** VF 拆分」。
   - 加了「VF 拆分来源（P64 闭环）」说明段。
2. **`ascendc-coder-regbase.md`**：加「照蓝图实现、禁重推导，`tiling_results.json`
   是实现蓝图主源（含 VF 函数规格）」Coding Rules 条目。

> 这两处的完整 diff 可 `git show 08d5ca22 -- .claude/agents/ascendc-dev-s2-analysis.md
> .claude/agents/ascendc-coder-regbase.md` 取得。

## 待 A5 codegen 负责人决策

- 是否让 `s2-analysis` 消费 design 态 `vf_design`（消解 P64 codegen 半）？
- 若消费：`.VT.{M}` 映射规则、无 `vf_design` 时的回退策略、coder-regbase 是否
  加蓝图约束——均由 A5 侧定。
- **design 侧承诺**：`vf_design` 段形状稳定（schema 权威源），如 A5 侧消费需要
  字段调整，提需求给 design 侧（不改 A5 codegen）。

## 关联

- P64（`docs/plan/self-evolution/06-problems.md`）：vf-design/vf-test gap。
- design 侧闭环凭证：commit `08d5ca22` / `2e110ae7`；`test_vfdesign_tui_selfclosure`（PASS）。
- 回退凭证：commit `d19bdb33`。
