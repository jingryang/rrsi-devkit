"""P2 (step-4) — CSV→TestCase adapter (anti-corruption layer).

The testdesign skill chain emits 13-column spec-style CSV (UTF-8-BOM,
repr-tuple fields). This adapter normalizes a CSV file into domain TestCase
objects. Field values below are taken verbatim from the real skill samples
(generate-case-skill/tmp_用例生成/*.csv) — no fabricated structure.
"""

from __future__ import annotations

import csv
import math
import io
from pathlib import Path

import pytest

from ascendc_devkit.adapters.testdesign.csv_to_testcases import parse_testcase_csv
from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
from ascendc_devkit.domain.requirement import TestCase


_COLS = [
    "testcase_name", "op_name", "stc_input_dtypes", "other_compilation_params",
    "stc_inputs", "output_dtypes", "stc_outputs", "stc_input_formats",
    "output_formats", "stc_op_name", "input_data_ranges", "absolute_precision",
    "error_message",
]

# Verbatim real row values (boundary CSV): an op and its grad.
_ROW_OP = {
    "testcase_name": "manifold_constrained_hyper_connection_post_1_524288_8_24576_bf16_L1_boundary_000009",
    "op_name": "manifold_constrained_hyper_connection_post",
    "stc_input_dtypes": "('bfloat16', 'float32', 'bfloat16', 'float32')",
    "other_compilation_params": "",
    "stc_inputs": "((1, 524288, 8, 24576), (1, 524288, 8, 8), (1, 524288, 24576), (1, 524288, 8))",
    "output_dtypes": "('bfloat16',)",
    "stc_outputs": "((1, 524288, 8, 24576),)",
    "stc_input_formats": "('ND', 'ND', 'ND', 'ND')",
    "output_formats": "('ND',)",
    "stc_op_name": "manifold_constrained_hyper_connection_post",
    "input_data_ranges": "",
    "absolute_precision": "",
    "error_message": "",
}
_ROW_GRAD = {
    "testcase_name": "manifold_constrained_hyper_connection_post_grad_1_524288_8_24576_bf16_L1_boundary_000009",
    "op_name": "manifold_constrained_hyper_connection_post_grad",
    "stc_input_dtypes": "('bfloat16', 'bfloat16', 'float32', 'bfloat16', 'float32')",
    "other_compilation_params": "",
    "stc_inputs": "((1, 524288, 8, 24576), (1, 524288, 8, 24576), (1, 524288, 8, 8), (1, 524288, 24576), (1, 524288, 8))",
    "output_dtypes": "('bfloat16', 'float32', 'bfloat16', 'float32')",
    "stc_outputs": "((1, 524288, 8, 24576), (1, 524288, 8, 8), (1, 524288, 24576), (1, 524288, 8))",
    "stc_input_formats": "('ND', 'ND', 'ND', 'ND', 'ND')",
    "output_formats": "('ND', 'ND', 'ND', 'ND')",
    "stc_op_name": "manifold_constrained_hyper_connection_post_grad",
    "input_data_ranges": "",
    "absolute_precision": "",
    "error_message": "",
}


def _write_csv(tmp_path, *rows, bom=True, cols=_COLS):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, quoting=csv.QUOTE_ALL)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    p = tmp_path / "cases.csv"
    p.write_text(buf.getvalue(), encoding="utf-8-sig" if bom else "utf-8")
    return p


def _row(**overrides):
    r = dict(_ROW_OP)
    r.update(overrides)
    return r


class TestNormalRows:
    def test_two_rows_two_cases(self, tmp_path):
        cases = parse_testcase_csv(_write_csv(tmp_path, _ROW_OP, _ROW_GRAD))
        assert len(cases) == 2
        assert all(isinstance(c, TestCase) for c in cases)

    def test_op_row_name_and_inputs(self, tmp_path):
        (c,) = parse_testcase_csv(_write_csv(tmp_path, _ROW_OP))
        assert c.name == _ROW_OP["testcase_name"]
        assert len(c.inputs) == 4
        first = c.inputs[0]
        assert first["shape"] == [1, 524288, 8, 24576]
        assert first["dtype"] == "bfloat16"
        assert first["format"] == "ND"
        assert first["name"] == "input_0"

    def test_grad_is_independent_case(self, tmp_path):
        cases = parse_testcase_csv(_write_csv(tmp_path, _ROW_OP, _ROW_GRAD))
        grad = cases[1]
        assert grad.name.startswith("manifold_constrained_hyper_connection_post_grad")
        assert len(grad.inputs) == 5

    def test_default_generator(self, tmp_path):
        (c,) = parse_testcase_csv(_write_csv(tmp_path, _ROW_OP))
        assert c.generator == "random_uniform"

    def test_single_input_collapse_wrapped(self, tmp_path):
        # ast.literal_eval("((1,2,3))") collapses to a flat int tuple; the
        # adapter must treat it as ONE input shape, not three scalar inputs.
        r = _row(
            stc_input_dtypes="('float16',)",
            stc_inputs="((1, 2, 3))",
            stc_input_formats="('ND')",
        )
        (c,) = parse_testcase_csv(_write_csv(tmp_path, r))
        assert len(c.inputs) == 1
        assert c.inputs[0]["shape"] == [1, 2, 3]
        assert c.inputs[0]["dtype"] == "float16"
        assert c.inputs[0]["format"] == "ND"


