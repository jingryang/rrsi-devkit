# foreach/TensorList precision_debug 入口修复 — 实施方案（L4）

> 动手前写。目标：P1/P2/P3/W3/W4 一并修复，按「尽早前置解决」排序实施。
> 依据：同目录 `01-problems.md`（L1 事实）+ `02-analysis.md`（L3 取舍）。
> 原则：§1.2（主修复 + 兜底 + 可观测）、§1.12（结构信号，不认算子）、§1.13（契约权威）、
> §2.5（唯一通路）、§2.9（构造性保证）。

## 实施顺序（前置优先：先修源头，后修下游兜底/观测）

| # | 改动 | 文件 | 目的 |
|---|------|------|------|
| 1 | **W4** manifest 先 relay 进 state 再 deploy | `stages/codegen.py` | 源头：smoke 拿到 callable_target，消灭假阴性 |
| 2 | **P2** `is_list→DYNAMIC` 确定性派生 | `domain/operator.py` | 源头：op_spec 契约正确，runner DYNAMIC 闸门自然触发 |
| 3 | **P2 观测** PD-CONTRACT 报错补根因 hint | `adapters/npu/runner.py` | 下游兜底：A2 覆盖不到的场景一眼可诊断 |
| 4 | **W3** m.def 自检正则支持 `Tensor[]` | `stages/codegen.py` | 观测：消灭 TensorList 假阳性 + 漏检 |
| 5 | **P1** `real_errs` 滤 None | `stages/precision_debug_substages.py` | 兜底：harness 中止场景 transition 不崩 |
| 6 | **P3** `__halt__` 优先语义化 halt 原因 + dispatcher 分支 | `graph_executor.py` + `application/dispatcher.py` | 观测：halt 消息反映真实原因 |

**A1（req-analysis 端派生 DYNAMIC）实现方式演进**：原始设计是 LLM 引导（req-analysis skill 写
对 `is_list=true → param_type=DYNAMIC`），属 `.claude/` 共享文件、并发期不动
（`concurrent-session-defer-shared-edits`）。后续实现改为**确定性工程实现**（§2b：requirement
阶段从 proto 结构信号派生，不依赖 LLM、不碰 skill 文件），A2 退为确定性兜底（双保险）。

---

## 1. W4 — codegen transition 先 relay manifest 再 deploy（`stages/codegen.py:1791`）

**根因**：`state.codegen_manifest` 在 `Deployer().deploy(state)`（L1792）执行**之后**才于
L1865 的 `with_updates` 写入 → deploy 读 `_callable_target(state)`（`deploy.py:354`）得到
None → smoke 假阴性。

**改**：在 deploy 前把当前 manifest relay 进 state（L1782 `_persist_sources` 之后、
L1791 import 之前插入）：
```python
self._persist_sources(state, agent_result.artifacts)
# W4: 先 relay 本轮 manifest（含 callable_target）进 state 再 deploy — 否则
# Deployer.deploy(state) 的 _callable_target 读到的是旧/空 state.codegen_manifest，
# smoke 因 callable_target 缺失而假失败（foreach_norm 20260807-144939-310314）。
if manifest is not None:
    state = state.with_updates(codegen_manifest=manifest)
```
后续所有 `state.with_updates(codegen_manifest=manifest, ...)` 幂等，无需改动。

**验证**：UT 断言「state 携 manifest（callable_target 完整）时 `Deployer._callable_target`
非 None」；或单测 transition 路径 `state.codegen_manifest` 在 deploy 调用点已设置。

## 2. P2 — `TensorSpec.from_dict` 派生 `is_list→DYNAMIC`（`domain/operator.py:191`）

**根因**：requirement.json 对 TensorList 输入声明 `param_type=REQUIRED` + `is_list=true`
（语义矛盾）；`TensorSpec` 无 `is_list` 字段，`filter_known_fields` 丢弃该信号，仅保留
REQUIRED → runner DYNAMIC 闸门永不触发。

