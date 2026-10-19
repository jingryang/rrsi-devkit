# 产物落点误判的取证缺口 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 来源：`design-halt-diagnostics`（step 50）P4 修复（op_dir 只读消歧文案）落地后，用户追问该修复是否
> 只是降低概率、有没有确定性硬解法。核实代码现状后记录如下。

## P1 — `_missing_artifact_error` 只在 wd 内查找，查不到即报统一错误，不区分"没产出"与"产出到了别处"

`_locate_artifact`（`design_substages.py:76-116`）的 glob 搜索范围严格限定在当前 stage 的
`working_dir`（wd）内；一旦目标文件名在 wd 内找不到，`_missing_artifact_error`
（`design_substages.py:613-627`）立即产出统一的"产物未在正确目录找到"文案，不会去检查该文件是否
其实存在于 `state.op_dir`（`op_dir` 在同一作用域内已可取，`design_substages.py:323,336-343` 已在用）
或其他位置。也就是说，"agent 根本没写文件"和"agent 把文件写到了 op_dir"这两种截然不同的失败原因，
目前在系统里产生完全相同的错误信号，无法区分。

## P2 — step 50 P4 的现有修复（prompt 文案消歧）不提供确定性保证，仍依赖 agent 对提示词的服从度

`_operator_section`/`_output_boundary` 的 op_dir 只读说明是纯文本提示，agent 是否遵守取决于其对
prompt 的理解与执行，框架侧无法验证也无法拦截。若 agent 仍误写到 op_dir，系统目前除 P1 所述的统一
错误文案外没有其他信号。

## P3 — SDK backend 已经在采集每轮 agent 调用的完整 tool_use 参数（含 Write/Edit 的 `file_path`），
## 但这份数据当前未被任何产物定位/校验逻辑消费

`sdk_backend.py:17-43`（`_serialize_block`）对每个 `tool_use` content block 原样记录
`{"tool_name": block.name, "tool_input": block.input}`（Write/Edit 的 `input` 含 `file_path`），
`sdk_backend.py:667-682` 把每轮消息流（含 tool_use/tool_result）逐条落盘到
`<run>/agents/<agent>-<seq>.jsonl`（原用途是给 `show` 命令做会话回放）。这个 transcript 文件路径
通过 `AgentResult.transcript: Path | None`（`backend.py:21`）已经原样返回给调用方——`design_substages.py`
里 spawn agent 的 stage 在拿到 `AgentResult` 后，手上已经有这一轮全部 Write/Edit 调用参数的完整记录，
只是当前代码里没有任何地方读取它来做产物定位校验。

## P4 — 通过 Bash 工具（`cp`/`mv`）而非 Write/Edit 写文件时，transcript 里没有结构化的目标路径字段

transcript 中 Bash 调用的 `tool_input` 是 `{"command": "<shell 命令字符串>"}`，不像 Write/Edit 那样有
独立的 `file_path` 字段；若要从 Bash 调用推断实际写入路径，需要对命令字符串做模式解析，覆盖面天然
弱于 Write/Edit 的结构化参数读取。

## 状态

P1-P4 已解决/已收口。方案见 `02-analysis.md`（含"决策 3 修订"）、实施见 `03-impl.md`。
`_harvest_relocation_evidence` 消费 P3 记录的 transcript 数据（Write/Edit 结构化读取，P4 范围内
Bash 命令解析未覆盖，符合决策 4 的 best-effort 定位）；`_missing_artifact_error` 分流有证据/无证据
两条消息（P1/P2）；`State.pending_relocation` + `_DesignSubstage.actions()` 门禁复用既有
`on_decision` 策略（`runner._execute_ask_user_question`），不新增打断机制。UT 见
`tests/ut/orchestration/test_design_substages.py`（`TestHarvestRelocationEvidence`/
`TestMissingArtifactErrorEvidence`/`TestRelocationGate`/`TestReadDiskArtifactsDecisionFallthrough`/
`TestTilingSegmentPendingRelocationCleared`），148/148 通过。
