"""Unit tests for the external cases loader (A5, P10/D4/D5; B5 14 L4).

The loader bridges an external cann-bench cases.csv into the framework's
TestCase list. B5: load_cann_bench_cases takes a single cases_path (13 E1/E2 — the CLI
param name encodes the format; no CasesSource/format dispatch, no {op}/{N}).
"""

import json
from pathlib import Path
import math

import pytest

from ascendc_devkit.domain.cann_bench_cases_loader import (
    load_cann_bench_case_meta, load_cann_bench_cases, parse_cann_bench_csv,
)

from tests._testrepos import resolve_test_repo, repo_skip_reason


def _write_csv(path: Path, rows: list[list[str]]) -> Path:
    import csv as _csv
    header = ["operator", "case_id", "input_shape", "dtype", "attrs",
              "value_range", "note"]
    with Path(path).open("w", encoding="utf-8", newline="") as f:
        writer = _csv.writer(f)
        writer.writerow(header)
        writer.writerows(rows)
    return path


class TestCannBenchCsvParser:
    def test_exp_row_becomes_testcase_with_attrs(self, tmp_path):
        """An exp-like row (single input, attrs with scale=1.5) becomes a
        TestCase carrying shape/dtype/attrs — the non-default branch P10 cares
        about (A2 forwards attrs as kwargs)."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            [
                "Exp", "1",
                json.dumps([[1024, 1024]]),
                json.dumps(["float16"]),
                json.dumps({"base": -1.0, "scale": 1.5, "shift": 0.0}),
                json.dumps([-1, 1]),
                "S-float16-scale=1.5",
            ],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert len(cases) == 1
        tc = cases[0]
        assert tc.inputs[0]["shape"] == [1024, 1024]
        assert tc.inputs[0]["dtype"] == "fp16"  # cann-bench float16 → framework fp16
        assert tc.attrs == {"base": -1.0, "scale": 1.5, "shift": 0.0}
        # value_range [low,high] → random_uniform generator params
        assert tc.generator == "random_uniform"
        assert tc.generator_params == {"low": -1.0, "high": 1.0, "seed": 42}

    def test_dtype_aliases_mapped(self, tmp_path):
        """cann-bench dtype names (float16/float32/bfloat16) map to the
        framework vocabulary (fp16/fp32/bf16) the harness _NP dict understands."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1", json.dumps([[8]]), json.dumps(["float16"]),
             json.dumps({}), json.dumps([-1, 1]), ""],
            ["Op", "2", json.dumps([[8]]), json.dumps(["bfloat16"]),
             json.dumps({}), json.dumps([-1, 1]), ""],
            ["Op", "3", json.dumps([[8]]), json.dumps(["float32"]),
             json.dumps({}), json.dumps([-1, 1]), ""],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert [c.inputs[0]["dtype"] for c in cases] == ["fp16", "bf16", "fp32"]

    def test_multi_input_shapes_and_attrs(self, tmp_path):
        """Multi-input row (n-ary op): each input gets its own shape/dtype;
        attrs carry through; nested value_range → first non-null range."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Add", "1",
             json.dumps([[4, 8], [4, 8]]),
             json.dumps(["float16", "float16"]),
             json.dumps({}),
             json.dumps([[-1, 1], [-2, 2]]),
             "binary"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        tc = cases[0]
        assert [i["shape"] for i in tc.inputs] == [[4, 8], [4, 8]]
        assert [i["dtype"] for i in tc.inputs] == ["fp16", "fp16"]
        assert tc.generator_params == {"low": -1.0, "high": 1.0, "seed": 42}

    def test_attrs_default_empty_when_missing(self, tmp_path):
        """A row whose attrs column is empty/{} → TestCase.attrs == {} (attr-less
        op, A2 degrades to positional)."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1", json.dumps([[8]]), json.dumps(["float16"]), "{}",
             json.dumps([-1, 1]), ""],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert cases[0].attrs == {}

    def test_value_range_null_skips_generator_params(self, tmp_path):
        """A null value_range (e.g. int index inputs) → no generator params;
        the harness falls back to its default random_uniform [-1,1]."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1", json.dumps([[8]]), json.dumps(["int32"]),
             json.dumps({}), "null", ""],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert cases[0].generator is None
        assert cases[0].generator_params is None

    def test_null_optional_input_dropped(self, tmp_path):
        """Optional input absent (cann-bench null shape entry) → that input is
        dropped from the TestCase; the harness relies on the param's default at
        the call site. moe_re_routing case 4: per_token_scales=null → 2 inputs
        (tokens, expert_token_num_per_rank), scales defaults None in the kernel."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["MoeReRouting", "4",
             json.dumps([[4096, 512], [8, 8], None]),
             json.dumps(["float16", "int32", "float32"]),
             json.dumps({"expert_token_num_type": 1, "idx_type": 0}),
             json.dumps([[-1, 1], [1, 128], None]),
             "no-scales"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert len(cases[0].inputs) == 2  # null 3rd input dropped
        assert [i["dtype"] for i in cases[0].inputs] == ["fp16", "int32"]

    def test_per_input_value_range_attached(self, tmp_path):
        """Nested value_range → each input carries its own [low, high] (Fix E).
        Multi-input ops need per-input ranges (e.g. moe_re_routing's
        expert_token_num_per_rank needs [1,128] while tokens needs [-1,1]); the
        old single-range collapse broke the sum==A invariant for such inputs."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["MoeReRouting", "1",
             json.dumps([[1024, 512], [8, 8], [1024]]),
             json.dumps(["float16", "int32", "float32"]),
             json.dumps({}),
             json.dumps([[-1, 1], [1, 128], [-1, 1]]),
             "scales"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        vr = [i.get("value_range") for i in cases[0].inputs]
        assert vr == [[-1.0, 1.0], [1.0, 128.0], [-1.0, 1.0]]

    def test_string_inf_nan_value_range_coerced(self, tmp_path):
        """JSON 不支持 Infinity/NaN 字面量，cann-bench CSV 用字符串 "-inf"/"inf"/"nan"
        表示特殊 range。loader 必须识别并 float() 转换，让 inf/nan value_range 正确
        进入 TestCase（per-input + generator_params），而不是被 isinstance(int,float)
        门槛丢弃 → harness fallback 到默认 [-1,1] → inf/nan 测试假通过。"""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["RmsNorm", "15",
             json.dumps([[1000003, 2], [2]]),
             json.dumps(["bfloat16", "bfloat16"]),
             json.dumps({"epsilon": 1e-6}),
             json.dumps(["-inf", "inf"]),
             "inf-special"],
            ["RmsNorm", "16",
             json.dumps([[11, 13, 17, 67], [67]]),
             json.dumps(["float16", "float16"]),
             json.dumps({"epsilon": 1e-8}),
             json.dumps(["nan", "nan"]),
             "nan-special"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert len(cases) == 2

        # case 15: [-inf, inf] per-input + generator_params
        tc15 = cases[0]
        vr15 = tc15.inputs[0].get("value_range")
        assert vr15 is not None, "inf value_range 不应被丢弃"
        assert math.isinf(vr15[0]) and vr15[0] < 0
        assert math.isinf(vr15[1]) and vr15[1] > 0
        assert tc15.generator == "random_uniform"
        gp15 = tc15.generator_params
        assert gp15 is not None
        assert math.isinf(gp15["low"]) and gp15["low"] < 0
        assert math.isinf(gp15["high"]) and gp15["high"] > 0

        # case 16: [nan, nan]
        tc16 = cases[1]
        vr16 = tc16.inputs[0].get("value_range")
        assert vr16 is not None, "nan value_range 不应被丢弃"
        assert math.isnan(vr16[0])
        assert math.isnan(vr16[1])
        assert tc16.generator == "random_uniform"
        assert math.isnan(tc16.generator_params["low"])
        assert math.isnan(tc16.generator_params["high"])

    def test_single_quote_fallback(self, tmp_path):
        """CSV cells 用 Python 单引号（非标准 JSON）时，ast.literal_eval fallback 应
        正确解析。roi_pooling case 13 的 value_range: ['-inf', 'inf'] 和 dtype: ['float32',
        'float32'] 是真实遇到的场景。"""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["RoiPooling", "13",
             "[[4,4,4,4], [4,4]]",  # shape: valid JSON
             "['float32', 'float32']",  # dtype: Python single-quote — NOT valid JSON
             json.dumps({}),
             "['-inf', 'inf']",  # value_range: Python single-quote — NOT valid JSON
             "inf-special"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert len(cases) == 1
        tc = cases[0]
        # dtype 应通过 ast.literal_eval 正确解析并映射
        assert [i["dtype"] for i in tc.inputs] == ["fp32", "fp32"]
        # value_range 应通过 ast.literal_eval 正确解析 → _coerce_float → inf
        vr = tc.inputs[0].get("value_range")
        assert vr is not None, "inf value_range 不应被丢弃（ast 兜底失败？）"
        assert math.isinf(vr[0]) and vr[0] < 0  # -inf
        assert math.isinf(vr[1]) and vr[1] > 0  # inf
        assert tc.generator_params is not None
        assert math.isinf(tc.generator_params["low"]) and tc.generator_params["low"] < 0
        assert math.isinf(tc.generator_params["high"]) and tc.generator_params["high"] > 0

    def test_single_quote_nested_fallback(self, tmp_path):
        """Nested single-quote value_range: [['-inf', 'inf'], [-1, 1]] — same pattern
        from roi_pooling case 13 (multi-input)."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1",
             json.dumps([[8], [8]]),
             "['float32', 'float32']",
             json.dumps({}),
             "[['-inf', 'inf'], [-1, 1]]",
             "multi-inf"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert len(cases) == 1
        tc = cases[0]
        # per-input ranges: input 0 = [-inf, inf], input 1 = [-1, 1]
        vr0 = tc.inputs[0].get("value_range")
        vr1 = tc.inputs[1].get("value_range")
        assert vr0 is not None
        assert math.isinf(vr0[0]) and vr0[0] < 0
        assert math.isinf(vr0[1]) and vr0[1] > 0
        assert vr1 == [-1.0, 1.0]
        # generator_params picks first non-null range: [-inf, inf]
        assert tc.generator_params is not None
        assert math.isinf(tc.generator_params["low"])

    def test_ast_fallback_rejects_potentially_unsafe(self, tmp_path):
        """ast.literal_eval 只接受字面量（str/num/list/dict/tuple/None/bool），拒绝对
        函数调用、变量名等潜在不安全表达式求值——这就是不用 eval() 的原因。"""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1",
             json.dumps([[8]]),
             "__import__('os').system('echo bad')",
             json.dumps({}),
             json.dumps([-1, 1]),
             "unsafe"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert len(cases) == 1
        # dtype 解析失败 → raw string 经 _map_dtype 变小写 → 最终不会是 "fp16" 等已知
        # 但不会执行任意代码
        assert cases[0].inputs[0]["dtype"] != "__import__"  # 不会原始字符串原封不动

    def test_multiple_rows_preserve_order(self, tmp_path):
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Exp", "1", json.dumps([[1024, 1024]]), json.dumps(["float16"]),
             json.dumps({"scale": 1.0}), json.dumps([-1, 1]), ""],
            ["Exp", "2", json.dumps([[2048, 2048]]), json.dumps(["float32"]),
             json.dumps({"scale": 1.5}), json.dumps([-2, 2]), ""],
            ["Exp", "3", json.dumps([[4096, 4096]]), json.dumps(["bfloat16"]),
             json.dumps({"scale": 2.0}), json.dumps([-3, 3]), ""],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert [c.attrs["scale"] for c in cases] == [1.0, 1.5, 2.0]
        assert [c.inputs[0]["shape"] for c in cases] == [
            [1024, 1024], [2048, 2048], [4096, 4096]]

    # ---- dtype 广播（foreach 类多输入同 dtype 算子；run 20260805-100200-c00f72
    #      20/20 empty-dtype ValueError 根因回归，见 docs/plan/case-dtype-broadcast/）----

    def test_single_dtype_broadcast_to_multi_input(self, tmp_path):
        """cann-bench 单元素 dtype = 全体 tensor 输入共享（广播约定，cann_loader
        _parse_case 同款）。foreach_addcdiv_scalar 3 输入 dtype=["float32"] → 3 输入
        全 fp32，而非 ["fp32","",""] 空串穿透（本批 20/20 ValueError 根因）。"""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["ForeachAddcdivScalar", "1",
             json.dumps([[1024, 1024], [1024, 1024], [1024, 1024]]),
             json.dumps(["float32"]),
             json.dumps({"scalar": 1.0}),
             json.dumps([[-1, 1], [-1, 1], [0.5, 1]]),
             "M-float32"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        tc = cases[0]
        assert len(tc.inputs) == 3
        assert [i["dtype"] for i in tc.inputs] == ["fp32", "fp32", "fp32"]

    def test_single_dtype_with_null_input_dropped(self, tmp_path):
        """广播只计非 None shape（optional 输入被 drop，不参与广播）。
        3 shape 含 1 None + 单 dtype → 2 输入共享该 dtype。"""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1",
             json.dumps([[4096, 512], [8, 8], None]),
             json.dumps(["float16"]),
             json.dumps({}),
             json.dumps([[-1, 1], [1, 128], None]),
             "no-scales"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert len(cases[0].inputs) == 2
        assert [i["dtype"] for i in cases[0].inputs] == ["fp16", "fp16"]

    def test_scalar_dtype_string_wrapped(self, tmp_path):
        """dtype 列为带引号裸串（JSON 字符串，非数组）→ 归一为单元素列表，防
        「裸串按字符索引」产生 'f'/'l' 垃圾 dtype（'float32'[0]=='f'）。"""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1",
             json.dumps([[8]]),
             json.dumps("float32"),     # '"float32"' 带引号 → json.loads → 'float32' 字符串
             json.dumps({}),
             json.dumps([-1, 1]),
             "scalar-dtype"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert cases[0].inputs[0]["dtype"] == "fp32"

    def test_per_input_dtypes_unchanged(self, tmp_path):
        """多输入多 dtype 用例（并行数组）不受广播影响——广播仅在 len==1 触发。
        moe_re_routing 类混合 dtype（int 索引 + fp16 数据）保持逐输入原样。"""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["MoeReRouting", "1",
             json.dumps([[1024, 512], [8, 8]]),
             json.dumps(["float16", "int32"]),
             json.dumps({}),
             json.dumps([[-1, 1], [1, 128]]),
             "scales"],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert [i["dtype"] for i in cases[0].inputs] == ["fp16", "int32"]

    def test_partial_dtypes_warns_no_broadcast(self, tmp_path, caplog):
        """1 < len(dtypes) < 非空输入数（结构性不齐，非单 dtype 广播约定）：不广播
        （无合法依据），打 WARN（§1.3 可观测），缺 dtype 的输入留空由 runner 存量
        兜底继承（改动 B）。"""
        import logging
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1",
             json.dumps([[8], [8], [8]]),
             json.dumps(["float16", "int32"]),
             json.dumps({}),
             json.dumps([[-1, 1], [1, 128], [0, 1]]),
             "partial-dtypes"],
        ])
        with caplog.at_level(
                logging.WARNING,
                logger="ascendc_devkit.domain.cann_bench_cases_loader"):
            cases = parse_cann_bench_csv(csv_path)
        # 不广播：input_0/1 有真实 dtype，input_2 留空（由 runner 继承）
        assert [i["dtype"] for i in cases[0].inputs] == ["fp16", "int32", ""]
        assert any("dtype len=2" in r.message for r in caplog.records), (
            "结构性不齐应打 WARN（§1.3），不应静默"
        )

    def test_tensorlist_nested_dtype_takes_first_element(self, tmp_path):
        """TensorList 输入在 cann-bench CSV 里 dtype 是嵌套 ``["float32"]``
        （lstm/gru 权重列表逐 tensor 一个 dtype 数组）→ 取首元素映射（与
        DataGenerator 的 ``d[0]`` 约定一致），不再对 list 调 ``.strip()`` 崩
        AttributeError（本批 lstm/gru 加载失败根因）。"""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["LSTM", "1",
             json.dumps([[10, 4, 64], [[128, 64]], [[128, 32]], [[128]], [[128]]]),
             json.dumps(["float32", ["float32"], ["float32"], ["float32"], ["float32"]]),
             json.dumps({}), json.dumps([[-1, 1], [[-0.1, 0.1]]]), ""],
        ])
        cases = parse_cann_bench_csv(csv_path)
        assert [i["dtype"] for i in cases[0].inputs] == ["fp32"] * 5

    def test_extra_dtypes_warns_no_silent_truncate(self, tmp_path, caplog):
        """多填 dtype（len > 非空输入数）同样结构不齐：不静默截断，打 WARN（n4）。
        原实现只对 1<len<输入数 WARN，多填被 raw_dtype 静默取前 N 个丢弃。"""
        import logging
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1",
             json.dumps([[8], [8]]),
             json.dumps(["float16", "int32", "float32"]),   # 3 dtype, 2 输入
             json.dumps({}),
             json.dumps([[-1, 1], [1, 128]]),
             "extra-dtypes"],
        ])
        with caplog.at_level(
                logging.WARNING,
                logger="ascendc_devkit.domain.cann_bench_cases_loader"):
            cases = parse_cann_bench_csv(csv_path)
        # 前 N 个 dtype 生效，多余丢弃，但必须 WARN 暴露（§1.3 不静默）
        assert [i["dtype"] for i in cases[0].inputs] == ["fp16", "int32"]
        assert any("dtype len=3" in r.message for r in caplog.records), (
            "多填 dtype 应打 WARN（§1.3），不应静默截断"
        )


