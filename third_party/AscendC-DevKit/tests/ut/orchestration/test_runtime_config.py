"""Strict-vs-tolerant config loading policy for orchestration-config.json.

Policy under test:
  - MISSING config (no file / no section / no key) → use code defaults (tolerant)
  - INVALID config (bad JSON / wrong type / non-positive) → ConfigError (fail-fast)

The loader runs at import time, so each case writes a temp config, points the
loader at it, and reloads the module to exercise the real module-level path.
"""

import importlib
import json
from pathlib import Path
from unittest import mock

import pytest

from ascendc_devkit.domain.exceptions import ConfigError
from ascendc_devkit.orchestration.runtime_config import (
    _DEFAULT_PRECISION_MAX_ITERATIONS,
    _DEFAULT_PRECISION_MAX_ATTEMPTS_PER_CASE,
    _DEFAULT_PRECISION_TIME_BUDGET_S,
)


@pytest.fixture(autouse=True)
def _restore_runtime_config_globals():
    """Snapshot + restore the module globals these tests mutate.

    Several cases below assign rc.STAGE_ITERATIONS / rc._RAW directly to exercise
    the loader. Without restoration they leak the mutated value (e.g. an empty
    STAGE_ITERATIONS) into later test files, breaking config-dependent tests
    (test isolation bug). Snapshot before, restore after — unconditionally.
    """
    import ascendc_devkit.orchestration.runtime_config as rc
    saved = {name: getattr(rc, name) for name in
             ("STAGE_ITERATIONS", "_RAW", "_ITER", "_CONFIG", "_CONFIG_PATH",
              "CONFIG_MAX_CORRECTIVE", "CONFIG_MAX_ESCALATIONS")
             if hasattr(rc, name)}
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(rc, name, value)


def _reload_with(tmp_path, content=None, write_raw=None):
    """Reload runtime_config with its config path redirected to a temp file.

    content: a dict to json.dump, or None to leave the file absent.
    write_raw: raw string to write verbatim (for malformed-JSON cases).
    """
    import ascendc_devkit.orchestration.runtime_config as rc
    cfg = tmp_path / "orchestration-config.json"
    if write_raw is not None:
        cfg.write_text(write_raw)
    elif content is not None:
        cfg.write_text(json.dumps(content))
    # else: leave it absent

    orig = rc._CONFIG_PATH
    rc._CONFIG_PATH = cfg
    try:
        # Re-run module-level loading against the redirected path by reloading.
        # _CONFIG_PATH is recomputed on reload, so monkeypatch the module global
        # the loader reads instead: simplest is to call the internals directly.
        rc._CONFIG_PATH = cfg
        raw = rc._load_raw()
        return rc, raw
    finally:
        rc._CONFIG_PATH = orig


class TestTolerantOnMissing:
    def test_absent_file_uses_defaults(self, tmp_path):
        rc, raw = _reload_with(tmp_path, content=None)
        assert raw == {}

    def test_empty_object_uses_defaults(self, tmp_path):
        rc, raw = _reload_with(tmp_path, content={})
        assert raw == {}
        # No iterations section → empty stage map, default quotas downstream.
        assert raw.get("iterations", {}) == {}

    def test_missing_key_falls_back(self, tmp_path):
        # iterations present but max_corrective omitted → default applies.
        rc, raw = _reload_with(
            tmp_path, content={"iterations": {"stages": {"verify": 7}}})
        iters = raw["iterations"]
        assert iters["stages"]["verify"] == 7
        assert "max_corrective" not in iters  # downstream uses code default


class TestFailFastOnInvalid:
    def test_malformed_json_raises(self, tmp_path):
        with pytest.raises(ConfigError) as ei:
            _reload_with(tmp_path, write_raw="{ broken ]")
        assert "malformed JSON" in str(ei.value)

    def test_top_level_not_object_raises(self, tmp_path):
        with pytest.raises(ConfigError):
            _reload_with(tmp_path, write_raw="[1, 2, 3]")


