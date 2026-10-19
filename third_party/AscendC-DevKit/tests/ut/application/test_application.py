"""Unit tests for L2 Application layer."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from ascendc_devkit.application.report import Report, StageSummary
from ascendc_devkit.orchestration.profile_loader import load_profile, list_profiles
from ascendc_devkit.application.dispatcher import (
    dispatch, dispatch_single_stage, dispatch_single_skill, _load_state_from_run,
    _preflight_user_inputs, _input_present, _preflight_runtime,
    _preflight_input_topology, _preflight_deploy_capability,
)
from ascendc_devkit.domain.exceptions import DecisionPendingError
from ascendc_devkit.domain.exit_codes import EX_DECISION_PENDING, EX_USAGE, EX_DATAERR, EX_CONFIG, EX_TEMPFAIL, EX_TIMEOUT
from ascendc_devkit.capabilities.agent.stub_backend import StubBackend


class TestSigtermHandler:
    """S4 (hard-timeout): SIGTERM is translated to KeyboardInterrupt so it reuses
    the dispatcher's SIGINT graceful-exit path (cancel + save state + EX_SIGINT)
    instead of the default hard-terminate."""

    def test_handler_raises_keyboard_interrupt(self):
        from ascendc_devkit.application.dispatcher import (
            _sigterm_to_keyboard_interrupt)
        with pytest.raises(KeyboardInterrupt):
            _sigterm_to_keyboard_interrupt(None, None)


class TestReport:
    def test_empty_report(self):
        report = Report()
        assert report.run_id == ""
        assert report.stages == []

    def test_stage_summary(self):
        s = StageSummary(name="codegen", elapsed_ms=1000, iterations=1, status="ok")
        assert s.name == "codegen"
        assert s.status == "ok"

    def test_write_markdown(self):
        report = Report(
            run_id="test-123",
            stages=[
                StageSummary(name="entry", elapsed_ms=50, iterations=1, status="ok"),
                StageSummary(name="codegen", elapsed_ms=5000, iterations=2, status="ok"),
            ],
            total_elapsed_ms=5050,
            errors=["Test warning"],
        )
        with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
            path = Path(f.name)
        try:
            report.write_markdown(path)
            content = path.read_text()
            assert "test-123" in content
            assert "entry" in content
            assert "codegen" in content
            assert "Test warning" in content
        finally:
            path.unlink(missing_ok=True)

    def test_write_json(self):
        report = Report(
            run_id="test-json",
            stages=[StageSummary(name="entry", elapsed_ms=50, iterations=1, status="ok")],
            total_elapsed_ms=50,
        )
        with tempfile.NamedTemporaryFile(suffix=".json", mode="w", delete=False) as f:
            path = Path(f.name)
        try:
            report.write_json(path)
            data = json.loads(path.read_text())
            assert data["run_id"] == "test-json"
            assert len(data["stages"]) == 1
        finally:
            path.unlink(missing_ok=True)

    def test_generate_from_events(self):
        events = [
            {"ts": "2026-01-01T00:00:00", "type": "stage_enter", "stage": "entry"},
            {"ts": "2026-01-01T00:00:01", "type": "stage_complete", "stage": "entry", "elapsed_ms": 100, "total_iterations": 1},
            {"ts": "2026-01-01T00:00:01", "type": "stage_enter", "stage": "context"},
            {"ts": "2026-01-01T00:00:02", "type": "stage_complete", "stage": "context", "elapsed_ms": 200, "total_iterations": 1},
        ]
        report = Report._from_events("run-1", events)
        assert report.run_id == "run-1"
        assert len(report.stages) == 2
        assert report.total_elapsed_ms == 300

    def test_generate_from_events_scoped_stage_not_unknown(self, tmp_path):
        """design-halt-diagnostics P2: a stage run under a Runner scope prefix
        (fork-join branch) must resolve to a real status, not "unknown". Root
        cause was stage_enter logging the bare stage.name while stage_complete/
        stage_aborted/iteration_start all used the scope-prefixed label — the
        dict lookup in _from_events never hit. This drives the actual Runner +
        EventLog to reproduce the mismatch, not hand-crafted matching events."""
        from ascendc_devkit.infra.workspace import Workspace
        from ascendc_devkit.infra.event_log import EventLog
        from ascendc_devkit.orchestration.kernel.runner import Runner
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.base import Stage
        from ascendc_devkit.domain.contract import StageIOContract
        from ascendc_devkit.orchestration.kernel.action import NoOp

        class _CleanStage(Stage):
            name = "clean"
            description = "no-op success stage"
            default_max_iterations = 1

            def input_contract(self):
                return StageIOContract(requires=[])

            def output_contract(self):
                return StageIOContract(provides=[])

            def actions(self, state, iteration=1):
                return [NoOp()]

        ws = Workspace.create(output_root=str(tmp_path))
        runner = Runner(workspace=ws)
        runner._scope_prefix = "branch1"
        runner.run_stage(State(mode="new", user_max_iterations=1), _CleanStage())

        events = EventLog.read(ws.events_path)
        report = Report._from_events("run-1", events)
        stage = next(s for s in report.stages if s.name == "branch1/clean")
        assert stage.status == "ok", (
            f"expected 'ok', got {stage.status!r} — stage_enter/stage_complete "
            "stage-name keys must agree under a scope prefix")


class TestProfileLoader:
    def test_load_profile(self):
        profile = load_profile("omni-ops")
        assert profile.name == "omni-ops"

    def test_list_profiles(self):
        profiles = list_profiles()
        assert "omni-ops" in profiles


class TestPreflightUserInputs:
    """_preflight_user_inputs enforces user-supplied inputs that static chain
    validation cannot catch (EntryStage forwards them from task_request)."""

    def test_input_present_rejects_none_and_blank(self):
        from ascendc_devkit.orchestration.kernel.state import State
        s = State(op_name="  ", repo_profile_name="omni-ops")
        assert _input_present(s, "op_name") is False
        assert _input_present(s, "repo_profile_name") is True
        assert _input_present(s, "requirement_path") is False

    def test_new_mode_missing_requirement_blocks(self):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.registry import get_workflow
        wf = get_workflow("generate_ascendc")
        state = State(mode="new", op_name="gelu", non_interactive=True)
        _, code = _preflight_user_inputs(state, wf)
        assert code == EX_USAGE

    def test_new_mode_with_requirement_passes(self, tmp_path):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.registry import get_workflow
        req = tmp_path / "req.md"
        req.write_text("requirement")
        g = tmp_path / "golden.py"
        g.write_text("# golden")
        wf = get_workflow("generate_ascendc")
        state = State(mode="new", op_name="gelu", requirement_path=req,
                      golden_path=g, golden_entry="gelu",
                      golden_input_type="torch", non_interactive=True)
        _, code = _preflight_user_inputs(state, wf)
        assert code is None

    def test_incremental_missing_op_name_blocks(self, tmp_path):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.registry import get_workflow
        req = tmp_path / "req.md"
        req.write_text("requirement")
        wf = get_workflow("generate_ascendc")
        # requirement present, but op_name missing in incremental mode
        state = State(mode="incremental", op_name="", requirement_path=req,
                      non_interactive=True)
        _, code = _preflight_user_inputs(state, wf)
        assert code == EX_USAGE

    def test_workflow_without_requirement_stage_not_blocked(self, tmp_path):
        """generate_ascendc_dev has no requirement stage → no requirement_path needed."""
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.registry import get_workflow
        g = tmp_path / "golden.py"
        g.write_text("# golden")
        wf = get_workflow("generate_ascendc_dev")
        state = State(mode="new", op_name="gelu", golden_path=g,
                      golden_entry="gelu", golden_input_type="torch",
                      non_interactive=True)
        _, code = _preflight_user_inputs(state, wf)
        assert code is None

    def test_interactive_prompt_resolves_missing_input(self, tmp_path):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.registry import get_workflow
        req = tmp_path / "req.md"
        req.write_text("requirement")
        g = tmp_path / "golden.py"
        g.write_text("# golden")
        wf = get_workflow("generate_ascendc")
        state = State(mode="new", op_name="gelu", non_interactive=False,
                      golden_path=g, golden_entry="gelu",
                      golden_input_type="torch")
        with mock.patch("ascendc_devkit.application.dispatcher.input",
                        return_value=str(req)):
            new_state, code = _preflight_user_inputs(state, wf)
        assert code is None
        assert new_state.requirement_path == req

    def test_interactive_prompt_writes_back_to_task_request(self, tmp_path):
        """Regression: a prompted value must also land in task_request, or
        EntryStage.transition re-reads task_request and overwrites State with
        None, leaving the entry stage spinning until max_iterations."""
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.registry import get_workflow
        req = tmp_path / "req.md"
        req.write_text("requirement")
        g = tmp_path / "golden.py"
        g.write_text("# golden")
        wf = get_workflow("generate_ascendc")
        state = State(mode="new", op_name="gelu", non_interactive=False,
                      golden_path=g, golden_entry="gelu",
                      golden_input_type="torch",
                      task_request={"mode": "new", "op_name": "gelu"})
        with mock.patch("ascendc_devkit.application.dispatcher.input",
                        return_value=str(req)):
            new_state, code = _preflight_user_inputs(state, wf)
        assert code is None
        assert new_state.task_request["requirement_path"] == str(req)

    def test_entry_preserves_prompted_requirement_path(self, tmp_path):
        """End-to-end of the fix: after preflight prompts for requirement_path,
        EntryStage.transition reads it back from task_request rather than
        clobbering it with None."""
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.registry import get_workflow, get_stage
        req = tmp_path / "req.md"
        req.write_text("requirement")
        g = tmp_path / "golden.py"
        g.write_text("# golden")
        wf = get_workflow("generate_ascendc")
        state = State(mode="new", op_name="gelu", non_interactive=False,
                      golden_path=g, golden_entry="gelu",
                      golden_input_type="torch",
                      task_request={"mode": "new", "op_name": "gelu"})
        with mock.patch("ascendc_devkit.application.dispatcher.input",
                        return_value=str(req)):
            state, code = _preflight_user_inputs(state, wf)
        assert code is None

        entry = get_stage("entry")()
        state = entry.transition(state, {})
        # The value survives the transition — entry no longer nulls it out.
        assert state.requirement_path == req

    def test_dispatch_new_mode_missing_requirement_returns_usage(self, tmp_path):
        """End-to-end: dispatch() blocks a new run with no requirement."""
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        exit_code = dispatch({
            "mode": "new",
            "op_name": "gelu",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
        })
        assert exit_code == EX_USAGE


class TestPreflightToolchain:
    """Startup CANN+NPU preflight uses workflow.requires_npu to decide
    whether to probe.  Design-only workflows (requires_npu=False) skip.
    Execution workflows (requires_npu=True) probe CANNToolchain + NPURunner
    directly, failing fast before any agent spawns."""

    @pytest.fixture(autouse=True)
    def _isolate_runtime_cache(self):
        """P113: _check_runtime_once 的进程级 cache 在每个 UT 前后清空，隔离。

        cache 按 (workflow.name, enable_stubbed) 缓存；现有用例都用 name="test"，
        不清会跨用例串味（前一个 cache 的 EX_CONFIG 让后一个的 mock 失效）。
        """
        from ascendc_devkit.orchestration import runtime_probe
        runtime_probe._RUNTIME_CHECK_CACHE.clear()
        yield
        runtime_probe._RUNTIME_CHECK_CACHE.clear()

    @staticmethod
    def _workflow(requires_npu: bool):
        """Build a minimal workflow with the given requires_npu flag."""
        from ascendc_devkit.orchestration.workflow import Workflow
        from ascendc_devkit.orchestration.stages.entry import EntryStage
        from ascendc_devkit.orchestration.stages.finalize import FinalizeStage
        return Workflow(
            name="test",
            stages=[EntryStage(), FinalizeStage()],
            requires_npu=requires_npu,
        )

    def test_skips_when_requires_npu_false(self):
        """Design-only workflows skip NPU preflight entirely."""
        from ascendc_devkit.orchestration.kernel.state import State
        wf = self._workflow(requires_npu=False)
        state = State(enable_stubbed=False)
        code = _preflight_runtime(state, wf)
        assert code is None

    def test_skips_when_stubbed(self):
        """--enable-stubbed skips the probe even for NPU workflows."""
        from ascendc_devkit.orchestration.kernel.state import State
        wf = self._workflow(requires_npu=True)
        state = State(enable_stubbed=True)
        code = _preflight_runtime(state, wf)
        assert code is None

    def test_blocks_when_toolchain_missing(self):
        """CANN missing on an NPU workflow → EX_CONFIG."""
        from ascendc_devkit.orchestration.kernel.state import State
        wf = self._workflow(requires_npu=True)
        state = State(enable_stubbed=False)
        with mock.patch(
            "ascendc_devkit.adapters.toolchain.cann.CANNToolchain"
        ) as mock_tc:
            mock_tc.return_value.is_available = False
            mock_tc.return_value.diagnostic_hint.return_value = "source set_env.sh"
            code = _preflight_runtime(state, wf)
        assert code == EX_CONFIG

    def test_blocks_when_npu_missing(self):
        """NPU runtime missing on an NPU workflow → EX_CONFIG."""
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.application import dispatcher
        wf = self._workflow(requires_npu=True)
        state = State(enable_stubbed=False)
        with mock.patch(
            "ascendc_devkit.adapters.toolchain.cann.CANNToolchain"
        ) as mock_tc:
            mock_tc.return_value.is_available = True
            # M1: Check 2 走子进程 smoke，mock _run_npu_smoke_subprocess（不再 mock 主进程 NPURunner）
            with mock.patch("ascendc_devkit.orchestration.runtime_probe._run_npu_smoke_subprocess",
                return_value=(False, "torch_npu unavailable"),
            ):
                code = _preflight_runtime(state, wf)
        assert code == EX_CONFIG

    def test_proceeds_when_both_available(self):
        """CANN + NPU both present on an NPU workflow → proceeds."""
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.application import dispatcher
        wf = self._workflow(requires_npu=True)
        state = State(enable_stubbed=False)
        with mock.patch(
            "ascendc_devkit.adapters.toolchain.cann.CANNToolchain"
        ) as mock_tc:
            mock_tc.return_value.is_available = True
            with mock.patch("ascendc_devkit.orchestration.runtime_probe._run_npu_smoke_subprocess",
                return_value=(True, "ok"),
            ):
                code = _preflight_runtime(state, wf)
        assert code is None

    # —— step-108: Check 3 env 契约回环探针（开跑级拦截）——

    def test_check3_env_contract_violation_blocks_startup(self, monkeypatch):
        """Check 3 失配 → EX_CONFIG（外部 sitecustomize 类毒在 t=0 拦截，
        对照批 20260829-142941-49134b 的 10h 空烧）。探测必须用形态忠实值。"""
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.application import dispatcher
        from ascendc_devkit.infra import env_contract

        wf = self._workflow(requires_npu=True)
        state = State(enable_stubbed=False)
        probed: list[dict] = []

        def fake_probe(env, timeout_sec=10.0):
            probed.append(env)
            return ("ASCEND_CUSTOM_OPP_PATH mutated: expected "
                    "/tmp/po/vendors/custom_ops in actual /tmp/po")

        monkeypatch.setattr(env_contract, "probe_env_contract", fake_probe)
        monkeypatch.setattr(env_contract, "diagnose_env_hooks", lambda: [])
        with mock.patch(
            "ascendc_devkit.adapters.toolchain.cann.CANNToolchain"
        ) as mock_tc:
            mock_tc.return_value.is_available = True
            with mock.patch("ascendc_devkit.orchestration.runtime_probe._run_npu_smoke_subprocess",
                return_value=(True, "ok"),
            ):
                code = _preflight_runtime(state, wf)
        assert code == EX_CONFIG
        # 探测 env 携带形态忠实的合成值（哑值触发不了后缀匹配类毒）
        assert probed and probed[0]["ASCEND_CUSTOM_OPP_PATH"] == (
            env_contract.PREFLIGHT_PROBE_VALUE)

    def test_check3_env_contract_passes_through_when_intact(self, monkeypatch):
        """Check 3 完好 → 不拦（干净机器零行为变化）。"""
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.application import dispatcher
        from ascendc_devkit.infra import env_contract

        wf = self._workflow(requires_npu=True)
        state = State(enable_stubbed=False)
        monkeypatch.setattr(env_contract, "probe_env_contract",
                            lambda env, timeout_sec=10.0: None)
        with mock.patch(
            "ascendc_devkit.adapters.toolchain.cann.CANNToolchain"
        ) as mock_tc:
            mock_tc.return_value.is_available = True
            with mock.patch("ascendc_devkit.orchestration.runtime_probe._run_npu_smoke_subprocess",
                return_value=(True, "ok"),
            ):
                code = _preflight_runtime(state, wf)
        assert code is None

    def test_real_workflows_have_correct_flags(self):
        """Verify each built-in workflow has the correct requires_npu flag."""
        from ascendc_devkit.orchestration.registry import get_workflow
        # Design-only: no NPU needed (runs on CPU machines)
        assert get_workflow("generate_ascendc_se").requires_npu is False, (
            "SE (design-only) must not require NPU")
        # Execution: need NPU for verify/deploy/eval
        assert get_workflow("generate_ascendc").requires_npu is True
        assert get_workflow("generate_ascendc_dev").requires_npu is True
        assert get_workflow("self_evolve_op").requires_npu is True
        assert get_workflow("full_test").requires_npu is True

    # —— P113: runtime 预检进程内缓存 + Lock 串行化 ——

    def test_runtime_check_cached_within_process(self, monkeypatch):
        """P113: 同进程同 workflow 只实跑一次 smoke（cache 命中后续不重复）。"""
        from ascendc_devkit.orchestration import runtime_probe
        calls = {"n": 0}

        def fake_checks():
            calls["n"] += 1
            return None

        monkeypatch.setattr(runtime_probe, "_run_runtime_checks", fake_checks)
        wf = self._workflow(requires_npu=True)
        r1 = runtime_probe._check_runtime_once(wf, False)
        r2 = runtime_probe._check_runtime_once(wf, False)
        r3 = runtime_probe._check_runtime_once(wf, False)
        assert (r1, r2, r3) == (None, None, None)
        assert calls["n"] == 1  # 只实跑 1 次，余命中 cache

    def test_runtime_check_concurrent_serializes_to_one_run(self, monkeypatch):
        """P113: 5 并发调用只实跑 1 次 smoke（Lock 串行化 cache miss）。

        这是 batch resume ThreadPoolExecutor 并发 dispatch 不再触发 ERR99999
        NPU runtime init 冲突的核心契约：5 个并发 task 第一个持锁实跑、其余
        等锁后命中 cache，绝不并发 smoke。
        """
        import threading
        from concurrent.futures import ThreadPoolExecutor
        from ascendc_devkit.orchestration import runtime_probe
        from ascendc_devkit.orchestration.workflow import Workflow
        from ascendc_devkit.orchestration.stages.entry import EntryStage
        from ascendc_devkit.orchestration.stages.finalize import FinalizeStage
        wf = Workflow(name="concurrent_p113",
                      stages=[EntryStage(), FinalizeStage()],
                      requires_npu=True)
        calls = {"n": 0}
        cnt_lock = threading.Lock()

        def fake_checks():
            with cnt_lock:
                calls["n"] += 1
            return None

        monkeypatch.setattr(runtime_probe, "_run_runtime_checks", fake_checks)
        with ThreadPoolExecutor(max_workers=5) as ex:
            results = list(ex.map(
                lambda _: runtime_probe._check_runtime_once(wf, False), range(5)))
        assert all(r is None for r in results)
        assert calls["n"] == 1  # 5 并发只实跑 1 次

    # —— M1: NPU smoke 子进程超时（防 driver hang）——

    def test_npu_smoke_timeout_returns_false_with_hang_reason(self):
        """M1: smoke 子进程超时 → (False, 超时 + driver-hang 诊断)，不卡死主流程。"""
        import subprocess as _sp
        from ascendc_devkit.orchestration.runtime_probe import _run_npu_smoke_subprocess
        with mock.patch(
            "ascendc_devkit.orchestration.npu_probe.subprocess.run",
            side_effect=_sp.TimeoutExpired(cmd="python", timeout=30),
        ):
            ok, reason = _run_npu_smoke_subprocess(30)
        assert ok is False
        assert "超时" in reason
        assert "driver hang" in reason  # 诊断点出疑因

    def test_npu_smoke_subprocess_success(self):
        """M1: smoke 子进程 exit 0 → (True, ok)，reason 带健康卡清单。"""
        from ascendc_devkit.orchestration.runtime_probe import _run_npu_smoke_subprocess
        fake = mock.MagicMock(returncode=0, stderr="", stdout="HEALTHY_CARDS=3,4,5\n")
        with mock.patch(
            "ascendc_devkit.orchestration.npu_probe.subprocess.run",
            return_value=fake,
        ):
            ok, reason = _run_npu_smoke_subprocess(30)
        assert ok is True
        assert "3,4,5" in reason  # 健康卡清单进 reason（可诊断）

    def test_npu_smoke_success_even_when_some_cards_bad(self):
        """单卡坏（driver context 泄漏）不应让整个 smoke 判 fail——子进程脚本枚举
        全部卡、跳过坏卡，只要 ≥1 健康卡 exit 0。脚本须委托统一单点 healthy_cards
        （串行逐卡探测，P113），且枚举全部卡。"""
        from ascendc_devkit.orchestration.runtime_probe import _run_npu_smoke_subprocess
        captured = {}

        def fake_run(*args, **kwargs):
            captured["script"] = args[0][2]
            captured["env"] = kwargs.get("env")
            return mock.MagicMock(returncode=0, stderr="",
                                  stdout="HEALTHY_CARDS=1,2\n")

        with mock.patch(
            "ascendc_devkit.orchestration.npu_probe.subprocess.run",
            side_effect=fake_run,
        ):
            ok, reason = _run_npu_smoke_subprocess(30)
        assert ok is True
        assert "healthy_cards" in captured["script"]  # 委托统一单点（而非线程并行手写探测）
        assert "first_only=True" in captured["script"]  # 至少一张健康卡即停
        assert "range(total)" in captured["script"]  # 枚举全部卡、坏卡跳过
        assert captured["env"] and "PYTHONPATH" in captured["env"]  # 子进程可 import 框架单点

    def test_npu_smoke_subprocess_failure_carries_traceback(self):
        """M1: smoke 子进程 exit 3（异常）→ (False, 含子进程 traceback 供诊断)。"""
        from ascendc_devkit.orchestration.runtime_probe import _run_npu_smoke_subprocess
        fake = mock.MagicMock(returncode=3, stderr="RuntimeError: boom\nERR99999")
        with mock.patch(
            "ascendc_devkit.orchestration.npu_probe.subprocess.run",
            return_value=fake,
        ):
            ok, reason = _run_npu_smoke_subprocess(30)
        assert ok is False
        assert "smoke 异常" in reason
        assert "ERR99999" in reason  # 子进程 traceback 透传


class TestGoldenTopologyPreflight:
    """13 E4: golden is NO LONGER a topology concern. The old '--golden needs
    a verify stage' rule is deleted — golden is a full-chain reference required
    declaratively via the consuming stage's `requires` (_preflight_user_inputs;
    see test_golden_required_declarative.py). Topology therefore never blocks
    golden on any workflow."""

    def _state_with_golden(self, tmp_path):
        from ascendc_devkit.orchestration.kernel.state import State
        g = tmp_path / "golden.py"
        g.write_text("# golden reference\n", encoding="utf-8")
        return State.empty().with_updates(golden_path=g)

    def test_golden_allowed_for_self_evolve_op(self, tmp_path):
        """self_evolve_op contains verify → topology never blocks golden."""
        from ascendc_devkit.orchestration.registry import get_workflow
        wf = get_workflow("self_evolve_op")
        state = self._state_with_golden(tmp_path)
        assert _preflight_input_topology(state, wf) is None

    def test_golden_allowed_for_generate_ascendc(self, tmp_path):
        """Full pipeline → topology never blocks golden."""
        from ascendc_devkit.orchestration.registry import get_workflow
        wf = get_workflow("generate_ascendc")
        state = self._state_with_golden(tmp_path)
        assert _preflight_input_topology(state, wf) is None

    def test_golden_not_rejected_for_design_only_se(self, tmp_path):
        """13 E4: design-only SE no longer hits a topology block on --golden
        (the rule is gone); golden's required-ness is declarative instead."""
        from ascendc_devkit.orchestration.registry import get_workflow
        wf = get_workflow("generate_ascendc_se")
        state = self._state_with_golden(tmp_path)
        assert _preflight_input_topology(state, wf) is None


