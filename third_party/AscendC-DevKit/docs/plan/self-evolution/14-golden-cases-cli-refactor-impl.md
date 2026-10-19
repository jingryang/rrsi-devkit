# L4 实施方案 — golden/cases 来源改 CLI 显式 + golden 全链路正名

> **性质**：L4 实施方案。改哪个函数、什么顺序、怎么验证。动手前写。
> **上游**：`13-golden-cases-cli-refactor.md`（L3，E1–E7 已定案）；覆盖 `06-problems.md` **P11 / P12**，修订 `11/12` 的 source 层。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line）。TDD：先改/加测试再改实现（CLAUDE.md 3.1）。全量 UT + ST 必须全绿，npu/llm/slow 不跳过（3.2/3.4）。
> **两层分离（13 §0）**：consumer 层（harness golden 加载段、`parse_cann_bench_csv`）不动；只改 source 层（来源从 profile 预置 → CLI 显式）+ 删代换/探测通路。

---

## 0. 改动总览（按依赖顺序）

| 步 | 改动 | 归属 | 依赖 |
|---|---|---|---|
| **B1** | State 增 `golden_entry` / `golden_input_type` / `cases_path` 三标量 + `from_snapshot` 默认 | E3 | — |
| **B2** | CLI 增 `--golden-entry` / `--golden-input-type` / `--cann-bench-cases` + task_request 键 | E1/E2 | B1 |
| **B3** | dispatcher：golden 三参进声明式必选（`_USER_INPUT_FIELDS`/`_FIELD_HELP`）；消费 golden 的 stage 把 `golden_path` 写进 `requires`；**删** `_preflight_input_topology` 的 golden→verify 规则；State 构造取新参 | E4/E6 | B1,B2 |
| **B4** | verify `_resolve_golden_contract` 改为读 State 三标量；删 profile.golden_source 分支 + `resolve_task_level` 调用 | E1 | B1,B3 |
| **B5** | `cases_loader.load_cases` 签名简化为 `(cases_path)` 直读 `parse_cann_bench_csv`；删 `CasesSource`/format 分派 | E1/E2 | B1 |
| **B6** | test_design：`_has_external_cases` 改判 `state.cases_path` 非空；`_load_external_cases` 用 `cases_path`；删 `_task_level`/`resolve_task_level` | E1 | B1,B5 |
| **B7** | 删 profile source 层：schema `profile.json` 删 `golden_source`/`cases_source` 段；`RepositoryProfile` 删字段 + `_parse_golden_source`/`_parse_cases_source` + 枚举常量 | E1 | B4,B6 |
| **B8** | 删 `GoldenSource`/`CasesSource` dataclass + `.resolve()` + `resolve_task_level`（consumer 已迁移） | E1/2.5 | B4,B5,B6,B7 |
| **B9** | `cann-bench.yaml` 删 source 块（先于 B7 schema 删，避免加载炸）；e2e 脚本 golden 改必传 + 三参 + cases；workflow 注释更新；测试收口 | E1 | B7,B8 |

顺序建议 **B1→B2→B3→B4→B5→B6→B7→B8→B9**。关键耦合：B7（删 schema 段）与 B9（删 yaml source 块）必须**同步**——schema `additionalProperties:false`，旧 yaml 仍含 source 会加载失败（先删 yaml 块，再删 schema 段）。B8 必须在 B4/B5/B6（consumer 迁移）之后，否则删 `GoldenSource`/`CasesSource` 留悬空引用。

---

## 步 B1：State 增 golden/cases 标量（E3）

**文件**：`orchestration/kernel/state.py`（`State`）。

**改动**：
1. `State` 增三个标量（与既有 `golden_path` 配套，不再是 profile 代换出的契约对象）：
   - `golden_entry: str = ""`（源 golden 的入口函数名，如 `exp`）
   - `golden_input_type: str = ""`（`torch` / `numpy`，空串=未指定）
   - `cases_path: Path | None = None`（外部用例 CSV 绝对路径）
