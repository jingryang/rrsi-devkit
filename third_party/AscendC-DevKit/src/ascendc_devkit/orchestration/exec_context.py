"""L3 Orchestration — ExecContext: per-execution context passed by call.

Replaces Runner's mutable instance fields so parallel branches don't clobber
each other's "current stage / deadline / cancel" state.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable


class CancelToken:
    """Thread-safe cancellation flag shared across parallel branches."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


@dataclass
class ExecContext:
    """Context for one node execution. Carried by call, never stored on Runner."""

    workspace_dir: Path
    current_node_path: str
    event_log: Any = None                       # infra.EventLog (thread-safe)
    stage_deadline: float | None = None
    workflow_deadline: float | None = None
    cancel_flag: CancelToken = field(default_factory=CancelToken)
    progress_callback: Callable | None = None

    def child(self, node_path: str,
              workspace_dir: Path | None = None,
              stage_deadline: float | None = None) -> "ExecContext":
        """Derive a child context. Shares cancel_flag and event_log."""
        return replace(
            self,
            current_node_path=node_path,
            workspace_dir=workspace_dir if workspace_dir is not None else self.workspace_dir,
            stage_deadline=stage_deadline,
        )
