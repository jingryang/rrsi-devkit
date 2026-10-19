"""L7 Infrastructure — bind a run's log/op identity to the current execution context.

P-BC1 fix: previously a process-global ``_Tee`` on ``sys.stderr`` mirrored all
stderr writes to ``run.log``; under batch's ``ThreadPoolExecutor`` (sibling
threads) the global ``_BINDING`` / ``sys.stderr`` raced — a sibling thread's
rebind closed this thread's file mid-write → run.log 串流/丢失 (see
``docs/plan/opencode-batch-concurrency/01-problems.md`` P-BC1).

``run.log``/op_name are bound via ``contextvars.ContextVar`` rather than
``threading.local``. For a plain new ``threading.Thread`` the two behave
identically — each thread gets its own empty context, so sibling exec worker
threads under batch's ``ThreadPoolExecutor`` stay isolated from each other
exactly as before (P-BC1 unaffected). The difference only matters for a thread
started via ``spawn_context_thread`` (below): it explicitly copies the
*current* context before starting, so it inherits whatever binding was active
in its parent thread at spawn time — e.g. an opencode backend's SSE daemon
reader thread inheriting the exec worker's run.log/op_name binding (AU-6),
which ``threading.local`` could never do. ``Logger._emit`` is unchanged —
``run.log``'s only writer is still ``Logger`` (§2.5 single path).

Crash-safety unchanged: the file is line-buffered and flushed per write, so a
SIGKILL loses at most the half-line being written. ``run.log`` is append-only
and never parsed (``events.jsonl`` is the authoritative record).
"""

from __future__ import annotations

import contextvars
import functools
import threading
import warnings
from typing import IO, Any, Callable, TypeVar

__all__ = [
    "bind_run_log",
    "unbind_run_log",
    "current_run_log_file",
    "bind_op_name",
    "current_op_name",
    "spawn_context_thread",
    "context_callable",
]

R = TypeVar("R")

# Bound by ``bind_run_log`` (in the exec's worker thread), read by
# ``Logger._emit`` (same thread, or a thread started via
# ``spawn_context_thread`` that copied this context).
_run_log_ctx: contextvars.ContextVar[IO[str] | None] = contextvars.ContextVar(
    "run_log_file", default=None)

# Bound alongside ``_run_log_ctx`` (same call sites in dispatcher.py) so
# per-exec log lines (e.g. opencode's ``agent_stream``) can be attributed to
# the op they belong to under batch concurrency (AU-7).
_op_name_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "op_name", default="")


def bind_run_log(path: Any) -> None:
    """Bind ``run.log`` to the CURRENT execution context (line-buffered).

    P-BC1: per-thread isolation replaces the process-global ``_Tee`` on
    ``sys.stderr`` — sibling threads no longer race on a shared ``_BINDING`` /
    ``sys.stderr``. Console output stays on the shared ``sys.stderr``
    (interleaves under concurrency, acceptable); ``run.log`` is written by
    ``Logger._emit`` and is per-exec-isolated. Repeated calls in the same
    context close the prior handle first (no leak). Safe no-op on open
    failure: warns and leaves no binding — logging must never break a run.
    """
    unbind_run_log()
    try:
        # buffering=1 → line-buffered (text mode). Combined with the per-write
        # flush in Logger._emit, completed lines reach the OS page cache
        # immediately and survive a process SIGKILL.
        file = open(path, "a", encoding="utf-8", buffering=1)
    except Exception as e:  # noqa: BLE001 — logging must never break the run
        warnings.warn(f"run.log 绑定失败 ({path}): {e}；控制台日志不落盘", stacklevel=2)
        return
    _run_log_ctx.set(file)


def unbind_run_log() -> None:
    """Close the current context's run.log file. Idempotent."""
    f = _run_log_ctx.get()
    if f is None:
        return
    _run_log_ctx.set(None)
    try:
        f.close()
    except Exception:  # noqa: BLE001
        pass


def current_run_log_file() -> IO[str] | None:
    """The current context's run.log file handle, or ``None``.

    ``Logger._emit`` uses this to mirror console output into the per-exec run.log.
    Returns ``None`` when no binding is active in the current context (Logger then
    writes console only — e.g. the main thread's batch-level progress lines).
    """
    return _run_log_ctx.get()


def bind_op_name(name: str) -> None:
    """Bind the current execution context's op name (for log attribution, AU-7)."""
    _op_name_ctx.set(name or "")


def current_op_name() -> str:
    """The current context's op name, or ``""`` when unbound."""
    return _op_name_ctx.get()


def spawn_context_thread(target: Callable[[], None], *, daemon: bool = True) -> threading.Thread:
    """Start a thread that inherits the CALLER's current context (run.log/op_name/...).

    A plain ``threading.Thread`` starts with a fresh, empty ``contextvars``
    context — it would not see the caller's ``bind_run_log``/``bind_op_name``
    binding (this is what caused AU-6: opencode's SSE reader thread couldn't
    see its exec worker's run.log). This is the single entry point for
    "background thread that should keep logging into the same run.log/op
    attribution as its parent" — future call sites should use this instead of
    hand-rolling ``contextvars.copy_context().run(...)``, so the inheritance
    is never forgotten at a new call site.
    """
    ctx = contextvars.copy_context()
    thread = threading.Thread(target=lambda: ctx.run(target), daemon=daemon)
    thread.start()
    return thread


def context_callable(fn: Callable[..., R]) -> Callable[..., R]:
    """Wrap ``fn`` so a ``ThreadPoolExecutor`` worker runs it inside a copy of
    THIS thread's context — inheriting run.log/op_name bindings (AU-8).

    Pool workers start with an empty ``contextvars`` context, so without this
    wrap a ForkJoin/SideTask branch running in a worker cannot see the dispatch
    thread's ``bind_run_log`` binding → its ``Logger`` output (incl. opencode
    SSE ``agent_stream``) is dropped from per-op run.log (the AU-8 defect:
    ForkJoin branches invisible in run.log for up to hours).

    Sibling of ``spawn_context_thread`` (which gives a background *thread* the
    same inheritance). Capture happens HERE, in the submitting thread where the
    binding is active; the returned callable runs ``fn`` via ``ctx.run`` in
    whichever worker invokes it.

    **One wrapped callable per pool task** — a single ``Context`` object cannot
    be entered by two threads at once (CPython raises ``RuntimeError: cannot
    enter context: ... is already entered``). For a multi-task ``pool.map``,
    build one wrapped callable per item, e.g.::

        wrapped = [context_callable(_run) for _ in pending]
        pool.map(lambda r, x: r(x), wrapped, pending)

    For a single ``pool.submit`` one wrapped callable is correct.
    """
    ctx = contextvars.copy_context()

    @functools.wraps(fn)
    def _runner(*args: Any, **kwargs: Any) -> R:
        return ctx.run(fn, *args, **kwargs)

    return _runner
