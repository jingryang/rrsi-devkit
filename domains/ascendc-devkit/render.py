# Copyright 2026 The rrsi Authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Render one AscendC-DevKit run into the text the analyst/digester/proposer read.

A trial here is one operator-development run: an input requirement package
(desc.md / golden.py / proto.yaml / cases.csv) is handed to the DevKit
pipeline (entry → context → requirement → design → codegen → precision_debug
→ perf → integrate → finalize) and the operator it writes into a target
repository is compiled, deployed and scored. The score is a scalar; the
EVIDENCE is what this module renders:

  - the FAILURE CLASS: which of the six families the loss belongs to. They
    need different mechanisms, and a mechanism aimed at the wrong one
    measures as noise. A compile error is not a precision error, a precision
    error is not a performance miss, and none of them is an infrastructure
    fault — the analyst must be able to tell them apart before theorising.

  - the PER-CASE table: cann-bench compares every case against the golden
    with its own threshold. "case 4 exceeds 1e-3 by 31x on a non-32B-aligned
    bf16 row" is a mechanism; "pass_rate 0.85" is not.

  - the RUBRIC HIT, when a class K and its A5 score features are known: the
    positive/negative patterns for the capability dimension the failure sits
    in. This is the one piece of domain structure a scalar score cannot carry.

  - the SUBMITTED OPERATOR SOURCE: the only graded artefact. Without it the
    proposer sees a score and a log tail but cannot check whether the
    mechanism it declared actually landed in code.

Rendering is pure and read-only: repeated calls return the same text, a
malformed artefact degrades to a note, and it never raises into the loop.

Format contract with rrsi/propose.py:_read_trace (do not break it):
  * every trajectory line starts with ``[step N]`` so from_step/to_step
    slicing works;
  * the grading block's title contains «GRADING» (and «VERIFIER») so it is
    kept by the slice reader even outside the requested step range.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

# ------------------------------------------------------------------ caps ---
# Non-detail values are what the proposer reads by default; detail values are
# what the analyst/digester read (prepare_rendered uses detail=True). The
# operator source and the compiled errors are the two things a diagnosis is
# made of, so both widen substantially in detail mode.
MAX_CHARS = 300_000
# The detail document is not pasted into a prompt: prepare_rendered writes it to
# disk and the digester reads line ranges and greps it. It therefore gets its
# own, larger budget — capping it at the proposer's MAX_CHARS used to squeeze a
# 700k-char trajectory down to a quarter of itself and hide the stages that
# mattered (20261026 r0: all five digesters burned their turn budget and
# returned "hit max turns without returning").
MAX_CHARS_DETAIL = 1_500_000
# Char budget for the trajectory itself. The archive of a healthy run
# (20261022, exp) was ~300k chars total and digesters returned cleanly at turn
# ~22; a 730k trajectory is past the point where they run out of turns.
TRAJECTORY_BUDGET = 120_000
TRAJECTORY_BUDGET_DETAIL = 320_000
STEP_HEAD = 1_200
STEP_HEAD_DETAIL = 4_000
TOOL_HEAD = 700
TOOL_HEAD_DETAIL = 4_000
TOOL_ARGS_HEAD = 400
TOOL_ARGS_HEAD_DETAIL = 1_200
PROMPT_HEAD = 3_000
PROMPT_HEAD_DETAIL = 40_000
SOURCE_HEAD = 12_000
SOURCE_HEAD_DETAIL = 60_000
SOURCE_FILE_HEAD = 4_000
SOURCE_FILE_HEAD_DETAIL = 20_000
LOG_TAIL = 3_000
LOG_TAIL_DETAIL = 10_000
RUBRIC_HEAD = 2_500
RUBRIC_HEAD_DETAIL = 12_000

# cann-bench score maxima per weight profile:
# (compilation, function, performance, all-cases-pass bonus).
_SCORE_MAXIMA = {"1": (20, 30, 50, 0), "2": (5, 20, 70, 5)}


def _score_maxima(v: dict, rep: dict) -> tuple[str, tuple[int, int, int, int]]:
    """Weight profile from the verdict, the report, or the frozen report file."""
    profile = str(v.get("score_weight_profile")
                  or rep.get("score_weight_profile") or "").strip()
    if not profile:
        raw = v.get("report_json") or v.get("report_path")
        if isinstance(raw, dict):
            profile = str(raw.get("score_weight_profile") or "").strip()
        elif isinstance(raw, str) and raw:
            try:
                report = json.loads(Path(raw).read_text(encoding="utf-8"))
                profile = str(report.get("score_weight_profile") or "").strip()
            except Exception:  # noqa: BLE001 - rendering must never raise
                profile = ""
    return profile, _SCORE_MAXIMA.get(profile, (20, 30, 50, 0))

# Failure classes. ORDER MATTERS: the first matching rule wins, because a run
# that never compiled must not be described by its (empty) precision result.
FAILURE_CLASSES = ("NOT_STARTED", "COMPILE_FAILED", "DEPLOY_FAILED",
                   "PRECISION_FAILED", "PERF_UNDER_TARGET", "PASSED", "INFRA")
FAILURE_TEXT = {
    "NOT_STARTED": (
        "NO SUBMISSION - the pipeline ended before the operator was written "
        "into the target repo, or the stage chain never reached codegen. "
        "Nothing about AscendC explains this: it is routing, termination, "
        "budget or plumbing."),
    "COMPILE_FAILED": (
        "COMPILE FAILED - the operator source exists but the toolchain "
        "rejected it. Read the first error, not the last: a missing include "
        "or an undeclared symbol cascades. This is a code-generation / "
        "tiling-template / API-knowledge failure."),
    "DEPLOY_FAILED": (
        "DEPLOY FAILED - the build produced artefacts but installing the opp "
        "package or registering the torch/PTA symbol failed. The operator may "
        "be correct; the packaging or callable contract is not."),
    "PRECISION_FAILED": (
        "PRECISION FAILED - compiled, deployed and executed, but at least one "
        "cann-bench case exceeds its golden threshold. This is a kernel "
        "logic / reduction-accuracy / sync failure."),
    "PERF_UNDER_TARGET": (
        "PERF UNDER TARGET - every case meets its precision threshold, but "
        "the performance score is low (latency vs the reference). This is a "
        "tiling / pipelining / buffer-organisation failure."),
    "PASSED": "PASSED - every case meets its threshold and the perf gate.",
    "INFRA": (
        "INFRASTRUCTURE - the run failed for a reason that is not evidence "
        "about the harness or the operator: a crashed stage, a probe timeout, "
        "a stubbed gate, a card/driver fault, or an evaluation process that "
        "died. Do NOT read this trace as a capability signal."),
}


