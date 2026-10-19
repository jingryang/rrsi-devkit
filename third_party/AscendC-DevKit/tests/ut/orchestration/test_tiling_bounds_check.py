"""UT for the A5 tiling_bounds_check.py helper script.

The script is a standalone tool provisioned into ``{debug_dir}/scripts/`` and
invoked by the kernel_debug skill as a pre-DumpTensor diagnostic.  These tests
exercise its pure parsing/checking functions and the ``run_check`` entry point
so the P0 tiling bounds check is not shipped unguarded.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_SCRIPT = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "ascendc_devkit"
    / "orchestration"
    / "stages"
    / "precision_debug_a5"
    / "scripts"
    / "tiling_bounds_check.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("tiling_bounds_check", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tbc():
    return _load_module()


def _sample_kernel():
    return """
#include "kernel_operator.h"
using namespace AscendC;
constexpr int BLOCK = 128;
constexpr int ubFactor = 64;

class KernelAdd {
public:
    __aicore__ inline KernelAdd() {}
    __aicore__ inline void Init(GM_ADDR x, GM_ADDR y, GM_ADDR out) {
        pipe.InitBuffer(inQ, 2, 32 * 1024);
        pipe.InitBuffer(outQ, 1, AlignUpKernel(32 * 1024, 32));
        pipe.InitBuffer(tmpBuf, 4096);
    }
    __aicore__ inline void Process() {
        LocalTensor<half> inLocal = inQ.AllocTensor<half>();
        LocalTensor<half> tmpLocal = tmpBuf.Get<half>();
        DataCopy(inLocal, tmpLocal);
        Cast(tmpLocal, inLocal, RoundMode::CAST_NONE, 16);
        Duplicate(tmpLocal, half(1), 16);
        Add(tmpLocal, inLocal, tmpLocal, 16);
        LocalTensor<half> outLocal = outQ.AllocTensor<half>();
        DataCopyPad(outLocal, tmpLocal);
    }
};
"""


# ── 纯解析函数 ─────────────────────────────────────────────────────────

def test_extract_init_buffers_parses_plain_and_tque(tbc):
    buf = tbc.extract_init_buffers(_sample_kernel(), dtype_size=2)
    # inQ is a TQue (num=2), outQ is a TBuf (num=1), tmpBuf is a TBuf.
    assert "inQ" in buf and "outQ" in buf and "tmpBuf" in buf
    assert buf["inQ"]["is_tque"] is True
    assert buf["inQ"]["num"] == 2
    assert buf["outQ"]["is_tque"] is False
    assert buf["inQ"]["capacity_bytes"] == 2 * tbc.align_up_kernel(32 * 1024, 32)
    # Buffers are laid out contiguously.
    assert buf["outQ"]["start_byte"] == buf["inQ"]["capacity_bytes"]


def test_extract_init_buffers_dedups_same_name(tbc):
    src = """
    pipe.InitBuffer(bufA, 1, 1024);
    pipe.InitBuffer(bufA, 1, 2048);
    """
    buf = tbc.extract_init_buffers(src, dtype_size=2)
    assert "bufA" in buf
    assert buf["bufA"]["capacity_bytes"] == 1024  # first wins


def test_extract_tiling_params_constants(tbc):
    params = tbc.extract_tiling_params(_sample_kernel())
    assert params["BLOCK"] == 128
    assert params["ubFactor"] == 64


def test_eval_expr_arithmetic(tbc):
    assert tbc._eval_expr("32 * 1024") == 32768
    assert tbc._eval_expr("4096 // 32") == 128
    # Unknown identifiers degrade to 0-conservative (integer fallback).
    assert isinstance(tbc._eval_expr("notDefined + 1"), int)


# ── 检查函数 ───────────────────────────────────────────────────────────

def test_check_ub_oob_total_exceeds_hw(tbc):
    # Force total > 196608 UB budget with two large buffers.
    buf = {
        "a": {"start_byte": 0, "capacity_bytes": 120000, "is_tque": False},
        "b": {"start_byte": 120000, "capacity_bytes": 120000, "is_tque": False},
    }
    findings = tbc.check_ub_oob(buf, "", dtype_size=2, tiling_params={}, case_shape=[16])
    cats = {f["category"] for f in findings}
    assert "UB_TOTAL" in cats


def test_check_ub_oob_alignment(tbc):
    # outQ starts right after inQ's padded capacity — with the sample kernel
    # layout all starts are 32B-aligned by construction, so force a misaligned one.
    buf = {"bad": {"start_byte": 16, "capacity_bytes": 64, "is_tque": False}}
    findings = tbc.check_ub_oob(buf, "", dtype_size=2, tiling_params={}, case_shape=[16])
    assert any(f["category"] == "ALIGN_32B" and f["start_byte"] == 16 for f in findings)


def test_check_tail_block_uneven(tbc):
    findings = tbc.check_tail_block(
        case_shape=[130], tiling_params={"blockFactorB": 64},
    )
    assert any(f["category"] == "tail_block" and f["dim_size"] == 130 for f in findings)


def test_check_tail_block_even_no_finding(tbc):
    findings = tbc.check_tail_block(
        case_shape=[128], tiling_params={"blockFactorB": 64},
    )
    assert not any(f["category"] == "tail_block" for f in findings)


# ── run_check 集成 ─────────────────────────────────────────────────────

def test_run_check_ok_with_kernel_and_shape(tbc, tmp_path):
    op_dir = tmp_path / "op"
    (op_dir / "op_kernel").mkdir(parents=True)
    (op_dir / "op_kernel" / "kernel_add.cpp").write_text(
        _sample_kernel(), encoding="utf-8")
    result = tbc.run_check(
        str(op_dir), case_json={"shape": [128, 128], "dtype": "float16"},
    )
    assert result["status"] in ("ok", "findings")
    assert result["buffer_map"]
    assert result["case_shape"] == [128, 128]


def test_run_check_no_shape_skips(tbc, tmp_path):
    result = tbc.run_check(str(tmp_path), case_json={})
    assert result["status"] == "skipped"
    assert result["reason"] == "no shape in case"


def test_run_check_no_kernel_skips(tbc, tmp_path):
    op_dir = tmp_path / "empty_op"
    op_dir.mkdir()
    result = tbc.run_check(str(op_dir), case_json={"shape": [16]})
    assert result["status"] == "skipped"
    assert result["reason"] == "no kernel source found"


def test_parse_init_buffer_call_aligns_32b(tbc):
    m = tbc._INIT_BUFFER_RE.search(
        "pipe.InitBuffer(bufX, 1, AlignUpKernel(4096, 32));")
    assert m is not None
    parsed = tbc._parse_init_buffer_call(m, dtype_size=2)
    assert parsed["name"] == "bufX"
    assert parsed["aligned_size"] == 4096
    assert parsed["capacity_bytes"] == 4096

