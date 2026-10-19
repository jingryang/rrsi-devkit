"""L7 Infrastructure — Atomic filesystem operations."""

from __future__ import annotations

import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path


class FileSystem:

    @staticmethod
    def atomic_write(path: Path, content: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)

    @staticmethod
    def ensure_dir(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def sync_dir(src: Path, dst: Path) -> None:
        if not src.is_dir():
            raise NotADirectoryError(str(src))
        shutil.copytree(src, dst, dirs_exist_ok=True)

    @staticmethod
    @contextmanager
    def temp_dir(prefix: str = "tmp"):
        path = Path(tempfile.mkdtemp(prefix=prefix))
        try:
            yield path
        finally:
            shutil.rmtree(path, ignore_errors=True)
