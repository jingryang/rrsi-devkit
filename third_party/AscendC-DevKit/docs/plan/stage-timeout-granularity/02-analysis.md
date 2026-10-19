# stage 超时粒度 — L3 方案分析（2026-06-25）

> 层级：**L3 / 方案分析**。只陈述「有哪些选项、选了哪个、为什么」。
> 问题记录见 `01-problems.md`（L1）；实施方案见 `03-impl-*.md`（L4）。

---

## 背景：anchor-check 为什么这么慢

### 数据画像

| 指标 | 数值 |
|------|------|
| `tiling_results.json` 总大小 | **169 KB**（2539 行） |
| 模板数 | 3（T1_Half + T2_Interleave + T3_InterleaveHalf） |
| 每模板产物段 | 3 段（split + buffer_kernel + precision_perf） |
| iteration 1 turns | 87（292.6s），后期单 turn 50K+ chars |
| iteration 2 turns | 65（321.8s），后期单 turn 57K+ chars |
| 累计耗时 | 614.4s |

### 两大根因

**根因 1：上下文规模** — 169KB 全量产物注入 1 个 agent，
每 turn 携带 50K+ chars 历史上下文重新发送。

**根因 2：agent 自行搜索** — `ascendc-design-anchor` agent 的
`allowed_tools` 含 `Glob` + `Grep`，agent 在对话中会自行搜索文件/CWD 结构，
这些搜索轮次不产出审查结论，纯粹消耗时间和 token。

---

## 方案选型：拆 Skill -> 并行 -> 限工具

核心：先把 SKILL.md 拆成两个 skill，各自明确只读什么文件、禁止搜索，
再在 pipeline 层做 per-template 并行。

---

## 第一步：当前输入输出对齐状况诊断

### 现状

```
上游提供：tiling_results (State 字段, dict[str,dict])
     | _materialize_inputs
  CWD 文件：tiling_results.json (169KB, 3模板全量)
     | agent Read + Glob + Grep (可以搜索 CWD 外的东西)
  产出：anchor_report.json
```

**问题 1**：`_materialize_inputs` 写入的是全量 169KB 文件，没有 per-template 裁剪。

**问题 2**：`allowed_tools` 含 `Glob` + `Grep`。agent 可以 `ls artifacts/design/tiling/`
遍历其他模板的目录，可以 `grep -r UB_SIZE` 搜索整个代码仓——这些搜索轮次
不产出审查结论，每轮浪费 3-5s。

**问题 3**：SKILL.md 写法暗示了搜索行为——"用 `ascendc-dev-knowledge` 自己查一遍"、
"对照 `code_constraints.md` / 目标仓同类算子"——如果文件不存在 agent 会反复 grep。

---

## 第二步：SKILL.md 按 per-template vs cross-template 拆开

当前 SKILL.md 的 5 个步骤：

### 步骤归属表

| 步骤 | 工作 | 依赖 | 归属 |
|------|------|------|------|
| 0 | 收集所有模板 claims | 全部模板 | Skill B |
| 1 | 骨架 API 语义判定 | 算子级 | Skill B |
| 2 | 硬件 API 对质 (AC1/AC2) | **单模板独立** | **Skill A** |
| 3 | 仓库范式 (AC3) | 拆两半 | per-template 部分->A, 一致性->B |
| 4 | 汇总 blocking_issues | 所有报告 | Skill B |
| 5 | 输出自检 | 最终产物 | Skill B |

---

### Skill A: ascendc-op-design-anchor-per-template

**职责**：对单个模板的 claims 逐条对照硬件 API 文档做可行性判定
（AC0/AC1/AC2）+ 该模板自身的 AC3 仓库范式检查。

**输入文件（CWD，由工程层 _materialize_inputs 写入）**：

| 文件 | 大小 | 说明 |
|------|------|------|
| `tiling_current_template.json` | ~50KB | **仅当前模板**的 split+buffer_kernel+precision_perf。字段名 `tiling_results_current_template`，复用 `_INPUT_FILENAMES` 已有条目 |

**不写的文件**：
- `tiling_results.json`（全局 169KB 全量——不写）
- `template_division.json`（per-template 审查不需要知道其他模板）
- `general_design.json`（硬件 API 对质只看 tiling claims）

