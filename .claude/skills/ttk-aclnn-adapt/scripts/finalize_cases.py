#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把最终运行结果回填到产物目录的 cases.csv。

产物目录约定：
  <WORKDIR>/golden.py                修正后的 TestSpec/golden
  <WORKDIR>/cases.csv                TTK 用例（末尾追加 pass / note 两列）
  <WORKDIR>/debug/                   运行结果、dump、日志、契约表等中间产物

本脚本负责：
  - pass  列：取 TTK 结果 CSV 的 precision_status（PASS / FAIL / SKIP；
              GOLDEN_FAILURE / COMPARE_FAILURE / FAILURE 等运行期失败归一为 FAIL，
              原始值打印出来，具体原因写进 note）
  - note 列：保留 cases.csv 中已有内容；可用 --notes 指定的 JSON 覆盖/补充
  - 清理产物根目录的 __pycache__/（跑 --plugin <WORKDIR> 时 Python 的副产物）

用法：
  python3 finalize_cases.py --cases <WORKDIR>/cases.csv \
      --result <WORKDIR>/debug/result.csv [--notes <WORKDIR>/debug/notes.json]

notes.json 结构（UTF-8）：
  {
    "<case_name>": "失败为 float32 golden 在近零抵消点的舍入，无法规避（fp64 复算 golden 自身同样超差）",
    "<another_case>": "同上",
    "default": ""
  }
"""

import argparse
import csv
import json
import os
import shutil
import sys

PASS_COL = "pass"
NOTE_COL = "note"

# TTK 的 precision_status 只有 PASS/FAIL/SKIP 三种正常值；其余（GOLDEN_FAILURE、
# COMPARE_FAILURE、FAILURE、INPUT_GEN_FAILURE……）都表示该用例没能完成精度比对，
# 对交付来说一律算 FAIL，原始值由脚本打印，原因写进 note 列。
NORMAL_STATUS = ("PASS", "FAIL", "SKIP")


def _normalize_status(raw):
    value = (raw or "").strip()
    if value in NORMAL_STATUS:
        return value, value
    return "FAIL", value


def _load_rows(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader), list(reader.fieldnames or [])


def _load_notes(path):
    if not path:
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise SystemExit(f"[ERROR] notes file must contain a JSON object: {path}")
    return {str(k): str(v) for k, v in data.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--cases", required=True, help="产物目录下的 cases.csv（原地回填）")
    parser.add_argument("--result", required=True, help="TTK 结果 CSV（使用 -o 输出）")
    parser.add_argument("--notes", help="可选：case -> 分析结论 的 JSON 文件")
    parser.add_argument("--keep-pycache", action="store_true",
                        help="保留产物根目录的 __pycache__/（默认清理）")
    parser.add_argument("--dry-run", action="store_true", help="只打印结果，不写文件")
    args = parser.parse_args()

    if not os.path.isfile(args.cases):
        print(f"[ERROR] cases file not found: {args.cases}", file=sys.stderr)
        return 2
    if not os.path.isfile(args.result):
        print(f"[ERROR] result file not found: {args.result}", file=sys.stderr)
        return 2

    cases, fields = _load_rows(args.cases)
    results, result_fields = _load_rows(args.result)
    if "testcase_name" not in fields or "testcase_name" not in result_fields:
        print("[ERROR] both CSVs must contain testcase_name", file=sys.stderr)
        return 2
    if "precision_status" not in result_fields:
        print("[ERROR] result CSV has no precision_status column", file=sys.stderr)
        return 2

    status = {row["testcase_name"]: (row.get("precision_status") or "").strip() for row in results}
    notes = _load_notes(args.notes)

    missing = [row["testcase_name"] for row in cases if row["testcase_name"] not in status]
    if missing:
        print(f"[WARN] {len(missing)} case(s) not found in result CSV, pass 列留空: {missing}",
              file=sys.stderr)

    # 标准列在前，pass/note 追加在末尾；若已存在则保持原位置
    base = [c for c in fields if c not in (PASS_COL, NOTE_COL)]
    out_fields = base + [PASS_COL, NOTE_COL]

    counts = {"PASS": 0, "FAIL": 0, "SKIP": 0, "": 0}
    abnormal = []
    for row in cases:
        raw = status.get(row["testcase_name"], "")
        passed, raw = _normalize_status(raw)
        if raw and passed == "FAIL" and raw != "FAIL":
            abnormal.append((row["testcase_name"], raw))
        row[PASS_COL] = passed
        counts[passed if passed in counts else ""] += 1
        existing = row.get(NOTE_COL) or ""
        if row["testcase_name"] in notes:
            note = notes[row["testcase_name"]]
        elif raw and raw not in NORMAL_STATUS:
            # 运行期失败不是精度结论，note 里至少留下原始状态便于追日志
            note = f"精度比对未完成：precision_status={raw}（见 debug/full_run.log）"
        else:
            note = existing or notes.get("default", "")
        row[NOTE_COL] = note

    print(f"cases={len(cases)} pass={counts['PASS']} fail={counts['FAIL']} "
          f"skip={counts['SKIP']} missing={counts['']}")
    for name, raw in abnormal:
        print(f"[WARN] {name}: precision_status={raw} 归一为 pass=FAIL", file=sys.stderr)
    for row in cases:
        print(f"  {row['testcase_name']:<24} {row[PASS_COL]:<5} {row[NOTE_COL]}")

    if args.dry_run:
        return 0

    with open(args.cases, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=out_fields)
        writer.writeheader()
        writer.writerows(cases)
    print(f"updated: {args.cases}")

    # --plugin <WORKDIR> 会让 Python 在产物根目录留下 __pycache__/，交付前清掉
    if not args.keep_pycache:
        pycache = os.path.join(os.path.dirname(os.path.abspath(args.cases)), "__pycache__")
        if os.path.isdir(pycache):
            shutil.rmtree(pycache)
            print(f"removed: {pycache}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
