# step-62 — claims schema 收口 + checkpoint_convention 清理 — 实施方案（第四层）

> L3 见 `62-claims-closure-analysis.md`；L1 见 `06-problems.md` P85。

## 1. tiling 三段 schema 收口 verifiable_claims

- `tiling_split.json` / `tiling_buffer_kernel.json` / `tiling_precision_perf.json`：
  - `required_keys` 加 `verifiable_claims`。
  - `example` 加 `"verifiable_claims": []`（elementwise 无断言范例）。
  - `description` 加 verifiable_claims 语义说明（各段 claim_type + 指向 checkpoint_convention.md 字段定义 + anchor/validate 消费）。
- 各段 claim_type 语义：split=`numeric_derivation`（分核/ubFactor 推导）、buffer_kernel=`hardware_api_capability`（gather/scatter/reduce 骨架级 API）、precision_perf=`api_checked`（硬件常量）/`derived`（性能瓶颈）。

## 2. checkpoint_convention.md 清理

- 删 §manifest.json（planner 生成）段。
- 删 §general-design.json 所有权段。
- §目录结构删 manifest.json 行。
- 顶部加范围说明（manifest/planner 废弃，工程层走 stage contract）。
- 保留字段定义/查证规则段 + 单步格式段（被引用）。

## 3. 不改

- anchor/validate 核对规则（修B 已写，schema 收口后有 claims 可核）。
- tiling segment transition（不强制 errors，宽容 + anchor AC0 兜底）。
- ArtifactSchema（不扩展 verifiable_claims issue 级校验）。

## 4. 验证

- 全量 UT 2318 passed/7 skip 零回归。
- heavy_llm 已验证（`tests/st/test_design_claims_anchor_selfclosure.py`，gather 算子，3 测试共 ~10.5 分钟）：
  - **A 产出端**：spawn `tiling-buffer-kernel` 按 schema `required_keys`（含 verifiable_claims）产非空 claims（带 verification）— 6:06。
  - **B1 不误阻断**：anchor 对一致 claim（用 Gather 指令, api_checked）clean 通过（passed + skeleton_api_verdict 非 N/A）— 1:54。
  - **B2 对质阻断**：anchor 对矛盾 claim（"不用 Gather、A5 无 Gather"）触发 AC2（Grep ascendc-dev-knowledge 发现 Gather 是标准 SIMD 离散与聚合指令）— 2:14。
  - 三测试完整覆盖 P85（产出 + 消费两端 + 行为区间 [一致→passed, 矛盾→阻断]）。
