# L4: precision harness 接受 Optional/可空 attr + 类型名规范化 + 误判族 — 实施方案

> L1 `01-problems.md`（P1–P5）、L3 `02-analysis.md`（决策 1–8）。本文件 = 实施配方 + as-built。
> 触发：run `20260805-152456-8b48b2` 算子 `resize_bilinear` precision_debug halt（0/20 上板）。
> **阶段 A 已落地并验证（2026-08-06，见文末 As-built）；阶段 B 未做。**

## 总览与分层（决策 6）

- **阶段 A（主修复，根治 halt）**：决策 1（None 接受）+ 决策 2（类型名加载期规范化 + 补 `list[float]`）。
  落地后 harness 不再对合法 None abort → 用例真正上板 → 本次 halt 消失。
- **阶段 B（二级硬化 / 可观测性，独立于本次根因）**：决策 3（scope_guard ownership 判据）、
  决策 4（passed 计数诚实）、决策 5（failure_type 结构性分类）。对任何 halt 都该修，分别验证。

---

## 阶段 A — 主修复

### A1. `_validate_attrs` 接受「声明缺省为 None」的 attr 取 None（决策 1，P1）

- **文件**：`src/ascendc_devkit/adapters/npu/runner.py`
- **函数**：`_validate_attrs`（`:225`），循环体（`:238 for k, v in attrs.items()`）。
- **改法**：在取 `expected` 之后、进入 typed 分支之前，加一个**前置短路**：
  `if v is None and getattr(attr_spec, "default", "__none__") is None: continue`
  （attr 声明缺省即 None 时，None 是合法缺省，跳过类型校验）。其余路径不变——必填 attr
  （default 非 None）传 None 仍被对应分支/兜底拒绝。
- **不改 schema**：`AttrSpec.default` 既有（`domain/operator.py:48`），requirement 已产 `default:null`。
- **验证（UT）**：`tests/ut/adapters/npu/test_runner_contract.py`（已有 `_validate_attrs` 用例族）新增：
  - `test_attrs_none_accepted_when_default_none`：`AttrSpec(name="output_size", type="list[int]", default=None)` +
    `_validate_attrs({"output_size": None}, 0, operator=op)` 不抛。
  - `test_attrs_none_rejected_when_default_non_none`：`AttrSpec(name="k", type="int", default=0)` +
    `_validate_attrs({"k": None}, 0, operator=op)` **抛**（必填 attr 误传 None 仍拒）。
  - `test_attrs_none_rejected_when_no_default`：default 缺省（`REQUIRED` 语义）+ None → 抛。

### A2. attr 类型名加载期规范化（单一翻译点，决策 2，P2）

- **文件**：`src/ascendc_devkit/domain/operator.py`
- **位置**：`AttrSpec` 构造处（`type=e.get("type") or e.get("dtype","")`，约 `:184`）——`AttrSpec` 的
  唯一入参 chokepoint。新增模块级 `_CANON_ATTR_TYPE = { "ListInt":"list[int]", "ListFloat":"list[float]",
  "Int":"int", "Float":"float", "Bool":"bool", "Str":"str" }`（单一翻译点，类比 §1.9 `to_soc_version`）。
- **改法**：构造 `AttrSpec` 时 `type = _CANON_ATTR_TYPE.get(raw, raw)`；同时按 §1.3 加载期校验——
  `raw` 既非 canonical（`int/float/str/list[int]/list[float]/bool`）又不在别名表 → 记 WARN（未知类型名，
  将走兜底校验），不再静默落兜底。
- **不改 requirement 管线**：requirement-analyst 仍可产 `ListInt/ListFloat`，规范化在加载期吸收（单一翻译点）。
- **验证（UT）**：`tests/ut/domain/test_operator_spec.py`（或对应 OperatorSpec.from_dict 测试）新增：
  - `test_attr_type_canonicalized_listint`：from_dict 入参 `type:"ListInt"` → AttrSpec.type == `"list[int]"`。
  - `test_attr_type_canonicalized_listfloat` → `"list[float]"`。
  - `test_attr_type_unknown_warns`：`type:"WeirdType"` → 规范化不变 + 触发 WARN（用 `caplog` 断言）。

### A3. `_validate_attrs` 补 `list[float]` 分支（决策 2，P2）

- **文件**：`src/ascendc_devkit/adapters/npu/runner.py`
- **函数**：`_validate_attrs` typed 分支（`:269` `elif expected == "list[int]"` 之后）。
- **改法**：新增 `elif expected == "list[float]":` 分支——`isinstance(v,(list,tuple)) and all(isinstance(x,(int,float)) and not isinstance(x,bool) for x in v)`，否则抛 `expected list[float], got {v!r}`。
- **验证（UT）**：`test_runner_contract.py` 新增 `test_attrs_list_float_matches_spec_passes`（`[2.0,2.0]` 过）、
  `test_attrs_list_float_rejects_str_element`（`["a","b"]` 抛）。
