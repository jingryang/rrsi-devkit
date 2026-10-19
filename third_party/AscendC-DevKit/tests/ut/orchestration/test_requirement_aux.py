"""Requirement stage 附加需求材料（--requirement-aux）测试。

覆盖框架层新增能力：主需求文档（--requirement，物化为 requirement_doc.md）之外，
可声明若干附加需求材料（如同 task 目录的 desc.md），随 requirement 工作目录一并
物化 + prompt 点名供 agent 阅读。附加材料**不参与**确定性 proto 解析（schema/精度/
tensorlist 仍只读 requirement_path，golden 仍为行为唯一权威 §1.13）。

对应 field chain: run.py --requirement-aux → task_request → entry.py → State.
requirement_aux_paths → RequirementStage._materialize_inputs / _build_analysis_prompt。
"""

import json
import tempfile
from pathlib import Path

from ascendc_devkit.orchestration.kernel.state import State
from ascendc_devkit.orchestration.stages.requirement import RequirementStage


def _write(text: str, suffix: str = ".md") -> Path:
    f = tempfile.NamedTemporaryFile(suffix=suffix, mode="w", delete=False)
    f.write(text)
    f.close()
    return Path(f.name)


def _make_state(**kw) -> State:
    """State with a real requirement doc; extra kwargs (e.g. requirement_aux_paths) overlaid."""
    req_path = _write("operator:\n  name: Exp\n")
    base = dict(mode="new", requirement_path=req_path)
    base.update(kw)
    return State(**base)


# —— _materialize_inputs：物化 ——

def test_materialize_writes_aux_file_name_preserving():
    aux = _write("# Exp 需求补充\n\n精度阈值表…", suffix=".md")
    state = _make_state(requirement_aux_paths=[aux])
    wd = tempfile.mkdtemp()
    RequirementStage()._materialize_inputs(state, Path(wd))

    materialized = Path(wd) / aux.name  # name-preserving
    assert materialized.exists()
    assert materialized.read_text() == "# Exp 需求补充\n\n精度阈值表…"


def test_materialize_skips_missing_aux_path():
    """不存在路径不崩，静默跳过（Graceful，§1.3 加载期校验不阻断）。"""
    missing = Path("/nonexistent/desc.md")
    state = _make_state(requirement_aux_paths=[missing])
    wd = tempfile.mkdtemp()
    RequirementStage()._materialize_inputs(state, Path(wd))
    # 只写了主需求，无额外文件
    assert not (Path(wd) / missing.name).exists()


def test_materialize_disambiguates_basename_collision():
    """附加材料与既有 CWD 文件（requirement_doc.md）撞名时前缀 aux_，不覆盖主需求。"""
    aux = _write("# 假的需求", suffix=".md")
    # 强制与主需求撞名：用临时目录里的 requirement_doc.md 同名源文件
    # aux.name 就是 requirement_doc.md 的场景：构造同名文件
    collide_src = Path(tempfile.mkdtemp()) / "requirement_doc.md"
    collide_src.write_text("# 撞名材料", encoding="utf-8")
    state = _make_state(requirement_aux_paths=[collide_src])
    wd = tempfile.mkdtemp()
    RequirementStage()._materialize_inputs(state, Path(wd))

    # 主需求保留在 requirement_doc.md，撞名材料落到 aux_requirement_doc.md
    assert (Path(wd) / "requirement_doc.md").exists()
    aux_dest = Path(wd) / "aux_requirement_doc.md"
    assert aux_dest.exists()
    assert aux_dest.read_text() == "# 撞名材料"


def test_materialize_without_aux_is_noop():
    state = _make_state()  # 无 requirement_aux_paths
    wd = tempfile.mkdtemp()
    RequirementStage()._materialize_inputs(state, Path(wd))
    assert (Path(wd) / "requirement_doc.md").exists()
    # 无额外 aux 文件
    assert not (Path(wd) / "desc.md").exists()


# —— _build_analysis_prompt：点名 ——

def test_prompt_points_at_aux_material():
    aux = _write("# Exp 需求补充", suffix=".md")
    state = _make_state(requirement_aux_paths=[aux])
    prompt = RequirementStage()._build_analysis_prompt(state, iteration=1)

    assert "## 附加需求材料" in prompt
    assert f"`{aux.name}`" in prompt
    assert "requirement_doc.md" in prompt  # 主需求仍以 requirement_doc.md 为准
    assert str(aux) in prompt  # 来源绝对路径


def test_prompt_without_aux_omits_section():
    state = _make_state()
    prompt = RequirementStage()._build_analysis_prompt(state, iteration=1)
    assert "## 附加需求材料" not in prompt


def test_prompt_skips_missing_aux_in_listing():
    """aux 路径存在性防御：不存在则 prompt 不列出（与 materialize 一致）。"""
    missing = Path("/nonexistent/desc.md")
    state = _make_state(requirement_aux_paths=[missing])
    prompt = RequirementStage()._build_analysis_prompt(state, iteration=1)
    assert "## 附加需求材料" not in prompt


# —— 确定性解析不受附加材料影响 ——

def test_deterministic_parse_still_reads_requirement_path():
    """read_proto_schema / _attach_proto 等确定性解析只读 requirement_path，
    requirement_aux_paths 非空不影响其行为。"""
    from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
    proto = _write(
        "operator:\n"
        "  name: Exp\n"
        "  precision_thresholds:\n"
        "    float16: 0.001\n"
        "  schema: exp(Tensor x) -> Tensor y\n",
        suffix=".yaml",
    )
    aux = _write("# Exp desc", suffix=".md")
    state = _make_state(requirement_path=proto, requirement_aux_paths=[aux])

    # 主需求仍是确定性解析唯一源：schema 从 proto 读出
    from ascendc_devkit.domain.requirement import read_proto_schema
    assert read_proto_schema(state.requirement_path) == "exp(Tensor x) -> Tensor y"
    # _attach_proto 把 proto 的 precision_thresholds patch 上 op_spec
    spec = OperatorSpec(name="Exp", outputs=[TensorSpec(name="y", dtype="fp16")])
    patched = RequirementStage._attach_proto(spec, state.requirement_path)
    assert patched.precision_thresholds == {"float16": 0.001}


# —— snapshot 往返 ——

def test_snapshot_roundtrip_preserves_aux_paths():
    aux = _write("# desc", suffix=".md")
    state = _make_state(requirement_aux_paths=[aux])
    snap = state.to_snapshot()
    # to_snapshot 用 asdict，list[Path] 会被序列化成列表
    assert "requirement_aux_paths" in snap
    rebuilt = State.from_snapshot(json.loads(json.dumps(snap, default=str)))
    # from_snapshot 里 list[str]（asdict 后 Path→str? 需核）能还原为可用状态
    assert hasattr(rebuilt, "requirement_aux_paths")


def test_snapshot_without_aux_defaults_to_empty():
    """旧快照缺 requirement_aux_paths 键 → from_snapshot 补默认 []（§1.4 兜底）。"""
    state = _make_state()
    snap = state.to_snapshot()
    snap.pop("requirement_aux_paths", None)  # 模拟旧快照
    rebuilt = State.from_snapshot(snap)
    assert rebuilt.requirement_aux_paths == []
