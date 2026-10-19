"""L2 Domain — Chip generation identity (canonical) + compile translation.

``chip_version`` 的唯一 canonical 身份是代际码 ``A2``/``A3``/``A5``,贯穿
CLI/profile/state/日志/文档。本模块是这套命名的单一来源:

  - 代际常量 ``A2``/``A3``/``A5`` + ``CHIP_GENERATIONS``(加载期/CLI 校验)
  - ``to_soc_version()`` — canonical → CANN/build.sh soc_version(**唯一编译翻译点**)
  - ``chip_display_name()`` — 人类可读名(日志/报告)

设计(P29 chip-version 代际化):
  - canonical 是唯一 authority;``soc_version`` 是 canonical 的纯函数派生,**仅在物理
    出口**(profile ``command_template`` 渲染 → 算子仓 ``build.sh --soc``、runner
    ``CHIP_VERSION`` env 注入)处计算,不作为 state 冗余字段(避免双字段漂移,对齐
    ``state.py`` 既有的 "chip_version truth / hw_params derived" 哲学)。
  - 真实算子编译走算子仓 ``build.sh``(经 CMake ``ASCEND_COMPUTE_UNIT`` 消费 soc_version);
    本项目**永不直接调 cce/ccec 编译器**(2026-07-05 用户定调),故无 in-process 裸编译
    出口。soc_version 三值对齐 ops-nn build.sh 支持列表。
  - 不留 alias/过渡层(§1.4/§2.5):detect/profile/CLI 一律用 A2/A3/A5。
  - 代际身份属 domain 层;``detect.py``(adapter)只负责"探测硬件 → 返回 canonical"。

覆盖范围:仅 910 家族三代(用户决策:其余芯片无开发场景)。
  - A2 = Ascend910B / Atlas A2
  - A3 = Ascend910C / 910_93xx / Atlas A3
  - A5 = David / 950 / Atlas 350
"""

from __future__ import annotations

# Canonical chip generation codes — the sole chip identity project-wide.
A2 = "A2"   # Ascend910B / Atlas A2
A3 = "A3"   # Ascend910C / 910_93xx / Atlas A3
A5 = "A5"   # David / 950 / Atlas 350

# Probe missing-hardware sentinel (step-34 D5): torch_npu unavailable / 0 devices
# / unknown device name → the probe cannot produce a truth, so it returns UNKNOWN
# instead of silently masquerading as A2 (the old detect.py _FALLBACK_CHIP lie).
# Deliberately NOT in CHIP_GENERATIONS, so is_known_generation(UNKNOWN) is False
# and to_soc_version(UNKNOWN) raises (honest) — callers guard with
# is_known_generation before translating.
UNKNOWN = "unknown"

CHIP_GENERATIONS: frozenset[str] = frozenset({A2, A3, A5})

# Canonical → CANN/build.sh soc_version. **唯一编译翻译点**,经 profile
# command_template 渲染喂给算子仓 build.sh --soc(真实活路径);runner 也用此译值
# 注入 CHIP_VERSION env。三值与 ops-nn build.sh 的 SUPPORT_COMPUTE_UNIT_SHORT 对齐:
# A2→ascend910b、A3→ascend910_93(910C 系列;build.sh 注释 "A3(--soc=ascend910_93)"、
# platform_config 对应 Ascend910_93xx.ini)、A5→ascend950。
_SOC_VERSION: dict[str, str] = {
    A2: "ascend910b",
    A3: "ascend910_93",
    A5: "ascend950",
}


def is_known_generation(chip: str) -> bool:
    """Whether *chip* is one of the supported A-series generations."""
    return chip in CHIP_GENERATIONS


def to_soc_version(chip: str) -> str:
    """Translate canonical generation → CANN/build.sh soc_version.

    单一翻译函数,仅由物理出口调用:profile ``command_template`` 渲染(→ 算子仓
    ``build.sh --soc``)与 runner ``CHIP_VERSION`` env。本项目无 in-process 直接编译
    通路(算子编译一律走算子仓 build.sh),故无 ``cann.py --chip`` 之类调用。
    未知代际抛 ``ValueError``(§3.7 honest error — 不静默回落)。
    """
    if chip not in _SOC_VERSION:
        raise ValueError(
            f"chip_version {chip!r} has no soc_version translation; "
            f"known generations: {sorted(CHIP_GENERATIONS)}")
    return _SOC_VERSION[chip]


