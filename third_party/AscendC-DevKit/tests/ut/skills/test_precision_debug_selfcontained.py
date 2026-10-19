"""Stage 1 (54-*.md) — per-phase precision_debug skill 即插即用性 (§2.1/§2.2/§2.6).

Deterministic (no-LLM) guards locking the plug-and-play invariant so it can't
silently regress:

  - Each per-phase SKILL.md ships in the single flat tree .claude/skills/<skill>/
    (natively discovered by both backends — §4.2).
  - Each skill's frontmatter ``name`` matches its directory name.
  - The two phase sub-agent manifests (ascendc-precision-{run-tests,diagnose})
    parse and validate clean. (P3 减法：scope_guard/bounds_check/printf/comment_bisect
    独立 phase 已删，只剩 run_tests ⇄ diagnose。)
  - Each SKILL.md is self-contained (§2.1/§2.2/§2.6): no live references to
    paths outside its own dir, no absolute paths, no DevKit-internal MCP.
    (A bare skill-name pointer to a sibling skill is allowed.)
"""

from __future__ import annotations

import re
from pathlib import Path

from ascendc_devkit.capabilities.skill.loader import (
    load_agent_manifest, validate_manifest,
)

_SKILLS_ROOT = Path(__file__).resolve().parents[3] / ".claude" / "skills"

# Per-phase skills (the fat ascendc-precision-debug was deleted — §2.5 single path)
# §judgment-ownership (N1): run_tests 纯 Python 化——run_tests skill 删除（测量脚本迁入
# 框架包 src/.../precision_debug_run_tests/scripts/），只剩 diagnose 是 phase skill。
_PHASE_SKILLS = [
    "ascendc-precision-diagnose",
]

# Live-reference leak patterns
_LEAK_PATTERNS = [
    r"\.claude/rules/",
    r"\.claude/AIInfra",
    r"[A-Z]:\\",          # Windows abs path
    r"/home/",
    r"/usr/local/Ascend",
    r"\$ASCEND_TOOLKIT_HOME",
    r"\$ASCEND_OPP_PATH",
    r"mcp__ascendc",
]

_NEGATION_MARKERS = ("禁止", "不再", "不要", "不写", "不读", "改为", "悬空", "删除",
                     "已删除", "不依赖", "不引", "无绝对", "不包含", "without",
                     "不引用", "均已删", "不调用")


def _live_lines(text: str) -> list[str]:
    return [ln for ln in text.splitlines()
            if not any(m in ln for m in _NEGATION_MARKERS)]


