"""UT for adapters/npu/card_pin (P13 / step-116 — op-level card lease + pin).

Covers the three single points: ``card_pin_env`` (two-variable pin),
``resolve_op_card`` (op-boundary resolution: lease / pin-env / standalone),
``verify_pin`` (op-start probe — mocked subprocess; the real-probe path is
exercised by @npu ST, not here).
"""

from __future__ import annotations

import subprocess
import types
from unittest.mock import MagicMock

import pytest

from ascendc_devkit.capabilities.agent.stub_backend import StubBackend
from ascendc_devkit.adapters.npu.card_pin import (
    card_pin_env, resolve_op_card, verify_pin)
from ascendc_devkit.adapters.npu.slot import NPUSlotManager
from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError


# ---------------------------------------------------------------- pin env --

class TestCardPinEnv:
    def test_two_variables_single_source(self):
        assert card_pin_env(3) == {
            "ASCEND_RT_VISIBLE_DEVICES": "3",
            "ASCEND_NPU_ID": "0",
        }

    @pytest.mark.parametrize("bad", [-1, "3", None, 1.0, True])
    def test_invalid_card_rejected(self, bad):
        with pytest.raises(ValueError):
            card_pin_env(bad)


# ------------------------------------------------------- op-boundary lease --

class TestResolveOpCardPool:
    def test_preferred_card_leased_with_owner(self):
        pool = NPUSlotManager(max_devices=4, allowed=[0, 1, 2, 3])
        card, release = resolve_op_card(2, pool, owner="op:foo/run1")
        assert card == 2
        assert pool.acquired_holders() == {2: "op:foo/run1"}
        release()
        assert pool.list_acquired() == []

    def test_no_preferred_auto_picks_lowest_free(self):
        pool = NPUSlotManager(max_devices=4, allowed=[0, 1, 2, 3])
        pool.acquire(npu_id=0, owner="sibling")
        card, release = resolve_op_card(None, pool, owner="op:bar/run2")
        assert card == 1  # lowest free, sibling's 0 untouched
        release()

    def test_preferred_held_by_sibling_raises(self):
        pool = NPUSlotManager(max_devices=4, allowed=[0, 1, 2, 3])
        pool.acquire(npu_id=2, owner="sibling")
        with pytest.raises(RuntimeError, match="already acquired"):
            resolve_op_card(2, pool, owner="op:baz/run3")

    def test_release_survives_double_call_and_pool_error(self):
        pool = NPUSlotManager(max_devices=2, allowed=[0, 1])
        card, release = resolve_op_card(0, pool, owner="op:x/r")
        release()
        pool.release(card)  # already released — must not raise here
        release()  # second release call: internally warned, never raises


class TestResolveOpCardStandalone:
    def test_pin_env_wins(self, monkeypatch):
        monkeypatch.setenv("ASCEND_RT_VISIBLE_DEVICES", "5")
        monkeypatch.setenv("ASCEND_NPU_ID", "0")
        card, release = resolve_op_card(3, None)
        assert (card, release) == (5, None)

    def test_pin_env_first_entry_of_list(self, monkeypatch):
        monkeypatch.setenv("ASCEND_RT_VISIBLE_DEVICES", "3,4")
        card, _ = resolve_op_card(None, None)
        assert card == 3

    def test_preferred_when_no_pin_env(self, monkeypatch):
        monkeypatch.delenv("ASCEND_RT_VISIBLE_DEVICES", raising=False)
        monkeypatch.delenv("ASCEND_NPU_ID", raising=False)
        assert resolve_op_card(4, None)[0] == 4

    def test_legacy_npu_id_env_then_zero(self, monkeypatch):
        monkeypatch.delenv("ASCEND_RT_VISIBLE_DEVICES", raising=False)
        monkeypatch.delenv("ASCEND_NPU_ID", raising=False)
        assert resolve_op_card(None, None)[0] == 0
        monkeypatch.setenv("ASCEND_NPU_ID", "6")
        assert resolve_op_card(None, None)[0] == 6
        monkeypatch.setenv("ASCEND_NPU_ID", "junk")
        assert resolve_op_card(None, None)[0] == 0

    def test_negative_pin_env_falls_to_next_priority(self, monkeypatch):
        """M11：负值/畸形 pin env（如 "-3"）视为无 pin env——落下一优先级，
        不经 lstrip("-") 误读成 3（与 card_pin_env 的非负校验同语义）。"""
        monkeypatch.delenv("ASCEND_NPU_ID", raising=False)
        monkeypatch.setenv("ASCEND_RT_VISIBLE_DEVICES", "-3")
        assert resolve_op_card(4, None)[0] == 4          # → preferred
        assert resolve_op_card(None, None)[0] == 0       # 无 preferred → 0
        monkeypatch.setenv("ASCEND_RT_VISIBLE_DEVICES", "3.0")
        assert resolve_op_card(4, None)[0] == 4          # 畸形同判

    def test_negative_legacy_npu_id_falls_to_zero(self, monkeypatch):
        monkeypatch.delenv("ASCEND_RT_VISIBLE_DEVICES", raising=False)
        monkeypatch.setenv("ASCEND_NPU_ID", "-3")
        assert resolve_op_card(None, None)[0] == 0


