#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打印 TTK 解析到的 aclnn 接口签名（张量槽顺序 / 标量 / 其他属性）。

用法：
    python3 .claude/skills/ttk-aclnn-adapt/scripts/dump_aclnn_signature.py <API>
    python3 .claude/skills/ttk-aclnn-adapt/scripts/dump_aclnn_signature.py <API> --json

例如 API 为 aclnnXxx 时传 aclnnXxx。输出中的 tensor slot 序号即 CSV
tensor_view_shapes 的顺序；标量/other 对应 scalar_dtypes / attributes。
需要 CANN 环境（会读 aclnn 头文件）。
"""

import argparse
import json
import os
import sys


def _repo_root() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    # <repo>/.claude/skills/ttk-aclnn-adapt/scripts
    return os.path.abspath(os.path.join(here, "..", "..", "..", ".."))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("api_name", help="aclnn 接口名，如 aclnnXxx")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args()

    root = _repo_root()
    sys.path.insert(0, root)

    from ttk.core_modules.aclnn.info_keeper import OpApiInfoKeeper

    keeper = OpApiInfoKeeper()
    info = keeper.info_of(args.api_name)
    if info is None:
        print(f"[ERROR] {args.api_name} not found in aclnn headers.", file=sys.stderr)
        print("Check TTK_OP_API_HEADER_PATH / installed aclnnop headers.", file=sys.stderr)
        return 2

    rows = []
    tensor_slot = 0
    for name, meta in info.params.items():
        ptype = meta["type"]
        item = {"name": name, "type": ptype, "default": meta.get("default")}
        if ptype in ("aclTensor*", "aclTensorList*"):
            item["kind"] = "tensor"
            item["slot"] = tensor_slot
            tensor_slot += 1
        elif ptype in ("aclScalar*", "aclScalarList*"):
            item["kind"] = "scalar"
        else:
            item["kind"] = "attribute"
        rows.append(item)

    if args.json:
        print(json.dumps({"api_name": args.api_name, "params": rows}, indent=2, ensure_ascii=False))
        return 0

    print(f"API: {args.api_name}")
    print(f"tensor_count: {tensor_slot}")
    print()
    header = f"{'slot':>4}  {'kind':<10} {'name':<20} type"
    print(header)
    print("-" * len(header))
    for row in rows:
        slot = str(row.get("slot", "")) if row["kind"] == "tensor" else ""
        print(f"{slot:>4}  {row['kind']:<10} {row['name']:<20} {row['type']}")
    print()
    print("CSV tensor_view_shapes / tensor_dtypes 必须按上述 tensor slot 顺序覆盖全部张量（含输出）。")
    print("attributes 形参：" + ", ".join(r["name"] for r in rows if r["kind"] == "attribute"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
