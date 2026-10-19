# L4 实施方案 — 外部 golden/cases 适配 + cann-bench ① 对齐 ②

> **性质**：L4 实施方案。改哪个函数、什么顺序、怎么验证。动手前写。
> **上游**：`11-external-golden-cases-adapter.md`（L3，D1–D7 已定案）；覆盖 `06-problems.md` **P8 / P9 / P10**。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点、不写 file:line）。TDD：先改/加测试再改实现（CLAUDE.md 3.1）。
> **前置**：P8（A1/A2）是其余各步的共同前提，最先落地。

---

## 0. 改动总览（按依赖顺序）

| 步 | 改动 | 归属 | 依赖 |
|---|---|---|---|
| **A1** | `TestCase` 加 `attrs: dict` 字段；领域 plumbing（序列化/equality） | P8 | — |
| **A2** | harness 生成：把 case 的 attrs 当 kwargs 传给 `kernel_fn` 与 `golden_fn` | P8 | A1 |
| **A3** | profile schema 增 `golden_source`/`cases_source` 顶层声明 + 加载期校验 | D2/D5 | — |
| **A4** | golden-adapter：harness 生成按 golden 契约 emit 加载+入口归一+类型转换；单一 `reference`；收口 `run`/`compute` | D1/D2/D3 | A2 |
| **A5** | cases-loader：`cann_bench_csv` parser → `TestCase`（含 attrs）；test_design 有 `cases_source` 时走 loader | D4/D5 | A1,A3 |
| **A6** | cann-bench profile 声明 `golden_source` + `cases_source` | D6 | A3 |
| **A7** | self_evolve_op 接线：test_design 消费 `cases_source`、verify 消费 `golden_source` | D6 | A4,A5,A6 |
| **A8** | 测试：UT（attrs/harness kwargs/golden 契约/csv parser）+ ST（exp 真机：对齐后 ① 跑 cann-bench 用例+golden） | 全 | A1–A7 |

顺序建议 **A1→A2→A3→(A4‖A5)→A6→A7→A8**。A3 无依赖可与 A1/A2 并行起步。

---

## 步 A1：`TestCase` 加 attrs（P8）

**文件**：`domain/requirement.py`（`TestCase`）。

**改动**：
1. `TestCase` 增 `attrs: dict = field(default_factory=dict)`——承载算子属性值（如 `{"base": -1.0, "scale": 1.5, "shift": 0.0}`）。frozen dataclass，默认空 dict（无 attrs 算子零回归）。
2. 序列化（harness 用到的 `inputs` 序列化旁）同步带 attrs；任何按 `TestCase` 字段做 equality/hash 的地方随字段增加自然覆盖。

**验证**：
- UT：`TestCase(attrs={...})` 构造/读取；空 attrs 默认值不破坏既有用例。

## 步 A2：harness 传 attrs（P8）

**文件**：`adapters/npu/runner.py`（`_build_test_harness`）。

**改动**：
1. 每个 case 序列化时带上 `attrs`（`TestCase.attrs`）。
2. harness 脚本调用改为 `kernel_fn(*_npu_inputs, **_attrs)` 与 `golden_fn(*_np_inputs, **_attrs)`——attrs 作为 kwargs 透传。attrs 为空时退化为现状（纯位置参数），无 attrs 算子零回归。

**验证**：
- UT：生成的 harness 脚本含 `**_attrs` 透传（字符串断言）；attrs 非空时 kernel/golden 收到 kwargs。
- ST（@npu）：带 attrs 的算子（exp）真机跑非默认 attr 分支（scale=1.5 等），不再只测默认。

## 步 A3：profile schema 增 golden_source/cases_source（D2/D5）

**文件**：`resources/schemas/repository/profile.json`、`domain/repository.py`（`RepositoryProfile`/加载校验）。

