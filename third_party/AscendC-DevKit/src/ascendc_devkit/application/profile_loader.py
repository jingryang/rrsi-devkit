"""L2 Application — Profile loader entry for L1 CLI (KNOWN 清零 step-5).

薄包 delegation：L1 (verify_repo) 只能 import L2/L4，够不到 L3 orchestration；
本 L2 入口把 ``load_profile`` / ``list_profiles`` 暴露给 L1。实现单一来源在
L3 ``orchestration/profile_loader``（真正 delegation 到 L6 adapter），本模块
只转手（L2→L3 合法）。
"""

from __future__ import annotations

from ascendc_devkit.domain.repository import RepositoryProfile
from ascendc_devkit.orchestration.profile_loader import (
    load_profile as _load_profile,
    list_profiles as _list_profiles,
)


def load_profile(profile_name: str) -> RepositoryProfile:
    """Load a RepositoryProfile by name. Delegates to L3 orchestration loader."""
    return _load_profile(profile_name)


def list_profiles() -> list[str]:
    """List available profile names."""
    return _list_profiles()
