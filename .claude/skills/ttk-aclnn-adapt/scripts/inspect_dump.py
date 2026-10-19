#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查一个用例的 dump 目录（--dump in,out,golden --dump-format npy）。

用法：
    python3 .claude/skills/ttk-aclnn-adapt/scripts/inspect_dump.py <dump_dir>
    python3 .claude/skills/ttk-aclnn-adapt/scripts/inspect_dump.py <dump_dir> --near-zero 1e-5

<dump_dir> 通常是 <WORKDIR>/debug/dump/<case_name>。

对每个输出槽（output_*/golden_* 配对）打印：
  - shape / dtype / 元素数
  - 最大绝对误差、最大相对误差、超差元素个数
  - 误差最大的若干元素（golden 值、绝对误差、relative、是否近零）
并统计"近零失败"占比——近零抵消点是 stat_rel_err 类判据的典型伪失败来源。
"""

import argparse
import glob
import os
import re
import sys

import numpy as np

_PAIR_RE = re.compile(r"^(output|golden)_(\d+)_([A-Za-z0-9]+)\.npy$")

# 与 ttk/core_modules/common/comparison/stat_rel_err.py 保持一致
_NOISE_FLOOR = {
    "float16": 2.0**-11,
    "bfloat16": 2.0**-8,
    "float32": 2.0**-23,
}


def _collect(dump_dir):
    pairs = {}
    for path in sorted(glob.glob(os.path.join(dump_dir, "*.npy"))):
        m = _PAIR_RE.match(os.path.basename(path))
        if not m:
            continue
        role, idx, dtype = m.group(1), int(m.group(2)), m.group(3)
        pairs.setdefault(idx, {}).setdefault(role, {})[dtype] = path
    return pairs


def _newest(paths):
    return max(paths, key=lambda p: os.path.getmtime(p))


def _pick_output(index, roles):
    """每个槽取本次运行落下的 output/golden（最新 mtime），并提示过期文件。

    注意：golden 的 dtype 不一定等于 output dtype——`--golden-mode Promote`
    （mixed/mix_tolerance/cross_check 默认触发）会把 golden 升到 float32，
    而 output 按算子声明 dtype 落盘。因此这里按*槽位*配对，不按 dtype。"""
    outputs = roles.get("output") or {}
    goldens = roles.get("golden") or {}
    if not outputs:
        return None, None
    out_path = _newest(outputs.values())
    out_mtime = os.path.getmtime(out_path)
    stale = [
        p
        for role in ("output", "golden")
        for p in (roles.get(role) or {}).values()
        if out_mtime - os.path.getmtime(p) > 300
    ]
    if stale:
        print(f"  [WARN] slot {index} 存在过期 dump 文件（比本次 output 早 5 分钟以上），"
              f"建议先删 dump/<case> 再重跑：")
        for p in stale:
            print(f"         {p}")
    gold_path = _newest(goldens.values()) if goldens else None
    if gold_path is not None:
        out_dtype = next(d for d, p in outputs.items() if p == out_path)
        gold_dtype = next(d for d, p in goldens.items() if p == gold_path)
        if out_dtype != gold_dtype:
            print(f"  note: output dtype={out_dtype}, golden dtype={gold_dtype} "
                  f"(Promote/声明差异)，以下按 float64 对齐比较")
    return out_path, gold_path


def _analyze(index, out_path, gold_path, near_zero, topk):
    raw_out = np.load(out_path)
    out = raw_out.astype(np.float64).reshape(-1)
    gold = np.load(gold_path).astype(np.float64).reshape(-1)
    if out.size != gold.size:
        print(f"  [WARN] size mismatch: output={out.size} golden={gold.size}")
    n = min(out.size, gold.size)
    out, gold = out[:n], gold[:n]

    finite = np.isfinite(out) & np.isfinite(gold)
    nan_out = int(np.count_nonzero(~np.isfinite(out)))
    nan_gold = int(np.count_nonzero(~np.isfinite(gold)))

    abs_err = np.where(finite, np.abs(out - gold), np.nan)
    denom = np.maximum(np.abs(gold), np.finfo(np.float64).tiny)
    rel_err = np.where(finite, abs_err / denom, np.nan)

    # stat_rel_err 口径：分母按输出 dtype 的 1 ulp 设噪声地板（见 comparison/stat_rel_err.py）
    floor = _NOISE_FLOOR.get(str(raw_out.dtype), 1e-7)
    floor_rel = np.where(finite, abs_err / np.maximum(np.abs(gold), floor), np.nan)

    bad = finite & (abs_err > 0)
    near = finite & (np.abs(gold) < near_zero)
    near_bad = bad & near

    print(f"  elements={n} dtype_out={raw_out.dtype} near_zero={near_zero}")
    if nan_out or nan_gold:
        print(f"  non-finite: output={nan_out} golden={nan_gold}")
    print(f"  max_abs_err={np.nanmax(abs_err) if n else 0:.6e}  "
          f"max_rel_err={np.nanmax(rel_err) if n else 0:.6e}")
    print(f"  stat_rel_err 口径 (floor={floor:.3e}): mere={np.nanmean(floor_rel) if n else 0:.3e}  "
          f"mare={np.nanmax(floor_rel) if n else 0:.3e}")
    print(f"  diff_elements={int(np.count_nonzero(bad))}  "
          f"diff_in_near_zero={int(np.count_nonzero(near_bad))} "
          f"({100.0 * np.count_nonzero(near_bad) / max(1, np.count_nonzero(bad)):.1f}% of diffs)")

    finite_rel = np.where(finite, floor_rel, 0.0)
    worst = int(np.argmax(finite_rel))
    if finite_rel[worst] > 0:
        print(f"  worst rel (stat 口径): [{worst}] out={out[worst]:.9g} golden={gold[worst]:.9g} "
              f"abs={abs_err[worst]:.3e} rel={finite_rel[worst]:.3e} "
              f"{'near-zero 主导' if abs(gold[worst]) < near_zero else ''}")
        without = finite_rel.copy()
        without[worst] = 0.0
        print(f"  去掉该点后 mare={without.max():.3e}"
              f"{' → 整张用例由该点决定' if without.max() < finite_rel[worst] / 10 else ''}")

    order = np.argsort(-np.nan_to_num(abs_err, nan=-1.0))[:topk]
    print(f"  top-{topk} abs errors:")
    for i in order:
        if not np.isfinite(abs_err[i]) or abs_err[i] == 0:
            break
        flag = "near-zero" if near[i] else ""
        print(f"    [{i}] out={out[i]:.9g} golden={gold[i]:.9g} "
              f"abs={abs_err[i]:.3e} rel={rel_err[i]:.3e} {flag}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dump_dir", help="dump 目录，如 <WORKDIR>/debug/dump/<case_name>")
    parser.add_argument("--near-zero", type=float, default=1e-4,
                        help="近零判定阈值（|golden| < 该值），默认 1e-4")
    parser.add_argument("--topk", type=int, default=10, help="每槽打印的最大误差元素数")
    args = parser.parse_args()

    if not os.path.isdir(args.dump_dir):
        print(f"[ERROR] not a directory: {args.dump_dir}", file=sys.stderr)
        return 2

    pairs = _collect(args.dump_dir)
    if not pairs:
        print(f"[ERROR] no output_*/golden_*.npy in {args.dump_dir}", file=sys.stderr)
        print("Hint: 用 --dump in,out,golden --dump-format npy 重新跑该用例。", file=sys.stderr)
        return 2

    for idx in sorted(pairs):
        roles = pairs[idx]
        print(f"slot {idx}:")
        out_path, gold_path = _pick_output(idx, roles)
        if out_path is None or gold_path is None:
            missing = "output" if out_path is None else "golden"
            print(f"  [SKIP] missing {missing} file")
            continue
        _analyze(idx, out_path, gold_path, args.near_zero, args.topk)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
