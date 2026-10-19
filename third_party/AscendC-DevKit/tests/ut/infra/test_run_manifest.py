"""UT for infra.run_manifest + cli.pack session-id collection (step-67)."""

import json

from ascendc_devkit.infra import run_manifest as rm


def test_build_and_verify_clean(tmp_path):
    (tmp_path / "events.jsonl").write_text("{}\n", encoding="utf-8")
    (tmp_path / "agents").mkdir()
    (tmp_path / "agents" / "a-01.jsonl").write_text("{}\n", encoding="utf-8")
    rm.build_manifest(tmp_path)
    r = rm.verify_manifest(tmp_path)
    assert r["ok"] is True
    assert r["file_count"] == 2


def test_verify_detects_mismatch(tmp_path):
    (tmp_path / "events.jsonl").write_text("hello", encoding="utf-8")
    rm.build_manifest(tmp_path)
    (tmp_path / "events.jsonl").write_text("tampered", encoding="utf-8")
    r = rm.verify_manifest(tmp_path)
    assert r["ok"] is False
    assert "events.jsonl" in r["mismatched"]


def test_verify_detects_missing(tmp_path):
    (tmp_path / "events.jsonl").write_text("x", encoding="utf-8")
    (tmp_path / "report.md").write_text("r", encoding="utf-8")
    rm.build_manifest(tmp_path)
    (tmp_path / "report.md").unlink()
    r = rm.verify_manifest(tmp_path)
    assert r["ok"] is False
    assert "report.md" in r["missing"]


def test_manifest_excludes_self_and_dirty(tmp_path):
    (tmp_path / "events.jsonl").write_text("x", encoding="utf-8")
    (tmp_path / ".dirty").touch()
    rm.build_manifest(tmp_path)
    m = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
    paths = {f["path"] for f in m["files"]}
    assert "MANIFEST.json" not in paths
    assert ".dirty" not in paths


def test_manifest_carries_provenance_header(tmp_path):
    (tmp_path / "events.jsonl").write_text("x", encoding="utf-8")
    rm.build_manifest(tmp_path, provenance_summary="devkit=abc | backend=claude",
                      provenance_warnings=["output=8192"])
    m = json.loads((tmp_path / "MANIFEST.json").read_text(encoding="utf-8"))
    assert m["provenance_summary"] == "devkit=abc | backend=claude"
    assert m["provenance_warnings"] == ["output=8192"]


def test_collect_session_ids_from_events_and_sidecar(tmp_path):
    from ascendc_devkit.application.run_packaging import collect_session_ids
    (tmp_path / "events.jsonl").write_text(
        json.dumps({"type": "spawn_context", "session_id": "ses_a"}) + "\n" +
        json.dumps({"type": "spawn_context", "session_id": ""}) + "\n",
        encoding="utf-8")
    ag = tmp_path / "agents"
    ag.mkdir()
    (ag / "coder.session.json").write_text(
        json.dumps({"session_id": "ses_b"}), encoding="utf-8")
    assert collect_session_ids(tmp_path) == ["ses_a", "ses_b"]
