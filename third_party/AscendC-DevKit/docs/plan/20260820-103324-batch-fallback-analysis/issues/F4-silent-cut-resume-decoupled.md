# F4: silent-cut 与 resume 计数脱节，cut-resume 循环不触发 fresh 重开

## 现象

silent-cut（thinking-only terminal，无产物）后，框架保留 sidecar 作 resume 句柄，下次 spawn 自动 resume **同一 session**。模型在旧上下文里重复 thinking，状态不重置。d8d4d9 requirement 连 resume 3 次同一 session（`ses_fe143e8b8ffe4HGZeTgUsCmfII`），每次 thinking 数万字符零落盘。

**而 silent-cut→resume→silent-cut 这种循环，`resume_fails` 计数不增长**（因为每次 resume 本身"成功"了，只是后续又 cut），永远不触发退化 fresh 重开。

## 凭什么这么说（证据）

- `opencode_backend.py:545-575`：`_resume_attempts`（resume 连续失败 N 次 → 退化 spawn）只统计 **resume 调用本身失败** 的次数（`_fails = int(_data.get("resume_fails", 0))`）。
- d8d4d9 run.log 18:39:53 / 18:46:12 两次 `agent_resume ... auto-resuming session ses_fe143e8b8...`，但**没有任何一次 resume 调用报失败**——每次都 resume 成功，只是 resume 后的 agent 又 silent-cut。
- 结果：`cut_streak`（runner.py:495-505，MAX_CUT_STREAK=5）在涨，`resume_fails` 不涨。两套计数互不感知。

## 影响

- 同一 session 反复 resume，模型在旧 thinking 泥潭里空转（单块 thinking 11 万字符）。
- 明明"连续多次无效 resume"应当 fresh 重开，却被两套独立计数漏掉。

## 根因定位

`cut_streak`（runner 层）与 `resume_fails`（backend 层）是两套独立计数。**"resume 后仍 cut"这个信号既不归入 cut_streak 的语义（它已计入），也不归入 resume_fails 的语义（resume 没失败）**——中间地带无人管辖。

## 补充

用户指出"同一 session resume 符合预期，只要 resume 有界"——正确。问题不在 resume 本身，而在**"resume 后仍无产出的连续 cut"没有进入任何有界计数**，导致 fresh 重开机制永远不触发。
