"""Step 10 (cleanup): retire the legacy single ``target_chip`` field and the
``assume_chip`` probe-bypass — both superseded by the step-34 dual-field model
(``design_target_chip`` + ``runtime_target_chip``) and the bounded probe that
returns UNKNOWN instead of letting a caller declare a chip verbatim.

Per §1.4 (no backward compat) and §2.5 (single path), the superseded通路 is
deleted outright — only a from_snapshot pop-tolerance for old snapshot keys
remains (loading-time defense, not a compatibility shim). These tests enforce
that no production code path still references the retired names.
"""
from __future__ import annotations

import dataclasses
import inspect
from pathlib import Path

import ascendc_devkit
from ascendc_devkit.adapters.npu.detect import detect_chip_version
from ascendc_devkit.orchestration.kernel.state import State

_SRC_ROOT = Path(ascendc_devkit.__file__).resolve().parent


def _src_py_lines():
    for p in _SRC_ROOT.rglob("*.py"):
        # skip the dual-field names' own definitions region by line content only
        for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            yield p, lineno, line


def test_state_has_no_legacy_chip_fields():
    fields = {f.name for f in dataclasses.fields(State)}
    assert "target_chip" not in fields, "legacy single target_chip field must be gone"
    assert "assume_chip" not in fields, "retired assume_chip field must be gone"
    # the dual fields + confirmation marker remain (regression guard)
    assert {"design_target_chip", "runtime_target_chip",
            "cross_gen_confirmed"} <= fields


def test_detect_chip_version_has_no_assume_chip_parameter():
    params = inspect.signature(detect_chip_version).parameters
    assert "assume_chip" not in params, (
        "detect_chip_version must not carry the retired assume_chip bypass")


def test_no_legacy_chip_refs_in_src():
    """No production source references the retired names.

    Every ``target_chip`` occurrence must be the dual-field form (preceded by
    ``design_`` or ``runtime_``); ``assume_chip`` must not appear at all. The
    from_snapshot pop-tolerance is the sole sanctioned mention and lives in
    state.py as a ``data.pop(...)`` strip, which this scan still rejects — so
    that defense is expressed as a pop of a literal string, not a bare ident.
    """
    offenders: list[str] = []
    for p, lineno, line in _src_py_lines():
        # assume_chip: forbidden except as a quoted string literal — the only
        # sanctioned mention is the from_snapshot pop of the old snapshot key.
        if "assume_chip" in line:
            if '"assume_chip"' not in line and "'assume_chip'" not in line:
                offenders.append(f"{p.name}:{lineno}: {line.strip()}")
        # target_chip: only the dual-field forms (design_/runtime_) or a quoted
        # string literal (the pop key) are allowed.
        if "target_chip" in line:
            idx = 0
            while True:
                idx = line.find("target_chip", idx)
                if idx == -1:
                    break
                prefix = line[:idx]
                quoted = (prefix.endswith('"') or prefix.endswith("'"))
                if not (prefix.endswith("design_") or prefix.endswith("runtime_")
                        or quoted):
                    offenders.append(f"{p.name}:{lineno}: {line.strip()}")
                    break
                idx += len("target_chip")
    assert not offenders, "legacy chip refs remain:\n" + "\n".join(offenders)
