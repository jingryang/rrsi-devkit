"""Detection layer B (P13 / step-116): load-time guard against hardcoded
``ASCEND_RT_VISIBLE_DEVICES`` overrides in skill tool scripts.

The one historically-real escape vector from the framework's structural card
pin was an in-tree literal write (a camodel env setup hardcoding ``"0"`` into
``os.environ``, which then persisted into every later real-card launch of the
same process). Parameterized writes (``str(npu_id)`` — dsl-cluster's parallel
tool) and ``setdefault`` (fallback-only, respects an inherited pin) stay
legal; a literal hard override silently breaks out of the pin.
"""

from __future__ import annotations

import re
from pathlib import Path

_SKILLS_DIR = (Path(__file__).resolve().parents[3] / ".claude" / "skills")

# A direct subscript-assignment of a literal device spec ("0", "0,1", …).
# setdefault / pop / parameterized RHS do not match.
_LITERAL_OVERRIDE = re.compile(
    r"ASCEND_RT_VISIBLE_DEVICES['\"]\s*\]\s*=\s*['\"][0-9][0-9,\s]*['\"]")

# Known offenders pending their owner's confirmation (A5 domain needs separate
# sign-off before the same setdefault fix lands) — tracked as shrinkable debt,
# mirroring test_layer_dependencies' KNOWN set. Empty when fixed.
# (main 分支该文件已由 A5 侧修复，无在册 offender；新违例由本守护直接报红。)
_PENDING_FIX: set[str] = set()


def _skill_py_files():
    assert _SKILLS_DIR.is_dir(), f"skills dir missing: {_SKILLS_DIR}"
    return sorted(_SKILLS_DIR.rglob("*.py"))


def test_no_literal_visible_devices_override_in_skill_tools():
    offenders = [
        f"{p.relative_to(_SKILLS_DIR)}: {m.group(0)}"
        for p in _skill_py_files()
        for m in _LITERAL_OVERRIDE.finditer(p.read_text(encoding="utf-8",
                                                        errors="replace"))
        if str(p.relative_to(_SKILLS_DIR)) not in _PENDING_FIX
    ]
    assert not offenders, (
        "skill tool scripts must not hard-override ASCEND_RT_VISIBLE_DEVICES "
        "with a literal — it breaks out of the framework card pin "
        "(use setdefault fallback or a parameterized value):\n  "
        + "\n  ".join(offenders))


def test_pending_fix_list_still_matches_real_offenders():
    """The pending list must not rot: every entry still offends, every pending
    offender is listed. When the A5 fix lands, both sides empty together."""
    pending_offenders = {
        str(p.relative_to(_SKILLS_DIR))
        for p in _skill_py_files()
        if _LITERAL_OVERRIDE.search(p.read_text(encoding="utf-8",
                                                errors="replace"))
    }
    assert pending_offenders == _PENDING_FIX, (
        f"pending-fix drift: actual={sorted(pending_offenders)} "
        f"listed={sorted(_PENDING_FIX)} — fix the offender and drop the entry, "
        "or add the new offender to the list")