**不允许的搜索行为**：
- 禁止 Glob：CWD 已明确只有 `tiling_current_template.json`，不需要遍历
- 禁止 Grep：要查数据直接 Read 该文件
- 硬件参数真值表（UB 大小等）写在 SKILL.md 中作为常量——不需要搜索

**输出文件**：

| 文件 | schema |
|------|--------|
| `anchor_template_report.json` | 新增：`{status, template_name, blocking_issues}` |

**State 输出契约**：`provides=["anchor_template_reports"]`

---

### Skill B: ascendc-op-design-anchor-consistency

**职责**：骨架 API 语义判定 + 跨模板一致性检查 + 汇总 per-template 报告。

**输入文件（CWD）**：

| 文件 | 大小 | 说明 |
|------|------|------|
| `anchor_template_reports.json` | ~5KB | N 个 per-template report 的聚合数组 |
| `tiling_shared_summary.json` | ~8KB | 工程层从 `tiling_results` 剪裁生成：每模板 TilingData 共享字段、TilingKey 路由表、workspace 分配、dtype 路由概要。**不传全量 169KB** |

**明确不读的文件**：
- 不读 per-template 的 `tiling_current_template.json`
- 不读 `general_design.json`、`template_division.json`

**输出文件**：`anchor_report.json`（与当前 schema 一致）

**State 输出契约**：`provides=["anchor_report"]`

---

### 两 Skill 的 Schema 对齐

```
  tiling (ForkJoin)
       | tiling_results (State, dict)
  anchor-forkjoin (ForkJoin: N x Skill A)
       | anchor_template_reports (State, list[dict])    <- 新增 State 字段
  anchor-consistency (Skill B)
       | anchor_report (State, dict)                    <- 现有字段，不变
  integrate
       | consumes ["tiling_results", "anchor_report"]   <- 现有契约，不变
```

`integrate` 当前 `requires=["tiling_results", "anchor_report"]` —— **不变**。

---

## 第三步：工具权限收紧 —— 禁止 agent 自行搜索

### 现状

```
allowed_tools: [Read, Bash, Glob, Grep, Skill, mcp__engine__resolve_ambiguity]
                                    ------- --------
                                    浪费时间的搜索工具
```

### 收紧方案

**Skill A（per-template）和 Skill B（consistency）统一收紧**：

```yaml
allowed_tools:
  - Read      # 只读 CWD 中已提供的文件
  - Skill     # 调用 ascendc-dev-knowledge 等知识库 skill
  - Bash      # 仅用于 cat > file 写产物
disallowed_tools:
  - Write
  - Edit
  - Glob      # 不需要遍历目录
  - Grep      # 不需要搜索——要查数据直接 Read 指定文件
```

### SKILL.md 中搜索语义去重

- "用 `ascendc-dev-knowledge` 自己查一遍" -> 这是 `Skill` 工具调用知识库，**保留**。
- "对照 `code_constraints.md` / 目标仓同类算子" -> 如果文件不存在直接在
  prompt_intro 中声明 "本 op 无存量代码，AC3 仓库范式项标 N/A"，避免 agent
  反复 grep 找不到后自行推断浪费时间。
- 硬件参数真值表（UB 大小等）直接写在 SKILL.md 常量区 —— **不查文件，不当变量**。

---

## 第四步：Pipeline 拓扑

```python
# build_detailed_design_group() 变更后：

children = [
    AtomicStage(DetailedDesignIntakeStage()),
    AtomicStage(TemplateDivisionStage()),
    _build_tiling_node(),                  # ForkJoin (现有不变)
    _build_anchor_forkjoin_node(),         # ForkJoin: N x Skill A (新增)
    AtomicStage(AnchorConsistencyStage()), # Skill B (新增, 取代原 AnchorCheckStage)
    AtomicStage(IntegrateStage()),
    ...
]
```

### _build_anchor_forkjoin_node() 设计

复用 `ForkJoinGroup` + `branch_factory` 模式（与 tiling ForkJoin 一致）。
每个 branch 的 `_materialize_inputs` 只取 `tiling_results[{template}]`
写入 `tiling_current_template.json` —— 只物化 50KB，不写全量 169KB。

### AnchorPerTemplateStage

- `agent_name = "ascendc-design-anchor"`（复用现有 agent）
- `_working_dir`: `design/anchor/<template>/`（每模板独立子目录，与 tiling 段同模式）
- `output_contract`: `provides=["anchor_template_reports"]`
- `transition`: 上报 per-template `anchor_template_report.json`

