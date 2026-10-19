#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""Make ``python3 -m KernelStaticCheck`` work."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
