# Pipeline Observability — 问题/需求记录

> 来源：2026-06-23 完整管线执行日志分析（`logs/run_20260623_152938.log`）

## 问题清单

### P1: SDKBackend 初始化日志显示错误的 LLM provider 信息 ✅

**现象**：日志首行 `SDKBackend initialized with LLM provider: Anthropic (claude-sonnet-4-6)`，但当前工程并未使用 Anthropic API——实际 agent 调用走 claude_agent_sdk，SDK 内部自己管理模型选择。

**证据**：
- `sdk_backend.py:405` 日志输出 `self._llm_provider.provider_name()`
- `dispatcher.py:435` 默认传 `llm_provider="anthropic"`
- `anthropic.py:94` `provider_name()` 返回 `f"Anthropic ({self._model})"` 其中 model 硬编码为 `"claude-sonnet-4-6"`
- `SDKBackend.spawn()` 实际不使用 `_llm_provider` 做 API 调用，而是委托给 claude_agent_sdk

**影响**：日志信息与实际情况不符，可能误导排查（如怀疑模型选择错误）。

**Resolution**：已删除。`SDKBackend.llm_provider` 参数、`adapters/llm/` 整目录、CLI `--llm-provider` option、`State.llm_provider` 字段、相关测试全部移除。1259 UT + 19 ST 全绿。

### P2: "gd-generate" 命名风格与同级 stage 不一致 ✅

**现象**：design 组内各 stage 命名：
- `gd-generate`（缩写，风格断裂）
- `general-design-review`（完整描述）
- `template-division`、`dd-intake`、`split`、`buffer-kernel`、`precision-perf`...

`gd-generate` 是与 `general-design-review` 配对的 stage，但使用了不直观的缩写。

**证据**：
- `design_substages.py:381`: `class GeneralDesignStage: name = "gd-generate"`
- `design_substages.py:467`: `class GeneralDesignReviewStage: name = "general-design-review"`
- `orchestration-config.json:15`: skills 映射使用 `"gd-generate": "stage-design:ascendc-op-general-design"`

**影响**：命名不统一降低代码可读性；新开发者难以从名字推断 `gd-generate` 的功能。

**Resolution**：已重命名 `gd-generate` → `general-design-generator`。覆盖 `GeneralDesignStage.name`、`orchestration-config.json`（skills + iterations key）、`design_artifacts.py`（working dir）、所有 test 字面量、SKILL.md 引用。仅 plan 历史文档保留旧名以维护历史。

### P3: ForkJoin 并行的 stage_iteration 日志不含模板/分支路径 ✅

**现象**：日志中 `stage_iteration split iteration 1/3` 出现两次（第 311-312 行），无法区分是哪个模板的 split stage。同样 `buffer-kernel` 和 `precision-perf` 也存在该问题。agent stream 日志（如 `[split/InterleaveBased]`）有分支前缀，但 `stage_iteration` 没有。

**证据**：
- `runner.py:219-220`: `self.Logger.action("stage_iteration", f"{stage.name} iteration {iteration}/{iteration_ceiling}")` —— 只用了 `stage.name`（都是 `"split"`），不含 scope path
- tiling ForkJoin 产生 2 个模板分支：`ContiguousSplit`、`InterleaveBased`，每个分支内都有 split/buffer-kernel/precision-perf 同名 stage
- agent stream 日志包含分支：`agent_stream [split/InterleaveBased] ascendc-design-generator turn N`

**影响**：控制台日志中同名字段重复出现且无法区分来源，排查时只能靠时间线推断。

**Resolution**：`GraphExecutor._execute_atomic` 在调用 `Runner.run_stage` 前设置 `runner._scope_prefix = path`。Runner 的 `stage_iteration` / `stage_done` / events 统一使用 `{scope_prefix}/{stage.name}` 格式。现在输出如 `detailed-design/tiling/ContiguousSplit/split iteration 1/3`。

### P4: gate stage is_satisfied 不检查 blocking_issues ✅