class TestPositiveIntValidation:
    """_positive_int is the shared validator for every budget field."""

    def test_non_int_string_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        with pytest.raises(ConfigError) as ei:
            rc._positive_int("abc", "iterations.stages.verify")
        assert "positive integer" in str(ei.value)

    def test_zero_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        with pytest.raises(ConfigError) as ei:
            rc._positive_int(0, "iterations.stages.verify")
        assert ">= 1" in str(ei.value)

    def test_negative_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        with pytest.raises(ConfigError):
            rc._positive_int(-3, "iterations.max_corrective")

    def test_bool_rejected(self, tmp_path):
        # JSON true is a Python int subclass but never a valid budget.
        rc, _ = _reload_with(tmp_path, content={})
        with pytest.raises(ConfigError):
            rc._positive_int(True, "iterations.stages.verify")

    def test_valid_positive_passes(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        assert rc._positive_int(5, "iterations.stages.verify") == 5


class TestStageMaxIterations:
    def test_config_override_wins(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc.STAGE_ITERATIONS = {"verify": 9}
        try:
            assert rc.stage_max_iterations("verify", 3) == 9
        finally:
            rc.STAGE_ITERATIONS = {}

    def test_code_default_when_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc.STAGE_ITERATIONS = {}
        assert rc.stage_max_iterations("integrate", 1) == 1


class TestNonNegativeIntValidation:
    """_non_negative_int is the shared validator for timeout fields, where 0 is
    a legitimate value meaning 'no timeout' (unlike iteration budgets)."""

    def test_zero_allowed(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        assert rc._non_negative_int(0, "timeouts.stages.codegen") == 0

    def test_valid_positive_passes(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        assert rc._non_negative_int(1800, "timeouts.stages.codegen") == 1800

    def test_negative_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        with pytest.raises(ConfigError) as ei:
            rc._non_negative_int(-1, "timeouts.stages.codegen")
        assert ">= 0" in str(ei.value)

    def test_non_int_string_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        with pytest.raises(ConfigError) as ei:
            rc._non_negative_int("abc", "timeouts.default")
        assert "non-negative integer" in str(ei.value)

    def test_bool_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        with pytest.raises(ConfigError):
            rc._non_negative_int(True, "timeouts.stages.codegen")


class TestResolveStageTimeout:
    """step-5b: timeouts.stages.<name> + default, with CLI override winning.

    Priority: CLI --stage-timeout (explicit, incl. explicit 0) > config
    timeouts.stages.<stage> > config default > 0 (no timeout).
    """

    def test_cli_explicit_positive_wins(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        orig_s, orig_d = dict(rc.STAGE_TIMEOUTS), rc.CONFIG_DEFAULT_STAGE_TIMEOUT
        rc.STAGE_TIMEOUTS = {"codegen": 1800}
        rc.CONFIG_DEFAULT_STAGE_TIMEOUT = 300
        try:
            # CLI passes 600 → wins over config's 1800 and default 300.
            assert rc.resolve_stage_timeout("codegen", 600) == 600
        finally:
            rc.STAGE_TIMEOUTS, rc.CONFIG_DEFAULT_STAGE_TIMEOUT = orig_s, orig_d

    def test_cli_explicit_zero_wins(self, tmp_path):
        """Explicit --stage-timeout 0 disables the timeout even when config
        sets a stage budget (CLI explicit beats config)."""
        rc, _ = _reload_with(tmp_path, content={})
        orig_s = dict(rc.STAGE_TIMEOUTS)
        rc.STAGE_TIMEOUTS = {"codegen": 1800}
        try:
            assert rc.resolve_stage_timeout("codegen", 0) == 0
        finally:
            rc.STAGE_TIMEOUTS = orig_s

    def test_config_stage_used_when_cli_none(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        orig_s, orig_d = dict(rc.STAGE_TIMEOUTS), rc.CONFIG_DEFAULT_STAGE_TIMEOUT
        rc.STAGE_TIMEOUTS = {"codegen": 1800}
        rc.CONFIG_DEFAULT_STAGE_TIMEOUT = 300
        try:
            assert rc.resolve_stage_timeout("codegen", None) == 1800
        finally:
            rc.STAGE_TIMEOUTS, rc.CONFIG_DEFAULT_STAGE_TIMEOUT = orig_s, orig_d

    def test_config_default_used_when_stage_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        orig_s, orig_d = dict(rc.STAGE_TIMEOUTS), rc.CONFIG_DEFAULT_STAGE_TIMEOUT
        rc.STAGE_TIMEOUTS = {"codegen": 1800}
        rc.CONFIG_DEFAULT_STAGE_TIMEOUT = 300
        try:
            assert rc.resolve_stage_timeout("requirement", None) == 300
        finally:
            rc.STAGE_TIMEOUTS, rc.CONFIG_DEFAULT_STAGE_TIMEOUT = orig_s, orig_d

    def test_zero_when_all_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        orig_s, orig_d = dict(rc.STAGE_TIMEOUTS), rc.CONFIG_DEFAULT_STAGE_TIMEOUT
        rc.STAGE_TIMEOUTS = {}
        rc.CONFIG_DEFAULT_STAGE_TIMEOUT = 0
        try:
            assert rc.resolve_stage_timeout("design", None) == 0
        finally:
            rc.STAGE_TIMEOUTS, rc.CONFIG_DEFAULT_STAGE_TIMEOUT = orig_s, orig_d

    def test_invalid_stage_value_fails_fast(self, tmp_path):
        rc, raw = _reload_with(
            tmp_path,
            content={"timeouts": {"stages": {"codegen": -5}}})
        orig_raw = rc._RAW
        rc._RAW = raw
        try:
            with pytest.raises(ConfigError) as ei:
                rc._load_stage_timeouts()
            assert "timeouts.stages.codegen" in str(ei.value)
        finally:
            rc._RAW = orig_raw

    def test_real_config_codegen_18000(self, tmp_path):
        """The shipped orchestration-config.json gives codegen 18000s (c42191e3:
        increase stage timeouts for long-running codegen; was 1800)."""
        import ascendc_devkit.orchestration.runtime_config as rc
        assert rc.STAGE_TIMEOUTS.get("codegen") == 18000


class TestResumeLimits:
    """step-5a: agent.resume_max_retries / resume_max_no_progress.

    resume_limits() reads the 'agent' section at call time (same pattern as
    design_group_quota / review_points), so tests patch rc._RAW.
    """

    def test_defaults_when_section_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {}
        limits = rc.resume_limits()
        assert limits["max_retries"] == 10
        assert limits["max_no_progress"] == 3

    def test_defaults_when_keys_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {}}
        limits = rc.resume_limits()
        assert limits["max_retries"] == 10
        assert limits["max_no_progress"] == 3

    def test_config_override_wins(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {"resume_max_retries": 5,
                             "resume_max_no_progress": 2}}
        limits = rc.resume_limits()
        assert limits["max_retries"] == 5
        assert limits["max_no_progress"] == 2

    def test_non_positive_retries_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {"resume_max_retries": 0}}
        with pytest.raises(ConfigError) as ei:
            rc.resume_limits()
        assert "agent.resume_max_retries" in str(ei.value)

    def test_non_int_no_progress_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {"resume_max_no_progress": "lots"}}
        with pytest.raises(ConfigError) as ei:
            rc.resume_limits()
        assert "agent.resume_max_no_progress" in str(ei.value)

    def test_agent_section_not_object_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": [1, 2]}
        with pytest.raises(ConfigError) as ei:
            rc.resume_limits()
        assert "agent" in str(ei.value)


class TestRateLimitBackoffLimits:
    """step-57 (P80): agent.rate_limit_* — 429 burst backoff-resume budget,
    read from the same 'agent' section by resume_limits()."""

    def test_defaults_when_keys_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {}}
        limits = rc.resume_limits()
        assert limits["rate_limit_max_retries"] == 6
        assert limits["rate_limit_backoff_base_s"] == 30.0
        assert limits["rate_limit_backoff_factor"] == 2.0
        assert limits["rate_limit_backoff_max_total_s"] == 600.0

    def test_config_override_wins(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {
            "rate_limit_max_retries": 3,
            "rate_limit_backoff_base_s": 10,
            "rate_limit_backoff_factor": 1.5,
            "rate_limit_backoff_max_total_s": 120,
        }}
        limits = rc.resume_limits()
        assert limits["rate_limit_max_retries"] == 3
        assert limits["rate_limit_backoff_base_s"] == 10.0
        assert limits["rate_limit_backoff_factor"] == 1.5
        assert limits["rate_limit_backoff_max_total_s"] == 120.0

    def test_non_positive_retries_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {"rate_limit_max_retries": 0}}
        with pytest.raises(ConfigError) as ei:
            rc.resume_limits()
        assert "agent.rate_limit_max_retries" in str(ei.value)

    def test_non_positive_base_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {"rate_limit_backoff_base_s": 0}}
        with pytest.raises(ConfigError) as ei:
            rc.resume_limits()
        assert "agent.rate_limit_backoff_base_s" in str(ei.value)

    def test_factor_below_one_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {"rate_limit_backoff_factor": 0.5}}
        with pytest.raises(ConfigError) as ei:
            rc.resume_limits()
        assert "agent.rate_limit_backoff_factor" in str(ei.value)

    def test_factor_one_allowed(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {"rate_limit_backoff_factor": 1.0}}
        limits = rc.resume_limits()
        assert limits["rate_limit_backoff_factor"] == 1.0

    def test_non_number_max_total_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {"rate_limit_backoff_max_total_s": "lots"}}
        with pytest.raises(ConfigError) as ei:
            rc.resume_limits()
        assert "agent.rate_limit_backoff_max_total_s" in str(ei.value)

    def test_bool_rejected_for_float_param(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"agent": {"rate_limit_backoff_base_s": True}}
        with pytest.raises(ConfigError):
            rc.resume_limits()


