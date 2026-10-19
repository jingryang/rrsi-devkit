# anchor-check 重构实施方案（2026-06-25）

> 层级：**L4 / 实施方案**。覆盖 P1（拆 skill+并行+限工具）+ P3（schema 迁 skill 目录）。
> P2（日志行时间戳）是独立的日志 pipeline 改动，另起 `03-impl-log-timestamp.md`。

## 前置条件

`SchemaLoader.load_contract_from_skill(plugin, skill, filenames)` **已存在**
（`adapters/schema/loader.py:100-109`），step-10 时为 test_design/requirement 的
单-skill schema 场景预留。本次只需让 design skill 也走这条路径。

---

## Phase 1: Schema 迁入 skill 目录（P3）

### 1.1 搬迁 schema 文件

对 12 个单-skill 独享的 schema（见 L3 归属表），将 JSON 从
`plugins/stage-design/schema/` 搬到 `plugins/stage-design/skills/<skill>/schema/`。

```bash
# 伪脚本，实际每个 skill 一一对应
# ascendc-op-general-design          → general_design.json
# ascendc-op-general-design-review   → general_design_reviewed.json
# ascendc-op-design-template-division→ template_division.json
# ascendc-op-tiling-split            → tiling_split.json
# ascendc-op-tiling-buffer-kernel    → tiling_buffer_kernel.json
# ascendc-op-tiling-precision-perf   → tiling_precision_perf.json
# ascendc-op-design-anchor-check     → anchor_report.json
# ascendc-op-design-integrate        → design_spec.json, tiling_strategy.json,
#                                      kernel_architecture.json, data_flow.json
# ascendc-op-design-docgen           → design_doc.json
# ascendc-op-design-validate         → blocking_status.json

for skill in ascendc-op-general-design ...; do
  mkdir -p "plugins/stage-design/skills/$skill/schema"
  cp "plugins/stage-design/schema/${MAPPING[$skill]}" \
     "plugins/stage-design/skills/$skill/schema/"
done
```

> `tiling_results.json` 是 ForkJoin 工程聚合产物，非 skill 产出，删掉不搬。

### 1.2 更新 SKILL.md 引用路径

每份 SKILL.md 输出表格行的 schema 引用路径从 `../../../schema/<name>.json` →
`schema/<name>.json`。受影响文件：

| 文件 | 改动 |
|------|------|
| `ascendc-op-general-design/SKILL.md` | `schema/general_design.json` |
| `ascendc-op-general-design-review/SKILL.md` | `schema/general_design_reviewed.json` |
| `ascendc-op-design-template-division/SKILL.md` | `schema/template_division.json` |
| `ascendc-op-tiling-split/SKILL.md` | `schema/tiling_split.json` |
| `ascendc-op-tiling-buffer-kernel/SKILL.md` | `schema/tiling_buffer_kernel.json` |
| `ascendc-op-tiling-precision-perf/SKILL.md` | `schema/tiling_precision_perf.json` |
| `ascendc-op-design-anchor-check/SKILL.md` | `schema/anchor_report.json` |
| `ascendc-op-design-integrate/SKILL.md` | `schema/design_spec.json` 等 4 个 |
| `ascendc-op-design-docgen/SKILL.md` | `schema/design_doc.json` |
| `ascendc-op-design-validate/SKILL.md` | `schema/blocking_status.json` |
| `ascendc-op-design-intake/SKILL.md` | `schema/design_spec.json` 等 4 个（读 integrate 的 schema） |

> 注意：`ascendc-op-design-intake` 与 `integrate` 共享 4 个 schema（design_spec 等），
> intake 的 SKILL.md 不搬 schema 文件，只把引用路径改为指向 integrate skill 的 schema
> 子目录的**相对路径**：`../ascendc-op-design-integrate/schema/design_spec.json`。

### 1.3 更新 DevKit 加载路径

所有 design substage 的 `artifact_contract()` 从
`load_contract_from_plugin("stage-design", [...])` →
`load_contract_from_skill("stage-design", skill_name, [...])`。

以 `GeneralDesignStage` 为例：

```python
# 改前：
def artifact_contract(self) -> ArtifactContract:
    return SchemaLoader.load_contract_from_plugin("stage-design", ["general_design.json"])

# 改后：
def artifact_contract(self) -> ArtifactContract:
    return SchemaLoader.load_contract_from_skill(
        "stage-design", "ascendc-op-general-design", ["general_design.json"])
```

所有改动位置（`design_substages.py`）：

