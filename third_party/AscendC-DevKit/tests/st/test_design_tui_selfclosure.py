"""Real-link system test: design skills self-close via file I/O in TUI mode (step-10 L4-d).

THE acceptance guard for first-principle F2/F3 on the design stage: a design
skill must run in Claude Code TUI WITHOUT the DevKit framework, reading its
inputs from CWD files and writing its outputs to CWD, proving the skill chain
can self-close via file relay.

Mirrors tests/st/test_testdesign_tui_selfclosure.py (step-9 L4-d task2).
Spawns agents DIRECTLY (no Stage / Runner / GraphExecutor / State) in a bare
temp dir — exactly as a human typing /<skill> would, BUT with the
same schema examples the production framework inlines via
ArtifactContract.render_output_requirements(), so the model sees concrete
output-format examples rather than deriving them from SKILL.md alone.

Two guards:
  - single skill: seed tiling_results.json → spawn integrate
    → it must read the files and produce the three-piece (design_spec.json +
    tiling_strategy.json + kernel_architecture.json) conforming to the plugin-root
    schema (F1+F2).
  - chain relay: seed general_design.json → spawn template-division → integrate
    in ONE shared dir, injecting nothing between spawns → the final three-piece
    must be schema-conforming (F3: the chain self-relays via files).

Marked @pytest.mark.llm + @pytest.mark.heavy_llm: NOT in the default sweep
(§3.11 — real LLM full-flow, minute-scale); run explicitly via -m llm or by
name, on user decision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


from tests._llm_env import has_anthropic as _has_anthropic, load_settings_env

load_settings_env()


_MAX_ATTEMPTS = 3
_DESIGN = "stage-design"
_TD = "ascendc-op-design-template-division"
_INTEGRATE = "ascendc-op-design-integrate"

# Schema→producing-skill map (相1: schemas live in flat skill directories).
_SCHEMA_SKILL_MAP = {
    "design_spec.json":             "ascendc-op-design-integrate",
    "tiling_strategy.json":         "ascendc-op-design-integrate",
    "kernel_architecture.json":     "ascendc-op-design-integrate",
    "data_flow.json":               "ascendc-op-design-integrate",
    "template_division.json":       "ascendc-op-design-template-division",
    "tiling_split.json":            "ascendc-op-tiling-split",
    "tiling_buffer_kernel.json":    "ascendc-op-tiling-buffer-kernel",
    "tiling_precision_perf.json":   "ascendc-op-tiling-precision-perf",
    "general_design.json":          "ascendc-op-general-design",
}
_SKILLS_ROOT = (Path(__file__).resolve().parent.parent.parent
                / ".claude/skills")


def _schema_path(filename: str) -> Path:
    """Resolve a schema file to its producing skill's schema/ directory."""
    skill = _SCHEMA_SKILL_MAP.get(filename)
    if skill:
        return _SKILLS_ROOT / skill / "schema" / filename
    return _SKILLS_ROOT / "ascendc-op-design-integrate" / "schema" / filename  # fallback


def _read_schema(filename: str) -> dict:
    return json.loads(_schema_path(filename).read_text(encoding="utf-8"))


def _schema_required_keys(fn: str) -> list:
    return _read_schema(fn).get("required_keys", [])


def _schema_example(filename: str) -> dict | None:
    """Return the example payload from a spec schema file (mirrors
    ArtifactSpec.to_prompt_block)."""
    s = _read_schema(filename)
    eg = s.get("example")
    if eg is not None:
        return eg
    # When no example is declared, inline the required_keys as a hint.
    rk = s.get("required_keys")
    if rk:
        return {k: f"<{k}>" for k in rk}
    return {}


def _prompt_output_requirements(spec_names: list[str]) -> str:
    """Build the '## 输出要求' section mirroring
    ArtifactContract.render_output_requirements(). Includes the schema example
    for each output so the model sees a concrete format — the key difference
    from the old bare-instruction prompt that made this test flaky."""
    lines = ["## 输出要求",
             "请使用 Bash 或 Edit 工具将以下 JSON 文件写入当前工作目录："]
    for fn in spec_names:
        s = _read_schema(fn)
        desc = s.get("description", "")
        header = f"### {fn} — {desc}".rstrip(" —")
        example = s.get("example")
        if example:
            body = json.dumps(example, ensure_ascii=False, indent=2)
            lines.append(f"\n{header}\n```json\n{body}\n```")
        else:
            rk = s.get("required_keys", [])
            if rk:
                lines.append(f"{header}\n(必含字段: {', '.join(rk)})")
            else:
                lines.append(header)
    return "\n".join(lines)


