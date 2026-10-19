"""UT for cann-bench-eval/scripts/perf_eval.py (skill self-contained, pure logic).

Deterministic no-LLM/no-NPU guard on the perf-only contract:
  - cases.csv 解析（cann-bench 约定列 → 归一化 case dict，sentinel / 原生 attrs 类型）
  - 输入生成（固定 seed 确定性、NaN/Inf 哨兵）
  - 聚合口径（kernel/torch_npu 均值、geo_speedup 几何平均、faster 计数、
    verdict=measured/no 与 partial 覆盖语义）

torch/torch_npu 依赖均在函数内部懒加载——本 UT 只测纯逻辑，不依赖 NPU/LLM
（不标 npu/llm，§3.5 标记语义）。
"""
from __future__ import annotations

import csv
import importlib.util
import math
import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest

_SKILL_SCRIPT = (
    Path(__file__).resolve().parent.parent.parent.parent
    / ".claude" / "skills" / "cann-bench-eval" / "scripts" / "perf_eval.py"
)


def _load_perf_eval():
    spec = importlib.util.spec_from_file_location("_perf_eval_ut", _SKILL_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


perf_eval = _load_perf_eval()


def _write_cases_csv(rows: list[dict]) -> str:
    fd = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", delete=False, newline="", encoding="utf-8")
    try:
        writer = csv.DictWriter(fd, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    finally:
        fd.close()
    return fd.name


class TestLoadCases:
    """cann-bench cases.csv → 归一化 case dict。"""

    def test_basic_columns(self):
        path = _write_cases_csv([
            {"operator": "op", "case_id": "1", "input_shape": "[[2048]]",
             "dtype": '["float16"]', "attrs": "{}",
             "value_range": "[-1, 1]", "note": "typical"},
            {"operator": "op", "case_id": "2", "input_shape": "[[2, 8]]",
             "dtype": '["bfloat16"]', "attrs": '{"alpha": 2}',
             "value_range": '["nan", "nan"]', "note": "nan"},
        ])
        try:
            cases = perf_eval.load_cases(path)
        finally:
            Path(path).unlink(missing_ok=True)
        assert len(cases) == 2
        assert cases[0]["case_id"] == 1
        assert cases[0]["shape"] == (2048,)
        assert cases[0]["dtype"] == "float16"
        assert cases[0]["value_range"] == (-1.0, 1.0)
        assert cases[1]["shape"] == (2, 8)
        assert cases[1]["dtype"] == "bfloat16"

    def test_attrs_keep_native_json_types(self):
        """attrs 保持 JSON 原生类型（int 不被压成 float）——PTA kwargs 直传。"""
        path = _write_cases_csv([
            {"operator": "op", "case_id": "1", "input_shape": "[[8]]",
             "dtype": '["float32"]', "attrs": '{"n": 3, "flag": true, "s": "x"}',
             "value_range": "[-1, 1]", "note": ""},
        ])
        try:
            cases = perf_eval.load_cases(path)
        finally:
            Path(path).unlink(missing_ok=True)
        assert cases[0]["attrs"] == {"n": 3, "flag": True, "s": "x"}

    def test_value_range_sentinels(self):
        """NaN/Inf 哨兵（JSON 字符串形式，与 golden_compare._parse_vrange 同约定）。"""
        path = _write_cases_csv([
            {"operator": "op", "case_id": "1", "input_shape": "[[8]]",
             "dtype": '["float16"]', "attrs": "{}",
             "value_range": '["nan", "nan"]', "note": ""},
            {"operator": "op", "case_id": "2", "input_shape": "[[8]]",
             "dtype": '["float16"]', "attrs": "{}",
             "value_range": '["inf", "-inf"]', "note": ""},
        ])
        try:
            cases = perf_eval.load_cases(path)
        finally:
            Path(path).unlink(missing_ok=True)
        assert math.isnan(cases[0]["value_range"][0])
        assert math.isnan(cases[0]["value_range"][1])
        assert cases[1]["value_range"] == (float("inf"), float("-inf"))

    def test_invalid_case_id_rows_skipped(self):
        path = _write_cases_csv([
            {"operator": "op", "case_id": "bad", "input_shape": "[[8]]",
             "dtype": '["float16"]', "attrs": "{}",
             "value_range": "[-1, 1]", "note": ""},
        ])
        try:
            cases = perf_eval.load_cases(path)
        finally:
            Path(path).unlink(missing_ok=True)
        assert cases == []


class TestGenInput:
    """固定 seed 确定性 + 哨兵处理（对齐 KernelLaunch 输入生成约定）。"""

    def test_same_seed_deterministic(self):
        a = perf_eval.gen_input((16,), -1.0, 1.0, 42)
        b = perf_eval.gen_input((16,), -1.0, 1.0, 42)
        np.testing.assert_array_equal(a, b)
        assert a.dtype == np.float32

    def test_nan_sentinel_all_nan(self):
        x = perf_eval.gen_input((8,), float("nan"), float("nan"), 42)
        assert np.isnan(x).all()

    def test_inf_sentinel_contains_inf(self):
        x = perf_eval.gen_input((1024,), float("inf"), float("inf"), 42)
        assert np.isinf(x).any()


def _case(cid, k_us, r_us, k_err=None, r_err=None):
    return {
        "case_id": cid,
        "kernel": None if k_us is None else {"mean_us": k_us},
        "torch_npu": None if r_us is None else {"mean_us": r_us},
        "speedup": (r_us / k_us) if (k_us and r_us) else None,
        "faster": (k_us < r_us) if (k_us and r_us) else None,
        "kernel_error": k_err,
        "ref_error": r_err,
    }


class TestAggregate:
    """聚合口径：均值 / geo_speedup 几何平均 / faster 计数 / verdict 语义。"""

    def test_measured_full_coverage(self):
        agg = perf_eval.aggregate([
            _case(1, 10.0, 40.0),   # speedup 4.0, faster
            _case(2, 20.0, 10.0),   # speedup 0.5, slower
        ])
        assert agg["verdict"] == "measured"
        assert agg["total_cases"] == 2
        assert agg["complete_cases"] == 2
        assert agg["kernel_mean_us"] == pytest.approx(15.0)
        assert agg["torch_npu_mean_us"] == pytest.approx(25.0)
        # geo = sqrt(4.0 * 0.5) = sqrt(2)
        assert agg["geo_speedup"] == pytest.approx(math.sqrt(2.0))
        assert agg["faster_cases"] == 1

    def test_measured_partial_coverage_visible(self):
        """partial 覆盖仍是 measured，complete < total 如实可见（不静默丢弃）。"""
        agg = perf_eval.aggregate([
            _case(1, 10.0, 40.0),
            _case(2, None, 5.0, k_err="boom"),   # kernel 失败 → 不入 complete
        ])
        assert agg["verdict"] == "measured"
        assert agg["complete_cases"] == 1
        assert agg["total_cases"] == 2
        assert agg["kernel_mean_us"] == pytest.approx(10.0)
        assert agg["faster_cases"] == 1

    def test_no_complete_case_verdict_no_with_reason(self):
        agg = perf_eval.aggregate([
            _case(1, None, None, k_err="env", r_err=None),
            _case(2, None, None, k_err="env", r_err=None),
        ])
        assert agg["verdict"] == "no"
        assert "env" in agg["reason"]
        assert "kernel_mean_us" not in agg

    def test_ref_only_failure_reason_surfaced(self):
        agg = perf_eval.aggregate([
            _case(1, 10.0, None, r_err="golden cannot run on NPU"),
        ])
        assert agg["verdict"] == "no"
        assert "golden cannot run on NPU" in agg["reason"]
