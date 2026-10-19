"""L2 Application — Report generation from events.jsonl."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


# P134 (trial-20260730): map runner's derived stage_status → report status vocab.
# runner emits stage_complete with status ∈ {ok, partial, failed} (normal finish)
# or "cancelled" (cancel path). Report vocab: ok | partial | error | aborted |
# skipped | unverified | unknown. A missing/unknown key passes through verbatim
# (defensive — never silently绿).
_REPORT_STATUS_MAP = {
    "ok": "ok",
    "partial": "partial",
    "failed": "error",
    "cancelled": "aborted",
}


def read_run_events(run_id: str, output_root: str = "output") -> list[dict] | None:
    """Read a run's events.jsonl via the L2 application layer (KNOWN 清零 step-5).

    show(L1) cannot import L7 event_log directly (matrix 1→{2,4}); this L2 entry
    resolves the run workspace and reads its events, so the CLI stays on the
    application seam.
    """
    from ascendc_devkit.infra.event_log import EventLog
    from ascendc_devkit.infra.workspace import Workspace

    try:
        ws = Workspace.from_existing(run_id, output_root=output_root)
    except FileNotFoundError:
        return None
    if not ws.events_path.exists():
        return None
    return EventLog.read(ws.events_path)


@dataclass
class StageSummary:
    name: str
    elapsed_ms: int = 0
    iterations: int = 0
    status: str = "unknown"   # ok | partial | error | aborted | skipped | unverified


@dataclass
class Report:
    run_id: str = ""
    workflow: str = ""
    stages: list[StageSummary] = field(default_factory=list)
    total_elapsed_ms: int = 0
    exit_code: int = 0
    errors: list[str] = field(default_factory=list)
    # step-67: provenance header so a reviewer sees version / backend / danger
    # warnings at first glance (mirrors PROVENANCE.json + the run_started event).
    provenance_summary: str = ""
    provenance_warnings: list[str] = field(default_factory=list)

    @staticmethod
    def generate(workspace, run_elapsed_ms: int = 0) -> Report:
        """Generate report from workspace events.jsonl.

        ``run_elapsed_ms`` is the dispatcher wall-clock. When >0 it is used
        as ``total_elapsed_ms`` instead of summing stage_complete events,
        covering aborted stages that never emitted their completion.
        """
        from ascendc_devkit.infra.event_log import EventLog

        events_path = workspace.report_path.parent / "events.jsonl"
        if not events_path.exists():
            return Report(run_id=workspace.run_id, errors=["No events.jsonl found"])

        events = EventLog.read(events_path)
        return Report._from_events(workspace.run_id, events,
                                   run_elapsed_ms=run_elapsed_ms)

    @staticmethod
    def _from_events(run_id: str, events: list[dict],
                     run_elapsed_ms: int = 0) -> Report:
        stages: dict[str, StageSummary] = {}
        total_elapsed = 0
        errors: list[str] = []
        stubbed_stages: set[str] = set()

        for evt in events:
            etype = evt.get("type", "")

            if etype == "stage_enter":
                name = evt.get("stage", "unknown")
                stages[name] = StageSummary(name=name)

            elif etype == "stage_complete":
                name = evt.get("stage", "unknown")
                if name in stages:
                    stages[name].elapsed_ms = evt.get("elapsed_ms", 0)
                    stages[name].iterations = evt.get("total_iterations", 0)
                    # P134 (trial-20260730): honor the event's status instead of
                    # unconditionally绿. runner now stamps the derived stage_status
                    # (ok/partial/failed) — and the cancelled path stamps
                    # "cancelled". A stage that halted/blocked must not read as
                    # ok (假绿 hid real failures from the batch overview).
                    # missing status → "unknown"（绝不静默绿；runner 修复后
                    # stage_complete 恒带 status，缺失即异常事件）。已知词经
                    # _REPORT_STATUS_MAP 归一化，未知词原样透传（defensive）。
                    _st = evt.get("status", "unknown")
                    stages[name].status = _REPORT_STATUS_MAP.get(_st, _st)

                total_elapsed += evt.get("elapsed_ms", 0)

            elif etype == "stage_aborted":
                name = evt.get("stage", "unknown")
                if name in stages:
                    stages[name].elapsed_ms = evt.get("elapsed_ms", 0)
                    stages[name].status = "aborted"

                total_elapsed += evt.get("elapsed_ms", 0)

            elif etype == "stage_skipped":
                name = evt.get("stage", "unknown")
                if name in stages:
                    stages[name].status = "skipped"

            elif etype == "action_complete":
                # Detect stubbed gate results
                gate_result = evt.get("gate_result", {})
                if gate_result:
                    metrics = gate_result.get("metrics", {})
                    if metrics.get("stubbed"):
                        stage_name = evt.get("stage", "")
                        if stage_name:
                            stubbed_stages.add(stage_name)

            elif etype == "error":
                errors.append(evt.get("message", "Unknown error"))

        # Mark stages with stubbed verification as "unverified"
        for name in stubbed_stages:
            if name in stages and stages[name].status == "ok":
                stages[name].status = "unverified"

        # P9: dispatcher wall-clock covers aborted stages that never emitted
        # stage_complete.  When provided (>0) it replaces the event-sum total.
        if run_elapsed_ms > 0:
            total_elapsed = run_elapsed_ms

        # step-67: provenance header (best-effort read of PROVENANCE.json).
        prov_summary = ""
        prov_warnings: list[str] = []
        try:
            _pp = workspace.provenance_path
            if _pp.exists():
                from ascendc_devkit.infra.provenance import summary_from_dict
                _pd = json.loads(_pp.read_text(encoding="utf-8"))
                prov_summary = summary_from_dict(_pd)
                prov_warnings = list(_pd.get("warnings") or [])
        except Exception:
            pass

        return Report(
            run_id=run_id,
            stages=list(stages.values()),
            total_elapsed_ms=total_elapsed,
            errors=errors,
            provenance_summary=prov_summary,
            provenance_warnings=prov_warnings,
        )

    def write_markdown(self, path: Path) -> None:
        lines = [
            f"# Run Report: {self.run_id}",
            "",
            f"**Total elapsed**: {self.total_elapsed_ms}ms",
        ]
        if self.provenance_summary:
            lines += ["", f"**Provenance**: {self.provenance_summary}"]
        if self.provenance_warnings:
            lines += ["", f"**⚠ Provenance warnings** ({len(self.provenance_warnings)}):"]
            lines += [f"- {w}" for w in self.provenance_warnings]
        lines += [
            "",
            "## Stages",
            "",
            "| Stage | Status | Iterations | Elapsed |",
            "|-------|--------|------------|---------|",
        ]
        for s in self.stages:
            lines.append(f"| {s.name} | {s.status} | {s.iterations} | {s.elapsed_ms}ms |")

        if self.errors:
            lines.append("")
            lines.append("## Errors")
            for e in self.errors:
                lines.append(f"- {e}")

        path.write_text("\n".join(lines) + "\n")

    def write_json(self, path: Path) -> None:
        data = {
            "run_id": self.run_id,
            "total_elapsed_ms": self.total_elapsed_ms,
            "stages": [
                {
                    "name": s.name,
                    "status": s.status,
                    "iterations": s.iterations,
                    "elapsed_ms": s.elapsed_ms,
                }
                for s in self.stages
            ],
            "errors": self.errors,
            "provenance_summary": self.provenance_summary,
            "provenance_warnings": self.provenance_warnings,
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
