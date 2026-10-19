"""L4 Domain — Pipeline exceptions."""

from __future__ import annotations


class DecisionPendingError(Exception):
    """A decision is pending user input. Pipeline must be paused."""
    def __init__(self, question: str, options: list[str], workspace_dir: str):
        self.question = question
        self.options = options
        self.workspace_dir = workspace_dir
        super().__init__(f"Decision pending: {question}")


class PreconditionError(Exception):
    """A stage's precondition is unmet: a required upstream artifact is missing
    or an input fails content validation.

    This is a hard, non-recoverable failure for the current run — the
    dependency chain is already broken, so continuing to later stages only
    produces cascading noise. It must propagate to the dispatcher instead of
    being swallowed by the executor's per-stage tolerance.
    """
    def __init__(self, stage_name: str, reason: str):
        self.stage_name = stage_name
        self.reason = reason
        super().__init__(f"Stage '{stage_name}' precondition failed: {reason}")


class EnvironmentNotAvailableError(Exception):
    """Required hardware environment is not available and stub mode is disabled."""
    def __init__(self, stage_name: str, missing: str, help_hint: str = ""):
        self.stage_name = stage_name
        self.missing = missing
        self.help_hint = help_hint
        msg = f"Stage '{stage_name}': {missing} not available"
        if help_hint:
            msg += f". {help_hint}"
        super().__init__(msg)


class ConfigError(Exception):
    """A configuration file is present but invalid (bad JSON, wrong type, or
    out-of-range value).

    Deliberately fail-fast: an *invalid* config means the user expressed an
    intent incorrectly, and silently falling back to defaults would let them
    run for many iterations under the wrong budget before noticing. A *missing*
    config is different — that is a legitimate "use defaults" path and must NOT
    raise. The message names the file, field, and expectation so the user can
    fix it immediately rather than decoding a low-level JSONDecodeError.
    """
    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason
        super().__init__(f"Invalid config '{path}': {reason}")


class WorkflowTimeoutError(Exception):
    """Workflow-level timeout exceeded.

    Carries the configured budget and the actual elapsed time (both seconds)
    so the message is human-meaningful. ``deadline`` is retained for backward
    compatibility (it is the raw monotonic deadline, not for display).
    """
    def __init__(self, deadline: float, budget_sec: float | None = None,
                 elapsed_sec: float | None = None):
        self.deadline = deadline
        self.budget_sec = budget_sec
        self.elapsed_sec = elapsed_sec
        if budget_sec is not None and elapsed_sec is not None:
            msg = (f"Workflow timeout: exceeded {budget_sec:.0f}s budget "
                   f"(ran {elapsed_sec:.1f}s)")
        else:
            msg = "Workflow timeout exceeded"
        super().__init__(msg)


class StageTimeoutError(Exception):
    """Stage-level timeout exceeded.

    See WorkflowTimeoutError for the budget/elapsed display contract.
    """
    def __init__(self, stage_name: str, deadline: float,
                 budget_sec: float | None = None,
                 elapsed_sec: float | None = None):
        self.stage_name = stage_name
        self.deadline = deadline
        self.budget_sec = budget_sec
        self.elapsed_sec = elapsed_sec
        if budget_sec is not None and elapsed_sec is not None:
            msg = (f"Stage '{stage_name}' timeout: exceeded {budget_sec:.0f}s "
                   f"budget (ran {elapsed_sec:.1f}s)")
        else:
            msg = f"Stage '{stage_name}' timeout exceeded"
        super().__init__(msg)


class CardAcquireTimeout(Exception):
    """No NPU card could be acquired within the requested wait.

    Raised by ``NPUSlotManager.acquire`` when the card pool is exhausted and
    the caller's budget elapses: a bounded ``timeout`` wait, or ``timeout=0``
    non-blocking probe. Carries ``pool_size`` and ``waited_sec`` so the caller
    surfaces a meaningful message instead of blocking forever or silently
    degrading (§3.4 — failures must be observable, never swallowed).

    Subprocess-level card granularity (P69 stage 2) makes this the normal
    back-pressure path when concurrent NPU subprocesses exceed physical cards:
    the caller waits for a peer to release, rather than racing on a fixed card.
    """
    def __init__(self, reason: str, pool_size: int | None = None,
                 waited_sec: float | None = None):
        self.pool_size = pool_size
        self.waited_sec = waited_sec
        super().__init__(reason)


class HarnessContractError(RuntimeError):
    """Test-case morphology violation (§P5/D2=A).

    Lives in the domain layer (L4) so both the L6 adapter that raises it
    (``adapters.npu.runner._validate_case_form``) and the L1 CLI that catches
    it (``cli.commands.debug``) can import it without crossing the layer matrix
    (L1→L4 and L6→L4 are both allowed; L1→L6 is not).

    Always carries ``[PD-CONTRACT]`` so :func:`_classify_uncaught` in
    ``graph_executor.py`` routes it to ``framework`` → halt (non-fixable
    upstream defect: test_design / codegen / golden, not kernel bug).
    """
    def __init__(self, msg: str):
        if not msg.startswith("[PD-CONTRACT]"):
            msg = f"[PD-CONTRACT] {msg}"
        super().__init__(msg)