class TestDeployCapabilityPreflight:
    """G6/D8: a deploy-bearing workflow needs a deploy-capable target profile.

    Resolvable at dispatch (repo_profile + rel_op_dir) → fail fast; otherwise
    defer to the in-session Deployer runtime capability check (codegen's
    redeploy post-P57; deploy is no longer a dedicated stage).
    """

    def test_deploy_capable_profile_passes(self):
        from ascendc_devkit.orchestration.registry import get_workflow
        from ascendc_devkit.orchestration.kernel.state import State
        wf = get_workflow("generate_ascendc")  # has deploy stage
        state = State.empty().with_updates(
            repo_profile_name="cann-bench",
            rel_op_dir="examples/aclnn_launch_example/csrc/ops/add",
        )
        assert _preflight_deploy_capability(state, wf) is None

    def test_deploy_incapable_profile_rejected(self, tmp_path):
        """A profile lacking install_runtime/smoke roles → fail fast (no stub)."""
        from ascendc_devkit.orchestration.registry import get_workflow
        from ascendc_devkit.orchestration.kernel.state import State
        # ops-nn currently declares no deploy roles → incapable.
        wf = get_workflow("generate_ascendc")
        state = State.empty().with_updates(
            repo_profile_name="ops-nn", rel_op_dir="conv/conv3d",
        )
        assert _preflight_deploy_capability(state, wf) == EX_USAGE

    def test_defers_when_profile_unresolvable(self):
        """No repo_profile at dispatch → defer to runtime (returns None)."""
        from ascendc_devkit.orchestration.registry import get_workflow
        from ascendc_devkit.orchestration.kernel.state import State
        wf = get_workflow("generate_ascendc")
        state = State.empty().with_updates(rel_op_dir="ops/add")
        assert _preflight_deploy_capability(state, wf) is None

    def test_skips_for_workflow_without_deploy(self, tmp_path):
        """A design-only workflow (no deploy stage) is unaffected."""
        from ascendc_devkit.orchestration.registry import get_workflow
        from ascendc_devkit.orchestration.kernel.state import State
        wf = get_workflow("generate_ascendc_se")
        state = State.empty().with_updates(
            repo_profile_name="ops-nn", rel_op_dir="conv/conv3d",
        )
        assert _preflight_deploy_capability(state, wf) is None


