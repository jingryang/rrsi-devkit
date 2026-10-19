"""UT for infra.provenance + run_started/spawn_context/output_truncated events
+ the repo_baseline_ref → target_repo_baseline_ref rename (step-67)."""

import json
import subprocess
from pathlib import Path

from ascendc_devkit.infra import provenance as prov
from ascendc_devkit.orchestration.kernel import event as evt
from ascendc_devkit.orchestration.kernel.state import State


def _git_init(repo: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"])
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"])


# —— git probe ————————————————————————————————————————————————

def test_git_probe_clean(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
    g = prov._git(tmp_path)
    assert g.commit and g.commit_short == g.commit[:12]
    assert g.dirty is False
    assert g.dirty_file_count == 0


def test_git_probe_dirty(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
    (tmp_path / "a.txt").write_text("dirty")  # uncommitted
    g = prov._git(tmp_path)
    assert g.dirty is True
    assert g.dirty_file_count == 1


def test_git_probe_not_a_repo_records_reason(tmp_path):
    g = prov._git(tmp_path)
    assert g.commit is None
    assert g.error  # absence is diagnostic, never silent (§3.7)


def test_probe_git_head_and_dirty_contract(tmp_path):
    """probe_git_head_and_dirty 返回 (commit, dirty_lines)——commit 完整 sha、
    dirty_lines 为 porcelain 非空行数（§1.15 单点，_git 与 deploy._source_identity 共用）。"""
    _git_init(tmp_path)
    (tmp_path / "a.txt").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "init"], check=True)
    # clean → 无 dirty
    commit, dirty = prov.probe_git_head_and_dirty(tmp_path)
    assert commit and len(commit) == 40
    assert dirty == []
    # dirty → 行数反映改动文件数
    (tmp_path / "a.txt").write_text("dirty")
    (tmp_path / "b.txt").write_text("new")
    _, dirty2 = prov.probe_git_head_and_dirty(tmp_path)
    assert len(dirty2) == 2  # a.txt 修改 + b.txt 新增
    # 非 git → (None, [])。not_repo 必须建在 tmp_path(git 仓)之外——否则 git 向上
    # 找到父仓 .git 把它当子目录（实测返回 parent commit，非 None）。
    import tempfile
    not_repo = Path(tempfile.mkdtemp(dir=str(tmp_path.parent)))
    assert prov.probe_git_head_and_dirty(not_repo) == (None, [])


# —— runtime_config + danger warning (the 8192 silent-truncation case) ——

def _write_opencode(repo: Path, output: int) -> None:
    (repo / "opencode.json").write_text(json.dumps({
        "model": "anthropic/GLM-5.2",
        "provider": {"anthropic": {
            "options": {"baseURL": "http://x/v1"},
            "models": {"GLM-5.2": {"limit": {"context": 200000, "output": output}}},
        }},
    }))


def test_runtime_config_reads_opencode_json(tmp_path):
    _write_opencode(tmp_path, 8192)
    rc = prov._runtime_config("opencode", tmp_path)
    assert rc.source == "opencode.json"
    assert rc.model == "GLM-5.2"
    assert rc.output_token_limit == 8192
    assert rc.context_token_limit == 200000
    assert rc.base_url == "http://x/v1"


def test_danger_warning_for_low_output_limit(tmp_path):
    _write_opencode(tmp_path, 8192)
    p = prov.build_provenance(run_id="r", repo_root=tmp_path, agent_backend="opencode")
    assert any("output_token_limit=8192" in w for w in p.warnings)


def test_no_warning_for_large_output_limit(tmp_path):
    _write_opencode(tmp_path, 65536)
    p = prov.build_provenance(run_id="r", repo_root=tmp_path, agent_backend="opencode")
    assert not any("output_token_limit" in w for w in p.warnings)


def test_dirty_tree_also_warned(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "a").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "i"], check=True)
    (tmp_path / "a").write_text("dirty")
    p = prov.build_provenance(run_id="r", repo_root=tmp_path, agent_backend="opencode")
    assert any("dirty=true" in w for w in p.warnings)


# —— build_provenance + write + summary ————————————————————————

def test_build_provenance_structure(tmp_path):
    p = prov.build_provenance(
        run_id="run-1", repo_root=tmp_path, agent_backend="claude",
        target_repo_baseline_ref="deadbeef" * 5)
    assert p.run_id == "run-1"
    assert p.orchestration.agent_backend == "claude"
    assert p.target_repo_baseline_ref == "deadbeef" * 5
    assert p.devkit.git.commit is None      # not a git repo
    assert p.devkit.git.error
    assert p.environment.hostname           # independently probed (infra-layer)
    assert p.built_at


