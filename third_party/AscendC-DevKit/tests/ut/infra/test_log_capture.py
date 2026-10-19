"""UT for infra.log_capture — per-thread run.log binding (P-BC1).

P-BC1 fix: ``run.log`` is thread-local (per-exec isolated under batch's
``ThreadPoolExecutor``), retiring the process-global ``_Tee`` on ``sys.stderr``
that raced across sibling threads (run.log 串流/丢失). ``Logger._emit`` writes
the shared console (``sys.stderr``) + the current thread's run.log.
"""

from __future__ import annotations

import sys
import threading

import pytest

from ascendc_devkit.infra import log_capture
from ascendc_devkit.infra.log_capture import (
    bind_run_log,
    unbind_run_log,
    current_run_log_file,
    bind_op_name,
    current_op_name,
    spawn_context_thread,
)
from ascendc_devkit.infra.logger import Logger


@pytest.fixture(autouse=True)
def _unbind_current_thread():
    yield
    unbind_run_log()
    bind_op_name("")


def test_bind_logger_writes_to_runlog_and_console(tmp_path, capsys):
    log = tmp_path / "run.log"
    bind_run_log(log)

    Logger.action("test", "hello run-log")

    err = capsys.readouterr().err
    assert "hello run-log" in err                              # console
    assert "hello run-log" in log.read_text(encoding="utf-8")  # durable run.log


def test_unbind_closes_runlog(tmp_path, capsys):
    log = tmp_path / "run.log"
    bind_run_log(log)
    unbind_run_log()

    Logger.action("test", "after unbind")
    capsys.readouterr()  # drain console

    assert "after unbind" not in log.read_text(encoding="utf-8")  # file closed
    assert current_run_log_file() is None


def test_rebind_closes_previous_file(tmp_path, capsys):
    log1 = tmp_path / "run1.log"
    log2 = tmp_path / "run2.log"
    bind_run_log(log1)
    file1 = current_run_log_file()

    bind_run_log(log2)  # implicit unbind of log1 in THIS thread

    assert file1.closed  # prior handle closed — no fd leak
    Logger.action("test", "to log2")
    capsys.readouterr()
    assert "to log2" in log2.read_text(encoding="utf-8")
    assert "to log2" not in log1.read_text(encoding="utf-8")


def test_append_mode_preserves_prior_content(tmp_path, capsys):
    log = tmp_path / "run.log"
    log.write_text("PRE-EXISTING\n", encoding="utf-8")
    bind_run_log(log)

    Logger.action("test", "appended line")
    capsys.readouterr()

    content = log.read_text(encoding="utf-8")
    assert "PRE-EXISTING" in content
    assert "appended line" in content


def test_bind_failure_does_not_break_run(tmp_path, monkeypatch):
    bad = tmp_path / "no_such_dir" / "run.log"
    monkeypatch.setattr(log_capture.warnings, "warn", lambda *a, **k: None)

    bind_run_log(bad)

    assert current_run_log_file() is None  # no binding on failure
    Logger.action("test", "no crash")      # must not raise


def test_concurrent_threads_runlog_isolated(tmp_path):
    """P-BC1 regression: sibling threads each bind their own run.log and Logger
    output is isolated per thread — no cross-thread 串流/丢失 (the exact bug under
    the old process-global ``_Tee`` on ``sys.stderr``)."""
    errors: list[BaseException] = []

    def worker(i):
        try:
            bind_run_log(tmp_path / f"run{i}.log")
            for n in range(50):
                Logger.action("test", f"thread{i}-{n}")
            unbind_run_log()
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"concurrent bind/write raised: {errors}"
    # Each run.log contains ONLY its own thread's lines (no 串流).
    for i in range(4):
        content = (tmp_path / f"run{i}.log").read_text(encoding="utf-8")
        assert f"thread{i}-" in content, f"run{i}.log lost its own lines (P-BC1)"
        for j in range(4):
            if j != i:
                assert f"thread{j}-" not in content, (
                    f"run{i}.log 串入了 thread{j} 的内容 (P-BC1 regression)")


def test_no_bind_logger_writes_console_only(tmp_path, capsys):
    # No active binding in this thread: Logger writes console only, no crash.
    Logger.action("test", "console only")

    err = capsys.readouterr().err
    assert "console only" in err
    assert current_run_log_file() is None


def test_op_name_default_empty():
    assert current_op_name() == ""


def test_bind_op_name_roundtrip():
    bind_op_name("MyOp")
    assert current_op_name() == "MyOp"


def test_bind_op_name_none_treated_as_empty():
    bind_op_name("MyOp")
    bind_op_name(None)
    assert current_op_name() == ""


