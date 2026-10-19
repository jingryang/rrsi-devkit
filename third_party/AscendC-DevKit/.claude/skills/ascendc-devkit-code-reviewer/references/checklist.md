# Review Checklist — D1–D8

本文件是 review 的核心判据。每条 = 「查什么 + **怎么查（机械信号）** + 违反信号 + 默认严重度」。权威源是 CLAUDE.md；本表是其 review 视角的蒸馏，不是 CLAUDE.md 的替代。

> **机械化原则**：`怎么查` 列必须给 grep 命令或明确检查步骤，不得只写结论性描述。grep 是在**改动文件 / 相关 skill 目录**内执行，命中后由人复核确认（信号非绝对证明）。
>
> **误报过滤**：grep 命中后按来源过滤——①排除 reviewer 自身目录（如本 skill 的示例文本）；②按 code/skill/doc 分作用域扫（§1.7 只扫 `src/`、§2.6 只扫对应 skill 目录）；③**docstring 里陈述反模式**（如 `no ~/.claude`、`# 不留兼容`）是**合规声明**非违规。**命中 ≠ 违规**，必须读上下文确认。
>
> **审核原则（recall > precision）**：**宁可错报，不可漏报**。发现疑似问题就提（在 finding 里标注不确定性），由人裁决；**不得因「不确定」「可能没问题」而放过**。一条 finding 被复核为误报，是可接受代价；一个真实问题被漏掉，是 review 失职。所有问题从严审核。

## 严重度校准
- **blocker**：违反硬不变式（跨层依赖 / State 可变 / §2.5 新旧并存 / §3.4 掩盖失败 / 测试不过 / §1.7 外部路径 / §2.1 框架耦合 / §1.12 具体算子耦合 / §1.13 覆盖 golden）。
- **major**：偏离原则但不致崩（缺真实链路 ST、方案只兜底未治根因、缺加载期校验）。
- **minor**：可改进（命名 / 注释 / 小重复）。
- **nit**：风格。

> blocker 级不得因「能跑通」降级；其余可按上下文调整，但要在 finding 里写明理由。

## 启用条件
D1/D3/D5/D6/D7/D8 常驻；**D2** 仅 PR 触及 `.claude/skills/**`；**D4** 仅 PR 触及 `.claude/agents/**` 或 `src/ascendc_devkit/orchestration/**`。

---

## D1 — 设计原则符合性（CLAUDE.md §1）｜常驻

