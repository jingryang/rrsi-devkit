#!/usr/bin/env python3
"""One-click opencode trajectory export from DevKit run/batch output dirs.

Given a run id (session) or batch id under the DevKit ``output/`` root, locate
the opencode database(s) and export each run's full trajectories as canonical
records + 2.0 SFT JSONL (slow/fast thinking), via the two sibling modules:

    reconstruct_opencode_request.py   db → canonical per-native-session records
    convert_to_sft.py                 canonical records → 2.0 SFT JSONL

Id resolution mirrors application/resume_resolver.py (the RULE's authority):
batch_id and execution_id share the ts+uuid format, so ids are disambiguated
by LOCATION, never by string:
    1. <root>/<id>/state_snapshot.json       → flat single run
    2. <root>/<id>/ has ≥1 run subdirs       → batch → every exec run in it
    3. <root>/*/<id>/state_snapshot.json     → nested execution (unique match)

Per-run output lands at <out>/<run path relative to runs-root>/ :
    canonical/NNN_<ses_id>.json   one per native session (agent spawn),
                                  time-ordered
    slow_thinking.jsonl           records with reasoning
    fast_thinking.jsonl           records without

Runs without an opencode db (claude backend / pre-isolation runs) are skipped
with a reason; batch processing continues past per-run failures and exits
non-zero only when nothing was exported or any attempted run failed.

Usage:
    python3 scripts/trace_export/export_trace.py <run_id|batch_id> [options]

Examples:
    python3 scripts/trace_export/export_trace.py 20260818-152906-e72f73
    python3 scripts/trace_export/export_trace.py 20260818-152906-dde0d9 --out /tmp/traces
    python3 scripts/trace_export/export_trace.py <run_id> --session ascendc-design-generator
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import sqlite3
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import convert_to_sft  # noqa: E402
import reconstruct_opencode_request as recon  # noqa: E402


class TraceExportError(Exception):
    """Fatal input/resolution error for one id/run (reported, not tracebacked)."""


def resolve_runs(id_: str, runs_root: Path) -> list[Path]:
    """Resolve <id> to the list of run directories it refers to (by location).

    Raises TraceExportError on no match or ambiguous nested matches.
    """
    base = runs_root.resolve()
    direct = base / id_

    # State 1: flat single run — direct snapshot unambiguously means a run.
    if (direct / "state_snapshot.json").is_file():
        return [direct]

    # State 2: batch dir — contains ≥1 execution subdirs; ignore non-run
    # subdirs that may sit alongside (cann_bench/, tarballs, ...).
    if direct.is_dir():
        runs = sorted(d for d in direct.iterdir()
                      if d.is_dir() and (d / "state_snapshot.json").is_file())
        if runs:
            return runs

    # State 3: nested execution — id_ is an exec under some batch.
    matches = sorted(m for m in base.glob(f"*/{id_}")
                     if m.is_dir() and (m / "state_snapshot.json").is_file())
    if len(matches) == 1:
        return [matches[0]]
    if len(matches) > 1:
        raise TraceExportError(
            f"id '{id_}' matched multiple nested executions under {base}/ "
            f"(batches: {[m.parent.name for m in matches]}); "
            f"pass the batch_id to export the whole batch instead")
    raise TraceExportError(
        f"id '{id_}' not found under {base}/ (neither a run nor a batch). "
        f"Check the id or pass --runs-root.")


def find_db(run_dir: Path) -> Path | None:
    """The run's isolated opencode db (one per run — all spawns share it)."""
    db = run_dir / ".opencode_home" / "data" / "opencode" / "opencode.db"
    return db if db.is_file() else None


_CAMEL1 = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL2 = re.compile(r"([a-z0-9])([A-Z])")


def _camel_to_snake(name: str) -> str:
    return _CAMEL2.sub(r"\1_\2", _CAMEL1.sub(r"\1_\2", name)).lower()