class TestLoadCannBenchCasesPath:
    """B5 (14 L4): load_cann_bench_cases takes a single cases_path (13 E1/E2 — the CLI
    param name encodes the format, so the loader no longer dispatches by
    format nor substitutes {op}/{N})."""

    def test_load_cann_bench_cases_takes_path_only(self, tmp_path):
        """load_cann_bench_cases(cases_path) parses the CSV directly into TestCases."""
        csv_path = tmp_path / "cases.csv"
        _write_csv(csv_path, [
            ["Exp", "1", json.dumps([[8]]), json.dumps(["float16"]),
             json.dumps({"scale": 1.5}), json.dumps([-1, 1]), ""],
        ])
        cases = load_cann_bench_cases(csv_path)
        assert len(cases) == 1
        assert cases[0].attrs == {"scale": 1.5}

    def test_load_cann_bench_cases_signature_is_single_path(self):
        """The loader signature is just (cases_path) — no CasesSource/format/
        op_name/repo_root/level (13 E2: param name encodes the format)."""
        import inspect
        sig = inspect.signature(load_cann_bench_cases)
        assert list(sig.parameters) == ["cases_path"]

    def test_load_cann_bench_cases_accepts_str_or_path(self, tmp_path):
        """load_cann_bench_cases accepts both str and Path (callers may pass either)."""
        csv_path = tmp_path / "cases.csv"
        _write_csv(csv_path, [
            ["Exp", "1", json.dumps([[8]]), json.dumps(["float16"]),
             json.dumps({}), json.dumps([-1, 1]), ""],
        ])
        assert len(load_cann_bench_cases(str(csv_path))) == 1
        assert len(load_cann_bench_cases(Path(csv_path))) == 1


