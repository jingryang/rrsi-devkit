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

"""golden 实现（KernelBench 风格 `class Model(nn.Module)`）→ 语义事实包。

这是 golden-driven 模式下 Step 1 的机械部分，对标 name-driven 模式的
`resolve_semantics.py`。区别在于**事实来源相反**：

  - name-driven：算子名 → PyTorch 自省取权威签名 → 反推着写 golden.py
  - golden-driven：**golden 实现本身就是语义唯一事实源** → 先把它拆解成结构化事实，
    再据此把 `Model.forward` 转写成一个可导入的自由函数 golden.py，其余四文件对齐它

本脚本用 `ast` 静态抽取（不依赖 torch 即可跑），可选地在 torch 可用且能构造实例时
做一次运行探测确认 output shape/dtype。输出 JSON 供生成侧填五个文件。

核心拆解：
  - forward 形参（除 self）        → 数据输入（proto.inputs 打头）
  - __init__ 里 self.X = 张量表达式 → **提升为张量输入**（不是烘焙常量！下游要对同一组
    随机输入同时喂 golden 和 kernel 做精度比对，隐藏的随机权重无法跨边界复现）
  - __init__ 里 self.m = nn.<Mod>() 子模块 → 内联成 F.* 泛函，其权重张量也提升为输入
  - __init__ 的标量构造参数           → attrs 或形状决定量
  - forward 里的算子序列               → 命名（按算子组合描述）与定级的依据

用法：
    resolve_golden.py <golden.py>
    resolve_golden.py <golden.py> --init-args num_channels=4 alpha_value=0.25 \\
                       --input-shape 2,4,8 --input-dtype float32
"""

import argparse
import ast
import json
import re
import sys


# ── 子模块 → 它携带的权重张量 + 推理期泛函形式 ───────────────────────────
# key 是 nn.<Module> 的类名；weights 是要提升为输入的张量（按 F.* 的实参顺序）；
# functional 是转写 golden.py 时应采用的推理语义泛函形式（训练态模块一律取 eval 语义）。
SUBMODULE_TABLE = {
    "PReLU": {
        "weights": ["weight"],
        "functional": "F.prelu(x, weight)",
        "note": "weight 形状 (num_parameters,)；num_parameters=1 或通道数 C",
    },
    "Linear": {
        "weights": ["weight", "bias"],
        "functional": "F.linear(x, weight, bias)",
        "note": "weight 形状 (out_features, in_features)，bias (out_features,)",
    },
    "BatchNorm1d": {
        "weights": ["running_mean", "running_var", "weight", "bias"],
        "functional": "F.batch_norm(x, running_mean, running_var, weight, bias, training=False, eps=eps)",
        "note": "推理语义（training=False）；running_var 值域必须为正",
    },
    "BatchNorm2d": {
        "weights": ["running_mean", "running_var", "weight", "bias"],
        "functional": "F.batch_norm(x, running_mean, running_var, weight, bias, training=False, eps=eps)",
        "note": "推理语义（training=False）；running_var 值域必须为正",
    },
    "BatchNorm3d": {
        "weights": ["running_mean", "running_var", "weight", "bias"],
        "functional": "F.batch_norm(x, running_mean, running_var, weight, bias, training=False, eps=eps)",
        "note": "推理语义（training=False）；running_var 值域必须为正",
    },
    "LayerNorm": {
        "weights": ["weight", "bias"],
        "functional": "F.layer_norm(x, normalized_shape, weight, bias, eps=eps)",
        "note": "normalized_shape 取自构造实参",
    },
    "GroupNorm": {
        "weights": ["weight", "bias"],
        "functional": "F.group_norm(x, num_groups, weight, bias, eps=eps)",
        "note": "num_groups 取自构造实参；C % num_groups == 0",
    },
    "Conv2d": {
        "weights": ["weight", "bias"],
        "functional": "F.conv2d(x, weight, bias, stride, padding)",
        "note": "weight 形状 (C_out, C_in, K_h, K_w)，bias (C_out,)",
    },
    "Embedding": {
        "weights": ["weight"],
        "functional": "F.embedding(x, weight)",
        "note": "weight 形状 (num_embeddings, embedding_dim)；x 为整型索引",
    },
}

# 张量构造工厂：self.X = 这些之一 → param_tensor（提升为输入）
TENSOR_FACTORIES = {"Parameter", "tensor", "randn", "rand", "zeros", "ones",
                    "empty", "full", "randint", "arange"}

# forward 里主导 category 判定的算子
MASK_OPS = {"where", "isin", "masked_fill", "masked_fill_", "masked_select", "eq",
            "gt", "lt", "ge", "le", "ne"}
