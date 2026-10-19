# F6: stage_complete status 与最终 state 脱节（成功却记 failed）

## 现象

d8d4d9 的 requirement 阶段**实际成功**（最终 `requirement_clarified=True`、`requirement` 为完整 dict），但 events.jsonl 记 `stage_complete status=failed`。

## 凭什么这么说（证据）

- `state_snapshot.json`（d8d4d9）：`requirement_clarified: True`、`requirement: dict[op_spec, design_doc_path, constraints, test_cases, reference_op, unclear_items]`、`unclear_items: []`、`last_error: None`。
- `events.jsonl`：`stage_complete self_evolve_op/requirement/requirement ... status: failed`。
- 时序：第 3 次 spawn（18:50:30.736）后 agent silent-cut，但产物写盘发生在 18:50:14（第 2 次 resume 会话延续）——状态已满足契约，stage 却按最后一次 empty_artifacts 判 failed。

## 影响

- events 记录不诚实：成功被记为失败。
- 依赖 events/report 判断 run 成败的自动化会被误导（memory `batch-status-provenance-events-jsonl`：events.jsonl 是判成败权威源）。

## 根因定位

**（2026-08-21 复核修正，原文存档于文末）**真根因不是 runner 只看最后一次
agent_status——批次时点 `empty_artifacts` 本就在 runner 白名单内，branch 1 不会
翻 failed。实际路径：run.log 末尾的 `→ schema_violation: ...` 是 runner
**own_error 分支（branch 2）**的确定性输出；round 2 报 schema_violation（该轮
artifacts dict 缺 requirement.json），round 3 解析成功（快照
requirement_clarified=True 佐证；用批次时点契约解析该 run 的 requirement.json
本地复现 errors=[]），但 **requirement 成功 return 不清 last_error**——旧错误
粘滞到 stage 末，被 branch 2 如实渲染成 failed。

深层原因：**"stage 成功清 own last_error"是散落在各 stage 的手工纪律**
（design×2 / test_design×2 / codegen×4 手写了 `last_error=None`，requirement
漏写）——缺统一抽象（CLAUDE.md §1.15）。修复方案见 08-impl。

> 原文（归因有误，存档）：`runner.py:567-570` 的 stage_status 判定只看**最后一次** agent_status（empty_artifacts → 判 failed），不看**最终 state 是否满足 output_contract**。契约满足的 stage 被最后一次空转的 agent 拖累误判。

## 补充

`fail_strategy=continue` 让 failed 后仍继续下游（这是设计行为），但 status 记录本身错了。~~修复方向：stage_status 判定应优先看最终 state 是否满足契约（满足即 ok），agent_status 只作补充证据。~~（该方向已否决：让判定无视残留错误 = 状态与结论分裂、错误被吞；正确修法是统一归一化——已交付即错误已解，从状态中清除，详见 08-impl。）