| 行号 | Stage | 新 skill_name |
|------|-------|---------------|
| 418 | GeneralDesignStage | `ascendc-op-general-design` |
| 506 | GeneralDesignReviewStage | `ascendc-op-general-design-review` |
| 574 | DetailedDesignIntakeStage | `ascendc-op-design-intake` |
| 681 | TemplateDivisionStage | `ascendc-op-design-template-division` |
| 707 | AnchorCheckStage | `ascendc-op-design-anchor-check`（Phase 3 会改为新 stage） |
| 757 | IntegrateStage | `ascendc-op-design-integrate` |
| 941 | ValidateStage | `ascendc-op-design-validate` |
| 1035 | `_TilingSegmentStage.artifact_contract` | 动态：`STAGE_SKILL_MAP.get(self.name)` 提取 skill 名 |

`_TilingSegmentStage.artifact_contract` 特殊处理：

```python
# 改前：
def artifact_contract(self) -> ArtifactContract:
    return SchemaLoader.load_contract_from_plugin("stage-design", [self.schema_file])

# 改后：
def artifact_contract(self) -> ArtifactContract:
    # 三个 tiling 子阶段的 schema 各在各自 skill 的 schema/ 下
    skill = STAGE_SKILL_MAP.get(self.name, "")
    if not skill:
        return SchemaLoader.load_contract_from_plugin("stage-design", [self.schema_file])
    return SchemaLoader.load_contract_from_skill("stage-design", skill, [self.schema_file])
```

### 1.4 删除共享 schema 目录

`rm -rf .claude/plugins/stage-design/schema/`（14 个 JSON 已全部迁出）。

### 1.5 更新测试

`tests/ut/adapters/test_schema_loader.py` + `tests/ut/adapters/test_design_schemas.py`
中的 `load_spec_from_plugin("stage-design", ...)` 调用改为 `load_spec_from_skill`。
测试 fixture 常量增加 stage-design skill 名映射，与 `orchestration-config.json` 的
`skills.stages` 一致。

### 1.6 验证

```bash
# 单元测试全绿
pytest tests/ut/adapters/test_schema_loader.py tests/ut/adapters/test_design_schemas.py -v

# 确认 plugin/schema/ 目录已空
ls .claude/plugins/stage-design/schema/ 2>&1  # 应为 No such file or directory

# 确认所有 skill 目录 schema 就位
for d in .claude/plugins/stage-design/skills/*/; do
  echo "$d: $(ls "$d/schema/" 2>/dev/null || echo 'no schema')"
done
```

---

## Phase 2: 拆分 SKILL.md 与新增 schema（P1-a）

### 2.1 新建 Skill A: `ascendc-op-design-anchor-per-template`

**目录结构**：

```
plugins/stage-design/skills/ascendc-op-design-anchor-per-template/
  SKILL.md
  schema/
    anchor_template_report.json
```

**`anchor_template_report.json` schema**：

```json
{
  "required": true,
  "required_keys": ["status"],
  "description": "per-template anchor 报告。对单个模板的 tiling claims 做硬件 API 可行性对质（AC0/AC1/AC2），产出该模板的阻断/告警项。",
  "example": {
    "status": "blocked",
    "template_name": "T1_Half",
    "blocking_issues": [
      {"code": "AC2", "severity": "blocker", "detail": "声称标量 gather 但 Gather 指令明文可用", "target": "tiling", "target_template": "T1_Half"}
    ]
  }
}
```

**`SKILL.md`**：从现 `ascendc-op-design-anchor-check/SKILL.md` 剪裁，保留：

- 步骤 0（但只收集**当前模板**的 claims）
- 步骤 1 骨架 API 判定（保留，但判定范围限定为当前模板）
- 步骤 2 硬件 API 对质（AC1/AC2）——核心内容，逐 claim 独立查证
- AC3 per-template 部分（该模板自身的 dtype/搬运/workspace 惯例）
- 输出文件：`anchor_template_report.json`，schema 路径 `schema/anchor_template_report.json`
- 约束：硬件参数真值表（UB 240KB 等）不变，以常量嵌入 SKILL.md

明确添加约束：

> **禁止搜索**：你不需要 `Glob` / `Grep`。当前工作目录中**只**有这一个模板的 tiling 产物
> （`tiling_current_template.json`），直接 Read 即可。硬件参数真值表已在本 skill 给出，
> 不需查文档。

### 2.2 新建 Skill B: `ascendc-op-design-anchor-consistency`

