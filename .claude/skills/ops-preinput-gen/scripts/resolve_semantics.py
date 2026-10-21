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

"""算子名 → 语义事实包（Step 1 的机械部分）。

不猜签名：优先从 PyTorch **自省**取权威事实，而不是靠记忆或网页。
  1. `torch.ops.aten.<name>.default._schema` —— ATen 权威签名（参数名/类型/默认值）
  2. `torch.<name>` / `torch.nn.functional.<name>` / `Tensor.<name>` —— golden 可调用体
  3. 空跑探测 —— 定义域、dtype 实际支持面、输出 dtype/shape 关系
  4. 先例检索（可选）—— 若指定了既有算子库目录，找同名/同类算子以复用其设计

输出 JSON 供生成侧填 5 个文件；探测不到的字段留 null，由模型据文档补全并标注来源。
本脚本**不依赖任何外部算子库**即可工作，先例检索纯属加分项。

用法：
    resolve_semantics.py aten_abs
    resolve_semantics.py aten_hardswish --precedent-dir <既有算子库>   # 可选
"""

import argparse
import inspect
import json
import os
import re
import sys

# aten 常见别名 → 规范名（PyTorch 里 *_ 别名与同义名很多）
ALIASES = {
    "absolute": "abs", "arccos": "acos", "arcsin": "asin", "arctan": "atan",
    "arctan2": "atan2", "arccosh": "acosh", "arcsinh": "asinh",
    "arctanh": "atanh", "clip": "clamp", "divide": "div", "multiply": "mul",
    "subtract": "sub", "true_divide": "div", "greater": "gt",
    "greater_equal": "ge", "less": "lt", "less_equal": "le",
    "not_equal": "ne", "negative": "neg", "fix": "trunc",
    "concat": "cat", "row_stack": "vstack", "swapaxes": "transpose",
}

FLOAT_PROBE = ["float32", "float16", "bfloat16"]
INT_PROBE = ["int8", "uint8", "int32", "int64", "bool"]

# 语义类别 → proto.operator.category（13 类全集见 references/format-contract.md §4）
CATEGORY_HINTS = {
    "elementwise": "Elementwise", "activation": "Elementwise",
    "reduction": "Reduction", "norm": "Normalization",
    "matmul": "Contraction", "conv": "Contraction",
    "sort": "SortSelect", "topk": "SortSelect",
    "gather": "IndexGather", "scatter": "ScatterUpdate",
    "transpose": "LayoutTransform", "broadcast": "Broadcast",
}


def normalize(op_name):
    """aten_abs / aten.abs / Abs / abs_ → ('abs', 'aten_abs')。"""
    raw = op_name.strip()
    n = raw
    for pre in ("aten_", "aten.", "aten::", "cann_bench.", "npu_"):
        if n.startswith(pre):
            n = n[len(pre):]
    n = n.rstrip("_")                      # 原地版 abs_ → abs
    n = re.sub(r"(?<!^)(?=[A-Z])", "_", n).lower() if re.search(r"[a-z][A-Z]", n) else n.lower()
    return ALIASES.get(n, n), raw


def aten_schemas(name):
    import torch
    try:
        pk = getattr(torch.ops.aten, name)
    except AttributeError:
        return []
    out = []
    for ov in pk.overloads():
        try:
            s = str(getattr(pk, ov)._schema)
        except Exception:                                    # noqa: BLE001
            continue
        if ".out" in s.split("(")[0] or "Tensor(a!)" in s:   # 跳过 out= / inplace 变体
            continue
        out.append({"overload": ov, "schema": s})
    return out


def parse_aten_schema(schema):
    """aten::gelu(Tensor self, *, str approximate="none") -> Tensor → 结构化参数表。"""
    m = re.match(r"[\w:]+\((.*)\)\s*->\s*(.+)$", schema.strip())
    if not m:
        return None
    args_s, ret = m.group(1), m.group(2).strip()
    args = []
    for tok in re.split(r",(?![^\[\(]*[\]\)])", args_s):
        tok = tok.strip()
        if not tok or tok == "*":
            continue
        default = None
        if "=" in tok:
            tok, default = [x.strip() for x in tok.split("=", 1)]
        parts = tok.split()
        if len(parts) < 2:
            continue
        args.append({"type": " ".join(parts[:-1]), "name": parts[-1], "default": default})
    n_out = len([x for x in re.split(r",\s*", ret.strip("()")) if x]) if ret.startswith("(") else 1
    return {"args": args, "returns": ret, "n_outputs": n_out}


def find_callable(name):
    """定位可用于 golden 的 python 级实现，按优先级返回候选列表。"""
    import torch
    cands = []
    for mod, label in ((torch, "torch"), (torch.nn.functional, "torch.nn.functional")):
        f = getattr(mod, name, None)
        if callable(f):
            try:
                sig = str(inspect.signature(f))
            except (TypeError, ValueError):
                sig = "(...)"      # C 实现的内建，签名不可自省
            cands.append({"path": f"{label}.{name}", "signature": sig})
    if hasattr(torch.Tensor, name):
        cands.append({"path": f"Tensor.{name}", "signature": "(self, ...)"})
    return cands


