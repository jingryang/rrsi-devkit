# 多输入算子空 dtype 穿透 — 实施方案（L4）

> 动手前写，按需产出。本文给出具体改哪个函数、什么顺序、怎么验证。
> 决策与理由见同目录 `02-analysis.md`（L3）；事实见 `01-problems.md`（L1）。
> 三处改动对应 L3 的 A（主修复）/ D（契约校验）/ B（存量兜底）。
>
> **实施状态（2026-08-07）**：A/D/B 三处改动**已全部实施并验证**——
> 新增 UT 11 个（loader 5 + csv 2 + runner 3 + 端到端集成 1）+ 真实 foreach 集成测试 2 个
> 全绿；定向回归通过；全量 UT `--quick` 3520 passed / 7 skipped（skip 均为既有
> cann-bench 条件跳过，与本改动无关）；真实 foreach_addcdiv_scalar cases.csv
> loader→runner 全链路 20 case 无空 dtype。实施期间 `test_integration.py` 偶发
> segfault 一次，单独重跑 30 passed——已知偶发原生崩溃（`st-suite-sporadic-native-crash`），
> 崩溃栈（skill_config/dispatcher）不在本次改动路径上。
>
> **2026-08-07 补充测试**（应 UT/ST 充分性审查）：新增
> `test_partial_dtypes_warns_no_broadcast`（覆盖 `1<len<输入数` 中间态的 WARN 分支，
> 原缺失）+ `test_real_foreach_loader_to_harness_no_empty_dtype`（真实 cases.csv →
> loader 广播 → runner 烘焙 harness 端到端产物链路回归门）。
>
> **2026-08-07 review 修正（LOCAL-unpushed-44122e0d-review）**：
> - **改动 B 日志通道偏差回填**：实现用已 import 的 `infra.Logger.warn`（stderr + run.log），
>   非本段草图的 stdlib `logger.warning`（仅 stderr）——运行期无需补模块 logger。选 Logger
>   更优：与框架其他告警一致、进 run.log。
> - **WARN 消息修正**：`input {_idx}`（误用 case 序号）→ `input {_proto_idx}`（用例内 input
>   序号）；「全用例无声明回退 fp16」不再冒充「继承用例声明 dtype」；异构 dtype 用例的空输入
>   标注「继承值仅防崩、不可信」。新增 runner UT 3 条（input 序号 / 异构标注 / fp16 回退措辞）。
> - **改动 A WARN 条件放宽**：`1 < len < 输入数` → `len > 1 且 len ≠ 输入数`（多填 dtype 同样
>   结构不齐，原被 `raw_dtype` 静默截断无 WARN）。新增 loader UT 1 条（多填 WARN）。
> - **改动 D 报错消息**：区分「少于/多于输入数」，不再一律「不支持广播省略」。
> - **nominal 缺口说明**：TDD 清单的 `test_full_dtypes_ok`/`test_scalar_single_input_ok`
>   未独立加——`test_op_row_name_and_inputs`（4/4 全量）/`test_single_input_collapse_wrapped`
>   （1/1 单输入）已覆盖同路径，无独立用例必要。

## 改动清单总览

| # | 文件 | 函数 | 职责 |
|---|---|---|---|
| A | `src/ascendc_devkit/domain/cann_bench_cases_loader.py` | `parse_cann_bench_csv` | 单 dtype 广播（合法推理） |
| D | `src/ascendc_devkit/adapters/testdesign/csv_to_testcases.py` | `_row_to_testcase` | 契约校验报错（输入错误） |
| B | `src/ascendc_devkit/adapters/npu/runner.py` | `_build_test_harness` | 存量空/缺失 dtype 继承 + WARN（防崩） |

---

## 改动 A — loader 单 dtype 广播（cann-bench adapter 边界）

**文件**：`src/ascendc_devkit/domain/cann_bench_cases_loader.py`

**位置**：`parse_cann_bench_csv` 内 `dtypes = _loads_or(row.get("dtype"), [])` 之后、
`for i, shape in enumerate(shapes)` 之前插入：

```python
# cann-bench 约定：dtype 列允许裸串（isinstance str），也允许单元素数组「所有
# tensor 输入共享该 dtype」（foreach 类多输入算子）。复刻 cann-bench 自家 loader
# （cann_loader._parse_case: len==1 && 多输入 → dtypes*输入数）——本 loader 是
# cann-bench 格式产权层，忠实转写上游约定（§1.13），非修正、非报错。
if isinstance(dtypes, str):
    dtypes = [dtypes]
_num_shapes = sum(1 for s in shapes if s is not None)
if len(dtypes) == 1 and _num_shapes > 1:
    dtypes = dtypes * _num_shapes
elif 1 < len(dtypes) < _num_shapes:
    logger.warning(
        "cann-bench case %s: dtype len=%d < 非空输入数=%d（仅广播单 dtype 约定，"
        "缺 dtype 的输入将由 runner 存量兜底继承）",
        case_id, len(dtypes), _num_shapes,
    )
```

