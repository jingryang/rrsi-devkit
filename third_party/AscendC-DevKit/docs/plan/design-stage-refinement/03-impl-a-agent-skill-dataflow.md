# step-8 §P1 实施方案 a — agent 角色化 + skill 加载 + 数据流 (c)

> 层级：**L4 / 实施方案**。精确到改哪个函数、怎么改、怎么验证。
> 决策依据见同目录 `02-analysis.md` §P1；问题证据见 `01-problems.md` P1。
> 范围：§P1 全部（角色化 agent / skills 指派透传 / 打开 skills 闸 / 上下文注入 / 数据流 (c)
> 物化+回灌 / 加载期 fail-fast）。是 step-8 其余 L4（b/c/d）的依赖前提。

## 代码落点核实（2026-06-15 实读）

| 关注点 | 现状 | 文件:行 |
|---|---|---|
| `SpawnAgent.skills` 字段 | **已存在**（默认 None），但 design substage 未填 | `kernel/action.py:30` |
| `SpawnAgent.branch_label` | 不存在（§P2 加，本份不动） | — |
| runner 调 backend.spawn | **未传 `skills=`** → 透传链断点① | `kernel/runner.py:388` |
| backend.spawn/`_spawn` 签名 | **已有 `skills` 形参**（默认 None） | `sdk_backend.py:343,354` |
| ClaudeAgentOptions 写 skills | `skills=skills or []` → None 被压成 `[]`=全抑制，断点② | `sdk_backend.py:425` |
| 占位 system prompt 回退 | `"You are {agent_name}…"` 静默降级 | `sdk_backend.py:122` |
| 加载期校验 | `validate_manifest` 仅校验已存在 manifest，**不校验 agent.md 是否存在** | `loader.py:338` |
| design substage 构造 SpawnAgent | 无 `skills=`、`_context` 仅 `{"mode"}`、`working_dir=design/<name>` | `design_substages.py:78-84` |
| 上下文注入源 | State 有 `op_name/op_dir/op_identity/requirement` | `state.py:47-81` |

---

## 任务 1 — 修复 skills 透传链（打开"死"了的 skill 闸）

**目标**：让 stage 指派的 skill 真正进入 `ClaudeAgentOptions.skills`，不再被 `or []` 全抑制。

### 1.1 backend：区分 None 与 []（断点②）

`sdk_backend.py:425`，`ClaudeAgentOptions(...)`：

```python
# 改前
skills=skills or [],
# 改后：None=不过滤(继承 CLI 默认全开)，[]=显式全抑制，list=仅这些
skills=skills,
```

语义依据（CLAUDE.md 已记 + `docs/agent-sdk-ref/skills.md`）：`None` 不做 SDK 自动配置（CLI 默认
保留），`[]` 全抑制，`list[str]` 仅列出项。`skills or []` 把"未指派"误当"全抑制"，是 skill
对所有 agent 失效的直接原因。

> 注意：SDK 在 `skills` 非 None 时会自动把 `"Skill"` 加进 allowed_tools；本仓 allowed_tools 已含
> `"Skill"`（backend 默认 + 角色 agent.md），不冲突。验证见 §1.3。

### 1.2 runner：把 `action.skills` 透传给 backend（断点①）

`kernel/runner.py:388`，`self._agent_backend.spawn(...)` 调用，补 `skills=action.skills`：

```python
agent_result = self._agent_backend.spawn(
    action.agent_name, action.prompt, action.context,
    skills=action.skills,            # ← 新增：透传 stage 指派的 skill 白名单
    plugins=effective_plugins, model=model,
    working_dir=action.working_dir,
    repo_baseline=action.repo_baseline,
    repo_root=action.repo_root)
```

### 1.3 验证

- 单测：构造带 `skills=["stage-design:ascendc-op-tiling-split"]` 的 SpawnAgent，断言透传到
  backend._spawn 收到的 skills 实参（mock backend 或 spy）。
- 真实链路（`@pytest.mark.llm`）：spawn 一个角色 A agent + 指派一个 design skill，断言其 transcript
  出现 `"tool_name": "Skill"` 调用（对照 P1 现状：本次 run 全程零 Skill 调用）。这是 skill 真正
  生效的硬指标。

---

## 任务 2 — 角色化 agent.md（A/B/C 三个新文件）

