"""step-89 — run_tests deploy-precondition UT。

L3（docs/plan/precision-runtests-deploy-precondition/02-analysis.md）：
  - P1（根因）：N1 去 LLM 化后 run-cases 的文件接力前提（last_deploy.json，唯一
    写入者 redeploy）无人保证——fresh entry 必撞闸门 rc=1 → 空转熔断。
  - P2：判据须是「记录可用」（install_path+python_path 非空），非「文件存在」
    （deploy build-failure 分支落盘无路径记录；diagnose 构建失败回滚后留陈旧记录）。
  - P3：redeploy rc≠0 容忍（DeployService.redeploy 无条件落盘，rc 不是判据）。

守护三层：
  - 命令构造：有 workspace+build_command → 测量命令含前提段；无 → 跳过（边缘态旧行为）。
  - shell 语义真实执行（bash 跑真实 helper 输出，不复制文案防漂移）：
    缺文件/空路径记录 → 触发 redeploy（容忍 rc）→ 可用记录落盘 → exit 0；
    redeploy 仍产不出可用记录 → FATAL exit 1；已有可用记录 → 不触发 redeploy。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.precision_debug_substages import (
    RunTestsSubstage, _deploy_precondition,
)


def _state(tmp_path: Path, workspace=None) -> State:
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
        deploy_result=DeployResult(smoke_passed=True),
        design_target_chip="A2",
        _workspace=workspace,
    )


def _run_shell(snippet: str) -> subprocess.CompletedProcess:
    """bash + set -e 环境下执行前提段（与 RunMeasure 同 shell 语义）。"""
    return subprocess.run(["bash", "-c", "set -e\n" + snippet],
                          capture_output=True, text=True, timeout=60)


def _fake_redeploy(tmp_path: Path, write_usable: bool) -> str:
    """fake build_command：touch marker（证明被调用）+ 按需写可用/无用记录。"""
    script = tmp_path / ("fake_redeploy_ok.sh" if write_usable else "fake_redeploy_bad.sh")
    body = ["#!/bin/bash", f"touch {tmp_path / 'redeploy_called.marker'}"]
    if write_usable:
        body += [
            "mkdir -p \"$(dirname \"$1\")\"",
            "printf '%s' '{\"install_path\": \"/opp\", \"python_path\": \"/py\"}' > \"$1\"",
            "exit 1",  # 关键：redeploy rc=1（deploy 失败）也必须被容忍——rc 不是判据
        ]
    script.write_text("\n".join(body) + "\n", encoding="utf-8")
    script.chmod(0o755)
    return f"bash {script} {{last_deploy}}"


class TestCommandConstruction:
    def test_measure_command_contains_precondition(self, tmp_path):
        ws = SimpleNamespace(dir=tmp_path, artifacts=tmp_path / "artifacts")
        s = RunTestsSubstage()
        ctx = s._common_context(_state(tmp_path, workspace=ws))
        dbg = tmp_path / "artifacts" / "debug" / "unique"
        cmd = s._build_measure_command(ctx, None, dbg, tmp_path, 0)
        assert "[deploy-precondition]" in cmd
        assert "last_deploy.json" in cmd
        assert ctx["build_command"] in cmd
        assert "FATAL" in cmd
        # 前提段在 run-cases 之前（构造性保证：先保证前提再测量）
        assert cmd.index("deploy-precondition") < cmd.index("--label run_tests")

    def test_no_build_command_skips_precondition(self, tmp_path):
        """无 workspace（build_command 空）→ 前提段整体跳过，run 段保留（边缘态旧行为）。"""
        s = RunTestsSubstage()
        ctx = s._common_context(_state(tmp_path))
        cmd = s._build_measure_command(ctx, None, tmp_path / "debug" / "unique",
                                       tmp_path, 0)
        assert "deploy-precondition" not in cmd
        assert "build-failed-case-queue" in cmd


class TestShellSemantics:
    """真实 bash 执行 _deploy_precondition 输出（单点文案，防 UT/实现漂移）。"""

    def _snippet(self, tmp_path: Path, build_cmd: str) -> str:
        return _deploy_precondition(tmp_path / "debug" / "unique", build_cmd)

    def test_missing_record_triggers_redeploy_then_pass(self, tmp_path):
        build = _fake_redeploy(tmp_path, write_usable=True).replace(
            "{last_deploy}", str(tmp_path / "debug" / "unique" / "last_deploy.json"))
        r = _run_shell(self._snippet(tmp_path, build))
        assert r.returncode == 0, r.stderr
        assert (tmp_path / "redeploy_called.marker").exists()

    def test_unusable_record_triggers_redeploy(self, tmp_path):
        """P2：空路径记录（build-failure 落盘形态）必须触发 redeploy，不被文件存在骗过。"""
        last = tmp_path / "debug" / "unique" / "last_deploy.json"
        last.parent.mkdir(parents=True)
        last.write_text(json.dumps({"smoke_passed": False}), encoding="utf-8")
        build = _fake_redeploy(tmp_path, write_usable=True).replace(
            "{last_deploy}", str(last))
        r = _run_shell(self._snippet(tmp_path, build))
        assert r.returncode == 0, r.stderr
        assert (tmp_path / "redeploy_called.marker").exists()
        assert json.loads(last.read_text())["install_path"] == "/opp"

    def test_usable_record_skips_redeploy(self, tmp_path):
        last = tmp_path / "debug" / "unique" / "last_deploy.json"
        last.parent.mkdir(parents=True)
        last.write_text(json.dumps(
            {"install_path": "/opp", "python_path": "/py", "smoke_passed": False}),
            encoding="utf-8")
        build = _fake_redeploy(tmp_path, write_usable=True).replace(
            "{last_deploy}", str(last))
        r = _run_shell(self._snippet(tmp_path, build))
        assert r.returncode == 0, r.stderr
        assert not (tmp_path / "redeploy_called.marker").exists()

    def test_redeploy_still_unusable_fatals(self, tmp_path):
        build = _fake_redeploy(tmp_path, write_usable=False).replace(
            "{last_deploy}", str(tmp_path / "debug" / "unique" / "last_deploy.json"))
        r = _run_shell(self._snippet(tmp_path, build))
        assert r.returncode == 1
        assert "FATAL" in r.stderr
        assert (tmp_path / "redeploy_called.marker").exists()

    def test_redeploy_nonzero_exit_tolerated(self, tmp_path):
        """P3：fake 写可用记录但 exit 1（deploy 失败形态）——rc 不是判据，落盘结果才是。"""
        build = _fake_redeploy(tmp_path, write_usable=True).replace(
            "{last_deploy}", str(tmp_path / "debug" / "unique" / "last_deploy.json"))
        r = _run_shell(self._snippet(tmp_path, build))
        assert r.returncode == 0, r.stderr
