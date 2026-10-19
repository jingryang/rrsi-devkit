"""ST (heavy_llm, §3.9) — cross-run session resume via sidecar (提案#1): real LLM.

UT covers the WIRING deterministically (StubBackend/mock):
  - tests/ut/capabilities/test_session_resume.py — sidecar path resolution,
    write-at-capture, survive-crash, clear-on-clean, resume-init options,
    session-gone degrade.
  - tests/ut/orchestration/test_session_resume.py — codegen.actions sidecar-read
    fork → SpawnAgent(resume_session_id=...), runner pass-through, corrupt-sidecar
    fallback.

This ST guards the REAL link the UTs structurally cannot (§3.9/§3.10): a real
claude_agent_sdk session, once captured by ``_spawn``, can actually be RESUMED
across ``_spawn`` calls (the SDK accepts ``resume=<sid>`` and the session is
still valid — not gone, not degraded), and a resume into a session that cannot
exist really hits the gone path and degrades to a fresh spawn. Both need a real
LLM round-trip; mocking ``query()`` would void the proof.

heavy_llm (§3.11): real LLM full flow, minutes + tokens. NOT in default pytest
— excluded by ``-m "not heavy_llm"``. Run only on explicit user decision.

Why _spawn-level (not dispatch_single_stage): the resume mechanism lives in
``SDKBackend._spawn``. Driving it directly isolates the real-link property
(session capture + resume + degrade) from the much heavier full codegen stage,
bounding token cost while still exercising the real SDK session lifecycle. The
sidecar-on-disk → ``codegen.actions`` fork is UT-covered, so this ST does not
re-derive it; it validates the SDK session behavior that mocks cannot.

Observability: ``Logger`` prints to stderr, captured via ``capsys``. The resume
path logs ``agent_resume``; the degrade path logs ``degrading to fresh spawn``.
"""
from __future__ import annotations

import asyncio

import pytest

from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend


_AGENT = "resume-e2e"
# A UUID-shaped value that cannot be a live session — drives the gone path.
_BOGUS_SID = "00000000-0000-0000-0000-000000000000"
# These tests use a "do not use any tools, just reply" prompt to bound token
# cost, so the agent produces NO product files. The backend correctly reports
# status "ok" + empty artifacts for such a clean finish (agent ran, model replied, no
# files) — that is NOT a failure for these mechanism tests. The only status we
# reject is ``fatal`` (the spawn itself broke). See sdk_backend.py:941.
_COMPLETED = ("ok", "partial")


