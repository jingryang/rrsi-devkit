# L3 方案分析 — training-time 进化回路 + 多通道用户确认模块

> **性质**：self-evolution 线工作记录（L3），step 70。承接 `self-evolution-design.md`（v0.7 主线）/ `04-training-time-iteration.md` / `07-eval-vs-correction-analysis.md`。
> **本步定位**：把用户「重命名 self_evolve→cann-bench-eval + 新增 training-time 四 stage + 多通道用户确认 + 确认后上库」的整体设想，**对齐到既有 self-evolution 设计线**，给出初步方案与关键决策点，供逐轮细化。
> **纪律**：遵守 `plan-doc-discipline`——语义锚点（类名/方法名/接口签名），不写 `file:line`，不维护代码现状快照，外部依赖只读。
> **新增 vs 引用**：本线两层迭代（§2.2）、人工参与两层模型（§2.5）、候选积木（§6）、训练循环（`04`）、cann-bench 一次性 loss（`07`）**均已设计**，本文只引用不重述；**真正新增**仅三处——① 重命名的具体决策、② 多通道确认模块、③ 确认后上库（GitAdapter 落地）。

---

## 0. 用户设想 ↔ 既有设计的映射

用户整体设想并非新方向，而是既有 self-evolution 设计的 **training-time 层 (b) 的具体化**。映射如下（避免重复造轮子，§2.5 单一通路）：

| 用户设想 | 既有设计位置 | 状态 | 本文动作 |
|---|---|---|---|
| 「self_evolve 实际只走到 cann-bench 评测，重命名为 cann-bench-eval」 | `07` §1 表 ②：cann-bench = training-time 一次性 loss，**刻意 NO loopback**（已落地于 `SelfEvolveOpWorkflow` / `CannbenchEvalStage`） | 设计已定、已实现 | **命名后果**：名字诚实化（D1） |
| 「不删 self_evolve，在当前基础上新增」 | §2.2：两层迭代——(a) inference-time 单算子修正（已有）vs (b) training-time 跨算子改进（待建） | (b) 待建 | 物化 (b) 为 `self_evolve` training-time 编排（D2） |
| 「新增问题分析 stage（利用已有 skill）」 | §6：`eval_review`/`root_cause`/`issue_triage`；`04` §3 归因骨架；既有 `AttributionEngine` | 积木已命名、未接线 | stage 定义 + skill 映射（D3-S1） |
| 「问题解决方案制定 stage」 | §6：`diagnose`→fix_plan；`04` §2 改进对象风险分级 | 积木已命名、未接线 | D3-S2 |
| 「问题解决实施方案制定 stage」 | （§6 未单列，属「方案→可执行步骤」拆解） | 新能力 | D3-S3 |
| 「问题解决修改编码及回归验证 stage」 | §6：`fix_self`/`verify_fix`；`04` §4 回归保护（铁律） | 积木已命名、未接线 | D3-S4 |
| 「公共用户确认模块，决策人是用户；不仅 MCP 弹框，还可邮件/三方通信（钉钉）」 | §2.5：训练时人工审核=**独立 Stage**（非 `resolve_ambiguity`/`__halt__`），建在「默认决策契约 + 非交互开关」之上；既有 `resolve_ambiguity`（default/abort/notify-webhook）+ `respond` CLI | 机制骨架已有，**IM/邮件适配缺失**，`human_review` Stage 未建 | **核心新增**：`ConfirmationChannel` 协议 + 多 adapter（D4） |
| 「用户完全确认后修改上库，达到自我进化」 | §6：`prepare_pr`/`await_merge` + `GitAdapter`；§8 #6 待定；**用户追加：经 gitcode Issue（带日志附件）跟踪问题再分析解决** | 积木已命名、未落地 | D5（扩展为 issue 流） |

> **一句话**：用户的 4 stage 是 §6 已命名积木的粗粒度聚合；真正要新建的框架设施只有「多通道确认模块」与「上库门」两块，其余是接线既有组件。

---

## 1. 关键事实（引用，非本文产权）

下列事实产权在既有 L1/L3，本文仅引用：

