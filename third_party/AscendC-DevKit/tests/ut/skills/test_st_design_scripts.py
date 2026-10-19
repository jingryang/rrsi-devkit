"""UT for ascendc-st-design/scripts factor-value + case-selection behavior.

Deterministic no-LLM guards (§3.8) for the special-value & duplicate-padding
defects surfaced by the GridSampler3D run:

- P1: ``complete_value_range_coverage`` guarantees every declared
  ``{param}.value_range_{dtype}`` value (incl. inf/-inf/nan/extreme) appears in
  the factor-value pool, so L0 single-factor coverage can actually cover it.
- P2: ``pad_cases`` pads with **distinct** unselected rows instead of re-sampling
  already-selected indices (the 98/100 duplicate rows defect).
- P3: ``extract_all_factor_values`` uses the **declared** domain as the coverage
  target (∪ actual), so a declared-but-not-generated value shows as uncovered
  rather than a self-certifying 100%.
- P4: ``generate_all_cases`` no longer fake-pads to ``max_cases`` by duplicating
  identical anchor combinations.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

_SKILL_SCRIPTS = (
    Path(__file__).resolve().parents[3]
    / ".claude" / "skills" / "ascendc-st-design" / "scripts"
)


def _load(name: str):
    if str(_SKILL_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SKILL_SCRIPTS))
    path = _SKILL_SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_st_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


tc = _load("generate_test_cases")
fv = _load("generate_factor_values")


# ── P2: pad_cases must add distinct content ──────────────────────────────────


class TestPadCasesDistinct:
    def _df(self, ranges):
        return pd.DataFrame({
            "x.dtype": ["float16"] * len(ranges),
            "x.value_range": ranges,
        })

    def test_pad_skips_duplicate_content(self):
        # index 0/1 share content; 2/3 share; 4 unique → distinct pool = {0,2,4}
        df = self._df(["[0, 0]", "[0, 0]", "[-1, 1]", "[-1, 1]", "[inf, inf]"])
        padded = tc.pad_cases([0], target_count=10, seed=42, df=df)
        assert len(padded) == 3
        contents = [tc.case_content_key(df.loc[i]) for i in padded]
        assert len(set(contents)) == len(contents)

    def test_pad_stops_at_available_distinct(self):
        df = self._df([f"[{i}, {i}]" for i in range(10)])
        padded = tc.pad_cases([0], target_count=5, seed=1, df=df)
        assert len(padded) == 5
        assert len({tc.case_content_key(df.loc[i]) for i in padded}) == 5

    def test_pad_never_returns_more_than_target(self):
        df = self._df([f"[{i}, 0]" for i in range(10)])
        padded = tc.pad_cases([], target_count=4, seed=1, df=df)
        assert len(padded) == 4

    def test_pad_without_df_is_noop(self):
        assert tc.pad_cases([3, 7], target_count=10, seed=1, df=None) == [3, 7]


# ── P3: declared values drive the coverage target ────────────────────────────


class TestExtractAllFactorValuesDeclared:
    def test_declared_range_absent_from_csv_is_still_target(self):
        factors = {
            "x": {"factors": {
                "x.dtype": ["float16", "float32"],
                "x.value_range_float16": [["inf", "inf"], ["nan", "nan"]],
                "x.format": ["ND"],
            }},
        }
        df = pd.DataFrame({"x.dtype": ["float16"], "x.value_range": ["[0, 0]"]})
        target = tc.extract_all_factor_values(factors, df)
        # declared list values normalized to CSV string form
        assert target["x.value_range"] == {"['inf', 'inf']", "['nan', 'nan']", "[0, 0]"}
        assert target["x.dtype"] == {"float16", "float32"}

    def test_declared_factor_absent_from_df_is_dropped(self):
        # interpolation_mode.exist declared but never materialized (attrs not a
        # case dimension) — must not enter the target and create a fake gap.
        factors = {"interpolation_mode": {"factors": {
            "interpolation_mode.exist": [True, False],
            "interpolation_mode.value": ["bilinear", "nearest"],
        }}}
        df = pd.DataFrame({"interpolation_mode.value": ["bilinear"]})
        target = tc.extract_all_factor_values(factors, df)
        assert "interpolation_mode.exist" not in target
        assert target["interpolation_mode.value"] == {"bilinear", "nearest"}

    def test_bool_int_values_kept_as_is(self):
        factors = {"align_corners": {"factors": {
            "align_corners.value": [False, True],
            "align_corners.dtype": ["bool"],
        }}, "grid": {"factors": {"grid.dimensions": [5]}}}
        df = pd.DataFrame({
            "align_corners.value": [True],
            "align_corners.dtype": ["bool"],
            "grid.dimensions": [5],
        })
        target = tc.extract_all_factor_values(factors, df)
        assert target["align_corners.value"] == {False, True}
        assert target["grid.dimensions"] == {5}


# ── P1: value_range coverage completion ──────────────────────────────────────


class TestCompleteValueRangeCoverage:
    def _gen(self, test_factors):
        g = fv.FactorValueGenerator()
        g.test_factors = test_factors
        return g

    def test_missing_declared_ranges_are_filled(self):
        g = self._gen({"x": {"factors": {
            "x.dtype": ["float16"],
            "x.value_range_float16": [["inf", "inf"], ["nan", "nan"], [0, 0]],
        }}})
        cases = [{"x.dtype": "float16", "x.value_range": [0, 0]}]
        out = g.complete_value_range_coverage(cases)
        realized = {tuple(c["x.value_range"]) for c in out if c["x.dtype"] == "float16"}
        assert realized == {("inf", "inf"), ("nan", "nan"), (0, 0)}

    def test_clone_preserves_other_factors(self):
        g = self._gen({"x": {"factors": {
            "x.dtype": ["float16"],
            "x.value_range_float16": [["inf", "inf"]],
        }}})
        cases = [{"x.dtype": "float16", "x.value_range": [0, 0], "x.shape": [1, 2, 3, 4, 5]}]
        out = g.complete_value_range_coverage(cases)
        assert any(c["x.value_range"] == ["inf", "inf"] and c["x.shape"] == [1, 2, 3, 4, 5]
                   for c in out)

    def test_dtype_without_base_case_is_skipped(self):
        g = self._gen({"x": {"factors": {
            "x.dtype": ["float16", "float32"],
            "x.value_range_float32": [["inf", "inf"]],
        }}})
        cases = [{"x.dtype": "float16", "x.value_range": [0, 0]}]
        out = g.complete_value_range_coverage(cases)
        assert len(out) == 1
        assert all(c["x.dtype"] != "float32" for c in out)

    def test_already_covered_is_unchanged(self):
        g = self._gen({"x": {"factors": {
            "x.dtype": ["float16"],
            "x.value_range_float16": [[0, 0]],
        }}})
        cases = [{"x.dtype": "float16", "x.value_range": [0, 0]}]
        assert g.complete_value_range_coverage(cases) == cases

    def test_structure_key_ignores_value_range(self):
        g = self._gen({})
        a = {"x.dtype": "float16", "x.value_range": [0, 0], "x.shape": [1]}
        b = {"x.dtype": "float16", "x.value_range": [9, 9], "x.shape": [1]}
        assert g._structure_key(a) == g._structure_key(b)

    def test_missing_ranges_rotate_across_structures(self):
        """Clones must spread over distinct structural templates, not pile on one.

        Old behavior cloned ``same_dtype[0]`` for every missing range → all added
        rows shared one shape (L0 got ~21 structurally-identical rows).
        """
        g = self._gen({"x": {"factors": {
            "x.dtype": ["float16"],
            "x.value_range_float16": [[0, 0], [1, 1], [2, 2], [3, 3]],
        }}})
        cases = [
            {"x.dtype": "float16", "x.value_range": [0, 0], "x.shape": [1, 1, 1, 1, 4]},
            {"x.dtype": "float16", "x.value_range": [9, 9], "x.shape": [2, 2, 2, 2, 8]},
        ]
        out = g.complete_value_range_coverage(cases)
        clones = out[2:]
        # 3 missing ranges rotate over the 2 distinct structures
        assert [tuple(c["x.shape"]) for c in clones] == [
            (1, 1, 1, 1, 4), (2, 2, 2, 2, 8), (1, 1, 1, 1, 4),
        ]
        assert [c["x.value_range"] for c in clones] == [[1, 1], [2, 2], [3, 3]]
        # all declared ranges still realized (coverage guarantee preserved)
        realized = {tuple(c["x.value_range"]) for c in out}
        assert realized >= {(0, 0), (1, 1), (2, 2), (3, 3)}


# ── P4: generate_all_cases must not fake-pad with duplicates ─────────────────


class TestGenerateAllCasesNoFakePad:
    def test_does_not_duplicate_when_fewer_than_max(self, monkeypatch):
        g = fv.FactorValueGenerator()
        base = [{"x.dtype": "float16", "x.value_range": [0, 0]}]

        monkeypatch.setattr(g, "generate_bc_combinations", lambda max_combinations=None: [{}])
        monkeypatch.setattr(g, "generate_complete_cases", lambda combos: list(base))
        out = g.generate_all_cases(max_cases=100)
        assert out == base


# ── L1 pairwise: enum attributes in target, feasibility from pool ────────────


class TestSelectPairwiseFactors:
    def test_enum_value_included_non_enum_and_derived_excluded(self):
        df = pd.DataFrame({
            "interpolation_mode.value": ["bilinear", "nearest"],
            "alpha.value": [0.1, 0.2],           # non-enum scalar (derived) → excluded
            "x.dtype": ["float16", "float32"],
            "x.shape": ["[1]", "[2]"],           # derived → excluded
            "x.value_range": ["[0, 0]", "[1, 1]"],  # continuous → excluded
            "y.exist": [True, True],             # single-value → no pairwise meaning
        })
        param_def = {"parameters": [
            {"name": "interpolation_mode", "is_enum": True},
            {"name": "alpha", "is_enum": False},
        ]}
        factors = tc.select_pairwise_factors(df, param_def)
        assert set(factors) == {"interpolation_mode.value", "x.dtype"}

    def test_value_requires_is_enum_declaration_not_hardcoded_name(self):
        df = pd.DataFrame({"foo.value": ["a", "b"]})
        assert tc.select_pairwise_factors(
            df, {"parameters": [{"name": "foo", "is_enum": True}]}
        ) == {"foo.value": {"a", "b"}}
        # no is_enum declaration → not treated as enumeration (structural signal)
        assert tc.select_pairwise_factors(df, {"parameters": [{"name": "foo"}]}) == {}


class TestFeasiblePairwiseCombinations:
    def test_pairs_come_from_pool_not_cartesian(self):
        # constraint forces x.dtype == grid.dtype → the cross pairs are infeasible
        df = pd.DataFrame({
            "x.dtype": ["float16", "float32"],
            "grid.dtype": ["float16", "float32"],
        })
        discrete = {
            "x.dtype": {"float16", "float32"},
            "grid.dtype": {"float16", "float32"},
        }
        combos = tc.generate_pairwise_combinations(df, discrete)
        assert combos == {
            (("grid.dtype", "float16"), ("x.dtype", "float16")),
            (("grid.dtype", "float32"), ("x.dtype", "float32")),
        }

    def test_greedy_covers_all_feasible_pairs(self):
        df = pd.DataFrame({
            "interpolation_mode.value": ["bilinear", "nearest", "bilinear", "nearest"],
            "padding_mode.value": ["zeros", "zeros", "border", "reflection"],
            "x.dtype": ["float16", "float16", "float32", "float32"],
        })
        param_def = {"parameters": [
            {"name": "interpolation_mode", "is_enum": True},
            {"name": "padding_mode", "is_enum": True},
        ]}
        discrete = tc.select_pairwise_factors(df, param_def)
        combos = tc.generate_pairwise_combinations(df, discrete)
        selected, coverage = tc.select_cases_L1(df, combos, discrete)
        assert coverage["covered_pairwise"] == coverage["total_pairwise"] == len(combos)
        assert coverage["uncovered_pairwise"] == 0
        assert len(selected) >= 1


class TestL1ReportAndSave:
    def test_report_uses_discrete_factors_and_honest_counts(self):
        discrete = {"a.value": {"x", "y"}, "b.dtype": {"float16", "float32"}}
        coverage = {
            "total_pairwise": 4, "covered_pairwise": 4, "uncovered_pairwise": 0,
            "coverage_rate": 100.0, "selected_count": 3,
        }
        report = tc.generate_L1_report(
            {(f, v) for f in discrete for v in discrete[f]}, coverage, discrete,
            target_count=100, final_count=10)
        s = report["summary"]
        assert s["pairwise_factor_count"] == 2
        assert s["selected_case_count"] == 3
        assert s["padded_case_count"] == 7
        assert s["final_case_count"] == 10
        assert set(report["factor_statistics"]) == set(discrete)

    def test_l1_coverage_report_is_written(self, tmp_path):
        import types
        args = types.SimpleNamespace(output_dir=str(tmp_path), verbose=False)
        params = tc.SaveCaseParams(
            level="L1", args=args, report={"summary": {"level": "L1"}},
            case_df_ttk=pd.DataFrame({"testcase_name": ["t1"]}),
            report_file="aclnnX_L1_coverage_report.yaml",
            case_file="L1_test_cases.csv", aclnn_name="aclnnX")
        tc._save_case_results(params)
        assert (tmp_path / "aclnnX_L1_coverage_report.yaml").exists()
        assert (tmp_path / "aclnnX_L1_test_cases.csv").exists()


class TestAbsentOptionalInputPlaceholder:
    """缺省可选输入必须在 TTK 中间格式按 proto 位置留 ``None`` 占位（镜像
    cann-bench ``null``）——压缩会让其后输入整体上移，下游按位置绑定出错。"""

    @staticmethod
    def _param_def():
        return {
            "a": {"name": "a", "type": "aclTensor", "io_type": "input",
                  "dimensions": [2]},
            "b": {"name": "b", "type": "aclTensor", "io_type": "input",
                  "dimensions": [2]},
            "out": {"name": "out", "type": "aclTensor", "io_type": "output",
                    "dimensions": [2]},
        }

    @staticmethod
    def _row(**over):
        row = {
            "a.exist": True, "b.exist": True, "out.exist": True,
            "a.shape": "[2, 3]", "b.shape": "[4, 5]", "out.shape": "[2, 5]",
            "a.dtype": "float16", "b.dtype": "float16", "out.dtype": "float16",
            "a.value_range": "[0, 1]", "b.value_range": "[0, 1]",
        }
        row.update(over)
        return pd.Series(row)

    def _case(self, row):
        pdef = self._param_def()
        ctx = tc.TtkProcessContext(
            row=row, idx=2, param_def=pdef, param_names=list(pdef),
            aclnn_name="aclnnX", case_level="L0")
        return tc._process_single_ttk_case(ctx)

    def test_all_present_no_placeholder(self):
        import ast
        case = self._case(self._row())
        assert ast.literal_eval(case["tensor_view_shapes"]) == (
            (2, 3), (4, 5), (2, 5))
        assert ast.literal_eval(case["output_tensor_indexes"]) == (2,)

    def test_absent_optional_keeps_none_slot(self):
        import ast
        case = self._case(self._row(**{"b.exist": False}))
        # b absent → None at proto slot 1; out follows at slot 2 (not shifted).
        assert ast.literal_eval(case["tensor_view_shapes"]) == (
            (2, 3), None, (2, 5))
        assert ast.literal_eval(case["tensor_dtypes"]) == (
            "float16", None, "float16")
        assert ast.literal_eval(case["input_data_ranges"]) == ((0, 1), None)
        assert ast.literal_eval(case["output_tensor_indexes"]) == (2,)


# ── 符号值域边界必须在生成期诚实报错，不得流入用例 ────────────────────────────


class TestSymbolicValueRangeGate:
    """值域候选含符号边界（如依赖 shape 的 ``C-1``）必须在生成端报错。

    历史缺陷：符号候选原样写进用例 CSV，消费端缺失 value_range 时回退默认
    区间，为 int64 targets 生成 -1（非法类别下标），批量精度全挂。符号值域
    唯一合法表达是形状来源的 calculate 约束（sources 指 shape 类因子，
    expression 算出数值 [lo, hi]）；声明候选必须全数值（含 inf/-inf/nan）。
    """

    # ── utils 共享判定 ──

    def test_bound_predicate_accepts_numeric_and_special_literals(self):
        u = _load("utils")
        for v in (0, -7, 1.5, "inf", "-inf", "nan", "+0", "-0", "1e3"):
            assert u.is_numeric_range_bound(v), v

    def test_bound_predicate_rejects_symbolic_and_nonscalar(self):
        u = _load("utils")
        for v in ("C-1", "batch", "logits.shape[1]", True, False, None,
                  [0, 1]):
            assert not u.is_numeric_range_bound(v), v

    # ── 求解端：声明候选的全部读取口 ──

    @staticmethod
    def _solver_with(factors):
        g = fv.FactorValueGenerator()
        g.test_factors = factors
        return g

    def test_dtype_expansion_rejects_symbolic_candidate(self):
        g = self._solver_with({"targets": {"type": "aclTensor", "factors": {
            "targets.value_range_int64": [[0, "C-1"]]}}})
        with pytest.raises(ValueError, match="C-1"):
            g.expand_value_range_for_dtype([{"targets.dtype": "int64"}])

    def test_dtype_expansion_accepts_numeric_candidates(self):
        g = self._solver_with({"targets": {"type": "aclTensor", "factors": {
            "targets.value_range_int64": [[0, 7], [0, 0], ["inf", "inf"]]}}})
        out = g.expand_value_range_for_dtype([{"targets.dtype": "int64"}])
        assert {tuple(c["targets.value_range"]) for c in out} == {
            (0, 7), (0, 0), ("inf", "inf")}

    def test_domain_fallback_rejects_symbolic_candidate(self):
        # 无约束因子兜底路径：get_factor_domain 前缀匹配读取声明候选。
        g = self._solver_with({"targets": {"type": "aclTensor", "factors": {
            "targets.value_range_int64": [[0, "C-1"]]}}})
        with pytest.raises(ValueError, match="C-1"):
            g.get_factor_domain("targets.value_range_int64")

    def test_declared_coverage_rejects_symbolic_candidate(self):
        # 覆盖补齐路径：声明的每个候选都会被强制注入结果，符号候选必须
        # 在读取声明时就报错，而不是覆盖出非法用例。
        g = self._solver_with({"targets": {"type": "aclTensor", "factors": {
            "targets.value_range_int64": [[0, "C-1"]]}}})
        with pytest.raises(ValueError, match="C-1"):
            g.complete_value_range_coverage([{
                "targets.dtype": "int64", "targets.shape": [2, 8],
                "targets.value_range": [0, 8]}])

    def test_calculate_constraint_path_error_not_swallowed(self):
        # 机械 derive_value_range_from_dtype 读到符号候选时，诚实错误不许被
        # solve_constraint_range 的兜底 except 吞成 None。
        g = self._solver_with({"targets": {"type": "aclTensor", "factors": {
            "targets.value_range_int64": [[0, "C-1"]]}}})
        constraint = {
            "type": "calculate", "sources": ["targets.dtype"],
            "target": "targets.value_range",
            "expression": "derive_value_range_from_dtype(sources[0])"}
        with pytest.raises(ValueError, match="C-1"):
            g.solve_constraint_range(constraint, {"targets.dtype": "int64"})

    # ── 渲染端兜底（任何生产端漏网符号到渲染期即报错）──

    @staticmethod
    def _ttk_data(input_ranges):
        return tc.TtkCaseData(
            input_shapes=[[2, 8]], input_dtypes=["int64"],
            input_ranges=input_ranges, output_shapes=[], output_dtypes=[],
            output_indexes=[], scalar_dtypes_list=[], attrs_dict={},
            tensor_list_lengths=[])

    def test_render_rejects_surviving_symbolic_range(self):
        case = {"testcase_name": "aclnnX_L0_001"}
        with pytest.raises(ValueError, match="aclnnX_L0_001"):
            tc._build_ttk_case_data(case, self._ttk_data([[0, "C-1"]]))

    def test_render_accepts_numeric_nested_and_none_slots(self):
        case = {"testcase_name": "aclnnX_L0_001"}
        ranges = [[0, 7], None, ((0, 10), (0, 10)), ["inf", "-inf"]]
        tc._build_ttk_case_data(case, self._ttk_data(ranges))
        assert "input_data_ranges" in case

    # ── 隐式约束生成端：符号候选不得产出「按 dtype 机械选值」假约束 ──

    @staticmethod
    def _factor_files(tmp_path, ranges):
        import yaml as _yaml
        fp = tmp_path / "04.yaml"
        fp.write_text(_yaml.safe_dump({
            "targets": {"type": "aclTensor", "factors": {
                "targets.dtype": ["int64"],
                "targets.value_range_int64": ranges}}}), encoding="utf-8")
        cp = tmp_path / "05.yaml"
        cp.write_text("constraints: []\n", encoding="utf-8")
        return str(fp), str(cp)

    def test_symbolic_candidates_get_no_mechanical_range_constraint(
            self, tmp_path):
        ic = _load("generate_implicit_constraints")
        fp, cp = self._factor_files(tmp_path, [[0, "C-1"]])
        gen = ic.ImplicitConstraintGenerator(fp, cp)
        deps = gen._identify_implicit_dependencies()
        assert not any(d["rule"] == "value_range_from_dtype" for d in deps)

    def test_numeric_candidates_still_get_mechanical_range_constraint(
            self, tmp_path):
        ic = _load("generate_implicit_constraints")
        fp, cp = self._factor_files(tmp_path, [[0, 7]])
        gen = ic.ImplicitConstraintGenerator(fp, cp)
        deps = gen._identify_implicit_dependencies()
        assert any(d["rule"] == "value_range_from_dtype" for d in deps)
