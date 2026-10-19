"""UT for harness-timeout adaptation (harness-timeout-adaptive).

Coverage (§3.8 UT = 纯逻辑/编排, mock 不依赖 NPU):
  1. runner._tested_cases_summary — 超时时 shape/element-size 摘要（解决 case_details 空丢 shape）
  2. runtime_config loaders — harness_timeout_sec / harness_timeout_max_sec（config 默认 + 兜底）
  3. control.json contract — harness_timeout_sec 进 required keys + defaults（旧 control.json 兜底）
  4. _extract_debug_checkpoint — observed_issues 透出供 resolve_condition
  5. RunTestsSubstage.resolve_condition — observed_issues 非空 → has_failures
  6. EvalRequest.test_timeout_sec → _common 透传 runner.execute(timeout_sec)
  7. debug_service.run_cases — 读 control.json.harness_timeout_sec 覆盖 config 默认
"""

import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from ascendc_devkit.adapters.npu.runner import _tested_cases_summary
from ascendc_devkit.domain.evaluation import EvalRequest, OpRef, RunMode
from ascendc_devkit.domain.requirement import TestCase


# ── 1. runner._tested_cases_summary ──────────────────────────────────────────

def test_tested_cases_summary_normal_shapes():
    cases = [
        TestCase(name="a", inputs=[{"shape": [16, 257, 256]}]),
        TestCase(name="b", inputs=[{"shape": [17, 4112, 8, 16]},
                                   {"shape": [16]}]),
    ]
    summary = _tested_cases_summary(cases)
    assert len(summary) == 2
    assert summary[0]["case_id"] == "a"
    # 16*257*256
    assert summary[0]["max_input_elements"] == 16 * 257 * 256
    # 17*4112*8*16 是两输入中更大的
    assert summary[1]["max_input_elements"] == 17 * 4112 * 8 * 16
    assert "4112" in summary[1]["shape"]


def test_tested_cases_summary_symbolic_or_str_dims_not_counted():
    """符号/字符串维不可数 → 该输入元素数记 0（不误判大 shape）。"""
    cases = [TestCase(name="sym", inputs=[{"shape": [1024, "N", 32]},
                                          {"shape": [8, 8]}])]
    summary = _tested_cases_summary(cases)
    assert summary[0]["max_input_elements"] == 64  # 只计 [8,8] 那个可数输入


def test_tested_cases_summary_no_inputs():
    cases = [TestCase(name="empty", inputs=[])]
    summary = _tested_cases_summary(cases)
    assert summary[0]["max_input_elements"] == 0
    assert summary[0]["shape"] == "[]"


# ── 2. runtime_config loaders ────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _restore_runtime_config():
    """恢复 runtime_config 模块级值（loader 测试会 mutate _RAW）。"""
    import ascendc_devkit.orchestration.runtime_config as rc
    saved = {name: getattr(rc, name) for name in
             ("_RAW", "HARNESS_TIMEOUT_SEC", "HARNESS_TIMEOUT_MAX_SEC")
             if hasattr(rc, name)}
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(rc, name, value)


def test_harness_timeout_defaults_when_config_missing():
    import ascendc_devkit.orchestration.runtime_config as rc
    rc._RAW = {}
    assert rc.harness_timeout_sec() == 120.0
    assert rc.harness_timeout_max_sec() == 1200.0


def test_harness_timeout_reads_config():
    """直接测 loader（模块级常量在 import 时固化，_RAW 改动由 _load_* 消费）。"""
    import ascendc_devkit.orchestration.runtime_config as rc
    rc._RAW = {"timeouts": {"harness_sec": 240},
               "precision_debug": {"harness_timeout_max_sec": 900}}
    assert rc._load_harness_timeout() == 240.0
    assert rc._precision_knob("harness_timeout_max_sec", 1200) == 900


def test_harness_timeout_invalid_rejects_non_positive():
    import ascendc_devkit.orchestration.runtime_config as rc
    from ascendc_devkit.domain.exceptions import ConfigError
    rc._RAW = {"timeouts": {"harness_sec": 0}}
    with pytest.raises(ConfigError):
        rc._load_harness_timeout()


# ── 3. control.json contract ─────────────────────────────────────────────────

def test_control_required_keys_include_harness_timeout():
    from ascendc_devkit.orchestration.stages import precision_debug_substages as ps
    assert "harness_timeout_sec" in ps._CONTROL_REQUIRED_KEYS


def test_control_defaults_include_harness_timeout():
    from ascendc_devkit.orchestration.stages import precision_debug_substages as ps
    assert ps._CONTROL_DEFAULTS["harness_timeout_sec"] > 0


# ── 4. checkpoint extraction ─────────────────────────────────────────────────

def test_extract_debug_checkpoint_exposes_observed_issues():
    from ascendc_devkit.orchestration.stages.precision_debug_substages import (
        _extract_debug_checkpoint,
    )
    cp = {"observed_issues": [{"category": "upstream_signal"}]}
    dc = _extract_debug_checkpoint(cp)
    assert dc["observed_issues"] == [{"category": "upstream_signal"}]
    # 缺失时兜底空列表（旧 control.json 兼容）
    assert _extract_debug_checkpoint({})["observed_issues"] == []