def chip_display_name(chip: str) -> str:
    """Human-readable chip name for logs and reports."""
    display: dict[str, str] = {
        A2: "Ascend 910B (A2)",
        A3: "Ascend 910C (A3)",
        A5: "Ascend 950 (A5)",
    }
    return display.get(chip, chip)


# —— Programming model (architecture family) + cross-generation compatibility ——
#
# A chip's programming model is an intrinsic property of its generation — not a
# codegen-path choice. Membase (traditional AscendC SIMD Vector) for A2/A3;
# Regbase (VF entry + RegTensor) for A5. This is the SINGLE source (§1.9/§2.5)
# for three consumers that previously each held a private copy or a strict-
# equality substitute:
#   - codegen meta.json ``programming_model`` field (drives code style / path)
#   - the build-chip gate (``chip_mismatch_reason`` — can this box build/run?)
#   - the pre-design cross-generation confirmation gate
# Promotion to domain reverses the prior decision (codegen.py used to comment
# "programming_model is a codegen-path concept so its derivation lives here,
# not in chip.py"): the compatibility matrix needs the model mapping shared
# across adapter (detect) + orchestration (design_substages) + codegen layers,
# and leaving it codegen-private would duplicate it as a second source (§2.5).

MEMBASE = "Membase"   # A2/A3 — traditional AscendC Vector (SIMD)
REGBASE = "Regbase"   # A5    — VF entry + RegTensor (SIMT)

# Generation → its codegen programming model.
_CHIP_PROGRAMMING_MODEL: dict[str, str] = {
    A2: MEMBASE,
    A3: MEMBASE,
    A5: REGBASE,
}

# Generation → programming models its HARDWARE can actually execute. A5
# (newest) runs BOTH Membase (backward compatible) and Regbase; A2/A3 run
# Membase only. This asymmetry is what makes a low-generation Membase design
# forward-compatible with an A5 box, while a Regbase (A5) design cannot be
# built/run on A2/A3.
_RUNTIME_SUPPORTED_MODELS: dict[str, frozenset[str]] = {
    A2: frozenset({MEMBASE}),
    A3: frozenset({MEMBASE}),
    A5: frozenset({MEMBASE, REGBASE}),
}


def chip_programming_model(chip: str) -> str:
    """The codegen programming model for a generation (domain concept).

    Returns the pure model name (``MEMBASE``/``REGBASE``); the codegen stage
    wraps it into the skill-contract literal ``"{chip} {model}"`` (e.g.
    ``"A5 Regbase"``) — that wrapping stays in codegen, not here, so the
    domain layer stays unaware of skill-contract formatting (layering).
    Unknown/empty → ``MEMBASE`` (conservative fallback: Membase is the
    broadly-applicable traditional path).
    """
    return _CHIP_PROGRAMMING_MODEL.get((chip or "").strip(), MEMBASE)


def runtime_supports_design(design_chip: str, runtime_chip: str) -> bool:
    """Whether *runtime_chip* hardware can compile/run a design targeting
    *design_chip*.

    Compatibility is by programming model: the runtime hardware must support
    the design's model. Membase designs (A2/A3) run on any A2/A3/A5 box (A5
    is backward compatible with Membase — this is the forward-compatible mode
    that lets an A5 box validate A2/A3 codegen); Regbase designs (A5) run only
    on A5. Same generation is always compatible.

    A non-known runtime (UNKNOWN / empty / unmapped) returns False so callers
    route to their distinct "cannot verify" branch rather than silently
    passing (§3.7 honest error — distinguish "incompatible" from "unknown").
    """
    if not is_known_generation(runtime_chip):
        return False
    design_model = chip_programming_model(design_chip)
    return design_model in _RUNTIME_SUPPORTED_MODELS[runtime_chip]
