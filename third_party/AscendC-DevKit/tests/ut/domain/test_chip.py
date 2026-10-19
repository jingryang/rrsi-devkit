"""UT for domain.chip — canonical chip identity + compile translation.

守护 chip_version 代际化的核心不变式(Plan P29):
  - canonical 身份 = {A2, A3, A5},单一来源。
  - ``to_soc_version()`` 是唯一编译翻译点;非 canonical 输入必须 raise(§3.7),
    不静默回落——避免错误 chip_version 推迟到 CANN 编译期才暴露。
  - 穷尽性:每一代 ``CHIP_GENERATIONS`` 都必须有 soc_version 映射(新增代际时
    强制同步 ``_SOC_VERSION``,§1.2 可扩展尺子)。

detect / compatibility / display 的覆盖见
``tests/ut/adapters/test_adapters.py``(TestChipDetection / TestChipDisplay /
TestChipCompatibility);本文件只守护翻译层契约。
"""

from __future__ import annotations

import pytest

from ascendc_devkit.domain.chip import (
    A2, A3, A5,
    CHIP_GENERATIONS,
    MEMBASE, REGBASE,
    chip_programming_model,
    is_known_generation,
    runtime_supports_design,
    to_soc_version,
)


class TestToSocVersion:
    """The single compile-translation point (cann.py --chip, build.sh --soc)."""

    def test_a2_translates_to_910b(self):
        assert to_soc_version(A2) == "ascend910b"

    def test_a3_translates_to_910_93(self):
        # A3 = 910C 系列,soc_version = ascend910_93。证据:ops-nn build.sh
        # SUPPORT_COMPUTE_UNIT_SHORT 含 ascend910_93、help 注释 "A3(--soc=ascend910_93)"、
        # platform_config 对应 Ascend910_93xx.ini(无 Ascend910C.ini)。
        assert to_soc_version(A3) == "ascend910_93"

    def test_a5_translates_to_950(self):
        assert to_soc_version(A5) == "ascend950"

    def test_unknown_generation_raises(self):
        """§3.7: 非 canonical 输入必须 honest error,不静默回落。"""
        with pytest.raises(ValueError, match="no soc_version translation"):
            to_soc_version("A9")

    def test_legacy_soc_version_string_is_not_accepted(self):
        """Regression: 历史 soc_version 字面量(如 'ascend910b')本身不是
        canonical 输入——传入必须 raise,防止双词表悄悄回潮(§2.5 单一通路)。"""
        with pytest.raises(ValueError):
            to_soc_version("ascend910b")

    def test_every_generation_has_translation(self):
        """穷尽性(§1.2 可扩展): 每一代 CHIP_GENERATIONS 都必须有 soc_version,
        且产出合法。新增代际时若漏配 _SOC_VERSION,此 UT 立即失败。"""
        for gen in CHIP_GENERATIONS:
            sv = to_soc_version(gen)
            assert isinstance(sv, str) and sv.startswith("ascend"), (
                f"generation {gen} maps to invalid soc_version {sv!r}")


class TestIsKnownGeneration:
    def test_known_generations(self):
        for gen in (A2, A3, A5):
            assert is_known_generation(gen)

    def test_unknown_rejected(self):
        assert not is_known_generation("A9")
        # legacy literal, not canonical — must not pass as a generation
        assert not is_known_generation("ascend910b")
        assert not is_known_generation("")


class TestChipProgrammingModel:
    """programming_model 归属是芯片代际的固有属性（P65 收敛进 domain 单一源）。
    A2/A3 = Membase（传统 AscendC SIMD Vector），A5 = Regbase（VF 入口 + RegTensor）。
    未知/空 → Membase（保守回退，沿用 codegen._programming_model_for 旧语义）。"""

    def test_a2_a3_are_membase(self):
        # A2 与 A3 同属 Membase 代（general_design_common_knowledge.md「A2 行为与 A3 一致」）
        assert chip_programming_model(A2) == MEMBASE
        assert chip_programming_model(A3) == MEMBASE

    def test_a5_is_regbase(self):
        assert chip_programming_model(A5) == REGBASE

    def test_unknown_falls_back_to_membase(self):
        # 保守回退：Membase 是适用面最广的传统路径（与 codegen 旧 _programming_model_for 一致）
        assert chip_programming_model("A9") == MEMBASE
        assert chip_programming_model("") == MEMBASE

    def test_returns_pure_model_not_skill_literal(self):
        # domain 返回纯模型名；"{chip} {model}" skill 契约字面量由 codegen 拼装，
        # 不进 domain（分层：domain 不知 skill 契约）
        for gen in CHIP_GENERATIONS:
            model = chip_programming_model(gen)
            assert model in (MEMBASE, REGBASE)
            assert gen not in model


class TestRuntimeSupportsDesign:
    """跨代兼容矩阵（P65）：runtime 真机是否支持 design 的编程模型。
    Membase（A2/A3 design）→ 任意 A2/A3/A5 runtime 可（A5 向后兼容 Membase）。
    Regbase（A5 design）→ 仅 A5 runtime 可。
    方向性（易错）：design 低代际 → runtime 高代际 = 兼容；反向（A5→A2/A3）= 不兼容。"""

    def test_same_generation_compatible(self):
        assert runtime_supports_design(A2, A2) is True
        assert runtime_supports_design(A3, A3) is True
        assert runtime_supports_design(A5, A5) is True

    def test_membase_design_forward_compatible_with_a5(self):
        # 用户核心诉求：design=A2/A3 + runtime=A5（在 A5 真机验证 Membase codegen）
        assert runtime_supports_design(A2, A5) is True
        assert runtime_supports_design(A3, A5) is True

    def test_membase_design_portable_across_a2_a3(self):
        # A2↔A3 同 Membase，源码跨小代通用（依赖 code-review 维3 禁硬编码硬件参数）
        assert runtime_supports_design(A2, A3) is True
        assert runtime_supports_design(A3, A2) is True

    def test_regbase_design_blocked_on_membase_only_runtime(self):
        # 唯一硬阻塞：A5(Regbase) design + A2/A3 runtime —— Regbase 跑不了
        assert runtime_supports_design(A5, A2) is False
        assert runtime_supports_design(A5, A3) is False

    def test_unknown_runtime_not_supported(self):
        # runtime 非已知代际 → False（交调用方走"无法校验"分支，§3.7 honest error）
        from ascendc_devkit.domain.chip import UNKNOWN
        assert runtime_supports_design(A5, UNKNOWN) is False
        assert runtime_supports_design(A2, "") is False

    def test_unknown_design_falls_back_to_membase_compatible(self):
        # 未知 design 代际 → chip_programming_model 回退 Membase → 与已知 runtime
        # 的兼容性按 Membase 判（A5/A2/A3 runtime 均兼容 Membase，故均 True）。
        # 锁定此语义：design 的合法性校验在 upstream（CLI/profile 加载期，§1.3），
        # gate 假设 design 已合法；若未知 design 漏到 gate，走 Membase 回退不当硬
        # 阻断（Membase 是适用面最广的传统路径）。若将来 chip_programming_model
        # 的未知回退策略改变（如改 raise），此用例红以提醒兼容矩阵语义变化。
        assert runtime_supports_design("A9", A5) is True
        assert runtime_supports_design("A9", A2) is True