| 检查项 | 怎么查（机械信号） | 违反信号 | 默认 |
|---|---|---|---|
| §1.1 七层向下依赖 | 对改动 `.py`：`grep -nE '^\s*(from\|import) ' <file>`，核对 import 目标模块是否在「当前层允许依赖的下游」集合内 | 跨层 / 反向依赖（下层 import 上层、domain import application/orchestration、orchestration 反向 import application 之外） | blocker |
| §1.1 Stage 标准入口 | `grep -nE 'def (actions\|transition)\(' <stage_file>` | Stage 子类缺 `actions`/`transition` 标准签名、自造扩展口绕过 state | major |
| §1.1 State 不可变 | `grep -nE '@dataclass' <state_file>` 看是否 `frozen=True`；`grep -nE '\bstate\.\w+\s*=' <file>` 找直接赋值 | State 非 frozen；直接 `state.x = y`（应走 `with_updates`） | blocker |
| §1.1 Event Sourcing | 确认 `events.jsonl` 仍被写入/读取作为运行历史权威 | 引入旁路状态源、绕过 events.jsonl | major |
| §1.3 加载期校验 | 看 skill/工具/权限/manifest 配置加载处是否有校验+告警（loader/import 期） | 合法性问题推迟到运行期才炸 | major |
| §1.3 校验在每个 reader | 对改动涉及的控制文件（control.json / checkpoint.json 等）：`grep -rnE 'json\.load\|read_text\|read()' src/` 列出所有 reader；加载期校验须在每个 reader（或经集中包装）发生 | 校验只在一个 reader，其它裸读路径绕过 | major |
| §1.3 docstring 承诺兑现 | 代码 docstring 若出现校验/解析/加载承诺（如 `SchemaLoader.load_contract` / `parse(raw)` / "load-time validation"），核对同 PR 有等价调用或 L4 §10 明确撤回 | 承诺了校验但代码无实现且无撤回记录 | major |
| §1.4 不留兼容 | `grep -rnE '@deprecated\|_legacy\|_old\b\|compat\|backward\|migrate\|迁移\|if .*(LEGACY\|OLD_)\|TODO.*(remove\|delete\|deprecat)' src/` | 残留 alias、`if legacy` 分支、`@deprecated`、旧 schema 兼容 | blocker |
| §1.5 资源清单 | `grep -rnE "['\"][^'\"]*\.(json\|yaml\|yml\|md)['\"]" src/` 看资源路径是否走清单 / 是否硬编码 | 硬编码资源路径；算子知识写进 `.py` | major |
| §1.6 依赖注入 | 业务层应持 `Protocol`/`ABC`：`grep -nE 'class .*Protocol\|ABC'`；确认不直接 import 具体 adapter | 业务层直接 new/import 具体实现 | major |
| §1.7 仓自闭环 | `grep -rnE 'Path\.home\|expanduser\|/home/\|/root/\|~/\.claude\|\$HOME' src/` | 命中外部路径 | blocker |
| §1.9 芯片命名 | `grep -rnE 'ascend910[a-z_0-9]*\|ascend950\|soc_version' src/`，确认字面量都经 `domain/chip.py::to_soc_version` | 散落 soc_version 字面量、另立词表 | major |
| §1.10 横切控制流判据用业务语义 | 改动涉及超时/重试/放行/熔断/配额等横切控制流时，核对判据来源：`grep -rnE 'uninterruptible\|可重试\|retryable\|豁免\|timeout.*skip\|skip.*timeout' <file>`；判据应是 stage/操作**显式声明的业务语义**（如 `uninterruptible`、操作声明「可重试」），不是「是否 spawn / 调 API / 含 subprocess / 触发 IO」等机制特征隐式代理 | 用机制特征隐式代理判据，语义相反的单元被静默误判（如不 spawn 的非收尾重型 stage 被超时拦）；漏声明靠运行期静默误判兜 | major |
| §1.11 诊断链路看实际产出 | 新增可达性探活/自检/诊断代码：判据是否取真实链路产出（agent chars>0 / tool 调用 / SDK 请求日志），而非 curl 返回码直判；与「系统同凭证正常工作」强反证矛盾时是否质疑探测本身（弱探测不推翻强反证） | 用 curl 返回码直判可用性并外推到 SDK 链路；弱探测推翻强反证 | major |
| §1.12 禁止具体算子耦合（工程侧） | 对改动中形如算子名的 snake_case 字面量（`grep -nE '"[a-z][a-z0-9]+_[a-z0-9_]+"' src/`）人工核对是否用于按名分支/白名单/特判表；判定逻辑应基于**客观结构信号**（同名 IO 关系 / proto 字段 / schema 签名）派生 | 出现具体算子名字面量用于分支/白名单/内置清单/特判表（§1.12 判据：删掉某算子名会改变代码路径） | blocker |
| §1.13 Golden 永远是权威 | 改动涉及 golden/参考实现读取、比对、传递：`grep -rnE 'golden\|reference\|expected\|gt_' src/` 看有无对 golden 做修正/猜测/覆盖的静默纠偏分支；工程派生结论与 golden 冲突时是否以 golden 为准 + 留可观测信号交回上游 | 工程逻辑「修正」golden、为「golden 可能错」加静默纠偏分支、冲突时工程私自改写 golden | blocker |
| §通用化边界（§1.5/§1.6/§1.7 延伸） | 通用流程（`orchestration/`/`application/`/adapter **基类**）不得写死绑定**具体仓 / 具体算子 / 具体路径**的机制或约定——含调用方式（如 `torch.ops.cann_bench.<op>`）、目录布局、命名规则、接口形态。`grep -rnE 'cann_bench\|cann-bench\|ops-nn\|omni-ops\|torch\.ops\.[a-z_]+' src/ascendc_devkit/orchestration src/ascendc_devkit/application`；确认具体性是经注入/配置/适配器，而非写死在通用层。**判别**：换一个仓/算子，这段通用代码还能跑吗？不能 → 命中 | 通用流程绑定具体仓/算子/路径的约定（换仓/换算子即失效） | major→blocker |

## D2 — Skill 原则（CLAUDE.md §2）｜触及 `.claude/skills` 时

