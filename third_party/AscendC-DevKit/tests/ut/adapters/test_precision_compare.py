"""UT for ascendc_devkit.adapters.npu.precision_compare.

守护 P69：devkit 自实现的 cann-bench 对齐精度比较（标准方法 + 阈值作数据）。
纯 CPU torch 数学逻辑（无 NPU/CANN/LLM 运行时依赖），故不加 pytest mark（§3.5）。

关键场景：DQ 冤杀解除（int8 ±1 量化差 + threshold=1.0 → PASS）。
"""

import os

# UT 环境无 CANN（libhccl.so 缺失），import torch 会触发 torch_npu device-backend
# autoload 失败。precision_compare 的比较是纯 CPU（张量先 .cpu()，cann-bench 同路径），
# 不需 torch_npu。设 autoload=0 让纯 torch CPU 可用（memory torch-npu-autoload-conflict）。
# 仅此 UT 文件 test-local 设置——devkit 其余 UT 不 import torch（runner lazy import + mock）。
os.environ.setdefault("TORCH_DEVICE_BACKEND_AUTOLOAD", "0")

import pytest
import torch

from ascendc_devkit.adapters.npu.precision_compare import (
    compare_outputs,
    validate_index_gather_outputs,
)
from ascendc_devkit.domain.precision import (
    DEFAULT_THRESHOLDS,
    SMALL_VALUE_THRESHOLDS,
    merge_thresholds,
    threshold_for_dtype,
)


# ---------------------------------------------------------------------------
# 阈值数据 + 查询
# ---------------------------------------------------------------------------

class TestThresholdData:
    def test_default_table_values_aligned_to_cannbench(self):
        # 值对齐 cann-bench thresholds.py（作传递数据，非 import）
        assert DEFAULT_THRESHOLDS["float16"] == 2 ** -10
        assert DEFAULT_THRESHOLDS["bfloat16"] == 2 ** -7
        assert DEFAULT_THRESHOLDS["float32"] == 2 ** -13
        assert DEFAULT_THRESHOLDS["float64"] == 2 ** -13
        assert DEFAULT_THRESHOLDS["hifloat32"] == 2 ** -11
        assert DEFAULT_THRESHOLDS["float8_e4m3fn"] == 2 ** -3
        assert DEFAULT_THRESHOLDS["float8_e5m2"] == 2 ** -2
        # 整数默认 exact（threshold=0）
        for d in ("int8", "int16", "int32", "int64", "uint8", "uint16", "uint32", "uint64"):
            assert DEFAULT_THRESHOLDS[d] == 0

    def test_threshold_for_dtype_merged_overrides_default(self):
        # proto 覆盖优先（merged 含该 dtype）
        assert threshold_for_dtype("int8", {"int8": 1.0}) == 1.0
        # merged 缺该 dtype → 默认表
        assert threshold_for_dtype("int8", {}) == 0.0
        assert threshold_for_dtype("float32", {}) == 2 ** -13

    def test_threshold_for_dtype_unknown_falls_back_to_float32(self):
        # 未知 dtype → float32 阈值（cann-bench get_threshold 同语义）
        assert threshold_for_dtype("unknowndtype", {}) == 2 ** -13
        assert threshold_for_dtype("UNKOWNDTYPE", {}) == 2 ** -13  # 大小写不敏感


class TestMergeThresholds:
    """P79 维度 A 桥接：默认表 ⊕ proto 覆盖 → CompareRule.dtype_thresholds 唯一入口。"""

    def test_none_proto_returns_default_table_copy(self):
        merged = merge_thresholds(None)
        assert merged == DEFAULT_THRESHOLDS
        # 返回副本，改它不污染规范表
        merged["int8"] = 99.0
        assert DEFAULT_THRESHOLDS["int8"] == 0

    def test_empty_dict_returns_default_table(self):
        assert merge_thresholds({}) == DEFAULT_THRESHOLDS

    def test_proto_overrides_default_per_dtype(self):
        # DQ 场景：proto 声明 int8=1.0（允许 ±1 量化）覆盖默认 0
        merged = merge_thresholds({"int8": 1.0})
        assert merged["int8"] == 1.0
        # 未覆盖的 dtype 保留默认
        assert merged["float16"] == 2 ** -10
        assert merged["float32"] == 2 ** -13

    def test_proto_partial_override_only_listed_dtypes(self):
        merged = merge_thresholds({"bfloat16": 0.05, "float32": 1e-6})
        assert merged["bfloat16"] == 0.05
        assert merged["float32"] == 1e-6
        assert merged["int8"] == 0  # 未覆盖保留默认


# ---------------------------------------------------------------------------
# 整数路径（DQ 冤杀核心）
# ---------------------------------------------------------------------------