def _clip(s, n: int) -> str:
    s = "" if s is None else str(s)
    return s if len(s) <= n else s[:n] + f" ...[+{len(s) - n} chars]"


def _cap_total(text: str, head_frac: float = 0.6, limit: int | None = None) -> str:
    limit = MAX_CHARS if limit is None else limit
    if len(text) <= limit:
        return text
    head, tail = int(limit * head_frac), int(limit * (1 - head_frac))
    return (text[:head] + f"\n...[TRUNCATED {len(text) - head - tail} chars]...\n"
            + text[-tail:])


# ------------------------------------------------------------- artefacts ---
_RUN_FILE = re.compile(r"run_id:\s*(\S+)")
_STAGE_LINE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(\w+)\s*\|\s*(\d+)\s*\|\s*(\d+)ms\s*\|")
_BUILD_ERR = re.compile(
    r"(?im)^.*(?:error:|fatal error:|undefined reference|\.h:\d+:\d+: error|"
    r"error C\d+|ld\.lld: error|ccec.*error).*$")


def _json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(errors="replace"))
    except Exception:  # noqa: BLE001 — an unreadable artefact is a note, not a crash
        return {}


def resolve_run_dir(root: Path) -> Path:
    """The DevKit output root is `output/<run_id>/`; accept either level."""
    root = Path(root)
    if (root / "state_snapshot.json").is_file() or (root / "report.json").is_file():
        return root
    if root.is_dir():
        runs = sorted((p for p in root.iterdir()
                       if p.is_dir() and (p / "state_snapshot.json").is_file()),
                      key=lambda p: p.name)
        if runs:
            return runs[-1]
    return root


def rep_total_ms(run_dir: Path) -> int:
    return int((_json(resolve_run_dir(run_dir) / "report.json")
                or {}).get("total_elapsed_ms") or 0)


def run_reports(run_dir: Path) -> dict:
    """Parse the stage table out of report.md / report.json (best effort)."""
    run_dir = resolve_run_dir(run_dir)
    rep = {"stages": [], "errors": [], "total_ms": 0,
           "build_history": build_history(run_dir)}
    rj = _json(run_dir / "report.json")
    if rj:
        rep["total_ms"] = int(rj.get("total_elapsed_ms") or 0)
        rep["errors"] = [str(e) for e in (rj.get("errors") or [])]
        for s in rj.get("stages") or []:
            if isinstance(s, dict):
                rep["stages"].append({"name": s.get("name"), "status": s.get("status"),
                                      "iterations": s.get("iterations"),
                                      "elapsed_ms": s.get("elapsed_ms")})
        return rep
    md = run_dir / "report.md"
    if md.exists():
        try:
            for line in md.read_text(errors="replace").splitlines():
                m = _STAGE_LINE.match(line.strip())
                if m:
                    rep["stages"].append({"name": m.group(1), "status": m.group(2),
                                          "iterations": int(m.group(3)),
                                          "elapsed_ms": int(m.group(4))})
        except Exception:  # noqa: BLE001
            pass
    return rep


def load_verdict(run_dir: Path) -> dict:
    """The evaluation verdict: three-dimensional scores + per-case detail.

    Primary source is the DevKit snapshot (`eval_result` written by the
    cannbench_eval stage); the cann-bench report it points at fills in the
    per-case accuracy/perf rows when it is readable.
    """
    run_dir = resolve_run_dir(run_dir)
    snap = _json(run_dir / "state_snapshot.json")
    ev = (snap.get("eval_result") or {}) if isinstance(snap, dict) else {}
    dep = (snap.get("deploy_result") or {}) if isinstance(snap, dict) else {}
    v = {
        "overall_score": ev.get("overall_score"),
        "compile_score": ev.get("compile_score"),
        "function_score": ev.get("function_score"),
        "performance_score": ev.get("performance_score"),
        "pass_rate": ev.get("pass_rate"),
        "num_cases": ev.get("num_cases"),
        "num_passed": ev.get("num_passed"),
        "report_json": ev.get("report_json") or "",
        "smoke_passed": dep.get("smoke_passed"),
        "deploy_ok": bool(dep.get("install_path")),
        "per_case": [],
        # classify() needs the compiler output to tell COMPILE_FAILED from
        # NOT_STARTED; both call sites (score and load_trial) read it here.
        "compile_log": find_compile_log(run_dir),
        "error": "",
        "stages": {},
    }
    # Node status per stage: the difference between "never ran" and "ran and
    # failed" is what separates NOT_STARTED from COMPILE_FAILED.
    for name, st in ((snap.get("node_status") or {}) if isinstance(snap, dict) else {}).items():
        v["stages"][str(name)] = str(st)
    for e in (rep_errors(run_dir) or []):
        v["error"] = v["error"] or str(e)

    rp = find_eval_report(run_dir, v.get("report_json") or "")
    if rp:
        v["report_json"] = str(rp)
        data = _json(Path(rp))
        ops = data.get("operators") or []
        first = ops[0] if ops and isinstance(ops[0], dict) else {}
        for k_src, k_dst in (("compilation_score", "compile_score"),
                             ("function_score", "function_score"),
                             ("performance_score", "performance_score")):
            if v.get(k_dst) in (None, 0.0) and first.get(k_src) is not None:
                v[k_dst] = float(first.get(k_src) or 0.0)
        if v.get("num_cases") in (None, 0):
            v["num_cases"] = int(first.get("total_cases") or 0)
        if v.get("num_passed") in (None, 0):
            v["num_passed"] = int(first.get("passed_cases") or 0)
        for c in first.get("cases") or []:
            if not isinstance(c, dict):
                continue
            acc = c.get("accuracy") or {}
            cd = c.get("case_detail") or c
            # Two report vintages: older ones carry `outputs`, the current
            # kernel_eval report nests them under accuracy.output_results.
            outs = c.get("outputs") or acc.get("output_results") or [{}]
            out0 = outs[0] if outs and isinstance(outs[0], dict) else {}
            v["per_case"].append({
                "case_id": c.get("case_id") or c.get("case") or "",
                "name": c.get("case") or c.get("name") or "",
                "passed": bool(c.get("passed") if c.get("passed") is not None
                               else acc.get("passed")),
                "max_diff": _f(acc.get("max_diff") or out0.get("max_diff")
                               or cd.get("diff")),
                "mere": _f(acc.get("mere") or out0.get("mere")),
                "mare": _f(acc.get("mare") or out0.get("mare")),
                "threshold": _f(acc.get("threshold") or out0.get("threshold")),
                "mismatch": int(out0.get("mismatch_count", 0) or 0),
                "baseline_us": _f(c.get("baseline_perf_us")),
                # The cann-bench report carries device time as elapsed_ms; the
                # standalone perf skill writes kernel_perf_us. Normalize to us,
                # or the trace compares 0.2 us against 150 us.
                "kernel_us": (_f(c.get("kernel_perf_us"))
                              or _f(c.get("elapsed_us"))
                              or (_f(c.get("elapsed_ms")) or 0.0) * 1000.0 or None),
                "error": str(cd.get("error") or acc.get("error_msg") or "")[:400],
            })
    return v


