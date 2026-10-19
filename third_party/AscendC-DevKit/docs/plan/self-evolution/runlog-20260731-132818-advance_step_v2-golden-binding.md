# Run-log 根因分析：advance_step_v2 precision_debug HALT
## `got multiple values for argument 'num_seqs'`

- **Run**: `output/20260731-132818-a5820b/20260731-132818-e507de/`
- **算子**: `advance_step_v2`（cann-bench kernel_bench/level2）
- **失败阶段**: `precision_debug` → `run_tests`（首轮）→ `scope_guard` → **HALT**
- **症状**: 全部 20/20 用例以**同一** `TypeError: advance_step_v2() got multiple values for argument 'num_seqs'` 失败，`elapsed_ms=-1`、`diff=999`（占位）、`output_comparisons` 空——**kernel 从未上板运行**。
- **框架判定（错误）**: scope_guard 判为 `upstream=codegen`，理由 "op-plugin/torch.ops schema mismatch"。

---

## 一、结论先行（TL;DR）

**真根因不在 codegen，也不在 op-plugin schema，而在 DevKit 自身的 ST harness 模板**
`src/ascendc_devkit/adapters/npu/_harness_template.py`：它用**朴素位置传参** `_golden_raw(*tensors, **attrs)` 调用 golden 参考函数，
而 `advance_step_v2` 的 golden 签名是**标量在前、张量在后**（`advance_step_v2(num_seqs, num_queries, block_size, input_tokens, ...)`）。
于是 8 个张量按位置绑定时，`tensors[0]` 落到了形参 `num_seqs` 上，`**attrs` 里的 `num_seqs=314` 再次绑定 `num_seqs` → 重复绑定 → `TypeError`。

- **kernel 侧（op-plugin）无缺陷**：注册的 torch schema 是张量在前、标量在后
  （`advance_step_v2(Tensor input_tokens, ..., int num_seqs, int num_queries, int block_size)`），
  与 proto.yaml `schema:` 行、与 harness 的 `kernel_fn(*tensors, **attrs)` 位置约定完全一致 → **kernel 绑定成功**。
- **报错的是 golden 调用，不是 kernel 调用**。TypeError 里的 `advance_step_v2()` 是 golden 的 `def` 名（Python 函数名），
  被误读成了 torch.ops 的 op 名，导致归因偏到 codegen/op-plugin。

**次生问题**：scope_guard 把一个 harness bug 误判为 `upstream=codegen` 并 HALT。
按 skill 的启发式（SKILL.md 第 37 行「op_plugin / torch.ops schema 不匹配 → upstream=codegen」），
`got multiple values` 被模式匹配成 schema 不匹配，但它其实是 **DevKit 侧 golden 调用约定** 的缺陷，重跑 codegen 永远修不好。

---

## 二、证据链

### 2.1 失败症状（result.json）

`artifacts/debug/advance_step_v2/run_tests_iter-0/result.json`，20 条 case_details 全部：

```json
{
  "case": "AdvanceStepV2_1:16956",
  "diff": 999.0,
  "elapsed_ms": -1.0,
  "error": "TypeError(\"advance_step_v2() got multiple values for argument 'num_seqs'\")",
  "input_shapes": [[16956],[314,54],[16956],[16956],[16956],[314,10000],[314,53],[314]]
}
```

`input_shapes` 是 **8 个张量**（无标量位），对应 8 个 tensor 输入
`[input_tokens, sampled_token_ids, input_positions, seq_lens, slot_mapping, block_tables, spec_token, accepted_num]`。
`elapsed_ms=-1 / diff=999` = harness `except` 兜底占位（`_harness_template.py:500-511`），证明**异常在 kernel 上板之前**抛出。

### 2.2 golden 签名（标量在前）

`bench_lab/kernel_bench/level2/advance_step_v2/golden.py`：

```python
def advance_step_v2(num_seqs: int, num_queries: int, block_size: int,
                    input_tokens: torch.Tensor, sampled_token_ids: torch.Tensor,
                    input_positions: torch.Tensor, seq_lens: torch.Tensor,
                    slot_mapping: torch.Tensor, block_tables: torch.Tensor,
                    spec_token: torch.Tensor, accepted_num: torch.Tensor):
```

