# L4 实施方案 — 设计链需求权威单一通路（A + A2/A3/A4）

> 动手前写。按步骤执行，每步 TDD（§3.1）；UT 用真实 fixture 表达业务不变式（§3.12）。

## 改动点（文件 / 函数）

| # | 文件 | 函数 | 改动 |
|---|---|---|---|
| 1 | `orchestration/stages/design_substages.py` | `_DesignSubstage._materialize_inputs` | 对 `field == "requirement"` 改走 `materialize_authoritative_requirement(state, wd/"requirement.json")`；返回 True → 跳过通用写；False → `Logger.warn` + fail（不落 reduced） |
| 2 | `orchestration/design_artifacts.py` | `materialize_authoritative_requirement` | 删 last-resort fallback（`asdict(state.requirement)` 回退）；权威源不可达返回 False，语义改为「缺失即失败」，由调用方诚实 fail |
| 3 | `orchestration/stages/design_substages.py` | `SynthesizeStage.transition` reconcile 区 | 加 support_domain 对质：`requirement.domain.inputs[name].dtypes ⊆ design_spec.support_domain.inputs[*].dtypes`（design 必须覆盖需求域）；未覆盖/超集 → `Logger.warn` 留痕（run.log 告警 + 下游 codegen domain-gap 安全网；decision_log 归 agent 自产，框架不代写）；不机械撑大（反对 D） |
| 4 | `orchestration/stages/design_substages.py` | 设计加载期校验点 | 接线 `validate_support_domain_structure`（§1.3 结构校验，现死代码 P3） |
| 5 | `orchestration/stages/codegen.py` | `_materialize_inputs` requirement 分支 | 同步 §3.12：权威不可达时不再 `_json_text(state.requirement)` 兜底，改 fail/告警（与步 2 一致） |

## 顺序

1. 步 4（接线校验器，独立无依赖）→ 2. 步 1 + 步 2（输入路权威回读 + 删 fallback，核心）→ 3. 步 5（codegen 同步）→ 4. 步 3（synthesize 对质，依赖步 1 使 agent 看到全量 domain）。

## resume 维度

- 确认 `_working_dir` 在 resume 后指向原 run 的 artifacts 子目录（磁盘产物文件可得）；若 resume 重建新 working_dir 而产物不在，属恢复基础设施问题（本方案外），但物化代码统一后正常/resume 同路径受益。
- 验证补充：resume 重建 State 后，stage 物化仍走权威回读（从磁盘 requirement.json 全量），不从 state_snapshot 的 reduced 快照。

## 验证（§3.12 真实 fixture）

- **UT-1（不变式）**：构造 workspace + `artifacts/requirement/requirement.json`（含 `domain.inputs[0].dtypes=[fp16,fp32,bf16]`）→ 断言 GeneralDesign / Synthesize stage 物化的 requirement.json 为权威全量（含 domain 三值），**非** `{op_spec:单dtype}` wrap。
- **UT-2（§3.12）**：权威文件缺失（无 workspace / 文件不存在）→ 断言 stage fail / 告警，**不落 reduced requirement.json**。
- **UT-3（A3）**：design_spec.support_domain 超需求域（声称 int8）→ 断言 warn；子集（fp16）→ 断言留痕无 warn。
- **UT-4（步 4）**：support_domain 结构非法（dtypes 非 list / rank 非 {min,max}）→ 加载期告警（§1.3「校验并告警」，warn-only——结构违规不阻断，由 schema parse（SynthesizeStage.transition 的 artifact_contract 校验）与引擎 `_rank_gaps` 等 isinstance 守卫分层兜底；§1.14 不为此搭硬 gate）。
- **回归**：codegen 既有 UT（`test_codegen_upstream_reuse.py::test_requirement_serializes_as_json_not_repr` 等，db504b #1 曾断言 last-resort 语义）需按 §3.12 更新为"权威缺失 → fail"语义；design 链既有 UT 全量跑绿（§3.2）。

## 风险

- 步 1 影响全部设计 stage（general-design/template-division/tiling/synthesize/test_design），漏改即断链 → UT-1 前置守护。
- 步 2/5 删 fallback 影响 codegen 无 workspace 的既有 UT → 需同步更新（按 §3.12 断言 fail 而非兜底）。
- 步 3 对质是设计链内自检，不新增下游门（§2.9），不阻断（§1.14 非控模型 gate）。

## 后续（本方案外，待 L2 挂载）

- `State.Requirement` 边界声明为「仅框架机械消费（阈值/身份/名字），不作为 agent 需求源」（§2.5 收尾文档）。
- L2 总纲（docs/plan 根）挂载本工作；共享文档修改避让并发（concurrent-session 约定）。
