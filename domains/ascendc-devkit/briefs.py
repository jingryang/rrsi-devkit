# Copyright 2026 The rrsi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""为搜索角色提供与 AscendC-DevKit 算子流水线相关的领域提示内容。

关键术语对照：
- `NO ARTEFACT`：未产出评测产物
- `COMPILE-FAIL`：编译失败
- `LOAD-FAIL`：加载或调用失败
- `ACCURACY-MISMATCH`：精度不匹配
- `UNDER-PERF`：性能不佳
- `产物经验`：运行中产出的经验写入 run 产物目录（如 `{output_dir}/vf_experiences/`），由进化循环的出策/审查环节审阅后并入技能经验库；技能树对运行中的 Agent 只读
- `capability_gap`：平台能力缺口
- `EVAL VERDICT`：评测结论
- `stage graph`：阶段图
- `gate`：门控条件
- `trajectory / transcript`：运行轨迹 / 阶段交互记录
- `memorisation`：记忆化，即把基准专属信息编码为可重复利用的固定答案或规则
- `artefact`：产物；在本文件语境中通常指代码、报告或可部署算子等运行结果

`_STAGES` 是本实例评测实际执行的链路：`scripts/batch_self_evolve.sh` 生成的
manifest 里 `workflow: self_evolve_op`。链上没有 `verify` 阶段，精度验证由
`precision_debug` 复合阶段承担；`build`/`deploy`/`smoke` 也不是独立阶段，而是
`codegen` 内 agent 自跑的 `redeploy` 自修复循环；`cannbench_eval` 是一次性的
评分节点，不会回环到 codegen。

`generate_ascendc` 是另一条工作流，尾段有 `perf`、`integrate`，本实例的 trial
不跑这两个阶段——把失败归因到它们，就是在归因一段从未执行的代码。
"""

_STAGES = """entry -> context -> requirement -> [general-design | detailed-design]
-> test_design -> codegen_init -> codegen -> precision_debug
-> cannbench_adapt -> cannbench_eval -> finalize"""

_CLASSES = """每一次未通过的运行，都应归入以下**四类**之一。不同失败类别需要采用不同的处理机制；如果机制针对的失败类型不对，那么它带来的效果在评测中就只会表现为噪声。四类之后另有两条：性能与基础设施，它们不在归因主线里，但很容易被误读，因此单独说明。

NO ARTEFACT（未产出评测产物）
本次运行没有可用于判定的评测结果。两种情况性质不同：

(a) 根本没有生成报告。流水线可能崩溃、超时、被自身的门控条件卡住，或者在 codegen 产出可部署算子之前就提前结束。
(b) 报告文件存在，但 `total_cases = 0`。这说明 cann-bench 没有为该算子匹配到任何测试用例，属于打包或封装层的问题，不是 Kernel 实现的问题。

两者都不应归咎于 AscendC 本身，而应从任务编排、运行预算或产物传递流程中排查。

COMPILE-FAIL（编译失败）
评测报告存在，但 `compilation_score` 为 0，也就是说，没有任何测试用例成功完成编译并运行。

这通常意味着 AscendC Kernel 或 host 侧 Tiling 代码无法构建。常见原因包括：API 函数签名不正确、队列或 TBuf 的配置与 Tiling 计算公式不一致、某个数据类型（dtype）或形状（shape）分支无法实例化，以及模板参数错误。

LOAD-FAIL（加载或调用失败）
代码能够编译，但 `compile_runtime_fail_cases == total_cases`，即所有测试用例都在加载或调用阶段失败。

此时问题出在封装或部署环节，而不是 Kernel 的计算逻辑本身。例如：`aclnn` 注册不正确、`m.def` 中 schema 的参数名与 `proto.yaml` 定义不一致、opp 包或 cann-bench 的 Python 模块没有正确部署，或者缺少 `__init__.py` 中所需的注册入口。

