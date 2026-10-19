"""UT: domain/op_name 注册名↔落盘名 case 派生 + runtime 反推兼容。

背景与判据见模块 docstring。核心不变式两条(从 ``docs/plan/adaptive-opname-snake-mismatch/``
实测日志固化):

1. **正向派生闭合**:落盘名经 ``snake_to_pascal`` 得到的注册名,runtime 反推必命中
   落盘名——``registration_matches_disk(snake_to_pascal(disk), disk) is True`` 对含
   ``_3d``/``_2d`` 数字段、无数字段、多下划线全部成立。
2. **proto 抄写必拦**:把 proto/requirement 的 Pascal(数字段大写)当注册名,对边界
   形态含数字段下划线的落盘名不命中——如注册 ``AdaptiveAvgPool3D``(proto 大写 D)、
   落盘 ``adaptive_avg_pool_3d`` → 拦;同注册名对无边界落盘 ``adaptive_avg_pool3d``
   仍命中(runtime 宽松候选),不算误拦。
"""

from __future__ import annotations

import pytest

from ascendc_devkit.domain.op_name import (
    registration_matches_disk,
    runtime_camelsnake,
    runtime_config_candidates,
    runtime_snake_lenient,
    snake_to_pascal,
)


class TestSnakeToPascal:
    @pytest.mark.parametrize("snake,expected", [
        ("add", "Add"),
        ("sqrt", "Sqrt"),
        ("swi_glu", "SwiGlu"),
        ("adaptive_avg_pool_3d", "AdaptiveAvgPool3d"),   # 数字段 3d capitalize 仍小写 d
        ("conv_2d", "Conv2d"),
        ("adaptive_avg_pool3d", "AdaptiveAvgPool3d"),
    ])
    def test_snake_to_pascal(self, snake, expected):
        assert snake_to_pascal(snake) == expected


class TestRuntimeReverse:
    def test_camelsnake_aggressive(self):
        """激进候选:AdaptiveAvgPool3D → adaptive_avg_pool_3_d(实测日志第一候选)。"""
        assert runtime_camelsnake("AdaptiveAvgPool3D") == "adaptive_avg_pool_3_d"

    def test_camelsnake_lenient(self):
        """宽松候选:AdaptiveAvgPool3D → adaptive_avg_pool3d(实测日志第二候选)。"""
        assert runtime_snake_lenient("AdaptiveAvgPool3D") == "adaptive_avg_pool3d"

    def test_candidates_both_families(self):
        """候选集同时含激进与宽松两族(与 runtime 依序尝试一致)。"""
        c = runtime_config_candidates("AdaptiveAvgPool3D")
        assert c == frozenset({"adaptive_avg_pool_3_d", "adaptive_avg_pool3d"})

    def test_candidates_simple_name(self):
        """无数字段名两候选合一,不引入假分隔。"""
        c = runtime_config_candidates("Add")
        assert "add" in c
        assert len(c) == 1


class TestRegistrationMatchesDisk:
    @pytest.mark.parametrize("disk", [
        "adaptive_avg_pool_3d",   # 数字段带下划线
        "add",
        "sqrt",
        "conv_2d",
        "adaptive_avg_pool3d",    # 无 pool/3d 边界
        "softmax",
        "swi_glu",
        "apply_adam_w",
        "rms_norm",
    ])
    def test_derived_registration_always_hits(self, disk):
        """正向派生闭合:snake_to_pascal(落盘名) 作注册名,runtime 反推必命中落盘名。"""
        reg = snake_to_pascal(disk)
        assert registration_matches_disk(reg, disk), (
            f"派生注册名 {reg!r} 应命中落盘名 {disk!r}")

    def test_proto_uppercase_digit_blocked(self):
        """proto 抄写(数字段大写)对含数字段边界的落盘名必拦。"""
        assert not registration_matches_disk("AdaptiveAvgPool3D", "adaptive_avg_pool_3d")
        assert not registration_matches_disk("Conv2D", "conv_2d")

    def test_proto_copy_but_no_boundary_still_hits(self):
        """同 proto 抄写对无边界落盘名仍命中(runtime 宽松候选)——不算误拦。"""
        assert registration_matches_disk("AdaptiveAvgPool3D", "adaptive_avg_pool3d")