class TestDispatcherDispatch:
    """Test dispatch() — full 9-stage pipeline execution."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_incremental_mode_dispatches(self, mock_sdk, tmp_path):
        """Incremental mode should dispatch without early return — not blocked.

        SDKBackend is mocked to fail so the dispatcher falls back to the stub
        backend; this keeps the test hermetic (no real LLM call) even when
        Anthropic/Bedrock credentials are present in the environment.
        """
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: test_gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")
        exit_code = dispatch({
            "mode": "incremental",
            "op_name": "test_gelu",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "requirement_path": str(req_file),
            "golden_path": str(golden_file),
            "golden_entry": "test_gelu",
            "golden_input_type": "torch",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
        })
        # Should not return 64 (USAGE error) — incremental mode is now supported
        assert exit_code != 64

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_pipeline_completes_with_stub_fallback(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: test_gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        exit_code = dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "test_gelu",
            "requirement_path": str(req_file),
            "golden_path": str(golden_file),
            "golden_entry": "test_gelu",
            "golden_input_type": "torch",
            "npu_id": 0,
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
            "output_root": str(tmp_path / "output"),
        })
        # Stub backend produces no real requirement, so the design stage's
        # precondition (gate) fails and the workflow halts fast with EX_DATAERR
        # instead of cascading through every downstream stage.
        assert exit_code == EX_DATAERR

        # Verify workspace was created
        output = tmp_path / "output"
        run_dirs = [d for d in output.iterdir() if d.is_dir()]
        assert len(run_dirs) == 1
        workspace = run_dirs[0]

        # events.jsonl must exist
        events_path = workspace / "events.jsonl"
        assert events_path.exists()

        # state_snapshot.json must exist
        state_path = workspace / "state_snapshot.json"
        assert state_path.exists()
        snapshot = json.loads(state_path.read_text())
        assert snapshot["mode"] == "new"
        assert snapshot["op_name"] == "test_gelu"

        # report must still be generated on the halt path
        report_md = workspace / "report.md"
        assert report_md.exists()
        report_json = workspace / "report.json"
        assert report_json.exists()

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_does_not_overwrite_provenance_and_emits_run_resumed(
            self, mock_sdk, tmp_path):
        """bug1 (step-68): resuming a run must NOT overwrite the first run's
        immutable PROVENANCE.json and must emit run_resumed (not a second
        run_started) carrying a diff against the first. Guards the dispatcher
        provenance fork — previously resume re-probed with the stale first
        snapshot and overwrote the original version identity."""
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "target-repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: test_gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")
        output_root = tmp_path / "output"
        common = dict(
            target_repo=str(target_repo), repo_profile="omni-ops",
            requirement_path=str(req_file), golden_path=str(golden_file),
            golden_entry="test_gelu", golden_input_type="torch",
            non_interactive=True, enable_stubbed=True,
            output_root=str(output_root),
        )

        def _events(run_dir):
            return [json.loads(ln)
                    for ln in (run_dir / "events.jsonl").read_text().splitlines()
                    if ln.strip()]

        # Phase 1: first run writes the immutable PROVENANCE.json + run_started.
        dispatch({"mode": "new", "op_name": "test_gelu", **common})
        run_dir = next(d for d in output_root.iterdir() if d.is_dir())
        assert (run_dir / "PROVENANCE.json").exists()
        first_prov_text = (run_dir / "PROVENANCE.json").read_text()
        types_after_first = [e["type"] for e in _events(run_dir)]
        assert types_after_first.count("run_started") == 1
        assert "run_resumed" not in types_after_first

        # Phase 2: resume the same run.
        dispatch({"mode": "new", "op_name": "test_gelu",
                  "resume_from": run_dir.name, **common})

        # PROVENANCE.json is byte-identical (immutable) — NOT overwritten.
        assert (run_dir / "PROVENANCE.json").read_text() == first_prov_text
        # events.jsonl now also carries run_resumed (appended); the first run's
        # single run_started opener is preserved (no second run_started).
        types_after_resume = [e["type"] for e in _events(run_dir)]
        assert types_after_resume.count("run_started") == 1
        assert types_after_resume.count("run_resumed") == 1
        rr = next(e for e in _events(run_dir) if e["type"] == "run_resumed")
        assert rr["resumed_from"] == run_dir.name
        assert isinstance(rr["changes"], dict)
        assert "provenance" in rr

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_pipeline_events_record_stages(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "requirement_path": str(req_file),
            "golden_path": str(golden_file),
            "golden_entry": "gelu",
            "golden_input_type": "torch",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
        })

        output = tmp_path / "output"
        run_dirs = [d for d in output.iterdir() if d.is_dir()]
        events_path = run_dirs[0] / "events.jsonl"
        events = [json.loads(l) for l in events_path.read_text().strip().split("\n") if l.strip()]
        event_types = {e["type"] for e in events}
        assert "stage_enter" in event_types
        assert "stage_complete" in event_types

        # design-halt-diagnostics P2: stage_enter must use the same
        # scope-prefixed label as stage_complete (else Report._from_events'
        # dict lookup never hits and every stage shows status "unknown").
        stages_seen = {e["stage"] for e in events if e["type"] == "stage_enter"}
        assert any(s.endswith("/entry") for s in stages_seen), stages_seen
        completed_seen = {e["stage"] for e in events if e["type"] == "stage_complete"}
        assert completed_seen <= stages_seen, (
            "every completed stage's label must have a matching stage_enter "
            f"label: complete={completed_seen} enter={stages_seen}")

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_pipeline_halts_fast_on_precondition_failure(self, mock_sdk, tmp_path):
        """A precondition failure (missing upstream artifact) halts the workflow
        and returns EX_DATAERR rather than cascading through downstream stages."""
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        exit_code = dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "requirement_path": str(req_file),
            "golden_path": str(golden_file),
            "golden_entry": "gelu",
            "golden_input_type": "torch",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
        })
        assert exit_code == EX_DATAERR

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_dispatch_passes_webhook_url(self, mock_sdk, tmp_path):
        """dispatch() passes webhook_url to SDKBackend constructor."""
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")
        dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "requirement_path": str(req_file),
            "golden_path": str(golden_file),
            "golden_entry": "gelu",
            "golden_input_type": "torch",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
            "webhook_url": "https://hooks.example.com/decisions",
        })
        call_kwargs = mock_sdk.call_args.kwargs
        assert call_kwargs["webhook_url"] == "https://hooks.example.com/decisions"


class TestDispatcherSingleStage:
    """Test dispatch_single_stage() for each stage type."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_entry_stage(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "mode": "new", "task_request": {"mode": "new", "op_name": "gelu"},
        }))
        exit_code = dispatch_single_stage(
            "entry", state_file=state_file, non_interactive=True,
            output_root=str(tmp_path / "output"),
        )
        assert exit_code == 0

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_context_stage(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "mode": "new", "op_name": "gelu",
            "target_repo": str(target_repo), "repo_profile_name": "omni-ops",
        }))
        exit_code = dispatch_single_stage(
            "context", state_file=state_file, non_interactive=True,
            output_root=str(tmp_path / "output"),
        )
        assert exit_code == 0

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_codegen_stage(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        req_file = tmp_path / "req.json"
        req_file.write_text(json.dumps({"op": {"name": "gelu"}}))
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({
            "mode": "new", "op_name": "gelu",
        }))
        exit_code = dispatch_single_stage(
            "codegen", state_file=state_file, non_interactive=True,
            max_iterations=1, requirement_file=req_file,
            output_root=str(tmp_path / "output"),
        )
        # Returns 64 when required fields (design_spec etc.) are missing
        assert exit_code == 64

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_missing_required_fields_returns_64(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        state_file = tmp_path / "state.json"
        state_file.write_text('{"mode": "new"}')
        exit_code = dispatch_single_stage(
            "context", state_file=state_file, non_interactive=True,
            output_root=str(tmp_path / "output"),
        )
        assert exit_code == 64

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_unknown_stage_raises_key_error(self, mock_sdk, tmp_path):
        mock_sdk.return_value = StubBackend()
        state_file = tmp_path / "state.json"
        state_file.write_text('{"mode": "new"}')
        with pytest.raises(KeyError, match="nonexistent"):
            dispatch_single_stage(
                "nonexistent", state_file=state_file, non_interactive=True,
                output_root=str(tmp_path / "output"),
            )

    @mock.patch("ascendc_devkit.application.dispatcher.Runner")
    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_from_run_reuses_existing_run_and_injects_workspace(
            self, mock_sdk, mock_runner_cls, tmp_path):
        """--from-run 复用原 run 目录（不为单 stage 新建），并把 _workspace 挂回 state。

        修复两个硬伤：(1) 单 stage 路径此前只挂 run_id 不挂 _workspace，依赖
        state._workspace 的 stage（requirement/context/precision_debug 子 stage）
        单跑即崩——如 precision_debug 子 stage 的 _common_context 取 run 目录写进
        prompt 给 agent 调 redeploy/run-cases --workspace，_workspace 为 None 时写死
        字面量 <run_dir>；
        (2) from-run 时总 Workspace.create 新建，丢掉原 run 已 deploy 的算子与真实
        snapshot。对齐主 dispatch resume 分支范式（from_existing + 挂回 _workspace）。
        """
        mock_sdk.return_value = StubBackend()
        captured = {}
        runner_inst = mock_runner_cls.return_value
        runner_inst.run_stage.side_effect = (
            lambda state, stage: captured.setdefault("state", state))

        output_root = tmp_path / "output"
        existing = output_root / "fixed-run-id"
        existing.mkdir(parents=True)
        (existing / "state_snapshot.json").write_text(json.dumps({
            "task_request": {"mode": "new", "op_name": "gelu"},
            "op_name": "gelu",
        }))

        exit_code = dispatch_single_stage(
            "entry", from_run_id="fixed-run-id", non_interactive=True,
            output_root=str(output_root),
        )
        assert exit_code == 0
        # 复用原 run，没有为单 stage 新建额外 run 目录
        runs = sorted(p.name for p in output_root.iterdir() if p.is_dir())
        assert runs == ["fixed-run-id"], runs
        # _workspace 挂回 state（不再 None）——依赖它的 stage 单跑前提
        assert captured["state"]._workspace is not None
        assert captured["state"]._workspace.run_id == "fixed-run-id"

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_from_run_missing_returns_usage(self, mock_sdk, tmp_path):
        """--from-run 指向不存在的 run → EX_USAGE 友好报错（不 warn+empty 掩盖成缺字段）。"""
        mock_sdk.return_value = StubBackend()
        exit_code = dispatch_single_stage(
            "entry", from_run_id="no-such-run", non_interactive=True,
            output_root=str(tmp_path / "output"),
        )
        assert exit_code == EX_USAGE

    @mock.patch("ascendc_devkit.application.dispatcher.Runner")
    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_no_from_run_still_injects_workspace(
            self, mock_sdk, mock_runner_cls, tmp_path):
        """无 --from-run（新建 run）也注入 _workspace——修复对所有单 stage 生效，非仅 from-run。"""
        mock_sdk.return_value = StubBackend()
        captured = {}
        runner_inst = mock_runner_cls.return_value
        runner_inst.run_stage.side_effect = (
            lambda state, stage: captured.setdefault("state", state))
        state_file = tmp_path / "state.json"
        state_file.write_text(json.dumps({"task_request": {"op_name": "gelu"}}))
        exit_code = dispatch_single_stage(
            "entry", state_file=state_file, non_interactive=True,
            output_root=str(tmp_path / "output"),
        )
        assert exit_code == 0
        assert captured["state"]._workspace is not None


class TestDispatcherNonInteractiveAbort:
    """Test non-interactive mode with on_decision='abort' flow."""

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_abort_on_decision_exits_with_decision_pending(self, mock_sdk, tmp_path):
        """When Runner raises DecisionPendingError, dispatch returns EX_DECISION_PENDING."""
        from unittest import mock as umock

        mock_instance = mock.MagicMock()
        mock_sdk.return_value = mock_instance

        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: test_gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        # Intercept Runner.run_stage to raise DecisionPendingError
        with umock.patch(
            "ascendc_devkit.orchestration.kernel.runner.Runner.run_stage",
            side_effect=DecisionPendingError(
                question="Which tiling?",
                options=["tile_32", "tile_64"],
                workspace_dir=str(tmp_path),
            ),
        ):
            exit_code = dispatch({
                "mode": "new",
                "target_repo": str(target_repo),
                "repo_profile": "omni-ops",
                "op_name": "test_gelu",
                "requirement_path": str(req_file),
                "golden_path": str(golden_file),
                "golden_entry": "test_gelu",
                "golden_input_type": "torch",
                "output_root": str(tmp_path / "output"),
                "non_interactive": True,
                "on_decision": "abort",
                "max_iterations": 1,
                "enable_stubbed": True,
            })
        assert exit_code == EX_DECISION_PENDING

        # State snapshot should have been saved
        output = tmp_path / "output"
        run_dirs = [d for d in output.iterdir() if d.is_dir()]
        assert len(run_dirs) == 1
        state_path = run_dirs[0] / "state_snapshot.json"
        assert state_path.exists()


class TestDispatcherResume:
    """Test --resume flow."""

    def test_load_state_from_existing_run(self, tmp_path):
        """_load_state_from_run reads state_snapshot.json from a previous run."""
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        ws = tmp_path / "output" / "run-42"
        ws.mkdir(parents=True)
        snapshot = State(mode="new", op_name="gelu", run_id="run-42",
                         stage_iterations={"entry": 1, "context": 1}).to_snapshot()
        (ws / "state_snapshot.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2))

        state = _load_state_from_run("run-42", str(tmp_path / "output"))
        assert state.mode == "new"
        assert state.op_name == "gelu"
        assert state.stage_iterations == {"entry": 1, "context": 1}

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_continues_from_next_stage(self, mock_sdk, tmp_path):
        """Resume should skip completed stages and continue from next."""
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        mock_instance = mock.MagicMock()
        mock_sdk.return_value = mock_instance

        # Create a previous run with 2 completed stages
        ws = tmp_path / "output" / "resume-1"
        ws.mkdir(parents=True)
        target_repo = tmp_path / "repo"
        target_repo.mkdir()

        state = State(
            mode="new", op_name="gelu", run_id="resume-1",
            workflow_name="generate_ascendc",
            target_repo=str(target_repo), repo_profile_name="omni-ops",
            # node_status is the sole resume authority (step-2b B): mark entry +
            # context complete with their real multi-level paths so the executor
            # skips them and advances into requirement.
            node_status={"generate_ascendc/entry": "completed",
                         "generate_ascendc/context": "completed"},
            non_interactive=True, user_max_iterations=1,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2, default=str))
        # Write minimal events
        (ws / "events.jsonl").write_text(
            json.dumps({"ts": "", "type": "stage_enter", "stage": "entry"}) + "\n" +
            json.dumps({"ts": "", "type": "stage_complete", "stage": "entry", "elapsed_ms": 0}) + "\n")

        exit_code = dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
            "resume_from": "resume-1",
        })
        # Resume continues past the completed entry/context stages; with a mock
        # backend no real requirement is produced, so design halts (EX_DATAERR).
        # The point is that resume advanced rather than short-circuiting.
        assert exit_code == EX_DATAERR

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_applies_npu_id_override(self, mock_sdk, tmp_path):
        """--npu-id on resume must override the persisted npu_id (硬 pin 换卡).

        回归：resume State 构造曾缺 npu_id 覆盖，--npu-id 被静默忽略 → 原 device
        不可用（如上下文池耗尽）时无法换卡续跑。现在 CLI int 覆盖 state 值。
        """
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        mock_sdk.return_value = StubBackend()

        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        ws = tmp_path / "output" / "resume-npu"
        ws.mkdir(parents=True)
        state = State(
            mode="new", op_name="gelu", run_id="resume-npu",
            workflow_name="generate_ascendc",
            target_repo=str(target_repo), repo_profile_name="omni-ops",
            npu_id=0,  # 首次 run 用 device 0
            non_interactive=True, user_max_iterations=1,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2,
                       default=str))

        dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
            "npu_id": 2,  # resume 显式覆盖到 device 2
            "resume_from": "resume-npu",
        })

        resumed = json.loads((ws / "state_snapshot.json").read_text())
        assert resumed["npu_id"] == 2

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_binds_op_name_from_state(self, mock_sdk, tmp_path, monkeypatch):
        """AU-7 wiring, resume branch: op_name is bound from ``state.op_name``
        (the resume authority), not from ``task_request`` — the resume
        task_request below deliberately omits "op_name" to prove the fallback
        actually reads state, not just happening to echo an equal CLI value."""
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        mock_instance = mock.MagicMock()
        mock_sdk.return_value = mock_instance
        calls = []
        monkeypatch.setattr(
            "ascendc_devkit.application.dispatcher.bind_op_name",
            lambda name: calls.append(name))

        ws = tmp_path / "output" / "resume-opname"
        ws.mkdir(parents=True)
        target_repo = tmp_path / "repo"
        target_repo.mkdir()

        state = State(
            mode="new", op_name="gelu_from_state", run_id="resume-opname",
            workflow_name="generate_ascendc",
            target_repo=str(target_repo), repo_profile_name="omni-ops",
            node_status={"generate_ascendc/entry": "completed",
                         "generate_ascendc/context": "completed"},
            non_interactive=True, user_max_iterations=1,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2, default=str))
        (ws / "events.jsonl").write_text(
            json.dumps({"ts": "", "type": "stage_enter", "stage": "entry"}) + "\n" +
            json.dumps({"ts": "", "type": "stage_complete", "stage": "entry", "elapsed_ms": 0}) + "\n")

        dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            # op_name deliberately absent — must fall back to state.op_name.
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
            "resume_from": "resume-opname",
        })

        assert calls == ["gelu_from_state"]

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_all_completed_returns_ok(self, mock_sdk, tmp_path):
        """When all stages are done, resume regenerates report and returns 0."""
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        ws = tmp_path / "output" / "done-1"
        ws.mkdir(parents=True)
        # node_status is the sole resume authority (step-2b B): the executor marks
        # the root path (== workflow.name) completed only when the whole tree
        # finishes. A completed root means all-done → report-only.
        state = State(
            mode="new", op_name="gelu", run_id="done-1",
            workflow_name="generate_ascendc",
            node_status={"generate_ascendc": "completed"},
            non_interactive=True, user_max_iterations=1,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2))
        (ws / "events.jsonl").write_text("")

        exit_code = dispatch({
            "mode": "new",
            "output_root": str(tmp_path / "output"),
            "resume_from": "done-1",
        })
        assert exit_code == 0

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_overrides_timeout_from_task_request(self, mock_sdk, tmp_path):
        """P23: resume 应让 CLI 重传的 workflow/stage timeout 覆盖旧 state。

        场景:第一次 stage_timeout=600 超时;resume 传 --stage-timeout 1200 →
        state.stage_timeout_sec 应为 1200(不沿用旧 600);workflow_timeout 同理。
        CLI 默认(workflow=0/stage=None)视为"未传",沿用旧 state。"""
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        mock_instance = mock.MagicMock()
        mock_sdk.return_value = mock_instance

        ws = tmp_path / "output" / "resume-to"
        ws.mkdir(parents=True)
        target_repo = tmp_path / "repo"
        target_repo.mkdir()

        state = State(
            mode="new", op_name="gelu", run_id="resume-to",
            workflow_name="generate_ascendc",
            target_repo=str(target_repo), repo_profile_name="omni-ops",
            node_status={"generate_ascendc/entry": "completed"},
            non_interactive=True, user_max_iterations=1,
            workflow_timeout_sec=3600, stage_timeout_sec=600,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2, default=str))
        (ws / "events.jsonl").write_text("")

        exit_code = dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
            "resume_from": "resume-to",
            "workflow_timeout_sec": 7200,
            "stage_timeout_sec": 1200,
        })
        assert exit_code == EX_DATAERR  # mock backend → design halts,与 test_resume_continues 同

        # 关键:resume 段把新 timeout 写进了 state(覆盖旧 3600/600)
        snap = json.loads((ws / "state_snapshot.json").read_text())
        assert snap["workflow_timeout_sec"] == 7200, "resume 未覆盖 workflow_timeout"
        assert snap["stage_timeout_sec"] == 1200, "resume 未覆盖 stage_timeout"
        # Report should be regenerated
        assert (ws / "report.md").exists()
        assert (ws / "report.json").exists()

    @mock.patch("ascendc_devkit.orchestration.graph_executor.GraphExecutor")
    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_reattaches_workspace(self, mock_sdk, mock_ge, tmp_path):
        """P40: resume 须把 workspace 挂回 state。

        _workspace 是 transient(to_snapshot / from_snapshot 都 pop),不会进
        state_snapshot.json。resume 从 snap 重建 state 后必须重附 _workspace,
        否则 _DesignSubstage._working_dir(state) 因 state._workspace is None 返
        None → runner cwd 退化到 artifacts 根、agent 产物写错位置 →
        _parse_single 读不到 → 「contract unsatisfied: general_design」死循环
        (new-run 分支构造 State 时已传 _workspace,resume 分支对齐)。"""
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        mock_sdk.return_value = mock.MagicMock()
        ws = tmp_path / "output" / "resume-ws"
        ws.mkdir(parents=True)
        target_repo = tmp_path / "repo"
        target_repo.mkdir()

        state = State(
            mode="new", op_name="gelu", run_id="resume-ws",
            workflow_name="generate_ascendc",
            target_repo=str(target_repo), repo_profile_name="omni-ops",
            node_status={"generate_ascendc/entry": "completed"},
            non_interactive=True, user_max_iterations=1,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2, default=str))
        (ws / "events.jsonl").write_text("")

        captured = {}

        def _capture(root, st):
            captured["state"] = st
            return st

        mock_executor = mock_ge.return_value  # GraphExecutor(...) 实例
        mock_executor.execute.side_effect = _capture
        mock_executor.latest_state = None

        dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
            "resume_from": "resume-ws",
        })

        assert "state" in captured, "executor.execute 未被调用"
        assert captured["state"]._workspace is not None, \
            "resume 未把 _workspace 挂回 state(transient 字段须重附,否则 cwd 退化)"

    @mock.patch("ascendc_devkit.orchestration.graph_executor.GraphExecutor")
    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_terminal_halt_message_names_fail_strategy_halt_stage(
            self, mock_sdk, mock_ge, tmp_path):
        """design-halt-diagnostics P3: when GraphExecutor returns a terminal
        state with halt_reason.kind == 'fail_strategy_halt', the dispatcher's
        Logger.error message must name that specific stage and mechanism —
        not the generic 'exhausted its correction budget' text written for
        the OTHER halt mechanism (__halt__)."""
        from ascendc_devkit.orchestration.kernel.state import State

        mock_sdk.return_value = mock.MagicMock()
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        def _terminal(root, st):
            return st.with_updates(
                is_terminal=True,
                halt_reason={"kind": "fail_strategy_halt", "stage": "build",
                            "message": "compile error: undefined symbol"})

        mock_ge.return_value.execute.side_effect = _terminal
        mock_ge.return_value.latest_state = None

        with mock.patch("ascendc_devkit.application.dispatcher.Logger.error") as m:
            exit_code = dispatch({
                "mode": "new",
                "target_repo": str(target_repo),
                "repo_profile": "omni-ops",
                "op_name": "gelu",
                "requirement_path": str(req_file),
                "golden_path": str(golden_file),
                "golden_entry": "gelu",
                "golden_input_type": "torch",
                "output_root": str(tmp_path / "output"),
                "non_interactive": True,
                "max_iterations": 1,
                "enable_stubbed": True,
            })

        assert exit_code == EX_DATAERR
        msgs = [c.args[0] for c in m.call_args_list if c.args]
        halt_msgs = [msg for msg in msgs if "Workflow halted" in msg]
        assert len(halt_msgs) == 1
        assert "fail_strategy=halt" in halt_msgs[0]
        assert "'build'" in halt_msgs[0]
        assert "compile error: undefined symbol" in halt_msgs[0]
        assert "correction budget" not in halt_msgs[0], (
            "fail_strategy_halt message must not reuse the corrective_exhausted text")

    @mock.patch("ascendc_devkit.orchestration.graph_executor.GraphExecutor")
    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_terminal_halt_message_names_corrective_exhausted_stage(
            self, mock_sdk, mock_ge, tmp_path):
        """design-halt-diagnostics P3: when GraphExecutor returns a terminal
        state with halt_reason.kind == 'corrective_exhausted', the dispatcher's
        message must name that stage and describe budget exhaustion — and the
        text must differ from the fail_strategy_halt scenario above."""
        from ascendc_devkit.orchestration.kernel.state import State

        mock_sdk.return_value = mock.MagicMock()
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        def _terminal(root, st):
            return st.with_updates(
                is_terminal=True,
                halt_reason={"kind": "corrective_exhausted", "stage": "verify",
                            "message": "rel error 0.05 exceeds threshold 0.01"})

        mock_ge.return_value.execute.side_effect = _terminal
        mock_ge.return_value.latest_state = None

        with mock.patch("ascendc_devkit.application.dispatcher.Logger.error") as m:
            exit_code = dispatch({
                "mode": "new",
                "target_repo": str(target_repo),
                "repo_profile": "omni-ops",
                "op_name": "gelu",
                "requirement_path": str(req_file),
                "golden_path": str(golden_file),
                "golden_entry": "gelu",
                "golden_input_type": "torch",
                "output_root": str(tmp_path / "output"),
                "non_interactive": True,
                "max_iterations": 1,
                "enable_stubbed": True,
            })

        assert exit_code == EX_DATAERR
        msgs = [c.args[0] for c in m.call_args_list if c.args]
        halt_msgs = [msg for msg in msgs if "Workflow halted" in msg]
        assert len(halt_msgs) == 1
        assert "correction budget" in halt_msgs[0]
        assert "'verify'" in halt_msgs[0]
        assert "rel error 0.05 exceeds threshold 0.01" in halt_msgs[0]
        assert "fail_strategy=halt" not in halt_msgs[0], (
            "corrective_exhausted message must not reuse the fail_strategy_halt text")

    @mock.patch("ascendc_devkit.orchestration.graph_executor.GraphExecutor")
    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_terminal_halt_message_names_upstream_defect(
            self, mock_sdk, mock_ge, tmp_path):
        """P3 (precision-tensorlist-harness-contract): an upstream-defect halt
        (scope_guard: test_design/requirement/golden/deploy owns the failure)
        must be reported as an upstream defect with the scope_reason — NOT
        framed as 'implementation bug the coder could not fix'."""
        from ascendc_devkit.orchestration.kernel.state import State

        mock_sdk.return_value = mock.MagicMock()
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        def _terminal(root, st):
            return st.with_updates(
                is_terminal=True,
                halt_reason={"kind": "upstream_defect", "stage": "test_design",
                            "message": "test_cases shape list-of-lists vs "
                                       "runner contract list[int]"})

        mock_ge.return_value.execute.side_effect = _terminal
        mock_ge.return_value.latest_state = None

        with mock.patch("ascendc_devkit.application.dispatcher.Logger.error") as m:
            exit_code = dispatch({
                "mode": "new",
                "target_repo": str(target_repo),
                "repo_profile": "omni-ops",
                "op_name": "gelu",
                "requirement_path": str(req_file),
                "golden_path": str(golden_file),
                "golden_entry": "gelu",
                "golden_input_type": "torch",
                "output_root": str(tmp_path / "output"),
                "non_interactive": True,
                "max_iterations": 1,
                "enable_stubbed": True,
            })

        assert exit_code == EX_DATAERR
        msgs = [c.args[0] for c in m.call_args_list if c.args]
        halt_msgs = [msg for msg in msgs if "Workflow halted" in msg]
        assert len(halt_msgs) == 1
        assert "upstream defect" in halt_msgs[0]
        assert "'test_design'" in halt_msgs[0]
        assert "list-of-lists" in halt_msgs[0]
        assert "implementation bug" not in halt_msgs[0], (
            "upstream_defect must not be framed as a coder implementation bug")

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_inherits_run_control_when_cli_unset(self, mock_sdk, tmp_path):
        """Bug A(P30 推广到 non_interactive/on_decision/enable_stubbed):
        CLI 未传(default=None)→ resume 沿用 state,不被 CLI 默认值覆盖。

        回归:--non-interactive 曾是 is_flag 默认 False,task_request 永远带 False,
        把首次 run 的 True 覆盖成 False → 非交互变交互。on_decision(default='default')
        /enable_stubbed(default=False)同病。修复后三键 default=None,dispatcher 用
        is not None 区分「未传=继承」与「显式=覆盖」。"""
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        mock_instance = mock.MagicMock()
        mock_sdk.return_value = mock_instance
        ws = tmp_path / "output" / "resume-inherit"
        ws.mkdir(parents=True)
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        state = State(
            mode="new", op_name="gelu", run_id="resume-inherit",
            workflow_name="generate_ascendc",
            target_repo=str(target_repo), repo_profile_name="omni-ops",
            node_status={"generate_ascendc/entry": "completed"},
            non_interactive=True, on_decision="abort", enable_stubbed=True,
            user_max_iterations=1,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2, default=str))
        (ws / "events.jsonl").write_text("")

        dispatch({
            "mode": "new", "target_repo": str(target_repo), "repo_profile": "omni-ops",
            "op_name": "gelu", "output_root": str(tmp_path / "output"),
            "max_iterations": 1, "resume_from": "resume-inherit",
            # CLI default=None 后的真实形态:三键都在、值为 None(=未传)
            "non_interactive": None, "on_decision": None, "enable_stubbed": None,
        })

        snap = json.loads((ws / "state_snapshot.json").read_text())
        assert snap["non_interactive"] is True, "resume 应沿用 state.non_interactive(True)"
        assert snap["on_decision"] == "abort", "resume 应沿用 state.on_decision(abort)"
        assert snap["enable_stubbed"] is True, "resume 应沿用 state.enable_stubbed(True)"

    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_overrides_run_control_when_explicit(self, mock_sdk, tmp_path):
        """对称:CLI 显式传(non-None)→ 覆盖 state。让 resume 能临时切换模式
        (如首次非交互、resume 想交互审核),与 P23 timeout 覆盖语义一致。"""
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        mock_instance = mock.MagicMock()
        mock_sdk.return_value = mock_instance
        ws = tmp_path / "output" / "resume-override"
        ws.mkdir(parents=True)
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        state = State(
            mode="new", op_name="gelu", run_id="resume-override",
            workflow_name="generate_ascendc",
            target_repo=str(target_repo), repo_profile_name="omni-ops",
            node_status={"generate_ascendc/entry": "completed"},
            non_interactive=True, on_decision="default", enable_stubbed=True,
            user_max_iterations=1,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2, default=str))
        (ws / "events.jsonl").write_text("")

        dispatch({
            "mode": "new", "target_repo": str(target_repo), "repo_profile": "omni-ops",
            "op_name": "gelu", "output_root": str(tmp_path / "output"),
            "max_iterations": 1, "resume_from": "resume-override",
            "non_interactive": False, "on_decision": "abort", "enable_stubbed": False,
        })

        snap = json.loads((ws / "state_snapshot.json").read_text())
        assert snap["non_interactive"] is False
        assert snap["on_decision"] == "abort"
        assert snap["enable_stubbed"] is False

    @mock.patch("ascendc_devkit.application.dispatcher.get_workflow")
    @mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend")
    def test_resume_uses_workflow_name_from_state(self, mock_sdk, mock_get_wf,
                                                   tmp_path):
        """resume 必须以 state.workflow_name 为唯一权威,而非 CLI --workflow 默认。

        场景:原 run 是 self_evolve_op(validate 超时被 abort),resume 不传 --workflow。
        回归 bug:dispatcher 用 task_request 默认 'generate_ascendc' → 加载错图、
        节点名前缀错配(generate_ascendc/* vs state 里 self_evolve_op/*)→ 全判未完成 →
        从头重跑、空转。修复后 get_workflow 应收到 state 里的 'self_evolve_op'。
        """
        import json
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.orchestration.registry import get_workflow as real_get_workflow

        mock_instance = mock.MagicMock()
        mock_sdk.return_value = mock_instance

        # spy:记录收到的 workflow name,但仍返回 generate_ascendc 真实图,让 execute
        # 在 mock backend 下跑到 EX_DATAERR(沿用 test_resume_continues 的稳定终态)。
        # self_evolve_op 真实图需 golden 等前置,这里只验证"workflow_name 选择"。
        captured = {}

        def _spy(name):
            captured["name"] = name
            return real_get_workflow("generate_ascendc")

        mock_get_wf.side_effect = _spy

        ws = tmp_path / "output" / "resume-wf"
        ws.mkdir(parents=True)
        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        state = State(
            mode="new", op_name="gelu", run_id="resume-wf",
            workflow_name="self_evolve_op",  # 非 CLI 默认 → 暴露回归
            target_repo=str(target_repo), repo_profile_name="omni-ops",
            node_status={"self_evolve_op/entry": "completed",
                         "self_evolve_op/context": "completed"},
            non_interactive=True, user_max_iterations=1,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2, default=str))
        (ws / "events.jsonl").write_text("")

        exit_code = dispatch({
            "mode": "new",
            "target_repo": str(target_repo),
            "repo_profile": "omni-ops",
            "op_name": "gelu",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "enable_stubbed": True,
            "resume_from": "resume-wf",
            # 故意不传 "workflow" → CLI 默认 generate_ascendc;修复后须被 state 覆盖
        })
        assert captured.get("name") == "self_evolve_op", (
            f"resume 应沿用 state.workflow_name,实际调用 get_workflow("
            f"{captured.get('name')!r})")
        assert exit_code == EX_DATAERR  # mock backend → design halts

    def test_resume_conflicting_workflow_returns_usage(self, tmp_path):
        """CLI 显式 --workflow 与 state.workflow_name 冲突 → 加载期 EX_USAGE(§1.3),
        而非静默用错图从头重跑。workflow 是 run 身份的一部分,resume 不允许换。"""
        import json
        from ascendc_devkit.orchestration.kernel.state import State

        ws = tmp_path / "output" / "resume-conf"
        ws.mkdir(parents=True)
        state = State(
            mode="new", op_name="gelu", run_id="resume-conf",
            workflow_name="self_evolve_op",
            non_interactive=True, user_max_iterations=1,
        )
        (ws / "state_snapshot.json").write_text(
            json.dumps(state.to_snapshot(), ensure_ascii=False, indent=2, default=str))
        (ws / "events.jsonl").write_text("")

        exit_code = dispatch({
            "mode": "new",
            "output_root": str(tmp_path / "output"),
            "non_interactive": True,
            "max_iterations": 1,
            "resume_from": "resume-conf",
            "workflow": "generate_ascendc",  # 与 state 的 self_evolve_op 冲突
        })
        assert exit_code == EX_USAGE