class TestIntegerPath:
    def test_dq_int8_plus_minus_one_within_threshold_passes(self):
        """DQ 冤杀解除：int8 ±1 量化差，proto threshold=1.0 → PASS。

        这是 P69 的根因场景：devkit 旧硬编 1e-2 → 1.0>0.01 误杀；
        cann-bench 1.0<=1.0 通过。"""
        golden = torch.tensor([0, 1, 2, 3], dtype=torch.int8)
        output = torch.tensor([0, 2, 2, 4], dtype=torch.int8)  # diff = [0,1,0,1]
        verdict = compare_outputs(output, golden, merged_thresholds={"int8": 1.0})
        assert verdict.passed is True

    def test_int8_diff_exceeds_threshold_fails(self):
        golden = torch.tensor([0, 1], dtype=torch.int8)
        output = torch.tensor([0, 3], dtype=torch.int8)  # diff=[0,2] > 1.0
        verdict = compare_outputs(output, golden, merged_thresholds={"int8": 1.0})
        assert verdict.passed is False

    def test_int_exact_when_threshold_zero(self):
        golden = torch.tensor([0, 1, 2], dtype=torch.int32)
        output = torch.tensor([0, 1, 2], dtype=torch.int32)
        assert compare_outputs(
            output, golden, merged_thresholds={"int32": 0.0}
        ).passed is True
        output2 = torch.tensor([0, 2, 2], dtype=torch.int32)  # diff=[0,1,0]
        assert compare_outputs(
            output2, golden, merged_thresholds={"int32": 0.0}
        ).passed is False

    def test_int_default_threshold_is_exact(self):
        # 默认表 int=0 → 要求 exact（merged 无覆盖）
        golden = torch.tensor([10, 20], dtype=torch.int64)
        output = torch.tensor([10, 21], dtype=torch.int64)
        verdict = compare_outputs(output, golden, merged_thresholds={})
        assert verdict.passed is False


# ---------------------------------------------------------------------------
# 浮点 MERE/MARE
# ---------------------------------------------------------------------------

class TestFloatMereMare:
    def test_float32_tiny_relative_error_passes_stage1(self):
        golden = torch.tensor([1.0, 2.0, 3.0, 4.0], dtype=torch.float32)
        output = golden * (1 + 1e-6)  # 相对误差 ≈1e-6 << 2^-13
        verdict = compare_outputs(output, golden, merged_thresholds={"float32": 2 ** -13})
        assert verdict.passed is True

    def test_float32_large_relative_error_fails(self):
        golden = torch.tensor([1.0, 2.0, 3.0], dtype=torch.float32)
        output = golden * 2.0  # 相对误差 ≈1.0，正常值域 → 直接失败
        verdict = compare_outputs(output, golden, merged_thresholds={"float32": 2 ** -13})
        assert verdict.passed is False

    def test_float32_exact_passes(self):
        golden = torch.tensor([1.0, 2.0], dtype=torch.float32)
        output = golden.clone()
        verdict = compare_outputs(output, golden, merged_thresholds={"float32": 2 ** -13})
        assert verdict.passed is True
        assert verdict.mere == 0.0
        assert verdict.mare == 0.0


# ---------------------------------------------------------------------------
# bit-exact（threshold=0 浮点）
# ---------------------------------------------------------------------------

class TestBitExact:
    def test_bit_exact_identical_passes(self):
        golden = torch.tensor([1.0, 2.0], dtype=torch.float32)
        output = golden.clone()
        verdict = compare_outputs(output, golden, merged_thresholds={"float32": 0.0})
        assert verdict.passed is True

    def test_bit_exact_signed_zero_distinguished(self):
        # +0.0 vs -0.0：IEEE754 相等但字节不同 → bit-exact 判 fail
        golden = torch.tensor([0.0], dtype=torch.float32)
        output = torch.tensor([-0.0], dtype=torch.float32)
        verdict = compare_outputs(output, golden, merged_thresholds={"float32": 0.0})
        assert verdict.passed is False


# ---------------------------------------------------------------------------
# 多输出 / ignore / None
# ---------------------------------------------------------------------------

