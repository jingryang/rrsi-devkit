# Design X 实施方案（L4）— 扁平单源 + opencode 双后端

> 配方层：**改哪个模块/函数、什么顺序、怎么验证**。决策与理由在 `01-analysis.md`（L3），
> 不在此复述。遵 [[plan-doc-discipline]]：不写 file:line，只点模块/函数名与顺序。

## 分两相，相内是「一次不可拆的耦合切换」

L3 §5/§10 已列能力与步骤。落地时按**风险与可独立验证性**切成两相：

- **相 1（claude 侧扁平切换）**：把 skill 加载从「嵌套 `plugins=`」整体换成「扁平 `.claude/skills/`
  发现 + 工作目录软链锚点」。**只此一相触及生产 skill 加载**，是全盘风险所在；由 L3 §1（V7 实测）
  背书。此相内 `SDKBackend` 仍是唯一后端，不引入 opencode，可用纯 claude 回归验证。
- **相 2（opencode 后端）**：新增 `OpenCodeBackend` + 工厂 + 配置（默认 opencode）+ dispatcher 三处替换。
  相 1 冻结后再做，双 SDK 验证。

**为何相 1 是一次耦合提交**：leading `/plugin:skill` 触发（`codegen` / `design_substages` /
`test_design_substages` 构建）、`plugins=` 路径（`runner` 从 agent manifest 构建）、`STAGE_SKILL_MAP`
值域（`plugin:skill`）、扁平发现（`SDKBackend`）四者互锁——改一半即断链（触发展开为空 / 发现不到
stage skill）。§2.5 不容新旧并存为长期态，故相 1 收敛为一次切换：物理迁移可先行并存（旧树仍被
`plugins=` 用，不断），但**触发+发现+值域+加载**必须同一提交翻转，末尾删旧树。

---

## 相 1：步骤与验证

### 1.0 CLAUDE.md 宪法修订（与本相代码同提交，不提前）
- §4.2 改：Skill 加载 = 扁平 `.claude/skills/` 发现（claude 经工作目录 skills 软链锚点 +
  `setting_sources=[project,local]`；opencode 经原生 cwd 走查）；删「`plugins=` 唯一路」。
- §4.3 改：leading slash 命名 `/<plugin>:<skill>` → `/<skill>` 裸名（机制不变）。
- §2.2 改：canonical 资源路径 `.claude/plugins/<plugin>/skills/<skill>/` → `.claude/skills/<skill>/`。
- §4.1 不变（manifest 驱动）；agent frontmatter skill 名同步裸化（本就多为裸名，核对即可）。
- **落点纪律**：§1.4 不留 constitution-code gap——本步与 1.3/1.4 代码在同一提交，不单独先合。
- 验证：人读一致性（宪法描述 = 代码行为）。

### 1.1 物理迁移：34 个嵌套 skill → 扁平（裸名）
- 把 `.claude/plugins/<plugin>/skills/<skill>/`（连同 references/scripts/schema 等全部子内容）
  搬到 `.claude/skills/<skill>/`。基名去命名空间。
- **冲突处理（仅 2 例）**：`ascendc-dev-knowledge`、`regbase-vf-test` 现为扁平软链，指向嵌套源；
  迁移即「软链位置落为真实目录」——先删软链再落真身，内容零丢失。其余 32 名对现有 17 扁平名零碰撞。
- **并存窗口合法**：此步后 `.claude/plugins/` 仍在、`plugins=` 仍指它，生产不断（§2.5 限时并存）。
- 验证：`SkillLoader.discover()` 扁平枚举 = 34 迁入 + 17 既有（去 2 重叠）= 49 个唯一名；无重名。

### 1.2 命名去空间化：STAGE_SKILL_MAP / tail_calls / 值域
- `resources/orchestration-config.json` 的 `skills.stages` / `skills.tail_calls` 值 `plugin:skill` → 裸 `skill`
  （如 `stage-design:ascendc-op-general-design` → `ascendc-op-general-design`）。改 `_comment` 措辞同步。
- `skill_config.py`：`validate_skill_map()` / `_plugin_skills_on_disk()` 从「扫 `.claude/plugins/<plugin>/skills`
  + 校验 `<plugin>:<skill>` 形」改为「扫扁平 `.claude/skills` + 校验裸名存在 + **裸名全局唯一**（加载期
  报重名，§1.3）」。`skill_allowlist()` 逻辑不变（键改裸名自然生效）。
- 验证：`validate_skill_map()` 返回空；构造重名场景 UT 断言报错。

### 1.3 触发构建改裸名（3 个 consumer）
- `codegen.py`（`_with_trigger` / `STAGE_SKILL_MAP.get(key)`）、`design_substages.py`（`skill` 属性 +
  1112/1278/1373 三处 trigger 构建）、`test_design_substages.py`：leading 消息由 `/<plugin>:<skill>`
  改 `/<skill>`。`skills=skill_allowlist(...)` 传参不变（值已裸名）。
- 验证：UT 断言各 stage 的首条消息以 `/<裸skill>` 起头、`skills=` 为裸名 allowlist。

### 1.4 加载机制切换：flat 发现 + 软链锚点，删 plugins=
- `SDKBackend._spawn`：spawn 前建 `<effective_cwd>/.claude/skills → <repo>/.claude/skills` 目录软链
  （幂等：存在且指向正确则跳过；指向错误则重建）；`ClaudeAgentOptions` 删 `plugins=`，保留
  `setting_sources=["project","local"]`（已在）；`AgentBackend.spawn` 签名删 `plugins` 形参。