**改**（`TensorSpec.from_dict`，单点派生，§2.5）：
```python
@classmethod
def from_dict(cls, d: dict) -> "TensorSpec":
    kwargs = filter_known_fields(cls, d)
    # P2: TensorList（is_list=true）在 CANN 必须是 DYNAMIC（变长），REQUIRED/OPTIONAL
    # 是语义矛盾（requirement 曾把 Tensor[] 输入标 REQUIRED → runner 的 DYNAMIC 放行
    # 分支永不触发 → list-of-lists 用例全被 PD-CONTRACT 拒 → upstream halt）。用结构
    # 信号 is_list 确定性派生（§1.12），不认算子名；改写 WARN 暴露（§1.3 不留静默）。
    if d.get("is_list") and kwargs.get("param_type", "REQUIRED") != "DYNAMIC":
        old = kwargs.get("param_type", "REQUIRED")
        kwargs["param_type"] = "DYNAMIC"
        logger.warning(
            "TensorSpec %r: is_list=true 但 param_type=%r — TensorList 在 CANN 必须 "
            "DYNAMIC，派生为 DYNAMIC。", d.get("name", "?"), old)
    return cls(**kwargs)
```
**不触碰**：runner 的 DYNAMIC 闸门逻辑（`runner.py:197-212` 本身正确）；REQUIRED 输入仍拒
list-of-lists（`TensorSpec(..., param_type="REQUIRED")` 直构不受影响，测试
`test_required_input_rejects_nested_shape` 语义保留）。

**影响面核查**：`param_type` 消费点 — runner 闸门（input only）、cannbench_adapt、
`is_scalar_entry`（`param_type` presence 已判 tensor，派生后仍 tensor）。outputs 同样派生
（Tensor[] 输出 DYNAMIC 语义正确）。codegen 读 requirement.json 原文（未改文件），行为不变。

## 2b. A1 确定性落地 — requirement 阶段 proto 结构信号派生（`stages/requirement.py` + `domain/requirement.py`）

**背景**：A2（§2）只在 requirement entry **已有 `is_list` 字段**时派生；而真实运行中
requirement-analyst 产出的 requirement.json **从不输出 `is_list`**（schema 未定义该字段，
LLM 无从写），A2 的触发条件永不满足 → foreach 类算子仍循环 PD-CONTRACT 失败
（run.log 7527/8776/10961/11941 四处同一报错）。修复必须补源头：requirement 阶段用
**proto.yaml 的结构信号**（§1.12 不认算子名、§1.13 proto 是接口契约权威）确定性判定
TensorList，不依赖 LLM 手写。

**改**（两层，均在 requirement transition 内、`OperatorSpec.from_dict` 之前）：
1. `domain/requirement.py` 新增 `read_proto_tensorlist_inputs(proto_path)`：从 proto 提取
   TensorList 输入名，认**两个结构信号**并集——
   - `operator.inputs[].is_list: true`（显式字段）；
   - `operator.schema` 签名参数 `Tensor[] <name>`（如 `foreach_norm(Tensor[] x, ...)`，
     内联正则取首个 `(`..`)` 间参数体；不依赖 `parse_mdef_param_types`——该函数在
     v0.2.0 分支不存在，内联保证跨分支一致）。
   缺失/不可读/未声明 → `[]`（Graceful，§1.3 不阻断）。
2. `stages/requirement.py` 新增两个方法并在 transition 接线：
   - `_derive_tensorlist_param_type(req_data, proto_path)`：命中 proto TensorList 的
     input 补 `is_list=true` 并派生 `param_type=DYNAMIC`（agent 误标 REQUIRED/OPTIONAL 时
     WARN 留痕，§1.3）。幂等；proto 缺失 → 不改写（fallback 给 A2 + runner hint）。
   - `_validate_tensorlist_param_type(req_data)`：加载期交叉校验（§1.3）——`is_list=true`
     但 `param_type≠DYNAMIC` → `schema_violation` 重试。兜「agent 手写 is_list=true 却标错
     param_type 且 proto 未声明」的反向误伤。

**接线位置**：transition 中 `req_data["name"]` 归一化后、`OperatorSpec.from_dict` 之前
（先派生 → 后校验，派生已把 proto 命中的修正为 DYNAMIC，校验兜残余）。

**与 A2（§2）关系**：A1 确定性实现补「源头产对」；A2 在 `from_dict` 仍是确定性兜底
（双保险）。runner 的 DYNAMIC 闸门逻辑不变。

