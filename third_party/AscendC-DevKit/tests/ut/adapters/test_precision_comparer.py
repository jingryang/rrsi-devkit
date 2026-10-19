"""UT for ascendc_devkit.adapters.npu.precision_comparer（P79）。

守护 rule × backend 正交的 backend 侧：
- DevkitComparer（默认，零 import cann-bench）/ CannbenchComparer（可选注入）的 setup 行 + 聚合。
- judge_case_details 共享聚合（原 runner._all_outputs_within_threshold 提取）。

纯逻辑（无 NPU/CANN/LLM 依赖），不加 pytest mark（§3.5）。
"""

from ascendc_devkit.adapters.npu.precision_comparer import (
    CannbenchComparer,
    DevkitComparer,
    PrecisionComparer,
    judge_case_details,
)
from ascendc_devkit.domain.precision import CompareRule


# ---------------------------------------------------------------------------
# judge_case_details（共享聚合）
# ---------------------------------------------------------------------------

class TestJudgeCaseDetails:
    def _rule(self, **overrides):
        dts = {"int8": 1.0, "float16": 0.001, "float32": 0.0001}
        dts.update(overrides)
        return CompareRule(dtype_thresholds=dts)

    def test_empty_case_details_passes(self):
        assert judge_case_details(self._rule(), []) is True

    def test_case_level_error_fails(self):
        # P7：case 级 error（harness per-case except 记录的崩溃/超时/输出数量不匹配）
        # 必须判失败——旧逻辑只看 output_results，error case 无 output_results（空对比
        # 假绿洞的输出端）会被"无事可查"空过（§3.4 禁掩盖）。
        cds = [{"error": "ValueError: kernel/golden 输出数量不匹配", "diff": 999.0}]
        assert judge_case_details(self._rule(), cds) is False

    def test_error_case_not_vacuous_pass_even_with_empty_outputs(self):
        # error + 空 output_results（harness except 路径产物）→ 仍判失败，不得因
        # 无 output 可查而空过。
        cds = [{"error": "case failed", "output_results": [], "diff": 999.0}]
        assert judge_case_details(self._rule(), cds) is False

    def test_passed_field_authoritative(self):
        # cann-bench 路径：output 带 passed → 权威（diff 大也过）
        cds = [{"outputs": [{"passed": True, "diff": 999.0}]}]
        assert judge_case_details(self._rule(), cds) is True
        cds_fail = [{"outputs": [{"passed": False, "diff": 0.0}]}]
        assert judge_case_details(self._rule(), cds_fail) is False

    def test_diff_within_dtype_threshold_passes(self):
        # int8 diff=1.0 == threshold 1.0 → 过（DQ 场景：±1 量化差）
        cds = [{"outputs": [{"diff": 1.0, "dtype": "int8", "threshold": 1.0}]}]
        assert judge_case_details(self._rule(), cds) is True

    def test_diff_exceeds_dtype_threshold_fails(self):
        # int8 diff=1.0 但 proto 未放宽（threshold=0）→ 冤杀（DQ 根因）
        cds = [{"outputs": [{"diff": 1.0, "dtype": "int8", "threshold": 0.0}]}]
        assert judge_case_details(self._rule(int8=0.0), cds) is False

    def test_negative_diff_skipped_no_golden(self):
        cds = [{"outputs": [{"diff": -1.0, "dtype": "float16"}]}]
        assert judge_case_details(self._rule(), cds) is True

    def test_multi_output_all_must_pass(self):
        cds = [{"outputs": [
            {"diff": 0.5, "dtype": "int8", "threshold": 1.0},       # 过（0.5 ≤ 1.0）
            {"diff": 0.0005, "dtype": "float16", "threshold": 0.001},  # 过（0.0005 ≤ 0.001）
        ]}]
        assert judge_case_details(self._rule(), cds) is True
        cds_fail = [{"outputs": [
            {"diff": 0.5, "dtype": "int8", "threshold": 1.0},        # 过
            {"diff": 0.005, "dtype": "float16", "threshold": 0.001}, # 挂（0.005 > 0.001）
        ]}]
        assert judge_case_details(self._rule(), cds_fail) is False

    def test_output_results_key_also_supported(self):
        # 'output_results' 新格式键名兼容
        cds = [{"output_results": [{"passed": True}]}]
        assert judge_case_details(self._rule(), cds) is True

    def test_unknown_dtype_falls_back_to_output_threshold(self):
        # 未知 dtype + output 自带 threshold → 用之
        cds = [{"outputs": [{"diff": 0.05, "dtype": "weirddtype", "threshold": 0.1}]}]
        assert judge_case_details(self._rule(), cds) is True

    def test_empty_output_data_is_failure_not_vacuous_pass(self):
        # unique 假通过根因：compare_tensors 输出数量不匹配 → 空 output_results
        # + passed=False 被 harness 丢弃 → case 无任何输出数据 → 旧逻辑空循环
        # 空真通过。数据缺失不是通过证据，必须判失败。
        cds = [{"case": "c1", "diff": 0.0, "elapsed_ms": 10.0}]
        assert judge_case_details(self._rule(), cds) is False

    def test_case_error_is_failure_not_vacuous_pass(self):
        # case 级执行异常（error 字段）且无输出数据 → 失败，不得空真通过
        cds = [{"case": "c1", "error": "kernel crashed", "elapsed_ms": 10.0}]
        assert judge_case_details(self._rule(), cds) is False

    def test_empty_case_details_still_passes(self):
        # 空 case_details（无 case）语义保持：runner 只在 case_details 非空时
        # 调 aggregate，空列表不构成"数据缺失的 case"
        assert judge_case_details(self._rule(), []) is True


