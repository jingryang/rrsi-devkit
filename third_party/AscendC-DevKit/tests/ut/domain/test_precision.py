"""UT for ascendc_devkit.domain.precision — CompareRule（P79）。

CompareRule 是精度判定的策略数据（rule × backend 正交的 rule 侧）。
纯数据 frozen dataclass，无运行时依赖（不 import torch/NPU），故不加 pytest mark（§3.5）。
"""

import dataclasses

import pytest

from ascendc_devkit.domain.precision import CompareRule


class TestCompareRule:
    def test_construct_with_dtype_thresholds(self):
        rule = CompareRule(dtype_thresholds={"int8": 1.0, "float16": 2 ** -10})
        assert rule.dtype_thresholds == {"int8": 1.0, "float16": 2 ** -10}

    def test_frozen_immutable(self):
        # frozen dataclass：赋值报错（domain 不变式，§1.1 State 风格）
        rule = CompareRule(dtype_thresholds={"int8": 1.0})
        with pytest.raises(dataclasses.FrozenInstanceError):
            rule.dtype_thresholds = {"int8": 2.0}

    def test_rule_object_shape_reserves_l3_double_benchmark(self):
        # rule 用对象（非散参数）承载——双标杆/区间未来只加字段，
        # PrecisionComparer.aggregate(rule, ...) 签名不动（§2.7 形状预留不实现）。
        rule = CompareRule(dtype_thresholds={"int8": 1.0})
        # 现仅 1 字段；future-proof：dataclass 可平滑加字段
        assert "dtype_thresholds" in {f.name for f in dataclasses.fields(rule)}

    def test_dtype_thresholds_is_the_merged_proto_truth(self):
        # 模拟 debug_service 桥接产物：默认表 ⊕ proto 覆盖（proto 优先）
        from ascendc_devkit.domain.precision import merge_thresholds
        rule = CompareRule(
            dtype_thresholds=merge_thresholds({"int8": 1.0}))
        # DQ 真值：proto int8=1.0 覆盖默认 0
        assert rule.dtype_thresholds["int8"] == 1.0
        # 未覆盖 dtype 保留默认
        assert rule.dtype_thresholds["float16"] == 2 ** -10