**不触碰**：`.claude/` skill 文件（避免并发期共享文件冲突）；codegen 读 requirement.json
原文的行为不变（派生只改内存 req_data，不改落盘文件）。

## 3. P2 观测 — PD-CONTRACT 报错补 hint（`adapters/npu/runner.py:213`）

**改**（`elif` 分支，shape 非 list[int] 时报错追加 hint）：
```python
elif not isinstance(shape, (list, tuple)) or not all(
    isinstance(d, int) for d in shape
):
    _hint = ""
    if (isinstance(shape, (list, tuple)) and len(shape) > 0
            and isinstance(shape[0], (list, tuple))):
        _hint = (" — 用例给的是多张量 list-of-lists 但 op_spec 对该输入声明 param_type "
                 "非 DYNAMIC；TensorList 输入应派生 DYNAMIC，疑似 requirement 误标 "
                 "(docs/plan/precision-tensorlist-harness-contract)")
    raise HarnessContractError(
        f"test_cases[{idx}].inputs[{j}].shape must be list[int] "
        f"(got {shape!r}){_hint}"
    )
```
**不改**放行语义（§1.13 契约不一致仍大声失败）。

## 4. W3 — m.def 自检正则支持 `Tensor[]`（`stages/codegen.py:1467`）

**改**：
```python
tensor_params = re.findall(r'Tensor\??(\[\])?\s*(\w+)', schema_params)
tensor_params = [n for _, n in tensor_params]
```
覆盖 `Tensor x` / `Tensor? mask` / `Tensor[] x` / `Tensor?[] x`。foreach_norm 的
`Tensor[] x, float scalar` → `['x']` == manifest `['x']` → 不再误报；真实 phantom bug 仍被抓。

## 5. P1 — `real_errs` 滤 None（`stages/precision_debug_substages.py:1908`）

**改**：
```python
real_errs = [c["max_err"] for c in queue_for_best
             if c.get("max_err") is not None
             and c.get("max_err") != 999.0 and c.get("elapsed_ms", 0) >= 0]
```
`max(real_errs)` 不再收到 None（harness 中止/未执行用例 → 全 `max_err=null` 的场景自愈为
`best_real_max_err=None`，如实传递 0/20，交给 scope_guard 判定）。

## 6. P3 — `__halt__` 优先语义化 halt 原因 + dispatcher `upstream_defect` 分支

### 6a. `orchestration/graph_executor.py:531` `__halt__` 分支

**改**：优先用 `debug_result.halt_reason`（scope_guard 判 upstream 时 `_sync_debug_result`
已写入 `precision_debug_substages.py:1242`，非空 ⟺ upstream）；`last_error` 降为 fallback；
上游 halt 置 `kind="upstream_defect"`：
```python
dr = getattr(state, "debug_result", None)
semantic = (dr.halt_reason
            if dr is not None and getattr(dr, "halt_reason", "")
            else "")
last_err = getattr(state, "last_error", None)
last_err_msg = (last_err.message
                if last_err is not None and getattr(last_err, "message", "")
                else "")
halt_msg = semantic or last_err_msg or (
    f"corrective/escalation quota exhausted at condition '{condition}'")
kind = "upstream_defect" if semantic else "corrective_exhausted"
state = state.with_updates(
    is_terminal=True,
    halt_reason={"kind": kind, "stage": child.name, "message": halt_msg})
```
非 precision halt（`debug_result` 为 None）→ semantic="" → 行为与现状一致（kind 不变）。

### 6b. `application/dispatcher.py:1137` 加 `upstream_defect` 分支

**改**：在 `corrective_exhausted` 分支后加：
```python
elif halt_reason and halt_reason.get("kind") == "upstream_defect":
    msg = halt_reason.get("message", "")
    Logger.error(
        f"Workflow halted: stage '{halt_reason.get('stage', '?')}' refused to "
        f"proceed on an upstream defect{(': ' + msg) if msg else '.'} "
        "The failure is owned by an upstream stage (test_design/requirement/"
        "golden/deploy), not the coder — fix the upstream product, then re-run.")
```
同时覆盖 `__escalate__:upstream`（`graph_executor.py:485` 已置 `upstream_defect`）与 6a 两条路径。

