"""UT for CannbenchScorer — the cann-bench kernel_eval scoring adapter.

Moved here from tests/ut/orchestration/test_cannbench_eval.py (the _run_eval
mechanism tests): the stage now only orchestrates, the scorer owns the
kernel_eval subprocess + env + report parse + the new cann_bench_utils
reachability precheck. Invariants (autoload=0, card→--device-id, PYTHONPATH,
--task-dir, infra/LOSS split) are guarded at the scorer's new home (§3.1 TDD).
"""

import json
import subprocess
from types import SimpleNamespace
from unittest import mock

import pytest

from ascendc_devkit.adapters.evaluation.cannbench_scorer import CannbenchScorer
from ascendc_devkit.domain.exceptions import EnvironmentNotAvailableError
from ascendc_devkit.domain.verification import EvalResult


def _completed(returncode: int = 1) -> mock.Mock:
    """A stand-in subprocess.CompletedProcess: kernel_eval 崩溃 → returncode=1。"""
    return mock.Mock(returncode=returncode, stdout="", stderr="")


def _precheck_ok() -> mock.Mock:
    """cann_bench_utils reachability precheck passes (returncode=0)."""
    return mock.Mock(returncode=0, stdout="", stderr="")


def _deploy_stub() -> SimpleNamespace:
    return SimpleNamespace(
        python_path="", install_path="", ld_library_path_add="",
    )


def _scorer_with_precheck_pass() -> CannbenchScorer:
    """Scorer whose precheck is stubbed to pass (so tests target the kernel_eval
    subprocess, not the precheck)."""
    scorer = CannbenchScorer()
    mock.patch.object(scorer, "_precheck_cannbench_utils", return_value="").start()
    return scorer


@pytest.fixture(autouse=True)
def _stub_verify_pin(monkeypatch):
    """Keep scorer UT deterministic and independent of real NPU hardware.

    eval 前的 card_pin.verify_pin 真实探针（main 侧先例织入）在未全局 mock
    subprocess.run 的用例（如超时路由）会做真 NPU 探测——autouse 桩掉，保持
    全文件确定性；TestDeviceProbe 用自己的 monkeypatch 覆盖本桩测集成。"""
    monkeypatch.setattr(
        "ascendc_devkit.adapters.npu.card_pin.verify_pin",
        lambda *args, **kwargs: None,
    )


class TestKernelEvalAutoloadEnv:
    """torch_npu autoload=0 forced into the kernel_eval subprocess env."""

    def test_injects_zero_when_unset(self, tmp_path, monkeypatch):
        monkeypatch.delenv("TORCH_DEVICE_BACKEND_AUTOLOAD", raising=False)
        scorer = _scorer_with_precheck_pass()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            return_value=_completed(),
        ) as mrun:
            scorer.run_eval(tmp_path, tmp_path, "RmsNorm", "rms_norm",
                            _deploy_stub(), 0, ws=None)
        env = mrun.call_args.kwargs["env"]
        assert env["TORCH_DEVICE_BACKEND_AUTOLOAD"] == "0"

    def test_forces_autoload_off_even_when_parent_overrides(self, tmp_path, monkeypatch):
        monkeypatch.setenv("TORCH_DEVICE_BACKEND_AUTOLOAD", "1")
        scorer = _scorer_with_precheck_pass()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            return_value=_completed(),
        ) as mrun:
            scorer.run_eval(tmp_path, tmp_path, "RmsNorm", "rms_norm",
                            _deploy_stub(), 0, ws=None)
        env = mrun.call_args.kwargs["env"]
        assert env["TORCH_DEVICE_BACKEND_AUTOLOAD"] == "0"


