"""方案 F — diagnose resume 状态传递 UT。

diagnose 被杀/resume 后，需感知"当前真实状态"（自身进度 + 失败状态），而非从 round 1
重头认知 + 过时环境结论（docs/plan/diagnose-upstream-misattribution/02-l3-analysis.md 方案 F）。

守护：
  - _format_resume_status 无 _summary → "被杀未写进度"提示（引导先读 error_msg）。
  - _format_resume_status 有 _summary → "续跑"提示含 root_cause + 最近尝试。
  - _common_context 注入 resume_status（基类空，diagnose 非空）。
  - _phase_prompt 输出包含 resume_status 段。
  - 纯函数（不改 state）。
"""

from __future__ import annotations

import json
from pathlib import Path

from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.requirement import Requirement
from ascendc_devkit.domain.verification import DeployResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.precision_debug_substages import (
    DiagnoseSubstage, RunTestsSubstage,
)


def _state(tmp_path: Path, **overrides) -> State:
    defaults = dict(
        mode="new",
        op_identity=OperatorIdentity(
            spec=OperatorSpec(name="unique"),
            repo_root=tmp_path,
            op_dir=tmp_path / "op"),
        requirement=Requirement(op_spec=OperatorSpec(name="unique")),
        golden_path=Path("/tmp/golden.py"),
        golden_entry="unique",
        golden_input_type="torch",
        deploy_result=DeployResult(smoke_passed=True),
        design_target_chip="A2",
    )
    defaults.update(overrides)
    return State(**defaults)


def _write_diagnose_phase(state: State, summary: dict | None, tried: list | None = None) -> None:
    """写 diagnose round 后缀 phase json（_summary + fix_code_log）。"""
    from ascendc_devkit.orchestration.stages import precision_debug_substages as pds
    p = pds._phase_path(state, "precision_diagnose.json", round_suffix=True)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"diagnose_done": True, "fix_code_log": {"tried_fixes": tried or []}}
    if summary is not None:
        payload["_summary"] = summary
    p.write_text(json.dumps(payload), encoding="utf-8")


def _seed_control_with_diagnose_history(state: State) -> None:
    """写带 diagnose history 条目的 control.json（模拟 diagnose 曾跑过一轮）。"""
    from ascendc_devkit.orchestration.stages import precision_debug_substages as pds
    p = pds._control_path(state)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "status": "running",
        "history": [{"phase": "diagnose",
                     "content": {"failure_type": "precision"}}],
    }), encoding="utf-8")


class TestFormatResumeStatus:
    def test_no_summary_gives_no_progress_hint(self, tmp_path):
        """无 _summary 但 history 有 diagnose 条目（上轮跑过、本轮被杀太早没写进度）
        → 提示先读 error_msg 确认失败状态。"""
        s = DiagnoseSubstage()
        state = _state(tmp_path)
        _seed_control_with_diagnose_history(state)
        status = s._format_resume_status(state)
        assert "被杀" in status or "未写进度" in status
        assert "error_msg" in status  # 引导读失败证据

    def test_true_first_round_no_resume_section(self, tmp_path):
        """§weak-model D：真首轮（无 _summary 且 history 无 diagnose 条目）→ 不注入
        "被杀"提示——框架事实不能错（首轮没有"上次被杀"），否则误导模型自我怀疑。
        heavy 实证：首次 spawn 的 prompt 曾含「你上次可能正在定位中途被杀」。"""
        s = DiagnoseSubstage()
        state = _state(tmp_path)
        assert s._format_resume_status(state) == ""

    def test_with_summary_gives_continue_hint(self, tmp_path):
        """有 _summary（上次已写进度）→ 续跑提示含 root_cause + 最近尝试。"""
        s = DiagnoseSubstage()
        state = _state(tmp_path)
        _write_diagnose_phase(
            state,
            summary={"symptom": "507035 crash", "root_cause": "ShiftF32 unaligned Duplicate"},
            tried=[{"fix_desc": "ShiftF32 scalar loop", "result": "succeeded"}],
        )
        status = s._format_resume_status(state)
        assert "续跑" in status or "Resume" in status
        assert "ShiftF32" in status  # root_cause 摘要
        assert "ShiftF32 scalar loop" in status  # 最近尝试

    def test_with_summary_empty_tried(self, tmp_path):
        """有 _summary 但无 tried_fixes → 不报错，root_cause 仍在。"""
        s = DiagnoseSubstage()
        state = _state(tmp_path)
        _write_diagnose_phase(
            state,
            summary={"root_cause": "some bug"},
            tried=[],
        )
        status = s._format_resume_status(state)
        assert "some bug" in status

    def test_pure_function_no_mutation(self, tmp_path):
        """_format_resume_status 不改 state（纯读）。"""
        s = DiagnoseSubstage()
        state = _state(tmp_path)
        before = state._debug_checkpoint
        s._format_resume_status(state)
        assert state._debug_checkpoint == before


