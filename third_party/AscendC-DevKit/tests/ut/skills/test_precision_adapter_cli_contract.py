"""Contract guard: precision-adapter SKILL.md command template ↔ init-checkpoint CLI.

B2 regression: removing a CLI argument from the framework-side script while the
skill's command template still passes it made the TUI adapter loop die at init
(`unrecognized arguments`, argparse exit 2) with no test noticing. The skill's
bash template and the script's argparse are one framework↔skill interface —
this guard binds them mechanically: every template flag must exist in the
script's parser, and every required argument must be present in the template.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[3]
_SCRIPT = (_REPO / "src" / "ascendc_devkit" / "orchestration" / "stages" /
           "precision_debug_run_tests" / "scripts" / "init-checkpoint.py")
_SKILL_MD = (_REPO / ".claude" / "skills" / "ascendc-precision-adapter" /
             "SKILL.md")


def _argparse_args(script: Path) -> dict[str, bool]:
    """Map of flag → required, from add_argument calls in the script."""
    tree = ast.parse(script.read_text(encoding="utf-8"))
    args: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        flags = [a.value for a in node.args
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)
                 and a.value.startswith("--")]
        required = any(kw.arg == "required" and isinstance(kw.value, ast.Constant)
                       and kw.value.value for kw in node.keywords)
        for f in flags:
            args[f] = required
    return args


def _template_flags() -> set[str]:
    """Flags used by the SKILL.md init-checkpoint invocation (section 2)."""
    text = _SKILL_MD.read_text(encoding="utf-8")
    m = re.search(r"python3 \{INIT_CKPT\}(.*?)```", text, re.DOTALL)
    assert m, "SKILL.md init-checkpoint command template not found"
    return set(re.findall(r"--[a-z][a-z0-9-]*", m.group(1)))


def test_template_flags_all_exist_in_argparse():
    parser_args = _argparse_args(_SCRIPT)
    unknown = _template_flags() - set(parser_args)
    assert not unknown, (
        f"SKILL.md 模板传了脚本不认识的参数（TUI 初始化即 argparse exit 2）: "
        f"{sorted(unknown)}；脚本现存参数: {sorted(parser_args)}")


def test_required_args_all_present_in_template():
    parser_args = _argparse_args(_SCRIPT)
    missing = {f for f, req in parser_args.items() if req} - _template_flags()
    assert not missing, (
        f"init-checkpoint 必填参数未出现在 SKILL.md 模板（初始化必失败）: "
        f"{sorted(missing)}")
