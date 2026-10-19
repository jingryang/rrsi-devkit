# 49 — PrecisionComparer 协议化：rule × backend 正交（L4 实施方案）

> 工作线：self-evolution
> 状态：**✅ 已实施（v1，2026-07-15）**
> 关联 L3：`49-precision-comparer-protocol-analysis.md`
> L1 问题：`06-problems.md` P79
> 决策：A-1 + B-1（rule × backend 正交），实现 L1+L2，预留 L3+L4 接口形状。

## 落地形态（v1 实际实现）

### 协议签名（实际，比原设计更简）

```python
# domain/precision.py — 纯数据，无 torch/无 adapter import（§1.1 domain 零依赖）
@dataclass(frozen=True)
class CompareRule:
    dtype_thresholds: dict[str, float]   # proto 真值经 merge_thresholds 合并默认表

# adapters/npu/precision_comparer.py — subprocess-harness 策略（backend 侧）
class PrecisionComparer(Protocol):
    def harness_setup_lines(self, rule: CompareRule) -> list[str]: ...  # 注入 harness 顶部 import 行
    def aggregate(self, rule: CompareRule, case_details: list[dict]) -> bool: ...  # 主进程聚合

def judge_case_details(rule, case_details) -> bool: ...  # 共享聚合（原 runner._all_outputs_within_threshold 提取）
class DevkitComparer: ...   # 默认：harness_setup_lines=[]（abs-diff 用 harness 内 numpy），aggregate=judge
class CannbenchComparer: ...  # 可选注入：harness_setup_lines 注入 kernel_eval import（软降级 warn），aggregate=judge
```

**对原 L4 设计的简化**：
- 协议用 `harness_setup_lines(rule) -> list[str]`（注入 harness **顶部 import 行**）+ `aggregate(...) -> bool`，**不引入** `HarnessComparePlan` 结构 / `PrecisionOutcome` dataclass。理由：harness 内的比较调用块（cann-bench `compare_tensors` 路径 vs devkit abs-diff 路径）差异大、且已稳定，不值得抽象成统一 plan；只需把**会因 backend 不同的顶部 import 行**外提（kernel_eval import + 软降级），比较调用块留在 runner harness（§2.7 不为假想统一抽象）。
- `aggregate` 返 `bool`（与旧 `_all_outputs_within_threshold` 签名一致），逐输出明细已在 `case_details` 里（runner 不再需要 `PrecisionOutcome` 包装）。

### 装配点 = `run_precision_cases`（L3，非 debug_service）

**关键分层决策（实际落地）**：rule 构建 + comparer 选择都在 **L3 `run_precision_cases`**（`orchestration/stages/precision_debug.py`），**不在 L2 `debug_service`**：

```python
# orchestration/stages/precision_debug.py
def run_precision_cases(op_spec, test_cases, npu_id, golden_contract,
                        deploy_result, callable_target, chip_version="A2",
                        use_cannbench_checker: bool = False, log_dir=None, card_pool=None):
    runner = NPURunner(chip_version=chip_version)
    from ascendc_devkit.adapters.npu.precision_compare import merge_thresholds  # 懒导入（torch-free 模块）
    rule = CompareRule(dtype_thresholds=merge_thresholds(op_spec.precision_thresholds))
    comparer = CannbenchComparer() if use_cannbench_checker else DevkitComparer()
    return runner.execute(..., rule=rule, comparer=comparer, log_dir=log_dir)
```

- **L2 `debug_service.run_cases`** 只算 `use_cannbench_checker = bool(task_test_cases)` 传下去——**不 import L6**（§1.1 L2→L3→L6，L3 独占 NPURunner/adapter）。
- **backend 显式选择** = `use_cannbench_checker` flag（task 加载成功 → cann-bench `compare_tensors` 权威路径），**取代** runner 原 `'tasks/' in golden_source_path` 嗅探（同一事实的冗余再推导）。
- **dim A 桥接** = `merge_thresholds(op_spec.precision_thresholds)`：`op_spec.precision_thresholds`（proto 真值，原悬空字段）→ `CompareRule.dtype_thresholds` 真实消费点。

