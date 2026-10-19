# compare_tensors fallback 三连缺陷 — L4 实施方案

> 配套 `86-batch-20260731-132818-compare-tensors-fallback.md`（L1 事实 + L3 选型）。本文件记
> 具体改哪段代码、什么顺序、怎么验证（§1.8 L4 产权）。

## 改动清单（按依赖顺序）

### 改动 1（F1）— `precision_comparer.py` `CannbenchComparer.harness_setup_lines`

**文件**：`src/ascendc_devkit/adapters/npu/precision_comparer.py:115-131`

**现状**：`if golden_source_path and 'tasks/' in str(golden_source_path):` 用 `'tasks/'` 字面量
反推 cann root，golden 在 `bench_lab/kernel_bench/` 时失配。

**改为**：向上遍历 `golden_source_path` 父目录，找含 `src/kernel_eval/utils/compare.py` 的祖先，
将其 `<root>/src` 加 `sys.path`。注入的 harness 代码片段（Python，跑在 subprocess）：

```python
# 定位 cann-bench src（package=false 不可 pip 装；以 src/kernel_eval/utils/compare.py
# 为稳定结构锚点向上找仓根，不依赖 golden 在 tasks/ 还是 bench_lab/ 下）：
_cann_src = None
_p = os.path.dirname(os.path.abspath(str(golden_source_path)))
for _ in range(8):  # 至多向上 8 层，覆盖 golden 嵌套深度
    _cand = os.path.join(_p, 'src')
    if os.path.isfile(os.path.join(_cand, 'kernel_eval', 'utils', 'compare.py')):
        _cann_src = _cand
        break
    _np = os.path.dirname(_p)
    if _np == _p:
        break
    _p = _np
if _cann_src and _cann_src not in sys.path:
    sys.path.insert(0, _cann_src)
try:
    from kernel_eval.utils.compare import compare_tensors as _compare_tensors
    _cann_checker_used = True
except ImportError as _cann_imp_err:
    import warnings
    warnings.warn('CannbenchComparer: cann-bench compare_tensors 不可用 (%r)，退 devkit 默认路径' % (_cann_imp_err,))
```

同步更新该方法的注释 + 类 docstring（`:100-104`）：删掉「用 `tasks/` 启发」表述，改为
「以 `src/kernel_eval/utils/compare.py` 结构锚点定位」；落实 `:12` docstring 早先宣称的
「取代路径嗅探」。

### 改动 2（F3）— `_harness_template.py` `_golden_wrap`

**文件**：`src/ascendc_devkit/adapters/npu/_harness_template.py:85`

**现状**：`_inputs = [torch.from_numpy(a) for a in _inputs]` —— TensorList（a 是 list）必炸。

**改为**（对齐 `:379`/`:426` 既有 TensorList 写法）：

```python
_inputs = [
    [torch.from_numpy(t) for t in a] if isinstance(a, list) else torch.from_numpy(a)
    for a in _inputs
]
```

`:91` `bind_golden_args(_golden_raw, list(_inputs), _attrs)` 已能按 golden 签名处理
tensor-list（权威路径 `:273-286` 同款），故仅需让 `_inputs` 里 TensorList 转成 list-of-tensor。

### 改动 3（F2）— `runner.py` 降级 warning 上浮

**文件**：`src/ascendc_devkit/adapters/npu/runner.py:429-435`（dump stderr 段之后）

**现状**：stderr 只 dump 到 per-iter run.log，不转发主 log。

**改为**：dump 后 scan stderr 的降级 signature，命中则 `Logger.warn` 上浮主 run.log：

```python
# §1.2 可诊断：权威对比→降级对比是重大语义变化，须在主 run.log 可见
# （harness 的 warnings.warn 只进 per-iter run.log，顶层观察者不可见）。
_stderr = result.stderr or ''
if 'compare_tensors 不可用' in _stderr or '退 devkit 默认路径' in _stderr:
    from ascendc_devkit.infra.logger import Logger
    Logger.warn(
        'precision 对比降级：cann-bench compare_tensors 不可用，harness 退 devkit '
        '默认路径（详见 per-iter run.log 的 STDERR）。case 正确性判定口径已变。'
    )
```

`Logger.warn`（`infra/logger.py:104`）经 `current_run_log_file` 落主 run.log `[WARN]` 行。

## 验证

### UT（§3.1/§3.8，纯逻辑，前台）

1. **F1 路径定位**：构造临时目录树（含 `src/kernel_eval/utils/compare.py` + golden 在
   `bench_lab/kernel_bench/level2/<op>/golden.py` 与 `tasks/level2/<op>/golden.py` 两种布局），
   断言两种布局都能定位到 cann src；缺锚点时返回 None（软失败不变）。
   - 注：定位逻辑注入 harness 是字符串片段，UT 直接 exec 该片段或提取为可测纯函数。
2. **F3 TensorList 转换**：断言 `_golden_wrap` 对 `[ndarray, ndarray]`（TensorList）产出
   `[tensor, tensor]`，对单 `ndarray` 产出单 `tensor`，且不抛 `TypeError`。

### ST（§3.2/§3.9，真实链路）

用 `multi_add_rms_norm_dynamic_quant`（本批次算子，TensorList 输入 x1）重跑 precision_debug：
- 断言主 run.log **不再出现** `compare_tensors 不可用 / 退 devkit 默认路径`（F1 修后走权威路径）；
- 断言 11 个单输入 case 不再报 `TypeError('expected np.ndarray (got list)')`（F3 修后 TensorList
  正确）；若 cann-bench 环境仍有别的问题致 import 失败，则断言主 run.log **出现** 降级 `[WARN]`
  （F2 修后上浮）且 fallback 不再因 TensorList 崩。

ST 属真实 NPU + cann-bench 链路，按 §3.6 预检可达性；若需 heavy_llm（端到端 precision_debug
全流程）按 §3.11 由用户确认。

## 不做（边界）

- 不改 golden、不改 codegen 多输入同步缺陷、不改 scope_guard 主导归类（见 L3「共同边界」）。
