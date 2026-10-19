"""Unit tests for KernelLaunch golden_compare — no NPU required."""

import sys
import tempfile
from pathlib import Path

import numpy as np
import pytest
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from KernelLaunch.golden_compare import (
    _is_numpy_bfloat16,
    _normalize_outputs,
    _to_np,
    _to_np_list,
    _to_torch_golden,
    _to_torch_kernel,
    compare_outputs,
    load_golden,
)


# ---------------------------------------------------------------------------
#  _to_np / _to_np_list
# ---------------------------------------------------------------------------

class TestToNp:
    def test_numpy_unchanged(self):
        arr = np.array([1.0, 2.0])
        assert np.array_equal(_to_np(arr), arr)

    def test_torch_tensor_to_numpy(self):
        import torch
        t = torch.tensor([1.0, 2.0])
        result = _to_np(t)
        assert isinstance(result, np.ndarray)
        assert np.allclose(result, [1.0, 2.0])

    def test_plain_number(self):
        result = _to_np(3.0)
        assert np.allclose(result, 3.0)


class TestToNpList:
    def test_single_array(self):
        arr = np.array([1.0])
        result = _to_np_list(arr)
        assert len(result) == 1
        assert np.array_equal(result[0], [1.0])

    def test_list(self):
        arrs = [np.array([1.0]), np.array([2.0, 3.0])]
        result = _to_np_list(arrs)
        assert len(result) == 2

    def test_tuple(self):
        result = _to_np_list((np.array([1.0]),))
        assert len(result) == 1


# ---------------------------------------------------------------------------
#  _normalize_outputs
# ---------------------------------------------------------------------------

class TestNormalizeOutputs:
    def test_single_array(self):
        arr = np.array([1.0])
        result = _normalize_outputs(arr)
        assert len(result) == 1

    def test_list(self):
        result = _normalize_outputs([np.array([1.0]), np.array([2.0])])
        assert len(result) == 2


# ---------------------------------------------------------------------------
#  _is_numpy_bfloat16
# ---------------------------------------------------------------------------

class TestIsNumpyBfloat16:
    def test_ordinary_array(self):
        assert not _is_numpy_bfloat16(np.array([1.0], dtype=np.float32))

    def test_unknown_type_no_dtype(self):
        assert not _is_numpy_bfloat16("not an array")


# ---------------------------------------------------------------------------
#  _to_torch_kernel / _to_torch_golden
# ---------------------------------------------------------------------------

class TestToTorch:
    def test_kernel_fp32(self):
        arr = np.array([1.0, 2.0], dtype=np.float32)
        t = _to_torch_kernel(arr)
        assert t.dtype == torch.float32

    def test_kernel_fp16(self):
        arr = np.array([1.0, 2.0], dtype=np.float16)
        t = _to_torch_kernel(arr)
        assert t.dtype == torch.float16

    def test_golden_fp32_to_fp64(self):
        arr = np.array([1.0, 2.0], dtype=np.float32)
        t = _to_torch_golden(arr)
        assert t.dtype == torch.float64


# ---------------------------------------------------------------------------
#  load_golden
# ---------------------------------------------------------------------------

GOLDEN_ADD_PY = """
import numpy as np

def reference(a, b):
    return a + b

def add_torch(a, b):
    import torch
    return a + b

def multi_out(a, b):
    return a + b, a - b
"""

GOLDEN_TORCH_PY = """
def rms_norm(x, gamma, epsilon=1e-6):
    import torch
    return x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + epsilon) * gamma
"""