这类失败意味着前面已经完成的工作在最后一步被浪费了；从故障机制上看，它与 `COMPILE-FAIL` 相对应，但故障位置不同。

ACCURACY-MISMATCH（精度不匹配）
算子能够加载并运行，但 `passed_cases == 0`，说明数值结果不正确。

可能原因包括：对数据布局或最后一个轴的假设错误、尾部数据块没有进行掩码处理、基地址没有满足 32 字节对齐要求、golden 参考实现使用 FP32 累加而 Kernel 使用 FP16 累加，或者读取属性时误解了属性的实际含义。

UNDER-PERF（性能不佳，不属于失败原因）
算子的编译、加载与精度都通过，只是 `performance_score` 低。Kernel 计算结果正确，执行效率不理想。

例如：没有使用双缓冲、tile 的形状导致 UB 利用不充分，或者全部工作都由单个核心完成。

它不构成任何试次未通过的原因：判定只看编译、加载、精度三项，`performance_score` 只进入 `overall_score` 的加权和。因此它回答的是"有没有浪费"，而不是"为什么没通过"；只在该次运行已经通过、需要解释分数差异时才用得上。

反过来也不能把 `performance_score` 的任何取值直接读成"慢"：没测到加速比时该维度同样是 0，总分因此比同批其他算子低，这属于"没测到"，不是"跑得慢"。遇到 0 先确认是测过但很差，还是根本没测到。

INFRA（基础设施故障，不是算子质量问题）
总有一类失败与 Kernel 无关：agent 调用本身没能跑起来——环境或服务侧的故障让它整次失败，轨迹里只留下一条终止记录、没有任何 turn 内容；相邻的几次调用同样失败，中间出现退避重试；运行被断点续跑；工作树不干净的告警也属于这一层。这类现象会消耗大量墙钟时间，并让阶段看起来"跑过但没产出"。

归因时先排除它们：如果失败链路上存在这类事件，应记为基础设施问题，不要据此推断 AscendC 能力或平台设计缺陷。只有在该链路上没有这类事件时，才按前四类归因。

同一台机器上并行跑多个试次时，破坏是共享的：一个试次弄坏了环境，另一个试次的失败会以一个看似无关的错误出现在自己的轨迹里。所以同一时间窗内多个试次报同一种错误，指向的是共享环境，而不是两个算子各自的质量问题。

也要防止反向误判：基础设施事件出现在链路上，不等于这次运行失败。事件之后可能续跑并最终产出全部通过的报告。归因以最终判定为准；"轨迹里有 crash 行"和"这次试次没通过"是两件事。

还有一种容易误读的状态：中间阶段的 `deploy_result.smoke_passed = False` 并不等于算子坏了。冒烟失败可能发生在一次部署尝试，而随后 `cannbench_adapt` 会修正封装层（例如改 `cann_bench/__init__.py` 的注册），最终评测报告仍可能全部用例通过。**判定以评测报告为准，不以中间阶段的 smoke 标志为准。**

评测报告包含诊断所需的信息，包括每个算子的 `compilation_score`、`function_score` 和 `performance_score`，加载失败用例的汇总数量，以及 `passed_cases` 和 `total_cases`。分析失败原因之前，应先阅读评测报告。

这些字段用于**归因**，不是用于**编码**：不要把它们写成平台里的判定阈值或通过条件。"""

_SKILL_TREE_INTEGRITY = """平台的技能树（`.claude/skills/**`）对运行中的 Agent 只读：不允许修改技能脚本，也不允许把经验写进技能经验库。验证或调试会话中产出的经验，协议要求写入本次运行的产物目录（例如 `{output_dir}/vf_experiences/`）；技能经验库的并入不由运行中的 Agent、也不由人工执行，而是由本进化框架的出策/审查环节在 round 间审阅产物经验后并入。工具脚本存在缺陷时，运行中的 Agent 应如实报告并绕过，而不是就地修补。