**目标**：为详设 substage 提供真实 system prompt + plugins 声明，消灭占位提示词降级。
按 `02-analysis.md` §P1 的 A/B/C 角色（按工具/权限 profile，非按子任务 1:1）。

### 2.1 新建三个 agent.md（`.claude/agents/`）

文件名即角色名，被 `design_substages.py` 的 `agent_name` 引用（见任务 3 的 agent_name 改造）：

- `.claude/agents/ascendc-design-generator.md`（角色 A）
- `.claude/agents/ascendc-design-reviewer.md`（角色 B）
- `.claude/agents/ascendc-design-anchor.md`（角色 C）

三者 frontmatter 共性 + 差异（差异即权限）：

```yaml
# A 生成者
---
name: ascendc-design-generator
description: AscendC 详设生成者；按编排指派的 stage-design skill 方法学产出结构化设计产物。
plugins: [stage-design, shared]
allowed_tools: [Read, Write, Edit, Bash, Glob, Grep, Skill, mcp__engine__resolve_ambiguity]
---
# B 评审者：去掉 Write（只就地 Edit 修，不重新创作）
allowed_tools: [Read, Edit, Bash, Glob, Grep, Skill, mcp__engine__resolve_ambiguity]
# C 锚点判定者：禁改产物 → 去掉 Write/Edit
allowed_tools: [Read, Bash, Glob, Grep, Skill, mcp__engine__resolve_ambiguity]
disallowed_tools: [Write, Edit]
```

> C 用 `disallowed_tools: [Write, Edit]` 显式表达"禁改产物"（权限级约束，可测）。
> backend 的 manifest 驱动（`load_agent_manifest`→`eff_allowed/eff_disallowed`）已支持这些字段。

### 2.2 agent.md body = 角色级契约（Pattern 2：不内联方法学）

body 只写：角色定位、职责边界、"你会被编排告知本步要调用的 stage-design skill 与输入产物，
**先调用该 skill 获取方法学**再执行"、产出结构化 JSON 契约、不越界。方法学留在 SKILL.md。

> 关键：body 必须**显式指令调用指派的 skill**，否则模型可能不主动调（Pattern 2 成立的前提，
> 见 §P1 决策）。这条由任务 1.3 的真实链路测试守护。

### 2.3 验证

- `validate_manifest` 对三个新 manifest 无 error（plugins 存在、工具名合法）。
- 加载期校验（任务 4）覆盖：三个角色名都能解析到非占位 system prompt。

---

## 任务 3 — design substage 改 agent_name + 指派 skill + 注入上下文

**目标**：每个 substage 指向角色 agent、显式指派本步 skill、把算子上下文喂进去。
依据 `02-analysis.md` §P1 映射表。

### 3.1 agent_name 改为角色名 + skill 指派集中配置（D7）

两侧分工：**agent_name（角色）写在 Stage 类**（稳定，3 选 1）；**stage→skill 映射集中到
`resources/orchestration-config.json`**（D7：套用 STAGE_MODEL_MAP 范式，不写 stage 类属性）。

(A) `design_substages.py` 各 Stage 类把 `agent_name` 从「skill 名」改为「角色名」：

| Stage | agent_name（角色） | 对应 skill（配在 json，见 B） |
|---|---|---|
| GeneralDesignStage | ascendc-design-generator | stage-design:ascendc-op-general-design |
| GeneralDesignReviewStage | ascendc-design-reviewer | stage-design:ascendc-op-general-design-review |
| TemplateDivisionStage | ascendc-design-generator | stage-design:ascendc-op-design-template-division |
| TilingSplitStage | ascendc-design-generator | stage-design:ascendc-op-tiling-split |
| TilingBufferKernelStage | ascendc-design-generator | stage-design:ascendc-op-tiling-buffer-kernel |
| TilingPrecisionPerfStage | ascendc-design-generator | stage-design:ascendc-op-tiling-precision-perf |
| AnchorCheckStage | ascendc-design-anchor | stage-design:ascendc-op-design-anchor-check |
| IntegrateStage | ascendc-design-generator | stage-design:ascendc-op-design-integrate |
| ValidateStage | ascendc-design-reviewer | stage-design:ascendc-op-design-validate |
| DetailedDesignIntakeStage | ascendc-design-generator | stage-design:ascendc-op-design-intake（D4 新建） |

(B) `resources/orchestration-config.json` 加 `skills` section（stage.name → skill 限定名）：