class TestDispatchSingleSkill:
    """dispatch_single_skill tests (Slice 7)."""

    def test_dispatch_single_skill_not_found(self, tmp_path):
        """Returns 1 when skill name doesn't exist."""
        exit_code = dispatch_single_skill(
            "nonexistent-skill-xyz-123",
            output_root=str(tmp_path / "output"),
        )
        assert exit_code == 1

    def test_dispatch_single_skill_with_stub_fallback(self, tmp_path):
        """dispatch_single_skill with StubBackend fallback."""
        from unittest import mock as umock

        # Mock SDKBackend to raise, forcing StubBackend fallback
        with umock.patch(
            "ascendc_devkit.application.dispatcher.build_agent_backend",
            return_value=StubBackend(),
        ):
            with umock.patch(
                "ascendc_devkit.orchestration.skill.load_skill_spec",
                return_value=mock.MagicMock(name="test-skill", path=tmp_path),
            ):
                exit_code = dispatch_single_skill(
                    "test-skill",
                    prompt="test prompt",
                    output_root=str(tmp_path / "output"),
                )
                # StubBackend returns "ok" by default
                assert exit_code == 0


class TestDispatchWithProgressCallback:
    """Verify dispatch() passes progress_callback to Runner and calls it."""

    def test_progress_callback_accepted(self, tmp_path):
        from unittest import mock as umock
        from ascendc_devkit.application.dispatcher import dispatch
        from ascendc_devkit.orchestration.node import SequentialGroup

        task = {
            "mode": "new", "op_name": "gelu",
            "target_repo": str(tmp_path), "repo_profile": "ops-nn",
            "output_root": str(tmp_path / "output"),
        }

        with umock.patch(
            "ascendc_devkit.application.dispatcher.build_agent_backend",
            return_value=StubBackend(),
        ):
            with umock.patch(
                "ascendc_devkit.application.dispatcher.get_workflow",
                return_value=umock.MagicMock(
                    stages=[],
                    # 空 workflow 无 stage，本就不需要 NPU → 显式 requires_npu=False
                    # 跳过 _preflight_runtime 的 CANN/NPU 探测（否则无 NPU 环境报 exit 78，
                    # 与本用例「progress_callback 接线」的关注点无关）。
                    requires_npu=False,
                    validate_chain=lambda: [],
                    validate_agents=lambda: [],
                    root=lambda design_target_chip="":
                        SequentialGroup(name="generate_ascendc", children=[]),
                ),
            ):
                calls = []
                def cb(event_type, stage_name, metadata):
                    calls.append(event_type)

                exit_code = dispatch(task, progress_callback=cb)
                assert exit_code == 0