**目录结构**：

```
plugins/stage-design/skills/ascendc-op-design-anchor-consistency/
  SKILL.md
  schema/
    anchor_report.json          ← 从 plugin/schema/ 搬来（Phase 1 已搬）
```

**`anchor_report.json`** 不变（与当前一致）。

**`SKILL.md`**：从现 `ascendc-op-design-anchor-check/SKILL.md` 保留：

- 骨架 API 语义判定（步骤 1，算子级全局判断）
- 跨模板 AC3 一致性（TilingKey 定义不冲突、workspace 分配不重叠、dtype 路由表一致）
- 汇总所有 per-template `anchor_template_report.json` 的 blocking_issues + 跨模板 findings
- 输出：`anchor_report.json`

明确添加约束：

> **禁止搜索**：你不需要 `Glob` / `Grep`。所有需要对质的文件已在工作目录中
> （`anchor_template_reports.json` + `tiling_shared_summary.json`），直接 Read。
> 没有 `code_constraints.md` 时直接标 N/A，不要搜索。

### 2.3 `orchestration-config.json` 新增技能注册

```json
"skills": {
  "stages": {
    ...
    "anchor-forkjoin":   "stage-design:ascendc-op-design-anchor-per-template",
    "anchor-consistency": "stage-design:ascendc-op-design-anchor-consistency"
  }
}
```

### 2.4 验证

```bash
# TUI 自闭环测试（per-template skill 单独跑）
cd /tmp && mkdir anchor-test && cd anchor-test
cp /path/to/tiling_current_template.json .
# 在 Claude Code TUI 中输入 /stage-design:ascendc-op-design-anchor-per-template
# 预期：Read tiling_current_template.json → 逐 claim 对质 → 产出 anchor_template_report.json
# 确认：没有 Glob/Grep 调用，没有目录遍历，纯 Read + Skill 完成
```

---

## Phase 3: Pipeline 拓扑变更（P1-b）

### 3.1 新增 State 字段

`kernel/state.py` L109 后新增：

```python
anchor_template_reports: list | None = None   # per-template anchor reports (ForkJoin)
```

### 3.2 新增 `AnchorPerTemplateStage`

`design_substages.py` 新增（放在 `AnchorCheckStage` 之前，复用 `_TilingSegmentStage`
的 per-template 模式）：

```python
class AnchorPerTemplateStage(_DesignSubstage):
    """Per-template anchor: 对单个模板的 tiling claims 做硬件 API 对质 (Skill A)."""

    name = "anchor-per-template"
    description = "Per-template external feasibility gate (AC0/AC1/AC2 + per-template AC3)"
    agent_name = "ascendc-design-anchor"
    prompt_intro = ("对质单个模板的 tiling 产物与真实硬件 API（不改产物）。"
                    "不可实现项写 blocking_issues（AC0/AC1/AC2，target=tiling）。"
                    "只审查当前模板，不跨模板。")

    def __init__(self, template=None):
        self.template = template or {}

    @property
    def _template_name(self) -> str:
        t = self.template
        if isinstance(t, dict):
            return str(t.get("name", ""))
        return str(t)

    def input_contract(self) -> StageIOContract:
        return StageIOContract(requires=["tiling_results"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["anchor_template_reports"])

    def artifact_contract(self) -> ArtifactContract:
        return SchemaLoader.load_contract_from_skill(
            "stage-design", "ascendc-op-design-anchor-per-template",
            ["anchor_template_report.json"])

    def _upstream_inputs(self, state: "State") -> dict:
        # 只物化当前模板的 tiling 产物 — 不传全量 169KB
        this_template = (getattr(state, "tiling_results", None) or {}).get(
            self._template_name, {})
        if this_template:
            return {"tiling_results_current_template": this_template}
        return {}

    def _working_dir(self, state):
        if not state._workspace:
            return None
        return (state._workspace.artifacts / "design" / "anchor"
                / self._template_name)

    def _branch_label(self) -> str:
        return self._template_name

    def transition(self, state, result):
        # 上报 per-template report → ForkJoin merge 聚合为 anchor_template_reports 数组
        new_state, ok = self._parse_single(
            state, result, "anchor_template_report", "anchor_template_report.json")
        if not ok:
            return new_state
        # 把 per-template report 包装进 State.anchor_template_reports
        report = getattr(new_state, "anchor_template_report", None)
        prev_reports = list(getattr(new_state, "anchor_template_reports", None) or [])
        if report:
            prev_reports.append(report)
        return new_state.with_field("anchor_template_reports", prev_reports)
```