```json
"skills": {
  "stages": {
    "gd-generate": "stage-design:ascendc-op-general-design",
    "general-design-review": "stage-design:ascendc-op-general-design-review",
    "template-division": "stage-design:ascendc-op-design-template-division",
    "split": "stage-design:ascendc-op-tiling-split",
    "buffer-kernel": "stage-design:ascendc-op-tiling-buffer-kernel",
    "precision-perf": "stage-design:ascendc-op-tiling-precision-perf",
    "anchor-check": "stage-design:ascendc-op-design-anchor-check",
    "integrate": "stage-design:ascendc-op-design-integrate",
    "validate": "stage-design:ascendc-op-design-validate",
    "dd-intake": "stage-design:ascendc-op-design-intake"
  }
}
```

(C) 新建 `orchestration/skill_config.py`（仿 `model_config.py`）加载为 `STAGE_SKILL_MAP`。

(D) `_DesignSubstage.actions()`（:78）按 stage.name 查表指派：

```python
from ascendc_devkit.orchestration.skill_config import STAGE_SKILL_MAP
_skill = STAGE_SKILL_MAP.get(self.name)
actions: list[Action] = [SpawnAgent(
    agent_name=self.agent_name,            # 角色名（写在类）
    prompt=prompt,
    context=self._context(state),
    skills=[_skill] if _skill else None,   # 指派（来自集中配置）
    working_dir=...,
)]
```

> 注：tiling 三段（split/buffer-kernel/precision-perf）按 `self.name`（segment 名）查表，
> 与模板无关——同一 skill 服务该 segment 的所有模板分支。
> §P4 一致性校验：`STAGE_SKILL_MAP` 值集合 ⇄ stage-design 插件实际 skill 集合应一一对应。


### 3.2 上下文注入（消灭"the specific operator wasn't provided"）

`_build_prompt`（:91）与 `_context`（:88）补算子身份 + 上游产物。`_context` 现仅返回
`{"mode": state.mode}`，扩为：

```python
def _context(self, state):
    return {
        "mode": state.mode,
        "op_name": state.op_name,
        "op_dir": str(state.op_dir) if state.op_dir else "",
    }
```

`_build_prompt` 在 sections 头部加一段"## 算子"，注入 `op_name` + `requirement` 摘要（已有
`_previous_decision_section` 模式可循）；tiling segment 已注入 `template`，再补本模板上游 split/
buffer 产物（来自 State `tiling_results`，对应 (c) 物化文件）。

### 3.3 验证

- 单测：各 Stage 的 `actions()` 产出的 SpawnAgent 带正确 `agent_name`（角色）+ `skills`（指派）。
- 单测：`_build_prompt` 输出含 op_name / requirement 摘要（非空算子上下文）。
- 真实链路：gd-generate 不再自述"operator wasn't provided"。

---

## 任务 4 — 加载期 fail-fast：agent_name 必须解析到真实 system prompt

**目标**：杜绝"找不到 agent.md → 静默退回占位 prompt"的隐性降级（P1 根因 3）。

### 4.1 暴露占位降级

`sdk_backend.py:109` `_find_agent_prompt`：现找不到文件返回 `"You are {agent_name}…"`。
新增一个可被校验调用的判定（不改 spawn 期行为，避免运行期硬失败影响兜底）：

```python
def agent_prompt_is_placeholder(agent_name: str) -> bool:
    """True 当 agent.md 缺失、_find_agent_prompt 落到占位回退。"""
    # 复用 _find_agent_prompt 的查找路径；命中真实文件→False，否则→True
```

### 4.2 校验挂点：workflow 启动期

`workflow.validate_chain`（:59）现做 IO 契约静态校验、返回 warnings。新增一项 **error 级**校验
（区别于 warnings）：遍历 `flat_stages()` 里所有 AtomicStage 的 `agent_name`（spawn 型 stage），
凡 `agent_prompt_is_placeholder(name)` 为真 → 收集为启动 error，dispatcher 启动期报错中止。

> 取舍：放在启动期（static）而非 spawn 期（runtime），符合 CLAUDE.md「加载期校验优于运行期暴露」；
> 且避免 spawn 期硬失败破坏既有兜底语义。docgen 无 agent，跳过（其 `actions()` 返回 []）。

### 4.3 验证

- 单测：构造一个引用不存在 agent.md 的 stage → `validate_chain` 返回该 error。
- 单测：三个新角色 agent.md 就位后 → 无 placeholder error。