- **F1（eval 终态）**：`SelfEvolveOpWorkflow` 是单算子 inference-time 流水线，终态为 `cannbench_eval`；`eval_result` 在该 workflow 内**无下游消费**（`finalize` 不读它）。这是 `07` §1 表 ② 决策（cann-bench 一次性 loss、NO loopback）的实现后果，非缺陷。——产权：`07-eval-vs-correction-analysis.md` D4 + `06-problems.md` P5。
- **F2（上层未接线）**：`self_evolution/` 包（`TrainingRunner` / `LossAggregator` / `AttributionEngine` / `OpScheduler`）已设计训练循环骨架，但 `_apply_improvements()` 为空壳（只 record 不 apply）；CLI（`batch_self_evolve.sh` → `run --batch`）直接并发派发 `self_evolve_op` 子进程，**绕过** `TrainingRunner`。——产权：`self-evolution-design.md` §5「待建」+ `04`。
- **F3（确认机制现状）**：编排型子 agent 的 `AskUserQuestion` 被两后端 `disallowed_tools` 禁用（§4.4）；编排层提问走 `resolve_ambiguity` MCP（`mcp__engine__resolve_ambiguity`），三策略中 `abort` 是唯一真异步路径（落盘 `pending_decision.json` → `DecisionPendingError` 暂停 → `respond` CLI 写 `decision_response.json` → `run --resume` 消费）；`notify-webhook` 是**同步阻塞**（30s 超时回落 default），非真异步；**无钉钉/邮件适配**（零代码）。——产权：`self-evolution-design.md` §2.5 + `06-problems.md` 相关条目。
- **F4（决策事件可观测）**：`events.jsonl` 已有 `decision_pending` 事件（记录 stage/iteration/question）——确认模块的可观测信号已具备。

> **建议追加的 L1 条目**（产权应在 `06-problems.md`，留下一轮细化时落）：P-「`self_evolve_op` 命名与终态职责不符（07 已定性为一次性 loss，名字仍叫 self_evolve）」；P-「确认机制缺 IM/邮件通道、`human_review` Stage 未建」。

---

## 2. 决策点（调研中演进，拍板后冻结）

### D0（meta）：本线是否建制化进四层体系？

`self-evolution/` 线当前游离于四层体系外（`00-review-2026-06-29.md` 已列为待决）。本步推进 training-time 落地，是建制化的自然时机。

- **选项 A**：维持现状——继续 step-numbered 约定（本文 step 70），不挂 L2 总纲，与 skills 线并行。
- **选项 B**：建制化——建标准 L1/L3 子目录 + 挂 L2 总纲（`skills-integration-and-tdd-plan.md` 步骤索引表）。
- **推荐 A（暂维持现状）**：self-evolution 线与 skills 线**正交**（前者做 loss 训练闭环，后者做 skill 接入/编排归位），硬挂 skills 线的 L2 会混淆产权；本线已有自洽的 step 编号 + `06-problems.md` 共享 L1 + 主设计 `self-evolution-design.md`。建制化与否不阻塞本方案，留作用户拍板。
- 四把尺子：可维护（不混淆两条线产权）✓；可扩展（step 编号可续）✓；可诊断（`00-review` 文件已是入口）✓；架构合理（正交线不强并）✓。
- **✅ 拍板（2026-07-23）**：选 A——维持 step-numbered 现状，不挂 L2 总纲（self-evolution 线与 skills 线正交）。

### D1：重命名 `self_evolve_op` → cann-bench-eval

重命名是 `07` ②决策的**命名后果**——该流水线终态是 cann-bench 一次性 loss，叫「self_evolve」名不副实；腾出 `self_evolve` 名字给真正的 training-time 层。

- **选项 A**：registry 名 `cann_bench_eval_op`（snake_case 符合既有惯例 `self_evolve_op`/`generate_ascendc_se`；**保留 `_op` 后缀**），work-name/CLI 用 `cann-bench-eval`。
- **选项 B**：registry 名 `cann_bench_eval`（去 `_op`）。
- **选项 C**：不重命名，仅在上层新建 `self_evolve`。
- **推荐 A**：保留 `_op` 后缀恰好成为**两层架构的命名信号**——`cann_bench_eval_op`（per-op eval 流水线，inference-time）vs `self_evolve`（跨 op 训练层，training-time），`_op` 即「单算子」。重命名是机械改动（registry 名 + manifest `workflow:` 字段 + `e2e_self_evolve.sh`/`batch_self_evolve.sh`/`rerun_from_stage.sh` + 测试/fixture，覆盖 17 文件），按 CLAUDE.md §1.4 **不留兼容别名**、一刀改净。
- 四把尺子：可维护（名字诚实，读 code 即知是 eval-ending 流水线）✓；可扩展（`self_evolve` 名字腾给训练层）✓；可诊断（两层不混淆）✓；架构合理（命名落在 `@register_workflow` 单一注册点）✓。
- **前置**：确认无外部系统硬依赖字面量 `self_evolve_op`（manifest 由本仓脚本生成，无外部消费者）。
- **✅ 拍板（2026-07-23，覆盖原推荐）**：registry 名用 `cann_bench_eval`（**不保 `_op`**），CLI/work-name `cann-bench-eval`。两层靠纯名字语义区分——`cann_bench_eval`（per-op eval 流水线）vs `self_evolve`（training-time loop），不依赖 `_op` 后缀作信号。重命名机械面（registry + manifest `workflow:` 字段 + `e2e_self_evolve.sh`/`batch_self_evolve.sh`/`rerun_from_stage.sh` + 测试/fixture，17 文件）与 §1.4 不留兼容，照旧。