2. `from_snapshot` 的"新字段默认值"清单补 `("golden_entry", "")`、`("golden_input_type", "")`、`("cases_path", None)`，旧快照零回归。

**验证**（TDD 先行）：
- UT：`State(golden_entry="exp", golden_input_type="torch", cases_path=...)` 构造；`to_snapshot`/`from_snapshot` round-trip 保留三值；旧快照（无三字段）加载得到默认值。

## 步 B2：CLI 增 golden/cases 参数（E1/E2）

**文件**：`cli/commands/run.py`（`run_cmd`）。

**改动**：
1. 增三个 click option（参数名编码语义，E2）：
   - `--golden-entry`（`golden_entry`，str）
   - `--golden-input-type`（`golden_input_type`，`click.Choice(["torch","numpy"])`——CLI 层枚举校验，E3/E5 dispatch 期语法校验）
   - `--cann-bench-cases`（`cases_path`，`click.Path(exists=True)`——path 存在性 CLI 拦，E3/E5）
2. `task_request` dict 增 `"golden_entry"`/`"golden_input_type"`/`"cases_path"` 三键。
3. `--golden`（既有 `golden_path`）保留不变。

**验证**：
- UT：`run` 命令解析 `--golden-entry exp --golden-input-type torch --cann-bench-cases x.csv` → task_request 含三键；非法 `--golden-input-type cuda` → click 枚举拒绝。

## 步 B3：dispatcher 声明式必选 + 删拓扑规则（E4/E6）

**文件**：`application/dispatcher.py`（`_USER_INPUT_FIELDS`/`_FIELD_HELP`/`_preflight_user_inputs`/`_preflight_input_topology`/`dispatch` 的 State 构造）。

**改动**：
1. **声明式必选（E6）**：
   - `_USER_INPUT_FIELDS` 增 `golden_path`/`golden_entry`/`golden_input_type`（golden 三参进用户输入集合）。
   - `_FIELD_HELP` 增 golden 三参的人读说明。
   - **消费 golden 的 stage 把 `golden_path` 写进其 `input_contract().requires`**：**verify** 与 **`GeneralDesignStage`（general-design-generator）** 都写入（D-1 定案 (a)：design 也 require golden，含 SE）。由此 `_preflight_user_inputs` 的 `candidates = required_by_stages & _USER_INPUT_FIELDS` 自然把 golden 列为 hard_missing：凡含 general-design 或 verify 的 workflow 即必选，切换可选↔必选只改 stage 的 `requires` 声明（声明式，满足 E6 灵活性）。
   - **三参配套校验（E3 不猜测）**：`golden_path` 已 present 但 `golden_entry`/`golden_input_type` 缺失（或反之）→ 追加一条明确报错"golden 三参必须配套提供"，并入 hard_missing 输出。
2. **删拓扑规则（E4）**：`_preflight_input_topology._RULES` 删 `("golden_path", "verify", "--golden", ...)` 一条——golden 非 verify 专属，design-only/SE workflow 亦可传 golden。`--detailed-design`→codegen 规则保留。
3. **State 构造**：`dispatch` 组装 State 时从 task_request 取 `golden_entry`/`golden_input_type`/`cases_path`（与既有 `golden_path` 同处）。

**验证**：
- UT：含 verify 的 workflow 缺 golden 三参 → hard_missing 报错并列项；三参齐全 → 通过；`golden_path` 有但 entry 缺 → 配套报错。
- UT：删拓扑规则后，无 verify 的 workflow 传 `--golden` 不再被拒。
- UT：声明式切换——把 golden 从某 stage 的 `requires` 移到 `optional`，该 workflow 即不再强制（验证机制灵活性）。

## 步 B4：verify 读 State 三标量（E1）

**文件**：`orchestration/stages/verify.py`（`_resolve_golden_contract`）。