**现象**：`general-design-review` 运行了 3 次迭代，所有迭代都产出了 `general_design_reviewed.json` 所以 `is_satisfied` 默认返回 True。但 `is_satisfied` 不检查 `blocking_issues` 是否清空——带未解决阻塞问题的 review 结果即可进入下游。

**证据**：
- `base.py:48`: `default_max_iterations = 3`（`GeneralDesignReviewStage` 未覆盖）
- `base.py:93-103`: `is_satisfied` 默认 `return True`（只要求 provides 存在）
- 三个 gate stage（`GeneralDesignReviewStage`、`AnchorCheckStage`、`ValidateStage`）均有 `blocking_issues()` 方法但均未覆写 `is_satisfied`

**影响**：可能产出带未解决阻塞问题的 review 结果即进入下游。

**Resolution**：三个 gate stage 各覆写 `is_satisfied` 返回 `len(self.blocking_issues(state)) == 0`。只有 blocking_issues 清空才退出迭代，从机制上杜绝带问题的 gate 产物进入下游。

### P5: 工作流超时检查粒度太粗，导致大幅 overshoot ✅

**现象**：超时预算 1800s，实际运行到 2882.8s 才被检测到，超出 1082.8s（+60%）。

**原因**：超时检查 `_check_timeout()` 仅在每个 stage iteration 的 for-loop 开头调用。每次 iteration 内 agent spawn 可能耗时 100+ 秒，deadline 可能落在长时间 spawn 中。

**证据**：
- `runner.py:217`: `self._check_timeout(stage.name)` 在 iteration loop 开头
- `e2e_run.sh:42`: `WORKFLOW_TIMEOUT="${WORKFLOW_TIMEOUT:-1800}"`

**影响**：超时不可靠，实际运行时间远超预算。

**Resolution**：`_check_timeout` 从 iteration 级下沉到 action 级——在 `_execute_spawn_agent` 的 `backend.spawn()` 调用前增加检查。最大 overshoot 从"一次完整 iteration"缩至"一次 agent spawn"。

### P6: SDKBackend LLM provider 信息与 claude_agent_sdk 脱节 ✅

**现象**：`_llm_provider` 作为 SDKBackend 的构造参数，但其唯一用途就是打印第 7 行日志。claude_agent_sdk 的内部模型选择对此字段完全透明。即使将来切换模型（如从 sonnet 换到 opus），这行日志也不会变化。

**证据**：
- `SDKBackend.spawn()` 不使用 `_llm_provider`
- `SDKBackend.__init__` 第 395-405 行只是 resolve 了一个 provider 对象只用于 `provider_name()` 调用

**影响**：日志信息无实际参考价值，且可能长期不更新产生误导。

**Resolution**：随 P1 一并删除。`_llm_provider` 字段、`llm_provider` 构造参数、`adapters/llm/` 整目录已移除。

### P7: 多轮迭代不输出触发原因，排查靠猜 ✅

**现象**：`general-design-review` 运行 3 轮，`requirement` 1 轮即完成。日志只显示 `stage_iteration general-design-review iteration 1/3` / `2/3` / `3/3`，没有任何原因说明为何进入下一轮——是 agent 自行请求继续（`is_terminal=False`）、质量自检未通过（`is_satisfied=False`）、产物缺失（contract unsatisfied）、还是 schema 校验失败？

**证据**：
- `runner.py:254-268`: early-termination 判断仅内部状态机用，判断结果不写日志
- `runner.py:270-274`: 仅 `max_iterations` 耗尽且 contract 未满足时有一条 warn，**中间 rounds 的原因完全空白**
- 日志示例：`general-design-review iteration 2/3` — 读日志的人无法判断第 1 轮是否失败了需要重试、还是 agent 主动细化、还是质量自检卡住

**影响**：日志沦为状态机进度条，不具备排查价值。当 stage 反复迭代到预算耗尽才停时，无法回溯根因。

**Resolution**：Runner early-termination 判断后抓取原因写入 `_iteration_reason`，下一轮 `stage_iteration` 日志追加原因。同时写入 `events.jsonl` 的 `iteration_start` event 的 `reason` 字段。三种原因：`contract unsatisfied: {list}` / `quality check not satisfied` / `agent continuing (is_terminal not set)`。

