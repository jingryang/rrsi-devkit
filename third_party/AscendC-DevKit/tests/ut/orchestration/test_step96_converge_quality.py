"""step-96 — 收尾链质量事实流转（D1 决策消费事实 / D2 绝对质量态 / D3 死亡位置二分）。

L3 冻结（docs/plan/converge-tail-reverification/02-analysis.md）：
  - D1：converge 决策读 control.json 已测事实——best 已知坏（bad）直接结构化
    记录 + 保留既有 deploy_result，不再用 redeploy+smoke 崩溃重新「发现」
    （99c4c0 unique：best 0/20 重部署 → smoke 507035 → deploy_failed 断链）；
  - D2：best 绝对质量态 good/partial/bad/unmeasured——纯函数从计数客观派生，
    刻度=证据有无（passed==0 ⇔ 零正证据），total==0 = unmeasured ≠ good；
  - D3：smoke 失败按死亡位置二分（codegen.classify_smoke_failure_phase 单点
    §1.15）——launch 后设备侧死亡 = 质量信号（放行新鲜 deploy_result，eval 不
    以 smoke_passed 为门）；launch 前 host 侧 = 部署完整性失败（现行 fallback）。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import ascendc_devkit.orchestration.stages.precision_debug_substages as pds
from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.precision_debug_substages import (
    _classify_best_quality, _converge_to_best_commit)


def _state(tmp_path: Path, deploy_result=None) -> State:
    return State(
        mode="new",
        op_identity=OperatorIdentity(
            spec=OperatorSpec(name="unique"),
            repo_root=tmp_path,
            op_dir=tmp_path / "op"),
        requirement=Requirement(op_spec=OperatorSpec(name="unique")),
        golden_path=Path("/tmp/golden.py"),
        golden_entry="unique",
        golden_input_type="torch",
        deploy_result=deploy_result or DeployResult(smoke_passed=True),
        design_target_chip="A2",
        _workspace=SimpleNamespace(dir=tmp_path, artifacts=tmp_path / "artifacts"),
    )


class TestClassifyBestQuality:
    """D2 纯函数：证据计数 → 四态。"""

    def test_good(self):
        assert _classify_best_quality(
            {"best_passed_count": 20, "best_failed_count": 0}) == "good"

    def test_partial(self):
        assert _classify_best_quality(
            {"best_passed_count": 12, "best_failed_count": 8}) == "partial"

    def test_bad_zero_positive_evidence(self):
        assert _classify_best_quality(
            {"best_passed_count": 0, "best_failed_count": 20}) == "bad"

    def test_unmeasured_total_zero(self):
        """total==0（无任何测量）≠ good——未测量必须显式区分（0==0 陷阱）。"""
        assert _classify_best_quality({}) == "unmeasured"
        assert _classify_best_quality(
            {"best_passed_count": 0, "best_failed_count": 0}) == "unmeasured"


class TestConvergeCheckHandoff:
    """C1（step-119）：converge 交付前自检——最终 deploy_result 是否指向最优被测代码。

    防「rollback/deploy/smoke 失败 keep 旧包 → eval 用非最优 source 而无人察觉」。
    四分支：best 空 / deploy_result 无 source / 一致 / 不一致（标记 converge_mismatch）。
    """

    def test_best_empty_noop(self, tmp_path):
        """无最优 identity 可比对 → 原样返回（诚实，不误标）。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_check_handoff,
        )
        st = _state(tmp_path)
        out = _converge_check_handoff(st, "")
        assert out is st

    def test_deploy_result_no_source_noop(self, tmp_path):
        """deploy_result 无 source_identity（旧格式/非 git）→ 无从比对，不标记。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_check_handoff,
        )
        st = _state(tmp_path)  # deploy_result source_identity=""（默认）
        out = _converge_check_handoff(st, "abc-clean")
        assert out is st

    def test_matching_source_no_mark(self, tmp_path):
        """deploy_result.source_identity == 最优 → 一致，无标记。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_check_handoff,
        )
        st = _state(tmp_path, DeployResult(
            smoke_passed=True, source_identity="abc-clean"))
        out = _converge_check_handoff(st, "abc-clean")
        assert out is st
        assert not (out._debug_checkpoint or {}).get("converge_mismatch")

    def test_mismatch_marks_converge_mismatch(self, tmp_path):
        """deploy_result.source != 最优（keep 旧坏包路径）→ WARN + 标记 converge_mismatch，
        使 eval 报告/用户可见非最优 source。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_check_handoff,
        )
        st = _state(tmp_path, DeployResult(
            smoke_passed=True, source_identity="old-bad-clean"))
        out = _converge_check_handoff(st, "best-clean")
        mm = (out._debug_checkpoint or {}).get("converge_mismatch")
        assert mm == {"deploy_source": "old-bad-clean", "best": "best-clean"}

    def test_same_commit_sha_prefix_no_mark(self, tmp_path):
        """§step-124: deploy stamp（{sha12}-dirty-N 标签）与 best 锚点（全 sha）按
        sha 前缀比对——同一 commit（deploy 时刻带未提交改动）视为一致，不误标。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_check_handoff,
        )
        best = "abc123def456" + "9" * 28          # 全 sha
        st = _state(tmp_path, DeployResult(
            smoke_passed=True, source_identity="abc123def456-dirty-2"))
        out = _converge_check_handoff(st, best)
        assert out is st
        assert not (out._debug_checkpoint or {}).get("converge_mismatch")

    def test_different_commit_sha_prefix_marks(self, tmp_path):
        """§step-124: sha 前缀不同（eval 将用非最优 commit 的旧包）→ 标记
        converge_mismatch，记录双方原值。"""
        from ascendc_devkit.orchestration.stages.precision_debug_substages import (
            _converge_check_handoff,
        )
        best = "fff" + "f" * 37
        st = _state(tmp_path, DeployResult(
            smoke_passed=True, source_identity="abc123def456-clean"))
        out = _converge_check_handoff(st, best)
        mm = (out._debug_checkpoint or {}).get("converge_mismatch")
        assert mm == {"deploy_source": "abc123def456-clean", "best": best}


