# opencode SDK 后端接入 — 方案分析（L3）

> 目标：agent 执行从「只绑 `claude_agent_sdk`」升级为「**opencode / claude 双后端**，
> 默认 opencode、claude 降为可选，开关走配置文件」，且**最大化复用**同一套 skill，
> 两套 SDK 完美兼容。

本文回答用户三点关切：**#1 能力能否完全对等** / **#2 开关配置（默认 opencode）** /
**#3 skill 组织形式如何一源两兼容**。

> **v3 修订（Design X，经真实 spawn 验证冻结）**：v2 以「嵌套 `.claude/plugins/` 为
> skill 单源，opencode 侧靠符号链接投影到扁平发现根」定案。经 heavy_llm spike 实测
> （见 §1），推翻了仓内旧论断「扁平 `.claude/skills/` 不被 Claude 发现」，据此改采
> **Design X：扁平 `.claude/skills/<skill>/` 为唯一真源，两后端都原生发现同一棵扁平树**
> ——claude 侧靠「工作目录内一条 skills 软链锚点」补齐深 cwd 发现，opencode 侧靠原生
> cwd→git worktree 走查。本文按该事实重写 §0/§1/§3/§4/§8，并新增 §1（验证证据）与
> §8（CLAUDE.md 宪法级修订）。v2 的投影方案作废，理由见 §4 末。

---

## 0. 全局视角：一个稳定接缝 + 三条不变式

- **稳定接缝**：`AgentBackend` ABC（`capabilities/agent/backend.py`，唯一 `spawn(...)`）。
  所有 SDK 方言差异都收在它后面，上层（Stage/Runner/编排）零感知。契约**不改**。
- **不变式 I（skill 单源 = 扁平树）**：`.claude/skills/<skill>/SKILL.md` 是 skill 方法学的
  **唯一产权源**。两后端都从这里取内容，**绝不分叉出第二套 skill 文本、也不再维护第二棵
  目录树**。Design X 相对 v2 的关键升级：单源本身就是两后端的公共发现根，投影降为
  「claude 侧工作目录一条目录软链」，不再是「按 skill 逐条投影的第二棵树」。
- **不变式 II（skill 即插即用，§2.1）**：任一 skill 从本仓取出仍能在 Claude Code TUI
  `/<skill>` 跑通。扁平 `.claude/skills/<skill>/` 本就是 Claude 的原生发现根之一（§1 实测），
  即插即用天然成立，且比嵌套 `plugins` 布局更贴近「取出即用」。
- **不变式 III（I/O 契约=文件，§2.3）**：skill 间靠文件接力自闭环，与 SDK 无关，天然跨后端。

判据：凡"要给某后端单独维护一份 skill 文本 / 第二棵目录树"的方案，直接否决——违背不变式 I。
工作目录内一条指向单源的软链不违背：目标即那一棵源树，改源即改发现。

---

## 1. 验证证据：扁平 skill 发现取决于工作目录（heavy_llm spike）

Design X 的地基是一条被 v2 假设否定、但经真实 spawn 证伪的事实。用不可伪造的探针
（secret token 只写在 `SKILL.md` 内、不进 spawn prompt；agent 唯有真的发现并加载该 skill
才能把 token 写进 proof 文件）跑 `claude_agent_sdk` 真 spawn，四组对照：

| 配置 | cwd | 发现锚点 | 结果 |
|---|---|---|---|
| V1 | 仓库根（浅） | 无 | **PASS** |
| 原 | 深 artifacts 工作目录 | `add_dirs=[repo]` | FAIL |
| V5 | 深 artifacts 工作目录 | 无 | FAIL |
| V7 | 深 artifacts 工作目录 | `<workspace>/.claude/skills → <repo>/.claude/skills` 目录软链 | **PASS** |

**结论（钉死）**：

1. Claude **能**发现扁平 `.claude/skills/<skill>/`——只要它在 `cwd/.claude/skills`（或足够浅的
   walk-up 命中）。仓内旧注释「bare `.claude/skills` 不被 CLI 发现（empirically）」是**从深 cwd
   测的**，浅 cwd 能发现，该论断已被 V1 推翻。
