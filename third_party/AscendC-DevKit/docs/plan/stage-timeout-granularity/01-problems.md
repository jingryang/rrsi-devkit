# stage 超时粒度 — L1 问题记录（2026-06-24）

> 层级：**L1 / 问题记录**。只陈述「哪里坏了、凭什么这么说」（证据/现象/根因/影响）。
> 方案分析见 `02-analysis.md`（L3）；实施方案见 `03-impl-*.md`（L4）。

本记录基于最近一次本地执行：

- **日志文件**：`logs/20260625.log`
- **运行命令**：`ascendc-devkit run --workflow generate_ascendc --op-dir .../rotary_position_embedding --stage-timeout 600 ...`
- **算子**：RotaryPositionEmbedding
- **总耗时**：~2087s（anchor-check 超时时截断），exit code 124

---

## P1（严重）：anchor-check 单 agent 审查 3 模板 169KB 全量上下文，执行时间 614s 远超 600s budget

### 证据

日志第 906 行：

```
[ERROR] Timeout: Stage 'anchor-check' timeout: exceeded 600s budget (ran 614.4s)
```

anchor-check 阶段数据画像：

| 指标 | 数值 |
|------|------|
| `tiling_results.json` 总大小 | **169 KB**（2539 行） |
| 模板数 | 3（T1_Half + T2_Interleave + T3_InterleaveHalf） |
| iteration 1 turns | 87（292.6s），后期单 turn 50K+ chars，15-20s/turn |
| iteration 2 turns | 65（321.8s），后期单 turn 57K+ chars，20-30s/turn |
| 累计耗时 | 614.4s |

同时 `ascendc-design-anchor` agent 的 `allowed_tools` 含 `Glob` + `Grep`，
agent 在对话中自行搜索文件系统，搜索轮次不产出审查结论，每轮浪费 3-5s。

### 根因

1. **上下文膨胀**：3 模板 × 3 段产物 169KB 全部注入 1 个 agent，每 turn 携带 50K+ chars 历史。
2. **agent 自行搜索**：`Glob` + `Grep` 让 agent 遍历目录、搜索代码仓，纯消耗时间。
3. **单 agent 串行审查全部模板**：没有利用多模板天然可并行的特性。

### 影响

1. 600s budget 不够，必然超时。
2. 未来 5 模板、10 模板场景下线性恶化。
3. 超时后无有效审查结果，后续 integrate 在断链上继续。

---

## P2（中等）：日志内容每行没有时间戳，无法知道每步发生的时间

### 证据

`logs/20260625.log` 中每一条日志行均无时间前缀。典型行格式：

```
═══ INSTALL — pip install -e (editable) @ /home/x00584171/code/AscendC-DevKit ═══
  • agent_stream requirement-analyst turn 1 (budget 10000/query), 99 chars, 3.1s
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ ✓ generate_ascendc/detailed-design/tiling/T1_Half/split/split done (374.8s)
[ERROR] Timeout: Stage 'anchor-check' timeout: exceeded 600s budget (ran 614.4s)
```

### 根因

日志写入 pipeline 未在每行输出前添加时间戳格式化。

### 影响

1. 无法从日志行直接看出某阶段何时开始、何时结束。
2. 多日志对比时只能靠阶段名和 turn 号手动对齐。
3. 排查超时需要借助文件名和 `/tmp/` 内部日志的时间戳手动推算。

---

## P3（中等）：skill schema 不随 skill 目录走，违背第一准则 #3

### 证据

14 个 design stage 的 schema 文件全部集中存放在
`.claude/plugins/stage-design/schema/`（plugin 根目录），不在各 skill 目录内：

```
.claude/plugins/stage-design/
  schema/                          ← 共享目录，所有 skill 共用
    anchor_report.json
    tiling_split.json
    general_design.json
    ...（共 14 个）
  skills/
    ascendc-op-design-anchor-check/
      SKILL.md                     ← 引用 ../../../schema/anchor_report.json
    ascendc-op-tiling-split/
      SKILL.md                     ← 引用 ../../../schema/tiling_split.json
    ...（12 个 skill 目录均无 schema 子目录）
```