class TestConvergeQualityAware:
    def _patches(self, monkeypatch, *, rolled=True, deploy=None, err=None):
        calls = {"rollback": 0, "deploy": 0}
        monkeypatch.setattr(
            pds, "_current_head", lambda root: "f" * 40)
        from ascendc_devkit.infra.repo_guard import RepoGuard
        monkeypatch.setattr(
            RepoGuard, "rollback",
            staticmethod(lambda root, op_dir, ref: calls.__setitem__(
                "rollback", calls["rollback"] + 1) or rolled))
        from ascendc_devkit.orchestration.stages.deploy import Deployer
        monkeypatch.setattr(
            Deployer, "deploy",
            lambda self, st: calls.__setitem__(
                "deploy", calls["deploy"] + 1) or (deploy, err))
        return calls

    def test_bad_skips_redeploy_keeps_prior(self, tmp_path, monkeypatch):
        """D1 主用例：best 0/20（烂中之最）→ 不 rollback/不 redeploy（不制造
        崩溃重发现），保留既有 deploy_result。"""
        calls = self._patches(monkeypatch)
        prior = DeployResult(smoke_passed=True)
        dc = {"best_commit": "a" * 40, "best_passed_count": 0,
              "best_failed_count": 20, "status": "running"}
        out = _converge_to_best_commit(_state(tmp_path, prior), dc)
        assert calls["rollback"] == 0 and calls["deploy"] == 0
        assert out.deploy_result is prior

    def test_unmeasured_runs_current_path(self, tmp_path, monkeypatch):
        """total==0 → 无质量信息，smoke 即首测 → 现行重部署路径。"""
        fresh = DeployResult(smoke_passed=True)
        calls = self._patches(monkeypatch, deploy=fresh)
        dc = {"best_commit": "b" * 40}
        out = _converge_to_best_commit(_state(tmp_path), dc)
        assert calls["rollback"] == 1 and calls["deploy"] == 1
        assert out.deploy_result is fresh

    def test_kernel_phase_smoke_fail_accepts_fresh_deploy(self, tmp_path,
                                                          monkeypatch):
        """D3：launch 后设备侧死亡（507035）= 质量信号非部署失败——放行新鲜
        deploy_result（eval 不以 smoke_passed 为门；新鲜包才是安装一致态）。"""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        fresh = DeployResult(smoke_passed=False)
        err = ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="smoke failed",
            details={"stderr_tail": "EZ9999 0x900000053 ... (UI_vector) "
                      "507035 vector core exception MTE invalid GM"})
        calls = self._patches(monkeypatch, deploy=fresh, err=err)
        prior = DeployResult(smoke_passed=True)
        dc = {"best_commit": "c" * 40, "best_passed_count": 12,
              "best_failed_count": 8}  # partial：smoke 崩是真意外场景
        out = _converge_to_best_commit(_state(tmp_path, prior), dc)
        assert calls["deploy"] == 1
        assert out.deploy_result is fresh

    def test_host_phase_smoke_fail_keeps_prior(self, tmp_path, monkeypatch):
        """D3 反向：launch 前 host 侧失败（EZ1008 tiling 家族）= 部署完整性
        失败 → 现行 fallback（保留 prior deploy_result）。"""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        fresh = DeployResult(smoke_passed=False)
        err = ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="smoke failed",
            details={"stderr_tail": "EZ1008: Failed to execute tiling"})
        self._patches(monkeypatch, deploy=fresh, err=err)
        prior = DeployResult(smoke_passed=True)
        dc = {"best_commit": "d" * 40, "best_passed_count": 12,
              "best_failed_count": 8}
        out = _converge_to_best_commit(_state(tmp_path, prior), dc)
        assert out.deploy_result is prior

    def test_unknown_phase_smoke_fail_keeps_prior(self, tmp_path, monkeypatch):
        """无死亡位置证据（phase=None 歧义区）→ 保守沿用现行 fallback。"""
        from ascendc_devkit.orchestration.kernel.state import ErrorFeedback
        fresh = DeployResult(smoke_passed=False)
        err = ErrorFeedback(
            stage_name="deploy", error_type="deploy_failed",
            message="smoke failed", details={"stderr_tail": "weird"})
        self._patches(monkeypatch, deploy=fresh, err=err)
        prior = DeployResult(smoke_passed=True)
        dc = {"best_commit": "e" * 40, "best_passed_count": 12,
              "best_failed_count": 8}
        out = _converge_to_best_commit(_state(tmp_path, prior), dc)
        assert out.deploy_result is prior


class TestSyncDebugResultQuality:
    def test_terminal_state_carries_best_quality(self, tmp_path):
        """D2 流转：_sync_debug_result 把质量态写进 debug_result.best_quality
        （§2.10 结构化字段，收尾链/报表消费字段而非重新测量）。"""
        ws = tmp_path / "artifacts" / "debug" / "unique"
        ws.mkdir(parents=True)
        (ws / "control.json").write_text(json.dumps({
            "status": "running",
            "rounds": 9, "max_iterations": 8,   # exhausted → terminal
            "best_commit": "f" * 40,
            "best_passed_count": 0, "best_failed_count": 20,
            "failing_cases": ["unique_1:1048576"],
        }), encoding="utf-8")
        state = _state(tmp_path)
        out = pds._sync_debug_result(
            state, {"status": "running", "rounds": 9, "max_iterations": 8,
                    "best_commit": "f" * 40,
                    "best_passed_count": 0, "best_failed_count": 20,
                    "failing_cases": ["unique_1:1048576"]})
        assert out.debug_result.best_quality == "bad"
        assert out.debug_result.best_passed_count == 0
        assert out.debug_result.failing_cases == ["unique_1:1048576"]