2. 生产 spawn 用**深 artifacts 工作目录**（skill 文件接力 I/O 必须 cwd 相对，§2.4）；Claude
   **不会**从深 cwd 一路 walk-up 到仓库根（opencode 会走到 git worktree，Claude 不会——两端
   walk-up 语义不同），故裸放仓库根的扁平树发现不到（V5 FAIL）。
3. `add_dirs=[repo]` 只给文件访问权，**不触发 skill 发现**（原组 + V5 双证 FAIL）。官方文档
   称 `add_dirs` 目录的 `.claude/skills` 自动加载，在当前 SDK headless 场景**不成立**——文档实锤
   ≠ 端到端跑通，以实测为准。
4. **修复 = 工作目录内一条 skills 目录软链**：spawn 前建 `<workspace>/.claude/skills →
   <repo>/.claude/skills`，深 cwd 就地命中（V7 PASS），同时保住 skill 文件接力仍 cwd 相对。

这一条软链就是 Design X 让 claude 读扁平单源的**全部代价**——一次运行一条目录软链、零内容分叉、
无逐 skill 处理，比 v2 的「嵌套→扁平逐 skill 投影农场」轻一个量级。

> 方法论：本节遵「明知下游风险先真跑证实，再定方案」——机制存在与否用最小 spike 打穿，
> 不把不确定推给后续 heavy e2e。

---

## 2. 现状与接缝

| 位置 | 角色 |
|---|---|
| `capabilities/agent/backend.py` | `AgentBackend` ABC（L5 协议，唯一 `spawn`） |
| `capabilities/agent/sdk_backend.py` | `SDKBackend` = claude_agent_sdk 实现 |
| `capabilities/agent/stub_backend.py` | `StubBackend` = 测试桩（两后端共用，不动） |
| `application/dispatcher.py`（**3 处**） | DI 装配点：`backend = SDKBackend(...)` |
| `capabilities/mcp_tools.py` | `build_engine_mcp_server` 内 `from claude_agent_sdk import tool, create_sdk_mcp_server` |
| `orchestration/skill_config.py` | `STAGE_SKILL_MAP`（stage→skill）+ `STAGE_TAIL_CALL_MAP`（tail-call 闭包）+ `validate_skill_map()`（对盘校验） |
| `capabilities/skill/loader.py` | 现 `PluginLoader.resolve_paths` → `plugins=[{type:local,path}]`（Design X 后由扁平发现取代，见 §4/§8） |

现状要点：`SDKBackend` 通过 `plugins=[{type:local,path}]` 让 CLI 发现 `.claude/plugins/<plugin>/
skills/<skill>/`，命名空间化为 `<plugin>:<skill>`；`STAGE_SKILL_MAP` 值域是 `plugin:skill`。
这条路是**绝对路径**、深 cwd 安全，但要求维护嵌套 `plugins` 树 + 命名空间，且与 opencode 的
扁平裸名发现根不一致——正是本次要统一的点。

---

## 3. 两后端的 skill 发现机制（Design X：同一棵扁平树，各自原生发现）

**都靠文件系统发现 skill、都经原生工具按需加载**，且**读的是同一棵扁平树**。没有一条路是
prompt 注入。

- **claude 后端**：`setting_sources` 含 `project`，发现根 = `cwd/.claude/skills`。spawn 前在
  工作目录建 `<workspace>/.claude/skills → <repo>/.claude/skills` 目录软链（§1 V7），深 cwd
  就地命中扁平单源；spawn 首条消息以 `/<skill>`（**裸名**，非 `plugin:skill`）领头注入首轮
  方法体；运行中经 `Skill` 工具 tail-call 其它裸名 skill。`settings` 仍绝对钉
  （`.claude/settings.json`，承载网关 env + model）。
- **opencode 后端**：opencode server 按 **cwd 向上走到 git worktree**，原生发现
  `.claude/skills/<name>/SKILL.md`（工作目录在仓内 → 命中同一棵扁平单源，软链对它冗余无害）；
  把可用 skill 列进原生 `skill` 工具描述，模型 `skill({name})` 惰性加载；tail-call = 同工具再调。

**结论**：Design X 把「发现根对齐」问题降为「**同一棵扁平树 + claude 侧一条工作目录软链**」，
两端都裸名、都原生惰性加载、都原生 tail-call，语义完全同构。

---