class TestHwProbeTimeout:
    """step-32 收尾: timeouts.hw_probe_sec — the bound on the NPU hardware probe
    (driver-hang protection, §3.7).

    Same strict-vs-tolerant policy as the stage timeouts:
      - MISSING (no key / no timeouts section) → detect._DEFAULT_HW_PROBE_TIMEOUT
        (single source imported from the L4 adapter, tolerant)
      - INVALID (bool / non-number / <=0) → ConfigError (fail-fast)
      - valid positive number → float(value)

    Unlike a stage timeout, 0 is NOT valid here: a probe bound of 0 would time
    out instantly (there is no 'disabled' semantic — skip the probe with
    ``--assume-chip``, not 0). The loader reads rc._RAW, so tests patch rc._RAW
    (restored by the autouse fixture) then call _load_hw_probe_timeout().
    """

    def test_missing_key_uses_default(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"stages": {"codegen": 1800}}}
        from ascendc_devkit.adapters.npu.detect import _DEFAULT_HW_PROBE_TIMEOUT
        assert rc._load_hw_probe_timeout() == _DEFAULT_HW_PROBE_TIMEOUT

    def test_no_timeouts_section_uses_default(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"iterations": {}}
        from ascendc_devkit.adapters.npu.detect import _DEFAULT_HW_PROBE_TIMEOUT
        assert rc._load_hw_probe_timeout() == _DEFAULT_HW_PROBE_TIMEOUT

    def test_timeouts_not_object_treated_as_missing(self, tmp_path):
        # A non-dict timeouts section is tolerated as 'absent' → default.
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": [1, 2, 3]}
        from ascendc_devkit.adapters.npu.detect import _DEFAULT_HW_PROBE_TIMEOUT
        assert rc._load_hw_probe_timeout() == _DEFAULT_HW_PROBE_TIMEOUT

    def test_valid_int_override(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"hw_probe_sec": 25}}
        assert rc._load_hw_probe_timeout() == 25.0

    def test_valid_float_override(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"hw_probe_sec": 2.5}}
        assert rc._load_hw_probe_timeout() == 2.5

    def test_zero_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"hw_probe_sec": 0}}
        with pytest.raises(ConfigError) as ei:
            rc._load_hw_probe_timeout()
        assert "> 0" in str(ei.value)

    def test_negative_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"hw_probe_sec": -5}}
        with pytest.raises(ConfigError) as ei:
            rc._load_hw_probe_timeout()
        assert "> 0" in str(ei.value)

    def test_bool_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"hw_probe_sec": True}}
        with pytest.raises(ConfigError) as ei:
            rc._load_hw_probe_timeout()
        assert "must be a number" in str(ei.value)

    def test_non_number_string_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"hw_probe_sec": "10"}}
        with pytest.raises(ConfigError) as ei:
            rc._load_hw_probe_timeout()
        assert "must be a number" in str(ei.value)

    def test_real_config_default_60_and_getter(self, tmp_path):
        """The shipped orchestration-config.json sets hw_probe_sec 60 (2026-08:
        fresh torch_npu open-device cold-start measured 8-12s per card, slow
        cards 12-44s, so 10s/30s can falsely drop healthy cards on a cold box;
        60s cleanly separates healthy cold-start from a hung driver and matches
        the dispatcher NPU smoke subprocess bound), parsed into
        HW_PROBE_TIMEOUT_SEC at import and surfaced via the getter."""
        import ascendc_devkit.orchestration.runtime_config as rc
        assert rc.HW_PROBE_TIMEOUT_SEC == 60.0
        assert rc.hw_probe_timeout_sec() == 60.0


