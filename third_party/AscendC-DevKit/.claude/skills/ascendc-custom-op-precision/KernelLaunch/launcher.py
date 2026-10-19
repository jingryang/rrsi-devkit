import ctypes
import logging
import math
import os
from typing import Dict, List, Optional, Tuple, Union


_LOCAL_CSRC_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "csrc")


def _ensure_ttk_csrc_local():
    """Prefer the csrc/ vendored inside KernelLaunch for ttk cext loading.

    The pip-installed ttk wheel neither includes the csrc/ C extensions (so
    libttk_error_manager_cleaner.so etc. are absent) nor can build them on
    demand.  An editable install can additionally be shadowed by a leftover
    physical site-packages copy (editable finder is appended after PathFinder).
    Point ttk's cext loader at the vendored csrc so the error cleaner and other
    extensions resolve from KernelLaunch regardless of how ttk was installed.
    """
    if not os.path.isdir(_LOCAL_CSRC_ROOT):
        return
    try:
        from ttk.utilities import cext_loader
    except Exception:
        return
    if getattr(cext_loader, "_kernel_launch_local_csrc", False):
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
    cext_loader._kernel_launch_local_csrc = True


_ensure_ttk_csrc_local()

from ttk._env import setup_env
setup_env()

import numpy as np

from ttk.core_modules.runtime import RTSInterface, LaunchKernelArgs

from ttk.core_modules.operator.op_interface import OperatorInterface
from ttk.core_modules.operator.op_info_keeper import OpInfoKeeper

# -- monkey-patch: backport _derive_op_source fix for vendor-name extraction from path
_original_derive = OpInfoKeeper._derive_op_source

@staticmethod
def _derive_op_source(config_file_path, source_type, vendor_name):
    impl_prefix = ""
    if not vendor_name:
        vendors_marker = os.sep + "vendors" + os.sep
        if vendors_marker in config_file_path:
            vendor_name = config_file_path.split(vendors_marker)[1].split(os.sep)[0]
    if vendor_name:
        impl_prefix = vendor_name + "_"

    config_filename = os.path.basename(config_file_path)
    ops_group = ""
    if config_filename.startswith("aic-") and "-ops-info-" in config_filename:
        category = config_filename.split("-ops-info-")[1].replace(".json", "")
        if category:
            ops_group = "ops_" + category

    config_dir = os.path.dirname(config_file_path)
    config_parent = os.path.dirname(config_dir)
    impl_base_path = os.path.dirname(config_parent)

    return {"_impl_prefix": impl_prefix, "_ops_group": ops_group,
            "_impl_base_path": impl_base_path}

OpInfoKeeper._derive_op_source = _derive_op_source
# -- end monkey-patch

from ttk.core_modules.npu.op.compilation.binary_kernel_match import (
    binary_kernel_match, parse_matched_bin_info,
)
from ttk.core_modules.npu.op.compilation.common import CceManualCompile
from ttk.core_modules.npu.op.compilation.dynamic_compilation import dyn_do_tiling
from ttk.core_modules.testcase_manager.testcase_op import TestcaseOp
from ttk.utilities.container_utils import get_global_storage, set_global_storage
from ttk.utilities.classes import SWITCHES, DynamicOpTilingResult, DynamicCompilationResult, SoCSimtCfg
from ttk.utilities.platform import get_npu_hw_info
from ttk.utilities.dtypes import get_dtype_width, resolve_custom_numpy_dtypes
from ttk.core_modules.operator.tbe_interface import Opc
from ttk.core_modules.npu.error_cleaner import clear_error_manager

from .static_check import (
    auto_detect_kernel_name,
    check_regbase_source,
    StaticCheckReport,
)

logger = logging.getLogger("KernelLaunch")


def _prepare_camodel_tmp():
    ascend_toolkit_home = os.environ.get("ASCEND_TOOLKIT_HOME")
    if not ascend_toolkit_home:
        return ""

    camodel_dir = os.path.join(
        ascend_toolkit_home, "tools", "simulator", "Ascend950PR_9599", "camodel"
    )
    if not os.path.isdir(camodel_dir):
        return ""

    tmp_dir = f"/tmp/cannsim_camodel_fix_{os.getuid()}"
    if not os.path.isdir(tmp_dir):
        shutil.copytree(camodel_dir, tmp_dir, dirs_exist_ok=True)

    return tmp_dir + "/"