---

## 验证

### 新增 UT
1. `tests/ut/domain/test_operator.py`：
   - `test_tensor_spec_from_dict_is_list_derives_dynamic`：`TensorSpec.from_dict({is_list:True, param_type:"REQUIRED"}).param_type == "DYNAMIC"`。
   - `test_tensor_spec_from_dict_is_list_dynamic_no_warn`：已 DYNAMIC 不派生、不 WARN。
   - `test_operator_spec_from_dict_is_list_input_dynamic`：`OperatorSpec.from_dict` 全链派生。
2. `tests/ut/adapters/npu/test_runner_contract.py`：
   - `test_is_list_derived_op_spec_accepts_nested_shape`：from_dict 派生 DYNAMIC 的 op_spec → 验证器放行 list-of-lists。
   - `test_required_reject_nested_shape_hints_param_type`：REQUIRED 直构 + nested shape → 报错含 hint 文案。
3. `tests/ut/orchestration/test_graph_executor.py`：
   - `test_halt_reason_upstream_defect_prefers_debug_result_halt_reason`：debug_result.halt_reason 非空 + last_error 非空 → message 用语义原因、kind=upstream_defect。
4. `tests/ut/application/test_application.py`：
   - `test_terminal_halt_message_names_upstream_defect`：kind=upstream_defect → dispatcher 文案含 "upstream defect" 且不含 "implementation bug"。
5. `tests/ut/stages/`（codegen）：m.def `Tensor[] x` 不再触发 `_check_plugin_schema_consistency` WARN；manifest 已 relay 时 deploy 前 `state.codegen_manifest` 非空。
6. `tests/ut/...precision_debug...`：`real_errs` 全 None → `max` 不崩、`best_real_max_err=None`。

### 回归
- 既有相关套件全跑：`test_runner_contract.py`、`test_graph_executor.py`、`test_application.py`、
  `test_operator.py`、codegen/precision_debug UT。
- 新增 UT 断言 W3 假阳性消除：foreach-like `Tensor[]` m.def 不再告警。

## 实施结果（2026-08-08）

**已实施全部 6 步**，改动清单见 git status（6 个 src + 8 个 test/fixture）。
**commit**：`327454e4`（v0.2.0，未 push）→ 后续 review 整改（M1–M4/M7）另行 commit。

**验证**：
- 新增 UT（9 个，见下）+ 既有相关套件，`tests/ut` 全量 `--quick` 一次通过：
  **3544 passed, 7 skipped, 3 deselected**（0 failed）。
- 实测 P2 全链：`is_list=true + param_type=REQUIRED` → `from_dict` 派生 DYNAMIC（含 WARN）
  → runner 的 DYNAMIC 闸门放行 `[[1024,1024],[1024,1024]]` 用例（foreach_norm 中止路径消除）。
- 实测 W3 正则：`Tensor[] x` / `Tensor x` / `Tensor? mask` / `Tensor?[]` 全部正确解析，
  TensorList 插件不再假阳性，真实 phantom 仍被抓。

**新增 UT 位置**：
- `tests/ut/domain/test_domain.py`：P2 派生（DYNAMIC / 已 DYNAMIC 不重写 / WARN 暴露 / 全链）。
- `tests/ut/adapters/npu/test_runner_contract.py`：P2 派生 op_spec 放行 list-of-lists；
  REQUIRED+nested 报错含 DYNAMIC hint。
- `tests/ut/orchestration/test_codegen_plugin_schema_consistency.py`：W3 TensorList 不误报 +
  phantom 仍抓；W4 transition 先 relay manifest 再 deploy（mock Deployer 捕获 deploy state）。
- `tests/ut/orchestration/test_graph_executor.py`：P3 upstream halt 消息用语义原因、
  kind=upstream_defect、不用 last_error。
- `tests/ut/application/test_application.py`：P3 dispatcher `upstream_defect` 文案
  （含 scope_reason、不含 "implementation bug"）。
- `tests/ut/orchestration/test_precision_debug_stage.py`：P1 全 None max_err transition 不崩。

