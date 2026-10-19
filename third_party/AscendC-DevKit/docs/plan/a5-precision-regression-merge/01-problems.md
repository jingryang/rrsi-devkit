# L1 问题/需求记录 — A5 精度调试流程：删除 regression 阶段并合入 kernel_debug

## 需求（客观事实，不含方案）

- 用户需求：去除 A5 precision_debug 的独立 **regression** 阶段，将其核心功能
  （修复后批跑全量 KernelLaunch 验证）合入 **kernel_debug** 阶段。
- 用户需求：kernel_debug 解决完当前 case 的精度问题后，就地做一次全部 case 的
  精度测试（批跑 KernelLaunch）；KL 结果写入 JSON，Python 编排层读取该 JSON
  刷新 `failed_case_queue`（resolved / regressed / 追加 pending / index 推进）。
- 当前现状（改动前事实）：
  - 流程为 6 阶段：`baseline → kernel_debug → vf_test / vector_error_debug /
    op_plugin_debug → regression`。
  - `regression` 只跑全量 KernelLaunch（不跑 run-cases），输出 `regression_status`
    （`kl_all_pass` / `case_kl_fails`），框架 transition 读 KL summary JSON
    （`result_{op_name}_summary.json`）调和失败队列。
  - `kernel_debug` 修完当前 case 后只回验当前 case，不跑全量。

## 改动后目标形态（验收判据）

- `regression` 阶段（Python 类 / skill / agent / transition table 条目）全部删除。
- `kernel_debug` 在 `debug_status=fixed` 时批跑全量 KernelLaunch，把 KL 结果写入
  JSON（脚本自动 dump `result_{op_name}_summary.json` + agent 结果 JSON 的
  `kl_result` 字段）。
- 编排层 transition 读取 KL JSON 调和失败队列，并推导路由：
  - KL 全过 → `kl_all_pass` → baseline 权威双跑验收；
  - KL 有失败 → `case_kl_fails` → kernel_debug 修下一个失败 case；
  - VECTOR_ERROR → `vector_error` → vector_error_debug。
- 失败队列的 resolved / regressed / 追加 / index 推进由框架从 KL 实测推导
  （§1.13 权威，不复用 agent 手工失败清单）。

## 事实（改动前的代码位置）

- `src/ascendc_devkit/orchestration/stages/precision_debug_a5/regression.py` — regression 阶段实现。
- `.claude/skills/ascendc-precision-regression/SKILL.md`、`.claude/agents/ascendc-precision-regression.md` — regression skill / agent。
- `src/.../precision_debug_a5/transition_table.py` — `regression` 阶段路由条目。
- `resources/orchestration-config.json` — `regression` → skill 映射与 tail_call。
- `src/.../precision_debug_a5/kernel_debug.py` — per-case 调试阶段（合入目标）。
