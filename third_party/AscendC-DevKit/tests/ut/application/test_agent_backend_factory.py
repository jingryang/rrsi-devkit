"""UT for the agent backend factory (相2 §2.3).

Guards backend selection precedence (explicit > env > config > default), kwarg
filtering (each backend receives only the kwargs its __init__ declares, so the
three dispatcher call sites pass their full union unchanged), and fail-fast on
an unknown kind (§1.3). No real serve / SDK — construction only.
"""

from __future__ import annotations

import pytest

from ascendc_devkit.orchestration import agent_backend_factory as fac
from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
from ascendc_devkit.capabilities.agent.opencode_backend import OpenCodeBackend
from ascendc_devkit.domain.exceptions import ConfigError


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    monkeypatch.delenv(fac._ENV_VAR, raising=False)


def test_default_kind_is_opencode(monkeypatch):
    # no env, config returns None → built-in default (opencode as of 2.4)
    monkeypatch.setattr(fac, "_config_kind", lambda: None)
    assert fac.resolve_backend_kind() == "opencode"


def test_explicit_kind_wins_over_env_and_config(monkeypatch):
    monkeypatch.setenv(fac._ENV_VAR, "opencode")
    monkeypatch.setattr(fac, "_config_kind", lambda: "opencode")
    assert fac.resolve_backend_kind("claude") == "claude"


def test_env_wins_over_config(monkeypatch):
    monkeypatch.setenv(fac._ENV_VAR, "claude")
    monkeypatch.setattr(fac, "_config_kind", lambda: "opencode")
    assert fac.resolve_backend_kind() == "claude"


def test_config_used_when_no_env(monkeypatch):
    monkeypatch.setattr(fac, "_config_kind", lambda: "claude")
    assert fac.resolve_backend_kind() == "claude"


def test_unknown_kind_fails_fast(monkeypatch):
    monkeypatch.setattr(fac, "_config_kind", lambda: None)
    with pytest.raises(ConfigError):
        fac.resolve_backend_kind("nonsense")


def test_build_claude_filters_opencode_only_kwargs(monkeypatch):
    monkeypatch.setattr(fac, "_config_kind", lambda: None)
    # pass the union of both backends' kwargs; claude must ignore opencode-only ones
    b = fac.build_agent_backend(
        "claude",
        interactive=False,
        on_decision="default",
        enable_stubbed=True,              # claude-only
        resume_max_retries=7,             # claude-only
        opencode_bin="opencode",          # opencode-only → filtered out
        serve_startup_timeout=5.0,        # opencode-only → filtered out
    )
    assert isinstance(b, SDKBackend)


def test_build_opencode_filters_claude_only_kwargs(monkeypatch):
    monkeypatch.setattr(fac, "_config_kind", lambda: None)
    b = fac.build_agent_backend(
        "opencode",
        interactive=False,
        on_decision="default",
        enable_stubbed=True,              # claude-only → filtered out
        resume_max_retries=7,             # claude-only → filtered out
        opencode_bin="opencode",          # opencode-only
        message_timeout=42.0,             # opencode-only
    )
    assert isinstance(b, OpenCodeBackend)
    assert b._message_timeout == 42.0     # accepted kwarg landed


def test_rate_limit_kwargs_land_on_both_backends(monkeypatch):
    # step-57: rate_limit_* is accepted by BOTH backends (parity), so the
    # factory routes it to whichever is active.
    monkeypatch.setattr(fac, "_config_kind", lambda: None)
    for kind, expected in (("claude", SDKBackend), ("opencode", OpenCodeBackend)):
        b = fac.build_agent_backend(
            kind,
            interactive=False,
            rate_limit_max_retries=4,
            rate_limit_backoff_base_s=11.0,
            rate_limit_backoff_factor=3.0,
            rate_limit_backoff_max_total_s=222.0,
        )
        assert isinstance(b, expected)
        assert b._rl_max_retries == 4
        assert b._rl_backoff_base_s == 11.0
        assert b._rl_backoff_factor == 3.0
        assert b._rl_backoff_max_total_s == 222.0


def test_build_defaults_to_opencode(monkeypatch):
    monkeypatch.setattr(fac, "_config_kind", lambda: None)
    b = fac.build_agent_backend(interactive=False)
    assert isinstance(b, OpenCodeBackend)


def test_config_kind_reads_orchestration_config():
    # The shipped resources/orchestration-config.json declares opencode
    # (default flipped after 2.4 live-verified opencode on the D1/D2/permission
    # paths; D3 dispatch is heavy_llm-deferred, not a flip blocker).
    assert fac._config_kind() == "opencode"


def test_fallback_to_stub_on_construction_failure(monkeypatch):
    """review M1: fallback_to_stub=True + 后端构造失败 → StubBackend + 留 warn。

    KNOWN 清零 step-3 后 fallback 收进工厂（原 dispatcher 三处 try/except）；本用例
    守护「构造失败不静默」——落 stub 且打 Logger.warn（§1.2 可诊断）。
    """
    import ascendc_devkit.infra.logger as logger_mod
    from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
    warns = []
    monkeypatch.setattr(logger_mod.Logger, "warn",
                        staticmethod(lambda *a, **k: warns.append(a)))
    monkeypatch.setattr(fac, "_config_kind", lambda: "opencode")
    # 让 OpenCodeBackend 构造抛（模拟 SDK serve 不可用）
    monkeypatch.setattr(fac, "_BACKENDS",
                        {"opencode": type("Boom", (), {"__init__": lambda self, **k: (_ for _ in ()).throw(RuntimeError("serve down"))})})
    b = fac.build_agent_backend(fallback_to_stub=True)
    assert isinstance(b, StubBackend), "fallback_to_stub=True 构造失败应落 StubBackend"
    assert warns, "降级 stub 必须留 warn 日志（review M1：不静默吞）"
    assert "falling back to StubBackend" in warns[0][0]


def test_no_fallback_propagates_construction_error(monkeypatch):
    """fallback_to_stub=False（默认）构造失败 → 原异常传播（不静默降级）。"""
    monkeypatch.setattr(fac, "_config_kind", lambda: "opencode")
    monkeypatch.setattr(fac, "_BACKENDS",
                        {"opencode": type("Boom", (), {"__init__": lambda self, **k: (_ for _ in ()).throw(RuntimeError("serve down"))})})
    with pytest.raises(RuntimeError, match="serve down"):
        fac.build_agent_backend()


def test_unknown_kind_config_error_not_swallowed_by_fallback(monkeypatch):
    """review m7: resolve_backend_kind 的 ConfigError 在 try 外——fallback_to_stub=True
    也不吞配置错（fail-fast §1.3；旧 dispatcher 宽 except 会吞，已收窄为正确行为）。"""
    monkeypatch.setattr(fac, "_config_kind", lambda: None)
    monkeypatch.setenv(fac._ENV_VAR, "nonexistent-kind")
    with pytest.raises(ConfigError):
        fac.build_agent_backend(fallback_to_stub=True)