class TestMultiOutput:
    def test_one_output_failing_fails_overall(self):
        g1 = torch.tensor([1, 2], dtype=torch.int8)
        o1 = torch.tensor([1, 2], dtype=torch.int8)  # pass
        g2 = torch.tensor([1, 2], dtype=torch.int8)
        o2 = torch.tensor([1, 5], dtype=torch.int8)  # diff=[0,3] fail
        verdict = compare_outputs(
            [o1, o2], [g1, g2], merged_thresholds={"int8": 1.0}
        )
        assert verdict.passed is False
        assert len(verdict.output_verdicts) == 2
        assert verdict.output_verdicts[0].passed is True
        assert verdict.output_verdicts[1].passed is False

    def test_ignore_indices_skips_output(self):
        g1 = torch.tensor([1, 2], dtype=torch.int8)
        o1 = torch.tensor([1, 2], dtype=torch.int8)
        g2 = torch.tensor([1, 2], dtype=torch.int8)
        o2 = torch.tensor([9, 9], dtype=torch.int8)  # 本会 fail
        verdict = compare_outputs(
            [o1, o2], [g1, g2], merged_thresholds={"int8": 1.0}, ignore_indices=[1]
        )
        assert verdict.passed is True  # index 1 被跳过

    def test_both_none_output_passes(self):
        verdict = compare_outputs(
            [None], [None], merged_thresholds={"float32": 2 ** -13}
        )
        assert verdict.passed is True

    def test_single_side_none_fails(self):
        verdict = compare_outputs(
            [torch.tensor([1.0])], [None], merged_thresholds={"float32": 2 ** -13}
        )
        assert verdict.passed is False

    def test_count_mismatch_returns_passed_false_with_empty_verdicts(self):
        # P7：kernel 输出数 != golden 输出数（条件输出算子 golden 单张量 vs kernel
        # 固定二元组）→ compare_outputs 必须显式失败，且空 verdicts 是数量不匹配的
        # 唯一信号（数量匹配时 None 对/ignore/真实对比三路必 append verdict）。
        outs = [torch.tensor([1, 2]), torch.tensor([0])]   # kernel 恒二元组
        golds = [torch.tensor([1, 2])]                     # golden 单张量
        verdict = compare_outputs(outs, golds, merged_thresholds={"int8": 1.0})
        assert verdict.passed is False
        assert "数量不匹配" in verdict.error_msg
        assert verdict.output_verdicts == []  # 空 verdicts ⇔ count mismatch（harness 据此判 fail）

    def test_count_mismatch_never_has_verdicts(self):
        # 数量匹配时（含全 ignore_indices）必有 verdicts——证明"空 verdicts ⇔ 数量不匹配"，
        # harness 的 P7 守卫（空 verdicts → raise）不会误伤合法场景。
        g1 = torch.tensor([1, 2], dtype=torch.int8)
        o1 = torch.tensor([9, 9], dtype=torch.int8)
        # 全 ignore 仍 append "跳过对比" verdict
        verdict = compare_outputs([o1], [g1], merged_thresholds={"int8": 1.0}, ignore_indices=[0])
        assert verdict.passed is True
        assert len(verdict.output_verdicts) == 1

    def test_shape_mismatch_sets_structured_signal(self):
        """F4：shape 不匹配必须给结构化信号（shape_mismatch），且「output 空而 golden
        非空」要置 empty_output_suspect——供 scope_guard/diagnose 把输出定型缺陷
        （plugin/harness/codegen 层）与 kernel 数值问题区分，不烧精度循环预算。
        unique 20260808 P4（y=Size([0]) vs golden Size([19058])）即此特征。"""
        verdict = compare_outputs(
            [torch.tensor([], dtype=torch.float32)],
            [torch.tensor([1.0, 2.0, 3.0], dtype=torch.float32)],
            merged_thresholds={"float32": 2 ** -13})
        assert verdict.passed is False
        v = verdict.output_verdicts[0]
        assert v.shape_mismatch is True
        assert v.empty_output_suspect is True       # output 空 vs golden 非空
        assert "疑似输出定型缺陷" in v.error_msg
        assert v.to_dict()["shape_mismatch"] is True
        assert v.to_dict()["empty_output_suspect"] is True

    def test_shape_mismatch_nonempty_not_empty_suspect(self):
        """F4：shape 不匹配但 output 非空 → 只置 shape_mismatch，不置
        empty_output_suspect（可能是 kernel 真算错 shape，不是定型缺陷特征）。"""
        verdict = compare_outputs(
            [torch.tensor([1.0, 2.0], dtype=torch.float32)],
            [torch.tensor([1.0, 2.0, 3.0], dtype=torch.float32)],
            merged_thresholds={"float32": 2 ** -13})
        assert verdict.passed is False
        v = verdict.output_verdicts[0]
        assert v.shape_mismatch is True
        assert v.empty_output_suspect is False
        assert "疑似输出定型缺陷" not in v.error_msg


# ---------------------------------------------------------------------------
# index_gather（TopK idx 输出：tie 顺序无关的"指向值"校验，移植 batch
# index_check.validate_index_output 语义，消息对齐）
# ---------------------------------------------------------------------------