class _CapturingBackend(SDKBackend):
    """SDKBackend that records the real session_id at capture time.

    NOT a mock: ``_spawn`` runs 100 % against the real claude_agent_sdk. We only
    observe the session_id the backend already persists to the sidecar, so the
    test can feed it to a resume ``_spawn`` — exactly the value the on-disk
    sidecar holds in a real crashed run (the on-disk read path is UT-covered).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.captured_session_id: str | None = None

    def _write_session_sidecar(self, agent_name, branch_label, session_id,
                               stage_name: str = "", resume_fails: int = 0):
        if session_id:
            self.captured_session_id = session_id
        return super()._write_session_sidecar(agent_name, branch_label, session_id,
                                              stage_name=stage_name,
                                              resume_fails=resume_fails)


def _backend(tmp_path) -> _CapturingBackend:
    return _CapturingBackend(
        interactive=False,
        working_dir=str(tmp_path),
        on_decision="default",
        decision_workspace=str(tmp_path),
    )


def _spawn(backend, tmp_path, *, resume_session_id=None, prompt=None,
           resume_prompt=None):
    """Run one real ``_spawn``. Prompts forbid tool use so the model just replies
    — keeps the turn/token cost minimal while still exercising a real session."""
    p = prompt or "Do not use any tools. Reply with exactly: ACK"
    return asyncio.run(backend._spawn(
        agent_name=_AGENT,
        prompt=p,
        context={},
        skills=None,
        working_dir=str(tmp_path),
        resume_session_id=resume_session_id,
        resume_prompt=resume_prompt,
    ))


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestCrossRunSessionResumeE2E:
    """Real LLM: a captured claude_agent_sdk session resumes across _spawn calls."""

    def test_fresh_spawn_captures_real_session_id(self, tmp_path):
        """A fresh real ``_spawn`` captures a non-empty session_id (the value the
        sidecar persists in a real run). This is the capture half of 提案#1."""
        backend = _backend(tmp_path)
        result = _spawn(backend, tmp_path)
        assert result.status in _COMPLETED, (
            f"fresh spawn failed: status={result.status} err={result.error_type}")
        assert backend.captured_session_id, (
            "fresh spawn must capture a real session_id at the sidecar write")

    def test_captured_session_resumes_without_degrade(self, tmp_path, capsys):
        """Core real-link guarantee (§3.9): a session_id captured by a fresh
        ``_spawn``, fed back as ``resume_session_id``, is RESUMED by the SDK —
        the session is still valid (no session-gone degrade) and the resumed
        turn completes. Proves cross-``_spawn`` session reuse against the real SDK.

        Failure means either (a) the resume wiring dropped the id (no
        ``agent_resume`` log), or (b) real sessions are not resumable across
        ``_spawn`` calls within seconds (``degrading to fresh spawn`` logged) —
        both are exactly the regressions this test exists to catch.

        Note: the backend uses ``_RESUME_PROMPT`` on resume (our prompt is
        ignored by design — the session carries its own context), so we assert
        on the resume *mechanism*, not on model recall.
        """
        backend = _backend(tmp_path)
        # 1) fresh spawn captures a real session_id
        _spawn(backend, tmp_path)
        sid = backend.captured_session_id
        assert sid, "fresh spawn did not capture a session_id"

        # 2) resume that session — _RESUME_PROMPT is used (our prompt ignored)
        result = _spawn(backend, tmp_path, resume_session_id=sid,
                        prompt="Do not use any tools. Reply with exactly: DONE")
        err = capsys.readouterr().err

        assert "agent_resume" in err, (
            "resume path was not taken — resume_session_id not delivered to backend")
        assert "degrading to fresh spawn" not in err, (
            "resumed session was treated as gone/expired — real session not "
            "resumable across _spawn within seconds (TTL too short?)")
        assert result.status in _COMPLETED, (
            f"resumed spawn failed: status={result.status} err={result.error_type}")

    def test_bogus_session_id_degrades_to_fresh(self, tmp_path, capsys):
        """A resume into a session that cannot exist hits the gone path and
        degrades to a fresh spawn (real SDK reject → real fresh retry). Proves
        the degrade half of 提案#1 against the real SDK, not just the marker set.

        If this fails on the ``degrading to fresh spawn`` assertion, the real
        SDK's wording for an invalid session does not match
        ``_SESSION_GONE_MARKERS`` (sdk_backend.py) and the markers need widening
        — that is actionable signal, not a flaky test.
        """
        backend = _backend(tmp_path)
        result = _spawn(
            backend, tmp_path, resume_session_id=_BOGUS_SID,
            prompt="Do not use any tools. Reply with exactly: HELLO")
        err = capsys.readouterr().err

        # Robust floor: a bogus resume_session_id must not fatal the spawn.
        assert result.status in _COMPLETED, (
            f"bogus resume_session_id broke the spawn: status={result.status} "
            f"err={result.error_type}")
        # Real-link claim: the SDK reports the bogus id as gone → degrade fires.
        assert "degrading to fresh spawn" in err, (
            "bogus session_id did not trigger session-gone degrade — real SDK "
            "wording for an invalid session differs from _SESSION_GONE_MARKERS")


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestExplicitResumePromptE2E:
    """step-100 (§3.9, review M2): the EXPLICIT resume pathway codegen now uses —
    ``SpawnAgent(resume_session_id=..., resume_prompt=...)`` — against the real
    SDK. The classes above resume via the backend's built-in ``_RESUME_PROMPT``
    (sidecar silent-cut recovery); step-100's feedback redispatch passes a
    per-failure ``resume_prompt`` that MUST become the first message of the
    resumed turn (``active_prompt = resume_prompt or _RESUME_PROMPT``,
    sdk_backend.py). If the wiring dropped it, the coder would resume on a bare
    "继续" with no failure feedback — exactly the regression this guards.

    Real-link assertions:
    - same session: ``result.session_id == sid`` (resume reuses the id — the
      code comment at the sidecar flush notes it is stable within a spawn);
    - first-message delivery proven BEHAVIORALLY: the marker string is carried
      ONLY by resume_prompt (absent from the fresh prompt and from
      ``_RESUME_PROMPT``), and the model is told to echo it — marker in the
      transcript proves resume_prompt reached the wire of the resumed turn.
    """

    def test_resume_prompt_is_first_message_of_resumed_session(
            self, tmp_path, capsys):
        backend = _backend(tmp_path)
        # 1) fresh spawn establishes a real session and captures its id.
        r1 = _spawn(backend, tmp_path,
                    prompt="Do not use any tools. Reply with exactly: ACK")
        assert r1.status in _COMPLETED, (
            f"fresh spawn failed: status={r1.status} err={r1.error_type}")
        sid = backend.captured_session_id or r1.session_id
        assert sid, "fresh spawn did not capture a session_id"

        # 2) resume with an EXPLICIT resume_prompt carrying a unique marker.
        marker = "RESUME-PROMPT-DELIVERED-7f3d"
        result = _spawn(
            backend, tmp_path,
            resume_session_id=sid,
            prompt="Do not use any tools. Reply with exactly: FRESH-IGNORED",
            resume_prompt=(
                "Do not use any tools. Reply with exactly the token "
                f"{marker} and nothing else."),
        )
        err = capsys.readouterr().err

        assert "degrading to fresh spawn" not in err, (
            "explicit resume degraded to fresh — session not resumable")
        assert result.status in _COMPLETED, (
            f"explicit-resume spawn failed: status={result.status} "
            f"err={result.error_type}")
        assert result.session_id == sid, (
            f"resume ran in session {result.session_id!r}, expected {sid!r} "
            "— explicit resume must CONTINUE the prior session, not open one")
        # First-message delivery: marker appears in the resumed turn's
        # transcript (assistant echo) — unreachable if resume_prompt was
        # dropped (the built-in _RESUME_PROMPT does not contain it).
        assert result.transcript and result.transcript.exists(), (
            "no transcript persisted — cannot prove resume_prompt delivery")
        body = result.transcript.read_text(encoding="utf-8")
        assert marker in body, (
            "resume_prompt marker absent from the resumed turn's transcript — "
            "resume_prompt was not delivered as the first message (fell back "
            "to the built-in _RESUME_PROMPT?)")