class TestCardDeviceIdInjection:
    """P13 (step-116)：op 卡（npu_id 权威值）经双变量 pin 进 eval 子进程 env；
    kernel_eval 的 --device-id 恒传逻辑 0（remap 后子进程内只可见一张卡=0）。
    只 mock OS 边界 subprocess.run；§3.9 真实链路守护，§3.5 无真 NPU 不标 npu。"""

    @staticmethod
    def _device_id_arg(mrun) -> str:
        argv = mrun.call_args.args[0]
        i = argv.index("--device-id")
        return argv[i + 1]

    @staticmethod
    def _pin_env(mrun) -> dict:
        return mrun.call_args.kwargs["env"]

    def test_op_card_pins_env_and_device_id_is_logical_zero(self, tmp_path):
        scorer = _scorer_with_precheck_pass()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            return_value=_completed(),
        ) as mrun:
            scorer.run_eval(tmp_path, tmp_path, "RmsNorm", "rms_norm",
                            _deploy_stub(), 3, ws=None)
        env = self._pin_env(mrun)
        assert env["ASCEND_RT_VISIBLE_DEVICES"] == "3"
        assert env["ASCEND_NPU_ID"] == "0"
        assert self._device_id_arg(mrun) == "0"

    def test_no_npu_id_fails_fast(self, tmp_path):
        """P13：npu_id=None = 调用方跳过了唯一解析点——与 NPURunner.execute
        同款确定性报错（§1.15），不静默落卡 0。"""
        scorer = _scorer_with_precheck_pass()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            return_value=_completed(),
        ), pytest.raises(ValueError, match="single resolution point"):
            scorer.run_eval(tmp_path, tmp_path, "RmsNorm", "rms_norm",
                            _deploy_stub(), None, ws=None)


class TestCannBenchPkgRootOnPythonpath:
    """PYTHONPATH 含 cann_bench 包目录（examples/<ex>/）。"""

    def test_pythonpath_includes_cann_bench_pkg_root(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PYTHONPATH", raising=False)
        repo = tmp_path / "repo"
        example = repo / "examples" / "aclnn_launch_example"
        (example / "cann_bench").mkdir(parents=True)
        src_dir = example / "csrc" / "ops" / "exp"
        src_dir.mkdir(parents=True)
        scorer = _scorer_with_precheck_pass()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            return_value=_completed(),
        ) as mrun:
            scorer.run_eval(src_dir, repo, "Exp", "exp",
                            _deploy_stub(), 0, ws=None)
        pypath = mrun.call_args.kwargs["env"]["PYTHONPATH"]
        assert str(example.resolve()) in pypath.split(":")


class TestTaskDirDiscovery:
    """--task-dir 传**任务目录**（非评测集根）——cann-bench 的 resolve_task_dir
    会拆成 bench_root（match_operators/golden/baseline 不变）+ filter_prefix
    （用例集构造性限定到目标任务）。

    根因回归守护：kernel_eval 的 --operator 过滤大小写不敏感（lower 相等），
    任务集中存在仅差大小写的算子名（如 Aten 拼法 vs 大写 D 拼法）时，传根会
    把孪生任务一并拉入执行与计分——overall 变成两任务求和，且孪生任务的
    4D/NaN/极值用例污染执行环境。任务身份 = rel_path（唯一），不是名字。"""

    def test_run_eval_injects_task_dir_flag(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PYTHONPATH", raising=False)
        repo = tmp_path / "repo"
        op_dir = repo / "bench_lab" / "kernel_bench" / "level2" / "rms_norm"
        op_dir.mkdir(parents=True)
        (op_dir / "cases.yaml").write_text("cases: []")
        scorer = _scorer_with_precheck_pass()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            return_value=_completed(),
        ) as mrun:
            scorer.run_eval(repo, repo, "RmsNorm", "rms_norm",
                            _deploy_stub(), 0, ws=None)
        argv = mrun.call_args.args[0]
        assert "--task-dir" in argv
        i = argv.index("--task-dir")
        # 任务目录（激活 filter_prefix），不是评测集根
        assert argv[i + 1] == str(op_dir)

    def test_resolve_task_dir_returns_task_dir_from_bench_lab(self, tmp_path):
        repo = tmp_path / "repo"
        op_dir = repo / "bench_lab" / "kernel_bench" / "level3" / "exp"
        op_dir.mkdir(parents=True)
        (op_dir / "cases.yaml").write_text("cases: []")
        assert CannbenchScorer()._resolve_task_dir(repo, "exp") == str(op_dir)

    def test_resolve_task_dir_returns_task_dir_from_tasks(self, tmp_path):
        """bench_lab 未命中 → tasks/ 候选集同样返回任务目录。"""
        repo = tmp_path / "repo"
        op_dir = repo / "tasks" / "level2" / "exp"
        op_dir.mkdir(parents=True)
        (op_dir / "cases.yaml").write_text("cases: []")
        assert CannbenchScorer()._resolve_task_dir(repo, "exp") == str(op_dir)

    def test_resolve_task_dir_prefers_bench_lab_over_tasks(self, tmp_path):
        """两个候选集都有该 op 时，bench_lab/kernel_bench（self_evolve 目标集）
        优先——与既有遍历顺序一致的守护。"""
        repo = tmp_path / "repo"
        bl = repo / "bench_lab" / "kernel_bench" / "level3" / "exp"
        bl.mkdir(parents=True)
        (bl / "cases.yaml").write_text("cases: []")
        tk = repo / "tasks" / "level3" / "exp"
        tk.mkdir(parents=True)
        (tk / "cases.yaml").write_text("cases: []")
        assert CannbenchScorer()._resolve_task_dir(repo, "exp") == str(bl)

    def test_resolve_task_dir_falls_back_to_tasks_root_when_op_absent(self, tmp_path):
        """未找到任务目录 → 回退 tasks/ 根（该路径 operators=[] → 既有
        discovery-broken infra 错误，行为不变）。"""
        repo = tmp_path / "repo"
        (repo / "tasks").mkdir(parents=True)
        assert CannbenchScorer()._resolve_task_dir(repo, "exp") == str(repo / "tasks")

    def test_run_eval_injects_eval_seed_zero(self, tmp_path, monkeypatch):
        """review 补充（6199165e F3 scorer 改动缺测试守护）: kernel_eval 显式
        `--eval-seed 0`——devkit harness 的 `(eval_seed + SHA256(case_id)) % 2^31`
        与 kernel_eval config.eval_seed 必须同值，否则两侧输入分裂 → debug 判过而
        eval 判挂。显式传值把"未来 config.eval_seed 变默认"的漂移风险钉死为 0。"""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        repo = tmp_path / "repo"
        op_dir = repo / "bench_lab" / "kernel_bench" / "level2" / "rms_norm"
        op_dir.mkdir(parents=True)
        (op_dir / "cases.yaml").write_text("cases: []")
        scorer = _scorer_with_precheck_pass()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            return_value=_completed(),
        ) as mrun:
            scorer.run_eval(repo, repo, "RmsNorm", "rms_norm",
                            _deploy_stub(), 0, ws=None)
        argv = mrun.call_args.args[0]
        assert "--eval-seed" in argv
        i = argv.index("--eval-seed")
        assert argv[i + 1] == "0"


