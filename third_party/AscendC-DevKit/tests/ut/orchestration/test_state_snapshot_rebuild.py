"""UT — State snapshot round-trip rebuilds every nested dataclass.

Reproduces the resume crash where ``State.from_snapshot`` only rebuilt
``run_context`` and left every other nested frozen dataclass
(``op_identity`` / ``profile`` / ``op_spec`` / ``build_result`` / ...)
as a plain dict, so the first attribute access after resume raised
``'dict' object has no attribute 'op_dir'`` (hit by codegen).

This mirrors the *real* resume path: ``to_snapshot`` → ``json.dumps(default=str)``
(Path → str) → disk → ``json.loads`` → ``from_snapshot``. The earlier
run_context test only covered the in-memory ``to_snapshot``/``from_snapshot``
half, so it never saw the Path→str layer; this suite round-trips through
JSON to catch both the dict-flattening and the Path demotion.
"""

import json
from pathlib import Path

from ascendc_devkit.domain.operator import OperatorIdentity, OperatorSpec
from ascendc_devkit.domain.repository import (
    BuildStage, BuildVariant, OpNaming, RepositoryProfile,
)
from ascendc_devkit.domain.requirement import (
    Constraint, Requirement, TestCase, UnclearItem,
)
from ascendc_devkit.domain.verification import (
    AdaptResult, BuildResult, DeployResult, EvalResult,
    PerformanceResult, PrecisionDebugResult,
)
from ascendc_devkit.orchestration.kernel.state import State, ErrorFeedback


def _profile() -> RepositoryProfile:
    return RepositoryProfile(
        name="cann-bench",
        op_naming=OpNaming(prefix="Exp"),
        build_variants=(
            BuildVariant(
                name="default",
                match_prefix="examples/aclnn_launch_example",
                stages=(
                    BuildStage(name="build", cwd=".", command_template="bash build.sh {full_op_name}"),
                ),
            ),
        ),
    )


def _identity() -> OperatorIdentity:
    return OperatorIdentity(
        spec=OperatorSpec(name="exp"),
        repo_root=Path("/home/u/code/cann-bench"),
        op_dir=Path("/home/u/code/cann-bench/examples/aclnn_launch_example/csrc/ops/exp"),
        files={"kernel_cpp": Path("/home/u/code/cann-bench/examples/aclnn_launch_example/csrc/ops/exp/exp.cpp")},
    )


def _requirement() -> Requirement:
    return Requirement(
        op_spec=OperatorSpec(name="exp"),
        design_doc_path=Path("/repo/docs/exp.md"),
        constraints=[Constraint(kind="precision", threshold=1e-5, comparison="abs_diff")],
        test_cases=[TestCase(name="t0", expected={"max_diff": 1e-7})],
        unclear_items=[UnclearItem(question="dtype?")],
    )


def _round_trip(state: State) -> State:
    """The exact path _write_state_snapshot → _load_state_from_run takes."""
    snap = state.to_snapshot()
    on_disk = json.dumps(snap, ensure_ascii=False, default=str)
    return State.from_snapshot(json.loads(on_disk))


# —— The exact crash site: codegen.py does `state.op_identity.op_dir`. ——

def test_op_identity_op_dir_is_attribute_access_after_resume():
    state = State(op_identity=_identity())
    restored = _round_trip(state)
    # This line is the codegen crash: attribute access on a truthy dict.
    assert restored.op_identity  # truthy, not None
    assert restored.op_identity.op_dir == Path(
        "/home/u/code/cann-bench/examples/aclnn_launch_example/csrc/ops/exp")
    assert isinstance(restored.op_identity.op_dir, Path)  # str would break downstream Path ops
    assert isinstance(restored.op_identity.repo_root, Path)
    assert isinstance(restored.op_identity.files["kernel_cpp"], Path)
    assert str(restored.op_identity.files["kernel_cpp"]).endswith("/ops/exp/exp.cpp")


def test_op_identity_and_spec_rebuilt_as_dataclasses():
    state = State(op_identity=_identity())
    restored = _round_trip(state)
    assert isinstance(restored.op_identity, OperatorIdentity)
    assert isinstance(restored.op_identity.spec, OperatorSpec)
    assert restored.op_identity.spec.name == "exp"


def test_profile_rebuilt_with_variants_and_stages():
    state = State(profile=_profile())
    restored = _round_trip(state)
    assert isinstance(restored.profile, RepositoryProfile)
    assert restored.profile.name == "cann-bench"
    variant = restored.profile.build_variants[0]
    assert isinstance(variant, BuildVariant)
    assert isinstance(variant.stages[0], BuildStage)
    # attribute/method access (the thing a dict breaks) still works
    assert restored.profile.full_op_name("exp") == "Expexp"