REDUCE_OPS = {"sum", "mean", "max", "min", "prod", "amax", "amin", "norm",
              "logsumexp", "argmax", "argmin"}


def _attr_chain(node):
    """torch.nn.functional.elu / F.elu / x.triu → 末端算子名字符串。"""
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Name):
        return node.id
    return None


def _literal(node):
    """尽力把 ast 常量/简单表达式还原成 python 值，失败返回源码串。"""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError, TypeError):
        try:
            return ast.unparse(node)
        except Exception:                                    # noqa: BLE001
            return None


class ModelVisitor(ast.NodeVisitor):
    """抽取 class Model 的 __init__ / forward 结构。"""

    def __init__(self):
        self.found = False
        self.init_args = []          # [(name, default)]
        self.forward_args = []       # 除 self 外的形参名
        self.stateful = []           # self.X = … 的分类结果
        self.op_sequence = []        # forward 里按序出现的算子名
        self.has_inplace_index = False
        self.n_return = 1

    def visit_ClassDef(self, node):
        if node.name != "Model":
            self.generic_visit(node)
            return
        self.found = True
        for item in node.body:
            if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                self._parse_init(item)
            elif isinstance(item, ast.FunctionDef) and item.name == "forward":
                self._parse_forward(item)

    # ── __init__ ──
    def _parse_init(self, fn):
        args = fn.args.args[1:]      # 去 self
        defaults = fn.args.defaults
        pad = [None] * (len(args) - len(defaults))
        for a, d in zip(args, pad + list(defaults)):
            self.init_args.append((a.arg, _literal(d) if d is not None else None))
        for st in ast.walk(fn):
            if not isinstance(st, ast.Assign):
                continue
            for tgt in st.targets:
                if not (isinstance(tgt, ast.Attribute)
                        and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"):
                    continue
                self._classify_stateful(tgt.attr, st.value)

    def _classify_stateful(self, attr, value):
        if not isinstance(value, ast.Call):
            # self.x = 某个常量/表达式，非张量非模块 —— 记为 other，交给人判断
            self.stateful.append({"attr": attr, "kind": "other",
                                  "expr": _safe_unparse(value)})
            return
        factory = _attr_chain(value.func)
        module_type = _module_type(value.func)
        if module_type in SUBMODULE_TABLE:
            info = SUBMODULE_TABLE[module_type]
            self.stateful.append({
                "attr": attr, "kind": "submodule", "module_type": module_type,
                "ctor_args": [_literal(a) for a in value.args],
                "ctor_kwargs": {k.arg: _literal(k.value) for k in value.keywords},
                "weights": info["weights"], "functional": info["functional"],
                "note": info["note"],
            })
        elif factory in TENSOR_FACTORIES:
            # 记 shape 依据：Parameter(torch.randn(SHAPE)) / tensor(VALUES) / randn(SHAPE)
            shape_hint = _tensor_shape_hint(value)
            self.stateful.append({
                "attr": attr, "kind": "param_tensor", "factory": factory,
                "shape_hint": shape_hint, "expr": _safe_unparse(value),
            })
        else:
            self.stateful.append({"attr": attr, "kind": "submodule_other",
                                  "module_type": module_type or factory,
                                  "expr": _safe_unparse(value)})

    # ── forward ──
    def _parse_forward(self, fn):
        self.forward_args = [a.arg for a in fn.args.args[1:]]
        for node in ast.walk(fn):
            if isinstance(node, ast.Call):
                name = _attr_chain(node.func)
                if name and name not in ("self",):
                    # 过滤掉对 self.submodule(...) 的调用记成子模块算子名
                    if _is_self_attr_call(node.func):
                        self.op_sequence.append(f"self.{name}")
                    else:
                        self.op_sequence.append(name)
            elif isinstance(node, ast.BinOp):
                self.op_sequence.append(_binop_name(node.op))
            elif isinstance(node, ast.Subscript) and isinstance(
                    getattr(node, "ctx", None), ast.Store):
                self.has_inplace_index = True
                self.op_sequence.append("index_assign")
        # 下标赋值也可能出现在 Assign 的 target 上
        for node in ast.walk(fn):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Subscript):
                        self.has_inplace_index = True
            if isinstance(node, ast.Return):
                if isinstance(node.value, ast.Tuple):
                    self.n_return = len(node.value.elts)


def _is_self_attr_call(func):
    return (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)
            and func.value.id == "self")


def _module_type(func):
    """nn.BatchNorm3d / torch.nn.PReLU → 'BatchNorm3d' / 'PReLU'。"""
    name = _attr_chain(func)
    return name


