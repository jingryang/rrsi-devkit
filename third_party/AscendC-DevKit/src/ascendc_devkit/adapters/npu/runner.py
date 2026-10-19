"""L6 Adapters — NPU Runner: execute operator verification on NPU hardware."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import inspect
import time
from pathlib import Path
from typing import TYPE_CHECKING

from ascendc_devkit.adapters.evaluation.cannbench_env import cann_lib_paths
from ascendc_devkit.adapters.npu.card_pin import card_pin_env
from ascendc_devkit.adapters.npu.golden_binding import bind_golden_args
from ascendc_devkit.adapters.npu.precision_comparer import (
    DevkitComparer,
    PrecisionComparer,
)
from ascendc_devkit.domain.chip import is_known_generation, to_soc_version
from ascendc_devkit.domain.exceptions import HarnessContractError
from ascendc_devkit.domain.operator import validate_case_attrs
from ascendc_devkit.domain.precision import CompareRule, merge_thresholds
from ascendc_devkit.infra.logger import Logger

if TYPE_CHECKING:
    from ascendc_devkit.domain.operator import OperatorSpec
    from ascendc_devkit.domain.requirement import TestCase



def _detect_crash_dump(run_started_at: float) -> str | None:
    """Best-effort fatal-crash signal: CANN writes ``exception_info.*`` on a fatal
    AICORE abort to ``<cwd>/extra-info/data-dump/``. The dump's mere existence is a
    100%-reliable signal of a fatal device crash. Return the newest path whose
    mtime falls within the subprocess span (>= ``run_started_at``), else None.

    Non-load-bearing enrichment (§1.3 可观测): ``failure_type``/``returncode`` carry
    the crash identity regardless; this just hands diagnose the dump path. CWD is the
    op dir in the precision_debug pipeline; the glob misses silently elsewhere.

    A small backward tolerance (``_CRASH_DUMP_MTIME_TOL``) absorbs clock skew between
    ``time.time()`` (ns precision) and filesystem mtime (coarser) so a dump written
    microseconds after ``run_started_at`` isn't falsely excluded — while still
    rejecting stale dumps from prior iters (minutes+ old).
    """
    try:
        base = Path.cwd()
    except OSError:
        return None
    threshold = run_started_at - _CRASH_DUMP_MTIME_TOL
    newest = None
    try:
        for p in base.glob("extra-info/data-dump/**/exception_info.*"):
            try:
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime >= threshold and (
                newest is None or st.st_mtime > newest[0]
            ):
                newest = (st.st_mtime, str(p))
    except Exception:
        return None
    return newest[1] if newest else None


# Tolerance for the crash-dump mtime window (seconds). See _detect_crash_dump.
_CRASH_DUMP_MTIME_TOL = 2.0


def _crash_extras(returncode, timed_out: bool, stderr: str, run_started_at: float) -> dict:
    """Honest crash-identity fields the abnormal-exit sentinel must carry (D2).

    A fatal AICORE abort kills the child (negative returncode = signal, e.g. -6
    SIGABRT) or hangs until the harness watchdog (``timed_out``; timeout_sec is
    caller-configurable, default 120s). The old sentinel
    collapsed every abnormal exit into ``{passed:False, max_diff:999, case_details:[]}``
    with NO failure_type — and ``golden_used`` never reaches result.json (the
    harness dies before its ``print``), so scope_guard mistook a crash for a golden
    defect and HALT'd the wrong stage. These extras restore the identity so a crash
    routes to diagnose. Decision basis is the STRUCTURAL signal
    (returncode/timeout/dump), NOT a stderr keyword grep (§1.12 — no error-vocabulary
    whitelist that rots with CANN wording changes).
    """
    crash_dump = _detect_crash_dump(run_started_at)
    if timed_out:
        failure_type: str | None = "timeout"
    else:
        # Any non-zero / signal exit on the kernel subprocess is a runtime crash
        # (returncode==0 is handled by the parse path, never reaches here).
        failure_type = "runtime_crash"
    extras: dict = {
        "failure_type": failure_type,
        "returncode": returncode,
        "timed_out": timed_out,
        # Keep stderr HEAD (compat/readability) AND add TAIL — the real crash
        # keyword (AICORE/507035/RuntimeError) sits AFTER CANN's warning preamble,
        # so ``[:500]`` truncated it off (D2 defect B).
        "error_tail": (stderr or "")[-800:],
    }
    if crash_dump is not None:
        extras["crash_dump_path"] = crash_dump
    return extras


def _tested_cases_summary(test_cases: list) -> list[dict]:
    """Per-case shape/element-size summary for timeout attribution.

    A timeout returns an empty ``case_details`` (the harness died before its
    final ``print``), so the shape info the queue script needs to judge
    'is this a large-shape timeout?' would otherwise be lost. This summary
    restores it from the cases the runner actually executed: each case's shape
    plus the max input element count — the structural size signal (§1.12, no
    operator-name coupling). build-failed-case-queue.py consumes this to decide
    whether to amplify the timeout and retry (large shape) or report honestly
    (environment/deadlock).
    """
    summary: list[dict] = []
    for tc in test_cases:
        shapes: list = []
        max_elements = 0
        for inp in getattr(tc, "inputs", None) or []:
            shp = inp.get("shape") if isinstance(inp, dict) else None
            if not isinstance(shp, list):
                continue
            shapes.append(shp)
            prod = 1
            for dim in shp:
                if isinstance(dim, int) and dim > 0:
                    prod *= dim
                else:
                    prod = 0  # symbolic / str dim → not countable
                    break
            if prod > max_elements:
                max_elements = prod
        summary.append({
            "case_id": getattr(tc, "case_id", "") or getattr(tc, "name", ""),
            "shape": str(shapes),
            "max_input_elements": max_elements,
        })
    return summary


def _validate_case_form(tc, idx, operator=None):
    """Validate test-case morphology (§P5/D2=A).

    Returns the validated attrs dict (filtered: 与输入同名的 attr key 已丢弃，
    cann-bench optional 输入占位) — the caller serializes THIS dict, not
    ``tc.attrs``, so filtering happens exactly once at the validator.
    Raises :exc:`HarnessContractError` on violation.
    """
    inputs = getattr(tc, "inputs", None)
    if inputs is None:
        raise HarnessContractError(
            f"test_cases[{idx}].inputs is missing or None"
        )
    if not isinstance(inputs, (list, tuple)):
        raise HarnessContractError(
            f"test_cases[{idx}].inputs must be list/tuple "
            f"(got {type(inputs).__name__})"
        )
    # Positional coupling guard: the DYNAMIC check below maps
    # ``test_cases.inputs[j] → op_spec.inputs[j]`` by index to read param_type,
    # but the two lists come from different writers (test_design vs requirement).
    # If there are MORE test-case inputs than op_spec tensors, the extra entries
    # have no op_spec counterpart — ``j < len(op_inputs)`` silently leaves them
    # is_dynamic=False, i.e. a DYNAMIC input validated as non-dynamic (the exact
    # §1.10 silent-misjudgment shape). Fail deterministically instead (§3.7 诚实
    # 报错 > 静默误判). Fewer test-case inputs is legitimate (an OPTIONAL input
    # omitted at the tail) and stays safe under the per-index guard, so only the
    # over-count is a contract violation.
    if operator is not None:
        op_inputs = getattr(operator, "inputs", None) or []
        # Only when op_spec actually DECLARES inputs is a positional comparison
        # meaningful. A name-only op_spec (empty inputs) carries no positional
        # info — same as operator=None — so the per-index guard's REQUIRED
        # fallback applies and we don't flag a phantom misalignment.
        if op_inputs and len(inputs) > len(op_inputs):
            raise HarnessContractError(
                f"test_cases[{idx}].inputs count ({len(inputs)}) exceeds "
                f"op_spec.inputs count ({len(op_inputs)}) — positional "
                f"param_type mapping is unreliable (test_cases ⇄ op_spec "
                f"misalignment; check upstream test_design vs requirement)"
            )
    for j, inp in enumerate(inputs):
        if not isinstance(inp, dict):
            raise HarnessContractError(
                f"test_cases[{idx}].inputs[{j}] must be dict "
                f"(got {type(inp).__name__})"
            )
        shape = inp.get("shape")
        # Q3-multi_add: DYNAMIC (Tensor[]) inputs take list[list[int]] — one
        # inner shape per tensor in the variadic list. The harness template
        # already normalizes nested shapes (its ``input_shapes=...`` has an
        # ``isinstance(i['shape'][0], list)`` branch); this validator was the
        # only holdout, rejecting what the harness supports. Map
        # TestCase.inputs[j] → operator.inputs[j] by position to read param_type.
        is_dynamic = False
        if operator is not None:
            op_inputs = getattr(operator, "inputs", None) or []
            if j < len(op_inputs):
                is_dynamic = (
                    str(getattr(op_inputs[j], "param_type", "")).upper() == "DYNAMIC"
                )
        if is_dynamic:
            if (not isinstance(shape, (list, tuple))
                    or not all(isinstance(s, (list, tuple))
                               and all(isinstance(d, int) for d in s)
                               for s in shape)):
                raise HarnessContractError(
                    f"test_cases[{idx}].inputs[{j}].shape must be "
                    f"list[list[int]] (DYNAMIC/Tensor[] input; got {shape!r})"
                )
        elif not isinstance(shape, (list, tuple)) or not all(
            isinstance(d, int) for d in shape
        ):
            # P2 (precision-tensorlist-harness-contract): when the case supplies a
            # multi-tensor list-of-lists but the op_spec input isn't DYNAMIC, hint
            # at the likely upstream cause — the reject stays (契约不一致要大声失败,
            # §1.13), only the message becomes self-explanatory (可诊断, §1.2).
            _hint = ""
            if (isinstance(shape, (list, tuple)) and len(shape) > 0
                    and isinstance(shape[0], (list, tuple))):
                # M2 (PR-42 review): no repo-specific docs path in a generic
                # runner error message — keep the hint repo-agnostic.
                _hint = (" — 用例给的是多张量 list-of-lists 但 op_spec 对该输入声明 "
                         "param_type 非 DYNAMIC；TensorList 输入应派生 DYNAMIC，"
                         "疑似 requirement 误标 param_type")
            raise HarnessContractError(
                f"test_cases[{idx}].inputs[{j}].shape must be list[int] "
                f"(got {shape!r}){_hint}"
            )

    attrs = getattr(tc, "attrs", None)
    if attrs is None:
        attrs = {}
    if not isinstance(attrs, dict):
        raise HarnessContractError(
            f"test_cases[{idx}].attrs must be dict "
            f"(got {type(attrs).__name__})"
        )
    if operator is not None:
        # 过滤与输入同名的 attr key（cann-bench 约定：optional 输入在 attrs 列以
        # null 占位，quant_matmul offset/pertoken_scale/bias；官方 param_builder
        # 对与输入同名的 attr key 忽略——params 已含输入键）。devkit 位置传参 +
        # kwargs attrs 会因同名 key 造成位置 + 关键字重复传参崩（"got multiple
        # values for argument"），故校验前丢弃——输入值以 inputs 槽为准，占位不
        # 参与 attr 校验（None 无 spec 会被 validate_case_attrs 拒）。名字是算子
        # 自带信息（TensorSpec.name），不耦合 cann-bench 代码（§1.13 忠实消费上游
        # 约定，非工程私改）。
        _proto_names = {s.name for s in (operator.inputs or [])}
        if _proto_names:
            _aliased = sorted(k for k in attrs if k in _proto_names)
            if _aliased:
                # null 占位过滤是常态；非 null 同名 key 属上游误填信号，WARN 留痕
                # （§1.3），仍按输入槽权威丢弃。
                if any(attrs[k] is not None for k in _aliased):
                    Logger.warn(
                        f"case {getattr(tc, 'name', 'case')!r} attrs 含与输入同名"
                        f"的 key {_aliased} 且值非 null（cann-bench optional 输入"
                        f"占位应为 null）——输入值以 inputs 槽为准，同名 attr 已丢弃"
                    )
                attrs = {k: v for k, v in attrs.items()
                         if k not in _proto_names}
    # §1.15/§2.5 单点：attrs 契约校验（含数值字符串 coerce 副作用）在域层
    # ``domain.operator.validate_case_attrs``——runner 与 test_design 自检共用。
    validate_case_attrs(attrs, idx, operator)
    return attrs


# P79: per-dtype 阈值默认表 + 逐输出聚合判定已上移至 domain/precision
# （DEFAULT_THRESHOLDS + merge_thresholds）与 precision_comparer（judge_case_details）。
# runner 不再自带第二份容差表（§2.5 单通路）——阈值经 CompareRule.dtype_thresholds
# （proto 真值经 debug_service 桥接）贯穿，聚合经 PrecisionComparer.aggregate。


class NPURunner:
    """Execute operator verification and performance measurement on NPU hardware.

    Uses subprocess to run a Python test harness that:
    1. Imports the compiled operator / golden reference
    2. Runs inference on specified shapes
    3. Outputs precision data as JSON

    Precision judgment is P79 rule × backend orthogonal:
    - ``rule`` (``CompareRule.dtype_thresholds`` = proto truth via
      ``merge_thresholds``) drives both the per-dtype thresholds baked into the
      harness and the main-process aggregation.
    - ``comparer`` (``PrecisionComparer``) injects the harness setup/import lines
      and aggregates the subprocess-returned ``case_details``
      (``DevkitComparer`` default / ``CannbenchComparer`` injected).

    This is a pure L6 adapter: execute() returns a result dict or raises.
    Stub fallback strategy lives in the calling gate/stage (L3-L4), not here.
    """

    def __init__(self, chip_version: str | None = None):
        if chip_version is None:
            from ascendc_devkit.adapters.npu.detect import detect_chip_version
            chip_version = detect_chip_version()
        self._chip_version = chip_version
        self._torch_npu_available = False
        self._device_count = 0
        self._check_environment()

    @classmethod
    def probe_free(cls, chip_version: str | None = None) -> "NPURunner":
        """构造**不探测**的 runner（主进程合法构造通路，step-106）。

        ``__init__`` 的构造期探测（``_check_environment``）在进程内 import
        torch/torch_npu——只允许发生在子进程（run-cases 链）；主进程（perf 测量
        编排、smoke harness 生成）一律经本通路构造：设备无关字段就位、探测字段
        取三值 None=未知（``_torch_npu_available=None``/``_device_count=None``——
        主进程不裁决设备可用性，真实 kernel 执行在子进程 harness，它才是设备
        真值源；execute 的可用性闸门对 None 跳过，False 才是探测实证不可用）。
        ``chip_version`` 缺省时**保持 None 原样传入**（不静默缺省 A2——detect.py
        模块头「never a silent A2 guess」不变式）；真需要 soc_version 时由
        ``_soc_version`` 响亮报错。deploy ``_build_smoke_harness`` 的 ``__new__``
        惯用法正式化（§1.15 单点：同一意图不再三处手写）。
        """
        runner = cls.__new__(cls)
        runner._chip_version = chip_version
        # None = 未知（主进程不裁决设备可用性——真实执行在子进程 harness，
        # 它才是设备真值源；execute 的可用性闸门对 None 跳过）。
        runner._torch_npu_available = None
        runner._device_count = None
        runner._env_info = {"torch_available": None, "torch_npu_available": None,
                            "device_count": None, "probe": "probe-free"}
        return runner

    def _soc_version(self) -> str:
        """Translate the detected chip → CANN ``soc_version`` for the run harness.

        Single translation feed point for both the build harness (``CHIP_VERSION``
        env) and the eval harness (``chip_version`` source line). Raises a clear
        ``RuntimeError`` — NOT ``to_soc_version``'s bare ``ValueError`` — when the
        chip is unknown (``None``: never declared — e.g. a probe-free runner whose
        caller passed no chip; or ``UNKNOWN``: the probe couldn't identify the
        hardware), so there is no honest soc_version to compile/run against. This
        is the run-time terminal signal for an unresolved chip; the dispatch-time
        gate (Step 3) and the pre-design confirmation gate (Step 8) are the
        earlier chances to catch it.
        """
        if not is_known_generation(self._chip_version):
            raise RuntimeError(
                f"无法确定运行 soc_version：NPU 硬件代际未知（{self._chip_version!r}），"
                f"探机未能识别本机设备。请修复 NPU/驱动环境，或用 --runtime_target_chip "
                f"显式声明硬件代际。"
            )
        return to_soc_version(self._chip_version)

    def _check_environment(self) -> dict:
        """Detect NPU environment. Returns availability info."""
        info: dict = {
            "torch_available": False,
            "torch_npu_available": False,
            "device_count": 0,
        }
        try:
            import torch
            info["torch_available"] = True
        except ImportError:
            pass

        try:
            import torch_npu  # noqa: F811
            # Smoke test: a successful import does NOT guarantee the NPU is
            # functional.  torch_npu is a monkey-patch package that adds .npu()
            # to torch.Tensor; if the backing torch is CPU-only (e.g. 2.7.1+cpu)
            # the import succeeds but .npu() fails at runtime.
            torch.zeros(1).npu()  # Raises RuntimeError/AttributeError if broken.
            info["torch_npu_available"] = True
            self._torch_npu_available = True
            try:
                self._device_count = torch_npu.npu.device_count()
                info["device_count"] = self._device_count
            except Exception:
                pass
        except (ImportError, RuntimeError, AttributeError) as e:
            # §1.2 可诊断：保留首错 traceback（如 NPU runtime init 并发冲突的
            # ERR99999），而非静默吞成 torch_npu_available=False——否则下游
            # _preflight_runtime 报「NPU 运行时缺失」时看不到真实原因。
            Logger.warn(
                f"torch_npu smoke 失败（.npu() init）：{type(e).__name__}: {e}",
                exc_info=True)

        self._env_info = info
        return info

    def execute(
        self,
        operator: OperatorSpec,
        test_cases: list[TestCase],
        npu_id: int | None = None,
        golden_contract=None,
        deploy_result=None,
        callable_target=None,
        precision_threshold: float = 1e-2,
        rule: CompareRule | None = None,
        comparer: PrecisionComparer | None = None,
        log_dir=None,
        timeout_sec: float = 120,
    ) -> dict:
        """Execute operator on NPU, return per-case timing and precision results.

        Args:
            rule: 精度判定规则（P79，``CompareRule.dtype_thresholds`` = proto 真值经
                ``merge_thresholds`` 合并默认表）。When None，用默认表（proto 未声明
                精度规格）。harness 按每个输出的**运行时 dtype** 取阈值——单次运行可
                含混合 dtype 输出（如 int8 量化值 + float32 scale）。
            comparer: 精度判定策略（P79，rule × backend 正交的 backend 侧）。默认
                ``DevkitComparer``（§1.7 自包含，abs-diff 路径）；cann-bench 任务由
                debug_service 注入 ``CannbenchComparer``（harness 走 cann-bench
                ``compare_tensors`` 权威路径）。comparer 提供 harness setup import 行
                + 主进程 ``aggregate``（逐输出 passed 权威 / 否则 diff ≤ threshold）。
            precision_threshold: 无 golden 时的标量回退（``max_diff <= precision_threshold``），
                与 dtype rule 正交（无 golden 无法逐 dtype 判）。
            timeout_sec: 测试 harness 子进程看门狗（秒）。大 shape 用例耗时可能超过默认
                120s —— 调用方（debug_service 解析 control.json 放大值或 config 默认）
                可设置；超时时返回带 ``tested_cases`` 摘要供队列脚本评估大 shape。
            golden_contract: {path, entry, input_type} describing how to load the
                authoritative golden reference. ``path`` is an absolute path to a
                .py module; ``entry`` the function name in it (cann-bench uses the
                op name, hand-written fixtures use ``reference``); ``input_type``
                (``torch``/``numpy``) what tensor type it expects. None when no
                golden is available (the caller then has no precision truth).
                Resolved by the verify stage from the explicit CLI golden
                contract (``--golden`` + ``--golden-entry`` + ``--golden-input-type``,
                13 E1).
            deploy_result: DeployResult from the deploy stage — carries the
                per-op python_path / install_path / ld_library_path_add needed to
                import + call the deployed kernel (G7/P7).
            callable_target: {kind, symbol} from codegen_manifest — how to call
                the operator (e.g. torch.ops.cann_bench.add). codegen authored
                the registration, so it is the authority on the symbol (D7).

        Returns:
            dict with keys: passed (bool), actual_ms (float), per_shape (dict),
            max_diff (float), baseline_ms (float), bottleneck (str)
        """
        # P79: rule × backend 默认解析。rule=None → 默认表（proto 未声明精度规格，
        # perf 路径无精度门控时走此）；comparer=None → DevkitComparer（§1.7 默认 backend）。
        # merge_thresholds 在 domain/precision（torch-free，模块级 import——原 precision_compare
        # 懒导入的 torch 理由已随阈值上移消失，且主进程纯度不变式禁止它）。
        if rule is None:
            rule = CompareRule(dtype_thresholds=merge_thresholds(None))
        if comparer is None:
            comparer = DevkitComparer()

        # None = probe-free 构造（主进程编排，设备真值源=子进程 harness）→ 跳过
        # 闸门；False = 子进程探测实证不可用 → 诚实报缺（§3.7）。
        if self._torch_npu_available is False:
            from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
            raise EnvironmentNotAvailableError(
                stage_name="npu_runner",
                missing="NPU runtime (torch_npu)",
                help_hint="Install torch_npu or verify your torch/torch_npu versions are compatible (torch must be a GPU build, not CPU-only)",
            )

        # G7/D8: the real kernel is only callable when deploy produced the
        # artifacts AND codegen declared the callable_target. Missing either →
        # honest error, never a stubbed max_diff=0.
        if deploy_result is None or not getattr(deploy_result, "python_path", ""):
            from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
            raise EnvironmentNotAvailableError(
                stage_name="npu_runner",
                missing="deploy artifacts (python_path)",
                help_hint="verify precision requires the operator to be deployed first (deploy stage must run before verify and produce python_path/install_path)",
            )
        if not (isinstance(callable_target, dict)
                and callable_target.get("kind") and callable_target.get("symbol")):
            from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
            raise EnvironmentNotAvailableError(
                stage_name="npu_runner",
                missing="callable_target (kind, symbol)",
                help_hint="codegen_manifest must declare callable_target so the harness knows which symbol to call",
            )

        Logger.action(
            "npu_execute",
            f"Running {operator.name} on NPU {npu_id} via {callable_target['symbol']}",
        )

        # P13 (step-116)：npu_id 是 dispatch 在 op 边界解析出的权威 op 卡
        # （原 span 级 card_context 租约已拆除——agent 子树绕过其账本正是 P13
        # 根因；op 级租约 + 双变量 pin 取代）。物理卡只进
        # ASCEND_RT_VISIBLE_DEVICES，harness 内设备号恒 0（remap 语义）。
        if npu_id is None:
            raise ValueError(
                "npu_id must be the op-resolved card (dispatch/resolve_op_card) "
                "— None means the caller skipped the single resolution point")
        card = int(npu_id)
        harness = self._build_test_harness(
            operator, test_cases, golden_contract, deploy_result,
            callable_target, rule=rule, comparer=comparer,
        )

        # Write harness to log_dir BEFORE subprocess.run so it's preserved
        # even on timeout/crash — critical for post-mortem debugging.
        _log_path = Path(log_dir) if log_dir is not None else None
        if _log_path is not None:
            _log_path.mkdir(parents=True, exist_ok=True)
            (_log_path / "harness.py").write_text(harness, encoding="utf-8")

        # Also write to a tempfile for execution (avoid ARG_MAX limits).
        import tempfile
        with tempfile.NamedTemporaryFile(
            mode='w', suffix='.py', delete=False, prefix='npu_harness_',
        ) as f:
            f.write(harness)
            harness_path = f.name
    
        try:
            try:
                run_env = {
                    **os.environ,
                    # P13 (step-116)：双变量 pin——物理卡只由 VISIBLE_DEVICES
                    # 携带，harness 内设备号恒 0（remap）。
                    **card_pin_env(card),
                    "CHIP_VERSION": self._soc_version(),
                    "PYTHONUNBUFFERED": "1",
                }
                # G7: inject deploy artifact env so the harness can import + call
                # the deployed kernel (mirrors the Deployer smoke env).
                py_path = getattr(deploy_result, "python_path", "")
                opp_path = getattr(deploy_result, "install_path", "")
                ld_add = getattr(deploy_result, "ld_library_path_add", "")
                if py_path:
                    existing_pp = run_env.get("PYTHONPATH", "")
                    run_env["PYTHONPATH"] = (
                        f"{py_path}:{existing_pp}" if existing_pp else py_path
                    )
                if opp_path:
                    # step-108: 值形态单源（vendor 级由 env_contract 拼出，§1.15）
                    from ascendc_devkit.infra.env_contract import (
                        expected_ascend_custom_opp)
                    run_env["ASCEND_CUSTOM_OPP_PATH"] = (
                        expected_ascend_custom_opp(opp_path))
                ld_parts = [p for p in [ld_add] if p]
                ld_parts.extend(cann_lib_paths())
                existing_ld = run_env.get("LD_LIBRARY_PATH", "")
                if existing_ld:
                    ld_parts.append(existing_ld)
                if ld_parts:
                    run_env["LD_LIBRARY_PATH"] = ":".join(ld_parts)
    
                # D2: record the subprocess span start so _crash_extras can
                # distinguish a freshly-written exception_info dump (fatal
                # AICORE abort) from stale ones via mtime.
                run_started_at = time.time()
                result = subprocess.run(
                    [sys.executable, harness_path],
                    capture_output=True, text=True, timeout=timeout_sec,
                    env=run_env,
                )
                # P54 D7: dump the raw harness stdout/stderr (carries DumpTensor
                # output + prints) to <log_dir>/run.log, so the
                # precision_debug agent can read the root-cause signal off disk
                # (run-cases CLI passes log_dir=<artifacts>/debug/<op>/iter-N/).
                # harness.py is already written before subprocess.run (post-mortem).
                if log_dir is not None:
                    _log_path = Path(log_dir)
                    (_log_path / "run.log").write_text(
                        f"=== STDOUT ===\n{result.stdout}\n\n"
                        f"=== STDERR ===\n{result.stderr}\n",
                        encoding="utf-8",
                    )
                # §1.2 可诊断 + §1.6 DI + §2.7：降级 signature 由 comparer 自声明
                # （backend 知道自己注入的 warning 原文），runner 通用层据此 scan
                # 上浮主 log [WARN]——不 hardcode cann-bench 文本，避免通用 runner
                # 耦合具体 backend（compare_tensors fallback 三连缺陷 F2）。
                _stderr_str = result.stderr or ""
                _sigs = getattr(comparer, "degradation_signatures", ()) or ()
                if any(_s in _stderr_str for _s in _sigs):
                    Logger.warn(
                        f"precision 对比降级：{type(comparer).__name__} 的 harness "
                        f"降级到非权威对比路径（详见 per-iter run.log 的 STDERR）。"
                        f"case 正确性判定口径可能已变。"
                    )
                if result.returncode == 0:
                    for line in result.stdout.strip().splitlines():
                        line = line.strip()
                        if line.startswith("{"):
                            data = json.loads(line)
                            actual_ms = float(data.get("total_ms", 0.0))
                            max_diff = float(data.get("max_diff", 0.0))
                            case_details = data.get("case_details", [])
                            # G7 / P54: per-dtype pass/fail — each output is
                            # checked against its dtype-specific threshold (e.g.
                            # int8 → 1.0, fp16 → 0.001) rather than a blanket
                            # 1e-2 that is too loose for fp32 and too tight for
                            # int8.  The harness bakes the threshold into each
                            # output_comparison; the Python side checks whether
                            # *any* output of *any* case exceeds its threshold.
                            golden_used = data.get("golden_used", False)
                            if golden_used and case_details:
                                # P79: 聚合经 comparer.aggregate（rule × backend 正交
                                # 的 backend 侧；逐输出 passed 权威 / 否则
                                # diff ≤ threshold，阈值取 rule.dtype_thresholds）。
                                passed = comparer.aggregate(rule, case_details)
                            else:
                                passed = max_diff <= precision_threshold
                            return {
                                "passed": passed,
                                "max_diff": max_diff,
                                "actual_ms": actual_ms,
                                "case_details": case_details,
                                "dtype_thresholds": rule.dtype_thresholds,
                                # Propagate harness-reported provenance so callers
                                # (precision_debug stage, ST, CLI) can distinguish a
                                # real kernel-vs-golden diff from a no-golden run.
                                # The harness always sets ``bottleneck`` from
                                # golden_used; the ``or`` fallback keeps the value
                                # consistent if a harness ever omitted it.
                                "bottleneck": data.get("bottleneck") or (
                                    "real_kernel_vs_golden" if golden_used
                                    else "no_golden_reference"),
                                "golden_used": golden_used,
                            }
                return {
                    "passed": False,
                    "max_diff": 999.0,
                    "actual_ms": 999.0,
                    "case_details": [],
                    "dtype_thresholds": rule.dtype_thresholds,
                    "error": result.stderr[:500],
                    # D2: restore crash identity so scope_guard routes a fatal
                    # abort to diagnose instead of mistaking it for a golden
                    # defect (golden_used never reaches result.json when the
                    # harness is killed before its print). Structural signal
                    # (returncode/dump) is the decision basis, not a stderr
                    # keyword grep (§1.12).
                    **_crash_extras(
                        result.returncode, False,
                        result.stderr or "", run_started_at,
                    ),
                }
            except subprocess.TimeoutExpired as e:
                # D2-defect D: run.log write (at :429, after subprocess.run)
                # is skipped on timeout — yet run.log is the very artifact
                # scope_guard is told to read for crash evidence. Recover the
                # partial stdout/stderr and write it here too.
                _to_stderr = e.stderr
                if isinstance(_to_stderr, bytes):
                    _to_stderr = _to_stderr.decode(errors="replace")
                _to_stdout = e.stdout
                if isinstance(_to_stdout, bytes):
                    _to_stdout = _to_stdout.decode(errors="replace")
                if _log_path is not None:
                    (_log_path / "run.log").write_text(
                        f"=== STDOUT ===\n{_to_stdout or ''}\n\n"
                        f"=== STDERR ===\n{_to_stderr or ''}\n",
                        encoding="utf-8",
                    )
                return {
                    "passed": False,
                    "max_diff": 999.0,
                    "actual_ms": 999.0,
                    "case_details": [],
                    "dtype_thresholds": rule.dtype_thresholds,
                    "error": (_to_stderr or str(e))[:500],
                    # D2: timeout = kernel hung (typically a fatal AICORE abort
                    # blocking in CANN device-sync teardown until the watchdog).
                    # Mark as a crash, not a golden defect.
                    #
                    # 超时自适应：case_details 为空（harness 死于 print 前），
                    # 若只回传空列表，队列脚本无法判断「是否大 shape 超时」。
                    # 这里补上 tested_cases 摘要（各用例 shape + 输入元素总数）
                    # + 实际超时值，供脚本评估后决定放大超时重试或如实反馈。
                    "tested_cases": _tested_cases_summary(test_cases),
                    "timeout_sec": timeout_sec,
                    **_crash_extras(
                        None, True, _to_stderr or "", run_started_at,
                    ),
                }
        finally:
            os.unlink(harness_path)

    def _build_test_harness(
        self, operator: OperatorSpec, test_cases: list[TestCase],
        golden_contract=None, deploy_result=None, callable_target=None,
        rule: CompareRule | None = None,
        comparer: PrecisionComparer | None = None,
        smoke_probe: bool = False,
    ) -> str:
        """Generate a Python test harness script.

        The generated script:
          1. Initializes NPU device
          2. Imports the deployed operator package + resolves callable_target
          3. For each test case, creates input tensors, runs the REAL kernel on
             NPU and the golden reference on CPU, computes max_diff = |kernel - golden|
          4. Outputs timing and precision data as JSON
        """
        symbol = (callable_target or {}).get("symbol", "")
        # Scaffolding authority: kind is set upstream by the repo profile and
        # carried in callable_target — do NOT silently default to torch_op here
        # (that was a hidden second truth source that let a kind-less manifest
        # masquerade as torch_op). An empty kind means the manifest never went
        # through codegen's profile injection → a contract drift we surface, not
        # paper over (§1.2 可诊断 / §3.7).
        kind = (callable_target or {}).get("kind", "")
        if not kind:
            raise ValueError(
                "callable_target.kind is empty — the invocation protocol must be "
                "set from the repo profile (codegen injects it). Refusing to "
                "assume torch_op."
            )

        # 13 E1: golden contract — {path, entry, input_type}. The verify stage
        # resolves this from the explicit CLI golden contract (--golden +
        # --golden-entry + --golden-input-type). None when no golden is available.
        gc = golden_contract or {}
        g_path = str(gc["path"]) if gc.get("path") else None
        g_entry = gc.get("entry") or "reference"
        g_input_type = gc.get("input_type") or "numpy"
        # golden 参考计算精度：对齐 cann-bench eval（默认 fp64_cpu）。空值落默认
        # —— harness 与 eval 必须用同一参考，否则 debug 判过而 eval 判挂的假收敛。
        g_precision = gc.get("precision") or "fp64_cpu"
        # eval seed：harness 与 kernel_eval 的 config.eval_seed 必须同值（默认 0）。
        # 显式从契约读（不再模板内硬编码 0）——两侧种子漂移会静默分裂判定。
        g_eval_seed = gc.get("eval_seed") or 0

        # Serialize each test case as {name, inputs:[{shape,dtype,data?}, ...],
        # attrs:{...}}. All inputs of a case are passed positionally to BOTH the
        # kernel and the golden — this supports n-ary ops (add(a,b),
        # rope(x,cos,sin,mode), …), not just unary. A case with no inputs falls
        # back to a single 1024 fp16. attrs (A2/P8) are forwarded as kwargs so
        # non-default operator branches are exercised; empty attrs is a no-op.
        #
        # value_range 归一化：NaN/Inf → sentinel 字符串（__NAN__/__INF__/__NINF__），
        # 避开 json.dumps→NaN/Infinity→Python NameError。cann-bench csv 把 inf/nan
        # 存成字符串 "-inf"/"nan"，loader 的 float() 已转真 float；这里对 str 再兜
        # 一道 float()，防上游漏转时字符串穿透到 harness。
        import math as _math
        def _norm_vr(v):
            if isinstance(v, str):
                try:
                    v = float(v)
                except (ValueError, TypeError):
                    return v
            if isinstance(v, float):
                if _math.isnan(v): return "__NAN__"
                if _math.isinf(v) and v > 0: return "__INF__"
                if _math.isinf(v) and v < 0: return "__NINF__"
            return v

        serial_cases: list[dict] = []
        # cann-bench case_id_str 兜底构造：evaluator.get_case_id_str() 真值 =
        # f'{rel_path}_{case_num}'（如 'level1/clipped_swiglu_7'）。优先取 loader 填进
        # TestCase.case_id 的串；为空时（state_snapshot.json 在 loader 升级前序列化、
        # case_id='' 的存量快照复用）从 golden 路径反推 rel_path + name 末段拼出同串，
        # 让旧 state 快照也立即生效，不依赖重新跑 test_design。最后才回退本批序号
        # _idx+1（单用例 _idx=0 会压成 1 → 种子漂移，故仅当反推不出时才用）。
        _rel_path = ""
        if g_path and "tasks/" in str(g_path):
            # g_path = .../tasks/<rel_path>/golden.py → 取 tasks/ 与 golden.py 之间段
            _rel_path = str(g_path).rsplit("tasks/", 1)[-1].rsplit("/", 1)[0]

        def _case_id_from_name(name: str):
            if not name:
                return None
            tail = str(name).rsplit("_", 1)[-1]
            return tail if tail.isdigit() else None

        def _resolve_case_id(tc, _idx):
            cid = getattr(tc, "case_id", None)
            if cid:
                return cid  # loader 已填的完整 case_id_str
            num = _case_id_from_name(getattr(tc, "name", ""))
            if num and _rel_path:
                return f"{_rel_path}_{num}"  # 旧 state 快照兜底：拼出完整串
            if num:
                return num  # 无 rel_path 时至少保持单/全量一致（用全局 num）
            return _idx + 1

        for _idx, tc in enumerate(test_cases):
            # 返回过滤后的 attrs（与输入同名的 cann-bench optional 占位 key 已丢弃，
            # 见 _validate_case_form）——序列化消费返回值，不重复过滤。
            _case_attrs = _validate_case_form(tc, _idx, operator)
            # 用例级 dtype 兜底 = 首个非空声明 dtype。存量防崩猜测，非合法语义：仅对
            # 「多输入同 dtype 用例」语义正确；异构 dtype 用例出现空值属已损坏数据，
            # 继承值不可信（WARN 会标注，见 _hetero）。仅对「存量」无依据数据防崩（旧
            # state_snapshot 空串残值、非 loader 生产者），不上升为合法语义——新数据经
            # loader 广播（cann_bench cases_loader）/ csv 契约校验（csv_to_testcases）后
            # 不会带空 dtype 到达此处。全用例均无声明时才落回 fp16 既有默认（「无信息
            # 可循」的 last resort，非业务语义代理）。见 docs/plan/case-dtype-broadcast/。
            _declared = [_i.get("dtype") for _i in tc.inputs if _i.get("dtype")]
            _hetero = len(set(_declared)) > 1
            _case_dtype = _declared[0] if _declared else "fp16"
            inps = []
            for inp in tc.inputs:
                if isinstance(inp, dict):
                    # proto_idx = original proto.inputs position, an EXPLICIT
                    # field written by every input producer (cann-bench loader,
                    # test-design _flat_inputs/_build_inputs) — the harness uses
                    # it to re-insert None placeholders for absent optional
                    # inputs, restoring proto order so positional get_input /
                    # bind_golden_args / kernel calls line up (conv1d
                    # query_start_loc absent → None at slot 3, instead of
                    # cache_indices mis-bound onto it). Position is never
                    # inferred from names (§1.15 single point); entries without
                    # the field degrade to the compact position only.
                    _proto_idx = inp.get("proto_idx")
                    if not isinstance(_proto_idx, int):
                        _proto_idx = len(inps)
                    _d = inp.get("dtype")
                    if not _d:   # 空串 "" / 缺失 None 一视同仁（get 默认值对空串不生效）
                        if _declared:
                            _inherit = (f"继承用例声明 dtype={_case_dtype!r}"
                                        + ("（用例存在异构 dtype，继承值仅防崩、不可信）"
                                           if _hetero else ""))
                        else:
                            _inherit = "用例无 dtype 声明，回退框架默认 fp16"
                        Logger.warn(
                            f"case {getattr(tc, 'name', 'case')!r} input {_proto_idx} "
                            f"dtype 为空/缺失，{_inherit} "
                            f"（loader 广播应已展开；空值说明来源为旧快照或非 loader 生产者）"
                        )
                        _d = _case_dtype
                    d = {"shape": inp["shape"],
                         "dtype": _d,
                         "proto_idx": _proto_idx}
                    if "data" in inp:
                        d["data"] = inp["data"]
                    # per-input value_range 透传（loader 已按 input 挂载：apply_adam_w
                    # 4 输入异值域、clipped_swiglu group_index [1,2] 均依赖此）。原实现
                    # 只拷 shape/dtype/data，丢掉 per-input range、改用 case 级单一 range
                    # 广播——多输入异值域被压扁，制造假通过。
                    if inp.get("value_range"):
                        d["value_range"] = [_norm_vr(inp["value_range"][0]),
                                            _norm_vr(inp["value_range"][1])]
                    inps.append(d)
            if not inps:
                inps = [{"shape": [1024], "dtype": "fp16"}]
            _cid = _resolve_case_id(tc, _idx)
            _case: dict = {
                "name": getattr(tc, "name", "case"),
                "inputs": inps,
                "case_id": _cid,
                # attrs 值过 _norm_vr（与上方 value_range 同源）：float inf/nan →
                # __INF__/__NAN__/__NINF__ 哨兵。否则 pprint 把 float('inf') 写成裸
                # inf token → harness import NameError（foreach_norm scalar=inf 即
                # L∞范数阶，proto y=(sum|x|^p)^(1/p) / golden torch.norm(p=scalar)，
                # 20260806-034053 deploy smoke 0/0 ran）。_norm_vr 对有限值/非数字串
                # pass-through，与 harness _cast_attr 运行时 float() 行为等价（无回归）。
                # key 消费 _validate_case_form 的过滤返回值（与输入同名的 optional
                # null 占位已丢弃）——不重读 tc.attrs 原始值（§1.15 单点过滤）。
                "attrs": {k: _norm_vr(v) for k, v in _case_attrs.items()},
            }
            serial_cases.append(_case)
        if not serial_cases:
            serial_cases = [{"name": "default",
                             "inputs": [{"shape": [1024], "dtype": "fp16"}],
                             "attrs": {}}]

        # Data init helper — select based on generator
        gen = "random_uniform"
        gen_params = {"seed": 42, "low": -1.0, "high": 1.0}
        for tc in test_cases:
            if tc.generator:
                gen = tc.generator
                if tc.generator_params:
                    gen_params = tc.generator_params
                break

        import json as _json

        def _json_to_py(obj):
            """Serialize a JSON-native structure as a valid Python literal.

            Never substring-replace (would corrupt names like 'true_div_op').
            Pre-processes special float values (inf/-inf/nan) that pformat
            emits as bare identifiers → NameError in the generated harness.
            """
            import math
            import pprint

            class _SpecialFloat:
                __slots__ = ('_repr',)
                def __init__(self, r): self._repr = r
                def __repr__(self): return self._repr

            def _walk(v):
                if isinstance(v, float):
                    if math.isinf(v):
                        return _SpecialFloat("float('inf')" if v > 0 else "float('-inf')")
                    if math.isnan(v):
                        return _SpecialFloat("float('nan')")
                if isinstance(v, dict):
                    return {kk: _walk(vv) for kk, vv in v.items()}
                if isinstance(v, (list, tuple)):
                    return type(v)(_walk(x) for x in v)
                return v

            _src = pprint.pformat(_walk(obj), width=120, sort_dicts=False)
            _src = _src.replace("'float('inf')'", "float('inf')") \
                       .replace("'float('-inf')'", "float('-inf')") \
                       .replace("'float('nan')'", "float('nan')")
            return _src

        # P79: rule × backend 默认解析（与 execute 一致；perf/直接调用路径无精度门控）。
        # merge_thresholds 在 domain/precision（torch-free，模块级 import）。
        if rule is None:
            rule = CompareRule(dtype_thresholds=merge_thresholds(None))
        if comparer is None:
            comparer = DevkitComparer()
        # proto 真值（经 debug_service 桥接）→ harness 烘焙的逐 dtype 阈值。
        _dts = rule.dtype_thresholds

        # A1: harness body extracted to _harness_template.py (string.Template).
        # Pre-compute the substitution params, then fill the template — the body
        # is raw Python source where `{}` are dict/string literals (Template only
        # expands `$var`), so harness dicts need no escaping.
        from ascendc_devkit.adapters.npu._harness_template import HARNESS_TEMPLATE
        # comparer setup is multi-line (CannbenchComparer) or empty (DevkitComparer).
        # Template inlines `$comparer_setup` right after `_cann_checker_used = False`
        # (same line); non-empty carries a leading "\n" → its own line(s), empty → "".
        _setup_lines = comparer.harness_setup_lines(rule)
        # Q8: pin per-op cann_bench ahead of site-packages so the harness
        # __import__ resolves the DEPLOYED package (with the target op), not a
        # stale global install. Inlined into the template (self-contained: also
        # covers an agent running harness.py directly, bypassing PYTHONPATH).
        per_op_python_dir = getattr(deploy_result, "python_path", "") or ""
        # P135: inline bind_golden_args source into the generated harness so the
        # golden call is name-keyed (signature-driven), not positional — fixes
        # goldens that lead with scalars (advance_step_v2(num_seqs, ..., tensors))
        # where golden(*tensors, **attrs) collided on num_seqs. Source is inlined
        # (not imported at runtime) to keep the harness dependency-free for golden
        # binding; bind_golden_args is annotation-free + stdlib-only on purpose
        # (see golden_binding.py docstring).
        _golden_bind_src = inspect.getsource(bind_golden_args)
        # proto inputs name list (完整 proto 顺序，含 optional 名字) — harness 用它
        # ① 把 null-dropped 的压实输入按 proto_idx 还原成 proto 顺序含 None 占位；
        # ② 在 golden/kernel 调用前打印 {name:(shape,dtype)} 绑定快照（可观测性）。
        # 名字是算子自带信息（TensorSpec.name），不耦合 cann-bench 代码。
        _input_names = [spec.name for spec in (operator.inputs or [])]
        # proto outputs 名字（完整 proto 顺序，含 optional）— harness 用它把
        # kernel/golden 输出右补 None 对齐到 proto 输出数（golden union 省略尾部
        # optional 时单返回），比较器原生处理双边 None 跳过/单边 fail。
        _output_names = [spec.name for spec in (operator.outputs or [])]
        # op_spec 声明的 attrs（name + default）：harness 据它把用例缺的 attr 补齐
        # （optional→None、有默认→默认值）——镜像输入侧 None 占位语义。20260810 批
        # resize_bilinear run_tests 崩（missing scale_factor）根因：m.def 声明
        # `float[2]? scale_factor`（可选类型但无默认=kwarg 必须传），harness 只传用例
        # attrs 不补 None → torch 拒。结构信号（op_spec 声明）驱动，不认算子名（§1.12）。
        _attr_specs = [
            {"name": spec.name, "default": getattr(spec, "default", None)}
            for spec in (operator.attrs or {}).values()
        ]
        # proto idx 语义（TopK 类算子）：outputs[].compare:false → ignore 列表；
        # outputs[].index_gather → 把声明的 input/value_output 名字解析为索引，
        # 生成 {输出索引: {input_idx, dim_attr, value_output_idx}} 规格。名字解析
        # 失败（引用不存在的 input/output）在加载期抛 HarnessContractError（§1.3
        # 暴露配置问题，不静默丢弃——静默会退化为逐元素比较、idx 误判回归）。
        _ignore_indices: list[int] = []
        _index_gather_specs: dict[int, dict] = {}
        for _oi, _ospec in enumerate(operator.outputs or []):
            if getattr(_ospec, "compare", None) is False:
                _ignore_indices.append(_oi)
            _ig = getattr(_ospec, "index_gather", None)
            if not _ig:
                continue
            _src_name = _ig.get("input", "")
            _val_name = _ig.get("value_output", "")
            _dim_attr = _ig.get("dim_attr", "dim")
            _in_idx = next(
                (j for j, s in enumerate(operator.inputs or []) if s.name == _src_name),
                None)
            _val_idx = next(
                (j for j, s in enumerate(operator.outputs or [])
                 if j != _oi and s.name == _val_name),
                None)
            if _in_idx is None or _val_idx is None:
                raise HarnessContractError(
                    f"outputs[{_oi}].index_gather 无法解析: input={_src_name!r} "
                    f"(inputs={[s.name for s in operator.inputs or []]}), "
                    f"value_output={_val_name!r} "
                    f"(outputs={[s.name for s in operator.outputs or []]})")
            _index_gather_specs[_oi] = {
                "input_idx": _in_idx, "dim_attr": _dim_attr,
                "value_output_idx": _val_idx,
            }
        # step-108: env 契约断言块——期望值从 deploy_result.install_path 活值单源
        # 派生（每次渲染时计算；resume 换 exec 目录后重渲染自动跟随，防 stale 假红）。
        from ascendc_devkit.infra.env_contract import (
            expected_ascend_custom_opp, harness_assert_block)
        _opp_dir = getattr(deploy_result, "install_path", "") or ""
        _env_contract_assert = (
            harness_assert_block(expected_ascend_custom_opp(_opp_dir))
            if _opp_dir else "")
        # P13 (step-116)：harness 内设备号恒 0——物理卡由 spawn env 的
        # ASCEND_RT_VISIBLE_DEVICES 携带（remap 后逻辑 0=物理卡）；脚本被人工
        # 单独执行时 NPU_ID=0 → 物理卡 0（无 pin 语境的调试语义）。
        return HARNESS_TEMPLATE.substitute(
            npu_id=0,
            env_contract_assert=_env_contract_assert,
            op_name=repr(operator.name),
            chip_version=repr(self._soc_version()),
            golden_source_path=repr(g_path),
            golden_entry=repr(g_entry),
            golden_input_type=repr(g_input_type),
            golden_precision=repr(g_precision),
            eval_seed=repr(int(g_eval_seed)),
            smoke_probe=repr(bool(smoke_probe)),
            golden_bind_helper=_golden_bind_src,
            comparer_setup=("\n" + "\n".join(_setup_lines)) if _setup_lines else "",
            per_op_python_path_insert=("\n" + "sys.path.insert(0, " + repr(per_op_python_dir) + ")  # Q8: per-op cann_bench before site-packages") if per_op_python_dir else "",
            callable_symbol=repr(symbol),
            callable_kind=repr(kind),
            test_cases_src=_json_to_py(serial_cases),
            input_names=_json_to_py(_input_names),
            output_names=_json_to_py(_output_names),
            gen=repr(gen),
            gen_low=_json_to_py(gen_params.get('low', -1.0)),
            gen_high=_json_to_py(gen_params.get('high', 1.0)),
            dtype_thresholds_src=_json_to_py(_dts),
            ignore_indices=_json_to_py(_ignore_indices),
            index_gather_specs=_json_to_py(_index_gather_specs),
            attr_specs=_json_to_py(_attr_specs),
        )