class TestDeviceProbe:
    """The resolved card is pin-verified (verify_pin) before kernel_eval starts.

    P13 (step-116) 织入：eval 前的真实环境探针走 card_pin.verify_pin（探针 env
    形态与 eval 子进程一致 base_env+pin）；infra 故障经
    EnvironmentNotAvailableError 传播，绝不冒充 LOSS=0。"""

    def test_probe_failure_halts_before_kernel_eval(self, tmp_path, monkeypatch):
        scorer = _scorer_with_precheck_pass()
        monkeypatch.setattr(
            "ascendc_devkit.adapters.npu.card_pin.verify_pin",
            lambda *args, **kwargs: (_ for _ in ()).throw(
                EnvironmentNotAvailableError(
                    stage_name="cannbench_eval",
                    missing="NPU device 0",
                    help_hint="probe failed",
                )
            ),
        )
        kernel_eval = mock.Mock(return_value=_completed())
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            kernel_eval,
        ):
            with pytest.raises(EnvironmentNotAvailableError):
                scorer.run_eval(
                    tmp_path,
                    tmp_path,
                    "RmsNorm",
                    "rms_norm",
                    _deploy_stub(),
                    0,
                    ws=None,
                )
        assert kernel_eval.call_count == 0

    def test_probe_receives_resolved_card_and_eval_env(
        self, tmp_path, monkeypatch
    ):
        seen: dict = {}

        def _spy(card, env=None, **kwargs):
            seen["card"] = card
            seen["env"] = env

        monkeypatch.setattr(
            "ascendc_devkit.adapters.npu.card_pin.verify_pin",
            _spy,
        )
        scorer = _scorer_with_precheck_pass()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            return_value=_completed(),
        ):
            scorer.run_eval(
                tmp_path,
                tmp_path,
                "RmsNorm",
                "rms_norm",
                _deploy_stub(),
                3,
                ws=None,
            )
        assert seen["card"] == 3
        assert seen["env"]["TORCH_DEVICE_BACKEND_AUTOLOAD"] == "0"


