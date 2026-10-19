"""Phase 0: ExecContext + CancelToken — per-execution context."""

from pathlib import Path
from ascendc_devkit.orchestration.exec_context import ExecContext, CancelToken


class TestCancelToken:
    def test_default_not_cancelled(self):
        t = CancelToken()
        assert t.is_cancelled() is False

    def test_cancel_sets_flag(self):
        t = CancelToken()
        t.cancel()
        assert t.is_cancelled() is True

    def test_shared_across_references(self):
        t = CancelToken()
        alias = t
        alias.cancel()
        assert t.is_cancelled() is True


class TestExecContext:
    def test_construct_minimal(self):
        ctx = ExecContext(workspace_dir=Path("/tmp/ws"),
                          current_node_path="pipeline/entry")
        assert ctx.current_node_path == "pipeline/entry"
        assert ctx.cancel_flag.is_cancelled() is False

    def test_child_derives_new_path_shares_cancel(self):
        parent = ExecContext(workspace_dir=Path("/tmp/ws"),
                             current_node_path="pipeline")
        child = parent.child(node_path="pipeline/entry",
                             workspace_dir=Path("/tmp/ws/entry"))
        assert child.current_node_path == "pipeline/entry"
        assert child.workspace_dir == Path("/tmp/ws/entry")
        # cancel flag is shared, not copied
        parent.cancel_flag.cancel()
        assert child.cancel_flag.is_cancelled() is True


import time
from ascendc_devkit.orchestration.kernel.runner import Runner
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.base import Stage
from ascendc_devkit.domain.contract import StageIOContract


class _NoopStage(Stage):
    name = "noop"
    default_max_iterations = 1
    def input_contract(self): return StageIOContract()
    def output_contract(self): return StageIOContract()
    def actions(self, state, iteration=1): return []


class TestRunnerExecContext:
    def test_run_stage_without_ctx_still_works(self):
        """Backward compat: no ctx → uses self._* path, behaves as before."""
        r = Runner()
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        out = r.run_stage(s, _NoopStage())
        assert out.stage_iterations.get("noop") == 1

    def test_run_stage_with_ctx_cancel_token(self):
        """When ctx.cancel_flag is set, run_stage raises at iteration boundary."""
        from ascendc_devkit.orchestration.exec_context import ExecContext, CancelToken
        from ascendc_devkit.orchestration.kernel.runner import RunnerCancelledError
        from pathlib import Path
        import pytest
        tok = CancelToken(); tok.cancel()
        ctx = ExecContext(workspace_dir=Path("/tmp"), current_node_path="p/noop",
                          cancel_flag=tok)
        r = Runner()
        s = State.empty().with_updates(non_interactive=True, user_max_iterations=1)
        with pytest.raises(RunnerCancelledError):
            r.run_stage(s, _NoopStage(), ctx=ctx)