---

## 任务 5 — 数据流 (c)：产物物化路径规范化 + 单 stage 回灌

**目标**：让磁盘产物成为 State 的确定性投影（按 template 隔离），并支持单步调试从产物文件回灌。

### 5.1 现状：产物已天然落盘

agent 以 `working_dir=artifacts/design/<name>` 为 cwd，用 Write 写产物 —— 物化**已发生**。
(c) 要补的是两点：**(1) 并行分支按 template 隔离路径**（解决 P2 覆盖，本份只定路径；日志归属在 L4-b）；
**(2) 回灌装载器**。

### 5.2 路径规范化（tiling 三段按 template 隔离）

`_TilingSegmentStage.actions()` 的 working_dir 从 `design/<name>`（如 `design/split`）改为
`design/tiling/<template>/`，使 5 个并行分支各写自己的子目录（对齐 §P1 映射表「物化产物路径」列）：

```python
working_dir = state._workspace.artifacts / "design" / "tiling" / self._template_name
```

非 tiling substage 维持 `design/<name>`。transition 解析逻辑不变（仍从 agent_result.artifacts
读，与落盘路径解耦）。

### 5.3 回灌装载器（单 stage 调试）

`dispatcher._build_state_for_stage`（:749，三层合并 from_run→state_file→CLI）**新增一层**：当
`--sources` 指向某 run 的 `artifacts/design/` 时，按映射表「物化产物路径 ⇄ provides 字段」反向重建
State 字段（如读 `design/tiling/<t>/tiling_split.json` → 重建 `tiling_results[t].split`）。

- 实现一个 `design_artifacts_to_state(artifacts_dir) -> dict[field, value]`，复用各 Stage 的
  `artifact_contract().parse()`（已有，避免重写解析），按映射表聚合。
- 优先级：回灌层位于 state_file 之上、CLI flags 之下（盘上产物可被 state_file 覆盖，符合"显式 state 最高"）。

### 5.4 验证

- 单测：5 个 tiling 分支并行后，`design/tiling/<t>/` 各有独立 `tiling_split.json`（无覆盖）。
- 单测：`design_artifacts_to_state` 从一组物化文件正确重建 `tiling_results` / `general_design` 等。
- 端到端：编辑盘上某模板 `tiling_split.json` → `stage run --name anchor-check --sources <dir>` →
  anchor 消费到改后的值（验证回灌驱动调试）。

---

## 实施顺序与整体验收

### 顺序（任务内有依赖）

1. **任务 1**（透传链）—— 最小且无 agent.md 依赖，先打通闸；此时 skills 指派虽空但链路通。
2. **任务 2**（三个 agent.md）—— 提供真实 prompt + plugins。
3. **任务 3**（substage 改 agent_name + 指派 skill + 注入上下文）—— 依赖 1+2。
4. **任务 4**（fail-fast 校验）—— 依赖 2（校验对象是 agent.md 就位）。
5. **任务 5**（路径规范化 + 回灌）—— 与 1-4 解耦，可并行；但建议 3 之后做（路径与映射表对齐）。

### 整体验收（§P1 闭环判据）

- `spawn_context` 事件的 `skills` 字段对详设 agent 从 `[]` 变为 `['stage-design','shared']`
  （对照 P1 现状）。
- 真实链路：详设 agent transcript 出现 `"tool_name": "Skill"` 调用（skill 真正生效）。
- gd-generate 不再凭空猜算子（上下文注入生效）。
- 引用不存在 agent.md 时启动期报错（fail-fast 生效）。
- 5 模板 tiling 产物各自独立落盘、可编辑回灌驱动单 stage 调试（(c) 生效）。
- 既有测试全绿（注意任务 2/3 改 agent_name 后，原以 skill 名作 agent_name 的测试需同步更新；
  与 L4-c 的 ascendc-designer 删除闭包不重叠）。

### 与其他 L4 的边界

- §P2 日志归属（branch_label 透传）、§P3 loopback 摘要、§P6 产物清单 → **L4-b**（依赖本份 5.2 的路径）。
  D8（角色复用下 stage 日志可分辨）并入 L4-b。
- §P4 skill 精选 + D4（删 detailed-design + 建 design-intake）、§P5 删除 ascendc-designer 闭包
  → **L4-c**（依赖本份角色/指派定型）。
- §P7 正确性/健壮性 → **L4-d**（可与本份并行）。