def _prepare_camodel_workdirs():
    os.makedirs("log_ca", exist_ok=True)


def _generate_cannsim_report(
    kernel_meta: pathlib.Path,
    kernel_name: str,
    core_ids: str = "0",
    output_dir: Optional[pathlib.Path] = None,
    object_file: Optional[str] = None,
) -> Optional[pathlib.Path]:
    try:
        from cannsim.core.report.report import generate_report
    except Exception as exc:
        logger.warning("cannsim package not available; skipping report generation: %s", exc)
        return None

    export_dir = kernel_meta / "camodel_artifacts"
    if not (export_dir / "instr.bin").exists():
        if pathlib.Path("instr.bin").exists():
            export_dir = pathlib.Path(os.getcwd())
        else:
            logger.warning("No instr.bin found in %s or cwd; skipping report generation.", export_dir)
            return None

    if output_dir is None:
        output_dir = kernel_meta / "cannsim_report"

    output_dir.mkdir(parents=True, exist_ok=True)

    if output_dir.exists():
        for child in output_dir.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            elif child.name != ".gitkeep":
                child.unlink()

    try:
        success = generate_report(
            export=str(export_dir),
            output=str(output_dir),
            core_id=core_ids,
            object_file=object_file,
        )
    except Exception as exc:
        logger.warning("Report generation failed: %s", exc)
        return None

    if success:
        logger.info("CAModel report generated in %s", output_dir)
        simplify_traces_in_dir(output_dir, core_ids=core_ids)
        return output_dir
    else:
        logger.warning("Report generation returned failure.")
        return None


def _ensure_camodel_env():
    _prepare_camodel_workdirs()

    tmp_dir_prefix = _prepare_camodel_tmp()
    if not tmp_dir_prefix:
        return ""

    tmp_dir = tmp_dir_prefix.rstrip("/")
    ld_path = os.environ.get("LD_LIBRARY_PATH", "")
    ld_parts = [p for p in ld_path.split(os.pathsep) if p]

    if ld_parts and os.path.normpath(ld_parts[0]) == os.path.normpath(tmp_dir):
        os.environ.setdefault("ASCEND_RT_VISIBLE_DEVICES", "0")
        return tmp_dir_prefix

    if os.environ.get("_TTK_CAMODEL_SETUP_DONE"):
        reordered = [p for p in ld_parts if tmp_dir not in p]
        os.environ["LD_LIBRARY_PATH"] = f"{tmp_dir}:{':'.join(reordered)}"
        os.environ.setdefault("ASCEND_RT_VISIBLE_DEVICES", "0")
        return tmp_dir_prefix

    new_env = os.environ.copy()
    cleaned = [p for p in ld_parts if "/simulator/" not in p]
    new_env["LD_LIBRARY_PATH"] = f"{tmp_dir}:{os.pathsep.join(cleaned)}"
    new_env["_TTK_CAMODEL_SETUP_DONE"] = "1"
    # setdefault 语义：继承的框架 op 卡 pin 优先（硬覆盖会污染 execve 后同
    # 进程的后续真实卡操作）；独立 TUI 无 pin 保持历史 "0"。
    new_env.setdefault("ASCEND_RT_VISIBLE_DEVICES", "0")
    os.execve(sys.executable, [sys.executable] + sys.argv, new_env)


def _as_numpy(arr):
    if isinstance(arr, np.ndarray):
        return arr
    return np.ascontiguousarray(arr)


def _np_dtype_to_str(dt) -> str:
    return np.dtype(dt).name