## 4. #3 的核心：skill 组织形式 —— 扁平单源 + 分组回落配置

**设计原则**：skill 的**内容**（方法学）与**位置**统一为唯一一棵扁平 `.claude/skills/<skill>/`
（不变式 I）；**发现**两端都原生（§3）；**按 stage 分组**这一"一目了然"诉求，从「靠嵌套目录
物理分开」回落到「靠 `STAGE_SKILL_MAP` 语义分组」——分组信息本就该在编排单源里，不该同时
散在目录结构里造成两处产权。

```
        唯一真源：扁平 .claude/skills/<skill>/SKILL.md（裸名，全局唯一）   ← 不变式 I
                        │
          ┌─────────────┴─────────────────┐
   claude 后端                        opencode 后端
   <workspace>/.claude/skills         cwd→git worktree 原生走查
     └→ <repo>/.claude/skills（软链锚点，§1 V7）      命中同一棵扁平树
   setting_sources=[project] 原生发现              原生 skill 工具惰性加载
   /<skill> 领头注入 + Skill 工具 tail-call         skill({name}) 惰性 + tail-call
```

### 4.1 命名去空间化（`plugin:skill` → 裸 `name`）

- `STAGE_SKILL_MAP` / `STAGE_TAIL_CALL_MAP` 值域从 `plugin:skill` 改**裸 `skill`**（=目录名）。
  这本就是 opencode 的要求，也让 claude 领头 slash 从 `/<plugin>:<skill>` 变 `/<skill>`，两端一致。
- **裸名全局唯一**是硬约束：`validate_skill_map()`（现已对盘）扩展为**加载期唯一性校验**——
  两个 skill 目录同名 → 加载期报错并列出冲突，不推迟运行期（§1.3）。当前两棵树合并后除历史
  重叠（已由软链去重）无同名冲突，flatten 无碰撞。

### 4.2 分组回落：STAGE_SKILL_MAP 是唯一分组产权

- 失去的是**目录层面**的 stage 分组（`plugins/stage-design/skills/*`）；**语义分组**由
  `STAGE_SKILL_MAP`（stage→skills）承载，它本就是单一真源，只是不再和目录结构重复记账。
- 「一目了然」诉求：若需人读视图，由 `STAGE_SKILL_MAP` **生成**一份只读索引（stage→skill 清单），
  不新建独立分组系统（[[avoid-overdesign-prefer-reuse]]）；生成物非产权源，源仍是 `STAGE_SKILL_MAP`。
- 限权承载点：claude 侧领头 slash + `Skill` 工具 allowlist（现 `skill_allowlist`）不变，只是键改裸名；
  opencode 侧「哪个 agent 能加载哪些 skill」由 per-agent `permission.skill` glob 承载，编译自同一
  `STAGE_SKILL_MAP`（单一真源，两后端各自编译成领头 slash / permission）。

### 4.3 为何是扁平单源而非 v2 的嵌套单源 + 投影

- v2 保留嵌套 `plugins` 为源、给 opencode 投影一棵扁平树 → **两棵目录树长期并存**（源嵌套 +
  投影扁平），投影农场按 skill 逐条维护、易腐化，违背「单一通路不留旧债」的精神（§2.5）。
- Design X 只有一棵扁平树，两后端读它；claude 的"投影"退化为工作目录一条软链（指向源本身，
  改源即改发现，无第二棵树可腐化）。可维护/可扩展/可诊断/架构合理四把尺子全面优于 v2。
- 代价：需改 claude 的 skill 加载机制（现 `plugins=` → 扁平发现 + 软链锚点），触及 CLAUDE.md
  §2.2/§4.2/§4.3 宪法条款（§8）。这是 Design X 唯一的重量级动作，但由 §1 实测背书，理据充分。

---

## 5. #1 能力对等矩阵（逐项 + 校验状态）

诚实结论：**每一项都有确定的 opencode 原生落点，无硬阻断**；claude 侧 skill 加载改造由 §1
实测背书。剩余 gap 是**名称/布局对齐**与**一次端到端回归**，不是"机制缺失"。

