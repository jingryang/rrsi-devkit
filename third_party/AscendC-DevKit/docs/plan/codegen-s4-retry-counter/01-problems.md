# s4 子阶段重试计数缺失 — 问题/需求记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：真实 run `20260831-223250`（log_softmax / A5 Regbase）会话 DB + meta.json
> + 代码实证；用户需求陈述（2026-09-01）。

## 观察事实

- `log_softmax` run 的 4.C.6 子阶段连续返回 `FAILED(error_type=CK)` **32 次**
  （01:19→02:26），每次 dispatch 都判定「未超限 → retry_s4」；直到 stage 硬迭代上限
  (40) 才 halt。
- 期间 `meta.json` 的 `retries.stage4_selfcheck.used` 恒为 0（`updated_at` 停留在
  4.C.6 开始前的 23:59:05），一次都没被递增。
- 全仓只有 `codegen.py:_handle_regbase_failure` 写重试计数器（`_update_meta_retries`），
  且它只在 **s2/s5** 阶段失败时被调用（codegen.py:3604/3620/3871/4040/4082/4113）；
  **s4 串行 FAILED 路径**（`_transition_regbase_s4` → `dispatch` → `retry_s4`）与
  **并行 VF transition**（`_transition_regbase_s4_parallel`）都不递增任何计数器。
- `codegen_s4.py:check_retry_exceeded` 只**读** `meta.json` 的 `used`，从不写；
  因此 `stage4_selfcheck` / `vf_test` / `stage5_compile` / `stage3_ambiguity`
  在 s4 相关路径上永远不会触顶。
- 文档语义（`ascendc-op-dev-coding-regbase/references/error-handling.md` §6）：
  「每次 SubAgent 返回 status=FAILED 时，编排层按错误类型递增对应 per-type 计数器
  （meta.json retries），未超限则重试；计数器耗尽后按类别确定性升级」。

## 需求（用户陈述）

- s4 每个 subagent 阶段（s4-coding 串行 / vf-test-agent 并行）返回 FAILED 时，
  重试要按**子阶段（sub_stage）**计数：每个子阶段的失败只消耗自己的预算，
  不消耗其他子阶段的预算；使「同一子阶段 4 次自检失败 → 回退 s2」「同一 VF
  步骤 2 次失败 → 标 exhausted」等升级门真正生效，不再无限重试到迭代上限。
- 全局共享计数不满足：并行批内两个 VF 同时失败会互相吃掉 `vf_test` 预算
  （先处理的成员耗尽后，同批另一成员被立即标 exhausted），且不同 VF/编码子
  阶段的偶发失败会累计误触发回退。

## 边界

- 不改变 ENV 恒 pause / DSG 恒回退 / 未注册错误类型的既有语义（不为此新增计数类别）。
- 不改变 s2/s5 已有的 `_handle_regbase_failure` 计数通路（阶段级，非 substage）。
- 计数递增发生在编排层（与 error-handling.md §6 文档一致），不是让 agent 自增。

