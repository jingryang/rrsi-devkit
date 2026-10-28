"""UT: codegen 域对质安全网 _emit_domain_gap_signal（docs/plan/design-math-claims-verification L4 V3 / F9）。

确定性（no-LLM）。判据：requirement(golden) 域 ⊆ design.support_domain；缺口 →
domain_gap_signal.json 写出且**不 halt**；无缺口 / 缺 requirement → 静默（不写信号、不崩）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.codegen import CodegenStage


def _write_req(staging: Path, perm_constraint: str = "any") -> None:
    staging.mkdir(parents=True, exist_ok=True)
    (staging / "requirement.json").write_text(
        json.dumps({
            "domain": {
                "inputs": [{"name": "x", "rank": {"min": 1, "max": 8}}],
                "attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": perm_constraint}}],
            }
        }),
        encoding="utf-8")


def _perm_design(constraint: str) -> dict:
    """设计 support_domain 完整声明（逐张量 rank + attr），与 requirement 同口径
    （F5：需求声明了某张量的 rank，设计缺该声明会被保守 flag）。"""
    return {"support_domain": {
        "inputs": [{"name": "x", "rank": {"min": 1, "max": 8}}],
        "attrs": [{"name": "perm", "domain": {"kind": "permutation", "constraint": constraint}}],
    }}


class TestCodegenDomainGapSignal:
    def test_gap_written_no_halt(self, tmp_path):
        """需求 perm:any + 设计 support_domain perm:cyclic_rotation → 写 domain_gap_signal.json（不 halt）。"""
        stage = CodegenStage()
        state = State(mode="new", design_spec=_perm_design("cyclic_rotation"))
        staging = tmp_path / "staging"
        _write_req(staging)
        stage._emit_domain_gap_signal(state, staging)
        sig = staging / "domain_gap_signal.json"
        assert sig.exists(), "域缺口应写 domain_gap_signal.json"
        data = json.loads(sig.read_text(encoding="utf-8"))
        assert any("perm" in g and "⊄" in g for g in data["gaps"]), data["gaps"]

    def test_full_domain_no_signal(self, tmp_path):
        """需求 perm:any + 设计 perm:any → 覆盖，不写信号。"""
        stage = CodegenStage()
        state = State(mode="new", design_spec=_perm_design("any"))
        staging = tmp_path / "staging"
        _write_req(staging)
        stage._emit_domain_gap_signal(state, staging)
        assert not (staging / "domain_gap_signal.json").exists()

    def test_missing_requirement_silent(self, tmp_path):
        """缺 requirement.json → 静默不崩、不写信号（安全网不阻断 codegen）。"""
        stage = CodegenStage()
        state = State(mode="new", design_spec={})
        staging = tmp_path / "empty"
        staging.mkdir(parents=True, exist_ok=True)
        stage._emit_domain_gap_signal(state, staging)  # 不应抛异常
        assert not (staging / "domain_gap_signal.json").exists()

    def test_req_without_domain_no_signal(self, tmp_path):
        """requirement.json 无结构化 domain 字段 → 需求侧未声明轴，跳过、不写信号。"""
        stage = CodegenStage()
        state = State(mode="new", design_spec={})
        staging = tmp_path / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "requirement.json").write_text(
            json.dumps({"op_name": "Transpose"}), encoding="utf-8")
        stage._emit_domain_gap_signal(state, staging)
        assert not (staging / "domain_gap_signal.json").exists()

    def test_malformed_design_rank_no_halt_signal(self, tmp_path):
        """design_spec.support_domain.rank 为 prose 字符串（gelu 场景）→ 不 halt、不抛异常、
        写「无法对质」信号文件（20260809-170202 gelu run 回归）。"""
        stage = CodegenStage()
        state = State(mode="new", design_spec={"support_domain": {
            "inputs": [{"name": "x", "rank": "0..8（任意 shape，逐元素等价）"}],
            "dtype": "fp16 / fp32 / bf16",
        }})
        staging = tmp_path / "staging"
        _write_req(staging)  # requirement 有结构化 rank
        stage._emit_domain_gap_signal(state, staging)  # 不应抛异常、不 halt
        sig = staging / "domain_gap_signal.json"
        assert sig.exists(), "设计 rank 无法对质应写信号文件"
        data = json.loads(sig.read_text(encoding="utf-8"))
        assert any("无法对质" in g for g in data["gaps"]), data["gaps"]

    def test_domain_gap_signal_injected_into_coder_prompt(self, tmp_path):
        """domain_gap_signal.json 缺口 → 注入 coder prompt（明确消费，非只写不读的静默信号）。"""
        stage = CodegenStage()
        staging = tmp_path / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        (staging / "domain_gap_signal.json").write_text(json.dumps({
            "gaps": ["rank: design support_domain.rank 非 {min,max} dict（实际 str），无法对质 — 保守按未覆盖 flag"],
            "source": "codegen domain-gap safety net"}), encoding="utf-8")
        state = State(mode="new", design_spec={})
        prompt = stage._build_codegen_prompt(state, 1, staging)
        assert "设计 support_domain 域缺口" in prompt
        assert "无法对质" in prompt
        assert "decision_log.json" in prompt  # 指引 coder 覆盖 golden 域并记录

    def test_domain_gap_no_signal_no_section(self, tmp_path):
        """无 domain_gap_signal.json → prompt 无缺口段。"""
        stage = CodegenStage()
        staging = tmp_path / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        state = State(mode="new", design_spec={})
        prompt = stage._build_codegen_prompt(state, 1, staging)
        assert "设计 support_domain 域缺口" not in prompt
