# 44 — proto precision_thresholds 全链路贯穿 + 比较方法对齐 cann-bench（L4 实施方案）

> 工作线：self-evolution
> 状态：**已实施**（2026-07-14，commit `7696279`）；+56 UT 全绿；全量 1954 passed / 15 pre-existing env fail（非本方案回归，git stash 验证）
> 关联 L3：`48-precision-spec-threading-analysis.md`
> L1 问题：`06-problems.md` P78

## 改动（函数级，7 处）

### 改动 1 — `domain/operator.py`：规格字段 + coerce 纯函数 + dtype list 降级

- 新增纯函数 `coerce_precision_thresholds(raw) -> dict[str, float] | None`：非 dict/空 → `None`（proto 未声明精度规格，下游用默认表 + 显式标记，不静默）；逐项 `float()`，坏值跳过 + warning（§1.3 加载期校验、§1.4 不留坏值兜底分支）。
- `OperatorSpec` 加 `precision_thresholds: dict[str, float] | None = None`（proto `{dtype: max_diff_or_relative}`）。`from_dict` 末尾 `precision_thresholds=coerce_precision_thresholds(d.get("precision_thresholds"))`（不走 `filter_known_fields`，显式读）。
- `TensorSpec` 加 `compare: bool | None = None`（proto output `compare: false` → 跳过该输出比较，对应 cann-bench `ignore_output_indices`；`None` = 正常比较）。
- `_route`（dtype list→scalar 降级）：proto inputs/outputs dtype 是 **list**（多 dtype 支持，如 `[float16, bfloat16]`），devkit `TensorSpec.dtype` 是 scalar。命中时 `replace(ts, dtype=ts.dtype[0] if ts.dtype else "")` 取主 dtype，保证下游 dtype 派生拿到 scalar。
- import：`from dataclasses import dataclass, field, fields, replace`（加 `replace`）。
- 序列化零改动（`asdict`/`_rebuild_dataclass` 自动处理 dict 与 bool）。

### 改动 2 — proto 解析（双路接入，确定性 post-step，非 LLM 提取——契约值非算子知识 §1.5/§2.7）

> agent 回吐的 requirement.json schema 是 `op_name/inputs/outputs` only，**丢掉** proto 的 `precision_thresholds`。两路都确定性重读 proto 补回（proto 覆盖优先，单一源）。

**`domain/requirement.py`**：
- 新增模块级 `read_proto_precision(proto_path) -> tuple[dict[str, float] | None, list[bool | None]]`：读 yaml/json → 取顶层 `operator:` 块（fallback flat map）→ 返回 `(precision_thresholds 经 coerce, 各 output 的 compare 标志列表)`。graceful：`None`/missing/unreadable/non-mapping → `(None, [])`，绝不 raise（stage transition 调用，§1.3 加载期校验但对 malformed proto 降级非中止）。
- `Requirement.from_dict`：`op_block = d.get("op") if "op" in d else d.get("operator")`（devkit `op:` / cann-bench `operator:` 双兼容），再 `OperatorSpec.from_dict(op_block)`（自动读 precision_thresholds）。

**`orchestration/stages/requirement.py`（Flow A — self_evolve 主路径）**：
- `transition` 中 `op_spec = OperatorSpec.from_dict(req_data)` 之后，加确定性 post-step `op_spec = self._attach_proto(op_spec, state.requirement_path)`。
- 新增静态方法 `_attach_proto(op_spec, proto_path)`：调 `read_proto_precision` → `dataclasses.replace` patch `precision_thresholds` + 逐 output `compare` 标志（两者皆 None 时 no-op）。graceful：路径 None/不存在 → 返回原 op_spec。

### 改动 3 — `adapters/npu/precision_compare.py`（新增，devkit 自实现标准方法，零 import cann-bench §1.7）

整模块一次实现（stage-1 MERE/MARE 与 stage-2 小值域/相消相互依赖，拆 commit 会有临时误杀窗口；parity UT 是整模块安全网）。

**阈值数据**（dict literal，值对齐 cann-bench `thresholds.py` per-dtype 语义——这是数据，非代码）：
- `DEFAULT_THRESHOLDS`：float16=2⁻¹⁰、bfloat16=2⁻⁷、float32/float64=2⁻¹³、hifloat32=2⁻¹¹、float8_e4m3fn=2⁻³、float8_e5m2=2⁻²、int*/uint*=0。
- `SMALL_VALUE_THRESHOLDS` / `SMALL_VALUE_ERROR_THRESHOLDS` / `CANCEL_BOUNDARY_THRESHOLDS` / `CANCEL_ZERO_THRESHOLDS`（stage-2 兜底用，值对齐 thresholds.py:50-127）。