class TestResumeStatusInjectedIntoContext:
    def test_diagnose_context_has_resume_status(self, tmp_path):
        """DiagnoseSubstage._common_context 注入 resume_status（非空或明确提示）。"""
        s = DiagnoseSubstage()
        state = _state(tmp_path)
        ctx = s._common_context(state)
        assert "resume_status" in ctx

    def test_diagnose_prompt_includes_resume_status(self, tmp_path):
        """_phase_prompt 输出包含 resume_status 段（§weak-model D 修正：构造真实续跑
        场景——上轮 diagnose 写过进度；真首轮不再注入，见上方新用例）。"""
        s = DiagnoseSubstage()
        state = _state(tmp_path)
        _seed_control_with_diagnose_history(state)
        _write_diagnose_phase(
            state, summary={"root_cause": "Cast RoundMode 错"})
        ctx = s._common_context(state)
        prompt = s._phase_prompt(ctx, str(ctx.get("operator_dir") or tmp_path),
                                 str(ctx.get("control_path") or tmp_path),
                                 str(ctx.get("phase_json_path") or tmp_path),
                                 str(ctx.get("skill_dir") or tmp_path), 1)
        assert "Resume 状态" in prompt or "resume" in prompt.lower() or "续跑" in prompt

    def test_run_tests_context_no_resume_status(self, tmp_path):
        """RunTestsSubstage 不注入 resume_status（基类空，通用性——只有 diagnose 需要 resume 感知）。"""
        s = RunTestsSubstage()
        state = _state(tmp_path)
        ctx = s._common_context(state)
        assert ctx.get("resume_status", "") == "" or "resume_status" not in ctx


class TestJudgmentOwnershipPrompt:
    """L4 阶段2（E-H）：判断决策权交还模型的 prompt 注入（框架层）。

    §judgment-ownership (P5)：diagnose/run_tests prompt 必须体现「判断决策权在模型」——
    diagnose 有假设纪律 + stalled 诚实报告；run_tests 有「路由判断在你」；
    diagnose 有「验证节奏由你定」。
    """

    def _diagnose_prompt(self, tmp_path):
        s = DiagnoseSubstage()
        state = _state(tmp_path)
        ctx = s._common_context(state)
        return s._phase_prompt(ctx, str(ctx.get("operator_dir") or tmp_path),
                               str(ctx.get("control_path") or tmp_path),
                               str(ctx.get("phase_json_path") or tmp_path),
                               str(ctx.get("skill_dir") or tmp_path), 1)

    def test_diagnose_prompt_has_hypothesis_discipline(self, tmp_path):
        """diagnose prompt 含假设纪律（predict 必填）——杜绝试错法。"""
        prompt = self._diagnose_prompt(tmp_path)
        assert "假设" in prompt and ("predict" in prompt or "预测" in prompt)

    def test_diagnose_prompt_has_stalled_report(self, tmp_path):
        """diagnose prompt 含 stalled 诚实报告（假设空间穷尽 → DIAGNOSED_STALLED）。"""
        prompt = self._diagnose_prompt(tmp_path)
        assert "stalled" in prompt and ("DIAGNOSED_STALLED" in prompt or "穷尽" in prompt)

    def test_diagnose_prompt_has_judgment_ownership(self, tmp_path):
        """diagnose prompt 含「判断决策权在你」——失败性质/打法由模型判断。"""
        prompt = self._diagnose_prompt(tmp_path)
        assert "判断决策权" in prompt or "判断权" in prompt or "由你判断" in prompt

    def test_diagnose_prompt_has_verify_rhythm(self, tmp_path):
        """diagnose prompt 含「验证节奏由你定」——算法级 bug 可改完一起验证。"""
        prompt = self._diagnose_prompt(tmp_path)
        assert "验证节奏" in prompt or "验证范围" in prompt

    def test_diagnose_prompt_upstream_first_tries_local_fix(self, tmp_path):
        """N2: diagnose prompt 的上游判据含「先尝试原地兜底，解决不了才上报」——
        上游问题不直接 halt，先看工程内能否就地修。"""
        prompt = self._diagnose_prompt(tmp_path)
        assert "先尝试原地兜底" in prompt or "先尝试" in prompt or "能修就修" in prompt
        assert "DIAGNOSE_UPSTREAM" in prompt, "上报路径仍存在（兜底解决不了才上报）"
