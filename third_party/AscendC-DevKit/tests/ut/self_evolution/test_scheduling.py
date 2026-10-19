"""UT — OpScheduler pure-function helpers."""

import json
from pathlib import Path
from unittest import mock

from ascendc_devkit.self_evolution.scheduling import OpScheduler


class TestClassifyExit:
    def test_compile_failure(self):
        assert OpScheduler._classify_exit(
            "error: compile failed in kernel.cpp", ""
        ) == "compile_failed"

    def test_build_failed(self):
        assert OpScheduler._classify_exit(
            "", "build failed at step 3"
        ) == "compile_failed"

    def test_deploy_failure(self):
        assert OpScheduler._classify_exit(
            "deploy stage error", ""
        ) == "deploy_failed"

    def test_install_failure(self):
        assert OpScheduler._classify_exit(
            "", "pip install failed"
        ) == "deploy_failed"

    def test_smoke_failure(self):
        assert OpScheduler._classify_exit(
            "smoke test returned non-zero", ""
        ) == "deploy_failed"

    def test_unknown_crash(self):
        assert OpScheduler._classify_exit(
            "segmentation fault", ""
        ) == "crashed"

    def test_empty_output(self):
        assert OpScheduler._classify_exit("", "") == "crashed"

    def test_case_insensitive(self):
        assert OpScheduler._classify_exit(
            "COMPILE ERROR", ""
        ) == "compile_failed"


class TestParseResult:
    def test_direct_snapshot_path(self, tmp_path):
        out_dir = tmp_path / "run_001"
        out_dir.mkdir()
        snapshot = {
            "eval_result": {
                "overall_score": 85.5,
                "pass_rate": 0.9,
                "compile_score": 17.0,
                "function_score": 25.0,
                "performance_score": 43.5,
                "report_json": "/tmp/report.json",
                "baseline_source": "inherited",
                "num_cases": 20,
                "num_passed": 18,
            },
        }
        (out_dir / "state_snapshot.json").write_text(json.dumps(snapshot))

        result = OpScheduler._parse_result("add", str(out_dir))
        assert result.op_name == "add"
        assert result.status == "ok"
        assert result.eval_result is not None
        assert result.eval_result.overall_score == 85.5
        assert result.eval_result.pass_rate == 0.9
        assert result.eval_result.num_cases == 20
        assert result.eval_result.num_passed == 18

    def test_missing_snapshot_returns_crashed(self, tmp_path):
        out_dir = tmp_path / "nonexistent"
        out_dir.mkdir()
        result = OpScheduler._parse_result("add", str(out_dir))
        assert result.op_name == "add"
        assert result.status == "crashed"
        assert result.eval_result is None

    def test_finds_nested_run_dir(self, tmp_path):
        """When state_snapshot.json is one level deeper (run dir inside output dir)."""
        import time
        out_dir = tmp_path / "output"
        out_dir.mkdir()
        # Create run_001 first (older)
        old_dir = out_dir / "run_001"
        old_dir.mkdir()
        (old_dir / "state_snapshot.json").write_text(
            json.dumps({"eval_result": {"overall_score": 40.0}}))
        # Small delay so mtime differs
        time.sleep(0.01)
        # Create run_003 later (newer, should be picked)
        run_dir = out_dir / "run_003"
        run_dir.mkdir()
        (run_dir / "state_snapshot.json").write_text(
            json.dumps({"eval_result": {"overall_score": 60.0}}))

        result = OpScheduler._parse_result("exp", str(out_dir))
        assert result.status == "ok"
        # Should find run_003 (newest by mtime)
        assert result.eval_result.overall_score == 60.0

    def test_bad_json_returns_crashed(self, tmp_path):
        out_dir = tmp_path / "bad"
        out_dir.mkdir()
        (out_dir / "state_snapshot.json").write_text("{not valid json")

        result = OpScheduler._parse_result("add", str(out_dir))
        assert result.status == "crashed"
        assert result.eval_result is None

    def test_snapshot_without_eval_result(self, tmp_path):
        """Snapshot exists but eval_result field is missing → status ok, eval_result None."""
        out_dir = tmp_path / "run"
        out_dir.mkdir()
        (out_dir / "state_snapshot.json").write_text(json.dumps({"other_field": 1}))

        result = OpScheduler._parse_result("add", str(out_dir))
        assert result.status == "ok"
        assert result.eval_result is None


class TestOpSchedulerEdgeCases:
    def test_eval_all_empty_operators(self):
        scheduler = OpScheduler()
        results = scheduler.eval_all([])
        assert results == []

    def test_injected_run_func_bypasses_subprocess(self):
        """Test injection point: run_func receives all params and returns result."""
        called_with = {}

        def fake_run(**kwargs):
            called_with.update(kwargs)
            from ascendc_devkit.domain.evolution import OpEvalResult
            return OpEvalResult(op_name=kwargs["op_name"], status="ok")

        scheduler = OpScheduler(run_func=fake_run)
        results = scheduler.eval_all(
            operators=["add"],
            op_dir_root=Path("/tmp/ops"),
            output_root="/tmp/out",
            slot_manager=None,
        )
        assert len(results) == 1
        assert results[0].op_name == "add"
        assert results[0].status == "ok"
        assert called_with["op_name"] == "add"
        assert called_with["op_dir_root"] == Path("/tmp/ops")


class TestNpuIdInjectedToSubprocessArgv:
    """训练线 ``--npu-id`` 透传到子 CLI argv 守护（P69 阶段 2）。

    ``OpScheduler._run_subprocess`` 把领到的 card（``slot_manager.acquire()``
    的返回值）作为 ``--npu-id`` 注入子 CLI argv；``None`` 则省略 flag（子
    CLI 走默认/池领）。这是 P69 三个 NPU subprocess 注入点之一（另两个
    NPURunner.execute / cannbench_eval._run_eval 已有 UT 守护 card→spawn
    边界），训练线此前无 argv 断言 —— 本类补这个盲区。只 mock OS 边界
    ``subprocess.run``（捕 argv）；``_run_subprocess`` 的 argv 拼接逻辑全
    真实（§3.9 真实链路守护；§3.5 无真 NPU → 不标 npu）。
    """

    @staticmethod
    def _completed(returncode: int = 1) -> mock.Mock:
        """Non-zero exit short-circuits before _parse_result (no snapshot needed)."""
        return mock.Mock(returncode=returncode, stdout="", stderr="")

    def test_npu_id_flows_to_argv(self):
        """Leased card=3 → argv contains ['--npu-id', '3']."""
        scheduler = OpScheduler()
        with mock.patch(
            "ascendc_devkit.self_evolution.scheduling.subprocess.run",
            return_value=self._completed(),
        ) as mrun:
            scheduler._run_subprocess("add", None, None, npu_id=3)
        argv = mrun.call_args.args[0]
        assert "--npu-id" in argv
        assert argv[argv.index("--npu-id") + 1] == "3"

    def test_none_npu_id_omits_flag(self):
        """npu_id=None → argv omits --npu-id (sub-CLI default path)."""
        scheduler = OpScheduler()
        with mock.patch(
            "ascendc_devkit.self_evolution.scheduling.subprocess.run",
            return_value=self._completed(),
        ) as mrun:
            scheduler._run_subprocess("add", None, None, npu_id=None)
        argv = mrun.call_args.args[0]
        assert "--npu-id" not in argv