**公开 API**：
- `threshold_for_dtype(dtype_str, merged) -> float`：merged（含 proto 覆盖）优先 → `DEFAULT_THRESHOLDS` → 未知 dtype 回退 float32=2⁻¹³。
- `_compare_single(output, golden, threshold, dtype, native_ref=None) -> OutputVerdict`：按 dtype 派生方法——
  - **bit-exact**（`threshold==0` 且浮点）：`_BIT_VIEW` 映射 `.view(int_dtype)` 字节级比（区分 ±0.0/NaN payload/Inf 符号）；golden cast 产生新 inf 时 warning（数据范围超 dtype，bit-exact 失败可能非计算错）。
  - **整数**：`torch.equal` 精确匹配；不等再 `abs(output.long()-golden.long()) > max(threshold,0)` 计 mismatch（`int8:1.0` = 允许 ±1）。
  - **浮点 MERE/MARE**：`relative_error = |actual-golden|/(|golden|+1e-7)`；NaN 位置不匹配→fail；单边 inf 饱和到 dtype 最大有限值续比，双边同号 inf 匹配并排除；**stage-1** `MERE<thr AND MARE<10*thr` → 通过；**stage-2** 小值域（`|golden|<small_value_threshold`）+ 相消（output≈0 且 golden∈[svt, cancel_boundary)）兜底——`ErrorCount_npu/max(ErrorCount_native,1) ≤ 2`；正常值域有超标点 → 直接失败。`native_ref=None` → golden 截断当参考（cpu_diff=0，与 cann-bench 同路径）。
