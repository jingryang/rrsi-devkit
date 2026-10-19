#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
SingleOperatorLaunch - PyCUDA-like API for AscendC operator compilation and execution.
"""

import ctypes
import logging
import os

_LOCAL_CSRC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csrc")


def _ensure_ttk_csrc_local():
    """Prefer the csrc/ vendored inside SingleOperatorLaunch for ttk cext loading.

    The pip-installed ttk wheel neither includes the csrc/ C extensions (so
    libttk_error_manager_cleaner.so etc. are absent) nor can build them on
    demand.  An editable install can additionally be shadowed by a leftover
    physical site-packages copy (editable finder is appended after PathFinder).
    Point ttk's cext loader at the vendored csrc so the error cleaner and other
    extensions resolve from SingleOperatorLaunch regardless of how ttk was
    installed.
    """
    if not os.path.isdir(_LOCAL_CSRC_ROOT):
        return
    try:
        from ttk.utilities import cext_loader
    except Exception:
        return
    if getattr(cext_loader, "_single_op_launch_local_csrc", False):
        return
    original_load_cext = cext_loader.load_cext

    def load_cext_local(so_name, src_subdir):
        so_path = os.path.join(_LOCAL_CSRC_ROOT, src_subdir, "build", so_name)
        if os.path.isfile(so_path):
            return ctypes.CDLL(so_path)
        src_dir = os.path.join(_LOCAL_CSRC_ROOT, src_subdir)
        if os.path.isdir(src_dir):
            logging.info("On-demand build: compiling %s from %s", so_name, src_dir)
            cext_loader._build_cext(src_dir, so_name)
            so_path = os.path.join(src_dir, "build", so_name)
            if os.path.isfile(so_path):
                return ctypes.CDLL(so_path)
        return original_load_cext(so_name, src_subdir)

    cext_loader.load_cext = load_cext_local
    cext_loader._single_op_launch_local_csrc = True


_ensure_ttk_csrc_local()

import numpy

from .device_info import DeviceInfo
from .diagnostics import Diagnostics
from .source_module import SourceModule
from .static_check import check_regbase_source, RegBaseChecker, StaticCheckReport
from .logging_config import setup_log_separation
from . import precision_check as precision_check


def pack_tiling_data(fields, values=None):
    """Pack structured tiling data into raw bytes.

    This helper creates a byte buffer that exactly matches the in-memory layout
    of a C/C++ struct, so ``CopyTilingData`` in the kernel can memcpy it into a
    local struct safely.

    Args:
        fields: A list of ``(name, numpy_dtype)`` tuples describing the struct
            fields in order. Supported dtypes: ``np.uint8/16/32/64``,
            ``np.int8/16/32/64``, ``np.float16/32/64``.
        values: A dict ``{name: value}`` or a list/tuple of values in field
            order. If ``None``, the caller must set values on the returned
            numpy array before calling ``.tobytes()``.

    Returns:
        ``bytes`` ready to be passed as ``tiling_data``.
    """
    dtype = numpy.dtype(fields)
    arr = numpy.zeros(1, dtype=dtype)

    if values is not None:
        if isinstance(values, (list, tuple)):
            for (name, _), val in zip(fields, values):
                arr[name] = val
        else:
            for name, val in values.items():
                arr[name] = val

    return arr.tobytes()


__all__ = [
    "DeviceInfo",
    "SourceModule",
    "setup_log_separation",
    "pack_tiling_data",
    "check_regbase_source",
    "RegBaseChecker",
    "StaticCheckReport",
]
