# F11: silent-cut 不消耗 iteration 计数，日志读数误导

## 现象

silent-cut（thinking-only terminal，无产物）的迭代**不消耗 iteration 预算**（`_iteration` 不递增），只递增 `cut_streak`。导致 run.log 里 `iteration 1/10` 从不变化，实际却已重试多次。**日志上看起来"只尝试了一次、预算还剩 9 次"，实际已连续失败 2 次、进行到第 3 次。**

## 凭什么这么说（证据）

d8d4d9 requirement 的 run.log：
```
18:33:50  iteration 1/10  spawn serve:36889
18:39:46  WARN silent-cut (cut_streak=1/5)
18:39:46  iteration 1/10  ← 还是 1/10！不是 2/10
18:39:46  spawn serve:47217 (resume)
18:46:05  WARN silent-cut (cut_streak=2/5)
18:46:05  iteration 1/10  ← 还是 1/10
18:46:05  spawn serve:50779 (resume)
18:50:30  ✗ requirement done [failed]
```

三次 spawn 全部显示 `iteration 1/10`。代码：`runner.py:495-505`（cut 分支 `_iteration` 不递增，只 `_cut_streak += 1`）。

## 影响

- **读数误导**：`iteration 1/10` 让看日志的人以为"预算还剩 9 次就放弃了"，实际是"连续 cut 多次后失败"。
- `cut_streak=2/5` 才是真实失败计数，但它和 `iteration 1/10` 并排出现却无关联说明。
- 两套计数（生产迭代 vs cut 连续失败）语义不同，日志无解释。

## 根因定位

cut 会计与 iteration 会计是两套独立计数（这是**刻意设计**：cut 不烧预算、cut_streak 单独兜底）。但**日志展示没有把两套计数并置解释**，导致读数误导。

## 补充

用户指出：同一 session resume 符合预期，只要 resume 有界、日志准确。本问题**不是"重试没日志"**——重试（cut_streak、agent_resume、silent-cut）都有日志。问题是 **iteration 计数不反映真实重试消耗**，读数上"看不出在重试"。这是日志/计数展示问题，不是日志缺失。
