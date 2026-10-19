"""Data-flow (c) re-injection: rebuild State fields from materialized design
products (step-8 §P1 task 5.3).

The orchestration materializes each design substage's product to a stable,
template-isolated path under ``artifacts/design/`` (the deterministic projection
of State). This module is the inverse: read those files back and reconstruct the
``provides`` State fields, so a single stage can be debugged by editing a product
file on disk and re-running (``stage run --name anchor-consistency --sources <dir>``).

Reuses each Stage's ``artifact_contract().parse()`` (no re-implemented parsing),
keyed by the §P1 映射表 (materialized path ⇄ provides field).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path


def load_authoritative_requirement(state) -> dict | None:
    """Load the authoritative, agent-produced ``requirement.json`` from the
    workspace artifacts dir (``artifacts/requirement/requirement.json``).

    Why the raw file and not ``state.requirement.op_spec``: ``OperatorSpec`` is a
    Python projection that models only tensors + attrs — it has **no**
    ``mutation_mode`` field and its ``TensorSpec`` drops ``shape_formula`` /
    output ``dtype_derivation``. Consumers that need those design-time facts (the
    in-place reconcile, the codegen "需求权威源" contract) must read the raw
    ``requirement.json``, which carries them verbatim. (Since the §1.10 fix to
    ``OperatorSpec.from_dict._route``, op_spec no longer *loses* DYNAMIC/alias
    tensors — this loader is about the extra design-time fields op_spec never
    modeled, not about working around a lossy tensor projection.)

    Reading a prior stage's artifact from the canonical workspace store is the
    same cross-stage pattern this module already embodies (§2.5 single pathway) —
    not a hardcoded path. Returns the parsed ``requirement`` sub-dict (or the
    whole dict when flat), or ``None`` when unavailable — callers treat ``None``
    as a requirement-chain break (warn + 不落 reduced, §3.12), never as a valid
    reduced fallback.
    """
    ws = getattr(state, "_workspace", None)
    artifacts = getattr(ws, "artifacts", None)
    if artifacts is None:
        return None
    path = artifacts / "requirement" / "requirement.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data.get("requirement", data) if "requirement" in data else data


def materialize_authoritative_requirement(state, dst: Path) -> bool:
    """Copy the FULL on-disk ``requirement.json`` to ``dst``, verbatim.

    The single shared reach-back for every stage that must deliver the
    *authoritative* requirement to an agent's cwd (general-design review gate,
    codegen). ``asdict(state.requirement)`` is rejected: the reduced
    ``Requirement`` dataclass drops ``math_formula`` / ``mutation_mode`` /
    ``shape_formula`` / ``golden_alignment`` and re-wraps into a non-flat
    ``{op_spec: {...}}`` shape — materializing that would deliver a spec that
    contradicts what the consuming SKILL promises is present (§2.3 I/O 契约诚实).

    Returns ``True`` when ``dst`` was written from the authoritative source (the
    canonical file copied whole, or — canonical path absent but a flat dict was
    parseable — the full flat dict written back). Returns ``False`` when no
    authoritative source is reachable (no ``_workspace`` / file missing).

    Callers MUST NOT fall back to the reduced dataclass serialization on
    ``False`` — §3.12: authoritative-missing is a requirement-chain break that
    must surface (warn + 不落 reduced / validate_inputs 拦截), never masquerade
    as a valid input.
    """
    req = load_authoritative_requirement(state)
    if req is None:
        return False
    ws = getattr(state, "_workspace", None)
    artifacts = getattr(ws, "artifacts", None)
    src = (artifacts / "requirement" / "requirement.json"
           if artifacts is not None else None)
    dst = Path(dst)
    if src is not None and src.exists():
        shutil.copyfile(src, dst)  # full verbatim file (math_formula 等齐全)
    else:
        # load_authoritative_requirement succeeded via a flat dict but the
        # canonical path is absent — write the parsed authoritative dict back
        # (still the full form, not the reduced dataclass).
        dst.write_text(json.dumps(req, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    return True


def _parse_one(stage, artifacts_dir: Path, subdir: str) -> dict:
    """Parse a non-tiling substage's products from design/<subdir>/.

    Returns the {artifact_name: payload} dict parsed by the stage's contract;
    empty when the directory is absent or holds nothing the contract recognizes.
    """
    d = artifacts_dir / subdir
    if not d.is_dir():
        return {}
    raw: dict[str, str] = {}
    for f in d.glob("*.json"):
        try:
            raw[f.name] = f.read_text(encoding="utf-8")
        except OSError:
            continue
    parsed, _ = stage.artifact_contract().parse(raw)
    return parsed


def _rebuild_tiling_results(artifacts_dir: Path) -> dict:
    """Rebuild tiling_results[{template}][{segment_key}] from
    design/tiling/<template>/tiling_*.json (the per-template isolated paths)."""
    from ascendc_devkit.orchestration.stages.design_substages import (
        TilingStage, _TILING_SEGMENTS,
    )
    tiling_dir = artifacts_dir / "design" / "tiling"
    if not tiling_dir.is_dir():
        return {}
    contract = TilingStage().artifact_contract()
    results: dict[str, dict] = {}
    for tmpl_dir in sorted(p for p in tiling_dir.iterdir() if p.is_dir()):
        tmpl = tmpl_dir.name
        raw: dict = {}
        for _sub, fname, _key, _req in _TILING_SEGMENTS:
            f = tmpl_dir / fname
            if not f.is_file():
                continue
            try:
                raw[fname] = f.read_text(encoding="utf-8")
            except OSError:
                continue
        if not raw:
            continue
        # 用完整 4-spec contract parse；partial 模板缺 required 文件时 parse 会报
        # errors 但仍返回已解析 payload（parse 契约：成功解析的即使有 schema 错误
        # 也返回）。只取已产出的段，容忍中断/partial 状态。
        parsed, _ = contract.parse(raw)
        entry: dict = {}
        for _sub, fname, seg_key, _req in _TILING_SEGMENTS:
            spec_name = fname[:-len(".json")]
            payload = parsed.get(spec_name)
            if isinstance(payload, dict) and seg_key in payload:
                entry[seg_key] = payload[seg_key]
        if entry:
            results[tmpl] = entry
    return results


def design_artifacts_to_state(artifacts_dir: Path | str) -> dict:
    """Reconstruct design-related State fields from a run's materialized
    products under ``artifacts_dir`` (the run's ``artifacts/`` directory).

    Returns ``{field: value}`` for every product found, following the §P1
    映射表. Missing products are simply absent from the result (a partial
    re-injection is valid — debug one stage by supplying only its inputs).
    Each substage's own ``artifact_contract().parse()`` does the parsing, so the
    schema stays single-sourced.
    """
    from ascendc_devkit.orchestration.stages.design_substages import (
        GeneralDesignStage, TemplateDivisionStage, SynthesizeStage,
    )
    artifacts_dir = Path(artifacts_dir)
    out: dict = {}

    # 1:1 substages (subdir under design/ == stage.name; payload name == field).
    simple = [
        (GeneralDesignStage(), "general-design-generator", [
            ("general_design", "general_design"),
            ("template_decision", "template_decision")]),
        (TemplateDivisionStage(), "template-division",
         [("template_division", "template_division")]),
        (SynthesizeStage(), "synthesize", [
            ("design_spec", "design_spec"),
            ("tiling_strategy", "tiling_strategy"),
            ("data_flow", "data_flow"),
        ]),
    ]
    for stage, subdir, fields in simple:
        parsed = _parse_one(stage, artifacts_dir / "design", subdir)
        for payload_name, field in fields:
            if payload_name in parsed:
                out[field] = parsed[payload_name]

    # tiling fork-join: per-template subdirs → tiling_results.
    tiling = _rebuild_tiling_results(artifacts_dir)
    if tiling:
        out["tiling_results"] = tiling

    return out