def find_eval_report(run_dir: Path, recorded: str = "") -> Path | None:
    """Locate the cann-bench report for a run.

    `state_snapshot.eval_result.report_json` is an absolute path recorded on
    the machine that produced the run, so it is stale as soon as the run is
    copied elsewhere. Fall back to the known artefact locations.
    """
    run_dir = resolve_run_dir(run_dir)
    if recorded:
        p = Path(recorded)
        if p.is_file():
            return p
    roots = [run_dir / "subprocess", run_dir / "artifacts", run_dir.parent]
    for root in roots:
        if not root.is_dir():
            continue
        best = None
        for p in sorted(root.rglob("*.json")):
            if "eval" not in p.name.lower() and "report" not in p.name.lower():
                continue
            try:
                head = p.read_text(errors="replace")[:400]
            except Exception:  # noqa: BLE001
                continue
            if '"operators"' in head or '"total_cases"' in head:
                best = p if best is None or p.stat().st_mtime > best.stat().st_mtime else best
        if best is not None:
            return best
    return None


def rep_errors(run_dir: Path) -> list:
    return run_reports(run_dir).get("errors") or []


def _f(v):
    try:
        return None if v is None or v == "" else float(v)
    except (TypeError, ValueError):
        return None


def _build_logs(run_dir: Path) -> list[Path]:
    run_dir = resolve_run_dir(run_dir)
    sub = run_dir / "subprocess"
    if not sub.is_dir():
        return []
    return [p for p in sorted(sub.rglob("*"))
            if p.is_file() and p.suffix in (".log", ".txt", ".out", ".err", "")]


def _extract_errors(p: Path, run_dir: Path) -> str:
    try:
        text = p.read_text(errors="replace")
    except Exception:  # noqa: BLE001
        return ""
    lines = text.splitlines()
    errs = []
    for i, line in enumerate(lines):
        if _BUILD_ERR.match(line):
            # A compiler error is only usable with its context: the
            # instantiation chain and the caret are what name the fault.
            errs.append("\n".join(lines[i:i + 6])[:900])
            if len(errs) >= 20:
                break
    if not errs:
        return ""
    return f"--- {p.relative_to(resolve_run_dir(run_dir))} ---\n" + "\n".join(errs)


def find_compile_log(run_dir: Path) -> str:
    """Errors from the FINAL build attempt, or "" when it succeeded.

    A DevKit run may build several times (codegen's self-repair loop:
    build, fix, rebuild). An intermediate failure that a later attempt fixed is
    not evidence about the operator, and showing it next to a PASSED run reads
    as a contradiction — so only the newest `build*` log speaks for the run.
    Runs without build logs fall back to the newest log that has an error.
    """
    run_dir = resolve_run_dir(run_dir)
    logs = _build_logs(run_dir)
    if not logs:
        return ""
    builds = [p for p in logs if p.name.startswith("build")]
    if builds:
        newest = max(builds, key=lambda p: (p.stat().st_mtime, p.name))
        return _extract_errors(newest, run_dir)
    for p in sorted(logs, key=lambda p: p.stat().st_mtime, reverse=True):
        e = _extract_errors(p, run_dir)
        if e:
            return e
    return ""


def build_history(run_dir: Path) -> dict:
    """How many build attempts the run made, and how many failed. Used to say
    "an earlier attempt failed and was fixed" without replaying its log."""
    run_dir = resolve_run_dir(run_dir)
    builds = [p for p in _build_logs(run_dir) if p.name.startswith("build")]
    failed = sum(1 for p in builds if _extract_errors(p, run_dir))
    return {"attempts": len(builds), "failed": failed}