### 3.3 新增 `AnchorConsistencyStage`

```python
class AnchorConsistencyStage(_DesignSubstage):
    """Cross-template anchor: 汇总 per-template 报告 + 跨模板一致性 (Skill B)."""

    name = "anchor-consistency"
    description = "Cross-template consistency gate + blocking_issues aggregation"
    agent_name = "ascendc-design-anchor"
    prompt_intro = ("听取各模板独立对质结论，判跨模板一致性（TilingKey / workspace / dtype 路由），"
                    "合并 per-template blocking_issues 为最终 anchor_report。"
                    "不合规项写 blocking_issues（AC3 跨模板部分，target=tiling）。")
    fail_strategy = "continue"

    def input_contract(self) -> StageIOContract:
        return StageIOContract(requires=["tiling_results", "anchor_template_reports"])

    def output_contract(self) -> StageIOContract:
        return StageIOContract(provides=["anchor_report"])

    def artifact_contract(self) -> ArtifactContract:
        return SchemaLoader.load_contract_from_skill(
            "stage-design", "ascendc-op-design-anchor-consistency",
            ["anchor_report.json"])

    def _upstream_inputs(self, state: "State") -> dict:
        anchor_reports = getattr(state, "anchor_template_reports", None) or []
        # 剪裁 tiling_results：只提 TilingData 共享字段 / TilingKey / workspace（~8KB）
        shared = self._extract_shared_summary(state)
        return {
            "anchor_template_reports": anchor_reports,
            "tiling_shared_summary": shared,
        }

    @staticmethod
    def _extract_shared_summary(state) -> dict:
        """提取跨模板一致性所需的共享字段摘要，不传全量 169KB。"""
        tr = getattr(state, "tiling_results", None) or {}
        summary = {}
        for tmpl, segments in tr.items():
            entry = {}
            for seg in ("split", "buffer_kernel", "precision_perf"):
                s = segments.get(seg, {})
                if not isinstance(s, dict):
                    continue
                # 只提取共享字段：TilingData / TilingKey / workspace / dtype
                entry[seg] = {
                    k: s[k] for k in (
                        "tiling_data_fields", "tiling_key", "workspace",
                        "compute_dtype", "dtype", "buffer_allocation",
                    ) if k in s
                }
            if entry:
                summary[tmpl] = entry
        return summary or {}

    def transition(self, state, result):
        new_state, _ = self._parse_single(
            state, result, "anchor_report", "anchor_report.json")
        return new_state

    def resolve_condition(self, state) -> str:
        return AnchorCheckStage.resolve_condition(self, state)

    def blocking_issues(self, state) -> list[dict]:
        return AnchorCheckStage.blocking_issues(self, state)

    def loopback_feedback(self, state) -> dict | None:
        return AnchorCheckStage.loopback_feedback(self, state)

    def is_satisfied(self, state) -> bool:
        return AnchorCheckStage.is_satisfied(self, state)
```

### 3.4 `design_tree.py` 改动

新增 `_build_anchor_forkjoin_node()`：

```python
def _anchor_branch_factory(state) -> list:
    """每模板一个 per-template anchor branch (Skill A)."""
    division = getattr(state, "template_division", None) or {}
    templates = division.get("templates", [])
    branches = []
    for t in templates:
        name = _template_name(t)
        branches.append(AtomicStage(AnchorPerTemplateStage(template=t)))
    return branches


def _build_anchor_forkjoin_node() -> ForkJoinGroup:
    return ForkJoinGroup(
        name="anchor-forkjoin",
        branch_factory=_anchor_branch_factory,
        input_contract_override=StageIOContract(requires=["tiling_results"]),
        output_contract_override=StageIOContract(provides=["anchor_template_reports"]))
```

修改 `build_detailed_design_group()` children：

```python
# 改前：
children = [
    ...
    AtomicStage(AnchorCheckStage()),
    AtomicStage(IntegrateStage()),
    ...
]

# 改后：
children = [
    ...
    _build_anchor_forkjoin_node(),
    AtomicStage(AnchorConsistencyStage()),
    AtomicStage(IntegrateStage()),
    ...
]
```

更新 `_DETAILED_DESIGN_TRANSITION_TABLE`：

```python
# 改前：
"anchor-check": {
    "infeasible": ("tiling", "corrective"),
},

# 改后：
"anchor-consistency": {
    "infeasible": ("tiling", "corrective"),
},
```

