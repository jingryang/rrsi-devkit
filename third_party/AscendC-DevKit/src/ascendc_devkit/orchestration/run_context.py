"""L3 Orchestration — RunContext: frozen, run-invariant environment context.

P27 (single source of truth for run-invariant facts). A run computes this ONCE
(at the context stage) and every stage reads it directly via
``state.run_context`` — no per-stage ``_upstream_inputs`` declaration, which is
the "传递丢失" vector (a stage that forgets to declare a field silently loses
it, with no load-time check). The materialization layer auto-writes the
``hw_params`` slice into every design substage's working dir, so skills always
see hardware facts without per-stage wiring.

Three sections (user decision: build all three at once):
  - hardware_target : what we design FOR   (chip + hw_params from chip spec)
  - hardware_env    : what we run ON        (npu_id, detected chip, driver)
  - software_env    : what we run WITH      (CANN toolkit/version, python, torch_npu)

Hardware constants live ONLY in the chip spec JSON (ascend-hardware/references/
chips/*.json) — the single source. This loader reads them; nothing duplicates
them into skill prose (cures P24 drift: UB 192/240/248/256KB).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


# Canonical chip generation (A2/A3/A5) → chip-spec-file mapping. The canonical
# identity comes from ``domain.chip`` and flows through detect.py / profile
# default_chip / CLI --chip-version; this table points each generation at its
# spec family JSON (single source for hw_params, infra-level lookup — does not
# violate §1.5). Coverage is the 910 family only; other chips have no
# development scenario and were removed (their spec JSONs stay as ascend-hardware
# skill reference data).
_CHIP_SPEC_FILE = {
    "A2": "ascend_910b.json",     # Ascend910B / Atlas A2
    "A3": "ascend_910_93xx.json", # Ascend910C / Atlas A3
    "A5": "ascend_910_95xx.json", # David / 950 / Atlas 350
}

# Typical variant per generation — the mainstream SKU used for design-time
# perf estimate (bandwidth×cores throughput) when the caller does not name a
# sub-variant. Core counts here are estimates ONLY; block_dim MUST be
# runtime-derived via GetCoreNumAiv()/GetBlockNum() — a generation spans
# multiple core tiers (A5: 8/28/32/36), so any static core count breaks on a
# different SKU (P1, see docs/plan/blockdim-runtime-dynamic/). A2/A3 typical =
# 20-cube (entry tier happens to be mainstream); A5 typical = 9582 32-core, NOT
# the 8-core entry 950z which low-balled cores 4× (P2). Users targeting a
# specific sub-SKU name the variant explicitly.
_TYPICAL_VARIANT = {
    "A2": "910B3",     # Gen2 die, UB=192KB, 20-cube/40-vector
    "A3": "910_9362",  # 20-cube/40-vector
    "A5": "910_9582",  # 32-cube/64-vector (was entry 950z 8-core)
}


@dataclass(frozen=True)
class HardwareTarget:
    """Design target — the chip the operator is being designed FOR."""

    chip: str                       # canonical generation, e.g. "A2"/"A3"/"A5"
    variant: str = ""               # sub-variant if named, e.g. "910B3"
    # Flat hardware params from the chip spec (single source). Fields present
    # depend on the spec; consumers read via .get(). Key fields: ub_size_bytes,
    # l1_size_bytes, l2_size_bytes, vector_core_cnt, cube_core_cnt,
    # vec_calc_size_bytes, alignment_bytes.
    hw_params: dict = field(default_factory=dict)


@dataclass(frozen=True)
class HardwareEnvironment:
    """Current hardware — the NPU the run actually executes ON (may differ from
    target in cross-compile / pure-design scenarios; None then)."""

    # P69: npu_id is now a preferred/hint (State.npu_id may be None when the run
    # acquires cards per subprocess). Recorded for the diagnostic panel; not a
    # mechanism — the authoritative card is resolved once at the op boundary.
    npu_id: int | None = None
    detected_chip: str | None = None
    driver_version: str | None = None


@dataclass(frozen=True)
class SoftwareEnvironment:
    """Runtime software — CANN toolkit / language runtimes (None when not probed)."""

    cann_toolkit_path: str | None = None
    cann_version: str | None = None
    compiler: str | None = None
    python_version: str | None = None
    torch_npu_version: str | None = None


@dataclass(frozen=True)
class RunContext:
    """Frozen, run-invariant environment context. Populated once, never mutated."""

    hardware_target: HardwareTarget
    hardware_env: HardwareEnvironment | None = None
    software_env: SoftwareEnvironment | None = None


def _skills_root() -> Path:
    # src/ascendc_devkit/orchestration/run_context.py → parents[3] = project root
    return Path(__file__).resolve().parents[3] / ".claude" / "skills"


def _chip_spec_path(chip: str) -> Path:
    return (_skills_root() / "ascend-hardware"
            / "references" / "chips" / _CHIP_SPEC_FILE[chip])


def _extract_hw_params(spec: dict, chip: str, variant: str) -> dict:
    """Flatten chip-spec fields a design stage cross-checks against.

    Prefers a named/representative variant entry (flat fields), then falls back
    to shared sections. Robust to missing keys via .get().
    """
    params: dict = {}

    variants = spec.get("variants") or {}
    chosen = variant or _TYPICAL_VARIANT.get(chip, "")
    v = variants.get(chosen) if chosen else None
    if v is None and isinstance(variants, dict):
        # first non-comment variant entry
        for k, val in variants.items():
            if not k.startswith("_") and isinstance(val, dict):
                v = val
                break
    if v:
        for flat in ("ub_size_bytes", "l1_size_bytes", "l2_size_bytes",
                     "l0c_size_bytes", "vector_core_cnt", "cube_core_cnt",
                     "ai_core_cnt", "gm_size_bytes"):
            if v.get(flat) is not None:
                params[flat] = v[flat]

    shared = (spec.get("shared") or {})
    mem = shared.get("memory") or {}
    ub = mem.get("ub") or {}
    # Variant already gave the authoritative ub_size_bytes (gen-correct); only
    # fall back to shared if variant lacked it.
    params.setdefault("ub_size_bytes", ub.get("size_bytes_gen2") or ub.get("size_bytes"))
    vec = shared.get("vector_unit") or {}
    if vec.get("vec_calc_size_bytes") is not None:
        params["vec_calc_size_bytes"] = vec["vec_calc_size_bytes"]
    # 32B alignment is a platform constant recorded once here (not duplicated in
    # skills). Read from ubblock_size where available, else the universal 32B.
    params["alignment_bytes"] = ub.get("ubblock_size") or 32
    return params


def load_hw_params(chip: str, variant: str = "") -> dict:
    """Load flat hardware params for a chip from the chip spec (single source).

    Raises KeyError if the chip is not in the mapping (§3.7 honest error — do not
    silently fall back to a hardcoded constant, which is how P24 drift happened).
    """
    if chip not in _CHIP_SPEC_FILE:
        raise KeyError(
            f"chip_version {chip!r} has no chip-spec mapping; "
            f"known: {sorted(_CHIP_SPEC_FILE)}")
    path = _chip_spec_path(chip)
    if not path.is_file():
        raise FileNotFoundError(f"chip spec not found: {path}")
    with path.open(encoding="utf-8") as fh:
        spec = json.load(fh)
    return _extract_hw_params(spec, chip, variant)


def build_hardware_target(chip: str, variant: str = "") -> HardwareTarget:
    return HardwareTarget(chip=chip, variant=variant or _TYPICAL_VARIANT.get(chip, ""),
                          hw_params=load_hw_params(chip, variant))


def _probe_software_env() -> SoftwareEnvironment:
    """Best-effort runtime-software probe (guarded — never hard-fails the run).

    Reuses the same signals CannAdapter/verify_env read, so RunContext is the
    single read point downstream stages consult instead of each os.environ.get.
    """
    import os
    import platform
    import shutil
    toolkit = os.environ.get("ASCEND_TOOLKIT_HOME")
    compiler = next((shutil.which(s) for s in ("ccec", "c++") if shutil.which(s)), None)
    cann_version = None
    if toolkit:
        for part in Path(toolkit).parts:
            if part.startswith("cann-"):
                cann_version = part[len("cann-"):]
                break
    torch_npu_version = None
    try:
        import torch_npu  # type: ignore  # optional at runtime
        torch_npu_version = getattr(torch_npu, "__version__", None)
    except Exception:
        pass
    return SoftwareEnvironment(
        cann_toolkit_path=toolkit or None,
        cann_version=cann_version,
        compiler=compiler,
        python_version=platform.python_version(),
        torch_npu_version=torch_npu_version,
    )


def _probe_hardware_env(npu_id: int) -> HardwareEnvironment:
    """Best-effort current-hardware probe. detected_chip reuses npu/detect.py."""
    detected = None
    try:
        from ascendc_devkit.adapters.npu.detect import detect_chip_version
        detected = detect_chip_version()
    except Exception:
        detected = None
    return HardwareEnvironment(npu_id=npu_id, detected_chip=detected,
                               driver_version=None)


def build_run_context(chip: str, npu_id: int | None = None, variant: str = "") -> RunContext:
    """Assemble the full three-section RunContext. Called once at the context stage."""
    return RunContext(
        hardware_target=build_hardware_target(chip, variant),
        hardware_env=_probe_hardware_env(npu_id),
        software_env=_probe_software_env(),
    )


def run_context_from_dict(d):
    """Inverse of dataclasses.asdict — rebuild a frozen RunContext from the plain
    nested dict produced by State.to_snapshot, so attribute access survives resume.
    Pass-through when already a RunContext or None.
    """
    if d is None or isinstance(d, RunContext):
        return d

    def _section(cls, v):
        return cls(**v) if isinstance(v, dict) else v

    return RunContext(
        hardware_target=_section(HardwareTarget, d.get("hardware_target")),
        hardware_env=_section(HardwareEnvironment, d.get("hardware_env")),
        software_env=_section(SoftwareEnvironment, d.get("software_env")),
    )
