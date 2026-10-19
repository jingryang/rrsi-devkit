# 测试执行外部化 — 实施方案（L4）

> **性质**：test-execution-decoupling 线 L4 符号级实施方案。承接 L3 `02-analysis.md`（v3 冻结：服务型抽象 + 双向 adapter）。
> **状态**：方案完整（4 待确认已转决策，L3 §9）。**假设 P0（`self-evolution/51-*.md`）已实现**——本 L4 标注所有 P0 接口依赖点。
> **纪律**：遵守 `plan-doc-discipline`（语义锚点用函数/模块名、不照搬外部脚本、外部依赖只读）。

---

## 0. 前置依赖（P0 接口契约）

本 L4 假设 P0 已落地，依赖 P0 的以下产物（P0 L4 `51` §4/§5/§6）：

- **`RunTestsSubstage`**（P0 §4.1）：precision_debug CompositeGroup 的判定子 stage。其 `actions()` 派发 `ascendc-precision-run-tests` agent，`transition()` 读 checkpoint.json 写 `state._debug_checkpoint`。
- **`run_precision_cases()`**（P0 §3 保留）：判定执行函数。**本 L4 的核心改造点**——P0 让 run_tests 子 stage 调用它，本 L4 把其内部从"内化 runner"换为"`select_backend().run()`"。
- **`state._debug_checkpoint`**（P0 §6）：路由字段，本 L4 不改（backend.run 返回的 TestReport 经 run_tests 子 stage transition 提取，机制沿用 P0）。

> **接口契合点（L3 §11.2）**：P0 的 run_tests 子 stage 调判定函数。本 L4 让该调用走 `run_precision_cases()` → 内部 `select_backend().run()`。run_tests 子 stage 本身不改（透明替换）。**反查 P0 L4**：确认 P0 的 run_tests 子 stage transition 从 TestReport 提取的字段 ≥ 现有 checkpoint 提取（否则 P0 L4 §4.1 transition 要补）。

---

## 1. 改动总览

```
新增:
  src/ascendc_devkit/domain/evaluation.py              # 中立格式: EvalRequest/TestReport/CaseReport/RunMode
  src/ascendc_devkit/adapters/evaluation/__init__.py   # EvaluationBackend 协议 + select_backend
  src/ascendc_devkit/adapters/evaluation/devkit.py     # DevkitBackend (迁 runner.execute + DevkitComparer)
  src/ascendc_devkit/adapters/evaluation/cannbench.py  # CannbenchBackend (模块形态: DataGenerator+compare_tensors)
  tests/ut/adapters/evaluation/test_devkit_backend.py
  tests/ut/adapters/evaluation/test_cannbench_backend.py
  tests/ut/adapters/evaluation/test_select_backend.py

修改:
  src/ascendc_devkit/orchestration/stages/precision_debug.py
    # run_precision_cases() 内部改调 select_backend().run()
    # 删 try_load_cannbench_task() (目录嗅探外部化)
    # DEBUG_RESULT_CONTRACT 保留
  src/ascendc_devkit/orchestration/kernel/state.py
    # 新增 cases_source: str | None = None (上游 test_design 标记, 驱动 backend 选择)
  src/ascendc_devkit/orchestration/stages/test_design_substages.py
    # _load_external_cases 命中 cann_bench_cases_loader → state.cases_source="cannbench"
    # LLM 生成 cases → "devkit"; 不改 behavior, 只标 source

删除:
  src/ascendc_devkit/adapters/npu/task_loader.py       # 目录嗅探 + cases 格式解析 (CannbenchBackend 内化)
    # 注: task_loader 的 TaskCase/CannbenchTask dataclass 迁入 cannbench.py adapter

不变:
  src/ascendc_devkit/orchestration/stages/cannbench_eval.py  # ② 权威评测保持调 CLI (L3 §9 决策3)
  src/ascendc_devkit/adapters/npu/precision_comparer.py      # P79 协议 + DevkitComparer/CannbenchComparer (backend 内部复用)
  src/ascendc_devkit/adapters/npu/runner.py                  # NPURunner (DevkitBackend 内部复用, 不删)
  src/ascendc_devkit/adapters/npu/precision_compare.py       # merge_thresholds等 (复用)
```