class TestCannBenchUtilsPrecheck:
    """可达性预检：cann_bench_utils 不可达 → eval 不跑 + infra error（不 overall=0 掩盖）。"""

    def test_unreachable_returns_infra_error_no_kernel_eval(self, tmp_path, monkeypatch):
        """预检失败 → eval_prepare build 尝试 → 仍不可达 → infra ErrorFeedback，
        kernel_eval subprocess 全程未调。§3.7 诚实报、§1.11 env 忠实。"""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        scorer = CannbenchScorer()  # real precheck + real profile eval_prepare
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            return_value=mock.Mock(returncode=1, stdout="", stderr="No module"),
        ) as mrun:
            eval_result, err = scorer.run_eval(
                tmp_path, tmp_path, "Exp", "exp",
                _deploy_stub(), 0, ws=None,
            )
        # kernel_eval never ran — every subprocess call was a precheck or an
        # eval_prepare build attempt (all failed); no argv is the kernel_eval.cli
        # invocation (a list), build steps run shell=True (a string).
        for call in mrun.call_args_list:
            argv = call.args[0] if call.args else None
            if isinstance(argv, list) and "kernel_eval.cli" in argv:
                pytest.fail("kernel_eval ran despite cann_bench_utils unreachable")
        assert err  # non-empty reason string (stage wraps it into ErrorFeedback)
        assert "cann_bench_utils" in err
        assert eval_result.overall_score == 0.0

    def test_reachable_proceeds_to_kernel_eval(self, tmp_path, monkeypatch):
        """预检通过 → 继续 kernel_eval subprocess（两次 subprocess.run：预检 + 评分）。"""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        scorer = CannbenchScorer()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            side_effect=[_precheck_ok(), _completed()],
        ) as mrun:
            scorer.run_eval(tmp_path, tmp_path, "Exp", "exp",
                            _deploy_stub(), 0, ws=None)
        assert mrun.call_count == 2  # precheck + kernel_eval