@pytest.mark.external_repo("cann-bench")
class TestRealCannBenchExpCases:
    """A8 integration: parse cann-bench's REAL exp cases.csv to confirm the
    loader handles the actual format (multi-row, attrs across non-default
    branches, value_range). The cann-bench repo is an external read-only dep;
    skip (not fail) when absent — this guards the real format only when present.
    """

    CANN_BENCH = resolve_test_repo("ASCENDC_TEST_CANN_BENCH", "cann-bench")

    def test_parses_real_exp_cases_with_attrs(self):
        if self.CANN_BENCH is None:
            pytest.skip(repo_skip_reason("cann-bench", "ASCENDC_TEST_CANN_BENCH"))
        csv_path = self.CANN_BENCH / "tasks" / "level1" / "exp" / "cases.csv"
        if not csv_path.is_file():
            pytest.skip(f"cann-bench exp cases.csv not present at {csv_path}")
        cases = parse_cann_bench_csv(csv_path)
        assert len(cases) >= 3
        # Every case carries the exp attrs (base/scale/shift) — the non-default
        # branches (scale=1.5/2.0) that align ① verify with ② cann-bench.
        for tc in cases:
            assert {"base", "scale", "shift"} <= set(tc.attrs.keys())
            assert tc.inputs and tc.inputs[0]["shape"]
            assert tc.inputs[0]["dtype"] in {"fp16", "fp32", "bf16"}
        # At least one non-default scale branch is present (P8/P10 coverage).
        scales = {tc.attrs["scale"] for tc in cases}
        assert scales != {1.0}, "expected non-default scale branches in exp cases"