- `runner.py`：删 `PluginLoader.validate/resolve_paths` 调用与 `plugins=effective_plugins` 传参。
- `loader.py`：删 `PluginLoader` 整类 + `resolve_paths`；`SkillLoader` 扁平发现升为 canonical（`loader.py:124`
  旧注释删）；`load_agent_manifest` 的 `plugins` 字段解析删（agent frontmatter 不再声明 plugins）。
- `precision_debug.py`：`PluginLoader.plugins_dir()` 引用改为扁平 `.claude/skills` 定位（或删，视用途）。
- `domain/skill.py`（`AgentManifest`）：删 `plugins` 字段（§1.4 不留别名）。
- 验证：见 1.6。

### 1.5 删旧树（本相收口，§2.5）
- 删 `.claude/plugins/` 整棵；删所有 `plugins=` / `PluginLoader` / `plugin:skill` 残留引用与测试夹具。
- 验证：全仓 `grep -rn "plugins=\|PluginLoader\|plugin:skill\|\.claude/plugins"` src/tests 零命中（docs/plan 历史文档不算，用户要求不改）。

### 1.6 测试（TDD，相 1 = 纯 claude 回归）
- **先改测试夹具**：所有断言 `plugin:skill` / `plugins_dir` / `resolve_paths` / 34-nested 布局的 UT
  改为裸名 + 扁平布局断言（`test_testdesigner_plugin.py` 等）。
- **新增 UT**：软链锚点建链正确（目标解析、幂等、指向错重建）；裸名唯一性冲突报错；`validate_skill_map`
  扁平版全绿；3 consumer 裸名 trigger。
- **ST `@llm`（非 heavy，单后端=claude）**：一次真实 spawn 打网关，验 `Skill` 工具/ leading slash 列出
  全部在册 skill + 决策门触发（§3.9/§3.10 有界重试）。
- **heavy_llm（§3.11，用户确认后）**：一条端到端设计链，验扁平发现 + tail-call（tiling→selfcheck）真实跑通。
- 命令：`pytest`（默认 = UT + 非 heavy ST + 可达性预检，§3.6）；heavy 单列用户确认。

---

## 相 2：opencode 后端（相 1 冻结后）

### 2.1 抽 SDK 无关共享层
- 从 `sdk_backend.py` 抽出与 claude SDK 无关的 helper（transcript 序列化 / 产物 git-diff 收集 /
  resume 门 / stall 门 / `AgentResult` 构造 / session sidecar）到共享模块，两后端复用。
- `mcp_tools.build_engine_mcp_server`：去 `from claude_agent_sdk import ...` 硬编码，改注入 SDK 模块
  （claude 注 claude_agent_sdk，opencode 注其等价物）。
- 验证：相 1 全测仍绿（纯重构，行为不变）。

### 2.2 OpenCodeBackend
- 新增 `capabilities/agent/opencode_backend.py`：`spawn` 入参 1:1 映射 opencode session/prompt；
  工具名映射表（`Read→read` 等）；`disallowed`→per-agent `permission.{task,question}=deny`；
  skill 经原生 cwd 走查（同一棵扁平树，软链对其冗余无害）；subagent 经 opencode `task`/agents +
  `subagent_depth`；MCP 同名复用。
- 验证：UT（选项/工具名/permission 映射，mock opencode sdk）；`StubBackend` 共用不变。

### 2.3 工厂 + 配置开关（默认 opencode）
- `orchestration-config.json` 增 `agent_backend` 段（默认 `kind="opencode"`）；env `ASCENDC_AGENT_BACKEND` 覆盖。
- `application/` 增 `build_agent_backend(kind, **kw)`；`dispatcher.py` **三处** `SDKBackend(...)` 换工厂调用。
- 验证：UT（工厂按配置/env 选后端）。

### 2.4 双 SDK 验证（用户标准：每步双侧真跑）
- Spike-1 opencode 原生发现 + tail-call；Spike-2 subagent 派发；Spike-3 工具权限（L3 §9）。
- ST `@llm`：**两后端各**一次真实 spawn。heavy_llm：**两后端各**一条端到端链（用户确认后）。

---

## 影响面清单（相 1 触及）
| 模块 | 改动 |
|---|---|
| `resources/orchestration-config.json` | `skills.*` 值裸名 + 新增 `agent_backend`（相 2） |
| `orchestration/skill_config.py` | 扁平扫描 + 裸名唯一性校验 |
| `orchestration/stages/codegen.py` | leading `/<skill>` 裸名 |
| `orchestration/stages/design_substages.py` | 同上（4 处） |
| `orchestration/stages/test_design_substages.py` | 同上 |
| `orchestration/kernel/runner.py` | 删 `plugins=` 构建 |
| `orchestration/stages/precision_debug.py` | `plugins_dir` 引用改扁平 |
| `capabilities/agent/backend.py` | `spawn` 删 `plugins` 形参 |
| `capabilities/agent/sdk_backend.py` | 软链锚点 + 删 `plugins` |
| `capabilities/skill/loader.py` | 删 `PluginLoader`；扁平 canonical |
| `domain/skill.py` | `AgentManifest` 删 `plugins` 字段 |
| `.claude/plugins/` | 迁移后整删 |
| `.claude/skills/` | +32 迁入（2 软链落真身） |
| `CLAUDE.md` | §2.2/§4.1/§4.2/§4.3 修订 |
| `tests/**` | 夹具 `plugin:skill`→裸名 + 扁平布局 |

## 约束核对（补 L3 §11 未覆盖的落地项）
- §1.8：本 L4 冻结配方；进度在 L2 总纲（`skills-integration-and-tdd-plan.md`）挂一行 step。
- §3.11：heavy_llm 不随 `pytest` 自动跑，相 1/相 2 各在交付前由用户确认跑一次。
- 用户标准：相 2 每步 claude + opencode 双侧真跑，不留单边盲区。