前三个形参是标量 `num_seqs / num_queries / block_size`。

### 2.3 用例数据

`cases.yaml`：8 个 int64 输入张量 + `attrs: {num_seqs, num_queries, block_size}`。
harness 生成 8 个张量，`attrs` 作为 kwargs。

### 2.4 op-plugin 注册 schema（张量在前——正确）

`op_plugin/advance_step_v2_plugin.cpp`：

```cpp
m.def("advance_step_v2("
      "Tensor input_tokens, Tensor sampled_token_ids, Tensor input_positions, "
      "Tensor seq_lens, Tensor slot_mapping, Tensor block_tables, "
      "Tensor spec_token, Tensor accepted_num, "
      "int num_seqs, int num_queries, int block_size"
      ") -> (Tensor, Tensor, Tensor, Tensor)");
```

与 `proto.yaml` 的 `schema:` 行逐字一致（proto 把 8 个 `inputs` 张量放前、3 个 `attrs` 标量放后）。
kernel 调用 `kernel_fn(*8tensors, num_seqs=…, num_queries=…, block_size=…)` → 8 张量对 8 张量、3 kwarg 对 3 标量 → **绑定成功**。

### 2.5 harness 的三处 golden 调用点（缺陷所在）

`src/ascendc_devkit/adapters/npu/_harness_template.py`：

| 行 | 调用 | 说明 |
|---|---|---|
| 84  | `_golden_raw(*_inputs, **_attrs)`（`_golden_wrap` 内） | 通用包装 |
| 267 | `_golden_raw(*_torch_inputs, **_attrs)` | **cann-checker 路径——本次触发点** |
| 393 | `golden_fn(*_np_inputs, **_attrs)` | numpy fallback 路径 |

三处都是「张量位置传参 + attrs 关键字传参」，**都隐含假设 golden 把所有张量列在标量之前**。
一旦 golden 标量在前（如本算子），`tensors[0]` 与 `attrs['num_seqs']` 双重绑定第一个形参。

### 2.6 复现（确定性）

```python
import inspect
def golden(num_seqs, num_queries, block_size, input_tokens, sampled_token_ids,
           input_positions, seq_lens, slot_mapping, block_tables, spec_token, accepted_num): ...
def kernel(input_tokens, sampled_token_ids, input_positions, seq_lens, slot_mapping,
           block_tables, spec_token, accepted_num, num_seqs, num_queries, block_size): ...

tensors = ['t%d' % i for i in range(8)]
attrs = {'num_seqs': 314, 'num_queries': 314, 'block_size': 8}

inspect.signature(golden).bind(*tensors, **attrs)   # -> TypeError: multiple values for 'num_seqs'
inspect.signature(kernel).bind(*tensors, **attrs)   # -> OK
```

> golden 绑定失败、kernel 绑定成功。与 run.log 症状完全一致。

### 2.7 权威参照：cann-bench 自己怎么调 golden

`cann-bench/src/kernel_eval/eval/evaluator.py:207` + `utils/param_builder.py:125 build_call_params`：

cann-bench **不做位置传参**。它遍历 golden 的真实签名，按注解把每个形参归类：

- 形参注解含 `Tensor` → 从张量列表按签名顺序取下一个；
- 形参名在 `case_attrs` 里 → 取该 attr 值；
- 否则用默认值。

最终构造 **name-keyed 参数字典**，用 `golden_func(**params)` 调用——**与形参顺序无关**，张量/标量任意交错都正确。

DevKit harness 的位置传参是对这套约定的**退化实现**，仅在「张量全在标量前」时偶然成立。

---

## 三、根因定性（四把尺子 · CLAUDE.md §1.2）

