"""Real-link ST (P38): docgen skill self-closes via file I/O in TUI mode.

THE acceptance guard for P36 path Y: the docgen skill must run in Claude Code
TUI WITHOUT the DevKit framework, reading its JSON inputs from CWD and
assembling a v2.0 template-faithful 《<op>_详细设计说明书.md》 — proving the
LLM spawn path (P36) produces a template-faithful doc, not a JSON dump.

Mirrors tests/st/test_design_tui_selfclosure.py. Spawns the docgen skill
DIRECTLY (no Stage / Runner / GraphExecutor / State) in a bare temp dir.
Seeds the upstream JSON exactly as the orchestrator materializes via
_DesignSubstage._materialize_inputs, then asserts the produced md:
  - exists at <op>_详细设计说明书.md
  - carries the v2.0 chapter skeleton (关联需求/接口实现设计/总体设计/
    算子计算模板/维测设计/代码生成任务拆分表)
  - loads EACH template's kernel_pseudo_code (both T1/T2 tags land ⇒ no
    template dropped; 5 fn names present ⇒ no function omitted/summarized)
  - keeps each 4.x section independent (no "同 4.x" shorthand)
  - emits a mermaid flowchart TD (multi-template op ⇒ required by the skill)

heavy_llm by §3.11 (real LLM full-flow, minute-scale) — marked
@pytest.mark.llm + @pytest.mark.heavy_llm so `-m "not heavy_llm"` (the
default sweep per §3.6) excludes it; run only on explicit user decision.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


from tests._llm_env import has_anthropic as _has_anthropic, load_settings_env

load_settings_env()


_MAX_ATTEMPTS = 3
_DESIGN = "stage-design"
_DOCGEN = "ascendc-op-design-docgen"
_OP = "add"  # matches seed design_spec.op_name → expected md filename

# Per-template kernel tag: each template's kernel_pseudo_code body carries a
# distinct marker so the assertion can tell the two templates apart in the md
# (verifies BOTH landed, not just one dumped).
_T1_TAG = "T1_KERNEL_BODY"
_T2_TAG = "T2_KERNEL_BODY"

# v2.0 chapter skeleton markers (doc_template_v2.0.md headings).
_CHAPTER_MARKERS = ["关联需求", "接口实现设计", "总体设计",
                    "算子计算模板", "维测设计", "代码生成任务拆分表"]
# The 5 kernel functions the skill must load in full (no omission/summary).
_KERNEL_FNS = ["Init", "CopyIn", "Compute", "CopyOut", "MainLoop"]
# Forbidden shorthand proving 4.x sections are NOT independent.
_INDEP_VIOLATION = "同 4"
_MERMAID = "flowchart TD"

# §2.3 OpDef canonical form (this round's OpDef-hallucination fix). The docgen
# skill must render a REAL OpDef (builder chain + OP_ADD + real soc), not a
# fictional API. Canonical tokens must be present; hallucination tokens absent.
_OPDEF_CANONICAL_PRESENT = ["OP_ADD(", "this->Input(", ".ParamType(",
                            ".DataType(", "AddConfig("]
_OPDEF_HALLUCINATION_TOKENS = ["desc.Mut", "MutatableInputDesc",
                               "OutputAttrMapping", "ScalarValueType",
                               "<SOC_VERSION"]
# hw_params.chip_code seeded below → recipe renders AddConfig("ascend950", ...).
_OPDEF_REAL_SOC = "ascend950"

# TDR1 TilingData-struct guard (this round): docgen must render TilingData as
# plain C struct (POD) from split.tiling_data_fields[], NOT legacy CANN macros.
# Seeds an array field too — the case that tempts TILING_DATA_FIELD_DEF_ARR.
_TILINGDATA_LEGACY_MACROS = ["BEGIN_TILING_DATA_DEF", "TILING_DATA_FIELD_DEF",
                             "END_TILING_DATA_DEF", "REGISTER_TILING_DATA_CLASS"]


def _hw_params_json() -> dict:
    """Mirror what design_substages._materialize_run_context writes: hw params
    + chip_code/soc_version (the sanctioned chip channel for design skills)."""
    return {"ub_size_bytes": 253952, "ai_core_cnt": 20, "alignment_bytes": 32,
            "chip_code": "A5", "soc_version": "ascend950"}


def _spawn(work_dir: Path, slash_skill: str, instruction: str):
    """Spawn the docgen skill in TUI mode: first message leads with the
    /<skill> bare slash command, then a short instruction. No State,
    no Stage — only the files already in work_dir are available."""
    from ascendc_devkit.capabilities.agent.sdk_backend import SDKBackend
    from ascendc_devkit.orchestration.skill_config import skill_allowlist
    primary = slash_skill
    prompt = f"/{primary}\n\n{instruction}"
    backend = SDKBackend(interactive=False, working_dir=work_dir.parent,
                         on_decision="default", decision_workspace=work_dir)
    backend.spawn("ascendc-design-generator", prompt, {},
                  skills=skill_allowlist(primary),
                  working_dir=work_dir, stage_name="tui")


def _seed_docgen_inputs(d: Path) -> None:
    """Seed docgen's upstream inputs as CWD JSON files (mirrors what the
    orchestrator materializes via _DesignSubstage._materialize_inputs)."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "design_spec.json").write_text(json.dumps({
        "op_name": _OP,
        "inputs": [{"name": "x", "dtype": "fp16", "param_type": "REQUIRED"},
                   {"name": "bias", "dtype": "fp16", "param_type": "OPTIONAL"}],
        "outputs": [{"name": "y", "dtype": "fp16", "param_type": "REQUIRED"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # hw_params.json carries chip_code/soc_version — the chip channel docgen
    # reads to render OpDef AddConfig (this round's fix; mirrors orchestration).
    (d / "hw_params.json").write_text(json.dumps(_hw_params_json(),
                                                 ensure_ascii=False, indent=2),
                                      encoding="utf-8")
    (d / "tiling_strategy.json").write_text(json.dumps({
        "approach": "multi_template",
        "tiling_keys": [{"key": 1, "route": "N>1024"},
                        {"key": 2, "route": "N<=1024"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    # 2 templates, each with a 5-fn kernel_pseudo_code carrying a DISTINCT tag
    # — the assertion checks BOTH tags land in the md (no template dropped) and
    # all 5 fn names appear (no function omitted/summarized).
    def _kernel(tag: str) -> dict:
        return {
            "init": f"void Init(...) {{ /*{tag}*/ }}",
            "copy_in": f"void CopyIn(...) {{ /*{tag}*/ }}",
            "compute": f"void Compute(...) {{ /*{tag}*/ }}",
            "copy_out": f"void CopyOut(...) {{ /*{tag}*/ }}",
            "main_loop": f"void MainLoop(...) {{ /*{tag}*/ }}",
        }

    (d / "tiling_results.json").write_text(json.dumps({
        "T1": {
            "split": {"core_split_axis": "N", "ubFactor": 16,
                      "tiling_data_fields": [
                          {"field": "totalNum", "dtype": "int64", "source": "shape product"},
                          {"field": "ubFactor", "dtype": "int64", "source": "UB tile size"},
                          {"field": "coreOffsets", "dtype": "int64[]",
                           "source": "per-core output offset", "length": "usedCores + 1"}]},
            "buffer_kernel": {"buffer": "double",
                              "kernel_pseudo_code": _kernel(_T1_TAG)},
            "precision_perf": {"atol": 0.001, "rtol": 0.001}},
        "T2": {
            "split": {"core_split_axis": "N", "ubFactor": 8,
                      "tiling_data_fields": [
                          {"field": "totalNum", "dtype": "int64", "source": "shape product"},
                          {"field": "ubFactor", "dtype": "int64", "source": "UB tile size"},
                          {"field": "coreOffsets", "dtype": "int64[]",
                           "source": "per-core output offset", "length": "usedCores + 1"}]},
            "buffer_kernel": {"buffer": "single",
                              "kernel_pseudo_code": _kernel(_T2_TAG)},
            "precision_perf": {"atol": 0.002, "rtol": 0.002}},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "general_design.json").write_text(json.dumps({
        "op_name": _OP,
        "split_axis_priority": ["N"],
        "tiling_data": [], "loop_framework": "", "buffer_eval": {},
        "关联需求": "需求链接占位（继承源）",
        "接口实现设计": "PTA: add(x) -> y（继承源）",
        "总体设计": "多模板路由（继承源）",
    }, ensure_ascii=False, indent=2), encoding="utf-8")


# A5 Regbase variant (P64/P88① vf-design render guard): a single-template op
# whose tiling_results carries a vf_design segment — docgen must render a
# VF编排设计 chapter from it (the consumer-side render gap this round closed).
_VF_OP = "rms_norm"
_VF_CHAPTER_MARKER = "VF编排"  # the section my docgen edit maps vf_design →
_VF_FNS = ["ComputeMeanSq", "ComputeRstd", "ComputeNormalize"]


def _seed_docgen_a5_inputs(d: Path) -> None:
    """Seed docgen's A5 inputs: one template carrying a vf_design segment (the
    new design product whose rendering this round added). docgen must surface it
    as a VF编排设计 chapter — proving the P88① consumer-side gap stays closed."""
    d.mkdir(parents=True, exist_ok=True)
    (d / "design_spec.json").write_text(json.dumps({
        "op_name": _VF_OP,
        "inputs": [{"name": "x", "dtype": "fp16"},
                   {"name": "gamma", "dtype": "fp16"}],
        "outputs": [{"name": "y", "dtype": "fp16"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "tiling_strategy.json").write_text(json.dumps({
        "approach": "single_template",
        "tiling_keys": [{"key": 1, "route": "default"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    vfs = [
        {"name": fn,
         "function_signature": f"__aicore__ inline void {fn}(LocalTensor<half>& x)",
         "interface_params": {"inputs": ["x"], "outputs": ["out"]}}
        for fn in _VF_FNS
    ]
    (d / "tiling_results.json").write_text(json.dumps({
        "T1": {
            "split": {"core_split_axis": "M", "ubFactor": 128},
            "vf_design": {
                "pattern": 4, "pattern_name": "三VF全流水",
                "vf_count": 3, "has_dependency": True, "loop_count": 1,
                "rationale": "RmsNorm reduce 聚合边界 → rstd → normalize",
                "vfs": vfs,
                "data_flow": "copy_in → ComputeMeanSq → ComputeRstd → ComputeNormalize → copy_out",
            },
            "buffer_kernel": {
                "buffer": "double",
                "kernel_pseudo_code": {
                    "init": "void Init(...) {}",
                    "copy_in": "void CopyIn(...) {}",
                    "compute": ("void Compute(...) { VF_CALL(ComputeMeanSq); "
                                "VF_CALL(ComputeRstd); VF_CALL(ComputeNormalize); }"),
                    "copy_out": "void CopyOut(...) {}",
                    "main_loop": "void MainLoop(...) {}",
                }},
            "precision_perf": {"atol": 0.001, "rtol": 0.001}},
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (d / "general_design.json").write_text(json.dumps({
        "op_name": _VF_OP,
        "split_axis_priority": ["M"],
        "tiling_data": [], "loop_framework": "rms_norm", "buffer_eval": {},
    }, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.mark.llm
@pytest.mark.heavy_llm
class TestDocgenTuiSelfclosure:
    """P38: docgen skill reads CWD JSON inputs and writes a v2.0 template-faithful
    <op>_详细设计说明书.md via TUI — no DevKit framework, just the skill."""

    def test_docgen_assembles_template_faithful_md(self, tmp_path):
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        instruction = (
            "通路验证测试。从当前工作目录读取 design_spec.json / tiling_strategy.json / "
            "tiling_results.json / general_design.json / hw_params.json，按自带 doc_template_v2.0.md 模板"
            f"组装为《{_OP}_详细设计说明书.md》写入当前工作目录。要求：各模板 Kernel 伪码"
            "全量装载（Init/CopyIn/Compute/CopyOut/MainLoop 全保留，禁止摘要/省略）；多模板"
            "算子第 3 章须含 mermaid 计算流程图（flowchart TD）；各 4.x 节独立完整。"
            "§2.3 算子信息库须渲染真实 OpDef：按知识库《OpDef渲染规格映射》从 design_spec 的"
            "inputs/outputs/param_type 套 builder 链（.Input/.ParamType/.DataType/.Format），"
            "attr 套 .Float/.Int，chip 取 hw_params.json.chip_code 经 to_soc_version 渲染 AddConfig，"
            "末尾 OP_ADD——禁虚构 API、禁 <占位> soc。TilingData 设计章节按 tiling_results 各模板 "
            "split.tiling_data_fields 渲染为 plain C struct（标量 `dtype field;`、数组 "
            "`dtype field[length];`），禁用 BEGIN_TILING_DATA_DEF 等 CANN 旧宏。")
        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_{attempt}"
            _seed_docgen_inputs(wd)
            _spawn(wd, _DOCGEN, instruction)
            md = wd / f"{_OP}_详细设计说明书.md"
            if not md.is_file():
                continue
            text = md.read_text(encoding="utf-8")
            # 1) v2.0 chapter skeleton present (guards against a JSON dump)
            if any(m not in text for m in _CHAPTER_MARKERS):
                continue
            # 2) BOTH templates' kernel bodies landed (no template dropped)
            if _T1_TAG not in text or _T2_TAG not in text:
                continue
            # 3) all 5 kernel fns present (no function omitted/summarized)
            if any(fn not in text for fn in _KERNEL_FNS):
                continue
            # 4) each 4.x section independent (no "同 4.x" shorthand)
            if _INDEP_VIOLATION in text:
                continue
            # 5) multi-template op ⇒ mermaid flowchart TD present
            if _MERMAID not in text:
                continue
            # 6) §2.3 OpDef canonical (this round's hallucination fix): real
            # builder chain + OP_ADD + real soc, no fictional API / placeholder.
            if any(t not in text for t in _OPDEF_CANONICAL_PRESENT):
                continue
            if any(t in text for t in _OPDEF_HALLUCINATION_TOKENS):
                continue
            if _OPDEF_REAL_SOC not in text:
                continue
            # 7) TilingData rendered as plain C struct, NOT legacy CANN macros (TDR1)
            if any(m in text for m in _TILINGDATA_LEGACY_MACROS):
                continue
            if "struct" not in text or "TilingData" not in text:
                continue
            return  # template-faithful doc self-closed via files in TUI
        pytest.fail(
            "docgen did not self-close a template-faithful md in TUI mode after "
            f"{_MAX_ATTEMPTS} attempts (P38 regression: skill must read CWD JSON + "
            "assemble v2.0 template-faithful md with full kernel load + mermaid + "
            "canonical §2.3 OpDef — no fictional API / placeholder soc — + plain C "
            "struct TilingData, no legacy macros)")

    def test_docgen_renders_vf_design_chapter_a5(self, tmp_path):
        """P88① §3.9 guard: docgen renders a VF编排设计 chapter from an A5
        template's vf_design segment (the consumer-side render gap this round
        closed). Proves my docgen SKILL.md edit (vf_design 段 → VF编排设计 节)
        actually takes effect via a real LLM, not just structurally."""
        if not _has_anthropic():
            pytest.skip("Anthropic not configured")
        instruction = (
            "通路验证测试。从当前工作目录读取 design_spec.json / tiling_strategy.json / "
            "tiling_results.json / general_design.json，按自带 doc_template_v2.0.md 模板"
            f"组装为《{_VF_OP}_详细设计说明书.md》写入当前工作目录。注意：模板 T1 含 vf_design "
            "段（A5 Regbase），须在文档中渲染 VF 编排设计章节；Kernel 伪码全量装载。")
        for attempt in range(_MAX_ATTEMPTS):
            wd = tmp_path / f"ws_a5_{attempt}"
            _seed_docgen_a5_inputs(wd)
            _spawn(wd, _DOCGEN, instruction)
            md = wd / f"{_VF_OP}_详细设计说明书.md"
            if not md.is_file():
                continue
            text = md.read_text(encoding="utf-8")
            # 1) VF编排 chapter rendered from the vf_design segment
            if _VF_CHAPTER_MARKER not in text:
                continue
            # 2) at least one VF function name from the seed landed (content, not title)
            if not any(fn in text for fn in _VF_FNS):
                continue
            # 3) chapter skeleton still intact (not a JSON dump)
            if any(m not in text for m in _CHAPTER_MARKERS):
                continue
            return
        pytest.fail(
            "docgen did not render a VF编排设计 chapter from the A5 vf_design "
            f"segment across {_MAX_ATTEMPTS} attempts (P88① regression: the "
            "consumer-side render gap this round closed has reopened)")
