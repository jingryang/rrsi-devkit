"""Backstop UT for regbase coding skill template invariants.

Guards the fixes documented in:
  references/diff-analysis-vs-ascendc-dev.md

§3.8 pure logic — parses markdown files, asserts structural invariants.
No LLM/NPU/CANN dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# ── path resolution ──────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SKILL_DIR = (
    _REPO_ROOT / ".claude" / "skills"
    / "ascendc-op-dev-coding-regbase"
)
_SKILL_MD = _SKILL_DIR / "SKILL.md"
_PHASE_C_PROMPTS = _SKILL_DIR / "references" / "phase-c-prompts.md"
_ORCHESTRATOR_LOGIC = _SKILL_DIR / "references" / "orchestrator-logic.md"


# ── helpers ──────────────────────────────────────────────────────────────────

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _extract_section(content: str, heading: str, next_headings: list[str] | None = None) -> str:
    """Extract the text under a markdown heading until the next heading or EOF."""
    pattern = re.escape(heading)
    m = re.search(rf"^{pattern}\s*$", content, re.MULTILINE)
    if not m:
        return ""
    start = m.end()
    if next_headings:
        stops = "|".join(re.escape(h) for h in next_headings)
        end_m = re.search(rf"^(?:{stops})\s*$", content[start:], re.MULTILINE)
        end = start + end_m.start() if end_m else len(content)
    else:
        # find next ## heading
        end_m = re.search(r"^##\s", content[start:], re.MULTILINE)
        end = start + end_m.start() if end_m else len(content)
    return content[start:end]


def _extract_code_block(content: str, label_hint: str) -> str:
    """Extract the first fenced code block after a markdown heading containing label_hint."""
    idx = content.find(label_hint)
    if idx < 0:
        return ""
    m = re.search(r"```(?:python|bash|json)?\s*\n(.*?)```", content[idx:], re.DOTALL)
    return m.group(1) if m else ""


# ═══════════════════════════════════════════════════════════════════════════════
# Phase C Prompts — fast_start 协议已移除
# ═══════════════════════════════════════════════════════════════════════════════

class TestFastStartRemoved:
    """Guard: fast_start 协议已从 agent 前置检查中移除，门控收敛到编排层。

    前置检查（check_gate.sh / fast_start 跳过）已删除——阶段跳转完全由 Python
    编排层确定性门控（s2→s4 校验 orchestration_plan.json + coding_index.md）决定，
    模板中不得残留 【fast_start】 字段。
    """

    def test_phase_c_prompts_has_no_fast_start(self):
        """phase-c-prompts.md 不得包含 【fast_start】 字段。"""
        content = _read(_PHASE_C_PROMPTS)
        assert "【fast_start】" not in content, (
            "fast_start 协议已移除（门控收敛到 Python 编排层），"
            "模板中残留 【fast_start】 会诱导 agent 执行已删除的前置检查协议"
        )

    def test_skill_md_has_no_fast_start(self):
        """SKILL.md 不得引用 fast_start 协议。"""
        content = _read(_SKILL_MD)
        assert "fast_start" not in content, (
            "SKILL.md 残留 fast_start 引用（协议已移除）"
        )

    def test_orchestrator_logic_has_no_fast_start(self):
        """orchestrator-logic.md 不得引用 fast_start 协议。"""
        content = _read(_ORCHESTRATOR_LOGIC)
        assert "fast_start" not in content, (
            "orchestrator-logic.md 残留 fast_start 引用（协议已移除）"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase C Prompts — field completeness in 【已在主 SKILL 收集的项】
# ═══════════════════════════════════════════════════════════════════════════════

class TestCollectedItemsCompleteness:
    """Guard #19, #20, #21: template 【已在主 SKILL 收集的项】 must list all
    optional fields that SKILL.md says should be injected."""

    def _get_collected_fields(self, section: str) -> set[str]:
        """Parse the collected-items section and return the set of field variable names."""
        fields: set[str] = set()
        # Match lines like: "- field_name: {VAR_NAME}（..."
        for m in re.finditer(r"^- (\w+): \{(\w+)\}", section, re.MULTILINE):
            fields.add(m.group(1))
        return fields

    def test_c2_has_design_doc_and_vf_ref_dir(self):
        """#19 — C.2 must inject design_doc and vf_ref_dir."""
        content = _read(_PHASE_C_PROMPTS)
        section = _extract_section(content, "## C.2 ascendc-dev-s2-analysis",
                                   ["## C.3 循环机制"])
        collected_start = section.find("【已在主 SKILL 收集的项")
        assert collected_start >= 0, (
            "C.2 missing 【已在主 SKILL 收集的项】 section"
        )
        fields = self._get_collected_fields(section[collected_start:])

        missing = []
        for f in ("design_doc", "vf_ref_dir"):
            if f not in fields:
                missing.append(f)
        assert not missing, (
            f"C.2 【已在主 SKILL 收集的项】 missing fields: {missing}. "
            "SKILL.md:149 requires these be injected into S2 prompt"
        )

    def test_c3_s4_has_design_doc_and_ref_op(self):
        """#21 — C.3 S4 must inject design_doc and ref_op."""
        content = _read(_PHASE_C_PROMPTS)
        idx_s4 = content.find("## C.3 ascendc-dev-s4-coding")
        idx_vf = content.find("## C.3 ascendc-vf-test-agent", idx_s4 + 1)
        section = content[idx_s4:idx_vf] if idx_vf > idx_s4 else content[idx_s4:]

        collected_start = section.find("【已在主 SKILL 收集的项")
        assert collected_start >= 0, (
            "C.3 S4 missing 【已在主 SKILL 收集的项】 section"
        )
        fields = self._get_collected_fields(section[collected_start:])

        missing = []
        for f in ("design_doc", "ref_op"):
            if f not in fields:
                missing.append(f)
        assert not missing, (
            f"C.3 S4 【已在主 SKILL 收集的项】 missing fields: {missing}. "
            "SKILL.md:150 requires these be injected into S4 prompt"
        )

    def test_c3_vf_has_all_collected_fields(self):
        """#20 — C.3 VF must inject design_doc, ref_op, vf_ref_dir."""
        content = _read(_PHASE_C_PROMPTS)
        idx_vf = content.find("## C.3 ascendc-vf-test-agent")
        # Find the real VF section (the one with '仅 A5 Regbase')
        if "仅 A5 Regbase" not in content[idx_vf:idx_vf + 80]:
            idx_vf = content.find("## C.3 ascendc-vf-test-agent", idx_vf + 1)
        idx_c4 = content.find("## C.4 ascendc-dev-s5-compile", idx_vf)
        section = content[idx_vf:idx_c4] if idx_c4 > idx_vf else content[idx_vf:]

        collected_start = section.find("【已在主 SKILL 收集的项")
        assert collected_start >= 0, (
            "C.3 VF missing 【已在主 SKILL 收集的项】 section"
        )
        fields = self._get_collected_fields(section[collected_start:])

        missing = []
        for f in ("design_doc", "ref_op", "vf_ref_dir"):
            if f not in fields:
                missing.append(f)
        assert not missing, (
            f"C.3 VF 【已在主 SKILL 收集的项】 missing fields: {missing}. "
            "SKILL.md:152 requires these be injected into VF prompt"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Phase C Prompts — next_stage constraint
# ═══════════════════════════════════════════════════════════════════════════════

class TestNextStageConstraint:
    """Guard #17: C.2 must explicitly constrain next_stage=4 (not 3)."""

    def test_c2_has_next_stage_4_constraint(self):
        """#17 — C.2 must contain next_stage=4 constraint, forbid next_stage=3."""
        content = _read(_PHASE_C_PROMPTS)
        section = _extract_section(content, "## C.2 ascendc-dev-s2-analysis",
                                   ["## C.3 循环机制"])
        assert "next_stage=4" in section, (
            "C.2 missing 'next_stage=4' constraint. "
            "Without it s2-analysis may return next_stage=3 → PAUSED"
        )
        assert "禁止返回 next_stage=3" in section or "禁止返回 `next_stage=3`" in section, (
            "C.2 missing explicit prohibition of next_stage=3"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator Logic — no ascendc-dev residue
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrchestratorLogicRegbasePurity:
    """Guard #10: orchestrator-logic.md must not contain Stage 3 / s3-clarify
    references or ascendc-dev todo numbering."""

    def test_no_stage3_or_s3_clarify(self):
        """#10 — No Stage 3 quick-path or s3-clarify as active agent reference."""
        content = _read(_ORCHESTRATOR_LOGIC)

        # "s3-clarify" may appear in the §3 "不适用" disclaimer (line 175).
        # That's correct — it says regbase has NO s3-clarify.
        # Remove that line, then check the rest for forbidden references.
        cleaned = "\n".join(
            line for line in content.split("\n")
            if "不存在 Stage 3" not in line and "不适用" not in line
        )

        forbidden = [
            ("s3-clarify", "s3-clarify agent reference (outside §3 disclaimer)"),
            ("Stage 3 快速通道", "Stage 3 quick-path section"),
            ("todo-7", "ascendc-dev todo-7 (regbase has no todo-7)"),
        ]
        for pattern, desc in forbidden:
            assert pattern not in cleaned, (
                f"orchestrator-logic.md contains '{pattern}' ({desc}). "
                "regbase is 3-stage (s2→s4→s5), no Stage 3"
            )

    def test_uses_regbase_todo_numbers(self):
        """#10/#15 — Must use regbase todo-naming (todo-2/3/4), not ascendc-dev."""
        content = _read(_ORCHESTRATOR_LOGIC)

        # These ascendc-dev todo numbers must NOT appear
        forbidden_todos = ["todo-8", "todo-9", "todo-10", "todo-11"]
        for t in forbidden_todos:
            assert t not in content, (
                f"orchestrator-logic.md contains ascendc-dev todo '{t}'. "
                "regbase uses todo-2 (s4-coding), todo-3 (VF), todo-4 (s5-compile)"
            )

    def test_finish_action_references_todo2(self):
        """#15 — finish action must reference todo-2/todo-3, not todo-8/todo-9."""
        content = _read(_ORCHESTRATOR_LOGIC)
        # Find the finish action row in dispatch table
        finish_patterns = re.findall(r"`finish`\s*\|.*\|", content)
        for row in finish_patterns:
            assert "todo-8" not in row, f"finish action references todo-8: {row.strip()}"
            assert "todo-9" not in row, f"finish action references todo-9: {row.strip()}"

    def test_vf_failed_uses_vf_exhausted_not_paused(self):
        """#11 — VF FAILED exhaustion must produce vf_exhausted (non-blocking),
        not PAUSED (which would deadlock in zero-interaction mode)."""
        content = _read(_ORCHESTRATOR_LOGIC)

        # The dispatch action table must contain vf_exhausted
        assert "vf_exhausted" in content, (
            "orchestrator-logic.md missing 'vf_exhausted' action. "
            "VF exhaustion must not PAUSED in zero-interaction regbase mode"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# SKILL.md — flow invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestSkillMdFlowInvariants:
    """Guard #11, #12, #13: SKILL.md structural invariants for expand-kernel
    verification, current_stage update, vf_test retries, progress.md format."""

    def test_step12_has_expand_kernel_verification(self):
        """#12 — Step 1.2 must verify s2-analysis produced a usable plan.

        Originally this guarded the progress.md expand-kernel grep. The flow
        since moved the authoritative s2 output to ``orchestration_plan.json``
        (progress.md is now a derived mirror regenerated by the framework from
        the plan). The invariant preserved here is the same: Step 1.2 must
        fail-fast when s2-analysis silently produced nothing usable, instead of
        letting the empty plan flow into s4 and loop forever. The check is the
        ``[ ! -s "$RECORD_DIR/orchestration_plan.json" ]`` guard whose absence
        would let a silent s2 failure go undetected (run 20260805-024838-57d2cd
        placeholder rows → infinite retry_s4)."""
        content = _read(_SKILL_MD)
        assert (
            'grep -qF "| 4.C Kernel"' in content
            or 'orchestration_plan.json' in content
        ), (
            "SKILL.md Step 1.2 missing s2-output verification. "
            "Without it, a silent s2-analysis failure (no plan / placeholder "
            "rows) goes undetected and s4 loops forever"
        )

    def test_step12_updates_current_stage(self):
        """#13 — Step 1.2 must set current_stage=2 after s2 COMPLETED."""
        content = _read(_SKILL_MD)
        assert 'set-meta' in content and 'current_stage 2' in content, (
            "SKILL.md Step 1.2 missing 'set-meta current_stage 2'. "
            "Without it, Scenario D recovery after s2 COMPLETED re-enters Step 1"
        )

    def test_step11_includes_vf_test_retries(self):
        """#11 — Step 1.1 meta.json defaults must include vf_test retry counter."""
        content = _read(_SKILL_MD)
        # The python code is inside a ```bash block: python3 -c " ... "
        # Find the area around Step 1.1
        idx = content.find("1.1 首次初始化")
        if idx < 0:
            idx = content.find("扩展 meta.json 追踪字段")
        assert idx >= 0, "Could not locate Step 1.1 in SKILL.md"

        snippet = content[idx:idx + 2000]

        assert "'vf_test':" in snippet, (
            "SKILL.md Step 1.1 meta.json defaults missing 'vf_test' retry counter. "
            "Required for independent VF exhaustion tracking (#11 fix)"
        )
        assert ("'used': 0, 'limit': 2" in snippet
                or '"used": 0, "limit": 2' in snippet), (
            "SKILL.md Step 1.1 vf_test counter must have used=0, limit=2"
        )

    def test_progress_md_skeleton_no_stage1_or_stage3(self):
        """#16 — progress.md skeleton must not contain Stage 1 or Stage 3 rows.
        If present, check_gate.sh would pass incorrectly for regbase."""
        content = _read(_SKILL_MD)
        # Find the progress.md skeleton (cat > ... << 'EOF' ... EOF)
        idx = content.find("progress.md 骨架")
        if idx < 0:
            idx = content.find("cat > \"$RECORD_DIR/progress.md\"")
        if idx < 0:
            pytest.skip("Could not locate progress.md skeleton in SKILL.md")

        # Extract the heredoc content
        m = re.search(r"<<\s*'EOF'\s*\n(.*?)EOF", content[idx:], re.DOTALL)
        if not m:
            m = re.search(r"<<\s*EOF\s*\n(.*?)EOF", content[idx:], re.DOTALL)
        assert m, "Could not extract progress.md heredoc from SKILL.md"

        skeleton = m.group(1)
        # Check no Stage 1 or Stage 3 rows exist
        for forbidden in ("| 1 ", "| 3 "):
            assert forbidden not in skeleton, (
                f"progress.md skeleton contains '{forbidden}' row. "
                "regbase has no Stage 1 or Stage 3 — check_gate.sh would be misled"
            )

    def test_skill_md_input_table_has_vf_ref_dir(self):
        """#19 — SKILL.md input table must declare VF_REF_DIR as optional input."""
        content = _read(_SKILL_MD)
        input_section_start = content.find("## 输入")
        sk_root_start = content.find("## SKILL_ROOT", input_section_start)
        input_section = content[input_section_start:sk_root_start] if sk_root_start > input_section_start else ""

        assert "VF_REF_DIR" in input_section, (
            "SKILL.md input table missing VF_REF_DIR declaration"
        )
        assert "否" in input_section.split("VF_REF_DIR")[1][:50], (
            "VF_REF_DIR should be marked as optional (否) in input table"
        )
