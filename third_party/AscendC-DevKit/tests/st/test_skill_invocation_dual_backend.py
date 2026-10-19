"""相2 §2.4 Spike-1 — dual-backend skill-methodology injection (D2, real-link).

THE acceptance guard that the D2 skill-delivery seam works IDENTICALLY on both
agent backends. One assertion body, parametrized over ``claude`` and ``opencode``
× the merged tiling design skill (directive: 相2 每步 claude + opencode 双侧真跑，
不留单边盲区).

Hard signal (mirrors tests/st/test_skill_invocation.py): the persisted transcript
must contain terms that live ONLY in the assigned skill's SKILL.md and never in
the prompt. Their presence proves the backend actually loaded the flat skill:
  - claude  : backend prepends ``/<skill>`` to the first message (CLI expands it).
  - opencode : backend steers ``skill({name})`` via ``system`` + ``permission.skill``
               allow, and opencode natively discovers the SAME flat
               ``.claude/skills/<name>/SKILL.md`` tree.

Reachability = the methodology shows up in ANY attempt within the retry budget
(§3.10 — bounded retry absorbs real-LLM jitter, does NOT weaken into a mock).

Marked @pytest.mark.llm (single-spawn skill load, seconds-scale — NOT heavy_llm:
no minutes-long multi-turn pipeline; runs in the default suite once LLM prechecks).

Skills covered:
  - tiling   : ascendc-op-tiling (the merged facade skill; split → vf-design →
               buffer-kernel → precision-perf tail-called in one session).
  - st-design: ascendc-st-design (M3: 替换旧 test_design 三步后的新测试设计 skill，
               恢复被删的 test_testdesign_skill_invocation 真实方法论注入守护).
"""

from __future__ import annotations

import pytest

from tests.st._dual_backend import (
    has_anthropic,
    load_settings_env,
    make_backend,
    require_live_opencode,
)

load_settings_env()


# One assertion body, parametrized over (skill, backend). Each case carries its
# SKILL.md-only methodology markers, the pathway prompt, and the stage that
# produces its SpawnAgent.
def _tiling_stage():
    from ascendc_devkit.orchestration.stages.design_substages import TilingStage
    return TilingStage(template={"name": "T1"})


def _st_design_stage():
    from ascendc_devkit.orchestration.registry import get_stage
    return get_stage("ascendc-st-design")()


_SKILL_CASES = {
    "tiling": {
        "assigned": "ascendc-op-tiling",
        # Terms ONLY in ascendc-op-tiling/SKILL.md, never in the prompt.
        "markers": ("编排门面", "串行调度", "tiling_current_template.json", "跨段一致性"),
        "prompt": (
            "这是一个通路验证测试。请直接说明：你已经加载了单模板完整 tiling 推导的方法论，"
            "并输出该方法论中的核心概念/术语名称（用逗号分隔列出）。"
            "不需要做实际的 tiling 分析，不需要读写文件。简短回答即可。"
        ),
        "stage_name": "tiling",
        "branch_label": "T1",
        "op_name": "rotary_position_embedding",
        "chip": None,
        "stage_factory": _tiling_stage,
    },
    "st-design": {
        "assigned": "ascendc-st-design",
        # Terms ONLY in ascendc-st-design/SKILL.md (脚本名/术语均不进 stage prompt)：
        # stage prompt 只点名 merge_test_cases.py / convert_to_param_def.py；
        # generate_implicit_constraints / generate_solver_config / generate_test_cases
        # 与「锚点因子」（solver step 6 术语）只在 SKILL.md。命中即证明方法论被注入。
        "markers": ("generate_implicit_constraints.py",
                    "generate_solver_config.py",
                    "generate_test_cases.py", "锚点因子"),
        "prompt": (
            "这是一个通路验证测试。请直接说明：你已经加载了 ascendc-st-design 测试"
            "设计方法论，并输出该方法论中的核心概念/脚本名（用逗号分隔列出）。"
            "不需要做实际的测试设计，不需要读写文件。简短回答即可。"
        ),
        "stage_name": "ascendc-st-design",
        "branch_label": "",
        "op_name": "add",
        "chip": None,
        "stage_factory": _st_design_stage,
    },
}

_MAX_ATTEMPTS = 3


def _assert_production_carries_skill(case) -> None:
    """Production guard (backend-agnostic): the stage carries the methodology on
    ``SpawnAgent.primary_skill`` (D2 — delivery rendered at the backend boundary,
    NOT prepended into the prompt by the stage). A missing spawn means the stage
    failed to emit its SpawnAgent."""
    from ascendc_devkit.orchestration.kernel.state import State
    from ascendc_devkit.orchestration.kernel.action import SpawnAgent

    state_kwargs = dict(
        op_name=case["op_name"],
        template_division={"templates": [{"name": case["branch_label"]}]})
    if case["chip"] is not None:
        state_kwargs["design_target_chip"] = case["chip"]
    state = State.empty().with_updates(**state_kwargs)
    stage = case["stage_factory"]()
    spawns = [a for a in stage.actions(state, 1) if isinstance(a, SpawnAgent)]
    assert spawns, (
        f"{case['assigned']}: stage produced no SpawnAgent — check the stage's "
        f"actions() and assigned skill")
    assert spawns[0].primary_skill == case["assigned"]


@pytest.mark.llm
@pytest.mark.parametrize(
    "skill,kind",
    [(s, k) for s in _SKILL_CASES for k in ("claude", "opencode")],
    ids=[f"{s}-{k}" for s in _SKILL_CASES for k in ("claude", "opencode")])
def test_skill_methodology_enters_agent_context_dual_backend(skill, kind, tmp_path):
    """D2 parity: the assigned skill's SKILL.md-only methodology reaches the
    design agent's transcript on BOTH backends, for each covered skill
    (tiling + st-design).

    Per-backend gate（§3.7）：claude 后端依赖 ANTHROPIC_* 凭据（has_anthropic）；
    opencode 后端用自己的 opencode.json provider，不依赖 Anthropic——用
    require_live_opencode() 的 smoke 判定（配置/网关/模型真实可用才跑），
    避免 opencode 可用却被缺 Anthropic 一刀切 skip。"""
    if kind == "claude" and not has_anthropic():
        pytest.skip("Anthropic not configured")
    if kind == "opencode":
        require_live_opencode()

    case = _SKILL_CASES[skill]
    _assert_production_carries_skill(case)

    hit = None
    for attempt in range(_MAX_ATTEMPTS):
        ws = tmp_path / f"ws_{attempt}"
        ws.mkdir(parents=True, exist_ok=True)
        backend = make_backend(kind, ws)
        backend.spawn(
            "ascendc-design-generator", case["prompt"], {},
            skills=[case["assigned"]],
            primary_skill=case["assigned"],
            working_dir=ws,
            stage_name=case["stage_name"],
            branch_label=case["branch_label"],
        )
        for t in sorted((ws / "agents").glob("*.jsonl")):
            body = t.read_text()
            hit = next((m for m in case["markers"] if m in body), None)
            if hit:
                break
        if hit:
            break

    assert hit, (
        f"[{skill}/{kind}] no SKILL.md-only methodology term appeared across "
        f"{_MAX_ATTEMPTS} attempts — backend did not inject the skill "
        "(D2 regression: check primary_skill on the spawn, backend skill "
        "rendering, and flat skill-tree discoverability)")
