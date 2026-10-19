"""L7 Infrastructure — Isolated workspace management."""

from __future__ import annotations

import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ascendc_devkit.infra.logger import Logger


def new_run_id() -> str:
    """Generate a run id: ``<YYYYMMDD-HHMMSS>-<uuid6>`` (UTC).

    Single source for the id format shared by three identities: a single-op
    ``run_id``, a batch-op ``execution_id`` (= run_id semantics), and a
    ``batch_id``. Callers that need the id BEFORE dispatch (e.g. batch_runner
    pre-assigning execution_ids so ``output/<batch_id>/<exec>/`` lands in one
    step) call this directly and pass it through ``Workspace.create(run_id=)``;
    callers that don't care (single-op run) let ``Workspace.create`` generate
    it. One format, one generator — no per-site ts/uuid duplication (§1.2).
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    short = uuid.uuid4().hex[:6]
    return f"{ts}-{short}"


def session_sidecar_path(run_dir, agent_name: str, branch_label: str = "",
                         stage_name: str = "") -> Path | None:
    """Path to the latest-session resume sidecar: ``<run_dir>/agents/<stem>.session.json``.

    The stem matches the backend's transcript stem (``agent_name``, optionally
    suffixed with ``-branch_label`` for fork-join role agents) but carries NO
    seq counter — the sidecar always reflects the most recent session for that
    stem, so a cross-run resume picks up the last interrupted spawn.

    键含 stage 维度（review M2，2026-08-11）：同一 agent_name 会被不同 stage 的
    任务复用（如 ascendc-design-generator 用于 general-design/dd-intake/
    template-division 等多个 substage；ascendc-coder 用于 smoke/codegen），
    仅 (agent_name, branch_label) 作键时，前一个任务被切留下的 sidecar 会被后
    一个不同任务误 resume（自动 resume 用"继续"续跑前任务的 session，prompt 不
    注入）。stage_name 并入 stem 使不同任务构造性分离（§2.9）；同一 stage 内
    跨迭代/cross-run resume 键不变（stage_name 稳定），行为不变。

    Written by ``SDKBackend`` at session_id capture (mid-spawn, before any
    crash or hard kill) and deleted on a clean finish. Read by
    ``codegen.actions`` to issue a resume spawn. The single source for the path
    so the writer (L5 backend, holds a Path) and the reader (L3 stage, holds a
    Workspace) cannot drift. Returns None when ``run_dir`` is falsy (no
    workspace configured — resume is best-effort, never blocks a spawn).
    """
    if not run_dir:
        return None
    parts = [agent_name]
    if stage_name:
        parts.append(stage_name)
    if branch_label:
        parts.append(branch_label)
    stem = "-".join(parts)
    return Path(run_dir) / "agents" / f"{stem}.session.json"


class Workspace:
    """Isolated output directory for a single run."""

    def __init__(self, base_dir: Path, run_id: str):
        self._base = base_dir
        self.run_id = run_id
        self.dir = base_dir / run_id

    @classmethod
    def create(cls, output_root: str = "output", run_id: str | None = None) -> Workspace:
        if run_id is None:
            run_id = new_run_id()
        base = Path(output_root).resolve()
        ws = cls(base, run_id)
        ws.dir.mkdir(parents=True, exist_ok=True)
        (ws.dir / "artifacts").mkdir()
        (ws.dir / "agents").mkdir()
        (ws.dir / "subprocess").mkdir()
        return ws

    @classmethod
    def from_existing(cls, run_id: str, output_root: str = "output") -> Workspace:
        base = Path(output_root).resolve()
        ws = cls(base, run_id)
        if not ws.dir.exists():
            raise FileNotFoundError(f"Workspace not found: {ws.dir}")
        return ws

    @property
    def artifacts(self) -> Path:
        return self.dir / "artifacts"

    @property
    def agents_log(self) -> Path:
        return self.dir / "agents"

    def transcript_path(self, agent_name: str, seq: int) -> Path:
        """Return the jsonl transcript path for one agent session.

        Layout: ``<run>/agents/<agent_name>-<seq:02d>.jsonl``. Ensures the
        agents/ directory exists (workspaces loaded via from_existing() may not
        have created it). One file per spawn so multiple rounds of the same
        agent don't clobber each other.
        """
        self.agents_log.mkdir(parents=True, exist_ok=True)
        return self.agents_log / f"{agent_name}-{seq:02d}.jsonl"

    def session_sidecar(self, agent_name: str, branch_label: str = "",
                        stage_name: str = "") -> Path | None:
        """Path to the resume sidecar for this agent stem (see
        :func:`session_sidecar_path`). Convenience wrapper for stage callers
        that hold a Workspace rather than a bare run-dir Path."""
        return session_sidecar_path(self.dir, agent_name, branch_label,
                                    stage_name)

    @property
    def subprocess_log(self) -> Path:
        return self.dir / "subprocess"

    @property
    def events_path(self) -> Path:
        return self.dir / "events.jsonl"

    @property
    def state_snapshot_path(self) -> Path:
        return self.dir / "state_snapshot.json"

    @property
    def report_path(self) -> Path:
        return self.dir / "report.md"

    @property
    def report_json_path(self) -> Path:
        return self.dir / "report.json"

    # —— Diagnostic-pack paths (run-diagnostic-provenance, step-67) ————————
    # PROVENANCE.json: immutable run provenance written once at dispatch.
    # MANIFEST.json: per-file sha256 manifest for pack-run/verify-run integrity.
    # agents/index.json: action↔session↔transcript mapping for localization.

    @property
    def provenance_path(self) -> Path:
        return self.dir / "PROVENANCE.json"

    @property
    def manifest_path(self) -> Path:
        return self.dir / "MANIFEST.json"

    @property
    def agent_index_path(self) -> Path:
        return self.dir / "agents" / "index.json"

    def mark_dirty(self) -> None:
        (self.dir / ".dirty").touch()

    def is_dirty(self) -> bool:
        return (self.dir / ".dirty").exists()

    def cleanup(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir)

    def remove_skills_anchors(self) -> int:
        """Remove framework-planted ``.claude/skills`` discovery symlinks
        under this run's artifacts (see ``capabilities.agent._shared
        ._ensure_skills_anchor``).

        Each per-stage agent cwd gets one of these as a spawn-time anchor so
        the Claude/OpenCode backends can natively discover the repo's single
        skill tree from a deep artifacts cwd. The anchor is a symlink (~50
        bytes) so it's harmless inside this run's own directory tree — but a
        naive archiver that dereferences symlinks (e.g. ``zip -r`` without
        ``-y``) will expand every one of them into a full copy of the repo's
        skill tree, inflating an archive by orders of magnitude. Removing them
        at run finalization keeps the run dir anchor-free regardless of which
        archiving tool a caller later uses.

        Safe at any terminal point: ``_ensure_skills_anchor`` is idempotent
        and re-plants the anchor on the next spawn, so a later ``--resume``
        recreates what it needs. Only removes symlinks (never touches a
        real directory that a warned-about naming collision left in place).
        Returns the count removed.
        """
        removed = 0
        if not self.dir.exists():
            return removed
        for anchor in self.dir.rglob(".claude/skills"):
            if anchor.is_symlink():
                try:
                    anchor.unlink()
                    removed += 1
                except OSError as e:
                    Logger.warn(f"could not remove skills anchor {anchor}: {e}")
        return removed