### AnchorConsistencyStage

- `agent_name = "ascendc-design-anchor"`（复用）
- `_materialize_inputs`: 写入 `tiling_shared_summary.json`（剪裁版，~8KB）+ `anchor_template_reports.json`
- `output_contract`: `provides=["anchor_report"]`（与当前 AnchorCheckStage 一致）
- `resolve_condition` / `is_satisfied` / `blocking_issues` / `loopback_feedback`
  逻辑与原 `AnchorCheckStage` 相同，无需改动。

---

## 时序预估

```
                       /-- per-template (T1_Half, 50KB, ~25t)  75s  \
tiling_results --------+-- per-template (T2_Interleave, 50KB)  85s  +-- consistency (8KB, ~15t) 45s = ~130s
                       \-- per-template (T3_InterleaveHal)     80s  /
                                   ForkJoin 并行, 无 Glob/Grep         串行, 无 Glob/Grep
```

**614s -> ~130s，约 4.7x 改善。** 节省来自三方面：
1. 上下文从 169KB -> 50KB/模板（~3.4x 减少）
2. 去掉 Glob/Grep 搜索轮次（每模板节省 5-10 轮无效 turn）
3. 3 模板并行（墙钟取最长，~3x）

---

## 第五步：Schema 随 skill 目录走（P3 — 第一准则 #3 收官）

### 问题

step-10 L4-a 将 schema 从 `resources/schemas/` 迁到了
`.claude/plugins/stage-design/schema/`（plugin 根），但**没有**
迁到每个 skill 自己的目录。这是第一准则 #3（"schema 文件随 skill 目录走"）
的最后一公里欠账。

### 现状

```
.claude/plugins/stage-design/
  schema/                          <- 14 个 JSON，所有 skill 共享
    anchor_report.json
    tiling_split.json
    ...
  skills/
    ascendc-op-design-anchor-check/
      SKILL.md                     <- 引用 ../../../schema/anchor_report.json
    ...（12 个 skill 目录均无 schema 子目录）
```

DevKit 加载路径：`SchemaLoader.load_contract_from_plugin("stage-design", ["<file>"])`
→ 读 `plugins/stage-design/schema/<file>`。

### 各 schema 与 skill 的归属（1:1 为主）

| schema | 归属 skill | 共享？ |
|--------|-----------|--------|
| `anchor_report.json` | `ascendc-op-design-anchor-check`（→ 拆后归 consistency） | 否 |
| `tiling_split.json` | `ascendc-op-tiling-split` | 否 |
| `tiling_buffer_kernel.json` | `ascendc-op-tiling-buffer-kernel` | 否 |
| `tiling_precision_perf.json` | `ascendc-op-tiling-precision-perf` | 否 |
| `template_division.json` | `ascendc-op-design-template-division` | 否 |
| `general_design.json` | `ascendc-op-general-design` | 否 |
| `general_design_reviewed.json` | `ascendc-op-general-design-review` | 否 |
| `blocking_status.json` | `ascendc-op-design-validate` | 否 |
| `design_doc.json` | `ascendc-op-design-docgen` | 否 |
| `design_spec.json` | `ascendc-op-design-integrate` | 与 dd-intake 共享 |
| `tiling_strategy.json` | `ascendc-op-design-integrate` | 与 dd-intake 共享 |
| `kernel_architecture.json` | `ascendc-op-design-integrate` | 与 dd-intake 共享 |
| `data_flow.json` | `ascendc-op-design-integrate` | 与 dd-intake 共享 |
| `tiling_results.json` | ForkJoin 工程聚合产物（非 skill 产出） | N/A |

**12/14 是单 skill 独享**，仅 integrate 的 4 个 schema 与 dd-intake 共享。
共享场景的解法：放一个 skill、另一个 skill 的 SKILL.md 声明从同级的 schema/ 读取。

### 方案（与 anchor-check 拆分为同一批改动）

#### 目标目录结构

