# precision-debug harness 数据生成层 — 问题记录（L1）

> 纯事实快照（哪里坏了 / 凭什么这么说）。不提方案、不排顺序、不写决策。
> 触发算子：clipped_swiglu（cann-bench，多输入异值域 + int64 index 输入）；
> 覆盖验证：apply_adam_w（4 输入异值域）。
> 涉及代码：`adapters/npu/runner.py` `_build_test_harness`（harness 生成器）。

## 背景：假通过现象

precision-debug 闭环报 clipped_swiglu **0/20 失败**（全绿），但同源 cann-bench 评测报
**2/20 失败**（case 7、case 12）。两者用同一 golden + 同一 kernel，差异 100% 在 devkit
侧 harness 数据生成。本 L1 记录 harness 数据生成层的两个 bug（一个回归、一个新缺陷），
二者均由同一 commit `3c250fd3` 引入。

## P1 — per-input value_range 透传回归（3c250fd3 回退 fb0d552a / e2e-moe P3e）

### 现象
clipped_swiglu 的 `group_index` 输入应在值域 `[1,2]` 生成（索引语义），实际被生成在
`[-1,1]`（首个张量输入 `x` 的值域）→ 该输入求和 ≤ 0 → golden 参考全 0 → kernel 输出
也全 0（**双重归零巧合**）→ max_diff=0 → 假通过。

### 凭证（git 证据，`git log -S 'value_range' -- runner.py`）
- **fb0d552a**（`feat(evolve): 多输出算子 harness 修复`，e2e-moe-re-routing P3e）曾正确
  实现 per-input value_range 透传——serial_cases 循环里 `d["value_range"] = inp["value_range"]`
  （每个 input 自带自己的 range）。产权见 `e2e-moe-re-routing/01-problems.md` P3e 与
  `e2e-moe-re-routing/03-impl-harness-softgate.md` 改动 2-3。
- **3c250fd3**（`update run_tests for cann-bench task`，2026-07-13）删除该透传，改为
  case 级单一 range：`_lo = tc.generator_params.get("low", -1.0)` / `_hi = ...("high", 1.0)`，
  再 `_case["value_range"] = [_norm_vr(_lo), _norm_vr(_hi)]`，模板
  `value_ranges=[[_lo, _hi] for _ in _tc['inputs']]` 把单一 range 广播到每个 input。
- `tc.generator_params` 的 low/high 来自 loader `_value_range_to_gen`——它只取 value_range
  的**第一个**非空 pair（flat 或 nested 首项）。故多输入异值域被压扁成首个输入的 range。

### 证据 diff（3c250fd3；`-` = 被删的 per-input 透传，`+` = 替换的 case 级广播）
```diff
-                    # per-input value_range (E): carried so gen_input uses each
-                    if inp.get("value_range") is not None:
-                        d["value_range"] = inp["value_range"]
+                _lo = tc.generator_params.get("low", -1.0)
+                _hi = tc.generator_params.get("high", 1.0)
+                _case["value_range"] = [_norm_vr(_lo), _norm_vr(_hi)]
+                value_ranges=[[_lo, _hi] for _ in _tc['inputs']],
```

### 影响范围
任何「多输入异值域」cann-bench 算子都中招：
- clipped_swiglu：x `[-1,1]` + group_index `[1,2]` → group_index 被压成 `[-1,1]`。
- apply_adam_w：4 输入 `[-1,1]/[-1,1]/[-0.1,0.1]/[0,0.1]` → 后三个全被压成 `[-1,1]`。
- moe_re_routing（e2e-moe P3e 原始反例）：tokens `[-1,1]` + expert_token_num `[1,128]`。

### loader 侧（非本 bug）
`domain/cann_bench_cases_loader.py` `_per_input_value_range` 正确地为每个 input 挂载
各自 value_range（`cases_loader` UT 11 绿，含 apply_adam_w 4 输入异值域验证）。bug 全在
runner 序列化层丢弃了 loader 已挂好的 per-input range。

## P2 — output_dtype = 首输入 dtype 猜测缺陷（3c250fd3 引入）

### 现象
harness 序列化 test case 时，`output_dtype` 取「第一个输入的 dtype」，且循环内有
**末尾覆盖 bug**：`if not output_dtype or output_dtype == "fp16": output_dtype = inp.get("dtype")`
每轮重判，最终落到**末尾**输入的 dtype（如 group_index=int64 会污染 output_dtype）。