**改动**：
1. `_resolve_golden_contract` 改为**直接读 State 三标量**（`state.golden_path`/`golden_entry`/`golden_input_type`）构造 harness golden 契约（`{source_path, entry, input_type}`）。
2. **删** profile 分支（`profile.golden_source` 优先级 / `.resolve()` 代换）与 `resolve_task_level` 调用——source 已由 CLI 进 State，verify 不再回 profile。
3. 三标量任一缺失（且该 workflow 要求 golden）→ 由 B3 的 dispatch 期必选拦截；若运行期仍缺（如旧快照 resume）→ 明确报错，不退化为无 golden 桩（PrecisionGate 既有的 `golden_contract is None → passed=False` 诚实报错保留）。

**验证**：
- UT：State 三标量齐全 → 构造出正确契约（entry/input_type 透传）；无 profile 分支代码残留。
- ST（@npu）：cann-bench golden 经 State 三标量（entry=`exp`、input_type=torch）适配后，verify 真比对（max_diff 非恒 0）——consumer 机制不变，复用既有 ST。

## 步 B5：cases_loader 签名简化（E1/E2）

**文件**：`domain/cases_loader.py`（`load_cases`）。

**改动**：
1. `load_cases(cases_path: Path) -> list[TestCase]`——**直接** `parse_cann_bench_csv(cases_path)`。
2. **删**：`CasesSource`/`op_name`/`repo_root`/`level` 参数、`{op}`/`{N}` 代换、format 分派（`_KNOWN_FORMATS`）、未知 format 报错分支。参数名 `--cann-bench-cases` 已在 CLI 层编码格式（E2），loader 内不再分派。
3. `parse_cann_bench_csv` / `_DTYPE_MAP` / `_value_range_to_gen` / `_loads_or` / `_map_dtype` **保留**（consumer 层，13 §0）。

**验证**：
- UT：`load_cases(<exp cases.csv>)` → TestCase 列表（shape/dtype/attrs 齐全）；签名只剩 `cases_path`。

## 步 B6：test_design 用 cases_path（E1）

**文件**：`orchestration/stages/test_design_substages.py`（`_TestDesignSubstage._task_level`/`_has_external_cases`、`TestCaseGenStage._load_external_cases`）。

**改动**：
1. `_has_external_cases` 改判 **`state.cases_path` 非空**（替代"`cases_source` present 且 task 存在"）。
2. `_load_external_cases` 改为 `load_cases(state.cases_path)`（B5 新签名）。
3. **删** `_task_level`（`resolve_task_level` 探测）——`{N}` 代换已随 source 层删除；cases 路径由用户 CLI 直接给出绝对路径。
4. `actions()` 的 NoOp 分支（有外部 cases 时不调 LLM）维持，触发条件改判 `state.cases_path`。

**验证**：
- UT：`state.cases_path` 非空 → `_has_external_cases=True`、走 loader 填 `test_cases`（不调 LLM）；空 → 维持 LLM 设计。
- ST（@npu/@slow）：self_evolve_op（CLI 传 cases_path）下 test_design 加载 cann-bench cases（含 attrs 非默认分支）。

## 步 B7：删 profile source 层（E1）

**文件**：`resources/schemas/repository/profile.json`、`domain/repository.py`（`RepositoryProfile`/加载校验）。

**改动**（**先做 B9 的 yaml 块删除，再做本步**——见总览耦合说明）：
1. `profile.json` 删 `golden_source`/`cases_source` 两个 properties（`additionalProperties:false` 已就位，删字段即收紧）。
2. `RepositoryProfile` 删 `golden_source`/`cases_source` 字段。
3. 删 `_parse_golden_source`/`_parse_cases_source` 及其加载期校验。
4. `_KNOWN_INPUT_TYPES`/`_KNOWN_CASES_FORMATS` 枚举常量：input_type 枚举迁到 CLI（B2 的 `click.Choice`）；cases format 不再需要（参数名编码）。删常量。