def resolve_op_name(run_dir: Path) -> str:
    """The run's operator name for output labeling (structured sources first).

    1. artifacts/codegen/_contract/codegen_manifest.json ``op_name`` (CamelCase
       → snake; step-109 routes contract metadata under ``_contract/``)
    2. the kernel file under artifacts/codegen/op_kernel (``<op>_kernel.cpp``)
    3. ``unknown_op`` (run died before codegen — honest placeholder)
    """
    manifest = run_dir / "artifacts" / "codegen" / "_contract" / "codegen_manifest.json"
    if manifest.is_file():
        try:
            op = json.loads(manifest.read_text(encoding="utf-8")).get("op_name")
            if op:
                return _camel_to_snake(str(op))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[WARN] unreadable {manifest}: {e}")
    kernels = sorted((run_dir / "artifacts" / "codegen" / "op_kernel").glob("*_kernel.cpp")) \
        if (run_dir / "artifacts" / "codegen" / "op_kernel").is_dir() else []
    if kernels:
        return kernels[0].name[: -len("_kernel.cpp")]
    return "unknown_op"


def export_index_entry(out_dir: Path, run_dir: Path, *, native_sessions: int,
                       slow: int, fast: int, code_files: int) -> dict:
    """One machine-readable record of what was exported where (traceability)."""
    return {
        "operator": resolve_op_name(run_dir),
        "run_id": run_dir.name,
        "source_run_dir": str(run_dir.resolve()),
        "exported_at": datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "export_dir": out_dir.name,
        "native_sessions": native_sessions,
        "slow_thinking": slow,
        "fast_thinking": fast,
        "code_files": code_files,
    }


def upsert_index(index_path: Path, entry: dict) -> None:
    """Insert-or-update by run_id so re-export stays idempotent."""
    entries: list[dict] = []
    if index_path.is_file():
        try:
            entries = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            print(f"[WARN] unreadable index {index_path} — starting fresh")
    entries = [e for e in entries if e.get("run_id") != entry["run_id"]]
    entries.append(entry)
    entries.sort(key=lambda e: (e.get("operator", ""), e.get("run_id", "")))
    index_path.write_text(json.dumps(entries, ensure_ascii=False, indent=2),
                          encoding="utf-8")


def load_config(db_path: Path) -> dict | None:
    """The per-spawn served config next to the db (recon.find_config layout)."""
    cfg_path = recon.find_config(db_path)
    if cfg_path and cfg_path.is_file():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return None


def build_canonical_records(db_path: Path, config: dict | None,
                            needle: str | None = None) -> list[dict]:
    """Reconstruct canonical records for every native session in the db,
    optionally filtered by substring on session id / agent / title,
    sorted by session start time."""
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute("SELECT * FROM session ORDER BY time_created").fetchall()
        if needle:
            n = needle.lower()
            rows = [r for r in rows if n in r["id"].lower()
                    or n in (r["agent"] or "").lower()
                    or n in (r["title"] or "").lower()]
            if not rows:
                raise TraceExportError(
                    f"no native session matches '{needle}' in {db_path}")
        return [recon.reconstruct_session(con, row, config, recon.ENGINE_MCP_TOOLS)
                for row in rows]
    finally:
        con.close()


def write_canonical(records: list[dict], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    width = len(str(len(records)))
    for idx, rec in enumerate(records, 1):
        (out_dir / f"{idx:0{width}d}_{rec['session']['id']}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")


def export_code(run_dir: Path, out_dir: Path) -> bool:
    """Copy the run's final operator code (``artifacts/codegen`` — the
    framework-materialized snapshot: op_kernel/op_host/op_api/op_plugin +
    build files) next to the trajectories. Returns True when exported."""
    src = run_dir / "artifacts" / "codegen"
    if not src.is_dir():
        print(f"[WARN] no final code at {src} — skipping code export")
        return False
    dst = out_dir / "code"
    if dst.exists():
        shutil.rmtree(dst)
    # _contract/ 是框架契约元数据（step-109 路由：codegen_manifest/decision_log
    # 等），非算子代码语料——不进代码导出。
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("_contract"))
    n = sum(1 for p in dst.rglob("*") if p.is_file())
    print(f"final code        : {n} file(s) -> {dst}")
    return True