def find_sources(root: Path, op_name: str, repo_root: Path | None = None) -> dict:
    """The operator source the run produced (the graded artefact).

    The candidate worktree is the search root; the operator lives at
    `<repo>/<group>/<op>/` (ops-nn: norm/layer_norm_v4) or
    `<repo>/examples/.../csrc/ops/<op>/` (cann-bench). We walk for a directory
    whose name matches the op and whose files carry the operator's
    implementation suffixes.
    """
    out: dict = {}
    exts = {".cpp", ".h", ".cc", ".cce", ".py", ".json", ".txt", ".md"}
    skip = {"__pycache__", "build", "build_out", "node_modules", ".git"}
    if root is None or not Path(root).is_dir():
        return out
    candidates = []
    for p in Path(root).rglob(op_name):
        if not p.is_dir() or any(s in p.parts for s in skip):
            continue
        has_impl = any((p / f).exists() for f in ("op_kernel", "op_host", "op_api"))
        if has_impl or (repo_root and str(p).startswith(str(repo_root))):
            candidates.append(p)
    if not candidates:
        return out
    # Prefer the shallowest hit under the repo (the operator dir, not a test copy).
    candidates.sort(key=lambda p: len(p.parts))
    base = candidates[0]
    budget = SOURCE_HEAD
    for p in sorted(base.rglob("*")):
        if not p.is_file() or p.suffix not in exts or any(s in p.parts for s in skip):
            continue
        rel = str(p.relative_to(base))
        if len(out) >= 60 or budget <= 0:
            out["...[more files omitted]"] = ""
            break
        try:
            body = p.read_text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        out[rel] = body
        budget -= len(body)
    return out


# -------------------------------------------------------------- rendering --
def classify(v: dict, rep: dict) -> str:
    """First matching failure class (see FAILURE_CLASSES for the reasoning)."""
    stages = v.get("stages") or {}
    if v.get("error") and _is_infra_error(v["error"]):
        return "INFRA"
    if any(st in ("error", "aborted") and n in ("entry", "context")
           for n, st in stages.items()):
        return "INFRA"
    if any(str(st).startswith("unverified") for st in stages.values()):
        return "INFRA"
    has_eval = v.get("overall_score") not in (None,) or v.get("report_json")
    if not has_eval:
        gen = (v.get("function_score") or 0) + (v.get("compile_score") or 0)
        if not gen and v.get("deploy_ok") is False and v.get("compile_log"):
            return "COMPILE_FAILED"
        return "NOT_STARTED"
    compile_score = v.get("compile_score")
    function_score = v.get("function_score") or 0.0
    perf_score = v.get("performance_score") or 0.0
    pass_rate = v.get("pass_rate")
    if (compile_score is not None and compile_score <= 0.0) and function_score <= 0.0:
        if v.get("deploy_ok") is False and v.get("compile_log") == "":
            return "DEPLOY_FAILED"
        return "COMPILE_FAILED"
    if pass_rate is not None and pass_rate < 1.0:
        return "PRECISION_FAILED"
    if function_score <= 0.0 and (v.get("num_passed") or 0) == 0:
        return "PRECISION_FAILED"
    if perf_score <= 0.0:
        return "PERF_UNDER_TARGET"
    return "PASSED"


_INFRA_MARKERS = re.compile(
    r"(cann_bench_utils|不可达|超时|timeout|timed out|stubbed|probe|hdcdrv|"
    r"driver|device|card|NPU|infra|crash|报告畸形|discovery.*broken|"
    r"cann-bench eval 报告|eval_prepare)", re.I)


def _is_infra_error(msg: str) -> bool:
    return bool(_INFRA_MARKERS.search(str(msg)))