class TestBomHandling:
    def test_bom_stripped(self, tmp_path):
        (c,) = parse_testcase_csv(_write_csv(tmp_path, _ROW_OP, bom=True))
        assert c.name == _ROW_OP["testcase_name"]

    def test_no_bom_also_ok(self, tmp_path):
        (c,) = parse_testcase_csv(_write_csv(tmp_path, _ROW_OP, bom=False))
        assert c.name == _ROW_OP["testcase_name"]


class TestPrecision:
    def test_empty_precision_expected_none(self, tmp_path):
        (c,) = parse_testcase_csv(_write_csv(tmp_path, _ROW_OP))
        assert c.expected is None

    def test_numeric_precision_max_diff(self, tmp_path):
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(absolute_precision="0.001")))
        assert c.expected == {"max_diff": 0.001}

    def test_prose_precision_does_not_crash(self, tmp_path):
        # perf CSVs put prose in absolute_precision; must not break float parse.
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(absolute_precision="相比小算子拼接性能提升10倍以上")))
        assert c.expected is None


class TestOptionalInputPlaceholders:
    """缺省可选输入以 ``None`` 占位（镜像 cann-bench ``null``）：adapter 跳过缺省
    位，为存在输入保留 proto 位置（``proto_idx``）。"""

    def _op(self, **dtypes):
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        return OperatorSpec(
            name="moe",
            inputs=[TensorSpec(name="a", param_type="REQUIRED"),
                    TensorSpec(name="b", param_type=dtypes.get("b", "OPTIONAL")),
                    TensorSpec(name="c", param_type="REQUIRED")],
            outputs=[TensorSpec(name="out")])

    def test_none_placeholder_skipped_and_proto_idx_kept(self, tmp_path):
        r = _row(
            testcase_name="moe_c1",
            stc_input_dtypes="('float16',None,'float16')",
            stc_inputs="[(2,3,),None,(4,5,)]",
            stc_input_formats="('ND',None,'ND')",
        )
        (c,) = parse_testcase_csv(_write_csv(tmp_path, r), operator=self._op())
        assert [i["name"] for i in c.inputs] == ["a", "c"]
        assert [i["proto_idx"] for i in c.inputs] == [0, 2]
        assert [i["shape"] for i in c.inputs] == [[2, 3], [4, 5]]

    def test_absent_required_input_raises(self, tmp_path):
        r = _row(
            testcase_name="moe_c2",
            stc_input_dtypes="(None,'float16','float16')",
            stc_inputs="[None,(3,),(4,)]",
            stc_input_formats="(None,'ND','ND')",
        )
        with pytest.raises(ValueError, match="not\\s+declared OPTIONAL"):
            parse_testcase_csv(_write_csv(tmp_path, r), operator=self._op())

    def test_flat_path_keeps_proto_idx(self, tmp_path):
        # No op_spec (skill-standalone): None still skipped, proto_idx preserved.
        r = _row(
            testcase_name="moe_c3",
            stc_input_dtypes="('float16',None,'float16')",
            stc_inputs="[(2,3,),None,(4,5,)]",
            stc_input_formats="('ND',None,'ND')",
        )
        (c,) = parse_testcase_csv(_write_csv(tmp_path, r))
        assert [(i["name"], i["proto_idx"]) for i in c.inputs] == [
            ("input_0", 0), ("input_2", 2)]


