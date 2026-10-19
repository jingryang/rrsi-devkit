#!/usr/bin/env python3
"""
Evaluation backend — self-contained within ascendc-ops-evaluation skill.

Provides AscendBackend for three-way precision comparison and
performance measurement via msprof --application.
"""

import logging
import os
import random
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import numpy as np
import torch
import torch_npu

from precision import dual_inspect

# repo_type -> wheel package name mapping (mirrors evaluate_ops.py)
REPO_TYPE_TO_WHEEL = {
    "omni": "omni_training_custom_ops",      # omni-ops training (default)
    "inference": "omni_custom_ops",           # omni-ops inference
    "nn": "ascend_ops_nn",                    # ops-nn
    "cv": "ascend_ops_cv",                    # ops-cv
    "math": "ascend_ops_math",                # ops-math
    "transformer": "ascend_ops_transformer",  # ops-transformer
}


def set_seed(seed: int):
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


class AscendBackend:
    def __init__(self, eval_src: str, ref_src: str, seed_num: int = 42,
                 num_correct_trials: int = 3, device_id: int = 0, install_path: str = ""):
        self.seed_num = seed_num
        self.num_correct_trials = num_correct_trials
        self.device_id = device_id
        self.logger = logging.getLogger("AscendBackend")
        self.eval_src = eval_src
        self.ref_src = ref_src
        self.install_path = install_path

        # Execute eval code
        eval_ns = {}
        exec(eval_src, eval_ns)
        self.ModelNew = eval_ns.get("ModelNew") or eval_ns.get("Model")
        self.get_inputs_eval = eval_ns.get("get_inputs")
        self.get_init_inputs_eval = eval_ns.get("get_init_inputs")

        # Execute ref code
        ref_ns = {}
        exec(ref_src, ref_ns)
        self.ModelRef = ref_ns.get("Model")
        self.get_inputs_ref = ref_ns.get("get_inputs")
        self.get_init_inputs_ref = ref_ns.get("get_init_inputs")

        if self.ModelNew is None:
            raise RuntimeError("ModelNew/Model not found in eval code")
        if self.ModelRef is None:
            raise RuntimeError("Model not found in ref code")

    def _make_model(self, model_cls, init_inputs):
        if init_inputs:
            try:
                return model_cls(*init_inputs)
            except TypeError:
                return model_cls()
        return model_cls()

    def evaluate_correctness(self):
        """Three-way precision comparison (golden CPU fp64 vs ref NPU vs custom NPU)."""
        for trial in range(self.num_correct_trials):
            set_seed(self.seed_num + trial)

            init_inputs = self.get_init_inputs_eval() if self.get_init_inputs_eval else []
            eval_model = self._make_model(self.ModelNew, init_inputs)
            if hasattr(eval_model, "npu"):
                eval_model = eval_model.npu()
            eval_model.eval()

            set_seed(self.seed_num + trial)
            init_inputs_ref = self.get_init_inputs_ref() if self.get_init_inputs_ref else []
            ref_model = self._make_model(self.ModelRef, init_inputs_ref)
            if hasattr(ref_model, "npu"):
                ref_model = ref_model.npu()
            ref_model.eval()

            inputs_eval = self.get_inputs_eval()
            inputs_eval = [x.npu() if isinstance(x, torch.Tensor) else x for x in inputs_eval]

            set_seed(self.seed_num + trial)
            inputs_ref = self.get_inputs_ref()
            # PyTorch indexing requires int64 on both CPU and NPU
            def _ensure_index_long(x):
                if isinstance(x, torch.Tensor) and x.dtype == torch.int32:
                    return x.long()
                return x
            inputs_ref = [_ensure_index_long(x).npu() if isinstance(x, torch.Tensor) else x for x in inputs_ref]

            with torch.no_grad():
                y_eval = eval_model(*inputs_eval)
                y_ref = ref_model(*inputs_ref)

            # Golden on CPU fp64
            set_seed(self.seed_num + trial)
            inputs_golden = self.get_inputs_ref()
            def _to_cpu_golden(x):
                if isinstance(x, torch.Tensor):
                    # Indices must be int64 for CPU; numerical tensors to fp64
                    if x.dtype in (torch.int32, torch.int64):
                        return x.long()
                    return x.double()
                return x
            inputs_golden = [_to_cpu_golden(x) for x in inputs_golden]
            ref_model_cpu = self._make_model(self.ModelRef, [])
            ref_model_cpu.eval()
            with torch.no_grad():
                y_golden = ref_model_cpu(*inputs_golden)

            if isinstance(y_eval, tuple):
                y_eval = y_eval[0]
            if isinstance(y_ref, tuple):
                y_ref = y_ref[0]
            if isinstance(y_golden, tuple):
                y_golden = y_golden[0]

            # Move NPU outputs to CPU for comparison
            if y_eval.device.type != "cpu":
                y_eval = y_eval.cpu()
            if y_ref.device.type != "cpu":
                y_ref = y_ref.cpu()

            if y_eval.dtype != y_ref.dtype:
                y_eval = y_eval.to(y_ref.dtype)
            if y_golden.dtype != torch.float64:
                y_golden = y_golden.double()

            result = dual_inspect(y_eval, y_ref, y_golden, "Output")
            if not result.passed:
                diag = result.diagnosis
                msg = f"Trial {trial+1} failed: {diag.get('pattern', 'unknown')}"
                return False, msg

        return True, f"All {self.num_correct_trials} trials passed"

    def _build_perf_script(self, code_src: str, seed_num: int, num_trials: int, tag: str,
                           repo_type: str = "") -> str:
        """Generate a standalone Python script for msprof --application."""
        wheel_name = REPO_TYPE_TO_WHEEL.get(repo_type, "omni_training_custom_ops")
        wheel_import_line = f"import {wheel_name}\n" if wheel_name else ""
        pybind_lib_path = os.path.join(self.install_path, "pybind_lib") if self.install_path else ""
        pybind_lib_line = f"""
# inject pybind_lib for custom ops registration
pybind_lib = {repr(pybind_lib_path)}
if pybind_lib and os.path.isdir(pybind_lib) and pybind_lib not in sys.path:
    sys.path.insert(0, pybind_lib)
""" if pybind_lib_path else ""
        script = textwrap.dedent(f'''
import os
import sys
import torch
import torch_npu
import random
import numpy as np

# import wheel to register custom ops before model execution
{wheel_import_line}{pybind_lib_line}device_id = int(os.environ.get("ASCEND_DEVICE_ID", "0"))
torch.npu.set_device(device_id)

seed = {seed_num}
random.seed(seed)
np.random.seed(seed)
torch.manual_seed(seed)

ns = {{}}
exec({repr(code_src)}, ns)

ModelCls = ns.get("ModelNew") or ns.get("Model")
get_inputs = ns.get("get_inputs")
get_init_inputs = ns.get("get_init_inputs")

init_inputs = get_init_inputs() if get_init_inputs else []
model = ModelCls(*init_inputs) if init_inputs else ModelCls()
if hasattr(model, "npu"):
    model = model.npu()
model.eval()

inputs = get_inputs()
inputs = [x.npu() if isinstance(x, torch.Tensor) else x for x in inputs]

# Warmup
for _ in range(10):
    with torch.no_grad():
        _ = model(*inputs)
    torch.npu.synchronize()

# Trials
for _ in range({num_trials}):
    with torch.no_grad():
        _ = model(*inputs)
    torch.npu.synchronize()
        ''').strip()
        fd, path = tempfile.mkstemp(suffix=".py", prefix=f"perf_{tag}_")
        with os.fdopen(fd, "w") as f:
            f.write(script)
        return path

    def compare_performance_advanced(self, profile_root, num_trials=20, task_type="vector",
                                      repo_type: str = ""):
        """
        Measure performance via msprof --application.

        Returns:
            tuple: (ref_time, ref_data, ref_dir, ref_cv,
                    custom_time, custom_data, custom_dir, custom_cv)
        """
        from AscendPerformanceTest import (
            extract_simple_perf_info,
            extract_perf_info_from_profiling_v2,
            locate_op_summary_file,
            run_msprof_application,
        )

        profile_root = Path(profile_root).resolve()
        profile_root.mkdir(parents=True, exist_ok=True)

        # Custom model performance
        custom_script = self._build_perf_script(self.eval_src, self.seed_num, num_trials, "custom", repo_type)
        custom_prof_dir = profile_root / "custom_msprof"
        try:
            prof_out = run_msprof_application(f"python3 {custom_script}", str(custom_prof_dir), self.device_id)
            op_summary = locate_op_summary_file(prof_out)
            median_time, perf_data, cv_pct = extract_perf_info_from_profiling_v2(op_summary, task_type)
            if median_time is None:
                median_time, perf_data, cv_pct = extract_simple_perf_info(op_summary, task_type)
            custom_time = median_time
            custom_data = perf_data
            custom_cv = cv_pct
        except Exception as e:
            self.logger.error(f"Custom perf failed: {e}")
            custom_time, custom_data, custom_cv = -1, [], 0.0
        finally:
            if os.path.exists(custom_script):
                os.remove(custom_script)

        # Ref model performance
        ref_script = self._build_perf_script(self.ref_src, self.seed_num, num_trials, "ref", repo_type)
        ref_prof_dir = profile_root / "ref_msprof"
        try:
            prof_out = run_msprof_application(f"python3 {ref_script}", str(ref_prof_dir), self.device_id)
            op_summary = locate_op_summary_file(prof_out)
            median_time, perf_data, cv_pct = extract_perf_info_from_profiling_v2(op_summary, task_type)
            if median_time is None:
                median_time, perf_data, cv_pct = extract_simple_perf_info(op_summary, task_type)
            ref_time = median_time
            ref_data = perf_data
            ref_cv = cv_pct
        except Exception as e:
            self.logger.error(f"Ref perf failed: {e}")
            ref_time, ref_data, ref_cv = -1, [], 0.0
        finally:
            if os.path.exists(ref_script):
                os.remove(ref_script)

        return ref_time, ref_data, str(ref_prof_dir), ref_cv, custom_time, custom_data, str(custom_prof_dir), custom_cv