| 维度 | DevKit harness 现状 | 判定 |
|---|---|---|
| 可维护 | 位置传参偷偷假设「张量在前」，未在任何不变式里声明 | ✗ 隐式契约，脆 |
| 可扩展 | 任何「标量在前 / 标量交错」的新 golden 都会同样炸；每个都要单独查 | ✗ 不能自动归位（§1.12） |
| 可诊断 | 报错落在 golden 的 `def` 名，易被误读成 op 名，误导归因到 codegen | ✗ 误导信号 |
| 架构合理 | golden 调用约定属 harness 职责，却让 codegen/op-plugin 背锅 | ✗ 归属错层 |

**归属**：DevKit ST harness（用户域 `_harness_template.py`），**非** A5 codegen、**非** op-plugin、**非** golden（golden 完全合法，标量在前是合法 Python 签名，且 cann-bench 官方评测器能正确调用它，§1.13 golden 是权威）。

---

## 四、修复方案

### 4.1 主修复（正确改动）——harness 按 golden 真实签名 name-keyed 绑定

在 `_harness_template.py` 中新增一个签名感知的 golden 绑定 helper，取代三处 `_golden_raw(*positional, **attrs)`。
harness 运行期已持有 golden 函数对象（`_golden_raw`），可 `inspect.signature` 内省，做法与 cann-bench `build_call_params` 同构：

```python
import inspect as _inspect

def _bind_golden_args(_fn, _tensors, _attrs):
    """Build name-keyed kwargs for the golden fn by its real signature.

    Matches cann-bench evaluator convention: walk the golden signature, map
    Tensor-annotated params to the next positional tensor (in signature order),
    scalar params by name from attrs (or their default). Order-independent —
    tolerates goldens that list scalars before/among tensors
    (e.g. advance_step_v2(num_seqs, num_queries, block_size, input_tokens, ...)).
    """
    _sig = _inspect.signature(_fn)
    _kw = {}
    _ti = 0
    for _name, _p in _sig.parameters.items():
        _ann = str(_p.annotation) if _p.annotation is not _inspect.Parameter.empty else ''
        if 'Tensor' in _ann:
            if _ti < len(_tensors):
                _kw[_name] = _tensors[_ti]
                _ti += 1
            elif _p.default is not _inspect.Parameter.empty:
                _kw[_name] = _p.default
            else:
                _kw[_name] = None
        elif _name in _attrs:
            _kw[_name] = _attrs[_name]
        elif _p.default is not _inspect.Parameter.empty:
            _kw[_name] = _p.default
    return _kw
```

三处调用点改为 name-keyed：

| 行 | 改前 | 改后 |
|---|---|---|
| 84  | `_out = _golden_raw(*_inputs, **_attrs)` | `_out = _golden_raw(**_bind_golden_args(_golden_raw, list(_inputs), _attrs))` |
| 267 | `_g_raw_out = _golden_raw(*_torch_inputs, **_attrs)` | `_g_raw_out = _golden_raw(**_bind_golden_args(_golden_raw, _torch_inputs, _attrs))` |
| 393 | `golden_np_list = golden_fn(*_np_inputs, **_attrs)` | 让 `golden_fn`/`_golden_wrap` 内部走 `_bind_golden_args`（见下） |

> `_golden_wrap`（行 81-85）是 numpy 路径的统一入口。把 `_bind_golden_args` 内嵌进 `_golden_wrap` 后，
> 行 393 的 `golden_fn(*_np_inputs, **_attrs)` 不必改调用点——由 `_golden_wrap` 内部按签名重绑，即可覆盖 numpy fallback 路径。
> 注意 `_golden_wrap` 里已有 `golden_input_type == 'torch'` 的 numpy→torch 转换，需在张量转换**后**再做签名绑定
> （绑定用的是转换后的张量列表）。

**为什么不改 kernel 侧**：kernel 的 op-plugin schema（张量在前）与 proto/harness 位置约定一致、绑定成功，改它会引入真正的 schema 不匹配。缺陷单在 golden 调用路径。

**为什么不改 golden**：golden 标量在前是合法签名，cann-bench 官方评测器能正确调用（§1.13 golden 永远是权威，工程忠实消费，不改写 golden）。

### 4.2 兜底 + 可观测（last resort · §1.2 组合）