class TestRanges:
    """input_data_ranges → per-input value_range 挂载（只读消费者的唯一可执行形式）。

    事故背景：ranges 原样装箱进 generator_params.ranges（全仓零消费者），harness
    读不到 per-input value_range → 回退 [-1,1] → 受约束整数域输入（如类别索引）
    取到非法值。挂载语义与 cann_bench_cases_loader 对齐（Fix E 同款）。
    """

    def test_ranges_mounted_per_input_proto_path(self, tmp_path):
        op = OperatorSpec(name="op", inputs=[
            TensorSpec(name="logits", param_type="REQUIRED"),
            TensorSpec(name="targets", param_type="REQUIRED"),
            TensorSpec(name="predictions", param_type="REQUIRED"),
        ], outputs=[])
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(
                stc_inputs="((1,2,3,8,), (1,3,8,), (1,2,3,8),)",
                stc_input_dtypes="('bfloat16', 'int64', 'bfloat16')",
                input_data_ranges="((0,0,),(0,7,),(1,10,),)",
            )),
            operator=op)
        assert [i.get("value_range") for i in c.inputs] == [
            [0, 0], [0, 7], [1, 10]]

    def test_zero_zero_is_literal_range_not_null(self, tmp_path):
        # (0,0) 是因子候选被选中的字面区间（全零输入是有意的边界用例），
        # 不得当"无约束"丢弃（§1.13 忠实传递声明的事实）。
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(
                stc_inputs="((1, 8),)",
                stc_input_dtypes="('bfloat16',)",
                input_data_ranges="((0,0,),)",
            )))
        assert c.inputs[0]["value_range"] == [0, 0]

    def test_inf_nan_strings_become_floats(self, tmp_path):
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(
                stc_inputs="((1, 8), (1, 8),)",
                stc_input_dtypes="('float16', 'float32')",
                input_data_ranges="(('inf','-inf',),('nan','nan',),)",
            )))
        lo0, hi0 = c.inputs[0]["value_range"]
        lo1, hi1 = c.inputs[1]["value_range"]
        assert (lo0, hi0) == (float("inf"), float("-inf"))
        assert math.isnan(lo1) and math.isnan(hi1)

    def test_symbolic_range_raises_not_silent_fallback(self, tmp_path):
        # 引号内的符号串可解析但不可执行 = 上游设计产物非法 → 诚实报错，
        # 绝不回退默认 [-1,1] 静默制造非法输入（§3.7 / §1.3）。
        with pytest.raises(ValueError, match="C-1"):
            parse_testcase_csv(
                _write_csv(tmp_path, _row(
                    stc_inputs="((1,2,3,8,), (1,3,8,),)",
                    stc_input_dtypes="('bfloat16', 'int64')",
                    input_data_ranges="((0,0,),(0,'C-1',),)",
                )))

    def test_unquoted_symbolic_cell_hard_fails_not_raw_string_carry(self, tmp_path):
        # 事故原形（未加引号的 (0,C-1,)）：旧实现 literal_eval 失败后把**原始
        # 字符串**静默装箱进 generator_params.ranges（零消费者）——现在硬失败。
        with pytest.raises(ValueError, match="input_data_ranges"):
            parse_testcase_csv(
                _write_csv(tmp_path, _row(
                    stc_inputs="((1,2,3,8,), (1,3,8,),)",
                    stc_input_dtypes="('bfloat16', 'int64')",
                    input_data_ranges="((0,0,),(0,C-1,),)",
                )))

    def test_none_placeholder_slot_skipped(self, tmp_path):
        # 缺省可选输入的三列同位 None：range 槽位同样为 None → 不产 entry。
        op = OperatorSpec(name="op", inputs=[
            TensorSpec(name="x", param_type="REQUIRED"),
            TensorSpec(name="bias", param_type="OPTIONAL"),
        ], outputs=[])
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(
                stc_inputs="((1, 8), None)",
                stc_input_dtypes="('float16', None)",
                input_data_ranges="((-1,1,),None)",
            )),
            operator=op)
        assert len(c.inputs) == 1
        assert c.inputs[0]["value_range"] == [-1, 1]

    def test_ranges_length_mismatch_raises(self, tmp_path):
        with pytest.raises(ValueError, match="input_data_ranges"):
            parse_testcase_csv(
                _write_csv(tmp_path, _row(
                    stc_inputs="((1, 8), (1, 8),)",
                    stc_input_dtypes="('float16', 'float16')",
                    input_data_ranges="((-1,1,),)",
                )))

    def test_flat_path_mounts_ranges(self, tmp_path):
        # 无 op_spec（skill 单跑）的 legacy 1:1 路径同样挂载。
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(
                stc_inputs="((1, 8), (1, 3, 8),)",
                stc_input_dtypes="('float16', 'int64')",
                input_data_ranges="((-1,1,),(0,7,),)",
            )))
        assert [i.get("value_range") for i in c.inputs] == [[-1, 1], [0, 7]]

    def test_dynamic_param_single_range_covers_members(self, tmp_path):
        # TensorList/DYNAMIC：值域按逻辑参数对齐（生成器逐 param 产出），
        # 一个值域管全部成员（与 dtype/format 的"取首成员"同构）。
        op = OperatorSpec(name="op", inputs=[
            TensorSpec(name="x", param_type="REQUIRED"),
            TensorSpec(name="l", param_type="DYNAMIC"),
        ], outputs=[])
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(
                stc_inputs="((1, 8), (2, 8), (3, 8),)",
                stc_input_dtypes="('float16', 'float16', 'float16')",
                input_data_ranges="((-1,1,),(0,10,),)",
            )), operator=op)
        assert len(c.inputs) == 2
        assert c.inputs[0]["value_range"] == [-1, 1]
        assert c.inputs[1]["value_range"] == [0, 10]
        assert c.inputs[1]["shape"] == [[2, 8], [3, 8]]

    def test_empty_ranges_no_mount_params_none(self, tmp_path):
        (c,) = parse_testcase_csv(_write_csv(tmp_path, _ROW_OP))
        assert c.generator_params is None
        assert all("value_range" not in i for i in c.inputs)

    def test_generator_params_no_longer_carries_ranges(self, tmp_path):
        # generator_params.ranges 是零消费者死字段（§2.5 唯一通路）：
        # per-input value_range 是值域的唯一表达，不再双写。
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(
                stc_inputs="((1, 8),)",
                stc_input_dtypes="('float16',)",
                input_data_ranges="((-1,1,),)",
            )))
        assert c.generator_params is None


