"""L7 Infrastructure — run MANIFEST: per-file sha256 for integrity verification.

``build_manifest(run_dir)`` walks the run directory (excluding the manifest
itself, the ``.dirty`` marker, and the backend sandbox scratch dir), records
each file's sha256 + size + role, and writes ``MANIFEST.json``.
``verify_manifest(run_dir)`` reads it back and reports missing / mismatched /
extra files — so a foreign run package can be checked for truncation,
tampering, or selective omission (step-67, P2).

The manifest header carries the provenance summary so a single file gives both
the version identity and the integrity check.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


MANIFEST_NAME = "MANIFEST.json"

# Files that are self-referential or transient — excluded from the manifest.
_EXCLUDE_FILES = {MANIFEST_NAME, ".dirty"}
# Backend sandbox scratch (large, regenerable, not a run product).
_EXCLUDE_DIRS = {".opencode_home"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _role(rel: str) -> str:
    if rel == "events.jsonl":
        return "event_log"
    if rel == "state_snapshot.json":
        return "state"
    if rel in ("report.md", "report.json"):
        return "report"
    if rel == "PROVENANCE.json":
        return "provenance"
    if rel.startswith("agents/"):
        return "agent_session" if rel.endswith(".jsonl") else "session_sidecar"
    if rel.startswith("subprocess/"):
        return "subprocess_log"
    if rel.startswith("artifacts/"):
        return "artifact"
    return "other"


def _is_excluded(rel: str) -> bool:
    if rel in _EXCLUDE_FILES:
        return True
    return any(rel == d or rel.startswith(d + "/") for d in _EXCLUDE_DIRS)


def _iter_run_files(run_dir: Path):
    for p in sorted(run_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(run_dir).as_posix()
        if _is_excluded(rel):
            continue
        yield rel, p


def build_manifest(run_dir: Path, *, provenance_summary: str = "",
                   provenance_warnings: list[str] | None = None) -> Path:
    """Write ``<run>/MANIFEST.json`` with per-file sha256. Idempotent."""
    run_dir = Path(run_dir)
    files = []
    for rel, p in _iter_run_files(run_dir):
        try:
            files.append({"path": rel, "sha256": _sha256(p),
                          "size": p.stat().st_size, "role": _role(rel)})
        except Exception:
            continue
    manifest = {
        "run_dir": run_dir.name,
        "file_count": len(files),
        "provenance_summary": provenance_summary,
        "provenance_warnings": list(provenance_warnings or []),
        "files": files,
    }
    path = run_dir / MANIFEST_NAME
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def verify_manifest(run_dir: Path) -> dict:
    """Verify a run dir against its MANIFEST.json.

    Returns ``{ok, missing, mismatched, extra, file_count, provenance_*}``.
    ``missing`` = listed file absent (omitted from package); ``mismatched`` =
    present but sha256 differs (truncated or tampered); ``extra`` = present but
    not listed (added after manifest, or unmanaged).
    """
    run_dir = Path(run_dir)
    mpath = run_dir / MANIFEST_NAME
    if not mpath.exists():
        return {"ok": False, "error": "MANIFEST.json not found",
                "missing": [], "mismatched": [], "extra": [],
                "file_count": 0}
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    expected = {f["path"]: f for f in manifest.get("files", [])}
    missing, mismatched = [], []
    for rel, f in expected.items():
        p = run_dir / rel
        if not p.exists():
            missing.append(rel)
            continue
        try:
            if _sha256(p) != f["sha256"]:
                mismatched.append(rel)
        except Exception:
            mismatched.append(rel)
    actual = {rel for rel, _ in _iter_run_files(run_dir)}
    extra = sorted(actual - set(expected))
    return {
        "ok": not missing and not mismatched,
        "missing": missing, "mismatched": mismatched, "extra": extra,
        "file_count": len(expected),
        "provenance_summary": manifest.get("provenance_summary", ""),
        "provenance_warnings": manifest.get("provenance_warnings", []),
    }