**改动**：
1. schema 顶层 `properties` 增可选 `golden_source`（`{path, entry, input_type}`）与 `cases_source`（`{format, path}`）；放开 `additionalProperties`（已是 false，仅新增白名单字段）。
2. `RepositoryProfile` 增对应字段 + `from_yaml` 读取。
3. **加载期校验（1.3）**：`input_type ∈ {torch, numpy}`；`format` 属已知枚举（首版 `{cann_bench_csv}`）；path 非空。非法值加载期报错。

**验证**：
- UT：profile 含合法 `golden_source`/`cases_source` → 加载成功；非法 `input_type`/`format` → 加载报错。

## 步 A4：golden-adapter（D1/D2/D3）

**文件**：`adapters/npu/runner.py`（`_build_test_harness` 的 golden 加载段）、`orchestration/stages/verify.py`（evidence 组装）。

**改动**：
1. verify 组 evidence 时：profile 有 `golden_source` 时，把契约（`{source_path, entry, input_type}`，`{op}`/`{N}` 运行期代入）传入 harness；`state.golden_path`（用户 `--golden`）优先级更高。
2. harness 生成的 golden 加载段按契约：`importlib` 加载源 golden → 按契约 `entry` 取函数（支持 `{op}` 代入）→ 按 `input_type` 决定 numpy↔torch 转换 → 包成单一 `reference(*inputs, **attrs)`。
3. **收口（2.5）**：harness golden 入口收成单一 `reference`，删 `run`/`compute` 回退（手写 fixture 被 adapter 取代后无依赖）。

**验证**：
- UT：给定 cann-bench golden 契约（entry=`{op}`、input_type=torch），生成的 harness 脚本能定位 `exp` 函数 + 做 torch 转换（字符串断言，不依赖真机）。
- UT：用户 `--golden` 优先于 profile `golden_source`。
- ST（@npu）：cann-bench golden 经适配后，① verify 真比对其输出（max_diff 非恒 0）。

## 步 A5：cases-loader（D4/D5）

**文件**：新增 cases loader 模块（如 `domain/cases_loader.py` 或 `adapters/repository/`）；`orchestration/stages/test_design_substages.py`（`TestCaseGenStage`）。

**改动**：
1. 新增 `cann_bench_csv` parser：读 cann-bench `cases.csv`（列：operator/case_id/input_shape/dtype/attrs/value_range/note）→ `TestCase` 列表（`inputs=[{shape,dtype}]`、`attrs={...}`、`generator`/`generator_params` 由 value_range 映射）。
2. 通用 loader 入口按 `cases_source.format` 分派（首版只 `cann_bench_csv` 一支；未知 format 报错，不静默）。
3. `TestCaseGenStage`：profile 有 `cases_source` 时，走 loader 填 `state.test_cases`（确定性，**不调 LLM**）；无 `cases_source` 时维持现状（LLM 设计）。

**验证**：
- UT：`cann_bench_csv` parser 把一行 exp 用例正确转成 `TestCase`（shape/dtype/attrs 都在）。
- UT：未知 format → 报错。

## 步 A6：cann-bench profile 声明 source（D6）

**文件**：`resources/repository-profiles/cann-bench.yaml`。

**改动**：声明 `golden_source`（path=`tasks/level{N}/{op}/golden.py`、entry=`{op}`、input_type=torch）+ `cases_source`（format=`cann_bench_csv`、path=`tasks/level{N}/{op}/cases.csv`）。

**待定（运行期代入）**：`{op}` 由算子名代入；`{N}`（task 难度层级）如何确定留 A7/A8 现场定（候选：op_dir 推断、运行参数、或搜 `tasks/level*/{op}`）。不臆造，现场验。

**验证**：
- UT：cann-bench profile 加载后 `golden_source`/`cases_source` 齐全且合法。

## 步 A7：self_evolve_op 接线（D6）

**文件**：`orchestration/stages/test_design_substages.py`、`orchestration/stages/verify.py`。

