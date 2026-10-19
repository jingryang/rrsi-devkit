"""L6 Adapters — RepositoryAdapter ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
    from ascendc_devkit.domain.verification import BuildResult
    from ascendc_devkit.domain.repository import RepositoryProfile


class RepositoryAdapter(ABC):
    """Protocol for all repository adapters. GenericRepositoryAdapter is the default."""

    profile: RepositoryProfile

    def __init__(self, profile: RepositoryProfile):
        self.profile = profile

    @abstractmethod
    def materialize_new_operator(
        self, op: OperatorSpec, sources: dict[str, str], dest_root: Path,
        op_dir: Path | None = None,
    ) -> list[Path]:
        """Write agent-generated code from workspace to target repo."""

    @abstractmethod
    def scan_existing_operator(
        self, repo_root: Path, op_name: str, op_dir: Path | None = None
    ) -> OperatorIdentity:
        """Find existing operator in target repo. Returns its file layout."""

    @abstractmethod
    def build(
        self, repo_root: Path, op: OperatorIdentity, chip_version: str
    ) -> BuildResult:
        """Compile operator in target repo."""

    @abstractmethod
    def write_dev_record(self, op_dir: Path, entry: dict) -> Path:
        """Write a dev_record entry for incremental mode. Returns path to record file."""