- `compare_outputs(output, golden, merged_thresholds, ignore_indices=None, native_refs=None) -> PrecisionVerdict`：`_normalize_tensors` 归一（tensor/list/tuple/None，保留 None 占位维持索引对齐）；逐输出按运行时 `str(t.dtype)` 查 `threshold_for_dtype` → `_compare_single`；`passed = 全输出 AND`；None 处理（双边 None→pass、单边→fail）；`ignore_indices` 跳过（passed 不计入）；返回聚合 `PrecisionVerdict`（含逐输出 `output_verdicts`）。
- dataclass：`OutputVerdict`（`passed` + mere/mare/max_diff/mean_diff/mismatch_count/total_count/mismatch_ratio/small_value_passed/cancel_passed/error_msg`，带 `to_dict`）/ `PrecisionVerdict`。

纯 torch CPU（张量先 `.cpu()`），可在 harness subprocess 跑。

### 改动 4 — `adapters/npu/runner.py`：删硬编参 + harness 调 compare_outputs + 返回重构

- **`execute()` 删 `precision_threshold: float = 1e-2` 参数**（§1.4 不留 deprecated；零 caller 传——perf/precision_debug 全省略，threshold 来自 op_spec）。
- **`run_env` PYTHONPATH** 加 `_devkit_src = str(Path(__file__).resolve().parents[3])`：harness subprocess 能 `from ascendc_devkit.adapters.npu.precision_compare import compare_outputs`。
- **`_build_test_harness` codegen**：顶部 import `compare_outputs, DEFAULT_THRESHOLDS`；嵌入 `op_precision_thresholds`（dict|None）+ 各 output `compare` 标志；计算 `merged_thresholds = dict(DEFAULT_THRESHOLDS); merged_thresholds.update(op or {})`、`ignore_indices`（compare:false）、`precision_spec_declared`（bool，proto 是否声明了 precision_thresholds——**P78 显式标记**）、`case_pass_flags`；替换原 :496-541 内联 float64-abs-diff 块为调 `compare_outputs(kernel_out_list, golden_list, merged_thresholds, ignore_indices, native_refs)`（harness 持 torch 张量，直接传）；`output_comparisons` 每项带 `passed/dtype/threshold/mere/mare/mismatch_count/total_count/small_value_passed/cancel_passed`（转发 `OutputVerdict`）；无 golden / except 分支 append `case_pass_flags(False)`；output dict 加 `passed`/`thresholds`/`precision_spec_declared`。
- **`execute()` 返回块重构**：读回 harness case_details；`passed = bool(data.get("passed"))`（harness 按 cann-bench 语义逐 case 逐输出已算好）；删 `threshold` 标量键 + `passed = max_diff <= precision_threshold`（:228/:235 旧判据）；返回加 `thresholds`（merged map，可观测）、`precision_spec_declared`、`case_details`。
- 门控在 harness 内（张量在那）；thresholds 经嵌入传进；不把 Python dict 注入 codegen 逻辑（只传值）。

### 改动 5 — `orchestration/stages/perf.py:106-112`：dtype 派生

`primary_dtype = (op_spec.inputs[0].dtype if op_spec.inputs else "fp16") or "fp16"`（首个输入 = 主 tensor，与 harness 首输入口径一致）；test_cases 用 `primary_dtype` 替硬编 `"fp16"`。

### 改动 6 — `application/debug_service.py:115`：spec 选择

优先 `state.requirement.op_spec`（带 precision_thresholds）over 裸壳 `op_identity.spec`；requirement 缺失才回退 op_identity；都没有 raise。**不修这条，precision_debug（DQ 案例路径）拿不到阈值**。

### 改动 7 — 第二源清理（全部指向贯穿值，§2.1/§2.7 skill 自包含）

- `cli/commands/debug.py:109`：output 显示 `output[{idx}] ({dtype}) passed={passed} thr={threshold} diff={diff}`；`:133` 失败用 per-output `passed`（**删 `0.01` 兜底**）：`failed = [cd for cd in case_details if cd.get('error') or cd.get('passed') is False or any(not o.get('passed', False) for o in cd.get('outputs', []))]`。
- skill `stage-precision-debug/.../prompts/run_tests.md:117`：「权威判据 = `result.json` `case_details[].outputs[].passed`（runner 按 proto precision_thresholds + cann-bench 语义逐输出判）；不要自己造阈值（旧 `diff>1e-2` 口径已废，会把 DQ int8 ±1 合法量化差误杀）」。
- skill `gates/static-check/symptom-table.md`：rtol/atol 表上方加注「权威 pass/fail = `case_details[].outputs[].passed`；下表仅人工排查/printf 调试 dtype 量级参考，非运行时门」。
- skill `gates/printf/printf-debug.md`：顶部加注「判定权威 = `case_details[].outputs[].passed`；本文 printf 数值观察/`1e-3h` 等量级启发式是定位发散点的辅助手段，不是通过/失败门」。

## 验证（TDD §3.1，UT mock §3.8）

**新增 UT +56**（全绿）：
- `tests/ut/adapters/test_precision_compare.py`（**27**）：整数 exact/`int8:1.0`±1/±2/`int:0`；浮点 MERE/MARE（构造 known diff 手算期望，`<thr AND <10thr` 通过 + 边界失败）；bit-exact（thr=0 浮点，±0.0/NaN payload 区分）；小值域 stage-2（`|golden|<svt`、native=None→NPU 须 0 错）；相消 stage-2（output≈0+golden 边界）；NaN 位置不匹配→fail；单边 inf 饱和续比；双边同号 inf 匹配；多输出（一失败→整体失败）；ignore_indices 跳过；dtype 回退（未知→float32）；`threshold_for_dtype` merged/默认/回退。**parity UT**（cann-bench 在场才跑：`kernel_eval` 需 `PYTHONPATH=<cann-bench>/src` + `TORCH_DEVICE_BACKEND_AUTOLOAD=0`，否则 §3.7 skip）：同一组 (output,golden,threshold) 过 devkit 标准方法 + cann-bench 原版，断言 `passed/mere/mare` 一致。
- `tests/ut/domain/test_domain.py`（**+15**）：`TestPrecisionThresholds`（coerce 各路径 8）/ `TestTensorSpecCompare`（4）/ `TestSpecSerializationRoundTrip`（2）/ `TestProtoPrecisionParsing`（6）/ `TestRequirementFromDictProto`（3）。
- `tests/ut/orchestration/test_requirement_proto.py`（**9**）：`_attach_proto` patch/preserve/transfer/missing/none/nonexistent/prose_md + transition 端到端 + without_proto_path。
- `tests/ut/adapters/test_runner_execute.py`（**5**）：无 precision_threshold 参 / DQ int8 通过 / failed verdict / 执行失败 / PYTHONPATH 含 devkit src。

**全量回归**：UT 1954 passed，15 pre-existing env fail（`TestNPURunner::*` 13 + `test_detect_returns_known_generation` + `test_progress_callback_accepted`——NPU `_soc_version` raise / CANN toolkit 缺失，§3.7 环境缺失）。**git stash 验证**：15 fail 在 clean main 同样复现，非 P78 回归。

**heavy_llm/npu ST（§3.11）**：核心是确定性路径（proto 解析 + 比较数学，UT 覆盖）。端到端「真实 int8 op 在 NPU ±1 差 → 判 PASS」（DQ 冤杀解除实证）属 heavy_llm/npu ST，**本次未跑**——交付前用户决策。未跑诚实记录（§3.11）：本次未覆盖 heavy_llm：DQ 真机 int8 ±1 端到端。

## cann-bench 语义行号对照（parity 基准，devkit 不 import）

| 语义 | cann-bench 行号 | devkit 复刻位置 |
|---|---|---|
| 逐输出 + 全输出 AND | compare.py:755-834 | `compare_outputs` |
| 阈值合并（默认 ⊕ proto） | evaluator.py:891-911 | runner harness `merged_thresholds` |
| dtype→阈值 | compare.py:703-708 | `threshold_for_dtype` |
| 整数 exact + abs-diff | compare.py:291-347 | `_compare_single` 整数分支 |
| bit-exact（thr==0 浮点） | compare.py:230-288 | `_compare_single` bit-exact 分支 |
| 浮点 MERE/MARE stage-1 | compare.py:420-502 | `_compare_single` 浮点 stage-1 |
| 小值域/相消 stage-2 | compare.py:504-667 | `_compare_single` 浮点 stage-2 |
| NaN/Inf 饱和 | compare.py:356-418 | `_compare_single` NaN/Inf 块 |
| 默认表 | thresholds.py:28-46 | `DEFAULT_THRESHOLDS` |
| 无 golden / compare:false | compare.py:757-767 | `compare_outputs` None/ignore 分支 |