**改动**：
1. test_design：有 `cases_source` 时 loader 填 `state.test_cases`（A5）；self_evolve_op 经 cann-bench profile 自动获得 cann-bench 用例。
2. verify：有 `golden_source` 时 adapter 喂 harness（A4）；`state.golden_path` 优先。
3. 更新 self_evolve_op 文档/注释：① 此时为 ② function 维度本地预检。

**验证**：
- UT：self_evolve_op（cann-bench profile）下，test_design 产出 cann-bench 用例（含 attrs），verify 用 cann-bench golden。
- ST（@npu/@slow）：exp 端到端——① verify 跑 cann-bench 用例 + cann-bench golden 通过后，② cannbench_eval 出 overall_score。

## 步 A8：测试（全量）

**UT**（A1–A7 各步自带）：attrs 模型、harness kwargs、profile schema、golden 契约、csv parser、接线。
**ST**（@npu/@slow）：exp 真机端到端——① 对齐 ② 后跑通，且 ① 用例/golden 与 ② 同源（断言 harness 调用的 attrs 覆盖 cann-bench cases 的非默认分支）。
**回归**：generate_ascendc（无 golden_source/cases_source）维持现状——test_design LLM + 用户 `--golden`，不受影响。

全量 UT + ST 必须全绿（CLAUDE.md 3.2），npu/llm/slow 不跳过。

---

## 测试影响面（TDD 先行）

- `tests/ut/domain/`：`TestCase.attrs` 构造/序列化。
- `tests/ut/adapters/`（harness 生成）：kwargs 透传、golden 契约 emit、单一 reference。
- `tests/ut/domain/` 或 `tests/ut/application/`：profile `golden_source`/`cases_source` 加载校验；`cann_bench_csv` parser。
- `tests/ut/orchestration/`：test_design 有 `cases_source` 走 loader、verify 有 `golden_source` 走 adapter；self_evolve_op 接线。
- `tests/st/test_npu.py` / `tests/st/test_self_evolution_stages.py`：exp 真机 ① 对齐 ② 端到端。

---

## 待定（现场解决，不臆造）

- ~~**`{N}`（task 难度层级）代入**~~ **已落地（A7）**：`resolve_task_level(path_template, op_name, repo_root)` 按存在性探测——遍历 `N=1..10`，取使 `{op}`/`{N}` 代入后路径在 repo_root 下存在的首个 N；找不到返回 None（该算子无 cann-bench task，如 add/sqrt，短路不触发、回退 LLM/用户 golden）。通用、不耦合 cann-bench 目录布局。test_design 与 verify 共用此解析。
- **cases-loader 的第二种 format**：D5 明确首版只 `cann_bench_csv`；第二种 format 出现再加。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-02 | 初版：承接 11（D1–D7）。A1–A8 八步：TestCase attrs、harness 传 kwargs、profile 增 golden_source/cases_source、golden-adapter（契约驱动 + 收口 run/compute）、cases-loader（cann_bench_csv 首版）、cann-bench profile 声明、self_evolve_op 接线、全量测试。P8 先修。 |
| 2026-07-02 | **A1–A8 全部落地**：UT 1465 + ST 124（含 @llm/@npu/@slow 全绿）。`{N}` 经 `resolve_task_level` 存在性探测落地。NPU 真机 ST 守护 golden 契约 torch 路径；真实 exp cases.csv 解析 ST 守护 loader。 |
| 2026-07-03 | **source 层修订**：A3（profile schema 增 `golden_source`/`cases_source` 段）/ A6（cann-bench profile 声明 source）/ A7（按 profile 消费 + `resolve_task_level` 探测 `{N}`）的 **source 层**由 `13/14` 重构为 CLI 显式（`--golden`/`--golden-entry`/`--golden-input-type`/`--cann-bench-cases`）。**保留**：A1/A2（`TestCase.attrs` + harness 传 kwargs）、A4 的 consumer 部分（harness golden 加载段 emit）、A5 的 `parse_cann_bench_csv`。`resolve_task_level` 在单算子 run 通路删除（批量工具未来自带算子→层级映射）。详见 `13`（L3）/`14`（L4）。 |
