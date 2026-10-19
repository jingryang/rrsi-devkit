"""P1: report status 诚实化 —— stage_complete event 的 status 决定 report 里
该 stage 的 status，不再无条件 "ok"。

回归 run 20260730-072625-bec36b：codegen 实际 fail_strategy=halt 失败，但
report.json/report.md 显示 status=ok，因为 report.py:69 硬编码 "ok"，且
runner emit stage_complete 时未带 status。
"""

from __future__ import annotations

from ascendc_devkit.application.report import Report


def _events(status=None, stage="codegen"):
    sc = {"type": "stage_complete", "stage": stage,
          "elapsed_ms": 100, "total_iterations": 3}
    if status is not None:
        sc["status"] = status
    return [
        {"type": "stage_enter", "stage": stage},
        sc,
    ]


def test_report_reads_failed_status():
    r = Report._from_events("run1", _events("failed"))
    assert r.stages[0].name == "codegen"
    assert r.stages[0].status == "error"   # v0.2.0 归一化词表: failed→error


def test_report_reads_partial_status():
    r = Report._from_events("run1", _events("partial"))
    assert r.stages[0].status == "partial"


def test_report_reads_ok_status():
    r = Report._from_events("run1", _events("ok"))
    assert r.stages[0].status == "ok"


def test_report_missing_status_is_unknown_not_ok():
    """无 status 字段 → unknown（绝不静默报 ok）。"""
    r = Report._from_events("run1", _events(None))
    assert r.stages[0].status == "unknown"


def test_report_markdown_reflects_failed(tmp_path):
    """run 20260730 回归：halted codegen 在 report.md 表格里显示 failed。"""
    r = Report._from_events("run1", _events("failed"))
    out = tmp_path / "report.md"
    r.write_markdown(out)
    text = out.read_text(encoding="utf-8")
    assert "| codegen | error |" in text
    assert "| codegen | ok |" not in text


def test_report_json_reflects_failed(tmp_path):
    import json
    r = Report._from_events("run1", _events("failed"))
    out = tmp_path / "report.json"
    r.write_json(out)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert any(s["name"] == "codegen" and s["status"] == "error"   # 归一化词表
               for s in data["stages"])


def test_report_reads_cancelled_status():
    """stage_complete status=cancelled 直透为 cancelled（runner cancel 路径
    发的是独立的 stage_aborted 事件，那条路置 aborted；本用例覆盖 stage_complete
    携带 cancelled 的边界）。"""
    r = Report._from_events("run1", _events("cancelled", stage="eval"))
    assert r.stages[0].status == "aborted"   # v0.2.0 归一化词表: cancelled→aborted