def probe_dtypes(name, n_tensor_args=1):
    """在 CPU 上小张量空跑，探测各 dtype 是否可算 + 输出 dtype。

    注意：CPU 支持面 ≠ NPU 支持面。CPU 探测只用于「定义域/输出 dtype」取证；
    浮点 elementwise 算子的**声明** dtype 集应取 {float16, float32, bfloat16}
    CPU 探不通不代表 NPU 不支持。
    """
    import torch
    fn = None
    for m in (torch, torch.nn.functional):
        if callable(getattr(m, name, None)):
            fn = getattr(m, name)
            break
    if fn is None:
        return {}
    res = {}
    for dt in FLOAT_PROBE + INT_PROBE:
        td = getattr(torch, dt, None)
        if td is None:
            continue
        try:
            if dt == "bool":
                args = [torch.ones(4, dtype=td)] * n_tensor_args
            elif dt in INT_PROBE:
                args = [torch.ones(4, dtype=td)] * n_tensor_args
            else:
                args = [torch.rand(4, dtype=td) + 0.5] * n_tensor_args
            with torch.no_grad():
                o = fn(*args)
            o0 = o[0] if isinstance(o, (tuple, list)) else o
            res[dt] = {"ok": True, "out_dtype": str(o0.dtype).replace("torch.", "")}
        except Exception as e:                               # noqa: BLE001
            res[dt] = {"ok": False, "err": f"{type(e).__name__}: {str(e)[:80]}"}
    return res


def probe_domain(name):
    """探测定义域：在若干区间上看是否产生 nan/inf，用来定 value_range。"""
    import torch
    fn = None
    for m in (torch, torch.nn.functional):
        if callable(getattr(m, name, None)):
            fn = getattr(m, name)
            break
    if fn is None:
        return {}
    probes = {
        "negative": torch.tensor([-5.0, -1.0, -0.5]),
        "zero": torch.tensor([0.0]),
        "unit": torch.tensor([0.1, 0.5, 0.9]),
        "gt_one": torch.tensor([1.5, 10.0, 100.0]),
        "large": torch.tensor([1e4, 1e8]),
    }
    out = {}
    for k, t in probes.items():
        try:
            with torch.no_grad():
                y = fn(t)
            y0 = y[0] if isinstance(y, (tuple, list)) else y
            out[k] = {"finite": bool(torch.isfinite(y0).all()),
                      "has_nan": bool(torch.isnan(y0).any())}
        except Exception as e:                               # noqa: BLE001
            out[k] = {"error": f"{type(e).__name__}: {str(e)[:60]}"}
    return out


def find_precedents(name, precedent_dir):
    """可选：在一个既有算子库里找同名/同类先例，有则复用其设计而非新造。

    目录结构假定为 `<root>/<分组>/<算子名>/`。未指定或不存在时直接返回空，
    不影响主流程 —— 骨架与规范都已内置在 references/ 里。
    """
    if not precedent_dir or not os.path.isdir(precedent_dir):
        return {"exact": None, "all_ops": []}
    exact = None
    all_ops = []
    for lvl in sorted(os.listdir(precedent_dir)):
        d = os.path.join(precedent_dir, lvl)
        if not os.path.isdir(d):
            continue
        for op in sorted(os.listdir(d)):
            p = os.path.join(d, op)
            if os.path.isdir(p):
                all_ops.append(f"{lvl}/{op}")
                if op == name:
                    exact = f"{lvl}/{op}"
    return {"exact": exact, "all_ops": all_ops}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("op_name")
    ap.add_argument("--precedent-dir", default=None,
                    help="可选：既有算子库根目录（<root>/<分组>/<算子名>/），用于复用先例")
    ap.add_argument("--n-tensor-args", type=int, default=1,
                    help="探测时构造几个张量入参（二元算子传 2）")
    args = ap.parse_args()

    name, raw = normalize(args.op_name)
    out = {"input_name": raw, "normalized": name,
           "alias_applied": ALIASES.get(re.sub(r"^aten[_.]", "", raw).rstrip("_").lower())}
    try:
        import torch
        out["torch_version"] = torch.__version__
    except ImportError:
        out["error"] = "torch 不可用，无法自省；请改用文档路径并标注来源"
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1

    schemas = aten_schemas(name)
    out["aten_schemas"] = schemas
    out["parsed_schema"] = parse_aten_schema(schemas[0]["schema"]) if schemas else None
    out["callables"] = find_callable(name)
    out["dtype_probe_cpu"] = probe_dtypes(name, args.n_tensor_args)
    out["domain_probe"] = probe_domain(name)
    out["precedents"] = find_precedents(name, args.precedent_dir)

    ok_float = [d for d in FLOAT_PROBE
                if out["dtype_probe_cpu"].get(d, {}).get("ok")]
    out["recommendation"] = {
        "declare_dtypes": FLOAT_PROBE if ok_float else None,
        "note": "浮点 elementwise 算子一律声明 {float16, float32, bfloat16}；"
                "CPU 探测仅作定义域取证，不足以缩小 NPU 声明面。",
        "reuse_skeleton": "references/case-design.md §2 的 L1 骨架"
                          if not schemas or not out["parsed_schema"]
                          or len(out["parsed_schema"]["args"]) <= 2 else None,
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
