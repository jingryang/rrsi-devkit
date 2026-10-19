# F9: "read-only 空产出"被判定为合法，静默吞掉

## 现象

`_maybe_warn_silent_failure` 对 `turn_count>=1 且 stalled==0`（有 tool_use progress）的会话**不报警**（视为"合法 read-only"）。但 coder 读了 26-30 次文件（大量 tool_use progress）却零写盘，被当"合法 read-only"，既不报警也不引导——只在空跑结束时以 `empty_artifacts` status 暴露。

## 凭什么这么说（证据）

- `_maybe_warn_silent_failure`（`opencode_backend.py:908-942`）判据：`full.strip()` 空 + `turn_count>=1 且 stalled==0` → 直接 return（不报警）。
- moe_re_routing 的 coder-01/02/03：tools=read 26-30 次、bash 6-8 次、grep/skill，**writes=0**，最后 text 是"继续"。全程 tool_use progress 充足，无 warning。
- 三次都只在结束时以 `empty_artifacts` 暴露（events.jsonl action_complete result=empty_artifacts）。

## 影响

- "读了很多但就是不写"的空转是**最需要干预**的信号（模型在思考泥潭），却恰好被当作合法。
- silent-cut 检测（`_last_turn_actionable`）与 silent-failure 检测（`full_response 空`）都覆盖不到"有 tool_use 但无产物"的中间态。

## 根因定位

"有 tool_use progress"被当作"agent 在干活"的证据，但**tool_use progress ≠ 产出**。判定空转应看"是否有产物落地"（write/edit 到 wd），而非"是否有 tool_use"。