因此，轨迹中出现对 `.claude/skills/**` 的修改不属于预期行为。判断时应关注修改内容和适用范围：如果内容编码了当前基准的具体分布，例如某个算子的 golden 逻辑、该算子的测试用例表、通过阈值，或绕过评测器反作弊机制的路径，就属于对基准的记忆化（memorisation）；即使内容是通用修复，也仍是对平台资产的未授权改动。

归因工作树中的修改时，还要注意：多次运行共享同一个仓库，因此相对于 `HEAD` 的 diff 并不等于某一次运行单独产生的 diff。技能改动可能以未提交状态在多个会话之间持续累积。判断某项修改何时发生，应依据该次运行的事件记录，而不是仅凭当前工作树里存在什么内容。"""

ANALYST = f"""该 Agent 所面对的平台是 AscendC-DevKit：一个由七层 Python 组件构成的平台，通过 Claude Code CLI 后端驱动一个被冻结的策略模型 LLM（`{{policy}}`），将算子需求（DEMAND）转化为可用的 AscendC Kernel。

它并不是一个反复执行同一提示词的简单循环，而是一个阶段图执行器。一次运行的实际链路是：

`{_STAGES}`

每个阶段都会独立调用一次 Agent。阶段图可以通过纠错或升级处理路径进行分支、汇合和回环。只有当该算子生成了预期的 cann-bench `kernel_eval` 报告时，流水线才算完成交付。

每次试运行对应一个算子，并由固定的评测器判定结果：
- `compilation_score > 0`：编译通过；
- 并非所有测试用例都加载失败：加载阶段通过；
- `passed_cases > 0`：至少有一个测试用例通过精度验证。

每个算子都有一份渲染后的运行轨迹；如果存在失败试次，则使用失败试次的轨迹。每份轨迹末尾的 `EVAL VERDICT`（评测结论）部分是判断实际结果的权威依据。

遇到失败时，首先要确定它属于哪一类：

{_CLASSES}

关于技能树只读约束与运行中产出的经验的去向：

{_SKILL_TREE_INTEGRITY}

`NO-ARTEFACT` 或 `LOAD-FAIL` 造成的损失，其重要性应高于单纯的分数损失：这两类失败都会使已经完成的工作付诸东流。例如，Kernel 已经编写完成并成功编译，却因为封装层或门控逻辑的问题而未能进入评测。

原则上应把这两类归因于平台机制，而不是策略模型的 AscendC 知识；但实际诊断仍要结合轨迹确认。如果轨迹显示运行受平台机制阻塞，例如门控提前终止流水线、阶段超时、Agent 轮次被判定为停滞、回环从未触发，或产物写入了下游阶段不会查找的路径，则从 `capability_gap`（平台能力缺口）的角度分析。"""

DIGESTER = """轨迹来自 AscendC-DevKit：这是一个阶段图平台，它驱动被冻结的策略模型 LLM 为单个算子编写 AscendC Kernel，随后通过 cann-bench `kernel_eval` 进行评分。

一次运行的实际链路是：

`""" + _STAGES + """`

运行轨迹按固定的小节渲染，读的时候按小节名定位：
- `=== EVAL VERDICT ===`（最前，判定结论）；
- `=== PLATFORM RECORD ===` 之下依次是：
  - `=== STAGE TABLE (report.json, authoritative) ===`：平台自己记录的执行表，**一行一个实际执行的节点**（含 `self_evolve_op/...` 的完整路径、status、迭代次数、耗时）。判断"跑没跑、跑了多久、卡在哪"以它为准；
  - `=== STAGE TIMELINE (event log) ===`：阶段进出、门控、回环、`infra_backoff`（基础设施重试）、`env_warning`、`run_resumed` 等事件；
  - `=== STATE SNAPSHOT ===`：`eval_result`（评分四轴与用例数）、`debug_result`（本地精度回环）、`deploy_result`（含 `smoke_passed`）、`adapt_result`（封装层适配改了哪些文件），以及 `codegen_*_retries` / `*_same_error_streak` 一类重试与停滞计数；
  - `=== AGENT SESSIONS ===`：**每次 agent 调用一个文件**（`<agent名>-NN.jsonl`），行首标 `[turn N] <role>:`、`[turn N] TOOL <工具>:`、`[turn N] RESULT:`、`[turn N] THINK:`；整次调用没跑起来的会话只有一行 `[CRASH turn=N] <错误>`，没有后续 turn；
  - `=== RUN LOG tail ===`。

