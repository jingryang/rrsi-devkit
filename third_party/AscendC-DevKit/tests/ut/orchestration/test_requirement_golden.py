"""P121: req-analysis 收 golden.py（shape 权威源物化）+ golden_alignment 强制。

真根因（advance_step_v2 9d6e61）：``RequirementStage._materialize_inputs`` 从不把
golden.py 写进 agent CWD，而 SKILL 早要求 agent 读 golden.py 做 math-equiv——agent
找不到文件 → 只能凭"标准语义"猜 shape（input_tokens 猜 2D，实际 1D）→ 一路 verbatim
传播到 codegen → harness 用 cases 1D 构造 → EZ1001 halt。机械层断裂（golden 没物化），
非缺自检。本组覆盖物化 + prompt 点名 + golden_alignment 杜绝 "pending"。
"""
import json
import tempfile
from pathlib import Path

from ascendc_devkit.capabilities.agent.backend import AgentResult
from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.requirement import RequirementStage

_STAGE = RequirementStage()


def _tmp_file(text: str, suffix: str) -> Path:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(text)
    f.close()
    return Path(f.name)


def _tmp_golden(text: str = "def op(x):\n    return x\n") -> Path:
    return _tmp_file(text, ".py")


# —— S1-物化：_materialize_inputs 写 golden.py（真根因修复）——

def test_materialize_writes_golden_py_when_present():
    """golden_path 提供 → _materialize_inputs 把 golden.py 写进 CWD（agent 终于能读）。"""
    golden = _tmp_golden("def advance_step(input_tokens, num_seqs):\n"
                         "    input_tokens[:num_seqs] = 0\n")
    state = State(mode="new", golden_path=golden)
    wd = Path(tempfile.mkdtemp())
    _STAGE._materialize_inputs(state, wd)
    assert (wd / "golden.py").exists()
    assert (wd / "golden.py").read_text(encoding="utf-8") == golden.read_text()


def test_materialize_preserves_golden_content_verbatim():
    """物化是文件拷贝，内容逐字节一致（不经过 JSON/转义）。"""
    body = "# complex golden with special chars: 中文 \\ ' \" \n view = x.view(-1, k)\n"
    golden = _tmp_golden(body)
    state = State(mode="new", golden_path=golden)
    wd = Path(tempfile.mkdtemp())
    _STAGE._materialize_inputs(state, wd)
    assert (wd / "golden.py").read_text(encoding="utf-8") == body


# —— S1-物化：_build_analysis_prompt 点名 golden.py ——

def test_prompt_names_golden_py_when_present():
    """golden_path 提供 → prompt 出现 `golden.py` 文件名 + shape rank 引导。"""
    state = State(mode="new", golden_path=_tmp_golden())
    prompt = _STAGE._build_analysis_prompt(state, 1)
    assert "golden.py" in prompt
    assert "shape rank" in prompt or "rank" in prompt


def test_prompt_omits_golden_section_when_absent():
    """无 golden_path → prompt 不含 Golden 段（防御：materialize/prompt 都跳过）。
    注：schema example 的 golden_alignment notes 可能含 'golden.py' 字样（输出格式
    示例始终渲染），故只断言 Golden 段头不出现，不断言子串。"""
    state = State(mode="new")
    prompt = _STAGE._build_analysis_prompt(state, 1)
    assert "## Golden 参考实现" not in prompt


# —— S1-校验：_validate_golden_alignment 单元 ——

def test_validator_rejects_pending():
    """status=pending（未检）→ 报错强制重试（advance_step_v2 真根因）。"""
    errors = _STAGE._validate_golden_alignment({"golden_alignment": {"status": "pending"}})
    assert len(errors) == 1
    assert "pending" in errors[0]


def test_validator_accepts_pass():
    assert _STAGE._validate_golden_alignment({"golden_alignment": {"status": "pass"}}) == []


def test_validator_accepts_diff():
    assert _STAGE._validate_golden_alignment(
        {"golden_alignment": {"status": "diff", "differences": ["math 略不同"]}}) == []


def test_validator_rejects_bogus_status():
    errors = _STAGE._validate_golden_alignment({"golden_alignment": {"status": "maybe"}})
    assert len(errors) == 1
    assert "pass|diff" in errors[0]


def test_validator_none_and_missing_deferred_to_required_keys():
    """缺失/None 由 required_keys 兜（parse 报）；validator 不重复报（职责分层）。"""
    assert _STAGE._validate_golden_alignment({"golden_alignment": None}) == []
    assert _STAGE._validate_golden_alignment({}) == []
    assert _STAGE._validate_golden_alignment(None) == []
    assert _STAGE._validate_golden_alignment("str") == []


def test_validator_non_dict_value_rejected():
    """present 但非对象（malformed）→ 报（可诊断：不静默放行畸形值）。"""
    errors = _STAGE._validate_golden_alignment({"golden_alignment": "not an object"})
    assert len(errors) == 1
    assert "对象" in errors[0]


# —— S1-校验：transition 集成（parse required_keys + validator 串联）——

def _req_artifact(golden_alignment=None, omit_golden_alignment=False,
                  mutation_mode="out_of_place"):
    req = {
        "op_name": "op",
        "aclnn_name": "aclnnOp",
        "mutation_mode": mutation_mode,
        "inputs": [{"name": "x", "dtype": "fp16", "shape": ["N"]}],
        "outputs": [{"name": "y", "dtype": "fp16", "shape": ["N"]}],
    }
    if not omit_golden_alignment:
        req["golden_alignment"] = golden_alignment or {"status": "pass"}
    return {"requirement.json": json.dumps(req)}


def _req_state():
    return State(mode="new",
                 requirement_path=_tmp_file("operator:\n  name: op\n", ".md"),
                 design_target_chip="A2",
                 golden_path=_tmp_golden())


def test_transition_rejects_pending_golden_alignment():
    """agent 产 status=pending → transition schema_violation（杜绝未检流过）。"""
    ar = AgentResult(agent_name="requirement-analyst", status="ok",
                     artifacts=_req_artifact({"status": "pending"}))
    new_state = RequirementStage().transition(_req_state(), {"agent_result": ar})
    assert new_state.last_error is not None
    assert new_state.last_error.error_type == "schema_violation"
    assert "pending" in new_state.last_error.message


def test_transition_missing_golden_alignment_schema_violation():
    """agent 漏 golden_alignment → required_keys 兜 presence → schema_violation
    （可诊断：req-analysis 当场报，不推迟到下游 precision 才炸）。"""
    ar = AgentResult(agent_name="requirement-analyst", status="ok",
                     artifacts=_req_artifact(omit_golden_alignment=True))
    new_state = RequirementStage().transition(_req_state(), {"agent_result": ar})
    assert new_state.last_error is not None
    assert new_state.last_error.error_type == "schema_violation"
    assert "golden_alignment" in new_state.last_error.message


def test_transition_accepts_pass_golden_alignment():
    """status=pass → 校验通过，requirement 正常落盘（happy path 不被误伤）。"""
    ar = AgentResult(agent_name="requirement-analyst", status="ok",
                     artifacts=_req_artifact({"status": "pass"}))
    new_state = RequirementStage().transition(_req_state(), {"agent_result": ar})
    assert new_state.last_error is None
    assert new_state.requirement is not None
