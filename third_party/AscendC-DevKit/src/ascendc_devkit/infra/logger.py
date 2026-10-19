"""L7 Infrastructure — Structured logging with three-tier feedback.

P-BC1: ``_emit`` writes each line to the shared console (``sys.stderr``) AND the
current thread's run.log (``current_run_log_file``, thread-local — per-exec
isolation under batch's ``ThreadPoolExecutor``). The retired process-global
``_Tee`` on ``sys.stderr`` raced across sibling threads (run.log 串流/丢失);
run.log is now Logger-written and per-thread-isolated (§2.5 single path:
``run.log``'s only writer is ``Logger``).
"""

import sys
import time
import traceback

from ascendc_devkit.infra.log_capture import current_run_log_file


class Logger:
    """Three-tier feedback: Stage (coarse), Action (medium), Heartbeat (fine).

    Every log line is prefixed with ``[YYYY-MM-DD HH:MM:SS]`` so the console
    and redirected log files carry full wall-clock timestamps — date included,
    so logs spanning multiple days stay unambiguous.
    """

    @staticmethod
    def _ts() -> str:
        return time.strftime("[%Y-%m-%d %H:%M:%S]")

    @staticmethod
    def _emit(line: str, *, end: str = "\n", flush: bool = False) -> None:
        """Write ``line`` to the shared console (``sys.stderr``) + the current
        thread's run.log (per-exec isolated, P-BC1).

        Either sink is best-effort: a closed run.log (thread teardown) or a
        hostile terminal never raises — logging must never break a run. Console
        is shared under concurrency (output interleaves, acceptable — it's a
        shared terminal); run.log is per-thread-isolated so it never 串流.
        """
        print(line, end=end, file=sys.stderr, flush=flush)
        f = current_run_log_file()
        if f is not None:
            try:
                f.write(line + (end if end else ""))
                f.flush()
            except (ValueError, OSError):
                pass

    @staticmethod
    def stage_header(stage_name: str, total_stages: int, current_index: int,
                     elapsed_sec: float = 0) -> None:
        elapsed = f"{elapsed_sec:.0f}s elapsed" if elapsed_sec else ""
        rule = "━" * 40
        Logger._emit(f"\n{Logger._ts()}  {rule} [{stage_name}] {current_index}/{total_stages} {elapsed}")

    @staticmethod
    def stage_done(stage_name: str, elapsed_ms: int,
                   artifacts: dict | None = None, status: str = "ok") -> None:
        """Print a stage's completion line.

        ``status`` controls the leading glyph so a failed stage no longer
        masquerades as success (§P7.1): "ok" → ✓, "partial" → ⚠ (ran but output
        is half-baked / contract unmet), anything else → ✗ (failed). The status
        word is appended for non-ok stages so the cause is greppable.
        """
        elapsed = f"{elapsed_ms / 1000:.1f}s"
        rule = "━" * 40
        glyph = {"ok": "✓", "partial": "⚠"}.get(status, "✗")
        suffix = "" if status == "ok" else f" [{status}]"
        Logger._emit(f"{Logger._ts()}  {rule} {glyph} {stage_name} done ({elapsed}){suffix}")
        # §P6: list the stage's products (path + size) so the user can verify
        # intermediate artifacts without hunting through the output dir. artifacts
        # is {relpath: content}; omitted/empty → no list (e.g. deterministic or
        # no-op stages).
        if artifacts:
            for rel in sorted(artifacts):
                content = artifacts[rel] or ""
                lines = content.count("\n") + 1 if content else 0
                Logger._emit(f"{Logger._ts()}      ↳ {rel} ({lines} lines, {len(content)} bytes)")

    @staticmethod
    def stage_skipped(stage_name: str, reason: str) -> None:
        """P6-b: log an intentionally skipped stage.

        Uses ○ glyph to distinguish from ✓ done (normal completion),
        ⚠ partial (contract unmet), and ✗ failed (failed).
        """
        rule = "━" * 40
        Logger._emit(f"{Logger._ts()}  {rule} ○ {stage_name} skipped ({reason})")

    @staticmethod
    def action(action_type: str, details: str) -> None:
        Logger._emit(f"{Logger._ts()}    • {action_type} {details}")

    @staticmethod
    def heartbeat(message: str) -> None:
        Logger._emit(f"{Logger._ts()}    ⠋ {message}", end="\r", flush=True)

    @staticmethod
    def info(msg: str) -> None:
        Logger._emit(f"{Logger._ts()}    [INFO] {msg}")

    @staticmethod
    def warn(msg: str, exc_info: bool = False) -> None:
        Logger._emit(f"{Logger._ts()}    [WARN] {msg}")
        if exc_info:
            Logger._emit_traceback()

    @staticmethod
    def error(msg: str, exc_info: bool = False) -> None:
        Logger._emit(f"{Logger._ts()}    [ERROR] {msg}")
        if exc_info:
            Logger._emit_traceback()

    @staticmethod
    def _emit_traceback() -> None:
        """Append the current exception traceback (best-effort, never raises).

        Called inside an ``except`` block: ``traceback.format_exc()`` captures
        the in-flight exception. §1.2 可诊断 — surface the real first-cause
        (e.g. NPU runtime init ERR99999) instead of a swallowed generic message.
        """
        tb = traceback.format_exc()
        if tb and tb.strip() != "NoneType: None":
            for line in tb.rstrip().splitlines():
                Logger._emit(f"{Logger._ts()}      {line}")