class TestNameFallback:
    def test_empty_name_falls_back(self, tmp_path):
        (c,) = parse_testcase_csv(_write_csv(tmp_path, _row(testcase_name="")))
        # fallback = op_name + 1-based row index
        assert c.name == "manifold_constrained_hyper_connection_post_1"


class TestErrors:
    def test_missing_required_column_raises(self, tmp_path):
        p = tmp_path / "bad.csv"
        p.write_text('"testcase_name","op_name"\n"n","op"\n', encoding="utf-8-sig")
        with pytest.raises(ValueError):
            parse_testcase_csv(p)

    def test_literal_eval_failure_raises(self, tmp_path):
        with pytest.raises(ValueError):
            parse_testcase_csv(
                _write_csv(tmp_path, _row(stc_inputs="not-a-tuple")))

    def test_empty_csv_returns_empty_list(self, tmp_path):
        p = _write_csv(tmp_path)  # header only
        assert parse_testcase_csv(p) == []

    def test_short_dtypes_raises_contract_error(self, tmp_path):
        """devkit 契约（testcase_csv.json）要求 stc_input_dtypes 逐输入声明（并行
        数组）。声明不足 = producer 违约（输入错误），加载期报错（§1.3），而非静默
        截断（旧 n=min）或静默降级 fp16（run 20260805-100200-c00f72 同源形态）。"""
        r = _row(
            stc_input_dtypes="('float32',)",   # 3 输入只声明 1 个
            stc_inputs="((1, 8, 24576), (1, 8, 24576), (1, 8, 24576))",
            stc_input_formats="('ND', 'ND', 'ND')",
        )
        with pytest.raises(ValueError, match="stc_input_dtypes"):
            parse_testcase_csv(_write_csv(tmp_path, r))

    def test_dtypes_empty_no_error(self, tmp_path):
        """多输入 + 空 dtype 列：不报错（既有行为——inputs 无 dtype key，由 runner
        默认 fp16 / 改动 B 存量继承兜底）。"""
        r = _row(
            stc_input_dtypes="",
            stc_inputs="((1, 8, 24576), (1, 8, 24576))",
            stc_input_formats="",
        )
        (c,) = parse_testcase_csv(_write_csv(tmp_path, r))
        assert len(c.inputs) == 2
        assert "dtype" not in c.inputs[1]


