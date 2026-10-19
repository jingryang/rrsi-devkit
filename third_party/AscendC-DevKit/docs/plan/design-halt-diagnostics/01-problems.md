# 详设阶段假性 halt 与终止诊断信息缺失 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：`h00616010` 机上一次 `ascendc-devkit run` 的真实执行记录（run-id `20260714-170137-ba8b74`，
> 已拷贝到本仓 `output/` 下只读分析，不在本仓复现执行）。运行在 `integrate` 阶段假性 halt，
> `report.md`/`report.json` 全部 stage 显示 `unknown`，终止时的控制台 ERROR 文案与实际原因不符。

## P1 — 设计子阶段成功产出后未清 `last_error`，导致 stale 错误把成功迭代误判为失败

`_DesignSubstage` 的基础成功路径 `_parse_single` 会在成功时清空 `last_error`（既有约定，代码注释
「P5: 清除 sticky error」）。但以下三个 stage 各自重写了 `transition()`、直接调用
`_read_disk_artifacts` 组装 `state.with_updates(...)`，**成功路径都没有带上 `last_error=None`**：

- `IntegrateStage.transition`
- `DetailedDesignIntakeStage.transition`
- `ValidateStage.transition`

对照组：同样自定义 `transition` 的 `AnchorPerTemplateStage`、`DocgenStage`、`_TilingSegmentStage`
均在成功路径手动补了 `last_error=None`，说明这是一条「记得清」的隐性约定，已经独立漏掉三次。

**证据**：runner 的 halt 判定只看 `own_error = last_error if last_error.stage_name == stage.name`，
不检查 contract 是否满足；只要 `last_error.stage_name` 命中当前 stage 就判 `stage_status="failed"`，
叠加 `fail_strategy="halt"` 即触发 `_stage_failed`。本次事故中 `integrate` 第 1 轮因产物落盘位置
错误产出过一次 `missing_artifact` 错误，第 2 轮修复后产物齐全、`state` 里
`design_spec`/`tiling_strategy`/`data_flow` 均已正确写入，但 `last_error` 仍是第 1 轮遗留的
`missing_artifact`，导致本该成功的第 2 轮仍被判 `failed` 并触发 halt。

**影响**：`integrate` 实际已产出全部约定产物，管线仍被当作失败终止，用户看到的 halt 与真实执行结果不符。

## P2 — `report.md` / `report.json` 全部 stage 显示 status `unknown`，无法用于事后复盘

**现象**：本次 run 的 `report.md`/`report.json` 中全部 13 个 stage 均为 `status: "unknown"`、
`iterations: 0`、`elapsed_ms: 0`，尽管运行实际推进过多数 stage。

**证据**：`Report._from_events` 按 `evt["stage"]` 字段名做字典 key，先由 `stage_enter` 建立
`StageSummary(name=name)`（默认 `status="unknown"`），再由 `stage_complete`/`stage_aborted`/
`stage_skipped` 按同一 key 回填状态。逐条核对本地 `events.jsonl`：`stage_enter` 事件的 `stage`
字段是裸 stage 名（如 `integrate`），而 `stage_complete`/`iteration_start`/`stage_aborted` 事件的
`stage` 字段是加了 scope 前缀的名字（如 `generate_ascendc/detailed-design/integrate/integrate`）。
两类事件的 key 从不相同，`Report._from_events` 的字典查找必然落空，回填逻辑对所有 stage 都不生效。

**影响**：`report.md`/`report.json` 作为事后复盘产物完全失去参考价值。

## P3 — 终止 ERROR 消息是为另一种 halt 场景写的固定文案，与本次实际触发原因/阶段不符

**现象**：本次 run 因 `integrate`（设计阶段，`fail_strategy=halt`）触发硬停，但控制台/日志最终打出的
`[ERROR] Workflow halted: ...` 文案描述的是「a stage exhausted its correction budget on an
unresolved build/precision failure」「review the latest verify output」——这段话是为 codegen/verify
耗尽纠正配额触发的 `__halt__` 场景写的，与 `integrate` 的实际情况（设计产物 schema/落盘问题）不符，
且文案完全不提具体是哪个 stage 触发了终止。

**证据**：halt 触发时刻，`graph_executor.py` 的 `fail_strategy=halt` 硬停分支确实先打印了一条准确的
WARN（点名 stage 与失败原因），但随即把 `_stage_failed` 清空为 `None`，这条准确信息没有被保存到任何
`State` 字段上；终止逻辑走到 `dispatcher.py` 只看 `state.is_terminal` 是否为真，对两种截然不同的
halt 触发路径（`fail_strategy=halt` 硬停 vs `__halt__` 纠正配额耗尽）输出同一段写死的通用文案。
全仓检索确认当前 `State` 上不存在任何记录「哪个 stage / 什么原因触发了本次 halt」的字段。

**影响**：终止消息误导事后排查方向——本次事故最初的 triage 就是被这段文案带偏，去找并不存在的
「build/precision failure」和「verify output」。

## P4 — 设计阶段首轮 prompt 未清楚区分「算子源目录（只读参考）」与「当前工作目录（唯一产出位置）」

**现象**：本次 run 的一次设计 agent spawn 在其首轮迭代中，把产物用绝对路径写去了外部算子源目录
（`op_dir` 指向的 cann-bench 仓内路径），而不是编排真正读取产物的当前工作目录（spawn 时的 cwd），
触发了 P1 中提到的第 1 轮 `missing_artifact`。

**证据**：`_operator_section` 在 prompt 里展示 `算子目录：{op_dir}`，未说明该目录是只读参考、不是产出
位置；`_output_boundary` 只警告「不要把上游产物复制到当前工作目录」，同样没有说明 `op_dir` 不可写。
框架侧已有的纠正手段（`_missing_artifact_error` 在报错时说明必须用相对路径写入 cwd）是事后补救，
首轮 prompt 本身缺少预防性说明。

**影响**：至少一次真实 spawn 因此在首轮就产生了可避免的 `missing_artifact` 错误，是 P1 触发链条的起点。

## P5 — entry/context 两阶段在本次 run 中各空转 5 轮无 agent_spawn（观察记录）

**现象**：日志显示 `entry`、`context` 两个 stage 在本次 run 的开局各自跑满 5 轮迭代、期间没有任何
`agent_spawn` 事件。

**证据**：`events.jsonl` 中 `entry`/`context` 对应的 `stage_iteration` 序列达到迭代上限，但同一时间窗口
内无 `agent_spawn` 记录。

**影响**：未观察到对本次 halt 有直接因果关系；记为独立观察项。

## P6 — 开局 WARN 提示 `repo_profile_name`/`target_repo` 等可选输入未提供（观察记录）

**现象**：日志开局阶段打印 WARN，提示 `repo_profile_name`/`target_repo` 等字段未提供。

**证据**：`run.log` 开局部分的 WARN 行。

**影响**：这些字段在本次 run 的 profile/CLI 输入中确实未传入，是可选输入缺省的正常提示，未观察到
对后续执行造成实质影响；记为独立观察项。