---

## 2. domain 中立格式（`domain/evaluation.py`）

```python
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class RunMode(Enum):
    SINGLE_CASE = "single_case"   # ① 本地预检: 快速单 case 迭代
    BATCH = "batch"               # ② 全集评测 (预留; ② 现走 CannbenchEvalStage)


@dataclass(frozen=True)
class OpRef:
    """算子定位 (backend 跑 kernel 需要)."""
    callable_target: dict          # {kind, symbol} (来自 codegen_manifest)
    op_dir: str                    # 算子源码目录 (= agent cwd)
    chip: str                      # design_target_chip (A2/A3/A5)


@dataclass(frozen=True)
class EvalRequest:
    """标准评测请求 (中立格式, 各 backend adapter 转译到原生)."""
    op: OpRef
    cases: list                     # list[domain.requirement.TestCase]
    rule: "CompareRule"             # proto 真值精度规格 (domain.precision)
    deploy_result: "DeployResult"   # 部署产物路径 (domain.verification)
    golden_contract: dict | None    # {path, entry, input_type}
    mode: RunMode
    case_filter: list[str] | None = None   # 单 case 指定 case_id
    cases_source: str | None = None        # "cannbench" | "devkit" | None (上游 test_design 标记, 驱动 backend 选择)
    npu_id: int | None = None
    card_pool: object | None = None


@dataclass(frozen=True)
class CaseReport:
    """per-case 标准结果."""
    case_id: str
    name: str
    status: str                     # pass | fail | skip | cascade
    max_diff: float = 0.0
    mere: float = 0.0
    mare: float = 0.0
    mismatch_count: int = 0
    threshold: float = 0.0
    elapsed_us: float | None = None # 性能 (可选)
    error_msg: str = ""


@dataclass(frozen=True)
class TestReport:
    """聚合标准结果. 三维分 Optional (cann-bench 有/Devkit 无)."""
    cases: list[CaseReport] = field(default_factory=list)
    total: int = 0
    passed: int = 0
    failed: int = 0
    pass_rate: float = 0.0
    overall_score: float | None = None      # Optional: 三维加权
    compile_score: float | None = None
    function_score: float | None = None
    performance_score: float | None = None
    extra: dict = field(default_factory=dict)  # backend 特有透传 (框架不解释)

    def case_by_id(self, case_id: str) -> CaseReport | None:
        return next((c for c in self.cases if c.case_id == case_id), None)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0 and self.total > 0
```

---

## 3. EvaluationBackend 协议 + 选择器（`adapters/evaluation/__init__.py`）

```python
from __future__ import annotations
from typing import Protocol
from ascendc_devkit.domain.evaluation import EvalRequest, TestReport


class EvaluationBackend(Protocol):
    """评测后端: 接收标准请求 → 执行测试 → 返回标准化 TestReport.

    实现保证内部自成体 (数据生成/比较/阈值同源), 框架不混搭.
    """
    name: str

    def run(self, request: EvalRequest) -> TestReport: ...

    def available(self, request: EvalRequest) -> bool:
        """该 backend 是否适用此算子 (选择器按优先级探)."""
        ...


def select_backend(request: EvalRequest,
                   registry: list[EvaluationBackend] | None = None) -> EvaluationBackend:
    """按优先级选第一个 available 的 backend.

    默认注册顺序: CannbenchBackend (标准对齐优先, cann-bench task 存在时)
                  > DevkitBackend (通用兜底).
    未来 ATK/TTK 按算子仓 profile 或显式注入插入序列.
    """
    if registry is None:
        registry = _default_registry()
    for backend in registry:
        if backend.available(request):
            return backend
    # DevkitBackend 永远 available (通用兜底), 不会走到这
    raise RuntimeError("no available evaluation backend")


def _default_registry() -> list[EvaluationBackend]:
    # 延迟导入避免循环 + torch 在 backend 内部才 import
    from ascendc_devkit.adapters.evaluation.cannbench import CannbenchBackend
    from ascendc_devkit.adapters.evaluation.devkit import DevkitBackend
    return [CannbenchBackend(), DevkitBackend()]
```

