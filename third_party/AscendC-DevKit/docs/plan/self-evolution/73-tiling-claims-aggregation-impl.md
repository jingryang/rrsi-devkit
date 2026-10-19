# 73 — tiling 段聚合接力 verifiable_claims 收口（L4 实施方案，方案 S 结构性）

> 对应 L3：`73-tiling-claims-aggregation-analysis.md`（**已拍板方案 S**，冻结；含 T1 修正：`self_check_summary` 留顶层）。
> 对应 L1：[[P100]]。
> 状态：**已实施 + heavy_llm ST 通过（2026-07-24）**——方案 S + T1 全部落盘，全量 UT 2906 passed / 7 skipped / 0 failed（零回归）；heavy_llm ST `tests/st/test_design_claims_anchor_selfclosure.py` 3 项全过（604s，真实 LLM agent）：①producer 真产 `buffer_kernel.verifiable_claims`（段内，闭合 schema 未误拒）；②anchor 真读段内 claims 对质（矛盾→AC2 / 一致→pass）；③AC0 不再误判。P100 端到端验证完成。
> 硬约束：运行中任务（run `20260724-045259-898837` 等）**已结束**后方实施——本次实施在其结束后进行。
>
> 方案命名见 L3：方案 S（Structural，选定）/ N（Nest-only）/ R（Relay）/ G（Gate-rewrite）。
> 字段分类判据：**门是否消费该字段做对质/校验**。是 → 进 segment；否（过程元数据/纯簿记）→ 留顶层白名单。

## 0. 核心改动一句话

两部分：(a) 三段 tiling schema 把 **gate-relevant 设计内容**（`verifiable_claims`/`key_parameters`/`kernel_structure`）移进 segment 对象；`self_check_summary` **留顶层**（唯一消费者 feedback-selfcheck 从**源文件**读、不经聚合；非 load-bearing，详 L3 §8）。(b) 给 `ArtifactSpec` 加 `allowed_top_level_keys` + `validate_payload` 拒未知键，三段 schema 设允许集。聚合 `:2050` **零逻辑改**。

## 1. 改动清单（顺序 = 框架机制 → 契约 → 引导 → 注释 → 测试）

### 1.1 ArtifactSpec 加 schema 闭合能力（框架，1 类）

`src/ascendc_devkit/domain/artifact.py`：
- `ArtifactSpec` 加字段 `allowed_top_level_keys: tuple[str, ...] = ()`（默认空=不闭合，兼容所有现有 schema）。
- `validate_payload`（:64-94）加分支：若 `allowed_top_level_keys` 非空，则 `data` 的顶层键必须 ⊆ `allowed_top_level_keys`，多余键报 `{filename}: unexpected top-level key(s) [...]`（扩展既有早拒机制，§1.3 精神；在段 transition 读产物时即拒 → schema_violation 重 spawn）。
- `to_prompt_block`（:96）：若闭合，把 allowed 集渲染进 prompt，让 producer 知道顶层只能写哪些。

**实施发现（enforcement hook 必要前提）**：方案 S 路径 (b)「在段 transition 读产物时即拒」依赖 transition **真的检查** parse 返回的 `errors`。审计发现 `_TilingSegmentStage.transition`（design_substages.py:2033）**只**在 `spec_name not in parsed`（文件缺失/JSON 坏）时用 `errors`，**schema_violation（required_keys 缺/未知顶层键）被静默丢弃**——它是 6 个 design substage transition 里**唯一**缺 `if errors: reject` 的（其余 5 个如 ValidateStage:1842 都有，P47 Step 2）。故实施在 :2033 后补 `if errors: return self._error(state, "; ".join(errors), error_type="schema_violation")`（范式照搬 ValidateStage）。这不是偏离 L4（L4 §1.1 原文即预期"在 transition 读产物时即拒"），而是该预期的落地——并顺带修正了段 stage 相对 sibling 的潜在不一致（§1.2 可维护）。**此改动必须与 schema 重构同步**：现状 schema required_keys 含顶层 `verifiable_claims`，而既有 UT payload 不带它，现在能过仅因 transition 忽略 errors；一旦加 `if errors:`，必须同时把 verifiable_claims 移出 required_keys（进 segment），否则既有 UT 集体回归。L4 §1.4「聚合层零逻辑改」指 :2048-2054 聚合行，与 :2033 parse/errors 处理不冲突。

### 1.2 三段 schemas：内容重构 + 设闭合（3 文件）