class TestIndexGather:
    """proto output index_gather → 逐元素比较跳过，改为
    ``x.gather(dim, idx) == values`` 自洽校验（防"乱填索引也过"缺口）。"""

    def _spec(self, input_idx=0, dim_attr="dim", value_output_idx=0):
        return {"input_idx": input_idx, "dim_attr": dim_attr, "value_output_idx": value_output_idx}

    def test_tie_tolerant_pass(self):
        # torch.topk tie 顺序可以是 [0,1,2] 或 [2,1,0]——idx=[2,1,0] 指向值正确即过
        x = torch.tensor([5.0, 3.0, 5.0])
        idx = torch.tensor([2, 1, 0], dtype=torch.int64)
        values = torch.tensor([5.0, 3.0, 5.0])
        ok, msg = validate_index_gather_outputs(
            1, self._spec(), [x], [values, idx], {"dim": 0})
        assert ok is True, msg

    def test_wrong_target_fails(self):
        x = torch.tensor([5.0, 3.0, 5.0])
        idx = torch.tensor([2, 1, 0], dtype=torch.int64)
        values = torch.tensor([5.0, 5.0, 3.0])  # gathered=[5,3,5]；第 1/2 处不符
        ok, msg = validate_index_gather_outputs(
            1, self._spec(), [x], [values, idx], {"dim": 0})
        assert ok is False
        assert "不一致（2 处不符）" in msg

    def test_nan_aware_pass(self):
        # value_range=[nan,nan] 全 NaN 用例：两侧同为 NaN 视为相等
        x = torch.tensor([float("nan"), float("nan")])
        idx = torch.tensor([0, 1], dtype=torch.int64)
        values = torch.tensor([float("nan"), float("nan")])
        ok, msg = validate_index_gather_outputs(
            1, self._spec(), [x], [values, idx], {"dim": 0})
        assert ok is True, msg

    def test_dim_attr_missing_fails(self):
        # dim_attr 缺失不静默兜底（会在错误维度 gather）——判失败暴露配置问题
        x = torch.tensor([5.0, 3.0, 5.0])
        idx = torch.tensor([0], dtype=torch.int64)
        values = torch.tensor([5.0])
        ok, msg = validate_index_gather_outputs(
            1, self._spec(), [x], [values, idx], {})
        assert ok is False
        assert "缺少维度属性 'dim'" in msg

    def test_dim_out_of_range_fails(self):
        x = torch.tensor([5.0, 3.0, 5.0])
        idx = torch.tensor([0], dtype=torch.int64)
        values = torch.tensor([5.0])
        ok, msg = validate_index_gather_outputs(
            1, self._spec(), [x], [values, idx], {"dim": 5})
        assert ok is False
        assert "dim=5 越界（输入 1 维）" in msg

    def test_dim_negative_normalized(self):
        x = torch.tensor([5.0, 3.0, 5.0])
        idx = torch.tensor([2, 1, 0], dtype=torch.int64)
        values = torch.tensor([5.0, 3.0, 5.0])
        ok, msg = validate_index_gather_outputs(
            1, self._spec(), [x], [values, idx], {"dim": -1})
        assert ok is True, msg

    def test_shape_mismatch_fails(self):
        x = torch.tensor([5.0, 3.0, 5.0])
        idx = torch.tensor([0, 1], dtype=torch.int64)
        values = torch.tensor([5.0])  # 索引输出形状 [2] vs 值输出形状 [1]
        ok, msg = validate_index_gather_outputs(
            1, self._spec(), [x], [values, idx], {"dim": 0})
        assert ok is False
        assert "形状" in msg

    def test_index_bounds_fails(self):
        x = torch.tensor([5.0, 3.0, 5.0])
        idx = torch.tensor([7], dtype=torch.int64)
        values = torch.tensor([5.0])
        ok, msg = validate_index_gather_outputs(
            1, self._spec(), [x], [values, idx], {"dim": 0})
        assert ok is False
        assert "索引越界 [7,7]，合法区间 [0,3)" in msg

    def test_missing_input_tensor_fails(self):
        # inputs 里该位置为 None（optional 占位）→ 无法 gather
        x = torch.tensor([5.0, 3.0, 5.0])
        idx = torch.tensor([0], dtype=torch.int64)
        values = torch.tensor([5.0])
        ok, msg = validate_index_gather_outputs(
            1, self._spec(), [None], [values, idx], {"dim": 0})
        assert ok is False
        assert "找不到源输入张量" in msg

    def test_missing_value_output_fails(self):
        x = torch.tensor([5.0, 3.0, 5.0])
        idx = torch.tensor([0], dtype=torch.int64)
        ok, msg = validate_index_gather_outputs(
            1, self._spec(value_output_idx=2), [x], [None, idx], {"dim": 0})
        assert ok is False
        assert "缺少配对值输出" in msg

    def test_gather_output_skipped_from_element_compare_but_checked(self):
        # golden idx 是垃圾（逐元素必 fail），但 gather 自洽 → 整体 pass
        x = torch.tensor([5.0, 3.0, 5.0])
        o_values = torch.tensor([5.0, 3.0, 5.0])
        o_idx = torch.tensor([2, 1, 0], dtype=torch.int64)
        g_values = o_values.clone()
        g_idx = torch.tensor([0, 0, 0], dtype=torch.int64)  # 垃圾 golden idx
        verdict = compare_outputs(
            [o_values, o_idx], [g_values, g_idx],
            merged_thresholds={"float32": 2 ** -13},
            ignore_indices=[1], inputs=[x],
            index_gather_specs={1: self._spec()},
            case_attrs={"dim": 0},
        )
        assert verdict.passed is True
        assert verdict.output_verdicts[1].passed is True
        assert verdict.output_verdicts[1].error_msg == ""

    def test_gather_wrong_target_fails_despite_ignore(self):
        # idx 指向错值：即使 ignore_indices 声明，gather 失败仍整体 fail
        x = torch.tensor([5.0, 3.0, 5.0])
        o_values = torch.tensor([5.0, 3.0, 5.0])  # 值输出正确
        o_idx = torch.tensor([0, 0, 0], dtype=torch.int64)  # 全部指向 x[0]=5
        g_values = o_values.clone()
        g_idx = torch.tensor([0, 0, 0], dtype=torch.int64)
        verdict = compare_outputs(
            [o_values, o_idx], [g_values, g_idx],
            merged_thresholds={"float32": 2 ** -13},
            ignore_indices=[1], inputs=[x],
            index_gather_specs={1: self._spec()},
            case_attrs={"dim": 0},
        )
        assert verdict.passed is False
        assert "不一致（1 处不符）" in verdict.output_verdicts[1].error_msg

    def test_no_spec_no_change(self):
        # 不带 index_gather_specs：行为与既有调用完全一致
        g = torch.tensor([1, 2], dtype=torch.int8)
        o = torch.tensor([1, 5], dtype=torch.int8)
        verdict = compare_outputs(o, g, merged_thresholds={"int8": 1.0})
        assert verdict.passed is False


