"""Real-link heavy_llm ST (P64 / P90②): vf-design skill self-closes via file I/O
in TUI mode — A5 Regbase VF orchestration design.

THE §3.9 acceptance guard for the vf-design skill's PRODUCER side (P64 闭环):
vf-design must run in Claude Code TUI WITHOUT the DevKit framework, reading its
A5 inputs from CWD files (requirement / general_design / template_division /
tiling_current_template / hw_params) and writing ``tiling_vf_design.json`` with
a valid vf_design payload — proving the migrated skill's decision-tree
methodology (公式展开 → 聚合边界 → 变量依赖 → 模式 1-5 → per-VF 函数接口) actually
produces a structured VF layout via a REAL LLM, not a stub.

Seed = RmsNorm (the skill's own running example in SKILL.md: x²→reduce→mean_sq,
rsqrt(+ε)→rstd, x*rstd*γ→y ⇒ a reduce aggregation boundary ⇒ multi-VF). The
assertions check STRUCTURAL conformance (§3.10 — bounded retry absorbs LLM
jitter on stable signals, does NOT hard-assert exact VF count):
  - tiling_vf_design.json exists with required_keys [template, vf_design]
  - vf_design.vf_count is an int ≥ 1 (RmsNorm ⇒ ≥ 2: aggregation boundary cuts)
  - vf_design.pattern present
  - vf_design.vfs is a non-empty list; each entry carries function_signature
    (a ``__aicore__ inline void Compute…``-style declaration) + interface_params

Mirrors tests/st/test_design_tui_selfclosure.py + test_design_docgen_tui_selfclosure.py
(seed files + bare TUI spawn, no Stage/Runner/State).

heavy_llm by §3.11 (real LLM full-flow, minute-scale) — marked @llm + @heavy_llm
so ``-m "not heavy_llm"`` (default sweep per §3.6) excludes it; run only on
explicit user decision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


from tests._llm_env import has_anthropic as _has_anthropic, load_settings_env

load_settings_env()


_SKILL = "ascendc-op-tiling-vf-design"
_SCHEMA_FILE = "tiling_vf_design.json"
_MAX_ATTEMPTS = 3

_SKILLS_ROOT = (Path(__file__).resolve().parent.parent.parent / ".claude/skills")


def _read_schema() -> dict:
    return json.loads((_SKILLS_ROOT / _SKILL / "schema" / _SCHEMA_FILE)
                      .read_text(encoding="utf-8"))


def _prompt_output_requirements() -> str:
    """Build the '## 输出要求' section mirroring
    ArtifactContract.render_output_requirements() — include the schema example so
    the model sees a concrete format (the key anti-flake lever, per
    test_design_tui_selfclosure)."""
    s = _read_schema()
    lines = ["## 输出要求",
             "请使用 Bash（cat）工具将以下 JSON 文件写入当前工作目录："]
    desc = s.get("description", "")
    header = f"### {_SCHEMA_FILE} — {desc}".rstrip(" —")
    example = s.get("example")
    if example:
        body = json.dumps(example, ensure_ascii=False, indent=2)
        lines.append(f"\n{header}\n```json\n{body}\n```")
    else:
        rk = s.get("required_keys", [])
        lines.append(f"{header}\n(必含字段: {', '.join(rk)})")
    return "\n".join(lines)


def _spawn(work_dir: Path, instruction: str):
    """Spawn vf-design via the design-generator agent in TUI mode: first message
    leads with /ascendc-op-tiling-vf-design, then the instruction. No State, no
    Stage — only the seeded CWD files are available. skills allowlist goes
    through the production ``skill_allowlist`` so it is wired identically to the
    real substage."""
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
    from ascendc_devkit.orchestration.skill_config import skill_allowlist
    prompt = f"/{_SKILL}\n\n{instruction}"
    backend = SDKBackend(interactive=False, working_dir=work_dir.parent,
                         on_decision="default", decision_workspace=work_dir)
    backend.spawn("ascendc-design-generator", prompt, {},
                  skills=skill_allowlist(_SKILL),
                  working_dir=work_dir, stage_name="vf-design")


def _seed_rmsnorm_a5(d: Path) -> None:
    """Seed vf-design's A5 inputs as CWD files. RmsNorm = the skill's own
    example (reduce aggregation boundary ⇒ multi-VF). Minimal-but-valid so the
    skill's decision tree has a real formula/structure to chew on."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "requirement.json").write_text(json.dumps({
        "op_name": "rstd_rms_norm",
        "op_spec": {
            "inputs": [{"name": "x", "dtype": "float16", "shape": ["M", "D"]},
                       {"name": "gamma", "dtype": "float16", "shape": ["D"]}],
            "outputs": [{"name": "y", "dtype": "float16", "shape": ["M", "D"]}],
            "attrs": [{"name": "eps", "type": "float", "default": 1e-6}],
        },
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # general_design.json — CR1-flattened (P87) + loop_framework + gradient_formula
    # (vf-design reads these two as the formula/structure source).
    (d / "general_design.json").write_text(json.dumps({
        "op_name": "rstd_rms_norm",
        "split_axis_priority": ["M"],
        "tiling_data": [{"name": "D", "type": "int"},
                        {"name": "ubFactor", "type": "int"}],
        "loop_framework": "对每行 m∈[0,M)：reduce_mean(x[m,:]^2) → rsqrt(+eps) → 逐元素归一化 * gamma",
        "buffer_eval": {"feasible": True},
        "gradient_formula": "rms = sqrt(mean(x^2) + eps); rstd = 1/rms; y = x * rstd * gamma",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "template_division.json").write_text(json.dumps({
        "templates": [{"name": "T1", "scope": "RmsNorm 主模板"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "tiling_current_template.json").write_text(json.dumps({
        "template": "T1",
        "split": {"loopCount": 1, "ubFactor": 128, "resident": ["gamma"]},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "hw_params.json").write_text(json.dumps({
        "platform": "A5", "ub_size_kb": 256,
    }, ensure_ascii=False, indent=2), encoding="utf-8")


def _validate_vf_design(payload: dict) -> None:
    """Structural assertions on the produced vf_design (§3.10 — stable signals)."""
    assert "template" in payload, "missing required_key: template"
    assert "vf_design" in payload, "missing required_key: vf_design"
    vf = payload["vf_design"]
    assert isinstance(vf, dict), f"vf_design not a dict: {type(vf)}"
    # vf_count: RmsNorm has a reduce aggregation boundary ⇒ must cut into ≥2 VF.
    fc = vf.get("vf_count")
    assert isinstance(fc, int) and fc >= 1, f"vf_count not int≥1: {fc!r}"
    assert vf.get("pattern"), f"pattern missing/empty: {vf.get('pattern')!r}"
    vfs = vf.get("vfs")
    assert isinstance(vfs, list) and len(vfs) >= 1, f"vfs not non-empty list: {vfs!r}"
    for i, v in enumerate(vfs):
        sig = v.get("function_signature") or v.get("function_signature_draft")
        assert sig and isinstance(sig, str) and ("void" in sig or "Compute" in sig), (
            f"vfs[{i}].function_signature not a RegBase void Compute decl: {sig!r}")
        assert v.get("interface_params"), f"vfs[{i}].interface_params missing"


@pytest.mark.llm
@pytest.mark.heavy_llm
def test_vf_design_skill_selfcloses_a5_rmsnorm(tmp_path):
    """P64 producer-side §3.9 guard: vf-design self-closes in TUI on an A5
    RmsNorm seed, producing a structurally-valid tiling_vf_design.json."""
    if not _has_anthropic():
        pytest.skip("Anthropic not configured")

    last_err = None
    for attempt in range(_MAX_ATTEMPTS):
        ws = tmp_path / f"ws_{attempt}"
        _seed_rmsnorm_a5(ws)
        instruction = (
            "目标芯片 A5（Regbase）。当前模板 T1（RmsNorm）。"
            "请按本 skill 的方法论完成 VF 编排设计，产出 tiling_vf_design.json。\n\n"
            + _prompt_output_requirements())
        try:
            _spawn(ws, instruction)
        except Exception as e:  # backend spawn error ≠ skill output error
            last_err = e
            continue
        out = ws / _SCHEMA_FILE
        if not out.exists():
            last_err = f"{_SCHEMA_FILE} not produced in {ws}"
            continue
        try:
            payload = json.loads(out.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            last_err = f"unparseable JSON: {e}"
            continue
        _validate_vf_design(payload)  # raises AssertionError if malformed
        return  # success

    pytest.fail(
        f"vf-design did not produce a valid {_SCHEMA_FILE} across {_MAX_ATTEMPTS} "
        f"attempts (P64 producer-side regression). last_err={last_err!r}")