### P8: 日志行缺少时间戳，无法还原时序 ✅

**现象**：所有日志行（`stage_iteration`、`agent_spawn`、`agent_stream`、`[INFO]`、`[WARN]`、`[ERROR]`）均不携带时间戳。以 `20260625.log` 为例，只有 agent_stream 行记录了单轮耗时（如 `65.3s`），但无法知道该行打在什么时刻、与前后行的真实时间间隔。

**证据**：
- `infra/logger.py`: `action()`、`info()`、`warn()`、`error()` 均只输出 prefix + message，无时间
- 控制台日志重定向到文件后，完全丢失时间维度，排查时只能靠内容推断先后

**影响**：日志文件无法独立还原执行时序；需要关联外部时间源（如文件修改时间）才能判断耗时瓶颈。

**Resolution**：`Logger._ts()` 为每行日志输出添加 `[HH:MM:SS]` 前缀，覆盖 `action()`、`info()`、`warn()`、`error()`、`stage_header()`、`stage_done()` 全部入口。

### P9: stage abort 后 workflow done 显示 0.0s，与实际耗时严重不符 ✅

**现象**：`20260625.log` L113 显示 `✓ workflow done (0.0s)`，但 requirement stage 的 agent 实际跑了 167s。

**证据**：
- `PreconditionError` 从 `runner.run_stage()` 中途跳出 → `runner.py` L312 `stage_complete` 事件**未写入** `events.jsonl`
- `report.py` L60 `total_elapsed` 只累加 `stage_complete` 事件的 `elapsed_ms`
- 只有 entry/context（均 ~0ms）有 `stage_complete` 事件 → `total_elapsed = 0`
- `dispatcher.py` L600 `Logger.stage_done("workflow", 0)` → 打印 0.0s

**影响**：异常路径的耗时完全丢失，workflow done 行无参考价值，无法从日志判断实际运行了多久。

**Resolution**：
1. **Runner 拆两层**：`run_stage()` 变为 10 行 wrapper（try/except 捕所有异常 → 发 `stage_aborted` 事件 + re-raise），原体迁到 `_run_stage_body()`。
2. **单事件类型**：新增 `evt.stage_aborted(stage_name, elapsed_ms, error_type)`，用 `error_type` 字段区分异常种类。
3. **墙钟兜底**：dispatcher 记录 `run_start`/`run_end` 墙钟传给 report，`total_elapsed_ms` 不再依赖 `stage_complete` 累加。异常路径耗时自动覆盖。

### P10: agent session_id 未在日志中打印，crash 排查无法关联后台会话 ✅

**现象**：`20260625.log` 全程未出现 session_id。只有 `agent_resume` 路径（crash 恢复时）会打印，正常流程完全不暴露。

**证据**：
- `sdk_backend.py` L595-601 从 SDK 事件流捕获 `session_id`，但仅用于 crash-resume（L740 `resume=session_id`）
- `agent_spawn` 日志（L528）在事件流启动之前，此时 session_id 尚未拿到
- `agent_stream` 日志（L648）只打印 turn/chars/elapsed，不含 session_id

**影响**：无法从日志关联后台 API 的 agent 会话，排查问题时只能靠时间戳猜测。

**Resolution**：在首次捕获 session_id 时打一条一次性 `agent_session` 日志。新增 `session_id_logged` 标记防重复，位置在 `sdk_backend.py`。

### P11: `load_profile` 日志重复打印 3 次，同一 profile 无缓存 ✅

**现象**：`20260625.log` 中同一 profile `ops-transformer` 被加载并打印 3 次（L62/L67/L71）。每次调用重新读 YAML、解析、打日志。

**证据**：
- L62：`cli/run.py:88` → `resolve_op_dir()` → `load_profile()` — CLI 解析 `--op-dir`
- L67：`dispatcher.py:463` → `load_profile()` — 获取 `artifacts_ignore` 配置
- L71：`context.py:118` → `ProfileLoader.load()` — 构造 OperatorIdentity
- `ProfileLoader.load()` 无 `@lru_cache` 或任何缓存机制

