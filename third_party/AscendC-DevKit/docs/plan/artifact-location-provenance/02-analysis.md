# 产物落点误判的取证缺口 — 方案分析（L3）

> 选项 / 选择 / 理由。决策拍板后冻结。问题事实见 `01-problems.md`。

## 决策 1（P1/P2）— 产物误落点检测机制：三个选项 → **选"从 SDK transcript 回收实际 tool_use 调用参数"**

- **选项 A：`_missing_artifact_error` 增加 op_dir 存在性检查**（wd 查不到时，再查一次 op_dir 是否有
  同名文件）。**否决**：单纯"存在"这个信号无法证明该文件是这一轮写的——op_dir 是外部已有算子源码
  目录，可能本来就有同名文件（撞名）；同一 stage 可能已经因同一 bug 重试过多轮，可能是更早失败迭代
  留下的残留；op_dir 若是共享 checkout，也不能排除是其他进程/人员放的。据一个无法证明归属的信号做出
  "自动挪回 wd" 这类强动作，误判代价（悄悄用错误/过期内容顶替本轮真实产出）比现状的"报统一错误"更
  严重——用不可靠证据做强动作，属于反面案例。
- **选项 B：agent 在结构化输出里自报"我把文件写到了哪个绝对路径"**。**否决**：这仍然是让 agent
  输出一段文本、由 Python 侧信任它，本质上还是 prompt-compliance 的变种，没有解决 P2 记录的"依赖
  agent 服从度"这个根本问题——agent 完全可能写对了但汇报错（记错/幻觉/沿用上一轮路径），且新增了
  "写入路径与汇报路径不一致时该信谁"这个新的失配点，不比现状更可靠。
- **选项 C：从 P3 已确认存在的 SDK transcript（`AgentResult.transcript`）里解析这一轮实际发生过的
  `tool_use` 调用，取 Write/Edit 的 `file_path` 参数**。**选中**。理由（四把尺子）：
  - **可诊断**：这是调用发生时就固定下来的记录，不是事后推测或事后询问，天然带轮次归属——不存在
    选项 A 的"旧文件/撞名/他方误放"归因难题，因为读的不是"现状扫描"而是"这一轮真实发生过什么"。
  - **可维护**：数据源已经存在（`sdk_backend.py` 采集、`AgentResult.transcript` 已暴露），新增的只是
    一个纯读取端的解析/校验逻辑，不需要改 SDK backend 层，不引入新的采集机制。
  - **可扩展**：这套解析逻辑天然覆盖"任何 Write/Edit 调用落在预期 wd 之外"的场景，不止 op_dir 一种，
    未来出现新的路径混淆源不需要再补一个专门的探测分支。
  - **架构合理**：读取权责放在产物校验发生的地方（design_substages 的产物定位逻辑），消费的是 SDK
    backend 已经作为通用能力提供的数据，没有跨层新增职责。

## 决策 2 — harvest 到的路径怎么用：当作产物新真源 vs 当作诊断证据 → **选"仅当诊断证据，不改变 canonical 产出位置"**

现有约定是产物必须落在 wd（相对路径，`_output_boundary` 已明确），下游（`report` 生成、下一 stage 的
产物加载、resume 逻辑）都依赖这个固定位置读取。若把 harvest 到的绝对路径当作产物的新合法位置（"agent
说写哪就认哪"），会让产物散落到任意路径，把"定位问题"换成"下游要兼容任意路径"的维护负担，且违反
`_output_boundary` 已经存在的强约束。因此 harvest 结果只作为**诊断证据**使用：确认 `_missing_artifact_error`
触发时，缺失的产物是否被这一轮的 Write/Edit 调用错误地写去了 wd 之外（如 op_dir）——canonical 产出
位置始终是 wd，不因诊断结果改变。

## 决策 3 — 确认误落点后：自动搬回 wd（自愈）vs 仅证据化诊断、交给下一轮重试 → **选"仅证据化诊断"**