class TestRepoRollbackHelpers:
    """Task 3.3: dispatcher exits apply D4 rollback strategy."""

    @staticmethod
    def _state_with_baseline(ref="abc123def456"):
        from ascendc_devkit.orchestration.kernel.state import State
        from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
        op = OperatorIdentity(
            spec=OperatorSpec(name="gelu"),
            repo_root=Path("/tmp/repo"),
            op_dir=Path("/tmp/repo/ops/gelu"),
        )
        return State(op_identity=op, target_repo_baseline_ref=ref)

    def test_rollback_invokes_guard_on_hard_failure(self):
        from ascendc_devkit.application import dispatcher as disp
        state = self._state_with_baseline()
        guard = mock.MagicMock()
        guard.rollback.return_value = True
        with mock.patch.object(disp, "_repo_guard_for", return_value=guard):
            disp._rollback_repo_if_needed(state)
        guard.rollback.assert_called_once_with(
            Path("/tmp/repo"), Path("/tmp/repo/ops/gelu"), "abc123def456")

    def test_rollback_noop_without_baseline(self):
        from ascendc_devkit.application import dispatcher as disp
        state = self._state_with_baseline(ref="")
        # _repo_guard_for returns None when no baseline → no rollback attempted.
        assert disp._repo_guard_for(state) is None
        disp._rollback_repo_if_needed(state)  # must not raise

    def test_preserve_does_not_call_rollback(self):
        from ascendc_devkit.application import dispatcher as disp
        state = self._state_with_baseline()
        guard = mock.MagicMock()
        with mock.patch.object(disp, "_repo_guard_for", return_value=guard):
            disp._preserve_repo_with_hint(state)
        # Abort path preserves changes — never destructive.
        guard.rollback.assert_not_called()

    def test_repo_guard_for_none_without_op_identity(self):
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.orchestration.kernel.state import State
        state = State(target_repo_baseline_ref="abc", op_identity=None)
        assert disp._repo_guard_for(state) is None

    def test_env_failure_preserves_not_rolls_back(self, tmp_path):
        """F3: an EnvironmentNotAvailableError mid-run keeps generated code
        (preserve), rather than discarding it (rollback). A missing CANN/NPU is
        an external prerequisite issue, not a code defect."""
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError

        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        # enable_stubbed bypasses the F2 preflight so the run reaches the
        # executor, where we force the env error to exercise the except branch.
        with mock.patch.object(disp, "build_agent_backend", return_value=StubBackend()), \
             mock.patch("ascendc_devkit.orchestration.graph_executor.GraphExecutor.execute",
                        side_effect=EnvironmentNotAvailableError(
                            stage_name="perf", missing="NPU runtime")), \
             mock.patch.object(disp, "_preserve_repo_with_hint") as preserve, \
             mock.patch.object(disp, "_rollback_repo_if_needed") as rollback:
            code = disp.dispatch({
                "mode": "new",
                "target_repo": str(target_repo),
                "repo_profile": "omni-ops",
                "op_name": "gelu",
                "requirement_path": str(req_file),
                "golden_path": str(golden_file),
                "golden_entry": "gelu",
                "golden_input_type": "torch",
                "output_root": str(tmp_path / "output"),
                "non_interactive": True,
                "max_iterations": 1,
                "enable_stubbed": True,
            })
        assert code == EX_CONFIG
        preserve.assert_called_once()
        rollback.assert_not_called()

    def test_timeout_preserves_not_rolls_back(self, tmp_path):
        """step-107 (P1): a WorkflowTimeoutError mid-run keeps generated code
        (preserve), rather than discarding it (rollback). Timeout = budget
        exhausted = "not finished", same pause family as cancel/env/card —
        and the branch already writes the state snapshot FOR resume; rolling
        back the tree would hand resume a session whose memory diverges from
        an empty op_dir."""
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.domain.exceptions import WorkflowTimeoutError

        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        with mock.patch.object(disp, "build_agent_backend", return_value=StubBackend()), \
             mock.patch("ascendc_devkit.orchestration.graph_executor.GraphExecutor.execute",
                        side_effect=WorkflowTimeoutError(
                            0.0, budget_sec=1, elapsed_sec=2)), \
             mock.patch.object(disp, "_preserve_repo_with_hint") as preserve, \
             mock.patch.object(disp, "_rollback_repo_if_needed") as rollback:
            code = disp.dispatch({
                "mode": "new",
                "target_repo": str(target_repo),
                "repo_profile": "omni-ops",
                "op_name": "gelu",
                "requirement_path": str(req_file),
                "golden_path": str(golden_file),
                "golden_entry": "gelu",
                "golden_input_type": "torch",
                "output_root": str(tmp_path / "output"),
                "non_interactive": True,
                "max_iterations": 1,
                "enable_stubbed": True,
            })
        assert code == EX_TIMEOUT
        preserve.assert_called_once()
        rollback.assert_not_called()

    def test_timeout_prints_resume_hint(self, tmp_path):
        """step-107 (P1): the timeout exit surfaces the exact resume command
        (parity with KeyboardInterrupt) — a budget-exhausted run is resumable,
        and the operator must not be left guessing how to continue."""
        from ascendc_devkit.application import dispatcher as disp
        from ascendc_devkit.domain.exceptions import WorkflowTimeoutError

        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\nop_type: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("# golden\n")

        with mock.patch.object(disp, "build_agent_backend", return_value=StubBackend()), \
             mock.patch("ascendc_devkit.orchestration.graph_executor.GraphExecutor.execute",
                        side_effect=WorkflowTimeoutError(
                            0.0, budget_sec=1, elapsed_sec=2)), \
             mock.patch.object(disp, "_print_resume_hint") as resume_hint:
            code = disp.dispatch({
                "mode": "new",
                "target_repo": str(target_repo),
                "repo_profile": "omni-ops",
                "op_name": "gelu",
                "requirement_path": str(req_file),
                "golden_path": str(golden_file),
                "golden_entry": "gelu",
                "golden_input_type": "torch",
                "output_root": str(tmp_path / "output"),
                "non_interactive": True,
                "max_iterations": 1,
                "enable_stubbed": True,
            })
        assert code == EX_TIMEOUT
        resume_hint.assert_called_once()