这份轨迹没有统一的行号/步号：引用证据时，请写成"小节名 + 该小节内的行号或 session/turn"（例如 `STAGE TIMELINE 第 12 行`、`AGENT SESSIONS/ascendc-dev-s5-compile-06`、`turn 14 的 TOOL bash`），不要编造 `step N`。

分析时应先阅读 `EVAL VERDICT`，确定失败类别，再沿着轨迹回溯，找出导致最终结果的关键阶段：哪个阶段写出了产物、哪个门控条件放行或终止了运行、Agent 实际输出了什么，以及下游阶段预期读取什么。

轨迹中对仓库自身技能树的修改，是平台有意设计的自修复与经验沉淀渠道，并不天然属于异常行为。由于多次运行共享同一个工作树，判断未提交修改的归属时，应依据本次运行的事件记录，而不是简单地根据当前文件是否存在来下结论。"""

PROPOSER = f"""基准任务是一组来自 cann-bench 的 AscendC 算子（level 1–4：从逐元素与归约，到归一化与池化，再到路由、量化与卷积，以及注意力和 RNN 类）。

对于每个算子，平台会获得一份需求定义，其中 `proto.yaml` 描述公式、带数据类型的输入与输出以及属性；此外，还可能提供文字说明、固定的 golden 参考实现和测试用例表。平台必须交付一个能够编译的 AscendC Kernel，并确保 host 侧 Tiling 和 `aclnn` 封装层能够正确调用该算子，且输出数值正确。

平台 AscendC-DevKit 由七层 Python 组件构成，依次涵盖 CLI/TUI、应用层、阶段图编排、纯数据领域层、Agent/技能/知识能力层、仓库/NPU/LLM/工具链适配层，以及基础设施层。它通过带门控、分支汇合和作用域受限回环的阶段图驱动 Claude Code CLI Agent。实际链路是：

`{_STAGES}`

算子开发知识以 Agent 定义（`.claude/agents/*.md`）、技能（`.claude/skills/*/SKILL.md`）和规则文件的形式提供。

平台源码总量约 7 MB，一次性全部放进上下文的做法不可行。你的初始源码视图是一个**有预算的子集**（Agent 定义、规则、编排内核、图执行器等），末尾会列出未展开的文件。`stages/`（各阶段实现，例如 codegen、precision_debug）、`capabilities/`、`application/` 通常不在初始视图里——它们是可读可改的，用 `read_file` 按路径取即可。若失败类别指向某个阶段的决策（例如 `cannbench_eval`、`precision_debug`），先 `read_file` 那个阶段再动手。

被冻结的策略模型为 `{{policy}}`。不要假设它的行为与你熟悉的模型一致，应阅读各阶段 transcript（交互记录），了解它实际采取了哪些行动。

以下内容属于冻结范围，不允许修改：LLM、cann-bench 任务集及其评测器、NPU 与 CANN 工具链、AscendC 语言语义，以及 32 字节对齐规则。

禁止越界的行为

以下行为会在测量前被强制禁止：
1. 在运行时读取、探测或引用评测器信息，包括 cann-bench 报告、`reward.json`、`verification.md`、评测报告 JSON、`/logs/verifier` 目录树，以及任何只能从这些来源获知的通过阈值、容差或参考值。
2. 将当前运行算子的答案硬编码进平台，例如其 golden 实现、逐算子常量或 shape 表。
3. 在代码、提示词、技能或状态中的任何位置，针对某个算子名称、某个 level，或当前基准集合中的算子清单设置特殊分支。