即使 transcript 精确证明了"这一轮的某次 Write 调用把文件写去了 op_dir"，也不代表该次写入的内容是这
一轮 agent 打算产出的最终版本——可能是中间态、误操作的半成品。自动读取并搬迁未经过正常产物解析/校验
流程的内容去顶替正式产物，相当于新开一条绕过既有校验路径的写入通道，与"产物必须经过 `_parse_single`/
`_read_disk_artifacts` 的解析校验"这条既有不变式冲突。因此选择更保守的做法：确认误落点后，把这条
**证据本身**（"检测到 `<filename>` 被写入了 `<实际路径>`，而不是当前工作目录"）作为 `_missing_artifact_error`
的纠正文案主体喂给下一轮重试——纠正信号从"通用提示、猜测原因"变成"精确指出这一轮真实发生的错误"，
但产物仍必须经过正常流程重新落地在 wd，不引入自动内容接受路径。

## 决策 4（P4）— Bash 调用（`cp`/`mv`）目标路径的覆盖范围 → **best-effort 命令解析，非阻塞项**

Write/Edit 的 `file_path` 是结构化字段，直接读取即可、可靠性高；Bash 调用只有整条命令字符串，若要
覆盖 `cp`/`mv` 场景需要额外的命令解析（识别 `cp`/`mv` 及其参数），可靠性和覆盖面天然弱于 Write/Edit
读取。本轮范围：优先实现 Write/Edit 的结构化读取（覆盖绝大多数场景，`_output_boundary` 本身也是引导
agent 用 Write/Edit 产出，不是引导用 Bash 挪文件）；Bash 命令解析作为可选的 best-effort 增强，不作为
本轮阻塞项，缺失时静默跳过 Bash 类工具调用的检测（不影响 Write/Edit 场景的确定性）。

## 决策 3 修订 — 证据确凿时的用户决策门：复用 `on_decision`，而非新造打断机制

决策 3 原文（"仅证据化诊断，不自动搬回"）作为**核心不变式继续冻结**：搬回操作永远不直接采信内容，
必须重新走 `_read_disk_artifacts`/`_locate_artifact` 的定位+解析校验路径。本条只是把"要不要问用户"
这一步，从"决策 3 原本隐含的唯一选项（诚实记录 + 下一轮重试）"，演进为"复用系统已有的
`state.on_decision` 策略给出两条路"：

- `on_decision="default"`（系统默认）：不打断流水线。`runner.py` 的 `_execute_ask_user_question`
  按 `default_index` 自动选中安全项（"不搬，按纠正提示重新生成"）、记一行日志、继续跑——这正是决策 3
  原有行为，纠正文案从"通用提示"变成"精确指出这一轮真实发生的误落点"。
- `on_decision="abort"`（用户主动加严）：`_execute_ask_user_question` 在非交互模式下写
  `pending_decision.json` 并抛 `DecisionPendingError`，交互模式下真弹窗——问用户是否要把文件搬回
  工作目录。用户选"搬回"时，`_read_disk_artifacts` 的决策回退分支把文件物理 move 到 wd 后，仍然落入
  与其他产物完全相同的定位+解析循环，不开绕过校验的第二通道。

**架构落地修订（相对已批准的实施计划的偏差，需在此记录）**：批准计划原稿的 `_DesignSubstage.actions()`
伪代码是 `if state.pending_relocation and state.on_decision == "abort":`——即把 `on_decision` 判断放
在 stage 层。实现阶段重新核对 `GeneralDesignStage` 现存的 cross-generation gate（同样是"命中某条件就
直接返回 `AskUserQuestion`，否则 `super().actions()`"的形状）发现：那个先例完全不检查 `on_decision`，
全部策略分支（交互/非交互、default/abort）都封装在 `runner.py` 的 `_execute_ask_user_question` 里，
stage 只管"要不要问"，不管"问了之后怎么落地"。若在 stage 层也加一层 `on_decision == "abort"` 判断，
会把同一策略拆成两处独立实现（stage 一处、runner 一处），违反 §2.5 唯一通路与 §1.2 架构合理这两把尺子。

因此最终实现是 `_DesignSubstage.actions()` **无条件**在 `state.pending_relocation` 命中时返回
`AskUserQuestion(default_index=0)`（`design_substages.py` 的 `_RELOCATE_KEEP`/`_RELOCATE_MOVE` 门禁），
把 `on_decision` 分支完全留给 `runner.py` 既有实现消费——`default` 时自动选中 index 0 的安全项，
`abort` 时才真正暂停。效果与批准计划描述的用户可见行为完全一致（default 不打断、abort 才问），只是
判断"是否要问"与"问了之后怎么处理"的权责边界更干净地落在了各自该在的层。
