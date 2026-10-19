# compare_tensors fallback 三连缺陷 — L1 问题记录 + L3 方案分析

> 批次 `20260731-132818-a5820b`，算子 `multi_add_rms_norm_dynamic_quant`（execution_id `13fa48`）。
> 源起：用户问 run.log 最后错误（eval 507035 vector core exception）根因；深挖后同事指出
> `from kernel_eval.utils.compare import compare_tensors` 加载失败的隐藏问题，进而坐实**三个串联缺陷**。
> 纪律（§1.8）：L1 只记事实/证据/产权，不提方案不排序；L3 记选项取舍。本章 L1/L3 分节，产权不混。

---

## L1 — 问题记录（事实 + 证据 + 产权）

### F1  `kernel_eval` import 失败 —— cann-bench src 路径启发式失配

- **哪里坏了**：precision_debug 的 run_tests harness 启动时，注入的 cann-bench `compare_tensors`
  import 必失败：`ModuleNotFoundError: No module named 'kernel_eval'`。
- **证据**：
  - `run_tests_iter-0/run.log:7`、`run_tests_iter-1/run.log:7`、`printf_location_iter-5/run.log:7` 三处：
    `UserWarning: CannbenchComparer: cann-bench compare_tensors 不可用 (ModuleNotFoundError: No module named 'kernel_eval')，退 devkit 默认路径`。
  - `run_tests_iter-0/harness.py:8`：`golden_source_path = '.../cann-bench-batch/20260731_212804/multi_add_rms_norm_dynamic_quant/bench_lab/kernel_bench/level2/multi_add_rms_norm_dynamic_quant/golden.py'`。
  - 注入逻辑 `src/ascendc_devkit/adapters/npu/precision_comparer.py:119`：
    `if golden_source_path and 'tasks/' in str(golden_source_path):` —— golden 实际在
    `bench_lab/kernel_bench/level2/`，**路径不含 `'tasks/'`**，整个 `if` 被跳过 → cann src 未加
    `sys.path` → import 失败。
  - cann-bench src 实际存在（`cann-bench-batch/.../multi_add_rms_norm_dynamic_quant/src/` 顶层在）。
- **凭什么说是问题**：cann-bench src 在场却 import 不到，纯因定位它的启发式（`'tasks/' in path`）
  与 golden 实际布局（`bench_lab/kernel_bench/`）不匹配。属于 §1.10「用机制特征（路径字面量）
  代理业务语义（cann-bench src 根）」式缺陷。
- **讽刺点**：`precision_comparer.py:12` docstring 明写「**取代** runner 原
  `'tasks/' in golden_source_path` 嗅探」，但 `CannbenchComparer.harness_setup_lines` 在
  `:119` **自己又用了同一个嗅探**——P79 重构时嗅探只是从 runner 挪到 comparer，没真删。
- **产权**：`precision_comparer.py` `CannbenchComparer`（cann-bench src 定位逻辑）。

### F2  降级 warning 不上浮主 run.log —— 可观测性埋深

- **哪里坏了**：`compare_tensors` import 失败 → 降级到 devkit 默认路径（权威对比→降级对比，重大
  语义变化），但该降级**只在 per-iter run.log 留痕，主 run.log 完全没有**。
- **证据**：
  - `src/ascendc_devkit/adapters/npu/runner.py:429-435`：`capture_output=True` 跑 harness 后，
    `(_log_path / "run.log").write_text(f"=== STDERR ===\n{result.stderr}\n")` —— 只 dump 到
    per-iter run.log，不转发主 log。
  - 主 `run.log` grep `compare_tensors|不可用|UserWarning|退 devkit|kernel_eval` 仅 3 匹配，全是
    别的（`cann_bench_utils 不可达`=warmup `_C`、`kernel_eval exited 5`=eval 崩溃、stage skipped），
    **无一条是 fallback 降级 warning**。
- **凭什么说是问题**：§1.2 可诊断——降级是对比口径的根本变化，本应在顶层显眼报警。现状符合
  「不静默吞」（warning 留在 per-iter log），但对看主 run.log 的观察者事实上不可见，导致本次
  最初诊断漏掉它（一度误判为 golden 上游缺陷）。
- **产权**：`runner.py` harness 执行段（subprocess stderr 处理 + 主 log 上浮）。

### F3  fallback numpy 路径无 TensorList 感知 —— 兜底自身崩

- **哪里坏了**：降级到 devkit numpy 路径后，对 **TensorList 输入**（如本算子 `x1` shape
  `[[1,72,7168]]`，list-of-tensor）构造出嵌套 Python list 喂给 golden，golden 侧
  `torch.from_numpy(list)` 拒绝 → `TypeError('expected np.ndarray (got list)')`。
- **证据**：
  - `report.json:80`（printf_location agent analysis，本次 LLM 诊断精确）：
    `cann_checker_used=False → harness falls into FALLBACK numpy path. For TensorList input x1
    (shape [[1,72,7168]]), fallback builds _np_inputs[0] = [ndarray] (Python list). golden_fn =
    _golden_wrap calls torch.from_numpy(a) where a is the Python list → TypeError. Error fires
    AFTER kernel_fn(*_npu_inputs) and npu.synchronize() succeeded — kernel executes clean.`
  - `_harness_template.py:83-85` `_golden_wrap`：
    `_inputs = [torch.from_numpy(a) for a in _inputs]` —— 对每个位置参数无脑 `from_numpy`，
    遇 TensorList（a 是 list）必炸。
  - 对照权威路径 `_harness_template.py:426` `_npu_inputs = [[x.npu() for x in t] if isinstance(t, list)
    else t.npu() for t in _torch_inputs]` —— 权威路径**有** TensorList 感知；`:379`
    `_torch_in.append([torch.from_numpy(t) for t in a])` 亦有同款正确写法。fallback 路径唯独漏了。