> 作用域：本维查 `.claude/skills/<skill>/` 目录自身内容。凡「外部路径 / 算子耦合 / 编号引用 / 框架依赖」判据，与 D1 同源但作用层不同——D1 查 `src/` 工程代码，本维查 skill 内容，勿把 D1 判据直接套 skill。

### D2-A 框架耦合检测（§2.1 / §2.2 / §2.6）★

判据：skill 从本仓取出后，能否在干净 Claude Code TUI 里直接 `/<skill>` 跑通，不依赖工程注入上下文、不依赖自身目录之外的文件。

| 耦合类型 | 怎么查（机械信号） | 违反信号 | 处置 | 默认 |
|---|---|---|---|---|
| §2.6-① 绝对/家目录路径 | `grep -rnE '/home/\|/root/\|~/\|Path\.home\|expanduser\|\$HOME' .claude/skills/<skill>/` | 命中 | 改 CWD 相对 / 文档约定 | blocker |
| §2.6-① DevKit 布局依赖 | `grep -rnE 'src/ascendc_devkit\|<workspace>\|\.precision-fix\|workspace 专有' .claude/skills/<skill>/` | 依赖 DevKit 专有目录结构 | 改 CWD 相对 | blocker |
| §2.1/§2.6-② 跨目录读资源 | 检查 skill 引用的文件路径是否落在 `.claude/skills/<self>/` **之外**（`resources/`、别 skill 目录、`docs/`） | 读自身目录外的文件 | 收进 skill 用相对路径（§2.2） | major |
| §2.1 slash 调用 vs 直读 | 引用别 skill **经 slash command**（`/<skill>`）= OK；直接 cat/Read 别 skill 文件 = 不 OK | 直读跨 skill 文件 | 改 slash 调用 | major |
| §2.6-③ DevKit 专有 MCP | grep skill 引用的工具名是否 DevKit 注入的 MCP（非 Claude Code 标准工具） | 依赖 DevKit MCP | 去除 | major |
| §2.1 框架 import | `grep -rn 'import ascendc_devkit\|from ascendc_devkit' .claude/skills/<skill>/`（含 `scripts/`） | skill 脚本 import 框架代码 | 解耦 / 内联 | blocker |
| §2.1 注入上下文依赖 | skill 是否假定只有编排器才注入的 state/context/文件布局 | 依赖框架注入 | 改文件契约 / 自包含 | major |
| §2.1 取出可跑（终极判据） | 把 `<skill>/` 单独拷出仓 → 干净 TUI `/<skill>` 能否跑通 | 跑不通 | 修到自包含 | blocker |

### D2-B 其余 skill 原则

