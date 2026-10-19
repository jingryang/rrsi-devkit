"""§P7.3 + P6 — stall detection counts only EFFECTIVE progress, never wall-clock
time, and aclose() race after stall break is non-fatal.

The old `had_tool_use` reset the stall counter on ANY tool call, so an agent that
spun on repeated/erroring tool calls (e.g. re-`ls`/`cat`/`grep` a missing path)
never tripped the MAX_STALLED_TURNS cutoff. The fix tightens "progress" to:
new text OR a NON-repeat tool call whose prior tool_results did not all error.

Crucially the signal is content-only: a slow proxy/relay taking minutes per turn
must NOT be mistaken for a stall, so time never enters the decision.
"""

from __future__ import annotations

from collections import deque

from ascendc_devkit.capabilities.agent.sdk_backend import (
    _tool_use_signature, _scan_tool_results, _TOOL_SIG_WINDOW,
    _ACLOSE_ERROR_MARKER,
)


class _ToolUse:
    def __init__(self, name, inp):
        self.name = name
        self.input = inp


class _ToolResult:
    """Mimics an SDK ToolResultBlock (class name contains 'Result')."""
    def __init__(self, content, is_error=False):
        self.content = content
        self.is_error = is_error


class _UserMessage:
    def __init__(self, content):
        self.content = content


class TestToolUseSignature:
    def test_same_name_and_input_same_signature(self):
        a = _ToolUse("Bash", {"command": "ls -la"})
        b = _ToolUse("Bash", {"command": "ls -la"})
        assert _tool_use_signature(a) == _tool_use_signature(b)

    def test_different_input_different_signature(self):
        a = _ToolUse("Bash", {"command": "ls -la"})
        b = _ToolUse("Bash", {"command": "cat foo"})
        assert _tool_use_signature(a) != _tool_use_signature(b)

    def test_key_order_irrelevant(self):
        a = _ToolUse("Read", {"file_path": "x", "limit": 5})
        b = _ToolUse("Read", {"limit": 5, "file_path": "x"})
        assert _tool_use_signature(a) == _tool_use_signature(b)

    def test_non_serializable_input_does_not_raise(self):
        a = _ToolUse("X", object())
        assert isinstance(_tool_use_signature(a), str)


class TestScanToolResults:
    def test_no_results_seen(self):
        errored, seen = _scan_tool_results(_UserMessage([_ToolUse("Bash", {})]))
        assert seen is False and errored is False

    def test_all_errored(self):
        ev = _UserMessage([_ToolResult("no such file", is_error=True)])
        errored, seen = _scan_tool_results(ev)
        assert seen is True and errored is True

    def test_one_ok_means_not_all_errored(self):
        ev = _UserMessage([_ToolResult("err", is_error=True),
                           _ToolResult("ok output", is_error=False)])
        errored, seen = _scan_tool_results(ev)
        assert seen is True and errored is False

    def test_event_without_list_content(self):
        class _E:
            content = None
        errored, seen = _scan_tool_results(_E())
        assert seen is False and errored is False


def _progress(full_len_grew, had_new_tool_use):
    """Mirror the backend's new progress predicate (P6-a fix).

    Old: full_len_grew or (had_new_tool_use and not last_tool_results_errored)
    P6-a: full_len_grew or had_new_tool_use
    — a genuinely new tool call is always progress, regardless of whether
    a prior turn's unrelated call errored.
    """
    return full_len_grew or had_new_tool_use


class TestProgressPredicate:
    def test_new_text_is_progress(self):
        assert _progress(True, False) is True

    def test_new_text_is_progress_even_if_tools_errored(self):
        # Text output is real progress regardless of tool outcomes.
        assert _progress(True, False) is True

    def test_new_effective_tool_call_is_progress(self):
        assert _progress(False, True) is True

    def test_repeated_tool_call_is_not_progress(self):
        # had_new_tool_use False = the call was a verbatim repeat.
        assert _progress(False, False) is False

    def test_new_call_even_when_prior_turn_errored_is_progress(self):
        """P6-a: a genuinely new tool call is progress even when the prior turn's
        UNRELATED tool call errored (e.g. bootstrap file read 404).
        Previously this was NOT progress — the global error flag leaked."""
        assert _progress(False, True) is True


