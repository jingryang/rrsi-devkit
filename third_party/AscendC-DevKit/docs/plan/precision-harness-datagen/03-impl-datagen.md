# precision-debug harness 数据生成层 — 实施（L4）

> 改哪 / 顺序 / 怎么验证。决策见 `02-analysis.md`，事实见 `01-problems.md`。
> 全部改动落在 `adapters/npu/runner.py` `_build_test_harness`（harness 生成器）。

## 改动 1（P1）— serial_cases per-input value_range 透传

- 提取 `_norm_vr(v)` 到 serial_cases 循环上方：float 的 nan/inf → sentinel 字符串
  （`__NAN__`/`__INF__`/`__NINF__`），字符串数字 → float，其余原样返回。
- 循环内每个 input：拷 `shape`/`dtype`/`data`，若 `inp.get("value_range")` 则
  `d["value_range"] = [_norm_vr(lo), _norm_vr(hi)]`（per-input 透传，恢复 fb0d552a 行为）。
- **删** case 级 `_lo = tc.generator_params.get("low")` / `_hi` / `_case["value_range"] = [...]`
  （3c250fd3 引入的广播）。

## 改动 2（P1）— 模板 _resolve_vr + _vr_list

- 新增 `_resolve_vr(_pair)`：sentinel → float（`__NAN__`→nan / `__INF__`→inf / `__NINF__`→-inf），
  缺失/非法 → `[GEN_LOW, GEN_HIGH]`。
- `_vr_list = [_resolve_vr(_i.get('value_range')) for _i in _tc['inputs']]`（per-input list）。
- `gen_input` 调用改用 `_vr_list[_k][0], _vr_list[_k][1]`（按 input index 取各自 range）。
- **删** `_vr = _tc.get('value_range')`（case 级单一）+ `value_ranges=[[_lo, _hi] for _ in _tc['inputs']]`
  （把单一 range 广播到每个 input）。

## 改动 3（P2）— output_dtype 彻底删除（4 处）

- serial_cases：删 `output_dtype = "fp16"` / `tc.inputs[0].get("dtype", ...)` 猜测逻辑 + 相关注释；
  删 `_case` dict 的 `"output_dtype": output_dtype,` 字段。
- 模板：删 `_out_dtype = _tc.get('output_dtype', '') or ...` 定义行；
  `'dtype': getattr(_sr, 'dtype', '') or _out_dtype,` → `'dtype': getattr(_sr, 'dtype', ''),`
  （显示用 compare 返回的权威 dtype，不再猜测兜底）。

## 验证（TDD，先红后绿）
新增/重写 4 个 UT（`tests/ut/adapters/test_adapters.py::TestNPURunner`）：
- `test_harness_per_input_value_range_propagated`：两 input 各自 range 进 case payload
  （clipped_swiglu x `[-1,1]` + group_index `[1,2]`）；harness 用 `_vr_list` / `value_ranges=_vr_list`，
  不用 case 级广播。**注意双引号**：harness 经 `json.dumps→_json_to_py` 序列化，value_range 是
  双引号 JSON 字段（`"value_range": [-1.0, 1.0]`），非 Python 单引号 dict repr——首轮断言用单引号误红，
  已修正为双引号并加来源注释。
- `test_harness_does_not_guess_output_dtype`：harness 中不再出现 `output_dtype` / `_out_dtype`
  （重写自原 `test_harness_output_dtype_is_first_input_dtype`——契约从「取首输入」改为「不猜」）。
- `test_harness_input_without_value_range_falls_back_to_gen`：无 range input 回退 GEN_LOW/HIGH，
  harness 仍生成有效代码。
- `test_harness_per_input_value_range_inf_nan_sentinels`：inf/nan（apply_adam_w case12 `[-inf,inf]` /
  case13 `[nan,nan]`）全链路 sentinel 编码→还原。

回归：`tests/ut/domain/test_cann_bench_cases_loader.py` 11 例（含 apply_adam_w 4 输入异值域）全绿，
证明 loader 侧 per-input range 正确、本次未动 loader（改动 1-3 期间；改动 4 后见下）。

## 改动 4（P4，2026-07-20）— loader `_coerce_float`：字符串 inf/nan value_range 识别

- 新增 `_coerce_float(x)` helper：bool→None，int/float→float(x)，
  字符串→`try float(x)`（含 `-inf/inf/nan`，Python `float()` 原生支持），失败→None。
- `_value_range_to_gen`（:134）：flat 判据从 `isinstance(value_range[0],(int,float))`
  改为 `_coerce_float(value_range[0]) is not None`；flat/nested 分支的 `float(pair[...])`
  改为直接用 `pair[0]/pair[1]`（已 coerce）；nested 分支元素也走 `_coerce_float`。
- `_per_input_value_range`（:161）：flat 判据改用 `_coerce_float`，`float(value_range[...])`
  改为 `_coerce_float`；nested 分支 `float(lo)/float(hi)` 改为 `_coerce_float`。

### 验证（TDD，先红后绿）
新增 1 UT——`test_string_inf_nan_value_range_coerced`（`test_cann_bench_cases_loader.py`）：
rms_norm case 15 `["-inf","inf"]` + case 16 `["nan","nan"]` 经 loader csv 路径 → per-input
value_range 有正确的 float inf/nan + generator_params 有正确的 low/high。
**补测试盲区**：原 `test_harness_per_input_value_range_inf_nan_sentinels` 直接构造 float
TestCase 绕过 loader csv 路径，不触发 loader 的 `isinstance` 字符串门槛。

红→绿：`12 passed/1 skip`（loader UT，+1 新增）；全量 `106 passed/1 skip`（test_adapters
+ test_cann_bench_cases_loader）零回归。

## 结果（完整）
| 阶段 | 范围 | 结果 |
|---|---|---|
| 改动 1-3（2026-07-20） | runner 透传 + output_dtype 删除 + sentinel；test_adapters + loader 回归 | 34 passed, 1 skipped |
| 改动 4（2026-07-20） | loader `_coerce_float` 字符串 inf/nan；test_adapters + loader 全量 | **106 passed, 1 skipped** |

## 不在本轮
- heavy_llm ST：真实 precision_debug 全流程验证 case 7/12 不再假通过（§3.11，需用户确认）。
- kernel 侧（cann-bench 仓）：group_index 语义 / sum 判断的真 kernel bug。