class TestPerPhaseSkillsPackaged:
    def test_each_skill_md_exists(self):
        for skill in _PHASE_SKILLS:
            sm = _SKILLS_ROOT / skill / "SKILL.md"
            assert sm.is_file(), f"skills/{skill}/SKILL.md missing"

    def test_each_frontmatter_name_matches_dir(self):
        for skill in _PHASE_SKILLS:
            body = (_SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
            m = re.search(r"^name:\s*(\S+)\s*$", body, re.MULTILINE)
            assert m and m.group(1) == skill, (
                f"{skill}/SKILL.md frontmatter name must equal dir name {skill!r}")

    def test_each_carries_schema(self):
        """§2.2: each per-phase skill ships its schema/ in its own dir."""
        for skill in _PHASE_SKILLS:
            schema_dir = _SKILLS_ROOT / skill / "schema"
            assert schema_dir.is_dir(), f"{skill}/schema/ missing"
            schemas = list(schema_dir.glob("*.json"))
            assert len(schemas) >= 1, f"{skill} has no schema files"


class TestPerPhaseSkillsSelfContained:
    def test_no_live_external_references(self):
        for skill in _PHASE_SKILLS:
            sm = _SKILLS_ROOT / skill / "SKILL.md"
            body = "\n".join(_live_lines(sm.read_text(encoding="utf-8")))
            for pat in _LEAK_PATTERNS:
                m = re.search(pat, body)
                assert m is None, (
                    f"{skill}/SKILL.md has live external ref matching {pat!r}: "
                    f"...{body[max(0, m.start()-40):m.start()+40]}...")

    def test_no_forced_clear(self):
        for skill in _PHASE_SKILLS:
            sm = _SKILLS_ROOT / skill / "SKILL.md"
            for ln in _live_lines(sm.read_text(encoding="utf-8")):
                assert "/clear" not in ln, (
                    f"{skill}: forced /clear must be gone: {ln!r}")

    def test_carries_core_methodology(self):
        """§2.7: each per-phase skill carries domain-core concepts (control.json
        relay, phase-specific json, per-phase methodology), not boilerplate."""
        core_terms = ["control.json", "phase_json_path", "RESULT:",
                      "operator_dir", "skill_dir"]
        for skill in _PHASE_SKILLS:
            body = (_SKILLS_ROOT / skill / "SKILL.md").read_text(encoding="utf-8")
            found = [t for t in core_terms if t in body]
            assert len(found) >= 3, (
                f"{skill}: expected ≥3 core terms, found {found}")
            # NO pip install scaffolding (§2.7)
            assert "pip install" not in body, (
                f"{skill}: must not carry pip install scaffolding (§2.7)")


class TestAgentManifest:
    """P0 (51-*.md): the LLM orchestrator agent is DELETED. The four phase
    sub-agents + scope_guard are the manifest-bearing agents; guard they
    each parse + validate + declare a tool surface."""

    _SUB_AGENTS = [
        "ascendc-precision-diagnose",
    ]

    def test_orchestrator_agent_deleted(self):
        from ascendc_devkit.capabilities.agent.sdk_backend import (
            agent_prompt_is_placeholder,
        )
        assert agent_prompt_is_placeholder("ascendc-precision-debugger"), (
            "ascendc-precision-debugger agent should be deleted (P0)")
        assert agent_prompt_is_placeholder("ascendc-precision-debugger-a5"), (
            "ascendc-precision-debugger-a5 agent should be deleted (P0)")

    def test_subagents_parse_and_validate(self):
        for agent in self._SUB_AGENTS:
            m = load_agent_manifest(agent)
            assert m.name == agent, f"{agent}: manifest name mismatch"
            errs = validate_manifest(m)
            assert errs == [], (
                f"{agent} manifest validation errors: {errs}")

    def test_subagents_declare_tool_surface(self):
        for agent in self._SUB_AGENTS:
            m = load_agent_manifest(agent)
            assert m.allowed_tools, f"{agent} should declare allowed_tools (§4.1)"
            assert "Bash" in m.allowed_tools, (
                f"{agent} needs Bash")


class TestNewSkillsPackaged:
    """Verify the 2 new skills (runtime-debug + sync-static-check) are plug-and-play."""

    _RUNTIME_SKILL = "ascendc-runtime-debug"
    _SYNC_SKILL_DIR = "ascendc-sync-static-check"

    def test_runtime_debug_skill_exists(self):
        skill_md = _SKILLS_ROOT / self._RUNTIME_SKILL / "SKILL.md"
        assert skill_md.is_file(), f"{self._RUNTIME_SKILL}/SKILL.md missing"

    def test_sync_check_skill_exists(self):
        skill_md = _SKILLS_ROOT / self._SYNC_SKILL_DIR / "SKILL.md"
        assert skill_md.is_file(), f"{self._SYNC_SKILL_DIR}/SKILL.md missing"

    def test_runtime_debug_self_contained(self):
        skill_md = _SKILLS_ROOT / self._RUNTIME_SKILL / "SKILL.md"
        body = "\n".join(_live_lines(skill_md.read_text(encoding="utf-8")))
        relaxed = [p for p in _LEAK_PATTERNS
                   if p not in (r"\$ASCEND_TOOLKIT_HOME", r"\$ASCEND_OPP_PATH")]
        for pat in relaxed:
            m = re.search(pat, body)
            assert m is None, (
                f"{self._RUNTIME_SKILL}/SKILL.md has external ref matching "
                f"{pat!r}: ...{body[max(0, m.start()-40):m.start()+40]}...")

    def test_sync_check_self_contained(self):
        skill_md = _SKILLS_ROOT / self._SYNC_SKILL_DIR / "SKILL.md"
        body = "\n".join(_live_lines(skill_md.read_text(encoding="utf-8")))
        for pat in _LEAK_PATTERNS:
            m = re.search(pat, body)
            assert m is None, (
                f"{self._SYNC_SKILL_DIR}/SKILL.md has external ref matching "
                f"{pat!r}: ...{body[max(0, m.start()-40):m.start()+40]}...")


class TestApiLookupClosure:
    """P15：API 查证链禁「知识库无记录 → API 不存在」假闭环。

    知识库是精选子集（索引），索引缺口不能当 ground truth 排除修复方向；
    「找不到」后必须留定向查证回退（定点读/窄域锚定 grep/问用户），
    终态只能是「存在性存疑 + 降权」，不是「不存在 + 排除」。
    """

    def test_no_false_closure_over_knowledge_base_index(self):
        sm = _SKILLS_ROOT / "ascendc-precision-diagnose" / "SKILL.md"
        body = sm.read_text(encoding="utf-8")
        assert "则 API 不存在" not in body, (
            "假闭环文本回潮：知识库查不到被直接判『API 不存在』")

    def test_coder_skill_no_false_closure_over_knowledge_base_index(self):
        # coder 侧同族（知识源优先级链末端）：三源查不到 = 知识库未覆盖，
        # 不是「API 不存在」的存在性结论。
        sm = _SKILLS_ROOT / "ascendc-op-dev-coding" / "SKILL.md"
        body = sm.read_text(encoding="utf-8")
        assert "「API 不存在」" not in body, (
            "假闭环文本回潮：知识库查不到被直接判『API 不存在』")
        assert "知识库未覆盖" in body

    def test_carries_fallback_and_bounded_ban(self):
        sm = _SKILLS_ROOT / "ascendc-precision-diagnose" / "SKILL.md"
        body = sm.read_text(encoding="utf-8")
        # 回退三通道 + 存在性存疑终态 + 禁令收窄为「广撒网」
        assert "知识库未覆盖" in body
        assert "存在性存疑" in body and "降权" in body
        assert "广撒网" in body and "不受禁" in body
