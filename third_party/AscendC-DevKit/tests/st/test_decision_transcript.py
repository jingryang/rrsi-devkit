"""Real-link system test: MCP decision tool reachability.

This is the regression guard for the bug where ``allowed_tools`` listed the
bare name ``resolve_ambiguity`` instead of the MCP-qualified name
``mcp__engine__resolve_ambiguity`` — which made the decision tool invisible to
the agent so it silently defaulted every unclear item instead of asking.

The whole point is that this test does NOT mock the SDK/CLI. It spawns a real
agent and asserts the engine MCP tool is actually callable end-to-end. With
``on_decision="abort"`` the handler writes ``pending_decision.json`` the moment
the tool is invoked, so the file's existence proves reachability.

Marked ``@pytest.mark.llm`` to declare a real-LLM runtime dependency: it runs
in the default full suite (which prechecks LLM) and under ``-m llm``, and is
excluded by the fast ``--quick`` lane.
"""

from __future__ import annotations

import json

import pytest

from ascendc_devkit.domain.exceptions import DecisionPendingError

from tests._llm_env import has_anthropic as _has_anthropic, load_settings_env

load_settings_env()


_FORCE_DECISION_PROMPT = (
    "这是一个通路验证测试。请直接调用 resolve_ambiguity 工具：\n"
    "question='测试：选择旋转模式'\n"
    "options=['选项A', '选项B', '选项C']"
)

# Real LLMs are non-deterministic: a single run may not obey the instruction to
# call the tool. Reachability is proven if the tool fires in ANY attempt; it is
# refuted only if it never fires across all attempts. This absorbs model jitter
# without weakening into a mock.
_MAX_ATTEMPTS = 3


def _try_trigger_decision(allowed_tools, agent_name, tmp_path_factory):
    """Spawn until the decision tool fires (DecisionPendingError) or attempts
    are exhausted. Returns (fired: bool, pending_data: dict | None, run_dir)."""
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend

    last_run = None
    for attempt in range(_MAX_ATTEMPTS):
        decision_ws = tmp_path_factory(attempt)
        decision_ws.mkdir(parents=True, exist_ok=True)
        last_run = decision_ws
        backend = SDKBackend(
            interactive=False,
            working_dir=decision_ws.parent,
            on_decision="abort",
            decision_workspace=decision_ws,
            allowed_tools=allowed_tools,
        )
        try:
            backend.spawn(agent_name, _FORCE_DECISION_PROMPT, {})
        except DecisionPendingError:
            pass
        pending = decision_ws / "pending_decision.json"
        if pending.exists():
            return True, json.loads(pending.read_text()), decision_ws
    return False, None, last_run


@pytest.mark.llm
class TestMcpDecisionReachable:
    """Prove mcp__engine__resolve_ambiguity is reachable via the real SDK/CLI."""

    def test_agent_can_invoke_resolve_ambiguity(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")

        # allowed_tools=None → requirement-analyst manifest governs (it whitelists
        # the full MCP name); this verifies the manifest-driven config is live.
        fired, data, run_dir = _try_trigger_decision(
            allowed_tools=None,
            agent_name="requirement-analyst",
            tmp_path_factory=lambda i: tmp_path / f"ws_{i}",
        )
        assert fired, (
            "resolve_ambiguity never invoked across "
            f"{_MAX_ATTEMPTS} attempts — MCP tool unreachable "
            "(check allowed_tools uses mcp__engine__resolve_ambiguity)"
        )
        assert data and data.get("options")

        # Task 1.2: the session transcript was persisted and captured the
        # tool_use for the decision tool (hard proof of real-link replay data).
        transcripts = sorted((run_dir / "agents").glob("requirement-analyst-*.jsonl"))
        assert transcripts, "no transcript jsonl written under agents/"
        body = transcripts[-1].read_text()
        assert body.strip(), "transcript is empty"
        assert "mcp__engine__resolve_ambiguity" in body

    def test_full_name_only_is_sufficient(self, tmp_path):
        """The MCP-qualified name alone must make the tool reachable.

        This pins down Task 1.1: it proves the bare ``resolve_ambiguity`` is
        redundant, so the default allowed_tools can collapse to the full name
        only. If this passes, the bare alias can be safely removed.

        Uses ``ascendc-coder`` whose manifest declares no allowed_tools, so the
        constructor list (full name only) actually takes effect — unlike
        requirement-analyst whose manifest would override it.
        """
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")

        from ascendc_devkit.capabilities.skill.loader import load_agent_manifest
        # Guard the assumption: if this manifest ever gains allowed_tools the
        # constructor list would be ignored and the test would be vacuous.
        assert not load_agent_manifest("ascendc-coder").allowed_tools, (
            "ascendc-coder manifest now declares allowed_tools; pick another "
            "agent without one for this test"
        )

        fired, _, _ = _try_trigger_decision(
            allowed_tools=[
                "Read", "Write", "Edit", "Bash", "Glob", "Grep",
                "mcp__engine__resolve_ambiguity",  # full name only, no bare alias
            ],
            agent_name="ascendc-coder",
            tmp_path_factory=lambda i: tmp_path / f"ws_{i}",
        )
        assert fired, (
            f"full name alone did not reach the tool in {_MAX_ATTEMPTS} "
            "attempts — keep the bare alias"
        )
