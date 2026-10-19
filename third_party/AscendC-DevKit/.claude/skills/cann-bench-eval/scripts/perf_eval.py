#!/usr/bin/env python3
"""性能-only 评测：自定义算子（PTA 交付通路）vs torch_npu 参考实现 逐 case 时延测量。

测量口径（双侧同经 torch dispatch，保证可比）：
  - kernel_mean_us     自定义算子经其 PTA 符号（``torch.ops.<ns>.<op>`` 或 pybind）
                       调用的平均时延——与 run-cases 交付通路同一调用入口；
  - torch_npu_mean_us  golden entry 在 NPU 张量上执行的平均时延——golden 以 torch
                       算子书写时在 NPU 上即分发 torch_npu 内置算子（主线参考实现）；
  - speedup（逐 case）= torch_npu_mean_us / kernel_mean_us（>1 表示 kernel 更快）。

聚合口径：
  - kernel_mean_us / torch_npu_mean_us  逐 case 均值的算术平均；
  - geo_speedup                         逐 case speedup 的几何平均；
  - faster_cases / complete_cases       kernel 更快的 case 数 / 双侧均有测量值的 case 数。

自包含：不 import 本仓其他 skill / ascendc_devkit；输入生成与 dtype 约定对齐
KernelLaunch 测试脚本（固定 seed、float32 载体 + ``.to(目标 dtype)``、NaN/Inf 哨兵）。
torch/torch_npu 依赖全部懒加载（函数内部 import），纯逻辑部分可离线 UT。

退出码：0 = 至少一个 case 双侧完整；1 = 无完整 case（verdict=no）；2 = 环境 /
符号 / golden 加载失败。

Usage:
    python3 perf_eval.py \\
        --cases-csv cases.csv \\
        --golden-module golden.py \\
        --golden-entry exp \\
        --callable-symbol torch.ops.cann_bench.exp \\
        --output perf_result.json \\
        [--device 0] [--warmup 10] [--repeat 50] [--seed 42]
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
import statistics
import sys
from pathlib import Path

import numpy as np


# ---------------------------------------------------------------------------
# cases.csv 解析（cann-bench 约定列：operator,case_id,input_shape,dtype,attrs,
# value_range,note）
# ---------------------------------------------------------------------------

def _parse_shape(raw: str) -> tuple:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and parsed:
            inner = parsed[0]
            if isinstance(inner, list):
                return tuple(int(d) for d in inner)
            return (int(parsed[0]),)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return (1024,)


def _parse_attrs(raw: str) -> dict:
    """attrs 保持 JSON 原生类型（int/float/bool/str）——PTA kwargs 直传。"""
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


_SENTINEL = {"nan": float("nan"), "inf": float("inf"), "-inf": float("-inf")}


def _parse_vrange(raw: str) -> tuple:
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list) and len(parsed) >= 2:
            lo, hi = parsed[0], parsed[1]
            return (
                _SENTINEL.get(str(lo).lower(), float(lo)),
                _SENTINEL.get(str(hi).lower(), float(hi)),
            )
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return (-1.0, 1.0)


def _parse_dtype(raw: str) -> str:
    try:
        parsed = json.loads(raw)
        name = (parsed[0] if isinstance(parsed, list) and parsed
                else str(parsed)).strip().lower()
    except (json.JSONDecodeError, TypeError):
        name = str(raw).strip().lower()
    return name.strip('[]"\' ')


def load_cases(csv_path: str) -> list:
    cases = []
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                cid = int(row.get("case_id", 0))
            except (TypeError, ValueError):
                continue
            cases.append({
                "case_id": cid,
                "shape": _parse_shape(row.get("input_shape", "[[1024]]")),
                "dtype": _parse_dtype(row.get("dtype", '["float16"]')),
                "attrs": _parse_attrs(row.get("attrs", "{}")),
                "value_range": _parse_vrange(row.get("value_range", "[-1, 1]")),
            })
    return cases


# ---------------------------------------------------------------------------
# 输入生成（对齐 KernelLaunch 测试脚本约定：固定 seed、float32 载体、NaN/Inf 哨兵）
# ---------------------------------------------------------------------------

def gen_input(shape, lo: float, hi: float, seed: int) -> np.ndarray:
    rng = np.random.RandomState(seed)
    if np.isnan(lo) or np.isnan(hi):
        return np.full(shape, np.nan, dtype=np.float32)
    if np.isinf(lo) or np.isinf(hi):
        x = rng.uniform(-10, 10, size=shape).astype(np.float32)
        mask = rng.random(shape) < 0.05
        sign = np.where(rng.random(shape) < 0.5, 1.0, -1.0)
        x[mask] = sign[mask] * np.inf
        return x
    return rng.uniform(lo, hi, size=shape).astype(np.float32)


_TORCH_DTYPE_CACHE = None


def _torch_dtype(name: str):
    """dtype 名 → torch dtype；不支持的 dtype 显式报错（不静默降级）。"""
    global _TORCH_DTYPE_CACHE
    import torch
    if _TORCH_DTYPE_CACHE is None:
        _TORCH_DTYPE_CACHE = {
            "float16": torch.float16, "fp16": torch.float16,
            "float32": torch.float32, "fp32": torch.float32,
            "float64": torch.float64, "fp64": torch.float64,
            "bfloat16": torch.bfloat16, "bf16": torch.bfloat16,
            "int8": torch.int8, "int16": torch.int16, "int32": torch.int32,
            "int64": torch.int64, "uint8": torch.uint8,
            "float8_e4m3": getattr(torch, "float8_e4m3fn", None),
            "float8_e4m3fn": getattr(torch, "float8_e4m3fn", None),
            "fp8_e4m3": getattr(torch, "float8_e4m3fn", None),
            "float8_e5m2": getattr(torch, "float8_e5m2", None),
            "fp8_e5m2": getattr(torch, "float8_e5m2", None),
            "hifloat32": getattr(torch, "hifloat32", None),
        }
        _TORCH_DTYPE_CACHE = {
            k: v for k, v in _TORCH_DTYPE_CACHE.items() if v is not None
        }
    key = str(name).lower()
    if key not in _TORCH_DTYPE_CACHE:
        raise ValueError(f"dtype not supported by this torch build: {name}")
    return _TORCH_DTYPE_CACHE[key]


def to_npu_tensor(arr: np.ndarray, dtype_name: str):
    """numpy float32 载体 → 目标 dtype 的 NPU 张量（bf16/fp8 经 .to 转换）。"""
    import torch
    carrier = torch.from_numpy(arr.astype(np.float32))
    return carrier.to(_torch_dtype(dtype_name)).npu()


# ---------------------------------------------------------------------------
# callable / golden 解析（与 run-cases harness 同一解析约定）
# ---------------------------------------------------------------------------

def resolve_callable(symbol: str):
    """PTA 符号解析：``torch.ops.<ns>.<op>`` 或 ``<pkg.mod>.<attr>``（pybind）。"""
    import torch
    symbol = str(symbol).strip()
    if symbol.startswith("torch.ops."):
        parts = symbol.split(".")
        if len(parts) < 4:
            raise ValueError(f"invalid torch.ops symbol: {symbol}")
        ns, op = parts[-2], parts[-1]
        try:
            __import__(ns)
        except Exception:
            pass  # 注册可能来自其他已导入包（对齐 harness 容忍度）
        return getattr(getattr(torch.ops, ns), op)
    module_name, _, attr = symbol.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"invalid callable symbol: {symbol}")
    return getattr(__import__(module_name, fromlist=[attr]), attr)


def load_golden_raw(golden_path: str, entry: str):
    """importlib 加载 golden 模块并返回 entry 原函数（不做 numpy/torch 包装）。"""
    if not golden_path or not str(golden_path).endswith(".py"):
        raise ValueError(f"golden_module must be a .py file: {golden_path!r}")
    spec = importlib.util.spec_from_file_location("perf_golden_ref", golden_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["perf_golden_ref"] = module
    spec.loader.exec_module(module)
    fn = getattr(module, entry, None)
    if fn is None:
        raise ValueError(f"golden entry {entry!r} not found in {golden_path!r}")
    return fn


def _bind_golden_kwargs(fn, attrs: dict) -> dict:
    """按 golden 签名过滤 attrs（name-keyed，镜像 harness bind_golden_args 语义）。

    golden 不接受的 attr 不传，避免伪 TypeError；``**kwargs`` 形 golden 全透传。
    """
    import inspect
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return attrs
    if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()):
        return attrs
    return {k: v for k, v in attrs.items() if k in params}


# ---------------------------------------------------------------------------
# 时延测量（torch.npu.Event 设备侧计时）
# ---------------------------------------------------------------------------

def time_call(fn, warmup: int, repeat: int) -> dict:
    import torch
    import torch_npu  # noqa: F401 — monkey-patch torch.npu

    for _ in range(warmup):
        fn()
    torch.npu.synchronize()
    times_us = []
    for _ in range(repeat):
        start = torch.npu.Event(enable_timing=True)
        end = torch.npu.Event(enable_timing=True)
        start.record()
        fn()
        end.record()
        end.synchronize()
        times_us.append(start.elapsed_time(end) * 1000.0)  # ms → us
    mean = statistics.mean(times_us)
    stdev = statistics.stdev(times_us) if len(times_us) > 1 else 0.0
    return {
        "mean_us": mean,
        "median_us": statistics.median(times_us),
        "min_us": min(times_us),
        "max_us": max(times_us),
        "cv_pct": (stdev / mean * 100.0) if mean > 0 else 0.0,
        "n": len(times_us),
    }


# ---------------------------------------------------------------------------
# 聚合（纯函数，离线可 UT）
# ---------------------------------------------------------------------------

def aggregate(per_case: list) -> dict:
    """逐 case 双侧结果 → 聚合统计 + verdict。

    verdict 语义：``measured`` = 至少一个 case 双侧均有测量值；``no`` = 无完整
    case（附 reason）。partial 覆盖（complete < total）仍是 measured——未测量的
    case 逐条带 error 落盘在 per_case，不静默丢弃。
    """
    complete = [c for c in per_case if c.get("kernel") and c.get("torch_npu")]
    result = {
        "total_cases": len(per_case),
        "complete_cases": len(complete),
        "verdict": "measured" if complete else "no",
    }
    if not complete:
        reasons = sorted({
            str(c.get("kernel_error") or c.get("ref_error") or "no measurement")
            for c in per_case
        })
        result["reason"] = "; ".join(reasons[:3]) if reasons else "no measurable case"
        return result
    kernel_mean = statistics.mean(c["kernel"]["mean_us"] for c in complete)
    ref_mean = statistics.mean(c["torch_npu"]["mean_us"] for c in complete)
    speedups = [c["speedup"] for c in complete if c.get("speedup")]
    geo = (
        math.exp(statistics.mean(math.log(s) for s in speedups))
        if speedups else None
    )
    faster = sum(1 for c in complete if c.get("faster"))
    result.update({
        "kernel_mean_us": kernel_mean,
        "torch_npu_mean_us": ref_mean,
        "geo_speedup": geo,
        "faster_cases": faster,
    })
    return result


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def _emit_error(message: str, code: int = 2) -> int:
    print(json.dumps({"ok": False, "error": message}, ensure_ascii=False))
    return code


def main() -> int:
    parser = argparse.ArgumentParser(description="perf-only: kernel vs torch_npu latency")
    parser.add_argument("--cases-csv", required=True)
    parser.add_argument("--golden-module", required=True)
    parser.add_argument("--golden-entry", required=True)
    parser.add_argument("--callable-symbol", required=True,
                        help="自定义算子 PTA 符号：torch.ops.<ns>.<op> 或 <pkg.mod>.<attr>")
    parser.add_argument("--output", default="perf_result.json")
    parser.add_argument("--device", type=int, default=0)
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--repeat", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    try:
        import torch  # noqa: F401
        import torch_npu
    except ImportError as exc:
        return _emit_error(f"torch/torch_npu unavailable: {exc}")

    import os
    os.environ.setdefault("ASCEND_DEVICE_ID", str(args.device))
    torch_npu.npu.set_device(args.device)

    try:
        kernel_fn = resolve_callable(args.callable_symbol)
    except Exception as exc:
        return _emit_error(f"cannot resolve callable {args.callable_symbol!r}: {exc!r}")

    try:
        golden_raw = load_golden_raw(args.golden_module, args.golden_entry)
    except Exception as exc:
        return _emit_error(f"golden load failed: {exc!r}")

    try:
        cases = load_cases(args.cases_csv)
    except OSError as exc:
        return _emit_error(f"cannot read cases csv: {exc!r}")
    if not cases:
        return _emit_error(f"no cases parsed from {args.cases_csv}")

    per_case = []
    for case in cases:
        entry = {
            "case_id": case["case_id"],
            "dtype": case["dtype"],
            "shape": list(case["shape"]),
            "kernel": None,
            "torch_npu": None,
            "speedup": None,
            "faster": None,
            "kernel_error": None,
            "ref_error": None,
        }
        try:
            x_np = gen_input(case["shape"], *case["value_range"], args.seed)
            x_kernel = to_npu_tensor(x_np, case["dtype"])
            x_ref = to_npu_tensor(x_np, case["dtype"])  # 独立副本，防交叉污染
            attrs = case["attrs"]
        except Exception as exc:
            entry["kernel_error"] = f"input preparation failed: {exc!r}"
            per_case.append(entry)
            continue

        try:
            entry["kernel"] = time_call(
                lambda: kernel_fn(x_kernel, **attrs), args.warmup, args.repeat)
        except Exception as exc:
            entry["kernel_error"] = repr(exc)

        golden_kwargs = _bind_golden_kwargs(golden_raw, attrs)
        try:
            entry["torch_npu"] = time_call(
                lambda: golden_raw(x_ref, **golden_kwargs), args.warmup, args.repeat)
        except Exception as exc:
            entry["ref_error"] = repr(exc)

        if entry["kernel"] and entry["torch_npu"]:
            k = entry["kernel"]["mean_us"]
            r = entry["torch_npu"]["mean_us"]
            if k > 0:
                entry["speedup"] = r / k
                entry["faster"] = k < r
        per_case.append(entry)

    report = {
        "op_symbol": args.callable_symbol,
        "golden_entry": args.golden_entry,
        "golden_module": args.golden_module,
        "device": args.device,
        "warmup": args.warmup,
        "repeat": args.repeat,
        "seed": args.seed,
        "per_case": per_case,
    }
    report.update(aggregate(per_case))
    report["ok"] = report["verdict"] == "measured"

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    one_liner = {
        "ok": report["ok"],
        "verdict": report["verdict"],
        "kernel_mean_us": report.get("kernel_mean_us"),
        "torch_npu_mean_us": report.get("torch_npu_mean_us"),
        "geo_speedup": report.get("geo_speedup"),
        "faster_cases": report.get("faster_cases"),
        "complete_cases": report["complete_cases"],
        "total_cases": report["total_cases"],
        "artifact": str(out),
    }
    if report["verdict"] == "no":
        one_liner["reason"] = report.get("reason")
    print(json.dumps(one_liner, ensure_ascii=False))
    if report["verdict"] == "measured":
        print(
            f"perf: kernel_mean={report['kernel_mean_us']:.2f}us "
            f"torch_npu_mean={report['torch_npu_mean_us']:.2f}us "
            f"geo_speedup={report['geo_speedup']:.3f} "
            f"faster={report['faster_cases']}/{report['complete_cases']}"
        )
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
