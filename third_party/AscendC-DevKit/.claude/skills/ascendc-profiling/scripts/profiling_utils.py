#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AscendC Profiling Utilities

Reusable profiling setup and analysis functions.

Usage:
    from profiling_utils import (
        create_profiler,
        profile_operator,
        analyze_kernel_details,
        diagnose_bottleneck,
    )
"""

import torch_npu
import os
import csv
from pathlib import Path
from typing import Callable, Optional, Dict, List, Tuple


def create_profiler(
    profile_dir: str,
    level: str = "Level1",
    aic_metrics: str = "PipeUtilization",
) -> torch_npu.profiler.profile:
    """
    Create a configured NPU profiler.

    Args:
        profile_dir: Output directory for profiling data
        level: ProfilerLevel (Level0, Level1, Level2)
        aic_metrics: AiCMetrics type (PipeUtilization, ArithmeticUtilization, etc.)

    Returns:
        Configured profiler instance
    """
    level_map = {
        "Level0": torch_npu.profiler.ProfilerLevel.Level0,
        "Level1": torch_npu.profiler.ProfilerLevel.Level1,
        "Level2": torch_npu.profiler.ProfilerLevel.Level2,
    }
    metrics_map = {
        "PipeUtilization": torch_npu.profiler.AiCMetrics.PipeUtilization,
        "ArithmeticUtilization": torch_npu.profiler.AiCMetrics.ArithmeticUtilization,
        "Memory": torch_npu.profiler.AiCMetrics.Memory,
        "MemoryL0": torch_npu.profiler.AiCMetrics.MemoryL0,
        "MemoryUB": torch_npu.profiler.AiCMetrics.MemoryUB,
    }

    experimental_config = torch_npu.profiler._ExperimentalConfig(
        aic_metrics=metrics_map.get(aic_metrics, torch_npu.profiler.AiCMetrics.PipeUtilization),
        profiler_level=level_map.get(level, torch_npu.profiler.ProfilerLevel.Level1),
    )

    profiler = torch_npu.profiler.profile(
        activities=[
            torch_npu.profiler.ProfilerActivity.CPU,
            torch_npu.profiler.ProfilerActivity.NPU,
        ],
        with_stack=False,
        profile_memory=False,
        with_modules=False,
        experimental_config=experimental_config,
        on_trace_ready=torch_npu.profiler.tensorboard_trace_handler(profile_dir),
    )

    return profiler


def profile_operator(
    operator_fn: Callable,
    inputs: tuple,
    profile_dir: str,
    warmup: int = 10,
    iterations: int = 100,
    **profiler_kwargs,
) -> str:
    """
    Profile an operator with warmup and timing.

    Args:
        operator_fn: Callable operator function
        inputs: Tuple of input tensors
        profile_dir: Output directory
        warmup: Warmup iterations
        iterations: Profiling iterations
        **profiler_kwargs: Additional args for create_profiler

    Returns:
        Path to profiler output directory
    """
    # Warmup
    for _ in range(warmup):
        _ = operator_fn(*inputs)
    torch_npu.npu.synchronize()

    # Profile
    profiler = create_profiler(profile_dir, **profiler_kwargs)
    profiler.start()
    for _ in range(iterations):
        _ = operator_fn(*inputs)
    torch_npu.npu.synchronize()
    profiler.stop()

    # Find output directory
    output_dirs = list(Path(profile_dir).glob("*_ascend_pt"))
    if output_dirs:
        return str(output_dirs[-1] / "ASCEND_PROFILER_OUTPUT")
    return profile_dir


def analyze_kernel_details(csv_path: str) -> List[Dict]:
    """
    Parse kernel_details.csv and extract key metrics.

    Args:
        csv_path: Path to kernel_details.csv

    Returns:
        List of kernel metric dicts
    """
    kernels = []
    with open(csv_path, "r") as f:
        reader = csv.DictReader(f)
        for row in reader:
            kernel = {
                "name": row.get("Name", ""),
                "duration_us": float(row.get("Duration(us)", 0)),
                "block_dim": int(row.get("Block Dim", 0)),
                "aiv_vec_ratio": float(row.get("aiv_vec_ratio", 0)),
                "aiv_scalar_ratio": float(row.get("aiv_scalar_ratio", 0)),
                "aiv_mte2_ratio": float(row.get("aiv_mte2_ratio", 0)),
                "aiv_mte3_ratio": float(row.get("aiv_mte3_ratio", 0)),
                "aic_mac_ratio": float(row.get("aic_mac_ratio", 0)),
            }
            kernels.append(kernel)
    return kernels


def diagnose_bottleneck(kernel: Dict) -> Tuple[str, str]:
    """
    Diagnose bottleneck type from kernel metrics.

    Args:
        kernel: Dict with ratio metrics

    Returns:
        Tuple of (bottleneck_type, recommendation)
    """
    ratios = {
        "vector_compute": kernel.get("aiv_vec_ratio", 0),
        "scalar_compute": kernel.get("aiv_scalar_ratio", 0),
        "memory_input": kernel.get("aiv_mte2_ratio", 0),
        "memory_output": kernel.get("aiv_mte3_ratio", 0),
        "cube_compute": kernel.get("aic_mac_ratio", 0),
    }

    dominant = max(ratios, key=ratios.get)
    dominant_val = ratios[dominant]

    recommendations = {
        "vector_compute": "Optimize algorithm, reduce redundant ops, use fused APIs",
        "scalar_compute": "Vectorize control flow with Select/Compare, use mask ops",
        "memory_input": "Increase tile size, reduce data movement frequency",
        "memory_output": "Fuse downstream operations, batch outputs",
        "cube_compute": "Optimize matrix dimensions, check padding",
    }

    return dominant, recommendations.get(dominant, "Profile further")


def print_summary(kernels: List[Dict], top_n: int = 5):
    """
    Print profiling summary for top kernels.

    Args:
        kernels: List of kernel metrics
        top_n: Number of top kernels to show
    """
    # Sort by duration
    sorted_kernels = sorted(kernels, key=lambda k: k["duration_us"], reverse=True)

    print("\n" + "=" * 80)
    print("Performance Summary (Top {} Kernels)".format(top_n))
    print("=" * 80)

    for i, k in enumerate(sorted_kernels[:top_n], 1):
        bottleneck, rec = diagnose_bottleneck(k)
        print(f"\n{i}. {k['name']}")
        print(f"   Duration: {k['duration_us']:.2f} us, Cores: {k['block_dim']}")
        print(f"   Pipeline: Vec={k['aiv_vec_ratio']:.1f}%, "
              f"Scalar={k['aiv_scalar_ratio']:.1f}%, "
              f"MTE2={k['aiv_mte2_ratio']:.1f}%, "
              f"MTE3={k['aiv_mte3_ratio']:.1f}%")
        print(f"   Bottleneck: {bottleneck}")
        print(f"   Recommendation: {rec}")