---

## 4. DevkitBackend（`adapters/evaluation/devkit.py`）

**职责**：通用默认，任何算子仓可用，零外部负担。迁现有 `runner.execute` + `DevkitComparer` + 自建数据生成进来。

```python
class DevkitBackend:
    name = "devkit"

    def available(self, request: EvalRequest) -> bool:
        return True   # 通用兜底, 永远可用

    def run(self, request: EvalRequest) -> TestReport:
        # 复用现有 NPURunner.execute 的 harness 构造 + DevkitComparer 比较逻辑
        # (从 adapters/npu/runner.py 迁移; NPURunner 保留作底层 NPU 执行器)
        # 数据生成: 自建确定性 seed (torch.rand) — 不依赖 cann-bench DataGenerator
        # 比较: DevkitComparer (P79 自实现 MERE/MARE, precision_compare.py)
        # 结果: NPURunner.execute 返回的 dict → 转 CaseReport/TestReport
        ...
        return _to_test_report(raw_result)
```

**迁移要点**：
- `NPURunner.execute`（`adapters/npu/runner.py`）保留作底层 NPU 执行器，DevkitBackend 调用它
- 现有 runner 的 harness 构造逻辑（数据生成 + kernel/golden 跑 + 比较）拆为 DevkitBackend 的 `run()` 主体
- `_to_test_report(raw)` 把 NPURunner 返回的 dict（per-case diff/max_diff）转 `CaseReport`/`TestReport`；三维分留 None（Devkit 产不出）

---

## 5. CannbenchBackend（`adapters/evaluation/cannbench.py`，模块形态）

**职责**：cann-bench 标准对齐。模块形态（L3 §9 决策2）——自建 harness + cann-bench DataGenerator/compare_tensors，无 CLI 冷启动。

```python
class CannbenchBackend:
    name = "cannbench"

    def available(self, request: EvalRequest) -> bool:
        """cann-bench task 存在才适用. 不扫目录——基于上游 test_design 标记的 cases_source."""
        return request.cases_source == "cannbench" and request.golden_contract is not None

    def run(self, request: EvalRequest) -> TestReport:
        # 自建 harness (复用 NPURunner 底层), 但:
        #   - 数据生成: cann-bench DataGenerator (import kernel_eval.data... 内化于本 adapter)
        #   - 比较: cann-bench compare_tensors (CannbenchComparer, P79)
        #   - 阈值: proto 真值 (rule.dtype_thresholds)
        # 双向 adapter:
        #   - 入: EvalRequest.cases (TestCase) → cann-bench 原生 case 格式
        #   - 出: cann-bench CompareResult → CaseReport/TestReport (三维分填上)
        ...
        return _to_test_report(raw_result, with_dimensions=True)
```

**关键**：
- `import DataGenerator` / `compare_tensors` **内化于本 adapter 文件**（不散落到 runner/task_loader），这是 L3 §4.2 的"显式依赖边界"
- `available` 基于 `request.cases_source == "cannbench"`（上游 test_design 标记，**不扫 `tasks/level*/<op>` 目录**）——这是反查 P0/state 时发现的接口需求：state 现无 cases_source 字段，本 L4 新增（见 §7）
- cases 加载：从 `request.cases`（已是 domain TestCase，上游 `cann_bench_cases_loader` 加载）取，adapter 转译到 cann-bench DataGenerator 所需格式；**不再有 task_loader 目录嗅探**

---

## 6. run_precision_cases 改造（`precision_debug.py`）