# —— opencode dual-backend (断链②, step-68) ——————————————————————————————
# The SAME cross-run resume property, driven through a REAL ``opencode serve``
# subprocess (claude above drives claude_agent_sdk in-process). Task 7's probe
# confirmed opencode sessions survive a serve restart; these STs lock that
# end-to-end through OpenCodeBackend — the UT fakes the HTTP transport and so
# cannot prove the real cross-serve session link (断链②).

from ascendc_devkit.capabilities.agent.opencode_backend import OpenCodeBackend
from tests.st._dual_backend import REPO, load_settings_env, require_live_opencode

load_settings_env()


class _CapturingOpenCodeBackend(OpenCodeBackend):
    """OpenCodeBackend that records the real session_id at sidecar write.

    NOT a mock: spawn runs 100% against a real ``opencode serve`` + LLM; we only
    observe the session_id the backend already persists to the sidecar, so the
    test can feed it to a resume spawn — exactly the value the on-disk sidecar
    holds in a real crashed run."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.captured_session_id: str | None = None

    def _write_session_sidecar(self, agent_name, branch_label, session_id,
                               stage_name: str = "", resume_fails: int = 0):
        if session_id:
            self.captured_session_id = session_id
        return super()._write_session_sidecar(agent_name, branch_label, session_id,
                                              stage_name=stage_name,
                                              resume_fails=resume_fails)


def _opencode_backend(ws):
    return _CapturingOpenCodeBackend(
        interactive=False,
        working_dir=str(ws.parent),
        on_decision="default",
        decision_workspace=str(ws),
        project_config_path=str(REPO / "opencode.json"),
        serve_startup_timeout=90.0,
        message_timeout=180.0,
    )


def _opencode_spawn(backend, tmp_path, *, resume_session_id=None, prompt=None,
                    resume_prompt=None):
    """One real opencode spawn. Forbids tool use so the model just replies —
    bounds turn/token cost while still exercising a real session + serve."""
    p = prompt or "Do not use any tools. Reply with exactly: ACK"
    return backend.spawn(
        agent_name=_AGENT, prompt=p, context={},
        working_dir=str(tmp_path),
        resume_session_id=resume_session_id,
        resume_prompt=resume_prompt,
    )


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestOpenCodeCrossRunResumeE2E:
    """Real LLM (opencode serve): 断链② — a session captured by one spawn is
    REUSED (not freshly POSTed) by a resume spawn across serve lifecycles."""

    def test_fresh_opencode_spawn_captures_session_id(self, tmp_path):
        """Capture half: a fresh real opencode spawn captures a non-empty
        session_id (the value the sidecar persists). Mirrors the claude capture
        test on the opencode transport."""
        require_live_opencode()
        ws = tmp_path / "ws"
        ws.mkdir()
        backend = _opencode_backend(ws)
        result = _opencode_spawn(backend, tmp_path)
        assert result.status in _COMPLETED, (
            f"fresh opencode spawn failed: status={result.status} "
            f"err={result.error_type} "
            f"reason={result.metrics.get('failure_reason')}")
        assert backend.captured_session_id, (
            "fresh opencode spawn must capture a real session_id at the "
            "sidecar write")

    def test_opencode_resume_reuses_prior_session(self, tmp_path):
        """断链② core real-link guard (§3.9): spawn1 captures session S on a
        real serve1; spawn2 starts a NEW serve2 with resume_session_id=S and
        reuses it (no fresh POST /session — that wiring is UT-covered).
        opencode sessions persist in the operator's data dir across serve
        instances (task 7 probe), so serve2 accepts S. If cross-serve
        persistence were broken, spawn2 would fatal on the message POST — so
        completion is the real-link proof that mocks cannot establish."""
        require_live_opencode()
        ws = tmp_path / "ws"
        ws.mkdir()
        backend = _opencode_backend(ws)
        # 1) fresh spawn captures a real session_id on serve1.
        _opencode_spawn(backend, tmp_path)
        sid = backend.captured_session_id
        assert sid, "fresh opencode spawn did not capture a session_id"
        # 2) resume that session on a NEW serve2 (spawn2 starts its own serve).
        result = _opencode_spawn(backend, tmp_path, resume_session_id=sid)
        assert result.status in _COMPLETED, (
            f"opencode resume of a prior session across a new serve fatal'd — "
            f"cross-serve session reuse broken (断链②): status={result.status} "
            f"err={result.error_type} "
            f"reason={result.metrics.get('failure_reason')}")

    def test_opencode_bogus_session_degrades_to_fresh(self, tmp_path, capsys):
        """M1 (step-68 review): the gone-degrade half of opencode cross-run
        resume, against a REAL serve. A resume_session_id that opencode does not
        hold (stale/cross-device sidecar, or a purged real session) returns HTTP
        404 NotFoundError "Session not found" (probe-confirmed — see
        ``_OPENCODE_SESSION_GONE_MARKERS``; opencode's shape is HTTP/JSON, NOT
        claude's SDK exception text). The spawn must self-heal: degrade to a
        fresh spawn on the same serve instead of fataling — parity with claude's
        ``_SESSION_GONE_MARKERS`` degrade (test_bogus_session_id_degrades_to_fresh).

        The bogus id uses the real ``ses_`` prefix opencode issues (a sidecar
        only ever holds such an id); an all-zeros UUID would 500 with a generic
        UnknownError (malformed-id path, NOT the resume scenario), so it is
        deliberately avoided here. Failing the degrade-log assertion means the
        real opencode wording drifted from the marker set — actionable signal."""
        require_live_opencode()
        ws = tmp_path / "ws"
        ws.mkdir()
        backend = _opencode_backend(ws)
        # A realistic "purged real session" id: ses_ prefix + payload that
        # cannot exist on this serve's fresh data dir.
        bogus = "ses_PURGED0000000000STEP68M1PROBE"
        result = _opencode_spawn(backend, tmp_path, resume_session_id=bogus,
                                 prompt="Do not use any tools. Reply with exactly: ACK")
        err = capsys.readouterr().err

        # Robust floor: a bogus resume must not fatal the spawn.
        assert result.status in _COMPLETED, (
            f"bogus opencode resume_session_id broke the spawn: "
            f"status={result.status} err={result.error_type} "
            f"reason={result.metrics.get('failure_reason')}")
        # Real-link claim: opencode reported the id as gone/not-found → degrade.
        assert "degrading to fresh spawn" in err, (
            "bogus opencode session_id did not trigger session-gone degrade — "
            "real opencode wording for an invalid session differs from "
            "_OPENCODE_SESSION_GONE_MARKERS (probe said HTTP 404 NotFoundError "
            "'Session not found'); markers need widening")

    def test_opencode_explicit_resume_prompt_delivered(self, tmp_path, capsys):
        """step-100 (§3.9, review M2) opencode parity: resume with an EXPLICIT
        ``resume_prompt`` — it must become the first message of the resumed
        session (``first_prompt = (resume_prompt or _RESUME_PROMPT)``,
        opencode_backend.py), continuing the SAME session. Marker-echo proof
        mirrors the claude test: the marker exists only in resume_prompt, so
        its appearance in the resumed turn's transcript proves delivery. If the
        transcript assert fires while claude's passes, opencode's per-spawn
        transcript has a real observability gap — actionable signal, not a
        flaky test."""
        require_live_opencode()
        ws = tmp_path / "ws"
        ws.mkdir()
        backend = _opencode_backend(ws)
        # 1) fresh spawn captures a real session_id on serve1.
        _opencode_spawn(backend, tmp_path)
        sid = backend.captured_session_id
        assert sid, "fresh opencode spawn did not capture a session_id"
        # 2) explicit resume on a new serve2: same session + marker delivered.
        marker = "OC-RESUME-PROMPT-DELIVERED-7f3d"
        result = _opencode_spawn(
            backend, tmp_path,
            resume_session_id=sid,
            prompt="Do not use any tools. Reply with exactly: FRESH-IGNORED",
            resume_prompt=(
                "Do not use any tools. Reply with exactly the token "
                f"{marker} and nothing else."),
        )
        err = capsys.readouterr().err
        assert "degrading to fresh spawn" not in err
        assert result.status in _COMPLETED, (
            f"opencode explicit-resume spawn failed: status={result.status} "
            f"err={result.error_type} "
            f"reason={result.metrics.get('failure_reason')}")
        assert result.session_id == sid, (
            f"resume ran in session {result.session_id!r}, expected {sid!r} "
            "— explicit resume must CONTINUE the prior session, not open one")
        assert result.transcript and result.transcript.exists(), (
            "no transcript persisted — cannot prove resume_prompt delivery")
        body = result.transcript.read_text(encoding="utf-8")
        assert marker in body, (
            "resume_prompt marker absent from the resumed turn's transcript — "
            "resume_prompt was not delivered as the first message (fell back "
            "to the built-in _RESUME_PROMPT?)")
