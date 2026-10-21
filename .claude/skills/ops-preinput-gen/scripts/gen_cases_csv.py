#!/usr/bin/python3
# coding=utf-8

# ----------------------------------------------------------------------------
# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# This program is free software, you can redistribute it and/or modify it under the terms and conditions of
# CANN Open Software License Agreement Version 2.0 (the "License").
# Please refer to the License for details. You may not use this file except in compliance with the License.
# THIS SOFTWARE IS PROVIDED ON AN "AS IS" BASIS, WITHOUT WARRANTIES OF ANY KIND, EITHER EXPRESS OR IMPLIED,
# INCLUDING BUT NOT LIMITED TO NON-INFRINGEMENT, MERCHANTABILITY, OR FITNESS FOR A PARTICULAR PURPOSE.
# See LICENSE in the root of the software repository for the full text of the License.
# ----------------------------------------------------------------------------

"""cases.yaml → cases.csv 机械派生。

cases.yaml 是唯一事实来源；cases.csv 一律由本脚本生成，禁止手写。
input_shape / dtype / value_range 三列可完全机械派生。

用法：
    gen_cases_csv.py <op_dir>...          # 就地写 cases.csv
    gen_cases_csv.py --check <op_dir>...  # 只校验现有 cases.csv 是否与 yaml 一致
"""

import argparse
import csv
import json
import sys

from preinput_lib import (cases_to_csv_rows, deep_from_csv, eq_nan, load_cases,
                          note_core, write_csv)


def check_one(op_dir):
    """返回不一致的 (case_id, 列名) 列表。

    note 列只比对 `|` 之前的设计 slug：`baseline_kernels: ...` 尾巴是下游 profiling
    回填的度量注解，不属于生成器职责。
    """
    cases = load_cases(op_dir)
    want = cases_to_csv_rows(cases)
    with open(f"{op_dir}/cases.csv", newline="", encoding="utf-8") as f:
        got = list(csv.reader(f))
    bad = []
    if got and got[0] != want[0]:
        bad.append(("header", f"{got[0]} != {want[0]}"))
    for w, g in zip(want[1:], got[1:]):
        for i, col in enumerate(want[0]):
            if col == "note":
                if note_core(w[i]) != note_core(g[i]):
                    bad.append((w[1], col))
            elif col in ("operator", "case_id"):
                if w[i] != g[i]:
                    bad.append((w[1], col))
            else:
                try:
                    if not eq_nan(deep_from_csv(json.loads(w[i])),
                                  deep_from_csv(json.loads(g[i]))):
                        bad.append((w[1], col))
                except (json.JSONDecodeError, IndexError):
                    bad.append((w[1], f"{col}(unparsable)"))
    if len(got) - 1 != len(want) - 1:
        bad.append(("rowcount", f"csv={len(got)-1} yaml={len(want)-1}"))
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("op_dirs", nargs="+")
    ap.add_argument("--check", action="store_true", help="只校验，不写文件")
    args = ap.parse_args()

    rc = 0
    for d in args.op_dirs:
        d = d.rstrip("/")
        try:
            if args.check:
                bad = check_one(d)
                if bad:
                    rc = 1
                    print(f"FAIL {d}: {len(bad)} 处不一致 -> {bad[:6]}")
                else:
                    print(f"OK   {d}")
            else:
                write_csv(f"{d}/cases.csv", cases_to_csv_rows(load_cases(d)))
                print(f"WROTE {d}/cases.csv")
        except (OSError, ValueError, KeyError) as e:
            rc = 1
            print(f"ERROR {d}: {type(e).__name__}: {e}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