```python
def run_precision_cases(op_spec, test_cases, npu_id, golden_contract,
                        deploy_result, callable_target, chip_version="A2",
                        use_cannbench_checker=False, log_dir=None, card_pool=None) -> dict:
    """[改造] 内部改调 select_backend().run(), 返回值形态不变 (向后兼容 debug_service)."""
    from ascendc_devkit.adapters.evaluation import select_backend
    from ascendc_devkit.domain.evaluation import EvalRequest, OpRef, RunMode
    from ascendc_devkit.domain.precision import CompareRule
    from ascendc_devkit.adapters.npu.precision_compare import merge_thresholds

    rule = CompareRule(dtype_thresholds=merge_thresholds(
        getattr(op_spec, "precision_thresholds", None)))
    request = EvalRequest(
        op=OpRef(callable_target=callable_target, op_dir=..., chip=chip_version),
        cases=test_cases,
        rule=rule,
        deploy_result=deploy_result,
        golden_contract=golden_contract,
        mode=RunMode.SINGLE_CASE,
        npu_id=npu_id, card_pool=card_pool,
    )
    report = select_backend(request).run(request)
    _persist_report(log_dir, report)   # 落盘 result.json + run.log (debug_service 读)
    return _report_to_legacy_dict(report)   # 保持现有返回 dict 形态 (debug_service 依赖)
```

**保留点**：
- 函数签名 + 返回 dict 形态**不变**（debug_service.run_cases 依赖，P0 的 run_tests 子 stage 经 debug_service 间接调用）
- `try_load_cannbench_task()` **删除**（目录嗅探外部化；cann-bench task 判定移入 CannbenchBackend.available）
- `DEBUG_RESULT_CONTRACT` 保留

> **注**：`use_cannbench_checker` 参数保留但语义弱化（backend 选择改为 select_backend 自动判 available）；可标 deprecated，最终由 select_backend 取代。L4 实施时若 debug_service 调用点简化则一并清理。

---

## 7. run_tests 子 stage 接入 + 上游 cases_source 标记（依赖 P0）

### 7.1 cases_source 上游标记（反查发现的接口需求）

CannbenchBackend.available 不扫目录，需上游告知"cases 来自 cann-bench"。新增 `state.cases_source`：
- `test_design_substages._load_external_cases`：命中 `cann_bench_cases_loader`（cases_path 来自 cann-bench task）→ `state.cases_source="cannbench"`；LLM 生成 cases → `"devkit"`
- `run_precision_cases` 构造 EvalRequest 时从 state 取 `cases_source` 传入
- `CannbenchBackend.available` 读 `request.cases_source == "cannbench"`

**与 P0 关系**：cases_source 是 step-40 自身的 state 字段，不依赖 P0 编排改动。test_design stage 在 P0 之前运行（流水线顺序），标记天然就位。

### 7.2 run_tests 子 stage（P0 §4.1，透明接入）

P0 的 `RunTestsSubstage` `actions()` 派发 `ascendc-precision-run-tests` agent，agent 经 debug CLI `run-cases` → `debug_service.run_cases()` → `run_precision_cases()` → **`select_backend().run()`**。

**本 L4 不改 RunTestsSubstage**（透明替换）。反查 P0 L4 §4.1 transition + run_tests 子 agent（`ascendc-precision-run-tests.md`）写入字段，确认契合：
- run_tests agent 写 checkpoint：`status`(passed) / `failed_case_queue` / `history`(test_result/failed_count/max_err/total_count/failure_type) / `failed_count` / `total_count`
- P0 `_extract_debug_checkpoint` 提取：status/failed_case_count(从 queue 算)/best_*/debug_state/printf_location_result/diagnose_done
- **契合 OK**：P0 transition 字段来源 ⊆ run_tests agent 写入字段集（best_* 由 fix/printf 阶段更新，run_tests transition 读时为旧值但不影响其 resolve_condition）

---