class TestPrecisionDebugKnobs:
    """precision_debug.{max_iterations, max_attempts_per_case, time_budget_sec} —
    all knobs share the ``_precision_knob`` loader, so
    boundary cases are covered representatively (one knob per invalid kind) plus
    a real-config value check for all four. Same strict-vs-tolerant policy as the
    other knobs. These mutate rc._RAW directly then read the module constants
    (restored by the autouse _restore_runtime_config_globals fixture)."""

    _DEFAULTS = {
        "max_iterations": _DEFAULT_PRECISION_MAX_ITERATIONS,
        "max_attempts_per_case": _DEFAULT_PRECISION_MAX_ATTEMPTS_PER_CASE,
        "time_budget_sec": _DEFAULT_PRECISION_TIME_BUDGET_S,
    }

    def test_missing_section_uses_defaults(self, tmp_path):
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {"iterations": {"codegen": 10}}
        for key, default in self._DEFAULTS.items():
            assert rc._precision_knob(key, default) == default

    def test_missing_key_uses_default(self, tmp_path):
        # Section present but a specific key absent → that key's default.
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {"precision_debug": {"max_iterations": 50}}
        assert rc._precision_knob("max_iterations", 30) == 50
        assert rc._precision_knob("max_attempts_per_case", 8) == 8  # absent → default

    def test_section_not_object_raises(self, tmp_path):
        # A non-dict precision_debug section is a hard error (fail-fast §1.3),
        # not tolerated as 'missing' — the user wrote something malformed. The
        # section-type guard lives inside _precision_knob (which reads the live
        # _RAW), so mutating rc._RAW then calling the helper exercises it.
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {"precision_debug": [1, 2, 3]}
        with pytest.raises(ConfigError):
            rc._precision_knob("max_iterations", 30)

    def test_valid_values_parsed(self, tmp_path):
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {"precision_debug": {
            "max_iterations": 50,
            "max_attempts_per_case": 3,
            "time_budget_sec": 8000,
        }}
        assert rc._precision_knob("max_iterations", 30) == 50
        assert rc._precision_knob("max_attempts_per_case", 10) == 3
        assert rc._precision_knob("time_budget_sec", _DEFAULT_PRECISION_TIME_BUDGET_S) == 8000

    def test_zero_rejected(self, tmp_path):
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {"precision_debug": {"max_iterations": 0}}
        with pytest.raises(ConfigError) as ei:
            rc._precision_knob("max_iterations", 30)
        assert "precision_debug.max_iterations" in str(ei.value)

    def test_negative_rejected(self, tmp_path):
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {"precision_debug": {"max_iterations": -1}}
        with pytest.raises(ConfigError):
            rc._precision_knob("max_iterations", 8)

    def test_bool_rejected(self, tmp_path):
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {"precision_debug": {"max_attempts_per_case": True}}
        with pytest.raises(ConfigError):
            rc._precision_knob("max_attempts_per_case", 10)

    def test_float_rejected(self, tmp_path):
        """Integer only — a fractional budget/quota is a likely typo."""
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {"precision_debug": {"time_budget_sec": 12000.5}}
        with pytest.raises(ConfigError):
            rc._precision_knob("time_budget_sec", _DEFAULT_PRECISION_TIME_BUDGET_S)

    def test_string_rejected(self, tmp_path):
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {"precision_debug": {"max_iterations": "30"}}
        with pytest.raises(ConfigError):
            rc._precision_knob("max_iterations", 30)

    def test_real_config_values_and_getters(self, tmp_path):
        """Module constants must match the shipped orchestration-config.json."""
        import json
        from pathlib import Path
        config_path = Path(__file__).parent.parent.parent.parent / "resources" / "orchestration-config.json"
        with open(config_path) as f:
            cfg = json.load(f)
        pd = cfg["precision_debug"]
        import ascendc_devkit.orchestration.runtime_config as rc
        assert rc.PRECISION_MAX_ITERATIONS == pd["max_iterations"]
        assert rc.PRECISION_MAX_ATTEMPTS_PER_CASE == pd["max_attempts_per_case"]
        assert rc.PRECISION_DEBUG_TIME_BUDGET_S == pd["time_budget_sec"]
        assert rc.PRECISION_DEBUG_MAX_CORRECTIVE == pd["max_corrective"]
        assert rc.precision_debug_max_iterations() == pd["max_iterations"]
        assert rc.precision_debug_max_attempts_per_case() == pd["max_attempts_per_case"]
        assert rc.precision_debug_time_budget_sec() == pd["time_budget_sec"]
        assert rc.precision_debug_max_corrective() == pd["max_corrective"]