`_bind_golden_args` 里对「Tensor 形参耗尽张量却仍有剩余张量」「attrs 有键但签名无对应形参」等异常形态，
不静默吞：在 harness stderr 打一行 diagnostic（形参名/张量数/attrs 键），保留 §1.3 可观测信号，避免退回「难定位的下游黑盒」。

### 4.3 次生修复——scope_guard 误判纠偏（skill 层，独立小改）

`.claude/skills/ascendc-precision-scope-guard/SKILL.md` 第 37 行的启发式把
`got multiple values for argument` 归到 `upstream=codegen`（op_plugin schema 不匹配）。
需要区分两类**形态不同**的绑定错误：

| 错误文本 | 真正归属 | 现状判定 |
|---|---|---|
| `Unknown keyword argument` / `expected at most N but received M` | codegen / op-plugin（kernel 注册 schema 与 attrs 形态不符） | 正确 |
| `got multiple values for argument <X>`（X 同时是张量位与 attr 名） | **DevKit harness golden 调用约定**（本阶段/框架侧） | **应剔出 upstream=codegen** |

建议：在 skill 判据表里把 `got multiple values` 明确排除出「codegen schema 不匹配」类，
标注为「harness golden 位置传参 vs golden 标量在前签名」的框架侧缺陷特征；拿不准时倾向 `pass`（SKILL.md 第 66 行既有原则），
让精度循环用预算兜底，而非误 HALT 到 codegen。

> 该 skill 改动是「减少误判 + 诚实归因」，不改状态机不变式，属 §2.9「本阶段自检」范畴。

### 4.4 回归守护（TDD · §3.1）

- **UT（harness 参数绑定，无 NPU/无 LLM，毫秒级）**：对 `_bind_golden_args`（或提取的等价纯函数）单测——
  用「标量在前」「张量在前」「标量交错」「optional 张量缺省」四类 golden 签名 + attrs，断言绑定结果 name-keyed 正确、不抛 `got multiple values`。
  这是**结构信号驱动**（按注解分类），不点名具体算子（§1.12），advance_step_v2 只作 fixture 样例。
- **ST（真实链路，`@pytest.mark.npu`）**：以一个「标量在前」golden 的算子跑通 harness → golden 绑定成功、进入真实精度对比，
  守护本次断裂点不回归。若须真实 LLM 全流程则按 §3.11 heavy_llm 由用户决策执行。

---

## 五、影响面与验证顺序

- **影响面**：所有 golden 签名「标量在前 / 标量与张量交错」的 cann-bench 算子，在 DevKit ST harness 下都会同样 HALT。
  这不是 advance_step_v2 独有——是 harness 位置传参约定的通用缺陷（§1.12 判据：删掉本算子名不改变缺陷存在性）。
- **验证顺序**：
  1. 先加 4.4 UT（红）；
  2. 落 4.1 主修复（`_bind_golden_args` + 三处调用点）→ UT 转绿；
  3. 4.2 兜底可观测；
  4. 4.3 scope_guard skill 纠偏；
  5. 重跑 advance_step_v2 precision_debug，确认 golden 绑定成功、kernel 上板、进入真实精度对比（`elapsed_ms>0`、`diff` 为真实值）。

---

## 六、实施记录（P135，已落地）

**状态：4.1 / 4.2 / 4.4 已实施并验证；4.3（scope_guard skill 纠偏）暂留为建议。**

### 6.1 已实施

- **新增** `src/ascendc_devkit/adapters/npu/golden_binding.py`：纯函数 `bind_golden_args(fn, tensors, attrs)`，
  stdlib-only（`inspect`）、**函数自身无 typing 注解**（保证 getsource 内联进生成 harness 后可移植，见模块 docstring）。
  按注解归类（`Tensor` → 下一个张量；标量 → 按名取 attr / 默认值），构造 name-keyed kwargs，与 cann-bench
  `build_call_params` 同构。
- **改造** `_harness_template.py`：
  - 生成 harness 的 import 行追加 `inspect`；
  - 注入 `$golden_bind_helper` 占位符（runner.py 用 `inspect.getsource(bind_golden_args)` 填充，单一真源、无漂移）；
  - `_golden_wrap`（覆盖 numpy fallback 路径）与 cann-checker 路径的 `_golden_raw` 调用，改为
    `_golden_raw(**bind_golden_args(_golden_raw, tensors, attrs))`。
  - kernel 调用（`kernel_fn(*..., **_attrs)`）**不动**——op-plugin 张量在前的 schema 与位置约定一致、绑定成功。
