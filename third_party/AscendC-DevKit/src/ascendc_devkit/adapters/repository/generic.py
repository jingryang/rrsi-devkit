"""L6 Adapters — GenericRepositoryAdapter: YAML-configuration-driven.

Redesigned (2026-06-08): the operator root is the user-supplied absolute
``op_dir`` (no ``op_root_template`` synthesis); files are *discovered* by
recursive scan (no fixed ``file_patterns`` / ``role_dirs`` enumeration); the
build runs each enabled stage of the variant selected by the op_dir's relative
path (no single ``build.command_template``).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ascendc_devkit.domain.chip import to_soc_version
from ascendc_devkit.domain.operator import OperatorSpec, OperatorIdentity
from ascendc_devkit.domain.verification import BuildResult
from ascendc_devkit.domain.repository import RepositoryProfile
from ascendc_devkit.infra.logger import Logger
from .base import RepositoryAdapter


_SOURCE_SUFFIXES = (".cpp", ".h", ".hpp", ".py")


class GenericRepositoryAdapter(RepositoryAdapter):
    """Default adapter driven by YAML RepositoryProfile. Covers ~95% of repos."""

    def materialize_new_operator(
        self, op: OperatorSpec, sources: dict[str, str], dest_root: Path,
        op_dir: Path | None = None,
    ) -> list[Path]:
        """Write generated sources under the operator directory.

        ``op_dir`` is the absolute operator root (user-supplied, resolved from
        ``--op-dir``). New operators may not exist yet, so the directory is
        created. ``dest_root`` is kept for back-compat as a fallback base.
        """
        target = Path(op_dir) if op_dir is not None else Path(dest_root)
        target.mkdir(parents=True, exist_ok=True)

        written = []
        for filename, content in sources.items():
            dest = target / filename
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content)
            written.append(dest)

        Logger.action("materialize", f"Wrote {len(written)} files to {target}")
        return written

    def scan_existing_operator(
        self, repo_root: Path, op_name: str, op_dir: Path | None = None
    ) -> OperatorIdentity:
        """Discover an existing operator's source files by recursive scan.

        Files are keyed by their *repo-relative-to-op_dir* path (e.g.
        ``op_host/xxx_tiling.cpp``) so downstream consumers can infer layer/role
        from the path itself — no fixed file enumeration, no role mapping.
        """
        if op_dir is None:
            raise ValueError(
                "scan_existing_operator requires an absolute op_dir "
                "(resolved from --op-dir); none was provided."
            )
        op_dir = Path(op_dir)
        if not op_dir.is_dir():
            raise FileNotFoundError(
                f"Operator directory not found for '{op_name}' at {op_dir}"
            )

        spec = OperatorSpec(name=op_name)
        files: dict[str, Path] = {}
        for f in op_dir.rglob("*"):
            if f.is_file() and f.suffix in _SOURCE_SUFFIXES:
                rel = f.relative_to(op_dir)
                files[str(rel)] = f

        Logger.action("scan", f"Found {len(files)} files for '{op_name}' at {op_dir}")
        return OperatorIdentity(spec=spec, repo_root=repo_root, op_dir=op_dir, files=files)

    def write_dev_record(self, op_dir: Path, entry: dict) -> Path:
        """Append a dev_record entry for incremental development tracking.

        Writes to .lingxi/dev_record.md under op_dir, prepending new entries
        so the most recent change appears first.
        """
        record_dir = op_dir / ".lingxi"
        record_dir.mkdir(parents=True, exist_ok=True)
        record_path = record_dir / "dev_record.md"

        timestamp = entry.get("timestamp", "")
        change_summary = entry.get("change_summary", "N/A")
        target_files = entry.get("target_files", [])
        requirement_path = entry.get("requirement_path", "N/A")

        new_entry = (
            f"## {timestamp} — {change_summary}\n\n"
            f"**变更摘要：** {change_summary}\n"
            f"**变更文件：** {', '.join(target_files) if target_files else 'N/A'}\n"
            f"**Requirement：** {requirement_path}\n\n"
            f"---\n"
        )

        if record_path.exists():
            existing = record_path.read_text(encoding="utf-8")
            content = new_entry + "\n" + existing
        else:
            content = new_entry

        record_path.write_text(content, encoding="utf-8")
        Logger.action("dev_record", f"Updated dev_record at {record_path}")
        return record_path

    def build(
        self, repo_root: Path, op: OperatorIdentity, chip_version: str
    ) -> BuildResult:
        """Run each enabled stage of the variant selected by op_dir.

        The variant is chosen by ``select_variant`` against op_dir's path
        relative to repo_root (the ``match_prefix`` boundary). Each enabled
        stage runs its ``command_template`` in its own ``cwd`` (relative to the
        repo root). Stages run in declared order; the first failure stops the
        chain. ``full_op_name`` is the prefixed name (op_dir's last segment).
        """
        repo_root = Path(repo_root)
        rel_op_dir = self._rel_op_dir(repo_root, op.op_dir)
        variant = self.profile.select_variant(rel_op_dir)
        if variant is None:
            return BuildResult(
                passed=False, stdout="",
                stderr=(f"No build variant matches op_dir '{rel_op_dir}'. "
                        f"Legal match_prefix values: {self.profile.match_prefixes()}"),
            )

        full_op_name = Path(op.op_dir).name
        stages = variant.enabled_stages()
        if not stages:
            Logger.warn(f"Variant '{variant.name}' has no enabled stages, skipping build")
            return BuildResult(passed=True, stdout="", stderr="")

        chip = chip_version or (stages[0].default_chip if stages else "")
        combined_out: list[str] = []
        combined_err: list[str] = []
        for stage in stages:
            cmd = stage.command_template.format(
                full_op_name=full_op_name, chip_version=chip,
                soc_version=to_soc_version(chip),
            )
            cwd = (repo_root / stage.cwd).resolve()
            Logger.action("build", f"[{variant.name}/{stage.name}] {cmd} (cwd={cwd})")
            try:
                result = subprocess.run(
                    cmd, shell=True, cwd=str(cwd),
                    capture_output=True, text=True, timeout=300,
                )
            except subprocess.TimeoutExpired:
                combined_err.append(f"[{stage.name}] timed out after 300s")
                return BuildResult(passed=False, stdout="\n".join(combined_out),
                                   stderr="\n".join(combined_err))
            except Exception as e:
                combined_err.append(f"[{stage.name}] {e}")
                return BuildResult(passed=False, stdout="\n".join(combined_out),
                                   stderr="\n".join(combined_err))
            combined_out.append(f"[{stage.name}]\n{result.stdout}")
            if result.stderr:
                combined_err.append(f"[{stage.name}]\n{result.stderr}")
            if result.returncode != 0:
                return BuildResult(passed=False, stdout="\n".join(combined_out),
                                   stderr="\n".join(combined_err))

        return BuildResult(passed=True, stdout="\n".join(combined_out),
                           stderr="\n".join(combined_err))

    @staticmethod
    def _rel_op_dir(repo_root: Path, op_dir: Path) -> str:
        """op_dir relative to repo_root as a forward-slash string."""
        try:
            return Path(op_dir).resolve().relative_to(Path(repo_root).resolve()).as_posix()
        except ValueError:
            return Path(op_dir).name