**验证**：
- UT：profile 含 `golden_source`/`cases_source` → 加载失败（schema 拒，`additionalProperties:false`）；不含 → 加载成功。
- UT：`RepositoryProfile` 无 source 字段；`_parse_golden_source`/`_parse_cases_source` 已删。

## 步 B8：删 GoldenSource/CasesSource/resolve_task_level（E1/2.5）

**文件**：`domain/repository.py`。

**改动**（consumer 已在 B4/B5/B6 迁移完毕，此时删无悬空引用）：
1. 删 `GoldenSource` dataclass + `.resolve()`（`{op}`/`{N}` 代换）。
2. 删 `CasesSource` dataclass + `.resolve()`。
3. 删 `resolve_task_level`（`{N}` 存在性探测）——单算子 run 通路不再需要；批量工具未来自带算子→层级映射（E7）。

**验证**：
- UT：`GoldenSource`/`CasesSource`/`resolve_task_level` 符号已不存在（grep 全仓无引用）。
- 全量 UT/ST 绿（确认无残留 import/调用）。

## 步 B9：cann-bench.yaml + e2e + workflow 注释 + 测试收口（E1）

**文件**：`resources/repository-profiles/cann-bench.yaml`、`scripts/e2e_self_evolve.sh`、`orchestration/workflow.py`、测试。

**改动**：
1. **cann-bench.yaml**：删 `golden_source`/`cases_source` 块（**先于 B7 schema 删**）。
2. **e2e_self_evolve.sh**：
   - `GOLDEN` 从"可选（留空走 profile）"改为**必传**；新增 `GOLDEN_ENTRY`（默认 `exp`）、`GOLDEN_INPUT_TYPE`（默认 `torch`）、`CASES`（cann-bench cases.csv 路径）。
   - `ARGS` 增 `--golden-entry`/`--golden-input-type`/`--cann-bench-cases`；删"GOLDEN 留空则走 profile"分支与注释。
3. **workflow.py**：`self_evolve_op` 根部注释里"`cases_source`/`golden_source`"措辞改为"CLI 显式 golden 三参 + cases"。
4. **测试收口**：
   - 删/改依赖 profile source 的旧 ST（如"profile 声明 source → 自动消费"类），改为 CLI 显式传参的 ST。
   - 保留并迁移：exp 真机 ST（golden 契约 torch 路径、cases.csv 解析）改为从 State 三标量/cases_path 驱动。
   - generate_ascendc 回归：无 cases（test_design LLM）、golden 三参显式（必选），不受 profile 删除影响。

**验证**：
- UT 全绿；ST（@npu/@slow/@llm）全绿：self_evolve_op（CLI 显式 golden 三参 + cases）exp 端到端——① verify 跑 cann-bench 用例 + golden，② cannbench_eval 出 overall_score。
- 回归：generate_ascendc / generate_ascendc_se 维持各自语义（golden 必选性按其 stage requires 声明）。

---

## 测试影响面（TDD 先行）

- `tests/ut/orchestration/`（State）：三标量构造/快照 round-trip。
- `tests/ut/cli/`（run）：`--golden-entry`/`--golden-input-type`/`--cann-bench-cases` 解析进 task_request；input_type 枚举校验。
- `tests/ut/application/`（dispatcher）：golden 三参声明式必选（hard_missing 列项）、三参配套校验、删拓扑规则后无 verify 亦可传 golden、声明式切换灵活性。
- `tests/ut/orchestration/`（verify）：`_resolve_golden_contract` 读 State 三标量、无 profile 分支。
- `tests/ut/domain/`（cases_loader）：`load_cases(cases_path)` 签名、exp cases.csv → TestCase。
- `tests/ut/orchestration/`（test_design）：`_has_external_cases` 判 cases_path、`_load_external_cases` 用 cases_path。
- `tests/ut/domain/`（repository/profile）：profile schema 删 source 段后加载行为。
- `tests/st/`（@npu/@slow/@llm）：self_evolve_op CLI 显式 golden 三参 + cases 的 exp 端到端；删旧 profile source ST。

