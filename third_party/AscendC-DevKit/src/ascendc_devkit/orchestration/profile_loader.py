"""L3 Orchestration — Profile loader: delegates to L6 RepositoryAdapter."""

from __future__ import annotations

from ascendc_devkit.domain.repository import RepositoryProfile
from ascendc_devkit.adapters.repository.profile_loader import ProfileLoader as L6ProfileLoader


def load_profile(profile_name: str) -> RepositoryProfile:
    """Load a RepositoryProfile by name. Delegates to L6 ProfileLoader."""
    return L6ProfileLoader.load(profile_name)


def list_profiles() -> list[str]:
    """List available profile names."""
    return L6ProfileLoader.list_profiles()
