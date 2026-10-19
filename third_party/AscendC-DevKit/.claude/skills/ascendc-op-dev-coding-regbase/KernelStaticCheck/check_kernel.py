#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Standalone CLI entry point for KernelStaticCheck.

Run directly without ``python3 -m`` (``$SKILL_ROOT`` = ascendc-op-dev-coding-regbase
skill directory):

    python3 "$SKILL_ROOT/KernelStaticCheck/check_kernel.py" /path/to/op_kernel

Or make it executable:

    chmod +x "$SKILL_ROOT/KernelStaticCheck/check_kernel.py"
    "$SKILL_ROOT/KernelStaticCheck/check_kernel.py" /path/to/op_kernel

This script just forwards to ``KernelStaticCheck.cli.main``. For available
options, run with ``--help``.
"""

import sys
from pathlib import Path

# When this file is executed directly (``python3 check_kernel.py``), Python
# puts the directory containing this script on sys.path, not the workspace root.
# Add the workspace root so ``import KernelStaticCheck`` resolves correctly.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from KernelStaticCheck.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