| 检查项 | 怎么查（机械信号） | 违反信号 | 默认 |
|---|---|---|---|
| §2.3 I/O=文件 | 输入输出以文件契约；skill 间文件接力（前 skill 产文件 → 后 skill 读） | 用内存/全局变量传契约 | major |
| §2.4 中间产物 | 中间产物落工作目录（codegen 等除外） | 产物乱放或缺失 | minor |
| §2.5 唯一通路 | `git log/diff` 看同职责是否有旧通路残留（旧 skill/schema/prompt/stage） | 新旧并存、被取代的旧通路未删 | blocker |
| §2.7 核心归 skill | 核心方法引导在 skill；脚手架（CMakeLists/模板/注册宏）外移给 LLM | 仓特定脚手架写死进 skill；或核心方法散在 agent | major |
| §2.8 workflow/知识分离 | SKILL.md 正文是否内联「某值是多少/某 API 长什么样」的知识数据（硬件真值表/API 规格/范式/参考文档/schema example），而非「做什么/怎么做」的 workflow；知识/数据应归 `references/`/`library/`/`schema/` 按需 Read | workflow 与知识/数据混排，模型易把数据当流程指令；SKILL.md 膨胀 | major |
| §2.9 自检闭环+门边界 | 新增质量门/自检节点时核查：①门是否只查本 stage 产物（不越界回检上游）；②门是否「只报问题、修复靠重跑 producer 碰运气」（discover+regenerate，禁止）；③一致性若可由「下游消费上游既定前提」构造性保证，是否就不该再加门 | 跨段回检上游正确性；门只发现不解决；构造性可保证却加冗余门 | major |
| §2.10 输入输出结构化 | skill/agent 输出产物：机器交接事实是否落在 schema 约束的 JSON（control.json / candidate_pool / *_report.json 等字段契约），而非只写进自由文本 md prose 让 harness/下游 LLM 二次解析。判据：框架/下游需读的某事实必须有确定字段路径（§2.10；agent manifest 亦然，D4 启用时一并查） | 机器交接事实只写 prose、无结构化字段；harness 靠 LLM 二次解析 | major |
| §2.5 四方字段写入权一致性 | 对核心字段（如 routing history / debug_result 等跨声明源字段）：grep 其在 SKILL.md / prompts / agent.md / 框架 `*.py` 中的写入权声明是否一致；skill 侧若声明对框架字段的写入权，与框架代码实际写入权比对（谁写、何时清） | 同一字段出现「agent 写」与「框架写」冲突声明；skill 声明的框架字段写入权与框架实际不符 | blocker |
| §1.12 skill 侧：禁止算子名当分类锚点 | `grep -rnE '典型例\|例如 .*算子\|如 .*(v2\|AdamW\|Softmax\|Gelu\|moe\|scatter\|conv\|resize)' <skill>/` 人工核对是否把具体算子名当分类锚点；举例应为结构特征描述（如「输出与输入同名的状态张量」）而非算子点名 | SKILL.md/manifest 用具体算子名当「某类典型例」诱导按名模式匹配（§1.12 判据：删掉算子名改变分类结论） | major |
| §2.11 skill 侧：禁止问题/需求编号耦合 | `grep -rnE 'P[0-9]{1,3}\|step-[0-9]+\|问题[0-9]+\|D[0-9]+' <skill>/` 人工核对是否引用本仓 docs/plan 问题编号 / 会话步骤号 / 历史实例决策编号；需要佐证时用**通用语义描述**（如「空占位冒充省略导致与 golden 对比失败的历史实证」），编号只留 docs/plan（§2.11 判据：删掉编号是否改变判据/流程结论） | SKILL.md/schema/references 出现 P7/P12 类、step-84 类、D4 类编号引用（无法索引的内部上下文） | major |

## D3 — 测试必要性与真实性（CLAUDE.md §3）｜常驻

| 检查项 | 怎么查（机械信号） | 违反信号 | 默认 |
|---|---|---|---|
| 新行为有 UT | 改动的 `.py` 是否有对应 `tests/ut/**/test_*.py` 覆盖（按模块归位） | 新分支/新逻辑无 UT | major |
| 真实链路有真实 ST | 改动触及 SDK/CLI/MCP/agent 真实行为时：`grep -rln '@pytest.mark.llm' tests/st/` 看是否有用例且**非 mock** | 真实链路只 mock、无 `@llm` 真实用例守护（§3.9） | major |
| §3.4 不掩盖 | `grep -rnE 'pytest\.skip\|except\s*:\s*$\|except.*:\s*pass\|@pytest\.mark\.skip' tests/`（复核 skipif 是否合理） | 用 skip/except-pass 绕过失败用例 | blocker |
| §3.5 mark 语义真实 | 对每个带 `llm/npu/cann` mark 的用例：看其是否**真实依赖**（grep 用例内是否用了 mock/StubBackend/MagicMock） | mock 掉依赖却仍标 mark；或真实依赖未标 | major |
| §3.10 真实 LLM 用例吸收非确定性 | 对 `@llm` 真实用例：断言判据是否为「有界重试内至少触发一次」而非「每次都服从」；重试是否只为吸收抖动，未退化成 mock/放宽真实性 | 断言要求每次确定性成功（抖动即失败）；用重试把真实依赖放宽成确定性 | minor |
| §3.11 heavy_llm | `grep -rA2 '@pytest.mark.heavy_llm' tests/` 看是否成对带 `@pytest.mark.llm` | 单标 heavy_llm 缺 llm；交付节点未跑未记录 | minor |
| 实跑通过 | 前台 `pytest tests/ut`（+ 相关非 heavy ST） | 任何失败 | blocker |

## D4 — Agent/编排（CLAUDE.md §4）｜触及 `.claude/agents` 或 `orchestration/` 时

