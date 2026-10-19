"""L3 Orchestration — Perf Stage: performance benchmarking and tactical tuning."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.verification import PerformanceResult
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.orchestration.registry import register_stage
from ascendc_devkit.orchestration.kernel.action import RunGate, SpawnAgent, Action
from ascendc_devkit.orchestration.kernel.gate import Gate, GateResult
from ascendc_devkit.infra.logger import Logger
from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
from ascendc_devkit.orchestration.artifact_recovery import orphan_path_feedback
from ascendc_devkit.capabilities.agent._shared import is_infra_error_type

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.state import State

# step-106 探测结果进程级缓存（对齐 detect._PROBE_CACHE 模式）：NPU 可用性探测
# 是子进程秒级开销，PerfStage.actions 每次调用不该重复支付；进程内环境不变，
# 探一次即定论（True/False 都缓存——False 侧 raise/stub 的处置不因重探改变）。
_NPU_AVAILABLE_CACHE: bool | None = None


class PrecisionPassedGate(Gate):
    """Verify that precision verification has passed.

    D1: reads ``debug_result`` (produced by precision_debug, Option II 排 perf 前)
    rather than the deleted verify's ``precision_result``. 门槛语义不变——精度
    未通过则不测性能。
    """

    def evaluate(self, evidence: dict) -> GateResult:
        debug = evidence.get("debug_result")
        if debug is None:
            return GateResult(passed=False, reason="No debug_result available")
        if hasattr(debug, "passed") and not debug.passed:
            return GateResult(passed=False, reason="Precision debug did not pass")
        return GateResult(passed=True, reason="Precision verification passed")


def _stub_result(op_name: str) -> dict:
    """Produce a stub performance result when NPU is unavailable."""
    Logger.warn(
        f"NPU perf measurement STUBBED for '{op_name}' — "
        f"install a functional torch_npu to enable real performance measurement"
    )
    return {
        "passed": False,
        "actual_ms": 1.5,
        "max_diff": 0.0,
        "per_shape": {"stubbed": 1.5},
        "baseline_ms": 0.0,
        "bottleneck": "stubbed",
        "stubbed": True,
    }


class PerformanceGate(Gate):
    """Measure performance via NPURunner and compare against baseline.

    Evidence should contain:
      - generated_sources: source files dict
      - requirement: Requirement with performance constraints
      - npu_id: int
      - operator_spec: OperatorSpec (optional, from requirement)
      - design_target_chip: str
      - current_code: modified sources from tuning (optional, overrides generated_sources)
    """

    def evaluate(self, evidence: dict) -> GateResult:
        npu_id = evidence.get("npu_id", 0)
        requirement = evidence.get("requirement")
        design_target_chip = evidence.get("design_target_chip", "")

        # Use current_code if available (from tuning), otherwise generated_sources
        sources = evidence.get("current_code") or evidence.get("generated_sources", {})

        # Determine performance baseline from requirement constraints
        baseline_ms = 10.0
        shapes = [[1024]]
        has_perf_constraint = False
        if requirement:
            for c in requirement.constraints:
                if c.kind == "performance":
                    has_perf_constraint = True
                    baseline_ms = c.baseline_ms if c.baseline_ms is not None else 10.0
                    shapes = c.shapes if c.shapes else [[1024]]
                    break

        if not has_perf_constraint:
            return GateResult(
                passed=True,
                reason="No performance constraint — skipping perf measurement",
                metrics={"baseline_ms": 0.0, "actual_ms": 0.0},
            )

        # Execute performance measurement via NPURunner
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.requirement import TestCase

        op_spec = evidence.get("operator_spec")
        if op_spec is None and requirement:
            op_spec = requirement.op_spec

        if op_spec is None:
            op_spec = OperatorSpec(name="unknown")

        # Build test cases from shapes. Primary dtype derives from the first
        # input (the main tensor, same口径 as the harness's first input) — P69:
        # a hard-coded fp16 would mis-dtype ops whose primary input is bf16/fp32.
        # dtype may be a list (multi-dtype support); extract the first element.
        _raw_dt = (op_spec.inputs[0].dtype if op_spec.inputs else "fp16") or "fp16"
        primary_dtype = _raw_dt[0] if isinstance(_raw_dt, list) else _raw_dt
        test_cases = []
        for shape in shapes:
            test_cases.append(TestCase(
                name=f"shape_{'x'.join(str(d) for d in shape)}",
                inputs=[{"shape": shape, "dtype": primary_dtype}],
                expected={},
            ))

        enable_stubbed = evidence.get("enable_stubbed", False)
        # step-106（第五向量）：主进程构造走 probe-free 通路（构造期探测=进程内
        # import torch，纯度不变式禁止）；真实 kernel 执行本就在 runner.execute
        # 拉起的子进程 harness 内。
        runner = NPURunner.probe_free(chip_version=design_target_chip)
        try:
            result = runner.execute(op_spec, test_cases, npu_id)
        except Exception as e:
            if not enable_stubbed:
                raise
            Logger.warn(f"PerfGate: NPURunner exception ({e}), falling back to stub")
            result = _stub_result(op_name=op_spec.name if op_spec else "unknown")

        actual_ms = result.get("actual_ms", 999.0)
        passed = actual_ms <= baseline_ms

        return GateResult(
            passed=passed,
            reason=f"Perf: {actual_ms:.2f}ms {'<=' if passed else '>'} baseline {baseline_ms:.2f}ms",
            metrics={
                "actual_ms": actual_ms,
                "baseline_ms": baseline_ms,
                "per_shape": result.get("per_shape", {}),
                "bottleneck": result.get("bottleneck", "unknown"),
                "stubbed": result.get("stubbed", False),
            },
        )


@register_stage
class PerfStage(Stage):
    name = "perf"
    description = "Performance benchmarking and tactical tuning via perf-tuner agent"
    default_max_iterations = 3

    def input_contract(self) -> StageIOContract:
        # D1: requires 把 precision_result 换 debug_result（precision_debug 产）。
        return StageIOContract(
            requires=["build_result", "debug_result", "generated_sources", "requirement", "npu_id"],
            optional=["perf_baseline", "last_perf_profile"],
        )

    def output_contract(self) -> StageIOContract:
        return StageIOContract(
            provides=["performance_result", "perf_iterations", "perf_needs_redesign", "perf_profile_report"],
        )

    def gate(self):
        return PrecisionPassedGate()

    def _check_cann_available(self) -> bool:
        try:
            from ascendc_devkit.adapters.toolchain.cann import CANNToolchain
            return CANNToolchain().is_available
        except Exception:
            return False

    def _check_npu_available(self) -> bool:
        # step-106（第五向量收口）：主进程纯度不变式——NPURunner() 构造期在进程内
        # import torch/torch_npu（原生堆损坏根因）。改走 L3 子进程探测单点
        # （orchestration/npu_probe.npu_runtime_available，与 dispatcher smoke
        # 同一通路）；不可用时如实带 reason 进异常（不再 except Exception 静默
        # 折成 False——那会连纯度守卫/子进程异常一起吞掉，§1.2 可诊断性）。
        # 结果进程内缓存（_NPU_AVAILABLE_CACHE，一次定论）。
        global _NPU_AVAILABLE_CACHE
        if _NPU_AVAILABLE_CACHE is not None:
            return _NPU_AVAILABLE_CACHE
        from ascendc_devkit.orchestration.npu_probe import npu_runtime_available
        ok, reason = npu_runtime_available()
        if not ok:
            Logger.warn(f"PerfGate: NPU 可用性探测失败——{reason}")
        _NPU_AVAILABLE_CACHE = ok
        return ok

    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        has_perf_target = False
        if state.requirement:
            for c in state.requirement.constraints:
                if c.kind == "performance":
                    has_perf_target = True
                    break

        if not has_perf_target:
            return []

        npu_available = self._check_npu_available()
        if not npu_available:
            if not state.enable_stubbed:
                raise EnvironmentNotAvailableError(
                    stage_name=self.name,
                    missing="NPU runtime (torch_npu)",
                    help_hint="Install torch_npu or use --enable-stubbed to allow stub fallback",
                )
            Logger.warn("PerfStage: Performance measurement running in stubbed mode (NPU unavailable)")

        # Build performance gate evidence
        evidence = {
            "generated_sources": state.generated_sources,
            "requirement": state.requirement,
            "npu_id": state.npu_id,
            "design_target_chip": state.design_target_chip,
            "enable_stubbed": state.enable_stubbed,
        }
        if state.performance_result and not state.performance_result.passed:
            evidence["current_code"] = state.generated_sources

        actions: list[Action] = [
            RunGate(gate_name="performance", evidence=evidence),
        ]

        # Check if tactical tuning is needed
        perf_result = state.performance_result
        if perf_result and not perf_result.passed:
            if self._needs_strategic_change(perf_result, iteration):
                return actions

            # state.op_dir 兜底：op_identity 是 profile-gated（无 profile 的 run 为 None，
            # 即便 op_dir 已设）。漏兜底会让 cwd 退化到 workspace.artifacts（P66）。
            working_dir = state.op_dir or (
                state.op_identity.op_dir if state.op_identity else None)
            if working_dir is not None:
                self._materialize_inputs(state, working_dir)
            actions.append(
                SpawnAgent(
                    agent_name="perf-tuner",
                    prompt=self._build_tuning_prompt(state, iteration),
                    context={
                        "hardware": {
                            "chip_version": state.design_target_chip,
                        },
                        "last_perf_profile": state.perf_profile_report,
                    },
                    working_dir=working_dir,
                    repo_baseline=state.target_repo_baseline_ref or None,
                    repo_root=state.op_identity.repo_root
                    if state.op_identity else state.repo_root,
                ),
            )

        return actions

    def _needs_strategic_change(self, result, iteration: int) -> bool:
        if iteration >= 3 and not result.passed:
            return True
        return False

    def _materialize_inputs(self, state: State, working_dir) -> None:
        """Write current code + performance result as CWD files (F2).

        The perf agent reads the generated sources and performance data from
        files in the working dir, not from the context dict. First principle:
        the skill's inputs travel as files.
        """
        import json
        from pathlib import Path
        wd = Path(working_dir) if not isinstance(working_dir, Path) else working_dir
        wd.mkdir(parents=True, exist_ok=True)
        # Generated sources (the code under tuning)
        if state.generated_sources:
            for path, content in state.generated_sources.items():
                (wd / f"current_{Path(path).name}").write_text(
                    content, encoding="utf-8")
        # Performance result snapshot
        if state.performance_result:
            pr = state.performance_result
            payload = {"passed": pr.passed, "actual_ms": pr.actual_ms,
                       "baseline_ms": pr.baseline_ms}
            (wd / "perf_result.json").write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _build_tuning_prompt(self, state: State, iteration: int) -> str:
        sections = ["## 性能调优任务"]

        if state.requirement:
            sections.append(f"算子: {state.requirement.op_spec.name}")
            for c in state.requirement.constraints:
                if c.kind == "performance":
                    sections.append(f"目标基线: {c.baseline_ms}ms")
                    break

        if state.performance_result:
            pr = state.performance_result
            sections.append(f"当前耗时: {pr.actual_ms}ms (目标: {pr.baseline_ms}ms)")
            sections.append(f"轮次: {iteration}/{self.effective_max_iterations()}")

        if state.perf_profile_report:
            sections.append(f"上轮分析: {state.perf_profile_report}")

        if state.user_feedback:
            sections.append(f"## 上一轮反馈\n{state.user_feedback}")

        sections.append(
            "\n## 约束\n"
            "- 不能修改 TilingData 结构体\n"
            "- 不能新增 TilingKey 分支\n"
            "- 不能改变 Kernel 的 Init/CopyIn/Compute/CopyOut 流程骨架\n"
            "- 保持 32-byte 对齐\n"
            "- 不要硬编码硬件参数\n\n"
            "## 输出要求\n"
            "请分析性能瓶颈（计算密集/访存密集/流水空泡），\n"
            "实施战术优化（loop unrolling/双缓冲/数据预取/UB布局/指令调度）。\n"
            "\n## 工作目录（方案 A）\n"
            "- 当前工作目录就是算子仓内的算子目录（op_dir），用 Edit 直接修改其中的源文件。\n"
            "- 只动本算子相关文件，不要触碰 op_dir 之外或无关文件。\n"
            "- 构建中间物（*.o / *.so / build/）不算改动；改动清单由框架从 git diff 机械派生。\n"
        )

        return "\n\n".join(sections)

    def _has_perf_constraint(self, state: State) -> bool:
        """True iff the requirement declares a performance constraint.

        Mirrors the probe in actions()/PerformanceGate: with no perf constraint
        there is no tuning to do, so perf must not emit a 'tuned' re-validation
        loop-back (which would bounce back to verify indefinitely).
        """
        if not state.requirement:
            return False
        for c in state.requirement.constraints:
            if c.kind == "performance":
                return True
        return False

    def skip_reason(self, state: State) -> str | None:
        """P6-b: perf stage intentionally skipped when no performance constraint."""
        if not self._has_perf_constraint(state):
            return "no performance constraint in requirement"
        return None

    def resolve_condition(self, state: State) -> str:
        """Return condition for the centralized transition table.

        - "redesign" → design (strategic change after exhausted tuning)
        - "tuned"    → verify (tactical tuning modified code, re-validate)
        - "default"  → linear successor (integrate)
        """
        if state.perf_needs_redesign:
            return "redesign"
        # No performance constraint → no tuning happened → never emit a 'tuned'
        # re-validation loop-back. Proceed linearly to integrate. (Without this,
        # PerformanceGate returns passed=True for unconstrained ops, and with
        # perf_iterations>0 the stage would loop verify↔perf forever.)
        if not self._has_perf_constraint(state):
            return "default"
        if (state.perf_iterations > 0
                and state.performance_result
                and state.performance_result.passed):
            return "tuned"
        return "default"

    def transition(self, state: State, result: dict) -> State:
        iterations = state.perf_iterations + 1

        if not result:
            return state.with_updates(
                performance_result=PerformanceResult(passed=True),
                perf_iterations=iterations,
                perf_needs_redesign=False,
                perf_profile_report={},
            )

        gate_result = result.get("gate_result", {})
        perf_passed = gate_result.get("passed", True)
        metrics = gate_result.get("metrics", {})

        perf_result = PerformanceResult(
            passed=perf_passed,
            baseline_ms=float(metrics.get("baseline_ms", 0.0)),
            actual_ms=float(metrics.get("actual_ms", 0.0)),
            stubbed=bool(metrics.get("stubbed", False)),
        )

        needs_redesign = iterations >= self.effective_max_iterations() and not perf_passed

        if needs_redesign:
            Logger.warn(
                f"Perf Stage: {iterations} iterations without meeting baseline. "
                f"Needs strategic redesign."
            )
            return state.with_updates(
                performance_result=perf_result,
                perf_iterations=iterations,
                perf_needs_redesign=True,
                perf_profile_report=metrics,
            )

        # Handle agent tuning result
        agent_result = result.get("agent_result")
        if agent_result and agent_result.status == "ok" and agent_result.artifacts:
            updated_sources = dict(state.generated_sources or {})
            updated_sources.update(agent_result.artifacts)
            # P5：成功清 sticky 孤儿反馈（不把过期路径反馈带进后续轮）
            return state.with_updates(
                performance_result=perf_result,
                perf_iterations=iterations,
                perf_needs_redesign=False,
                perf_profile_report=metrics,
                generated_sources=updated_sources,
                user_feedback="",
            )

        # F7 残留闭合（§1.15）：agent 跑过但零产物——与 codegen 同类（代码树
        # 生产者，git-diff 收集），孤儿（transcript Write 证据在 op_dir 外）走
        # 统一 orphan_path_feedback 单点：注入路径反馈下轮重生成，不盲重试；
        # 空跑（无证据）保持原行为。迭代预算照常消耗（perf 无熔断可豁免）。
        if (agent_result is not None
                and not is_infra_error_type(agent_result.error_type)):
            working_dir = state.op_dir or (
                state.op_identity.op_dir if state.op_identity else None)
            orphan_paths, feedback = orphan_path_feedback(
                agent_result, working_dir, "perf", locator_name="op_dir")
            if orphan_paths:
                from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
                return state.with_updates(
                    performance_result=perf_result,
                    perf_iterations=iterations,
                    perf_needs_redesign=False,
                    perf_profile_report=metrics,
                    last_error=ErrorFeedback(
                        stage_name="perf",
                        error_type="artifact_misplaced",
                        message=feedback,
                    ),
                    user_feedback=feedback,
                )

        return state.with_updates(
            performance_result=perf_result,
            perf_iterations=iterations,
            perf_needs_redesign=False,
            perf_profile_report=metrics,
        )