def test_write_provenance_roundtrip(tmp_path):
    p = prov.build_provenance(run_id="r", repo_root=tmp_path, agent_backend="opencode")
    path = prov.write_provenance(tmp_path, p)
    assert path.name == "PROVENANCE.json"
    d = json.loads(path.read_text(encoding="utf-8"))
    assert d["run_id"] == "r"
    assert d["orchestration"]["agent_backend"] == "opencode"
    assert "devkit" in d and "environment" in d and "runtime_config" in d


def test_summary_one_line(tmp_path):
    _git_init(tmp_path)
    (tmp_path / "a").write_text("x")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "i"], check=True)
    p = prov.build_provenance(run_id="r", repo_root=tmp_path, agent_backend="opencode")
    s = prov.summary_one_line(p)
    assert "backend=opencode" in s
    assert "devkit=" in s


# —— events ————————————————————————————————————————————————————

def test_run_started_carries_provenance():
    p = prov.build_provenance(run_id="r", repo_root=Path("/tmp"), agent_backend="claude")
    e = evt.run_started("r", p.to_dict())
    assert e["type"] == "run_started"
    assert e["run_id"] == "r"
    assert e["provenance"]["orchestration"]["agent_backend"] == "claude"
    assert "ts" in e


def test_spawn_context_carries_transcript_and_session():
    e = evt.spawn_context("coder", "p", ["k"], ["s"], "/wd",
                          transcript="agents/coder-01.jsonl", session_id="ses_abc")
    assert e["transcript"] == "agents/coder-01.jsonl"
    assert e["session_id"] == "ses_abc"


def test_spawn_context_defaults_empty():
    e = evt.spawn_context("coder", "p", [], [], "/wd")
    assert e["transcript"] == ""
    assert e["session_id"] == ""


def test_output_truncated_event():
    e = evt.output_truncated("coder", turn=3, reason="max_tokens",
                             stage="codegen", session_id="ses_abc")
    assert e["type"] == "output_truncated"
    assert e["turn"] == 3 and e["reason"] == "max_tokens"


# —— state rename migration (repo_baseline_ref → target_repo_baseline_ref) ——

def test_state_from_snapshot_migrates_old_key():
    s = State.from_snapshot({"repo_baseline_ref": "abc123", "run_id": "r"})
    assert s.target_repo_baseline_ref == "abc123"


def test_state_from_snapshot_new_key():
    s = State.from_snapshot({"target_repo_baseline_ref": "xyz", "run_id": "r"})
    assert s.target_repo_baseline_ref == "xyz"


# —— skill/agent manifest fingerprint (P1: detect same-name-different-content) ——

def test_skill_fingerprint_changes_on_content(tmp_path):
    skills = tmp_path / ".claude" / "skills"
    (skills / "a").mkdir(parents=True)
    (skills / "a" / "SKILL.md").write_text("v1", encoding="utf-8")
    h1 = prov._skill_fingerprint(tmp_path)
    (skills / "a" / "SKILL.md").write_text("v2", encoding="utf-8")
    h2 = prov._skill_fingerprint(tmp_path)
    assert h1 and h2 and h1 != h2   # content change is detectable


def test_skill_fingerprint_none_when_absent(tmp_path):
    assert prov._skill_fingerprint(tmp_path) is None


def test_build_provenance_records_skill_fingerprint(tmp_path):
    skills = tmp_path / ".claude" / "skills"
    (skills / "a").mkdir(parents=True)
    (skills / "a" / "SKILL.md").write_text("x", encoding="utf-8")
    p = prov.build_provenance(run_id="r", repo_root=tmp_path, agent_backend="claude")
    assert p.orchestration.skill_manifest_fingerprint


# —— bug1 (step-68): diff_provenance + run_resumed ————————————————————

def _prov_dict(*, commit="c1", backend="claude", output_limit=8192,
               skill_fp="fp1", cann="8.0.0"):
    """Serialized-shape provenance dict (what PROVENANCE.json / to_dict yield)."""
    return {
        "run_id": "r", "built_at": "2026-01-01T00:00:00Z",
        "devkit": {"version": "1", "git": {"commit": commit, "commit_short": commit[:7]}},
        "orchestration": {"agent_backend": backend,
                          "skill_manifest_fingerprint": skill_fp},
        "runtime_config": {"output_token_limit": output_limit},
        "environment": {"cann_version": cann, "detected_chip": "A2"},
    }


def test_diff_no_drift_returns_empty():
    assert prov.diff_provenance(_prov_dict(), _prov_dict()) == {}


def test_diff_detects_commit_change():
    d = prov.diff_provenance(_prov_dict(commit="c1"), _prov_dict(commit="c2"))
    assert d.get("commit_changed") is True
    assert d["commit"] == {"old": "c1", "new": "c2"}


