#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Diagnostic tools for SingleOperatorLaunch: OOB detection, overflow check,
assert callback, and data dump on failure.
"""

import ctypes
import logging
import math
import os
import sys
from typing import Optional

import numpy

from ttk.core_modules.npu.error_cleaner import clear_error_manager
from ttk.core_modules.runtime import RTSInterface, rts_info
from ttk.utilities import get_dtype_width
from ttk.utilities.file_utils import dump_to_file

logger = logging.getLogger(__name__)


class Diagnostics:
    """Diagnostic checks for kernel execution: OOB, overflow, assert, data dump.

    Two independent OOB checks:
    1. **Sentinel check** – guard bytes at end of HBM allocation.  If the kernel
       writes past the end into the guard region, the sentinel will be corrupted.
    2. **Data-change check** – compares post-kernel HBM content to pre-kernel
       snapshot.  If unchanged, the kernel wrote to a wrong address (silent OOB).
    """

    def __init__(self, device: RTSInterface, kernel_name: str,
                 kernel_dir: str, short_soc: str):
        self._device = device
        self._kernel_name = kernel_name
        self._kernel_dir = kernel_dir
        self._short_soc = short_soc
        self._task_fail_cb_invoked = None
        self._rts_task_fail_cb_set = False

    # ------------------------------------------------------------------
    # Kernel assert callback setup
    # ------------------------------------------------------------------

    def kernel_assert_setup(self):
        self._task_fail_cb_invoked = ctypes.c_uint64(0)
        if not self._rts_task_fail_cb_set:
            self._device.set_task_fail_callback()
            self._rts_task_fail_cb_set = True
        try:
            self._device.set_exception_extend_info(
                ctypes.c_void_p(ctypes.addressof(self._task_fail_cb_invoked)))
        except RuntimeError:
            pass

    # ------------------------------------------------------------------
    # Data dump on failure
    # ------------------------------------------------------------------

    def dump_on_fail(self, np_args: list, dump_dir: str = None):
        if dump_dir is None:
            dump_dir = os.path.join(self._kernel_dir, "oob_dump")
        os.makedirs(dump_dir, exist_ok=True)
        for idx, (arr, dev_ptr) in enumerate(np_args):
            if arr is None:
                continue
            dump_name = f"arg_{idx}_{self._kernel_name}"
            try:
                dump_to_file(arr, dump_dir, dump_name, file_format="bin")
                logger.info("Dumped arg %d to %s/%s.bin", idx, dump_dir, dump_name)
            except Exception as e:
                logger.debug("Failed to dump arg %d: %s", idx, e)

    # ------------------------------------------------------------------
    # Pre-kernel HBM snapshot for silent-OOB detection
    # ------------------------------------------------------------------

    def save_hbm_state(self, np_args: list, output_mask: set = None) -> list:
        """Read back pre-kernel HBM content for each output array.

        Only entries whose np_args index is in ``output_mask`` are saved.
        Returns a list (parallel to np_args) of uint8 arrays or None.
        """
        saved = []
        for i, (arr, dev_ptr) in enumerate(np_args):
            if dev_ptr is None or dev_ptr.value is None or dev_ptr.value == 0:
                saved.append(None)
                continue
            if output_mask is not None and i not in output_mask:
                saved.append(None)
                continue
            byte_size = int(math.ceil(arr.size * get_dtype_width(arr.dtype)))
            data = self._device.get_data_from_hbm(dev_ptr, byte_size)
            saved.append(numpy.frombuffer(data, dtype="uint8"))
        return saved

    # ------------------------------------------------------------------
    # Main OOB check (sentinel guard + data-change)
    # ------------------------------------------------------------------

    def check_oob(self, np_args: list, saved_hbm: list = None,
                  output_mask: set = None) -> bool:
        """Check OOB sentinel bytes and data integrity after kernel execution.

        Returns True if any OOB was detected, False otherwise.
        """
        OOB_SENTINEL = self._device.OOB_SENTINEL
        any_oob = False
        for idx, (arr, dev_ptr) in enumerate(np_args):
            if dev_ptr is None or dev_ptr.value is None or dev_ptr.value == 0:
                continue

            array_size = int(math.ceil(arr.size * get_dtype_width(arr.dtype)))
            aligned_size = self._device.get_npu_aligned_size(array_size, fill_oob_flag=True)
            gm_addr = dev_ptr.value
            oob_detected = False

            arg_info = f"Arg {idx} ({arr.dtype}{arr.shape}, {array_size} bytes)"
            buf_info = (f"  Buffer:  GM_ADDR {hex(gm_addr)}\n"
                        f"  Data:    [{hex(gm_addr)}, {hex(gm_addr + array_size)})  ({array_size} bytes)\n"
                        f"  Total:   [{hex(gm_addr)}, {hex(gm_addr + aligned_size)})  ({aligned_size} bytes, incl. guard)")

            # --- Check 1: Sentinel guard bytes ---
            oob_offset, oob_size = self._device.get_oob_check_offset_bytes(array_size)
            hbm_addr = ctypes.c_void_p(gm_addr + oob_offset)
            oob_bytes = self._device.get_data_from_hbm(hbm_addr, oob_size)
            oob_sentinels = numpy.frombuffer(oob_bytes, dtype="uint8")
            if not numpy.all(oob_sentinels == OOB_SENTINEL):
                any_oob = oob_detected = True
                n_corrupted = int(numpy.sum(oob_sentinels != OOB_SENTINEL))
                msg = (f"{arg_info} memory out of bound (sentinel corrupted) !! "
                       f"Guard region at [{hex(gm_addr + oob_offset)}, "
                       f"{hex(gm_addr + oob_offset + oob_size)}): "
                       f"{n_corrupted}/{oob_size} bytes != {OOB_SENTINEL} (expected).\n"
                       f"Corrupted sentinel bytes:\n{oob_sentinels}")
                logging.error(msg)
                sys.stderr.write(msg + "\n")

            # --- Check 2: Data-change check (silent OOB) ---
            if (saved_hbm is not None and saved_hbm[idx] is not None
                    and output_mask is not None and idx in output_mask):
                post_data = self._device.get_data_from_hbm(dev_ptr, array_size)
                post_bytes = numpy.frombuffer(post_data, dtype="uint8")
                if numpy.array_equal(post_bytes, saved_hbm[idx]):
                    any_oob = oob_detected = True
                    pre_hex = " ".join(f"{b:02x}" for b in saved_hbm[idx][:16])
                    post_hex = " ".join(f"{b:02x}" for b in post_bytes[:16])
                    msg = (f"{arg_info} memory out of bound (data unchanged) !! "
                           f"The kernel wrote NOTHING to the expected output buffer.\n"
                           f"{buf_info}\n"
                           f"  Pre-kernel (first 16B):  {pre_hex}\n"
                           f"  Post-kernel (first 16B): {post_hex}\n"
                           f"  => Identical. Kernel wrote to a different GM address.")
                    logging.error(msg)
                    sys.stderr.write(msg + "\n")

            if oob_detected:
                sys.stderr.write("=" * 68 + "\n")
                sys.stderr.flush()

        return any_oob

    # ------------------------------------------------------------------
    # Full diagnostic pipeline (convenience)
    # ------------------------------------------------------------------

    def run_pipeline(self, np_args: list, output_mask: set = None) -> dict:
        """Run the full diagnostic pipeline.

        Steps:
        1. Clear residual ErrorManager errors.
        2. Set up kernel assert callback.
        3. Save pre-kernel HBM snapshot (for outputs only).
        4. Returns the snapshot so the caller can pass it to
           :meth:`finish_pipeline` after kernel execution.

        Returns a dict with ``saved_hbm`` key.
        """
        clear_error_manager()
        self.kernel_assert_setup()
        saved_hbm = self.save_hbm_state(np_args, output_mask=output_mask)
        return {"saved_hbm": saved_hbm}

    def finish_pipeline(self, np_args: list, saved_hbm: list = None,
                        output_mask: set = None, kernel_status: str = "OK") -> bool:
        """Finish the diagnostic pipeline after kernel sync.

        Steps:
        1. Check OOB (sentinel + data-change).
        2. Dump data on any failure.

        Returns True if any OOB was detected.
        """
        oob_detected = self.check_oob(np_args, saved_hbm, output_mask=output_mask)
        if kernel_status != "OK" or oob_detected:
            self.dump_on_fail(np_args)
        return oob_detected
