#!/usr/bin/env python3
# -*- coding: UTF-8 -*-
"""
Example: Launch exp kernel — launcher.run_case(case, golden_fn).

Usage::

    python3 run_exp_test.py --task-dir /path/to/cann-bench --device_id 7
    python3 run_exp_test.py --task-dir /path/to/cann-bench --case 1,6,12
"""

import argparse
import os
import sys

_CUR = os.path.dirname(os.path.abspath(__file__))
_KL_ROOT = os.path.dirname(os.path.dirname(_CUR))
sys.path.insert(0, _KL_ROOT)

from KernelLaunch import (
    KernelLauncher,
    find_task_asset,
    load_cases,
    load_golden,
    setup_log_separation,
)

setup_log_separation(log_file="log_exp.log", result_file="result_exp.log")

OP_NAME = "exp"


def main():
    parser = argparse.ArgumentParser(description="Kernel exp test — run_case")
    parser.add_argument("--cannbench-dir", type=str, required=True,
                        help="cann-bench task root (e.g. .../cann-bench)")
    parser.add_argument("--device_id", type=int, default=0)
    parser.add_argument("--case", type=str, default=None)
    args = parser.parse_args()

    # --- golden + cases -------------------------------------------------------
    golden_fn = load_golden(
        find_task_asset(args.cannbench_dir, OP_NAME, "golden.py"),
        entry=OP_NAME, input_type="torch",
    )
    cases = load_cases(
        find_task_asset(args.cannbench_dir, OP_NAME, "cases.csv"),
    )
    print(f"[{OP_NAME}] golden + {len(cases)} cases loaded\n")

    # --- filter ---------------------------------------------------------------
    case_ids = {int(c) for c in args.case.split(",")} if args.case else None

    launcher = KernelLauncher(OP_NAME, device_id=args.device_id)
    results = []

    for c in cases:
        cid = c["case_id"]
        if case_ids and cid not in case_ids:
            continue

        print(f"  #{cid:3d} shape={str(c['shape']):28s} attrs={c['attrs']}")

        result = launcher.run_case(c, golden_fn)
        results.append((cid, result))

        marker = "PASS" if result["passed"] else "FAIL"
        print(f"       [{marker}] "
              f"MERE={result['mere']:.2e} MARE={result['mare']:.2e} "
              f"max_diff={result['max_diff']:.2e}")
        for po in result["per_output"]:
            e = f" [{po['error_msg']}]" if po.get("error_msg") else ""
            print(f"       out[{po['index']}] {po['dtype']:6s} "
                  f"passed={po['passed']} thr={po['threshold']:.2e} "
                  f"MERE={po['mere']:.2e} MARE={po['mare']:.2e}{e}")

    launcher.close()

    n_pass = sum(1 for _, r in results if r["passed"])
    n_total = len(results)
    print(f"\n{'='*60}\n  Passed: {n_pass}/{n_total}")
    for cid, r in results:
        if not r["passed"]:
            print(f"  FAIL #{cid}: mare={r['mare']:.2e} {r.get('error_msg','')}")
    print(f"[{'ALL PASSED' if n_pass == n_total else 'SOME FAILED'}]")


if __name__ == "__main__":
    main()