class TestOptionalSlotMisalign:
    """step-127 — 可选参数缺省的位置语义（CSV 三列同位 None 占位 + proto_idx）。

    历史缺陷：可选参数缺省时 CSV 少一项 → cursor 顺序补位 → 后续张量形状
    绑到前一个（可选）参数上。fixture 一律结构信号构造（中间/尾部缺省位置），
    不引入算子名分支（§1.12）。
    """

    @staticmethod
    def _op(mid_optional=True, dynamic=False):
        params = [TensorSpec(name="a", dtype="float16"),
                  TensorSpec(name="opt", dtype="float16",
                             param_type="OPTIONAL" if mid_optional else "REQUIRED"),
                  TensorSpec(name="c", dtype="float16")]
        if dynamic:
            params.insert(2, TensorSpec(name="var", dtype="float16",
                                        param_type="DYNAMIC"))
        return OperatorSpec(name="slot_op", inputs=params,
                            outputs=[TensorSpec(name="y", dtype="float16")])

    @staticmethod
    def _absent_row():
        # 生成端修复后的 CSV 形态：三列同位 None 占位
        return _row(
            stc_inputs="((1, 8), None, (3, 4))",
            stc_input_dtypes="('float16', None, 'float16')",
            stc_input_formats="('ND', None, 'ND')",
        )

    # 场景 1：中间可选参数缺省——后续张量不误绑、显式位置正确
    def test_middle_optional_absent_no_misbind(self, tmp_path):
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, self._absent_row()), operator=self._op())
        assert [i["name"] for i in c.inputs] == ["a", "c"]
        assert c.inputs[0]["shape"] == [1, 8]
        assert c.inputs[1]["shape"] == [3, 4]          # 不绑到 opt
        assert [i["proto_idx"] for i in c.inputs] == [0, 2]

    # 场景 2：尾部可选参数缺省
    def test_tail_optional_absent(self, tmp_path):
        r = _row(
            stc_inputs="((1, 8), (3, 4), None)",
            stc_input_dtypes="('float16', 'float16', None)",
            stc_input_formats="('ND', 'ND', None)",
        )
        op = OperatorSpec(name="slot_op",
                          inputs=[TensorSpec(name="a", dtype="float16"),
                                  TensorSpec(name="b", dtype="float16"),
                                  TensorSpec(name="opt", dtype="float16",
                                             param_type="OPTIONAL")],
                          outputs=[TensorSpec(name="y", dtype="float16")])
        (c,) = parse_testcase_csv(_write_csv(tmp_path, r), operator=op)
        assert [i["name"] for i in c.inputs] == ["a", "b"]
        assert [i["proto_idx"] for i in c.inputs] == [0, 1]

    # 场景 3：全部参数齐全——无回归（新契约：entry 带 proto_idx）
    def test_all_present_no_regression(self, tmp_path):
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(
                stc_inputs="((1, 8), (2, 2), (3, 4))",
                stc_input_dtypes="('float16', 'float16', 'float16')",
                stc_input_formats="('ND', 'ND', 'ND')",
            )), operator=self._op())
        assert [i["name"] for i in c.inputs] == ["a", "opt", "c"]
        assert [i["proto_idx"] for i in c.inputs] == [0, 1, 2]

    # 场景 4：空张量 [] 与未提供 None 语义区分（§1.10）
    def test_empty_tensor_is_present(self, tmp_path):
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(
                stc_inputs="((), None, (3, 4))",
                stc_input_dtypes="('float16', None, 'float16')",
                stc_input_formats="('ND', None, 'ND')",
            )), operator=self._op())
        assert [i["name"] for i in c.inputs] == ["a", "c"]
        assert c.inputs[0]["shape"] == []              # 空张量：真实 entry
        assert [i["proto_idx"] for i in c.inputs] == [0, 2]

    # 场景 5：None 字面量可解析、null 不行（ast.literal_eval 契约）
    def test_none_literal_parses_null_rejected(self, tmp_path):
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, self._absent_row()), operator=self._op())
        assert len(c.inputs) == 2
        with pytest.raises(ValueError):
            parse_testcase_csv(_write_csv(tmp_path, _row(
                stc_inputs="((1, 8), null, (3, 4))")), operator=self._op())

    # 场景 6：_as_shape_list 含 None 不被误判为单个 shape
    def test_shape_list_none_grouping(self):
        from ascendc_devkit.adapters.testdesign.csv_to_testcases import (
            _as_shape_list,
        )
        out = _as_shape_list([(1, 8), None, (3, 4)])
        assert out == [[1, 8], None, [3, 4]]

    # 场景 8：legacy 平铺路径（无 op_spec）——None 位跳过 + proto_idx
    def test_flat_inputs_none_skip_with_proto_idx(self, tmp_path):
        (c,) = parse_testcase_csv(_write_csv(tmp_path, _row(
            stc_inputs="((1, 8), None, (3, 4))",
            stc_input_dtypes="('float16', None, 'float16')",
            stc_input_formats="('ND', None, 'ND')",
        )))
        assert [i["name"] for i in c.inputs] == ["input_0", "input_2"]
        assert [i["proto_idx"] for i in c.inputs] == [0, 2]

    # 场景 10：三列同位占位 → 加载期平行契约校验通过
    def test_parallel_columns_with_placeholders_pass_contract(self, tmp_path):
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, self._absent_row()), operator=self._op())
        assert len(c.inputs) == 2                       # 契约校验未拒收

    def test_parallel_columns_misaligned_rejected(self, tmp_path):
        # shapes 占位而 dtypes 未占位 → 平行性破坏 → 加载期报错（§1.3）
        with pytest.raises(ValueError, match="stc_input_dtypes"):
            parse_testcase_csv(_write_csv(tmp_path, _row(
                stc_inputs="((1, 8), None, (3, 4))",
                stc_input_dtypes="('float16', 'float16')",
            )), operator=self._op())

    # 场景 11：DYNAMIC（Tensor[]）× 可选缺省并存 → 显式报错（不猜测拆分）
    def test_dynamic_with_optional_absent_raises(self, tmp_path):
        op = self._op(dynamic=True)                     # a, opt(OPT), var(DYN), c
        r = _row(
            stc_inputs="((1, 8), None, (3, 4), (5,))",  # opt 缺省 + var 2 成员?
            stc_input_dtypes="('float16', None, 'float16', 'float16')",
            stc_input_formats="('ND', None, 'ND', 'ND')",
        )
        with pytest.raises(ValueError, match="DYNAMIC"):
            parse_testcase_csv(_write_csv(tmp_path, r), operator=op)

    def test_dynamic_all_present_still_works(self, tmp_path):
        """DYNAMIC 用例参数齐全 → 不受影响（surplus 吸收不变）。"""
        op = self._op(dynamic=True)                     # a, opt, var(DYN), c
        r = _row(
            stc_inputs="((1, 8), (2, 2), (3, 4), (5,), (6,))",
            stc_input_dtypes="('float16', 'float16', 'float16', 'float16', 'float16')",
            stc_input_formats="('ND', 'ND', 'ND', 'ND', 'ND')",
        )
        (c,) = parse_testcase_csv(_write_csv(tmp_path, r), operator=op)
        by_name = {i["name"]: i for i in c.inputs}
        assert by_name["var"]["shape"] == [[3, 4], [5,]]   # surplus 吸收不变