### 3.5 新增 import

`design_tree.py` 的 import 增加：

```python
from ascendc_devkit.orchestration.stages.design_substages import (
    ...,
    AnchorPerTemplateStage,   # 新增
    AnchorConsistencyStage,   # 新增
)
```

### 3.6 验证

```bash
# 单元测试
pytest tests/ut/orchestration/ -v -k "anchor or tiling or forkjoin"

# 集成测试
pytest tests/st/ -v -k "design"

# 端到端（不传 --stage-timeout，验证 anchor 不再超时）
ascendc-devkit run --workflow generate_ascendc --op-dir .../rotary_position_embedding \
  --npu-id 0 --non-interactive --on-decision default \
  --requirement tests/fixtures/rope_requirements.md \
  --golden tests/fixtures/rope_golden.py
```

---

## Phase 4: 工具权限收紧（P1-c）

### 4.1 Agent manifest 改动

`ascendc-design-anchor.md`（两个 skill 共用同一 agent）：

```yaml
# 改前：
allowed_tools:
  - Read
  - Bash
  - Glob
  - Grep
  - Skill
  - mcp__engine__resolve_ambiguity

# 改后：
allowed_tools:
  - Read
  - Skill
disallowed_tools:
  - Write
  - Edit
```

- 移除 `Bash`、`Glob`、`Grep`、`mcp__engine__resolve_ambiguity`。
- 两个新 skill 的 CWD 文件契约已明确，不需要搜索工具。

### 4.2 验证

```bash
# 确认 agent manifest 解析正确
pytest tests/ut/ -v -k "agent.*manifest" 2>/dev/null || \
  python -c "
from ascendc_devkit.adapters.agent.manifest_loader import load_agent_manifest
m = load_agent_manifest('ascendc-design-anchor')
assert 'Glob' not in m.allowed_tools, f'Glob should be removed: {m.allowed_tools}'
assert 'Grep' not in m.allowed_tools, f'Grep should be removed: {m.allowed_tools}'
print('OK: allowed_tools =', m.allowed_tools)
"
```

---

## 改动文件汇总

| 文件 | Phase | 改动类型 |
|------|-------|---------|
| `plugins/stage-design/skills/*/schema/`（12 个目录） | 1 | 新建目录 + 搬入 schema JSON |
| `plugins/stage-design/skills/*/SKILL.md`（11 个） | 1 | 路径 `../../../schema/` → `schema/` |
| `plugins/stage-design/schema/` | 1 | **删除** |
| `design_substages.py`（8 个 `artifact_contract()`） | 1 | `load_contract_from_plugin` → `load_contract_from_skill` |
| `tests/ut/adapters/test_schema_loader.py` | 1 | 调用从 plugin root 改为 skill root |
| `tests/ut/adapters/test_design_schemas.py` | 1 | 同上 |
| `plugins/stage-design/skills/ascendc-op-design-anchor-per-template/` | 2 | **新建** SKILL.md + schema/ |
| `plugins/stage-design/skills/ascendc-op-design-anchor-consistency/` | 2 | **新建** SKILL.md + schema/ (anchor_report.json 从 Phase 1 搬来) |
| `orchestration-config.json` | 2 | skills.stages 新增两行 |
| `kernel/state.py` | 3 | 新增 `anchor_template_reports` 字段 |
| `design_substages.py` | 3 | 新增 `AnchorPerTemplateStage` + `AnchorConsistencyStage` |
| `design_tree.py` | 3 | 新增 `_build_anchor_forkjoin_node()`，修改 `build_detailed_design_group()` |
| `ascendc-design-anchor.md` | 4 | allowed_tools 移除 Glob/Grep/Bash |

## 执行顺序

Phase 1 → Phase 2 → Phase 3 → Phase 4 必须严格按序：

1. **Phase 1 先做**：schema 搬迁是纯文件搬动 + 路径替换，不涉及逻辑变更，先把地基铺好。
2. **Phase 2 后做**：新 skill 的 schema 直接放在各自的 `schema/` 子目录下（Phase 1 已建立的约定）。
3. **Phase 3 再做**：pipeline 拓扑依赖新 stage 类和 ForkJoin 节点——前面的 schema 和 skill 必须就位。
4. **Phase 4 最后做**：工具权限收紧是安全兜底，放在最后不影响前面的逻辑正确性。

每 phase 完成后跑一次 `pytest tests/ut/ -v` 确保无回归。