### runner 适配（`adapters/npu/runner.py`）

- `execute(...)` / `_build_test_harness(...)`：删 `dtype_thresholds: dict | None` 参，改收 `rule: CompareRule | None = None, comparer: PrecisionComparer | None = None`（None → 默认表 + DevkitComparer）。
- harness 顶部 import 块：`*comparer.harness_setup_lines(rule)`（DevkitComparer→空；CannbenchComparer→kernel_eval import + 软降级 warn + 'tasks/' 定位启发）。**删** 原 try import + `'tasks/' in path` 嗅探块。
- harness 烘焙：`DTYPE_THRESHOLDS = {_dts}`（`_dts = rule.dtype_thresholds`，proto 合并真值）；cann-bench 路径 `_custom_th = DTYPE_THRESHOLDS`（**删** 硬编 `{'int8':1.0,...}` int-only 表 → proto 真值对所有 dtype 生效）。
- 成功/错误/超时结果 dict 回显 `"dtype_thresholds": rule.dtype_thresholds`。
- 成功路径 `passed = comparer.aggregate(rule, case_details)`（删 `_all_outputs_within_threshold` + `_DTYPE_THRESHOLDS_FALLBACK`）。

### try_load_cannbench_task（L3）3→2 元组

阈值不再从此出（proto 单一来源）。`try_load_cannbench_task(state, op_name) -> (test_cases, golden_contract)`。删 `_fallback_thresholds()`（依赖已删的 `_DTYPE_THRESHOLDS_FALLBACK`）。

### 三表合一（§2.5 单通路，全部删除）

| 删除项 | 原位置 | 理由 |
|---|---|---|
| `runner._DTYPE_THRESHOLDS_FALLBACK` | runner.py（模块级） | 三表合一，规范表 = `precision_compare.DEFAULT_THRESHOLDS` |
| `runner._all_outputs_within_threshold` | runner.py | 提取为 `precision_comparer.judge_case_details`（共享聚合） |
| `task_loader.DEFAULT_DTYPE_THRESHOLDS` | task_loader.py | 同上，单一规范表 |
| `task_loader._derive_thresholds`（读错字段 `proto.get("thresholds")`） | task_loader.py | 字段名错；阈值来源改 op_spec 桥接 |
| `CannbenchTask.thresholds` / `TaskCase.thresholds` | task_loader.py | 无消费点（dead field） |
| `precision_debug._fallback_thresholds` | precision_debug.py | 依赖已删表 |
| runner `_custom_th` 硬编 int-only 表 | runner.py harness | dim A：改读 proto 真值 `DTYPE_THRESHOLDS` |
| runner try import + `'tasks/' in path` 嗅探 | runner.py harness | dim B：backend 显式选择 |

→ 规范默认表唯一源 = `precision_compare.DEFAULT_THRESHOLDS`（cann-bench thresholds.py 对齐）；per-op 容差由 proto `precision_thresholds` 经 `merge_thresholds` 覆盖。

## 关键架构约束（实施依据）

**精度比较在 subprocess harness 内执行，不在主进程。** runner 生成一段 Python 串作为子进程 harness：子进程 import `kernel_eval.utils.compare`、调 `compare_tensors`、把每个输出的 `diff`/`passed` 写进 `case_details` JSON 回传。主进程 `comparer.aggregate` 只对回传的 `case_details` 做**聚合判 pass/fail**——不接触张量。

→ `PrecisionComparer` 协议是**策略对象**（主进程负责 harness setup 注入 + 结果聚合），**不是**主进程 `compare(rule, output, golden)` 可调用对象（张量在子进程，主进程拿不到）。

**PYTHONPATH 决策（已 spike 验证，2026-07-15）**：devkit **editable 安装**（`.pth` 注入 `<repo>/src`），子进程（任意 cwd、仅继承 `os.environ` + 部署 `py_path`）即可 import `precision_compare`。v1 DevkitComparer 的 abs-diff 路径用 harness 内 numpy（不 import precision_compare），故 `harness_setup_lines=[]`；P79.1 升级为 precision_compare MERE/MARE 时再用 import 路径（已验证可行）。

## 验证（TDD — 已落地）

