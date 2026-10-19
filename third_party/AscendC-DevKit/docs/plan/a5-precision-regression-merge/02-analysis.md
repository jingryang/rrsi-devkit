# L3 方案分析 — regression 合入 kernel_debug

## 选项

- **选项 A：保持独立 regression 阶段**。现状，不改。缺点：修复后多一次独立的
  agent spawn / 编译 / 全量 KL 循环，耗时且多一轮 prompt 上下文切换；两个阶段
  共享同一职责（跑全量 KL），属于 §2.5「同一职责两条通路」的违规倾向。
- **选项 B（选定）：删除 regression 阶段，合入 kernel_debug**。kernel_debug 在
  `fixed` 后就地批跑全量 KernelLaunch；框架 transition 读 KL summary JSON 调和
  队列 + 推导路由。符合用户需求（解决完当前 case 后做全量精度测试）。

## 选定理由（四把尺子）

- **可维护**：唯一通路（§2.5）——「跑全量 KL 验证修复」只存在于 kernel_debug，
  无新旧并存；`kl_all_pass` / `case_kl_fails` / `vector_error` 三态由框架从
  KL summary（`per_case` 全量，§1.13 权威）推导，agent 无需、也不得上报 per-case
  状态，队列调和逻辑与 baseline 同构，复用同一批 case_loop helpers。
- **可扩展**：新增失败 case 由 `_apply_kl_failures_to_queue` 自动追加 pending、
  已 resolved 的 case 重新失败自动 regressed——不依赖任何具体 case/算子名
  （§1.12），对同类新算子自动归位。
- **可诊断**：`fixed` 后无 KL summary（agent 未批跑）→ warn 留痕并保守路由
  `case_kl_fails`（不直通 baseline）；VECTOR_ERROR 时不用过期 summary 调和队列
  （交 vector_error_debug）；agent 报的 `new_failed_cases` 与 KL 实测不一致 → 留痕。
- **架构合理**：职责落在「修 kernel 的阶段」内闭环（§2.9 构造性保证优先），
  不再由独立验证阶段跨阶段兜底；best_snapshot 晋升只在提供全量 `kl_result` 时
  发生（per-case `precision_result` 不代表全量高水位）。

## 冻结决策

1. 删除 `regression` 阶段：Python 类 / skill / agent / transition table / 配置映射。
2. `kernel_debug` 的 `fixed` 后：
   - 批跑全量 KernelLaunch（复用 baseline 脚本），不跑 run-cases；
   - KL 脚本 dump `result_{op_name}_summary.json`（per_case 全量），agent 结果 JSON
     写 `kl_result` 汇总；
   - 框架 transition 读 summary 调和失败队列 + 推导 `_kl_status`
     （`kl_all_pass` / `case_kl_fails` / `vector_error`）；
   - best_snapshot 晋升仅在存在全量 `kl_result` 时进行。
3. `resolve_condition`：`debug_status=fixed` → 返回框架推导的 `_kl_status`；
   `_kl_status` 缺失（KL 实测未知）→ 保守 `case_kl_fails`（不直通 baseline）。
4. transition table：kernel_debug 移除 `fixed→regression`，改为
   `kl_all_pass→baseline(validation)`、`case_kl_fails→kernel_debug(corrective)`；
   `vector_error` 沿用。

## 否决

- 选项 A（保持独立阶段）——用户明确要求合并，且合并符合 §2.5 唯一通路。
- 保留 regression 别名/兼容层（`FinalizeSubstage` 等）——§1.4 不考虑向后兼容。