# ────────────────────────────────────────────────────────────
# P29 / step-16: interrupt → snapshot persistence → resume (dispatcher level).
# The resume SKIP logic is covered elsewhere; these pin the PERSISTENCE path —
# that an interrupt mid-run leaves a snapshot whose node_status reflects the
# completed frontier, so resume skips it.
#
# Interrupt→resume matrix coverage:
#   • SIGKILL / power / OOM (no handler can run): GraphExecutor-level
#     test_kill_then_resume_skips_completed catches the interrupt at the executor
#     boundary and reads the per-node-flush snapshot directly (bypassing every
#     dispatcher handler) + test_write_state_snapshot_is_atomic.
#   • SIGINT (Ctrl+C) / explicit cancel / timeout (handlers DO run): covered
#     here, parametrized — they all flow through the dispatcher's control-
#     exception handlers that write executor.latest_state (kept current per-node
#     by GraphExecutor) via the atomic _write_state_snapshot.
#   • DecisionPending: same dispatcher-handler write mechanism (shared code
#     path) + Runner-level coverage in test_integration.
# ────────────────────────────────────────────────────────────

def _count_stage_enter(events_path, leaf):
    """Count stage_enter events whose stage name is/ends-with `leaf`.

    stage_enter fires once per real stage entry, so the count stays at 1 across
    a skip-on-resume and goes to 2 if the stage wrongly re-ran."""
    if not events_path.exists():
        return 0
    n = 0
    for line in events_path.read_text().splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            e = json.loads(s)
        except Exception:
            continue
        if e.get("type") == "stage_enter":
            st = e.get("stage", "")
            if st == leaf or st.split("/")[-1] == leaf:
                n += 1
    return n