| 检查项 | 怎么查（机械信号） | 违反信号 | 默认 |
|---|---|---|---|
| §4.1 manifest 驱动 | agent `.md` frontmatter 声明 skills/tools/permissions；`grep -rnE "skills\s*=\s*\[.*\]" src/ascendc_devkit/` 看 Python 是否硬编码 skill 名传 agent | Python 里硬编码 skill 名 | major |
| §4.2 扁平发现 | skill 发现走单一扁平树 `.claude/skills/<name>/SKILL.md` | 引入 plugins 加载路、依赖文件系统深层级 | major |
| §4.3 slash 投递 | skill 注入靠发给 agent 的消息首行 `/<skill>` 裸名 | 非 slash 方式注入、带 `plugin:` 前缀 | major |
| §4.4 澄清走 resolve_ambiguity | 编排型 agent（被 SpawnAgent 拉起的子 agent）manifest：澄清/反问是否映射到 `mcp__engine__resolve_ambiguity`（或确认 backend `disallowed_tools` 排除了原生 AskUserQuestion）；skill 文档是否用自然语言「需要就提问」（TUI 语义）而非写死 DevKit 专有工具名 | 编排 agent 依赖原生 AskUserQuestion（backend 默认 disallowed 调不到）；skill 文档写死 DevKit 专有工具名 | major |

## D5 — 方案合理性与最优性（CLAUDE.md §1.2）｜常驻

| 检查项 | 怎么查 | 违反信号 | 默认 |
|---|---|---|---|
| 根因被治 | 读改动 + 对应 L1 问题文档（`docs/plan/**/NN-problems.md`），确认是根因修复 | 只兜底未治根因；错误被静默吞/推迟下游 | major/blocker |
| 四把尺子 | 逐条过：可维护 / 可扩展 / 可诊断 / 架构合理 | 任一明显失分且无补偿 | major |
| 最优性 | **主动评估**有无更简/更优备选（不只勾选） | 存在明显更优方案未采纳且无理由 | minor→major |
| 与 L3 一致 | 若有 `docs/plan` L3，对比实现与拍板选项 | 实现偏离 L3 决策且无 L3 更新 | major |
| documented-but-not-built | 把关联 L4 §N 的分阶段/承诺项与实现交叉——承诺的 API（函数名 / 校验调用 / 接口）若缺失且 L4 §10 无撤回记录 | L4 承诺的 API 未实现、无撤回记录 | major |

> **四把尺子组合原则（§1.2）**：单一方案无法全过时，用「正确改动」保不变式 + 「宽容兜底」防崩 + 可观测性防掩盖。按此组合判断，而非一刀切。

## D6 — 通用代码质量｜常驻

| 检查项 | 怎么查 | 违反信号 | 默认 |
|---|---|---|---|
| 正确性 | 审 边界 / 并发 / 空值 / 类型 / 资源匹配 | 潜在 bug | major |
| 复用/简化 | `grep` 找重复实现、死代码；对照 §2.5 唯一通路 | 重复实现、死代码 | minor→major |
| 可诊断 | 异常路径是否留可观测信号（日志/事件/return code） | 错误被静默吞、无信号 | major |
| 副作用生成器反模式 | 路径 / 键 / id / 计数等生成器（及任何「返回简单值却内部改状态」的函数，如返回 Path 却写盘/自增）：不得改盘 / 改状态；若改，核查所有调用点是否复用缓存或承受计数漂移 | 生成器/查询函数有隐藏副作用，调用点未感知（如每次调用落盘/递增致漂移） | major |
| 返回修改对象的函数——调用者必用返回值 | helper 若 `x=load(); mutate(x); save(x); return x`，调用者必须用返回值或重载 | 调用者丢弃返回值 → 保存陈旧引用覆盖并发修改 | blocker |

## D7 — 文档与跟踪一致性（CLAUDE.md §1.8）｜常驻

| 检查项 | 怎么查 | 违反信号 | 默认 |
|---|---|---|---|
| 四层产权 | L1 事实 / L2 进度 / L3 决策 / L4 配方 各归其位（按 `docs/plan/README.md` 试金石） | 把方案写进 L1、把证据写进 L2 | minor |
| PR 同步文档 | PR 实质变更是否有对应 `docs/plan` 层记录 | 有实质变更却无 L1/L2/L4 记录 | major |
| 代码-文档一致 | public 接口/行为与文档对照 | 文档与代码漂移 | minor |
| L4 §10 as-built 回填 | PR 关联 L4 的 §10 as-built 是否回填实际偏差 + UT 数 + commit | as-built 留空模板 / 只贴计划 | minor |

## D8 — 软件架构与经典软件工程｜常驻

经典软件工程方法论视角的实现健康度审查（§1.2 架构合理尺子的独立深化；D1 查本仓自定义层矩阵/原则，本维查通用软件架构与代码组织）。