def _tensor_shape_hint(call):
    """从 Parameter(torch.randn(SHAPE)) / torch.tensor(VALUES) 里抠 shape 线索。"""
    # 剥掉 Parameter(...) 外壳，取内层工厂调用
    inner = call
    if _attr_chain(call.func) == "Parameter" and call.args and isinstance(call.args[0], ast.Call):
        inner = call.args[0]
    fac = _attr_chain(inner.func)
    if fac in ("randn", "rand", "zeros", "ones", "empty", "full"):
        # 位置实参即 shape（full 第一个是 shape）
        return [_literal(a) for a in inner.args if not isinstance(a, ast.keyword)]
    if fac in ("tensor",):
        return {"from_values": _literal(inner.args[0]) if inner.args else None}
    return None


def _binop_name(op):
    return {ast.Add: "add", ast.Sub: "sub", ast.Mult: "mul", ast.Div: "div",
            ast.MatMult: "matmul", ast.Pow: "pow", ast.Mod: "mod"}.get(type(op), "binop")


def _safe_unparse(node):
    try:
        return ast.unparse(node)
    except Exception:                                        # noqa: BLE001
        return None


# ── 命名 / 定级 / 分类 ───────────────────────────────────────────────

def _clean_ops(seq):
    """把算子序列归一成用于命名的干净 token 列表（去 self./去比较算子/去重相邻）。"""
    out = []
    for op in seq:
        o = op.replace("self.", "")
        if o in ("binop",):
            continue
        if o == "index_assign":
            o = "mask_zero"
        if out and out[-1] == o:
            continue
        out.append(o)
    return out


def suggest_name(op_seq, stateful):
    """按算子组合描述生成 snake + Pascal 名。"""
    toks = _clean_ops(op_seq)
    # 比较算子（gt/lt…）通常是 where 的谓词，命名时省掉，避免噪声
    toks = [t for t in toks if t not in {"gt", "lt", "ge", "le", "eq", "ne"}]
    if not toks:
        toks = ["fused"]
    snake = "_".join(toks)
    snake = re.sub(r"_+", "_", snake).strip("_")
    pascal = "".join(w.capitalize() for w in snake.split("_"))
    return snake, pascal


def infer_hints(op_seq, forward_args, stateful):
    toks = _clean_ops(op_seq)
    # 张量输入 = forward 数据输入 + 每个 param_tensor + 每个 submodule 的权重张量
    n_tensor_inputs = len(forward_args)
    for s in stateful:
        if s["kind"] == "param_tensor":
            n_tensor_inputs += 1
        elif s["kind"] == "submodule":
            n_tensor_inputs += len(s.get("weights") or [])

    n_ops = len(toks)
    has_reduce = any(t in REDUCE_OPS for t in toks)
    has_mask = any(t in MASK_OPS or t == "mask_zero" for t in toks)

    # 定级：单算子逐元素=L1；单数据输入的短融合/含一层结构=L2；多张量输入或长融合=L3
    extra_inputs = n_tensor_inputs - len(forward_args)
    if n_ops <= 1 and extra_inputs == 0 and not has_reduce:
        difficulty = "L1"
    elif extra_inputs >= 2 or n_ops >= 3 or has_reduce:
        difficulty = "L3"
    else:
        difficulty = "L2"

    # 分类
    if n_ops <= 1 and extra_inputs == 0:
        category = "Elementwise"
    elif has_mask:
        category = "MaskPredicate"
    elif has_reduce:
        category = "Reduction"
    else:
        category = "FusedComposite"

    return {
        "difficulty": difficulty,
        "category": category,
        "n_tensor_inputs": n_tensor_inputs,
        "n_data_inputs": len(forward_args),
        "n_extra_tensor_inputs": extra_inputs,
        "ops": toks,
        "has_reduce": has_reduce,
        "has_mask": has_mask,
    }


def collect_tensor_inputs(forward_args, stateful):
    """把「数据输入 + 提升的权重张量」汇成一张有序输入表（proto.inputs 的雏形）。"""
    inputs = [{"name": a, "role": "data", "source": "forward_arg"} for a in forward_args]
    for s in stateful:
        if s["kind"] == "param_tensor":
            inputs.append({"name": s["attr"], "role": "param",
                           "source": f"self.{s['attr']}", "shape_hint": s.get("shape_hint")})
        elif s["kind"] == "submodule":
            for w in (s.get("weights") or []):
                inputs.append({"name": f"{s['attr']}_{w}", "role": "weight",
                               "source": f"self.{s['attr']}.{w}",
                               "module_type": s["module_type"]})
    return inputs


# ── 可选运行探测 ─────────────────────────────────────────────────────