**UT（纯逻辑/编排，§3.8）—— 全绿：**
- `tests/ut/domain/test_precision.py`（4）：CompareRule 构造/frozen/proto-merge 真值。
- `tests/ut/adapters/test_precision_compare.py::TestMergeThresholds`（4）：默认表 ⊕ proto 覆盖 → CompareRule.dtype_thresholds 唯一入口。
- `tests/ut/adapters/test_precision_comparer.py`（16）：judge_case_details 逐输出判 / DevkitComparer 零 cann-bench import / CannbenchComparer kernel_eval 注入 + 软降级 warn / rule 贯穿（DQ int8=1.0 不冤杀、int8=0 冤杀复现）。
- `tests/ut/adapters/test_runner_execute.py`（7，已适配新签名）：execute 暴露 `rule`+`comparer`+`precision_threshold`；DQ proto 经 rule 贯穿到 `result["dtype_thresholds"]["int8"]==1.0`。
- `tests/ut/orchestration/test_precision_debug_assembly.py`（5，新增）：**dim A 桥接 + backend 选择的 L3 装配守护**——proto `{int8:1.0}` → rule.dtype_thresholds；`use_cannbench_checker` → CannbenchComparer/DevkitComparer；proto None → 默认表（int8=0 非 1.0）；try_load_cannbench_task 2 元组。
- `tests/ut/cli/test_debug_cli.py`（5）：debug_service → run_precision_cases 接线（mock run_precision_cases）。

**parity（§3.4/§3.9）**：`test_precision_compare.py::TestParityCannBench`（DevkitComparer 语义对拍 cann-bench 原版）仍在场（cann-bench 不可用时 skip，§3.7）。

**全量 UT（§3.6 默认范围）**：`2041 passed, 7 skipped, 17 failed`。**17 fail 全部是 pre-existing**（经 pristine HEAD 交叉验证：stash P79 改动后 clean main 同样 17 fail）——15 环境 fail（NPURunner `_soc_version`/detect 探机 + CANN exit 78）+ 2 非 env drift（slash-prompt / agent Write-tool 断言）。**P79 零回归**（见 memory `ut-preexisting-env-failures`）。

**ST（真实链路，§3.9/§3.11）—— 待环境**：`@pytest.mark.npu` DQ 真机 int8 ±1 端到端（proto `{int8:1.0}` 经 rule 贯穿 → 不冤杀，P78/P79 回归守护核心）属 heavy_llm，本环境无 NPU 未跑（§3.7 诚实记录）；**交付/合并前由用户决策跑一次**。

## 范围边界（YAGNI §2.7）

**P79 v1 已做**：dim A 桥接（proto→rule，`run_precision_cases` 装配）+ dim B 协议化（DevkitComparer 默认 / CannbenchComparer 显式注入）+ 三表合一 + 删路径嗅探/`_custom_th` 硬编 + rule 贯穿。

**P79 v1 不做（仅留接口形状）**：
- **P79.1（预留）**：FALLBACK abs-diff 路径升级为 `precision_compare` MERE/MARE（与 cann-bench 浮点语义对齐）——待 ST 真机验证后做；v1 abs-diff 用 harness 内 numpy（行为同旧 FALLBACK）。
- 双标杆/区间 rule、CommandBackend（命令注入）、远程后端——协议签名（rule 用对象、comparer 是 Protocol）不堵死，**不写实现**。

## cann-bench 语义行号对照（parity 参考，非代码来源）

| 语义 | cann-bench | devkit 复刻 |
|---|---|---|
| 阈值合并（默认 ⊕ proto） | evaluator.py `_get_merged_thresholds` | `merge_thresholds`（run_precision_cases 桥接） |
| 逐输出按 dtype 查阈值 | compare.py | `precision_compare.threshold_for_dtype` / harness `threshold_for` |
| 整数精确 + abs-diff | compare.py 整数分支 | `precision_compare._compare_single` 整数分支（parity 已守） |
| 浮点 MERE/MARE + 二阶段 | compare.py 浮点分支 | `precision_compare._compare_single` 浮点分支（parity 已守；P79.1 接入 FALLBACK 路径） |