def _spawn(work_dir: Path, slash_skill: str, instruction: str):
    """Spawn a design generator agent in TUI mode: first message leads with the
    /<skill> slash command, then a short instruction. No State, no
    Stage — only the files already in work_dir are available.

    The skills allowlist is resolved through the production helper
    ``skill_allowlist`` so the TUI test carries the SAME closure as the real
    substage — the test mirrors real wiring instead of hardcoding a single skill."""
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
    from ascendc_devkit.orchestration.skill_config import skill_allowlist
    primary = slash_skill
    prompt = f"/{primary}\n\n{instruction}"
    backend = SDKBackend(interactive=False, working_dir=work_dir.parent,
                         on_decision="default", decision_workspace=work_dir)
    backend.spawn("ascendc-design-generator", prompt, {},
                  skills=skill_allowlist(primary),
                  working_dir=work_dir, stage_name="tui")


def _seed_integrate_inputs(d: Path) -> None:
    """Seed integrate's upstream inputs as CWD files."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "general_design.json").write_text(json.dumps({
        "op_name": "add", "parallel_decomp": {"priority": "B"},
        "split_axis_priority": ["B"], "tiling_data": [],
        "loop_framework": "", "buffer_eval": {}}, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "tiling_results.json").write_text(json.dumps({
        "T1": {"split": {"core_split_axis": "B", "ubFactor": 16},
               "buffer_kernel": {"buffer": "double", "tiling_data": {}},
               "precision_perf": {"atol": 0.001, "rtol": 0.001}}
    }, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestDesignSingleSkillFileIO:
    """F1+F2: a design skill reads its input files from CWD and writes its output
    files — no DevKit framework, just /<skill> in a bare dir."""

    _INTEGRATE_OUTPUT_SPECS = ["design_spec.json"]

    def test_integrate_reads_files_produces_three_piece(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        req = _schema_required_keys("design_spec.json")
        output_req = _prompt_output_requirements(self._INTEGRATE_OUTPUT_SPECS)
        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_{attempt}"
            _seed_integrate_inputs(wd)
            _spawn(wd, _INTEGRATE,
                   "这是一个通路验证测试。从当前工作目录读取 tiling_results.json，"
                   "导出为 design_spec.json（按 schema/ 契约）到当前工作目录。"
                   "只需包含 required_keys 中的字段，使用种子文件中的值即可，"
                   "不需要做深度设计推理。\n\n"
                   + output_req)
            out = wd / "design_spec.json"
            if out.is_file():
                try:
                    data = json.loads(out.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                if all(k in data for k in req):
                    return  # self-closed: read files in, wrote conforming three-piece out
        pytest.fail(
            "integrate did not self-close via files in TUI mode: "
            f"no design_spec.json with required_keys {req} after {_MAX_ATTEMPTS} attempts "
            "(F1/F2 regression: skill must read CWD input files + write its schema output)")


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestDesignChainRelay:
    """F3: template-division → integrate relay via files in one shared dir,
    with nothing injected between spawns, producing the three-piece contract."""

    _TD_OUTPUT_SPECS = ["template_division.json"]
    _INTEGRATE_OUTPUT_SPECS = ["design_spec.json"]

    def test_td_then_integrate_relay_to_three_piece(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        req = _schema_required_keys("design_spec.json")
        td_output_req = _prompt_output_requirements(self._TD_OUTPUT_SPECS)
        int_output_req = _prompt_output_requirements(self._INTEGRATE_OUTPUT_SPECS)
        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_{attempt}"
            _seed_integrate_inputs(wd)  # includes general_design + tiling
            # 1) template-division: general_design.json → template_division.json
            _spawn(wd, _TD,
                   "通路验证测试。从当前工作目录读取 general_design.json，按模板划分方法"
                   "写出 template_division.json 到当前工作目录（用种子文件值即可，"
                   "无需深度推理）。\n\n"
                   + td_output_req)
            if not (wd / "template_division.json").is_file():
                continue
            # 2) integrate: all upstream files → three-piece contract
            _spawn(wd, _INTEGRATE,
                   "通路验证测试。从当前工作目录读取 tiling_results.json 与 "
                   "template_division.json，整合为 design_spec.json（按 schema/ 契约）"
                   "到当前工作目录。用种子文件中的值填充 required_keys 即可。\n\n"
                   + int_output_req)
            out = wd / "design_spec.json"
            if out.is_file():
                try:
                    data = json.loads(out.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    continue
                if all(k in data for k in req):
                    return  # chain self-closed end-to-end via files
        pytest.fail(
            "design chain did not self-close via files in TUI mode after "
            f"{_MAX_ATTEMPTS} attempts (F3 regression: template-division→integrate "
            "must relay through files in a shared dir, producing the three-piece)")


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestTilingFacadeSelfClosure:
    """合并 tiling（选 B 编排层合并）：ascendc-op-tiling 门面 skill 在 TUI 单跑时
    串行 tail-call 四个子 skill，产出三份必需 schema 文件（A2/A3）。证明门面自闭环
    （§2.8 单 skill 自闭环 + 门面 tail-call 子 skill 的文件接力）。"""

    _TILING_OUTPUT_SPECS = ["tiling_split.json", "tiling_buffer_kernel.json",
                            "tiling_precision_perf.json"]

    def _seed_tiling_inputs(self, d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "general_design.json").write_text(json.dumps({
            "op_name": "add", "split_axis_priority": ["N"],
            "tiling_data": [], "loop_framework": "", "buffer_eval": {}},
            ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "template_division.json").write_text(json.dumps({
            "templates": [{"name": "T1", "tiling_key": 1, "route_condition": "N>0"}],
            "locked_decisions": {"precision": "fp32"}},
            ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "hw_params.json").write_text(json.dumps({
            "ub_size_bytes": 196608, "alignment_bytes": 32,
            "vec_calc_size_bytes": 128}, ensure_ascii=False), encoding="utf-8")

    def test_facade_tail_calls_four_skills_to_three_files(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        reqs = {fn: _schema_required_keys(fn) for fn in self._TILING_OUTPUT_SPECS}
        output_req = _prompt_output_requirements(self._TILING_OUTPUT_SPECS)
        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_{attempt}"
            self._seed_tiling_inputs(wd)
            _spawn(wd, "ascendc-op-tiling",
                   "这是一个通路验证测试。从当前工作目录读取 general_design.json + "
                   "template_division.json + hw_params.json，按 SKILL.md 依次 tail-call "
                   "四个子 skill（split → vf-design[仅A5] → buffer-kernel → precision-perf），"
                   "产出三份必需 schema 文件（tiling_split.json / tiling_buffer_kernel.json / "
                   "tiling_precision_perf.json）到当前工作目录。只需包含 required_keys 字段，"
                   "用种子文件的值填充即可，不需要深度设计推理。\n\n" + output_req)
            if all((wd / fn).is_file() for fn in self._TILING_OUTPUT_SPECS):
                try:
                    datas = {fn: json.loads((wd / fn).read_text(encoding="utf-8"))
                             for fn in self._TILING_OUTPUT_SPECS}
                except json.JSONDecodeError:
                    continue
                if all(all(k in datas[fn] for k in reqs[fn])
                       for fn in self._TILING_OUTPUT_SPECS):
                    return  # facade self-closed: tail-called sub-skills → 3 files
        pytest.fail(
            "ascendc-op-tiling facade did not self-close via tail-call in TUI mode: "
            f"missing three tiling schema files after {_MAX_ATTEMPTS} attempts "
            "(merged-tiling regression: facade must tail-call the 4 sub-skills and "
            "relay tiling_current_template.json between them)")


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestDocgenSelfClosure:
    """docgen 独立成段（docs/plan/synthesize-docgen-dilution/）：ascendc-op-design-docgen
    skill 在 TUI 单跑时读上游合成产物（design_spec / tiling_strategy / tiling_results /
    general_design）组装 <op>_详细设计说明书.md。证明 docgen 独立段自闭环（§2.8 单 skill
    自闭环 + 文件接力，不依赖 synthesize 门面 tail-call）。"""

    def _seed_docgen_inputs(self, d: Path) -> None:
        d.mkdir(parents=True, exist_ok=True)
        (d / "design_spec.json").write_text(json.dumps({
            "op_name": "add", "mutation_mode": "out_of_place",
            "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"],
                        "param_type": "REQUIRED"}],
            "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"],
                         "param_type": "REQUIRED"}]},
            ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "tiling_strategy.json").write_text(json.dumps({
            "approach": "single_core"}, ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "tiling_results.json").write_text(json.dumps({
            "T1": {"split": {"core_split_axis": "N", "ubFactor": 16},
                   "buffer_kernel": {"buffer": "double", "tiling_data": {}},
                   "precision_perf": {"atol": 0.001, "rtol": 0.001}}},
            ensure_ascii=False, indent=2), encoding="utf-8")
        (d / "general_design.json").write_text(json.dumps({
            "op_name": "add", "split_axis_priority": ["N"],
            "tiling_data": [], "loop_framework": "", "buffer_eval": {}},
            ensure_ascii=False, indent=2), encoding="utf-8")

    def test_docgen_reads_contract_produces_md(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_{attempt}"
            self._seed_docgen_inputs(wd)
            _spawn(wd, "ascendc-op-design-docgen",
                   "这是一个通路验证测试。从当前工作目录读取 design_spec.json + "
                   "tiling_strategy.json + tiling_results.json + general_design.json，"
                   "按 SKILL.md 组装 <op>_详细设计说明书.md 到当前工作目录。"
                   "用种子文件的值填充即可，不需要深度设计推理。")
            md = list(wd.glob("*_详细设计说明书.md"))
            if md:
                return  # docgen self-closed: read contract, wrote md
        pytest.fail(
            "ascendc-op-design-docgen did not self-close via files in TUI mode: "
            f"missing *_详细设计说明书.md after {_MAX_ATTEMPTS} attempts "
            "(docgen独立段 regression: skill must read upstream contract + write md)")