@pytest.mark.external_repo("cann-bench")
class TestRealCannBenchForeachCases:
    """A8 integration: parse cann-bench's REAL foreach_addcdiv_scalar cases.csv to
    confirm the single-dtype broadcast convention is honored — the exact run that
    halted with 20/20 empty-dtype ValueError (run 20260805-100200-c00f72). Skip
    when the cann-bench repo is absent (external read-only dep).
    """

    CANN_BENCH = resolve_test_repo("ASCENDC_TEST_CANN_BENCH", "cann-bench")

    def test_real_foreach_cases_no_empty_dtype(self):
        if self.CANN_BENCH is None:
            pytest.skip(repo_skip_reason("cann-bench", "ASCENDC_TEST_CANN_BENCH"))
        csv_path = self.CANN_BENCH / "tasks" / "level1" / "foreach_addcdiv_scalar" / "cases.csv"
        if not csv_path.is_file():
            pytest.skip(f"cann-bench foreach_addcdiv_scalar cases.csv not present at {csv_path}")
        cases = parse_cann_bench_csv(csv_path)
        assert len(cases) >= 20
        for tc in cases:
            for i in tc.inputs:
                assert i.get("dtype"), (
                    f"case {tc.name} input 缺 dtype（应为广播展开后的真实值）：{i}"
                )

    def test_real_foreach_loader_to_harness_no_empty_dtype(self):
        """真实 foreach cases.csv → loader 广播（改动 A）→ runner 烘焙 harness（改动 B）
        的端到端产物链路：20 case 全链路无空 dtype。非 LLM/NPU，是本次修复的
        loader+runner 完整回归门（run 20260805-100200-c00f72 的 20/20 halt 复现场景）。
        """
        if self.CANN_BENCH is None:
            pytest.skip(repo_skip_reason("cann-bench", "ASCENDC_TEST_CANN_BENCH"))
        csv_path = self.CANN_BENCH / "tasks" / "level1" / "foreach_addcdiv_scalar" / "cases.csv"
        if not csv_path.is_file():
            pytest.skip(f"cann-bench foreach_addcdiv_scalar cases.csv not present at {csv_path}")
        from types import SimpleNamespace
        import ast

        from ascendc_devkit.adapters.npu.runner import NPURunner
        from ascendc_devkit.adapters.npu.precision_comparer import DevkitComparer
        from ascendc_devkit.domain.operator import OperatorSpec
        from ascendc_devkit.domain.precision import CompareRule

        cases = parse_cann_bench_csv(csv_path)
        # 真实链路 op_spec 来自 requirement：3 个 DYNAMIC（TensorList）输入。
        op = OperatorSpec.from_dict({
            "name": "foreach_addcdiv_scalar",
            "inputs": [
                {"name": "x1", "param_type": "DYNAMIC", "dtype": ["fp32"]},
                {"name": "x2", "param_type": "DYNAMIC", "dtype": ["fp32"]},
                {"name": "x3", "param_type": "DYNAMIC", "dtype": ["fp32"]},
            ],
            "outputs": [{"name": "y", "param_type": "REQUIRED", "dtype": ["fp32"]}],
        })
        r = NPURunner.__new__(NPURunner)
        r._chip_version = "A2"
        r._torch_npu_available = True
        src = r._build_test_harness(
            op, cases,
            golden_contract={"path": "/tmp/g.py", "entry": "reference",
                             "input_type": "numpy"},
            deploy_result=SimpleNamespace(python_path="/p", install_path="/i",
                                          ld_library_path_add=""),
            callable_target={"kind": "torch_op",
                             "symbol": "torch.ops.cann_bench.foreach_addcdiv_scalar"},
            rule=CompareRule(dtype_thresholds={"*": 1e-2}),
            comparer=DevkitComparer(),
        )
        tree = ast.parse(src)
        harness_cases = None
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "test_cases":
                        harness_cases = ast.literal_eval(node.value)
        assert harness_cases is not None and len(harness_cases) == len(cases)
        empty = [(c["name"], i) for c in harness_cases
                 for i in c["inputs"] if not i.get("dtype")]
        assert not empty, f"harness 仍有空 dtype 输入：{empty[:2]}"