---

## 实施进度（跨会话同步用）

> 编码实施跨多个会话推进；每完成一个任务在此更新状态，新会话据此接续，避免重复/遗漏。
> 行号基于 2026-06-15 实读，实施时以实际代码为准、重新核对。

> ✅ **§P1 已闭环（2026-06-16，见 `03-impl-c-p9-and-cleanup.md`）**：任务 1-5 代码就位后，§P9 揭示本
> CLI（2.1.178）把 plugin skill 暴露为 slash command 而非 `Skill` 工具。按 §P9 拍板方案 2，编排在 design
> substage 的 spawn **首条消息以 `/stage-design:<skill>` 开头**触发 CLI 注入 SKILL.md；并在 L4-c 改写各
> SKILL.md 输入契约（铲除"校验上游完成状态 / 跨读 checkpoint"的 AC0 控制流病根）。真实链路 ST
> `test_skill_invocation.py` 已翻绿（断言 SKILL.md 独有术语进入 agent transcript，150s 1 passed）——
> 证明 skill 设计方法真正进入 agent 上下文。§P1 终极目标达成。下表"已完成"现指代码就位 **且** §P1 闭环。

| 任务 | 状态 | 备注 |
|---|---|---|
| 1 skills 透传链（backend `skills or []`→`skills` + runner 透传 `action.skills`） | 已完成 | sdk_backend.py:425 改 `skills=skills`；runner.py:388 调用补 `skills=action.skills`；新增 TestSpawnAgentSkillsPassthrough（透传 list / None 各一例）；ut 全绿 1108 passed |
| 2 三个角色 agent.md（generator/reviewer/anchor） | 已完成 | `.claude/agents/` 新建三文件（中文 body，Pattern 2 不内联方法学、显式指令先调指派 skill）；A 含 Write、B 去 Write 只 Edit、C `disallowed_tools:[Write,Edit]`；validate_manifest 三者 0 error；_find_agent_prompt 三者均非占位；capabilities ut 124 passed |
| 3 substage 改 agent_name + STAGE_SKILL_MAP + 上下文注入 | 已完成 | 10 个 Stage agent_name 改角色名（generator/reviewer/anchor）；orchestration-config.json 加 `skills.stages`；新建 skill_config.py（STAGE_SKILL_MAP）；base.actions() 按表指派 `skills=[skill]`；`_context` 补 op_name/op_dir；`_build_prompt`+三个 override（gd/intake/tiling）注入「## 算子」+「## 方法学」段；同步更新 test_design_substages/tiling_forkjoin/e2e（改按 skill 归属）；新增 TestContextInjection 4 例；ut+st 1181 passed。注：dd-intake 在 L4-c(D4) 已改指 `stage-design:ascendc-op-design-intake`（见 03-impl-c）；「## 方法学」段在 L4-c 已更名「## 设计方法」并由首消息 slash 触发注入 |
| 4 加载期 fail-fast（validate_chain 加 placeholder 检测） | 已完成 | sdk_backend 新增 `agent_prompt_is_placeholder`（抽出 `_agent_prompt_search_paths`，纯检查不改 spawn 兜底）；workflow 新增 `validate_agents()`（遍历 flat_stages 的静态 agent_name，缺 agent.md → error，去重）；dispatcher 启动期调用，有 error 写 snapshot 后 `EX_CONFIG` 中止；新增 TestValidateAgents 5 例 + 占位检测 2 例；修 test_application mock 补 validate_agents；ut+st 1188 passed |
| 5 数据流 (c)：tiling 路径按 template 隔离 + 回灌装载器 | 已完成 | base 抽 `_working_dir(state)` hook；`_TilingSegmentStage` override 到 `design/tiling/<template>/`（消除 P2 覆盖）；新建 design_artifacts.py（`design_artifacts_to_state` 复用各 stage `artifact_contract().parse()` 反向重建 general_design/template_division/anchor_report/三件套/tiling_results）；dispatcher `_build_state_for_stage` 加 Layer 1.5 回灌（在 from_run 之上、state_file 之下，`--sources` 指向含 design/ 的目录时触发）；新增 test_design_artifacts_reinjection.py 9 例（路径隔离 4 + 回灌 5，含编辑产物驱动调试）；ut+st 1197 passed |

> 决策依据：所有相关决策点（D1-D8、§P5、§P7.2）已在 `02-analysis.md` 拍板。