### D2：真 `self_evolve`（training-time）的编排形态

- **选项 A**：新建独立 Workflow `self_evolve`，编排 meta stages（归因/方案/实施/编码回归/确认）；「跑算子」交给外层调度器（§2.6）。即把 `TrainingRunner` 物化为 Workflow。
- **选项 B**：直接填 `TrainingRunner._apply_improvements()` 空壳（保持 runner 形态，不做 Workflow）。
- **选项 C**：把四 stage 做成 `cann_bench_eval_op` 的后继 stage（接在 eval 后）。
- **推荐 A，且复用不重造**：training-time 编排用 Workflow 形态（符合 §1.1 Stage 标准入口、可 event-sourcing、可 `--resume`），但其 stages **调用既有** `TrainingRunner`/`OpScheduler`/`LossAggregator`/`AttributionEngine`，而非平行实现（§2.5 单一通路）。**明确否定 C**：违反 `07` ② NO-loopback，把 training-time 混进 inference-time 流水线（§2.2 两层混淆）。
- 四把尺子：可维护（复用既有 evolution 组件）✓；可扩展（Workflow 可加 stage）✓；可诊断（event-sourcing + `decision_pending` 事件）✓；架构合理（两层不混）✓。

### D3：四个 training-time stage 的定义 + skill/agent 映射

用户的 4 stage 聚合了 §6 多个积木。每 stage 后接 human-gate（D4）。I/O 以文件接力（§2.3）。

#### D3-S1 问题分析（← `eval_review`/`root_cause`/`issue_triage`）
- **职责**：读 per-op `EvalResult` 聚合 + cann-bench report → `AttributionEngine` 粗分类（compile/precision/perf/deploy/eval_zero → target_component）→ 按 failure_type 分流到既有 skill 做细分析：
  - 编译/规范 → `ascendc-code-review` + `build_log_scanner`（确定性前置筛）
  - 性能 → `ascendc-profiling` / `ascendc-profiling-analysis`
  - 精度 → `ascendc-precision-diagnose` / `ascendc-dumptensor`
  - 运行时 → `ascendc-runtime-debug`（错误码解码）
  - 同步 → `ascendc-sync-static-check`（已为 diagnose tail_call）
- **职责边界**：复用 `ascendc-precision-scope-guard` 思路——判定失败属「算子质量」还是「框架/上游产物缺陷」，命中上游则 halt 不浪费 training 预算。
- **产物**：结构化根因报告（JSON + md），含 failure_type / target_component / severity / 证据。
- **缺口**：无「读 cann-bench report → 综合根因」的现成 skill，需新写编排（调度上述 skill），但**底层 skill 全部复用**。

#### D3-S2 问题解决方案制定（← `diagnose` → fix_plan）
- **职责**：根因 → 改进对象（`04` §2 风险分级：resources 知识库 < skill prompt < agent manifest < 框架 Python）+ 候选策略。
- **复用**：`evolution-knowledge`（知识底座）+ `evolution-strategies`（P/A 系列候选策略池，**仅性能/精度方向**）+ `proven_solutions/`（方案沉淀落点）。
- **不硬套** `evolution-world-model`（决策树探索范式，是「试错寻优」，与 training-time「已知根因→定向方案」范式不匹配）。
- **产物**：`fix_plan`（候选改进列表，仿 `ascendc-precision-fix` 的 `candidate_pool` 契约：改进对象 + 策略 + 预期收益 + 风险级）。

#### D3-S3 问题解决实施方案制定（新能力）
- **职责**：`fix_plan` → 可执行步骤（改哪个 skill/agent/资源文件、什么顺序、怎么验证）。
- **定位**：「方案→L4」的拆解，§6 未单列。可借 `ascendc-op-dev-coding-regbase` 的「编排器拆步骤」范式（s2-analysis→s4-coding 的步骤分解思路）。
- **产物**：实施步骤清单（改动的语义锚点 + 顺序 + 每 step 验证方式）。