# ------------------------------------------------------------ op-start probe --

def _fake_run(rc=0, stdout="", stderr="", exc=None):
    """Build a monkeypatch target for subprocess.run inside verify_pin."""
    calls: list[dict] = []

    def _run(cmd, env=None, **kw):
        calls.append({"cmd": cmd, "env": env})
        if exc is not None:
            raise exc
        return types.SimpleNamespace(returncode=rc, stdout=stdout, stderr=stderr)

    return _run, calls


class TestVerifyPin:
    def test_ok_passes_env_shape(self, monkeypatch):
        _run, calls = _fake_run(rc=0)
        monkeypatch.setattr("ascendc_devkit.adapters.npu.card_pin.subprocess.run", _run)
        monkeypatch.setenv("SOME_INHERITED", "yes")
        verify_pin(7)
        (call,) = calls
        assert call["env"]["ASCEND_RT_VISIBLE_DEVICES"] == "7"
        assert call["env"]["ASCEND_NPU_ID"] == "0"
        assert call["env"]["SOME_INHERITED"] == "yes"  # base env merged

    def test_probe_asserts_single_device(self, monkeypatch):
        _run, calls = _fake_run(rc=0)
        monkeypatch.setattr("ascendc_devkit.adapters.npu.card_pin.subprocess.run", _run)
        verify_pin(1)
        assert "device_count()" in calls[0]["cmd"][-1]
        assert "n == 1" in calls[0]["cmd"][-1]

    def test_nonzero_rc_raises_with_stderr_tail(self, monkeypatch):
        _run, _ = _fake_run(rc=1, stderr="AssertionError: device_count=8")
        monkeypatch.setattr("ascendc_devkit.adapters.npu.card_pin.subprocess.run", _run)
        with pytest.raises(EnvironmentNotAvailableError, match="card 2"):
            verify_pin(2)

    def test_timeout_raises(self, monkeypatch):
        _run, _ = _fake_run(exc=subprocess.TimeoutExpired(cmd="x", timeout=5))
        monkeypatch.setattr("ascendc_devkit.adapters.npu.card_pin.subprocess.run", _run)
        with pytest.raises(EnvironmentNotAvailableError, match="timed out"):
            verify_pin(2, timeout_s=5)


# ------------------------------------------------- op lease lifecycle in dispatch --

class TestDispatchOpLeaseLifecycle:
    """dispatch must acquire the op lease once and release it on EVERY
    terminal exit. Drives the real dispatch with the established minimal
    stub task (mirrors test_application's pipeline fixture); the workflow
    halts fast at the design precondition, which still goes through the
    release path — that is the invariant under test."""

    @pytest.fixture
    def pool(self):
        return NPUSlotManager(max_devices=4, allowed=[0, 1, 2, 3])

    def _task(self, tmp_path):
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir(exist_ok=True)
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: test_gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")
        return {
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "test_gelu",
            "requirement_path": str(req_file),
            "golden_path": str(golden_file),
            "golden_entry": "test_gelu",
            "golden_input_type": "torch",
            "npu_id": 0,
            "runtime_target_chip": "A3",
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        }

    def test_lease_released_on_halt_exit_with_pool(self, tmp_path, pool,
                                                   monkeypatch):
        from unittest import mock
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.orchestration import op_card as oc
        release_calls: list[int] = []
        monkeypatch.setattr("ascendc_devkit.orchestration.op_card.verify_pin", lambda card, **kw: None)
        monkeypatch.setattr(
            oc, "resolve_op_card",
            lambda preferred, p, owner="": (
                (2, lambda: release_calls.append(2))))
        with mock.patch.object(disp, "build_agent_backend",
                               return_value=StubBackend()):
            exit_code = disp.dispatch(self._task(tmp_path), card_pool=pool)
        assert exit_code != 0  # halted stub run — any terminal exit counts
        assert release_calls == [2]  # released exactly once
        assert pool.list_acquired() == []  # nothing leaked into the pool

    def test_state_npu_id_becomes_authoritative_op_card(self, tmp_path, pool,
                                                        monkeypatch):
        from unittest import mock
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.orchestration import op_card as oc
        monkeypatch.setattr("ascendc_devkit.orchestration.op_card.verify_pin", lambda card, **kw: None)
        monkeypatch.setattr(
            oc, "resolve_op_card",
            lambda preferred, p, owner="": (3, lambda: None))
        seen: dict = {}

        def _spy_build(**kw):
            seen["card_pin"] = kw.get("card_pin")
            return StubBackend()

        with mock.patch.object(disp, "build_agent_backend", side_effect=_spy_build):
            disp.dispatch(self._task(tmp_path), card_pool=pool)
        assert seen["card_pin"] == 3  # backend got the leased op card
        # and the persisted snapshot carries it as npu_id
        output = tmp_path / "output"
        snapshots = list(output.rglob("state_snapshot.json"))
        assert snapshots, "state snapshot must exist"
        import json as _json
        snap = _json.loads(snapshots[0].read_text())
        assert snap["npu_id"] == 3