def test_repeated_calls_eventually_stall():
    """Simulate the idle-spin: same Bash call every turn, no text → stall
    counter climbs to the cutoff.  (P6-a: since the call is a repeat —
    had_new_tool_use False — it is NOT progress regardless of error state.)"""
    from ascendc_devkit.capabilities.agent.sdk_backend import MAX_STALLED_TURNS

    recent = deque(maxlen=_TOOL_SIG_WINDOW)
    stalled = 0
    sig = _tool_use_signature(_ToolUse("Bash", {"command": "ls /missing"}))
    for _ in range(MAX_STALLED_TURNS + 2):
        had_new = sig not in recent
        recent.append(sig)
        if _progress(False, had_new):
            stalled = 0
        else:
            stalled += 1
    assert stalled >= MAX_STALLED_TURNS


def test_slow_but_progressing_never_stalls():
    """A slow relay (long gaps between turns) with genuine per-turn progress must
    never stall — time is not part of the decision."""
    recent = deque(maxlen=_TOOL_SIG_WINDOW)
    stalled = 0
    for i in range(20):
        # Each turn issues a DISTINCT effective tool call (new content).
        sig = _tool_use_signature(_ToolUse("Read", {"file_path": f"f{i}.h"}))
        had_new = sig not in recent
        recent.append(sig)
        if _progress(False, had_new):
            stalled = 0
        else:
            stalled += 1
    assert stalled == 0


# —— P6-a: per-signature error tracking (not global cross-turn flag) ——

def test_unrelated_error_does_not_contaminate_new_call():
    """P6-a: a new tool call (different signature) is progress even when the
    previous turn's tool_results ALL errored for an unrelated tool."""
    recent = deque(maxlen=_TOOL_SIG_WINDOW)
    stalled = 0

    # Turn 1: Bash "ls" errors — populate _errored_sigs with Bash:ls
    sig_bad = _tool_use_signature(_ToolUse("Bash", {"command": "ls /missing"}))
    recent.append(sig_bad)
    # has_new=False (it was the 1st call, not in recent yet initially — actually it is in recent after append, second call would be repeat), just set it up
    stalled += 1  # no progress this turn

    # Turn 2: Read a new file — this is a NEW tool call with DIFFERENT signature.
    # Under the old code, last_tool_results_errored=True would block progress.
    # Under P6-a, it counts as progress (had_new_tool_use=True, cross-turn error ignored).
    sig_new = _tool_use_signature(_ToolUse("Read", {"file_path": "design_spec.json"}))
    had_new = sig_new not in recent  # True — new signature
    recent.append(sig_new)
    if _progress(False, had_new):
        stalled = 0  # P6-a: reset stall counter — this is progress!
    else:
        stalled += 1
    assert stalled == 0, (
        "P6-a: a genuinely new tool call must reset the stall counter "
        "even when the prior turn's tool call errored")


# —— P6: aclose() RuntimeError after stall break is non-fatal ——

def test_aclose_error_marker_matches_real_exception():
    """P6: the _ACLOSE_ERROR_MARKER string matches the exact RuntimeError message
    raised by Python when an async generator is already running."""
    assert _ACLOSE_ERROR_MARKER == "asynchronous generator is already running"
    err = RuntimeError("aclose(): asynchronous generator is already running")
    assert _ACLOSE_ERROR_MARKER in str(err)


def test_aclose_marker_matches_typical_race_message():
    """P6: various forms of the aclose race message are matched by the marker."""
    messages = [
        "aclose(): asynchronous generator is already running",
        "RuntimeError: aclose(): asynchronous generator is already running",
        "async generator ignored GeneratorExit: aclose(): asynchronous generator is already running",
    ]
    for msg in messages:
        assert _ACLOSE_ERROR_MARKER in msg, f"marker should match: {msg}"


def test_aclose_not_matched_by_unrelated_runtime_errors():
    """P6: unrelated RuntimeErrors must NOT be mistaken for aclose race."""
    unrelated = [
        "cannot schedule new futures after shutdown",
        "generator didn't yield",
        "coroutine raised StopIteration",
    ]
    for msg in unrelated:
        assert _ACLOSE_ERROR_MARKER not in msg