class KernelLauncher:

    def __init__(self, op_name: str, device_id: int = 0,
                 kernel_meta: Optional[str] = None,
                 static_check: bool = False):
        self._op_name = op_name
        self._device_id = device_id
        self._static_check = static_check
        self._kernel_meta_root = kernel_meta
        self._inputs: list = []
        self._output_specs: List[dict] = []
        self._attrs: Dict[int, object] = {}
        self._input_dtype_overrides: Dict[int, str] = {}
        self._device: Optional[RTSInterface] = None
        self._kernel_meta = ""
        self._kernel_o_path: Optional[str] = None
        self._kernel_name: Optional[str] = None
        self._kernel_dir: Optional[str] = None
        self._last_compile_result: Optional[DynamicCompilationResult] = None
        self._last_block_dim: Optional[int] = None
        self._tiling_keys: List[int] = []
        self._o_paths: List[str] = []
        self._init_ttk_environment()

    @staticmethod
    def _ensure_soc_version():
        sw = get_global_storage()
        if sw is None:
            sw = SWITCHES()
            set_global_storage(sw)
        if sw.dev_plat == "AUTO":
            from ttk.utilities.platform import get_ascend_full_soc_version
            sw.dev_plat = get_ascend_full_soc_version()
            hw_info = get_npu_hw_info(sw.dev_plat)
            sw.short_soc_version = hw_info.get("short_soc_version")
            os.environ["TTK_FULL_SOC_VERSION"] = sw.dev_plat
            os.environ["TTK_SHORT_SOC_VERSION"] = sw.short_soc_version

    def _init_ttk_environment(self):
        self._ensure_soc_version()
        sw = get_global_storage()
        if self._kernel_meta_root:
            self._kernel_meta = os.path.join(self._kernel_meta_root, self._op_name)
            sw.compile_options["kernel_meta_parent_dir"] = self._kernel_meta_root
        else:
            self._kernel_meta = os.path.join(os.getcwd(), "kernel_meta", self._op_name)
        os.makedirs(self._kernel_meta, mode=0o700, exist_ok=True)
        sw.kernel_meta = self._kernel_meta
        sw.warmup = False
        sw.tiling_run_time = 1
        sw.run_timeout = 0
        sw.force_clear_l1 = None
        sw.force_clear_ub = None
        sw.reuse_hbm = False
        sw.simt_cfg = SoCSimtCfg()

    def set_input(self, index: int, tensor, dtype_override: Optional[str] = None):
        if isinstance(tensor, np.ndarray):
            tensor = np.ascontiguousarray(tensor)
        while len(self._inputs) <= index:
            self._inputs.append(None)
        self._inputs[index] = tensor

        if dtype_override is not None:
            self._input_dtype_overrides[index] = dtype_override
        else:
            self._input_dtype_overrides.pop(index, None)

    def set_output(self, index: int, shape: Tuple[int, ...],
                   dtype):
        dtype_str = dtype
        if isinstance(dtype, str):
            dtype_str = dtype
        elif isinstance(dtype, np.dtype):
            dtype_str = _np_dtype_to_str(dtype)
        else:
            dtype_str = _np_dtype_to_str(dtype)
        while len(self._output_specs) <= index:
            self._output_specs.append(None)
        self._output_specs[index] = {"shape": tuple(shape), "dtype": dtype_str}

    def set_attr(self, index: int, value: Union[int, float, bool, str]):
        self._attrs[index] = value

    def show_op_info(self, op_name=None):
        if op_name is None:
            op_name = self._op_name
        self._ensure_soc_version()
        info = OpInfoKeeper().info_of(op_name)
        if not info:
            print(f"Operator [{op_name}] not found.")
            return
        op_type = OpInfoKeeper().op_type_of(op_name)
        impl_path = info.get("_impl_base_path", "")
        print(f"Operator: {op_name}  (type: {op_type})")
        if impl_path:
            # Try to locate the concrete dynamic operator script.
            prefix = info.get("_impl_prefix", "")
            group = info.get("_ops_group", "")
            op_file = info.get("opFile.value", "")
            parts = [impl_path, "impl"]
            if group:
                parts.append(group)
            parts.append("dynamic")
            parts.append(f"{prefix}{op_file}.py" if prefix else f"{op_file}.py")
            dynamic_script = os.path.join(*parts)
            if os.path.isfile(dynamic_script):
                print(f"  Script: {dynamic_script}")
            else:
                print(f"  Impl base: {impl_path}")
        print(f"  Inputs:")
        for i, inp in enumerate(info.get("inputs", ())):
            print(f"    [{i}] {inp.get('name', '?')}  dtype={inp.get('dtype', '?')}  "
                  f"format={inp.get('format', '?')}  paramType={inp.get('paramType', 'required')}")
        print(f"  Outputs:")
        for i, out in enumerate(info.get("outputs", ())):
            print(f"    [{i}] {out.get('name', '?')}  dtype={out.get('dtype', '?')}  "
                  f"format={out.get('format', '?')}")
        attr_list = info.get("attr", ())
        if attr_list:
            print(f"  Attributes:")
            for i, attr in enumerate(attr_list):
                print(f"    [{i}] {attr.get('name', '?')}  type={attr.get('type', '?')}  "
                      f"default={attr.get('defaultValue', '?')}")

    def locate_op_source(self, op_name: Optional[str] = None) -> Optional[str]:
        """Locate the AscendC kernel source file for an operator.

        The kernel source lives alongside the operator implementation, derived
        from the op registration info:

            {impl_base_path}/impl/{ops_group}/ascendc/{op_interface}/{op_file}.cpp

        Returns:
            The absolute path to the ``.cpp`` source file, or ``None`` when the
            operator is not registered or no source file can be found.
        """
        if op_name is None:
            op_name = self._op_name
        self._ensure_soc_version()
        try:
            info = OpInfoKeeper().info_of(op_name)
        except Exception:
            return None
        if not info:
            return None
        impl_base = info.get("_impl_base_path", "")
        ops_group = info.get("_ops_group", "")
        op_file = info.get("opFile.value", "")
        op_interface = info.get("opInterface.value", "") or op_file
        if not impl_base or not op_file:
            return None
        ascendc_dir = os.path.join(impl_base, "impl", ops_group, "ascendc", op_interface)
        if not os.path.isdir(ascendc_dir):
            return None
        source = os.path.join(ascendc_dir, f"{op_file}.cpp")
        if os.path.isfile(source):
            return source
        for entry in sorted(os.listdir(ascendc_dir)):
            if entry.endswith(".cpp"):
                return os.path.join(ascendc_dir, entry)
        return None

    def static_check(self, op_name: Optional[str] = None,
                     raise_on_failure: bool = True) -> StaticCheckReport:
        """Run the built-in RegBase static checks on the operator's kernel source.

        The source file is located automatically via ``locate_op_source``, so no
        manual path needs to be supplied. This is useful to validate an operator
        before the (expensive) compile/launch pipeline.

        Args:
            op_name: Operator name to check. Defaults to the launcher's op_name.
            raise_on_failure: If ``True``, raise ``RuntimeError`` when any check
                fails. Set ``False`` to get the report instead.

        Returns:
            A ``StaticCheckReport`` with every check result.

        Raises:
            RuntimeError: If the source file cannot be located, or (when
                ``raise_on_failure`` is ``True``) if any check fails.
        """
        if op_name is None:
            op_name = self._op_name
        source_path = self.locate_op_source(op_name)
        if not source_path:
            raise RuntimeError(
                f"Cannot locate AscendC kernel source for operator [{op_name}]. "
                "Make sure the operator is registered in the op info config "
                "and its .cpp source exists under {impl_base}/impl/{ops_group}/ascendc/."
            )
        with open(source_path, encoding="UTF-8") as f:
            source = f.read()
        kernel_name = auto_detect_kernel_name(source) or op_name
        logger.info("Static check %s: %s", op_name, source_path)
        return check_regbase_source(source, kernel_name, raise_on_failure=raise_on_failure)

    @classmethod
    def for_case(cls, op_name: str, case_label: str = "",
                 device_id: int = 0) -> "KernelLauncher":
        import datetime
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_{case_label}" if case_label else ""
        kernel_meta = f"kernel_meta_{op_name}{suffix}_{ts}"
        return cls(op_name, device_id=device_id, kernel_meta=kernel_meta)

    def run(self) -> List[np.ndarray]:
        clear_error_manager()

        if self._static_check:
            self.static_check(self._op_name)
        if self._device is None:
            self._device = self._create_device()
        testcase = self._build_testcase()
        interface = OperatorInterface().with_core_type(testcase.core_type)

        try:
            compile_result = self._binary_match(interface, testcase)
        except RuntimeError as e:
            raise RuntimeError(
                f"Binary kernel match failed for [{self._op_name}]. "
                f"No OPP prebuilt kernel. {e}"
            ) from None

        self._last_compile_result = compile_result
        self._do_tiling(interface, testcase, compile_result)
        self.dump_tiling_data(compile_result)
        results = self._launch_kernel(testcase, compile_result)
        self._tiling_keys.append(compile_result.tiling_key)
        self._o_paths.append(self._kernel_o_path)

        self._attrs.clear()
        self._inputs.clear()
        self._output_specs.clear()
        self._input_dtype_overrides.clear()
        return results

    def run_case(self, case: dict, golden_fn, seed: int = 42) -> dict:
        """Run one cann-bench case: generate input, set attrs, launch, compare.

        由用户传入 ``case`` (来自 ``load_cases``) 和 ``golden_fn`` (来自
        ``load_golden``)，launcher 负责生成输入、清理旧状态、设置参数、启动
        kernel 并用 devkit MERE/MARE 标准与 golden 比较。

        Example::

            golden_fn = load_golden("golden.py", entry="exp", input_type="torch")
            cases     = load_cases("cases.csv")

            launcher = KernelLauncher("exp", device_id=7)
            for c in cases:
                result = launcher.run_case(c, golden_fn)
                print(result["passed"], result["mare"])

        Returns:
            ``compare_outputs`` 结果 dict::

                {"passed": True, "mere": 0.0, "mare": 0.0,
                 "max_diff": 0.0, "per_output": [...], ...}
        """
        from .golden_compare import compare_outputs as _cmp

        shape      = case["shape"]
        dtype      = case["dtype"]
        attrs      = case["attrs"]
        lo, hi     = case["value_range"]

        # ---- generate input ----------------------------------------------
        x = self._gen_case_input(shape, dtype, lo, hi, seed)
        is_bf16 = "bfloat16" in str(dtype).lower()
        x_g = x.astype(np.float32) if is_bf16 else x.astype(np.float32)
        golden = golden_fn(x_g, **attrs)

        # ---- set up launcher ---------------------------------------------
        clear_error_manager()

        self.set_input(0, x)
        self.set_output(0, shape, dtype=dtype)

        # map attr dict keys → launcher index via op info
        attr_names = self._get_op_attr_names()
        for name, val in attrs.items():
            try:
                idx = attr_names.index(name)
            except ValueError:
                continue   # attr not in op definition — skip
            self.set_attr(idx, float(val))

        # ---- run + compare -----------------------------------------------
        outputs = self.run()
        return _cmp(outputs, golden)

    @staticmethod
    def _gen_case_input(shape, dtype, lo, hi, seed):
        """Generate random input for a case value range (handles NaN / Inf)."""
        rng   = np.random.RandomState(seed)
        is_bf = "bfloat16" in str(dtype).lower()

        if np.isnan(lo) or np.isnan(hi):
            x = np.full(shape, np.nan, dtype=np.float32)
        elif np.isinf(lo) or np.isinf(hi):
            x = rng.uniform(-10, 10, size=shape).astype(np.float32)
            mask = rng.random(shape) < 0.05
            sign = np.where(rng.random(shape) < 0.5, 1.0, -1.0)
            x[mask] = sign[mask] * np.inf
        else:
            x = rng.uniform(lo, hi, size=shape).astype(np.float32)
        if is_bf:
            x = x.astype(dtype)
        return x

    @property
    def kernel_meta(self) -> str:
        return self._kernel_meta

    @property
    def kernel_o_path(self) -> Optional[str]:
        return self._kernel_o_path

    @property
    def kernel_name(self) -> Optional[str]:
        return self._kernel_name

    @property
    def kernel_dir(self) -> Optional[str]:
        return self._kernel_dir

    @property
    def last_block_dim(self) -> Optional[int]:
        return self._last_block_dim

    @property
    def tiling_keys(self) -> List[int]:
        return list(self._tiling_keys)

    @property
    def o_paths(self) -> List[str]:
        return list(self._o_paths)

    def close(self):
        if self._device:
            try:
                self._device.reset()
            except Exception:
                pass
            self._device = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _create_device(self) -> RTSInterface:
        sw = get_global_storage()
        device = RTSInterface(
            short_soc_version=sw.short_soc_version,
        )
        device.set_device(self._device_id)
        return device

    def _build_testcase(self) -> TestcaseOp:
        tc = TestcaseOp()
        tc.testcase_name = f"kl_{self._op_name}"
        tc.op_name = self._op_name
        tc.is_valid = True
        tc.fail_reason = ""
        tc.core_type = "AiCore"

        input_count = len([x for x in self._inputs if x is not None])
        output_count = len([x for x in self._output_specs if x is not None])
        attr_names = self._get_op_attr_names()

        shapes = []
        dtypes = []
        for i, inp in enumerate(self._inputs):
            if inp is None:
                shapes.append(None)
                dtypes.append(None)
            elif isinstance(inp, np.ndarray):
                shapes.append(tuple(inp.shape))
                dt = self._input_dtype_overrides.get(i, _np_dtype_to_str(inp.dtype))
                dtypes.append(dt)
            else:
                shapes.append(tuple(inp.shape))
                dt = self._input_dtype_overrides.get(i, _np_dtype_to_str(inp.dtype))
                dtypes.append(dt)

        tc.input_shapes = tuple(shapes)
        tc.input_dtypes = tuple(dtypes)
        nd = tuple("ND" for _ in shapes)
        tc.input_formats = nd
        tc.input_ori_shapes = tc.input_shapes
        tc.input_ori_formats = nd

        out_shapes = []
        out_dtypes = []
        for spec in self._output_specs:
            if spec is None:
                out_shapes.append(None)
                out_dtypes.append(None)
            else:
                out_shapes.append(tuple(spec["shape"]))
                out_dtypes.append(spec["dtype"])
        tc.output_shapes = tuple(out_shapes)
        tc.output_dtypes = tuple(out_dtypes)
        out_nd = tuple("ND" for _ in out_shapes)
        tc.output_formats = out_nd
        tc.output_ori_shapes = tc.output_shapes
        tc.output_ori_formats = out_nd

        tla = {}
        for k, v in self._attrs.items():
            if k < len(attr_names):
                tla[attr_names[k]] = v
        tc.attributes = tla

        tc._input_distribution = tuple(0 for _ in shapes)
        tc._output_distribution = tuple(0 for _ in out_shapes)
        tc._computed_list_distribution = tc._input_distribution + tc._output_distribution
        tc._cache_split_attributes()

        return tc

    def _get_op_attr_names(self) -> List[str]:
        try:
            info = OpInfoKeeper().info_of(self._op_name)
            if not info:
                return []
            return [a.get("name", f"attr_{i}") for i, a in enumerate(info.get("attr", ()))]
        except Exception:
            return []

    def dump_tiling_data(self, compile_result: DynamicCompilationResult = None):
        """Print tiling data bytes and parsed fields."""
        if compile_result is None:
            compile_result = self._last_compile_result
        if compile_result is None or compile_result.tiling_data is None:
            print("Tiling data: not available")
            return
        tiling_data = compile_result.tiling_data
        tiling_key = compile_result.tiling_key
        print(f"Tiling key: {tiling_key}")
        print(f"Tiling data ({len(tiling_data)} bytes):")
        if len(tiling_data) % 4 == 0:
            arr = np.frombuffer(tiling_data, dtype=np.uint32)
            print(f"  uint32: {arr.tolist()}")
        else:
            print(f"  hex: {tiling_data.hex()}")

    def _check_output_out_of_bounds(self, device, addrs, arrays, label: str = "output",
                                    pre_snapshots: Optional[List[np.ndarray]] = None) -> List[str]:
        """Check whether kernel wrote past the allocated HBM boundary.

        Two independent OOB checks:
        1. **Sentinel check** – guard bytes at end of HBM allocation.
        2. **Data-change check** – compares post-kernel HBM content to
           pre-kernel snapshot.  If unchanged, the kernel wrote to a
           wrong address (silent OOB).

        Reference: SingleOperatorLaunch/diagnostics.py
        """
        oob_results = []
        for idx, (addr, arr) in enumerate(zip(addrs, arrays)):
            if addr is None or (isinstance(addr, ctypes.c_void_p) and not addr.value):
                oob_results.append("OK")
                continue
            array_size = int(math.ceil(arr.size * get_dtype_width(arr.dtype)))

            # --- Check 1: Sentinel guard bytes ---
            oob_offset, oob_size = device.get_oob_check_offset_bytes(array_size)
            oob_addr = ctypes.c_void_p(addr.value + oob_offset)
            try:
                oob_bytes = device.get_data_from_hbm(oob_addr, oob_size)
            except Exception as e:
                logger.warning(f"Failed to read {label} OOB sentinel for index {idx}: {e}")
                oob_results.append("UNKNOWN")
                continue
            oob_sentinels = np.frombuffer(bytes(oob_bytes), dtype=np.uint8)
            if not np.all(oob_sentinels == device.OOB_SENTINEL):
                oob_results.append("FAIL")
                msg = (f"The {idx}th {label} memory out of bound! "
                       f"All data should be {device.OOB_SENTINEL} (uint8), "
                       f"but got:\n{oob_sentinels}")
                logger.error(msg)
                print(msg)
                continue

            # --- Check 2: Data-change check (silent OOB) ---
            if pre_snapshots is not None and idx < len(pre_snapshots) and pre_snapshots[idx] is not None:
                try:
                    post_data = device.get_data_from_hbm(addr, array_size)
                    post_bytes = np.frombuffer(bytes(post_data), dtype=np.uint8)
                    if np.array_equal(post_bytes, pre_snapshots[idx]):
                        oob_results.append("FAIL")
                        msg = (f"The {idx}th {label} memory out of bound (data unchanged) !! "
                               f"The kernel wrote NOTHING to the expected output buffer.\n"
                               f"  Data at [{hex(addr.value)}, {hex(addr.value + array_size)}) "
                               f"is identical to pre-kernel state.")
                        logger.error(msg)
                        print(msg)
                        continue
                except Exception as e:
                    logger.warning(f"Failed to read {label} data-change check for index {idx}: {e}")

            oob_results.append("OK")
        return oob_results

    def _binary_match(self, interface: OperatorInterface,
                      testcase: TestcaseOp) -> DynamicCompilationResult:
        sw = get_global_storage()
        matched_json = binary_kernel_match(interface, testcase, sw.compile_options)
        if not matched_json:
            raise RuntimeError(
                f"Binary kernel match failed for [{self._op_name}]. "
                f"Check ASCEND_OPP_PATH and soc_version."
            )
        result = DynamicCompilationResult()
        result.tiling_result = DynamicOpTilingResult()
        parse_matched_bin_info(interface, testcase, matched_json, result)
        return result

    def _do_tiling(self, interface: OperatorInterface,
                   testcase: TestcaseOp, compile_result: DynamicCompilationResult):
        dyn_do_tiling(interface, testcase, compile_result)

    def _launch_kernel(self, testcase: TestcaseOp,
                       compile_result: DynamicCompilationResult) -> List[np.ndarray]:
        device = self._device
        kj = compile_result.kernel_json_info
        kernel_path = os.path.join(compile_result.kernel_dir, f"{compile_result.kernel_name}.o")
        self._kernel_o_path = kernel_path
        self._kernel_name = compile_result.kernel_name
        self._kernel_dir = compile_result.kernel_dir
        if not os.path.exists(kernel_path):
            raise RuntimeError(f"Kernel binary not found: {kernel_path}")

        magic = kj.magic
        if isinstance(magic, str):
            magic = device.int_magic(magic)

        output_arrays = []
        for spec in self._output_specs:
            if spec is not None:
                dt = spec["dtype"]
                buf_dt = resolve_custom_numpy_dtypes([dt])[0]
                out = np.zeros(spec["shape"], dtype=buf_dt)
                output_arrays.append(out)

        # Save pre-kernel snapshots (as uint8) for data-change OOB check
        pre_output_snapshots = []
        for oa in output_arrays:
            byte_size = int(math.ceil(oa.size * get_dtype_width(oa.dtype)))
            pre_output_snapshots.append(np.frombuffer(oa.tobytes(), dtype=np.uint8))

        output_placeholder = OpInfoKeeper().op_output_defined(self._op_name)

        ipt_addrs = []
        opt_addrs = []
        ws_addrs = []
        ctx = None
        stream = None

        try:
            ctx = device.create_context()
            stream = device.create_stream()
            # device.warmup(get_global_storage())

            if kj.is_fat_bin:
                binary = device.register_all_kernel(kernel_path, magic)
            else:
                binary = device.register_device_binary_kernel(kernel_path, magic)

            for inp in self._inputs:
                if inp is None:
                    ipt_addrs.append(ctypes.c_void_p(None))
                else:
                    arr = _as_numpy(inp)
                    addr = device.copy_nparray_to_hbm(arr, fill_oob_flag=True)
                    ipt_addrs.append(addr)

            for oa in output_arrays:
                addr = device.copy_nparray_to_hbm(oa, fill_oob_flag=True)
                opt_addrs.append(addr)

            ws_sizes = compile_result.workspaces or ()
            ws_arrays = []
            for ws_size in ws_sizes:
                wa = np.zeros(int(ws_size), dtype=np.uint8)
                ws_arrays.append(wa)
                addr = device.copy_nparray_to_hbm(wa, fill_oob_flag=True)
                ws_addrs.append(addr)

            op_args = list(ipt_addrs)
            if output_placeholder:
                op_args.extend(opt_addrs)
            op_args.extend(ws_addrs)

            tiling_data = compile_result.tiling_data
            block_dim = int(compile_result.block_dim)
            if block_dim <= 0:
                raise RuntimeError(f"Invalid block_dim: {block_dim}")
            self._last_block_dim = block_dim

            global_ws_size = kj.global_workspace_size or 0
            dfx_args = []
            if global_ws_size > 0:
                da = np.zeros(global_ws_size, dtype=np.byte)
                g_addr = device.copy_nparray_to_hbm(da)
                dfx_args.append(g_addr)

            if kj.is_fat_bin:
                launch_args = LaunchKernelArgs(
                    func_or_binary_hdl=binary,
                    op_args=op_args,
                    dfx_args=dfx_args,
                    block_dim=block_dim,
                    tiling_key=compile_result.tiling_key,
                    tiling_data=tiling_data,
                    mix_kernel=kj.is_mix_kernel,
                    schedule_mode=kj.schedule_mode,
                )
                device.launch_kernel_with_handle(launch_args, stream)
            else:
                launch_args = LaunchKernelArgs(
                    func_or_binary_hdl=binary,
                    op_args=op_args,
                    dfx_args=dfx_args,
                    block_dim=block_dim,
                    mix_kernel=kj.is_mix_kernel,
                    tiling_data=tiling_data,
                    schedule_mode=kj.schedule_mode,
                )
                device.launch_kernel_with_flag(launch_args, stream)

            device.synchronize_with_stream(stream, timeout=0)

            opt_oob = self._check_output_out_of_bounds(device, opt_addrs, output_arrays, "output",
                                                       pre_snapshots=pre_output_snapshots)
            ws_oob = self._check_output_out_of_bounds(device, ws_addrs, ws_arrays, "workspace")
            print(f"Runtime block_dim: {block_dim}")
            print(f"OOB check: output={opt_oob}, workspace={ws_oob}")
            if any(r == "FAIL" for r in opt_oob + ws_oob):
                print("Error: Memory out-of-bound detected.")

            results = []
            for idx, oa in enumerate(output_arrays):
                byte_size = int(math.ceil(oa.size * get_dtype_width(oa.dtype)))
                data = device.get_data_from_hbm(opt_addrs[idx], byte_size)
                arr = np.frombuffer(bytes(data), dtype=oa.dtype).reshape(oa.shape)
                results.append(arr)

            return results

        finally:
            for a in ipt_addrs + opt_addrs + ws_addrs:
                if isinstance(a, ctypes.c_void_p) and a.value:
                    try:
                        device.free(a)
                    except Exception:
                        pass
            if stream:
                try:
                    device.destroy_stream_force(stream)
                except Exception:
                    pass
            if ctx:
                try:
                    device.destroy_context(ctx)
                except Exception:
                    pass