# ---------------------------------------------------------------------------
# DevkitComparer
# ---------------------------------------------------------------------------

class TestDevkitComparer:
    def test_is_precision_comparer(self):
        # Protocol 满足性（structural）
        comparer: PrecisionComparer = DevkitComparer()
        assert comparer is not None

    def test_no_cannbench_import_in_setup(self):
        # §1.7：默认 backend 零 import cann-bench
        rule = CompareRule(dtype_thresholds={"int8": 1.0})
        lines = DevkitComparer().harness_setup_lines(rule)
        assert lines == []
        joined = "\n".join(lines)
        assert "kernel_eval" not in joined

    def test_aggregate_delegates_to_judge(self):
        rule = CompareRule(dtype_thresholds={"int8": 1.0})
        cds_pass = [{"outputs": [{"diff": 1.0, "dtype": "int8", "threshold": 1.0}]}]
        cds_fail = [{"outputs": [{"passed": False}]}]
        assert DevkitComparer().aggregate(rule, cds_pass) is True
        assert DevkitComparer().aggregate(rule, cds_fail) is False


# ---------------------------------------------------------------------------
# CannbenchComparer
# ---------------------------------------------------------------------------

class TestCannbenchComparer:
    def test_setup_injects_kernel_eval_import(self):
        rule = CompareRule(dtype_thresholds={"int8": 1.0})
        lines = CannbenchComparer().harness_setup_lines(rule)
        joined = "\n".join(lines)
        # 注入 cann-bench compare_tensors import
        assert "from kernel_eval.utils.compare import compare_tensors" in joined
        assert "_compare_tensors" in joined
        assert "_cann_checker_used" in joined

    def test_setup_soft_degrades_with_warning_not_silent(self):
        # §1.2 可诊断：import 失败 warn 留痕，不静默 except pass
        lines = CannbenchComparer().harness_setup_lines(CompareRule(dtype_thresholds={}))
        joined = "\n".join(lines)
        assert "except ImportError" in joined
        assert "warnings.warn" in joined  # 留痕，非静默

    def test_setup_locates_cann_src_by_structure_anchor(self, tmp_path):
        """F1: cann src 定位以 ``src/kernel_eval/utils/compare.py`` 结构锚点自
        golden 向上找，**不依赖** golden 落在 ``tasks/`` 还是
        ``bench_lab/kernel_bench/``。原 ``'tasks/' in path`` 嗅探对 bench_lab
        布局失配 → cann src 未加 sys.path → import 失败 → 误降级（batch
        20260731-132818 multi_add 实证）。"""
        import os, sys
        cann_root = tmp_path / "cannbench"
        (cann_root / "src" / "kernel_eval" / "utils").mkdir(parents=True)
        (cann_root / "src" / "kernel_eval" / "utils" / "compare.py").write_text(
            "def compare_tensors(*a, **k):\n    return None\n")
        cann_src_expected = str(cann_root / "src")

        lines = CannbenchComparer().harness_setup_lines(CompareRule(dtype_thresholds={}))
        code = "import os, sys\n" + "\n".join(lines)

        # 两种 golden 布局都必须定位到同一个 cann src（golden 与 src 同处一个
        # cann-bench 仓根——真实布局；原测试误把 golden 放 tmp_path 顶层致向上找不到）
        for layout in ("bench_lab/kernel_bench/level2/op", "tasks/level2/op"):
            golden = cann_root / layout / "golden.py"
            golden.parent.mkdir(parents=True, exist_ok=True)
            golden.write_text("# stub")
            saved = list(sys.path)
            ns = {"golden_source_path": str(golden)}
            try:
                exec(code, ns)
                assert cann_src_expected in sys.path, (
                    f"F1 regression: golden 布局 {layout} 未能定位 cann src")
            finally:
                sys.path[:] = saved

    def test_setup_no_cann_src_soft_fails(self, tmp_path):
        """F1: golden 向上无 ``src/kernel_eval/utils/compare.py`` → ``_cann_src``
        维持 None，不抛异常（软失败，交 try/except ImportError 降级路径）。"""
        import sys
        golden = tmp_path / "stray" / "golden.py"
        golden.parent.mkdir(parents=True)
        golden.write_text("# stub")
        lines = CannbenchComparer().harness_setup_lines(CompareRule(dtype_thresholds={}))
        code = "import os, sys\n" + "\n".join(lines)
        saved = list(sys.path)
        ns = {"golden_source_path": str(golden)}
        try:
            exec(code, ns)  # 不应抛
            assert ns.get("_cann_src") is None
        finally:
            sys.path[:] = saved

    def test_aggregate_uses_passed_field(self):
        rule = CompareRule(dtype_thresholds={"int8": 1.0})
        cds = [{"outputs": [{"passed": True, "diff": 999.0}]}]
        assert CannbenchComparer().aggregate(rule, cds) is True


# ---------------------------------------------------------------------------
# rule 贯穿（dim A）：proto 真值经 rule 驱动聚合
# ---------------------------------------------------------------------------

class TestRuleThreading:
    def test_proto_threshold_reaches_aggregate(self):
        # DQ 真值：proto int8=1.0（允许 ±1）→ diff=1.0 过；int8=0（默认）→ diff=1.0 冤杀
        cds = [{"outputs": [{"diff": 1.0, "dtype": "int8"}]}]
        rule_dq = CompareRule(dtype_thresholds={"int8": 1.0})  # proto 放宽
        rule_default = CompareRule(dtype_thresholds={"int8": 0.0})  # 默认 exact
        assert judge_case_details(rule_dq, cds) is True   # proto 真值 → 不冤杀
        assert judge_case_details(rule_default, cds) is False  # 默认 → 冤杀（P78 根因复现）
