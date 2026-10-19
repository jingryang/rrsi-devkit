# F3: 非交互 batch 下 pending_relocation 自动选 KEEP（不搬回）

## 现象

检测到孤儿产物后，框架在 `actions()` 里返回 MOVE/KEEP 询问（`design_substages.py:292-301`），`default_index=0` = **KEEP（不搬）**。非交互 batch（on_decision=default）下 runner 自动选 `default_index`（`runner.py:1066-1072`）→ 选 KEEP。**框架明知文件在 `actual_path`，却选择不搬回，把修复完全寄托于 LLM 自觉。**

## 凭什么这么说（证据）

- `design_substages.py:292-301`：`AskUserQuestion(question="检测到 {filename} 被写入了 {actual_path}，而不是工作目录 {wd}。是否搬回工作目录并继续？", options=[KEEP, MOVE], default_index=0)`
- `runner.py:1066-1072`：非交互（on_decision=default）`idx = action.default_index` → 选 `options[0]` = KEEP。
- rms_norm 5 次迭代全走这条路径：每次检测到孤儿产物 → 询问 → 自动 KEEP → 重 spawn agent（带纠正提示）→ agent 仍写孤儿 → 循环直到预算耗尽。

## 影响

batch 场景下，**"自动搬回"这个确定性修复从不执行**。MOVE 需要用户交互（AskUserQuestion 被触发且被选 MOVE）才发生，而非交互批跑里这是死路。

## 根因定位

`pending_relocation` 的 MOVE 是**用户决策驱动**的，没有"非交互下自动 MOVE"的确定性路径。框架把"搬回"设计成需要人确认的选项，但批跑恰恰无人确认。

## 补充

`default_index=0` 选 KEEP 是刻意的"安全项"（避免误搬）。但框架此时**已有 transcript 证据证明 `actual_path` 是 agent 本次写的**，搬回是构造性修复，不是猜测——安全顾虑可以通过"仅搬 transcript 证据明确的文件"来消除，而非一刀切不搬。