class TestDiscoveryAndLossSplit:
    """发现断裂（operators=[]）→ infra；精度差（operators 非空 pass_rate==0）→ LOSS（None）。"""

    def test_parse_report_infra_when_operators_empty(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "exp_eval_1.json").write_text(json.dumps({
            "operators": [], "total_cases": 0,
            "summary": {"overall_score": 0.0, "pass_rate": 0.0},
        }))
        eval_result, err = CannbenchScorer()._parse_report(tmp_path, "", "", "exp")
        assert err  # non-empty reason string (stage wraps it into ErrorFeedback)
        assert eval_result.overall_score == 0.0

    def test_parse_report_infra_when_multiple_operators(self, tmp_path):
        """scope 守卫：报告出现 >1 个 operator = 任务级 scoping 失效（如
        cann-bench 行为漂移把仅差大小写重名的孪生任务一并拉入）。overall 是
        跨任务求和的错数据，不得静默流入 converge——按 infra 错误暴露，reason
        列出全部 rel_path 供归因（拒绝错误冒充）。"""
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "exp_eval_1.json").write_text(json.dumps({
            "operators": [
                {"rel_path": "level3/exp", "total_cases": 20, "passed_cases": 18,
                 "cases": []},
                {"rel_path": "level2/task_0001_aten_exp", "total_cases": 20,
                 "passed_cases": 12, "cases": []},
            ],
            "total_cases": 40,
            "summary": {"overall_score": 82.54, "pass_rate": 0.75},
        }))
        eval_result, err = CannbenchScorer()._parse_report(tmp_path, "", "", "exp")
        assert err
        assert "level3/exp" in err and "level2/task_0001_aten_exp" in err
        assert eval_result.overall_score == 0.0

    @pytest.mark.parametrize("malformed_operators", [
        [None],                       # 单个非 dict 元素 → 既有 first.get 崩溃路径
        [None, {"rel_path": "a"}],    # 多元素含非 dict → 多 operator 守卫崩溃路径
        {"level3/exp": {}},           # operators 非 list
    ])
    def test_parse_report_infra_when_operators_malformed(
            self, tmp_path, malformed_operators):
        """畸形报告（operators 非 dict 列表）→ infra reason 终止，不得以
        AttributeError 异常炸穿 stage（同暴露面单点收口：新守卫的 op.get 与
        既有 first.get 都消费其后的 operators，结构校验统一放在解析点）。"""
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "exp_eval_1.json").write_text(json.dumps({
            "operators": malformed_operators, "total_cases": 1,
            "summary": {"overall_score": 1.0, "pass_rate": 1.0},
        }))
        eval_result, err = CannbenchScorer()._parse_report(tmp_path, "", "", "exp")
        assert err  # infra reason，非异常
        assert "operators" in err
        assert eval_result.overall_score == 0.0

    def test_parse_report_no_infra_when_precision_fail(self, tmp_path):
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "exp_eval_1.json").write_text(json.dumps({
            "operators": [{"total_cases": 5, "passed_cases": 0, "cases": []}],
            "total_cases": 5,
            "summary": {"overall_score": 20.0, "pass_rate": 0.0},
        }))
        eval_result, err = CannbenchScorer()._parse_report(tmp_path, "", "", "exp")
        assert err is None
        assert eval_result.num_cases == 5

    def test_parse_report_no_report_returns_infra(self, tmp_path):
        eval_result, err = CannbenchScorer()._parse_report(tmp_path, "", "", "exp")
        assert err  # non-empty reason string (stage wraps it into ErrorFeedback)

    def test_parse_report_exposes_real_dimension_scores(self, tmp_path):
        """G1: per-dimension scores ARE on operators[0]; the scorer must read
        them (not hardcode 0). Regression for the long-standing false signal
        where a passing eval (func=30) logged identically to one that never
        ran, and a legitimately-0 perf (missing cann-bench baseline anchor)
        could not be distinguished from wholesale failure."""
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "exp_eval_1.json").write_text(json.dumps({
            "operators": [{
                "total_cases": 20, "passed_cases": 20,
                "compilation_score": 20.0,
                "function_score": 30.0,
                "performance_score": 0.0,  # real 0: missing baseline anchor
                "cases": [],
            }],
            "total_cases": 20,
            "summary": {"overall_score": 50.0, "pass_rate": 1.0},
        }))
        eval_result, err = CannbenchScorer()._parse_report(tmp_path, "", "", "exp")
        assert err is None
        assert eval_result.compile_score == 20.0
        assert eval_result.function_score == 30.0
        # perf stays 0 but is now faithfully transcribed, not conflated
        assert eval_result.performance_score == 0.0
        assert eval_result.overall_score == 50.0

    def test_parse_report_missing_dimension_fields_fall_back_to_zero(self, tmp_path):
        """Older report schema without per-dimension fields → graceful 0,
        not a crash."""
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "exp_eval_1.json").write_text(json.dumps({
            "operators": [{"total_cases": 5, "passed_cases": 5, "cases": []}],
            "total_cases": 5,
            "summary": {"overall_score": 42.0, "pass_rate": 1.0},
        }))
        eval_result, err = CannbenchScorer()._parse_report(tmp_path, "", "", "exp")
        assert err is None
        assert eval_result.function_score == 0.0
        assert eval_result.performance_score == 0.0
        assert eval_result.overall_score == 42.0

    def test_parse_report_prefers_output_dir_over_repo_reports(self, tmp_path):
        """step-102: 报告发现顺序 = --output 目录（scorer 自指定的产出位置）优先，
        repo reports/ 回退。两处都有报告时必须取 --output 目录的——顺序倒置会把
        旧批残留报告读成当轮结果（20260827 批 0 分误报的回归守护）。"""
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        out_dir = ws.subprocess_log / "cannbench_eval_exp.partial.json"
        out_dir.mkdir(parents=True)
        (out_dir / "exp_eval_20260828_054218.json").write_text(json.dumps({
            "operators": [{"total_cases": 20, "passed_cases": 20,
                           "compilation_score": 20.0, "function_score": 30.0,
                           "performance_score": 0.0, "cases": []}],
            "total_cases": 20,
            "summary": {"overall_score": 50.01, "pass_rate": 1.0},
        }))
        reports = tmp_path / "reports"  # 旧批残留的过期报告（分数不同）
        reports.mkdir()
        (reports / "exp_eval_20200101_000000.json").write_text(json.dumps({
            "operators": [{"total_cases": 1, "passed_cases": 0, "cases": []}],
            "total_cases": 1,
            "summary": {"overall_score": 9.9, "pass_rate": 0.0},
        }))
        eval_result, err = CannbenchScorer()._parse_report(
            tmp_path, "", "", "exp", ws=ws)
        assert err is None
        assert eval_result.overall_score == 50.01  # --output 目录的报告胜出
        assert eval_result.num_cases == 20

    def test_parse_report_output_dir_empty_falls_back_to_repo_reports(self, tmp_path):
        """step-102: --output 目录存在但无报告（如 kernel_eval 早退）→ 回退
        repo reports/ glob（无 --output/单测场景的行为保持）。"""
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        out_dir = ws.subprocess_log / "cannbench_eval_exp.partial.json"
        out_dir.mkdir(parents=True)  # 目录存在但空
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "exp_eval_1.json").write_text(json.dumps({
            "operators": [{"total_cases": 5, "passed_cases": 5, "cases": []}],
            "total_cases": 5,
            "summary": {"overall_score": 42.0, "pass_rate": 1.0},
        }))
        eval_result, err = CannbenchScorer()._parse_report(
            tmp_path, "", "", "exp", ws=ws)
        assert err is None
        assert eval_result.overall_score == 42.0

    def test_parse_report_no_report_reason_separates_fact_from_guess(self, tmp_path):
        """step-102: 双处皆无报告 → infra reason 必须把「事实」（搜索过哪些位置、
        无报告）与「推测」（kernel_eval 崩溃/stale——未验证）分开表述，不得把
        猜测写成事实断言（§1.10 错误不冒充）。"""
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        eval_result, err = CannbenchScorer()._parse_report(
            tmp_path, "", "", "exp", ws=ws)
        assert eval_result.overall_score == 0.0
        assert err
        # 事实段：列出实际搜索过的位置
        assert str(ws.subprocess_log / "cannbench_eval_exp.partial.json") in err
        assert str(tmp_path / "reports") in err
        # 推测段有显式标记（suspected），与事实分离
        assert "suspected" in err.lower()

    def test_snake_to_pascal(self):
        assert CannbenchScorer.snake_to_pascal("swi_glu") == "SwiGlu"
        assert CannbenchScorer.snake_to_pascal("exp") == "Exp"