def test_build_result_rebuilt_and_attribute_accessible():
    state = State(build_result=BuildResult(
        passed=True, stdout="ok", stderr="",
        artifacts=[Path("/repo/build/exp.o")]))
    restored = _round_trip(state)
    assert isinstance(restored.build_result, BuildResult)
    assert restored.build_result.passed is True          # gates.py reads .passed
    assert isinstance(restored.build_result.artifacts[0], Path)


def test_debug_result_rebuilt_and_attribute_accessible():
    """P54: PrecisionDebugResult 往返（防 P48 类反序列化漏建字段）。"""
    state = State(debug_result=PrecisionDebugResult(
        passed=False, max_diff=0.42, best_commit="abc123",
        failing_cases=["t0", "t1"], iterations_used=3))
    restored = _round_trip(state)
    assert isinstance(restored.debug_result, PrecisionDebugResult)
    assert restored.debug_result.passed is False
    assert restored.debug_result.max_diff == 0.42
    assert restored.debug_result.best_commit == "abc123"
    assert restored.debug_result.failing_cases == ["t0", "t1"]
    assert restored.debug_result.iterations_used == 3


def test_debug_iterations_default_and_roundtrip():
    """P54: debug_iterations 默认 0 + 往返；debug_result 默认 None。"""
    state = State(debug_iterations=5)
    restored = _round_trip(state)
    assert restored.debug_iterations == 5
    assert State().debug_iterations == 0
    assert State().debug_result is None


def test_other_verification_results_rebuilt():
    state = State(
        performance_result=PerformanceResult(passed=True, actual_ms=1.2, speedup=3.1),
        deploy_result=DeployResult(smoke_passed=True, install_path="/opp/exp"),
        eval_result=EvalResult(overall_score=88.0, num_cases=10, num_passed=9),
        adapt_result=AdaptResult(adapted=True, files_modified=["__init__.py"]),
    )
    restored = _round_trip(state)
    assert isinstance(restored.performance_result, PerformanceResult)
    assert restored.performance_result.speedup == 3.1
    assert isinstance(restored.deploy_result, DeployResult)
    assert restored.deploy_result.smoke_passed is True
    assert isinstance(restored.eval_result, EvalResult)
    assert restored.eval_result.overall_score == 88.0
    assert isinstance(restored.adapt_result, AdaptResult)
    assert restored.adapt_result.files_modified == ["__init__.py"]


def test_last_error_rebuilt():
    state = State(last_error=ErrorFeedback(
        stage_name="codegen", error_type="compile_error",
        message="boom", details={"file": "exp.cpp"}))
    restored = _round_trip(state)
    assert isinstance(restored.last_error, ErrorFeedback)
    assert restored.last_error.stage_name == "codegen"
    assert restored.last_error.details == {"file": "exp.cpp"}


def test_run_context_still_rebuilt_after_converging_into_generic_path():
    # run_context must keep working after its special-case handling is folded
    # into the generic rebuilder.
    from ascendc_devkit.orchestration.run_context import (
        RunContext, build_hardware_target,
    )
    state = State(run_context=RunContext(hardware_target=build_hardware_target("A2")))
    restored = _round_trip(state)
    assert isinstance(restored.run_context, RunContext)
    assert isinstance(restored.run_context.hardware_target, type(state.run_context.hardware_target))
    assert restored.run_context.hardware_target.hw_params["ub_size_bytes"] == 196608


def test_requirement_rebuilt_with_nested_lists():
    state = State(requirement=_requirement())
    restored = _round_trip(state)
    req = restored.requirement
    assert isinstance(req.op_spec, OperatorSpec)
    assert isinstance(req.design_doc_path, Path)            # Path | None → Path restored
    # list[TensorSpec] / list[Constraint] / list[TestCase] / list[UnclearItem]
    # must rebuild element-wise, not stay list[dict].
    assert len(req.constraints) and not isinstance(req.constraints[0], dict)
    assert len(req.test_cases) and not isinstance(req.test_cases[0], dict)
    assert len(req.unclear_items) and not isinstance(req.unclear_items[0], dict)


# —— Top-level scalar/list Path fields on State itself ——————————————————
#
# The rebuild loop in from_snapshot only called _rebuild_value for fields
# whose annotation is_dataclass. Every OTHER field (Path scalars, list[Path],
# list[<nested dataclass>] declared directly on State) was left untouched —
# a str/str TypeError first surfaced when deploy.py did `repo_root / cwd`
# after resume (state.repo_root came back as str, not Path).

