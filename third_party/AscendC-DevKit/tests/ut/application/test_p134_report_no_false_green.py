"""P134 (trial-20260730): report.json 假绿 —— stage_complete 无条件 status=ok。

根因：runner 在 stage_status 计算**之前**发射 stage_complete 且不带 status；
Report._from_events 见 stage_complete 即无条件置 status="ok"，故 halt/blocked 的
stage 也被报成 ok（假绿），掩盖真实失败。

修复：runner 把 stage_complete 移到 stage_status 算完后发射并带 status；
Report 按事件 status 忠实映射（ok/partial/failed/cancelled），不再一律绿。
"""
from __future__ import annotations

from ascendc_devkit.application.report import Report


def _report(events):
    return Report._from_events("run-x", events)


def _stages(report):
    return {s.name: s.status for s in report.stages}


def test_failed_stage_not_green():
    """stage_complete status=failed → report 'error'，不是 'ok'。"""
    events = [
        {"type": "stage_enter", "stage": "codegen"},
        {"type": "stage_complete", "stage": "codegen", "elapsed_ms": 10,
         "status": "failed", "total_iterations": 3},
    ]
    assert _stages(_report(events))["codegen"] == "error"


def test_partial_stage_reported_partial():
    events = [
        {"type": "stage_enter", "stage": "design"},
        {"type": "stage_complete", "stage": "design", "elapsed_ms": 5,
         "status": "partial", "total_iterations": 1},
    ]
    assert _stages(_report(events))["design"] == "partial"


def test_ok_stage_still_green():
    events = [
        {"type": "stage_enter", "stage": "requirement"},
        {"type": "stage_complete", "stage": "requirement", "elapsed_ms": 5,
         "status": "ok", "total_iterations": 1},
    ]
    assert _stages(_report(events))["requirement"] == "ok"


def test_cancelled_stage_reported_aborted():
    events = [
        {"type": "stage_enter", "stage": "eval"},
        {"type": "stage_complete", "stage": "eval", "elapsed_ms": 5,
         "status": "cancelled", "total_iterations": 0},
    ]
    assert _stages(_report(events))["eval"] == "aborted"


def test_missing_status_defaults_ok():
    """事件无 status → unknown（诚实默认，绝不静默绿）。正常路径已总是带
    status（runner P134 修复后）；缺失即异常事件，不可推断为成功——与
    test_report_status.test_report_missing_status_is_unknown_not_ok 同判据。"""
    events = [
        {"type": "stage_enter", "stage": "x"},
        {"type": "stage_complete", "stage": "x", "elapsed_ms": 5,
         "total_iterations": 1},
    ]
    assert _stages(_report(events))["x"] == "unknown"