class TestOpencodeTimeouts:
    """P117 route C: timeouts.opencode_* — opencode keepalive watchdog
    thresholds. opencode can't be modified (unbounded session-layer retry +
    silent-swallow of gateway errors), so the framework stops a hung spawn via a
    turn-stall gate; the trip reason carries the stalled turn's number + active
    block types. The framework does NOT read opencode.log (external path, §1.7).
    opencode_timeouts() reads the ``timeouts`` section at call time (same pattern
    as resume_limits), so tests patch rc._RAW.

    turn_stall_s / message_timeout_s accept 0 (= disabled).
    """

    def test_defaults_when_section_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {}
        t = rc.opencode_timeouts()
        assert t["turn_stall_s"] == rc._DEFAULT_OPENCODE_TURN_STALL_S
        assert t["message_timeout_s"] == rc._DEFAULT_OPENCODE_MESSAGE_TIMEOUT_S

    def test_default_turn_stall_180_p16(self):
        """step-115 (P16, 2026-09-02 用户裁定)：判死分型后时长界只是无证据
        残差兜底（阳性网关错误由 gateway_error_probe_s 提前 trip、工具在飞由
        step-97 db 探针 re-arm），600→180。P9 教训在案：残差类=活深推理无增量
        静默，>180s 有误杀风险——已知悉接受，timeouts.opencode_turn_stall_s
        可回调；trip 打标 evidence/duration 两类供后续校准。钉住 180 防无意识
        回退/漂移（构造默认三值已统一）。"""
        import ascendc_devkit.orchestration.runtime_config as rc
        assert rc._DEFAULT_OPENCODE_TURN_STALL_S == 180.0

    def test_shipped_config_pins_turn_stall_180(self):
        """发运 config 显式钉 opencode_turn_stall_s——只改代码默认对生产无效
        （config 显式值优先）。守护 config 与 step-115 裁定（180）一致。"""
        import json
        from pathlib import Path
        config_path = (Path(__file__).parent.parent.parent.parent
                       / "resources" / "orchestration-config.json")
        with open(config_path) as f:
            cfg = json.load(f)
        assert cfg["timeouts"]["opencode_turn_stall_s"] == 180
        assert cfg["timeouts"]["opencode_gateway_error_probe_s"] == 30

    def test_gateway_error_probe_three_states(self, tmp_path):
        """step-115 (P16)：gateway_error_probe_s 默认 30 / config 覆盖 / 0 合法
        （= 禁用证据速杀，时长界独立工作）/ 负值非法（ConfigError 点名）。"""
        import ascendc_devkit.orchestration.runtime_config as rc
        rc._RAW = {}
        assert rc.opencode_timeouts()["gateway_error_probe_s"] == 30.0
        rc._RAW = {"timeouts": {"opencode_gateway_error_probe_s": 5}}
        assert rc.opencode_timeouts()["gateway_error_probe_s"] == 5.0
        rc._RAW = {"timeouts": {"opencode_gateway_error_probe_s": 0}}
        assert rc.opencode_timeouts()["gateway_error_probe_s"] == 0.0
        rc._RAW = {"timeouts": {"opencode_gateway_error_probe_s": -1}}
        import pytest
        from ascendc_devkit.domain.exceptions import ConfigError
        with pytest.raises(ConfigError):
            rc.opencode_timeouts()

    def test_defaults_when_keys_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {}}
        t = rc.opencode_timeouts()
        assert t["turn_stall_s"] == rc._DEFAULT_OPENCODE_TURN_STALL_S
        assert t["message_timeout_s"] == rc._DEFAULT_OPENCODE_MESSAGE_TIMEOUT_S

    def test_config_override_wins(self, tmp_path):
        # override 用非默认值（999 ≠ 默认 120 / 1800 ≠ 默认 14400），证明覆盖真生效
        # 而非恰好等于默认值（若 override 被忽略仍回默认，断言会失败）。
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {
            "opencode_turn_stall_s": 999,
            "opencode_message_timeout_s": 1800,
        }}
        t = rc.opencode_timeouts()
        assert t["turn_stall_s"] == 999
        assert t["message_timeout_s"] == 1800

    def test_zero_disables_turn_stall_and_message_timeout(self, tmp_path):
        # 0 = disabled (rely on the other stop), same semantic as stage timeouts.
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"opencode_turn_stall_s": 0,
                                "opencode_message_timeout_s": 0}}
        t = rc.opencode_timeouts()
        assert t["turn_stall_s"] == 0
        assert t["message_timeout_s"] == 0

    def test_negative_turn_stall_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"opencode_turn_stall_s": -1}}
        with pytest.raises(ConfigError) as ei:
            rc.opencode_timeouts()
        assert "opencode_turn_stall_s" in str(ei.value)

    def test_bool_rejected(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": {"opencode_turn_stall_s": True}}
        with pytest.raises(ConfigError):
            rc.opencode_timeouts()

    def test_timeouts_section_not_object_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"timeouts": [1, 2]}
        with pytest.raises(ConfigError) as ei:
            rc.opencode_timeouts()
        assert "timeouts" in str(ei.value)

    def test_real_config_values(self, tmp_path):
        """shipped orchestration-config.json 的 opencode_* 字段与 code 默认常量一致
        （code==config，与 TestPrecisionDebugKnobs 同口径；不 pin 字面量——单一事实源
        在 runtime_config.py 常量，值随批次收敛，改值只动常量 + 配置，不动测试）。"""
        import json
        from pathlib import Path
        import ascendc_devkit.orchestration.runtime_config as rc
        config_path = (Path(__file__).parent.parent.parent.parent
                       / "resources" / "orchestration-config.json")
        with open(config_path) as f:
            cfg = json.load(f)
        to = cfg["timeouts"]
        assert to["opencode_turn_stall_s"] == rc._DEFAULT_OPENCODE_TURN_STALL_S
        assert to["opencode_message_timeout_s"] == rc._DEFAULT_OPENCODE_MESSAGE_TIMEOUT_S


