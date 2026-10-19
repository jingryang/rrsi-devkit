# L3 方案分析 — eval 报告发现路径修复（方向已拍板）

- 拍板时间：2026-08-28，用户拍板
- 输入：`01-problems.md`（L1 事实）

## 候选方案

### 方案 a — 发现路径对齐产出位置（✅ 拍板方向）

`_parse_report` 优先在 `_eval_partial_path`（即传给 kernel_eval 的 `--output`
目录）内 glob `*_eval_*.json`（mtime 取最新）；未传 `--output`（ws 不可用，
单测场景）或该目录无报告时，回退现行 `repo_root/reports/` glob。

- 优点：scorer 在**自己指定**的位置找报告，语义自洽；保留 step-91/92 的
  超时 partial 归档能力；回退路径覆盖旧场景，行为无空洞。
- 附带整改：`_discovery_broken_error` 的"likely crashed / operators=[]"是
  猜测文案——修复后该文案仅在两处均找不到报告时出现，且不应把猜测写成
  事实断言（§1.10 错误不冒充的精神：找不到报告是事实，崩溃是推测，两者
  分行表述）。

### 方案 b — 不再传 `--output`，报告回落 worktree reports/（否决）

- 否决：放弃 step-91/92 超时归档能力（超时墙下 partial 报告又回随机考古）；
  且汇总 json 落 worktree `reports/` 污染干净检出的算子仓工作区。

### 方案 c — 从 kernel_eval stdout 解析报告路径（否决）

- 否决：对输出格式脆弱耦合；报告位置本就由 scorer 指定，无需向 stdout 考古。

## 实施注意（给 L4）

- 发现顺序：`--output` 目录 glob → `repo_root/reports/` glob → 都空才走
  infra 误判（文案整改同上）。
- TDD fixture：用本批真实报告做样例（`unique_eval_20260828_054218.json`
  断言 overall_score≈50.01 / 20/20；`moererouting_eval_20260828_003615.json`
  断言 68.52）——真实产物进 fixture，合成结构对齐 schema 即可。
- 回归守护：`--output` 目录有报告时**不得**回落 reports/ glob（防顺序倒置）。
- 本批分数恢复：修复后不需要重跑评测——报告已在 ws（unique 50.01 /
  moe 68.52），批记录可据实更正。

## 关联

- step-91/92（`--output` 引入点——超时分支改了、正常分支漏改的回归源）、
  step-101（同批另一问题）、§1.10（猜测不得冒充事实）。
