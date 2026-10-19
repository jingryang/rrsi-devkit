"""L7 Infrastructure — Append-only event log with thread safety."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Iterator


class EventLog:
    """Append-only, thread-safe event writer to events.jsonl.

    ``for_path`` is the single construction point for cross-writer use: it
    returns a PROCESS-WIDE shared instance per resolved path (all writers —
    runner, dispatcher, artifact_recovery — serialize on one lock and one
    fdatasync discipline). Direct construction is fine for private logs; any
    writer that can run concurrently with another writer on the SAME path must
    go through ``for_path`` (20260821 F3 加固：短生命周期实例依赖 O_APPEND
    单写原子性防撕行，是工程判断非构造性保证——共享实例把跨写者串行化
    变成显式不变式)。"""

    _shared: "dict[str, EventLog]" = {}
    _shared_lock = threading.Lock()

    def __init__(self, path: Path):
        self._path = path
        self._lock = threading.Lock()

    @classmethod
    def for_path(cls, path: Path) -> "EventLog":
        """Process-wide shared instance for ``path`` (see class docstring)."""
        key = str(Path(path).resolve())
        with cls._shared_lock:
            inst = cls._shared.get(key)
            if inst is None:
                inst = cls(path)
                cls._shared[key] = inst
            return inst

    def append(self, event: dict) -> None:
        with self._lock:
            with open(self._path, "a") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
                f.flush()
                os.fdatasync(f.fileno())

    @staticmethod
    def read(path: Path) -> list[dict]:
        if not path.exists():
            return []
        events = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    events.append(json.loads(line))
        return events

    @staticmethod
    def replay(path: Path) -> Iterator[dict]:
        if not path.exists():
            return
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)