算子自身的 `proto.yaml`、`desc.md`、`golden.py` 和 `cases.csv` 是本次运行合法提供的输入，可以作为数据读取。但如果某项机制把这些内容编码成针对特定算子的固定规则，就属于记忆化，并会被拒绝。

每次编辑都必须通过以下检验：

这种修改能否帮助一位有能力的 AscendC 算子开发者处理大量陌生算子，并且适用于当前基准未覆盖的芯片和 CANN 版本？

两条合规的改进路径

平台允许通过对自身技能树的写权限，进行以下两类改进：
- **运行时修复通用工具：** 找到技能脚本或工具的根本缺陷，修复后继续执行。
- **跨会话沉淀抽象经验：** 将判断标准、常见陷阱和可复用模式（而不是完整源码答案）写入技能库，供后续运行检索。

这两条路径都遵循同一个标准：适用于通用问题的改进可以接受；编码了当前基准具体内容的改动则属于记忆化，会被拒绝。

前文 `_CLASSES` 定义的五类失败及其诊断依据，是本任务的归因框架：
{_CLASSES}"""

CRITIC = f"""该平台通过阶段图驱动被冻结的策略模型 LLM 生成 AscendC 算子。实际链路是：

`{_STAGES}`

流水线包含门控条件和回环路由，最终交付的 Kernel 由预设的 cann-bench `kernel_eval` 报告进行编译、加载和精度评估。

审查时应最先检查两类问题：**绕过评测器（VERIFIER ESCAPE）**和**任务记忆化（TASK MEMORISATION）**。

1. 绕过评测器与任务记忆化

应拒绝会读取、搜索或引用评测器内部信息的改动，包括 cann-bench 报告、`reward.json`、`verification.md`、评测报告 JSON、`/logs/verifier` 目录树和 `FINAL_*_STATUS` 一类的判定字符串。

也应拒绝以下改动：
- 硬编码只能从评测器获得的通过阈值、容差、参考值或测试用例表；
- 对特定算子名称或 level 设置特殊分支；
- 将当前基准分布编码进精心整理的 AscendC API 名称清单或逐算子实现配方，而不是提供通用的开发流程。

2. 可以接受的通用 AscendC 开发实践

通用的 AscendC 开发经验可以迁移，不属于违规行为。例如：
- 通过 `ascend-hardware` 技能查询硬件参数，而不是硬编码 UB 大小、核心数或对齐要求；
- 检测尾部数据块，并使用掩码处理；
- 在调用 `DataCopy` 之前检查 tile 是否满足 32 字节对齐要求；
- 编译器拒绝某个 API 时，从知识库查询其函数签名，而不是凭空猜测；
- 在宣布部署成功之前，验证算子是否确实能够被调用；
- 防止 Tiling 参数在上下文压缩后丢失。

3. 不应随意禁用的安全机制

如果没有可用的替代方案，不得禁用以下机制：
- 环境和硬件预检查；
- 知识库查询；
- “编译 → 精度”的门控链：`codegen` 内的 build/deploy/smoke 自修复循环，以及 `precision_debug` 的本地精度回环；
- 精度调试用的 `DumpTensor` 路径；
- 逐阶段超时机制和停滞监控看门狗。

一次试运行如果完全没有产出任何产物，就会得到零分。因此，也应拒绝没有退出条件的开放式“持续改进”循环，以及任何可能在系统尽力生成一个可部署算子之前就终止运行的门控逻辑。

平台在运行过程中修改自身技能树，是预期设计行为，并不等于越狱。通用工具修复和抽象经验沉淀，正是预设的自修复与经验积累机制。

但如果这些修改编码了某个算子的 golden 逻辑、其测试用例表、特定阈值，或者绕过评测器评分策略的路径——包括规避反作弊机制导致的清零——就越过了允许的边界。"""