**影响**：日志噪声（3 条相同信息无增量价值）；不必要的文件 IO 重复。

**Resolution**：`ProfileLoader.load()` 添加 `@lru_cache`，同一 run 中同名 profile 只加载一次。

### P12: "IO chain issue" WARN 误导用户，user-provided 字段是预期行为 ✅

**现象**：`20260625.log` L63 输出 `[WARN] Workflow IO chain issue: Stage 'verify' requires ['golden_path'] (user-provided, not produced by any previous stage)`。`golden_path` 是用户通过 `--golden` CLI 参数传入的，不存在于任何 stage 产物中是预期行为，但 WARN 级别 + "issue" 用词暗示配置有误。

**证据**：
- `workflow.py:86-88`：累加所有前置 stage 的 provides 后仍缺失的字段统一标记为 `(user-provided, not produced by any previous stage)`
- `dispatcher.py:407`：`Logger.warn(f"Workflow IO chain issue: {err}")`

**影响**：用户看到 `[WARN]` + "issue" 会误以为配置有问题，实际一切正常。

**Resolution**：`dispatcher.py:407` `Logger.warn` → `Logger.info`；`workflow.py:88` 消息改为 `(user-provided inputs — validated by preflight)`。

### P13: agent_stream 日志不区分 block 类型（text/thinking/tool_use），相邻 turn chars 重复无法解释 ✅

**现象**：`20260625.log` 中相邻 turn 的 chars 完全一致（如 turn 7-8 都是 5715 chars），因为 SDK 把 text/thinking 和 tool_use 拆成两个 AssistantMessage，tool_use 轮不增 chars。日志不标注类型，无法判断哪些轮在思考、哪些在调工具。

**证据**：
- `sdk_backend.py` L618-649 遍历 `event.content` 时能区分 `text`/`thinking`/`tool_use`（L619/L626），但 `agent_stream` 日志行（L648）只输出 turn/chars/elapsed，不含 block 类型
- transcript 验证：turn 7 是 5000+ 字 text，turn 8 是 `tool_use:resolve_ambiguity`，两者 chars 完全相同

**影响**：排查时无法快速判断 agent 行为模式（思考 vs 操作）；chars 成对重复的现象无法从日志本身解释，只能靠 transcript 回溯。

**Resolution**：在 `agent_stream` 日志行追加 block 类型标签 `[text]`/`[thinking]`/`[tool:<name>]`，位置在 `sdk_backend.py`。

### A: requirement-analyst 将 "mode 无默认值" 误判为 blocking，导致 non-interactive abort ✅

**现象**：`20260625.log` L109 `[ERROR] Stage 'requirement' aborted: requirement underspecified — 1 blocking item(s) need clarification but the run is non-interactive`。根因：agent 将 C API 必传参数 `mode` 的无默认值属性误判为需求缺失。

**根因链**：
1. Agent manifest (`requirement-analyst.md`) 指导将 "无默认值的运行时参数" 归类为 `blocking`
2. `resolve_ambiguity` 在非交互模式下 auto-select 第一选项："无默认值，阻塞未解决，resolution=null"
3. `_apply_non_interactive_severity` 检测到 blocking+null → `PreconditionError` → pipeline abort

**Resolution**：
- L1（skill prompt）：`requirement-analyst.md` 新增 "C API required-parameter with NO default→NOT blocking" 规则 + resolve_ambiguity options[0] 必须是有效 resolution + 示例修复
- L2（框架兜底）：`requirement.py` `_apply_non_interactive_severity` 首次遇到 blocking+null 不 abort，注入 loopback feedback 让 agent 重新评估；仅二次确认 blocking 时才 raise

## 非问题（已确认正常的行为）

- `split iteration 1/3` 出现两次：ForkJoin 两个模板分支并行执行同名 stage，属预期行为（见 P3 的日志可读性问题）
- `buffer-kernel` 在 `split` 未全部完成时就开始：ForkJoin 中更快的分支先完成 split 后立即进入 buffer-kernel，属并行预期行为
- `requirement_doc.md`：用户需求文档的 CWD 拷贝，设计如此（F2 第一性原理）