| claude 能力 | 管线是否用 | opencode 落点 | 对等 |
|---|---|---|---|
| system_prompt（agent.md 正文） | 是 | `new_session(system_prompt=)` | ✅ |
| cwd / 产物落 workspace | 是 | ✅（且 cwd 驱动 skill/agent 发现） | ✅ |
| model + 网关 | 是 | `model`+`provider_id="anthropic"`+`opencode.json` | ✅ |
| MCP engine（resolve_ambiguity 决策门） | 是 | 同名 `mcp__engine__resolve_ambiguity` | ✅（换 import 源） |
| max_turns | 是 | ✅ | ✅ |
| resume / session_id | 是 | `resume` 字段 | ✅ |
| transcript 消息序列化 | 是 | 同形消息 | ✅（微调容错） |
| **skill 加载（扁平 SKILL.md 发现）** | 是 | **原生走查** `.claude/skills/`（cwd→git worktree） | ✅（同一棵扁平单源，无投影） |
| **claude 侧扁平发现（深 cwd）** | 是 | — | ✅（工作目录 skills 软链锚点，§1 V7 实测） |
| **`Skill` 工具 / tail-call** | 是（tiling→selfcheck） | **原生 `skill` 工具**，`skill({name})` 再调即 tail-call | ✅ |
| **skill 惰性/按需加载** | 是（模型自选） | 原生 `<available_skills>` + 惰性 `skill()` | ✅ |
| skill 按 stage/agent 限权 | 是（`STAGE_SKILL_MAP` + allowlist） | per-agent `permission.skill` glob | ✅（同一真源两编译） |
| permission_mode `acceptEdits` | 是 | per-agent `permission.edit=allow` | ⚠️ 语义映射 |
| allowed_tools | 是 | 有字段；内置工具名大小写不同 | ⚠️ 名称映射表 |
| disallowed_tools（Task/AskUserQuestion） | 是 | per-agent `permission.{task,question}=deny` | ✅（原生 deny，非 hook） |
| agents= 子 agent（Task 派发） | 是（precision-debugger 派发 phase 子 agent） | 原生 subagent（`.opencode/agents/*.md` + `task` + `subagent_depth`） | ⚠️ 定义投影 + 验证 |
| settings.json 钉配置 | 是（claude） | opencode.json（已就位） | ✅ 换源 |

无 ❌。两个 ⚠️（subagent 派发、工具名/权限映射）由 §9 spike 打穿。

---

## 6. 后端层方案取舍

- **方案 A（选定）**：新增 `OpenCodeBackend(AgentBackend)`，与 `SDKBackend` 平级，`spawn` 入参
  1:1 映射 `AgentOptions`；两后端都从扁平单源原生发现 skill（claude 加软链锚点，opencode 原生
  走查）；subagent 经 opencode 原生 `task`/agents；`disallowed` 经 per-agent `permission.deny`；
  工具名经映射表；MCP 换 import 源复用。
  - 可维护：两后端各绑一个 SDK 方言，互不污染；skill 单源单树，无投影农场。
  - 可扩展：第三种 SDK 同样落一个子类；新 skill = 扁平树落一个目录 + `STAGE_SKILL_MAP` 加一行。
  - 可诊断：gap 逐项显式（§5）；裸名唯一性冲突加载期报错；软链缺失可检测；异常有落点不静默。
  - 架构合理：契约在 L5、装配在 L3、skill 内容单源单树、发现各后端原生——各归其位。
- **方案 B（否）**：在 `SDKBackend` 内分支两 SDK。→ 一类两方言，违 §2.5、难测。
- **方案 C（否）**：再抽一层"AgentSDK 协议"。→ 过度设计，`AgentBackend` 已是该接缝。
- **方案 D（已废弃，v2）**：嵌套单源 + opencode 符号链接投影一棵扁平树。→ 两棵树长期并存、
  投影农场易腐化；被 Design X 单树取代（§4.3）。
- **方案 E（已废弃，初版 S2）**：SKILL.md 正文注入 prompt。→ 基于"opencode 无 skill 发现"的错误
  假设，失去原生惰性加载，用户已否决。

---

## 7. #2 开关配置（默认 opencode，claude 可选）

- 配置源：`resources/orchestration-config.json` 增 `agent_backend` 段：
  `{"kind": "opencode", "transport": "subprocess|http", "server_url": "..."}`，**默认
  `kind="opencode"`**；`claude` 为可选值。环境变量 `ASCENDC_AGENT_BACKEND` 可覆盖（临时切换 / CI）。
