"""Real-link system test: design skill methodology is injected (step-8 §P1/§P9 hard proof).

This is THE acceptance guard for §P1's real goal: the design substage's methodology
(written in SKILL.md) must actually enter the design agent's context end-to-end.

§P9 discovery (2026-06-16): a session exposes a flat skill as a SLASH
COMMAND (``/<skill>`` bare name), NOT a model-invokable ``Skill`` tool — the model
has no Skill tool to call. The original assertion (``"tool_name": "Skill"``) was
therefore a wrong signal and the test was xfail.

Decision §P9 plan 2 (adopted): the orchestration makes the spawn's FIRST message
begin with ``/<skill>`` so the session expands it and injects SKILL.md into
the session. This test now asserts the CORRECT signal: the persisted transcript shows
the agent operating under the skill's methodology (terms that exist ONLY in the
SKILL.md, never in the prompt) — proving the slash trigger injected it.

Like test_decision_transcript, this does NOT mock the SDK: it builds the prompt via
the real substage (so the leading slash trigger is exactly what production sends), spawns
a real agent against the real flat skill tree, then inspects the transcript.
Reachability is proven if the methodology shows up in ANY attempt across the retry budget
(absorbs real-LLM jitter without weakening into a mock).

Marked @pytest.mark.llm: runs in the full suite (LLM prechecked) and under -m llm.
"""

from __future__ import annotations

import pytest

from tests._llm_env import has_anthropic as _has_anthropic, load_settings_env

load_settings_env()


_ASSIGNED_SKILL = "ascendc-op-tiling"

# Terms that appear ONLY in ascendc-op-tiling/SKILL.md (the merged facade skill),
# never in the prompt the substage builds. If any shows up in the transcript, the
# methodology was injected by the leading /ascendc-op-tiling slash command
# (§P9 plan 2) — the agent could not have produced these from the bare prompt.
_SKILL_METHODOLOGY_MARKERS = (
    "编排门面",     # the facade's self-description (调度四个子 skill)
    "串行调度",     # the facade's orchestration model
    "tiling_current_template.json",  # the facade's per-segment relay file
    "跨段一致性",   # the facade's cross-segment consistency invariant
)

_MAX_ATTEMPTS = 3


def _build_substage_prompt() -> str:
    """Return the production TilingStage prompt body and assert it carries
    its methodology skill on SpawnAgent.primary_skill (D2 — delivery is rendered
    at the backend boundary, not prepended into the prompt by the stage)."""
    from ascendc_devkit.orchestration.kernel.state import State
    from ascendc_devkit.orchestration.kernel.action import SpawnAgent
    from ascendc_devkit.orchestration.stages.design_substages import TilingStage

    state = State.empty().with_updates(
        op_name="rotary_position_embedding",
        template_division={"templates": [{"name": "T1_Half"}]})
    stage = TilingStage(template={"name": "T1_Half"})
    spawn = next(a for a in stage.actions(state, 1) if isinstance(a, SpawnAgent))
    # Guard: production carries the skill on primary_skill (D2); the backend
    # renders /<skill> at the boundary (render_skill_injection).
    assert spawn.primary_skill == _ASSIGNED_SKILL
    return spawn.prompt


@pytest.mark.llm
class TestDesignSkillInjection:
    """Prove the assigned stage-design skill's methodology reaches a design agent.

    D2 closure: the methodology arrives via the backend rendering primary_skill
    as the leading slash command in the first message (claude expands it — this
    CLI has no Skill tool_use). The hard signal is that the transcript contains
    SKILL.md-only terms the prompt never supplied.
    """

    def _spawn_until_methodology_injected(self, tmp_path):
        from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend

        # Production guard: the stage carries primary_skill (asserted in helper).
        _build_substage_prompt()
        # Pathway-test body (no manual slash): pass primary_skill and let the
        # REAL backend render the injection (render_skill_injection) — this is
        # what exercises the D2 delivery path end-to-end with a live LLM.
        prompt = (
            "这是一个通路验证测试。请直接说明：你已经加载了 tiling split 的方法论，"
            "并输出该方法论中的核心概念/术语名称（用逗号分隔列出）。"
            "不需要做实际的 tiling 分析，不需要读写文件。简短回答即可。"
        )
        for attempt in range(_MAX_ATTEMPTS):
            ws = tmp_path / f"ws_{attempt}"
            ws.mkdir(parents=True, exist_ok=True)
            backend = SDKBackend(
                interactive=False,
                working_dir=ws.parent,
                on_decision="default",
                decision_workspace=ws,
            )
            backend.spawn(
                "ascendc-design-generator", prompt, {},
                skills=[_ASSIGNED_SKILL],
                primary_skill=_ASSIGNED_SKILL,
                working_dir=ws,
                stage_name="tiling",
                branch_label="T1_Half",
            )
            transcripts = sorted((ws / "agents").glob("*.jsonl"))
            for t in transcripts:
                body = t.read_text()
                hit = next((m for m in _SKILL_METHODOLOGY_MARKERS if m in body), None)
                if hit:
                    return True, t, hit
        return False, None, None

    def test_skill_methodology_enters_agent_context(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")

        injected, transcript, marker = self._spawn_until_methodology_injected(tmp_path)
        assert injected, (
            "no SKILL.md-only methodology term appeared in the transcript across "
            f"{_MAX_ATTEMPTS} attempts — the backend did not inject the skill "
            "(D2 regression: check primary_skill is set on the spawn, the backend "
            "renders /<skill>, and the flat skill tree is discoverable)"
        )
        # The transcript naming carries the branch label (§P2 attribution).
        assert "T1_Half" in transcript.name
