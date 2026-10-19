"""AU-6 regression guard — opencode real-time turn info lands in per-op run.log.

Proves LIVE against the REAL opencode SSE stream (not a hand-crafted fixture —
see the pure UT ``test_subscribe_sse_thread_writes_agent_stream_into_bound_run_log``
in ``tests/ut/capabilities/test_opencode_backend.py``, which mocks
``urllib.request.urlopen`` and therefore can't catch a mismatch between the real
opencode SSE frame shape and that fixture) that design B's streaming
``agent_stream`` lines actually reach the per-op ``run.log``: the SSE daemon
reader thread (``OpenCodeBackend._subscribe_sse``) must inherit the calling
thread's ``run.log`` binding via ``infra.log_capture.spawn_context_thread``
(AU-6 fix, ``docs/plan/opencode-batch-concurrency/04-audit-followups.md``).
Before this fix the daemon thread saw no binding (``threading.local`` doesn't
propagate to a plain child thread) and ``agent_stream`` lines landed in
console/batch log only — this test is the real-environment backstop for that
regression (§3.9: real SDK/Agent behavior links need an ``@pytest.mark.llm``
case, not just mocked UT).

Marked @pytest.mark.llm (single-spawn, explicit one-turn instruction, seconds
scale — NOT heavy_llm: no open-ended multi-turn pipeline). Bounded by
``message_timeout=180s`` (``make_backend``).
"""

from __future__ import annotations

import pytest

from tests.st._dual_backend import load_settings_env, make_backend, require_live_opencode

load_settings_env()

_MAX_ATTEMPTS = 3
_PROMPT = "回复一句简短的话确认收到即可，不需要使用任何工具，直接结束对话。"


@pytest.mark.llm
def test_real_opencode_spawn_writes_agent_stream_turn_lines_into_run_log(tmp_path):
    """AU-6 regression guard: a real opencode spawn's SSE-streamed
    ``agent_stream`` (turn N, ...) lines must land in the run.log that was
    bound in the CALLING thread before spawn() started — proving the daemon
    reader thread inherited that binding against a real opencode SSE stream,
    not console/batch log only."""
    require_live_opencode()

    from ascendc_devkit.infra.log_capture import bind_run_log, unbind_run_log

    log_path = tmp_path / "run.log"
    bind_run_log(log_path)
    try:
        last_status = None
        for attempt in range(_MAX_ATTEMPTS):
            ws = tmp_path / f"ws_{attempt}"
            ws.mkdir(parents=True, exist_ok=True)
            backend = make_backend("opencode", ws)
            result = backend.spawn(
                "ascendc-design-generator", _PROMPT, {},
                skills=[], primary_skill=None, working_dir=ws,
                stage_name="run_log_turn_probe", branch_label=f"A{attempt}",
            )
            last_status = result.status
            content = log_path.read_text(encoding="utf-8")
            if "agent_stream" in content and "turn " in content:
                return

        pytest.fail(
            f"agent_stream turn lines never appeared in the bound run.log across "
            f"{_MAX_ATTEMPTS} attempts (last status={last_status}) — AU-6 "
            "regression: check OpenCodeBackend._subscribe_sse still starts its "
            "daemon reader via infra.log_capture.spawn_context_thread (a plain "
            "threading.Thread would not inherit the run.log binding).")
    finally:
        unbind_run_log()


@pytest.mark.llm
def test_real_opencode_forkjoin_branches_agent_stream_into_run_log(tmp_path):
    """AU-8 regression guard: two REAL opencode spawns run CONCURRENTLY in a
    ``ThreadPoolExecutor`` (the ``_execute_forkjoin`` dispatch model) must BOTH
    land their SSE-streamed ``agent_stream`` lines in the run.log bound in the
    SUBMITTING thread — proving each pool worker inherited that binding via
    ``infra.log_capture.context_callable`` (AU-8 fix,
    ``docs/plan/opencode-batch-concurrency/04-audit-followups.md``).

    A ``ThreadPoolExecutor`` worker starts with an EMPTY ``contextvars``
    context: without ``context_callable`` wrapping each branch, the worker's
    ``current_run_log_file()`` returns ``None`` and ``agent_stream`` lands in
    console/batch log only — the AU-8 defect (ForkJoin branches invisible in
    per-op run.log for up to hours). The sibling single-spawn guard above
    (AU-6) cannot catch this — it never crosses a pool boundary, so it stays
    green even if ``_execute_forkjoin`` regressed to a bare ``pool.map``.

    Marked @pytest.mark.llm (two concurrent one-turn spawns, seconds scale — NOT
    heavy_llm: no open-ended multi-turn pipeline). This is the §3.9 real-link
    backstop; the pure-UT pool-boundary invariant lives in
    ``tests/ut/infra/test_log_capture.py`` +
    ``tests/ut/orchestration/test_forkjoin.py`` (mocked, can't catch a real
    opencode SSE-frame mismatch). Bounded by ``message_timeout=180s``.
    """
    require_live_opencode()

    from concurrent.futures import ThreadPoolExecutor

    from ascendc_devkit.infra.log_capture import (
        bind_run_log, context_callable, unbind_run_log,
    )

    log_path = tmp_path / "run.log"
    bind_run_log(log_path)
    try:
        def _spawn(branch: str):
            ws = tmp_path / f"ws_{branch}"
            ws.mkdir(parents=True, exist_ok=True)
            backend = make_backend("opencode", ws)
            return backend.spawn(
                "ascendc-design-generator", _PROMPT, {},
                skills=[], primary_skill=None, working_dir=ws,
                stage_name="run_log_forkjoin_probe", branch_label=branch,
            )

        last_statuses = None
        for attempt in range(_MAX_ATTEMPTS):
            # Mirror graph_executor._execute_forkjoin EXACTLY: one fresh
            # context_callable per branch — a single Context cannot be entered
            # by two workers at once (CPython RuntimeError; see
            # context_callable docstring), so per-task copies, not one shared.
            branches = [f"AU8T1_{attempt}", f"AU8T2_{attempt}"]
            wrapped = [context_callable(_spawn) for _ in branches]
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(
                    lambda fn, b: fn(b), wrapped, branches))
            last_statuses = [r.status if r else None for r in results]

            content = log_path.read_text(encoding="utf-8")
            if ("agent_stream" in content
                    and branches[0] in content and branches[1] in content):
                return

        pytest.fail(
            f"both branches' agent_stream lines never appeared together in the "
            f"bound run.log across {_MAX_ATTEMPTS} attempts (last statuses="
            f"{last_statuses}) — AU-8 regression: check "
            "graph_executor._execute_forkjoin still wraps each branch via "
            "infra.log_capture.context_callable (a bare pool.map(_run, ...) "
            "runs branches in workers with an empty contextvars context and "
            "drops run.log — the per-op run.log would then show a long silent "
            "gap across the whole ForkJoin, exactly the production symptom).")
    finally:
        unbind_run_log()