def export_run(run_dir: Path, out_dir: Path, *, needle: str | None = None,
               meta: dict | None = None,
               include_code: bool = True) -> dict:
    """One run dir → canonical/*.json + slow/fast_thinking.jsonl + code/.

    Returns an index entry (machine-readable export record).
    """
    db_path = find_db(run_dir)
    if db_path is None:
        raise TraceExportError(
            f"no opencode.db under {run_dir}/.opencode_home "
            f"(claude-backend or pre-isolation run?)")
    config = load_config(db_path)
    records = build_canonical_records(db_path, config, needle)
    write_canonical(records, out_dir / "canonical")
    slow, fast, issues = convert_to_sft.export_jsonl(records, out_dir, **(meta or {}))
    if issues:
        print(f"[WARN] {len(issues)} quality check issue(s) — report-only, "
              f"data kept (see [CHECK FAIL] lines above)")
    code_files = 0
    code_dir = out_dir / "code"
    if include_code:
        if export_code(run_dir, out_dir):
            code_files = sum(1 for p in code_dir.rglob("*") if p.is_file())
    print(f"canonical records : {len(records)} -> {out_dir / 'canonical'}")
    return export_index_entry(out_dir, run_dir, native_sessions=len(records),
                              slow=slow, fast=fast, code_files=code_files)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("id", help="run/execution id (single session) or batch id under the runs root")
    ap.add_argument("--runs-root", type=Path, default=Path("output"),
                    help="root containing run/batch dirs (the DevKit runs data; "
                         "default: output under the current directory)")
    ap.add_argument("--out", type=Path, default=Path("trace_export"),
                    help="export root for the trajectory corpus; one leaf dir per "
                         "run, named <operator>_<run_id> (default: trace_export)")
    ap.add_argument("--session", default=None,
                    help="export only native sessions whose id/agent/title contains this substring")
    ap.add_argument("--teacher", default=None,
                    help="override meta_info.teacher for ALL records "
                         "(default: each record's own logged session model id)")
    ap.add_argument("--owner", default=None,
                    help="meta_info.owner (default: unknown)")
    ap.add_argument("--query-source", default=None,
                    help="meta_info.query_source (default: operator)")
    ap.add_argument("--category", default=None,
                    help="meta_info.category (default: code)")
    ap.add_argument("--no-code", action="store_true",
                    help="skip exporting the final operator code (artifacts/codegen)")
    args = ap.parse_args(argv)

    meta = {k: v for k, v in (("teacher", args.teacher), ("owner", args.owner),
                              ("query_source", args.query_source),
                              ("category", args.category)) if v is not None}

    try:
        runs = resolve_runs(args.id, args.runs_root)
    except TraceExportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    out_root = args.out.resolve()
    index_path = out_root / "index.json"
    ok = skip = fail = 0
    for i, run_dir in enumerate(runs, 1):
        op_name = resolve_op_name(run_dir)
        out_dir = out_root / f"{op_name}_{run_dir.name}"
        print(f"\n== [{i}/{len(runs)}] {op_name} ({run_dir.relative_to(args.runs_root.resolve())}) ==")
        try:
            entry = export_run(run_dir, out_dir, needle=args.session,
                               meta=meta, include_code=not args.no_code)
        except TraceExportError as e:  # input-condition skip (no db, empty filter)
            print(f"[SKIP] {run_dir.name}: {e}", file=sys.stderr)
            skip += 1
            continue
        except Exception as e:  # noqa: BLE001 — keep batch going, report loudly
            print(f"[FAIL] {run_dir.name}: {type(e).__name__}: {e}", file=sys.stderr)
            fail += 1
            continue
        upsert_index(index_path, entry)
        print(f"[OK] {out_dir.name}: {entry['native_sessions']} native session(s), "
              f"{entry['code_files']} code file(s)")
        ok += 1

    print("\n" + "=" * 60)
    print(f"Done: ok={ok} skipped={skip} failed={fail}")
    print(f"Output root: {out_root}  (index: {index_path})")
    print("=" * 60)
    return 0 if (ok >= 1 and fail == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
