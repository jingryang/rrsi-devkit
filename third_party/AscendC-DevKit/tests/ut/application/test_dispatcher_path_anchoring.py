"""UT: dispatch() 在入口把 CLI 路径字段锚定为绝对路径。

背景：用户 CLI 传的路径字段（golden / requirement / op_dir / ...）会被写进 State，
随后序列化进 ``state_snapshot.json``，供**下游独立进程**（run-cases / redeploy /
harness 子进程）读取——它们各自的 cwd 与初始进程不同。相对路径只在初始进程可解析，
跨进程即断（实证：golden 相对路径在 run-cases cwd=operator_dir 下 FileNotFoundError，
harness 加载 golden 前死亡）。

守护点（dispatcher.py ``_cli_path``）：
- 全部 CLI 路径字段走单点 ``Path(v).resolve()``，不留裸 ``Path()`` 构造的例外；
- 空值 → ``None``（不落成 cwd 本身）。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from ascendc_devkit.application.dispatcher import dispatch
from ascendc_devkit.capabilities.agent.stub_backend import StubBackend


def _task_request(tmp_path: Path, **paths) -> dict:
    """构造一个最小可 dispatch 的 task_request，路径字段由调用方以**相对**形式给出。"""
    return {
        "mode": "new",
        "workflow": "generate_ascendc",
        "repo_profile": "ops-nn",
        "op_name": "path_anchor_op",
        "golden_entry": "path_anchor_op",
        "golden_input_type": "torch",
        "non_interactive": True,
        "on_decision": "default",
        "max_iterations": 5,
        "max_corrective": 5,
        "max_escalations": 2,
        "enable_stubbed": True,
        "output_root": str(paths.pop("output_root")),
        "npu_id": 0,
        **paths,
    }


def _snapshot(output_root: Path) -> dict:
    snaps = sorted(output_root.glob("*/state_snapshot.json"))
    assert snaps, "dispatch 未写出 state_snapshot.json"
    return json.loads(snaps[0].read_text())


@pytest.mark.parametrize(
    "field", ["golden_path", "requirement_path", "cases_path",
              "detailed_design_path", "op_dir", "repo_root", "target_repo"])
def test_cli_path_fields_anchored_absolute(tmp_path, monkeypatch, field):
    """相对路径入口 → snapshot 里该字段是绝对路径。

    ``Path.is_absolute()`` 是权威判据：相对路径在不同 cwd 下解析结果不同，跨进程即断；
    绝对路径与 cwd 无关。
    """
    monkeypatch.chdir(tmp_path)  # 相对路径以此为基准解析
    out = tmp_path / "output"
    out.mkdir()

    rel = f"./rel_{field}"
    (tmp_path / f"rel_{field}").mkdir()

    req = _task_request(out, output_root=out, **{field: rel})
    with mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend",
                    return_value=StubBackend()):
        dispatch(req)

    snap = _snapshot(out)
    value = snap.get(field)
    assert value is not None, f"{field} 未进 snapshot"
    assert Path(value).is_absolute(), (
        f"{field} 未被锚定为绝对路径：{value!r}（下游跨进程 cwd 不同 → 解析即断）")


def test_relative_golden_resolves_against_entry_cwd(tmp_path, monkeypatch):
    """相对 golden 解析到**入口 cwd**，而非某个下游目录。

    这是本机制的核心语义：锚定发生在 dispatch 入口、初始 cwd 仍有效的那一刻；
    下游进程无论 cwd 为何，拿到的都是同一个绝对路径。
    """
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "output"
    out.mkdir()
    golden = tmp_path / "my_golden.py"
    golden.write_text("# golden\n")

    req = _task_request(out, output_root=out, golden_path="./my_golden.py")
    with mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend",
                    return_value=StubBackend()):
        dispatch(req)

    assert Path(_snapshot(out)["golden_path"]) == golden.resolve()


def test_absent_path_fields_stay_none(tmp_path, monkeypatch):
    """未提供的路径字段保持 None——不落成 cwd 本身（``Path('').resolve()`` 的陷阱）。"""
    monkeypatch.chdir(tmp_path)
    out = tmp_path / "output"
    out.mkdir()

    req = _task_request(out, output_root=out)
    with mock.patch("ascendc_devkit.application.dispatcher.build_agent_backend",
                    return_value=StubBackend()):
        dispatch(req)

    snap = _snapshot(out)
    for field in ("golden_path", "cases_path", "detailed_design_path",
                  "op_dir", "repo_root"):
        assert snap.get(field) is None, (
            f"{field} 未传时应为 None，实际 {snap.get(field)!r}"
            "（Path('').resolve() 会退化成 cwd 本身）")