- **单一真值源提示（不在本步做，仅记）**：理想上 validator 的可接受类型集应与 `_CANON_ATTR_TYPE` 的
  canonical 值集同源（目前 validator 在 runner.py 硬编码分支，是第二份真值，§2.5 隐患）。本步先补齐
  `list[float]` 消除功能缺口；类型集单一化留作后续小重构，不在本轮扩大范围。

### A4. 回归验证（端到端）

- 用 resize_bilinear 的失败 case 复跑：`output_size=null + scale_factor=[2.0,2.0]` 的 staging
  test_cases.json 经 `_validate_attrs` 不再 abort → harness 进入真实执行 → 产出 per-case result.json
 （`last_result_json` 非 null）。
- 断言：`run_tests_iter-0/` 非空、`precision_run_tests.json.last_result_json != null`、不再有
  `[PD-CONTRACT] … unsupported type NoneType`。
- 注：A4 只验证「假性 abort 消除、用例真正上板」；kernel 的 scale_factor 分支若仍有精度/runtime 缺陷，
  由真实 case 结果暴露（不在本修复承诺范围，符合「修假性 abort，不包精度」）。

---

## 阶段 B — 二级硬化 / 可观测性

### B1. scope_guard 归属判据改 ownership（决策 3，P3）

- **位置**：scope_guard 的归属判定由 `ascendc-precision-scope-guard` **agent**（写 `scope_verdict.json`）
  产出，框架侧 `precision_debug_substages.py:1218-1228` 仅据 `dc.upstream_stage` 拼 halt 文案。
  故判据修正落在 **scope_guard skill/agent 的判定指引**（`.claude/skills/ascendc-custom-op-precision/`
  scope_guard 段 + agent 定义），非纯 Python。
- **改法（skill 核心引导，§2.7）**：把归属判据从「错误形态（schema/compilation）」改为「抛错代码
  ownership」——harness/框架自有代码（`adapters/npu/runner.py` 等本仓 src）抛的契约错 = in-scope
  （precision_debug 同侧或框架侧，**不**甩 test_design）；只有 `cases.yaml` / kernel 源码 / golden.py
  等上游产物错误才算 upstream。给抽象范式（「抛错点的文件归属」），不点具体算子名（§1.12）。
- **验证**：`tests/ut/orchestration/test_precision_debug_stage.py` 新增——构造「harness 自家 `_validate_attrs`
  抛 PD-CONTRACT」的 control.json 输入，断言 scope_guard 判定不走 `upstream_stage=test_design`
  （ownership 在框架侧）。skill 侧指引变更附 skill 自检清单项。

### B2. passed 计数诚实（决策 4，P4）

- **文件**：`src/ascendc_devkit/orchestration/stages/precision_debug_substages.py`
- **位置**：`passed_count = total_count - failed_count`（`:847` 注释自承）+ 渲染（`:552-586`）+ 更新（`:843-869`）。
- **改法**：当 `last_result_json is None`（0 条上板）/ hard_error 发生在 schema-abort 期，`passed_count` 记 `0`
  （不按 `total − failed` 算）；report 渲染（`:586`/`:667`）在该状态下不渲染「最优 commit / 收敛趋势」假信号，
  改渲染「0/N 上板（harness abort 于执行前）」。
- **验证（UT）**：`test_precision_debug_stage.py` 新增 `test_passed_count_zero_when_harness_aborted_pre_execution`
  （`last_result_json=None` → best_passed_count=0，report 不含「N/M passed」收敛行）。

### B3. failure_type 结构性分类（决策 5，P5）

- **位置**：`failure_type` 的赋值发生在 run_tests 结果解析（把 harness 报错映射到
  compilation/runtime/precision）。关键词匹配（`Error:` 前缀 → compilation）需在解析处定位
  （`precision_debug_substages.py` 内 run_tests summary 构建路径，结合 `:2122/:2260/:2262` 消费点回溯）。
- **改法**：分类判据从「错误文本关键词」改为「结构性信号」——按抛错点/阶段判：C++ 编译器阶段失败 =
  compilation；Python schema/契约校验抛错（`HarnessContractError`/PD-CONTRACT 且非编译器输出）=
  `schema_contract`；kernel runtime 错误码 = runtime。
- **验证（UT）**：`test_precision_debug_stage.py` 新增 `test_failure_type_schema_not_compilation`
  （PD-CONTRACT 抛错 → failure_type≠`compilation`，为 `schema_contract`）。
- **诚实标注**：B3 的精确改动行需在实施时于 run_tests 解析路径定位确认（本配方标到消费点，赋值点待定）。

---

## 实施顺序与依赖

1. **A2 → A3 → A1**（先建类型规范化与 `list[float]` 分支，再开 None 接受短路；A1 依赖 canonical type 到位，
   否则 `output_size` 仍可能因类型名落兜底）。三者合为阶段 A 一个 commit。
