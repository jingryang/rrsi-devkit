# s4 子阶段重试计数 — 方案分析（L3）

> 对应 L1 `01-problems.md`。状态：已拍板冻结（用户决策，2026-09-01）。

## 问题本质

error-handling.md §6 要求「每次 SubAgent FAILED 时编排层递增 per-type 计数器」，但
编排层只有 `_handle_regbase_failure`（s2/s5）写计数器；s4 的两条失败路径（串行
`dispatch`、并行 VF transition）只**读** `check_retry_exceeded` 而不写 → 计数恒 0
→ 升级门永不触发 → 无限重试直到 stage 迭代上限（40）→ halt。log_softmax 4.C.6
32× 是实证。

## 计数维度：全局 per-type vs per-substage

| 维度 | 描述 | 问题 |
|------|------|------|
| 全局 per-type | 全 s4 共享同一 `meta.json retries.<type>.used` | ① 并行批两 VF 同时失败互相吃预算，先处理者耗尽后同批另一成员被立即 exhausted；② 不同子阶段各自偶发失败会累计误触发「设计有问题→回退 s2」；③ 单个持续失败子阶段（如 4.C.6）与多个偶发失败子阶段无法区分 |
| **per-substage（选）** | 每个 sub_stage 自己的失败计数 | 各子阶段预算隔离；持续失败的子阶段自己触顶；偶发自愈的子阶段不连累他人；并行 VF 各步骤独立预算 |

## 决策（用户拍板，2026-09-01）

- **per-substage 计数**：s4 每个子阶段的失败重试计数独立。
- 存储：`orchestration_plan.json` 的每个 sub_stage 条目带 `retry_count`（运行时由
  编排层维护，与 `status` 同位；s2 agent 不产出，首次 bump 懒初始化）。
- limit 仍按错误类型取 `RETRY_COUNTER_LIMITS`（CK→selfcheck 4、CK-VF→vf_test 2、
  C-SYM 族→compile 6、AMB→ambiguity 3）；`used` 是该子阶段的 `retry_count`。
- 子阶段标记 done 时清零 `retry_count`（按尝试窗口计，成功后再进入的失败重新计数）。
- s2/s5 保持阶段级计数（`_handle_regbase_failure` + meta.json retries，非 substage
  语义；s2/s5 各是一次性阶段，天然等价 per-unit）。

## 计数语义（拍板）

- **共享映射单点**：错误类型 → (计数器键, label) 的映射提取为 `_retry_key_label`，
  `check_retry_exceeded`（读）与 `bump_retry_counter`（写）共用（§1.15 防漂移）。
- **递增时机**：`dispatch` FAILED 分支在 `commit_or_pause` 校验通过后、
  `check_retry_exceeded` 之前递增**失败子阶段**（`failed_sub_stage or current`）；
  并行 VF transition 对每个 FAILED 成员递增**该成员子阶段**。
- **不计数类别**：ENV 恒 pause / DSG 恒回退 / 未注册类型维持「allow retry」，
  均不递增（§7 契约要求 agent 使用注册错误码；未注册属契约违规，另案）。

## 升级行为（修复后，per-substage）

- 同一编码子阶段自检/编码连续失败 4 次（CK 族）→ 该子阶段 retry_count=4 →
  `rollback_s4` 回退 s2。
- 同一 VF 步骤连续失败 2 次（CK-VF）→ 该 VF retry_count=2 → 标 `exhausted`（⚠️ 继续）。
- 同一子阶段编译（C-SYM 族 6）/ 歧义（AMB 3）同理。
- 各子阶段互不消耗预算。
