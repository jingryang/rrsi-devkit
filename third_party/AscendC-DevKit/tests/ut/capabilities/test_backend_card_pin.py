"""UT: both agent backends carry the op card pin into their spawn env (P13).

The serve/CLI subprocess env is where the structural pin enters the agent
subtree — every bash tool descendant inherits it (default env inheritance).
"""

from __future__ import annotations

import inspect

from ascendc_devkit.capabilities.agent.opencode_backend import OpenCodeBackend


class TestOpenCodeServeEnvPin:
    def _backend(self, card_pin):
        # ctor spawns nothing (serve starts on first spawn) — safe to build
        return OpenCodeBackend(card_pin=card_pin)

    def test_ctor_accepts_card_pin(self):
        ob = self._backend(3)
        assert ob._card_pin == 3

    def test_serve_env_carries_pin_pair(self, tmp_path, monkeypatch):
        ob = self._backend(5)
        env = ob._build_serve_env({}, str(tmp_path))
        assert env["ASCEND_RT_VISIBLE_DEVICES"] == "5"
        assert env["ASCEND_NPU_ID"] == "0"

    def test_serve_env_without_pin_leaves_vars_untouched(self, tmp_path,
                                                         monkeypatch):
        ob = OpenCodeBackend()
        monkeypatch.delenv("ASCEND_RT_VISIBLE_DEVICES", raising=False)
        monkeypatch.setenv("ASCEND_NPU_ID", "7")  # framework process unpinned
        env = ob._build_serve_env({}, str(tmp_path))
        assert env.get("ASCEND_NPU_ID") == "7"  # inherited, not rewritten


class TestSdkOptionsPin:
    def test_ctor_accepts_card_pin_and_env_helper(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
        sig = inspect.signature(SDKBackend.__init__)
        assert "card_pin" in sig.parameters
        sb = SDKBackend(card_pin=4)
        assert sb._card_pin == 4

    def test_options_env_gets_pin_pair(self):
        from ascendc_devkit.capabilities.agent import sdk_backend as sb_mod
        if not hasattr(sb_mod, "_card_pin_options_env"):
            import pytest
            pytest.fail("sdk_backend must expose _card_pin_options_env(card_pin)")
        assert sb_mod._card_pin_options_env(6) == {
            "env": {"ASCEND_RT_VISIBLE_DEVICES": "6", "ASCEND_NPU_ID": "0"},
        }
        assert sb_mod._card_pin_options_env(None) == {}


class TestFactoryThreadsCardPin:
    def test_factory_passes_card_pin_union_kwarg(self):
        from ascendc_devkit.orchestration.agent_backend_factory import (
            build_agent_backend)
        from ascendc_devkit.capabilities.agent.opencode_backend import (
            OpenCodeBackend)
        backend = build_agent_backend(kind="opencode", card_pin=2)
        assert isinstance(backend, OpenCodeBackend)
        assert backend._card_pin == 2

    def test_factory_threads_card_pin_to_sdk_backend_too(self):
        from ascendc_devkit.orchestration.agent_backend_factory import (
            build_agent_backend)
        from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
        backend = build_agent_backend(kind="claude", card_pin=4)
        assert isinstance(backend, SDKBackend)
        assert backend._card_pin == 4
