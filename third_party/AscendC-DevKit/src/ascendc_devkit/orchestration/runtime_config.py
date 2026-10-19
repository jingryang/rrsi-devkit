"""Orchestration runtime tuning knobs.

Reads the "runner" and "iterations" sections of
resources/orchestration-config.json (the single source of truth for
orchestration tuning) so operational limits are discoverable and editable in
one place rather than buried as magic numbers in runner / stage logic.

Failure policy (fail-fast on invalid, tolerant of missing):
  - MISSING config (no file, no section, no key) → use the documented code
    default. This is a legitimate "I didn't tune anything" path.
  - INVALID config (bad JSON, wrong type, non-positive budget) → raise
    ConfigError with a message that names the file, field, and expectation.
    Silently falling back here would let a run proceed for many iterations
    under the wrong budget before the user noticed the typo.

ConfigError raised at import time is caught at the CLI entry point (cli/main.py)
and mapped to EX_CONFIG, so a broken config fails the command cleanly with a
clear message rather than a raw JSONDecodeError traceback.
"""

from __future__ import annotations

import json
from pathlib import Path

from ascendc_devkit.domain.exceptions import ConfigError

# Interactive mode never lets the user-driven loop run unbounded; this is the
# safety-net ceiling applied to agent-driven stages when the user did NOT pass
# an explicit --max-iterations. High enough to never cap a legitimate
# convergence, low enough to stop a runaway bug.
_DEFAULT_INTERACTIVE_SAFETY_NET = 100

# Defaults for the global cross-stage loop-back quotas, used when the config
# file omits them. Mirror State's field defaults so behavior is unchanged when
# no config is present.
_DEFAULT_MAX_CORRECTIVE = 5
_DEFAULT_MAX_ESCALATIONS = 2

_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "resources" / "orchestration-config.json"
)


def _load_raw() -> dict:
    """Load the whole config file. Missing file → {} (tolerated). Malformed
    JSON → ConfigError (fail-fast: the user wrote something, and it's broken)."""
    if not _CONFIG_PATH.exists():
        return {}
    try:
        text = _CONFIG_PATH.read_text()
    except OSError as e:
        raise ConfigError(str(_CONFIG_PATH), f"could not read file: {e}") from e
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ConfigError(
            str(_CONFIG_PATH),
            f"malformed JSON ({e}). Fix the syntax or remove the file to use "
            f"built-in defaults.",
        ) from e
    if not isinstance(data, dict):
        raise ConfigError(str(_CONFIG_PATH),
                          "top-level value must be a JSON object")
    return data


def _positive_int(value, field: str) -> int:
    """Validate a config value is a positive integer. Reject bool (a JSON
    `true` is an int in Python but never a valid budget) and non-positive
    values, which would silently disable a stage or quota."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be a positive integer, got {value!r}")
    if value < 1:
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be >= 1, got {value}")
    return value


def _non_negative_int(value, field: str) -> int:
    """Validate a config value is a non-negative integer (>= 0). Unlike
    iteration budgets, a timeout of 0 is a legitimate value meaning 'no
    timeout', so 0 is allowed here. Still rejects bool, non-int and negatives
    (a negative timeout is meaningless and is most likely a typo)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be a non-negative integer, got {value!r}")
    if value < 0:
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be >= 0, got {value}")
    return value


def _non_negative_float(value, field: str) -> float:
    """Validate a config value is a non-negative number (int or float, >= 0).

    Like ``_non_negative_int`` but allows fractional seconds. 0 is a legitimate
    value meaning 'disabled' for timeouts (P117 opencode turn_stall /
    message_timeout). Rejects bool, non-numbers, and negatives (a negative
    timeout is meaningless and is most likely a typo)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be a non-negative number, got {value!r}")
    if value < 0:
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be >= 0, got {value}")
    return float(value)


def _positive_float(value, field: str) -> float:
    """Validate a config value is a positive number (int or float, > 0). Reject
    bool and non-numbers. Used by the 429 backoff params (step-57), where a
    fractional base/factor is legitimate but zero/negative would disable or
    invert the backoff."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be a positive number, got {value!r}")
    if value <= 0:
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be > 0, got {value}")
    return float(value)