class TestDispatchLeaseSymmetry:
    """§step-95 对称性回归门：acquire 之后每一条退出路径恰好释放一次。

    四条路径逐一断言「池清空 + 正确退出码/异常穿透」：
    ① 探针失败（EnvironmentNotAvailableError → EX_CONFIG，不泄租——首版实现
       曾在此漏 release，本组即其回归门）；
    ② 探针通过后的 stretch 段异常（backend→executor 之间，绕过主 finally 的
       盲区——守卫释放后 re-raise）；
    ③ acquire 自身失败（hard-pin 撞兄弟租约 → EX_CONFIG，无租可泄）；
    ④ 探针段 KeyboardInterrupt（BaseException 也必须先释放再穿透）。
    """

    @pytest.fixture
    def pool(self):
        return NPUSlotManager(max_devices=4, allowed=[0, 1, 2, 3])

    def _task(self, tmp_path, npu_id=0):
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir(exist_ok=True)
        (tmp_path / "req.yaml").write_text("op: test_gelu\nop_type: gelu\n")
        (tmp_path / "golden.py").write_text("# golden\n")
        return {"mode": "new", "target_repo": str(target_repo),
                "repo_profile": "omni-ops", "op_name": "test_gelu",
                "requirement_path": str(tmp_path / "req.yaml"),
                "golden_path": str(tmp_path / "golden.py"),
                "golden_entry": "test_gelu", "golden_input_type": "torch",
                "npu_id": npu_id, "runtime_target_chip": "A3",
                "non_interactive": True,
                "max_iterations": 1, "enable_stubbed": True,
                "output_root": str(tmp_path / "output")}

    def test_probe_failure_releases_lease_and_exits_config(
            self, tmp_path, pool, monkeypatch):
        from unittest import mock
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.orchestration import op_card as oc
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError

        def _boom(card, **kw):
            raise EnvironmentNotAvailableError(
                "dispatch", "probe failed (synthetic)")

        monkeypatch.setattr("ascendc_devkit.orchestration.op_card.verify_pin", _boom)
        monkeypatch.setattr(disp, "build_agent_backend",
                            lambda **kw: (_ for _ in ()).throw(
                                AssertionError("must not reach backend")))
        rc = disp.dispatch(self._task(tmp_path), card_pool=pool)
        import ascendc_devkit.domain.exit_codes as ec
        assert rc == ec.EX_CONFIG
        assert pool.list_acquired() == []

    def test_stretch_exception_releases_lease_and_propagates(
            self, tmp_path, pool, monkeypatch):
        from unittest import mock
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.orchestration import op_card as oc
        monkeypatch.setattr("ascendc_devkit.orchestration.op_card.verify_pin", lambda card, **kw: None)
        # stretch killer: Runner ctor raises (between backend and main try)
        def _runner_ctor(*a, **kw):
            raise RuntimeError("synthetic stretch failure")
        monkeypatch.setattr(disp, "Runner", _runner_ctor)
        with mock.patch.object(disp, "build_agent_backend",
                               return_value=StubBackend()):
            with pytest.raises(RuntimeError, match="synthetic stretch"):
                disp.dispatch(self._task(tmp_path), card_pool=pool)
        assert pool.list_acquired() == []

    def test_probe_segment_keyboard_interrupt_releases(
            self, tmp_path, pool, monkeypatch):
        from unittest import mock
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.orchestration import op_card as oc

        def _interrupted(card, **kw):
            raise KeyboardInterrupt()

        monkeypatch.setattr("ascendc_devkit.orchestration.op_card.verify_pin", _interrupted)
        with mock.patch.object(disp, "build_agent_backend",
                               return_value=StubBackend()):
            with pytest.raises(KeyboardInterrupt):
                disp.dispatch(self._task(tmp_path), card_pool=pool)
        assert pool.list_acquired() == []

    def test_acquire_conflict_exits_config_nothing_leaked(
            self, tmp_path, pool, monkeypatch):
        from unittest import mock
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.orchestration import op_card as oc
        pool.acquire(npu_id=2, owner="sibling")  # task also wants card 2
        monkeypatch.setattr(disp, "build_agent_backend",
                            lambda **kw: (_ for _ in ()).throw(
                                AssertionError("must not reach backend")))
        import ascendc_devkit.domain.exit_codes as ec
        rc = disp.dispatch(self._task(tmp_path, npu_id=2), card_pool=pool)
        assert rc == ec.EX_CONFIG
        assert pool.acquired_holders() == {2: "sibling"}  # only the sibling
