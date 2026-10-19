"""L2 Application — resume target resolver.

Unifies ``--resume <id>`` for single-run and batch resume by detecting the
id's kind from its LOCATION in ``output/`` (not its string — batch_id and
execution_id share the ts+uuid format, so string-based detection is
ambiguous).

Layered ids (L4 §54):
- single-op run lives at ``output/<run_id>/`` (flat) — its dir directly holds
  ``state_snapshot.json``.
- batch lives at ``output/<batch_id>/`` containing execution dirs
  ``output/<batch_id>/<execution_id>/`` — each execution dir holds
  ``state_snapshot.json``; the batch dir itself does NOT.

Detection (three states, mutually exclusive by location):
1. ``output/<id>/state_snapshot.json`` exists        → flat single run
2. ``output/<id>/`` contains ≥1 run subdirs           → batch (resume all)
3. ``output/*/<id>/state_snapshot.json`` matches      → nested execution (single)

Layering (§1.1): L2 pure logic + stdlib + L4 (ConfigError). No L1/L3 import.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ascendc_devkit.domain.exceptions import ConfigError


@dataclass(frozen=True)
class ResumeTarget:
    """Where and how to resume.

    - kind == "single": resume one run; ``id`` is its run_id, ``output_root``
      is where its dir lives (``output`` for flat, ``output/<batch_id>`` for a
      nested execution).
    - kind == "batch": resume every execution under the batch; ``id`` is the
      batch_id, ``output_root`` is the top-level output root.
    """
    kind: str            # "single" | "batch"
    id: str              # run_id (single) or batch_id (batch)
    output_root: str     # output_root to load the run/batch from


def resolve_resume_target(id_: str, output_root: str = "output") -> ResumeTarget:
    """Resolve ``id_`` to a ResumeTarget by location (§1.3 fail-fast).

    Raises ConfigError on 0 matches or ambiguous nested matches.
    """
    base = Path(output_root).resolve()
    direct = base / id_

    # State 1: flat single run (or a batch dir that ALSO has a direct snapshot
    # — impossible under the layered layout, since batch dirs hold exec SUBDIRS
    # not a direct snapshot; so a direct snapshot unambiguously means a run).
    if (direct / "state_snapshot.json").exists():
        return ResumeTarget("single", id_, output_root)

    # State 2: batch dir — contains ≥1 execution subdirs (each a real run).
    if direct.is_dir() and _contains_runs(direct):
        return ResumeTarget("batch", id_, output_root)

    # State 3: nested execution — id_ is an exec under some batch.
    matches = [m for m in base.glob(f"*/{id_}")
               if m.is_dir() and (m / "state_snapshot.json").exists()]
    if len(matches) == 1:
        # output_root scoped to the batch dir (output/<batch_id>), keeping the
        # caller's output_root form (relative or absolute) — consistent with
        # state 1 which returns output_root verbatim.
        return ResumeTarget("single", id_, f"{output_root}/{matches[0].parent.name}")
    if len(matches) > 1:
        raise ConfigError(
            id_,
            f"resume id '{id_}' matched multiple nested executions under "
            f"{output_root}/ (batches: {[m.parent.name for m in matches]}); "
            f"pass the batch_id to resume the whole batch instead")
    raise ConfigError(
        id_,
        f"resume id '{id_}' not found under {output_root}/ (neither a run nor "
        f"a batch). Check the id or pass the matching --output-root.")


def _contains_runs(dir_path: Path) -> bool:
    """A batch dir contains ≥1 execution subdirs (each holding a
    state_snapshot.json)."""
    if not dir_path.is_dir():
        return False
    return any(d.is_dir() and (d / "state_snapshot.json").exists()
               for d in dir_path.iterdir())