class TestInterruptResumePersistence:
    """For each handler-based interrupt cause: the run halts mid-pipeline, the
    snapshot still reflects the completed frontier, and resume skips it."""

    @pytest.mark.parametrize("exc_kind", ["keyboard", "cancel", "timeout"])
    def test_interrupt_persists_frontier_and_resume_skips(self, tmp_path, exc_kind):
        from ascendc_devkit.capabilities.agent.backend import AgentBackend, AgentResult
        from ascendc_devkit.orchestration.kernel.runner import RunnerCancelledError
        from ascendc_devkit.domain.exceptions import WorkflowTimeoutError
        from ascendc_devkit.domain.exit_codes import EX_SIGINT, EX_TIMEOUT

        exc_map = {
            "keyboard": (KeyboardInterrupt, EX_SIGINT),
            "cancel": (RunnerCancelledError, EX_SIGINT),
            "timeout": (WorkflowTimeoutError, EX_TIMEOUT),
        }
        exc_cls, expected_rc = exc_map[exc_kind]

        class _RaisingBackend(AgentBackend):
            def __init__(self, exc):
                self.exc = exc
                self.spawned = []
            def spawn(self, agent_name, prompt, context, skills=None,
                      model=None, working_dir=None, repo_baseline=None, repo_root=None,
                      stage_name="", branch_label="", resume_session_id=None, resume_prompt=None, primary_skill=None, deadline_monotonic: float | None = None):
                self.spawned.append(agent_name)
                if self.exc is not None:
                    raise self.exc
                return AgentResult(agent_name=agent_name, status="ok", artifacts={})

        target_repo = tmp_path / "repo"
        target_repo.mkdir()
        req_file = tmp_path / "req.yaml"
        req_file.write_text("op: gelu\n")
        golden_file = tmp_path / "golden.py"
        golden_file.write_text("def reference(*a, **k):\n    return a\n")
        output_root = tmp_path / "output"
        common = dict(
            mode="new", workflow="generate_ascendc",
            target_repo=str(target_repo), repo_profile="omni-ops", op_name="gelu",
            requirement_path=str(req_file),
            golden_path=str(golden_file), golden_entry="gelu", golden_input_type="numpy",
            npu_id=0, non_interactive=True, max_iterations=1, enable_stubbed=True,
            output_root=str(output_root),
        )

        # --- Run 1: interrupt at the first agent spawn (requirement stage). ---
        backend1 = _RaisingBackend(exc_cls("simulated interrupt"))
        with mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend",
                        return_value=backend1):
            rc = dispatch(dict(common))
        assert rc == expected_rc, f"{exc_kind}: expected exit {expected_rc}, got {rc}"

        run_dir = next(p for p in output_root.iterdir() if p.is_dir())
        run_id = run_dir.name
        snap_path = run_dir / "state_snapshot.json"
        events_path = run_dir / "events.jsonl"

        # Persistence invariant (what was broken for Ctrl+C): the snapshot
        # reflects entry + context completed — written by per-node flush, and
        # for these caught causes confirmed by the handler's latest_state.
        snap = json.loads(snap_path.read_text())
        assert snap["node_status"].get("generate_ascendc/entry") == "completed", (
            f"{exc_kind}: entry not persisted completed — resume would redo it")
        assert snap["node_status"].get("generate_ascendc/context") == "completed"

        # entry/context were entered exactly once in run 1.
        assert _count_stage_enter(events_path, "entry") == 1
        assert _count_stage_enter(events_path, "context") == 1

        # --- Run 2: resume — entry/context must be skipped, not re-entered. ---
        backend2 = _RaisingBackend(exc=None)
        with mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend",
                        return_value=backend2):
            dispatch(dict(common, resume_from=run_id))

        assert _count_stage_enter(events_path, "entry") == 1, (
            f"{exc_kind}: entry re-entered on resume — skip failed")
        assert _count_stage_enter(events_path, "context") == 1, (
            f"{exc_kind}: context re-entered on resume — skip failed")