**顺带修复的既有失败**（非本次引入）：`harness_devkit_golden.txt` 快照回归门——commit
`6da8b821`（moe_gating_top_k_softmax ignore_output_indices）改了 `_harness_template.py` 但未
再生成 golden，导致 `test_harness_matches_golden` 红。已按该测试自身的约定（"若有意改动，更新
该 golden"）重新生成 golden（diff 仅 6da8b821 的 ignore_output_indices 段，6+/1-）。

## ST 结论（2026-08-08，环境已具备 NPU 后重新评估）

**常规 ST 不补**——6 处修改全是确定性逻辑/编排，9 个新 UT 已守护（§3.8 UT 测纯逻辑），再写
不依赖真实环境的 ST 是 mock 化重复。

**真实验收已做（一次性脚本 `/tmp/verify_foreachnorm_p2.py`，未入测试套件）**，用 foreach_norm
产物临时部署 + 真实 NPU 调用，结论：
- ✅ P2 派生 DYNAMIC 真实触发（`is_list=true + REQUIRED → DYNAMIC`，WARN 打出）。
- ✅ 真实编译成功；smoke harness 成功构建并**越过 PD-CONTRACT 契约检查**（原 halt 场景的契约层
  已解除——list-of-lists 用例被接受）。
- ✅ op 真实注册（正确 PYTHONPATH 下 `torch.ops.cann_bench.foreach_norm` 存在）。
- ⚠️ 真实调用 `foreach_norm([x], 1.0)` 在本机 SIGSEGV（exit 139）——属 foreach_norm kernel
  在本机 torch_npu 2.10.0.post4 环境的独立运行时问题，**与本批框架修复无关，用户指示忽略**
  （2026-08-08）。本批验证到此为止：P2/W4 修复已把该算子从"契约层被卡死（harness 一个都不
  跑）"推进到"真实调用 kernel"。

**正式 npu ST（foreach_norm 上板）当前不写**：kernel 本机运行时问题未解决前做成正式 ST 必
fail，且归因是 kernel 运行时/环境而非框架修复。待本机环境配套下 kernel 能上板、或 cann-bench
含可用 TensorList 算子后，再并入 `tests/st/test_npu.py::TestNPURunnerRealExecution`（既有
`deployed_*` fixture 骨架，§3.11 优先合并），标 `@pytest.mark.npu + slow`。

## 收口（§2.5 唯一通路）
无新通路引入；全部为既有路径内的最小修正。A1 已以确定性工程实现落地（§2b：requirement 阶段
proto 结构信号派生），**不依赖 req-analysis skill 引导**（skill 侧保持并发期不动）；A2（from_dict
派生）仍为确定性兜底（双保险）。

## 实施结果（§2b A1 确定性落地，2026-08-11）

**commit**：`21be75e6`（main 分支；v0.2.0 分支 `1444cee0` 逐字一致，均未 push）。
**改动清单**（4 files，+368/−1）：
- `src/ascendc_devkit/domain/requirement.py`：新增 `read_proto_tensorlist_inputs`（77 行）。
- `src/ascendc_devkit/orchestration/stages/requirement.py`：新增 `_derive_tensorlist_param_type`、
  `_validate_tensorlist_param_type` 并在 transition 接线（95 行）。
- `.claude/skills/ascendc-op-req-analysis/references/op_spec_schema.md`：inputs 补 `is_list`
  字段说明。
- `tests/ut/orchestration/test_requirement_tensorlist.py`：14 个新 UT。

**验证**：
- 新增 UT 全过（14 个：domain 双信号 / 派生幂等 / 交叉校验 / transition 集成）。
- 相关既有套件（requirement/domain/runner 8 文件）**283 passed**（`--quick`，前台实跑）。
- 端到端实测：真实 foreach_norm proto + agent 产 `param_type=REQUIRED` →
  transition 派生为 `DYNAMIC`（WARN 留痕），foreach_norm 原 PD-CONTRACT 循环失败路径解除。

**as-built 偏差**：与 §2b 设计一致，无偏差。内联正则 vs `parse_mdef_param_types` 的取舍
（跨分支 v0.2.0 缺该函数）按 §2b 记录执行，未引入新解析器。