def test_diff_detects_backend_change():
    d = prov.diff_provenance(_prov_dict(backend="claude"),
                              _prov_dict(backend="opencode"))
    assert d.get("backend_changed") is True
    assert d["backend"] == {"old": "claude", "new": "opencode"}


def test_diff_detects_output_limit_change():
    # The silent-truncation danger axis: 8192 → 65536 must surface.
    d = prov.diff_provenance(_prov_dict(output_limit=8192),
                              _prov_dict(output_limit=65536))
    assert d.get("output_limit_changed") is True
    assert d["output_limit"] == {"old": 8192, "new": 65536}


def test_diff_detects_skill_fingerprint_change():
    d = prov.diff_provenance(_prov_dict(skill_fp="fp1"),
                              _prov_dict(skill_fp="fp2"))
    assert d.get("skill_fingerprint_changed") is True
    assert d["skill_fingerprint"] == {"old": "fp1", "new": "fp2"}


def test_diff_detects_environment_change():
    d = prov.diff_provenance(_prov_dict(cann="8.0.0"),
                              _prov_dict(cann="8.1.0"))
    assert d.get("environment_changed") is True
    assert d["environment"]["old"]["cann_version"] == "8.0.0"
    assert d["environment"]["new"]["cann_version"] == "8.1.0"


def test_diff_ignores_stable_axes():
    # built_at always differs but is NOT a diff axis (no diagnostic value);
    # run_id is stable identity, also not diffed.
    a = _prov_dict()
    b = _prov_dict()
    b["built_at"] = "2099-12-31T23:59:59Z"
    b["run_id"] = "r2"
    assert prov.diff_provenance(a, b) == {}


def test_diff_non_dict_input_returns_empty():
    assert prov.diff_provenance(None, _prov_dict()) == {}
    assert prov.diff_provenance(_prov_dict(), "nope") == {}


def test_run_resumed_event_shape():
    e = evt.run_resumed(
        run_id="r2", provenance=_prov_dict(backend="opencode"),
        resumed_from="r1", changes={"backend_changed": True,
                                     "backend": {"old": "claude", "new": "opencode"}})
    assert e["type"] == "run_resumed"
    assert e["run_id"] == "r2"
    assert e["resumed_from"] == "r1"
    assert e["provenance"]["orchestration"]["agent_backend"] == "opencode"
    assert e["changes"]["backend_changed"] is True
    assert "ts" in e


# —— step 104 — 两探针去主进程 import（主进程纯 Python 不变式）———————————————

def test_torch_npu_version_reads_installed_metadata(monkeypatch):
    """版本读走 importlib.metadata（已装=报告值），不 import torch_npu。

    语义钉住：即使 torch_npu 已装但 import 会坏，仍报告已装版本（环境记录
    而言"装了什么"比"能不能 import"更诚实——显式变更，非回归）。
    """
    import sys

    class _FakeMeta:
        @staticmethod
        def version(name):
            if name == "torch_npu":
                return "9.9.9.test"
            raise KeyError(name)

    import importlib.metadata as real_meta
    monkeypatch.setattr(real_meta, "version", _FakeMeta.version)
    # pytest 环境插件启动期可能预载 torch_npu（与被测代码无关）：先摘除，
    # 断言"探针没有把它带回来"——测被测路径，非整个会话。
    monkeypatch.delitem(sys.modules, "torch_npu", raising=False)
    assert prov._probe_torch_npu_version() == "9.9.9.test"
    assert "torch_npu" not in sys.modules, "版本探针不得 import torch_npu"


def test_torch_npu_version_missing_returns_none(monkeypatch):
    import importlib.metadata as real_meta

    def raise_missing(name):
        raise real_meta.PackageNotFoundError(name)

    monkeypatch.setattr(real_meta, "version", raise_missing)
    assert prov._probe_torch_npu_version() is None


def test_npu_device_count_env_then_smi_then_none(monkeypatch):
    """env → npu-smi → None（不给默认值——provenance 只记录事实）。"""
    import ascendc_devkit.infra.npu_smi as smi_mod

    monkeypatch.setenv("ASCEND_NPU_COUNT", "3")
    assert prov._npu_device_count() == 3

    monkeypatch.delenv("ASCEND_NPU_COUNT")
    monkeypatch.delenv("ASCEND_DEVICE_NUM", raising=False)
    monkeypatch.setattr(smi_mod, "npu_smi_device_count", lambda: 8)
    assert prov._npu_device_count() == 8

    monkeypatch.setattr(smi_mod, "npu_smi_device_count", lambda: None)
    assert prov._npu_device_count() is None
