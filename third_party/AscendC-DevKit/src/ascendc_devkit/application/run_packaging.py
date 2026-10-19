"""L2 Application — run packaging (step-67).

Builds a self-describing run tarball (run dir + MANIFEST.json + optional SDK
native sessions) and verifies one against its manifest. Lives in L2 (not L1
CLI) so it may import L7 infra (workspace / run_manifest / provenance) — the
CLI layer is a thin click wrapper over these functions (§1.1 layering).
"""

from __future__ import annotations

import json
import tarfile
from pathlib import Path

from ascendc_devkit.infra import provenance as prov_mod
from ascendc_devkit.infra import run_manifest
from ascendc_devkit.infra.workspace import Workspace


def collect_session_ids(run_dir: Path) -> list[str]:
    """session_ids this run touched: events.jsonl spawn_context ∪ sidecars."""
    ids: set[str] = set()
    ev = run_dir / "events.jsonl"
    if ev.exists():
        for line in ev.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get("type") == "spawn_context" and o.get("session_id"):
                ids.add(o["session_id"])
    agents = run_dir / "agents"
    if agents.exists():
        for p in agents.glob("*.session.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                if d.get("session_id"):
                    ids.add(d["session_id"])
            except Exception:
                continue
    return sorted(ids)


def collect_native_sessions(session_ids: list[str],
                            backend: str) -> list[tuple[str, Path]]:
    """Best-effort fish SDK native session files matching any session_id.

    claude → ~/.claude/projects/**/<session_id>*
    opencode → ~/.local/share/opencode/session/**/<session_id>*

    Diagnostic-only (§1.7): reading the SDK's global storage to package it for
    a reviewer is NOT a runtime dependency — the run only ever trusts
    <run>/agents/. Returns [] when the storage is absent or no id matches.
    """
    home = Path.home()
    roots: list[Path] = []
    if backend == "claude":
        roots.append(home / ".claude" / "projects")
    elif backend == "opencode":
        roots.append(home / ".local" / "share" / "opencode" / "session")
    found: list[tuple[str, Path]] = []
    for root in roots:
        if not root.exists():
            continue
        for sid in session_ids:
            if not sid:
                continue
            for p in root.rglob(f"*{sid}*"):
                if p.is_file():
                    found.append((sid, p))
    return found


def pack_run(run_id: str, output_root: str = "output",
             include_native: bool = True) -> dict:
    """Build MANIFEST.json then tar the run dir (+ optional native sessions).

    Returns a report dict {out, backend, native_count, include_native}.
    """
    ws = Workspace.from_existing(run_id, output_root)
    prov_summary = ""
    prov_warnings: list[str] = []
    backend = ""
    if ws.provenance_path.exists():
        try:
            pd = json.loads(ws.provenance_path.read_text(encoding="utf-8"))
            prov_summary = prov_mod.summary_from_dict(pd)
            prov_warnings = list(pd.get("warnings") or [])
            backend = (pd.get("orchestration") or {}).get("agent_backend", "")
        except Exception:
            pass
    run_manifest.build_manifest(
        ws.dir, provenance_summary=prov_summary,
        provenance_warnings=prov_warnings)
    native: list[tuple[str, Path]] = []
    if include_native:
        native = collect_native_sessions(collect_session_ids(ws.dir), backend)
    out = Path(output_root).resolve() / f"{run_id}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(ws.dir, arcname=run_id)
        for _sid, p in native:
            tar.add(p, arcname=f"{run_id}/native-sessions/{p.name}")
    return {"out": str(out), "backend": backend,
            "native_count": len(native), "include_native": include_native}


def verify_run(run_dir) -> dict:
    """Verify a run dir against its MANIFEST.json (delegates to infra)."""
    return run_manifest.verify_manifest(Path(run_dir))
