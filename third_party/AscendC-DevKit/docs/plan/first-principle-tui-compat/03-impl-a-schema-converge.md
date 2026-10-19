# step-10 L4-a — schema 收口：删旧根 + design 迁 plugin 根 / requirement 迁 skill 目录（2026-06-17）

> 层级：**L4 / 实施方案**。依据 `02-analysis.md`（§收口纪律 2 + §收敛-2 分发单元=plugin）。
> 这是纪律二的**强制收口**：step-9 引入的「skill-dir 根 + `resources/schemas/` 旧根」并存到此终结，
> 收敛到唯一 `*_from_skill`/`*_from_plugin` 通路，删除 `resources/schemas/` + `_SCHEMAS_ROOT` +
> `load_spec`/`load_contract`。

## 已核实 schema→producer 映射（源码实证）

| schema 文件 | 产出 substage / skill | 归属 |
|---|---|---|
| general_design.json | gd-generate / ascendc-op-general-design | design plugin 根 |
| general_design_reviewed.json | general-design-review | design plugin 根 |
| template_division.json | template-division | design plugin 根 |
| tiling_split/buffer_kernel/precision_perf.json | 三 tiling segment | design plugin 根 |
| anchor_report.json | anchor-check | design plugin 根 |
| **design_spec/tiling_strategy/kernel_architecture/data_flow.json** | **integrate + dd-intake（两 skill 共产）** | design plugin 根（不可归单 skill） |
| blocking_status.json | validate | design plugin 根 |
| tiling_results.json | 聚合产物（reflow `_rebuild_tiling_results` 用 segment 的 artifact_contract，非单独 load） | design plugin 根 |
| design_doc.json | docgen（确定性渲染，无 agent；无 artifact_contract load；仅 test 校验） | design plugin 根 |
| requirement.json | requirement / ascendc-op-req-analysis | requirement skill 目录 |

> 结论：design 是单 plugin 内紧耦合流水线、含两-skill 共产与聚合/确定性产物 → 统一放
> **plugin 根** `.claude/plugins/stage-design/schema/`（convergence-2：分发单元=plugin，"取出即完整"）。
> requirement 单 skill 单 schema → 其 skill 目录（与 testdesign 同规则）。

## 改动清单

1. **SchemaLoader**：新增 `load_spec_from_plugin(plugin, filename)` / `load_contract_from_plugin`
   （根 = `.claude/plugins/<plugin>/schema/`）。复用 `_build_spec`/`_read_schema_json`。
2. **迁移文件**：14 个 `resources/schemas/design/*` → `.claude/plugins/stage-design/schema/`；
   `resources/schemas/requirement/requirement.json` → `ascendc-op-req-analysis/schema/`。
3. **call sites**：design_substages.py 9 处 `load_contract("design", …)` → `load_contract_from_plugin("stage-design", …)`；
   requirement.py 1 处 → `load_contract_from_skill("stage-requirement", "ascendc-op-req-analysis", …)`。
   tiling segment 用 `self.schema_file`（基类 artifact_contract）同改。
4. **删旧通路（纪律二）**：删 `_SCHEMAS_ROOT`、`load_spec`、`load_contract`；删 `resources/schemas/` 目录。
5. **reflow**：`design_artifacts.py` 走各 stage 的 `artifact_contract().parse()`，自动跟随（无独立路径）。
6. **测试**：`test_design_schemas.py`/`test_schema_loader.py` 改用新 loader；§P4 校验已泛化（step-9）不受影响。
7. **收口验收**：`grep -rn "resources/schemas\|_SCHEMAS_ROOT\|load_contract(\|load_spec("` src/ 应为 0。

> **范围边界（实施时踩到，记录备查）**：`resources/schemas/repository/profile.json` **不在本收口范围**——
> 它是仓库 YAML profile 的 **JSON-Schema 校验器**（`ProfileLoader._PROFILE_SCHEMA_PATH` 用），不是 skill
> 的 I/O 契约（不随任何 skill 分发、不经 SchemaLoader）。第一准则只约束「skill 产物 schema」。`rm -rf
> resources/schemas` 会误删它（已从 git 恢复）；只删 `design/` + `requirement/` 子目录即可。

## 实施状态（2026-06-17）：✅ 已实施并验证
- SchemaLoader 加 `load_spec_from_plugin`/`load_contract_from_plugin`；删 `_SCHEMAS_ROOT`/`load_spec`/`load_contract`。
- 14 design schema → `.claude/plugins/stage-design/schema/`；requirement → 其 skill `schema/`；删
  `resources/schemas/{design,requirement}`（保留 repository/）。
- 9 个 design call site → `*_from_plugin`，requirement → `*_from_skill`。
- 收口验收 grep：src/ 无 live 旧引用（仅 docstring 提及）。
- 验证：全量 UT 1259 passed；design pipeline + reflow 回灌 ST 15 passed；无回归。

## 验证
- 红→绿：schema loader 新法测 + design schema 自校验测；reflow 回灌测；§P4。
- 全量 UT + design/test_design stub ST 无回归。
