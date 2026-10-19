# L4 — 实施方案：设计门「确定性归一化 + escalation」落地

> 前置契约：`03-artifact-access-contract.md`（authoritative）。本文件按依赖序列出改哪个函数、什么顺序、怎么验证。
> 关联 L3：`02-analysis.md` §2（改动清单）§3（完成判据）。
> 约束：§1.4 不留旧通路（删了 loopback 就删干净）；§3.1 TDD（先写测试）；§3.6 默认全量真实环境。

---

## 实施顺序（依赖序，前一步验证通过再进下一步）

### Step 1 — 修 branch 命名 bug（独立，确定性，无依赖）

**改**：`design_tree.py::_anchor_branch_factory`（157-165）——`name = _template_name(t)` 是死变量，分支名恒为 `"anchor-per-template"`，致 `_anchor_rerun_selector` 返回的 `{"T1"}` 永不命中。

**方案**：`AtomicStage` 目前只收 `stage`、`self.name = stage.name`（`node.py:35`）。两条路选一：
- (a) 给 `AtomicStage` 加 `name=None` override 参数，`_anchor_branch_factory` 传 `AtomicStage(AnchorPerTemplateStage(template=t), name=name)`；
- (b) 对齐 `tiling_branch_factory`，包 `SequentialGroup(name=name, children=[AtomicStage(...)])`。

**验证**：UT 断言 `_anchor_rerun_selector` 命中 `anchor-forkjoin/T1/...` 子树（`graph_executor._invalidate_subtree` 按 targets 清除正确分支）。**注意**：Step 5 若删 loopback，此 bug 不再被触发，但分支命名仍要修——它是 anchor-per-template 复验/产物归属的根基，不能留死变量。

### Step 2 — 确定性 checker 模块（新增，独立）

**改**：新增 `src/ascendc_devkit/orchestration/design_checks.py`，单一入口 `normalize_tiling(products: dict, hw_params) -> (normalized: dict, applied: list[Change])`，`Change` 记 `{file, field, before, after, rule_id, evidence}`（§03 §5.3 可观测）。

**规则清单**（来自 03 §1 表，本批 AC2 抽样）：

| rule_id | 校验 + 归一化 |
|---|---|
| BF16_SORT_SCORE | 排序分数 bf16 必须升宽 fp32（`score=-(float)v`），禁止 Cast 到 fp16（指数域 8→5 溢出） |
| INT64_CHUNK | int64 桶内排序 chunk 必须 ≤24 位（`低24/中24/高8` 三趟），禁止 `(低24,高32)` 两趟 |
| API_EXISTS | 引用的同步/搬运 API 必须在知识库 API 全集中存在（如 `SyncGrid` 不存在 → 归一化/报错） |
| DIV_DOMAIN | `repeatTime=cTile/N` 等整数除法必须覆盖支持域（C=7 非 8 倍数 → 报错，非归一化） |
| HW_CONST | 核数/对齐/hw 常量必须与 `hw_params` 一致（A2 vector_core_cnt） |

**验证**：UT 每规则正例（应归一化/通过）+ 反例（应报错/拒绝）。**注意**：`DIV_DOMAIN`、`HW_CONST` 类"唯一正确解不存在但确定性可判错"的，归入"报错→escalation"，不算归一化——归一化只限"唯一正确解"（§03 §1）。

### Step 3 — checker 接入 producer commit 路径

**改**：`design_substages.py` 的 producer stage（`TilingSplitStage`/`TilingBufferKernelStage`/`TilingPrecisionPerfStage` 的 `transition`，或 `_DesignSubstage` 共享 commit 钩子）——agent 产出 → `_read_disk_artifacts` 读回 → **`normalize_tiling` 归一化** → 归一化结果写 State 同名字段。

**验证**：ST——构造一个产出「bf16 Cast 到 fp16」的 tiling 产物，断言 State 里 `tiling_results` 已是 `score=-(float)v` 的归一化版，且 `applied` 记录了 `Change`。

### Step 4 — 重配三个 gate_scope.json（缩 fix_owner、扩确定性）