class TestHarnessTimeoutSidecar:
    """§2.9 框架自有超时 sidecar：放大值落 debug 目录 sidecar（agent control.json
    重写碰不到），debug_service 读它恢复放大超时。"""

    def test_reads_valid_sidecar(self, tmp_path):
        from ascendc_devkit.orchestration.runtime_config import (
            read_harness_timeout_sidecar, HARNESS_TIMEOUT_SIDECAR_NAME)
        import json
        p = tmp_path / HARNESS_TIMEOUT_SIDECAR_NAME
        p.write_text(json.dumps({"harness_timeout_sec": 480.0}), encoding="utf-8")
        assert read_harness_timeout_sidecar(tmp_path) == 480.0

    def test_missing_sidecar_returns_none(self, tmp_path):
        from ascendc_devkit.orchestration.runtime_config import (
            read_harness_timeout_sidecar)
        assert read_harness_timeout_sidecar(tmp_path) is None

    def test_bad_sidecar_returns_none(self, tmp_path):
        from ascendc_devkit.orchestration.runtime_config import (
            read_harness_timeout_sidecar, HARNESS_TIMEOUT_SIDECAR_NAME)
        p = tmp_path / HARNESS_TIMEOUT_SIDECAR_NAME
        p.write_text("{not json", encoding="utf-8")
        assert read_harness_timeout_sidecar(tmp_path) is None

    def test_bad_sidecar_warns(self, tmp_path):
        """F5 (review 坐实, 补断言): 读失败必须 Logger.warn——静默损坏的 sidecar
        若无声回默认 120，放大值丢失无任何可观测信号（§1.2 不静默吞告警）。
        原测试只断言返回 None，未断言 WARN 触发（F5 修复的核心）。"""
        from ascendc_devkit.orchestration.runtime_config import (
            read_harness_timeout_sidecar, HARNESS_TIMEOUT_SIDECAR_NAME)
        from ascendc_devkit.infra.logger import Logger
        p = tmp_path / HARNESS_TIMEOUT_SIDECAR_NAME
        p.write_text("{not json", encoding="utf-8")
        with mock.patch.object(Logger, "warn") as m:
            assert read_harness_timeout_sidecar(tmp_path) is None
            m.assert_called_once()
            assert "falling back to default" in str(m.call_args)

    def test_nonpositive_value_returns_none(self, tmp_path):
        from ascendc_devkit.orchestration.runtime_config import (
            read_harness_timeout_sidecar, HARNESS_TIMEOUT_SIDECAR_NAME)
        import json
        p = tmp_path / HARNESS_TIMEOUT_SIDECAR_NAME
        p.write_text(json.dumps({"harness_timeout_sec": 0}), encoding="utf-8")
        assert read_harness_timeout_sidecar(tmp_path) is None

    def test_nonpositive_value_warns(self, tmp_path):
        """F5 (补断言): 非正值同样 WARN（放大值丢失可观测），非静默回默认。"""
        from ascendc_devkit.orchestration.runtime_config import (
            read_harness_timeout_sidecar, HARNESS_TIMEOUT_SIDECAR_NAME)
        from ascendc_devkit.infra.logger import Logger
        import json
        p = tmp_path / HARNESS_TIMEOUT_SIDECAR_NAME
        p.write_text(json.dumps({"harness_timeout_sec": 0}), encoding="utf-8")
        with mock.patch.object(Logger, "warn") as m:
            assert read_harness_timeout_sidecar(tmp_path) is None
            m.assert_called_once()

    def test_missing_sidecar_no_warn(self, tmp_path):
        """F5 (补断言): missing 是正常态（从未放大），不 WARN——与损坏/非正值区分。"""
        from ascendc_devkit.orchestration.runtime_config import (
            read_harness_timeout_sidecar)
        from ascendc_devkit.infra.logger import Logger
        with mock.patch.object(Logger, "warn") as m:
            assert read_harness_timeout_sidecar(tmp_path) is None
            m.assert_not_called()