def render_grading(v: dict, rep: dict, op: dict, rubric: dict | None,
                   log: str = "", detail: bool = False) -> str:
    cls = classify(v, rep)
    lines = [f"FAILURE CLASS: {FAILURE_TEXT.get(cls, cls)}",
             f"CLASS CODE: {cls}"]
    if v.get("error"):
        lines.append(f"RUN ERROR: {_clip(v['error'], 600)}")
    profile, (compile_full, function_full, perf_full, bonus_full) = _score_maxima(v, rep)
    overall_full = compile_full + function_full + perf_full + bonus_full
    scores = []
    for label, key, full in (("overall", "overall_score", overall_full),
                             ("compile", "compile_score", compile_full),
                             ("function", "function_score", function_full),
                             ("perf", "performance_score", perf_full)):
        val = v.get(key)
        scores.append(f"{label}={val if val is not None else '?'}/{full}")
    if bonus_full:
        # The all-cases-pass bonus has no field of its own in older reports;
        # the verdict records it as implied_bonus, else derive it.
        bonus = v.get("implied_bonus")
        if bonus is None:
            parts = [v.get(k) for k in ("overall_score", "compile_score",
                                        "function_score", "performance_score")]
            if all(isinstance(x, (int, float)) for x in parts):
                bonus = parts[0] - sum(parts[1:])
        shown = f"{bonus:.2f}".rstrip("0").rstrip(".") \
            if isinstance(bonus, (int, float)) else "?"
        scores.append(f"bonus={shown}/{bonus_full}")
    pr = v.get("pass_rate")
    scores.append(f"pass_rate={pr:.3f}" if isinstance(pr, (int, float)) else "pass_rate=?")
    if v.get("num_cases"):
        scores.append(f"cases={v.get('num_passed')}/{v.get('num_cases')}")
    if v.get("smoke_passed") is not None:
        scores.append(f"smoke={'pass' if v.get('smoke_passed') else 'FAIL'}")
    lines.append("SCORES: " + " | ".join(scores))
    if profile:
        lines.append(f"SCORE PROFILE: {profile} — compile/{compile_full} + "
                     f"function/{function_full} + perf/{perf_full}"
                     + (f" + bonus/{bonus_full}" if bonus_full else ""))
    _perf = v.get("performance_score")
    if isinstance(_perf, (int, float)) and 0.0 < _perf < perf_full * 0.6:
        lines.append(f"PERF PARTIAL: {_perf:.1f}/{perf_full} — precision passes but "
                     f"the kernel does not reach the reference latency. Not a "
                     f"correctness failure; the evidence is in the per-case "
                     f"latency column.")
    # The stage chain is shown once, from the report. Node statuses are only
    # worth repeating when one is NOT completed — that is the difference
    # between "never ran" and "ran and failed".
    stages = rep.get("stages") or []
    if stages:
        lines.append("STAGES: " + _clip(" -> ".join(
            f"{s['name']}:{s['status']}" for s in stages), 900))
    odd = {n: st for n, st in (v.get("stages") or {}).items()
           if str(st) not in ("completed", "ok")}
    if odd:
        lines.append("STAGES NOT COMPLETED: " + _clip(json.dumps(odd), 600))

    pc = v.get("per_case") or []
    if pc:
        fails = [c for c in pc if not c["passed"]]
        passes = [c for c in pc if c["passed"]]
        lines.append(f"PER-CASE ({len(passes)}/{len(pc)} pass; failing cases first — "
                     "max_diff/mere/mare against the case's own threshold):")
        shown = sorted(pc, key=lambda c: (c["passed"], -(c.get("max_diff") or 0)))
        if not detail:
            # Compact: every failure (they carry the mechanism) plus a couple of
            # passes as a control; the rest is a count, not evidence.
            shown = fails + passes[:2]
        for c in shown:
            row = f"  [{c['case_id']}] {'PASS' if c['passed'] else 'FAIL'}"
            if c.get("name"):
                row += f" {_clip(c['name'], 90)}"
            for k in ("max_diff", "mere", "mare", "threshold"):
                if c.get(k) is not None:
                    row += f" {k}={c[k]:.3g}"
            if c.get("mismatch"):
                row += f" mismatch={c['mismatch']}"
            if c.get("baseline_us") and c.get("kernel_us"):
                row += f" latency={c['kernel_us']:.1f}us vs ref {c['baseline_us']:.1f}us"
            if c.get("error"):
                row += f" error={_clip(c['error'], 240)}"
            lines.append(row)
        if not detail and len(passes) > 2:
            lines.append(f"  ...[{len(passes) - 2} more passing cases omitted; "
                         f"read with detail for the full table]")

    hist = build_history_via(rep)
    if log and cls in ("COMPILE_FAILED", "DEPLOY_FAILED"):
        lines.append("COMPILER / BUILD LOG (final attempt — first error lines):")
        lines.append(_clip(log, LOG_TAIL_DETAIL if detail else LOG_TAIL))
    elif log:
        lines.append("COMPILER / BUILD LOG (the final attempt still logged errors, "
                     "but the run was scored above: read these as warnings):")
        lines.append(_clip(log, LOG_TAIL_DETAIL if detail else LOG_TAIL))
    elif hist.get("failed"):
        lines.append(f"BUILD HISTORY: {hist['attempts']} attempt(s), "
                     f"{hist['failed']} failed earlier and was fixed by a later "
                     f"attempt (log omitted — it is not evidence about the "
                     f"final operator).")

    rb = render_rubric_hit(op, cls, rubric, detail=detail)
    if rb:
        lines.append(rb)
    return "\n".join(lines)


def build_history_via(rep: dict) -> dict:
    return rep.get("build_history") or {}


def _rubric_rows(rubric: dict, k: str) -> dict:
    classes = (rubric or {}).get("classes") or {}
    return (classes.get(k) or {}).get("dimensions") or {}


# Which capability dimension owns which failure class. This mapping is the
# whole point of the rubric link: it turns "the score is low" into "look at
# the DataCopy / the pipeline / the vector API".
_DIM_BY_CLASS = {
    "COMPILE_FAILED": ["范式", "单元"],
    "DEPLOY_FAILED": ["单元"],
    "PRECISION_FAILED": ["范式", "单元", "同步"],
    "PERF_UNDER_TARGET": ["搬运", "buffer", "流水", "优化"],
}


def render_rubric_hit(op: dict, cls: str, rubric: dict | None,
                      detail: bool = False) -> str:
    k = str(op.get("k") or "").strip()
    if not k or not rubric:
        return ""
    dims = _rubric_rows(rubric, k)
    if not dims:
        return ""
    # A plumbing/infra loss has no capability dimension to judge the operator
    # against; showing the rubric there invites the analyst to read a crash as
    # a kernel-logic problem.
    wanted = _DIM_BY_CLASS.get(cls)
    if not wanted:
        return ""
    cap = RUBRIC_HEAD_DETAIL if detail else RUBRIC_HEAD
    lines = [f"RUBRIC (A5, class {k} {op.get('category', '')}): the score "
             f"features to check this failure against — a failing operator "
             f"usually violates ONE negative pattern; name it in the hypothesis."]
    for d in wanted:
        rows = dims.get(d) or []
        if not rows:
            continue
        lines.append(f"  [{d}]")
        for r in rows:
            pol = r.get("polarity", "?")
            lines.append(f"    {pol}: {r.get('feature', '')}")
            if detail and r.get("explanation"):
                lines.append(f"      why: {r['explanation']}")
            if detail and r.get("exception"):
                lines.append(f"      exception: {r['exception']}")
    out = "\n".join(lines)
    return _clip(out, cap) if cap else out


def render_sources(sources: dict, detail: bool = False,
                   budget: int | None = None) -> str:
    """Operator source listing, capped to `budget` characters in total.

    Per-file caps alone do not bound the section: a listing of 60 files at
    20k each is 1.2M chars. `render_full` passes a section budget so the
    listing can never crowd out the trajectory that follows it.
    """
    if not sources:
        return ("(no operator source found in the worktree — the run never "
                "wrote an operator, or the target repo layout is unknown)")
    cap = SOURCE_FILE_HEAD_DETAIL if detail else SOURCE_FILE_HEAD
    limit = len(sources) * cap if budget is None else max(0, budget)
    parts: list[str] = []
    used = 0
    for rel, body in sources.items():
        if used >= limit:
            parts.append(f"...[{len(sources) - len(parts)} more file(s) omitted; "
                         f"source section capped at {limit} chars]")
            break
        piece = f"===== {rel} =====\n{_clip(body, min(cap, limit - used))}"
        parts.append(piece)
        used += len(piece)
    return "\n\n".join(parts)