SKILL.md 中引用路径为 `../../../schema/<name>.json`（如 anchor-check SKILL.md 第 42-44 行）。

step-10（第一准则对齐）L4-a 将 schema 从 `resources/schemas/` 迁到 plugin 根目录后
标记为"已完成"，但 **schema 随 plugin 目录走 ≠ 随 skill 目录走**。把任意一个 skill
目录单独提取到 Claude Code TUI，它没有自己的 schema 文件，无法知道输出 JSON 的
required_keys 和结构。

### 根因

step-10 L4-a 的"收敛到 plugin 根目录"是一次正确的解耦，但只做了半程——没有继续下发
到每个 skill 的 `schema/` 子目录。DevKit 的 `SchemaLoader.load_contract_from_plugin()`
按 `plugin/schema/<filename>` 路径加载，不支持 `plugin/skills/<skill>/schema/<filename>`。

### 影响

1. **第一准则 #3 未完全满足**："schema 文件随 skill 目录走"只做到了 plugin 级，
   skill 级仍未满足。
2. **skill TUI 自闭环受阻**：单独拿出一个 skill 目录时，schema 缺失，
   用户/模型不知道输出 JSON 的结构要求。
3. **新增 skill 容易欠债**：马上要新增 anchor-per-template 和 anchor-consistency
   两个 skill，它们的 schema 如果放进共享 `schema/` 目录又在欠债；
   如果放进 skill 目录则与其他 skill 不一致（一半随 skill、一半在共享目录）。
4. **各 schema:skill 天然 1:1**（14 个 schema 中 12 个是单 skill 独享，
   仅 integrate 的 4 个与 dd-intake 共享），目录拆分是纯粹机械的搬动，
   不存在"共享 schema 往哪个 skill 放"的争议。

---

## P4（低）：`_DesignSubstage` 当前按单 skill 组织（`_assigned_skill()` → `str | None`），无法在同 stage 内调用多个 skill

### 证据

框架底层 `SpawnAgent.skills` 已是 `list[str] | None`（`action.py:30`），SDK backend
透传的三态语义完备（`None`=继承所有 plugin skill，`[]`=禁用全部，`list[str]`=仅暴露指定
skill）。但编排层 `_DesignSubstage` 调用约定为单 skill：

```python
# design_substages.py:100-118
def _assigned_skill(self) -> str | None:
    return STAGE_SKILL_MAP.get(self.name)   # 值类型为 str

def actions(self, state, iteration=1):
    skill = self._assigned_skill()
    actions = [SpawnAgent(
        skills=[skill] if skill else None,   # 包装为单元素列表
        ...
    )]
```

### 根因

`STAGE_SKILL_MAP` 的值类型约定为 `str`（如 `orchestration-config.json` 中
`"anchor-check": "stage-design:ascendc-op-design-anchor-check"`）。要支持多 skill 只需：
`_assigned_skill()` → `_assigned_skills()` 返回 `list[str]`，`STAGE_SKILL_MAP`
值类型兼容 `str | list[str]`。改动量约 5 行，框架本体无阻。

### 影响

对本次 anchor-check 拆分为两阶段**无影响**——per-template 和 consistency 的输入/输出/
拓扑都不同（先 ForkJoin 后串行），天然就是两个 stage。多 skill 同 stage 适用于"同一组输入、
产出同一组输出、但需要两种不同审查视角"的场景（如未来 codegen 阶段同时跑语法检查 + 规范检查），
届时再启用本能力即可。

---

## P5（低）：`_schema_files` 仍硬编码在 Python stage class 中，schema 文件名也存在双重来源

### 证据

`_DesignSubstage` 新增的 `artifact_contract()` 从 `STAGE_SKILL_MAP` 取 skill 名（✅ 单一来源），
但 `_schema_files` 仍在各子类中硬编码（❌ Python 中写死文件名）：

