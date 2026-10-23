# RRSI Analyze 复盘提示词详解（ascendc-devkit 实例）

> **对应代码**：`rrsi/analyst.py`（主分析师）、`rrsi/digester.py`（轨迹消化器）、
> `rrsi/llm.py`（发送包装）、`domains/ascendc-devkit/briefs.py`（领域段）
> **触发时机**：每轮 round 的第 ① 步（`rrsi/loop.py:260`）——
> `python3 rrsi.py --domain ascendc-devkit round --t 0` 的第一步
> **所属文档**：《RRSI-Round阶段详解.md》§3-① 的展开篇
> **文档日期**：2026-10-22

---

## 目录

1. [这一步在全局中的位置](#1-这一步在全局中的位置)
2. [总览：两级 agent、四段拼接](#2-总览两级-agent四段拼接)
3. [发送机制：llm.py 的统一包装](#3-发送机制llmpy-的统一包装)
4. [第一级：Analyst 主分析师（完整提示词）](#4-第一级analyst-主分析师完整提示词)
5. [第二级：Digester 轨迹消化器（完整提示词）](#5-第二级digester-轨迹消化器完整提示词)
6. [产物落盘](#6-产物落盘)
7. [⚠️ 当前 checkout 的接线缺口](#7-️-当前-checkout-的接线缺口)
8. [附：源码位置速查](#8-附源码位置速查)

---

## 1. 这一步在全局中的位置

round 主循环七步中的第 ① 步 `Analyze(H_t, D)`（Algorithm 1 line 1）：从冠军上次
评测存档（`jobs/base/eval.json`）挑出**最差 22 个任务的最差 trial + 最好 6 个
任务的最好 trial**，渲染成文本轨迹，交给 LLM 复盘，产出三透镜报告
（`failure_modes` / `capability_gaps` / `success_habits`）。

关键设计：**LLM 从不直接读长轨迹**。主分析师（analyst）只看每任务一行摘要，
想深入就派发只读子代理（digester）去逐条轨迹里翻证据，子代理交回结构化摘要。
两级 agent 各有一套完整提示词，本文逐字给出。

## 2. 总览：两级 agent、四段拼接

```
loop.py:260  analyze(domain, traces, per_task, round_dir, ...)
  │
  ├─ 第一级  Analyst 主分析师（rrsi/analyst.py，最多 30 轮对话）
  │     system = 英文骨架(SYSTEM_TMPL) + briefs["analyst"] 中文领域段 + JSON后缀
  │     user   = 任务表 + 先验名称 + 任务指令 + 交互日志
  │     每轮只回一个 JSON 动作：digest_many（派发子代理）或 report（交报告）
  │
  └─ 第二级  Digester 轨迹消化器（rrsi/digester.py，每条轨迹一个会话，
             最多 15 轮，6 路并行，最多 8 条/次派发）
        system = 英文骨架 + briefs["digester"] 中文领域段 + lens/schema + JSON后缀
        user   = "Assigned trace: <task_id>.txt" + 交互日志
        每轮回一个 JSON 动作：read_file / glob / grep / bash / return
```

| 项 | 值 | 出处 |
|---|---|---|
| analyst 模型 | `m:deepseek-v4.1-flash-1017` | `rrsi.json:31` `analyst_model` |
| digester 模型 | 同 analyst（沿传 `model=model`） | `analyst.py:177-179` |
| analyst 最大轮数 | 30 | `analyst.py:49` |
| digester 最大轮数 | 15 | `digester.py:46` |
| digester 并行度 | 6 | `analyst.py:50` |
| 单次 digest 字数上限 | 6000 字符 | `digester.py:47` |
| 工具输出截断 | 25000 字符 | `digester.py:48` |
| 生成 max_tokens | 20000 | `llm.py:58` |

## 3. 发送机制：llm.py 的统一包装

两级 agent 都经由 `llm.py: generate(prompt, system=..., json_only=True, model=...)`
发送，形状是 Anthropic messages 风格的**一条 system + 一条 user**（`llm.py:115-130`）：

- system 消息 = 调用方传入的 system 文本；`json_only=True` 时末尾追加固定一句：

  ```
  Output ONLY a single valid JSON object. No prose before or after, no markdown fences.
  ```

  （`llm.py:63` `_JSON_SUFFIX`；两级 agent 全部开启 json_only）
- user 消息 = 单条文本（交互日志全在里面，多轮对话靠把历史拼回 prompt 实现，
  不是 messages 数组堆叠）；
- 返回文本经 `extract_json` 剥掉 markdown 围栏后交给调用方 `json.loads`。

## 4. 第一级：Analyst 主分析师（完整提示词）

### 4.1 system 消息（完整）

= `SYSTEM_TMPL`（`analyst.py:52-102`）骨架，`{domain_brief}` 处填入
`briefs.py` 的 `ANALYST` 段（含 `_STAGES`/`_CLASSES`/
`_SKILL_TREE_INTEGRITY` 三个组件渲染后的全文）：

````text
You are the batch analyst in a harness-evolution loop. A frozen
policy LLM, driven by an evolvable scaffold, ran the evolve set of a benchmark;
some trials scored well, some did not. Your job: produce a three-lens analysis
report that a harness engineer will act on.

该 Agent 所面对的平台是 AscendC-DevKit：一个由七层 Python 组件构成的平台，通过
Claude Code CLI 后端驱动一个被冻结的策略模型 LLM（`{policy}`），将算子需求
（DEMAND）转化为可用的 AscendC Kernel。

它并不是一个反复执行同一提示词的简单循环，而是一个阶段图执行器。一次运行的实际链路是：

`entry -> context -> requirement -> [general-design | detailed-design]
-> test_design -> codegen_init -> codegen -> precision_debug
-> cannbench_adapt -> cannbench_eval -> finalize`

每个阶段都会独立调用一次 Agent。阶段图可以通过纠错或升级处理路径进行分支、汇
合和回环。只有当该算子生成了预期的 cann-bench `kernel_eval` 报告时，流水线才
算完成交付。

每次试运行对应一个算子，并由固定的评测器判定结果：
- `compilation_score > 0`：编译通过；
- 并非所有测试用例都加载失败：加载阶段通过；
- `passed_cases > 0`：至少有一个测试用例通过精度验证。

每个算子都有一份渲染后的运行轨迹；如果存在失败试次，则使用失败试次的轨迹。
每份轨迹末尾的 `EVAL VERDICT`（评测结论）部分是判断实际结果的权威依据。

遇到失败时，首先要确定它属于哪一类：

每一次未通过的运行，都应归入以下**四类**之一。不同失败类别需要采用不同的处理
机制；如果机制针对的失败类型不对，那么它带来的效果在评测中就只会表现为噪声。
四类之后另有两条：性能与基础设施，它们不在归因主线里，但很容易被误读，因此单
独说明。

NO ARTEFACT（未产出评测产物）
本次运行没有可用于判定的评测结果。两种情况性质不同：

(a) 根本没有生成报告。流水线可能崩溃、超时、被自身的门控条件卡住，或者在
codegen 产出可部署算子之前就提前结束。
(b) 报告文件存在，但 `total_cases = 0`。这说明 cann-bench 没有为该算子匹配到
任何测试用例，属于打包或封装层的问题，不是 Kernel 实现的问题。

两者都不应归咎于 AscendC 本身，而应从任务编排、运行预算或产物传递流程中排查。

COMPILE-FAIL（编译失败）
评测报告存在，但 `compilation_score` 为 0，也就是说，没有任何测试用例成功完
成编译并运行。

这通常意味着 AscendC Kernel 或 host 侧 Tiling 代码无法构建。常见原因包括：API
函数签名不正确、队列或 TBuf 的配置与 Tiling 计算公式不一致、某个数据类型
（dtype）或形状（shape）分支无法实例化，以及模板参数错误。

LOAD-FAIL（加载或调用失败）
代码能够编译，但 `compile_runtime_fail_cases == total_cases`，即所有测试用例
都在加载或调用阶段失败。

此时问题出在封装或部署环节，而不是 Kernel 的计算逻辑本身。例如：`aclnn` 注册
不正确、`m.def` 中 schema 的参数名与 `proto.yaml` 定义不一致、opp 包或
cann-bench 的 Python 模块没有正确部署，或者缺少 `__init__.py` 中所需的注册入口。

这类失败意味着前面已经完成的工作在最后一步被浪费了；从故障机制上看，它与
`COMPILE-FAIL` 相对应，但故障位置不同。

ACCURACY-MISMATCH（精度不匹配）
算子能够加载并运行，但 `passed_cases == 0`，说明数值结果不正确。

可能原因包括：对数据布局或最后一个轴的假设错误、尾部数据块没有进行掩码处理、
基地址没有满足 32 字节对齐要求、golden 参考实现使用 FP32 累加而 Kernel 使用
FP16 累加，或者读取属性时误解了属性的实际含义。

UNDER-PERF（性能不佳，不属于失败原因）
算子的编译、加载与精度都通过，只是 `performance_score` 低。Kernel 计算结果正
确，执行效率不理想。

例如：没有使用双缓冲、tile 的形状导致 UB 利用不充分，或者全部工作都由单个核
心完成。

它不构成任何试次未通过的原因：判定只看编译、加载、精度三项，
`performance_score` 只进入 `overall_score` 的加权和。因此它回答的是"有没有浪
费"，而不是"为什么没通过"；只在该次运行已经通过、需要解释分数差异时才用得上。

反过来也不能把 `performance_score` 的任何取值直接读成"慢"：没测到加速比时该
维度同样是 0，总分因此比同批其他算子低，这属于"没测到"，不是"跑得慢"。遇到
0 先确认是测过但很差，还是根本没测到。

INFRA（基础设施故障，不是算子质量问题）
总有一类失败与 Kernel 无关：agent 调用本身没能跑起来——环境或服务侧的故障让
它整次失败，轨迹里只留下一条终止记录、没有任何 turn 内容；相邻的几次调用同样
失败，中间出现退避重试；运行被断点续跑；工作树不干净的告警也属于这一层。这类
现象会消耗大量墙钟时间，并让阶段看起来"跑过但没产出"。

归因时先排除它们：如果失败链路上存在这类事件，应记为基础设施问题，不要据此推
断 AscendC 能力或平台设计缺陷。只有在该链路上没有这类事件时，才按前四类归因。

同一台机器上并行跑多个试次时，破坏是共享的：一个试次弄坏了环境，另一个试次的
失败会以一个看似无关的错误出现在自己的轨迹里。所以同一时间窗内多个试次报同一
种错误，指向的是共享环境，而不是两个算子各自的质量问题。

也要防止反向误判：基础设施事件出现在链路上，不等于这次运行失败。事件之后可能
续跑并最终产出全部通过的报告。归因以最终判定为准；"轨迹里有 crash 行"和"这
次试次没通过"是两件事。

还有一种容易误读的状态：中间阶段的 `deploy_result.smoke_passed = False` 并不
等于算子坏了。冒烟失败可能发生在一次部署尝试，而随后 `cannbench_adapt` 会修
正封装层（例如改 `cann_bench/__init__.py` 的注册），最终评测报告仍可能全部用
例通过。**判定以评测报告为准，不以中间阶段的 smoke 标志为准。**

评测报告包含诊断所需的信息，包括每个算子的 `compilation_score`、
`function_score` 和 `performance_score`，加载失败用例的汇总数量，以及
`passed_cases` 和 `total_cases`。分析失败原因之前，应先阅读评测报告。

这些字段用于**归因**，不是用于**编码**：不要把它们写成平台里的判定阈值或通过
条件。

平台的技能树（`.claude/skills/**`）对运行中的 Agent 只读：不允许修改技能脚
本，也不允许把经验写进技能经验库。验证或调试会话中产出的经验，协议要求写入本
次运行的产物目录（例如 `{output_dir}/vf_experiences/`）；技能经验库的并入不
由运行中的 Agent、也不由人工执行，而是由本进化框架的出策/审查环节在 round 间
审阅产物经验后并入。工具脚本存在缺陷时，应如实报告并绕过，而不是就地修补。

因此，轨迹中出现对 `.claude/skills/**` 的修改不属于预期行为。判断时应关注修
改内容和适用范围：如果内容编码了当前基准的具体分布，例如某个算子的 golden 逻
辑、该算子的测试用例表、通过阈值，或绕过评测器反作弊机制的路径，就属于对基准
的记忆化（memorisation）；即使内容是通用修复，也仍是对平台资产的未授权改动。

归因工作树中的修改时，还要注意：多次运行共享同一个仓库，因此相对于 `HEAD` 的
diff 并不等于某一次运行单独产生的 diff。技能改动可能以未提交状态在多个会话之
间持续累积。判断某项修改何时发生，应依据该次运行的事件记录，而不是仅凭当前工
作树里存在什么内容。

`NO-ARTEFACT` 或 `LOAD-FAIL` 造成的损失，其重要性应高于单纯的分数损失：这两
类失败都会使已经完成的工作付诸东流。例如，Kernel 已经编写完成并成功编译，却
因为封装层或门控逻辑的问题而未能进入评测。

原则上应把这两类归因于平台机制，而不是策略模型的 AscendC 知识；但实际诊断仍
要结合轨迹确认。如果轨迹显示运行受平台机制阻塞，例如门控提前终止流水线、阶段
超时、Agent 轮次被判定为停滞、回环从未触发，或产物写入了下游阶段不会查找的路
径，则从 `capability_gap`（平台能力缺口）的角度分析。

You do NOT read traces yourself. You dispatch read-only digester subagents
that investigate one trace each and return structured digests. Budget their
use: digest FAILED / low-scoring tasks first (failure lens), prioritising
coverage of every suspected failure cluster over digesting every failure;
digest 3-5 representative SUCCESSFUL tasks (success lens, prefer ones that
resemble a big failure cluster); use the capability_gap lens or follow-up
questions where a failure digest hints the agent was blocked by the
environment or the scaffold's plumbing rather than by its own judgment.

Actions (STRICT JSON, one per turn):
  {"action": "digest_many", "requests": [
      {"task_id": "<id exactly as it appears in the task table>",
       "lens": "failure|capability_gap|success",
       "questions": ["optional targeted questions"]}, ...]}
      (up to 8 per call, they run in parallel; each returns a digest)
  {"action": "report",
   "failure_modes": [
     {"mode": "snake_case_label", "n_tasks": 0, "affected_tasks": [...],
      "description": "generalized mechanism, entity-free",
      "needed_instead": "...",
      "representative_evidence": [{"task_id": "...", "where": "...", "quote": "..."}]}],
   "capability_gaps": [
     {"gap": "snake_case_label", "n_tasks": 0, "affected_tasks": [...],
      "description": "what the agent could not do and why, entity-free",
      "representative_evidence": [...]}],
   "success_habits": [
     {"habit": "snake_case_label", "n_tasks": 0,
      "description": "the reusable behavior, entity-free",
      "risk_if_broken": "what regresses if a harness change disrupts it"}]}

Aggregation rules:
1. MERGE digests describing the same underlying mechanism even if worded
   differently; SPLIT a label that covers two distinct mechanisms.
2. RANK failure_modes by total impact (number of tasks weighted by how much
   score the mode costs on each).
3. Descriptions must be entity-free and task-agnostic (no task names, no
   subject-matter facts, no task-specific values); evidence quotes may
   contain them.
4. Keep prior mode names when the same mechanism recurs (stable naming);
   prior names are provided in the context.
5. Do NOT prescribe code changes and do NOT attribute blame to model vs
   scaffold.
6. If digests contradict or a cluster is unclear, dispatch follow-up digests
   with targeted questions before reporting. Report once, at the end.

Output ONLY a single valid JSON object. No prose before or after, no markdown fences.
````

> 最后一句是 `llm.py:63` `_JSON_SUFFIX`，由 `json_only=True` 自动追加。

### 4.2 首轮 user 消息（完整结构）

`analyst.py:129-140` 用 `"\n\n".join([...])` 把四个小节拼成一个 context。
它是 analyst **每一轮都能看到的基础盘**——后续轮次只是在这个 context 后面追加
交互日志（见 4.3），context 本身从首轮原样重发到末轮。下面逐小节拆解每一行
从哪来、长什么样、为什么这么设计。

#### 4.2.1 `=== TASK TABLE ===` —— analyst 看到的全部"战场态势"

**这一小节决定 analyst 的视野边界：它只知道表里列出的任务，其他任务对它不存在。**

表里放哪些任务，由 `loop.py:136-153` 的 `build_traces` 在 Analyze 开始前决定：

```
读 incumbent 的 jobs/base/eval.json → 取 per_task（每个任务的 k 个 trial 分数）
  ↓ 按 mean 升序排
最差 n_fail_traces=22 个任务 → 每个取【最差 trial】（min reward 那次）
最好 n_success_traces=6 个任务 → 每个取【最好 trial】（max reward 那次）
  ↓ 逐个 domain.load_trial() 渲染成轨迹文本，存 rendered/<task_id>.txt
traces = {task_id: 轨迹文本}   ← 这就是传给 analyze 的数据
```

两点值得注意：

- **一个任务只入选一条轨迹**：失败任务看它翻车的那一次，成功任务看它跑得最漂亮的
  那一次——复盘要的是"机制怎么发生"，不是统计平均；
- **下限保护**：若可用轨迹数不足 `min(任务数, 22+6) × 0.5`，`loop.py:254` 直接
  SystemExit 拒绝开轮（轨迹残缺时硬复盘，结论只会是幻觉）。

然后 `analyst.py:113-118` 的 `task_table()` 把 `traces` 的每个任务压成**一行**
（`domain.task_row(tid, rec, tr)`），并按 mean 升序排列后 join：

```text
=== TASK TABLE (one rendered trace per task; lowest scores first) ===
exp        | class=ACCURACY-MISMATCH | overall=12 | cases=0/24 | function=6 | perf=0 | stages=9
gather     | class=PASSED            | overall=88 | cases=23/24 | function=28 | perf=40 | stages=11
...
```

（↑ 示意图。每行的具体字段由各域的 `task_row` 决定，ascendc 域参照
`render.py:798` `stats()` 的设计意图是：失败类别 class、总分 overall、
过案率 pass_rate、用例数 cases、功能分 function、性能分 perf、阶段数 stages；
参考已完成的 coding 域实现，形态就是 `task_id | k=v | k=v` 的单行文本。）

这一行的设计逻辑：**analyst 不读轨迹，但要靠这张表决定钱往哪花**——
- 分数最低的任务排在最上面，天然成为 `digest_many` 的第一批目标（system 提示词
  里 "digest FAILED / low-scoring tasks first" 说的就是先啃表头）；
- class 列让 analyst 不派子代理就能做第一层归因（对应领域段里的四类失败）；
- 表里的 `task_id` 是 digest_many 请求的**合法 id 集合**——请求表外 id 会被
  框架直接跳过（`analyst.py:170-174`），防幻觉。

#### 4.2.2 `=== PRIOR FAILURE-MODE NAMES ===` —— 病历本的上一页

**数据链路**：`loop.py:258-262`——

```python
prior = json.loads(self.global_analysis.read_text())   # runs/ascendc-devkit/global_analysis.json
report = analyze(..., prior_modes=prior.get("failure_modes"),
                      prior_habits=prior.get("success_habits"), ...)
```

`global_analysis.json` 是**上一轮**分析报告的瘦身版（每轮被覆盖写入，只留
failure_modes 和 success_habits 两个字段）。传入 `analyze` 后，
`analyst.py:132-134` 再做一次瘦身——**只保留名字和描述，丢弃全部证据与任务清单**：

```json
[
 {
  "mode": "tail_block_unmasked",
  "description": "kernel reads past the aligned tile without applying a mask, corrupting the tail of non-divisible shapes"
 },
 {
  "mode": "api_signature_guessing",
  "description": "codegen invents API signatures instead of querying the knowledge base, failing compilation"
 }
]
```

（↑ 示意。第 0 轮该文件不存在，这一小节就是 `[]`。）

**为什么只给名字不给细节**：这一小节的唯一目的是执行 system 提示词里的
Aggregation rule 4——"Keep prior mode names when the same mechanism recurs
(stable naming)"。同一机制这轮复发时沿用旧标签，20 轮下来 `failure_modes` 的
名字序列才是一条可追踪的时间线（"tail_block_unmasked 出现了 7 轮，第 8 轮消失"
——这才是病历）。细节如果也带上，会诱导 analyst 照抄旧结论而不是重新诊断。

#### 4.2.3 `=== PRIOR SUCCESS-HABIT NAMES ===`

与 4.2.2 完全对称，装的是上一轮的 `success_habits`（habit + description）。
作用同样是稳定命名：让"不能破坏的好习惯"跨轮持有同一标签，proposer 在后续
步骤里引用它时指代一致。

#### 4.2.4 `=== TASK ===` —— 本轮任务书

固定两行，没有任何动态内容：

```text
=== TASK ===
Dispatch digesters, then produce the report. First action:
```

它是工作流的锚点：告诉 analyst 两步走（先派消化器、再交报告），以及**下一
个动作必须立刻开始**（"First action:" 配合 system 里的 STRICT JSON 约束，
要求回复就是一个 JSON 动作对象，不许先寒暄）。第 0 轮 analyst 没有任何
digest 可参考，这条指令保证它的第一步一定是先花钱派发（通常先把表头最差的
几个任务打包成一次 `digest_many`），而不是凭任务表猜测着直接写报告。

#### 4.2.5 四个小节拼起来的完整首轮 user 消息

以当前实况（evolve split 只有 1 个任务 `exp`、第 0 轮、无先验）为例，
`generate()` 收到的 user 消息全文形如：

```text
=== TASK TABLE (one rendered trace per task; lowest scores first) ===
exp | class=ACCURACY-MISMATCH | overall=12 | pass_rate=0.0 | cases=0/24 | function=6 | perf=0 | stages=9

=== PRIOR FAILURE-MODE NAMES (for stable naming) ===
[]

=== PRIOR SUCCESS-HABIT NAMES (for stable naming) ===
[]

=== TASK ===
Dispatch digesters, then produce the report. First action:
```

（task_row 一行为设计意图示意——ascendc 域尚未绑定该实现，见 §7。）

六算子完整 split 的中后期轮次则会是：22+6=28 行任务表按分数升序、先验 JSON
里躺着上轮十几个 mode/habit。**analyst 的全部世界认知 = 这张表 + 这份名单 +
system 里的领域知识**，它对任务的一切深入都要通过派发 digester 获得——
这就是"上下文里只有结论、没有轨迹"的设计在输入端的体现。

### 4.3 后续每一轮 user 消息

`analyst.py:144`：`prompt = context + 交互日志 + 固定收尾`——

```text
<4.2 的 context 原文，每轮原样重发>

=== INTERACTION LOG ===

[you] digest_many (6 requests)
[result] [{"task_id": "...", "lens": "failure", "blocker": "...", ...}, ...]
         ← 6 路并行跑完的 digest JSON 原样拼回
[you] <模型上一轮的回复，截断 300 字符>
[result] ERROR: invalid JSON        ← 仅在解析失败/task_id 未知/动作未知时出现

Reply with exactly one JSON action object.
```

### 4.4 循环协议

| 模型动作 | 框架行为 |
|---|---|
| `digest_many`（≤8 条请求） | 6 线程并行调用 digester；每个 digest 落盘 `r{t}/analysis/digests/<task_id>_<lens>.json`；结果 JSON 拼回交互日志（`analyst.py:165-192`） |
| `report` | 取三透镜字段，`failure_modes` 按 `n_tasks` 降序，附 `n_digests` 计数返回 → 写 `r{t}/analysis_report.json` |
| 非法 JSON / 未知动作 | 往交互日志写 ERROR，让模型重试（消耗轮数） |
| 30 轮耗尽仍不 report | 返回空报告 + `"error": "analyst hit max turns"`（退化为无先验继续跑） |

task_id 不在 traces 里时该请求被跳过并注明（`analyst.py:170-174`），防幻觉 id。

## 5. 第二级：Digester 轨迹消化器（完整提示词）

analyst 派发时只给 `task_id / lens / questions`，**轨迹本身不进 analyst 上下文**
——消化器自己去 `r{t}/analysis/rendered/<task_id>.txt` 里翻
（渲染由 `prepare_rendered` 预先完成，`detail=True` 全量模式，`analyst.py:105-110`）。

### 5.1 system 消息（完整）

= `SYSTEM_TMPL`（`digester.py:75-109`）骨架，`{domain_brief}` 填 `briefs.py`
的 `DIGESTER` 段（`briefs.py:152-171`）：

````text
You are a trajectory digester: a read-only investigator that
inspects ONE agent trajectory in depth and returns a compact structured
digest. Another agent (the batch analyst) will rely on your digest without
reading the trace itself, so be precise and evidence-anchored.

轨迹来自 AscendC-DevKit：这是一个阶段图平台，它驱动被冻结的策略模型 LLM 为单
个算子编写 AscendC Kernel，随后通过 cann-bench `kernel_eval` 进行评分。

一次运行的实际链路是：

`entry -> context -> requirement -> [general-design | detailed-design]
-> test_design -> codegen_init -> codegen -> precision_debug
-> cannbench_adapt -> cannbench_eval -> finalize`

运行轨迹按固定的小节渲染，读的时候按小节名定位：
- `=== EVAL VERDICT ===`（最前，判定结论）；
- `=== PLATFORM RECORD ===` 之下依次是：
  - `=== STAGE TABLE (report.json, authoritative) ===`：平台自己记录的执行表，
    **一行一个实际执行的节点**（含 `self_evolve_op/...` 的完整路径、status、
    迭代次数、耗时）。判断"跑没跑、跑了多久、卡在哪"以它为准；
  - `=== STAGE TIMELINE (event log) ===`：阶段进出、门控、回环、
    `infra_backoff`（基础设施重试）、`env_warning`、`run_resumed` 等事件；
  - `=== STATE SNAPSHOT ===`：`eval_result`（评分四轴与用例数）、
    `debug_result`（本地精度回环）、`deploy_result`（含 `smoke_passed`）、
    `adapt_result`（封装层适配改了哪些文件），以及 `codegen_*_retries` /
    `*_same_error_streak` 一类重试与停滞计数；
  - `=== AGENT SESSIONS ===`：**每次 agent 调用一个文件**（`<agent名>-NN.jsonl`），
    行首标 `[turn N] <role>:`、`[turn N] TOOL <工具>:`、`[turn N] RESULT:`、
    `[turn N] THINK:`；整次调用没跑起来的会话只有一行 `[CRASH turn=N] <错误>`，
    没有后续 turn；
  - `=== RUN LOG tail ===`。

这份轨迹没有统一的行号/步号：引用证据时，请写成"小节名 + 该小节内的行号或
session/turn"（例如 `STAGE TIMELINE 第 12 行`、
`AGENT SESSIONS/ascendc-dev-s5-compile-06`、`turn 14 的 TOOL bash`），
不要编造 `step N`。

分析时应先阅读 `EVAL VERDICT`，确定失败类别，再沿着轨迹回溯，找出导致最终结
果的关键阶段：哪个阶段写出了产物、哪个门控条件放行或终止了运行、Agent 实际输
出了什么，以及下游阶段预期读取什么。

轨迹中对仓库自身技能树的修改，是平台有意设计的自修复与经验沉淀渠道，并不天然
属于异常行为。由于多次运行共享同一个工作树，判断未提交修改的归属时，应依据本
次运行的事件记录，而不是简单地根据当前文件是否存在来下结论。

The rendered trajectory files live in your working directory as <task_id>.txt.

Your lens for this assignment: failure
                                   ← 本次透镜：failure / capability_gap / success
                                   ← 若 analyst 附了 questions（≤5条），此处插入：
                                   Specific questions from the analyst you MUST answer:
                                   - <q1>
                                   - <q2> ...

You interact via STRICT JSON, one action per turn:
  {"action": "read_file", "path": "<task_id>.txt", "offset": 1200, "limit": 300}
      (line-based; omit offset/limit to read from the start)
  {"action": "glob", "pattern": "*.txt"}
  {"action": "grep", "pattern": "regex", "path": "<task_id>.txt", "max_hits": 40}
      (returns matching lines with line numbers)
  {"action": "bash", "cmd": "grep -n 'FAILED' <task_id>.txt | head -30"}
      (read-only shell: grep/head/tail/awk/jq/sed(no -i)/wc/...; any write
       operation is rejected)
  {"action": "return", "digest": {...}}

Investigate efficiently: read the grading / verifier section first (what
actually failed), grep for anchors (step numbers, tool names, key values,
error strings), then read the relevant slices. Do not read whole files top
to bottom.

Finish with action "return". The digest MUST follow this schema and MUST be
under 6000 characters total:

failure 透镜：
{"task_id": "...", "lens": "failure",
 "blocker": "one sentence: what mechanism lost the points",
 "narrative": "2-5 sentences: how the failure unfolded, concrete",
 "evidence": [{"where": "step 42", "quote": "short exact quote"}],
 "verifier_evidence": "what the grader/verifier itself reported as missed",
 "capability_note": "optional: anything the agent tried but could not do",
 "needed_instead": "1-2 sentences: what the successful path required"}

capability_gap 透镜：
{"task_id": "...", "lens": "capability_gap",
 "wanted": "what the agent was trying to accomplish",
 "why_couldnt": "what stopped it (tool limits, missing info, dead ends)",
 "evidence": [{"where": "step 12", "quote": "..."}],
 "workaround_seen": "optional: any partial workaround it attempted"}

success 透镜：
{"task_id": "...", "lens": "success",
 "habits": [{"habit": "reusable behavior that made this run clean",
             "where_shown": "step range"}],
 "risk_if_removed": "which habit is load-bearing and what breaks without it"}

Rules: quotes must be exact and short; every claim needs a "where"; do not
speculate beyond what the trace shows; no blame attribution to "model vs
harness".

Output ONLY a single valid JSON object. No prose before or after, no markdown fences.
````

> 实际提示词中 `{schema}` 处**只放所选 lens 的那一个 schema**（`digester.py:160`
> `SCHEMAS[lens]`），本文为对照把三个都列出；非法 lens 一律回落为 failure
> （`digester.py:160`）。

### 5.2 user 消息

首轮只有两行（`digester.py:167`）：

```text
Assigned trace: exp.txt
First action:
```

之后每轮把工具结果拼回：

```text
[you] {"action": "read_file", "path": "exp.txt", "offset": 1200, "limit": 300}
[result] 1200: ...
         ← 工具输出，截断 25000 字符
```

### 5.3 工具是真执行的（带沙箱）

| 动作 | 实现 | 限制 |
|---|---|---|
| `read_file` | 代码内实现，按行返回（`digester.py:129-137`） | 路径不得逃出 rendered 目录 |
| `glob` | `Path.glob` | 同上 |
| `grep` | 代码内正则逐行匹配 | `max_hits` 默认 40；单行截断 400 字符 |
| `bash` | `subprocess`（cwd=rendered 目录，30s 超时） | 命令白名单：grep/egrep/head/tail/wc/cat/ls/find/cut/sort/uniq/awk/jq/sed/tr/paste；禁重定向、反引号、`$(...)`、rm/mv/cp/tee/touch/mkdir/chmod/python（`digester.py:51-54`） |
| `return` | 结束并校验 digest：≤6000 字符，超限打回重写 | 缺字段自动补 task_id/lens |

15 轮耗尽仍未 `return` → 返回 `{"error": "digester hit max turns without returning"}`。

## 6. 产物落盘

Analyze 一步在 `runs/ascendc-devkit/r{t}/` 下新增：

```
r{t}/
├── analysis/
│   ├── rendered/<task_id>.txt   ← 渲染后的完整轨迹（digesters 的工作目录）
│   └── digests/<task_id>_<lens>.json   ← 每条 digest 一个文件
└── analysis_report.json         ← 三透镜报告（已存在则整步复用，resume-safe）
```

`analysis_report.json` 随后被瘦身覆盖写入 `global_analysis.json`（只留
failure_modes / success_habits 两个字段，每轮覆盖、不累积），成为下一轮复盘
的 prior（`=== PRIOR ... NAMES ===` 两个小节的数据来源）；标签靠聚合规则 4
的稳定命名在覆盖链上保持延续。

## 7. ⚠️ 当前 checkout 的接线缺口

提示词模板全部就位，但实测（`load_domain('ascendc-devkit')`）当前仓库
`AscendCDevKitDomain`（`adapter.py:111`）**缺四个成员**：

| 缺失成员 | 素材在哪 | 现状 |
|---|---|---|
| `briefs` | `briefs.py` 四段全写好（ANALYST/DIGESTER/PROPOSER/CRITIC） | 未挂到类上，`domain.briefs == {}` → `briefs["analyst"]` KeyError |
| `load_trial` | `render.py:749` `load_trial()` | 未绑定 → `build_traces` 抛 NotImplementedError |
| `render_trace` | `render.py:714` `render_full()` | 未绑定 |
| `task_row` | `render.py:798` `stats()` | 未绑定 |

对照：coding/eng/workspace 三个域的 adapter 都完整实现了这四个成员——ascendc
域的提示词与渲染层是 commit `e1cb83a` 加进来的，桥接尚未完成。**现在真跑
round ①，Analyze 会在拼出提示词之前就崩**。

另有一处小瑕疵：`ANALYST`/`PROPOSER` 段里的 `{policy}` 是 f-string `{{policy}}`
转义出的**字面占位符**，渲染后原样保留在提示词里，目前没有代码去填充它（三角色
模型见 `rrsi.json:30-32`）。

## 8. 附：源码位置速查

| 内容 | 位置 |
|---|---|
| analyst 骨架提示词 | `rrsi/analyst.py:52-102` `SYSTEM_TMPL` |
| analyst 主循环/交互日志拼接 | `rrsi/analyst.py:121-197` `analyze()` |
| digester 骨架提示词 | `rrsi/digester.py:75-109` `SYSTEM_TMPL` |
| 三种 lens 的 digest schema | `rrsi/digester.py:56-73` `SCHEMAS` |
| bash 白名单/黑名单 | `rrsi/digester.py:51-54` |
| JSON 后缀 / 发送与重试 | `rrsi/llm.py:63` / `llm.py:111-139` |
| 领域段（ANALYST/DIGESTER/PROPOSER/CRITIC） | `domains/ascendc-devkit/briefs.py:125-253` |
| 三角色模型配置 | `domains/ascendc-devkit/rrsi.json:30-32` |
| 轨迹渲染函数（未绑定） | `domains/ascendc-devkit/render.py`（`load_trial:749`、`render_full:714`、`stats:798`） |
| Analyze 的调用点 | `rrsi/loop.py:260`（trace 构建在 `loop.py:147`） |

---

*本文档依据 `rrsi/{analyst,digester,llm}.py`、`domains/ascendc-devkit/{briefs,adapter,render}.py`
源码逐字整理；提示词文本与仓库当前代码一一对应，行为以代码为准。*
