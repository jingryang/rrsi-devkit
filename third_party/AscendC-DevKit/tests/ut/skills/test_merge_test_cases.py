"""UT for ascendc-st-design/scripts/merge_test_cases.py (skill self-contained).

Deterministic no-LLM guard on the L0/L1/L2 → 13-column merge contract:
  - error_type 结构信号列优先（m4：不依赖 testcase_name 命名约定，§2.12/§1.12）
  - 名字匹配 fallback 仅对无 error_type 列的旧 CSV 生效
  - 合并仍产出 13 列下游契约（stc_* 为合法 Python tuple/list repr，ast 可解析）
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest

from ascendc_devkit.adapters.testdesign.csv_to_testcases import parse_testcase_csv

try:
    from ascendc_devkit.adapters.testdesign.convert_to_param_def import convert
except Exception:  # pragma: no cover — adapter moved to framework; not needed here
    convert = None

_SKILL_SCRIPTS = (
    Path(__file__).resolve().parent.parent.parent.parent
    / ".claude" / "skills" / "ascendc-st-design" / "scripts"
)


def _load_merge():
    import importlib.util
    import sys

    path = _SKILL_SCRIPTS / "merge_test_cases.py"
    spec = importlib.util.spec_from_file_location("_merge_test_cases_ut", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


merge_module = _load_merge()


class TestDetectErrorStructural:
    """m4: error_type 结构信号优先，名字匹配仅作旧格式 fallback。"""

    def test_structural_error_type_wins(self):
        m = merge_module
        row = {"error_type": "dimension_overflow",
               "testcase_name": "aclnnX_float32_random_y_dim_exception"}
        assert m._detect_error(row) == "dimension exceeds maximum supported rank (8)"

    def test_structural_unknown_type_falls_to_generic(self):
        m = merge_module
        row = {"error_type": "new_future_type",
               "testcase_name": "aclnnX_whatever"}
        assert m._detect_error(row) == "exception case"

    def test_no_error_type_uses_name_fallback(self):
        m = merge_module
        row = {"error_type": "", "testcase_name": "aclnnX_float32_y_format_exception"}
        assert m._detect_error(row) == "unsupported format (only ND supported)"

    def test_normal_case_no_error(self):
        m = merge_module
        assert m._detect_error({"error_type": "", "testcase_name": "aclnnX_L0_001"}) == ""


class TestMergeProduces13ColumnContract:
    """merge 主流程：L0/L1 CSV → 13 列契约，下游 parse_testcase_csv 可解析。"""

    def _write_l0(self, d: Path) -> Path:
        # 构造一行 L0 CSV（TTK 风格中间格式：api_name/tensor_view_shapes…）
        l0 = d / "aclnnAdd_l0_test_cases.csv"
        rows = [
            ["testcase_name", "api_name", "tensor_view_shapes", "tensor_dtypes",
             "scalar_dtypes", "attributes", "output_tensor_indexes",
             "precision_tolerances", "absolute_precision", "input_data_ranges",
             "scalar_data_ranges", "tensor_list_distribution", "error_type"],
            ["aclnnAdd_L0_001", "aclnnAdd", "((3,3,),)", "('float32',)",
             "", "", "(1,)", "", "1e-05", "((-100,100,),)", "", "", ""],
        ]
        with l0.open("w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(rows)
        return l0

    def test_merge_output_parses(self, tmp_path):
        m = merge_module
        self._write_l0(tmp_path)
        rows = m.merge(
            testcase_dir=tmp_path, l0="aclnnAdd_l0_test_cases.csv",
            l1="", l2="", op_name="add", aclnn_name="aclnnAdd",
            default_precision="1e-05", default_format="ND")
        assert len(rows) == 1
        assert list(rows[0].keys()) == m.TARGET_HEADER  # 13 列契约
        # stc_* 必须是合法 Python repr（ast 可解析）
        merged = tmp_path / "merged" / "合并_测试用例.csv"
        merged.parent.mkdir(parents=True)
        with merged.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=m.TARGET_HEADER)
            w.writeheader()
            w.writerows(rows)
        cases = parse_testcase_csv(merged)
        assert len(cases) == 1
        assert cases[0].name == "aclnnAdd_L0_001"
        assert cases[0].inputs[0]["dtype"] == "float32"
        assert cases[0].inputs[0]["shape"] == [3, 3]


class TestOptionalInputPlaceholder:
    """缺省可选输入在 merge 后保留 ``None`` 位置占位（镜像 cann-bench null）。

    中间 TTK 格式用裸 ``None`` 标记缺省可选输入位；merge 必须逐位透传到
    ``stc_inputs``/``stc_input_dtypes``/``stc_input_formats``，**不得压缩**——
    压缩会使其后输入整体上移，下游按位置绑定 golden/kernel 时错位。
    """

    def _write_l0(self, d: Path) -> Path:
        l0 = d / "aclnnMoe_l0_test_cases.csv"
        rows = [
            ["testcase_name", "api_name", "tensor_view_shapes", "tensor_dtypes",
             "scalar_dtypes", "attributes", "output_tensor_indexes",
             "precision_tolerances", "absolute_precision", "input_data_ranges",
             "scalar_data_ranges", "tensor_list_distribution", "error_type"],
            # proto inputs [A, B(absent), C], output at index 3
            ["aclnnMoe_L0_001", "aclnnMoe",
             "((2,3,),None,(4,5,),(2,5,),)",
             "('float16',None,'float16','float16',)",
             "", "", "(3,)", "", "1e-05", "((0,1,),None,(0,2,),)", "", "", ""],
        ]
        with l0.open("w", encoding="utf-8", newline="") as fh:
            csv.writer(fh).writerows(rows)
        return l0

    def test_absent_optional_keeps_none_placeholder(self, tmp_path):
        import ast
        m = merge_module
        self._write_l0(tmp_path)
        rows = m.merge(
            testcase_dir=tmp_path, l0="aclnnMoe_l0_test_cases.csv",
            l1="", l2="", op_name="moe", aclnn_name="aclnnMoe",
            default_precision="1e-05", default_format="ND")
        assert len(rows) == 1
        r = rows[0]
        assert ast.literal_eval(r["stc_inputs"]) == [(2, 3), None, (4, 5)]
        assert ast.literal_eval(r["stc_input_dtypes"]) == (
            "float16", None, "float16")
        assert ast.literal_eval(r["stc_input_formats"]) == ("ND", None, "ND")
        assert ast.literal_eval(r["stc_outputs"]) == [(2, 5)]

    def test_placeholder_roundtrips_through_adapter(self, tmp_path):
        """merge 产物 → adapter：缺省位被跳过，存在输入打上 proto_idx。"""
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        m = merge_module
        self._write_l0(tmp_path)
        rows = m.merge(
            testcase_dir=tmp_path, l0="aclnnMoe_l0_test_cases.csv",
            l1="", l2="", op_name="moe", aclnn_name="aclnnMoe",
            default_precision="1e-05", default_format="ND")
        merged = tmp_path / "合并_测试用例.csv"
        with merged.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=m.TARGET_HEADER)
            w.writeheader()
            w.writerows(rows)
        op = OperatorSpec(
            name="moe",
            inputs=[TensorSpec(name="a", param_type="REQUIRED"),
                    TensorSpec(name="b", param_type="OPTIONAL"),
                    TensorSpec(name="c", param_type="REQUIRED")],
            outputs=[TensorSpec(name="out")])
        (c,) = parse_testcase_csv(merged, operator=op)
        assert [i["name"] for i in c.inputs] == ["a", "c"]
        assert [i["proto_idx"] for i in c.inputs] == [0, 2]
        assert c.inputs[1]["shape"] == [4, 5]