def _record_step(rec: dict) -> bool:
    return bool(rec.get("blocks") or rec.get("result") or rec.get("role"))


def render_trajectory(run_dir: Path, detail: bool = False, max_steps: int = 400,
                      budget: int | None = None) -> str:
    """`render_transcript`, but scaled to fit `budget` characters.

    A 600-step trajectory at the detail caps is ~730k chars. Rather than cut
    whole stages out of the middle (which is what makes a digester hunt for
    evidence that is no longer there), shrink the per-line caps until every
    step fits: worse resolution, intact sequence.
    """
    caps = ([STEP_HEAD_DETAIL, TOOL_HEAD_DETAIL, TOOL_ARGS_HEAD_DETAIL] if detail
            else [STEP_HEAD, TOOL_HEAD, TOOL_ARGS_HEAD])
    text = render_transcript(run_dir, detail=detail, max_steps=max_steps, caps=caps)
    for _ in range(4):
        if budget is None or len(text) <= budget or min(caps) <= 240:
            return text
        scale = max(0.4, budget / len(text))
        caps = [max(240, int(c * scale)) for c in caps]
        text = render_transcript(run_dir, detail=detail, max_steps=max_steps,
                                 caps=caps)
    return text


def sessions(run_dir: Path) -> list[tuple[int, Path, str]]:
    """`(first_ts, path, agent)` for every agent session, in pipeline order.

    Sorted by the first record's ``ts``, NOT by filename: the sessions are
    named per agent and stage (`ascendc-design-generator-01`,
    `ascendc-dev-s4-coding-03`, ...), so name order puts every design session
    before every coding session and says nothing about when the pipeline
    actually ran them. Rendering in name order also put the biggest stage
    first, which is how a 600-step cap ended up showing design work only.
    """
    run_dir = resolve_run_dir(run_dir)
    agents = run_dir / "agents"
    if not agents.is_dir():
        return []
    out: list[tuple[int, Path, str]] = []
    for sp in agents.glob("*.jsonl"):
        ts = 0
        try:
            for raw in sp.read_text(errors="replace").splitlines():
                if not raw.strip():
                    continue
                ts = int(json.loads(raw).get("ts") or 0)
                break
        except Exception:  # noqa: BLE001
            ts = 0
        if not ts:
            ts = int(sp.stat().st_mtime * 1000)
        agent = sp.name.rsplit("-", 1)[0] if sp.stem[-2:].isdigit() else sp.stem
        out.append((ts, sp, agent))
    return sorted(out, key=lambda x: (x[0], x[1].name))


def _allocate_step_budget(counts: list[int], budget: int, floor: int = 12) -> list[int]:
    """Split `budget` steps across stages so no stage is starved.

    Proportional-to-size allocation with a floor: a 400-step cap over a trace
    whose first stage alone has 600 steps must still show every later stage.
    Whatever the floor forces on small stages is taken from the largest ones.
    """
    if not counts:
        return []
    total = sum(counts) or 1
    if budget >= total:
        return list(counts)
    alloc = [max(1, min(c, round(budget * c / total))) for c in counts]
    for i, c in enumerate(counts):
        if c > 0:
            alloc[i] = max(alloc[i], min(c, floor))
    while sum(alloc) > budget:
        i = max(range(len(alloc)), key=lambda j: alloc[j] - min(counts[j], floor))
        if alloc[i] <= min(counts[i], floor):
            break
        alloc[i] -= 1
    while sum(alloc) < budget:
        i = max(range(len(alloc)), key=lambda j: counts[j] - alloc[j])
        if alloc[i] >= counts[i]:
            break
        alloc[i] += 1
    return alloc


def render_stage(run_dir: Path, session: Path, detail: bool = False,
                 caps: list[int] | None = None, max_steps: int | None = None) -> str:
    """One agent session, rendered on its own (used for the per-stage files)."""
    run_dir = resolve_run_dir(run_dir)
    return render_transcript(run_dir, detail=detail, max_steps=max_steps or 10**9,
                             caps=caps, only=[session])


def render_stage_at(run_dir: Path, stage: int, detail: bool = True) -> tuple[str, str]:
    """`(agent, text)` for the `stage`-th session in pipeline order (1-based).

    The proposer addresses evidence by stage number from `render_index`: the
    full trace is thousands of steps and cannot be rendered into one document,
    so "read stage 14, steps 20-60 of it" is the only way to reach the coding
    and evaluation stages at all.
    """
    run_dir = resolve_run_dir(run_dir)
    rows = sessions(run_dir)
    if not rows:
        return "", "(no agent sessions recorded)"
    if not 1 <= int(stage) <= len(rows):
        return "", (f"ERROR: stage {stage} out of range 1..{len(rows)}; "
                    f"call list_traces for the stage list")
    _ts, sp, agent = rows[int(stage) - 1]
    return agent, render_stage(run_dir, sp, detail=detail)


def render_index(run_dir: Path) -> str:
    """Cheap outline of a run: every stage, its step range and error anchors.

    This is what a consumer reads first. It is ~1 kB regardless of trace size,
    so an investigator can decide which stage to grep or read instead of
    pulling a multi-hundred-kB document into its context.
    """
    run_dir = resolve_run_dir(run_dir)
    rows = sessions(run_dir)
    if not rows:
        return "(no agent sessions recorded)"
    lines = ["=== TRACE OUTLINE (stages in pipeline order) ==="]
    offset = 0
    anchors: list[str] = []
    for i, (ts, sp, agent) in enumerate(rows, 1):
        text = render_stage(run_dir, sp, detail=False)
        n = text.count("[step ")
        lo, hi = offset + 1, offset + n
        offset = hi
        lines.append(f"  stage {i:2}  {agent:44} steps {lo:5}-{hi:5} "
                     f"({n:4})  {sp.name}")
        for line in text.splitlines():
            if re.search(r"\bERROR\b|\bFAILED\b|Traceback|error:", line):
                anchors.append(line[:200])
    lines.append(f"total steps: {offset}")
    lines.append(f"error-anchor lines: {len(anchors)} "
                 f"(use grep_trace, or read_trace with a stage + step window)")
    lines += ["  " + a for a in anchors[:5]]
    return "\n".join(lines)