# ── 5. resolve_condition ───────────────────────────────────────────────


def test_eval_request_carries_test_timeout():
    req = EvalRequest(
        op=OpRef(callable_target={"kind": "torch_op", "symbol": "x"},
                 op_name="x", op_dir="", chip="A2"),
        cases=[], rule=SimpleNamespace(dtype_thresholds={}),
        deploy_result=None, golden_contract=None, mode=RunMode.SINGLE_CASE,
        test_timeout_sec=240.0,
    )
    assert req.test_timeout_sec == 240.0
    # None 默认（backend 用 runner 默认 120）
    req2 = EvalRequest(
        op=req.op, cases=[], rule=req.rule, deploy_result=None,
        golden_contract=None, mode=RunMode.SINGLE_CASE,
    )
    assert req2.test_timeout_sec is None


@patch("ascendc_devkit.adapters.npu.runner.NPURunner")
def test_common_passes_timeout_to_runner(MockRunner):
    """run_with_npu_runner 把 request.test_timeout_sec 传给 runner.execute(timeout_sec)。"""
    from ascendc_devkit.adapters.evaluation._common import run_with_npu_runner
    import ascendc_devkit.adapters.evaluation._common as common

    # 构造真实 EvalRequest（rule 需要 CompareRule）
    from ascendc_devkit.domain.precision import CompareRule
    req = EvalRequest(
        op=OpRef(callable_target={"kind": "torch_op", "symbol": "x"},
                 op_name="x", op_dir="", chip="A2"),
        cases=[], rule=CompareRule(dtype_thresholds={}),
        deploy_result=None, golden_contract=None, mode=RunMode.SINGLE_CASE,
        test_timeout_sec=360.0,
        log_dir="/tmp/log",
    )
    runner = MockRunner.return_value
    runner.execute.return_value = {"passed": True, "case_details": []}
    # result_dict_to_test_report 需要可用；mock 掉 report 转换
    with patch.object(common, "result_dict_to_test_report",
                      return_value=SimpleNamespace(cases=[], extra={})):
        run_with_npu_runner(req, comparer=SimpleNamespace(harness_setup_lines=lambda r: ""))

    # 拿到传给 execute 的 timeout_sec
    _, kwargs = runner.execute.call_args
    assert kwargs.get("timeout_sec") == 360.0


def test_common_timeout_defaults_to_120_when_none():
    from ascendc_devkit.adapters.evaluation._common import run_with_npu_runner
    import ascendc_devkit.adapters.evaluation._common as common
    from ascendc_devkit.domain.precision import CompareRule
    req = EvalRequest(
        op=OpRef(callable_target={"kind": "torch_op", "symbol": "x"},
                 op_name="x", op_dir="", chip="A2"),
        cases=[], rule=CompareRule(dtype_thresholds={}),
        deploy_result=None, golden_contract=None, mode=RunMode.SINGLE_CASE,
    )
    with patch("ascendc_devkit.adapters.npu.runner.NPURunner") as MockRunner:
        runner = MockRunner.return_value
        runner.execute.return_value = {"passed": True, "case_details": []}
        with patch.object(common, "result_dict_to_test_report",
                          return_value=SimpleNamespace(cases=[], extra={})):
            run_with_npu_runner(req, comparer=SimpleNamespace(harness_setup_lines=lambda r: ""))
        _, kwargs = runner.execute.call_args
        assert kwargs.get("timeout_sec") == 120


# ── 7. debug_service.run_cases 解析超时（control.json 覆盖 config）──────────

def _make_debug_service_mocks(tmp_path):
    """构造 DebugService 与各依赖的 mock；返回 (service, run_dir, debug_dir)。"""
    from ascendc_devkit.application.debug_service import DebugService
    svc = DebugService()
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    debug_dir = tmp_path / "ws" / "artifacts" / "debug" / "op"
    debug_dir.mkdir(parents=True)
    return svc, run_dir, debug_dir


@patch("ascendc_devkit.application.debug_service.run_precision_cases")
def test_run_cases_uses_control_json_timeout_override(mock_rpc, tmp_path):
    """control.json.harness_timeout_sec 存在 → 覆盖 config 默认透传。"""
    from ascendc_devkit.application.debug_service import DebugService
    svc, run_dir, debug_dir = _make_debug_service_mocks(tmp_path)
    # control.json 写放大值
    (debug_dir / "control.json").write_text(
        json.dumps({"harness_timeout_sec": 480}), encoding="utf-8")

    mock_rpc.return_value = {"passed": True, "case_details": []}
    # state 提供 load 所需字段（test_cases 非空，否则 run_cases 提前 raise）
    state = SimpleNamespace(
        op_dir=tmp_path, npu_id=0,
        cases_source="devkit", design_target_chip="A2",
        test_cases=[TestCase(name="c1", inputs=[{"shape": [4], "dtype": "fp16"}])],
        codegen_manifest={"callable_target": {"kind": "torch_op", "symbol": "x"}},
        requirement=None, op_identity=SimpleNamespace(spec=SimpleNamespace(
            precision_thresholds=None, outputs=[])),
        golden_path=None, golden_entry=None, golden_input_type=None,
        requirement_path=None,
    )
    with patch.object(svc, "load_state", return_value=state), \
         patch.object(svc, "_op_name", return_value="op"), \
         patch.object(svc, "debug_dir", return_value=debug_dir), \
         patch.object(svc, "read_last_deploy",
                      return_value=SimpleNamespace(python_path="/p", install_path="/i",
                                                   ld_library_path_add="")):
        svc.run_cases(run_dir, iter_n=1, label="run_tests")

    kwargs = mock_rpc.call_args.kwargs
    assert kwargs["test_timeout_sec"] == 480.0