#### D3-S4 问题解决修改编码及回归验证（← `fix_self`/`verify_fix`）
- **职责**：按实施步骤定点改 → 回归。
- **编码**：`incremental-developer`（定点修复，最佳匹配）/ `perf-tuner`（性能类）/ `cannbench-adapt`（glue 层）；全量重写走 `ascendc-coder`。
- **回归**：`cannbench_eval`（标准 loss 重测）+ `TrainingRunner._check_regression`（baseline 守卫，任一算子跌幅 > 阈值 → 回滚，`04` §4 铁律）+ `ascendc-test-simple`（轻量快验）。
- **契约**：仿 `ascendc-precision-fix` 的 commit/rollback + 副作用检测。

### D4：公共用户确认模块（**核心新增**）

这是本方案真正要新建的框架设施。设计三层：

**① 形态——可复用的门 Stage**
- §2.5 P6b 已定：训练时人工审核 = **独立 Stage**（非 `resolve_ambiguity`/`__halt__`，后者是 Stage 内运行期抉择）。
- 用户要求「每个 stage 决策人是用户」→ `HumanReviewStage` 作为**通用门组件**，在 D3 每个 stage 后继调用（D3-S1→gate→S2→gate→S3→gate→S4→gate→上库门）。

**② 通道抽象——`ConfirmationChannel` 协议（§1.6 依赖注入）**
- 定义 protocol/ABC：`request_decision(question, options, context) -> Decision`（+ 异步句柄）。
- adapter（可插拔）：
  - **MCP popup adapter**：包 `resolve_ambiguity`（交互 TUI 走 `default`/`abort`）—— 即插即用语境的原生提问。
  - **Welink（华为）adapter**：调华为 Welink SDK/机器人发消息卡片，等回复（用户首期选定的三方通信通道）。
  - **邮件 adapter**：发邮件 + 解析回复（reply-to 或确认链接）。
  - **webhook adapter**：既有 `notify-webhook` 泛化（同步阻塞，作兜底）。
- **异步闭环**：**复用既有 `abort` 路径**（落盘 `pending_decision.json` → 暂停 → `respond` 写 `decision_response.json` → `--resume` 消费）。IM/邮件 adapter 只负责「把 decision request 推到外部通道 + 把外部回复写回 `decision_response.json`」，框架的暂停/resume 原语不变（不造新原语，§1.2 正确改动落在既有机制）。
- **可观测**：复用 `events.jsonl` 的 `decision_pending` 事件（F4）。

**③ 默认决策契约（§2.5 基础层 + §8 #10/#11）**
- 非关键决策：框架代选默认值（批量/无人值守，`default` 策略，受控非静默）。
- 关键方向决策：必走真人（`abort` → 外部通道）。
- 「必须真人 vs 可默认」边界 = §8 #11（改 `src/` Python 必真人、改 skill md/agent manifest 可默认）—— 留 L4 细化。

**外部集成边界（重要）**：Welink SDK/邮件服务是**外部基础设施**，按 [[external-infra-not-framework-responsibility]] 记忆原则，框架只定 `ConfirmationChannel` 协议 + 内置 MCP/webhook adapter；IM/邮件 adapter（首期 Welink）作为**可插拔实现**（部署侧提供 SDK 凭证），框架不内置 Welink SDK。**协议保证可扩展**——后续钉钉/飞书/邮件等仅新增 adapter，零改框架。
- **✅ 拍板（2026-07-23，迭代）**：**开发期先用外部版 Welink**（服务端 REST/开放 API，Linux 可跑、Claude 可调研），`ConfirmationChannel` 协议保证后续接内部版/钉钉/飞书/邮件等（新通道 = 新 adapter，零改框架）。
  - **为何外部版先行**：内部版资料在华为内网（`3ms.huawei.com/...`，Claude 不可达）+ 可能不支持 Linux；外部版开放平台有服务端 REST（OS 无关、Linux 直跑），开发期无阻塞。
  - **内部版 Linux 风险降级为「后续接入事项」**：待内部版接口形态（桌面 SDK vs 服务端 API）+ Linux 支持明确后，作为新 adapter 接入；若仅桌面 SDK 则走中继（藏于协议后）。不阻塞本期开发。这与 §4.4「skill 不写死工具名、编排层工具通路由 manifest + disallowed_tools 保证」一致——通道选型是部署/运行期配置，非硬编码。

- 四把尺子：可维护（协议隔离，adapter 独立演进）✓；可扩展（新通道=新 adapter，零改框架）✓；可诊断（`decision_pending` 事件 + 落盘，错误不静默）✓；架构合理（DI + 复用既有 abort/resume，不造新暂停原语）✓。

