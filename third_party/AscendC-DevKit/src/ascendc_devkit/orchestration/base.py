"""L3 Orchestration — Base abstractions: StageProtocol, Stage, Gate, Workflow."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ascendc_devkit.domain.contract import StageIOContract
from ascendc_devkit.domain.artifact import ArtifactContract
from .kernel.gate import Gate, GateResult  # re-export for backward compatibility

if TYPE_CHECKING:
    from .kernel.action import Action
    from .kernel.state import State


__all__ = ["StageProtocol", "Stage", "Gate", "GateResult"]


class StageProtocol(ABC):
    """Unified protocol for Stage and Workflow — both can be nested."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def input_contract(self) -> StageIOContract:
        ...

    @abstractmethod
    def output_contract(self) -> StageIOContract:
        ...

    @abstractmethod
    def actions(self, state: State, iteration: int = 1) -> list[Action]:
        ...

    @abstractmethod
    def gate(self) -> Gate | None:
        ...


class Stage(StageProtocol):
    """Single atomic execution unit in a pipeline."""

    name: str = ""
    description: str = ""
    default_max_iterations: int = 3
    # In interactive mode the runner raises the iteration ceiling to a safety
    # net (100) for stages that may need many rounds to converge (agent-driven
    # stages clarifying/redesigning). Deterministic single-pass stages (no
    # agent, default_max_iterations==1) set this False so the status bar shows
    # their real ceiling (e.g. 1/1) instead of a misleading 1/100.
    needs_iteration_safety_net: bool = True
    fail_strategy: str = "continue"  # "continue" | "halt"
    # R1 (2026-08-21, 公共 artifact-retry 抽象): agent 型 stage 的"产物契约未满足"
    # （missing_artifact / incomplete_output）走独立定向重试预算，不烧 iteration。
    # 默认 5（对齐 codegen artifact_max_retries 现值）；可由 config artifact.retry_max
    # 覆盖（effective_artifact_retry_max）。与 cut（agent 没跑完）/ infra（spawn 失败）
    # 并列——三种"失败但值得重试"各走独立预算，均不烧 iteration。
    artifact_retry_max: int = 5
    # D6 (hard-timeout): declare this stage must NOT be preempted by a passed
    # deadline — once its iteration starts, runner._check_timeout defers the
    # raise until the stage completes (transition/subprocess runs to the end).
    # For transition-based stages whose long work has no spawn (e.g. cann-bench
    # kernel_eval subprocess in transition), this is what lets the eval finish
    # even when the workflow deadline already passed at the iteration boundary.
    # Spawn-based stages don't need this (the backend hard wall handles them).
    uninterruptible: bool = False

    def gate(self) -> Gate | None:
        return None

    def effective_max_iterations(self) -> int:
        """Resolve this stage's iteration budget from central config.

        Returns the per-stage override in resources/orchestration-config.json
        (iterations.stages.<name>) when present, else the class-level
        default_max_iterations. Stages whose own logic compares against an
        iteration budget (e.g. verify's "exhausted", perf's "redesign") must
        use this rather than default_max_iterations directly, so the config
        knob governs both the runner ceiling and the stage's decision points.
        """
        from ascendc_devkit.orchestration.runtime_config import (
            stage_max_iterations,
        )
        return stage_max_iterations(self.name, self.default_max_iterations)

    def effective_artifact_retry_max(self) -> int:
        """Resolve this stage's artifact-retry budget.

        A stage that explicitly sets ``artifact_retry_max`` (class attr) wins;
        otherwise fall back to config ``artifact.retry_max`` (default 5).
        Mirrors the "stage default vs central config" tension of
        ``effective_max_iterations`` but with stage-first precedence — the
        runner's artifact-retry branch is generic; individual stages (e.g. a
        test fixture, or a stage needing a different ceiling) override locally.
        """
        if self.artifact_retry_max != 5:   # 显式设置过（非默认）
            return self.artifact_retry_max
        from ascendc_devkit.orchestration.runtime_config import (
            artifact_retry_max,
        )
        cfg = artifact_retry_max()
        return cfg or self.artifact_retry_max

    def is_artifact_retry_error(self, error_type: str) -> bool:
        """Does this error_type denote a "产物契约未满足" that deserves independent
        artifact-retry (not burning iteration)? Default: the two structural product
        failures — missing_artifact (file not landed in cwd) and incomplete_output
        (agent finished but didn't deliver the contract). Stages override to widen.

        R1: 这类失败是"确定性可纠正错误"（agent 路径幻觉/漏写），重试喂定向反馈即可修，
        与"模型迭代产出质量不达标"（烧 iteration）语义不同——后者才是迭代预算的本意。
        """
        return error_type in ("missing_artifact", "incomplete_output")

    def artifact_contract(self) -> ArtifactContract:
        """Declare the on-disk artifacts this stage produces.

        Single source of truth for the hand-off files an agent writes to the
        working directory: prompts are generated from it and parsing/validation
        read it back. Default: empty (stage produces no artifacts).
        Override in stages that spawn agents and consume their output.
        """
        return ArtifactContract()

    def validate_inputs(self, state: State) -> list[str]:
        """Content-level validation beyond presence check. Returns error messages."""
        return []

    def transition(self, state: State, result) -> State:
        """Pure function: state + action_result → new state. Override in subclasses."""
        return state

    def on_uncaught_failure(self, state: State, exc: Exception) -> State:
        """Crash bookkeeping hook (P51): transition()'s stand-in when actions() /
        transition() raised a non-control exception. Lets a stage do the
        bookkeeping transition would have done (bump its iteration counter, mark a
        failure result) so the existing resolve_condition routing + stop-loss
        engage on a crash instead of reading stale state and advancing. Default
        no-op: a stage that doesn't override keeps the crash as a plain 'failed'
        node mark (no loopback bookkeeping). Override in stages that own an
        iteration counter feeding an exhausted→halt stop-loss (e.g. verify). See
        30-verify-continue-crash-impl.md.
        """
        return state

    def teardown(self, state: State, *, interrupt_reason: str) -> State:
        """Cleanup hook on hard-timeout interruption (D5, finally semantics).

        The runner calls this after a spawn was hard-killed by the backend wall
        (``AgentResult.aborted`` set), before the stage returns. Override in
        stages that need deterministic cleanup when interrupted mid-flight —
        e.g. precision-debug diagnose 实施模式 → ``git reset --hard best_commit``
        (revert to last known-good), codegen → remove half-written temp files.

        Contract:
        - **Seconds-scale, MUST stay under 60s, MUST be idempotent.** Long work
          (e.g. cann-bench eval) is NOT teardown — it belongs to an
          ``uninterruptible`` stage (D6) instead.
        - **Best-effort**: the runner wraps this in try/except; a failure is
          logged and swallowed so teardown never blocks the graceful exit.

        ``interrupt_reason`` mirrors ``AgentResult.aborted`` (e.g.
        ``"hard_timeout"``). Default: no-op (returns state unchanged).
        """
        return state

    def outputs_delivered(self, state: State) -> bool:
        """M14（review 整改）：「本 run 的工作集已交付」判定。

        默认 = provides 全在场（非聚合字段的正确语义）。聚合字段（一个 dict
        按子键聚多个工作单元，如 tiling_results 按模板聚合）**必须** override
        降粒度——批 RESUME 部分交付时字段非 None 但本 run 的工作单元未必交付，
        裸 has_all 恒真会使 runner 的错误归一化 / artifact-retry 预算 / 终态
        分类静默失效。runner 一切「已交付」判定统一走本谓词（§1.15 单语义）。
        """
        provides = self.output_contract().provides
        return bool(provides) and state.has_all(provides)

    def is_satisfied(self, state: State) -> bool:
        """Quality self-check for early termination.

        The runner stops iterating a stage once its output_contract.provides are
        all present AND this returns True. Default True means "presence of the
        declared outputs is sufficient". Override to add a quality gate the stage
        owns — e.g. RequirementStage returns requirement_clarified so it keeps
        iterating (clarifying) until no unclear items remain, rather than
        emitting a half-done artifact for a downstream gate to reject.
        """
        return True

    def rerun_reset_fields(self) -> list[str]:
        """State fields to reset to dataclass defaults on a user-triggered rerun
        (P68 — ``--rerun-from``).

        Default: this stage's ``output_contract().provides`` — the fields it
        (re)produces each run, so a fresh rerun starts clean (e.g. resetting
        ``perf_iterations=0`` so the verify↔perf loop guard at ``perf.py:344``
        does not misfire on re-entry). Override to ALSO reset internal counters
        that gate re-entry but are NOT in the output contract — e.g. codegen's
        circuit breaker ``codegen_consecutive_failures``. The dispatcher collects
        these for every atomic node a rerun invalidates and resets them together
        (single source: the stage owns what rerun must clear). See
        ``test_rerun.py`` / P68.
        """
        return list(self.output_contract().provides)

    def rerun_reset_files(self, workspace) -> None:
        """Clear per-stage checkpoint files on disk when invalidated by ``--rerun-from``.

        Default: no-op.  Override in stages that write persistent state files
        (progress.md / coding_index.md / meta.json 等) — when such a file
        survives a rerun it can short-circuit the re-execution (e.g. a stale
        progress.md with all-✅ steps makes the s4 scheduler return DONE
        immediately, skipping the entire coding loop including VT dispatch).

        ``workspace`` is the ``Workspace`` object for the run; the stage's
        artifacts live under ``workspace.artifacts``.
        """
        pass

    def resolve_condition(self, state: State) -> str:
        """Return a condition key that the Workflow transition table uses to determine
        the next stage.

        Return "default" to use the linear successor (default behavior).
        Override to return domain-specific keys like "build_failed", "redesign", etc.
        The Workflow TRANSITION_TABLE maps (stage_name, condition) → (next_stage, route_type).
        """
        return "default"

    def skip_reason(self, state: State) -> str | None:
        """Return a reason when this stage intentionally produces no actions.

        P6-b: a stage that emits no actions AND returns a non-None skip_reason
        is logged as ``○ skipped (reason)``.  A stage that emits no actions AND
        returns None logs ``⚠ no actions (possible bug)``.  Default returns None
        — most stages are expected to produce actions.
        """
        return None

    def error_signature(self, state: State) -> str:
        """Extract a stable error fingerprint for stagnation detection.

        Override to provide domain-aware extraction (e.g., regex on compiler stderr).
        Default: last_error.message truncated to 200 chars.
        """
        if state.last_error:
            return state.last_error.message[:200]
        return ""

    def blocking_issues(self, state: State) -> list[dict]:
        """Structured blocking issues this stage wrote, for loop-back observability.

        A quality-gate stage (anchor-consistency / review / validate) overrides this to
        return the issues it recorded in State (each ``{code, severity, detail,
        target, target_template}``), so the executor can echo a deterministic
        summary to the console when it routes a loop-back (step-8 §P3/L4-b). The
        domain judgment (which issues) stays in the stage; the executor only does
        deterministic display. Default: none.
        """
        return []

    def loopback_feedback(self, state: State) -> dict | None:
        """Structured feedback for the target of a corrective loopback (P6-c).

        A quality-gate stage (anchor-consistency / validate / review) overrides this to
        return a JSON-serialisable dict (e.g. ``{"blocking_issues": [...]}``) that
        the GraphExecutor writes into ``state._loopback_feedback`` after resolving
        the loopback condition.  The target stage's ``_build_prompt`` reads this
        field and appends a ``## 上次反馈`` section so the agent sees *what*
        specifically failed rather than a generic retry context.

        Default returns None — no feedback injected.  Subclasses that route to a
        corrective target AND produce structured issues should override.
        """
        return None

    # —— Decision log helpers (loop-back context injection) ——

    def _previous_decision_section(self, state: State) -> str | None:
        """Return prompt section with the previous decision log for this stage.

        Called by _build_xxx_prompt() on loop-back to inject prior reasoning
        without resuming the full agent session. Returns None if no log exists.
        """
        log = state.decision_logs.get(self.name)
        if not log:
            return None
        import json
        parts = ["## 上一版本的决策记录（请基于此修复，避免重复已排除的方案）"]
        decisions = log.get("key_decisions", [])
        if decisions:
            parts.append("### 关键决策")
            for d in decisions:
                decision = d.get("decision", "")
                reason = d.get("reason", "")
                constraints = d.get("constraints", [])
                line = f"- {decision}: {reason}"
                if constraints:
                    line += f" (约束: {', '.join(constraints)})"
                parts.append(line)
        known = log.get("known_issues", [])
        if known:
            parts.append("### 已知问题")
            for issue in known:
                parts.append(f"- {issue}")
        assumptions = log.get("assumptions", [])
        if assumptions:
            parts.append("### 假设")
            for a in assumptions:
                parts.append(f"- {a}")
        return "\n".join(parts)

    def _decision_log_output_section(self) -> str:
        """Return the prompt section requiring the agent to output decision_log.json.

        Call this at the end of _build_xxx_prompt() for any stage that spawns
        an agent and may be a loop-back target.
        """
        return (
            "\n## 决策记录（必填）\n"
            "在完成任务后，请将 decision_log.json 写入工作目录，记录你的关键决策：\n"
            "```json\n"
            "{\n"
            '  "stage": "' + self.name + '",\n'
            '  "key_decisions": [\n'
            '    {\n'
            '      "decision": "选择双缓冲而非三缓冲",\n'
            '      "reason": "UB 仅 192KB，三缓冲需要 >256KB",\n'
            '      "constraints": ["UB_LIMIT=192KB"]\n'
            '    }\n'
            '  ],\n'
            '  "known_issues": ["kernel.cpp L45 的 stride 计算依赖运行时 shape"],\n'
            '  "assumptions": ["输入 shape 为 [N, C] 且 N%256==0"]\n'
            '}\n'
            '```\n'
            '只记录对未来修复有帮助的关键决策，不需要记录无争议的常规选择。'
        )

    # —— Unified loop-back / review helpers (step-2b §7.3/7.4) ——

    def _maybe_append_review(self, state: State, node_name: str,
                             actions: list) -> list:
        """Append an interactive review prompt after this node when configured.

        Single point where review is inserted (decision 6): no-op in
        non-interactive mode or when ``node_name`` is not a configured review
        point. Substages/groups call this at the end of actions() so the review
        policy lives in one helper + one config section, not in each stage.
        """
        from ascendc_devkit.orchestration.runtime_config import review_points
        if getattr(state, "non_interactive", False):
            return actions
        if node_name not in review_points():
            return actions
        from ascendc_devkit.orchestration.kernel.action import (
            AskUserQuestion, Option,
        )
        actions.append(AskUserQuestion(
            question=f"{node_name} 产出待审查",
            options=[Option("approve", "✅ 通过"),
                     Option("revise", "✏️ 回退修改"),
                     Option("abort", "❌ 放弃")],
            default_index=0))
        return actions

    def _loopback_context_section(self, state: State,
                                  prev_fields: list[str]) -> str:
        """Build a prompt section injecting prior products + feedback for rerun.

        The unified loop-back mechanism (decision 10): on rerun a stage gets its
        previous structured JSON (the named State fields), the user/gate feedback
        (``user_feedback``), and its previous decision log — so the skill makes an
        incremental fix without needing any ``--incremental`` mode. Returns "" when
        there is no prior context (first run).
        """
        import json
        parts: list[str] = []
        for field in prev_fields:
            val = getattr(state, field, None)
            if val:
                parts.append(
                    f"## 上一版 {field}\n```json\n"
                    f"{json.dumps(val, ensure_ascii=False, indent=2)}\n```")
        if getattr(state, "user_feedback", ""):
            parts.append(f"## 反馈\n{state.user_feedback}")
        prev = self._previous_decision_section(state)
        if prev:
            parts.append(prev)
        return "\n\n".join(parts)