@patch("ascendc_devkit.application.debug_service.run_precision_cases")
def test_run_cases_uses_config_default_without_control_json(mock_rpc, tmp_path):
    """无 control.json → 用 config 默认 harness_timeout_sec。"""
    from ascendc_devkit.application.debug_service import DebugService
    svc, run_dir, debug_dir = _make_debug_service_mocks(tmp_path)
    mock_rpc.return_value = {"passed": True, "case_details": []}
    state = SimpleNamespace(
        op_dir=tmp_path, npu_id=0,
        cases_source="devkit", design_target_chip="A2",
        test_cases=[TestCase(name="c1", inputs=[{"shape": [4], "dtype": "fp16"}])],
        codegen_manifest={"callable_target": {"kind": "torch_op", "symbol": "x"}},
        requirement=None, op_identity=SimpleNamespace(spec=SimpleNamespace(
            precision_thresholds=None, outputs=[])),
        golden_path=None, golden_entry=None, golden_input_type=None,
        requirement_path=None,
    )
    with patch.object(svc, "load_state", return_value=state), \
         patch.object(svc, "_op_name", return_value="op"), \
         patch.object(svc, "debug_dir", return_value=debug_dir), \
         patch.object(svc, "read_last_deploy",
                      return_value=SimpleNamespace(python_path="/p", install_path="/i",
                                                   ld_library_path_add="")):
        svc.run_cases(run_dir, iter_n=1, label="run_tests")

    kwargs = mock_rpc.call_args.kwargs
    # config 默认 = harness_timeout_sec()（环境默认 120，若被其他测试改则取当前值）
    from ascendc_devkit.orchestration.runtime_config import harness_timeout_sec
    assert kwargs["test_timeout_sec"] == harness_timeout_sec()


@patch("ascendc_devkit.application.debug_service.run_precision_cases")
def test_run_cases_uses_sidecar_timeout_when_control_missing(mock_rpc, tmp_path):
    """review 补充（e4095eb2 模式 3 三级优先级缺 sidecar 级）: control.json 存在但
    无 harness_timeout_sec（agent 重写 control.json 属正常交接，框架自有字段缺失
    不 WARN 不填默认），放大值落框架自有 sidecar（harness_timeout.fw.json）→
    debug_service.run_cases 应读 sidecar 兜底，而非退回 config 默认（120）。

    control 显式值 > sidecar > config 默认（§2.9 构造性：放大值是代码派生，
    不靠 agent 在 control.json 保留）。"""
    from ascendc_devkit.application.debug_service import DebugService
    svc, run_dir, debug_dir = _make_debug_service_mocks(tmp_path)
    # control.json 缺 harness_timeout_sec（agent 重写弄丢 = 正常交接）
    (debug_dir / "control.json").write_text(
        json.dumps({"failed_case_queue": []}), encoding="utf-8")
    # 框架自有 sidecar 持放大值 480
    (debug_dir / "harness_timeout.fw.json").write_text(
        json.dumps({"harness_timeout_sec": 480}), encoding="utf-8")

    mock_rpc.return_value = {"passed": True, "case_details": []}
    state = SimpleNamespace(
        op_dir=tmp_path, npu_id=0,
        cases_source="devkit", design_target_chip="A2",
        test_cases=[TestCase(name="c1", inputs=[{"shape": [4], "dtype": "fp16"}])],
        codegen_manifest={"callable_target": {"kind": "torch_op", "symbol": "x"}},
        requirement=None, op_identity=SimpleNamespace(spec=SimpleNamespace(
            precision_thresholds=None, outputs=[])),
        golden_path=None, golden_entry=None, golden_input_type=None,
        requirement_path=None,
    )
    with patch.object(svc, "load_state", return_value=state), \
         patch.object(svc, "_op_name", return_value="op"), \
         patch.object(svc, "debug_dir", return_value=debug_dir), \
         patch.object(svc, "read_last_deploy",
                      return_value=SimpleNamespace(python_path="/p", install_path="/i",
                                                   ld_library_path_add="")):
        svc.run_cases(run_dir, iter_n=1, label="run_tests")

    kwargs = mock_rpc.call_args.kwargs
    assert kwargs["test_timeout_sec"] == 480.0