### D5：问题 → gitcode Issue（带日志附件）→ 分析解决 → 上库（D5a–d 已拍板；D5e 对比分析已出，待用户定）

用户明确：上库不止 `git commit`，而要**利用 gitcode 能力把问题转成 Issue（含日志附件）提交，再分析解决**。这把 D5 从「终态 commit」扩展为「贯穿回路的 issue 跟踪 + 证据附件 + 上库闭环」——gitcode Issue 成为问题的**外部跟踪单元 + 协作面 + 证据归档**。

**目标态回路**（issue 作为工作单元贯穿 D3）：
```
[D3-S1 问题分析] 根因报告
    │ （聚合后建 issue，避免 per-op issue 爆炸）
    ▼
[Issue 提交门] GitAdapter.create_issue(
      title   = 根因摘要,
      body    = 根因报告 md（引用内部 L1 P 编号）,
      attach  = [events.jsonl, run.log, cann-bench report, stderr,
                 precision_diagnose.json, profiling CSV, ...],
      labels  = [failure_type, severity])
    │  用户确认（HumanReviewStage + Welink 通道）
    ▼
gitcode Issue #N（外部跟踪 + 证据归档）
    │
    ▼
[D3-S2 方案] → [D3-S3 实施] → [D3-S4 编码+回归]
    （issue #N 贯穿；各 stage 进展以评论回写 issue）
    │
    ▼
[上库门] GitAdapter.commit + 关闭 issue #N（resolution 评论）—— 必真人确认
```

**待讨论子决策**（用户要求「展开讨论」，下列需逐项拍板）：

- **D5a — Issue 与内部 `docs/plan/` L1 的产权关系**（最关键，决定整套跟踪结构）：
  - 选项 A：gitcode Issue = 外部协作面 + 证据附件；内部 `06-problems.md` 仍是权威事实源（§1.8 不动）；Issue body 引用 L1 P 编号，双向链接。
  - 选项 B：gitcode Issue 成为权威问题跟踪（取代内部 L1）。
  - 选项 C：分层——机械/框架内部问题走内部 L1，需人工协作的重大问题走 gitcode Issue。
  - **倾向 A**：保 §1.8 内部产权单一，gitcode Issue 是对外延伸（协作 + 可附件 + 可 @ 人），不颠覆既有四层体系。
  - **✅ 拍板（2026-07-23，用户覆盖倾向，选 B）**：gitcode Issue 成为**唯一权威**问题跟踪。
  - **✅ 范围界定（2026-07-23，用户确认）**：按**四层分管**——
    - **L1 问题记录** → gitcode Issue（**唯一权威**）：评测失败/根因/修复等工作单元的权威事实源、证据附件、协作面都在 issue。
    - **L3 方案分析 + L4 实施方案** → 保留本地 `docs/plan/`（分析与实施仍本地跟踪）。
    - 即「问题在哪坏/凭什么」进 issue；「有哪些选项/选哪个/为什么/改哪个函数/怎么验证」留本地。
  - **本地组织形式后续重构（用户意见）**：当前 `docs/plan/` 组织形式不太好，后续可重构（**非本期范围**）。重构时需处理的细节：L2 总纲索引（跨步骤索引）在 L1 外迁至 issue 后，如何引用 issue 编号——留待重构期定。