# ---------------------------------------------------------------------------
# NaN / Inf
# ---------------------------------------------------------------------------

class TestNanInf:
    def test_nan_position_mismatch_fails(self):
        golden = torch.tensor([1.0, float("nan")], dtype=torch.float32)
        output = torch.tensor([1.0, 2.0], dtype=torch.float32)  # golden[1]=NaN, output[1]=2
        verdict = compare_outputs(output, golden, merged_thresholds={"float32": 2 ** -13})
        assert verdict.passed is False

    def test_nan_position_match_passes(self):
        golden = torch.tensor([1.0, float("nan")], dtype=torch.float32)
        output = torch.tensor([1.0, float("nan")], dtype=torch.float32)
        verdict = compare_outputs(output, golden, merged_thresholds={"float32": 2 ** -13})
        assert verdict.passed is True

    def test_both_inf_same_sign_matches(self):
        golden = torch.tensor([float("inf")], dtype=torch.float32)
        output = torch.tensor([float("inf")], dtype=torch.float32)
        verdict = compare_outputs(output, golden, merged_thresholds={"float32": 2 ** -13})
        assert verdict.passed is True


# ---------------------------------------------------------------------------
# dtype 回退（per-output 运行时 dtype 查表）
# ---------------------------------------------------------------------------

class TestPerOutputDtype:
    def test_per_output_uses_runtime_dtype(self):
        # 第一个输出 float32（默认 thr 2^-13），第二个 int8（默认 thr 0 exact）
        g = [torch.tensor([1.0], dtype=torch.float32), torch.tensor([1], dtype=torch.int8)]
        o = [torch.tensor([1.0], dtype=torch.float32), torch.tensor([1], dtype=torch.int8)]
        verdict = compare_outputs(o, g, merged_thresholds={})
        assert verdict.passed is True
        assert verdict.output_verdicts[0].dtype == "float32"
        assert verdict.output_verdicts[1].dtype == "int8"
        assert verdict.output_verdicts[1].threshold == 0.0


# ---------------------------------------------------------------------------
# Parity（门控 cann-bench 在场；仅 test 期 import，非运行时依赖 §1.7）
# ---------------------------------------------------------------------------

def _cannbench_available() -> bool:
    """探测 cann-bench（import 名 kernel_eval）是否可用。

    cann-bench pyproject package=false，需 PYTHONPATH=<cann-bench>/src；
    import 触发 torch_npu autoload，需 TORCH_DEVICE_BACKEND_AUTOLOAD=0。
    缺任一条件 → skip（§3.7 诚实，非 mock）。
    """
    import importlib
    try:
        importlib.import_module("kernel_eval.utils.compare")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _cannbench_available(), reason="cann-bench (kernel_eval) 不可用：需 PYTHONPATH=<cann-bench>/src + TORCH_DEVICE_BACKEND_AUTOLOAD=0")
