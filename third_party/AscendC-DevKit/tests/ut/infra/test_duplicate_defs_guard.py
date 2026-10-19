"""Guard: no duplicate function definitions in src (B1 regression).

A scripted edit once appended a whole modified helper cluster to dispatcher.py
without deleting the original — ~1023 dead lines whose stale copy contained an
undefined name. Python's last-def-wins shadowing made it invisible to every
runtime test (imports fine, callers bind the final def). This guard catches
the accident class at load time, deterministically.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[3] / "src" / "ascendc_devkit"


def _src_files() -> list[Path]:
    return sorted(_SRC.rglob("*.py"))


def _duplicate_defs(path: Path) -> list[str]:
    """Names defined more than once in the same class/module scope."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    seen: dict[str, int] = {}
    dup: list[str] = []

    def _collect(body, label: str) -> None:
        names: set[str] = set()
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name in names and not node.name.startswith("__"):
                    dup.append(f"{label}:{node.name}")
                names.add(node.name)
            elif isinstance(node, ast.ClassDef):
                _collect(node.body, f"{label}.{node.name}")

    _collect(tree.body, str(path.relative_to(_SRC)))
    return dup


@pytest.mark.parametrize("path", _src_files(), ids=lambda p: str(p))
def test_no_duplicate_function_defs(path: Path):
    dups = _duplicate_defs(path)
    assert not dups, (
        f"duplicate function definitions (last-def-wins shadows the earlier "
        f"copy — the shadowed one is dead code and silently diverges): {dups}")


def test_guard_scans_source_tree():
    # anti-rot: the guard must actually see the tree it polices
    assert len(_src_files()) > 100, "src tree unexpectedly small — guard mis-rooted"