- **D5b — 日志附件策略**（events.jsonl / run.log 可能很大）：
  - 选项 A：gitcode Issue attachment（需核实 gitcode 是否支持大附件 / 上限）。
  - 选项 B：run 目录作 artifact 存储，Issue 贴链接（框架侧保留产物 + 可清理）。
  - 选项 C：关键片段截断内嵌 + 全量链接。
  - **待核实**：gitcode Issues API 能力（附件 / 评论附件 / 是否类 Gitea·GitLab·Gitee）。
  - **✅ 拍板（2026-07-23）**：**分类双实现，两者都要**——能挂日志文件则挂 gitcode Issue 附件；同时挂 Welink 群空间文件存储链接（若 Welink SDK 支持）。两者不冲突。
  - **外部能力核实（2026-07-23 web 调研）**：
    1. **gitcode**：✅ 支持——`POST api.gitcode.com/api/v5/repos/:owner/:repo/file/upload` 上传文件返回 URL，再以 Markdown `[附件](URL)` 写入 Issue 正文/评论（类 Gitea/GitHub 模式）。故「挂 gitcode 附件」通路确认可行。
    2. **Welink**：🟡 大概率可行、需实测——Welink 开放平台（`open.welink.huaweicloud.com`，300+ REST API、HTTPS）有「云空间」群空间文件存储 + 分享链接能力；**公开搜索未见官方群空间文件上传 SDK 封装包**（adapter 须做薄 REST 客户端——这反而契合「框架不内置 SDK、adapter 可插拔」的设计）；云空间单文件约 **1GB 上限**。具体上传端点 + 鉴权流程 + 分享链接生成需凭开放平台文档/凭证在 L4 实施期实测。
       - **注**：开发期即用**外部版**开放平台（D4 已定外部版先行），故上述能力调研**直接适用**于本期 adapter；内部版群空间/文件 API + Linux 支持留待后续接入时核实。
  - **结论**：gitcode 附件通路已确认；Welink 群空间链接通路架构可行（adapter=薄 REST 客户端），细节待 L4 凭证实测。附件分流策略不变（小/关键→gitcode 附件；大/全量→Welink 链接，注意 1GB 单文件上限，超大文件需切片或抽样）。
  - **附件分流策略**（细节留 L4）：按日志类型/大小分流——小且关键（stderr、precision_diagnose.json 摘要）→ gitcode 附件；大/全量（events.jsonl、run.log、profiling CSV）→ Welink 群空间链接。

- **D5c — Issue 触发粒度**：per-op 失败建 issue（爆炸风险）vs **聚合后建共因 issue**（AttributionEngine 归因后）。倾向聚合。
  - **✅ 拍板（2026-07-23）**：按推荐——聚合后建共因 issue（AttributionEngine 归因后建，避免 per-op issue 爆炸）。

- **D5d — GitAdapter 能力边界**：Issues API（create / comment / close / attachment）+ commit + PR（§6 `prepare_pr`/`await_merge`）。鉴权 = gitcode PAT（[[gitcode-remote-needs-pat]]：origin=gitcode 需 PAT，fetch/push/Issues API 均可 Claude Bash 跑）。
  - **✅ 拍板（2026-07-23）**：GitAdapter **全管**（Issues API + commit + PR）；具体能力切分后续按方案合理性可调整。

- **D5e — Issue 是否驱动 stage**（用户要求展开对比，下为两种方式的优劣分析 + 推荐）：

  **方式 X：issue 驱动 stage（issue 作为 stage 输入工作单元）**
  - 形态：D3-S2/S3/S4 以 gitcode Issue（body=根因报告、attachments=日志、comments=历史进展）为主输入；产物回写 issue。
  - 优点：单一真相源=issue（契合 D5a 唯一权威）；人可在 issue 上干预/补充、stage 自动拾取；跨 run 可按 issue 号续跑；外部协作者经 issue comment 参与。
  - 缺点：
    - stage **强依赖 gitcode API** 可用性/格式——gitcode 宕则 stage 挂（违背 [[external-infra-not-framework-responsibility]]：外部故障不该让框架崩）。
    - 热路径每次读=网络调用，慢且脆。
    - **职责混淆**——issue 既是人协作面又是机读数据源：机写冗长结构化数据污染人视图、人编辑破坏机解析（违背 §2.8 workflow/data 分离）。
    - 解析半结构化 markdown 脆弱（同 §2.4 反对「整份详设当 ground truth」之理）；违背 P5/P9（确定性、可机器校验优先）。

  **方式 Y：issue 作镜像（issue 只记录，stage 读内部产物）**
  - 形态：stage 仍读确定性内部产物（State/workspace 文件：根因报告 JSON、fix_plan、precision_diagnose.json）；issue 是**单向投影**（internal→issue），供人可见。
  - 优点：
    - stage 读**确定性、机器结构化**数据，快且可靠（契合 P5/P9、§2.8 数据分离）。
    - gitcode **解耦**——gitcode 宕则 stage 照跑，issue 同步 best-effort（契合 external-infra-not-framework-responsibility）。
    - 机数据在文件/State、人协作在 issue，互不污染；issue 可由内部产物**幂等重建**。
  - 缺点：两份来源（内部产物 + issue），但机读权威只在内部、issue 权威只在人跟踪（D5a）——需明确「写方向」：internal→issue 投影，**禁止 issue→internal 反向机读**；issue 上人工编辑不自动回流 stage（人机回路不直接）。

  **推荐：Y + 结构化反馈通道（综合，兼顾 D5a 与工程原则）**
  - **issue = 人跟踪与协作的唯一权威**（满足 D5a）；**内部产物 = stage 机读执行的权威**。
  - 人在 issue 上做的**决策**（否决某修复方向、改优先级、补线索）经 **D4 的 `ConfirmationChannel`/human-gate** 回流，**而非 stage 解析 issue**——人机回路走确认门，不走 issue 文本解析。
  - 这样同时满足：D5a 唯一权威（人视角）+ §2.8/P5/P9（stage 读确定性数据）+ 解耦（gitcode 宕 stage 不挂）。
  - 四把尺子：可维护（职责清晰：机数据/人协作分离）✓；可扩展（issue 投影可换平台）✓；可诊断（内部产物确定性可校验 + issue 留人视图）✓；架构合理（不把外部协作文档当机读 ground truth）✓。
  - **状态**：D5a 的分层界定（issue=L1 记录权威，L3/L4 本地）已**隐含选 Y**——分析与实施在本地，stage 读本地产物，issue 作记录；人在 issue 上的决策经 D4 确认门回流。待用户一句话确认即冻结。

