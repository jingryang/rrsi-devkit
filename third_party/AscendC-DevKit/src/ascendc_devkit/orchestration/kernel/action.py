"""L3 Orchestration — Action types: instructions L3 issues to L5/L6."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ascendc_devkit.orchestration.kernel.gate import Gate


@dataclass(frozen=True)
class Action:
    """Base action type."""
    pass


@dataclass(frozen=True)
class Option:
    label: str
    description: str = ""


@dataclass(frozen=True)
class SpawnAgent(Action):
    agent_name: str
    prompt: str
    context: dict = field(default_factory=dict)
    skills: list[str] | None = None
    # D2 (2.1): the flat skill whose methodology this spawn delivers. Decoupled
    # from ``skills`` (the session allowlist) — codegen delivers its coding skill
    # while keeping ``skills=None`` (open allowlist) so the agent can still
    # Skill-call ascendc-dev-knowledge/ascendc-tips at runtime. The backend
    # renders delivery natively (claude ``/<skill>`` slash / opencode first-call).
    # None = deliver nothing (stage carries no assigned methodology skill).
    primary_skill: str | None = None
    max_retries: int = 3
    model: str | None = None  # per-stage override; None = use SDK default
    working_dir: Any = None  # per-spawn cwd (Path/str); None = backend instance default cwd
    repo_baseline: Any = None  # target_repo_baseline_ref for in-repo git-diff product collection
    repo_root: Any = None      # repo root for git diff scope; None = derive from working_dir
    # Display-only attribution (step-8 L4-b §P2/D8): which stage/branch this spawn
    # belongs to, so logs + transcript names can disambiguate a role agent reused
    # across stages and N parallel fork-join branches. Empty = not applicable.
    stage_name: str = ""       # current stage name (role reused across stages, D8)
    branch_label: str = ""     # fork-join branch id (tiling template name); "" = no branch
    # Proposal #1: cross-run session resume — when non-None, the backend starts
    # the spawn by resuming this claude_agent_sdk session_id (reusing the prior
    # run's reasoning memory) instead of a fresh query. Set by codegen.actions
    # from the resume sidecar (<run>/agents/<agent>.session.json — written by the
    # backend at session_id capture, survives even a hard kill). Degrades to a
    # fresh spawn inside the backend if the session expired (TTL/gone).
    resume_session_id: str | None = None
    # Part 3 (2026-08-20): resume 时作为首条消息发送的反馈/指令（替代硬编码「继续」）。
    # 深修场景（如 precision_debug diagnose→fix）resume 同一会话时，把上一轮的
    # 失败反馈作为 resume 首条消息送达，agent 无需重读设计/代码即可续改。
    # None = 沿用默认 `_RESUME_PROMPT`（"继续"）。
    resume_prompt: str | None = None


@dataclass(frozen=True)
class RunGate(Action):
    gate_name: str
    evidence: dict = field(default_factory=dict)
    gate: Any = None  # Optional[Gate] — direct reference avoids registry lookup


@dataclass(frozen=True)
class Integrate(Action):
    adapter_name: str
    action: str          # "materialize_new_operator"
    operator: Any = None
    sources: dict[str, str] | None = None
    dest_root: Path | None = None
    repo_root: Path | None = None


@dataclass(frozen=True)
class AskUserQuestion(Action):
    question: str
    options: list[Option] = field(default_factory=list)
    default_index: int | None = None
    timeout_sec: int = 0


@dataclass(frozen=True)
class NoOp(Action):
    reason: str = ""
    # P33: 显式确定性跳过声明。当 stage 因场景替代(如 external cases 替代 test_design
    # 的 LLM 产物)而 NoOp 时,output_contract.provides 在此场景本就不适用 —— 置 True 让
    # runner 把契约视为满足(早终止、不 warn、不 partial),避免"NoOp → 契约未满足 →
    # 重试 NoOp"死循环耗尽 budget 误 halt。默认 False:裸 NoOp() 仍按"未产出" warn/partial,
    # 保留"stage 本该产出却 NoOp"这类真 bug 的可观测性(见 TestMaxIterations)。
    contract_satisfied: bool = False


# —— Context Stage Actions ——

@dataclass(frozen=True)
class LoadProfile(Action):
    profile_name: str


@dataclass(frozen=True)
class InitAdapter(Action):
    profile: Any = None
    repo_root: Any = None


@dataclass(frozen=True)
class CollectReferenceCode(Action):
    ref_path: Any = None


@dataclass(frozen=True)
class ScanExistingOperator(Action):
    adapter: Any = None
    op_name: str = ""
    repo_root: Any = None


@dataclass(frozen=True)
class ReadOperatorCode(Action):
    op_identity: Any = None


@dataclass(frozen=True)
class BuildBaseline(Action):
    adapter: Any = None
    op: Any = None
    design_target_chip: str = ""


@dataclass(frozen=True)
class ReadOperatorFromPath(Action):
    path: Any = None


# —— Entry Stage Actions ——

@dataclass(frozen=True)
class ValidateInputs(Action):
    checks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CheckOperatorExists(Action):
    pass


# —— Finalize Stage Actions ——

@dataclass(frozen=True)
class UpdateDevRecord(Action):
    path: Any = None
    stage_status: str = ""
    requirement_path: Any = None
    change_summary: str = ""
    target_files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RunMeasure(Action):
    """Deterministic measurement: run a shell command (run-cases + scripts) in-process.

    Precision_debug run_tests 从 LLM agent 收敛为纯 Python 测量（§judgment-ownership N1）。
    取代 SpawnAgent：确定性跑测试+建队列，无 LLM。runner 的 _execute_actions 加分支
    执行（subprocess.run），结果写 result["measure_result"]（rc + stdout/stderr tail）。
    """
    command: str                       # shell command（shell=True 执行）
    working_dir: Any = None            # subprocess cwd（None = 继承 runner cwd）
    timeout: int | None = None         # 整条命令墙钟上限（None = 不限，依赖 harness 看门狗）


@dataclass(frozen=True)
class RemoveMemoryPointer(Action):
    op_name: str = ""
