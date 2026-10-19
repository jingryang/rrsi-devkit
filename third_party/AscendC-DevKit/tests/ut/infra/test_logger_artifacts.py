"""step-8 §P6 — stage_done lists the stage's products (path + size)."""

from __future__ import annotations

from ascendc_devkit.infra.logger import Logger


def test_stage_done_lists_artifacts(capsys):
    Logger.stage_done("integrate", 1500, {
        "design_spec.json": '{"op_name": "rope"}',
        "tiling_strategy.json": "a\nb\nc",
    })
    err = capsys.readouterr().err
    assert "✓ integrate done (1.5s)" in err
    assert "design_spec.json" in err
    assert "tiling_strategy.json" in err
    assert "bytes" in err and "lines" in err


def test_stage_done_no_artifacts_no_list(capsys):
    Logger.stage_done("docgen", 100)
    err = capsys.readouterr().err
    assert "✓ docgen done" in err
    assert "↳" not in err  # no product lines


def test_stage_done_empty_dict_no_list(capsys):
    Logger.stage_done("noop", 50, {})
    err = capsys.readouterr().err
    assert "✓ noop done" in err
    assert "↳" not in err


# —— §P7.1: stage_done glyph reflects real status (no fake ✓) ——

def test_stage_done_ok_shows_check(capsys):
    Logger.stage_done("split", 1000, status="ok")
    err = capsys.readouterr().err
    assert "✓ split done (1.0s)" in err
    assert "[ok]" not in err  # ok status not annotated


def test_stage_done_partial_shows_warning(capsys):
    Logger.stage_done("split", 1000, status="partial")
    err = capsys.readouterr().err
    assert "⚠ split done (1.0s) [partial]" in err
    assert "✓" not in err


def test_stage_done_failed_shows_cross(capsys):
    Logger.stage_done("example-stage", 1000, status="failed")
    err = capsys.readouterr().err
    assert "✗ example-stage done (1.0s) [failed]" in err
    assert "✓" not in err


def test_stage_done_default_status_is_ok(capsys):
    # Back-compat: callers that omit status still get ✓.
    Logger.stage_done("docgen", 100)
    err = capsys.readouterr().err
    assert "✓ docgen done" in err


# —— §1.2 可诊断：error/warn 的 exc_info 附首错 traceback（B3-2）——

def test_error_exc_info_appends_traceback(capsys):
    try:
        raise RuntimeError("boom-ERR99999")
    except RuntimeError:
        Logger.error("NPU 运行时缺失", exc_info=True)
    err = capsys.readouterr().err
    assert "[ERROR] NPU 运行时缺失" in err
    assert "Traceback" in err
    assert "RuntimeError" in err
    assert "boom-ERR99999" in err


def test_warn_exc_info_appends_traceback(capsys):
    try:
        raise ValueError("init-failed")
    except ValueError:
        Logger.warn("smoke 失败", exc_info=True)
    err = capsys.readouterr().err
    assert "[WARN] smoke 失败" in err
    assert "Traceback" in err
    assert "ValueError" in err


def test_error_default_no_traceback(capsys):
    # exc_info 默认 False：普通调用不打 traceback（向后兼容，无噪音）。
    Logger.error("plain")
    err = capsys.readouterr().err
    assert "[ERROR] plain" in err
    assert "Traceback" not in err


def test_exc_info_without_active_exception_is_noop(capsys):
    # 不在 except 块时 format_exc() 返回 "NoneType: None"，应被过滤（不打垃圾行）。
    Logger.error("msg", exc_info=True)
    err = capsys.readouterr().err
    assert "[ERROR] msg" in err
    assert "NoneType" not in err
    assert "Traceback" not in err