每段（`tiling_split.json` / `tiling_buffer_kernel.json` / `tiling_precision_perf.json`）：
1. **顶层 `required_keys`**：去 `verifiable_claims` → `{template, <segment>}`。
2. **`allowed_top_level_keys`**：设为 `{template, <segment>, step, status, decisions, external_verification, self_check_summary}`（纯簿记 + 过程元数据；`self_check_summary` 是 producer 自检结果，按对质原则门不读，留顶层）。
3. **`<segment>` 段对象**：把 `verifiable_claims`、`key_parameters`（+ buffer_kernel 的 `kernel_structure`）纳为其内层字段（进 segment 的 required/allowed）。**`self_check_summary` 不进 segment**。
4. **`example`**：`{"template":"T1", "self_check_summary":{...}, "<segment>":{...原段字段..., "verifiable_claims":[], "key_parameters":{}}}`（self_check_summary 留顶层；claims/key_params 进段）。
5. **`description`**：「verifiable_claims（顶层必填）」→「`<segment>.verifiable_claims`（段内必填）」；保留 claim_type/verification/source_pointer 字段说明（指 checkpoint_convention.md）。

> exact 字段清单（尤其 buffer_kernel 的 kernel_structure 形态）落地时核对真实 artifacts；原则固定：**gate-relevant 设计内容进 segment，过程元数据/纯簿记留顶层**。

**实施范围强化（§1.2 可扩展）**：闭合（`allowed_top_level_keys`）对**全部 4 段** segment schema 施加——含 `tiling_vf_design.json`。vf_design 的 `required_keys` 本就不含顶层 `verifiable_claims`（其 gate-relevant 内容 `vfs[].compute_ops` 本在 `vf_design` 对象内层，`:2050` 正确抓取），故 vf_design **仅需闭合、无需内容重构**。统一 4 段闭合让 UT-A 成为真正的类级守护（遍历 4 个 `_TilingSegmentStage` 子类，全部断言闭合），任一新增段 stage 自动归位。

### 1.3 skill 产出引导（3 文件）

`ascendc-op-tiling-split/SKILL.md` / `-buffer-kernel/` / `-precision-perf/`：
- 「产出 verifiable_claims / key_parameters（顶层）」→「产出 `<segment>.<字段>`（段内）」。
- `self_check_summary` 仍产在**顶层**（不变）。
- `ascendc-op-design-shared/references/checkpoint_convention.md`：verifiable_claims 字段位置说明同步改段内。

### 1.4 聚合层（零逻辑改，仅注释）

`design_substages.py:2048-2054`：**不改逻辑**。加注释：「gate-relevant 设计内容（verifiable_claims/key_parameters/kernel_structure）经 segment 内层随 `payload.get(segment_key)` 流转（[[P100]]/方案73 方案 S）；schema 已闭合（allowed_top_level_keys），顶层只许簿记/过程元数据，勿在顶层加回设计字段——会被 validate_payload 拒。decisions 经 `_capture_decision_log` 另存；self_check_summary 留顶层（对质原则门不读）。」

### 1.5 gate skill：零改

anchor-per-template / validate 已期望"三段产物的 verifiable_claims"（段内）→ 方案 S 后物化文件正合其期望，**不改**。

## 2. TDD 验证（纵深：UT-A 契约 + UT-B 代码 + schema 自检 + heavy_llm）

### 2.1 UT-A（schema 契约不变式，类守护，schema 集合驱动）

`tests/ut/orchestration/test_tiling_forkjoin.py`（或 test_design_substages.py）加：

- **A1 闭合性**：对每个 per-stage schema（**动态发现**——遍历 `_TilingSegmentStage` 子类的 `schema_file`，不硬编码三个），断言其 `allowed_top_level_keys` 非空（已闭合）。
- **A2 白名单纯洁性**：每个 schema 的 `allowed_top_level_keys` ⊆ `{<segment>} ∪ BOOKKEEPING`，BOOKKEEPING=`{template, step, status, decisions, external_verification, self_check_summary}`（纯簿记 + 过程元数据；任一项若被门开始读，需重审分类）。→ 任一 schema 把 gate-relevant 设计字段放回顶层 allowed 即 FAIL。
- **A3 拒未知键**：构造一个带非法顶层键（如 `"safety_assertions": ...`）的 per-stage 产物 → 断言 `validate_payload` 报 unexpected key。→ 守护闭合机制本身。

> A1/A2 是"类"守护：未来加新段、加新字段，只要走 schema 声明，UT 自动覆盖；不走声明（agent 私加）则被 A3 在 validate_payload 拒。

### 2.2 UT-B（聚合代码不变式）

构造一个"段内全字段填满"（含 `verifiable_claims`/`key_parameters`）的 per-stage 产物 → 跑 `_TilingSegmentStage.transition` → 断言 `state.tiling_results["T1"]["<segment>"]` 与输入段对象 deep-equal（含 claims/key_params）。→ 守护 :2050 不丢段内任何字段（防代码回归）。另断言 `self_check_summary` 等顶层簿记**不进** segment（留在顶层，不流向聚合）。

### 2.3 schema 自检 UT

既有 `test_example_satisfies_own_schema`：example 改段内 + 闭合后须仍过（example 顶层键 ⊆ allowed_top_level_keys）。

### 2.4 heavy_llm ST（§3.11，用户决策跑）