class TestLoadGolden:
    def test_load_and_call_numpy(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(GOLDEN_ADD_PY)
            f.flush()
            fn = load_golden(f.name, entry="reference")

        a = np.array([1.0, 2.0, 3.0])
        b = np.array([4.0, 5.0, 6.0])
        result = fn(a, b)
        assert len(result) == 1
        np.testing.assert_array_equal(result[0], a + b)

    def test_multi_output(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(GOLDEN_ADD_PY)
            f.flush()
            fn = load_golden(f.name, entry="multi_out")

        a = np.array([1.0, 2.0])
        b = np.array([3.0, 4.0])
        result = fn(a, b)
        assert len(result) == 2
        np.testing.assert_array_equal(result[0], a + b)
        np.testing.assert_array_equal(result[1], a - b)

    def test_load_torch(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(GOLDEN_ADD_PY)
            f.flush()
            fn = load_golden(f.name, entry="add_torch", input_type="torch")

        a = np.array([1.0, 2.0])
        b = np.array([3.0, 4.0])
        result = fn(a, b)
        assert len(result) == 1
        np.testing.assert_allclose(result[0], [4.0, 6.0])

    def test_entry_not_found_raises(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(GOLDEN_ADD_PY)
            f.flush()
            with pytest.raises(ValueError, match="golden entry 'nonexistent' not found"):
                load_golden(f.name, entry="nonexistent")

    def test_not_py_extension_raises(self):
        with pytest.raises(ValueError, match="must be a .py file"):
            load_golden("not_a_python_file.txt")


# ---------------------------------------------------------------------------
#  compare_outputs
# ---------------------------------------------------------------------------

class TestCompareOutputs:
    def test_identical_outputs_pass(self):
        out = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        golden = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        result = compare_outputs(out, golden)
        assert result["passed"]
        assert result["max_diff"] == 0.0

    def test_fp32_within_threshold_passes(self):
        out = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        golden = np.array([1.0, 2.0, 3.00001], dtype=np.float64)
        result = compare_outputs(out, golden)
        assert result["passed"]

    def test_grossly_wrong_fails(self):
        out = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        golden = np.array([100.0, 200.0, 300.0], dtype=np.float64)
        result = compare_outputs(out, golden)
        assert not result["passed"]
        assert result["mare"] > 0.0

    def test_single_output_not_list(self):
        out = np.array([1.0, 2.0], dtype=np.float32)
        golden = np.array([1.0, 2.0], dtype=np.float64)
        result = compare_outputs(out, golden)
        assert result["passed"]

    def test_per_output_field(self):
        out = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        golden = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        result = compare_outputs(out, golden)
        assert len(result["per_output"]) == 1
        po = result["per_output"][0]
        assert po["passed"]
        assert po["dtype"] == "float32"

    def test_int_passes_bit_exact(self):
        out = np.array([1, 2, 3], dtype=np.int32)
        golden = np.array([1, 2, 3], dtype=np.int64)
        result = compare_outputs(out, golden)
        assert result["passed"]

    def test_int_fails_on_difference(self):
        out = np.array([1, 2, 3], dtype=np.int32)
        golden = np.array([1, 2, 99], dtype=np.int64)
        result = compare_outputs(out, golden)
        assert not result["passed"]

    def test_custom_thresholds_override(self):
        out = np.array([1.0, 2.0, 3.0], dtype=np.float16)
        golden = np.array([1.0, 2.0, 3.1], dtype=np.float64)
        # 3.1 vs 3.0: diff ≈ 3.3%, with default float16 threshold 2^-10 ≈ 0.1%
        # this should fail.  But with a very loose threshold, should pass.
        result_default = compare_outputs(out, golden)
        assert not result_default["passed"]

        result_loose = compare_outputs(
            out, golden, thresholds={"float16": 99.0}
        )
        assert result_loose["passed"]

    def test_proto_override_highest_priority(self):
        out = np.array([1, 2, 3], dtype=np.int32)
        golden = np.array([1, 2, 9], dtype=np.int64)
        result = compare_outputs(out, golden, proto={"int32": 99.0})
        assert result["passed"]

    def test_multi_output_list(self):
        out = [np.array([1.0, 2.0], dtype=np.float32),
               np.array([3.0, 4.0], dtype=np.float32)]
        golden = [np.array([1.0, 2.0], dtype=np.float64),
                  np.array([3.0, 4.0], dtype=np.float64)]
        result = compare_outputs(out, golden)
        assert result["passed"]
        assert len(result["per_output"]) == 2

    def test_returns_all_fields(self):
        out = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        golden = np.array([1.0, 2.0, 3.0], dtype=np.float64)
        result = compare_outputs(out, golden)
        for key in ("passed", "mere", "mare", "max_diff", "mean_diff",
                     "mismatch_count", "total_count", "threshold", "dtype",
                     "error_msg", "per_output"):
            assert key in result

    def test_dtype_in_result(self):
        out = np.array([1.0, 2.0], dtype=np.float32)
        golden = np.array([1.0, 2.0], dtype=np.float64)
        result = compare_outputs(out, golden)
        assert result["dtype"] == "float32"
        assert result["per_output"][0]["dtype"] == "float32"


# ---------------------------------------------------------------------------
#  End-to-end: load_golden + compare_outputs
# ---------------------------------------------------------------------------

class TestLoadGoldenRealFile:
    """Verify load_golden works with the golden.py shipped in examples/."""

    def test_load_examples_golden_py(self):
        import pathlib
        golden_path = pathlib.Path(__file__).resolve().parents[0].joinpath(
            "..", "examples", "golden.py"
        )
        if not golden_path.exists():
            pytest.skip("golden.py not found (examples not shipped with test?)")

        fn = load_golden(str(golden_path), entry="add")
        assert callable(fn)

        a = np.array([1.0, 2.0, 3.0])
        b = np.array([4.0, 5.0, 6.0])
        result = fn(a, b)
        assert len(result) == 1
        np.testing.assert_array_equal(result[0], [5.0, 7.0, 9.0])


class TestEndToEnd:
    def test_load_then_compare(self):
        """Full flow: load golden.py, call it, compare with devkit standard."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(GOLDEN_ADD_PY)
            f.flush()
            fn = load_golden(f.name, entry="reference")

        a = np.random.randn(32).astype(np.float32)
        b = np.random.randn(32).astype(np.float32)
        golden = fn(a, b)

        # kernel output = golden output (simulates a perfect kernel)
        result = compare_outputs(golden[0].astype(np.float32), golden)
        assert result["passed"]

    def test_load_then_compare_multi_out(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(GOLDEN_ADD_PY)
            f.flush()
            fn = load_golden(f.name, entry="multi_out")

        a = np.random.randn(32).astype(np.float32)
        b = np.random.randn(32).astype(np.float32)
        golden = fn(a, b)

        # simulate kernel with slight error on output[1]
        kernel_out = [golden[0].astype(np.float32),
                      (golden[1] + 1e-3).astype(np.float32)]
        result = compare_outputs(kernel_out, golden)
        assert not result["passed"]
        assert result["per_output"][0]["passed"]
        assert not result["per_output"][1]["passed"]
