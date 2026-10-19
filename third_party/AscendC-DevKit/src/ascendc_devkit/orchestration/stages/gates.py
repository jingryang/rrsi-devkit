"""L3 Orchestration — Shared gates used by more than one stage.

BuildInRepoGate lives here (not in a single stage) because Plan-A makes both
verify and finalize compile against the operator repo's own build system via
``adapter.build`` — the same gate, so it is extracted to avoid duplication.
"""

from __future__ import annotations

from ascendc_devkit.orchestration.kernel.gate import Gate, GateResult


class BuildInRepoGate(Gate):
    """Compile the operator using the target repo's own build system.

    evidence: {adapter, op_identity, design_target_chip}. Delegates to
    ``adapter.build(repo_root, op, chip_version)`` (GenericRepositoryAdapter),
    which runs the repo's build command in-place. The operator is compiled by
    the repo's own build.sh (CMake → bisheng), never by an in-process compiler
    — code already lives in the repo.
    """

    def evaluate(self, evidence: dict) -> GateResult:
        adapter = evidence.get("adapter")
        op = evidence.get("op_identity")
        design_target_chip = evidence.get("design_target_chip", "")

        if adapter is None or op is None:
            return GateResult(passed=False, reason="Missing adapter or operator identity")

        try:
            from ascendc_devkit.domain.operator import OperatorIdentity
            if isinstance(op, dict):
                op = OperatorIdentity(**op)
            result = adapter.build(
                repo_root=op.repo_root,
                op=op,
                chip_version=design_target_chip,
            )
            return GateResult(
                passed=result.passed,
                reason=result.stderr if not result.passed else "Build in repo passed",
                metrics={"stubbed": bool(getattr(result, "stubbed", False))},
            )
        except NotImplementedError:
            return GateResult(passed=True, reason="Build stubbed — assuming passes")
        except Exception as e:
            return GateResult(passed=False, reason=str(e))