2. **A4** 阶段 A 自验（resize_bilinear 复跑）。
3. **B1 / B2 / B3** 互不依赖，可并行/分 commit；各带独立 UT。
4. 全量回归：UT 全量 + 非 heavy_llm 的 ST（§3.2/§3.6），重点 `test_runner_contract.py` /
   `test_precision_debug_stage.py` / `test_operator_spec.py`。

## 不做（明确排除）

- 不改 cases.yaml / loader 去物化 output_size（决策 7，反向修正正确上游，违 §1.13）。
- 不新增 `AttrSpec.nullable` 字段（决策 1 选 B，复用既有 `default`；YAGNI）。
- 不做「validator 可接受类型集与 `_CANON_ATTR_TYPE` 单一真值源化」重构（A3 注，留后续）。
- 不动 codegen manifest 参数名顺序漂移（`run.log:3611`，独立已知项 P10，cannbench_adapt 已兜底）。

---

## As-built（阶段 A v2，2026-08-06）

> **v1→v2 演进**：v1（已 commit `f48eead8`）用「静态别名表 `_ATTR_TYPE_ALIASES` + validator
> if/elif 分支 + `list[float]` 补分支」。经用户连环追问（cann-bench 是否权威源 / `ListInt` 能否归一 /
> 是否耦合 cann-bench / 完全符合原则）发现 v1 是「半截表 + 三处词汇表重复」，升级为 v2 闭合契约体系。
> v2 改动在工作区（未 commit），覆盖 v1 的 operator.py / runner.py，新增 deploy 契约校验 + requirement
> skill/schema 生产者契约。

**v2 已落地**（工作区，未 commit）：

- **domain `operator.py`**（单一来源 + 翻译点 + 忠实承载 + 可观测）：`CANON_ATTR_CHECKERS` dispatch
  table（canonical type→值校验器，**单一权威源**，validator 与 deploy 共用，§2.5 消除三份词汇表重复）
  + `_canonical_attr_type()` source-agnostic 翻译点（目标取自 dispatch table；generic 规则 case/bracket/
  `_t`/族匹配；**零 cann-bench 标识**；§1.9 类比 `to_soc_version` / §2.9 构造性保证）+ `AttrSpec.__post_init__`
  翻译 + 未知类型**加载期 WARN**（§1.3）。
- **runner `_validate_attrs`**：**删 if/elif 链** → `CANON_ATTR_CHECKERS.get(expected)` dispatch；保留
  None 短路（`default is None`，§1.13）+ 数值串强制 + 兜底。
- **deploy `_SMOKE_ATTR_DEFAULTS`**：键 load 期 `assert ⊆ CANON_ATTR_CHECKERS`（drift→import 即崩，§1.3）。
- **requirement skill/schema**（生产者侧闭合）：schema attr 示例 `int64→int` + 描述声明 canonical 词汇表
  契约；SKILL.md 自检清单加「attrs[*].type 取 canonical 集，从 golden 注解派生，禁别名」。

**覆盖**：cann-bench 142 proto.yaml 实测 17 种 attr type 拼写全部归一或正确 passthrough（Tensor 等非标量
+ 加载期 WARN）。

**验证**：
- `tests/ut/adapters/npu/test_runner_contract.py`：dispatch table / 翻译全拼写（parametrize）/ 未知类型
  WARN（caplog）/ None 短路 / dispatch 通过拒绝 —— **73/73**。
- 全量 `--quick` UT **3487 passed/0 failed/7 skipped/1 deselected**（343s）零回归；修 1 stale 断言
  `tests/ut/domain/test_domain.py:310`（`int64`→`int`，反映 canonical 化是新设计意图）。
- v1 附带修的 4 个 `test_build_failed_case_queue` stale test（tuple unpack）在 commit `f9775a4c`。

**未验证（诚实标注）**：
- heavy_llm / 真实 NPU 端到端（resize_bilinear 复跑确认 0/20→上板）**未跑**——本次会话环境无
  NPU/CANN（`--quick` 模式），仅 UT 守护根因。§3.11：特性交付前应由用户在真实环境跑一次。
- A4 端到端复跑（`run_tests_iter-0/` 非空、`last_result_json != null`）待真实环境确认。

**阶段 B（未做，待用户定）**：B1 scope_guard ownership 判据（skill/agent 内容）、B2 passed 计数诚实
（`precision_debug_substages.py:847` 等）、B3 failure_type 结构性分类。三者独立于本次根因，属二级
硬化/可观测性；主修复（阶段 A）已消除 halt，B 不阻塞。

## L2 挂载（housekeeping，已完成）

本工作子目录已挂载到 L2 总纲 `docs/plan/skills-integration-and-tdd-plan.md` 步骤索引表 step 83
（覆盖问题 P1–P5，状态✅ 阶段 A 已实施+验证）。