- 工厂 `build_agent_backend(kind, **kw)`（放 `application/` 装配层）读该配置，返回
  `OpenCodeBackend` 或 `SDKBackend`；`StubBackend` 兜底与异常降级不变。
- `dispatcher.py` **三处** `SDKBackend(...)` 全部替换为工厂调用（§2.5 唯一装配路，不在三处各写 if）。
- provider/网关：opencode 走已就位的 `opencode.json`；claude 走 `.claude/settings.json`。model 解析链
  （`action.model > stage_model > default`，见 [[orchestration-default-model-deadconfig]]）不变，末端
  字符串透传（opencode 需 `provider/model` 形，翻译点在 `OpenCodeBackend`）。
- 传输取舍：倾向 **subprocess**（`opencode acp`，每 spawn 一进程，与 claude query 进程模型一致，
  免维护常驻 `opencode serve` 生命周期/端口/鉴权）；HTTP 作为可选。

---

## 8. CLAUDE.md 宪法级修订（Design X 前置）

Design X 改动 claude 的 skill 加载机制，直接触及三条项目硬规则，必须**先改宪法再改码**
（§1.4 不留兼容层：彻底改干净）：

- **§4.2**「Skill 加载 = plugins，唯一路 `plugins=[{type:local,path}]`」：其立论前提「扁平
  `.claude/skills` 不被发现」已被 §1 V1/V7 推翻。改为「Skill 加载 = 扁平 `.claude/skills/` 发现
  （claude 经工作目录 skills 软链锚点 + `setting_sources=[project]`；opencode 经原生 cwd 走查）」。
- **§4.3**「Skill 投递 = 领头 slash」：机制不变，仅命名从 `/<plugin>:<skill>` 改 `/<skill>` 裸名。
- **§2.2**「Schema 及资源存 `.claude/plugins/<plugin>/skills/<skill>/`」：canonical 路径改
  `.claude/skills/<skill>/`（资源仍与 skill 同目录，即插即用不破坏）。
- **§4.1**（Agent 契约 manifest 驱动）不变；agent frontmatter 的 skill 名同步去命名空间。

修订遵 §1.8：本文（L3）冻结方案，宪法修订与迁移落 L4，问题状态在 L2 总纲跟踪。

---

## 9. 决定性风险 + 验证先行（spike gate）

- **已打穿**：claude 扁平发现（深 cwd + 工作目录软链锚点）——§1 V7 真 spawn PASS。
- **Spike-1 opencode 原生发现 + tail-call**：opencode 后端 spawn 一个 tiling substage，验证
  ① 扁平 `.claude/skills` 进 `<available_skills>`、模型 `skill({name})` 加载方法学；
  ② tail-call 的 `feedback-selfcheck` 经再次 `skill()` 消费、产出 `selfcheck_report.json`。
- **Spike-2 subagent 原生派发**：opencode 后端跑 precision-debugger（派发 phase 子 agent），验证
  opencode `task`/agents + `subagent_depth` 承接 Claude subagent 语义；不通则定 fallback
  （子 agent 降级主 agent 内联步骤 / 或该链暂锁 claude 后端）。
- **Spike-3 工具权限**：验证 allowed_tools 名称映射 + per-agent `permission.{task,question}=deny`
  生效（禁 Task/AskUserQuestion）。
- **迁移正确性 gate**：嵌套 `plugins` 树内容迁入扁平单源后，`validate_skill_map()` 全绿 +
  裸名唯一性零冲突 + 两后端各跑一次非 heavy ST 各自发现全部在册 skill。

**双 SDK 验证是每步硬要求**：任一改动都须 claude + opencode 双侧真跑证实，不留单边盲区
（UT + 非 heavy ST 双后端各跑；heavy_llm 用户确认后端到端）。

---

## 10. 实施步骤概要（L4 动手前细化，spike 后）

1. 迁移：把 `.claude/plugins/**/skills/**` 的 34 个 skill 连同 references/scripts/schema 迁入扁平
   `.claude/skills/<skill>/`（裸名去命名空间，解历史重叠）；删嵌套 `plugins` 树与旧加载路（§2.5）。