class TestEnsureEvalPrepare:
    """eval_prepare (决策1=C 主修复): precheck fail → build via profile → re-check."""

    def test_skips_build_when_reachable(self, tmp_path):
        scorer = CannbenchScorer()
        with mock.patch.object(scorer, "_precheck_cannbench_utils", return_value=""), \
             mock.patch.object(scorer, "_load_eval_prepare_steps", return_value=["stub"]), \
             mock.patch(
                 "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run") as mrun:
            reason = scorer._ensure_eval_prepare({}, tmp_path)
        assert reason == ""
        assert mrun.call_count == 0  # reachable → no build step runs

    def test_builds_when_unreachable_then_rechecks(self, tmp_path):
        scorer = CannbenchScorer()
        step = SimpleNamespace(
            command_template="bash build.sh", cwd="src/cann_bench_utils",
            enabled=True, name="cbu_build")
        with mock.patch.object(
                scorer, "_precheck_cannbench_utils", side_effect=["unreachable", ""]), \
             mock.patch.object(scorer, "_load_eval_prepare_steps", return_value=[step]), \
             mock.patch(
                 "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
                 return_value=mock.Mock(returncode=0, stdout="", stderr="")) as mrun:
            reason = scorer._ensure_eval_prepare({}, tmp_path)
        assert reason == ""  # build fixed it
        assert mrun.call_count == 1

    def test_no_steps_keeps_reason(self, tmp_path):
        scorer = CannbenchScorer()
        with mock.patch.object(scorer, "_precheck_cannbench_utils", return_value="unreachable"), \
             mock.patch.object(scorer, "_load_eval_prepare_steps", return_value=[]):
            reason = scorer._ensure_eval_prepare({}, tmp_path)
        assert reason == "unreachable"  # no eval_prepare → keep precheck reason

    def test_build_fails_returns_reason(self, tmp_path):
        scorer = CannbenchScorer()
        step = SimpleNamespace(
            command_template="bash build.sh", cwd="src/cann_bench_utils",
            enabled=True, name="cbu_build")
        with mock.patch.object(
                scorer, "_precheck_cannbench_utils",
                side_effect=["unreachable", "still unreachable"]), \
             mock.patch.object(scorer, "_load_eval_prepare_steps", return_value=[step]), \
             mock.patch(
                 "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
                 return_value=mock.Mock(returncode=1, stdout="", stderr="err")):
            reason = scorer._ensure_eval_prepare({}, tmp_path)
        assert reason == "still unreachable"

    def test_disabled_step_skipped(self, tmp_path):
        scorer = CannbenchScorer()
        step = SimpleNamespace(
            command_template="bash build.sh", cwd=".", enabled=False, name="off")
        with mock.patch.object(
                scorer, "_precheck_cannbench_utils", side_effect=["bad", ""]), \
             mock.patch.object(scorer, "_load_eval_prepare_steps", return_value=[step]), \
             mock.patch(
                 "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run") as mrun:
            scorer._ensure_eval_prepare({}, tmp_path)
        assert mrun.call_count == 0  # disabled step not run


