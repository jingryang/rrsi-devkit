#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
SourceModule for AscendC kernels, inspired by pycuda.compiler.SourceModule.
"""

import ctypes
import datetime
import hashlib
import json
import logging
import math
import os
import sys
import pathlib
import platform as _platform
import shutil
from typing import Optional

import numpy

from ttk.core_modules.adump.adx_interface import AdxInterface
from ttk.core_modules.msprof import MsProfiler, MsProfOpDfx, TtkMsProfType
from ttk.core_modules.npu.op.compilation.common import CceManualCompile
from ttk.core_modules.runtime import RTSInterface, rts_info
from ttk.core_modules.runtime.rts_structures import LaunchKernelArgs
from ttk.utilities import extract_csv_cells, get_dtype_width
from ttk.utilities.platform import get_ascend_full_soc_version, get_npu_hw_info, PLATFORM_BEFORE_DAVID
from ttk.core_modules.npu.error_cleaner import clear_error_manager

from .diagnostics import Diagnostics
from .static_check import check_regbase_source

logger = logging.getLogger(__name__)


def _auto_detect_platform() -> str:
    """Auto-detect the current Ascend platform."""
    try:
        return get_ascend_full_soc_version()
    except Exception:
        pass
    try:
        from SingleOperatorLaunch.device_info import DeviceInfo
        dev = DeviceInfo()
        return dev.get_soc_version(0)
    except Exception:
        raise RuntimeError(
            "Failed to auto-detect Ascend platform. "
            "Please specify platform explicitly or ensure 'asys' is in PATH."
        ) from None


def _get_short_soc(platform: str) -> str:
    """Get short SoC version from full platform string."""
    try:
        hw_info = get_npu_hw_info(platform)
        return hw_info.get("short_soc_version", platform)
    except Exception:
        return platform


def _write_kernel_source(source: str, kernel_path: pathlib.Path):
    """Write kernel source to .cce file."""
    cce_path = kernel_path.with_suffix(".cce")
    with open(cce_path, "w", encoding="UTF-8") as f:
        f.write(source)
    return cce_path


def _generate_kernel_json(kernel_path: pathlib.Path, kernel_name: str,
                          block_dim: int, core_type: str,
                          task_ration: str = "1:0",
                          workspace_sizes=None,
                          ascendc_dump: bool = False,
                          short_soc: str = ""):
    """Generate kernel metadata JSON."""
    magic_map = {
        "AiCore": "RT_DEV_BINARY_MAGIC_ELF",
        "VectorCore": "RT_DEV_BINARY_MAGIC_ELF_AIVEC",
        "CubeCore": "RT_DEV_BINARY_MAGIC_ELF_AICUBE",
        "MIX": "RT_DEV_BINARY_MAGIC_ELF",
    }
    magic = magic_map.get(core_type, "RT_DEV_BINARY_MAGIC_ELF")
    json_data = {
        "kernelName": kernel_name,
        "blockDim": block_dim,
        "magic": magic,
        "coreType": core_type,
        "workspace": {"size": list(workspace_sizes)} if workspace_sizes else {},
        "parameters": [],
        "taskRation": task_ration,
    }
    if ascendc_dump:
        json_data["debugOptions"] = "printf"
        max_dump_core = 75 if short_soc in PLATFORM_BEFORE_DAVID else 108
        json_data["debugBufSize"] = max_dump_core * 1024 * 1024
    json_path = kernel_path.with_suffix(".json")
    with open(json_path, "w", encoding="UTF-8") as f:
        json.dump(json_data, f, indent=2)
    return json_path


def _get_caller_script_dir() -> Optional[str]:
    """Get the directory of the Python script that called into SourceModule."""
    import inspect
    current_file = os.path.abspath(__file__)
    for frame_info in inspect.stack():
        caller_file = os.path.abspath(frame_info.filename)
        if caller_file != current_file:
            return os.path.dirname(caller_file)
    return None


def _kernel_config_hash(source: str, ascendc_dump: bool,
                        core_type: str, platform: str) -> str:
    """Hash of the inputs that determine the compiled binary.

    Same *source* + *ascendc_dump* + *core_type* + *platform* must produce the
    same ``.o`` — core_type changes the ELF magic/ktype/mix flags and platform
    changes the target SoC — so this is the staleness key for cache reuse.
    """
    return hashlib.sha1(
        (f"dump={int(ascendc_dump)}\ncore={core_type}\nplatform={platform}\n{source}")
        .encode("UTF-8")
    ).hexdigest()


def _write_cache_marker(kernel_meta: pathlib.Path, kernel_name: str,
                        source: str, ascendc_dump: bool,
                        core_type: str, platform: str) -> None:
    """Record a SUCCESSFUL compile's input hash as the cache marker.

    Called only after ``_compile_kernel`` returns SUCC (review S5): a failed
    compile leaves no matching marker, so a partial/stale ``.o`` on disk can
    never be mistaken for a reusable build on the next run.
    """
    marker = kernel_meta / (kernel_name + ".src_hash")
    pending_hash = _kernel_config_hash(source, ascendc_dump, core_type, platform)
    try:
        marker.write_text(pending_hash, encoding="UTF-8")
    except OSError:
        logger.debug("Failed to write cache marker for %s", kernel_name)


def _fresh_kernel_artifacts(kernel_meta: pathlib.Path, kernel_name: str,
                            source: str, ascendc_dump: bool,
                            core_type: str, platform: str) -> bool:
    """Ensure no stale binary is loaded for *kernel_name*.

    A previously compiled ``.o`` is only reusable when (a) it exists, (b) the
    cache marker matches the pending compilation inputs (source + dump flag +
    core_type + platform), AND (c) the marker was written by a SUCCESSFUL compile
    (``_write_cache_marker`` is only called after SUCC, so a failed compile never
    leaves a matching marker). Otherwise prior artifacts are removed so the
    upcoming compile starts clean.

    Removes prior artifacts for *kernel_name* so a stale binary is never loaded
    after a source change or a failed compile. The compiled kernel is
    re-registered from ``{kernel_meta}/{kernel_name}.o``.

    Returns ``True`` if artifacts were kept and can be reused, ``False`` if the
    kernel must be recompiled (prior artifacts removed).
    """
    marker = kernel_meta / (kernel_name + ".src_hash")
    pending_hash = _kernel_config_hash(source, ascendc_dump, core_type, platform)
    obj = kernel_meta / (kernel_name + ".o")
    try:
        if obj.exists() and marker.exists() and marker.read_text("UTF-8") == pending_hash:
            logger.debug(
                "Reusing cached artifacts for '%s' (source+dump+core+platform unchanged)",
                kernel_name)
            return True
    except OSError:
        logger.debug("Failed to read cache marker for %s; falling back to fresh build",
                     kernel_name)
    for suffix in (".cce", ".i", ".o", ".json", "_meta.cce", "_meta.i"):
        artifact = kernel_meta / (kernel_name + suffix)
        try:
            if artifact.exists():
                artifact.unlink()
        except OSError:
            logger.debug("Failed to remove stale artifact %s", artifact)
    return False


def _get_ascend_include_paths() -> list:
    """Get AscendC include paths from ASCEND_HOME_PATH."""
    ascend_home = os.getenv("ASCEND_HOME_PATH", "/usr/local/Ascend/cann")
    machine = _platform.machine()
    if machine == "aarch64":
        arch = "aarch64-linux"
    elif machine == "x86_64":
        arch = "x86_64-linux"
    else:
        raise RuntimeError(f"Unsupported architecture: {machine}")
    asc_path = os.path.join(ascend_home, arch, "asc")
    if not os.path.isdir(asc_path):
        asc_path = os.path.join(ascend_home, "compiler", "asc")
    paths = [
        os.path.join(asc_path, "impl"),
        os.path.join(asc_path, "impl", "adv_api"),
        os.path.join(asc_path, "impl", "basic_api"),
        os.path.join(asc_path, "impl", "c_api"),
        os.path.join(asc_path, "impl", "basic_api", "reg_compute"),
        os.path.join(asc_path, "impl", "simt_api"),
        os.path.join(asc_path, "impl", "utils"),
        asc_path,
        os.path.join(asc_path, "include"),
        os.path.join(asc_path, "include", "adv_api"),
        os.path.join(asc_path, "include", "basic_api"),
        os.path.join(asc_path, "include", "aicpu_api"),
        os.path.join(asc_path, "include", "c_api"),
        os.path.join(asc_path, "include", "basic_api", "reg_compute"),
        os.path.join(asc_path, "include", "simt_api"),
        os.path.join(asc_path, "include", "utils"),
        os.path.join(asc_path, "..", "..", "include"),
        os.path.join(asc_path, "..", "..", "include", "ascendc"),
    ]
    return ["-I" + p for p in paths if os.path.isdir(p)]


_META_CCE_TEMPLATE = """
struct BaseTlv {{ unsigned short type; unsigned short len; }};
struct BinaryMetaVersion {{ struct BaseTlv head; unsigned int version; }};
struct BinaryMetaDebug {{ struct BaseTlv head; unsigned int debugBufSize; unsigned int debugOptions; }};
struct BinaryMetaDynamicParam {{ struct BaseTlv head; unsigned short reserve; unsigned short dynamicParamMode; }};
struct BinaryMetaOptionalParam {{ struct BaseTlv head; unsigned short optionalInputMode; unsigned short optionalOutputMode; }};
struct FunMetaKType {{ struct BaseTlv head; unsigned int ktype; }};
struct FunLevelKType {{ struct FunMetaKType ktypeMeta; }};