- **改造** `runner.py`：import `bind_golden_args` + `inspect`；`_build_test_harness` substitute 注入 `golden_bind_helper`。
- **回归守护**：
  - 新增 `tests/ut/adapters/npu/test_golden_binding.py`（9 用例，纯 UT 无 NPU/LLM）：scalars-first / tensors-first /
    交错 / optional 张量缺省 / optional 标量缺省 / 必填张量耗尽不静默 None / 必填标量缺失不静默 / 多余 attr 丢弃 /
    朴素位置绑定的对照（证明旧路径会 `got multiple values`）。
  - `test_runner_execute.py::TestHarnessExtractionSnapshot::test_golden_call_is_name_keyed_not_positional`：
    源断言 bind_golden_args 已内联 + golden 调用走 name-keyed + 无残留朴素位置调用，独立于 byte-exact snapshot。
  - 刷新快照 fixture `tests/ut/adapters/fixtures/harness_devkit_golden.txt`（模板有意变更，按测试指引更新）。

### 6.2 验证

- `tests/ut/adapters/npu/` + `test_runner_execute.py`：66 passed。
- 全量 UT（`pytest tests/ut --quick`）：**3434 passed, 7 skipped, 1 deselected**（5m40s，无回归）。
- 渲染检查：生成 harness `compile()` 通过；`bind_golden_args` 已内联；两处 golden 调用走 name-keyed；无残留
  `_golden_raw(*..., **_attrs)`。
- **未覆盖**（诚实记录，§3.11）：未在真实 NPU 上重跑 advance_step_v2 precision_debug 全流程（本机 torch_npu/CANN 不可用）。
  golden 绑定正确性已由纯 UT 确定性证明；上板真实精度对比需在具备 NPU+CANN 的环境由用户决策重跑。

### 6.3 4.2 可观测（已并入主修复，非独立分支）

`bind_golden_args` 对「必填张量无对应输入」「必填标量不在 attrs 且无默认值」**不静默填 None**，而是省略该 key →
`fn(**kw)` 抛清晰的 `missing required argument: <name>`（§1.2 可诊断），把 proto↔golden 形参数不一致暴露在
绑定点，而非推到 kernel 运行期。

### 6.4 4.3 暂留为建议（未实施）

主修复已消除触发条件（harness 不再对 golden 产生 `got multiple values`），scope_guard 误判该错误的场景不再发生。
skill 判据表（`ascendc-precision-scope-guard/SKILL.md:37`）把 `got multiple values` 归 `upstream=codegen` 的纠偏，
属「减少未来同类误判」的预防性改进，建议单独立项评审（skill 改动影响 LLM 判定行为，宜与精度调试 skill 维护方对齐）。


---

## 附：关键文件索引

| 角色 | 路径 |
|---|---|
| 缺陷点（主修复） | `src/ascendc_devkit/adapters/npu/_harness_template.py:84,267,393`（+ `_golden_wrap` 81-85） |
| harness 组装 | `src/ascendc_devkit/adapters/npu/runner.py:655-681` |
| golden（权威，合法） | `cann-bench-batch/.../bench_lab/kernel_bench/level2/advance_step_v2/golden.py` |
| op-plugin（正确 schema） | `.../csrc/ops/advance_step_v2/op_plugin/advance_step_v2_plugin.cpp` |
| proto schema | `.../bench_lab/kernel_bench/level2/advance_step_v2/proto.yaml`（`schema:` 行） |
| 权威参照（正确约定） | `cann-bench/src/kernel_eval/eval/evaluator.py:207` + `utils/param_builder.py:125` |
| 次生误判 | `.claude/skills/ascendc-precision-scope-guard/SKILL.md:37` |
| 失败证据 | `artifacts/debug/advance_step_v2/run_tests_iter-0/result.json` |