**改**：`.claude/skills/<gate>/schema/gate_scope.json` ×3：
- `ascendc-op-general-design-review`：GD-G* 从 `fix_owner=generator` 改为 self_fixable（CR1 字段补全/矛盾改写已含），只剩 `GD-CR2 math 素材缺失→requirement` escalation。
- `ascendc-op-design-anchor-consistency`：`self_fixable_scope` 从「无」改为「AC2 确定性类由 checker 归一化（不在 gate 层面报 blocking）」；`routes` 只剩 `tiling`（architectural escalation）+ `integrate`（advisory）。
- `ascendc-op-design-validate`：`self_fixable_scope` 扩 GV1 字段缺失/GV5 格式/GV10-a 机械重写；`routes` 的 `tiling` 收窄为 architectural-only。

**验证**：加载期校验——`gate_scope` 的 `fix_owner` 路由只剩 architectural/escalation，`self_fixable_scope` 只含确定性规则 id（§03 §6）。

### Step 5 — 删/收 transition table 的 design corrective 边

**改**：`design_tree.py`：
- `_GENERAL_DESIGN_TRANSITION_TABLE` 删 `"redo_generator": ("general-design-generator", "corrective")`（line 40）；
- `_DETAILED_DESIGN_TRANSITION_TABLE` 的 `anchor-consistency` `"infeasible": ("tiling", "corrective")`（line 63）→ 改为 `"architectural": ("tiling", "corrective")`（仅 architectural escalation）；`validate` 的 `"redo_tiling"`（line 89）→ 同样收窄为 architectural。

**验证**：UT 断言 design 组 transition table 无 `redo_generator`/`infeasible`/`redo_tiling` 键（或仅 architectural），且 `graph_executor` 的 stagnation/fail-open 逻辑不回归（该机制保留给 precision/perf 的 escalation）。

### Step 6 — 更新 skills（与 gate_scope 一致，防两套口径）

**改**：
- `ascendc-op-design-anchor-per-template` SKILL.md：从「只读对质，写 blocking_issues」改为「确定性类交给 checker（不在本门报）、语义类判 blast_radius——localized 且唯一正确解→checker 归一化，多解→target=tiling escalation，architectural→escalation」。
- `ascendc-op-general-design-review` / `ascendc-op-design-validate` SKILL.md：同步 §Step 4 的 self_fixable 判据。
- `ascendc-op-design-feedback-selfcheck`：若 loopback 删除后无消费者，按 §2.5 删；否则保留为「归一化复验自检」。

**验证**：skill prose 的「就地修/报 blocking」判据与 gate_scope 逐条一致（对齐 L1 P2 教训——R5 曾出现"代码改了 skill 没跟上"）。

### Step 7 — 下游消费一致性

**改**：
- `integrate`（`IntegrateStage`）：读 `anchor_report.json` 不再有 `blocked` 语义（checker 已归一化、semantic 已 escalation 或 advisory），改为消费归一化 tiling_results + `design_known_issues`（残留 advisory）。
- `validate`（`ValidateStage`）：`_raw_blocking_issues` 不再产 tiling 段 issue（checker 已前置），只剩 advisory/escalation。
- `codegen` / `scope_guard`：不变，回归验证归一化产物能正常进 codegen。

**验证**：ST 端到端——归一化后的 `design_spec.json`/`tiling_strategy.json` 通过 `codegen.validate_inputs`。

### Step 8 — 端到端验收（§03 §3 完成判据）

**验证**：
1. UT：transition table 无 design corrective 边；checker 每规则正反例；rerun_selector 命中。
2. ST：用会触发 AC2 的算子（grid_sampler_3d 的 gather 建模、unique 的 int64 排序）跑 design，断言 `events.jsonl` **无 design 组 loopback 事件**、产物可进 codegen。
3. 回归：既有 R5（删越界门）196 UT、R6（rerun_selector）UT、全量 UT + 非 heavy_llm ST 通过；heavy_llm 列清单待确认（§3.11）。

---

## 完成判据（复述 03 §3，落地即验收）

1. `design_tree.py` design 组无任何 `fix_owner` corrective 边（grep 断言）。
2. 三个 gate_scope.json `self_fixable_scope` 只含确定性规则 id，`fix_owner` 只剩 architectural/escalation。
3. `design_checks.py` 规则清单可枚举、加载期校验（§1.3）。
4. 三门 skill 判据与 gate_scope 一致。
5. events.jsonl 实证 design 零 loopback，产物可进 codegen。
6. 全量 UT + 非 heavy_llm ST 通过。