- **四把尺子**：可维护（issue 是外部协作标准件，不造新跟踪原语）✓；可扩展（GitAdapter 协议可加 PR/review/更多 API）✓；可诊断（日志附件随 issue 永久可溯）✓；架构合理（issue 落在 GitAdapter 边界，与 §6 一致；内部 L1 产权不动）✓。

---

## 3. 数据流 / 文件接力（training-time 回路）

```
[外层调度器: 并发 N 个 cann_bench_eval_op]          [self_evolve: training-time meta 编排]
        │ per-op EvalResult(overall_score / 三维)
        ▼
   LossAggregator.aggregate ──► epoch training loss
        ▼
 ┌─ D3-S1 问题分析 ──gate(HumanReviewStage)──► 根因报告
 │     (AttributionEngine + 分流 skill + scope-guard)        │ ConfirmationChannel
 ├─ D3-S2 方案制定 ──gate──────────────────────► fix_plan     │ (MCP/钉钉/邮件/webhook)
 │     (evolution-knowledge + strategies + proven_solutions) │ abort→落盘→外部回复→resume
 ├─ D3-S3 实施方案制定 ──gate──────────────────► 实施步骤清单
 │     (fix_plan → 可执行步骤)                                │
 ├─ D3-S4 编码+回归 ──gate────────────────────► 改动 + 回归结论
 │     (incremental-developer/perf-tuner → cannbench_eval     │
 │      + _check_regression baseline 守卫, commit/rollback)   │
 └─ 上库门 ──gate(必真人)──► GitAdapter.commit + 关闭 gitcode Issue #N（详见 D5）
        ▼
   下 epoch: 用新「模型」(skill/agent/资源) 再跑 cann_bench_eval_op ×N → 对比 loss
   收敛: loss < 阈值 或 连续 N epoch 无改善 → 停 / 人工（04 §4）
```

**关键不变式**：
- training-time 改的是「模型」（skill/agent/资源/框架），惠及未来所有算子；inference-time 改的是单算子代码。两层不混（§2.2）。
- 回归保护铁律：每次改「模型」后全量评测，loss 不降或某算子退化超阈值 → 回滚（`04` §4）。
- 每个 stage 的决策权在用户；框架只在「可默认」项代选（§2.5 + §8 #11）。
- gitcode Issue 作为问题跟踪单元贯穿 D3-S1→上库（D5）：聚合后建 issue（带日志附件）→ 各 stage 进展回写 → commit 关闭 issue。

---

## 4. 产权归属与后续拆分（逐步细化）

按四层纪律，本 L3 拍板后，事实/实施应分流：

- **→ L1 `06-problems.md`（事实产权）**：追加 F1/F3 对应的两条新 P（命名不符、确认通道缺失）；F2 上层未接线若未记则补。
- **→ L4 `71-...-impl.md` 系列（实施产权）**：每 stage 一份或合并，落「改哪个类/方法、顺序、TDD 验证」。建议拆分：
  - `71-rename-cann-bench-eval-impl.md`（D1 机械重命名 + 测试同步）
  - `72-confirmation-channel-impl.md`（D4 协议 + MCP/webhook adapter + 异步闭环接线；IM/邮件 adapter 留接口）
  - `73-training-stages-impl.md`（D3-S1~S4 stage 子类 + STAGE_SKILL_MAP + TRANSITION_TABLE 接边）
  - `74-commit-gate-impl.md`（D5 GitAdapter + 上库门）
- **→ 主设计 `self-evolution-design.md`**：D0/D2 若拍板建制化/Workflow 形态，回写 §5「待建」状态。

