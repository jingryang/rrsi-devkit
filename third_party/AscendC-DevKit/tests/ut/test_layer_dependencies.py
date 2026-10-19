"""Guard: enforce strict downward layer dependencies.

Architecture rule (from CLAUDE.md L2.4):
  L1 -> L2, L4
  L2 -> L3, L4, L7
  L3 -> L4, L5, L6, L7
  L4 -> (none)
  L5 -> L4, L6, L7
  L6 -> L4, L7
  L7 -> (none)

Any import that violates this matrix causes this test to fail.
"""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import pytest

SRC = Path(__file__).resolve().parent.parent.parent / "src" / "ascendc_devkit"

LAYER_MAP: Dict[str, int] = {
    "cli": 1,
    "application": 2,
    "orchestration": 3,
    "domain": 4,
    "capabilities": 5,
    "adapters": 6,
    "infra": 7,
}

ALLOWED: Dict[int, Set[int]] = {
    1: {2, 4},
    2: {3, 4, 7},
    3: {4, 5, 6, 7},
    4: set(),
    5: {4, 6, 7},
    6: {4, 7},
    7: set(),
}

# Known violations — shrink toward empty as they are fixed.
# Keys: "source_file_relative -> target_layer target_module"
# KNOWN 清零完成（2026-09-03，docs/plan/npu-probe-single-point/）：dispatcher 归位
# 到只依赖 {L3,L4,L7}，全部跨层违例真实上移/下沉，无一豁免。此后任何新违例即红
# （test_known_violations_still_exist 断言 KNOWN 为空——防回潮，勿再添加豁免）。
KNOWN: Set[str] = set()


def _collect_source_files() -> List[Path]:
    files: List[Path] = []
    for root, dirs, filenames in os.walk(SRC):
        dirs[:] = [d for d in dirs if not d.startswith("_") or d == "__pycache__"]
        for fn in filenames:
            if fn.endswith(".py"):
                files.append(Path(root) / fn)
    return files


def _layer_of(filepath: Path) -> int | None:
    rel = filepath.relative_to(SRC)
    top = rel.parts[0]
    return LAYER_MAP.get(top)


def _target_layer(module_dotted: str) -> int | None:
    """ascendc_devkit.capabilities.agent.sdk_backend -> 5"""
    parts = module_dotted.split(".")
    if len(parts) >= 2 and parts[0] == "ascendc_devkit":
        return LAYER_MAP.get(parts[1])
    return None


def _extract_cross_layer_imports(filepath: Path) -> List[Tuple[int, str, int]]:
    """Return (src_layer, import_stmt, tgt_layer) for every cross-layer import."""
    try:
        tree = ast.parse(filepath.read_text(), filename=str(filepath))
    except SyntaxError:
        return []

    src_layer = _layer_of(filepath)
    if src_layer is None:
        return []

    results: List[Tuple[int, str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tgt = _target_layer(alias.name)
                if tgt is not None and tgt != src_layer and tgt not in ALLOWED.get(src_layer, set()):
                    results.append((src_layer, alias.name, tgt))
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith("ascendc_devkit"):
                tgt = _target_layer(node.module)
                if tgt is not None and tgt != src_layer and tgt not in ALLOWED.get(src_layer, set()):
                    results.append((src_layer, node.module, tgt))
    return results


def _build_violation_key(filepath: Path, src_layer: int, module: str, tgt_layer: int) -> str:
    rel = str(filepath.relative_to(SRC))
    return f"{rel} -> L{tgt_layer} {module}"


def test_no_cross_layer_violations():
    """Every .py file must only import from layers allowed by the architecture matrix."""
    violations: List[str] = []
    for fpath in sorted(_collect_source_files()):
        for src_layer, module, tgt_layer in _extract_cross_layer_imports(fpath):
            key = _build_violation_key(fpath, src_layer, module, tgt_layer)
            if key not in KNOWN:
                violations.append(key)

    if violations:
        msg = (
            f"\n{'='*70}\n"
            f"  LAYER DEPENDENCY VIOLATIONS DETECTED ({len(violations)} new)\n"
            f"{'='*70}\n\n"
        )
        for v in violations:
            msg += f"  {v}\n"
        msg += (
            f"\n  Allowed cross-layer imports:\n"
            f"    L1 -> L2, L4\n"
            f"    L2 -> L3, L4, L7\n"
            f"    L3 -> L4, L5, L6, L7\n"
            f"    L4 -> (none)\n"
            f"    L5 -> L4, L6, L7\n"
            f"    L6 -> L4, L7\n"
            f"    L7 -> (none)\n"
            f"\n  If this import is intentional, add it to KNOWN in\n"
            f"  tests/ut/test_layer_dependencies.py with a TODO comment.\n"
        )
        pytest.fail(msg)


def test_known_violations_still_exist():
    """Sanity check: known violations should still exist in the codebase.

    If this test fails because a violation was fixed, remove its entry from KNOWN.
    """
    all_current: Set[str] = set()
    for fpath in sorted(_collect_source_files()):
        for src_layer, module, tgt_layer in _extract_cross_layer_imports(fpath):
            all_current.add(_build_violation_key(fpath, src_layer, module, tgt_layer))

    still_present = KNOWN & all_current
    missing = KNOWN - all_current

    if missing:
        # Violation was fixed — this is good. Remove from KNOWN.
        msg = (
            f"\n  VIOLATIONS FIXED ({len(missing)} entries). Remove from KNOWN:\n\n"
        )
        for m in sorted(missing):
            msg += f"    \"{m}\",\n"
        msg += "\n  Copy these lines and replace the KNOWN set in test_layer_dependencies.py.\n"
        pytest.fail(msg)

    assert len(still_present) == len(KNOWN), (
        f"KNOWN has {len(KNOWN)} entries but only {len(still_present)} exist. "
        f"Update KNOWN."
    )


def test_dispatcher_imports_stay_on_application_seam():
    """KNOWN 清零终态（2026-09-03）：dispatcher(L2) 只经 application/domain/
    orchestration/infra 取能力，不再直连 L5 capabilities / L6 adapters。

    防回潮：dispatcher 是 god-object 收口后的组合边界——若未来又在 dispatcher
    顶层/函数内 import L5/L6，本测试即红。KNOWN==∅ 已由上层断言钉住，这是第二层
    防腐（直接断言 dispatcher 的 import 面，而非仅靠 KNOWN 空）。
    """
    fpath = SRC / "application" / "dispatcher.py"
    import ast as _ast
    tree = _ast.parse(fpath.read_text(), filename=str(fpath))
    allowed = {"ascendc_devkit.application", "ascendc_devkit.domain",
               "ascendc_devkit.orchestration", "ascendc_devkit.infra"}
    offenders = []
    for node in _ast.walk(tree):
        if isinstance(node, _ast.ImportFrom) and node.module and \
                node.module.startswith("ascendc_devkit"):
            top = ".".join(node.module.split(".")[:2])
            if top not in allowed:
                offenders.append(f"{node.lineno}: {node.module}")
    assert not offenders, (
        "dispatcher 不得 import L5/L6（KNOWN 清零终态，防回潮）：\n  "
        + "\n  ".join(sorted(set(offenders))))
