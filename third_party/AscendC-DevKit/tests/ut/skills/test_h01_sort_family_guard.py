"""Backstop UT for H01 select-sort family knowledge contract.

Guards the int64→fp32 cross-dtype sorting trap documented in
  .claude/skills/ascendc-op-general-design/references/patterns/atomic/H01_select-sort.md
§3.5 (sorting-family selection) and the shared no-guess fallback in
  .claude/skills/ascendc-op-design-shared/references/knowledge_policy.md

Why this exists: the 20260822 unique run selected bitonic comparison-sort for
int64-index sorting, which silently lost precision (int64 → fp32, 24-bit
mantissa). H01 had covered radix's bit-order transform and bitmap's int64
limitation but MISSED the "comparison-sort + int64 index" combination — a
classic enumeration blind spot (§1.14). These tests guard the general
cross-dtype-lossless rule so it cannot be silently reverted.

§3.8 pure logic — parses markdown, asserts structural invariants.
No LLM/NPU/CANN dependency.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_H01 = (
    _REPO_ROOT
    / ".claude" / "skills" / "ascendc-op-general-design"
    / "references" / "patterns" / "atomic" / "H01_select-sort.md"
)
_KNOWLEDGE_POLICY = (
    _REPO_ROOT
    / ".claude" / "skills" / "ascendc-op-design-shared"
    / "references" / "knowledge_policy.md"
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class TestH01CrossDtypeTrap:
    """H01 sorting family must warn that int→fp cross-dtype comparison loses
    precision (structure signal — the exact trap the unique run hit)."""

    def test_h01_mentions_int_to_fp_loss(self):
        content = _read(_H01)
        assert "int64" in content, "H01 must cover int64 (the whole-point dtype)"
        assert "转 fp32" in content or "fp32" in content, (
            "H01 must warn int→fp32 comparison loses precision"
        )

    def test_h01_warns_comparison_sort_requires_lossless_check(self):
        content = _read(_H01)
        assert "跨 dtype 转换必须无损" in content, (
            "H01 must mandate lossless cross-dtype check (not enumerate combos)"
        )
        assert "comparable" in content or "位序" in content, (
            "H01 must offer comparable bit-order transform as the lossless path"
        )

    def test_h01_forbids_bare_int_fp_sort(self):
        content = _read(_H01)
        assert "Cast(int, fp)" in content or "裸 `Cast(int, fp)`" in content, (
            "H01 must forbid bare Cast(int, fp) for sorting"
        )


class TestKnowledgePolicyNoGuessFallback:
    """knowledge_policy must say: on missing API constraint, sink DOWN layers
    first, then expose/ask — never guess or assume 'unmentioned = unrestricted'."""

    def test_policy_forbids_guessing(self):
        content = _read(_KNOWLEDGE_POLICY)
        assert "不猜测" in content or "禁止猜测" in content

    def test_policy_sinks_down_before_exposing(self):
        content = _read(_KNOWLEDGE_POLICY)
        # Must mention sinking to the next-lower tier, not jump straight to AskUserQuestion
        assert "下沉" in content and "下一层" in content, (
            "knowledge_policy must mandate sinking to lower tiers before exposing"
        )

    def test_policy_rejects_unmentioned_equals_unrestricted(self):
        content = _read(_KNOWLEDGE_POLICY)
        assert "没提就是没限制" in content or "没写就是没限制" in content, (
            "must reject the 'unmentioned = unrestricted' fallacy"
        )