| 检查项 | 怎么查 | 违反信号 | 默认 |
|---|---|---|---|
| 散弹式修改 | 列出本次 PR 实际改动文件 → 按概念/需求归组：同一概念是否落在多个无共同抽象的文件各改一点（如改一个错误分类却动 orchestration+adapter+domain 三处无共用） | 一个概念变更散落 >5 文件各打补丁、无单一抽象承载 | major |
| 模块内聚 | 看改动文件内是否混多个无关关注点：一个 class/函数是否同时做编排+IO+判定+UI（跨职责引用）；改动函数 >150 行或单函数 >8 if 分支 → 审视是否可拆 | 上帝模块 / 混合无关职责 / 单函数过长多分支 | major |
| 模块低耦合 | 改动模块有无访问别模块私有成员：`grep -rnE '_\w+\s*=\|_\w+\.\w+\|getattr\(.*_\w+' <file>`（下划线前缀私有跨模块访问）；有无 `import` 深层模块内部类而非其公共接口 | 直接读别模块私有、跨模块深耦合、改一处牵动无关模块 | major |
| 循环依赖 / 依赖方向 | `grep -nE '^\s*(from\|import) ' <file>` 列出改动模块 import → 沿被依赖模块反向 grep 是否 import 回改动模块（成环）；业务层是否 import adapter/具体实现而非 Protocol/接口（对照 D1 §1.6） | A↔B 环依赖；高层依赖低层实现细节；`from x import` 非 interface/协议 | major |
| 上帝对象 / 过长函数 | 改动 class 是否 `>400` 行职责单一性存疑；改动函数 >150 行或嵌套 >4 层 → 审视可拆 | 数百行函数、超多 if 分支单函数、God class | minor→major |
| 设计模式恰当性 | 改动是否自造与现成模式重复的机制：若有 2+ 个 if-branch 各做相似策略 → 是否该用策略/注册表；有 switch-on-type → 是否多态/状态机更直接。**judgment 项**：核对"用模式更简"还是"硬套制造间接层" | 模式误用（当用不用 / 不当用硬套制造间接层） | minor→major |
| 开闭/扩展点 | 新加一类情况是否改既有函数体加 if，还是经注册/配置/继承扩展：`grep -nE 'if .*(kind\|type\|name) ==' <file>` 看有无按新增类型名加分支（对照 §1.12 结构信号，勿按具体算子/实例名分支） | 每加一类新情况改既有函数体加 if 分支 | minor→major |
| 命名与可读性 | 标识符是否名实相符：`grep -nE 'def get_\|def _?is_\|def has_' <file>` 核对返回真/假或副作用的命名一致性 | 误导性命名（返回 bool 却叫 get_xx、有副作用却叫 get/query）、无意义缩写 | nit→minor |

> **机械化 vs judgment**：上表机械信号（行数/分支数/grep 私有访问/import 图）用于**触发审视**，非绝对判据——命中后由人复核确认。设计模式恰当性与命名是 judgment 项（无机械阈值），执行时给**具体 evidence**（某处用 X 模式反而比直接写法多一层间接）而非空泛断言。两条通用，与 §2.12 表达严谨一致。

> **经典工程视角 vs 本仓原则**：D1 管本仓自定义硬约束（层矩阵 / State 不可变 / §2.5 / §1.13 等）；D8 管普适软件工程。两者互补：一次改动可同时命中 D1（违反本仓约定）与 D8（通用设计缺陷）。**同证据去重**：同一违反若已由 D1 以更高严重度记录（如跨层反向 import 已记 D1 §1.1 blocker），D8 不重复记同证据的低严重度——D8 聚焦 D1 未覆盖的层内环与模块级设计问题，避免对同一行双记制造噪音（§2.9 门不制造噪音）。D8 判据独立成立，不因「现有代码已如此」而豁免——review 的是本次改动质量，不是全仓历史债（历史债可另记，不阻断本次）。

---

## 执行注意
- 每条 finding 必须给 **evidence**（`file:line` + 代码/事实片段），不得空泛。
- severity 可按上下文调整，但 blocker 级不得降级。
- 测试未跑的维度，报告里标「未验证」并说明原因（§3.7 诚实）。
- 逐维执行时发现某条判据检不实 / 有遗漏 → 就地修正或回补本文件对应维度表（本文件是 skill 判据的唯一权威源）。