### 凭证
- 引入点 = **3c250fd3**（`git log -S 'output_dtype' -- runner.py` 全仓唯一改变其出现次数的
  commit）。diff：
  ```diff
  +            output_dtype = "fp16"
  +                    if not output_dtype or output_dtype == "fp16":
  +                        output_dtype = inp.get("dtype", "fp16")
  +                "output_dtype": output_dtype,
  ```
- 缺陷本质：**输出 dtype 与首个输入 dtype 之间没有一般关系**。反例：argmax（fp16→int64）、
  cast（任意→任意）。用户指出：「选用输入的第一个元素的类型作为输出类型不合理」。
- 实际作用面（修复前）：output_dtype 仅作**显示 fallback**（`'dtype': getattr(_sr,'dtype','') or _out_dtype`），
  真实精度阈值用的是 runtime dtype（`str(_k_tensors[0].dtype)`）。故此字段从未参与判定，
  是「错误但无害显示」+「末尾覆盖」双重问题。

### cases 来源限制
cann-bench `cases.csv` 无 output dtype 列；proto.yaml 的 output dtype 是算子级（非 per-case）。
harness 生成层无从可靠得知 per-case output dtype——这正是「不该猜」的根因。

## P3 — inf/nan 值处理（非 bug，记录链路一致性）

apply_adam_w case 12 value_range `[-inf, inf]`、case 13 `[nan, nan]`。loader 的 `float()`
把 csv 字符串 `-.inf`/`.nan` 转成真 float；runner 序列化须经 JSON（`json.dumps` 对 NaN/Infinity
会产 Python `NaN`/`Infinity` 非 JSON 字面量，作为 Python 代码执行则触发 `NameError`）。本项确认
链路对 inf/nan 等价普通数值——非 bug，归 L4 实现细节（sentinel 编码 `__INF__/__NAN__/__NINF__`）。

## P4 — loader 字符串 inf/nan value_range 不识别（cann-bench CSV 约定 × isinstance 门槛）

### 现象
rms_norm case 15 `value_range=["-inf","inf"]` 经 loader 后，`generator_params`=None、
per-input `value_range`=None（缺失），导致 harness fallback 到默认 `[-1,1]` 生成普通
输入 → inf/nan 特殊值测试意图完全落空 + **假通过**（RmsNorm 正常输入当然算对）。

### 凭证
- 实测（2026-07-20）：`load_cann_bench_cases(rms_norm/cases.csv)` → case 15 `.generator=None`、
  `.generator_params=None`、`inputs[0].value_range=None`。
- 根因：JSON 标准不支持 Infinity/NaN 字面量，cann-bench CSV 把 `-inf/inf/nan` 写成字符串。
  `_per_input_value_range`（:161）和 `_value_range_to_gen`（:134）用 `isinstance(x,(int,float))`
  判 flat range——字符串 `"-inf"` 不是 int/float → 被判为「既非 flat 数字也非 nested list」→
  两个函数均返回空/None。
- Python `float("-inf")/float("inf")/float("nan")` 原生支持这些特殊字符串，loader 应尝试
  转换但未做。

### 与 P1/P2 的关系
- P1/P2 修复了 **runner** 序列化层（per-input value_range 透传 + output_dtype 删除），但
  **loader 没把字符串 inf/nan 送进来**——runner 拿到的是空，per-input 透传对空输入无效果。
- 原 P3（runner sentinel → `__INF__/__NAN__/__NINF__`→`_resolve_vr`）对 float inf/nan
  正确——前提是 loader 已把字符串转成 float。P4 补这个前提。
- 原 `test_harness_per_input_value_range_inf_nan_sentinels` 测试直接构造 `float("-inf")`
  的 TestCase（绕过 loader csv 路径），是**测试盲区**——没覆盖 loader 字符串解析。

### 影响范围
cann-bench `cases.csv` 中任何用字符串 `-inf/inf/nan` 的 value_range 特殊值 case 均丢失；
已验证 rms_norm case 15/16 受此影响。

### 修复
见 `03-impl-datagen.md` 改动 4——loader `_coerce_float` helper（字符串→float，含 inf/nan）
+ TDD `test_string_inf_nan_value_range_coerced`（走 loader csv 路径，补测试盲区）。

## 不在本轮
- **kernel 侧**（cann-bench 仓）：clipped_swiglu group_index 语义 / sum 判断的真 kernel bug
  未处理（用户决策「拆开，本次只修 harness」）。
- **heavy_llm ST**：真实 precision_debug 全流程端到端验证（§3.11，需用户确认才跑）。