---

## 待定（现场解决，不臆造）

- **D-1（design stage 是否现在就 require golden）—— ✅ 已定：(a) design 也 require golden（含 SE）**。现场确认结论：`GeneralDesignStage` 现状 `requires=["requirement"]`（不读 golden，P12）；`generate_ascendc_se` = `entry→context→requirement→general-design→finalize`，含 general-design、无 verify/detailed-design；既有测试有两条守护"SE 拒 golden"的拓扑断言（B3 删拓扑规则时一并改）。
  - **决策**：把 `golden_path` 写进 **`GeneralDesignStage`（general-design-generator）的 `requires`** + verify 的 `requires`。由此凡含 general-design 或 verify 的 workflow 都必选 golden——`generate_ascendc` / `_dev` / `self_evolve_op` / **`generate_ascendc_se`** 全覆盖。
  - **接受的代价**：design agent 当前不读 golden，`golden_path` 作"设计依据"前置存在，待 SE design 仿真接入后自然生效；`generate_ascendc_se` 现有测试（`test_dispatch_new_mode_missing_requirement` / `test_neither_input_passes_on_se` 等）需补 golden 三参输入，"SE 拒 golden"的两条拓扑测试（`test_golden_on_se_workflow_blocks` / `test_golden_rejected_for_design_only_se`）改为"SE 现在也 require golden"。SE 用于"从需求文档从 0 设计新算子（无参考实现）"的用法会被阻塞——这是用户明确接受的方向（golden 是设计正确性锚点，本就该前置）。
- **D-2（批量工具的算子→层级映射）**：`resolve_task_level` 删除后，未来批量工具如何按算子定位 task 层级——由批量工具自带（E7），不在本批范围。本批只保证单算子 run 通路干净。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-03 | 初版：承接 13（E1–E7）。B1–B9 九步：State 三标量、CLI 三参、dispatcher 声明式必选 + 删 golden→verify 拓扑规则、verify 读 State、cases_loader 简化签名、test_design 用 cases_path、删 profile source 层、删 GoldenSource/CasesSource/resolve_task_level、cann-bench.yaml + e2e + 测试收口。B7↔B9 schema/yaml 同步耦合标注；B8 在 consumer 迁移后。D-1 design-requires 现场定。 |
| 2026-07-03 | **D-1 定案 (a)**：design 也 require golden（含 SE）。`golden_path` 写进 `GeneralDesignStage`（general-design-generator）+ verify 的 `requires`；含 general-design 或 verify 的 workflow 全部必选 golden；`generate_ascendc_se` 亦覆盖，其现有测试需补 golden 三参、"SE 拒 golden"拓扑测试改为"SE 也 require golden"。B3 据此实施。 |
| 2026-07-03 | **B1–B9 全部实施完成**。B1（State 三标量）B2（CLI 三参）B3（dispatcher 声明式必选+design/verify require）B4（verify 读 State）B5（cases_loader 简化）B6（test_design 用 cases_path）B9a（cann-bench.yaml 删 source 块）B7（删 profile source 层+schema）B8（删 GoldenSource/CasesSource/resolve_task_level）B9b（e2e script 三参显式+workflow 注释+测试收口）。结果：UT 1482 ✅ + ST 124 ✅（含 @npu 10 + @llm 13 + @slow），consumer 层零改动。 |
| 2026-07-03 | **B9b 测试收口**：ST test_integration.py 8个 generate_ascendc 管道测试补 golden 三参（D-1：design now requires golden），新增 helper `_golden_required`；validate golden 三参 CLI 解析+e2e script bash 语法检查。 |
| 2026-07-03 | **input_type 保留**（D-2 现状）：`--golden-input-type` 由 CLI 显式传入，控制 runner harness 的 numpy→torch 适配；未采纳自动检测（静态分析脆弱、运行时探针有副作用+env 依赖），消费者层保持不动。 |