class TestParityCannBench:
    """devkit 标准方法 vs cann-bench 原版 compare_tensors 逐 case 对拍。"""

    def _cannbench_compare(self, output, golden, merged, ignore_output_indices=None):
        from kernel_eval.utils.compare import compare_tensors
        return compare_tensors(output, golden, custom_thresholds=merged,
                               ignore_output_indices=ignore_output_indices)

    def _assert_parity(self, output, golden, merged, ignore_indices=None):
        dev = compare_outputs(output, golden, merged_thresholds=merged,
                              ignore_indices=ignore_indices)
        cb = self._cannbench_compare(output, golden, merged,
                                     ignore_output_indices=ignore_indices)
        assert dev.passed == cb.passed, (
            f"parity 偏离: devkit={dev.passed} cann-bench={cb.passed}\n"
            f"  dev: mere={dev.mere:.3e} mare={dev.mare:.3e}\n"
            f"  cb:  mere={cb.mere:.3e} mare={cb.mare:.3e}"
        )

    def _cannbench_compare_with_native(self, output, golden, merged, native):
        """cann-bench compare_tensors 传 native_output——真实评测（evaluator
        golden_precision=fp64_cpu）正是这样调用的。"""
        from kernel_eval.utils.compare import compare_tensors
        return compare_tensors(output, golden, custom_thresholds=merged,
                               native_output=native)

    def _assert_parity_with_native(self, output, golden, merged, native):
        """devkit compare_outputs(native_refs) vs cann-bench
        compare_tensors(native_output) 逐 case 对拍（同精度参考两侧都传）。"""
        dev = compare_outputs(output, golden, merged_thresholds=merged,
                              native_refs=native)
        cb = self._cannbench_compare_with_native(output, golden, merged, native)
        assert dev.passed == cb.passed, (
            f"parity(native) 偏离: devkit={dev.passed} cann-bench={cb.passed}\n"
            f"  dev: mere={dev.mere:.3e} mare={dev.mare:.3e} "
            f"sv={dev.output_verdicts[0].small_value_passed} "
            f"cancel={dev.output_verdicts[0].cancel_passed} "
            f"normal={dev.output_verdicts[0].normal_passed}\n"
            f"  cb:  mere={cb.mere:.3e} mare={cb.mare:.3e} "
            f"sv={cb.small_value_passed} cancel={cb.cancel_passed} "
            f"normal={cb.normal_passed}"
        )

    def test_parity_ignore_indices(self):
        # ignore_indices 语义对拍：devkit skip 与 cann-bench ignore 判据一致
        o1 = torch.tensor([1, 2], dtype=torch.int8)
        o2 = torch.tensor([9, 9], dtype=torch.int8)  # 本会 fail，被 ignore
        g1 = torch.tensor([1, 2], dtype=torch.int8)
        g2 = torch.tensor([1, 2], dtype=torch.int8)
        self._assert_parity([o1, o2], [g1, g2], {"int8": 1.0}, ignore_indices=[1])

    def test_cannbench_ignore_output_results_keep_index_alignment(self):
        """F1 前提锁定：cann-bench compare_tensors 对被 ignore 输出**仍产出**
        output_results 条目（index 标注=输出索引）——harness 里
        ``enumerate(_cr.output_results)`` 与输出索引一致，``_gather_ok`` 合并
        不会错位。若 cann-bench 侧改为跳过产出，此测试先失败（harness 模板
        另有数量 warn 守护兜底）。"""
        o1 = torch.tensor([1, 2], dtype=torch.int8)
        o2 = torch.tensor([9, 9], dtype=torch.int8)  # 本会 fail，被 ignore
        g1 = torch.tensor([1, 2], dtype=torch.int8)
        g2 = torch.tensor([1, 2], dtype=torch.int8)
        cr = self._cannbench_compare([o1, o2], [g1, g2], {"int8": 1.0},
                                     ignore_output_indices=[1])
        assert len(cr.output_results) == 2, (
            "cann-bench ignore 输出必须仍产出 output_results 条目（否则 harness 枚举索引错位）")
        assert [r.index for r in cr.output_results] == [0, 1], (
            "output_results 的 index 标注必须与输出索引一致")
        assert cr.output_results[1].passed is True and cr.output_results[1].error_msg, (
            "被 ignore 的条目应 passed=True 且带跳过标记")

    def test_cannbench_count_mismatch_empty_output_results(self):
        """F3 前提锁定：cann-bench compare_tensors 在输出数量不匹配时返回
        passed=False + 空 output_results——harness 合成显式失败条目的触发
        条件（``passed False and not output_results``）与此行为耦合。"""
        o = [torch.tensor([1, 2], dtype=torch.int8)]
        g = [torch.tensor([1, 2], dtype=torch.int8), torch.tensor([3], dtype=torch.int8)]
        cr = self._cannbench_compare(o, g, {"int8": 1.0})
        assert cr.passed is False
        assert not cr.output_results

    def test_cannbench_both_none_outputs_keep_index_alignment(self):
        """output_names 归一化前提锁定：cann-bench compare_tensors 对**双边
        None**（optional 输出双方 absent，harness 右补 None 对齐后整体传列表）
        仍产出 output_results 条目（index=输出索引, passed=True）——枚举索引
        与输出索引保持对齐，``_gather_ok`` 合并不错位、F1 数量 warn 不误触发。
        若 cann-bench 改为跳过 None 对产出，此测试先失败。"""
        o = [torch.tensor([1, 2], dtype=torch.int8), None]
        g = [torch.tensor([1, 2], dtype=torch.int8), None]
        cr = self._cannbench_compare(o, g, {"int8": 1.0})
        assert len(cr.output_results) == 2, (
            "cann-bench 双边 None 必须仍产出 output_results 条目（否则右补 None 后枚举索引错位）")
        assert [r.index for r in cr.output_results] == [0, 1]
        assert cr.output_results[1].passed is True, "双边 None 应视为通过（跳过）"

    def test_parity_int8(self):
        cases = [
            (torch.tensor([0, 1, 2], dtype=torch.int8), torch.tensor([0, 2, 2], dtype=torch.int8), {"int8": 1.0}),
            (torch.tensor([0, 1], dtype=torch.int8), torch.tensor([0, 3], dtype=torch.int8), {"int8": 1.0}),
            (torch.tensor([0, 1, 2], dtype=torch.int8), torch.tensor([0, 1, 2], dtype=torch.int8), {"int8": 1.0}),
        ]
        for out, gold, merged in cases:
            self._assert_parity(out, gold, merged)

    def test_parity_float32(self):
        golden = torch.tensor([1.0, 2.0, 3.0, 4.0], dtype=torch.float32)
        for factor in (1 + 1e-6, 1.01, 2.0, 1.0):
            out = (golden * factor).to(torch.float32)
            self._assert_parity(out, golden, {"float32": 2 ** -13})

    def test_parity_bit_exact(self):
        # thr=0 浮点 → bit-exact：identical pass / ±0.0 fail
        g = torch.tensor([1.0, 2.0], dtype=torch.float32)
        self._assert_parity(g.clone(), g, {"float32": 0.0})
        self._assert_parity(
            torch.tensor([-0.0], dtype=torch.float32),
            torch.tensor([0.0], dtype=torch.float32),
            {"float32": 0.0},
        )

    def test_parity_bfloat16(self):
        golden = torch.tensor([1.0, 2.0, 3.0], dtype=torch.float32).to(torch.bfloat16)
        out_exact = golden.clone()
        out_drift = (golden.to(torch.float32) * 1.05).to(torch.bfloat16)
        self._assert_parity(out_exact, golden, {"bfloat16": 2 ** -7})
        self._assert_parity(out_drift, golden, {"bfloat16": 2 ** -7})

    def test_parity_nan(self):
        # NaN 位置匹配 → pass；不匹配 → fail
        self._assert_parity(
            torch.tensor([1.0, float("nan")], dtype=torch.float32),
            torch.tensor([1.0, float("nan")], dtype=torch.float32),
            {"float32": 2 ** -13},
        )
        self._assert_parity(
            torch.tensor([1.0, 2.0], dtype=torch.float32),
            torch.tensor([1.0, float("nan")], dtype=torch.float32),
            {"float32": 2 ** -13},
        )

    def test_small_value_no_cpu_ref_aligned_parity(self):
        # |golden| < small_value_threshold(float32)=2^-14 → 走 stage2 兜底。
        # 【对齐 2026-08-10】devkit compare_outputs 已**完全对齐** cann-bench
        # compare_tensors：无 CPU 参考时小值域恒 ratio≤2（容忍 ≤2 个），不再
        # 刻意更严。2026-08-01 的零容忍"有意偏离"已反转（防 golden=1e-6/output=65504
        # 假阳性守卫放弃，由用户拍板完全对齐；见 docs/plan 对齐记录）。
        thr = {"float32": 2 ** -13}
        gold = torch.tensor([1e-6, 1.0], dtype=torch.float32)      # [0] 小值域
        out_err = torch.tensor([2e-6, 1.0], dtype=torch.float32)   # [0] 1 个小值域误差
        # 无误差时 parity 成立（两侧都过）：
        self._assert_parity(gold.clone(), gold, thr)
        # 有小值域误差 + 无 CPU 参考：devkit 与 cann-bench 一致（ratio=1≤2 → 过）
        self._assert_parity(out_err, gold, thr)
        # 3 个误差（ratio=3>2）→ 两侧都失败
        gold3 = torch.tensor([1e-6, 1e-6, 1e-6, 1.0], dtype=torch.float32)
        out3 = torch.tensor([3e-6, 3e-6, 3e-6, 1.0], dtype=torch.float32)
        self._assert_parity(out3, gold3, thr)

    def test_parity_small_value_with_native(self):
        """parity 盲区（原零容忍特判只测无参考）：小值域带同精度参考。

        - CPU 参考干净 + NPU 1-2 错 → 两侧都 PASS（ratio≤2）
        - CPU 参考干净 + NPU 3 错 → 两侧都 FAIL（ratio>2）
        - CPU 参考自身也脏（小值域）→ 两侧都 PASS（ratio≤2）
        """
        thr = {"float32": 2 ** -13}
        gold = torch.tensor([1e-6, 1e-6, 1e-6, 1.0], dtype=torch.float32)
        clean = gold.clone()
        # NPU 1 错 / 2 错 + CPU 干净 → 两侧 PASS
        for nerr in (1, 2):
            out = torch.tensor(
                [1e-6 + 2e-6 if i < nerr else 1e-6 for i in range(3)] + [1.0],
                dtype=torch.float32)
            self._assert_parity_with_native(out, gold, thr, clean)
        # NPU 3 错 + CPU 干净 → 两侧 FAIL（ratio=3>2）
        out3 = torch.tensor([3e-6, 3e-6, 3e-6, 1.0], dtype=torch.float32)
        self._assert_parity_with_native(out3, gold, thr, clean)
        # CPU 参考自身也脏（2 处）→ ratio=3/2=1.5≤2 → 两侧 PASS
        dirty = torch.tensor([2e-6, 2e-6, 1e-6, 1.0], dtype=torch.float32)
        self._assert_parity_with_native(out3, gold, thr, dirty)

    def test_parity_cancel_with_native(self):
        """parity 盲区（相消带同精度参考）：output≈0 且 golden 在精度边界。"""
        thr = {"float32": 2 ** -13}
        gold = torch.tensor([1e-3, 1e-3, 1e-3, 1.0], dtype=torch.float32)
        clean = gold.clone()
        # NPU 1-2 相消误差 + CPU 干净 → 两侧 PASS
        for nerr in (1, 2):
            out = torch.tensor(
                [0.0 if i < nerr else 1e-3 for i in range(3)] + [1.0],
                dtype=torch.float32)
            self._assert_parity_with_native(out, gold, thr, clean)
        # CPU 参考自身也脏（相消同位置）→ 两侧 PASS
        dirty = torch.tensor([0.0, 0.0, 1e-3, 1.0], dtype=torch.float32)
        out3 = torch.tensor([0.0, 0.0, 0.0, 1.0], dtype=torch.float32)
        self._assert_parity_with_native(out3, gold, thr, dirty)

    def test_parity_normal_region_issue92(self):
        """parity 盲区（normal 区 #92 兜底）：正常值域同精度参考自身也脏时，
        允许候选不差于 2× 参考；参考干净维持严格失败。"""
        thr = {"float32": 2 ** -13}
        gold = torch.tensor([1.0, 2.0, 3.0, 4.0], dtype=torch.float32)
        # NPU 3 处超标(0.02)、CPU 参考自身 3 处也超标(0.01) → 两侧 PASS（#92 兜底）
        out3 = gold + torch.tensor([0.02, 0.02, 0.02, 0.0], dtype=torch.float32)
        dirty = gold + torch.tensor([0.01, 0.01, 0.01, 0.0], dtype=torch.float32)
        self._assert_parity_with_native(out3, gold, thr, dirty)
        # 参考干净 → 两侧 FAIL（normal 区有超标点不放宽）
        self._assert_parity_with_native(out3, gold, thr, gold.clone())
        # NPU 1 处超标、参考脏 → 两侧 PASS
        out1 = gold + torch.tensor([0.02, 0.0, 0.0, 0.0], dtype=torch.float32)
        self._assert_parity_with_native(out1, gold, thr, dirty)
        # ratio>2（NPU 5 超标 / 参考 2 超标）→ 两侧 FAIL
        g5 = torch.tensor([1.0, 2.0, 3.0, 4.0, 5.0], dtype=torch.float32)
        o5 = g5 + torch.tensor([0.02, 0.02, 0.02, 0.02, 0.02], dtype=torch.float32)
        n5 = g5 + torch.tensor([0.01, 0.01, 0.0, 0.0, 0.0], dtype=torch.float32)
        self._assert_parity_with_native(o5, g5, thr, n5)

    def test_output_verdict_exposes_normal_fields(self):
        """normal 区字段透出（对齐 cann-bench CompareResult.normal_*）：
        normal_error_count/normal_cpu_error_count/normal_total_count/normal_passed。"""
        thr = {"float32": 2 ** -13}
        gold = torch.tensor([1.0, 2.0, 3.0, 4.0], dtype=torch.float32)
        out = gold + torch.tensor([0.02, 0.02, 0.02, 0.0], dtype=torch.float32)
        dirty = gold + torch.tensor([0.01, 0.01, 0.01, 0.0], dtype=torch.float32)
        dev = compare_outputs(out, gold, merged_thresholds=thr, native_refs=dirty)
        v = dev.output_verdicts[0]
        assert v.normal_error_count == 3
        assert v.normal_cpu_error_count == 3
        assert v.normal_total_count == 4
        assert v.normal_passed is True
        assert dev.passed is True
        # to_dict 透出
        d = v.to_dict()
        assert d["normal_error_count"] == 3 and d["normal_passed"] is True

    def test_parity_native_length_mismatch(self):
        """parity 盲区（F5 review 整改）：native_refs 的**输出数量**与 golden 不匹配时，
        devkit compare_outputs 与 cann-bench compare_tensors 都返回显式失败 verdict
        （不 IndexError、不静默忽略）——对齐 compare.py 的「同精度输出数量不匹配」守卫。
        注意：guard 看的是输出条数（tensor 个数），不是 numel——用多输出 list 构造。"""
        thr = {"float32": 2 ** -13}
        outs = [torch.tensor([1.0], dtype=torch.float32),
                torch.tensor([2.0], dtype=torch.float32)]
        golds = [torch.tensor([1.0], dtype=torch.float32),
                 torch.tensor([2.0], dtype=torch.float32)]
        # native 只有 1 条输出（< golden 2 条）——单 tensor 归一化为 1 条
        native_short = torch.tensor([1.0], dtype=torch.float32)
        dev = compare_outputs(outs, golds, merged_thresholds=thr, native_refs=native_short)
        cb = self._cannbench_compare_with_native(outs, golds, thr, native_short)
        assert dev.passed is False and cb.passed is False, (
            f"native 少 1 条输出：devkit={dev.passed} cann-bench={cb.passed} 都应显式失败（F5）")
        assert "同精度输出数量不匹配" in dev.error_msg, (
            f"devkit 应给明确 error_msg，实得: {dev.error_msg!r}")
        assert "同精度输出数量不匹配" in (cb.error_msg or ""), (
            f"cann-bench 应给明确 error_msg，实得: {cb.error_msg!r}")
        # native 有 3 条输出（> golden 2 条）——cann-bench 同守卫，devkit 同返回
        native_long = [torch.tensor([1.0], dtype=torch.float32),
                       torch.tensor([2.0], dtype=torch.float32),
                       torch.tensor([3.0], dtype=torch.float32)]
        dev2 = compare_outputs(outs, golds, merged_thresholds=thr, native_refs=native_long)
        cb2 = self._cannbench_compare_with_native(outs, golds, thr, native_long)
        assert dev2.passed is False and cb2.passed is False, (
            f"native 多 1 条输出：devkit={dev2.passed} cann-bench={cb2.passed} 都应显式失败（F5）")

    def test_parity_multi_output(self):
        outs = [torch.tensor([1, 2], dtype=torch.int8), torch.tensor([1.0, 2.0], dtype=torch.float32)]
        golds = [torch.tensor([1, 2], dtype=torch.int8), torch.tensor([1.0, 2.0], dtype=torch.float32)]
        self._assert_parity(outs, golds, {"int8": 1.0, "float32": 2 ** -13})
        # 第二个输出引入偏差
        outs2 = [torch.tensor([1, 2], dtype=torch.int8), torch.tensor([1.0, 2.1], dtype=torch.float32)]
        self._assert_parity(outs2, golds, {"int8": 1.0, "float32": 2 ** -13})