`tests/st/test_design_claims_anchor_selfclosure.py`（方案62 建）：复核 producer 产在 segment 内（claims/key_params）、self_check_summary 产在顶层、闭合 schema 不误拒、anchor 读到段内 claims、AC0 不再误判。

## 3. 顺序与门

1. `ArtifactSpec` 加 `allowed_top_level_keys` + `validate_payload` 拒未知键（框架机制，含 to_prompt_block 渲染）。
2. 三段 schema：内容重构（claims/key_params/kernel_structure 进段；self_check_summary 留顶层）+ 设 allowed_top_level_keys + example。
3. 三段 skill 引导 + convention。
4. 注释 :2050（零逻辑改）。
5. UT-A（A1/A2/A3）+ UT-B 红→绿 + schema 自检。
6. 全量 UT（非 heavy_llm）零回归。
7. heavy_llm ST 由用户决策跑（§3.11）。

## 4. 影响面与回归

- design 段聚合 / anchor / validate / codegen staging（读 tiling_results）形状一致化（都见段内 claims）。
- `ArtifactSpec` 新字段默认空 → 其它 schema 零影响（开放如故），仅三段 tiling 闭合。
- 既有 run 产物（旧顶层形态）不迁（§1.4）。
- [[P110]]：随方案 S 消解（key_parameters 进 segment 流向门；self_check_summary 留顶层白名单；闭合立规则）。
- **复发面消除**：gate-relevant 设计内容构造性流转 + 顶层闭合拒孤儿 → P100 类 bug 结构性不可能；UT-A/UT-B 纵深防回退。

## 5. 不做的事

- 不加方案 R 的 relay 变换（单一通路 §2.5）。
- 不为旧顶层形态加兼容/迁移（§1.4）。
- 不改 gate skill（已期望段内）。
- 不强制全框架 schema 闭合（`allowed_top_level_keys` opt-in，仅 tiling 三段；其余日后按需）。
- 不把 `self_check_summary` 挪进 segment（T1：过程元数据 + 对质原则门不读，留顶层白名单）。
- 不在运行中任务结束前实施。
- 「门输入契约化」（原方案 N/R 白名单盲区的 follow-up）：因方案 S 白名单全是"按定义非 gate-visible"字段、盲区实际消除，**降为低优先，可不做**。

## 6. follow-up（低优先）

- 其它 design/codegen schema 视需 opt-in `allowed_top_level_keys`（推广闭合）。
- 若未来某门要读纯簿记/过程元数据字段（如 self_check_summary，与对质原则相悖的低概率场景），再评估"门输入契约化"交叉校验。

## 7. 实施日志（2026-07-24）

**改动文件**：
- `src/ascendc_devkit/domain/artifact.py`：`ArtifactSpec` 加 `allowed_top_level_keys` 字段；`validate_payload` 加"拒未知顶层键"分支；`to_prompt_block` 渲染闭合契约。
- `src/ascendc_devkit/adapters/schema/loader.py`：`_build_spec` 读 `allowed_top_level_keys`。
- `src/ascendc_devkit/orchestration/stages/design_substages.py`：`_TilingSegmentStage.transition` 加 `if errors: return self._error(..., schema_violation)`（enforcement hook，§1.1 实施发现）；:2050 聚合行加注释（零逻辑改）。
- 4 段 schema：`tiling_split.json` / `tiling_buffer_kernel.json` / `tiling_precision_perf.json`（required_keys 去 verifiable_claims + claims/key_params/kernel_structure 进 segment + 设闭合）/ `tiling_vf_design.json`（仅设闭合）。
- 3 段 SKILL.md + `checkpoint_convention.md`：字段位置说明改段内 + 闭合约束。
- `tests/st/test_design_claims_anchor_selfclosure.py`：`TestTilingBufferKernelProducesClaims` 断言改段内（对齐新契约）。

**新增测试（TDD red→green）**：
- UT-A（`tests/ut/adapters/test_design_schemas.py::TestTilingSegmentSchemaClosure`）：A1 闭合性 / A2 白名单纯洁性 / A3 拒孤儿顶层键——4 段参数化（12 项），schema 集合驱动，类级守护。
- UT-B（`tests/ut/orchestration/test_tiling_forkjoin.py::TestSegmentClosureRoundTrip`）：B1 段内字段 round-trip deep-equal / B2 顶层簿记不进 slice / B3 孤儿顶层键 transition schema_violation 拒绝。

**验证**：UT-A/UT-B 15 项全绿；design+schema 子集 241 项全绿；全量 UT **2906 passed / 7 skipped / 0 failed**（7 skip 为 cann-bench 环境用例，记忆 `ut-preexisting-env-failures`）。heavy_llm ST（用户决策跑）**3 项全过**（604s，真实 LLM agent）：producer 真产段内 claims + anchor 真读段内对质 + AC0 不再误判。P100 端到端验证完成。