- **凭什么说是问题**：fallback 设计意图是「import 失败时仍能兜底对比」，但对 TensorList 输入
  兜不住——等于 fallback 只覆盖单 tensor 输入，TensorList 算子一触即崩。兜底不兜底。
- **产权**：`_harness_template.py` `_golden_wrap`（fallback numpy→torch 转换）。

### 连带事实（推翻前期误判，必须记录）

- **golden 没坏**：前三轮据 scope_guard/diagnose 的 LLM 判定，误将 11 个单输入 case 的
  `TypeError` 归为「golden `get_input` 返回 list 的上游缺陷」。F3 坐实：是 harness fallback
  把 list 喂到 golden 门口，golden 的 `torch.from_numpy` 正确拒绝了 list。golden 产权方无责。
- **9 个 multi-input runtime crash（507057）仍是独立的 codegen 真实缺陷**（kernel 多输入路径
  Pass1/Pass2 缺同步），不受 F1/F2/F3 影响——但只有先修 F1/F2/F3，precision_debug 才能正确路由
  到 comment_bisect 去修它。
- **本三缺陷是 precision_debug 跑偏链的最上游扳机**：F1 触发降级 → F3 让降级崩成 TypeError →
  被 LLM 误判 golden 上游 → scope_guard 把 11 case 标 precision → 挤掉 9 个 runtime case 的
  调试预算 → converge 全崩 commit → eval 507035。修 F1 即可让权威路径接管，F2/F3 不触发；但
  F2/F3 仍须修（import 再次失败时 fallback 要能兜住 + 顶层可见）。

---

## L3 — 方案分析（选项 + 选型 + 理由）

### F1 修法

- **选项 A（选）**：向上遍历 `golden_source_path` 的父目录，找含
  `src/kernel_eval/utils/compare.py` 的祖先目录，将其 `src` 加 `sys.path`。
  - 理由：`src/kernel_eval/utils/compare.py` 是 cann-bench 仓库的**稳定结构锚点**（与 golden
    放 `tasks/` 还是 `bench_lab/kernel_bench/` 无关）。不依赖任何路径字面量，鲁棒。
  - 副作用：向上遍历最多到 golden 所在仓根，O(深度) 可忽略；找不到则维持原降级（软失败不变）。
- **选项 B（弃）**：backend 选择层（`CannbenchBackend`）显式传入 cann root。
  - 弃理由：`cases_source`/`golden_contract` 已在 `EvalRequest`，但 cann root 仍未显式化；要
    传就得改 `EvalRequest` schema + backend 构造 + comparer 协议签名，改动面远大于 A，且
    harness 内仍需落地——不如让离 src 最近的 harness 自己定位。
- **选项 C（弃）**：保留 `'tasks/'` 嗅探 + 补 `'bench_lab/'` 嗅探。
  - 弃理由：每出现一个 golden 布局就打一条补丁，§1.2 可扩展性失败（同类新布局仍会失配）。

### F2 修法

- **选项 A（选）**：`runner.py` dump stderr 后，scan 降级 signature（`compare_tensors 不可用`
  / `退 devkit 默认路径`），命中则 `Logger.warn(...)` 上浮主 run.log。
  - 理由：`Logger.warn`（`infra/logger.py:104`）经 `current_run_log_file` 落主 run.log 的
    `[WARN]` 行（workspace.py/repo_guard.py 同款用法）。runner 是 subprocess stderr 的唯一
    汇聚点，由它上浮职责正确、改动最小。
- **选项 B（弃）**：harness 内把 `_cann_checker_used` 写进 stdout JSON，comparer.aggregate 据此
  记 WARN。
  - 弃理由：要改 harness 输出契约 + comparer 协议；且 aggregate 只在 golden_used 时调用，
    覆盖面不如 runner stderr 扫描全（smoke 的 no-golden 探测也走 runner）。

### F3 修法

- **选项 A（选）**：`_golden_wrap` 的 `from_numpy` 列表推导加 `isinstance(a, list)` 分支，
  TensorList → `[torch.from_numpy(t) for t in a]`（对齐 `:379`/`:426` 既有正确写法）。
  - 理由：`bind_golden_args`（`:91`）已能按 golden 签名处理 tensor-list（权威路径 `:273-286`
    这么用），fallback 只需把 TensorList 转成 list-of-tensor 即可对齐。改一行，最小正确。
- **选项 B（弃）**：在 `_np_inputs` 构造处把 TensorList 展平成单 ndarray。
  - 弃理由：TensorList 语义是「list-of-tensor」，golden 签名按 List[Tensor] 接收；展平成单
    ndarray 会破坏 golden 的参数形态，引入新错。

### 共同边界（不修的部分）

- 不改 golden（§1.13：golden 是权威，错也归产权方；本例 golden 本就没错）。
- 不改 codegen 的多输入同步缺陷（独立真实缺陷，由 precision_debug 修对路由后经
  comment_bisect 处理，不属本三缺陷范围）。
- 不改 scope_guard 的「主导归类」逻辑（它是 F1/F3 的连带受害者；F1/F3 修后 11 个 case 不再
  被污染，scope_guard 自然不跑偏。若仍想加固 per-case 上游识别，另开 issue）。