**本期（初步方案）明确不落地、留待逐轮细化**：
1. D0 体系建制化（A/B 拍板）。
2. D1 registry 名是否保 `_op`（A/B）。
3. D3 各 stage 的精确 artifact schema（I/O 契约）。
4. D4 钉钉/邮件 adapter 的具体实现（SDK 选型、凭证管理、回复解析）—— 外部集成，需用户决策。
5. D5 gitcode Issue 流（见 §2 D5）：D5a–d 已拍板（issue 唯一权威 / 附件分类双实现 / 聚合建 issue / GitAdapter 全管），**剩**：① D5a 的「唯一权威」范围界定（是否仅限 training-time 回路问题，待用户确认 §1.8 边界）；② D5b 两处外部能力核实（gitcode 附件 API、Welink SDK 群空间文件上传）；③ D5e 待用户定（推荐「Y 镜像 + 确认门反馈通道」）；目标仓/分支/PAT（§8 #6、[[gitcode-remote-needs-pat]]）。
6. §8 待定问题逐项（#5 改对象边界、#10 默认决策契约表、#11 必须真人 vs 可默认）。
7. 评测算子集固化（§2.3，training loop 的锚）、中间 loss（§2.4）是否本期纳入。

---

## 5. 变更记录

| 日期 | 版本 | 内容 |
|---|---|---|
| 2026-07-23 | v0.1 | 初版：对齐用户设想到既有 self-evolution 设计线（§0 映射）；F1–F4 事实引用；D0–D5 决策点（含四把尺子）；training-time 回路数据流；产权拆分与细化清单。真正新增仅「重命名决策 / 多通道确认模块 / 上库门」三处，其余接线既有组件。 |
| 2026-07-23 | v0.2 | **用户拍板 + D5 展开**：D0 选 A（维持 step-numbered 现状）；D1 覆盖原推荐——registry 名 `cann_bench_eval`（不保 `_op`）；D4 首期三方通道选华为 Welink，可扩展性由 `ConfirmationChannel` 协议保证。**D5 从「终态 commit」扩展为「问题→gitcode Issue（带日志附件）→分析解决→上库」**，新增 D5a–D5e 子决策（Issue↔内部 L1 产权关系 / 日志附件策略 / 触发粒度 / GitAdapter 边界 / issue 驱动 stage）供展开讨论。同步更新 §0 映射、§3 数据流、§4 细化清单。 |
| 2026-07-23 | v0.3 | **D5a–d 拍板 + D5e 对比分析**：D5a 选 B（gitcode Issue 唯一权威）+ ⚠️ §1.8 边界提醒（待用户确认范围：仅限 training-time 回路问题 vs 全量 supersede §1.8）；D5b 分类双实现（gitcode 附件 + Welink 群空间链接，两者都要）+ 两处外部能力待核实；D5c 聚合建 issue；D5d GitAdapter 全管。**D5e 展开对比**：方式 X（issue 驱动 stage）vs 方式 Y（issue 作镜像），推荐「Y + 确认门反馈通道」（兼顾 D5a 唯一权威与 §2.8/P5/P9/解耦），待用户定。 |
| 2026-07-23 | v0.4 | **D5a 范围界定 + Welink 内部版/Linux 风险**：D5a 按**四层分管**——L1 问题记录→gitcode Issue（唯一权威），L3 分析+L4 实施→保留本地；本地 `docs/plan` 组织形式后续重构（非本期）。D5e 由 D5a 分层隐含选 Y（待一句话确认）。D5b 外部能力核实：gitcode ✅（file/upload→URL→引用），Welink 🟡（外部版开放平台有云空间 REST、~1GB 上限、无官方 SDK 包→adapter 薄 REST 客户端）。Welink 改为**内部版优先**（参考 3ms 内部博客，Claude 不可达）+ ⚠️ **Linux 支持风险**（DevKit 宿主 Linux，内部版可能仅桌面 SDK）+ 缓解（服务端 REST 优先 / 桌面 SDK 则中继，藏于协议后）。 |
| 2026-07-23 | v0.5 | **Welink 外部版先行 + 设计收敛**：因内部版资料在内网（Claude 不可达）+ Linux 风险，**开发期先用外部版 Welink**（服务端 REST、Linux 可跑、可调研），协议保证后续接内部版/其他工具（新 adapter）。内部版 Linux 风险降级为「后续接入事项」，不阻塞本期。**D0–D5 设计层收敛**：D2（Workflow 形态，复用 TrainingRunner）/D5e（Y + 确认门反馈通道）按推荐默认采纳。 |