class TestRetryBudgetsThinkingActiveGap:
    """P6（step-110）：retry_budgets.thinking_active_gap_s——硬切分类 gap 判据
    阈值（网关 flush 行为参数）。同组既有三键的读法延续：缺键默认 / 显式覆盖 /
    非法值 fail-fast。"""

    def test_default_when_section_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {}
        assert rc.retry_budgets()["thinking_active_gap_s"] == 0.6

    def test_default_when_key_absent(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"retry_budgets": {}}
        assert rc.retry_budgets()["thinking_active_gap_s"] == 0.6

    def test_config_override_wins(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"retry_budgets": {"thinking_active_gap_s": 2.0}}
        assert rc.retry_budgets()["thinking_active_gap_s"] == 2.0

    def test_non_positive_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"retry_budgets": {"thinking_active_gap_s": 0}}
        with pytest.raises(ConfigError) as ei:
            rc.retry_budgets()
        assert "thinking_active_gap_s" in str(ei.value)

    def test_non_float_fails_fast(self, tmp_path):
        rc, _ = _reload_with(tmp_path, content={})
        rc._RAW = {"retry_budgets": {"thinking_active_gap_s": "soon"}}
        with pytest.raises(ConfigError) as ei:
            rc.retry_budgets()
        assert "thinking_active_gap_s" in str(ei.value)

    def test_real_config_carries_documented_default(self, tmp_path):
        """仓内真实配置显式携带 0.6（默认值与实证来源在 _comment 如实标注）。"""
        import json as _json
        cfg_path = Path(__file__).resolve().parents[3] / "resources" \
            / "orchestration-config.json"
        raw = _json.loads(cfg_path.read_text(encoding="utf-8"))
        assert raw["retry_budgets"]["thinking_active_gap_s"] == 0.6