class TestProtoIdxThroughHarness:
    """step-127 改动 5 —— runner 只读显式 proto_idx（删猜名字），
    harness test_cases 的 proto_idx 与 CSV 位置一致。"""

    @staticmethod
    def _harness_cases(tmp_path, row, operator):
        from types import SimpleNamespace
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.precision import CompareRule
        cases = parse_testcase_csv(_write_csv(tmp_path, row), operator=operator)
        r = NPURunner.__new__(NPURunner)
        r._chip_version = "A2"
        r._torch_npu_available = True
        src = r._build_test_harness(
            operator, cases,
            golden_contract={"path": "/tmp/g.py", "entry": "reference",
                             "input_type": "numpy"},
            deploy_result=SimpleNamespace(python_path="", install_path="/i",
                                          ld_library_path_add=""),
            callable_target={"kind": "torch_op",
                             "symbol": "torch.ops.cann_bench.slot_op"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
        )
        import ast as _ast
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Assign):
                for t in node.targets:
                    if isinstance(t, _ast.Name) and t.id == "test_cases":
                        return _ast.literal_eval(node.value)
        raise AssertionError("test_cases 未找到")

    def test_real_names_carry_explicit_proto_idx(self, tmp_path):
        """真实参数名（非 input_N）+ 缺省 → harness 收到显式原始位置 0/2
        （旧猜名字逻辑会给紧凑位置 0/1）。"""
        op = OperatorSpec(name="slot_op",
                          inputs=[TensorSpec(name="a", dtype="float16"),
                                  TensorSpec(name="opt", dtype="float16",
                                             param_type="OPTIONAL"),
                                  TensorSpec(name="c", dtype="float16")],
                          outputs=[TensorSpec(name="y", dtype="float16")])
        row = _row(
            stc_inputs="((1, 8), None, (3, 4))",
            stc_input_dtypes="('float16', None, 'float16')",
            stc_input_formats="('ND', None, 'ND')",
        )
        (hc,) = self._harness_cases(tmp_path, row, op)
        idx = [i["proto_idx"] for i in hc["inputs"]]
        assert idx == [0, 2]

    def test_missing_proto_idx_degrades_to_compact(self, tmp_path):
        """entry 无 proto_idx（旧形态）→ 唯一退化：紧凑顺序（§1.4 不留猜名字）。"""
        from types import SimpleNamespace
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.precision import CompareRule
        op = OperatorSpec(name="slot_op",
                          inputs=[TensorSpec(name="a", dtype="float16"),
                                  TensorSpec(name="b", dtype="float16")],
                          outputs=[TensorSpec(name="y", dtype="float16")])
        case = TestCase(name="no_idx",
                        inputs=[{"name": "a", "shape": [4]},
                                {"name": "b", "shape": [5]}],
                        expected=None)
        r = NPURunner.__new__(NPURunner)
        r._chip_version = "A2"
        r._torch_npu_available = True
        src = r._build_test_harness(
            op, [case],
            golden_contract={"path": "/tmp/g.py", "entry": "reference",
                             "input_type": "numpy"},
            deploy_result=SimpleNamespace(python_path="", install_path="/i",
                                          ld_library_path_add=""),
            callable_target={"kind": "torch_op",
                             "symbol": "torch.ops.cann_bench.slot_op"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
        )
        import ast as _ast
        tree = _ast.parse(src)
        for node in _ast.walk(tree):
            if isinstance(node, _ast.Assign):
                for t in node.targets:
                    if isinstance(t, _ast.Name) and t.id == "test_cases":
                        (hc,) = _ast.literal_eval(node.value)
                        assert [i["proto_idx"] for i in hc["inputs"]] == [0, 1]
                        return
        raise AssertionError("test_cases 未找到")


class TestCsvToHarnessConsumption:
    """全链路守护：test-design CSV 产物必须能被下游 harness 消费（§2.3 文件接力）。

    CSV → parse_testcase_csv → TestCase → NPURunner._build_test_harness 渲染。
    逐段 UT 各自孤立（test_csv_to_testcases / test_runner_execute），本类补上
    「CSV 产出的 shape/dtype/attrs 直达 harness test_cases 字面量」这一链接，
    防两端各自正确、接缝处丢字段/错 dtype（如 _NP 表缺全名 dtype 键导致
    bf16/float32 用例数据被 fp16 量化——test_harness_dtype 只守短别名 'bf16'）。
    """

    @staticmethod
    def _harness_from_csv(tmp_path, row, operator=None):
        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.domain.precision import CompareRule
        from types import SimpleNamespace

        cases = parse_testcase_csv(_write_csv(tmp_path, row), operator=operator)
        assert cases, "CSV 必须解析出用例"
        r = NPURunner.__new__(NPURunner)
        r._chip_version = "A2"
        r._torch_npu_available = True
        return r, cases[0], r._build_test_harness(
            operator or OperatorSpec(name="add"),
            cases,
            golden_contract={"path": "/tmp/g.py", "entry": "reference",
                             "input_type": "numpy"},
            deploy_result=SimpleNamespace(python_path="", install_path="/i",
                                          ld_library_path_add=""),
            callable_target={"kind": "torch_op",
                             "symbol": "torch.ops.cann_bench.add"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
        )

    @staticmethod
    def _harness_test_cases(src: str) -> list:
        import ast
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "test_cases":
                        return ast.literal_eval(node.value)
        raise AssertionError("test_cases 赋值未在 harness 中找到")

    def test_csv_case_renders_into_harness(self, tmp_path):
        """CSV 的 shape/dtype/attrs/name 全部直达 harness test_cases 字面量——
        runner 校验（_validate_case_form）与序列化不丢字段。"""
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        op = OperatorSpec(name="add",
                          inputs=[TensorSpec(name="x1", dtype="bf16"),
                                  TensorSpec(name="x2", dtype="bf16")],
                          outputs=[TensorSpec(name="y", dtype="bf16")])
        r, case, src = self._harness_from_csv(tmp_path, _row(
            testcase_name="add_c1",
            stc_input_dtypes="('bfloat16', 'bfloat16')",
            stc_inputs="((1, 8, 24576), (1, 8, 24576))",
            stc_input_formats="('ND', 'ND')",
            other_compilation_params='{"scalar": 3.0, "axis": -1}',
            absolute_precision="0.001",
        ), operator=op)
        assert case.attrs == {"scalar": 3.0, "axis": -1}
        (harness_case,) = self._harness_test_cases(src)
        shapes = [i["shape"] for i in harness_case["inputs"]]
        assert shapes == [[1, 8, 24576], [1, 8, 24576]], shapes
        dtypes = [i["dtype"] for i in harness_case["inputs"]]
        assert dtypes == ["bfloat16", "bfloat16"], dtypes
        assert harness_case["attrs"] == {"scalar": 3.0, "axis": -1}
        assert harness_case["name"] == "add_c1"

    def test_csv_full_name_dtype_maps_in_fallback_generation(self, tmp_path):
        """FALLBACK 路径 gen_input 对 CSV 全名 dtype（float32/bfloat16）必须用
        正确 numpy 载体（np.float32），不得落 np.float16 兜底（量化/溢出）。
        CSV 契约写全名，_NP 表缺全名键即此测试失败。"""
        import ast
        r, case, src = self._harness_from_csv(tmp_path, _row(
            stc_input_dtypes="('float32', 'bfloat16')",
            stc_inputs="((8,), (8,))",
            stc_input_formats="('ND', 'ND')",
        ))
        assert [i["dtype"] for i in case.inputs] == ["float32", "bfloat16"]
        tree = ast.parse(src)
        import numpy as np
        ns = {"np": np, "torch": __import__("torch"),
              "GEN": "random", "GEN_LOW": -1.0, "GEN_HIGH": 1.0}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name in (
                    "gen_input", "_flatten_shape"):
                exec(compile(ast.Module(body=[node], type_ignores=[]),
                             "<h>", "exec"), ns)
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in ("_NP", "_NP2TORCH"):
                        exec(compile(ast.Module(body=[node], type_ignores=[]),
                                     "<h>", "exec"), ns)
        assert ns["gen_input"]([8], "float32").dtype == np.float32, (
            "float32 用例数据被 np.float16 兜底量化——_NP 表缺 'float32' 全名键")
        assert ns["gen_input"]([8], "bfloat16").dtype == np.float32, (
            "bfloat16 用例数据非 float32 载体——_NP 表缺 'bfloat16' 全名键")

    def test_csv_harness_is_valid_python(self, tmp_path):
        """渲染出的 harness 是合法 Python（py_compile）——CSV 全名 dtype/attrs
        不会注入非法字面量。"""
        import py_compile
        import tempfile
        r, case, src = self._harness_from_csv(tmp_path, _row())
        with tempfile.NamedTemporaryFile(
                suffix=".py", mode="w", delete=False) as f:
            f.write(src)
            path = f.name
        py_compile.compile(path, doraise=True)

    def test_optional_placeholder_proto_idx_in_harness(self, tmp_path):
        """缺省可选输入的 proto 位置（proto_idx）必须直达 harness test_cases，
        使运行期 ``_restore_proto_order`` 能把输入放回原槽位。"""
        from ascendc_devkit.domain.operator import OperatorSpec, TensorSpec
        op = OperatorSpec(
            name="moe",
            inputs=[TensorSpec(name="a"),
                    TensorSpec(name="b", param_type="OPTIONAL"),
                    TensorSpec(name="c")],
            outputs=[TensorSpec(name="out")])
        r, case, src = self._harness_from_csv(tmp_path, _row(
            testcase_name="moe_c1",
            stc_input_dtypes="('float16',None,'float16')",
            stc_inputs="[(2,3,),None,(4,5,)]",
            stc_input_formats="('ND',None,'ND')",
        ), operator=op)
        (h,) = self._harness_test_cases(src)
        assert [i["proto_idx"] for i in h["inputs"]] == [0, 2]
        assert [i["shape"] for i in h["inputs"]] == [[2, 3], [4, 5]]


class TestIncidentRegression:
    """真实事故产物回归（2026-10-10 A3 批量精度全挂，109 条 devkit 用例）。

    事故行原样取自 output/…/artifacts/test_design/合并_测试用例.csv 的
    aclnnMseLossCrossEntropyLoss_L0_001：input_data_ranges 携带符号边界
    `(0,C-1,)`（C = logits 类别维，仅存在于需求 prose，无机器可执行定义）。
    历史实现原样装箱进 generator_params.ranges（零消费者），harness 回退
    [-1,1] 为 int64 targets 生成 -1 → cross_entropy IndexError。契约：
    转换端对符号边界诚实报错；对已实例化的数值边界逐输入挂载。
    """

    # 原样事故行（未做任何改写）。
    _INCIDENT_ROW = {
        "testcase_name": "aclnnMseLossCrossEntropyLoss_L0_001",
        "op_name": "mse_loss_cross_entropy_loss",
        "stc_input_dtypes": "('bfloat16','int64','bfloat16',)",
        "stc_inputs": "[(1,2,3,1,1,1,1,8,),(1,3,1,1,1,1,8,),(1,2,3,1,1,1,1,8,)]",
        "output_dtypes": "('bfloat16',)",
        "stc_outputs": "[()]",
        "stc_input_formats": "('ND','ND','ND',)",
        "output_formats": "('ND',)",
        "stc_op_name": "aclnnMseLossCrossEntropyLoss",
        "input_data_ranges": "((0,0,),(0,C-1,),(0,0,),)",
        "absolute_precision": "1e-05",
    }

    @staticmethod
    def _op():
        return OperatorSpec(name="mse_loss_cross_entropy_loss", inputs=[
            TensorSpec(name="logits", param_type="REQUIRED"),
            TensorSpec(name="targets", param_type="REQUIRED"),
            TensorSpec(name="predictions", param_type="REQUIRED"),
        ], outputs=[])

    def test_real_incident_row_hard_fails_not_silent_fallback(self, tmp_path):
        # 符号边界 C-1 在转换端指名列报错——绝不静默回退 [-1,1]。
        with pytest.raises(ValueError, match="input_data_ranges"):
            parse_testcase_csv(
                _write_csv(tmp_path, _row(**self._INCIDENT_ROW)))

    def test_instantiated_incident_row_mounts_per_input(self, tmp_path):
        # 同一行、符号按本行 shape 实例化后（logits.shape[1]=2 → targets
        # [0,1]）：数值边界逐输入挂载，generator_params 不再承载 ranges。
        row = dict(self._INCIDENT_ROW)
        row["input_data_ranges"] = "((0,0,),(0,1,),(0,0,),)"
        (c,) = parse_testcase_csv(
            _write_csv(tmp_path, _row(**row)), operator=self._op())
        assert [i.get("value_range") for i in c.inputs] == [
            [0, 0], [0, 1], [0, 0]]
        assert not (c.generator_params or {}).get("ranges")