## 8. TDD 顺序（§3.1，红→绿）

### Phase A：domain 中立格式 + 协议
1. `test_evaluation_domain.py`：EvalRequest/TestReport/CaseReport 构造 + `all_passed`/`case_by_id`。
2. `test_select_backend.py`：注册序（Cannbench available → 选它；不 available → Devkit 兜底）；`_default_registry` 顺序。
3. 实现 `domain/evaluation.py` + `adapters/evaluation/__init__.py`。

### Phase B：DevkitBackend
4. `test_devkit_backend.py`：mock NPURunner.execute，断言 DevkitBackend.run 返回 TestReport（三维分 None、cases 来自 raw dict 转换）。
5. 实现 `devkit.py`（迁 runner.execute 的 harness 构造 + DevkitComparer）。

### Phase C：CannbenchBackend
6. `test_cannbench_backend.py`：mock DataGenerator/compare_tensors import，断言 CannbenchBackend.run 用 cann-bench 路径 + 返回三维分；`available` 判定（golden_contract + cann-bench task 标记）。
7. 实现 `cannbench.py`（双向 adapter + 内化 DataGenerator/compare_tensors）。

### Phase D：接入 + 清理
8. 改 `run_precision_cases` 调 select_backend；删 `try_load_cannbench_task`；TaskCase/CannbenchTask dataclass 迁入 cannbench.py；删 `task_loader.py`。
9. 全量 UT + 非 heavy ST 回归（test_precision_debug_stage / test_debug_service / test_self_evolution_stages）。

---

## 9. 验证

- **UT**：domain 格式 + select_backend + DevkitBackend + CannbenchBackend（mock 外部 import/CLI）+ run_precision_cases 接入。
- **ST（非 heavy）**：全量非 heavy ST 回归，重点 test_precision_debug_stage / test_debug_service（run-cases 链路）/ test_self_evolution_stages。
- **heavy_llm（§3.11，交付前用户决策）**：
  - CannbenchBackend 标准对齐：真实 cann-bench 算子（如 scatter）经 backend.run 单 case 判定，验证 per-input value_range 正确（int32 索引不被喂 [-100,100]）+ 与 cann-bench 权威评测一致
  - DevkitBackend 通用：ops-nn 算子经 backend.run 跑通（零 cann-bench 依赖）
  - **本次未覆盖即记录**（§3.11 诚实）

---

## 10. 与 P0 的实施衔接（L3 §11 镜像）

- **P0 先行**：P0 编码（CompositeGroup + 子 stage）+ UT/ST 验证编排层。
- **本 L4 阶段 A-C（协议+两 backend）可与 P0 并行**：不依赖 P0（domain/adapter 独立）。
- **本 L4 阶段 D（接入 run_precision_cases）可与 P0 并行或紧跟**：改 run_precision_cases 内部，P0 的 run_tests 子 stage 透明。
- **集成验证**：P0 + 本 L4 都绿后，heavy_llm 集成验证（编排 + 执行）。

---

## 11. 不改 / 关键边界

- **② CannbenchEvalStage**：保持调 kernel_eval.cli（L3 §9 决策3 不统一）。
- **P79 PrecisionComparer/DevkitComparer/CannbenchComparer**：保留，作 backend 内部组件。
- **NPURunner**：保留作底层 NPU 执行器，Devkit/Cannbench backend 复用。
- **TestReport 三维分**：Devkit 留 None，Cannbench 填；框架不强求（L3 §9 决策1）。
- **算子核心代码**：零改动。
- **checkpoint.json schema / 子 agent 契约**：零改动（P0 已保证）。

---

## 变更记录

| 日期 | 内容 |
|---|---|
| 2026-07-17 | 初版：承接 L3 v3 冻结（服务型抽象）。domain 中立格式 + 协议 + Devkit/Cannbench backend + run_precision_cases 接入 + TDD 4 Phase。假设 P0 已实现，标注接口契合点。4 待确认转决策（L3 §9） |