class TestCannBenchProfileEvalPrepare:
    """cann-bench.yaml declares eval_prepare; other repos' profiles stay empty."""

    def test_cannbench_profile_has_eval_prepare(self):
        from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader
        profile = ProfileLoader.load("cann-bench")
        names = [s.name for s in profile.eval_prepare]
        assert "cann_bench_utils_build" in names
        assert "cann_bench_utils_install" in names

    def test_eval_prepare_empty_for_profile_without_it(self):
        from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader
        profile = ProfileLoader.load("ops-nn")
        assert profile.eval_prepare == ()



class TestEvalTimeoutMessage:
    """§1.10 错误不冒充：eval 超时 ≠ 前置环境缺失（两个不同的外部故障类）。"""

    def test_timeout_reason_is_timeout_not_env_missing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PYTHONPATH", raising=False)
        scorer = CannbenchScorer()
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            side_effect=[_precheck_ok(),
                         subprocess.TimeoutExpired(cmd="kernel_eval", timeout=1)],
        ):
            eval_result, err = scorer.run_eval(
                tmp_path, tmp_path, "Exp", "exp",
                _deploy_stub(), 0, ws=None,
            )
        assert err and "超时" in err
        assert "前置环境缺失" not in err
        assert eval_result.overall_score == 0.0


class TestEvalTimeoutDumpsPartialOutput:
    """§1.11 留可诊断信号：超时前捕获的 partial stdout/stderr 必须落盘——
    是定位 kernel hang 前在跑哪个 case 的唯一线索（20260825-153847-ccad38
    的 subprocess/ 为空即此缺口）。"""

    def test_timeout_dumps_partial_output_to_ws(self, tmp_path, monkeypatch):
        monkeypatch.delenv("PYTHONPATH", raising=False)
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        scorer = CannbenchScorer()
        te = subprocess.TimeoutExpired(cmd="kernel_eval", timeout=1,
                                       output="partial-stdout-last-case",
                                       stderr="partial-stderr-crash-trace")
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            side_effect=[_precheck_ok(), te],
        ):
            _, err = scorer.run_eval(tmp_path, tmp_path, "Exp", "exp",
                                     _deploy_stub(), 0, ws=ws)
        # both partial streams are on disk (not discarded on timeout)
        assert (ws.subprocess_log / "cannbench_eval_exp.stderr.log").exists()
        assert (ws.subprocess_log / "cannbench_eval_exp.stdout.log").exists()
        assert "partial-stderr-crash-trace" in (ws.subprocess_log / "cannbench_eval_exp.stderr.log").read_text()
        assert "partial-stdout-last-case" in (ws.subprocess_log / "cannbench_eval_exp.stdout.log").read_text()