def test_repo_root_and_op_dir_restored_as_path_after_resume():
    """Exact crash site: deploy.py does `repo_root / variant.stages[0].cwd`."""
    state = State(
        repo_root=Path("/home/u/code/cann-bench"),
        op_dir=Path("/home/u/code/cann-bench/examples/aclnn_launch_example/csrc/ops/exp"),
        target_repo=Path("/home/u/code/cann-bench"),
    )
    restored = _round_trip(state)
    assert isinstance(restored.repo_root, Path)
    assert isinstance(restored.op_dir, Path)
    assert isinstance(restored.target_repo, Path)
    # The actual failing expression from deploy.py transition().
    assert restored.repo_root / "examples/aclnn_launch_example" == (
        Path("/home/u/code/cann-bench/examples/aclnn_launch_example"))


def test_all_top_level_path_fields_restored_as_path_after_resume():
    """Every Path-typed field declared directly on State, not just repo_root."""
    paths = dict(
        target_repo=Path("/a"), op_dir=Path("/b"), repo_root=Path("/c"),
        requirement_path=Path("/d"), reference_op_path=Path("/e"),
        design_doc_path=Path("/f"), golden_path=Path("/g"),
        cases_path=Path("/h"), detailed_design_path=Path("/i"),
        test_design_report=Path("/j"),
    )
    state = State(**paths)
    restored = _round_trip(state)
    for field_name in paths:
        value = getattr(restored, field_name)
        assert isinstance(value, Path), (
            f"State.{field_name} came back as {type(value).__name__}, not Path")


def test_top_level_test_cases_rebuilt_as_testcase_after_resume():
    """Exact crash site: runner.py:277 does `for inp in tc.inputs` over
    State.test_cases. The field is the test_design stage's authoritative
    case list (CSV→TestCase adapter); on resume it must come back as
    list[TestCase], not list[dict], or verify dies with
    ``'dict' object has no attribute 'inputs'``.

    (Requirement.test_cases is already typed list[TestCase] and covered above;
    State.test_cases is a *separate* top-level field — its own annotation must
    carry TestCase so the generic rebuilder recurses into each element.)
    """
    state = State(test_cases=[
        TestCase(name="t0", inputs=[{"shape": [1024], "dtype": "fp16"}],
                 attrs={"base": -1.0}),
        TestCase(name="t1", inputs=[{"shape": [4, 4], "dtype": "fp32"}]),
    ])
    restored = _round_trip(state)
    assert len(restored.test_cases) == 2
    # The runner crash: attribute access on what would be a plain dict.
    assert isinstance(restored.test_cases[0], TestCase)
    assert restored.test_cases[0].name == "t0"
    assert restored.test_cases[0].inputs[0]["shape"] == [1024]
    assert restored.test_cases[0].attrs == {"base": -1.0}
    assert isinstance(restored.test_cases[1], TestCase)
    assert restored.test_cases[1].inputs[0]["dtype"] == "fp32"


def test_target_files_list_of_path_restored_element_wise():
    state = State(target_files=[Path("/repo/exp.cpp"), Path("/repo/exp.h")])
    restored = _round_trip(state)
    assert len(restored.target_files) == 2
    assert all(isinstance(p, Path) for p in restored.target_files)


# —— npu_id Optional（op 级权威卡：dispatch 解析前为 None）+ card_pool/card_lease 已退役 ————

def test_npu_id_defaults_to_none():
    """npu_id defaults to None (card resolved once at the dispatch boundary via
    the op-level lease), NOT 0 — a literal 0 would hard-pin card 0 and break
    batch pooling for tasks that did not opt into a specific card."""
    assert State().npu_id is None


def test_npu_id_none_and_int_both_round_trip():
    state_none = State(npu_id=None)
    assert _round_trip(state_none).npu_id is None
    state_pin = State(npu_id=3)
    assert _round_trip(state_pin).npu_id == 3


def test_retired_card_fields_dropped_from_disk_on_rebuild():
    """P13 (step-116)：card_pool/card_lease 字段已退役——旧快照/伪造盘上值在
    from_snapshot 一次性丢弃（§1.4 不留别名），重建的 State 无这两个属性。"""
    snap = State(npu_id=1).to_snapshot()
    snap["card_pool"] = {"forged": True}   # tampered / legacy disk state
    snap["card_lease"] = 3
    state = State.from_snapshot(snap)
    assert not hasattr(state, "card_pool") and not hasattr(state, "card_lease")


def test_npu_id_persisted_as_authoritative_op_card():
    """npu_id 是 dispatch 解析的权威 op 卡——随快照持久化（resume/TUI 读回）。"""
    snap = State(npu_id=5).to_snapshot()
    assert snap["npu_id"] == 5
    assert State.from_snapshot(dict(snap)).npu_id == 5
