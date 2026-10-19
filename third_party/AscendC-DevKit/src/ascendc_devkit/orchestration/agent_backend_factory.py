"""L3 Orchestration — agent backend factory (相2 §2.3).

Single construction point for the two ``AgentBackend`` implementations
(``SDKBackend`` = claude in-process, ``OpenCodeBackend`` = opencode serve over
HTTP). The dispatcher no longer names a concrete backend class; it calls
``build_agent_backend(**kw)`` and the factory resolves which SDK to use.

Backend selection (first wins):
  1. explicit ``kind`` argument (tests / programmatic override)
  2. ``ASCENDC_AGENT_BACKEND`` env var  (``opencode`` | ``claude``)
  3. ``agent_backend.kind`` in resources/orchestration-config.json
  4. the built-in default (``_DEFAULT_KIND``)

Default backend: ``opencode`` as of 2.4. The frozen L3/L4 plan targets opencode
as the default, and 2.4 verified it equivalent on every live path — D1 transport,
D2 skill injection (dual-backend @llm ST), tool-permission edit-allow
(dual-backend @llm ST), and D3 subagent DISPATCH (dual-backend @llm+@heavy_llm
ST, ``test_subagent_dispatch_dual_backend``) — with D3 subagent projection and
D4 engine MCP additionally UT-pinned at the config layer. No remaining live gap.
Override to claude via the config ``kind`` or ``ASCENDC_AGENT_BACKEND=claude``.

Kwarg handling (§1.6 DI, §2.5 single path): the two constructors take
overlapping-but-not-identical kwargs (e.g. ``enable_stubbed`` /
``resume_max_*`` are claude-only; ``opencode_bin`` / ``serve_startup_timeout``
are opencode-only). Rather than force every call site to know which SDK is
active, the factory accepts the union and passes each backend ONLY the kwargs
its ``__init__`` declares. An unknown kind fails fast (§1.3) rather than
silently degrading.
"""

from __future__ import annotations

import inspect
import os

from ascendc_devkit.domain.exceptions import ConfigError
from ascendc_devkit.capabilities.agent.backend import AgentBackend
from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
from ascendc_devkit.capabilities.agent.opencode_backend import OpenCodeBackend
from ascendc_devkit.capabilities.agent.stub_backend import StubBackend

_ENV_VAR = "ASCENDC_AGENT_BACKEND"
_DEFAULT_KIND = "opencode"  # 2.4-verified default; override via config/env

_BACKENDS: dict[str, type[AgentBackend]] = {
    "claude": SDKBackend,
    "opencode": OpenCodeBackend,
}


def _config_kind() -> str | None:
    """Read ``agent_backend.kind`` from orchestration-config.json, or None.

    Reuses runtime_config's already-parsed raw config so there is one config
    file reader. Missing section/key → None (fall through to the default);
    present-but-malformed → ConfigError (fail-fast, §1.3), matching the strict
    policy the rest of runtime_config uses.
    """
    from ascendc_devkit.orchestration.runtime_config import _RAW, _CONFIG_PATH
    raw = _RAW.get("agent_backend")
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ConfigError(str(_CONFIG_PATH),
                          "'agent_backend' must be a JSON object")
    kind = raw.get("kind")
    if kind is None:
        return None
    if not isinstance(kind, str) or kind not in _BACKENDS:
        raise ConfigError(
            str(_CONFIG_PATH),
            f"'agent_backend.kind' must be one of {sorted(_BACKENDS)}, "
            f"got {kind!r}")
    return kind


def resolve_backend_kind(kind: str | None = None) -> str:
    """Resolve which backend to build: explicit > env > config > default."""
    if kind:
        chosen = kind
    else:
        env = os.environ.get(_ENV_VAR)
        chosen = env or _config_kind() or _DEFAULT_KIND
    if chosen not in _BACKENDS:
        raise ConfigError(
            _ENV_VAR,
            f"unknown agent backend {chosen!r}; expected one of "
            f"{sorted(_BACKENDS)}")
    return chosen


def build_agent_backend(kind: str | None = None, *,
                        fallback_to_stub: bool = False, **kwargs) -> AgentBackend:
    """Construct the selected agent backend, passing through only accepted kwargs.

    ``kind`` overrides the env/config resolution when given (used by tests and
    explicit callers). All other kwargs are the union of both constructors'
    parameters; each backend receives only the subset its ``__init__`` declares,
    so a single call site works regardless of which SDK is active.

    ``fallback_to_stub`` — when the configured backend fails to construct (SDK
    unavailable at runtime), fall back to ``StubBackend`` so an op/stage can run
    in deterministic stub mode. The stub fallback decision is an orchestration
    concern (KNOWN 清零 step-3: dispatcher no longer news StubBackend directly);
    dispatcher passes ``fallback_to_stub=True`` at its call sites.
    """
    chosen = resolve_backend_kind(kind)
    cls = _BACKENDS[chosen]
    accepted = set(inspect.signature(cls.__init__).parameters) - {"self"}
    filtered = {k: v for k, v in kwargs.items() if k in accepted}
    try:
        return cls(**filtered)
    except Exception as e:
        if fallback_to_stub:
            # KNOWN 清零 step-3 修正（review M1）：原 dispatcher 三处 fallback 前必打
            # Logger.warn——收进工厂后不得静默吞（§1.2 可诊断）。降级 stub 必须留痕，
            # 否则真 SDK 不可用的 run 与故意 enable_stubbed 不可区分。
            from ascendc_devkit.infra.logger import Logger
            Logger.warn(
                f"agent backend '{chosen}' unavailable, falling back to StubBackend: {e}")
            return StubBackend()
        raise