class TestTimeoutDumpRobustness:
    """§1.11 + §1.2：dump 是尽力而为的可观测性——bytes 输入、dump 自身失败都不得
    把「干净 return infra」变成 stage crash（20260826 回放实证 'data must be str,
    not bytes' 把超时路径炸成 stage failed/aborted）。"""

    def test_timeout_dump_handles_bytes_output(self, tmp_path, monkeypatch):
        """TimeoutExpired.output/stderr 在部分路径是 bytes（即使 text=True）——
        必须解码落盘而非 write_text 炸掉。"""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        scorer = CannbenchScorer()
        te = subprocess.TimeoutExpired(cmd="kernel_eval", timeout=1,
                                       output=b"bytes-stdout", stderr=b"bytes-stderr")
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            side_effect=[_precheck_ok(), te],
        ):
            _, err = scorer.run_eval(tmp_path, tmp_path, "Exp", "exp",
                                     _deploy_stub(), 0, ws=ws)
        assert "超时" in err and "前置环境缺失" not in err
        assert (ws.subprocess_log / "cannbench_eval_exp.stdout.log").exists()
        assert "bytes-stdout" in (ws.subprocess_log / "cannbench_eval_exp.stdout.log").read_text()

    def test_dump_failure_does_not_break_timeout_route(self, tmp_path, monkeypatch):
        """dump 自身失败 → WARN 留痕 + 超时仍按 infra 返回（不 stage crash）。"""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        scorer = CannbenchScorer()
        te = subprocess.TimeoutExpired(cmd="kernel_eval", timeout=1,
                                       output="x", stderr="y")
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            side_effect=[_precheck_ok(), te],
        ), mock.patch.object(
            type(scorer), "_dump_partial_output",
            side_effect=RuntimeError("dump boom"),
        ):
            eval_result, err = scorer.run_eval(tmp_path, tmp_path, "Exp", "exp",
                                               _deploy_stub(), 0, ws=ws)
        assert "超时" in err
        assert eval_result.overall_score == 0.0


class TestEvalPartialReportArchive:
    """§P3 方向：kernel_eval 增量写 partial 报告（已完成 case 的完整 perf/accuracy），
    超时/崩溃时归档到 subprocess_log —— 性能分布可查，不被超时墙读成纯 infra 0 分。

    M1（step-102 同族追修）：kernel_eval 的 --output 语义是**报告目录**
    （内写 <op>_eval_<ts>.json，20260827 批实证）——归档按目录发现报告，
    不按文件直读（此前 read_text 目录必抛 IsADirectoryError 被 OSError
    静默吞，超时归档自 --output 引入起从未工作）。"""

    def test_timeout_archives_partial_report(self, tmp_path, monkeypatch):
        """目录形态 + 内含增量报告 → warn 已完成 case 数（total_cases）与
        报告路径——超时下性能分布可查。"""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        scorer = CannbenchScorer()
        te = subprocess.TimeoutExpired(cmd="kernel_eval", timeout=1,
                                       output=b"x", stderr=b"y")
        out_dir = ws.subprocess_log / "cannbench_eval_exp.partial.json"
        out_dir.mkdir(parents=True)
        report = out_dir / "exp_eval_20260828_054218.json"
        report.write_text(json.dumps({
            "total_cases": 9, "passed_cases": 9,
            "summary": {"overall_score": 0.0, "pass_rate": 1.0}}),
            encoding="utf-8")
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            side_effect=[_precheck_ok(), te],
        ), mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.Logger.warn"
        ) as mwarn:
            _, err = scorer.run_eval(tmp_path, tmp_path, "Exp", "exp",
                                     _deploy_stub(), 0, ws=ws)
        assert "超时" in err
        # 归档 warn：已完成 case 数 + 报告路径（这是 §P3 的可观测信号）
        warned = " ".join(str(c) for c in mwarn.call_args_list)
        assert "9 case(s)" in warned
        assert "exp_eval_20260828_054218.json" in warned
        # 报告原样保留在产出位置
        assert report.exists()

    def test_archive_silent_when_dir_not_formed(self, tmp_path, monkeypatch):
        """目录不存在/未成形（首个 case 都没写完）→ 静默 return：无 warn、
        不炸——超时仍按 infra 返回。"""
        monkeypatch.delenv("PYTHONPATH", raising=False)
        ws = SimpleNamespace(subprocess_log=tmp_path / "subprocess")
        scorer = CannbenchScorer()
        te = subprocess.TimeoutExpired(cmd="kernel_eval", timeout=1,
                                       output=b"x", stderr=b"y")
        # 不创建 partial 目录（kernel_eval 早退未写任何东西）
        with mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.subprocess.run",
            side_effect=[_precheck_ok(), te],
        ), mock.patch(
            "ascendc_devkit.adapters.evaluation.cannbench_scorer.Logger.warn"
        ) as mwarn:
            _, err = scorer.run_eval(tmp_path, tmp_path, "Exp", "exp",
                                     _deploy_stub(), 0, ws=ws)
        assert "超时" in err
        warned = " ".join(str(c) for c in mwarn.call_args_list)
        assert "case(s) completed" not in warned  # 无归档信号（无东西可归档）
