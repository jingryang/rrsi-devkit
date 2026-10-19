"""Case-source provenance (st-design vs cann-bench) for baseline reporting.

- The cann-bench loader stamps ``TestCase.source="cannbench"``; the test-design
  CSV adapter stamps ``"devkit"`` — set once at the producing loader (§1.12
  structural signal, no name guessing).
- ``case_source_composition`` is the single point (§1.15) that counts cases by
  source; the baseline stage uses it to drive the ``st-design-case: N/M`` line
  and to cross-check the agent-reported ``rc_result.by_source.devkit.total``.
"""
from __future__ import annotations

import csv
from pathlib import Path

from ascendc_devkit.domain.requirement import TestCase
from ascendc_devkit.orchestration.stages.precision_debug_a5.base import (
    case_source_composition,
)

_COLS = [
    "testcase_name", "op_name", "stc_input_dtypes", "other_compilation_params",
    "stc_inputs", "output_dtypes", "stc_outputs", "stc_input_formats",
    "output_formats", "stc_op_name", "input_data_ranges", "absolute_precision",
    "error_message",
]


def _write_cann_bench_csv(path: Path, n: int = 2) -> Path:
    header = ["operator", "case_id", "input_shape", "dtype", "attrs",
              "value_range", "note"]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for i in range(1, n + 1):
            w.writerow(["Foo", str(i), "[[2,3]]", '["float32"]', "{}",
                        "[0,1]", ""])
    return path


def _write_testdesign_csv(path: Path, n: int = 3) -> Path:
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=_COLS)
        w.writeheader()
        for i in range(1, n + 1):
            w.writerow({
                "testcase_name": f"aclnnFoo_L0_{i:03d}",
                "op_name": "Foo",
                "stc_input_dtypes": "('float32',)",
                "other_compilation_params": "{}",
                "stc_inputs": "((2,3),)",
                "output_dtypes": "('float32',)",
                "stc_outputs": "((2,3),)",
                "stc_input_formats": "('ND',)",
                "output_formats": "('ND',)",
                "stc_op_name": "aclnnFoo",
                "input_data_ranges": "((0,1,),)",
                "absolute_precision": "1e-5",
                "error_message": "",
            })
    return path


def test_cann_bench_loader_stamps_source(tmp_path):
    from ascendc_devkit.domain.cann_bench_cases_loader import load_cann_bench_cases
    cases = load_cann_bench_cases(_write_cann_bench_csv(tmp_path / "cases.csv"))
    assert cases
    assert all(c.source == "cannbench" for c in cases)


def test_testdesign_adapter_stamps_source(tmp_path):
    from ascendc_devkit.adapters.testdesign.csv_to_testcases import parse_testcase_csv
    cases = parse_testcase_csv(_write_testdesign_csv(tmp_path / "cases.csv"))
    assert cases
    assert all(c.source == "devkit" for c in cases)


def test_composition_counts_by_source():
    cases = (
        [TestCase(name=f"c{i}", source="cannbench") for i in range(20)]
        + [TestCase(name=f"d{i}", source="devkit") for i in range(116)]
        + [TestCase(name="legacy")]  # no source → unknown, never folded
    )
    comp = case_source_composition(cases)
    assert comp == {"cannbench": 20, "devkit": 116, "unknown": 1}


def test_composition_empty_and_none():
    assert case_source_composition([]) == {
        "cannbench": 0, "devkit": 0, "unknown": 0}
    assert case_source_composition(None) == {
        "cannbench": 0, "devkit": 0, "unknown": 0}


def test_baseline_prompt_renders_composition_and_split_instruction():
    from ascendc_devkit.orchestration.stages.precision_debug_a5.baseline import (
        BaselineSubstage,
    )
    ctx = {
        "debug_dir": "/tmp/dbg",
        "code_dir": "/tmp/code",
        "phase_json_latest_path": "/tmp/dbg/baseline/baseline_result.json",
        "op_name": "foo",
        "test_case_source_composition": {
            "cannbench": 20, "devkit": 116, "unknown": 0},
    }
    prompt = BaselineSubstage()._phase_prompt(ctx, 1)
    assert "cannbench=20, devkit(st-design)=116" in prompt
    assert "rc_result.by_source" in prompt
    # rc_pass marker = cann-bench subset (same basis as kl_pass), not the merged total
    assert "`rc_pass` 行取 cann-bench 子集" in prompt
    assert "by_source.cannbench" in prompt
    assert "st-design-case" in prompt
