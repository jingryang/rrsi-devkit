"""L6 Adapters — CANN Toolchain: detect CANN compiler availability.

This adapter never invokes the CANN compiler directly; it is a **presence
probe only** that answers "is the CANN
toolchain sourced and on PATH?" for the dispatcher preflight and the stage
gates, and emits an actionable diagnostic when it is not. There is no
``compile()`` here by design — the legacy in-memory compile path (the
``[ccec, "--chip", ...]`` side-path with its wrong ``--chip`` flag) was
removed as a superseded path (§2.5 single path); see
docs/plan/chip-version-generation/02-analysis.md.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from ascendc_devkit.infra.logger import Logger


class CANNToolchain:
    """CANN compiler toolchain presence probe.

    Detection:
      - Checks ASCEND_TOOLKIT_HOME environment variable.
      - Checks for a CANN compiler binary on PATH (ccec / bishengir-compile /
        asc_opc) — these are what ``set_env.sh`` puts on PATH.
      - ``is_available`` is False when none are found.

    ``ccec`` appears here only as a *sentinel* for "CANN is sourced" — the
    binary is detected on PATH (``shutil.which``), never invoked by this
    class. S5's authoritative build remains the target repo ``build.sh``.
    """

    # Sentinel binaries that prove CANN's compiler is initialised on PATH.
    # These are presence markers only (shutil.which), not compilation targets.
    _COMPILER_SENTINELS = ("ccec", "bishengir-compile", "asc_opc")

    def __init__(self):
        self._cann_available = self._detect_cann()

    @classmethod
    def _find_compiler(cls) -> str | None:
        """Return the path of the first CANN compiler sentinel on PATH."""
        for name in cls._COMPILER_SENTINELS:
            path = shutil.which(name)
            if path:
                return path
        return None

    def _detect_cann(self) -> bool:
        """Detect CANN toolchain availability."""
        ascend_home = os.environ.get("ASCEND_TOOLKIT_HOME")
        compiler = self._find_compiler()

        if ascend_home:
            Logger.info(f"ASCEND_TOOLKIT_HOME: {ascend_home}")
        else:
            Logger.warn("ASCEND_TOOLKIT_HOME environment variable is not set")
        if compiler:
            Logger.info(f"CANN compiler found: {compiler}")
            return True

        # No compiler on PATH — emit a precise, actionable diagnostic rather
        # than a generic "not detected". diagnostic_hint() distinguishes
        # "CANN installed but set_env.sh not sourced" from "CANN not installed".
        Logger.warn(self.diagnostic_hint())
        return False

    @staticmethod
    def _set_env_path(ascend_home: str) -> str | None:
        """Best-effort derivation of set_env.sh path from ASCEND_TOOLKIT_HOME.

        Two common layouts:
          - .../cann-<ver>/ascend-toolkit/latest  → set_env.sh lives at the
            cann-<ver> root (two levels up from ASCEND_TOOLKIT_HOME).
          - .../cann-<ver>                          → set_env.sh is in the same
            directory.
        Returns the first candidate whose set_env.sh exists, else the most
        likely path (so the hint is still actionable even if we can't stat it).
        """
        home = Path(ascend_home)
        candidates = [
            home / "set_env.sh",
            home.parent / "set_env.sh",
            home.parent.parent / "set_env.sh",
        ]
        for c in candidates:
            try:
                if c.is_file():
                    return str(c)
            except OSError:
                continue
        # Fall back to the cann-root candidate when nothing stats cleanly.
        if "ascend-toolkit" in home.parts:
            idx = home.parts.index("ascend-toolkit")
            return str(Path(*home.parts[:idx]) / "set_env.sh")
        return str(home / "set_env.sh")

    def diagnostic_hint(self) -> str:
        """Build an actionable message explaining why CANN is unavailable.

        Shared by _detect_cann (warn log), the dispatcher preflight, and the
        EnvironmentNotAvailable help_hint so the guidance never diverges.
        """
        compiler = self._find_compiler()
        if compiler:
            return f"CANN toolchain available (compiler on PATH: {compiler})."
        sentinels = "/".join(self._COMPILER_SENTINELS)
        ascend_home = os.environ.get("ASCEND_TOOLKIT_HOME")
        if ascend_home:
            set_env = self._set_env_path(ascend_home)
            return (
                f"检测到 ASCEND_TOOLKIT_HOME ({ascend_home}) 但 CANN 编译器"
                f"（{sentinels}）不在 PATH，可能未初始化 CANN 环境，"
                f"请执行: source {set_env} 后重试"
                f"（如需跳过编译可加 --enable-stubbed 走桩模式）。"
            )
        return (
            f"未检测到 ASCEND_TOOLKIT_HOME 且 CANN 编译器（{sentinels}）不在 PATH，"
            "CANN 可能未安装。请确认安装路径并 source 对应的 set_env.sh，"
            "或先安装 CANN（如需跳过编译可加 --enable-stubbed 走桩模式）。"
        )

    @property
    def is_available(self) -> bool:
        return self._cann_available