```
ascendc-op-design-anchor-consistency/    # Skill B
  SKILL.md
  schema/
    anchor_report.json                  <- 从 plugin/schema/ 搬来

ascendc-op-tiling-split/
  SKILL.md
  schema/
    tiling_split.json                   <- 从 plugin/schema/ 搬来

...（同理，12 个单-skill schema 各归其主）

ascendc-op-design-integrate/
  SKILL.md
  schema/
    design_spec.json                    <- 4 个 schema 归 integrate skill
    tiling_strategy.json                <- dd-intake 的 SKILL.md 引用
    kernel_architecture.json              integrate/schema/ 下的文件
    data_flow.json
```

#### DevKit 端改动

1. `SchemaLoader` 新增 `load_contract_from_skill(plugin, skill, filenames)`：
   从 `plugins/<plugin>/skills/<skill>/schema/<filename>` 读取。
2. 各 substage 的 `artifact_contract()` 改为按 skill 名加载：
   `SchemaLoader.load_contract_from_skill("stage-design", skill_name, [files])`。

   > 注意：tiling split / buffer-kernel / precision-perf 三个 substage
   > 的 `artifact_contract()` 当前用 `self.schema_file`（`TilingSplitStage.schema_file =
   > "tiling_split.json"`），改为按 skill 名加载后 skill 名可从
   > `STAGE_SKILL_MAP[self.name]` 提取。

3. 删除 `.claude/plugins/stage-design/schema/` 目录（14 个文件已各归其主）。

#### SKILL.md 端改动

所有 SKILL.md 中 `../../../schema/<name>.json` → `schema/<name>.json`。

> anchor-check 拆分后：新增的 `anchor_template_report.json` schema
> 直接放在 `ascendc-op-design-anchor-per-template/schema/` 下，
> 避免欠新债。

### 评估

| 维度 | 判断 |
|------|------|
| 必要性 | **必须**：第一准则 #3 是合规硬约束 |
| 风险 | 低：schema:skill 映射是 1:1 的机械搬动，无逻辑判断 |
| 时机 | 与 anchor-check 拆分同一批改动最合理：新增 skill 的 schema 直接放对位置，存量 skill 同时搬迁 |
| 与现有功能冲突 | 无：DevKit 的 `SchemaLoader` 改加载路径不影响（TUI 场景则完全依赖 skill 内文件） |

---

## 需要改动的文件清单

| 文件 | 改动 |
|------|------|
| `design_substages.py` | 新增 `AnchorPerTemplateStage` + `AnchorConsistencyStage`；all substage `artifact_contract()` 改为 `load_contract_from_skill` |
| `design_tree.py` | 新增 `_build_anchor_forkjoin_node()`；修改 `build_detailed_design_group()` children；更新 `_DETAILED_DESIGN_TRANSITION_TABLE` |
| `orchestration-config.json` | `skills.stages` 新增 `anchor-forkjoin` / `anchor-consistency` 注册 |
| `kernel/state.py` | 新增 `anchor_template_reports: list | None = None` 字段 |
| `.claude/agents/ascendc-design-anchor.md` | `allowed_tools` 移除 `Glob`、`Grep` |
| `.claude/plugins/stage-design/skills/ascendc-op-design-anchor-per-template/` | 新建 SKILL.md + `schema/anchor_template_report.json` |
| `.claude/plugins/stage-design/skills/ascendc-op-design-anchor-consistency/` | 新建 SKILL.md + `schema/anchor_report.json`（从 plugin/schema 搬来） |
| `.claude/plugins/stage-design/skills/ascendc-op-tiling-split/schema/` 等 12 个 skill 目录 | 各搬入自己的 schema JSON；SKILL.md 路径更新为 `schema/<name>.json` |
| `.claude/plugins/stage-design/schema/` | 删除（14 个文件已各归其主） |
| `adapters/schema/loader.py` | 新增 `load_contract_from_skill()` + `load_spec_from_skill()`；原 `load_contract_from_plugin` 保留兼容旧路径 |
| `.claude/agents/ascendc-design-anchor.md` | `allowed_tools` 移除 `Glob`、`Grep`，只保留 `Read`、`Bash`、`Skill` |
| `design_substages.py` | 新增 `AnchorPerTemplateStage` + `AnchorConsistencyStage` |
| `design_tree.py` | 新增 `_build_anchor_forkjoin_node()`；修改 `build_detailed_design_group()` children |
| `orchestration-config.json` | `skills.stages` 新增两个 skill 注册 |
| `kernel/state.py` | 新增 `anchor_template_reports: list | None = None` 字段 |