def test_spawn_context_thread_with_no_binding_sees_no_binding():
    """No run.log/op_name bound in the caller → the spawned thread sees none
    either (no crash, no phantom inheritance)."""
    seen: dict = {}

    def _probe():
        seen["file"] = current_run_log_file()
        seen["op"] = current_op_name()

    thread = spawn_context_thread(_probe)
    thread.join(timeout=5.0)

    assert seen["file"] is None
    assert seen["op"] == ""


def test_spawn_context_thread_inherits_caller_binding(tmp_path):
    """AU-6 regression: a thread started via ``spawn_context_thread`` (e.g.
    opencode's SSE daemon reader) inherits the CALLER thread's run.log/op_name
    binding — unlike a plain ``threading.Thread``, which would see nothing and
    silently drop agent_stream lines from run.log (the exact AU-6 defect)."""
    log = tmp_path / "run.log"
    bind_run_log(log)
    bind_op_name("MyOp")

    seen: dict = {}

    def _child():
        seen["file"] = current_run_log_file()
        seen["op"] = current_op_name()
        Logger.action("agent_stream", "turn 1 from child thread")

    thread = spawn_context_thread(_child)
    thread.join(timeout=5.0)

    assert seen["file"] is current_run_log_file()
    assert seen["op"] == "MyOp"
    assert "turn 1 from child thread" in log.read_text(encoding="utf-8")


def test_context_callable_pool_worker_inherits_binding(tmp_path):
    """AU-8 regression: a callable wrapped with ``context_callable`` and submitted
    to a ``ThreadPoolExecutor`` inherits the SUBMITTING thread's run.log/op_name
    binding — so its ``Logger`` output reaches per-op run.log. A pool worker
    otherwise starts with an empty ``contextvars`` context and silently drops
    the lines (the AU-8 defect: ForkJoin/SideTask branches invisible in run.log).
    """
    from concurrent.futures import ThreadPoolExecutor

    log = tmp_path / "run.log"
    bind_run_log(log)
    bind_op_name("MyOp")
    handle = current_run_log_file()

    seen: dict = {}

    def _probe():
        seen["file"] = current_run_log_file()
        seen["op"] = current_op_name()
        Logger.action("agent_stream", "turn 1 from pool worker")

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(log_capture.context_callable(_probe))
        fut.result(timeout=5.0)

    assert seen["file"] is handle
    assert seen["op"] == "MyOp"
    assert "turn 1 from pool worker" in log.read_text(encoding="utf-8")


def test_plain_callable_in_pool_drops_binding(tmp_path):
    """AU-8 contrast (documents why ``context_callable`` is required): an
    UN-wrapped callable in a pool worker does NOT inherit the caller's binding
    — pool worker's contextvars context is empty, so its ``Logger`` output is
    dropped from run.log. Guards against regressions where someone removes the
    wrap thinking plain pool submission already inherits."""
    from concurrent.futures import ThreadPoolExecutor

    log = tmp_path / "run.log"
    bind_run_log(log)

    seen: dict = {}

    def _probe():
        seen["file"] = current_run_log_file()
        Logger.action("agent_stream", "should-not-reach-runlog")

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_probe)  # NOT wrapped
        fut.result(timeout=5.0)

    assert seen["file"] is None
    assert "should-not-reach-runlog" not in log.read_text(encoding="utf-8")


def test_context_callable_concurrent_tasks_each_inherit_binding(tmp_path):
    """AU-8 + CPython constraint: multiple ``context_callable``-wrapped tasks
    submitted concurrently (``max_workers > 1``) each inherit the caller's
    binding — one fresh context copy PER task. A single shared ``Context``
    cannot be entered by two workers at once (CPython raises ``cannot enter
    context: ... already entered``), so this guards the per-task-copy invariant
    the ForkJoin ``pool.map`` relies on: build one wrapped callable per item,
    not one shared."""
    from concurrent.futures import ThreadPoolExecutor

    log = tmp_path / "run.log"
    bind_run_log(log)
    bind_op_name("MyOp")
    handle = current_run_log_file()

    seen: dict = {}

    def _probe(i):
        seen[i] = (current_run_log_file(), current_op_name())
        Logger.action("agent_stream", f"task{i}-line")

    n = 6
    wrapped = [log_capture.context_callable(_probe) for _ in range(n)]
    with ThreadPoolExecutor(max_workers=n) as pool:
        futs = [pool.submit(w, i) for w, i in zip(wrapped, range(n))]
        for f in futs:
            f.result(timeout=5.0)  # raises (e.g. already-entered) if invariant breaks

    assert len(seen) == n
    content = log.read_text(encoding="utf-8")
    for i in range(n):
        assert seen[i] == (handle, "MyOp"), f"task{i} lost the binding"
        assert f"task{i}-line" in content, f"task{i} Logger dropped from run.log"