static const struct BinaryMetaVersion {kernel_name}_kernel_metainfo_version_section __attribute__((used, section(".ascend.meta"))) = {{{{0, sizeof(unsigned int)}}, 0x01}};
static const struct BinaryMetaDebug {kernel_name}_kernel_metainfo_debug_section __attribute__((used, section(".ascend.meta"))) = {{{{1, 8}}, {debug_buf_size}, 0x001}};
static const struct BinaryMetaDynamicParam {kernel_name}_kernel_metainfo_dynamicparam_section __attribute__((used, section(".ascend.meta"))) = {{{{2, 4}}, 0, 0}};
static const struct BinaryMetaOptionalParam {kernel_name}_kernel_metainfo_optionalparam_section __attribute__((used, section(".ascend.meta"))) = {{{{3, 4}}, 0, 0}};
static const struct FunLevelKType {kernel_name}_kernel_type_section __attribute__((used, section(".ascend.meta.{kernel_name}"))) = {{{{{{1, sizeof(unsigned int)}}, {ktype}}}}};
"""


def _compile_kernel(kernel_path: pathlib.Path, platform: str, core_type: str,
                    ascendc_dump: bool = True, short_soc: str = "", kernel_source: str = "",
                    extra_include_paths: Optional[list] = None) -> str:
    """Compile .cce to .o using ccec + ld.lld."""
    import re
    kernel_name = str(kernel_path)
    include_paths = _get_ascend_include_paths()
    if extra_include_paths:
        include_paths.extend(["-I" + p for p in extra_include_paths if os.path.isdir(p)])
    extra_options = include_paths + [
        "--cce-disable-kernel-global-attr-check",
        "-std=c++17",
    ]
    if ascendc_dump:
        extra_options.append("-DASCENDC_DUMP=1")
    else:
        extra_options.append("-DASCENDC_DUMP=0")

    compile_i = f"{kernel_name}.i"
    if ascendc_dump:
        # Inject InitDump at the beginning of user's __global__ kernel function.
        # This keeps the kernel as __global__ (avoiding __aicore__ inline GM-write issues)
        # while still enabling printf on David platforms.
        injected_source = re.sub(
            r'(extern\s+"C"\s+__global__\s+(?:__vector__|__aicore__)\s+void\s+\w+\([^)]*\)\s*\{)',
            r'''\1
    constexpr uint32_t ASCENDC_DUMP_SIZE = 123;
    AscendC::InitDump(false, workspace, ASCENDC_DUMP_SIZE);
''',
            kernel_source
        )
        user_cce = f"{kernel_name}.cce"
        with open(user_cce, "w", encoding="UTF-8") as f:
            f.write(injected_source)
        compile_cce = user_cce
    else:
        compile_cce = f"{kernel_name}.cce"

    result = CceManualCompile._compile_cce(
        compile_cce,
        compile_i,
        platform,
        core_type,
        extra_compile_options=extra_options,
    )
    if result != "SUCC":
        return result

    ld_inputs = [compile_i]
    if ascendc_dump:
        max_dump_core =  75 if short_soc in PLATFORM_BEFORE_DAVID else 108
        debug_buf_size = max_dump_core * 1024 * 1024
        ktype = 3 if core_type == "VectorCore" else 2
        meta_cce = f"{kernel_name}_meta.cce"
        meta_i = f"{kernel_name}_meta.i"
        with open(meta_cce, "w", encoding="UTF-8") as f:
            f.write(_META_CCE_TEMPLATE.format(
                kernel_name=pathlib.Path(kernel_name).name,
                debug_buf_size=debug_buf_size,
                ktype=ktype,
            ))
        result = CceManualCompile._compile_cce(
            meta_cce,
            meta_i,
            platform,
            core_type,
            extra_compile_options=extra_options,
        )
        if result != "SUCC":
            return result
        ld_inputs.append(meta_i)

    return CceManualCompile._ld(f"{kernel_name}.o", ld_inputs)


def _gen_workspace_arrays(workspace_sizes):
    """Generate workspace numpy arrays from sizes (in bytes)."""
    if not workspace_sizes:
        return []
    arrays = []
    for size in workspace_sizes:
        if size:
            arrays.append(numpy.zeros(int(size), dtype=numpy.uint8))
        else:
            arrays.append(None)
    return arrays


def _make_launch_args(*, func_or_binary_hdl, op_args, block_dim,
                      mix_kernel, tiling_data=None, simt_share_memory_size=None):
    """Build :class:`LaunchKernelArgs`, resolving the SIMT share-memory window.

    ``simt_share_memory_size`` (bytes) is the SIMT 共享内存窗口 / Dynamic
    Unified Buffer for this launch. ``None`` and ``0`` are equivalent: the RTS
    runtime default applies (实测 SingleOperatorLaunch 默认落 8KB 窗口). A
    positive value enlarges the window (上限受 UB−预留8KB−DCache≥32KB 约束).
    """
    if simt_share_memory_size is not None and simt_share_memory_size < 0:
        raise ValueError(
            f"simt_share_memory_size must be >= 0 (got {simt_share_memory_size})")
    return LaunchKernelArgs(
        func_or_binary_hdl=func_or_binary_hdl,
        op_args=op_args,
        block_dim=block_dim,
        mix_kernel=mix_kernel,
        tiling_data=tiling_data,
        simt_share_memory_size=0 if simt_share_memory_size is None else simt_share_memory_size,
    )


class _KernelFunction:
    """Callable wrapper for a compiled AscendC kernel function."""

    def __init__(self,
                 device: RTSInterface,
                 kernel_binary: ctypes.c_void_p,
                 kernel_func: ctypes.c_void_p,
                 kernel_name: str,
                 kernel_json: dict,
                 block_dim: int,
                 core_type: str,
                 kernel_dir: str,
                 ascendc_dump: bool = False,
                 short_soc: str = "",
                 workspace_arrays=None):
        self._device = device
        self._kernel_binary = kernel_binary
        self._kernel_func = kernel_func
        self._kernel_name = kernel_name
        self._kernel_json = kernel_json
        self._block_dim = block_dim
        self._core_type = core_type
        self._kernel_dir = kernel_dir
        self._is_fat_bin = False
        self._magic = self._parse_magic(kernel_json.get("magic", "RT_DEV_BINARY_MAGIC_ELF"))
        self._ascendc_dump = ascendc_dump
        self._short_soc = short_soc
        self._workspace_arrays = workspace_arrays
        self._diag = Diagnostics(device, kernel_name, kernel_dir, short_soc)

    def _printf_enabled(self) -> bool:
        if not self._ascendc_dump:
            return False
        debug_options = self._kernel_json.get("debugOptions", "")
        return "printf" in debug_options.lower().split(",")

    def _debug_buf_size(self) -> int:
        return int(self._kernel_json.get("debugBufSize", 0))

    def _print_dump_workspace(self, workspace_ptr: ctypes.c_void_p):
        if not self._printf_enabled() or workspace_ptr is None or workspace_ptr.value is None or workspace_ptr.value == 0:
            return
        try:
            debug_buf_size = self._debug_buf_size()
            if debug_buf_size <= 0:
                return
            c_buffer = self._device.get_data_from_hbm(workspace_ptr, debug_buf_size)
            AdxInterface.print_dump_info(ctypes.c_void_p(ctypes.addressof(c_buffer)),
                                         debug_buf_size,
                                         self._short_soc)
        except RuntimeError:
            return

    @staticmethod
    def _parse_magic(magic: str) -> int:
        if magic in rts_info.rt_binary_magic_dict:
            return rts_info.rt_binary_magic_dict[magic]
        raise RuntimeError(f"Unknown kernel magic: {magic}")

    def _copy_to_hbm(self, arr: numpy.ndarray, fill_oob_flag: bool = False):
        """Copy numpy array to device HBM."""
        if arr is None:
            return ctypes.c_void_p(None)
        return self._device.copy_nparray_to_hbm(arr, fill_oob_flag=fill_oob_flag)

    def _copy_from_hbm(self, hbm_ptr: ctypes.c_void_p, arr: numpy.ndarray):
        """Copy data from HBM back to numpy array."""
        if hbm_ptr is None or hbm_ptr.value is None or hbm_ptr.value == 0:
            return
        byte_size = int(math.ceil(arr.size * get_dtype_width(arr.dtype)))
        data = self._device.get_data_from_hbm(hbm_ptr, byte_size)
        arr_view = numpy.frombuffer(data, dtype=arr.dtype)
        arr.flat[:] = arr_view

    def __call__(self, *args, block_dim: Optional[int] = None,
                 tiling_data: Optional[bytes] = None,
                 output_indices: Optional[set] = None,
                 simt_share_memory_size: Optional[int] = None):
        """Launch the kernel with given arguments.

        Args:
            *args: numpy.ndarray for GM buffers, scalars for other params.
            block_dim: override block dimension for this launch.
            tiling_data: raw bytes passed as tiling data. When provided, the
                kernel's ``tiling`` parameter is filled automatically by the
                RTS runtime (host-side buffer) instead of being passed as a
                regular GM pointer argument.
            output_indices: Set of argument indices (counted from 0) that are
                output arrays. When provided, enables a data-change OOB check
                that compares pre- and post-kernel HBM content for these
                arrays. If the data is bitwise identical, the kernel likely
                wrote to the wrong address (silent OOB).
            simt_share_memory_size: SIMT 共享内存窗口 / Dynamic Unified Buffer
                in bytes. ``None``/``0`` → RTS runtime default (实测 8KB);
                positive enlarges the window (上限 ≈ UB−8KB−DCache). Pass a
                value ≥ the kernel's largest SIMT shared-buffer footprint when
                a ``__simt_vf__`` kernel accesses UB beyond the default window.
        """
        clear_error_manager()
        bd = block_dim if block_dim is not None else self._block_dim

        # Convert args to device addresses / values
        dev_args = []
        np_args = []  # track numpy arrays for sync-back
        np_arg_indices = []  # original arg index for each entry in np_args
        ws_ptrs = []  # track workspace pointers for printf dump
        workspace_ids = {id(ws) for ws in self._workspace_arrays if ws is not None}

        for arg_idx, arg in enumerate(args):
            if isinstance(arg, numpy.ndarray):
                # For outputs, fill OOB sentinel to catch out-of-bounds writes.
                dev_ptr = self._copy_to_hbm(arg, fill_oob_flag=True)
                dev_args.append(dev_ptr)
                np_args.append((arg, dev_ptr))
                np_arg_indices.append(arg_idx)
                if id(arg) in workspace_ids:
                    ws_ptrs.append(dev_ptr)
            elif isinstance(arg, (int, numpy.integer)):
                dev_args.append(int(arg))
            elif isinstance(arg, (float, numpy.floating)):
                # Pack float as uint64 bits
                dev_args.append(numpy.float32(arg).view(numpy.uint32).item())
            elif isinstance(arg, ctypes.c_void_p):
                dev_args.append(arg)
            else:
                raise TypeError(f"Unsupported kernel argument type: {type(arg)}")

        # Determine which np_args entries are outputs (for data-change OOB check)
        if output_indices is not None:
            np_output_set = {i for i, aidx in enumerate(np_arg_indices) if aidx in output_indices}
        else:
            np_output_set = set()

        # Launch kernel (with diagnostic pipeline)
        stream = self._device.create_stream()
        kernel_status = "OK"
        oob_detected = False
        try:
            # Pre-launch diagnostics
            pipe_ctx = self._diag.run_pipeline(np_args, output_mask=np_output_set)

            launch_args = _make_launch_args(
                func_or_binary_hdl=self._kernel_func,
                op_args=dev_args,
                block_dim=bd,
                mix_kernel=(self._core_type == "MIX"),
                tiling_data=tiling_data,
                simt_share_memory_size=simt_share_memory_size,
            )
            self._device.launch_kernel_with_flag(launch_args, stream)
            try:
                self._device.synchronize_with_stream(stream)
            except RuntimeError as e:
                kernel_status = RTSInterface.handle_stream_sync_exception(e.args[0])
                sys.stderr.write(f"[{kernel_status}] Kernel execution failed\n")
                sys.stderr.flush()

            # Print printf output from workspace (required on David platforms like Ascend950)
            for ws_ptr in ws_ptrs:
                self._print_dump_workspace(ws_ptr)
            # Post-launch diagnostics
            oob_detected = self._diag.finish_pipeline(
                np_args, saved_hbm=pipe_ctx["saved_hbm"],
                output_mask=np_output_set, kernel_status=kernel_status)
        finally:
            self._device.destroy_stream_force(stream)
            # Copy outputs back and free HBM
            for np_arr, dev_ptr in np_args:
                self._copy_from_hbm(dev_ptr, np_arr)
                if dev_ptr and dev_ptr.value:
                    self._device.free(dev_ptr)

    def profile(self, *args,
                block_dim: Optional[int] = None,
                repeat_times: int = 10,
                warmup_times: int = 3,
                result_path: Optional[str] = None,
                tiling_data: Optional[bytes] = None,
                output_indices: Optional[set] = None,
                simt_share_memory_size: Optional[int] = None):
        """Profile kernel execution using msprof.

        Args:
            *args: Same as ``__call__``.
            block_dim: Override block dimension.
            repeat_times: Number of profiled iterations.
            warmup_times: Number of warmup iterations (un-profiled).
            result_path: Directory to store msprof data.
                         Defaults to ``<kernel_dir>/msprof``.
            tiling_data: Same as ``__call__``.
            output_indices: Same as ``__call__``.
            simt_share_memory_size: Same as ``__call__``.

        Returns:
            dict with keys ``median_us``, ``all_times_us``, ``status``,
            ``result_path``.
        """
        bd = block_dim if block_dim is not None else self._block_dim

        if result_path is None:
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            result_path = os.path.join(os.getcwd(), "msprof", f"{self._kernel_name}_{ts}")

        # Determine output mask for profile runs
        np_arg_indices = [i for i, arg in enumerate(args) if isinstance(arg, numpy.ndarray)]
        if output_indices is not None:
            np_output_set = {i for i, aidx in enumerate(np_arg_indices) if aidx in output_indices}
        else:
            np_output_set = set()

        # Warmup runs (no profiling)
        for _ in range(warmup_times):
            self(*args, block_dim=bd, tiling_data=tiling_data,
                 output_indices=output_indices,
                 simt_share_memory_size=simt_share_memory_size)

        op_dfx = MsProfOpDfx(
            kernel_name=self._kernel_name,
            block_dim=bd,
            core_type=self._core_type,
            task_ration=None,
        )

        with MsProfiler(self._device.device_id, result_path,
                        ttk_prof_type=TtkMsProfType.OP,
                        start_step=0) as profiler:
            for _ in range(repeat_times):
                profiler.step()

                dev_args = []
                np_args = []
                np_arg_indices = []
                for a_idx, arg in enumerate(args):
                    if isinstance(arg, numpy.ndarray):
                        dev_ptr = self._copy_to_hbm(arg, fill_oob_flag=True)
                        dev_args.append(dev_ptr)
                        np_args.append((arg, dev_ptr))
                        np_arg_indices.append(a_idx)
                    elif isinstance(arg, (int, numpy.integer)):
                        dev_args.append(int(arg))
                    elif isinstance(arg, (float, numpy.floating)):
                        dev_args.append(
                            numpy.float32(arg).view(numpy.uint32).item()
                        )
                    elif isinstance(arg, ctypes.c_void_p):
                        dev_args.append(arg)
                    else:
                        raise TypeError(
                            f"Unsupported kernel argument type: {type(arg)}"
                        )

                stream = self._device.create_stream()
                try:
                    pipe_ctx = self._diag.run_pipeline(np_args, output_mask=np_output_set)
                    launch_args = _make_launch_args(
                        func_or_binary_hdl=self._kernel_func,
                        op_args=dev_args,
                        block_dim=bd,
                        mix_kernel=(self._core_type == "MIX"),
                        tiling_data=tiling_data,
                        simt_share_memory_size=simt_share_memory_size,
                    )
                    self._device.launch_kernel_with_flag(launch_args, stream)
                    self._device.synchronize_with_stream(stream)
                    self._diag.finish_pipeline(
                        np_args, saved_hbm=pipe_ctx["saved_hbm"],
                        output_mask=np_output_set)
                    profiler.report_op_dfx(op_dfx)
                finally:
                    self._device.destroy_stream_force(stream)
                    for _np_arr, dev_ptr in np_args:
                        if dev_ptr and dev_ptr.value:
                            self._device.free(dev_ptr)

        median_us = self._parse_msprof_result(result_path)
        return {
            "median_us": median_us,
            "repeat_times": repeat_times,
            "warmup_times": warmup_times,
            "status": "OK" if median_us != "UNKNOWN" else "UNKNOWN",
            "result_path": result_path,
        }

    @staticmethod
    def _parse_msprof_result(result_path: str):
        """Parse msprof CSV to extract median task duration in microseconds.

        Mirrors the logic in ``OnlineRtsProfiling._process_msprof_cycles``.
        """
        kernel_type = (
            "AI_CORE", "AIV_SQE", "AI_VECTOR_CORE",
            "MIX_AIC", "MIX_AIV",
            "KERNEL_AIVEC", "KERNEL_AICORE",
        )
        prof_path = pathlib.Path(result_path)
        if not prof_path.is_dir():
            return "UNKNOWN"

        csv_files = list(prof_path.glob("**/*.csv"))
        if not csv_files:
            return "UNKNOWN"

        op_prof = []
        for item in csv_files:
            if op_prof:
                break
            if item.name.startswith("op_summary_"):
                op_prof = extract_csv_cells(
                    item, ("Task Duration(us)",),
                    col_name_mapping={"Task Duration(us)": "duration"},
                    cmp=lambda row: row["Task Type"] in kernel_type,
                )
            elif item.name.startswith("task_time_"):
                op_prof = extract_csv_cells(
                    item, ("task_time(us)",),
                    col_name_mapping={"task_time(us)": "duration"},
                    cmp=lambda row: row["kernel_type"] in kernel_type,
                )

        if not op_prof:
            return "UNKNOWN"

        durations = [x["duration"] for x in op_prof]
        results = durations[1:] if len(durations) > 1 else durations
        return float(numpy.round(numpy.median(results), 3))

    def __repr__(self):
        return f"_KernelFunction({self._kernel_name}, block_dim={self._block_dim})"


class SourceModule:
    """Compile and launch AscendC kernels from source code.

    Example:
        mod = SourceModule('''
            #include "kernel_operator.h"
            extern "C" __global__ __vector__ void add_custom(
                __gm__ uint8_t* x, __gm__ uint8_t* y, __gm__ uint8_t* z,
                uint32_t totalLength) { ... }
        ''', kernel_name="add_custom", block_dim=8)

        add = mod.get_function()   # single entry, no name needed
        add(x, y, z, 1024)
    """

    def __init__(self,
                 source: str,
                 kernel_name: str,
                 block_dim: int = 1,
                 core_type: str = "VectorCore",
                 kernel_meta: Optional[str] = None,
                 device_id: int = 0,
                 task_ration: str = "1:0",
                 keep_source: bool = False,
                 ascendc_dump: bool = False,
                 workspace_sizes=None,
                 include_paths: Optional[list] = None,
                 auto_include_script_dir: bool = True):
        """
        Args:
            source: AscendC kernel source code (C++ with AscendC extensions).
            kernel_name: Name of the kernel function to compile.
            block_dim: Default block dimension for kernel launch.
            core_type: "AiCore", "VectorCore", "CubeCore", or "MIX".
            platform: Full SoC version (e.g. "Ascend910B3"). Auto-detected if None.
            kernel_meta: Directory to store compiled artifacts. If None, defaults
                to ``<caller_script_dir>/kernel_meta/<kernel_name>``. Cached
                artifacts are reused when the pending source+dump flag match the
                last successful build; otherwise they are removed and rebuilt.
            device_id: NPU device ID to use.
            task_ration: Mix core task ratio (e.g. "1:0").
            keep_source: Whether to keep source file after compilation.
            ascendc_dump: Whether to enable ASCENDC_DUMP. Set False to pass -DASCENDC_DUMP=0.
            workspace_sizes: Workspace sizes in bytes. Can be a single int or a list/tuple
                of ints. When provided, workspace arrays are auto-generated and can be
                accessed via ``workspace_arrays`` and passed to the kernel call.
            include_paths: Extra include directories to add to the ccec command line.
            auto_include_script_dir: If True, automatically add the directory of the
                Python script that created this SourceModule to the include paths.
        """
        self._kernel_name = kernel_name
        self._block_dim = block_dim
        self._core_type = core_type
        # Run lightweight RegBase static checks before any expensive steps.
        # This is mandatory; failures stop the compile/launch pipeline early.
        check_regbase_source(source, kernel_name)
        self._platform = _auto_detect_platform()
        self._short_soc = _get_short_soc(self._platform)
        self._device_id = device_id
        self._task_ration = task_ration
        self._keep_source = keep_source
        self._ascendc_dump = ascendc_dump

        # Normalize workspace sizes
        if workspace_sizes is not None:
            if isinstance(workspace_sizes, int):
                self._workspace_sizes = [workspace_sizes]
            else:
                self._workspace_sizes = list(workspace_sizes)
        else:
            self._workspace_sizes = None
        
        # Ensure workspace is large enough for debug buffer on David platforms
        if self._ascendc_dump and self._workspace_sizes:
            max_dump_core =  75 if self._short_soc in PLATFORM_BEFORE_DAVID else 108
            debug_buf_size = max_dump_core * 1024 * 1024
            if self._workspace_sizes[0] < debug_buf_size:
                self._workspace_sizes[0] = debug_buf_size
        self._rts_custom_path = ""
        self._workspace_arrays = _gen_workspace_arrays(self._workspace_sizes)

        # Setup kernel_meta directory
        if kernel_meta is not None:
            self._kernel_meta = pathlib.Path(kernel_meta)
        else:
            # Default to the directory of the script that created this
            # SourceModule (deterministic and colocated with the test), NOT the
            # process cwd: an agent-driven run may `cd` elsewhere and cwd-based
            # kernel_meta would land in an unexpected place that cleanup and
            # debugging cannot find.
            caller_dir = _get_caller_script_dir() or os.getcwd()
            self._kernel_meta = pathlib.Path(caller_dir) / "kernel_meta" / kernel_name
        self._kernel_meta.mkdir(parents=True, exist_ok=True)
        # Rebuild only when the source/dump changed from the last successful
        # compile, or when the binary is missing (never built / prior failure).
        # This avoids needlessly recompiling the same kernel on each SourceModule
        # construction and removes the whole-directory delete/reset dance.
        _reused = _fresh_kernel_artifacts(
            self._kernel_meta, kernel_name, source, ascendc_dump,
            core_type, self._platform)
        logger.info(
            "SourceModule kernel_meta dir: %s (%s)",
            self._kernel_meta,
            "reuse cached build" if _reused else "fresh build",
        )

        # Write source
        kernel_path = self._kernel_meta / kernel_name
        _write_kernel_source(source, kernel_path)

        # Generate JSON
        self._json_path = _generate_kernel_json(
            kernel_path, kernel_name, block_dim, core_type, task_ration,
            workspace_sizes=self._workspace_sizes,
            ascendc_dump=self._ascendc_dump,
            short_soc=self._short_soc,
        )

        # Build extra include paths
        extra_include_paths = []
        if auto_include_script_dir:
            script_dir = _get_caller_script_dir()
            if script_dir:
                extra_include_paths.append(script_dir)
        if include_paths:
            extra_include_paths.extend(include_paths)

        # Compile
        compile_result = _compile_kernel(
            kernel_path, self._platform, core_type,
            self._ascendc_dump, self._short_soc, source,
            extra_include_paths=extra_include_paths,
        )
        if compile_result != "SUCC":
            raise RuntimeError(
                f"Kernel compilation failed for '{kernel_name}': {compile_result}\n"
                f"Source written to: {kernel_path.with_suffix('.cce')}"
            )
        # S5: marker written only AFTER a successful compile — a failed compile
        # leaves no matching marker, so a partial/stale .o can never be reused.
        _write_cache_marker(self._kernel_meta, kernel_name, source,
                            self._ascendc_dump, core_type, self._platform)

        # Setup RTS device
        self._device = RTSInterface(
            short_soc_version=self._short_soc,
        )
        self._device.set_device(device_id)
        self._device.create_context()
        try:
            self._device.set_float_overflow_mode(rts_info.RtFloatOverflowMode.RT_OVERFLOW_MODE_SATURATION)
        except RuntimeError:
            logger.debug("Float overflow mode not supported on this device, skipping.")

        # Register kernel binary
        obj_path = str(kernel_path) + ".o"
        magic_int = RTSInterface.core_type_to_magic(core_type)
        self._kernel_binary = self._device.register_device_binary_kernel(obj_path, magic_int)
        self._kernel_func = self._device.register_function(self._kernel_binary, kernel_name)

        logger.info(
            f"SourceModule compiled '{kernel_name}' successfully. "
            f"Platform={self._platform}, Core={core_type}, BlockDim={block_dim}"
        )

    def get_function(self) -> _KernelFunction:
        """Get the callable kernel function.

        Since each SourceModule compiles exactly one kernel entry,
        the ``name`` argument is optional and defaults to the kernel
        name passed to the constructor.
        """
        with open(self._json_path, encoding="UTF-8") as f:
            kernel_json = json.load(f)
        return _KernelFunction(
            device=self._device,
            kernel_binary=self._kernel_binary,
            kernel_func=self._kernel_func,
            kernel_name=self._kernel_name,
            kernel_json=kernel_json,
            block_dim=self._block_dim,
            core_type=self._core_type,
            kernel_dir=str(self._kernel_meta),
            ascendc_dump=self._ascendc_dump,
            short_soc=self._short_soc,
            workspace_arrays=self._workspace_arrays,
        )

    def __call__(self, *args, block_dim: Optional[int] = None,
                 tiling_data: Optional[bytes] = None,
                 output_indices: Optional[set] = None,
                 simt_share_memory_size: Optional[int] = None):
        """Launch the compiled kernel directly.

        This is a convenience shortcut equivalent to
        ``mod.get_function()(*args, ...)``.

        ``simt_share_memory_size`` is passed through to the kernel launch
        (see :meth:`_KernelFunction.__call__`).
        """
        return self.get_function()(*args, block_dim=block_dim, tiling_data=tiling_data,
                                    output_indices=output_indices,
                                    simt_share_memory_size=simt_share_memory_size)

    @property
    def kernel_meta(self) -> str:
        """Return the directory containing compiled artifacts."""
        return str(self._kernel_meta)

    @property
    def workspace_arrays(self):
        """Return the auto-generated workspace arrays."""
        return self._workspace_arrays

    def __del__(self):
        """Cleanup: unregister kernel and reset device."""
        try:
            if hasattr(self, "_device") and self._device:
                self._device.reset()
        except Exception:
            pass

    def __repr__(self):
        return (
            f"SourceModule('{self._kernel_name}', "
            f"platform={self._platform}, core={self._core_type}, "
            f"block_dim={self._block_dim}, device={self._device_id})"
        )