2. `STAGE_SKILL_MAP` / `STAGE_TAIL_CALL_MAP` / agent frontmatter 值改裸名；`validate_skill_map()`
   扩展加载期唯一性校验。
3. `SDKBackend.spawn`：建工作目录 skills 软链锚点 + `setting_sources` 扁平发现取代 `plugins=`；
   领头 slash 改裸名。删 `PluginLoader` 的 `plugins=` 通路（唯一路收敛）。
4. 抽 `SDKBackend` 中 SDK 无关 helper（transcript / 产物 git-diff 收集 / resume 门 / `AgentResult`
   构造）为共享模块；`build_engine_mcp_server` 去 claude 硬编码 import，改注入 SDK 模块。
5. 新增 `OpenCodeBackend`：映射 `AgentOptions`；工具名映射表；`disallowed`→per-agent
   `permission.deny`；skill 经原生走查；subagent 经 opencode agents/`task`；MCP 复用。
6. 新增 `build_agent_backend` 工厂 + `agent_backend` 配置段（默认 opencode）；dispatcher 三处替换。
7. CLAUDE.md §2.2/§4.2/§4.3 修订（§8）。
8. 测试（TDD，遵 §三，**双 SDK**）：
   - UT：`OpenCodeBackend` 选项映射 / 工具名映射 / `permission.deny` 生成 / 软链锚点建链正确 /
     裸名唯一性冲突报错（mock opencode sdk）；两后端共用 `StubBackend` 跑 stage UT。
   - ST `@llm`（真实非 heavy）：**两后端各**一次真实 spawn 打网关，验可达 + `skill` 工具/领头 slash
     列出全部在册 skill + 决策门触发（§3.9/§3.10 有界重试）。
   - heavy_llm（§3.11，用户确认后）：**两后端各**跑一次端到端设计/精度链（Spike-1/2 正式回归）。

---

## 11. 约束核对

- §1.2 合理性优先：Design X 由 §1 实测背书，单树优于 v2 双树投影，四把尺子全面更优。
- §1.3 加载期校验：裸名全局唯一性在加载期校验，不推迟运行期。
- §1.4 不留兼容层：删嵌套 `plugins` 树 + `plugins=` 加载路 + 命名空间，不留新旧并存。
- §1.6 依赖注入：后端经协议注入；工厂在装配层选后端。
- §2.1/§2.3 skill 即插即用 + 文件 I/O：扁平 `.claude/skills/<skill>/` 是 Claude 原生发现根，
  资源同目录，TUI `/<skill>` 自闭环不破坏。
- §2.5 唯一通路：一棵扁平树、一个后端工厂、每后端一条发现路；删被取代的嵌套树与旧加载路。
- 过度设计规避（[[avoid-overdesign-prefer-reuse]]、[[soundness-over-minimal-change]]）：不新造 SDK
  抽象层（复用 `AgentBackend`）、不新建分组系统（复用 `STAGE_SKILL_MAP`）、不注入 prompt。

---

## 附：官方文档索引（`docs/opencode-sdk-ref/`，源 `sst/opencode@dev`）

| 文件 | 核实要点 |
|---|---|
| `skills.mdx` | 发现路径（含 `.claude/skills/`）、原生 `skill` 工具、`permission.skill`、裸 `name` 规则 |
| `agents.mdx` | primary/subagent、`task` 派发、per-agent `permission`、`hidden`、task 限权 |
| `commands.mdx` | `.opencode/commands/*.md` slash 命令（本方案 skill 不依赖，仅备查） |
| `plugins.mdx` | JS/TS 插件 + hooks（本方案 disallow 用原生 permission，不用 hook） |
| `config.mdx` | `.opencode` 目录结构、`agent`/`command`/`plugin`/`permission`/`subagent_depth` 键 |
| `sdk.mdx` / `server.mdx` | session cwd 驱动发现；`/session/:id/message` 的 `tools`/`agent`/`system` |
| `permissions.mdx` / `tools.mdx` | 权限键与内置工具名（小写，映射表依据） |
| `mcp-servers.mdx` / `custom-tools.mdx` / `acp.mdx` / `rules.mdx` / `references.mdx` | MCP/自定义工具/ACP 传输/AGENTS.md 规则/类型引用 |