def run_probe(path, init_args, input_shape, input_dtype):
    """best-effort：实例化 Model → eval → 跑 forward，记 output shape/dtype。

    只有 torch 可用、能构造实例、且给了 input_shape 才做；任何异常都吞掉记进 error。
    """
    out = {"attempted": True}
    try:
        import importlib.util
        import torch
    except ImportError:
        return {"attempted": False, "reason": "torch 不可用"}
    try:
        spec = importlib.util.spec_from_file_location("golden_probe", path)
        mod = importlib.util.module_from_spec(spec)
        sys.dont_write_bytecode = True
        spec.loader.exec_module(mod)
        Model = getattr(mod, "Model")
        m = Model(**(init_args or {}))
        if hasattr(m, "eval"):
            m.eval()
        if not input_shape:
            return {"attempted": True, "reason": "未给 --input-shape，跳过前向"}
        td = getattr(torch, input_dtype or "float32")
        if input_dtype in ("int32", "int64", "int8", "uint8"):
            x = torch.randint(0, 4, tuple(input_shape), dtype=td)
        else:
            x = torch.randn(*input_shape).to(td)
        with torch.no_grad():
            y = m(x)
        ys = y if isinstance(y, (tuple, list)) else (y,)
        out["n_outputs"] = len(ys)
        out["outputs"] = [{"shape": list(o.shape), "dtype": str(o.dtype).replace("torch.", "")}
                          for o in ys if hasattr(o, "shape")]
    except Exception as e:                                   # noqa: BLE001
        out["error"] = f"{type(e).__name__}: {str(e)[:160]}"
    return out


def parse_init_args(pairs):
    """['num_channels=4', 'alpha=0.25'] → {'num_channels': 4, 'alpha': 0.25}。"""
    out = {}
    for p in pairs or []:
        if "=" not in p:
            continue
        k, v = p.split("=", 1)
        try:
            out[k.strip()] = ast.literal_eval(v.strip())
        except (ValueError, SyntaxError):
            out[k.strip()] = v.strip()
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("golden_path", help="KernelBench 风格的 golden 实现（含 class Model）")
    ap.add_argument("--init-args", nargs="*", default=None,
                    help="Model 构造参数，形如 num_channels=4 alpha=0.25")
    ap.add_argument("--input-shape", default=None,
                    help="运行探测用的输入 shape，形如 2,4,8")
    ap.add_argument("--input-dtype", default="float32")
    args = ap.parse_args()

    try:
        src = open(args.golden_path, encoding="utf-8").read()
        tree = ast.parse(src)
    except (OSError, SyntaxError) as e:
        print(json.dumps({"error": f"{type(e).__name__}: {e}",
                          "path": args.golden_path}, ensure_ascii=False, indent=2))
        return 1

    v = ModelVisitor()
    v.visit(tree)
    if not v.found:
        print(json.dumps({"error": "未找到 class Model(nn.Module)",
                          "path": args.golden_path}, ensure_ascii=False, indent=2))
        return 1

    snake, pascal = suggest_name(v.op_sequence, v.stateful)
    hints = infer_hints(v.op_sequence, v.forward_args, v.stateful)
    tensor_inputs = collect_tensor_inputs(v.forward_args, v.stateful)

    input_shape = None
    if args.input_shape:
        input_shape = [int(x) for x in args.input_shape.split(",") if x.strip()]
    init_args = parse_init_args(args.init_args)

    out = {
        "path": args.golden_path,
        "source_id": re.sub(r"\.py$", "", args.golden_path.split("/")[-1]),
        "forward_args": v.forward_args,
        "init_args": [{"name": n, "default": d} for n, d in v.init_args],
        "stateful": v.stateful,
        "op_sequence": v.op_sequence,
        "clean_ops": _clean_ops(v.op_sequence),
        "has_inplace_index": v.has_inplace_index,
        "n_return": v.n_return,
        "tensor_inputs": tensor_inputs,
        "suggested_name": {"snake": snake, "pascal": pascal,
                           "note": "按算子组合描述；desc.md §1 应记原文件编号 "
                                   f"{re.sub(r'.py$', '', args.golden_path.split('/')[-1])} 作溯源"},
        "hints": hints,
        "run_probe": run_probe(args.golden_path, init_args, input_shape, args.input_dtype),
        "guidance": "把 Model.forward 转写成可导入的自由函数 golden.py："
                    "forward 形参与所有 param/权重张量都作为函数入参（张量入参在前、"
                    "标量 attr 在后）；保持算子顺序；in-place 下标赋值前先 .clone()；"
                    "reduction/exp 类升 fp32 计算再降回。其余四文件对齐该函数。"
                    "详见 references/golden-driven.md。",
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