class TestCannBenchCaseMeta:
    def test_primary_input_shape_dtype_extracted(self, tmp_path):
        """Per-case metadata takes the primary (first non-null) input's
        shape/dtype — the authoritative source for failed_case_queue enrichment
        (cross_compare carries only comparison results, not case metadata)."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            [
                "GroupNorm", "3",
                json.dumps([[2, 128, 256, 256], [128], [128]]),
                json.dumps(["bfloat16", "bfloat16", "bfloat16"]),
                json.dumps({"num_groups": 32}),
                json.dumps([-3, 3]),
                "M-bfloat16-16M",
            ],
        ])
        meta = load_cann_bench_case_meta(csv_path)
        assert meta["3"] == {"shape": [2, 128, 256, 256], "dtype": "bfloat16"}

    def test_keys_are_str_case_ids(self, tmp_path):
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1", json.dumps([[8, 8]]), json.dumps(["float16"]),
             json.dumps({}), json.dumps([-1, 1]), ""],
            ["Op", "2", json.dumps([[16]]), json.dumps(["float32"]),
             json.dumps({}), json.dumps([-1, 1]), ""],
        ])
        meta = load_cann_bench_case_meta(csv_path)
        assert set(meta) == {"1", "2"}
        assert meta["2"] == {"shape": [16], "dtype": "float32"}

    def test_null_primary_input_skips_to_next(self, tmp_path):
        """A null first input (optional tensor) must not produce an empty
        primary; the metadata falls through to the next non-null input.
        dtype broadcast (single column → all inputs) matches the parser."""
        csv_path = _write_csv(tmp_path / "cases.csv", [
            ["Op", "1", json.dumps([None, [64, 64], [32]]),
             json.dumps(["float16"]), json.dumps({}), json.dumps([-1, 1]), ""],
        ])
        meta = load_cann_bench_case_meta(csv_path)
        assert meta["1"] == {"shape": [64, 64], "dtype": "float16"}

    def test_missing_csv_returns_empty(self, tmp_path):
        assert load_cann_bench_case_meta(tmp_path / "nope.csv") == {}