**配套**：模块顶部补 `import logging` + `logger = logging.getLogger(__name__)`
（对齐 `domain/operator.py:8` 的仓库惯例）。

**注意**：
- 每输入 `raw_dtype = (dtypes[i] if i < len(dtypes) else "") or ""` 保持不动——广播后恒有值，
  该行由「bug 源头」变为「防御性兜底」。
- 广播计数 `_num_shapes` 只算**非 None** shape（`None` = optional 输入被 drop，不能参与广播，
  见 `test_single_dtype_with_null_input_dropped`）。

---

## 改动 D — csv_to_testcases 契约校验报错（devkit 边界）

**文件**：`src/ascendc_devkit/adapters/testdesign/csv_to_testcases.py`

**位置**：`_row_to_testcase` 内，`shapes/dtypes/formats` 三个 `_as_*` 归一之后、构建 `inputs` 之前插入：

```python
# 契约校验（§1.3 加载期校验优于运行期暴露）：testcase_csv.json 要求
# stc_input_dtypes 逐输入声明（并行数组）。声明不足 = producer 违约（输入错误），
# 显式报错让 LLM/skill 修正，而非静默截断（旧 n=min）或静默降级 fp16。
num_tensor_inputs = len(shapes)
if dtypes and len(dtypes) != num_tensor_inputs:
    raise ValueError(
        f"CSV '{csv_path}' row {idx}: stc_input_dtypes 声明 {len(dtypes)} 个 dtype，"
        f"但 stc_inputs 有 {num_tensor_inputs} 个 tensor 输入"
        f"（契约要求逐输入声明，不支持广播省略）"
    )
```

**配套**：把 `n = min(len(shapes), len(dtypes), len(formats)) if dtypes and formats else len(shapes)`
改为 `n = len(shapes)`——校验后 dtype 数必等于输入数，`min` 只可能被 formats 长度误截断；
`entry["format"]` 的 `if i < len(formats)` 保持（format 是弱契约元数据，缺省允许）。

**注意**：校验是**逐行**的（单行违约报单行），不连坐整份 CSV；`dtypes` 为空（`[]`）时不报
（无 dtype 声明的用例走 runner 的 `"fp16"` 默认，属既有行为）。

---

## 改动 B — runner 存量空/缺失 dtype 继承 + WARN（通用兜底）

**文件**：`src/ascendc_devkit/adapters/npu/runner.py`

**位置**：`_build_test_harness` 内 `for _idx, tc in enumerate(test_cases)` 循环，`for inp in tc.inputs`
之前计算用例级 dtype 兜底；`inp.get("dtype", "fp16")`（现 line 777）改为继承：

```python
# 用例级 dtype 兜底 = 首个非空声明 dtype（业务语义：多输入同 dtype 用例声明不足
# 即继承；空串/缺 key 均视同未声明）。仅对「存量」无依据数据防崩（旧快照残值），
# 不上升为合法语义——新数据经 loader 广播（改动 A）/ csv 校验（改动 D）后不会带
# 空 dtype 到达此处。全用例均无声明时才落回 fp16 既有默认。
_case_dtype = next(
    (_i.get("dtype") for _i in tc.inputs if _i.get("dtype")), "fp16"
)
```
```python
    _d = inp.get("dtype")
    if not _d:                      # 空串 "" / 缺失 None 一视同仁
        logger.warning(
            "case %r input %d dtype 为空/缺失，继承用例声明 dtype=%r"
            "（loader 广播应已展开；空值说明来源为旧快照或非 loader 生产者）",
            getattr(tc, "name", "case"), _idx, _case_dtype,
        )
        _d = _case_dtype
    d = {"shape": inp["shape"], "dtype": _d, "proto_idx": _proto_idx}
```

**配套**：`runner.py` 顶部补模块 logger（该文件当前无 logger，需确认仓库注入方式后对齐）。

**注意**：
- 保留「全用例无 dtype → fp16」的既有默认（`_case_dtype` 的 `"fp16"` 尾项）——那是「无信息可循」
  的合理 last resort，非业务语义代理。
- 不新增「混合 dtype 继承」逻辑：只在「空/缺失」触发，且继承的是**用例首声明**（与旧 loader 语义
  及 cann-bench 广播结果一致）。

---

## TDD 测试清单（§3.1 先测试后实现）

### 改动 A — `tests/ut/domain/test_cann_bench_cases_loader.py` 增补

