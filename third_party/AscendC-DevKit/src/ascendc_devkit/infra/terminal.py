"""L7 Infrastructure — Terminal capability detection."""

import os
import shutil
import sys


class Terminal:

    @staticmethod
    def is_tty() -> bool:
        return sys.stderr.isatty()

    @staticmethod
    def stdin_is_tty() -> bool:
        """Whether stdin can supply interactive input.

        Distinct from is_tty() (which checks stderr for rendering). input()
        reads stdin, so interactive prompts must gate on THIS — stderr may be
        redirected while stdin is still a live terminal, or vice versa.
        """
        try:
            return sys.stdin is not None and sys.stdin.isatty()
        except (ValueError, AttributeError):
            # stdin closed/detached (e.g. pytest capture, daemonized run)
            return False

    @staticmethod
    def width() -> int:
        return shutil.get_terminal_size().columns

    @staticmethod
    def supports_color() -> bool:
        if not Terminal.is_tty():
            return False
        term = os.environ.get("TERM", "")
        if term == "dumb":
            return False
        return True

    @staticmethod
    def supports_unicode() -> bool:
        encoding = sys.stderr.encoding or "ascii"
        return "utf" in encoding.lower()