```python
# design_substages.py
class GeneralDesignStage(_DesignSubstage):
    _schema_files = ["general_design.json"]        # 硬编码

class IntegrateStage(_DesignSubstage):
    _schema_files = ["design_spec.json", "tiling_strategy.json",   # 硬编码
                     "kernel_architecture.json", "data_flow.json"]
```

而事实上这些文件恰好都在对应 skill 的 `schema/` 目录下，1:1 对应，完全可自动发现：

```
plugins/stage-design/skills/
  ascendc-op-general-design/schema/       → general_design.json
  ascendc-op-design-integrate/schema/     → design_spec.json + tiling_strategy.json + ...
  ...（10/12 skill 的 schema 文件与 _schema_files 声明完全一致）
```

### 根因

`artifact_contract()` 需要 `ArtifactSpec` 的**顺序**来控制 prompt 中输出要求段的渲染顺序
（如 integrate 的 4 个 schema 先 design_spec 后 data_flow）。自动 `glob("*.json")` 的排序不
保证稳定（字母序 vs 业务序可能不一致）。因此当前写成显式列表——但显式列表本身就是新硬编码。

### 影响

- P3（schema 迁 skill 目录）的收益被部分稀释：schema 文件从 Python 硬编码的 plugin root
  迁到了 skill 目录，但 stage 类仍然硬编码文件名。
- 新增/删除 schema 文件时，skill 目录和 stage 类要同步改（两处）。
- 但这仍然比 Phase 1 之前好：之前是 **skill 名 + 文件名** 双重硬编码，现在只剩文件名。
  
### 未来解法方向

1. `artifact_contract()` 默认 `glob` skill 的 `schema/*.json` 自动发现。
2. 对需要非字母序的 stage（如 integrate），提供一个可选的 `_schema_file_order: list[str]`
   仅用作排序键，不重复声明文件存在性。
3. 或者更进一步：在 `orchestration-config.json` 的 `skills.stages` 中约定每个 stage 的
   schema 文件列表，与 skill 名放在同一份配置。

暂不解决，记录为后续优化项。

---

## 问题汇总矩阵

| 问题 | 严重度 | 影响范围 | 证据密度 |
|------|--------|----------|----------|
| P1 anchor-check 614s 超时 | 严重 | design 阶段可靠性 + 总耗时 | 912 行日志 |
| P2 日志行缺时间戳 | 低 | 日志可读性/排查效率 | 全日志 900+ 行 |
| P3 schema 不随 skill 目录 | 中等 | 第一准则合规 + TUI 自闭环 | 14 个 schema 文件位置 |
| P4 stage→单 skill 限制 | 低 | 扩展性（暂不影响本次） | `_assigned_skill()` 返回 `str\|None` |
| P5 `_schema_files` 仍硬编码 | 低 | 文件名双来源 | 各 stage 类中 `_schema_files = [...]` |

---

## 证据索引

| 证据 | 来源 |
|------|------|
| `--stage-timeout 600` CLI 参数 | 日志第 58 行 |
| anchor-check timeout 614.4s > 600s | 日志第 906 行 |
| exit code 124 (EX_TIMEOUT) | 日志第 909 行 |
| iteration 1: 87 turns / 292.6s, iteration 2: 65 turns / 321.8s | 日志第 750-906 行 |
| tiling_results.json 169KB | `output/20260625-033205-c539d9/artifacts/design/anchor-check/` |
| allowed_tools 含 Glob+Grep | `.claude/agents/ascendc-design-anchor.md` |
| 全 912 行日志均无 `[HH:MM:SS]` 前缀 | 日志全文 |
| 14 schema 在 `stage-design/schema/` 不在 skill 目录 | `.claude/plugins/stage-design/schema/` |
| SKILL.md 引用 `../../../schema/` | 各 SKILL.md 输出表格行 |