def render_transcript(run_dir: Path, detail: bool = False, max_steps: int = 400,
                      agent_filter: str | None = None,
                      caps: list[int] | None = None,
                      only: list[Path] | None = None) -> str:
    """Agent transcripts + stage events, one rendered step per line.

    Line shape (the `[step N]` prefix is parsed by rrsi.propose._read_trace):
        [step 7] AGENT ascendc-coder TURN: ...
        [step 8] TOOL ascendc-coder Bash  {command...}
        [step 8] RESULT ascendc-coder Bash: ...
        [step 9] STAGE codegen ok

    Sessions are rendered in pipeline order (see `sessions`), and `max_steps`
    is split across them proportionally with a floor — a cap smaller than the
    first stage no longer hides every stage after it.

    `agent_filter` restricts the render to the sessions whose name contains it
    and renumbers from 1, so "step 40 of the coding agent" means what a human
    expects. The session name is repeated on TOOL/RESULT lines because a bare
    tool name does not say which agent issued it.
    """
    run_dir = resolve_run_dir(run_dir)
    step_head, tool_head, args_head = caps or (
        [STEP_HEAD_DETAIL, TOOL_HEAD_DETAIL, TOOL_ARGS_HEAD_DETAIL] if detail
        else [STEP_HEAD, TOOL_HEAD, TOOL_ARGS_HEAD])
    if only is not None:
        chosen = [(0, sp, sp.name.rsplit("-", 1)[0] if sp.stem[-2:].isdigit()
                   else sp.stem) for sp in only]
    else:
        chosen = [r for r in sessions(run_dir)
                  if not agent_filter or agent_filter in r[1].name]
    lines: list[str] = []
    step = 0
    # Per-session step counts, so the budget can be split across stages.
    parsed: list[tuple[str, list[dict]]] = []
    for _ts, sp, agent in chosen:
        try:
            recs = [json.loads(x) for x in sp.read_text(errors="replace").splitlines()
                    if x.strip()]
        except Exception:  # noqa: BLE001
            continue
        parsed.append((agent, [r for r in recs if isinstance(r, dict)]))
    counts = [sum(len([b for b in (r.get("blocks") or []) if isinstance(b, dict)])
                  + (1 if r.get("result") else 0) for r in recs)
              for _a, recs in parsed]
    quotas = _allocate_step_budget(counts, max_steps) if only is None else counts
    for (agent, recs), quota in zip(parsed, quotas):
        if quota <= 0:
            continue
        head = step
        session_start, session_end = 0, 0
        truncated = False
        for rec in recs:
            if not isinstance(rec, dict) or not _record_step(rec):
                continue
            if step - head >= quota:
                truncated = True
                break
            role = str(rec.get("role") or rec.get("type") or "agent")
            for b in rec.get("blocks") or []:
                if not isinstance(b, dict):
                    continue
                kind = b.get("kind")
                if kind in ("text", "thinking"):
                    txt = b.get("text") or ""
                    if txt:
                        step += 1
                        lines.append(f"[step {step}] AGENT {agent} "
                                     f"{kind.upper()}: {_clip(txt, step_head)}")
                elif kind == "tool_use":
                    step += 1
                    nm = b.get("tool_name") or "?"
                    args = b.get("tool_input")
                    if isinstance(args, (dict, list)):
                        args = json.dumps(args, ensure_ascii=False)
                    lines.append(f"[step {step}] TOOL {agent} {nm}: "
                                 f"{_clip(args, args_head)}")
                elif kind == "tool_result":
                    step += 1
                    err = " (ERROR)" if b.get("is_error") else ""
                    lines.append(f"[step {step}] RESULT {agent}{err}: "
                                 f"{_clip(b.get('content'), tool_head)}")
            if rec.get("result") and step - head < quota:
                step += 1
                lines.append(f"[step {step}] AGENT {agent} RESULT: "
                             f"{_clip(rec['result'], step_head)}")
        if truncated:
            lines.append(f"[step {step}] ...[{agent} truncated at its "
                         f"{quota}-step share of the {max_steps}-step render "
                         f"budget; read the stage file for the full session]")
    ev = run_dir / "events.jsonl"
    if ev.is_file():
        try:
            for raw in ev.read_text(errors="replace").splitlines():
                if not raw.strip():
                    continue
                e = json.loads(raw)
                if not isinstance(e, dict):
                    continue
                etype = str(e.get("type") or "")
                if etype not in ("stage_enter", "stage_complete", "stage_aborted",
                                 "stage_skipped", "error", "gate_result",
                                 "chip_decision", "action_complete"):
                    continue
                step += 1
                if step > max_steps:
                    lines.append(f"[step {step}] ...[events truncated]")
                    break
                keep = {k: v for k, v in e.items() if k in
                        ("type", "stage", "status", "elapsed_ms", "message",
                         "total_iterations", "reason", "error_type")}
                lines.append(f"[step {step}] STAGE {_clip(json.dumps(keep, ensure_ascii=False), 600)}")
        except Exception:  # noqa: BLE001
            pass
    return "\n".join(lines) if lines else "(no agent transcript or events recorded)"