def _at_least_one_float(value, field: str) -> float:
    """Validate a config value is a number >= 1.0 (int or float). Used for the
    429 backoff *factor* (step-57): a factor < 1 would shrink each successive
    sleep, defeating exponential backoff. factor == 1.0 (constant base) is
    allowed."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be a number >= 1.0, got {value!r}")
    if value < 1.0:
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'{field}' must be >= 1.0, got {value}")
    return float(value)


_RAW = _load_raw()
_CONFIG = _RAW.get("runner", {})
_ITER = _RAW.get("iterations", {})

if not isinstance(_CONFIG, dict):
    raise ConfigError(str(_CONFIG_PATH), "'runner' must be a JSON object")
if not isinstance(_ITER, dict):
    raise ConfigError(str(_CONFIG_PATH), "'iterations' must be a JSON object")

_safety = _CONFIG.get("interactive_iteration_safety_net",
                      _DEFAULT_INTERACTIVE_SAFETY_NET)
INTERACTIVE_ITERATION_SAFETY_NET: int = _positive_int(
    _safety, "runner.interactive_iteration_safety_net")

# Per-stage iteration budgets (stage_name → max_iterations). Stages absent here
# fall back to their class-level default_max_iterations. Present-but-invalid
# values fail fast.
_stages_raw = _ITER.get("stages", {})
if not isinstance(_stages_raw, dict):
    raise ConfigError(str(_CONFIG_PATH), "'iterations.stages' must be a JSON object")
STAGE_ITERATIONS: dict[str, int] = {
    str(k): _positive_int(v, f"iterations.stages.{k}")
    for k, v in _stages_raw.items()
}

# Global cross-stage loop-back quotas (config defaults; an explicit CLI value
# still wins because the dispatcher only applies these when no CLI value given).
CONFIG_MAX_CORRECTIVE: int = _positive_int(
    _ITER.get("max_corrective", _DEFAULT_MAX_CORRECTIVE),
    "iterations.max_corrective")
CONFIG_MAX_ESCALATIONS: int = _positive_int(
    _ITER.get("max_escalations", _DEFAULT_MAX_ESCALATIONS),
    "iterations.max_escalations")


def stage_max_iterations(stage_name: str, code_default: int) -> int:
    """Resolve a stage's iteration budget: config override or the code default.

    Centralizes the lookup so the runner does not need to know the config file
    structure. ``code_default`` is the stage's class-level
    ``default_max_iterations``, used when the config does not list the stage.
    """
    return STAGE_ITERATIONS.get(stage_name, code_default)


# —— Per-stage timeouts (step-5b: direction C) ——

# Default per-stage timeout when the config omits timeouts.default. 0 = no
# timeout, which preserves the historical behavior (a single global
# --stage-timeout that defaults to disabled).
_DEFAULT_STAGE_TIMEOUT = 0


def _load_stage_timeouts() -> tuple[dict[str, int], int]:
    """Parse the ``timeouts`` section into (per-stage map, global default).

    Same strict-vs-tolerant policy as the iteration budgets: MISSING section /
    key → documented default; present-but-invalid (wrong type, negative, bool)
    → ConfigError. A timeout of 0 is allowed (means 'no timeout'), so this uses
    ``_non_negative_int`` rather than ``_positive_int``.
    """
    raw = _RAW.get("timeouts", {})
    if not isinstance(raw, dict):
        raise ConfigError(str(_CONFIG_PATH), "'timeouts' must be a JSON object")
    stages_raw = raw.get("stages", {})
    if not isinstance(stages_raw, dict):
        raise ConfigError(str(_CONFIG_PATH),
                          "'timeouts.stages' must be a JSON object")
    stages = {
        str(k): _non_negative_int(v, f"timeouts.stages.{k}")
        for k, v in stages_raw.items()
    }
    default = _non_negative_int(
        raw.get("default", _DEFAULT_STAGE_TIMEOUT), "timeouts.default")
    return stages, default


# Module-level so the runner reads a parsed map (mirrors STAGE_ITERATIONS).
STAGE_TIMEOUTS, CONFIG_DEFAULT_STAGE_TIMEOUT = _load_stage_timeouts()


def resolve_stage_timeout(stage_name: str, cli_override: int | None) -> int:
    """Resolve a stage's timeout (seconds): CLI explicit > config stage >
    config default > 0 (no timeout).

    ``cli_override`` is the value the user passed via ``--stage-timeout``
    (threaded through ``State.stage_timeout_sec``). ``None`` means the user did
    not pass the flag, so the config takes over. An explicit value — including
    an explicit ``0`` to disable the timeout — always wins over the config,
    matching the override semantics of ``--max-iterations`` and the second-layer
    plan (step-5-codegen-stability.md §三 direction C).
    """
    if cli_override is not None:
        return cli_override
    return STAGE_TIMEOUTS.get(stage_name, CONFIG_DEFAULT_STAGE_TIMEOUT)


# —— NPU hardware-probe timeout (driver-hang bound) ——


def _load_hw_probe_timeout() -> float:
    """Parse ``timeouts.hw_probe_sec`` — the bound on the NPU hardware probe.

    Same strict-vs-tolerant policy as the iteration budgets / stage timeouts:
    MISSING key → the documented code default; present-but-invalid (wrong type,
    non-positive, bool) → ConfigError. Must be > 0: unlike a stage timeout (where
    0 means 'disabled'), a probe bound of 0 would time out instantly — there is
    no 'disabled' semantic for the probe (skip it with ``--assume-chip`` instead).

    The default is imported from the L4 adapter (single source —
    ``detect._DEFAULT_HW_PROBE_TIMEOUT``) rather than duplicated here, so the
    bound and its fallback can't drift.
    """
    from ascendc_devkit.adapters.npu.detect import _DEFAULT_HW_PROBE_TIMEOUT
    raw_timeouts = _RAW.get("timeouts", {})
    if not isinstance(raw_timeouts, dict) or "hw_probe_sec" not in raw_timeouts:
        return _DEFAULT_HW_PROBE_TIMEOUT
    value = raw_timeouts["hw_probe_sec"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(str(_CONFIG_PATH),
                          "timeouts.hw_probe_sec must be a number (seconds)")
    if value <= 0:
        raise ConfigError(str(_CONFIG_PATH),
                          "timeouts.hw_probe_sec must be > 0 "
                          "(use --assume-chip to skip the probe, not 0)")
    return float(value)


# Module-level so callers read a parsed value (mirrors STAGE_TIMEOUTS).
HW_PROBE_TIMEOUT_SEC = _load_hw_probe_timeout()


def hw_probe_timeout_sec() -> float:
    """Bound (seconds) for the NPU hardware probe — driver-hang protection.

    From orchestration-config.json ``timeouts.hw_probe_sec``; defaults to
    ``detect._DEFAULT_HW_PROBE_TIMEOUT`` when unset. The L3 callers
    (codegen.validate_inputs / Deployer.deploy / dispatcher auto-detect) thread
    this into ``detect_chip_version`` since the L4 adapter cannot import this L3
    module (§1.1 layering).
    """
    return HW_PROBE_TIMEOUT_SEC


# —— precision_debug loop knobs (global defaults; per-run override via control.json) ——
#
# Single config section so all precision_debug tuning lives in one place. These
# are GLOBAL DEFAULTS. Per-run override: init-checkpoint.py writes them into
# control.json on first run (from these values); the substage reads control.json
# (per-run wins, including a hand-edited value), falling back to these accessors
# only when the control.json field is absent (defensive — half-written file).
#
# Each knob: MISSING (no key / no section / non-dict section) → documented
# default; present-but-invalid (wrong type, non-positive, bool, float) →
# ConfigError naming the field. Integer only (a fractional budget/quota is a
# likely typo). Must be > 0 — no 'disabled' semantic.
_DEFAULT_PRECISION_MAX_ITERATIONS = 15        # big-loop (run_tests↔diagnose) round ceiling
_DEFAULT_PRECISION_MAX_CORRECTIVE_CYCLES = 6  # A5 diagnose↔printf / diagnose↔comment_bisect (precision_debug_a5 包消费)
_DEFAULT_PRECISION_MAX_ATTEMPTS_PER_CASE = 8   # per-case stop-loss
_DEFAULT_PRECISION_TIME_BUDGET_S = 12000       # wall-clock budget
_DEFAULT_PRECISION_FRAMEWORK_MAX_CORRECTIVE = 30  # framework corrective safety net


def _precision_knob(key: str, default: int, variant: str | None = None) -> int:
    """Parse one precision_debug knob, with optional A3/A5 split.

    Section resolution (first match wins):
      1. ``precision_debug_{variant}`` when ``variant`` is given — the
         variant-specific override section;
      2. the shared ``precision_debug`` section — A3/A5 common defaults;
    MISSING (no key in either applicable section) → ``default``;
    present-but-invalid → ConfigError naming the field.
    Each section must be a JSON object (non-dict → ConfigError, fail-fast §1.3).
    Reads the live ``_RAW`` (mirrors ``_load_timeouts``) so unit tests can
    mutate ``rc._RAW`` and exercise MISSING / valid / invalid paths.
    """
    sections: list[tuple[str, dict]] = []
    if variant:
        vsection = _RAW.get(f"precision_debug_{variant}", {})
        if not isinstance(vsection, dict):
            raise ConfigError(str(_CONFIG_PATH),
                              f"'precision_debug_{variant}' must be a JSON object")
        sections.append((f"precision_debug_{variant}", vsection))
    shared = _RAW.get("precision_debug", {})
    if not isinstance(shared, dict):
        raise ConfigError(str(_CONFIG_PATH),
                          "'precision_debug' must be a JSON object")
    sections.append(("precision_debug", shared))
    for name, section in sections:
        if key in section:
            return _positive_int(section[key], f"{name}.{key}")
    return default


# Module-level so callers read a parsed value (mirrors HW_PROBE_TIMEOUT_SEC).
# A3 is the legacy default variant; the shared `precision_debug` section holds
# common defaults, `precision_debug_a3` / `precision_debug_a5` override them.
PRECISION_MAX_ITERATIONS = _precision_knob(
    "max_iterations", _DEFAULT_PRECISION_MAX_ITERATIONS, "a3")
PRECISION_MAX_CORRECTIVE_CYCLES = _precision_knob(
    "max_corrective_cycles", _DEFAULT_PRECISION_MAX_CORRECTIVE_CYCLES, "a3")
PRECISION_MAX_ATTEMPTS_PER_CASE = _precision_knob(
    "max_attempts_per_case", _DEFAULT_PRECISION_MAX_ATTEMPTS_PER_CASE, "a3")
PRECISION_DEBUG_TIME_BUDGET_S = _precision_knob(
    "time_budget_sec", _DEFAULT_PRECISION_TIME_BUDGET_S, "a3")
PRECISION_DEBUG_MAX_CORRECTIVE = _precision_knob(
    "max_corrective", _DEFAULT_PRECISION_FRAMEWORK_MAX_CORRECTIVE, "a3")


def _precision_knob_variant(variant: str, key: str, default: int) -> int:
    """Parse one knob from the ``precision_debug_{variant}`` override section,
    falling back to the shared ``precision_debug`` section, then ``default``."""
    return _precision_knob(key, default, variant)


def precision_debug_max_iterations() -> int:
    """Max rounds of the precision_debug big loop (run_tests→diagnose(实施)→…).
    From ``precision_debug.max_iterations``; per-run override via control.json."""
    return PRECISION_MAX_ITERATIONS


def precision_debug_max_corrective_cycles() -> int:
    """Max corrective cycles (A5 diagnose↔printf / diagnose↔comment_bisect,
    bypassing run_tests; consumed by the precision_debug_a5 package). From
    ``precision_debug.max_corrective_cycles``; per-run override via control.json."""
    return PRECISION_MAX_CORRECTIVE_CYCLES


def precision_debug_max_attempts_per_case() -> int:
    """Max fix attempts per failed case (per-case stop-loss). From
    ``precision_debug.max_attempts_per_case``; per-run override via control.json
    (single top-level value applies to all cases)."""
    return PRECISION_MAX_ATTEMPTS_PER_CASE


def precision_debug_time_budget_sec() -> int:
    """Wall-clock budget (seconds) for the precision_debug checkpoint loop.
    From ``precision_debug.time_budget_sec``; defaults to 12000. First
    run_test starts the timer; each run_test checks it; exceeding → exit (route
    ``exhausted``) and converge to the best-passed-count commit. Per-run override
    via control.json."""
    return PRECISION_DEBUG_TIME_BUDGET_S


# —— A5 (Regbase 6-stage) 独立配置 ——
# A5 与 A3 共读 ``precision_debug`` 共享节 + ``precision_debug_a5`` 覆盖节
# （variant 解析见 _precision_knob）。A5 专属轮次上限（vf / vector_error /
# op_plugin rounds 与 abort 阈值）只存在于 ``precision_debug_a5`` 节，fallback
# 到共享节再 fallback 到代码默认。
_DEFAULT_PRECISION_A5_MAX_ITERATIONS = 15
_DEFAULT_PRECISION_A5_MAX_ATTEMPTS_PER_CASE = 10
_DEFAULT_PRECISION_A5_ABORT_EXHAUST_THRESHOLD = 10
_DEFAULT_PRECISION_A5_MAX_VF_ROUNDS = 10
_DEFAULT_PRECISION_A5_MAX_VECTOR_ERROR_ROUNDS = 10
_DEFAULT_PRECISION_A5_MAX_OP_PLUGIN_ROUNDS = 10


def precision_debug_a5_max_iterations() -> int:
    """A5 big-loop round ceiling. From ``precision_debug_a5.max_iterations``
    (fallback ``precision_debug.max_iterations``); default 15."""
    return _precision_knob_variant(
        "a5", "max_iterations", _DEFAULT_PRECISION_A5_MAX_ITERATIONS)


def precision_debug_a5_max_attempts_per_case() -> int:
    """A5 per-case stop-loss. From ``precision_debug_a5.max_attempts_per_case``
    (fallback ``precision_debug.max_attempts_per_case``); default 10."""
    return _precision_knob_variant(
        "a5", "max_attempts_per_case", _DEFAULT_PRECISION_A5_MAX_ATTEMPTS_PER_CASE)


def precision_debug_a5_abort_exhaust_threshold() -> int:
    """A5 consecutive-abort anneal threshold. From
    ``precision_debug_a5.abort_exhaust_threshold`` (fallback shared);
    default 10. After this many consecutive aborted spawns the stage escalates
    ``abort_exhausted`` instead of re-spawning forever."""
    return _precision_knob_variant(
        "a5", "abort_exhaust_threshold", _DEFAULT_PRECISION_A5_ABORT_EXHAUST_THRESHOLD)


def precision_debug_a5_max_vf_rounds() -> int:
    """A5 vf_test round ceiling. From ``precision_debug_a5.max_vf_rounds``;
    default 10."""
    return _precision_knob_variant(
        "a5", "max_vf_rounds", _DEFAULT_PRECISION_A5_MAX_VF_ROUNDS)


def precision_debug_a5_max_vector_error_rounds() -> int:
    """A5 vector_error_debug round ceiling. From
    ``precision_debug_a5.max_vector_error_rounds``; default 10."""
    return _precision_knob_variant(
        "a5", "max_vector_error_rounds", _DEFAULT_PRECISION_A5_MAX_VECTOR_ERROR_ROUNDS)


def precision_debug_a5_max_op_plugin_rounds() -> int:
    """A5 op_plugin_debug round ceiling. From
    ``precision_debug_a5.max_op_plugin_rounds``; default 10."""
    return _precision_knob_variant(
        "a5", "max_op_plugin_rounds", _DEFAULT_PRECISION_A5_MAX_OP_PLUGIN_ROUNDS)


def precision_debug_abort_exhaust_threshold() -> int:
    """A3 consecutive-abort anneal threshold. From
    ``precision_debug_a3.abort_exhaust_threshold`` (fallback shared);
    default 10. Mirrors the A5 ``_resolve_abort_condition`` guard for the A3
    Membase loop (RunTestsSubstage._resolve_abort_condition)."""
    return _precision_knob_variant(
        "a3", "abort_exhaust_threshold", _DEFAULT_PRECISION_A5_ABORT_EXHAUST_THRESHOLD)


# —— codegen build-retry ceiling (阶段3 framework-driven build-retry, 方案 Z) ——
# Membase build-retry 上限：到上限 D4 逃生（带 smoke_passed=False 交下游，不 halt）。
# MUST ≤ iterations.stages.codegen（runner 机械上限），见 orchestration-config.json codegen._comment。
_DEFAULT_CODEGEN_BUILD_MAX_RETRIES = 1000


def _codegen_build_max_retries_raw() -> int:
    section = _RAW.get("codegen", {})
    if not isinstance(section, dict) or "build_max_retries" not in section:
        return _DEFAULT_CODEGEN_BUILD_MAX_RETRIES
    return _positive_int(section["build_max_retries"], "codegen.build_max_retries")


CODEGEN_BUILD_MAX_RETRIES = _codegen_build_max_retries_raw()  # 加载期求值（§1.3 校验）


def codegen_build_max_retries() -> int:
    """Membase codegen framework-driven build-retry ceiling (codegen.build_max_retries).
    On exhaustion → D4 escape (carries smoke_passed=False downstream, no halt). MUST be ≤
    iterations.stages.codegen (runner mechanical ceiling — build-retry consumes one
    runner iteration per round; see orchestration-config.json codegen._comment)."""
    return CODEGEN_BUILD_MAX_RETRIES


# —— codegen artifact-retry ceiling (manifest/plugin 不完整重试) ——
# Membase artifact-retry 上限：codegen_manifest 非契约（缺 callable_target/inputs/outputs 等，
# 且 callable_target 无法从 plugin 构造性派生兜底时）的定向重试上限。
# 到上限 halt（无可调用算子可交下游 triage，非 build-retry 的 D4）。MUST ≤ iterations.stages.codegen。
_DEFAULT_CODEGEN_ARTIFACT_MAX_RETRIES = 5


def _codegen_artifact_max_retries_raw() -> int:
    section = _RAW.get("codegen", {})
    if not isinstance(section, dict) or "artifact_max_retries" not in section:
        return _DEFAULT_CODEGEN_ARTIFACT_MAX_RETRIES
    return _positive_int(section["artifact_max_retries"], "codegen.artifact_max_retries")


CODEGEN_ARTIFACT_MAX_RETRIES = _codegen_artifact_max_retries_raw()  # 加载期求值（§1.3 校验）


def artifact_retry_max() -> int:
    """R1 (2026-08-21): 公共 artifact-retry ceiling (artifact.retry_max).

    所有 agent 型 stage 的"产物契约未满足"（missing_artifact / incomplete_output）
    独立重试预算——不烧 iteration。默认 5（对齐 codegen artifact_max_retries）。
    Stage.effective_artifact_retry_max() 返回本值；缺失返回 0（调用方回退 stage 类
    默认 artifact_retry_max=5）。§1.3 加载期校验：非法值加载即 ConfigError。
    """
    section = _RAW.get("artifact", {})
    if not isinstance(section, dict) or "retry_max" not in section:
        return 0
    return _positive_int(section["retry_max"], "artifact.retry_max")


def codegen_artifact_max_retries() -> int:
    """Membase codegen artifact-retry ceiling (codegen.artifact_max_retries).

    Max targeted re-spawns when codegen_manifest is non-conforming (missing required
    fields that cannot be constructively derived from the op_plugin registration).
    On exhaustion → halt (no callable artifact to carry downstream, unlike build-retry's
    D4 — deferring to precision_debug scope_guard would only postpone an inevitable halt,
    §1.10). Default 5: a missing-manifest-field defect is binary/simpler than the open
    space of compile errors, so 5 targeted attempts is sufficient before human triage.
    MUST be ≤ iterations.stages.codegen (each retry consumes one runner iteration)."""
    return CODEGEN_ARTIFACT_MAX_RETRIES


def precision_debug_max_corrective() -> int:
    """Framework corrective quota for the whole precision_debug group.
    From ``precision_debug.max_corrective``; defaults to 30. This is a safety
    backstop. Set high enough that the sub-stage's own exhaustion signal is
    always reached first; this quota only prevents genuine runaway."""
    return PRECISION_DEBUG_MAX_CORRECTIVE


# —— NPU test harness subprocess watchdog (run_tests timeout adaptation) ——
#
# The historical hardcoded 120s watchdog on the test harness subprocess is now
# configurable: ``timeouts.harness_sec`` is the default; precision_debug's
# build-failed-case-queue.py amplifies it (×4 per level) up to
# ``precision_debug.harness_timeout_max_sec`` for large-shape cases and persists
# the amplified value into control.json.harness_timeout_sec (per-run override —
# the debug_service reads control.json first, falling back to this default).
# See docs/plan/harness-timeout-adaptive/.
_DEFAULT_HARNESS_TIMEOUT_SEC = 120.0        # matches the historical hardcoded 120s
_DEFAULT_HARNESS_TIMEOUT_MAX_SEC = 1200.0   # large-shape amplification cap (user: 1200)


def _load_harness_timeout() -> float:
    """Parse ``timeouts.harness_sec`` — the test harness subprocess watchdog.

    Same strict-vs-tolerant policy as the other knobs: MISSING key → the
    documented default (120s); present-but-invalid (wrong type, bool, ≤0) →
    ConfigError naming the field. Must be > 0: a 0-second watchdog would kill
    every harness subprocess instantly (there is no 'disabled' semantic — the
    caller passes an explicit value when it wants a bound).
    """
    raw = _RAW.get("timeouts", {})
    if not isinstance(raw, dict) or "harness_sec" not in raw:
        return _DEFAULT_HARNESS_TIMEOUT_SEC
    value = raw["harness_sec"]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(str(_CONFIG_PATH),
                          "timeouts.harness_sec must be a number (seconds)")
    if value <= 0:
        raise ConfigError(str(_CONFIG_PATH),
                          "timeouts.harness_sec must be > 0 "
                          "(a 0s watchdog kills every harness subprocess)")
    return float(value)


# Module-level so callers read a parsed value (mirrors HW_PROBE_TIMEOUT_SEC).
HARNESS_TIMEOUT_SEC = _load_harness_timeout()
# Max amplification cap lives in the precision_debug section (per-run override
# via control.json is not needed — the cap bounds the amplification itself).
HARNESS_TIMEOUT_MAX_SEC = float(_precision_knob(
    "harness_timeout_max_sec", _DEFAULT_HARNESS_TIMEOUT_MAX_SEC))


def harness_timeout_sec() -> float:
    """Default test harness subprocess watchdog (seconds).

    From ``timeouts.harness_sec``; defaults to 120 (the historical hardcoded
    value). debug_service.run_cases resolves the final timeout as
    ``control.json.harness_timeout_sec`` (per-run amplification) when present,
    else this default.
    """
    return HARNESS_TIMEOUT_SEC


# 框架自有 sidecar 文件名（agent 的 control.json 重写碰不到）：确定性脚本
# （build-failed-case-queue.py）把放大后的 harness_timeout_sec 写进
# ``<debug_dir>/HARNESS_TIMEOUT_SIDECAR_NAME``，debug_service 读它兜底放大值——
# 超时字段是代码派生（§2.9 构造性），不靠 agent 在 control.json 里保留。
HARNESS_TIMEOUT_SIDECAR_NAME = "harness_timeout.fw.json"


def read_harness_timeout_sidecar(debug_dir) -> float | None:
    """Read the framework-owned amplified timeout sidecar (seconds), or None.

    ``debug_dir`` is the precision_debug artifacts dir for the operator
    (``<artifacts>/debug/<op>``); the sidecar lives alongside ``control.json``.

    Read failure (parse error / non-positive value) → ``None`` (fall back to the
    default, never block the test) BUT logs a warning — a silently-corrupted
    sidecar would otherwise drop the amplified timeout to the default 120 with
    no observable signal (§1.2 可诊断). A missing file is normal (never
    amplified) and does not warn.
    """
    from ascendc_devkit.infra.logger import Logger
    try:
        from pathlib import Path
        p = Path(debug_dir) / HARNESS_TIMEOUT_SIDECAR_NAME
        if not p.exists():
            return None
        import json as _json
        data = _json.loads(p.read_text(encoding="utf-8"))
        v = data.get("harness_timeout_sec") if isinstance(data, dict) else None
        if isinstance(v, (int, float)) and v > 0:
            return float(v)
        Logger.warn(
            f"harness timeout sidecar {p} unreadable/invalid value {v!r} — "
            f"falling back to default (amplified timeout lost)")
    except Exception as e:  # noqa: BLE001 — 读失败用默认，绝不阻断测试
        Logger.warn(f"harness timeout sidecar read failed: {e} — falling back to default")
    return None


def harness_timeout_max_sec() -> float:
    """Large-shape timeout amplification cap (seconds).

    From ``precision_debug.harness_timeout_max_sec``; defaults to 1200. The
    queue script doubles ``harness_timeout_sec`` per amplification level up to
    this cap. Bounded: only large-shape timeouts amplify; a deadlock waits at
    most this long.
    """
    return HARNESS_TIMEOUT_MAX_SEC


# —— Design review points + group quotas (step-2b §7.3/7.5) ——

# Default review points = the two design group boundaries. A run with only the
# concept-design group (SE workflow) naturally triggers just the general-design
# review. An empty config list is legitimate ("review nothing").
_DEFAULT_REVIEW_POINTS = {"general-design", "detailed-design"}
_DEFAULT_GROUP_QUOTA = {"max_corrective": 3, "max_escalations": 1}

_REVIEW = _RAW.get("review", {})
if not isinstance(_REVIEW, dict):
    raise ConfigError(str(_CONFIG_PATH), "'review' must be a JSON object")

_points_raw = _REVIEW.get("points", None)
if _points_raw is None:
    _REVIEW_POINTS: set[str] = set(_DEFAULT_REVIEW_POINTS)
elif isinstance(_points_raw, list):
    _REVIEW_POINTS = {str(p) for p in _points_raw}
else:
    raise ConfigError(str(_CONFIG_PATH), "'review.points' must be a JSON array")


def review_points() -> set[str]:
    """Node names after which an interactive review prompt is inserted.

    Reads ``review.points`` from orchestration-config.json. Missing → the two
    design group boundaries; an explicit empty list → no review points.
    """
    return set(_REVIEW_POINTS)


def design_group_quota(group_key: str) -> dict:
    """Loop-back quota for a design group's own scope.

    ``group_key`` is the config key ("general_design_group" /
    "detailed_design_group"). Missing → a documented default. Present-but-invalid
    budgets fail fast (same policy as stage budgets).
    """
    raw = _ITER.get(group_key)
    if raw is None:
        return dict(_DEFAULT_GROUP_QUOTA)
    if not isinstance(raw, dict):
        raise ConfigError(str(_CONFIG_PATH),
                          f"'iterations.{group_key}' must be a JSON object")
    return {
        "max_corrective": _positive_int(
            raw.get("max_corrective", _DEFAULT_GROUP_QUOTA["max_corrective"]),
            f"iterations.{group_key}.max_corrective"),
        "max_escalations": _positive_int(
            raw.get("max_escalations", _DEFAULT_GROUP_QUOTA["max_escalations"]),
            f"iterations.{group_key}.max_escalations"),
    }


# —— Agent spawn resilience (step-5a: B2-resume retry) ——

# Defaults for the resume-retry gates. On a transient SSE error (e.g. the
# proxy's "Content block not found" block-index off-by-one), the SDK backend
# resumes the crashed session by session_id rather than failing the whole
# spawn. Two gates bound the loop: a total-budget gate (max_retries) and a
# no-progress gate (max_no_progress consecutive resumes that add no new text,
# tool use, or product files). See step-5-codegen-stability.md §三 B2-resume.
_DEFAULT_RESUME_MAX_RETRIES = 10
_DEFAULT_RESUME_MAX_NO_PROGRESS = 3

# step-57 (P80): 429 burst rate-limit backoff-resume budget. A 429 is a soft
# server rejection where the session survives; the backend sleeps (exponential
# backoff) then resumes the same session with "继续". These bound that loop
# INDEPENDENTLY of the SSE resume gates above (a rejected 429 turn adds no
# progress and would instantly trip resume_max_no_progress — wrong gate). The
# total-time cap is the hard-quota stop-loss: a true (non-burst) quota simply
# exhausts it and halts with an actionable reason rather than sleeping for
# hours. See 57-burst-429-resume-{analysis,impl}.md.
_DEFAULT_RATE_LIMIT_MAX_RETRIES = 6
_DEFAULT_RATE_LIMIT_BACKOFF_BASE_S = 30.0
_DEFAULT_RATE_LIMIT_BACKOFF_FACTOR = 2.0
_DEFAULT_RATE_LIMIT_BACKOFF_MAX_TOTAL_S = 600.0

# P131c (trial-20260730): cross-run backoff-resume budget for a TRANSIENT infra
# abort (the turn-stall / keepalive / hard-timeout watchdog killed a live-but-
# stalled spawn — ``AgentResult.aborted`` set). Distinct from the in-session 429
# budget above (that re-POSTs to the SAME session; this RE-SPAWNS the stage to
# sample a FRESH gateway window, because the watchdog already killed the serve).
# Distinct too from permanent infra (401/config markers, aborted empty) which
# still halts immediately (P116) — no window resampling can fix a bad
# credential. A modest base (early retry, per the user's "不如早重试": a lost
# message / server blip is often gone by the next window) with a small retry
# count; the total-time cap is the stop-loss so a truly dead gateway exhausts
# and halts with an actionable reason rather than sleeping for hours. Computed
# via the shared ``compute_backoff_seconds`` (§2.5 single source).
# 退化 spawn 设计（docs/plan/turn-stall-resume-escalation/）：turn-stall 后先原地 resume
# （续同一 session，满窗 turn_stall_s），连续失败 resume_attempts 次后退化 spawn
# （清 sidecar + fresh 新 session）。须 < infra_retry_max_retries，否则预算先耗尽、
# 退化永远轮不到（§1.3 加载期交叉校验）。默认 4 = resume 3 次 + 1 发 fresh。
_DEFAULT_INFRA_RETRY_MAX_RETRIES = 4
_DEFAULT_INFRA_BACKOFF_BASE_S = 20.0
_DEFAULT_INFRA_BACKOFF_FACTOR = 2.0
_DEFAULT_INFRA_BACKOFF_MAX_TOTAL_S = 600.0
_DEFAULT_RESUME_ATTEMPTS = 3

# —— retry_budgets 统一组（§1.15，2026-08-21 方案 B）——
# 『有界公平机会→升级』类阈值收敛为单一配置组，不散点写死在各模块/类。
# 默认值 = 迁移前各散点的原值（cut_streak=5 / codegen 熔断=5 / 孤儿豁免窗=2），
# 无 config 时行为不变。
_DEFAULT_CUT_STREAK_THRESHOLD = 5
_DEFAULT_CONSECUTIVE_FAILURES_MAX = 5
_DEFAULT_ORPHAN_EXEMPT_WINDOW = 2
# P6（step-110）硬切分类判据：末次 thinking 增量距截断 ≤ 此秒数 = 思考流仍
# 活跃（网关输出墙形态）。实证默认：批 49134b 34/34 硬切 gap ≤0.58s、中位
# 0.12s；网关 flush 粒度影响观测值，故可调（§1.15 进统一组不散点写死）。
_DEFAULT_THINKING_ACTIVE_GAP_S = 0.6


def retry_budgets() -> dict:
    """Cross-stage unified retry-budget thresholds.

    Reads the ``retry_budgets`` section of orchestration-config.json at call
    time (same strict-vs-tolerant pattern as ``infra_backoff``): MISSING
    section/keys → documented defaults (5 / 5 / 2 / 0.6); present-but-invalid →
    ``ConfigError`` naming the field.

    Members:
      - cut_streak_threshold      runner 连续 silent-cut 放弃 cut-recovery 阈值
      - consecutive_failures_max  codegen 熔断阈值（空跑/孤儿超豁免后消耗）
      - orphan_exempt_window      连续孤儿豁免熔断的公平窗口（F8）
      - thinking_active_gap_s     硬切分类判据（P6）：末次 thinking 增量距截断
                                  的 gap 上限（秒）——网关 flush 行为参数
    """
    raw = _RAW.get("retry_budgets", {})
    if not isinstance(raw, dict):
        raise ConfigError(str(_CONFIG_PATH),
                          "'retry_budgets' must be a JSON object")
    return {
        "cut_streak_threshold": _positive_int(
            raw.get("cut_streak_threshold", _DEFAULT_CUT_STREAK_THRESHOLD),
            "retry_budgets.cut_streak_threshold"),
        "consecutive_failures_max": _positive_int(
            raw.get("consecutive_failures_max",
                    _DEFAULT_CONSECUTIVE_FAILURES_MAX),
            "retry_budgets.consecutive_failures_max"),
        "orphan_exempt_window": _positive_int(
            raw.get("orphan_exempt_window", _DEFAULT_ORPHAN_EXEMPT_WINDOW),
            "retry_budgets.orphan_exempt_window"),
        "thinking_active_gap_s": _positive_float(
            raw.get("thinking_active_gap_s", _DEFAULT_THINKING_ACTIVE_GAP_S),
            "retry_budgets.thinking_active_gap_s"),
    }


def resume_limits() -> dict:
    """Resume-retry gate thresholds for agent spawns.

    Reads the ``agent`` section of orchestration-config.json at call time
    (same pattern as design_group_quota / review_points). Missing section or
    keys → documented defaults (max_retries=10, max_no_progress=3).
    Present-but-invalid values fail fast (ConfigError), same policy as the
    iteration budgets.
    """
    raw = _RAW.get("agent", {})
    if not isinstance(raw, dict):
        raise ConfigError(str(_CONFIG_PATH), "'agent' must be a JSON object")
    return {
        "max_retries": _positive_int(
            raw.get("resume_max_retries", _DEFAULT_RESUME_MAX_RETRIES),
            "agent.resume_max_retries"),
        "max_no_progress": _positive_int(
            raw.get("resume_max_no_progress", _DEFAULT_RESUME_MAX_NO_PROGRESS),
            "agent.resume_max_no_progress"),
        # step-57: 429 burst backoff-resume budget (independent of the two
        # gates above). Keys are optional; absent → documented defaults.
        "rate_limit_max_retries": _positive_int(
            raw.get("rate_limit_max_retries", _DEFAULT_RATE_LIMIT_MAX_RETRIES),
            "agent.rate_limit_max_retries"),
        "rate_limit_backoff_base_s": _positive_float(
            raw.get("rate_limit_backoff_base_s",
                    _DEFAULT_RATE_LIMIT_BACKOFF_BASE_S),
            "agent.rate_limit_backoff_base_s"),
        "rate_limit_backoff_factor": _at_least_one_float(
            raw.get("rate_limit_backoff_factor",
                    _DEFAULT_RATE_LIMIT_BACKOFF_FACTOR),
            "agent.rate_limit_backoff_factor"),
        "rate_limit_backoff_max_total_s": _positive_float(
            raw.get("rate_limit_backoff_max_total_s",
                    _DEFAULT_RATE_LIMIT_BACKOFF_MAX_TOTAL_S),
            "agent.rate_limit_backoff_max_total_s"),
    }


def infra_backoff() -> dict:
    """P131c: cross-run backoff-resume budget for transient infra aborts.

    Reads the ``agent`` section of orchestration-config.json at call time (same
    pattern as ``resume_limits``). Missing keys → documented defaults
    (max_retries=4, base=20s, factor=2, max_total=600s); present-but-invalid →
    ``ConfigError`` naming the field. ``max_retries`` bounds the re-spawn count;
    ``max_total`` bounds cumulative backoff sleep (stop-loss on a dead gateway).
    """
    raw = _RAW.get("agent", {})
    if not isinstance(raw, dict):
        raise ConfigError(str(_CONFIG_PATH), "'agent' must be a JSON object")
    max_retries = _positive_int(
        raw.get("infra_retry_max_retries", _DEFAULT_INFRA_RETRY_MAX_RETRIES),
        "agent.infra_retry_max_retries")
    resume_attempts = _positive_int(
        raw.get("resume_attempts", _DEFAULT_RESUME_ATTEMPTS),
        "agent.resume_attempts")
    # 加载期交叉校验（§1.3）：resume_attempts 须 < max_retries，预算内才留得下
    # 至少一发 fresh 退化。否则 N 太大时预算先耗尽、退化永远轮不到。
    if resume_attempts >= max_retries:
        raise ConfigError(
            str(_CONFIG_PATH),
            f"agent.resume_attempts({resume_attempts}) must be < "
            f"agent.infra_retry_max_retries({max_retries}) — 预算内须留一发 fresh")
    return {
        "max_retries": max_retries,
        "backoff_base_s": _positive_float(
            raw.get("infra_backoff_base_s", _DEFAULT_INFRA_BACKOFF_BASE_S),
            "agent.infra_backoff_base_s"),
        "backoff_factor": _at_least_one_float(
            raw.get("infra_backoff_factor", _DEFAULT_INFRA_BACKOFF_FACTOR),
            "agent.infra_backoff_factor"),
        "backoff_max_total_s": _positive_float(
            raw.get("infra_backoff_max_total_s",
                    _DEFAULT_INFRA_BACKOFF_MAX_TOTAL_S),
            "agent.infra_backoff_max_total_s"),
        "resume_attempts": resume_attempts,
    }


# P117 route C: opencode keepalive watchdog thresholds. opencode can't be
# modified (session-layer SessionRetry.policy has no retry cap → unbounded
# backoff on gateway errors like 1313; it also silent-swallows the error so the
# POST never returns, and keeps emitting SSE noise that fools the existing
# last_event_ts keepalive). The framework side therefore stops a hung spawn via
# a turn-stall gate (no new turn for turn_stall_s → trip); message_timeout_s is
# the configurable hard cap. The framework does NOT read opencode.log (external
# path, §1.7) — the turn-stall trip reason instead carries the stalled turn's
# number + active block types (e.g. tool:read) as the honest signal of what the
# agent was doing when it stalled. All thresholds configurable; 0 disables one.
# P131 (trial-20260730) 原论证 600s = 2× gateway request_timeout(300s) 是为让
# 「单个慢/重试上游请求存活」。batch-20260813 坐实推翻该前提（11 次 stall，见
# docs/plan/batch-20260813-timing-analysis Q1）：全是 fresh-session 永久静默
# （last turn 2，chars static 610s），判死后 infra_backoff + cross-run resume
# 立即成功、无一例 600s 内自发恢复（本批无可恢复慢请求形态）。故缩到 120s：
# 把「判死 + resume 重采样」提前 480s/次（省 ~88m），不误杀可恢复慢请求（本批
# 无此形态）。真正的恢复仍是 cross-run backoff-resume 重采样 FRESH 网关窗口，
# 120s 只是更早触发它，不是「等待一个可能恢复的慢请求」。
# P9 (batch-20260821, moe_re_routing) 坐实 120s 系统性误杀深推理模型后回调 600s：
# pangu 深推理单 turn 静默（连 reasoning 增量都不吐）常态 >120s，每次 trip→resume
# →再 trip 死亡螺旋（resume_fails 3x 退化 fresh → infra-retry 4/4 耗尽 → halt，
# 整算子 exit 65，18 分钟内 5 连杀）。P131 的 11 次永久静默均 ≥610s —— 600s 界
# 仍全部捕获，仅每个死会话晚判 480s；误杀代价（整算子小时级）≫ 晚杀代价（8min/
# 死会话），宽容优先。与 keepalive_idle_s(600s) 收敛为一个语义：生产者静默 >600s
# = 死（turn_stall 看 turn/chars 真进展，keepalive 看任何 SSE 帧——P117 噪声场景
# 靠前者）。§step-97：tool 执行期静默由判死前取证（opencode db running 探活，
# 见 tool_grace_s 注释与 opencode_backend._pretrip_tool_evidence）判别——旧 §P9
# 静态让位公式已删（两旋钮收敛 600 后 max(600,600) 数值恒零）。
_DEFAULT_OPENCODE_TURN_STALL_S = 180.0        # no new turn this long → trip
# step-115 (P16, 2026-09-02 用户裁定)：600→180。前置分型落地后本界只是「无任何
# 证据」时的残差兜底——阳性网关错误（app log stream error）由 gateway_error_probe_s
# 提前 trip（<1min），工具在飞由 step-97 db 探针 re-arm；残差类=活深推理无增量
# 静默（P9 形态，>180s 存在误杀风险——用户已知悉接受，配置面
# timeouts.opencode_turn_stall_s 随时可回调；trip 打标 evidence/duration 两类，
# 后续用真实分布校准）。构造默认同步统一 180（原 opencode 300/sdk 180/config 600
# 三值漂移收敛）。
# §step-97 (docs/plan/turn-stall-pretrip-evidence/): pre-trip 取证后的工具容忍
# 界——看门狗判死前查本 spawn 的 opencode db，最新 tool part status=running 视为
# 「工具在飞」（存活复位）；running 超过本界判工具挂死 → 杀工具进程树（不杀
# serve，agent 带工具错误继续）。1800s 覆盖 build+deploy+多 case 验证的合法时长；
# 0 = 禁用杀工具（running 只作存活复位，永不杀）。配置面同 turn_stall_s。
_DEFAULT_OPENCODE_TOOL_GRACE_S = 1800.0
# P132 (trial-20260730): message_timeout is now a runaway-cost backstop only,
# NOT a per-turn stall guard (turn_stall + keepalive own that). The old 3600s
# hard-killed HEALTHY heavy stages mid-progress (apply_rotary made steady turn
# progress for 3689s across many turns and 3600 guillotined it). 4h gives a
# legitimately large operator room while still capping a pathological unbounded
# spawn. 0 disables entirely (turn-stall/keepalive as the sole guards).
_DEFAULT_OPENCODE_MESSAGE_TIMEOUT_S = 14400.0  # 4h runaway backstop (0 = disabled)
# step-115 (P16)：阳性错误证据探针起始静默时长（见 opencode_timeouts 注释）。
_DEFAULT_OPENCODE_GATEWAY_ERROR_PROBE_S = 30.0


def opencode_timeouts() -> dict:
    """P117 route C: opencode keepalive watchdog thresholds.

    Reads the ``timeouts`` section of orchestration-config.json at call time
    (same pattern as ``resume_limits``). ``turn_stall_s`` / ``message_timeout_s``
    accept 0 (= disabled).

    MISSING section/keys → documented defaults; present-but-invalid →
    ``ConfigError`` naming the field (same strict-vs-tolerant policy).
    """
    raw = _RAW.get("timeouts", {})
    if not isinstance(raw, dict):
        raise ConfigError(str(_CONFIG_PATH), "'timeouts' must be a JSON object")
    return {
        "turn_stall_s": _non_negative_float(
            raw.get("opencode_turn_stall_s", _DEFAULT_OPENCODE_TURN_STALL_S),
            "timeouts.opencode_turn_stall_s"),
        "tool_grace_s": _non_negative_float(
            raw.get("opencode_tool_grace_s", _DEFAULT_OPENCODE_TOOL_GRACE_S),
            "timeouts.opencode_tool_grace_s"),
        "message_timeout_s": _non_negative_float(
            raw.get("opencode_message_timeout_s",
                    _DEFAULT_OPENCODE_MESSAGE_TIMEOUT_S),
            "timeouts.opencode_message_timeout_s"),
        # step-115 (P16)：阳性网关错误证据探针——chars 静止超过该值才开始读本
        # spawn scratch 的 opencode app log（XDG_DATA_HOME 内，§1.7 无忧），
        # 发现晚于静默起点且 ≥2 条（复发）的 stream error → 立即 trip
        # （gateway_stream_error）。静默前置防 flappy-alive 误杀（与 ≥2 复发
        # 判据正交）；数值调节价值边际——**0 = 禁用整条证据腿**是本键的真实
        # 运维价值（新杀路径的逃生口）。探针随 poll 直读，不设节流。
        "gateway_error_probe_s": _non_negative_float(
            raw.get("opencode_gateway_error_probe_s",
                    _DEFAULT_OPENCODE_GATEWAY_ERROR_PROBE_S),
            "timeouts.opencode_gateway_error_probe_s"),
    }