| 用例 | 断言 |
|---|---|
| `test_single_dtype_broadcast_to_multi_input` | 3 非空 shape + `["float32"]` → 3 输入全 `"fp32"`（foreach 复现，红→绿） |
| `test_single_dtype_with_null_input_dropped` | 3 shape 含 1 个 `None` + `["float16"]` → 2 输入全 `"fp16"`（广播只计非空） |
| `test_scalar_dtype_string_wrapped` | `dtype="float32"`（裸串）→ 1 输入 `"fp32"`（修「裸串按字符索引」潜在 bug） |
| `test_per_input_dtypes_unchanged` | `["fp16","fp32"]` 2 输入 → 原样（回归保护，防广播误伤多 dtype 算子） |
| `test_real_foreach_cases_no_empty_dtype` | 真实 `foreach_addcdiv_scalar/cases.csv`（`@pytest.mark.external_repo`，缺失 skip）→ 无任何输入 dtype 为空 |

### 改动 D — `tests/ut/adapters/test_csv_to_testcases*.py`（或新建）增补

| 用例 | 断言 |
|---|---|
| `test_short_dtypes_raises_contract_error` | 3 shapes + 1 dtype → `ValueError`，信息含行号/两个计数 |
| `test_full_dtypes_ok` | 3 shapes + 3 dtypes → 正常生成（回归保护） |
| `test_scalar_single_input_ok` | 1 shape + 1 dtype → 正常（单输入合法） |
| `test_dtypes_empty_no_error` | 3 shapes + 空 dtype 列 → 不报错（走既有 fp16 默认） |

### 改动 B — runner 级 UT（`tests/ut/adapters/test_runner_execute.py` 或 `test_harness_dtype.py`）增补

| 用例 | 断言 |
|---|---|
| `test_stale_empty_dtype_inherits_case_declared` | tc inputs `[fp32,"",""]` → 烘焙后 3 输入全 `fp32` + WARN |
| `test_all_empty_dtype_falls_back_fp16` | inputs `["",""]` → 烘焙后 `fp16`（既有默认不破坏） |
| `test_runner_full_dtype_unchanged` | 全声明 dtype 用例 → 原样、无 WARN |

---

## 验证方式（§3.2/§3.3 前台执行）

1. **UT 逐项**：A/D/B 各自新用例红→绿（先写测试见红，再实现转绿）。
2. **定向回归**：
   - `pytest tests/ut/domain/test_cann_bench_cases_loader.py`（loader 既有 18 例不被广播破坏）；
   - `pytest tests/ut/adapters/` 相关 runner/harness 用例（重点 `moe_re_routing`/`roi_pooling`/
     `exp` 等多 dtype 用例——广播仅在 `len==1` 触发，不涉多 dtype，须验证不受影响）。
3. **全量回归**：全量 UT + 非 heavy_llm ST（§3.6），确认无既有行为改变。
4. **重放验证（本 run 场景）**：对 `foreach_addcdiv_scalar` 用 `cases_source=cannbench` 走一次
   test_design → 精度 precheck，确认 `test_cases.json` 无空 dtype、harness 无 ValueError。
5. **存量快照验证（改动 B 生效点）**：用本 run `state_snapshot.json`（含空 dtype 用例）resume，
   确认继承 + WARN 而非 ValueError。

## 实施顺序

1. **改动 A + 测试**（本次 halt 根修，最高优先）。
2. **改动 D + 测试**（devkit 契约校验，与 A 同根、风险独立）。
3. **改动 B + 测试**（存量兜底，最后，依赖 A/D 判断其触发面）。
4. 每步完成即跑对应 UT；全部完成后全量回归 + 重放验证。

## 相邻工作边界

- **`precision-scope-upstream-halt-eval-loss/`**：`upstream→__halt__` 路由本身的修复，与本「修复
  upstream 根因（loader 未广播）」正交；本案修好 loader 后该 halt 不再因空 dtype 触发。
- **`codegen-dtype-strategy/`**（design 侧 dtype 策略）：非计算算子 native dtype，与本「case 加载
  dtype 广播」不同层，不冲突。

## heavy_llm 待跑验证清单（2026-08-07 用户决策：记录，下次 batch 顺带验证）

> §3.11：heavy_llm 不默认随 pytest 跑，执行前需用户确认。本次非 heavy_llm 的 UT/ST 已全部补齐
> （3520 UT 全绿）；以下两项真实链路验证成本高（真实 LLM + NPU，分钟级 + token），按用户决策
> 记录为待跑清单，**下次 foreach 类 batch 跑批时顺带核对**，不单独立 heavy_llm 用例：

1. **本次 dtype 改动（A/D/B）真实重跑**：`foreach_addcdiv_scalar` 走 `cases_source=cannbench`
   全流水线，确认 **不再 halt、进 cannbench_eval 评分**。核对点：
   - `test_cases.json` 无空 dtype（loader 广播生效）；
   - precision_debug 不再因 `str_to_torch_dtype("")` ValueError halt；
   - `cannbench_eval` 产出评分而非 0。
2. **`a1035798`（skill dtype 策略）落地核对**：同批 design 产物（design_spec.json / 产出代码）检查
   dtype 是否按「非计算算子 native dtype、解耦升精度/FP32、禁 int→FP」落地——该 skill 话术类
   改动无 schema/代码可断言结构，真实行为只能靠 batch 产物观察。