def render_full(rec: dict, detail: bool = False) -> str:
    """rec = the dict assembled by load_trial(). detail=True widens the caps so
    the analyst/digester can see what the agent actually did and submitted."""
    rep = rec.get("report") or {}
    v = rec.get("verdict") or {}
    op = rec.get("op") or {}
    meta = rec.get("meta") or {}
    prompt = rec.get("prompt") or ""
    head = [
        (f"TASK: {rec.get('task_id')} | operator: {op.get('name', '?')} "
         f"| class: {op.get('k', '?')} {op.get('category', '')} "
         f"| trial: {rec.get('trial')} | run: {meta.get('run_id', '?')}"),
        (f"STATUS: {meta.get('status', '?')} | wall_s: {meta.get('wall_s')} "
         f"| tokens: {meta.get('tokens')} | run_dir: {rec.get('run_dir', '?')}"),
        "",
        "=== GRADING (ground truth) ===",
        render_grading(v, rep, op, rec.get("rubric"), log=rec.get("compile_log") or "",
                       detail=detail),
    ]
    if prompt:
        head += ["",
                 "=== TASK PROMPT (the requirement the pipeline was given) ===",
                 _clip(prompt, PROMPT_HEAD_DETAIL if detail else PROMPT_HEAD)]
    # The trajectory is what a diagnosis is built from and what the proposer
    # reads by step range, so it goes first in the document and is never cut by
    # the source listing. Both are bounded on their own (max_steps × per-line
    # caps; a section budget for the listing), so the total-document trim below
    # is only a backstop — cutting mid-document used to drop whole stages, which
    # is what made every digester burn its turn budget looking for evidence that
    # had already been removed.
    if rec.get("run_dir"):
        run_dir = resolve_run_dir(Path(rec["run_dir"]))
        outline = render_index(run_dir)
        trajectory = render_trajectory(
            run_dir, detail=detail, max_steps=600 if detail else 250,
            budget=TRAJECTORY_BUDGET_DETAIL if detail else TRAJECTORY_BUDGET)
        trajectory = (outline + "\n\n=== TRAJECTORY (representative slices; "
                      "one file per stage sits next to this document) ===\n"
                      + trajectory)
    else:
        trajectory = "(no run directory)"
    parts = head + ["",
                    "=== TRAJECTORY ===",
                    trajectory,
                    "",
                    "=== SUBMITTED OPERATOR SOURCE (the only graded artefact) ===",
                    render_sources(rec.get("sources") or {}, detail=detail,
                                   budget=SOURCE_HEAD_DETAIL if detail
                                   else SOURCE_HEAD)]
    return _cap_total("\n".join(parts), head_frac=0.97,
                      limit=MAX_CHARS_DETAIL if detail else MAX_CHARS)


def render_stage_files(run_dir: Path, out_dir: Path, detail: bool = True) -> list[str]:
    """Write one file per agent session plus an `index.txt`; return their names.

    A whole run is 2000+ steps and 1.3M chars, which no consumer should have to
    pull in at once. Stage files let an investigator grep and read by range
    instead: `index.txt` is ~1 kB and says which stage holds what.
    """
    run_dir = resolve_run_dir(run_dir)
    rows = sessions(run_dir)
    if not rows:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for i, (_ts, sp, agent) in enumerate(rows, 1):
        name = f"{i:02d}-{re.sub(r'[^A-Za-z0-9_.-]+', '_', agent)}.txt"
        body = render_stage(run_dir, sp, detail=detail)
        (out_dir / name).write_text(body, encoding="utf-8")
        written.append(name)
    (out_dir / "index.txt").write_text(render_index(run_dir), encoding="utf-8")
    written.append("index.txt")
    return written


# ---------------------------------------------------------------- loading ---
def load_trial(job_dir, op: dict, trial: int, rubric: dict | None = None,
               task_id: str | None = None) -> dict | None:
    """Assemble one trial record for a task under `job_dir`; None if never ran.

    Layout (written by the adapter, see domains/ascendc-devkit/adapter.py):

        <job_dir>/<op_snake>/t<trial>/run/       the DevKit output root copy
        <job_dir>/<op_snake>/t<trial>/task.json  the task row + prompt digest
    """
    td = Path(job_dir) / str(op.get("op_snake") or op.get("name")) / f"t{trial}"
    task_json = _json(td / "task.json")
    run_dir = resolve_run_dir(td / "run")
    if not task_json and not run_dir.is_dir():
        return None
    try:
        meta = dict(task_json.get("meta") or {})
        if run_dir.is_dir():
            meta.setdefault("run_id", run_dir.name)
            # A run killed mid-flight has no task.json; the report still says
            # how far it got, and that is the evidence.
            meta.setdefault("wall_s", round(rep_total_ms(run_dir) / 1000.0, 1))
            meta.setdefault("status", "partial" if task_json else "no_task_record")
        rep = run_reports(run_dir) if run_dir.is_dir() else {}
        verdict = load_verdict(run_dir) if run_dir.is_dir() else {}
        sources = {}
        try:
            sources = find_sources(td, str(op.get("op_snake") or op.get("name")))
        except Exception:  # noqa: BLE001 — evidence rendering must never kill a round
            sources = {}
        log = find_compile_log(run_dir) if run_dir.is_dir() else ""
        if log:
            verdict["compile_log"] = log      # classify() reads it from the verdict
        return {
            "task_id": task_id or task_json.get("task_id") or op.get("name"),
            "op": op,
            "trial": trial,
            "run_dir": str(run_dir),
            "meta": meta,
            "report": rep,
            "verdict": verdict,
            "prompt": task_json.get("prompt") or "",
            "sources": sources,
            "compile_log": log,
            "rubric": rubric,
        }
    except Exception:  # noqa: BLE001
        return None


def stats(rec: dict) -> dict:
    """One-line summary fields for Domain.task_row (never raises)."""
    try:
        v = rec.get("verdict") or {}
        return {"class": classify(v, rec.get("report") or {}),
                "overall": v.get("overall_score"),
                "pass_rate": v.get("pass_rate"),
                "cases": f"{v.get('num_passed')}/{v.get('num_cases')}",
                "function": v.get("function_score"),
                "perf": v.get("performance_score"),
                "stages": len((rec.get("report") or {}).get("stages") or [])}
    except Exception:  # noqa: BLE001
        return {}
